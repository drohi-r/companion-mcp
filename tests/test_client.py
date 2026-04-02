import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from companion_mcp.client import CompanionClient
from companion_mcp.config import CompanionConfig


@pytest.mark.asyncio
async def test_request_constructs_url():
    client = CompanionClient(CompanionConfig(host="10.0.0.1", port=9000))
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
async def test_set_style_sends_json_body():
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
    assert call_kwargs[1]["json"] == {"text": "GO", "bgcolor": "ff0000"}
