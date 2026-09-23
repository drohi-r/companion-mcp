"""Pure logic for Companion 5.x layered button styling.

No network I/O. Converts human-friendly layer specs (hex colors, percentages,
optional expressions) into the tRPC element-mutation shapes, and reconciles a
button's current layer stack toward a desired spec.
"""

from __future__ import annotations

from typing import Any

_HEX_DIGITS = set("0123456789abcdefABCDEF")

# Structural keys in a client-side layer spec (not element properties).
STRUCTURAL_KEYS = {"type", "name"}

# Fields whose values are colors (hex on input, int stored).
COLOR_FIELDS = {"color", "borderColor", "outlineColor", "markerColor"}

# Fields validated as percentages 0..100.
PERCENT_FIELDS = {"x", "y", "width", "height", "fromX", "fromY", "toX", "toY"}

# Common transform/visibility fields shared by all non-canvas elements.
_COMMON = {"enabled", "opacity", "x", "y", "width", "height", "rotation"}

# Allowed settable fields per element type (excludes structural keys).
ELEMENT_FIELDS: dict[str, set[str]] = {
    "box": _COMMON | {"color", "cornerRadius", "borderWidth", "borderColor", "borderPosition"},
    "text": _COMMON | {"text", "color", "outlineColor", "fontsize", "fontsizeAllowShrink",
                       "font", "weight", "styles", "halign", "valign"},
    "image": _COMMON | {"base64Image", "halign", "valign", "fillMode"},
    "gauge": _COMMON | {"value", "min", "max", "origin", "symmetric", "orientation", "reverse",
                        "startAngle", "endAngle", "ringWidth", "roundedEnds", "fillEnabled",
                        "multiColour", "fillWidth", "markerEnabled", "markerColor", "markerWidth",
                        "trackStyle", "trackAmount", "trackWidth"},
    "line": {"enabled", "opacity", "fromX", "fromY", "toX", "toY",
             "borderWidth", "borderColor", "borderPosition"},
    "circle": _COMMON | {"color", "startAngle", "endAngle", "drawSlice", "borderOnlyArc",
                         "borderWidth", "borderColor", "borderPosition"},
    "group": _COMMON | {"squareCoords"},
    "reference": _COMMON | {"location"},
    "canvas": {"decoration", "showStatusIcons"},
}

# Types that can be added/removed via addElement/removeElement (canvas excluded).
ADDABLE_TYPES = set(ELEMENT_FIELDS) - {"canvas"}


def hex_to_int(value: str) -> int:
    """Convert '#RRGGBB' or '#AARRGGBB' (with/without '#') to an int."""
    normalized = value.lstrip("#")
    if len(normalized) not in (6, 8) or any(ch not in _HEX_DIGITS for ch in normalized):
        raise ValueError(f"invalid hex color: {value!r} (expected #RRGGBB or #AARRGGBB)")
    return int(normalized, 16)


def int_to_hex(value: int) -> str:
    """Convert a stored color int back to '#RRGGBB' (or '#AARRGGBB' if alpha set)."""
    if value > 0xFFFFFF:
        return f"#{value:08X}"
    return f"#{value:06X}"


def wrap_value(value: Any) -> dict[str, Any]:
    """Wrap a spec value as Companion's ExpressionOrValue.

    A dict of the form {"expr": "<expression string>"} becomes an expression;
    anything else is a literal.
    """
    if isinstance(value, dict) and set(value.keys()) == {"expr"}:
        return {"value": value["expr"], "isExpression": True}
    return {"value": value, "isExpression": False}


def _validate_percent(field: str, value: Any) -> None:
    if isinstance(value, (int, float)) and not (0 <= value <= 100):
        raise ValueError(f"{field} must be within 0..100, got {value}")


def convert_values(values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Convert a flat {field: raw} map into {field: ExpressionOrValue}.

    Hex strings on COLOR_FIELDS become ints. Values may be literals or {"expr": ...}.
    Does NOT validate field names (used by the raw primitive path).
    """
    out: dict[str, dict[str, Any]] = {}
    for key, raw in values.items():
        if key in COLOR_FIELDS and isinstance(raw, str):
            raw = hex_to_int(raw)
        if key in PERCENT_FIELDS:
            _validate_percent(key, raw)
        out[key] = wrap_value(raw)
    return out


def build_element_values(spec: dict[str, Any]) -> tuple[str, str | None, dict[str, dict[str, Any]]]:
    """Validate a layer spec and return (element_type, name, wrapped_values).

    Rejects unknown element types and unknown fields for the given type.
    """
    element_type = spec.get("type")
    if element_type not in ELEMENT_FIELDS:
        raise ValueError(f"unknown element type: {element_type!r}")
    name = spec.get("name")
    allowed = ELEMENT_FIELDS[element_type]
    field_values = {}
    for key, raw in spec.items():
        if key in STRUCTURAL_KEYS:
            continue
        if key not in allowed:
            raise ValueError(f"field {key!r} is not valid for element type {element_type!r}")
        field_values[key] = raw
    return element_type, name, convert_values(field_values)


def _canvas_id(current_layers: list[dict[str, Any]]) -> str:
    for layer in current_layers:
        if layer.get("type") == "canvas":
            cid = layer.get("id")
            if isinstance(cid, str):
                return cid
    raise ValueError("button has no canvas element; cannot reconcile styling")


def reconcile(current_layers: list[dict[str, Any]],
              desired: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace-mode reconcile: turn current stack + desired specs into a plan.

    - canvas is preserved; a desired {type:'canvas', ...} spec becomes an update.
    - all current non-canvas layers are removed.
    - all desired non-canvas specs are added in given (bottom->top) order.
    """
    _canvas_id(current_layers)  # validates a canvas exists

    canvas_update = None
    adds: list[dict[str, Any]] = []
    for spec in desired:
        element_type, name, values = build_element_values(spec)
        if element_type == "canvas":
            canvas_update = {"elementId": "canvas", "values": values}
            continue
        adds.append({"type": element_type, "name": name, "values": values})

    removes = [layer["id"] for layer in current_layers
               if layer.get("type") != "canvas" and isinstance(layer.get("id"), str)]

    return {"canvas_update": canvas_update, "removes": removes, "adds": adds}


def _contains_string(node: Any, needle: str) -> bool:
    if isinstance(node, str):
        return node == needle
    if isinstance(node, dict):
        return any(_contains_string(v, needle) for v in node.values())
    if isinstance(node, list):
        return any(_contains_string(v, needle) for v in node)
    return False


def find_feedback_element_refs(config: dict[str, Any],
                               element_ids: list[str]) -> list[str]:
    """Return which of element_ids are referenced by the control's feedbacks.

    Searches the control config's feedback data (NOT the style.layers subtree,
    where the element ids naturally live) for each id.
    """
    if not isinstance(config, dict):
        return []
    search_space = {k: v for k, v in config.items() if k != "style"}
    return [eid for eid in element_ids if _contains_string(search_space, eid)]
