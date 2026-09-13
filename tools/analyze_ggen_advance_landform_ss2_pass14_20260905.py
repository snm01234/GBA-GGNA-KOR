#!/usr/bin/env python3
"""Bind LANDFORM 海 to a 12x12 draw source and list sibling terrain names."""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import analyze_ggen_advance_remaining_ui_draw_calls_20260902 as draw
import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt
from ggen_advance_project_paths import ADVANCE_ROOT, MAIN_TIP_ROM, ORIGINAL_ROM
from ggen_advance_text_codec import (
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)

CHARMAP12 = ADVANCE_ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
OUT = ADVANCE_ROOT / "analysis" / "ggen_advance_landform_ss2_pass14_20260905.json"
ROM_BASE = 0x08000000
SEA_SLOT = 0x01C1
SEA_TOKEN = 0xDF20 + SEA_SLOT  # 0xE0E1


def u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def decode_stream(rom, charmap, dict12, off, limit=24):
    if not (0 <= off < len(rom) - 1):
        return None
    try:
        tokens, raw = read_tokens(rom, off, limit=limit)
        if not (1 <= len(raw) <= 24):
            return None
        slots = expand_to_slots(tokens, dict12)
        if not (1 <= len(slots) <= 8):
            return None
        text = "".join(charmap.get(s, f"<{s:04X}>") for s in slots)
        return {"text": text, "raw": raw.hex(), "slots": [hex(s) for s in slots], "offset": hex(off)}
    except Exception:
        return None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    japan = ORIGINAL_ROM.read_bytes()
    rom = MAIN_TIP_ROM.read_bytes()
    charmap = {int(k, 16): v for k, v in json.loads(CHARMAP12.read_text(encoding="utf-8"))["verified_charmap"].items()}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    terrain_chars = set("海砂森林街山空宙地上漠市月面宇宙砂漠森林市街山岳月面空中水中海上平地基地")

    calls = draw.draw_calls(japan)
    xy_hits = []
    r3_terrain = []
    r3_sea = []
    for call in calls:
        cx, cy = call.get("x_r1"), call.get("y_r2")
        if cx is not None and cy is not None:
            for tx, ty in ((101, 74), (45, 18), (100, 74), (96, 72), (104, 72), (88, 72), (72, 72)):
                if abs(cx - tx) + abs(cy - ty) <= 8:
                    xy_hits.append({**{k: call[k] for k in ("call", "call_file_offset", "renderer", "x_r1", "y_r2", "r3_literal_value")}, "want": [tx, ty]})
                    break
        val = call.get("r3_literal_value")
        if not val:
            continue
        if not (ROM_BASE <= val < ROM_BASE + 0x01000000):
            continue
        decoded = decode_stream(japan, charmap, dict12, val - ROM_BASE)
        if not decoded:
            continue
        if "海" in decoded["text"] or SEA_SLOT in [int(s, 16) for s in decoded["slots"]]:
            r3_sea.append({**decoded, "call": hex(call["call"]), "x": cx, "y": cy, "renderer": call["renderer"]})
        if any(ch in terrain_chars for ch in decoded["text"]) and len(decoded["text"]) <= 4:
            r3_terrain.append({**decoded, "call": hex(call["call"]), "x": cx, "y": cy, "renderer": call["renderer"]})

    # Isolated E0E1 00 and following C-strings
    sea_payloads = []
    start = 0
    while len(sea_payloads) < 24:
        pos = japan.find(bytes.fromhex("E0 E1 00"), start)
        if pos < 0:
            break
        decoded = decode_stream(japan, charmap, dict12, pos)
        neighbors = []
        cursor = pos + (len(bytes.fromhex(decoded["raw"])) if decoded else 3)
        for _ in range(8):
            nxt = decode_stream(japan, charmap, dict12, cursor)
            if not nxt:
                break
            neighbors.append(nxt)
            cursor = int(nxt["offset"], 16) + len(bytes.fromhex(nxt["raw"]))
        sea_payloads.append({"offset": hex(pos), "decoded": decoded, "neighbors": neighbors[:8], "before": japan[max(0, pos - 8) : pos].hex()})
        start = pos + 1

    # Compact non-sequential u16 slot tables containing 海
    compact = []
    pos = 0
    data = japan[:0x01000000]
    while pos < len(data) - 4:
        hit = data.find(b"\xc1\x01", pos)
        if hit < 0 or hit % 2:
            pos = hit + 1 if hit >= 0 else len(data)
            if hit < 0:
                break
            continue
        for n in (6, 8, 10, 12, 16):
            for base in (hit - 2 * i for i in range(n)):
                if base < 0 or base + n * 2 > len(data) or base % 2:
                    continue
                values = [u16(data, base + i * 2) for i in range(n)]
                if SEA_SLOT not in values:
                    continue
                consec = sum(1 for i in range(n - 1) if values[i + 1] == values[i] + 1)
                if consec >= n // 2:
                    continue
                named = [(i, hex(values[i]), charmap.get(values[i])) for i in range(n) if charmap.get(values[i])]
                if len(named) < 4:
                    continue
                texts = [ch for _, _, ch in named if ch]
                if not any(ch in terrain_chars for ch in texts):
                    continue
                compact.append({"base": hex(base), "n": n, "named": named, "values": [hex(v) for v in values]})
        pos = hit + 2
        if len(compact) >= 24:
            break

    # Sequential 12x12 C-string pools that include 海
    pools = []
    for row in sea_payloads:
        texts = []
        if row["decoded"]:
            texts.append(row["decoded"]["text"])
        texts.extend(n["text"] for n in row["neighbors"])
        if len(texts) >= 4 and any("海" in t for t in texts):
            pools.append({"offset": row["offset"], "texts": texts})

    # Known 2-kanji terrain payloads
    pairs = {
        "宇宙": bytes.fromhex("E1 9C E2 BC 00"),
        "地上": bytes.fromhex("E4 03 BE 00"),
        "森林": bytes.fromhex("E3 2A E5 DE 00"),
        "市街": bytes.fromhex("E2 78 E0 EC 00"),
        "月面": bytes.fromhex("E1 C3 E5 82 00"),
        "空中": bytes.fromhex("E1 9C") + bytes([charmap and 0]) ,  # placeholder, filled below
    }
    # 空=0x027C → E19C, 中 needs lookup
    chuu = [slot for slot, ch in charmap.items() if ch == "中"]
    if chuu:
        token = chuu[0] if chuu[0] <= 0xDF else 0xDF20 + chuu[0]
        if token <= 0xDF:
            pairs["空中"] = bytes.fromhex("E1 9C") + bytes([token, 0])
        else:
            pairs["空中"] = bytes.fromhex("E19C") + bytes([token >> 8, token & 0xFF, 0])
    pair_hits = {}
    for name, needle in pairs.items():
        if not needle or needle.endswith(b"\x00\x00"):
            continue
        found = []
        start = 0
        while len(found) < 6:
            h = japan.find(needle, start)
            if h < 0:
                break
            found.append(hex(h))
            start = h + 1
        pair_hits[name] = found

    # Cave high-water in current main
    cave_probe = []
    for off in range(0x01304000, 0x01306000, 0x40):
        chunk = rom[off : off + 0x40]
        cave_probe.append({"off": hex(off), "nonzero": sum(1 for b in chunk if b), "head": chunk[:8].hex()})

    cpu = statefmt.parse_png_state(ADVANCE_ROOT / "SD Gundam GGeneration Advance (Korean).ss2")[0][:64]

    report = {
        "xy_hits": [
            {k: (hex(v) if k in {"call", "r3_literal_value"} and isinstance(v, int) else v) for k, v in row.items()}
            for row in xy_hits
        ],
        "r3_sea": r3_sea,
        "r3_terrain": r3_terrain[:40],
        "sea_payloads": sea_payloads,
        "compact_slot_tables": compact,
        "string_pools": pools,
        "pair_hits": pair_hits,
        "cave_probe": cave_probe,
        "cpu_head": cpu.hex(),
        "call_count": len(calls),
        "중_slots": [hex(s) for s in chuu],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("xy", json.dumps(report["xy_hits"], ensure_ascii=False, indent=2)[:2000])
    print("r3_sea", json.dumps(r3_sea, ensure_ascii=False, indent=2)[:2000])
    print("r3_terrain_n", len(r3_terrain), "sample", json.dumps(r3_terrain[:12], ensure_ascii=False)[:2000])
    print("pools", json.dumps(pools, ensure_ascii=False, indent=2)[:2000])
    print("compact", json.dumps(compact[:8], ensure_ascii=False, indent=2)[:2000])
    print("pairs", json.dumps(pair_hits, ensure_ascii=False))
    print("cave first empty", next((r for r in cave_probe if r["nonzero"] == 0), None))
    print("calls", len(calls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
