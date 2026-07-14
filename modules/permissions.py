"""Permission helpers for message sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PermissionConfig:
    admin_users: list[str]
    admin_groups: list[str]
    allow_query_without_admin: bool = True


class PermissionChecker:
    def __init__(self, config: PermissionConfig) -> None:
        self.config = config

    def can_query(self, event: Any) -> bool:
        return self.config.allow_query_without_admin or self.is_admin(event)

    def can_control(self, event: Any) -> bool:
        if not self.config.admin_users and not self.config.admin_groups:
            return True
        return self.is_admin(event)

    def is_admin(self, event: Any) -> bool:
        if getattr(event, "is_admin", None):
            try:
                if event.is_admin():
                    return True
            except Exception:
                pass

        umo = getattr(event, "unified_msg_origin", "") or ""
        sender_id = _call(event, "get_sender_id")
        if umo in self.config.admin_users or sender_id in self.config.admin_users:
            return True

        parts = umo.split(":")
        platform = parts[0] if len(parts) > 0 else ""
        message_type = parts[1] if len(parts) > 1 else ""
        session_id = parts[2] if len(parts) > 2 else ""

        for admin in self.config.admin_users:
            if ":" in admin:
                admin_parts = admin.split(":")
                if len(admin_parts) == 2:
                    admin_platform, admin_id = admin_parts
                    if admin_platform == platform and admin_id in {session_id, sender_id}:
                        return True

        if message_type == "GroupMessage":
            for group in self.config.admin_groups:
                if group == session_id:
                    return True
                if ":" in group:
                    group_platform, group_id = group.split(":", 1)
                    if group_platform == platform and group_id == session_id:
                        return True

        return False


def _call(obj: Any, name: str) -> str:
    method = getattr(obj, name, None)
    if not method:
        return ""
    try:
        return str(method())
    except Exception:
        return ""
