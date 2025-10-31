# EVE Data Framework 3

EVE Data Framework 3 is a self-hosted operations hub that keeps a corporation's EVE Online data synchronized, warehoused, and explorable through a single Flask web UI. The codebase automates the entire lifecycle: it provisions local SQLite databases, manages authentication with the EVE SSO, schedules pulls from ESI and the Static Data Export (SDE), normalizes the responses, and renders dashboards plus manual refresh tools for pilots.

This document walks through how the application behaves from the first `python main.py` run through recurring data refreshes. It assumes you are comfortable with Python, SQLAlchemy, and Flask, but have never seen this project before.

---

## 1. High-Level Workflow

1. **Runtime bootstrap (`main.py`)**
   - Loads `config.yaml`, surfaces runtime toggles (debug mode, auto-install, host/port), and configures logging via `util.utils.initialize_runtime_environment`.
   - Optionally auto-installs missing packages if `Runtime.auto_install` is enabled in the config.
   - Ensures the public database exists (`db.database.initialize_public_database`).
   - Launches the Flask application created in `webUI.create_app`.

2. **Web UI startup (`webUI/app.py`)**
   - Builds a Flask app pre-configured with sessions, blueprints, and Jinja environment.
   - Serves the dashboard (`webUI/dashboard.py`) that surfaces job slots, wallet information, and refresh actions.
   - Registers personal and public update routes (`webUI/personal_routes.py`, `webUI/public_routes.py`). Each route orchestrates fetchers, records progress to the logger, and streams a “console output” page for long operations.

3. **Data ingestion**
   - **Private pulls**: Authenticated character data flows through modules in `esi/personal_*` (skills, wallet, assets, etc.). Helper utilities in `util/utils.py` retrieve and refresh tokens stored inside each owner’s private SQLite database.
   - **Public pulls**: Market, structure, and SDE content is imported through `esi/public/*`. These modules rely on the rate-limited HTTP helpers in `util/esi_rate_limiter.py` to deduplicate requests and honor endpoint-specific TTLs.
   - **Analysis**: Modules under `analysis/` post-process raw tables (e.g., `analysis/job_slots.py`, `analysis/structures.py`) and expose summaries consumed by the dashboard.

4. **Storage**
   - Public data lives in `_publicData/public.db` and uses models defined in `db/models.py`’s `PublicBase`.
   - Each account owner receives a dedicated SQLite database in `_privateData/<owner_id>/<owner_id>.db` driven by `PrivateBase` models. The separation prevents leakage between characters and reduces lock contention.

5. **Long-running job UX**
   - Routes such as “Refresh SDE” or “Structure Markets” render `webUI/templates/console_output.html`. A tee handler mirrors log output both to stdout and to an in-memory buffer passed to the template. The page displays the complete log history with a live redirect countdown so the user can read the output before returning to the dashboard.

---

## 2. Configuration

All runtime knobs live in `config.yaml`. The file has three major sections:

- **Environment Variables** – copied into `os.environ` on startup. Use this block to define ESI credentials (`EVE_CLIENT_ID`, `EVE_SECRET_KEY`), organization identifiers, or custom cache directories.
- **Runtime** – optional keys that map onto `util.utils.RuntimeSettings`. Notable flags include:
  - `debug`: Enables Flask debug mode and verbose logging.
  - `auto_install`: When true, missing modules trigger a `pip install -r requirements.txt` automatically.
  - `host`/`port`: Network binding for the web server.
  - `trace_esi`: Prints every outgoing ESI request.
- **Tracked Entities** – character IDs, structure IDs, regions, and other lists consumed by fetchers. Each fetcher checks this section to decide which owners or regions to update by default.

Because environment variables are populated only if they are absent from the real shell environment, you can override values at launch without editing the file.

---

## 3. Dependency Management

`requirements.txt` lists the supported dependency set. On startup, `ensure_dependencies` will attempt to import each required module. If a module is missing and `auto_install` is false, the program raises an `ImportError` describing what to install. If `auto_install` is true, the runtime executes `pip install -r requirements.txt` in-place and retries the imports.

