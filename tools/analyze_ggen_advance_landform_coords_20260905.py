#!/usr/bin/env python3
"""Find LANDFORM 海 draw-site by window-relative coordinates 45,18."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from ggen_advance_project_paths import ORIGINAL_ROM

# Thumb mov rd, #imm8 : 0x20|rd, imm
# mov r1, #45 = 21 2D
# mov r2, #18 = 22 12
# mov r0, #45 = 20 2D
# mov r3, #18 = 23 12
# Also 101,74 absolute: mov r1, #101 = 21 65; mov r2, #74 = 22 4A


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    patterns = {
        "mov_r1_45": bytes.fromhex("2D 21"),
        "mov_r2_18": bytes.fromhex("12 22"),
        "mov_r0_45": bytes.fromhex("2D 20"),
        "mov_r3_18": bytes.fromhex("12 23"),
        "mov_r1_101": bytes.fromhex("65 21"),
        "mov_r2_74": bytes.fromhex("4A 22"),
        "mov_r0_101": bytes.fromhex("65 20"),
        "mov_r1_74": bytes.fromhex("4A 21"),
        "add_sp_imm_related": bytes.fromhex("65 00"),
    }
    hits = {name: [] for name in patterns}
    for name, needle in patterns.items():
        start = 0
        while len(hits[name]) < 8:
            pos = japan.find(needle, start)
            if pos < 0:
                break
            if pos % 2 == 0:  # thumb aligned
                hits[name].append(hex(pos))
            start = pos + 1
    # proximity: 45 and 18 within 16 bytes
    prox = []
    for a in hits["mov_r1_45"] + hits["mov_r0_45"]:
        ia = int(a, 16)
        for b in hits["mov_r2_18"] + hits["mov_r3_18"]:
            ib = int(b, 16)
            if abs(ia - ib) <= 16:
                prox.append((a, b, abs(ia - ib)))
    absprox = []
    for a in hits["mov_r1_101"] + hits["mov_r0_101"]:
        ia = int(a, 16)
        for b in hits["mov_r2_74"] + hits["mov_r1_74"]:
            ib = int(b, 16)
            if abs(ia - ib) <= 16:
                absprox.append((a, b, abs(ia - ib)))
    print("rel_prox", prox)
    print("abs_prox", absprox)
    print("r1_101", hits["mov_r1_101"][:8])
    print("r2_74", hits["mov_r2_74"][:8])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
