#!/usr/bin/env python3
"""Translate 12x12-decoded ID-command descriptions, 8x16 effect summaries, Ginn weapons.

ID-command bodies are 12x12 token streams that the sheet had decoded as 8x16, so
they stayed pending and the live JP mixed with Hangul-painted 威力/命中 slots.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

from analyze_ggen_advance_pending_decode import CORRECTED_LOW_KANA, load_map  # noqa: E402
from ggen_advance_text_codec import (  # noqa: E402
    DICT_8X16_BASE,
    DICT_8X16_END,
    DICT_12X12_BASE,
    DICT_12X12_END,
    expand_to_slots,
    load_dictionary,
    read_tokens,
)
from build_ggen_advance_unified_rom_poc import raw_hex_bytes  # noqa: E402

MERGED_IN = ROOT / "analysis" / "ggen_advance_translation_merged_20260833.json"
MERGED_OUT = ROOT / "analysis" / "ggen_advance_translation_merged_20260834.json"
BATCH = "idcmd-desc-12x12-weapons-20260829"
JP_LEFT = re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF]")

DESC_REPLACEMENTS: list[tuple[str, str]] = [
    ("1ターンの間、指揮範囲内の味方の", "1턴 동안 지휘 범위 내 아군의"),
    ("1ターンの間、味方チームの移動力", "1턴 동안 아군 팀의 이동력"),
    ("1ターンの間、味方チームの命中と", "1턴 동안 아군 팀의 명중과"),
    ("1ターンの間、味方チームの命中を", "1턴 동안 아군 팀의 명중을"),
    ("1ターンの間、味方チームの回避を", "1턴 동안 아군 팀의 회피를"),
    ("1ターンの間、味方チームの威力と", "1턴 동안 아군 팀의 위력과"),
    ("1ターンの間、味方チームの能力を", "1턴 동안 아군 팀의 능력을"),
    ("1ターンの間、味方チームの", "1턴 동안 아군 팀의"),
    ("1ターンの間、自分の命中・回避", "1턴 동안 자신의 명중·회피"),
    ("1ターンの間、自分の命中と反応を", "1턴 동안 자신의 명중과 반응을"),
    ("1ターンの間、自分の命中と回避、", "1턴 동안 자신의 명중과 회피,"),
    ("1ターンの間、自分の命中と回避を", "1턴 동안 자신의 명중과 회피를"),
    ("1ターンの間、自分の命中と威力を", "1턴 동안 자신의 명중과 위력을"),
    ("1ターンの間、自分의回避と装甲を", "1턴 동안 자신의 회피와 장갑을"),
    ("1ターンの間、自分の回避と装甲を", "1턴 동안 자신의 회피와 장갑을"),
    ("1ターンの間、自分の威力と反応を", "1턴 동안 자신의 위력과 반응을"),
    ("1ターンの間、自分の威力と命中、", "1턴 동안 자신의 위력과 명중,"),
    ("1ターンの間、自分の威力と命中を", "1턴 동안 자신의 위력과 명중을"),
    ("1ターンの間、自分の威力と回避を", "1턴 동안 자신의 위력과 회피를"),
    ("1ターンの間、自分の威力と装甲、", "1턴 동안 자신의 위력과 장갑,"),
    ("1ターンの間、自分の威力と装甲を", "1턴 동안 자신의 위력과 장갑을"),
    ("1ターンの間、自分の装甲と命中、", "1턴 동안 자신의 장갑과 명중,"),
    ("1ターンの間、自分の装甲と回避、", "1턴 동안 자신의 장갑과 회피,"),
    ("1ターンの間、自分の装甲と回避を", "1턴 동안 자신의 장갑과 회피를"),
    ("1ターンの間、自分の能力を", "1턴 동안 자신의 능력을"),
    ("1ターンの間、IDも封じます", "1턴 동안 ID도 봉인합니다"),
    ("1ターンの間、使用可能にします", "1턴 동안 사용 가능하게 합니다"),
    ("1ターン封じます。命中も上昇", "1턴 봉인합니다. 명중도 상승"),
    ("戦闘時、味方チームが敵ユニットを", "전투 시 아군 팀이 적 유닛을"),
    ("戦闘時、味方チームが敵の攻撃を", "전투 시 아군 팀이 적의 공격을"),
    ("戦闘時、味方チームの威力と命中を", "전투 시 아군 팀의 위력과 명중을"),
    ("戦闘時、味方チームの威力を上げ", "전투 시 아군 팀의 위력을 올리고"),
    ("戦闘時、味方チームの装甲を上げ", "전투 시 아군 팀의 장갑을 올리고"),
    ("戦闘時、味方チームの命中を", "전투 시 아군 팀의 명중을"),
    ("戦闘時、味方チームの回避を", "전투 시 아군 팀의 회피를"),
    ("戦闘時、味方チーム의", "전투 시 아군 팀의"),
    ("戦闘時、味方チームの", "전투 시 아군 팀의"),
    ("戦闘時、敵チームの命中と回避、", "전투 시 적 팀의 명중과 회피,"),
    ("戦闘時、敵チームの命中と回避を", "전투 시 적 팀의 명중과 회피를"),
    ("戦闘時、敵チームの威力と反応を", "전투 시 적 팀의 위력과 반응을"),
    ("戦闘時、敵チームの威力と命中、", "전투 시 적 팀의 위력과 명중,"),
    ("戦闘時、敵チームの威力と命中を", "전투 시 적 팀의 위력과 명중을"),
    ("戦闘時、敵チームの威力と回避を", "전투 시 적 팀의 위력과 회피를"),
    ("戦闘時、敵チームの威力と装甲、", "전투 시 적 팀의 위력과 장갑,"),
    ("戦闘時、敵チームの威力と装甲を", "전투 시 적 팀의 위력과 장갑을"),
    ("戦闘時、敵チームの装甲と命中、", "전투 시 적 팀의 장갑과 명중,"),
    ("戦闘時、敵チームの装甲と回避、", "전투 시 적 팀의 장갑과 회피,"),
    ("戦闘時、敵チームの装甲と回避を", "전투 시 적 팀의 장갑과 회피를"),
    ("戦闘時、敵チームの攻撃を封じます", "전투 시 적 팀의 공격을 봉합니다"),
    ("戦闘時、敵チームの散開を封じます", "전투 시 적 팀의 산개를 봉합니다"),
    ("戦闘時、敵チームの散開を封印し", "전투 시 적 팀의 산개를 봉인하고"),
    ("戦闘時、敵チームの威力を", "전투 시 적 팀의 위력을"),
    ("戦闘時、敵チームの能力を", "전투 시 적 팀의 능력을"),
    ("戦闘時、敵チームを強制的に", "전투 시 적 팀을 강제로"),
    ("戦闘時、敵チームの", "전투 시 적 팀의"),
    ("戦闘時、自分の近接攻撃の威力と", "전투 시 자신의 근접 공격 위력과"),
    ("戦闘時、自分의近接攻撃の威力を", "전투 시 자신의 근접 공격 위력을"),
    ("戦闘時、自分の近接攻撃の威力を", "전투 시 자신의 근접 공격 위력을"),
    ("戦闘時、自分の命中と回避を大幅に", "전투 시 자신의 명중과 회피를 크게"),
    ("戦闘時、自分の命中を上昇させます", "전투 시 자신의 명중을 상승시킵니다"),
    ("戦闘時、自分の命中を上昇させ", "전투 시 자신의 명중을 상승시켜"),
    ("戦闘時、自分の命中を大幅に上げ", "전투 시 자신의 명중을 크게 올리고"),
    ("戦闘時、自分の命中と威力を", "전투 시 자신의 명중과 위력을"),
    ("戦闘時、自分の命中を", "전투 시 자신의 명중을"),
    ("戦闘時、自分の回避を大幅に上げ", "전투 시 자신의 회피를 크게 올리고"),
    ("戦闘時、自分의回避を大幅に", "전투 시 자신의 회피를 크게"),
    ("戦闘時、自分の回避を大幅に", "전투 시 자신의 회피를 크게"),
    ("戦闘時、自分の回避を上昇させます", "전투 시 자신의 회피를 상승시킵니다"),
    ("戦闘時、自分の回避を", "전투 시 자신의 회피를"),
    ("戦闘時、自分の威力・命中・回避を上げ", "전투 시 자신의 위력·명중·회피를 올리고"),
    ("戦闘時、自分の威力・命中・回避を", "전투 시 자신의 위력·명중·회피를"),
    ("戦闘時、自分の威力・命中・装甲を", "전투 시 자신의 위력·명중·장갑을"),
    ("戦闘時、自分の威力・装甲・命中を", "전투 시 자신의 위력·장갑·명중을"),
    ("戦闘時、自分の威力と命中を上昇させ", "전투 시 자신의 위력과 명중을 상승시켜"),
    ("戦闘時、自分の威力と命中を上げ", "전투 시 자신의 위력과 명중을 올리고"),
    ("戦闘時、自分の威力と回避を上昇させ", "전투 시 자신의 위력과 회피를 상승시켜"),
    ("戦闘時、自分の威力と痛撃率を上げ", "전투 시 자신의 위력과 통격률을 올리고"),
    ("戦闘時、自分の威力と反応を", "전투 시 자신의 위력과 반응을"),
    ("戦闘時、自分の威力と命中を", "전투 시 자신의 위력과 명중을"),
    ("戦闘時、自分の威力と回避を", "전투 시 자신의 위력과 회피를"),
    ("戦闘時、自分の威力と装甲を", "전투 시 자신의 위력과 장갑을"),
    ("戦闘時、自分の威力を大幅に上昇させ", "전투 시 자신의 위력을 크게 상승시켜"),
    ("戦闘時、自分の威力を大幅に上げ", "전투 시 자신의 위력을 크게 올리고"),
    ("戦闘時、自分の威力を上昇させて", "전투 시 자신의 위력을 상승시켜"),
    ("戦闘時、自分の威力を上昇させます", "전투 시 자신의 위력을 상승시킵니다"),
    ("戦闘時、自分の威力を上昇させ", "전투 시 자신의 위력을 상승시켜"),
    ("戦闘時、自分の威力を上げ", "전투 시 자신의 위력을 올리고"),
    ("戦闘時、自分の威力を", "전투 시 자신의 위력을"),
    ("戦闘時、自分の反応を大幅に上げ", "전투 시 자신의 반응을 크게 올리고"),
    ("戦闘時、自分の痛撃率が上昇し", "전투 시 자신의 통격률이 상승하고"),
    ("戦闘時、自分の装甲と命中を", "전투 시 자신의 장갑과 명중을"),
    ("戦闘時、自分の装甲と回避を", "전투 시 자신의 장갑과 회피를"),
    ("戦闘時、自分の装甲を上昇させます", "전투 시 자신의 장갑을 상승시킵니다"),
    ("戦闘時、自分の装甲を上昇させ", "전투 시 자신의 장갑을 상승시켜"),
    ("戦闘時、攻撃を命中させた敵の移動と", "전투 시 공격을 명중시킨 적의 이동과"),
    ("戦闘時、攻撃を命中させた敵の移動を", "전투 시 공격을 명중시킨 적의 이동을"),
    ("戦闘時、攻撃を命中させた敵の", "전투 시 공격을 명중시킨 적의"),
    ("戦闘時、攻撃対象のＨPが３0％未満", "전투 시 공격 대상의 HP가 30% 미만"),
    ("戦闘時、敵の威力・回避・反応を", "전투 시 적의 위력·회피·반응을"),
    ("戦闘時、敵の攻撃と散開を封印し", "전투 시 적의 공격과 산개를 봉인하고"),
    ("戦闘時、敵の攻撃を完全に回避します", "전투 시 적의 공격을 완전히 회피합니다"),
    ("戦闘時、敵の攻撃を封じます", "전투 시 적의 공격을 봉합니다"),
    ("戦闘時、敵を強制的に散開させます", "전투 시 적을 강제로 산개시킵니다"),
    ("戦闘時、敵の攻撃を", "전투 시 적의 공격을"),
    ("戦闘時、回避と痛撃率を上昇させ", "전투 시 회피와 통격률을 상승시켜"),
    ("戦闘時、先制攻撃を行います", "전투 시 선제 공격을 합니다"),
    ("戦闘時、味方をかばいます", "전투 시 아군을 지켜 줍니다"),
    ("戦闘時、", "전투 시 "),
    ("威力・命中・回避を上昇させます", "위력·명중·회피를 상승시킵니다"),
    ("威力・装甲・命中を上昇させます", "위력·장갑·명중을 상승시킵니다"),
    ("威力・装甲・命中・回避が上昇", "위력·장갑·명중·회피가 상승"),
    ("威力と命中と回避を上昇させます", "위력과 명중과 회피를 상승시킵니다"),
    ("威力と命中を上昇させます", "위력과 명중을 상승시킵니다"),
    ("威力と装甲を上昇させます", "위력과 장갑을 상승시킵니다"),
    ("命中と回避を上昇させます", "명중과 회피를 상승시킵니다"),
    ("命中と回避を減少させます", "명중과 회피를 감소시킵니다"),
    ("命中と反応を減少させます", "명중과 반응을 감소시킵니다"),
    ("命中と威力を上昇させます", "명중과 위력을 상승시킵니다"),
    ("回避、および反応を上昇させます", "회피와 반응을 상승시킵니다"),
    ("回避と反応을上昇させます", "회피와 반응을 상승시킵니다"),
    ("回避と反応を上昇させます", "회피와 반응을 상승시킵니다"),
    ("装甲と回避を大幅に上昇させます", "장갑과 회피를 크게 상승시킵니다"),
    ("装甲と回避を上昇させます", "장갑과 회피를 상승시킵니다"),
    ("移動と反応を上昇させます", "이동과 반응을 상승시킵니다"),
    ("移動とIDを1ターン封じます", "이동과 ID를 1턴 봉인합니다"),
    ("反応を上げ、ＨPも回復します", "반응을 올리고 HP도 회복합니다"),
    ("反応を大幅に上昇させます", "반응을 크게 상승시킵니다"),
    ("回避を大幅に上昇させます", "회피를 크게 상승시킵니다"),
    ("命中を大幅に上昇させます", "명중을 크게 상승시킵니다"),
    ("大幅に上昇。ただし回避は粗能", "크게 상승. 다만 회피는 불가"),
    ("痛撃率が上昇。ただし回避は粗能", "통격률이 상승. 다만 회피는 불가"),
    ("撃破しなくなります。痛撃率も上昇", "격파되지 않습니다. 통격률도 상승"),
    ("であれば確実に撃破。先制攻撃", "이면 반드시 격파. 선제 공격"),
    ("であれば確実に撃破します", "이면 반드시 격파합니다"),
    ("上げ、さらに威力も上昇させます", "올리고, 위력도 더 상승시킵니다"),
    ("さらに命中も上昇させます", "명중도 더 상승시킵니다"),
    ("さらに威力も上昇させます", "위력도 더 상승시킵니다"),
    ("および反応を上昇させます", "그리고 반응을 상승시킵니다"),
    ("および反応を減少させます", "그리고 반응을 감소시킵니다"),
    ("および命中を上昇させます", "그리고 명중을 상승시킵니다"),
    ("および回避を上昇させます", "그리고 회피를 상승시킵니다"),
    ("および回避を減少させます", "그리고 회피를 감소시킵니다"),
    ("および威力を上昇させます", "그리고 위력을 상승시킵니다"),
    ("および装甲を上昇させます", "그리고 장갑을 상승시킵니다"),
    ("味方チーム全員のＨPを完全に", "아군 팀 전원의 HP를 완전히"),
    ("味方チームのＨPを回復させます", "아군 팀의 HP를 회복시킵니다"),
    ("味方チームのＨPを回復します", "아군 팀의 HP를 회복합니다"),
    ("自軍ユニット全員の能力を全般的に", "자군 유닛 전원의 능력을 전반적으로"),
    ("自軍ユニット全員のＨPを回復します", "자군 유닛 전원의 HP를 회복합니다"),
    ("自軍全員のＨPとSPを回復させ", "자군 전원의 HP와 SP를 회복시켜"),
    ("両軍全員のIDコマンド의効果を", "양군 전원의 ID 커맨드 효과를"),
    ("両軍全員のIDコマンドの効果を", "양군 전원의 ID 커맨드 효과를"),
    ("IDコマンドを1ターン封印します", "ID 커맨드를 1턴 봉인합니다"),
    ("IDを1ターン封印。威力も上昇", "ID를 1턴 봉인. 위력도 상승"),
    ("IDを1ターン封印します", "ID를 1턴 봉인합니다"),
    ("攻撃した敵のIDを1ターン封印", "공격한 적의 ID를 1턴 봉인"),
    ("敵の攻撃と散開を封印します", "적의 공격과 산개를 봉인합니다"),
    ("敵の攻撃を完全に回避します", "적의 공격을 완전히 회피합니다"),
    ("敵チームの攻撃を封じます", "적 팀의 공격을 봉합니다"),
    ("敵チームの散開を封じます", "적 팀의 산개를 봉합니다"),
    ("敵の特殊防御を無効化します", "적의 특수 방어를 무효화합니다"),
    ("敵の攻撃を封じます", "적의 공격을 봉합니다"),
    ("完全回避とID封印の効果を得ます", "완전 회피와 ID 봉인 효과를 얻습니다"),
    ("装甲を上げ、先制攻撃を行います", "장갑을 올리고 선제 공격을 합니다"),
    ("ガンダムXのサテライトキャノンを", "건담 X의 새틀라이트 캐논을"),
    ("Zガンダムの秘められた力を", "Z건담의 숨겨진 힘을"),
    ("３ターンの間、νガンダムの", "3턴 동안 ν건담의"),
    ("３ターンの間、∀ガンダムの", "3턴 동안 ∀건담의"),
    ("３ターンの間、反応を上昇させます", "3턴 동안 반응을 상승시킵니다"),
    ("３ターンの間、愛の力で", "3턴 동안 사랑의 힘으로"),
    ("３ターンの間、続いた勢いで", "3턴 동안 이어진 기세로"),
    ("３ターンの間、魂の拳で", "3턴 동안 혼의 주먹으로"),
    ("明鏡止水・ハイパーモードを", "명경지수·하이퍼 모드를"),
    ("スーパーモードを発動させます", "슈퍼 모드를 발동시킵니다"),
    ("月光蝶システムを発動させます", "월광접 시스템을 발동시킵니다"),
    ("EXAMシステムを起動させます", "EXAM 시스템을 기동시킵니다"),
    ("自分の意志でSEED能力を", "자신의 의지로 SEED 능력을"),
    ("自分のＨPを完全に回復します", "자신의 HP를 완전히 회복합니다"),
    ("自分のＨPを回復します", "자신의 HP를 회복합니다"),
    ("味方一人を復活させます", "아군 한 명을 부활시킵니다"),
    ("味方をかばいます", "아군을 지켜 줍니다"),
    ("捕獲成功率を上昇させます", "포획 성공률을 상승시킵니다"),
    ("一部を除いて消去します", "일부를 제외하고 소거합니다"),
    ("上昇させます。効果は無期限", "상승시킵니다. 효과는 무기한"),
    ("発動させます。効果は無期限", "발동시킵니다. 효과는 무기한"),
    ("解き放ちます。효과は無期限", "해방합니다. 효과는 무기한"),
    ("解き放ちます。効果は無期限", "해방합니다. 효과는 무기한"),
    ("秘められた力を解放します", "숨겨진 힘을 해방합니다"),
    ("すごい能力을発揮します", "대단한 능력을 발휘합니다"),
    ("すごい能力を発揮します", "대단한 능력을 발휘합니다"),
    ("全般的に上昇させます", "전반적으로 상승시킵니다"),
    ("全般的に減少させます", "전반적으로 감소시킵니다"),
    ("大幅に上昇させます", "크게 상승시킵니다"),
    ("大幅に減少させます", "크게 감소시킵니다"),
    ("命中も上昇させます", "명중도 상승시킵니다"),
    ("命中を上昇させます", "명중을 상승시킵니다"),
    ("回避を上昇させます", "회피를 상승시킵니다"),
    ("威力も上昇させます", "위력도 상승시킵니다"),
    ("威力を上昇させます", "위력을 상승시킵니다"),
    ("装甲も上昇させます", "장갑도 상승시킵니다"),
    ("反応を減少させます", "반응을 감소시킵니다"),
    ("移動力を上昇させます", "이동력을 상승시킵니다"),
    ("移動を上昇させます", "이동을 상승시킵니다"),
    ("痛撃率も上昇させます", "통격률도 상승시킵니다"),
    ("先制攻撃を行います", "선제 공격을 합니다"),
    ("完全に回避します", "완전히 회피합니다"),
    ("撃破しなくなります", "격파되지 않습니다"),
    ("散開させます", "산개시킵니다"),
    ("回復させます", "회복시킵니다"),
    ("発動させます", "발동시킵니다"),
    ("上昇させます", "상승시킵니다"),
    ("減少させます", "감소시킵니다"),
    ("効果は３ターン", "효과는 3턴"),
    ("効果は無期限", "효과는 무기한"),
]

EFFECT_BY_ID: dict[str, str] = {}  # filled from reconstructed templates
WEAPON_KO: dict[str, tuple[str, str]] = {
    "GGA-TEXT-0017A275": ("중돌격 기관총", "Ginn MMI-M8A3; 重突撃機銃"),
    "GGA-TEXT-0017A27E": ("중참도", "Ginn heavy blade; 重斬刀"),
    "GGA-TEXT-0017A285": ("팔두스 3연장 유도탄", "Ginn Pardus 3-tube missile"),
    "GGA-TEXT-0017A41B": ("돌격", "reconstructed 8x16 突撃 (same 突 slot as Ginn 重突撃機銃)"),
}
EXTRA_KO: dict[str, str] = {
    "GGA-TEXT-001BE7B4": "ID 설명 없음",
    "GGA-TEXT-001BE7BE": "세이브하시겠습니까?",
    "GGA-TEXT-001BE7CA": "아니오",
}


def translate_desc(jp: str) -> str:
    text = jp
    for src, dst in DESC_REPLACEMENTS:
        text = text.replace(src, dst)
    return text


def decode_row(row: dict[str, Any], dictionary: list, mapping: dict[int, str]) -> tuple[str, list[int]]:
    raw = raw_hex_bytes(str(row.get("raw_hex") or ""))
    if not raw or raw == b"\x00":
        return "", []
    slots = expand_to_slots(read_tokens(raw, 0)[0], dictionary)
    out: list[str] = []
    missing: list[int] = []
    for slot in slots:
        ch = mapping.get(slot)
        if ch:
            out.append(ch)
        else:
            out.append(f"<{slot:04X}>")
            missing.append(slot)
    return "".join(out), missing


def apply_row(row: dict[str, Any], ko: str, jp: str, note: str) -> None:
    row["source_text"] = jp
    row["source_decode_status"] = "complete"
    row["source_unresolved_slots"] = []
    row["translation_ko"] = ko
    row["translation_status"] = "translated"
    row["translation_policy"] = "translate"
    row["translation_source"] = "curated_project_data"
    row["translator_notes"] = note
    row["overlay_batch_id"] = BATCH


def reconstruct_effect(text: str) -> str | None:
    out = text
    out = out.replace("回<04F0>", "회피")
    out = out.replace("<04DB><017F>", "반응")
    out = out.replace("<049F><0333>無効", "특수방어무효")
    out = out.replace("<045B>撃", "통격")
    out = out.replace("手加<028F>", "추가")
    out = out.replace("<0408><0310>め", "산개")
    out = out.replace("<0534><01BA><05AD>", "SP")
    out = out.replace("無<01F5><0293>ハイパー化", "무제한 하이퍼화")
    out = out.replace("ID効<0195><0374><0221>", "ID 효과 무효")
    if "<" in out:
        return None
    out = out.replace("・", "·")
    out = out.replace("味方", "아군")
    out = out.replace("自軍", "자군")
    out = out.replace("敵", "적")
    out = out.replace("完全", "완전")
    out = out.replace("威力", "위력")
    out = out.replace("命中", "명중")
    out = out.replace("装甲", "장갑")
    out = out.replace("防御力", "방어력")
    out = out.replace("攻撃力", "공격력")
    out = out.replace("攻撃", "공격")
    out = out.replace("移動強化", "이동 강화")
    out = out.replace("移動力", "이동력")
    out = out.replace("防御", "방어")
    out = out.replace("回避", "회피")
    out = out.replace("反応", "반응")
    out = out.replace("無効", "무효")
    out = out.replace("封印", "봉인")
    out = out.replace("回復", "회복")
    out = out.replace("散開", "산개")
    out = out.replace("捨て身", "버리기")
    leftover = JP_LEFT.findall(out)
    if leftover:
        return None
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    rom = (ROOT / "SD Gundam GGeneration Advance (Japan).gba").read_bytes()
    dict8 = load_dictionary(rom, DICT_8X16_BASE, DICT_8X16_END)
    dict12 = load_dictionary(rom, DICT_12X12_BASE, DICT_12X12_END)
    map8 = load_map(ROOT / "analysis" / "ggen_advance_8x16_charmap_supplement_20260828.json")
    map12 = load_map(ROOT / "analysis" / "ggen_advance_12x12_identified_charmap_20260828.json")
    map12.update(CORRECTED_LOW_KANA)
    merged = json.loads(MERGED_IN.read_text(encoding="utf-8"))

    desc_fail: list[str] = []
    desc_ok = 0
    for row in merged["records"]:
        if row.get("semantic_category") != "id_command_description":
            continue
        if row.get("translation_status") == "translated":
            continue
        jp, miss = decode_row(row, dict12, map12)
        if miss or not jp:
            continue
        ko = translate_desc(jp)
        leftover = JP_LEFT.findall(ko)
        if leftover:
            desc_fail.append(f"{row['record_id']}: {jp!r} -> {ko!r} leftover={leftover}")
            continue
        apply_row(row, ko, jp, "12x12-decoded ID-command description")
        desc_ok += 1
    if desc_fail:
        print("\n".join(desc_fail[:40]))
        raise SystemExit(f"ID description leftover JP in {len(desc_fail)} rows")

    effect_ok = effect_skip = 0
    for row in merged["records"]:
        if row.get("semantic_category") != "id_command_effect_summary":
            continue
        if row.get("translation_status") == "translated":
            continue
        text, _ = decode_row(row, dict8, map8)
        ko = reconstruct_effect(text)
        if not ko:
            effect_skip += 1
            continue
        jp_note = (
            text.replace("<04F0>", "避")
            .replace("<04DB><017F>", "反応")
            .replace("<049F><0333>", "特殊防御")
        )
        apply_row(row, ko, jp_note, "reconstructed 8x16 ID-command effect summary")
        effect_ok += 1

    weapon_ok = 0
    for row in merged["records"]:
        spec = WEAPON_KO.get(row["record_id"])
        if not spec:
            continue
        ko, note = spec
        jp, _ = decode_row(row, dict8, map8)
        apply_row(row, ko, jp, note)
        weapon_ok += 1

    extra_ok = 0
    for row in merged["records"]:
        ko = EXTRA_KO.get(row["record_id"])
        if not ko:
            continue
        jp, _ = decode_row(row, dict12, map12)
        apply_row(row, ko, jp, "12x12-decoded direct-PC UI line")
        extra_ok += 1

    MERGED_OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "merged_out": str(MERGED_OUT),
                "id_descriptions": desc_ok,
                "effect_summaries": effect_ok,
                "effect_skipped": effect_skip,
                "weapons": weapon_ok,
                "extra_ui": extra_ok,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
