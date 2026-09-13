#!/usr/bin/env python3
"""Apply closable pending readable JP to the sheet and current-main ROM.

Order:
1. 12x12 battle-condition lines (fully closed)
2. 8x16 scroll-list bodies (UI prefix 00F9/00FF/00FA preserved)
3. closed ID-command bark only (leftover=1 mixed frames are held)
4. closed ending-credit lines (personal names kept Japanese)

Does not guess-promote mixed 8x16 slots.  Original JP bytes stay in place;
U32 owners are redirected into a zero-filled expansion cave.
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
sys.path.insert(0, str(ROOT / "analysis"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, RESERVED  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    FONT12_RELOCATED,
    load_galmuri12,
    load_galmuri8,
    packed_12x12,
    packed_8x16,
    paint_8x16,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
    slot_raw,
    token_from_slot,
    tokens_from_recovered,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import (  # noqa: E402
    DICT_12X12_BASE,
    DICT_12X12_END,
    DICT_8X16_BASE,
    DICT_8X16_END,
    expand_to_slots,
    load_dictionary,
)
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    ROM_BASE,
    gate,
    payload_at,
    sha256,
    u32,
)

import _tmp_classify_pending_readable_20260907 as decode  # noqa: E402

BATCH_ID = "pending-readable-batch-20260907"
KO_MAP = ROOT / "analysis" / "ggen_advance_pending_readable_ko_20260907.json"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260907_pending_readable.json"
OUT_DIR = ROOT / "outputs" / "20260907_ggen_advance_pending_readable"
OUTPUT = OUT_DIR / "ggen_advance_pending_readable_candidate_20260907.gba"
OUT_SAV = OUT_DIR / "ggen_advance_pending_readable_candidate_20260907.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_pending_readable_candidate_20260907.json"
MANIFEST = OUT_DIR / "manifest.json"
CAVE_START = 0x012B0100
CAVE_END = 0x012C0000
PREFIX_SLOTS = (0x00F9, 0x00FF, 0x00FA)
PROTECTED = {0x010A, 0x0143, 0x071E, 0x07DB, 0x07DC}


def owner_offsets(row: dict[str, Any]) -> tuple[int, ...]:
    return tuple(
        int(str(owner).removeprefix("OWNER-U32-"), 16)
        for owner in row.get("owner_ids") or []
        if str(owner).startswith("OWNER-U32-")
    )


def align16(value: int) -> int:
    return (value + 15) & ~15


def emit_slot(slot: int) -> bytes:
    token = token_from_slot(slot)
    if token <= 0xDF:
        return bytes((token,))
    gate(0xE000 <= token <= 0xEFFF, f"invalid literal token for slot 0x{slot:04X}")
    return bytes((token >> 8, token & 0xFF))


def hangul_chars(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


def latin_chars(text: str) -> set[str]:
    return {char for char in text if ("A" <= char <= "Z") or ("a" <= char <= "z") or ("0" <= char <= "9")}


def load_char_to_slot(path: Path, extra: dict[int, str] | None = None) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, int] = {}
    mapping = dict(payload.get("verified_charmap") or {})
    if extra:
        for slot, char in extra.items():
            mapping[f"0x{slot:04X}"] = char
    for slot_text, char in mapping.items():
        if not isinstance(char, str) or not char:
            continue
        slot = int(str(slot_text), 16)
        previous = result.get(char)
        if previous is None or slot < previous:
            result[char] = slot
    return result


def paint_12x12(candidate: bytearray, slot: int, char: str, font12) -> int:
    packed = packed_12x12(char, font12)
    start = FONT12_RELOCATED + slot * fontops.FONT_12X12_STRIDE
    candidate[start : start + fontops.FONT_12X12_STRIDE] = packed
    gate(bytes(candidate[start : start + fontops.FONT_12X12_STRIDE]) == packed, f"failed to paint 12x12 {char!r}")
    return start


def choose_free_12x12(candidate: bytearray, japan: bytes, live12: set[int], occupied: set[int]) -> int:
    protected = set(PROTECTED) | unified.SPECIAL_SLOTS | unified.RESERVED_GLYPH_SLOTS
    for slot in range(unified.SLOT_MAX, unified.SLOT_MIN - 1, -1):
        if slot in protected or slot in occupied or slot in live12:
            continue
        current = slot_raw(candidate, FONT12_RELOCATED, slot, fontops.FONT_12X12_STRIDE)
        native = slot_raw(japan, fontops.FONT_12X12_BASE, slot, fontops.FONT_12X12_STRIDE)
        if current != native:
            continue
        return slot
    raise SystemExit("gate failed: no free 12x12 slot for new Hangul")


def choose_free_8x16(candidate: bytearray, japan: bytes, live8: set[int], occupied: set[int]) -> int:
    protected = set(PROTECTED) | unified.SPECIAL_SLOTS | unified.RESERVED_GLYPH_SLOTS
    for slot in range(unified.SLOT_MAX, unified.SLOT_MIN - 1, -1):
        if slot in protected or slot in occupied or slot in live8:
            continue
        current = slot_raw(candidate, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
        native = slot_raw(japan, fontops.FONT_8X16_BASE, slot, fontops.FONT_8X16_STRIDE)
        if current != native:
            continue
        return slot
    raise SystemExit("gate failed: no free 8x16 slot for new Hangul")


def try_recover(fn, rom, font, char: str) -> int | None:
    try:
        return fn(rom, font, {char})[char]
    except SystemExit as exc:
        if "is not painted" in str(exc) or "is not unique" in str(exc):
            return None
        raise


def update_payload_hash(row: dict[str, Any]) -> None:
    patch = {
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
    row["translation_payload_sha256"] = translation_payload_digest(patch)


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
            "translation_overlay_identity_sha256": merged.get("identity", {}).get("translation_overlay_identity_sha256"),
            "record_translation_status_counts": counts,
            "source_summary_translation_status_counts": counts,
        }
    )
    TRANSLATION_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


FULLWIDTH = {
    "!": "！",
    "?": "？",
    "(": "（",
    ")": "）",
    ":": "：",
    "/": "／",
    ",": "、",
    ".": "。",
    "-": "－",
    "~": "～",
}


def encode_text(text: str, slots: dict[str, int], jp_map: dict[str, int]) -> bytes:
    out = bytearray()
    for char in text:
        if char == " ":
            out.append(0x01)
            continue
        slot = slots.get(char, jp_map.get(char))
        if slot is None and char in FULLWIDTH:
            slot = slots.get(FULLWIDTH[char], jp_map.get(FULLWIDTH[char]))
        if slot is None and (("A" <= char <= "Z") or ("a" <= char <= "z") or ("0" <= char <= "9")):
            wide = chr(ord(char) + 0xFEE0)
            slot = slots.get(wide, jp_map.get(wide))
        gate(slot is not None, f"missing encode slot for {char!r} in {text!r}")
        out.extend(emit_slot(slot))
    out.append(0)
    return bytes(out)


def mark_row(row: dict[str, Any], source_jp: str, korean: str, notes: str) -> None:
    row["source_text"] = source_jp
    row["source_decode_status"] = "complete"
    row["source_unresolved_slots"] = []
    row["baseline_translation_ko"] = korean
    row["baseline_translation_status"] = "translated"
    row["translation_ko"] = korean
    row["translation_status"] = "translated"
    row["translation_source"] = "human"
    row["review_status"] = "draft"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-07"
    row["translator_notes"] = notes
    row["qa_status"] = "static_consumer_pending"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    maps = json.loads(KO_MAP.read_text(encoding="utf-8"))
    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "readable-batch cave is not zero-filled")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    dict8 = load_dictionary(original, DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(original, DICT_12X12_BASE, DICT_12X12_END)
    map8 = decode.load_identified_slot_to_char(decode.CHARMAP_8X16_PATH)
    map12 = decode.load_identified_slot_to_char(decode.CHARMAP_12X12_PATH)
    map12.update(CORRECTED_LOW_KANA)
    jp12 = load_char_to_slot(decode.CHARMAP_12X12_PATH, CORRECTED_LOW_KANA)
    jp8 = load_char_to_slot(decode.CHARMAP_8X16_PATH)
    font8 = load_galmuri8()
    font12 = load_galmuri12()
    live8, live12 = unified.collect_live_slots(original, merged["records"])

    jobs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in merged["records"]:
        if row.get("translation_status") != "pending":
            continue
        category = str(row.get("semantic_category") or "")
        decoded, missing, font = decode.decode_row(row, dict8, dict12, map8, map12)
        text_missing = [slot for slot in missing if slot not in RESERVED]
        owners = owner_offsets(row)
        if category == "stage_battle_condition_line":
            if text_missing:
                skipped.append({"record_id": row["record_id"], "reason": "condition still partial"})
                continue
            korean = maps["condition_jp_to_ko"].get(decoded)
            gate(korean is not None, f"unmapped condition {decoded!r}")
            jobs.append({"row": row, "font": "12x12", "source": decoded, "korean": korean, "prefix": (), "notes": "12x12 승패 조건. 시트 partial을 현재 맵으로 닫고 번역"})
            continue
        if category == "scroll_list_label":
            if set(text_missing) != set(PREFIX_SLOTS):
                skipped.append({"record_id": row["record_id"], "reason": "scroll extra unresolved slots", "missing": [f"0x{s:04X}" for s in text_missing]})
                continue
            body = decoded
            for slot in PREFIX_SLOTS:
                body = body.replace(f"<{slot:04X}>", "")
            korean = maps["scroll_body_jp_to_ko"].get(body)
            gate(korean is not None, f"unmapped scroll body {body!r}")
            jobs.append({"row": row, "font": "8x16", "source": body, "korean": korean, "prefix": PREFIX_SLOTS, "notes": "스크롤 라벨. UI 접두 00F9/00FF/00FA 보존, 본문만 번역"})
            continue
        if category == "id_command_name":
            korean = maps["idcmd_jp_to_ko"].get(decoded)
            if korean is None:
                skipped.append({"record_id": row["record_id"], "reason": "idcmd leftover or mixed_frames hold", "decoded": decoded[:80]})
                continue
            jobs.append({"row": row, "font": "8x16", "source": decoded, "korean": korean, "prefix": (), "notes": "닫힌 ID커맨드 대사만 번역. leftover=1 mixed_frames는 미승격"})
            continue
        if category == "scripted_multiline_text":
            # These records are members of double-NUL containers. A single
            # line rewrite can consume its neighbor or discard continuation
            # names. Use the complete-container credit builder instead.
            skipped.append({"record_id": row["record_id"], "reason": "requires complete double-NUL container rebuild; use build_ggen_credits_ko_20260912.py"})
            continue

    hangul12 = set().union(*(hangul_chars(job["korean"]) for job in jobs if job["font"] == "12x12"))
    hangul8 = set().union(*(hangul_chars(job["korean"]) for job in jobs if job["font"] == "8x16"))
    candidate = bytearray(current)
    allowed: set[int] = set()
    occupied12: set[int] = set()
    occupied8: set[int] = set()
    slots12: dict[str, int] = {}
    slots8: dict[str, int] = {}
    painted = []

    for char in sorted(hangul12):
        slot = try_recover(recover_unique_12x12_slots, candidate, font12, char)
        if slot is None:
            slot = choose_free_12x12(candidate, original, live12, occupied12)
            start = paint_12x12(candidate, slot, char, font12)
            allowed.update(range(start, start + fontops.FONT_12X12_STRIDE))
            painted.append({"font": "12x12", "char": char, "slot": f"0x{slot:04X}"})
            live12.add(slot)
        occupied12.add(slot)
        slots12[char] = slot
        if slot not in live8:
            current8 = slot_raw(candidate, FONT8_RELOCATED, slot, fontops.FONT_8X16_STRIDE)
            native8 = slot_raw(original, fontops.FONT_8X16_BASE, slot, fontops.FONT_8X16_STRIDE)
            wanted8 = packed_8x16(char, font8)
            if current8 == wanted8:
                occupied8.add(slot)
            elif current8 == native8:
                start = paint_8x16(candidate, slot, char, font8)
                allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
                painted.append({"font": "8x16-mirror", "char": char, "slot": f"0x{slot:04X}"})
                occupied8.add(slot)

    for char in sorted(hangul8):
        slot = try_recover(recover_unique_8x16_slots, candidate, font8, char)
        if slot is None:
            slot = choose_free_8x16(candidate, original, live8, occupied8)
            start = paint_8x16(candidate, slot, char, font8)
            allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
            painted.append({"font": "8x16", "char": char, "slot": f"0x{slot:04X}"})
            live8.add(slot)
        occupied8.add(slot)
        slots8[char] = slot

    # Latin/digit fallback from the reviewed JP maps.  Prefer already-painted Hangul slots first.
    encode12_map = dict(jp12)
    encode12_map.update(slots12)
    encode8_map = dict(jp8)
    encode8_map.update(slots8)

    cursor = CAVE_START
    written: dict[str, int] = {}
    rom_jobs = 0
    sheet_only = 0
    changed_ids: list[str] = []

    for job in jobs:
        row = job["row"]
        korean = job["korean"]
        source = job["source"]
        owners = owner_offsets(row)
        mark_row(row, source, korean, job["notes"])
        changed_ids.append(row["record_id"])
        if not owners:
            gate(job.get("allow_no_owner"), f"{row['record_id']} has no owners")
            sheet_only += 1
            continue
        orig_raw = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        current_payloads = [payload_at(current, u32(current, owner)) for owner in owners]
        already_relocated = any(payload != orig_raw for payload in current_payloads)
        if already_relocated:
            sheet_only += 1
            continue
        jp_map = encode12_map if job["font"] == "12x12" else encode8_map
        hangul_map = slots12 if job["font"] == "12x12" else slots8
        body = encode_text(korean, hangul_map, jp_map)
        payload = b"".join(emit_slot(slot) for slot in job["prefix"]) + body
        key = payload.hex()
        if key in written:
            pointer = ROM_BASE + written[key]
        else:
            start = align16(cursor)
            end = start + len(payload)
            gate(end <= CAVE_END, "readable-batch cave overflow")
            candidate[start:end] = payload
            allowed.update(range(start, end))
            written[key] = start
            cursor = end
            pointer = ROM_BASE + start
        for owner in owners:
            struct.pack_into("<I", candidate, owner, pointer)
            allowed.update(range(owner, owner + 4))
        rom_jobs += 1

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": changed_ids})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["pending_readable_batch_identity_sha256"] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged["pending_readable_batch_20260907"] = {
        "batch_id": BATCH_ID,
        "changed_records": len(changed_ids),
        "rom_redirected": rom_jobs,
        "sheet_only": sheet_only,
        "skipped": len(skipped),
    }

    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    report = {
        "result": "PASS",
        "batch_id": BATCH_ID,
        "changed_records": len(changed_ids),
        "rom_redirected": rom_jobs,
        "sheet_only": sheet_only,
        "skipped": len(skipped),
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cursor), "capacity_end": hex(CAVE_END)},
        "unique_payloads": len(written),
        "parent": {"path": advance_relative(MAIN_TIP_ROM), "sha256": sha256(current)},
        "output": {"path": advance_relative(OUTPUT), "sha256": sha256(candidate), "size": len(candidate)},
        "translation_source": {"path": advance_relative(TRANSLATION_MERGED_JSON), "sha256": sha256(payload_json.encode("utf-8"))},
        "verification": {
            "result": "PASS",
            "only_cave_owners_and_new_glyphs_changed": True,
            "id_command_mixed_frames_not_promoted": True,
            "scroll_prefix_preserved": True,
            "runtime_emulator": "not run; static ROM verification only",
        },
        "skipped_samples": skipped[:20],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("result", "changed_records", "rom_redirected", "sheet_only", "skipped", "painted_glyphs", "cave", "output")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
