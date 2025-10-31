# utils.py

import importlib
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from threading import Lock
from typing import Iterable, Optional

import requests
import yaml

from db.database import get_private_session
from db.models import Character
from util.auth import CredentialManager, TokenDBManager
from util.esi_rate_limiter import esi_get, esi_post, esi_request

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"
PRIVATE_DATA_FOLDER = os.getenv("EVE_PRIVATE_DATABASE_FOLDER", "_privateData/")
ESI_BASE = "https://esi.evetech.net/latest"
HEADERS = {"Accept": "application/json"}
DATASOURCE = {"datasource": "tranquility"}

TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"

REQUIRED_MODULES = (
    "sqlalchemy",
    "ruamel.yaml",
    "flask",
    "cryptography",
    "requests_oauthlib",
    "jwt",
    "yaml",
)

DEFAULT_SECRET = "nolieravioli"


# ──────── Runtime Settings ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class RuntimeSettings:
    """In-memory view of the runtime knobs for the small-team deployment."""

    debug_mode: bool = False
    auto_install: bool = False
    web_host: str = "127.0.0.1"
    web_port: int = 5000
    session_secret: str = DEFAULT_SECRET
    log_level: str = "INFO"
    trace_esi: bool = False
    testing_version: bool = False


_runtime_settings: Optional[RuntimeSettings] = None
_runtime_lock = Lock()


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def initialize_runtime_environment(config_path: str = CONFIG_PATH) -> RuntimeSettings:
    """Load config, set up logging, and surface runtime toggles once."""

    global _runtime_settings
    with _runtime_lock:
        if _runtime_settings is not None:
            return _runtime_settings

        cfg = load_config(config_path)
        runtime_cfg = cfg.get("Runtime", {}) if isinstance(cfg, dict) else {}

        debug_mode = _as_bool(runtime_cfg.get("debug") or os.getenv("EVE_DEBUG"))
        auto_install = _as_bool(runtime_cfg.get("auto_install") or os.getenv("EVE_AUTO_INSTALL"))
        trace_esi = _as_bool(runtime_cfg.get("trace_esi") or os.getenv("EVE_TRACE_ESI"))
        testing_version = _as_bool(
            runtime_cfg.get("testing_version") or os.getenv("EVE_TESTING_VERSION")
        )

        web_host = runtime_cfg.get("host") or os.getenv("EVE_WEB_HOST", "127.0.0.1")
        web_port = int(runtime_cfg.get("port") or os.getenv("EVE_WEB_PORT", "5000"))

        session_secret = (
            os.getenv("FLASK_SECRET_KEY")
            or runtime_cfg.get("secret_key")
            or DEFAULT_SECRET
        )

        log_level = (runtime_cfg.get("log_level") or os.getenv("EVE_LOG_LEVEL") or "INFO").upper()
        logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

        if debug_mode:
            print(f"[Runtime] Debug mode enabled. Log level={log_level}")
        if trace_esi:
            print("[Runtime] ESI tracing is active. HTTP requests will be printed.")

        _runtime_settings = RuntimeSettings(
            debug_mode=debug_mode,
            auto_install=auto_install,
            web_host=web_host,
            web_port=web_port,
            session_secret=session_secret,
            log_level=log_level,
            trace_esi=trace_esi,
            testing_version=testing_version,
        )

        return _runtime_settings


def get_runtime_settings() -> RuntimeSettings:
    """Return cached runtime settings, initialising them if needed."""

    if _runtime_settings is None:
        return initialize_runtime_environment(CONFIG_PATH)
    return _runtime_settings


