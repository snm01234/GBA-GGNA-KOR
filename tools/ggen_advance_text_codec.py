#!/usr/bin/env python3
"""Advance-local G Generation Advance text token/dictionary codec helpers."""
from __future__ import annotations

import struct

ROM_BASE = 0x08000000
DICT_8X16_BASE = 0x000A42A8
DICT_8X16_END = 0x000A4A2C
DICT_12X12_BASE = 0x00093850
DICT_12X12_END = 0x00093FD8
DICT_COUNT = 319
MAX_LITERAL_TOKEN = 0xE733
MAX_DICTIONARY_TOKEN = 0xF000 + DICT_COUNT - 1


def read_tokens(data: bytes, offset: int, limit: int = 4096) -> tuple[list[int], bytes]:
    if not 0 <= offset < len(data):
        raise ValueError(f"target outside ROM: 0x{offset:08X}")
    cursor = offset
    tokens: list[int] = []
    while cursor - offset < limit:
        if cursor >= len(data):
            raise ValueError(f"unterminated stream at 0x{offset:08X}")
        lead = data[cursor]
        cursor += 1
        if lead == 0:
            return tokens, data[offset:cursor]
        if lead <= 0xDF:
            tokens.append(lead)
            continue
        if cursor >= len(data):
            raise ValueError(f"truncated token at 0x{cursor-1:08X}")
        tokens.append((lead << 8) | data[cursor])
        cursor += 1
    raise ValueError(f"token stream exceeds {limit} bytes at 0x{offset:08X}")


def validate_tokens(tokens: list[int]) -> None:
    for token in tokens:
        if 0 < token <= 0xDF:
            continue
        if 0xE000 <= token <= MAX_LITERAL_TOKEN:
            continue
        if 0xF000 <= token <= MAX_DICTIONARY_TOKEN:
            continue
        raise ValueError(f"token outside renderer-valid range: 0x{token:04X}")


def read_tokens_strict(data: bytes, offset: int, limit: int = 4096) -> tuple[list[int], bytes]:
    tokens, raw = read_tokens(data, offset, limit=limit)
    validate_tokens(tokens)
    return tokens, raw


def encode_tokens(tokens: list[int]) -> bytes:
    out = bytearray()
    for token in tokens:
        if not 0 < token <= 0xFFFF:
            raise ValueError(f"invalid token 0x{token:X}")
        if token <= 0xDF:
            out.append(token)
        else:
            lead, tail = token >> 8, token & 0xFF
            if lead < 0xE0:
                raise ValueError(f"noncanonical two-byte token 0x{token:04X}")
            out.extend((lead, tail))
    out.append(0)
    return bytes(out)


def token_label(token: int) -> str:
    return f"{token:02X}" if token <= 0xDF else f"{token:04X}"


def token_kind(token: int) -> str:
    if token <= 0xDF:
        return "single_byte"
    if 0xE000 <= token <= 0xEFFF:
        return "literal_extended"
    if 0xF000 <= token <= 0xFFFF:
        return "dictionary"
    return "two_byte_other"


def load_dictionary(data: bytes, base: int, end: int) -> list[list[int]]:
    entries: list[list[int]] = []
    for index in range(DICT_COUNT):
        rel = struct.unpack_from("<H", data, base + index * 2)[0]
        target = base + rel
        if not base <= target < end:
            raise ValueError(f"dictionary entry {index} target outside dictionary")
        tokens, _raw = read_tokens(data, target, limit=end - target)
        entries.append(tokens)
    return entries


def normalized_slot(token: int) -> int:
    if token <= 0xDF:
        return token
    if 0xE000 <= token <= 0xEFFF:
        return (token + 0x20E0) & 0xFFFF
    raise ValueError(f"not a literal glyph token: 0x{token:04X}")


def expand_to_slots(tokens: list[int], dictionary: list[list[int]], depth: int = 0) -> list[int]:
    if depth > 8:
        raise ValueError("dictionary recursion depth exceeded")
    out: list[int] = []
    for token in tokens:
        if 0xF000 <= token < 0xF000 + len(dictionary):
            out.extend(expand_to_slots(dictionary[token - 0xF000], dictionary, depth + 1))
        else:
            out.append(normalized_slot(token))
    return out
