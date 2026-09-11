#!/usr/bin/env python3
"""Build ulb-extension.zip from the unpacked extension/ folder (no .git, no nested zip)."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OUT = ROOT / "ulb-extension.zip"
SKIP_NAMES = {".git", "__pycache__", ".DS_Store", "ulb-extension.zip", "pack.py", "pack.ps1", "test"}
SKIP_SUFFIXES = {".pyc", ".log", ".zip"}


def should_skip(path: Path) -> bool:
    if path.name in SKIP_NAMES:
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def main() -> int:
    files: list[Path] = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_NAMES for part in rel.parts):
            continue
        if should_skip(p):
            continue
        files.append(p)

    if not (ROOT / "manifest.json").is_file():
        raise SystemExit("manifest.json missing — run from extension/")

    if OUT.exists():
        OUT.unlink()

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(files):
            # Zip so extracting creates ./extension/manifest.json when user
            # unzips next to a folder named extension — actually put files at
            # archive root so Load unpacked = the unzipped folder.
            arc = p.relative_to(ROOT).as_posix()
            zf.write(p, arcname=arc)

    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes, {len(files)} files)")

    for dest_dir in (REPO / "docs", REPO / "web-publish"):
        if dest_dir.is_dir():
            dest = dest_dir / "ulb-extension.zip"
            shutil.copy2(OUT, dest)
            print(f"Copied → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
