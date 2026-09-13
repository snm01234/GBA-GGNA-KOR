"""Fix profile list names, reserved glyphs, Nu/Turn A, and proper nouns.

ss1: NT-001 short name became NT-0011 via a trailing-digit suffix append.
ss2: series ギレンの野望 was translated as the person 기렌 자비.
ss3: followup3 space-stripping produced 파이로럿 / 사이드 8.
ss4-ss6: unresolved 07E8/00EC/0126 encoded as ASCII hex.
ss7: slot 0x07DC is the 8x16 Nu glyph (sheet labelled ∀); 0x07E3 is Turn A ∀.
"""
from __future__ import annotations

import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
import patch_ggen_profile_followup3_20260912 as f3  # noqa: E402
from analyze_ggen_advance_ui_matrix_expansion import FIXED16_MATRIX, FIXED40_MATRIX  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT8_RELOCATED, slot_raw  # noqa: E402
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
    choose_free_8x16,
    hangul_chars,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import gate, sha256  # noqa: E402
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)

BATCH_ID = "profile-followup4-20260912"
IDENTITY_KEY = "profile_followup4_20260912_sha256"
BATCH_KEY = "profile_followup4_20260912"
OUT = ROOT / "outputs" / "20260912_allclear_profile_followup4"
WORK = OUT / "ggen_profile_followup4_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_profile_followup4.json"
CAVE_START = 0x01134748
CAVE_END = 0x01230000
WIDTH = 18
HEX_TAG = re.compile(r"<([0-9A-Fa-f]{4})>")
LEAD_ICON = re.compile(r"<(07F[8BCD]|0813)>", re.IGNORECASE)
NU_SLOT_8 = 0x07DC
TURN_A_SLOT_8 = 0x07E3
NU_SLOT_12 = 0x0143
TURN_A_SLOT_12 = 0x071B
BRACKET_L = 0x0134
BRACKET_R = 0x0135
UNIT_BASE = 0x001AFB5C
UNIT_STRIDE = 0x28
CHAR_BASE = 0x001ABF6C
CHAR_STRIDE = 0x10

NAME_JOBS = [
    {"owner": 0x001AC768, "ko": "NT-001", "mode": 8},
    {"owner": 0x001AC6DC, "ko": "라이조 캇슈", "mode": 8},
    {"owner": 0x001AC6E8, "ko": "라이조 캇슈", "mode": 8},
    {"owner": 0x001AC6BC, "ko": "유우 카지마1", "mode": 8},
    {"owner": 0x001AC6C8, "ko": "유우 카지마1", "mode": 8},
    {"owner": 0x001AC6CC, "ko": "유우 카지마<이벤트 후>", "mode": 8},
    {"owner": 0x001AC6D8, "ko": "유우 카지마2", "mode": 8},
    {"owner": 0x001B4D3C, "ko": "기렌의 야망", "mode": 8, "max_cells": 14},
    {"owner": 0x001B4D14, "ko": "∀건담", "mode": 8, "max_cells": 14},
]

PAGE_OVERRIDES = {
    ( "char", 7, 0): [
        "기동전사 건담의 주인공。",
        "사이드7에서 살던 민간인 소년",
        "이었지만, 지온군 습격 당시",
        "우연히 건담에 올라타 싸워",
        "그 파일럿이 되었다。",
    ],
}

LINE_REPLACES = [
    ("사이드 8", "사이드7"),
    ("파이로럿", "파일럿"),
    ("파이로트", "파일럿"),
    ("파이파일럿", "파일럿"),
    ("파일럿를", "파일럿을"),
    ("파일럿가", "파일럿이"),
    ("함장로", "함장으로"),
    ("여여성", "여성"),
    ("아아가마", "아가마"),
    ("참참가", "참가"),
    ("때턴에이 건담", "때 ∀건담"),
    ("턴에이 건담", "∀건담"),
    ("스트라이크루주", "스트라이크 루즈"),
    ("스트라이크 루주", "스트라이크 루즈"),
    ("말레렌", "마를렌"),
    ("유 카지마", "유우 카지마"),
    ("라이조 캐시", "라이조 캇슈"),
    ("네일 아가마", "넬 아가마"),
    ("하이곡", "하이고크"),
    ("빌고", "비르고"),
]


def cell_count(text: str) -> int:
    n = i = 0
    while i < len(text):
        match = HEX_TAG.match(text, i)
        if match:
            n += 1
            i = match.end()
        else:
            n += 1
            i += 1
    return n


def apply_line_replaces(text: str) -> str:
    out = text
    for old, new in LINE_REPLACES:
        out = out.replace(old, new)
    return out