You can safely pre-create a virtual environment, install dependencies manually, and run the framework there; nothing in the codebase assumes global installations.

---

## 4. Database Architecture

### 4.1 Public Database (`_publicData/public.db`)

Created by `initialize_public_database`, this SQLite file holds data that is safe to share across all owners:

- `users`: Character-to-owner mapping used when tokens are refreshed automatically.
- `systems` & `stargates`: Derived from the SDE to provide navigation, region lookups, and topology.
- `structures` & `market_structures`: Station metadata including solar system, region, ownership, and last-seen timestamps.
- `market_orders` & `public_contracts`: Latest snapshots of public order books and contracts.

### 4.2 Private Databases (`_privateData/<owner_id>.db`)

When a character logs in or data is pulled for a new owner, `initialize_private_database` provisions a dedicated SQLite database. It stores sensitive information such as:

- OAuth tokens and identity metadata (`characters`).
- Personal assets and blueprints.
- Industry jobs, skill queue, wallet balances, journal entries, and bookmarks.

Sessions are created on demand via `db.database.get_private_session(owner_id)` so concurrent requests can work with separate session objects. `check_same_thread=False` combined with `pool_pre_ping=True` mitigates SQLite lock errors when routes are executed in quick succession.

---

## 5. Authentication and Token Flow

1. Characters authenticate through EVE SSO. Credentials are encrypted at rest using Fernet (see `util/auth.py`).
2. OAuth tokens are persisted in the owner’s private database. Each fetcher begins by calling `util.utils.get_token(owner_id)`:
   - It loads all characters for the owner.
   - Expired tokens are refreshed synchronously with the `/oauth/token` endpoint.
   - Access and refresh tokens are updated in-place and the caller receives a dictionary keyed by `character_id`.
3. Fetchers then attach the tokens to their ESI requests.

This design allows the framework to refresh tokens lazily at the moment of use, avoiding a central scheduler.

---

## 6. ESI Access, Caching, and Rate Limiting

`util/esi_rate_limiter.py` centralizes outbound HTTP calls. Key behaviors:

- **Request Coalescing** – identical requests within a TTL window reuse cached responses to avoid tripping ESI rate limits. For example, `/universe/structures/` responses are cached for a week, while `/markets/structures/{id}/` refresh every 30 minutes.
- **Thread Safety** – an `asyncio`-style token bucket is implemented using threading primitives so multiple routes can queue requests without exceeding per-second thresholds.
- **Tracing** – when `RuntimeSettings.trace_esi` is true, each outbound call is printed with method, URL, and cache status. This output also appears in the console template pages for long-running jobs.

All fetcher modules import `esi_get`, `esi_post`, or `esi_request` from this helper to ensure consistent behavior.

---

## 7. Static Data Export (SDE) Pipeline

Triggering “Refresh SDE” in the UI, or calling the underlying helper directly, performs the following steps (`esi/public/static_data.py` and `util/sde.py`):

1. Download the latest SDE ZIP from CCP.
2. Extract YAML files into `_sde_tmp`, filter to supported languages, and move the curated data into `_sde/`.
3. Rebuild cached lookup dictionaries, including solar system ⇄ region mappings.
4. Regenerate the `systems` and `stargates` tables using `util.sde.build_universe_table` so the relational data mirrors the fresh export.

During this process, log lines are captured by the console template so the operator can monitor progress.

---

## 8. Fetcher Modules and Data Refreshes

### 8.1 Personal Update Routes (`webUI/personal_routes.py`)

Each route corresponds to a button on the dashboard:

- `/update_personal/skills` → `esi.personal_skills.fetch_all_skills`
- `/update_personal/wallet` → `esi.personal_wallet.sync_wallet`
- `/update_personal/assets`, `/industry`, `/bookmarks`, etc.

Execution flow:
1. Resolve the active owner/character from the session.
2. Acquire tokens via `get_token`.
3. Call the appropriate fetcher which contacts ESI, parses JSON payloads, and merges rows into the private database.
4. Emit summary log lines (counts of stored rows, queue lengths, balances).
5. Redirect back to the dashboard or render the console output template if the route is long-running.

