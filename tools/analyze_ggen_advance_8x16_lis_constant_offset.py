#!/usr/bin/env python3
"""Find high-confidence constant-offset blocks between GGA 8x16 and 12x12 atlases.

The current verified 8x16 charmap and the mostly decoded 12x12 charmap provide
same-character anchor pairs.  We first choose the longest monotone subsequence
of unique same-character pairs, then split it into runs with a constant
(slot12-slot8) offset.  A run is considered promotion-safe only when:

* at least three anchors support the identical offset; and
* every already-known 8x16 slot inside the run span whose mapped 12x12 slot is
  decoded agrees exactly with that 12x12 character.

This is a structural position proof rather than OCR.  It is intentionally
read-only and reports unresolved production/UI slots inside safe runs.
"""
from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MAP8_DEFAULT = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
MAP12_DEFAULT = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
MERGED_DEFAULT = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"
RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
QUARANTINE = {0x03D9, 0x0101, 0x05F2, 0x0514, 0x0652}
# Explicit cross-method conflict found on 2026-08-29; keep held until resolved.
EXPLICIT_HOLD = {0x0247}


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(k), 16): str(v) for k, v in payload["verified_charmap"].items()}


def monotone_unique_pairs(map8: dict[int, str], map12: dict[int, str]) -> list[tuple[int, int, str]]:
    reverse12: dict[str, list[int]] = defaultdict(list)
    for slot, char in map12.items():
        reverse12[char].append(slot)
    pairs = [
        (slot8, reverse12[char][0], char)
        for slot8, char in sorted(map8.items())
        if slot8 >= 0x0140 and len(reverse12.get(char, ())) == 1
    ]
    if not pairs:
        return []
    tails: list[int] = []
    tails_index: list[int] = []
    previous = [-1] * len(pairs)
    for index, (_slot8, slot12, _char) in enumerate(pairs):
        pos = bisect.bisect_left(tails, slot12)
        if pos == len(tails):
            tails.append(slot12)
            tails_index.append(index)
        else:
            tails[pos] = slot12
            tails_index[pos] = index
        if pos > 0:
            previous[index] = tails_index[pos - 1]
    cursor = tails_index[-1]
    indices: list[int] = []
    while cursor != -1:
        indices.append(cursor)
        cursor = previous[cursor]
    return [pairs[index] for index in reversed(indices)]


def constant_offset_runs(lis: list[tuple[int, int, str]]) -> list[list[tuple[int, int, str]]]:
    if not lis:
        return []
    runs: list[list[tuple[int, int, str]]] = []
    current = [lis[0]]
    for pair in lis[1:]:
        if pair[1] - pair[0] == current[-1][1] - current[-1][0]:
            current.append(pair)
        else:
            runs.append(current)
            current = [pair]
    runs.append(current)
    return runs


