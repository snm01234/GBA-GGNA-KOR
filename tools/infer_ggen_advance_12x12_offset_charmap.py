#!/usr/bin/env python3
"""Infer remaining 12x12 glyph identities by exact offset bitmap match.

The earlier template/unicode passes only pasted a cropped MS Gothic glyph at
(0, 0).  Many Advance 12x12 slots failed that test because the game atlas is
baseline-aligned rather than top-left packed.  This helper keeps the same
exact-match rule: a slot is accepted only when one unused Japanese character
produces an identical 12x12 bitmap at some placement.  Approximate F1 scores
are discarded.  The immutable unified source is never rewritten.

Renderer-verified compact kana ``0x001D-0x0058`` is pinned and is never
replaced by a font template.
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
DEFAULT_SEED = ROOT / "analysis" / "ggen_advance_12x12_unicode_charmap_20260827.json"
DEFAULT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_12x12_offset_charmap_20260828.json"

FONT_BASE = 0x0008AC40
FONT_COUNT = 1992
FONT_STRIDE = 18
CANVAS = 32
WINDOW = 12
PINNED_KANA_END = 0x0058

CORRECTED_LOW_KANA = {
    0x001D: "ぁ", 0x001E: "あ", 0x001F: "い", 0x0020: "う",
    0x0021: "ぇ", 0x0022: "え", 0x0023: "ぉ", 0x0024: "お",
    0x0025: "か", 0x0026: "が", 0x0027: "き", 0x0028: "く",
    0x0029: "け", 0x002A: "げ", 0x002B: "こ", 0x002C: "さ",
    0x002D: "し", 0x002E: "じ", 0x002F: "す", 0x0030: "ず",
    0x0031: "せ", 0x0032: "そ", 0x0033: "ぞ", 0x0034: "た",
    0x0035: "だ", 0x0036: "ち", 0x0037: "っ", 0x0038: "つ",
    0x0039: "て", 0x003A: "で", 0x003B: "と", 0x003C: "ど",
    0x003D: "な", 0x003E: "に", 0x003F: "ぬ", 0x0040: "ね",
    0x0041: "の", 0x0042: "は", 0x0043: "ば", 0x0044: "ひ",
    0x0045: "び", 0x0046: "ふ", 0x0047: "ま", 0x0048: "み",
    0x0049: "む", 0x004A: "め", 0x004B: "も", 0x004C: "ゃ",
    0x004D: "や", 0x004E: "ゅ", 0x004F: "ょ", 0x0050: "よ",
    0x0051: "ら", 0x0052: "り", 0x0053: "る", 0x0054: "れ",
    0x0055: "ろ", 0x0056: "わ", 0x0057: "を", 0x0058: "ん",
}

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
    bits: list[int] = []
    for value in raw:
        bits.extend((value >> bit) & 1 for bit in range(8))
    return np.asarray(bits[:144], dtype=np.uint8).reshape(12, 12)


def candidate_chars() -> list[str]:
    ranges = (
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
    for top in range(max(0, y1 - WINDOW), min(y0, CANVAS - WINDOW) + 1):
        for left in range(max(0, x1 - WINDOW), min(x0, CANVAS - WINDOW) + 1):
            key = array[top : top + WINDOW, left : left + WINDOW].tobytes()
            if key not in seen:
                seen.add(key)
                windows.append(key)
    # Also keep every overlapping 12x12 crop when the glyph is larger than the
    # cell.  Exact equality still required, so this only helps cropped forms.
    if (x1 - x0) > WINDOW or (y1 - y0) > WINDOW:
        for top in range(max(0, y0 - 1), min(y1, CANVAS - WINDOW) + 1):
            for left in range(max(0, x0 - 1), min(x1, CANVAS - WINDOW) + 1):
                key = array[top : top + WINDOW, left : left + WINDOW].tobytes()
                if key not in seen and key != b"\x00" * (WINDOW * WINDOW):
                    seen.add(key)
                    windows.append(key)
    return windows


def pending_unresolved_slots(merged: dict, scopes: set[str] | None = None) -> list[int]:
    slots: set[int] = set()
    for row in merged.get("records", []):
        if row.get("translation_status") != "pending":
            continue
        if row.get("translation_policy") != "translate":
            continue
        if scopes and str(row.get("source_scope", "")) not in scopes:
            continue
        for raw in row.get("source_unresolved_slots", []):
            try:
                slot = int(str(raw), 16)
            except (TypeError, ValueError):
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
    parser.add_argument("--sizes", type=int, nargs="+", default=[11, 12, 13])
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help="limit target slots to these source_scope values (repeatable)",
    )
    args = parser.parse_args(argv)

    rom = args.rom.read_bytes()
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    fixed = load_map(args.seed)
    fixed.update(CORRECTED_LOW_KANA)

    scopes = set(args.scope) if args.scope else None
    target_slots = [
        slot
        for slot in pending_unresolved_slots(merged, scopes)
        if slot not in fixed and slot > PINNED_KANA_END
    ]
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
        "font_mode": "12x12",
        "method": "exact 12x12 bitmap match against Japanese system fonts at every placement that can contain the rendered glyph",
        "base_seed": str(args.seed),
        "pinned_low_kana": {f"0x{slot:04X}": char for slot, char in CORRECTED_LOW_KANA.items()},
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
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
