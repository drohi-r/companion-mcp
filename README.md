<p align="center">
  <img src="assets/banner.svg" alt="Companion MCP" width="100%">
</p>

# Companion MCP

<p align="center">
  <a href="https://github.com/drohi-r/companion-mcp/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-orange?style=for-the-badge" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-blue?style=for-the-badge" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/MCP_Tools-18-14B8A6?style=for-the-badge" alt="18 MCP Tools">
</p>

An MCP server for [Bitfocus Companion](https://bitfocus.io/companion). Exposes button control, styling, variable access, discovery reads, and batch show programming — so AI assistants can operate Stream Deck surfaces and other Companion-connected devices via the HTTP API.

Built for live production. Pairs with [MA2 Agent](https://github.com/drohi-r/grandma2-mcp), [Resolume MCP](https://github.com/drohi-r/resolume-mcp), and [Beyond MCP](https://github.com/drohi-r/beyond-mcp) for full AI-driven show control.

## Quick start

```bash
git clone https://github.com/drohi-r/companion-mcp && cd companion-mcp
uv sync
uv run python -m companion_mcp
```

Make sure Companion is running with the HTTP API enabled (default port 8000).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `COMPANION_HOST` | `127.0.0.1` | Companion instance IP |
| `COMPANION_PORT` | `8000` | HTTP API port |
| `COMPANION_TIMEOUT_S` | `10.0` | HTTP timeout in seconds |
| `COMPANION_TRANSPORT` | `stdio` | MCP transport (`stdio`, `sse`, `streamable-http`) |

## Tools

### Button actions
| Tool | What it does |
|------|-------------|
| `press_button` | Press and release a button |
| `hold_button` | Press and hold (down actions only) |
| `release_button` | Release a held button (up actions) |
| `rotate_left` | Rotate encoder left |
| `rotate_right` | Rotate encoder right |
| `set_step` | Set the current action step |

### Button styling
| Tool | What it does |
|------|-------------|
| `set_button_text` | Change button display text |
| `set_button_color` | Change text and/or background color |
| `set_button_style` | Set multiple style properties at once |

### Variables
| Tool | What it does |
|------|-------------|
| `get_custom_variable` | Read a Companion custom variable |
| `set_custom_variable` | Write a Companion custom variable |
| `get_module_variable` | Read a variable from a Companion module connection |

### Discovery / health
| Tool | What it does |
|------|-------------|
| `health_check` | Probe Companion API reachability and return status details |
| `list_surfaces` | List connected control surfaces |
| `get_button_info` | Read raw API payload for a specific button location |

### Batch operations
| Tool | What it does |
|------|-------------|
| `press_button_sequence` | Press multiple buttons in order with delay |
| `set_page_style` | Batch-set style on multiple buttons |
| `label_button_grid` | Label a grid of buttons from a flat list |

### System
| Tool | What it does |
|------|-------------|
| `get_server_config` | Return current MCP server config |
| `rescan_surfaces` | Rescan USB surfaces |
| `press_bank_button` | Legacy bank API (deprecated, still works) |

## Claude Desktop

```json
{
  "mcpServers": {
    "companion": {
      "command": "uv",
      "args": ["run", "python", "-m", "companion_mcp"],
      "env": {
        "COMPANION_HOST": "127.0.0.1",
        "COMPANION_PORT": "8000"
      }
    }
  }
}
```

## VS Code / Cursor

```json
{
  "servers": {
    "companion": {
      "command": "uv",
      "args": ["run", "python", "-m", "companion_mcp"],
      "env": {
        "COMPANION_HOST": "127.0.0.1",
        "COMPANION_PORT": "8000"
      }
    }
  }
}
```

## Development

```bash
uv sync
uv run python -m pytest -v
```

## License

[Apache 2.0](LICENSE)
