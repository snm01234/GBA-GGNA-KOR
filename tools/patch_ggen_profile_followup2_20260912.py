"""Fix leftover profile Japanese, series titles, and clipped empty-group text.

ss1: Amuro (前編) scroll selector 13 stayed on the JP pointer because Hangul-
painted slots made classify() treat it as Korean.
ss2: series table entry 20 (機動戦士ガンダム一年戦争外伝) was never in the
known-series batch. The Endless Waltz title encoded ASCII ':' as kana ね.
ss3: empty-group 해당 없음 is 5 glyphs; the panel only draws 4 tiles.
"""
from __future__ import annotations

import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    FONT12_RELOCATED,
    load_galmuri12,
    load_galmuri8,
    packed_12x12,
    packed_8x16,
    paint_8x16,
    slot_raw,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from ggen_advance_text_codec import (  # noqa: E402
    DICT_8X16_BASE,
    DICT_8X16_END,
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
    choose_free_8x16,
    hangul_chars,
    paint_12x12,
    recover_or_paint,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)

BATCH_ID = "profile-followup2-20260912"
IDENTITY_KEY = "profile_followup2_20260912_sha256"
BATCH_KEY = "profile_followup2_20260912"
OUT = ROOT / "outputs" / "20260912_allclear_profile_followup2"
WORK = OUT / "ggen_profile_followup2_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_profile_followup2.json"
CAVE_START = 0x01124200
CAVE_END = 0x01230000
ALLCLEAR = ROOT / "SD Gundam GGeneration Advance (Korean)_allclear.gba"

AMURO_OWNER = 0x001ACAD0
AMURO_KO = "격추 142기、격침 9척。연방"
SERIES20_OWNER = 0x001B4D38
SERIES20_ID = "GGA-TEXT-0018CEEF"
SERIES20_KO = "기동전사 건담 일년전쟁외전"
WALTZ_OWNER = 0x001B4D0C
WALTZ_ID = "GGA-TEXT-0018CE6F"
WALTZ_KO = "건담 W 엔드리스 왈츠"
EMPTY_OWNER = 0x00079F54
EMPTY_KO = "해당없음"
SERIES_CELLS = 14
EMPTY_CELLS = 4
BODY_CELLS = 18


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def fold_width(text: str) -> str:
    out = []
    for char in text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            char = chr(code - 0xFEE0)
        out.append(char)
    return "".join(out).replace("』", "」").replace("『", "「")


def payload_at(rom: bytes | bytearray, ptr: int) -> bytes:
    tokens, raw = read_tokens(bytes(rom), ptr - ROM_BASE)
    gate(raw.endswith(b"\x00"), f"payload missing NUL at {hex(ptr)}")
    return raw


def decode_text(rom: bytes | bytearray, ptr: int, dictionary, slot_to_char: dict[int, str]) -> str:
    tokens, _raw = read_tokens(bytes(rom), ptr - ROM_BASE)
    slots = expand_to_slots(tokens, dictionary)
    return "".join(slot_to_char.get(slot, f"<{slot:04X}>") for slot in slots)


def hangul_slot_map(rom: bytes | bytearray, *, mode: int) -> dict[int, str]:
    if mode == 8:
        relocated, stride, count, packer, font = (
            FONT8_RELOCATED,
            fontops.FONT_8X16_STRIDE,
            fontops.FONT_8X16_COUNT,
            packed_8x16,
            load_galmuri8(),
        )
    else:
        relocated, stride, count, packer, font = (
            FONT12_RELOCATED,
            fontops.FONT_12X12_STRIDE,
            fontops.FONT_12X12_COUNT,
            packed_12x12,
            load_galmuri12(),
        )
    by_glyph: dict[bytes, list[int]] = {}
    for slot in range(count):
        by_glyph.setdefault(slot_raw(rom, relocated, slot, stride), []).append(slot)
    out: dict[int, str] = {}
    for code in range(ord("가"), ord("힣") + 1):
        char = chr(code)
        try:
            packed = packer(char, font)
        except Exception:
            continue
        hits = by_glyph.get(packed, [])
        if len(hits) == 1:
            out[hits[0]] = char
    return out


