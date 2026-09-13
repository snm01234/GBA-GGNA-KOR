#!/usr/bin/env python3
"""Recover GGA 8x16 slots by exact one-character wildcard matches.

The project contains many independently reviewed Japanese strings in map-script,
scenario and curated production artifacts.  This analyzer builds a trusted
cross-artifact corpus, decodes current production/UI rows with the verified
8x16 charmap, and asks whether a single unresolved slot can be filled by an
otherwise exact corpus string.

The method is calibrated with leave-one-out over already verified 8x16 slots.
No ROM/charmap/source files are modified.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import analyze_ggen_advance_8x16_language_rerank as lang

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS = ROOT / "analysis"
JP_RE = re.compile(r"[ぁ-んァ-ヶ一-龯々ー・]")
SLOT_RE = re.compile(r"<[0-9A-Fa-f]{4}>")


def source_tier(path: Path) -> str | None:
    name = path.name.lower()
    if (
        ("map_script" in name and ("translation_source" in name or "dialogue_ko" in name))
        or ("scenario" in name and (
            "closed_strings" in name
            or "dialogue_ko" in name
            or "slot_promotions" in name
            or "translation_source" in name
        ))
        or name == "_tmp_ko_production.json"
        or "fully_decoded_production" in name
    ):
        return "A"
    if name.startswith("_tmp_ko_scn_"):
        return "B"
    return None


def walk_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                out.append(key)
            out.extend(walk_strings(child))
    elif isinstance(value, list):
        for child in value:
            out.extend(walk_strings(child))
    return out


def clean_string(text: str) -> str | None:
    text = text.strip()
    if not text or len(text) > 120:
        return None
    if not JP_RE.search(text) or SLOT_RE.search(text) or chr(0xFFFD) in text:
        return None
    return text


def build_corpus() -> tuple[dict[int, list[tuple[str, list[dict[str, str]]]]], int]:
    origins: dict[str, list[dict[str, str]]] = defaultdict(list)
    for dirpath, _dirs, filenames in os.walk(ANALYSIS):
        for filename in filenames:
            if not filename.endswith(".json"):
                continue
            path = Path(dirpath) / filename
            tier = source_tier(path)
            if tier is None:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            for raw in walk_strings(payload):
                text = clean_string(raw)
                if text is None:
                    continue
                item = {"path": str(path.relative_to(ROOT)), "tier": tier}
                if item not in origins[text]:
                    origins[text].append(item)
    by_length: dict[int, list[tuple[str, list[dict[str, str]]]]] = defaultdict(list)
    for text, source_rows in origins.items():
        by_length[len(text)].append((text, source_rows))
    return dict(by_length), len(origins)


def wildcard_matches(
    template: str,
    slot: int,
    by_length: dict[int, list[tuple[str, list[dict[str, str]]]]],
) -> list[dict[str, Any]]:
    marker = f"¤{slot:04X}¤"
    occurrences = template.count(marker)
    if occurrences < 1:
        return []
    target_length = len(template) - len(marker) * occurrences + occurrences
    parts = template.split(marker)
    out = []
    for candidate, sources in by_length.get(target_length, []):
        cursor = 0
        chars: list[str] = []
        ok = True
        for index, part in enumerate(parts):
            if not candidate.startswith(part, cursor):
                ok = False
                break
            cursor += len(part)
            if index < len(parts) - 1:
                if cursor >= len(candidate):
                    ok = False
                    break
                chars.append(candidate[cursor])
                cursor += 1
        if not ok or cursor != len(candidate) or not chars or len(set(chars)) != 1:
            continue
        out.append({
            "char": chars[0],
            "text": candidate,
            "sources": sources,
            "best_tier": min(source["tier"] for source in sources),
        })
    return out


def iter_rows(merged: dict[str, Any]):
    for row in merged.get("records", []):
        if row.get("translation_policy") != "translate":
            continue
        if row.get("source_scope") not in {"production", "non_scenario_ui"}:
            continue
        if row.get("semantic_category") == "configuration_option_text":
            continue
        source = str(row.get("source_text", ""))
        if source:
            yield row, source


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map8", type=Path, default=lang.MAP8_DEFAULT)
    ap.add_argument("--merged", type=Path, default=lang.MERGED_DEFAULT)
    ap.add_argument("--top", type=int, default=200)
    args = ap.parse_args(argv)
    for path in (args.map8, args.merged):
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            raise SystemExit(f"refused path outside advance workspace: {path}")

    map8 = lang.load_map(args.map8)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    by_length, corpus_count = build_corpus()

    # Leave-one-out calibration.  Require all exact wildcard matches for a row
    # to agree on one character, and at least one Tier-A source.
    calibration = []
    for slot, expected in sorted(map8.items()):
        if len(expected) != 1:
            continue
        for row, source in iter_rows(merged):
            if f"<{slot:04X}>" not in source:
                continue
            template, unresolved = lang.decode_template(source, map8, hidden_slot=slot)
            unresolved = {value for value in unresolved if value not in lang.RESERVED}
            if unresolved != {slot}:
                continue
            matches = wildcard_matches(template, slot, by_length)
            chars = {match["char"] for match in matches}
            if len(chars) != 1 or not any(match["best_tier"] == "A" for match in matches):
                continue
            predicted = next(iter(chars))
            calibration.append({
                "slot": f"0x{slot:04X}",
                "expected": expected,
                "predicted": predicted,
                "correct": predicted == expected,
                "record_id": row.get("record_id"),
                "semantic_category": row.get("semantic_category"),
                "match_count": len(matches),
                "matches": matches[:4],
            })
            break

    # Real unresolved single-slot rows.
    votes: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row, source in iter_rows(merged):
        if row.get("translation_status") != "pending":
            continue
        template, unresolved = lang.decode_template(source, map8)
        unresolved = {value for value in unresolved if value not in lang.RESERVED}
        if len(unresolved) != 1:
            continue
        slot = next(iter(unresolved))
        if slot in lang.QUARANTINE:
            continue
        matches = wildcard_matches(template, slot, by_length)
        chars = {match["char"] for match in matches}
        if len(chars) != 1:
            continue
        char = next(iter(chars))
        best_tier = min((match["best_tier"] for match in matches), default="Z")
        votes[slot].append({
            "char": char,
            "record_id": row.get("record_id"),
            "semantic_category": row.get("semantic_category"),
            "template": template,
            "best_tier": best_tier,
            "matches": matches[:5],
        })

    candidates = []
    for slot, rows in votes.items():
        chars = {row["char"] for row in rows}
        if len(chars) != 1:
            continue
        char = next(iter(chars))
        tier_a_rows = sum(row["best_tier"] == "A" for row in rows)
        candidates.append({
            "slot": f"0x{slot:04X}",
            "char": char,
            "row_count": len(rows),
            "tier_a_rows": tier_a_rows,
            "promotion_gate": tier_a_rows > 0,
            "evidence": rows[:8],
        })
    candidates.sort(key=lambda row: (-row["tier_a_rows"], -row["row_count"], int(row["slot"], 16)))

    correct = sum(row["correct"] for row in calibration)
    payload = {
        "schema_version": 1,
        "method": "trusted cross-artifact exact one-character wildcard",
        "verified_8x16_slots": len(map8),
        "trusted_corpus_unique_strings": corpus_count,
        "calibration": {
            "events": len(calibration),
            "correct": correct,
            "wrong": len(calibration) - correct,
            "precision": round(correct / len(calibration), 6) if calibration else 0.0,
            "wrong_examples": [row for row in calibration if not row["correct"]][:20],
        },
        "candidate_count": len(candidates),
        "promotion_gate_count": sum(row["promotion_gate"] for row in candidates),
        "candidates": candidates[: args.top],
        "notes": [
            "Tier A: reviewed map-script/scenario sources and curated production corpus.",
            "Tier B: older _tmp_ko_scn_* artifacts; Tier-B-only candidates are held.",
            "Read-only: no charmap/source/ROM writes.",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
