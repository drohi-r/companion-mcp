import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_get_server_config():
    from companion_mcp.server import get_server_config
    result = json.loads(await get_server_config())
    assert result["host"] == "127.0.0.1"
    assert result["port"] == 8000
    assert result["timeout_s"] == 10.0
    assert result["write_enabled"] is True
    assert "base_url" in result


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_health_check(mock_client_factory):
    from companion_mcp.server import health_check
    fake = MagicMock()
    fake.request = AsyncMock(return_value={"ok": True, "status_code": 200, "content_type": "application/json", "body": []})
    fake.get_app_info = AsyncMock(return_value={"ok": True, "body": {"appVersion": "4.2.6"}})
    mock_client_factory.return_value = fake

    result = json.loads(await health_check())
    assert result["ok"] is True
    assert result["probe_path"] == "/"
    assert result["app_info"]["body"]["appVersion"] == "4.2.6"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_list_surfaces(mock_client_factory):
    from companion_mcp.server import list_surfaces
    fake = MagicMock()
    fake.list_surfaces = AsyncMock(return_value={"ok": True, "body": [{"type": "init", "info": {"streamdeck-xl": {}}}]})
    mock_client_factory.return_value = fake

    result = json.loads(await list_surfaces())
    assert result["ok"] is True
    assert "streamdeck-xl" in result["body"][0]["info"]


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_list_surfaces_returns_compat_error_on_404(mock_client_factory):
    from companion_mcp.server import list_surfaces
    fake = MagicMock()
    fake.list_surfaces = AsyncMock(return_value={"ok": False, "error_code": "NOT_FOUND", "path": "surfaces.watchSurfaces"})
    mock_client_factory.return_value = fake

    result = json.loads(await list_surfaces())
    assert result["blocked"] is True
    assert result["compatibility"] == "current_companion_version"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_get_button_info(mock_client_factory):
    from companion_mcp.server import get_button_info
    fake = MagicMock()
    fake.get_button_info_current = AsyncMock(return_value={
        "ok": True,
        "body": {
            "control": {"config": {"text": "GO"}},
            "style_meta": {"text": "GO", "color": 1, "bgcolor": 2},
            "feedback_meta": {"count": 1, "active_style_feedbacks": 1, "style_may_be_feedback_controlled": True},
            "preview_meta": {"image_sha256": "abc123", "image_bytes": 42},
        },
    })
    mock_client_factory.return_value = fake

    result = json.loads(await get_button_info(1, 0, 0))
    assert result["ok"] is True
    assert result["body"]["control"]["config"]["text"] == "GO"
    assert result["body"]["style_meta"]["text"] == "GO"
    assert result["body"]["feedback_meta"]["style_may_be_feedback_controlled"] is True
    assert result["body"]["preview_meta"]["image_sha256"] == "abc123"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_get_button_info_returns_compat_error_on_404(mock_client_factory):
    from companion_mcp.server import get_button_info
    fake = MagicMock()
    fake.get_button_info_current = AsyncMock(return_value={"ok": False, "error_code": "NOT_FOUND", "path": "controls.watchControl"})
    mock_client_factory.return_value = fake

    result = json.loads(await get_button_info(1, 0, 0))
    assert result["blocked"] is True
    assert result["compatibility"] == "current_companion_version"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_verify_button_render_change(mock_client_factory):
    from companion_mcp.server import verify_button_render_change
    fake = MagicMock()
    fake.get_button_info_current = AsyncMock(return_value={
        "ok": True,
        "body": {"preview_meta": {"image_sha256": "newhash", "image_bytes": 123}},
    })
    mock_client_factory.return_value = fake

    result = json.loads(await verify_button_render_change(1, 0, 0, "oldhash"))
    assert result["changed"] is True
    assert result["current_sha256"] == "newhash"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_button_style_verified(mock_client_factory):
    from companion_mcp.server import set_button_style_verified
    fake = MagicMock()
    fake.get_button_info_current = AsyncMock(side_effect=[
        {
            "ok": True,
            "body": {
                "control": {"config": {"type": "button"}},
                "style_meta": {"text": "OLD", "color": 1, "bgcolor": 2},
                "feedback_meta": {"count": 0, "active_style_feedbacks": 0, "style_may_be_feedback_controlled": False},
                "preview_meta": {"image_sha256": "before"},
            },
        },
        {
            "ok": True,
            "body": {
                "control": {"config": {"type": "button"}},
                "style_meta": {"text": "NEW", "color": 3, "bgcolor": 4},
                "feedback_meta": {"count": 2, "active_style_feedbacks": 1, "style_may_be_feedback_controlled": True},
                "preview_meta": {"image_sha256": "after"},
            },
        },
    ])
    fake.set_style = AsyncMock(return_value={"ok": True, "status_code": 200})
    mock_client_factory.return_value = fake

    result = json.loads(await set_button_style_verified(1, 0, 1, text="NEW", color="ffffff", bgcolor="0057ff"))
    assert result["ok"] is True
    assert result["render_changed"] is True
    assert result["style_changed"] is True
    assert result["control_type"] == "button"
    assert result["style_may_be_feedback_controlled"] is True
    assert result["feedback_summary"]["active_style_feedbacks"] == 1
    fake.set_style.assert_awaited_once_with(1, 0, 1, text="NEW", color="ffffff", bgcolor="0057ff")


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_get_page_grid(mock_client_factory):
    from companion_mcp.server import get_page_grid
    fake = MagicMock()
    fake.get_page_grid_current = AsyncMock(return_value={
        "ok": True,
        "body": {
            "page": 1,
            "rows": 1,
            "columns": 2,
            "include_empty": False,
            "count": 1,
            "buttons": [{"page": 1, "row": 0, "column": 0, "control": {"config": {"text": "GO"}}}],
        },
    })
    mock_client_factory.return_value = fake

    result = json.loads(await get_page_grid(1, rows=1, columns=2))
    assert result["count"] == 1
    assert result["buttons"][0]["control"]["config"]["text"] == "GO"


