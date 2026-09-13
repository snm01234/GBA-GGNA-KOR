"""Restore 12x12 Turn A ∀. Slot 0x071B was overwritten by Hangul 곡.

ss8: 진정한 힘을 발동시킨 ∀건담 used the 8x16 ∀ token (slot 0x07DC)
in the 12x12 profile renderer, and the real 12x12 ∀ slot 0x071B now
holds 곡. Restore the Japan ∀ glyph at 0x071B, move 곡 to a free slot,
and retarget the Turn A lines.
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
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
import patch_ggen_profile_followup3_20260912 as f3  # noqa: E402
import patch_ggen_profile_followup4_20260912 as f4  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, load_galmuri12, packed_12x12, slot_raw  # noqa: E402
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
from patch_ggen_advance_apsaras_zentetsu_20260908 import (  # noqa: E402
    choose_free_12x12,
    hangul_chars,
    paint_12x12,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)

BATCH_ID = "profile-followup5-forall-20260912"
IDENTITY_KEY = "profile_followup5_forall_20260912_sha256"
BATCH_KEY = "profile_followup5_forall_20260912"
OUT = ROOT / "outputs" / "20260912_allclear_profile_followup5"
WORK = OUT / "ggen_profile_followup5_forall_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_profile_followup5.json"
CAVE_START = 0x01134FD0
CAVE_END = 0x01230000
TURN_A_SLOT_12 = 0x071B
WIDTH = 18

GOK_JOBS = [
    {"owner": 0x001AD900, "ko": "분쟁 종결 후에는 우여곡절을 거쳐"},
    {"owner": 0x001AF704, "ko": "있었다。그후 여러 우여곡절을"},
    {"owner": 0x001B1BA0, "ko": "베이스기가 된 곡에 비해"},
    {"owner": 0x001B1BB4, "ko": "그래도 본가 곡이 첫 등장 때 보"},
]
FORALL_JOBS = [
    {"owner": 0x001AF994, "ko": "「∀건담」의 주인공 로랑이"},
    {"owner": 0x001B3720, "ko": "∀건담과 같은 IFBD시스템으로"},
    {"owner": 0x001B433C, "ko": "진정한 힘을 발동시킨 ∀건담。"},
    {"owner": 0x001B4340, "ko": "강대한 에너지파동「월광접」을 전개"},
    {"owner": 0x001B4628, "ko": "또한 2천 년의 시간을 넘어、「∀"},
]


def patch_merged_row(row: dict[str, Any], ko: str) -> None:
    row["translation_ko"] = ko
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = "profile followup5: restore 12x12 ∀, keep 곡 off slot 0x071B"
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "followup5 cave is not empty")

    jp_forall = slot_raw(japan, fontops.FONT_12X12_BASE, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE)
    now_071b = slot_raw(parent, FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE)
    gate(now_071b == packed_12x12("곡", load_galmuri12()), "0x071B is no longer Galmuri 곡")
    gate(jp_forall != now_071b, "Japan ∀ already matches live 0x071B")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    live12.add(TURN_A_SLOT_12)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied: set[int] = {TURN_A_SLOT_12}

    start = FONT12_RELOCATED + TURN_A_SLOT_12 * fontops.FONT_12X12_STRIDE
    candidate[start : start + fontops.FONT_12X12_STRIDE] = jp_forall
    allowed.update(range(start, start + fontops.FONT_12X12_STRIDE))
    painted.append({"font": "12x12-restore", "char": "∀", "slot": hex(TURN_A_SLOT_12)})
    gate(
        slot_raw(candidate, FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE) == jp_forall,
        "failed to restore 12x12 ∀",
    )

    gok_slot = choose_free_12x12(candidate, japan, live12, occupied)
    paint_12x12(candidate, gok_slot, "곡", load_galmuri12())
    gok_start = FONT12_RELOCATED + gok_slot * fontops.FONT_12X12_STRIDE
    allowed.update(range(gok_start, gok_start + fontops.FONT_12X12_STRIDE))
    occupied.add(gok_slot)
    live12.add(gok_slot)
    painted.append({"font": "12x12", "char": "곡", "slot": hex(gok_slot)})

    hangul = {char for job in GOK_JOBS + FORALL_JOBS for char in hangul_chars(job["ko"])} - {"곡"}
    recovered = f2.recover_hangul(
        candidate, japan, hangul, mode=12, live=live12, occupied=occupied, allowed=allowed, painted=painted
    )
    recovered["곡"] = gok_slot
    recovered["∀"] = TURN_A_SLOT_12
    specials = {"∀": TURN_A_SLOT_12}
    cursor = CAVE_START
    applied = []
    for job in GOK_JOBS + FORALL_JOBS:
        gate(f4.cell_count(job["ko"]) <= WIDTH, f"width {job}")
        encoded = f4.encode_mixed(job["ko"], recovered, verified12, specials)
        slots = expand_to_slots(read_tokens(encoded, 0)[0], load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END))
        gate(1 <= len(slots) <= WIDTH, f"encoded width {len(slots)} {job['ko']}")
        new_ptr, cursor = f3.cave_payload(candidate, job["owner"], encoded, allowed, cursor)
        applied.append({"owner": hex(job["owner"]), "ko": job["ko"], "new_ptr": hex(new_ptr)})

    hangul_live = f2.hangul_slot_map(candidate, mode=12)
    map12 = f2.slot_to_char_map(verified12, recovered, hangul_live)
    map12[TURN_A_SLOT_12] = "∀"
    map12[gok_slot] = "곡"
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)

    def dec12(owner: int) -> str:
        return f2.decode_text(candidate, f2.u32(candidate, owner), dict12, map12)

    def slots12(owner: int) -> list[int]:
        return expand_to_slots(read_tokens(bytes(candidate), f2.u32(candidate, owner) - ROM_BASE)[0], dict12)

    ss8 = dec12(0x001B433C)
    gate(ss8 == "진정한 힘을 발동시킨 ∀건담。", f"ss8 line {ss8}")
    gate(TURN_A_SLOT_12 in slots12(0x001B433C), "ss8 missing 0x071B")
    gate(0x07DC not in slots12(0x001B433C), "ss8 still uses 0x07DC")
    gate("강대" not in ss8, "ss8 still glued 강대")
    sel1 = dec12(0x001B4340)
    gate(sel1.startswith("강대한"), f"sel1 {sel1}")
    gok = dec12(0x001AD900)
    gate("우여곡절" in gok and "∀절" not in gok, f"gok collision {gok}")
    gate(gok_slot in slots12(0x001AD900), "우여곡절 not on new 곡 slot")
    gate(TURN_A_SLOT_12 not in slots12(0x001AD900), "우여곡절 still on 0x071B")
    loran = dec12(0x001AF8C0)
    gate("∀건담" in loran, f"loran {loran}")
    hygog = dec12(0x001B1BA0)
    gate("곡에 비해" in hygog and "∀에" not in hygog, f"hygog {hygog}")
    gate(
        slot_raw(candidate, FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE) == jp_forall,
        "∀ glyph drifted after writes",
    )

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")

    by_owner: dict[int, list[str]] = {}
    for row in merged["records"]:
        for owner in owner_offsets(row):
            by_owner.setdefault(owner, []).append(str(row["record_id"]))
    changed_ids: list[str] = []
    for job in GOK_JOBS + FORALL_JOBS:
        for record_id in by_owner.get(job["owner"], []):
            patch_merged_row(next(r for r in merged["records"] if r["record_id"] == record_id), job["ko"])
            changed_ids.append(record_id)

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
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "gok_slot": hex(gok_slot), "changed_records": sorted(set(changed_ids))}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_profile_followup5_forall",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "gok_slot": hex(gok_slot),
        "proofs": {
            "ss8": ss8,
            "sel1": sel1,
            "gok": gok,
            "loran": loran,
            "hygog": hygog,
        },
        "verification": {
            "result": "PASS",
            "unrelated_bytes_preserved": True,
            "forall_restored_071b": True,
            "gok_moved_off_071b": True,
            "ss8_no_07dc": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "painted", "cave", "gok_slot", "proofs", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
