#!/usr/bin/env python3
"""Identify remaining 8x16 slots from original-ROM glyph bitmaps.

Exact 8x16 duplicates of verified glyphs are promote-ready.
MS Gothic / 12x12 template matches are ranked for visual review; they are
not auto-promoted by this script.
"""
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
from ggen_advance_project_paths import ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    load_dictionary,
)

OUT_JSON = ROOT / "analysis" / "ggen_advance_8x16_bitmap_id_20260907.json"
OUT_DIR = ROOT / "outputs" / "20260907_ggen_advance_8x16_bitmap_id"
FONT_PATHS = (
    Path(r"C:\Windows\Fonts\msgothic.ttc"),
    Path(r"C:\Windows\Fonts\YuGothM.ttc"),
    Path(r"C:\Windows\Fonts\meiryo.ttc"),
)
IDCMD_FOCUS = True
LEFTOVER1_FOCUS = True
USE_GOTHIC = False
MAX_FRAMES = 12


def glyph8(rom: bytes, slot: int) -> bytes:
    start = fontops.FONT_8X16_BASE + slot * fontops.FONT_8X16_STRIDE
    return rom[start : start + fontops.FONT_8X16_STRIDE]


def glyph12(rom: bytes, slot: int) -> bytes:
    start = fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE
    return rom[start : start + fontops.FONT_12X12_STRIDE]


def mask8(raw: bytes) -> frozenset[tuple[int, int]]:
    image = fontops.unpack_8x16(raw)
    return frozenset((x, y) for y in range(16) for x in range(8) if image.getpixel((x, y)))


def bbox(mask: frozenset[tuple[int, int]]) -> tuple[int, int, int, int] | None:
    if not mask:
        return None
    xs = [x for x, _y in mask]
    ys = [y for _x, y in mask]
    return min(xs), min(ys), max(xs), max(ys)


def normalize(mask: frozenset[tuple[int, int]], size: int = 16) -> frozenset[tuple[int, int]]:
    box = bbox(mask)
    if box is None:
        return frozenset()
    x0, y0, x1, y1 = box
    w = max(1, x1 - x0 + 1)
    h = max(1, y1 - y0 + 1)
    out: set[tuple[int, int]] = set()
    for x, y in mask:
        nx = int((x - x0) * (size - 1) / w)
        ny = int((y - y0) * (size - 1) / h)
        out.add((min(size - 1, nx), min(size - 1, ny)))
    return frozenset(out)


def iou(a: frozenset[tuple[int, int]], b: frozenset[tuple[int, int]]) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def unpack12_mask(raw: bytes) -> frozenset[tuple[int, int]]:
    bits: list[int] = []
    for value in raw:
        bits.extend((value >> bit) & 1 for bit in range(8))
    return frozenset((x, y) for y in range(12) for x in range(12) if bits[y * 12 + x])


def font_masks(char: str, font: ImageFont.FreeTypeFont) -> list[frozenset[tuple[int, int]]]:
    out: list[frozenset[tuple[int, int]]] = []
    for dx in range(-1, 2):
        for dy in range(-2, 3):
            image = Image.new("L", (8, 16), 0)
            ImageDraw.Draw(image).text((dx, dy), char, font=font, fill=255)
            out.append(frozenset((x, y) for y in range(16) for x in range(8) if image.getpixel((x, y)) >= 128))
    return out


