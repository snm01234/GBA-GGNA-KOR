#!/usr/bin/env python3
"""Relocate the 37-entry in-battle cut-in quote table to Korean streams.

ID-command barks (256x3 at 0x00226984) are already Korean.  Battle cut-ins
read a separate pointer table at 0x00228600 whose payloads still sit in the
original Japanese pool 0x00228184-0x00228600.  This builder leaves that pool
byte-exact, rebuilds each container in a 32 MiB cave, and rewrites only the
37 table pointers.

Korean text is the existing map-script / ID-bark translation for the same
raw 12x12 stream.  The 12x12 ν cell is restored from the already-verified
nu-slot candidate so Amuro's line does not show 꺄 again.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from extract_ggen_advance_id_command_battle_barks import (  # noqa: E402
    load_slot_map,
    read_decoded_stream,
)
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT12_RELOCATED,
    load_galmuri12,
    packed_12x12,
    recover_unique_12x12_slots,
    slot_raw,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, load_dictionary  # noqa: E402

ROM_BASE = 0x08000000
TABLE = 0x00228600
PAYLOAD_LO = 0x00228184
CAVE_START = 0x012A2000
CAVE_END = 0x012A6000
IDBARK_PATH = ROOT / "integrated" / "translation" / "ggen_advance_id_command_battle_barks.json"
NU_ROM = (
    ROOT
    / "outputs"
    / "20260905_ggen_advance_nu_slot_battle_bark"
    / "ggen_advance_nu_slot_battle_bark_candidate_20260905.gba"
)
NU_MANIFEST = ROOT / "analysis" / "ggen_advance_nu_slot_battle_bark_candidate_20260905.json"
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
CORR = ROOT / "analysis" / "ggen_advance_12x12_runtime_measurement_corrections_20260829.json"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_battle_cutin_quotes"
OUT_ROM = OUT_DIR / "ggen_advance_battle_cutin_quotes_ko_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_battle_cutin_quotes_ko_candidate_20260905.sav"
OUT_MANIFEST = ROOT / "analysis" / "ggen_advance_battle_cutin_quotes_ko_candidate_20260905.json"
OUT_OVERLAY = ROOT / "integrated" / "translation" / "ggen_advance_battle_cutin_quotes.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
ALLCLEAR_SAV = ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.sav"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def norm_hex(value: str) -> str:
    return bytes.fromhex(value.replace(" ", "")).hex().upper()


def parse_blocks(data: bytes, start: int, boundary: int, dictionary, map12) -> dict[str, Any]:
    cursor = start
    blocks: list[dict[str, Any]] = []
    streams: list[dict[str, Any]] = []
    while cursor < boundary:
        if cursor + 6 > boundary or data[cursor : cursor + 2] != b"\x00\x05":
            break
        speaker = data[cursor + 2]
        gate(data[cursor + 3 : cursor + 5] == b"\x00\x06", f"cut-in header drift at 0x{cursor:08X}")
        portrait = data[cursor + 5]
        header_at = cursor
        cursor += 6
        block_streams = []
        while cursor < boundary:
            stream = read_decoded_stream(data, cursor, boundary, dictionary, map12)
            row = {
                "start_file_offset": stream["start_file_offset"],
                "source_text": stream["source_text"],
                "raw_hex": stream["raw_hex"],
                "raw_byte_length": stream["raw_byte_length"],
            }
            block_streams.append(row)
            streams.append(row)
            cursor += stream["raw_byte_length"]
            if cursor >= boundary or data[cursor] != 0x03:
                break
            cursor += 1
            if cursor + 1 < boundary and data[cursor] == 0x00 and data[cursor + 1] in (0x01, 0x02):
                break
        terminal = None
        if cursor + 1 < boundary and data[cursor] == 0x00:
            terminal = data[cursor + 1]
            cursor += 2
        blocks.append(
            {
                "header_file_offset": f"0x{header_at:08X}",
                "speaker_id": f"0x{speaker:02X}",
                "portrait": f"0x{portrait:02X}",
                "streams": block_streams,
                "terminal": None if terminal is None else f"0x{terminal:02X}",
            }
        )
        if terminal != 0x02:
            break
    return {
        "consumed_end": cursor,
        "tail": data[cursor:boundary],
        "blocks": blocks,
        "streams": streams,
    }


def translation_hits_for_raw(
    merged: dict[str, Any],
    idbark: dict[str, Any],
    needed: set[str],
) -> dict[str, tuple[str, str]]:
    collected: dict[str, list[tuple[int, str, str]]] = {key: [] for key in needed}

    def add(raw: str, ko: str, source: str, rank: int) -> None:
        if not raw or not str(ko).strip():
            return
        key = norm_hex(raw)
        if key not in collected:
            return
        collected[key].append((rank, source, str(ko)))

    for row in merged["records"]:
        if row.get("translation_status") != "translated" or row.get("translation_policy") != "translate":
            continue
        segs = list(row.get("segments") or [])
        kos = list(row.get("translation_segments") or [])
        scope = str(row.get("source_scope") or "")
        rank = 0 if scope == "scenario_map_script" else 2
        if len(segs) == len(kos):
            for segment, ko in zip(segs, kos):
                add(str(segment.get("raw_hex") or ""), ko, f"{scope}:{row['record_id']}", rank)
        ko = str(row.get("translation_ko") or "")
        raw = str(row.get("raw_hex") or "")
        source_text = str(row.get("source_text") or "")
        if ko and raw and "\\n" not in source_text and "\n" not in ko:
            add(raw, ko, f"{scope}:{row['record_id']}", rank + 1)
    for row in idbark["records"]:
        if row.get("translation_status") != "translated":
            continue
        add(str(row.get("raw_hex") or ""), str(row.get("translation_ko") or ""), f"idbark:{row['record_id']}", 1)
    chosen: dict[str, tuple[str, str]] = {}
    for key, rows in collected.items():
        gate(rows, f"no translation for stream {key}")
        rows.sort()
        best_rank = rows[0][0]
        best = [(source, ko) for rank, source, ko in rows if rank == best_rank]
        uniq = sorted({ko for _, ko in best})
        gate(len(uniq) == 1, f"conflicting KO for stream {key}: {uniq[:4]}")
        chosen[key] = (uniq[0], best[0][0])
    return chosen


def hangul_chars(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


def verify_hangul_and_nu(rom: bytes | bytearray, payload: bytes, text: str, font12, japan: bytes) -> None:
    index = 0
    seen = 0
    expected = [char for char in text if char != " "]
    while index < len(payload):
        lead = payload[index]
        if lead == 0:
            break
        if lead == 1:
            index += 1
            continue
        if lead >= 0xE0:
            slot = ((lead << 8) | payload[index + 1]) - 0xDF20
            index += 2
        else:
            slot = lead
            index += 1
        gate(seen < len(expected), f"payload longer than text {text!r}")
        char = expected[seen]
        seen += 1
        if "가" <= char <= "힣":
            actual = slot_raw(rom, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
            gate(actual == packed_12x12(char, font12), f"12x12 {char!r} is not painted at 0x{slot:04X}")
        elif char == "ν":
            actual = slot_raw(rom, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
            original = slot_raw(japan, fontops.FONT_12X12_BASE, slot, fontops.FONT_12X12_STRIDE)
            gate(actual == original and slot == 0x0143, "ν payload does not use restored slot 0x0143")
    gate(seen == len(expected), f"payload missing glyphs for {text!r}")


def apply_nu_font(candidate: bytearray, main: bytes, nu: bytes) -> int:
    gate(nu[:0x01000000] == main[:0x01000000], "nu candidate original half drifted from main")
    font_start = FONT12_RELOCATED
    font_end = font_start + fontops.FONT_12X12_COUNT * fontops.FONT_12X12_STRIDE
    changed = 0
    for off in range(font_start, font_end):
        if nu[off] != main[off]:
            candidate[off] = nu[off]
            changed += 1
    gate(changed == 48, f"nu font delta is {changed} bytes, expected 48")
    gate(bytes(candidate[font_start:font_end]) == nu[font_start:font_end], "nu font copy incomplete")
    return changed


def rebuild_container(original: bytes, start: int, parsed: dict[str, Any], replacements: dict[int, bytes]) -> bytes:
    rebuilt = bytearray()
    cursor = 0
    for stream in parsed["streams"]:
        rel = int(stream["start_file_offset"], 16) - start
        raw = bytes.fromhex(str(stream["raw_hex"]).replace(" ", ""))
        gate(original[rel : rel + len(raw)] == raw, f"stream bytes drift at 0x{start + rel:08X}")
        rebuilt.extend(original[cursor:rel])
        rebuilt.extend(replacements[int(stream["start_file_offset"], 16)])
        cursor = rel + len(raw)
    rebuilt.extend(original[cursor:])
    return bytes(rebuilt)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main_rom = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    nu = NU_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    nu_manifest = json.loads(NU_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    idbark = json.loads(IDBARK_PATH.read_text(encoding="utf-8"))
    gate(len(main_rom) == 32 * 1024 * 1024, "main TIP is not 32 MiB")
    gate(sha256(main_rom) == main_manifest["sha256"], "main TIP/manifest drift")
    gate(nu_manifest["base"]["sha256"] == sha256(main_rom), "nu candidate is not based on current main")
    gate(sha256(nu) == nu_manifest["output"]["sha256"], "nu candidate/manifest drift")
    gate(all(value == 0 for value in main_rom[CAVE_START:CAVE_END]), "cut-in cave is not zero-filled")
    gate(main_rom[PAYLOAD_LO:TABLE] == japan[PAYLOAD_LO:TABLE], "cut-in payload pool drifted from Japan")
    gate(main_rom[TABLE : TABLE + 37 * 4] == japan[TABLE : TABLE + 37 * 4], "cut-in table drifted from Japan")

    map12 = load_slot_map(MAP12, CORR)
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)

    ptrs: list[tuple[int, int]] = []
    off = TABLE
    while off + 4 <= len(japan):
        val = u32(japan, off)
        dest = val - ROM_BASE
        if not (PAYLOAD_LO <= dest < TABLE):
            break
        ptrs.append((off, dest))
        off += 4
    gate(len(ptrs) == 37, f"cut-in table count drift: {len(ptrs)}")
    gate(u32(japan, off) == 0x10200000, "cut-in table sentinel drift")

    candidate = bytearray(main_rom)
    nu_font_bytes = apply_nu_font(candidate, main_rom, nu)
    font12 = load_galmuri12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)

    parsed_entries = []
    for i, (src, start) in enumerate(ptrs):
        boundary = ptrs[i + 1][1] if i + 1 < len(ptrs) else TABLE
        parsed = parse_blocks(japan, start, boundary, dictionary, map12)
        original = japan[start:boundary]
        roundtrip = rebuild_container(
            original,
            start,
            parsed,
            {
                int(stream["start_file_offset"], 16): bytes.fromhex(str(stream["raw_hex"]).replace(" ", ""))
                for stream in parsed["streams"]
            },
        )
        gate(roundtrip == original, f"container roundtrip drift at 0x{start:08X}")
        parsed_entries.append((src, start, boundary, original, parsed))

    needed = {
        norm_hex(str(stream["raw_hex"]))
        for _src, _start, _boundary, _original, parsed in parsed_entries
        for stream in parsed["streams"]
    }
    by_raw = translation_hits_for_raw(merged, idbark, needed)
    needed_hangul: set[str] = set()
    for _src, _start, _boundary, _original, parsed in parsed_entries:
        for stream in parsed["streams"]:
            needed_hangul |= hangul_chars(by_raw[norm_hex(str(stream["raw_hex"]))][0])

    recovered = recover_unique_12x12_slots(candidate, font12, needed_hangul)
    counts: Counter[str] = Counter()
    overlay_records: list[dict[str, Any]] = []
    blob = bytearray()
    patches: list[dict[str, Any]] = []
    encode_failed: list[str] = []

    for i, (src, start, boundary, original, parsed) in enumerate(parsed_entries):
        replacements: dict[int, bytes] = {}
        translated_streams = 0
        for stream in parsed["streams"]:
            raw = bytes.fromhex(str(stream["raw_hex"]).replace(" ", ""))
            key = norm_hex(str(stream["raw_hex"]))
            ko, source = by_raw[key]
            jp = str(stream["source_text"])
            stream_off = int(stream["start_file_offset"], 16)
            if jp == ko:
                payload = raw
                status = "kept_original_label"
                counts["kept_original_label"] += 1
            else:
                encoded, missing = unified.encode_korean_text(
                    ko,
                    recovered,
                    verified_charmap=verified12,
                    strict_punctuation=True,
                )
                if encoded is None:
                    encode_failed.extend(missing)
                    counts["encode_failed"] += 1
                    payload = raw
                    status = "encode_failed"
                else:
                    payload = encoded
                    verify_hangul_and_nu(candidate, payload, ko, font12, japan)
                    translated_streams += 1
                    counts["translated_streams"] += 1
                    status = "translated"
            replacements[stream_off] = payload
            overlay_records.append(
                {
                    "record_id": f"GGA-BATTLECUTIN-{stream_off:08X}",
                    "source_scope": "battle_cutin_quote",
                    "container_index": i,
                    "target_file_offset": f"0x{stream_off:08X}",
                    "source_text": jp,
                    "translation_ko": ko,
                    "translation_status": "translated" if status != "encode_failed" else "encode_failed",
                    "translation_source": source,
                    "kept_original_bytes": payload == raw,
                }
            )
        rebuilt = rebuild_container(original, start, parsed, replacements)
        while len(blob) & 3:
            blob.append(0)
        rel = len(blob)
        blob.extend(rebuilt)
        new_addr = ROM_BASE + CAVE_START + rel
        struct.pack_into("<I", candidate, src, new_addr)
        if translated_streams == 0:
            counts["containers_labels_only"] += 1
        counts["containers_patched"] += 1
        patches.append(
            {
                "index": i,
                "table_source": f"0x{src:08X}",
                "old_container": f"0x{ROM_BASE + start:08X}",
                "new_container": f"0x{new_addr:08X}",
                "new_size": len(rebuilt),
                "translated_streams": translated_streams,
                "total_streams": len(parsed["streams"]),
                "texts_ko": [by_raw[norm_hex(str(stream["raw_hex"]))][0] for stream in parsed["streams"]],
            }
        )

    gate(not encode_failed, "cut-in Korean encode failed: " + ", ".join(sorted(set(encode_failed))))
    gate(len(blob) <= CAVE_END - CAVE_START, f"cut-in cave overflow {len(blob)}")
    candidate[CAVE_START : CAVE_START + len(blob)] = blob
    gate(len(patches) == 37, f"expected 37 patched containers, got {len(patches)}")

    out = bytes(candidate)
    changed = [i for i, (a, b) in enumerate(zip(main_rom, out)) if a != b]
    font_start = FONT12_RELOCATED
    font_end = font_start + fontops.FONT_12X12_COUNT * fontops.FONT_12X12_STRIDE
    allowed_original = set(range(TABLE, TABLE + 37 * 4))
    escaped = [
        off
        for off in changed
        if not (
            off in allowed_original
            or font_start <= off < font_end
            or CAVE_START <= off < CAVE_START + len(blob)
        )
    ]
    gate(not escaped, f"unexpected changed bytes: {[hex(off) for off in escaped[:12]]}")
    gate(out[PAYLOAD_LO:TABLE] == japan[PAYLOAD_LO:TABLE], "original cut-in payloads changed")
    for src, _start in ptrs:
        gate(u32(out, src) >= 0x09000000, f"table pointer not relocated at 0x{src:08X}")
    gate(u32(out, 0x0002AEE4) == ROM_BASE + TABLE, "cut-in table base literal changed")

    kira = next(row for row in patches if row["index"] == 27)
    still = next(row for row in patches if row["index"] == 28)
    amuro = next(row for row in patches if row["index"] == 34)
    gate(kira["texts_ko"] == ["마음만으로는……", "힘만으로는 안 되지만……"], "Kira feelings KO drift")
    gate(still["texts_ko"] == ["그래도！", "지키고 싶은 세상이 있어！"], "Kira world KO drift")
    gate(amuro["texts_ko"] == ["ν건담은 허세가 아니야！"], "Amuro nu KO drift")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    sav_source = ALLCLEAR_SAV if ALLCLEAR_SAV.is_file() else MAIN_SAV
    if sav_source.is_file():
        shutil.copy2(sav_source, OUT_SAV)
    overlay = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_cutin_quotes",
        "table_file_offset": hex(TABLE),
        "entry_count": 37,
        "records": overlay_records,
    }
    OUT_OVERLAY.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_battle_cutin_quotes_ko_candidate_20260905",
        "result": "PASS",
        "base": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(main_rom)},
        "nu_slot_restore": {
            "path": advance_relative(NU_ROM),
            "sha256": sha256(nu),
            "font12_changed_bytes": nu_font_bytes,
            "included": True,
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "size": len(out),
            "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
            "sav_source": advance_relative(sav_source) if sav_source.is_file() else None,
        },
        "overlay": advance_relative(OUT_OVERLAY),
        "table": {
            "file_offset": hex(TABLE),
            "entry_count": 37,
            "payload_unchanged": True,
            "table_base_literal": "0x0002AEE4",
        },
        "cave": {"start": hex(CAVE_START), "end": hex(CAVE_END), "used": len(blob)},
        "counts": dict(counts),
        "kira_feelings": kira,
        "kira_world": still,
        "amuro_nu": amuro,
        "diff": {
            "changed_byte_count": len(changed),
            "original_payload_unchanged": True,
            "unexpected_changed_bytes": 0,
        },
        "verification": {
            "result": "PASS",
            "containers_patched": counts["containers_patched"],
            "encode_failed": 0,
            "nu_font_from_verified_candidate": True,
            "reported_lines_korean": True,
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "rom": advance_relative(OUT_ROM),
                "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
                "manifest": advance_relative(OUT_MANIFEST),
                "sha256": manifest["output"]["sha256"],
                "changed_bytes": len(changed),
                "cave_used": len(blob),
                "counts": dict(counts),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
