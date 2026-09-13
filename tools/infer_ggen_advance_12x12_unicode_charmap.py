#!/usr/bin/env python3
"""Infer additional exact 12x12 glyph identities from the full Japanese range.

The normal template pass uses Japanese characters already present in project
JSON.  This companion pass widens only the *candidate* set to standard
Japanese Unicode ranges.  It still accepts a slot only when the rendered
12x12 bitmap has one exact MS Gothic match and the character is not already
assigned.  The unified source remains immutable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import ImageFont

from infer_ggen_advance_12x12_template_charmap import (
    DEFAULT_FONT,
    DEFAULT_MERGED,
    DEFAULT_ROM,
    DEFAULT_SEED,
    FONT_BASE,
    FONT_COUNT,
    FONT_SIZE,
    FONT_STRIDE,
    font_template,
    game_glyph,
    japanese_characters,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUPPLEMENT = ROOT / "analysis" / "ggen_advance_12x12_template_charmap_20260827.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_12x12_unicode_charmap_20260827.json"


def range_chars() -> list[str]:
    ranges = (
        (0x3000, 0x303F),  # CJK punctuation
        (0x3040, 0x309F),  # hiragana
        (0x30A0, 0x30FF),  # katakana
        (0x3400, 0x4DBF),  # CJK extension A
        (0x4E00, 0x9FFF),  # common CJK
        (0xF900, 0xFAFF),  # CJK compatibility ideographs
        (0xFF00, 0xFFEF),  # full-width forms
    )
    return [chr(code) for start, end in ranges for code in range(start, end + 1)]


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(slot), 16): str(char) for slot, char in payload.get("verified_charmap", {}).items()}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--supplement", type=Path, default=DEFAULT_SUPPLEMENT)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    rom = args.rom.read_bytes()
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    fixed = load_map(args.seed)
    if args.supplement.exists():
        fixed.update(load_map(args.supplement))

    # Keep the project corpus as a useful source of symbols not covered by the
    # ranges, then add the complete Japanese/CJK candidate space.
    corpus_paths = [args.merged, ROOT / "analysis" / "scenario_event_translation_source_20260827.json"]
    candidates = set(japanese_characters(corpus_paths))
    candidates.update(range_chars())
    candidates = sorted(candidates)

    font = ImageFont.truetype(str(args.font), FONT_SIZE, index=0)
    template_chars: list[str] = []
    template_rows = []
    for char in candidates:
        template = font_template(font, char)
        if template is not None:
            template_chars.append(char)
            template_rows.append(template)

    target_slots = sorted(
        {
            int(str(slot), 16)
            for row in merged.get("records", [])
            if row.get("translation_status") == "pending"
            for slot in row.get("source_unresolved_slots", [])
            if isinstance(slot, str)
        }
    )
    used_chars = set(fixed.values())
    inferred: dict[int, str] = {}
    rejected: dict[str, int] = {}
    for slot in target_slots:
        if slot in fixed or slot < 0 or slot >= FONT_COUNT:
            continue
        glyph = game_glyph(rom, slot)
        matches = [
            char
            for char, template in zip(template_chars, template_rows)
            if (template == glyph).all()
        ]
        matches = [char for char in matches if char not in used_chars]
        if len(matches) != 1:
            key = "no_exact_match" if not matches else "ambiguous_or_used"
            rejected[key] = rejected.get(key, 0) + 1
            continue
        inferred[slot] = matches[0]
        used_chars.add(matches[0])

    combined = dict(fixed)
    combined.update(inferred)
    payload = {
        "schema_version": 1,
        "font_mode": "12x12",
        "method": "exact 12x12 bitmap match against MS Gothic index 0 with full Japanese/CJK candidate ranges",
        "base_seed": str(args.seed),
        "template_supplement": str(args.supplement),
        "candidate_character_count": len(candidates),
        "template_character_count": len(template_chars),
        "target_slot_count": len(target_slots),
        "fixed_slot_count": len(fixed),
        "inferred_slot_count": len(inferred),
        "rejected": rejected,
        "verified_charmap": {f"0x{slot:04X}": combined[slot] for slot in sorted(combined)},
        "inferred": [
            {"slot": f"0x{slot:04X}", "char": char, "score": 144}
            for slot, char in sorted(inferred.items())
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "candidate_characters": len(candidates),
        "template_characters": len(template_chars),
        "target_slots": len(target_slots),
        "fixed_slots": len(fixed),
        "inferred_slots": len(inferred),
        "rejected": rejected,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
