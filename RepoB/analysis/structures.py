# analysis/structures.py

import logging
import os
import time
from flask import session
from typing import Optional
from datetime import datetime
import requests

from util.utils import get_token, batched
from util.sde import region_id_from_system_id
from util.esi_rate_limiter import esi_request
from db.database import get_private_session, get_public_session
from db.models import Structure, Asset, IndustryJob, Character

logger = logging.getLogger(__name__)

ESI_BASE = "https://esi.evetech.net/latest"
DATASOURCE = {"datasource": "tranquility"}
INT32_MAX = 2_147_483_647
_system_name_cache = {}

def safe_request(method, url, max_retries=5, backoff_factor=2, **kwargs):
    delay = 1
    for attempt in range(1, max_retries + 1):
        try:
            kwargs.setdefault("timeout", 30)
            resp = esi_request(method, url, **kwargs)
            if resp.status_code == 420:
                logger.warning(f"[RateLimit] 420 on {url}, sleeping 7s (attempt {attempt})")
                time.sleep(7)
                continue
            if resp.status_code == 403:
                logger.warning(f"[Forbidden] 403 on {url}, skipping.")
                return None
            if resp.status_code == 401:
                logger.warning(f"[Unauthorized] 401 on {url}, skipping retries.")
                return None
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            logger.warning(f"[HTTP Error] {e} on {url} (attempt {attempt})")
            if attempt == max_retries:
                logger.error(f"[FAILED] Max retries reached for {url}")
                return None
            time.sleep(delay)
            delay *= backoff_factor

def fetch_structure_info(structure_id: int, token: str) -> Optional[dict]:
    url = f"{ESI_BASE}/universe/structures/{structure_id}/"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    resp = safe_request("GET", url, headers=headers, params=DATASOURCE)
    if resp:
        try:
            return resp.json()
        except Exception as e:
            logger.warning(f"[StructInfo] JSON parse failed for {structure_id}: {e}")
    return None

def discover_private_structure_ids(owner_id: int) -> set[int]:
    ids = set()
    with get_private_session(owner_id) as session:
        for (loc,) in session.query(Asset.location_id).distinct():
            if loc and loc > INT32_MAX:
                ids.add(loc)
        for (loc,) in session.query(IndustryJob.facility_id).distinct():
            if loc and loc > INT32_MAX:
                ids.add(loc)
        for (loc,) in session.query(IndustryJob.output_location_id).distinct():
            if loc and loc > INT32_MAX:
                ids.add(loc)
    logger.info(f"[StructIDs] Owner {owner_id} private IDs: {len(ids)}")
    return ids

def fetch_public_structures() -> set[int]:
    """
    Returns the set of *all* currently known public structure IDs.
    """
    url = f"{ESI_BASE}/universe/structures/"
    resp = safe_request("GET", url, params=DATASOURCE, headers={"Accept": "application/json"})
    if not resp:
        return set()
    try:
        return set(resp.json())
    except Exception as e:
        logger.error(f"[Discovery] Failed parsing public structures list: {e}")
        return set()

