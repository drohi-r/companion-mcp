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
