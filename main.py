import contextlib
import ctypes
import json
import logging
import queue
import random
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import FrameType
from typing import ClassVar
import qrcode
import pywintypes
import win32api
import win32con
import win32file
import win32gui
import win32pipe
from typing import Self
from helpers import (
    GDIContext,
    create_layered_window,
    draw_centered_text,
    draw_colored_background,
    measure_text,
    set_layered_window_attributes,
)

logger = logging.getLogger("pyfenster")

logger = logging.getLogger(__name__)

ERROR_NO_DATA = 232  # client disconnected
ERROR_BROKEN_PIPE = 109
RECT_CORRECT_DIMENSIONS = 4


class OverlayManager:
    _instance: Self = None

    def __new__(class_, *args, **kwargs):
        if not isinstance(class_._instance, class_):
            class_._instance = object.__new__(class_, *args, **kwargs)
        return class_._instance

    def __init__(self, pipe_name: str = r"\\.\pipe\overlay_manager") -> None:
        """Initialize the OverlayManager instance with named pipe support."""
        self.command_queue = queue.Queue()
        self.response_queue = queue.Queue()
        self.shutdown_event = threading.Event()
        self.thread = None
        self.pipe_thread = None
        self.pipe_name = pipe_name
        self.start_thread()
        self.start_pipe_server()

    def start_thread(self) -> None:
        """Start the manager thread if it's not already running."""
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(
                target=self._run_manager_thread,
                daemon=True,
                name="OverlayManager",
            )
            self.thread.start()

    def start_pipe_server(self) -> None:
        """Start the named pipe server thread."""
        if self.pipe_thread is None or not self.pipe_thread.is_alive():
            self.pipe_thread = threading.Thread(
                target=self._run_pipe_server,
                daemon=True,
                name="OverlayPipeServer",
            )
            self.pipe_thread.start()

    def create_countdown_window(
        self, message_text: str, countdown_seconds: int = 3
    ) -> None:
        """
        Create a countdown window with the specified message and duration.

        Args:
            message_text (str): Message to display in the window
            countdown_seconds (int, optional): Duration in seconds. Defaults to 3

        """
        self.command_queue.put(("create_countdown", message_text, countdown_seconds))

    def create_qrcode_window(
        self, data: str | dict, duration: int = 5, caption: str | None = None
    ) -> None:
        """
        Display metadata as a QR code for a limited time.

        Args:
            data (str | dict): QR code content
            duration (int): Duration of the QR code
            caption (str | None): Optional caption text
        """
        self.command_queue.put(("create_qrcode", data, duration, caption))

    def create_highlight_window(
        self,
        rect: tuple[int, int, int, int],
        timeout_seconds: int = 3,
    ) -> None:
        """
        Create a highlight window for the specified rectangle and duration.

        Args:
            rect (Tuple[int, int, int, int]): Rectangle coordinates (left, top, right, bottom)
            timeout_seconds (int, optional): Duration in seconds. Defaults to 3

        """
        self.command_queue.put(("create_highlight", rect, timeout_seconds))

    def create_elapsed_time_window(
        self, message_text: str
    ) -> "ElapsedTimeWindowControl|None":
        """
        Create an elapsed time window with the specified message.

        Args:
            message_text (str): Initial message to display in the window

        Returns:
            ElapsedTimeWindowControl|None: Control object for the window, or None if creation fails

        """
        self.start_thread()  # Ensure thread is running
        self.command_queue.put(("create_elapsed", message_text))
        try:
            # Wait for response with timeout
            window_id = self.response_queue.get(timeout=5.0)
            return ElapsedTimeWindowControl(window_id, self)
        except queue.Empty:
            logger.debug("Timeout waiting for elapsed time window creation")
            return None

    def close_window(self, window_id: int) -> None:
        """
        Close the window with the specified ID.

        Args:
            window_id (int): Identifier of the window to close

        """
        logger.debug("Sending close command for window %s", window_id)
        self.command_queue.put(("close_window", window_id))

    def update_window_message(self, window_id: int, new_message: str) -> None:
        """
        Update the message of the window with the specified ID.

        Args:
            window_id (int): Identifier of the window to update
            new_message (str): New message text to display

        """
        self.command_queue.put(("update_message", window_id, new_message))

    def take_break(self, duration_seconds: int) -> bool:
        """
        Take a break for the specified duration by ignoring any incoming commands
        until the break is over. All commands received during the break (except
        cancel_break) will be discarded.

        Args:
            duration_seconds (int): Duration of the break in seconds

        Returns:
            bool: True if break was successfully initiated, False otherwise

        """
        self.command_queue.put(("take_break", duration_seconds))

        try:
            # Wait for confirmation with timeout
            response = self.response_queue.get(timeout=5.0)
        except queue.Empty:
            logger.debug("Timeout waiting for break confirmation")
            return False
        else:
            return response == "break_started"

    def cancel_break(self) -> bool:
        """
        Cancel an active break, allowing the manager to resume processing commands immediately.
        This is the only command that will be processed during a break.

        Returns:
            bool: True if break was successfully canceled, False otherwise

        """
        self.command_queue.put(("cancel_break",))

        try:
            # Wait for confirmation with timeout
            response = self.response_queue.get(timeout=5.0)
        except queue.Empty:
            logger.debug("Timeout waiting for break cancellation confirmation")
            return False
        else:
            return response == "break_canceled"

    def shutdown(self) -> None:
        """Shut down the manager thread and clean up resources."""
        self.shutdown_event.set()

        if self.thread and self.thread.is_alive():
            # Send shutdown signal
            self.command_queue.put(None)
            # Wait for thread to terminate gracefully
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                logger.warning("Manager thread did not terminate gracefully")
            self.thread = None

        if self.pipe_thread and self.pipe_thread.is_alive():
            # Pipe thread should terminate when shutdown_event is set
            self.pipe_thread.join(timeout=5)
            if self.pipe_thread.is_alive():
                logger.warning("Pipe thread did not terminate gracefully")
            self.pipe_thread = None

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

    def _process_pipe_command(self, command_data: dict) -> dict:  # noqa:C901, PLR0911, PLR0912
        """Process a command received via named pipe."""
        try:
            command = command_data.get("command")
            args = command_data.get("args", {})

            if command == "create_countdown":
                message_text = args.get("message_text", "")
                countdown_seconds = args.get("countdown_seconds", 3)
                self.create_countdown_window(message_text, countdown_seconds)
                return {"status": "success", "message": "Countdown window created"}

            if command == "create_highlight":
                rect = args.get("rect")
                timeout_seconds = args.get("timeout_seconds", 3)
                if rect and len(rect) == RECT_CORRECT_DIMENSIONS:
                    self.create_highlight_window(tuple(rect), timeout_seconds)
                    return {"status": "success", "message": "Highlight window created"}
                return {"status": "error", "message": "Invalid rect parameter"}

            if command == "create_elapsed_time":
                message_text = args.get("message_text", "")
                control = self.create_elapsed_time_window(message_text)
                if control:
                    return {
                        "status": "success",
                        "window_id": control.window_id,
                        "message": "Elapsed time window created",
                    }
                return {
                    "status": "error",
                    "message": "Failed to create elapsed time window",
                }

            if command == "create_qrcode_window":
                data = args.get("data", "")
                duration = args.get("duration", "")
                caption = args.get("caption", "")
                control = self.create_qrcode_window(data, duration, caption)
                return {"status": "success", "message": "QR code window created"}

            if command == "close_window":
                window_id = args.get("window_id")
                if window_id is not None:
                    self.close_window(window_id)
                    return {
                        "status": "success",
                        "message": f"Window {window_id} closed",
                    }
                return {"status": "error", "message": "window_id parameter required"}

            if command == "update_window_message":
                window_id = args.get("window_id")
                new_message = args.get("new_message", "")
                if window_id is not None:
                    self.update_window_message(window_id, new_message)
                    return {
                        "status": "success",
                        "message": f"Window {window_id} message updated",
                    }
                return {"status": "error", "message": "window_id parameter required"}

            if command == "take_break":
                duration_seconds = args.get("duration_seconds", 60)
                success = self.take_break(duration_seconds)
                if success:
                    return {
                        "status": "success",
                        "message": f"Break started for {duration_seconds} seconds",
                    }
                return {"status": "error", "message": "Failed to start break"}

            if command == "cancel_break":
                success = self.cancel_break()
                if success:
                    return {"status": "success", "message": "Break canceled"}
                return {"status": "error", "message": "Failed to cancel break"}

        except Exception as e:
            msg = f"Error processing pipe command: {e}"
            logger.exception(msg)
            return {"status": "error", "message": str(e)}

        else:
            return {"status": "error", "message": f"Unknown command: {command}"}

    def _run_manager_thread(self) -> None:  # noqa: C901, PLR0912, PLR0915
        """Main thread function that processes commands."""
        try:
            # Import Windows-specific modules here to avoid issues if not available
            import win32con
            import win32gui

            # Create thread-specific GDI resources
            thread_hdc = win32gui.CreateCompatibleDC(0)
            thread_font = win32gui.GetStockObject(win32con.DEVICE_DEFAULT_FONT)

            window_manager = WindowManager()
            window_map = {}
            next_window_id = 1
            break_until = 0

            while not self.shutdown_event.is_set():
                try:
                    # Check if we're still in break mode
                    current_time = time.time()
                    if current_time < break_until:
                        # We're in break mode
                        # Pump Windows messages to keep UI responsive
                        win32gui.PumpWaitingMessages()

                        # Check queue but only process cancel_break commands
                        # All other commands are discarded during break mode
                        try:
                            request = self.command_queue.get(timeout=0.1)
                            if request is not None:
                                if (
                                    isinstance(request, tuple)
                                    and request[0] == "cancel_break"
                                ):
                                    logger.debug(
                                        "Processing cancel_break during break mode"
                                    )
                                    print("🔄 Break cancelled (was active)")
                                    # Reset the break timer to immediately end the break
                                    break_until = 0
                                    # Send confirmation back
                                    self.response_queue.put("break_canceled")
                                else:
                                    # Discard any other commands received during break
                                    logger.debug(
                                        "Discarding command during break: %s", request
                                    )
                        except queue.Empty:
                            # No commands in queue, continue with the break
                            pass

                        # Short sleep to prevent CPU spinning
                        time.sleep(0.01)
                        continue

                    # Get command from queue
                    try:
                        request = self.command_queue.get(timeout=0.1)
                    except queue.Empty:
                        win32gui.PumpWaitingMessages()
                        continue

                    if request is None:
                        # Shutdown signal
                        break

                    logger.debug("Received command: %s", request)

                    if not isinstance(request, tuple) or not request:
                        logger.debug("Invalid request format: %s", request)
                        continue

                    command = request[0]

                    if command == "take_break":
                        _, duration_seconds = request
                        logger.debug("Taking a break for %s seconds", duration_seconds)
                        print(f"☕ Taking a break for {duration_seconds} seconds")
                        # Set the break duration
                        break_until = time.time() + duration_seconds
                        # Send confirmation back
                        self.response_queue.put("break_started")

                    elif command == "cancel_break":
                        logger.debug(
                            "Canceling break command received (but no active break)"
                        )
                        print("🔄 Break cancelled")
                        # No active break to cancel, but still send a confirmation
                        self.response_queue.put("break_canceled")

                    elif command == "create_countdown":
                        _, message_text, countdown_seconds = request
                        print(
                            f"⏰ Creating countdown window: '{message_text}' ({countdown_seconds}s)"
                        )
                        window = CountdownWindow(
                            message_text, countdown_seconds, window_manager
                        )
                        window.set_resources(thread_hdc, thread_font)
                        window_manager.active_windows.append(window)
                        window_manager.realign_windows()

                    elif command == "create_highlight":
                        _, rect, timeout_seconds = request
                        print(
                            f"🔍 Creating highlight window: {rect} ({timeout_seconds}s)"
                        )
                        window = HighlightWindow(rect, timeout_seconds, window_manager)
                        window.create_window()

                    elif command == "create_elapsed":
                        _, message_text = request
                        print(
                            f"⏱️ Creating elapsed time window: '{message_text}' (ID: {next_window_id})"
                        )
                        window = ElapsedTimeWindow(message_text, window_manager)
                        window.set_resources(thread_hdc, thread_font)
                        window_manager.active_windows.append(window)
                        window_map[next_window_id] = window
                        self.response_queue.put(next_window_id)
                        next_window_id += 1
                        window_manager.realign_windows()

                    elif command == "update_message":
                        _, window_id, new_message = request
                        if window_id in window_map:
                            window = window_map[window_id]
                            if hasattr(window, "update_message"):
                                window.update_message(new_message)

                    elif command == "close_window":
                        _, window_id = request
                        logger.debug("Attempting to close window %s", window_id)
                        print(f"❌ Closing window ID: {window_id}")
                        if window_id in window_map:
                            window = window_map[window_id]
                            logger.debug("Found window in map")
                            if hasattr(window, "hwnd") and win32gui.IsWindow(
                                window.hwnd
                            ):
                                logger.debug("Window exists, sending close command")
                                # Try the window's close method first
                                if hasattr(window, "close"):
                                    window.close()

                                if win32gui.IsWindow(window.hwnd):
                                    win32gui.PostMessage(
                                        window.hwnd, win32con.WM_CLOSE, 0, 0
                                    )

                                if win32gui.IsWindow(window.hwnd):
                                    win32gui.DestroyWindow(window.hwnd)

                            if window in window_manager.active_windows:
                                window_manager.active_windows.remove(window)
                            del window_map[window_id]
                            window_manager.realign_windows()
                    elif command == "create_qrcode":
                        _, metadata, timeout, caption = request
                        window = QRCodeWindow(
                            metadata, timeout, window_manager, caption
                        )
                        print(f"🔍 Creating QR code window: (Duration: {timeout}s)")
                        window.set_resources(thread_hdc, thread_font)
                        window_manager.active_windows.append(window)
                        window_manager.realign_windows()

                    # Clean up closed windows
                    closed_ids = []
                    for window_id, window in window_map.items():
                        if not hasattr(window, "hwnd") or not win32gui.IsWindow(
                            window.hwnd
                        ):
                            closed_ids.append(window_id)

                    for window_id in closed_ids:
                        del window_map[window_id]

                    window_manager.active_windows = [
                        w
                        for w in window_manager.active_windows
                        if hasattr(w, "hwnd") and win32gui.IsWindow(w.hwnd)
                    ]

                except Exception as exc:
                    msg = f"Error processing command: {exc}"
                    logger.exception(msg)

        except Exception as exc:
            msg = f"Error in overlay manager thread: {exc}"
            logger.exception(msg)
        finally:
            # Clean up any thread-specific GDI resources
            if "thread_hdc" in locals():
                win32gui.DeleteDC(thread_hdc)
            # Clean up any remaining windows
            if "window_map" in locals():
                for _, window in list(window_map.items()):
                    if hasattr(window, "hwnd") and win32gui.IsWindow(window.hwnd):
                        with contextlib.suppress(Exception):
                            win32gui.DestroyWindow(window.hwnd)


