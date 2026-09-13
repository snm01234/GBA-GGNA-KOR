#!/usr/bin/env python3
"""Build the integrated Korean translation sheet source for G Generation Advance.

The production corpus (4,069 records) is the only input of record.  This tool
adds reviewed Korean text where the Japanese source is fully decoded and the
meaning is unambiguous (unit/character/weapon names, UI labels, stage names,
and short ability/part labels).  Unresolved Japanese glyphs are deliberately
left pending; no glyph is guessed.

The output JSON is an auditable intermediate for the single XLSX translation
sheet.  It also computes replacement byte lengths using the advance-local
Korean token assignment and emits a pointer-recalculation plan.  No ROM is
written here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

THIS_DIR = Path(__file__).resolve().parent
ADVANCE_DIR = THIS_DIR.parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import build_stage2_translation_master as stage2  # noqa: E402

ROM_BASE = 0x08000000
TEXT_START = 0x01040000
TEXT_END = 0x01240000
RELATIVE_BASE_FILE = 0x001BF908
RELATIVE_BASE_LITERAL_FILE = 0x0004DC54
RELATIVE_OFFSET_COUNT = 766
RELATIVE_TABLE_BYTES = (RELATIVE_OFFSET_COUNT + 3) * 2

CHARMAP_PATH = THIS_DIR.parent / "font_tables" / "ggen_advance_korean_charmap_plan_20260825.json"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"gate failed: {message}")


def norm_key(value: str) -> str:
    """Normalize JP keys without changing semantic text in the sheet."""
    value = unicodedata.normalize("NFKC", value)
    return (
        value.replace("\u3000", " ")
        .replace("－", "-")
        .replace("‐", "-")
        .replace("‑", "-")
        .replace("‒", "-")
        .replace("–", "-")
        .replace("—", "-")
        .strip()
    )


def ko_clean(value: str) -> str:
    """Keep the existing project convention but use ordinary sheet spaces."""
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u3000", " ")
    value = value.replace("－", "-")
    return value.strip()


def compact_key(value: str) -> str:
    return re.sub(r"[ \t\r\n]", "", norm_key(value))


def iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


CURATED_FILES = [
    "main_translation_glossary_ko.json",
    "unit_names_ko.json",
    "weapon_names_ko.json",
    "ui_menu_terms_ko.json",
    "ui_menu_terms2_ko.json",
    "ui_menu_terms3_ko.json",
    "ui_system_ko.json",
    "ui_battle_terms_ko.json",
    "ui_inplace_ko.json",
    "ui_mined_terms_ko.json",
    "menu_plate_labels_ko.json",
    "intermission_labels_ko.json",
    "broad_stage2_title_ui_ko.json",
    "stage_title_translations_ko.json",
    "stage_title_translations_ko_bold14.json",
    "id_command_plaque_translations_ko.json",
    "id_command_effect_width_ko.json",
    "id_command_dynamic_labels_followup_ko.json",
    "battle_ui_action_labels_ko.json",
    "battle_popup_glyph_translations_ko.json",
]


def curated_translation_maps() -> tuple[dict[str, str], dict[str, str]]:
    """Return exact and compact reviewed JP -> KO mappings.

    Legacy dialogue files are intentionally not scanned.  They contain many
    context-specific alternatives and do not establish a stable short-label
    translation for this GBA corpus.
    """
    exact: dict[str, str] = {}
    compact: dict[str, str] = {}

    def add(source: Any, target: Any) -> None:
        if not isinstance(source, str) or not isinstance(target, str):
            return
        source = norm_key(source)
        target = ko_clean(target)
        if not source or not target:
            return
        # First writer wins: the curated glossary is listed before broad UI
        # files, so a canonical proper noun cannot be overwritten by a noisy
        # compatibility entry.
        exact.setdefault(source, target)
        compact.setdefault(compact_key(source), target)

    data_dir = ADVANCE_DIR / "data"
    for filename in CURATED_FILES:
        path = data_dir / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in iter_dicts(payload):
            # Canonical glossary entries expose aliases and canonical_ko.
            jp = item.get("jp")
            target = item.get("canonical_ko") or item.get("user_confirmed_ko") or item.get("official_ko")
            if isinstance(jp, str) and isinstance(target, str):
                add(jp, target)
                for alias in item.get("aliases", []):
                    add(alias, target)
            # Most project data uses jp/source_text/original_text + ko.
            for source_key in ("jp", "source_text", "original_text", "before", "current"):
                add(item.get(source_key), item.get("ko"))

    return exact, compact


# Short, high-confidence labels used by the production semantic closure.
MANUAL_TRANSLATIONS: dict[str, str] = {
    # Series / title labels.
    "ガンダムW エンドレスワルツ": "건담 W: 엔드리스 왈츠",
    "∀ガンダム": "턴에이 건담",
    "0083スターダストメモリー": "0083 스타더스트 메모리",
    "MSV": "MSV",
    "ZMSV": "Z-MSV",
    "ガンダム・センチネル": "건담 센티넬",
    "ギャザービート": "개더 비트",
    "ア・バオア・クー": "아 바오아 쿠",
    "アクシズ": "액시즈",
    "コロニー": "콜로니",
    "クレーター": "크레이터",
    "オアシス": "오아시스",
    "バルジ": "발지",
    "月": "달",
    "ジャンクヤード": "정크 야드",
    "デビルコロニー": "데빌 콜로니",
    # Stage/map labels.
    "ニューヤーク": "뉴야크",
    "オデッサ": "오데사",
    "フォン・シティ": "폰 시티",
    "アリス・スプリングス": "앨리스 스프링스",
    "シャングリラ": "샹그릴라",
    "サイド1コロニー": "사이드 1 콜로니",
    "ムーンレィス": "문레이스",
    # Battle/UI labels.
    "スペシャル": "스페셜",
    "ノーマル": "노멀",
    "デバッグモード": "디버그 모드",
    "バックステージ": "백스테이지",
    "オマケBGM": "보너스 BGM",
    "プロフィール<パイロット": "프로필<파일럿",
    "プロフィール<ユニット": "프로필<유닛",
    # Ability / defence / part labels.
    "ビームコート": "빔 코팅",
    "Iフィールド": "I 필드",
    "Pディフェンサー": "P 디펜서",
    "FFバリア": "FF 배리어",
    "バイオフィールド": "바이오 필드",
    "月光蝶": "월광접",
    "カスタムパーツ": "커스텀 파츠",
    "クリアランスパーツ": "클리어런스 파츠",
    "アップグレードパーツ": "업그레이드 파츠",
    "ハイクリアランスパーツ": "하이 클리어런스 파츠",
    "ハイグレードパーツ": "하이그레이드 파츠",
    "陸戦キット": "지상전 키트",
    "スナイパーライフル": "스나이퍼 라이플",
    "ビームキャノン": "빔 캐논",
    "ガンダリウムγ": "건다리움 γ",
    "ムーバブルフレーム": "무버블 프레임",
    "可変フレーム": "가변 프레임",
    "高機動スラスター": "고기동 슬러스터",
    "メガバズーカランチャー": "메가 바주카 런처",
    "ハイメガキャノン": "하이메가 캐논",
    "アーマーユニット": "아머 유닛",
    "ディフェンサーユニット": "디펜서 유닛",
    "BWS": "BWS",
    "アームドベース": "암드 베이스",
    "ベクタードスラスター": "벡터드 슬러스터",
    "サラミス砲": "살라미스 포",
    "インコム": "인컴",
    "バイオセンサー": "바이오센서",
    "サイココントローラー": "사이코 컨트롤러",
    "サイコフレーム": "사이코 프레임",
    "マグネットコーティング": "마그넷 코팅",
    "フィンファンネル": "핀 판넬",
    # A few canonical compounds that need a natural Korean spacing/reading.
    "コア・ブースター": "코어 부스터",
    "シャア専用ザク": "샤아 전용 자쿠",
    "ライデン専用ザク": "라이덴 전용 자쿠",
    "イフリート改": "이프리트 개량형",
    "NT試験用ジム ジャグラー": "NT 시험용 짐 저글러",
    "ドム・トローペン": "돔 트로펜",
    "陸戦型ガンダム": "육전형 건담",
    "ゲルググM": "겔구그 M",
    "ジムカスタム": "짐 커스텀",
    "シャア専用ズゴック": "샤아 전용 즈고크",
    "ズゴックE": "즈고크 E",
    "Ez8": "Ez8",
    "Ez8改": "Ez8 개량형",
    "Ez8ハイモビリティーカスタム": "Ez8 하이 모빌리티 커스텀",
    "アプサラスⅡ": "아프사라스 II",
    "アプサラスⅢ": "아프사라스 III",
    "ガンダムMkⅡ": "건담 Mk-II",
    "ガンダムMkⅡ0号機": "건담 Mk-II 0호기",
    "キュベレイMkⅡ": "큐베레이 Mk-II",
    "GP01 ゼフィランサス": "GP01 제피랜서스",
    "GP01 フルバーニアン": "GP01 풀 버니언",
    "GP02 サイサリス": "GP02 사이살리스",
    "GP03S ステイメン": "GP03S 스테이맨",
    "GP03D デンドロビウム": "GP03D 덴드로비움",
    "リック・ディアス": "릭 디아스",
    "リックディアスS": "릭 디아스 S",
    "スーパーガンダム": "슈퍼 건담",
    "フルアーマー百式改": "풀 아머 백식 개량형",
    "R・ジャジャ": "R 자자",
    "Zガンダム": "Z건담",
    "ウェーブライダー": "웨이브 라이더",
    "エールストライクガンダム": "에일 스트라이크 건담",
    "スモー シルバータイプ": "스모 실버 타입",
    "イージスガンダム": "이지스 건담",
    "ヤクト・ドーガ": "야크트 도가",
    "Vダッシュガンダム": "V 대시 건담",
    "ドーベンウルフ": "도벤 울프",
    "リ・ガズィ": "리 가지",
    "リ・ガズィ<BWS>": "리 가지<BWS>",
    "スペリオルガンダム": "S 건담",
    "ウィングガンダム": "윙 건담",
    "ウィングガンダム バード": "윙 건담 버드",
    "シャイニングガンダム": "샤이닝 건담",
    "ZZガンダム": "ZZ건담",
    "Gフォートレス": "G 포트리스",
    "フルアーマーZZ": "풀 아머 ZZ",
    "クーロンガンダム": "쿠롱 건담",
    "∀ガンダム<∀99>": "턴에이 건담<턴에이99>",
    "∀ガンダム<月光蝶>": "턴에이 건담<월광접>",
    "ガンダムアシュタロン": "건담 아슈타론",
    "ガンダムヴァサーゴ": "건담 바사고",
    "F91": "F91",
    "V2ガンダム": "V2 건담",
    "αアジール": "알파 아질",
    "ガンダムエピオン": "건담 에피온",
    "ガンダムX": "건담 X",
    "ガンダムX<サテライト>": "건담 X<새틀라이트>",
    "フリーダムガンダム": "프리덤 건담",
    "ストライク・ルージュ": "스트라이크 루주",
    "ストライクルージュ": "스트라이크 루주",
    "トールギス": "톨기스",
    "リリー・マルレーン": "릴리 말레렌",
    "ホワイトベース": "화이트 베이스",
    "ネェル・アーガマ": "네일 아가마",
    "レウルーラ": "레우루라",
    "ヴェサリウス": "베사리우스",
    "アルマイヤー": "알마이어",
    "アークエンジェル": "아크엔젤",
    "ピースミリオン": "피스밀리온",
    "リーブラ": "리브라",
}

# GBA's production corpus uses a compact set of canonical MS/pilot/ship names
# that is broader than the older WSC glossary.  These are explicit so a
# transliterator never emits awkward syllable-by-syllable readings such as
# "구후" for グフ or "도무" for ドム.
MANUAL_TRANSLATIONS.update({
    # Character / pilot names.
    "アイシャ": "아이샤", "アイナ・サハリン": "아이나 사할린", "アスラン・ザラ": "아스란 자라",
    "アナベル・ガトー": "아나벨 가토", "アムロ・レイ": "아무로 레이", "アルフ・カムラ": "알프 카무라",
    "アルファ・A・ベイト": "알파 A 베이트", "アレックス": "알렉스", "イーノ・アッバーブ": "이노 아바브",
    "ウッディ": "우디", "ウラガン": "우라간", "エイパー・シナプス": "에이퍼 시냅스",
    "エギーユ・デラーズ": "에규 데라즈", "エル・ビアンノ": "엘 비안노", "オルテガ": "오르테가",
    "オルバ・フロスト": "올바 프로스트", "カイ・シデン": "카이 시덴", "ガイア": "가이아",
    "カミーユ・ビダン": "카미유 비단", "ガルマ・ザビ": "가르마 자비", "カレン・ジョシュア": "카렌 조슈아",
    "ガロード・ラン": "가로드 란", "キシリア・ザビ": "키시리아 자비", "ギニアス・サハリン": "기니어스 사할린",
    "キャスバル": "캐스발", "キラ・ヤマト": "키라 야마토", "キリング": "킬링", "ギレン・ザビ": "기렌 자비",
    "ククルス・ドアン": "쿠쿠루스 도안", "クラウレ・ハモン": "클라우레 하몬", "クランプ": "클램프",
    "クリス": "크리스", "ケリィ・レズナー": "케리 레즈너", "コウ・ウラキ": "코우 우라키",
    "サウス・バニング": "사우스 버닝", "サマナ・フュリス": "사마나 퓨리스", "シーブック・アノー": "시북 아노",
    "シーマ・ガラハウ": "시마 가라하우", "シャア・アズナブル": "샤아 아즈나블", "シャギア・フロスト": "샤기아 프로스트",
    "ジャミトフ・ハイマン": "자미토프 하이만", "シュタイナー": "슈타이너", "ジュドー・アーシタ": "쥬도 아시타",
    "ジョニー・ライデン": "조니 라이덴", "シロー・アマダ": "시로 아마다", "シン・マツナガ": "신 마츠나가",
    "スレッガー・ロウ": "슬레거 로우", "セイラ・マス": "세이라 마스", "ゼクス・マーキス": "젝스 마키스",
    "ゼロ・ムラサメ": "제로 무라사메", "プロト・ゼロ": "프로토 제로", "チャック・キース": "척 키스",
    "チャップ・アデル": "채프 아델", "ティアンム": "티안무", "ティファ・アディール": "티파 아딜",
    "デギン・ザビ": "데긴 자비", "デトローフ・コッセル": "데트로프 콧셀", "テリー・サンダース": "테리 샌더스",
    "ドクターJ": "닥터 J", "ドズル・ザビ": "도즐 자비", "ドモン・カッシュ": "도몬 캇슈",
    "ナタル・バジルール": "나탈 바지룰", "ニナ・パープルトン": "니나 퍼플턴", "ニムバス": "님버스",
    "ノイエン・ビッター": "노이에른 비터", "ノリス・パッカード": "노리스 패커드", "バーニィ": "버니",
    "バスク・オム": "바스크 옴", "ハマーン・カーン": "하만 칸", "ハヤト・コバヤシ": "하야토 코바야시",
    "ハリー・オード": "해리 오드", "バルトフェルド": "발트펠트", "ハンゲルグ": "한게르그",
    "ビーチャ・オーレグ": "비챠 올레그", "ヒイロ・ユイ": "히이로 유이", "フィリップ・ヒューズ": "필리프 휴즈",
    "フィル・アッカマン": "필 아카만", "ブライト・ノア": "브라이트 노아", "フランクリン・ビダン": "프랭클린 비단",
    "プリベンター・W": "프리벤터 W", "ベルナルド・モンシア": "베르나르도 몬시아", "ポゥ・エイジ": "포우 에이지",
    "マ・クベ": "마 쿠베", "マーカー・クラン": "마커 클랜", "マチルダ・アジャン": "마틸다 아쟌",
    "マッシュ": "마슈", "マリオン・ウェルチ": "마리온 웰치", "マリュー・ラミアス": "마류 라미아스",
    "ミーシャ": "미샤", "ミカムラ": "미카무라", "ミュラー": "뮐러", "ミリアルド": "밀리아르도",
    "ムウ・ラ・フラガ": "무 라 프라가", "モーリン・キタムラ": "모린 키타무라", "モンド・アガケ": "몬도 아가케",
    "ヤザン・ゲーブル": "야잔 게이블", "ユウ・カジマ": "유우 카지마", "ラウ・ル・クルーゼ": "라우 르 크루제",
    "ララァ・スン": "라라아 슨", "ランバ・ラル": "람바 랄", "リィナ・アーシタ": "리나 아시타",
    "ルクレツィア・ノイン": "루크레치아 노인", "レイラ・レイモンド": "레이라 레이먼드", "レイン・ミカムラ": "레인 미카무라",
    "レビル": "레빌", "ローラ・ローラ": "로라 로라", "ロラン・セアック": "로랑 세아크", "ロラン・チュアン": "로랑 추안",
    "ワッケイン": "왓케인", "カガリ": "카가리", "ウズミ": "우즈미", "MDシステム": "MD 시스템",
    "MD<A・R>": "MD<A-R>", "Fシステム": "F 시스템", "ジオンNT": "지온 NT", "シルエット": "실루엣",
    "ネオジオンNT": "네오지온 NT", "レジスタンス": "레지스탕스", "アスラン・ザラ<ザフト>": "아스란 자라<자프트>",
    "ウッディ・マルデン": "우디 마르덴", "ガイア1": "가이아 1", "ガイア2": "가이아 2",
    "カミーユ・ビダン<ハイパー>": "카미유 비단<하이퍼>", "キャスバル・レム・ダイクン": "캐스발 렘 다이쿤",
    "ククルス・ドアン<ハイパー>": "쿠쿠루스 도안<하이퍼>", "クリスチーナ・マッケンジー": "크리스티나 맥켄지",
    "シュタイナー・ハーディ": "슈타이너 하디", "シロー・アマダ<ハイパー>": "시로 아마다<하이퍼>",
    "ニムバス・シュターゼン": "님버스 슈타젠", "バーナード・ワイズマン": "버나드 와이즈먼",
    "アンドリュー・バルトフェルド": "앤드루 발트펠트", "ハンゲルグ・エヴィン": "한게르그 에빈",
    "プリベンター・ウィンド": "프리벤터 윈드", "ミハイル・カミンスキー": "미하일 카민스키",
    "ミリアルド・ピースクラフト": "밀리아르도 피스크래프트", "カガリ・ユラ・アスハ": "카가리 유라 아스하",
    "ウズミ・ナラ・アスハ": "우즈미 나라 아스하",
    # Mobile suits / ships.
    "ザクⅡ ドアン機": "자쿠II 도안전용기", "ザクⅡ ドアン機 スーパー": "자쿠II 도안전용기 슈퍼",
    "ザクⅡF": "자쿠 II F", "ザクⅡJ": "자쿠 II J", "ジム": "짐", "アプサラスⅡ": "아프사라스 II",
    "グフ": "구프", "コア・ブースター": "코어 부스터", "シャア専用ザク": "샤아 전용 자쿠", "ライデン専用ザク": "라이덴 전용 자쿠",
    "イフリート改": "이프리트 개량형", "ガンタンク": "건탱크", "ザクⅡFZ": "자쿠 II FZ", "ジム・コマンド": "짐 커맨드",
    "ズゴック": "즈고크", "ドム": "돔", "ハイゴッグ": "하이곡", "ビグロ": "빅로", "BDⅠ": "BD I", "エルメス": "엘메스",
    "ガンキャノン": "건캐논", "グフカスタム": "구프 커스텀", "ゲルググ": "겔구그", "NT試験用ジム ジャグラー": "NT 시험용 짐 저글러",
    "ドム・トローペン": "돔 트로펜", "陸戦型ガンダム": "육전형 건담", "ゲルググM": "겔구그 M", "ジムカスタム": "짐 커스텀",
    "シャア専用ズゴック": "샤아 전용 즈고크", "ズゴックE": "즈고크 E", "Ez8": "Ez8", "Ez8改": "Ez8 개량형",
    "Ez8ハイモビリティーカスタム": "Ez8 하이 모빌리티 커스텀", "アプサラスⅢ": "아프사라스 III", "ゲルググJG": "겔구그 JG",
    "ジムキャノンⅡ": "짐 캐논 II", "ドム・バインニヒツ": "돔 바인니히츠", "MCガンダム": "MC 건담", "ヴァル・ヴァロ": "발 바르",
    "ガザC": "가자 C", "ジムⅡ": "짐 II", "ドム・グロースバイル": "돔 그로스바일", "ハイザック": "하이잭", "BDⅡ": "블루 데스티니 II",
    "BDⅢ": "블루 데스티니 III", "NT-1 アレックス": "NT-1 알렉스", "アレックスFA": "알렉스 FA", "ケンプファー": "캠퍼",
    "GP01 ゼフィランサス": "GP01 제피랜서스", "GP01 フルバーニアン": "GP01 풀 버니언", "ガザD": "가자 D", "デスアーミー": "데스 아미",
    "バーザム": "바잠", "リック・ディアス": "릭 디아스", "GP02 サイサリス": "GP02 사이살리스", "GP03S ステイメン": "GP03S 스테이맨",
    "GP03D デンドロビウム": "GP03D 덴드로비움", "ガンダムMkⅡ": "건담 Mk-II", "スーパーガンダム": "슈퍼 건담", "ガンダムMkⅡ0号機": "건담 Mk-II 0호기",
    "ジムⅢ": "짐 III", "ドライセン": "드라이센", "フラット": "플랫", "ガーベラ・テトラ": "가베라 테트라", "ガザE": "가자 E", "ジン": "진",
    "メタス": "메타스", "ザクⅢ": "자쿠 III", "ストライクガンダム": "스트라이크 건담", "ストライクガンダム<グレー>": "스트라이크 건담<그레이>",
    "リックディアスS": "릭 디아스 S", "スーパーディアス": "슈퍼 디아스", "ノイエ・ジール": "노이에 질", "百式": "백식", "ジェガン": "제간",
    "バクゥ": "바쿠", "キュベレイMkⅡ": "큐베레이 Mk-II", "ギラ・ドーガ": "기라 도가", "サイコガンダム": "사이코 건담", "トーラス": "토러스",
    "ウォドム": "워돔", "ガンダムMkⅤ": "건담 Mk-V", "ビルゴⅠ": "빌고 I", "百式改": "백식 개량형", "フルアーマー百式改": "풀 아머 백식 개량형",
    "量産型キュベレイ": "양산형 큐베레이", "R・ジャジャ": "R 자자", "Zガンダム": "Z건담", "ウェーブライダー": "웨이브 라이더",
    "エールストライクガンダム": "에일 스트라이크 건담", "エールストライクガンダム<グレー>": "에일 스트라이크 건담<그레이>",
    "スモー シルバータイプ": "스모 실버 타입", "イージスガンダム": "이지스 건담", "イージスガンダム<グレー>": "이지스 건담<그레이>",
    "グロムリン": "그롬린", "ヤクト・ドーガ": "야크트 도가", "Vガンダム": "V건담", "Vダッシュガンダム": "V 대시 건담",
    "ドーベンウルフ": "도벤 울프", "ビルゴⅡ": "빌고 II", "リ・ガズィ": "리 가지", "リ・ガズィ<BWS>": "리 가지<BWS>",
    "ヴァイエィト": "바이에이트", "ザクⅢ改": "자쿠 III 개량형", "スペリオルガンダム": "S건담", "メリクリウス": "메리크리우스",
    "ウィングガンダム": "윙 건담", "ウィングガンダム バード": "윙 건담 버드", "シャイニングガンダム": "샤이닝 건담",
    "シャイニングガンダム スーパー": "샤이닝 건담 슈퍼", "ZZガンダム": "ZZ건담", "Gフォートレス": "G 포트리스", "フルアーマーZZ": "풀 아머 ZZ",
    "クーロンガンダム": "쿠롱 건담", "ガンダムアシュタロン": "건담 아슈타론", "ガンダムヴァサーゴ": "건담 바사고", "スモー ゴールドタイプ": "스모 골드 타입",
    "F91": "F91", "V2ガンダム": "V2 건담", "αアジール": "알파 아질", "ガンダムエピオン": "건담 에피온", "サザビー": "사자비",
    "ガンダムX": "건담 X", "ガンダムX<サテライト>": "건담 X<새틀라이트>", "フリーダムガンダム": "프리덤 건담", "∀ガンダム<∀99>": "턴에이 건담<턴에이99>",
    "∀ガンダム<月光蝶>": "턴에이 건담<월광접>", "グロムリン・フォズィル": "그롬린 포실", "エールストライク<ナチュラル>": "에일 스트라이크<내추럴>",
    "エールストライク<ナチュラル・グレー>": "에일 스트라이크<내추럴 그레이>", "ストライク・ルージュ": "스트라이크 루주", "トールギス": "톨기스",
    "ドモン": "도몬", "ギャロップ": "갤롭", "シャトル": "셔틀", "サラミス": "살라미스", "ムサイ": "무사이", "ガウ": "가우", "マゼラン": "마젤란",
    "ザンジバル": "잔지바르", "ホワイトベース": "화이트 베이스", "グワジン": "그와진", "ペガサス": "페가수스", "グワデン": "그와덴",
    "リリー・マルレーン": "릴리 말레렌", "アルビオン": "알비온", "アーガマ": "아가마", "アレキサンドリア": "알렉산드리아", "ピースミリオン": "피스밀리온",
    "ネェル・アーガマ": "네일 아가마", "レウルーラ": "레우루라", "ヴェサリウス": "베사리우스", "アルマイヤー": "알마이어", "アークエンジェル": "아크엔젤", "リーブラ": "리브라",
    # Weapons.
    "ザクマシンガン": "자쿠 머신건", "ヒートホーク": "히트 호크", "ザクバズーカ": "자쿠 바주카", "ミサイルポッド": "미사일 포드",
    "ビームスプレーガン": "빔 스프레이 건", "ビームサーベル": "빔 사벨", "バズーカ": "바주카", "メガ粒子砲": "메가 입자포", "ヒートロッド": "히트 로드",
    "ヒートサーベル": "히트 사벨", "フィンガーバルカン": "핑거 발칸", "ビーム砲": "빔포", "ミサイル": "미사일", "ミサイルランチャー": "미사일 런처",
    "キャノン砲": "캐논포", "マシンガン": "머신건", "シュツルム・ファウスト": "슈투룸 파우스트", "ビームガン": "빔 건", "クローバイスビーム": "클로비스 빔",
    "クロー": "클로", "ジャイアント・バズ": "자이언트 바주카", "ビーム・カノン": "빔 캐논", "ビームライフル": "빔 라이플", "ガトリングガン": "개틀링 건",
    "ビームナギナタ": "빔 나기나타", "ラケーテン・バズ": "라케텐 바주카", "ハイパーバズーカ": "하이퍼 바주카", "ナックルシールド": "너클 실드", "ジム・ライフル": "짐 라이플",
    "ビームスプレーガンⅡ": "빔 스프레이 건 II", "サラミス砲": "살라미스 포", "ビームマシンガン": "빔 머신건", "ビームキャノン": "빔 캐논", "プラズマリーダー": "플라즈마 리더",
    "ナックルバスター": "너클 버스터", "ヒートナイフ": "히트 나이프", "ザクマシンガン改": "자쿠 머신건 개량형", "EXAM": "EXAM", "ショットガン": "샷건", "チェーンマイン": "체인 마인",
    "ビームピストル": "빔 피스톨", "クレイバズーカ": "클레이 바주카", "バルカン": "발칸", "アトミックバズーカ": "아토믹 바주카", "フォールディングバズーカ": "폴딩 바주카",
    "コンテナミサイル": "컨테이너 미사일", "メガビーム砲": "메가 빔포", "マイクロミサイル": "마이크로 미사일", "ロングライフル": "롱 라이플", "トライブレード": "트라이 블레이드",
    "ビームトマホーク": "빔 토마호크", "ハンドガン": "핸드건", "ビームカノン": "빔 캐논", "アームビームガン": "암 빔 건", "イーゲルシュテルン": "이겔슈테른",
    "アーマーシュナイダー": "아머 슈나이더", "ロングバズーカ": "롱 바주카", "メガカノン砲": "메가 캐논포", "メガバズーカランチャー": "메가 바주카 런처", "グレネードランチャー": "그레네이드 런처",
    "インコム": "인컴", "ビームガトリングガン": "빔 개틀링 건", "アクティブカノン": "액티브 캐논", "ハイパーメガランチャー": "하이퍼 메가 런처", "ヒートファン": "히트 팬",
    "Iフィールド・サーベル": "I 필드 사벨", "スキュラ": "스큐라", "ヴァリアブル・メガ粒子砲": "가변 메가 입자포", "ビームアサルトライフル": "빔 어설트 라이플",
    "オーバーハングキャノン": "오버행 캐논", "メガランチャー": "메가 런처", "メガビームキャノン": "메가 빔 캐논", "ビームスマートガン": "빔 스마트 건", "クラッシュシールド": "크래시 실드",
    "バスターライフル": "버스터 라이플", "マシンキャノン": "머신 캐논", "シャイニングショット": "샤이닝 샷", "シャイニングフィンガー": "샤이닝 핑거", "ダブルビームライフル": "더블 빔 라이플",
    "ハイパービームサーベル": "하이퍼 빔 사벨", "ハイメガキャノン": "하이메가 캐논", "クーロンクロス": "쿠롱 크로스", "ニューハイパーバズーカ": "뉴 하이퍼 바주카", "アトミックシザース": "아토믹 시저스",
    "シザースビーム砲": "시저스 빔포", "ノーズビーム砲": "노즈 빔포", "クロービーム砲": "클로 빔포", "ヴェスバー": "베스바", "MPRビームライフル": "MPR 빔 라이플",
    "マルチプルランチャー": "멀티플 런처", "ビームショットライフル": "빔 샷 라이플", "シールドバスターライフル": "실드 버스터 라이플", "ブレストバルカン": "브레스트 발칸", "サテライトキャノン": "새틀라이트 캐논",
    "クスフィアス": "크시피어스", "バラエーナ": "발라에나", "マルチパーパスサイロ": "멀티 퍼포즈 사일로", "ガンダムハンマー": "건담 해머", "ドーバーガン": "도버 건",
    "マスタークロス": "마스터 크로스", "J型ミサイル": "J형 미사일", "ハイパーメガ粒子砲": "하이퍼 메가 입자포", "サブメガ粒子砲": "서브 메가 입자포", "CIWS": "CIWS", "ビームホイール": "빔 휠",
    "ローエングリン": "로엔그린", "ゴットフリート": "고트프리트", "バリアント": "바리언트", "スレッジハマー": "슬레지 해머",
})

MANUAL_TRANSLATIONS_NORMALIZED = {norm_key(key): value for key, value in MANUAL_TRANSLATIONS.items()}
MANUAL_TRANSLATIONS_COMPACT = {compact_key(key): value for key, value in MANUAL_TRANSLATIONS.items()}


# Loanwords are applied after exact/compound lookup and before mora-level
# transliteration.  They make short labels read naturally rather than as a
# mechanical katakana-by-katakana transcription.
LOANWORD_MAP: dict[str, str] = {
    "ビーム": "빔",
    "ライフル": "라이플",
    "サーベル": "사벨",
    "バズーカ": "바주카",
    "ミサイル": "미사일",
    "キャノン": "캐논",
    "ランチャー": "런처",
    "シールド": "실드",
    "マシンガン": "머신건",
    "ガン": "건",
    "ナギナタ": "나기나타",
    "バルカン": "발칸",
    "メガ": "메가",
    "グレネード": "그레네이드",
    "ショットガン": "샷건",
    "チェーンマイン": "체인 마인",
    "ハンマー": "해머",
    "フィンガー": "핑거",
    "トマホーク": "토마호크",
    "ファウスト": "파우스트",
    "プラズマ": "플라즈마",
    "リーダー": "리더",
    "スプレー": "스프레이",
    "カノン": "캐논",
    "カスタム": "커스텀",
    "クリアランス": "클리어런스",
    "アップグレード": "업그레이드",
    "ハイグレード": "하이그레이드",
    "スナイパー": "스나이퍼",
    "フレーム": "프레임",
    "スラスター": "슬러스터",
    "アーマー": "아머",
    "ユニット": "유닛",
    "ディフェンサー": "디펜서",
    "サイコ": "사이코",
    "コントローラー": "컨트롤러",
    "センサー": "센서",
    "コーティング": "코팅",
    "フィールド": "필드",
    "バリア": "배리어",
    "モビルスーツ": "모빌슈트",
    "モビルアーマー": "모빌아머",
    "コロニー": "콜로니",
    "ブースター": "부스터",
    "フォートレス": "포트리스",
    "ストライク": "스트라이크",
    "フリーダム": "프리덤",
    "シャイニング": "샤이닝",
    "スペシャル": "스페셜",
    "ノーマル": "노멀",
    "プロフィール": "프로필",
    "パイロット": "파일럿",
    "デバッグ": "디버그",
    "モード": "모드",
    "オマケ": "보너스",
    "ステータス": "상태",
    "ステージ": "스테이지",
    "タイトル": "타이틀",
    "システム": "시스템",
}


# Mora table for proper names not covered by the curated glossary.  Longest
# keys are selected first.  ン/ッ are attached as final consonants below.
KATA_MORA: dict[str, str] = {
    "キャ": "캬", "キュ": "큐", "キョ": "쿄", "ギャ": "갸", "ギュ": "규", "ギョ": "교",
    "シャ": "샤", "シュ": "슈", "ショ": "쇼", "ジャ": "자", "ジュ": "주", "ジョ": "조",
    "チャ": "차", "チュ": "추", "チョ": "초", "ニャ": "냐", "ニュ": "뉴", "ニョ": "뇨",
    "ヒャ": "햐", "ヒュ": "휴", "ヒョ": "효", "ビャ": "뱌", "ビュ": "뷰", "ビョ": "뵤",
    "ピャ": "퍄", "ピュ": "퓨", "ピョ": "표", "ミャ": "먀", "ミュ": "뮤", "ミョ": "묘",
    "リャ": "랴", "リュ": "류", "リョ": "료", "ファ": "파", "フィ": "피", "フェ": "페", "フォ": "포",
    "ウィ": "위", "ウェ": "웨", "ウォ": "워", "ヴァ": "바", "ヴィ": "비", "ヴェ": "베", "ヴォ": "보",
    "イェ": "예", "チェ": "체", "シェ": "셰", "ジェ": "제",
    "ア": "아", "イ": "이", "ウ": "우", "エ": "에", "オ": "오",
    "カ": "카", "キ": "키", "ク": "쿠", "ケ": "케", "コ": "코",
    "ガ": "가", "ギ": "기", "グ": "구", "ゲ": "게", "ゴ": "고",
    "サ": "사", "シ": "시", "ス": "스", "セ": "세", "ソ": "소",
    "ザ": "자", "ジ": "지", "ズ": "즈", "ゼ": "제", "ゾ": "조",
    "タ": "타", "チ": "치", "ツ": "츠", "テ": "테", "ト": "토",
    "ダ": "다", "ヂ": "지", "ヅ": "즈", "デ": "데", "ド": "도",
    "ナ": "나", "ニ": "니", "ヌ": "누", "ネ": "네", "ノ": "노",
    "ハ": "하", "ヒ": "히", "フ": "후", "ヘ": "헤", "ホ": "호",
    "バ": "바", "ビ": "비", "ブ": "부", "ベ": "베", "ボ": "보",
    "パ": "파", "ピ": "피", "プ": "푸", "ペ": "페", "ポ": "포",
    "マ": "마", "ミ": "미", "ム": "무", "メ": "메", "モ": "모",
    "ヤ": "야", "ユ": "유", "ヨ": "요", "ラ": "라", "リ": "리", "ル": "루", "レ": "레", "ロ": "로",
    "ワ": "와", "ヲ": "오", "ヰ": "이", "ヱ": "에",
}

KANJI_WORD_MAP: dict[str, str] = {
    "専用": "전용",
    "試験用": "시험용",
    "小隊": "소대",
    "量産型": "양산형",
    "陸戦型": "육전형",
    "高機動": "고기동",
    "可変": "가변",
    "機": "기",
    "型": "형",
    "改": "개량형",
    "砲": "포",
    "月光蝶": "월광접",
    "粒子": "입자",
    "戦": "전투",
    "地": "지상",
    "上": "상",
    "中": "중",
    "小": "소",
    "大": "대",
    "隊": "대",
    "プロフィール": "프로필",
}


def replace_longest(value: str, mapping: dict[str, str]) -> str:
    for source in sorted(mapping, key=len, reverse=True):
        value = value.replace(source, mapping[source])
    return value


def attach_final(char: str, final_index: int) -> str:
    code = ord(char)
    if not 0xAC00 <= code <= 0xD7A3:
        return char
    syllable = code - 0xAC00
    if syllable % 28:
        return char
    return chr(code + final_index)


def transliterate_fragment(value: str) -> tuple[str, bool]:
    """Transliterate a short JP label and report remaining JP characters."""
    value = norm_key(value)
    value = value.replace("∀", "턴에이 ").replace("α", "알파 ").replace("ν", "뉴 ")
    value = value.replace("・", " ")
    value = replace_longest(value, KANJI_WORD_MAP)
    value = replace_longest(value, LOANWORD_MAP)

    out: list[str] = []
    unknown_japanese = False
    index = 0
    while index < len(value):
        # Tags may contain Japanese variant names but should remain visibly
        # delimited in the sheet.
        if value[index] == "<":
            end = value.find(">", index + 1)
            if end >= 0:
                inner, inner_unknown = transliterate_fragment(value[index + 1:end])
                out.append("<" + inner + ">")
                unknown_japanese |= inner_unknown
                index = end + 1
                continue
        if value[index] == "ー":
            index += 1
            continue
        if value[index] == "ン":
            if out and 0xAC00 <= ord(out[-1]) <= 0xD7A3:
                out[-1] = attach_final(out[-1], 4)  # ㄴ
            else:
                out.append("ㄴ")
            index += 1
            continue
        if value[index] == "ッ":
            if out and 0xAC00 <= ord(out[-1]) <= 0xD7A3:
                out[-1] = attach_final(out[-1], 19)  # ㅅ, e.g. ...앗
            index += 1
            continue
        matched = None
        for width in (2, 1):
            token = value[index:index + width]
            if token in KATA_MORA:
                matched = token
                break
        if matched is not None:
            out.append(KATA_MORA[matched])
            index += len(matched)
            continue
        char = value[index]
        # Hiragana is rare in the corpus, but simple labels such as さっそう
        # can still be handled by the katakana table after Unicode conversion.
        if "ぁ" <= char <= "ゖ":
            kata = chr(ord(char) + 0x60)
            if kata in KATA_MORA:
                out.append(KATA_MORA[kata])
                index += 1
                continue
        if "\u3040" <= char <= "\u30ff" or "\u3400" <= char <= "\u9fff":
            unknown_japanese = True
        out.append(char)
        index += 1
    result = re.sub(r"[ \t]+", " ", "".join(out)).strip()
    return result, unknown_japanese


def partial_leading_slot_translation(
    row: dict[str, Any], exact: dict[str, str], compact: dict[str, str]
) -> tuple[str, str, str] | None:
    """Translate a known name suffix while retaining one unresolved prefix slot.

    Entity-name tables contain entries such as ``<07FB>스트라이크ガンダム``.
    The leading literal is a real renderer glyph (often an icon/frame), not a
    Japanese character that can be safely guessed.  The name suffix itself is
    fully known, so we can replace only that suffix and preserve the original
    two-byte prefix in ``translated_raw_for``.  This keeps the unit-name table
    patchable without inventing a charmap assignment for the prefix slot.
    """
    if str(row.get("semantic_category")) != "unit_name":
        return None
    source = str(row.get("decoded_text_seed", ""))
    match = re.fullmatch(r"(<[0-9A-Fa-f]{4}>)(.+)", source)
    if match is None or len(row.get("unresolved_slots", [])) != 1:
        return None
    suffix = norm_key(match.group(2))
    key = norm_key(suffix)
    target = MANUAL_TRANSLATIONS_NORMALIZED.get(key)
    if target is None:
        target = exact.get(key)
    if target is None:
        target = MANUAL_TRANSLATIONS_COMPACT.get(compact_key(key))
    if target is None and compact_key(key):
        target = compact.get(compact_key(key))
    if target is None:
        return None
    return (
        target,
        "translated_partial_charmap_preserved",
        f"translated known unit-name suffix; preserved unresolved leading slot {match.group(1)}",
    )


def source_translation(row: dict[str, Any], exact: dict[str, str], compact: dict[str, str]) -> tuple[str, str, str]:
    """Return (translation, status, note)."""
    source = str(row["decoded_text_seed"])
    policy = str(row["translation_policy"])
    if policy != "translate":
        return source, "preserve", "translation policy preserves the original token stream"
    if not source:
        return "", "source_empty", "source stream is an intentional empty string"
    if row.get("unresolved_slots"):
        partial = partial_leading_slot_translation(row, exact, compact)
        if partial is not None:
            return partial
        return "", "needs_charmap_resolution", "Japanese source contains unresolved glyph slots"

    key = norm_key(source)
    manual = MANUAL_TRANSLATIONS_NORMALIZED.get(key)
    if manual is not None:
        return manual, "translated", "reviewed short-label translation"
    if key in exact:
        return exact[key], "translated", "curated project glossary/UI translation"

    # Compact matching is safe for names and short labels, but not for long
    # prose where spacing can carry meaning.
    semantic = str(row["semantic_category"])
    compact_allowed = semantic in {
        "character_name", "unit_name", "weapon_name", "unit_defense_ability",
        "upgrade_part_name", "series_title", "stage_location_name", "stage_battle_condition_component",
        "stage_code", "generic_ui_symbol", "statically_unreferenced_nine_row_menu_label",
    }
    if compact_allowed and compact_key(key) in compact:
        return compact[compact_key(key)], "translated", "curated compact-name translation"

    if semantic == "stage_code":
        return key, "translated_same", "stage code is an identifier, not prose"

    # A few short, fully decoded labels are safe to transliterate.  Deliberately
    # do not auto-translate garbled condition strings or multiline script rows.
    if semantic in {
        "character_name", "unit_name", "weapon_name", "unit_defense_ability",
        "upgrade_part_name", "series_title", "stage_location_name", "stage_battle_condition_component",
    }:
        rendered, unknown = transliterate_fragment(key)
        if rendered and not unknown:
            return rendered, "translated", "deterministic katakana/label transliteration"
    return "", "needs_review", "source is decoded but no reviewed natural Korean wording is fixed yet"


def load_korean_charmap() -> dict[str, int]:
    payload = json.loads(CHARMAP_PATH.read_text(encoding="utf-8"))
    assignments = payload.get("assignments", [])
    mapping: dict[str, int] = {}
    for item in assignments:
        char = item.get("char")
        slot = item.get("slot")
        if isinstance(char, str) and isinstance(slot, str):
            mapping[char] = int(slot, 16)
    check(len(mapping) == int(payload["allocation"]["assigned"]), "Korean charmap assignment count drift")
    return mapping


def encode_korean_text(value: str, charmap: dict[str, int]) -> tuple[bytes | None, list[str]]:
    """Encode a translated label as literal GBA tokens plus NUL.

    This is intentionally conservative: no dictionary recompression is
    attempted.  A future font-builder may replace literal tokens with shared
    dictionary phrases, but pointer planning remains valid because this is the
    exact byte stream selected for the current plan.
    """
    out = bytearray()
    missing: list[str] = []
    for char in value:
        code = ord(char)
        if char == " ":
            # 0x01 is the game's blank glyph.  0x20 is a Japanese kana glyph
            # (it renders like を), so emitting an ASCII space corrupts every
            # natural Korean name that uses word spacing.
            out.append(0x01)
        elif char in charmap:
            token = 0xDF20 + charmap[char]
            check(0xE000 <= token <= 0xEFFF, f"Korean token outside literal range for {char}")
            out.extend((token >> 8, token & 0xFF))
        elif 1 <= code <= 0xDF:
            out.append(code)
        elif char == "\n":
            out.append(0x0A)
        else:
            missing.append(char)
    if missing:
        return None, sorted(set(missing))
    out.append(0)
    return bytes(out), []


def pointer_group(row: dict[str, Any]) -> str:
    contract = str(row["storage_contract"])
    refs = row.get("references", [])
    if contract == "nul_stream_u16_relative_pair_member":
        return "relative_256x3"
    if contract.endswith("fallback_pair_member"):
        return str(next(ref["pair_address"] for ref in refs if ref.get("pair_address")))
    if contract.endswith("override_pair_member"):
        return str(next(ref["pair_address"] for ref in refs if ref.get("pair_address")))
    if contract == "nul_stream_double_nul_list_member":
        return str(next(ref["list_start_address"] for ref in refs if ref.get("list_start_address")))
    return "ordinary_u32_streams"


def translated_raw_for(row: dict[str, Any], charmap: dict[str, int]) -> tuple[bytes | None, list[str]]:
    status = str(row["translation_status"])
    if status in {"preserve", "source_empty", "needs_charmap_resolution", "needs_review", "not_started"}:
        return bytes.fromhex(str(row["raw_hex"]).replace(" ", "")), []
    if status == "translated_partial_charmap_preserved":
        raw = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        raw_tokens = [str(token) for token in row.get("tokens", [])]
        unresolved = row.get("unresolved_slots", [])
        check(len(unresolved) == 1, f"partial translation unresolved-slot count drift: {row['record_id']}")
        check(raw_tokens, f"partial translation lacks raw token provenance: {row['record_id']}")
        first_token = int(raw_tokens[0], 16)
        check(0xE000 <= first_token <= 0xEFFF, f"partial translation prefix is not a literal token: {row['record_id']}")
        first_slot = (first_token + 0x20E0) & 0xFFFF
        check(first_slot == int(str(unresolved[0]), 16), f"partial translation prefix slot drift: {row['record_id']}")
        encoded, missing = encode_korean_text(str(row["translation_ko"]), charmap)
        if encoded is None:
            return None, missing
        # Keep the unresolved leading glyph exactly as authored by the game;
        # replace the complete name body and retain only the NUL terminator.
        return raw[:2] + encoded, []
    return encode_korean_text(str(row["translation_ko"]), charmap)


def build_pointer_plan(rows: list[dict[str, Any]], raw_by_target: dict[int, bytes], rom: bytes) -> tuple[dict[str, Any], bytes]:
    """Rebuild container offsets and owner pointers in memory only."""
    by_target = {int(row["target_file_offset"], 16): row for row in rows}
    allocations: list[dict[str, Any]] = []
    cursor = TEXT_START
    total_payload = 0
    alignment_padding = 0
    candidate = bytearray(32 * 1024 * 1024)
    candidate[:len(rom)] = rom

    def allocate(name: str, category: str, payload: bytes, source: str) -> int:
        nonlocal cursor, total_payload, alignment_padding
        aligned = (cursor + 3) & ~3
        alignment_padding += aligned - cursor
        cursor = aligned
        start = cursor
        end = start + len(payload)
        check(end <= TEXT_END, f"text region overflow while allocating {name}")
        candidate[start:end] = payload
        cursor = end
        total_payload += len(payload)
        allocations.append({
            "name": name,
            "category": category,
            "file_offset": f"0x{start:08X}",
            "end_exclusive": f"0x{end:08X}",
            "size": len(payload),
            "source": source,
        })
        return start

    new_target: dict[int, int] = {}
    owner_patches: dict[int, tuple[int, str]] = {}
    internal_relative_offsets: list[int] = []

    def set_owner(source: int, value: int, kind: str) -> None:
        prior = owner_patches.get(source)
        check(prior is None or prior == (value, kind), f"conflicting owner pointer at 0x{source:08X}")
        owner_patches[source] = (value, kind)

    # Relative 256x3 block: rebuild the 769-entry u16 table and recompute all
    # 766 live/sentinel offsets from the translated pair lengths.  The base
    # literal is the only code/data owner patched outside the relocated block.
    relative_rows = [row for row in rows if row["storage_contract"] == "nul_stream_u16_relative_pair_member"]
    relative_by_pair: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in relative_rows:
        ref = next(ref for ref in row["references"] if ref.get("relative_entry_file"))
        relative_by_pair[int(ref["pair_index"])].append(row)
    check(len(relative_by_pair) == 765, f"relative pair count drift: {len(relative_by_pair)}")
    relative_pair_payload = bytearray()
    for pair_index in range(765):
        pair_rows = sorted(relative_by_pair[pair_index], key=lambda row: int(next(ref for ref in row["references"] if ref.get("line_index") is not None)["line_index"]))
        check(len(pair_rows) == 2, f"relative pair member count drift at {pair_index}")
        for row in pair_rows:
            old_offset = int(row["target_file_offset"], 16)
            new_target[old_offset] = 0  # filled after allocation
            relative_pair_payload.extend(raw_by_target[old_offset])
    relative_payload_offset = RELATIVE_TABLE_BYTES
    # The first source stream is exactly base + 0x602 in the clean ROM: the
    # table occupies 769 little-endian u16 entries and there is no hidden gap.
    cursor_for_pair = 0
    offset_values = [0, 0, 0]
    pair_offsets: list[int] = []
    for pair_index in range(765):
        pair_rows = sorted(relative_by_pair[pair_index], key=lambda row: int(next(ref for ref in row["references"] if ref.get("line_index") is not None)["line_index"]))
        pair_offsets.append(cursor_for_pair)
        for row in pair_rows:
            old_offset = int(row["target_file_offset"], 16)
            new_target[old_offset] = cursor_for_pair
            cursor_for_pair += len(raw_by_target[old_offset])
    pair_offsets.append(cursor_for_pair)
    offset_values.extend(relative_payload_offset + value for value in pair_offsets)
    check(len(offset_values) == RELATIVE_OFFSET_COUNT + 3, "relative u16 offset table size drift")
    relative_table = bytearray()
    for value in offset_values:
        check(0 <= value <= 0xFFFF, f"relative u16 offset overflow: {value}")
        relative_table.extend(struct.pack("<H", value))
    # Keep the one-byte tail that follows the last sentinel in the clean ROM;
    # it is padding, not a third line, but preserving it keeps the container
    # boundary stable when no relative text has changed.
    relative_payload = bytes(relative_table + relative_pair_payload + b"\0")
    relative_file = allocate("translated_relative_pair_block", "relative_256x3", relative_payload, "0x001BF908")
    for old_offset, relative_offset in list(new_target.items()):
        if old_offset in by_target and by_target[old_offset]["storage_contract"] == "nul_stream_u16_relative_pair_member":
            new_target[old_offset] = ROM_BASE + relative_file + relative_payload_offset + relative_offset
    set_owner(RELATIVE_BASE_LITERAL_FILE, ROM_BASE + relative_file, "relative_block_base_literal")
    internal_relative_offsets = offset_values[3:]

    # Length-prefixed pair containers.  The row reference carries the proven
    # pair address and owner field; recalculate the one-byte lengths and all
    # line offsets from the translated streams.
    for suffix, category, schema in (
        ("fallback_pair", "length_prefixed_fallback_pairs", "length_prefixed_pair_fallback"),
        ("override_pair", "length_prefixed_override_pairs", "length_prefixed_pair_override"),
    ):
        groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            for ref in row["references"]:
                if ref.get("relocation_schema") == schema:
                    groups[int(ref["pair_address"], 16)].append(row)
                    break
        blob = bytearray()
        pair_rel: dict[int, int] = {}
        line_rel: dict[int, int] = {}
        for old_pair in sorted(groups):
            pair_rel[old_pair] = len(blob)
            members = sorted(groups[old_pair], key=lambda row: int(next(ref for ref in row["references"] if ref.get("relocation_schema") == schema)["line_index"]))
            check(len(members) == 2, f"{suffix} line count drift at 0x{old_pair:08X}")
            for row in members:
                payload = raw_by_target[int(row["target_file_offset"], 16)]
                check(len(payload) - 1 <= 0xFF, f"{suffix} line exceeds one-byte length prefix")
                blob.append(len(payload) - 1)
                line_rel[int(row["target_file_offset"], 16)] = len(blob)
                blob.extend(payload)
        if blob:
            pair_file = allocate(f"translated_{suffix}s", category, bytes(blob), "production pair containers")
            for old_pair in sorted(groups):
                new_pair = ROM_BASE + pair_file + pair_rel[old_pair]
                for row in groups[old_pair]:
                    for ref in row["references"]:
                        if ref.get("relocation_schema") == schema:
                            set_owner(int(ref["pointer_source_file"], 16), new_pair, schema)
            for old_offset, rel in line_rel.items():
                new_target[old_offset] = ROM_BASE + pair_file + rel

    # Double-NUL lists: one owner u32 per list, all visible line streams in
    # line-index order, followed by an empty stream sentinel.
    list_groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["storage_contract"] == "nul_stream_double_nul_list_member":
            ref = next(ref for ref in row["references"] if ref.get("list_start_address"))
            list_groups[int(ref["list_start_address"], 16)].append(row)
    list_blob = bytearray()
    list_rel: dict[int, int] = {}
    for old_start in sorted(list_groups):
        list_rel[old_start] = len(list_blob)
        members = sorted(list_groups[old_start], key=lambda row: int(next(ref for ref in row["references"] if ref.get("list_start_address"))["line_index"]))
        for row in members:
            old_offset = int(row["target_file_offset"], 16)
            list_blob.extend(raw_by_target[old_offset])
        list_blob.append(0)
    if list_blob:
        list_file = allocate("translated_double_nul_lists", "double_nul_lists", bytes(list_blob), "table_1C92E8")
        for old_start, members in list_groups.items():
            start = ROM_BASE + list_file + list_rel[old_start]
            first = True
            pos = list_rel[old_start]
            for row in sorted(members, key=lambda row: int(next(ref for ref in row["references"] if ref.get("list_start_address"))["line_index"])):
                old_offset = int(row["target_file_offset"], 16)
                new_target[old_offset] = ROM_BASE + list_file + pos
                pos += len(raw_by_target[old_offset])
                first = False
            for row in members:
                for ref in row["references"]:
                    if ref.get("list_start_address"):
                        set_owner(int(ref["pointer_source_file"], 16), start, "double_nul_list")

    # Ordinary streams are deduplicated by target and moved as literal NUL
    # streams.  This is where unit/character/weapon/UI name length changes
    # normally land.
    ordinary_rows = [
        row for row in rows
        if row["storage_contract"] == "nul_stream"
    ]
    ordinary_blob = bytearray()
    ordinary_rel: dict[int, int] = {}
    for row in sorted(ordinary_rows, key=lambda row: int(row["target_file_offset"], 16)):
        old_offset = int(row["target_file_offset"], 16)
        ordinary_rel[old_offset] = len(ordinary_blob)
        ordinary_blob.extend(raw_by_target[old_offset])
    if ordinary_blob:
        ordinary_file = allocate("translated_ordinary_u32_streams", "ordinary_u32_streams", bytes(ordinary_blob), "ordinary NUL streams")
        for old_offset, rel in ordinary_rel.items():
            new_target[old_offset] = ROM_BASE + ordinary_file + rel

    # All remaining row contracts (fixed/indirect rows represented as ordinary
    # in the manifest) must have a destination.
    check(len(new_target) == len(rows), f"translated target map drift: {len(new_target)} vs {len(rows)}")

    # Ordinary and container owner fields are collected from the provenance;
    # relative rows have no direct u32 owner and are handled by the base literal.
    for row in rows:
        old_offset = int(row["target_file_offset"], 16)
        for ref in row["references"]:
            if not ref.get("patchable_u32"):
                continue
            source_text = ref.get("pointer_source_file")
            if not isinstance(source_text, str):
                continue
            source = int(source_text, 16)
            schema = str(ref.get("relocation_schema"))
            if schema == "ordinary_u32_stream":
                set_owner(source, new_target[old_offset], schema)

    changed_rows = [row for row in rows if int(row["byte_delta"]) != 0]
    check(cursor <= TEXT_END, "translated text region overflow")
    allowed_patch_bytes: set[int] = set()
    for source, (value, _kind) in sorted(owner_patches.items()):
        check(0 <= source <= len(rom) - 4, f"owner pointer source outside original ROM: 0x{source:08X}")
        struct.pack_into("<I", candidate, source, value)
        allowed_patch_bytes.update(range(source, source + 4))
    changed = [index for index, (before, after) in enumerate(zip(rom, candidate[:len(rom)])) if before != after]
    unexpected = [index for index in changed if index not in allowed_patch_bytes]
    check(not unexpected, f"unexpected original-half changes in translated PoC: {len(unexpected)}")
    for old_offset, row in by_target.items():
        new_address = new_target[old_offset]
        new_offset = new_address - ROM_BASE
        replacement = raw_by_target[old_offset]
        check(candidate[new_offset:new_offset + len(replacement)] == replacement, f"translated payload mismatch at 0x{old_offset:08X}")
    check(candidate[0x00FCED40:len(rom)] == rom[0x00FCED40:], "strong tail changed in translated PoC")
    candidate_sha256 = hashlib.sha256(candidate).hexdigest()
    plan = {
        "schema_version": 1,
        "text_region": {
            "start": f"0x{TEXT_START:08X}",
            "end_exclusive": f"0x{TEXT_END:08X}",
            "high_water": f"0x{cursor:08X}",
            "allocated_payload_bytes": total_payload,
            "alignment_padding_bytes": alignment_padding,
            "remaining_bytes": TEXT_END - cursor,
        },
        "containers": {
            "relative_pair_block": {
                "records": len(relative_rows),
                "pairs": len(relative_by_pair),
                "u16_offset_values_recalculated": len(internal_relative_offsets),
                "new_payload_bytes": len(relative_payload),
                "payload_offset_from_block_base": relative_payload_offset,
            },
            "double_nul_lists": {
                "lists": len(list_groups),
                "streams": sum(len(v) for v in list_groups.values()),
                "new_payload_bytes": len(list_blob),
            },
            "ordinary_u32_streams": {
                "streams": len(ordinary_rows),
                "new_payload_bytes": len(ordinary_blob),
            },
        },
        "pointer_recalculation": {
            "records_with_byte_length_change": len(changed_rows),
            "owner_u32_fields": len(owner_patches),
            "relative_base_literal_file": f"0x{RELATIVE_BASE_LITERAL_FILE:08X}",
            "relative_u16_table_values": len(internal_relative_offsets),
            "owner_kind_counts": dict(Counter(kind for _source, (_value, kind) in owner_patches.items())),
            "all_owner_pointers_resolved": True,
            "owner_patches": [
                {
                    "source_file": f"0x{source:08X}",
                    "new_value": f"0x{value:08X}",
                    "kind": kind,
                }
                for source, (value, kind) in sorted(owner_patches.items())
            ],
        },
        "verification": {
            "result": "PASS",
            "output_size": len(candidate),
            "output_sha256": candidate_sha256,
            "changed_bytes_in_original_half": len(changed),
            "allowed_patch_byte_positions": len(allowed_patch_bytes),
            "unexpected_changed_bytes": len(unexpected),
            "all_translated_target_payloads_match": True,
            "original_text_payloads_unchanged": True,
            "strong_tail_0xFCED40_unchanged": True,
        },
        "allocations": allocations,
        "new_targets": {
            f"0x{old_offset:08X}": f"0x{new_address:08X}"
            for old_offset, new_address in sorted(new_target.items())
        },
    }
    return plan, bytes(candidate)


def build_report(rom: bytes) -> dict[str, Any]:
    base = stage2.build_master(rom)
    exact, compact = curated_translation_maps()
    charmap = load_korean_charmap()
    rows: list[dict[str, Any]] = []
    translation_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    raw_by_target: dict[int, bytes] = {}
    missing_korean: Counter[str] = Counter()

    for source in base["records"]:
        row = dict(source)
        row["source_text"] = str(row.get("decoded_text_seed", ""))
        translation, status, note = source_translation(row, exact, compact)
        row["translation_ko"] = ko_clean(translation)
        row["translation_status"] = status
        row["translation_confidence"] = (
            "high" if "reviewed" in note or "curated" in note else
            "medium" if status == "translated" else
            "preserve" if status == "preserve" else
            "pending"
        )
        row["translator_notes"] = note
        row["pointer_group"] = pointer_group(row)
        encoded, missing = translated_raw_for(row, charmap)
        if status in {"translated", "translated_same", "translated_partial_charmap_preserved"} and encoded is None:
            row["translation_status"] = "translated_font_pending"
            row["translation_confidence"] = "pending"
            row["translator_notes"] = f"Korean charmap/font slot missing: {', '.join(missing)}"
            missing_korean.update(missing)
            encoded = bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))
        original_len = len(bytes.fromhex(str(row["raw_hex"]).replace(" ", "")))
        new_len = len(encoded) if encoded is not None else original_len
        row["original_byte_length"] = original_len
        row["translated_byte_length"] = new_len
        row["byte_delta"] = new_len - original_len
        row["pointer_recalc_required"] = bool(
            row["translation_status"] in {"translated", "translated_same", "translated_partial_charmap_preserved"}
            and row["byte_delta"] != 0
        )
        row["translated_raw_hex"] = encoded.hex(" ").upper() if encoded is not None else ""
        row["source_unresolved_slots"] = ", ".join(row.get("unresolved_slots", []))
        row["source_families_text"] = ", ".join(row.get("source_families", []))
        row["pointer_owner_field_count"] = sum(bool(ref.get("patchable_u32")) for ref in row.get("references", []))
        rows.append(row)
        translation_counts[row["translation_status"]] += 1
        confidence_counts[row["translation_confidence"]] += 1
        raw_by_target[int(row["target_file_offset"], 16)] = encoded or bytes.fromhex(str(row["raw_hex"]).replace(" ", ""))

    check(len(rows) == 4069, f"translation row count drift: {len(rows)}")
    pointer_plan, candidate = build_pointer_plan(rows, raw_by_target, rom)
    ready_statuses = {"translated", "translated_same", "translated_partial_charmap_preserved"}
    translated_rows = [row for row in rows if row["translation_status"] in ready_statuses]
    ready_rows = [row for row in rows if row["translation_status"] in ready_statuses]
    digest_payload = [
        {
            "record_id": row["record_id"],
            "source_sha256": row["original_raw_sha256"],
            "semantic_category": row["semantic_category"],
            "translation_ko": row["translation_ko"],
            "translation_status": row["translation_status"],
        }
        for row in rows
    ]
    translation_sha = hashlib.sha256(
        json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "scope": "G Generation Advance integrated Korean translation master",
        "source": base["source"],
        "record_identity_sha256": base["record_identity_sha256"],
        "base_master_schema_sha256": base["master_schema_sha256"],
        "translation_content_sha256": translation_sha,
        "summary": {
            "records": len(rows),
            "translated_rows": len(translated_rows),
            "translated_ready_for_pointer_plan": len(ready_rows),
            "translation_status_counts": dict(translation_counts),
            "translation_confidence_counts": dict(confidence_counts),
            "byte_length_changed_rows": sum(row["byte_delta"] != 0 for row in rows),
            "translated_byte_delta_total": sum(row["byte_delta"] for row in rows if row["translation_status"] in ready_statuses),
            "korean_charmap_missing_characters": len(missing_korean),
            "top_missing_korean_characters": [
                {"char": char, "occurrences": count}
                for char, count in missing_korean.most_common(50)
            ],
        },
        "sheet_columns": [
            "record_id", "target_file_offset", "primary_category", "semantic_category",
            "storage_contract", "pointer_group", "source_text", "translation_ko",
            "translation_status", "translation_confidence", "source_decode_status",
            "source_unresolved_slots", "original_byte_length", "translated_byte_length",
            "byte_delta", "pointer_recalc_required", "pointer_owner_field_count",
            "source_families_text", "translator_notes",
        ],
        "pointer_plan": pointer_plan,
        "_candidate_bytes": candidate,
        "records": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("rom", type=Path)
    ap.add_argument("--out-json", type=Path)
    ap.add_argument("--out-rom", type=Path, help="write the 32 MiB translated PoC ROM")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()
    rom = args.rom.read_bytes()
    check(len(rom) == 16 * 1024 * 1024, "ROM size drift")
    report = build_report(rom)
    candidate = report.pop("_candidate_bytes")
    if args.out_rom:
        args.out_rom.parent.mkdir(parents=True, exist_ok=True)
        args.out_rom.write_bytes(candidate)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.summary_only:
        visible = {key: report[key] for key in ("schema_version", "scope", "source", "record_identity_sha256", "base_master_schema_sha256", "translation_content_sha256", "summary", "sheet_columns", "pointer_plan")}
    else:
        visible = report
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
