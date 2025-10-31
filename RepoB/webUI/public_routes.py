# webUI/update_public_routes.py
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO, TextIOBase
import logging
import sys

from flask import Blueprint, make_response, render_template, request, url_for

# Public fetchers
from esi.public.market_structure import fetch_all_structure_markets, update_structure_market
from analysis.structures import discover_all_structures
from esi.public.market_contracts import fetch_all_public_contracts as fetch_all_contracts
from esi.public.market_station import fetch_all_market_data
from esi.public.static_data import update_sde

# ─────── Setup ────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
update_public_bp = Blueprint('update_public', __name__, url_prefix="/update_public")

# ─────── Routes ───────────────────────────────────────────────────────────────

class _Tee(TextIOBase):
    """Mirror writes to the captured stream and the original target."""

    def __init__(self, capture: StringIO, original):
        self._capture = capture
        self._original = original

    def write(self, data):  # pragma: no cover - passthrough behaviour
        self._capture.write(data)
        if self._original is not None:
            self._original.write(data)
        return len(data)

    def flush(self):  # pragma: no cover - passthrough behaviour
        self._capture.flush()
        if self._original is not None:
            self._original.flush()


def _render_console_page(title: str, operation):
    """Execute an operation, capture its logs, and render them to the user."""

    redirect_url = request.referrer or url_for("dashboard.home")
    stream = StringIO()

    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.NOTSET)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root_logger = logging.getLogger()
    original_level = root_logger.level
    root_logger.addHandler(handler)
    if original_level > logging.INFO:
        root_logger.setLevel(logging.INFO)

    success = True
    try:
        stdout_tee = _Tee(stream, sys.stdout)
        stderr_tee = _Tee(stream, sys.stderr)
        with redirect_stdout(stdout_tee), redirect_stderr(stderr_tee):
            operation()
    except Exception:  # pragma: no cover - surfaced via the captured logs
        success = False
        logger.exception("[%s] Operation failed.", title)
    finally:
        handler.flush()
        root_logger.removeHandler(handler)
        root_logger.setLevel(original_level)
        handler.close()

    log_output = stream.getvalue().strip()
    stream.close()

    status_code = 200 if success else 500
    response = make_response(
        render_template(
            "console_output.html",
            title=title,
            log_output=log_output or "No log output was produced.",
            redirect_url=redirect_url,
            redirect_delay=10000,
            success=success,
        )
    )
    response.status_code = status_code
    response.headers["Cache-Control"] = "no-store"
    return response


@update_public_bp.route("/structures")
def update_public_structures():
    """Discover all structures from all owners and store them."""

    def operation():
        discover_all_structures()
        logger.info("[UpdatePublic] Structure discovery complete.")

    return _render_console_page("Structure Discovery", operation)

@update_public_bp.route("/structure_markets")
def update_public_structure_markets():
    """Update market orders from discovered structures (all owners)."""

    def operation():
        fetch_all_structure_markets()
        logger.info("[UpdatePublic] Structure market update complete.")

    return _render_console_page("Structure Market Refresh", operation)

@update_public_bp.route("/contracts")
def update_public_contracts():
    """Update public contracts across all regions."""

    def operation():
        fetch_all_contracts()
        logger.info("[UpdatePublic] Public contracts fetch complete.")

    return _render_console_page("Public Contracts Refresh", operation)

@update_public_bp.route("/market")
def update_public_market():
    """Update public market orders across all regions."""

    def operation():
        fetch_all_market_data()
        logger.info("[UpdatePublic] Public market data fetch complete.")

    return _render_console_page("Public Market Refresh", operation)

@update_public_bp.route("/sde")
def update_public_sde():
    """Download and update the Static Data Export (SDE)."""

    def operation():
        update_sde()
        logger.info("[UpdatePublic] Static Data Export update complete.")

    return _render_console_page("Static Data Export Refresh", operation)