OVERLAY_WINDOW_CLASS = "PyFensterOverlayManagerWindow"


class BaseWindow:
    def __init__(self, class_name: str) -> None:
        """
        Initialize a base window instance.

        Args:
            class_name (str): Unique identifier for the window class

        """
        self.class_name = f"{OVERLAY_WINDOW_CLASS}_{class_name}"
        self.hInstance = win32api.GetModuleHandle(None)
        self.hwnd = None
        self.register_window_class()

    def set_resources(self, hdc: int, font: int) -> None:
        self.hdc = hdc
        self.font = font
        self.create_window()

    def register_window_class(self) -> None:
        """Register the window class with Windows."""
        wnd_class = win32gui.WNDCLASS()
        wnd_class.style = win32con.CS_HREDRAW | win32con.CS_VREDRAW
        wnd_class.lpfnWndProc = self.wnd_proc
        wnd_class.hInstance = self.hInstance
        wnd_class.hbrBackground = win32con.COLOR_WINDOW
        wnd_class.lpszClassName = self.class_name

        try:
            win32gui.RegisterClass(wnd_class)
        except win32gui.error as e:
            # Ignore "Class already exists"
            if e.winerror != 1410:  # noqa: PLR2004
                raise

    def create_window(self) -> any:
        """Abstract method to create the window - must be implemented by subclass."""
        raise NotImplementedError

    def wnd_proc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """
        Window procedure callback function.

        Args:
            hwnd (int): Window handle
            msg (int): Windows message identifier
            wparam (int): First message parameter
            lparam (int): Second message parameter

        Returns:
            int: Message processing result

        """
        if msg == win32con.WM_PAINT:
            self.on_paint(hwnd)
            return 0
        if msg == win32con.WM_TIMER:
            self.on_timer(hwnd)
            return 0
        if msg == win32con.WM_DESTROY:
            self.on_destroy(hwnd)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def on_paint(self, hwnd: int) -> any:
        """
        Handle WM_PAINT message - must be implemented by subclass.

        Args:
            hwnd (int): Window handle

        """
        raise NotImplementedError

    def on_timer(self, hwnd: int) -> any:
        """
        Handle WM_TIMER message - must be implemented by subclass.

        Args:
            hwnd (int): Window handle

        """
        raise NotImplementedError

    def on_destroy(self, hwnd: int) -> any:
        """
        Handle WM_DESTROY message - must be implemented by subclass.

        Args:
            hwnd (int): Window handle

        """
        raise NotImplementedError

    def move_window(self, x: float, y: float) -> None:
        """
        Move the window to new coordinates.

        Args:
            x (float): New x-coordinate
            y (float): New y-coordinate

        """
        if self.hwnd:
            win32gui.SetWindowPos(
                self.hwnd,
                None,
                int(x),
                int(y),
                0,
                0,
                win32con.SWP_NOZORDER | win32con.SWP_NOSIZE,
            )

    def set_timer(self, timer_id: int, interval_ms: int) -> None:
        """
        Set a timer for the window.

        Args:
            timer_id (int): Unique identifier for the timer
            interval_ms (int): Timer interval in milliseconds

        """
        ctypes.windll.user32.SetTimer(self.hwnd, timer_id, interval_ms, None)

    def safe_paint(self, hwnd: int, paint_func: Callable[[int], None]) -> None:
        """
        Safely execute a painting operation.

        Args:
            hwnd (int): Window handle
            paint_func (Callable[[int], None]): Function that takes HDC and paints

        """
        hdc, ps = win32gui.BeginPaint(hwnd)
        saved_dc = win32gui.SaveDC(hdc)
        try:
            paint_func(hdc)
        finally:
            win32gui.RestoreDC(hdc, saved_dc)
            win32gui.EndPaint(hwnd, ps)

    def create_base_window(  # noqa: PLR0913
        self,
        x: float,
        y: float,
        width: int,
        height: int,
        ex_style: int,
        style: int,
    ) -> None:
        """
        Create a base window with specified parameters.

        Args:
            x (float): X-coordinate of window position
            y (float): Y-coordinate of window position
            width (int): Window width in pixels
            height (int): Window height in pixels
            ex_style (int): Extended window style flags
            style (int): Window style flags

        """
        ex_style |= win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TRANSPARENT
        self.hwnd = create_layered_window(
            self.class_name,
            self.hInstance,
            x,
            y,
            width,
            height,
            ex_style,
            style,
        )


