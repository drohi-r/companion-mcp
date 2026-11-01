import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

CONNS = {
    "type": "init",
    "info": {
        "atem1": {"id": "atem1", "moduleType": "connection", "moduleId": "bmd-atem", "label": "atem", "enabled": False, "sortOrder": 1},
        "vmix1": {"id": "vmix1", "moduleType": "connection", "moduleId": "studiocoast-vmix", "label": "vmix", "enabled": True, "sortOrder": 2},
    },
}


def _fake(**overrides):
    fake = MagicMock()
    fake.list_connections = AsyncMock(return_value={"ok": True, "body": [CONNS]})
    fake.get_pages_snapshot = AsyncMock(return_value={"ok": True, "body": {"order": ["p1", "p2"], "pages": {}}})
    for key, value in overrides.items():
        setattr(fake, key, value)
    return fake


def test_auto_remap_prefers_id_then_label_then_module_and_ignores_unknown():
    from companion_mcp.server import _auto_remap

    existing = CONNS["info"]
    imported = {
        "atem1": {"moduleId": "bmd-atem", "label": "atem"},
        "oldvmix": {"moduleId": "studiocoast-vmix", "label": "vmix"},
        "otheratem": {"moduleId": "bmd-atem", "label": "atem-b"},
        "qlab": {"moduleId": "figure53-qlab-advance", "label": "qlab"},
    }
    remap = _auto_remap(imported, existing, {}, allow_create=False)
    assert remap == {"atem1": "atem1", "oldvmix": "vmix1", "otheratem": "atem1", "qlab": "_ignore"}
    assert _auto_remap({"qlab": imported["qlab"]}, existing, {}, allow_create=True) == {"qlab": ""}
    assert _auto_remap({"atem1": imported["atem1"]}, existing, {"atem1": "_ignore"}, allow_create=False) == {"atem1": "_ignore"}


def test_write_failed_and_entity_location():
    from companion_mcp.server import _entity_location, _write_failed

    assert _write_failed({"ok": True, "body": False})
    assert _write_failed({"ok": True, "body": "fail"})
    assert _write_failed({"ok": False})
    assert not _write_failed({"ok": True, "body": None})
    assert _entity_location("down", "0") == {"stepId": "0", "setId": "down"}
    assert _entity_location("feedbacks", "0") == "feedbacks"
    assert _entity_location("1500", "1") == {"stepId": "1", "setId": 1500}
    with pytest.raises(ValueError):
        _entity_location("sideways", "0")


