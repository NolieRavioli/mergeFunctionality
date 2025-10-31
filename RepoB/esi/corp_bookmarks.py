import logging
import requests

from datetime import datetime
from util.utils import get_token
from db.database import get_private_session
from db.models import CorpBookmark
from util.esi_rate_limiter import esi_get

logger = logging.getLogger(__name__)

ESI = "https://esi.evetech.net/latest"

# ──────── Fetching ─────────────────────────────────────────────────────────────

def fetch_corp_bookmarks(char_id: int, token: str) -> list:
    """Fetch corporation bookmarks using a character's access token."""
    url = f"{ESI}/characters/{char_id}/bookmarks/"
    headers = {"Authorization": f"Bearer {token}"}
    resp = esi_get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

# ──────── Storage ───────────────────────────────────────────────────────────────

def store_corp_bookmarks(owner_id: int, char_id: int, bookmarks: list):
    """Store corporation bookmarks into the owner's private DB."""
    db = get_private_session(owner_id)

    for bm in bookmarks:
        db.merge(CorpBookmark(
            bookmark_id     = bm["bookmark_id"],
            character_id    = char_id,
            created         = datetime.fromisoformat(bm["created"].replace("Z", "+00:00")),
            creator_id      = bm["creator_id"],
            label           = bm.get("label", ""),
            location_id     = bm["location_id"],
            notes           = bm.get("notes", ""),
            x               = bm.get("coordinates", {}).get("x"),
            y               = bm.get("coordinates", {}).get("y"),
            z               = bm.get("coordinates", {}).get("z"),
        ))

    db.commit()
    db.close()

# ──────── Orchestrator ───────────────────────────────────────────────────────────

def update_corp_bookmarks(owner_id: int) -> None:
    """Fetch and store corporation bookmarks for all characters owned by the given owner."""
    tokens = get_token(owner_id)
    for char_id, token_row in tokens.items():
        try:
            logger.info(f"[fetch_all_corp_bookmarks] Fetching corp bookmarks for character {char_id}")
            bookmarks = fetch_corp_bookmarks(char_id, token_row.access_token)
            store_corp_bookmarks(owner_id, char_id, bookmarks)
            logger.info(f"[fetch_all_corp_bookmarks] Stored {len(bookmarks)} corp bookmarks for {char_id}")
        except Exception as e:
            logger.error(f"[fetch_all_corp_bookmarks] Error updating corp bookmarks for {char_id}: {e}")
