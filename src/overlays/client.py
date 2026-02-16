import json
import logging
import time
import os
from types import TracebackType
from typing import Any, Self

import pywintypes
import win32file
import win32pipe

logger = logging.getLogger(__name__)


class OverlayClient:
    """
    Client for communicating with OverlayManager via named pipe.
    Can be used from a separate Python process.
    Gracefully handles cases where the server is unavailable.
    """

    def __init__(self, timeout: int = 5000) -> None:
        """
        Initialize the OverlayClient.

        Args:
            pipe_name (str): Name of the pipe to connect to
            timeout (int): Connection timeout in milliseconds

        """
        pipe_name = os.environ.get("OVERLAY_PIPE_NAME", "overlay_manager")
        self.pipe_name = rf"\\.\pipe\{pipe_name}"
        self.timeout = timeout
        self.pipe_handle = None
        self.server_available = False
        self._connect()

    def _connect(self) -> None:
        """Connect to the named pipe server. Fails silently if server unavailable."""
        try:
            # Wait for pipe to become available
            win32pipe.WaitNamedPipe(self.pipe_name, self.timeout)

            # Open the pipe
            self.pipe_handle = win32file.CreateFile(
                self.pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )

            # Set pipe mode
            win32pipe.SetNamedPipeHandleState(
                self.pipe_handle, win32pipe.PIPE_READMODE_MESSAGE, None, None
            )

            self.server_available = True
            logger.info("Connected to overlay manager pipe")

        except pywintypes.error as e:
            self.server_available = False
            self.pipe_handle = None
            msg = f"Overlay manager not available: {e}"
            logger.debug(msg)

    def _send_command(
        self, command: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Send a command to the overlay manager and return the response.
        Returns empty success response if server unavailable.

        Args:
            command (str): Command name
            args (Dict[str, Any]): Command arguments

        Returns:
            Dict[str, Any]: Response from the server or empty dict if unavailable

        """
        if not self.server_available or not self.pipe_handle:
            msg = f"Ignoring command '{command}' - overlay manager not available"
            logger.debug(msg)
            return {"status": "ignored", "reason": "server_unavailable"}

        # Prepare command data
        command_data = {"command": command, "args": args or {}}

        try:
            # Send command
            message = json.dumps(command_data).encode("utf-8")
            win32file.WriteFile(self.pipe_handle, message)

            # Read response
            result, data = win32file.ReadFile(self.pipe_handle, 65536)
            if result == 0 and data:
                return json.loads(data.decode("utf-8"))

            # Connection lost
            self._handle_connection_lost()

        except pywintypes.error as e:
            if e.winerror in [109, 232]:  # Broken pipe or no data
                self._handle_connection_lost()
                return {"status": "ignored", "reason": "connection_lost"}
            msg = f"Error sending command '{command}': {e}"
            logger.debug(msg)
            return {"status": "ignored", "reason": "communication_error"}

        except json.JSONDecodeError as e:
            msg = f"Invalid response from server for command '{command}': {e}"
            logger.debug(msg)
            return {"status": "ignored", "reason": "invalid_response"}

        else:
            return {"status": "ignored", "reason": "connection_lost"}

    def _handle_connection_lost(self) -> None:
        """Handle lost connection by marking server as unavailable."""
        logger.debug("Connection to overlay manager lost")
        self.server_available = False
        self.pipe_handle = None

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
        Tell the overlay manager to take a break.

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

    def is_available(self) -> bool:
        """
        Check if the overlay manager server is available.

        Returns:
            bool: True if server is available and connected

        """
        return self.server_available and self.pipe_handle is not None

    def disconnect(self) -> None:
        """Disconnect from the pipe server."""
        if self.pipe_handle:
            try:
                win32file.CloseHandle(self.pipe_handle)
            except (pywintypes.error, OSError) as e:
                # Log the specific error but continue cleanup
                msg = f"Error closing pipe handle: {e}"
                logger.debug(msg)
            self.pipe_handle = None

        self.server_available = False
        logger.debug("Disconnected from overlay manager pipe")

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
    """A client-side control for an elapsed time window running in the overlay manager."""

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


def get_overlay_client(timeout: int = 5000) -> OverlayClient:
    global _overlay_client  # noqa: PLW0603
    if _overlay_client is None:
        _overlay_client = OverlayClient(timeout=timeout)
    return _overlay_client


if __name__ == "__main__":
    """
    Run this script to test the OverlayClient.
    Make sure the OverlayManager server is running first!
    """
    print("OverlayClient Test Suite")  # noqa: T201
    print("=" * 40)  # noqa: T201
    print("Make sure the OverlayManager server is running before starting these tests.")  # noqa: T201
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
        print(f"Failed to connect to overlay manager: {e}")  # noqa: T201
    except Exception as e:  # noqa: BLE001
        print(f"Error during demo: {e}")  # noqa: T201
