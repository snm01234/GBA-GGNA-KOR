"""Restore I-Field hold tiles to the pre-ss123 ability clone.

ss3 asked only for Bio Field unique Hangul. I-Field hold (아이필드) was
rewritten as a side effect via shared suffix tiles; restore those hold tiles
from the pre-promotion main TIP backup.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_turn_ability_overlays_20260905 as ability  # noqa: E402
from ggen_advance_project_paths import MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256
from patch_ggen_advance_ss123_zeon_nt001_biofield_20260912 import (
    BIO_IDS,
    BIO_UNIQUE,
    I_HOLD_IDS,
    OUT,
    WORK,
    save_plate,
    u32,
)

BACKUP = (
    ROOT
    / "integrated"
    / "main_tip"
    / "backups"
    / "20260912T061755Z_user_requested_ss123_zeon_marine_nt001_biofield_20260912"
    / "SD Gundam GGeneration Advance (Korean).gba"
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    backup = BACKUP.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == str(manifest.get("sha256") or ""), "main TIP sha mismatch")
    gate(sha256(backup) == "9c6009ba4f2fee03f37e5d084ce5d808274b439796a93538d7086522f0414377", "backup sha mismatch")

    live_ptr = u32(parent, ability.ABILITY_POINTER)
    gate(live_ptr == ability.ROM_BASE + ability.ABILITY_CLONE, "ability clone pointer drift")
    gate(u32(backup, ability.ABILITY_POINTER) == live_ptr, "backup ability pointer drift")
    hdr, blob = ability.resource_blob(parent, live_ptr)
    backup_hdr, backup_blob = ability.resource_blob(backup, live_ptr)
    gate(hdr == backup_hdr, "ability header drift")
    gfx = bytearray(blob[hdr["gfx_rel"] : hdr["pal_rel"]])
    backup_gfx = backup_blob[hdr["gfx_rel"] : hdr["pal_rel"]]
    pal = bytes(blob[hdr["pal_rel"] : hdr["pal_rel"] + 32])
    save_plate(OUT / "ifield_hold_before_rollback.png", bytes(gfx), I_HOLD_IDS, pal)
    save_plate(OUT / "ifield_hold_backup.png", backup_gfx, I_HOLD_IDS, pal)
    save_plate(OUT / "biofield_before_rollback.png", bytes(gfx), BIO_IDS, pal)

    restored = []
    kept_bio = []
    for tile in I_HOLD_IDS:
        src = backup_gfx[tile * 32 : (tile + 1) * 32]
        if gfx[tile * 32 : (tile + 1) * 32] != src:
            gfx[tile * 32 : (tile + 1) * 32] = src
            restored.append(tile)
    for tile in sorted(BIO_UNIQUE):
        if gfx[tile * 32 : (tile + 1) * 32] != backup_gfx[tile * 32 : (tile + 1) * 32]:
            kept_bio.append(tile)
    gate(restored, "I-hold already matched backup")
    gate(set(BIO_UNIQUE) <= set(kept_bio), "bio unique tiles lost during rollback")

    clone = bytearray(blob)
    clone[hdr["gfx_rel"] : hdr["pal_rel"]] = gfx
    gate(clone[: hdr["gfx_rel"]] == blob[: hdr["gfx_rel"]], "animation records changed")
    gate(clone[hdr["pal_rel"] :] == blob[hdr["pal_rel"] :], "palettes changed")
    candidate = bytearray(parent)
    start = ability.ABILITY_CLONE
    candidate[start : start + len(clone)] = clone
    allowed = set(range(start + hdr["gfx_rel"], start + hdr["pal_rel"]))
    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")
    for tile in I_HOLD_IDS:
        gate(gfx[tile * 32 : (tile + 1) * 32] == backup_gfx[tile * 32 : (tile + 1) * 32], f"I-hold tile {tile} not restored")

    jp_hdr, jp_blob = ability.resource_blob(japan, ability.ABILITY_SOURCE)
    jp_gfx = jp_blob[jp_hdr["gfx_rel"] : jp_hdr["pal_rel"]]
    vs_jp = [tile for tile in sorted(BIO_UNIQUE) if gfx[tile * 32 : (tile + 1) * 32] != jp_gfx[tile * 32 : (tile + 1) * 32]]
    gate(set(BIO_UNIQUE) <= set(vs_jp), "bio unique reverted to Japanese")

    save_plate(OUT / "ifield_hold_after.png", bytes(gfx), I_HOLD_IDS, pal)
    save_plate(OUT / "biofield_after.png", bytes(gfx), BIO_IDS, pal)
    WORK.write_bytes(bytes(candidate))
    sav_src = MAIN_TIP_ROM.with_suffix(".sav")
    if sav_src.exists():
        WORK.with_suffix(".sav").write_bytes(sav_src.read_bytes())
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_ifield_hold_rollback_20260912",
        "batch_id": "ifield-hold-rollback-20260912",
        "parent_sha256": sha256(parent),
        "backup_sha256": sha256(backup),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "restored_ifield_hold_tiles": restored,
        "kept_bio_unique_tiles": kept_bio,
        "changed_bytes": len(changed),
        "verification": {
            "result": "PASS",
            "ifield_hold_matches_backup": True,
            "bio_unique_still_korean": True,
            "unrelated_bytes_preserved": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "restored_ifield_hold_tiles", "kept_bio_unique_tiles", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
