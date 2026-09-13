"""Re-translate あと一息 calques that were misread as 한숨.

Japanese:
- ここまでくればあと一息です → not 한숨만 남았습니다
- あと一息ですものね → not 한숨만 남았죠
- あと一息よ！ → not 이제 한숨이야 (same idiom leftover)
"""
from __future__ import annotations

import json
import shutil
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
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    load_identified_12x12,
    raw_hex_bytes,
)
from patch_ggen_advance_name_unify_20260909 import (  # noqa: E402
    encode_overlay as _encode_overlay,
    patch_map_row_live,
)
import patch_ggen_advance_name_unify_20260909 as nu_mod  # noqa: E402


def encode_overlay(
    text: str,
    recovered: dict[str, int],
    verified: dict[str, int],
    live_tokens: dict[str, bytes],
    *,
    identified: dict[str, int] | None = None,
) -> bytes:
    if identified is not None:
        return _encode_overlay(text, recovered, verified, live_tokens, identified=identified)
    out = bytearray()
    for char in text:
        if char in live_tokens:
            out.extend(live_tokens[char])
            continue
        piece, missing = unified.encode_korean_text(
            char, recovered, verified_charmap=verified, strict_punctuation=True
        )
        gate(
            piece is not None and not missing and piece.endswith(b"\x00"),
            f"encode char {ascii(char)} missing={missing!r}",
        )
        out.extend(piece[:-1])
    out.append(0)
    return bytes(out)


nu_mod.encode_overlay = encode_overlay

BATCH_ID = "ato-hitoiki-not-sigh-20260912"
IDENTITY_KEY = "ato_hitoiki_20260912_sha256"
BATCH_KEY = "ato_hitoiki_20260912"
OUT = ROOT / "outputs" / "20260912_ato_hitoiki"
WORK = OUT / "ggen_ato_hitoiki_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_ato_hitoiki.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
CAVE_START = 0x01135430
CAVE_END = 0x01230000
MAP_BANK = (0x00F00000, 0x00FC0000)
NOTES = "あと一息는 한숨이 아니라 조금만 더/거의 다. 라미아스·동행 대사 재의역"
JOBS: dict[str, tuple[str, list[str]]] = {
    "GGA-MAPSCRIPT-00FAD1DB": (
        "やりましょう、ラミアス艦長\\nここまでくればあと一息です",
        ["합시다, 라미아스 함장", "여기까지면 거의 다입니다"],
    ),
    "GGA-MAPSCRIPT-00FAD2BE": (
        "もう、ここまで来たら\\nあと一息ですものね",
        ["이제, 여기까지 왔으면", "조금만 더면 되죠"],
    ),
    "GGA-MAPSCRIPT-00FB3721": (
        "あと一息よ！\\n全機、このまま攻撃を！！",
        ["이제 조금만 더야!", "전 기, 이대로 공격!!"],
    ),
}
BANNED = ("한숨만 남", "한숨이야")


def patch_merged_row(row: dict[str, Any], ko: str, segments: list[str]) -> None:
    row["translation_ko"] = ko
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


def live_map_lines(row: dict[str, Any], candidate: bytearray, dict12: list[bytes], map12: dict[int, str]) -> list[str]:
    cursor = int(str(row["target_file_offset"]), 16)
    lines: list[str] = []
    for segment in row.get("segments") or []:
        raw = raw_hex_bytes(str(segment.get("raw_hex") or ""))
        if not raw:
            continue
        orig = ROM_BASE + cursor
        lookups = aps.find_lookups(bytes(candidate), orig, orig + len(raw) - 1)
        gate(lookups, f"map lookup missing {row['record_id']} @ {hex(cursor)}")
        lines.append(f2.decode_text(candidate, lookups[0][1], dict12, map12))
        cursor += len(raw)
    return lines


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "ato-hitoiki cave is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    hangul12: set[str] = set()
    planned: list[tuple[dict[str, Any], list[str], list[str]]] = []
    for record_id, (source, new_segments) in JOBS.items():
        row = by_id[record_id]
        gate(str(row.get("source_scope")) == "scenario_map_script", f"scope {record_id}")
        gate(str(row.get("source_text") or "") == source, f"source drift {record_id}")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        gate(len(old_segments) == len(new_segments), f"segment count {record_id}")
        after = "\n".join(visible_segments(new_segments))
        for text in new_segments:
            gate(
                "\n" not in text and len(text) <= MAX_DIALOGUE_CELLS,
                f"dialogue width {record_id} len={len(text)} text={text!r}",
            )
            hangul12.update(hangul_chars(text))
        for text in old_segments:
            hangul12.update(hangul_chars(text))
        planned.append((row, old_segments, new_segments))
        _ = after

    extra = hangul_chars("여기까지면거의다입니다조금만더면되죠야")
    hangul12.update(extra)
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    identified = load_identified_12x12()
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied12: set[int] = set()
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    for char in extra:
        gate(char in recovered12, f"missing 12x12 {ascii(char)}")

    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    for row, old_segments, new_segments in planned:
        after = "\n".join(visible_segments(new_segments))
        patch_merged_row(row, after, new_segments)
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
        evidence.append({"record_id": row["record_id"], "after": after, "segments": written})

    leftover = [
        row["record_id"]
        for row in merged["records"]
        if any(token in str(row.get("translation_ko") or "") for token in BANNED)
        or any(any(token in str(item) for token in BANNED) for item in (row.get("translation_segments") or []))
    ]
    gate(not leftover, f"sigh leftover: {leftover}")
    changed = [index for index, (before, after) in enumerate(zip(parent, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == parent[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "ato-hitoiki cave overflow")

    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    proofs = {rid: live_map_lines(by_id[rid], candidate, dict12, map12) for rid in JOBS}
    gate(proofs["GGA-MAPSCRIPT-00FAD1DB"][1] == "여기까지면 거의 다입니다", ascii(proofs["GGA-MAPSCRIPT-00FAD1DB"]))
    gate(all("한숨" not in line for line in proofs["GGA-MAPSCRIPT-00FAD1DB"]), ascii(proofs["GGA-MAPSCRIPT-00FAD1DB"]))
    gate(proofs["GGA-MAPSCRIPT-00FAD2BE"][1] == "조금만 더면 되죠", ascii(proofs["GGA-MAPSCRIPT-00FAD2BE"]))
    gate(all("한숨" not in line for line in proofs["GGA-MAPSCRIPT-00FAD2BE"]), ascii(proofs["GGA-MAPSCRIPT-00FAD2BE"]))
    gate("조금만 더야" in proofs["GGA-MAPSCRIPT-00FB3721"][0], ascii(proofs["GGA-MAPSCRIPT-00FB3721"]))
    gate(all("한숨" not in line for line in proofs["GGA-MAPSCRIPT-00FB3721"]), ascii(proofs["GGA-MAPSCRIPT-00FB3721"]))

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
    shutil.copy2(MAIN_SAV, OUT / "ggen_ato_hitoiki_20260912.sav")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_ato_hitoiki_20260912",
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
            "original_map_script_bank_unchanged": True,
            "ato_hitoiki_not_sigh": True,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "analysis" / "ggen_advance_ato_hitoiki_candidate_20260912.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": "PASS",
                "painted_glyphs": painted,
                "cave": report["cave"],
                "output": report["output"],
                "proofs": proofs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