def render_strip(rom: bytes, rows: list[dict], path: Path, map8: dict[int, str], map12: dict[int, str]) -> None:
    if not rows:
        return
    scale = 8
    cell_w, cell_h = 8 * scale + 10, 16 * scale + 36
    columns = 8
    image = Image.new("RGB", (columns * cell_w, ((len(rows) + columns - 1) // columns) * cell_h), "#111418")
    draw = ImageDraw.Draw(image)
    for index, row in enumerate(rows):
        slot = int(row["slot"], 16)
        glyph = fontops.unpack_8x16(glyph8(rom, slot)).resize((8 * scale, 16 * scale), Image.Resampling.NEAREST)
        col, r = index % columns, index // columns
        x0, y0 = col * cell_w + 4, r * cell_h + 2
        image.paste(glyph.convert("RGB"), (x0, y0))
        guess = row.get("char") or row.get("best") or ""
        label = f"{row['slot']} {guess}"
        draw.text((x0, y0 + 16 * scale + 2), label[:20], fill="#d0d4d8")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rom = ORIGINAL_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dict8 = load_dictionary(rom, DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(rom, DICT_12X12_BASE, DICT_12X12_END)
    map8 = decode.load_identified_slot_to_char(decode.CHARMAP_8X16_PATH)
    map12 = decode.load_identified_slot_to_char(decode.CHARMAP_12X12_PATH)
    map12.update(CORRECTED_LOW_KANA)

    verified_raw: dict[bytes, list[tuple[int, str]]] = defaultdict(list)
    for slot, char in map8.items():
        verified_raw[glyph8(rom, slot)].append((slot, char))

    templates12: dict[str, frozenset[tuple[int, int]]] = {}
    for slot, char in map12.items():
        templates12.setdefault(char, normalize(unpack12_mask(glyph12(rom, slot))))

    gothic = None
    gothic_masks: dict[str, list[frozenset[tuple[int, int]]]] = {}
    gothic_path = None
    for path in FONT_PATHS:
        if path.exists():
            gothic = ImageFont.truetype(str(path), size=12, index=0)
            gothic_path = str(path)
            break
    kanji_pool = sorted({char for char in map12.values() if len(char) == 1 and ord(char) >= 0x3000})
    if USE_GOTHIC and gothic is not None:
        for char in kanji_pool:
            gothic_masks[char] = font_masks(char, gothic)

    slot_info: dict[int, dict] = {}
    for row in merged["records"]:
        if row.get("translation_status") != "pending":
            continue
        if row.get("translation_policy") != "translate":
            continue
        decoded, missing, font = decode.decode_row(row, dict8, dict12, map8, map12)
        if font != "8x16":
            continue
        text_missing = [slot for slot in missing if slot not in RESERVED]
        category = str(row.get("semantic_category") or "")
        for slot in text_missing:
            info = slot_info.setdefault(
                slot,
                {
                    "slot": f"0x{slot:04X}",
                    "records": 0,
                    "idcmd": 0,
                    "idcmd_leftover1": 0,
                    "leftover1": 0,
                    "cats": Counter(),
                    "frames": [],
                    "leftover1_decoded": Counter(),
                },
            )
            info["records"] += 1
            info["cats"][category] += 1
            if category == "id_command_name":
                info["idcmd"] += 1
                if len(text_missing) == 1:
                    info["idcmd_leftover1"] += 1
            if len(text_missing) == 1:
                info["leftover1"] += 1
                info["leftover1_decoded"][decoded.replace("\n", " / ")] += 1
            if len(info["frames"]) < MAX_FRAMES:
                info["frames"].append({"id": row["record_id"], "cat": category, "decoded": decoded.replace("\n", " / ")[:80], "nmiss": len(text_missing)})

    for info in slot_info.values():
        info["leftover1_decoded"] = [
            {"n": n, "text": text} for text, n in info["leftover1_decoded"].most_common(8)
        ]

    focus_slots = sorted(
        slot
        for slot, info in slot_info.items()
        if info["idcmd_leftover1"] > 0
        or (IDCMD_FOCUS and info["idcmd"] > 0)
        or (LEFTOVER1_FOCUS and info["leftover1"] > 0)
    )
    if not focus_slots:
        focus_slots = sorted(slot_info, key=lambda slot: -slot_info[slot]["records"])[:80]

    results = []
    exact = []
    visual = []
    for slot in focus_slots:
        raw = glyph8(rom, slot)
        info = slot_info[slot]
        item = {
            **{k: info[k] for k in ("slot", "records", "idcmd", "idcmd_leftover1", "leftover1")},
            "cats": dict(info["cats"].most_common()),
            "leftover1_decoded": info.get("leftover1_decoded", []),
            "frames": info["frames"],
            "empty": not any(raw),
        }
        dupes = [(other, char) for other, char in verified_raw.get(raw, []) if other != slot]
        if dupes:
            char = dupes[0][1]
            item.update({"kind": "exact_8x16_duplicate", "char": char, "duplicates": [f"0x{other:04X}" for other, _c in dupes], "promote": True})
            exact.append(item)
            results.append(item)
            continue
        actual = mask8(raw)
        actual_n = normalize(actual)
        ranked12: list[tuple[float, str]] = []
        seen: set[str] = set()
        for char, templ in templates12.items():
            if char in seen:
                continue
            seen.add(char)
            ranked12.append((iou(actual_n, templ), char))
        ranked12.sort(reverse=True)
        item["top12"] = [{"char": char, "iou": round(score, 4)} for score, char in ranked12[:5]]
        if USE_GOTHIC and gothic_masks:
            ranked_g: list[tuple[float, str]] = []
            for char, masks in gothic_masks.items():
                best = max((iou(actual, mask) for mask in masks), default=0.0)
                ranked_g.append((best, char))
            ranked_g.sort(reverse=True)
            item["top_gothic"] = [{"char": char, "iou": round(score, 4)} for score, char in ranked_g[:5]]
        else:
            item["top_gothic"] = []
        best12 = ranked12[0] if ranked12 else (0.0, "")
        second12 = ranked12[1][0] if len(ranked12) > 1 else 0.0
        bestg = item["top_gothic"][0] if item["top_gothic"] else {"char": "", "iou": 0.0}
        secondg = item["top_gothic"][1]["iou"] if len(item["top_gothic"]) > 1 else 0.0
        agree = best12[1] and best12[1] == bestg["char"]
        unique12 = best12[0] >= 0.62 and (best12[0] - second12) >= 0.08
        uniqueg = bestg["iou"] >= 0.55 and (bestg["iou"] - secondg) >= 0.08
        item["kind"] = "visual_rank"
        item["best"] = bestg["char"] if uniqueg else (best12[1] if unique12 else "")
        item["promote"] = bool(agree and unique12 and uniqueg)
        item["gothic_font"] = gothic_path
        visual.append(item)
        results.append(item)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    leftover1_rows = [row for row in results if row.get("leftover1") or row.get("idcmd")]
    idcmd_l1 = [row for row in results if row.get("idcmd_leftover1")]
    render_strip(rom, leftover1_rows, OUT_DIR / "leftover1_and_idcmd_slots.png", map8, map12)
    render_strip(rom, idcmd_l1, OUT_DIR / "idcmd_leftover1_slots.png", map8, map12)
    render_strip(rom, exact, OUT_DIR / "exact_duplicates.png", map8, map12)
    render_strip(rom, visual, OUT_DIR / "visual_ranked_slots.png", map8, map12)
    payload = {
        "schema_version": 1,
        "merged": "integrated/translation/ggen_advance_translation_merged.json",
        "focus": "pending 8x16 leftover=1 plus id_command_name slots",
        "gothic_font": gothic_path,
        "focus_slots": len(focus_slots),
        "exact_duplicates": len(exact),
        "visual_ranked": len(visual),
        "promote_auto_exact": [row["slot"] + "=" + row["char"] for row in exact],
        "promote_auto_visual_agree": [row["slot"] + "=" + row["best"] for row in visual if row.get("promote")],
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(OUT_JSON),
        "focus_slots": len(focus_slots),
        "exact_duplicates": len(exact),
        "promote_auto_exact": payload["promote_auto_exact"],
        "promote_auto_visual_agree": payload["promote_auto_visual_agree"],
        "strip": str(OUT_DIR / "leftover1_and_idcmd_slots.png"),
        "idcmd_leftover1_strip": str(OUT_DIR / "idcmd_leftover1_slots.png"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
