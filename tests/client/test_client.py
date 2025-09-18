from unittest.mock import Mock

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
        yield
        monkeypatch.setattr("overlays.client._overlay_client", None)

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

    def test_get_overlay_client_singleton(self, monkeypatch):
        # First call creates, second returns same
        monkeypatch.setattr(OverlayClient, "_connect", lambda self: None)
        # Reset module var
        import importlib

        mod = importlib.import_module("client")
        mod._overlay_client = None
        c1 = get_overlay_client()
        c2 = get_overlay_client()
        assert c1 is c2


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
