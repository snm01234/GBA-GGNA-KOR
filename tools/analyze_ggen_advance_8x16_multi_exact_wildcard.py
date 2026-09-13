#!/usr/bin/env python3
"""Recover multiple unresolved GGA 8x16 slots from trusted exact Japanese strings.

This extends the one-slot global exact-wildcard pass.  A production/UI source
row is decoded with the current verified 8x16 charmap, leaving unresolved slot
markers in place.  Trusted, independently reviewed Japanese corpus strings of
the exact same visible length are then matched against every known character.
Each marker consumes exactly one character and repeated occurrences of the same
slot must resolve to the same character.

Safety is measured with leave-k-out calibration over rows that are otherwise
fully decoded by the current 8x16 map.  Known slot identities are hidden in
sets of 1..3 slots and recovered by the same matcher.  Configuration-option
rows are excluded because renderer tracing proves that family is 12x12.

Read-only: this tool does not modify ROM/charmap/source files.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import analyze_ggen_advance_8x16_global_exact_wildcard as one
import analyze_ggen_advance_8x16_language_rerank as lang

ROOT = Path(__file__).resolve().parent.parent
MARKER_RE = re.compile(r"¤([0-9A-Fa-f]{4})¤")
NON_8X16_CATEGORIES = {"configuration_option_text"}


def iter_rows(merged: dict[str, Any]):
    for row in merged.get("records", []):
        if row.get("translation_policy") != "translate":
            continue
        if row.get("source_scope") not in {"production", "non_scenario_ui"}:
            continue
        if str(row.get("semantic_category", "")) in NON_8X16_CATEGORIES:
            continue
        source = str(row.get("source_text", ""))
        if source:
            yield row, source


def hide_slots(source: str, map8: dict[int, str], hidden: set[int]) -> tuple[str, set[int]]:
    unresolved: set[int] = set()

    def repl(match: re.Match[str]) -> str:
        slot = int(match.group(1), 16)
        if slot in lang.RESERVED:
            return ""
        if slot in hidden or slot not in map8:
            unresolved.add(slot)
            return f"¤{slot:04X}¤"
        return map8[slot]

    return lang.SLOT_RE.sub(repl, source), unresolved


def marker_parts(template: str) -> tuple[list[str], list[int]]:
    literals: list[str] = []
    slots: list[int] = []
    cursor = 0
    for match in MARKER_RE.finditer(template):
        literals.append(template[cursor : match.start()])
        slots.append(int(match.group(1), 16))
        cursor = match.end()
    literals.append(template[cursor:])
    return literals, slots


def match_template(
    template: str,
    by_length: dict[int, list[tuple[str, list[dict[str, str]]]]],
) -> list[dict[str, Any]]:
    literals, marker_slots = marker_parts(template)
    if not marker_slots:
        return []
    visible_len = sum(len(part) for part in literals) + len(marker_slots)
    out: list[dict[str, Any]] = []
    for candidate, sources in by_length.get(visible_len, []):
        cursor = 0
        mapping: dict[int, str] = {}
        ok = True
        for index, literal in enumerate(literals):
            if not candidate.startswith(literal, cursor):
                ok = False
                break
            cursor += len(literal)
            if index >= len(marker_slots):
                continue
            if cursor >= len(candidate):
                ok = False
                break
            slot = marker_slots[index]
            char = candidate[cursor]
            prior = mapping.get(slot)
            if prior is not None and prior != char:
                ok = False
                break
            mapping[slot] = char
            cursor += 1
        if not ok or cursor != len(candidate):
            continue
        out.append({
            "text": candidate,
            "mapping": mapping,
            "sources": sources,
            "best_tier": min(source["tier"] for source in sources),
        })
    return out


def mapping_consensus(matches: list[dict[str, Any]]) -> dict[int, str] | None:
    tier_a = [match for match in matches if match["best_tier"] == "A"]
    if not tier_a:
        return None
    mappings = {
        tuple(sorted((int(slot), str(char)) for slot, char in match["mapping"].items()))
        for match in tier_a
    }
    if len(mappings) != 1:
        return None
    return dict(next(iter(mappings)))


def anchor_stats(template: str) -> dict[str, Any]:
    literals, marker_slots = marker_parts(template)
    known_chars = sum(len(part) for part in literals)
    visible_len = known_chars + len(marker_slots)
    marker_positions: list[int] = []
    cursor = 0
    for index, literal in enumerate(literals[:-1]):
        cursor += len(literal)
        marker_positions.append(cursor)
        cursor += 1
    bilateral = all(0 < pos < visible_len - 1 for pos in marker_positions)
    return {
        "visible_len": visible_len,
        "known_chars": known_chars,
        "known_ratio": known_chars / max(1, visible_len),
        "marker_occurrences": len(marker_slots),
        "distinct_slots": len(set(marker_slots)),
        "bilateral": bilateral,
    }


def known_placeholder_slots(source: str, map8: dict[int, str]) -> list[int]:
    slots: list[int] = []
    seen: set[int] = set()
    for match in lang.SLOT_RE.finditer(source):
        slot = int(match.group(1), 16)
        if slot in map8 and slot not in lang.RESERVED and slot not in seen:
            seen.add(slot)
            slots.append(slot)
    return slots


def calibrate(
    merged: dict[str, Any],
    map8: dict[int, str],
    by_length: dict[int, list[tuple[str, list[dict[str, str]]]]],
    *,
    max_k: int,
    max_events_per_k: int,
) -> dict[int, list[dict[str, Any]]]:
    events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row, source in iter_rows(merged):
        # Calibration rows must be fully decoded before hiding known slots.
        _decoded, unresolved_now = hide_slots(source, map8, set())
        unresolved_now = {slot for slot in unresolved_now if slot not in lang.RESERVED}
        if unresolved_now:
            continue
        known_slots = known_placeholder_slots(source, map8)
        if not known_slots:
            continue
        for k in range(1, min(max_k, len(known_slots)) + 1):
            if len(events[k]) >= max_events_per_k:
                continue
            # Deterministic sparse sampling avoids combinatorial explosion.
            combos = itertools.combinations(known_slots, k)
            for hidden_tuple in combos:
                hidden = set(hidden_tuple)
                template, unresolved = hide_slots(source, map8, hidden)
                if unresolved != hidden:
                    continue
                stats = anchor_stats(template)
                if stats["known_chars"] < 2:
                    continue
                matches = match_template(template, by_length)
                consensus = mapping_consensus(matches)
                if consensus is None or set(consensus) != hidden:
                    continue
                correct = all(consensus[slot] == map8[slot] for slot in hidden)
                events[k].append({
                    "record_id": row.get("record_id"),
                    "semantic_category": row.get("semantic_category"),
                    "hidden": {f"0x{slot:04X}": map8[slot] for slot in sorted(hidden)},
                    "predicted": {f"0x{slot:04X}": consensus[slot] for slot in sorted(hidden)},
                    "correct": correct,
                    "stats": stats,
                    "match_count": len(matches),
                    "match_texts": [match["text"] for match in matches[:4]],
                })
                if len(events[k]) >= max_events_per_k:
                    break
    return events


def gate_calibration(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find conservative exact-match gates, sorted by 100%-precision coverage."""
    rows: list[dict[str, Any]] = []
    for min_known in (3, 4, 5, 6, 8, 10):
        for min_ratio in (0.40, 0.50, 0.60, 0.70, 0.80):
            for bilateral in (False, True):
                accepted = [
                    event for event in events
                    if event["stats"]["known_chars"] >= min_known
                    and event["stats"]["known_ratio"] >= min_ratio
                    and (not bilateral or event["stats"]["bilateral"])
                ]
                if not accepted:
                    continue
                correct = sum(bool(event["correct"]) for event in accepted)
                rows.append({
                    "min_known_chars": min_known,
                    "min_known_ratio": min_ratio,
                    "require_bilateral": bilateral,
                    "events": len(accepted),
                    "correct": correct,
                    "wrong": len(accepted) - correct,
                    "precision": correct / len(accepted),
                })
    rows.sort(key=lambda row: (-row["precision"], -row["events"], row["min_known_chars"], row["min_known_ratio"], row["require_bilateral"]))
    return rows


