# esi/public/market_contracts.py

import logging
from datetime import datetime
import requests

from db.database import get_public_session
from db.models import PublicContract
from util.utils import get_all_region_ids
from util.esi_rate_limiter import esi_get

# ──────── Globals ───────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
ESI = "https://esi.evetech.net/latest"

# ──────── Fetching ──────────────────────────────────────────────────────────────

def fetch_public_contracts(region_id: int) -> list[dict]:
    """Fetch all public contracts in a region, handling pagination."""
    all_contracts = []
    page = 1
    url = f"{ESI}/contracts/public/{region_id}/"

    while True:
        resp = esi_get(url, params={"page": page})
        if resp.status_code == 204:
            logger.info(f"[Contracts] Region {region_id}: no contracts (204) on page {page}")
            break

        resp.raise_for_status()
        page_data = resp.json()

        if not page_data:
            logger.info(f"[Contracts] Region {region_id}: empty page {page}, stopping early")
            break

        all_contracts.extend(page_data)
        total_pages = int(resp.headers.get("X-Pages", page))

        logger.info(f"[Contracts] Region {region_id}: fetched page {page}/{total_pages}")

        if page >= total_pages:
            break
        page += 1

    return all_contracts

# ──────── Storage ───────────────────────────────────────────────────────────────

def store_contracts(region_id: int, contracts: list[dict]) -> None:
    """Merge a list of contract dicts into the database."""
    session = get_public_session()
    try:
        for c in contracts:
            # parse issued date
            issued = datetime.fromisoformat(c["date_issued"].replace("Z", "+00:00"))
            # parse expired date if present
            expired = None
            if c.get("date_expired"):
                expired = datetime.fromisoformat(c["date_expired"].replace("Z", "+00:00"))

            obj = PublicContract(
                contract_id            = c["contract_id"],
                region_id              = region_id,
                issuer_id              = c.get("issuer_id"),
                issuer_corporation_id  = c.get("issuer_corporation_id"),
                contract_type          = c["type"],
                date_issued            = issued,
                date_expired           = expired,
                title                  = c.get("title"),
                volume                 = c.get("volume", 0.0),
                price                  = c.get("price", 0.0),
                buyout                 = c.get("buyout"),
                collateral             = c.get("collateral"),
                reward                 = c.get("reward"),
                days_to_complete       = c.get("days_to_complete"),
                start_location_id      = c.get("start_location_id"),
                end_location_id        = c.get("end_location_id"),
                for_corporation        = c.get("for_corporation", False),
            )

            session.merge(obj)

        session.commit()
        logger.info(f"[Contracts] Region {region_id}: stored {len(contracts)} contracts")
    except Exception:
        session.rollback()
        logger.exception(f"[Contracts] Region {region_id}: failed to store contracts")
        raise
    finally:
        session.close()

# ──────── Orchestration ──────────────────────────────────────────────────────────

def fetch_all_public_contracts() -> None:
    """Fetch and store public contracts for every EVE region."""
    logger.info("[Contracts] Starting full public contracts fetch")
    region_ids = get_all_region_ids()

    for region_id in region_ids:
        try:
            logger.info(f"[Contracts] === Region {region_id} ===")
            contracts = fetch_public_contracts(region_id)
            if contracts:
                store_contracts(region_id, contracts)
        except Exception as e:
            logger.exception(f"[Contracts] Failed fetching region {region_id}: {e}")

    logger.info("[Contracts] Completed fetching all public contracts")
