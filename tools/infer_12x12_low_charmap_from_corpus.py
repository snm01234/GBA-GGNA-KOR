#!/usr/bin/env python3
"""Infer 12x12 low-kana slots from any matching Japanese project corpus.

The GBA scenario bank uses a compact 12x12 atlas whose low-kana order is not
the same as the production 8x16 table.  This read-only helper aligns the
scenario slot sequences with Japanese source strings already present in the
project data, using only punctuation, katakana, ASCII, and known-kanji anchors
as hard evidence.  It reports votes; it never edits a seed or translation.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SCENARIO = Path("legacy/analysis/scenario_event_translation_source_20260827.json")
DEFAULT_SEED = Path("legacy/analysis/scenario_event_12x12_charmap_seed_20260827.json")
DEFAULT_CORPUS = Path("../data")
LOW_START = 0x1D
LOW_END = 0x59


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("　", " ").replace("－", "ー").replace("…", "…")
    return value.strip()


def japanese_like(value: str) -> bool:
    return bool(re.search(r"[ぁ-ゖァ-ヺ一-龯！？。、・ー…「」]", value))


def iter_strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(child, str) and key in {
                "jp", "jp_full", "jp_body", "source_text", "original_text", "before", "current",
            }:
                text = normalize(child)
                if japanese_like(text):
                    yield text, child_path
            else:
                yield from iter_strings(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{index}]")


def load_corpus(root: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for text, location in iter_strings(payload, path.name):
            found.append((text, location))
    # Preserve duplicate text locations as useful confidence evidence but only
    # align each exact string once per scenario record below.
    return found


def source_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for section in (payload.get("main", {}), payload.get("dynamic", {})):
        for record in section.get("records", []):
            for segment in record.get("segments", []):
                slots = segment.get("slots", [])
                if slots:
                    rows.append({
                        "record_id": record.get("record_id"),
                        "segment_index": segment.get("segment_index"),
                        "slots": [int(str(slot), 16) for slot in slots],
                        "source_text": str(segment.get("source_text", "")),
                    })
    return rows


def load_fixed(seed_path: Path) -> dict[int, str]:
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    mapping = {
        int(str(slot), 16): str(char)
        for slot, char in payload.get("verified_charmap", {}).items()
    }
    # Low kana in the seed is the current hypothesis under test.  Excluding it
    # prevents circular votes from the hypothesis itself.
    return {slot: char for slot, char in mapping.items() if not LOW_START <= slot < LOW_END}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-fixed", type=int, default=2)
    args = parser.parse_args()

    fixed = load_fixed(args.seed)
    corpus = load_corpus(args.corpus)
    by_length: defaultdict[int, list[tuple[str, str]]] = defaultdict(list)
    for text, location in corpus:
        by_length[len(text)].append((text, location))

    votes: Counter[tuple[int, str]] = Counter()
    evidence: defaultdict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    matched_records = 0
    candidate_rows = 0
    rows = source_records(args.scenario)
    if args.limit > 0:
        rows = rows[:args.limit]
    for row in rows:
        slots = row["slots"]
        source_text = normalize(row["source_text"])
        # A control segment can include a literal backslash-n only at the main
        # stream level; individual segments are plain text here.
        candidates = by_length.get(len(slots), [])
        ranked: list[tuple[int, str, str]] = []
        for candidate, location in candidates:
            if any(char in candidate for char in "\\n⟦DYNAMIC⟧"):
                continue
            fixed_matches = sum(
                1 for slot, char in zip(slots, candidate)
                if slot in fixed and fixed[slot] == char
            )
            if fixed_matches >= args.min_fixed:
                ranked.append((fixed_matches, candidate, location))
        if not ranked:
            continue
        ranked.sort(reverse=True)
        top_score = ranked[0][0]
        top = [item for item in ranked if item[0] == top_score]
        # Only use unique top strings; repeated locations are not independent
        # evidence and can otherwise dominate common one-line phrases.
        unique_top: dict[str, str] = {candidate: location for _score, candidate, location in top}
        if not unique_top:
            continue
        matched_records += 1
        candidate_rows += len(unique_top)
        for candidate, location in unique_top.items():
            for slot, char in zip(slots, candidate):
                if LOW_START <= slot < LOW_END:
                    votes[(slot, char)] += 1
                    if len(evidence[(slot, char)]) < 6:
                        evidence[(slot, char)].append({
                            "record_id": row["record_id"],
                            "source_text": source_text,
                            "candidate": candidate,
                            "location": location,
                            "fixed_score": top_score,
                        })

    slot_votes: dict[str, list[dict[str, Any]]] = {}
    for slot in range(LOW_START, LOW_END):
        ranked = sorted(
            (
                {"char": char, "votes": count, "evidence": evidence[(slot, char)]}
                for (voted_slot, char), count in votes.items()
                if voted_slot == slot
            ),
            key=lambda item: (-item["votes"], item["char"]),
        )
        if ranked:
            slot_votes[f"0x{slot:04X}"] = ranked[:8]
    result = {
        "result": "PASS",
        "corpus_strings": len(corpus),
        "scenario_segments": len(rows),
        "matched_segments": matched_records,
        "top_candidate_rows": candidate_rows,
        "slot_votes": slot_votes,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
