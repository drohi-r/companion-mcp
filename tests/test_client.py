import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from companion_mcp.client import CompanionClient
from companion_mcp.config import CompanionConfig


@pytest.mark.asyncio
async def test_request_constructs_url():
    client = CompanionClient(CompanionConfig(host="10.0.0.1", port=9000, timeout_s=3.5))
    response = MagicMock()
    response.headers = {"content-type": "text/plain"}
    response.text = "ok"
    response.is_success = True
    response.status_code = 200

    async_client = MagicMock()
    async_client.request = AsyncMock(return_value=response)
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=False)

    with patch("companion_mcp.client.httpx.AsyncClient", return_value=async_client):
        result = await client.request("POST", "/api/test")

    assert result["url"] == "http://10.0.0.1:9000/api/test"
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert async_client.request.await_count == 1


@pytest.mark.asyncio
async def test_request_handles_json_response():
    client = CompanionClient(CompanionConfig())
    response = MagicMock()
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {"status": "ok"}
    response.is_success = True
    response.status_code = 200

    async_client = MagicMock()
    async_client.request = AsyncMock(return_value=response)
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=False)

    with patch("companion_mcp.client.httpx.AsyncClient", return_value=async_client):
        result = await client.request("GET", "/api/test")

    assert result["body"] == {"status": "ok"}


@pytest.mark.asyncio
async def test_request_handles_invalid_json():
    client = CompanionClient(CompanionConfig())
    response = MagicMock()
    response.headers = {"content-type": "application/json"}
    response.json.side_effect = Exception("bad json")
    response.text = "not json"
    response.is_success = False
    response.status_code = 500

    async_client = MagicMock()
    async_client.request = AsyncMock(return_value=response)
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=False)

    with patch("companion_mcp.client.httpx.AsyncClient", return_value=async_client):
        result = await client.request("GET", "/api/test")

    assert result["body"] == "not json"
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_button_action_calls_correct_path():
    client = CompanionClient(CompanionConfig())
    response = MagicMock()
    response.headers = {"content-type": "text/plain"}
    response.text = "ok"
    response.is_success = True
    response.status_code = 200

    async_client = MagicMock()
    async_client.request = AsyncMock(return_value=response)
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=False)

    with patch("companion_mcp.client.httpx.AsyncClient", return_value=async_client):
        result = await client.button_action(1, 2, 3, "press")

    assert result["path"] == "/api/location/1/2/3/press"


@pytest.mark.asyncio
async def test_set_style_uses_query_params():
    client = CompanionClient(CompanionConfig())
    response = MagicMock()
    response.headers = {"content-type": "text/plain"}
    response.text = "ok"
    response.is_success = True
    response.status_code = 200

    async_client = MagicMock()
    async_client.request = AsyncMock(return_value=response)
    async_client.__aenter__ = AsyncMock(return_value=async_client)
    async_client.__aexit__ = AsyncMock(return_value=False)

    with patch("companion_mcp.client.httpx.AsyncClient", return_value=async_client):
        await client.set_style(1, 0, 0, text="GO", bgcolor="ff0000")

    call_kwargs = async_client.request.call_args
    assert call_kwargs[0][1] == "http://127.0.0.1:8000/api/location/1/0/0/style?text=GO&bgcolor=ff0000"


@pytest.mark.asyncio
async def test_set_step_uses_query_param():
    client = CompanionClient(CompanionConfig())
    response = MagicMock()
    response.headers = {"content-type": "text/plain"}
    response.text = ""
    response.is_success = True
    response.status_code = 204

    async_client = MagicMock()
    async_client.request = AsyncMock(return_value=response)

    with patch("companion_mcp.client.httpx.AsyncClient", return_value=async_client):
        result = await client.set_step(1, 2, 3, 4)

    assert result["path"] == "/api/location/1/2/3/step?step=4"


def test_control_id_from_pages_snapshot():
    client = CompanionClient(CompanionConfig())
    pages = {
        "order": ["page-a"],
        "pages": {
            "page-a": {
                "controls": {
                    "0": {"0": "bank:abc"},
                }
            }
        },
    }
    assert client._control_id_from_pages_snapshot(pages, 1, 0, 0) == "bank:abc"
    assert client._control_id_from_pages_snapshot(pages, 1, 0, 1) is None


@pytest.mark.asyncio
async def test_get_custom_variable_current_extracts_value():
    client = CompanionClient(CompanionConfig())
    client.get_variable_values = AsyncMock(return_value={"ok": True, "body": {"show_name": "Nobo"}})
    result = await client.get_custom_variable_current("show_name")
    assert result["body"]["value"] == "Nobo"
    assert result["body"]["exists"] is True


@pytest.mark.asyncio
async def test_get_button_info_current_combines_control_and_preview():
    client = CompanionClient(CompanionConfig())
    client.get_pages_snapshot = AsyncMock(return_value={
        "ok": True,
        "body": {
            "order": ["page-a"],
            "pages": {
                "page-a": {
                    "controls": {"0": {"0": "bank:abc"}},
                }
            },
        },
    })
    client.get_preview_location = AsyncMock(return_value={"ok": True, "body": {"image": "data:image/png;base64,YWJj"}})
    client.get_control_snapshot = AsyncMock(return_value={"ok": True, "body": {"type": "init", "config": {"text": "GO", "style": {"text": "GO", "color": 1, "bgcolor": 2}}, "feedbacks": [{"id": "f1", "definitionId": "go", "style": {"bgcolor": 3}}]}})

    result = await client.get_button_info_current(1, 0, 0)
    assert result["body"]["control_id"] == "bank:abc"
    assert result["body"]["control"]["config"]["text"] == "GO"
    assert result["body"]["style_meta"]["text"] == "GO"
    assert result["body"]["feedback_meta"]["active_style_feedbacks"] == 1
    assert result["body"]["feedback_meta"]["style_may_be_feedback_controlled"] is True
    assert result["body"]["preview_meta"]["image_sha256"]
    assert result["body"]["preview_meta"]["image_bytes"] > 0


