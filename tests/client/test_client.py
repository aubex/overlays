import logging
from unittest.mock import Mock

import overlays.client as client_module
import pytest
import pywintypes
import win32file

# Replace 'overlay_client_module' with the actual module name where OverlayClient is defined
from overlays.client import (
    OverlayClient,
    RemoteElapsedTimeWindow,
    get_overlay_client,
)


class TestOverlayClient:
    @pytest.fixture(autouse=True)
    def reset_module_state(self, monkeypatch):
        # Reset the module-level client singleton
        monkeypatch.setattr("overlays.client._overlay_client", None)
        monkeypatch.setattr("overlays.client._server_unavailable_warning_emitted", False)
        yield
        monkeypatch.setattr("overlays.client._overlay_client", None)
        monkeypatch.setattr("overlays.client._server_unavailable_warning_emitted", False)

    @pytest.fixture
    def unavailable_client(self, monkeypatch):
        # Stub _connect to simulate no server
        monkeypatch.setattr(OverlayClient, "_connect", lambda self: None)
        client = OverlayClient()
        client.server_available = False
        client.pipe_handle = None
        return client

    @pytest.fixture
    def available_client(self, monkeypatch):
        # Stub _connect to simulate server available
        def fake_connect(self):
            self.server_available = True
            self.pipe_handle = "HANDLE"

        monkeypatch.setattr(OverlayClient, "_connect", fake_connect)
        return OverlayClient()

    def test_init_sets_defaults_and_calls_connect(self, monkeypatch):
        called = False

        def fake_connect(self):
            nonlocal called
            called = True
            self.server_available = True
            self.pipe_handle = "H"

        monkeypatch.setattr(OverlayClient, "_connect", fake_connect)
        client = OverlayClient(timeout=1234)
        assert called
        assert client.pipe_name == r"\\.\pipe\overlay_manager"
        assert client.timeout == 1234
        assert client.server_available is True
        assert client.pipe_handle == "H"

    def test_send_command_ignored_when_unavailable(self, unavailable_client):
        resp = unavailable_client._send_command("cmd", {"x": 1})
        assert resp == {"status": "ignored", "reason": "server_unavailable"}

    def test_connect_logs_warning_when_server_unavailable(self, monkeypatch, caplog):
        def fake_wait(pipe_name, timeout):
            raise pywintypes.error(2, "WaitNamedPipe", "missing")

        monkeypatch.setattr(client_module.win32pipe, "WaitNamedPipe", fake_wait)

        with caplog.at_level(logging.WARNING):
            client = OverlayClient()

        assert client.is_available() is False
        warnings = [record.message for record in caplog.records]
        assert warnings == [
            "Overlay server not available on pipe \\\\.\\pipe\\overlay_manager; "
            "overlay commands will be ignored until it is running."
        ]

    def test_send_command_logs_warning_only_once_when_unavailable(
        self, unavailable_client, caplog
    ):
        with caplog.at_level(logging.WARNING):
            first = unavailable_client._send_command("first", {"x": 1})
            second = unavailable_client._send_command("second", {"x": 2})

        assert first == {"status": "ignored", "reason": "server_unavailable"}
        assert second == {"status": "ignored", "reason": "server_unavailable"}
        warnings = [record.message for record in caplog.records]
        assert warnings == [
            "Ignoring overlay command 'first' because the server is not available "
            "on pipe \\\\.\\pipe\\overlay_manager."
        ]

    def test_send_command_success(self, available_client, monkeypatch):
        # Mock WriteFile and ReadFile
        monkeypatch.setattr(win32file, "WriteFile", lambda h, msg: None)
        monkeypatch.setattr(
            win32file, "ReadFile", lambda h, sz: (0, b'{"status":"success","data":123}')
        )

        resp = available_client._send_command("test", {"a": 2})
        assert resp == {"status": "success", "data": 123}

    def test_send_command_broken_pipe(self, available_client, monkeypatch):
        # Simulate WriteFile raising broken pipe error
        def fake_write(h, msg):
            raise pywintypes.error(109, "WriteFile", "Broken")

        monkeypatch.setattr(win32file, "WriteFile", fake_write)

        resp = available_client._send_command("cmd", {})
        assert resp == {"status": "ignored", "reason": "connection_lost"}
        assert not available_client.server_available
        assert available_client.pipe_handle is None

    def test_send_command_broken_pipe_logs_warning(
        self, available_client, monkeypatch, caplog
    ):
        def fake_write(h, msg):
            raise pywintypes.error(109, "WriteFile", "Broken")

        monkeypatch.setattr(win32file, "WriteFile", fake_write)

        with caplog.at_level(logging.WARNING):
            available_client._send_command("cmd", {})

        warnings = [record.message for record in caplog.records]
        assert warnings == [
            "Connection to overlay server on pipe \\\\.\\pipe\\overlay_manager was "
            "lost while handling 'cmd'; future overlay commands will be ignored "
            "until it is running again."
        ]

    def test_send_command_invalid_json_response(self, available_client, monkeypatch):
        monkeypatch.setattr(win32file, "WriteFile", lambda h, m: None)
        monkeypatch.setattr(win32file, "ReadFile", lambda h, sz: (0, b"not json"))

        resp = available_client._send_command("cmd", {})
        assert resp == {"status": "ignored", "reason": "invalid_response"}

    def test_handle_connection_lost(self, available_client):
        available_client.server_available = True
        available_client.pipe_handle = "H"
        available_client._handle_connection_lost()
        assert not available_client.server_available
        assert available_client.pipe_handle is None

    @pytest.mark.parametrize(
        "method,args,expected_cmd,return_val",
        [
            ("create_countdown_window", ("msg", 3), True, {"status": "success"}),
            ("create_highlight_window", ((1, 2, 3, 4), 5), True, {"status": "success"}),
            ("close_window", (8,), True, {"status": "success"}),
            ("update_window_message", (9, "new"), True, {"status": "success"}),
            ("take_break", (12,), True, {"status": "success"}),
            ("cancel_break", (), True, {"status": "success"}),
            ("close_all_windows", (), True, {"status": "success"}),
            # failure cases
            ("create_countdown_window", ("m", 1), False, {"status": "error"}),
        ],
    )
    def test_bool_commands(
        self, available_client, monkeypatch, method, args, expected_cmd, return_val
    ):
        # Patch _send_command
        monkeypatch.setattr(
            OverlayClient, "_send_command", lambda self, c, a=None: return_val
        )
        fn = getattr(available_client, method)
        result = fn(*args)
        assert (result is True) == expected_cmd

    def test_create_elapsed_time_window(self, available_client, monkeypatch):
        # success
        monkeypatch.setattr(
            OverlayClient,
            "_send_command",
            lambda self, c, a=None: {"status": "success", "window_id": 42},
        )
        assert available_client.create_elapsed_time_window("x") == 42
        # failure
        monkeypatch.setattr(
            OverlayClient, "_send_command", lambda self, c, a=None: {"status": "error"}
        )
        assert available_client.create_elapsed_time_window("x") is None

    def test_create_qrcode_window(self, available_client, monkeypatch):
        monkeypatch.setattr(
            OverlayClient,
            "_send_command",
            lambda self, c, a=None: {"status": "success", "window_id": 7},
        )
        assert available_client.create_qrcode_window("d", 4, "cap") == 7
        monkeypatch.setattr(
            OverlayClient, "_send_command", lambda self, c, a=None: {"status": "error"}
        )
        assert available_client.create_qrcode_window("d", 4, None) is None

    def test_is_available(self, unavailable_client, available_client):
        assert not unavailable_client.is_available()
        assert available_client.is_available()

    def test_disconnect_handles_closehandle(self, available_client, monkeypatch):
        # Test normal CloseHandle
        available_client.pipe_handle = "H"
        available_client.server_available = True
        monkeypatch.setattr(win32file, "CloseHandle", lambda h: None)
        available_client.disconnect()
        assert available_client.pipe_handle is None
        assert not available_client.server_available

    def test_disconnect_raises_error(self, available_client, monkeypatch):
        # Test CloseHandle raising
        available_client.pipe_handle = "H"
        available_client.server_available = True

        def fake_close(h):
            raise pywintypes.error(1, "CloseHandle", "err")

        monkeypatch.setattr(win32file, "CloseHandle", fake_close)
        # Should not raise
        available_client.disconnect()
        assert available_client.pipe_handle is None
        assert not available_client.server_available

    def test_context_manager_calls_disconnect(self, available_client, monkeypatch):
        # Spy on disconnect
        spy = Mock()
        available_client.pipe_handle = "H"
        monkeypatch.setattr(available_client, "disconnect", spy)
        with available_client as c:
            assert c is available_client
        spy.assert_called_once()

    def test_get_overlay_client_reuses_available_singleton(self, monkeypatch):
        class FakeOverlayClient:
            instances = []

            def __init__(self, timeout=5000):
                self.timeout = timeout
                self.server_available = True
                self.pipe_handle = "HANDLE"
                FakeOverlayClient.instances.append(self)

            def is_available(self):
                return True

        monkeypatch.setattr(client_module, "OverlayClient", FakeOverlayClient)
        monkeypatch.setattr(client_module, "_overlay_client", None)

        c1 = get_overlay_client(timeout=123)
        c2 = get_overlay_client(timeout=999)

        assert c1 is c2
        assert len(FakeOverlayClient.instances) == 1
        assert c1.timeout == 123

    def test_get_overlay_client_retries_after_initial_unavailability(self, monkeypatch):
        class FakeOverlayClient:
            created = 0

            def __init__(self, timeout=5000):
                FakeOverlayClient.created += 1
                self.timeout = timeout
                self.server_available = FakeOverlayClient.created > 1
                self.pipe_handle = "HANDLE" if self.server_available else None

            def is_available(self):
                return self.server_available and self.pipe_handle is not None

        monkeypatch.setattr(client_module, "OverlayClient", FakeOverlayClient)
        monkeypatch.setattr(client_module, "_overlay_client", None)

        first = get_overlay_client(timeout=111)
        second = get_overlay_client(timeout=222)

        assert first is not second
        assert first.is_available() is False
        assert second.is_available() is True
        assert second.timeout == 222

    def test_get_overlay_client_recreates_disconnected_singleton(self, monkeypatch):
        class FakeOverlayClient:
            instances = []

            def __init__(self, timeout=5000):
                self.timeout = timeout
                self.server_available = True
                self.pipe_handle = "HANDLE"
                FakeOverlayClient.instances.append(self)

            def is_available(self):
                return self.server_available and self.pipe_handle is not None

        monkeypatch.setattr(client_module, "OverlayClient", FakeOverlayClient)
        monkeypatch.setattr(client_module, "_overlay_client", None)

        first = get_overlay_client(timeout=111)
        first.server_available = False
        first.pipe_handle = None

        second = get_overlay_client(timeout=222)

        assert first is not second
        assert second.is_available() is True
        assert len(FakeOverlayClient.instances) == 2
        assert second.timeout == 222


