from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import struct
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

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

    async def _ws_connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_connection(self.config.host, self.config.port)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET /trpc HTTP/1.1\r\n"
            f"Host: {self.config.host}:{self.config.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()

        response = await reader.readuntil(b"\r\n\r\n")
        header_text = response.decode("utf-8", errors="replace")
        status_line = header_text.split("\r\n", 1)[0]
        if "101" not in status_line:
            raise httpx.HTTPError(f"WebSocket upgrade failed: {status_line}")

        headers: dict[str, str] = {}
        for line in header_text.split("\r\n")[1:]:
            if not line or ":" not in line:
                continue
            key_name, value = line.split(":", 1)
            headers[key_name.strip().lower()] = value.strip()

        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        actual_accept = headers.get("sec-websocket-accept")
        if actual_accept != expected_accept:
            raise httpx.HTTPError("WebSocket upgrade returned an invalid Sec-WebSocket-Accept header.")

        return reader, writer

    async def _ws_send_json(self, writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        writer.write(bytes(header) + mask + masked)
        await writer.drain()

    async def _ws_read_frame(self, reader: asyncio.StreamReader) -> tuple[int, bytes]:
        head = await reader.readexactly(2)
        first, second = head[0], head[1]
        opcode = first & 0x0F
        masked = (second & 0x80) != 0
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", await reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", await reader.readexactly(8))[0]
        mask = await reader.readexactly(4) if masked else b""
        payload = await reader.readexactly(length)
        if masked:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        return opcode, payload

    async def _ws_close(self, writer: asyncio.StreamWriter) -> None:
        try:
            writer.write(b"\x88\x80\x00\x00\x00\x00")
            await writer.drain()
        except Exception:
            pass
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    async def _trpc_receive_until_result(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request_id: int,
    ) -> dict[str, Any]:
        while True:
            opcode, payload = await self._ws_read_frame(reader)
            if opcode == 0x1:
                message = json.loads(payload.decode("utf-8"))
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    error = message["error"]
                    return {
                        "ok": False,
                        "transport": "trpc-ws",
                        "error": error.get("message", "Unknown tRPC error"),
                        "error_code": error.get("data", {}).get("code"),
                        "body": error,
                    }

                result = message.get("result", {})
                result_type = result.get("type")
                if result_type == "started":
                    continue
                if result_type == "data":
                    return {
                        "ok": True,
                        "transport": "trpc-ws",
                        "body": result.get("data"),
                    }
                return {
                    "ok": False,
                    "transport": "trpc-ws",
                    "error": f"Unexpected tRPC result type: {result_type!r}",
                    "body": message,
                }
            if opcode == 0x8:
                return {
                    "ok": False,
                    "transport": "trpc-ws",
                    "error": "Companion closed the websocket connection unexpectedly.",
                    "body": None,
                }
            if opcode == 0x9:
                pong = bytearray([0x8A])
                length = len(payload)
                if length < 126:
                    pong.append(0x80 | length)
                elif length < 65536:
                    pong.append(0x80 | 126)
                    pong.extend(struct.pack("!H", length))
                else:
                    pong.append(0x80 | 127)
                    pong.extend(struct.pack("!Q", length))
                mask = os.urandom(4)
                masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
                writer.write(bytes(pong) + mask + masked)
                await writer.drain()

    async def trpc_call(self, method: str, path: str, *, input: dict[str, Any] | None = None) -> dict[str, Any]:
        reader, writer = await self._ws_connect()
        request_id = 1
        params: dict[str, Any] = {"path": path}
        if input is not None:
            params["input"] = input
        try:
            await self._ws_send_json(
                writer,
                {
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
            )
            result = await self._trpc_receive_until_result(reader, writer, request_id)
            result["path"] = path
            result["method"] = method
            result["url"] = f"{self.config.ws_base_url}/trpc"
            return result
        finally:
            await self._ws_close(writer)

    async def trpc_query(self, path: str, input: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.trpc_call("query", path, input=input)

    async def trpc_subscription_once(self, path: str, input: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.trpc_call("subscription", path, input=input)

    async def button_action(self, page: int, row: int, column: int, action: str) -> dict[str, Any]:
        """Execute a button action: press, down, up, rotate-left, rotate-right, step."""
        return await self.request("POST", f"/api/location/{page}/{row}/{column}/{action}")

    async def set_style(self, page: int, row: int, column: int, **style: Any) -> dict[str, Any]:
        """Set button style properties using Companion's query-based style API."""
        params = {key: value for key, value in style.items() if value not in (None, "")}
        path = f"/api/location/{page}/{row}/{column}/style"
        if params:
            path = f"{path}?{urlencode(params)}"
        return await self.request("POST", path)

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

    async def set_step(self, page: int, row: int, column: int, step: int) -> dict[str, Any]:
        """Set the active step using Companion's query-based endpoint."""
        return await self.request("POST", f"/api/location/{page}/{row}/{column}/step?step={step}")

    async def get_button(self, page: int, row: int, column: int) -> dict[str, Any]:
        """Read the raw button payload for a location."""
        return await self.request("GET", f"/api/location/{page}/{row}/{column}")

    async def list_surfaces(self) -> dict[str, Any]:
        """Return connected control surfaces from Companion's tRPC API."""
        return await self.trpc_subscription_once("surfaces.watchSurfaces")

    async def get_app_info(self) -> dict[str, Any]:
        return await self.trpc_query("appInfo.version")

    async def get_variable_values(self, label: str) -> dict[str, Any]:
        return await self.trpc_query("variables.values.connection", {"label": label})

    async def get_custom_variable_current(self, name: str) -> dict[str, Any]:
        result = await self.get_variable_values("custom")
        body = result.get("body")
        value = body.get(name) if isinstance(body, dict) else None
        return {
            **result,
            "body": {
                "name": name,
                "value": value,
                "exists": value is not None,
            },
        }

    async def get_module_variable_current(self, connection: str, name: str) -> dict[str, Any]:
        result = await self.get_variable_values(connection)
        body = result.get("body")
        value = body.get(name) if isinstance(body, dict) else None
        return {
            **result,
            "body": {
                "connection": connection,
                "name": name,
                "value": value,
                "exists": value is not None,
            },
        }

    async def get_pages_snapshot(self) -> dict[str, Any]:
        return await self.trpc_subscription_once("pages.watch")

    def _control_id_from_pages_snapshot(
        self,
        pages_snapshot: dict[str, Any] | None,
        page: int,
        row: int,
        column: int,
    ) -> str | None:
        if not isinstance(pages_snapshot, dict):
            return None
        order = pages_snapshot.get("order")
        pages = pages_snapshot.get("pages")
        if not isinstance(order, list) or not isinstance(pages, dict) or page < 1 or page > len(order):
            return None
        page_id = order[page - 1]
        page_info = pages.get(page_id)
        if not isinstance(page_info, dict):
            return None
        controls = page_info.get("controls")
        if not isinstance(controls, dict):
            return None
        row_info = controls.get(str(row))
        if not isinstance(row_info, dict):
            return None
        control_id = row_info.get(str(column))
        return control_id if isinstance(control_id, str) else None

    async def get_control_snapshot(self, control_id: str) -> dict[str, Any]:
        return await self.trpc_subscription_once("controls.watchControl", {"controlId": control_id})

    async def get_preview_location(self, page: int, row: int, column: int) -> dict[str, Any]:
        return await self.trpc_subscription_once(
            "preview.graphics.location",
            {"location": {"pageNumber": page, "row": row, "column": column}},
        )

    def _preview_meta(self, preview: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(preview, dict):
            return None
        image = preview.get("image")
        if not isinstance(image, str) or "," not in image:
            return {"isUsed": preview.get("isUsed"), "image_sha256": None, "image_bytes": None}
        header, encoded = image.split(",", 1)
        mime = None
        if header.startswith("data:") and ";base64" in header:
            mime = header[5:].split(";", 1)[0]
        try:
            payload = base64.b64decode(encoded, validate=False)
        except Exception:
            return {"isUsed": preview.get("isUsed"), "mime": mime, "image_sha256": None, "image_bytes": None}
        return {
            "isUsed": preview.get("isUsed"),
            "mime": mime,
            "image_sha256": hashlib.sha256(payload).hexdigest(),
            "image_bytes": len(payload),
        }

    def _style_meta(self, control: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(control, dict):
            return None
        config = control.get("config")
        if not isinstance(config, dict):
            return None
        style = config.get("style")
        if not isinstance(style, dict):
            return None
        return {
            "text": style.get("text"),
            "size": style.get("size"),
            "color": style.get("color"),
            "bgcolor": style.get("bgcolor"),
            "show_topbar": style.get("show_topbar"),
            "alignment": style.get("alignment"),
            "pngalignment": style.get("pngalignment"),
        }

    async def get_button_info_current(self, page: int, row: int, column: int) -> dict[str, Any]:
        pages_result = await self.get_pages_snapshot()
        if not pages_result.get("ok"):
            return pages_result

        pages_snapshot = pages_result.get("body")
        control_id = self._control_id_from_pages_snapshot(pages_snapshot, page, row, column)
        preview_result = await self.get_preview_location(page, row, column)
        if not preview_result.get("ok"):
            return preview_result

        if not control_id:
            return {
                "ok": True,
                "transport": "trpc-ws",
                "path": "controls.watchControl",
                "body": {
                    "page": page,
                    "row": row,
                    "column": column,
                    "control_id": None,
                    "exists": False,
                    "preview": preview_result.get("body"),
                    "preview_meta": self._preview_meta(preview_result.get("body")),
                },
            }

        control_result = await self.get_control_snapshot(control_id)
        if not control_result.get("ok"):
            return control_result
        control_body = control_result.get("body")

        return {
            "ok": True,
            "transport": "trpc-ws",
            "path": "controls.watchControl",
            "body": {
                "page": page,
                "row": row,
                "column": column,
                "control_id": control_id,
                "exists": True,
                "control": control_body,
                "style_meta": self._style_meta(control_body),
                "preview": preview_result.get("body"),
                "preview_meta": self._preview_meta(preview_result.get("body")),
            },
        }

    async def get_page_grid_current(
        self,
        page: int,
        rows: int,
        columns: int,
        include_empty: bool = False,
    ) -> dict[str, Any]:
        pages_result = await self.get_pages_snapshot()
        if not pages_result.get("ok"):
            return pages_result

        pages_snapshot = pages_result.get("body")
        buttons: list[dict[str, Any]] = []
        for row in range(rows):
            for column in range(columns):
                control_id = self._control_id_from_pages_snapshot(pages_snapshot, page, row, column)
                if not include_empty and not control_id:
                    continue

                preview_result = await self.get_preview_location(page, row, column)
                control_result = await self.get_control_snapshot(control_id) if control_id else None
                control_body = control_result.get("body") if control_result and control_result.get("ok") else None
                buttons.append(
                    {
                        "page": page,
                        "row": row,
                        "column": column,
                        "control_id": control_id,
                        "exists": control_id is not None,
                        "preview": preview_result.get("body") if preview_result.get("ok") else None,
                        "preview_meta": self._preview_meta(preview_result.get("body")) if preview_result.get("ok") else None,
                        "control": control_body,
                        "style_meta": self._style_meta(control_body),
                    }
                )

        return {
            "ok": True,
            "transport": "trpc-ws",
            "path": "pages.watch",
            "body": {
                "page": page,
                "rows": rows,
                "columns": columns,
                "include_empty": include_empty,
                "count": len(buttons),
                "buttons": buttons,
            },
        }
