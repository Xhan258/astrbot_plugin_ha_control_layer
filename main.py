"""AstrBot Home Assistant semantic controller index plugin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from astrbot.api import FunctionTool, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .discovery import ControllerScanner
from .executor import SafeExecutor
from .index import IndexStore
from .matcher import IntentMatcher, parse_intent
from .modules.homeassistant import HomeAssistantClient
from .modules.permissions import PermissionChecker, PermissionConfig

PLUGIN_VERSION = "1.1.7"
PLUGIN_NAME = "astrbot_plugin_ha_control_layer"
LEGACY_PLUGIN_NAME = "home_assistant_control_layer"

DEFAULT_CONTROL_DOMAINS = {
    "climate",
    "fan",
    "input_boolean",
    "input_number",
    "input_select",
    "light",
    "number",
    "scene",
    "script",
    "select",
    "switch",
}

BLOCKED_SERVICE_DOMAINS = {
    "alarm_control_panel",
    "camera",
    "command_line",
    "hassio",
    "lock",
    "python_script",
    "pyscript",
    "rest_command",
    "shell_command",
    "siren",
}


def _config_get(config: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in config:
        return config.get(key, default)
    for section_name in ["basic", "advanced"]:
        section = config.get(section_name)
        if isinstance(section, dict) and key in section:
            return section.get(key, default)
    return default


class HATool(FunctionTool):
    def __init__(self, plugin: "HomeAssistantControlLayerPlugin") -> None:
        super().__init__(
            name="ha_execute_intent",
            description=(
                "Home Assistant 控制器唯一入口。所有智能家居、HA、灯、空调、冰箱、风扇、窗帘、"
                "天气或传感器查询都必须调用本工具。不要使用 shell/curl/python/file_read，也不要读取 HA token。"
                "本工具会根据 ControllerIndex 匹配控制器和能力，必要时内部安全调用 Home Assistant。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "用户原话，例如：把空调调到25度、空调开除湿、冰箱珍品变温改成蛋类。",
                    }
                },
                "required": ["text"],
            },
            handler=None,
        )
        self.plugin = plugin

    async def call(self, context: Any, **kwargs: Any) -> str:
        event = context.context.event
        try:
            return await self.plugin.execute_intent(event, str(kwargs.get("text", "") or ""))
        except Exception as exc:  # noqa: BLE001
            logger.error("[HA Controller Index] ha_execute_intent failed: %s", exc, exc_info=True)
            return json.dumps({"success": False, "message": f"HA 控制层执行失败：{exc}"}, ensure_ascii=False)


@register(
    PLUGIN_NAME,
    "local",
    "Home Assistant 控制器",
    PLUGIN_VERSION,
    "https://github.com/Xhan258/astrbot_plugin_ha_control_layer",
)
class HomeAssistantControlLayerPlugin(Star):
    """Build a Home Assistant controller index and expose one semantic LLM tool."""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        cfg = lambda key, default=None: _config_get(self.config, key, default)

        self.ha_url = str(cfg("home_assistant_url", "") or cfg("ha_url", "") or "").strip()
        self.ha_token = str(cfg("ha_token", "") or cfg("token", "") or "").strip()
        self.timeout = int(cfg("request_timeout", 10) or 10)
        self.confidence_threshold = float(cfg("confidence_threshold", 0.62) or 0.62)
        self.data_dir = Path(__file__).parent / "data"

        self.client: HomeAssistantClient | None = None
        if self.ha_url and self.ha_token:
            self.client = HomeAssistantClient(self.ha_url, self.ha_token, timeout=self.timeout)

        self.permissions = PermissionChecker(
            PermissionConfig(
                admin_users=list(cfg("admin_users", []) or []),
                admin_groups=list(cfg("admin_groups", []) or []),
                allow_query_without_admin=bool(cfg("allow_query_without_admin", True)),
            )
        )
        self.allowed_domains = {
            _normalize_domain(item)
            for item in (cfg("allowed_control_domains", []) or DEFAULT_CONTROL_DOMAINS)
            if _normalize_domain(item)
        }
        self.blocked_domains = {
            _normalize_domain(item)
            for item in (cfg("blocked_service_domains", []) or BLOCKED_SERVICE_DOMAINS)
            if _normalize_domain(item)
        }
        self.dangerous_entities = {str(item) for item in (cfg("dangerous_entities", []) or [])}

        self.store = IndexStore(self.data_dir)
        self.scanner = ControllerScanner(existing_aliases=cfg("entity_aliases", []))
        self.matcher = IntentMatcher(confidence_threshold=self.confidence_threshold)

        self.context.add_llm_tools(HATool(self))
        self._register_web_api_if_available()

    @filter.command("ha_check")
    async def ha_check(self, event: AstrMessageEvent):
        if not self.client:
            yield event.plain_result("Home Assistant 未配置：请填写 Home Assistant 地址和长期访问令牌。")
            return
        try:
            status = await self.client.api_status()
            yield event.plain_result(f"Home Assistant 连接正常：{status}")
        except Exception as exc:  # noqa: BLE001
            yield event.plain_result(f"Home Assistant 连接失败：{exc}")

    @filter.command("ha_rescan")
    async def ha_rescan(self, event: AstrMessageEvent):
        if not self.client:
            yield event.plain_result("Home Assistant 未配置。")
            return
        if not self.permissions.can_control(event):
            yield event.plain_result("没有刷新 Home Assistant 控制器索引的权限。")
            return
        index = await self._rescan()
        yield event.plain_result(f"已扫描 Home Assistant：{len(index.controllers)} 个控制器，{len(index.pending)} 个待整理项。")

    @filter.command("ha_index")
    async def ha_index(self, event: AstrMessageEvent):
        index = await self._effective_index()
        lines = [f"控制器索引：{len(index.controllers)} 个控制器"]
        for controller in index.controllers[:20]:
            caps = "、".join(cap.display_name for cap in controller.capabilities if cap.exposed) or "无暴露能力"
            lines.append(f"- {controller.display_name}: {caps}")
        yield event.plain_result("\n".join(lines))

    @filter.command("ha_version")
    async def ha_version(self, event: AstrMessageEvent):
        yield event.plain_result(
            "Home Assistant 控制器\n"
            f"v{PLUGIN_VERSION}\n"
            "架构：ControllerIndex + IntentMatcher + SafeExecutor\n"
            "LLM Tool：ha_execute_intent"
        )

    async def execute_intent(self, event: AstrMessageEvent, text: str) -> str:
        if not self.client:
            return _json({"success": False, "message": "Home Assistant 未配置。"})
        if not self.permissions.can_query(event):
            return _json({"success": False, "message": "没有查询 Home Assistant 的权限。"})

        slots = parse_intent(text)
        index = await self._effective_index()
        match = self.matcher.match(index, slots)

        if match.need_clarification:
            return _json(
                {
                    "success": False,
                    "executed": False,
                    "need_clarification": True,
                    "message": match.message,
                    "candidates": match.candidates or [],
                    "intent": slots.__dict__,
                }
            )
        if not match.matched:
            return _json({"success": False, "executed": False, "message": match.message or "未匹配到 Home Assistant 控制器。"})

        if slots.is_query or slots.action == "query" or (match.capability and match.capability.type == "query"):
            return _json(await self._query_result(match, slots))

        if not self.permissions.can_control(event):
            return _json({"success": False, "executed": False, "message": "没有控制 Home Assistant 的权限。"})
        if not match.binding or not match.controller or not match.capability:
            return _json({"success": False, "executed": False, "message": "匹配到了能力，但缺少可执行绑定。"})

        executor = SafeExecutor(
            self.client,
            allowed_domains=self.allowed_domains,
            blocked_domains=self.blocked_domains,
            dangerous_entities=self.dangerous_entities,
        )
        result = await executor.execute(
            controller=match.controller,
            capability=match.capability,
            value=match.value,
            binding=match.binding,
        )
        return _json(
            {
                "success": result.success,
                "executed": result.success,
                "controller": match.controller.display_name,
                "capability": match.capability.display_name,
                "value": match.value.display_name if match.value else "",
                "confidence": match.confidence,
                "message": result.message,
                "execution": result.to_dict(),
                "reply_hint": "请用自然语言回复用户，不要贴 JSON，不要继续调用其他工具。",
            }
        )

    async def _query_result(self, match: Any, slots: Any) -> dict[str, Any]:
        if not match.capability or not match.capability.entity_id:
            return {"success": False, "executed": False, "message": "这个查询能力没有对应实体。"}
        if match.capability.domain == "weather":
            return await self._weather_query_result(match, slots)
        state = await self.client.get_state(match.capability.entity_id)
        return {
            "success": True,
            "executed": False,
            "query": True,
            "controller": match.controller.display_name if match.controller else "",
            "capability": match.capability.display_name,
            "entity_id": match.capability.entity_id,
            "state": state.get("state"),
            "attributes": _safe_attrs(state.get("attributes", {}) or {}),
            "message": f"{match.controller.display_name if match.controller else '设备'}{match.capability.display_name}当前是 {state.get('state')}。",
        }

    async def _weather_query_result(self, match: Any, slots: Any) -> dict[str, Any]:
        entity_id = match.capability.entity_id
        state = await self.client.get_state(entity_id)
        current = {
            "condition": state.get("state"),
            "attributes": _weather_attrs(state.get("attributes", {}) or {}),
        }
        result = {
            "success": True,
            "executed": False,
            "query": True,
            "type": "weather",
            "controller": match.controller.display_name if match.controller else "",
            "capability": match.capability.display_name,
            "entity_id": entity_id,
            "current": current,
            "message": f"{match.controller.display_name if match.controller else '天气'}当前天气是 {state.get('state')}。",
            "reply_hint": "请用自然语言概括天气，不要直接贴 JSON。",
        }
        if _needs_weather_forecast(slots.text):
            try:
                response = await self.client.call_service(
                    "weather",
                    "get_forecasts",
                    {"entity_id": entity_id, "type": "daily"},
                    return_response=True,
                )
                result["type"] = "weather_forecast"
                result["forecast"] = _extract_weather_forecast(response, entity_id)
                result["message"] = f"已从 Home Assistant 查询 {match.controller.display_name if match.controller else '天气'} 的天气预报。"
            except Exception as exc:  # noqa: BLE001
                result["forecast_error"] = str(exc)
                result["message"] = f"已查到当前天气，但天气预报查询失败：{exc}"
        return result

    async def _effective_index(self):
        generated = self.store.load_generated()
        if not generated.controllers and self.client:
            generated = await self._rescan()
        return self.store.effective_index()

    async def _rescan(self):
        index = await self.scanner.scan(self.client)
        self.store.save_generated(index)
        return index

    def _register_web_api_if_available(self) -> None:
        register_api = getattr(self.context, "register_web_api", None)
        if not callable(register_api):
            return
        try:
            for plugin_name in [PLUGIN_NAME, LEGACY_PLUGIN_NAME]:
                register_api(f"/{plugin_name}/controllers", self._api_controllers, ["GET"], "List HA controller index")
                register_api(f"/{plugin_name}/rescan", self._api_rescan, ["POST"], "Rescan Home Assistant")
                register_api(f"/{plugin_name}/pending", self._api_pending, ["GET"], "List pending HA items")
                register_api(
                    f"/{plugin_name}/controllers/<controller_id>",
                    self._api_update_controller,
                    ["POST"],
                    "Update HA controller override",
                )
                register_api(
                    f"/{plugin_name}/controllers/<controller_id>/capabilities/<capability_id>",
                    self._api_update_capability,
                    ["POST"],
                    "Update HA capability override",
                )
                register_api(
                    f"/{plugin_name}/controllers/<controller_id>/capabilities/<capability_id>/values/<value_id>",
                    self._api_update_value,
                    ["POST"],
                    "Update HA value aliases",
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HA Controller Index] register_web_api unavailable: %s", exc)

    async def _api_controllers(self, *args: Any, **kwargs: Any):
        return self.store.effective_index().to_dict()

    async def _api_rescan(self, *args: Any, **kwargs: Any):
        if not self.client:
            return {"success": False, "message": "Home Assistant 未配置。"}
        index = await self._rescan()
        data = self.store.effective_index().to_dict()
        data.update({"success": True, "controllers_count": len(index.controllers), "pending_count": len(index.pending)})
        return data

    async def _api_pending(self, *args: Any, **kwargs: Any):
        return {"pending": self.store.effective_index().pending}

    async def _api_update_controller(self, *args: Any, **kwargs: Any):
        controller_id = str(kwargs.get("controller_id", "") or "")
        payload = await _extract_payload(args, kwargs)
        overrides = self.store.load_overrides()
        controllers = overrides.setdefault("controllers", {})
        item = controllers.setdefault(controller_id, {})
        for key in ["display_name", "aliases", "exposed", "area_name"]:
            if key in payload:
                item[key] = payload[key]
        self.store.save_overrides(overrides)
        return {"success": True}

    async def _api_update_capability(self, *args: Any, **kwargs: Any):
        controller_id = str(kwargs.get("controller_id", "") or "")
        capability_id = str(kwargs.get("capability_id", "") or "")
        payload = await _extract_payload(args, kwargs)
        overrides = self.store.load_overrides()
        cap = overrides.setdefault("controllers", {}).setdefault(controller_id, {}).setdefault("capabilities", {}).setdefault(capability_id, {})
        for key in ["display_name", "aliases", "exposed"]:
            if key in payload:
                cap[key] = payload[key]
        self.store.save_overrides(overrides)
        return {"success": True}

    async def _api_update_value(self, *args: Any, **kwargs: Any):
        controller_id = str(kwargs.get("controller_id", "") or "")
        capability_id = str(kwargs.get("capability_id", "") or "")
        value_id = str(kwargs.get("value_id", "") or "")
        payload = await _extract_payload(args, kwargs)
        overrides = self.store.load_overrides()
        value = (
            overrides.setdefault("controllers", {})
            .setdefault(controller_id, {})
            .setdefault("capabilities", {})
            .setdefault(capability_id, {})
            .setdefault("values", {})
            .setdefault(value_id, {})
        )
        if "aliases" in payload:
            value["aliases"] = payload["aliases"]
        self.store.save_overrides(overrides)
        return {"success": True}

    async def terminate(self):
        return None


def _normalize_domain(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    keys = ["friendly_name", "unit_of_measurement", "device_class", "temperature", "humidity", "options"]
    return {key: attrs[key] for key in keys if key in attrs}


def _weather_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "friendly_name",
        "temperature",
        "humidity",
        "pressure",
        "wind_bearing",
        "wind_speed",
        "visibility",
        "ozone",
        "uv_index",
        "precipitation",
    ]
    return {key: attrs[key] for key in keys if key in attrs}


def _needs_weather_forecast(text: str) -> bool:
    return any(word in str(text or "") for word in ["预报", "未来", "近几天", "这几天", "几天", "明天", "后天", "一周", "7天", "七天"])


def _extract_weather_forecast(response: Any, entity_id: str) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    payload = response.get("service_response", response)
    if isinstance(payload, dict):
        candidates = [
            payload.get(entity_id),
            payload.get("forecast"),
            payload.get("forecasts"),
        ]
        for value in candidates:
            forecast = _forecast_list(value)
            if forecast:
                return forecast
        for value in payload.values():
            forecast = _forecast_list(value)
            if forecast:
                return forecast
    return []


def _forecast_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        forecast = value.get("forecast")
        if isinstance(forecast, list):
            return [item for item in forecast if isinstance(item, dict)]
    return []


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


async def _extract_payload(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    for value in [kwargs.get("json"), kwargs.get("data"), kwargs.get("body"), *args]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
    try:
        from astrbot.api.web import request as web_request

        payload = await web_request.json(default={})
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    try:
        from quart import request as quart_request

        payload = await quart_request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}
