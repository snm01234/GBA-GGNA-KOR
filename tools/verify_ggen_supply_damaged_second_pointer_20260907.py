"""Independent checks that both (216,72) supply-status owners draw 파손중."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import build_ggen_advance_owned_count_ab_candidates_20260903 as ab
import build_ggen_supply_damaged_second_pointer_20260907 as b
from ggen_advance_text_codec import DICT_8X16_BASE, DICT_8X16_END, load_dictionary


def main() -> None:
    manifest = json.loads((b.OUT / "manifest.json").read_text(encoding="utf-8"))
    parent = b.MAIN_TIP_ROM.read_bytes()
    rom = (b.ROOT / manifest["output"]["path"]).read_bytes()
    jp = b.ORIGINAL_ROM.read_bytes()
    merged = json.loads(b.TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    row = next(r for r in merged["records"] if r["record_id"] == b.RID)
    b.gate(b.sha256(parent) == manifest["parent"]["sha256"], "parent hash drift")
    b.gate(b.sha256(rom) == manifest["output"]["sha256"], "candidate hash drift")
    b.gate(row["owner_ids"] == ["OWNER-U32-0006DF1C", "OWNER-U32-0006DF98"], "sheet owners incomplete")
    b.gate(any(o["owner_id"] == "OWNER-U32-0006DF98" for o in merged["owners"]), "sheet owner row missing")
    dic = load_dictionary(jp, DICT_8X16_BASE, DICT_8X16_END)
    font = b.glyph.load_galmuri8()
    b.gate(b.u32(rom, b.FIRST) == b.KO_ADDR and b.u32(rom, b.SECOND) == b.KO_ADDR, "live owners diverged")
    b.gate(ab.thumb_bl_target(rom, 0x0806DF14) == 0x08000F54, "F54 BL drift")
    b.gate(ab.thumb_bl_target(rom, 0x0806DF90) == 0x08000648, "0648 BL drift")
    for owner in (b.FIRST, b.SECOND):
        slots, _ = b.decode(rom, b.u32(rom, owner), dic)
        b.gate(b.glyphs_match(rom, slots, b.TEXT, font), f"0x{owner:X} glyphs")
    b.gate(rom[b.ORIGIN : b.ORIGIN + 7] == bytes.fromhex("E3DFE331E36200"), "source stream mutated")
    origin_ptr = struct.pack("<I", 0x08000000 + b.ORIGIN)
    remain = []
    pos = 0
    while True:
        pos = rom.find(origin_ptr, pos)
        if pos < 0:
            break
        if pos % 4 == 0:
            remain.append(pos)
        pos += 1
    b.gate(not remain, f"origin pointer remains: {[hex(x) for x in remain]}")
    b.gate(rom[0xC5700:0xC5A00] == parent[0xC5700:0xC5A00], "소유수 overlay stub mutated")
    changed = [i for i, (a, c) in enumerate(zip(parent, rom)) if a != c]
    b.gate(changed == list(range(b.SECOND, b.SECOND + 4)), "unexpected ROM delta")
    print("PASS: both supply (216,72) owners point at 8x16 파손중; 0648 literal was the missed live consumer.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
