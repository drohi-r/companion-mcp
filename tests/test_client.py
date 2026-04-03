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
    client.get_control_snapshot = AsyncMock(return_value={"ok": True, "body": {"type": "init", "config": {"text": "GO"}}})

    result = await client.get_button_info_current(1, 0, 0)
    assert result["body"]["control_id"] == "bank:abc"
    assert result["body"]["control"]["config"]["text"] == "GO"
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
    client.get_control_snapshot = AsyncMock(return_value={"ok": True, "body": {"type": "init"}})

    result = await client.get_page_grid_current(1, 1, 2, include_empty=False)
    assert result["body"]["count"] == 1
    assert result["body"]["buttons"][0]["control_id"] == "bank:abc"
    assert result["body"]["buttons"][0]["preview_meta"]["image_sha256"]
