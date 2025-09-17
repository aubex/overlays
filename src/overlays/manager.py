import contextlib
import json
import logging
import math
import queue
import random
import signal
import sys
import threading
import time
from types import FrameType

import pywintypes
import qrcode
import win32api
import win32con
import win32file
import win32gui
import win32pipe

from overlays.helpers import (
    draw_countdown_window,
    draw_highlight_rectangle,
    draw_qrcode,
    get_countdown_position,
    get_qrcode_position,
)

logger = logging.getLogger(__name__)

ERROR_NO_DATA = 232  # client disconnected
ERROR_BROKEN_PIPE = 109


def draw_all(hdc, full_rect, rectangles, countdowns, qrcodes, transparent_key):
    # Clear to transparent
    br = win32gui.CreateSolidBrush(transparent_key)
    win32gui.FillRect(hdc, full_rect, br)
    win32gui.DeleteObject(br)

    # Draw rectangles
    for rect in rectangles:
        draw_highlight_rectangle(hdc, rect)

    # Draw countdowns
    for idx, (_, cd) in enumerate(
        sorted(countdowns.items(), key=lambda x: x[1]["order"])
    ):
        position = get_countdown_position(idx, full_rect)
        draw_countdown_window(hdc, cd, position)

    # Draw QR codes
    box_gap = 10
    top_start = 20 + len(countdowns) * (80 + box_gap)
    for idx, (_, qr) in enumerate(sorted(qrcodes.items(), key=lambda x: x[1]["order"])):
        total = qr["qr_size"] + 2 * qr["padding"]
        position = get_qrcode_position(idx, total, box_gap, top_start, full_rect)
        draw_qrcode(hdc, qr, position=position)


class Command:
    def execute(self, overlay_manager, args, reply_queue):
        pass


class CreateHighlightCommand(Command):
    def execute(self, overlay_manager, args, reply_queue):
        rect = tuple(args["rect"])
        timeout = args.get("timeout_seconds", 3)
        win_id = overlay_manager.add_highlight_window(*rect, duration_s=timeout)
        reply_queue.put({"status": "success", "window_id": win_id})


class CreateCountdownCommand(Command):
    def execute(self, overlay_manager, args, reply_queue):
        msg = args.get("message_text", "")
        secs = args.get("countdown_seconds", 3)
        win_id = overlay_manager.add_countdown_window(msg, countdown_seconds=secs)
        reply_queue.put({"status": "success", "window_id": win_id})


class CreateElapsedTimeCommand(Command):
    def execute(self, overlay_manager, args, reply_queue):
        msg = args.get("message_text", "")
        win_id = overlay_manager.add_elapsed_time_window(msg)
        reply_queue.put({"status": "success", "window_id": win_id})


class CreateQRCodeCommand(Command):
    def execute(self, overlay_manager, args, reply_queue):
        content = args.get("data", "")
        duration_seconds = args.get("duration", 5)
        caption = args.get("caption", "")
        win_id = overlay_manager.add_qrcode_window(content, duration_seconds, caption)
        reply_queue.put({"status": "success", "window_id": win_id})


class CloseWindowCommand(Command):
    def execute(self, overlay_manager, args, reply_queue):
        window_id = args.get("window_id", "")
        if window_id:
            overlay_manager.close_window(window_id)
            reply_queue.put(
                {"status": "success", "message": f"Window {window_id} closed"}
            )


class UpdateWindowMessageCommand(Command):
    def execute(self, overlay_manager, args, reply_queue):
        window_id = args.get("window_id", "")
        new_message = args.get("new_message", "")
        if window_id and new_message:
            overlay_manager.update_window(window_id, new_message)
            reply_queue.put(
                {"status": "success", "message": f"Window {window_id} updated"}
            )


