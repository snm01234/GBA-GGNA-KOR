#!/usr/bin/env python3
"""Build a conflict-checked 8x16 Japanese charmap supplement.

The two GBA dictionaries contain the same literal glyph sequence but use
different slot numbers.  Their pinned bijection lets exact 12x12 Japanese
glyph assignments be carried into the production 8x16 table without changing
the immutable unified source.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED = ROOT / "font_tables" / "ggen_advance_japanese_charmap_seed_20260826.json"
DEFAULT_BIJECTION = ROOT / "analysis" / "dictionary_comparison_20260827.json"
DEFAULT_12X12 = ROOT / "analysis" / "ggen_advance_12x12_unicode_charmap_20260827.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260827.json"

# The seed alignment around the low kana is one position short.  This is the
# same atlas correction used by the scenario batch decoder; keep it local to
# the derived supplement and never rewrite the pinned seed.
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


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(slot), 16): str(char) for slot, char in payload.get("verified_charmap", {}).items()}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--bijection", type=Path, default=DEFAULT_BIJECTION)
    parser.add_argument("--charmap-12x12", type=Path, default=DEFAULT_12X12)
    parser.add_argument("--correct-low-kana", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    seed = load_map(args.seed)
    map12 = load_map(args.charmap_12x12)
    if args.correct_low_kana:
        map12.update(CORRECTED_LOW_KANA)
    bijection = json.loads(args.bijection.read_text(encoding="utf-8"))["slot_bijection_8x16_to_12x12"]

    combined = dict(seed)
    derived: dict[int, str] = {}
    conflicts: list[dict[str, str]] = []
    missing_12: list[str] = []
    for raw8, raw12 in sorted(bijection.items(), key=lambda item: int(item[0], 16)):
        slot8 = int(raw8, 16)
        slot12 = int(raw12, 16)
        char = map12.get(slot12)
        if char is None:
            missing_12.append(raw12)
            continue
        if slot8 in seed and seed[slot8] != char:
            conflicts.append({"slot_8x16": raw8, "seed": seed[slot8], "derived": char})
            continue
        derived[slot8] = char
        combined[slot8] = char

    payload = {
        "schema_version": 1,
        "font_mode": "8x16",
        "method": "exact dictionary 8x16-to-12x12 slot bijection plus exact 12x12 charmap",
        "seed": str(args.seed),
        "bijection": str(args.bijection),
        "charmap_12x12": str(args.charmap_12x12),
        "seed_slot_count": len(seed),
        "bijection_slot_count": len(bijection),
        "derived_slot_count": len(derived),
        "combined_slot_count": len(combined),
        "missing_12x12_slots": sorted(set(missing_12), key=lambda value: int(value, 16)),
        "conflicts": conflicts,
        "verified_charmap": {f"0x{slot:04X}": combined[slot] for slot in sorted(combined)},
        "derived": [
            {"slot": f"0x{slot:04X}", "char": char, "via_12x12_slot": bijection[f"0x{slot:04X}"]}
            for slot, char in sorted(derived.items())
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "seed_slots": len(seed),
        "bijection_slots": len(bijection),
        "derived_slots": len(derived),
        "combined_slots": len(combined),
        "missing_12x12_slots": len(set(missing_12)),
        "conflicts": len(conflicts),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
