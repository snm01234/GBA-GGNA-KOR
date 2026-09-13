#!/usr/bin/env python3
"""Fill fully-decoded production/UI pending rows with idiomatic Korean.

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
MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260828.json"
CLOSED = ROOT / "analysis" / "ggen_advance_8x16_closed_pending_after_a12_20260829.json"
COMPACT = ROOT / "analysis" / "ggen_advance_translation_overlays" / "fully_decoded_production_ui_a12_compact_20260829.json"
OUT_MERGED = ROOT / "analysis" / "ggen_advance_translation_merged_20260829.json"

# Readable Japanese only.  Missing keys are skipped on purpose.
JP_TO_KO: dict[str, str] = {
    "1Tハイパー化": "1턴 하이퍼화",
    "1T全能力↑": "1턴 전능력↑",
    "1T味方威力↑": "1턴 아군 위력↑",
    "1T味方防御↑": "1턴 아군 방어↑",
    "1T威力・命中↑": "1턴 위력·명중↑",
    "1T威力・装甲↑": "1턴 위력·장갑↑",
    "1T攻撃・防御↑": "1턴 공격·방어↑",
    "1T防御・命中↑": "1턴 방어·명중↑",
    "3Tハイパー化": "3턴 하이퍼화",
    "ECM！ 最大出力！！": "ECM! 최대 출력!!",
    "EXAMによって裁かれるがいい": "EXAM이 심판해 주마",
    "EXAM起動……": "EXAM 기동……",
    "HPを回復する": "HP를 회복한다",
    "IDコマンド封印": "ID 커맨드 봉인",
    "MSの性能を活かせぬまま……": "MS 성능을 살리지 못한 채……",
    "MSの格闘技を見せてやる！": "MS의 격투기를 보여 주마!",
    "SPを回復する": "SP를 회복한다",
    "……ごあいさつだな": "……인사치레로군",
    "……恥かかすんじゃねぇぞ！": "……망신 주지 마!",
    "……来る！？": "……온다!?",
    "……絶対に死ぬな！": "……절대 죽지 마!",
    "……遊んであげるからさ！": "……놀아 줄게!",
    "あたしゃ、今こそ戦うんだ！": "나는 지금이야말로 싸운다!",
    "あらゆる射撃攻撃を防ぐ": "모든 사격 공격을 막는다",
    "いけるぞ！ 一気にいく！": "된다! 단숨에 간다!",
    "いつまでガキの遊びを……": "언제까지 애들 장난을……",
    "うぉぉぉぉーー！": "우오오오오──!",
    "うわぁぁぁ！": "우와아아앗!",
    "お兄さまの力になりたい……": "오라버니의 힘이 되고 싶어……",
    "このっ！……このぉっ！！": "이 자식!……이 자식!!",
    "この戦い、我が祖国に捧げる！": "이 싸움, 조국에 바친다!",
    "こんな一方的な戦い……": "이런 일방적인 싸움이……",
    "しつこいのが信条だ！": "집요한 게 신조다!",
    "しぶとくなければ……": "질기지 않으면……",
    "そういう時は身を隠すんだ！": "그럴 땐 몸을 숨기는 거다!",
    "その他": "기타",
    "その機体では話にならんな！": "그 기체로는 얘기가 안 되겠군!",
    "だから甘いというのだ……": "그래서 안일하다는 거다……",
    "どんな運命だろうと戦いぬく！": "어떤 운명이든 끝까지 싸운다!",
    "なすべきことを見失った軍に……": "해야 할 일을 잃은 군대에게……",
    "なんとぉーっ！": "뭐라고어엇!",
    "まだ決着は着いていない……": "아직 결판은 나지 않았다……",
    "もう、やめろぉぉ！！": "이제 그만둬어!!",
    "もう誰も悲しませはしない！": "이제 아무도 슬프게 하지 않아!",
    "やられっぱなしじゃないんだ！": "당하기만 하는 게 아니라고!",
    "ようし、良い子だ……": "좋아, 착한 아이야……",
    "ア・バオア・クー宙域": "아 바오아 쿠 우주역",
    "イベント起動": "이벤트 기동",
    "オレの誇りのために戦う！": "내 긍지를 위해 싸운다!",
    "オレは死神じゃない！！": "난 사신이 아니야!!",
    "オレは負け犬にはならないぞ！": "난 패잔견이 되지 않아!",
    "オレは貴様らを認めない！": "난 너희를 인정하지 않는다!",
    "キャラ追加": "캐릭터 추가",
    "ククルス・ドアンの島": "쿠쿠르스 도안의 섬",
    "シャングリラの少年": "샹그리라의 소년",
    "ジオンの脅威": "지온의 위협",
    "スタックを撃破する": "스택을 격파한다",
    "ソロモン攻防戦": "솔로몬 공방전",
    "ゾンビ兵": "좀비병",
    "デルマイユ公爵": "델마이유 공작",
    "ドンパチ楽しもうじゃないか！": "한바탕 신나게 붙어 보자고!",
    "バルジ攻防戦": "벌지 공방전",
    "パーツの追加": "파츠 추가",
    "パーツ追加": "파츠 추가",
    "ビームによる射撃を防ぐ": "빔 사격을 막는다",
    "ビーム兵器を防ぐ": "빔 병기를 막는다",
    "ヘリオポリスの少年": "헬리오폴리스의 소년",
    "ボール射出": "볼 사출",
    "マッシュの仇よ……": "마슈의 원수여……",
    "ムーンレィスのための国家を！": "문레이스를 위한 국가를!",
    "メビウスの輪から": "뫼비우스의 고리에서",
    "ユウ・カジマ<イベント後>": "유 카지마<이벤트 후>",
    "ユニット追加": "유닛 추가",
    "ライゾウ・カッシュ": "라이조 캐시",
    "一覧": "일람",
    "世界が我らを抹殺するから……": "세계가 우리를 말살하려 하니까……",
    "人の生は何を成したかで決まる！": "사람의 삶은 무엇을 이뤘느냐로 정해진다!",
    "人は変わってゆくわ……": "사람은 변해 가는 거야……",
    "人は変わって行くものだろ？": "사람은 변해 가는 거잖아?",
    "何てお上手なんでしょ！": "정말 능숙하시네요!",
    "何て無謀な！": "얼마나 무모한 거야!",
    "何様のつもりだ！？": "네가 뭔데!?",
    "使用中": "사용 중",
    "信じるものの為には……": "믿는 것을 위해서라면……",
    "修正してやるっ！": "수정해 주마!",
    "先制攻撃": "선제공격",
    "全員レベル50にする": "전원을 레벨 50으로 만든다",
    "分身": "분신",
    "味方HP回復": "아군 HP 회복",
    "味方一人復活": "아군 1명 부활",
    "味方命中・威力↑": "아군 명중·위력↑",
    "味方威力・命中↑": "아군 위력·명중↑",
    "命中・威力↑": "명중·위력↑",
    "地下基地": "지하 기지",
    "地球は我々の手によって……": "지구는 우리 손에 의해……",
    "基地": "기지",
    "大きな、力……": "거대한, 힘……",
    "好きにさせるかよ！": "제멋대로 하게 둘 줄 알아!",
    "威力↑": "위력↑",
    "威力・命中↑": "위력·명중↑",
    "威力・装甲↑": "위력·장갑↑",
    "子供の間合いだな！": "애들 거리감이군!",
    "宇宙に散る星": "우주에 흩어지는 별",
    "射撃": "사격",
    "市街地": "시가지",
    "強制出撃": "강제 출격",
    "強制散開": "강제 산개",
    "強化人間だって……": "강화인간이라도……",
    "悲しみを増やしちゃいけない！": "슬픔을 늘리면 안 돼!",
    "成すべきことはひとつ！": "해야 할 일은 하나다!",
    "我々が起つのだ！！": "우리가 일어서는 거다!!",
    "戦いとは二手三手先を……": "싸움이란 두 수, 세 수 앞을……",
    "戦力増大": "전력 증대",
    "戦場": "전장",
    "戦闘力増大": "전투력 증대",
    "手動で移動可能に": "수동으로 이동 가능하게",
    "拡散メガ粒子砲": "확산 메가 입자포",
    "改造": "개조",
    "攻撃封印": "공격 봉인",
    "政府高官": "정부 고관",
    "散開することはありえません！": "산개할 수는 없습니다!",
    "散開封印": "산개 봉인",
    "敵を知り、己を知れば……": "적을 알고 나를 알면……",
    "敵威力↓": "적 위력↓",
    "敵威力・命中↓": "적 위력·명중↓",
    "敵威力・装甲↓": "적 위력·장갑↓",
    "敵行動封印": "적 행동 봉인",
    "敵防御力・命中↓": "적 방어력·명중↓",
    "暗礁宙域": "암초 우주역",
    "月光蝶": "월광접",
    "来るなぁーーっ！！": "오지 마아앗!!",
    "森林": "삼림",
    "目を覚ませ……": "정신 차려……",
    "破損中": "파손 중",
    "移動力↑": "이동력↑",
    "移動力強化": "이동력 강화",
    "粛清！ 粛清ぇーっ！！": "숙청! 숙처엉!!",
    "索敵": "색적",
    "索敵地上": "색적 지상",
    "索敵宇宙": "색적 우주",
    "脱出": "탈출",
    "自分HP回復": "자신 HP 회복",
    "自軍HP回復": "자군 HP 회복",
    "自軍攻撃・防御↑": "자군 공격·방어↑",
    "良いもの……なのですか？": "좋은 것……인가요?",
    "誰よりも戦い抜いて見せる！": "누구보다 끝까지 싸워 보이겠다!",
    "負けられないんだぁーっ！": "질 수 없다고오!",
    "連装砲": "연장포",
    "遊びじゃないんだぜ！": "장난이 아니라고!",
    "遊びをやってるつもりか！？": "장난하는 거냐!?",
    "防御・威力↑": "방어·위력↑",
    "黒い三連星のオルテガだ！": "검은 삼연성의 오르테가다!",
    "黒い三連星の実力……": "검은 삼연성의 실력……",
    "？？？": "???",
    "？？？？？": "?????",
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
                "translator_notes": f"slot-complete 8x16 after A12; jp={jp}",
            }
        )

    envelope = {
        "schema_version": 1,
        "kind": "ggen_advance_translation_overlay",
        "batch_id": "fully-decoded-production-ui-a12-20260829",
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
        merged["summary"]["added_production_ui_a12_translations"] = len(compact)

    OUT_MERGED.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "translated_rows": len(compact),
                "unique_jp": len({item["translator_notes"] for item in compact}),
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
