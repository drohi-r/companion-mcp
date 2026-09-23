# Companion MCP — 5.0 Layered Styling Write Layer

**Date:** 2026-09-23
**Status:** Approved design (pending written-spec review)
**Target Companion version:** 5.0.6 (validated live); API present since 5.0

## Problem

The `companion-mcp` server writes button styles only through Companion's legacy
HTTP style API (`POST /api/location/{page}/{row}/{column}/style?...`), which
accepts just the flat properties `text`, `color`, `bgcolor`, `size`. Two gaps
result on Companion 5.x:

1. **No access to the 5.0 layered styling model.** In 5.x a button is a stack of
   graphics elements (canvas / box / image / text / gauge / line / circle / group /
   reference), each positioned by percentage, with gradients (gauges), borders,
   corner radius, rotation, and expressions on every property. None of this is
   reachable through the legacy flat endpoint.
2. **The legacy write path can silently no-op.** In 5.x the HTTP `/style` endpoint
   is gated per button by the `canModifyStyleInApis` option, which **defaults to
   `false` for user-created buttons**. The MCP's `set_button_style`,
   `set_button_color`, and `set_page_style` tools therefore may be accepted by the
   API yet change nothing on the user's existing buttons.

All of the MCP's **read** paths were validated working against live 5.0.6
(`appInfo.version`, `surfaces.watchSurfaces`, `pages.watch`, `controls.watchControl`),
as were its HTTP action/variable/rescan endpoints. The gap is exclusively in the
**style-write** path.

## Goal

Add a write layer that targets Companion 5.x's **tRPC `controls.styles.*`
mutations** (the modern, correct styling path, gated only by `supportsLayeredStyle`
— which every existing button satisfies — and **not** by `canModifyStyleInApis`),
and harden the legacy flat-style tools so they never silently no-op.

Out of scope for this spec: the actual restyling of the user's pages
(3, 12, 13, 14, 16, 19, 29, 38, 39). That is a separate follow-on cycle that will
*use* the tools built here.

## Confirmed API facts (from `bitfocus/companion` source + live 5.0.6 reads)

- **Transport:** tRPC over WebSocket at `ws://host:port/trpc`. Writes are ordinary
  tRPC calls with `method: "mutation"`, `params: { path, input }`. The MCP's
  existing `client.trpc_call()` already supports arbitrary methods.
- **Auth:** none. The `/trpc` endpoint has no authentication. A non-browser client
  sends no `Origin` header and passes the anti-hijacking check; loopback host must
  stay loopback (we connect to 127.0.0.1, so this holds).
- **Target identity:** `controls.styles.*` mutations identify the button by
  `controlId` (string, form `bank:<uuid>`), **not** by grid location. Resolve it
  from `pages.watch`: `pages[pageId].controls[row][column]`. The MCP already reads
  this snapshot.
- **Mutations (all under `controls.styles.`):**
  - `addElement { controlId, type, afterElementId: string|null }` → returns new element id;
    inserts above `afterElementId`, or top-of-stack when `null`.
  - `updateOptions { controlId, elementId, values: Record<string, ExpressionOrValue> }` (batched; preferred).
  - `updateOption { controlId, elementId, key, value: ExpressionOrValue }` (single).
  - `removeElement { controlId, elementId }`.
  - `moveElement { controlId, elementId, parentElementId: string|null, newIndex: number }`.
  - `setElementName { controlId, elementId, name }`.
- **`ExpressionOrValue<T>`** wraps every settable property:
  `{ value: T, isExpression: false }` (literal) or
  `{ value: string, isExpression: true }` (Companion expression string).
  `updateOptions` refuses structural keys: `id, type, name, usage, pinnedProperties,
  children, connectionId, elementId`.
- **Element types for `addElement`:** `text | image | box | line | circle | group |
  gauge | reference`. `canvas` is the fixed bottom element — not addable/removable;
  only its `decoration` and `showStatusIcons` are editable.
- **Coordinates** (`x, y, width, height`) are **percentages 0–100**.
- **Colors** stored as integers (`0xRRGGBB` or `0xAARRGGBB`); CSS strings also accepted.
- **No single "set whole style" mutation.** Build/replace incrementally via
  add/update/remove/move. `controls.resetControls` exists but clears the **entire
  control including actions/feedbacks**, so it MUST NOT be used for restyle.
- **Actions / steps / feedbacks are separate** from the visual layer stack
  (`entities` / `actionSets` / `steps`), so restyling never alters what a button does.
- **Legacy flat style** (`text/size/color/bgcolor/alignment/png64`) is NOT exposed
  over tRPC; it is only settable via the HTTP REST API, gated by
  `canModifyStyleInApis`. That option is flipped via `controls.setOptionsField`.

## Architecture

Structure chosen (option B): a dedicated, network-free styling module keeps the
already-large `server.py` and the transport-only `client.py` thin, and makes the
reconciler independently unit-testable.

