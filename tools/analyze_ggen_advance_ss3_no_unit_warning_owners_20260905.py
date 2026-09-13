#!/usr/bin/env python3
"""Find ROM owners of the ss3 no-unit warning live OBJ tiles."""
from __future__ import annotations

import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path

import analyze_ggen_advance_develop_menu_buttons_state_20260901 as analysis
import analyze_ggen_advance_remaining_ui_states_20260902 as ui
import analyze_ggen_advance_settings_suspend_ui as sprite
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM

STATE = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss3"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_ss3_no_unit_warning_owners_20260905.json"
ROM_BASE = 0x08000000


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def obj_tile(vram, tid):
    return bytes(vram[0x10000 + tid * 32 : 0x10000 + tid * 32 + 32])


def header(rom, address):
    off = address - ROM_BASE
    if off < 0 or off + 0x14 > len(rom):
        return None
    kind = u32(rom, off)
    pal_n = u32(rom, off + 4)
    gfx_rel = u32(rom, off + 8)
    pal_rel = u32(rom, off + 0xC)
    anim_n = u32(rom, off + 0x10)
    if kind != 0 or pal_n not in (1, 2, 4, 6, 8, 16) or anim_n < 1 or anim_n > 64:
        return None
    if gfx_rel < 0x14 or pal_rel <= gfx_rel or (pal_rel - gfx_rel) % 32:
        return None
    size = pal_rel + pal_n * 32
    if off + size > len(rom):
        return None
    return {
        "address": address,
        "palettes": pal_n,
        "anims": anim_n,
        "tiles": (pal_rel - gfx_rel) // 32,
        "gfx_rel": gfx_rel,
        "pal_rel": pal_rel,
        "size": size,
        "graphics": rom[off + gfx_rel : off + pal_rel],
    }


def main():
    rom = MAIN_TIP_ROM.read_bytes()
    jp = ORIGINAL_ROM.read_bytes()
    st, _ = statefmt.parse_png_state(STATE)
    io = st[statefmt.STATE_IO : statefmt.STATE_PALETTE]
    dispcnt = u16(io, 0)
    vram = st[statefmt.STATE_VRAM : statefmt.STATE_IWRAM]
    oam = ui.visible_oam(st)
    popup = [row for row in oam if row["palette_bank"] == 12]
    text = [row for row in popup if row["width"] == 64 and row["height"] == 32]
    live = []
    for row in popup:
        tw, th = row["width"] // 8, row["height"] // 8
        for ty in range(th):
            for tx in range(tw):
                tid = row["tile"] + ty * tw + tx
                live.append((tid, obj_tile(vram, tid), row["index"], tx, ty))

    # unique non-empty tiles from text plane
    text_tiles = []
    for row in text:
        tw, th = row["width"] // 8, row["height"] // 8
        for ty in range(th):
            for tx in range(tw):
                raw = obj_tile(vram, row["tile"] + ty * tw + tx)
                if raw != b"\x00" * 32:
                    text_tiles.append((row["index"], tx, ty, raw, hashlib.sha256(raw).hexdigest()[:12]))

    probes = text_tiles[:: max(1, len(text_tiles) // 8)][:8]
    if not probes:
        probes = [(t[2], 0, 0, t[1], hashlib.sha256(t[1]).hexdigest()[:12]) for t in live[40:48]]

    # ROM scan for first distinctive tile
    distinctive = None
    for item in text_tiles:
        # skip mostly-fill tiles: few unique nibbles
        vals = set()
        for b in item[3]:
            vals.add(b & 15)
            vals.add(b >> 4)
        if len(vals) >= 4:
            distinctive = item
            break
    if distinctive is None and text_tiles:
        distinctive = text_tiles[len(text_tiles) // 2]

    hits_low = []
    hits_exp = []
    needle = distinctive[3] if distinctive else None
    if needle:
        cursor = 0
        while True:
            found = rom.find(needle, cursor)
            if found < 0:
                break
            (hits_low if found < 0x01000000 else hits_exp).append(found)
            cursor = found + 1
            if len(hits_low) + len(hits_exp) > 40:
                break

    slot_matches = []
    for slot in ui.sprite_slots(st):
        ptr = int(slot["resource"], 16)
        info = header(rom, ptr)
        if not info:
            slot_matches.append({**slot, "header": "unparsed"})
            continue
        gfx = info["graphics"]
        n = info["tiles"]
        hits = 0
        for _tid, raw, *_rest in live:
            for sid in range(n):
                if gfx[sid * 32 : (sid + 1) * 32] == raw:
                    hits += 1
                    break
        slot_matches.append({
            **slot,
            "tiles": n,
            "anims": info["anims"],
            "palettes": info["palettes"],
            "live_hits": hits,
            "live_total": len(live),
        })

        # anim geom
        try:
            _g, records = sprite.animation_records(rom, ptr)
            anim_info = parse_anim_counts(records)
        except Exception as exc:
            anim_info = {"error": str(exc)}
        slot_matches[-1]["anim_objects"] = anim_info

    # also scan original C64140 and CD9250 etc
    extras = [0x08C64140, 0x08CD9250, 0x08429D94, 0x08C7504C, 0x09274000, 0x09298000, 0x09284000, 0x08C5D5F0, 0x092C0000]
    extra_rows = []
    for addr in extras:
        info = header(rom if addr >= 0x09000000 else (rom if addr - ROM_BASE < len(rom) else jp), addr)
        # always from main ROM if present
        info = header(rom, addr)
        if not info:
            extra_rows.append({"address": f"0x{addr:08X}", "missing": True})
            continue
        gfx = info["graphics"]
        n = info["tiles"]
        hits = sum(any(gfx[sid * 32:(sid+1)*32] == raw for sid in range(n)) for _t, raw, *_ in live)
        extra_rows.append({"address": f"0x{addr:08X}", "tiles": n, "anims": info["anims"], "hits": hits})

    report = {
        "dispcnt": hex(dispcnt),
        "obj_1d": bool(dispcnt & 0x40),
        "obj_enable": bool(dispcnt & 0x1000),
        "live_tiles": len(live),
        "text_nonempty": len(text_tiles),
        "distinctive": None if distinctive is None else {
            "oam": distinctive[0], "tx": distinctive[1], "ty": distinctive[2],
            "sha": distinctive[4], "nibble_set": sorted({*(b & 15 for b in distinctive[3]), *(b >> 4 for b in distinctive[3])}),
        },
        "rom_hits_low": [hex(x) for x in hits_low],
        "rom_hits_exp": [hex(x) for x in hits_exp],
        "slot_matches": slot_matches,
        "extra": extra_rows,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def parse_anim_counts(records):
    rows = []
    for i, (_s, rec) in enumerate(records):
        marker = analysis.find_marker(rec)
        if marker is None:
            rows.append({"anim": i, "error": "no marker", "len": len(rec)})
            continue
        try:
            parsed = sprite.parse_animation_oam(rec[marker:])
        except Exception as exc:
            rows.append({"anim": i, "error": str(exc), "len": len(rec)})
            continue
        rows.append({
            "anim": i,
            "objects": parsed["object_count"],
            "sizes": [o["size_px"] for o in parsed["objects"]],
            "xy": [[o["x"], o["y"]] for o in parsed["objects"]],
            "tile_starts": [o["tile_start"] for o in parsed["objects"]],
            "banks": [o["palette_bank"] for o in parsed["objects"]],
        })
    return rows


if __name__ == "__main__":
    main()
