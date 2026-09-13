"""User-verified mistranslation fixes 20260912.

- Maryu: 모르겠게 됐어 → 모르게 됐어
- GP03 Dendrobium weapon I필드 → 돌격 (this 8x16 slot only)
- Shining Finger Sword shouts: 하트엇/멘/메에에엔 → 하트으/면/며어어언
- Bright ID command: ……모두의 목숨을 내놔 → 모두의 목숨을 주게
- Scenario leftover 빌고 → 비르고
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
import patch_ggen_advance_apsaras_zentetsu_20260908 as aps  # noqa: E402
import patch_ggen_profile_followup2_20260912 as f2  # noqa: E402
from build_ggen_advance_battle_cutin_quotes_20260905 import (  # noqa: E402
    parse_blocks,
    rebuild_container,
    verify_hangul_and_nu,
)
from extract_ggen_advance_id_command_battle_barks import load_slot_map  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    FONT12_RELOCATED,
    load_galmuri12,
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
    load_dictionary,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import (  # noqa: E402
    hangul_chars,
    patch_owned_payload,
    visible_segments,
    write_payload,
)
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import live_char_tokens  # noqa: E402
from patch_ggen_advance_idcmd_list_fit_20260909 import NAME_CAP  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    gate,
    payload_at,
    sha256,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    owner_offsets,
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    encode_map_korean_line,
    load_identified_12x12,
)
from patch_ggen_advance_name_unify_20260909 import (  # noqa: E402
    encode_overlay,
    patch_map_row_live,
)

BATCH_ID = "user-fix-maryu-dendrobium-shining-bright-virgo-20260912"
IDENTITY_KEY = "user_fix_20260912_sha256"
BATCH_KEY = "user_fix_20260912"
OUT = ROOT / "outputs" / "20260912_user_fix_dialogue"
WORK = OUT / "ggen_user_fix_20260912.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260912_user_fix.json"
CUTIN_OVERLAY = ROOT / "integrated" / "translation" / "ggen_advance_battle_cutin_quotes.json"
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
CORR = ROOT / "analysis" / "ggen_advance_12x12_runtime_measurement_corrections_20260829.json"
CAVE_START = 0x0113529C
CAVE_END = 0x01230000
TABLE = 0x00228600
TURN_A_SLOT_12 = 0x071B
NOTES = (
    "마류 모르게 됐어; GP03 덴드로비움 I필드→돌격; "
    "샤이닝F 하트으/면/며어어언; 브라이트 ID 목숨을 주게; 시나리오 빌고→비르고"
)

MAP_JOBS: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F824BC": ["모르게 됐어……"],
    "GGA-MAPSCRIPT-00F5451A": ["면！ 면！", "며어어언！！"],
    "GGA-MAPSCRIPT-00F526A4": ["OZ가 쓰는 비르고라는", "기체는……"],
    "GGA-MAPSCRIPT-00F527F4": ["적의 주력은 전에 싸운", "비르고 타입이겠지"],
    "GGA-MAPSCRIPT-00F534AD": ["비르고 타입 MS를 사용하고", "있음이 확인되었습니다"],
}
TEXT8_JOBS: dict[str, dict[str, str]] = {
    "GGA-TEXT-0017A1C9": {"old": "I필드", "new": "돌격", "notes": "GP03 덴드로비움 무장. ss1 돌격. 다른 I필드는 유지"},
    "GGA-TEXT-0017C7DE": {
        "old": "……모두의 목숨을 내놔！",
        "new": "모두의 목숨을 주게！",
        "notes": "브라이트 ID커맨드 목록명. 내놔→주게, 선두 줄임표 제거",
    },
}
CUTIN_JOBS: dict[int, list[tuple[str, str]]] = {
    13: [("킹 오브 하트엇！", "킹 오브 하트으！")],
    15: [("멘！ 멘！", "면！ 면！"), ("메에에엔！！", "며어어언！！")],
}
CUTIN_OVERLAY_JOBS: dict[str, str] = {
    "GGA-BATTLECUTIN-0022834C": "킹 오브 하트으！",
    "GGA-BATTLECUTIN-00228386": "면！ 면！",
    "GGA-BATTLECUTIN-0022838F": "며어어언！！",
}
KEEP_IFEILD = ("I 필드", "I 필드 사벨")
KEEP_DOLGYEOK = "GGA-TEXT-0017A41B"


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def apply_visible(old_segments: list[str], new_visible: list[str], record_id: str) -> list[str]:
    old_visible = visible_segments(old_segments)
    gate(len(old_visible) == len(new_visible), f"visible count {record_id}")
    if not old_segments:
        return list(new_visible)
    out: list[str] = []
    index = 0
    for item in old_segments:
        if item:
            out.append(new_visible[index])
            index += 1
        else:
            out.append(item)
    gate(index == len(new_visible), f"visible framing {record_id}")
    return out


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


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "user-fix cave is not empty")
    for record_id, segs in MAP_JOBS.items():
        for line in segs:
            gate("\n" not in line and len(line) <= MAX_DIALOGUE_CELLS, f"map width {record_id} {line!r} {len(line)}")
    for record_id, job in TEXT8_JOBS.items():
        gate(len(job["new"].replace("\n", "")) <= NAME_CAP, f"8x16 width {record_id}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    overlay = json.loads(CUTIN_OVERLAY.read_text(encoding="utf-8"))
    for record_id in list(MAP_JOBS) + list(TEXT8_JOBS):
        gate(record_id in by_id, f"missing {record_id}")
    gate(str(by_id["GGA-MAPSCRIPT-00F824BC"].get("translation_ko") or "") == "모르겠게 됐어……", "maryu drift")
    gate(str(by_id["GGA-TEXT-0017A1C9"].get("translation_ko") or "") == "I필드", "dendrobium weapon drift")
    gate("목숨을 내놔" in str(by_id["GGA-TEXT-0017C7DE"].get("translation_ko") or ""), "bright idcmd drift")
    gate("필살！\n킹 오브 하트으！" in str(by_id["GGA-MAPSCRIPT-00F544D2"].get("translation_ko") or ""), "map heart already fixed")

    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    identified = load_identified_12x12()
    font12 = load_galmuri12()
    jp_forall = slot_raw(japan, fontops.FONT_12X12_BASE, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE)

    hangul12: set[str] = set()
    hangul8: set[str] = set()
    for segs in MAP_JOBS.values():
        hangul12.update(char for line in segs for char in hangul_chars(line))
    for old_segs in (by_id[rid].get("translation_segments") or [] for rid in MAP_JOBS):
        hangul12.update(char for line in old_segs for char in hangul_chars(str(line)))
    for pairs in CUTIN_JOBS.values():
        for old, new in pairs:
            hangul12.update(hangul_chars(old))
            hangul12.update(hangul_chars(new))
    for job in TEXT8_JOBS.values():
        hangul8.update(hangul_chars(job["old"]))
        hangul8.update(hangul_chars(job["new"]))

    keep_ifield_payloads: dict[int, bytes] = {}
    dendrobium_owners = set(owner_offsets(by_id["GGA-TEXT-0017A1C9"]))
    for row in merged["records"]:
        ko_text = str(row.get("translation_ko") or "")
        if str(row["record_id"]) == "GGA-TEXT-0017A1C9":
            continue
        if ko_text not in KEEP_IFEILD and ko_text != "I필드":
            continue
        for owner in owner_offsets(row):
            if owner in dendrobium_owners:
                continue
            pointer = u32(parent, owner)
            keep_ifield_payloads[owner] = payload_at(parent, pointer)

    candidate = bytearray(parent)
    allowed: set[int] = set()
    painted: list[dict[str, str]] = []
    occupied8: set[int] = set()
    occupied12: set[int] = set()
    recovered8 = f2.recover_hangul(
        candidate, japan, hangul8, mode=8, live=live8, occupied=occupied8, allowed=allowed, painted=painted
    )
    recovered12 = f2.recover_hangul(
        candidate, japan, hangul12, mode=12, live=live12, occupied=occupied12, allowed=allowed, painted=painted
    )
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []

    for record_id, job in TEXT8_JOBS.items():
        row = by_id[record_id]
        owners = owner_offsets(row)
        gate(owners, f"no owners {record_id}")
        ptrs = {u32(parent, owner) for owner in owners}
        gate(len(ptrs) == 1, f"{record_id} owners diverge")
        pointer = next(iter(ptrs))
        old_payload = payload_at(parent, pointer)
        live_tokens = live_char_tokens(job["old"], old_payload)
        new_payload = encode_overlay(job["new"], recovered8, verified8, live_tokens)
        cave_cursor, old_addresses, new_addr = patch_owned_payload(
            row, old_payload, new_payload, parent, candidate, allowed, cave_cursor, require_nul=True
        )
        evidence.append(
            {
                "record_id": record_id,
                "path": "u32_8x16",
                "before": job["old"],
                "after": job["new"],
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
                "encoded_size": len(new_payload),
            }
        )

    for record_id, new_visible in MAP_JOBS.items():
        row = by_id[record_id]
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        new_segments = apply_visible(old_segments, new_visible, record_id)
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
        evidence.append({"record_id": record_id, "path": "map_script", "segments": written})

    d12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    map12 = load_slot_map(MAP12, CORR)
    map12.update(f2.hangul_slot_map(candidate, mode=12))
    cutin_ptrs = [(TABLE + i * 4, u32(parent, TABLE + i * 4) - ROM_BASE) for i in range(37)]
    for index, pairs in CUTIN_JOBS.items():
        src, start = cutin_ptrs[index]
        boundary = cutin_ptrs[index + 1][1]
        original = bytes(parent[start:boundary])
        parsed = parse_blocks(parent, start, boundary, d12, map12)
        replacements: dict[int, bytes] = {}
        for stream in parsed["streams"]:
            raw = bytes.fromhex(str(stream["raw_hex"]).replace(" ", ""))
            replacements[int(stream["start_file_offset"], 16)] = raw
        for old, new in pairs:
            hits = [stream for stream in parsed["streams"] if str(stream["source_text"]) == old]
            gate(len(hits) == 1, f"cutin {index} {old!r} hits={len(hits)} {[s['source_text'] for s in parsed['streams']]}")
            stream = hits[0]
            encoded, missing = unified.encode_korean_text(
                new, recovered12, verified_charmap=verified12, strict_punctuation=True
            )
            gate(encoded is not None and not missing, f"cutin encode {new!r} {missing}")
            assert encoded is not None
            verify_hangul_and_nu(candidate, encoded, new, font12, japan)
            replacements[int(stream["start_file_offset"], 16)] = encoded
        rebuilt = rebuild_container(original, start, parsed, replacements)
        if len(rebuilt) <= len(original):
            candidate[start : start + len(rebuilt)] = rebuilt
            if len(rebuilt) < len(original):
                candidate[start + len(rebuilt) : start + len(original)] = b"\x00" * (len(original) - len(rebuilt))
            allowed.update(range(start, start + len(original)))
            new_addr = ROM_BASE + start
        else:
            new_addr, cave_cursor = write_payload(
                candidate, ROM_BASE + start, rebuilt, len(original), allowed, cave_cursor, require_nul=False
            )
            if new_addr != ROM_BASE + start:
                struct.pack_into("<I", candidate, src, new_addr)
                allowed.update(range(src, src + 4))
        evidence.append(
            {
                "record_id": f"cutin-{index}",
                "path": "battle_cutin",
                "after": [new for _old, new in pairs],
                "new_address": f"0x{new_addr:08X}",
                "new_size": len(rebuilt),
            }
        )

    hangul_live8 = f2.hangul_slot_map(candidate, mode=8)
    hangul_live12 = f2.hangul_slot_map(candidate, mode=12)
    map8 = f2.slot_to_char_map(verified8, recovered8, hangul_live8)
    map12_dec = f2.slot_to_char_map(verified12, recovered12, hangul_live12)
    dict8 = load_dictionary(bytes(candidate), DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(bytes(candidate), DICT_12X12_BASE, DICT_12X12_END)

    def dec8(owner: int) -> str:
        return f2.decode_text(candidate, u32(candidate, owner), dict8, map8)

    def dec12_ptr(ptr: int) -> str:
        return f2.decode_text(candidate, ptr, dict12, map12_dec)

    dendrobium = dec8(0x00190D88)
    gate(dendrobium == "돌격", f"dendrobium {dendrobium}")
    gate(dec8(0x001972FC) == "돌격", "dendrobium secondary")
    bright = dec8(0x001A8F48)
    gate(bright == "모두의 목숨을 주게！", f"bright {bright}")
    gate(keep_ifield_payloads, "lost I필드 keep-set")
    for owner, old_payload in keep_ifield_payloads.items():
        pointer = u32(candidate, owner)
        gate(payload_at(candidate, pointer) == old_payload, f"I필드 keep payload drift owner 0x{owner:08X}")
    gate(str(by_id[KEEP_DOLGYEOK].get("translation_ko") or "") == "돌격", "unrelated 돌격 sheet drift")
    parsed15 = parse_blocks(
        bytes(candidate),
        u32(candidate, TABLE + 15 * 4) - ROM_BASE,
        u32(candidate, TABLE + 16 * 4) - ROM_BASE,
        dict12,
        {**map12, **hangul_live12},
    )
    parsed13 = parse_blocks(
        bytes(candidate),
        u32(candidate, TABLE + 13 * 4) - ROM_BASE,
        u32(candidate, TABLE + 14 * 4) - ROM_BASE,
        dict12,
        {**map12, **hangul_live12},
    )
    texts13 = [str(stream["source_text"]) for stream in parsed13["streams"]]
    texts15 = [str(stream["source_text"]) for stream in parsed15["streams"]]
    gate("킹 오브 하트으！" in texts13 and "하트엇" not in "".join(texts13), texts13)
    gate(texts15[:2] == ["면！ 면！", "며어어언！！"], texts15)
    gate(
        slot_raw(candidate, FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE) == jp_forall,
        "∀ glyph drifted",
    )

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")

    changed_ids: list[str] = []
    for record_id, new_visible in MAP_JOBS.items():
        row = by_id[record_id]
        new_segments = apply_visible([str(item) for item in (row.get("translation_segments") or [])], new_visible, record_id)
        patch_merged_row(row, "\n".join(new_visible), new_segments)
        changed_ids.append(record_id)
    for record_id, job in TEXT8_JOBS.items():
        patch_merged_row(by_id[record_id], job["new"])
        by_id[record_id]["translator_notes"] = job["notes"]
        changed_ids.append(record_id)
    leftover_virgo = [
        str(row["record_id"])
        for row in merged["records"]
        if str(row.get("source_scope")) == "scenario_map_script"
        and "빌고" in str(row.get("translation_ko") or "")
    ]
    gate(not leftover_virgo, f"scenario 빌고 leftover {leftover_virgo}")
    leftover_maryu = [
        str(row["record_id"])
        for row in merged["records"]
        if "모르겠게" in str(row.get("translation_ko") or "")
        or any("모르겠게" in str(item) for item in (row.get("translation_segments") or []))
    ]
    gate(not leftover_maryu, f"maryu leftover {leftover_maryu}")
    leftover_shining = [
        str(row["record_id"])
        for row in merged["records"]
        if any(token in str(row.get("translation_ko") or "") for token in ("하트엇", "멘！ 멘", "메에에엔"))
        or any(any(token in str(item) for token in ("하트엇", "멘！ 멘", "메에에엔")) for item in (row.get("translation_segments") or []))
    ]
    gate(not leftover_shining, f"shining leftover {leftover_shining}")
    leftover_bright = [
        str(row["record_id"])
        for row in merged["records"]
        if "목숨을 내놔" in str(row.get("translation_ko") or "")
    ]
    gate(not leftover_bright, f"bright leftover {leftover_bright}")

    for row in overlay.get("records", []):
        record_id = str(row.get("record_id") or "")
        if record_id in CUTIN_OVERLAY_JOBS:
            row["translation_ko"] = CUTIN_OVERLAY_JOBS[record_id]
            row["translation_source"] = "user_verified"
    CUTIN_OVERLAY.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": changed_ids, "evidence": evidence}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    WORK.write_bytes(bytes(candidate))
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_user_fix_20260912",
        "batch_id": BATCH_ID,
        "parent_sha256": sha256(parent),
        "output": {"path": advance_relative(WORK), "size": len(candidate), "sha256": sha256(bytes(candidate))},
        "painted": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "changed_bytes": len(changed),
        "changed_records": changed_ids,
        "evidence": evidence,
        "proofs": {
            "dendrobium_weapon": dendrobium,
            "bright_idcmd": bright,
            "cutin_13": texts13,
            "cutin_15": texts15,
        },
        "verification": {
            "result": "PASS",
            "unrelated_bytes_preserved": True,
            "forall_071b_preserved": True,
            "other_ifield_kept": True,
            "scenario_virgo_clean": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("output", "painted", "cave", "proofs", "verification")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
