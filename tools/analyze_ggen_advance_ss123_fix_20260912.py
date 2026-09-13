#!/usr/bin/env python3
"""Locate ss1 ジオン海兵, ss2 NT00, and ss3 Bio Field tile owners."""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import analyze_ggen_advance_unit_list_sprite_state_20260830 as statefmt  # noqa: E402
import build_ggen_advance_turn_ability_overlays_20260905 as ability  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from build_ggen_advance_unified_rom_poc import (  # noqa: E402
    CHARMAP_8X16_PATH,
    CHARMAP_12X12_PATH,
    load_identified_slot_to_char,
    tokens_from_bytes,
)
from ggen_advance_project_paths import MAIN_TIP_ROM, ORIGINAL_ROM, TRANSLATION_MERGED_JSON
from ggen_advance_text_codec import (  # noqa: E402
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
)

OUT = ROOT / "analysis" / "ggen_advance_ss123_fix_20260912.json"
SS = {
    "ss1": ROOT / "SD Gundam GGeneration Advance (Korean).ss1",
    "ss2": ROOT / "SD Gundam GGeneration Advance (Korean).ss2",
    "ss3": ROOT / "SD Gundam GGeneration Advance (Korean).ss3",
}


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_slots(slots, charmap) -> str:
    chars = []
    for slot in slots:
        char = charmap.get(slot)
        chars.append(char if char is not None else f"<{slot:04X}>")
    return "".join(chars)


def decode_raw(raw: bytes, dictionary, charmap) -> str:
    return decode_slots(expand_to_slots(tokens_from_bytes(raw), dictionary), charmap)


def payload_at(rom: bytes, address: int) -> bytes | None:
    offset = address - ROM_BASE
    if not 0 <= offset < len(rom):
        return None
    end = rom.find(0, offset, min(len(rom), offset + 0x120))
    if end < 0:
        return None
    return bytes(rom[offset : end + 1])