```
src/companion_mcp/
  client.py    → + trpc_mutation() helper (method:"mutation");
                 + controls_styles_add/update/remove/move element methods;
                 + resolve_control_id(page,row,column) via pages.watch;
                 + set_options_field() for canModifyStyleInApis.
  elements.py  → NEW. Pure logic, no I/O:
                 • LayerSpec parsing + validation (type, %-bounds, hex, expr, fields)
                 • hex <-> int color conversion
                 • value wrapping: literal -> {value,isExpression:false};
                   {"expr":"..."} -> {value:"...",isExpression:true}
                 • per-type field maps (text/box/image/gauge/line/circle)
                 • reconcile(current_layers, desired_specs) -> ordered mutation plan
  server.py    → + declarative tool, primitives, preview, batch,
                 + hardened legacy tools + style-api-access toggle.
```

The **reconciler is a pure function**: `(current stack, desired specs) → ordered
list of {op, args}` mutations. Replace mode = remove existing non-canvas elements,
then add spec layers in order and `updateOptions` each. Canvas is always preserved.
Element ordering is achieved by adding in stack order (and `moveElement` only if a
correction is needed). No network in `elements.py`.

## Tools

### New — layered styling (tRPC)
- `set_button_layered_style(page, row, column, layers_json, verify=False)` —
  reconcile the button's visual stack to match `layers_json` (replace mode).
  Captures a pre-write inventory snapshot; returns the applied mutation plan,
  any feedback-orphan warnings, and (if `verify`) a render-change check.
- `preview_button_layered_style(page, row, column, layers_json)` — return the
  reconcile plan with **no** mutation.
- `set_page_layered_style(page, buttons_json, verify=False)` — batch across a page;
  returns per-button plans/results plus an inventory diff.

### New — primitives (raw tRPC 1:1)
- `add_button_element(page, row, column, type, after=None)` → element id
- `update_button_element(page, row, column, element_id, values_json)`
- `remove_button_element(page, row, column, element_id)`
- `move_button_element(page, row, column, element_id, new_index, parent=None)`

### Hardened — legacy flat style (the silent-no-op fix)
- `set_button_style`, `set_button_color`, `set_page_style` gain a
  `canModifyStyleInApis` pre-check. If the gate is off, return a structured error
  `{ ok:false, blocked:true, reason:"style-api-gated", hint:"enable via
  set_button_style_api_access, or use set_button_layered_style" }` instead of
  reporting a hollow success.
- `set_button_style_api_access(page, row, column, enabled)` — flip
  `canModifyStyleInApis` via `controls.setOptionsField`.

## Layer-spec format (`layers_json`)

Human-friendly JSON array, translated by `elements.py`:

```jsonc
[
  {"type":"box",  "name":"bg",     "color":"#101010", "cornerRadius":12},
  {"type":"box",  "name":"accent", "y":86, "height":14, "color":"#00CC00"},
  {"type":"text", "name":"label",  "text":"START", "color":"#FFFFFF",
                  "fontsize":22, "valign":"center"},
  {"type":"gauge","name":"ring",   "orientation":"ring",
                  "value":{"expr":"$(internal:time_s)"}, "min":0, "max":60}
]
```

Translator rules (all violations raise structured errors, never silent drops):
- Colors accept `#RRGGBB` / `#AARRGGBB` (or CSS string) → stored int; reads convert back to hex.
- `x/y/width/height` are percentages 0–100 (bounds-validated).
- Any field value may be `{"expr":"<companion expression>"}` → `isExpression:true`;
  otherwise treated as a literal.
- Unknown fields for the element's type are rejected with a clear message.
- `canvas` is never addable/removable; a spec entry for it only tweaks
  `decoration` / `showStatusIcons`.

## Safety model (reuses existing repo mechanisms)

- New write tools honor `COMPANION_WRITE_ENABLED` and the host allowlist
  (`@_require_writes_enabled` + existing coord/validation helpers).
- **Preview:** `preview_button_layered_style` shows the plan without writing.
- **Snapshot/rollback:** layered writes capture a page-inventory checkpoint first,
  so the existing restore/rollback tools apply.
- **Verified writes:** optional `verify=True` polls the preview hash
  (reuse `verify_button_render_change`) to confirm the render changed.
- **Feedback guard:** before removing an element in replace mode, inspect the
  button's feedbacks; if any target a removed element, include a warning in the
  result rather than silently orphaning the feedback.
- **Error isolation:** all tools keep the existing `_handle_errors` wrapper and
  structured `{ok:false,...}` returns.

## Testing (TDD, mirrors existing mocked-client suite)

- **`elements.py` unit tests (no network):** hex⇄int; %-bounds validation;
  expr-wrapping; unknown-field rejection; reconciler produces the expected ordered
  mutation plan for representative before-stacks + specs (add-only, replace,
  reorder, canvas-only tweak).
- **Tool tests (mocked tRPC client):** assert the correct mutations are issued in
  order for declarative + each primitive; snapshot captured before write; verify
  path polls preview.
- **Legacy-hardening tests:** gated button → `blocked` structured error;
  `set_button_style_api_access` toggles the flag; ungated button still writes.
- Run via `uv run python -m pytest`.

## Non-goals / YAGNI

- No `merge` reconcile mode (replace only, per decision); can be added later if a
  concrete need appears.
- No `group`/`reference` composition helpers in the declarative tool beyond passing
  them through the primitives.
- No page-restyling content — that is the follow-on cycle.
```
