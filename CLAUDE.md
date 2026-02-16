# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Windows-only overlay manager system that provides click-through overlay windows (highlights, countdowns, timers, QR codes) via a named pipe IPC mechanism. The system uses a client-server architecture where:
- **OverlayManager** (server) creates and manages overlay windows using Win32 APIs
- **OverlayClient** (client) sends commands to the manager over a named pipe

The project requires Python 3.10+ and is Windows-specific (uses pywin32).

## Development Commands

### Setup and Dependencies
```bash
# Install dependencies using uv
uv sync

# Install dev dependencies
uv sync --group dev
```

### Running the Application
```bash
# Run the overlay manager (default pipe name)
uvx overlays

# Run with custom pipe name via environment variable
$env:OVERLAY_PIPE_NAME="custom_pipe"
uvx overlays
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/manager/test_manager.py

# Run specific test function
uv run pytest tests/manager/test_manager.py::test_add_highlight_window

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

**OverlayManager** (`src/overlays/manager.py`): The main server component that:
- Creates a full-screen transparent, click-through window using Win32 layered window APIs
- Runs 4 concurrent threads:
  1. Window message pump (`_init_window_and_pump`)
  2. Named pipe server (`_run_pipe_server`)
  3. Command processing queue (`_run_command_thread`)
  4. Countdown/elapsed time updater (`_run_countdown_manager`)
- Maintains state for rectangles (highlights), countdowns, and QR codes
- Uses `win32gui.InvalidateRect()` to trigger redraws via WM_PAINT

**OverlayClient** (`src/overlays/client.py`): The client library that:
- Connects to the named pipe server
- Gracefully handles server unavailability (fails silently)
- Provides methods like `create_highlight_window()`, `create_countdown_window()`, etc.
- Returns window IDs that can be used to update/close windows
- Includes `get_overlay_client()` singleton helper for reusing connections

**Command Pattern**: Commands are implemented as classes (`CreateHighlightCommand`, `CreateCountdownCommand`, etc.) in `manager.py` that execute operations and put responses on reply queues.

**Drawing Helpers** (`src/overlays/helpers.py`): Contains Win32 GDI drawing functions for rendering rectangles, countdown boxes, and QR codes onto the HDC (device context).

### Named Pipe Communication

- Pipe name is configurable via `OVERLAY_PIPE_NAME` environment variable (default: "overlay_manager")
- Full pipe path format: `\\.\pipe\{OVERLAY_PIPE_NAME}`
- Client sends JSON commands with structure: `{"command": "create_highlight", "args": {...}}`
- Server responds with JSON: `{"status": "success", "window_id": 1}` or error messages
- Communication is synchronous (client waits for response)

### Window Management

The overlay uses a single full-screen window with these properties:
- `WS_EX_LAYERED`: Supports transparency via color key
- `WS_EX_TRANSPARENT`: Click-through behavior
- `WS_EX_TOPMOST`: Always on top
- `WS_EX_TOOLWINDOW`: Hidden from taskbar
- Transparency key: magenta RGB(255, 0, 255)

All overlays (highlights, countdowns, QR codes) are drawn onto this single window. The window redraws on `WM_PAINT` messages triggered by `InvalidateRect()`.

### Break Mode

The manager supports "break mode" where incoming commands are queued instead of executed:
- `take_break(duration_seconds)`: Holds commands for specified duration
- `cancel_break()`: Immediately discards pending commands and resumes normal operation
- Break commands (`take_break`, `cancel_break`) bypass the queue

## Testing Patterns

Tests use `pytest` with heavy use of `monkeypatch` to mock Win32 APIs and threading:
- Mock `threading.Timer` to prevent actual timers from running
- Mock `win32gui` functions like `InvalidateRect`, `PumpMessages`
- Stub `_run_pipe_server`, `_run_command_thread`, `_init_window_and_pump` for unit testing
- Use `time.time()` mocking to control countdown/elapsed time tests
- See `tests/manager/test_manager.py::patch_timer_and_threads` fixture for common setup

When writing tests:
- Use autouse fixtures to mock Win32 functions globally
- Mock `time.time()` with a list to simulate time progression
- Create `NoopTimer` classes to disable threading.Timer behavior
- Test window lifetime by checking presence/absence in manager's state dicts

## Thread Safety

The OverlayManager has shared mutable state (`rectangles`, `countdowns`, `qrcodes`, ID counters, order counters) accessed from multiple threads without explicit locking. Under testing with `sys.setswitchinterval(1e-6)` and 8 concurrent threads, the `_countdown_order += 1` increment was proven non-atomic (3166 duplicate order values out of 16000 operations).

However, **this is not a practical bug** because the architecture serializes all state mutations through `_run_command_thread` (a single queue consumer). The only cross-thread access patterns in production are:
- **Thread 3 (command)** writes to state dicts
- **Thread 4 (countdown manager)** iterates + mutates `countdowns`
- **Thread 1 (paint/WM_PAINT)** reads all three dicts
- **Timer callbacks** call `_remove_rectangle` and `remove_qrcode_window`

CPython's GIL makes individual dict/list operations atomic enough that these don't crash. If the architecture ever changes to process commands in parallel or call mutation methods from multiple threads, a `threading.Lock` should be added to protect shared state.

## Important Notes

- **Windows-only**: Code checks `platform.system() != "Windows"` and exits with error
- **Entry point**: `main.cross_platform_helper()` is the CLI entry point
- **Window IDs**: Auto-incrementing integers tracked separately for rectangles, countdowns, and QR codes
- **Order tracking**: Countdowns and QR codes maintain an `order` field for consistent vertical positioning
- **Graceful shutdown**: Handles SIGINT/SIGTERM by cleaning up threads and posting WM_CLOSE
- **Error handling**: Pipe errors (ERROR_BROKEN_PIPE=109, ERROR_NO_DATA=232) are expected during client disconnects

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
