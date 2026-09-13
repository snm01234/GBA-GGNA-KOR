#!/usr/bin/env python3
"""Audit target identity overlap among advance-local text-family closures.

This prevents semantic review counts from being inflated when one text target has
multiple producer/reference paths.  It reads only files under advance/ plus the
clean ROM and never modifies the ROM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from itertools import combinations
from pathlib import Path

ROM_BASE = 0x08000000
EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rom", type=Path)
    parser.add_argument("--analysis-dir", type=Path, default=Path("analysis"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == EXPECTED_SIZE, f"unexpected ROM size {len(data)}")
    check(digest == EXPECTED_SHA256, f"unexpected ROM SHA-256 {digest}")

    pc = load_json(args.analysis_dir / "direct_pc_literal_static_summary_20260826.json")
    indirect = load_json(args.analysis_dir / "indirect_text_owners_20260826.json")

    families: dict[str, set[int]] = {
        "table_1C92E8": {u32(data, 0x001C92E8 + 4 * i) for i in range(114)},
        "direct_struct8_text": {u32(data, 0x001C94B4 + 8 * i) for i in range(70)},
        "table_FCE2D8_flat69_paired_selection": {u32(data, 0x00FCE2D8 + 4 * i) for i in range(69)},
        "direct_pc_literal": {int(row["text_pointer_address"], 16) for row in pc["targets"]},
        "indirect_owner_trio": {
            int(entry["target_address"], 16)
            for owner in indirect["owners"].values()
            for entry in owner["entries"]
            if entry.get("target_address")
        },
    }

    expected_sizes = {
        "table_1C92E8": 114,
        "direct_struct8_text": 70,
        "table_FCE2D8_flat69_paired_selection": 68,
        "direct_pc_literal": 67,
        "indirect_owner_trio": 39,
    }
    actual_sizes = {name: len(targets) for name, targets in families.items()}
    check(actual_sizes == expected_sizes, f"family size drift: {actual_sizes}")

    overlaps = []
    for left, right in combinations(families, 2):
        common = sorted(families[left] & families[right])
        if common:
            overlaps.append(
                {
                    "left": left,
                    "right": right,
                    "count": len(common),
                    "targets": [f"0x{x:08X}" for x in common],
                }
            )

    core_partial_intersection = families["table_FCE2D8_flat69_paired_selection"] & families["direct_pc_literal"]
    check(not core_partial_intersection, "current 68+67 partial checkpoint now overlaps")

    indirect_vs_pc = families["indirect_owner_trio"] & families["direct_pc_literal"]
    check(
        indirect_vs_pc == {0x081BE8C4, 0x081BEB58},
        f"indirect/direct_pc overlap drift: {[hex(x) for x in sorted(indirect_vs_pc)]}",
    )

    union_all = set().union(*families.values())
    union_without_indirect = set().union(
        families["table_1C92E8"],
        families["direct_struct8_text"],
        families["table_FCE2D8_flat69_paired_selection"],
        families["direct_pc_literal"],
    )

    report = {
        "schema_version": 1,
        "rom_sha256": digest,
        "family_unique_target_counts": actual_sizes,
        "pairwise_overlaps": overlaps,
        "checkpoint_audit": {
            "table_FCE2D8_plus_direct_pc_partial_records": 135,
            "intersection": 0,
            "result": "PASS: existing 68 + 67 partial subtotal is target-disjoint",
        },
        "indirect_owner_trio_increment": {
            "unique_targets": len(families["indirect_owner_trio"]),
            "overlap_with_direct_pc": len(indirect_vs_pc),
            "new_vs_direct_pc": len(families["indirect_owner_trio"] - families["direct_pc_literal"]),
            "overlap_targets": [f"0x{x:08X}" for x in sorted(indirect_vs_pc)],
            "new_vs_all_four_existing_local_families": len(families["indirect_owner_trio"] - union_without_indirect),
        },
        "all_five_family_union": len(union_all),
        "note": "This audits overlap only among advance-local closures. It does not assert disjointness from every family in the historical parent exporter.",
    }

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