def slot_to_char_map(verified: dict[str, int], recovered: dict[str, int], hangul_live: dict[int, str]) -> dict[int, str]:
    inv: dict[int, str] = {1: " "}
    for char, slot in verified.items():
        inv.setdefault(slot, char)
    for char, token in unified.SPECIAL_CHAR_TOKENS.items():
        if token >= 0xE000:
            inv.setdefault((token - 0xDF20) & 0xFFFF, char)
        else:
            inv.setdefault(token, char)
    inv.update(hangul_live)
    for char, slot in recovered.items():
        inv[slot] = char
    return inv


def place_payload(
    candidate: bytearray,
    owner: int,
    encoded: bytes,
    allowed: set[int],
    cursor: int,
) -> tuple[int, int, bool]:
    gate(encoded.endswith(b"\x00"), "encoded payload missing NUL")
    old_ptr = u32(candidate, owner)
    old_raw = payload_at(candidate, old_ptr)
    old_off = old_ptr - ROM_BASE
    # Keep original JP banks intact; only reuse an existing Korean cave payload.
    in_korean_cave = 0x09000000 <= old_ptr < 0x0A000000
    if in_korean_cave and len(encoded) <= len(old_raw):
        candidate[old_off : old_off + len(encoded)] = encoded
        if len(encoded) < len(old_raw):
            candidate[old_off + len(encoded) : old_off + len(old_raw)] = b"\x00" * (len(old_raw) - len(encoded))
        allowed.update(range(old_off, old_off + len(old_raw)))
        return old_ptr, cursor, True
    cursor = (cursor + 3) & ~3
    gate(cursor + len(encoded) <= CAVE_END, "followup2 cave overflow")
    candidate[cursor : cursor + len(encoded)] = encoded
    allowed.update(range(cursor, cursor + len(encoded)))
    new_ptr = ROM_BASE + cursor
    struct.pack_into("<I", candidate, owner, new_ptr)
    allowed.update(range(owner, owner + 4))
    return new_ptr, cursor + len(encoded), False


def recover_hangul(
    candidate: bytearray,
    japan: bytes,
    chars: set[str],
    *,
    mode: int,
    live: set[int],
    occupied: set[int],
    allowed: set[int],
    painted: list[dict[str, str]],
) -> dict[str, int]:
    recovered: dict[str, int] = {}
    if mode == 8:
        font = load_galmuri8()
        choose_free, paint, packed, relocated, stride, count, label = (
            choose_free_8x16,
            paint_8x16,
            packed_8x16,
            FONT8_RELOCATED,
            fontops.FONT_8X16_STRIDE,
            fontops.FONT_8X16_COUNT,
            "8x16",
        )
    else:
        font = load_galmuri12()
        choose_free, paint, packed, relocated, stride, count, label = (
            choose_free_12x12,
            paint_12x12,
            packed_12x12,
            FONT12_RELOCATED,
            fontops.FONT_12X12_STRIDE,
            fontops.FONT_12X12_COUNT,
            "12x12",
        )
    for char in sorted(chars):
        recovered[char] = recover_or_paint(
            candidate,
            japan,
            font,
            char,
            choose_free=choose_free,
            paint=paint,
            packed=packed,
            live=live,
            occupied=occupied,
            allowed=allowed,
            painted=painted,
            label=label,
            relocated=relocated,
            stride=stride,
            count=count,
        )
    return recovered


