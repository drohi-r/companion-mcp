from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .config import CompanionConfig


@dataclass
class CompanionClient:
    config: CompanionConfig
    _http_client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self.config.timeout_s)
        return self._http_client

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        request_kwargs: dict[str, Any] = {"params": params}
        if body is not None:
            if isinstance(body, str):
                request_kwargs["content"] = body
                request_kwargs["headers"] = {"content-type": "text/plain"}
            else:
                request_kwargs["json"] = body

        client = await self._http()
        response = await client.request(method.upper(), url, **request_kwargs)

        parsed: Any
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                parsed = response.json()
            except Exception:
                parsed = response.text
        else:
            parsed = response.text

        return {
            "method": method.upper(),
            "path": path,
            "url": url,
            "status_code": response.status_code,
            "ok": response.is_success,
            "content_type": content_type,
            "body": parsed,
        }

    async def button_action(self, page: int, row: int, column: int, action: str) -> dict[str, Any]:
        """Execute a button action: press, down, up, rotate-left, rotate-right, step."""
        return await self.request("POST", f"/api/location/{page}/{row}/{column}/{action}")

    async def set_style(self, page: int, row: int, column: int, **style: Any) -> dict[str, Any]:
        """Set button style properties (text, color, bgcolor, size)."""
        return await self.request("POST", f"/api/location/{page}/{row}/{column}/style", body=style)

    async def get_variable(self, path: str) -> dict[str, Any]:
        """Get a custom or module variable value."""
        return await self.request("GET", path)

    async def set_variable(self, name: str, value: str) -> dict[str, Any]:
        """Set a custom variable value."""
        return await self.request(
            "POST",
            f"/api/custom-variable/{name}/value",
            body=value,
        )

    async def get_button(self, page: int, row: int, column: int) -> dict[str, Any]:
        """Read the raw button payload for a location."""
        return await self.request("GET", f"/api/location/{page}/{row}/{column}")

    async def list_surfaces(self) -> dict[str, Any]:
        """Return connected control surfaces when the API supports it."""
        return await self.request("GET", "/api/surfaces")
