"""Build a controller index from Home Assistant states/services."""

from __future__ import annotations

import hashlib
import re
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..index.models import Binding, Capability, CapabilityValue, Controller, ControllerIndex

LOGGER = logging.getLogger(__name__)

CONTROL_DOMAINS = {
    "climate",
    "fan",
    "input_boolean",
    "input_number",
    "input_select",
    "light",
    "number",
    "script",
    "select",
    "sensor",
    "binary_sensor",
    "switch",
    "weather",
}

IGNORED_DOMAINS = {"automation"}

POWER_MISBINDING_KEYWORDS = [
    "strong",
    "quiet",
    "sleep",
    "formaldehyde",
    "aux_heat",
    "swing",
    "health",
    "airflow",
    "fan",
    "mode",
    "purify",
    "boost",
]


@dataclass
class NormalizedEntity:
    entity_id: str
    domain: str
    friendly_name: str
    state: str
    attributes: dict[str, Any]
    controller_id: str
    controller_name: str
    capability_id: str
    capability_name: str
    area_id: str = ""
    area_name: str = ""
    device_id: str = ""
    device_name: str = ""
    entity_category: str = ""
    hidden_by: str = ""
    platform: str = ""
    area_resolved_by: str = "unresolved"


@dataclass
class EntityGroup:
    group_key: str
    source: str
    entities: list[NormalizedEntity]


@dataclass
class RegistryContext:
    registry_by_entity_id: dict[str, dict[str, Any]]
    area_name_by_id: dict[str, str]
    device_by_id: dict[str, dict[str, Any]]
    warnings: list[str]
    auth_success: bool = False
    raw_types: dict[str, str] | None = None
    states_count: int = 0
    matched_registry_by_entity_id: int = 0
    entities_with_area_id: int = 0
    entities_resolved_by_device_area: int = 0
    entities_unresolved_area: int = 0


class ControllerScanner:
    def __init__(self, *, existing_aliases: list[dict[str, Any]] | None = None) -> None:
        self.existing_aliases = existing_aliases or []

    async def scan(self, client: Any) -> ControllerIndex:
        states = await client.get_states()
        registry = await _load_registry_context(client)
        registry.states_count = len(states)
        normalized = [_normalize_state(item, registry) for item in states]
        groups: dict[str, EntityGroup] = {}
        controllers: dict[str, Controller] = {}
        pending: list[dict[str, Any]] = []
        scripts: list[NormalizedEntity] = []

        for entity in normalized:
            if entity.domain in IGNORED_DOMAINS:
                continue
            if entity.domain not in CONTROL_DOMAINS:
                continue
            if entity.domain == "script":
                pending.append(_pending_script(entity))
                scripts.append(entity)
                continue

            group_key, group_source = _controller_group_key(entity)
            group = groups.setdefault(group_key, EntityGroup(group_key, group_source, []))
            group.entities.append(entity)

        grouping_summary = {
            "total_entities": len(normalized),
            "total_device_id_groups": len({item.device_id for item in normalized if item.device_id}),
            "controllers_built_from_device_id": 0,
            "controllers_built_from_environment": 0,
            "controllers_built_from_prefix": 0,
            "standalone_controllers": 0,
            "entities_hidden_as_config_diagnostic_internal": 0,
        }
        for group in groups.values():
            controller = _controller_from_group(group, registry, grouping_summary)
            controllers[controller.controller_id] = controller

        _attach_power_scripts(controllers, scripts)
        _sanitize_power_bindings(controllers)
        _log_power_selections(controllers)

        if not registry.warnings and normalized and registry.entities_with_area_id == 0 and registry.entities_resolved_by_device_area == 0:
            registry.warnings.append("未读取到 HA Area 信息，可能是 WebSocket registry 扫描失败。")
        summary = _registry_summary(registry)
        summary.update(grouping_summary)
        summary["controller_living_light_source_entities_count"] = _source_count_for_controller(controllers, "客厅灯")
        index = ControllerIndex(
            version=1,
            controllers=sorted(controllers.values(), key=lambda item: item.controller_id),
            pending=pending,
            warnings=list(registry.warnings),
            summary=summary,
            last_scan_time=datetime.now().isoformat(timespec="seconds"),
            scan_status="success",
        )
        if registry.warnings:
            index.pending.append(
                {
                    "pending_id": "ha_registry_area_warning",
                    "type": "registry_warning",
                    "reason": "未读取到 HA Area 信息，可能是 WebSocket registry 扫描失败。",
                    "warnings": registry.warnings,
                }
            )
        _log_registry_summary(registry, normalized)
        _log_grouping_summary(grouping_summary, controllers)
        return index


