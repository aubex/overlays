# overlays

A lightweight Windows overlay manager and client library for creating interactive overlay windows: highlights, countdowns, elapsed timers, and QR codes, all communicated over a named pipe. This project is licensed under the Apache License 2.0. See the LICENSE file for details.

![OverlayManager in action](static/stress_test.gif)

## Features

* **Highlight Windows**: Draw colored rectangles around screen regions for attention-grabbing highlights.
* **Countdown Timers**: Display a countdown clock with a custom message.
* **Elapsed Time Windows**: Track and display elapsed time since creation.
* **QR Code Overlays**: Render QR codes with captions in an always-on-top window.
* **Named-Pipe IPC**: Send commands from your application to the overlay manager via a simple pipe.
* **Graceful Shutdown**: Press `Ctrl+C` or send `SIGTERM` to clean up windows and threads.

## Requirements

* Windows 10 or later
* Python 3.10+
* Dependencies: `pywin32`, `qrcode`

## Getting Started

### 1. Run the Overlay Manager

The overlay manager hosts a named-pipe server and listens for overlay commands. \
To run the manager, simply use the following [uv](https://docs.astral.sh/uv/) command:

```bash
uv run main.py
```

You should see the following output:

```
🔧 OverlayManager - Windows Overlay Application
================================================
✅ Signal handlers configured
🚀 Starting OverlayManager...
✅ OverlayManager initialized successfully
📡 Named pipe server: \\.\pipe\overlay_manager
🎯 Application ready - overlay windows can now be created
💡 Press Ctrl+C to shutdown gracefully
```

### 2. Embed the OverlayClient in Your Code

Import and instantiate the `OverlayClient` to send overlay commands:

```python
from overlay_client import OverlayClient

# Create one client to connect to the manager's pipe
overlay = OverlayClient(pipe_name=r"\\.\pipe\overlay_manager")

# Create a highlight window
overlay.create_highlight_window(rect=(100, 100, 400, 300), timeout_seconds=5)

# Create a 10-second countdown
overlay.create_countdown_window(message_text="Get ready!", countdown_seconds=10)

# Create an elapsed-time window
overlay.create_elapsed_time_window(message_text="Session Length")

# Show a QR code for some data
overlay.create_qrcode_window(data={"url": "https://example.com"}, duration=15, caption="Scan me")

# Update a window's message
overlay.update_window_message(window_id=2, new_message="Halfway there...")

# Close a specific window
overlay.close_window(window_id=1)

# Take and cancel breaks
overlay.take_break(duration_seconds=60)
overlay.cancel_break()
```

## IPC Commands Reference

| Command                 | Args                                          | Description                                     |
| ----------------------- | --------------------------------------------- | ----------------------------------------------- |
| `create_highlight_window`      | `rect: (l, t, r, b)`, `timeout_seconds: int`  | Shows a colored rectangle for a duration.       |
| `create_countdown_window`      | `message_text: str`, `countdown_seconds: int` | Starts a countdown timer.                       |
| `create_elapsed_time_window`   | `message_text: str`                           | Displays elapsed time since creation.           |
| `create_qrcode_window`  | `data: str \| dict`, `duration: int`, `caption: str`         | Renders a QR code overlay. |
| `update_window_message` | `window_id: int`, `new_message: str`          | Changes the text of a countdown/elapsed window. |
| `close_window`          | `window_id: int`                              | Closes a countdown or elapsed window.           |
| `take_break`            | `duration_seconds: int`                       | Holds incoming commands for a break period.     |
| `cancel_break`          | *(none)*                                      | Cancels any active break and flushes queue.     |

## Graceful Shutdown

Press `Ctrl+C` in the console running `main.py`, or send a `SIGTERM` signal. The manager will clean up all open windows and exit.

## Contributing
Contributions are always welcome! \
The following steps should be used:

1. Fork the repo.
2. Create a feature branch.
3. Submit a pull request—happy to review improvements!
