from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path


DEFAULT_BINARY = Path("rust/overlays-server/target/release/overlays-server.exe")
DEFAULT_OUTPUT_DIR = Path(".tmp-dist/release")
README_NAME = "README.txt"
CHECKSUMS_NAME = "SHA256SUMS.txt"
ZIP_NAME_TEMPLATE = "overlays-server-v{version}-windows-x64.zip"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the standalone GitHub release zip for overlays-server."
    )
    parser.add_argument(
        "--version", required=True, help="Release version without the v prefix"
    )
    parser.add_argument(
        "--binary",
        type=Path,
        default=DEFAULT_BINARY,
        help=f"Path to overlays-server.exe (default: {DEFAULT_BINARY})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory where the zip should be written (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bundle_readme(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "overlays-server",
                "",
                "Run overlays-server.exe to start the named-pipe overlay server.",
                "Set OVERLAY_PIPE_NAME to change the default pipe name.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_internal_checksums(output_path: Path, files: list[Path]) -> None:
    lines = [f"{sha256(path)}  {path.name}" for path in files]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_bundle(version: str, binary: Path, output_dir: Path) -> Path:
    if not binary.is_file():
        raise FileNotFoundError(f"Standalone server binary not found: {binary}")

    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = output_dir / "bundle"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    bundled_binary = staging_dir / binary.name
    shutil.copy2(binary, bundled_binary)

    readme = staging_dir / README_NAME
    write_bundle_readme(readme)

    internal_checksums = staging_dir / CHECKSUMS_NAME
    write_internal_checksums(internal_checksums, [bundled_binary, readme])

    zip_path = output_dir / ZIP_NAME_TEMPLATE.format(version=version)
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in (bundled_binary, readme, internal_checksums):
            archive.write(file_path, arcname=file_path.name)

    print(f"Built standalone release bundle: {zip_path}")
    return zip_path


def main() -> int:
    args = parse_args()
    version = args.version[1:] if args.version.startswith("v") else args.version
    build_bundle(
        version=version,
        binary=args.binary.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
