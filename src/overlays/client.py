import json
import logging
import os
import sys
import threading
import time
from types import TracebackType
from typing import Any, Self

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import pywintypes
    import win32event
    import win32file
    import win32pipe
    import winerror
else:  # pragma: no cover - exercised only on non-Windows platforms
    pywintypes = None  # type: ignore[assignment]
    win32event = None  # type: ignore[assignment]
    win32file = None  # type: ignore[assignment]
    win32pipe = None  # type: ignore[assignment]
    winerror = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 5000

# Largest response the client accepts; matches the server's pipe buffer size.
_RESPONSE_BUFFER_SIZE = 65_536

# After a failed connection attempt a client instance waits this long before it
# probes the pipe again, so callers holding an instance do not pay for a probe on
# every overlay call while the server is down.
_RECONNECT_COOLDOWN_SECONDS = 1.0

# A server that accepts connections but never answers is expensive to probe: each
# probe costs a full timeout. Such pipes are paused with exponential backoff.
_UNRESPONSIVE_BACKOFF_INITIAL_SECONDS = 1.0
_UNRESPONSIVE_BACKOFF_MAX_SECONDS = 30.0

# Win32 errors that mean "this pipe connection is gone": invalid handle, broken pipe,
# pipe being closed, pipe not connected, operation aborted.
_CONNECTION_LOST_ERRORS = frozenset({6, 109, 232, 233, 995})

_server_unavailable_warning_emitted = False


def _warn_server_unavailable_once(message: str, *args: Any) -> None:
    """Log a warning once per outage so missing-server issues stay visible without spamming."""
    global _server_unavailable_warning_emitted  # noqa: PLW0603
    if _server_unavailable_warning_emitted:
        logger.debug(message, *args)
        return

    logger.warning(message, *args)
    _server_unavailable_warning_emitted = True


def _reset_server_unavailable_warning() -> None:
    global _server_unavailable_warning_emitted  # noqa: PLW0603
    _server_unavailable_warning_emitted = False


_backoff_lock = threading.Lock()
# pipe path -> (monotonic time until which connects are skipped, last delay in seconds)
_unresponsive_backoff: dict[str, tuple[float, float]] = {}


def _unresponsive_backoff_active(pipe_path: str) -> bool:
    with _backoff_lock:
        entry = _unresponsive_backoff.get(pipe_path)
    return entry is not None and time.monotonic() < entry[0]


def _register_unresponsive(pipe_path: str) -> float:
    """Record that the server on ``pipe_path`` accepted a request but never answered."""
    with _backoff_lock:
        entry = _unresponsive_backoff.get(pipe_path)
        if entry is None:
            delay = _UNRESPONSIVE_BACKOFF_INITIAL_SECONDS
        else:
            delay = min(entry[1] * 2, _UNRESPONSIVE_BACKOFF_MAX_SECONDS)
        _unresponsive_backoff[pipe_path] = (time.monotonic() + delay, delay)
    return delay


def _clear_unresponsive_backoff(pipe_path: str) -> None:
    with _backoff_lock:
        _unresponsive_backoff.pop(pipe_path, None)


def _reset_backoff_state() -> None:
    """Forget every recorded outage. Intended for tests."""
    with _backoff_lock:
        _unresponsive_backoff.clear()


class _PipeTimeout(Exception):
    """The deadline passed before the pipe operation completed."""


class _PipeAborted(Exception):
    """The pending pipe operation was aborted by ``OverlayClient.disconnect()``."""


