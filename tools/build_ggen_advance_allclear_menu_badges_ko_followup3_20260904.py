#!/usr/bin/env python3
"""Extend the clean-plate all-clear badge candidate with 노말게임 / 스페셜게임.

This wrapper keeps every verified followup2 target (including 캐릭터 / 유닛),
then adds duplicate animation families 3/12 = ノーマルゲーム and
4/13 = スペシャルゲーム.  The followup2 savestate proves both families live
20/20 and shows native palette banks 10/11, so source graphics are replaced
while palettes and animation records remain untouched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_ggen_advance_allclear_menu_badges_ko_followup2_20260904 as previous
from ggen_advance_project_paths import ADVANCE_ROOT, advance_relative

ANALYSIS = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_normal_special_game_badges_20260904.json"
OUT_DIR = ADVANCE_ROOT / "outputs" / "20260904_ggen_advance_allclear_menu_badges"
OUT_ROM = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup3_candidate_20260904.gba"
OUT_SAV = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup3_candidate_20260904.sav"
OUT_PREVIEW = OUT_DIR / "ggen_advance_allclear_menu_badges_ko_followup3_preview_20260904.png"
OUT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_allclear_menu_badges_ko_followup3_candidate_20260904.json"

NEW_VARIANTS = [
    ("ノーマルゲーム", "노말게임", 3, [3, 12], "active", 14),
    ("スペシャルゲーム", "스페셜게임", 4, [4, 13], "active", 14),
]


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def main() -> int:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    gate(analysis.get("result") == "PASS", "normal/special game analysis is not PASS")
    by_source = {row["source"]: row for row in analysis["targets"]}
    gate(by_source["ノーマルゲーム"]["animation_family"] == [3, 12], "normal-game animation family drift")
    gate(by_source["スペシャルゲーム"]["animation_family"] == [4, 13], "special-game animation family drift")
    gate(by_source["ノーマルゲーム"]["live_match"]["result"] == "PASS", "normal-game live ownership not PASS")
    gate(by_source["スペシャルゲーム"]["live_match"]["result"] == "PASS", "special-game live ownership not PASS")
    gate(by_source["ノーマルゲーム"]["native_text_width"] < by_source["スペシャルゲーム"]["native_text_width"], "native width semantic ordering drift")
    gate(by_source["ノーマルゲーム"]["live_palette_bank"] != by_source["スペシャルゲーム"]["live_palette_bank"], "normal/focus live palette evidence drift")

    # previous.main() adds previous.EXTRA_VARIANTS to the verified base builder.
    # Extend that list in this fresh process, preserving every followup2 target.
    previous.EXTRA_VARIANTS = list(previous.EXTRA_VARIANTS) + NEW_VARIANTS
    previous.OUT_ROM = OUT_ROM
    previous.OUT_SAV = OUT_SAV
    previous.OUT_PREVIEW = OUT_PREVIEW
    previous.OUT_MANIFEST = OUT_MANIFEST

    result = previous.main()
    gate(result == 0, "followup2 cumulative builder failed")

    # Replace inherited preview with a focused normal/special-game normal/focus
    # sheet.  Source rasters are shared by duplicate animation pairs; palettes
    # remain native and are shown with package palette 0/1 for representative
    # normal/focus appearance, matching prior verified previews.
    out = OUT_ROM.read_bytes()
    base = previous.base
    off = base.RESOURCE - base.ROM_BASE
    import struct
    _kind, pal_count, grel, prel, anim_count = struct.unpack_from("<5I", out, off)
    gate((pal_count, anim_count) == (6, 26), "followup3 preview resource drift")
    graphics = out[off + grel:off + prel]
    palettes = out[off + prel:off + prel + pal_count * 32]
    _gr, records = base.sprite.animation_records(out, base.RESOURCE)
    anim = {i: base.old.animation_info(records, i) for i in range(anim_count)}
    canvases = {i: base.old.canvas_for(graphics, anim[i]) for i in (3, 4, 12, 13)}
    gate(canvases[3] == canvases[12], "normal-game duplicate raster drift")
    gate(canvases[4] == canvases[13], "special-game duplicate raster drift")

    scale = 4
    rows = [
        ("노말게임 normal", canvases[3], 0),
        ("노말게임 focus", canvases[12], 1),
        ("스페셜게임 normal", canvases[4], 0),
        ("스페셜게임 focus", canvases[13], 1),
    ]
    row_h = 16 * scale
    sheet = base.Image.new("RGB", (80 * scale + 190, len(rows) * (row_h + 8) + 30), (18, 18, 18))
    draw = base.ImageDraw.Draw(sheet)
    draw.text((8, 8), "all-clear normal / special game badge follow-up", fill=(255, 255, 255))
    y = 28
    for label, canvas, pal in rows:
        sheet.paste(base.image_for(canvas, palettes[pal * 32:(pal + 1) * 32], scale), (0, y))
        draw.text((80 * scale + 10, y + 20), label, fill=(235, 235, 235))
        y += row_h + 8
    sheet.save(OUT_PREVIEW)

    manifest = json.loads(OUT_MANIFEST.read_text(encoding="utf-8"))
    manifest["kind"] = "ggen_advance_allclear_menu_badges_ko_followup3_candidate_20260904"
    manifest["normal_special_game_analysis"] = advance_relative(ANALYSIS)
    manifest["normal_special_game_followup"] = {
        "ノーマルゲーム": {
            "translation": "노말게임",
            "animations": [3, 12],
            "normal_focus_source_shared": True,
            "captured_live_palette_bank": by_source["ノーマルゲーム"]["live_palette_bank"],
        },
        "スペシャルゲーム": {
            "translation": "스페셜게임",
            "animations": [4, 13],
            "normal_focus_source_shared": True,
            "captured_live_palette_bank": by_source["スペシャルゲーム"]["live_palette_bank"],
        },
    }
    manifest["verification"]["normal_special_game_normal_focus_included"] = True
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
        "normal_game_animations": [3, 12],
        "special_game_animations": [4, 13],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
