#!/usr/bin/env python3
"""Archive superseded main-TIP backups and POC/test ROMs into legacy/.

Used for the v1.0.0 public-repo freeze. Records relative paths, destinations,
sizes, SHA-256 for ROM-like binaries, UTC time, and reason.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ggen_advance_project_paths import advance_relative  # noqa: E402

REASON = "v1.0.0_public_repo_freeze_archive_superseded_backups_and_poc_roms"
HASH_SUFFIXES = {".gba", ".sav", ".xdelta", ".bin"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def record_file(src: Path, dest: Path) -> dict:
    item = {
        "original_path": advance_relative(src),
        "destination": advance_relative(dest),
        "size": src.stat().st_size,
    }
    if src.suffix.lower() in HASH_SUFFIXES:
        item["sha256"] = sha256_file(src)
    return item


def move_dir(src: Path, dest: Path, moved: list[dict]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise SystemExit(f"destination already exists: {dest}")
    for path in sorted(src.rglob("*")):
        if path.is_file():
            rel = path.relative_to(src)
            moved.append(record_file(path, dest / rel))
    shutil.move(str(src), str(dest))


def move_file(src: Path, dest: Path, moved: list[dict]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise SystemExit(f"destination already exists: {dest}")
    moved.append(record_file(src, dest))
    shutil.move(str(src), str(dest))


def main() -> int:
    moved: list[dict] = []
    skipped: list[str] = []

    backup_root = ROOT / "integrated" / "main_tip" / "backups"
    backup_dest_root = ROOT / "legacy" / "main_tip_backups"
    if backup_root.is_dir():
        for child in sorted(backup_root.iterdir()):
            if child.is_dir():
                move_dir(child, backup_dest_root / child.name, moved)
            elif child.is_file():
                move_file(child, backup_dest_root / child.name, moved)
        backup_root.mkdir(parents=True, exist_ok=True)

    outputs_root = ROOT / "outputs"
    poc_dest_root = ROOT / "legacy" / "poc" / "outputs"
    if outputs_root.is_dir():
        for child in sorted(outputs_root.iterdir()):
            if child.name == "dist":
                continue
            if child.is_dir() and child.name.startswith("20"):
                move_dir(child, poc_dest_root / child.name, moved)
            else:
                skipped.append(advance_relative(child))

    dist_root = outputs_root / "dist"
    stale_names = [
        "ggen_advance_ko_main_tip.xdelta",
        "ggen_advance_ko_main_tip_xdelta.json",
        "ggen_advance_ko_main_tip_XDELTA_README.md",
    ]
    stale_dest = ROOT / "legacy" / "dist"
    if dist_root.is_dir():
        for name in stale_names:
            src = dist_root / name
            if src.is_file():
                move_file(src, stale_dest / name, moved)

    log = {
        "moved_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": REASON,
        "release_version": "1.0.0",
        "kept_local_not_moved": [
            "SD Gundam GGeneration Advance (Japan).gba",
            "SD Gundam GGeneration Advance (Korean).gba",
            "SD Gundam GGeneration Advance (Korean)_allclear.gba",
            "savebackup/",
            "outputs/dist/ (regenerated as v1.0.0 xdelta)",
        ],
        "skipped": skipped,
        "moved_count": len(moved),
        "moved": moved,
    }
    log_path = ROOT / "legacy" / "MOVE_LOG_20260913_v1_0_0_public_freeze.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"log": advance_relative(log_path), "moved_count": len(moved)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