class TakeBreakCommand(Command):
    def execute(self, overlay_manager, args, reply_queue):
        duration_seconds = args.get("duration_seconds", 0)
        overlay_manager.take_break(duration_seconds)
        reply_queue.put(
            {
                "status": "success",
                "message": f"Break started for {duration_seconds} seconds",
            }
        )


class CancelBreakCommand(Command):
    def execute(self, overlay_manager, args, reply_queue):
        overlay_manager.cancel_break()
        reply_queue.put({"status": "success", "message": "Break canceled"})


COMMANDS = {
    "create_highlight": CreateHighlightCommand(),
    "create_countdown": CreateCountdownCommand(),
    "create_elapsed_time": CreateElapsedTimeCommand(),
    "create_qrcode_window": CreateQRCodeCommand(),
    "close_window": CloseWindowCommand(),
    "update_window_message": UpdateWindowMessageCommand(),
    "take_break": TakeBreakCommand(),
    "cancel_break": CancelBreakCommand(),
}


# --- OverlayManager ---
class OverlayManager:
    def __init__(self, pipe_name: str):
        self.className = "TransparentOverlayWindow"
        self.rectangles = []
        self.countdowns = {}
        self.qrcodes = {}
        self._next_rect_id = 1
        self._next_countdown_id = 1
        self._next_qrcode_id = 1
        self._qrcode_order = 0
        self._countdown_order = 0
        self.pipe_name = rf"\\.\pipe\{pipe_name}"
        self.shutdown_event = threading.Event()
        self.command_queue = queue.Queue()
        self._break_until = 0.0
        self._pending_commands = []
        self.hwnd = None
        self._transparent_key = win32api.RGB(255, 0, 255)
        self._ready = threading.Event()
        self._threads = []

    def _init_window_and_pump(self):
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = self.className
        wc.lpfnWndProc = self.wndProc
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
        wc.hbrBackground = 0
        win32gui.RegisterClass(wc)

        sw = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        sh = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        self.hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_TOPMOST
            | win32con.WS_EX_TOOLWINDOW,
            self.className,
            "Overlay",
            win32con.WS_POPUP,
            0,
            0,
            sw,
            sh,
            0,
            0,
            wc.hInstance,
            None,
        )
        win32gui.SetLayeredWindowAttributes(
            self.hwnd,
            self._transparent_key,
            200,
            win32con.LWA_COLORKEY | win32con.LWA_ALPHA,
        )
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        win32gui.UpdateWindow(self.hwnd)
        self._ready.set()
        win32gui.PumpMessages()

    def start(self):
        if self._threads:
            return

        targets = [
            self._init_window_and_pump,
            self._run_pipe_server,
            self._run_command_thread,
            self._run_countdown_manager,
        ]
        for fn in targets:
            t = threading.Thread(target=fn, daemon=True, name=fn.__name__)
            t.start()
            self._threads.append(t)

        self._ready.wait()

    def shutdown(self, join_timeout: float = 5.0):
        self.shutdown_event.set()
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        [t.join(timeout=join_timeout) for t in self._threads]

    def _run_command_thread(self):
        while not self.shutdown_event.is_set():
            try:
                cmd, args, reply_queue = self.command_queue.get(timeout=1)
                if cmd in ("take_break", "cancel_break"):
                    COMMANDS[cmd].execute(self, args, reply_queue)
                    continue
                if self._break_until and time.time() < self._break_until:
                    self._pending_commands.append((cmd, args, reply_queue))
                    continue
                if self._break_until and time.time() >= self._break_until:
                    self._break_until = 0
                    while self._pending_commands:
                        p_cmd, p_args, p_reply_queue = self._pending_commands.pop(0)
                        COMMANDS[p_cmd].execute(self, p_args, p_reply_queue)
                COMMANDS[cmd].execute(self, args, reply_queue)
            except queue.Empty:
                continue

    def take_break(self, duration_s):
        self._break_until = time.time() + duration_s

    def cancel_break(self):
        self._break_until = 0
        self._pending_commands.clear()

    def _handle_pipe_errors(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except pywintypes.error as e:
                if e.winerror in (ERROR_BROKEN_PIPE, ERROR_NO_DATA):
                    logger.debug("Client disconnected: %s", e)
                else:
                    logger.exception("Pipe error: %s", e)
                return
            except json.JSONDecodeError as e:
                logger.exception("Invalid JSON: %s", e)
                return {"error": "Invalid JSON"}
            except Exception as e:
                logger.exception("Unexpected error in %s: %s", func.__name__, e)
                return

        return wrapper

    @_handle_pipe_errors
    def _run_pipe_server(self):
        logger.info("Starting named pipe server on %s", self.pipe_name)
        print(f"🔌 Named pipe server starting on {self.pipe_name}")
        while not self.shutdown_event.is_set():
            pipe_handle = win32pipe.CreateNamedPipe(
                self.pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE
                | win32pipe.PIPE_READMODE_MESSAGE
                | win32pipe.PIPE_WAIT,
                1,
                65536,
                65536,
                0,
                None,
            )
            if pipe_handle == win32file.INVALID_HANDLE_VALUE:
                logger.error("Failed to create named pipe")
                time.sleep(1)
                continue
            try:
                win32pipe.ConnectNamedPipe(pipe_handle, None)
                logger.info("Client connected to named pipe")
                self._handle_pipe_client(pipe_handle)
            finally:
                with contextlib.suppress(Exception):
                    win32file.CloseHandle(pipe_handle)

    @_handle_pipe_errors
    def _handle_pipe_client(self, pipe_handle):
        while not self.shutdown_event.is_set():
            result, data = win32file.ReadFile(pipe_handle, 4096)
            if result == 0 and data:
                message = data.decode("utf-8")
                logger.debug("Received pipe message: %s", message)
                command_data = json.loads(message)
                response = self._process_pipe_command(command_data)
                response_data = json.dumps(response).encode("utf-8")
                win32file.WriteFile(pipe_handle, response_data)
            else:
                break

    def _process_pipe_command(self, command_data: dict) -> dict:
        cmd = command_data.get("command")
        args = command_data.get("args", {})
        reply_queue = queue.Queue()
        command = COMMANDS.get(cmd)
        if command:
            self.command_queue.put((cmd, args, reply_queue))
            try:
                return reply_queue.get(timeout=10)
            except queue.Empty:
                return {"status": "error", "message": "Command timed out"}
        return {"status": "error", "message": f"Unknown command {cmd}"}

    def _invalidate_rect(self) -> None:
        try:
            win32gui.InvalidateRect(self.hwnd, None, True)
        except pywintypes.error:
            pass  # Do nothing; handle rest normally

    def add_highlight_window(self, left, top, right, bottom, duration_s):
        rid = self._next_rect_id
        self._next_rect_id += 1
        color = (
            random.randint(64, 255),
            random.randint(64, 255),
            random.randint(64, 255),
        )
        self.rectangles.append(
            {"id": rid, "coords": (left, top, right, bottom), "color": color}
        )
        self._invalidate_rect()
        threading.Timer(duration_s, lambda: self._remove_rectangle(rid)).start()
        return rid

    def _remove_rectangle(self, rid):
        self.rectangles = [r for r in self.rectangles if r["id"] != rid]
        self._invalidate_rect()

    def add_elapsed_time_window(self, message_text):
        cid = self._next_countdown_id
        self._next_countdown_id += 1
        self._countdown_order += 1

        # store the message and when we started
        self.countdowns[cid] = {
            "message": message_text,
            "start_time": time.time(),
            "elapsed": 0,
            "order": self._countdown_order,
        }
        self._invalidate_rect()
        return cid

    def add_countdown_window(self, message_text, countdown_seconds):
        cid = self._next_countdown_id
        self._next_countdown_id += 1
        self._countdown_order += 1
        now = time.time()
        self.countdowns[cid] = {
            "message": message_text,
            "end_time": now + countdown_seconds,
            "remaining": countdown_seconds,
            "order": self._countdown_order,
        }
        self._invalidate_rect()
        return cid

    def add_qrcode_window(
        self, metadata: str | dict, timeout_seconds: int, caption: str | None = None
    ) -> int:
        qr_id = self._next_qrcode_id
        self._next_qrcode_id += 1
        self._qrcode_order += 1
        data = metadata if isinstance(metadata, str) else json.dumps(metadata)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        module_count = len(matrix)
        pix_per_mod = 6
        qr_size = module_count * pix_per_mod
        padding = 10
        self.qrcodes[qr_id] = {
            "matrix": matrix,
            "qr_size": qr_size,
            "pix_per_mod": pix_per_mod,
            "padding": padding,
            "caption": caption or "",
            "order": self._qrcode_order,
        }
        threading.Timer(
            timeout_seconds, lambda: self.remove_qrcode_window(qr_id)
        ).start()
        self._invalidate_rect()
        return qr_id

    def remove_qrcode_window(self, qr_id: int):
        if qr_id in self.qrcodes:
            del self.qrcodes[qr_id]
            self._invalidate_rect()

    def _run_countdown_manager(self):
        while not self.shutdown_event.is_set():
            now = time.time()
            for cid, cd in list(self.countdowns.items()):
                if "start_time" in cd:
                    cd["elapsed"] = math.ceil(now - cd["start_time"]) - 1
                    self._invalidate_rect()
                if "end_time" not in cd:
                    continue
                remaining = max(0, math.ceil(cd["end_time"] - now))
                if remaining <= 0:
                    cd["remaining"] = 0
                    self._invalidate_rect()
                    del self.countdowns[cid]
                elif cd["remaining"] != remaining:
                    cd["remaining"] = remaining
                    self._invalidate_rect()
            time.sleep(0.1)

    def close_window(self, window_id: int):
        if window_id in self.countdowns:
            del self.countdowns[window_id]
            self._invalidate_rect()

    def update_window(self, window_id: int, new_msg: str):
        cd = self.countdowns.get(window_id)
        if not cd:
            return False
        cd["message"] = new_msg
        self._invalidate_rect()
        return True

    def wndProc(self, hwnd, msg, wParam, lParam):
        if msg == win32con.WM_PAINT:
            self.onPaint(hwnd)
            return 0
        if msg == win32con.WM_KEYDOWN and wParam == win32con.VK_ESCAPE:
            win32gui.DestroyWindow(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wParam, lParam)

    def onPaint(self, hwnd):
        hdc, ps = win32gui.BeginPaint(hwnd)
        full = win32gui.GetClientRect(hwnd)
        draw_all(
            hdc,
            full,
            self.rectangles,
            self.countdowns,
            self.qrcodes,
            self._transparent_key,
        )
        win32gui.EndPaint(hwnd, ps)


def signal_handler(sig: int, frame: FrameType | None) -> None:
    print("\nReceived shutdown signal, cleaning up...")
    sys.exit(0)


def main(pipe_name: str = r"overlay_manager") -> None:
    print("🔧 OverlayManager - Windows Overlay Application")
    print("================================================")
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    print("✅ Signal handlers configured")
    print("🚀 Starting OverlayManager...")
    overlay_manager = OverlayManager(pipe_name=pipe_name)
    overlay_manager.start()  # Ensure OverlayManager is started
    print("✅ OverlayManager initialized successfully")
    print(f"📡 Named pipe server: {overlay_manager.pipe_name}")
    print("🎯 Application ready - overlay windows can now be created")
    print("💡 Press Ctrl+C to shutdown gracefully")
    print()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    finally:
        print("🧹 Cleaning up resources...")
        overlay_manager.shutdown()
        print("👋 OverlayManager shutdown complete")