def desired_unit_ko(row: dict[str, Any]) -> str | None:
    record_id = str(row.get("record_id") or "")
    if record_id == "GGA-TEXT-0018CF02":
        return "기렌의 야망"
    if record_id == "GGA-TEXT-0018CE8F":
        return "∀건담"
    category = str(row.get("semantic_category") or "")
    family = str(row.get("ui_family") or "")
    source = str(row.get("source_text") or "")
    current = str(row.get("translation_ko") or "")
    if category == "character_name" or "카지마" in current or "캐시" in current:
        changed = current.replace("유 카지마", "유우 카지마").replace("라이조 캐시", "라이조 캇슈")
        return changed if changed != current else None
    unitish = category in {"unit_name", "unit_name_alternate"} or family == "fixed40_secondary_display_text"
    if not unitish:
        return None
    icons = [match.group(0).upper().replace("0X", "") for match in LEAD_ICON.finditer(source)]
    icons = [tag if tag.startswith("<") else f"<{tag}>" for tag in icons]
    has_h = "<07FE>" in source.upper() or current.endswith("<07FE>")
    body = None
    if "ハイゴッグ" in source or current == "하이곡":
        body = "하이고크"
    elif "百式" in source and ("MB" in source or "00EC" in source or "MBL" in current):
        body = "백식 (MBL)"
    elif "ビルゴⅡ" in source:
        body = "비르고 II"
    elif "ビルゴⅠ" in source:
        body = "비르고 I"
    elif "ビーガン" in source or ("0126" in source and "비건" in current) or current == "헤비건":
        body = "헤비건"
    elif "07E8" in source or "ダッシュ" in source:
        body = "V대시 건담"
    elif "月光蝶" in source or "월광접" in current:
        body = "∀건담<월광접>"
    elif "∀99" in source or "턴에이99" in current:
        body = "∀건담<∀99>"
    elif "∀ガンダム" in source or "턴에이 건담" in current:
        body = "ν건담"
        if has_h:
            body += "<07FE>"
    elif "ルージュ" in source or "루주" in current:
        if source.endswith("1"):
            body = "스트라이크 루즈 1"
        elif source.endswith("2"):
            body = "스트라이크 루즈 2"
        elif "グレー" in source or "구레" in current:
            body = "스트라이크 루즈<그레이>"
        else:
            body = "스트라이크 루즈"
    elif "リリー" in source or "말레렌" in current:
        body = "릴리 마를렌"
    elif "ネェル" in source or "네일 아가마" in current:
        body = "넬 아가마"
    else:
        return None
    if body in {"헤비건", "V대시 건담"} and current == body and not any(tag in current for tag in ("07E8", "0126", "00EC")):
        # Production already has the Hangul; still rewrite when a leading icon must be kept
        # or when the live payload still contains an unresolved slot. Sheet-only no-op
        # is skipped later if owners already decode to the same text.
        pass
    rebuilt = "".join(icons) + body
    return rebuilt


def ensure_jp_glyph(
    candidate: bytearray,
    japan: bytes,
    preferred: int,
    live: set[int],
    occupied: set[int],
    allowed: set[int],
    painted: list[dict[str, str]],
    label: str,
) -> int:
    wanted = slot_raw(japan, fontops.FONT_8X16_BASE, preferred, fontops.FONT_8X16_STRIDE)
    current = slot_raw(candidate, FONT8_RELOCATED, preferred, fontops.FONT_8X16_STRIDE)
    if current == wanted:
        occupied.add(preferred)
        return preferred
    slot = choose_free_8x16(candidate, japan, live, occupied)
    start = FONT8_RELOCATED + slot * fontops.FONT_8X16_STRIDE
    candidate[start : start + fontops.FONT_8X16_STRIDE] = wanted
    allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
    occupied.add(slot)
    live.add(slot)
    painted.append({"font": "8x16-copy", "char": label, "from": hex(preferred), "slot": hex(slot)})
    return slot


def encode_mixed(text: str, recovered: dict[str, int], verified: dict[str, int], specials: dict[str, int]) -> bytes:
    out = bytearray()
    index = 0
    while index < len(text):
        match = HEX_TAG.match(text, index)
        if match:
            slot = int(match.group(1), 16)
            out.extend(unified.slot_to_token_bytes(slot) if slot > 0xDF else bytes((slot,)))
            index = match.end()
            continue
        char = text[index]
        if char in specials:
            slot = specials[char]
            out.extend(unified.slot_to_token_bytes(slot) if slot > 0xDF else bytes((slot,)))
            index += 1
            continue
        start = index
        while index < len(text) and not HEX_TAG.match(text, index) and text[index] not in specials:
            index += 1
        chunk = text[start:index]
        encoded, missing = unified.encode_korean_text(
            chunk, recovered, verified_charmap=verified, strict_punctuation=True
        )
        gate(encoded and not missing, f"encode failed {chunk!r} {missing}")
        out.extend(encoded[:-1])
    out.append(0)
    return bytes(out)


