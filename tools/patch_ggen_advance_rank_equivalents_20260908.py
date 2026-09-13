#!/usr/bin/env python3
"""Apply the Korean rank equivalent for the remaining 軍曹 map lines.

Japanese 伍長/軍曹/曹長 correspond to Korean 하사/중사/상사.  The first
rank-normalization pass corrected the five misdecoded 伍長 strings and other
officer-rank typos.  This follow-up changes the six existing 軍曹 lines from
하사 to 중사 and verifies that the complete rank audit remains clean.
"""
from __future__ import annotations

import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_advance_rank_terms_20260908 as base  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    load_galmuri12,
    recover_unique_12x12_slots,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    ROM_BASE,
    encode_map_korean_line,
    load_identified_12x12,
    raw_hex_bytes,
)


BATCH_ID = "rank-equivalent-normalization-20260908"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260908_rank_equivalents.json"
OUT_DIR = ROOT / "outputs" / "20260908_ggen_advance_rank_equivalents"
OUTPUT = OUT_DIR / "ggen_advance_rank_equivalents_candidate_20260908.gba"
OUT_SAV = OUT_DIR / "ggen_advance_rank_equivalents_candidate_20260908.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_rank_equivalents_candidate_20260908.json"
MANIFEST = OUT_DIR / "manifest.json"
MAP_BANK = (0x00F00000, 0x00FC0000)