def patch_merged_row(row: dict[str, Any], ko: str) -> None:
    row["translation_ko"] = ko
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = "profile followup2: series title width/colon/pending JP"
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
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "followup2 cave is not empty")
    gate(len(AMURO_KO) <= BODY_CELLS, f"amuro width {len(AMURO_KO)}")
    gate(len(SERIES20_KO) <= SERIES_CELLS, f"series20 width {len(SERIES20_KO)}")
    gate(len(WALTZ_KO) <= SERIES_CELLS, f"waltz width {len(WALTZ_KO)}")
    gate(len(EMPTY_KO) == EMPTY_CELLS, f"empty width {len(EMPTY_KO)}")
    gate(u32(parent, AMURO_OWNER) == 0x081865FA, "amuro sel13 pointer drift")
    gate(u32(parent, SERIES20_OWNER) == 0x09052145, "series20 pointer drift")
    gate(u32(parent, WALTZ_OWNER) == 0x0905209E, "waltz pointer drift")
    gate(u32(parent, EMPTY_OWNER) == 0x091148CF, "empty pointer drift")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    series20 = by_id[SERIES20_ID]
    waltz = by_id[WALTZ_ID]
    gate(str(series20.get("translation_ko") or "") in ("", SERIES20_KO), "series20 unexpected KO")
    gate(str(waltz.get("translation_ko") or "") in ("건담 W: 엔드리스 왈츠", WALTZ_KO), "waltz unexpected KO")

    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered12 = recover_hangul(
        candidate,
        japan,
        hangul_chars(AMURO_KO),
        mode=12,
        live=live12,
        occupied=set(),
        allowed=allowed,
        painted=painted,
    )
    recovered8 = recover_hangul(
        candidate,
        japan,
        hangul_chars(SERIES20_KO) | hangul_chars(WALTZ_KO) | hangul_chars(EMPTY_KO),
        mode=8,
        live=live8,
        occupied=set(),
        allowed=allowed,
        painted=painted,
    )
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)

    jobs = [
        {"id": "amuro_sel13", "owner": AMURO_OWNER, "ko": AMURO_KO, "mode": 12, "recovered": recovered12, "verified": verified12},
        {"id": "series20", "owner": SERIES20_OWNER, "ko": SERIES20_KO, "mode": 8, "recovered": recovered8, "verified": verified8},
        {"id": "waltz", "owner": WALTZ_OWNER, "ko": WALTZ_KO, "mode": 8, "recovered": recovered8, "verified": verified8},
        {"id": "empty_group", "owner": EMPTY_OWNER, "ko": EMPTY_KO, "mode": 8, "recovered": recovered8, "verified": verified8},
    ]
    cursor = CAVE_START
    applied = []
    for job in jobs:
        encoded, missing = unified.encode_korean_text(
            job["ko"],
            job["recovered"],
            verified_charmap=job["verified"],
            strict_punctuation=True,
        )
        gate(encoded and not missing, f"encode failed {job['id']}: {missing}")
        new_ptr, cursor, in_place = place_payload(candidate, job["owner"], encoded, allowed, cursor)
        applied.append(
            {
                "id": job["id"],
                "owner": hex(job["owner"]),
                "ko": job["ko"],
                "mode": job["mode"],
                "old_ptr": hex(u32(parent, job["owner"])),
                "new_ptr": hex(new_ptr),
                "in_place": in_place,
                "encoded_hex": encoded.hex(),
                "cells": len(job["ko"]),
            }
        )

    hangul12 = hangul_slot_map(candidate, mode=12)
    hangul8 = hangul_slot_map(candidate, mode=8)
    map12 = slot_to_char_map(verified12, recovered12, hangul12)
    map8 = slot_to_char_map(verified8, recovered8, hangul8)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)
    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)
    for job, row in zip(jobs, applied):
        got = decode_text(
            candidate,
            u32(candidate, job["owner"]),
            dict12 if job["mode"] == 12 else dict8,
            map12 if job["mode"] == 12 else map8,
        )
        gate(fold_width(got) == fold_width(job["ko"]), f"roundtrip {job['id']}: {got!r} != {job['ko']!r}")
        row["live"] = got

    changed = {i for i, (a, b) in enumerate(zip(parent, candidate)) if a != b}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")

    patch_merged_row(series20, SERIES20_KO)
    patch_merged_row(waltz, WALTZ_KO)
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [SERIES20_ID, WALTZ_ID]})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": [SERIES20_ID, WALTZ_ID]}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_profile_followup2",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {
            "path": advance_relative(WORK),
            "size": len(candidate),
            "sha256": sha256(bytes(candidate)),
        },
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "jobs": applied,
        "translation_source": {
            "path": advance_relative(TRANSLATION_MERGED_JSON),
            "sha256": sha256(payload_json.encode("utf-8")),
            "changed_records": [SERIES20_ID, WALTZ_ID],
        },
        "verification": {
            "result": "PASS",
            "roundtrip_all_jobs": True,
            "unrelated_bytes_preserved": True,
            "series_field_cells": SERIES_CELLS,
            "empty_field_cells": EMPTY_CELLS,
            "amuro_owner_only": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "painted", "cave", "changed_bytes", "jobs", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
