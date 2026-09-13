#!/usr/bin/env python3
"""Recover 8x16 voiced kana from atlas-internal dakuten deltas.

Known voiced pairs in the same 8x16 atlas give an exact extra-pixel mask.
Unmapped slots are accepted only when (base | delta) equals the candidate
glyph bit-for-bit.  System-font guesses are not used.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_SEED = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_8x16_dakuten_charmap_20260828.json"

FONT_BASE = 0x00094028
FONT_COUNT = 2068
FONT_STRIDE = 32

VOICED_PAIRS = (
    ("か", "が"), ("き", "ぎ"), ("く", "ぐ"), ("け", "げ"), ("こ", "ご"),
    ("さ", "ざ"), ("し", "じ"), ("す", "ず"), ("せ", "ぜ"), ("そ", "ぞ"),
    ("た", "だ"), ("ち", "ぢ"), ("つ", "づ"), ("て", "で"), ("と", "ど"),
    ("は", "ば"), ("ひ", "び"), ("ふ", "ぶ"), ("へ", "べ"), ("ほ", "ぼ"),
    ("カ", "ガ"), ("キ", "ギ"), ("ク", "グ"), ("ケ", "ゲ"), ("コ", "ゴ"),
    ("サ", "ザ"), ("シ", "ジ"), ("ス", "ズ"), ("セ", "ゼ"), ("ソ", "ゾ"),
    ("タ", "ダ"), ("チ", "ヂ"), ("ツ", "ヅ"), ("テ", "デ"), ("ト", "ド"),
    ("ハ", "バ"), ("ヒ", "ビ"), ("フ", "ブ"), ("ヘ", "ベ"), ("ホ", "ボ"),
)
HANDAKUTEN_PAIRS = (
    ("は", "ぱ"), ("ひ", "ぴ"), ("ふ", "ぷ"), ("へ", "ぺ"), ("ほ", "ぽ"),
    ("ハ", "パ"), ("ヒ", "ピ"), ("フ", "プ"), ("ヘ", "ペ"), ("ホ", "ポ"),
)


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(slot), 16): str(char) for slot, char in payload.get("verified_charmap", {}).items()}


def game_glyph(data: bytes, slot: int) -> np.ndarray:
    raw = data[FONT_BASE + slot * FONT_STRIDE : FONT_BASE + (slot + 1) * FONT_STRIDE]
    pixels = np.zeros((16, 8), dtype=np.uint8)
    for y in range(16):
        for half in range(2):
            value = raw[y * 2 + half]
            for x in range(4):
                pixels[y, half * 4 + x] = 1 if (value & 0x03) else 0
                value >>= 2
    return pixels


def invert_map(charmap: dict[int, str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for slot, char in charmap.items():
        result.setdefault(char, slot)
    return result


def pair_delta(glyphs: dict[int, np.ndarray], charmap: dict[int, str], pairs: tuple[tuple[str, str], ...]) -> np.ndarray | None:
    by_char = invert_map(charmap)
    deltas: list[np.ndarray] = []
    for base, voiced in pairs:
        if base not in by_char or voiced not in by_char:
            continue
        left = glyphs[by_char[base]]
        right = glyphs[by_char[voiced]]
        if not np.array_equal(np.minimum(left, right), left):
            continue
        delta = right - left
        if int(delta.sum()):
            deltas.append(delta)
    if not deltas:
        return None
    stacked = np.stack(deltas)
    if not np.all(stacked == stacked[0], axis=0).all():
        # Keep pixels that are extra in every observed pair.
        common = np.min(stacked, axis=0)
        if not int(common.sum()):
            return None
        return common.astype(np.uint8)
    return deltas[0]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    rom = args.rom.read_bytes()
    charmap = load_map(args.seed)
    glyphs = {slot: game_glyph(rom, slot) for slot in range(FONT_COUNT)}
    by_char = invert_map(charmap)
    used_chars = set(charmap.values())
    mapped_slots = set(charmap)
    dakuten = pair_delta(glyphs, charmap, VOICED_PAIRS)
    handakuten = pair_delta(glyphs, charmap, HANDAKUTEN_PAIRS)

    inferred: dict[int, str] = {}
    evidence: list[dict[str, str]] = []
    for pairs, delta, kind in (
        (VOICED_PAIRS, dakuten, "dakuten"),
        (HANDAKUTEN_PAIRS, handakuten, "handakuten"),
    ):
        if delta is None:
            continue
        for base, voiced in pairs:
            if voiced in used_chars or base not in by_char:
                continue
            predicted = np.maximum(glyphs[by_char[base]], delta)
            hits = [
                slot
                for slot, glyph in glyphs.items()
                if slot not in mapped_slots and np.array_equal(glyph, predicted)
            ]
            if len(hits) != 1:
                continue
            slot = hits[0]
            inferred[slot] = voiced
            used_chars.add(voiced)
            mapped_slots.add(slot)
            evidence.append({
                "slot": f"0x{slot:04X}",
                "char": voiced,
                "base_char": base,
                "base_slot": f"0x{by_char[base]:04X}",
                "kind": kind,
            })

    combined = dict(charmap)
    combined.update(inferred)
    payload = {
        "schema_version": 1,
        "font_mode": "8x16",
        "method": "exact atlas-internal dakuten/handakuten completion from known voiced pairs",
        "base_seed": str(args.seed),
        "dakuten_pixels": None if dakuten is None else int(dakuten.sum()),
        "handakuten_pixels": None if handakuten is None else int(handakuten.sum()),
        "inferred_slot_count": len(inferred),
        "verified_charmap": {f"0x{slot:04X}": combined[slot] for slot in sorted(combined)},
        "inferred": evidence,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "dakuten_pixels": payload["dakuten_pixels"],
        "handakuten_pixels": payload["handakuten_pixels"],
        "inferred_slots": len(inferred),
        "inferred": evidence,
        "combined_slots": len(combined),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
