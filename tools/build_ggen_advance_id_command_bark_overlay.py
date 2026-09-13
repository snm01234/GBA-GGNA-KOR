#!/usr/bin/env python3
"""Build the first reviewed translation overlay for 12x12 ID-command battle barks.

Only conservative seeds are promoted automatically:
* exact same Japanese text as the character/command's translated 8x16 A field;
* a unique exact translated source_text already present in the canonical merge;
* measured/manual overrides for the 2026-08-29 screenshot regression cases.

Partial matches and unresolved 12x12 glyphs remain pending.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ggen_advance_project_paths import ADVANCE_ROOT

DEFAULT_EXTRACT = ADVANCE_ROOT / "analysis" / "ggen_advance_id_command_battle_barks_20260829.json"
DEFAULT_OUT = ADVANCE_ROOT / "integrated" / "translation" / "ggen_advance_id_command_battle_barks.json"
DEFAULT_MANUAL = ADVANCE_ROOT / "integrated" / "translation" / "ggen_advance_id_command_battle_bark_manual_ko_20260829.json"

MANUAL_MEASURED: dict[str, str] = {
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


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def choose_translation(
    entry: dict[str, Any],
    stream: dict[str, Any],
    curated_manual: dict[str, str],
) -> tuple[str, str, str]:
    jp = str(stream.get("source_text") or "")
    if not jp:
        return "", "pending", "empty_placeholder"
    if stream.get("source_decode_status") != "complete":
        return "", "pending", "unresolved_12x12_glyph"
    if jp in MANUAL_MEASURED:
        return MANUAL_MEASURED[jp], "translated", "measured_manual_20260829"
    if jp in curated_manual:
        return curated_manual[jp], "translated", "curated_manual_full_20260829"

    command_a = entry.get("character_command_reference", {}).get("command_A", {})
    if (
        str(command_a.get("source_text") or "") == jp
        and command_a.get("translation_status") == "translated"
        and str(command_a.get("translation_ko") or "").strip()
    ):
        return str(command_a["translation_ko"]), "translated", "parallel_command_A_exact"

    unique = [str(value) for value in stream.get("exact_translation_unique_ko", []) if str(value).strip()]
    if len(unique) == 1:
        return unique[0], "translated", "canonical_exact_source_text"
    return "", "pending", "no_safe_exact_seed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", type=Path, default=DEFAULT_EXTRACT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--manual", type=Path, default=DEFAULT_MANUAL)
    args = parser.parse_args()

    source = json.loads(args.extract.read_text(encoding="utf-8"))
    manual_payload = json.loads(args.manual.read_text(encoding="utf-8"))
    curated_manual = {
        str(jp): str(ko)
        for jp, ko in manual_payload.get("translations", {}).items()
        if str(jp) and str(ko).strip()
    }
    records: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    translated_chars: set[str] = set()

    for entry in source["entries"]:
        character = entry["character_command_reference"]
        for stream in entry["streams"]:
            jp = str(stream.get("source_text") or "")
            if not jp:
                continue
            ko, status, translation_source = choose_translation(entry, stream, curated_manual)
            record = {
                "record_id": f"GGA-IDBARK-{int(stream['start_file_offset'], 16):08X}",
                "source_scope": "id_command_battle_bark",
                "scope_status": "included",
                "record_kind": "id_command_battle_bark_12x12_stream",
                "target_file_offset": stream["start_file_offset"],
                "target_address": stream["start_address"],
                "raw_hex": stream["raw_hex"],
                "original_byte_length": stream["raw_byte_length"],
                "source_text": jp,
                "source_decode_status": stream["source_decode_status"],
                "source_unresolved_slots": stream["source_unresolved_slots"],
                "font_mode": "12x12",
                "semantic_category": "id_command_battle_bark",
                "translation_policy": "translate",
                "translation_ko": ko,
                "translation_status": status,
                "translation_source": translation_source,
                "review_status": (
                    "measured"
                    if translation_source == "measured_manual_20260829"
                    else ("curated" if translation_source == "curated_manual_full_20260829" else ("seeded" if status == "translated" else "unreviewed"))
                ),
                "character_index": entry["character_index"],
                "command_index": entry["command_index"],
                "logical_index": entry["logical_index"],
                "stream_index": stream["stream_index"],
                "container_start_file_offset": entry["container_start_file_offset"],
                "table_entry_file_offset": entry["table_entry_file_offset"],
                "metadata_u32": entry["metadata_u32"],
                "character_name": character.get("character_name", ""),
                "character_name_ko": character.get("character_name_ko", ""),
                "parallel_command_A_record_id": character.get("command_A", {}).get("record_id", ""),
                "parallel_command_A_source_text": character.get("command_A", {}).get("source_text", ""),
                "parallel_command_A_translation_ko": character.get("command_A", {}).get("translation_ko", ""),
                "runtime_apply_contract": "parser_pointer_redirect_only; original table/container/metadata unchanged",
            }
            record["translation_payload_sha256"] = sha256_json(
                {
                    "record_id": record["record_id"],
                    "source_text": jp,
                    "translation_ko": ko,
                    "translation_status": status,
                }
            )
            records.append(record)
            status_counts[status] += 1
            source_counts[translation_source] += 1
            if status == "translated":
                translated_chars.update(char for char in ko if "가" <= char <= "힣")

    payload = {
        "schema_version": 1,
        "kind": "ggen_advance_id_command_battle_bark_translation_overlay",
        "source_extract": str(args.extract.relative_to(ADVANCE_ROOT)).replace("\\", "/"),
        "renderer_contract": source["renderer_contract"],
        "summary": {
            "records": len(records),
            "status_counts": dict(sorted(status_counts.items())),
            "translation_source_counts": dict(sorted(source_counts.items())),
            "translated_unique_hangul": len(translated_chars),
            "manual_measured_phrases": len(MANUAL_MEASURED),
            "curated_manual_phrases": len(curated_manual),
        },
        "records": records,
    }
    payload["identity_sha256"] = sha256_json(
        [
            {
                "record_id": row["record_id"],
                "target_file_offset": row["target_file_offset"],
                "source_text": row["source_text"],
                "translation_ko": row["translation_ko"],
                "translation_status": row["translation_status"],
            }
            for row in records
        ]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(args.out), "summary": payload["summary"], "identity_sha256": payload["identity_sha256"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