def select_gate(gates: list[dict[str, Any]], min_events: int) -> dict[str, Any] | None:
    safe = [row for row in gates if row["wrong"] == 0 and row["events"] >= min_events]
    if not safe:
        return None
    safe.sort(key=lambda row: (-row["events"], row["min_known_chars"], row["min_known_ratio"], row["require_bilateral"]))
    return safe[0]


def gate_accepts(stats: dict[str, Any], gate: dict[str, Any]) -> bool:
    return (
        stats["known_chars"] >= gate["min_known_chars"]
        and stats["known_ratio"] >= gate["min_known_ratio"]
        and (not gate["require_bilateral"] or stats["bilateral"])
    )


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map8", type=Path, default=lang.MAP8_DEFAULT)
    ap.add_argument("--merged", type=Path, default=lang.MERGED_DEFAULT)
    ap.add_argument("--max-k", type=int, default=3)
    ap.add_argument("--max-calibration-events", type=int, default=500)
    ap.add_argument("--min-safe-events", type=int, default=20)
    ap.add_argument("--max-real-unresolved", type=int, default=4)
    ap.add_argument("--top", type=int, default=200)
    args = ap.parse_args(argv)
    for path in (args.map8, args.merged):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    map8 = lang.load_map(args.map8)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    by_length, corpus_count = one.build_corpus()

    calibration = calibrate(
        merged, map8, by_length,
        max_k=args.max_k,
        max_events_per_k=args.max_calibration_events,
    )
    gate_by_k: dict[int, dict[str, Any] | None] = {}
    calibration_out: dict[str, Any] = {}
    for k in range(1, args.max_k + 1):
        events = calibration.get(k, [])
        gates = gate_calibration(events)
        selected = select_gate(gates, args.min_safe_events)
        gate_by_k[k] = selected
        calibration_out[str(k)] = {
            "events": len(events),
            "correct": sum(bool(event["correct"]) for event in events),
            "wrong": sum(not bool(event["correct"]) for event in events),
            "selected_gate": selected,
            "top_gates": gates[:12],
            "wrong_examples": [event for event in events if not event["correct"]][:12],
        }

    votes: dict[int, Counter[str]] = defaultdict(Counter)
    evidence: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    accepted_rows = 0
    rejected = Counter()
    for row, source in iter_rows(merged):
        if row.get("translation_status") != "pending":
            continue
        template, unresolved = hide_slots(source, map8, set())
        unresolved = {slot for slot in unresolved if slot not in lang.RESERVED and slot not in lang.QUARANTINE}
        k = len(unresolved)
        if k < 1 or k > args.max_real_unresolved:
            continue
        gate = gate_by_k.get(k)
        if gate is None:
            rejected[f"no_safe_gate_k{k}"] += 1
            continue
        stats = anchor_stats(template)
        if not gate_accepts(stats, gate):
            rejected["gate_rejected"] += 1
            continue
        matches = match_template(template, by_length)
        consensus = mapping_consensus(matches)
        if consensus is None or set(consensus) != unresolved:
            rejected["no_unique_consensus"] += 1
            continue
        accepted_rows += 1
        for slot, char in consensus.items():
            votes[slot][char] += 1
            key = (slot, char)
            if len(evidence[key]) < 8:
                evidence[key].append({
                    "record_id": row.get("record_id"),
                    "semantic_category": row.get("semantic_category"),
                    "template": template,
                    "resolved_text": next((m["text"] for m in matches if m["best_tier"] == "A" and m["mapping"] == consensus), ""),
                    "k": k,
                    "stats": stats,
                    "sources": [src for m in matches if m["best_tier"] == "A" and m["mapping"] == consensus for src in m["sources"]][:6],
                })

    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for slot, counter in votes.items():
        if len(counter) != 1:
            conflicts.append({
                "slot": f"0x{slot:04X}",
                "votes": dict(counter),
            })
            continue
        char, count = next(iter(counter.items()))
        ev = evidence[(slot, char)]
        candidates.append({
            "slot": f"0x{slot:04X}",
            "char": char,
            "vote_rows": count,
            "distinct_categories": sorted({str(row["semantic_category"]) for row in ev}),
            "evidence": ev,
        })
    candidates.sort(key=lambda row: (-row["vote_rows"], int(row["slot"], 16)))

    payload = {
        "schema_version": 1,
        "method": "trusted exact multi-slot wildcard with leave-k-out calibration",
        "verified_8x16_slots": len(map8),
        "trusted_corpus_strings": corpus_count,
        "excluded_non_8x16_categories": sorted(NON_8X16_CATEGORIES),
        "calibration": calibration_out,
        "accepted_real_rows": accepted_rows,
        "candidate_count": len(candidates),
        "candidate_vote_coverage": sum(row["vote_rows"] for row in candidates),
        "conflict_count": len(conflicts),
        "rejected": dict(rejected),
        "candidates": candidates[: args.top],
        "conflicts": conflicts[:50],
        "notes": [
            "Only Tier-A corpus matches contribute to consensus.",
            "Repeated occurrences of one slot must map to the same character.",
            "configuration_option_text is excluded because it is renderer-proven 12x12.",
            "No charmap/source/ROM writes are performed.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