### 8.2 Public Update Routes (`webUI/public_routes.py`)

These routes populate global intelligence and require more CPU/IO time:

- `update_public/sde`: runs the SDE pipeline described above.
- `update_public/structures`: orchestrates structure discovery in `analysis.structures`. The analysis module merges SDE metadata, corporation sovereignty data, and private structure IDs to ensure every structure has a `solar_system_id` and `region_id` recorded.
- `update_public/markets`: imports public market contracts or pulls market orders for user-tracked structures, depending on the route.

The shared `run_with_console_output` helper wraps each route so stdout/stderr are captured, displayed in `console_output.html`, and then the page automatically redirects.

---

## 9. Analysis Modules

Data consumers under `analysis/` summarize stored information for display:

- `analysis/job_slots.py`: Calculates how many manufacturing and science slots are currently free for each character by comparing job counts to configured limits.
- `analysis/structures.py`: Discovers structure IDs, enriches them with region/system data, and exposes progress metrics while scanning sovereignty systems.
- Additional modules can be added without changing the ingestion layer because they read directly from the databases through SQLAlchemy sessions.

These scripts are pure Python and rely on the persisted data, so you can run them manually for offline analysis if desired.

---

## 10. Web UI Overview

The Flask UI lives under `webUI/`:

- `webUI/__init__.py`: Factory for the Flask app, registers blueprints, configures Jinja globals, and sets up session management.
- `webUI/templates/`: Jinja templates used throughout the interface. `dashboard.html` provides the main landing page, while `console_output.html` captures log streams for long jobs.
- `webUI/static/`: Houses CSS, JavaScript, and images required by the templates.

When you run the app, navigate to `http://127.0.0.1:5000`. The dashboard shows:

- Character summaries (skill queue, wallet balances, job slots).
- Buttons for each fetcher to trigger manual refreshes.
- Status banners derived from analysis modules.

Because the server uses Flask’s built-in development server, deploy behind a production WSGI server or reverse proxy for long-term hosting.

---

## 11. Logging

The framework uses the standard library `logging` module. Default log level is INFO, configurable via `Runtime.log_level`. Notable behaviors:

- Each fetcher logs the number of rows inserted/updated per pull.
- Token refresh events are explicitly logged so you can detect authentication churn.
- During long-running public tasks, output is duplicated to the browser console page.

Logs are emitted to stdout; consider redirecting output to files or a centralized logging system when running in production.

---

## 12. Development Tips

- **Running Tests**: Many modules are plain scripts. Use `python -m compileall <path>` to perform a quick syntax check, or integrate a linter/formatter of your choice.
- **Extending Fetchers**: Implement a new ESI integration by creating a module in `esi/personal_*` or `esi/public/`, reusing the rate-limited request helpers, and adding a route button in the corresponding blueprint.
- **Schema Changes**: Update models in `db/models.py` and ensure `PublicBase.metadata.create_all` or `PrivateBase.metadata.create_all` is called somewhere during initialization so new tables are created automatically.
- **Background Jobs**: A future `scheduler.py` placeholder exists. Today, refreshes are triggered manually from the UI; you can schedule them with cron or a task runner by invoking the fetcher modules directly.

---

## 13. Frequently Asked Operational Questions

- **Where are credentials stored?** In the private database for each owner. Tokens are encrypted before persisting, and the encryption key derives from values in `config.yaml`.
- **How do I add a new character?** Invite them through the UI’s SSO login flow. The framework will create the private DB (if needed), record the character, and start collecting data on the next refresh.
- **Can I run it headless?** Yes. Trigger refresh functions from standalone scripts or CLI wrappers that import the relevant modules and call them directly. The web UI is optional but helpful for visibility.
- **What happens if ESI is down?** Errors bubble up through the rate limiter with descriptive log messages. Because responses are cached with TTLs, the framework will continue serving the last known data until new pulls succeed.

---

## 14. Licensing

This project is released under the MIT License. See `LICENCE.md` for the full text.