class TestRemoteElapsedTimeWindow:
    @pytest.fixture
    def dummy_client(self):
        return Mock(
            update_window_message=Mock(return_value=True),
            close_window=Mock(return_value=True),
        )

    def test_update_message_server_unavailable(self, dummy_client):
        w = RemoteElapsedTimeWindow(None, dummy_client)
        assert not w.update_message("hi")
        dummy_client.update_window_message.assert_not_called()

    def test_update_message_after_closed(self, dummy_client):
        w = RemoteElapsedTimeWindow(1, dummy_client)
        w._closed = True
        assert not w.update_message("msg")
        dummy_client.update_window_message.assert_not_called()

    def test_update_message_delegates(self, dummy_client):
        w = RemoteElapsedTimeWindow(5, dummy_client)
        assert w.update_message("new")
        dummy_client.update_window_message.assert_called_once_with(5, "new")

    def test_close_unavailable(self, dummy_client):
        w = RemoteElapsedTimeWindow(None, dummy_client)
        assert w.close() is True
        # second close still True
        assert w.close() is True

    def test_close_delegates_and_sets_closed(self, dummy_client):
        w = RemoteElapsedTimeWindow(10, dummy_client)
        assert w.close() is True
        dummy_client.close_window.assert_called_once_with(10)
        # now closed
        assert w._closed
        # calling again returns True, no extra calls
        w.close()
        assert dummy_client.close_window.call_count == 1

    def test_context_manager_auto_closes(self, dummy_client):
        w = RemoteElapsedTimeWindow(20, dummy_client)
        with w:
            pass
        dummy_client.close_window.assert_called_once_with(20)