@pytest.mark.asyncio
@patch("companion_mcp.server.get_page_grid")
async def test_export_page_layout(mock_get_page_grid):
    from companion_mcp.server import export_page_layout
    mock_get_page_grid.return_value = json.dumps({
        "buttons": [{"row": 0, "column": 0, "body": {"text": "GO"}}],
    })
    result = json.loads(await export_page_layout(1, rows=1, columns=1))
    assert result["button_count"] == 1
    assert result["layout"][0]["body"]["text"] == "GO"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_snapshot_custom_variables(mock_client_factory):
    from companion_mcp.server import snapshot_custom_variables
    fake = MagicMock()
    fake.get_custom_variable_current = AsyncMock(side_effect=[
        {"ok": True, "body": {"name": "show_name", "value": "ShowA", "exists": True}},
        {"ok": True, "body": {"name": "bpm", "value": "128", "exists": True}},
    ])
    mock_client_factory.return_value = fake
    result = json.loads(await snapshot_custom_variables(json.dumps(["show_name", "bpm"])))
    assert result["count"] == 2
    assert result["variables"][0]["name"] == "show_name"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_press_button(mock_client_factory):
    from companion_mcp.server import press_button
    fake = MagicMock()
    fake.button_action = AsyncMock(return_value={"ok": True, "path": "/api/location/1/0/0/press"})
    mock_client_factory.return_value = fake

    result = json.loads(await press_button(1, 0, 0))
    assert result["ok"] is True
    fake.button_action.assert_awaited_once_with(1, 0, 0, "press")


