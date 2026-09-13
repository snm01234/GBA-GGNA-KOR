#!/usr/bin/env python3
"""Inventory pending translate rows and split fully-decoded work slices.

Read-only.  Does not write charmap, unified source, or ROM.
Uses merged_20260830 plus live 8x16/12x12 maps.  configuration_option_text
is decoded with 12x12 even when source_scope is production.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import analyze_ggen_advance_pending_decode as decode

ROOT = Path(__file__).resolve().parent.parent
MERGED_DEFAULT = ROOT / "analysis" / "ggen_advance_translation_merged_20260830.json"
OUT_DEFAULT = ROOT / "analysis" / "ggen_advance_pending_translation_work_20260829.json"
SLICES_DEFAULT = ROOT / "analysis" / "ggen_advance_pending_translation_slices_20260829.json"

GARBLE_RE = re.compile(
    r"(ま試作|なで1|ひばな|負参|基闘|パメ|ケ「D|ＯZま|デDメ|"
    r"ストノジ|我ツ|ゴナシ|ばが1|印がし|ョなで|宇宙宙貴|"
    r"ザク官1|武死エ|ムキノジ|戦闘貴1|年だからって|無門をやる|"
    r"<[0-9A-Fa-f]{4}>|EE$|でEE|み$|ま$)"
)


def looks_garbled(jp: str) -> bool:
    text = jp.replace("\n", " / ").strip()
    if not text:
        return False
    if GARBLE_RE.search(text):
        return True
    # leftover private-use / replacement noise
    if "�" in text:
        return True
    kana_noise = sum(1 for ch in text if ch in "まみむめもひばなで1")
    if len(text) >= 8 and kana_noise >= max(3, len(text) // 3):
        return True
    return False


def pick_map(row: dict[str, Any], map12: dict[int, str], map8: dict[int, str]) -> dict[int, str]:
    scope = str(row.get("source_scope", ""))
    category = str(row.get("semantic_category", ""))
    if category == "configuration_option_text":
        return map12
    if scope in decode.SCENARIO_SCOPES:
        return map12
    return map8


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--merged", type=Path, default=MERGED_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--slices", type=Path, default=SLICES_DEFAULT)
    ap.add_argument("--agents", type=int, default=8)
    args = ap.parse_args(argv)

    map12 = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    map8 = decode.merge_maps([decode.DEFAULT_MAP8], apply_kana=False)
    merged = json.loads(args.merged.read_text(encoding="utf-8"))

    unit_members: dict[str, list[str]] = defaultdict(list)
    for row in merged["records"]:
        if row.get("scope_status") == "included" and row.get("translation_policy") == "translate":
            unit_members[str(row.get("translation_unit_id"))].append(row["record_id"])

    pending_by_scope: Counter[str] = Counter()
    pending_by_cat: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    class_by_scope: dict[str, Counter[str]] = defaultdict(Counter)
    work: list[dict[str, Any]] = []
    skip_rows: list[dict[str, Any]] = []

    for row in merged["records"]:
        if row.get("scope_status") != "included":
            continue
        if row.get("translation_policy") != "translate":
            continue
        if row.get("translation_status") == "translated":
            continue
        scope = str(row.get("source_scope", ""))
        category = str(row.get("semantic_category", ""))
        pending_by_scope[scope] += 1
        pending_by_cat[f"{scope}:{category}"] += 1
        charmap = pick_map(row, map12, map8)
        leftover = decode.remaining_slots(row, charmap)
        decoded, marker_missing = decode.decode_text(str(row.get("source_text") or ""), charmap)
        leftover_set = set(leftover) | set(marker_missing)
        text_leftover = sorted(slot for slot in leftover_set if slot not in decode.RESERVED)
        reserved_leftover = sorted(slot for slot in leftover_set if slot in decode.RESERVED)
        jp = decoded.replace("\n", " / ")
        unit_id = str(row.get("translation_unit_id"))
        members = unit_members.get(unit_id, [row["record_id"]])
        item = {
            "record_id": row["record_id"],
            "translation_unit_id": unit_id,
            "unit_size": len(members),
            "scope": scope,
            "semantic_category": category,
            "decoded_jp": jp,
            "remaining_text_slots": [f"0x{slot:04X}" for slot in text_leftover],
            "reserved_slots": [f"0x{slot:04X}" for slot in reserved_leftover],
        }
        if text_leftover:
            kind = "still_partial"
        elif not jp.strip():
            kind = "empty"
        elif looks_garbled(jp):
            kind = "garbled"
        elif len(members) != 1:
            kind = "split_unit"
        else:
            kind = "translatable"
        item["kind"] = kind
        class_counts[kind] += 1
        class_by_scope[scope][kind] += 1
        if kind == "translatable":
            work.append(item)
        else:
            skip_rows.append({"record_id": item["record_id"], "kind": kind, "scope": scope, "category": category})

    unique_jp = sorted({item["decoded_jp"] for item in work})
    by_jp: dict[str, list[str]] = defaultdict(list)
    for item in work:
        by_jp[item["decoded_jp"]].append(item["record_id"])

    n_agents = max(1, int(args.agents))
    slices: dict[str, Any] = {
        "schema_version": 1,
        "merged": str(args.merged.relative_to(ROOT)).replace("\\", "/"),
        "map8_slots": len(map8),
        "map12_slots": len(map12),
        "agent_count": n_agents,
        "translatable_rows": len(work),
        "unique_jp": len(unique_jp),
        "agents": {},
    }
    # Split unique JP round-robin so duplicate rows stay with the same agent.
    buckets: list[list[str]] = [[] for _ in range(n_agents)]
    for index, jp in enumerate(unique_jp):
        buckets[index % n_agents].append(jp)
    for index, jp_list in enumerate(buckets, start=1):
        rows = [item for item in work if item["decoded_jp"] in set(jp_list)]
        agent_id = f"ko_{index:02d}"
        out_path = f"analysis/ggen_advance_translation_overlays/pending_parallel_{agent_id}_20260829.json"
        slices["agents"][agent_id] = {
            "unique_jp": len(jp_list),
            "rows": len(rows),
            "out": out_path,
            "jp_list": jp_list,
            "record_ids": [item["record_id"] for item in rows],
        }

    payload = {
        "schema_version": 1,
        "merged": str(args.merged.relative_to(ROOT)).replace("\\", "/"),
        "pending_canonical": sum(pending_by_scope.values()),
        "pending_by_scope": dict(pending_by_scope),
        "class_counts": dict(class_counts),
        "class_by_scope": {key: dict(value) for key, value in class_by_scope.items()},
        "pending_by_category_top": pending_by_cat.most_common(40),
        "translatable_rows": len(work),
        "unique_jp": len(unique_jp),
        "work": work,
        "notes": [
            "still_partial cannot be translated until remaining 8x16/12x12 slots are identified.",
            "empty/garbled/split_unit stay pending on purpose.",
            "configuration_option_text uses 12x12.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.slices.write_text(json.dumps(slices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "pending_canonical": payload["pending_canonical"],
                "pending_by_scope": payload["pending_by_scope"],
                "class_counts": payload["class_counts"],
                "class_by_scope": payload["class_by_scope"],
                "translatable_rows": len(work),
                "unique_jp": len(unique_jp),
                "agent_unique_jp": [len(spec["jp_list"]) for spec in slices["agents"].values()],
                "out": str(args.out.relative_to(ROOT)),
                "slices": str(args.slices.relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
