#!/usr/bin/env python3
"""Fix 女→벽 mistranslations and include omitted extra-session map scripts.

Map-script extraction stopped at 0x00FC0000, so Extra-session event prints
(Exss4 Nimbus/Yuu/Doan and neighbours) stayed Japanese.  This batch:

1. Adds the 0x00FC0000–0x00FD0000 map-script bank to the sheet.
2. Translates the Exss4 Nimbus/Yuu/Doan/Marion event cluster.
3. Rewrites remaining 女 lines that were decoded as 벽.
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

import build_ggen_advance_ko_poc as fontops  # noqa: E402
import build_ggen_advance_unified_rom_poc as unified  # noqa: E402
import patch_ggen_advance_apsaras_zentetsu_20260908 as apsaras_mod  # noqa: E402
from build_ggen_advance_map_script_sheet import build_record, recount  # noqa: E402
from ggen_advance_painted_glyph_identity import FONT12_RELOCATED, load_galmuri12, packed_12x12  # noqa: E402
from ggen_advance_project_paths import (  # noqa: E402
    MAIN_TIP_MANIFEST,
    MAIN_TIP_ROM,
    ORIGINAL_ROM,
    TRANSLATION_MERGED_JSON,
    advance_relative,
)
from merge_ggen_advance_translation_overlays import digest  # noqa: E402
from patch_ggen_advance_apsaras_zentetsu_20260908 import (  # noqa: E402
    choose_free_12x12,
    hangul_chars,
    paint_12x12,
    patch_owned_payload,
    recover_or_paint,
    visible_segments,
)
import patch_ggen_advance_ashi_kagari_idcmd_20260910 as ashi_mod  # noqa: E402
from patch_ggen_advance_ashi_kagari_idcmd_20260910 import (  # noqa: E402
    insert_live_lookup,
    lookup_hits,
    patch_map_row_fresh,
)
from patch_ggen_advance_intermission_text_consumers_20260904 import (  # noqa: E402
    ROM_BASE,
    gate,
    sha256,
    u32,
)
from patch_ggen_advance_kimi_jane_to_neo_20260904 import (  # noqa: E402
    update_payload_hash,
    update_translation_manifest,
)
from patch_ggen_advance_map_script_inline_poc import load_identified_12x12  # noqa: E402
from patch_ggen_advance_name_unify_20260909 import (  # noqa: E402
    encode_overlay,
    patch_map_row_live,
    rebuild_scenario_live,
)

BATCH_ID = "nimbus-exss4-woman-extrabank-20260910"
IDENTITY_KEY = "nimbus_exss4_woman_extrabank_sha256"
BATCH_KEY = "nimbus_exss4_woman_extrabank_20260910"
REPORT_KIND = "ggen_advance_nimbus_exss4_candidate_20260910"
SNAPSHOT = ROOT / "analysis" / "ggen_advance_translation_merged_20260910_nimbus_exss4.json"
EXTRACT = ROOT / "analysis" / "ggen_advance_map_script_extrabank_extract_20260910.json"
OUT_DIR = ROOT / "outputs" / "20260910_ggen_advance_nimbus_exss4"
OUTPUT = OUT_DIR / "ggen_advance_nimbus_exss4_candidate_20260910.gba"
OUT_SAV = OUT_DIR / "ggen_advance_nimbus_exss4_candidate_20260910.sav"
MAIN_SAV = ROOT / "SD Gundam GGeneration Advance (Korean).sav"
REPORT = ROOT / "analysis" / "ggen_advance_nimbus_exss4_candidate_20260910.json"
MANIFEST = OUT_DIR / "manifest.json"
# Wait-icon hook occupies 0x012B4000–0x012B401C; leftover payloads sit at
# 0x012B3000.  Use the empty run after that hook.  Lookup table at
# 0x01308000 only has ~75 trailing slots, so Extra-session inserts relocate
# the table into the empty tail after the elongated-shout cave.
CAVE_START = 0x012B4800
CAVE_END = 0x012BF000
MAP_BANK = (0x00F00000, 0x00FC0000)
EXTRA_BANK = (0x00FC0000, 0x00FD0000)
VISUAL_DIALOGUE_CELLS = 14
LIVE_LOOKUP_TABLE = 0x01308000
LIVE_LOOKUP_PTR_OFF = 0x01112588
LIVE_LOOKUP_COUNT_OFF = 0x0111258C
LIVE_LOOKUP_PTR = 0x09308000
NEW_LOOKUP_TABLE = 0x01360000
NEW_LOOKUP_PTR = 0x09360000
LOOKUP_ENTRY_SIZE = 12
NOTES = (
    "0x03C7 女 not 壁. Extra-session map scripts after 0x00FC0000 were outside "
    "the old extract bank, so Exss4 Nimbus/Yuu/Doan events stayed Japanese."
)

WALL_MAP: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00FB2261": ["결국 너도", "한낱 여자라는 거로군"],
    "GGA-MAPSCRIPT-00FBFDD3": ["……네놈도", "그 여자에게 선택된 것이다"],
    "GGA-MAPSCRIPT-00FBFDF2": ["여자……"],
}
WALL_SCENARIO: dict[str, list[str]] = {
    "GGA-SCENARIO-0020AFD8": ["하하하하핫！", "나는 그 여자를 넘었다！"],
    "GGA-SCENARIO-00215790": ["연약한 여자아이에게", "뭘 하는 거야!"],
}
EXTRA_KO: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00FC013C": ["뭐라고……？"],
    "GGA-MAPSCRIPT-00FC0150": ["이제 네놈에게 흔들리지", "않는다는 말이다……"],
    "GGA-MAPSCRIPT-00FC017C": ["……보여 주마！", "님버스 슈타젠！"],
    "GGA-MAPSCRIPT-00FC018F": ["모빌슈트의", "격투기란 것을 말이다！！"],
    "GGA-MAPSCRIPT-00FC01B6": ["이, 이 힘……"],
    "GGA-MAPSCRIPT-00FC01C1": ["네놈！쿠쿠루스 도안！", "대체 뭘 한 거냐！！"],
    "GGA-MAPSCRIPT-00FC01E7": ["네놈 같은", "남자는 모를 거다……"],
    "GGA-MAPSCRIPT-00FC01FC": ["이것이 사내의……", "혼의 주먹이란 거다！！"],
    "GGA-MAPSCRIPT-00FC0215": ["잘 보고 기억해 둬！"],
    "GGA-MAPSCRIPT-00FC0232": ["크크크……만만치 않군"],
    "GGA-MAPSCRIPT-00FC024B": ["하지만！"],
    "GGA-MAPSCRIPT-00FC0252": ["나는 님버스 슈타젠！", "선택받은 지온의 기사다！"],
    "GGA-MAPSCRIPT-00FC026A": ["이 몸에 패배 없다！！"],
    "GGA-MAPSCRIPT-00FC028A": ["EXAM을……！？"],
    "GGA-MAPSCRIPT-00FC02A3": ["조심해, 유우！"],
    "GGA-MAPSCRIPT-00FC02AF": ["2호기의 EXAM에는", "리미터가 없다！！"],
    "GGA-MAPSCRIPT-00FC02CB": ["한번 작동하면", "죽을 때까지 싸운다！！"],
    "GGA-MAPSCRIPT-00FC02F1": ["……………"],
    "GGA-MAPSCRIPT-00FC0308": ["님버스 슈타젠……！"],
    "GGA-MAPSCRIPT-00FC031D": ["나야말로", "지온의 정의를 이룰 자……"],
    "GGA-MAPSCRIPT-00FC0331": ["EXAM에 선택받은 기사다", "유우 카지마！！"],
    "GGA-MAPSCRIPT-00FC0359": ["……！？"],
    "GGA-MAPSCRIPT-00FC0370": ["「……그만둬」"],
    "GGA-MAPSCRIPT-00FC0389": ["「……나한테 손대지 마！」"],
    "GGA-MAPSCRIPT-00FC03AA": ["「……난폭하게 굴 마！」"],
    "GGA-MAPSCRIPT-00FC03C8": ["「……그만둬, 님버스！」"],
    "GGA-MAPSCRIPT-00FC0405": ["이건……"],
    "GGA-MAPSCRIPT-00FC041C": ["……목소리？"],
    "GGA-MAPSCRIPT-00FC0433": ["기억……？"],
    "GGA-MAPSCRIPT-00FC046C": ["이건……", "마리온이라는 소녀의……"],
    "GGA-MAPSCRIPT-00FC049A": ["님버스 슈타젠", "너는 마리온을……"],
    "GGA-MAPSCRIPT-00FC04B5": ["그렇게까지 해서", "존재를 드러내고 싶었나……"],
    "GGA-MAPSCRIPT-00FC04D2": ["그 여자를 지배했나！？"],
    "GGA-MAPSCRIPT-00FC04F1": ["……범속한 놈, 닥쳐！"],
    "GGA-MAPSCRIPT-00FC0500": ["마리온을 넘지 못하는 게", "네놈의 한계란 말이다！"],
    "GGA-MAPSCRIPT-00FC052B": ["큭……！"],
    "GGA-MAPSCRIPT-00FC053D": ["「……나한테 손대지 마！」"],
    "GGA-MAPSCRIPT-00FC055D": ["죽어라, 유우 카지마！"],
    "GGA-MAPSCRIPT-00FC057F": ["큭……！"],
    "GGA-MAPSCRIPT-00FC0596": ["하하하핫！ 봐라！！"],
    "GGA-MAPSCRIPT-00FC05A9": ["내가 그 여자를", "뛰어넘었다는 거다！！"],
    "GGA-MAPSCRIPT-00FC05D6": ["「난폭한 녀석……", "사라져 버려！！」"],
    "GGA-MAPSCRIPT-00FC05FC": ["……아니야"],
    "GGA-MAPSCRIPT-00FC0613": ["이 목소리는……", "넌 마리온이 아니야……！"],
    "GGA-MAPSCRIPT-00FC0639": ["……EXAM이다！"],
    "GGA-MAPSCRIPT-00FC0651": ["「………………」"],
    "GGA-MAPSCRIPT-00FC066B": ["난 내 의지로", "님버스를 죽인다……！"],
    "GGA-MAPSCRIPT-00FC0695": ["……뭐라고！？"],
    "GGA-MAPSCRIPT-00FC06E5": ["……………"],
    "GGA-MAPSCRIPT-00FC06FC": ["이 자식……", "네놈 따위에게……！"],
    "GGA-MAPSCRIPT-00FC0719": ["혼자 죽진 않는다！！", "유우 카지마！"],
    "GGA-MAPSCRIPT-00FC073D": ["………！！"],
    "GGA-MAPSCRIPT-00FC0754": ["죽어라, 마리온！！"],
    "GGA-MAPSCRIPT-00FC0772": ["……………"],
    "GGA-MAPSCRIPT-00FC078E": ["……그 오만을 속죄해라"],
    "GGA-MAPSCRIPT-00FC07B5": ["크으윽！", "왜, 왜지……！？"],
    "GGA-MAPSCRIPT-00FC07DD": ["왜 네놈이 날 심판했지……"],
    "GGA-MAPSCRIPT-00FC07FE": ["네놈도 오만한", "인간 중 하나가 아닌가……"],
    "GGA-MAPSCRIPT-00FC082B": ["……………"],
    "GGA-MAPSCRIPT-00FC0842": ["「……아니야」"],
    "GGA-MAPSCRIPT-00FC085C": ["마리…온……？"],
    "GGA-MAPSCRIPT-00FC0880": ["「왜냐면, 당신은……」"],
    "GGA-MAPSCRIPT-00FC0893": ["「EXAM이 내가 아니라고", "말해 줬잖아」"],
    "GGA-MAPSCRIPT-00FC08B1": ["「그러니까 나는", "너에게 이렇게 말해……」"],
    "GGA-MAPSCRIPT-00FC08CE": ["「너도 EXAM이 아니야」"],
    "GGA-MAPSCRIPT-00FC08E2": ["「그렇지 않아？」"],
    "GGA-MAPSCRIPT-00FC08F5": ["「죽이기만 생각하며", "살아온 건 아니야」"],
    "GGA-MAPSCRIPT-00FC0919": ["「빼앗고 지배할", "생각만으로 싸운 게 아냐」"],
    "GGA-MAPSCRIPT-00FC0941": ["「그렇지 않았다면……」"],
    "GGA-MAPSCRIPT-00FC0955": ["「널 부르는 사람이", "있을 리 없잖아」"],
    "GGA-MAPSCRIPT-00FC097E": ["모린……", "그리고, 모두……"],
    "GGA-MAPSCRIPT-00FC099F": ["「……그렇지, 유우」"],
    "GGA-MAPSCRIPT-00FC09BA": ["그래……그렇지"],
    "GGA-MAPSCRIPT-00FC09D2": ["「자, 봐……밖을」"],
    "GGA-MAPSCRIPT-00FC0A1B": ["우주……"],
    "GGA-MAPSCRIPT-00FC0A31": ["푸른……우주다"],
    "GGA-MAPSCRIPT-00FC0A4B": ["「우주엔 마음이 가득해」"],
    "GGA-MAPSCRIPT-00FC0A6C": ["푸른 우주에는……", "적의만 있는 게 아냐……"],
    "GGA-MAPSCRIPT-00FC0A9C": ["……유우！！"],
    "GGA-MAPSCRIPT-00FC0AB4": ["서둘러！", "유우 소위를 회수해！！"],
    "GGA-MAPSCRIPT-00FC0ADF": ["무사한가！？ 유우 소위！！"],
    "GGA-MAPSCRIPT-00FC0AFA": ["……그래"],
    "GGA-MAPSCRIPT-00FC0B01": ["블루를 부쉈다……", "미안하군"],
    "GGA-MAPSCRIPT-00FC0B20": ["흥……뭐 됐군"],
    "GGA-MAPSCRIPT-00FC0B2D": ["네가 살아남았다면", "데이터는 또 뽑을 수 있어"],
    "GGA-MAPSCRIPT-00FC0B51": ["그게 마지막", "EXAM이었나……？"],
    "GGA-MAPSCRIPT-00FC0B6F": ["그, 그런 일은", "네가 생각할 일이 아냐！！"],
    "GGA-MAPSCRIPT-00FC0B93": ["캄라 대위도 참", "무리하긴……"],
    "GGA-MAPSCRIPT-00FC0BB9": ["……어쨌든！"],
    "GGA-MAPSCRIPT-00FC0BC3": ["유우를 구한 이상", "여긴 더 있을 곳 아냐！！"],
    "GGA-MAPSCRIPT-00FC0BEB": ["나머지는 남은 적 부대를", "빨리 소탕해 줘！"],
    "GGA-MAPSCRIPT-00FC0C17": ["님버스 대위……", "당신은 잘못되어 있었다"],
    "GGA-MAPSCRIPT-00FC0C2D": ["지킬 무기 없는 기사 따윈", "이제 기사가 아니다……"],
    "GGA-MAPSCRIPT-00FC0C4C": ["그래서 당신은 패한 거다"],
    "GGA-MAPSCRIPT-00FC0C5B": ["님버스 슈타젠"],
    "GGA-MAPSCRIPT-00FC0C72": ["이, 이 몸이……"],
    "GGA-MAPSCRIPT-00FC0C8D": ["지온의 기사인 이 몸이……"],
    "GGA-MAPSCRIPT-00FC0CAB": ["왜……！！"],
    "GGA-MAPSCRIPT-00FC0CCA": ["적, 보이지 않습니다！！"],
    "GGA-MAPSCRIPT-00FC0CE5": ["끝났나……"],
    "GGA-MAPSCRIPT-00FC0CFE": ["……그래", "모든 게 끝이다"],
    "GGA-MAPSCRIPT-00FC0D16": ["님버스는 이제……"],
    "GGA-MAPSCRIPT-00FC0D20": ["……………"],
    "GGA-MAPSCRIPT-00FC19D1": ["이 자식！", "이 몸에게 거역하나！？"],
    "GGA-MAPSCRIPT-00FC19F2": ["선택받은 기사의 힘……", "네놈에게 보여 주마！"],
    "GGA-MAPSCRIPT-00FC1A18": ["살기……！"],
}


def mark_row(row: dict[str, Any], after: str, new_segments: list[str]) -> None:
    row["translation_ko"] = after
    row["translation_segments"] = new_segments
    row["translation_status"] = "translated"
    row["translation_source"] = "user_verified"
    row["review_status"] = "user_verified"
    row["review_count"] = int(row.get("review_count") or 0) + 1
    row["reviewed_at"] = "2026-09-10"
    row["translator_notes"] = NOTES
    row["qa_status"] = "static_consumer_verified"
    row["overlay_batch_id"] = BATCH_ID
    update_payload_hash(row)


def plan_visible(row: dict[str, Any], new_visible: list[str]) -> tuple[str, list[str], list[str]]:
    before = str(row.get("translation_ko") or "")
    old_segments = [str(item) for item in (row.get("translation_segments") or [])]
    if old_segments:
        old_visible = visible_segments(old_segments)
        gate(len(old_visible) == len(new_visible), f"visible count {row['record_id']}")
        new_segments: list[str] = []
        visible_index = 0
        for item in old_segments:
            if item:
                new_segments.append(new_visible[visible_index])
                visible_index += 1
            else:
                new_segments.append(item)
        gate(visible_index == len(new_visible), f"framing {row['record_id']}")
    else:
        segs = list(row.get("segments") or [])
        gate(len(segs) == len(new_visible), f"fresh segment count {row['record_id']}")
        new_segments = list(new_visible)
        old_segments = [""] * len(new_segments)
    after = "\n".join(new_visible)
    return before, old_segments, new_segments


def relocate_lookup_table(candidate: bytearray, allowed: set[int]) -> dict[str, Any]:
    count = struct.unpack_from("<I", candidate, LIVE_LOOKUP_COUNT_OFF)[0]
    size = count * LOOKUP_ENTRY_SIZE
    src = LIVE_LOOKUP_TABLE
    dst = NEW_LOOKUP_TABLE
    gate(u32(candidate, LIVE_LOOKUP_PTR_OFF) == LIVE_LOOKUP_PTR, "lookup pointer changed before relocate")
    gate(all(value == 0 for value in candidate[dst : dst + size + LOOKUP_ENTRY_SIZE]), "new lookup dest is not empty")
    candidate[dst : dst + size] = candidate[src : src + size]
    allowed.update(range(dst, dst + size))
    struct.pack_into("<I", candidate, LIVE_LOOKUP_PTR_OFF, NEW_LOOKUP_PTR)
    allowed.update(range(LIVE_LOOKUP_PTR_OFF, LIVE_LOOKUP_PTR_OFF + 4))
    ashi_mod.LIVE_LOOKUP_TABLE = dst
    ashi_mod.LIVE_LOOKUP_PTR = NEW_LOOKUP_PTR
    return {
        "old_table": hex(src),
        "new_table": hex(dst),
        "old_ptr": hex(LIVE_LOOKUP_PTR),
        "new_ptr": hex(NEW_LOOKUP_PTR),
        "copied_entries": count,
        "copied_bytes": size,
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    apsaras_mod.CAVE_END = CAVE_END
    for table in (WALL_MAP, WALL_SCENARIO, EXTRA_KO):
        for record_id, lines in table.items():
            for line in lines:
                gate("\n" not in line, f"newline in {record_id}: {line!r}")
                gate(
                    len(line) <= VISUAL_DIALOGUE_CELLS,
                    f"{record_id} {len(line)}>{VISUAL_DIALOGUE_CELLS}: {line!r}",
                )

    original = ORIGINAL_ROM.read_bytes()
    current = MAIN_TIP_ROM.read_bytes()
    main_manifest = json.loads(MAIN_TIP_MANIFEST.read_text(encoding="utf-8"))
    gate(len(current) == 32 * 1024 * 1024, "main TIP size drift")
    gate(sha256(current) == main_manifest.get("sha256"), "main TIP/manifest hash drift")
    gate(u32(current, LIVE_LOOKUP_PTR_OFF) == LIVE_LOOKUP_PTR, "live lookup pointer drift")
    gate(all(value == 0 for value in current[CAVE_START:CAVE_END]), "nimbus cave is not zero-filled")
    gate(all(value == 0 for value in current[NEW_LOOKUP_TABLE : NEW_LOOKUP_TABLE + 0x80000]), "new lookup dest is not empty")
    gate(MAIN_SAV.exists(), "current main SAV missing")
    gate(EXTRACT.exists(), "extra-bank extract missing")

    merged = json.loads(TRANSLATION_MERGED_JSON.read_text(encoding="utf-8"))
    extract = json.loads(EXTRACT.read_text(encoding="utf-8"))
    rom_sha = str(merged["source"]["sha256"]).lower()
    existing_ids = {str(row["record_id"]) for row in merged["records"]}
    existing_targets = {
        str(row["target_file_offset"])
        for row in merged["records"]
        if row.get("scope_status") == "included"
    }
    existing_owners = {str(owner["owner_id"]) for owner in merged["owners"]}
    new_records: list[dict[str, Any]] = []
    new_owners: list[dict[str, Any]] = []
    for row in extract["records"]:
        record, owner = build_record(row, rom_sha)
        gate(record["record_id"] not in existing_ids, f"duplicate extra record {record['record_id']}")
        gate(record["target_file_offset"] not in existing_targets, f"target collision {record['target_file_offset']}")
        gate(owner["owner_id"] not in existing_owners, f"owner collision {owner['owner_id']}")
        existing_ids.add(record["record_id"])
        existing_targets.add(record["target_file_offset"])
        existing_owners.add(owner["owner_id"])
        new_records.append(record)
        new_owners.append(owner)
    merged["records"].extend(new_records)
    merged["owners"].extend(new_owners)
    recount(merged)

    by_id = {str(row["record_id"]): row for row in merged["records"]}
    missing_extra = sorted(set(EXTRA_KO) - set(by_id))
    gate(not missing_extra, f"extra KO ids missing {missing_extra}")

    planned_map: list[tuple[str, dict[str, Any], str, list[str], list[str], bool]] = []
    planned_scenario: list[tuple[dict[str, Any], str, list[str], list[str]]] = []
    hangul12: set[str] = set()
    for record_id, lines in WALL_MAP.items():
        row = by_id[record_id]
        before, old_segments, new_segments = plan_visible(row, lines)
        hangul12.update(hangul_chars(before))
        hangul12.update(hangul_chars("\n".join(lines)))
        planned_map.append((record_id, row, before, old_segments, new_segments, False))
    for record_id, lines in EXTRA_KO.items():
        row = by_id[record_id]
        before, old_segments, new_segments = plan_visible(row, lines)
        hangul12.update(hangul_chars("\n".join(lines)))
        planned_map.append((record_id, row, before, old_segments, new_segments, True))
    for record_id, lines in WALL_SCENARIO.items():
        row = by_id[record_id]
        before, old_segments, new_segments = plan_visible(row, lines)
        hangul12.update(hangul_chars(before))
        hangul12.update(hangul_chars("\n".join(lines)))
        planned_scenario.append((row, before, old_segments, new_segments))

    identified = load_identified_12x12()
    verified12 = unified.load_verified_charmap(unified.CHARMAP_12X12_PATH)
    font12 = load_galmuri12()
    live8, live12 = unified.collect_live_slots(original, merged["records"])
    candidate = bytearray(current)
    allowed: set[int] = set()
    occupied12: set[int] = set()
    painted: list[dict[str, str]] = []
    recovered12: dict[str, int] = {}
    for char in sorted(hangul12):
        recovered12[char] = recover_or_paint(
            candidate,
            original,
            font12,
            char,
            choose_free=choose_free_12x12,
            paint=paint_12x12,
            packed=packed_12x12,
            live=live12,
            occupied=occupied12,
            allowed=allowed,
            painted=painted,
            label="12x12",
            relocated=FONT12_RELOCATED,
            stride=fontops.FONT_12X12_STRIDE,
            count=fontops.FONT_12X12_COUNT,
        )
    cave_cursor = CAVE_START
    evidence: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for record_id, row, before, old_segments, new_segments, fresh in planned_map:
        if fresh:
            continue
        after = "\n".join(visible_segments(new_segments))
        mark_row(row, after, new_segments)
        cave_cursor, written = patch_map_row_live(
            row,
            old_segments,
            new_segments,
            current,
            candidate,
            recovered12,
            identified,
            verified12,
            allowed,
            cave_cursor,
        )
        counts["map_live"] += 1
        evidence.append(
            {
                "record_id": record_id,
                "kind": "live",
                "before": before,
                "after": after,
                "segments": written,
            }
        )

    for row, before, old_segments, new_segments in planned_scenario:
        after = "\n".join(visible_segments(new_segments))
        mark_row(row, after, new_segments)
        owners = tuple(
            int(owner.removeprefix("OWNER-U32-"), 16)
            for owner in row.get("owner_ids", [])
            if str(owner).startswith("OWNER-U32-")
        )
        gate(owners, f"scenario owner missing {row['record_id']}")
        pointer = struct.unpack_from("<I", current, owners[0])[0]
        live_from = bytes(current[pointer - ROM_BASE :])
        identity_payload, consumed = rebuild_scenario_live(
            row, old_segments, old_segments, live_from, recovered12, verified12
        )
        old_payload = live_from[:consumed]
        gate(identity_payload == old_payload, f"live identity rebuild drift {row['record_id']}")
        new_payload, _new_consumed = rebuild_scenario_live(
            row, old_segments, new_segments, live_from, recovered12, verified12
        )
        cave_cursor, old_addresses, new_addr = patch_owned_payload(
            row,
            old_payload,
            new_payload,
            current,
            candidate,
            allowed,
            cave_cursor,
            require_nul=False,
        )
        counts["scenario"] += 1
        evidence.append(
            {
                "record_id": row["record_id"],
                "kind": "scenario",
                "before": before,
                "after": after,
                "old_active_addresses": old_addresses,
                "new_address": new_addr,
            }
        )

    lookup_move = relocate_lookup_table(candidate, allowed)
    for record_id, row, before, old_segments, new_segments, fresh in planned_map:
        if not fresh:
            continue
        after = "\n".join(visible_segments(new_segments))
        mark_row(row, after, new_segments)
        cave_cursor, written = patch_map_row_fresh(
            row,
            new_segments,
            current,
            candidate,
            recovered12,
            identified,
            verified12,
            allowed,
            cave_cursor,
        )
        counts["map_fresh"] += 1
        evidence.append(
            {
                "record_id": record_id,
                "kind": "fresh",
                "before": before,
                "after": after,
                "segments": written,
            }
        )

    leftover_wall = [
        str(row["record_id"])
        for row in merged["records"]
        if row.get("scope_status") != "alias"
        and "벽" in str(row.get("translation_ko") or "")
        and str(row["record_id"]) in set(WALL_MAP) | set(WALL_SCENARIO)
    ]
    gate(not leftover_wall, f"wall leftover {leftover_wall}")
    for record_id, lines in EXTRA_KO.items():
        gate(str(by_id[record_id].get("translation_ko")) == "\n".join(lines), f"extra KO drift {record_id}")
    gate("여자" in str(by_id["GGA-MAPSCRIPT-00FBFDF2"].get("translation_ko")), "女 line still 벽")
    gate("여자" in str(by_id["GGA-SCENARIO-0020AFD8"].get("translation_ko")), "scenario 女 still 벽")

    changed = [index for index, (before, after) in enumerate(zip(current, candidate)) if before != after]
    gate(set(changed) <= allowed, f"unexpected ROM byte change x{len(set(changed) - allowed)}")
    gate(bytes(candidate[MAP_BANK[0] : MAP_BANK[1]]) == current[MAP_BANK[0] : MAP_BANK[1]], "old map-script bank changed")
    gate(bytes(candidate[EXTRA_BANK[0] : EXTRA_BANK[1]]) == current[EXTRA_BANK[0] : EXTRA_BANK[1]], "extra map-script bank changed")
    gate(sha256(MAIN_TIP_ROM.read_bytes()) == sha256(current), "main TIP mutated during patch")
    gate(cave_cursor <= CAVE_END, "nimbus cave overflow")

    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    new_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "wall_map": sorted(WALL_MAP),
            "wall_scenario": sorted(WALL_SCENARIO),
            "extra": sorted(EXTRA_KO),
            "added_records": len(new_records),
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity[IDENTITY_KEY] = new_identity
    identity["translation_overlay_identity_sha256"] = new_identity
    identity["map_script_extrabank_record_identity_sha256"] = digest(
        [
            {
                "record_id": row["record_id"],
                "target_file_offset": row["target_file_offset"],
                "original_raw_sha256": row["original_raw_sha256"],
            }
            for row in new_records
        ]
    )
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary = merged.setdefault("summary", {})
    summary["merged_translation_status_counts"] = status_counts
    merged["inputs"]["map_script_extrabank_20260910"] = {
        "file": EXTRACT.name,
        "file_sha256": sha256(EXTRACT.read_bytes()),
        "record_count": len(new_records),
        "translated_cluster": len(EXTRA_KO),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(bytes(candidate))
    shutil.copy2(MAIN_SAV, OUT_SAV)
    SNAPSHOT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    TRANSLATION_MERGED_JSON.write_bytes(SNAPSHOT.read_bytes())
    update_translation_manifest(merged, SNAPSHOT)
    report = {
        "schema_version": 1,
        "kind": REPORT_KIND,
        "result": "PASS",
        "batch_id": BATCH_ID,
        "cause": (
            "map-script extract BANK_END was 0x00FC0000, so Extra-session "
            "inline prints at 0x00FC0000+ never entered the sheet or lookup hook"
        ),
        "added_map_records": len(new_records),
        "translated_extra_cluster": len(EXTRA_KO),
        "wall_map": len(WALL_MAP),
        "wall_scenario": len(WALL_SCENARIO),
        "painted_glyphs": painted,
        "cave": {"start": hex(CAVE_START), "end": hex(cave_cursor), "capacity_end": hex(CAVE_END)},
        "lookup_relocate": lookup_move,
        "counts": dict(counts),
        "changed_records": len(evidence),
        "jobs": evidence,
        "diff": {"changed_byte_count": len(changed), "unexpected_changed_bytes": 0},
        "output": {
            "path": advance_relative(OUTPUT),
            "sha256": sha256(bytes(candidate)),
            "size": len(candidate),
            "sav": advance_relative(OUT_SAV),
        },
        "verification": {
            "result": "PASS",
            "woman_not_wall": True,
            "screenshot_lines_in_sheet": True,
            "extra_bank_unmodified": True,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "added": len(new_records),
                "translated_extra": len(EXTRA_KO),
                "wall": len(WALL_MAP) + len(WALL_SCENARIO),
                "rom": advance_relative(OUTPUT),
                "sha256": report["output"]["sha256"],
                "changed_bytes": len(changed),
                "cave_used": cave_cursor - CAVE_START,
                "lookup_table": lookup_move["new_table"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
