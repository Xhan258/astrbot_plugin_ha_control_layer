"""Lightweight slot extraction for home intents."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class IntentSlots:
    text: str
    action: str = ""
    area_hint: str = ""
    device_hint: str = ""
    capability_hint: str = ""
    value_hint: str = ""
    number: float | None = None
    is_query: bool = False


def parse_intent(text: str) -> IntentSlots:
    value = str(text or "").strip()
    slots = IntentSlots(text=value)
    slots.is_query = any(word in value for word in ["吗", "么", "是不是", "状态", "正常", "多少", "几度", "湿度", "温湿度", "潮不潮", "湿不湿", "干不干", "还有多久", "查", "查询", "天气", "预报"])
    slots.action = _parse_action(value)
    slots.number = _extract_number(value)
    slots.area_hint = _parse_area_hint(value)
    slots.capability_hint = _parse_capability_hint(value)
    slots.value_hint = _parse_value_hint(value, slots)
    slots.device_hint = _parse_device_hint(value, slots)
    return slots


def _parse_area_hint(text: str) -> str:
    areas = [
        "主卧",
        "次卧",
        "卧室",
        "客厅",
        "厨房",
        "阳台",
        "书房",
        "卫生间",
        "浴室",
        "餐厅",
        "玄关",
        "儿童房",
        "老人房",
        "衣帽间",
        "未分区",
    ]
    for area in areas:
        if area in text:
            return area
    return ""


def _parse_action(text: str) -> str:
    if any(word in text for word in ["关闭", "关掉", "关了", "关机", "关灯"]):
        return "off"
    if any(word in text for word in ["打开", "开启", "开开", "开机", "开灯"]):
        return "on"
    if any(word in text for word in ["调到", "设为", "设置为", "设成", "改成", "改为", "开成", "开到", "切到", "切换到"]):
        return "set"
    if any(word in text for word in ["查", "查询", "看看", "多少", "几度", "湿度", "温湿度", "潮不潮", "湿不湿", "干不干", "正常", "天气", "预报"]):
        return "query"
    return ""


def _parse_capability_hint(text: str) -> str:
    if any(word in text for word in ["温湿度", "干湿度", "环境"]):
        return "温湿度"
    if any(word in text for word in ["湿度", "潮不潮", "湿不湿", "干不干"]):
        return "湿度"
    if any(word in text for word in ["几度", "多少度", "温度"]):
        return "温度"
    candidates = [
        "天气预报",
        "天气",
        "珍品变温",
        "健康气流",
        "强力安静",
        "除甲醛",
        "色温",
        "温度",
        "模式",
        "风速",
        "风量",
        "风向",
        "摆风",
        "扫风",
        "静眠",
        "睡眠",
        "辅热",
        "亮度",
        "湿度",
        "电源",
        "开关",
    ]
    for item in candidates:
        if item in text:
            return item
    if re.search(r"\d+(?:\.\d+)?\s*(?:度|℃|摄氏度)", text):
        return "温度"
    return ""


def _parse_value_hint(text: str, slots: IntentSlots) -> str:
    if slots.number is not None and slots.capability_hint == "温度":
        return f"{slots.number:g}℃"
    patterns = [
        r"(?:改成|改为|设成|设为|设置为|调成|调为|调到|切到|切换到|开到|开成)([^，,。.!！?？]+)",
        r"(?:开|开启)(除湿|制冷|制热|睡眠|静眠|强力|安静|低风|中风|强风|自由风|自然风|暖光|暖灯|暖白|冷光|白光|向上|向下)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean_value(match.group(1))
    for word in ["除湿", "制冷", "制热", "蛋类", "熟食", "母婴", "低风", "中风", "强风", "自由风", "自然风", "暖光", "暖灯", "暖白", "冷光", "白光", "向上", "向下", "强力", "安静"]:
        if word in text:
            return word
    if slots.action in {"on", "off"}:
        return slots.action
    return ""


def _parse_device_hint(text: str, slots: IntentSlots) -> str:
    known = ["珍品变温", "空调", "冰箱", "风扇", "窗帘", "灯"]
    for item in known:
        if item in text:
            if item == "珍品变温":
                return "冰箱"
            return item
    return ""


def _extract_number(text: str) -> float | None:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:℃|度|摄氏度|%|百分比)?", text)
    if not match:
        return None
    value = float(match.group(1))
    return int(value) if value.is_integer() else value


def _clean_value(text: str) -> str:
    value = str(text or "").strip(" ，,。.!！?？")
    for suffix in ["模式", "档位"]:
        if value.endswith(suffix) and len(value) > len(suffix):
            value = value[: -len(suffix)]
    return value.strip()
