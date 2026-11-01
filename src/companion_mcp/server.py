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
from pathlib import Path
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


def _validate_snapshot_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ValueError("snapshot name must be non-empty.")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if any(ch not in allowed for ch in normalized):
        raise ValueError("snapshot name may contain only letters, numbers, '.', '-', and '_'.")
    return normalized


def _snapshot_dir() -> Path:
    return Path(os.environ.get("COMPANION_SNAPSHOT_DIR", ".companion-snapshots"))


def _snapshot_path(name: str) -> Path:
    safe_name = _validate_snapshot_name(name)
    return _snapshot_dir() / f"{safe_name}.json"


def _preset_dir() -> Path:
    return Path(os.environ.get("COMPANION_PRESET_DIR", ".companion-presets"))


def _preset_path(name: str) -> Path:
    safe_name = _validate_snapshot_name(name)
    return _preset_dir() / f"{safe_name}.json"


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


def _filter_restore_entries(entries: list[dict[str, Any]], coords_json: str = "") -> list[dict[str, Any]]:
    if not coords_json:
        return entries
    coords = json.loads(coords_json)
    if not isinstance(coords, list):
        raise ValueError("coords_json must be a JSON array of {row, column} objects.")
    wanted: set[tuple[int, int]] = set()
    for item in coords:
        if not isinstance(item, dict):
            raise ValueError("Each coords_json entry must be an object.")
        row = item.get("row")
        column = item.get("column")
        if not isinstance(row, int) or not isinstance(column, int):
            raise ValueError("Each coords_json entry must include integer row and column values.")
        wanted.add((row, column))
    return [entry for entry in entries if (entry["row"], entry["column"]) in wanted]


def _write_snapshot_file(name: str, payload: dict[str, Any]) -> Path:
    path = _snapshot_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def _read_snapshot_file(name: str) -> dict[str, Any]:
    path = _snapshot_path(name)
    if not path.exists():
        raise ValueError(f"Snapshot {name!r} does not exist.")
    return json.loads(path.read_text())


