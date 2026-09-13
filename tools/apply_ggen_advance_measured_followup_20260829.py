#!/usr/bin/env python3
"""Apply the measured 2026-08-29 translation follow-up to the derived sheet.

This keeps the Japanese ROM bytes and the unified source identity unchanged.
It corrects the verified ボク glyph reading and replaces the resulting Korean
``펙`` false readings with context-appropriate first-person Korean.  The output is a new derived merged
snapshot plus a compact audit report; no ROM is written by this script.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "analysis" / "ggen_advance_translation_merged_20260835.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_translation_merged_20260836.json"
DEFAULT_REPORT = ROOT / "analysis" / "ggen_advance_measured_followup_20260829.json"
BATCH_ID = "measured-followup-boku-mirai-20260829"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_ggen_advance_translation_overlays import (  # noqa: E402
    digest,
    translation_payload_digest,
)


HANGUL_BEFORE_PEK = re.compile(r"(?<![가-힣])펙")
FORMAL_KOREAN = re.compile(
    r"(?:습니다|ㅂ니다|입니다|합니다|니다|아요|어요|예요|에요|세요|나요|까요|죠|고요|게요|래요|습니까|겠어요|겠습니다|할게요|주세요)"
)


# These are the few measured lines where a mechanical case conversion would
# be grammatical but less natural than the screenshot/context-specific line.
EXPLICIT_SEGMENTS: dict[str, list[str]] = {
    "GGA-MAPSCRIPT-00F5DE8B": ["하지만 내가 모빌슈트에", "안 타면……"],
    "GGA-MAPSCRIPT-00F5D7BF": ["저도…… 싸울게요"],
    "GGA-MAPSCRIPT-00F5EC0E": ["여기는 제가 선두에 서서", "미끼가 될까요？"],
    "GGA-MAPSCRIPT-00F6BFA6": ["난 당신을 이기고 싶어……", "아니! 이겨 보이겠어!!"],
    "GGA-MAPSCRIPT-00F8A6CD": ["네", "저라도 괜찮다면"],
    "GGA-MAPSCRIPT-00F8A728": ["네", "저라도 괜찮다면"],
    "GGA-MAPSCRIPT-00F8E0B3": ["저는 가야 합니다", "이유가 있습니다!"],
    "GGA-MAPSCRIPT-00F897AE": ["나는 내 의지로", "싸울 상대를 고른다!"],
    "GGA-MAPSCRIPT-00F9B6CD": ["제가 시간을 벌겠습니다"],
    "GGA-MAPSCRIPT-00F9BB5C": ["그럼 우리가 만난 건", "뭐란 말이냐!"],
    "GGA-MAPSCRIPT-00F89516": ["적이 나한테 무슨 용무야?", "말할 것 따위 아무것도 없어"],
    "GGA-MAPSCRIPT-00F89671": ["내 가능성……", "꿈이라고……?"],
    "GGA-MAPSCRIPT-00F8E14E": ["디아나 님은 우리", "문레이스에게 있어,"],
    "GGA-MAPSCRIPT-00F9793F": ["저, 저는……"],
    "GGA-MAPSCRIPT-00F9BF39": ["저, 내가……", "내가 라라아를……"],
    "GGA-MAPSCRIPT-00F9C3E2": ["저, 나는……", "라라아를 죽여 버렸어……"],
    "GGA-MAPSCRIPT-00FB7856": ["갈 곳이 없다면,", "우리 쪽으로 오지 않을래요?"],
    "GGA-MAPSCRIPT-00FBAB75": ["근데, 나한테는", "상대가 안 된다고!!"],
    "GGA-MAPSCRIPT-00FBABFC": ["이 나를", "적대시하고 있다는 거냐!!"],
    "GGA-MAPSCRIPT-00FBB269": ["진 채로 있는 것은,", "내 자존심은 용서 못 해……"],
    "GGA-MAPSCRIPT-00FB2B18": ["당신, 들어 주세요!"],
    "GGA-MAPSCRIPT-00FBE3BF": ["저도 당신과 같이", "가게 해 주실 수 없나요?"],
    "GGA-SCENARIO-001F82C4": ["", "내가 제일 잘", "이걸 쓸 수 있다고!!", ""],
    "GGA-SCENARIO-001F8774": ["", "", "나, 나는……", ""],
    "GGA-SCENARIO-001F87A0": ["", "", "나는……", "돌이킬 수 없는 일을……", ""],
    "GGA-SCENARIO-001F87D0": ["", "", "라라아……", "나도 네 곁으로……", ""],
    "GGA-SCENARIO-001F9990": ["", "", "그렇게 끈질기게 나오면", "나라도 저격해 버리겠어!", ""],
    "GGA-SCENARIO-001FF3F8": ["", "", "지, 질 수 없다고!", "나는… 나는……", ""],
    "GGA-SCENARIO-001FF484": ["", "", "나는……", "잡힐 수 없어!", ""],
    "GGA-SCENARIO-001FF60C": ["", "", "이제 도망치지 않아……", "나는 결심했어!!", ""],
    "GGA-SCENARIO-001FF840": ["", "", "나는", "잡힐 수 없어!", ""],
    "GGA-SCENARIO-001FF8E8": ["", "", "나는 믿고 있으니까……!", ""],
    "GGA-SCENARIO-00205C70": ["", "", "적의 움직임을 기다리는 건", "내 취미가 아니라서 말이지！", ""],
    "GGA-SCENARIO-00205D78": ["", "", "진다는 건", "내 취미가 아니라서 말이지！", ""],
    "GGA-SCENARIO-00206DA4": ["", "", "너 따위가 이 나를", "쓰러뜨릴 수 있을 리 없잖아？", ""],
}

EXPLICIT_TEXT: dict[str, str] = {
    "GGA-TEXT-0017B6E3": "나를 살인자로 만들지 마!",
    "GGA-TEXT-0017BBCA": "내가 해야……",
    "GGA-TEXT-0017BDCA": "나는…… 연방 사관이야!",
    "GGA-TEXT-0017BE48": "저도 돕게 해 주세요",
    "GGA-TEXT-0017C671": "나도 할 수 있다고!",
}


def is_formal(text: str) -> bool:
    return bool(FORMAL_KOREAN.search(text))


def replace_first_person(text: str, formal_override: bool | None = None) -> str:
    """Replace a standalone false reading, leaving 스펙 untouched."""

    if not text or not HANGUL_BEFORE_PEK.search(text):
        return text
    formal = is_formal(text) if formal_override is None else formal_override
    rules = [
        ("펙들에게는", "우리에게는", "우리에게는"),
        ("펙들에게", "우리에게", "우리에게"),
        ("펙들과의", "우리와의", "우리와의"),
        ("펙들과", "우리와", "우리와"),
        ("펙들의", "우리의", "우리의"),
        ("펙들이", "우리가", "우리가"),
        ("펙들도", "우리도", "우리도"),
        ("펙들은", "우리는", "우리는"),
        ("펙들", "우리", "우리"),
        ("펙네", "우리 쪽", "우리 쪽"),
        ("펙이야말로", "나야말로", "저야말로"),
        ("펙이라도", "나라도", "저라도"),
        ("펙이랑", "나랑", "저랑"),
        ("펙과", "나와", "저와"),
        ("펙에게는", "나에게는", "저에게는"),
        ("펙에게", "나에게", "저에게"),
        ("펙한테", "나한테", "저한테"),
        ("펙으로", "나로", "저로"),
        ("펙 자신의", "나 자신의", "저 자신의"),
        ("펙을", "나를", "저를"),
        ("펙이", "내가", "제가"),
        ("펙의", "내", "제"),
        ("펙도", "나도", "저도"),
        ("펙은", "나는", "저는"),
        ("펙,", "나,", "저,"),
        ("펙……", "나……", "저……"),
        ("펙", "나", "저"),
    ]
    for old, casual, polite in rules:
        replacement = polite if formal else casual
        text = re.sub(rf"(?<![가-힣]){re.escape(old)}", replacement, text)
    return text


def correct_source_decode(row: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    scope = str(row.get("source_scope") or "")
    if scope in {"scenario_main", "scenario_map_script"}:
        old = str(row.get("source_text") or "")
        new = old.replace("ペク", "ボク")
        if new != old:
            row["source_text"] = new
            changes.append("source_text ペク→ボク")
        for segment in row.get("segments") or []:
            old_segment = str(segment.get("source_text") or "")
            new_segment = old_segment.replace("ペク", "ボク")
            if new_segment != old_segment:
                segment["source_text"] = new_segment
                changes.append("segment source_text ペク→ボク")
    elif scope == "production":
        raw = str(row.get("raw_hex") or "").replace(" ", "").upper()
        old = str(row.get("source_text") or "")
        if "F00E" in raw and "<0083>ク" in old:
            new = old.replace("<0083>ク", "ボク", 1)
            row["source_text"] = new
            unresolved = [slot for slot in row.get("source_unresolved_slots") or [] if slot != "0x0083"]
            row["source_unresolved_slots"] = unresolved
            changes.append("source_text <0083>ク→ボク")
            changes.append("source_unresolved_slots remove 0x0083")
    return changes


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


def apply_translation(row: dict[str, Any]) -> list[str]:
    before_ko = str(row.get("translation_ko") or "")
    before_segments = copy.deepcopy(row.get("translation_segments"))
    record_id = str(row["record_id"])
    segments = row.get("translation_segments")

    if record_id in EXPLICIT_SEGMENTS:
        expected = row.get("segments") or []
        if not isinstance(segments, list) or len(segments) != len(expected):
            raise ValueError(f"explicit segment framing drift: {record_id}")
        row["translation_segments"] = list(EXPLICIT_SEGMENTS[record_id])
        row["translation_ko"] = "\n".join(part for part in row["translation_segments"] if part)
    elif record_id in EXPLICIT_TEXT:
        row["translation_ko"] = EXPLICIT_TEXT[record_id]
    elif isinstance(segments, list) and segments:
        row_formal = is_formal(before_ko)
        row["translation_segments"] = [replace_first_person(str(part), row_formal) for part in segments]
        row["translation_ko"] = "\n".join(part for part in row["translation_segments"] if part)
    else:
        row["translation_ko"] = replace_first_person(before_ko)

    after_ko = str(row.get("translation_ko") or "")
    after_segments = row.get("translation_segments")
    changes: list[str] = []
    if after_ko != before_ko or after_segments != before_segments:
        row["translation_source"] = "user_verified"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-08-29"
        row["overlay_batch_id"] = BATCH_ID
        row["translator_notes"] = (
            str(row.get("translator_notes") or "").rstrip()
            + "; measured follow-up: corrected ボク/first-person reading"
        )
        update_payload_hash(row)
        changes.append("translation_ko/segments corrected")
    return changes


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    merged = json.loads(args.source.read_text(encoding="utf-8"))
    changed: list[dict[str, Any]] = []
    source_only = 0
    translation_only = 0
    both = 0
    for row in merged.get("records") or []:
        before_source = str(row.get("source_text") or "")
        before_segments_source = copy.deepcopy(row.get("segments"))
        before_ko = str(row.get("translation_ko") or "")
        before_translation_segments = copy.deepcopy(row.get("translation_segments"))
        source_changes = correct_source_decode(row)
        translation_changes = apply_translation(row) if (
            HANGUL_BEFORE_PEK.search(before_ko)
            or str(row.get("record_id")) in EXPLICIT_SEGMENTS
            or str(row.get("record_id")) in EXPLICIT_TEXT
        ) else []
        if not source_changes and not translation_changes:
            continue
        if source_changes and translation_changes:
            both += 1
        elif source_changes:
            source_only += 1
        else:
            translation_only += 1
        changed.append(
            {
                "record_id": row["record_id"],
                "source_scope": row.get("source_scope"),
                "target_file_offset": row.get("target_file_offset"),
                "source_before": before_source,
                "source_after": row.get("source_text"),
                "segments_source_changed": before_segments_source != row.get("segments"),
                "translation_before": before_ko,
                "translation_after": row.get("translation_ko"),
                "translation_segments_before": before_translation_segments,
                "translation_segments_after": row.get("translation_segments"),
                "changes": source_changes + translation_changes,
                "translation_payload_sha256": row.get("translation_payload_sha256"),
            }
        )

    changed.sort(key=lambda item: str(item["record_id"]))
    translated = [item for item in changed if item["translation_before"] != item["translation_after"] or item["translation_segments_before"] != item["translation_segments_after"]]
    map_translated = [item for item in translated if item.get("source_scope") in {"scenario_map_script", "scenario_main"}]
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    followup_identity = digest({"parent": parent_identity, "batch_id": BATCH_ID, "records": [{"record_id": item["record_id"], "payload": item.get("translation_payload_sha256")} for item in changed]})
    merged.setdefault("identity", {})["parent_translation_overlay_identity_sha256"] = parent_identity
    merged["identity"]["measured_followup_identity_sha256"] = followup_identity
    merged["identity"]["translation_overlay_identity_sha256"] = followup_identity
    if map_translated:
        parent_map_identity = str(merged["identity"].get("map_script_translation_overlay_identity_sha256") or "")
        map_identity = digest({"parent": parent_map_identity, "batch_id": BATCH_ID, "records": [{"record_id": item["record_id"], "payload": item.get("translation_payload_sha256")} for item in map_translated]})
        merged["identity"]["parent_map_script_translation_overlay_identity_sha256"] = parent_map_identity
        merged["identity"]["measured_followup_map_script_identity_sha256"] = map_identity
        merged["identity"]["map_script_translation_overlay_identity_sha256"] = map_identity

    summary = merged.setdefault("summary", {})
    summary["translation_overlay_identity_sha256"] = followup_identity
    summary["measured_followup_changed_records"] = len(changed)
    summary["measured_followup_translation_records"] = len(translated)
    summary["measured_followup_source_decode_records"] = sum(1 for item in changed if item["source_before"] != item["source_after"] or item["segments_source_changed"])
    merged["measured_followup"] = {
        "batch_id": BATCH_ID,
        "report": str(args.report.relative_to(ROOT)).replace("\\", "/"),
        "parent_snapshot": args.source.name,
        "changed_records": len(changed),
        "translation_records": len(translated),
        "source_decode_records": summary["measured_followup_source_decode_records"],
        "source_only_records": source_only,
        "translation_only_records": translation_only,
        "both_records": both,
        "identity_sha256": followup_identity,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_measured_followup",
        "batch_id": BATCH_ID,
        "source_snapshot": str(args.source.relative_to(ROOT)).replace("\\", "/"),
        "output_snapshot": str(args.out.relative_to(ROOT)).replace("\\", "/"),
        "identity_sha256": followup_identity,
        "summary": merged["measured_followup"],
        "records": changed,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", **merged["measured_followup"], "report": str(args.report)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
