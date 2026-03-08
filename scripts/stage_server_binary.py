from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DEFAULT_SOURCE = Path("rust/overlays-server/target/release/overlays-server.exe")
DEFAULT_DESTINATION = Path(".tmp-dist/package-payload/overlays-server.exe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage the Rust server binary for wheel packaging."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"Path to the built overlays-server.exe (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DESTINATION,
        help=(
            "Where the wheel build should read the bundled server binary "
            f"(default: {DEFAULT_DESTINATION})"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Rust server binary not found: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    print(f"Staged bundled server binary: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
