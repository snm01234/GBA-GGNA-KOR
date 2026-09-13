"""Heero ID-command effect summary: 추가＋치명 → 봐주기＋치명.

Japanese source is 手加減＋痛撃 (slot-decoded 手加<028F>＋<045B>撃).
The previous 手加減攻撃 pass fixed 추가공격 but left this plus-form.
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
from ggen_advance_text_codec import DICT_8X16_BASE, DICT_8X16_END, ROM_BASE, load_dictionary  # noqa: E402
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars, patch_owned_payload  # noqa: E402
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import live_char_tokens  # noqa: E402
from patch_ggen_advance_idcmd_list_fit_20260909 import EFFECT_CAP  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, payload_at, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_name_unify_20260909 import encode_overlay  # noqa: E402

BATCH_ID = "heero-idcmd-mercy-crit-20260913"
IDENTITY_KEY = "heero_idcmd_mercy_20260913_sha256"
BATCH_KEY = "heero_idcmd_mercy_20260913"
OUT = ROOT / "outputs" / "20260913_heero_idcmd_mercy"
WORK = OUT / "ggen_heero_idcmd_mercy_20260913.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260913_heero_idcmd_mercy.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
CAVE_START = 0x011354C9
CAVE_END = 0x01230000
RECORD_ID = "GGA-TEXT-0017C736"
OLD = "추가＋치명"
NEW = "봐주기＋치명"
SOURCE = "手加<028F>＋<045B>撃"
NOTES = "히이로 ID커맨드 요약. 手加減＋痛撃. 추가=追加 오역 → 봐주기＋치명"


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def patch_merged_row(row: dict[str, Any], ko: str) -> None:
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
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "heero-idcmd cave is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(len(NEW.replace("\n", "")) <= EFFECT_CAP, f"effect cap {NEW!r}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    row = by_id[RECORD_ID]
    gate(str(row.get("source_text") or "") == SOURCE, f"source drift {RECORD_ID}")
    gate(str(row.get("translation_ko") or "") == OLD, f"old drift {RECORD_ID}")
    gate(str(row.get("semantic_category")) == "id_command_effect_summary", "category drift")
    leftover_before = [
        str(item["record_id"])
        for item in merged["records"]
        if "추가＋치명" in str(item.get("translation_ko") or "")
        or "추가+치명" in str(item.get("translation_ko") or "")
    ]
    gate(leftover_before == [RECORD_ID], f"unexpected 추가＋치명 {leftover_before}")

    hangul8 = hangul_chars(OLD) | hangul_chars(NEW)
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied8: set[int] = set()
    recovered8 = f2.recover_hangul(
        candidate, japan, hangul8, mode=8, live=live8, occupied=occupied8, allowed=allowed, painted=painted
    )
    for char in hangul_chars(NEW):
        gate(char in recovered8, f"missing 8x16 {ascii(char)}")

    owners = owner_offsets(row)
    gate(owners, f"no owners {RECORD_ID}")
    ptrs = {u32(parent, owner) for owner in owners}
    gate(len(ptrs) == 1, f"{RECORD_ID} owners diverge")
    pointer = next(iter(ptrs))
    old_payload = payload_at(parent, pointer)
    live_tokens = live_char_tokens(OLD, old_payload)
    new_payload = encode_overlay(NEW, recovered8, verified8, live_tokens)
    cave_cursor, old_addresses, new_addr = patch_owned_payload(
        row, old_payload, new_payload, parent, candidate, allowed, cave_cursor := CAVE_START, require_nul=True
    )
    patch_merged_row(row, NEW)

    hangul_live8 = f2.hangul_slot_map(candidate, mode=8)
    map8 = f2.slot_to_char_map(verified8, recovered8, hangul_live8)
    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)
    live = f2.decode_text(candidate, u32(candidate, owners[0]), dict8, map8)
    gate(live == NEW, f"live {live!r}")
    leftover = [
        str(item["record_id"])
        for item in merged["records"]
        if "추가＋치명" in str(item.get("translation_ko") or "")
        or "추가+치명" in str(item.get("translation_ko") or "")
        or (
            str(item.get("semantic_category")) == "id_command_effect_summary"
            and "手加" in str(item.get("source_text") or "")
            and "추가" in str(item.get("translation_ko") or "")
        )
    ]
    gate(not leftover, f"translation leftover {leftover}")
    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "heero-idcmd cave overflow")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [RECORD_ID]})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(item.get("translation_status") or "") for item in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": [RECORD_ID], "notes": NOTES}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    WORK.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT / "ggen_heero_idcmd_mercy_20260913.sav")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_heero_idcmd_mercy_20260913",
        "result": "PASS",
        "batch_id": BATCH_ID,
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "jobs": [
            {
                "record_id": RECORD_ID,
                "path": "u32_8x16",
                "before": OLD,
                "after": NEW,
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
                "encoded_size": len(new_payload),
            }
        ],
        "proofs": {"heero_effect": live},
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {"path": advance_relative(WORK), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {
            "path": advance_relative(TRANSLATION_MERGED_JSON),
            "sha256": sha256(payload_json.encode("utf-8")),
        },
        "verification": {
            "result": "PASS",
            "heero_tegakagen_plus_crit": True,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "analysis" / "ggen_advance_heero_idcmd_mercy_candidate_20260913.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": "PASS", "painted_glyphs": painted, "cave": report["cave"], "output": report["output"], "proofs": report["proofs"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
