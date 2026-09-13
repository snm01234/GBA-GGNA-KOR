"""User-verified mistranslation fixes 20260913.

- Master Asia 十二王方牌 shout 대차병 → 대차륜
- 超級覇王 shout 전영다아안 → 전영타아안
- Murrue Ramius: 있으니 충분히 조심하게 → 있으니 충분히 조심합시다
- ID-command 撃破しなくなります: 격파되지 → 격파하지
- ID-command effect 手加減攻撃: 추가공격 → 봐주기공격
"""
from __future__ import annotations

import json
import shutil
import struct
import sys
from collections import Counter, defaultdict
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
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import (  # noqa: E402
    live_char_tokens,
    live_pair_blob,
    owner_u16,
    split_pair,
    write_padded,
)
from patch_ggen_advance_dialogue_idcmd_fit_20260909 import (  # noqa: E402
    live_char_tokens as desc_live_char_tokens,
)
from patch_ggen_advance_idcmd_list_fit_20260909 import DESC_CAP, EFFECT_CAP  # noqa: E402
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
    load_identified_12x12,
    raw_hex_bytes,
)
from patch_ggen_advance_name_unify_20260909 import encode_overlay, patch_map_row_live  # noqa: E402

BATCH_ID = "term-fix-daecharyun-idcmd-mercy-20260913"
IDENTITY_KEY = "term_fix_20260913_sha256"
BATCH_KEY = "term_fix_20260913"
OUT = ROOT / "outputs" / "20260913_term_fix_daecharyun_idcmd"
WORK = OUT / "ggen_term_fix_daecharyun_idcmd_20260913.gba"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260913_term_fix.json"
CUTIN_OVERLAY = ROOT / "integrated" / "translation" / "ggen_advance_battle_cutin_quotes.json"
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
CORR = ROOT / "analysis" / "ggen_advance_12x12_runtime_measurement_corrections_20260829.json"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
CAVE_START = 0x01135470
CAVE_END = 0x01230000
TABLE = 0x00228600
TURN_A_SLOT_12 = 0x071B
NOTES = (
    "십이왕방패 대차병→대차륜; 전영다아안→전영타아안; "
    "마류 조심하게→조심합시다; ID설명 격파되지→격파하지; "
    "手加減攻撃 추가공격→봐주기공격"
)

MAP_JOBS: dict[str, dict[str, Any]] = {
    "GGA-MAPSCRIPT-00F54561": {
        "source": "大当りいいいんっ！！",
        "old_segments": ["대차병！！"],
        "new_segments": ["대차륜！！"],
    },
    "GGA-MAPSCRIPT-00F54600": {
        "source": "電影だぁぁぁぁんっ！！",
        "old_segments": ["전영다아안！！"],
        "new_segments": ["전영타아안！！"],
    },
    "GGA-MAPSCRIPT-00F537CC": {
        "source": "強力なMSが出てくる可能性も\\nあるから、十分気をつけて",
        "old_segments": ["강력한 MS가 나올 가능성도", "있으니 충분히 조심하게"],
        "new_segments": ["강력한 MS가 나올 가능성도", "있으니 충분히 조심합시다"],
    },
}
TEXT8_JOBS: dict[str, dict[str, str]] = {
    "GGA-TEXT-0017B451": {
        "old": "추가공격",
        "new": "봐주기공격",
        "source": "手加<028F>攻撃",
        "notes": "ID커맨드 효과 요약. 手加減攻撃. 추가=追加 오역",
    },
}
CUTIN_JOBS: dict[int, list[tuple[str, str]]] = {
    17: [("대차병！！", "대차륜！！")],
    22: [("전영다아안！！", "전영타아안！！")],
}
CUTIN_OVERLAY_JOBS: dict[str, str] = {
    "GGA-BATTLECUTIN-002283CE": "대차륜！！",
    "GGA-BATTLECUTIN-0022845E": "전영타아안！！",
}
DESC_REPLACE = ("격파되지", "격파하지")


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def patch_merged_row(row: dict[str, Any], ko: str, segments: list[str] | None = None, notes: str | None = None) -> None:
    row["translation_ko"] = ko
    if segments is not None:
        row["translation_segments"] = segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-13"
    row["translator_notes"] = notes or NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    row["pointer_recalc_required"] = True
    update_payload_hash(row)


def rewrite_desc(text: str) -> str:
    return text.replace(*DESC_REPLACE)


