"""A controllable named-pipe server used to exercise failure modes of the client.

The real Rust server always answers every request. This fake lets a test decide,
per request, whether to answer, delay, stay silent forever or drop the connection.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

import pywintypes
import win32event
import win32file
import win32pipe
import winerror

PIPE_BUFFER_SIZE = 65_536

# Sentinel a handler returns to close the session without answering.
CLOSE_SESSION = object()

Handler = Callable[[dict[str, Any], "Session"], Any]


class Session:
    """Per-connection bookkeeping exposed to handlers."""

    def __init__(self, session_id: int) -> None:
        self.session_id = session_id
        self.requests: list[dict[str, Any]] = []


class FakePipeServer:
    """Accepts named-pipe clients and delegates every request to ``handler``.

    ``handler(request, session)`` may return:

    * a ``dict`` or ``bytes``: written back as the response,
    * ``None``: no response at all; the session keeps reading,
    * ``CLOSE_SESSION``: the server side of the pipe is closed immediately.
    """

    def __init__(self, pipe_name: str, handler: Handler) -> None:
        self.pipe_name = pipe_name
        self.pipe_path = rf"\\.\pipe\{pipe_name}"
        self.handler = handler
        self.sessions: list[Session] = []
        self.write_errors: list[int] = []
        self._lock = threading.Lock()
        self._stop_event = win32event.CreateEvent(None, True, False, None)
        self._ready_event = threading.Event()
        self._accept_thread: threading.Thread | None = None
        self._session_threads: list[threading.Thread] = []

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> FakePipeServer:
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name=f"fake-pipe-accept-{self.pipe_name}"
        )
        self._accept_thread.daemon = True
        self._accept_thread.start()
        if not self._ready_event.wait(5.0):
            raise RuntimeError("fake pipe server did not start listening")
        return self

    def stop(self) -> None:
        win32event.SetEvent(self._stop_event)
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=5.0)
        with self._lock:
            threads = list(self._session_threads)
        for thread in threads:
            thread.join(timeout=5.0)

    def __enter__(self) -> FakePipeServer:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # -- observation helpers ---------------------------------------------------------

    @property
    def requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                request for session in self.sessions for request in session.requests
            ]

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self.sessions)

    # -- internals -------------------------------------------------------------------

    def _accept_loop(self) -> None:
        while True:
            handle = win32pipe.CreateNamedPipe(
                self.pipe_path,
                win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED,
                win32pipe.PIPE_TYPE_MESSAGE
                | win32pipe.PIPE_READMODE_MESSAGE
                | win32pipe.PIPE_WAIT,
                win32pipe.PIPE_UNLIMITED_INSTANCES,
                PIPE_BUFFER_SIZE,
                PIPE_BUFFER_SIZE,
                0,
                None,
            )
            self._ready_event.set()

            overlapped = pywintypes.OVERLAPPED()
            overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
            try:
                rc = win32pipe.ConnectNamedPipe(handle, overlapped)
            except pywintypes.error:
                win32file.CloseHandle(handle)
                return

            if rc == winerror.ERROR_IO_PENDING:
                waited = win32event.WaitForMultipleObjects(
                    [overlapped.hEvent, self._stop_event], False, win32event.INFINITE
                )
                if waited != win32event.WAIT_OBJECT_0:
                    win32file.CancelIo(handle)
                    win32file.CloseHandle(handle)
                    return
            elif win32event.WaitForSingleObject(self._stop_event, 0) == (
                win32event.WAIT_OBJECT_0
            ):
                win32file.CloseHandle(handle)
                return

            with self._lock:
                session = Session(len(self.sessions) + 1)
                self.sessions.append(session)
                thread = threading.Thread(
                    target=self._session_loop,
                    args=(handle, session),
                    name=f"fake-pipe-session-{session.session_id}",
                )
                thread.daemon = True
                self._session_threads.append(thread)
            thread.start()

    def _session_loop(self, handle: Any, session: Session) -> None:
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
        try:
            while True:
                request_bytes = self._read_message(handle, overlapped)
                if request_bytes is None:
                    return
                request = json.loads(request_bytes.decode("utf-8"))
                with self._lock:
                    session.requests.append(request)

                result = self.handler(request, session)
                if result is CLOSE_SESSION:
                    return
                if result is None:
                    continue

                payload = (
                    result if isinstance(result, bytes) else json.dumps(result).encode()
                )
                if not self._write_message(handle, overlapped, payload):
                    return
        finally:
            try:
                win32pipe.DisconnectNamedPipe(handle)
            except pywintypes.error:
                pass
            win32file.CloseHandle(handle)

    def _read_message(self, handle: Any, overlapped: Any) -> bytes | None:
        win32event.ResetEvent(overlapped.hEvent)
        buffer = win32file.AllocateReadBuffer(PIPE_BUFFER_SIZE)
        try:
            rc, buffer = win32file.ReadFile(handle, buffer, overlapped)
            if rc == winerror.ERROR_IO_PENDING:
                waited = win32event.WaitForMultipleObjects(
                    [overlapped.hEvent, self._stop_event], False, win32event.INFINITE
                )
                if waited != win32event.WAIT_OBJECT_0:
                    win32file.CancelIo(handle)
                    try:
                        win32file.GetOverlappedResult(handle, overlapped, True)
                    except pywintypes.error:
                        pass
                    return None
            count = win32file.GetOverlappedResult(handle, overlapped, True)
        except pywintypes.error:
            return None
        if count == 0:
            return None
        return bytes(buffer[:count])

    def _write_message(self, handle: Any, overlapped: Any, payload: bytes) -> bool:
        win32event.ResetEvent(overlapped.hEvent)
        try:
            rc, _ = win32file.WriteFile(handle, payload, overlapped)
            if rc == winerror.ERROR_IO_PENDING:
                waited = win32event.WaitForMultipleObjects(
                    [overlapped.hEvent, self._stop_event], False, win32event.INFINITE
                )
                if waited != win32event.WAIT_OBJECT_0:
                    win32file.CancelIo(handle)
                    try:
                        win32file.GetOverlappedResult(handle, overlapped, True)
                    except pywintypes.error:
                        pass
                    return False
            win32file.GetOverlappedResult(handle, overlapped, True)
        except pywintypes.error as exc:
            with self._lock:
                self.write_errors.append(exc.winerror)
            return False
        return True
