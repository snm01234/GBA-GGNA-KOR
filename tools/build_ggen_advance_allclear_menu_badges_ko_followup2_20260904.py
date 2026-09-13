#!/usr/bin/env python3
"""Extend the clean-plate all-clear badge candidate with 캐릭터 / 유닛.

This wrapper deliberately reuses the verified clean-plate builder and only
extends its target animation set.  キャラクター uses duplicate animations
22/24 and ユニット uses 23/25; the follow-up state analyzer proves 20/20 live
source-tile ownership for animation 24 and 23 respectively.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_allclear_menu_badges_ko_followup_20260904 as base
from ggen_advance_project_paths import ADVANCE_ROOT, advance_relative

ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_character_unit_badges_20260904.json"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_allclear_menu_badges"
OUT_ROM = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup2_candidate_20260904.gba"
OUT_SAV = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup2_candidate_20260904.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup2_preview_20260904.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_menu_badges_ko_followup2_candidate_20260904.json"

EXTRA_VARIANTS = [
    ("キャラクター", "캐릭터", 22, [22, 24], "active", 14),
    ("ユニット", "유닛", 23, [23, 25], "active", 14),
]


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def main() -> int:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    gate(analysis.get("result") == "PASS", "character/unit analysis is not PASS")
    by_source = {row["source"]: row for row in analysis["targets"]}
    gate(by_source["キャラクター"]["animation_family"] == [22, 24], "character animation family drift")
    gate(by_source["ユニット"]["animation_family"] == [23, 25], "unit animation family drift")
    gate(by_source["キャラクター"]["live_match"]["result"] == "PASS", "character live ownership not PASS")
    gate(by_source["ユニット"]["live_match"]["result"] == "PASS", "unit live ownership not PASS")

    # Patch the verified builder's globals without altering the previous
    # candidate or its reproducibility artifacts.
    base.VARIANTS = list(base.VARIANTS) + EXTRA_VARIANTS
    base.TARGET_ANIMS = {a for _jp, _ko, _canon, family, _style, _face in base.VARIANTS for a in family}
    base.OUT_ROM = OUT_ROM
    base.OUT_SAV = OUT_SAV
    base.OUT_PREVIEW = OUT_PREVIEW
    base.OUT_MANIFEST = OUT_MANIFEST

    result = base.main()
    gate(result == 0, "base clean-plate builder failed")

    # Replace the inherited preview with a focused character/unit normal/focus
    # sheet.  The duplicate animation pairs share source graphics; palettes are
    # intentionally left native and are shown with package palette 0/1 as the
    # same representative normal/focus pair used by the established builder.
    out = OUT_ROM.read_bytes()
    off = base.RESOURCE - base.ROM_BASE
    _kind, pal_count, grel, prel, anim_count = __import__("struct").unpack_from("<5I", out, off)
    gate((pal_count, anim_count) == (6, 26), "followup2 preview resource drift")
    graphics = out[off + grel:off + prel]
    palettes = out[off + prel:off + prel + pal_count * 32]
    _gr, records = base.sprite.animation_records(out, base.RESOURCE)
    anim = {i: base.old.animation_info(records, i) for i in range(anim_count)}
    canvases = {i: base.old.canvas_for(graphics, anim[i]) for i in (22, 23, 24, 25)}
    gate(canvases[22] == canvases[24], "character normal/focus source raster drift")
    gate(canvases[23] == canvases[25], "unit normal/focus source raster drift")
    scale = 4
    rows = [("캐릭터 normal", canvases[22], 0), ("캐릭터 focus", canvases[24], 1), ("유닛 normal", canvases[23], 0), ("유닛 focus", canvases[25], 1)]
    row_h = 16 * scale
    sheet = base.Image.new("RGB", (80 * scale + 180, len(rows) * (row_h + 8) + 30), (18, 18, 18))
    draw = base.ImageDraw.Draw(sheet)
    draw.text((8, 8), "all-clear character / unit badge follow-up", fill=(255, 255, 255))
    y = 28
    for label, canvas, pal in rows:
        sheet.paste(base.image_for(canvas, palettes[pal * 32:(pal + 1) * 32], scale), (0, y))
        draw.text((80 * scale + 10, y + 20), label, fill=(235, 235, 235))
        y += row_h + 8
    sheet.save(OUT_PREVIEW)

    manifest = json.loads(OUT_MANIFEST.read_text(encoding="utf-8"))
    manifest["kind"] = "ggen_advance_allclear_menu_badges_ko_followup2_candidate_20260904"
    manifest["character_unit_analysis"] = advance_relative(ANALYSIS)
    manifest["character_unit_followup"] = {
        "キャラクター": {"translation": "캐릭터", "animations": [22, 24], "normal_focus_source_shared": True},
        "ユニット": {"translation": "유닛", "animations": [23, 25], "normal_focus_source_shared": True},
    }
    manifest["verification"]["character_unit_normal_focus_included"] = True
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "rom": advance_relative(OUT_ROM),
        "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
        "preview": advance_relative(OUT_PREVIEW),
        "manifest": advance_relative(OUT_MANIFEST),
        "sha256": manifest["output"]["sha256"],
        "crc32": manifest["output"]["crc32"],
        "character_animations": [22, 24],
        "unit_animations": [23, 25],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
