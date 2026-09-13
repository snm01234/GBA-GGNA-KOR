#!/usr/bin/env python3
"""Audit non-scenario text candidates outside the 4,069-row production set.

The production translation sheet is intentionally a closed set of text owners.
This read-only audit looks for additional ROM pointers which land on a valid
Advance token stream but are not in that set.  It deliberately excludes the
known scenario/dynamic banks.  A candidate is evidence for follow-up only; it
is not promoted into the translation sheet without a producer/renderer owner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
DICT_8X16_BASE = 0x000A42A8
DICT_8X16_END = 0x000A4A2C

# These are the already separated scenario/dynamic pools.  Their boundaries
# are file offsets, not CPU addresses.
SCENARIO_EXCLUSIONS = [
    {"name": "scenario_dynamic_pool", "start": 0x001F1A04, "end": 0x001F1E6B},
    {"name": "scenario_main_bank", "start": 0x001F5F20, "end": 0x0021D5B1},
]

# Font/dictionary data can accidentally satisfy the token grammar; it is not
# a text candidate even when a table happens to point into it.
NON_TEXT_DATA_RANGES = [
    (0x00093850, 0x00093FD8, "font_12x12_dictionary"),
    (0x000A42A8, 0x000A4A2C, "font_8x16_dictionary"),
    (0x0008AC40, 0x00093850, "font_12x12_bitmap"),
    (0x00094028, 0x000A42A8, "font_8x16_bitmap"),
]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def in_rom_pointer(value: int, size: int) -> bool:
    return ROM_BASE <= value < ROM_BASE + size


def read_tokens(data: bytes, offset: int, limit: int = 0x400) -> tuple[list[int], bytes] | None:
    """Parse one renderer-valid token stream, returning tokens and raw bytes."""
    if not 0 <= offset < len(data):
        return None
    cur = offset
    tokens: list[int] = []
    while cur - offset < limit:
        lead = data[cur]
        cur += 1
        if lead == 0:
            return tokens, data[offset:cur]
        if lead < 0xE0:
            tokens.append(lead)
            continue
        if cur >= len(data):
            return None
        token = (lead << 8) | data[cur]
        cur += 1
        if not (0xE000 <= token <= 0xE733 or 0xF000 <= token <= 0xF13E):
            return None
        tokens.append(token)
    return None


def load_dictionary(data: bytes) -> list[list[int]]:
    entries: list[list[int]] = []
    for index in range(319):
        rel = struct.unpack_from("<H", data, DICT_8X16_BASE + index * 2)[0]
        target = DICT_8X16_BASE + rel
        parsed = read_tokens(data, target, DICT_8X16_END - target)
        if parsed is None:
            raise SystemExit(f"dictionary parse failed at {target:#x}")
        entries.append(parsed[0])
    return entries


def normalize_slot(token: int) -> int:
    if token <= 0xDF:
        return token
    if 0xE000 <= token <= 0xEFFF:
        return (token + 0x20E0) & 0xFFFF
    raise ValueError(f"not a literal slot: {token:04X}")


def expand_slots(tokens: list[int], dictionary: list[list[int]], depth: int = 0) -> list[int]:
    if depth > 8:
        raise ValueError("dictionary recursion depth exceeded")
    out: list[int] = []
    for token in tokens:
        if 0xF000 <= token < 0xF000 + len(dictionary):
            out.extend(expand_slots(dictionary[token - 0xF000], dictionary, depth + 1))
        else:
            out.append(normalize_slot(token))
    return out


def is_excluded(offset: int) -> str | None:
    for row in SCENARIO_EXCLUSIONS:
        if row["start"] <= offset < row["end"]:
            return row["name"]
    for start, end, name in NON_TEXT_DATA_RANGES:
        if start <= offset < end:
            return name
    return None


def load_known_targets(report_path: Path) -> set[int]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        int(row["target_file_offset"], 16)
        for row in report["records"]
    }


def load_charmap(path: Path) -> dict[int, str]:
    seed = json.loads(path.read_text(encoding="utf-8"))
    return {int(slot, 16): char for slot, char in seed["verified_charmap"].items()}


def decode_slots(slots: list[int], charmap: dict[int, str]) -> str:
    return "".join(charmap.get(slot, f"<{slot:04X}>") for slot in slots)


def collect_pointer_xrefs(data: bytes) -> dict[int, list[int]]:
    """Collect aligned and halfword-aligned literal pointer references.

    Thumb literal pools and data tables are at least halfword aligned.  We keep
    all such xrefs for evidence, then expose the 4-byte-aligned subset separately
    so a candidate is not promoted merely because of an accidental byte window.
    """
    refs: dict[int, list[int]] = defaultdict(list)
    for source in range(0, len(data) - 3, 2):
        value = u32(data, source)
        if in_rom_pointer(value, len(data)):
            refs[value - ROM_BASE].append(source)
    return refs


def region_name(offset: int) -> str:
    if offset < 0x01000000:
        return f"file_0x{offset // 0x10000:04X}xxxx"
    return "file_high"


def candidate_rows(
    data: bytes,
    refs: dict[int, list[int]],
    known: set[int],
    charmap: dict[int, str],
    dictionary: list[list[int]],
) -> tuple[list[dict[str, Any]], Counter[str], Counter[str]]:
    rows: list[dict[str, Any]] = []
    exclusion_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    for offset, sources in refs.items():
        excluded = is_excluded(offset)
        if excluded:
            exclusion_counts[excluded] += 1
            continue
        if offset in known:
            continue
        parsed = read_tokens(data, offset)
        if parsed is None:
            failure_counts["invalid_token_or_unterminated"] += 1
            continue
        tokens, raw = parsed
        if len(tokens) < 2:
            failure_counts["too_short"] += 1
            continue
        try:
            slots = expand_slots(tokens, dictionary)
        except ValueError:
            failure_counts["dictionary_expansion"] += 1
            continue
        if len(slots) < 2:
            failure_counts["too_short_after_dictionary"] += 1
            continue
        aligned = [source for source in sources if source % 4 == 0]
        rows.append(
            {
                "target_file_offset": f"0x{offset:08X}",
                "target_address": f"0x{ROM_BASE + offset:08X}",
                "raw_byte_length": len(raw),
                "token_count": len(tokens),
                "expanded_units": len(slots),
                "unresolved_slots": sorted({f"0x{x:04X}" for x in slots if x not in charmap}),
                "decoded_text_seed": decode_slots(slots, charmap),
                "pointer_xref_count": len(sources),
                "aligned_u32_xref_count": len(aligned),
                "pointer_sources_file": [f"0x{x:08X}" for x in sources[:32]],
                "region": region_name(offset),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    rows.sort(key=lambda row: (-row["aligned_u32_xref_count"], -row["pointer_xref_count"], int(row["target_file_offset"], 16)))
    return rows, exclusion_counts, failure_counts


def cluster_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group nearby candidate streams into storage pools for manual ownership review."""
    ordered = sorted(rows, key=lambda row: int(row["target_file_offset"], 16))
    clusters: list[list[dict[str, Any]]] = []
    for row in ordered:
        offset = int(row["target_file_offset"], 16)
        if not clusters or offset - int(clusters[-1][-1]["target_file_offset"], 16) > 0x100:
            clusters.append([row])
        else:
            clusters[-1].append(row)
    result: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters, 1):
        if len(cluster) == 1 and cluster[0]["aligned_u32_xref_count"] < 2:
            confidence = "low_singleton"
        elif len(cluster) >= 4 and sum(r["aligned_u32_xref_count"] for r in cluster) >= 4:
            confidence = "high_pool_candidate"
        else:
            confidence = "medium_followup"
        result.append(
            {
                "cluster_id": f"NSX-{index:03d}",
                "candidate_count": len(cluster),
                "start_file_offset": cluster[0]["target_file_offset"],
                "end_file_offset": cluster[-1]["target_file_offset"],
                "sum_aligned_u32_xrefs": sum(r["aligned_u32_xref_count"] for r in cluster),
                "confidence": confidence,
                "targets": [r["target_file_offset"] for r in cluster],
                "seed_text_preview": [r["decoded_text_seed"] for r in cluster[:8]],
            }
        )
    result.sort(key=lambda row: (-row["sum_aligned_u32_xrefs"], -row["candidate_count"], row["start_file_offset"]))
    for index, row in enumerate(result, 1):
        row["cluster_rank"] = index
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--report", type=Path, default=Path("legacy/analysis/stage2_translation_sheet_rows_20260827.json"))
    parser.add_argument("--charmap", type=Path, default=Path("font_tables/ggen_advance_japanese_charmap_seed_20260826.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != EXPECTED_SIZE or digest != EXPECTED_SHA256:
        raise SystemExit(f"unexpected ROM: size={len(data)}, sha256={digest}")
    known = load_known_targets(args.report)
    charmap = load_charmap(args.charmap)
    dictionary = load_dictionary(data)
    refs = collect_pointer_xrefs(data)
    rows, exclusion_counts, failure_counts = candidate_rows(data, refs, known, charmap, dictionary)
    clusters = cluster_candidates(rows)
    result = {
        "schema_version": 1,
        "scope": "non-scenario static expansion audit outside 4,069 production records",
        "rom_sha256": digest,
        "production_record_count": len(known),
        "production_target_min": f"0x{min(known):08X}",
        "production_target_max": f"0x{max(known):08X}",
        "scenario_exclusions": [
            {**row, "start_file_offset": f"0x{row['start']:08X}", "end_file_offset_exclusive": f"0x{row['end']:08X}"}
            for row in SCENARIO_EXCLUSIONS
        ],
        "scan_contract": {
            "pointer_scan_alignment": 2,
            "accepted_token_stream": "strict Advance literal/dictionary grammar, NUL terminated within 0x400 bytes",
            "minimum_expanded_units": 2,
            "known_target_policy": "4,069 production targets are suppressed; candidates are follow-up only",
            "font_dictionary_suppression": [name for _start, _end, name in NON_TEXT_DATA_RANGES],
        },
        "pointer_scan": {
            "unique_rom_pointer_targets": len(refs),
            "known_target_suppressed": len([offset for offset in refs if offset in known]),
            "scenario_or_font_suppressed": dict(sorted(exclusion_counts.items())),
            "parse_failures": dict(sorted(failure_counts.items())),
        },
        "candidate_summary": {
            "candidate_targets": len(rows),
            "candidate_clusters": len(clusters),
            "high_pool_candidates": sum(row["confidence"] == "high_pool_candidate" for row in clusters),
            "medium_followup_clusters": sum(row["confidence"] == "medium_followup" for row in clusters),
            "low_singleton_clusters": sum(row["confidence"] == "low_singleton" for row in clusters),
            "candidate_targets_with_aligned_u32_xref": sum(row["aligned_u32_xref_count"] > 0 for row in rows),
            "candidate_targets_with_multiple_aligned_u32_xrefs": sum(row["aligned_u32_xref_count"] >= 2 for row in rows),
        },
        "clusters": clusters,
        "candidates": rows,
        "limitations": [
            "A valid token stream plus a literal pointer is not, by itself, proof of a UI owner.",
            "Scenario banks are excluded by address only; no scenario candidate is promoted.",
            "Rows require a producer/renderer edge review before entering the integrated sheet.",
        ],
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["candidate_summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
