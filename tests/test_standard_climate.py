"""Regression tests for standard Home Assistant climate entities."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "ha_control_layer_test"
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(ROOT)]
sys.modules.setdefault(PACKAGE_NAME, package)

from ha_control_layer_test.discovery.scanner import NormalizedEntity, _capabilities_from_entity
from ha_control_layer_test.executor.safe_executor import SafeExecutor
from ha_control_layer_test.index.models import Controller, ControllerIndex
from ha_control_layer_test.matcher.intent_parser import parse_intent
from ha_control_layer_test.matcher.matcher import IntentMatcher


def climate_entity(*, area_name: str = "一楼次卧", supported_features: int = 384) -> NormalizedEntity:
    return NormalizedEntity(
        entity_id="climate.yj1226_cn_2141828144_air",
        domain="climate",
        friendly_name=f"{area_name}空调",
        state="off",
        attributes={
            "hvac_modes": ["off", "heat", "cool", "dry", "fan_only", "auto", "heat_cool"],
            "supported_features": supported_features,
        },
        controller_id=f"{area_name}_air",
        controller_name=f"{area_name}空调",
        capability_id="climate",
        capability_name="空调",
        area_id=area_name,
        area_name=area_name,
    )


def controller_for(entity: NormalizedEntity, *, exposed: bool = True) -> Controller:
    return Controller(
        controller_id=f"{entity.area_id}_air",
        display_name=entity.friendly_name,
        aliases=[entity.friendly_name, "空调", "冷气"],
        exposed=exposed,
        area_id=entity.area_id,
        area_name=entity.area_name,
        capabilities=_capabilities_from_entity(entity),
    )


class StandardClimateScannerTests(unittest.TestCase):
    def test_scanner_creates_real_mode_bindings_and_localized_values(self) -> None:
        capabilities = _capabilities_from_entity(climate_entity())
        by_id = {item.capability_id: item for item in capabilities}

        self.assertEqual({"temperature", "mode", "power"}, set(by_id))
        heat = next(item for item in by_id["mode"].values if item.value == "heat")
        self.assertEqual("制热", heat.display_name)
        self.assertIn("暖风", heat.aliases)
        self.assertEqual("set_hvac_mode", heat.binding.service)
        self.assertEqual("heat", heat.binding.service_data["hvac_mode"])

    def test_scanner_only_generates_power_values_for_declared_flags(self) -> None:
        capabilities = _capabilities_from_entity(climate_entity(supported_features=128))
        power = next(item for item in capabilities if item.capability_id == "power")
        self.assertEqual(["off"], [item.value for item in power.values])
        self.assertEqual("turn_off", power.values[0].binding.service)

        capabilities = _capabilities_from_entity(climate_entity(supported_features=0))
        self.assertNotIn("power", {item.capability_id for item in capabilities})


class StandardClimateMatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = IntentMatcher()
        self.guest = controller_for(climate_entity())
        self.index = ControllerIndex(controllers=[self.guest])

    def _match(self, text: str):
        return self.matcher.match(self.index, parse_intent(text))

    def test_heat_cool_and_dry_use_scanned_mode_bindings(self) -> None:
        for text, expected in [
            ("次卧空调设置为制热模式", "heat"),
            ("次卧空调设置为制冷模式", "cool"),
            ("次卧空调除湿", "dry"),
        ]:
            with self.subTest(text=text):
                result = self._match(text)
                self.assertTrue(result.matched)
                self.assertFalse(result.need_clarification)
                self.assertEqual("mode", result.capability.capability_id)
                self.assertEqual(expected, result.value.value)
                self.assertEqual("set_hvac_mode", result.binding.service)
                self.assertEqual(expected, result.binding.service_data["hvac_mode"])

    def test_power_uses_only_scanned_climate_turn_bindings(self) -> None:
        on_result = self._match("打开次卧空调")
        off_result = self._match("关闭次卧空调")
        self.assertEqual("turn_on", on_result.binding.service)
        self.assertEqual("turn_off", off_result.binding.service)
        self.assertEqual("power", on_result.capability.capability_id)
        self.assertEqual("power", off_result.capability.capability_id)

    def test_missing_power_flags_cannot_fall_back_to_mode_off(self) -> None:
        controller = controller_for(climate_entity(supported_features=0))
        index = ControllerIndex(controllers=[controller])
        for text in ["打开次卧空调", "关闭次卧空调"]:
            with self.subTest(text=text):
                result = self.matcher.match(index, parse_intent(text))
                self.assertFalse(result.matched)
                self.assertTrue(result.need_clarification)
                self.assertIsNone(result.binding)

    def test_temperature_keeps_the_existing_climate_execution_chain(self) -> None:
        result = self._match("次卧空调调到25度")
        self.assertTrue(result.matched)
        self.assertEqual("temperature", result.capability.capability_id)
        self.assertEqual("set_temperature", result.binding.service)
        self.assertEqual(25, result.binding.service_data["temperature"])

    def test_mode_binding_reaches_safe_executor_without_text_service_fallback(self) -> None:
        class FakeClient:
            calls: list[tuple[str, str, dict]] = []

            async def call_service(self, domain: str, service: str, data: dict):
                self.calls.append((domain, service, data))
                return {"ok": True}

        match = self._match("次卧空调设置为制热模式")
        client = FakeClient()
        result = asyncio.run(
            SafeExecutor(
                client,
                allowed_domains={"climate"},
                blocked_domains=set(),
                dangerous_entities=set(),
            ).execute(
                controller=match.controller,
                capability=match.capability,
                value=match.value,
                binding=match.binding,
            )
        )
        self.assertTrue(result.success)
        self.assertEqual(
            [("climate", "set_hvac_mode", {"entity_id": "climate.yj1226_cn_2141828144_air", "hvac_mode": "heat"})],
            client.calls,
        )

    def test_hidden_capability_and_controller_cannot_match(self) -> None:
        mode = next(item for item in self.guest.capabilities if item.capability_id == "mode")
        mode.exposed = False
        result = self._match("次卧空调设置为制热模式")
        self.assertFalse(result.matched)
        self.assertTrue(result.need_clarification)

        hidden_index = ControllerIndex(controllers=[controller_for(climate_entity(), exposed=False)])
        result = self.matcher.match(hidden_index, parse_intent("次卧空调设置为制热模式"))
        self.assertFalse(result.matched)
        self.assertTrue(result.need_clarification)

    def test_area_hint_prevents_cross_room_ac_match(self) -> None:
        living = controller_for(climate_entity(area_name="客厅"))
        result = self.matcher.match(ControllerIndex(controllers=[living, self.guest]), parse_intent("次卧空调设置为制热模式"))
        self.assertTrue(result.matched)
        self.assertEqual("一楼次卧", result.controller.area_name)


if __name__ == "__main__":
    unittest.main()
