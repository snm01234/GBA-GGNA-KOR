#!/usr/bin/env python3
"""Patch the intermission text consumers and audit their static draw paths.

The visible stage subtitle ``哀戦士`` is the remaining untranslated FCE2D8
paired-selection entry.  The two help records are translated but their active
payloads predate later font-slot assignments, so they must be re-encoded with
the current apply charmap.  This tool writes a targeted current-main candidate
and records static consumer evidence for all three paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402


ROM_BASE = 0x08000000
BATCH_ID = "intermission-text-consumers-20260904"
TARGET_RECORD_ID = "GGA-TEXT-0018D16B"
TARGET_SOURCE = "哀戦士"
TARGET_KOREAN = "애전사"
TARGET_OWNER = 0x00FCE304
TARGET_ORIGINAL_ADDRESS = 0x0818D16B
TARGET_ORIGINAL_RAW = bytes.fromhex("E0 65 B7 A8 00")
TARGET_PAYLOAD_OFFSET = 0x01290000
TARGET_PAYLOAD_ADDRESS = ROM_BASE + TARGET_PAYLOAD_OFFSET
REENCODE_OFFSETS = {
    "advance_help": 0x01290010,
    "search_help": 0x01290040,
}

FCE128_TABLE = 0x00FCE128
FCE128_CALL = 0x00065446
SEARCH_LOCATION_CALL = 0x0001C63E
SEARCH_LOCATION_OWNER = 0x00D55938
FCE2D8_TABLE = 0x00FCE2D8
FCE2D8_DRAW_CALLS = (0x00073B54, 0x00073B68, 0x00073C20, 0x00073C34, 0x00073E94, 0x00073EA8, 0x00073F10, 0x00073F24)
DRAW_WRAPPER = 0x08000CA0

AUDIT_RECORDS = {
    "advance_help": "GGA-TEXT-001BE836",
    "search_help": "GGA-TEXT-001BE824",
    "odessa": "GGA-TEXT-001BEF11",
}


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def bl_target(data: bytes | bytearray, offset: int) -> int | None:
    hi, lo = struct.unpack_from("<HH", data, offset)
    if hi & 0xF800 != 0xF000 or lo & 0xF800 != 0xF800:
        return None
    disp = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
    if disp & (1 << 22):
        disp -= 1 << 23
    return ROM_BASE + offset + 4 + disp


def payload_at(rom: bytes | bytearray, address: int) -> bytes:
    offset = address - ROM_BASE
    gate(0 <= offset < len(rom), f"payload address outside ROM: 0x{address:08X}")
    end = rom.find(0, offset, min(len(rom), offset + 0x100))
    gate(end >= 0, f"unterminated payload: 0x{address:08X}")
    return bytes(rom[offset : end + 1])


def load_apply_tokens(path: Path) -> dict[str, int]:
    """Return apply-charmap metadata tokens.

    Do not use this map alone to encode 8x16 UI against an already-promoted
    ROM.  Relocated Hangul cells can drift from later allocator snapshots
    (으 metadata 0x018C currently paints 짊).  8x16 writers must recover
    slots from the painted font via ``ggen_advance_painted_glyph_identity``.
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    for row in value.get("assignments", []):
        char = str(row.get("char") or "")
        slot = int(str(row.get("slot")), 16)
        token = slot if slot <= 0xDF else 0xDF20 + slot
        if char:
            result[char] = token
    return result


