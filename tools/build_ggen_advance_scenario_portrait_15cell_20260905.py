#!/usr/bin/env python3
"""Fit remaining scenario_main portrait lines to 15 12x12 cells.

Portrait boxes do not wrap.  Map scripts already gate at 15 cells; scenario
body lines were still overflowing.  This batch keeps control signatures
(no extra lines), moves phrases only at word boundaries, and paraphrases
when a grammatical split cannot fit.
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
from ggen_advance_scenario_portrait_15 import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    apply_to_segments,
    overlong_scenario_rows,
    translation_ko_from_segments,
    visible_pairs,
)
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402

ROM_BASE = 0x08000000
CAVE_START = 0x012A2880
CAVE_END = 0x012A6000
BATCH_ID = "scenario-portrait-15cell-batch-20260905"
OUT_DIR = ROOT / "outputs" / "20260905_ggen_advance_scenario_portrait_15cell"
OUT_ROM = OUT_DIR / "ggen_advance_scenario_portrait_15cell_candidate_20260905.gba"
OUT_SAV = OUT_ROM.with_suffix(".sav")
OUT_MANIFEST = ROOT / "analysis" / "ggen_advance_scenario_portrait_15cell_candidate_20260905.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260905_scenario_portrait_15cell.json"
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
    gate(cursor + len(encoded) <= CAVE_END, "scenario 15-cell cave exhausted")
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


def patch_row_metadata(row: dict[str, Any], new_ko: str, new_segments: list[str], method: str) -> None:
    row["translation_ko"] = new_ko
    row["translation_segments"] = list(new_segments)
    row["overlay_batch_id"] = BATCH_ID
    row["qa_status"] = "portrait_15cell_fit"
    row["translator_notes"] = f"portrait 12x12 15-cell fit ({method}); no last-word shuffle, no space-stripping"
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


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parent = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    gate(sha256(parent) == main_manifest["sha256"], "parent is not current main TIP")
    gate(all(value == 0 for value in parent[CAVE_START:CAVE_END]), "scenario 15-cell cave is not zero-filled")

    targets = overlong_scenario_rows(merged["records"])
    gate(targets, "no scenario_main portrait overflows to fit")
    planned: list[dict[str, Any]] = []
    hangul: set[str] = set()
    for row in targets:
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        applied = apply_to_segments(row["record_id"], old_segments)
        gate(applied is not None, f"{row['record_id']} fitter returned no change")
        assert applied is not None
        new_segments, method = applied
        new_visible = [text for _index, text in visible_pairs(new_segments)]
        gate(
            all(len(text) <= MAX_DIALOGUE_CELLS for text in new_visible),
            f"{row['record_id']} still exceeds 15: {new_visible}",
        )
        gate(len(new_segments) == len(old_segments), f"{row['record_id']} segment framing drift")
        hangul |= hangul_chars("".join(old_segments) + "".join(new_segments) + str(row.get("translation_ko") or ""))
        planned.append(
            {
                "row": row,
                "old_segments": old_segments,
                "new_segments": new_segments,
                "method": method,
                "new_ko": translation_ko_from_segments(new_segments),
                "cells": [len(text) for text in new_visible],
            }
        )
    gate("깃" not in hangul, "batch uses 깃; unique 12x12 recover cannot encode it")

    font12 = load_galmuri12()
    recovered = recover_unique_12x12_slots(parent, font12, hangul)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)

    candidate = bytearray(parent)
    allowed: set[int] = set()
    cave_cursor = CAVE_START
    fixes: list[dict[str, Any]] = []
    methods = Counter(item["method"] for item in planned)
    in_place = 0
    relocated = 0

    for item in planned:
        row = item["row"]
        old_row = dict(row)
        old_row["translation_segments"] = item["old_segments"]
        old_payload, old_missing = unified.rebuild_scenario_payload(
            old_row, recovered, verified12, translate=True
        )
        patch_row_metadata(row, item["new_ko"], item["new_segments"], item["method"])
        new_payload, new_missing = unified.rebuild_scenario_payload(
            row, recovered, verified12, translate=True
        )
        gate(old_payload is not None and not old_missing, f"{row['record_id']} old rebuild failed: {old_missing}")
        gate(new_payload is not None and not new_missing, f"{row['record_id']} new rebuild failed: {new_missing}")
        assert old_payload is not None and new_payload is not None
        owners = owner_offsets(row)
        gate(owners, f"{row['record_id']} has no U32 owners")
        new_addr = None
        old_addresses: list[int] = []
        written_for_pointer: dict[int, int] = {}
        for owner in owners:
            pointer = struct.unpack_from("<I", parent, owner)[0]
            file_off = pointer - ROM_BASE
            live = bytes(parent[file_off : file_off + len(old_payload)])
            gate(live == old_payload, f"live mismatch {row['record_id']} owner 0x{owner:08X}")
            old_addresses.append(pointer)
            if pointer in written_for_pointer:
                written_addr = written_for_pointer[pointer]
            else:
                written_addr, cave_cursor = write_payload(
                    candidate, pointer, new_payload, len(old_payload), allowed, cave_cursor
                )
                written_for_pointer[pointer] = written_addr
            if written_addr != pointer:
                struct.pack_into("<I", candidate, owner, written_addr)
                allowed.update(range(owner, owner + 4))
            new_addr = written_addr
        if new_addr == old_addresses[0]:
            in_place += 1
        else:
            relocated += 1
        live_new = bytes(candidate[new_addr - ROM_BASE : new_addr - ROM_BASE + len(new_payload)])
        gate(live_new == new_payload, f"{row['record_id']} candidate payload mismatch")
        fixes.append(
            {
                "record_id": row["record_id"],
                "method": item["method"],
                "before": "\n".join(text for text in item["old_segments"] if text.strip()),
                "after": item["new_ko"],
                "cells": item["cells"],
                "old_addresses": [f"0x{addr:08X}" for addr in old_addresses],
                "new_address": f"0x{new_addr:08X}",
            }
        )

    leftover = overlong_scenario_rows(merged["records"])
    gate(not leftover, f"leftover overflows: {[row['record_id'] for row in leftover[:8]]}")

    fitted_by_id = {item["row"]["record_id"]: item for item in planned}
    alias_updated = 0
    for row in merged["records"]:
        if row.get("scope_status") != "alias":
            continue
        source = fitted_by_id.get(str(row.get("alias_of") or ""))
        if source is None:
            continue
        patch_row_metadata(row, source["new_ko"], source["new_segments"], source["method"])
        alias_updated += 1

    parent_overlay = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    identity = digest(
        {
            "parent": parent_overlay,
            "batch_id": BATCH_ID,
            "record_ids": [item["row"]["record_id"] for item in planned],
            "payloads": [item["row"]["translation_payload_sha256"] for item in planned],
        }
    )
    merged["identity"]["parent_translation_overlay_identity_sha256"] = parent_overlay
    merged["identity"]["scenario_portrait_15cell_sha256"] = identity
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
        "kind": "ggen_advance_scenario_portrait_15cell_candidate_20260905",
        "result": "PASS",
        "base": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(parent)},
        "output": {
            "path": advance_relative(OUT_ROM),
            "sha256": sha256(out),
            "crc32": f"0x{binascii.crc32(out) & 0xFFFFFFFF:08X}",
            "size": len(out),
            "sav": advance_relative(OUT_SAV) if OUT_SAV.exists() else None,
        },
        "batch": {
            "id": BATCH_ID,
            "records": len(planned),
            "methods": dict(methods),
            "in_place": in_place,
            "relocated": relocated,
            "alias_updated": alias_updated,
            "cave_used": cave_cursor - CAVE_START,
            "cave_start": f"0x{CAVE_START:08X}",
            "cave_end": f"0x{CAVE_END:08X}",
        },
        "fixes": fixes,
        "verification": {
            "result": "PASS",
            "max_dialogue_cells": MAX_DIALOGUE_CELLS,
            "leftover_scenario_main": 0,
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
                "records": len(planned),
                "methods": dict(methods),
                "in_place": in_place,
                "relocated": relocated,
                "changed_bytes": len(changed),
                "cave_used": cave_cursor - CAVE_START,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