async def _load_registry_context(client: Any) -> RegistryContext:
    empty = RegistryContext({}, {}, {}, [])
    get_registry_metadata = getattr(client, "get_registry_metadata", None)
    if not callable(get_registry_metadata):
        empty.warnings.append("client does not support WebSocket registry scan")
        return empty
    try:
        metadata = await get_registry_metadata()
    except Exception as exc:  # noqa: BLE001
        empty.warnings.append(str(exc))
        return empty

    entity_registry = metadata.get("entity_registry", []) if isinstance(metadata, dict) else []
    area_registry = metadata.get("area_registry", []) if isinstance(metadata, dict) else []
    device_registry = metadata.get("device_registry", []) if isinstance(metadata, dict) else []
    warnings = metadata.get("warnings", []) if isinstance(metadata, dict) else []
    raw_types = metadata.get("raw_types", {}) if isinstance(metadata, dict) else {}
    auth_success = bool(metadata.get("auth_success", False)) if isinstance(metadata, dict) else False

    registry_by_entity_id = {
        item["entity_id"]: item
        for item in entity_registry
        if isinstance(item, dict)
        for item in [_normalize_registry_entity(item)]
        if item.get("entity_id")
    }
    area_name_by_id = {
        item["area_id"]: item["name"]
        for item in area_registry
        if isinstance(item, dict)
        for item in [_normalize_registry_area(item)]
        if item.get("area_id")
    }
    device_by_id = {
        item["device_id"]: item
        for item in device_registry
        if isinstance(item, dict)
        for item in [_normalize_registry_device(item)]
        if item.get("device_id")
    }
    return RegistryContext(
        registry_by_entity_id=registry_by_entity_id,
        area_name_by_id=area_name_by_id,
        device_by_id=device_by_id,
        warnings=[str(item) for item in warnings or []],
        auth_success=auth_success,
        raw_types=raw_types if isinstance(raw_types, dict) else {},
    )


def _normalize_registry_entity(item: dict[str, Any]) -> dict[str, str]:
    return {
        "entity_id": str(item.get("ei") or item.get("entity_id") or ""),
        "area_id": str(item.get("ai") or item.get("area_id") or ""),
        "device_id": str(item.get("di") or item.get("device_id") or ""),
        "entity_category": str(item.get("ec") or item.get("entity_category") or ""),
        "hidden_by": str(item.get("hb") or item.get("hidden_by") or ""),
        "platform": str(item.get("pl") or item.get("platform") or ""),
        "name": str(item.get("en") or item.get("name") or ""),
    }


def _normalize_registry_area(item: dict[str, Any]) -> dict[str, str]:
    area_id = str(item.get("area_id") or item.get("id") or "")
    return {
        "area_id": area_id,
        "name": str(item.get("name") or item.get("area_name") or area_id),
    }


def _normalize_registry_device(item: dict[str, Any]) -> dict[str, Any]:
    device_id = str(item.get("id") or item.get("device_id") or "")
    area_id = str(item.get("area_id") or item.get("area") or "")
    normalized = dict(item)
    normalized["device_id"] = device_id
    normalized["area_id"] = area_id
    normalized["display_name"] = str(item.get("name_by_user") or item.get("name") or item.get("original_name") or "")
    return normalized


def _normalize_state(state: dict[str, Any], registry_context: RegistryContext | None = None) -> NormalizedEntity:
    entity_id = str(state.get("entity_id", "") or "")
    domain, slug = entity_id.split(".", 1) if "." in entity_id else ("", entity_id)
    attrs = state.get("attributes", {}) or {}
    friendly_name = str(attrs.get("friendly_name") or entity_id)
    controller_name, capability_name = split_friendly_name(friendly_name, slug, domain)
    controller_id = _controller_id_from_slug(slug, controller_name, capability_name)
    capability_id = _capability_id(capability_name, slug, domain)
    sensor_metric = _sensor_metric_kind(domain, attrs, friendly_name, slug)
    if sensor_metric == "temperature":
        capability_id = "temperature"
        capability_name = "温度"
    elif sensor_metric == "humidity":
        capability_id = "humidity"
        capability_name = "湿度"
    registry = (registry_context.registry_by_entity_id.get(entity_id, {}) if registry_context else {}) or {}
    if registry_context and registry:
        registry_context.matched_registry_by_entity_id += 1
    area_id = str(registry.get("area_id") or "")
    device_id = str(registry.get("device_id") or "")
    area_resolved_by = "unresolved"
    if area_id:
        area_resolved_by = "entity_registry"
    resolved_by_device = False
    if not area_id and device_id and registry_context:
        device = registry_context.device_by_id.get(device_id, {}) or {}
        area_id = str(device.get("area_id") or device.get("area") or "")
        resolved_by_device = bool(area_id)
        if resolved_by_device:
            area_resolved_by = "device_registry"
    device = registry_context.device_by_id.get(device_id, {}) if registry_context and device_id else {}
    area_name = registry_context.area_name_by_id.get(area_id, "") if registry_context and area_id else ""
    if not area_name and area_id:
        area_name = area_id
    if not area_name:
        area_name = "未分区"
    if registry_context:
        if str(registry.get("ai") or registry.get("area_id") or ""):
            registry_context.entities_with_area_id += 1
        elif resolved_by_device:
            registry_context.entities_resolved_by_device_area += 1
        else:
            registry_context.entities_unresolved_area += 1
    return NormalizedEntity(
        entity_id=entity_id,
        domain=domain,
        friendly_name=friendly_name,
        state=str(state.get("state", "unknown")),
        attributes=attrs,
        controller_id=controller_id,
        controller_name=controller_name,
        capability_id=capability_id,
        capability_name=capability_name,
        area_id=area_id,
        area_name=area_name,
        device_id=device_id,
        device_name=str(device.get("display_name") or ""),
        entity_category=str(registry.get("entity_category") or ""),
        hidden_by=str(registry.get("hidden_by") or ""),
        platform=str(registry.get("platform") or ""),
        area_resolved_by=area_resolved_by,
    )


