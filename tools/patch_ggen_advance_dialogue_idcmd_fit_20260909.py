#!/usr/bin/env python3
"""Fix two awkward map lines and fit overflowing ID-command descriptions.

1. Kou Uraki ``こんな戦術レベルの戦いの最中になにを！？``
   ``전술 수준`` is a calque; the game already uses ``전술 레벨``.
2. Federation officer ``少歩がMSを持ち出したと！！`` is dictionary-decoded
   少年 (Camille Bidan). Korean ``소녀`` is corrected to ``소년``.
3. ID-command 12x12 descriptions longer than the yellow help box (ss4/ss6)
   are shortened to 17 cells, matching the longest Japanese lines that fit.
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

import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
from ggen_advance_painted_glyph_identity import load_galmuri12, recover_unique_12x12_slots  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    sha256,
    update_payload_hash,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    payload_until_nul,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    MAX_DIALOGUE_CELLS,
    encode_map_korean_line,
    load_identified_12x12,
    raw_hex_bytes,
)
from patch_ggen_advance_rank_terms_20260908 import lookup_entries  # noqa: E402

BATCH_ID = "dialogue-idcmd-desc-fit-20260909"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260909_dialogue_idcmd_fit.json"
OUT_DIR = ROOT / "outputs" / "20260909_ggen_advance_dialogue_idcmd_fit"
OUTPUT = OUT_DIR / "ggen_advance_dialogue_idcmd_fit_candidate_20260909.gba"
OUT_SAV = OUT_DIR / "ggen_advance_dialogue_idcmd_fit_candidate_20260909.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_dialogue_idcmd_fit_candidate_20260909.json"
MANIFEST = OUT_DIR / "manifest.json"
MAP_BANK = (0x00F00000, 0x00FC0000)
ROM_BASE = 0x08000000
RELATIVE_BASE_LITERAL = 0x0004DC54
RELATIVE_OLD_BASE = 0x001BF908
MAX_IDCMD_DESC_CELLS = 17

MAP_JOBS: dict[str, dict[str, Any]] = {
    "GGA-MAPSCRIPT-00F75695": {
        "new_segments": ["이런 전술 레벨의", "싸움 한복판에 뭔소리야!?"],
        "source": "こんな戦術レベルの\\n戦いの最中になにを！？",
        "notes": "戦術レベル는 게임 용어 전술 레벨. 한가운데에→한복판에",
    },
    "GGA-MAPSCRIPT-00F79D1F": {
        "new_segments": ["MS 덱에서,", "소년이 MS를 꺼냈다고!!"],
        "source": "MSデッキから、\\n少歩がMSを持ち出したと！！",
        "notes": "少歩는 12x12 少年 디코드. 카미유 비단을 가리키므로 소년",
    },
}

# Longest-first. Applied only while the line still exceeds 17 cells.
IDCMD_COMPRESS: tuple[tuple[str, str], ...] = (
    ("전투 시 자신의 근접 공격 ", "전투시 근접공격 "),
    ("전투 시 자신의 ", "전투시 "),
    ("전투 시 적의 ", "전투시 적 "),
    ("전투 시 아군 팀의 ", "전투시 아군팀 "),
    ("전투 시 적 팀의 ", "전투시 적팀 "),
    ("전투 시 공격을 명중시킨 적의 ", "전투시 명중시킨 적 "),
    ("전투 시 공격 대상의 HP가 30% 미만", "전투시 공격대상 HP 30%미만"),
    ("전투 시 ", "전투시 "),
    ("자군 유닛 전원의 ", "자군 전원 "),
    ("자군 전원의 ", "자군 전원 "),
    ("완전 회피와 ID 봉인 ", "완전회피·ID봉인 "),
    ("완전히 ", "완전 "),
    ("효과를 얻습니다", "효과를 얻음"),
    ("선제 공격을 합니다", "선제공격합니다"),
    ("격파되지 않습니다.", "격파되지 않음."),
    ("다만 회피는 불가", "다만 회피 불가"),
    ("위력과 명중과 회피", "위력·명중·회피"),
    ("회피합니다", "회피함"),
    ("공격과 산개를", "공격·산개를"),
    ("HP와 SP를", "HP·SP를"),
)


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def u16(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def u32(data: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def hangul_chars(text: str) -> set[str]:
    return {char for char in text if "가" <= char <= "힣"}


def fit_idcmd(text: str) -> str:
    current = text
    if len(current) <= MAX_IDCMD_DESC_CELLS:
        return current
    for source, dest in IDCMD_COMPRESS:
        if len(current) <= MAX_IDCMD_DESC_CELLS:
            break
        current = current.replace(source, dest)
    gate(
        len(current) <= MAX_IDCMD_DESC_CELLS,
        f"ID description still overflows {len(current)}: {current!r} <= {text!r}",
    )
    return current


def owner_u16(row: dict[str, Any]) -> int | None:
    for owner in row.get("owner_ids") or []:
        if str(owner).startswith("OWNER-U16-"):
            return int(str(owner).removeprefix("OWNER-U16-"), 16)
    return None


def live_pair_blob(rom: bytes, owner: int) -> tuple[int, bytes]:
    base = u32(rom, RELATIVE_BASE_LITERAL) - ROM_BASE
    rel = owner - RELATIVE_OLD_BASE
    gate(rel >= 0 and rel % 2 == 0, f"relative owner not aligned 0x{owner:08X}")
    start = base + u16(rom, base + rel)
    end = base + u16(rom, base + rel + 2)
    gate(start < end <= len(rom), f"relative pair range drift owner 0x{owner:08X}")
    return start, bytes(rom[start:end])


def read_tokens(blob: bytes) -> list[bytes]:
    tokens: list[bytes] = []
    index = 0
    while index < len(blob):
        lead = blob[index]
        if lead == 0:
            break
        if lead >= 0xE0:
            gate(index + 1 < len(blob), "truncated ID desc token")
            tokens.append(blob[index : index + 2])
            index += 2
        else:
            tokens.append(blob[index : index + 1])
            index += 1
    return tokens


def live_char_tokens(text: str, blob: bytes) -> dict[str, bytes]:
    tokens = read_tokens(blob)
    gate(len(tokens) == len(text), f"live token/text length drift {len(tokens)}!={len(text)} {text!r}")
    mapping: dict[str, bytes] = {}
    for char, token in zip(text, tokens):
        prior = mapping.get(char)
        gate(prior is None or prior == token, f"live token conflict for {char!r}")
        mapping[char] = token
    return mapping


def encode_desc(
    text: str,
    recovered: dict[str, int],
    verified: dict[str, int],
    live_tokens: dict[str, bytes] | None = None,
) -> bytes:
    if not text:
        return b"\x00"
    encoded, missing = unified.encode_korean_text(
        text,
        recovered,
        verified_charmap=verified,
        strict_punctuation=True,
    )
    gate(encoded is not None and not missing, f"ID desc encode failed {text!r}: {missing}")
    gate(encoded.endswith(b"\x00"), f"ID desc missing NUL: {text!r}")
    if not live_tokens:
        return encoded
    out = bytearray()
    fallback = read_tokens(encoded)
    gate(len(fallback) == len(text), f"fallback token drift {text!r}")
    for char, token in zip(text, fallback):
        out.extend(live_tokens.get(char, token))
    out.append(0)
    return bytes(out)


def split_pair(blob: bytes) -> tuple[bytes, bytes]:
    first = blob.find(0)
    gate(first >= 0, "relative pair missing first NUL")
    line1 = blob[: first + 1]
    rest = blob[first + 1 :]
    second = rest.find(0)
    gate(second >= 0, "relative pair missing second NUL")
    line2 = rest[: second + 1]
    gate(line1 + line2 == blob or blob.startswith(line1 + line2), "relative pair has trailing junk before pad")
    return line1, line2


def write_padded(
    candidate: bytearray,
    file_offset: int,
    new_blob: bytes,
    old_blob: bytes,
    allowed: set[int],
) -> None:
    gate(len(new_blob) <= len(old_blob), f"relative pair grew {len(new_blob)}>{len(old_blob)}")
    gate(bytes(candidate[file_offset : file_offset + len(old_blob)]) == old_blob, "live pair changed before write")
    padded = new_blob + b"\x00" * (len(old_blob) - len(new_blob))
    candidate[file_offset : file_offset + len(old_blob)] = padded
    allowed.update(range(file_offset, file_offset + len(old_blob)))


def set_translation_fields(
    row: dict[str, Any],
    translation: str,
    segments: list[str] | None,
    notes: str,
) -> None:
    row["translation_ko"] = translation
    if segments is not None:
        row["translation_segments"] = segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-09"
    row["translator_notes"] = notes
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP must be 32 MiB")
    gate(sha256(current) == str(main_manifest.get("sha256") or "").lower(), "main TIP/manifest hash drift")
    gate(ORIGINAL_ROM.exists() and MAIN_SAV.exists(), "required source or SAV missing")
    gate(u32(current, RELATIVE_BASE_LITERAL) >= 0x09000000, "relative pair base was not relocated")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    for record_id, job in MAP_JOBS.items():
        row = by_id[record_id]
        gate(row.get("source_scope") == "scenario_map_script", f"map scope drift {record_id}")
        gate(str(row.get("source_text") or "") == job["source"], f"source drift {record_id}")

    desc_rows = [
        row
        for row in merged["records"]
        if row.get("semantic_category") == "id_command_description"
        and str(row.get("translation_status") or "") == "translated"
    ]
    overflow_before = [row for row in desc_rows if len(str(row.get("translation_ko") or "")) > MAX_IDCMD_DESC_CELLS]
    gate(overflow_before, "no overflowing ID-command descriptions found")

    hangul: set[str] = set()
    for record_id, job in MAP_JOBS.items():
        hangul.update(hangul_chars(str(by_id[record_id].get("translation_ko") or "")))
        hangul.update(hangul_chars("\n".join(job["new_segments"])))
    planned_desc: list[tuple[dict[str, Any], str, str]] = []
    for row in overflow_before:
        before = str(row.get("translation_ko") or "")
        after = fit_idcmd(before)
        gate(after != before, f"fit produced no change {row['record_id']}: {before!r}")
        hangul.update(hangul_chars(before))
        hangul.update(hangul_chars(after))
        planned_desc.append((row, before, after))

    font12 = load_galmuri12()
    recovered12 = recover_unique_12x12_slots(current, font12, hangul)
    identified12 = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    candidate = bytearray(current)
    allowed: set[int] = set()
    map_evidence: list[dict[str, Any]] = []
    desc_evidence: list[dict[str, Any]] = []

    for record_id, job in MAP_JOBS.items():
        row = by_id[record_id]
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        new_segments = [str(item) for item in job["new_segments"]]
        gate(len(old_segments) == len(new_segments), f"map segment count {record_id}")
        segments = list(row.get("segments") or [])
        gate(len(segments) == len(new_segments), f"map framing {record_id}")
        cursor = int(str(row["target_file_offset"]), 16)
        for index, (segment, old_text, new_text) in enumerate(zip(segments, old_segments, new_segments)):
            raw = raw_hex_bytes(str(segment.get("raw_hex") or ""))
            gate(raw.endswith(b"\x00"), f"map segment missing NUL {record_id}#{index}")
            orig_addr = ROM_BASE + cursor
            orig_end = orig_addr + len(raw) - 1
            hits = lookup_entries(current, orig_addr, orig_end)
            relocated = hits[0][1]
            old_payload = payload_until_nul(current, relocated, 128)
            old_encoded, old_missing = encode_map_korean_line(old_text, recovered12, identified12)
            gate(not old_missing and old_encoded == old_payload, f"map old payload mismatch {record_id}#{index}")
            gate("\n" not in new_text and len(new_text) <= MAX_DIALOGUE_CELLS, f"map width {record_id}#{index}")
            new_encoded, new_missing = encode_map_korean_line(new_text, recovered12, identified12)
            gate(new_encoded is not None and not new_missing, f"map encode failed {record_id}#{index}: {new_missing}")
            gate(len(new_encoded) <= len(old_payload), f"map payload grew {record_id}#{index}")
            start = relocated - ROM_BASE
            candidate[start : start + len(new_encoded)] = new_encoded
            if len(new_encoded) < len(old_payload):
                candidate[start + len(new_encoded) : start + len(old_payload)] = b"\x00" * (
                    len(old_payload) - len(new_encoded)
                )
            allowed.update(range(start, start + len(old_payload)))
            map_evidence.append(
                {
                    "record_id": record_id,
                    "segment": index,
                    "before": old_text,
                    "after": new_text,
                    "cells": len(new_text),
                    "payload": f"0x{relocated:08X}",
                    "lookup_copies": len(hits),
                }
            )
            cursor += len(raw)
        set_translation_fields(row, "\n".join(new_segments), new_segments, str(job["notes"]))

    dirty_containers: set[str] = set()
    after_by_id: dict[str, str] = {}
    for row, before, after in planned_desc:
        after_by_id[str(row["record_id"])] = after
        dirty_containers.add(str(row.get("container_id") or ""))
    gate("" not in dirty_containers, "ID desc container_id missing")

    by_container: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in merged["records"]:
        if str(row.get("container_id") or "") in dirty_containers:
            by_container[str(row["container_id"])].append(row)

    for container_id in sorted(dirty_containers):
        members = sorted(by_container[container_id], key=lambda item: int(item.get("line_index") or 0))
        gate(len(members) == 2, f"relative pair member count {container_id}")
        owners = {owner_u16(item) for item in members}
        gate(len(owners) == 1 and None not in owners, f"relative pair owner drift {container_id}")
        owner = next(iter(owners))
        start, old_blob = live_pair_blob(current, owner)
        old_line1, old_line2 = split_pair(old_blob)
        gate(all(byte == 0 for byte in old_blob[len(old_line1) + len(old_line2) :]), f"pair junk {container_id}")
        new_lines: list[bytes] = []
        texts: list[str] = []
        before_cells: list[int] = []
        live_tokens: dict[str, bytes] = {}
        for member, old_line in zip(members, (old_line1, old_line2)):
            before = str(member.get("translation_ko") or "")
            if before:
                for char, token in live_char_tokens(before, old_line).items():
                    prior = live_tokens.get(char)
                    gate(prior is None or prior == token, f"live token conflict {char!r} in {container_id}")
                    live_tokens[char] = token
        for member, old_line in zip(members, (old_line1, old_line2)):
            before = str(member.get("translation_ko") or "")
            after = after_by_id.get(str(member["record_id"]), before)
            before_cells.append(len(before))
            if after == before:
                encoded_new = old_line
            else:
                encoded_new = encode_desc(after, recovered12, verified12, live_tokens)
            new_lines.append(encoded_new)
            texts.append(after)
            if after != before:
                set_translation_fields(
                    member,
                    after,
                    None,
                    "ID커맨드 설명 17칸 상자 맞춤. 전투시 공백·조사 축약",
                )
        packed = new_lines[0] + new_lines[1]
        write_padded(candidate, start, packed, old_blob, allowed)
        desc_evidence.append(
            {
                "container_id": container_id,
                "owner": f"0x{owner:08X}",
                "payload": f"0x{ROM_BASE + start:08X}",
                "before_cells": before_cells,
                "after": texts,
                "after_cells": [len(item) for item in texts],
                "old_size": len(old_blob),
                "new_size": len(packed),
            }
        )

    leftover = [
        {
            "record_id": row["record_id"],
            "ko": row.get("translation_ko"),
            "len": len(str(row.get("translation_ko") or "")),
        }
        for row in merged["records"]
        if row.get("semantic_category") == "id_command_description"
        and str(row.get("translation_status") or "") == "translated"
        and len(str(row.get("translation_ko") or "")) > MAX_IDCMD_DESC_CELLS
    ]
    gate(not leftover, f"ID desc overflow remains: {leftover[:5]}")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"candidate changed outside allowed bytes: {len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "map-script bank changed")
    gate(MAIN_TIP_ROM.read_bytes() == current, "main TIP mutated during patch")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    overlay_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "map_records": sorted(MAP_JOBS),
            "idcmd_records": sorted(after_by_id),
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["dialogue_idcmd_desc_fit_sha256"] = overlay_identity
    identity["translation_overlay_identity_sha256"] = overlay_identity
    counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged.setdefault("summary", {})["merged_translation_status_counts"] = counts
    merged["summary"]["translation_overlay_identity_sha256"] = overlay_identity
    merged["dialogue_idcmd_desc_fit_20260909"] = {
        "batch_id": BATCH_ID,
        "map_records": sorted(MAP_JOBS),
        "idcmd_records": len(after_by_id),
        "idcmd_pairs": len(dirty_containers),
        "max_idcmd_desc_cells": MAX_IDCMD_DESC_CELLS,
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
        "kind": "ggen_advance_dialogue_idcmd_fit_candidate_20260909",
        "batch_id": BATCH_ID,
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(current),
            "translation_source": advance_relative(TRANSLATION_MERGED_JSON),
        },
        "map_jobs": {
            record_id: {
                "source": job["source"],
                "after": job["new_segments"],
                "notes": job["notes"],
            }
            for record_id, job in MAP_JOBS.items()
        },
        "idcmd": {
            "overflow_before": len(overflow_before),
            "rewritten_records": len(after_by_id),
            "pairs": len(dirty_containers),
            "max_cells": MAX_IDCMD_DESC_CELLS,
        },
        "consumers": {"map": map_evidence, "idcmd_pairs": desc_evidence},
        "output": {"path": advance_relative(OUTPUT), "size": len(candidate), "sha256": sha256(candidate)},
        "sav": {"path": advance_relative(OUT_SAV), "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes()},
        "verification": {
            "result": "PASS",
            "changed_bytes": len(changed),
            "allowed_changed_bytes": len(allowed),
            "map_old_payloads_matched": True,
            "idcmd_old_payloads_matched": True,
            "idcmd_pairs_padded_not_shifted": True,
            "no_idcmd_line_over_17": True,
            "original_map_script_bank_unchanged": True,
            "runtime_emulator": "not run; static ROM/font/payload verification only",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("batch_id", "idcmd", "output", "verification")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
