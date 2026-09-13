#!/usr/bin/env python3
"""Scan custom-LZSS graphic resources for the user-measured 32x16 action labels.

This is a read-only discovery tool. It does not assume a resource table: every
4-byte-aligned ROM word that looks like the game's custom-LZSS header is tested,
and every sequential 4x2 tile window in successfully decoded 4bpp streams is
compared against the independently quantized user screenshot crops.

The comparison is palette-name independent. We use normalized mutual
information (NMI) between the 4bpp index plane and the measured RGB cluster
plane, so alternate normal/focus palettes can still match the same geometry.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT

JP_ROM = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
MEASURED = ADVANCE_ROOT / "analysis" / "ggen_advance_user_action_menu_crops_20260830.json"
DEFAULT_OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_action_graphics_scan_20260830.json"
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
HEX = "0123456789ABCDEF"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def lzss_decompress(payload: bytes, max_output: int = 0x40000) -> bytes:
    ring = bytearray(4096)
    ring_pos = 4078
    out = bytearray()
    src = 0
    flags = 0
    while src < len(payload):
        flags >>= 1
        if (flags & 0x100) == 0:
            flags = payload[src] | 0xFF00
            src += 1
        if flags & 1:
            if src >= len(payload):
                raise ValueError("literal overrun")
            value = payload[src]
            src += 1
            out.append(value)
            ring[ring_pos] = value
            ring_pos = (ring_pos + 1) & 0xFFF
        else:
            if src + 1 >= len(payload):
                raise ValueError("backref overrun")
            lo = payload[src]
            hi = payload[src + 1]
            src += 2
            offset = lo | ((hi & 0xF0) << 4)
            length = (hi & 0x0F) + 3
            for index in range(length):
                value = ring[(offset + index) & 0xFFF]
                out.append(value)
                ring[ring_pos] = value
                ring_pos = (ring_pos + 1) & 0xFFF
                if len(out) > max_output:
                    raise ValueError("output limit")
    return bytes(out)


def decode_tile(data: bytes, tile_id: int) -> list[int]:
    raw = data[tile_id * 32 : (tile_id + 1) * 32]
    if len(raw) != 32:
        raise ValueError("tile overrun")
    result: list[int] = []
    for y in range(8):
        for x in range(8):
            value = raw[y * 4 + x // 2]
            result.append((value >> (4 * (x & 1))) & 0x0F)
    return result


def stitch_sequential_4x2(data: bytes, first_tile: int) -> list[int]:
    tiles = [decode_tile(data, first_tile + i) for i in range(8)]
    out: list[int] = []
    for y in range(16):
        ty = y // 8
        iy = y & 7
        for tx in range(4):
            tile = tiles[ty * 4 + tx]
            out.extend(tile[iy * 8 : iy * 8 + 8])
    return out


def entropy(values: list[int]) -> float:
    n = len(values)
    counts = Counter(values)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def nmi(a: list[int], b: list[int]) -> float:
    gate(len(a) == len(b) and len(a) > 0, "NMI size mismatch")
    ha, hb = entropy(a), entropy(b)
    if ha == 0 or hb == 0:
        return 0.0
    n = len(a)
    pairs = Counter(zip(a, b))
    ca, cb = Counter(a), Counter(b)
    mi = 0.0
    for (x, y), c in pairs.items():
        pxy = c / n
        mi += pxy * math.log2(pxy / ((ca[x] / n) * (cb[y] / n)))
    return 2.0 * mi / (ha + hb)


def compact_classes(text: str) -> list[int]:
    values = [HEX.index(ch) for ch in text.strip()]
    gate(len(values) == 512, f"measured crop is not 32x16: {len(values)}")
    return values


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rom", type=Path, default=JP_ROM)
    ap.add_argument("--measured", type=Path, default=MEASURED)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--top", type=int, default=24)
    args = ap.parse_args()

    rom = args.rom.read_bytes()
    digest = hashlib.sha256(rom).hexdigest()
    gate(digest == EXPECTED_SHA256, f"unexpected Japanese ROM hash: {digest}")
    measured_json = json.loads(args.measured.read_text(encoding="utf-8"))
    measured = {name: compact_classes(value) for name, value in measured_json["classes"].items()}

    candidates: list[dict[str, Any]] = []
    tested_headers = 0
    accepted_streams = 0
    for off in range(0, len(rom) - 8, 4):
        header = struct.unpack_from("<I", rom, off)[0]
        if (header & 0xFFFF0000) != 0x80000000:
            continue
        body_len = header & 0xFFFF
        if body_len < 16 or off + 4 + body_len > len(rom):
            continue
        tested_headers += 1
        try:
            decoded = lzss_decompress(rom[off + 4 : off + 4 + body_len])
        except (ValueError, IndexError):
            continue
        if len(decoded) < 8 * 32 or len(decoded) % 32 != 0:
            continue
        # Graphic streams of interest are compact; rejecting huge random
        # decodes keeps false-positive cost bounded without excluding known UI.
        tile_count = len(decoded) // 32
        if tile_count > 4096:
            continue
        accepted_streams += 1
        for first in range(0, tile_count - 7):
            plane = stitch_sequential_4x2(decoded, first)
            # Skip near-flat windows; they generate high accidental mappings.
            if len(set(plane)) < 4:
                continue
            scores = {name: nmi(plane, target) for name, target in measured.items()}
            best_name, best_score = max(scores.items(), key=lambda item: item[1])
            if best_score < 0.20:
                continue
            candidates.append({
                "resource_file_offset": f"0x{off:08X}",
                "compressed_body_length": body_len,
                "decoded_size": len(decoded),
                "decoded_tile_count": tile_count,
                "first_sequential_tile": first,
                "best_crop": best_name,
                "best_nmi": best_score,
                "scores": scores,
            })

    by_crop: dict[str, list[dict[str, Any]]] = {}
    for name in measured:
        rows = sorted(candidates, key=lambda row: row["scores"][name], reverse=True)[: args.top]
        by_crop[name] = [
            {**row, "target_nmi": row["scores"][name]}
            for row in rows
        ]

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_action_graphics_scan_20260830",
        "result": "PASS",
        "source": {"path": args.rom.name, "sha256": digest, "size": len(rom)},
        "measurement": str(args.measured.relative_to(ADVANCE_ROOT)),
        "method": "scan custom-LZSS 4bpp streams; compare every sequential 4x2 tile window to user crop by palette-independent normalized mutual information",
        "tested_header_count": tested_headers,
        "accepted_4bpp_stream_count": accepted_streams,
        "matches_by_crop": by_crop,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "result": "PASS",
        "out": str(args.out),
        "tested_headers": tested_headers,
        "accepted_streams": accepted_streams,
        "best": {
            name: ([{
                "resource_file_offset": rows[0]["resource_file_offset"],
                "first_tile": rows[0]["first_sequential_tile"],
                "nmi": round(rows[0]["target_nmi"], 6),
            }] if rows else [])
            for name, rows in by_crop.items()
        },
    }, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
