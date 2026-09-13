#!/usr/bin/env python3
"""Verify direct 256x3 table-pointer relocation for ID-command battle barks.

The battle renderer (0x08018058 -> 0x08000648) bypasses the generic
0x08000CA8/map-script draw wrapper.  Therefore translated bark containers must
be reached through the live 256x3 table itself, not only through the generic
runtime redirect lookup.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import build_ggen_advance_unified_rom_poc as unified
from ggen_advance_project_paths import ADVANCE_ROOT

DEFAULT_CLEAN = ADVANCE_ROOT / "SD Gundam GGeneration Advance (Japan).gba"
DEFAULT_CANDIDATE = ADVANCE_ROOT / "outputs" / "20260829_ggen_advance_unified_rom" / "ggen_advance_unified_translation_poc_20260839_idbark_tableptr.gba"
DEFAULT_MANIFEST = ADVANCE_ROOT / "analysis" / "ggen_advance_unified_rom_poc_20260839_idbark_tableptr.json"
DEFAULT_APPLY = ADVANCE_ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260839_idbark_tableptr.json"
DEFAULT_OVERLAY = ADVANCE_ROOT / "integrated" / "translation" / "ggen_advance_id_command_battle_barks.json"
DEFAULT_EXTRACT = ADVANCE_ROOT / "analysis" / "ggen_advance_id_command_battle_barks_20260829.json"

MEASURED_PHRASES = {
    "IDコマンドなし": "ID 커맨드 없음",
    "IDコマンド無し": "ID 커맨드 없음",
    "俺はザフトのパイロットだ……": "나는 자프트의 파일럿이다……",
    "機体に手を掛けさせる訳には！": "기체에 손대게 둘 순 없어!",
    "うわぁぁぁ！！": "우와아아앗!!",
    "ヒーローはガラじゃ": "히어로는 겉모습이",
    "ねえってのに……！": "아니라니까……!",
    "戦いは非情さ……": "전투는 비정한 법이지……",
    "手加減はしない！": "봐주지 않겠다!",
}


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def load_mapping12(apply_payload: dict) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in apply_payload.get("assignments", []):
        paint = str(row.get("paint") or "")
        if paint not in {"12x12", "both", "split"}:
            continue
        result[str(row["char"])] = int(str(row["slot"]), 16)
    return result


def raw_hex(value: str) -> bytes:
    text = value.replace(" ", "").strip()
    return bytes.fromhex(text) if text else b""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, default=DEFAULT_CLEAN)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--apply-charmap", type=Path, default=DEFAULT_APPLY)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--extract", type=Path, default=DEFAULT_EXTRACT)
    args = parser.parse_args()

    clean = args.clean.read_bytes()
    candidate = args.candidate.read_bytes()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    apply_payload = json.loads(args.apply_charmap.read_text(encoding="utf-8"))
    overlay = json.loads(args.overlay.read_text(encoding="utf-8"))
    extract = json.loads(args.extract.read_text(encoding="utf-8"))

    gate(len(clean) == 16 * 1024 * 1024, "clean ROM size drift")
    gate(len(candidate) == 32 * 1024 * 1024, "candidate ROM size drift")
    gate(manifest.get("verification", {}).get("result") == "PASS", "unified manifest is not PASS")
    bark_manifest = manifest.get("id_command_battle_barks", {})
    gate(bark_manifest.get("overlay_identity_sha256") == overlay.get("identity_sha256"), "overlay identity drift")
    gate(len(extract.get("entries", [])) == 765, "extract entry count drift")

    gate(
        candidate[unified.ID_BARK_PAYLOAD_START:unified.ID_BARK_TABLE_START]
        == clean[unified.ID_BARK_PAYLOAD_START:unified.ID_BARK_TABLE_START],
        "original battle-bark payload changed",
    )

    # The +4 metadata word must remain byte-identical for every physical slot.
    for logical_index in range(768):
        source = unified.ID_BARK_TABLE_START + logical_index * 8
        gate(
            candidate[source + 4 : source + 8] == clean[source + 4 : source + 8],
            f"battle-bark metadata changed at logical index {logical_index}",
        )

    mapping12 = load_mapping12(apply_payload)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    overlay_by_target = {
        int(str(row["target_file_offset"]), 16): row
        for row in overlay.get("records", [])
    }
    gate(len(overlay_by_target) == 1023, "overlay target count drift")

    measured_seen: dict[str, int] = {key: 0 for key in MEASURED_PHRASES}
    seen_overlay_targets: set[int] = set()
    touched_containers = 0
    full_containers = 0
    mixed_containers = 0
    translated_streams = 0
    pending_streams = 0

    for entry in extract["entries"]:
        table_source = int(str(entry["table_entry_file_offset"]), 16)
        original_start = int(str(entry["container_start_file_offset"]), 16)
        boundary = int(str(entry["container_boundary_file_offset"]), 16)
        clean_pointer = u32(clean, table_source)
        gate(clean_pointer == unified.ROM_BASE + original_start, f"clean table pointer drift at 0x{table_source:08X}")

        expected = bytearray()
        translated_here = 0
        nonempty_here = 0
        streams = entry.get("streams", [])
        separators = entry.get("separators", [])
        gate(len(streams) == len(separators), f"stream/separator mismatch at 0x{original_start:08X}")
        for stream, separator in zip(streams, separators):
            stream_start = int(str(stream["start_file_offset"]), 16)
            original_stream = raw_hex(str(stream.get("raw_hex") or ""))
            source_text = str(stream.get("source_text") or "")
            payload = original_stream
            if source_text:
                nonempty_here += 1
                row = overlay_by_target.get(stream_start)
                gate(row is not None, f"overlay missing nonempty stream 0x{stream_start:08X}")
                seen_overlay_targets.add(stream_start)
                if row.get("translation_status") == "translated" and row.get("translation_policy") == "translate":
                    encoded, missing = unified.encode_korean_text(
                        str(row["translation_ko"]),
                        mapping12,
                        verified_charmap=verified12,
                        strict_punctuation=True,
                    )
                    gate(encoded is not None and not missing, f"verification encode failed: {row['record_id']} {missing}")
                    payload = encoded
                    translated_here += 1
                    translated_streams += 1
                    if source_text in measured_seen:
                        gate(str(row["translation_ko"]) == MEASURED_PHRASES[source_text], f"measured translation drift: {source_text}")
                        measured_seen[source_text] += 1
                else:
                    pending_streams += 1
            expected.extend(payload)
            expected.append(int(str(separator["marker"]), 16))
        expected.extend(raw_hex(str(entry.get("tail_padding_hex") or "")))

        candidate_pointer = u32(candidate, table_source)
        if translated_here == 0:
            gate(candidate_pointer == clean_pointer, f"untouched container pointer changed at 0x{table_source:08X}")
            continue

        touched_containers += 1
        if translated_here == nonempty_here:
            full_containers += 1
        else:
            mixed_containers += 1
        gate(candidate_pointer != clean_pointer, f"translated container still points at original at 0x{table_source:08X}")
        new_off = candidate_pointer - unified.ROM_BASE
        gate(new_off >= 16 * 1024 * 1024, f"translated container destination not in expanded half at 0x{table_source:08X}")
        gate(candidate[new_off : new_off + len(expected)] == bytes(expected), f"rebuilt container mismatch at 0x{table_source:08X}")

        # The old source container itself remains intact.
        gate(
            candidate[original_start:boundary] == clean[original_start:boundary],
            f"original container bytes changed at 0x{original_start:08X}",
        )

    gate(seen_overlay_targets == set(overlay_by_target), "overlay/extract target coverage drift")
    expected_translated = sum(
        row.get("translation_status") == "translated" and row.get("translation_policy") == "translate"
        for row in overlay_by_target.values()
    )
    expected_pending = len(overlay_by_target) - expected_translated
    gate(translated_streams == expected_translated, f"translated stream count drift: {translated_streams} != {expected_translated}")
    gate(pending_streams == expected_pending, f"pending stream count drift: {pending_streams} != {expected_pending}")
    gate(touched_containers == int(bark_manifest.get("table_pointer_patches", -1)), f"touched container count drift: {touched_containers}")
    manifest_encode = bark_manifest.get("encode", {})
    gate(full_containers == int(manifest_encode.get("containers_fully_translated", -1)), f"fully translated container count drift: {full_containers}")
    gate(mixed_containers == int(manifest_encode.get("containers_mixed", 0)), f"mixed container count drift: {mixed_containers}")
    gate(all(count > 0 for count in measured_seen.values()), f"measured regression phrase missing: {measured_seen}")
    gate(
        "id_command_battle_bark" not in manifest.get("scenario_map_script", {}).get("runtime_redirect_categories", {}),
        "battle-bark still incorrectly depends on generic runtime redirect",
    )

    result = {
        "result": "PASS",
        "translated_bark_streams": translated_streams,
        "pending_bark_streams": pending_streams,
        "table_pointer_patches": touched_containers,
        "fully_translated_containers": full_containers,
        "mixed_containers": mixed_containers,
        "measured_regression_occurrences": measured_seen,
        "original_bark_payload_unchanged": True,
        "metadata_unchanged_all_768_slots": True,
        "generic_runtime_redirect_dependency": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
