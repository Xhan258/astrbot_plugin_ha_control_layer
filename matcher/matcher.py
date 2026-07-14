"""Match parsed intents against the controller index."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from ..index.models import Binding, Capability, CapabilityValue, Controller, ControllerIndex
from .intent_parser import IntentSlots


@dataclass
class MatchResult:
    matched: bool
    need_clarification: bool = False
    message: str = ""
    controller: Controller | None = None
    capability: Capability | None = None
    value: CapabilityValue | None = None
    binding: Binding | None = None
    candidates: list[str] | None = None
    confidence: float = 0.0


class IntentMatcher:
    def __init__(self, *, confidence_threshold: float = 0.62) -> None:
        self.confidence_threshold = confidence_threshold

    def match(self, index: ControllerIndex, slots: IntentSlots) -> MatchResult:
        controllers = [item for item in index.controllers if item.exposed]
        controller_matches = _rank_controllers(controllers, slots)
        if not controller_matches:
            return MatchResult(False, True, "我没找到对应的 Home Assistant 控制器。", candidates=[])
        if _is_ambiguous(controller_matches):
            return MatchResult(
                False,
                True,
                "你要控制哪个设备？",
                candidates=[item.display_name for _, item in controller_matches[:5]],
            )

        controller_score, controller = controller_matches[0]
        default_power = _default_power_capability(controller, slots)
        if default_power:
            capability_matches = [(0.96, default_power)]
        else:
            capability_matches = _rank_capabilities(controller, slots)
        if not capability_matches:
            return MatchResult(False, True, f"我在 {controller.display_name} 里没找到对应能力。", controller=controller)
        if _is_ambiguous(capability_matches):
            return MatchResult(
                False,
                True,
                f"你要控制 {controller.display_name} 的哪个能力？",
                controller=controller,
                candidates=[item.display_name for _, item in capability_matches[:5]],
            )

        capability_score, capability = capability_matches[0]
        if slots.is_query or capability.type == "query" or slots.action == "query":
            return MatchResult(
                True,
                False,
                controller=controller,
                capability=capability,
                confidence=min(1.0, (controller_score + capability_score) / 2),
            )

        value_result = _match_value(capability, slots)
        if value_result.need_clarification or not value_result.matched:
            value_result.controller = controller
            value_result.capability = capability
            return value_result

        confidence = min(1.0, (controller_score + capability_score + value_result.confidence) / 3)
        if confidence < self.confidence_threshold:
            return MatchResult(
                False,
                True,
                "这个控制有点不确定，我需要你确认一下。",
                controller=controller,
                capability=capability,
                value=value_result.value,
                candidates=[value_result.value.display_name] if value_result.value else [],
                confidence=confidence,
            )
        return MatchResult(
            True,
            False,
            controller=controller,
            capability=capability,
            value=value_result.value,
            binding=value_result.binding,
            confidence=confidence,
        )


def _rank_controllers(controllers: list[Controller], slots: IntentSlots) -> list[tuple[float, Controller]]:
    scored: list[tuple[float, Controller]] = []
    name_hint = slots.device_hint or slots.text
    for controller in controllers:
        score = _score_names(name_hint, [controller.display_name, *controller.aliases])
        if not slots.device_hint:
            score = max(score, _score_controller_by_capability(controller, slots))
        else:
            score = max(score, _score_controller_by_capability(controller, slots) * 0.45)
        if score > 0:
            scored.append((score, controller))
    scored.sort(key=lambda item: (-item[0], item[1].controller_id))
    return scored


def _score_controller_by_capability(controller: Controller, slots: IntentSlots) -> float:
    best = 0.0
    for cap in controller.capabilities:
        if not cap.exposed:
            continue
        best = max(best, _score_capability(cap, slots))
        if slots.value_hint:
            value_score = max((_score_value(value, slots.value_hint) for value in cap.values), default=0.0)
            best = max(best, value_score * 0.8)
    return best


def _rank_capabilities(controller: Controller, slots: IntentSlots) -> list[tuple[float, Capability]]:
    scored = []
    for capability in controller.capabilities:
        if not capability.exposed:
            continue
        score = _score_capability(capability, slots)
        if slots.action in {"on", "off"} and capability.type == "switch_like":
            score = max(score, 0.78)
        if slots.value_hint:
            score = max(score, max((_score_value(value, slots.value_hint) for value in capability.values), default=0.0) * 0.88)
        if score > 0:
            scored.append((score, capability))
    scored.sort(key=lambda item: (-item[0], item[1].capability_id))
    return scored


def _default_power_capability(controller: Controller, slots: IntentSlots) -> Capability | None:
    if slots.action not in {"on", "off"}:
        return None
    if _has_specific_capability_hint(slots.capability_hint):
        return None
    return _find_power_capability(controller)


def _has_specific_capability_hint(hint: str) -> bool:
    normalized = _normalize(hint)
    if not normalized:
        return False
    return normalized not in {"开关", "电源"}


def _find_power_capability(controller: Controller) -> Capability | None:
    for capability in controller.capabilities:
        if not capability.exposed:
            continue
        if capability.capability_id == "power" or capability.display_name == "电源":
            return capability
    return None


def _score_capability(capability: Capability, slots: IntentSlots) -> float:
    names = [capability.display_name, *capability.aliases, capability.capability_id]
    score = _score_names(slots.capability_hint or slots.text, names)
    if not slots.capability_hint and slots.value_hint:
        score = max(score, max((_score_value(value, slots.value_hint) for value in capability.values), default=0.0) * 0.82)
    return score


def _match_value(capability: Capability, slots: IntentSlots) -> MatchResult:
    if capability.type == "switch_like":
        value_id = "on" if slots.action == "on" else "off" if slots.action == "off" else slots.value_hint
        value = next((item for item in capability.values if item.value == value_id), None)
        if not value:
            return MatchResult(False, True, "我不知道该开还是关。")
        return MatchResult(True, value=value, binding=value.binding, confidence=0.95)

    if capability.type == "number":
        if slots.number is None:
            return MatchResult(False, True, "需要一个具体数值。")
        binding = capability.binding
        if not binding:
            return MatchResult(False, True, "这个数值能力没有可执行绑定。")
        data = dict(binding.service_data)
        if capability.domain == "light" and capability.capability_id == "brightness":
            data["brightness_pct"] = max(1, min(100, int(slots.number)))
        else:
            data["value"] = slots.number
        return MatchResult(True, value=CapabilityValue(str(slots.number), str(slots.number), binding=Binding(binding.domain, binding.service, data)), binding=Binding(binding.domain, binding.service, data), confidence=0.9)

    if capability.type == "select":
        ranked = sorted(((_score_value(value, slots.value_hint), value) for value in capability.values), key=lambda item: -item[0])
        ranked = [item for item in ranked if item[0] > 0]
        if not ranked:
            return MatchResult(False, True, f"我没找到 {slots.value_hint or '这个值'}。", candidates=[item.display_name for item in capability.values[:8]])
        if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
            return MatchResult(False, True, "我找到多个接近的值，需要你确认。", candidates=[item.display_name for _, item in ranked[:5]])
        score, value = ranked[0]
        return MatchResult(True, value=value, binding=value.binding, confidence=score)

    if capability.type == "climate" and slots.number is not None:
        binding = Binding("climate", "set_temperature", {"entity_id": capability.entity_id, "temperature": slots.number})
        return MatchResult(True, value=CapabilityValue(str(slots.number), f"{slots.number:g}℃", binding=binding), binding=binding, confidence=0.88)

    return MatchResult(False, True, "这个能力暂时不能自动执行。")


def _score_value(value: CapabilityValue, hint: str) -> float:
    if not hint:
        return 0.0
    names = [value.display_name, value.value, *value.aliases]
    return _score_names(hint, names)


def _score_names(hint: str, names: list[str]) -> float:
    normalized_hint = _normalize(hint)
    if not normalized_hint:
        return 0.0
    best = 0.0
    for name in names:
        normalized_name = _normalize(name)
        if not normalized_name:
            continue
        if normalized_hint == normalized_name:
            best = max(best, 1.0)
        elif normalized_hint in normalized_name or normalized_name in normalized_hint:
            best = max(best, 0.86)
        else:
            best = max(best, difflib.SequenceMatcher(None, normalized_hint, normalized_name).ratio())
    return best


def _is_ambiguous(matches: list[tuple[float, object]]) -> bool:
    if len(matches) < 2:
        return False
    return matches[0][0] < 0.99 and matches[0][0] - matches[1][0] < 0.08


def _normalize(text: str) -> str:
    return re.sub(r"[\s，,。.!！?？:：\-－—_.*·]+", "", str(text or "").strip().lower())