def fetch_owned_structures(owner_id: int) -> set[int]:
    """
    Finds all structures in sov systems friendly to this owner.
    """
    structure_ids = set()
    _system_name_cache.clear()
    main_char_id = owner_id

    # --- grab a fresh token for this character ---
    tokens = get_token(owner_id)
    token_data = tokens.get(main_char_id) or {}
    if token_data.get("expires_at", 0) < time.time():
        logger.info(f"[TokenRefresh] Expired for {main_char_id}, refreshing…")
        tokens = get_token(owner_id)
        token_data = tokens.get(main_char_id) or {}
    access_token = token_data.get("access_token")
    if not access_token:
        logger.warning(f"[StructScan] No token for character {main_char_id}")
        return structure_ids

    corp_id = token_data.get("corporation_id")
    alliance_id = token_data.get("alliance_id")
    logger.info(f"[StructScan] Starting sov scan for char {main_char_id}, corp {corp_id}, alliance {alliance_id}")

    # --- build friendly lists via contacts ---
    friendly_corp_ids = set()
    friendly_alliance_ids = set()

    if corp_id:
        resp = safe_request(
            "GET",
            f"{ESI_BASE}/corporations/{corp_id}/contacts/",
            headers={"Authorization": f"Bearer {access_token}"},
            params=DATASOURCE
        )
        if resp:
            for c in resp.json():
                if c.get("standing", 0) > 0:
                    if c["contact_type"] == "corporation":
                        friendly_corp_ids.add(c["contact_id"])
                    elif c["contact_type"] == "alliance":
                        friendly_alliance_ids.add(c["contact_id"])

    if alliance_id:
        resp = safe_request(
            "GET",
            f"{ESI_BASE}/alliances/{alliance_id}/contacts/",
            headers={"Authorization": f"Bearer {access_token}"},
            params=DATASOURCE
        )
        if resp:
            for c in resp.json():
                if c.get("standing", 0) > 0:
                    if c["contact_type"] == "corporation":
                        friendly_corp_ids.add(c["contact_id"])
                    elif c["contact_type"] == "alliance":
                        friendly_alliance_ids.add(c["contact_id"])

    if not friendly_corp_ids and corp_id:
        logger.info("[StructScan] No friendly corps; using own corp.")
        friendly_corp_ids.add(corp_id)
    if not friendly_alliance_ids and alliance_id:
        logger.info("[StructScan] No friendly alliances; using own alliance.")
        friendly_alliance_ids.add(alliance_id)

    # --- fetch sov map and filter relevant systems ---
    sov_resp = safe_request("GET", f"{ESI_BASE}/sovereignty/map/", params=DATASOURCE)
    if not sov_resp:
        logger.error("[StructScan] Failed to fetch sovereignty map.")
        return structure_ids

    sov_map = sov_resp.json()
    sov_systems = {
        entry["system_id"]
        for entry in sov_map
        if entry.get("corporation_id") in friendly_corp_ids
        or entry.get("alliance_id") in friendly_alliance_ids
    }
    logger.info(f"[StructScan] Found {len(sov_systems)} friendly sov systems")

    # --- resolve system names in batches ---
    for batch in batched(list(sov_systems), 1000):
        name_resp = safe_request(
            "POST",
            f"{ESI_BASE}/universe/names/",
            json=batch,
            headers={"Accept": "application/json"}
        )
        if name_resp:
            for entry in name_resp.json():
                if entry["category"] == "solar_system":
                    _system_name_cache[entry["id"]] = entry["name"]

    # --- for each system, run the `/search` endpoint ---
    total = len(sov_systems)
    t0 = time.time()
    for idx, sid in enumerate(sov_systems, start=1):
        system_name = _system_name_cache.get(sid)
        if not system_name:
            continue

        search_resp = safe_request(
            "GET",
            f"{ESI_BASE}/characters/{main_char_id}/search/",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"categories": "structure", "search": f"{system_name} - ", "strict": "false"}
        )
        if search_resp:
            structure_ids.update(search_resp.json().get("structure", []))

        if idx % max(1, total // 500) == 0:
            elapsed = time.time() - t0
            eta = (elapsed / idx) * (total - idx)
            logger.info(f"[StructSearch] {100*idx/total:.1f}% done. ETA {eta:.1f}s")

    logger.info(f"[StructScan] Found {len(structure_ids)} structures in friendly sov")
    return structure_ids

def discover_all_structures() -> list[int]:
    """
    1) Pull every public structure ID once
    2) Add each owner's private + friendly sov IDs
    3) Seed public DB, then enrich metadata per owner
    """
    from util.utils import PRIVATE_DATA_FOLDER

    # --- find all owner folders ---
    owner_ids = [
        int(d) for d in os.listdir(PRIVATE_DATA_FOLDER)
        if d.isdigit() and os.path.isdir(os.path.join(PRIVATE_DATA_FOLDER, d))
    ]
    logger.info(f"[Discovery] Found {len(owner_ids)} owners.")

    # --- 1) universe-wide public structures ---
    try:
        public_ids = fetch_public_structures()
        logger.info(f"[Discovery] Pulled {len(public_ids)} public structures from /universe/structures/")
    except Exception as e:
        logger.error(f"[Discovery] Could not fetch public structures: {e}")
        public_ids = set()

    structure_ids = set(public_ids)

    # --- 2) per-owner private + sov structures ---
    for owner_id in owner_ids:
        try:
            pvt = discover_private_structure_ids(owner_id)
            sov = fetch_owned_structures(owner_id)
            structure_ids |= (pvt | sov)
        except Exception as e:
            logger.warning(f"[Discovery] Skipped owner {owner_id} due to: {e}")

    logger.info(f"[Discovery] Total unique structure IDs: {len(structure_ids)}")
    remaining_ids = set(structure_ids)

    # --- write to public DB ---
    with get_public_session() as db:
        for sid in sorted(structure_ids):
            db.merge(Structure(structure_id=sid, last_seen=datetime.utcnow()))
        db.commit()

    # --- enrich metadata ---
    enriched = []
    total = len(structure_ids)
    count = 0
    t0 = time.time()

    for owner_id in owner_ids:
        try:
            # get the character row for name/credentials
            with get_private_session(owner_id) as pvt:
                main_char = pvt.query(Character).filter_by(character_id=owner_id).first()
            tokens = get_token(owner_id)
            token_candidates = [
                data for _, data in sorted(tokens.items()) if data.get("access_token")
            ]
            if not token_candidates:
                logger.warning(f"[Enrich] No usable tokens for owner {owner_id}")
                continue

            if not remaining_ids:
                break

            for sid in list(sorted(remaining_ids)):
                count += 1
                info = None
                for token_data in token_candidates:
                    access_token = token_data.get("access_token")
                    if not access_token:
                        continue
                    info = fetch_structure_info(sid, access_token)
                    if info:
                        break
                if info:
                    solar_system_id = info.get("solar_system_id")
                    region_id = region_id_from_system_id(solar_system_id) if solar_system_id else None
                    with get_public_session() as db:
                        db.merge(Structure(
                            structure_id=sid,
                            name=info.get("name"),
                            solar_system_id=solar_system_id,
                            region_id=region_id,
                            owner_id=info.get("owner_id"),
                            type_id=info.get("type_id"),
                            last_seen=datetime.utcnow(),
                        ))
                        db.commit()
                        enriched.append(sid)
                        remaining_ids.discard(sid)

                if count % max(1, total // 1000) == 0:
                    elapsed = time.time() - t0
                    eta = (elapsed / count) * (total - count)
                    logger.info(f"[Enrich] {100*count/total:.1f}% done. ETA {eta:.1f}s")

        except Exception as e:
            logger.warning(f"[Enrich] Failed for owner {owner_id}: {e}")

    if remaining_ids:
        with get_public_session() as db:
            for sid in sorted(remaining_ids):
                struct = db.get(Structure, sid)
                if struct and struct.solar_system_id and not struct.region_id:
                    struct.region_id = region_id_from_system_id(struct.solar_system_id)
                    struct.last_seen = datetime.utcnow()
            db.commit()

    logger.info(f"[Discovery] Enriched metadata for {len(enriched)} structures.")
    return enriched