class CountdownWindow(BaseWindow):
    def __init__(
        self, message_text: str, countdown_seconds: int, manager: "WindowManager"
    ) -> None:
        """
        Initialize a countdown window instance.

        Args:
            message_text (str): Message to display in the window
            countdown_seconds (int): Number of seconds for the countdown
            manager (WindowManager): Reference to the window manager instance

        """
        self.message_text: str = message_text
        self.countdown_seconds: int = countdown_seconds
        self.manager: WindowManager = manager
        super().__init__(f"PyFensterCountdownClass_{id(self)}")

    def create_window(self, x: int = 0, y: int = 0) -> None:
        """
        Create and display the countdown window.

        Args:
            x (int, optional): X-coordinate for window position. Defaults to 0 (centered)
            y (int, optional): Y-coordinate for window position. Defaults to 0 (top with offset)

        """
        text: str = f"{self.message_text}\nClosing in {self.countdown_seconds} seconds"
        max_width: int = 400
        text_width: int
        text_height: int
        text_width, text_height = measure_text(self.hdc, text, max_width, self.font)

        padding: int = 20
        win_width: int = text_width + padding * 2
        win_height: int = text_height + padding * 2
        screen_x: int = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        if x == 0 and y == 0:
            x = (screen_x - win_width) // 2
            y = 20 + len(self.manager.active_windows) * (win_height + 10)

        ex_style: int = (
            win32con.WS_EX_TOPMOST
            | win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_NOACTIVATE
            | win32con.WS_EX_TOOLWINDOW
        )
        style: int = win32con.WS_POPUP

        self.create_base_window(x, y, win_width, win_height, ex_style, style)
        set_layered_window_attributes(self.hwnd, 230)
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNORMAL)
        win32gui.UpdateWindow(self.hwnd)
        self.set_timer(1, 1000)

    def on_paint(self, hwnd: int) -> None:
        """
        Handle WM_PAINT message by drawing the countdown window content.

        Args:
            hwnd (int): Window handle

        """

        def paint_func(hdc: int) -> None:
            """
            Inner paint function to draw window contents.

            Args:
                hdc (int): Device context handle

            """
            rect: tuple[int, int, int, int] = win32gui.GetClientRect(hwnd)
            draw_colored_background(hdc, rect, 200, 220, 255)
            text: str = (
                f"\n{self.message_text}\n\nClosing in {self.countdown_seconds} seconds"
            )
            draw_centered_text(hdc, rect, text)

        self.safe_paint(hwnd, paint_func)

    def on_timer(self, hwnd: int) -> None:
        """
        Handle WM_TIMER message by updating countdown and closing if complete.

        Args:
            hwnd (int): Window handle

        """
        self.countdown_seconds -= 1
        if self.countdown_seconds <= 0:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        else:
            win32gui.InvalidateRect(hwnd, None, True)  # noqa: FBT003

    def on_destroy(self, _hwnd: int) -> None:
        """
        Handle WM_DESTROY message by removing window from manager.

        Args:
            hwnd (int): Window handle

        """
        self.manager.remove_window(self)


