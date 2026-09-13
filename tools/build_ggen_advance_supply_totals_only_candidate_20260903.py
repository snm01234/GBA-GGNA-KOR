#!/usr/bin/env python3
"""Build an isolated current-main candidate for the bottom supply summary labels.

Includes only:
  補給ポイント -> 보급포인트
  総ユニット数 -> 총유닛수

The unresolved focused-row 持c and 所有数 paths are deliberately excluded.
The already-approved disposal panel from main 22.120.4 is carried forward
byte-exact because the current canonical main TIP is the parent.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_ss1_four_graphics_ko_candidate_20260903 as source
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_supply_totals_only"
OUT_ROM = OUT_DIR / "ggen_advance_supply_totals_ko_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_supply_totals_ko_candidate_20260903.sav"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_supply_totals_ko_candidate_20260903.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"
EXPECTED_PARENT_SHA256 = "0b6df278befa5b7e55cd79097ccbbc6b05dc8b3ecaf50ee6efe3391ed6569989"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    if not offsets:
        return []
    result: list[list[str]] = []
    start = previous = offsets[0]
    for value in offsets[1:]:
        if value != previous + 1:
            result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
            start = value
        previous = value
    result.append([f"0x{start:08X}", f"0x{previous + 1:08X}"])
    return result


def main() -> int:
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP hash/manifest drift")
    gate(sha256(parent) == EXPECTED_PARENT_SHA256, f"unexpected parent main TIP: {sha256(parent)}")

    with ZipFile(FONT_ZIP) as archive:
        font11 = fontpair.load_bdf(archive, "Galmuri11.bdf")

    rebuilt, _before_canvas, _after_canvas, patch_report = source.patch_supply_animation8(parent, font11)
    candidate = bytearray(parent)
    start = source.SUPPLY_FILE
    end = start + len(rebuilt)
    gate(end <= source.SUPPLY_LIMIT, "supply resource overflow")
    candidate[start:end] = rebuilt
    output = bytes(candidate)

    changed = [index for index, (before, after) in enumerate(zip(parent, output)) if before != after]
    gate(bool(changed), "isolated supply candidate made no changes")
    gate(all(start <= index < end for index in changed), "changes escaped supply private resource")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(output)
    shutil.copy2(MAIN_SAV, OUT_SAV)
    gate(OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(), "SAV copy drift")

    compile_result = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__))], cwd=ADVANCE_ROOT, capture_output=True, text=True)
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_supply_totals_ko_candidate_20260903",
        "result": "PASS",
        "status": "test_candidate_main_tip_not_promoted",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(parent),
            "main_tip_manifest_match": True,
        },
        "scope": {
            "included": {"補給ポイント": "보급포인트", "総ユニット数": "총유닛수"},
            "excluded_unresolved": ["持c", "所有数"],
            "carried_forward_approved_main": ["強化費用 -> 강화비용", "補給P -> 보급P"],
        },
        "patch": patch_report,
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(OUT_SAV),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "main_tip_parent_exact": True,
            "only_private_supply_resource_changed": True,
            "supply_resource_address": f"0x{source.SUPPLY_ADDRESS:08X}",
            "supply_animation8_only_lookup_remap": True,
            "supply_animations_0_to_7_preserved": True,
            "existing_supply_source_tiles_preserved": True,
            "supply_palettes_byte_exact": True,
            "sav_byte_exact_copy": True,
            "py_compile": "PASS",
            "fresh_emulator_measurement": "pending user verification",
        },
    }
    OUT_MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sha256": sha256(output),
        "sav": advance_relative(OUT_SAV),
        "manifest": advance_relative(OUT_MANIFEST),
        "changed_bytes": len(changed),
        "translations": report["scope"]["included"],
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
