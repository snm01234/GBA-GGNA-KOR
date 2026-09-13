"""Build a batch from rows fully decoded by the exact font supplement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_MERGED = Path("analysis/ggen_advance_translation_merged_20260827.json")
DEFAULT_OUTPUT = Path(
    "analysis/ggen_advance_translation_batch_maps/decoded_supplement_batch.json"
)

# The corresponding Japanese rows are completely covered by the conflict-free
# 8x16 supplement.  Korean wording follows the existing project glossary.
TRANSLATIONS = {
    # weapon_name
    "GGA-TEXT-00179E86": "격투",
    "GGA-TEXT-00179F0E": "펩 미사일",
    "GGA-TEXT-0017A0CB": "대형 히트 사벨",
    "GGA-TEXT-0017A159": "곤봉형 빔 라이플",
    "GGA-TEXT-0017A15F": "곤봉",
    "GGA-TEXT-0017A1C4": "대형 빔 사벨",
    "GGA-TEXT-0017A207": "시작형 빔 라이플",
    "GGA-TEXT-0017A20C": "시작형 빔 사벨",
    "GGA-TEXT-0017A23D": "소닉 웨폰",
    "GGA-TEXT-0017A24E": "기관포",
    "GGA-TEXT-0017A2ED": "유선 클로 암",
    "GGA-TEXT-0017A2F4": "대형 미사일 런처",
    "GGA-TEXT-0017A35E": "빔 소드 액스",
    "GGA-TEXT-0017A39F": "대형 미사일",
    "GGA-TEXT-0017A564": "빔 소드",
    "GGA-TEXT-0017A581": "샤이닝 F 소드",
    "GGA-TEXT-0017A645": "메가소닉포",
    "GGA-TEXT-0017A6CD": "대형 빔 소드",
    "GGA-TEXT-0017AD29": "대공 기관포",
    "GGA-TEXT-0017AD37": "대형 메가 입자포",
    "GGA-TEXT-0017AD63": "대공 레이저",
    "GGA-TEXT-0017ADC8": "대공포",
    # character_name
    "GGA-TEXT-0017B6DC": "웃소 에빈",
    "GGA-TEXT-0017C2DA": "디아나 소렐",
    "GGA-TEXT-0017C3B4": "동방불패",
    "GGA-TEXT-0017CEC8": "지온 사관",
    "GGA-TEXT-0017CEF1": "네오 지온 사관",
    "GGA-TEXT-0017CF2B": "WF 사관",
    "GGA-TEXT-0017CF4D": "자프트 사관",
    "GGA-TEXT-001856CB": "웃소 에빈",
    "GGA-TEXT-0018596C": "시마 가라하우<아군>",
    "GGA-TEXT-00185ABE": "디아나 소렐",
    "GGA-TEXT-00185B34": "동방불패 마스터 아시아",
    # fully decoded short labels
    "GGA-TEXT-0018CF27": "솔로몬",
    "GGA-TEXT-0018CF2C": "우주",
    "GGA-TEXT-0018CFE0": "솔라 시스템",
    "GGA-TEXT-0018D004": "우주",
    "GGA-TEXT-0018D20D": "빛나는 우주",
    "GGA-TEXT-001BEF79": "솔로몬",
}


def select_records(merged: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {str(row["record_id"]): row for row in merged.get("records", [])}
    selected: list[dict[str, Any]] = []
    for record_id, translation in TRANSLATIONS.items():
        row = by_id.get(record_id)
        if row is None:
            raise SystemExit(f"record is missing from merged source: {record_id}")
        if row.get("translation_status") != "pending":
            raise SystemExit(f"record is not pending: {record_id}")
        if row.get("translation_policy") != "translate":
            raise SystemExit(f"record is not translatable: {record_id}")
        selected.append(
            {
                "record_id": record_id,
                "translation_ko": translation,
                "translation_status": "translated",
                "translator_notes": "natural Korean label from fully decoded exact font-supplement source",
            }
        )
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args(argv)

    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    records = select_records(merged)
    payload = {
        "schema_version": 1,
        "batch_id": args.batch_id,
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "translator_notes": "Rows fully decoded by the exact 8x16 font supplement; no unresolved text slot was guessed.",
        "records": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "output": str(args.out), "record_count": len(records)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
