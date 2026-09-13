#!/usr/bin/env python3
"""Promote an approved G Generation Advance POC to the canonical main TIP.

POC ROMs stay date-stamped under ``outputs`` for review and rollback evidence.
Only this command writes the approved artifact, and it always writes the
fixed filename ``SD Gundam GGeneration Advance (Korean).gba`` at the root of
the advance project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ggen_advance_project_paths import (
    LATEST_MERGED_ANALYSIS,
    LATEST_POC_MANIFEST,
    LATEST_POC_ROM,
    MAIN_TIP_BACKUP_ROOT,
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"gate failed: invalid manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"gate failed: manifest is not an object: {path}")
    return value


def backup_current_tip(timestamp: str, reason: str) -> dict[str, str] | None:
    if not MAIN_TIP_ROM.exists():
        return None
    safe_reason = "".join(char if char.isalnum() or char in "-_" else "_" for char in reason).strip("_")
    backup_dir = MAIN_TIP_BACKUP_ROOT / f"{timestamp}_{safe_reason or 'replacement'}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_rom = backup_dir / MAIN_TIP_ROM.name
    shutil.copy2(MAIN_TIP_ROM, backup_rom)
    result = {
        "path": advance_relative(backup_rom),
        "sha256": sha256(backup_rom.read_bytes()),
        "size": backup_rom.stat().st_size,
    }
    if MAIN_TIP_MANIFEST.exists():
        backup_manifest = backup_dir / MAIN_TIP_MANIFEST.name
        shutil.copy2(MAIN_TIP_MANIFEST, backup_manifest)
        result["manifest_path"] = advance_relative(backup_manifest)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=LATEST_POC_ROM)
    parser.add_argument("--candidate-manifest", type=Path, default=LATEST_POC_MANIFEST)
    parser.add_argument("--reason", default="approved_20260836_measured_followup")
    args = parser.parse_args()

    candidate = args.candidate.resolve()
    candidate_manifest_path = args.candidate_manifest.resolve()
    if not candidate.is_file():
        raise SystemExit(f"gate failed: candidate ROM does not exist: {candidate}")
    if not candidate.is_relative_to(MAIN_TIP_ROM.parents[0].resolve()):
        raise SystemExit("gate failed: candidate must remain inside the advance project")
    if not candidate_manifest_path.is_file():
        raise SystemExit(f"gate failed: candidate manifest does not exist: {candidate_manifest_path}")

    candidate_manifest = read_json(candidate_manifest_path)
    output_meta = candidate_manifest.get("output", {})
    verification = candidate_manifest.get("verification", {})
    actual = candidate.read_bytes()
    actual_sha = sha256(actual)
    if verification.get("result") != "PASS":
        raise SystemExit("gate failed: candidate manifest verification is not PASS")
    if int(output_meta.get("size", -1)) != len(actual):
        raise SystemExit("gate failed: candidate size differs from its manifest")
    if str(output_meta.get("sha256", "")).lower() != actual_sha:
        raise SystemExit("gate failed: candidate SHA-256 differs from its manifest")
    if len(actual) != 32 * 1024 * 1024:
        raise SystemExit("gate failed: approved GBA main TIP must be 32 MiB")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    previous = None
    if MAIN_TIP_ROM.exists() and sha256(MAIN_TIP_ROM.read_bytes()) != actual_sha:
        previous = backup_current_tip(timestamp, args.reason)
    atomic_write(MAIN_TIP_ROM, actual)
    if sha256(MAIN_TIP_ROM.read_bytes()) != actual_sha:
        raise SystemExit("gate failed: canonical main TIP failed post-write hash check")

    translation_source = TRANSLATION_MERGED_JSON if TRANSLATION_MERGED_JSON.exists() else LATEST_MERGED_ANALYSIS
    translation_meta = {
        "path": advance_relative(translation_source),
        "sha256": sha256(translation_source.read_bytes()) if translation_source.exists() else None,
    }
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_approved_main_tip",
        "status": "approved_main_tip",
        "canonical_path": advance_relative(MAIN_TIP_ROM),
        "size": len(actual),
        "sha256": actual_sha,
        "approved_at_utc": datetime.now(timezone.utc).isoformat(),
        "promotion_reason": args.reason,
        "source_poc": {
            "path": advance_relative(candidate),
            "manifest_path": advance_relative(candidate_manifest_path),
            "sha256": actual_sha,
            "verification": verification,
        },
        "translation_source": translation_meta,
        "previous_main_tip_backup": previous,
        "policy": {
            "approved_output_filename_is_fixed": MAIN_TIP_ROM.name,
            "poc_outputs_remain_date_stamped": True,
            "promotion_is_the_only_canonical_writer": True,
            "parent_project_references_forbidden": True,
        },
    }
    atomic_write(MAIN_TIP_MANIFEST, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
