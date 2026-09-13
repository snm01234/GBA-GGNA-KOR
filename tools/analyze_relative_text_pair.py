#!/usr/bin/env python3
"""Advance-local static gate for the 0x0804DC30 relative two-line text-pair table."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

EXPECTED_SIZE = 16 * 1024 * 1024
EXPECTED_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
ROM_BASE = 0x08000000
TABLE = 0x001BF908
SLOTS = 768
SENTINEL_INDEX = 768
FIRST_LIVE_INDEX = 3
PAIR_COUNT = 765


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_stream(data: bytes, off: int, limit: int) -> tuple[int, int]:
    start = off
    tokens = 0
    while off < limit:
        lead = data[off]
        off += 1
        if lead == 0:
            return off, tokens
        tokens += 1
        if lead >= 0xE0:
            if off >= limit:
                raise AssertionError(f"truncated 2-byte token at 0x{start:08X}")
            off += 1
    raise AssertionError(f"unterminated stream at 0x{start:08X}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    args = ap.parse_args()
    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert len(data) == EXPECTED_SIZE
    assert digest == EXPECTED_SHA256

    # 0x0804DC42 loads the table base literal at file 0x0004DC54.
    assert u32(data, 0x0004DC54) == ROM_BASE + TABLE
    # Runtime index is row*3+column, then doubled for the u16 offset table.
    assert data[0x0004DC3A:0x0004DC42] == bytes.fromhex("4200121852181204")

    offsets = [u16(data, TABLE + 2 * i) for i in range(SLOTS + 1)]
    assert offsets[:3] == [0, 0, 0]
    assert all(offsets[i] != 0 for i in range(FIRST_LIVE_INDEX, SLOTS))
    assert all(offsets[i] < offsets[i + 1] for i in range(FIRST_LIVE_INDEX, SLOTS))

    stream_offsets: list[int] = []
    total_tokens = 0
    pair_bytes = 0
    pairs = []
    for index in range(FIRST_LIVE_INDEX, SLOTS):
        start = TABLE + offsets[index]
        end = TABLE + offsets[index + 1]
        p1 = start
        p2, t1 = parse_stream(data, p1, end)
        p3, t2 = parse_stream(data, p2, end)
        assert p3 == end, (index, hex(start), hex(end), hex(p3))
        stream_offsets.extend([p1, p2])
        total_tokens += t1 + t2
        pair_bytes += end - start
        pairs.append({
            "index": index,
            "row": index // 3,
            "column": index % 3,
            "relative_offset": offsets[index],
            "stream_1_file_offset": f"0x{p1:08X}",
            "stream_2_file_offset": f"0x{p2:08X}",
            "end_file_offset": f"0x{end:08X}",
        })

    assert len(pairs) == PAIR_COUNT
    assert len(stream_offsets) == PAIR_COUNT * 2
    assert len(set(stream_offsets)) == PAIR_COUNT * 2

    result = {
        "schema_version": 1,
        "rom_sha256": digest,
        "family": "relative_text_pair",
        "semantic_status": "structural provenance closed",
        "table": {
            "file_offset": f"0x{TABLE:08X}",
            "rom_address": f"0x{ROM_BASE + TABLE:08X}",
            "physical_slots": SLOTS,
            "sentinel_index": SENTINEL_INDEX,
            "null_slots": [0, 1, 2],
            "live_pair_indices": "3..767",
            "live_pairs": PAIR_COUNT,
            "sentinel_relative_offset": f"0x{offsets[SENTINEL_INDEX]:04X}",
        },
        "corpus": {
            "streams": len(stream_offsets),
            "unique_stream_offsets": len(set(stream_offsets)),
            "payload_bytes": pair_bytes,
            "token_count": total_tokens,
            "first_stream_file_offset": f"0x{min(stream_offsets):08X}",
            "last_stream_file_offset": f"0x{max(stream_offsets):08X}",
            "payload_end_file_offset": f"0x{TABLE + offsets[SENTINEL_INDEX]:08X}",
        },
        "invariants": [
            "indices 0..2 are NULL",
            "indices 3..767 are 765 strictly increasing nonzero pair starts",
            "index 768 is the end-boundary sentinel",
            "every live interval contains exactly two strict token streams and ends exactly at the next relative offset",
            "all 1,530 stream start offsets are unique",
        ],
        "pairs": pairs,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
