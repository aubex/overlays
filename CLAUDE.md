# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Windows-only overlay manager system that provides click-through overlay windows (highlights, countdowns, timers, QR codes) via a named pipe IPC mechanism. The system uses a client-server architecture where:
- **Rust server** (`rust/overlays-server`) creates and manages overlay windows using Win32 APIs
- **OverlayClient** (`src/overlays/client.py`) sends commands to the server over a named pipe

The Python package is client-only. The old Python server implementation has been removed. The project is Windows-specific.

## Development Commands

### Setup and Dependencies
```bash
# Install dependencies using uv
uv sync

# Install dev dependencies
uv sync --group dev

# Build the Rust server
cargo build --manifest-path rust/overlays-server/Cargo.toml
```

### Running the Application
```bash
# Run the Rust overlay server (default pipe name)
cargo run --manifest-path rust/overlays-server/Cargo.toml

# Run with custom pipe name via environment variable
$env:OVERLAY_PIPE_NAME="custom_pipe"
cargo run --manifest-path rust/overlays-server/Cargo.toml
```

### Testing
```bash
# Run all tests
uv run pytest

# Run Rust tests
cargo test --manifest-path rust/overlays-server/Cargo.toml

# Run Python client compatibility tests against the built Rust binary
uv run pytest tests/rust_server/test_rust_server_compat.py

# Run with verbose output
uv run pytest -v
```

### Linting and Formatting
```bash
# Run ruff linter
uv run ruff check

# Auto-fix linting issues
uv run ruff check --fix

# Format code
uv run ruff format
```

## Architecture

### Core Components

**Rust server** (`rust/overlays-server/src`): The authoritative server implementation that:
- Creates the transparent overlay window and owns render state
- Accepts named-pipe clients concurrently
- Preserves the existing JSON command protocol used by the Python client
- Exposes an executable named `overlays-server.exe`

**OverlayClient** (`src/overlays/client.py`): The client library that:
- Connects to the named pipe server
- Gracefully handles server unavailability (fails silently)
- Provides methods like `create_highlight_window()`, `create_countdown_window()`, etc.
- Returns window IDs that can be used to update/close windows
- Includes `get_overlay_client()` singleton helper for reusing connections

### Named Pipe Communication

- Pipe name is configurable via `OVERLAY_PIPE_NAME` environment variable (default: "overlay_manager")
- Full pipe path format: `\\.\pipe\{OVERLAY_PIPE_NAME}`
- Client sends JSON commands with structure: `{"command": "create_highlight", "args": {...}}`
- Server responds with JSON: `{"status": "success", "window_id": 1}` or error messages
- Communication is synchronous from the Python client's perspective

### Rust Server Layout

- `rust/overlays-server/src/ipc.rs`: named-pipe listener and request handling
- `rust/overlays-server/src/state.rs`: overlay state and command execution
- `rust/overlays-server/src/ui.rs`: Win32 window lifecycle and painting
- `rust/overlays-server/src/render.rs`: overlay drawing primitives
- `rust/overlays-server/src/protocol.rs`: request and response types

## Testing Patterns

Python tests focus on client behavior and client-to-server compatibility:
- `tests/client/test_client.py`: unit tests for the Python client API
- `tests/rust_server/test_rust_server_compat.py`: boots the Rust server binary and verifies protocol compatibility through the Python client

Rust tests cover server behavior directly:
- `rust/overlays-server/tests/server_integration.rs`

## Important Notes

- **Windows-only**: both the client and server depend on Win32 APIs
- **Server executable**: build `rust/overlays-server`
- **Compatibility target**: keep the Python client protocol stable unless the change is intentional across both stacks
- **Graceful shutdown**: stop the Rust server with `Ctrl+C`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OVERLAY_PIPE_NAME` | `overlay_manager` | Named pipe identifier (without `\\.\pipe\` prefix) |

## IPC Commands

| Command | Args | Returns |
|---------|------|---------|
| `create_highlight` | `rect: [l, t, r, b]`, `timeout_seconds: int` | `window_id` |
| `create_countdown` | `message_text: str`, `countdown_seconds: int` | `window_id` |
| `create_elapsed_time` | `message_text: str` | `window_id` |
| `create_qrcode_window` | `data: str\|dict`, `duration: int`, `caption: str` | `window_id` |
| `close_window` | `window_id: int` | success message |
| `update_window_message` | `window_id: int`, `new_message: str` | success message |
| `take_break` | `duration_seconds: int` | success message |
| `cancel_break` | *(none)* | success message |
