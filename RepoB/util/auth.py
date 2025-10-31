# util/auth.py

import os
import json
import logging
import requests
from typing import Tuple
from cryptography.fernet import Fernet

from sqlalchemy import text
from db.database import (
    initialize_private_database,
    get_private_session,
    initialize_public_database,
    get_public_session,
)
from util.esi_rate_limiter import esi_get

# ─────── Globals ─────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

PUBLIC_DATA_FOLDER = os.getenv("PUBLIC_DATA_PATH", "_publicData")
PUBLIC_DATABASE_FILENAME = os.getenv("EVE_PUBLIC_DATABASE_FILE", "public.db")
PUBLIC_DATABASE_FILE = os.path.join(PUBLIC_DATA_FOLDER, PUBLIC_DATABASE_FILENAME)

PRIVATE_DATA_FOLDER = os.getenv("EVE_PRIVATE_DATABASE_FOLDER", "_privateData")

CONFIG_FILE_PATH = os.getenv("CONFIG_FILE", "config.yaml")
CLIENT_CRED_FILE = os.path.join(PUBLIC_DATA_FOLDER, "client_cred")
KEY_FILE = os.path.join(PUBLIC_DATA_FOLDER, "key")

# ────── Helpers ──────────────────────────────────────────────────────────────

def ensure_folder(path: str):
    os.makedirs(path, exist_ok=True)


def lookup_info(character_id: int):
    """
    Return [name, corporation_id, birthday, alliance_id] for a given EVE character.
    alliance_id will be None if the corp isn’t in an alliance.
    Raises HTTPError on any non-200 response.
    """
    char_url = (
        f"https://esi.evetech.net/latest/characters/{character_id}/?datasource=tranquility"
    )
    resp = esi_get(char_url)
    resp.raise_for_status()
    char_data = resp.json()

    name = char_data["name"]
    corporation_id = char_data["corporation_id"]
    birthday = char_data["birthday"]
    security_status = char_data.get("security_status")
    alliance_id = char_data.get("alliance_id")

    return [name, corporation_id, birthday, security_status, alliance_id]

# ─────── Classes ─────────────────────────────────────────────────────────────
class CredentialManager:
    """Handles loading and saving client credentials."""
    logger = logging.getLogger('CredentialManager')

    @staticmethod
    def load_credentials() -> Tuple[str, str, str, str]:
        ensure_folder(PUBLIC_DATA_FOLDER)
        if not os.path.exists(KEY_FILE):
            with open(KEY_FILE, "wb") as f:
                f.write(Fernet.generate_key())

        with open(KEY_FILE, "rb") as f:
            fernet = Fernet(f.read())

        if not os.path.exists(CLIENT_CRED_FILE):
            logger.info("No credentials found. Setup required.")
            return CredentialManager.setup_credentials(fernet)

        with open(CLIENT_CRED_FILE, "rb") as f:
            creds = json.loads(fernet.decrypt(f.read()).decode())
            return creds["client_id"], creds["client_secret"], creds["redirect_uri"], creds["scopes"]

    @staticmethod
    def setup_credentials(fernet: Fernet) -> Tuple[str, str, str, str]:
        import webbrowser
        webbrowser.open("https://developers.eveonline.com/applications")
        client_id = input("Client ID: ").strip()
        client_secret = input("Client Secret: ").strip()
        redirect_uri = input("Callback URL: ").strip()
        raw_scopes = input("Scopes (JSON list format): ").strip()

        try:
            scopes_list = json.loads(raw_scopes)
            scopes = " ".join(scopes_list)
        except Exception:
            raise ValueError("Scopes must be a valid JSON list!")

        creds = {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "scopes": scopes
        }

        with open(CLIENT_CRED_FILE, "wb") as f:
            f.write(fernet.encrypt(json.dumps(creds).encode()))
        logger.info(f"Credentials saved at {CLIENT_CRED_FILE}")

        return client_id, client_secret, redirect_uri, scopes

class TokenDBManager:
    """Handles token storage and character linkage using SQLAlchemy sessions."""
    logger = logging.getLogger('TokenDBManager')

    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        # ensure DBs initialized
        initialize_public_database()
        initialize_private_database(owner_id)

    def save_tokens(self,
                    character_id: int,
                    access_token: str,
                    refresh_token: str,
                    expires_at: float,
                    scopes: str):
        """
        1) Link character → owner in the public DB (users table);
        2) Lookup character info via ESI;
        3) INSERT OR REPLACE into the owner’s private DB.
        """
        # ——— Public DB ———
        session_pub = get_public_session()
        session_pub.execute(
            text(
                "INSERT OR IGNORE INTO users (character_id, owner_id)"
                " VALUES (:cid, :oid)"
            ),
            {"cid": character_id, "oid": self.owner_id}
        )
        session_pub.commit()
        session_pub.close()

        # ——— ESI lookup ———
        name, corporation_id, birthday, security_status, alliance_id = lookup_info(character_id)

        # ——— Private DB ———
        session_priv = get_private_session(self.owner_id)
        session_priv.execute(
            text(
                "INSERT OR REPLACE INTO characters"
                " (character_id, name, corporation_id, birthday,"
                " security_status, alliance_id, access_token,"
                " refresh_token, expires_at, scopes)"
                " VALUES (:cid, :nm, :corp, :bday, :sec, :alli, :at, :rt, :exp, :sc)"
            ),
            {
                "cid": character_id,
                "nm": name,
                "corp": corporation_id,
                "bday": birthday,
                "sec": security_status,
                "alli": alliance_id,
                "at": access_token,
                "rt": refresh_token,
                "exp": expires_at,
                "sc": scopes
            }
        )
        session_priv.commit()
        session_priv.close()
