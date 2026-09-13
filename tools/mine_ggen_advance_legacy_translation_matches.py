#!/usr/bin/env python3
"""Find exact legacy Japanese->Korean matches for pending unified records.

This is a read-only mining helper.  It deliberately emits only exact source
text matches (plus an optional address match for legacy catalog entries) so
that an old translation is never applied to a different record by fuzzy text.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def add_pair(table: dict[str, list[dict[str, str]]], source: Any, target: Any, path: Path) -> None:
    if not isinstance(source, str) or not source or not isinstance(target, str) or not target:
        return
    table[source].append({"translation_ko": target, "source_file": str(path)})


def collect(value: Any, path: Path, table: dict[str, list[dict[str, str]]]) -> None:
    if isinstance(value, dict):
        entries = value.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    for source_key in ("source_text", "jp", "text"):
                        add_pair(table, entry.get(source_key), entry.get("ko"), path)
        lines = value.get("lines")
        if isinstance(lines, list):
            for entry in lines:
                if isinstance(entry, dict):
                    add_pair(table, entry.get("jp"), entry.get("ko"), path)
        ignored = {
            "description", "_note", "_marker_note", "generated_by",
            "manifest_sha256", "original_rom_sha256", "schema_version",
        }
        for key, target in value.items():
            if key not in ignored:
                add_pair(table, key, target, path)
        for child in value.values():
            if isinstance(child, (dict, list)):
                collect(child, path, table)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                collect(child, path, table)


def norm(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("　", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("analysis/ggen_advance_translation_merged_20260827.json"))
    parser.add_argument("--data-root", type=Path, default=Path(r"D:\monoeye\data"))
    parser.add_argument("--output", type=Path, default=Path("legacy/analysis/ggen_advance_legacy_translation_matches_20260827.json"))
    args = parser.parse_args()

    source = load(args.source)
    pending = [r for r in source["records"] if r.get("translation_status") == "pending"]
    pairs: dict[str, list[dict[str, str]]] = defaultdict(list)
    paths = sorted(set(glob.glob(str(args.data_root / "*.json")) + glob.glob(str(args.data_root / "**" / "*.json"), recursive=True)))
    for raw_path in paths:
        path = Path(raw_path)
        try:
            collect(load(path), path, pairs)
        except (OSError, json.JSONDecodeError):
            continue

    normalized_pairs: dict[str, list[dict[str, str]]] = defaultdict(list)
    for legacy_source, values in pairs.items():
        key = norm(legacy_source)
        if key:
            normalized_pairs[key].extend(values)

    matches: list[dict[str, Any]] = []
    exact_count = 0
    normalized_count = 0
    conflicting = 0
    by_category: Counter[str] = Counter()
    for record in pending:
        source_text = record.get("source_text", "")
        if not source_text:
            continue
        candidates = pairs.get(source_text, [])
        match_kind = "exact"
        if not candidates:
            key = norm(source_text)
            candidates = normalized_pairs.get(key, []) if key else []
            match_kind = "normalized"
        if not candidates:
            continue
        translations = sorted({candidate["translation_ko"] for candidate in candidates})
        if len(translations) != 1:
            conflicting += 1
            continue
        if match_kind == "exact":
            exact_count += 1
        else:
            normalized_count += 1
        by_category[record.get("semantic_category", "")] += 1
        matches.append({
            "record_id": record["record_id"],
            "source_text": source_text,
            "translation_ko": translations[0],
            "match_kind": match_kind,
            "legacy_sources": sorted({candidate["source_file"] for candidate in candidates}),
            "target_file_offset": record.get("target_file_offset", ""),
            "source_scope": record.get("source_scope", ""),
            "semantic_category": record.get("semantic_category", ""),
        })

    result = {
        "schema_version": 1,
        "source_file": str(args.source),
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "legacy_data_root": str(args.data_root),
        "legacy_pair_key_count": len(pairs),
        "pending_record_count": len(pending),
        "exact_match_count": exact_count,
        "normalized_match_count": normalized_count,
        "conflicting_match_record_count": conflicting,
        "matches_by_category": dict(sorted(by_category.items())),
        "matches": matches,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("pending_record_count", "legacy_pair_key_count", "exact_match_count", "normalized_match_count", "conflicting_match_record_count", "matches_by_category")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
