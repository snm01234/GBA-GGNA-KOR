"""Fix FCE1A0 yellow-window locations misdecoded as 8x16 戦闘力増大.

The parallel stage-entry table at 0xFCE1A0 is 12x12.  Historical A12 8x16
decode mapped the same bytes to 戦闘力増大 / 戦力増大, so the live Korean
showed 전투력 증대 / 전력 증대 instead of 衛星軌道上 / 月軌道上.
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
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA  # noqa: E402
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
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars, patch_owned_payload  # noqa: E402
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import live_char_tokens  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, payload_at, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_name_unify_20260909 import encode_overlay  # noqa: E402

BATCH_ID = "stage-entry-orbit-misdecode-20260913"
IDENTITY_KEY = "stage_entry_orbit_20260913_sha256"
BATCH_KEY = "stage_entry_orbit_20260913"
OUT = ROOT / "outputs" / "20260913_stage_entry_orbit"
WORK = OUT / "ggen_stage_entry_orbit_20260913.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260913_stage_entry_orbit.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
CAVE_START = 0x011354F6
CAVE_END = 0x01230000
NOTES = (
    "스테이지 진입 FCE1A0 12x12 지명. "
    "衛星軌道上을 8x16 戦闘力増大로 오독한 전투력 증대, "
    "月軌道上을 戦力増大로 오독한 전력 증대를 궤도 지명으로 교정"
)
JOBS: dict[str, dict[str, str]] = {
    "GGA-TEXT-0018D4DF": {
        "jp12": "衛星軌道上",
        "old": "전투력 증대",
        "new": "위성 궤도 상",
        "owner": "00FCE1A4",
    },
    "GGA-TEXT-0018D59F": {
        "jp12": "衛星軌道上",
        "old": "전투력 증대",
        "new": "위성 궤도 상",
        "owner": "00FCE208",
    },
    "GGA-TEXT-0018D581": {
        "jp12": "月軌道上",
        "old": "전력 증대",
        "new": "달 궤도 상",
        "owner": "00FCE1E8",
    },
}


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def decode_jp12(raw: bytes, dictionary: list[bytes], cmap: dict[int, str]) -> str:
    tokens, _ = read_tokens(raw, 0)
    slots = expand_to_slots(tokens, dictionary)
    return "".join(cmap.get(slot, f"<{slot:04X}>") for slot in slots)


def patch_merged_row(row: dict[str, Any], job: dict[str, str]) -> None:
    row["source_text"] = job["jp12"]
    row["source_decode_status"] = "complete"
    row["source_unresolved_slots"] = []
    row["translation_ko"] = job["new"]
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-13"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "stage-entry-orbit cave is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    map12 = unified.load_identified_slot_to_char(unified.CHARMAP_12X12_PATH)
    map12.update(CORRECTED_LOW_KANA)

    hangul12: set[str] = set()
    for record_id, job in JOBS.items():
        row = by_id[record_id]
        gate(str(row.get("semantic_category")) == "stage_battle_condition_text", f"category {record_id}")
        raw = bytes.fromhex(str(row.get("raw_hex") or "").replace(" ", ""))
        gate(decode_jp12(raw, dict12, map12) == job["jp12"], f"jp12 drift {record_id}")
        gate(str(row.get("translation_ko") or "") == job["old"], f"old drift {record_id}")
        owners = owner_offsets(row)
        gate(owners == (int(job["owner"], 16),), f"owner drift {record_id}")
        hangul12.update(hangul_chars(job["old"]))
        hangul12.update(hangul_chars(job["new"]))

    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied12: set[int] = set()
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    for char in hangul_chars("위성궤도상달"):
        gate(char in recovered12, f"missing 12x12 {ascii(char)}")

    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    for record_id, job in JOBS.items():
        row = by_id[record_id]
        owners = owner_offsets(row)
        pointer = u32(parent, owners[0])
        old_payload = payload_at(parent, pointer)
        live_tokens = live_char_tokens(job["old"], old_payload)
        new_payload = encode_overlay(job["new"], recovered12, verified12, live_tokens)
        cave_cursor, old_addresses, new_addr = patch_owned_payload(
            row, old_payload, new_payload, parent, candidate, allowed, cave_cursor, require_nul=True
        )
        patch_merged_row(row, job)
        evidence.append(
            {
                "record_id": record_id,
                "jp12": job["jp12"],
                "before": job["old"],
                "after": job["new"],
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
            }
        )

    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map12_dec = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    live_dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    proofs: dict[str, str] = {}
    for record_id, job in JOBS.items():
        live = f2.decode_text(candidate, u32(candidate, int(job["owner"], 16)), live_dict12, map12_dec)
        gate(live == job["new"], f"live {record_id} {live!r}")
        proofs[record_id] = live

    leftover = [
        str(row["record_id"])
        for row in merged["records"]
        if row.get("semantic_category") == "stage_battle_condition_text"
        and str(row.get("translation_ko") or "") in {"전투력 증대", "전력 증대"}
    ]
    gate(not leftover, f"stage condition leftover {leftover}")
    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "stage-entry-orbit cave overflow")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": list(JOBS)})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": list(JOBS), "notes": NOTES}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    WORK.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT / "ggen_stage_entry_orbit_20260913.sav")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_stage_entry_orbit_20260913",
        "result": "PASS",
        "batch_id": BATCH_ID,
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "jobs": evidence,
        "proofs": proofs,
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {"path": advance_relative(WORK), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {
            "path": advance_relative(TRANSLATION_MERGED_JSON),
            "sha256": sha256(payload_json.encode("utf-8")),
        },
        "verification": {
            "result": "PASS",
            "fce1a0_orbit_not_combat_power": True,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "analysis" / "ggen_advance_stage_entry_orbit_candidate_20260913.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": "PASS", "painted_glyphs": painted, "cave": report["cave"], "output": report["output"], "proofs": proofs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
