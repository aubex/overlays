import pytest
import threading
import time
import signal
import win32gui
from main import OverlayManager, signal_handler, main


# Dummy Timer to execute callbacks immediately
class DummyTimer:
    def __init__(self, interval, function, args=None, kwargs=None):
        self.function = function

    def start(self):
        # Do not execute callback by default
        pass


@pytest.fixture(autouse=True)
def patch_timer_and_threads(monkeypatch):
    # Patch threading.Timer to no-op stub
    monkeypatch.setattr(threading, "Timer", DummyTimer)
    # Prevent pipe server and command thread from starting
    monkeypatch.setattr(OverlayManager, "start_pipe_server", lambda self: None)
    monkeypatch.setattr(OverlayManager, "start_command_thread", lambda self: None)

    # Stub out window initialization and message pump
    def fake_init_window(self):
        self.hwnd = 1
        self._ready.set()

    monkeypatch.setattr(OverlayManager, "_init_window", fake_init_window)
    monkeypatch.setattr(win32gui, "PumpMessages", lambda: None)
    # Stub InvalidateRect to no-op
    monkeypatch.setattr(win32gui, "InvalidateRect", lambda hwnd, rect, b: None)
    yield


def test_add_highlight_window():
    om = OverlayManager(pipe_name="test")
    om.rectangles.clear()
    om.add_highlight_window(
        7, 7, 7, 7, duration_s=10
    )  # One highlight window already exists
    win_id = om.add_highlight_window(1, 2, 3, 4, duration_s=0)
    assert win_id == 2
    assert len(om.rectangles) == 2
    rect = om.rectangles[1]
    assert rect["id"] == 2 and rect["coords"] == (1, 2, 3, 4)


def test_remove_rectangle():
    om = OverlayManager(pipe_name="test")
    om.rectangles = [{"id": 1, "coords": (0, 0, 1, 1)}]
    om._remove_rectangle(1)
    assert not om.rectangles


def test_add_elapsed_time_window():
    om = OverlayManager(pipe_name="test")
    om.response_queue.queue.clear()
    cid = om.add_elapsed_time_window("hello")
    assert cid == 1
    assert cid in list(om.response_queue.queue)


def test_add_countdown_window_and_tick(monkeypatch):
    # Freeze time
    initial = 1000.0
    time_calls = [initial]
    monkeypatch.setattr(time, "time", lambda: time_calls[-1])

    # Prevent any Timer from auto-scheduling
    class NoopTimer:
        def __init__(self, interval, function, args=None, kwargs=None):
            pass

        def start(self):
            pass

    monkeypatch.setattr(threading, "Timer", NoopTimer)

    om = OverlayManager(pipe_name="test")
    cid = om.add_countdown_window("msg", 3)
    assert cid == 1
    cd = om.countdowns[cid]
    assert cd["message"] == "msg"
    assert cd["remaining"] == 3
    # Simulate passage past end_time
    time_calls.append(initial + 4)
    om._tick_countdown(cid)
    assert cid not in om.countdowns


def test_add_and_remove_qrcode_window(monkeypatch):
    # Prevent auto-removal timer from firing
    class NoopTimer:
        def __init__(self, interval, function, args=None, kwargs=None):
            pass

        def start(self):
            pass

    monkeypatch.setattr(threading, "Timer", NoopTimer)
    om = OverlayManager(pipe_name="test")
    qr_id = om.add_qrcode_window({"data": "x"}, timeout_seconds=0, caption="c")
    assert qr_id == 1
    assert qr_id in om.qrcodes
    om.remove_qrcode_window(qr_id)
    assert qr_id not in om.qrcodes
    om = OverlayManager(pipe_name="test")
    qr_id = om.add_qrcode_window({"data": "x"}, timeout_seconds=0, caption="c")
    assert qr_id == 1
    assert qr_id in om.qrcodes
    om.remove_qrcode_window(qr_id)
    assert qr_id not in om.qrcodes


def test_close_and_update_window():
    om = OverlayManager(pipe_name="test")
    # Prepare a countdown window
    om.countdowns = {1: {"message": "old", "order": 1}}
    assert om.update_window(1, "new")
    assert om.countdowns[1]["message"] == "new"
    om.close_window(1)
    assert 1 not in om.countdowns


def test_process_pipe_command_unknown():
    om = OverlayManager(pipe_name="test")
    response = om._process_pipe_command({"command": "unknown", "args": {}})
    assert response["status"] == "error"


def test_signal_handler_exits():
    with pytest.raises(SystemExit):
        signal_handler(signal.SIGINT, None)


def test_main_sets_signals_and_shuts_down(monkeypatch, capsys):
    calls = []
    # Patch signal.signal
    monkeypatch.setattr(signal, "signal", lambda sig, handler: calls.append(sig))

    # Patch OverlayManager to track shutdown
    class DummyOverlay:
        def __init__(self, pipe_name: str = "dummy_pipe"):
            self.pipe_name = pipe_name

        def shutdown(self):
            calls.append("shutdown")

    monkeypatch.setattr("main.OverlayManager", DummyOverlay)
    # Make sleep immediately raise KeyboardInterrupt
    monkeypatch.setattr(
        time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    main()
    assert signal.SIGINT in calls
    assert signal.SIGTERM in calls
    assert "shutdown" in calls