def _list_named_json_files(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    items = []
    for path in sorted(directory.glob("*.json")):
        stat = path.stat()
        items.append({
            "name": path.stem,
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
        })
    return items


def _delete_named_json_file(path: Path, label: str, name: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"{label} {name!r} does not exist.")
    path.unlink()
    return {"ok": True, "name": name, "path": str(path), "deleted": True}


def _write_preset_file(name: str, payload: dict[str, Any]) -> Path:
    path = _preset_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def _read_preset_file(name: str) -> dict[str, Any]:
    path = _preset_path(name)
    if not path.exists():
        raise ValueError(f"Preset {name!r} does not exist.")
    return json.loads(path.read_text())


def _preset_entries_from_inventory(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    return _restore_entries_from_inventory(inventory)


def _offset_preset_entries(
    entries: list[dict[str, Any]],
    *,
    page: int,
    origin_row: int,
    origin_column: int,
) -> list[dict[str, Any]]:
    resolved = []
    for entry in entries:
        row = origin_row + int(entry["row"])
        column = origin_column + int(entry["column"])
        _validate_button_coords(page, row, column)
        resolved.append({
            "row": row,
            "column": column,
            **{k: v for k, v in entry.items() if k not in {"row", "column"}},
        })
    return resolved


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
async def save_page_inventory_snapshot(
    name: str,
    page: int,
    rows: int = 4,
    columns: int = 8,
    include_empty: bool = False,
) -> str:
    """Capture a page inventory snapshot and save it to a local checkpoint file."""
    inventory = json.loads(await snapshot_page_inventory(page, rows=rows, columns=columns, include_empty=include_empty))
    path = _write_snapshot_file(name, inventory)
    return _json({
        "ok": True,
        "name": _validate_snapshot_name(name),
        "path": str(path),
        "page": page,
        "button_count": inventory.get("button_count"),
    })


@mcp.tool()
@_handle_errors
async def load_page_inventory_snapshot(name: str) -> str:
    """Load a previously saved page inventory snapshot from disk."""
    inventory = _read_snapshot_file(name)
    return _json({
        "ok": True,
        "name": _validate_snapshot_name(name),
        "path": str(_snapshot_path(name)),
        "inventory": inventory,
    })


@mcp.tool()
@_handle_errors
async def list_page_inventory_snapshots() -> str:
    """List saved page inventory snapshot files."""
    return _json({
        "ok": True,
        "directory": str(_snapshot_dir()),
        "count": len(_list_named_json_files(_snapshot_dir())),
        "snapshots": _list_named_json_files(_snapshot_dir()),
    })


@mcp.tool()
@_handle_errors
async def delete_page_inventory_snapshot(name: str) -> str:
    """Delete a saved page inventory snapshot file."""
    return _json(_delete_named_json_file(_snapshot_path(name), "Snapshot", _validate_snapshot_name(name)))


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
async def preview_restore_page_style_from_snapshot(name: str, coords_json: str = "") -> str:
    """Preview a restore plan from a saved snapshot, optionally filtered to selected coordinates."""
    inventory = _read_snapshot_file(name)
    entries = _filter_restore_entries(_restore_entries_from_inventory(inventory), coords_json)
    return _json({
        "action": "preview_restore_page_style_from_snapshot",
        "name": _validate_snapshot_name(name),
        "page": inventory.get("page"),
        "count": len(entries),
        "writes_companion": False,
        "preview": entries,
    })


@mcp.tool()
@_handle_errors
async def save_page_style_preset(name: str, page: int, rows: int = 4, columns: int = 8, include_empty: bool = False) -> str:
    """Save the current page style state as a reusable preset file."""
    inventory = json.loads(await snapshot_page_inventory(page, rows=rows, columns=columns, include_empty=include_empty))
    entries = _preset_entries_from_inventory(inventory)
    payload = {
        "name": _validate_snapshot_name(name),
        "page": page,
        "rows": rows,
        "columns": columns,
        "include_empty": include_empty,
        "count": len(entries),
        "entries": entries,
    }
    path = _write_preset_file(name, payload)
    return _json({
        "ok": True,
        "name": _validate_snapshot_name(name),
        "path": str(path),
        "count": len(entries),
    })


@mcp.tool()
@_handle_errors
async def load_page_style_preset(name: str) -> str:
    """Load a saved page style preset file."""
    preset = _read_preset_file(name)
    return _json({
        "ok": True,
        "name": _validate_snapshot_name(name),
        "path": str(_preset_path(name)),
        "preset": preset,
    })


@mcp.tool()
@_handle_errors
async def list_page_style_presets() -> str:
    """List saved page style preset files."""
    return _json({
        "ok": True,
        "directory": str(_preset_dir()),
        "count": len(_list_named_json_files(_preset_dir())),
        "presets": _list_named_json_files(_preset_dir()),
    })


@mcp.tool()
@_handle_errors
async def delete_page_style_preset(name: str) -> str:
    """Delete a saved page style preset file."""
    return _json(_delete_named_json_file(_preset_path(name), "Preset", _validate_snapshot_name(name)))


@mcp.tool()
@_handle_errors
async def preview_apply_page_style_preset(
    name: str,
    page: int = 0,
    origin_row: int = 0,
    origin_column: int = 0,
) -> str:
    """Preview applying a saved preset onto a page, optionally with row/column offsets."""
    preset = _read_preset_file(name)
    target_page = page or preset.get("page")
    if not isinstance(target_page, int):
        raise ValueError("Preset does not contain a valid page and no page override was provided.")
    _validate_page(target_page)
    _validate_row_column(origin_row, origin_column)
    entries = preset.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Preset file is missing entries.")
    resolved = _offset_preset_entries(entries, page=target_page, origin_row=origin_row, origin_column=origin_column)
    return _json({
        "action": "preview_apply_page_style_preset",
        "name": _validate_snapshot_name(name),
        "page": target_page,
        "origin_row": origin_row,
        "origin_column": origin_column,
        "count": len(resolved),
        "writes_companion": False,
        "preview": resolved,
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
async def restore_selected_page_style_from_inventory(
    inventory_json: str,
    coords_json: str,
    wait_ms: int = 500,
    poll_ms: int = 100,
) -> str:
    """Restore only selected coordinates from a captured page inventory."""
    inventory = json.loads(inventory_json)
    if not isinstance(inventory, dict):
        raise ValueError("inventory_json must be a JSON object.")
    page = inventory.get("page")
    if not isinstance(page, int):
        raise ValueError("inventory_json must include an integer page.")
    entries = _filter_restore_entries(_restore_entries_from_inventory(inventory), coords_json)
    return await set_page_style_verified(page, json.dumps(entries), wait_ms=wait_ms, poll_ms=poll_ms)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def restore_page_style_from_snapshot(name: str, wait_ms: int = 500, poll_ms: int = 100, coords_json: str = "") -> str:
    """Restore button style state from a saved snapshot file, optionally filtered to selected coordinates."""
    inventory = _read_snapshot_file(name)
    page = inventory.get("page")
    if not isinstance(page, int):
        raise ValueError("snapshot inventory must include an integer page.")
    entries = _filter_restore_entries(_restore_entries_from_inventory(inventory), coords_json)
    result = json.loads(await set_page_style_verified(page, json.dumps(entries), wait_ms=wait_ms, poll_ms=poll_ms))
    result["snapshot_name"] = _validate_snapshot_name(name)
    result["snapshot_path"] = str(_snapshot_path(name))
    return _json(result)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def apply_page_style_transaction(
    snapshot_name: str,
    page: int,
    buttons_json: str,
    rows: int = 4,
    columns: int = 8,
    include_empty: bool = False,
    wait_ms: int = 500,
    poll_ms: int = 100,
) -> str:
    """Save a rollback checkpoint, apply verified page style changes, and return the checkpoint metadata."""
    snapshot_result = json.loads(await save_page_inventory_snapshot(
        snapshot_name,
        page,
        rows=rows,
        columns=columns,
        include_empty=include_empty,
    ))
    apply_result = json.loads(await set_page_style_verified(page, buttons_json, wait_ms=wait_ms, poll_ms=poll_ms))
    return _json({
        "ok": apply_result.get("count", 0) >= 0,
        "snapshot": snapshot_result,
        "apply_result": apply_result,
        "rollback_hint": {
            "tool": "restore_page_style_from_snapshot",
            "snapshot_name": _validate_snapshot_name(snapshot_name),
        },
    })


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def rollback_page_style_transaction(snapshot_name: str, wait_ms: int = 500, poll_ms: int = 100, coords_json: str = "") -> str:
    """Rollback page styles from a saved transaction snapshot."""
    return await restore_page_style_from_snapshot(snapshot_name, wait_ms=wait_ms, poll_ms=poll_ms, coords_json=coords_json)


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def apply_page_style_preset(
    name: str,
    page: int = 0,
    origin_row: int = 0,
    origin_column: int = 0,
    wait_ms: int = 500,
    poll_ms: int = 100,
) -> str:
    """Apply a saved page style preset with optional page override and coordinate offsets."""
    preset = _read_preset_file(name)
    target_page = page or preset.get("page")
    if not isinstance(target_page, int):
        raise ValueError("Preset does not contain a valid page and no page override was provided.")
    _validate_page(target_page)
    _validate_row_column(origin_row, origin_column)
    entries = preset.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Preset file is missing entries.")
    resolved = _offset_preset_entries(entries, page=target_page, origin_row=origin_row, origin_column=origin_column)
    result = json.loads(await set_page_style_verified(target_page, json.dumps(resolved), wait_ms=wait_ms, poll_ms=poll_ms))
    result["preset_name"] = _validate_snapshot_name(name)
    result["preset_path"] = str(_preset_path(name))
    result["origin_row"] = origin_row
    result["origin_column"] = origin_column
    return _json(result)


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
# Native Control (connections, definitions, pages, buttons, entities, import/export)
# ============================================================

_SET_IDS = ("down", "up", "rotate_left", "rotate_right")
_BUTTON_TYPES = ("button-layered", "pageup", "pagedown", "pagenum")
_TRANSFER_OPS = ("copy", "move", "swap")


def _write_failed(result: dict[str, Any]) -> bool:
    """Companion mutations often 'succeed' at the transport level but return null/false/'fail'."""
    if not result.get("ok"):
        return True
    body = result.get("body")
    return body is False or body == "fail"


def _entity_location(location: str, step: str) -> Any:
    if location == "feedbacks":
        return "feedbacks"
    if location in _SET_IDS:
        return {"stepId": str(step), "setId": location}
    try:
        return {"stepId": str(step), "setId": int(location)}  # duration-group set ids are numeric
    except ValueError:
        raise ValueError(f"location must be one of {_SET_IDS + ('feedbacks',)} or a numeric duration set id.") from None


def _page_export_dir() -> Path:
    return _snapshot_dir() / "page-exports"


def _write_page_export(label: str, page: int, payload: dict[str, Any]) -> Path:
    from datetime import datetime

    directory = _page_export_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"{stamp}-page{page}-{_validate_snapshot_name(label)}.companionconfig"
    path.write_text(json.dumps(payload, indent=1))
    return path


async def _backup_page(client: CompanionClient, page: int, label: str) -> dict[str, Any]:
    exported = await client.export_page_config(page)
    if not exported.get("ok"):
        return {"ok": False, "error": "Could not export page for backup; refusing destructive change.", "detail": exported}
    path = _write_page_export(label, page, exported["body"])
    return {"ok": True, "path": str(path.resolve())}


async def _page_count(client: CompanionClient) -> int:
    snap = await client.get_pages_snapshot()
    order = (snap.get("body") or {}).get("order") if snap.get("ok") else None
    if not isinstance(order, list):
        raise ValueError("Could not read Companion page list.")
    return len(order)


async def _connections_map(client: CompanionClient) -> dict[str, dict[str, Any]]:
    result = await client.list_connections()
    if not result.get("ok"):
        raise ValueError(f"Could not list connections: {result.get('error')}")
    body = result.get("body")
    if isinstance(body, list):
        body = next((item for item in body if isinstance(item, dict) and item.get("type") == "init"), {})
    info = (body or {}).get("info") or {}
    return {cid: c for cid, c in info.items() if isinstance(c, dict) and c.get("moduleType", "connection") == "connection"}


def _resolve_connection(connections: dict[str, dict[str, Any]], ref: str) -> str:
    if ref == "internal":
        return "internal"
    if ref in connections:
        return ref
    matches = [cid for cid, c in connections.items() if str(c.get("label", "")).lower() == ref.lower()]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"Unknown connection {ref!r}. Known labels: {sorted(c.get('label') for c in connections.values())}")


def _compact_option(opt: dict[str, Any]) -> dict[str, Any]:
    out = {k: opt[k] for k in ("id", "type", "label", "default", "min", "max") if k in opt}
    if isinstance(opt.get("choices"), list):
        out["choices"] = [c.get("id") for c in opt["choices"][:50] if isinstance(c, dict)]
    return out


async def _control_entities(client: CompanionClient, control_id: str) -> dict[str, Any]:
    snap = await client.get_control_snapshot(control_id)
    body = snap.get("body") or {}
    return (body.get("config") or {}) if isinstance(body, dict) else {}


def _find_entity(config: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    stack: list[Any] = [config.get("feedbacks"), config.get("steps")]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("id") == entity_id and "definitionId" in node:
                return node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _summarize_entities(config: dict[str, Any]) -> dict[str, Any]:
    def brief(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": e.get("id"),
            "connectionId": e.get("connectionId"),
            "definitionId": e.get("definitionId"),
            "options": {k: (v.get("value") if isinstance(v, dict) else v) for k, v in (e.get("options") or {}).items()},
            "disabled": e.get("disabled", False),
        }

    steps = {}
    for step_id, step in (config.get("steps") or {}).items():
        steps[step_id] = {
            set_id: [brief(a) for a in actions or []] for set_id, actions in (step.get("action_sets") or {}).items()
        }
    return {
        "type": config.get("type"),
        "steps": steps,
        "feedbacks": [brief(f) for f in config.get("feedbacks") or []],
    }


async def _require_control(client: CompanionClient, page: int, row: int, column: int) -> str:
    _validate_button_coords(page, row, column)
    control_id = await client.get_control_id_at(page, row, column)
    if not control_id:
        raise ValueError(f"No button at page {page} row {row} column {column}. Use create_button first.")
    return control_id


@mcp.tool()
@_handle_errors
async def list_connections() -> str:
    """List Companion connections (id, label, module, version, enabled)."""
    connections = await _connections_map(_client())
    items = [
        {
            "id": cid,
            "label": c.get("label"),
            "moduleId": c.get("moduleId"),
            "moduleVersionId": c.get("moduleVersionId"),
            "enabled": c.get("enabled"),
        }
        for cid, c in sorted(connections.items(), key=lambda kv: kv[1].get("sortOrder", 0))
    ]
    return _json({"ok": True, "count": len(items), "connections": items})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_connection_enabled(connection: str, enabled: bool) -> str:
    """Enable or disable a connection (by id or label). Enabling starts network traffic to that device."""
    client = _client()
    connection_id = _resolve_connection(await _connections_map(client), connection)
    if connection_id == "internal":
        raise ValueError("The internal connection cannot be toggled.")
    result = await client.set_connection_enabled(connection_id, enabled)
    after = (await _connections_map(client)).get(connection_id, {})
    verified = after.get("enabled") == enabled
    return _json({"ok": bool(result.get("ok")) and verified, "connection_id": connection_id, "label": after.get("label"),
                  "enabled": after.get("enabled"), "verified": verified})


@mcp.tool()
@_handle_errors
async def list_entity_definitions(connection: str, entity_type: str = "action", query: str = "", include_options: bool = True) -> str:
    """List action or feedback definitions for a connection (id or label, or 'internal').

    Definitions are only published by RUNNING connections; a disabled connection returns none.
    query filters by id/label substring.
    """
    if entity_type not in ("action", "feedback"):
        raise ValueError("entity_type must be 'action' or 'feedback'.")
    client = _client()
    connections = await _connections_map(client)
    connection_id = _resolve_connection(connections, connection)
    result = await client.get_entity_definitions(entity_type)
    if not result.get("ok"):
        return _error("Could not read definitions.", detail=result.get("error"))
    body = result.get("body") or {}
    defs = ((body.get("definitions") or {}) if isinstance(body, dict) else {}).get(connection_id)
    if not defs:
        enabled = connections.get(connection_id, {}).get("enabled")
        return _error(
            f"No {entity_type} definitions published for {connection!r}.",
            blocked=True,
            connection_enabled=enabled,
            hint="Connection must be enabled and running to publish definitions." if not enabled else "Module may still be starting.",
        )
    q = query.lower()
    items = []
    for def_id, d in defs.items():
        if q and q not in def_id.lower() and q not in str(d.get("label", "")).lower():
            continue
        item = {"id": def_id, "label": d.get("label")}
        if entity_type == "feedback":
            item["feedbackType"] = d.get("feedbackType")
        if include_options:
            item["options"] = [_compact_option(o) for o in d.get("options") or [] if isinstance(o, dict)]
        items.append(item)
    return _json({"ok": True, "connection_id": connection_id, "entity_type": entity_type, "count": len(items), "definitions": items})


@mcp.tool()
@_handle_errors
async def list_pages() -> str:
    """List pages with number, id, name and number of buttons."""
    snap = await _client().get_pages_snapshot()
    if not snap.get("ok"):
        return _error("Could not read pages.", detail=snap.get("error"))
    body = snap.get("body") or {}
    pages = []
    for idx, page_id in enumerate(body.get("order") or [], start=1):
        info = (body.get("pages") or {}).get(page_id) or {}
        count = sum(len(cols) for cols in (info.get("controls") or {}).values() if isinstance(cols, dict))
        pages.append({"page": idx, "id": page_id, "name": info.get("name"), "buttons": count})
    return _json({"ok": True, "count": len(pages), "pages": pages})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def insert_page(page_number: int, name: str = "New Page") -> str:
    """Insert a new page at page_number (existing pages shift up). Use page count + 1 to append."""
    client = _client()
    count = await _page_count(client)
    if page_number < 1 or page_number > count + 1:
        raise ValueError(f"page_number must be between 1 and {count + 1}.")
    result = await client.insert_page(page_number, name)
    return _json({"ok": not _write_failed(result), "page": page_number, "name": name, "result": result.get("body")})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def rename_page(page: int, name: str) -> str:
    """Rename a page."""
    _validate_page(page)
    result = await _client().set_page_name(page, name)
    return _json({"ok": not _write_failed(result), "page": page, "name": name})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def clear_page(page: int, confirm: bool = False) -> str:
    """Delete every button on a page (nav buttons are recreated). Requires confirm=true; exports a backup first."""
    _validate_page(page)
    if not confirm:
        raise ValueError("clear_page deletes all buttons on the page; call again with confirm=true.")
    client = _client()
    backup = await _backup_page(client, page, "before-clear")
    if not backup["ok"]:
        return _json(backup)
    result = await client.clear_page(page)
    return _json({"ok": not _write_failed(result), "page": page, "backup": backup["path"]})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def remove_page(page: int, confirm: bool = False) -> str:
    """Delete a page and its buttons (later pages shift down). Requires confirm=true; exports a backup first."""
    _validate_page(page)
    if not confirm:
        raise ValueError("remove_page deletes the page and all its buttons; call again with confirm=true.")
    client = _client()
    backup = await _backup_page(client, page, "before-remove")
    if not backup["ok"]:
        return _json(backup)
    result = await client.remove_page(page)
    return _json({"ok": not _write_failed(result), "page": page, "backup": backup["path"], "result": result.get("body")})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def create_button(page: int, row: int, column: int, button_type: str = "button-layered", overwrite: bool = False) -> str:
    """Create an empty button (or nav button: pageup/pagedown/pagenum). Refuses occupied slots unless overwrite=true."""
    _validate_button_coords(page, row, column)
    if button_type not in _BUTTON_TYPES:
        raise ValueError(f"button_type must be one of {_BUTTON_TYPES}.")
    client = _client()
    existing = await client.get_control_id_at(page, row, column)
    if existing and not overwrite:
        raise ValueError(f"Slot page {page} row {row} column {column} already has a button ({existing}); pass overwrite=true to replace it.")
    await client.reset_controls([{"pageNumber": page, "row": row, "column": column}], button_type)
    control_id = await client.get_control_id_at(page, row, column)
    return _json({"ok": bool(control_id), "control_id": control_id, "type": button_type, "replaced": existing})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def delete_button(page: int, row: int, column: int, confirm: bool = False) -> str:
    """Delete the button at a location (actions, feedbacks, style). Requires confirm=true."""
    _validate_button_coords(page, row, column)
    if not confirm:
        raise ValueError("delete_button removes the button entirely; call again with confirm=true.")
    client = _client()
    existing = await client.get_control_id_at(page, row, column)
    if not existing:
        return _json({"ok": True, "deleted": None, "note": "Slot was already empty."})
    await client.reset_controls([{"pageNumber": page, "row": row, "column": column}], None)
    remaining = await client.get_control_id_at(page, row, column)
    return _json({"ok": remaining is None, "deleted": existing})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def transfer_buttons(operation: str, pairs_json: str) -> str:
    """Copy, move or swap whole buttons (actions + feedbacks + style).

    pairs_json: JSON array of {"from": {page,row,column}, "to": {page,row,column}}.
    copy/move overwrite the destination.
    """
    if operation not in _TRANSFER_OPS:
        raise ValueError(f"operation must be one of {_TRANSFER_OPS}.")
    raw = json.loads(pairs_json)
    if not isinstance(raw, list) or not raw:
        raise ValueError("pairs_json must be a non-empty JSON array.")
    pairs = []
    for item in raw:
        src, dst = item.get("from") or {}, item.get("to") or {}
        for loc in (src, dst):
            _validate_button_coords(int(loc.get("page", 0)), int(loc.get("row", -1)), int(loc.get("column", -1)))
        pairs.append({
            "fromLocation": {"pageNumber": int(src["page"]), "row": int(src["row"]), "column": int(src["column"])},
            "toLocation": {"pageNumber": int(dst["page"]), "row": int(dst["row"]), "column": int(dst["column"])},
        })
    result = await _client().grid_batch_transfer(operation, pairs)
    return _json({"ok": not _write_failed(result), "operation": operation, "count": len(pairs), "result": result.get("body")})


@mcp.tool()
@_handle_errors
async def list_button_entities(page: int, row: int, column: int) -> str:
    """List a button's actions (per step and set) and feedbacks with ids and option values."""
    client = _client()
    control_id = await _require_control(client, page, row, column)
    config = await _control_entities(client, control_id)
    return _json({"ok": True, "control_id": control_id, **_summarize_entities(config)})


async def _add_entity(
    page: int, row: int, column: int, connection: str, definition_id: str, options_json: str,
    entity_type: str, location: Any,
) -> str:
    options = json.loads(options_json or "{}")
    if not isinstance(options, dict):
        raise ValueError("options_json must be a JSON object of option id -> value.")
    client = _client()
    control_id = await _require_control(client, page, row, column)
    connection_id = _resolve_connection(await _connections_map(client), connection)
    added = await client.entity_add(control_id, location, connection_id, entity_type, definition_id)
    entity_id = added.get("body")
    if not added.get("ok") or not entity_id:
        return _error(
            f"Companion refused to add {entity_type} {definition_id!r} on {connection!r}.",
            detail=added.get("error"),
            hint="Check the definition id with list_entity_definitions; the connection must be enabled for its definitions to exist.",
        )
    option_results = {}
    for key, value in options.items():
        res = await client.entity_set_option(control_id, location, entity_id, key, value)
        option_results[key] = not _write_failed(res)
    entity = _find_entity(await _control_entities(client, control_id), entity_id)
    stored = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in ((entity or {}).get("options") or {}).items()}
    mismatched = [k for k, v in options.items() if stored.get(k) != v]
    return _json({
        "ok": entity is not None and not mismatched and all(option_results.values()),
        "control_id": control_id,
        "entity_id": entity_id,
        "connection_id": connection_id,
        "definition_id": definition_id,
        "location": location,
        "stored_options": stored,
        "mismatched_options": mismatched,
    })


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def add_button_action(
    page: int, row: int, column: int, connection: str, definition_id: str,
    options_json: str = "{}", location: str = "down", step: str = "0",
) -> str:
    """Add an action to a button and set its options, then verify by re-reading the button.

    connection: id or label ('internal' for Companion built-ins). location: down|up|rotate_left|rotate_right.
    options_json: {"optionId": value, ...} — plain values, not {value,isExpression} wrappers.
    """
    return await _add_entity(page, row, column, connection, definition_id, options_json, "action",
                             _entity_location(location, step))


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def add_button_feedback(
    page: int, row: int, column: int, connection: str, definition_id: str, options_json: str = "{}",
) -> str:
    """Add a feedback to a button and set its options, then verify. Style overrides use Companion's defaults."""
    return await _add_entity(page, row, column, connection, definition_id, options_json, "feedback", "feedbacks")


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_button_entity_option(
    page: int, row: int, column: int, entity_id: str, key: str, value_json: str,
    location: str = "down", step: str = "0", is_expression: bool = False,
) -> str:
    """Set one option on an existing action/feedback (location 'feedbacks' for feedbacks). value_json is JSON (e.g. 5, "abc", true)."""
    client = _client()
    control_id = await _require_control(client, page, row, column)
    loc = _entity_location(location, step)
    value = json.loads(value_json)
    result = await client.entity_set_option(control_id, loc, entity_id, key, value, is_expression)
    entity = _find_entity(await _control_entities(client, control_id), entity_id)
    stored = ((entity or {}).get("options") or {}).get(key)
    stored_value = stored.get("value") if isinstance(stored, dict) else stored
    return _json({"ok": not _write_failed(result) and stored_value == value, "entity_id": entity_id, "key": key, "stored": stored_value})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def remove_button_entity(page: int, row: int, column: int, entity_id: str, location: str = "down", step: str = "0") -> str:
    """Remove an action/feedback from a button by entity id (location 'feedbacks' for feedbacks)."""
    client = _client()
    control_id = await _require_control(client, page, row, column)
    result = await client.entity_remove(control_id, _entity_location(location, step), entity_id)
    still_there = _find_entity(await _control_entities(client, control_id), entity_id) is not None
    return _json({"ok": not _write_failed(result) and not still_there, "entity_id": entity_id})


@mcp.tool()
@_handle_errors
async def export_page_config(page: int, save: bool = True) -> str:
    """Export a page in Companion's native format (buttons + actions + feedbacks + connections).

    save=true writes a .companionconfig file (importable via import_page_config or the Companion UI) and returns its path.
    """
    _validate_page(page)
    exported = await _client().export_page_config(page)
    if not exported.get("ok"):
        return _error("Export failed.", detail=exported)
    body = exported["body"]
    out: dict[str, Any] = {"ok": True, "page": page, "name": (body.get("page") or {}).get("name"),
                           "connections": [c.get("label") for c in (body.get("instances") or {}).values()]}
    if save:
        out["path"] = str(_write_page_export("export", page, body).resolve())
    else:
        out["config"] = body
    return _json(out)


def _auto_remap(
    import_connections: dict[str, Any], existing: dict[str, dict[str, Any]], overrides: dict[str, str], allow_create: bool
) -> dict[str, str]:
    remap: dict[str, str] = {}
    for src_id, info in import_connections.items():
        if not info:
            continue
        if src_id in overrides:
            remap[src_id] = overrides[src_id]
            continue
        same_module = [cid for cid, c in existing.items() if c.get("moduleId") == info.get("moduleId")]
        by_label = [cid for cid in same_module if existing[cid].get("label") == info.get("label")]
        if src_id in existing and existing[src_id].get("moduleId") == info.get("moduleId"):
            remap[src_id] = src_id
        elif by_label:
            remap[src_id] = by_label[0]
        elif same_module:
            remap[src_id] = same_module[0]
        else:
            remap[src_id] = "" if allow_create else "_ignore"
    return remap


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def import_page_config(
    file_path: str,
    target_page: int,
    source_page: int = 1,
    remap_json: str = "",
    allow_create_connections: bool = False,
    confirm_overwrite: bool = False,
) -> str:
    """Import a page from a Companion export (.companionconfig / JSON) into target_page, with full actions/feedbacks.

    target_page=-1 appends a new page. Importing onto an existing page REPLACES it: requires confirm_overwrite=true and
    a backup export of that page is written first. Connections are matched to existing ones by id, then module+label,
    then module. Unmatched connections are ignored unless allow_create_connections=true, in which case they are created
    DISABLED. remap_json optionally overrides: {"importConnectionId": "existingConnectionId" | "_ignore"}.
    """
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    raw = path.read_bytes()
    try:
        config = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Only JSON exports are supported (export with format=json).") from None
    if config.get("type") not in ("page", "full"):
        raise ValueError("File is not a Companion page/full export.")
    if config.get("type") == "full" and str(source_page) not in (config.get("pages") or {}):
        raise ValueError(f"source_page {source_page} not present in full export.")
    # Never let an import switch on device traffic: created connections start disabled.
    for inst in (config.get("instances") or {}).values():
        if isinstance(inst, dict):
            inst["enabled"] = False
    data = json.dumps(config).encode("utf-8")

    overrides = json.loads(remap_json) if remap_json else {}
    if not isinstance(overrides, dict):
        raise ValueError("remap_json must be a JSON object.")

    client = _client()
    count = await _page_count(client)
    backup = None
    if target_page != -1:
        if target_page < 1 or target_page > count:
            raise ValueError(f"target_page must be -1 or between 1 and {count}.")
        if not confirm_overwrite:
            raise ValueError(f"Importing replaces everything on page {target_page}; call again with confirm_overwrite=true.")
        backup = await _backup_page(client, target_page, "before-import")
        if not backup["ok"]:
            return _json(backup)

    existing = await _connections_map(client)
    result = await client.import_page_config(
        data,
        filename=path.name,
        source_page=source_page,
        target_page=target_page,
        remap_fn=lambda conns: _auto_remap(conns, existing, overrides, allow_create_connections),
    )
    after = await _connections_map(client)
    created = [{"id": cid, "label": c.get("label"), "enabled": c.get("enabled")} for cid, c in after.items() if cid not in existing]
    return _json({
        **result,
        "target_page": target_page if target_page != -1 else count + 1,
        "backup": backup["path"] if backup else None,
        "connections_created": created,
        "ignored_connections": [k for k, v in (result.get("remap_requested") or {}).items() if v == "_ignore"],
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
