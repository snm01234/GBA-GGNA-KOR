"""Battle quote 開け！ 열려라 → 열어라.

Scenario templates inject the weapon name via DYNAMIC (機関砲 → 기관포).
열려라 is the sesame/passive form; the JP 開け！ is a command: 열어라.
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
from ggen_advance_text_codec import DICT_12X12_BASE, DICT_12X12_END, ROM_BASE, load_dictionary  # noqa: E402
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars, visible_segments  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import MAX_DIALOGUE_CELLS, raw_hex_bytes  # noqa: E402
from patch_ggen_advance_name_unify_20260909 import rebuild_scenario_live  # noqa: E402

BATCH_ID = "cannon-open-command-20260913"
IDENTITY_KEY = "cannon_open_20260913_sha256"
BATCH_KEY = "cannon_open_20260913"
OUT = ROOT / "outputs" / "20260913_cannon_open"
WORK = OUT / "ggen_cannon_open_20260913.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260913_cannon_open.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
CAVE_START = 0x0113553D
CAVE_END = 0x01230000
MAP_BANK = (0x00F00000, 0x00FC0000)
OLD = "열려라!"
NEW = "열어라!"
JOBS: dict[str, dict[str, Any]] = {
    "GGA-SCENARIO-002077AC": {
        "source": "⟦DYNAMIC⟧<01C5>げ！\\n<00AB>ど！\\n",
        "old_segments": ["", "", "", "열려라!", "쏴!", ""],
        "new_segments": ["", "", "", "열어라!", "쏴!", ""],
    },
    "GGA-SCENARIO-00217B30": {
        "source": "⟦DYNAMIC⟧<01C5>げ！\\n……<05A5><0382>ッ！！\\n",
        "old_segments": ["", "", "", "열려라!", "……발사!!", ""],
        "new_segments": ["", "", "", "열어라!", "……발사!!", ""],
    },
}
NOTES = "전투 열어라. DYNAMIC+開け！(기관포 등). 열려라(참깨형)→열어라(명령형)"


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def patch_merged_row(row: dict[str, Any], ko: str, segments: list[str]) -> None:
    row["translation_ko"] = ko
    row["translation_segments"] = segments
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


def live_scenario_lines(row: dict[str, Any], rom: bytes | bytearray, dict12: list[bytes], map12: dict[int, str]) -> list[str]:
    pointer = u32(rom, owner_offsets(row)[0])
    live = bytes(rom[pointer - ROM_BASE :])
    lines: list[str] = []
    index = 0
    for segment, control, text in zip(row.get("segments") or [], row.get("control_signature") or [], row.get("translation_segments") or []):
        original = raw_hex_bytes(str(segment.get("raw_hex") or ""))
        code = int(control["code"], 16)
        extra = 1 + (1 if code in (0x05, 0x06) else 0)
        if text:
            nul = live.find(0, index)
            gate(nul >= 0, f"live NUL missing {row['record_id']}")
            lines.append(f2.decode_text(rom, pointer + index, dict12, map12))
            index = nul + 1
        else:
            index += len(original)
        index += extra
    return lines


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "cannon-open cave is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(len(NEW) <= MAX_DIALOGUE_CELLS, f"width {NEW!r}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    leftover_before = [
        str(row["record_id"])
        for row in merged["records"]
        if OLD in str(row.get("translation_ko") or "")
        or any(OLD in str(seg) for seg in (row.get("translation_segments") or []))
    ]
    gate(leftover_before == list(JOBS), f"unexpected 열려라 {leftover_before}")

    hangul12 = hangul_chars("".join([OLD, NEW, "쏴발사"]))
    _live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied12: set[int] = set()
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    for char in hangul_chars(NEW):
        gate(char in recovered12, f"missing 12x12 {ascii(char)}")

    cave_cursor = CAVE_START
    jobs: list[dict[str, Any]] = []
    for record_id, spec in JOBS.items():
        row = by_id[record_id]
        gate(str(row.get("source_scope")) == "scenario_main", f"scope {record_id}")
        gate(str(row.get("source_text") or "") == spec["source"], f"source drift {record_id}")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        gate(old_segments == spec["old_segments"], f"old segments {record_id} {old_segments}")
        new_segments = list(spec["new_segments"])
        after = "\n".join(visible_segments(new_segments))
        owners = owner_offsets(row)
        gate(owners, f"no owners {record_id}")
        live_from = bytes(parent[u32(parent, owners[0]) - ROM_BASE :])
        identity_payload, consumed = rebuild_scenario_live(
            row, old_segments, old_segments, live_from, recovered12, verified12
        )
        old_payload = live_from[:consumed]
        gate(identity_payload == old_payload, f"live identity rebuild drift {record_id}")
        new_payload, _consumed = rebuild_scenario_live(
            row, old_segments, new_segments, live_from, recovered12, verified12
        )
        cave_cursor, old_addresses, new_addr = aps.patch_owned_payload(
            row, old_payload, new_payload, parent, candidate, allowed, cave_cursor, require_nul=False
        )
        patch_merged_row(row, after, new_segments)
        jobs.append(
            {
                "record_id": record_id,
                "path": "scenario_main",
                "before": "\n".join(visible_segments(old_segments)),
                "after": after,
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
            }
        )

    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    proofs: dict[str, list[str]] = {}
    for record_id, spec in JOBS.items():
        live_lines = live_scenario_lines(by_id[record_id], candidate, dict12, map12)
        expected = visible_segments(spec["new_segments"])
        live_norm = [line.replace("！", "!") for line in live_lines]
        gate(live_norm == expected, f"{record_id} live {live_lines!r} != {expected!r}")
        proofs[record_id] = live_norm

    leftover = [
        str(row["record_id"])
        for row in merged["records"]
        if OLD in str(row.get("translation_ko") or "")
        or any(OLD in str(seg) for seg in (row.get("translation_segments") or []))
    ]
    gate(not leftover, f"열려라 leftover {leftover}")
    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes x{len(changed - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == parent[MAP_BANK[0] : MAP_BANK[1]], "map bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "cannon-open cave overflow")

    changed_ids = list(JOBS)
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
    shutil.copy2(MAIN_SAV, OUT / "ggen_cannon_open_20260913.sav")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_cannon_open_20260913",
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
            "open_sesame_to_command": True,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "analysis" / "ggen_advance_cannon_open_candidate_20260913.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": "PASS", "painted_glyphs": painted, "cave": report["cave"], "output": report["output"], "proofs": proofs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
