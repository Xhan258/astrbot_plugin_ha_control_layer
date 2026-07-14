"""Controller index data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Binding:
    domain: str
    service: str
    service_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Binding | None":
        if not isinstance(data, dict):
            return None
        domain = str(data.get("domain", "") or "")
        service = str(data.get("service", "") or "")
        if not domain or not service:
            return None
        service_data = data.get("service_data", {})
        return cls(domain=domain, service=service, service_data=service_data if isinstance(service_data, dict) else {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "service": self.service,
            "service_data": self.service_data,
        }


@dataclass
class CapabilityValue:
    value: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    binding: Binding | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityValue":
        return cls(
            value=str(data.get("value", "") or ""),
            display_name=str(data.get("display_name", "") or data.get("value", "") or ""),
            aliases=[str(item) for item in data.get("aliases", []) or []],
            binding=Binding.from_dict(data.get("binding")),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "value": self.value,
            "display_name": self.display_name,
            "aliases": self.aliases,
        }
        if self.binding:
            data["binding"] = self.binding.to_dict()
        return data


@dataclass
class Capability:
    capability_id: str
    display_name: str
    type: str
    aliases: list[str] = field(default_factory=list)
    exposed: bool = True
    entity_id: str = ""
    domain: str = ""
    service: str = ""
    values: list[CapabilityValue] = field(default_factory=list)
    binding: Binding | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Capability":
        return cls(
            capability_id=str(data.get("capability_id", "") or ""),
            display_name=str(data.get("display_name", "") or ""),
            type=str(data.get("type", "") or ""),
            aliases=[str(item) for item in data.get("aliases", []) or []],
            exposed=bool(data.get("exposed", True)),
            entity_id=str(data.get("entity_id", "") or ""),
            domain=str(data.get("domain", "") or ""),
            service=str(data.get("service", "") or ""),
            values=[CapabilityValue.from_dict(item) for item in data.get("values", []) or [] if isinstance(item, dict)],
            binding=Binding.from_dict(data.get("binding")),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "capability_id": self.capability_id,
            "display_name": self.display_name,
            "aliases": self.aliases,
            "type": self.type,
            "exposed": self.exposed,
            "values": [item.to_dict() for item in self.values],
        }
        if self.entity_id:
            data["entity_id"] = self.entity_id
        if self.domain:
            data["domain"] = self.domain
        if self.service:
            data["service"] = self.service
        if self.binding:
            data["binding"] = self.binding.to_dict()
        return data


@dataclass
class Controller:
    controller_id: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    exposed: bool = True
    area_id: str = ""
    area_name: str = ""
    source: dict[str, Any] = field(default_factory=dict)
    capabilities: list[Capability] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Controller":
        return cls(
            controller_id=str(data.get("controller_id", "") or ""),
            display_name=str(data.get("display_name", "") or ""),
            aliases=[str(item) for item in data.get("aliases", []) or []],
            exposed=bool(data.get("exposed", True)),
            area_id=str(data.get("area_id", "") or ""),
            area_name=str(data.get("area_name", "") or ""),
            source=data.get("source", {}) if isinstance(data.get("source", {}), dict) else {},
            capabilities=[Capability.from_dict(item) for item in data.get("capabilities", []) or [] if isinstance(item, dict)],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "controller_id": self.controller_id,
            "display_name": self.display_name,
            "area_id": self.area_id,
            "area_name": self.area_name,
            "source": self.source,
            "aliases": self.aliases,
            "exposed": self.exposed,
            "capabilities": [item.to_dict() for item in self.capabilities],
        }


@dataclass
class ControllerIndex:
    version: int = 1
    controllers: list[Controller] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    last_scan_time: str = ""
    scan_status: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ControllerIndex":
        if not isinstance(data, dict):
            return cls()
        return cls(
            version=int(data.get("version", 1) or 1),
            controllers=[Controller.from_dict(item) for item in data.get("controllers", []) or [] if isinstance(item, dict)],
            pending=[item for item in data.get("pending", []) or [] if isinstance(item, dict)],
            warnings=[str(item) for item in data.get("warnings", []) or []],
            summary=data.get("summary", {}) if isinstance(data.get("summary", {}), dict) else {},
            last_scan_time=str(data.get("last_scan_time", "") or ""),
            scan_status=str(data.get("scan_status", "") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "controllers": [item.to_dict() for item in self.controllers],
            "pending": self.pending,
            "warnings": self.warnings,
            "summary": self.summary,
            "last_scan_time": self.last_scan_time,
            "scan_status": self.scan_status,
        }
