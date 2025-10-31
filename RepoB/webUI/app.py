# webUI/app.py

from typing import Optional

from util.utils import RuntimeSettings, get_runtime_settings
from webUI import create_app


def start_webUI(settings: Optional[RuntimeSettings] = None):
    """Create and run the Flask application with runtime-aware defaults."""

    settings = settings or get_runtime_settings()
    app = create_app(settings)

    if settings.debug_mode:
        print("[WebUI] Launching with Flask debug mode ON for rapid iteration.")

    app.run(
        debug=settings.debug_mode,
        host=settings.web_host,
        port=settings.web_port,
        use_reloader=settings.debug_mode,
    )