def ensure_dependencies(settings: Optional[RuntimeSettings] = None,
                        required_modules: Iterable[str] = REQUIRED_MODULES) -> None:
    """Optionally auto-install missing modules to keep small deployments running."""

    settings = settings or get_runtime_settings()
    missing = []
    for module_name in required_modules:
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(module_name)

    if not missing:
        return

    message = f"Missing dependencies detected: {', '.join(missing)}"
    if not settings.auto_install:
        raise ImportError(message)

    print(f"[Runtime] {message}. Installing from requirements.txt...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    print("[Runtime] Dependency installation complete.")


# ──────── Config Loader ─────────────────────────────────────────────────────────


def load_config(config_path: str = CONFIG_PATH) -> dict:
    """
    Loads Environment Variables from a config.yaml into os.environ.
    Returns the full config dict.
    """

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    env_vars = cfg.get("Environment Variables", {})
    if not isinstance(env_vars, dict):
        raise ValueError("Expected 'Environment Variables' to be a dictionary in config.yaml")

    for key, value in env_vars.items():
        if key not in os.environ:
            if isinstance(value, list):
                os.environ[key] = ",".join(str(v) for v in value)
            else:
                os.environ[key] = str(value)

    logger.info(f"Loaded {len(env_vars)} environment variables from {config_path}")
    return cfg

# ──────── Token / Character Utilities ───────────────────────────────────────────

def get_token(owner_id: int) -> dict:
    """
    Return { character_id: TokenRow } dict for all characters linked to an owner.
    If any tokens are expired, refresh them automatically and SAVE them.
    """
    token_map = {}
    now = time.time()
    session = get_private_session(owner_id)
    token_db = TokenDBManager(owner_id)
    try:
        tokens = session.query(Character).all()
        for token in tokens:
            if token.expires_at and token.expires_at < now:
                logger.info(f"Token expired for {token.character_id}, refreshing...")
                try:
                    refreshed = refresh_token(token.refresh_token)
                    # Update the SQLAlchemy model
                    token.access_token = refreshed["access_token"]
                    token.refresh_token = refreshed["refresh_token"]
                    token.expires_at = refreshed.get("expires_at", now + refreshed.get("expires_in", 1200))
                    token.scopes = refreshed.get("scope", token.scopes)
                    # Save to SQLAlchemy (private toon db)
                    session.commit()
                    # Save to raw SQLite (token db)
                    token_db.save_tokens(
                        character_id=token.character_id,
                        access_token=token.access_token,
                        refresh_token=token.refresh_token,
                        expires_at=token.expires_at,
                        scopes=token.scopes
                    )
                except Exception as e:
                    logger.error(f"[TokenManager] Failed to refresh token for {token.character_id}: {e}")
                    continue
            token_map[token.character_id] = {
                "corporation_id": token.corporation_id,
                "alliance_id": token.alliance_id,
                "security_status": token.security_status,
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expires_at": token.expires_at,
                "scopes": token.scopes,
            }
    finally:
        session.close()
    return token_map

def refresh_token(refresh_token: str) -> dict:
    client_id, client_secret, _, _ = CredentialManager.load_credentials()
    r = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        }
    )
    r.raise_for_status()
    token_data = r.json()
    token_data["expires_at"] = time.time() + token_data.get("expires_in", 1200)
    return token_data

# ──────── ESI Utilities ──────────────────────────────────────────────────────────

def safe_request(method, url, **kwargs):
    retries = 3
    backoff = 2
    if get_runtime_settings().trace_esi:
        print(f"[ESI] {method.upper()} {url} kwargs={kwargs}")
    for attempt in range(retries):
        try:
            kwargs.setdefault("timeout", 30)
            resp = esi_request(method, url, **kwargs)
            if resp.status_code == 403:
                logger.warning(f"Access forbidden (403) for {url}. Skipping retries.")
                resp.raise_for_status()
            resp.raise_for_status()
            if get_runtime_settings().trace_esi:
                print(f"[ESI] Response {resp.status_code} for {url}")
            return resp
        except requests.HTTPError as e:
            if e.response.status_code == 403:
                raise
            logger.warning(f"Request failed ({attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(backoff)
                backoff *= 2
            else:
                raise

def get_portrait(character_id: int):
    """ get esi portraits """
    url = f"{ESI_BASE}/characters/{character_id}/portrait/"
    resp = esi_get(url, headers=HEADERS, params=DATASOURCE)
    resp.raise_for_status()
    if get_runtime_settings().trace_esi:
        print(f"[ESI] Portrait lookup for {character_id}: {resp.json()}")
    return resp.json()


def batched(iterable, batch_size):
    """Yield successive batches of a list."""
    for i in range(0, len(iterable), batch_size):
        yield iterable[i:i + batch_size]

def get_all_region_ids():
    """Get all region IDs from ESI."""
    url = f"{ESI_BASE}/universe/regions/"
    resp = esi_get(url, headers=HEADERS, params=DATASOURCE)
    resp.raise_for_status()
    return resp.json()

def is_structure(structure_id: int) -> bool:
    """Check if a given ID is a structure via ESI."""
    url = f"{ESI_BASE}/universe/structures/{structure_id}/"
    r = esi_get(url, headers=HEADERS, params=DATASOURCE)
    return r

def resolve_names_to_ids(names: list[str]) -> dict:
    """Bulk convert system or structure names to IDs using ESI."""
    if not names:
        return {}

    response = esi_post(
        f"{ESI_BASE}/universe/ids/",
        headers=HEADERS,
        params={"datasource": "tranquility", "language": os.getenv("LANGUAGE", "en")},
        json=names,
    )
    response.raise_for_status()

    systems = response.json().get("systems", [])
    return {entry["name"]: entry["id"] for entry in systems}

