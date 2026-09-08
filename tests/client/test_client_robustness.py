"""Failure-mode tests for the overlay client against a controllable named-pipe server.

They cover the scenario reported from an RPA bot: one thread creates highlights while a
background thread updates an elapsed-time window through the same shared client, and
the server occasionally stops answering.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

import pytest

import overlays.client as client_module
from overlays.client import OverlayClient, RemoteElapsedTimeWindow, get_overlay_client
from tests.client.fake_pipe_server import CLOSE_SESSION, FakePipeServer


def echo_handler(request: dict[str, Any], session: Any) -> dict[str, Any]:
    return {"status": "success", "echo": request["args"].get("tag")}


def tag_of(request: dict[str, Any]) -> str | None:
    return request.get("args", {}).get("tag")


class ThreadedCall:
    """Runs ``fn`` on a daemon thread so a hanging call cannot hang the test run."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self.value: Any = None
        self.error: BaseException | None = None
        self.elapsed: float | None = None
        self._thread = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self._thread.start()

    def _run(self, fn: Callable[[], Any]) -> None:
        started = time.perf_counter()
        try:
            self.value = fn()
        except BaseException as exc:  # noqa: BLE001
            self.error = exc
        finally:
            self.elapsed = time.perf_counter() - started

    def wait(self, timeout: float) -> bool:
        self._thread.join(timeout)
        return not self._thread.is_alive()


@pytest.fixture
def pipe_name(monkeypatch) -> str:
    name = f"overlay_manager_pytest_{uuid.uuid4().hex}"
    monkeypatch.setenv("OVERLAY_PIPE_NAME", name)
    return name


@pytest.fixture
def fake_server(pipe_name):
    servers: list[FakePipeServer] = []

    def factory(handler) -> FakePipeServer:
        server = FakePipeServer(pipe_name, handler).start()
        servers.append(server)
        return server

    yield factory
    for server in servers:
        server.stop()


