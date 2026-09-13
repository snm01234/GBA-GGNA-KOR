#!/usr/bin/env python3
"""Reconstruct the historical Stage-2 3,948-record target identity set.

This advance-local tool rebuilds the structural target families directly from the
clean G Generation Advance ROM.  It does not read or modify parent monoeye tools.

The main purpose is to recover the historical exporter identity set and explain
why the physical fixed-record databases expose 622 text pointers while the
historical primary category contains 594 records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone.arm import ARM_REG_R3

ROM_BASE = 0x08000000
ROM_SIZE = 16 * 1024 * 1024
ROM_SHA256 = "75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772"
DRAW_WRAPPER = 0x08000CA0
EXPECTED_RECORD_IDENTITY_SHA256 = "9aeaea91c3e07d44cc591e76ccf9227b770c22cfdaceba18f952619a3e48c389"
EXPECTED_STAGE2_RAW_TEXT_BYTES = 61_350

EXPECTED_PRIMARY_COUNTS = {
    "relative_text_pair": 1530,
    "fixed_record_text": 594,
    "unit_subtext": 488,
    "entity_name": 373,
    "indexed_text_table": 221,
    "entity_subtext": 165,
    "unit_primary": 151,
    "direct_struct_text": 100,
    "search_record": 75,
    "sparse_lookup": 72,
    "direct_literal": 65,
    "id24_record": 48,
    "state_variant_pair": 36,
    "normalized_lookup": 30,
}

# 18 static victory/defeat override pair pointer literals used by 0x08012408.
OVERRIDE_LITERAL_OFFSETS = [
    0x0001249C, 0x000124B4, 0x000124CC, 0x000124E4, 0x000124FC,
    0x00012514, 0x0001252C, 0x00012540, 0x00012554, 0x00012568,
    0x0001257C, 0x00012590, 0x000125A4, 0x000125B8, 0x000125CC,
    0x000125E0, 0x000125F4, 0x00012608,
]


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def check(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"gate failed: {message}")


def is_rom_ptr(data: bytes, value: int) -> bool:
    return ROM_BASE <= value < ROM_BASE + len(data)


def ptr_target(data: bytes, off: int) -> int | None:
    value = u32(data, off)
    return value if is_rom_ptr(data, value) else None


def parse_nul_stream(data: bytes, target: int, max_bytes: int = 0x1000) -> tuple[int, int]:
    """Return (end_offset_after_NUL, token_count) for one strict token stream."""
    check(is_rom_ptr(data, target), f"non-ROM stream pointer 0x{target:08X}")
    cur = target - ROM_BASE
    end_limit = min(len(data), cur + max_bytes)
    tokens = 0
    while cur < end_limit:
        lead = data[cur]
        if lead == 0:
            return cur + 1, tokens
        if lead < 0xE0:
            cur += 1
        else:
            check(cur + 1 < end_limit, f"truncated token at 0x{cur:08X}")
            token = (lead << 8) | data[cur + 1]
            check(0xE000 <= token <= 0xE733 or 0xF000 <= token <= 0xF13E,
                  f"invalid token 0x{token:04X} at 0x{cur:08X}")
            cur += 2
        tokens += 1
    raise SystemExit(f"gate failed: unterminated stream 0x{target:08X}")


def thumb_bl_target(data: bytes, off: int) -> int | None:
    hi = u16(data, off)
    lo = u16(data, off + 2)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    disp = ((hi & 0x07FF) << 12) | ((lo & 0x07FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return (ROM_BASE + off + 4 + disp) & 0xFFFFFFFF


def literal_from_ldr_r3(data: bytes, off: int) -> tuple[int, int] | None:
    hw = u16(data, off)
    if hw & 0xFF00 != 0x4B00:
        return None
    pool = ((off + 4) & ~3) + ((hw & 0xFF) << 2)
    if pool + 4 > len(data):
        return None
    return pool, u32(data, pool)


def has_later_r3_writer(md: Cs, data: bytes, writer: int, call: int) -> bool:
    for insn in md.disasm(data[writer:call], ROM_BASE + writer):
        if insn.address == ROM_BASE + writer:
            continue
        try:
            _reads, writes = insn.regs_access()
        except Exception:
            continue
        if ARM_REG_R3 in writes:
            return True
    return False


def direct_pc_targets(data: bytes) -> set[int]:
    draw_calls = [
        off for off in range(0, len(data) - 3, 2)
        if thumb_bl_target(data, off) == DRAW_WRAPPER
    ]
    check(len(draw_calls) == 196, f"draw call count drift: {len(draw_calls)}")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    targets: set[int] = set()
    pc_calls = 0
    for call in draw_calls:
        candidates: list[tuple[int, int]] = []
        for writer in range(max(0, call - 12), call, 2):
            lit = literal_from_ldr_r3(data, writer)
            if lit is None:
                continue
            _pool, value = lit
            if not is_rom_ptr(data, value):
                continue
            try:
                end, tokens = parse_nul_stream(data, value, 512)
            except SystemExit:
                continue
            if tokens == 0 or end <= value - ROM_BASE + 1:
                continue
            candidates.append((writer, value))
        if not candidates:
            continue
        writer, value = candidates[-1]
        check(not has_later_r3_writer(md, data, writer, call),
              f"later r3 writer after PC literal at 0x{writer:08X}")
        pc_calls += 1
        targets.add(value)
    check(pc_calls == 121, f"PC-literal draw call drift: {pc_calls}")
    check(len(targets) == 67, f"PC-literal target drift: {len(targets)}")
    return targets


def relative_text_pair_targets(data: bytes) -> set[int]:
    base = 0x001BF908
    check([u16(data, base + i * 2) for i in range(3)] == [0, 0, 0], "relative NULL slots drift")
    starts = [u16(data, base + i * 2) for i in range(3, 769)]
    check(len(starts) == 766, "relative slot/sentinel count drift")
    check(all(x > 0 for x in starts), "relative live/sentinel offset zero drift")
    check(all(a < b for a, b in zip(starts, starts[1:])), "relative offsets not increasing")
    out: set[int] = set()
    for i in range(765):
        start = base + starts[i]
        boundary = base + starts[i + 1]
        p1 = ROM_BASE + start
        end1, tok1 = parse_nul_stream(data, p1)
        p2 = ROM_BASE + end1
        end2, tok2 = parse_nul_stream(data, p2)
        check(end2 == boundary, f"relative pair boundary drift at {i}: 0x{end2:X} != 0x{boundary:X}")
        out.add(p1)
        out.add(p2)
    check(len(out) == 1530, f"relative target count drift: {len(out)}")
    return out


def fixed_sets(data: bytes) -> tuple[set[int], set[int], set[int]]:
    f16_base = 0x001ABF6C
    f40_base = 0x001AFB5C
    f16_records = 137
    f40_records = 174

    # The option matrices begin exactly where the physical record arrays end.
    check(f16_base + f16_records * 0x10 == 0x001AC7FC, "fixed16 record/matrix boundary drift")
    check(f40_base + f40_records * 0x28 == 0x001B168C, "fixed40 record/matrix boundary drift")

    f16_all = {
        u32(data, f16_base + i * 0x10 + field)
        for i in range(f16_records)
        for field in (0x00, 0x0C)
    }
    f40_all = {
        u32(data, f40_base + i * 0x28 + field)
        for i in range(f40_records)
        for field in (0x00, 0x24)
    }
    check(all(is_rom_ptr(data, x) for x in f16_all | f40_all), "fixed text pointer validity drift")
    check(len(f16_all) == 274, f"fixed16 raw target drift: {len(f16_all)}")
    check(len(f40_all) == 348, f"fixed40 raw target drift: {len(f40_all)}")
    raw = f16_all | f40_all
    check(len(raw) == 622, f"fixed raw target drift: {len(raw)}")

    # Count-shaped fixed candidate only: first 123 fixed16 records plus all
    # 174 fixed40 records gives 594 targets, but the historical 61,350-byte
    # Stage-2 raw-text invariant proves that this is NOT yet the historical
    # identity set.  Keep it explicit as a hypothesis while fixed producer
    # enumeration is reconstructed.
    f16_hist = {
        u32(data, f16_base + i * 0x10 + field)
        for i in range(123)
        for field in (0x00, 0x0C)
    }
    historical = f16_hist | f40_all
    excluded_tail = raw - historical
    check(len(historical) == 594, f"count-shaped fixed candidate drift: {len(historical)}")
    check(len(excluded_tail) == 28, f"fixed tail exclusion drift: {len(excluded_tail)}")
    return raw, historical, excluded_tail


def unit_sets(data: bytes) -> tuple[set[int], set[int]]:
    base = 0x001A476C
    stride = 0x78
    primary: set[int] = set()
    sub: set[int] = set()
    for i in range(256):
        p = u32(data, base + i * stride + 4)
        if is_rom_ptr(data, p):
            primary.add(p)
        for field in (0x24, 0x40, 0x5C, 0x2C, 0x48, 0x64):
            p = u32(data, base + i * stride + field)
            if is_rom_ptr(data, p):
                sub.add(p)
    check(len(primary) == 151, f"unit primary drift: {len(primary)}")
    check(len(sub) == 488, f"unit subtext drift: {len(sub)}")
    return primary, sub


def entity_sets(data: bytes) -> tuple[set[int], set[int]]:
    id_map = 0x001A4298
    db = 0x0018E2E4
    stride = 0xAC
    reachable = {u16(data, id_map + i * 2) for i in range(512)}
    check(min(reachable) == 0 and max(reachable) == 390, "entity mapped record domain drift")
    names: set[int] = set()
    sub: set[int] = set()
    for rec in reachable:
        p = u32(data, db + rec * stride + 4)
        if is_rom_ptr(data, p):
            names.add(p)
        for slot in range(7):
            p = u32(data, db + rec * stride + 0x28 + slot * 0x14)
            if is_rom_ptr(data, p):
                sub.add(p)
    check(len(names) == 373, f"entity name drift: {len(names)}")
    check(len(sub) == 165, f"entity subtext drift: {len(sub)}")
    return names, sub


def indexed_targets(data: bytes) -> set[int]:
    table_1c92e8 = {u32(data, 0x001C92E8 + i * 4) for i in range(114)}
    fce2d8 = {u32(data, 0x00FCE2D8 + i * 4) for i in range(69)}
    fcdf78 = {u32(data, 0x00FCDF78 + i * 4) for i in range(13)}
    fce128 = {u32(data, 0x00FCE128 + i * 4) for i in range(22)}
    fce2a8 = {
        u32(data, 0x00FCE2A8 + i * 4)
        for i in range(12)
        if is_rom_ptr(data, u32(data, 0x00FCE2A8 + i * 4))
    }
    check(len(table_1c92e8) == 114, "table_1C92E8 count drift")
    check(len(fce2d8) == 68, "FCE2D8 unique count drift")
    check(len(fcdf78) == 13 and len(fce128) == 16 and len(fce2a8) == 10,
          "indirect indexed owner count drift")
    indirect = fcdf78 | fce128 | fce2a8
    check(len(indirect) == 39, f"indirect trio union drift: {len(indirect)}")
    out = table_1c92e8 | fce2d8 | indirect
    check(len(out) == 221, f"indexed target drift: {len(out)}")
    return out


def direct_struct_targets(data: bytes) -> set[int]:
    # count header + 70 x 8-byte records
    check(u32(data, 0x001C94B0) == 70, "direct_struct8 count header drift")
    s8 = {u32(data, 0x001C94B4 + i * 8) for i in range(70)}
    check(len(s8) == 70, "direct_struct8 target drift")

    base72 = 0x001C9B6C
    count72 = 0
    while data[base72 + count72 * 0x48] != 0:
        count72 += 1
    check(count72 == 30, f"direct_struct72 record count drift: {count72}")
    s72 = {u32(data, base72 + i * 0x48 + 4) for i in range(count72)}
    check(len(s72) == 30, "direct_struct72 target drift")
    out = s8 | s72
    check(len(out) == 100, f"direct struct union drift: {len(out)}")
    return out


def search_targets(data: bytes) -> set[int]:
    db = 0x00D55888
    locations = {u32(data, db + i * 0x20 + 0x10) for i in range(64)}
    parallel = {u32(data, 0x00FCE1A0 + i * 4) for i in range(64)}
    check(len(locations) == 37, f"search location target drift: {len(locations)}")
    check(len(parallel) == 38, f"search parallel target drift: {len(parallel)}")
    out = locations | parallel
    check(len(out) == 75, f"search union drift: {len(out)}")
    return out


def sparse_targets(data: bytes) -> set[int]:
    direct23 = {u32(data, 0x001B4CEC + i * 4) for i in range(23)}
    records49 = {u32(data, 0x001B4D58 + i * 0x10) for i in range(49)}
    check(len(direct23) == 23 and len(records49) == 49, "sparse component count drift")
    out = direct23 | records49
    check(len(out) == 72, f"sparse union drift: {len(out)}")
    return out


def id24_targets(data: bytes) -> set[int]:
    base = 0x001C86C8
    out = {
        u32(data, base + i * 0x18 + field)
        for i in range(16)
        for field in (0x0C, 0x10, 0x14)
    }
    check(len(out) == 48, f"id24 target drift: {len(out)}")
    return out


def state_variant_targets(data: bytes) -> set[int]:
    out: set[int] = set()
    pointers = [u32(data, off) for off in OVERRIDE_LITERAL_OFFSETS]
    check(len(set(pointers)) == 18, "override pair pointer drift")
    for p in pointers:
        base = p - ROM_BASE
        len1 = data[base]
        line1 = ROM_BASE + base + 1
        nul1 = base + 1 + len1
        check(data[nul1] == 0, f"override line1 terminator drift 0x{p:08X}")
        len2_off = nul1 + 1
        len2 = data[len2_off]
        line2 = ROM_BASE + len2_off + 1
        nul2 = len2_off + 1 + len2
        check(data[nul2] == 0, f"override line2 terminator drift 0x{p:08X}")
        out.add(line1)
        out.add(line2)
    check(len(out) == 36, f"state variant line target drift: {len(out)}")
    return out


def normalized_targets(data: bytes) -> set[int]:
    base = 0x0018DD68
    out = {u32(data, base + i * 8) for i in range(30)}
    check(all(is_rom_ptr(data, p) for p in out), "normalized pointer validity drift")
    check(len(out) == 30, f"normalized target drift: {len(out)}")
    # index 30 is the guarded fallback slot and is not a ROM text pointer.
    check(not is_rom_ptr(data, u32(data, base + 30 * 8)), "normalized fallback unexpectedly became text")
    return out


def pairwise_overlaps(sets: dict[str, set[int]]) -> list[dict[str, object]]:
    names = list(sets)
    rows = []
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            overlap = sets[left] & sets[right]
            if overlap:
                rows.append({
                    "left": left,
                    "right": right,
                    "count": len(overlap),
                    "targets": [f"0x{x:08X}" for x in sorted(overlap)],
                })
    return rows


def hash_candidates(record_ids: list[str], offsets: list[int]) -> dict[str, str]:
    forms: dict[str, bytes] = {
        "ids_newline_no_trailing": "\n".join(record_ids).encode(),
        "ids_newline_trailing": ("\n".join(record_ids) + "\n").encode(),
        "ids_concat": "".join(record_ids).encode(),
        "ids_json_compact": json.dumps(record_ids, ensure_ascii=False, separators=(",", ":")).encode(),
        "ids_json_default": json.dumps(record_ids, ensure_ascii=False).encode(),
        "offset_hex_newline": "\n".join(f"{x:08X}" for x in offsets).encode(),
        "offset_hex0x_newline": "\n".join(f"0x{x:08X}" for x in offsets).encode(),
        "offset_u32le_concat": b"".join(struct.pack("<I", x) for x in offsets),
        "offset_u32be_concat": b"".join(struct.pack(">I", x) for x in offsets),
    }
    return {name: hashlib.sha256(payload).hexdigest() for name, payload in forms.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    data = args.rom.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    check(len(data) == ROM_SIZE, f"ROM size drift: {len(data)}")
    check(digest == ROM_SHA256, f"ROM SHA-256 drift: {digest}")

    relative = relative_text_pair_targets(data)
    fixed_raw, fixed_hist, fixed_tail = fixed_sets(data)
    unit_primary, unit_subtext = unit_sets(data)
    entity_name, entity_subtext = entity_sets(data)
    indexed = indexed_targets(data)
    direct_struct = direct_struct_targets(data)
    search = search_targets(data)
    sparse = sparse_targets(data)
    direct_pc_raw = direct_pc_targets(data)
    id24 = id24_targets(data)
    state_variant = state_variant_targets(data)
    normalized = normalized_targets(data)

    # Historical primary category priority: direct PC literals lose two targets
    # already owned by indexed tables (0x081BE8C4, 0x081BEB58).
    pre_direct_union = (
        relative | fixed_hist | unit_subtext | entity_name | indexed |
        entity_subtext | unit_primary | direct_struct | search | sparse
    )
    direct_literal = direct_pc_raw - pre_direct_union
    check(len(direct_pc_raw & pre_direct_union) == 2,
          f"direct-PC earlier-family overlap drift: {len(direct_pc_raw & pre_direct_union)}")
    check(len(direct_literal) == 65, f"direct literal primary count drift: {len(direct_literal)}")

    primary = {
        "relative_text_pair": relative,
        "fixed_record_text": fixed_hist,
        "unit_subtext": unit_subtext,
        "entity_name": entity_name,
        "indexed_text_table": indexed,
        "entity_subtext": entity_subtext,
        "unit_primary": unit_primary,
        "direct_struct_text": direct_struct,
        "search_record": search,
        "sparse_lookup": sparse,
        "direct_literal": direct_literal,
        "id24_record": id24,
        "state_variant_pair": state_variant,
        "normalized_lookup": normalized,
    }

    counts = {name: len(values) for name, values in primary.items()}
    check(counts == EXPECTED_PRIMARY_COUNTS, f"primary category count drift: {counts}")
    primary_overlaps = pairwise_overlaps(primary)
    check(not primary_overlaps, f"primary categories are not disjoint: {primary_overlaps}")

    all_targets = set().union(*primary.values())
    check(len(all_targets) == 3948, f"Stage-2 target union drift: {len(all_targets)}")

    # Prove the 28 physical fixed tail targets are not secretly owned by any
    # other historical category in this reconstruction.
    all_nonfixed_raw = (
        relative | unit_subtext | entity_name | indexed | entity_subtext |
        unit_primary | direct_struct | search | sparse | direct_pc_raw |
        id24 | state_variant | normalized
    )
    fixed_tail_overlap = fixed_tail & all_nonfixed_raw
    check(not fixed_tail_overlap, f"fixed tail overlaps another family: {fixed_tail_overlap}")

    def raw_stream_bytes(targets: set[int]) -> int:
        total = 0
        for pointer in targets:
            start = pointer - ROM_BASE
            end, _tokens = parse_nul_stream(data, pointer)
            total += end - start
        return total

    candidate_raw_text_bytes = raw_stream_bytes(all_targets)
    historical_raw_text_delta = EXPECTED_STAGE2_RAW_TEXT_BYTES - candidate_raw_text_bytes

    offsets = sorted(x - ROM_BASE for x in all_targets)
    record_ids = [f"GGA-TEXT-{off:08X}" for off in offsets]
    check(len(set(record_ids)) == 3948, "record ID uniqueness drift")
    hashes = hash_candidates(record_ids, offsets)
    matched_hash_forms = [name for name, value in hashes.items() if value == EXPECTED_RECORD_IDENTITY_SHA256]

    report = {
        "schema_version": 1,
        "scope": "advance-local Stage-2 count-shaped target candidate reconstruction",
        "rom_sha256": digest,
        "historical_expected_records": 3948,
        "primary_category_counts": counts,
        "primary_categories_disjoint": True,
        "stage2_unique_targets": len(all_targets),
        "historical_raw_text_expected_bytes": EXPECTED_STAGE2_RAW_TEXT_BYTES,
        "candidate_raw_text_bytes": candidate_raw_text_bytes,
        "historical_raw_text_delta_bytes": historical_raw_text_delta,
        "historical_raw_text_invariant_match": candidate_raw_text_bytes == EXPECTED_STAGE2_RAW_TEXT_BYTES,
        "raw_family_audit": {
            "fixed_record_text_physical_raw": len(fixed_raw),
            "fixed_record_text_count_shaped_candidate": len(fixed_hist),
            "fixed16_tail_records_excluded": "123..136",
            "fixed16_tail_unique_targets_excluded": len(fixed_tail),
            "fixed_tail_overlap_with_all_other_raw_families": len(fixed_tail_overlap),
            "direct_pc_literal_raw_unique_targets": len(direct_pc_raw),
            "direct_pc_overlap_with_earlier_primary_families": len(direct_pc_raw & pre_direct_union),
            "direct_pc_primary_targets": len(direct_literal),
        },
        "known_direct_pc_overlap_targets": [
            f"0x{x:08X}" for x in sorted(direct_pc_raw & pre_direct_union)
        ],
        "fixed_tail_targets": [f"0x{x:08X}" for x in sorted(fixed_tail)],
        "target_range": {
            "min_file_offset": f"0x{min(offsets):08X}",
            "max_file_offset": f"0x{max(offsets):08X}",
        },
        "record_id_format": "GGA-TEXT-{target_file_offset:08X}",
        "record_id_count": len(record_ids),
        "record_identity_expected_sha256": EXPECTED_RECORD_IDENTITY_SHA256,
        "record_identity_hash_candidates": hashes,
        "matching_hash_forms": matched_hash_forms,
        "conclusion": (
            "All 14 historical primary category COUNTS can be matched by this candidate and the candidate categories are target-disjoint. "
            "However the candidate raw-text total is 58,365 B, not the historical 61,350 B. Therefore the exact 3,948 historical target identity set is NOT yet reproduced. "
            "The mismatch is concentrated in the unresolved fixed_record_text producer enumeration: the temporary first-123-fixed16 plus all-fixed40 choice is count-shaped only and must not be treated as historical identity proof."
        ),
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