def patch_merged_row(row: dict[str, Any], ko: str) -> None:
    row["translation_ko"] = ko
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-12"
    row["translator_notes"] = "profile followup4: names / reserved glyphs / Nu vs Turn A / proper nouns"
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    import analyze_ggen_advance_pending_decode as decode

    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "followup4 cave is not empty")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    jp12 = decode.merge_maps([decode.DEFAULT_MAP12], apply_kana=True)
    jp_dict12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)

    unit_jobs: list[dict[str, Any]] = []
    sheet_updates: dict[str, str] = {}
    for row in merged["records"]:
        wanted = desired_unit_ko(row)
        if not wanted:
            continue
        owners = list(owner_offsets(row))
        if not owners:
            continue
        sheet_updates[str(row["record_id"])] = wanted
        unit_jobs.append({"record_id": row["record_id"], "owners": owners, "ko": wanted, "mode": 8})

    extra_names = {job["ko"] for job in NAME_JOBS}
    extra_names.update(wanted for wanted in sheet_updates.values())
    extra_names.update(line for lines in PAGE_OVERRIDES.values() for line in lines)

    hangul8 = {char for text in extra_names for char in hangul_chars(text)}
    hangul12 = set()

    matrix_jobs: list[dict[str, Any]] = []
    override_owners: set[int] = set()
    for (kind, index, start), lines in PAGE_OVERRIDES.items():
        spec = FIXED16_MATRIX if kind == "char" else FIXED40_MATRIX
        base = spec["base_file"] + index * spec["stride"]
        for offset, line in enumerate(lines):
            owner = base + (start + offset) * 4
            override_owners.add(owner)
            hangul12.update(hangul_chars(line))
            matrix_jobs.append({"kind": kind, "index": index, "selector": start + offset, "owner": owner, "ko": line, "mode": 12})

    hangul8_map = f2.hangul_slot_map(parent, mode=8)
    hangul12_map = f2.hangul_slot_map(parent, mode=12)
    map12_now = f2.slot_to_char_map(verified12, {}, hangul12_map)
    dict12_now = load_dictionary(parent, DICT_12X12_BASE, DICT_12X12_END)
    for kind, spec in (("char", FIXED16_MATRIX), ("unit", FIXED40_MATRIX)):
        for index in range(spec["count"]):
            base = spec["base_file"] + index * spec["stride"]
            for sel in range(spec["selector_count"]):
                owner = base + sel * 4
                if owner in override_owners:
                    continue
                if not f3.jp_nonempty(japan, jp_dict12, jp12, owner):
                    continue
                current = f2.decode_text(parent, f2.u32(parent, owner), dict12_now, map12_now)
                if not current:
                    continue
                updated = apply_line_replaces(current)
                if updated == current:
                    continue
                gate(cell_count(updated) <= WIDTH, f"line overflow {kind}{index}s{sel}: {updated!r}")
                hangul12.update(hangul_chars(updated))
                matrix_jobs.append({"kind": kind, "index": index, "selector": sel, "owner": owner, "ko": updated, "mode": 12})

    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied8: set[int] = set()
    occupied12: set[int] = set()
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    recovered8 = f2.recover_hangul(
        candidate, japan, hangul8, mode=8, live=live8, occupied=occupied8, allowed=allowed, painted=painted
    )
    recovered8["ν"] = NU_SLOT_8
    recovered8["∀"] = TURN_A_SLOT_8
    recovered12["ν"] = NU_SLOT_12
    recovered12["∀"] = TURN_A_SLOT_12
    latin_slots = {
        "M": ensure_jp_glyph(candidate, japan, 0x000B, live8, occupied8, allowed, painted, "M"),
        "B": ensure_jp_glyph(candidate, japan, 0x0004, live8, occupied8, allowed, painted, "B"),
        "L": ensure_jp_glyph(candidate, japan, 0x00EC, live8, occupied8, allowed, painted, "L"),
        "V": ensure_jp_glyph(candidate, japan, 0x00F2, live8, occupied8, allowed, painted, "V"),
        "I": ensure_jp_glyph(candidate, japan, 0x00EA, live8, occupied8, allowed, painted, "I"),
    }
    specials8 = {
        "ν": NU_SLOT_8,
        "∀": TURN_A_SLOT_8,
        "<": BRACKET_L,
        ">": BRACKET_R,
        "(": BRACKET_L,
        ")": BRACKET_R,
        **latin_slots,
    }
    specials12 = {"ν": NU_SLOT_12, "∀": TURN_A_SLOT_12}

    cursor = CAVE_START
    applied: list[dict[str, Any]] = []

    def place(owner: int, encoded: bytes, meta: dict[str, Any]) -> None:
        nonlocal cursor
        new_ptr, cursor = f3.cave_payload(candidate, owner, encoded, allowed, cursor)
        applied.append({**meta, "owner": hex(owner), "new_ptr": hex(new_ptr), "old_ptr": hex(f2.u32(parent, owner))})

    for job in NAME_JOBS:
        encoded = encode_mixed(job["ko"], recovered8, verified8, specials8)
        if job.get("max_cells"):
            slots = expand_to_slots(read_tokens(encoded, 0)[0], load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END))
            gate(len(slots) <= int(job["max_cells"]), f"series too long {job['ko']} {len(slots)}")
        place(job["owner"], encoded, {"id": "name", "ko": job["ko"], "mode": 8})

    seen_unit_owners: set[int] = set()
    for job in unit_jobs:
        encoded = encode_mixed(job["ko"], recovered8, verified8, specials8)
        for owner in job["owners"]:
            if owner in seen_unit_owners:
                continue
            seen_unit_owners.add(owner)
            place(owner, encoded, {"id": job["record_id"], "ko": job["ko"], "mode": 8})

    for job in matrix_jobs:
        encoded = encode_mixed(job["ko"], recovered12, verified12, specials12)
        slots = expand_to_slots(read_tokens(encoded, 0)[0], load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END))
        gate(1 <= len(slots) <= WIDTH, f"12x12 width {len(slots)} {job['ko']}")
        place(job["owner"], encoded, {"id": f"{job['kind']}{job['index']}s{job['selector']}", "ko": job["ko"], "mode": 12})

    hangul8_live = f2.hangul_slot_map(candidate, mode=8)
    hangul12_live = f2.hangul_slot_map(candidate, mode=12)
    map8 = f2.slot_to_char_map(verified8, recovered8, hangul8_live)
    map8[NU_SLOT_8] = "ν"
    map8[TURN_A_SLOT_8] = "∀"
    map12 = f2.slot_to_char_map(verified12, recovered12, hangul12_live)
    map12[NU_SLOT_12] = "ν"
    map12[TURN_A_SLOT_12] = "∀"
    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)

    def dec8(owner: int) -> str:
        return f2.decode_text(candidate, f2.u32(candidate, owner), dict8, map8)

    def dec12(owner: int) -> str:
        return f2.decode_text(candidate, f2.u32(candidate, owner), dict12, map12)

    def slots8(owner: int) -> list[int]:
        return expand_to_slots(read_tokens(bytes(candidate), f2.u32(candidate, owner) - ROM_BASE)[0], dict8)

    nt = dec8(0x001AC768)
    gate(nt == "NT-001", f"NT short {nt}")
    gate(dec8(0x001AC75C) == "NT-001", "NT primary drift")
    series_g = dec8(0x001B4D3C)
    gate(series_g == "기렌의 야망", f"series ghiren {series_g}")
    series_t = dec8(0x001B4D14)
    gate(series_t == "∀건담", f"series turna {series_t}")
    gate("파이" not in dec12(0x001ACAA8) and "파일럿" in dec12(0x001ACAAC), "amuro pilot line")
    gate("사이드7" in dec12(0x001ACAA0) or "사이드7" in dec12(0x001ACA9C), "amuro side7")
    gate(dec8(0x001AC6DC) == "라이조 캇슈", "raizo")
    gate(dec8(0x001AC6BC).startswith("유우 카지마"), "yu kazima")
    hygog = dec8(UNIT_BASE + 16 * UNIT_STRIDE)
    gate(hygog == "하이고크", f"hygog primary {hygog}")
    vdash = dec8(UNIT_BASE + 111 * UNIT_STRIDE + 0x24)
    gate(vdash == "V대시 건담", f"vdash {vdash}")
    gate(0x07E8 not in slots8(UNIT_BASE + 111 * UNIT_STRIDE + 0x24), "07E8 still live")
    heavy = dec8(UNIT_BASE + 105 * UNIT_STRIDE + 0x24)
    gate(heavy == "헤비건", f"heavy {heavy}")
    gate(0x0126 not in slots8(UNIT_BASE + 105 * UNIT_STRIDE + 0x24), "0126 still live")
    mbl = dec8(UNIT_BASE + 82 * UNIT_STRIDE)
    gate("MBL" in mbl and "00EC" not in mbl and "れ" not in mbl, f"mbl primary {mbl}")
    mbl_s = dec8(UNIT_BASE + 82 * UNIT_STRIDE + 0x24)
    gate("MBL" in mbl_s and "00EC" not in mbl_s, f"mbl secondary {mbl_s}")
    nu_s = slots8(UNIT_BASE + 128 * UNIT_STRIDE + 0x24)
    gate(NU_SLOT_8 in nu_s, f"nu secondary slots {nu_s}")
    gate("턴에이" not in dec8(UNIT_BASE + 128 * UNIT_STRIDE + 0x24), "nu still hangul turna")
    nu_h = slots8(UNIT_BASE + 129 * UNIT_STRIDE + 0x24)
    gate(NU_SLOT_8 in nu_h and 0x07FE in nu_h, f"nu H slots {nu_h}")
    turna = slots8(UNIT_BASE + 142 * UNIT_STRIDE + 0x24)
    gate(TURN_A_SLOT_8 in turna, f"turna99 slots {turna}")
    gate("턴에이" not in dec8(UNIT_BASE + 142 * UNIT_STRIDE + 0x24), "turna99 hangul")
    virgo = dec8(UNIT_BASE + 93 * UNIT_STRIDE)
    gate(virgo == "비르고 I", f"virgo {virgo}")
    virgo2 = dec8(UNIT_BASE + 113 * UNIT_STRIDE)
    gate(virgo2 == "비르고 II", f"virgo2 {virgo2}")
    rouge = dec8(UNIT_BASE + 147 * UNIT_STRIDE)
    gate("루즈" in rouge and "루주" not in rouge, f"rouge {rouge}")
    marlene = dec8(UNIT_BASE + 163 * UNIT_STRIDE)
    gate(marlene == "릴리 마를렌", f"marlene {marlene}")
    nahel = dec8(UNIT_BASE + 168 * UNIT_STRIDE)
    gate(nahel == "넬 아가마", f"nahel {nahel}")
    gate("기렌 자비" not in series_g, "series still person name")

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")

    changed_ids: list[str] = []
    owner_to_id = {}
    for row in merged["records"]:
        for owner in owner_offsets(row):
            owner_to_id.setdefault(owner, []).append(str(row["record_id"]))
    for record_id, ko in sheet_updates.items():
        if record_id in by_id:
            patch_merged_row(by_id[record_id], ko)
            changed_ids.append(record_id)
    for job in NAME_JOBS:
        for record_id in owner_to_id.get(job["owner"], []):
            if record_id in by_id and record_id not in sheet_updates:
                patch_merged_row(by_id[record_id], job["ko"])
                changed_ids.append(record_id)
    for job in matrix_jobs:
        for record_id in owner_to_id.get(job["owner"], []):
            if record_id in by_id:
                patch_merged_row(by_id[record_id], job["ko"])
                changed_ids.append(record_id)

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": changed_ids})
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    summary["translation_overlay_identity_sha256"] = new_identity
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": sorted(set(changed_ids))}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_profile_followup4",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "name_jobs": len(NAME_JOBS),
        "unit_jobs": len(unit_jobs),
        "matrix_jobs": len(matrix_jobs),
        "proofs": {
            "nt_short": nt,
            "series_ghiren": series_g,
            "series_turn_a": series_t,
            "amuro0": dec12(0x001ACA9C),
            "amuro4": dec12(0x001ACAAC),
            "vdash": vdash,
            "heavy": heavy,
            "mbl": mbl,
            "mbl_secondary": mbl_s,
            "nu": dec8(UNIT_BASE + 128 * UNIT_STRIDE + 0x24),
            "turna99": dec8(UNIT_BASE + 142 * UNIT_STRIDE + 0x24),
            "hygog": hygog,
            "raizo": dec8(0x001AC6DC),
            "yu": dec8(0x001AC6BC),
        },
        "verification": {
            "result": "PASS",
            "unrelated_bytes_preserved": True,
            "nt_001_short": True,
            "ghiren_ambition_series": True,
            "amuro_pilot_wrap": True,
            "reserved_glyphs_not_ascii": True,
            "nu_slot_07dc": True,
            "turn_a_slot_07e3": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "painted", "cave", "changed_bytes", "name_jobs", "unit_jobs", "matrix_jobs", "proofs", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
