# fetchers/private/personal_industry_jobs.py

import logging
import requests
from datetime import datetime

from util.utils import get_token
from util.auth import TokenDBManager
from db.database import get_private_session
from db.models import IndustryJob
from util.esi_rate_limiter import esi_get

logger = logging.getLogger(__name__)

ESI = "https://esi.evetech.net/latest"

# ──────── Fetching ─────────────────────────────────────────────────────────────

def fetch_industry_jobs(char_id: int, access_token: str) -> list:
    """Fetch active industry jobs for a character."""
    url = f"{ESI}/characters/{char_id}/industry/jobs/"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = esi_get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

# ──────── Storage ───────────────────────────────────────────────────────────────

def store_jobs(owner_id: int, char_id: int, jobs: list[dict]) -> None:
    """
    Merge a list of industry-job dicts into the owner's private DB.
    """
    session = get_private_session(owner_id)  # returns a new Session() for this owner :contentReference[oaicite:0]{index=0}&#8203;:contentReference[oaicite:1]{index=1}
    try:
        for j in jobs:
            # parse ISO timestamps (API gives e.g. "2025-04-29T12:34:56Z")
            start = datetime.fromisoformat(j["start_date"].replace("Z", "+00:00"))
            end = None
            if j.get("end_date"):
                end = datetime.fromisoformat(j["end_date"].replace("Z", "+00:00"))

            job_obj = IndustryJob(
                job_id                  = j["job_id"],
                character_id            = char_id,
                activity_id             = j["activity_id"],
                blueprint_id            = j["blueprint_id"],
                blueprint_location_id   = j["blueprint_location_id"],
                blueprint_type_id       = j["blueprint_type_id"],
                cost                    = j.get("cost", 0.0),
                duration                = j["duration"],
                facility_id             = j["facility_id"],
                installer_id            = j["installer_id"],
                licensed_runs           = j.get("licensed_runs", 0),
                output_location_id      = j["output_location_id"],
                runs                    = j["runs"],
                status                  = j["status"],
                start_date              = start,
                end_date                = end,
            )
            session.merge(job_obj)  # upsert based on primary key :contentReference[oaicite:2]{index=2}&#8203;:contentReference[oaicite:3]{index=3}

        session.commit()
        logger.info(
            f"[IndustryJobs] Owner {owner_id} / Character {char_id}: stored {len(jobs)} jobs"
        )
    except Exception:
        session.rollback()
        logger.exception(
            f"[IndustryJobs] Owner {owner_id} / Character {char_id}: failed to store jobs"
        )
        raise
    finally:
        session.close()

# ──────── Orchestrator ───────────────────────────────────────────────────────────

def fetch_all_industry(owner_id: int):
    """Fetch and store industry jobs for all characters owned by the given owner."""
    tokens = get_token(owner_id)

    for char_id, token_row in tokens.items():
        logger.info(f"Fetching industry jobs for {char_id}")
        try:
            jobs = fetch_industry_jobs(char_id, token_row["access_token"])
            store_jobs(owner_id, char_id, jobs)
            logger.info(f"Stored {len(jobs)} jobs for {char_id}")
        except Exception as e:
            logger.error(f"Failed fetching jobs for {char_id}: {e}")
