from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a SHA256SUMS file for release artifacts."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination SHA256SUMS.txt path",
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Files to checksum",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    lines: list[str] = []
    for file_path in args.files:
        path = file_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Cannot checksum missing file: {path}")
        lines.append(f"{sha256(path)}  {path.name}")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote checksums: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
