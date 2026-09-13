#!/usr/bin/env python3
"""Fit ID-command list names/effects to the measured 8x16 columns.

Yellow 12x12 descriptions are already <=17 (22.142).  The same ID-command
screen still overflows two other widgets:

- names draw at x=8 until the SP cost at x=136 -> 16 cells of 8x16
- effect summaries draw at x=160 until the screen edge 240 -> 10 cells

ss6 clips ``자신 HP 완전 회복`` (11) to drop ``회복``.  Long catchphrase
names (17-25) run into the SP column.  This pass shortens those 8x16
NUL streams in place and pads with NULs; original JP bytes stay put.
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

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT8_RELOCATED,
    FONT12_RELOCATED,
    load_galmuri8,
    load_galmuri12,
    packed_12x12,
    paint_8x16,
    recover_unique_12x12_slots,
    recover_unique_8x16_slots,
    slot_raw,
    verify_payload_painted,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import (  # noqa: E402
    live_char_tokens,
    read_tokens,
    write_padded,
)
from patch_ggen_advance_idcmd_ecm_mishudeuk_20260905 import (  # noqa: E402
    hangul_chars,
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
    verified_from_charmap,
    verify_hangul_12x12,
    verify_mixed_8x16,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    ROM_BASE,
    gate,
    payload_at,
    sha256,
    u32,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import payload_until_nul  # noqa: E402

BATCH_ID = "idcmd-list-name-effect-fit-20260909"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260909_idcmd_list_fit.json"
OUT_DIR = ROOT / "outputs" / "20260909_ggen_advance_idcmd_list_fit"
OUTPUT = OUT_DIR / "ggen_advance_idcmd_list_fit_candidate_20260909.gba"
OUT_SAV = OUT_DIR / "ggen_advance_idcmd_list_fit_candidate_20260909.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_idcmd_list_fit_candidate_20260909.json"
MANIFEST = OUT_DIR / "manifest.json"
MAP_BANK = (0x00F00000, 0x00FC0000)
NAME_CAP = 16
EFFECT_CAP = 10
DESC_CAP = 17
CHARMAP_8 = ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json"

# record_id -> shortened Korean.  Lengths are gated below.
NAME_JOBS: dict[str, dict[str, str]] = {
    "GGA-TEXT-0017CE35": {
        "old": "사람의 목숨을 소중히 여기지 않는 사람과는……",
        "new": "목숨 여기지 않는 사람과는……",
        "notes": "ID커맨드 목록명 16칸. 사람의/을/소중히 축약",
    },
    "GGA-TEXT-0017C580": {
        "old": "사람의 삶은 무엇을 이뤘느냐로 정해진다!",
        "new": "삶은 이뤘느냐로 정해진다!",
        "notes": "ID커맨드 목록명 16칸. 사람의/무엇을 축약",
    },
    "GGA-TEXT-0017C9F1": {
        "old": "나 같은 믿음직하지 못한 함장에게……",
        "new": "믿음직 못한 함장에게……",
        "notes": "ID커맨드 목록명 16칸. 나 같은/하지 축약",
    },
    "GGA-TEXT-0017CDFE": {
        "old": "싸움의 역사를 되풀이하지 않겠습니다!",
        "new": "싸움 역사 되풀이 않겠습니다!",
        "notes": "ID커맨드 목록명 16칸. 의/를/하지 축약",
    },
    "GGA-TEXT-0017B6F2": {
        "old": "전쟁으로 세상을 바꿀 수 있다니……",
        "new": "전쟁으로 세상 바꿀수 있다니…",
        "notes": "ID커맨드 목록명 16칸. 을/공백/줄임표 축약",
    },
    "GGA-TEXT-0017BB22": {
        "old": "한번 보고 싶다고 생각하고 있었다…",
        "new": "한번 보고 싶다고 생각하고…",
        "notes": "ID커맨드 목록명 16칸. 있었다 축약",
    },
    "GGA-TEXT-0017C0EE": {
        "old": "죽는 것도 사는 것도 둘이 함께다!",
        "new": "죽는 것도 사는 것도 함께다!",
        "notes": "ID커맨드 목록명 16칸. 둘이 축약",
    },
    "GGA-TEXT-0017C427": {
        "old": "미네바를 위해서라도 질 것 같으냐!",
        "new": "미네바 위해 질 것 같으냐!",
        "notes": "ID커맨드 목록명 16칸. 위해서라도 축약",
    },
    "GGA-TEXT-0017B48F": {
        "old": "기체에 손을 대게 할 수는 없어！",
        "new": "기체에 손 대게 할 수 없어！",
        "notes": "ID커맨드 목록명 16칸. 손을/수는 축약",
    },
    "GGA-TEXT-0017BAFE": {
        "old": "봐라! 내 아들 그로무린의 힘을!",
        "new": "봐라! 아들 그로무린의 힘!",
        "notes": "ID커맨드 목록명 16칸. 내/를 축약",
    },
    "GGA-TEXT-0017BEFC": {
        "old": "싸움이란 두 수, 세 수 앞을……",
        "new": "싸움이란 두수, 세 수 앞을…",
        "notes": "ID커맨드 목록명 16칸. 두 수→두수, 줄임표 1칸",
    },
    "GGA-TEXT-0017BF82": {
        "old": "세계가 우리를 말살하려 하니까……",
        "new": "세계가 우리를 말살하려……",
        "notes": "ID커맨드 목록명 16칸. 하니까 축약",
    },
    "GGA-TEXT-0017C5D9": {
        "old": "……내가 내가 아니게 되어 버려！",
        "new": "내가 내가 아니게 되어 버려！",
        "notes": "ID커맨드 목록명 16칸. 앞 줄임표 축약",
    },
    "GGA-TEXT-0017C8DC": {
        "old": "내 체면이 완전히 구겨진 거라고！",
        "new": "내 체면이 구겨진 거라고！",
        "notes": "ID커맨드 목록명 16칸. 완전히 축약",
    },
    "GGA-TEXT-0017C969": {
        "old": "우주에는 마음이 가득 차 있어……",
        "new": "우주에는 마음 가득 있어……",
        "notes": "ID커맨드 목록명 16칸. 차 축약",
    },
    "GGA-TEXT-0017CBDA": {
        "old": "우주에는 마음이 가득 차 있다……",
        "new": "우주에는 마음 가득 있다……",
        "notes": "ID커맨드 목록명 16칸. 차 축약",
    },
    "GGA-TEXT-0017CC52": {
        "old": "여기서 눈감아 주면, 그 대가……",
        "new": "눈감아 주면, 그 대가……",
        "notes": "ID커맨드 목록명 16칸. 여기서 축약",
    },
    "GGA-TEXT-0017B613": {
        "old": "불사의 제4소대를 얕보지 마라！",
        "new": "불사 제4소대를 얕보지 마라！",
        "notes": "ID커맨드 목록명 16칸. 불사의→불사",
    },
    "GGA-TEXT-0017B7A0": {
        "old": "해야 할 일을 잃은 군대에게……",
        "new": "할 일을 잃은 군대에게……",
        "notes": "ID커맨드 목록명 16칸. 해야 축약",
    },
    "GGA-TEXT-0017B996": {
        "old": "내 몸…… 모두에게 빌려 줄게!",
        "new": "내 몸……모두에 빌려 줄게!",
        "notes": "ID커맨드 목록명 16칸. 공백·에게 축약",
    },
    "GGA-TEXT-0017BB35": {
        "old": "그 기체로는 얘기가 안 되겠군!",
        "new": "그 기체로는 안 되겠군!",
        "notes": "ID커맨드 목록명 16칸. 얘기가 축약",
    },
    "GGA-TEXT-0017BF4A": {
        "old": "목숨을 버려야 할 무대가 아니다",
        "new": "목숨 버려야 할 무대 아니다",
        "notes": "ID커맨드 목록명 16칸. 을/가 축약",
    },
    "GGA-TEXT-0017C220": {
        "old": "이제 아무도 슬프게 하지 않아!",
        "new": "이제 아무도 슬프게 않아!",
        "notes": "ID커맨드 목록명 16칸. 하지 축약",
    },
    "GGA-TEXT-0017C52A": {
        "old": "나의 승리가……우선되는 것이다！",
        "new": "나의 승리가……우선이다！",
        "notes": "ID커맨드 목록명 16칸. 되는 것 축약",
    },
    "GGA-TEXT-0017C591": {
        "old": "MS 성능을 살리지 못한 채……",
        "new": "MS성능을 살리지 못한 채…",
        "notes": "ID커맨드 목록명 16칸. 공백·줄임표 축약",
    },
    "GGA-TEXT-0017C74D": {
        "old": "누구보다 끝까지 싸워 보이겠다!",
        "new": "누구보다 끝 싸워 보이겠다!",
        "notes": "ID커맨드 목록명 16칸. 까지 축약",
    },
    "GGA-TEXT-0017C77A": {
        "old": "죽을 때는 침대 위에서라던데……",
        "new": "죽을 때 침대 위에서라던데…",
        "notes": "ID커맨드 목록명 16칸. 는 축약, 줄임표 1칸",
    },
    "GGA-TEXT-0017CE1C": {
        "old": "사람의 지혜가 만든 것이라면……",
        "new": "사람 지혜가 만든 것이라면……",
        "notes": "ID커맨드 목록명 16칸. 사람의→사람",
    },
    "GGA-TEXT-0017CE74": {
        "old": "추운 시대라고 생각하지 않나……",
        "new": "추운 시대라 생각하지 않나…",
        "notes": "ID커맨드 목록명 16칸. 라고→라, 줄임표 1칸",
    },
}

EFFECT_JOBS: dict[str, dict[str, str]] = {
    "GGA-TEXT-0017B422": {
        "old": "아군 HP 완전 회복",
        "new": "아군 HP완전회복",
        "notes": "ID커맨드 효과 10칸. ss6에서 회복이 잘림",
    },
    "GGA-TEXT-0017B5B8": {
        "old": "자신 HP 완전 회복",
        "new": "자신 HP완전회복",
        "notes": "ID커맨드 효과 10칸. ss6에서 회복이 잘림",
    },
}


def try_recover_slot(fn, rom: bytes | bytearray, font: Any, char: str) -> int | None:
    try:
        return fn(rom, font, {char})[char]
    except SystemExit as exc:
        if "is not painted" in str(exc) or "is not unique" in str(exc):
            return None
        raise


def encode_8x16(
    text: str,
    recovered: dict[str, int],
    verified: dict[str, int],
    live_tokens: dict[str, bytes] | None = None,
) -> bytes:
    encoded, missing = unified.encode_korean_text(
        text,
        recovered,
        verified_charmap=verified,
        strict_punctuation=True,
    )
    gate(encoded is not None and not missing, f"8x16 encode failed {text!r}: {missing}")
    gate(encoded.endswith(b"\x00"), f"8x16 missing NUL: {text!r}")
    if not live_tokens:
        return encoded
    out = bytearray()
    fallback = read_tokens(encoded)
    gate(len(fallback) == len(text), f"fallback token drift {text!r}")
    for char, token in zip(text, fallback):
        out.extend(live_tokens.get(char, token))
    out.append(0)
    return bytes(out)


def set_translation_fields(row: dict[str, Any], translation: str, notes: str) -> None:
    row["translation_ko"] = translation
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-09"
    row["translator_notes"] = notes
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)


def vis(text: str) -> int:
    return len(text.replace("\n", ""))


def overflow_rows(merged: dict[str, Any], category: str, cap: int) -> list[dict[str, Any]]:
    return [
        row
        for row in merged["records"]
        if row.get("semantic_category") == category
        and str(row.get("translation_status") or "") == "translated"
        and vis(str(row.get("translation_ko") or "")) > cap
    ]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    for record_id, job in {**NAME_JOBS, **EFFECT_JOBS}.items():
        cap = NAME_CAP if record_id in NAME_JOBS else EFFECT_CAP
        gate(vis(job["new"]) <= cap, f"{record_id} new {job['new']!r} is {vis(job['new'])} > {cap}")
        gate(job["new"] != job["old"], f"{record_id} is unchanged")
        extra = hangul_chars(job["new"]) - hangul_chars(job["old"])
        gate(not extra, f"{record_id} introduced Hangul {extra} in {job['new']!r}")

    current = MAIN_TIP_ROM.read_bytes()
    original = ORIGINAL_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    gate(sha256(current) == str(main_manifest.get("sha256") or "").lower(), "main TIP/manifest hash drift")
    gate(ORIGINAL_ROM.exists() and MAIN_SAV.exists(), "required source or SAV missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    desc_over = overflow_rows(merged, "id_command_description", DESC_CAP)
    gate(not desc_over, f"description overflow remains {len(desc_over)}")
    name_over = overflow_rows(merged, "id_command_name", NAME_CAP)
    effect_over = overflow_rows(merged, "id_command_effect_summary", EFFECT_CAP)
    gate({row["record_id"] for row in name_over} == set(NAME_JOBS), "name overflow set drift")
    gate({row["record_id"] for row in effect_over} == set(EFFECT_JOBS), "effect overflow set drift")

    jobs: list[tuple[str, str, dict[str, Any]]] = []
    hangul: set[str] = set()
    for category, table, cap in (
        ("id_command_name", NAME_JOBS, NAME_CAP),
        ("id_command_effect_summary", EFFECT_JOBS, EFFECT_CAP),
    ):
        for record_id, spec in table.items():
            row = by_id[record_id]
            gate(row.get("semantic_category") == category, f"{record_id} category drift")
            gate(not unified.uses_12x12(row), f"{record_id} is classified 12x12")
            gate(str(row.get("translation_ko") or "") == spec["old"], f"{record_id} Korean drift")
            hangul.update(hangul_chars(spec["old"]))
            hangul.update(hangul_chars(spec["new"]))
            jobs.append((category, record_id, spec))

    charmap = json.loads(CHARMAP_8.read_text(encoding="utf-8"))
    verified8 = verified_from_charmap(charmap)
    font8 = load_galmuri8()
    font12 = load_galmuri12()
    recovered12: dict[str, int] = {}
    recovered8: dict[str, int] = {}
    paint_8_onto_12: set[str] = set()
    for char in hangul:
        slot8 = try_recover_slot(recover_unique_8x16_slots, current, font8, char)
        slot12 = try_recover_slot(recover_unique_12x12_slots, current, font12, char)
        if slot8 is not None:
            recovered8[char] = slot8
            if slot12 is not None:
                recovered12[char] = slot12
            continue
        if slot12 is None:
            raise SystemExit(f"gate failed: no unique painted slot for {char!r}")
        recovered12[char] = slot12
        paint_8_onto_12.add(char)

    live8, _live12 = unified.collect_live_slots(original, merged["records"])
    candidate = bytearray(current)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    for char in sorted(paint_8_onto_12):
        slot = recovered12[char]
        gate(slot not in live8, f"cannot paint 8x16 {char!r} at live slot 0x{slot:04X}")
        start = paint_8x16(candidate, slot, char, font8)
        allowed.update(range(start, start + fontops.FONT_8X16_STRIDE))
        recovered8[char] = slot
        painted.append({"char": char, "slot": f"0x{slot:04X}", "file_offset": f"0x{start:08X}"})
    for char in hangul:
        gate(char in recovered8, f"8x16 slot missing for {char!r}")
    if paint_8_onto_12:
        verify_hangul_12x12(candidate, {char: recovered12[char] for char in paint_8_onto_12}, font12)

    evidence: list[dict[str, Any]] = []
    for category, record_id, spec in jobs:
        row = by_id[record_id]
        owners = owner_offsets(row)
        gate(owners, f"{record_id} has no U32 owners")
        old_addresses = [u32(current, owner) for owner in owners]
        gate(len(set(old_addresses)) == 1, f"{record_id} owners point at different payloads")
        pointer = old_addresses[0]
        old_payload = payload_at(current, pointer)
        live_tokens = live_char_tokens(spec["old"], old_payload)
        verify_mixed_8x16(candidate, original, old_payload, spec["old"], font8, hangul_chars(spec["old"]), verified8)
        encoded_new = encode_8x16(spec["new"], recovered8, verified8, live_tokens)
        verify_mixed_8x16(candidate, original, encoded_new, spec["new"], font8, hangul_chars(spec["new"]), verified8)
        hangul_only = "".join(char for char in spec["new"] if char in hangul)
        if hangul_only:
            hangul_payload = encode_8x16(hangul_only, recovered8, verified8)
            verify_payload_painted(candidate, hangul_payload, hangul_only, font8)
        start = pointer - ROM_BASE
        write_padded(candidate, start, encoded_new, old_payload, allowed)
        gate(payload_until_nul(candidate, pointer, 128) == encoded_new, f"{record_id} padded payload mismatch")
        for owner in owners:
            gate(u32(candidate, owner) == pointer, f"{record_id} owner was rewritten")
        set_translation_fields(row, spec["new"], spec["notes"])
        evidence.append(
            {
                "record_id": record_id,
                "category": category,
                "before": spec["old"],
                "after": spec["new"],
                "before_cells": vis(spec["old"]),
                "after_cells": vis(spec["new"]),
                "owner_offsets": [f"0x{owner:08X}" for owner in owners],
                "payload": f"0x{pointer:08X}",
                "old_size": len(old_payload),
                "new_size": len(encoded_new),
            }
        )

    leftover_names = overflow_rows(merged, "id_command_name", NAME_CAP)
    leftover_effects = overflow_rows(merged, "id_command_effect_summary", EFFECT_CAP)
    leftover_desc = overflow_rows(merged, "id_command_description", DESC_CAP)
    gate(not leftover_names, f"name overflow remains: {[row['record_id'] for row in leftover_names[:5]]}")
    gate(not leftover_effects, f"effect overflow remains: {[row['record_id'] for row in leftover_effects[:5]]}")
    gate(not leftover_desc, "description overflow reappeared")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"candidate changed outside allowed bytes: {len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "map-script bank changed")
    gate(MAIN_TIP_ROM.read_bytes() == current, "main TIP mutated during patch")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    overlay_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "name_records": sorted(NAME_JOBS),
            "effect_records": sorted(EFFECT_JOBS),
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["idcmd_list_fit_sha256"] = overlay_identity
    identity["translation_overlay_identity_sha256"] = overlay_identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged.setdefault("summary", {})["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = overlay_identity
    merged["idcmd_list_fit_20260909"] = {
        "batch_id": BATCH_ID,
        "name_records": sorted(NAME_JOBS),
        "effect_records": sorted(EFFECT_JOBS),
        "name_cap": NAME_CAP,
        "effect_cap": EFFECT_CAP,
        "desc_cap": DESC_CAP,
    }
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_idcmd_list_fit_candidate_20260909",
        "batch_id": BATCH_ID,
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
            "translation_source": advance_relative(TRANSLATION_MERGED_JSON),
        },
        "layout": {
            "description_12x12": {"x": 16, "cells": DESC_CAP, "overflow_remaining": 0},
            "name_8x16": {"x": 8, "cost_x": 136, "cells": NAME_CAP, "rewritten": len(NAME_JOBS)},
            "effect_8x16": {"x": 160, "screen_right": 240, "cells": EFFECT_CAP, "rewritten": len(EFFECT_JOBS)},
        },
        "painted_8x16_to_match_12x12": painted,
        "consumers": evidence,
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes()},
        "verification": {
            "result": "PASS",
            "changed_bytes": len(changed),
            "allowed_changed_bytes": len(allowed),
            "no_idcmd_desc_over_17": True,
            "no_idcmd_name_over_16": True,
            "no_idcmd_effect_over_10": True,
            "payloads_padded_not_shifted": True,
            "owners_not_rewritten": True,
            "original_map_script_bank_unchanged": True,
            "runtime_emulator": "not run; static ROM/font/payload verification only",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "batch_id": BATCH_ID,
                "names": len(NAME_JOBS),
                "effects": len(EFFECT_JOBS),
                "painted": painted,
                "output": report["output"],
                "verification": report["verification"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
