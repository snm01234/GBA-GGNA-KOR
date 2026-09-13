#!/usr/bin/env python3
"""Intersect 所有数 fixed-graphics scan candidates with live JP ss1 sprite binds."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import analyze_ggen_advance_owned_count_resource_bind_20260905 as bind
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, advance_relative

SCAN = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_graphics_scan_20260904.json"
JP_STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).ss1"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_owned_count_loaded_candidates_20260905.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    state, _ = statefmt.parse_png_state(JP_STATE)
    slots = bind.sprite_slots(state)
    live = {(row["resource"], int(row["animation"])): row for row in slots}
    intersections = []
    resource_only = []
    live_resources = {row["resource"] for row in slots}
    for rank, cand in enumerate(scan["candidates"], start=1):
        key = (cand["resource_address"], int(cand["animation"]))
        row = {"scan_rank": rank, **cand}
        if key in live:
            row["live_slot"] = live[key]
            intersections.append(row)
        elif cand["resource_address"] in live_resources:
            row["resident_other_animations"] = [
                {"slot": slot["slot"], "animation": slot["animation"], "x": slot["x"], "y": slot["y"]}
                for slot in slots if slot["resource"] == cand["resource_address"]
            ]
            resource_only.append(row)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_owned_count_loaded_candidates_20260905",
        "result": "PASS",
        "source": {
            "scan": advance_relative(SCAN),
            "state": advance_relative(JP_STATE),
            "state_sha256": sha256(JP_STATE.read_bytes()),
        },
        "resident_sprite_slots": slots,
        "exact_loaded_candidate_count": len(intersections),
        "exact_loaded_candidates": intersections,
        "resident_resource_wrong_animation_count": len(resource_only),
        "resident_resource_wrong_animation_candidates": resource_only,
        "conclusion": (
            "Only exact resource+animation intersections can own visible fixed artwork in this captured state; resource-only matches are rejected for this frame."
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": advance_relative(OUT),
        "exact_loaded_candidate_count": len(intersections),
        "exact_loaded_candidates": [
            {
                "rank": row["scan_rank"],
                "resource": row["resource_address"],
                "animation": row["animation"],
                "score": row["score"],
                "slot": row["live_slot"]["slot"],
                "xy": [row["live_slot"]["x"], row["live_slot"]["y"]],
            }
            for row in intersections[:30]
        ],
        "resource_only_top": [
            {"rank": row["scan_rank"], "resource": row["resource_address"], "animation": row["animation"], "score": row["score"], "live": row["resident_other_animations"]}
            for row in resource_only[:20]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
