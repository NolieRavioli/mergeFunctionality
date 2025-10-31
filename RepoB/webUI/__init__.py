# webUI/__init__.py

import os
from typing import Optional

from flask import Flask

from util.utils import RuntimeSettings, get_runtime_settings
from webUI.dashboard import dashboard_bp
from webUI.industry import industry_bp
from webUI.market_browser import market_bp
from webUI.personal_routes import update_personal_bp
from webUI.public_routes import update_public_bp
from webUI.sso import auth_bp


def create_app(settings: Optional[RuntimeSettings] = None):
    """Factory that wires blueprints and exposes runtime settings to Flask."""

    settings = settings or get_runtime_settings()
    app = Flask(__name__)
    secret = settings.session_secret or os.getenv("FLASK_SECRET_KEY")
    app.secret_key = secret or "nolieravioli"

    # Expose toggles for downstream handlers (dashboard, SSO, etc.).
    app.config["RUNTIME_SETTINGS"] = settings

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(update_personal_bp)
    app.register_blueprint(update_public_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(industry_bp)

    return app
