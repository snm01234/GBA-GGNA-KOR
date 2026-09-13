"""Fix the two ID-command descriptions that encode ∀ with slot 0x07DC.

The 12x12 renderer must use slot 0x071B for the Turn A forall glyph.  The two
relative-pair descriptions for the Turn A abilities were instead encoded with
0x07DC, a slot belonging to a different glyph in this font mode.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import ggen_advance_painted_glyph_identity as glyph  # noqa: E402
import patch_ggen_advance_apsaras_zentetsu_20260908 as aps  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import (  # noqa: E402
    DICT_12X12_BASE,
    DICT_12X12_END,
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import raw_hex_bytes  # noqa: E402

BATCH_ID = "idcmd-forall-token-20260912"
IDENTITY_KEY = "idcmd_forall_token_20260912_sha256"
BATCH_KEY = "idcmd_forall_token_20260912"
OUT = ROOT / "outputs" / "20260912_idcmd_forall_token"
WORK = OUT / "ggen_idcmd_forall_token_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_idcmd_forall_token.json"

RELATIVE_BASE_LITERAL = 0x0004DC54
RELATIVE_OLD_BASE = 0x001BF908
TURN_A_SLOT_12 = 0x071B
WRONG_SLOT_12 = 0x07DC
WRONG_TOKEN = bytes.fromhex("E6 FC")
RIGHT_TOKEN = bytes.fromhex("E6 3B")
TARGETS = {
    "GGA-TEXT-001C5C7F": 0x001BFDB6,
    "GGA-TEXT-001C5DA4": 0x001BFDC2,
}
OTHER_U32_12 = {
    "profile_turn_a": 0x001B433C,
    "profile_loran_a": 0x001AF8C0,
    "profile_loran_b": 0x001AF92C,
}
OTHER_MAP_12 = ("GGA-MAPSCRIPT-00F910F8", "GGA-MAPSCRIPT-00F91189")


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def relative_line(rom: bytes | bytearray, owner: int) -> tuple[int, bytes]:
    base = u32(rom, RELATIVE_BASE_LITERAL) - ROM_BASE
    gate(base == 0x01040000, f"relative block base drift: 0x{base:08X}")
    rel = owner - RELATIVE_OLD_BASE
    start = base + u16(rom, base + rel)
    end = base + u16(rom, base + rel + 2)
    blob = bytes(rom[start:end])
    nul = blob.find(b"\0")
    gate(nul >= 0, f"first relative line has no terminator at 0x{start:08X}")
    return start, blob[: nul + 1]


def slots_at(rom: bytes | bytearray, offset: int, dictionary: list[list[int]]) -> list[int]:
    return expand_to_slots(read_tokens(bytes(rom), offset)[0], dictionary)


def update_row(row: dict[str, Any]) -> None:
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = "ID커맨드 12x12 ∀ 오인코딩 0x07DC→0x071B 수정"
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = False
    update_payload_hash(row)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == str(manifest.get("sha256") or ""), "main TIP sha mismatch")
    gate(sha256(parent) == "b34d28962e9c4d9ce92cba59b18b7191100836bc4838b7b941e084cc2f27827d", "rollback parent is not active")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    dictionary = load_dictionary(parent, DICT_12X12_BASE, DICT_12X12_END)
    candidate = bytearray(parent)
    allowed: set[int] = set()
    evidence: list[dict[str, Any]] = []

    for record_id, owner in TARGETS.items():
        gate(record_id in by_id, f"missing translation row {record_id}")
        gate(str(by_id[record_id].get("translation_ko") or "") == "3턴 동안 ∀건담의", f"translation drift {record_id}")
        start, line = relative_line(parent, owner)
        before_slots = slots_at(parent, start, dictionary)
        gate(before_slots.count(WRONG_SLOT_12) == 1, f"wrong-slot count drift {record_id}: {before_slots}")
        gate(TURN_A_SLOT_12 not in before_slots, f"target already uses 0x071B {record_id}")
        token_at = line.find(WRONG_TOKEN)
        gate(token_at >= 0 and line.find(WRONG_TOKEN, token_at + 1) < 0, f"wrong token ambiguity {record_id}")
        patch_at = start + token_at
        candidate[patch_at : patch_at + 2] = RIGHT_TOKEN
        allowed.update(range(patch_at, patch_at + 2))
        after_slots = slots_at(candidate, start, dictionary)
        gate(after_slots.count(TURN_A_SLOT_12) == 1, f"0x071B missing after patch {record_id}")
        gate(WRONG_SLOT_12 not in after_slots, f"0x07DC remains after patch {record_id}")
        update_row(by_id[record_id])
        evidence.append(
            {
                "record_id": record_id,
                "owner": f"0x{owner:08X}",
                "line_offset": f"0x{start:08X}",
                "token_offset": f"0x{patch_at:08X}",
                "before_slot": f"0x{WRONG_SLOT_12:04X}",
                "after_slot": f"0x{TURN_A_SLOT_12:04X}",
            }
        )

    other_consumers: list[dict[str, Any]] = []
    for label, owner in OTHER_U32_12.items():
        pointer = u32(candidate, owner)
        slots = slots_at(candidate, pointer - ROM_BASE, dictionary)
        gate(TURN_A_SLOT_12 in slots and WRONG_SLOT_12 not in slots, f"similar U32 consumer drift {label}: {slots}")
        other_consumers.append({"consumer": label, "owner": f"0x{owner:08X}", "slot": "0x071B", "status": "already_correct"})

    for record_id in OTHER_MAP_12:
        row = by_id[record_id]
        raw = raw_hex_bytes(str(row["segments"][0]["raw_hex"]))
        original = ROM_BASE + int(str(row["target_file_offset"]), 16)
        hits = aps.find_lookups(bytes(candidate), original, original + len(raw) - 1)
        pointer = hits[0][1]
        slots = slots_at(candidate, pointer - ROM_BASE, dictionary)
        gate(TURN_A_SLOT_12 in slots and WRONG_SLOT_12 not in slots, f"similar map consumer drift {record_id}: {slots}")
        other_consumers.append({"consumer": record_id, "pointer": f"0x{pointer:08X}", "slot": "0x071B", "status": "already_correct"})

    font12_before = glyph.slot_raw(parent, glyph.FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE)
    font8_before = glyph.slot_raw(parent, glyph.FONT8_RELOCATED, 0x07E3, fontops.FONT_8X16_STRIDE)
    gate(glyph.slot_raw(candidate, glyph.FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE) == font12_before, "12x12 glyph changed")
    gate(glyph.slot_raw(candidate, glyph.FONT8_RELOCATED, 0x07E3, fontops.FONT_8X16_STRIDE) == font8_before, "8x16 glyph changed")

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes: {len(changed - allowed)}")
    gate(len(changed) == 2, f"expected two changed token bytes, got {len(changed)}")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": sorted(TARGETS)})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = dict(
        sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items())
    )
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": sorted(TARGETS), "evidence": evidence}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_idcmd_forall_token",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(candidate)},
        "evidence": evidence,
        "similar_case_audit": {
            "bad_idcmd_consumers_fixed": len(evidence),
            "other_12x12_consumers_checked": len(other_consumers),
            "other_consumers": other_consumers,
            "additional_wrong_0x07DC_consumers": 0,
        },
        "changed_bytes": len(changed),
        "verification": {
            "result": "PASS",
            "idcmd_07dc_replaced_with_071b": True,
            "forall_glyph_bitmaps_unchanged": True,
            "other_12x12_forall_consumers_already_correct": True,
            "unrelated_bytes_preserved": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
