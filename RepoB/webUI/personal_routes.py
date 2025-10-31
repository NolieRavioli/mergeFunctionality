# webUI/update_personal_routes.py

from flask import Blueprint, redirect, url_for, session
import logging

# Private fetchers
from esi.personal_industry_jobs import fetch_all_industry
from esi.personal_skills import fetch_all_skills
from esi.personal_assets import fetch_all_assets
from esi.personal_bookmarks import update_personal_bookmarks
from esi.personal_wallet import fetch_all_wallets


# ──────── Setup ──────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
update_personal_bp = Blueprint('update_personal', __name__, url_prefix="/update_personal")

# ──────── Private Data Update Endpoints ───────────────────────────────────────

@update_personal_bp.route("/assets")
def update_assets():
    """Trigger a refresh of personal assets."""

    owner_id = session.get("owner_id")
    if not owner_id:
        return "Unauthorized", 401
    fetch_all_assets(owner_id)
    logger.info(f"[UpdatePersonal] Fetched assets for owner {owner_id}")
    return redirect(url_for("dashboard.home"))

@update_personal_bp.route("/industry")
def update_industry():
    """Trigger a refresh of personal industry jobs."""

    owner_id = session.get("owner_id")
    if not owner_id:
        return "Unauthorized", 401
    fetch_all_industry(owner_id)
    logger.info(f"[UpdatePersonal] Fetched industry jobs for owner {owner_id}")
    return redirect(url_for("dashboard.home"))

@update_personal_bp.route("/wallet")
def update_wallet():
    """Trigger a refresh of personal wallet transactions."""
    owner_id = session.get("owner_id")
    if not owner_id:
        return "Unauthorized", 401
    fetch_all_wallets(owner_id)
    logger.info(f"[UpdatePersonal] Fetched wallet transactions for owner {owner_id}")
    return redirect(url_for("dashboard.home"))

@update_personal_bp.route("/skills")
def update_skills():
    """Trigger a refresh of personal skills."""
    owner_id = session.get("owner_id")
    if not owner_id:
        return "Unauthorized", 401
    fetch_all_skills(owner_id)
    logger.info(f"[UpdatePersonal] Fetched skills for owner {owner_id}")
    return redirect(url_for("dashboard.home"))

@update_personal_bp.route("/bookmarks")
def update_bookmarks():
    """Trigger a refresh of personal bookmarks."""
    owner_id = session.get("owner_id")
    if not owner_id:
        return "Unauthorized", 401
    update_personal_bookmarks(owner_id)
    logger.info(f"[UpdatePersonal] Fetched bookmarks for owner {owner_id}")
    return redirect(url_for("dashboard.home"))
