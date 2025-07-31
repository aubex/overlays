# tests/test_main.py
import signal
import threading
import time

import pytest
import win32gui

from overlays import main


# Dummy Timer to execute callbacks immediately
class DummyTimer:
    def __init__(self, interval, function, args=None, kwargs=None):
        self.function = function

    def start(self):
        pass


@pytest.fixture(autouse=True)
def patch_timer_and_threads(monkeypatch):
    monkeypatch.setattr(threading, "Timer", DummyTimer)
    monkeypatch.setattr(main.OverlayManager, "_run_pipe_server", lambda self: None)
    monkeypatch.setattr(main.OverlayManager, "_run_command_thread", lambda self: None)

    # Stub window init/pump
    def fake_init_window(self):
        self.hwnd = 1
        self._ready.set()

    monkeypatch.setattr(main.OverlayManager, "_init_window_and_pump", fake_init_window)
    monkeypatch.setattr(win32gui, "PumpMessages", lambda: None)
    monkeypatch.setattr(win32gui, "InvalidateRect", lambda hwnd, rect, b: None)

    yield


def test_add_highlight_window():
    om = main.OverlayManager(pipe_name="test")
    om.rectangles.clear()
    # first rectangle
    om.add_highlight_window(7, 7, 7, 7, duration_s=10)
    # second
    win_id = om.add_highlight_window(1, 2, 3, 4, duration_s=0)
    assert win_id == 2
    assert len(om.rectangles) == 2
    rect = om.rectangles[1]
    assert rect["id"] == 2
    assert rect["coords"] == (1, 2, 3, 4)


def test_remove_rectangle():
    om = main.OverlayManager(pipe_name="test")
    om.rectangles = [{"id": 1, "coords": (0, 0, 1, 1)}]
    om._remove_rectangle(1)
    assert om.rectangles == []


def test_add_countdown_window_and_tick(monkeypatch):
    # freeze time at t0
    t0 = 1_000.0
    times = [t0]
    monkeypatch.setattr(time, "time", lambda: times[-1])

    class NoopTimer:
        def __init__(self, interval, function, args=None, kwargs=None):
            pass

        def start(self):
            pass

    monkeypatch.setattr(threading, "Timer", NoopTimer)

    om = main.OverlayManager(pipe_name="test")
    cid = om.add_countdown_window("msg", 3)
    assert cid == 1
    cd = om.countdowns[cid]
    assert cd["message"] == "msg"
    assert cd["remaining"] == 3

    times.append(t0 + 4)

    # monkey-patch sleep
    def fake_sleep(sec):
        # stop the loop
        om.shutdown_event.set()
        raise StopIteration

    monkeypatch.setattr(time, "sleep", fake_sleep)

    with pytest.raises(StopIteration):
        om._run_countdown_manager()

    assert cid not in om.countdowns


def test_add_and_remove_qrcode_window(monkeypatch):
    # disable auto-remove timer
    class NoopTimer:
        def __init__(self, interval, function, args=None, kwargs=None):
            pass

        def start(self):
            pass

    monkeypatch.setattr(threading, "Timer", NoopTimer)

    om = main.OverlayManager(pipe_name="test")
    qr_id = om.add_qrcode_window({"data": "x"}, timeout_seconds=0, caption="c")
    assert qr_id == 1
    assert qr_id in om.qrcodes

    om.remove_qrcode_window(qr_id)
    assert qr_id not in om.qrcodes

    # try again on a fresh manager
    om = main.OverlayManager(pipe_name="test")
    qr_id = om.add_qrcode_window("foo", timeout_seconds=0, caption=None)
    assert qr_id == 1
    assert qr_id in om.qrcodes
    om.remove_qrcode_window(qr_id)
    assert qr_id not in om.qrcodes


def test_close_and_update_window():
    om = main.OverlayManager(pipe_name="test")
    om.countdowns = {1: {"message": "old", "order": 1}}
    assert om.update_window(1, "new") is True
    assert om.countdowns[1]["message"] == "new"
    om.close_window(1)
    assert 1 not in om.countdowns


def test_process_pipe_command_unknown():
    om = main.OverlayManager(pipe_name="test")
    resp = om._process_pipe_command({"command": "foo", "args": {}})
    assert resp["status"] == "error"
    assert "Unknown command" in resp["message"]


def test_signal_handler_exits():
    with pytest.raises(SystemExit):
        main.signal_handler(signal.SIGINT, None)


def test_main_sets_signals_and_shuts_down(monkeypatch):
    calls = []

    monkeypatch.setattr(signal, "signal", lambda sig, handler: calls.append(sig))

    class DummyOverlay:
        def __init__(self, pipe_name="dummy"):
            self.pipe_name = pipe_name

        def start(self):
            calls.append("started")

        def shutdown(self):
            calls.append("shutdown")

    # patch into main
    monkeypatch.setattr(main, "OverlayManager", DummyOverlay)
    monkeypatch.setattr(
        time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt())
    )

    main.main()

    assert signal.SIGINT in calls
    assert signal.SIGTERM in calls
    assert "started" in calls
    assert "shutdown" in calls
