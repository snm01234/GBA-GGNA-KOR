#!/usr/bin/env python3
"""Infer additional scenario 12x12 glyph identities from project source text.

The immutable unified source intentionally keeps unresolved glyph slots as
markers.  This helper uses Japanese source strings already present in the
project as positional evidence, seeded by the verified atlas map and the
exact-template supplement.  Only a unique best candidate with enough known
slot matches contributes votes; the source snapshot is never rewritten.
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
DEFAULT_SCENARIO = ROOT / "analysis" / "scenario_event_translation_source_20260827.json"
DEFAULT_SEED = ROOT / "analysis" / "scenario_event_12x12_charmap_seed_20260827.json"
DEFAULT_SUPPLEMENT = ROOT / "analysis" / "ggen_advance_12x12_template_charmap_20260827.json"
DEFAULT_CORPUS = ROOT.parent / "data"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_scenario_corpus_charmap_20260827.json"

CORRECTED_LOW_KANA = {
    0x001D: "ぁ", 0x001E: "あ", 0x001F: "い", 0x0020: "う",
    0x0021: "ぇ", 0x0022: "え", 0x0023: "ぉ", 0x0024: "お",
    0x0025: "か", 0x0026: "が", 0x0027: "き", 0x0028: "く",
    0x0029: "け", 0x002A: "げ", 0x002B: "こ", 0x002C: "さ",
    0x002D: "し", 0x002E: "じ", 0x002F: "す", 0x0030: "ず",
    0x0031: "せ", 0x0032: "そ", 0x0033: "ぞ", 0x0034: "た",
    0x0035: "だ", 0x0036: "ち", 0x0037: "っ", 0x0038: "つ",
    0x0039: "て", 0x003A: "で", 0x003B: "と", 0x003C: "ど",
    0x003D: "な", 0x003E: "に", 0x003F: "ぬ", 0x0040: "ね",
    0x0041: "の", 0x0042: "は", 0x0043: "ば", 0x0044: "ひ",
    0x0045: "び", 0x0046: "ふ", 0x0047: "ま", 0x0048: "み",
    0x0049: "む", 0x004A: "め", 0x004B: "も", 0x004C: "ゃ",
    0x004D: "や", 0x004E: "ゅ", 0x004F: "ょ", 0x0050: "よ",
    0x0051: "ら", 0x0052: "り", 0x0053: "る", 0x0054: "れ",
    0x0055: "ろ", 0x0056: "わ", 0x0057: "を", 0x0058: "ん",
}


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).replace("　", " ").replace("－", "ー").strip()


def walk_source_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            # Several reviewed dialogue resources use the Japanese source as
            # the dictionary key rather than storing it under ``jp``.
            if isinstance(key, str):
                yield key
            if key in {"jp", "jp_full", "jp_body", "source_text", "original_text", "before", "current"} and isinstance(child, str):
                yield child
            else:
                yield from walk_source_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_source_strings(child)


def japanese_candidate(value: str) -> bool:
    value = normalize(value)
    if not value or "\\n" in value or "⟦" in value or "<" in value or ">" in value:
        return False
    if re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", value):
        return False
    return bool(re.search(r"[ぁ-ゖァ-ヺ一-龯！？。、・ー…「」]", value))


def load_map(path: Path) -> dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(str(slot), 16): str(char) for slot, char in payload.get("verified_charmap", {}).items()}


def load_scenario_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for section in (payload.get("main", {}), payload.get("dynamic", {})):
        for record in section.get("records", []):
            for segment in record.get("segments", []):
                slots = [int(str(value), 16) for value in segment.get("slots", [])]
                if slots:
                    rows.append({
                        "record_id": record.get("record_id"),
                        "segment_index": segment.get("segment_index"),
                        "slots": slots,
                        "source_text": str(segment.get("source_text", "")),
                    })
    return rows


def build_corpus(path: Path) -> dict[int, list[str]]:
    by_length: dict[int, set[str]] = defaultdict(set)
    for file_path in sorted(path.rglob("*.json")):
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for raw in walk_source_strings(payload):
            value = normalize(raw)
            if japanese_candidate(value):
                by_length[len(value)].add(value)
    return {length: sorted(values) for length, values in by_length.items()}


def infer(
    rows: list[dict[str, Any]],
    corpus: dict[int, list[str]],
    fixed: dict[int, str],
    min_fixed: int,
) -> tuple[dict[int, str], dict[str, Any]]:
    votes: defaultdict[int, Counter[str]] = defaultdict(Counter)
    evidence: defaultdict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    matched = 0
    ambiguous = 0
    insufficient = 0
    for row in rows:
        slots = row["slots"]
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
                    "record_id": row["record_id"],
                    "segment_index": row["segment_index"],
                    "source_text": row["source_text"],
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
        if len(ranked) == 1 or ranked[0]["votes"] > ranked[1]["votes"]:
            if ranked[0]["votes"] >= 2:
                inferred[slot] = ranked[0]["char"]
    report = {
        "rows": len(rows),
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
    parser.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--supplement", type=Path, default=DEFAULT_SUPPLEMENT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--min-fixed", type=int, default=3)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    fixed = load_map(args.seed)
    fixed.update(CORRECTED_LOW_KANA)
    if args.supplement.exists():
        fixed.update(load_map(args.supplement))
    rows = load_scenario_rows(args.scenario)
    corpus = build_corpus(args.corpus)
    inferred, report = infer(rows, corpus, fixed, args.min_fixed)
    combined = dict(fixed)
    combined.update(inferred)
    payload = {
        "schema_version": 1,
        "font_mode": "12x12",
        "method": "unique positional corpus alignment seeded by verified atlas/template mappings",
        "base_seed": str(args.seed),
        "template_supplement": str(args.supplement),
        "verified_charmap": {f"0x{slot:04X}": char for slot, char in sorted(combined.items())},
        "inferred": [
            {"slot": f"0x{slot:04X}", "char": char, "votes": report["slot_votes"][f"0x{slot:04X}"][0]["votes"]}
            for slot, char in sorted(inferred.items())
        ],
        "report": report,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(args.out), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
