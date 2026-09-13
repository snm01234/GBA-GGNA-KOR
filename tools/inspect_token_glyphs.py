#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

FONT_8X16 = 0x00094028


def glyph_slot(token: int) -> int:
    if 1 <= token <= 0xDF:
        return token
    if 0xE000 <= token <= 0xEFFF:
        return (token + 0x20E0) & 0xFFFF
    raise ValueError(f"token 0x{token:04X} is not a literal glyph token")


def decode_rows(data: bytes, token: int) -> list[str]:
    slot = glyph_slot(token)
    raw = data[FONT_8X16 + slot * 32 : FONT_8X16 + (slot + 1) * 32]
    if len(raw) != 32:
        raise ValueError(f"glyph slot 0x{slot:04X} is outside the 8x16 font")
    rows: list[str] = []
    for y in range(16):
        row = ""
        for half in range(2):
            value = raw[y * 2 + half]
            for _ in range(4):
                row += "##" if value & 0x03 else "  "
                value >>= 2
        rows.append(row)
    return rows


def parse_token(text: str) -> int:
    return int(text, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render selected G Generation Advance literal tokens as 8x16 ASCII glyphs.")
    parser.add_argument("rom", type=Path)
    parser.add_argument("tokens", nargs="+", type=parse_token)
    args = parser.parse_args()

    data = args.rom.read_bytes()
    for token in args.tokens:
        slot = glyph_slot(token)
        print(f"TOKEN 0x{token:04X} SLOT 0x{slot:04X}")
        print("\n".join(decode_rows(data, token)))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
