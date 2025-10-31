"""Blueprint and manufacturing list routes."""

from __future__ import annotations

from flask import (Blueprint, redirect, render_template, request, session,
                   url_for, flash)

from analysis.industry import generate_industry_report
from util.settings_store import (
    ManufacturingSettings,
    load_manufacturing_settings,
    save_manufacturing_settings,
    update_settings_from_form,
)

industry_bp = Blueprint("industry", __name__, url_prefix="/industry")


def _current_owner() -> tuple[int | None, int | None]:
    return session.get("owner_id"), session.get("character_id")


@industry_bp.route("/")
def overview():
    owner_id, character_id = _current_owner()
    logged_in = owner_id is not None
    report = None
    settings: ManufacturingSettings | None = None

    if logged_in:
        settings = load_manufacturing_settings(owner_id)
        report = generate_industry_report(owner_id, settings, library_limit=8, plan_limit=6)

    return render_template(
        "industry/dashboard.html",
        logged_in=logged_in,
        character_id=character_id,
        settings=settings,
        report=report,
    )


@industry_bp.route("/library")
def library():
    owner_id, _ = _current_owner()
    if owner_id is None:
        flash("Connect a character to view your blueprint library.")
        return redirect(url_for("industry.overview"))

    settings = load_manufacturing_settings(owner_id)
    report = generate_industry_report(owner_id, settings, library_limit=None, plan_limit=10)

    return render_template(
        "industry/library.html",
        settings=settings,
        report=report,
    )


@industry_bp.route("/manufacturing")
def manufacturing():
    owner_id, _ = _current_owner()
    if owner_id is None:
        flash("Connect a character to view manufacturing recommendations.")
        return redirect(url_for("industry.overview"))

    settings = load_manufacturing_settings(owner_id)
    report = generate_industry_report(owner_id, settings, library_limit=10, plan_limit=None)

    return render_template(
        "industry/manufacturing.html",
        settings=settings,
        report=report,
    )


@industry_bp.route("/settings", methods=["GET", "POST"])
def settings_view():
    owner_id, _ = _current_owner()
    if owner_id is None:
        flash("Connect a character to configure manufacturing settings.")
        return redirect(url_for("industry.overview"))

    settings = load_manufacturing_settings(owner_id)

    if request.method == "POST":
        updated = update_settings_from_form(settings, request.form)
        save_manufacturing_settings(owner_id, updated)
        flash("Manufacturing settings saved.")
        return redirect(url_for("industry.settings_view"))

    report = generate_industry_report(owner_id, settings, library_limit=5, plan_limit=5)

    return render_template(
        "industry/settings.html",
        settings=settings,
        report=report,
    )
