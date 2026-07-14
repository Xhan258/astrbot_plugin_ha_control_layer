"""Safe Home Assistant execution based on controller-index bindings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..index.models import Binding, Capability, CapabilityValue, Controller


@dataclass
class ExecutionResult:
    success: bool
    message: str
    service: str = ""
    data: dict[str, Any] | None = None
    response: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "service": self.service,
            "data": self.data or {},
            "response": self.response,
        }


class SafeExecutor:
    def __init__(
        self,
        client: Any,
        *,
        allowed_domains: set[str],
        blocked_domains: set[str],
        dangerous_entities: set[str],
    ) -> None:
        self.client = client
        self.allowed_domains = allowed_domains
        self.blocked_domains = blocked_domains
        self.dangerous_entities = dangerous_entities

    async def execute(
        self,
        *,
        controller: Controller,
        capability: Capability,
        value: CapabilityValue | None,
        binding: Binding,
    ) -> ExecutionResult:
        denied = self._validate(binding)
        if denied:
            return ExecutionResult(False, denied)
        response = await self.client.call_service(binding.domain, binding.service, dict(binding.service_data))
        target = controller.display_name
        cap = capability.display_name
        if value:
            message = f"已把{target}{cap}设置为{value.display_name}。"
        else:
            message = f"已执行{target}{cap}。"
        return ExecutionResult(
            True,
            message,
            service=f"{binding.domain}.{binding.service}",
            data=dict(binding.service_data),
            response=response,
        )

    def _validate(self, binding: Binding) -> str:
        if binding.domain in self.blocked_domains:
            return f"{binding.domain} 属于危险服务，已拒绝。"
        if binding.domain not in self.allowed_domains:
            return f"{binding.domain} 未允许控制。"
        entity_id = str(binding.service_data.get("entity_id", "") or "")
        if entity_id and entity_id in self.dangerous_entities:
            return f"{entity_id} 被标记为高风险实体，拒绝控制。"
        return ""
