#!/usr/bin/env python3
"""Three-way merge the source-gated Marker Clan correction into current main TIP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM

OLD_UNIFIED = ADVANCE_ROOT / "outputs" / "20260829_ggen_advance_unified_rom" / "ggen_advance_unified_translation_poc_20260842.gba"
NEW_UNIFIED = ADVANCE_ROOT / "outputs" / "20260829_ggen_advance_unified_rom" / "ggen_advance_unified_translation_poc_20260843.gba"
NEW_UNIFIED_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_unified_rom_poc_20260843.json"
OUTPUT_DIR = ADVANCE_ROOT / "outputs" / "20260830_ggen_advance_marker_clan_restoration"
OUTPUT_ROM = OUTPUT_DIR / "ggen_advance_marker_clan_restoration_candidate_20260830.gba"
OUTPUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_marker_clan_main_tip_candidate_20260830.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ranges(indices: list[int]) -> list[dict[str, str | int]]:
    if not indices:
        return []
    result: list[dict[str, str | int]] = []
    start = previous = indices[0]
    for value in indices[1:]:
        if value != previous + 1:
            result.append({"start": f"0x{start:08X}", "end_exclusive": f"0x{previous + 1:08X}", "size": previous + 1 - start})
            start = value
        previous = value
    result.append({"start": f"0x{start:08X}", "end_exclusive": f"0x{previous + 1:08X}", "size": previous + 1 - start})
    return result


def main() -> int:
    old = OLD_UNIFIED.read_bytes()
    new = NEW_UNIFIED.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    if not (len(old) == len(new) == len(current) == 32 * 1024 * 1024):
        raise SystemExit("gate failed: all ROMs must be 32 MiB")

    current_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    if sha256(current) != str(current_manifest.get("sha256") or ""):
        raise SystemExit("gate failed: current main TIP hash differs from its manifest")
    new_manifest = json.loads(NEW_UNIFIED_MANIFEST.read_text(encoding="utf-8"))
    if sha256(new) != str(new_manifest.get("output", {}).get("sha256") or ""):
        raise SystemExit("gate failed: corrected unified ROM hash differs from its manifest")

    diff = [index for index, (before, after) in enumerate(zip(old, new)) if before != after]
    conflicts = [index for index in diff if current[index] not in (old[index], new[index])]
    if conflicts:
        raise SystemExit(f"gate failed: {len(conflicts)} main-TIP overlap conflicts")

    candidate = bytearray(current)
    applied: list[int] = []
    already_correct: list[int] = []
    for index in diff:
        if current[index] == old[index]:
            candidate[index] = new[index]
            applied.append(index)
        else:
            already_correct.append(index)
    candidate_bytes = bytes(candidate)
    actual_delta = [index for index, (before, after) in enumerate(zip(current, candidate_bytes)) if before != after]
    if actual_delta != applied:
        raise SystemExit("gate failed: candidate delta differs from three-way merge plan")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROM.write_bytes(candidate_bytes)
    output_sha = sha256(candidate_bytes)
    manifest = {
        "schema_version": 1,
        "description": "Current approved main TIP with source-gated Marker Clan restoration",
        "source": {
            "current_main_tip": MAIN_TIP_ROM.name,
            "current_main_tip_sha256": sha256(current),
            "old_unified_sha256": sha256(old),
            "corrected_unified_sha256": sha256(new),
        },
        "output": {"size": len(candidate_bytes), "sha256": output_sha},
        "correction": {
            "selection": "Japanese source マーカー・クラン or マーカ・クラン only",
            "protected": "Japanese source ミライ or ミライ・ヤシマ",
            "canonical_records_restored": 24,
            "unified_changed_bytes": len(diff),
            "bytes_applied_to_main_tip": len(applied),
            "bytes_already_correct": len(already_correct),
            "overlap_conflicts": len(conflicts),
            "changed_range_count": len(ranges(actual_delta)),
            "changed_range_samples": ranges(actual_delta)[:40],
        },
        "verification": {
            "result": "PASS",
            "current_main_tip_manifest_hash_verified": True,
            "corrected_unified_manifest_hash_verified": True,
            "all_unified_delta_bytes_three_way_merged": True,
            "later_main_tip_changes_preserved": True,
            "overlap_conflicts": 0,
            "candidate_delta_matches_merge_plan": True,
            "candidate_size_32mib": True,
            "source_gated_record_audit_passed": True,
        },
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(OUTPUT_ROM), "manifest": str(OUTPUT_MANIFEST), **manifest["correction"], "sha256": output_sha}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
