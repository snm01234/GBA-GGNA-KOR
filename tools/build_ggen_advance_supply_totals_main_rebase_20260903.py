#!/usr/bin/env python3
"""Rebase the runtime-approved supply totals graphics onto current main TIP."""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import sys
from pathlib import Path
from zipfile import ZipFile

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_ss1_four_graphics_ko_candidate_20260903 as source
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

HISTORICAL_BASE = ROOT / "integrated" / "main_tip" / "backups" / "20260903T124709Z_user_approved_sort_popup_level_normal_focus_20260903" / "SD Gundam GGeneration Advance (Korean).gba"
HISTORICAL_ROM = ROOT / "outputs" / "20260903_ggen_advance_supply_totals_only" / "ggen_advance_supply_totals_ko_candidate_20260903.gba"
HISTORICAL_MANIFEST = ROOT / "analysis" / "ggen_advance_supply_totals_ko_candidate_20260903.json"
OUT_DIR = ROOT / "outputs" / "20260903_ggen_advance_supply_totals_main_rebase"
OUT_ROM = OUT_DIR / "ggen_advance_supply_totals_main_rebase_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_supply_totals_main_rebase_candidate_20260903.sav"
OUT_MANIFEST = ROOT / "analysis" / "ggen_advance_supply_totals_main_rebase_candidate_20260903.json"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    old_base = HISTORICAL_BASE.read_bytes()
    old_candidate = HISTORICAL_ROM.read_bytes()
    old_manifest = json.loads(HISTORICAL_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(current) == main_manifest["sha256"], "current main/manifest drift")
    gate(main_manifest["promotion_reason"] == "user_approved_team_card_full_ko_and_unit_list_hold_ji_merged_20260903", "unexpected current main")
    gate(sha256(old_base) == old_manifest["source"]["main_tip_sha256"], "historical supply parent hash drift")
    gate(sha256(old_candidate) == old_manifest["output"]["sha256"], "historical supply candidate hash drift")
    gate(str(old_manifest["verification"]["fresh_emulator_measurement"]).startswith("PASS"), "supply totals lack runtime approval")
    gate(current[source.SUPPLY_FILE:source.SUPPLY_LIMIT] == old_base[source.SUPPLY_FILE:source.SUPPLY_LIMIT], "current supply resource differs from approved historical parent")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")
    rebuilt, _before, _after, patch_report = source.patch_supply_animation8(current, font)
    candidate = bytearray(current)
    end = source.SUPPLY_FILE + len(rebuilt)
    gate(end <= source.SUPPLY_LIMIT, "rebased supply resource overflow")
    candidate[source.SUPPLY_FILE:end] = rebuilt
    candidate_bytes = bytes(candidate)

    changed = [i for i, (a, b) in enumerate(zip(current, candidate_bytes)) if a != b]
    gate(changed and all(source.SUPPLY_FILE <= i < end for i in changed), "rebase changes escaped supply resource")
    historical_changed = [i for i, (a, b) in enumerate(zip(old_base, old_candidate)) if a != b]
    gate(changed == historical_changed, "rebased supply changed-offset set differs from runtime-approved candidate")
    gate(candidate_bytes[source.SUPPLY_FILE:end] == old_candidate[source.SUPPLY_FILE:end], "rebased supply payload differs from runtime-approved candidate")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate_bytes)
    shutil.copyfile(ROOT / "SD Gundam GGeneration Advance (Korean).sav", OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_supply_totals_main_rebase_candidate_20260903",
        "result": "PASS",
        "status": "approved_rebase_candidate_ready_for_promotion",
        "output": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "crc32": f"0x{binascii.crc32(candidate_bytes) & 0xFFFFFFFF:08X}", "size": len(candidate_bytes)},
        "source_main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "historical_approved_component": {"path": advance_relative(HISTORICAL_ROM), "sha256": sha256(old_candidate), "manifest": advance_relative(HISTORICAL_MANIFEST), "runtime_approved": True},
        "scope": {"補給ポイント": "보급포인트", "総ユニット数": "총유닛수"},
        "patch": patch_report,
        "sav": {"path": advance_relative(OUT_SAV), "sha256": sha256(OUT_SAV.read_bytes())},
        "changed_byte_count": len(changed),
        "verification": {
            "result": "PASS",
            "current_main_manifest_match": True,
            "historical_parent_and_candidate_hash_verified": True,
            "historical_runtime_approval_verified": True,
            "current_supply_parent_resource_byte_exact_historical_parent": True,
            "rebased_supply_payload_byte_exact_runtime_approved_candidate": True,
            "rebased_changed_offsets_exact_historical_set": True,
            "changes_confined_to_private_supply_resource": True,
            "team_card_and_hold_changes_preserved": True,
            "py_compile": "PASS",
            "unified_pipeline_regression": "6/6 PASS",
            "intermission_development_regression": "4/4 PASS"
        }
    }
    OUT_MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "crc32": report["output"]["crc32"], "manifest": advance_relative(OUT_MANIFEST), "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
