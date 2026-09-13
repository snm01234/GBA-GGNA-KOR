#!/usr/bin/env python3
"""Relocate map-script 12x12 Korean lines without moving inline bytecode.

Map cutscene prints live inside event bytecode at 0x00F00000-0x00FC0000.
Replacing those bytes in place would shift the script PC, so this PoC leaves
the original Japanese streams untouched and redirects the 12x12 parser/draw
entry points to relocated Korean token streams.

Lookup keys are the original GBA addresses of each NUL-terminated segment.
On a parser hit the exit hook returns the original NUL address so callers that
do `adds r0, #1` still walk the Japanese bytecode.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, Callable

THIS_DIR = Path(__file__).resolve().parent
ADVANCE_DIR = THIS_DIR.parent

ROM_BASE = 0x08000000
MAP_BANK_START = 0x00F00000
MAP_BANK_END = 0x00FC0000
PARSER_ENTRY = 0x0000118C
PARSER_CONT = 0x000011AE
PARSER_EXIT = 0x000011B4
DRAW_CA8 = 0x00000CA8
DRAW_CB0 = 0x00000CB0
IDENTIFIED_PATH = ADVANCE_DIR / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"

ORIGINAL_PARSER_ENTRY = bytes.fromhex("70 B5 06 1C 0C 1C 15 1C")
ORIGINAL_PARSER_EXIT = bytes.fromhex("20 1C 70 BC 02 BC 08 47")
ORIGINAL_DRAW_CA8 = bytes.fromhex("06 1C 0C 1C 15 1C 98 46")

ENTRY_SIZE = 12
READY = {"translated"}
MAX_DIALOGUE_CELLS = 15

# ASCII / extra punctuation that the Korean draft uses, mapped onto 12x12 glyphs.
CHAR_ALIASES = {
    "!": "！",
    "?": "？",
    ",": "、",
    ".": "・",
    "(": "（",
    ")": "）",
    "%": "％",
    "/": "／",
    "-": "－",
    "+": "＋",
    "＋": "＋",
    "~": "～",
    "K": "Ｋ",
    "O": "Ｏ",
    "U": "Ｕ",
    "V": "Ｖ",
    "3": "３",
    "4": "４",
    "』": "」",
    "『": "「",
}


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def parse_hex(value: str) -> int:
    return int(value, 16)


def raw_hex_bytes(value: str) -> bytes:
    return bytes.fromhex(value.replace(" ", ""))


def slot_to_bytes(slot: int) -> bytes:
    if 1 <= slot <= 0xDF:
        return bytes((slot,))
    token = 0xDF20 + slot
    gate(0xE000 <= token <= 0xEFFF, f"12x12 token outside literal range for slot 0x{slot:04X}")
    return bytes((token >> 8, token & 0xFF))


def load_identified_12x12(path: Path = IDENTIFIED_PATH) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, int] = {}
    for slot_text, char in payload["verified_charmap"].items():
        slot = int(slot_text, 16)
        previous = mapping.get(char)
        if previous is None or slot < previous:
            mapping[char] = slot
    # Match the Korean-only dash copy used by the unified 12x12 encoder.
    # The original slot 0x00E5 is painted as 값 in the current Korean ROM.
    mapping["―"] = 0x07B9
    return mapping


def encode_map_korean_line(
    value: str,
    hangul_charmap: dict[str, int],
    identified: dict[str, int],
) -> tuple[bytes | None, list[str]]:
    out = bytearray()
    missing: list[str] = []
    for char in value:
        if char == "\n":
            missing.append("\\n")
            continue
        mapped = CHAR_ALIASES.get(char, char)
        slot = hangul_charmap.get(mapped)
        if slot is None:
            slot = identified.get(mapped)
        if slot is None:
            missing.append(mapped)
            continue
        out.extend(slot_to_bytes(slot))
    if missing:
        return None, sorted(set(missing))
    out.append(0)
    return bytes(out), []


class _Thumb:
    def __init__(self, base: int) -> None:
        self.base = base
        self.ops: list[tuple[str, Any]] = []

    def label(self, name: str) -> None:
        self.ops.append(("label", name))

    def h(self, instr: int) -> None:
        self.ops.append(("h", instr & 0xFFFF))

    def bl(self, name: str) -> None:
        self.ops.append(("bl", name))

    def b(self, name: str, cond: int | None = None) -> None:
        self.ops.append(("b", (name, cond)))

    def ldr_pc(self, rt: int, name: str) -> None:
        self.ops.append(("ldr_pc", (rt, name)))

    def align4(self) -> None:
        self.ops.append(("align4", None))

    def word(self, name: str, value: int) -> None:
        self.ops.append(("word", (name, value & 0xFFFFFFFF)))

    def build(self) -> bytes:
        labels: dict[str, int] = {}
        for _ in range(3):
            addr = self.base
            labels.clear()
            for kind, payload in self.ops:
                if kind == "label":
                    labels[payload] = addr
                    continue
                if kind == "align4":
                    if addr & 3:
                        addr += 2
                    continue
                if kind == "word":
                    if addr & 3:
                        addr += 2
                    labels[payload[0]] = addr
                    addr += 4
                    continue
                addr += 4 if kind == "bl" else 2
        out = bytearray()
        addr = self.base
        for kind, payload in self.ops:
            if kind == "label":
                continue
            if kind == "align4":
                if addr & 3:
                    out.extend(struct.pack("<H", 0x46C0))
                    addr += 2
                continue
            if kind == "word":
                if addr & 3:
                    out.extend(struct.pack("<H", 0x46C0))
                    addr += 2
                out.extend(struct.pack("<I", payload[1]))
                addr += 4
                continue
            if kind == "h":
                out.extend(struct.pack("<H", payload))
                addr += 2
                continue
            if kind == "bl":
                target = labels[payload]
                offset = target - (addr + 4)
                gate(offset % 2 == 0, "Thumb BL misaligned")
                imm = offset >> 1
                gate(-0x400000 <= imm < 0x400000, "Thumb BL out of range")
                s = (imm >> 21) & 1
                imm10 = (imm >> 11) & 0x3FF
                imm11 = imm & 0x7FF
                first = 0xF000 | (s << 10) | imm10
                second = 0xF800 | imm11
                out.extend(struct.pack("<HH", first, second))
                addr += 4
                continue
            if kind == "b":
                name, cond = payload
                target = labels[name]
                offset = target - (addr + 4)
                gate(offset % 2 == 0, "Thumb B misaligned")
                imm = offset >> 1
                if cond is None:
                    gate(-1024 <= imm < 1024, "unconditional B out of range")
                    out.extend(struct.pack("<H", 0xE000 | (imm & 0x7FF)))
                else:
                    gate(-128 <= imm < 128, "conditional B out of range")
                    out.extend(struct.pack("<H", 0xD000 | (cond << 8) | (imm & 0xFF)))
                addr += 2
                continue
            if kind == "ldr_pc":
                rt, name = payload
                target = labels[name]
                pc = (addr + 4) & ~3
                off = target - pc
                gate(off % 4 == 0 and 0 <= off <= 1020, f"PC-relative LDR out of range for {name}")
                out.extend(struct.pack("<H", 0x4800 | (rt << 8) | (off // 4)))
                addr += 2
                continue
            raise AssertionError(kind)
        return bytes(out)


def _emit_map_hooks(t: _Thumb, table_address: int, count: int) -> None:
    # r3 trampoline lands here with original r0/r1/r2/lr.
    # Thumb pop with the extra bit loads PC, so caller lr is kept in r12.
    t.label("entry")
    t.h(0x46F4)  # mov r12, lr
    t.bl("lookup")
    t.h(0x46E6)  # mov lr, r12
    t.h(0xB408)  # push {r3} orig_end or 0
    t.h(0xB570)  # push {r4, r5, r6, lr}
    t.h(0x1C06)  # mov r6, r0
    t.h(0x1C0C)  # mov r4, r1
    t.h(0x1C15)  # mov r5, r2
    t.ldr_pc(3, "cont118c")
    t.h(0x4718)  # bx r3

    # Original exit replaced; stack is r4,r5,r6,lr,orig_end.
    t.label("exit")
    t.h(0x9B04)  # ldr r3, [sp, #16]
    t.h(0x2B00)  # cmp r3, #0
    t.b("use_r4", 0x0)  # beq
    t.h(0x1C18)  # mov r0, r3
    t.b("do_pop")
    t.label("use_r4")
    t.h(0x1C20)  # mov r0, r4
    t.label("do_pop")
    t.h(0xBC70)  # pop {r4, r5, r6}
    t.h(0xBC02)  # pop {r1}
    t.h(0xB001)  # add sp, #4
    t.h(0x4708)  # bx r1

    # Draw wrapper already saved r4-r7; r3 is the text pointer.
    t.label("draw")
    t.h(0x46F4)  # mov r12, lr
    t.h(0xB407)  # push {r0, r1, r2}
    t.h(0x1C19)  # mov r1, r3
    t.bl("lookup")
    t.h(0x1C0B)  # mov r3, r1
    t.h(0xBC07)  # pop {r0, r1, r2}
    t.h(0x46E6)  # mov lr, r12
    t.h(0x1C06)  # mov r6, r0
    t.h(0x1C0C)  # mov r4, r1
    t.h(0x1C15)  # mov r5, r2
    t.h(0x4698)  # mov r8, r3
    t.ldr_pc(7, "contca0")
    t.h(0x4738)  # bx r7

    t.label("lookup")
    t.h(0xB4F5)  # push {r0, r2, r4, r5, r6, r7}
    t.ldr_pc(4, "table")
    t.ldr_pc(5, "count")
    t.h(0x2600)  # movs r6, #0
    t.h(0x1C2F)  # mov r7, r5
    t.label("loop")
    t.h(0x42BE)  # cmp r6, r7
    t.b("miss", 0xA)  # bge
    t.h(0x19F0)  # add r0, r6, r7
    t.h(0x0840)  # lsr r0, r0, #1
    t.h(0x00C2)  # lsl r2, r0, #3
    t.h(0x0083)  # lsl r3, r0, #2
    t.h(0x18D2)  # add r2, r2, r3
    t.h(0x1912)  # add r2, r2, r4
    t.h(0x6813)  # ldr r3, [r2]
    t.h(0x4299)  # cmp r1, r3
    t.b("hit", 0x0)  # beq
    t.b("higher", 0x8)  # bhi
    t.h(0x1C07)  # mov r7, r0
    t.b("loop")
    t.label("higher")
    t.h(0x1C46)  # adds r6, r0, #1
    t.b("loop")
    t.label("hit")
    t.h(0x6851)  # ldr r1, [r2, #4]
    t.h(0x6893)  # ldr r3, [r2, #8]
    t.b("done")
    t.label("miss")
    t.h(0x2300)  # movs r3, #0
    t.label("done")
    t.h(0xBCF5)  # pop {r0, r2, r4, r5, r6, r7}
    t.h(0x4770)  # bx lr

    t.align4()
    t.word("table", table_address)
    t.word("count", count)
    t.word("cont118c", (ROM_BASE + PARSER_CONT) | 1)
    t.word("contca0", (ROM_BASE + DRAW_CB0) | 1)


def assemble_map_hooks(base: int, table_address: int, count: int) -> tuple[bytes, dict[str, int]]:
    t = _Thumb(base)
    _emit_map_hooks(t, table_address, count)
    code = t.build()
    labels: dict[str, int] = {}
    addr = base
    for kind, payload in t.ops:
        if kind == "label":
            labels[payload] = addr
            continue
        if kind == "align4":
            if addr & 3:
                addr += 2
            continue
        if kind == "word":
            if addr & 3:
                addr += 2
            labels[payload[0]] = addr
            addr += 4
            continue
        addr += 4 if kind == "bl" else 2
    return code, labels


def make_trampoline(reg: int, target: int) -> bytes:
    gate(0 <= reg <= 7, "trampoline register must be a low Thumb register")
    ldr = 0x4800 | (reg << 8)
    bx = 0x4700 | (reg << 3)
    return struct.pack("<HHI", ldr, bx, target | 1)


def collect_map_script_streams(
    records: list[dict[str, Any]],
    hangul_charmap: dict[str, int],
    identified: dict[str, int],
) -> tuple[bytes, list[tuple[int, int, int]], dict[str, Any]]:
    blob = bytearray()
    entries: list[tuple[int, int, int]] = []
    missing: dict[str, int] = {}
    counts = {
        "rows_ready": 0,
        "rows_encoded": 0,
        "rows_encode_failed": 0,
        "rows_kept_original": 0,
        "segments_encoded": 0,
        "opcode_alias_keys": 0,
        "dialogue_width_cells": MAX_DIALOGUE_CELLS,
        "dialogue_overflow_segments": 0,
    }
    for row in records:
        if row.get("source_scope") != "scenario_map_script" or row.get("scope_status") != "included":
            continue
        if row.get("translation_status") not in READY or row.get("translation_policy") != "translate":
            counts["rows_kept_original"] += 1
            continue
        counts["rows_ready"] += 1
        segments = list(row.get("segments") or [])
        translations = list(row.get("translation_segments") or [])
        if len(translations) != len(segments):
            ko = str(row.get("translation_ko") or "")
            if "\n" in ko:
                derived = ko.split("\n")
            elif "\\n" in ko:
                derived = ko.split("\\n")
            else:
                derived = [ko]
            if len(derived) == len(segments):
                translations = derived
            else:
                counts["rows_encode_failed"] += 1
                continue
        encoded_parts: list[bytes] = []
        failed: list[str] = []
        for segment_index, text in enumerate(translations):
            text_value = str(text)
            gate(
                "\n" not in text_value and len(text_value) <= MAX_DIALOGUE_CELLS,
                f"map dialogue exceeds {MAX_DIALOGUE_CELLS} cells: "
                f"{row['record_id']} segment {segment_index} ({len(text_value)})",
            )
            payload, failed_chars = encode_map_korean_line(text_value, hangul_charmap, identified)
            if payload is None:
                failed.extend(failed_chars)
            else:
                encoded_parts.append(payload)
        if failed or len(encoded_parts) != len(segments):
            counts["rows_encode_failed"] += 1
            for char in sorted(set(failed)):
                missing[char] = missing.get(char, 0) + 1
            continue
        cursor = parse_hex(str(row["target_file_offset"]))
        first_rel: int | None = None
        first_end: int | None = None
        for segment, payload in zip(segments, encoded_parts):
            original = raw_hex_bytes(str(segment.get("raw_hex") or ""))
            gate(original.endswith(b"\x00"), f"map segment missing NUL: {row['record_id']}")
            orig = ROM_BASE + cursor
            orig_end = orig + len(original) - 1
            if first_rel is None:
                first_rel = len(blob)
                first_end = orig_end
            entries.append((orig, len(blob), orig_end))
            blob.extend(payload)
            cursor += len(original)
            counts["segments_encoded"] += 1
        opcode_text = str(row.get("opcode_18_file_offset") or "")
        if opcode_text and first_rel is not None and first_end is not None:
            opcode_addr = ROM_BASE + parse_hex(opcode_text)
            text_start = ROM_BASE + parse_hex(str(row["target_file_offset"]))
            existing = {orig for orig, _, _ in entries}
            if opcode_addr != text_start and opcode_addr not in existing:
                entries.append((opcode_addr, first_rel, first_end))
                counts["opcode_alias_keys"] += 1
        counts["rows_encoded"] += 1
    gate(not missing, "map-script Korean encode failed: " + ", ".join(f"{char} x{count}" for char, count in list(missing.items())[:12]))
    return bytes(blob), entries, counts


def materialize_lookup_table(
    entries: list[tuple[int, int, int]],
    blob_address: int,
    resolved_entries: list[tuple[int, int, int]] | None = None,
) -> bytes:
    resolved = [(orig, blob_address + rel, orig_end) for orig, rel, orig_end in entries]
    resolved.extend(resolved_entries or [])
    resolved.sort(key=lambda item: item[0])
    seen: set[int] = set()
    table = bytearray()
    for orig, neu, orig_end in resolved:
        gate(orig not in seen, f"duplicate map-script lookup key 0x{orig:08X}")
        seen.add(orig)
        table.extend(struct.pack("<III", orig, neu, orig_end))
    gate(len(table) == len(resolved) * ENTRY_SIZE, "map-script lookup table size drift")
    return bytes(table)


def hook_allowed_offsets() -> set[int]:
    allowed: set[int] = set()
    for start, size in ((PARSER_ENTRY, 8), (PARSER_EXIT, 8), (DRAW_CA8, 8)):
        allowed.update(range(start, start + size))
    return allowed


def apply_map_script_inline_hooks(
    rom: bytes,
    candidate: bytearray,
    allocate_blob: Callable[[bytearray, int, bytes, str], tuple[int, int]],
    cursor: int,
    records: list[dict[str, Any]],
    hangul_charmap: dict[str, int],
    runtime_redirects: list[tuple[int, int, int]] | None = None,
) -> tuple[int, dict[str, Any]]:
    gate(rom[PARSER_ENTRY : PARSER_ENTRY + 8] == ORIGINAL_PARSER_ENTRY, "parser entry prologue drift")
    gate(rom[PARSER_EXIT : PARSER_EXIT + 8] == ORIGINAL_PARSER_EXIT, "parser exit epilogue drift")
    gate(rom[DRAW_CA8 : DRAW_CA8 + 8] == ORIGINAL_DRAW_CA8, "draw wrapper CA8 prologue drift")
    identified = load_identified_12x12()
    blob, raw_entries, counts = collect_map_script_streams(records, hangul_charmap, identified)
    resolved_redirects = list(runtime_redirects or [])
    if not raw_entries and not resolved_redirects:
        return cursor, {
            "applied": False,
            "counts": counts,
            "lookup_entries": 0,
            "runtime_redirect_entries": 0,
        }

    blob_start = 0
    blob_address = 0
    if blob:
        blob_start, cursor = allocate_blob(candidate, cursor, blob, "map_script_korean_streams")
        cursor = (cursor + 3) & ~3
        blob_address = ROM_BASE + blob_start
    table = materialize_lookup_table(raw_entries, blob_address, resolved_redirects)
    table_start, cursor = allocate_blob(candidate, cursor, table, "map_script_lookup_table")
    cursor = (cursor + 3) & ~3
    table_address = ROM_BASE + table_start
    count = len(table) // ENTRY_SIZE

    dummy, _ = assemble_map_hooks(0x09000000, table_address, count)
    code_start, cursor = allocate_blob(candidate, cursor, bytes(len(dummy)), "map_script_inline_hooks")
    code, labels = assemble_map_hooks(ROM_BASE + code_start, table_address, count)
    gate(len(code) == len(dummy), "map-script hook size drifted between assembly passes")
    _verify_hook_disassembly(code, ROM_BASE + code_start, labels)
    candidate[code_start : code_start + len(code)] = code
    cursor = (cursor + 3) & ~3

    candidate[PARSER_ENTRY : PARSER_ENTRY + 8] = make_trampoline(3, labels["entry"])
    candidate[PARSER_EXIT : PARSER_EXIT + 8] = make_trampoline(3, labels["exit"])
    candidate[DRAW_CA8 : DRAW_CA8 + 8] = make_trampoline(4, labels["draw"])

    gate(
        bytes(candidate[MAP_BANK_START:MAP_BANK_END]) == rom[MAP_BANK_START:MAP_BANK_END],
        "map-script bank bytes changed",
    )
    return cursor, {
        "applied": True,
        "counts": counts,
        "lookup_entries": count,
        "runtime_redirect_entries": len(resolved_redirects),
        "streams_file_offset": f"0x{blob_start:08X}",
        "streams_gba_address": f"0x{ROM_BASE + blob_start:08X}",
        "streams_size": len(blob),
        "table_file_offset": f"0x{table_start:08X}",
        "table_gba_address": f"0x{table_address:08X}",
        "table_size": len(table),
        "hooks_file_offset": f"0x{code_start:08X}",
        "hooks_gba_address": f"0x{ROM_BASE + code_start:08X}",
        "hooks_size": len(code),
        "hook_sites": {
            "parser_entry": "0x0800118C",
            "parser_exit": "0x080011B4",
            "draw_ca8": "0x08000CA8",
        },
        "entry_thumb": f"0x{labels['entry']:08X}",
        "exit_thumb": f"0x{labels['exit']:08X}",
        "draw_thumb": f"0x{labels['draw']:08X}",
    }


def _verify_hook_disassembly(code: bytes, base: int, labels: dict[str, int]) -> None:
    try:
        import capstone
    except ImportError:
        return
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    decoded = [(insn.address, insn.mnemonic, insn.op_str) for insn in md.disasm(code, base)]
    gate(decoded, "map-script hook failed to disassemble")
    by_addr = {addr: (mnemonic, ops) for addr, mnemonic, ops in decoded}
    entry = by_addr.get(labels["entry"])
    gate(entry is not None and entry[0] == "mov", "entry hook does not start with mov ip, lr")
    exit_insn = by_addr.get(labels["exit"])
    gate(exit_insn is not None and exit_insn[0] == "ldr", "exit hook does not start with ldr")
    draw = by_addr.get(labels["draw"])
    gate(draw is not None and draw[0] == "mov", "draw hook does not start with mov ip, lr")
    lookup = by_addr.get(labels["lookup"])
    gate(lookup is not None and lookup[0] == "push", "lookup does not start with push")
