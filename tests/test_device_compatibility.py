"""Regression coverage for device scanning and controller-name matching."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "ha_control_layer_device_test"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE_NAME, package)

from ha_control_layer_device_test.discovery.scanner import (
    EntityGroup,
    NormalizedEntity,
    RegistryContext,
    _capabilities_from_entity,
    _controller_from_group,
)
from ha_control_layer_device_test.executor.safe_executor import SafeExecutor
from ha_control_layer_device_test.index.models import Binding, Capability, CapabilityValue, Controller, ControllerIndex
from ha_control_layer_device_test.matcher.intent_parser import parse_intent
from ha_control_layer_device_test.matcher.matcher import IntentMatcher


def entity(
    entity_id: str,
    domain: str,
    friendly_name: str,
    *,
    device_id: str = "device-1",
    device_name: str = "",
    attributes: dict | None = None,
) -> NormalizedEntity:
    return NormalizedEntity(
        entity_id=entity_id,
        domain=domain,
        friendly_name=friendly_name,
        state="off",
        attributes=attributes or {},
        controller_id="device_1",
        controller_name=friendly_name,
        capability_id="power",
        capability_name="开关",
        area_id="bedroom",
        area_name="次卧",
        device_id=device_id,
        device_name=device_name,
    )


def controller_from_entities(*entities: NormalizedEntity, display_name: str) -> Controller:
    registry = RegistryContext({}, {}, {entities[0].device_id: {"display_name": display_name}}, [])
    summary = {
        "controllers_built_from_device_id": 0,
        "controllers_built_from_environment": 0,
        "controllers_built_from_prefix": 0,
        "standalone_controllers": 0,
        "entities_hidden_as_config_diagnostic_internal": 0,
    }
    return _controller_from_group(
        EntityGroup("bedroom__device__1", "device_id", list(entities)),
        registry,
        summary,
    )


def light_controller(name: str) -> Controller:
    return Controller(
        controller_id=name,
        display_name=name,
        aliases=[],
        area_id="bedroom",
        area_name="次卧",
        capabilities=[
            Capability(
                capability_id="power",
                display_name="开关",
                type="switch_like",
                values=[
                    CapabilityValue("on", "开", binding=Binding("light", "turn_on", {"entity_id": f"light.{name}"})),
                    CapabilityValue("off", "关", binding=Binding("light", "turn_off", {"entity_id": f"light.{name}"})),
                ],
            )
        ],
    )


class DeviceScannerTests(unittest.TestCase):
    def test_indicator_light_is_hidden_and_cannot_replace_relay_power(self) -> None:
        indicator = entity(
            "light.panel_indicator_light",
            "light",
            "吸顶灯 指示灯",
            device_name="吸顶灯面板",
        )
        relay = entity(
            "switch.ceiling_relay",
            "switch",
            "吸顶灯面板 开关 按键",
            device_name="吸顶灯面板",
        )
        controller = controller_from_entities(indicator, relay, display_name="吸顶灯")
        by_id = {capability.capability_id: capability for capability in controller.capabilities}

        self.assertFalse(by_id["indicator_light"].exposed)
        self.assertEqual("switch.ceiling_relay", by_id["power"].values[0].binding.service_data["entity_id"])

        result = IntentMatcher().match(ControllerIndex(controllers=[controller]), parse_intent("打开次卧吸顶灯"))
        self.assertTrue(result.matched)
        self.assertEqual("switch.ceiling_relay", result.binding.service_data["entity_id"])

    def test_multi_relay_switches_keep_independent_capabilities_and_bindings(self) -> None:
        left = entity(
            "switch.wall_panel_left",
            "switch",
            "双开墙壁开关 楼梯灯 左键",
            device_name="双开墙壁开关",
        )
        right = entity(
            "switch.wall_panel_right",
            "switch",
            "双开墙壁开关 鞋柜灯 右键",
            device_name="双开墙壁开关",
        )
        controller = controller_from_entities(left, right, display_name="双开墙壁开关")
        named = {capability.display_name: capability for capability in controller.capabilities}

        self.assertEqual({"楼梯灯", "鞋柜灯"}, set(named))
        self.assertNotEqual(named["楼梯灯"].capability_id, named["鞋柜灯"].capability_id)
        self.assertEqual("switch.wall_panel_left", named["楼梯灯"].values[0].binding.service_data["entity_id"])
        self.assertEqual("switch.wall_panel_right", named["鞋柜灯"].values[0].binding.service_data["entity_id"])

        matcher = IntentMatcher()
        for text, entity_id in [("打开楼梯灯", "switch.wall_panel_left"), ("打开鞋柜灯", "switch.wall_panel_right")]:
            with self.subTest(text=text):
                result = matcher.match(ControllerIndex(controllers=[controller]), parse_intent(text))
                self.assertTrue(result.matched)
                self.assertEqual(entity_id, result.binding.service_data["entity_id"])

    def test_indicator_fix_reaches_safe_executor_with_the_real_relay(self) -> None:
        class FakeClient:
            calls: list[tuple[str, str, dict]] = []

            async def call_service(self, domain: str, service: str, data: dict):
                self.calls.append((domain, service, data))
                return {"ok": True}

        indicator = entity("light.panel_indicator_light", "light", "吸顶灯 指示灯", device_name="吸顶灯面板")
        relay = entity("switch.ceiling_relay", "switch", "吸顶灯面板 开关 按键", device_name="吸顶灯面板")
        controller = controller_from_entities(indicator, relay, display_name="吸顶灯")
        match = IntentMatcher().match(ControllerIndex(controllers=[controller]), parse_intent("打开吸顶灯"))
        client = FakeClient()
        result = asyncio.run(
            SafeExecutor(client, allowed_domains={"switch"}, blocked_domains=set(), dangerous_entities=set()).execute(
                controller=match.controller,
                capability=match.capability,
                value=match.value,
                binding=match.binding,
            )
        )
        self.assertTrue(result.success)
        self.assertEqual([("switch", "turn_on", {"entity_id": "switch.ceiling_relay"})], client.calls)


class DeviceMatcherTests(unittest.TestCase):
    def test_specific_lamp_names_win_and_generic_lamp_is_ambiguous(self) -> None:
        index = ControllerIndex(controllers=[light_controller("台灯"), light_controller("吸顶灯"), light_controller("灯带")])
        matcher = IntentMatcher()

        for text, expected in [("打开一楼次卧台灯", "台灯"), ("打开吸顶灯", "吸顶灯")]:
            with self.subTest(text=text):
                result = matcher.match(index, parse_intent(text))
                self.assertTrue(result.matched)
                self.assertEqual(expected, result.controller.display_name)

        generic = matcher.match(index, parse_intent("打开灯"))
        self.assertFalse(generic.matched)
        self.assertTrue(generic.need_clarification)

    def test_named_ac_companion_beats_shared_generic_alias(self) -> None:
        fan_mode = Capability(
            capability_id="fan_mode",
            display_name="风速",
            aliases=["风量"],
            type="select",
            values=[CapabilityValue("low", "低风", ["最低"], Binding("climate", "set_fan_mode", {"entity_id": "climate.companion_2", "fan_mode": "low"}))],
        )
        named = Controller("companion_2", "空调伴侣2", aliases=["空调"], capabilities=[fan_mode])
        other = Controller("other_ac", "卧室空调", aliases=["空调"], capabilities=[fan_mode])
        result = IntentMatcher().match(ControllerIndex(controllers=[other, named]), parse_intent("空调伴侣2风速调到最低"))

        self.assertTrue(result.matched)
        self.assertEqual("空调伴侣2", result.controller.display_name)


class ClimateFanModeTests(unittest.TestCase):
    def test_scanner_creates_only_declared_climate_fan_modes_with_real_bindings(self) -> None:
        climate = entity(
            "climate.bedroom_air",
            "climate",
            "次卧空调",
            attributes={"fan_modes": ["auto", "low", "medium", "high"]},
        )
        capabilities = _capabilities_from_entity(climate)
        fan_mode = next(item for item in capabilities if item.capability_id == "fan_mode")
        values = {item.value: item for item in fan_mode.values}

        self.assertEqual({"auto", "low", "medium", "high"}, set(values))
        self.assertIn("最低", values["low"].aliases)
        self.assertEqual("set_fan_mode", values["low"].binding.service)
        self.assertEqual("low", values["low"].binding.service_data["fan_mode"])

        controller = Controller("bedroom_air", "次卧空调", aliases=["空调"], capabilities=[fan_mode])
        result = IntentMatcher().match(ControllerIndex(controllers=[controller]), parse_intent("次卧空调风速调到低风"))
        self.assertTrue(result.matched)
        self.assertEqual("low", result.value.value)
        self.assertEqual("set_fan_mode", result.binding.service)

    def test_climate_without_fan_modes_does_not_create_fan_speed(self) -> None:
        climate = entity("climate.bedroom_air", "climate", "次卧空调")
        capabilities = _capabilities_from_entity(climate)
        self.assertNotIn("fan_mode", {item.capability_id for item in capabilities})


if __name__ == "__main__":
    unittest.main()
