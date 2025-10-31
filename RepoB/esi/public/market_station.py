# esi/public/market_station.py

import logging
import time
from datetime import datetime

import requests

from db.database import get_public_session
from db.models import MarketOrder
from util.utils import get_all_region_ids
from util.esi_rate_limiter import esi_get

logger = logging.getLogger(__name__)

ESI_BASE = "https://esi.evetech.net/latest"
HEADERS = {"Accept": "application/json"}

# ──────── Fetching ─────────────────────────────────────────────────────────────

def fetch_with_retries(url: str, params: dict, max_retries: int = 3) -> requests.Response:
    """
    Fetch a URL with basic retry/backoff logic for ESI error codes.
    """
    backoff = 1
    for attempt in range(1, max_retries + 1):
        try:
            resp = esi_get(url, headers=HEADERS, params=params)
            if resp.status_code == 420:
                logger.warning(f"420 rate limit on {url}, sleeping 5s (attempt {attempt})")
                time.sleep(5)
                continue
            if resp.status_code in (429, 502, 503, 504):
                logger.warning(f"{resp.status_code} on {url}, retrying after {backoff}s (attempt {attempt})")
                time.sleep(backoff)
                backoff *= 2
                continue
            return resp
        except requests.RequestException as e:
            logger.warning(f"Request error on {url} (attempt {attempt}): {e}")
            time.sleep(backoff)
            backoff *= 2
    return esi_get(url, headers=HEADERS, params=params)

def fetch_market_orders(region_id: int, page: int = 1) -> tuple[list, int]:
    """
    Fetch a single page of market orders for a region with retries.
    Returns (data, total_pages).
    """
    url = f"{ESI_BASE}/markets/{region_id}/orders/"
    params = {"order_type": "all", "page": page, "datasource": "tranquility"}
    resp = fetch_with_retries(url, params)

    if resp.status_code in (400, 403, 404):
        logger.warning(f"Bad response {resp.status_code} for region {region_id}, page {page}")
        return [], 0

    resp.raise_for_status()
    return resp.json(), int(resp.headers.get("X-Pages", 1))

# ──────── Storage ───────────────────────────────────────────────────────────────

def save_orders_to_db(region_id: int, orders: list[dict]) -> None:
    """
    Save a list of market orders to the database for the given region.
    """
    logger.debug(f"Saving {len(orders)} orders for region {region_id}")
    with get_public_session() as db:
        for order in orders:
            db_order = MarketOrder(
                order_id=order["order_id"],
                region_id=region_id,
                type_id=order["type_id"],
                price=order["price"],
                volume_remain=order["volume_remain"],
                volume_total=order.get("volume_total", 0),
                min_volume=order.get("min_volume", 1),
                is_buy_order=order["is_buy_order"],
                location_id=order["location_id"],
                duration=order.get("duration", 0),
                issued=datetime.strptime(order["issued"], "%Y-%m-%dT%H:%M:%SZ") if "issued" in order else None,
                order_range=order.get("range", "region"),
                last_seen=datetime.utcnow(),
            )
            db.merge(db_order)
        db.commit()


# ──────── Orchestrator ───────────────────────────────────────────────────────────

def fetch_all_market_data() -> None:
    """
    Fetch and store all market orders from all EVE regions.
    """
    region_ids = get_all_region_ids()
    logger.info(f"Found {len(region_ids)} regions to process")

    for region_id in region_ids:
        logger.info(f"=== Fetching region {region_id} ===")
        try:
            first_page, total_pages = fetch_market_orders(region_id, page=1)
            if not first_page:
                logger.info(f"No market data for region {region_id}")
                continue

            save_orders_to_db(region_id, first_page)

            for page in range(2, total_pages + 1):
                time.sleep(0.033)  # ESI rate limit avoidance
                page_data, _ = fetch_market_orders(region_id, page)
                if not page_data:
                    break
                save_orders_to_db(region_id, page_data)

                if total_pages < 50 or page % 7 == 0:
                    logger.info(f"Region {region_id}: {100 * page / total_pages:.2f}% complete")

        except Exception as e:
            logger.error(f"Failed fetching market data for region {region_id}: {e}")

    logger.info("Completed fetch of all market data")
