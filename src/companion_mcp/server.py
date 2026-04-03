"""
Companion MCP Server

MCP server for Bitfocus Companion — button control, styling,
variable management, and batch show programming via HTTP API.
"""

from __future__ import annotations

import asyncio
import json
import os
from functools import wraps
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .client import CompanionClient
from .config import load_config


mcp = FastMCP(
    "Companion MCP",
    instructions=(
        "Control Bitfocus Companion button surfaces via HTTP API. "
        "Use page/row/column coordinates for button operations. "
        "Row and column are 0-indexed. Page is 1-indexed."
    ),
)


def _client() -> CompanionClient:
    return CompanionClient(load_config())


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _error(message: str, **extra: Any) -> str:
    return _json({"ok": False, "error": message, **extra})


def _handle_errors(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except json.JSONDecodeError as exc:
            return _error(f"Invalid JSON input: {exc.msg}", blocked=True)
        except ValueError as exc:
            return _error(str(exc), blocked=True)
        except httpx.HTTPError as exc:
            return _error("Companion HTTP request failed.", detail=str(exc), blocked=False)

    return wrapper


def _require_writes_enabled(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        config = load_config()
        if not config.write_enabled:
            return _error(
                "Companion write operations are disabled by COMPANION_WRITE_ENABLED=0.",
                blocked=True,
            )
        return await func(*args, **kwargs)

    return wrapper


def _validate_page(page: int) -> None:
    if page < 1:
        raise ValueError("page must be >= 1")


def _validate_row_column(row: int, column: int) -> None:
    if row < 0:
        raise ValueError("row must be >= 0")
    if column < 0:
        raise ValueError("column must be >= 0")


def _validate_button_coords(page: int, row: int, column: int) -> None:
    _validate_page(page)
    _validate_row_column(row, column)


def _validate_step(step: int) -> None:
    if step < 0:
        raise ValueError("step must be >= 0")


def _validate_delay_ms(delay_ms: int) -> None:
    if delay_ms < 0:
        raise ValueError("delay_ms must be >= 0")
    if delay_ms > 60_000:
        raise ValueError("delay_ms must be <= 60000")


def _validate_hex_color(value: str, field: str) -> None:
    if not value:
        return
    normalized = value.lstrip("#")
    if len(normalized) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in normalized):
        raise ValueError(f"{field} must be a 6-digit hex color")


def _normalize_style_payload(raw_style: dict[str, Any]) -> dict[str, Any]:
    style: dict[str, Any] = {}
    for key, value in raw_style.items():
        if key in ("row", "column") or value in (None, ""):
            continue
        if key in {"color", "bgcolor"}:
            value = str(value).lstrip("#")
            _validate_hex_color(value, key)
        style[key] = value
    return style


def _resolve_template_entries(
    page: int,
    template: list[dict[str, Any]],
    origin_row: int,
    origin_column: int,
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for i, entry in enumerate(template):
        if not isinstance(entry, dict):
            raise ValueError(f"Template entry at index {i} must be an object.")
        if "row" not in entry or "column" not in entry:
            raise ValueError(f"Template entry at index {i} must include row and column.")
        row = origin_row + int(entry["row"])
        column = origin_column + int(entry["column"])
        _validate_button_coords(page, row, column)
        style = _normalize_style_payload(entry)
        resolved.append({
            "page": page,
            "row": row,
            "column": column,
            "style": style,
        })
    return resolved


# ============================================================
# Read Tools
# ============================================================


@mcp.tool()
@_handle_errors
async def get_server_config() -> str:
    """Return the current Companion MCP server configuration."""
    config = load_config()
    return _json({
        "host": config.host,
        "port": config.port,
        "timeout_s": config.timeout_s,
        "allowed_hosts": list(config.allowed_hosts),
        "write_enabled": config.write_enabled,
        "base_url": config.base_url,
    })


@mcp.tool()
@_handle_errors
async def get_custom_variable(name: str) -> str:
    """Get the value of a Companion custom variable."""
    result = await _client().get_variable(f"/api/custom-variable/{name}/value")
    return _json(result)


@mcp.tool()
@_handle_errors
async def get_module_variable(connection: str, name: str) -> str:
    """Get a module variable value from a named Companion connection."""
    result = await _client().get_variable(f"/api/variable/{connection}/{name}/value")
    return _json(result)


@mcp.tool()
@_handle_errors
async def health_check() -> str:
    """Probe Companion reachability and return API status details."""
    config = load_config()
    result = await _client().request("GET", "/api/surfaces")
    return _json({
        "ok": result["ok"],
        "host": config.host,
        "port": config.port,
        "base_url": config.base_url,
        "probe_path": "/api/surfaces",
        "status_code": result["status_code"],
        "content_type": result["content_type"],
        "body": result["body"],
    })


@mcp.tool()
@_handle_errors
async def list_surfaces() -> str:
    """List connected Companion control surfaces."""
    result = await _client().list_surfaces()
    return _json(result)


@mcp.tool()
@_handle_errors
async def get_button_info(page: int, row: int, column: int) -> str:
    """Fetch the raw API payload for a Companion button location."""
    _validate_button_coords(page, row, column)
    result = await _client().get_button(page, row, column)
    return _json(result)


@mcp.tool()
@_handle_errors
async def get_page_grid(page: int, rows: int = 4, columns: int = 8, include_empty: bool = False) -> str:
    """Read a rectangular grid of button payloads for a page."""
    _validate_page(page)
    if rows <= 0:
        raise ValueError("rows must be >= 1")
    if columns <= 0:
        raise ValueError("columns must be >= 1")

    client = _client()
    buttons: list[dict[str, Any]] = []
    for row in range(rows):
        for column in range(columns):
            result = await client.get_button(page, row, column)
            body = result.get("body")
            is_empty = body in ("", None, {}, [])
            if include_empty or not is_empty:
                buttons.append({
                    "page": page,
                    "row": row,
                    "column": column,
                    "ok": result.get("ok", False),
                    "status_code": result.get("status_code"),
                    "body": body,
                })

    return _json({
        "page": page,
        "rows": rows,
        "columns": columns,
        "include_empty": include_empty,
        "count": len(buttons),
        "buttons": buttons,
    })


@mcp.tool()
@_handle_errors
async def export_page_layout(page: int, rows: int = 4, columns: int = 8, include_empty: bool = False) -> str:
    """Export a page region as a reusable layout payload."""
    raw = json.loads(await get_page_grid(page, rows=rows, columns=columns, include_empty=include_empty))
    buttons = []
    for button in raw.get("buttons", []):
        body = button.get("body")
        buttons.append({
            "row": button["row"],
            "column": button["column"],
            "body": body,
        })
    return _json({
        "page": page,
        "rows": rows,
        "columns": columns,
        "include_empty": include_empty,
        "button_count": len(buttons),
        "layout": buttons,
    })


@mcp.tool()
@_handle_errors
async def snapshot_custom_variables(names_json: str) -> str:
    """Read a named set of custom variables into one snapshot payload."""
    names = json.loads(names_json)
    if not isinstance(names, list):
        raise ValueError("names_json must be a JSON array of variable names.")

    client = _client()
    variables: list[dict[str, Any]] = []
    for i, name in enumerate(names):
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Variable at index {i} must be a non-empty string.")
        result = await client.get_variable(f"/api/custom-variable/{name}/value")
        variables.append({
            "name": name,
            "result": result,
        })

    return _json({
        "count": len(variables),
        "variables": variables,
    })


# ============================================================
# Button Actions
# ============================================================


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def press_button(page: int, row: int, column: int) -> str:
    """Press and release a button (runs both down and up actions)."""
    _validate_button_coords(page, row, column)
    result = await _client().button_action(page, row, column, "press")
    return _json(result)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def hold_button(page: int, row: int, column: int) -> str:
    """Press and hold a button (runs down actions only). Use release_button to let go."""
    _validate_button_coords(page, row, column)
    result = await _client().button_action(page, row, column, "down")
    return _json(result)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def release_button(page: int, row: int, column: int) -> str:
    """Release a held button (runs up actions)."""
    _validate_button_coords(page, row, column)
    result = await _client().button_action(page, row, column, "up")
    return _json(result)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def rotate_left(page: int, row: int, column: int) -> str:
    """Trigger a left rotation on an encoder button."""
    _validate_button_coords(page, row, column)
    result = await _client().button_action(page, row, column, "rotate-left")
    return _json(result)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def rotate_right(page: int, row: int, column: int) -> str:
    """Trigger a right rotation on an encoder button."""
    _validate_button_coords(page, row, column)
    result = await _client().button_action(page, row, column, "rotate-right")
    return _json(result)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_step(page: int, row: int, column: int, step: int) -> str:
    """Set the current step of a button action sequence."""
    _validate_button_coords(page, row, column)
    _validate_step(step)
    result = await _client().request(
        "POST",
        f"/api/location/{page}/{row}/{column}/step",
        body={"step": step},
    )
    return _json(result)


# ============================================================
# Button Styling
# ============================================================


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_button_text(page: int, row: int, column: int, text: str) -> str:
    """Change the text displayed on a button."""
    _validate_button_coords(page, row, column)
    result = await _client().set_style(page, row, column, text=text)
    return _json(result)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_button_color(
    page: int,
    row: int,
    column: int,
    *,
    color: str = "",
    bgcolor: str = "",
) -> str:
    """Change button colors. Use 6-digit hex (e.g. 'ff0000' for red). color=text color, bgcolor=background color."""
    _validate_button_coords(page, row, column)
    _validate_hex_color(color, "color")
    _validate_hex_color(bgcolor, "bgcolor")
    style: dict[str, Any] = {}
    if color:
        style["color"] = color
    if bgcolor:
        style["bgcolor"] = bgcolor
    result = await _client().set_style(page, row, column, **style)
    return _json(result)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_button_style(
    page: int,
    row: int,
    column: int,
    *,
    text: str = "",
    color: str = "",
    bgcolor: str = "",
    size: str = "",
) -> str:
    """Set multiple button style properties at once. All parameters optional — only provided values are changed."""
    _validate_button_coords(page, row, column)
    _validate_hex_color(color, "color")
    _validate_hex_color(bgcolor, "bgcolor")
    style = _normalize_style_payload({"text": text, "color": color, "bgcolor": bgcolor, "size": size})
    result = await _client().set_style(page, row, column, **style)
    return _json(result)


# ============================================================
# Custom Variables
# ============================================================


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_custom_variable(name: str, value: str) -> str:
    """Set the value of a Companion custom variable."""
    result = await _client().set_variable(name, value)
    return _json(result)


# ============================================================
# Surface Management
# ============================================================


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def rescan_surfaces() -> str:
    """Rescan for connected USB surfaces (Stream Deck, etc.)."""
    result = await _client().request("POST", "/api/surfaces/rescan")
    return _json(result)


# ============================================================
# Batch Operations
# ============================================================


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def press_button_sequence(buttons_json: str, delay_ms: int = 100) -> str:
    """Press multiple buttons in sequence with a configurable delay between each.

    buttons_json: JSON array of {page, row, column} objects.
    delay_ms: milliseconds to wait between presses (default 100).
    """
    _validate_delay_ms(delay_ms)
    buttons = json.loads(buttons_json)
    if not isinstance(buttons, list):
        raise ValueError("buttons_json must be a JSON array of {page, row, column} objects.")

    client = _client()
    results: list[dict[str, Any]] = []
    for i, btn in enumerate(buttons):
        if not isinstance(btn, dict) or "page" not in btn or "row" not in btn or "column" not in btn:
            raise ValueError(f"Button at index {i} must have page, row, and column fields.")
        _validate_button_coords(btn["page"], btn["row"], btn["column"])
        result = await client.button_action(btn["page"], btn["row"], btn["column"], "press")
        results.append({"button": btn, "result": result})
        if i < len(buttons) - 1:
            await asyncio.sleep(delay_ms / 1000)

    return _json({"action": "press_sequence", "count": len(results), "results": results})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_page_style(page: int, buttons_json: str) -> str:
    """Batch-set style on multiple buttons on a page.

    buttons_json: JSON array of {row, column, text?, color?, bgcolor?} objects.
    """
    _validate_page(page)
    buttons = json.loads(buttons_json)
    if not isinstance(buttons, list):
        raise ValueError("buttons_json must be a JSON array.")

    client = _client()
    results: list[dict[str, Any]] = []
    for btn in buttons:
        if not isinstance(btn, dict) or "row" not in btn or "column" not in btn:
            raise ValueError("Each button must have row and column fields.")
        _validate_row_column(btn["row"], btn["column"])
        style = _normalize_style_payload(btn)
        result = await client.set_style(page, btn["row"], btn["column"], **style)
        results.append({"button": {"page": page, "row": btn["row"], "column": btn["column"]}, "result": result})

    return _json({"action": "set_page_style", "page": page, "count": len(results), "results": results})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def label_button_grid(page: int, labels_json: str, columns: int = 8) -> str:
    """Label a grid of buttons from a flat list of names.

    Fills left-to-right, top-to-bottom. Empty strings skip that position.
    labels_json: JSON array of strings, e.g. ["GO", "STOP", "", "BLACKOUT"]
    columns: buttons per row (default 8, use 5 for standard Stream Deck).
    """
    _validate_page(page)
    if columns <= 0:
        raise ValueError("columns must be >= 1")
    labels = json.loads(labels_json)
    if not isinstance(labels, list):
        raise ValueError("labels_json must be a JSON array of strings.")

    client = _client()
    results: list[dict[str, Any]] = []
    for i, label in enumerate(labels):
        if not label:
            continue
        row = i // columns
        col = i % columns
        result = await client.set_style(page, row, col, text=str(label))
        results.append({"row": row, "column": col, "text": label, "result": result})

    return _json({"action": "label_grid", "page": page, "columns": columns, "labeled": len(results), "results": results})


@mcp.tool()
@_handle_errors
async def preview_page_style(page: int, buttons_json: str) -> str:
    """Validate and preview a batch page-style operation without writing to Companion."""
    _validate_page(page)
    buttons = json.loads(buttons_json)
    if not isinstance(buttons, list):
        raise ValueError("buttons_json must be a JSON array.")

    preview: list[dict[str, Any]] = []
    for btn in buttons:
        if not isinstance(btn, dict) or "row" not in btn or "column" not in btn:
            raise ValueError("Each button must have row and column fields.")
        _validate_row_column(btn["row"], btn["column"])
        style = _normalize_style_payload(btn)
        preview.append({
            "page": page,
            "row": btn["row"],
            "column": btn["column"],
            "style": style,
        })

    return _json({
        "action": "preview_page_style",
        "page": page,
        "count": len(preview),
        "writes_companion": False,
        "preview": preview,
    })


@mcp.tool()
@_handle_errors
async def preview_label_button_grid(page: int, labels_json: str, columns: int = 8) -> str:
    """Resolve a label grid into coordinates without writing to Companion."""
    _validate_page(page)
    if columns <= 0:
        raise ValueError("columns must be >= 1")
    labels = json.loads(labels_json)
    if not isinstance(labels, list):
        raise ValueError("labels_json must be a JSON array of strings.")

    preview: list[dict[str, Any]] = []
    for i, label in enumerate(labels):
        if not label:
            continue
        preview.append({
            "page": page,
            "row": i // columns,
            "column": i % columns,
            "text": str(label),
        })

    return _json({
        "action": "preview_label_grid",
        "page": page,
        "columns": columns,
        "labeled": len(preview),
        "writes_companion": False,
        "preview": preview,
    })


@mcp.tool()
@_handle_errors
async def preview_button_template(
    page: int,
    template_json: str,
    origin_row: int = 0,
    origin_column: int = 0,
) -> str:
    """Preview a reusable button template placed at an origin on a page."""
    _validate_page(page)
    _validate_row_column(origin_row, origin_column)
    template = json.loads(template_json)
    if not isinstance(template, list):
        raise ValueError("template_json must be a JSON array of button template entries.")
    resolved = _resolve_template_entries(page, template, origin_row, origin_column)
    return _json({
        "action": "preview_button_template",
        "page": page,
        "origin_row": origin_row,
        "origin_column": origin_column,
        "count": len(resolved),
        "writes_companion": False,
        "preview": resolved,
    })


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def apply_button_template(
    page: int,
    template_json: str,
    origin_row: int = 0,
    origin_column: int = 0,
) -> str:
    """Apply a reusable button template at an origin on a page."""
    _validate_page(page)
    _validate_row_column(origin_row, origin_column)
    template = json.loads(template_json)
    if not isinstance(template, list):
        raise ValueError("template_json must be a JSON array of button template entries.")
    resolved = _resolve_template_entries(page, template, origin_row, origin_column)

    client = _client()
    results: list[dict[str, Any]] = []
    for entry in resolved:
        result = await client.set_style(entry["page"], entry["row"], entry["column"], **entry["style"])
        results.append({
            "page": entry["page"],
            "row": entry["row"],
            "column": entry["column"],
            "style": entry["style"],
            "result": result,
        })

    return _json({
        "action": "apply_button_template",
        "page": page,
        "origin_row": origin_row,
        "origin_column": origin_column,
        "count": len(results),
        "results": results,
    })


# ============================================================
# Legacy Support
# ============================================================


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def press_bank_button(page: int, button: int) -> str:
    """Press a button using the legacy bank API (deprecated but still works). button is 0-indexed."""
    _validate_page(page)
    if button < 0:
        raise ValueError("button must be >= 0")
    result = await _client().request("GET", f"/press/bank/{page}/{button}")
    return _json(result)


# ============================================================
# Server Startup
# ============================================================

_VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


def main():
    """MCP Server entry point."""
    transport = os.environ.get("COMPANION_TRANSPORT", "stdio").lower()
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(
            f"Invalid COMPANION_TRANSPORT={transport!r}. "
            f"Valid options: {', '.join(_VALID_TRANSPORTS)}"
        )
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
