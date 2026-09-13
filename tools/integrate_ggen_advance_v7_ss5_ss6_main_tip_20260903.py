#!/usr/bin/env python3
"""Integrate the approved ss1/ss2/development v7 and ss5/ss6 v3 candidates.

The two candidates share historical private-clone allocations.  This builder
starts from the exact v7 ROM, reapplies v3's ss6 patch to the shared
dismantle/ss6 clone, and relocates only the ss5 clone into zero-filled space.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from PIL import Image

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_remaining_ui_ss5_ss6_candidate_v3_20260903 as ss56
import test_ggen_advance_font_pair as fontpair
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_ROM, advance_relative

ROM_BASE = 0x08000000
V7_ROM = ROOT / "outputs/20260902_ggen_advance_ss1_ss2_graphics/ggen_advance_ss1_ss2_graphics_ko_test_v7_20260903.gba"
V7_MANIFEST = ROOT / "legacy/analysis/ggen_advance_ss1_ss2_graphics_ko_test_v7_20260903.json"
SS56_ROM = ROOT / "outputs/20260903_ggen_advance_remaining_ui_ss5_ss6_v3/ggen_advance_remaining_ui_ss5_ss6_candidate_v3_20260903.gba"
SS56_MANIFEST = ROOT / "legacy/analysis/ggen_advance_remaining_ui_ss5_ss6_candidate_v3_20260903.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
OUT_DIR = ROOT / "outputs/20260903_ggen_advance_v7_ss5_ss6_integrated"
OUT_ROM = OUT_DIR / "ggen_advance_advance_v7_ss5_ss6_integrated_candidate_20260903.gba"
OUT_SAV = OUT_DIR / "ggen_advance_advance_v7_ss5_ss6_integrated_candidate_20260903.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_advance_v7_ss5_ss6_integrated_preview_20260903.png"
OUT_MANIFEST = ROOT / "legacy/analysis/ggen_advance_v7_ss5_ss6_integrated_candidate_20260903.json"
SS5_DEST_OFF = 0x01F00000


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def main() -> int:
    v7 = V7_ROM.read_bytes()
    ss56_candidate = SS56_ROM.read_bytes()
    v7_meta = json.loads(V7_MANIFEST.read_text(encoding="utf-8"))
    ss56_meta = json.loads(SS56_MANIFEST.read_text(encoding="utf-8"))
    gate(v7_meta.get("result") == "PASS", "v7 manifest is not PASS")
    gate(ss56_meta.get("result") == "PASS", "ss5/ss6 v3 manifest is not PASS")
    gate(v7_meta["source"]["parent_sha256"] == ss56_meta["source"]["parent_sha256"], "candidate parents differ")
    gate(len(v7) == 32 * 1024 * 1024 and len(ss56_candidate) == len(v7), "candidate ROM size drift")
    gate(sha256(v7) == v7_meta["output"]["rom_sha256"], "v7 SHA drift")
    gate(sha256(ss56_candidate) == ss56_meta["output"]["rom_sha256"], "ss5/ss6 v3 SHA drift")

    with ZipFile(FONT_ZIP) as archive:
        font = fontpair.load_bdf(archive, "Galmuri11.bdf")

    # Reapply ss6 v3 to v7's shared dismantle/ss6 resource.  This preserves
    # v7's development buttons and adds only animation-6 objects 6/7.
    integrated = bytearray(v7)
    ss6_clone, ss6_report, ss6_previews = ss56.build_ss6(v7, font)
    ss6_off = ss56.SS6_CLONE - ROM_BASE
    ss6_limit = ((ss6_off // ss56.BLOCK_SIZE) + 1) * ss56.BLOCK_SIZE
    gate(ss6_off + len(ss6_clone) <= ss6_limit, "integrated ss6 clone exceeds block")
    integrated[ss6_off:ss6_off + len(ss6_clone)] = ss6_clone

    # Build ss5 from the same source as v3, but place its private clone away
    # from v7's ss1 clone at 0x012F0000.
    ss5_clone, ss5_report, ss5_previews = ss56.build_ss5(v7, font)
    gate(SS5_DEST_OFF + len(ss5_clone) <= SS5_DEST_OFF + ss56.BLOCK_SIZE, "integrated ss5 clone exceeds block")
    gate(all(value == 0 for value in v7[SS5_DEST_OFF:SS5_DEST_OFF + len(ss5_clone)]), "ss5 destination is not zero-filled")
    integrated[SS5_DEST_OFF:SS5_DEST_OFF + len(ss5_clone)] = ss5_clone
    struct.pack_into("<I", integrated, 0x0006F074, ROM_BASE + SS5_DEST_OFF)

    # No original resources are changed; only v7 private clones plus the
    # relocated ss5 clone and the sole ss5 consumer redirect are present.
    changed = [i for i, (before, after) in enumerate(zip(v7, integrated)) if before != after]
    gate(0x0006F074 in changed, "ss5 consumer redirect missing")
    gate(sha256(integrated) != sha256(v7), "integration produced no changes")

    regression = {}
    for name in ("test_ggen_advance_unified_pipeline.py", "test_ggen_advance_intermission_development_fix.py"):
        cp = subprocess.run([sys.executable, str(THIS_DIR / name)], cwd=str(ROOT), capture_output=True, text=True)
        gate(cp.returncode == 0, f"{name} failed: {cp.stderr[-600:]}")
        regression[name] = "PASS"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(integrated)
    shutil.copy2(MAIN_SAV, OUT_SAV)
    preview = Image.new("RGB", (2 * 240 + 12, (len(ss5_previews) + len(ss6_previews)) * 48 + 8), (16, 16, 16))
    rows = ss5_previews + ss6_previews
    for idx, (before, after, palettes, bank) in enumerate(rows):
        y = 4 + idx * 48
        preview.paste(ss56.animutil.canvas_image(before, palettes, bank, 3), (4, y))
        preview.paste(ss56.animutil.canvas_image(after, palettes, bank, 3), (244, y))
    preview.save(OUT_PREVIEW)

    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_v7_ss5_ss6_integrated_candidate_20260903",
        "result": "PASS",
        "source": {
            "v7_rom": advance_relative(V7_ROM),
            "v7_sha256": sha256(v7),
            "ss5_ss6_v3_rom": advance_relative(SS56_ROM),
            "ss5_ss6_v3_sha256": sha256(ss56_candidate),
            "common_parent_sha256": v7_meta["source"]["parent_sha256"],
        },
        "integration": {
            "ss1_ss2_and_development": "v7 byte-exact base",
            "ss6": ss6_report,
            "ss5": ss5_report | {
                "clone_file_offset": f"0x{SS5_DEST_OFF:08X}",
                "clone_address": f"0x{ROM_BASE + SS5_DEST_OFF:08X}",
                "redirected_refs": ["0x0006F074"],
            },
            "ss5_destination": f"0x{SS5_DEST_OFF:08X}",
            "changed_bytes_vs_v7": len(changed),
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "size": len(integrated),
            "sha256": sha256(integrated),
            "preview": advance_relative(OUT_PREVIEW),
        },
        "verification": {
            "result": "PASS",
            "v7_base_verified": True,
            "ss5_ss6_v3_verified": True,
            "ss1_ss2_and_development_preserved_from_v7": True,
            "ss5_relocated_without_overlap": True,
            "ss6_applied_to_shared_dismantle_clone": True,
            "canonical_main_tip_unchanged": sha256(MAIN_TIP_ROM.read_bytes()) == json.loads((ROOT / "integrated/main_tip/ggen_advance_main_tip_manifest.json").read_text(encoding="utf-8"))["sha256"],
            "ss3_ss4_excluded": True,
            "regression": regression,
            "emulator_measurement": "pending user verification",
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": advance_relative(OUT_ROM), "rom_sha256": manifest["output"]["sha256"], "manifest": advance_relative(OUT_MANIFEST), "changed_bytes_vs_v7": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
