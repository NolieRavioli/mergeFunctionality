# webUI/dashboard.py

from collections import defaultdict
import logging
from typing import List

from flask import Blueprint, render_template, session

from db.database import get_private_session
from db.models import (
    Asset,
    Character,
    WalletBalance,
    WalletJournal,
    WalletTransaction,
)
from analysis.job_slots import analyze_slots
from util.sde import name_from_type_id
from util.utils import get_portrait, get_runtime_settings

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route("/")
def home():
    """Landing page (dashboard if logged in, basic page if not)."""
    runtime = get_runtime_settings()
    debug_enabled = runtime.debug_mode

    wallet_txns: List[dict] = []
    wallet_journal: List[dict] = []
    assets_summary: List[dict] = []
    slot_status: List[str] = []
    toon_cards: List[dict] = []
    portrait = None
    char_id = None
    owner_id = None
    current_name = None
    wallet_balance = None
    asset_meta = {"total_items": 0, "unique_types": 0}
    linked_toons = {}
    logged_in = False

    if "character_id" in session and "owner_id" in session:
        char_id = session["character_id"]
        owner_id = session["owner_id"]
        logged_in = True

        if debug_enabled:
            print(f"[Dashboard] Loading data for owner={owner_id} character={char_id}")

        logger.info(f"Loading dashboard for character {char_id}, owner {owner_id}")

        priv_db = get_private_session(owner_id)

        try:
            characters = priv_db.query(Character).all()
            for char in characters:
                linked_toons[char.name] = char.character_id
                toon_cards.append({
                    "name": char.name or f"Character {char.character_id}",
                    "id": char.character_id,
                    "portrait_url": f"https://images.evetech.net/characters/{char.character_id}/portrait?tenant=tranquility&size=128",
                })
                if char.character_id == char_id:
                    current_name = char.name or str(char.character_id)

            try:
                portrait = get_portrait(char_id)
                if debug_enabled:
                    print(f"[Dashboard] Portrait payload for {char_id}: {portrait}")
            except Exception as exc:  # pragma: no cover - diagnostic resilience
                logger.warning("Failed to load portrait for %s: %s", char_id, exc)
                if debug_enabled:
                    print(f"[Dashboard] Portrait lookup failed for {char_id}: {exc}")

            balance_row = (
                priv_db
                .query(WalletBalance)
                .filter_by(character_id=char_id)
                .first()
            )
            if balance_row:
                wallet_balance = balance_row.balance

            txn_rows = (
                priv_db
                .query(WalletTransaction)
                .filter_by(character_id=char_id)
                .order_by(WalletTransaction.date.desc())
                .limit(15)
                .all()
            )
            for txn in txn_rows:
                type_name = name_from_type_id(int(txn.type_id)) if txn.type_id else "Unknown"
                wallet_txns.append({
                    "amount": txn.amount or 0.0,
                    "is_buy": txn.is_buy,
                    "quantity": txn.quantity,
                    "type_name": type_name,
                    "unit_price": txn.unit_price or 0.0,
                    "date": txn.date.strftime("%Y-%m-%d %H:%M") if txn.date else "",
                })

            journal_rows = (
                priv_db
                .query(WalletJournal)
                .filter_by(character_id=char_id)
                .order_by(WalletJournal.date.desc())
                .limit(10)
                .all()
            )
            for entry in journal_rows:
                wallet_journal.append({
                    "date": entry.date,
                    "ref_type": entry.ref_type,
                    "amount": entry.amount,
                    "balance": entry.balance,
                    "description": entry.description,
                })

            asset_rows = (
                priv_db
                .query(Asset)
                .filter_by(character_id=char_id)
                .all()
            )
            asset_meta["total_items"] = len(asset_rows)

            summary = defaultdict(lambda: {
                "quantity": 0,
                "stacks": 0,
                "locations": set(),
            })

            for asset in asset_rows:
                bucket = summary[asset.type_id]
                bucket["quantity"] += asset.quantity or 0
                bucket["stacks"] += 1
                location_token = asset.location_flag or asset.location_type or "?"
                bucket["locations"].add(str(location_token))

            asset_meta["unique_types"] = len(summary)

            for type_id, info in summary.items():
                assets_summary.append({
                    "type_id": type_id,
                    "name": name_from_type_id(type_id),
                    "quantity": info["quantity"],
                    "stacks": info["stacks"],
                    "locations": sorted(info["locations"]),
                })

            assets_summary.sort(key=lambda row: row["quantity"], reverse=True)
            assets_summary = assets_summary[:30]

            slot_status = analyze_slots(owner_id)

            if debug_enabled:
                print(f"[Dashboard] Prepared {len(assets_summary)} asset summaries and {len(wallet_txns)} wallet txns")

        finally:
            priv_db.close()

    return render_template(
        "dashboard.html",
        logged_in=logged_in,
        char_id=char_id,
        owner_id=owner_id,
        linked_toons=linked_toons,
        toon_cards=toon_cards,
        portrait=portrait,
        current_name=current_name,
        wallet_balance=wallet_balance,
        wallet_txns=wallet_txns,
        wallet_journal=wallet_journal,
        slot_status=slot_status,
        assets_summary=assets_summary,
        asset_meta=asset_meta,
        runtime=runtime,
    )