@pytest.mark.asyncio
@patch("companion_mcp.server.load_config")
async def test_native_writes_respect_write_gate(mock_load_config):
    from companion_mcp.server import create_button, import_page_config, set_connection_enabled

    mock_load_config.return_value = MagicMock(write_enabled=False)
    for coro in (
        create_button(1, 0, 1),
        set_connection_enabled("atem", True),
        import_page_config("/nonexistent", 1),
    ):
        result = json.loads(await coro)
        assert result["blocked"] is True
        assert "disabled" in result["error"]


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_create_button_refuses_occupied_slot(mock_client_factory):
    from companion_mcp.server import create_button

    fake = _fake(get_control_id_at=AsyncMock(return_value="bank:existing"), reset_controls=AsyncMock())
    mock_client_factory.return_value = fake
    result = json.loads(await create_button(1, 0, 1))
    assert result["blocked"] is True
    fake.reset_controls.assert_not_called()


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_destructive_page_tools_need_confirm(mock_client_factory):
    from companion_mcp.server import clear_page, delete_button, remove_page

    fake = _fake(clear_page=AsyncMock(), remove_page=AsyncMock(), reset_controls=AsyncMock())
    mock_client_factory.return_value = fake
    for coro in (clear_page(2), remove_page(2), delete_button(2, 0, 0)):
        assert json.loads(await coro)["blocked"] is True
    fake.clear_page.assert_not_called()
    fake.remove_page.assert_not_called()
    fake.reset_controls.assert_not_called()


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_import_requires_confirm_and_backs_up(mock_client_factory, tmp_path, monkeypatch):
    from companion_mcp.server import import_page_config

    monkeypatch.setenv("COMPANION_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    cfg = {"version": 12, "type": "page", "page": {"name": "x", "controls": {}},
           "instances": {"q": {"moduleId": "figure53-qlab-advance", "label": "qlab", "enabled": True}}}
    f = tmp_path / "p.companionconfig"
    f.write_text(json.dumps(cfg))

    captured = {}

    async def fake_import(data, **kwargs):
        captured["data"] = json.loads(data)
        captured["remap"] = kwargs["remap_fn"](captured["data"]["instances"])
        return {"ok": True, "remap_requested": captured["remap"], "steps": []}

    fake = _fake(
        export_page_config=AsyncMock(return_value={"ok": True, "body": {"type": "page", "page": {"name": "old"}}}),
        import_page_config=AsyncMock(side_effect=fake_import),
    )
    mock_client_factory.return_value = fake

    blocked = json.loads(await import_page_config(str(f), 1))
    assert blocked["blocked"] is True
    fake.import_page_config.assert_not_called()

    result = json.loads(await import_page_config(str(f), 1, confirm_overwrite=True))
    assert result["ok"] is True
    assert result["backup"] and result["backup"].endswith(".companionconfig")
    assert captured["data"]["instances"]["q"]["enabled"] is False  # never auto-enable devices
    assert result["ignored_connections"] == ["q"]


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_add_button_action_sets_and_verifies_options(mock_client_factory):
    from companion_mcp.server import add_button_action

    control = {"config": {"type": "button-layered", "feedbacks": [], "steps": {"0": {"action_sets": {"down": [
        {"id": "e1", "connectionId": "atem1", "definitionId": "program",
         "options": {"mixeffect": {"value": 0, "isExpression": False}, "input": {"value": 3, "isExpression": False}}}
    ], "up": []}}}}}
    fake = _fake(
        get_control_id_at=AsyncMock(return_value="bank:b1"),
        entity_add=AsyncMock(return_value={"ok": True, "body": "e1"}),
        entity_set_option=AsyncMock(return_value={"ok": True, "body": True}),
        get_control_snapshot=AsyncMock(return_value={"ok": True, "body": control}),
    )
    mock_client_factory.return_value = fake

    result = json.loads(await add_button_action(1, 0, 1, "atem", "program", '{"mixeffect": 0, "input": 3}'))
    assert result["ok"] is True
    assert result["connection_id"] == "atem1"
    fake.entity_add.assert_awaited_once_with("bank:b1", {"stepId": "0", "setId": "down"}, "atem1", "action", "program")

    bad = json.loads(await add_button_action(1, 0, 1, "atem", "program", '{"input": 4}'))
    assert bad["ok"] is False and bad["mismatched_options"] == ["input"]


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_add_entity_reports_refusal(mock_client_factory):
    from companion_mcp.server import add_button_feedback

    fake = _fake(get_control_id_at=AsyncMock(return_value="bank:b1"), entity_add=AsyncMock(return_value={"ok": True, "body": None}))
    mock_client_factory.return_value = fake
    result = json.loads(await add_button_feedback(1, 0, 1, "vmix", "nope"))
    assert result["ok"] is False and "refused" in result["error"]


@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_list_entity_definitions_explains_disabled_connection(mock_client_factory):
    from companion_mcp.server import list_entity_definitions

    fake = _fake(get_entity_definitions=AsyncMock(return_value={"ok": True, "body": {"type": "init", "definitions": {"internal": {}}}}))
    mock_client_factory.return_value = fake
    result = json.loads(await list_entity_definitions("atem"))
    assert result["blocked"] is True and result["connection_enabled"] is False