JOBS: dict[str, dict[str, Any]] = {
    "GGA-MAPSCRIPT-00F71867": {
        "new_segments": ["……조슈아 상사!", "샌더스 중사! 간다!!"],
        "notes": "軍曹는 伍長보다 한 계급 높은 한국식 중사로 통일",
    },
    "GGA-MAPSCRIPT-00F71CF2": {
        "new_segments": ["무슨 일인가, 샌더스 중사?"],
        "notes": "軍曹는 한국식 중사로 통일",
    },
    "GGA-MAPSCRIPT-00F71E52": {
        "new_segments": ["샌더스 중사", "너는 위치로 돌아가"],
        "notes": "軍曹는 한국식 중사로 통일",
    },
    "GGA-MAPSCRIPT-00F71EAA": {
        "new_segments": ["알겠나, 중사!"],
        "notes": "軍曹는 한국식 중사로 통일",
    },
    "GGA-MAPSCRIPT-00F72595": {
        "new_segments": ["어때, 중사", "나는 살아 있어!!"],
        "notes": "軍曹는 한국식 중사로 통일",
    },
    "GGA-MAPSCRIPT-00F8119A": {
        "new_segments": ["좋아! 중사는 그대로", "두 사람을 보호해 주게!"],
        "notes": "軍曹는 한국식 중사로 통일",
    },
}


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    gate(base.sha256(current) == str(main_manifest.get("sha256") or "").lower(), "main TIP/manifest hash drift")
    gate(ORIGINAL_ROM.exists() and MAIN_SAV.exists(), "required source or SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    for record_id in JOBS:
        gate(record_id in by_id, f"軍曹 target missing: {record_id}")
    before_mismatches = base.rank_mismatches(merged)
    gate(
        {item["record_id"] for item in before_mismatches} == set(JOBS),
        "unexpected pre-patch rank mismatch set for 軍曹",
    )

    hangul = {
        char
        for record_id, job in JOBS.items()
        for text in list(by_id[record_id].get("translation_segments") or []) + list(job["new_segments"])
        for char in str(text)
        if "가" <= char <= "힣"
    }
    font12 = load_galmuri12()
    recovered12 = recover_unique_12x12_slots(current, font12, hangul)
    identified12 = load_identified_12x12()
    candidate = bytearray(current)
    allowed: set[int] = set()
    evidence: list[dict[str, Any]] = []

    for record_id, job in JOBS.items():
        row = by_id[record_id]
        gate(row.get("source_scope") == "scenario_map_script", f"rank map scope drift: {record_id}")
        gate("軍曹" in str(row.get("source_text") or ""), f"source is not 軍曹: {record_id}")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        new_segments = [str(item) for item in job["new_segments"]]
        gate(len(old_segments) == len(new_segments), f"segment count drift: {record_id}")
        segments = list(row.get("segments") or [])
        gate(len(segments) == len(new_segments), f"map framing drift: {record_id}")
        before = str(row.get("translation_ko") or "")
        after = "\n".join(new_segments)

        cursor = int(str(row["target_file_offset"]), 16)
        for index, (segment, old_text, new_text) in enumerate(zip(segments, old_segments, new_segments)):
            raw = raw_hex_bytes(str(segment.get("raw_hex") or ""))
            gate(raw.endswith(b"\x00"), f"map segment is not NUL terminated: {record_id}#{index}")
            orig_addr = ROM_BASE + cursor
            orig_end = orig_addr + len(raw) - 1
            hits = base.lookup_entries(current, orig_addr, orig_end)
            relocated = hits[0][1]
            old_payload = base.payload_until_nul(current, relocated, 128)
            old_encoded, old_missing = encode_map_korean_line(old_text, recovered12, identified12)
            gate(not old_missing and old_encoded == old_payload, f"map old payload mismatch: {record_id}#{index}")
            gate("\n" not in new_text and len(new_text) <= MAX_DIALOGUE_CELLS, f"map width drift: {record_id}#{index}")
            new_encoded, new_missing = encode_map_korean_line(new_text, recovered12, identified12)
            gate(new_encoded is not None and not new_missing, f"map encode failed: {record_id}#{index}: {new_missing}")
            base.patch_same_size(candidate, relocated, old_payload, new_encoded, allowed)
            gate(all(item[1] == relocated for item in hits), f"map lookup alias drift: {record_id}#{index}")
            evidence.append(
                {
                    "record_id": record_id,
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
            cursor += len(raw)
        base.BATCH_ID = BATCH_ID
        base.set_translation_fields(row, after, new_segments, str(job["notes"]))

    after_mismatches = base.rank_mismatches(merged)
    gate(not after_mismatches, f"Japanese rank mismatch remains: {after_mismatches[:4]}")
    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"candidate changed outside rank payloads: {len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "map-script bank changed")
    gate(MAIN_TIP_ROM.read_bytes() == current, "main TIP mutated during patch")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    rank_identity = base.digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [
                {
                    "record_id": record_id,
                    "translation_payload_sha256": by_id[record_id].get("translation_payload_sha256"),
                }
                for record_id in sorted(JOBS)
            ],
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["rank_equivalent_normalization_sha256"] = rank_identity
    identity["translation_overlay_identity_sha256"] = rank_identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged.setdefault("summary", {})["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = rank_identity
    merged["rank_equivalent_normalization_20260908"] = {
        "batch_id": BATCH_ID,
        "mapping": {"伍長": "하사", "軍曹": "중사", "曹長": "상사"},
        "records": sorted(JOBS),
        "previous_rank_normalization_retained": True,
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
        "kind": "ggen_advance_rank_equivalents_candidate_20260908",
        "batch_id": BATCH_ID,
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": base.sha256(current),
            "translation_source": advance_relative(TRANSLATION_MERGED_JSON),
        },
        "rank_audit": {
            "mapping": {"伍長": "하사", "軍曹": "중사", "曹長": "상사"},
            "before_mismatches": before_mismatches,
            "after_mismatches": after_mismatches,
            "corrected_records": sorted(JOBS),
        },
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": base.sha256(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes()},
        "verification": {
            "result": "PASS",
            "changed_bytes": len(changed),
            "allowed_changed_bytes": len(allowed),
            "all_old_live_payloads_matched": True,
            "all_new_payloads_same_size": True,
            "軍曹_translated_as_중사": True,
            "full_rank_audit_clean": True,
            "original_map_script_bank_unchanged": True,
            "runtime_emulator": "not run; static ROM/font/payload verification only",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
