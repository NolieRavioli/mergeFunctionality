# fetchers/private/personal_skills.py

import logging
import requests
from datetime import datetime

from db.database import get_private_session
from db.models import Skill, SkillQueue
from util.utils import get_token
from util.auth import TokenDBManager
from util.esi_rate_limiter import esi_get

logger = logging.getLogger(__name__)

ESI = "https://esi.evetech.net/latest"

# ──────── Fetching ─────────────────────────────────────────────────────────────

def fetch_skills(char_id: int, access_token: str) -> list[dict]:
    """Fetch all skills for a character."""
    url = f"{ESI}/characters/{char_id}/skills/"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = esi_get(url, headers=headers)
    resp.raise_for_status()
    return resp.json().get("skills", [])

def fetch_skillqueue(char_id: int, access_token: str) -> list[dict]:
    """Fetch skill queue for a character."""
    url = f"{ESI}/characters/{char_id}/skillqueue/"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = esi_get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

# ──────── Storage ───────────────────────────────────────────────────────────────

def store_skill_data(owner_id: int, char_id: int,
                     raw_skills: list[dict], queue: list[dict]) -> None:
    """
    Replace all existing Skill and SkillQueue rows for this character
    with the latest data from raw_skills and queue.
    """
    session = get_private_session(owner_id)  # returns a new Session for this owner :contentReference[oaicite:0]{index=0}&#8203;:contentReference[oaicite:1]{index=1}
    try:
        # clear out old data
        session.query(Skill).filter_by(character_id=char_id).delete()
        session.query(SkillQueue).filter_by(character_id=char_id).delete()

        # insert fresh Skill rows
        for sk in raw_skills:
            session.add(Skill(
                character_id         = char_id,
                skill_id             = sk["skill_id"],
                active_level         = sk["active_skill_level"],
                skillpoints_in_skill = sk["skillpoints_in_skill"],
                trained_skill_level  = sk["trained_skill_level"],
                skill_active         = sk.get("active", True),
            ))

        # insert fresh SkillQueue rows
        for entry in queue:
            finish_date = None
            if entry.get("finish_date"):
                finish_date = datetime.fromisoformat(
                    entry["finish_date"].replace("Z", "+00:00")
                )

            session.add(SkillQueue(
                character_id  = char_id,
                queue_position= entry["queue_position"],
                skill_id      = entry["skill_id"],
                finish_level  = entry["finished_level"],
                finish_date   = finish_date,
            ))

        session.commit()
        logger.info(
            f"[fetch_skills] Owner {owner_id} / Character {char_id}: "
            f"stored {len(raw_skills)} skills and {len(queue)} queue entries"
        )
    except Exception:
        session.rollback()
        logger.exception(
            f"[fetch_skills] Owner {owner_id} / Character {char_id}: failed to store skill data"
        )
        raise
    finally:
        session.close()

# ──────── Orchestrator ───────────────────────────────────────────────────────────

def fetch_all_skills(owner_id: int) -> None:
    """
    Fetch and store skills for each character this owner has tokens for.
    Continues on error per-character.
    """
    tokens = get_token(owner_id)
    for char_id, token_row in tokens.items():
        logger.info(f"[fetch_all_skills] Fetching skills for {char_id}")
        try:
            raw_skills = fetch_skills(char_id, token_row["access_token"])
            queue      = fetch_skillqueue(char_id, token_row["access_token"])
            store_skill_data(owner_id, char_id, raw_skills, queue)
        except requests.HTTPError as e:
            logger.error(f"[fetch_all_skills] HTTP error for {char_id}: {e}")
        except Exception as e:
            logger.error(f"[fetch_all_skills] Unexpected error for {char_id}: {e}")
