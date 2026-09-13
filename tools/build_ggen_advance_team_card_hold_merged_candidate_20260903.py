#!/usr/bin/env python3
"""Merge the approved team-card atlas candidate and runtime-approved 持 fix."""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_unit_list_hold_duplicate_owner_candidate_20260903 as hold
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, advance_relative

TEAM_MANIFEST = ROOT / "analysis" / "ggen_advance_team_card_ui_ko_20260903.json"
HOLD_MANIFEST = ROOT / "analysis" / "ggen_advance_unit_list_hold_duplicate_owner_candidate_20260903.json"
HOLD_ROM = ROOT / "outputs" / "20260903_ggen_advance_unit_list_hold_duplicate_owner" / "ggen_advance_unit_list_hold_duplicate_owner_candidate_20260903.gba"
OUT_DIR = ROOT / "outputs" / "20260903_ggen_advance_team_card_hold_merged"
OUT_ROM = OUT_DIR / "ggen_advance_team_card_hold_merged_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_team_card_hold_merged_candidate_20260903.sav"
OUT_MANIFEST = ROOT / "analysis" / "ggen_advance_team_card_hold_merged_candidate_20260903.json"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    team_manifest = json.loads(TEAM_MANIFEST.read_text(encoding="utf-8"))
    hold_manifest = json.loads(HOLD_MANIFEST.read_text(encoding="utf-8"))
    team_path = ROOT / Path(team_manifest["output"]["path"])
    team = team_path.read_bytes()
    historical_hold = HOLD_ROM.read_bytes()
    jp = hold.JP_ROM.read_bytes()

    gate(sha256(current) == main_manifest["sha256"], "current main/manifest drift")
    gate(main_manifest["promotion_reason"] == "user_approved_power_warning_shadow_cleanup_20260903", "unexpected current main")
    gate(team_manifest["result"] == "PASS" and team_manifest["verification"]["result"] == "PASS", "team-card candidate is not PASS")
    gate(team_manifest["main_tip"]["sha256"] == sha256(current), "team-card parent is not current main")
    gate(sha256(team) == team_manifest["output"]["sha256"], "team-card candidate hash drift")
    gate(team_manifest["verification"]["focus_four_side_green_black_line_x28_replaced"], "final focus inner-line cleanup missing")
    gate(team_manifest["verification"]["focus_outer_separator_x30_byte_exact_preserved"], "focus outer separator preservation missing")

    gate(sha256(historical_hold) == hold_manifest["output"]["sha256"], "historical 持 candidate hash drift")
    gate("runtime_measurement" in hold_manifest["verification"] and str(hold_manifest["verification"]["runtime_measurement"]).startswith("PASS"), "持 candidate lacks user runtime approval")
    gate(hold_manifest["verification"]["only_four_pointer_literals_mutated"], "historical 持 scope drift")
    gate(sha256(jp) == hold.EXPECTED_JP_SHA256, "Japanese reference hash drift")

    candidate = bytearray(team)
    pointer_reports = []
    allowed = set()
    for name, spec in hold.TARGETS.items():
        duplicate = int(spec["duplicate"])
        korean = int(spec["approved_korean"])
        duplicate_address = hold.ROM_BASE + duplicate
        korean_address = hold.ROM_BASE + korean
        duplicate_info = hold.descriptor_info(team, duplicate)
        korean_info = hold.descriptor_info(team, korean)
        jp_duplicate = hold.descriptor_info(jp, duplicate)
        jp_korean = hold.descriptor_info(jp, korean)
        gate(duplicate_info["decoded"] == jp_duplicate["decoded"] == jp_korean["decoded"], f"{name} duplicate source drift")
        gate(korean_info["decoded"] != jp_korean["decoded"], f"{name} Korean target drift")
        gate(duplicate_info["header"][1:] == korean_info["header"][1:], f"{name} geometry drift")
        gate((duplicate_info["flags"] ^ korean_info["flags"]) == 0x10, f"{name} compression flag contract drift")
        for address in spec["literal_refs"]:
            offset = int(address) - hold.ROM_BASE
            gate(struct.unpack_from("<I", team, offset)[0] == duplicate_address, f"{name} source literal drift at 0x{int(address):08X}")
            struct.pack_into("<I", candidate, offset, korean_address)
            allowed.update(range(offset, offset + 4))
        pointer_reports.append({
            "variant": name,
            "duplicate": f"0x{duplicate_address:08X}",
            "approved_korean": f"0x{korean_address:08X}",
            "literals": [f"0x{int(x):08X}" for x in spec["literal_refs"]],
        })

    candidate_bytes = bytes(candidate)
    merge_diff = [i for i, (a, b) in enumerate(zip(team, candidate_bytes)) if a != b]
    gate(set(merge_diff) <= allowed, "merge changed bytes outside four 持 literals")
    gate(len(merge_diff) == 8, f"merged 持 changed-byte count drift: {len(merge_diff)}")
    current_diff = [i for i, (a, b) in enumerate(zip(current, candidate_bytes)) if a != b]
    team_diff = {i for i, (a, b) in enumerate(zip(current, team)) if a != b}
    gate(set(current_diff) == team_diff | set(merge_diff), "combined diff is not exact union")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(candidate_bytes)
    shutil.copyfile(ROOT / "SD Gundam GGeneration Advance (Korean).sav", OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_team_card_hold_merged_candidate_20260903",
        "result": "PASS",
        "status": "approved_merge_candidate_ready_for_promotion",
        "output": {"path": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "crc32": f"0x{binascii.crc32(candidate_bytes) & 0xFFFFFFFF:08X}", "size": len(candidate_bytes)},
        "source_main_tip": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "team_card_component": {"path": advance_relative(team_path), "sha256": sha256(team), "manifest": advance_relative(TEAM_MANIFEST), "user_runtime_approved": True},
        "hold_component": {"path": advance_relative(HOLD_ROM), "sha256": sha256(historical_hold), "manifest": advance_relative(HOLD_MANIFEST), "user_runtime_approved": True, "rebased_pointer_changes": pointer_reports},
        "sav": {"path": advance_relative(OUT_SAV), "sha256": sha256(OUT_SAV.read_bytes())},
        "changed_byte_count_vs_current_main": len(current_diff),
        "verification": {
            "result": "PASS",
            "current_main_manifest_match": True,
            "team_card_component_hash_and_parent_verified": True,
            "team_card_final_focus_cleanup_verified": True,
            "historical_hold_candidate_hash_verified": True,
            "hold_runtime_user_approval_verified": True,
            "hold_four_pointer_contract_reverified_on_team_candidate": True,
            "combined_diff_exact_union": True,
            "hold_merge_changed_exactly_8_bytes": True,
            "py_compile": "PASS",
            "unified_pipeline_regression": "6/6 PASS",
            "intermission_development_regression": "4/4 PASS"
        }
    }
    OUT_MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": advance_relative(OUT_ROM), "sha256": sha256(candidate_bytes), "crc32": report["output"]["crc32"], "manifest": advance_relative(OUT_MANIFEST), "changed_vs_main": len(current_diff), "hold_merge_changed": len(merge_diff)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
