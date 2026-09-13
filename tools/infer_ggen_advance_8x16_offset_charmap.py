#!/usr/bin/env python3
"""Infer remaining 8x16 glyph identities by exact offset bitmap match.

Production and non-scenario UI use the 8x16 atlas.  Dictionary bijection only
covers 265 shared slots, so most pending 8x16 text sits outside that table.
This helper keeps the 12x12 rule: accept a slot only when one unused Japanese
character produces an identical 8x16 ink mask at some placement.  Approximate
scores are discarded.  The immutable unified source is never rewritten.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_SEED = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
DEFAULT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_8x16_offset_charmap_20260828.json"

FONT_BASE = 0x00094028
FONT_COUNT = 2068
FONT_STRIDE = 32
CANVAS = 32
WIDTH = 8
HEIGHT = 16
EIGHT_SCOPES = {"production", "non_scenario_ui"}
RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}

DEFAULT_FONTS = (
    (Path(r"C:\Windows\Fonts\msgothic.ttc"), 0, "MS Gothic"),
    (Path(r"C:\Windows\Fonts\msmincho.ttc"), 0, "MS Mincho"),
    (Path(r"C:\Windows\Fonts\YuGothM.ttc"), 0, "Yu Gothic Medium"),
    (Path(r"C:\Windows\Fonts\meiryo.ttc"), 0, "Meiryo"),
)


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(slot), 16): str(char) for slot, char in payload.get("verified_charmap", {}).items()}


def game_glyph(data: bytes, slot: int) -> np.ndarray:
    raw = data[FONT_BASE + slot * FONT_STRIDE : FONT_BASE + (slot + 1) * FONT_STRIDE]
    pixels = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    for y in range(HEIGHT):
        for half in range(2):
            value = raw[y * 2 + half]
            for x in range(4):
                pixels[y, half * 4 + x] = 1 if (value & 0x03) else 0
                value >>= 2
    return pixels


def candidate_chars() -> list[str]:
    ranges = (
        (0x0020, 0x007E),
        (0x3000, 0x303F),
        (0x3040, 0x309F),
        (0x30A0, 0x30FF),
        (0x3400, 0x4DBF),
        (0x4E00, 0x9FFF),
        (0xF900, 0xFAFF),
        (0xFF00, 0xFFEF),
    )
    extras = "♪★☆♥♡※→←↑↓±×÷∞℃○●◎□■△▲▽▼◇◆"
    chars = [chr(code) for start, end in ranges for code in range(start, end + 1)]
    chars.extend(extras)
    return chars


def render_windows(font: ImageFont.FreeTypeFont, char: str) -> list[bytes]:
    image = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(image).text((8, 8), char, font=font, fill=255)
    array = (np.asarray(image) > 64).astype(np.uint8)
    if not array.any():
        return []
    rows, cols = np.where(array)
    x0, x1 = int(cols.min()), int(cols.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    windows: list[bytes] = []
    seen: set[bytes] = set()
    # 8x16 cells cannot host a cropped fragment of a larger kanji.  Only
    # placements that contain the entire ink bbox are eligible.
    if (x1 - x0) > WIDTH or (y1 - y0) > HEIGHT:
        return []
    top_lo = max(0, y1 - HEIGHT)
    top_hi = min(y0, CANVAS - HEIGHT)
    left_lo = max(0, x1 - WIDTH)
    left_hi = min(x0, CANVAS - WIDTH)
    if top_lo > top_hi or left_lo > left_hi:
        return []
    for top in range(top_lo, top_hi + 1):
        for left in range(left_lo, left_hi + 1):
            key = array[top : top + HEIGHT, left : left + WIDTH].tobytes()
            if key not in seen:
                seen.add(key)
                windows.append(key)
    return windows


def pending_unresolved_slots(merged: dict) -> list[int]:
    slots: set[int] = set()
    for row in merged.get("records", []):
        if row.get("translation_status") != "pending":
            continue
        if row.get("translation_policy") != "translate":
            continue
        if row.get("source_scope") not in EIGHT_SCOPES:
            continue
        for raw in row.get("source_unresolved_slots", []):
            try:
                slot = int(str(raw), 16)
            except (TypeError, ValueError):
                continue
            if slot in RESERVED:
                continue
            if 0 <= slot < FONT_COUNT:
                slots.add(slot)
    return sorted(slots)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sizes", type=int, nargs="+", default=[8, 9, 10, 11, 12, 13, 14, 15, 16])
    args = parser.parse_args(argv)

    rom = args.rom.read_bytes()
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    fixed = load_map(args.seed)

    target_slots = [slot for slot in pending_unresolved_slots(merged) if slot not in fixed]
    target_keys: dict[bytes, list[int]] = defaultdict(list)
    blank = 0
    for slot in target_slots:
        glyph = game_glyph(rom, slot)
        if not int(glyph.sum()):
            blank += 1
            continue
        target_keys[glyph.tobytes()].append(slot)

    used_chars = set(fixed.values())
    fonts = [(path, index, name) for path, index, name in DEFAULT_FONTS if path.exists()]
    slot_chars: dict[int, set[str]] = defaultdict(set)
    slot_evidence: dict[int, list[dict[str, str]]] = defaultdict(list)
    chars = [char for char in candidate_chars() if char not in used_chars]

    for font_path, font_index, font_name in fonts:
        for size in args.sizes:
            font = ImageFont.truetype(str(font_path), size=size, index=font_index)
            for char in chars:
                for key in render_windows(font, char):
                    slots = target_keys.get(key)
                    if not slots:
                        continue
                    for slot in slots:
                        if char not in slot_chars[slot]:
                            slot_chars[slot].add(char)
                            if len(slot_evidence[slot]) < 4:
                                slot_evidence[slot].append(
                                    {
                                        "char": char,
                                        "font": font_name,
                                        "size": str(size),
                                    }
                                )

    inferred: dict[int, str] = {}
    rejected = Counter()
    for slot in target_slots:
        options = sorted(slot_chars.get(slot, ()))
        if not options:
            rejected["no_exact_match"] += 1
            continue
        unused = [char for char in options if char not in used_chars]
        if len(unused) != 1:
            rejected["ambiguous_or_used"] += 1
            continue
        inferred[slot] = unused[0]
        used_chars.add(unused[0])

    combined = dict(fixed)
    combined.update(inferred)
    payload = {
        "schema_version": 1,
        "font_mode": "8x16",
        "method": "exact 8x16 ink-mask match against Japanese system fonts at every placement that can contain the rendered glyph",
        "base_seed": str(args.seed),
        "fonts": [name for _, _, name in fonts],
        "sizes": args.sizes,
        "target_slot_count": len(target_slots),
        "blank_target_slots": blank,
        "unique_target_bitmaps": len(target_keys),
        "fixed_slot_count": len(fixed),
        "inferred_slot_count": len(inferred),
        "rejected": dict(rejected),
        "verified_charmap": {f"0x{slot:04X}": combined[slot] for slot in sorted(combined)},
        "inferred": [
            {
                "slot": f"0x{slot:04X}",
                "char": char,
                "evidence": slot_evidence.get(slot, []),
            }
            for slot, char in sorted(inferred.items())
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "fonts": [name for _, _, name in fonts],
        "target_slots": len(target_slots),
        "blank_targets": blank,
        "unique_bitmaps": len(target_keys),
        "fixed_slots": len(fixed),
        "inferred_slots": len(inferred),
        "rejected": dict(rejected),
        "combined_slots": len(combined),
        "inferred_preview": [
            {"slot": f"0x{slot:04X}", "char": char}
            for slot, char in sorted(inferred.items())[:40]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
