"""Fix NT試験用ジム ジャグラー spelling and ボール射出 misread as 페일.

ジャグラー is Juggler → 저글러 (not 재글러).
Production weapon raw 83 DD 91 E2 44 B2 is 8x16 ボ+ー+ル+射+出.
A12 had mapped slot 0x0083 via 12x12 ペ, yielding ペール射出 / 페일 사출.
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
import patch_ggen_advance_apsaras_zentetsu_20260908 as aps  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import (  # noqa: E402
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    ROM_BASE,
    expand_to_slots,
    load_dictionary,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars, patch_owned_payload  # noqa: E402
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import live_char_tokens  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, payload_at, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_name_unify_20260909 import encode_overlay  # noqa: E402

BATCH_ID = "juggler-ball-eject-20260913"
IDENTITY_KEY = "juggler_ball_20260913_sha256"
BATCH_KEY = "juggler_ball_20260913"
OUT = ROOT / "outputs" / "20260913_juggler_ball"
WORK = OUT / "ggen_juggler_ball_20260913.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260913_juggler_ball.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
CAVE_START = 0x0113553D
CAVE_END = 0x01230000
MAP_BANK = (0x00F00000, 0x00FC0000)
NAME_BOX_CELLS = 14
UNIT_CATS = {"unit_name", "unit_name_alternate"}
OLD_NAME = "NT 시험용 짐 재글러"
NEW_NAME = "NT 시험용 짐 저글러"
OLD_WEAPON = "페일 사출"
NEW_WEAPON = "볼 사출"
WEAPON_JP = "ボール射出"
WEAPON_8_ID = "GGA-TEXT-00179FC4"
WEAPON_12_ID = "GGA-DYNAMIC-001F1AAB"
WEAPON_8_RAW = bytes.fromhex("83DD91E244B200")
NOTES = (
    "ジャグラー=Juggler → 저글러. 무기 8x16 0x0083=ボ 이므로 ボール射出. "
    "A12가 ペ로 읽어 페일 사출이 됨 → 볼 사출"
)


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def slot_count(blob: bytes, dictionary) -> int:
    return len(expand_to_slots(unified.tokens_from_bytes(blob), dictionary))


def patch_merged_row(row: dict[str, Any], ko: str, *, source_text: str | None = None) -> None:
    row["translation_ko"] = ko
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-13"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    if source_text is not None:
        row["source_text"] = source_text
        row["source_decode_status"] = "complete"
        row["source_unresolved_slots"] = []
    update_payload_hash(row)


def encode_body(
    before: str,
    after: str,
    body: bytes,
    recovered: dict[str, int],
    verified: dict[str, int],
) -> bytes:
    live_tokens = live_char_tokens(before, body)
    try:
        old_body = encode_overlay(before, recovered, verified, live_tokens)
        if old_body == body:
            return encode_overlay(after, recovered, verified, live_tokens)
    except SystemExit:
        pass
    encoded, missing = unified.encode_korean_text(
        after, recovered, verified_charmap=verified, strict_punctuation=True
    )
    gate(encoded is not None and not missing, f"encode failed {after!r} {missing}")
    return encoded


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "juggler-ball cave is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(japan[0x00179FC4 : 0x00179FC4 + len(WEAPON_8_RAW)] == WEAPON_8_RAW, "JP ボール射出 raw drift")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    name_rows = [
        row
        for row in merged["records"]
        if str(row.get("semantic_category") or "") in UNIT_CATS
        and OLD_NAME in str(row.get("translation_ko") or "")
    ]
    gate(len(name_rows) == 5, f"juggler name count { [r['record_id'] for r in name_rows] }")
    weapon8 = by_id[WEAPON_8_ID]
    weapon12 = by_id[WEAPON_12_ID]
    gate(str(weapon8.get("translation_ko") or "") == OLD_WEAPON, "weapon 8x16 ko drift")
    gate(str(weapon12.get("translation_ko") or "") == OLD_WEAPON, "weapon 12x12 ko drift")
    gate(str(weapon12.get("source_text") or "") == WEAPON_JP, "weapon 12x12 source drift")
    gate(bytes.fromhex(str(weapon8.get("raw_hex") or "").replace(" ", "")) == WEAPON_8_RAW, "weapon 8 raw drift")
    pale_rows = [
        str(row["record_id"])
        for row in merged["records"]
        if OLD_WEAPON in str(row.get("translation_ko") or "")
    ]
    gate(pale_rows == [WEAPON_8_ID, WEAPON_12_ID], f"unexpected 페일 사출 {pale_rows}")

    hangul8 = hangul_chars(OLD_NAME + NEW_NAME + OLD_WEAPON + NEW_WEAPON)
    hangul12 = hangul_chars(OLD_WEAPON + NEW_WEAPON)
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    charmap8 = json.loads(unified.CHARMAP_8X16_PATH.read_text(encoding="utf-8"))["verified_charmap"]
    gate(charmap8.get("0x0083") == "ボ", f"charmap 0x0083 is {charmap8.get('0x0083')!r} not ボ")
    gate(verified8.get("ボ") == 0x0083, f"8x16 ボ slot {verified8.get('ボ')}")
    gate(verified8.get("ペ") != 0x0083, "verified 8x16 maps ペ onto 0x0083")

    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied8: set[int] = set()
    occupied12: set[int] = set()
    recovered8 = f2.recover_hangul(
        candidate, japan, hangul8, mode=8, live=live8, occupied=occupied8, allowed=allowed, painted=painted
    )
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    for char in hangul_chars("저글러볼"):
        gate(char in recovered8, f"missing 8x16 {ascii(char)}")
    for char in hangul_chars("볼사출"):
        gate(char in recovered12, f"missing 12x12 {ascii(char)}")

    dict8 = load_dictionary(parent, DICT_8X16_BASE, DICT_8X16_END)
    cave_cursor = CAVE_START
    jobs: list[dict[str, Any]] = []
    proofs: dict[str, str] = {}

    for row in name_rows:
        before = str(row.get("translation_ko") or "")
        after = before.replace(OLD_NAME, NEW_NAME)
        gate(after != before and NEW_NAME in after, f"name rewrite missed {row['record_id']}")
        owners = owner_offsets(row)
        gate(owners, f"no owners {row['record_id']}")
        live = payload_at(parent, u32(parent, owners[0]))
        prefix = unified.leading_reserved_prefix(live)
        body = live[len(prefix) :]
        new_payload = prefix + encode_body(before, after, body, recovered8, verified8)
        cells = slot_count(new_payload, dict8)
        gate(cells <= NAME_BOX_CELLS, f"{row['record_id']} width {cells}>{NAME_BOX_CELLS}: {after!r}")
        cave_cursor, old_addresses, new_addr = patch_owned_payload(
            row, live, new_payload, parent, candidate, allowed, cave_cursor, require_nul=True
        )
        patch_merged_row(row, after)
        jobs.append(
            {
                "record_id": row["record_id"],
                "path": "u32_8x16_name",
                "before": before,
                "after": after,
                "cells": cells,
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
            }
        )

    live8_weapon = payload_at(parent, u32(parent, owner_offsets(weapon8)[0]))
    new8 = encode_body(OLD_WEAPON, NEW_WEAPON, live8_weapon, recovered8, verified8)
    cave_cursor, old8_addr, new8_addr = patch_owned_payload(
        weapon8, live8_weapon, new8, parent, candidate, allowed, cave_cursor, require_nul=True
    )
    patch_merged_row(weapon8, NEW_WEAPON, source_text=WEAPON_JP)
    jobs.append(
        {
            "record_id": WEAPON_8_ID,
            "path": "u32_8x16_weapon",
            "before": OLD_WEAPON,
            "after": NEW_WEAPON,
            "jp": WEAPON_JP,
            "old_active_addresses": old8_addr,
            "new_address": new8_addr,
        }
    )

    live12_weapon = payload_at(parent, u32(parent, owner_offsets(weapon12)[0]))
    new12 = encode_body(OLD_WEAPON, NEW_WEAPON, live12_weapon, recovered12, verified12)
    cave_cursor, old12_addr, new12_addr = patch_owned_payload(
        weapon12, live12_weapon, new12, parent, candidate, allowed, cave_cursor, require_nul=True
    )
    patch_merged_row(weapon12, NEW_WEAPON)
    jobs.append(
        {
            "record_id": WEAPON_12_ID,
            "path": "u32_12x12_weapon",
            "before": OLD_WEAPON,
            "after": NEW_WEAPON,
            "jp": WEAPON_JP,
            "old_active_addresses": old12_addr,
            "new_address": new12_addr,
        }
    )

    hangul_live8 = f2.hangul_slot_map(candidate, mode=8)
    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map8 = f2.slot_to_char_map(verified8, recovered8, hangul_live8)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    dict8_live = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)
    dict12_live = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    for row in name_rows:
        live = f2.decode_text(candidate, u32(candidate, owner_offsets(row)[0]), dict8_live, map8)
        if live.startswith("\uE000") or (live and ord(live[0]) > 0xFFFF):
            pass
        # Drop reserved-prefix glyph if decoder emitted a leading unknown.
        body = live[1:] if live and NEW_NAME in live[1:] else live
        gate(NEW_NAME in body and OLD_NAME not in body, f"name live {row['record_id']} {live!r}")
        proofs[str(row["record_id"])] = live
    w8_live = f2.decode_text(candidate, u32(candidate, owner_offsets(weapon8)[0]), dict8_live, map8)
    w12_live = f2.decode_text(candidate, u32(candidate, owner_offsets(weapon12)[0]), dict12_live, map12)
    gate(w8_live == NEW_WEAPON, f"weapon 8 live {w8_live!r}")
    gate(w12_live == NEW_WEAPON, f"weapon 12 live {w12_live!r}")
    proofs[WEAPON_8_ID] = w8_live
    proofs[WEAPON_12_ID] = w12_live

    leftover_names = [
        str(row["record_id"])
        for row in merged["records"]
        if str(row.get("semantic_category") or "") in UNIT_CATS
        and OLD_NAME in str(row.get("translation_ko") or "")
    ]
    leftover_pale = [
        str(row["record_id"])
        for row in merged["records"]
        if OLD_WEAPON in str(row.get("translation_ko") or "")
    ]
    gate(not leftover_names, f"재글러 leftover {leftover_names}")
    gate(not leftover_pale, f"페일 leftover {leftover_pale}")
    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes x{len(changed - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == parent[MAP_BANK[0] : MAP_BANK[1]], "map bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "juggler-ball cave overflow")

    changed_ids = [str(row["record_id"]) for row in name_rows] + [WEAPON_8_ID, WEAPON_12_ID]
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": changed_ids})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(item.get("translation_status") or "") for item in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": changed_ids, "notes": NOTES}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    WORK.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT / "ggen_juggler_ball_20260913.sav")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_juggler_ball_20260913",
        "result": "PASS",
        "batch_id": BATCH_ID,
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "jobs": jobs,
        "proofs": proofs,
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {"path": advance_relative(WORK), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {
            "path": advance_relative(TRANSLATION_MERGED_JSON),
            "sha256": sha256(payload_json.encode("utf-8")),
        },
        "verification": {
            "result": "PASS",
            "juggler_not_jaegler": True,
            "ball_eject_not_pale": True,
            "jp_ball_eject": WEAPON_JP,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "analysis" / "ggen_advance_juggler_ball_candidate_20260913.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": "PASS",
                "painted_glyphs": painted,
                "cave": report["cave"],
                "output": report["output"],
                "proofs": {k: proofs[k] for k in (WEAPON_8_ID, WEAPON_12_ID)},
                "name_count": len(name_rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
