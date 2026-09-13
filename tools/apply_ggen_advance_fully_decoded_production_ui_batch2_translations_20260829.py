#!/usr/bin/env python3
"""Fill newly closed production/UI pending rows after remaining-683 batch2.

Only singleton translation units whose decoded Japanese is a complete,
readable string are translated.  Empty rows, garbled leftover text, and
split translation units stay pending.  Unified source and ROM are not written;
this patches the derived merged sheet and writes a fingerprint overlay.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260829.json"
CLOSED = ROOT / "analysis" / "ggen_advance_8x16_closed_pending_after_batch2_20260829.json"
COMPACT = (
    ROOT
    / "analysis"
    / "ggen_advance_translation_overlays"
    / "fully_decoded_production_ui_batch2_compact_20260829.json"
)
OUT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260830.json"

# Readable Japanese only.  Missing keys are skipped on purpose.
JP_TO_KO: dict[str, str] = {
    "1T能力↑＋先制": "1턴 능력↑＋선제",
    "NT研所員": "NT연구소원",
    "……私に力を貸してほしい！": "……내게 힘을 빌려 줘!",
    "……駆け抜けるだけのこと！": "……스쳐 지나갈 뿐이야!",
    "「だから甘いというのだ……」": "「그래서 안일하다는 거다……」",
    "「アナタに力を……」": "「당신에게 힘을……」",
    "お前に勝つのは私だ！": "널 이기는 건 나다!",
    "かばう＋装甲↑": "엄호＋장갑↑",
    "これが私の戦争です！": "이게 내 전쟁이다!",
    "これは私闘です！！": "이건 사사로운 싸움이다!!",
    "これは駆け引きなのだよ……！": "이건 밀고 당기는 거야……!",
    "その名はガンダム": "그 이름은 건담",
    "どうしてもやると言うのなら……": "굳이 하겠다고 한다면……",
    "なんと無防備な！": "얼마나 무방비한 거야!",
    "バインダー武装ポッド": "바인더 무장 포드",
    "マツナガの家名にかけて……": "마츠나가의 가문에 맹세코……",
    "ミカムラ博士": "미카무라 박사",
    "ムダの一言！": "한마디로 헛수고다!",
    "作戦／戦況": "작전／전황",
    "僕らの時代の夜開けだ！": "우리 시대의 새벽이다!",
    "先制攻撃＋命中↑": "선제공격＋명중↑",
    "先制攻撃＋威力↑": "선제공격＋위력↑",
    "先制攻撃＋能力↑": "선제공격＋능력↑",
    "名にかけて！": "이 이름에 걸고!",
    "味方HP完全回復": "아군 HP 완전 회복",
    "回復させます": "회복시킵니다",
    "夜間 索敵中": "야간 색적 중",
    "大人しく武器を捨てやがれ！": "순순히 무기를 버려!",
    "威力↑＋封印": "위력↑＋봉인",
    "強者なんていない……！": "강자 따윈 없어……!",
    "必殺攻撃＋先制": "필살공격＋선제",
    "戦いの歴史は繰り返させません！": "싸움의 역사를 되풀이하지 않겠습니다!",
    "戦場を駆ける紅い稲妻……": "전장을 달리는 붉은 번개……",
    "撃つのか！？ 私を！！": "쏠 거냐!? 나를!!",
    "攻撃力↑＋先制": "공격력↑＋선제",
    "攻撃封印＋命中↑": "공격 봉인＋명중↑",
    "攻撃封印＋威力↑": "공격 봉인＋위력↑",
    "散開封印＋威力↑": "산개 봉인＋위력↑",
    "散開封印＋攻撃↑": "산개 봉인＋공격↑",
    "最後の勝利者": "최후의 승리자",
    "滅び行く者のために……": "멸망해 가는 자를 위해……",
    "滅び行く者のために……か": "멸망해 가는 자를 위해……인가",
    "自分HP完全回復": "자신 HP 완전 회복",
    "裁かれし者": "심판받은 자",
    "私……行きます！！": "저…… 갑니다!!",
    "私が生きのびねば……": "내가 살아남아야……",
    "私には見える……": "내게는 보여……",
    "私に甘えに来たまえ": "내게 기대러 오렴",
    "私はジオンの正義のために……": "나는 지온의 정의를 위해……",
    "私はニムバス・シュターゼン……": "나는 님버스 슈타젠……",
    "私は軍人なのだよ！": "나는 군인이라고!",
    "紅い稲妻の名……": "붉은 번개의 이름……",
}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    closed = json.loads(CLOSED.read_text(encoding="utf-8"))["rows"]
    merged = json.loads(MERGED.read_text(encoding="utf-8"))
    by_id = {row["record_id"]: row for row in merged["records"]}
    unit_members: dict[str, set[str]] = defaultdict(set)
    for row in merged["records"]:
        if row.get("scope_status") == "included" and row.get("translation_policy") == "translate":
            unit_members[str(row["translation_unit_id"])].add(row["record_id"])

    skipped = Counter()
    compact: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in closed:
        record_id = item["record_id"]
        jp = str(item["decoded_jp"] or "")
        if record_id in seen:
            continue
        if not jp.strip():
            skipped["empty"] += 1
            continue
        members = unit_members[str(by_id[record_id]["translation_unit_id"])]
        if len(members) != 1:
            skipped["split_unit"] += 1
            continue
        ko = JP_TO_KO.get(jp)
        if not ko:
            skipped["garbled_or_incomplete"] += 1
            continue
        seen.add(record_id)
        compact.append(
            {
                "record_id": record_id,
                "translation_ko": ko,
                "translation_status": "translated",
                "review_status": "draft",
                "translation_source": "curated_project_data",
                "translator_notes": f"slot-complete 8x16 after batch2; jp={jp}",
            }
        )

    envelope = {
        "schema_version": 1,
        "kind": "ggen_advance_translation_overlay",
        "batch_id": "fully-decoded-production-ui-batch2-20260829",
        "translation_source": "curated_project_data",
        "review_status": "draft",
        "records": compact,
    }
    COMPACT.parent.mkdir(parents=True, exist_ok=True)
    COMPACT.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for item in compact:
        row = by_id[item["record_id"]]
        row["translation_ko"] = item["translation_ko"]
        row["translation_status"] = "translated"
        row["review_status"] = "draft"
        row["translation_source"] = "curated_project_data"
        row["translator_notes"] = item["translator_notes"]
        row["overlay_batch_id"] = envelope["batch_id"]

    statuses = Counter(str(row.get("translation_status", "")) for row in merged["records"])
    translated_canonical = sum(
        1
        for row in merged["records"]
        if row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and row.get("translation_status") == "translated"
    )
    pending_canonical = sum(
        1
        for row in merged["records"]
        if row.get("scope_status") == "included"
        and row.get("translation_policy") == "translate"
        and row.get("translation_status") != "translated"
    )
    summary = merged.setdefault("summary", {})
    summary["translated_canonical_records"] = translated_canonical
    summary["untranslated_translate_policy_records"] = pending_canonical
    merged.setdefault("merged_translation_status_counts", {})
    merged["merged_translation_status_counts"] = dict(sorted(statuses.items()))
    if "summary" in merged and isinstance(merged["summary"], dict):
        merged["summary"]["merged_translation_status_counts"] = dict(sorted(statuses.items()))
        merged["summary"]["added_production_ui_batch2_translations"] = len(compact)

    OUT_MERGED.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    unique_jp = len({item["translator_notes"].split("jp=", 1)[-1] for item in compact})
    print(
        json.dumps(
            {
                "result": "PASS",
                "translated_rows": len(compact),
                "unique_jp": unique_jp,
                "skipped": dict(skipped),
                "translated_canonical_records": translated_canonical,
                "untranslated_translate_policy_records": pending_canonical,
                "overlay": str(COMPACT.relative_to(ROOT)),
                "merged": str(OUT_MERGED.relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