def _sensor_metric_kind(domain: str, attrs: dict[str, Any], friendly_name: str, slug: str) -> str:
    if domain != "sensor":
        return ""
    device_class = str(attrs.get("device_class") or "").lower()
    unit = str(attrs.get("unit_of_measurement") or "").lower()
    text = f"{friendly_name} {slug}".lower()
    if device_class == "temperature" or unit in {"°c", "℃", "c", "°f", "f"} or any(word in text for word in ["temperature", "temp", "温度"]):
        return "temperature"
    if device_class == "humidity" or unit == "%" or any(word in text for word in ["humidity", "湿度"]):
        return "humidity"
    return ""


def split_friendly_name(friendly_name: str, slug: str, domain: str) -> tuple[str, str]:
    name = str(friendly_name or "").strip()
    for sep in ["*", "＊", "-", "－", "—", "_"]:
        if sep in name:
            left, right = name.rsplit(sep, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()

    if name.startswith("冰箱") and len(name) > 2:
        return "冰箱", name[2:].strip()

    suffix = _suffix_from_slug(slug)
    if suffix:
        controller = slug[: -len(suffix)].strip("_")
        return _display_from_slug(controller) or name, _display_capability_from_slug(suffix, domain)

    return name, _default_capability_for_domain(domain)


def _capabilities_from_entity(entity: NormalizedEntity) -> list[Capability]:
    domain = entity.domain
    if domain in {"input_select", "select"}:
        options = [str(item) for item in entity.attributes.get("options", []) or [] if str(item)]
        if not options:
            return []
        return [Capability(
            capability_id=entity.capability_id,
            display_name=entity.capability_name,
            aliases=_capability_aliases(entity.capability_name),
            type="select",
            entity_id=entity.entity_id,
            domain=domain,
            service="select_option",
            values=[
                CapabilityValue(
                    value=option,
                    display_name=option,
                    aliases=_value_aliases(option),
                    binding=Binding(domain=domain, service="select_option", service_data={"entity_id": entity.entity_id, "option": option}),
                )
                for option in options
            ],
        )]

    if domain in {"input_boolean", "switch"}:
        return [Capability(
            capability_id=entity.capability_id,
            display_name=entity.capability_name,
            aliases=_capability_aliases(entity.capability_name),
            type="switch_like",
            entity_id=entity.entity_id,
            domain=domain,
            values=[
                CapabilityValue("on", "开", ["打开", "开启", "开开"], Binding(domain, "turn_on", {"entity_id": entity.entity_id})),
                CapabilityValue("off", "关", ["关闭", "关掉", "关了"], Binding(domain, "turn_off", {"entity_id": entity.entity_id})),
            ],
        )]

    if domain in {"input_number", "number"}:
        return [Capability(
            capability_id=entity.capability_id,
            display_name=entity.capability_name,
            aliases=_capability_aliases(entity.capability_name),
            type="number",
            entity_id=entity.entity_id,
            domain=domain,
            service="set_value",
            binding=Binding(domain, "set_value", {"entity_id": entity.entity_id}),
        )]

    if domain == "climate":
        return [_climate_capability(entity)]
    if domain == "fan":
        return [_fan_capability(entity)]
    if domain == "light":
        return _light_capabilities(entity)
    if domain == "weather":
        return [Capability(
            capability_id="weather",
            display_name="天气",
            aliases=["天气预报", "预报", "气象"],
            type="query",
            entity_id=entity.entity_id,
            domain=domain,
            exposed=True,
        )]
    if domain in {"sensor", "binary_sensor"}:
        return [Capability(
            capability_id=entity.capability_id,
            display_name=entity.capability_name,
            aliases=_capability_aliases(entity.capability_name),
            type="query",
            entity_id=entity.entity_id,
            domain=domain,
            exposed=True,
        )]
    return []


def _climate_capability(entity: NormalizedEntity) -> Capability:
    caps = Capability(
        capability_id="climate",
        display_name="空调",
        aliases=["温控", "空调"],
        type="climate",
        entity_id=entity.entity_id,
        domain="climate",
    )
    modes = [str(item) for item in entity.attributes.get("hvac_modes", []) or [] if str(item)]
    for mode in modes:
        caps.values.append(
            CapabilityValue(mode, mode, [], Binding("climate", "set_hvac_mode", {"entity_id": entity.entity_id, "hvac_mode": mode}))
        )
    return caps


def _fan_capability(entity: NormalizedEntity) -> Capability:
    return Capability(
        capability_id=entity.capability_id if entity.capability_id != "fan" else "power",
        display_name=entity.capability_name,
        aliases=_capability_aliases(entity.capability_name),
        type="switch_like",
        entity_id=entity.entity_id,
        domain="fan",
        values=[
            CapabilityValue("on", "开", ["打开", "开启"], Binding("fan", "turn_on", {"entity_id": entity.entity_id})),
            CapabilityValue("off", "关", ["关闭", "关掉"], Binding("fan", "turn_off", {"entity_id": entity.entity_id})),
        ],
    )


def _light_capabilities(entity: NormalizedEntity) -> list[Capability]:
    capabilities = [
        Capability(
            capability_id="power",
            display_name="开关",
            aliases=["电源", "开关"],
            type="switch_like",
            entity_id=entity.entity_id,
            domain="light",
            values=[
                CapabilityValue("on", "开", ["打开", "开灯"], Binding("light", "turn_on", {"entity_id": entity.entity_id})),
                CapabilityValue("off", "关", ["关闭", "关灯"], Binding("light", "turn_off", {"entity_id": entity.entity_id})),
            ],
        )
    ]
    modes = {str(item) for item in entity.attributes.get("supported_color_modes", []) or []}
    if "brightness" in entity.attributes or modes - {"onoff"}:
        capabilities.append(
            Capability(
                capability_id="brightness",
                display_name="亮度",
                aliases=["明暗", "灯光亮度"],
                type="number",
                entity_id=entity.entity_id,
                domain="light",
                binding=Binding("light", "turn_on", {"entity_id": entity.entity_id}),
            )
        )
    if (
        "color_temp" in modes
        or "color_temp_kelvin" in entity.attributes
        or "min_color_temp_kelvin" in entity.attributes
        or "max_color_temp_kelvin" in entity.attributes
    ):
        capabilities.append(
            Capability(
                capability_id="color_temperature",
                display_name="色温",
                aliases=["冷暖", "灯色", "颜色温度"],
                type="select",
                entity_id=entity.entity_id,
                domain="light",
                values=[
                    CapabilityValue("warm", "暖光", ["暖灯", "暖白", "黄光"], Binding("light", "turn_on", {"entity_id": entity.entity_id, "color_temp_kelvin": 2700})),
                    CapabilityValue("neutral", "自然光", ["中性光", "普通白"], Binding("light", "turn_on", {"entity_id": entity.entity_id, "color_temp_kelvin": 4000})),
                    CapabilityValue("cool", "冷光", ["白光", "冷白"], Binding("light", "turn_on", {"entity_id": entity.entity_id, "color_temp_kelvin": 6500})),
                ],
            )
        )
    if modes & {"hs", "rgb", "rgbw", "rgbww", "xy"} or any(key in entity.attributes for key in ["rgb_color", "hs_color", "xy_color"]):
        capabilities.append(
            Capability(
                capability_id="color",
                display_name="颜色",
                aliases=["彩光", "灯光颜色"],
                type="select",
                entity_id=entity.entity_id,
                domain="light",
                values=[
                    CapabilityValue("red", "红色", ["红光"], Binding("light", "turn_on", {"entity_id": entity.entity_id, "rgb_color": [255, 0, 0]})),
                    CapabilityValue("green", "绿色", ["绿光"], Binding("light", "turn_on", {"entity_id": entity.entity_id, "rgb_color": [0, 255, 0]})),
                    CapabilityValue("blue", "蓝色", ["蓝光"], Binding("light", "turn_on", {"entity_id": entity.entity_id, "rgb_color": [0, 0, 255]})),
                    CapabilityValue("white", "白色", ["白光"], Binding("light", "turn_on", {"entity_id": entity.entity_id, "rgb_color": [255, 255, 255]})),
                ],
            )
        )
    effects = [str(item) for item in entity.attributes.get("effect_list", []) or [] if str(item)]
    if effects:
        capabilities.append(
            Capability(
                capability_id="effect",
                display_name="灯效",
                aliases=["效果", "灯光效果"],
                type="select",
                entity_id=entity.entity_id,
                domain="light",
                values=[
                    CapabilityValue(effect, effect, [], Binding("light", "turn_on", {"entity_id": entity.entity_id, "effect": effect}))
                    for effect in effects
                ],
            )
        )
    return capabilities


def _attach_power_scripts(controllers: dict[str, Controller], scripts: list[NormalizedEntity]) -> None:
    for script in scripts:
        text = f"{script.entity_id} {script.friendly_name}".lower()
        if any(word in text for word in ["sync", "同步", "automation"]):
            continue
        controller = _find_controller_for_script(controllers, script)
        if not controller:
            continue
        power = _find_capability(controller, "power") or _find_capability_by_name(controller, "电源")
        if not power:
            continue
        if _power_has_preferred_helper(power):
            continue
        if _looks_like_on_script(text):
            if _is_suspicious_power_binding(script.entity_id):
                _mark_suspicious_power_binding(controller, script.entity_id, "on")
                continue
            _override_value_binding(power, "on", Binding("script", "turn_on", {"entity_id": script.entity_id}))
            _append_entity_source(controller, script.entity_id)
        elif _looks_like_off_script(text):
            if _is_suspicious_power_binding(script.entity_id):
                _mark_suspicious_power_binding(controller, script.entity_id, "off")
                continue
            _override_value_binding(power, "off", Binding("script", "turn_on", {"entity_id": script.entity_id}))
            _append_entity_source(controller, script.entity_id)


def _controller_from_group(
    group: EntityGroup,
    registry: RegistryContext,
    grouping_summary: dict[str, int],
) -> Controller:
    entities = sorted(group.entities, key=_entity_priority)
    primary = next((item for item in entities if not _is_internal_entity(item)), entities[0])
    area_id = next((item.area_id for item in entities if item.area_id), "")
    area_name = next((item.area_name for item in entities if item.area_name and item.area_name != "未分区"), "") or primary.area_name
    device_id = next((item.device_id for item in entities if item.device_id), "")
    display_name = _environment_display_name(area_name) if group.source == "environment" else _group_display_name(entities, registry)
    controller = Controller(
        controller_id=group.group_key,
        display_name=display_name,
        aliases=_controller_aliases_from_name(display_name, primary),
        area_id=area_id,
        area_name=area_name,
        source={
            "type": "auto_generated",
            "confidence": 0.82 if group.source == "device_id" else 0.72,
            "group_source": group.source,
            "device_id": device_id,
            "entities": [],
            "hidden_entities": [],
            "registry": {
                "area_id": area_id,
                "area_name": area_name,
                "device_id": device_id,
                "area_resolved_by": primary.area_resolved_by,
            },
        },
    )
    if group.source == "device_id":
        grouping_summary["controllers_built_from_device_id"] += 1
    elif group.source == "environment":
        grouping_summary["controllers_built_from_environment"] += 1
    elif group.source == "prefix":
        grouping_summary["controllers_built_from_prefix"] += 1
    else:
        grouping_summary["standalone_controllers"] += 1

    for entity in entities:
        is_hidden = _is_internal_entity(entity)
        _append_entity_source(controller, entity.entity_id)
        if is_hidden:
            grouping_summary["entities_hidden_as_config_diagnostic_internal"] += 1
            controller.source.setdefault("hidden_entities", []).append(entity.entity_id)
        for capability in _capabilities_from_entity(entity):
            if is_hidden:
                capability.exposed = False
            _add_or_replace_capability(controller, capability)
    return controller


def _group_display_name(entities: list[NormalizedEntity], registry: RegistryContext) -> str:
    device_id = next((item.device_id for item in entities if item.device_id), "")
    if device_id:
        device = registry.device_by_id.get(device_id, {})
        device_name = str(device.get("display_name") or "").strip()
        if device_name and not _is_internal_name(device_name):
            return device_name
    prefix = _common_prefix_from_group(entities)
    if prefix:
        return prefix
    primary = next((item for item in entities if item.domain == "light"), None)
    primary = primary or next((item for item in entities if not _is_internal_entity(item)), entities[0])
    return primary.controller_name or primary.friendly_name


def _environment_display_name(area_name: str) -> str:
    name = str(area_name or "").strip()
    if name and name != "未分区":
        return f"{name}环境"
    return "环境"


def _controller_aliases_from_name(name: str, primary: NormalizedEntity) -> list[str]:
    aliases = [name, primary.controller_name]
    if name.endswith("空调"):
        aliases.extend(["空调", "冷气"])
    if name.endswith("灯"):
        aliases.extend(["灯", "灯光"])
    if name.endswith("环境"):
        room = name[: -len("环境")]
        aliases.extend(["环境", "温湿度", "温度", "湿度"])
        if room:
            aliases.extend([f"{room}温度", f"{room}湿度", f"{room}温湿度"])
    return list(dict.fromkeys(item for item in aliases if item))


def _entity_priority(entity: NormalizedEntity) -> tuple[int, str]:
    if _is_internal_entity(entity):
        return (9, entity.entity_id)
    if entity.domain == "light":
        return (0, entity.entity_id)
    if entity.domain in {"climate", "fan"}:
        return (1, entity.entity_id)
    if entity.domain in {"switch", "input_boolean", "select", "input_select", "number", "input_number"}:
        return (2, entity.entity_id)
    if entity.domain in {"sensor", "binary_sensor"}:
        return (5, entity.entity_id)
    return (7, entity.entity_id)


def _is_internal_entity(entity: NormalizedEntity) -> bool:
    if entity.hidden_by:
        return True
    if entity.entity_category in {"config", "diagnostic"}:
        return True
    return _is_internal_name(f"{entity.friendly_name} {entity.entity_id} {entity.capability_name}")


def _is_internal_name(text: str) -> bool:
    normalized = str(text or "").lower()
    keywords = [
        "功能设置",
        "参数重置",
        "默认上电状态",
        "遥控器 添加遥控器",
        "遥控器 删除遥控器",
        "遥控器 遥控",
        "最低亮度",
        "渐变时间",
        "dimming",
        "字节[",
        "config",
        "diagnostic",
    ]
    return any(keyword.lower() in normalized for keyword in keywords)


def _pending_script(entity: NormalizedEntity) -> dict[str, Any]:
    return {
        "pending_id": entity.entity_id,
        "type": "script",
        "entity_id": entity.entity_id,
        "friendly_name": entity.friendly_name,
        "area_id": entity.area_id,
        "area_name": entity.area_name,
        "reason": "script 默认不全量暴露，需要匹配到已有控制器或由用户整理。",
    }


def _controller_group_key(entity: NormalizedEntity) -> tuple[str, str]:
    area_prefix = _area_group_prefix(entity)
    if _sensor_metric_kind(entity.domain, entity.attributes, entity.friendly_name, entity.entity_id) and area_prefix:
        return f"{area_prefix}environment", "environment"
    if entity.device_id:
        return f"{area_prefix}device__{_slugify(entity.device_id)}", "device_id"
    prefix = _friendly_prefix(entity.friendly_name)
    if prefix:
        return f"{area_prefix}prefix__{_slugify(prefix)}", "prefix"
    return f"{area_prefix}standalone__{entity.controller_id}", "standalone"


def _area_group_prefix(entity: NormalizedEntity) -> str:
    if entity.area_id:
        return f"{_slugify(entity.area_id)}__"
    if entity.area_name and entity.area_name != "未分区":
        return f"{_slugify(entity.area_name)}__"
    return ""


def _friendly_prefix(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    patterns = [
        r"^(.+?)\s*[*＊]\s*.+$",
        r"^(.+?)\s*[-－—]\s*.+$",
        r"^(.+?)\s+功能设置\s+.+$",
        r"^(.+?)\s+遥控器\s+.+$",
        r"^(.+?)\s+智能场景\s+.+$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            prefix = match.group(1).strip()
            if len(prefix) >= 2:
                return prefix
    return ""


def _common_prefix_from_group(entities: list[NormalizedEntity]) -> str:
    prefixes = [_friendly_prefix(item.friendly_name) for item in entities]
    prefixes = [item for item in prefixes if item]
    if prefixes:
        counts: dict[str, int] = defaultdict(int)
        for prefix in prefixes:
            counts[prefix] += 1
        return sorted(counts.items(), key=lambda item: (-item[1], len(item[0])))[0][0]
    names = [item.controller_name for item in entities if item.controller_name]
    if not names:
        return ""
    shortest = min(names, key=len)
    common = shortest
    for name in names:
        while common and not name.startswith(common):
            common = common[:-1]
    common = common.strip()
    return common if len(common) >= 2 else ""


def _find_controller_for_script(controllers: dict[str, Controller], script: NormalizedEntity) -> Controller | None:
    script_key, _ = _controller_group_key(script)
    direct = controllers.get(script_key) or controllers.get(script.controller_id)
    if direct:
        return direct
    matches = [
        controller
        for key, controller in controllers.items()
        if key.endswith(f"__{script.controller_id}") or controller.controller_id.endswith(f"__{script.controller_id}")
    ]
    if len(matches) == 1:
        return matches[0]
    if script.area_id:
        area_matches = [controller for controller in matches if controller.area_id == script.area_id]
        if len(area_matches) == 1:
            return area_matches[0]
    return None


def _registry_summary(registry: RegistryContext) -> dict[str, Any]:
    raw_types = registry.raw_types or {}
    return {
        "websocket_auth_success": registry.auth_success,
        "entity_registry_raw_type": raw_types.get("entity_registry", ""),
        "entity_registry_parsed_count": len(registry.registry_by_entity_id),
        "area_registry_raw_type": raw_types.get("area_registry", ""),
        "area_registry_parsed_count": len(registry.area_name_by_id),
        "device_registry_raw_type": raw_types.get("device_registry", ""),
        "device_registry_parsed_count": len(registry.device_by_id),
        "states_count": registry.states_count,
        "matched_registry_by_entity_id_count": registry.matched_registry_by_entity_id,
        "entities_with_direct_area_id_count": registry.entities_with_area_id,
        "entities_resolved_by_device_area_count": registry.entities_resolved_by_device_area,
        "entities_still_unresolved_count": registry.entities_unresolved_area,
    }


def _log_registry_summary(registry: RegistryContext, normalized: list[NormalizedEntity]) -> None:
    summary = _registry_summary(registry)
    LOGGER.info(
        "[HA Controller Index] registry scan:\n"
        "- websocket auth success: %s\n"
        "- entity_registry raw type: %s\n"
        "- entity_registry parsed count: %s\n"
        "- area_registry raw type: %s\n"
        "- area_registry parsed count: %s\n"
        "- device_registry raw type: %s\n"
        "- device_registry parsed count: %s\n"
        "- states count: %s\n"
        "- matched registry by entity_id count: %s\n"
        "- entities with direct area_id count: %s\n"
        "- entities resolved by device area count: %s\n"
        "- entities still unresolved count: %s",
        summary["websocket_auth_success"],
        summary["entity_registry_raw_type"],
        summary["entity_registry_parsed_count"],
        summary["area_registry_raw_type"],
        summary["area_registry_parsed_count"],
        summary["device_registry_raw_type"],
        summary["device_registry_parsed_count"],
        summary["states_count"],
        summary["matched_registry_by_entity_id_count"],
        summary["entities_with_direct_area_id_count"],
        summary["entities_resolved_by_device_area_count"],
        summary["entities_still_unresolved_count"],
    )
    if registry.warnings:
        LOGGER.warning("[HA Controller Index] registry scan warnings: %s", "; ".join(registry.warnings))
    if normalized and all(item.area_name == "未分区" for item in normalized):
        LOGGER.warning("[HA Controller Index] 未读取到 HA Area 信息，可能是 WebSocket registry 扫描失败。")


def _log_grouping_summary(grouping_summary: dict[str, int], controllers: dict[str, Controller]) -> None:
    living_light_count = _source_count_for_controller(controllers, "客厅灯")
    LOGGER.info(
        "[HA Controller Index] controller grouping:\n"
        "- total entities: %s\n"
        "- total device_id groups: %s\n"
        "- controllers built from device_id: %s\n"
        "- controllers built from environment: %s\n"
        "- controllers built from prefix: %s\n"
        "- standalone controllers: %s\n"
        "- entities hidden as config/diagnostic/internal: %s\n"
        "- controller \"客厅灯\" source_entities count: %s",
        grouping_summary.get("total_entities", 0),
        grouping_summary.get("total_device_id_groups", 0),
        grouping_summary.get("controllers_built_from_device_id", 0),
        grouping_summary.get("controllers_built_from_environment", 0),
        grouping_summary.get("controllers_built_from_prefix", 0),
        grouping_summary.get("standalone_controllers", 0),
        grouping_summary.get("entities_hidden_as_config_diagnostic_internal", 0),
        living_light_count,
    )


def _source_count_for_controller(controllers: dict[str, Controller], display_name: str) -> int:
    for controller in controllers.values():
        if controller.display_name == display_name:
            return len(controller.source.get("entities", []) or [])
    return 0


def _add_or_replace_capability(controller: Controller, capability: Capability) -> None:
    existing = _find_capability(controller, capability.capability_id)
    if existing is None:
        controller.capabilities.append(capability)
        return
    if capability.values and not existing.values:
        existing.values = capability.values
    if not existing.entity_id and capability.entity_id:
        existing.entity_id = capability.entity_id
    if not existing.domain and capability.domain:
        existing.domain = capability.domain
    if not existing.service and capability.service:
        existing.service = capability.service


def _find_capability(controller: Controller, capability_id: str) -> Capability | None:
    return next((item for item in controller.capabilities if item.capability_id == capability_id), None)


def _find_capability_by_name(controller: Controller, name: str) -> Capability | None:
    return next((item for item in controller.capabilities if item.display_name == name), None)


def _override_value_binding(capability: Capability, value: str, binding: Binding) -> None:
    for item in capability.values:
        if item.value == value:
            item.binding = binding
            return
    display = "开" if value == "on" else "关"
    capability.values.append(CapabilityValue(value=value, display_name=display, binding=binding))


def _append_entity_source(controller: Controller, entity_id: str) -> None:
    entities = controller.source.setdefault("entities", [])
    if entity_id not in entities:
        entities.append(entity_id)


def _looks_like_on_script(text: str) -> bool:
    if _looks_like_off_script(text):
        return False
    return bool(
        re.search(r"(^|[._\-\s])power[_\-\s]*on($|[._\-\s])", text)
        or any(word in text for word in ["电源开启", "电源打开", "开机", "空调开启", "空调打开"])
    )


def _looks_like_off_script(text: str) -> bool:
    return bool(
        re.search(r"(^|[._\-\s])power[_\-\s]*off($|[._\-\s])", text)
        or any(word in text for word in ["电源关闭", "电源关掉", "关机", "空调关闭", "空调关掉"])
    )


def _power_has_preferred_helper(power: Capability) -> bool:
    return _has_helper_binding(power, "on") and _has_helper_binding(power, "off")


def _has_helper_binding(power: Capability, value: str) -> bool:
    item = next((candidate for candidate in power.values if candidate.value == value), None)
    binding = item.binding if item else None
    if not binding:
        return False
    entity_id = str(binding.service_data.get("entity_id", "") or "")
    return binding.domain in {"input_boolean", "switch"} and _is_power_entity(entity_id)


def _is_power_entity(entity_id: str) -> bool:
    text = str(entity_id or "").lower()
    return bool(re.search(r"(^|[._-])power($|[._-])", text)) or "电源" in text


def _is_suspicious_power_binding(entity_id: str) -> bool:
    text = str(entity_id or "").lower()
    return any(keyword in text for keyword in POWER_MISBINDING_KEYWORDS)


def _mark_suspicious_power_binding(controller: Controller, entity_id: str, value: str) -> None:
    warning = {
        "capability_id": "power",
        "value": value,
        "entity_id": entity_id,
        "reason": "疑似误绑：电源能力不能绑定到模式/静眠/风向/强力安静等脚本。",
    }
    controller.source.setdefault("binding_warnings", []).append(warning)
    LOGGER.warning(
        "[HA Controller Index] suspicious power binding skipped: controller=%s value=%s entity_id=%s",
        controller.display_name,
        value,
        entity_id,
    )


def _sanitize_power_bindings(controllers: dict[str, Controller]) -> None:
    for controller in controllers.values():
        power = _find_capability(controller, "power") or _find_capability_by_name(controller, "电源")
        if not power:
            continue
        for item in power.values:
            entity_id = _binding_entity_id(item.binding)
            if entity_id and _is_suspicious_power_binding(entity_id):
                _mark_suspicious_power_binding(controller, entity_id, item.value)
                item.binding = None


def _log_power_selections(controllers: dict[str, Controller]) -> None:
    for controller in controllers.values():
        power = _find_capability(controller, "power") or _find_capability_by_name(controller, "电源")
        if not power:
            continue
        on_binding = _value_binding(power, "on")
        off_binding = _value_binding(power, "off")
        reason = "prefer power helper entity" if _power_has_preferred_helper(power) else "strict explicit power script or native domain"
        source_entity = _binding_entity_id(on_binding) or _binding_entity_id(off_binding) or power.entity_id
        LOGGER.info(
            "[HA Controller Index] power capability selected: %s\n"
            "- source entity: %s\n"
            "- on binding: %s\n"
            "- off binding: %s\n"
            "- reason: %s",
            controller.display_name,
            source_entity,
            _binding_label(on_binding),
            _binding_label(off_binding),
            reason,
        )


def _value_binding(power: Capability, value: str) -> Binding | None:
    item = next((candidate for candidate in power.values if candidate.value == value), None)
    return item.binding if item else None


def _binding_entity_id(binding: Binding | None) -> str:
    if not binding:
        return ""
    return str(binding.service_data.get("entity_id", "") or "")


def _binding_label(binding: Binding | None) -> str:
    if not binding:
        return "missing"
    entity_id = _binding_entity_id(binding)
    return f"{binding.domain}.{binding.service} {entity_id}".strip()


def _controller_aliases(entity: NormalizedEntity) -> list[str]:
    aliases = [entity.controller_name]
    if entity.controller_name.endswith("空调"):
        aliases.extend(["空调", "冷气"])
    return list(dict.fromkeys(item for item in aliases if item))


def _capability_aliases(name: str) -> list[str]:
    mapping = {
        "电源": ["开关"],
        "风速": ["风量"],
        "温度": ["几度", "多少度"],
        "模式": ["工作模式"],
        "风向": ["摆风", "扫风"],
        "亮度": ["明暗", "灯光亮度"],
        "色温": ["冷暖", "灯色", "颜色温度"],
        "湿度": ["潮湿", "干不干", "湿不湿"],
    }
    return mapping.get(name, [])


def _value_aliases(value: str) -> list[str]:
    mapping = {
        "自由风": ["自然风", "自动风", "随便吹"],
        "强风": ["高风", "大风"],
        "低风": ["小风", "轻风"],
        "除湿": ["干燥"],
        "制冷": ["冷风"],
        "制热": ["暖风"],
    }
    return mapping.get(str(value), [])


def _controller_id_from_slug(slug: str, controller_name: str, capability_name: str) -> str:
    if slug.endswith("_power_on") or slug.endswith("_power_off"):
        base = slug.rsplit("_power_", 1)[0]
        if base:
            return _slugify(base)
    suffix = _suffix_from_slug(slug)
    if suffix:
        base = slug[: -len(suffix)].strip("_")
        if base:
            return _slugify(base)
    if controller_name:
        return _slugify(controller_name)
    return _slugify(slug)


def _capability_id(name: str, slug: str, domain: str) -> str:
    normalized = name.strip().lower()
    if normalized in {"开机", "关机", "开启", "关闭"} or slug.endswith("_power_on") or slug.endswith("_power_off"):
        return "power"
    known = {
        "电源": "power",
        "开关": "power",
        "温度": "temperature",
        "模式": "mode",
        "风速": "fan",
        "风量": "fan",
        "风向": "swing",
        "摆风": "swing",
        "静眠": "sleep",
        "睡眠": "sleep",
        "除甲醛": "formaldehyde",
        "辅热": "aux_heat",
        "珍品变温": "zone",
    }
    if normalized in known:
        return known[normalized]
    suffix = _suffix_from_slug(slug)
    if suffix:
        return _slugify(suffix)
    return _slugify(_default_capability_for_domain(domain))


def _suffix_from_slug(slug: str) -> str:
    suffixes = [
        "temperature",
        "temp",
        "power",
        "mode",
        "fan",
        "swing",
        "sleep",
        "formaldehyde",
        "aux_heat",
        "health_airflow",
        "strong_quiet",
        "brightness",
        "humidity",
    ]
    for suffix in suffixes:
        if slug.endswith("_" + suffix):
            return suffix
    return ""


def _display_capability_from_slug(suffix: str, domain: str) -> str:
    mapping = {
        "temperature": "温度",
        "temp": "温度",
        "power": "电源",
        "mode": "模式",
        "fan": "风速",
        "swing": "风向",
        "sleep": "静眠",
        "formaldehyde": "除甲醛",
        "aux_heat": "辅热",
        "health_airflow": "健康气流",
        "strong_quiet": "强力安静",
        "brightness": "亮度",
        "humidity": "湿度",
    }
    return mapping.get(suffix, _default_capability_for_domain(domain))


def _default_capability_for_domain(domain: str) -> str:
    return {
        "light": "开关",
        "switch": "开关",
        "input_boolean": "开关",
        "fan": "开关",
        "sensor": "状态",
        "binary_sensor": "状态",
        "climate": "空调",
        "weather": "天气",
    }.get(domain, "状态")


def _display_from_slug(slug: str) -> str:
    if not slug:
        return ""
    parts = [part for part in slug.split("_") if part]
    mapping = {
        "bedroom": "卧室",
        "living": "客厅",
        "room": "",
        "ac": "空调",
        "fridge": "冰箱",
        "kitchen": "厨房",
        "light": "灯",
    }
    translated = "".join(mapping.get(part, part) for part in parts)
    return translated or slug


def _slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "controller"
    if re.fullmatch(r"[a-z0-9_ .-]+", text):
        return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "controller"
    return "c_" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
