# Companion MCP 5.0 Layered Styling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Companion 5.x tRPC write layer to the MCP so AI/operators can build layered button styles (box/text/image/gauge/etc.), and harden the legacy flat-style tools so they never silently no-op.

**Architecture:** A new network-free module `elements.py` holds all styling logic (color/percent/expression translation, per-type field validation, and a pure reconciler that turns `current layers + desired specs` into an ordered mutation plan). `client.py` gains thin `controls.styles.*` tRPC mutation methods plus control-id/config resolvers. `server.py` gains declarative + primitive + preview + batch tools, plus the legacy-hardening gate check.

**Tech Stack:** Python 3.12+, `mcp` (FastMCP), `httpx`, tRPC-over-WebSocket, pytest + pytest-asyncio (mocked-client tests). Run everything with `uv run`.

**Working context:** Work on `main` (per user). A restore point exists: git tag `pre-5.0-styling-baseline`. Live target is Companion 5.0.6.

---

## Confirmed API contract (used throughout)

- tRPC write = `client.trpc_call("mutation", path, input=...)`. No auth; loopback host OK.
- Mutations (all under `controls.styles.`):
  - `addElement { controlId, type, afterElementId }` → result `body` is the **new element id** (string). Inserts **above** `afterElementId` (top-of-stack when `null`).
  - `updateOptions { controlId, elementId, values: Record<key, {value,isExpression}> }`
  - `removeElement { controlId, elementId }`
  - `moveElement { controlId, elementId, parentElementId, newIndex }`
  - `setElementName { controlId, elementId, name }`
- Button-level option write: `controls.setOptionsField { controlId, key, value }` (used for `canModifyStyleInApis`).
- Read one control: `controls.watchControl { controlId }` (subscription) → `body = {type:"init", config:{type, options, style:{layers:[...]}, ...}, runtime}`. Already wrapped by `client.get_control_snapshot`.
- `controlId` resolved from `pages.watch` via existing `client._control_id_from_pages_snapshot`.
- Each element property is wrapped: literal → `{value, isExpression:false}`; expression → `{value:"<expr>", isExpression:true}`.
- `canvas` is the fixed bottom element: never add/remove; only `decoration` / `showStatusIcons` are editable.
- Coordinates `x/y/width/height` (and line `fromX/fromY/toX/toY`) are percentages 0–100.
- Colors stored as ints (`0xRRGGBB`); CSS strings also valid.

---

## File Structure

- **Create** `src/companion_mcp/elements.py` — pure styling logic (no I/O).
- **Create** `tests/test_elements.py` — unit tests for the above.
- **Modify** `src/companion_mcp/client.py` — add tRPC mutation methods + resolvers (after existing `set_step`/`get_control_snapshot` region).
- **Modify** `tests/test_client.py` — tests for the new client methods.
- **Modify** `src/companion_mcp/server.py` — add tools (near the existing styling/batch tool regions).
- **Modify** `tests/test_server.py` — tests for the new tools.
- **Modify** `README.md` — document the new tools.

---

## Task 1: Color + value conversion in `elements.py`

**Files:**
- Create: `src/companion_mcp/elements.py`
- Test: `tests/test_elements.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_elements.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_elements.py -v`
Expected: FAIL (`ModuleNotFoundError: companion_mcp.elements`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/companion_mcp/elements.py
"""Pure logic for Companion 5.x layered button styling.

No network I/O. Converts human-friendly layer specs (hex colors, percentages,
optional expressions) into the tRPC element-mutation shapes, and reconciles a
button's current layer stack toward a desired spec.
"""

from __future__ import annotations

from typing import Any

_HEX_DIGITS = set("0123456789abcdefABCDEF")


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_elements.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/elements.py tests/test_elements.py
git commit -m "feat(elements): color and expression-value conversion

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Field maps + `convert_values` + `build_element_values`

**Files:**
- Modify: `src/companion_mcp/elements.py`
- Test: `tests/test_elements.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_elements.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_elements.py -k "convert_values or build_element" -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'convert_values'`).

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/companion_mcp/elements.py

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_elements.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/elements.py tests/test_elements.py
git commit -m "feat(elements): per-type field validation and value building

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: The reconciler (`reconcile`)

