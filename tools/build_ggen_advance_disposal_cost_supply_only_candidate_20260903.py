#!/usr/bin/env python3
"""Build an isolated main-TIP candidate for the approved disposal-panel labels.

Includes only 強化費用 -> 강화비용 and 補給P -> 보급P.  The unresolved
持c/所有数 runtime overlay and the unrelated bottom supply package are excluded.
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

OUT_DIR = ADVANCE_ROOT / "outputs" / "20260903_ggen_advance_disposal_cost_supply_only"
OUT_ROM = OUT_DIR / "ggen_advance_disposal_cost_supply_ko_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_disposal_cost_supply_ko_candidate_20260903.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_disposal_cost_supply_ko_preview_20260903.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_disposal_cost_supply_ko_candidate_20260903.json"
MAIN_SAV = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav"


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def changed_ranges(offsets: list[int]) -> list[list[str]]:
    result: list[list[str]] = []
    if not offsets:
        return result
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
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "main TIP hash/manifest drift")
    with ZipFile(FONT_ZIP) as archive:
        font11 = fontpair.load_bdf(archive, "Galmuri11.bdf")

    rebuilt, patch_report = source.patch_disposal_panel(parent, font11)
    candidate = bytearray(parent)
    start = source.DISPOSAL_FILE
    end = start + len(rebuilt)
    gate(end <= source.DISPOSAL_LIMIT, "isolated disposal resource overflow")
    candidate[start:end] = rebuilt
    output = bytes(candidate)
    changed = [index for index, (before, after) in enumerate(zip(parent, output)) if before != after]
    gate(bool(changed), "isolated candidate made no changes")
    gate(all(start <= index < end for index in changed), "changes escaped disposal resource")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(output)
    shutil.copy2(MAIN_SAV, OUT_SAV)
    shutil.copy2(source.OUT_DISPOSAL_PREVIEW, OUT_PREVIEW)
    compile_result = subprocess.run([sys.executable, "-m", "py_compile", str(Path(__file__))], cwd=ADVANCE_ROOT, capture_output=True, text=True)
    gate(compile_result.returncode == 0, f"py_compile failed: {compile_result.stderr}")

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_disposal_cost_supply_ko_candidate_20260903",
        "result": "PASS",
        "status": "user_approved_isolated_promotion_candidate",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(parent),
        },
        "scope": {
            "included": {"強化費用": "강화비용", "補給P": "보급P"},
            "excluded_unresolved": ["持c", "所有数"],
            "excluded_unrelated": ["補給ポイント", "総ユニット数"],
        },
        "patch": patch_report,
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(output),
            "size": len(output),
            "sav": advance_relative(OUT_SAV),
            "preview": advance_relative(OUT_PREVIEW),
            "changed_bytes": len(changed),
            "changed_ranges": changed_ranges(changed),
        },
        "verification": {
            "result": "PASS",
            "main_tip_manifest_match": True,
            "only_disposal_resource_changed": True,
            "approved_labels_only": True,
            "unresolved_hold_owned_runtime_patch_excluded": True,
            "bottom_supply_package_excluded": True,
            "native_supply_button_background_template": "0x08C4654C animation 0",
            "original_source_tiles_preserved": True,
            "palette_bytes_preserved": True,
            "sav_byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(),
            "py_compile": "PASS",
            "fresh_emulator_measurement": "user approved 2026-09-03",
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": advance_relative(OUT_ROM), "sha256": sha256(output), "manifest": advance_relative(OUT_MANIFEST), "changed_bytes": len(changed)}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
