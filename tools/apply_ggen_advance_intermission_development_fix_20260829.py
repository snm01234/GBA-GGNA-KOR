#!/usr/bin/env python3
"""Fix measured intermission help and development-dialogue Japanese leaks.

The affected records were inventoried with 8x16 source text even though their
runtime draw path is 12x12.  This patch records the corrected Japanese decode,
adds reviewed Korean, and emits a derived canonical-source candidate plus an
audit report.  ROM writing remains the unified builder's responsibility.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "integrated" / "translation" / "ggen_advance_translation_merged.json"
DEFAULT_OUTPUT = ROOT / "analysis" / "ggen_advance_translation_merged_20260841.json"
DEFAULT_REPORT = ROOT / "analysis" / "ggen_advance_intermission_development_fix_20260829.json"
BATCH_ID = "intermission-development-12x12-fix-20260829"

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_ggen_advance_translation_overlays import digest, translation_payload_digest  # noqa: E402


# record_id: (verified 12x12 Japanese, reviewed Korean)
TRANSLATIONS: dict[str, tuple[str, str]] = {
    "GGA-TEXT-001BE810": ("次の作戦の内容を表示します", "다음 작전 내용을 표시합니다"),
    "GGA-TEXT-001BE824": ("周辺地域の索敵を行います", "주변 지역을 탐색합니다"),
    "GGA-TEXT-001BE836": ("次のセッションに進みます", "다음 세션으로 진행합니다"),
    "GGA-TEXT-001BE845": ("MSや改修パーツを補給します", "MS와 강화 파츠를 보급합니다"),
    "GGA-TEXT-001BE857": ("MSの改修および強化を行います", "MS를 개조·강화합니다"),
    "GGA-TEXT-001BE86A": ("改修の組み合わせを表示します", "개조 조합을 표시합니다"),
    "GGA-TEXT-001BE87E": ("MSを分解します", "MS를 분해합니다"),
    "GGA-TEXT-001BE889": ("戦艦にMSとパイロットを配置します", "전함에 MS와 파일럿을 배치합니다"),
    "GGA-TEXT-001BE89B": ("MSやパイロットの情報を閲覧します", "MS와 파일럿 정보를 봅니다"),
    "GGA-TEXT-001BE8AE": ("データをセーブします", "데이터를 세이브합니다"),
    "GGA-TEXT-001BE8B9": ("データをロードします", "데이터를 로드합니다"),
    "GGA-TEXT-001BE8C4": ("Gジェネレーション アドバンス", "G 제네레이션 어드밴스"),
    "GGA-TEXT-001BE8D4": ("改修・強化可能なユニットが存在しません", "개조·강화 가능한 유닛이 없습니다"),
    "GGA-TEXT-001BE8EF": ("分解可能なユニットが存在しません", "분해 가능한 유닛이 없습니다"),
    "GGA-TEXT-001BE906": ("データがありません", "데이터가 없습니다"),
    "GGA-TEXT-001BE910": ("本バージョンでは選択出来ません", "이 버전에서는 선택할 수 없습니다"),
    "GGA-TEXT-001BE957": ("それでは、改造を行います", "그러면 개조를 시작합니다"),
    "GGA-TEXT-001BE965": ("改造が終了しました", "개조가 끝났습니다"),
    "GGA-TEXT-001BE972": ("では、改造を行います", "그럼 개조를 시작합니다"),
    "GGA-TEXT-001BE97E": ("完成です 機体はストックの", "완성됐습니다 기체는 스톡"),
    "GGA-TEXT-001BE98E": ("方に送っておきます", "쪽으로 보내 두겠습니다"),
    "GGA-TEXT-001BE999": ("じゃあ、始めるぞ", "자, 시작한다"),
    "GGA-TEXT-001BE9A3": ("…できたぞ 機体はストックの", "…됐다 기체는 스톡"),
    "GGA-TEXT-001BE9B2": ("方に送っておくからな", "쪽으로 보내 둘 테니까"),
    "GGA-TEXT-001BE9BE": ("では、始めようかの……", "그럼 시작해 볼까……"),
    "GGA-TEXT-001BE9CB": ("そおら、出来上がりじゃ", "자, 완성됐네"),
}


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    merged = json.loads(args.source.read_text(encoding="utf-8"))
    by_id = {str(row.get("record_id")): row for row in merged.get("records") or []}
    missing = sorted(set(TRANSLATIONS) - set(by_id))
    if missing:
        raise SystemExit(f"gate failed: target records missing: {missing}")

    changed: list[dict[str, Any]] = []
    for record_id, (source_text, translation_ko) in TRANSLATIONS.items():
        row = by_id[record_id]
        if row.get("source_scope") != "production":
            raise SystemExit(f"gate failed: source scope drift: {record_id}")
        if row.get("semantic_category") not in {
            "map_system_function_help",
            "stage_battle_condition_target_label",
        }:
            raise SystemExit(f"gate failed: semantic category drift: {record_id}")
        before = {
            "source_text": row.get("source_text"),
            "translation_ko": row.get("translation_ko"),
            "translation_status": row.get("translation_status"),
        }
        row["source_text"] = source_text
        row["source_decode_status"] = "complete"
        row["source_unresolved_slots"] = []
        row["translation_ko"] = translation_ko
        row["translation_status"] = "translated"
        row["translation_source"] = "user_verified_runtime_screenshot"
        row["review_status"] = "user_verified"
        row["review_count"] = int(row.get("review_count") or 0) + 1
        row["reviewed_at"] = "2026-08-29"
        row["translator_notes"] = (
            str(row.get("translator_notes") or "").rstrip("; ")
            + "; runtime screenshot confirmed 12x12 intermission/development text path"
        ).lstrip("; ")
        row["qa_status"] = "runtime_issue_reproduced"
        row["overlay_batch_id"] = BATCH_ID
        update_payload_hash(row)
        changed.append(
            {
                "record_id": record_id,
                "target_file_offset": row.get("target_file_offset"),
                "semantic_category": row.get("semantic_category"),
                "before": before,
                "source_text": source_text,
                "translation_ko": translation_ko,
                "translation_payload_sha256": row["translation_payload_sha256"],
            }
        )

    changed.sort(key=lambda item: item["record_id"])
    parent_identity = str(merged.get("identity", {}).get("translation_overlay_identity_sha256") or "")
    followup_identity = digest(
        {
            "parent": parent_identity,
            "batch_id": BATCH_ID,
            "records": [
                {"record_id": item["record_id"], "payload": item["translation_payload_sha256"]}
                for item in changed
            ],
        }
    )
    identity = merged.setdefault("identity", {})
    identity["parent_translation_overlay_identity_sha256"] = parent_identity
    identity["intermission_development_fix_identity_sha256"] = followup_identity
    identity["translation_overlay_identity_sha256"] = followup_identity

    summary = merged.setdefault("summary", {})
    status_counts = dict(sorted(Counter(str(row.get("translation_status") or "") for row in merged["records"]).items()))
    summary["merged_translation_status_counts"] = status_counts
    summary["translated_canonical_records"] = sum(
        1
        for row in merged["records"]
        if row.get("scope_status") == "included" and row.get("translation_status") == "translated"
    )
    summary["untranslated_canonical_records"] = sum(
        1
        for row in merged["records"]
        if row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and row.get("translation_status") != "translated"
    )
    summary["translation_overlay_identity_sha256"] = followup_identity
    summary["intermission_development_fix_records"] = len(changed)
    merged["intermission_development_fix"] = {
        "batch_id": BATCH_ID,
        "parent_snapshot": args.source.name,
        "report": str(args.report.relative_to(ROOT)).replace("\\", "/"),
        "changed_records": len(changed),
        "identity_sha256": followup_identity,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": 1,
        "kind": "ggen_advance_intermission_development_fix",
        "batch_id": BATCH_ID,
        "source_snapshot": str(args.source.relative_to(ROOT)).replace("\\", "/"),
        "output_snapshot": str(args.out.relative_to(ROOT)).replace("\\", "/"),
        "identity_sha256": followup_identity,
        "records": changed,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "changed_records": len(changed), "identity_sha256": followup_identity}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
