"""Persistence helpers for manufacturing and blueprint planning settings."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional

PRIVATE_DATA_FOLDER = os.getenv("EVE_PRIVATE_DATABASE_FOLDER", "_privateData")
SETTINGS_FILENAME = "manufacturing_settings.json"


@dataclass
class ManufacturingSettings:
    """User-tunable knobs that influence blueprint profitability calculations."""

    price_source: str = "sell"  # "sell" or "buy"
    region_id: Optional[int] = None
    facility_tax: float = 0.0
    facility_time_modifier: float = 1.0
    job_cost_per_run: float = 0.0
    runs_per_blueprint: int = 1
    parallel_jobs: int = 1
    minimum_margin: float = 0.0
    include_job_cost: bool = True
    override_prices: Dict[int, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ManufacturingSettings":
        data = dict(payload or {})
        overrides = data.get("override_prices") or {}
        normalised: Dict[int, float] = {}
        for key, value in overrides.items():
            try:
                type_id = int(key)
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price >= 0:
                normalised[type_id] = price

        source = str(data.get("price_source", "sell")).lower()
        if source not in {"sell", "buy"}:
            source = "sell"

        return cls(
            price_source=source,
            region_id=_coerce_optional_int(data.get("region_id")),
            facility_tax=_coerce_float(data.get("facility_tax"), 0.0),
            facility_time_modifier=max(0.1, _coerce_float(data.get("facility_time_modifier"), 1.0)),
            job_cost_per_run=max(0.0, _coerce_float(data.get("job_cost_per_run"), 0.0)),
            runs_per_blueprint=max(1, _coerce_int(data.get("runs_per_blueprint"), 1)),
            parallel_jobs=max(1, _coerce_int(data.get("parallel_jobs"), 1)),
            minimum_margin=max(0.0, _coerce_float(data.get("minimum_margin"), 0.0)),
            include_job_cost=bool(data.get("include_job_cost", True)),
            override_prices=normalised,
        )

    def to_json_ready(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["override_prices"] = {str(k): v for k, v in self.override_prices.items()}
        return payload

    def formatted_overrides(self) -> str:
        """Return overrides as human-editable lines."""
        lines = []
        for type_id, price in sorted(self.override_prices.items()):
            lines.append(f"{type_id} = {price:.2f}")
        return "\n".join(lines)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_optional_int(value: Any) -> Optional[int]:
    if value in (None, "", "none", "null"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_price_overrides(raw_text: str) -> Dict[int, float]:
    overrides: Dict[int, float] = {}
    for line in (raw_text or "").splitlines():
        chunk = line.strip()
        if not chunk:
            continue
        if "=" in chunk:
            key, value = chunk.split("=", 1)
        elif ":" in chunk:
            key, value = chunk.split(":", 1)
        else:
            parts = chunk.split()
            if len(parts) != 2:
                continue
            key, value = parts
        try:
            type_id = int(key.strip())
            price = float(value.strip())
        except (TypeError, ValueError):
            continue
        if price >= 0:
            overrides[type_id] = price
    return overrides


def _settings_path(owner_id: int) -> str:
    folder = os.path.join(PRIVATE_DATA_FOLDER, str(owner_id))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, SETTINGS_FILENAME)


def load_manufacturing_settings(owner_id: int) -> ManufacturingSettings:
    path = _settings_path(owner_id)
    if not os.path.exists(path):
        return ManufacturingSettings()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return ManufacturingSettings()
    return ManufacturingSettings.from_dict(payload)


def save_manufacturing_settings(owner_id: int, settings: ManufacturingSettings) -> None:
    path = _settings_path(owner_id)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(settings.to_json_ready(), handle, indent=2, sort_keys=True)


def update_settings_from_form(settings: ManufacturingSettings, form: Mapping[str, Any]) -> ManufacturingSettings:
    """Return a new settings object with data pulled from a submitted form."""

    payload = {
        "price_source": (form.get("price_source") or settings.price_source).lower(),
        "region_id": form.get("region_id") or None,
        "facility_tax": form.get("facility_tax") or settings.facility_tax,
        "facility_time_modifier": form.get("facility_time_modifier") or settings.facility_time_modifier,
        "job_cost_per_run": form.get("job_cost_per_run") or settings.job_cost_per_run,
        "runs_per_blueprint": form.get("runs_per_blueprint") or settings.runs_per_blueprint,
        "parallel_jobs": form.get("parallel_jobs") or settings.parallel_jobs,
        "minimum_margin": form.get("minimum_margin") or settings.minimum_margin,
        "include_job_cost": form.get("include_job_cost") in {"on", "true", "1", True},
        "override_prices": parse_price_overrides(form.get("override_prices", settings.formatted_overrides())),
    }
    return ManufacturingSettings.from_dict(payload)
