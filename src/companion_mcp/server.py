"""
Companion MCP Server

MCP server for Bitfocus Companion — button control, styling,
variable management, and batch show programming via HTTP API.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import CompanionClient
from .config import CompanionConfig, load_config


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


# ============================================================
# Read Tools
# ============================================================


@mcp.tool()
async def get_server_config() -> str:
    """Return the current Companion MCP server configuration."""
    config = load_config()
    return _json({
        "host": config.host,
        "port": config.port,
        "base_url": config.base_url,
    })


@mcp.tool()
async def get_custom_variable(name: str) -> str:
    """Get the value of a Companion custom variable."""
    result = await _client().get_variable(f"/api/custom-variable/{name}/value")
    return _json(result)


@mcp.tool()
async def get_module_variable(connection: str, name: str) -> str:
    """Get a module variable value from a named Companion connection."""
    result = await _client().get_variable(f"/api/variable/{connection}/{name}/value")
    return _json(result)


# ============================================================
# Button Actions
# ============================================================


@mcp.tool()
async def press_button(page: int, row: int, column: int) -> str:
    """Press and release a button (runs both down and up actions)."""
    result = await _client().button_action(page, row, column, "press")
    return _json(result)


@mcp.tool()
async def hold_button(page: int, row: int, column: int) -> str:
    """Press and hold a button (runs down actions only). Use release_button to let go."""
    result = await _client().button_action(page, row, column, "down")
    return _json(result)


@mcp.tool()
async def release_button(page: int, row: int, column: int) -> str:
    """Release a held button (runs up actions)."""
    result = await _client().button_action(page, row, column, "up")
    return _json(result)


@mcp.tool()
async def rotate_left(page: int, row: int, column: int) -> str:
    """Trigger a left rotation on an encoder button."""
    result = await _client().button_action(page, row, column, "rotate-left")
    return _json(result)


@mcp.tool()
async def rotate_right(page: int, row: int, column: int) -> str:
    """Trigger a right rotation on an encoder button."""
    result = await _client().button_action(page, row, column, "rotate-right")
    return _json(result)


@mcp.tool()
async def set_step(page: int, row: int, column: int, step: int) -> str:
    """Set the current step of a button action sequence."""
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
async def set_button_text(page: int, row: int, column: int, text: str) -> str:
    """Change the text displayed on a button."""
    result = await _client().set_style(page, row, column, text=text)
    return _json(result)


@mcp.tool()
async def set_button_color(
    page: int,
    row: int,
    column: int,
    *,
    color: str = "",
    bgcolor: str = "",
) -> str:
    """Change button colors. Use 6-digit hex (e.g. 'ff0000' for red). color=text color, bgcolor=background color."""
    style: dict[str, Any] = {}
    if color:
        style["color"] = color
    if bgcolor:
        style["bgcolor"] = bgcolor
    result = await _client().set_style(page, row, column, **style)
    return _json(result)


@mcp.tool()
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
    style: dict[str, Any] = {}
    if text:
        style["text"] = text
    if color:
        style["color"] = color
    if bgcolor:
        style["bgcolor"] = bgcolor
    if size:
        style["size"] = size
    result = await _client().set_style(page, row, column, **style)
    return _json(result)


# ============================================================
# Custom Variables
# ============================================================


@mcp.tool()
async def set_custom_variable(name: str, value: str) -> str:
    """Set the value of a Companion custom variable."""
    result = await _client().set_variable(name, value)
    return _json(result)


# ============================================================
# Surface Management
# ============================================================


@mcp.tool()
async def rescan_surfaces() -> str:
    """Rescan for connected USB surfaces (Stream Deck, etc.)."""
    result = await _client().request("POST", "/api/surfaces/rescan")
    return _json(result)


# ============================================================
# Batch Operations
# ============================================================


@mcp.tool()
async def press_button_sequence(buttons_json: str, delay_ms: int = 100) -> str:
    """Press multiple buttons in sequence with a configurable delay between each.

    buttons_json: JSON array of {page, row, column} objects.
    delay_ms: milliseconds to wait between presses (default 100).
    """
    buttons = json.loads(buttons_json)
    if not isinstance(buttons, list):
        raise ValueError("buttons_json must be a JSON array of {page, row, column} objects.")

    client = _client()
    results: list[dict[str, Any]] = []
    for i, btn in enumerate(buttons):
        if not isinstance(btn, dict) or "page" not in btn or "row" not in btn or "column" not in btn:
            raise ValueError(f"Button at index {i} must have page, row, and column fields.")
        result = await client.button_action(btn["page"], btn["row"], btn["column"], "press")
        results.append({"button": btn, "result": result})
        if i < len(buttons) - 1:
            await asyncio.sleep(delay_ms / 1000)

    return _json({"action": "press_sequence", "count": len(results), "results": results})


@mcp.tool()
async def set_page_style(page: int, buttons_json: str) -> str:
    """Batch-set style on multiple buttons on a page.

    buttons_json: JSON array of {row, column, text?, color?, bgcolor?} objects.
    """
    buttons = json.loads(buttons_json)
    if not isinstance(buttons, list):
        raise ValueError("buttons_json must be a JSON array.")

    client = _client()
    results: list[dict[str, Any]] = []
    for btn in buttons:
        if not isinstance(btn, dict) or "row" not in btn or "column" not in btn:
            raise ValueError("Each button must have row and column fields.")
        style = {k: v for k, v in btn.items() if k not in ("row", "column") and v}
        result = await client.set_style(page, btn["row"], btn["column"], **style)
        results.append({"button": {"page": page, "row": btn["row"], "column": btn["column"]}, "result": result})

    return _json({"action": "set_page_style", "page": page, "count": len(results), "results": results})


@mcp.tool()
async def label_button_grid(page: int, labels_json: str, columns: int = 8) -> str:
    """Label a grid of buttons from a flat list of names.

    Fills left-to-right, top-to-bottom. Empty strings skip that position.
    labels_json: JSON array of strings, e.g. ["GO", "STOP", "", "BLACKOUT"]
    columns: buttons per row (default 8, use 5 for standard Stream Deck).
    """
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


# ============================================================
# Legacy Support
# ============================================================


@mcp.tool()
async def press_bank_button(page: int, button: int) -> str:
    """Press a button using the legacy bank API (deprecated but still works). button is 0-indexed."""
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
