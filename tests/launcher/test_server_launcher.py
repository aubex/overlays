from __future__ import annotations

import pytest

from overlays import _server_launcher


def test_bundled_server_path_resolves_packaged_executable(monkeypatch, tmp_path):
    executable = tmp_path / "overlays-server.exe"
    executable.write_bytes(b"binary")
    monkeypatch.setattr(_server_launcher.resources, "files", lambda package: tmp_path)

    with _server_launcher.bundled_server_path() as bundled:
        assert bundled == executable


def test_main_propagates_environment_and_invokes_executable(monkeypatch, tmp_path):
    executable = tmp_path / "overlays-server.exe"
    executable.write_bytes(b"binary")
    monkeypatch.setattr(_server_launcher.resources, "files", lambda package: tmp_path)
    monkeypatch.setenv("OVERLAY_PIPE_NAME", "packaged_pipe")

    captured: dict[str, object] = {}

    class Process:
        def wait(self, timeout=None):
            captured["timeout"] = timeout
            return 0

    def fake_popen(command: list[str], *, env: dict[str, str]):
        captured["command"] = command
        captured["env"] = env
        return Process()

    monkeypatch.setattr(_server_launcher.subprocess, "Popen", fake_popen)

    assert _server_launcher.main() == 0
    assert captured["command"] == [str(executable)]
    assert captured["env"]["OVERLAY_PIPE_NAME"] == "packaged_pipe"
    assert captured["timeout"] is None


def test_main_returns_child_exit_code(monkeypatch, tmp_path):
    executable = tmp_path / "overlays-server.exe"
    executable.write_bytes(b"binary")
    monkeypatch.setattr(_server_launcher.resources, "files", lambda package: tmp_path)

    class Process:
        def wait(self, timeout=None):
            return 23

    monkeypatch.setattr(
        _server_launcher.subprocess,
        "Popen",
        lambda command, *, env: Process(),
    )

    assert _server_launcher.main() == 23


def test_main_swallows_keyboard_interrupt_and_waits_for_child(monkeypatch, tmp_path):
    executable = tmp_path / "overlays-server.exe"
    executable.write_bytes(b"binary")
    monkeypatch.setattr(_server_launcher.resources, "files", lambda package: tmp_path)

    calls: list[object] = []

    class Process:
        def wait(self, timeout=None):
            calls.append(timeout)
            if timeout is None:
                raise KeyboardInterrupt
            return 0

    monkeypatch.setattr(
        _server_launcher.subprocess,
        "Popen",
        lambda command, *, env: Process(),
    )

    assert _server_launcher.main() == 0
    assert calls == [None, _server_launcher._INTERRUPT_GRACE_SECONDS]


def test_main_terminates_child_after_repeated_keyboard_interrupts(
    monkeypatch,
    tmp_path,
):
    executable = tmp_path / "overlays-server.exe"
    executable.write_bytes(b"binary")
    monkeypatch.setattr(_server_launcher.resources, "files", lambda package: tmp_path)

    calls: list[object] = []

    class Process:
        def wait(self, timeout=None):
            calls.append(timeout)
            if timeout is None:
                raise KeyboardInterrupt
            if timeout == _server_launcher._INTERRUPT_GRACE_SECONDS:
                raise KeyboardInterrupt
            return 0

        def terminate(self):
            calls.append("terminate")

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(
        _server_launcher.subprocess,
        "Popen",
        lambda command, *, env: Process(),
    )

    assert _server_launcher.main() == 0
    assert calls == [
        None,
        _server_launcher._INTERRUPT_GRACE_SECONDS,
        "terminate",
        _server_launcher._TERMINATE_WAIT_SECONDS,
    ]


def test_bundled_server_path_raises_when_executable_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(_server_launcher.resources, "files", lambda package: tmp_path)

    with pytest.raises(FileNotFoundError):
        with _server_launcher.bundled_server_path():
            pass