class _PipeConnection:
    """One client handle to the overlay pipe, driven with overlapped (asynchronous) I/O.

    Every read and write is bounded by a deadline and can additionally be aborted from
    another thread. A cancelled operation is always waited for, so the kernel never
    writes into a buffer Python has already released.
    """

    def __init__(self, handle: Any) -> None:
        self.handle = handle
        self._io_event = win32event.CreateEvent(None, True, False, None)
        self._abort_event = win32event.CreateEvent(None, True, False, None)
        self._overlapped = pywintypes.OVERLAPPED()
        self._overlapped.hEvent = self._io_event

    @classmethod
    def open(cls, pipe_path: str, timeout_ms: int) -> Self:
        """Connect to ``pipe_path``; raises ``pywintypes.error`` when that fails."""
        win32pipe.WaitNamedPipe(pipe_path, max(1, timeout_ms))
        handle = win32file.CreateFile(
            pipe_path,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            win32file.FILE_FLAG_OVERLAPPED,
            None,
        )
        try:
            win32pipe.SetNamedPipeHandleState(
                handle, win32pipe.PIPE_READMODE_MESSAGE, None, None
            )
        except pywintypes.error:
            win32file.CloseHandle(handle)
            raise
        return cls(handle)

    def send(self, payload: bytes, deadline: float) -> None:
        win32event.ResetEvent(self._io_event)
        rc, _ = win32file.WriteFile(self.handle, payload, self._overlapped)
        written = self._complete(rc, deadline)
        if written != len(payload):
            raise pywintypes.error(
                winerror.ERROR_NO_DATA, "WriteFile", "incomplete pipe write"
            )

    def receive(self, deadline: float) -> bytes:
        win32event.ResetEvent(self._io_event)
        buffer = win32file.AllocateReadBuffer(_RESPONSE_BUFFER_SIZE)
        rc, buffer = win32file.ReadFile(self.handle, buffer, self._overlapped)
        count = self._complete(rc, deadline)
        return bytes(buffer[:count])

    def abort(self) -> None:
        """Wake up a thread blocked in ``send``/``receive``; safe from any thread."""
        win32event.SetEvent(self._abort_event)

    def close(self) -> None:
        handle, self.handle = self.handle, None
        for resource in (handle, self._io_event, self._abort_event):
            if resource is None:
                continue
            try:
                win32file.CloseHandle(resource)
            except (pywintypes.error, OSError) as exc:
                logger.debug("Error closing pipe resource: %s", exc)
        self._io_event = None
        self._abort_event = None

    def _complete(self, rc: int, deadline: float) -> int:
        if rc == winerror.ERROR_IO_PENDING:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            waited = win32event.WaitForMultipleObjects(
                [self._io_event, self._abort_event],
                False,
                min(remaining_ms, 0xFFFFFFFE),
            )
            if waited != win32event.WAIT_OBJECT_0:
                self._cancel_pending_io()
                if waited == win32event.WAIT_TIMEOUT:
                    raise _PipeTimeout
                raise _PipeAborted
        return win32file.GetOverlappedResult(self.handle, self._overlapped, True)

    def _cancel_pending_io(self) -> None:
        try:
            win32file.CancelIo(self.handle)
        except pywintypes.error:
            pass
        try:
            # Block until the cancelled operation has really completed.
            win32file.GetOverlappedResult(self.handle, self._overlapped, True)
        except pywintypes.error:
            pass


