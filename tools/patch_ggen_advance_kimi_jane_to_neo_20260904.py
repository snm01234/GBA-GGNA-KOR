#!/usr/bin/env python3
"""Rewrite non-하게체 자네 (from きみ/君) to 너/네가/너희 and patch main TIP.

하게체 endings (걸세, 게야, 건가/겐가/인가, 하네, 좋네, 있게, 기다리게, …)
keep 자네.  All other sentence registers become 너/네가/너희.
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
from ggen_advance_painted_glyph_identity import load_galmuri12, recover_unique_12x12_slots  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import sha256  # noqa: E402
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    encode_map_korean_line,
    load_identified_12x12,
    raw_hex_bytes,
)

ROM_BASE = 0x08000000
BATCH_ID = "kimi-jane-to-neo-hage-20260904"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260904_kimi_jane_to_neo.json"
OUTPUT = (
    ROOT
    / "outputs"
    / "20260904_ggen_advance_kimi_jane_to_neo"
    / "ggen_advance_kimi_jane_to_neo_candidate_20260904.gba"
)
OUT_SAV = OUTPUT.with_suffix(".sav")
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_kimi_jane_to_neo_20260904.json"
CAVE_START = 0x01290800
CAVE_END = 0x01294000
MAP_BANK = (0x00F00000, 0x00FC0000)

# 문장 전체가 하게체인 레코드만 자네를 유지한다.
HAGE_KEEP = {
    "GGA-MAPSCRIPT-00F5B0AB",  # 장난하는 건가
    "GGA-MAPSCRIPT-00F6138B",  # 좋을걸세
    "GGA-MAPSCRIPT-00F6140F",  # 게야
    "GGA-MAPSCRIPT-00F616EF",
    "GGA-MAPSCRIPT-00F61773",
    "GGA-MAPSCRIPT-00F680FA",  # 파일럿인가
    "GGA-MAPSCRIPT-00F854D5",  # 법정인가
    "GGA-MAPSCRIPT-00F881C8",  # 기다리게 / 오누시
    "GGA-MAPSCRIPT-00F88CF0",  # 수밖에없네
    "GGA-MAPSCRIPT-00F89A3C",  # 맡아줬으면하네
    "GGA-MAPSCRIPT-00F89A70",  # 모였네
    "GGA-MAPSCRIPT-00F89B05",  # 편이 좋네
    "GGA-MAPSCRIPT-00F8CA09",  # 자네인가
    "GGA-MAPSCRIPT-00F8CFB4",  # 있는 겐가
    "GGA-MAPSCRIPT-00F8DE08",  # 부탁하네
    "GGA-MAPSCRIPT-00F90F10",  # 시녀인가
    "GGA-MAPSCRIPT-00F91B16",  # 일어나는 건가
    "GGA-MAPSCRIPT-00F96DC6",  # 것은가
    "GGA-MAPSCRIPT-00FA3D16",  # 하겠다는 겐가
    "GGA-MAPSCRIPT-00FA3EAB",  # 맡기겠네
    "GGA-MAPSCRIPT-00FAC3AA",  # 자네인가
    "GGA-MAPSCRIPT-00FB74E4",  # 빠져 있게
    "GGA-MAPSCRIPT-00FBE040",  # 했다는건가
}

REPLACEMENTS = [
    ("자네들이라면", "너희들이라면"),
    ("자네들에게도", "너희에게도"),
    ("자네들에게", "너희에게"),
    ("자네들의", "너희의"),
    ("자네들을", "너희를"),
    ("자네들은", "너희는"),
    ("자네들도", "너희도"),
    ("자네들과", "너희와"),
    ("자네들만으로", "너희만으로"),
    ("자네들만", "너희만"),
    ("자네들", "너희들"),
    ("자네에게도", "너에게도"),
    ("자네에게", "너에게"),
    ("자네에겐", "너에겐"),
    ("자네가", "네가"),
    ("자네는", "너는"),
    ("자네를", "너를"),
    ("자네의", "너의"),
    ("자네도", "너도"),
    ("자네와", "너와"),
    ("자네랑", "너랑"),
    ("자네만", "너만"),
    ("자네야", "너야"),
    ("자네처럼", "너처럼"),
    ("자네 같은", "너 같은"),
    ("자네 마음", "너 마음"),
    ("자네 말대로", "너 말대로"),
    ("자네 친구", "네 친구"),
    ("자네", "너"),
]


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def rewrite_jane(text: str) -> str:
    out = text
    for old, new in REPLACEMENTS:
        out = out.replace(old, new)
    return out


def update_payload_hash(row: dict[str, Any]) -> None:
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
            "translation_overlay_identity_sha256": merged.get("identity", {}).get("translation_overlay_identity_sha256"),
            "record_translation_status_counts": counts,
            "source_summary_translation_status_counts": counts,
        }
    )
    TRANSLATION_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def owner_offsets(row: dict[str, Any]) -> tuple[int, ...]:
    return tuple(
        int(owner.removeprefix("OWNER-U32-"), 16)
        for owner in row.get("owner_ids", [])
        if str(owner).startswith("OWNER-U32-")
    )


def find_lookup(rom: bytes, orig_addr: int, expected_end: int) -> tuple[int, int, int]:
    key = struct.pack("<I", orig_addr)
    hits: list[tuple[int, int, int]] = []
    cursor = 0
    while True:
        pos = rom.find(key, cursor)
        if pos < 0:
            break
        if pos + 12 <= len(rom):
            orig, neu, orig_end = struct.unpack_from("<III", rom, pos)
            if orig == orig_addr and orig_end == expected_end and 0x09000000 <= neu < 0x0A000000:
                hits.append((pos, neu, orig_end))
        cursor = pos + 1
    gate(len(hits) == 1, f"lookup drift for 0x{orig_addr:08X}: {len(hits)} hits")
    return hits[0]


def payload_until_nul(rom: bytes | bytearray, address: int, limit: int = 64) -> bytes:
    offset = address - ROM_BASE
    gate(0 <= offset < len(rom), f"payload outside ROM 0x{address:08X}")
    end = bytes(rom).find(0, offset, min(len(rom), offset + limit))
    gate(end >= 0, f"unterminated map payload 0x{address:08X}")
    return bytes(rom[offset : end + 1])


def write_payload(
    candidate: bytearray,
    address: int,
    encoded: bytes,
    old_size: int,
    allowed: set[int],
    cursor: int,
    *,
    require_nul: bool = True,
) -> tuple[int, int]:
    if require_nul:
        gate(encoded.endswith(b"\x00"), "encoded map payload missing NUL")
    if len(encoded) <= old_size:
        start = address - ROM_BASE
        candidate[start : start + len(encoded)] = encoded
        if len(encoded) < old_size:
            candidate[start + len(encoded) : start + old_size] = b"\x00" * (old_size - len(encoded))
        allowed.update(range(start, start + old_size))
        return address, cursor
    gate(cursor + len(encoded) <= CAVE_END, "kimi/jane cave exhausted")
    start = cursor
    candidate[start : start + len(encoded)] = encoded
    allowed.update(range(start, start + len(encoded)))
    return ROM_BASE + start, (start + len(encoded) + 3) & ~3


def apply_row_translation(row: dict[str, Any]) -> tuple[str, list[str]]:
    before = str(row.get("translation_ko") or "")
    segments = [str(item) for item in (row.get("translation_segments") or [])]
    after = rewrite_jane(before)
    new_segments = [rewrite_jane(item) if item else item for item in segments]
    gate("자네" not in after, f"rewrite leftover 자네: {row['record_id']}")
    gate(all("자네" not in item for item in new_segments), f"segment leftover 자네: {row['record_id']}")
    return after, new_segments


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    current = MAIN_TIP_ROM.read_bytes()
    original = ORIGINAL_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP is not 32 MiB")
    gate(sha256(current) == main_manifest["sha256"], "main TIP/manifest drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "kimi/jane cave is not zero-filled")

    by_id = {row["record_id"]: row for row in merged["records"]}
    targets = [row for row in merged["records"] if "자네" in str(row.get("translation_ko") or "")]
    gate(len(targets) == 120, f"자네 record count drift: {len(targets)}")
    keep_rows = [row for row in targets if row["record_id"] in HAGE_KEEP]
    change_rows = [row for row in targets if row["record_id"] not in HAGE_KEEP]
    gate(len(keep_rows) == 23, f"하게체 keep count drift: {len(keep_rows)}")
    gate(len(change_rows) == 97, f"change count drift: {len(change_rows)}")
    missing_keep = HAGE_KEEP - {row["record_id"] for row in keep_rows}
    gate(not missing_keep, f"missing keep ids: {sorted(missing_keep)}")

    hangul = {
        char
        for row in targets
        for text in [str(row.get("translation_ko") or ""), rewrite_jane(str(row.get("translation_ko") or ""))]
        for char in text
        if "가" <= char <= "힣"
    }
    font12 = load_galmuri12()
    recovered = recover_unique_12x12_slots(current, font12, hangul)
    identified = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)

    candidate = bytearray(current)
    allowed: set[int] = set()
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    map_changed = 0
    scenario_changed = 0

    for row in change_rows:
        before = str(row["translation_ko"] or "")
        after, new_segments = apply_row_translation(row)
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        gate(len(new_segments) == len(old_segments), f"segment count drift {row['record_id']}")
        row["translation_ko"] = after
        row["translation_segments"] = new_segments
        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-09-04"
        row["translator_notes"] = (
            "きみ/君 자네는 하게체 문장만 유지. 해체·해요체·해라체·하오체는 너/네가/너희"
        )
        row["qa_status"] = "pronoun_register_reviewed"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)

        if row.get("source_scope") == "scenario_map_script":
            segments = list(row.get("segments") or [])
            gate(len(segments) == len(new_segments), f"map segment framing drift {row['record_id']}")
            cursor = int(str(row["target_file_offset"]), 16)
            first_new_addr: int | None = None
            first_old_end: int | None = None
            written: list[dict[str, Any]] = []
            for index, (segment, old_text, new_text) in enumerate(zip(segments, old_segments, new_segments)):
                original_bytes = raw_hex_bytes(str(segment.get("raw_hex") or ""))
                gate(original_bytes.endswith(b"\x00"), f"map segment missing NUL {row['record_id']}")
                orig_addr = ROM_BASE + cursor
                orig_end = orig_addr + len(original_bytes) - 1
                lookup_pos, neu, table_end = find_lookup(current, orig_addr, orig_end)
                gate(table_end == orig_end, f"orig_end mismatch {row['record_id']}")
                old_payload = payload_until_nul(current, neu)
                encoded_old, missing_old = encode_map_korean_line(old_text, recovered, identified)
                gate(
                    encoded_old == old_payload and not missing_old,
                    f"live encode mismatch {row['record_id']}#{index}: "
                    f"{None if encoded_old is None else encoded_old.hex()} vs {old_payload.hex()} missing={missing_old}",
                )
                gate(
                    "\n" not in new_text and len(new_text) <= MAX_DIALOGUE_CELLS,
                    f"map dialogue width {row['record_id']}#{index} len={len(new_text)}",
                )
                encoded_new, missing_new = encode_map_korean_line(new_text, recovered, identified)
                gate(encoded_new is not None and not missing_new, f"encode failed {row['record_id']}: {missing_new}")
                new_addr, cave_cursor = write_payload(
                    candidate, neu, encoded_new, len(old_payload), allowed, cave_cursor
                )
                if new_addr != neu:
                    struct.pack_into("<I", candidate, lookup_pos + 4, new_addr)
                    allowed.update(range(lookup_pos + 4, lookup_pos + 8))
                if index == 0:
                    first_new_addr = new_addr
                    first_old_end = orig_end
                written.append(
                    {
                        "segment": index,
                        "old": old_text,
                        "new": new_text,
                        "old_payload": f"0x{neu:08X}",
                        "new_payload": f"0x{new_addr:08X}",
                        "encoded_size": len(encoded_new),
                    }
                )
                cursor += len(original_bytes)
            opcode_text = str(row.get("opcode_18_file_offset") or "")
            if opcode_text and first_new_addr is not None and first_old_end is not None:
                opcode_addr = ROM_BASE + int(opcode_text, 16)
                if opcode_addr != ROM_BASE + int(str(row["target_file_offset"]), 16):
                    alias_pos, alias_neu, _alias_end = find_lookup(current, opcode_addr, first_old_end)
                    if alias_neu != first_new_addr:
                        struct.pack_into("<I", candidate, alias_pos + 4, first_new_addr)
                        allowed.update(range(alias_pos + 4, alias_pos + 8))
            map_changed += 1
            evidence.append(
                {
                    "record_id": row["record_id"],
                    "source_scope": row["source_scope"],
                    "source_text": row.get("source_text"),
                    "before": before,
                    "after": after,
                    "segments": written,
                }
            )
            continue

        gate(row.get("source_scope") == "scenario_main", f"unexpected scope {row['record_id']}")
        old_row = dict(row)
        old_row["translation_segments"] = old_segments
        old_payload, old_missing = unified.rebuild_scenario_payload(
            old_row, recovered, verified12, translate=True
        )
        new_payload, new_missing = unified.rebuild_scenario_payload(
            row, recovered, verified12, translate=True
        )
        gate(old_payload is not None and not old_missing, f"scenario old rebuild failed {row['record_id']}: {old_missing}")
        gate(new_payload is not None and not new_missing, f"scenario new rebuild failed {row['record_id']}: {new_missing}")
        owners = owner_offsets(row)
        gate(owners, f"scenario has no U32 owners {row['record_id']}")
        old_addresses = []
        new_addr = None
        for owner in owners:
            pointer = struct.unpack_from("<I", current, owner)[0]
            file_off = pointer - ROM_BASE
            gate(0 <= file_off < len(current), f"owner pointer outside ROM {row['record_id']}")
            live = bytes(current[file_off : file_off + len(old_payload)])
            gate(live == old_payload, f"scenario live mismatch {row['record_id']} owner 0x{owner:08X}")
            old_addresses.append(pointer)
            written_addr, cave_cursor = write_payload(
                candidate,
                pointer,
                new_payload,
                len(old_payload),
                allowed,
                cave_cursor,
                require_nul=False,
            )
            if written_addr != pointer:
                struct.pack_into("<I", candidate, owner, written_addr)
                allowed.update(range(owner, owner + 4))
            new_addr = written_addr
        scenario_changed += 1
        evidence.append(
            {
                "record_id": row["record_id"],
                "source_scope": row["source_scope"],
                "source_text": row.get("source_text"),
                "before": before,
                "after": after,
                "old_active_addresses": [f"0x{addr:08X}" for addr in old_addresses],
                "new_address": f"0x{new_addr:08X}",
                "encoded_size": len(new_payload),
            }
        )

    leftover = [row["record_id"] for row in merged["records"] if "자네" in str(row.get("translation_ko") or "") and row["record_id"] not in HAGE_KEEP]
    gate(not leftover, f"non-하게 자네 leftover: {leftover[:8]}")
    kept_now = [row["record_id"] for row in merged["records"] if "자네" in str(row.get("translation_ko") or "")]
    gate(set(kept_now) == HAGE_KEEP, f"keep set drift: {sorted(set(kept_now) ^ HAGE_KEEP)}")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, "candidate changed outside target payloads/lookups")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")

    parent = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent,
            "batch_id": BATCH_ID,
            "records": [
                {"record_id": row["record_id"], "payload": by_id[row["record_id"]]["translation_payload_sha256"]}
                for row in change_rows
            ],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent
    merged["identity"]["kimi_jane_to_neo_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity

    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(candidate)
    shutil.copyfile(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_kimi_jane_to_neo_candidate_20260904",
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
            "translation_source": advance_relative(TRANSLATION_MERGED_JSON),
        },
        "policy": {
            "keep_hageche_jane": True,
            "non_hageche_kimi_kun_to_neo": True,
            "keep_count": len(keep_rows),
            "changed_count": len(change_rows),
        },
        "keep_record_ids": sorted(HAGE_KEEP),
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes()},
        "verification": {
            "result": "PASS",
            "live_map_encode_matched_before_rewrite": True,
            "dialogue_width_limit": MAX_DIALOGUE_CELLS,
            "hageche_jane_preserved": 23,
            "rewritten_records": len(change_rows),
            "map_script_records": map_changed,
            "scenario_records": scenario_changed,
            "changed_bytes": len(changed),
            "original_map_script_bank_preserved": True,
            "main_tip_not_modified": sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current),
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "candidate": advance_relative(OUTPUT),
                "sha256": sha256(candidate),
                "changed_bytes": len(changed),
                "keep": len(keep_rows),
                "changed": len(change_rows),
                "map_script": map_changed,
                "scenario": scenario_changed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
