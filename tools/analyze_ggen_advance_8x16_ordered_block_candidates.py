#!/usr/bin/env python3
"""Find short exact-count Shift-JIS ordered-block candidates for GGA 8x16.

This is a read-only evidence generator.  It uses three independent signals:

1. Neighboring verified 8x16 characters are strictly increasing in Shift-JIS.
2. The number of verified 12x12 characters between those anchors exactly equals
   the number of intervening 8x16 slots.
3. The proposed character is compared with the actual 8x16 bitmap using a
   small ensemble of installed Japanese system fonts.

The ordered-block rule is calibrated by leave-one-out over already verified
8x16 slots.  Nothing is promoted automatically by this tool.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ROM_DEFAULT = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MAP8_DEFAULT = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
MAP12_DEFAULT = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
MERGED_DEFAULT = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"

FONT8_BASE = 0x00094028
FONT8_STRIDE = 32
FONT8_COUNT = 2068
RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
QUARANTINE = {0x03D9, 0x0101, 0x05F2, 0x0514, 0x0652}

FONTS = (
    (Path(r"C:\Windows\Fonts\msgothic.ttc"), 13, "MS Gothic 13"),
    (Path(r"C:\Windows\Fonts\msgothic.ttc"), 14, "MS Gothic 14"),
    (Path(r"C:\Windows\Fonts\meiryo.ttc"), 12, "Meiryo 12"),
    (Path(r"C:\Windows\Fonts\msmincho.ttc"), 13, "MS Mincho 13"),
)


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(k), 16): str(v) for k, v in payload["verified_charmap"].items()}


def sjis_value(char: str) -> int | None:
    try:
        raw = char.encode("shift_jis")
    except (UnicodeEncodeError, LookupError):
        return None
    if len(raw) != 2:
        return None
    return int.from_bytes(raw, "big")


def decode_glyph8(data: bytes, slot: int) -> Image.Image:
    raw = data[FONT8_BASE + slot * FONT8_STRIDE : FONT8_BASE + (slot + 1) * FONT8_STRIDE]
    image = Image.new("L", (8, 16), 0)
    pixels = image.load()
    for y in range(16):
        for half in range(2):
            value = raw[y * 2 + half]
            for x in range(4):
                pixels[half * 4 + x, y] = 255 if (value & 0x03) else 0
                value >>= 2
    return image


def crop(image: Image.Image) -> Image.Image:
    bbox = image.getbbox()
    if bbox is None:
        return Image.new("L", (1, 1), 0)
    return image.crop(bbox)


def resize_mask(image: Image.Image, size: tuple[int, int] = (11, 11)) -> bytes:
    image = image.resize(size, Image.Resampling.NEAREST)
    return bytes(1 if value else 0 for value in image.getdata())


def render_char(char: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    image = Image.new("L", (32, 32), 0)
    ImageDraw.Draw(image).text((8, 8), char, font=font, fill=255)
    return image.point(lambda value: 255 if value > 64 else 0)


def f1(left: bytes, right: bytes) -> float:
    intersection = sum(1 for a, b in zip(left, right) if a and b)
    total = sum(left) + sum(right)
    return (2.0 * intersection / total) if total else 1.0


def ensemble_scores(data: bytes, slots: list[int], candidate_chars: list[str]) -> dict[int, dict[str, float]]:
    fonts = [
        (ImageFont.truetype(str(path), size=size, index=0), label)
        for path, size, label in FONTS
        if path.exists()
    ]
    rendered: dict[str, list[np.ndarray]] = {}
    for char in candidate_chars:
        variants = []
        for font, _label in fonts:
            mask = crop(render_char(char, font))
            variants.append(resize_mask(mask))
        rendered[char] = variants
    out: dict[int, dict[str, float]] = {}
    for slot in slots:
        target = resize_mask(crop(decode_glyph8(data, slot)))
        scores: dict[str, float] = {}
        for char, variants in rendered.items():
            scores[char] = max((f1(target, variant) for variant in variants), default=0.0)
        out[slot] = scores
    return out


def pending_slot_rows(merged: dict[str, Any], fixed: dict[int, str]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in merged.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        if row.get("source_scope") not in {"production", "non_scenario_ui"}:
            continue
        unresolved = []
        for raw in row.get("source_unresolved_slots", []):
            try:
                slot = int(str(raw), 16)
            except (TypeError, ValueError):
                continue
            if slot in fixed or slot in RESERVED:
                continue
            unresolved.append(slot)
        for slot in set(unresolved):
            if len(result[slot]) < 10:
                result[slot].append({
                    "record_id": row.get("record_id"),
                    "scope": row.get("source_scope"),
                    "semantic_category": row.get("semantic_category"),
                    "source_text": row.get("source_text"),
                })
    return result


def exact_intervals(map8: dict[int, str], chars12: set[str], max_gap: int) -> list[dict[str, Any]]:
    known = []
    for slot, char in sorted(map8.items()):
        value = sjis_value(char)
        if value is not None and 0x0140 <= slot <= 0x07D0:
            known.append((slot, char, value))
    valid12 = sorted((sjis_value(char), char) for char in chars12 if sjis_value(char) is not None)
    intervals = []
    for left, right in zip(known, known[1:]):
        if left[2] >= right[2]:
            continue
        gap = right[0] - left[0] - 1
        if gap <= 0 or gap > max_gap:
            continue
        between = [char for value, char in valid12 if left[2] < value < right[2]]
        if len(between) != gap:
            continue
        intervals.append({
            "left": left,
            "right": right,
            "gap": gap,
            "chars": between,
        })
    return intervals


def leave_one_out(map8: dict[int, str], chars12: set[str], max_span: int) -> list[dict[str, Any]]:
    known = []
    for slot, char in sorted(map8.items()):
        value = sjis_value(char)
        if value is not None and 0x0140 <= slot <= 0x07D0:
            known.append((slot, char, value))
    valid12 = sorted((sjis_value(char), char) for char in chars12 if sjis_value(char) is not None)
    events = []
    for index in range(1, len(known) - 1):
        left, hidden, right = known[index - 1], known[index], known[index + 1]
        if not (left[2] < hidden[2] < right[2]):
            continue
        span = right[0] - left[0] - 1
        if span <= 0 or span > max_span:
            continue
        between = [char for value, char in valid12 if left[2] < value < right[2]]
        if len(between) != span:
            continue
        offset = hidden[0] - left[0] - 1
        predicted = between[offset]
        events.append({
            "slot": f"0x{hidden[0]:04X}",
            "expected": hidden[1],
            "predicted": predicted,
            "correct": predicted == hidden[1],
            "span": span,
            "left": {"slot": f"0x{left[0]:04X}", "char": left[1]},
            "right": {"slot": f"0x{right[0]:04X}", "char": right[1]},
        })
    return events


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=ROM_DEFAULT)
    ap.add_argument("--map8", type=Path, default=MAP8_DEFAULT)
    ap.add_argument("--map12", type=Path, default=MAP12_DEFAULT)
    ap.add_argument("--merged", type=Path, default=MERGED_DEFAULT)
    ap.add_argument("--max-gap", type=int, default=7)
    ap.add_argument("--max-span-calibration", type=int, default=8)
    ap.add_argument("--top-rank", type=int, default=20)
    args = ap.parse_args(argv)

    for path in (args.rom, args.map8, args.map12, args.merged):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    map8 = load_map(args.map8)
    map12 = load_map(args.map12)
    chars12 = set(map12.values())
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    slot_rows = pending_slot_rows(merged, map8)
    intervals = exact_intervals(map8, chars12, args.max_gap)
    proposed: list[tuple[int, str, dict[str, Any]]] = []
    for interval in intervals:
        left_slot = int(interval["left"][0])
        for offset, char in enumerate(interval["chars"], start=1):
            slot = left_slot + offset
            if slot in QUARANTINE or slot not in slot_rows:
                continue
            proposed.append((slot, char, interval))

    data = args.rom.read_bytes()
    candidate_chars = sorted(chars12 | {char for _, char, _ in proposed})
    score_map = ensemble_scores(data, sorted({slot for slot, _, _ in proposed}), candidate_chars)
    candidates = []
    for slot, char, interval in proposed:
        scores = score_map[slot]
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        rank = next((index for index, (item_char, _score) in enumerate(ranked, start=1) if item_char == char), None)
        score = scores.get(char, 0.0)
        candidates.append({
            "slot": f"0x{slot:04X}",
            "char": char,
            "ordered_gap": interval["gap"],
            "left_anchor": {"slot": f"0x{interval['left'][0]:04X}", "char": interval["left"][1]},
            "right_anchor": {"slot": f"0x{interval['right'][0]:04X}", "char": interval["right"][1]},
            "font_ensemble_score": round(score, 4),
            "font_ensemble_rank": rank,
            "font_top5": [{"char": c, "score": round(v, 4)} for c, v in ranked[:5]],
            "contexts": slot_rows.get(slot, [])[:6],
        })
    candidates.sort(key=lambda item: (item["font_ensemble_rank"] or 99999, -item["font_ensemble_score"], int(item["slot"], 16)))

    loo = leave_one_out(map8, chars12, args.max_span_calibration)
    payload = {
        "schema_version": 1,
        "method": "short exact-count Shift-JIS ordered interval + system-font bitmap ensemble",
        "max_gap": args.max_gap,
        "calibration": {
            "max_span": args.max_span_calibration,
            "events": len(loo),
            "correct": sum(bool(item["correct"]) for item in loo),
            "wrong": sum(not bool(item["correct"]) for item in loo),
            "precision": round(sum(bool(item["correct"]) for item in loo) / len(loo), 6) if loo else 0.0,
            "details": loo,
        },
        "exact_intervals": len(intervals),
        "proposed_remaining_slots": len(candidates),
        "font_rank_le_1": sum(item["font_ensemble_rank"] == 1 for item in candidates),
        "font_rank_le_5": sum((item["font_ensemble_rank"] or 99999) <= 5 for item in candidates),
        "font_rank_le_20": sum((item["font_ensemble_rank"] or 99999) <= 20 for item in candidates),
        "candidates": candidates,
        "notes": [
            "No ROM/charmap/source files are modified.",
            "Exact-count ordering is not sufficient by itself; it is only one evidence channel.",
            "Quarantined ID-command-only slots are excluded.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
