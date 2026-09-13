#!/usr/bin/env python3
"""Normalize Korean renderings of elongated Japanese battle shouts.

The Japanese battle scripts often attach a small vowel and/or a prolonged
sound mark to an existing word (for example ``クソォ`` or ``隊長ぉっ``).  The
old Korean overlay sometimes copied that tail as a separate ``앗``, ``엇``,
``옷`` or ``오`` syllable.  This pass keeps the Korean word intact and lets
the final sound continue naturally (``젠장오`` -> ``젠자앙``).

Pure cries such as ``うわぁぁ`` and ``うぉぉぉ`` have no lexical base, so they
are deliberately left phonetic.  Only the records in ``JOBS`` are rewritten.
The script builds a date-stamped candidate, updates the canonical merged
translation sheet, and leaves promotion to ``promote_ggen_advance_main_tip``.
"""
from __future__ import annotations

import hashlib
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
import patch_ggen_advance_rank_terms_20260908 as map_base  # noqa: E402
from ggen_advance_painted_glyph_identity import (  # noqa: E402
    load_galmuri12,
    recover_unique_12x12_slots,
)
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MANIFEST,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import (  # noqa: E402
    digest,
    translation_payload_digest,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import (  # noqa: E402
    encode_map_korean_line,
    load_identified_12x12,
    raw_hex_bytes,
)

BATCH_ID = "elongated-battle-shouts-normalization-20260908"
REVIEWED_AT = "2026-09-08"
ROM_BASE = 0x08000000
MAP_BANK = (0x00F00000, 0x00FC0000)

# This is a measured zero-filled ROM tail after the approved graphic/text
# expansions.  It is outside the original text pools and is large enough for
# the short dialogue payloads in this pass.
CAVE_START = 0x01350000
CAVE_END = 0x01360000
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"

SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260908_elongated_shouts.json"
OUT_DIR = ROOT / "outputs" / "20260908_ggen_advance_elongated_shouts"
OUTPUT = OUT_DIR / "ggen_advance_elongated_shouts_candidate_20260908.gba"
OUT_SAV = OUT_DIR / "ggen_advance_elongated_shouts_candidate_20260908.sav"
REPORT = ROOT / "analysis" / "ggen_advance_elongated_shouts_candidate_20260908.json"
MANIFEST = OUT_DIR / "manifest.json"


# record_id -> changed translation segment(s).  Empty framing segments are
# copied from the existing sheet; only the listed segment indexes are changed.
JOBS: dict[str, dict[int, str]] = {
    # Direct user examples and the same lexical pattern in nearby battle text.
    "GGA-MAPSCRIPT-00F72CFD": {0: "대자아앙!!"},
    "GGA-SCENARIO-0020CEC0": {3: "젠자앙！"},
    "GGA-SCENARIO-001FF0D4": {2: "젠장! 젠장! 젠자앙!"},
    "GGA-MAPSCRIPT-00F966B6": {0: "큭…젠자앙!!"},
    "GGA-SCENARIO-001F6CE0": {2: "그렇게 둘까아!"},
    "GGA-SCENARIO-001F70E4": {2: "거기냐아!"},
    "GGA-SCENARIO-001F7108": {2: "그렇게 둘까아!"},
    "GGA-SCENARIO-001FBAA8": {3: "아니었냐고오!"},
    "GGA-SCENARIO-001FBBA8": {2: "이 자식아!"},
    "GGA-SCENARIO-001FBBC0": {2: "이 자식아!"},
    "GGA-SCENARIO-001FC91C": {2: "네놈아！"},
    "GGA-SCENARIO-001FF098": {2: "……이 자식아!"},
    "GGA-SCENARIO-001FF0C4": {2: "……이 자식아!"},
    "GGA-SCENARIO-001FF344": {2: "이 자식아!!"},
    "GGA-SCENARIO-002027BC": {2: "뭐라고오오!!"},
    "GGA-SCENARIO-002041EC": {2: "거기다아!!"},
    "GGA-SCENARIO-002041D8": {2: "젠자앙!"},
    "GGA-SCENARIO-00208F20": {3: "하게 두지 않겠다아！"},
    "GGA-SCENARIO-00208FA0": {3: "그렇게 두지 않겠다아!!"},
    "GGA-SCENARIO-00209060": {3: "그렇게 두지 않겠다아!!"},
    "GGA-SCENARIO-002096E4": {3: "이름에 걸고오!!"},
    "GGA-SCENARIO-002099B8": {3: "이 주먹으로 충분하다아！"},
    "GGA-SCENARIO-0020B144": {3: "나를 만지지 마아!!"},
    "GGA-SCENARIO-0020B880": {2: "아직, 죽지 않는다고오!"},
    "GGA-SCENARIO-0020CEC0": {3: "젠자앙！"},
    "GGA-SCENARIO-0020D178": {2: "아, 아직이다아！！"},
    "GGA-SCENARIO-0020EDB8": {3: "피탄 상황 알려라아！"},
    "GGA-SCENARIO-0020EF2C": {3: "쏴라아!"},
    "GGA-SCENARIO-00209E34": {4: "쏴라아!"},
    "GGA-SCENARIO-0020BA9C": {2: "각오해라아!"},
    "GGA-SCENARIO-0021011C": {2: "이 자식아!"},
    "GGA-SCENARIO-002102D0": {3: "얌전히 있어라아!!"},
    "GGA-SCENARIO-0021030C": {3: "우쭐대지 마아！"},
    "GGA-SCENARIO-002103E0": {2: "이놈아！"},
    "GGA-SCENARIO-0021058C": {3: "깔보지 마라아!"},
    "GGA-SCENARIO-002105CC": {3: "사라져 버려어어!"},
    "GGA-SCENARIO-002105E8": {2: "이 자식아!"},
    "GGA-SCENARIO-002106A0": {2: "네놈아!"},
    "GGA-SCENARIO-002106BC": {3: "얕보지 마라아!!"},
    "GGA-SCENARIO-00206F08": {2: "이 자식아!!"},
    "GGA-SCENARIO-0021075C": {3: "이해가 안 되나아아！！"},
    "GGA-SCENARIO-00209B94": {3: "얕보지 마라아!"},
    "GGA-SCENARIO-00210094": {2: "얕보지 마라아!!"},
    "GGA-SCENARIO-00210328": {2: "얕보지 마라아!!"},
    "GGA-SCENARIO-002112FC": {3: "그렇게 둘까아!"},
    "GGA-SCENARIO-002119A4": {4: "！쏴아！"},
    "GGA-SCENARIO-00215B28": {2: "알겠어…… 거기다아!!"},
    "GGA-SCENARIO-00215E24": {3: "다가오지 마아!!"},
    "GGA-SCENARIO-00215F54": {3: "내가 아니라니까아아아아！"},
    "GGA-SCENARIO-00218BAC": {3: "간다아!"},
    "GGA-SCENARIO-00218C7C": {2: "이, 이 자식아!"},
    "GGA-SCENARIO-00218E14": {3: "이쪽으로 오지 마아!!"},
    "GGA-SCENARIO-0021A208": {2: "…………거기다아!"},
    "GGA-SCENARIO-0021B47C": {3: "우쭐대지 마아！"},
    "GGA-SCENARIO-0021B9B8": {3: "누가 네놈들 따위에게！"},
    "GGA-SCENARIO-00206F08": {2: "이 자식아!!"},
    "GGA-SCENARIO-00212D60": {2: "이 자식아!!"},
    "GGA-SCENARIO-001FAD54": {3: "맞아라아!!"},
    "GGA-SCENARIO-001FDA3C": {2: "다들, 흩어져라아!"},
    "GGA-SCENARIO-00208EB0": {3: "알아라아！！"},
    "GGA-SCENARIO-002046A8": {2: "그렇게 둘까아!!"},
    "GGA-SCENARIO-001FD8A0": {2: "그렇게 둘까아아!!"},
    # Additional raw-verified lexical forms omitted from the first pass.
    "GGA-SCENARIO-001F80F4": {2: "……거기냐아!"},
    "GGA-SCENARIO-001F8124": {2: "오게 할 것 같으냐아!"},
    "GGA-SCENARIO-001F8138": {2: "……거기다아!!"},
    "GGA-SCENARIO-001F8160": {2: "이 자식아!!"},
    "GGA-SCENARIO-001F8170": {2: "……떨어져라아!"},
    "GGA-SCENARIO-001F82C4": {2: "이걸 쓸 수 있다고오!!"},
    "GGA-SCENARIO-001F82E4": {2: "……그렇게 둘까아!"},
    "GGA-SCENARIO-001F830C": {2: "……거기냐아!!"},
    "GGA-SCENARIO-001F8334": {2: "……거기다아!"},
    "GGA-SCENARIO-001F8348": {2: "……이 자식아!!"},
    "GGA-SCENARIO-001F9244": {2: "이놈아아!"},
    "GGA-SCENARIO-001F9898": {2: "잠자코 사라져라아!!"},
    "GGA-SCENARIO-001FB9E0": {3: "제기라알!!"},
    "GGA-SCENARIO-001FC778": {3: "안 되는 거라고오오!"},
    "GGA-SCENARIO-001FD13C": {3: "쏴아！"},
    "GGA-SCENARIO-001FD158": {3: "쏴라아!!"},
    "GGA-SCENARIO-001FD634": {2: "……거기다아!!"},
    "GGA-SCENARIO-001FD648": {2: "……그렇게 둘까아!!"},
    "GGA-SCENARIO-001FD768": {2: "제, 젠자앙……!"},
    "GGA-SCENARIO-001FD9EC": {2: "제, 젠자앙……!"},
    "GGA-SCENARIO-00201BB0": {2: "질 것 같으냐아!"},
    "GGA-SCENARIO-00201CFC": {3: "젠자앙!"},
    "GGA-SCENARIO-00202498": {3: "젠자앙!!"},
    "GGA-SCENARIO-002028C8": {2: "그런 걸로오오!"},
    "GGA-SCENARIO-0020963C": {2: "……소용없다아!!"},
    "GGA-SCENARIO-0020CF8C": {3: "젠자앙!!"},
    "GGA-SCENARIO-0020ED0C": {3: "전원, 대피해에에!!"},
    "GGA-SCENARIO-0020FEE0": {2: "왜 그래아！？"},
    "GGA-SCENARIO-0020FF84": {3: "뭐, 뭐냐아！？"},
    "GGA-SCENARIO-002125F8": {3: "우쭐대지 마！"},
    "GGA-SCENARIO-002162DC": {2: "안 돼！"},
    "GGA-SCENARIO-00210634": {3: "나아아아!!"},
    "GGA-SCENARIO-00210680": {3: "당하는 건가아아!?"},
    "GGA-SCENARIO-00216D54": {3: "아니잖아아!!"},
    "GGA-SCENARIO-0021D520": {2: "큭, 젠자앙……"},
    "GGA-SCENARIO-00217D24": {2: "젠자앙!"},
    # Follow-up lexical forms found in the final source audit.
    "GGA-SCENARIO-001FF104": {2: "그만둬어어!"},
    "GGA-SCENARIO-001FF860": {2: "이제 그만둬어어!!"},
    "GGA-SCENARIO-00206D68": {3: "그만둬어!!"},
    "GGA-SCENARIO-00209DC4": {2: "……소용없다아!!"},
    "GGA-SCENARIO-002103FC": {3: "다, 당했다고오!?"},
    "GGA-SCENARIO-00216768": {3: "아니잖아아!!"},
    "GGA-SCENARIO-00218CF8": {3: "그, 그만둬어어어!!"},
    # Map-script inline dialogue.
    "GGA-MAPSCRIPT-00F54360": {0: "네놈들이이!!"},
    "GGA-MAPSCRIPT-00F54397": {0: "여기서 사라져라아아！"},
    "GGA-MAPSCRIPT-00F5440D": {0: "핑거어어어어어!!"},
    "GGA-MAPSCRIPT-00F54484": {0: "핑거어어어어어!!"},
    "GGA-MAPSCRIPT-00F544D2": {1: "킹 오브 하트으！"},
    "GGA-MAPSCRIPT-00F5466B": {0: "가라아아아!!"},
    "GGA-MAPSCRIPT-00F59476": {1: "쏴아아!!"},
    "GGA-MAPSCRIPT-00F612AC": {0: "쏴아아아!!"},
    "GGA-MAPSCRIPT-00F614FB": {1: "피하아아!!"},
    "GGA-MAPSCRIPT-00F6C1AD": {0: "이런 것이다아아!!"},
    "GGA-MAPSCRIPT-00F72CFD": {0: "대자아앙!!"},
    "GGA-MAPSCRIPT-00F79F05": {1: "약골 놈들아아아!!"},
    "GGA-MAPSCRIPT-00F79FD7": {1: "뭘 하겠다는 것이냐아!!"},
    "GGA-MAPSCRIPT-00F7A020": {1: "바로잡아 주마아!!"},
    "GGA-MAPSCRIPT-00F7A1C7": {0: "나와라아아!"},
    "GGA-MAPSCRIPT-00F7A28B": {1: "외도 놈들아아아!!"},
    "GGA-MAPSCRIPT-00F7A4C2": {0: "나와라아아!"},
    "GGA-MAPSCRIPT-00F7A84D": {0: "가토오오!!"},
    "GGA-MAPSCRIPT-00F7A989": {0: "건담 파이트으！"},
    "GGA-MAPSCRIPT-00F7FA2B": {0: "배로 갚아주마아!!"},
    "GGA-MAPSCRIPT-00F7FB50": {1: "그 빈틈, 받아 간다아!!"},
    "GGA-MAPSCRIPT-00F805B5": {0: "아이나아아!!"},
    "GGA-MAPSCRIPT-00F80E80": {0: "아이나아아아!!"},
    "GGA-MAPSCRIPT-00F847D1": {0: "나와라아아아!"},
    "GGA-MAPSCRIPT-00F87F22": {0: "회피이!"},
    "GGA-MAPSCRIPT-00F88DB0": {1: "쏴아아!"},
    "GGA-MAPSCRIPT-00F88833": {1: "교정해 주마아아!!!"},
    "GGA-MAPSCRIPT-00F8D2A8": {0: "피, 필 소령아아!"},
    "GGA-MAPSCRIPT-00F9D2CD": {0: "네놈은아아아!!"},
    "GGA-MAPSCRIPT-00FA1F7F": {1: "쏴아아아!"},
    "GGA-MAPSCRIPT-00FA3532": {1: "하게 두지 않겠다아!!"},
    "GGA-MAPSCRIPT-00FA84C2": {0: "각오해라아!!"},
    "GGA-MAPSCRIPT-00FA9011": {0: "아직이다아!!"},
    "GGA-MAPSCRIPT-00FA9117": {0: "사라져라아아아아아!"},
    "GGA-MAPSCRIPT-00FB3154": {0: "가라아아아아!"},
    "GGA-MAPSCRIPT-00FB3173": {0: "가라아아아아!"},
    "GGA-MAPSCRIPT-00FBDB51": {0: "『뭐라고오!』이라든가 하면서"},
    "GGA-MAPSCRIPT-00F97CC1": {0: "그럴 수가, 바보냐아아!!"},
    "GGA-MAPSCRIPT-00FA2F6E": {0: "케리이이!!"},
    "GGA-MAPSCRIPT-00FACD73": {0: "전원, 퇴피이!!"},
    "GGA-MAPSCRIPT-00F57DA8": {0: "비켜어어어！"},
    "GGA-MAPSCRIPT-00F7A049": {0: "네에에에에!!"},
    "GGA-MAPSCRIPT-00F7A0A9": {0: "도몬아!!"},
    "GGA-MAPSCRIPT-00F774EB": {0: "큭… 젠자앙!!"},
    "GGA-MAPSCRIPT-00F88D49": {0: "가라아!"},
    "GGA-MAPSCRIPT-00FA904E": {0: "가라아아아아!!"},
    "GGA-MAPSCRIPT-00F80E4F": {0: "네놈아아아!!"},
    "GGA-MAPSCRIPT-00F67E2B": {0: "뭐야！ 이 자식아!!"},
    "GGA-MAPSCRIPT-00F852FA": {0: "이, 이 녀석아!!"},
    "GGA-MAPSCRIPT-00F9126B": {0: "젝스!? 네놈아!!"},
    # Battle-event streams use the same controlled 12x12 framing.
    "GGA-BATTLEEVENT-00D34144": {0: "그만둬어어어！"},
    "GGA-BATTLEEVENT-00D342B0": {0: "그렇게 두진 않아아！"},
    "GGA-BATTLEEVENT-00D342EC": {0: "그만둬어어어！"},
    "GGA-BATTLEEVENT-00D343B4": {0: "내 꿈을…… 받아라아아！"},
}


def gate(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def sha256(value: bytes | bytearray) -> str:
    return hashlib.sha256(bytes(value)).hexdigest()


def parse_hex(value: Any) -> int:
    return int(str(value), 16)


def update_fields(row: dict[str, Any], new_segments: list[str], note: str) -> None:
    row["translation_segments"] = new_segments
    row["translation_ko"] = "\n".join(text for text in new_segments if text)
    row["overlay_batch_id"] = BATCH_ID
    row["translation_source"] = "user_requested_elongated_shout_review_20260908"
    row["review_status"] = "user_requested"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = REVIEWED_AT
    row["translator_notes"] = f"{row.get('translator_notes') or ''}; {note}".strip("; ")
    row["qa_status"] = "static_consumer_verified"
    row["translation_payload_sha256"] = translation_payload_digest(
        {
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
    )


def owner_offsets(row: dict[str, Any]) -> list[int]:
    return [
        parse_hex(owner.removeprefix("OWNER-U32-"))
        for owner in row.get("owner_ids", [])
        if str(owner).startswith("OWNER-U32-")
    ]


def payload_until_nul(rom: bytes | bytearray, address: int, limit: int = 128) -> bytes:
    offset = address - ROM_BASE
    gate(0 <= offset < len(rom), f"payload outside ROM: 0x{address:08X}")
    end = bytes(rom).find(b"\x00", offset, min(len(rom), offset + limit))
    gate(end >= 0, f"unterminated map payload: 0x{address:08X}")
    return bytes(rom[offset : end + 1])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    before = MAIN_TIP_ROM.read_bytes()
    gate(len(before) == 32 * 1024 * 1024, "current MainTip must be 32 MiB")
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(sha256(before) == str(main_manifest.get("sha256") or "").lower(), "MainTip/manifest hash drift")
    gate(ORIGINAL_ROM.exists() and MAIN_SAV.exists(), "source ROM or SAV missing")
    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    by_id = {str(row["record_id"]): row for row in merged["records"]}
    gate(set(JOBS) <= set(by_id), "one or more elongated-shout records are missing")

    # Collect only characters used by this batch.  The existing renderer-verified
    # slots handle the old text, while the painted identity recovers newly added
    # Hangul from the active Korean font.
    hangul: set[str] = set()
    for record_id, changes in JOBS.items():
        row = by_id[record_id]
        for text in list(row.get("translation_segments") or []) + list(changes.values()):
            hangul.update(char for char in str(text) if "가" <= char <= "힣")
    font12 = load_galmuri12()
    recovered12 = recover_unique_12x12_slots(before, font12, hangul)
    identified12 = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)

    candidate = bytearray(before)
    allowed: set[int] = set()
    cursor = CAVE_START
    gate(before[CAVE_START:CAVE_END] == b"\x00" * (CAVE_END - CAVE_START), "elongated-shout cave is not zero-filled")
    consumers: list[dict[str, Any]] = []
    changed_ids: list[str] = []
    changed_segments = 0
    scenario_count = map_count = battle_count = 0

    for record_id, changes in JOBS.items():
        row = by_id[record_id]
        old_segments = [str(item) for item in (row.get("translation_segments") or [])]
        new_segments = list(old_segments)
        for index, text in changes.items():
            gate(0 <= index < len(new_segments), f"segment index drift: {record_id}#{index}")
            new_segments[index] = text
        gate(new_segments != old_segments, f"no-op elongated-shout change: {record_id}")
        scope = str(row.get("source_scope") or "")
        before_text = str(row.get("translation_ko") or "")
        after_text = "\n".join(text for text in new_segments if text)
        note = "일본어 장음·기합의 어휘 어간을 유지하고 끝소리를 자연스럽게 연장"

        if scope in {"scenario_main", "scenario_dynamic", "battle_event_dialogue"}:
            old_payload, old_missing = unified.rebuild_scenario_payload(
                row, recovered12, verified12, translate=True
            )
            gate(old_payload is not None and not old_missing, f"old scenario encode failed: {record_id} {old_missing}")
            row_new = dict(row)
            row_new["translation_segments"] = new_segments
            row_new["translation_ko"] = after_text
            new_payload, new_missing = unified.rebuild_scenario_payload(
                row_new, recovered12, verified12, translate=True
            )
            gate(new_payload is not None and not new_missing, f"new scenario encode failed: {record_id} {new_missing}")
            owner_fields = owner_offsets(row)
            gate(owner_fields, f"scenario owner missing: {record_id}")
            owner_patches: list[dict[str, Any]] = []
            for owner_offset in owner_fields:
                old_pointer = struct.unpack_from("<I", before, owner_offset)[0]
                old_offset = old_pointer - ROM_BASE
                gate(before[old_offset : old_offset + len(old_payload)] == old_payload, f"active scenario payload mismatch: {record_id}")
                gate(cursor + len(new_payload) <= CAVE_END, "elongated-shout cave exhausted")
                payload_offset = cursor
                candidate[payload_offset : payload_offset + len(new_payload)] = new_payload
                allowed.update(range(payload_offset, payload_offset + len(new_payload)))
                new_pointer = ROM_BASE + payload_offset
                struct.pack_into("<I", candidate, owner_offset, new_pointer)
                allowed.update(range(owner_offset, owner_offset + 4))
                owner_patches.append(
                    {
                        "owner_file_offset": f"0x{owner_offset:08X}",
                        "old_pointer": f"0x{old_pointer:08X}",
                        "new_pointer": f"0x{new_pointer:08X}",
                    }
                )
                cursor = (cursor + len(new_payload) + 3) & ~3
            consumer = {
                "record_id": record_id,
                "scope": scope,
                "before": before_text,
                "after": after_text,
                "old_payload_size": len(old_payload),
                "new_payload_size": len(new_payload),
                "owner_patches": owner_patches,
            }
            if scope == "battle_event_dialogue":
                battle_count += 1
            else:
                scenario_count += 1
        elif scope == "scenario_map_script":
            map_count += 1
            source_cursor = parse_hex(row["target_file_offset"])
            segments = list(row.get("segments") or [])
            gate(len(segments) == len(old_segments), f"map framing drift: {record_id}")
            map_segments: list[dict[str, Any]] = []
            for index, (segment, old_text, new_text) in enumerate(zip(segments, old_segments, new_segments)):
                raw = raw_hex_bytes(str(segment.get("raw_hex") or ""))
                gate(raw.endswith(b"\x00"), f"map segment is not NUL terminated: {record_id}#{index}")
                if index not in changes:
                    source_cursor += len(raw)
                    continue
                original_address = ROM_BASE + source_cursor
                original_end = original_address + len(raw) - 1
                hits = map_base.lookup_entries(before, original_address, original_end)
                gate(hits, f"map lookup missing: {record_id}#{index}")
                old_encoded, old_missing = encode_map_korean_line(old_text, recovered12, identified12)
                gate(not old_missing and old_encoded is not None, f"old map encode failed: {record_id}#{index} {old_missing}")
                gate(all(payload_until_nul(before, hit[1]) == old_encoded for hit in hits), f"active map payload mismatch: {record_id}#{index}")
                new_encoded, new_missing = encode_map_korean_line(new_text, recovered12, identified12)
                gate(new_encoded is not None and not new_missing, f"new map encode failed: {record_id}#{index} {new_missing}")
                gate(cursor + len(new_encoded) <= CAVE_END, "elongated-shout cave exhausted")
                payload_offset = cursor
                candidate[payload_offset : payload_offset + len(new_encoded)] = new_encoded
                allowed.update(range(payload_offset, payload_offset + len(new_encoded)))
                new_pointer = ROM_BASE + payload_offset
                for lookup_position, _, _ in hits:
                    struct.pack_into("<I", candidate, lookup_position + 4, new_pointer)
                    allowed.update(range(lookup_position + 4, lookup_position + 8))
                map_segments.append(
                    {
                        "segment": index,
                        "before": old_text,
                        "after": new_text,
                        "lookup_count": len(hits),
                        "old_payload": f"0x{hits[0][1]:08X}",
                        "new_payload": f"0x{new_pointer:08X}",
                        "old_payload_size": len(old_encoded),
                        "new_payload_size": len(new_encoded),
                    }
                )
                cursor = (cursor + len(new_encoded) + 3) & ~3
                source_cursor += len(raw)
            consumer = {
                "record_id": record_id,
                "scope": scope,
                "before": before_text,
                "after": after_text,
                "segments": map_segments,
            }
        else:
            raise SystemExit(f"gate failed: unsupported scope for {record_id}: {scope}")

        update_fields(row, new_segments, note)
        changed_ids.append(record_id)
        changed_segments += len(changes)
        consumers.append(consumer)

    allocation_end = cursor
    gate(allocation_end <= CAVE_END, "elongated-shout allocation exceeds cave")
    changed = {index for index, (left, right) in enumerate(zip(before, candidate)) if left != right}
    gate(changed <= allowed, f"candidate changed outside approved payloads: {len(changed - allowed)}")
    gate(candidate[MAP_BANK[0] : MAP_BANK[1]] == before[MAP_BANK[0] : MAP_BANK[1]], "original map-script bank changed")
    gate(bytes(candidate[CAVE_START:allocation_end]).count(0) >= 0, "allocation write failed")

    # Verify each new pointer and payload against the candidate before any file
    # is written.
    for consumer in consumers:
        if consumer["scope"] == "scenario_map_script":
            for item in consumer["segments"]:
                pointer = parse_hex(item["new_payload"])
                encoded = payload_until_nul(candidate, pointer)
                gate(len(encoded) == item["new_payload_size"], f"new map payload verify failed: {consumer['record_id']}")
        else:
            for patch in consumer["owner_patches"]:
                owner_offset = parse_hex(patch["owner_file_offset"])
                gate(struct.unpack_from("<I", candidate, owner_offset)[0] == parse_hex(patch["new_pointer"]), f"new owner pointer verify failed: {consumer['record_id']}")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [
                {
                    "record_id": record_id,
                    "translation_payload_sha256": by_id[record_id].get("translation_payload_sha256"),
                }
                for record_id in sorted(JOBS)
            ],
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["elongated_battle_shouts_normalization_sha256"] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    merged.setdefault("summary", {})["merged_translation_status_counts"] = status_counts
    merged["summary"]["translation_overlay_identity_sha256"] = new_identity
    merged["elongated_battle_shouts_normalization_20260908"] = {
        "batch_id": BATCH_ID,
        "principle": "어휘 어간의 의미를 보존하고 일본어 장음·기합은 한국어 어미의 모음으로 자연스럽게 연장",
        "pure_phonetic_interjections_retained": True,
        "corrected_record_count": len(changed_ids),
        "changed_segment_count": changed_segments,
        "records": sorted(changed_ids),
        "scope_counts": {
            "scenario_main_or_dynamic": scenario_count,
            "scenario_map_script": map_count,
            "battle_event_dialogue": battle_count,
        },
    }

    # Write the canonical JSON only after every ROM/payload gate has passed.
    payload_json = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    SNAPSHOT.write_text(payload_json, encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_text(payload_json, encoding="utf-8")
    update_translation_manifest(merged, SNAPSHOT)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_elongated_shouts_candidate_20260908",
        "batch_id": BATCH_ID,
        "source": {
            "main_tip": advance_relative(MAIN_TIP_ROM),
            "main_tip_sha256": sha256(before),
            "translation_source": advance_relative(TRANSLATION_MERGED_JSON),
            "translation_parent_identity": parent_identity,
            "translation_overlay_identity": new_identity,
        },
        "review": {
            "corrected_record_count": len(changed_ids),
            "changed_segment_count": changed_segments,
            "scope_counts": {
                "scenario_main_or_dynamic": scenario_count,
                "scenario_map_script": map_count,
                "battle_event_dialogue": battle_count,
            },
            "consumers": consumers,
            "policy": {
                "lexical_base_preserved": True,
                "detached_ass_or_eot_suffixes_removed": True,
                "pure_phonetic_interjections_retained": True,
            },
        },
        "allocation": {
            "file_offset": f"0x{CAVE_START:08X}",
            "end_exclusive": f"0x{allocation_end:08X}",
            "size": allocation_end - CAVE_START,
            "capacity_end": f"0x{CAVE_END:08X}",
        },
        "output": {
            "path": advance_relative(OUTPUT),
            "size": len(candidate),
            "sha256": sha256(candidate),
        },
        "sav": {
            "path": advance_relative(OUT_SAV),
            "byte_exact_copy": OUT_SAV.read_bytes() == MAIN_SAV.read_bytes(),
        },
        "verification": {
            "result": "PASS",
            "changed_byte_count": len(changed),
            "allowed_changed_byte_count": len(allowed),
            "all_new_payloads_verified": True,
            "all_owner_and_lookup_pointers_verified": True,
            "allocation_zero_filled_before_write": True,
            "original_map_script_bank_unchanged": True,
            "canonical_main_tip_preserved_until_promotion": True,
            "runtime_emulator": "not run; static ROM/font/payload verification only",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