@pytest.fixture(autouse=True)
def immediate_reconnect(monkeypatch):
    """Tests drive reconnect timing explicitly unless they opt into the real backoff."""
    monkeypatch.setattr(client_module, "_RECONNECT_COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(client_module, "_UNRESPONSIVE_BACKOFF_INITIAL_SECONDS", 0.0)


def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class TestBoundedBlocking:
    def test_call_returns_within_timeout_when_server_never_answers(self, fake_server):
        fake_server(lambda request, session: None)
        client = OverlayClient(timeout=300)
        assert client.is_available()

        call = ThreadedCall(
            lambda: client._send_command("create_elapsed_time", {"message_text": "x"})
        )

        assert call.wait(3.0), "call did not return although the server stayed silent"
        assert call.error is None
        assert call.value == {"status": "ignored", "reason": "timeout"}
        assert call.elapsed is not None and call.elapsed < 1.5
        assert not client.is_available()
        assert client.pipe_handle is None

    def test_waiting_caller_is_bounded_while_another_call_stalls(self, fake_server):
        def handler(request, session):
            if tag_of(request) == "stall":
                return None
            return echo_handler(request, session)

        fake_server(handler)
        client = OverlayClient(timeout=800)

        stalled = ThreadedCall(lambda: client._send_command("echo", {"tag": "stall"}))
        time.sleep(0.1)
        waiting = ThreadedCall(lambda: client._send_command("echo", {"tag": "quick"}))

        assert waiting.wait(3.0), "second caller hung behind the stalled call"
        assert stalled.wait(3.0), "stalled call never returned"
        assert waiting.error is None and stalled.error is None
        assert stalled.value == {"status": "ignored", "reason": "timeout"}
        assert waiting.elapsed is not None and waiting.elapsed < 1.5
        # The waiting caller either gets its own answer or gives up; never someone else's.
        assert waiting.value.get("status") in {"success", "ignored"}
        if waiting.value.get("status") == "success":
            assert waiting.value["echo"] == "quick"

    def test_disconnect_while_call_is_pending_unblocks_caller(self, fake_server):
        fake_server(lambda request, session: None)
        client = OverlayClient(timeout=5000)

        pending = ThreadedCall(lambda: client._send_command("echo", {"tag": "x"}))
        time.sleep(0.2)

        started = time.perf_counter()
        client.disconnect()
        assert time.perf_counter() - started < 1.0

        assert pending.wait(2.0), "pending call did not return after disconnect()"
        assert pending.value == {"status": "ignored", "reason": "disconnected"}
        assert not client.is_available()
        # An explicitly disconnected client stays disconnected.
        assert client._send_command("echo", {"tag": "y"}) == {
            "status": "ignored",
            "reason": "server_unavailable",
        }


class TestResponseCorrelation:
    def test_concurrent_callers_receive_their_own_responses(self, fake_server):
        def handler(request, session):
            time.sleep(0.002)  # let several requests queue up before the first reply
            return echo_handler(request, session)

        fake_server(handler)
        client = OverlayClient(timeout=2000)
        mismatches: list[tuple[str, Any]] = []

        def worker(name: str) -> None:
            for index in range(50):
                tag = f"{name}-{index}"
                response = client._send_command("echo", {"tag": tag})
                if response.get("echo") != tag:
                    mismatches.append((tag, response))

        calls = [ThreadedCall(lambda name=name: worker(name)) for name in "ABCD"]
        assert all(call.wait(20.0) for call in calls)
        assert all(call.error is None for call in calls)
        assert mismatches == []
        client.disconnect()

    def test_late_response_is_not_delivered_to_next_call(self, fake_server):
        def handler(request, session):
            if tag_of(request) == "slow":
                time.sleep(0.8)
            return echo_handler(request, session)

        server = fake_server(handler)
        client = OverlayClient(timeout=300)

        slow = client._send_command("echo", {"tag": "slow"})
        assert slow == {"status": "ignored", "reason": "timeout"}

        fresh = client._send_command("echo", {"tag": "fresh"})
        assert fresh == {"status": "success", "echo": "fresh"}
        assert server.session_count == 2

        # The late answer dies with the dropped connection instead of reaching a caller.
        assert wait_until(lambda: len(server.write_errors) == 1)
        assert [tag_of(request) for request in server.sessions[0].requests] == ["slow"]
        client.disconnect()

    def test_shared_client_keeps_highlights_and_status_updates_apart(self, fake_server):
        """The RPA scenario: main thread highlights, background thread updates status."""
        windows: dict[int, str] = {}
        next_id = {"value": 100}
        lock = threading.Lock()

        def handler(request, session):
            command = request["command"]
            with lock:
                if command == "create_elapsed_time":
                    next_id["value"] += 1
                    windows[next_id["value"]] = request["args"]["message_text"]
                    return {"status": "success", "window_id": next_id["value"]}
                if command == "create_highlight":
                    next_id["value"] += 1
                    return {"status": "success", "window_id": next_id["value"]}
                if command == "update_window_message":
                    window_id = request["args"]["window_id"]
                    if window_id not in windows:
                        return {"status": "error", "message": "unknown window"}
                    windows[window_id] = request["args"]["new_message"]
                    return {
                        "status": "success",
                        "message": f"Window {window_id} updated",
                    }
                if command == "close_window":
                    windows.pop(request["args"]["window_id"], None)
                    return {"status": "success", "message": "closed"}
            return {"status": "error", "message": "unexpected"}

        fake_server(handler)
        client = get_overlay_client(timeout=2000)
        failures: list[str] = []

        def status_thread() -> None:
            window_id = client.create_elapsed_time_window("starting")
            if not isinstance(window_id, int):
                failures.append(f"create_elapsed_time_window returned {window_id!r}")
                return
            with RemoteElapsedTimeWindow(window_id, client) as window:
                for step in range(40):
                    if not window.update_message(f"step {step}"):
                        failures.append(f"update_message failed at step {step}")

        def main_thread() -> None:
            for step in range(40):
                if not client.create_highlight_window((0, 0, 10, 10), 1):
                    failures.append(f"create_highlight_window failed at step {step}")

        calls = [ThreadedCall(status_thread), ThreadedCall(main_thread)]
        assert all(call.wait(20.0) for call in calls)
        assert all(call.error is None for call in calls)
        assert failures == []
        client.disconnect()


class TestRecovery:
    def test_pipe_break_during_call_is_reported_and_connection_recovers(
        self, fake_server
    ):
        def handler(request, session):
            if tag_of(request) == "drop":
                return CLOSE_SESSION
            return echo_handler(request, session)

        server = fake_server(handler)
        client = OverlayClient(timeout=1000)

        dropped = client._send_command("echo", {"tag": "drop"})
        assert dropped == {"status": "ignored", "reason": "connection_lost"}
        assert not client.is_available()
        assert client.pipe_handle is None

        recovered = client._send_command("echo", {"tag": "again"})
        assert recovered == {"status": "success", "echo": "again"}
        assert client.is_available()
        assert server.session_count == 2
        client.disconnect()

    def test_client_recovers_after_server_restart(self, fake_server):
        first_server = fake_server(echo_handler)
        client = OverlayClient(timeout=1000)
        assert client._send_command("echo", {"tag": "one"})["echo"] == "one"

        first_server.stop()
        lost = client._send_command("echo", {"tag": "two"})
        assert lost == {"status": "ignored", "reason": "connection_lost"}
        assert not client.is_available()

        # Server gone entirely: the call fails fast instead of blocking.
        started = time.perf_counter()
        assert client._send_command("echo", {"tag": "three"})["status"] == "ignored"
        assert time.perf_counter() - started < 0.5

        fake_server(echo_handler)
        assert client._send_command("echo", {"tag": "four"})["echo"] == "four"
        assert client.is_available()
        client.disconnect()

    def test_unresponsive_server_pauses_new_clients_with_backoff(
        self, fake_server, monkeypatch
    ):
        monkeypatch.setattr(client_module, "_UNRESPONSIVE_BACKOFF_INITIAL_SECONDS", 5.0)
        server = fake_server(lambda request, session: None)

        first = OverlayClient(timeout=200)
        assert first._send_command("echo", {"tag": "x"}) == {
            "status": "ignored",
            "reason": "timeout",
        }

        started = time.perf_counter()
        second = OverlayClient(timeout=200)
        response = second._send_command("echo", {"tag": "y"})
        assert time.perf_counter() - started < 0.1
        assert response == {"status": "ignored", "reason": "server_unavailable"}
        assert not second.is_available()
        assert server.session_count == 1

        client_module._reset_backoff_state()
        third = OverlayClient(timeout=200)
        assert third.is_available()
        assert wait_until(lambda: server.session_count == 2)
        third.disconnect()

    def test_backoff_grows_and_is_cleared_by_a_successful_call(self, monkeypatch):
        monkeypatch.setattr(client_module, "_UNRESPONSIVE_BACKOFF_INITIAL_SECONDS", 1.0)
        monkeypatch.setattr(client_module, "_UNRESPONSIVE_BACKOFF_MAX_SECONDS", 3.0)
        pipe = r"\\.\pipe\backoff_test"

        assert client_module._register_unresponsive(pipe) == 1.0
        assert client_module._register_unresponsive(pipe) == 2.0
        assert client_module._register_unresponsive(pipe) == 3.0
        assert client_module._register_unresponsive(pipe) == 3.0
        assert client_module._unresponsive_backoff_active(pipe)

        client_module._clear_unresponsive_backoff(pipe)
        assert not client_module._unresponsive_backoff_active(pipe)


class TestSingleton:
    def test_get_overlay_client_creates_one_instance_under_contention(
        self, monkeypatch
    ):
        created: list[object] = []

        class SlowFakeClient:
            def __init__(self, timeout=5000):
                time.sleep(0.05)
                created.append(self)

            def is_available(self):
                return True

        monkeypatch.setattr(client_module, "OverlayClient", SlowFakeClient)
        monkeypatch.setattr(client_module, "_overlay_client", None)

        results: list[object] = []
        barrier = threading.Barrier(8)

        def worker() -> None:
            barrier.wait()
            results.append(get_overlay_client())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5.0)

        assert len(created) == 1
        assert len(results) == 8
        assert all(result is created[0] for result in results)
