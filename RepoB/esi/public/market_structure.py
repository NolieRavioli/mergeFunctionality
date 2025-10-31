# esi/public/market_structure.py

import logging
import requests
from datetime import datetime
import time
from typing import Optional

from db.database import get_public_session, get_private_session
from db.models import Character, Structure, MarketStructure, MarketOrder
from util.sde import region_id_from_system_id
from util.utils import get_token
from util.esi_rate_limiter import esi_get

logger = logging.getLogger(__name__)

ESI_BASE = "https://esi.evetech.net/latest"
DATASOURCE = {"datasource": "tranquility"}

_STRUCTURE_INFO_CACHE: dict[int, tuple[float, dict]] = {}
_STRUCTURE_INFO_TTL = 24 * 3600  # cache metadata for a day

def fetch_structure_orders(structure_id: int, token: str, page: int = 1, retries: int = 3) -> tuple[list, int]:
    url = f"{ESI_BASE}/markets/structures/{structure_id}/"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    for attempt in range(1, retries + 1):
        try:
            resp = esi_get(url, headers=headers, params={**DATASOURCE, "page": page}, timeout=15)

            if resp.status_code in (403, 404):
                logger.warning(f"[MarketFetch] Skipping {structure_id} page {page}: HTTP {resp.status_code}")
                return [], 1

            if resp.status_code == 420:
                logger.warning(f"[RateLimit] 420 returned for {structure_id}, sleeping 10s")
                time.sleep(10)
                continue

            resp.raise_for_status()
            data = resp.json()
            pages = int(resp.headers.get("x-pages", 1))
            return data, pages

        except requests.exceptions.Timeout:
            logger.warning(f"[Timeout] Attempt {attempt}/{retries} for structure {structure_id} page {page}")
            time.sleep(3 * attempt)
        except Exception as e:
            logger.warning(f"[RetryError] Attempt {attempt}/{retries} for structure {structure_id} page {page}: {e}")
            time.sleep(2 * attempt)

    logger.error(f"[MarketFetch] Failed after {retries} retries for structure {structure_id} page {page}")
    return [], 1


def fetch_structure_details(structure_id: int, token: str) -> Optional[dict]:
    now = time.time()
    cached = _STRUCTURE_INFO_CACHE.get(structure_id)
    if cached and cached[0] > now:
        return cached[1]

    url = f"{ESI_BASE}/universe/structures/{structure_id}/"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    try:
        resp = esi_get(url, headers=headers, params=DATASOURCE, timeout=15)
    except Exception as exc:
        logger.warning(f"[StructMeta] Request failed for {structure_id}: {exc}")
        return None

    if resp.status_code in (403, 404):
        logger.debug(f"[StructMeta] Access denied for {structure_id}: HTTP {resp.status_code}")
        return None

    try:
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"[StructMeta] Failed to parse metadata for {structure_id}: {exc}")
        return None

    _STRUCTURE_INFO_CACHE[structure_id] = (now + _STRUCTURE_INFO_TTL, data)
    return data


def populate_structure_metadata(structure: Structure, token: str, db_session) -> None:
    changed = False

    if not structure.solar_system_id or not structure.name or not structure.type_id or not structure.owner_id:
        info = fetch_structure_details(structure.structure_id, token)
        if info:
            structure.name = info.get("name")
            structure.solar_system_id = info.get("solar_system_id")
            structure.owner_id = info.get("owner_id")
            structure.type_id = info.get("type_id")
            changed = True

    if structure.solar_system_id and not structure.region_id:
        structure.region_id = region_id_from_system_id(structure.solar_system_id)
        changed = True

    if changed:
        structure.last_seen = datetime.utcnow()
        db_session.flush()


