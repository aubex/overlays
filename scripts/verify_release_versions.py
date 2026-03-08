from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


PYPROJECT = Path("pyproject.toml")
CARGO_TOML = Path("rust/overlays-server/Cargo.toml")
UV_LOCK = Path("uv.lock")
VERSION_PATTERN = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that the tag, Python package, Rust crate, and lockfile versions match."
    )
    parser.add_argument("--tag", required=True, help="Release tag, for example v2.0.0")
    return parser.parse_args()


def read_python_version() -> str:
    with PYPROJECT.open("rb") as handle:
        data = tomllib.load(handle)
    return data["project"]["version"]


def read_cargo_version() -> str:
    match = VERSION_PATTERN.search(CARGO_TOML.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError(f"Unable to read version from {CARGO_TOML}")
    return match.group(1)


def read_lock_version() -> str:
    text = UV_LOCK.read_text(encoding="utf-8")
    package_block = re.search(
        r'\[\[package\]\]\nname = "overlays"\nversion = "([^"]+)"',
        text,
        re.MULTILINE,
    )
    if package_block is None:
        raise RuntimeError(f"Unable to read overlays version from {UV_LOCK}")
    return package_block.group(1)


def main() -> int:
    args = parse_args()
    if not args.tag.startswith("v"):
        raise RuntimeError(f"Release tag must start with 'v': {args.tag}")

    expected_version = args.tag[1:]
    versions = {
        "tag": expected_version,
        "pyproject.toml": read_python_version(),
        "rust/overlays-server/Cargo.toml": read_cargo_version(),
        "uv.lock": read_lock_version(),
    }

    mismatches = [
        f"{name}={version}"
        for name, version in versions.items()
        if version != expected_version
    ]
    if mismatches:
        raise RuntimeError(
            "Release version mismatch. Expected "
            f"{expected_version}, found: {', '.join(mismatches)}"
        )

    print(f"Release versions verified: {expected_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
