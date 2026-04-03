from __future__ import annotations

import asyncio
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import server


def _ui_host() -> str:
    return os.environ.get("COMPANION_UI_HOST", "127.0.0.1")


def _ui_port() -> int:
    raw = os.environ.get("COMPANION_UI_PORT", "8088")
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f"COMPANION_UI_PORT={raw!r} is not a valid integer") from None
    if not (1 <= port <= 65535):
        raise ValueError(f"COMPANION_UI_PORT={port} is outside valid port range 1-65535")
    return port


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, indent=2, default=str).encode("utf-8")


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _query_value(query: dict[str, list[str]], name: str, default: str = "") -> str:
    values = query.get(name)
    if not values:
        return default
    return values[0]


def _query_int(query: dict[str, list[str]], name: str, default: int) -> int:
    raw = _query_value(query, name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Query parameter {name!r} must be an integer.") from None


def _load_static_text(name: str) -> bytes:
    base = resources.files("companion_mcp").joinpath("ui_static")
    return base.joinpath(name).read_bytes()


async def _call_json(func, *args, **kwargs) -> dict[str, Any]:
    raw = await func(*args, **kwargs)
    return json.loads(raw)


async def _route_api(method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[int, bytes]:
    if method == "GET" and path == "/api/config":
        return HTTPStatus.OK, _json_bytes(await _call_json(server.get_server_config))
    if method == "GET" and path == "/api/health":
        return HTTPStatus.OK, _json_bytes(await _call_json(server.health_check))
    if method == "GET" and path == "/api/page":
        payload = await _call_json(
            server.get_page_grid,
            _query_int(query, "page", 1),
            _query_int(query, "rows", 4),
            _query_int(query, "columns", 8),
            _parse_bool(_query_value(query, "include_empty"), False),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "GET" and path == "/api/button":
        payload = await _call_json(
            server.get_button_info,
            _query_int(query, "page", 1),
            _query_int(query, "row", 0),
            _query_int(query, "column", 0),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "GET" and path == "/api/button/runtime":
        payload = await _call_json(
            server.get_button_runtime_summary,
            _query_int(query, "page", 1),
            _query_int(query, "row", 0),
            _query_int(query, "column", 0),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "GET" and path == "/api/search":
        payload = await _call_json(
            server.find_buttons,
            _query_value(query, "query"),
            _query_int(query, "page", 1),
            _query_int(query, "rows", 4),
            _query_int(query, "columns", 8),
            _parse_bool(_query_value(query, "include_empty"), False),
            _query_value(query, "control_type"),
            _query_value(query, "connection_id"),
            _query_value(query, "definition_id"),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "GET" and path == "/api/snapshots":
        return HTTPStatus.OK, _json_bytes(await _call_json(server.list_page_inventory_snapshots))
    if method == "GET" and path == "/api/snapshots/load":
        return HTTPStatus.OK, _json_bytes(await _call_json(server.load_page_inventory_snapshot, _query_value(query, "name")))
    if method == "DELETE" and path == "/api/snapshots":
        return HTTPStatus.OK, _json_bytes(await _call_json(server.delete_page_inventory_snapshot, _query_value(query, "name")))
    if method == "POST" and path == "/api/snapshots/save":
        payload = await _call_json(
            server.save_page_inventory_snapshot,
            str(body.get("name", "")),
            int(body.get("page", 1)),
            int(body.get("rows", 4)),
            int(body.get("columns", 8)),
            bool(body.get("include_empty", False)),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "GET" and path == "/api/presets":
        return HTTPStatus.OK, _json_bytes(await _call_json(server.list_page_style_presets))
    if method == "GET" and path == "/api/presets/load":
        return HTTPStatus.OK, _json_bytes(await _call_json(server.load_page_style_preset, _query_value(query, "name")))
    if method == "DELETE" and path == "/api/presets":
        return HTTPStatus.OK, _json_bytes(await _call_json(server.delete_page_style_preset, _query_value(query, "name")))
    if method == "POST" and path == "/api/presets/save":
        payload = await _call_json(
            server.save_page_style_preset,
            str(body.get("name", "")),
            int(body.get("page", 1)),
            int(body.get("rows", 4)),
            int(body.get("columns", 8)),
            bool(body.get("include_empty", False)),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "POST" and path == "/api/presets/preview-apply":
        payload = await _call_json(
            server.preview_apply_page_style_preset,
            str(body.get("name", "")),
            int(body.get("page", 0)),
            int(body.get("origin_row", 0)),
            int(body.get("origin_column", 0)),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "POST" and path == "/api/presets/apply":
        payload = await _call_json(
            server.apply_page_style_preset,
            str(body.get("name", "")),
            int(body.get("page", 0)),
            int(body.get("origin_row", 0)),
            int(body.get("origin_column", 0)),
            int(body.get("wait_ms", 500)),
            int(body.get("poll_ms", 100)),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "POST" and path == "/api/button/press-verified":
        payload = await _call_json(
            server.press_button_verified,
            int(body.get("page", 1)),
            int(body.get("row", 0)),
            int(body.get("column", 0)),
            int(body.get("wait_ms", 500)),
            int(body.get("poll_ms", 100)),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "POST" and path == "/api/button/style-verified":
        payload = await _call_json(
            server.set_button_style_verified,
            int(body.get("page", 1)),
            int(body.get("row", 0)),
            int(body.get("column", 0)),
            text=str(body.get("text", "")),
            color=str(body.get("color", "")),
            bgcolor=str(body.get("bgcolor", "")),
            size=str(body.get("size", "")),
            wait_ms=int(body.get("wait_ms", 500)),
            poll_ms=int(body.get("poll_ms", 100)),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "POST" and path == "/api/transactions/apply":
        entries_json = json.dumps(body.get("styles", []))
        payload = await _call_json(
            server.apply_page_style_transaction,
            str(body.get("snapshot_name", "")),
            int(body.get("page", 1)),
            entries_json,
            int(body.get("rows", 4)),
            int(body.get("columns", 8)),
            bool(body.get("include_empty", False)),
            int(body.get("wait_ms", 500)),
            int(body.get("poll_ms", 100)),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    if method == "POST" and path == "/api/transactions/rollback":
        payload = await _call_json(
            server.rollback_page_style_transaction,
            str(body.get("snapshot_name", "")),
            str(body.get("coords_json", "")),
            int(body.get("wait_ms", 500)),
            int(body.get("poll_ms", 100)),
        )
        return HTTPStatus.OK, _json_bytes(payload)
    return HTTPStatus.NOT_FOUND, _json_bytes({"ok": False, "error": f"No route for {method} {path}"})


class _UIHandler(BaseHTTPRequestHandler):
    server_version = "CompanionMCPUI/0.1"

    def log_message(self, format: str, *args) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, name: str, content_type: str) -> None:
        self._send(HTTPStatus.OK, _load_static_text(name), content_type)

    def _serve_api(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            body = self._read_json_body() if method in {"POST", "PUT", "PATCH"} else {}
            status, payload = asyncio.run(_route_api(method, parsed.path, query, body))
            self._send(status, payload, "application/json; charset=utf-8")
        except ValueError as exc:
            self._send(HTTPStatus.BAD_REQUEST, _json_bytes({"ok": False, "error": str(exc)}), "application/json; charset=utf-8")
        except Exception as exc:
            self._send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                _json_bytes({"ok": False, "error": "UI request failed.", "detail": str(exc)}),
                "application/json; charset=utf-8",
            )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_static("app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
            return
        if parsed.path.startswith("/api/"):
            self._serve_api("GET")
            return
        self._send(HTTPStatus.NOT_FOUND, b"Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        self._serve_api("POST")

    def do_DELETE(self) -> None:
        self._serve_api("DELETE")


def main() -> None:
    host = _ui_host()
    port = _ui_port()
    httpd = ThreadingHTTPServer((host, port), _UIHandler)
    print(f"Companion MCP UI listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
