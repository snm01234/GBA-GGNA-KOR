#!/usr/bin/env python3
"""Calibrate same-ROM Japanese text alignment for unresolved 8x16 slots.

The production/UI 8x16 atlas is still only partially identified, while the
12x12 map-script dialogue corpus is now fully decoded.  Matching a production
row to a same-length map-script string can recover 8x16 glyph identities, but
only if the matching rule is empirically safe.  A weak suffix-only match can
produce convincing but false results.

This tool therefore does two things without modifying any project data:

1. Leave-one-out calibration on *already known* 8x16 slots.  Each known glyph
   position is temporarily hidden, the row is aligned against the same-ROM
   map-script corpus using the remaining anchors, and the hidden character is
   checked against the verified charmap.
2. Candidate generation for currently unresolved production slots using only
   rule thresholds that pass the requested calibration precision.

The output is printed to stdout.  No ROM/charmap/source file is rewritten.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROWS = ROOT / "analysis" / "stage2_translation_sheet_rows_20260827.json"
DEFAULT_MAP8 = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"
DEFAULT_CORPORA = (
    ROOT / "analysis" / "ggen_advance_map_script_translation_source_20260828.json",
    ROOT / "analysis" / "ggen_advance_scenario_pending_closed_strings_20260828.json",
    ROOT / "analysis" / "ggen_advance_scenario_slot_complete_dialogue_20260828.json",
)

RESERVED = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}
JAPANESE_RE = re.compile(r"[ぁ-ゖァ-ヺ一-龯々〆ヶ！？。、・ー…「」『』]", re.UNICODE)
PLACEHOLDER_RE = re.compile(r"<[0-9A-Fa-f]{4}>|⟦|⟧")


def normalize(value: str) -> str:
    return (
        unicodedata.normalize("NFKC", value)
        .replace("　", " ")
        .replace("－", "ー")
        .strip()
    )


def walk_same_rom_japanese(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        text = value.get("source_text")
        if isinstance(text, str):
            yield text
        parts = value.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, str):
                    yield part
        jp = value.get("jp")
        if isinstance(jp, str) and not isinstance(parts, list):
            yield jp
        elif isinstance(jp, list):
            for part in jp:
                if isinstance(part, str):
                    yield part
        for key, child in value.items():
            if key in {"source_text", "parts", "jp"}:
                continue
            if isinstance(child, (dict, list)):
                yield from walk_same_rom_japanese(child)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, str):
                yield child
            elif isinstance(child, (dict, list)):
                yield from walk_same_rom_japanese(child)


def load_corpus(paths: list[Path]) -> dict[int, tuple[str, ...]]:
    by_length: dict[int, set[str]] = defaultdict(set)
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for raw in walk_same_rom_japanese(payload):
            text = normalize(raw)
            if not text or "\n" in text or "\\n" in text or " / " in text:
                continue
            if PLACEHOLDER_RE.search(text):
                continue
            if not JAPANESE_RE.search(text):
                continue
            by_length[len(text)].add(text)
    return {length: tuple(sorted(values)) for length, values in by_length.items()}


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(str(slot), 16): str(char)
        for slot, char in payload.get("verified_charmap", {}).items()
    }


def load_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        row
        for row in payload.get("records", [])
        if row.get("translation_policy") == "translate"
        and row.get("slots")
        and str(row.get("source_text", ""))
    ]


def max_unknown_run(length: int, anchor_positions: set[int]) -> int:
    longest = 0
    current = 0
    for index in range(length):
        if index in anchor_positions:
            longest = max(longest, current)
            current = 0
        else:
            current += 1
    return max(longest, current)


def unique_candidate(
    candidates: tuple[str, ...],
    slots: list[int],
    fixed: dict[int, str],
    hidden_index: int | None = None,
) -> tuple[str | None, int, tuple[int, ...]]:
    anchor_positions = tuple(
        index
        for index, slot in enumerate(slots)
        if index != hidden_index and slot in fixed and slot not in RESERVED
    )
    if not anchor_positions:
        return None, 0, anchor_positions
    found: str | None = None
    count = 0
    for candidate in candidates:
        ok = True
        for index in anchor_positions:
            if candidate[index] != fixed[slots[index]]:
                ok = False
                break
        if not ok:
            continue
        count += 1
        if count == 1:
            found = candidate
        else:
            # Candidate uniqueness is mandatory; no need to keep scanning once
            # the match is known to be ambiguous.
            return None, count, anchor_positions
    return found if count == 1 else None, count, anchor_positions


@dataclass(frozen=True)
class Rule:
    min_anchors: int
    min_anchor_ratio: float
    max_unknown_positions: int
    max_unknown_run: int
    require_bilateral: bool

    @property
    def key(self) -> str:
        return (
            f"a{self.min_anchors}_r{self.min_anchor_ratio:.2f}_"
            f"u{self.max_unknown_positions}_run{self.max_unknown_run}_"
            f"bi{int(self.require_bilateral)}"
        )


def rule_accepts(
    rule: Rule,
    *,
    length: int,
    anchor_positions: tuple[int, ...],
    target_positions: tuple[int, ...],
) -> bool:
    anchors = len(anchor_positions)
    if anchors < rule.min_anchors:
        return False
    if anchors / max(1, length) < rule.min_anchor_ratio:
        return False
    unknown_positions = length - anchors
    if unknown_positions > rule.max_unknown_positions:
        return False
    anchor_set = set(anchor_positions)
    if max_unknown_run(length, anchor_set) > rule.max_unknown_run:
        return False
    if rule.require_bilateral:
        for target in target_positions:
            if not any(anchor < target for anchor in anchor_positions):
                return False
            if not any(anchor > target for anchor in anchor_positions):
                return False
    return True


def rule_grid() -> list[Rule]:
    rules: list[Rule] = []
    for min_anchors in (2, 3, 4, 5, 6, 8):
        for min_ratio in (0.40, 0.50, 0.60, 0.70, 0.80):
            for max_unknown in (1, 2, 3, 4):
                for max_run in (1, 2, 3):
                    for bilateral in (False, True):
                        rules.append(
                            Rule(min_anchors, min_ratio, max_unknown, max_run, bilateral)
                        )
    return rules


def calibration_events(
    rows: list[dict[str, Any]],
    corpus: dict[int, tuple[str, ...]],
    fixed: dict[int, str],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        slots = [int(str(value), 16) for value in row.get("slots", [])]
        candidates = corpus.get(len(slots), ())
        if not candidates:
            continue
        known_positions = [
            index
            for index, slot in enumerate(slots)
            if slot in fixed and slot not in RESERVED
        ]
        if len(known_positions) < 2:
            continue
        for hidden_index in known_positions:
            candidate, candidate_count, anchors = unique_candidate(
                candidates, slots, fixed, hidden_index
            )
            if candidate is None:
                continue
            hidden_slot = slots[hidden_index]
            expected = fixed[hidden_slot]
            predicted = candidate[hidden_index]
            events.append(
                {
                    "record_id": row.get("record_id"),
                    "semantic_category": row.get("semantic_category"),
                    "length": len(slots),
                    "hidden_index": hidden_index,
                    "hidden_slot": hidden_slot,
                    "expected": expected,
                    "predicted": predicted,
                    "correct": predicted == expected,
                    "candidate": candidate,
                    "candidate_count": candidate_count,
                    "anchors": anchors,
                }
            )
    return events


def evaluate_rules(events: list[dict[str, Any]], rules: list[Rule]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for rule in rules:
        accepted: list[dict[str, Any]] = []
        for event in events:
            hidden = int(event["hidden_index"])
            anchors = tuple(int(value) for value in event["anchors"])
            if rule_accepts(
                rule,
                length=int(event["length"]),
                anchor_positions=anchors,
                target_positions=(hidden,),
            ):
                accepted.append(event)
        if not accepted:
            continue
        correct = sum(bool(event["correct"]) for event in accepted)
        results.append(
            {
                "rule": rule,
                "accepted": len(accepted),
                "correct": correct,
                "wrong": len(accepted) - correct,
                "precision": correct / len(accepted),
                "distinct_rows": len({event["record_id"] for event in accepted}),
                "distinct_slots": len({event["hidden_slot"] for event in accepted}),
            }
        )
    results.sort(
        key=lambda item: (
            -float(item["precision"]),
            -int(item["accepted"]),
            -int(item["distinct_slots"]),
            item["rule"].key,
        )
    )
    return results


def select_rule(
    results: list[dict[str, Any]],
    *,
    min_precision: float,
    min_events: int,
) -> dict[str, Any] | None:
    eligible = [
        item
        for item in results
        if float(item["precision"]) >= min_precision
        and int(item["accepted"]) >= min_events
    ]
    if not eligible:
        return None
    # Among rules that satisfy the safety floor, maximize empirically validated
    # event coverage.  Precision still breaks ties before slot diversity.
    eligible.sort(
        key=lambda item: (
            -int(item["accepted"]),
            -float(item["precision"]),
            -int(item["distinct_slots"]),
            item["rule"].key,
        )
    )
    return eligible[0]


def candidate_votes(
    rows: list[dict[str, Any]],
    corpus: dict[int, tuple[str, ...]],
    fixed: dict[int, str],
    rule: Rule,
) -> tuple[dict[int, Counter[str]], dict[tuple[int, str], list[dict[str, Any]]], dict[str, int]]:
    votes: dict[int, Counter[str]] = defaultdict(Counter)
    evidence: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    stats = Counter()
    for row in rows:
        slots = [int(str(value), 16) for value in row.get("slots", [])]
        candidates = corpus.get(len(slots), ())
        if not candidates:
            stats["no_length_corpus"] += 1
            continue
        unresolved_positions = tuple(
            index
            for index, slot in enumerate(slots)
            if slot not in fixed and slot not in RESERVED
        )
        if not unresolved_positions:
            continue
        candidate, candidate_count, anchors = unique_candidate(candidates, slots, fixed, None)
        if candidate is None:
            stats["ambiguous_or_no_candidate"] += 1
            continue
        if not rule_accepts(
            rule,
            length=len(slots),
            anchor_positions=anchors,
            target_positions=unresolved_positions,
        ):
            stats["rule_rejected"] += 1
            continue
        stats["rule_accepted_rows"] += 1
        frame_key = tuple(slots)
        for index in unresolved_positions:
            slot = slots[index]
            char = candidate[index]
            votes[slot][char] += 1
            key = (slot, char)
            if len(evidence[key]) < 12:
                evidence[key].append(
                    {
                        "record_id": row.get("record_id"),
                        "semantic_category": row.get("semantic_category"),
                        "source_text": row.get("source_text"),
                        "candidate": candidate,
                        "position": index,
                        "anchor_count": len(anchors),
                        "anchor_ratio": round(len(anchors) / max(1, len(slots)), 4),
                        "slot_frame": [f"0x{value:04X}" for value in frame_key],
                    }
                )
    return votes, evidence, dict(stats)


def summarize_candidates(
    votes: dict[int, Counter[str]],
    evidence: dict[tuple[int, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slot, counts in votes.items():
        ranked = counts.most_common()
        top_char, top_votes = ranked[0]
        top_evidence = evidence[(slot, top_char)]
        distinct_record_ids = {str(item["record_id"]) for item in top_evidence}
        distinct_source_text = {str(item["source_text"]) for item in top_evidence}
        distinct_frames = {
            tuple(item["slot_frame"])
            for item in top_evidence
        }
        categories = sorted({str(item["semantic_category"]) for item in top_evidence})
        conflicting_votes = sum(count for _, count in ranked[1:])
        independent = len(distinct_frames) >= 2 or len(distinct_source_text) >= 2
        grade = "A" if top_votes >= 2 and conflicting_votes == 0 and independent else "B"
        rows.append(
            {
                "slot": f"0x{slot:04X}",
                "char": top_char,
                "votes": top_votes,
                "conflicting_votes": conflicting_votes,
                "alternatives": [
                    {"char": char, "votes": count}
                    for char, count in ranked[1:6]
                ],
                "distinct_record_ids": len(distinct_record_ids),
                "distinct_source_text": len(distinct_source_text),
                "distinct_slot_frames": len(distinct_frames),
                "semantic_categories": categories,
                "grade": grade,
                "evidence": top_evidence[:6],
            }
        )
    rows.sort(
        key=lambda item: (
            0 if item["grade"] == "A" else 1,
            -int(item["votes"]),
            int(item["slot"], 16),
        )
    )
    return rows


def serialize_rule_result(item: dict[str, Any]) -> dict[str, Any]:
    rule: Rule = item["rule"]
    return {
        "rule": rule.key,
        "min_anchors": rule.min_anchors,
        "min_anchor_ratio": rule.min_anchor_ratio,
        "max_unknown_positions": rule.max_unknown_positions,
        "max_unknown_run": rule.max_unknown_run,
        "require_bilateral": rule.require_bilateral,
        "accepted": item["accepted"],
        "correct": item["correct"],
        "wrong": item["wrong"],
        "precision": round(float(item["precision"]), 6),
        "distinct_rows": item["distinct_rows"],
        "distinct_slots": item["distinct_slots"],
    }


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--map8", type=Path, default=DEFAULT_MAP8)
    parser.add_argument("--corpus", type=Path, action="append", default=[])
    parser.add_argument("--min-precision", type=float, default=1.0)
    parser.add_argument("--min-events", type=int, default=20)
    parser.add_argument("--top-rules", type=int, default=20)
    parser.add_argument("--top-candidates", type=int, default=80)
    args = parser.parse_args(argv)

    corpus_paths = args.corpus or list(DEFAULT_CORPORA)
    for path in (args.rows, args.map8, *corpus_paths):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    fixed = load_map(args.map8)
    rows = load_rows(args.rows)
    corpus = load_corpus(corpus_paths)
    events = calibration_events(rows, corpus, fixed)
    results = evaluate_rules(events, rule_grid())
    selected = select_rule(
        results,
        min_precision=args.min_precision,
        min_events=args.min_events,
    )

    candidate_rows: list[dict[str, Any]] = []
    candidate_stats: dict[str, int] = {}
    selected_serialized: dict[str, Any] | None = None
    if selected is not None:
        selected_serialized = serialize_rule_result(selected)
        votes, evidence, candidate_stats = candidate_votes(
            rows, corpus, fixed, selected["rule"]
        )
        candidate_rows = summarize_candidates(votes, evidence)

    wrong_examples = [
        {
            "record_id": event["record_id"],
            "semantic_category": event["semantic_category"],
            "hidden_slot": f"0x{int(event['hidden_slot']):04X}",
            "expected": event["expected"],
            "predicted": event["predicted"],
            "candidate": event["candidate"],
            "anchors": len(event["anchors"]),
            "length": event["length"],
        }
        for event in events
        if not event["correct"]
    ][:30]

    payload = {
        "schema_version": 1,
        "method": "same-ROM map-script alignment with leave-one-out calibration",
        "inputs": {
            "rows": str(args.rows.relative_to(ROOT)),
            "map8": str(args.map8.relative_to(ROOT)),
            "corpora": [str(path.relative_to(ROOT)) for path in corpus_paths],
        },
        "production_rows": len(rows),
        "verified_8x16_slots": len(fixed),
        "same_rom_corpus_strings": sum(len(values) for values in corpus.values()),
        "same_rom_corpus_lengths": len(corpus),
        "calibration_unique_events": len(events),
        "calibration_correct": sum(bool(event["correct"]) for event in events),
        "calibration_wrong": sum(not bool(event["correct"]) for event in events),
        "safety_floor": {
            "min_precision": args.min_precision,
            "min_events": args.min_events,
        },
        "selected_rule": selected_serialized,
        "top_rules": [
            serialize_rule_result(item)
            for item in results[: args.top_rules]
        ],
        "candidate_stats": candidate_stats,
        "candidate_grade_counts": dict(Counter(row["grade"] for row in candidate_rows)),
        "top_candidates": candidate_rows[: args.top_candidates],
        "calibration_wrong_examples": wrong_examples,
        "notes": [
            "No charmap or ROM bytes are modified by this tool.",
            "A grade requires >=2 agreeing votes, no conflicting vote, and >=2 distinct source texts or slot frames.",
            "Even A candidates remain review candidates until their calibration rule and context are inspected.",
            "Cross-font shape similarity and external corpus votes are intentionally excluded from promotion evidence here.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
