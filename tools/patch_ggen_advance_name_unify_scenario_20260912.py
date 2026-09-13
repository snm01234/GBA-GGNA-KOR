"""Unify leftover followup4 proper nouns still live in scenario lines.

Unit/profile names were already 라이조 캇슈 / 넬 아가마 / 릴리 마를렌 /
스트라이크 루즈 / ∀건담. Map-script consumers still showed 루주·말레렌·턴에이.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_advance_apsaras_zentetsu_20260908 as aps  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, slot_raw  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
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
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars, visible_segments  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import MAX_DIALOGUE_CELLS, load_identified_12x12  # noqa: E402
from patch_ggen_advance_name_unify_20260909 import patch_map_row_live  # noqa: E402

BATCH_ID = "name-unify-scenario-followup4-leftover-20260912"
IDENTITY_KEY = "name_unify_scenario_20260912_sha256"
BATCH_KEY = "name_unify_scenario_20260912"
OUT = ROOT / "outputs" / "20260912_name_unify_scenario"
WORK = OUT / "ggen_name_unify_scenario_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_name_unify_scenario.json"
BARKS = ROOT / "integrated" / "translation" / "ggen_advance_id_command_battle_barks.json"
CAVE_START = 0x011352FC
CAVE_END = 0x01230000
TURN_A_SLOT_12 = 0x071B
NOTES = "시나리오 잔재 통일: 루주→루즈, 말레렌→마를렌, 턴에이→∀건담"
MAP_JOBS: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F8ACB6": ["내 스트라이크 루즈가", "센스 없는 색이라고!?"],
    "GGA-MAPSCRIPT-00F9D461": ["리, 릴리 마를렌", "후퇴다!!"],
    "GGA-MAPSCRIPT-00FB201D": ["릴리 마를렌이……", "우리들의 섬이……"],
    "GGA-MAPSCRIPT-00F910F8": ["그것은 ∀건담"],
    "GGA-MAPSCRIPT-00F91189": ["그것은 ∀건담"],
}
SHEET_ONLY: dict[str, str] = {
    "GGA-UI-00189926": "시마의 심복의 부하。모함 릴리",
}
OLD_TOKENS = (
    "라이조 캐시",
    "말레렌",
    "스트라이크 루주",
    "스트라이크루주",
    "네일 아가마",
    "하이곡",
    "턴에이 건담",
)


def apply_visible(old_segments: list[str], new_visible: list[str], record_id: str) -> list[str]:
    old_visible = visible_segments(old_segments)
    gate(len(old_visible) == len(new_visible), f"visible count {record_id}")
    if not old_segments:
        return list(new_visible)
    out: list[str] = []
    index = 0
    for item in old_segments:
        if item:
            out.append(new_visible[index])
            index += 1
        else:
            out.append(item)
    gate(index == len(new_visible), f"visible framing {record_id}")
    return out


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


def leftover_hits(text: str) -> list[str]:
    hits = [token for token in OLD_TOKENS if token in text]
    if "유 카지마" in text and "유우 카지마" in text:
        if "유 카지마" not in text.replace("유우 카지마", ""):
            hits = [token for token in hits if token != "유 카지마"]
    return hits


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "name-unify scenario cave is not empty")
    for record_id, segs in MAP_JOBS.items():
        for line in segs:
            gate("\n" not in line and len(line) <= MAX_DIALOGUE_CELLS, f"map width {record_id} {line!r} {len(line)}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    for record_id in list(MAP_JOBS) + list(SHEET_ONLY):
        gate(record_id in by_id, f"missing {record_id}")
    gate("루주" in str(by_id["GGA-MAPSCRIPT-00F8ACB6"].get("translation_ko") or ""), "rouge drift")
    gate("말레렌" in str(by_id["GGA-MAPSCRIPT-00F9D461"].get("translation_ko") or ""), "marlene drift")
    gate("라이조 캇슈" in str(by_id["GGA-MAPSCRIPT-00F91BBB"].get("translation_ko") or ""), "raizo already drifted")

    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    identified = load_identified_12x12()
    jp_forall = slot_raw(japan, fontops.FONT_12X12_BASE, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE)

    hangul12: set[str] = set()
    for segs in MAP_JOBS.values():
        hangul12.update(char for line in segs for char in hangul_chars(line))
    for record_id in MAP_JOBS:
        hangul12.update(
            char for line in (by_id[record_id].get("translation_segments") or []) for char in hangul_chars(str(line))
        )

    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied12: set[int] = set()
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    recovered12["∀"] = TURN_A_SLOT_12
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []

    for record_id, new_visible in MAP_JOBS.items():
        row = by_id[record_id]
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        new_segments = apply_visible(old_segments, new_visible, record_id)
        cave_cursor, written = patch_map_row_live(
            row,
            old_segments,
            new_segments,
            parent,
            candidate,
            recovered12,
            identified,
            verified12,
            allowed,
            cave_cursor,
        )
        evidence.append({"record_id": record_id, "path": "map_script", "segments": written})

    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    map12[TURN_A_SLOT_12] = "∀"
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)

    def dec_owner_text(row: dict[str, Any]) -> list[str]:
        from patch_ggen_advance_apsaras_zentetsu_20260908 import find_lookups
        from patch_ggen_advance_map_script_inline_poc import raw_hex_bytes

        lives: list[str] = []
        cursor = int(str(row["target_file_offset"]), 16)
        for segment in row.get("segments") or []:
            original_bytes = raw_hex_bytes(str(segment.get("raw_hex") or ""))
            orig_addr = ROM_BASE + cursor
            lookups = find_lookups(bytes(candidate), orig_addr, orig_addr + len(original_bytes) - 1)
            lives.append(f2.decode_text(candidate, lookups[0][1], dict12, map12))
            cursor += len(original_bytes)
        return lives

    proofs = {
        "rouge": dec_owner_text(by_id["GGA-MAPSCRIPT-00F8ACB6"]),
        "marlene_retreat": dec_owner_text(by_id["GGA-MAPSCRIPT-00F9D461"]),
        "marlene_island": dec_owner_text(by_id["GGA-MAPSCRIPT-00FB201D"]),
        "turn_a_a": dec_owner_text(by_id["GGA-MAPSCRIPT-00F910F8"]),
        "turn_a_b": dec_owner_text(by_id["GGA-MAPSCRIPT-00F91189"]),
        "raizo": dec_owner_text(by_id["GGA-MAPSCRIPT-00F91BBB"]),
    }
    gate("루즈가" in proofs["rouge"][0] and "루주" not in proofs["rouge"][0], proofs["rouge"])
    gate("마를렌" in proofs["marlene_retreat"][0] and "말레렌" not in proofs["marlene_retreat"][0], proofs["marlene_retreat"])
    gate("마를렌" in proofs["marlene_island"][0] and "말레렌" not in proofs["marlene_island"][0], proofs["marlene_island"])
    gate(proofs["turn_a_a"][0] == "그것은 ∀건담", proofs["turn_a_a"])
    gate(proofs["turn_a_b"][0] == "그것은 ∀건담", proofs["turn_a_b"])
    gate("라이조 캇슈" in proofs["raizo"][0] and "캐시" not in proofs["raizo"][0], proofs["raizo"])
    for record_id in ("GGA-MAPSCRIPT-00F910F8", "GGA-MAPSCRIPT-00F91189"):
        row = by_id[record_id]
        from patch_ggen_advance_apsaras_zentetsu_20260908 import find_lookups
        from patch_ggen_advance_map_script_inline_poc import raw_hex_bytes

        raw = raw_hex_bytes(str(row["segments"][0]["raw_hex"]))
        orig = ROM_BASE + int(str(row["target_file_offset"]), 16)
        neu = find_lookups(bytes(candidate), orig, orig + len(raw) - 1)[0][1]
        slots = expand_to_slots(read_tokens(bytes(candidate), neu - ROM_BASE)[0], dict12)
        gate(TURN_A_SLOT_12 in slots, f"{record_id} missing ∀ slot {slots}")
        gate(0x07DC not in slots, f"{record_id} used 0x07DC {slots}")
    gate(
        slot_raw(candidate, FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE) == jp_forall,
        "∀ glyph drifted",
    )

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")

    changed_ids: list[str] = []
    for record_id, new_visible in MAP_JOBS.items():
        row = by_id[record_id]
        new_segments = apply_visible([str(item) for item in (row.get("translation_segments") or [])], new_visible, record_id)
        patch_merged_row(row, "\n".join(new_visible), new_segments)
        changed_ids.append(record_id)
    for record_id, ko_text in SHEET_ONLY.items():
        patch_merged_row(by_id[record_id], ko_text)
        changed_ids.append(record_id)

    leftover = [
        str(row["record_id"])
        for row in merged["records"]
        if leftover_hits(str(row.get("translation_ko") or ""))
        or any(leftover_hits(str(item)) for item in (row.get("translation_segments") or []))
    ]
    gate(not leftover, f"name leftover {leftover}")

    barks = json.loads(BARKS.read_text(encoding="utf-8"))
    bark_hits = 0
    for row in barks.get("records", []):
        if row.get("character_name_ko") == "라이조 캐시":
            row["character_name_ko"] = "라이조 캇슈"
            bark_hits += 1
    gate(bark_hits == 3, f"barks raizo count {bark_hits}")
    BARKS.write_text(json.dumps(barks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": changed_ids})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": changed_ids, "evidence": evidence}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_name_unify_scenario_20260912",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "changed_records": changed_ids,
        "barks_raizo_relabeled": bark_hits,
        "proofs": proofs,
        "verification": {
            "result": "PASS",
            "unrelated_bytes_preserved": True,
            "forall_071b_preserved": True,
            "scenario_old_names_clean": True,
            "raizo_live_already_katsushu": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "painted", "cave", "proofs", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
