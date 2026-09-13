#!/usr/bin/env python3
"""Restore the two-layer overlay identities after rebuilding map-script rows.

The map-script sheet is regenerated from the 20260827 base and then receives
its 8,089 reviewed dialogue translations.  This utility preserves the base
overlay identity while recording the map-script overlay as a separate layer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    base = json.loads(BASE.read_text(encoding="utf-8"))
    merged = json.loads(MERGED.read_text(encoding="utf-8"))
    base_identity = base["identity"]["translation_overlay_identity_sha256"]
    map_identity = merged["merge"]["translation_overlay_identity_sha256"]
    map_files = list(merged["merge"].get("overlay_files") or [])
    if len(map_files) != 1 or map_files[0].get("record_count") != 8089:
        raise SystemExit("gate failed: expected one 8,089-record map-script overlay")
    if merged["summary"].get("translated_canonical_records") != 14693:
        raise SystemExit("gate failed: translated canonical count drift")

    base_files = list(base["merge"].get("overlay_files") or [])
    merged["identity"]["translation_overlay_identity_sha256"] = base_identity
    merged["identity"]["map_script_translation_overlay_identity_sha256"] = map_identity
    merged["summary"]["translation_overlay_identity_sha256"] = base_identity
    merged["summary"]["overlay_record_count"] = int(base["summary"].get("overlay_record_count", 0)) + 8089
    merged["summary"]["overlay_translation_unit_count"] = int(
        base["summary"].get("overlay_translation_unit_count", 0)
    ) + 8089
    merged["merge"]["overlay_files"] = base_files + map_files
    merged["merge"]["batch_count"] = len(base_files) + len(map_files)
    merged["merge"]["accepted_record_count"] = int(base["merge"].get("accepted_record_count", 0)) + 8089
    merged["merge"]["translation_unit_count"] = int(base["merge"].get("translation_unit_count", 0)) + 8089
    merged["merge"]["parent_translation_overlay_identity_sha256"] = base_identity
    MERGED.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "base_overlay_identity": base_identity,
                "map_script_overlay_identity": map_identity,
                "overlay_files": len(merged["merge"]["overlay_files"]),
                "overlay_records": merged["summary"]["overlay_record_count"],
                "translated_canonical_records": merged["summary"]["translated_canonical_records"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
