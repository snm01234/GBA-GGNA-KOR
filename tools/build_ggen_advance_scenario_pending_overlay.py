#!/usr/bin/env python3
"""Build overlay compact maps for newly slot-complete scenario pending rows.

Dialogue unique JP is looked up from a KO map.  Unused bark templates keep
＠ padding and translate speaker + type labels only.  The immutable source
is not rewritten; this writes compact maps for overlay-batch expansion.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, RESERVED, load_map  # noqa: E402
from analyze_ggen_advance_scenario_pending import decode_slots, is_bark  # noqa: E402
import build_ggen_advance_translation_overlay_batch as overlay_batch  # noqa: E402
import build_ggen_advance_translation_master as names  # noqa: E402

MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260827.json"
SCENARIO = ROOT / "analysis" / "scenario_event_translation_source_20260827.json"
SOURCE = ROOT / "analysis" / "ggen_advance_unified_source_20260827.json"
MAP12 = ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json"
KO_MAP = ROOT / "analysis" / "ggen_advance_scenario_pending_dialogue_ko_20260828.json"
DIALOGUE_COMPACT = ROOT / "analysis" / "scenario_pending_dialogue_compact_20260828.json"
BARK_COMPACT = ROOT / "analysis" / "scenario_pending_bark_compact_20260828.json"
DIALOGUE_OVERLAY = ROOT / "analysis" / "ggen_advance_translation_overlays" / "scenario_pending_dialogue_1454.json"
BARK_OVERLAY = ROOT / "analysis" / "ggen_advance_translation_overlays" / "scenario_pending_bark_0390.json"

AT = "＠"
PARTICLE_KO = {"の": "의", "を": "을", "で": "로", "！": "！", "!": "!"}

BARK_TYPES = {
    "NT武器セリフ": "NT무기 대사",
    "ダメージ瀕死セリフ": "데미지 빈사 대사",
    "先制攻撃セリフ": "선제공격 대사",
    "単独散開セリフ": "단독 산개 대사",
    "大ダメージセリフ": "대피해 대사",
    "射撃セリフ1": "사격 대사1",
    "射撃セリフ2": "사격 대사2",
    "射撃セリフ３": "사격 대사３",
    "小ダメージセリフ": "소피해 대사",
    "捕獲失敗反撃セリフ": "포획 실패 반격 대사",
    "捕獲実行セリフ": "포획 실행 대사",
    "撃破セリフ": "격파 대사",
    "瀕死回避セリフ": "빈사 회피 대사",
    "特殊防御セリフ": "특수 방어 대사",
    "被捕獲セリフ": "피포획 대사",
    "近接セリフ1": "근접 대사1",
    "近接セリフ2": "근접 대사2",
    "近接セリフ３": "근접 대사３",
    "通常ダメージセリフ1": "통상 피해 대사1",
    "通常ダメージセリフ2": "통상 피해 대사2",
    "通常回避セリフ": "통상 회피 대사",
    "通常散開セリフ": "통상 산개 대사",
}

SPEAKER_KO = {
    "－": "－",
    "アルフ・カムラ": "알프 카무라",
    "ウッディ": "우디",
    "ギレン・ザビ": "기렌 자비",
    "ディアナ・ソレル": "디아나 소렐",
    "デギン・ザビ": "데긴 자비",
    "デルマイユ公爵": "델마이유 공작",
    "ドモン＆レイン": "도몬＆레인",
    "ニナ・パープルトン": "니나 퍼플턴",
    "ハンゲルグ": "한게르그",
    "マーカ・クラン": "마커 클랜",
    "マチルダ・アジャン": "마틸다 아쟌",
    "ミカムラ": "미카무라",
    "ライゾウ・カッシュ": "라이조 캇슈",
    "レビル": "레빌",
    "ロラン・チュアン": "로랑 추안",
    "連邦エリート士官（ミラー）": "연방 엘리트 장교（밀러）",
    "シルエット": "실루엣",
    "政府高官1": "정부 고관1",
    "政府高官2": "정부 고관2",
    "NT研所員": "NT연구소원",
}


def fail(message: str) -> None:
    raise SystemExit(f"gate failed: {message}")


def translate_bark_type(text: str) -> str:
    marks = AT * text.count(AT)
    stem = text.replace(AT, "")
    ko = BARK_TYPES.get(stem)
    if ko is None:
        fail(f"unknown bark type: {text}")
    return ko + marks


def translate_speaker(text: str) -> str:
    if text in SPEAKER_KO:
        return SPEAKER_KO[text]
    if text in names.MANUAL_TRANSLATIONS:
        return names.MANUAL_TRANSLATIONS[text]
    fail(f"unknown bark speaker: {text}")


def load_ko_map(path: Path) -> dict[str, list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, list[str]] = {}
    if isinstance(payload, dict) and "records" in payload:
        payload = payload["records"]
    if isinstance(payload, list):
        for item in payload:
            mapping[item["jp"]] = list(item["parts"])
        return mapping
    if isinstance(payload, dict):
        return {key: list(value) for key, value in payload.items()}
    fail(f"unexpected KO map shape: {path}")
    return {}


def decode_text_parts(scenario_row: dict, charmap: dict[int, str]) -> list[str]:
    parts: list[str] = []
    for segment in scenario_row.get("segments") or []:
        slots = [int(str(item), 16) for item in (segment.get("slots") or [])]
        if not slots:
            continue
        text, missing = decode_slots(slots, charmap)
        if any(slot not in RESERVED for slot in missing):
            fail(f"undecoded slot in {scenario_row['record_id']}: {[hex(s) for s in missing]}")
        parts.append(text)
    return parts


def fill_segments(unified_row: dict, ko_parts: list[str]) -> tuple[list[str], str]:
    source_segments = unified_row.get("segments") or []
    text_indexes = [index for index, segment in enumerate(source_segments) if segment.get("is_text_segment")]
    if len(text_indexes) != len(ko_parts):
        fail(
            f"text segment count mismatch for {unified_row['record_id']}: "
            f"source {len(text_indexes)} ko {len(ko_parts)}"
        )
    filled = [""] * len(source_segments)
    for index, part in zip(text_indexes, ko_parts):
        filled[index] = part
    display = "\n".join(part for part in ko_parts if part)
    return filled, display


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    charmap = load_map(MAP12)
    charmap.update(CORRECTED_LOW_KANA)
    ko_map = load_ko_map(KO_MAP)
    merged = json.loads(MERGED.read_text(encoding="utf-8"))
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    unified = json.loads(SOURCE.read_text(encoding="utf-8"))
    by_scenario = {row["record_id"]: row for row in scenario["main"]["records"]}
    by_unified = {row["record_id"]: row for row in unified["records"]}
    pending_ids = [
        row["record_id"]
        for row in merged["records"]
        if row.get("source_scope") == "scenario_main"
        and row.get("translation_status") == "pending"
        and row.get("translation_policy") == "translate"
        and row.get("scope_status") == "included"
    ]

    dialogue_records: list[dict] = []
    bark_records: list[dict] = []
    missing_jp: list[str] = []
    for record_id in pending_ids:
        scenario_row = by_scenario[record_id]
        unified_row = by_unified[record_id]
        parts = decode_text_parts(scenario_row, charmap)
        joined = "\n".join(parts)
        if is_bark(joined):
            ko_parts: list[str] = []
            for part in parts:
                if "セリフ" in part:
                    ko_parts.append(translate_bark_type(part))
                elif part in PARTICLE_KO:
                    ko_parts.append(PARTICLE_KO[part])
                else:
                    ko_parts.append(translate_speaker(part))
            filled, display = fill_segments(unified_row, ko_parts)
            bark_records.append(
                {
                    "record_id": record_id,
                    "translation_segments": filled,
                    "translation_ko": display,
                }
            )
            continue
        key = " / ".join(parts)
        ko_parts = ko_map.get(key)
        if ko_parts is None:
            missing_jp.append(key)
            continue
        if len(ko_parts) != len(parts):
            fail(f"KO parts length mismatch for {record_id}: {key}")
        filled, display = fill_segments(unified_row, ko_parts)
        if not display.strip():
            fail(f"empty dialogue translation for {record_id}")
        dialogue_records.append(
            {
                "record_id": record_id,
                "translation_segments": filled,
                "translation_ko": display,
            }
        )

    if missing_jp:
        unique_missing = sorted(set(missing_jp))
        fail(f"KO map missing {len(unique_missing)} unique JP; first: {unique_missing[:8]}")

    dialogue_compact = {
        "schema_version": 1,
        "batch_id": "scenario-pending-dialogue-20260828",
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "translator_notes": "slot-complete 12x12 decode; natural Korean; ＠ unused",
        "records": dialogue_records,
    }
    bark_compact = {
        "schema_version": 1,
        "batch_id": "scenario-pending-bark-20260828",
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "translator_notes": "unused bark template labels; speaker names from glossary; ＠ placeholders preserved",
        "records": bark_records,
    }
    DIALOGUE_COMPACT.parent.mkdir(parents=True, exist_ok=True)
    DIALOGUE_COMPACT.write_text(json.dumps(dialogue_compact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BARK_COMPACT.write_text(json.dumps(bark_compact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    dialogue_overlay = overlay_batch.build_overlay(SOURCE, DIALOGUE_COMPACT, DIALOGUE_OVERLAY)
    bark_overlay = overlay_batch.build_overlay(SOURCE, BARK_COMPACT, BARK_OVERLAY)
    print(
        json.dumps(
            {
                "result": "PASS",
                "pending_rows": len(pending_ids),
                "dialogue_rows": len(dialogue_records),
                "bark_rows": len(bark_records),
                "dialogue_overlay": dialogue_overlay,
                "bark_overlay": bark_overlay,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
