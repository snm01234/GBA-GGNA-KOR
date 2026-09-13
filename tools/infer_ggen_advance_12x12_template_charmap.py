#!/usr/bin/env python3
"""Infer exact 12x12 Japanese glyph identities from a system font template.

The Advance 12x12 font is a 1bpp, 12-by-12 bitmap atlas.  This helper uses
only exact bitmap matches against the installed MS Gothic Japanese face and a
corpus of Japanese characters already present in the project data.  Ambiguous
or approximate matches are discarded.  The immutable unified source is never
rewritten; the result is an optional decoder supplement for later batches.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


DEFAULT_ROM = Path("SD Gundam GGeneration Advance (Japan).gba")
DEFAULT_SEED = Path("legacy/analysis/scenario_event_12x12_charmap_seed_20260827.json")
DEFAULT_MERGED = Path("analysis/ggen_advance_translation_merged_20260827.json")
DEFAULT_OUTPUT = Path("legacy/analysis/ggen_advance_12x12_template_charmap_20260827.json")
DEFAULT_FONT = Path("C:/Windows/Fonts/msgothic.ttc")

FONT_BASE = 0x0008AC40
FONT_COUNT = 1992
FONT_STRIDE = 18
FONT_SIZE = 12


def walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for child in value.values():
            result.extend(walk_strings(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(walk_strings(child))
        return result
    return []


def japanese_characters(paths: list[Path]) -> list[str]:
    chars: set[str] = set()
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for value in walk_strings(payload):
            chars.update(
                char
                for char in value
                if 0x3000 <= ord(char) <= 0x9FFF
                or 0x3040 <= ord(char) <= 0x30FF
            )
    return sorted(chars)


def game_glyph(data: bytes, slot: int) -> np.ndarray:
    raw = data[FONT_BASE + slot * FONT_STRIDE : FONT_BASE + (slot + 1) * FONT_STRIDE]
    bits: list[int] = []
    for value in raw:
        bits.extend((value >> bit) & 1 for bit in range(8))
    return np.asarray(bits, dtype=np.uint8)


def font_template(font: ImageFont.FreeTypeFont, char: str) -> np.ndarray | None:
    image = Image.new("L", (32, 32), 0)
    ImageDraw.Draw(image).text((0, 0), char, font=font, fill=255)
    bbox = image.getbbox()
    if bbox is None:
        return None
    cropped = image.crop(bbox)
    if cropped.width > 12 or cropped.height > 12:
        return None
    padded = Image.new("L", (12, 12), 0)
    padded.paste(cropped, (0, 0))
    return (np.asarray(padded) > 64).astype(np.uint8).reshape(-1)


def parse_slot(value: str) -> int:
    return int(value, 16)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    rom = args.rom.read_bytes()
    seed_payload = json.loads(args.seed.read_text(encoding="utf-8"))
    seed = {int(slot, 16): char for slot, char in seed_payload["verified_charmap"].items()}
    merged = json.loads(args.merged.read_text(encoding="utf-8"))

    corpus_paths = [args.merged, Path("legacy/analysis/scenario_event_translation_source_20260827.json")]
    corpus_paths.extend(Path("analysis").glob("*.json"))
    data_root = Path("D:/monoeye/data")
    if data_root.exists():
        corpus_paths.extend(data_root.rglob("*.json"))
    candidates = japanese_characters(corpus_paths)

    font = ImageFont.truetype(str(args.font), FONT_SIZE, index=0)
    template_chars: list[str] = []
    template_rows: list[np.ndarray] = []
    for char in candidates:
        template = font_template(font, char)
        if template is not None:
            template_chars.append(char)
            template_rows.append(template)
    templates = np.asarray(template_rows, dtype=np.uint8)

    target_slots = sorted(
        {
            int(slot, 16)
            for row in merged["records"]
            if row.get("translation_status") == "pending"
            for slot in row.get("source_unresolved_slots", [])
            if isinstance(slot, str)
        }
    )
    used_chars = set(seed.values())
    inferred: dict[int, str] = {}
    rejected = Counter()
    for slot in target_slots:
        if slot in seed or slot < 0 or slot >= FONT_COUNT:
            continue
        glyph = game_glyph(rom, slot)
        scores = (templates == glyph).sum(axis=1)
        if not len(scores):
            rejected["no_templates"] += 1
            continue
        best_indices = np.flatnonzero(scores == scores.max())
        if int(scores.max()) != 144:
            rejected["not_exact"] += 1
            continue
        if len(best_indices) != 1:
            rejected["ambiguous_candidate"] += 1
            continue
        char = template_chars[int(best_indices[0])]
        if char in used_chars:
            rejected["character_already_assigned"] += 1
            continue
        inferred[slot] = char
        used_chars.add(char)

    combined = dict(seed)
    combined.update(inferred)
    payload = {
        "schema_version": 1,
        "font_mode": "12x12",
        "method": "exact 12x12 bitmap match against MS Gothic index 0; approximate and ambiguous matches discarded",
        "base_seed": str(args.seed),
        "corpus_character_count": len(candidates),
        "template_character_count": len(template_chars),
        "target_slot_count": len(target_slots),
        "inferred_slot_count": len(inferred),
        "rejected": dict(rejected),
        "verified_charmap": {
            f"0x{slot:04X}": combined[slot] for slot in sorted(combined)
        },
        "inferred": [
            {
                "slot": f"0x{slot:04X}",
                "char": inferred[slot],
                "score": 144,
            }
            for slot in sorted(inferred)
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "output": str(args.out),
                "target_slots": len(target_slots),
                "inferred_slots": len(inferred),
                "corpus_characters": len(candidates),
                "rejected": dict(rejected),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
