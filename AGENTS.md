# AGENTS.md

## Project

- Product: `companion-mcp`
- Domain: Bitfocus Companion control and browser UI
- Protocols: HTTP and WebSocket
- Main entrypoints:
- `uv run python -m companion_mcp.server`
- `uv run python -m companion_mcp.ui`

## Core Rules

- Keep verified write flows explicit. Do not weaken safety checks for button/style writes.
- Preserve the lightweight local UI architecture.
- Keep protocol and UI concerns separated within `src/companion_mcp/`.
- Add tests for behavior changes, especially write verification and snapshot flows.

## Key Commands

```bash
uv sync
uv run python -m pytest -v
uv run python -m companion_mcp.server
uv run python -m companion_mcp.ui
```

## Key Paths

- `src/companion_mcp/server.py`: MCP server
- `src/companion_mcp/ui.py`: browser UI
- `src/companion_mcp/`: API and workflow logic
- `tests/`: verification

## When Editing

- Preserve rollback/restore semantics.
- Keep UI changes consistent with the existing product direction unless the task explicitly changes it.