def owner_offsets(row: dict) -> list[int]:
    return [
        int(str(owner_id).removeprefix("OWNER-U32-"), 16)
        for owner_id in row.get("owner_ids") or []
        if str(owner_id).startswith("OWNER-U32-")
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dict8_jp = load_dictionary(japan, DICT_8X16_BASE, DICT_8X16_END)
    dict8 = load_dictionary(rom, DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(rom, DICT_12X12_BASE, DICT_12X12_END)
    map8_jp = load_identified_slot_to_char(CHARMAP_8X16_PATH)
    map12_jp = load_identified_slot_to_char(CHARMAP_12X12_PATH)
    map8 = {**map8_jp, **f2.hangul_slot_map(rom, mode=8)}
    map12 = {**map12_jp, **f2.hangul_slot_map(rom, mode=12)}

    # Dictionary entries containing 海/兵/ジオン海兵-like text.
    dict_hits = []
    for idx, slots in enumerate(dict8_jp):
        text = decode_slots(slots, map8_jp)
        live_text = decode_slots(slots, map8)
        if any(part in text for part in ("海", "兵", "ジオン")):
            dict_hits.append({"dict8": idx, "text": text, "live": live_text, "slots": [f"0x{s:04X}" for s in slots]})

    name_hits = []
    nt00_hits = []
    bio_text_hits = []
    for row in merged["records"]:
        source = str(row.get("source_text") or "")
        ko = str(row.get("translation_ko") or "")
        cat = str(row.get("semantic_category") or "")
        if "海兵" in source or "海兵" in ko or "해병" in ko:
            live = []
            for owner in owner_offsets(row):
                ptr = u32(rom, owner)
                payload = payload_at(rom, ptr)
                live.append(
                    {
                        "owner": f"0x{owner:08X}",
                        "ptr": f"0x{ptr:08X}",
                        "ko8": decode_raw(payload, dict8, map8) if payload else None,
                        "jp8": decode_raw(payload, dict8_jp, map8_jp) if payload else None,
                    }
                )
            name_hits.append(
                {
                    "record_id": row.get("record_id"),
                    "cat": cat,
                    "source": source,
                    "ko": ko,
                    "status": row.get("translation_status"),
                    "raw_hex": row.get("raw_hex"),
                    "owners": live,
                    "families": row.get("source_families"),
                }
            )
        if "NT00" in source or "NT00" in ko or "NT-001" in source or "NT-001" in ko or "NT001" in ko:
            nt00_hits.append(
                {
                    "record_id": row.get("record_id"),
                    "cat": cat,
                    "source": source,
                    "ko": ko,
                    "status": row.get("translation_status"),
                    "screen": row.get("screen_class"),
                    "width": len(ko.replace("\n", "")),
                    "segments": row.get("translation_segments") or [],
                }
            )
        if "バイオフィールド" in source or "바이오필드" in ko.replace(" ", "") or "바이오 필드" in ko:
            bio_text_hits.append(
                {
                    "record_id": row.get("record_id"),
                    "cat": cat,
                    "source": source,
                    "ko": ko,
                    "status": row.get("translation_status"),
                    "raw_hex": row.get("raw_hex"),
                    "owners": row.get("owner_ids"),
                    "families": row.get("source_families"),
                }
            )

    # Scan live unit-name payloads for leftover Japanese 海兵 / ジオン海兵.
    leftover_unit = []
    for row in merged["records"]:
        cat = str(row.get("semantic_category") or "")
        if cat not in {"unit_name", "unit_name_alternate", "character_name", "character_name_alternate"}:
            continue
        for owner in owner_offsets(row):
            ptr = u32(rom, owner)
            payload = payload_at(rom, ptr)
            if not payload:
                continue
            live_ko = decode_raw(payload, dict8, map8)
            live_jp = decode_raw(payload, dict8_jp, map8_jp)
            if any(mark in live_jp for mark in ("海兵", "ジオン海兵")) or any(mark in live_ko for mark in ("海兵", "ジオン")):
                leftover_unit.append(
                    {
                        "record_id": row.get("record_id"),
                        "cat": cat,
                        "source": row.get("source_text"),
                        "sheet_ko": row.get("translation_ko"),
                        "status": row.get("translation_status"),
                        "owner": f"0x{owner:08X}",
                        "ptr": f"0x{ptr:08X}",
                        "live_ko": live_ko,
                        "live_jp": live_jp,
                        "raw": payload.hex(" ").upper(),
                    }
                )

    # Ability resource vs ss3 live OBJ tiles.
    parent = rom
    abil_hdr, abil_src = ability.resource_blob(parent, ability.ABILITY_SOURCE)
    live_ptr = u32(parent, ability.ABILITY_POINTER)
    abil_live_off = live_ptr - ROM_BASE
    live_hdr, live_src = ability.resource_blob(parent, live_ptr)
    records = ability.animation_records(bytes(abil_src), abil_hdr)
    live_records = ability.animation_records(bytes(live_src), live_hdr)
    runs = ability.consecutive_id_runs(records, abil_hdr["tiles"])
    labels = []
    for (start, count), (jp, ko) in zip(runs, ability.ABILITY_RUN_LABELS):
        ids = ability.extend_run(records, abil_hdr["tiles"], start, count)
        labels.append({"jp": jp, "ko": ko, "start": start, "count": count, "ids": ids})

    ss3, _ = statefmt.parse_png_state(SS["ss3"])
    obj_base = statefmt.STATE_VRAM + statefmt.OBJ_VRAM
    obj_vram = ss3[obj_base : obj_base + 0x8000]
    live_gfx = live_src[live_hdr["gfx_rel"] : live_hdr["pal_rel"]]
    orig_gfx = abil_src[abil_hdr["gfx_rel"] : abil_hdr["pal_rel"]]
    tile_hits = defaultdict(list)
    for tile_id in range(live_hdr["tiles"]):
        src = live_gfx[tile_id * 32 : (tile_id + 1) * 32]
        if src == b"\0" * 32:
            continue
        for dest in range(0, len(obj_vram), 32):
            if obj_vram[dest : dest + 32] == src:
                tile_hits[tile_id].append(dest // 32)

    # Reconstruct all animation ID streams that mention tiles currently in OBJ VRAM.
    live_tile_set = set(tile_hits)
    matching_anims = []
    for index, blob in enumerate(live_records):
        values = list(struct.unpack_from(f"<{len(blob) // 2}H", blob))
        ids = [v for v in values if 0 <= v < live_hdr["tiles"]]
        overlap = [v for v in ids if v in live_tile_set]
        if len(overlap) >= 4:
            matching_anims.append(
                {
                    "anim": index,
                    "id_count": len(ids),
                    "overlap": overlap,
                    "ids_sample": ids[:40],
                }
            )

    ifield = next(row for row in labels if row["jp"] == "Iフィールド")
    report = {
        "ability_pointer": {"literal": hex(ability.ABILITY_SOURCE), "live": hex(live_ptr)},
        "ability_tiles": live_hdr["tiles"],
        "ability_runs": labels,
        "ss3_obj_tile_hits": {str(k): v[:8] for k, v in sorted(tile_hits.items())},
        "ss3_matching_anims": matching_anims[:20],
        "ifield_ids": ifield["ids"],
        "dict8_hits": dict_hits[:80],
        "name_hits": name_hits,
        "leftover_unit": leftover_unit,
        "nt00_hits": nt00_hits,
        "bio_text_hits": bio_text_hits,
        "nt00_width_candidates": {
            "나는 NT00…… 아니": len("나는 NT00…… 아니"),
            "나는 NT-001…… 아니": len("나는 NT-001…… 아니"),
            "나는 NT001…… 아니": len("나는 NT001…… 아니"),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(
        {
            "name_hits": len(name_hits),
            "leftover_unit": leftover_unit,
            "nt00": [h for h in nt00_hits if "NT00" in h["source"] or "NT00" in h["ko"]],
            "bio_text": bio_text_hits,
            "ss3_tiles": sorted(tile_hits),
            "ss3_anims": matching_anims[:12],
            "ifield_ids": ifield["ids"],
            "dict_sea_or_marine": [h for h in dict_hits if "海" in h["text"] or "兵" in h["text"]],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
