"""
Companion MCP Server

MCP server for Bitfocus Companion — button control, styling,
variable management, and batch show programming via current Companion APIs.
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
        "Control Bitfocus Companion button surfaces via current Companion APIs. "
        "Writes use HTTP endpoints and richer reads use websocket tRPC where available. "
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


def _compat_error(message: str, **extra: Any) -> str:
    return _error(message, blocked=True, compatibility="current_companion_version", **extra)


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


def _validate_poll_ms(value: int, field: str) -> None:
    if value < 0:
        raise ValueError(f"{field} must be >= 0")
    if value > 10_000:
        raise ValueError(f"{field} must be <= 10000")


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


def _button_runtime_summary(button: dict[str, Any]) -> dict[str, Any]:
    control = button.get("control") or {}
    config = control.get("config") or {}
    runtime = control.get("runtime") or {}
    style_meta = button.get("style_meta") or {}
    feedback_meta = button.get("feedback_meta") or {}
    preview_meta = button.get("preview_meta") or {}
    control_type = config.get("type")
    current_step_id = runtime.get("current_step_id")
    return {
        "control_type": control_type,
        "current_step_id": current_step_id,
        "is_stepped": current_step_id not in (None, "", "0"),
        "has_feedback_overrides": feedback_meta.get("style_may_be_feedback_controlled", False),
        "visible_text": style_meta.get("text"),
        "preview_sha256": preview_meta.get("image_sha256"),
        "is_used": preview_meta.get("isUsed"),
    }


def _button_integration_summary(button: dict[str, Any]) -> dict[str, Any]:
    control = button.get("control") or {}
    feedback_meta = button.get("feedback_meta") or {}
    feedback_items = feedback_meta.get("items") or []
    config = control.get("config") or {}
    steps = control.get("steps") or {}

    connection_ids: set[str] = set()
    definition_ids: set[str] = set()
    for item in feedback_items:
        connection_id = item.get("connectionId")
        definition_id = item.get("definitionId")
        if connection_id:
            connection_ids.add(str(connection_id))
        if definition_id:
            definition_ids.add(str(definition_id))

    if isinstance(steps, dict):
        for step in steps.values():
            if not isinstance(step, dict):
                continue
            action_sets = step.get("action_sets") or {}
            if not isinstance(action_sets, dict):
                continue
            for actions in action_sets.values():
                if not isinstance(actions, list):
                    continue
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    connection_id = action.get("connectionId")
                    definition_id = action.get("definitionId")
                    if connection_id:
                        connection_ids.add(str(connection_id))
                    if definition_id:
                        definition_ids.add(str(definition_id))

    return {
        "connection_ids": sorted(connection_ids),
        "definition_ids": sorted(definition_ids),
        "config_type": config.get("type"),
    }


def _summarize_button(button: dict[str, Any]) -> dict[str, Any]:
    control = button.get("control") or {}
    config = control.get("config") or {}
    return {
        "page": button.get("page"),
        "row": button.get("row"),
        "column": button.get("column"),
        "control_id": button.get("control_id"),
        "exists": button.get("exists"),
        "control_type": config.get("type"),
        "style_meta": button.get("style_meta"),
        "feedback_meta": button.get("feedback_meta"),
        "integration_summary": _button_integration_summary(button),
        "runtime_summary": _button_runtime_summary(button),
        "preview_meta": button.get("preview_meta"),
    }


def _button_key(button: dict[str, Any]) -> tuple[int | None, int | None]:
    return (button.get("row"), button.get("column"))


def _diff_inventory(before_buttons: list[dict[str, Any]], after_buttons: list[dict[str, Any]]) -> dict[str, Any]:
    before_map = {_button_key(button): button for button in before_buttons}
    after_map = {_button_key(button): button for button in after_buttons}
    keys = sorted(set(before_map) | set(after_map))
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    unchanged = 0

    for key in keys:
        before = before_map.get(key)
        after = after_map.get(key)
        if before is None and after is not None:
            added.append(after)
            continue
        if after is None and before is not None:
            removed.append(before)
            continue
        if before == after:
            unchanged += 1
            continue
        changed.append({
            "row": key[0],
            "column": key[1],
            "before": before,
            "after": after,
            "render_changed": ((before or {}).get("preview_meta") or {}).get("image_sha256") != ((after or {}).get("preview_meta") or {}).get("image_sha256"),
            "style_changed": (before or {}).get("style_meta") != (after or {}).get("style_meta"),
            "runtime_changed": (before or {}).get("runtime_summary") != (after or {}).get("runtime_summary"),
        })

    return {
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "unchanged_count": unchanged,
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _restore_entries_from_inventory(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    buttons = inventory.get("buttons")
    if not isinstance(buttons, list):
        raise ValueError("inventory_json must include a buttons array.")
    entries: list[dict[str, Any]] = []
    for button in buttons:
        if not isinstance(button, dict):
            raise ValueError("Each inventory button entry must be an object.")
        row = button.get("row")
        column = button.get("column")
        if not isinstance(row, int) or not isinstance(column, int):
            raise ValueError("Each inventory button entry must include integer row and column values.")
        style_meta = button.get("style_meta")
        if not isinstance(style_meta, dict):
            continue
        entry: dict[str, Any] = {"row": row, "column": column}
        for key in ("text", "size"):
            value = style_meta.get(key)
            if value not in (None, ""):
                entry[key] = value
        for key in ("color", "bgcolor"):
            value = style_meta.get(key)
            if isinstance(value, int):
                entry[key] = f"{value:06x}"
            elif isinstance(value, str) and value:
                entry[key] = value.lstrip("#")
        if len(entry) > 2:
            entries.append(entry)
    return entries


async def _poll_button_info(
    client: CompanionClient,
    page: int,
    row: int,
    column: int,
    *,
    previous_preview_sha: str | None,
    wait_ms: int,
    poll_ms: int,
) -> tuple[dict[str, Any], int]:
    after = await client.get_button_info_current(page, row, column)
    if not after.get("ok"):
        return after, 1

    polls = 1
    if previous_preview_sha and wait_ms > 0:
        elapsed = 0
        while elapsed < wait_ms:
            current_preview_sha = ((after.get("body") or {}).get("preview_meta") or {}).get("image_sha256")
            if current_preview_sha and current_preview_sha != previous_preview_sha:
                break
            await asyncio.sleep(poll_ms / 1000)
            elapsed += poll_ms
            polls += 1
            after = await client.get_button_info_current(page, row, column)
            if not after.get("ok"):
                break
    return after, polls


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
    result = await _client().get_custom_variable_current(name)
    if not result.get("ok") and result.get("error_code") == "NOT_FOUND":
        return _compat_error(
            "This Companion build does not expose the expected custom-variable tRPC procedure.",
            path=result.get("path"),
            error=result.get("error"),
        )
    return _json(result)


@mcp.tool()
@_handle_errors
async def get_module_variable(connection: str, name: str) -> str:
    """Get a module variable value from a named Companion connection."""
    result = await _client().get_module_variable_current(connection, name)
    if not result.get("ok") and result.get("error_code") == "NOT_FOUND":
        return _compat_error(
            "This Companion build does not expose the expected module-variable tRPC procedure.",
            path=result.get("path"),
            error=result.get("error"),
        )
    return _json(result)


@mcp.tool()
@_handle_errors
async def health_check() -> str:
    """Probe Companion reachability and return API status details."""
    config = load_config()
    result = await _client().request("GET", "/")
    app_info = await _client().get_app_info()
    return _json({
        "ok": result["ok"],
        "host": config.host,
        "port": config.port,
        "base_url": config.base_url,
        "ws_base_url": config.ws_base_url,
        "probe_path": "/",
        "status_code": result["status_code"],
        "content_type": result["content_type"],
        "body": result["body"],
        "app_info": app_info,
    })


@mcp.tool()
@_handle_errors
async def list_surfaces() -> str:
    """List connected Companion control surfaces."""
    result = await _client().list_surfaces()
    if not result.get("ok") and result.get("error_code") == "NOT_FOUND":
        return _compat_error(
            "This Companion build does not expose the expected surface discovery tRPC procedure.",
            path=result.get("path"),
            error=result.get("error"),
        )
    return _json(result)


@mcp.tool()
@_handle_errors
async def get_button_info(page: int, row: int, column: int) -> str:
    """Fetch the current control state and rendered preview metadata for a Companion button location."""
    _validate_button_coords(page, row, column)
    result = await _client().get_button_info_current(page, row, column)
    if not result.get("ok") and result.get("error_code") == "NOT_FOUND":
        return _compat_error(
            "This Companion build does not expose the expected control inspection tRPC procedure.",
            path=result.get("path"),
            error=result.get("error"),
        )
    return _json(result)


@mcp.tool()
@_handle_errors
async def get_button_runtime_summary(page: int, row: int, column: int) -> str:
    """Return a compact runtime-oriented summary for a button."""
    _validate_button_coords(page, row, column)
    result = await _client().get_button_info_current(page, row, column)
    if not result.get("ok"):
        if result.get("error_code") == "NOT_FOUND":
            return _compat_error(
                "This Companion build does not expose the expected control inspection tRPC procedure.",
                path=result.get("path"),
                error=result.get("error"),
            )
        return _json(result)
    body = result.get("body", {})
    return _json({
        "ok": True,
        "page": page,
        "row": row,
        "column": column,
        "runtime_summary": _button_runtime_summary(body),
    })


@mcp.tool()
@_handle_errors
async def verify_button_render_change(page: int, row: int, column: int, previous_sha256: str) -> str:
    """Compare the current button preview fingerprint to a previous preview hash."""
    _validate_button_coords(page, row, column)
    result = await _client().get_button_info_current(page, row, column)
    if not result.get("ok"):
        if result.get("error_code") == "NOT_FOUND":
            return _compat_error(
                "This Companion build does not expose the expected control inspection tRPC procedure.",
                path=result.get("path"),
                error=result.get("error"),
            )
        return _json(result)

    preview_meta = result.get("body", {}).get("preview_meta") or {}
    current_sha = preview_meta.get("image_sha256")
    return _json({
        "ok": True,
        "page": page,
        "row": row,
        "column": column,
        "previous_sha256": previous_sha256,
        "current_sha256": current_sha,
        "changed": bool(current_sha and previous_sha256 and current_sha != previous_sha256),
        "preview_meta": preview_meta,
    })


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_button_style_verified(
    page: int,
    row: int,
    column: int,
    *,
    text: str = "",
    color: str = "",
    bgcolor: str = "",
    size: str = "",
    wait_ms: int = 500,
    poll_ms: int = 100,
) -> str:
    """Apply button style changes and verify whether the rendered button output actually changed."""
    _validate_button_coords(page, row, column)
    _validate_hex_color(color, "color")
    _validate_hex_color(bgcolor, "bgcolor")
    _validate_poll_ms(wait_ms, "wait_ms")
    _validate_poll_ms(poll_ms, "poll_ms")
    if wait_ms and poll_ms == 0:
        raise ValueError("poll_ms must be > 0 when wait_ms is non-zero.")
    style = _normalize_style_payload({"text": text, "color": color, "bgcolor": bgcolor, "size": size})
    if not style:
        raise ValueError("At least one style field must be provided.")

    client = _client()
    before = await client.get_button_info_current(page, row, column)
    if not before.get("ok"):
        return _json(before)

    write_result = await client.set_style(page, row, column, **style)
    before_preview_sha = ((before.get("body") or {}).get("preview_meta") or {}).get("image_sha256")
    after, polls = await _poll_button_info(
        client,
        page,
        row,
        column,
        previous_preview_sha=before_preview_sha,
        wait_ms=wait_ms,
        poll_ms=poll_ms,
    )
    if not after.get("ok"):
        return _json({
            "ok": False,
            "page": page,
            "row": row,
            "column": column,
            "write_result": write_result,
            "after": after,
        })

    before_body = before.get("body", {})
    after_body = after.get("body", {})
    before_preview = before_body.get("preview_meta") or {}
    after_preview = after_body.get("preview_meta") or {}
    before_control = (before_body.get("control") or {}).get("config") or {}
    after_control = (after_body.get("control") or {}).get("config") or {}
    before_style = before_body.get("style_meta")
    after_style = after_body.get("style_meta")
    after_feedback = after_body.get("feedback_meta") or {}

    return _json({
        "ok": bool(write_result.get("ok")) and after.get("ok", False),
        "page": page,
        "row": row,
        "column": column,
        "applied_style": style,
        "control_type": after_control.get("type"),
        "write_result": write_result,
        "wait_ms": wait_ms,
        "poll_ms": poll_ms,
        "polls": polls,
        "render_changed": before_preview.get("image_sha256") != after_preview.get("image_sha256"),
        "style_changed": before_style != after_style,
        "style_may_be_feedback_controlled": after_feedback.get("style_may_be_feedback_controlled", False),
        "feedback_summary": after_feedback,
        "before": {
            "style_meta": before_style,
            "preview_meta": before_preview,
        },
        "after": {
            "style_meta": after_style,
            "feedback_meta": after_feedback,
            "preview_meta": after_preview,
        },
    })


@mcp.tool()
@_handle_errors
async def get_page_grid(page: int, rows: int = 4, columns: int = 8, include_empty: bool = False) -> str:
    """Read a rectangular grid of button payloads for a page."""
    _validate_page(page)
    if rows <= 0:
        raise ValueError("rows must be >= 1")
    if columns <= 0:
        raise ValueError("columns must be >= 1")

    result = await _client().get_page_grid_current(page, rows, columns, include_empty)
    if not result.get("ok") and result.get("error_code") == "NOT_FOUND":
        return _compat_error(
            "This Companion build does not expose the expected page or preview tRPC procedures.",
            path=result.get("path"),
            error=result.get("error"),
        )
    body = result.get("body", {})
    return _json(body)


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
async def snapshot_page_inventory(page: int, rows: int = 4, columns: int = 8, include_empty: bool = False) -> str:
    """Export a page region with operator-focused button summaries, hashes, style, and feedback state."""
    raw = json.loads(await get_page_grid(page, rows=rows, columns=columns, include_empty=include_empty))
    buttons = [_summarize_button(button) for button in raw.get("buttons", [])]
    return _json({
        "page": page,
        "rows": rows,
        "columns": columns,
        "include_empty": include_empty,
        "button_count": len(buttons),
        "buttons": buttons,
    })


@mcp.tool()
@_handle_errors
async def diff_page_inventory(before_inventory_json: str, after_inventory_json: str) -> str:
    """Compare two page inventory snapshots and summarize added, removed, and changed buttons."""
    before = json.loads(before_inventory_json)
    after = json.loads(after_inventory_json)
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("Both inventory payloads must be JSON objects.")
    before_buttons = before.get("buttons")
    after_buttons = after.get("buttons")
    if not isinstance(before_buttons, list) or not isinstance(after_buttons, list):
        raise ValueError("Both inventory payloads must include a buttons array.")
    diff = _diff_inventory(before_buttons, after_buttons)
    return _json({
        "before_page": before.get("page"),
        "after_page": after.get("page"),
        **diff,
    })


@mcp.tool()
@_handle_errors
async def preview_restore_page_style_from_inventory(inventory_json: str) -> str:
    """Resolve a captured page inventory into restore-style entries without writing to Companion."""
    inventory = json.loads(inventory_json)
    if not isinstance(inventory, dict):
        raise ValueError("inventory_json must be a JSON object.")
    page = inventory.get("page")
    if not isinstance(page, int):
        raise ValueError("inventory_json must include an integer page.")
    entries = _restore_entries_from_inventory(inventory)
    return _json({
        "action": "preview_restore_page_style_from_inventory",
        "page": page,
        "count": len(entries),
        "writes_companion": False,
        "preview": entries,
    })


@mcp.tool()
@_handle_errors
async def find_buttons(
    query: str = "",
    page: int = 1,
    rows: int = 4,
    columns: int = 8,
    include_empty: bool = False,
    control_type: str = "",
    connection_id: str = "",
    definition_id: str = "",
) -> str:
    """Find buttons by text, control id, control type, or integration metadata within a page region."""
    raw = json.loads(await get_page_grid(page, rows=rows, columns=columns, include_empty=include_empty))
    needle = query.strip().lower()
    type_filter = control_type.strip().lower()
    connection_filter = connection_id.strip().lower()
    definition_filter = definition_id.strip().lower()
    matches = []
    for button in raw.get("buttons", []):
        summary = _summarize_button(button)
        integration_summary = summary.get("integration_summary") or {}
        haystack = " ".join(
            str(value)
            for value in [
                summary.get("control_id"),
                (summary.get("style_meta") or {}).get("text"),
                summary.get("control_type"),
                " ".join(integration_summary.get("connection_ids") or []),
                " ".join(integration_summary.get("definition_ids") or []),
            ]
            if value not in (None, "")
        ).lower()
        button_type = (summary.get("control_type") or "").lower()
        if needle and needle not in haystack:
            continue
        if type_filter and button_type != type_filter:
            continue
        connection_ids = [value.lower() for value in integration_summary.get("connection_ids") or []]
        definition_ids = [value.lower() for value in integration_summary.get("definition_ids") or []]
        if connection_filter and connection_filter not in connection_ids:
            continue
        if definition_filter and definition_filter not in definition_ids:
            continue
        matches.append(summary)
    return _json({
        "page": page,
        "rows": rows,
        "columns": columns,
        "query": query,
        "control_type": control_type,
        "connection_id": connection_id,
        "definition_id": definition_id,
        "count": len(matches),
        "matches": matches,
    })


@mcp.tool()
@_handle_errors
async def snapshot_custom_variables(names_json: str) -> str:
    """Read a named set of custom variables into one snapshot payload."""
    names = json.loads(names_json)
    if not isinstance(names, list):
        raise ValueError("names_json must be a JSON array of variable names.")

    variables: list[dict[str, Any]] = []
    for i, name in enumerate(names):
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Variable at index {i} must be a non-empty string.")
        result = await _client().get_custom_variable_current(name)
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
async def press_button_verified(page: int, row: int, column: int, wait_ms: int = 500, poll_ms: int = 100) -> str:
    """Press a button and verify whether its visible or runtime state changed."""
    _validate_button_coords(page, row, column)
    _validate_poll_ms(wait_ms, "wait_ms")
    _validate_poll_ms(poll_ms, "poll_ms")
    if wait_ms and poll_ms == 0:
        raise ValueError("poll_ms must be > 0 when wait_ms is non-zero.")

    client = _client()
    before = await client.get_button_info_current(page, row, column)
    if not before.get("ok"):
        return _json(before)

    write_result = await client.button_action(page, row, column, "press")
    before_preview_sha = ((before.get("body") or {}).get("preview_meta") or {}).get("image_sha256")
    after, polls = await _poll_button_info(
        client,
        page,
        row,
        column,
        previous_preview_sha=before_preview_sha,
        wait_ms=wait_ms,
        poll_ms=poll_ms,
    )
    if not after.get("ok"):
        return _json({
            "ok": False,
            "page": page,
            "row": row,
            "column": column,
            "write_result": write_result,
            "after": after,
        })

    before_body = before.get("body", {})
    after_body = after.get("body", {})
    before_preview = before_body.get("preview_meta") or {}
    after_preview = after_body.get("preview_meta") or {}
    before_runtime = _button_runtime_summary(before_body)
    after_runtime = _button_runtime_summary(after_body)
    return _json({
        "ok": bool(write_result.get("ok")) and after.get("ok", False),
        "page": page,
        "row": row,
        "column": column,
        "write_result": write_result,
        "wait_ms": wait_ms,
        "poll_ms": poll_ms,
        "polls": polls,
        "render_changed": before_preview.get("image_sha256") != after_preview.get("image_sha256"),
        "runtime_changed": before_runtime != after_runtime,
        "before": {
            "runtime_summary": before_runtime,
            "preview_meta": before_preview,
        },
        "after": {
            "runtime_summary": after_runtime,
            "preview_meta": after_preview,
        },
    })


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
    result = await _client().set_step(page, row, column, step)
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
    if result.get("status_code") == 404:
        return _compat_error(
            "This Companion build does not accept custom-variable writes at /api/custom-variable/{name}/value.",
            path=result["path"],
            status_code=result["status_code"],
        )
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
async def set_page_style_verified(page: int, buttons_json: str, wait_ms: int = 500, poll_ms: int = 100) -> str:
    """Batch-set styles on a page and return verified per-button outcomes plus an inventory diff."""
    _validate_page(page)
    _validate_poll_ms(wait_ms, "wait_ms")
    _validate_poll_ms(poll_ms, "poll_ms")
    if wait_ms and poll_ms == 0:
        raise ValueError("poll_ms must be > 0 when wait_ms is non-zero.")
    buttons = json.loads(buttons_json)
    if not isinstance(buttons, list):
        raise ValueError("buttons_json must be a JSON array.")

    client = _client()
    before_inventory = json.loads(await snapshot_page_inventory(page, include_empty=False))
    results: list[dict[str, Any]] = []
    for btn in buttons:
        if not isinstance(btn, dict) or "row" not in btn or "column" not in btn:
            raise ValueError("Each button must have row and column fields.")
        _validate_row_column(btn["row"], btn["column"])
        style = _normalize_style_payload(btn)
        verified = json.loads(await set_button_style_verified(
            page,
            btn["row"],
            btn["column"],
            text=str(style.get("text", "")),
            color=str(style.get("color", "")),
            bgcolor=str(style.get("bgcolor", "")),
            size=str(style.get("size", "")),
            wait_ms=wait_ms,
            poll_ms=poll_ms,
        ))
        results.append(verified)
    after_inventory = json.loads(await snapshot_page_inventory(page, include_empty=False))
    diff = _diff_inventory(before_inventory.get("buttons", []), after_inventory.get("buttons", []))
    return _json({
        "action": "set_page_style_verified",
        "page": page,
        "count": len(results),
        "wait_ms": wait_ms,
        "poll_ms": poll_ms,
        "results": results,
        "inventory_diff": diff,
    })


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def restore_page_style_from_inventory(inventory_json: str, wait_ms: int = 500, poll_ms: int = 100) -> str:
    """Restore button style state from a previously captured page inventory."""
    inventory = json.loads(inventory_json)
    if not isinstance(inventory, dict):
        raise ValueError("inventory_json must be a JSON object.")
    page = inventory.get("page")
    if not isinstance(page, int):
        raise ValueError("inventory_json must include an integer page.")
    entries = _restore_entries_from_inventory(inventory)
    return await set_page_style_verified(page, json.dumps(entries), wait_ms=wait_ms, poll_ms=poll_ms)


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