class HighlightWindow(BaseWindow):
    colors: ClassVar[list[tuple[int, int, int]]] = [
        (255, 99, 71),  # Tomato
        (135, 206, 250),  # LightSkyBlue
        (60, 179, 113),  # MediumSeaGreen
        (255, 215, 0),  # Gold
        (186, 85, 211),  # MediumOrchid
        (255, 140, 0),  # DarkOrange
        (70, 130, 180),  # SteelBlue
        (124, 252, 0),  # LawnGreen
        (238, 130, 238),  # Violet
        (255, 105, 180),  # HotPink
        (173, 216, 230),  # LightBlue
        (0, 128, 128),  # Teal
        (255, 69, 0),  # OrangeRed
        (147, 112, 219),  # MediumPurple
        (0, 191, 255),  # DeepSkyBlue
    ]

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        timeout_seconds: int,
        manager: "WindowManager",
    ) -> None:
        """
        Initialize a highlight window instance.

        Args:
            rect (tuple[int, int, int, int]): Rectangle coordinates (left, top, right, bottom)
            timeout_seconds (int): Duration in seconds before window closes
            manager (WindowManager): Reference to the window manager instance

        """
        self.rect: tuple[int, int, int, int] = rect
        self.timeout_seconds: int = timeout_seconds
        self.manager: WindowManager = manager
        self.color: tuple[int, int, int]  # Will be set in create_window
        super().__init__(f"HighlightWindow{id(self)}")

    def create_window(self) -> None:
        """Create and display the highlight window."""
        x, y, right, bottom = self.rect
        width = right - x
        height = bottom - y

        ex_style = (
            win32con.WS_EX_TOPMOST
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_LAYERED
            | win32con.WS_EX_NOACTIVATE
            | win32con.WS_EX_TOOLWINDOW
        )
        style = win32con.WS_POPUP

        self.create_base_window(x, y, width, height, ex_style, style)
        self.color = random.choice(self.colors)  # noqa: S311
        set_layered_window_attributes(self.hwnd, 128)
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
        win32gui.UpdateWindow(self.hwnd)
        self.set_timer(1, 1000)

    def on_paint(self, hwnd: int) -> None:
        """
        Handle WM_PAINT message by drawing the highlight rectangle.

        Args:
            hwnd (int): Window handle

        """

        def paint_func(hdc: int) -> None:
            """
            Inner paint function to draw the colored rectangle.

            Args:
                hdc (int): Device context handle

            """
            rect: tuple[int, int, int, int] = win32gui.GetClientRect(hwnd)
            pen: int = win32gui.CreatePen(
                win32con.PS_SOLID, 5, win32api.RGB(*self.color)
            )
            brush: int = win32gui.CreateSolidBrush(win32api.RGB(*self.color))
            with GDIContext(hdc, pen=pen, brush=brush):
                win32gui.Rectangle(hdc, rect[0], rect[1], rect[2], rect[3])

        self.safe_paint(hwnd, paint_func)

    def on_timer(self, hwnd: int) -> None:
        """
        Handle WM_TIMER message by updating timeout and closing if complete.

        Args:
            hwnd (int): Window handle

        """
        self.timeout_seconds -= 1
        if self.timeout_seconds <= 0:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        else:
            win32gui.InvalidateRect(hwnd, None, True)  # noqa: FBT003

    def on_destroy(self, _hwnd: int) -> None:
        """
        Handle WM_DESTROY message by removing window from manager.

        Args:
            hwnd (int): Window handle

        """
        self.manager.remove_window(self)


