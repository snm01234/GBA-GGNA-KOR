#!/usr/bin/env python3
"""Dump ID-command list name/effect overflow vs ARM column widths."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

THIS = Path(__file__).resolve().parent
ROOT = THIS.parent
sys.path.insert(0, str(THIS))

from ggen_advance_project_paths import MAIN_TIP_ROM, TRANSLATION_MERGED_JSON
from patch_ggen_advance_idcmd_ecm_mishudeuk_20260905 import owner_offsets
from patch_ggen_advance_intermission_text_consumers_20260904 import payload_at, u32

ROM_BASE = 0x08000000
NAME_CAP = 16
EFFECT_CAP = 10
DESC_CAP = 17


def vis(text: str) -> int:
    return len(text.replace("\n", ""))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    rom = MAIN_TIP_ROM.read_bytes()
    for cat, cap in (
        ("id_command_description", DESC_CAP),
        ("id_command_name", NAME_CAP),
        ("id_command_effect_summary", EFFECT_CAP),
    ):
        rows = [
            row
            for row in merged["records"]
            if row.get("semantic_category") == cat and row.get("translation_status") == "translated"
        ]
        hist = Counter(vis(str(row.get("translation_ko") or "")) for row in rows)
        over = [row for row in rows if vis(str(row.get("translation_ko") or "")) > cap]
        print(f"== {cat} cap={cap} translated={len(rows)} over={len(over)}")
        print("hist", hist.most_common())
        for row in sorted(over, key=lambda r: -vis(str(r.get("translation_ko") or ""))):
            ko = str(row.get("translation_ko") or "")
            owners = owner_offsets(row)
            ptrs = sorted({u32(rom, owner) for owner in owners})
            sizes = [len(payload_at(rom, ptr)) for ptr in ptrs]
            print(
                f"  {vis(ko):2d} {ko!r} {row['record_id']} owners={len(owners)} "
                f"ptr={[hex(p) for p in ptrs]} pay={sizes} src={row.get('translation_source')}"
            )
        if cat == "id_command_name":
            eq = [row for row in rows if vis(str(row.get("translation_ko") or "")) == cap]
            print(f"  exactly {cap}: {len(eq)}")
            for row in eq:
                print(f"    {str(row.get('translation_ko') or '')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