@pytest.mark.asyncio
async def test_write_tool_blocked_when_writes_disabled(monkeypatch):
    from companion_mcp.server import press_button
    monkeypatch.setenv("COMPANION_WRITE_ENABLED", "0")
    result = json.loads(await press_button(1, 0, 0))
    assert result["blocked"] is True
    assert "write operations are disabled" in result["error"]


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_button_text(mock_client_factory):
    from companion_mcp.server import set_button_text
    fake = MagicMock()
    fake.set_style = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    result = json.loads(await set_button_text(1, 0, 0, "GO"))
    assert result["ok"] is True
    fake.set_style.assert_awaited_once_with(1, 0, 0, text="GO")


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_custom_variable(mock_client_factory):
    from companion_mcp.server import set_custom_variable
    fake = MagicMock()
    fake.set_variable = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    result = json.loads(await set_custom_variable("show_name", "Nobo Winter"))
    assert result["ok"] is True


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_custom_variable_returns_compat_error_on_404(mock_client_factory):
    from companion_mcp.server import set_custom_variable
    fake = MagicMock()
    fake.set_variable = AsyncMock(return_value={"ok": False, "status_code": 404, "path": "/api/custom-variable/show_name/value"})
    mock_client_factory.return_value = fake

    result = json.loads(await set_custom_variable("show_name", "Nobo Winter"))
    assert result["blocked"] is True
    assert result["compatibility"] == "current_companion_version"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_press_button_sequence(mock_client_factory):
    from companion_mcp.server import press_button_sequence
    fake = MagicMock()
    fake.button_action = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    buttons = json.dumps([{"page": 1, "row": 0, "column": 0}, {"page": 1, "row": 0, "column": 1}])
    result = json.loads(await press_button_sequence(buttons, delay_ms=10))
    assert result["count"] == 2
    assert fake.button_action.await_count == 2


@pytest.mark.asyncio
async def test_press_button_sequence_rejects_non_array():
    from companion_mcp.server import press_button_sequence
    result = json.loads(await press_button_sequence('{"bad": true}'))
    assert result["blocked"] is True
    assert "JSON array" in result["error"]


@pytest.mark.asyncio
async def test_press_button_rejects_negative_coordinate():
    from companion_mcp.server import press_button
    result = json.loads(await press_button(1, -1, 0))
    assert result["blocked"] is True
    assert "row must be >= 0" in result["error"]


@pytest.mark.asyncio
async def test_set_button_color_rejects_bad_hex():
    from companion_mcp.server import set_button_color
    result = json.loads(await set_button_color(1, 0, 0, color="red"))
    assert result["blocked"] is True
    assert "6-digit hex color" in result["error"]


@pytest.mark.asyncio
async def test_press_button_sequence_rejects_negative_delay():
    from companion_mcp.server import press_button_sequence
    result = json.loads(await press_button_sequence("[]", delay_ms=-1))
    assert result["blocked"] is True
    assert "delay_ms must be >= 0" in result["error"]


@pytest.mark.asyncio
async def test_preview_page_style():
    from companion_mcp.server import preview_page_style
    result = json.loads(
        await preview_page_style(
            1,
            json.dumps([{"row": 0, "column": 0, "text": "GO", "color": "#ff0000"}]),
        )
    )
    assert result["writes_companion"] is False
    assert result["preview"][0]["style"]["color"] == "ff0000"


@pytest.mark.asyncio
async def test_preview_label_button_grid():
    from companion_mcp.server import preview_label_button_grid
    result = json.loads(await preview_label_button_grid(1, json.dumps(["GO", "", "STOP"]), columns=2))
    assert result["writes_companion"] is False
    assert result["labeled"] == 2
    assert result["preview"][1]["row"] == 1
    assert result["preview"][1]["column"] == 0


@pytest.mark.asyncio
async def test_preview_button_template():
    from companion_mcp.server import preview_button_template
    template = json.dumps([
        {"row": 0, "column": 0, "text": "GO", "bgcolor": "#00ff00"},
        {"row": 0, "column": 1, "text": "STOP"},
    ])
    result = json.loads(await preview_button_template(2, template, origin_row=1, origin_column=2))
    assert result["writes_companion"] is False
    assert result["preview"][0]["row"] == 1
    assert result["preview"][0]["column"] == 2
    assert result["preview"][0]["style"]["bgcolor"] == "00ff00"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_apply_button_template(mock_client_factory):
    from companion_mcp.server import apply_button_template
    fake = MagicMock()
    fake.set_style = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake
    template = json.dumps([{"row": 0, "column": 0, "text": "GO"}])
    result = json.loads(await apply_button_template(1, template))
    assert result["count"] == 1
    fake.set_style.assert_awaited_once_with(1, 0, 0, text="GO")


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_label_button_grid(mock_client_factory):
    from companion_mcp.server import label_button_grid
    fake = MagicMock()
    fake.set_style = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    labels = json.dumps(["GO", "STOP", "", "BLACKOUT"])
    result = json.loads(await label_button_grid(1, labels, columns=4))
    assert result["labeled"] == 3  # empty string skipped