class ElapsedTimeWindow(BaseWindow):
    def __init__(self, message_text: str, manager: "WindowManager") -> None:
        """
        Initialize an elapsed time window instance.

        Args:
            message_text (str): Initial message to display in the window
            manager (WindowManager): Reference to the window manager instance

        """
        self.message_text: str = message_text
        self.elapsed_seconds: int = 0
        self.manager: WindowManager = manager
        self.running: bool = True
        super().__init__(f"ElapsedTimeWindow{id(self)}")

    def update_message(self, new_message: str) -> None:
        """
        Update the displayed message and refresh the window.

        Args:
            new_message (str): New message text to display

        """
        self.message_text = new_message
        if self.hwnd:
            win32gui.InvalidateRect(self.hwnd, None, True)  # noqa: FBT003

    def create_window(self, x: int = 0, y: int = 0) -> None:
        """
        Create and display the elapsed time window.

        Args:
            x (int, optional): X-coordinate for window position. Defaults to 0 (centered)
            y (int, optional): Y-coordinate for window position. Defaults to 0 (top with offset)

        """
        text: str = f"{self.message_text}\nElapsed time: {self.elapsed_seconds} seconds"
        max_width: int = 400
        text_width: int
        text_height: int
        text_width, text_height = measure_text(self.hdc, text, max_width, self.font)

        padding: int = 20
        win_width: int = text_width + padding * 2
        win_height: int = text_height + padding * 2
        screen_x: int = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        if x == 0 and y == 0:
            x = (screen_x - win_width) // 2
            y = 20 + len(self.manager.active_windows) * (win_height + 10)

        ex_style: int = (
            win32con.WS_EX_TOPMOST
            | win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_NOACTIVATE
            | win32con.WS_EX_TOOLWINDOW
        )
        style: int = win32con.WS_POPUP
        self.create_base_window(x, y, win_width, win_height, ex_style, style)

        set_layered_window_attributes(self.hwnd, 230)
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNORMAL)
        win32gui.UpdateWindow(self.hwnd)
        self.set_timer(1, 1000)

    def on_paint(self, hwnd: int) -> None:
        """
        Handle WM_PAINT message by drawing the elapsed time window content.

        Args:
            hwnd (int): Window handle

        """

        def paint_func(hdc: int) -> None:
            """
            Inner paint function to draw window contents.

            Args:
                hdc (int): Device context handle

            """
            rect: tuple[int, int, int, int] = win32gui.GetClientRect(hwnd)
            draw_colored_background(hdc, rect, 200, 220, 255)
            text: str = (
                f"\n{self.message_text}\n\nElapsed time: {self.elapsed_seconds} seconds"
            )
            draw_centered_text(hdc, rect, text)

        self.safe_paint(hwnd, paint_func)

    def on_timer(self, hwnd: int) -> None:
        """
        Handle WM_TIMER message by updating elapsed time or closing if stopped.

        Args:
            hwnd (int): Window handle

        """
        if self.running:
            self.elapsed_seconds += 1
            win32gui.InvalidateRect(hwnd, None, True)  # noqa: FBT003
        else:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

    def stop(self) -> None:
        """Stop the elapsed time counter and trigger window closure."""
        self.running = False

    def on_destroy(self, _hwnd: int) -> None:
        """
        Handle WM_DESTROY message by removing window from manager.

        Args:
            hwnd (int): Window handle

        """
        self.manager.remove_window(self)


