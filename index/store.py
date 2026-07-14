"""JSON stores for generated and user-overridden controller indexes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ControllerIndex


class IndexStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.generated_path = data_dir / "ha_index.generated.json"
        self.overrides_path = data_dir / "ha_index.overrides.json"

    def ensure_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_generated(self) -> ControllerIndex:
        return ControllerIndex.from_dict(_read_json(self.generated_path))

    def save_generated(self, index: ControllerIndex) -> None:
        self.ensure_dir()
        _write_json(self.generated_path, index.to_dict())

    def load_overrides(self) -> dict[str, Any]:
        data = _read_json(self.overrides_path)
        return data if isinstance(data, dict) else {"controllers": {}}

    def save_overrides(self, data: dict[str, Any]) -> None:
        self.ensure_dir()
        _write_json(self.overrides_path, data)

    def effective_index(self) -> ControllerIndex:
        return merge_indexes(self.load_generated(), self.load_overrides())


def merge_indexes(generated: ControllerIndex, overrides: dict[str, Any]) -> ControllerIndex:
    controller_overrides = overrides.get("controllers", {}) if isinstance(overrides, dict) else {}
    result = ControllerIndex(
        version=generated.version,
        pending=list(generated.pending),
        warnings=list(generated.warnings),
        summary=dict(generated.summary),
        last_scan_time=generated.last_scan_time,
        scan_status=generated.scan_status,
    )
    for controller in generated.controllers:
        merged = controller.to_dict()
        c_override = controller_overrides.get(controller.controller_id, {}) if isinstance(controller_overrides, dict) else {}
        if isinstance(c_override, dict):
            _merge_controller_dict(merged, c_override)
        result.controllers.append(type(controller).from_dict(merged))
    return result


def _merge_controller_dict(target: dict[str, Any], override: dict[str, Any]) -> None:
    for key in ["display_name", "aliases", "exposed", "area_name"]:
        if key in override:
            target[key] = override[key]
    cap_overrides = override.get("capabilities", {})
    if not isinstance(cap_overrides, dict):
        return
    for cap in target.get("capabilities", []) or []:
        cap_id = cap.get("capability_id")
        cap_override = cap_overrides.get(cap_id, {})
        if not isinstance(cap_override, dict):
            continue
        for key in ["display_name", "aliases", "exposed"]:
            if key in cap_override:
                cap[key] = cap_override[key]
        value_overrides = cap_override.get("values", {})
        if not isinstance(value_overrides, dict):
            continue
        for value in cap.get("values", []) or []:
            value_id = value.get("value")
            value_override = value_overrides.get(value_id, {})
            if isinstance(value_override, dict) and "aliases" in value_override:
                value["aliases"] = value_override["aliases"]


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
