import threading
import time
import win32api
import win32con
import win32gui

import pywintypes
import win32file
import win32pipe
import logging
import contextlib
import json
import queue
import random
import signal
import sys
import math
import qrcode
from types import FrameType
from collections import deque
from helpers import (
    draw_highlight_rectangle,
    draw_qrcode,
    get_countdown_position,
    get_qrcode_position,
    draw_countdown_window,
)

logger = logging.getLogger("pyfenster")

logger = logging.getLogger(__name__)

ERROR_NO_DATA = 232  # client disconnected
ERROR_BROKEN_PIPE = 109
RECT_CORRECT_DIMENSIONS = 4


class OverlayManager:
    def __init__(self, pipe_name: str = r"\\.\pipe\overlay_manager"):
        # just init state – don’t touch Win32 yet
        self.className = "TransparentOverlayWindow"
        self.rectangles = []
        self.countdowns = {}
        self.qrcodes = {}
        self._next_rect_id = 1
        self._next_countdown_id = 1
        self._next_qrcode_id = 1
        self._qrcode_order = 0
        self._countdown_order = 0  # ensure insertion order
        self._pipe_thread = None
        self.pipe_name = pipe_name
        self.shutdown_event = threading.Event()
        self.command_queue = queue.Queue()
        self.response_queue = queue.Queue()

        self.hwnd = None
        self._transparent_key = win32api.RGB(255, 0, 255)
        self._ui_thread = None
        self._command_thread = None
        self._ready = threading.Event()
        self.start()

    def _init_window(self):
        """Register the class and create/show the layered window."""
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
        # Makes all window elements transparent
        win32gui.SetLayeredWindowAttributes(
            self.hwnd,
            self._transparent_key,
            200,
            win32con.LWA_COLORKEY | win32con.LWA_ALPHA,
        )
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        win32gui.UpdateWindow(self.hwnd)

    def start(self):
        """
        Launch the UI thread (which will create the window + pump messages),
        then wait until it's ready before returning.
        """
        if self._ui_thread is not None:
            return  # already started

        def ui_loop():
            self._init_window()
            # signal to caller that hwnd is now valid
            self._ready.set()
            # this blocks until the window is destroyed
            win32gui.PumpMessages()

        self._ui_thread = threading.Thread(target=ui_loop, daemon=True)
        self._ui_thread.start()
        self.start_pipe_server()
        self.start_command_thread()
        # wait here until window is up
        self._ready.wait()

    def shutdown(self, join_timeout: float = 5.0):
        """
        Cleanly shut down the overlay:
        1) Signal background threads to stop
        2) Close the overlay window (ends PumpMessages)
        3) Join the UI, pipe‐server, and command threads
        """
        # 1) signal threads that we’re shutting down
        self.shutdown_event.set()

        # 2) close the window (post WM_CLOSE onto the UI thread)
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)

        # 3) wait for each thread to exit
        for _, thread in (
            ("command", self._command_thread),
            ("pipe server", self._pipe_thread),
            ("UI", self._ui_thread),
        ):
            if thread and thread.is_alive():
                thread.join(join_timeout)

    def start_command_thread(self):
        def run_command_thread():
            break_until = 0.0
            pending = deque()

            while not self.shutdown_event.is_set():
                try:
                    request = self.command_queue.get(timeout=1)
                except queue.Empty:
                    # if break has just ended, flush pending
                    if break_until and time.time() >= break_until:
                        break_until = 0
                        while pending:
                            self._handle_request(pending.popleft())
                    continue

                # unpack request and reply_queue
                cmd = request[0]
                reply_queue = request[-1]

                # always handle break commands immediately
                if cmd == "take_break":
                    _, duration_s, _ = request
                    break_until = time.time() + duration_s
                    reply_queue.put(
                        {
                            "status": "success",
                            "message": f"Break started for {duration_s} seconds",
                        }
                    )
                    continue

                if cmd == "cancel_break":
                    _, _ = request
                    break_until = 0
                    pending.clear()
                    reply_queue.put({"status": "success", "message": "Break canceled"})
                    continue

                # if we're in a break, buffer all other commands
                if break_until and time.time() < break_until:
                    pending.append(request)
                    continue

                # if break has just ended, flush before handling this
                if break_until and time.time() >= break_until:
                    break_until = 0
                    while pending:
                        self._handle_request(pending.popleft())

                # now handle this request immediately
                self._handle_request(request)

        self._command_thread = threading.Thread(target=run_command_thread, daemon=True)
        self._command_thread.start()

    def _handle_request(self, request):
        cmd = request[0]
        reply_queue = request[-1]
        if cmd == "create_highlight":
            _, rect, timeout_s, reply_queue = request
            win_id = self.add_highlight_window(*rect, duration_s=timeout_s)
            reply_queue.put({"status": "success", "window_id": win_id})

        elif cmd == "create_countdown":
            _, msg, secs, reply_queue = request
            win_id = self.add_countdown_window(msg, countdown_seconds=secs)
            reply_queue.put({"status": "success", "window_id": win_id})

        elif cmd == "create_elapsed_time":
            _, msg, reply_queue = request
            win_id = self.add_elapsed_time_window(msg)
            reply_queue.put({"status": "success", "window_id": win_id})

        elif cmd == "create_qrcode_window":
            _, content, duration_seconds, caption, reply_queue = request
            win_id = self.add_qrcode_window(content, duration_seconds, caption)
            reply_queue.put({"status": "success", "window_id": win_id})

        elif cmd == "close_window":
            _, window_id, reply_queue = request
            if window_id:
                self.close_window(window_id)
                reply_queue.put(
                    {
                        "status": "success",
                        "message": f"Window {window_id} closed",
                    }
                )

        elif cmd == "update_window_message":
            _, window_id, msg, reply_queue = request
            if window_id and msg:
                self.update_window(window_id, msg)
                reply_queue.put(
                    {
                        "status": "success",
                        "message": f"Window {window_id} updated",
                    }
                )

        else:
            reply_queue.put({"status": "error", "message": f"Unknown command {cmd}"})

    def start_pipe_server(self) -> None:
        """Start the named pipe server thread."""
        if self._pipe_thread is None or not self._pipe_thread.is_alive():
            self._pipe_thread = threading.Thread(
                target=self._run_pipe_server,
                daemon=True,
                name="OverlayPipeServer",
            )
            self._pipe_thread.start()

    def _run_pipe_server(self) -> None:
        """Named pipe server thread function."""
        logger.info("Starting named pipe server on %s", self.pipe_name)
        print(f"🔌 Named pipe server starting on {self.pipe_name}")

        while not self.shutdown_event.is_set():
            try:
                # Create named pipe
                pipe_handle = win32pipe.CreateNamedPipe(
                    self.pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE
                    | win32pipe.PIPE_READMODE_MESSAGE
                    | win32pipe.PIPE_WAIT,
                    1,  # Max instances
                    65536,  # Out buffer size
                    65536,  # In buffer size
                    0,  # Default timeout
                    None,  # Security attributes
                )

                if pipe_handle == win32file.INVALID_HANDLE_VALUE:
                    logger.error("Failed to create named pipe")
                    time.sleep(1)
                    continue

                logger.debug("Waiting for client connection...")

                # Wait for client connection with timeout
                try:
                    win32pipe.ConnectNamedPipe(pipe_handle, None)
                    logger.info("Client connected to named pipe")
                    print("👤 Client connected to named pipe")

                    # Handle client communication
                    self._handle_pipe_client(pipe_handle)

                except pywintypes.error as e:
                    if e.winerror == ERROR_NO_DATA:
                        logger.debug("Client disconnected")
                        print("👋 Client disconnected")
                    else:
                        msg = f"Pipe connection error: {e}"
                        logger.exception(msg)
                        print(f"❌ Pipe connection error: {e}")

                finally:
                    with contextlib.suppress(Exception):
                        win32file.CloseHandle(pipe_handle)

            except Exception as e:
                msg = f"Error in pipe server: {e}"
                logger.exception(msg)
                time.sleep(1)

        logger.info("Pipe server thread shutting down")

    def _handle_pipe_client(self, pipe_handle) -> None:  # noqa: ANN001
        """Handle communication with a connected pipe client."""
        while not self.shutdown_event.is_set():
            try:
                # Read message from client
                result, data = win32file.ReadFile(pipe_handle, 4096)
                if result == 0 and data:
                    message = data.decode("utf-8")
                    logger.debug("Received pipe message: %s", message)

                    try:
                        # Parse JSON message
                        command_data = json.loads(message)
                        response = self._process_pipe_command(command_data)

                        # Send response back to client
                        response_data = json.dumps(response).encode("utf-8")
                        win32file.WriteFile(pipe_handle, response_data)

                    except json.JSONDecodeError as e:
                        msg = f"Invalid JSON received: {e}"
                        logger.exception(msg)
                        error_response = json.dumps({"error": "Invalid JSON"}).encode(
                            "utf-8"
                        )
                        win32file.WriteFile(pipe_handle, error_response)

                else:
                    # Client disconnected
                    break

            except pywintypes.error as e:
                if e.winerror == ERROR_BROKEN_PIPE:
                    logger.debug("Client disconnected (broken pipe)")
                    break
                if e.winerror == ERROR_NO_DATA:
                    logger.debug("Client disconnected (no data)")
                    break
                msg = f"Pipe read error: {e}"
                logger.exception(msg)
                break
            except Exception as e:
                msg = f"Error handling pipe client: {e}"
                logger.exception(msg)
                break

    def _process_pipe_command(self, command_data: dict) -> dict:
        """
        Instead of calling .create_*_window directly, we push into the
        command_queue a tuple ending in a reply_queueueue, then wait on it.
        """
        cmd = command_data.get("command")
        args = command_data.get("args", {})
        reply_queue = queue.Queue()

        if cmd == "create_highlight":
            rect = tuple(args["rect"])
            timeout = args.get("timeout_seconds", 3)
            self.command_queue.put(("create_highlight", rect, timeout, reply_queue))

        elif cmd == "create_countdown":
            msg = args.get("message_text", "")
            secs = args.get("countdown_seconds", 3)
            self.command_queue.put(("create_countdown", msg, secs, reply_queue))

        elif cmd == "create_elapsed_time":
            msg = args.get("message_text", "")
            self.command_queue.put(("create_elapsed_time", msg, reply_queue))

        elif cmd == "create_qrcode_window":
            content = args.get("data", "")
            duration_seconds = args.get("duration", 5)
            caption = args.get("caption", "")
            self.command_queue.put(
                (
                    "create_qrcode_window",
                    content,
                    duration_seconds,
                    caption,
                    reply_queue,
                )
            )

        elif cmd == "close_window":
            window_id = args.get("window_id", "")
            self.command_queue.put(("close_window", window_id, reply_queue))

        elif cmd == "update_window_message":
            window_id = args.get("window_id", "")
            new_message = args.get("new_message", "")
            self.command_queue.put(
                ("update_window_message", window_id, new_message, reply_queue)
            )

        elif cmd == "take_break":
            duration_seconds = args.get("duration_seconds", "")
            self.command_queue.put(("take_break", duration_seconds, reply_queue))

        elif cmd == "cancel_break":
            self.command_queue.put(("cancel_break", reply_queue))

        else:
            return {"status": "error", "message": f"Unknown command {cmd}"}

        # Wait for the reply (or timeout)
        try:
            return reply_queue.get(timeout=10)
        except queue.Empty:
            return {"status": "error", "message": "Command timed out"}

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
        win32gui.InvalidateRect(self.hwnd, None, True)
        threading.Timer(duration_s, lambda: self._remove_rectangle(rid)).start()
        return rid

    def _remove_rectangle(self, rid):
        self.rectangles = [r for r in self.rectangles if r["id"] != rid]
        win32gui.InvalidateRect(self.hwnd, None, True)

    def remove_qrcode_window(self, qr_id: int):
        """
        Immediately deletes the QR-window from the screen.
        """
        if qr_id in self.qrcodes:
            del self.qrcodes[qr_id]
            win32gui.InvalidateRect(self.hwnd, None, True)

    def add_elapsed_time_window(self, message_text):
        cid = self._next_countdown_id
        self._next_countdown_id += 1
        self.countdowns[cid] = {
            "message": message_text,
            "order": self._countdown_order,
        }
        win32gui.InvalidateRect(self.hwnd, None, True)
        self.response_queue.put(cid)
        return cid

    def add_countdown_window(self, message_text, countdown_seconds):
        cid = self._next_countdown_id
        self._next_countdown_id += 1
        now = time.time()
        self._countdown_order += 1

        self.countdowns[cid] = {
            "message": message_text,
            "end_time": now + countdown_seconds,
            "remaining": countdown_seconds,
            "order": self._countdown_order,
        }
        # first tick in one second
        threading.Timer(1.0, lambda: self._tick_countdown(cid)).start()
        win32gui.InvalidateRect(self.hwnd, None, True)
        return cid

    def add_qrcode_window(
        self, metadata: str | dict, timeout_seconds: int, caption: str | None = None
    ) -> int:
        """
        Create a QR-code overlay that lives for `timeout_seconds` and then auto-removes.
        Returns the qr_id.
        """
        qr_id = self._next_qrcode_id
        self._next_qrcode_id += 1
        self._qrcode_order += 1

        # 1) Prepare the data string
        data = metadata if isinstance(metadata, str) else json.dumps(metadata)

        # 2) Build QR matrix
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

        # 3) Store all info in self.qrcodes
        self.qrcodes[qr_id] = {
            "matrix": matrix,
            "qr_size": qr_size,
            "pix_per_mod": pix_per_mod,
            "padding": padding,
            "caption": caption or "",
            "order": self._qrcode_order,
        }

        # 4) Schedule auto-removal
        threading.Timer(
            timeout_seconds, lambda rid=qr_id: self.remove_qrcode_window(rid)
        ).start()

        # 5) Trigger an immediate repaint
        win32gui.InvalidateRect(self.hwnd, None, True)
        return qr_id

    def _tick_countdown(self, window_id: int):
        cd = self.countdowns.get(window_id)
        if not cd:
            return

        now = time.time()
        remaining_float = cd["end_time"] - now
        remaining_int = math.ceil(remaining_float)

        if remaining_int <= 0:
            # show “0” then remove
            cd["remaining"] = 0
            win32gui.InvalidateRect(self.hwnd, None, True)
            del self.countdowns[window_id]
            win32gui.InvalidateRect(self.hwnd, None, True)
        else:
            cd["remaining"] = remaining_int
            win32gui.InvalidateRect(self.hwnd, None, True)

            # schedule the next tick exactly when remaining_int drops by 1
            # next_target = end_time - (remaining_int - 1)
            next_target = cd["end_time"] - (remaining_int - 1)
            delay = max(next_target - now, 0.01)
            threading.Timer(delay, lambda: self._tick_countdown(window_id)).start()

    def close_window(self, window_id: int):
        """
        Immediately remove the countdown box for window_id (if it exists).
        """
        if window_id in self.countdowns:
            del self.countdowns[window_id]
            win32gui.InvalidateRect(self.hwnd, None, True)

    def update_window(self, window_id: int, new_msg: str):
        """ "
        Change the text of a countdown or elapsed‐time window and repaint.
        Returns True if that window existed (and was updated), False otherwise.
        """
        cd = self.countdowns.get(window_id)
        if not cd:
            return False

        cd["message"] = new_msg
        # For countdown windows, keep the remaining time untouched
        # For elapsed ones, they just display the new message

        # Force a repaint so the new text shows up right away
        win32gui.InvalidateRect(self.hwnd, None, True)
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

        # clear to transparent
        br = win32gui.CreateSolidBrush(self._transparent_key)
        win32gui.FillRect(hdc, full, br)
        win32gui.DeleteObject(br)

        # draw your rectangles
        for rect in self.rectangles:
            draw_highlight_rectangle(hdc, rect)

        # draw stacked countdowns / elapsed
        for idx, (_, cd) in enumerate(
            sorted(self.countdowns.items(), key=lambda item: item[1]["order"])
        ):
            position = get_countdown_position(idx, full)
            draw_countdown_window(hdc, cd, position)

        box_gap = 10
        top_start = 20 + len(self.countdowns) * (80 + box_gap)  # below countdowns

        for idx, (_, qr_code) in enumerate(
            sorted(self.qrcodes.items(), key=lambda i: i[1]["order"])
        ):
            total = qr_code["qr_size"] + 2 * qr_code["padding"]
            position = get_qrcode_position(idx, total, box_gap, top_start, full)
            draw_qrcode(hdc, qr_code, position=position)

        win32gui.EndPaint(hwnd, ps)


def signal_handler(sig: int, frame: FrameType | None) -> None:  # noqa: ARG001
    print("\nReceived shutdown signal, cleaning up...")  # noqa: T201
    # Add any cleanup logic here if needed
    sys.exit(0)


def main() -> None:
    print("🔧 OverlayManager - Windows Overlay Application")
    print("================================================")

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal
    print("✅ Signal handlers configured")

    # Create and start your overlay manager
    print("🚀 Starting OverlayManager...")
    overlay_manager = OverlayManager()
    print("✅ OverlayManager initialized successfully")
    print(f"📡 Named pipe server: {overlay_manager.pipe_name}")
    print("🎯 Application ready - overlay windows can now be created")
    print("💡 Press Ctrl+C to shutdown gracefully")
    print()
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)  # Sleep to prevent busy waiting

    except KeyboardInterrupt:
        print("\nShutting down gracefully...")  # noqa: T201
    finally:
        # Clean up resources if needed
        print("🧹 Cleaning up resources...")
        overlay_manager.shutdown()
        print("👋 OverlayManager shutdown complete")


if __name__ == "__main__":
    main()
