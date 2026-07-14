"""AstrBot Home Assistant semantic controller index plugin."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
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

PLUGIN_VERSION = "1.1.9"
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
                "传感器查询都必须调用本工具。不要使用 shell/curl/python/file_read，也不要读取 HA token。"
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


class HAWeatherTool(FunctionTool):
    def __init__(self, plugin: "HomeAssistantControlLayerPlugin") -> None:
        super().__init__(
            name="ha_query_weather",
            description=(
                "只读查询 Home Assistant 天气。用户询问家里天气、最近天气、天气预报、明天后天、"
                "近几天有没有雨、温度湿度风速时优先调用本工具，不要先使用网页搜索。"
                "本工具只读取 HA weather 实体和 weather.get_forecasts，不控制任何设备。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "用户原话，例如：最近天气怎么样、明天有没有雨、这几天热不热。",
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
            return await self.plugin.query_weather(event, str(kwargs.get("text", "") or ""))
        except Exception as exc:  # noqa: BLE001
            logger.error("[HA Controller Index] ha_query_weather failed: %s", exc, exc_info=True)
            return json.dumps({"success": False, "message": f"HA 天气查询失败：{exc}"}, ensure_ascii=False)


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
        self.context.add_llm_tools(HAWeatherTool(self))
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
            "LLM Tool：ha_execute_intent, ha_query_weather"
        )

    async def query_weather(self, event: AstrMessageEvent, text: str) -> str:
        if not self.client:
            return _json({"success": False, "message": "Home Assistant 未配置。"})
        if not self.permissions.can_query(event):
            return _json({"success": False, "message": "没有查询 Home Assistant 天气的权限。"})

        slots = parse_intent(text)
        index = await self._effective_index()
        candidates = _weather_candidates(index)
        if not candidates:
            return _json(
                {
                    "success": False,
                    "message": "没有在 Home Assistant 控制器索引里找到 weather 天气实体。请确认 HA 中存在 weather.xxx，并执行 /ha_rescan。",
                }
            )
        ranked = _rank_weather_candidates(candidates, text)
        if len(ranked) > 1 and ranked[0][0] < 0.86 and ranked[0][0] - ranked[1][0] < 0.08:
            return _json(
                {
                    "success": False,
                    "need_clarification": True,
                    "message": "你想查哪个天气？",
                    "candidates": [controller.display_name for _, controller, _ in ranked[:5]],
                }
            )

        _, controller, capability = ranked[0]
        result = await self._weather_query_result(
            SimpleNamespace(controller=controller, capability=capability),
            slots,
        )
        result["tool"] = "ha_query_weather"
        return _json(result)

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
        if _needs_environment_summary(match, slots):
            return await self._environment_query_result(match, slots)
        state = await self.client.get_state(match.capability.entity_id)
        attrs = state.get("attributes", {}) or {}
        unit = attrs.get("unit_of_measurement", "")
        unit_text = str(unit or "")
        return {
            "success": True,
            "executed": False,
            "query": True,
            "controller": match.controller.display_name if match.controller else "",
            "capability": match.capability.display_name,
            "entity_id": match.capability.entity_id,
            "state": state.get("state"),
            "attributes": _safe_attrs(state.get("attributes", {}) or {}),
            "message": f"{match.controller.display_name if match.controller else '设备'}{match.capability.display_name}当前是 {state.get('state')}{unit_text}。",
        }

    async def _environment_query_result(self, match: Any, slots: Any) -> dict[str, Any]:
        readings: list[dict[str, Any]] = []
        for capability in getattr(match.controller, "capabilities", []) or []:
            if capability.capability_id not in {"temperature", "humidity"} or not capability.entity_id:
                continue
            state = await self.client.get_state(capability.entity_id)
            attrs = state.get("attributes", {}) or {}
            readings.append(
                {
                    "capability": capability.display_name,
                    "capability_id": capability.capability_id,
                    "entity_id": capability.entity_id,
                    "state": state.get("state"),
                    "unit": attrs.get("unit_of_measurement", ""),
                    "attributes": _safe_attrs(attrs),
                }
            )
        if not readings:
            return {"success": False, "executed": False, "message": "这个环境控制器没有可查询的温湿度实体。"}
        summary = "，".join(f"{item['capability']} {item['state']}{item.get('unit') or ''}" for item in readings)
        return {
            "success": True,
            "executed": False,
            "query": True,
            "type": "environment",
            "controller": match.controller.display_name if match.controller else "",
            "readings": readings,
            "message": f"{match.controller.display_name if match.controller else '房间环境'}当前：{summary}。",
            "reply_hint": "请用自然语言概括房间温湿度，不要直接贴 JSON。",
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
            response, forecast_type, forecast_errors = await self._get_weather_forecast(entity_id)
            forecast = _extract_weather_forecast(response, entity_id)
            if forecast:
                result["type"] = "weather_forecast"
                result["forecast_type"] = forecast_type
                result["forecast"] = forecast
                result["message"] = f"已从 Home Assistant 查询 {match.controller.display_name if match.controller else '天气'} 的{forecast_type}天气预报。"
            else:
                result["forecast_error"] = "; ".join(forecast_errors) or "Home Assistant 未返回可用预报。"
                result["message"] = f"已查到当前天气，但天气预报查询失败：{result['forecast_error']}"
        return result

    async def _get_weather_forecast(self, entity_id: str) -> tuple[Any, str, list[str]]:
        errors: list[str] = []
        for forecast_type in ["daily", "hourly"]:
            try:
                response = await self.client.call_service(
                    "weather",
                    "get_forecasts",
                    {"entity_id": entity_id, "type": forecast_type},
                    return_response=True,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{forecast_type}: {exc}")
                continue
            if _extract_weather_forecast(response, entity_id):
                return response, forecast_type, errors
            errors.append(f"{forecast_type}: Home Assistant 返回为空")
        return None, "", errors

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


def _needs_environment_summary(match: Any, slots: Any) -> bool:
    capability = getattr(match, "capability", None)
    controller = getattr(match, "controller", None)
    if not capability or capability.capability_id not in {"temperature", "humidity"}:
        return False
    text = str(getattr(slots, "text", "") or "")
    if any(word in text for word in ["温湿度", "环境", "潮不潮", "湿不湿", "干不干"]):
        capability_ids = {item.capability_id for item in getattr(controller, "capabilities", []) or [] if getattr(item, "exposed", True)}
        return bool({"temperature", "humidity"} & capability_ids)
    return False


def _needs_weather_forecast(text: str) -> bool:
    return any(
        word in str(text or "")
        for word in ["预报", "未来", "最近", "近几天", "这几天", "几天", "明天", "后天", "一周", "7天", "七天", "雨", "下雨", "降雨"]
    )


def _weather_candidates(index: Any) -> list[tuple[Any, Any]]:
    candidates: list[tuple[Any, Any]] = []
    for controller in getattr(index, "controllers", []) or []:
        if not getattr(controller, "exposed", True):
            continue
        for capability in getattr(controller, "capabilities", []) or []:
            if not getattr(capability, "exposed", True):
                continue
            if capability.domain == "weather" or capability.capability_id == "weather":
                candidates.append((controller, capability))
    return candidates


def _rank_weather_candidates(candidates: list[tuple[Any, Any]], text: str) -> list[tuple[float, Any, Any]]:
    ranked = []
    normalized_text = _normalize_text(text)
    for controller, capability in candidates:
        names = [
            controller.display_name,
            *getattr(controller, "aliases", []),
            capability.display_name,
            *getattr(capability, "aliases", []),
        ]
        score = max((_name_score(normalized_text, name) for name in names), default=0.0)
        ranked.append((score, controller, capability))
    ranked.sort(key=lambda item: (-item[0], item[1].controller_id))
    return ranked


def _name_score(normalized_text: str, name: str) -> float:
    normalized_name = _normalize_text(name)
    if not normalized_text or not normalized_name:
        return 0.0
    if normalized_text == normalized_name:
        return 1.0
    if normalized_name in normalized_text or normalized_text in normalized_name:
        return 0.86
    return 0.0


def _normalize_text(text: str) -> str:
    return "".join(ch for ch in str(text or "").lower() if ch not in " \t\r\n，,。.!！?？:：-－—_.*·")


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
