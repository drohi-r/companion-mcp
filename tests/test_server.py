import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_get_server_config():
    from companion_mcp.server import get_server_config
    result = json.loads(await get_server_config())
    assert result["host"] == "127.0.0.1"
    assert result["port"] == 8000
    assert "base_url" in result


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
    with pytest.raises(ValueError, match="JSON array"):
        await press_button_sequence('{"bad": true}')


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
