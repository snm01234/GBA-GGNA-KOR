#!/usr/bin/env python3
"""Add Korean 컨티뉴 to the still-Japanese active continue badge pair.

Disabled animation 21 is already Korean.  allclear.ss1 proves animations 6/15
are the shared normal/focus raster.  This builder reconstructs the verified
active clean plate from Japan-ROM samples 0-8 (so already-Korean siblings on
current main cannot pollute the well), paints Galmuri11 컨티뉴, and writes
only source tiles owned by 6/15.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import sys
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_settings_suspend_ui as sprite
import build_ggen_advance_allclear_menu_badges_ko_followup_20260904 as base
from ggen_advance_project_paths import ADVANCE_ROOT, FONT_ZIP, MAIN_TIP_MANIFEST, MAIN_TIP_ROM, ORIGINAL_ROM, advance_relative

ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_continue_active_badges_20260905.json"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260905_ggen_advance_allclear_continue_active"
OUT_ROM = OUT_DIR / "ggen_advance_allclear_continue_active_ko_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_allclear_continue_active_ko_candidate_20260905.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_allclear_continue_active_ko_preview_20260905.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_continue_active_ko_candidate_20260905.json"
SOURCE_SAV_CANDIDATES = [
    ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.sav",
    ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).sav",
]
FONT_MEMBER = "Galmuri11.bdf"
TARGET_FAMILY = {6, 15}
LEAVE_UNCHANGED = {8, 17, 20, 21}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def load_graphics(rom: bytes) -> tuple[int, int, int, int, bytes, bytes]:
    off = base.RESOURCE - base.ROM_BASE
    kind, pal_count, grel, prel, anim_count = struct.unpack_from("<5I", rom, off)
    gate((kind, pal_count, grel, prel, anim_count) == (0, 6, 0x0DE4, 0x2BE4, 26), "resource layout drift")
    graphics = rom[off + grel:off + prel]
    palettes = rom[off + prel:off + prel + pal_count * 32]
    gate(len(graphics) == 240 * 32, "graphics tile count drift")
    return off, pal_count, grel, prel, graphics, palettes


def main() -> int:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    gate(analysis.get("result") == "PASS", "continue active analysis is not PASS")
    by_source = {row["source"]: row for row in analysis["targets"]}
    gate(by_source["コンティニュー"]["animation_family"] == [6, 15], "continue animation family drift")
    gate(by_source["コンティニュー"]["live_match"]["result"] == "PASS", "continue live ownership not PASS")

    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "parent main TIP/manifest mismatch")
    gate(analysis["current_main_tip"]["sha256"] == sha256(parent), "analysis parent drift")

    off, pal_count, grel, prel, original_graphics, palettes = load_graphics(parent)
    _j_off, _j_pals, _j_grel, _j_prel, japan_graphics, _japan_palettes = load_graphics(japan)
    _gr, records = sprite.animation_records(parent, base.RESOURCE)
    anim = {i: base.old.animation_info(records, i) for i in range(26)}
    gate(anim[6]["source_ids"] == anim[15]["source_ids"], "continue duplicate pair drift")

    before = {i: base.old.canvas_for(original_graphics, anim[i]) for i in range(26)}
    japan_canvases = {i: base.old.canvas_for(japan_graphics, anim[i]) for i in range(26)}
    gate(before[6] == japan_canvases[6] == before[15], "active continue is not Japan-identical")
    gate(before[21] != japan_canvases[21], "disabled continue Korean sibling missing")

    active_plate, active_plate_meta = base.build_active_clean_plate([japan_canvases[i] for i in base.ACTIVE_PLATE_ANIMS])
    with ZipFile(FONT_ZIP) as archive:
        font = base.fontpair.load_bdf(archive, FONT_MEMBER)

    clean = base.apply_plate(before[6], active_plate)
    x0, y0, x1, y1 = base.TEXT_WELL
    clean_residue = [(x, y, clean[y][x]) for y in range(y0, y1) for x in range(x0, x1) if clean[y][x] in base.GLYPH_ONLY_ACTIVE]
    gate(not clean_residue, f"clean plate retained glyph-only indices: {clean_residue[:8]}")
    painted, paint = base.render_korean(clean, "컨티뉴", font, 14)
    korean_pixels = {
        (x, y)
        for y in range(16)
        for x in range(80)
        if painted[y][x] != clean[y][x]
    }
    gate(korean_pixels, "Korean continue raster is empty")
    shade_residue = [(x, y) for y in range(y0, y1) for x in range(x0, x1) if painted[y][x] == 0xB]
    gate(not shade_residue, f"Japanese shade residue after Korean paint: {shade_residue[:8]}")

    source_users: dict[int, set[int]] = {tile: set() for tile in range(240)}
    for index, info in anim.items():
        for sid in info["source_ids"]:
            source_users[int(sid)].add(index)

    updates: dict[int, bytes] = {}
    owners: dict[int, list[str]] = defaultdict(list)
    skipped_shared: dict[int, list[int]] = {}
    for sid, ox, oy in anim[6]["positions"]:
        sid = int(sid)
        payload = base.old.encode_tile([painted[oy + y][ox:ox + 8] for y in range(8)])
        original = original_graphics[sid * 32:(sid + 1) * 32]
        if payload == original:
            continue
        non_target = source_users[sid] - TARGET_FAMILY
        if non_target:
            touches_korean = any(ox <= x < ox + 8 and oy <= y < oy + 8 for x, y in korean_pixels)
            gate(not touches_korean, f"shared source tile {sid} carries Korean pixels")
            skipped_shared[sid] = sorted(non_target)
            continue
        updates[sid] = payload
        owners[sid].append("コンティニュー")
    gate(updates, "no continue source tiles changed")

    patched = bytearray(original_graphics)
    for sid, payload in updates.items():
        patched[sid * 32:(sid + 1) * 32] = payload
    after = {i: base.old.canvas_for(patched, anim[i]) for i in range(26)}

    allowed_shared_coords: set[tuple[int, int]] = set()
    for sid, ox, oy in anim[6]["positions"]:
        if int(sid) in skipped_shared:
            allowed_shared_coords.update((x, y) for y in range(oy, oy + 8) for x in range(ox, ox + 8))
    for member in (6, 15):
        diffs = {(x, y) for y in range(16) for x in range(80) if after[member][y][x] != painted[y][x]}
        gate(diffs <= allowed_shared_coords, f"animation {member} differs from desired outside shared chrome")
        gate(not (diffs & korean_pixels), f"animation {member} lost Korean glyph pixels")
    gate(after[6] == after[15], "continue normal/focus raster drift after patch")

    changed_non_target = [i for i in range(26) if i not in TARGET_FAMILY and after[i] != before[i]]
    gate(not changed_non_target, f"non-target animations changed: {changed_non_target}")
    for index in sorted(LEAVE_UNCHANGED):
        gate(after[index] == before[index], f"protected animation {index} changed")

    candidate = bytearray(parent)
    candidate[off + grel:off + prel] = patched
    out = bytes(candidate)
    changed_offsets = [i for i, (a, b) in enumerate(zip(parent, out)) if a != b]
    start, end = off + grel, off + prel
    gate(changed_offsets and all(start <= x < end for x in changed_offsets), "change escaped resource graphics")
    gate(out[off:off + grel] == parent[off:off + grel], "resource header/animation records changed")
    gate(out[off + prel:off + prel + pal_count * 32] == parent[off + prel:off + prel + pal_count * 32], "palettes changed")

    scale = 4
    rows = [
        ("컨티뉴 normal", after[6], 0),
        ("컨티뉴 focus", after[15], 1),
        ("컨티뉴 disabled unchanged", after[21], 0),
        ("BGM unchanged", after[8], 0),
        ("로드 disabled unchanged", after[20], 0),
    ]
    row_h = 16 * scale
    sheet = Image.new("RGB", (80 * scale + 240, len(rows) * (row_h + 8) + 30), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), "all-clear continue active badge Korean follow-up", fill=(255, 255, 255))
    y = 28
    for label, canvas, pal in rows:
        sheet.paste(base.image_for(canvas, palettes[pal * 32:(pal + 1) * 32], scale), (0, y))
        draw.text((80 * scale + 10, y + 20), label, fill=(235, 235, 235))
        y += row_h + 8

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    sheet.save(OUT_PREVIEW)
    sav_source = next((path for path in SOURCE_SAV_CANDIDATES if path.is_file()), None)
    if sav_source is not None:
        shutil.copy2(sav_source, OUT_SAV)

    manifest_out = {
        "schema_version": 1,
        "kind": "ggen_advance_allclear_continue_active_ko_candidate_20260905",
        "result": "PASS",
        "base": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent), "crc32": f"0x{binascii.crc32(parent) & 0xFFFFFFFF:08X}"},
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "bytes": len(out),
            "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
            "sav_source": advance_relative(sav_source) if sav_source is not None else None,
        },
        "preview": advance_relative(OUT_PREVIEW),
        "analysis": advance_relative(ANALYSIS),
        "resource": {
            "address": f"0x{base.RESOURCE:08X}",
            "font": FONT_MEMBER,
            "header_animation_records_unchanged": True,
            "palettes_unchanged": True,
        },
        "continue_active_followup": {
            "コンティニュー": {
                "translation": "컨티뉴",
                "animations": [6, 15],
                "normal_focus_source_shared": True,
                "disabled_korean_sibling": 21,
                "captured_live_palette_bank": by_source["コンティニュー"]["live_palette_bank"],
                "paint": paint,
            }
        },
        "clean_plate": {"policy": "rebuild the Japan-ROM active clean plate, then paint only animations 6/15", "active": active_plate_meta},
        "source_tile_updates": {
            "count": len(updates),
            "ids": sorted(updates),
            "owners": {str(k): v for k, v in sorted(owners.items())},
            "skipped_shared_chrome": {str(k): v for k, v in sorted(skipped_shared.items())},
        },
        "diff": {
            "changed_byte_count": len(changed_offsets),
            "all_changes_within_resource_graphics": True,
            "first_changed": f"0x{min(changed_offsets):08X}",
            "last_changed_exclusive": f"0x{max(changed_offsets) + 1:08X}",
        },
        "verification": {
            "result": "PASS",
            "target_animations": [6, 15],
            "changed_non_target_animations": changed_non_target,
            "bgm_8_17_unchanged": True,
            "disabled_load_20_unchanged": True,
            "disabled_continue_21_unchanged": True,
            "clean_plate_first": True,
            "normal_focus_source_shared": True,
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
        "preview": advance_relative(OUT_PREVIEW),
        "manifest": advance_relative(OUT_MANIFEST),
        "sha256": manifest_out["output"]["sha256"],
        "crc32": manifest_out["output"]["crc32"],
        "source_tiles_changed": len(updates),
        "changed_bytes": len(changed_offsets),
        "continue_animations": [6, 15],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
