# esi/personal_wallet.py

import logging
import requests
from datetime import datetime

from db.database import get_private_session
from db.models import WalletJournal, WalletTransaction, WalletBalance
from util.utils import get_token
from util.esi_rate_limiter import esi_get

logger = logging.getLogger(__name__)

ESI = "https://esi.evetech.net/latest"
DATASOURCE = {"datasource": "tranquility"}


# ──────── Fetching ─────────────────────────────────────────────────────────────

def fetch_wallet_journal(char_id: int, access_token: str) -> list:
    """Fetch wallet journal entries for a character."""
    url = f"{ESI}/characters/{char_id}/wallet/journal/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    resp = esi_get(url, headers=headers, params=DATASOURCE)
    resp.raise_for_status()
    return resp.json()


def fetch_wallet_transactions(char_id: int, access_token: str) -> list:
    """Fetch wallet transaction entries for a character."""
    url = f"{ESI}/characters/{char_id}/wallet/transactions/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    resp = esi_get(url, headers=headers, params=DATASOURCE)
    resp.raise_for_status()
    return resp.json()


def fetch_wallet_balance(char_id: int, access_token: str) -> float:
    """Fetch the primary (division 1) wallet balance for a character."""

    url = f"{ESI}/characters/{char_id}/wallet/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    resp = esi_get(url, headers=headers, params=DATASOURCE)
    resp.raise_for_status()
    payload = resp.json()

    # The endpoint can return a simple number (legacy behaviour) or
    # a list of division objects. Handle both to remain future proof.
    if isinstance(payload, (int, float)):
        return float(payload)

    if isinstance(payload, dict):
        return float(payload.get("balance", 0.0))

    if isinstance(payload, list):
        for entry in payload:
            division = entry if isinstance(entry, dict) else {}
            if division.get("division") == 1:
                return float(division.get("balance", 0.0))
        if payload:
            first = payload[0] if isinstance(payload[0], dict) else {}
            return float(first.get("balance", 0.0))

    logger.warning("[wallet] Unexpected wallet payload for %s: %s", char_id, payload)
    return 0.0


# ──────── Storage ───────────────────────────────────────────────────────────────

def store_wallet_journal(owner_id: int, char_id: int, entries: list):
    """Store journal entries into the owner's private DB."""
    db = get_private_session(owner_id)
    for e in entries:
        jid = e.get("id") or e.get("ref_id")
        db.merge(WalletJournal(
            journal_id      = jid,
            character_id    = char_id,
            date            = e.get("date"),
            description     = e.get("description"),
            ref_type        = e.get("ref_type"),
            amount          = e.get("amount"),
            balance         = e.get("balance"),
            context_id      = e.get("context_id"),
            context_id_type = e.get("context_id_type"),
            first_party_id  = e.get("first_party_id"),
            second_party_id = e.get("second_party_id"),
            reason          = e.get("reason"),
        ))
    db.commit()
    db.close()


def store_wallet_transaction(owner_id: int, char_id: int, txns: list):
    """Store transaction entries into the owner's private DB."""
    db = get_private_session(owner_id)
    for e in txns:
        tid = e.get("transaction_id")
        dt  = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
        db.merge(WalletTransaction(
            transaction_id = tid,
            character_id   = char_id,
            location_id    = e.get("location_id"),
            type_id        = e.get("type_id"),
            quantity       = e.get("quantity"),
            amount         = e.get("amount"),
            unit_price     = e.get("unit_price"),
            date           = dt,
            is_buy         = e.get("is_buy"),
            is_personal    = e.get("is_personal"),
        ))
    db.commit()
    db.close()


def store_wallet_balance(owner_id: int, char_id: int, balance: float):
    """Store the character's wallet balance into the owner's private DB."""
    db = get_private_session(owner_id)
    db.merge(WalletBalance(
        character_id = char_id,
        balance      = balance
    ))
    db.commit()
    db.close()


# ──────── Orchestrator ───────────────────────────────────────────────────────────

def fetch_all_journals(owner_id: int):
    """Fetch & store wallet journals for all characters under this owner."""
    tokens = get_token(owner_id)
    for char_id, tok in tokens.items():
        logger.info(f"[wallet] Fetching journal for {char_id}")
        try:
            entries = fetch_wallet_journal(char_id, tok["access_token"])
            store_wallet_journal(owner_id, char_id, entries)
            logger.info(f"[wallet] Stored {len(entries)} journal entries for {char_id}")
        except requests.HTTPError as e:
            logger.error(f"[wallet] Journal fetch failed for {char_id}: {e}")


def fetch_all_transactions(owner_id: int):
    """Fetch & store wallet transactions for all characters under this owner."""
    tokens = get_token(owner_id)
    for char_id, tok in tokens.items():
        logger.info(f"[wallet] Fetching transactions for {char_id}")
        try:
            txns = fetch_wallet_transactions(char_id, tok["access_token"])
            store_wallet_transaction(owner_id, char_id, txns)
            logger.info(f"[wallet] Stored {len(txns)} transactions for {char_id}")
        except requests.HTTPError as e:
            logger.error(f"[wallet] Transactions fetch failed for {char_id}: {e}")


def fetch_all_balance(owner_id: int):
    """Fetch & store wallet balances for all characters under this owner."""
    tokens = get_token(owner_id)
    for char_id, tok in tokens.items():
        logger.info(f"[wallet] Fetching balance for {char_id}")
        try:
            bal = fetch_wallet_balance(char_id, tok["access_token"])
            store_wallet_balance(owner_id, char_id, bal)
            logger.info(f"[wallet] Stored balance {bal} for {char_id}")
        except requests.HTTPError as e:
            logger.error(f"[wallet] Balance fetch failed for {char_id}: {e}")


def fetch_all_wallets(owner_id: int):
    """
    Top–level: refresh balance, transactions, and journals
    for every character under this owner.
    """
    fetch_all_balance(owner_id)
    fetch_all_transactions(owner_id)
    fetch_all_journals(owner_id)
