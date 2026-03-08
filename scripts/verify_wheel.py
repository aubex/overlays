from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


EXPECTED_EXE = "overlays/overlays-server.exe"
EXPECTED_LAUNCHER = "overlays/_server_launcher.py"
EXPECTED_ENTRYPOINTS = [
    "overlays = overlays._server_launcher:main",
    "overlays-server = overlays._server_launcher:main",
]
EXPECTED_WHEEL_MARKERS = [
    "Root-Is-Purelib: false",
    "Tag: py3-none-win_amd64",
]
EXPECTED_LAUNCHER_MARKERS = [
    "process = subprocess.Popen(",
    "except KeyboardInterrupt:",
]
UNEXPECTED_LAUNCHER_MARKERS = [
    "completed = subprocess.run(",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that the built wheel contains the bundled server and expected metadata."
    )
    parser.add_argument("wheel", type=Path, help="Path to the built wheel")
    return parser.parse_args()


def find_dist_info_member(names: list[str], suffix: str) -> str:
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one {suffix} file in wheel, found {matches}"
        )
    return matches[0]


def main() -> int:
    args = parse_args()
    wheel_path = args.wheel.resolve()
    if not wheel_path.is_file():
        raise FileNotFoundError(f"Wheel not found: {wheel_path}")

    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
        if EXPECTED_EXE not in names:
            raise RuntimeError(
                f"Wheel is missing bundled server binary: {EXPECTED_EXE}"
            )
        if EXPECTED_LAUNCHER not in names:
            raise RuntimeError(f"Wheel is missing launcher source: {EXPECTED_LAUNCHER}")

        entry_points_name = find_dist_info_member(names, "entry_points.txt")
        entry_points = archive.read(entry_points_name).decode("utf-8")
        for entry in EXPECTED_ENTRYPOINTS:
            if entry not in entry_points:
                raise RuntimeError(f"Wheel is missing console entry point: {entry}")

        launcher_source = archive.read(EXPECTED_LAUNCHER).decode("utf-8")
        for marker in EXPECTED_LAUNCHER_MARKERS:
            if marker not in launcher_source:
                raise RuntimeError(f"Wheel launcher is missing marker: {marker}")
        for marker in UNEXPECTED_LAUNCHER_MARKERS:
            if marker in launcher_source:
                raise RuntimeError(f"Wheel launcher still contains marker: {marker}")

        wheel_metadata_name = find_dist_info_member(names, "WHEEL")
        wheel_metadata = archive.read(wheel_metadata_name).decode("utf-8")
        for marker in EXPECTED_WHEEL_MARKERS:
            if marker not in wheel_metadata:
                raise RuntimeError(f"Wheel metadata is missing marker: {marker}")

    print(f"Wheel verified: {wheel_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