@pytest.mark.asyncio
async def test_get_page_grid_current_skips_empty_buttons():
    client = CompanionClient(CompanionConfig())
    client.get_pages_snapshot = AsyncMock(return_value={
        "ok": True,
        "body": {
            "order": ["page-a"],
            "pages": {
                "page-a": {
                    "controls": {"0": {"0": "bank:abc"}},
                }
            },
        },
    })
    client.get_preview_location = AsyncMock(return_value={"ok": True, "body": {"image": "data:image/png;base64,YWJj"}})
    client.get_control_snapshot = AsyncMock(return_value={"ok": True, "body": {"type": "init", "config": {"style": {"text": "GO"}}, "feedbacks": []}})

    result = await client.get_page_grid_current(1, 1, 2, include_empty=False)
    assert result["body"]["count"] == 1
    assert result["body"]["buttons"][0]["control_id"] == "bank:abc"
    assert result["body"]["buttons"][0]["style_meta"]["text"] == "GO"
    assert result["body"]["buttons"][0]["feedback_meta"]["count"] == 0
    assert result["body"]["buttons"][0]["preview_meta"]["image_sha256"]


# --- 5.x layered-styling client methods ---
from unittest.mock import AsyncMock as _AsyncMock  # noqa: E402
from companion_mcp.client import CompanionClient as _CC  # noqa: E402
from companion_mcp.config import CompanionConfig as _CFG  # noqa: E402


@pytest.mark.asyncio
async def test_style_add_element_calls_mutation():
    client = _CC(_CFG())
    client.trpc_call = _AsyncMock(return_value={"ok": True, "body": "text9"})
    result = await client.style_add_element("bank:abc", "text", after="canvas")
    assert result["body"] == "text9"
    client.trpc_call.assert_awaited_once_with(
        "mutation", "controls.styles.addElement",
        input={"controlId": "bank:abc", "type": "text", "afterElementId": "canvas"})


@pytest.mark.asyncio
async def test_style_update_options_calls_mutation():
    client = _CC(_CFG())
    client.trpc_call = _AsyncMock(return_value={"ok": True, "body": None})
    values = {"color": {"value": 255, "isExpression": False}}
    await client.style_update_options("bank:abc", "text9", values)
    client.trpc_call.assert_awaited_once_with(
        "mutation", "controls.styles.updateOptions",
        input={"controlId": "bank:abc", "elementId": "text9", "values": values})


@pytest.mark.asyncio
async def test_style_remove_and_move_and_name():
    client = _CC(_CFG())
    client.trpc_call = _AsyncMock(return_value={"ok": True})
    await client.style_remove_element("bank:abc", "text9")
    await client.style_move_element("bank:abc", "text9", 2, parent=None)
    await client.style_set_element_name("bank:abc", "text9", "label")
    paths = [c.args[1] for c in client.trpc_call.await_args_list]
    assert paths == ["controls.styles.removeElement",
                     "controls.styles.moveElement",
                     "controls.styles.setElementName"]


@pytest.mark.asyncio
async def test_set_options_field_calls_mutation():
    client = _CC(_CFG())
    client.trpc_call = _AsyncMock(return_value={"ok": True})
    await client.set_options_field("bank:abc", "canModifyStyleInApis", True)
    client.trpc_call.assert_awaited_once_with(
        "mutation", "controls.setOptionsField",
        input={"controlId": "bank:abc", "key": "canModifyStyleInApis", "value": True})


@pytest.mark.asyncio
async def test_resolve_control_id_uses_pages_snapshot():
    client = _CC(_CFG())
    client.get_pages_snapshot = _AsyncMock(return_value={"ok": True, "body": {
        "order": ["p1", "p2"],
        "pages": {"p2": {"controls": {"0": {"3": "bank:xyz"}}}},
    }})
    assert await client.resolve_control_id(2, 0, 3) == "bank:xyz"
    assert await client.resolve_control_id(2, 5, 5) is None


@pytest.mark.asyncio
async def test_get_control_config_extracts_config():
    client = _CC(_CFG())
    client.get_control_snapshot = _AsyncMock(return_value={"ok": True, "body": {
        "type": "init",
        "config": {"type": "button-layered",
                   "options": {"canModifyStyleInApis": False},
                   "style": {"layers": [{"id": "canvas", "type": "canvas"}]}},
    }})
    out = await client.get_control_config("bank:xyz")
    assert out["ok"] is True
    assert out["config"]["options"]["canModifyStyleInApis"] is False
    assert out["layers"] == [{"id": "canvas", "type": "canvas"}]


@pytest.mark.asyncio
async def test_get_control_config_handles_missing():
    client = _CC(_CFG())
    client.get_control_snapshot = _AsyncMock(return_value={"ok": False, "body": None})
    out = await client.get_control_config("bank:xyz")
    assert out["ok"] is False
    assert out["config"] is None
    assert out["layers"] == []
