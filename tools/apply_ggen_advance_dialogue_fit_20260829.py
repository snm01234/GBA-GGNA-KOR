#!/usr/bin/env python3
"""Fit translated map-dialogue segments to the native 12x12 text box.

Map-event text is stored as one NUL-terminated stream per visible line.  The
renderer has no automatic Korean wrapping, so a translated segment must fit
the 15-cell dialogue area already allocated by the event.  This pass keeps
the original segment count and only removes low-value spacing when that is
enough; a small reviewed set uses shorter, natural Korean wording instead.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent

from build_ggen_advance_map_script_sheet import recount  # noqa: E402


MERGED_IN = ROOT / "analysis" / "ggen_advance_translation_merged_20260834.json"
MERGED_OUT = ROOT / "analysis" / "ggen_advance_translation_merged_20260835.json"
BATCH = "main-tip-dialogue-fit-20260829"
MAX_DIALOGUE_CELLS = 15

# These lines still exceeded 15 cells after harmless spacing compaction.  The
# replacements preserve the scene meaning while fitting the existing event
# line; keys include the segment index because some events have two lines.
MANUAL_SEGMENTS: dict[tuple[str, int], str] = {
    ("GGA-MAPSCRIPT-00F50CD3", 0): "그럼 승부는 루나2 함대와",
    ("GGA-MAPSCRIPT-00F50DF6", 0): "지온군 MS와 접촉했다는",
    ("GGA-MAPSCRIPT-00F5133F", 0): "사선의 호랑이와 푸른 거성",
    ("GGA-MAPSCRIPT-00F575AA", 0): "그런 얼굴 하지 마라",
    ("GGA-MAPSCRIPT-00F58CE6", 1): "1기를 자프트에 뺏겨 현재…",
    ("GGA-MAPSCRIPT-00F5AA7D", 0): "헬리오 이상을 이미 눈치채고",
    ("GGA-MAPSCRIPT-00F5AD43", 1): "1기를 자프트에 뺏겨 현재…",
    ("GGA-MAPSCRIPT-00F620CB", 0): "저주받은 자비의 자식이라니…",
    ("GGA-MAPSCRIPT-00F673F2", 1): "다음 행동으로 옮길까요",
    ("GGA-MAPSCRIPT-00F679DF", 0): "사선의 호랑이를 쓰러뜨리자!",
    ("GGA-MAPSCRIPT-00F68D76", 0): "호랑이와 푸른 거성에 맞서",
    ("GGA-MAPSCRIPT-00F68E8C", 0): "우리와 싸우고 싶나?",
    ("GGA-MAPSCRIPT-00F69033", 0): "우리도 호랑이를 쓰러뜨리려고",
    ("GGA-MAPSCRIPT-00F69CFC", 0): "……하지만, 어쩌죠?",
    ("GGA-MAPSCRIPT-00F6C017", 1): "그분은 내가 지킨다!",
    ("GGA-MAPSCRIPT-00F6E2AE", 0): "전황은 아직이고, 우리는",
    ("GGA-MAPSCRIPT-00F7F97D", 0): "동료를 위해 싸울 수 있어!",
    ("GGA-MAPSCRIPT-00F7FBF9", 0): "뭐가 살아 돌아가라니……",
    ("GGA-MAPSCRIPT-00F7FC09", 1): "동료 위해 싸우다니…!",
    ("GGA-MAPSCRIPT-00F808AC", 0): "……하지만, 이건 어때?",
    ("GGA-MAPSCRIPT-00F81BD3", 0): "이래 봬도 과학자라서 말이야",
    ("GGA-MAPSCRIPT-00F84F24", 0): "죽음도 돈으로 살 수 있어",
    ("GGA-MAPSCRIPT-00F85198", 1): "왜 내 앞에 나타나……?",
    ("GGA-MAPSCRIPT-00F8607A", 0): "누구에게도 굴하지 않고 평화",
    ("GGA-MAPSCRIPT-00F88202", 0): "뒤의 OZ를 쓰러뜨려야",
    ("GGA-MAPSCRIPT-00F89DAE", 0): "다만, 어떻게 싸울지……",
    ("GGA-MAPSCRIPT-00F8DC67", 0): "여왕님은 놈들에게 붙잡혀……",
    ("GGA-MAPSCRIPT-00F91365", 0): "내가 가르치고 싶던 건",
    ("GGA-MAPSCRIPT-00F9268A", 1): "호각이면 싸울 수 있단다",
    ("GGA-MAPSCRIPT-00F9296F", 1): "과분한 말씀이십니다!!",
    ("GGA-MAPSCRIPT-00F9701A", 1): "왜 놈들을 못 쓰러뜨리나!!",
    ("GGA-MAPSCRIPT-00F9776A", 0): "저 너머에 힘이 있다!!",
    ("GGA-MAPSCRIPT-00FA4C38", 1): "서로 죽고 죽이는 거다!!",
    ("GGA-MAPSCRIPT-00FA79D5", 0): "그래서 암살을 선언했다!!",
    ("GGA-MAPSCRIPT-00FA95AB", 0): "그럼 시냅스 함장께 맡기죠",
    ("GGA-MAPSCRIPT-00FAD02D", 1): "공략법이 떠오릅니까?",
    ("GGA-MAPSCRIPT-00FAD3A6", 1): "귀관들과 합류를 허락하라",
    ("GGA-MAPSCRIPT-00FAD52D", 0): "원한을 버리고 사람들을 위해",
    ("GGA-MAPSCRIPT-00FB512E", 0): "아니면 함대는 이길 수도",
    ("GGA-MAPSCRIPT-00FB6FDE", 0): "섬 일은 말하지 않겠다고",
    ("GGA-MAPSCRIPT-00FBB37D", 0): "실력보다 성격이 문제야……",
    ("GGA-MAPSCRIPT-00FBD0D0", 0): "엄마가 동생에게 가르치던 걸",
    ("GGA-MAPSCRIPT-00F68269", 0): "……도주 압력 상정, 마찰",
    ("GGA-MAPSCRIPT-00F829A2", 0): "그리되지 않도록, 자네들은",
    ("GGA-MAPSCRIPT-00F82A2E", 0): "작은 불도 꺼지지 않아…",
    ("GGA-MAPSCRIPT-00FB2099", 0): "이젠, 얽매이지 않아!!",
    ("GGA-MAPSCRIPT-00FBA8B2", 0): "투항자 안전지대 탈출까지",
    ("GGA-MAPSCRIPT-00FBA8B2", 1): "아시아군을 붙잡겠습니다!!",
}

PARTICLE_RE = re.compile(r"(?<=[가-힣A-Za-z0-9]) ([은는이가을를의도에로와과만])")
PUNCTUATION = set(".,!?，。、・…!?)]}』」")


def compact_line(value: str) -> str:
    """Remove the least costly spaces until a line fits its fixed cell width."""

    result = value
    while len(result) > MAX_DIALOGUE_CELLS:
        spaces = [index for index, char in enumerate(result) if char == " "]
        if not spaces:
            return result

        def rank(index: int) -> tuple[int, int]:
            before = result[index - 1] if index else ""
            after = result[index + 1] if index + 1 < len(result) else ""
            if after in "은는이가을를의도에로와과만":
                priority = 0
            elif before in PUNCTUATION or after in PUNCTUATION:
                priority = 1
            elif PARTICLE_RE.search(result[max(0, index - 1) : index + 2]):
                priority = 1
            else:
                priority = 2
            return priority, -index

        remove_at = min(spaces, key=rank)
        result = result[:remove_at] + result[remove_at + 1 :]
    return result


def fit_segments(row: dict[str, Any]) -> tuple[list[str], int, int]:
    record_id = str(row.get("record_id") or "")
    source_segments = list(row.get("segments") or [])
    original = [str(value) for value in (row.get("translation_segments") or [])]
    if len(original) != len(source_segments):
        translation_ko = str(row.get("translation_ko") or "")
        if "\n" in translation_ko:
            original = translation_ko.split("\n")
        elif "\\n" in translation_ko:
            original = translation_ko.split("\\n")
        else:
            original = [translation_ko]
        if len(original) != len(source_segments):
            raise SystemExit(
                f"gate failed: {record_id} translation segment count "
                f"{len(original)} != source count {len(source_segments)}"
            )
    fitted: list[str] = []
    overflow_before = 0
    manual = 0
    for index, value in enumerate(original):
        if len(value) > MAX_DIALOGUE_CELLS:
            overflow_before += 1
        key = (record_id, index)
        if key in MANUAL_SEGMENTS:
            value = MANUAL_SEGMENTS[key]
            manual += 1
        elif len(value) > MAX_DIALOGUE_CELLS:
            value = compact_line(value)
        if "\n" in value or len(value) > MAX_DIALOGUE_CELLS:
            raise SystemExit(
                f"gate failed: {record_id} segment {index} still exceeds "
                f"{MAX_DIALOGUE_CELLS} cells: {value!r}"
            )
        fitted.append(value)
    return fitted, overflow_before, manual


def main() -> int:
    merged = json.loads(MERGED_IN.read_text(encoding="utf-8"))
    seen_manual: set[tuple[str, int]] = set()
    rows_changed = 0
    segments_compacted = 0
    segments_overflow = 0
    manual_applied = 0

    for row in merged["records"]:
        if (
            row.get("source_scope") != "scenario_map_script"
            or row.get("scope_status") != "included"
            or row.get("translation_status") != "translated"
        ):
            continue
        old = [str(value) for value in (row.get("translation_segments") or [])]
        fitted, before, manual = fit_segments(row)
        if before:
            segments_overflow += before
        manual_applied += manual
        seen_manual.update(
            key for key in MANUAL_SEGMENTS if key[0] == str(row.get("record_id") or "")
        )
        if fitted == old:
            continue
        rows_changed += 1
        segments_compacted += sum(1 for previous, current in zip(old, fitted) if previous != current)
        row["translation_segments"] = fitted
        row["translation_ko"] = "\n".join(fitted)
        row["translation_source"] = "curated_project_data"
        row["overlay_batch_id"] = BATCH
        row["translator_notes"] = (
            f"{row.get('translator_notes') or 'reviewed Korean'}; "
            f"12x12 map dialogue fitted to {MAX_DIALOGUE_CELLS} cells"
        )

    missing_manual = set(MANUAL_SEGMENTS) - seen_manual
    if missing_manual:
        raise SystemExit(f"gate failed: manual fit keys not found: {sorted(missing_manual)!r}")

    recount(merged)
    MERGED_OUT.parent.mkdir(parents=True, exist_ok=True)
    MERGED_OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "merged_in": str(MERGED_IN),
                "merged_out": str(MERGED_OUT),
                "max_dialogue_cells": MAX_DIALOGUE_CELLS,
                "rows_changed": rows_changed,
                "segments_overflow_before": segments_overflow,
                "segments_compacted": segments_compacted,
                "manual_segments": manual_applied,
                "manual_keys": len(MANUAL_SEGMENTS),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