def update_structure_market_orders() -> None:
    from os import listdir
    from os.path import isdir, join
    from util.utils import PRIVATE_DATA_FOLDER

    owner_ids = [
        int(name) for name in listdir(PRIVATE_DATA_FOLDER)
        if name.isdigit() and isdir(join(PRIVATE_DATA_FOLDER, name))
    ]

    if not owner_ids:
        logger.error("[MarketUpdate] No private owner directories found.")
        return

    owner_id = min(owner_ids)
    tokens = get_token(owner_id)
    char_id, token_data = sorted(tokens.items())[0]
    token = token_data["access_token"]

    with get_public_session() as db:
        structures = db.query(Structure).all()
        logger.info(f"[MarketUpdate] Checking {len(structures)} structures.")
        total = len(structures)
        count = 0
        t0 = time.time()
        for s in structures:
            count += 1
            num_orders = 0
            try:
                tokens = get_token(owner_id)
                char_id, token_data = sorted(tokens.items())[0]
                if token_data.get("expires_at") and token_data["expires_at"] < time.time():
                    logger.info(f"[TokenRefresh] Token expired for {char_id}, refreshing...")
                    tokens = get_token(owner_id)
                    token_data = tokens.get(char_id)
                token = token_data["access_token"]

                populate_structure_metadata(s, token, db)

                db.merge(MarketStructure(
                    structure_id=s.structure_id,
                    solar_system_id=s.solar_system_id,
                    region_id=s.region_id,
                    owner_id=s.owner_id,
                    name=s.name,
                    type_id=s.type_id,
                    position=s.position,
                    last_seen=datetime.utcnow()
                ))

                orders, pages = fetch_structure_orders(s.structure_id, token, page=1)
                if not orders:
                    db.commit()
                    logger.info(f"{100*count/total:.2f}% done. ETA: {(time.time()-t0)*(1-count/total)/(count/total)}")
                    continue

                for o in orders:
                    num_orders += 1
                    db.merge(MarketOrder(
                        order_id=o["order_id"],
                        region_id=s.region_id,
                        type_id=o["type_id"],
                        price=o["price"],
                        volume_remain=o.get("volume_remain", 0),
                        volume_total=o.get("volume_total", 0),
                        min_volume=o.get("min_volume", 1),
                        is_buy_order=o.get("is_buy_order", False),
                        location_id=s.structure_id,
                        duration=o.get("duration", 0),
                        issued=datetime.strptime(o["issued"], "%Y-%m-%dT%H:%M:%SZ"),
                        order_range=o.get("range", "region"),
                        last_seen=datetime.utcnow()
                    ))
                
                
                for page in range(2, pages + 1):
                    tokens = get_token(owner_id)
                    char_id, token_data = sorted(tokens.items())[0]
                    if token_data.get("expires_at") and token_data["expires_at"] < time.time():
                        logger.info(f"[TokenRefresh] Token expired during paging for {char_id}, refreshing...")
                        tokens = get_token(owner_id)
                        token_data = tokens.get(char_id)
                    token = token_data["access_token"]

                    more, _ = fetch_structure_orders(s.structure_id, token, page=page)

                    for o in more:
                        num_orders += 1
                        db.merge(MarketOrder(
                            order_id=o["order_id"],
                            region_id=s.region_id,
                            type_id=o["type_id"],
                            price=o["price"],
                            volume_remain=o.get("volume_remain", 0),
                            volume_total=o.get("volume_total", 0),
                            min_volume=o.get("min_volume", 1),
                            is_buy_order=o.get("is_buy_order", False),
                            location_id=s.structure_id,
                            duration=o.get("duration", 0),
                            issued=datetime.strptime(o["issued"], "%Y-%m-%dT%H:%M:%SZ"),
                            order_range=o.get("range", "region"),
                            last_seen=datetime.utcnow()
                        ))

                db.commit()
                logger.info(f"[MarketUpdate] ✅ Synced {num_orders}+ orders for {s.structure_id}.")
                logger.info(f"{100*count/total:.2f}% done. ETA: {(time.time()-t0)*(1-count/total)/(count/total)}")
            
            except Exception:
                logger.exception(f"[MarketUpdate] ❌ Failed for {s.structure_id}.")
                db.rollback()

def update_structure_market(owner_id: int) -> None:
    logger.warning("[Compat] update_structure_market(owner_id) is deprecated, using update_structure_market_orders().")
    update_structure_market_orders()

def fetch_all_structure_markets() -> None:
    logger.warning("[Compat] fetch_all_structure_markets() is deprecated, using update_structure_market_orders().")
    update_structure_market_orders()
