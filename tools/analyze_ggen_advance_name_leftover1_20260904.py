#!/usr/bin/env python3
"""Leftover=1 slot hunt for pending ID-command names and unit names."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, RESERVED
from build_ggen_advance_unified_rom_poc import CHARMAP_8X16_PATH, load_identified_slot_to_char
from ggen_advance_project_paths import TRANSLATION_MERGED_JSON

SLOT_RE = re.compile(r"<([0-9A-Fa-f]{4})>")
CATEGORIES = {"id_command_name", "unit_name", "unit_name_alternate", "character_name", "weapon_name"}
OUTPUT = ROOT / "analysis" / "ggen_advance_name_leftover1_20260904.json"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    map8 = load_identified_slot_to_char(CHARMAP_8X16_PATH)
    map8.update(CORRECTED_LOW_KANA)
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    leftover1 = defaultdict(list)
    freq = Counter()
    pending = 0
    for row in merged["records"]:
        if row.get("translation_status") != "pending" or row.get("semantic_category") not in CATEGORIES:
            continue
        if row.get("scope_status") != "included":
            continue
        pending += 1
        source = str(row.get("source_text") or "")
        unknown = []
        decoded_parts = []
        for token in SLOT_RE.finditer(source):
            slot = int(token.group(1), 16)
            if slot in RESERVED:
                decoded_parts.append(token.group(0))
                continue
            char = map8.get(slot)
            if char is None:
                unknown.append(slot)
                decoded_parts.append(f"<{slot:04X}>")
            else:
                decoded_parts.append(char)
        # also plain text between markers is already in source; reconstruct by replacing known
        def repl(match):
            slot = int(match.group(1), 16)
            if slot in RESERVED:
                return match.group(0)
            return map8.get(slot, match.group(0))
        decoded = SLOT_RE.sub(repl, source)
        leftover = [slot for slot in unknown]
        for slot in leftover:
            freq[slot] += 1
        if len(leftover) == 1:
            leftover1[leftover[0]].append({
                "record_id": row["record_id"],
                "category": row["semantic_category"],
                "decoded": decoded,
            })

    promotions = []
    for slot, rows in sorted(leftover1.items(), key=lambda item: (-len(item[1]), item[0])):
        frames = sorted({item["decoded"] for item in rows})
        promotions.append({
            "slot": f"0x{slot:04X}",
            "leftover1_rows": len(rows),
            "unique_frames": frames[:12],
            "frame_count": len(frames),
            "categories": sorted({item["category"] for item in rows}),
        })
    report = {
        "pending_name_rows": pending,
        "leftover1_slots": len(leftover1),
        "leftover1_with_2plus_frames": sum(1 for item in promotions if item["frame_count"] >= 2),
        "top_freq": [{"slot": f"0x{slot:04X}", "count": count} for slot, count in freq.most_common(40)],
        "leftover1": promotions[:80],
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "pending_name_rows": pending,
        "leftover1_slots": len(leftover1),
        "leftover1_with_2plus_frames": report["leftover1_with_2plus_frames"],
        "top_freq": report["top_freq"][:20],
        "leftover1_2plus": [item for item in promotions if item["frame_count"] >= 2][:25],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
