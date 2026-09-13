#!/usr/bin/env python3
"""Normalize Japanese-style military rank terms in the current GGA main TIP.

The five map-script strings decoded as ``艦長`` actually contain the distinct
12x12 token pair used by ``伍長``.  Their Korean translations are therefore
changed from 함장 to 하사.  A repository-wide rank audit also found three
ordinary translation mismatches (소좌/대좌), which are corrected in the same
in-place payload pass.

The source rows remain immutable: the raw token evidence is recorded in the
derived translation metadata and candidate report, while only translation
payload fields and their live consumers are changed.
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    FONT12_RELOCATED,
    load_galmuri8,
    load_galmuri12,
    recover_unique_8x16_slots,
    recover_unique_12x12_slots,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    MAIN_TIP_ROOT,
    ORIGINAL_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    sha256,
    update_payload_hash,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    ROM_BASE,
    encode_map_korean_line,
    load_identified_12x12,
    raw_hex_bytes,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    payload_until_nul,
    update_translation_manifest,
)


BATCH_ID = "rank-term-normalization-20260908"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260908_rank_terms.json"
OUT_DIR = ROOT / "outputs" / "20260908_ggen_advance_rank_terms"
OUTPUT = OUT_DIR / "ggen_advance_rank_terms_candidate_20260908.gba"
OUT_SAV = OUT_DIR / "ggen_advance_rank_terms_candidate_20260908.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_rank_terms_candidate_20260908.json"
MANIFEST = OUT_DIR / "manifest.json"
MAP_BANK = (0x00F00000, 0x00FC0000)

MAP_JOBS: dict[str, dict[str, Any]] = {
    "GGA-MAPSCRIPT-00F52035": {
        "new_segments": ["모린 하사의 셔틀로", "발진하게 됩니다"],
        "actual_source": "伍長",
        "notes": "E1 F4 E4 29는 艦長이 아닌 伍長. 한국 군 계급 하사로 통일",
    },
    "GGA-MAPSCRIPT-00F52F5E": {
        "new_segments": ["……키타무라 하사", "적군에 대한 정보를"],
        "actual_source": "伍長",
        "notes": "E1 F4 E4 29의 실제 원문은 伍長. 한국 군 계급 하사로 통일",
    },
    "GGA-MAPSCRIPT-00F6DED6": {
        "new_segments": ["우몬 하사는?", "분명 뉴타입이라던가"],
        "actual_source": "伍長",
        "notes": "E1 F4 E4 29의 실제 원문은 伍長. 한국 군 계급 하사로 통일",
    },
    "GGA-MAPSCRIPT-00F75A1E": {
        "new_segments": ["와이즈먼 하사,어떻게된거지?"],
        "actual_source": "伍長",
        "notes": "와이즈먼의 E1 F4 E4 29는 함장이 아닌 伍長. 하사로 번역",
    },
    "GGA-MAPSCRIPT-00F75A90": {
        "new_segments": ["와이즈먼 하사,", "준비 완료입니다!!"],
        "actual_source": "伍長",
        "notes": "와이즈먼의 E1 F4 E4 29는 함장이 아닌 伍長. 하사로 번역",
    },
}

OTHER_JOBS: dict[str, dict[str, Any]] = {
    "GGA-MAPSCRIPT-00FA7BE5": {
        "new_segments": ["그런 귀공은 어떠한가?", "조니 라이덴 소령"],
        "notes": "少佐는 국내식 계급명 소령으로 통일",
    },
    "GGA-MAPSCRIPT-00F87FAC": {
        "new_segments": ["여기까지다, 라미아스 소령"],
        "notes": "少佐는 국내식 계급명 소령으로 통일",
    },
}

PRODUCTION_JOB: dict[str, Any] = {
    "record_id": "GGA-TEXT-0017C64D",
    "new_translation": "대령이 싸워 줄 거야……！！",
    "notes": "大佐는 국내식 계급명 대령. 조사격에 맞춰 대령이로 교정",
}

RANK_MAP = {
    "伍長": "하사",
    "軍曹": "중사",
    "曹長": "상사",
    "兵長": "병장",
    "上等兵": "상병",
    "一等兵": "일병",
    "二等兵": "이병",
    "准尉": "준위",
    "少尉": "소위",
    "中尉": "중위",
    "大尉": "대위",
    "少佐": "소령",
    "中佐": "중령",
    "大佐": "대령",
    "准将": "준장",
    "少将": "소장",
    "中将": "중장",
    "大将": "대장",
    "元帥": "원수",
}


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def owner_offsets(row: dict[str, Any]) -> tuple[int, ...]:
    return tuple(
        int(str(owner).removeprefix("OWNER-U32-"), 16)
        for owner in row.get("owner_ids", [])
        if str(owner).startswith("OWNER-U32-")
    )


def lookup_entries(
    rom: bytes,
    orig_addr: int,
    expected_end: int,
) -> list[tuple[int, int, int]]:
    """Return all identical live lookup entries for an inline map stream.

    The promoted main TIP contains two copies of the generated table.  Both
    copies are required to agree; accepting only one would make the patch
    silently depend on which table the runtime reaches.
    """

    key = struct.pack("<I", orig_addr)
    hits: list[tuple[int, int, int]] = []
    cursor = 0
    while True:
        position = rom.find(key, cursor)
        if position < 0:
            break
        if position + 12 <= len(rom):
            original, relocated, original_end = struct.unpack_from("<III", rom, position)
            if (
                original == orig_addr
                and original_end == expected_end
                and 0x09000000 <= relocated < 0x0A000000
            ):
                hits.append((position, relocated, original_end))
        cursor = position + 1
    gate(hits, f"map lookup missing for 0x{orig_addr:08X}")
    gate(
        len({relocated for _position, relocated, _end in hits}) == 1,
        f"map lookup copies disagree for 0x{orig_addr:08X}",
    )
    return hits


def patch_same_size(
    candidate: bytearray,
    address: int,
    old_payload: bytes,
    new_payload: bytes,
    allowed: set[int],
) -> None:
    gate(len(new_payload) == len(old_payload), "rank replacement unexpectedly changes payload size")
    file_offset = address - ROM_BASE
    gate(0 <= file_offset <= len(candidate) - len(old_payload), f"payload outside candidate 0x{address:08X}")
    gate(bytes(candidate[file_offset : file_offset + len(old_payload)]) == old_payload, "live payload changed before write")
    candidate[file_offset : file_offset + len(new_payload)] = new_payload
    allowed.update(range(file_offset, file_offset + len(old_payload)))


def row_translation_text(row: dict[str, Any]) -> str:
    segments = row.get("translation_segments")
    if isinstance(segments, list) and segments:
        return "\n".join(str(item) for item in segments)
    return str(row.get("translation_ko") or "")


def rank_mismatches(payload: dict[str, Any]) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    for row in payload["records"]:
        if row.get("translation_status") != "translated":
            continue
        source = str(row.get("source_text") or "")
        translation = row_translation_text(row)
        for japanese, korean in RANK_MAP.items():
            if japanese in source and korean not in translation:
                mismatches.append(
                    {
                        "record_id": str(row["record_id"]),
                        "source_rank": japanese,
                        "expected_korean": korean,
                        "translation": translation,
                    }
                )
    return mismatches


def rank_source_counts(payload: dict[str, Any]) -> dict[str, int]:
    return {
        japanese: sum(str(row.get("source_text") or "").count(japanese) for row in payload["records"])
        for japanese in RANK_MAP
    }


def set_translation_fields(
    row: dict[str, Any],
    translation: str,
    segments: list[str] | None,
    notes: str,
) -> None:
    row["translation_ko"] = translation
    if segments is not None:
        row["translation_segments"] = segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-08"
    row["translator_notes"] = notes
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    gate(sha256(current) == str(main_manifest.get("sha256") or "").lower(), "main TIP/manifest hash drift")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(ORIGINAL_ROM.exists(), "Japanese source ROM missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    all_jobs = {**MAP_JOBS, **OTHER_JOBS}
    for record_id in (*MAP_JOBS, *OTHER_JOBS, PRODUCTION_JOB["record_id"]):
        gate(record_id in by_id, f"rank target missing: {record_id}")

    before_mismatches = rank_mismatches(merged)
    gate(
        {item["record_id"] for item in before_mismatches}
        == {PRODUCTION_JOB["record_id"], "GGA-MAPSCRIPT-00FA7BE5", "GGA-MAPSCRIPT-00F87FAC"},
        "unexpected pre-patch rank mismatch set",
    )

    candidate = bytearray(current)
    allowed: set[int] = set()
    evidence: list[dict[str, Any]] = []

    # Recover only the Hangul cells used by the changed map lines.  The old
    # payload comparison below proves that the recovered slots match the
    # active font in the promoted ROM before any write occurs.
    map_hangul = {
        char
        for record_id, job in all_jobs.items()
        if by_id[record_id].get("source_scope") == "scenario_map_script"
        for text in list(by_id[record_id].get("translation_segments") or []) + list(job["new_segments"])
        for char in str(text)
        if "가" <= char <= "힣"
    }
    font12 = load_galmuri12()
    recovered12 = recover_unique_12x12_slots(current, font12, map_hangul)
    identified12 = load_identified_12x12()

    # Five exact E1 F4 E4 29 rows are the misdecoded 伍長 cases.  Keep their
    # immutable source_text/segments, but record the raw-token correction and
    # replace only their Korean consumers.
    wuchang_token_rows: list[str] = []
    for record_id, job in MAP_JOBS.items():
        row = by_id[record_id]
        gate(row.get("source_scope") == "scenario_map_script", f"rank map scope drift: {record_id}")
        raw_compact = "".join(str(row.get("raw_hex") or "").upper().split())
        gate("E1F4E429" in raw_compact, f"伍長 token missing from {record_id}")
        wuchang_token_rows.append(record_id)
    gate(len(wuchang_token_rows) == 5, "伍長 target count drift")

    for record_id, job in all_jobs.items():
        row = by_id[record_id]
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        new_segments = [str(item) for item in job["new_segments"]]
        gate(len(old_segments) == len(new_segments), f"segment count drift: {record_id}")
        segments = list(row.get("segments") or [])
        gate(len(segments) == len(new_segments), f"map framing drift: {record_id}")
        before = str(row.get("translation_ko") or "")
        after = "\n".join(new_segments)
        for index, (segment, old_text, new_text) in enumerate(zip(segments, old_segments, new_segments)):
            raw = raw_hex_bytes(str(segment.get("raw_hex") or ""))
            gate(raw.endswith(b"\x00"), f"map segment is not NUL terminated: {record_id}#{index}")
            cursor = int(str(row["target_file_offset"]), 16)
            for prior in segments[:index]:
                cursor += len(raw_hex_bytes(str(prior.get("raw_hex") or "")))
            orig_addr = ROM_BASE + cursor
            orig_end = orig_addr + len(raw) - 1
            hits = lookup_entries(current, orig_addr, orig_end)
            relocated = hits[0][1]
            old_payload = payload_until_nul(current, relocated, 128)
            old_encoded, old_missing = encode_map_korean_line(old_text, recovered12, identified12)
            gate(not old_missing and old_encoded == old_payload, f"map old payload mismatch: {record_id}#{index}")
            gate("\n" not in new_text and len(new_text) <= MAX_DIALOGUE_CELLS, f"map width drift: {record_id}#{index}")
            new_encoded, new_missing = encode_map_korean_line(new_text, recovered12, identified12)
            gate(new_encoded is not None and not new_missing, f"map encode failed: {record_id}#{index}: {new_missing}")
            patch_same_size(candidate, relocated, old_payload, new_encoded, allowed)
            # A same-size replacement leaves both generated lookup copies
            # valid.  Verify that their aliases still target this payload.
            gate(all(item[1] == relocated for item in hits), f"map lookup alias drift: {record_id}#{index}")
            evidence.append(
                {
                    "record_id": record_id,
                    "source_scope": row.get("source_scope"),
                    "segment": index,
                    "before": old_text,
                    "after": new_text,
                    "original_address": f"0x{orig_addr:08X}",
                    "lookup_copies": len(hits),
                    "payload_address": f"0x{relocated:08X}",
                    "old_payload": old_payload.hex(" ").upper(),
                    "new_payload": new_encoded.hex(" ").upper(),
                    "encoded_size": len(new_encoded),
                }
            )
        set_translation_fields(row, after, new_segments, str(job["notes"]))

    # Production/UI text uses the active 8x16 font and an ordinary u32 owner.
    production_row = by_id[PRODUCTION_JOB["record_id"]]
    old_translation = str(production_row.get("translation_ko") or "")
    new_translation = str(PRODUCTION_JOB["new_translation"])
    prod_hangul = {char for char in old_translation + new_translation if "가" <= char <= "힣"}
    font8 = load_galmuri8()
    recovered8 = recover_unique_8x16_slots(current, font8, prod_hangul)
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    old_encoded8, old_missing8 = unified.encode_korean_text(
        old_translation,
        recovered8,
        verified_charmap=verified8,
        strict_punctuation=True,
    )
    new_encoded8, new_missing8 = unified.encode_korean_text(
        new_translation,
        recovered8,
        verified_charmap=verified8,
        strict_punctuation=True,
    )
    gate(old_encoded8 is not None and not old_missing8, f"production old encode failed: {old_missing8}")
    gate(new_encoded8 is not None and not new_missing8, f"production new encode failed: {new_missing8}")
    owners = owner_offsets(production_row)
    gate(len(owners) == 1, "production rank row owner count drift")
    owner = owners[0]
    pointer = struct.unpack_from("<I", current, owner)[0]
    gate(0x09000000 <= pointer < 0x0A000000, "production owner pointer is not relocated")
    live_production = payload_until_nul(current, pointer, 128)
    gate(live_production == old_encoded8, "production live payload mismatch")
    patch_same_size(candidate, pointer, live_production, new_encoded8, allowed)
    gate(struct.unpack_from("<I", candidate, owner)[0] == pointer, "production owner pointer changed")
    set_translation_fields(production_row, new_translation, None, str(PRODUCTION_JOB["notes"]))
    evidence.append(
        {
            "record_id": PRODUCTION_JOB["record_id"],
            "source_scope": production_row.get("source_scope"),
            "owner_file_offset": f"0x{owner:08X}",
            "payload_address": f"0x{pointer:08X}",
            "before": old_translation,
            "after": new_translation,
            "old_payload": live_production.hex(" ").upper(),
            "new_payload": new_encoded8.hex(" ").upper(),
            "encoded_size": len(new_encoded8),
        }
    )

    after_mismatches = rank_mismatches(merged)
    gate(not after_mismatches, f"Japanese rank mismatch remains: {after_mismatches[:4]}")
    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"candidate changed outside rank payloads: {len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "map-script bank changed")
    gate(MAIN_TIP_ROM.read_bytes() == current, "main TIP mutated during patch")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    rank_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [
                {
                    "record_id": record_id,
                    "translation_payload_sha256": by_id[record_id].get("translation_payload_sha256"),
                }
                for record_id in sorted((*MAP_JOBS, *OTHER_JOBS, PRODUCTION_JOB["record_id"]))
            ],
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["rank_term_normalization_sha256"] = rank_identity
    identity["translation_overlay_identity_sha256"] = rank_identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged.setdefault("summary", {})["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = rank_identity
    merged["rank_term_normalization_20260908"] = {
        "batch_id": BATCH_ID,
        "actual_source_term": "伍長",
        "translated_as": "하사",
        "misdecoded_source_label": "艦長",
        "raw_token_sequence": "E1 F4 E4 29",
        "token_slots": {"E1F4": "0x02D4", "E429": "0x0509"},
        "records": sorted(wuchang_token_rows),
        "immutable_source_preserved": True,
        "other_rank_corrections": sorted((*OTHER_JOBS, PRODUCTION_JOB["record_id"])),
    }
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_rank_terms_candidate_20260908",
        "batch_id": BATCH_ID,
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
            "translation_source": advance_relative(TRANSLATION_MERGED_JSON),
        },
        "rank_audit": {
            "mapping": RANK_MAP,
            "source_occurrence_counts": rank_source_counts(merged),
            "before_mismatches": before_mismatches,
            "after_mismatches": after_mismatches,
            "wuchang_evidence": {
                "record_count": len(wuchang_token_rows),
                "record_ids": sorted(wuchang_token_rows),
                "actual_source_term": "伍長",
                "old_decoded_label": "艦長",
                "raw_token_sequence": "E1 F4 E4 29",
                "token_slots": {"E1F4": "0x02D4", "E429": "0x0509"},
                "genuine_captain_token": "E1 1D E4 29",
                "translation_before": "함장",
                "translation_after": "하사",
            },
        },
        "consumers": evidence,
        "output": {
            "path": advance_relative(OUTPUT),
            "size": len(candidate),
            "sha256": sha256(candidate),
        },
        "sav": {
            "path": advance_relative(OUT_SAV),
            "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(),
        },
        "verification": {
            "result": "PASS",
            "changed_bytes": len(changed),
            "allowed_changed_bytes": len(allowed),
            "all_old_live_payloads_matched": True,
            "all_new_payloads_same_size": True,
            "all_five_wuchang_rows_translated_as_hasa": True,
            "other_rank_mismatches_resolved": True,
            "original_map_script_bank_unchanged": True,
            "source_fields_immutable": True,
            "runtime_emulator": "not run; static ROM/font/payload verification only",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