class QRCodeWindow(BaseWindow):
    def __init__(
        self,
        metadata: str | dict,
        timeout_seconds: int,
        manager: "WindowManager",
        caption: str | None = None,
    ) -> None:
        """Initializes a QR Code window."""
        self.metadata = metadata
        self.timeout = timeout_seconds
        self.manager = manager
        self.caption = caption or ""
        self._prepare_qr_code()
        super().__init__(f"QRCodeWindow_{id(self)}")

    def _prepare_qr_code(self) -> None:
        data = (
            self.metadata
            if isinstance(self.metadata, str)
            else json.dumps(self.metadata)
        )
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=1,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        self.matrix = qr.get_matrix()
        self.module_count = len(self.matrix)
        self.pix_per_module = 6
        self.qr_size = self.module_count * self.pix_per_module
        self.padding = 10

    def create_window(self, x: int = 0, y: int = 0) -> None:
        caption_h = 0
        caption_w = 0
        if self.caption:
            caption_w, caption_h = measure_text(
                self.hdc,
                self.caption,
                max_width=self.qr_size,
                font=self.font,
            )

        # Computation of window dimensions
        win_w = max(self.qr_size, caption_w) + 2 * self.padding
        extra_gap = self.padding if self.caption else 0
        win_h = self.padding + self.qr_size + extra_gap + caption_h + self.padding

        if self.caption:
            self._caption_rect = (
                self.padding,
                self.padding + self.qr_size + extra_gap,
                win_w - self.padding,
                self.padding + self.qr_size + extra_gap + caption_h,
            )

        # X- and Y-Position
        screen_x = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        if x == 0 and y == 0:
            x = (screen_x - win_w) // 2
            y = 20 + len(self.manager.active_windows) * (win_h + 10)

        ex_style = (
            win32con.WS_EX_TOPMOST
            | win32con.WS_EX_LAYERED
            | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_NOACTIVATE
            | win32con.WS_EX_TOOLWINDOW
        )
        style = win32con.WS_POPUP

        self.create_base_window(x, y, win_w, win_h, ex_style, style)
        set_layered_window_attributes(self.hwnd, 255)
        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNORMAL)
        win32gui.UpdateWindow(self.hwnd)
        self.set_timer(1, 1000)

    def on_paint(self, hwnd: int) -> None:
        def paint(dc: int) -> None:
            # White background
            rect = win32gui.GetClientRect(hwnd)
            win32gui.FillRect(dc, rect, win32gui.GetStockObject(win32con.WHITE_BRUSH))

            # Draw QR code
            with GDIContext(dc):
                for ry, row in enumerate(self.matrix):
                    for cx, bit in enumerate(row):
                        if not bit:
                            continue
                        x0 = self.padding + cx * self.pix_per_module
                        y0 = self.padding + ry * self.pix_per_module
                        x1 = x0 + self.pix_per_module
                        y1 = y0 + self.pix_per_module
                        pen = win32gui.CreatePen(
                            win32con.PS_SOLID, 0, win32api.RGB(0, 0, 0)
                        )
                        brush = win32gui.CreateSolidBrush(win32api.RGB(0, 0, 0))
                        with GDIContext(dc, pen=pen, brush=brush):
                            win32gui.Rectangle(dc, x0, y0, x1, y1)

            # 3) draw the caption (if any), neatly centered in its rect
            if self.caption:
                draw_centered_text(dc, self._caption_rect, self.caption)

        self.safe_paint(hwnd, paint)

    def on_timer(self, hwnd: int) -> None:
        self.timeout -= 1
        if self.timeout <= 0:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)

    def on_destroy(self, hwnd: int) -> None:  # noqa: ARG002
        self.manager.remove_window(self)


