#!/usr/bin/env python3
"""Fit Kamille's gravity line into the 15-cell portrait dialogue box.

Measured clip: ``진짜 나쁜 것은… 지구의 중력에`` is 17 cells; ``에`` draws
into the frame.  Line 2 has only two spare cells, so the last word cannot
move.  Rephrase keeps the meaning without deleting spaces.
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
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    load_galmuri12,
    recover_unique_12x12_slots,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import write_payload  # noqa: E402
from patch_ggen_advance_map_script_inline_poc import MAX_DIALOGUE_CELLS  # noqa: E402

ROM_BASE = 0x08000000
RECORD_ID = "GGA-SCENARIO-001FC74C"
CAVE_START = 0x012A2880
CAVE_END = 0x012A6000
BATCH_ID = "scenario-portrait-15cell-kamille-20260905"
NEW_SEGMENTS = ["", "", "진짜 나쁜 것은 지구 중력에", "영혼이 끌린 인간들이다！", ""]
NEW_KO = "진짜 나쁜 것은 지구 중력에\n영혼이 끌린 인간들이다！"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_kamille_gravity_fit"
OUT_ROM = OUT_DIR / "ggen_advance_kamille_gravity_fit_candidate_20260905.gba"
OUT_SAV = OUT_ROM.with_suffix(".sav")
OUT_MANIFEST = ROOT / "analysis" / "ggen_advance_kamille_gravity_fit_candidate_20260905.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260905_kamille_gravity.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
ALLCLEAR_SAV = ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.sav"


def gate(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"gate failed: {message}")


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()


def hangul_chars(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


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
    visible = [item for item in NEW_SEGMENTS if item.strip()]
    gate(all(len(item) <= MAX_DIALOGUE_CELLS for item in visible), "Kamille lines exceed 15 cells")
    gate(len(NEW_SEGMENTS[2]) == 15, "line 1 cell count drift")
    gate(len(NEW_SEGMENTS[3]) == 13, "line 2 cell count drift")

    parent = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "parent is not current main TIP")
    gate(all(value == 0 for value in parent[CAVE_START:CAVE_END]), "kamille cave is not zero-filled")

    by_id = {row["record_id"]: row for row in merged["records"]}
    row = by_id[RECORD_ID]
    gate(row["translation_ko"].startswith("진짜 나쁜 것은"), "Kamille source translation drift")
    old_segments = [str(item) for item in row["translation_segments"]]
    gate(len(old_segments) == len(NEW_SEGMENTS), "segment framing drift")

    hangul = hangul_chars("".join(NEW_SEGMENTS) + str(row.get("translation_ko") or ""))
    font12 = load_galmuri12()
    recovered = recover_unique_12x12_slots(parent, font12, hangul)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)

    old_row = dict(row)
    old_row["translation_segments"] = old_segments
    old_payload, old_missing = unified.rebuild_scenario_payload(
        old_row, recovered, verified12, translate=True
    )
    row["translation_ko"] = NEW_KO
    row["translation_segments"] = list(NEW_SEGMENTS)
    row["overlay_batch_id"] = BATCH_ID
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["reviewed_at"] = "2026-09-05"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["qa_status"] = "portrait_15cell_fit"
    row["translator_notes"] = (
        "portrait 12x12 15-cell fit; 지구의→지구 to keep 중력에 on line 1; no space-stripping"
    )
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
    new_payload, new_missing = unified.rebuild_scenario_payload(
        row, recovered, verified12, translate=True
    )
    gate(old_payload is not None and not old_missing, f"old rebuild failed: {old_missing}")
    gate(new_payload is not None and not new_missing, f"new rebuild failed: {new_missing}")
    assert old_payload is not None and new_payload is not None

    candidate = bytearray(parent)
    allowed: set[int] = set()
    cave_cursor = CAVE_START
    owners = owner_offsets(row)
    gate(owners, "Kamille row has no U32 owners")
    new_addr = None
    old_addresses = []
    for owner in owners:
        pointer = struct.unpack_from("<I", parent, owner)[0]
        file_off = pointer - ROM_BASE
        live = bytes(parent[file_off : file_off + len(old_payload)])
        gate(live == old_payload, f"live mismatch owner 0x{owner:08X}")
        old_addresses.append(pointer)
        written_addr, cave_cursor = write_payload(
            candidate, pointer, new_payload, len(old_payload), allowed, cave_cursor, require_nul=False
        )
        if written_addr != pointer:
            struct.pack_into("<I", candidate, owner, written_addr)
            allowed.update(range(owner, owner + 4))
        new_addr = written_addr

    parent_overlay = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent_overlay,
            "batch_id": BATCH_ID,
            "record_id": RECORD_ID,
            "payload": row["translation_payload_sha256"],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent_overlay
    merged["identity"]["kamille_gravity_fit_sha256"] = identity
    merged["identity"]["translation_overlay_identity_sha256"] = identity
    counts = dict(sorted(Counter(str(item.get("translation_status") or "") for item in merged["records"]).items()))
    merged["summary"]["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = identity

    changed = [index for index, (before, after) in enumerate(zip(parent, candidate)) if before != after]
    stray = sorted(set(changed) - allowed)
    gate(set(changed) <= allowed, f"changed outside targets: {[hex(off) for off in stray[:12]]}")

    out = bytes(candidate)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ROM.write_bytes(out)
    sav_src = ALLCLEAR_SAV if ALLCLEAR_SAV.is_file() else MAIN_SAV
    if sav_src.is_file():
        shutil.copy2(sav_src, OUT_SAV)
    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    manifest = {
        "schema_version": 1,
        "kind": "ggen_advance_kamille_gravity_fit_candidate_20260905",
        "result": "PASS",
        "base": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "size": len(out),
            "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
        },
        "fixes": [
            {
                "record_id": RECORD_ID,
                "before": "\n".join(item for item in old_segments if item.strip()),
                "after": NEW_KO,
                "cells": [len(item) for item in visible],
                "old_addresses": [f"0x{addr:08X}" for addr in old_addresses],
                "new_address": f"0x{new_addr:08X}",
            }
        ],
        "verification": {
            "result": "PASS",
            "max_dialogue_cells": MAX_DIALOGUE_CELLS,
            "changed_bytes": len(changed),
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": advance_relative(OUT_ROM), "sha256": sha256(out), "fixes": manifest["fixes"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