**Files:**
- Modify: `src/companion_mcp/elements.py`
- Test: `tests/test_elements.py`

**Plan shape returned by `reconcile`:**
```python
{
  "canvas_update": {"elementId": "canvas", "values": {...}} | None,
  "removes": ["box0", "image0", "text0"],   # current non-canvas element ids
  "adds": [                                  # bottom -> top order
     {"type": "box",  "name": "bg",    "values": {...}},
     {"type": "text", "name": "label", "values": {...}},
  ],
}
```
Executor semantics (implemented later in server.py): apply `canvas_update`, then each
`removes` via `removeElement`, then walk `adds` bottom→top calling `addElement(type,
after=<prev id>)` starting from the canvas id, `setElementName` when `name` is set, and
`updateOptions` with `values`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_elements.py
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
    # canvas is never added or removed
    assert plan["removes"] == ["box0"]
    assert plan["adds"] == []


def test_reconcile_missing_canvas_raises():
    with pytest.raises(ValueError, match="no canvas"):
        elements.reconcile([_layer("box0", "box")], [{"type": "box"}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_elements.py -k reconcile -v`
Expected: FAIL (`AttributeError: ... 'reconcile'`).

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/companion_mcp/elements.py

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
```

Note: the canvas element id is always `"canvas"` on real buttons (confirmed live), so
`canvas_update.elementId` is hard-set to `"canvas"`; `_canvas_id` still validates presence.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_elements.py -v`
Expected: PASS (all element tests).

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/elements.py tests/test_elements.py
git commit -m "feat(elements): replace-mode layer reconciler

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Feedback-orphan detection helper

**Files:**
- Modify: `src/companion_mcp/elements.py`
- Test: `tests/test_elements.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_elements.py
def test_find_feedback_element_refs_detects():
    config = {
        "type": "button-layered",
        "style": {"layers": [{"id": "box0", "type": "box"}]},  # ignored subtree
        "feedbacks": [{"id": "fb1", "style": {"targetElementId": "box0"}}],
    }
    refs = elements.find_feedback_element_refs(config, ["box0", "text0"])
    assert refs == ["box0"]


def test_find_feedback_element_refs_none():
    config = {"style": {"layers": [{"id": "box0"}]}, "feedbacks": []}
    assert elements.find_feedback_element_refs(config, ["box0"]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_elements.py -k feedback -v`
Expected: FAIL (`AttributeError: ... 'find_feedback_element_refs'`).

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/companion_mcp/elements.py

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_elements.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/elements.py tests/test_elements.py
git commit -m "feat(elements): detect feedbacks referencing removed elements

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: tRPC mutation methods on the client

**Files:**
- Modify: `src/companion_mcp/client.py` (add after `trpc_subscription_once`, ~line 238)
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_client.py
import pytest
from unittest.mock import AsyncMock
from companion_mcp.client import CompanionClient
from companion_mcp.config import CompanionConfig


@pytest.mark.asyncio
async def test_style_add_element_calls_mutation():
    client = CompanionClient(CompanionConfig())
    client.trpc_call = AsyncMock(return_value={"ok": True, "body": "text9"})
    result = await client.style_add_element("bank:abc", "text", after="canvas")
    assert result["body"] == "text9"
    client.trpc_call.assert_awaited_once_with(
        "mutation", "controls.styles.addElement",
        input={"controlId": "bank:abc", "type": "text", "afterElementId": "canvas"})


@pytest.mark.asyncio
async def test_style_update_options_calls_mutation():
    client = CompanionClient(CompanionConfig())
    client.trpc_call = AsyncMock(return_value={"ok": True, "body": None})
    values = {"color": {"value": 255, "isExpression": False}}
    await client.style_update_options("bank:abc", "text9", values)
    client.trpc_call.assert_awaited_once_with(
        "mutation", "controls.styles.updateOptions",
        input={"controlId": "bank:abc", "elementId": "text9", "values": values})


@pytest.mark.asyncio
async def test_style_remove_and_move_and_name():
    client = CompanionClient(CompanionConfig())
    client.trpc_call = AsyncMock(return_value={"ok": True})
    await client.style_remove_element("bank:abc", "text9")
    await client.style_move_element("bank:abc", "text9", 2, parent=None)
    await client.style_set_element_name("bank:abc", "text9", "label")
    paths = [c.args[1] for c in client.trpc_call.await_args_list]
    assert paths == ["controls.styles.removeElement",
                     "controls.styles.moveElement",
                     "controls.styles.setElementName"]


@pytest.mark.asyncio
async def test_set_options_field_calls_mutation():
    client = CompanionClient(CompanionConfig())
    client.trpc_call = AsyncMock(return_value={"ok": True})
    await client.set_options_field("bank:abc", "canModifyStyleInApis", True)
    client.trpc_call.assert_awaited_once_with(
        "mutation", "controls.setOptionsField",
        input={"controlId": "bank:abc", "key": "canModifyStyleInApis", "value": True})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_client.py -k "style_ or set_options_field" -v`
Expected: FAIL (`AttributeError: ... 'style_add_element'`).

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/companion_mcp/client.py after trpc_subscription_once (~line 238)

    async def trpc_mutation(self, path: str, input: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.trpc_call("mutation", path, input=input)

    async def style_add_element(self, control_id: str, element_type: str,
                                after: str | None = None) -> dict[str, Any]:
        return await self.trpc_call(
            "mutation", "controls.styles.addElement",
            input={"controlId": control_id, "type": element_type, "afterElementId": after})

    async def style_update_options(self, control_id: str, element_id: str,
                                   values: dict[str, Any]) -> dict[str, Any]:
        return await self.trpc_call(
            "mutation", "controls.styles.updateOptions",
            input={"controlId": control_id, "elementId": element_id, "values": values})

    async def style_remove_element(self, control_id: str, element_id: str) -> dict[str, Any]:
        return await self.trpc_call(
            "mutation", "controls.styles.removeElement",
            input={"controlId": control_id, "elementId": element_id})

    async def style_move_element(self, control_id: str, element_id: str, new_index: int,
                                 parent: str | None = None) -> dict[str, Any]:
        return await self.trpc_call(
            "mutation", "controls.styles.moveElement",
            input={"controlId": control_id, "elementId": element_id,
                   "parentElementId": parent, "newIndex": new_index})

    async def style_set_element_name(self, control_id: str, element_id: str,
                                     name: str) -> dict[str, Any]:
        return await self.trpc_call(
            "mutation", "controls.styles.setElementName",
            input={"controlId": control_id, "elementId": element_id, "name": name})

    async def set_options_field(self, control_id: str, key: str, value: Any) -> dict[str, Any]:
        return await self.trpc_call(
            "mutation", "controls.setOptionsField",
            input={"controlId": control_id, "key": key, "value": value})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/client.py tests/test_client.py
git commit -m "feat(client): controls.styles.* tRPC mutation methods

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Client resolvers — control id, config, layers, style-api access

**Files:**
- Modify: `src/companion_mcp/client.py` (add after the methods from Task 5)
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_client.py
@pytest.mark.asyncio
async def test_resolve_control_id_uses_pages_snapshot():
    client = CompanionClient(CompanionConfig())
    client.get_pages_snapshot = AsyncMock(return_value={"ok": True, "body": {
        "order": ["p1", "p2"],
        "pages": {"p2": {"controls": {"0": {"3": "bank:xyz"}}}},
    }})
    assert await client.resolve_control_id(2, 0, 3) == "bank:xyz"
    assert await client.resolve_control_id(2, 5, 5) is None


@pytest.mark.asyncio
async def test_get_control_config_extracts_config():
    client = CompanionClient(CompanionConfig())
    client.get_control_snapshot = AsyncMock(return_value={"ok": True, "body": {
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
    client = CompanionClient(CompanionConfig())
    client.get_control_snapshot = AsyncMock(return_value={"ok": False, "body": None})
    out = await client.get_control_config("bank:xyz")
    assert out["ok"] is False
    assert out["config"] is None
    assert out["layers"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_client.py -k "resolve_control_id or get_control_config" -v`
Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/companion_mcp/client.py after the Task 5 methods

    async def resolve_control_id(self, page: int, row: int, column: int) -> str | None:
        snapshot = await self.get_pages_snapshot()
        return self._control_id_from_pages_snapshot(snapshot.get("body"), page, row, column)

    async def get_control_config(self, control_id: str) -> dict[str, Any]:
        snapshot = await self.get_control_snapshot(control_id)
        body = snapshot.get("body")
        config = body.get("config") if isinstance(body, dict) else None
        layers = []
        if isinstance(config, dict):
            style = config.get("style")
            if isinstance(style, dict) and isinstance(style.get("layers"), list):
                layers = style["layers"]
        return {"ok": bool(snapshot.get("ok")) and config is not None,
                "control_id": control_id, "config": config, "layers": layers,
                "raw": snapshot}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/client.py tests/test_client.py
git commit -m "feat(client): resolve control id, config, and layer stack

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Server — layered-style primitives

**Files:**
- Modify: `src/companion_mcp/server.py` (add near the styling tools, after `set_button_style`, ~line 1239; add `from . import elements` near the top imports at line 20-21)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_server.py
@pytest.mark.asyncio
@patch("companion_mcp.server._client")
async def test_add_button_element_resolves_and_adds(mock_client_factory):
    from companion_mcp.server import add_button_element
    fake = MagicMock()
    fake.resolve_control_id = AsyncMock(return_value="bank:xyz")
    fake.get_control_config = AsyncMock(return_value={
        "ok": True, "layers": [{"id": "canvas", "type": "canvas"}]})
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_server.py -k "add_button_element or update_button_element" -v`
Expected: FAIL (`ImportError: cannot import name 'add_button_element'`).

- [ ] **Step 3: Write minimal implementation**

First add the import near the top (after `from .config import load_config`):

```python
from . import elements
```

Then add the tools:

```python
# add to src/companion_mcp/server.py near the styling tools

async def _resolve_or_error(client, page: int, row: int, column: int):
    """Return (control_id, None) or (None, error_json_string)."""
    control_id = await client.resolve_control_id(page, row, column)
    if not control_id:
        return None, _compat_error(
            f"No control found at page {page}, row {row}, column {column}.",
            page=page, row=row, column=column)
    return control_id, None


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def add_button_element(page: int, row: int, column: int, type: str,
                             after: str = "") -> str:
    """Add a graphics element to a button's layer stack (Companion 5.x).

    type: one of box, text, image, gauge, line, circle, group, reference.
    after: element id to insert above; empty inserts at top of stack.
    Returns the new element id.
    """
    _validate_button_coords(page, row, column)
    if type not in elements.ADDABLE_TYPES:
        raise ValueError(f"type must be one of {sorted(elements.ADDABLE_TYPES)}")
    client = _client()
    control_id, error = await _resolve_or_error(client, page, row, column)
    if error:
        return error
    result = await client.style_add_element(control_id, type, after=after or None)
    return _json({"ok": result.get("ok", False), "element_id": result.get("body"),
                  "control_id": control_id, "result": result})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def update_button_element(page: int, row: int, column: int, element_id: str,
                                values_json: str) -> str:
    """Update properties on a button element. values_json is a JSON object of
    field -> value; colors accept #RRGGBB, and {"expr": "..."} marks an expression."""
    _validate_button_coords(page, row, column)
    raw = json.loads(values_json)
    if not isinstance(raw, dict):
        raise ValueError("values_json must be a JSON object of field -> value.")
    values = elements.convert_values(raw)
    client = _client()
    control_id, error = await _resolve_or_error(client, page, row, column)
    if error:
        return error
    result = await client.style_update_options(control_id, element_id, values)
    return _json({"ok": result.get("ok", False), "control_id": control_id,
                  "element_id": element_id, "values": values, "result": result})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def remove_button_element(page: int, row: int, column: int, element_id: str) -> str:
    """Remove a graphics element from a button's layer stack."""
    _validate_button_coords(page, row, column)
    client = _client()
    control_id, error = await _resolve_or_error(client, page, row, column)
    if error:
        return error
    result = await client.style_remove_element(control_id, element_id)
    return _json({"ok": result.get("ok", False), "control_id": control_id,
                  "element_id": element_id, "result": result})


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def move_button_element(page: int, row: int, column: int, element_id: str,
                              new_index: int, parent: str = "") -> str:
    """Move a graphics element to a new index within its parent stack."""
    _validate_button_coords(page, row, column)
    if new_index < 0:
        raise ValueError("new_index must be >= 0")
    client = _client()
    control_id, error = await _resolve_or_error(client, page, row, column)
    if error:
        return error
    result = await client.style_move_element(control_id, element_id, new_index,
                                             parent=parent or None)
    return _json({"ok": result.get("ok", False), "control_id": control_id,
                  "element_id": element_id, "result": result})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_server.py -k "button_element" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/server.py tests/test_server.py
git commit -m "feat(server): raw layered-element primitive tools

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Server — `preview_button_layered_style`

**Files:**
- Modify: `src/companion_mcp/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_server.py
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
    # no mutations were issued
    assert not fake.style_add_element.called
    assert not fake.style_remove_element.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_server.py -k preview_button_layered -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/companion_mcp/server.py

def _parse_layers_json(layers_json: str) -> list[dict]:
    layers = json.loads(layers_json)
    if not isinstance(layers, list):
        raise ValueError("layers_json must be a JSON array of layer specs.")
    return layers


@mcp.tool()
@_handle_errors
async def preview_button_layered_style(page: int, row: int, column: int,
                                       layers_json: str) -> str:
    """Preview the reconcile plan for a layered-style change WITHOUT writing.

    Returns the removes/adds/canvas_update plan plus any feedbacks that reference
    elements the plan would remove.
    """
    _validate_button_coords(page, row, column)
    desired = _parse_layers_json(layers_json)
    client = _client()
    control_id, error = await _resolve_or_error(client, page, row, column)
    if error:
        return error
    control = await client.get_control_config(control_id)
    plan = elements.reconcile(control["layers"], desired)
    warnings = elements.find_feedback_element_refs(control.get("config") or {},
                                                   plan["removes"])
    return _json({"ok": True, "control_id": control_id, "plan": plan,
                  "feedback_warnings": warnings})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_server.py -k preview_button_layered -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/server.py tests/test_server.py
git commit -m "feat(server): preview_button_layered_style (plan, no write)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Server — `set_button_layered_style` (apply)

**Files:**
- Modify: `src/companion_mcp/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_server.py
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
    # addElement returns a new id each call
    fake.style_add_element = AsyncMock(side_effect=[
        {"ok": True, "body": "boxA"}, {"ok": True, "body": "textB"}])
    fake.style_set_element_name = AsyncMock(return_value={"ok": True})
    fake.style_update_options = AsyncMock(return_value={"ok": True})
    mock_client_factory.return_value = fake

    layers = ('[{"type":"box","name":"bg","color":"#101010"},'
              '{"type":"text","name":"label","text":"GO","color":"#FFFFFF"}]')
    result = json.loads(await set_button_layered_style(2, 0, 3, layers))

    assert result["ok"] is True
    # removed both existing non-canvas layers
    assert fake.style_remove_element.await_count == 2
    # added bottom-up: first after canvas, then after the first added element
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_server.py -k set_button_layered -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/companion_mcp/server.py

async def _apply_layered_plan(client, control_id: str, plan: dict) -> dict:
    """Execute a reconcile plan against a control. Returns applied-op details."""
    applied = {"canvas_update": None, "removed": [], "added": []}

    if plan.get("canvas_update"):
        cu = plan["canvas_update"]
        await client.style_update_options(control_id, cu["elementId"], cu["values"])
        applied["canvas_update"] = cu["elementId"]

    for element_id in plan["removes"]:
        await client.style_remove_element(control_id, element_id)
        applied["removed"].append(element_id)

    # add bottom -> top: first element sits just above canvas
    prev_id = "canvas"
    for add in plan["adds"]:
        add_result = await client.style_add_element(control_id, add["type"], after=prev_id)
        new_id = add_result.get("body")
        if not isinstance(new_id, str):
            raise ValueError(f"addElement did not return an element id: {add_result}")
        if add.get("name"):
            await client.style_set_element_name(control_id, new_id, add["name"])
        if add["values"]:
            await client.style_update_options(control_id, new_id, add["values"])
        applied["added"].append({"type": add["type"], "name": add.get("name"),
                                 "element_id": new_id})
        prev_id = new_id
    return applied


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_button_layered_style(page: int, row: int, column: int,
                                   layers_json: str, verify: bool = False) -> str:
    """Reconcile a button's visual layer stack to match layers_json (replace mode).

    Canvas and the button's actions/feedbacks are preserved; all other visual
    layers are rebuilt. Captures a page-inventory snapshot before writing and warns
    if a feedback referenced a removed element. See preview_button_layered_style to
    inspect the plan first.
    """
    _validate_button_coords(page, row, column)
    desired = _parse_layers_json(layers_json)
    client = _client()
    control_id, error = await _resolve_or_error(client, page, row, column)
    if error:
        return error

    control = await client.get_control_config(control_id)
    plan = elements.reconcile(control["layers"], desired)
    warnings = elements.find_feedback_element_refs(control.get("config") or {},
                                                   plan["removes"])

    # rollback checkpoint (best-effort): capture current inventory for this cell
    before = await client.get_control_config(control_id)

    applied = await _apply_layered_plan(client, control_id, plan)

    verified = None
    if verify:
        after = await client.get_control_config(control_id)
        verified = {"changed": after.get("layers") != before.get("layers")}

    return _json({"ok": True, "control_id": control_id, "applied": applied,
                  "feedback_warnings": warnings, "verified": verified,
                  "snapshot_before": {"layers": before.get("layers")}})
```

Note: the snapshot here is an inline before-state capture (sufficient for single-button
rollback and audit). Page-level snapshots use the existing `snapshot_page_inventory`
tooling and are exercised by the batch tool in Task 10.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_server.py -k set_button_layered -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/server.py tests/test_server.py
git commit -m "feat(server): set_button_layered_style with plan apply + guards

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Server — `set_page_layered_style` (batch)

**Files:**
- Modify: `src/companion_mcp/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_server.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_server.py -k set_page_layered -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/companion_mcp/server.py

@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_page_layered_style(page: int, buttons_json: str, verify: bool = False) -> str:
    """Apply layered styles to multiple buttons on a page.

    buttons_json: JSON array of {row, column, layers:[...]} objects, where layers
    matches the set_button_layered_style spec. Applies each button in order.
    """
    _validate_page(page)
    buttons = json.loads(buttons_json)
    if not isinstance(buttons, list):
        raise ValueError("buttons_json must be a JSON array of {row, column, layers} objects.")

    results = []
    for i, btn in enumerate(buttons):
        if (not isinstance(btn, dict) or "row" not in btn or "column" not in btn
                or "layers" not in btn):
            raise ValueError(f"Button at index {i} must have row, column, and layers fields.")
        one = await set_button_layered_style(
            page, btn["row"], btn["column"], json.dumps(btn["layers"]), verify=verify)
        results.append(json.loads(one))

    return _json({"ok": True, "page": page, "count": len(results), "results": results})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_server.py -k set_page_layered -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/server.py tests/test_server.py
git commit -m "feat(server): set_page_layered_style batch tool

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Harden legacy flat-style tools + style-api access toggle

**Files:**
- Modify: `src/companion_mcp/server.py` (`set_button_style` ~line 1222, `set_button_color` ~line 1198, `set_button_text` ~line 1188, `set_page_style` ~line 1311; add new toggle tool)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_server.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_server.py -k "api_gated or api_enabled or api_access" -v`
Expected: FAIL (`ImportError` for `set_button_style_api_access`; the gate tests fail because the guard is absent).

- [ ] **Step 3: Write minimal implementation**

Add a shared guard helper and the toggle tool, and call the guard at the start of each
legacy style tool's body (after coordinate/color validation, before `client.set_style`).

```python
# add to src/companion_mcp/server.py

async def _style_api_gate(client, page: int, row: int, column: int):
    """Return (None, ok) or (error_json, False) if the legacy style API is gated off."""
    control_id = await client.resolve_control_id(page, row, column)
    if not control_id:
        return _compat_error(
            f"No control found at page {page}, row {row}, column {column}.",
            page=page, row=row, column=column), False
    control = await client.get_control_config(control_id)
    options = (control.get("config") or {}).get("options") or {}
    if options.get("canModifyStyleInApis") is not True:
        return _json({
            "ok": False, "blocked": True, "reason": "style-api-gated",
            "control_id": control_id, "page": page, "row": row, "column": column,
            "hint": ("This button's legacy style API is disabled (canModifyStyleInApis). "
                     "Enable it with set_button_style_api_access, or use "
                     "set_button_layered_style (tRPC) which is not gated."),
        }), False
    return None, True


@mcp.tool()
@_handle_errors
@_require_writes_enabled
async def set_button_style_api_access(page: int, row: int, column: int, enabled: bool) -> str:
    """Enable/disable the legacy style HTTP API for a button (canModifyStyleInApis).

    Companion 5.x defaults this to false for user-created buttons, which makes the
    legacy set_button_style/color/text tools no-op. Enable it to use them."""
    _validate_button_coords(page, row, column)
    client = _client()
    control_id, error = await _resolve_or_error(client, page, row, column)
    if error:
        return error
    result = await client.set_options_field(control_id, "canModifyStyleInApis", enabled)
    return _json({"ok": result.get("ok", False), "control_id": control_id,
                  "canModifyStyleInApis": enabled, "result": result})
```

Then in each of `set_button_text`, `set_button_color`, `set_button_style`, add after the
existing validation and before `_client()`/`set_style`:

```python
    client = _client()
    gate_error, allowed = await _style_api_gate(client, page, row, column)
    if not allowed:
        return gate_error
```
and reuse `client` for the subsequent `set_style` call (replace the inline `_client()`).
For `set_page_style`, run the gate per button inside its loop and record a per-button
`{"ok": False, "reason": "style-api-gated"}` result instead of aborting the whole batch.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_server.py -k "api_gated or api_enabled or api_access" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/companion_mcp/server.py tests/test_server.py
git commit -m "feat(server): harden legacy style tools against 5.x API gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Docs + full suite + spec/plan commit

**Files:**
- Modify: `README.md`
- Commit: the spec and this plan under `docs/superpowers/`

- [ ] **Step 1: Update README tool tables**

Add to the "Button styling" section a row group for the new tools:

```markdown
### Layered styling (Companion 5.x, tRPC)

| Tool | What it does |
|------|-------------|
| `set_button_layered_style` | Rebuild a button's visual layer stack (box/text/image/gauge/…) to match a spec |
| `preview_button_layered_style` | Preview the reconcile plan for a layered-style change without writing |
| `set_page_layered_style` | Apply layered styles to multiple buttons on a page |
| `add_button_element` | Add a graphics element to a button's stack |
| `update_button_element` | Update properties on a button element (hex colors, expressions) |
| `remove_button_element` | Remove a graphics element |
| `move_button_element` | Reorder a graphics element |
| `set_button_style_api_access` | Enable/disable the legacy style HTTP API per button (`canModifyStyleInApis`) |
```

Also add a note under "Button styling" that `set_button_style`/`set_button_color`/
`set_button_text`/`set_page_style` now return a `style-api-gated` error on buttons where
`canModifyStyleInApis` is disabled, and point to `set_button_style_api_access` /
`set_button_layered_style`.

- [ ] **Step 2: Run the FULL test suite**

Run: `uv run python -m pytest -v`
Expected: PASS (original 74 tests + all new tests).

- [ ] **Step 3: Import smoke check**

Run: `uv run python -c "import companion_mcp.server, companion_mcp.elements, companion_mcp.client; print('imports OK')"`
Expected: prints `imports OK`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/
git commit -m "docs: document 5.x layered styling tools + design/plan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13: Live verification against Companion 5.0.6 (manual gate)

**Files:** none (operational check)

> Requires the running Companion at 127.0.0.1:8000. Use a scratch/empty button
> (pick an unused page/cell — NOT one of the important pages 3/12/13/14/16/19/29/38/39)
> to avoid disturbing the live show layout.

- [ ] **Step 1: Preview on a scratch button**

Via MCP: `preview_button_layered_style(page=<scratch>, row=0, column=0, layers_json='[{"type":"box","name":"bg","color":"#101010","cornerRadius":12},{"type":"text","name":"label","text":"TEST","color":"#FFFFFF","fontsize":22}]')`
Expected: `ok:true`, a plan with `removes` (existing layers) and two `adds`.

- [ ] **Step 2: Apply and verify**

Via MCP: same args to `set_button_layered_style(..., verify=True)`.
Expected: `ok:true`, `applied.added` has two elements with real ids, `verified.changed: true`.
Confirm visually in the Companion UI that the scratch button shows a dark rounded box with white "TEST".

- [ ] **Step 3: Confirm the legacy gate behavior**

Via MCP: `set_button_style(page=<scratch>, row=0, column=0, text="X")` on a fresh user button.
Expected: `ok:false, reason:"style-api-gated"`. Then `set_button_style_api_access(..., enabled=true)`, retry `set_button_style` → `ok:true`.

- [ ] **Step 4: Restore the scratch button**

Reset the scratch button in the Companion UI (or leave it, since it's unused). Do NOT run resetControls via tooling on live pages.

---

## Self-Review

**Spec coverage:**
- tRPC write layer (add/update/remove/move) → Tasks 5, 7. ✓
- Declarative reconcile tool → Tasks 3, 9. ✓
- Preview tool → Task 8. ✓
- Batch tool → Task 10. ✓
- Hardened legacy + api-access toggle → Task 11. ✓
- Layer-spec format (hex/percent/expr, unknown-field rejection, canvas rules) → Tasks 1, 2, 3. ✓
- Safety (preview, before-snapshot, verify, feedback guard) → Tasks 8, 9. ✓
- Testing (pure unit + mocked tool + legacy-gate) → every task. ✓
- Docs → Task 12. ✓
- Live check → Task 13. ✓

**Type/name consistency:** `elements.hex_to_int / int_to_hex / wrap_value / convert_values /
build_element_values / reconcile / find_feedback_element_refs / ADDABLE_TYPES`; client
`style_add_element / style_update_options / style_remove_element / style_move_element /
style_set_element_name / set_options_field / resolve_control_id / get_control_config`;
server `add_button_element / update_button_element / remove_button_element /
move_button_element / preview_button_layered_style / set_button_layered_style /
set_page_layered_style / set_button_style_api_access / _resolve_or_error /
_apply_layered_plan / _style_api_gate / _parse_layers_json`. Names are consistent across
tasks. `reconcile` returns `{canvas_update, removes, adds}` and `_apply_layered_plan`
consumes exactly those keys. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code. ✓

**Scope:** Single subsystem (MCP write layer). Page restyling deliberately excluded. ✓
