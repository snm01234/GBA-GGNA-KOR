#!/usr/bin/env python3
"""Dump remaining pending 8x16 unknown slots after the 20260907 bitmap pass."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "analysis"))

import build_ggen_advance_ko_poc as fontops
import _tmp_classify_pending_readable_20260907 as decode
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, RESERVED
from ggen_advance_project_paths import ORIGINAL_ROM
from identify_ggen_advance_8x16_bitmap_idcmd_20260907 import glyph8

OUT_JSON = ROOT / "analysis" / "ggen_advance_8x16_bitmap_remaining_20260907.json"
OUT_DIR = ROOT / "outputs" / "20260907_ggen_advance_8x16_bitmap_remaining"
FONT = Path(r"C:\Windows\Fonts\msgothic.ttc")

READABLE_CATS = {
    "id_command_name",
    "scroll_list_label",
    "scripted_multiline_text",
    "series_title",
    "stage_location_name",
    "map_system_selector_static_label",
    "map_system_selector_help",
    "unit_defense_ability",
    "unit_ai_type",
    "unit_configuration_action_label",
    "ui_menu_or_status_text",
    "stage_battle_condition_static_label",
    "selector_empty_state_message",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rom = ORIGINAL_ROM.read_bytes()
    merged = json.loads(decode.TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dict8 = decode.load_dictionary(rom, decode.DICT_8X16_BASE, decode.DICT_8X16_END)
    dict12 = decode.load_dictionary(rom, decode.DICT_12X12_BASE, decode.DICT_12X12_END)
    map8 = decode.load_identified_slot_to_char(decode.CHARMAP_8X16_PATH)
    map12 = decode.load_identified_slot_to_char(decode.CHARMAP_12X12_PATH)
    map12.update(CORRECTED_LOW_KANA)

    info: dict[int, dict] = {}
    for row in merged["records"]:
        if row.get("translation_status") != "pending":
            continue
        if row.get("translation_policy") != "translate":
            continue
        decoded, missing, font = decode.decode_row(row, dict8, dict12, map8, map12)
        if font != "8x16":
            continue
        text_missing = [slot for slot in missing if slot not in RESERVED]
        if not text_missing:
            continue
        cat = str(row.get("semantic_category") or "")
        for slot in text_missing:
            item = info.setdefault(
                slot,
                {
                    "slot": f"0x{slot:04X}",
                    "records": 0,
                    "idcmd": 0,
                    "idcmd_leftover1": 0,
                    "leftover1": 0,
                    "readable_leftover1": 0,
                    "cats": Counter(),
                    "leftover1_decoded": Counter(),
                    "idcmd_frames": [],
                    "readable_frames": [],
                },
            )
            item["records"] += 1
            item["cats"][cat] += 1
            if cat == "id_command_name":
                item["idcmd"] += 1
                if len(item["idcmd_frames"]) < 8:
                    item["idcmd_frames"].append(decoded.replace("\n", " / ")[:90])
                if len(text_missing) == 1:
                    item["idcmd_leftover1"] += 1
            if len(text_missing) == 1:
                item["leftover1"] += 1
                item["leftover1_decoded"][decoded.replace("\n", " / ")] += 1
                if cat in READABLE_CATS:
                    item["readable_leftover1"] += 1
            if cat in READABLE_CATS and len(item["readable_frames"]) < 8:
                item["readable_frames"].append({"cat": cat, "nmiss": len(text_missing), "text": decoded.replace("\n", " / ")[:90]})

    focus = sorted(
        slot
        for slot, item in info.items()
        if item["idcmd"] > 0 or item["readable_leftover1"] > 0
    )
    rows = []
    for slot in focus:
        item = info[slot]
        rows.append(
            {
                "slot": item["slot"],
                "records": item["records"],
                "idcmd": item["idcmd"],
                "idcmd_leftover1": item["idcmd_leftover1"],
                "leftover1": item["leftover1"],
                "readable_leftover1": item["readable_leftover1"],
                "cats": dict(item["cats"].most_common()),
                "leftover1_decoded": [{"n": n, "text": t} for t, n in item["leftover1_decoded"].most_common(8)],
                "idcmd_frames": item["idcmd_frames"],
                "readable_frames": item["readable_frames"],
            }
        )

    OUT_JSON.write_text(json.dumps({"focus_slots": len(rows), "results": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    gothic = ImageFont.truetype(str(FONT), size=48, index=0) if FONT.exists() else None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scale = 16
    gw, gh = 8 * scale, 16 * scale
    rows_per = 6
    pages = []
    for start in range(0, len(focus), rows_per):
        chunk = focus[start : start + rows_per]
        width = 20 + gw + 24 + 420
        height = 16 + len(chunk) * (gh + 36)
        image = Image.new("RGB", (width, height), "#0d1014")
        draw = ImageDraw.Draw(image)
        for i, slot in enumerate(chunk):
            y = 10 + i * (gh + 36)
            glyph = fontops.unpack_8x16(glyph8(rom, slot)).resize((gw, gh), Image.Resampling.NEAREST).convert("RGB")
            image.paste(glyph, (12, y))
            item = info[slot]
            label = f"{item['slot']} idcmd={item['idcmd']} l1={item['leftover1']}"
            draw.text((12, y + gh + 2), label, fill="#d0d4d8")
            sample = ""
            if item["idcmd_frames"]:
                sample = item["idcmd_frames"][0]
            elif item["leftover1_decoded"]:
                sample = item["leftover1_decoded"].most_common(1)[0][0]
            draw.text((12 + gw + 16, y + 8), sample[:42], fill="#f0d060")
        path = OUT_DIR / f"panel_{start:03d}.png"
        image.save(path)
        pages.append(str(path))

    print(json.dumps({"out": str(OUT_JSON), "focus": len(rows), "idcmd_slots": sum(1 for r in rows if r["idcmd"]), "idcmd_l1": sum(1 for r in rows if r["idcmd_leftover1"]), "pages": pages}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
