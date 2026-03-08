from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pywintypes
import win32pipe


VENV_DIR = Path(".tmp-dist/smoke-venv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the built wheel into a clean venv and smoke-test the CLI/server path."
    )
    parser.add_argument("wheel", type=Path, help="Path to the built wheel")
    return parser.parse_args()


def wait_for_pipe(pipe_name: str, timeout_seconds: float = 10.0) -> None:
    pipe_path = rf"\\.\pipe\{pipe_name}"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            win32pipe.WaitNamedPipe(pipe_path, 100)
            return
        except pywintypes.error:
            time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {pipe_path}")


def create_clean_venv(venv_dir: Path, wheel: Path) -> Path:
    if venv_dir.exists():
        shutil.rmtree(venv_dir)

    subprocess.run(["uv", "venv", str(venv_dir)], check=True)
    python_executable = venv_dir / "Scripts" / "python.exe"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python_executable), str(wheel)],
        check=True,
    )
    return python_executable


def stop_process(process: subprocess.Popen[bytes]) -> int:
    if process.poll() is not None:
        return process.returncode

    try:
        process.send_signal(signal.CTRL_BREAK_EVENT)
        return process.wait(timeout=5)
    except (AttributeError, subprocess.TimeoutExpired, ValueError):
        process.terminate()
        try:
            return process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait(timeout=5)


def main() -> int:
    args = parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file():
        raise FileNotFoundError(f"Wheel not found: {wheel}")

    python_executable = create_clean_venv(VENV_DIR.resolve(), wheel)
    server_script = python_executable.parent / "overlays.exe"

    pipe_name = f"overlay_manager_smoke_{uuid.uuid4().hex}"
    env = os.environ.copy()
    env["OVERLAY_PIPE_NAME"] = pipe_name

    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log_path = VENV_DIR.resolve() / "server.log"
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            [str(server_script)],
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

        exit_code = None
        try:
            wait_for_pipe(pipe_name)
            subprocess.run(
                [
                    str(python_executable),
                    "-c",
                    (
                        "from overlays.client import OverlayClient; "
                        "client = OverlayClient(timeout=2000); "
                        "assert client.is_available(); "
                        "response = client._send_command("
                        "'create_countdown', "
                        "{'message_text': 'wheel smoke', 'countdown_seconds': 1}"
                        "); "
                        "assert response.get('status') == 'success', response; "
                        "client.disconnect()"
                    ),
                ],
                check=True,
                env=env,
            )
        finally:
            exit_code = stop_process(process)

    log_output = log_path.read_text(encoding="utf-8", errors="replace")
    if exit_code != 0:
        raise RuntimeError(
            "Packaged launcher exited unsuccessfully during shutdown. "
            f"exit_code={exit_code}\n{log_output}"
        )
    if (
        "Traceback (most recent call last):" in log_output
        or "KeyboardInterrupt" in log_output
    ):
        raise RuntimeError(
            "Packaged launcher printed a traceback during Ctrl+C shutdown.\n"
            f"{log_output}"
        )

    print(f"Wheel smoke test passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
