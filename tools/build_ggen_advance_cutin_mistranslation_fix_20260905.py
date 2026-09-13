#!/usr/bin/env python3
"""Fix Master Asia 大当り=대박 and Funnel=퍼넬 mistranslations on the cut-in candidate.

- 十二王方牌大当たり second line: 대박이다아앗!! → 대차병！！
- ファンネル / フィン・ファンネル weapon names: 퍼넬 → 판넬, 핀 퍼넬 → 핀 판넬
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

import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from build_ggen_advance_battle_cutin_quotes_20260905 import (  # noqa: E402
    parse_blocks,
    rebuild_container,
    verify_hangul_and_nu,
)
from extract_ggen_advance_id_command_battle_barks import load_slot_map  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    load_galmuri12,
    load_galmuri8,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
    verify_payload_painted,
)
from ggen_advance_project_paths import (  # noqa: E402
    ORIGINAL_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, load_dictionary  # noqa: E402
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import find_lookup, payload_until_nul  # noqa: E402

ROM_BASE = 0x08000000
TABLE = 0x00228600
PAYLOAD_LO = 0x00228184
CAVE_START = 0x012A2800
CAVE_END = 0x012A6000
PARENT_ROM = (
    ROOT
    / "outputs"
    / "20260905_ggen_advance_battle_cutin_quotes"
    / "ggen_advance_battle_cutin_quotes_ko_candidate_20260905.gba"
)
PARENT_SAV = PARENT_ROM.with_suffix(".sav")
PARENT_MANIFEST = ROOT / "analysis" / "ggen_advance_battle_cutin_quotes_ko_candidate_20260905.json"
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
CORR = ROOT / "analysis" / "ggen_advance_12x12_runtime_measurement_corrections_20260829.json"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_cutin_mistranslation_fix"
OUT_ROM = OUT_DIR / "ggen_advance_cutin_mistranslation_fix_candidate_20260905.gba"
OUT_SAV = OUT_DIR / "ggen_advance_cutin_mistranslation_fix_candidate_20260905.sav"
OUT_MANIFEST = ROOT / "analysis" / "ggen_advance_cutin_mistranslation_fix_candidate_20260905.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260905_funnel_daechabyeong.json"
CUTIN_OVERLAY = ROOT / "integrated" / "translation" / "ggen_advance_battle_cutin_quotes.json"
BATCH_ID = "funnel-panel-daechabyeong-20260905"
SUFFIX_E733 = bytes((0xE7, 0x33))

RECORD_FIXES = {
    "GGA-MAPSCRIPT-00F54561": {
        "translation_ko": "대차병！！",
        "translation_segments": ["대차병！！"],
        "font": "12x12",
    },
    "GGA-TEXT-0017A34F": {
        "translation_ko": "판넬",
        "font": "8x16",
    },
    "GGA-TEXT-0017A602": {
        "translation_ko": "핀 판넬",
        "font": "8x16",
    },
}


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def hangul_chars(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


def update_payload_hash(row: dict[str, Any]) -> None:
    row["overlay_batch_id"] = BATCH_ID
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["reviewed_at"] = "2026-09-05"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["translator_notes"] = (
        "Master Asia 大当り→대차병; ファンネル→판넬 / フィン・ファンネル→핀 판넬"
    )
    row["qa_status"] = "user_verified_term"
    row["translation_payload_sha256"] = translation_payload_digest(
        {
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
    )


def split_weapon_suffix(payload: bytes) -> tuple[bytes, bytes]:
    gate(payload.endswith(b"\x00"), "weapon payload missing NUL")
    body = payload[:-1]
    if body.endswith(SUFFIX_E733):
        return body[: -len(SUFFIX_E733)] + b"\x00", SUFFIX_E733
    return payload, b""


def write_payload(
    candidate: bytearray,
    address: int,
    encoded: bytes,
    old_size: int,
    allowed: set[int],
    cursor: int,
) -> tuple[int, int]:
    gate(encoded.endswith(b"\x00") or True, "encoded payload")
    if old_size > 0 and len(encoded) <= old_size:
        start = address - ROM_BASE
        candidate[start : start + len(encoded)] = encoded
        if len(encoded) < old_size:
            candidate[start + len(encoded) : start + old_size] = b"\x00" * (old_size - len(encoded))
        allowed.update(range(start, start + old_size))
        return address, cursor
    gate(cursor + len(encoded) <= CAVE_END, "mistranslation cave exhausted")
    start = cursor
    candidate[start : start + len(encoded)] = encoded
    allowed.update(range(start, start + len(encoded)))
    return ROM_BASE + start, (start + len(encoded) + 3) & ~3


def owner_offsets(row: dict[str, Any]) -> list[int]:
    return [
        int(owner.removeprefix("OWNER-U32-"), 16)
        for owner in row.get("owner_ids", [])
        if str(owner).startswith("OWNER-U32-")
    ]


def update_translation_manifest(merged: dict[str, Any], snapshot: Path) -> None:
    manifest = json.loads(TRANSLATION_MANIFEST.read_text(encoding="utf-8"))
    merged_sha = sha256(TRANSLATION_MERGED_JSON.read_bytes())
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    manifest.update(
        {
            "source_snapshot": advance_relative(snapshot),
            "sha256": merged_sha,
            "source_sha256": merged_sha,
            "record_count": len(merged["records"]),
            "record_identity_sha256": merged.get("identity", {}).get("record_identity_sha256"),
            "translation_overlay_identity_sha256": merged.get("identity", {}).get(
                "translation_overlay_identity_sha256"
            ),
            "record_translation_status_counts": counts,
            "source_summary_translation_status_counts": counts,
        }
    )
    TRANSLATION_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parent = PARENT_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    parent_manifest = json.loads(PARENT_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    overlay = json.loads(CUTIN_OVERLAY.read_text(encoding="utf-8"))
    gate(sha256(parent) == parent_manifest["output"]["sha256"], "cut-in parent/manifest drift")
    gate(all(value == 0 for value in parent[CAVE_START:CAVE_END]), "mistranslation cave is not zero-filled")

    leftover = [
        row["record_id"]
        for row in merged["records"]
        if "퍼넬" in str(row.get("translation_ko") or "")
        or "퍼넬" in "".join(str(x) for x in (row.get("translation_segments") or []))
    ]
    gate(set(leftover) <= {"GGA-TEXT-0017A34F", "GGA-TEXT-0017A602"}, f"unexpected 퍼넬 rows: {leftover}")

    by_id = {row["record_id"]: row for row in merged["records"]}
    hangul12: set[str] = set()
    hangul8: set[str] = set()
    for record_id, fix in RECORD_FIXES.items():
        row = by_id[record_id]
        chars = hangul_chars(fix["translation_ko"])
        if fix["font"] == "12x12":
            hangul12 |= chars
        else:
            hangul8 |= chars

    font12 = load_galmuri12()
    font8 = load_galmuri8()
    recovered12 = recover_unique_12x12_slots(parent, font12, hangul12)
    recovered8 = recover_unique_8x16_slots(parent, font8, hangul8)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    map12 = load_slot_map(MAP12, CORR)
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)

    candidate = bytearray(parent)
    allowed: set[int] = set()
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []

    for record_id, fix in RECORD_FIXES.items():
        row = by_id[record_id]
        before = str(row["translation_ko"] or "")
        after = fix["translation_ko"]
        gate(before != after, f"{record_id} already has the corrected KO")
        row["translation_ko"] = after
        if "translation_segments" in fix:
            row["translation_segments"] = list(fix["translation_segments"])
        update_payload_hash(row)
        if fix["font"] == "12x12":
            encoded, missing = unified.encode_korean_text(
                after, recovered12, verified_charmap=verified12, strict_punctuation=True
            )
            gate(encoded is not None and not missing, f"12x12 encode failed {record_id}: {missing}")
            assert encoded is not None
            verify_hangul_and_nu(candidate, encoded, after, font12, japan)
            orig = ROM_BASE + int(row["target_file_offset"], 16)
            original = bytes.fromhex(str(row["segments"][0]["raw_hex"]).replace(" ", ""))
            lookup_pos, neu, _orig_end = find_lookup(parent, orig, orig + len(original) - 1)
            old_payload = payload_until_nul(parent, neu)
            new_addr, cave_cursor = write_payload(
                candidate, neu, encoded, len(old_payload), allowed, cave_cursor
            )
            if new_addr != neu:
                struct.pack_into("<I", candidate, lookup_pos + 4, new_addr)
                allowed.update(range(lookup_pos + 4, lookup_pos + 8))
            evidence.append(
                {
                    "record_id": record_id,
                    "before": before,
                    "after": after,
                    "path": "map_script_lookup",
                    "old_address": f"0x{neu:08X}",
                    "new_address": f"0x{new_addr:08X}",
                }
            )
            continue

        encoded, missing = unified.encode_korean_text(
            after, recovered8, verified_charmap=verified8, strict_punctuation=False
        )
        gate(encoded is not None and not missing, f"8x16 encode failed {record_id}: {missing}")
        assert encoded is not None
        hangul_only = "".join(char for char in after if char != " ")
        verify_payload_painted(candidate, encoded, hangul_only, font8)
        owners = owner_offsets(row)
        pointers = [u32(parent, owner) for owner in owners]
        gate(pointers and len(set(pointers)) == 1, f"{record_id} owners do not converge")
        live = payload_until_nul(parent, pointers[0], limit=32)
        _core, suffix = split_weapon_suffix(live)
        payload = encoded[:-1] + suffix + b"\x00"
        new_addr, cave_cursor = write_payload(
            candidate, pointers[0], payload, len(live), allowed, cave_cursor
        )
        if new_addr != pointers[0]:
            for owner in owners:
                struct.pack_into("<I", candidate, owner, new_addr)
                allowed.update(range(owner, owner + 4))
        evidence.append(
            {
                "record_id": record_id,
                "before": before,
                "after": after,
                "path": "production_weapon",
                "old_address": f"0x{pointers[0]:08X}",
                "new_address": f"0x{new_addr:08X}",
                "preserved_e733_suffix": bool(suffix),
            }
        )

    leftover_after = [
        row["record_id"]
        for row in merged["records"]
        if "퍼넬" in str(row.get("translation_ko") or "")
        or "퍼넬" in "".join(str(x) for x in (row.get("translation_segments") or []))
        or "대박이다" in str(row.get("translation_ko") or "")
    ]
    gate(not leftover_after, f"leftover 퍼넬/대박이다: {leftover_after}")

    ptrs: list[tuple[int, int]] = []
    off = TABLE
    while off + 4 <= len(japan):
        val = u32(japan, off)
        dest = val - ROM_BASE
        if not (PAYLOAD_LO <= dest < TABLE):
            break
        ptrs.append((off, dest))
        off += 4
    src, start = ptrs[17]
    boundary = ptrs[18][1]
    parsed = parse_blocks(japan, start, boundary, dictionary, map12)
    gate(parsed["streams"][0]["source_text"] == "大当りいいいんっ！！", "cut-in index 17 is not 大当り")
    ko = RECORD_FIXES["GGA-MAPSCRIPT-00F54561"]["translation_ko"]
    encoded, missing = unified.encode_korean_text(
        ko, recovered12, verified_charmap=verified12, strict_punctuation=True
    )
    gate(encoded is not None and not missing, f"cut-in 大当り encode failed: {missing}")
    assert encoded is not None
    original = japan[start:boundary]
    rebuilt = rebuild_container(
        original,
        start,
        parsed,
        {int(parsed["streams"][0]["start_file_offset"], 16): encoded},
    )
    live_ptr = u32(parent, src)
    gate(cave_cursor + len(rebuilt) <= CAVE_END, "cut-in container cave exhausted")
    start_off = cave_cursor
    candidate[start_off : start_off + len(rebuilt)] = rebuilt
    allowed.update(range(start_off, start_off + len(rebuilt)))
    new_addr = ROM_BASE + start_off
    cave_cursor = (start_off + len(rebuilt) + 3) & ~3
    struct.pack_into("<I", candidate, src, new_addr)
    allowed.update(range(src, src + 4))
    evidence.append(
        {
            "record_id": "GGA-BATTLECUTIN-002283CE",
            "before": "대박이다아앗!!",
            "after": ko,
            "path": "battle_cutin_container_17",
            "old_address": f"0x{live_ptr:08X}",
            "new_address": f"0x{new_addr:08X}",
            "new_size": len(rebuilt),
        }
    )
    for row in overlay["records"]:
        if row.get("record_id") == "GGA-BATTLECUTIN-002283CE":
            row["translation_ko"] = ko
            row["translation_source"] = "user_verified:대차병"

    parent_overlay = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent_overlay,
            "batch_id": BATCH_ID,
            "records": [
                {"record_id": record_id, "payload": by_id[record_id]["translation_payload_sha256"]}
                for record_id in RECORD_FIXES
            ],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent_overlay
    merged["identity"]["funnel_panel_daechabyeong_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity

    changed = [index for index, (before, after) in enumerate(zip(parent, candidate)) if before != after]
    stray = sorted(set(changed) - allowed)
    gate(set(changed) <= allowed, f"changed outside targets: {[hex(off) for off in stray[:12]]}")
    gate(candidate[PAYLOAD_LO:TABLE] == japan[PAYLOAD_LO:TABLE], "original cut-in payloads changed")

    out = bytes(candidate)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    if PARENT_SAV.is_file():
        shutil.copy2(PARENT_SAV, OUT_SAV)
    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CUTIN_OVERLAY.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_cutin_mistranslation_fix_candidate_20260905",
        "result": "PASS",
        "base": {
            "path": advance_relative(PARENT_ROM),
            "sha256": sha256(parent),
        },
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "size": len(out),
            "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
        },
        "fixes": evidence,
        "verification": {
            "result": "PASS",
            "no_퍼넬_in_merged": True,
            "no_대박이다_in_merged": True,
            "changed_bytes": len(changed),
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "rom": advance_relative(OUT_ROM),
                "sha256": sha256(out),
                "changed_bytes": len(changed),
                "fixes": evidence,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
