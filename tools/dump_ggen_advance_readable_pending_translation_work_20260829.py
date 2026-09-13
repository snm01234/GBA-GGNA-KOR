#!/usr/bin/env python3
"""Build parallel translation agent inputs from actually readable pending JP.

configuration_option_text is re-decoded via 12x12 dictionary expansion + the
current 12x12 map (sheet source_text is an unexpanded token dump).  Map-script
leftover uses the existing 12x12 decode.  Garbled/empty/partial stay out.
Does not write charmap, unified source, or ROM.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import analyze_ggen_advance_pending_decode as decode
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens_strict,
)

ROOT = Path(__file__).resolve().parent.parent
MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260830.json"
ROM = ROOT / "SD Gundam GGeneration Advance (Japan).gba"
WORK_DIR = ROOT / "analysis" / "ggen_advance_pending_translation_agent_inputs_20260829"
SLICES = ROOT / "analysis" / "ggen_advance_pending_translation_slices_readable_20260829.json"
N_AGENTS = 8

GARBLE_RE = re.compile(
    r"(ま試作|なで1|ぬがィ|ねある1|イていィ|でXも|ポDド|ジジル|"
    r"本機エ指す|たど1|ゅァ|ァない|<[0-9A-Fa-f]{4}>|�)"
)


def looks_garbled(jp: str) -> bool:
    text = jp.replace("\n", " ").strip()
    if not text:
        return False
    if GARBLE_RE.search(text):
        return True
    if text.count("エ") >= 2 and "エネルギー" not in text:
        return True
    return False


def decode_expanded(raw_hex: str, dictionary: list[list[int]], charmap: dict[int, str]) -> tuple[str, list[int]]:
    raw = bytes(int(part, 16) for part in raw_hex.split() if part)
    tokens, _stored = read_tokens_strict(raw if raw.endswith(b"\x00") else raw + b"\x00", 0)
    slots = expand_to_slots(tokens, dictionary)
    missing: list[int] = []
    chars: list[str] = []
    seen: set[int] = set()
    for slot in slots:
        if slot in decode.RESERVED:
            if slot not in seen:
                missing.append(slot)
                seen.add(slot)
            chars.append(f"<{slot:04X}>")
            continue
        char = charmap.get(slot)
        if char is None:
            if slot not in seen:
                missing.append(slot)
                seen.add(slot)
            chars.append(f"<{slot:04X}>")
        else:
            chars.append(char)
    text_missing = [slot for slot in missing if slot not in decode.RESERVED]
    return "".join(chars), text_missing


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    map12 = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    rom = ROM.read_bytes()
    dictionary = load_dictionary(rom, DICT_12X12_BASE, DICT_12X12_END)
    merged = json.loads(MERGED.read_text(encoding="utf-8"))

    unit_members: dict[str, list[str]] = defaultdict(list)
    for row in merged["records"]:
        if row.get("scope_status") == "included" and row.get("translation_policy") == "translate":
            unit_members[str(row.get("translation_unit_id"))].append(row["record_id"])

    work: list[dict[str, Any]] = []
    skipped = Counter()
    for row in merged["records"]:
        if row.get("scope_status") != "included":
            continue
        if row.get("translation_policy") != "translate":
            continue
        if row.get("translation_status") == "translated":
            continue
        scope = str(row.get("source_scope", ""))
        category = str(row.get("semantic_category", ""))
        unit_id = str(row.get("translation_unit_id"))
        members = unit_members.get(unit_id, [row["record_id"]])
        if len(members) != 1:
            skipped["split_unit"] += 1
            continue
        if category == "configuration_option_text":
            try:
                jp, missing = decode_expanded(str(row.get("raw_hex") or ""), dictionary, map12)
            except (ValueError, IndexError):
                skipped["expand_fail"] += 1
                continue
            kind = "config_expanded"
        elif scope == "scenario_map_script":
            leftover = decode.remaining_slots(row, map12)
            jp, marker_missing = decode.decode_text(str(row.get("source_text") or ""), map12)
            missing = [slot for slot in set(leftover) | set(marker_missing) if slot not in decode.RESERVED]
            kind = "map_script"
        else:
            skipped["out_of_scope_partial_or_garbled"] += 1
            continue
        jp_norm = jp.replace("\r\n", "\n")
        if missing:
            skipped["still_partial"] += 1
            continue
        if not jp_norm.strip():
            skipped["empty"] += 1
            continue
        if looks_garbled(jp_norm):
            skipped["garbled"] += 1
            continue
        work.append(
            {
                "record_id": row["record_id"],
                "translation_unit_id": unit_id,
                "scope": scope,
                "semantic_category": category,
                "kind": kind,
                "decoded_jp": jp_norm,
            }
        )

    unique_jp = sorted({item["decoded_jp"] for item in work})
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    buckets: list[list[str]] = [[] for _ in range(N_AGENTS)]
    for index, jp in enumerate(unique_jp):
        buckets[index % N_AGENTS].append(jp)

    slices: dict[str, Any] = {
        "schema_version": 1,
        "merged": "analysis/ggen_advance_translation_merged_20260830.json",
        "agent_count": N_AGENTS,
        "translatable_rows": len(work),
        "unique_jp": len(unique_jp),
        "skipped": dict(skipped),
        "by_kind": dict(Counter(item["kind"] for item in work)),
        "agents": {},
    }
    for index, jp_list in enumerate(buckets, start=1):
        agent_id = f"ko_{index:02d}"
        rows = [item for item in work if item["decoded_jp"] in set(jp_list)]
        payload = {
            "schema_version": 1,
            "agent": agent_id,
            "unique_jp": len(jp_list),
            "rows": rows,
            "jp_to_record_ids": {
                jp: [item["record_id"] for item in rows if item["decoded_jp"] == jp] for jp in jp_list
            },
        }
        out = WORK_DIR / f"{agent_id}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        overlay = (
            ROOT
            / "analysis"
            / "ggen_advance_translation_overlays"
            / f"pending_parallel_{agent_id}_20260829.json"
        )
        slices["agents"][agent_id] = {
            "input": str(out.relative_to(ROOT)).replace("\\", "/"),
            "out": str(overlay.relative_to(ROOT)).replace("\\", "/"),
            "unique_jp": len(jp_list),
            "rows": len(rows),
        }

    SLICES.write_text(json.dumps(slices, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    samples = []
    for kind in ("config_expanded", "map_script"):
        for item in work:
            if item["kind"] == kind:
                samples.append({"kind": kind, "jp": item["decoded_jp"][:120]})
                if sum(1 for s in samples if s["kind"] == kind) >= 3:
                    break
    print(
        json.dumps(
            {
                "translatable_rows": len(work),
                "unique_jp": len(unique_jp),
                "skipped": dict(skipped),
                "by_kind": slices["by_kind"],
                "agent_unique_jp": [spec["unique_jp"] for spec in slices["agents"].values()],
                "samples": samples,
                "slices": str(SLICES.relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
