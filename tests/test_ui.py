from __future__ import annotations

import json

from companion_mcp import ui


def test_parse_bool_values():
    assert ui._parse_bool("1") is True
    assert ui._parse_bool("true") is True
    assert ui._parse_bool("0") is False
    assert ui._parse_bool(None, default=True) is True


def test_query_int_validation():
    assert ui._query_int({"page": ["7"]}, "page", 1) == 7


def test_json_bytes_round_trip():
    payload = {"ok": True, "count": 2}
    assert json.loads(ui._json_bytes(payload).decode("utf-8")) == payload


def test_coords_json_for_selected_button():
    payload = json.loads(ui._coords_json({"page": 1, "row": 2, "column": 3}))
    assert payload == [{"page": 1, "row": 2, "column": 3}]


def test_coords_json_missing_button_returns_empty_string():
    assert ui._coords_json({"page": 1}) == ""
