#!/usr/bin/env python3
"""Dump per-animation source-id sequences for ability resource 0x083424A0."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM

ROM_BASE = 0x08000000
ABILITY = 0x083424A0


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def main() -> int:
    rom = MAIN_TIP_ROM.read_bytes()
    off = ABILITY - ROM_BASE
    kind, pal_count, gfx_rel, pal_rel, anim_count = struct.unpack_from("<5I", rom, off)
    rels = [u32(rom, off + 0x14 + i * 4) for i in range(anim_count)]
    starts = [off + 0x14 + rel for rel in rels]
    ends = starts[1:] + [off + gfx_rel]
    tiles = (pal_rel - gfx_rel) // 32
    rows = []
    for index, (a, b) in enumerate(zip(starts, ends)):
        blob = rom[a:b]
        values = list(struct.unpack_from(f"<{len(blob)//2}H", blob))
        ids = [v for v in values if v < tiles]
        # compress to unique ordered appearance
        seen = []
        for v in ids:
            if not seen or seen[-1] != v:
                seen.append(v)
        rows.append({
            "anim": index,
            "group": index // 3,
            "bytes": len(blob),
            "id_count": len(ids),
            "unique": sorted(set(ids)),
            "unique_count": len(set(ids)),
            "min_max": [min(ids), max(ids)] if ids else None,
            "seq_head": seen[:40],
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
