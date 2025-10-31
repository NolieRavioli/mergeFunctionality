# analysis/job_slots.py

import logging
from datetime import datetime, timezone
from db.database import get_private_session
from db.models import IndustryJob, Skill, Character
from util.utils import get_token

logger = logging.getLogger(__name__)

SCIENCE_ACTIVITY_IDS = {3, 4, 5, 7, 8}
MASS_PRODUCTION_ID = 3387
ADV_MASS_PRODUCTION_ID = 24625
LAB_OPERATION_ID = 3406
ADV_LAB_OPERATION_ID = 24624

def get_industry_queues(owner_id: int, character_id: int) -> dict:
    """
    Return the max manufacturing and science job slots based on accurate in-game usable skill levels.
    Format: { "manuf": int, "science": int }
    """
    with get_private_session(owner_id) as db:
        skills = {
            s.skill_id: s.trained_skill_level
            for s in db.query(Skill).filter_by(character_id=character_id)
        }

        logger.debug(f"[Skills] Usable skills for {character_id}: {skills}")

        manuf_slots = 1 + skills.get(MASS_PRODUCTION_ID, 0) + skills.get(ADV_MASS_PRODUCTION_ID, 0)
        science_slots = 1 + skills.get(LAB_OPERATION_ID, 0) + skills.get(ADV_LAB_OPERATION_ID, 0)

        return {
            "manuf": manuf_slots,
            "science": science_slots,
        }


def analyze_slots(owner_id: int) -> list[str]:
    """Analyze active industry jobs and slot usage for all toons owned by owner_id."""
    now = datetime.now(timezone.utc)
    status_list = []
    token_map = get_token(owner_id)

    with get_private_session(owner_id) as db:
        for char_id in token_map.keys():
            jobs = db.query(IndustryJob).filter_by(character_id=char_id).all()
            queues = get_industry_queues(owner_id, char_id)
            name = db.query(Character).filter_by(character_id=char_id).first().name

            def to_utc_aware(dt):
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

            manuf_jobs = [j for j in jobs if j.activity_id == 1 and to_utc_aware(j.end_date) > now]
            science_jobs = [j for j in jobs if j.activity_id in SCIENCE_ACTIVITY_IDS and to_utc_aware(j.end_date) > now]

            def summarize(job_list, max_slots, label):
                used = len(job_list)
                if used < max_slots:
                    msg = f"{name} — OPEN {label.upper()} SLOTS ({used}/{max_slots})"
                    logger.info(msg)
                    status_list.append(msg)
                else:
                    soonest = min(to_utc_aware(j.end_date) for j in job_list)
                    remaining = soonest - now
                    hours, remainder = divmod(remaining.total_seconds(), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    msg = (
                        f"{name} — All {label} slots filled ({used}/{max_slots}), "
                        f"{int(hours)} hr {int(minutes)} min {int(seconds)} sec until next opening."
                    )
                    logger.info(msg)
                    status_list.append(msg)

            summarize(manuf_jobs, queues.get("manuf", 0), "manufacturing")
            summarize(science_jobs, queues.get("science", 0), "science")

    return status_list