def leftover_hits(text: str) -> bool:
    return any(token in text for token in ("대차병", "전영다아안", "충분히 조심하게", "추가공격")) or (
        "격파되지" in text and "격파되지 않" in text
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    aps.CAVE_END = CAVE_END
    OUT.mkdir(parents=True, exist_ok=True)
    parent = MAIN_TIP_ROM.read_bytes()
    japan = ORIGINAL_ROM.read_bytes()
    manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(parent) == manifest["sha256"], "main TIP sha mismatch")
    gate(len(parent) == 32 * 1024 * 1024, "main TIP size drift")
    gate(all(b == 0 for b in parent[CAVE_START:CAVE_END]), "term-fix cave is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")

    for record_id, job in MAP_JOBS.items():
        for line in job["new_segments"]:
            gate("\n" not in line and len(line) <= MAX_DIALOGUE_CELLS, f"map width {record_id} {line!r} {len(line)}")
    for record_id, job in TEXT8_JOBS.items():
        gate(len(job["new"].replace("\n", "")) <= EFFECT_CAP, f"effect cap {record_id}")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    overlay = json.loads(CUTIN_OVERLAY.read_text(encoding="utf-8"))

    for record_id, job in MAP_JOBS.items():
        row = by_id[record_id]
        gate(str(row.get("source_scope")) == "scenario_map_script", f"scope {record_id}")
        gate(str(row.get("source_text") or "") == job["source"], f"source drift {record_id}")
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        gate(old_segments == job["old_segments"], f"map old drift {record_id}: {old_segments}")
    for record_id, job in TEXT8_JOBS.items():
        row = by_id[record_id]
        gate(str(row.get("source_text") or "") == job["source"], f"effect source drift {record_id}")
        gate(str(row.get("translation_ko") or "") == job["old"], f"effect old drift {record_id}")
        gate(str(row.get("semantic_category")) == "id_command_effect_summary", f"effect category {record_id}")

    desc_rows = [
        row
        for row in merged["records"]
        if row.get("semantic_category") == "id_command_description"
        and DESC_REPLACE[0] in str(row.get("translation_ko") or "")
        and "撃破しなく" in str(row.get("source_text") or "")
    ]
    gate(len(desc_rows) == 5, f"desc hit count {len(desc_rows)} {[r['record_id'] for r in desc_rows]}")
    for row in desc_rows:
        after = rewrite_desc(str(row.get("translation_ko") or ""))
        gate(after != str(row.get("translation_ko") or ""), f"desc no-op {row['record_id']}")
        gate(len(after.replace("\n", "")) <= DESC_CAP, f"desc cap {row['record_id']} {after!r}")

    hangul12: set[str] = set()
    hangul8: set[str] = set()
    for job in MAP_JOBS.values():
        for line in job["old_segments"] + job["new_segments"]:
            hangul12.update(hangul_chars(line))
    for pairs in CUTIN_JOBS.values():
        for old, new in pairs:
            hangul12.update(hangul_chars(old))
            hangul12.update(hangul_chars(new))
    for job in TEXT8_JOBS.values():
        hangul8.update(hangul_chars(job["old"]))
        hangul8.update(hangul_chars(job["new"]))
    for row in desc_rows:
        hangul12.update(hangul_chars(str(row.get("translation_ko") or "")))
        hangul12.update(hangul_chars(rewrite_desc(str(row.get("translation_ko") or ""))))
    hangul12.update(hangul_chars("륜타합봅시다봐주기하지"))
    hangul8.update(hangul_chars("봐주기공격"))

    live8, live12 = unified.collect_live_slots(japan, merged["records"])
    verified8 = unified.load_verified_charmap(unified.CHARMAP_8X16_PATH)
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    identified = load_identified_12x12()
    font12 = load_galmuri12()
    jp_forall = slot_raw(japan, fontops.FONT_12X12_BASE, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE)

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
    for char in hangul_chars("륜타합봐주기하지"):
        if char in hangul12:
            gate(char in recovered12, f"missing 12x12 {ascii(char)}")
        if char in hangul8:
            gate(char in recovered8, f"missing 8x16 {ascii(char)}")

    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    changed_ids: list[str] = []

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
        patch_merged_row(row, job["new"], notes=job["notes"])
        changed_ids.append(record_id)
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

    for record_id, job in MAP_JOBS.items():
        row = by_id[record_id]
        old_segments = list(job["old_segments"])
        new_segments = list(job["new_segments"])
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
        patch_merged_row(row, "\n".join(visible_segments(new_segments)), new_segments)
        changed_ids.append(record_id)
        evidence.append({"record_id": record_id, "path": "map_script", "segments": written})

    d12 = load_dictionary(japan, DICT_12X12_BASE, DICT_12X12_END)
    map12 = load_slot_map(MAP12, CORR)
    map12.update(f2.hangul_slot_map(candidate, mode=12))
    for index, pairs in CUTIN_JOBS.items():
        src = TABLE + index * 4
        start = u32(parent, src) - ROM_BASE
        parsed = parse_blocks(parent, start, start + 0x80, d12, map12)
        boundary = int(parsed["consumed_end"])
        gate(boundary > start, f"cutin {index} empty parse")
        original = bytes(parent[start:boundary])
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

    relative_jobs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in desc_rows:
        relative_jobs[str(row.get("container_id") or "")].append(row)
    for container_id, jobs in relative_jobs.items():
        gate(container_id, "relative container id missing")
        members = sorted(
            [row for row in merged["records"] if str(row.get("container_id") or "") == container_id],
            key=lambda item: int(item.get("line_index") or 0),
        )
        gate(len(members) == 2, f"relative pair member count {container_id}")
        owners = {owner_u16(item) for item in members}
        gate(len(owners) == 1 and None not in owners, f"relative pair owner drift {container_id}")
        owner = next(iter(owners))
        start, old_blob = live_pair_blob(bytes(candidate), owner)
        old_line1, old_line2 = split_pair(old_blob)
        after_by_id = {
            str(row["record_id"]): rewrite_desc(str(row.get("translation_ko") or ""))
            if str(row["record_id"]) in {str(item["record_id"]) for item in jobs}
            else str(row.get("translation_ko") or "")
            for row in members
        }
        live_tokens: dict[str, bytes] = {}
        for member, old_line in zip(members, (old_line1, old_line2)):
            original = str(member.get("translation_ko") or "")
            if original:
                for char, token in desc_live_char_tokens(original, old_line).items():
                    prior = live_tokens.get(char)
                    gate(prior is None or prior == token, f"live token conflict {char!r} in {container_id}")
                    live_tokens[char] = token
        new_lines: list[bytes] = []
        texts: list[str] = []
        for member, old_line in zip(members, (old_line1, old_line2)):
            original = str(member.get("translation_ko") or "")
            after = after_by_id[str(member["record_id"])]
            if after == original:
                encoded_new = old_line
            else:
                encoded_new = encode_overlay(after, recovered12, verified12, live_tokens)
            new_lines.append(encoded_new)
            texts.append(after)
        packed = new_lines[0] + new_lines[1]
        write_padded(candidate, start, packed, old_blob, allowed)
        for row in jobs:
            after = rewrite_desc(str(row.get("translation_ko") or ""))
            patch_merged_row(row, after)
            changed_ids.append(str(row["record_id"]))
        evidence.append(
            {
                "container_id": container_id,
                "path": "relative_pair",
                "after": texts,
                "old_size": len(old_blob),
                "new_size": len(packed),
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

    def live_map_lines(row: dict[str, Any]) -> list[str]:
        cursor = int(str(row["target_file_offset"]), 16)
        lines: list[str] = []
        for segment in row.get("segments") or []:
            raw = raw_hex_bytes(str(segment.get("raw_hex") or ""))
            if not raw:
                continue
            orig = ROM_BASE + cursor
            lookups = aps.find_lookups(bytes(candidate), orig, orig + len(raw) - 1)
            gate(lookups, f"map lookup missing {row['record_id']} @ {hex(cursor)}")
            lines.append(f2.decode_text(candidate, lookups[0][1], dict12, map12_dec))
            cursor += len(raw)
        return lines

    effect_live = dec8(owner_offsets(by_id["GGA-TEXT-0017B451"])[0])
    gate(effect_live == "봐주기공격", f"effect live {effect_live}")
    maryu = live_map_lines(by_id["GGA-MAPSCRIPT-00F537CC"])
    gate(maryu == ["강력한 MS가 나올 가능성도", "있으니 충분히 조심합시다"], ascii(maryu))
    daecharyun = live_map_lines(by_id["GGA-MAPSCRIPT-00F54561"])
    gate(daecharyun == ["대차륜！！"], ascii(daecharyun))
    jeonyeong = live_map_lines(by_id["GGA-MAPSCRIPT-00F54600"])
    gate(jeonyeong == ["전영타아안！！"], ascii(jeonyeong))

    parsed17 = parse_blocks(
        bytes(candidate),
        u32(candidate, TABLE + 17 * 4) - ROM_BASE,
        u32(candidate, TABLE + 17 * 4) - ROM_BASE + 0x80,
        dict12,
        {**map12, **hangul_live12},
    )
    parsed22 = parse_blocks(
        bytes(candidate),
        u32(candidate, TABLE + 22 * 4) - ROM_BASE,
        u32(candidate, TABLE + 22 * 4) - ROM_BASE + 0x80,
        dict12,
        {**map12, **hangul_live12},
    )
    texts17 = [str(stream["source_text"]) for stream in parsed17["streams"]]
    texts22 = [str(stream["source_text"]) for stream in parsed22["streams"]]
    gate("대차륜！！" in texts17 and "대차병" not in "".join(texts17), texts17)
    gate("전영타아안！！" in texts22 and "전영다아안" not in "".join(texts22), texts22)
    gate(
        slot_raw(candidate, FONT12_RELOCATED, TURN_A_SLOT_12, fontops.FONT_12X12_STRIDE) == jp_forall,
        "∀ glyph drifted",
    )

    desc_proofs: dict[str, list[str]] = {}
    for container_id, jobs in relative_jobs.items():
        members = sorted(
            [row for row in merged["records"] if str(row.get("container_id") or "") == container_id],
            key=lambda item: int(item.get("line_index") or 0),
        )
        owner = owner_u16(members[0])
        assert owner is not None
        _start, blob = live_pair_blob(bytes(candidate), owner)
        line1, line2 = split_pair(blob)
        decoded = [
            f2.decode_text(candidate, ROM_BASE + _start, dict12, map12_dec),
            f2.decode_text(candidate, ROM_BASE + _start + len(line1), dict12, map12_dec),
        ]
        gate(decoded[1].startswith("격파하지"), f"{container_id} {decoded}")
        gate("격파되지" not in decoded[1], f"{container_id} leftover {decoded}")
        desc_proofs[container_id] = decoded

    leftover = [
        str(row["record_id"])
        for row in merged["records"]
        if leftover_hits(str(row.get("translation_ko") or ""))
        or any(leftover_hits(str(item)) for item in (row.get("translation_segments") or []))
    ]
    gate(not leftover, f"translation leftover {leftover}")

    changed = {i for i, (old, new) in enumerate(zip(parent, candidate)) if old != new}
    gate(changed <= allowed, f"unrelated writes {len(changed - allowed)}")
    gate(bytes(candidate[0x00F00000:0x00FC0000]) == parent[0x00F00000:0x00FC0000], "original map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(parent), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "term-fix cave overflow")

    for row in overlay.get("records", []):
        record_id = str(row.get("record_id") or "")
        if record_id in CUTIN_OVERLAY_JOBS:
            row["translation_ko"] = CUTIN_OVERLAY_JOBS[record_id]
            row["translation_source"] = "user_verified:대차륜" if "대차륜" in CUTIN_OVERLAY_JOBS[record_id] else "user_verified:전영타아안"
            row["translation_status"] = "translated"
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
    merged[BATCH_KEY] = {"batch_id": BATCH_ID, "changed_records": changed_ids, "notes": NOTES}
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)
    WORK.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT / "ggen_term_fix_daecharyun_idcmd_20260913.sav")
    proofs = {
        "effect": effect_live,
        "maryu": maryu,
        "daecharyun": daecharyun,
        "jeonyeong": jeonyeong,
        "cutin_17": texts17,
        "cutin_22": texts22,
        "idcmd_desc": desc_proofs,
    }
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_term_fix_daecharyun_idcmd_20260913",
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
            "daechabyeong_to_daecharyun": True,
            "jeonyeong_taaan": True,
            "maryu_caution_inclusive": True,
            "idcmd_mercy_active_voice": True,
            "idcmd_tegakagen_not_chuga": True,
            "runtime_emulator": "not run; static ROM verification only",
            "changed_bytes": len(changed),
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "analysis" / "ggen_advance_term_fix_daecharyun_idcmd_candidate_20260913.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": "PASS", "painted_glyphs": painted, "cave": report["cave"], "output": report["output"], "proofs": proofs}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