def encode_literal(text: str, tokens: dict[str, int]) -> bytes:
    out = bytearray()
    for char in text:
        if char == " ":
            out.append(0x01)
            continue
        token = tokens.get(char)
        gate(token is not None, f"missing apply token for {char!r}")
        if token <= 0xDF:
            out.append(token)
        else:
            gate(0xE000 <= token <= 0xEFFF, f"invalid literal token for {char!r}: 0x{token:04X}")
            out.extend((token >> 8, token & 0xFF))
    out.append(0)
    return bytes(out)


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--translation-source", type=Path, default=TRANSLATION_MERGED_JSON)
    parser.add_argument("--translation-out", type=Path, default=ROOT / "analysis" / "ggen_advance_translation_merged_20260904_intermission_text.json")
    parser.add_argument("--input", type=Path, default=MAIN_TIP_ROM)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "20260904_ggen_advance_intermission_text_consumers" / "ggen_advance_intermission_text_consumers_candidate_20260904.gba")
    parser.add_argument("--manifest", type=Path, default=ROOT / "analysis" / "ggen_advance_intermission_text_consumers_20260904.json")
    parser.add_argument("--apply-charmap", type=Path, default=ROOT / "analysis" / "ggen_advance_korean_apply_charmap_20260844.json")
    args = parser.parse_args()

    original = ORIGINAL_ROM.read_bytes()
    current = args.input.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "approved main TIP must be 32 MiB")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")

    merged = json.loads(args.translation_source.read_text(encoding="utf-8"))
    by_id = {str(row.get("record_id")): row for row in merged["records"]}
    gate(TARGET_RECORD_ID in by_id, "stage title record missing")
    target = by_id[TARGET_RECORD_ID]
    gate(target.get("source_text") == "<0145>戦<00A8>", "stage title source decode drift")
    gate(target.get("raw_hex") == TARGET_ORIGINAL_RAW.hex(" ").upper(), "stage title raw bytes drift")
    gate(target.get("translation_status") == "pending", "stage title is no longer pending")
    gate(target.get("owner_ids") == ["OWNER-U32-00FCE304"], "stage title owner drift")

    # Static consumers: help uses FCE128[index], location uses current-search
    # record +0x10, and the title uses the adjacent FCE2D8 pair at slot 11.
    gate(u32(original, 0x00065454) == ROM_BASE + FCE128_TABLE, "FCE128 literal drift")
    gate(bl_target(original, FCE128_CALL) == DRAW_WRAPPER, "FCE128 draw consumer drift")
    gate(bl_target(original, SEARCH_LOCATION_CALL) == DRAW_WRAPPER, "search-location draw consumer drift")
    gate(u32(original, TARGET_OWNER) == TARGET_ORIGINAL_ADDRESS, "FCE2D8 title owner drift")
    for call in FCE2D8_DRAW_CALLS:
        gate(bl_target(original, call) == DRAW_WRAPPER, f"FCE2D8 draw consumer drift at 0x{call:08X}")

    tokens = load_apply_tokens(args.apply_charmap)
    title_payload = encode_literal(TARGET_KOREAN, tokens)
    gate(title_payload == bytes.fromhex("E5 15 E6 CD E6 BD 00"), "stage title encoding drift")

    audited: dict[str, Any] = {}
    reencoded: dict[str, tuple[list[int], int, bytes]] = {}
    for name, record_id in AUDIT_RECORDS.items():
        row = by_id[record_id]
        gate(row.get("translation_status") == "translated", f"{name} translation is not ready")
        expected = encode_literal(str(row["translation_ko"]), tokens)
        owner_offsets = [int(value.removeprefix("OWNER-U32-"), 16) for value in row.get("owner_ids", [])]
        pointers = [u32(current, owner) for owner in owner_offsets]
        gate(pointers and len(set(pointers)) == 1, f"{name} owners do not converge")
        active_payload = payload_at(current, pointers[0])
        if active_payload != expected:
            gate(name in REENCODE_OFFSETS, f"{name} active payload does not match current charmap")
            reencoded[name] = (owner_offsets, REENCODE_OFFSETS[name], expected)
        audited[name] = {
            "record_id": record_id,
            "source_text": row["source_text"],
            "translation_ko": row["translation_ko"],
            "owner_offsets": [f"0x{owner:08X}" for owner in owner_offsets],
            "active_address": f"0x{pointers[0]:08X}",
            "active_payload_hex": active_payload.hex(" ").upper(),
            "current_charmap_payload_hex": expected.hex(" ").upper(),
            "status": "already_active_in_main_tip" if active_payload == expected else "stale_font_slots_reencoded",
        }

    gate(all(value == 0 for value in current[TARGET_PAYLOAD_OFFSET : TARGET_PAYLOAD_OFFSET + 0x100]), "target allocation is not zero-filled")
    candidate = bytearray(current)
    struct.pack_into("<I", candidate, TARGET_OWNER, TARGET_PAYLOAD_ADDRESS)
    candidate[TARGET_PAYLOAD_OFFSET : TARGET_PAYLOAD_OFFSET + len(title_payload)] = title_payload
    for _name, (owner_offsets, payload_offset, payload) in reencoded.items():
        candidate[payload_offset : payload_offset + len(payload)] = payload
        for owner in owner_offsets:
            struct.pack_into("<I", candidate, owner, ROM_BASE + payload_offset)
    gate(u32(candidate, TARGET_OWNER) == TARGET_PAYLOAD_ADDRESS, "stage title owner patch failed")
    gate(payload_at(candidate, TARGET_PAYLOAD_ADDRESS) == title_payload, "stage title payload patch failed")
    for name, (owner_offsets, payload_offset, payload) in reencoded.items():
        gate(all(u32(candidate, owner) == ROM_BASE + payload_offset for owner in owner_offsets), f"{name} owner redirect failed")
        gate(payload_at(candidate, ROM_BASE + payload_offset) == payload, f"{name} payload patch failed")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    allowed = set(range(TARGET_OWNER, TARGET_OWNER + 4)) | set(range(TARGET_PAYLOAD_OFFSET, TARGET_PAYLOAD_OFFSET + len(title_payload)))
    for owner_offsets, payload_offset, payload in reencoded.values():
        allowed.update(range(payload_offset, payload_offset + len(payload)))
        for owner in owner_offsets:
            allowed.update(range(owner, owner + 4))
    gate(set(changed) <= allowed, "candidate changed bytes outside targeted owner/payload")

    before = {key: target.get(key) for key in ("source_text", "source_decode_status", "source_unresolved_slots", "translation_ko", "translation_status", "review_status", "qa_status")}
    target["source_text"] = TARGET_SOURCE
    target["source_decode_status"] = "complete"
    target["source_unresolved_slots"] = []
    target["baseline_translation_ko"] = TARGET_KOREAN
    target["baseline_translation_status"] = "translated"
    target["translation_ko"] = TARGET_KOREAN
    target["translation_status"] = "translated"
    target["translation_source"] = "user_verified_runtime_screenshot"
    target["review_status"] = "user_verified"
    target["review_count"] = int(target.get("review_count") or 0) + 1
    target["reviewed_at"] = "2026-09-04"
    target["translator_notes"] = "첨부 화면과 FCE2D8 slot 11 owner 0x00FCE304 정적 추적으로 哀戦士를 확정하고 애전사로 번역"
    target["qa_status"] = "static_consumer_verified"
    target["overlay_batch_id"] = BATCH_ID
    update_payload_hash(target)

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [{"record_id": TARGET_RECORD_ID, "payload": target["translation_payload_sha256"]}]})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["intermission_text_consumers_identity_sha256"] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = counts
    summary["translation_overlay_identity_sha256"] = new_identity
    summary["intermission_text_consumer_records"] = 1
    merged["intermission_text_consumers"] = {
        "batch_id": BATCH_ID,
        "changed_records": 1,
        "identity_sha256": new_identity,
        "static_consumer_report": advance_relative(args.manifest),
    }

    args.translation_out.parent.mkdir(parents=True, exist_ok=True)
    args.translation_out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(candidate)

    report = {
        "schema_version": 1,
        "kind": "ggen_advance_intermission_text_consumers_candidate_20260904",
        "source": {
            "main_tip": advance_relative(args.input),
            "main_tip_sha256": sha256(current),
            "translation_source": advance_relative(args.translation_source),
        },
        "static_consumers": {
            "map_system_help": {"table": "0x00FCE128", "call": "0x08065446", "draw": "0x08000CA0", "records": [AUDIT_RECORDS["advance_help"], AUDIT_RECORDS["search_help"]]},
            "current_search_location": {"owner": "search_record+0x10", "call": "0x0801C63E", "draw": "0x08000CA0", "record": AUDIT_RECORDS["odessa"]},
            "stage_title": {"table": "0x00FCE2D8", "pair_slot": 11, "owner": f"0x{TARGET_OWNER:08X}", "record": TARGET_RECORD_ID},
        },
        "already_active_translations": audited,
        "translation_change": {
            "record_id": TARGET_RECORD_ID,
            "before": before,
            "source_text": TARGET_SOURCE,
            "translation_ko": TARGET_KOREAN,
            "translation_payload_sha256": target["translation_payload_sha256"],
            "translation_snapshot": advance_relative(args.translation_out),
        },
        "patch": {
            "owner_offset": f"0x{TARGET_OWNER:08X}",
            "old_address": f"0x{u32(current, TARGET_OWNER):08X}",
            "new_address": f"0x{TARGET_PAYLOAD_ADDRESS:08X}",
            "payload_offset": f"0x{TARGET_PAYLOAD_OFFSET:08X}",
            "payload_hex": title_payload.hex(" ").upper(),
            "reencoded_help": {
                name: {
                    "owner_offsets": [f"0x{owner:08X}" for owner in owner_offsets],
                    "payload_offset": f"0x{payload_offset:08X}",
                    "payload_hex": payload.hex(" ").upper(),
                }
                for name, (owner_offsets, payload_offset, payload) in reencoded.items()
            },
            "changed_bytes": len(changed),
        },
        "output": {"path": advance_relative(args.out), "size": len(candidate), "sha256": sha256(candidate)},
        "verification": {
            "result": "PASS",
            "static_consumers_verified": True,
            "translated_help_and_location_payloads_match_current_charmap": True,
            "stale_help_payloads_reencoded": sorted(reencoded),
            "stage_title_owner_redirected": True,
            "stage_title_payload_is_korean": True,
            "only_target_owner_and_zero_cave_mutated": True,
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current),
            "stale_state_warning": "mGBA save states embed VRAM. Cold boot from .sav or re-enter the screen after loading .ss* before judging the ROM text path.",
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "candidate": advance_relative(args.out), "candidate_sha256": sha256(candidate), "translation_snapshot": advance_relative(args.translation_out), "changed_bytes": len(changed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
