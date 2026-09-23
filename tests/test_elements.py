import pytest

from companion_mcp import elements


def test_hex_to_int_rgb():
    assert elements.hex_to_int("#00CC00") == 0x00CC00
    assert elements.hex_to_int("00CC00") == 0x00CC00
    assert elements.hex_to_int("#FFFFFF") == 0xFFFFFF


def test_hex_to_int_argb():
    assert elements.hex_to_int("#80FF0000") == 0x80FF0000


def test_hex_to_int_rejects_bad():
    with pytest.raises(ValueError):
        elements.hex_to_int("#12")
    with pytest.raises(ValueError):
        elements.hex_to_int("#GGGGGG")


def test_int_to_hex():
    assert elements.int_to_hex(0x00CC00) == "#00CC00"
    assert elements.int_to_hex(0x80FF0000) == "#80FF0000"


def test_wrap_value_literal():
    assert elements.wrap_value(30) == {"value": 30, "isExpression": False}
    assert elements.wrap_value("START") == {"value": "START", "isExpression": False}


def test_wrap_value_expression():
    assert elements.wrap_value({"expr": "$(internal:time_s)"}) == {
        "value": "$(internal:time_s)",
        "isExpression": True,
    }


def test_convert_values_colors_and_expr():
    out = elements.convert_values({"color": "#00CC00", "text": "GO",
                                   "value": {"expr": "$(x:y)"}})
    assert out["color"] == {"value": 0x00CC00, "isExpression": False}
    assert out["text"] == {"value": "GO", "isExpression": False}
    assert out["value"] == {"value": "$(x:y)", "isExpression": True}


def test_build_element_values_box():
    element_type, name, values = elements.build_element_values(
        {"type": "box", "name": "bg", "color": "#101010", "cornerRadius": 12,
         "x": 0, "y": 0, "width": 100, "height": 100})
    assert element_type == "box"
    assert name == "bg"
    assert values["color"] == {"value": 0x101010, "isExpression": False}
    assert values["cornerRadius"] == {"value": 12, "isExpression": False}
    assert "type" not in values and "name" not in values


def test_build_element_values_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown element type"):
        elements.build_element_values({"type": "widget"})


def test_build_element_values_rejects_unknown_field():
    with pytest.raises(ValueError, match="not valid for element type 'box'"):
        elements.build_element_values({"type": "box", "text": "nope"})


def test_build_element_values_rejects_out_of_range_percent():
    with pytest.raises(ValueError, match="0..100"):
        elements.build_element_values({"type": "box", "x": 150})


def test_build_element_values_canvas_fields():
    element_type, name, values = elements.build_element_values(
        {"type": "canvas", "decoration": "border"})
    assert element_type == "canvas"
    assert values["decoration"] == {"value": "border", "isExpression": False}


def _layer(eid, etype, name="X"):
    return {"id": eid, "type": etype, "name": name}


def test_reconcile_replace_stack():
    current = [
        _layer("canvas", "canvas", "Canvas"),
        _layer("box0", "box", "Background"),
        _layer("image0", "image", "Image"),
        _layer("text0", "text", "Text"),
    ]
    desired = [
        {"type": "box", "name": "bg", "color": "#101010"},
        {"type": "text", "name": "label", "text": "GO", "color": "#FFFFFF"},
    ]
    plan = elements.reconcile(current, desired)
    assert plan["canvas_update"] is None
    assert plan["removes"] == ["box0", "image0", "text0"]
    assert [a["type"] for a in plan["adds"]] == ["box", "text"]
    assert plan["adds"][0]["name"] == "bg"
    assert plan["adds"][0]["values"]["color"] == {"value": 0x101010, "isExpression": False}


def test_reconcile_canvas_only_tweak_updates_not_adds():
    current = [_layer("canvas", "canvas", "Canvas"), _layer("box0", "box")]
    desired = [{"type": "canvas", "decoration": "none"}]
    plan = elements.reconcile(current, desired)
    assert plan["canvas_update"] == {
        "elementId": "canvas",
        "values": {"decoration": {"value": "none", "isExpression": False}},
    }
    assert plan["removes"] == ["box0"]
    assert plan["adds"] == []


def test_reconcile_missing_canvas_raises():
    with pytest.raises(ValueError, match="no canvas"):
        elements.reconcile([_layer("box0", "box")], [{"type": "box"}])


def test_find_feedback_element_refs_detects():
    config = {
        "type": "button-layered",
        "style": {"layers": [{"id": "box0", "type": "box"}]},
        "feedbacks": [{"id": "fb1", "style": {"targetElementId": "box0"}}],
    }
    refs = elements.find_feedback_element_refs(config, ["box0", "text0"])
    assert refs == ["box0"]


def test_find_feedback_element_refs_none():
    config = {"style": {"layers": [{"id": "box0"}]}, "feedbacks": []}
    assert elements.find_feedback_element_refs(config, ["box0"]) == []
