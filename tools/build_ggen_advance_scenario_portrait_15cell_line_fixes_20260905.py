#!/usr/bin/env python3
"""User-requested wording fixes on the 15-cell scenario candidate.

- 잊었냐 → 잊었다
- POW line restores 포로의 치욕은 받지 않겠다
- 쓰러뜨리냐 → 쓰러뜨릴까보냐
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
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_scenario_portrait_15 import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    translation_ko_from_segments,
    visible_pairs,
)
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402

ROM_BASE = 0x08000000
CAVE_START = 0x012A2880
CAVE_END = 0x012A6000
BATCH_ID = "scenario-portrait-15cell-line-fixes-20260905"
PARENT_ROM = (
    ROOT
    / "outputs"
    / "20260905_ggen_advance_scenario_portrait_15cell"
    / "ggen_advance_scenario_portrait_15cell_candidate_20260905.gba"
)
PARENT_MANIFEST = ROOT / "analysis" / "ggen_advance_scenario_portrait_15cell_candidate_20260905.json"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_scenario_portrait_15cell_line_fixes"
OUT_ROM = OUT_DIR / "ggen_advance_scenario_portrait_15cell_line_fixes_candidate_20260905.gba"
OUT_SAV = OUT_ROM.with_suffix(".sav")
OUT_MANIFEST = ROOT / "analysis" / "ggen_advance_scenario_portrait_15cell_line_fixes_candidate_20260905.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260905_scenario_portrait_15cell_line_fixes.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
ALLCLEAR_SAV = ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.sav"

FIXES: dict[str, list[str]] = {
    "GGA-SCENARIO-001F669C": ["", "", "너희 따위의 힘으로", "앱살라스를 쓰러뜨릴까보냐！", ""],
    "GGA-SCENARIO-001F7AAC": ["", "", "조국에 바친 이 목숨!", "포로의 치욕은 받지 않겠다!", ""],
    "GGA-SCENARIO-0021546C": ["", "", "이 람바 랄이……", "싸움 속에서 싸움을 잊었다！", ""],
}


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


def write_payload(
    candidate: bytearray,
    address: int,
    encoded: bytes,
    old_size: int,
    allowed: set[int],
    cursor: int,
) -> tuple[int, int]:
    if len(encoded) <= old_size:
        start = address - ROM_BASE
        candidate[start : start + len(encoded)] = encoded
        if len(encoded) < old_size:
            candidate[start + len(encoded) : start + old_size] = b"\x00" * (old_size - len(encoded))
        allowed.update(range(start, start + old_size))
        return address, cursor
    gate(cursor + len(encoded) <= CAVE_END, "line-fix cave exhausted")
    start = cursor
    candidate[start : start + len(encoded)] = encoded
    allowed.update(range(start, start + len(encoded)))
    return ROM_BASE + start, (start + len(encoded) + 3) & ~3


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
    parent_manifest = json.loads(PARENT_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    gate(sha256(parent) == parent_manifest["output"]["sha256"], "parent is not the 15-cell candidate")
    gate(all(value == 0 for value in parent[CAVE_START:CAVE_END]), "line-fix cave is not zero-filled")

    by_id = {row["record_id"]: row for row in merged["records"]}
    hangul: set[str] = set()
    for record_id, new_segments in FIXES.items():
        row = by_id[record_id]
        visible = [text for _index, text in visible_pairs(new_segments)]
        gate(all(len(text) <= MAX_DIALOGUE_CELLS for text in visible), f"{record_id} exceeds 15: {visible}")
        hangul |= hangul_chars("".join(row.get("translation_segments") or []) + "".join(new_segments))

    font12 = load_galmuri12()
    recovered = recover_unique_12x12_slots(parent, font12, hangul)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)

    candidate = bytearray(parent)
    allowed: set[int] = set()
    cave_cursor = CAVE_START
    fixes: list[dict[str, Any]] = []

    for record_id, new_segments in FIXES.items():
        row = by_id[record_id]
        old_segments = [str(item) for item in row["translation_segments"]]
        gate(len(old_segments) == len(new_segments), f"{record_id} segment framing drift")
        old_row = dict(row)
        old_row["translation_segments"] = old_segments
        old_payload, old_missing = unified.rebuild_scenario_payload(
            old_row, recovered, verified12, translate=True
        )
        new_ko = translation_ko_from_segments(new_segments)
        row["translation_ko"] = new_ko
        row["translation_segments"] = list(new_segments)
        row["overlay_batch_id"] = BATCH_ID
        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["reviewed_at"] = "2026-09-05"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["qa_status"] = "portrait_15cell_fit"
        row["translator_notes"] = "user wording fix on 15-cell portrait line; keep meaning, max 15 cells"
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
        gate(old_payload is not None and not old_missing, f"{record_id} old rebuild failed: {old_missing}")
        gate(new_payload is not None and not new_missing, f"{record_id} new rebuild failed: {new_missing}")
        assert old_payload is not None and new_payload is not None
        owners = owner_offsets(row)
        gate(owners, f"{record_id} has no U32 owners")
        new_addr = None
        old_addresses: list[int] = []
        for owner in owners:
            pointer = struct.unpack_from("<I", parent, owner)[0]
            file_off = pointer - ROM_BASE
            live = bytes(parent[file_off : file_off + len(old_payload)])
            gate(live == old_payload, f"live mismatch {record_id} owner 0x{owner:08X}")
            old_addresses.append(pointer)
            written_addr, cave_cursor = write_payload(
                candidate, pointer, new_payload, len(old_payload), allowed, cave_cursor
            )
            if written_addr != pointer:
                struct.pack_into("<I", candidate, owner, written_addr)
                allowed.update(range(owner, owner + 4))
            new_addr = written_addr
        live_new = bytes(candidate[new_addr - ROM_BASE : new_addr - ROM_BASE + len(new_payload)])
        gate(live_new == new_payload, f"{record_id} candidate payload mismatch")
        visible = [text for _index, text in visible_pairs(new_segments)]
        fixes.append(
            {
                "record_id": record_id,
                "before": "\n".join(text for text in old_segments if text.strip()),
                "after": new_ko,
                "cells": [len(text) for text in visible],
                "old_addresses": [f"0x{addr:08X}" for addr in old_addresses],
                "new_address": f"0x{new_addr:08X}",
            }
        )

    parent_overlay = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent_overlay,
            "batch_id": BATCH_ID,
            "fixes": fixes,
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent_overlay
    merged["identity"]["scenario_portrait_15cell_line_fixes_sha256"] = identity
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
        "kind": "ggen_advance_scenario_portrait_15cell_line_fixes_candidate_20260905",
        "result": "PASS",
        "base": {"path": advance_relative(PARENT_ROM), "sha256": sha256(parent)},
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "size": len(out),
            "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
        },
        "fixes": fixes,
        "verification": {
            "result": "PASS",
            "max_dialogue_cells": MAX_DIALOGUE_CELLS,
            "changed_bytes": len(changed),
            "cave_used": cave_cursor - CAVE_START,
        },
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "rom": advance_relative(OUT_ROM), "sha256": sha256(out), "fixes": fixes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
