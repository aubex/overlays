from __future__ import annotations

import os
import signal
import subprocess
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator


_SERVER_EXE = "overlays-server.exe"
_PACKAGE_NAME = "overlays"
_INTERRUPT_GRACE_SECONDS = 10
_TERMINATE_WAIT_SECONDS = 5


class _ConsoleInterrupt(Exception):
    """Raised when the launcher receives a console interrupt signal."""


@contextmanager
def bundled_server_path() -> Iterator[Path]:
    resource = resources.files(_PACKAGE_NAME).joinpath(_SERVER_EXE)
    if not resource.is_file():
        raise FileNotFoundError(
            "Bundled overlays server executable is missing from the installed package."
        )

    with resources.as_file(resource) as executable:
        yield executable


def main() -> int:
    with bundled_server_path() as executable:
        process = subprocess.Popen(
            [os.fspath(executable)],
            env=os.environ.copy(),
        )

        with _handle_console_interrupts():
            try:
                return process.wait()
            except (KeyboardInterrupt, _ConsoleInterrupt):
                return _wait_for_interrupted_process(process)


@contextmanager
def _handle_console_interrupts() -> Iterator[None]:
    previous_handlers: dict[int, object] = {}

    def raise_interrupt(signum: int, frame: object) -> None:
        raise _ConsoleInterrupt

    for signum in _console_signal_numbers():
        previous_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, raise_interrupt)

    try:
        yield
    finally:
        for signum, previous_handler in previous_handlers.items():
            signal.signal(signum, previous_handler)


def _console_signal_numbers() -> tuple[int, ...]:
    handled = [signal.SIGINT]
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is not None:
        handled.append(sigbreak)
    return tuple(handled)


def _wait_for_interrupted_process(process: subprocess.Popen[bytes]) -> int:
    try:
        return process.wait(timeout=_INTERRUPT_GRACE_SECONDS)
    except KeyboardInterrupt:
        process.terminate()
        return _wait_for_terminated_process(process)
    except subprocess.TimeoutExpired:
        process.terminate()
        return _wait_for_terminated_process(process)


def _wait_for_terminated_process(process: subprocess.Popen[bytes]) -> int:
    try:
        return process.wait(timeout=_TERMINATE_WAIT_SECONDS)
    except KeyboardInterrupt:
        process.kill()
        return process.wait()
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            return process.wait()
        except KeyboardInterrupt:
            return process.wait()
