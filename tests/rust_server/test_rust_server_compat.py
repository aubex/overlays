from __future__ import annotations

import os
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pywintypes
import pytest
import win32pipe

from overlays.client import OverlayClient


def resolve_server_binary() -> Path:
    configured = os.environ.get("OVERLAYS_SERVER_BIN")
    if configured:
        candidate = Path(configured)
        if candidate.exists():
            return candidate
        pytest.skip(f"OVERLAYS_SERVER_BIN does not exist: {candidate}")

    candidate = (
        Path(__file__).resolve().parents[2]
        / "rust"
        / "overlays-server"
        / "target"
        / "debug"
        / "overlays-server.exe"
    )
    if candidate.exists():
        return candidate

    pytest.skip("Rust overlay server binary not available")


@contextmanager
def running_server(pipe_name: str):
    binary = resolve_server_binary()
    env = os.environ.copy()
    env["OVERLAY_PIPE_NAME"] = pipe_name

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(binary)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    try:
        wait_for_pipe(pipe_name)
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_for_pipe(pipe_name: str, timeout_seconds: float = 10.0) -> None:
    pipe_path = rf"\\.\pipe\{pipe_name}"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            win32pipe.WaitNamedPipe(pipe_path, 100)
            return
        except pywintypes.error:
            time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {pipe_path}")


def test_rust_server_matches_basic_command_contract(monkeypatch):
    pipe_name = f"overlay_manager_pytest_{uuid.uuid4().hex}"
    with running_server(pipe_name):
        monkeypatch.setenv("OVERLAY_PIPE_NAME", pipe_name)
        client = OverlayClient(timeout=2000)
        assert client.is_available()

        created = client._send_command(
            "create_countdown",
            {"message_text": "hello", "countdown_seconds": 5},
        )
        assert created == {"status": "success", "window_id": 1}

        updated = client._send_command(
            "update_window_message",
            {"window_id": 1, "new_message": "updated"},
        )
        assert updated == {"status": "success", "message": "Window 1 updated"}

        closed = client._send_command("close_window", {"window_id": 1})
        assert closed == {"status": "success", "message": "Window 1 closed"}

        missing_rect = client._send_command("create_highlight", {})
        assert missing_rect == {
            "status": "error",
            "message": "Command 'create_highlight' failed: internal error",
        }

        client.disconnect()


def test_rust_server_supports_breaks_and_parallel_clients(monkeypatch):
    pipe_name = f"overlay_manager_pytest_{uuid.uuid4().hex}"
    with running_server(pipe_name):
        monkeypatch.setenv("OVERLAY_PIPE_NAME", pipe_name)
        client_one = OverlayClient(timeout=2000)
        client_two = OverlayClient(timeout=2000)

        assert client_one.is_available()
        assert client_two.is_available()

        created = client_two._send_command(
            "create_elapsed_time",
            {"message_text": "parallel"},
        )
        assert created == {"status": "success", "window_id": 1}

        started = client_one._send_command("take_break", {"duration_seconds": 30})
        assert started == {
            "status": "success",
            "message": "Break started for 30 seconds",
        }

        ignored = client_two._send_command(
            "create_countdown",
            {"message_text": "discard", "countdown_seconds": 3},
        )
        assert ignored == {
            "status": "ignored",
            "reason": "break_active",
            "message": "Command discarded during break",
        }

        canceled = client_one._send_command("cancel_break")
        assert canceled == {"status": "success", "message": "Break canceled"}

        created_after_cancel = client_two._send_command(
            "create_countdown",
            {"message_text": "after cancel", "countdown_seconds": 3},
        )
        assert created_after_cancel == {"status": "success", "window_id": 2}

        client_one.disconnect()
        client_two.disconnect()


def test_rust_server_close_all_clears_windows(monkeypatch):
    pipe_name = f"overlay_manager_pytest_{uuid.uuid4().hex}"
    with running_server(pipe_name):
        monkeypatch.setenv("OVERLAY_PIPE_NAME", pipe_name)
        client = OverlayClient(timeout=2000)
        assert client.is_available()

        created_cd = client._send_command(
            "create_countdown",
            {"message_text": "cd", "countdown_seconds": 30},
        )
        assert created_cd["status"] == "success"

        created_et = client._send_command(
            "create_elapsed_time",
            {"message_text": "et"},
        )
        assert created_et["status"] == "success"

        closed_all = client._send_command("close_all")
        assert closed_all == {"status": "success", "message": "Closed 2 windows"}

        # Verify both windows are gone
        close_first = client._send_command(
            "close_window", {"window_id": created_cd["window_id"]}
        )
        assert close_first["status"] == "error"

        close_second = client._send_command(
            "close_window", {"window_id": created_et["window_id"]}
        )
        assert close_second["status"] == "error"

        client.disconnect()
