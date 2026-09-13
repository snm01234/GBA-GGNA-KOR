"""Fix Shiro→Aina 형님 and the UC 0089 cinematic year.

- もう君のお兄さんが: Shiro to Aina, so 오빠 not 형님
- 時に宇宙世紀0089……9月半ば: in-game ss5 shows 0089; 08th MS Team date is UC 0079
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
from ggen_advance_text_codec import (  # noqa: E402
    DICT_12X12_BASE,
    DICT_12X12_END,
    ROM_BASE,
    load_dictionary,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import hangul_chars, visible_segments  # noqa: E402
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import read_tokens  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, payload_at, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
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

BATCH_ID = "shiro-oppa-uc0079-20260912"
IDENTITY_KEY = "shiro_oppa_uc0079_20260912_sha256"
BATCH_KEY = "shiro_oppa_uc0079_20260912"
OUT = ROOT / "outputs" / "20260912_shiro_oppa_uc0079"
WORK = OUT / "ggen_shiro_oppa_uc0079_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_shiro_oppa_uc0079.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
CAVE_START = 0x01135470
CAVE_END = 0x01230000
MAP_BANK = (0x00F00000, 0x00FC0000)
NOTES = "시로→아이나 お兄さんは 오빠. 시네마틱 우주세기 0089→0079 (ss5 08팀 연도)"
SHIRO_ID = "GGA-MAPSCRIPT-00FB3580"
SHIRO_SOURCE = "もう君のお兄さんが\\n君のことを悩ませることはない"
SHIRO_SEGMENTS = ["이제 네 오빠가", "너를 괴롭히는 일은 없어"]
DATE_ID = "GGA-TEXT-001C8C4A"
DATE_SOURCE = "時に宇宙世紀0089……9月半ば"
DATE_BEFORE = "우주세기 0089 9월중순"
DATE_AFTER = "우주세기 0079 9월중순"


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def splice_same_length(
    before: str,
    after: str,
    live: bytes,
    recovered: dict[str, int],
    verified: dict[str, int],
) -> bytes:
    gate(len(before) == len(after), f"length drift {before!r} -> {after!r}")
    tokens = read_tokens(live)
    gate(len(tokens) == len(before), f"token/text drift {len(tokens)}!={len(before)}")
    out = bytearray()
    for old_ch, new_ch, token in zip(before, after, tokens):
        if old_ch == new_ch:
            out.extend(token)
            continue
        piece = encode_overlay(new_ch, recovered, verified, {})
        gate(piece.endswith(b"\x00") and piece[:-1], f"splice encode empty {new_ch!r}")
        out.extend(piece[:-1])
    out.append(0)
    return bytes(out)


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
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "shiro-oppa cave is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(len(DATE_AFTER) <= 16, f"narration width {len(DATE_AFTER)}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    shiro = by_id[SHIRO_ID]
    date_row = by_id[DATE_ID]
    gate(str(shiro.get("source_text") or "") == SHIRO_SOURCE, "shiro source drift")
    gate(str(date_row.get("source_text") or "") == DATE_SOURCE, "date source drift")
    gate(str(date_row.get("translation_ko") or "") == DATE_BEFORE, "date ko drift")
    old_segments = [str(item) for item in (shiro.get("translation_segments") or [])]
    gate(len(old_segments) == len(SHIRO_SEGMENTS), "shiro segment count")
    for text in SHIRO_SEGMENTS:
        gate("\n" not in text and len(text) <= MAX_DIALOGUE_CELLS, f"shiro width {text!r}")

    hangul12 = hangul_chars("".join(old_segments) + "".join(SHIRO_SEGMENTS) + DATE_BEFORE + DATE_AFTER)
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
    for char in hangul_chars("오빠가"):
        gate(char in recovered12, f"missing 12x12 {ascii(char)}")
    gate("7" in verified12, "verified 12x12 missing digit 7")

    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    patch_merged_row(shiro, "\n".join(visible_segments(SHIRO_SEGMENTS)), SHIRO_SEGMENTS)
    cave_cursor, written = patch_map_row_live(
        shiro,
        old_segments,
        SHIRO_SEGMENTS,
        parent,
        candidate,
        recovered12,
        identified,
        verified12,
        allowed,
        cave_cursor,
    )
    evidence.append({"record_id": SHIRO_ID, "path": "map_script", "segments": written})

    owners = owner_offsets(date_row)
    pointer = u32(parent, owners[0])
    live = payload_at(parent, pointer)
    new_payload = splice_same_length(DATE_BEFORE, DATE_AFTER, live, recovered12, verified12)
    cave_cursor, old_addresses, new_addr = aps.patch_owned_payload(
        date_row, live, new_payload, parent, candidate, allowed, cave_cursor, require_nul=True
    )
    patch_merged_row(date_row, DATE_AFTER)
    evidence.append(
        {
            "record_id": DATE_ID,
            "path": "u32_12x12",
            "before": DATE_BEFORE,
            "after": DATE_AFTER,
            "old_active_addresses": old_addresses,
            "new_address": new_addr,
        }
    )

    leftover = [
        row["record_id"]
        for row in merged["records"]
        if "네 형님" in str(row.get("translation_ko") or "")
        or "우주세기 0089" in str(row.get("translation_ko") or "")
    ]
    gate(not leftover, f"leftover {leftover}")
    changed = [index for index, (before, after) in enumerate(zip(parent, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == parent[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")

    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    shiro_live = live_map_lines(shiro, candidate, dict12, map12)
    date_live = f2.decode_text(candidate, u32(candidate, owners[0]), dict12, map12)
    proofs = {"shiro": shiro_live, "date": date_live}
    gate(shiro_live[0] == "이제 네 오빠가" or shiro_live[0].replace("、", ",") == "이제 네 오빠가", ascii(shiro_live))
    gate("오빠" in shiro_live[0] and "형님" not in "".join(shiro_live), ascii(shiro_live))
    gate(date_live == DATE_AFTER, ascii(date_live))
    gate("0089" not in date_live and "0079" in date_live, ascii(date_live))

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [SHIRO_ID, DATE_ID]})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": [SHIRO_ID, DATE_ID], "notes": NOTES}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    WORK.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT / "ggen_shiro_oppa_uc0079_20260912.sav")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_shiro_oppa_uc0079_20260912",
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
            "shiro_oppa_not_hyungnim": True,
            "uc0079_not_0089": True,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "analysis" / "ggen_advance_shiro_oppa_uc0079_candidate_20260912.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": "PASS", "painted_glyphs": painted, "cave": report["cave"], "output": report["output"], "proofs": proofs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