def pending(path: Path, map8: dict[int, str]) -> tuple[Counter[int], dict[int, list[dict[str, Any]]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    freq: Counter[int] = Counter()
    samples: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in payload.get("records", []):
        if row.get("translation_status") != "pending" or row.get("translation_policy") != "translate":
            continue
        if row.get("source_scope") not in {"production", "non_scenario_ui"}:
            continue
        if row.get("semantic_category") == "configuration_option_text":
            continue
        for raw in row.get("source_unresolved_slots", []):
            try:
                slot = int(str(raw), 16)
            except (TypeError, ValueError):
                continue
            if slot in map8 or slot in RESERVED:
                continue
            freq[slot] += 1
            if len(samples[slot]) < 5:
                samples[slot].append({
                    "record_id": row.get("record_id"),
                    "semantic_category": row.get("semantic_category"),
                    "source_text": row.get("source_text"),
                })
    return freq, samples


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map8", type=Path, default=MAP8_DEFAULT)
    ap.add_argument("--map12", type=Path, default=MAP12_DEFAULT)
    ap.add_argument("--merged", type=Path, default=MERGED_DEFAULT)
    ap.add_argument("--min-support", type=int, default=3)
    ap.add_argument("--top", type=int, default=200)
    args = ap.parse_args(argv)
    for path in (args.map8, args.map12, args.merged):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    map8 = load_map(args.map8)
    map12 = load_map(args.map12)
    lis = monotone_unique_pairs(map8, map12)
    runs = constant_offset_runs(lis)
    safe_runs: list[dict[str, Any]] = []
    rejected_runs: list[dict[str, Any]] = []
    calibration_events: list[dict[str, Any]] = []

    for run in runs:
        if len(run) < args.min_support:
            continue
        lo8, hi8 = run[0][0], run[-1][0]
        delta = run[0][1] - run[0][0]
        checks: list[dict[str, Any]] = []
        for slot8 in range(lo8, hi8 + 1):
            slot12 = slot8 + delta
            if slot8 not in map8 or slot12 not in map12:
                continue
            event = {
                "slot8": f"0x{slot8:04X}",
                "slot12": f"0x{slot12:04X}",
                "expected": map8[slot8],
                "predicted": map12[slot12],
                "correct": map8[slot8] == map12[slot12],
            }
            checks.append(event)
            calibration_events.append(event)
        row = {
            "support": len(run),
            "slot8_start": f"0x{lo8:04X}",
            "slot8_end": f"0x{hi8:04X}",
            "slot12_start": f"0x{run[0][1]:04X}",
            "slot12_end": f"0x{run[-1][1]:04X}",
            "delta": delta,
            "anchors": [
                {"slot8": f"0x{s8:04X}", "slot12": f"0x{s12:04X}", "char": char}
                for s8, s12, char in run
            ],
            "known_checks": len(checks),
            "known_correct": sum(bool(check["correct"]) for check in checks),
            "known_wrong": sum(not bool(check["correct"]) for check in checks),
            "wrong_examples": [check for check in checks if not check["correct"]],
        }
        if checks and all(check["correct"] for check in checks):
            safe_runs.append(row)
        else:
            rejected_runs.append(row)

    freq, samples = pending(args.merged, map8)
    candidates: dict[int, dict[str, Any]] = {}
    for run in safe_runs:
        lo8 = int(run["slot8_start"], 16)
        hi8 = int(run["slot8_end"], 16)
        delta = int(run["delta"])
        for slot8 in range(lo8, hi8 + 1):
            slot12 = slot8 + delta
            if slot8 not in freq or slot12 not in map12:
                continue
            if slot8 in QUARANTINE or slot8 in EXPLICIT_HOLD:
                continue
            candidates[slot8] = {
                "slot8": f"0x{slot8:04X}",
                "slot12": f"0x{slot12:04X}",
                "char": map12[slot12],
                "pending_records": freq[slot8],
                "support": run["support"],
                "run": f"{run['slot8_start']}-{run['slot8_end']}",
                "delta": delta,
                "samples": samples.get(slot8, []),
            }

    candidate_rows = sorted(
        candidates.values(),
        key=lambda row: (-row["pending_records"], -row["support"], int(row["slot8"], 16)),
    )
    safe_checks = [
        check
        for run in safe_runs
        for check in [
            {
                "slot8": f"0x{slot8:04X}",
                "slot12": f"0x{slot8 + int(run['delta']):04X}",
                "expected": map8[slot8],
                "predicted": map12[slot8 + int(run["delta"])],
                "correct": map8[slot8] == map12[slot8 + int(run["delta"])],
            }
            for slot8 in range(int(run["slot8_start"], 16), int(run["slot8_end"], 16) + 1)
            if slot8 in map8 and slot8 + int(run["delta"]) in map12
        ]
    ]
    correct = sum(bool(check["correct"]) for check in safe_checks)

    payload = {
        "schema_version": 1,
        "method": "LIS same-character anchors + contradiction-free constant-offset runs",
        "verified_8x16_slots": len(map8),
        "unique_same_char_lis_anchors": len(lis),
        "min_support": args.min_support,
        "safe_run_count": len(safe_runs),
        "rejected_run_count": len(rejected_runs),
        "safe_run_calibration": {
            "events": len(safe_checks),
            "correct": correct,
            "wrong": len(safe_checks) - correct,
            "precision": round(correct / len(safe_checks), 6) if safe_checks else 0.0,
        },
        "candidate_count": len(candidate_rows),
        "candidate_pending_record_coverage": sum(row["pending_records"] for row in candidate_rows),
        "explicit_hold": [f"0x{slot:04X}" for slot in sorted(EXPLICIT_HOLD)],
        "quarantine": [f"0x{slot:04X}" for slot in sorted(QUARANTINE)],
        "safe_runs": safe_runs,
        "rejected_runs": rejected_runs,
        "candidates": candidate_rows[: args.top],
        "notes": [
            "Read-only; no charmap/source/ROM writes.",
            "Any run containing a known mismatch is rejected as a whole.",
            "0x0247 is held because an independent Shift-JIS Viterbi pass disagrees with the constant-offset prediction.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
