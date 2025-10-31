# webUI/sso.py

import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Optional

import jwt
from flask import Blueprint, redirect, request, session, url_for
from requests.auth import HTTPBasicAuth
from requests_oauthlib import OAuth2Session

from util.auth import CredentialManager, TokenDBManager
from util.utils import RuntimeSettings, get_runtime_settings

# ─────── Globals ─────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)

TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
AUTH_URL = "https://login.eveonline.com/v2/oauth/authorize"


@dataclass
class OAuthStateRecord:
    """Track issued OAuth states so stateless callbacks still validate."""

    value: str
    is_add_toon: bool
    owner_id: Optional[int]
    created: float = field(default_factory=lambda: time.time())


class OAuthStateCache:
    """Simple TTL cache for issued state tokens."""

    def __init__(self, ttl_seconds: int, debug: bool = False):
        self._ttl = ttl_seconds
        self._store: Dict[str, OAuthStateRecord] = {}
        self._lock = Lock()
        self._debug = debug

    def remember(self, record: OAuthStateRecord) -> None:
        with self._lock:
            self._purge_locked()
            self._store[record.value] = record
            if self._debug:
                print(
                    f"[Auth] Remembered state {record.value} "
                    f"add_toon={record.is_add_toon} owner={record.owner_id}"
                )

    def consume(self, value: str) -> Optional[OAuthStateRecord]:
        with self._lock:
            self._purge_locked()
            record = self._store.pop(value, None)
            if self._debug:
                print(f"[Auth] Consumed state {value}: {record}")
            return record

    def _purge_locked(self) -> None:
        cutoff = time.time() - self._ttl
        expired = [key for key, rec in self._store.items() if rec.created < cutoff]
        for key in expired:
            self._store.pop(key, None)
        if expired and self._debug:
            print(f"[Auth] Purged expired states: {expired}")


def _build_state_cache(settings: RuntimeSettings) -> OAuthStateCache:
    ttl = 600 if settings.debug_mode else 300
    return OAuthStateCache(ttl_seconds=ttl, debug=settings.debug_mode)


_settings = get_runtime_settings()
_state_cache = _build_state_cache(_settings)


def _issue_state(eve_session: OAuth2Session, *, is_add_toon: bool) -> str:
    """Generate a durable state token and remember it for stateless callbacks."""

    manual_state = secrets.token_urlsafe(32)
    auth_url, _ = eve_session.authorization_url(AUTH_URL, state=manual_state)
    session["oauth_state"] = manual_state
    session["add_toon"] = is_add_toon

    owner_id = session.get("owner_id") if is_add_toon else None
    _state_cache.remember(OAuthStateRecord(manual_state, is_add_toon, owner_id))

    if _settings.debug_mode:
        print(f"[Auth] Issued state={manual_state} add_toon={is_add_toon} owner={owner_id}")

    return auth_url


def _prepare_oauth_session(is_add_toon: bool) -> OAuth2Session:
    """Helper that loads credentials and issues a state token."""

    client_id, _, redirect_uri, scopes = CredentialManager.load_credentials()
    eve = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scopes.split())
    auth_url = _issue_state(eve, is_add_toon=is_add_toon)
    if _settings.debug_mode:
        print(f"[Auth] Redirecting to {auth_url}")
    return auth_url


@auth_bp.route("/login")
def login():
    """Kick off the primary SSO login flow."""

    # NOTE: local testing only. On HTTPS deployments this should be removed.
    if _settings.debug_mode:
        print("[Auth] Login requested; permitting insecure transport for local dev.")
    # Flask-OAuthlib requires this flag when running over HTTP locally.
    # Safe because this code path is for our internal deployments.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    auth_url = _prepare_oauth_session(is_add_toon=False)
    return redirect(auth_url)


@auth_bp.route("/add_toon")
def add_toon():
    """Link an additional character to the logged-in owner."""

    if not session.get("owner_id"):
        return "Error: No owner session found for adding toon.", 400

    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    auth_url = _prepare_oauth_session(is_add_toon=True)
    return redirect(auth_url)


def _validate_state(returned_state: Optional[str]):
    if not returned_state:
        return None, None, ("Missing OAuth state.", 400)

    session_state = session.pop("oauth_state", None)
    cached = _state_cache.consume(returned_state)

    if session_state and session_state != returned_state:
        return None, None, ("State mismatch detected.", 400)

    if not session_state and not cached:
        return None, None, ("Session expired or missing state.", 400)

    is_add_toon = session.pop("add_toon", False)
    owner_hint = None
    if cached is not None:
        is_add_toon = cached.is_add_toon
        owner_hint = cached.owner_id

    if _settings.debug_mode:
        print(
            f"[Auth] State validated. add_toon={is_add_toon} "
            f"owner_hint={owner_hint} session_state={session_state}"
        )

    return is_add_toon, owner_hint, None


@auth_bp.route("/callback")
def callback():
    """Handle the OAuth2 callback from EVE SSO."""

    try:
        returned_state = request.args.get("state")
        is_add_toon, owner_hint, error = _validate_state(returned_state)
        if error:
            return error

        client_id, client_secret, redirect_uri, _ = CredentialManager.load_credentials()
        eve = OAuth2Session(client_id, redirect_uri=redirect_uri, state=returned_state)

        token = eve.fetch_token(
            TOKEN_URL,
            authorization_response=request.url,
            auth=HTTPBasicAuth(client_id, client_secret),
        )

        decoded = jwt.decode(token["access_token"], options={"verify_signature": False})
        character_id = int(decoded["sub"].split(":")[-1])

        if _settings.debug_mode:
            print(
                f"[Auth] Token received for character {character_id}. "
                f"Scopes={token.get('scope')}"
            )

        if is_add_toon:
            owner_id = session.get("owner_id") or owner_hint
            if not owner_id:
                return "Error: No owner session found for adding toon.", 400
        else:
            owner_id = character_id
            session["owner_id"] = owner_id
            session["character_id"] = character_id

        mgr = TokenDBManager(owner_id)
        mgr.save_tokens(
            character_id,
            token["access_token"],
            token["refresh_token"],
            token["expires_at"],
            token.get("scope", ""),
        )

        session["access_token"] = token["access_token"]
        session["refresh_token"] = token["refresh_token"]

        if _settings.debug_mode:
            print(
                f"[Auth] Session updated owner={owner_id} "
                f"characters={[session.get('character_id')]}")

        return redirect(url_for("dashboard.home"))

    except Exception as exc:  # pragma: no cover - diagnostic path
        logger.exception("[Auth] Error during authentication callback")
        return f"Authentication failed: {exc}", 500


@auth_bp.route("/logout")
def logout():
    """Clear the user session."""

    session.clear()
    if _settings.debug_mode:
        print("[Auth] Session cleared via logout.")
    return redirect(url_for("dashboard.home"))
