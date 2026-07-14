"""Small async Home Assistant REST/WebSocket client."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse, urlunparse

import aiohttp

LOGGER = logging.getLogger(__name__)


class HomeAssistantError(Exception):
    """Raised when Home Assistant returns an error or cannot be reached."""


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def api_status(self) -> dict[str, Any]:
        return await self.get("/api/")

    async def get_states(self) -> list[dict[str, Any]]:
        data = await self.get("/api/states")
        if not isinstance(data, list):
            raise HomeAssistantError("Home Assistant returned an invalid states payload.")
        return data

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        data = await self.get(f"/api/states/{entity_id}")
        if not isinstance(data, dict):
            raise HomeAssistantError(f"Home Assistant returned an invalid state for {entity_id}.")
        return data

    async def get_services(self) -> list[dict[str, Any]]:
        data = await self.get("/api/services")
        if not isinstance(data, list):
            raise HomeAssistantError("Home Assistant returned an invalid services payload.")
        return data

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any] | None = None,
        *,
        return_response: bool = False,
    ) -> Any:
        suffix = "?return_response" if return_response else ""
        return await self.post(f"/api/services/{domain}/{service}{suffix}", data or {})

    async def render_template(self, template: str) -> str:
        data = await self.post("/api/template", {"template": template}, expect_json=False)
        return str(data)

    async def get_registry_metadata(self) -> dict[str, Any]:
        """Read HA registries through the WebSocket API.

        Failures for optional registries are returned as warnings so discovery
        can fall back to the REST states payload instead of failing the scan.
        """
        warnings: list[str] = []
        auth_success = False
        entity_payload: Any = []
        area_payload: Any = []
        device_payload: Any = []

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.ws_connect(self._websocket_url()) as ws:
                    await self._authenticate_websocket(ws)
                    auth_success = True
                    try:
                        entity_payload = await self._websocket_command(
                            ws,
                            1,
                            "config/entity_registry/list_for_display",
                        )
                    except HomeAssistantError as exc:
                        warnings.append(f"entity registry failed: {exc}")

                    try:
                        area_payload = await self._websocket_command(
                            ws,
                            2,
                            "config/area_registry/list",
                        )
                    except HomeAssistantError as exc:
                        warnings.append(f"area registry failed: {exc}")

                    try:
                        device_payload = await self._websocket_command(
                            ws,
                            3,
                            "config/device_registry/list",
                        )
                    except HomeAssistantError as exc:
                        warnings.append(f"device registry failed: {exc}")
        except TimeoutError as exc:
            raise HomeAssistantError("Home Assistant WebSocket registry request timed out") from exc
        except aiohttp.ClientError as exc:
            raise HomeAssistantError(f"Home Assistant WebSocket registry request failed: {exc}") from exc

        entity_registry = _extract_list(entity_payload, ["entities"])
        area_registry = _extract_list(area_payload, ["areas"])
        device_registry = _extract_list(device_payload, ["devices"])

        if not entity_registry:
            warnings.append(f"entity registry parsed 0 entries from raw type {_type_name(entity_payload)}")
        if not area_registry:
            warnings.append(f"area registry parsed 0 entries from raw type {_type_name(area_payload)}")
        if not device_registry:
            warnings.append(f"device registry parsed 0 entries from raw type {_type_name(device_payload)}")

        LOGGER.info(
            "[HA Controller Index] websocket registry raw:\n"
            "- websocket auth success: %s\n"
            "- entity_registry raw type: %s\n"
            "- entity_registry parsed count: %s\n"
            "- area_registry raw type: %s\n"
            "- area_registry parsed count: %s\n"
            "- device_registry raw type: %s\n"
            "- device_registry parsed count: %s",
            auth_success,
            _type_name(entity_payload),
            len(entity_registry),
            _type_name(area_payload),
            len(area_registry),
            _type_name(device_payload),
            len(device_registry),
        )

        return {
            "entity_registry": entity_registry,
            "area_registry": area_registry,
            "device_registry": device_registry,
            "warnings": warnings,
            "auth_success": auth_success,
            "raw_types": {
                "entity_registry": _type_name(entity_payload),
                "area_registry": _type_name(area_payload),
                "device_registry": _type_name(device_payload),
            },
        }

    async def get(self, path: str) -> Any:
        return await self._request("GET", path)

    async def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expect_json: bool = True,
    ) -> Any:
        return await self._request("POST", path, payload=payload, expect_json=expect_json)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        expect_json: bool = True,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout, headers=self.headers) as session:
                async with session.request(method, url, json=payload) as response:
                    text = await response.text()
                    if response.status < 200 or response.status >= 300:
                        raise HomeAssistantError(
                            f"Home Assistant HTTP {response.status} for {method} {path}: {text[:500]}"
                        )
                    if not expect_json:
                        return text
                    if not text:
                        return None
                    try:
                        return await response.json()
                    except Exception as exc:  # noqa: BLE001
                        raise HomeAssistantError(
                            f"Home Assistant returned non-JSON data for {method} {path}: {text[:200]}"
                        ) from exc
        except TimeoutError as exc:
            raise HomeAssistantError(f"Home Assistant request timed out: {method} {path}") from exc
        except aiohttp.ClientError as exc:
            raise HomeAssistantError(f"Home Assistant request failed: {exc}") from exc

    def _websocket_url(self) -> str:
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, "/api/websocket", "", "", ""))

    async def _authenticate_websocket(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        message = await ws.receive_json()
        if message.get("type") != "auth_required":
            raise HomeAssistantError(f"unexpected WebSocket auth message: {message.get('type')}")
        await ws.send_json({"type": "auth", "access_token": self.token})
        message = await ws.receive_json()
        if message.get("type") != "auth_ok":
            raise HomeAssistantError(f"WebSocket auth failed: {message.get('type')}")

    async def _websocket_command(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        command_id: int,
        command_type: str,
    ) -> Any:
        await ws.send_json({"id": command_id, "type": command_type})
        while True:
            message = await ws.receive_json()
            if message.get("id") != command_id:
                continue
            if not message.get("success", False):
                error = message.get("error", {})
                if isinstance(error, dict):
                    detail = error.get("message") or error.get("code") or error
                else:
                    detail = error
                raise HomeAssistantError(f"{command_type} failed: {detail}")
            return message.get("result", [])


def _extract_list(payload: Any, keys: list[str]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _extract_list(value, keys)
            if nested:
                return nested
    if "result" in payload:
        return _extract_list(payload.get("result"), keys)
    return []


def _type_name(value: Any) -> str:
    if isinstance(value, dict):
        return f"dict({','.join(str(key) for key in list(value.keys())[:8])})"
    if isinstance(value, list):
        return "list"
    return type(value).__name__
