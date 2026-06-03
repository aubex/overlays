from __future__ import annotations

import os
import platform
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


_STAGED_BINARY = Path(".tmp-dist/package-payload/overlays-server.exe")
_SUPPORTED_MACHINES = {"amd64", "x86_64"}
_PURE_WHEEL_ENV = "OVERLAYS_PURE_WHEEL"


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        if self.target_name != "wheel":
            return
        if version == "editable":
            return

        # Pure-Python (client-only) wheel: tagged py3-none-any and installable on
        # any platform. The server binary is omitted, so downstream projects can
        # depend on overlays and run their suites on macOS/Linux, where the client
        # degrades to a no-op. Built by setting OVERLAYS_PURE_WHEEL=1.
        if os.environ.get(_PURE_WHEEL_ENV) == "1":
            return

        if platform.system() != "Windows":
            raise RuntimeError("Building the overlays wheel requires Windows.")

        if platform.machine().lower() not in _SUPPORTED_MACHINES:
            raise RuntimeError("Building the overlays wheel requires Windows x64.")

        staged_binary = Path(self.root, _STAGED_BINARY)
        if not staged_binary.is_file():
            raise FileNotFoundError(
                "Bundled server binary is missing. "
                "Run scripts/stage_server_binary.py before building the wheel."
            )

        build_data["pure_python"] = False
        build_data["tag"] = "py3-none-win_amd64"
        build_data["force_include"] = {
            str(staged_binary): "overlays/overlays-server.exe",
        }
