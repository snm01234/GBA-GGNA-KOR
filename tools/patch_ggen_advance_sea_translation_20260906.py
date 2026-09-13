"""Apply the verified 海 -> 바다 translation to the canonical source and ROM."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from ggen_advance_project_paths import MAIN_TIP_MANIFEST, MAIN_TIP_ROM, TRANSLATION_MERGED_JSON, advance_relative
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest
from patch_ggen_advance_intermission_text_consumers_20260904 import encode_literal, load_apply_tokens

RECORD_ID = "GGA-TEXT-0018CF9C"
OWNER = 0x001B4ED8
SOURCE_RAW = bytes.fromhex("E0 C9 00")
NEW_PAYLOAD_OFFSET = 0x012B0000
ROM_BASE = 0x08000000
BATCH_ID = "user-requested-sea-translation-20260906"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260906_sea_translation.json"
OUTPUT = ROOT / "outputs" / "20260906_ggen_advance_sea_translation" / "ggen_advance_sea_translation_20260906.gba"
REPORT = ROOT / "analysis" / "ggen_advance_sea_translation_20260906.json"
CHARMAP = ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json"


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def payload_at(data: bytes | bytearray, address: int) -> bytes:
    offset = address - ROM_BASE
    gate(0 <= offset < len(data), f"payload outside ROM: 0x{address:08X}")
    end = data.find(0, offset, min(len(data), offset + 0x100))
    gate(end >= 0, f"unterminated payload: 0x{address:08X}")
    return bytes(data[offset : end + 1])


def update_payload_hash(row: dict[str, Any]) -> None:
    patch = {
        "record_id": row["record_id"],
        "batch_id": row["overlay_batch_id"],
        "translation_ko": row.get("translation_ko") or "",
        "translation_segments": row.get("translation_segments"),
        "translation_status": row.get("translation_status") or "",
        "translation_source": row.get("translation_source") or "",
        "source_model": row.get("source_model") or "",
        "prompt_version": row.get("prompt_version") or "",
        "review_status": row.get("review_status") or "",
        "review_count": row.get("review_count") or 0,
        "reviewed_at": row.get("reviewed_at") or "",
        "translator_notes": row.get("translator_notes") or "",
        "qa_status": row.get("qa_status") or "",
    }
    row["translation_payload_sha256"] = translation_payload_digest(patch)


def main() -> int:
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row.get("record_id")): row for row in merged["records"]}
    gate(RECORD_ID in by_id, "Sea record missing")
    row = by_id[RECORD_ID]
    gate(row.get("raw_hex") == SOURCE_RAW.hex(" ").upper(), "Sea source bytes drift")
    gate(row.get("owner_ids") == ["OWNER-U32-001B4ED8"], "Sea owner drift")
    gate(row.get("translation_status") == "pending", "Sea translation is no longer pending")
    gate(u32(current, OWNER) == 0x0905220D, "Sea owner pointer drift")
    gate(payload_at(current, u32(current, OWNER)) == SOURCE_RAW, "current active Sea payload drift")

    tokens = load_apply_tokens(CHARMAP)
    new_payload = encode_literal("바다", tokens)
    gate(new_payload == bytes.fromhex("E6 79 E0 62 00"), "바다 encoding drift")
    gate(all(value == 0 for value in current[NEW_PAYLOAD_OFFSET : NEW_PAYLOAD_OFFSET + len(new_payload)]), "Sea allocation is not zero-filled")

    candidate = bytearray(current)
    candidate[NEW_PAYLOAD_OFFSET : NEW_PAYLOAD_OFFSET + len(new_payload)] = new_payload
    struct.pack_into("<I", candidate, OWNER, ROM_BASE + NEW_PAYLOAD_OFFSET)
    gate(payload_at(candidate, ROM_BASE + NEW_PAYLOAD_OFFSET) == new_payload, "Sea payload write failed")
    gate(u32(candidate, OWNER) == ROM_BASE + NEW_PAYLOAD_OFFSET, "Sea owner redirect failed")
    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    allowed = set(range(NEW_PAYLOAD_OFFSET, NEW_PAYLOAD_OFFSET + len(new_payload))) | set(range(OWNER, OWNER + 4))
    gate(set(changed) <= allowed, "unexpected ROM byte change")

    row["source_text"] = "海"
    row["source_decode_status"] = "complete"
    row["source_unresolved_slots"] = []
    row["translation_ko"] = "바다"
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified_runtime_ss1"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-06"
    row["translator_notes"] = "갱신 ss1에서 海 표시를 확인하고 GGA-TEXT-0018CF9C의 0x01A9를 海로 확정; 동일 지형명 소비 경로의 바다 payload로 재인코딩"
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [{"record_id": RECORD_ID, "payload": row["translation_payload_sha256"]}]})
    merged.setdefault("identity", {})["parent_translation_overlay_identity_sha256"] = parent_identity
    merged["identity"]["sea_translation_identity_sha256"] = new_identity
    merged["identity"]["translation_overlay_identity_sha256"] = new_identity
    merged.setdefault("merge", {})["rom_write_performed"] = False
    merged.setdefault("merge", {}).setdefault("overlay_files", []).append({
        "file": "user_requested_sea_translation_20260906.json",
        "file_sha256": sha256(new_payload),
        "batch_id": BATCH_ID,
        "record_count": 1,
        "record_ids": [RECORD_ID],
    })
    merged.setdefault("summary", {})["sea_translation_record_id"] = RECORD_ID
    merged["summary"]["sea_translation_status"] = "translated"

    payload = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload, encoding="utf-8")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    report = {
        "result": "PASS",
        "batch_id": BATCH_ID,
        "record_id": RECORD_ID,
        "translation": {"source": "海", "korean": "바다", "payload_hex": new_payload.hex(" ").upper()},
        "owner": {"file_offset": hex(OWNER), "new_payload_address": hex(ROM_BASE + NEW_PAYLOAD_OFFSET)},
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "output": {"path": advance_relative(OUTPUT), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {"path": advance_relative(TRANSLATION_MERGED_JSON), "sha256": sha256(payload.encode("utf-8"))},
        "verification": {
            "result": "PASS",
            "canonical_translation_updated": True,
            "canonical_workbook_pending_rebuild": True,
            "only_sea_owner_and_payload_changed": True,
            "payload_roundtrip": payload_at(candidate, ROM_BASE + NEW_PAYLOAD_OFFSET) == new_payload,
            "runtime_emulator": "not run; static ROM verification only",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
