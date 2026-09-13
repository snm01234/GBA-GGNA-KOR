#!/usr/bin/env python3
"""Export the 4,069-record production corpus with the verified Japanese charmap seed.

This advance-local exporter depends only on files under advance/.  Unknown glyph
slots are preserved as <XXXX> placeholders; no character is guessed.  Every row
keeps the complete source/reference provenance from the production manifest and
an empty translation_ko field for later translation work.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_stage2_production_reference_manifest as manifest  # noqa: E402
import ggen_advance_text_codec as codec  # noqa: E402

EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = manifest.ROM_SHA256
ROM_BASE = manifest.ROM_BASE
SEED_PATH = THIS_DIR.parent / "font_tables" / "ggen_advance_japanese_charmap_seed_20260826.json"
RESERVED_SLOTS = {0x07F8, 0x07FB, 0x07FC, 0x07FD, 0x07FE, 0x0813}

TSV_FIELDS = [
    "record_id", "primary_category", "storage_contract", "target_file_offset",
    "original_raw_sha256", "decode_status", "mapped_units", "total_units",
    "mapped_percent", "decoded_text_seed", "unresolved_slots", "reserved_slots",
    "source_types", "source_families", "reference_count", "patchable_reference_count",
    "raw_hex", "tokens", "slots", "translation_ko", "notes",
]


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def load_seed() -> dict[str, Any]:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    check(seed["source"]["rom_sha256"] == EXPECTED_SHA256, "charmap seed ROM hash drift")
    check(not seed["slot_conflicts"], "charmap seed has slot conflicts")
    check(not seed["length_mismatches"], "charmap seed has anchor length mismatches")
    mapping = seed["verified_charmap"]
    check(len(mapping) == 139, f"verified slot count drift: {len(mapping)}")
    check(len(set(mapping.values())) == 137, "verified character count drift")
    return seed


def decode_slots(slots: list[int], mapping: dict[int, str]) -> tuple[str, list[int], list[int], int]:
    text: list[str] = []
    unresolved: list[int] = []
    reserved: list[int] = []
    mapped = 0
    for slot in slots:
        char = mapping.get(slot)
        if char is None:
            text.append(f"<{slot:04X}>")
            unresolved.append(slot)
            if slot in RESERVED_SLOTS:
                reserved.append(slot)
        else:
            text.append(char)
            mapped += 1
    return "".join(text), unresolved, reserved, mapped


def build_export(data: bytes) -> dict[str, Any]:
    source_manifest = manifest.build_manifest(data)
    seed = load_seed()
    mapping = {int(slot, 16): char for slot, char in seed["verified_charmap"].items()}
    dict8 = codec.load_dictionary(data, codec.DICT_8X16_BASE, codec.DICT_8X16_END)
    dict12 = codec.load_dictionary(data, codec.DICT_12X12_BASE, codec.DICT_12X12_END)

    rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    unresolved_frequency: Counter[int] = Counter()
    category_counts: Counter[str] = Counter()
    category_unit_counts: Counter[str] = Counter()
    category_mapped_counts: Counter[str] = Counter()
    total_units = 0
    mapped_units = 0
    token_kind_counts: Counter[str] = Counter()

    for record in source_manifest["records"]:
        target = int(record["target_file_offset"], 16)
        tokens, raw = codec.read_tokens_strict(data, target)
        check(raw.hex(" ").upper() == record["raw_hex"], f"raw drift at 0x{target:08X}")
        check(codec.encode_tokens(tokens) == raw, f"round-trip drift at 0x{target:08X}")

        slots8 = codec.expand_to_slots(tokens, dict8)
        slots12 = codec.expand_to_slots(tokens, dict12)
        check(len(slots8) == len(slots12), f"8x16/12x12 expanded length drift at 0x{target:08X}")

        text, unresolved, reserved, mapped = decode_slots(slots8, mapping)
        status = "complete" if not unresolved else ("partial" if mapped else "unmapped")
        status_counts[status] += 1
        unresolved_frequency.update(unresolved)
        total_units += len(slots8)
        mapped_units += mapped
        category = str(record["primary_category"])
        category_counts[category] += 1
        category_unit_counts[category] += len(slots8)
        category_mapped_counts[category] += mapped
        for token in tokens:
            token_kind_counts[codec.token_kind(token)] += 1

        source_types = sorted({str(ref.get("source_type", "unknown")) for ref in record["references"]})
        source_families = sorted({str(ref.get("family", ref.get("source_type", "unknown"))) for ref in record["references"]})
        patchable_refs = sum(bool(ref.get("patchable_u32")) for ref in record["references"])

        rows.append({
            "record_id": record["record_id"],
            "primary_category": category,
            "storage_contract": record["storage_contract"],
            "target_address": record["target_address"],
            "target_file_offset": record["target_file_offset"],
            "original_raw_sha256": record["original_raw_sha256"],
            "raw_hex": record["raw_hex"],
            "tokens": [codec.token_label(t) for t in tokens],
            "slots": [f"0x{s:04X}" for s in slots8],
            "total_units": len(slots8),
            "mapped_units": mapped,
            "mapped_percent": round(mapped * 100 / len(slots8), 3) if slots8 else 100.0,
            "decode_status": status,
            "decoded_text_seed": text,
            "unresolved_slots": [f"0x{s:04X}" for s in sorted(set(unresolved))],
            "reserved_slots": [f"0x{s:04X}" for s in sorted(set(reserved))],
            "source_types": source_types,
            "source_families": source_families,
            "reference_count": len(record["references"]),
            "patchable_reference_count": patchable_refs,
            "references": record["references"],
            "translation_ko": "",
            "notes": "",
        })

    check(len(rows) == manifest.FINAL_RECORDS, f"Unicode export row drift: {len(rows)}")
    check(len({row["record_id"] for row in rows}) == manifest.FINAL_RECORDS, "Unicode record ID uniqueness drift")

    identity_payload = [
        {
            "record_id": row["record_id"],
            "target_file_offset": row["target_file_offset"],
            "original_raw_sha256": row["original_raw_sha256"],
        }
        for row in rows
    ]
    identity_sha256 = hashlib.sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    check(identity_sha256 == manifest.FINAL_IDENTITY_SHA256, f"Unicode export identity drift: {identity_sha256}")

    fallback_rows = [row for row in rows if row["primary_category"] == manifest.FALLBACK_CATEGORY]
    check(len(fallback_rows) == manifest.FALLBACK_RECORDS, "fallback Unicode row count drift")

    category_coverage = {
        category: {
            "records": category_counts[category],
            "expanded_units": category_unit_counts[category],
            "mapped_units": category_mapped_counts[category],
            "mapped_percent": round(category_mapped_counts[category] * 100 / category_unit_counts[category], 3)
            if category_unit_counts[category] else 100.0,
        }
        for category in sorted(category_counts)
    }

    return {
        "schema_version": 1,
        "source": {
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "charmap": {
            "seed_path": str(SEED_PATH.relative_to(THIS_DIR.parent)),
            "method": seed["method"],
            "anchor_count": seed["anchor_count"],
            "verified_slot_count": seed["verified_slot_count"],
            "verified_character_count": seed["verified_character_count"],
        },
        "summary": {
            "records": len(rows),
            "total_expanded_units": total_units,
            "mapped_units": mapped_units,
            "mapped_unit_percent": round(mapped_units * 100 / total_units, 3),
            "decode_status_counts": dict(status_counts),
            "complete_percent": round(status_counts["complete"] * 100 / len(rows), 3),
            "unresolved_unique_slots": len(unresolved_frequency),
            "record_identity_sha256": identity_sha256,
            "primary_category_counts": dict(category_counts),
            "token_kind_counts": dict(token_kind_counts),
            "fallback_records": len(fallback_rows),
            "fallback_expanded_units": sum(int(row["total_units"]) for row in fallback_rows),
            "fallback_mapped_units": sum(int(row["mapped_units"]) for row in fallback_rows),
            "fallback_complete_records": sum(row["decode_status"] == "complete" for row in fallback_rows),
            "top_unresolved_slots": [
                {"slot": f"0x{slot:04X}", "occurrences": count}
                for slot, count in unresolved_frequency.most_common(100)
            ],
        },
        "category_coverage": category_coverage,
        "records": rows,
    }


def tsv_text(report: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=TSV_FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for row in report["records"]:
        flat = {
            "record_id": row["record_id"],
            "primary_category": row["primary_category"],
            "storage_contract": row["storage_contract"],
            "target_file_offset": row["target_file_offset"],
            "original_raw_sha256": row["original_raw_sha256"],
            "decode_status": row["decode_status"],
            "mapped_units": row["mapped_units"],
            "total_units": row["total_units"],
            "mapped_percent": row["mapped_percent"],
            "decoded_text_seed": row["decoded_text_seed"],
            "unresolved_slots": ",".join(row["unresolved_slots"]),
            "reserved_slots": ",".join(row["reserved_slots"]),
            "source_types": ",".join(row["source_types"]),
            "source_families": ",".join(row["source_families"]),
            "reference_count": row["reference_count"],
            "patchable_reference_count": row["patchable_reference_count"],
            "raw_hex": row["raw_hex"],
            "tokens": " ".join(row["tokens"]),
            "slots": " ".join(row["slots"]),
            "translation_ko": row["translation_ko"],
            "notes": row["notes"],
        }
        writer.writerow(flat)
    return out.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--out-json", type=Path)
    ap.add_argument("--out-tsv", type=Path)
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"ROM size drift: {len(data)}")
    check(digest == EXPECTED_SHA256, f"ROM SHA-256 drift: {digest}")
    report = build_export(data)

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.out_tsv:
        args.out_tsv.parent.mkdir(parents=True, exist_ok=True)
        args.out_tsv.write_text(tsv_text(report), encoding="utf-8")

    visible = {
        "source": report["source"],
        "charmap": report["charmap"],
        "summary": report["summary"],
        "category_coverage": report["category_coverage"],
    } if args.summary_only else report
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
