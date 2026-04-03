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
    assert "base_url" in result


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_health_check(mock_client_factory):
    from companion_mcp.server import health_check
    fake = MagicMock()
    fake.request = AsyncMock(return_value={"ok": True, "status_code": 200, "content_type": "application/json", "body": []})
    mock_client_factory.return_value = fake

    result = json.loads(await health_check())
    assert result["ok"] is True
    assert result["probe_path"] == "/api/surfaces"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_list_surfaces(mock_client_factory):
    from companion_mcp.server import list_surfaces
    fake = MagicMock()
    fake.list_surfaces = AsyncMock(return_value={"ok": True, "body": [{"id": "streamdeck-xl"}]})
    mock_client_factory.return_value = fake

    result = json.loads(await list_surfaces())
    assert result["ok"] is True
    assert result["body"][0]["id"] == "streamdeck-xl"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_get_button_info(mock_client_factory):
    from companion_mcp.server import get_button_info
    fake = MagicMock()
    fake.get_button = AsyncMock(return_value={"ok": True, "body": {"text": "GO"}})
    mock_client_factory.return_value = fake

    result = json.loads(await get_button_info(1, 0, 0))
    assert result["ok"] is True
    assert result["body"]["text"] == "GO"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_get_page_grid(mock_client_factory):
    from companion_mcp.server import get_page_grid
    fake = MagicMock()
    fake.get_button = AsyncMock(side_effect=[
        {"ok": True, "status_code": 200, "body": {"text": "GO"}},
        {"ok": True, "status_code": 200, "body": ""},
    ])
    mock_client_factory.return_value = fake

    result = json.loads(await get_page_grid(1, rows=1, columns=2))
    assert result["count"] == 1
    assert result["buttons"][0]["body"]["text"] == "GO"


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
@patch("companion_mcp.server._client")
async def test_label_button_grid(mock_client_factory):
    from companion_mcp.server import label_button_grid
    fake = MagicMock()
    fake.set_style = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    labels = json.dumps(["GO", "STOP", "", "BLACKOUT"])
    result = json.loads(await label_button_grid(1, labels, columns=4))
    assert result["labeled"] == 3  # empty string skipped