class OverlayClient:
    """
    Client for communicating with the overlay server via named pipe.
    Can be used from a separate Python process and shared between threads.
    Gracefully handles cases where the server is unavailable.

    Every call returns within ``timeout`` milliseconds. That budget covers waiting
    for a concurrent call on the same instance, connecting, sending the command and
    receiving the answer. A server that does not answer in time is treated as gone:
    the connection is dropped, so its late answer can never be delivered to a later
    call, and the client reconnects lazily with a backoff.
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT_MS) -> None:
        """
        Initialize the OverlayClient.

        Args:
            timeout (int): Upper bound in milliseconds for each client call.

        """
        pipe_name = os.environ.get("OVERLAY_PIPE_NAME", "overlay_manager")
        self.pipe_name = rf"\\.\pipe\{pipe_name}"
        self.timeout = timeout
        self.pipe_handle = None
        self.server_available = False
        self._connection: _PipeConnection | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._retry_at = 0.0
        self._connect()

    def _connect(self, timeout_ms: int | None = None) -> None:
        """Connect to the named pipe server, waiting at most ``timeout_ms``."""
        if not _IS_WINDOWS:
            self.server_available = False
            self.pipe_handle = None
            logger.debug(
                "Overlay client is disabled on non-Windows platforms; "
                "overlay commands will be ignored."
            )
            return

        if _unresponsive_backoff_active(self.pipe_name):
            self.server_available = False
            self.pipe_handle = None
            logger.debug(
                "Skipping connection to overlay server on pipe %s while it is paused "
                "after not answering.",
                self.pipe_name,
            )
            return

        if timeout_ms is None:
            timeout_ms = self.timeout

        try:
            connection = _PipeConnection.open(self.pipe_name, timeout_ms)
        except pywintypes.error as e:
            self.server_available = False
            self.pipe_handle = None
            logger.debug(
                "Overlay server connection failed for pipe %s: %s", self.pipe_name, e
            )
            _warn_server_unavailable_once(
                "Overlay server not available on pipe %s; overlay commands will be ignored until it is running.",
                self.pipe_name,
            )
            return

        self._connection = connection
        self.pipe_handle = connection.handle
        self.server_available = True
        _reset_server_unavailable_warning()
        logger.info("Connected to overlay server pipe")

    def _ensure_connected(self, deadline: float) -> bool:
        """Reconnect lazily if needed; returns whether a connection is available."""
        if self._connection is not None:
            return True
        if self._closed:
            return False

        now = time.monotonic()
        if now < self._retry_at:
            return False

        remaining_ms = max(0, int((deadline - now) * 1000))
        self._connect(min(self.timeout, remaining_ms))
        if self._connection is None:
            self._retry_at = time.monotonic() + _RECONNECT_COOLDOWN_SECONDS
            return False
        return True

    def _send_command(
        self, command: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Send a command to the overlay server and return the response.
        Returns an "ignored" response if the server is unavailable, busy or silent.

        Args:
            command (str): Command name
            args (Dict[str, Any]): Command arguments

        Returns:
            Dict[str, Any]: Response from the server or an ignored response

        """
        deadline = time.monotonic() + self.timeout / 1000.0

        if not self._lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            logger.debug(
                "Ignoring overlay command '%s' because another overlay call on pipe %s "
                "is still in progress.",
                command,
                self.pipe_name,
            )
            return {"status": "ignored", "reason": "busy"}

        try:
            if not self._ensure_connected(deadline):
                _warn_server_unavailable_once(
                    "Ignoring overlay command '%s' because the server is not available on pipe %s.",
                    command,
                    self.pipe_name,
                )
                return {"status": "ignored", "reason": "server_unavailable"}

            connection = self._connection
            message = json.dumps({"command": command, "args": args or {}}).encode(
                "utf-8"
            )

            try:
                connection.send(message, deadline)
                data = connection.receive(deadline)
            except _PipeTimeout:
                self._handle_unresponsive(command)
                return {"status": "ignored", "reason": "timeout"}
            except _PipeAborted:
                self._drop_connection()
                logger.debug(
                    "Overlay command '%s' was aborted because the client disconnected.",
                    command,
                )
                return {"status": "ignored", "reason": "disconnected"}
            except pywintypes.error as e:
                if e.winerror in _CONNECTION_LOST_ERRORS:
                    self._handle_connection_lost(command)
                    return {"status": "ignored", "reason": "connection_lost"}
                logger.debug("Error sending command '%s': %s", command, e)
                self._drop_connection()
                return {"status": "ignored", "reason": "communication_error"}

            if not data:
                self._handle_connection_lost(command)
                return {"status": "ignored", "reason": "connection_lost"}

            try:
                response = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                logger.debug(
                    "Invalid response from server for command '%s': %s", command, e
                )
                # The stream is out of step; start over with a fresh connection.
                self._drop_connection()
                return {"status": "ignored", "reason": "invalid_response"}

            _clear_unresponsive_backoff(self.pipe_name)
            self._retry_at = 0.0
            return response
        finally:
            self._lock.release()

    def _drop_connection(self) -> None:
        """Close the pipe handle and mark the server as unavailable."""
        connection, self._connection = self._connection, None
        self.pipe_handle = None
        self.server_available = False
        if connection is not None:
            connection.close()

    def _handle_connection_lost(self, command: str | None = None) -> None:
        """Handle lost connection by marking server as unavailable."""
        if command is None:
            _warn_server_unavailable_once(
                "Connection to overlay server on pipe %s was lost; future overlay commands will be ignored until it is running again.",
                self.pipe_name,
            )
        else:
            _warn_server_unavailable_once(
                "Connection to overlay server on pipe %s was lost while handling '%s'; future overlay commands will be ignored until it is running again.",
                self.pipe_name,
                command,
            )
        self._drop_connection()

    def _handle_unresponsive(self, command: str) -> None:
        """Handle a server that accepted a command but did not answer in time."""
        delay = _register_unresponsive(self.pipe_name)
        _warn_server_unavailable_once(
            "Overlay server on pipe %s did not answer '%s' within %d ms; dropping the "
            "connection and pausing overlay commands for %.0f s.",
            self.pipe_name,
            command,
            self.timeout,
            delay,
        )
        self._drop_connection()

    def create_countdown_window(
        self, message_text: str, countdown_seconds: int = 3
    ) -> bool:
        """
        Create a countdown window.

        Args:
            message_text (str): Message to display
            countdown_seconds (int): Countdown duration in seconds

        Returns:
            bool: True if successful, False if server unavailable

        """
        response = self._send_command(
            "create_countdown",
            {"message_text": message_text, "countdown_seconds": countdown_seconds},
        )
        return response.get("status") == "success"

    def create_highlight_window(
        self, rect: tuple[int, int, int, int], timeout_seconds: int = 3
    ) -> bool:
        """
        Create a highlight window.

        Args:
            rect (Tuple[int, int, int, int]): Rectangle coordinates (left, top, right, bottom)
            timeout_seconds (int): Display duration in seconds

        Returns:
            bool: True if successful, False if server unavailable

        """
        response = self._send_command(
            "create_highlight", {"rect": list(rect), "timeout_seconds": timeout_seconds}
        )
        return response.get("status") == "success"

    def create_elapsed_time_window(self, message_text: str) -> int | None:
        """
        Create an elapsed time window.

        Args:
            message_text (str): Initial message text

        Returns:
            Optional[int]: Window ID if successful, None if server unavailable

        """
        response = self._send_command(
            "create_elapsed_time", {"message_text": message_text}
        )
        if response.get("status") == "success":
            return response.get("window_id")
        return None

    def create_qrcode_window(
        self, data: str | dict, duration: int = 5, caption: str | None = None
    ) -> int:
        """
        Create a timed QR Code window.

        Args:
            data (str | dict): Content of the QR code
            duration (int): Specifies how long the QR code should be displayed
            caption (str | None): Optional caption text

        Returns:
            Optional[int]: Window ID if successful, None if server unavailable

        """
        response = self._send_command(
            "create_qrcode_window",
            {"data": data, "duration": duration, "caption": caption or ""},
        )
        if response.get("status") == "success":
            return response.get("window_id")
        return None

    def close_window(self, window_id: int) -> bool:
        """
        Close a window by ID.

        Args:
            window_id (int): ID of the window to close

        Returns:
            bool: True if successful, False if server unavailable

        """
        response = self._send_command("close_window", {"window_id": window_id})
        return response.get("status") == "success"

    def update_window_message(self, window_id: int, new_message: str) -> bool:
        """
        Update a window's message.

        Args:
            window_id (int): ID of the window to update
            new_message (str): New message text

        Returns:
            bool: True if successful, False if server unavailable

        """
        response = self._send_command(
            "update_window_message",
            {"window_id": window_id, "new_message": new_message},
        )
        return response.get("status") == "success"

    def take_break(self, duration_seconds: int) -> bool:
        """
        Tell the overlay server to take a break.

        Args:
            duration_seconds (int): Break duration in seconds

        Returns:
            bool: True if successful, False if server unavailable

        """
        response = self._send_command(
            "take_break", {"duration_seconds": duration_seconds}
        )
        return response.get("status") == "success"

    def cancel_break(self) -> bool:
        """
        Cancel an active break.

        Returns:
            bool: True if successful, False if server unavailable

        """
        response = self._send_command("cancel_break")
        return response.get("status") == "success"

    def close_all_windows(self) -> bool:
        """
        Close all active overlay windows.

        Returns:
            bool: True if successful, False if server unavailable

        """
        response = self._send_command("close_all")
        return response.get("status") == "success"

    def is_available(self) -> bool:
        """
        Check if the overlay server is available.

        Returns:
            bool: True if server is available and connected

        """
        return self.server_available and self.pipe_handle is not None

    def disconnect(self) -> None:
        """Disconnect from the pipe server and stop reconnecting.

        Safe to call from any thread: a call in progress on another thread is
        aborted and returns an "ignored" response.
        """
        self._closed = True
        connection = self._connection
        if connection is not None:
            connection.abort()

        acquired = self._lock.acquire(timeout=self.timeout / 1000.0 + 1.0)
        try:
            self._drop_connection()
        finally:
            if acquired:
                self._lock.release()
        logger.debug("Disconnected from overlay server pipe")

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit."""
        self.disconnect()


class RemoteElapsedTimeWindow:
    """A client-side control for an elapsed-time window running in the overlay server."""

    def __init__(self, window_id: int | None, client: OverlayClient) -> None:
        """
        Initialize the remote window control.

        Args:
            window_id (Optional[int]): ID of the window (None if server unavailable)
            client (OverlayClient): Client instance to communicate through

        """
        self.window_id = window_id
        self.client = client
        self._closed = False
        self._server_unavailable = window_id is None

    def update_message(self, new_message: str) -> bool:
        """
        Update the window's message.

        Args:
            new_message (str): New message text

        Returns:
            bool: True if successful, False if server unavailable or window closed

        """
        if self._closed:
            logger.debug("Cannot update message - window has been closed")
            return False

        if self._server_unavailable or self.window_id is None:
            logger.debug("Cannot update message - server unavailable")
            return False

        return self.client.update_window_message(self.window_id, new_message)

    def close(self) -> bool:
        """
        Close the window.

        Returns:
            bool: True if successful or already closed

        """
        if self._closed:
            return True

        if self._server_unavailable or self.window_id is None:
            self._closed = True
            return True

        success = self.client.close_window(self.window_id)
        if success:
            self._closed = True
        return success

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit."""
        if not self._closed:
            self.close()


