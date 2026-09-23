import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_add_button_element_resolves_and_adds(mock_client_factory):
    from companion_mcp.server import add_button_element
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.style_add_element = AsyncMock(return_value={"ok": True, "body": "text9"})
    mock_client_factory.return_value = fake

    result = json.loads(await add_button_element(2, 0, 3, "text"))
    assert result["ok"] is True
    assert result["element_id"] == "text9"
    fake.style_add_element.assert_awaited_once_with("bank:xyz", "text", after=None)


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_add_button_element_missing_control(mock_client_factory):
    from companion_mcp.server import add_button_element
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value=None)
    mock_client_factory.return_value = fake

    result = json.loads(await add_button_element(2, 0, 3, "text"))
    assert result["ok"] is False
    assert result["blocked"] is True


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_add_button_element_rejects_bad_type(mock_client_factory):
    from companion_mcp.server import add_button_element
    fake = MagicMock()
    mock_client_factory.return_value = fake
    result = json.loads(await add_button_element(2, 0, 3, "widget"))
    assert result["ok"] is False


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_update_button_element_converts_values(mock_client_factory):
    from companion_mcp.server import update_button_element
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.style_update_options = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    await update_button_element(2, 0, 3, "text9", '{"color": "#00CC00"}')
    args = fake.style_update_options.await_args.args
    assert args[0] == "bank:xyz" and args[1] == "text9"
    assert args[2]["color"] == {"value": 0x00CC00, "isExpression": False}


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_preview_button_layered_style_no_write(mock_client_factory):
    from companion_mcp.server import preview_button_layered_style
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.get_control_config = AsyncMock(return_value={
        "ok": True,
        "config": {"feedbacks": []},
        "layers": [{"id": "canvas", "type": "canvas"},
                   {"id": "box0", "type": "box", "name": "Background"}]})
    mock_client_factory.return_value = fake

    layers = '[{"type":"box","name":"bg","color":"#101010"}]'
    result = json.loads(await preview_button_layered_style(2, 0, 3, layers))
    assert result["ok"] is True
    assert result["plan"]["removes"] == ["box0"]
    assert result["plan"]["adds"][0]["type"] == "box"
    assert not fake.style_add_element.called
    assert not fake.style_remove_element.called


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_button_layered_style_applies_plan_in_order(mock_client_factory):
    from companion_mcp.server import set_button_layered_style
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.get_control_config = AsyncMock(return_value={
        "ok": True, "config": {"feedbacks": []},
        "layers": [{"id": "canvas", "type": "canvas"},
                   {"id": "box0", "type": "box"},
                   {"id": "text0", "type": "text"}]})
    fake.style_remove_element = AsyncMock(return_value={"ok": True})
    fake.style_add_element = AsyncMock(side_effect=[
        {"ok": True, "body": "boxA"}, {"ok": True, "body": "textB"}])
    fake.style_set_element_name = AsyncMock(return_value={"ok": True})
    fake.style_update_options = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    layers = ('[{"type":"box","name":"bg","color":"#101010"},'
              '{"type":"text","name":"label","text":"GO","color":"#FFFFFF"}]')
    result = json.loads(await set_button_layered_style(2, 0, 3, layers))

    assert result["ok"] is True
    assert fake.style_remove_element.await_count == 2
    add_calls = fake.style_add_element.await_args_list
    assert add_calls[0].kwargs["after"] == "canvas"
    assert add_calls[1].kwargs["after"] == "boxA"


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_button_layered_style_warns_on_feedback_ref(mock_client_factory):
    from companion_mcp.server import set_button_layered_style
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.get_control_config = AsyncMock(return_value={
        "ok": True,
        "config": {"feedbacks": [{"style": {"targetElementId": "box0"}}]},
        "layers": [{"id": "canvas", "type": "canvas"}, {"id": "box0", "type": "box"}]})
    fake.style_remove_element = AsyncMock(return_value={"ok": True})
    fake.style_add_element = AsyncMock(return_value={"ok": True, "body": "boxA"})
    fake.style_set_element_name = AsyncMock(return_value={"ok": True})
    fake.style_update_options = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    result = json.loads(await set_button_layered_style(
        2, 0, 3, '[{"type":"box","name":"bg","color":"#101010"}]'))
    assert result["feedback_warnings"] == ["box0"]


@pytest.mark.asyncio
@patch("companion_mcp.server.set_button_layered_style")
async def test_set_page_layered_style_iterates(mock_set):
    from companion_mcp.server import set_page_layered_style
    mock_set.side_effect = [
        json.dumps({"ok": True, "control_id": "bank:a"}),
        json.dumps({"ok": True, "control_id": "bank:b"}),
    ]
    buttons = json.dumps([
        {"row": 0, "column": 0, "layers": [{"type": "box", "color": "#101010"}]},
        {"row": 0, "column": 1, "layers": [{"type": "box", "color": "#202020"}]},
    ])
    result = json.loads(await set_page_layered_style(2, buttons))
    assert result["count"] == 2
    assert result["results"][0]["ok"] is True
    assert mock_set.await_count == 2


@pytest.mark.asyncio
async def test_set_page_layered_style_validates_entries():
    from companion_mcp.server import set_page_layered_style
    result = json.loads(await set_page_layered_style(2, '[{"row": 0}]'))
    assert result["ok"] is False
    assert result["blocked"] is True


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_button_style_blocks_when_api_gated(mock_client_factory):
    from companion_mcp.server import set_button_style
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.get_control_config = AsyncMock(return_value={
        "ok": True, "config": {"options": {"canModifyStyleInApis": False}}, "layers": []})
    mock_client_factory.return_value = fake

    result = json.loads(await set_button_style(2, 0, 3, text="HI"))
    assert result["ok"] is False
    assert result["reason"] == "style-api-gated"
    assert not fake.set_style.called


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_button_style_writes_when_api_enabled(mock_client_factory):
    from companion_mcp.server import set_button_style
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.get_control_config = AsyncMock(return_value={
        "ok": True, "config": {"options": {"canModifyStyleInApis": True}}, "layers": []})
    fake.set_style = AsyncMock(return_value={"ok": True, "status_code": 200})
    mock_client_factory.return_value = fake

    result = json.loads(await set_button_style(2, 0, 3, text="HI"))
    assert result["ok"] is True
    fake.set_style.assert_awaited_once()


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_set_button_style_api_access_toggles(mock_client_factory):
    from companion_mcp.server import set_button_style_api_access
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.set_options_field = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    result = json.loads(await set_button_style_api_access(2, 0, 3, True))
    assert result["ok"] is True
    fake.set_options_field.assert_awaited_once_with("bank:xyz", "canModifyStyleInApis", True)