class WindowManager:
    def __init__(self) -> None:
        """Initialize a window manager instance."""
        self.active_windows: list[BaseWindow] = []

    def remove_window(self, window: BaseWindow) -> None:
        """
        Remove a window from the managed list and realign remaining windows.

        Args:
            window (BaseWindow): The window instance to remove

        """
        if window in self.active_windows:
            self.active_windows.remove(window)
        self.realign_windows()

    def realign_windows(self) -> None:
        """Realign all active windows vertically centered on the screen."""
        padding: int = 10
        screen_width: int = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        y_start: int = 20
        current_y: int = y_start

        for window in self.active_windows:
            if hasattr(window, "hwnd") and window.hwnd is not None:
                rect: tuple[int, int, int, int] = win32gui.GetWindowRect(window.hwnd)
                width: int = rect[2] - rect[0]
                height: int = rect[3] - rect[1]
                x: int = (screen_width - width) // 2

                win32gui.MoveWindow(window.hwnd, x, current_y, width, height, True)  # noqa: FBT003
                current_y += height + padding


@dataclass
class ElapsedTimeWindowControl:
    """
    Control class for managing an ElapsedTimeWindow instance.

    Attributes:
        window_id (int): Unique identifier for the controlled window
        overlay_manager (OverlayManager): Reference to the overlay manager instance

    """

    window_id: int
    overlay_manager: OverlayManager

    def close(self) -> None:
        """Close the associated window using the overlay manager."""
        self.overlay_manager.close_window(self.window_id)

    def update_message(self, new_message: str) -> None:
        """
        Update the message of the associated window.

        Args:
            new_message (str): New message text to display in the window

        """
        self.overlay_manager.update_window_message(self.window_id, new_message)


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