_overlay_client: OverlayClient | None = None
_overlay_client_lock = threading.Lock()


def get_overlay_client(timeout: int = DEFAULT_TIMEOUT_MS) -> OverlayClient:
    """Return the shared client, creating a new one while the current one is unusable."""
    global _overlay_client  # noqa: PLW0603
    with _overlay_client_lock:
        if _overlay_client is None or not _overlay_client.is_available():
            _overlay_client = OverlayClient(timeout=timeout)
        return _overlay_client


if __name__ == "__main__":
    """
    Run this script to test the OverlayClient.
    Make sure the overlay server is running first.
    """
    print("OverlayClient Test Suite")  # noqa: T201
    print("=" * 40)  # noqa: T201
    print("Make sure the overlay server is running before starting these tests.")  # noqa: T201
    input("Press Enter to continue...")

    try:
        with OverlayClient() as client:
            # Create elapsed time window using the control wrapper
            print("Creating controlled elapsed time window...")  # noqa: T201
            window_id = client.create_elapsed_time_window("Task starting...")

            if window_id:
                with RemoteElapsedTimeWindow(window_id, client) as window:
                    # Simulate a long-running task with updates
                    for i in range(5):
                        time.sleep(1)
                        window.update_message(f"Step {i + 1}/5 completed...")

                    window.update_message("Task completed!")
                    time.sleep(1)
                    # Window will be automatically closed when exiting context

            print("Remote window control demo completed!")  # noqa: T201

    except ConnectionError as e:
        print(f"Failed to connect to overlay server: {e}")  # noqa: T201
    except Exception as e:  # noqa: BLE001
        print(f"Error during demo: {e}")  # noqa: T201
