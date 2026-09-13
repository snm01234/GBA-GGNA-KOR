#!/usr/bin/env python3
"""Re-decode scenario pending rows from original slot lists, not source_text kana.

The immutable source_text still contains the uncorrected low-kana draft.  ROM
application requires leftover 12x12 glyphs identified against the actual slot
stream plus renderer-verified kana.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT.parent / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, RESERVED, load_map  # noqa: E402
import build_ggen_advance_ko_poc as fontops  # noqa: E402

DEFAULT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
DEFAULT_SCENARIO = ROOT / "analysis" / "scenario_event_translation_source_20260827.json"
DEFAULT_MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_scenario_pending_slot_queue_20260828.json"
DEFAULT_SHEET = ROOT / "analysis" / "ggen_advance_scenario_pending_glyph_sheet_20260828.png"


def decode_slots(slots: list[int], charmap: dict[int, str]) -> tuple[str, list[int]]:
    chars: list[str] = []
    missing: list[int] = []
    for slot in slots:
        if slot in RESERVED:
            missing.append(slot)
            chars.append(f"<{slot:04X}>")
            continue
        char = charmap.get(slot)
        if char is None:
            missing.append(slot)
            chars.append(f"<{slot:04X}>")
        else:
            chars.append(char)
    return "".join(chars), missing


def is_bark(decoded: str) -> bool:
    return "セリフ" in decoded and decoded.count("＠") >= 2


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--map12", type=Path, default=DEFAULT_MAP12)
    parser.add_argument("--rom", type=Path, default=ROOT / "SD Gundam GGeneration Advance (Japan).gba")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    args = parser.parse_args(argv)

    map12 = load_map(args.map12)
    map12.update(CORRECTED_LOW_KANA)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    source_rows = scenario.get("records")
    if not isinstance(source_rows, list):
        source_rows = (scenario.get("main") or {}).get("records") or []
    by_id = {str(row["record_id"]): row for row in source_rows if isinstance(row, dict) and row.get("record_id")}

    class_counts: Counter[str] = Counter()
    slot_freq: Counter[int] = Counter()
    close1: Counter[int] = Counter()
    nonbark: dict[int, Counter[str]] = defaultdict(Counter)
    bark: dict[int, Counter[str]] = defaultdict(Counter)
    leftover2: dict[int, Counter[str]] = defaultdict(Counter)
    samples: dict[int, list[dict]] = defaultdict(list)
    pending_ids: list[str] = []

    for row in merged.get("records", []):
        if row.get("source_scope") != "scenario_main" or row.get("scope_status") != "included":
            continue
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        pending_ids.append(row["record_id"])
        source = by_id.get(row["record_id"])
        if source is None:
            class_counts["missing_scenario_source"] += 1
            continue
        leftover_text: list[int] = []
        parts: list[str] = []
        for segment in source.get("segments") or []:
            slots = [int(str(item), 16) for item in (segment.get("slots") or [])]
            if not slots:
                continue
            text, missing = decode_slots(slots, map12)
            parts.append(text)
            for slot in missing:
                if slot not in RESERVED and slot not in leftover_text:
                    leftover_text.append(slot)
        decoded = "\n".join(parts)
        if not leftover_text:
            kind = "unused_bark_template" if is_bark(decoded) else "fully_decoded"
        elif len(leftover_text) == 1:
            kind = "single_unknown_text_slot"
        elif len(leftover_text) <= 3:
            kind = "few_unknown_text_slots"
        else:
            kind = "many_unknown_text_slots"
        class_counts[kind] += 1
        slot_freq.update(leftover_text)
        if kind == "single_unknown_text_slot":
            slot = leftover_text[0]
            close1[slot] += 1
            frame = decoded.replace("\n", " / ")
            (bark if is_bark(decoded) else nonbark)[slot][frame] += 1
            if len(samples[slot]) < 8:
                samples[slot].append(
                    {
                        "record_id": row["record_id"],
                        "directory_row": row.get("directory_row"),
                        "decoded_from_slots": decoded,
                        "bark": is_bark(decoded),
                    }
                )
        elif kind == "few_unknown_text_slots" and len(leftover_text) == 2:
            frame = decoded.replace("\n", " / ")
            if not is_bark(decoded):
                for slot in leftover_text:
                    leftover2[slot][frame] += 1

    queue = []
    for slot, count in slot_freq.most_common():
        nb = nonbark.get(slot, Counter())
        bk = bark.get(slot, Counter())
        if not nb and not bk:
            hold = "no_single_unknown"
        elif not nb:
            hold = "bark_template_only"
        elif len(nb) == 1:
            hold = "single_collocation"
        else:
            hold = "mixed_frames"
        queue.append(
            {
                "slot": f"0x{slot:04X}",
                "pending_records": count,
                "rows_closed_if_identified": close1[slot],
                "leftover1_nonbark_frames": len(nb),
                "leftover1_bark_frames": len(bk),
                "hold": hold,
                "top_nonbark": [frame[:120] for frame, _ in nb.most_common(6)],
                "top_bark": [frame[:80] for frame, _ in bk.most_common(3)],
                "top_leftover2": [frame[:140] for frame, _ in leftover2.get(slot, Counter()).most_common(6)],
                "samples": samples.get(slot, []),
            }
        )

    payload = {
        "schema_version": 2,
        "method": "decode pending scenario_main from original slot lists + identified 12x12 + corrected low kana",
        "map12_slots": len(map12),
        "pending_rows": len(pending_ids),
        "classification": dict(class_counts),
        "unique_leftover_slots": len(slot_freq),
        "fully_decoded_now": class_counts.get("fully_decoded", 0) + class_counts.get("unused_bark_template", 0),
        "queue": queue,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rom = args.rom.read_bytes()
    top = queue
    cell = 52
    label_h = 18
    cols = 12
    rows = max(1, (len(top) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * cell, rows * (cell + label_h)), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
    for index, item in enumerate(top):
        slot = int(item["slot"], 16)
        glyph = fontops.unpack_12x12(
            rom[fontops.FONT_12X12_BASE + slot * fontops.FONT_12X12_STRIDE : fontops.FONT_12X12_BASE + (slot + 1) * fontops.FONT_12X12_STRIDE]
        ).convert("RGB")
        glyph = glyph.resize((36, 36), Image.Resampling.NEAREST)
        x = (index % cols) * cell
        y = (index // cols) * (cell + label_h)
        sheet.paste(glyph, (x + 8, y + 2))
        draw.text((x + 2, y + 40), f"{item['slot'][2:]} n={item['pending_records']}", fill=(220, 220, 220), font=font)
    args.sheet.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.sheet)

    compact_path = args.out.with_name("ggen_advance_scenario_pending_review_compact_20260828.json")
    compact = [
        {
            "slot": item["slot"],
            "pending": item["pending_records"],
            "close1": item["rows_closed_if_identified"],
            "hold": item["hold"],
            "nonbark": item["leftover1_nonbark_frames"],
            "bark": item["leftover1_bark_frames"],
            "top_nonbark": item["top_nonbark"],
            "top_bark": item["top_bark"],
            "top_leftover2": item["top_leftover2"],
        }
        for item in queue
    ]
    compact_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "output": str(args.out),
        "sheet": str(args.sheet),
        "compact": str(compact_path),
        "pending_rows": payload["pending_rows"],
        "classification": payload["classification"],
        "unique_leftover_slots": payload["unique_leftover_slots"],
        "fully_decoded_now": payload["fully_decoded_now"],
        "top_holds": [
            {
                "slot": item["slot"],
                "pending": item["pending_records"],
                "close1": item["rows_closed_if_identified"],
                "hold": item["hold"],
                "nonbark": item["leftover1_nonbark_frames"],
                "bark": item["leftover1_bark_frames"],
            }
            for item in queue[:20]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
