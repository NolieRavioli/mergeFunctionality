# fetchers/private/personal_assets.py

import logging
import requests

from util.utils import get_token
from db.database import get_private_session
from db.models import Asset
from util.esi_rate_limiter import esi_get

logger = logging.getLogger(__name__)

ESI = "https://esi.evetech.net/latest"

# ──────── Fetching ─────────────────────────────────────────────────────────────

def fetch_assets(char_id: int, access_token: str) -> list:
    """Fetch all assets for a character using ESI."""
    assets = []
    page = 1
    headers = {"Authorization": f"Bearer {access_token}"}

    while True:
        url = f"{ESI}/characters/{char_id}/assets/"
        resp = esi_get(url, headers=headers, params={"page": page})
        resp.raise_for_status()

        data = resp.json()
        assets.extend(data)

        if "x-pages" in resp.headers:
            total_pages = int(resp.headers["x-pages"])
            if page >= total_pages:
                break
            page += 1
        else:
            break

    return assets

# ──────── Storage ───────────────────────────────────────────────────────────────

def store_assets(owner_id: int, char_id: int, assets: list):
    """Store assets into owner's private database."""
    db = get_private_session(owner_id)

    db.query(Asset).filter_by(character_id=char_id).delete()

    for asset in assets:
        db.add(Asset(
            item_id=asset["item_id"],
            character_id=char_id,
            type_id=asset["type_id"],
            location_id=asset["location_id"],
            quantity=asset.get("quantity", 1),
            location_flag=asset.get("location_flag", None),
        ))

    db.commit()
    db.close()

# ──────── Orchestrator ───────────────────────────────────────────────────────────

def fetch_all_assets(owner_id: int):
    """Fetch and store assets for all characters owned by this owner."""
    tokens = get_token(owner_id)

    for char_id, token_row in tokens.items():
        logger.info(f"[fetch_all_assets] Fetching assets for character {char_id}")
        try:
            assets = fetch_assets(char_id, token_row["access_token"])
            store_assets(owner_id, char_id, assets)
            logger.info(f"[fetch_all_assets] Stored {len(assets)} assets for {char_id}")
        except requests.HTTPError as e:
            logger.error(f"[fetch_all_assets] Failed fetching assets for {char_id}: {e}")
