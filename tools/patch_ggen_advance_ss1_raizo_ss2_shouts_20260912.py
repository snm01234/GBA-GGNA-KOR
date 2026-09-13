"""Fix ss1 라이조 캐시 nameplate and omitted short map-script shouts.

ss1: production character_name OWNER-U32-001A9E28 still pointed at
     라이조 캐시 while the unit-DB copy was already 라이조 캇슈.
ss2: setup 0x11 / 0xDD prints (17 11 18 / 17 DD 18) were outside
     PRINT_SETUP, so complete-box shorts like ……ぐわっ！？ never entered
     the sheet or lookup table and drew inline JP.
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
import extract_ggen_advance_map_script_dialogue as extract_mod  # noqa: E402
import patch_ggen_advance_apsaras_zentetsu_20260908 as aps  # noqa: E402
import patch_ggen_advance_ashi_kagari_idcmd_20260910 as ashi_mod  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map  # noqa: E402
from build_ggen_advance_map_script_sheet import build_record, recount  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, slot_raw  # noqa: E402
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
    load_dictionary,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars  # noqa: E402
from patch_ggen_advance_ashi_kagari_idcmd_20260910 import lookup_hits, patch_map_row_fresh  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import MAX_DIALOGUE_CELLS, load_identified_12x12  # noqa: E402
from patch_ggen_advance_nimbus_exss4_20260910 import plan_visible  # noqa: E402

BATCH_ID = "ss1-raizo-ss2-shouts-20260912"
IDENTITY_KEY = "ss1_raizo_ss2_shouts_20260912_sha256"
BATCH_KEY = "ss1_raizo_ss2_shouts_20260912"
OUT = ROOT / "outputs" / "20260912_ss1_raizo_ss2_shouts"
WORK = OUT / "ggen_ss1_raizo_ss2_shouts_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_ss1_raizo_ss2_shouts.json"
CAVE_START = 0x011352FC
CAVE_END = 0x01230000
MAP_BANK = (0x00F00000, 0x00FC0000)
EXTRA_BANK = (0x00FC0000, 0x00FD0000)
LIVE_LOOKUP_PTR_OFF = 0x01112588
LIVE_LOOKUP_COUNT_OFF = 0x0111258C
LIVE_LOOKUP_PTR = 0x09360000
LIVE_LOOKUP_TABLE = 0x01360000
TURN_A_SLOT_12 = 0x071B
RAIZO_OWNER = 0x001A9E28
RAIZO_RECORD = "GGA-TEXT-0017CBEA"
RAIZO_KEEP_PTR = 0x09134754
NOTES = (
    "대화 이름표 라이조 캐시→캇슈. setup 0x11/0xDD 짧은 비명 박스 "
    "……ぐわっ！？ / これは……！ / ……ララァ！！ 를 한글 lookup으로 추가."
)
FRESH_JOBS: dict[str, dict[str, Any]] = {
    "GGA-MAPSCRIPT-00F90DF4": {
        "opcode": 0x00F90DF3,
        "setup": 0x11,
        "ko": ["……으악！？"],
        "source": "……ぐわっ！？",
    },
    "GGA-MAPSCRIPT-00FACDC1": {
        "opcode": 0x00FACDC0,
        "setup": 0x11,
        "ko": ["이건……！"],
        "source": "これは……！",
    },
    "GGA-MAPSCRIPT-00FA824C": {
        "opcode": 0x00FA824B,
        "setup": 0xDD,
        "ko": ["……라라아！！"],
        "source": "……ララァ！！",
    },
}


def patch_merged_row(row: dict[str, Any], ko: str, segments: list[str] | None = None) -> None:
    row["translation_ko"] = ko
    if segments is not None:
        row["translation_segments"] = segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def extract_fresh_row(
    japan: bytes,
    opcode_18: int,
    setup: int,
    mapping: dict[int, str],
    dictionary: list[list[int]],
) -> dict[str, Any]:
    parsed, _cursor = extract_mod.parse_print(japan, opcode_18, dictionary, mapping)
    speaker = extract_mod.recent_speaker(japan, opcode_18)
    parsed["record_id"] = f"GGA-MAPSCRIPT-{opcode_18 + 1:08X}"
    parsed["print_setup"] = f"0x{setup:04X}"
    parsed["chained_box"] = False
    parsed["speaker_id"] = f"0x{speaker:04X}" if speaker is not None else ""
    return parsed


def unhooked_missed_prints(rom: bytes, japan: bytes, dictionary: list[list[int]], mapping: dict[int, str]) -> list[str]:
    leftover: list[str] = []
    for setup in (0x11, 0xDD):
        needle = bytes((0x17, setup, 0x18))
        cursor = MAP_BANK[0]
        while True:
            pos = rom.find(needle, cursor, EXTRA_BANK[1])
            if pos < 0:
                break
            opcode = pos + 2
            cursor = pos + 1
            try:
                parsed, _ = extract_mod.parse_print(japan, opcode, dictionary, mapping)
            except (ValueError, SystemExit):
                continue
            segs = parsed.get("segments") or []
            if not segs:
                continue
            raw = bytes.fromhex(str(segs[0].get("raw_hex") or "").replace(" ", ""))
            if not raw.endswith(b"\x00"):
                continue
            orig = ROM_BASE + opcode + 1
            orig_end = orig + len(raw) - 1
            if lookup_hits(rom, orig, orig_end):
                continue
            leftover.append(f"0x{opcode:08X}:{parsed.get('source_text_seed')}")
    return leftover


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    ashi_mod.LIVE_LOOKUP_TABLE = LIVE_LOOKUP_TABLE
    ashi_mod.LIVE_LOOKUP_PTR = LIVE_LOOKUP_PTR
    extract_mod.BANK_END = EXTRA_BANK[1]
    OUT.mkdir(parents=True, exist_ok=True)

    for job in FRESH_JOBS.values():
        for line in job["ko"]:
            gate("\n" not in line, f"newline {line!r}")
            gate(len(line) <= MAX_DIALOGUE_CELLS, f"width {line!r} {len(line)}")

    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")
    gate(f2.u32(parent, LIVE_LOOKUP_PTR_OFF) == LIVE_LOOKUP_PTR, "live lookup pointer drift")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "ss2 shout cave is not empty")
    gate(0x11 in extract_mod.PRINT_SETUP and 0xDD in extract_mod.PRINT_SETUP, "extractor setups not extended")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    mapping = load_map(ROOT / "analysis/ggen_advance_12x12_identified_charmap_20260828.json")
    mapping.update(CORRECTED_LOW_KANA)
    dictionary = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    rom_sha = str(merged["source"]["sha256"]).lower()
    existing_ids = {str(row["record_id"]) for row in merged["records"]}
    existing_owners = {str(owner["owner_id"]) for owner in merged["owners"]}
    new_records: list[dict[str, Any]] = []
    new_owners: list[dict[str, Any]] = []
    for record_id, job in FRESH_JOBS.items():
        parsed = extract_fresh_row(japan, int(job["opcode"]), int(job["setup"]), mapping, dictionary)
        gate(parsed["record_id"] == record_id, f"fresh id drift {parsed['record_id']}")
        gate(parsed["source_text_seed"] == job["source"], f"source drift {record_id} {parsed['source_text_seed']!r}")
        gate(japan[int(job["opcode"]) - 1] == int(job["setup"]), f"setup byte {record_id}")
        gate(record_id not in existing_ids, f"duplicate {record_id}")
        record, owner = build_record(parsed, rom_sha)
        gate(owner["owner_id"] not in existing_owners, f"owner collision {owner['owner_id']}")
        existing_ids.add(record_id)
        existing_owners.add(owner["owner_id"])
        new_records.append(record)
        new_owners.append(owner)
    merged["records"].extend(new_records)
    merged["owners"].extend(new_owners)
    recount(merged)
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    gate(RAIZO_RECORD in by_id, "missing raizo production name")
    gate(str(by_id[RAIZO_RECORD].get("translation_ko") or "") == "라이조 캇슈", "sheet raizo drifted")
    gate(RAIZO_OWNER in owner_offsets(by_id[RAIZO_RECORD]), "raizo owner drift")

    d8 = load_dictionary(parent, DICT_8X16_BASE, DICT_8X16_END)
    m8 = f2.slot_to_char_map(unified.load_verified_charmap(unified.CHARMAP_8X16_PATH), {}, f2.hangul_slot_map(parent, mode=8))
    gate(f2.decode_text(parent, f2.u32(parent, RAIZO_OWNER), d8, m8) == "라이조 캐시", "live raizo already new")
    gate(f2.decode_text(parent, RAIZO_KEEP_PTR, d8, m8) == "라이조 캇슈", "keep raizo payload drifted")
    gate(f2.u32(parent, RAIZO_OWNER) == 0x0904F79D, "raizo cache pointer drift")

    planned: list[tuple[str, dict[str, Any], str, list[str], list[str]]] = []
    hangul12: set[str] = set()
    for record_id, job in FRESH_JOBS.items():
        row = by_id[record_id]
        before, old_segments, new_segments = plan_visible(row, list(job["ko"]))
        hangul12.update(hangul_chars("\n".join(job["ko"])))
        planned.append((record_id, row, before, old_segments, new_segments))

    identified = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    _live8, live12 = unified.collect_live_slots(japan, merged["records"])
    jp_forall = slot_raw(japan, fontops.FONT_12X12_BASE, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE)
    candidate = bytearray(parent)
    allowed: set[int] = set()
    occupied12: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    recovered12["∀"] = TURN_A_SLOT_12

    struct.pack_into("<I", candidate, RAIZO_OWNER, RAIZO_KEEP_PTR)
    allowed.update(range(RAIZO_OWNER, RAIZO_OWNER + 4))

    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    for record_id, row, before, old_segments, new_segments in planned:
        after = "\n".join(job for job in FRESH_JOBS[record_id]["ko"])
        patch_merged_row(row, after, new_segments)
        cave_cursor, written = patch_map_row_fresh(
            row,
            new_segments,
            parent,
            candidate,
            recovered12,
            identified,
            verified12,
            allowed,
            cave_cursor,
        )
        evidence.append(
            {
                "record_id": record_id,
                "kind": "fresh",
                "before": before,
                "after": after,
                "segments": written,
            }
        )
    patch_merged_row(by_id[RAIZO_RECORD], "라이조 캇슈")

    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    map12[TURN_A_SLOT_12] = "∀"
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    d8_new = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)
    m8_new = f2.slot_to_char_map(
        unified.load_verified_charmap(unified.CHARMAP_8X16_PATH), {}, f2.hangul_slot_map(candidate, mode=8)
    )
    raizo_live = f2.decode_text(candidate, f2.u32(candidate, RAIZO_OWNER), d8_new, m8_new)
    gate(raizo_live == "라이조 캇슈", f"raizo still {raizo_live!r}")
    gate(f2.u32(candidate, RAIZO_OWNER) == RAIZO_KEEP_PTR, "raizo pointer not shared")

    leftover_cache = []
    for row in merged["records"]:
        if row.get("semantic_category") not in {"character_name", "character_name_alternate"}:
            continue
        for owner in owner_offsets(row):
            live = f2.decode_text(candidate, f2.u32(candidate, owner), d8_new, m8_new)
            if "캐시" in live:
                leftover_cache.append((str(row["record_id"]), hex(owner), live))
    gate(not leftover_cache, f"cache leftover {leftover_cache}")

    proofs: dict[str, str] = {"raizo": raizo_live}
    for record_id, job in FRESH_JOBS.items():
        row = by_id[record_id]
        raw = bytes.fromhex(str(row["segments"][0]["raw_hex"]).replace(" ", ""))
        orig = ROM_BASE + int(str(row["target_file_offset"]), 16)
        hits = lookup_hits(bytes(candidate), orig, orig + len(raw) - 1)
        gate(hits, f"missing lookup {record_id}")
        live = f2.decode_text(candidate, hits[0][1], dict12, map12)
        proofs[record_id] = live
        gate(live == job["ko"][0], f"live {record_id} {live!r}")
    leftover_prints = unhooked_missed_prints(bytes(candidate), japan, dictionary, mapping)
    gate(not leftover_prints, f"unhooked setup 0x11/0xDD leftover {leftover_prints}")
    gate(
        slot_raw(candidate, FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE) == jp_forall,
        "∀ glyph drifted",
    )
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == parent[MAP_BANK[0] : MAP_BANK[1]], "map bank mutated")
    gate(bytes(candidate[EXTRA_BANK[0] : EXTRA_BANK[1]]) == parent[EXTRA_BANK[0] : EXTRA_BANK[1]], "extra bank mutated")

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")
    gate(cave_cursor <= CAVE_END, "cave overflow")

    recount(merged)
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": sorted(FRESH_JOBS) + [RAIZO_RECORD]})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": sorted(FRESH_JOBS) + [RAIZO_RECORD], "evidence": evidence}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_ss1_raizo_ss2_shouts_20260912",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "lookup_count": f2.u32(candidate, LIVE_LOOKUP_COUNT_OFF),
        "proofs": proofs,
        "verification": {
            "result": "PASS",
            "raizo_shared_katsushu": True,
            "setup11_dd_hooked": True,
            "map_bank_unmodified": True,
            "forall_071b_preserved": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: report[k] for k in ("output", "painted", "cave", "proofs", "lookup_count", "verification")},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
