#!/usr/bin/env python3
"""Infer 8x16 slot identities from positional known-plaintext evidence.

Production rows expose their expanded literal slot sequence even when the
current charmap is incomplete.  This helper aligns those sequences with
Japanese strings already present in the project, using a conflict-checked
8x16 seed plus the dictionary-derived supplement as fixed evidence.  It only
emits a slot when the winning character has at least two independent votes
and a strict vote lead; the unified source is never rewritten.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROWS = ROOT / "analysis" / "stage2_translation_sheet_rows_20260827.json"
DEFAULT_SEED = ROOT / "font_tables" / "ggen_advance_japanese_charmap_seed_20260826.json"
DEFAULT_SUPPLEMENT = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260827.json"
DEFAULT_CORPUS = ROOT.parent / "data"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_8x16_corpus_charmap_20260827.json"


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).replace("　", " ").replace("－", "ー").strip()


def walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                yield key
            if isinstance(child, str):
                yield child
            else:
                yield from walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_strings(child)


def japanese_candidate(value: str) -> bool:
    value = normalize(value)
    if not value or "\\n" in value or "⟦" in value or "<" in value or ">" in value:
        return False
    if re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", value):
        return False
    return bool(re.search(r"[ぁ-ゖァ-ヺ一-龯！？。、・ー…「」]", value))


def load_corpus(root: Path) -> dict[int, list[str]]:
    by_length: dict[int, set[str]] = defaultdict(set)
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for raw in walk_strings(payload):
            value = normalize(raw)
            if japanese_candidate(value):
                by_length[len(value)].add(value)
    return {length: sorted(values) for length, values in by_length.items()}


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(slot), 16): str(char) for slot, char in payload.get("verified_charmap", {}).items()}


def source_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        row
        for row in payload.get("records", [])
        if row.get("translation_policy") == "translate"
        and row.get("slots")
        and str(row.get("semantic_category", "")) in {
            "unit_name", "unit_name_alternate", "weapon_name", "character_name",
            "series_title", "stage_location_name", "unit_defense_ability",
            "upgrade_part_name", "stage_battle_condition_component", "stage_code",
        }
    ]


def infer(rows: list[dict[str, Any]], corpus: dict[int, list[str]], fixed: dict[int, str], min_fixed: int) -> tuple[dict[int, str], dict[str, Any]]:
    votes: defaultdict[int, Counter[str]] = defaultdict(Counter)
    evidence: defaultdict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    matched = 0
    ambiguous = 0
    insufficient = 0
    for row in rows:
        slots = [int(str(value), 16) for value in row.get("slots", [])]
        candidates = corpus.get(len(slots), [])
        ranked: list[tuple[int, str]] = []
        for candidate in candidates:
            score = sum(1 for slot, char in zip(slots, candidate) if fixed.get(slot) == char)
            if score >= min_fixed:
                ranked.append((score, candidate))
        if not ranked:
            insufficient += 1
            continue
        ranked.sort(key=lambda item: (-item[0], item[1]))
        top_score = ranked[0][0]
        top = [candidate for score, candidate in ranked if score == top_score]
        if len(top) != 1:
            ambiguous += 1
            continue
        candidate = top[0]
        matched += 1
        for slot, char in zip(slots, candidate):
            if slot in fixed:
                continue
            votes[slot][char] += 1
            key = (slot, char)
            if len(evidence[key]) < 4:
                evidence[key].append({
                    "record_id": row.get("record_id"),
                    "semantic_category": row.get("semantic_category"),
                    "source_text": row.get("source_text", ""),
                    "candidate": candidate,
                    "fixed_score": top_score,
                })

    inferred: dict[int, str] = {}
    slot_votes: dict[str, list[dict[str, Any]]] = {}
    for slot, counter in sorted(votes.items()):
        ranked = [
            {"char": char, "votes": count, "evidence": evidence[(slot, char)]}
            for char, count in counter.most_common()
        ]
        slot_votes[f"0x{slot:04X}"] = ranked[:6]
        if ranked and ranked[0]["votes"] >= 2 and (len(ranked) == 1 or ranked[0]["votes"] > ranked[1]["votes"]):
            inferred[slot] = ranked[0]["char"]
    report = {
        "source_rows": len(rows),
        "corpus_strings": sum(len(values) for values in corpus.values()),
        "matched_unique_candidates": matched,
        "ambiguous_candidates": ambiguous,
        "insufficient_fixed_matches": insufficient,
        "inferred_slot_count": len(inferred),
        "slot_votes": slot_votes,
    }
    return inferred, report


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=Path, default=DEFAULT_ROWS)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--supplement", type=Path, default=DEFAULT_SUPPLEMENT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--min-fixed", type=int, default=3)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    fixed = load_map(args.seed)
    if args.supplement.exists():
        fixed.update(load_map(args.supplement))
    rows = source_rows(args.rows)
    corpus = load_corpus(args.corpus)
    inferred, report = infer(rows, corpus, fixed, args.min_fixed)
    combined = dict(fixed)
    combined.update(inferred)
    payload = {
        "schema_version": 1,
        "font_mode": "8x16",
        "method": "unique positional corpus alignment seeded by 8x16 known plaintext and dictionary-derived slots",
        "base_seed": str(args.seed),
        "supplement": str(args.supplement),
        "verified_charmap": {f"0x{slot:04X}": char for slot, char in sorted(combined.items())},
        "inferred": [
            {"slot": f"0x{slot:04X}", "char": char, "votes": report["slot_votes"][f"0x{slot:04X}"][0]["votes"]}
            for slot, char in sorted(inferred.items())
        ],
        "report": report,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(args.out), **{key: report[key] for key in (
        "source_rows", "corpus_strings", "matched_unique_candidates", "ambiguous_candidates",
        "insufficient_fixed_matches", "inferred_slot_count")}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
