#!/usr/bin/env python3
"""Apply 12x12-decoded table_1C92E8 narrative Korean onto the merged sheet."""
from __future__ import annotations

import json
from pathlib import Path

ADVANCE = Path(__file__).resolve().parent.parent
MERGED_IN = ADVANCE / "analysis" / "ggen_advance_translation_merged_20260831.json"
MERGED_OUT = ADVANCE / "analysis" / "ggen_advance_translation_merged_20260832.json"
DECODE = ADVANCE / "analysis" / "ggen_advance_table_1c92e8_12x12_decode_20260829.json"

# Narrative / epilogue only. Credit-roll name lines stay pending (live JP glyphs).
TRANSLATIONS: dict[str, str] = {
    "GGA-TEXT-001C8AD8": "지구에서 가장 먼 콜로니……",
    "GGA-TEXT-001C8AE9": "사이드 3는",
    "GGA-TEXT-001C8AF0": "지구연방정부를 상대로",
    "GGA-TEXT-001C8AFE": "독립 전쟁을 일으켰다",
    "GGA-TEXT-001C8B0B": "압도적인 국력을 가진 지구연방에 비해",
    "GGA-TEXT-001C8B1F": "지온 공국의 힘은 그 20분의 1",
    "GGA-TEXT-001C8B31": "누구나 믿어 의심치 않았던",
    "GGA-TEXT-001C8B3F": "지구연방군의 승리……",
    "GGA-TEXT-001C8B4C": "그러나 그 예상은",
    "GGA-TEXT-001C8B58": "여지없이 빗나가고 말았다",
    "GGA-TEXT-001C8B6A": "유전자를 조작한 인류……",
    "GGA-TEXT-001C8B7C": "코디네이터들의",
    "GGA-TEXT-001C8B88": "콜로니, 플랜트",
    "GGA-TEXT-001C8B92": "그리고 그 군사 조직 자프트",
    "GGA-TEXT-001C8BA2": "또한……",
    "GGA-TEXT-001C8BA8": "유럽에 큰 세력을 가진",
    "GGA-TEXT-001C8BBA": "롬펠라 재단과……",
    "GGA-TEXT-001C8BC8": "그 사병 집단 OZ",
    "GGA-TEXT-001C8BD4": "이런 제3세력의 개입으로",
    "GGA-TEXT-001C8BE8": "지온군은 초전에서",
    "GGA-TEXT-001C8BF5": "지구연방군을 압도했다",
    "GGA-TEXT-001C8C08": "그리고 전쟁이 교착 상태에",
    "GGA-TEXT-001C8C18": "빠진 지 반년 남짓……",
    "GGA-TEXT-001C8C28": "……지구연방",
    "GGA-TEXT-001C8C30": "……지온 공국",
    "GGA-TEXT-001C8C38": "……OZ",
    "GGA-TEXT-001C8C3E": "……자프트",
    "GGA-TEXT-001C8C44": "그리고……",
    "GGA-TEXT-001C8C4A": "때는 우주세기 0089…… 9월 중순",
    "GGA-TEXT-001C8C63": "여러 세력의 속셈을 품은 채",
    "GGA-TEXT-001C8C77": "지온과 연방의 싸움은",
    "GGA-TEXT-001C8C81": "더욱 격렬해져 갔다……",
    "GGA-TEXT-001C8C92": "크루제 대의 추격을 받으며……",
    "GGA-TEXT-001C8CA2": "아크엔젤은",
    "GGA-TEXT-001C8CA8": "중앙아시아로 강하했다",
    "GGA-TEXT-001C8CBA": "그 아크엔젤의",
    "GGA-TEXT-001C8CC2": "강하에 앞서 한 달……",
    "GGA-TEXT-001C8CD7": "연방의 「V작전」에 의해",
    "GGA-TEXT-001C8CE8": "개수된 신형 전함……",
    "GGA-TEXT-001C8CF9": "……화이트 베이스는",
    "GGA-TEXT-001C8D06": "지온군의 세력권인",
    "GGA-TEXT-001C8D14": "북미에서",
    "GGA-TEXT-001C8D1E": "가르마 자비가 이끄는",
    "GGA-TEXT-001C8D29": "지구 공격군과",
    "GGA-TEXT-001C8D33": "격렬한 전투를",
    "GGA-TEXT-001C8D3B": "벌이고 있었다……",
    "GGA-TEXT-001C8D48": "지온군의 공격으로",
    "GGA-TEXT-001C8D55": "자브로는 함락되었다……",
    "GGA-TEXT-001C8D65": "이 승리에 고무된",
    "GGA-TEXT-001C8D72": "지온군은……",
    "GGA-TEXT-001C8D7B": "지구 전토에서",
    "GGA-TEXT-001C8D86": "공세를 개시……",
    "GGA-TEXT-001C8D93": "연방군은 전례 없는 궁지로",
    "GGA-TEXT-001C8DA5": "몰리게 되었다",
    "GGA-TEXT-001C8DB3": "간신히 자브로를 탈출한",
    "GGA-TEXT-001C8DC3": "레빌 장군은……",
    "GGA-TEXT-001C8DCF": "오스트레일리아로 건너가",
    "GGA-TEXT-001C8DDC": "방어전을 지휘……",
    "GGA-TEXT-001C8DE8": "이로써 지온의 공세는",
    "GGA-TEXT-001C8DF7": "아슬아슬하게 막아내졌다",
    "GGA-TEXT-001C8E09": "그러나……",
    "GGA-TEXT-001C9223": "끝",
    "GGA-TEXT-001C9228": "아 바오아 쿠 전투로부터",
    "GGA-TEXT-001C9236": "며칠 뒤……",
    "GGA-TEXT-001C9241": "월면 도시 그라나다에서",
    "GGA-TEXT-001C9254": "지온 공국과 지구연방정부",
    "GGA-TEXT-001C9263": "사이에 종전 협정이 성립",
    "GGA-TEXT-001C9273": "지온 공국은",
    "GGA-TEXT-001C9279": "「지온 공화국」으로 이름을 바꿨다",
    "GGA-TEXT-001C928A": "또한 플랜트도 지구연방정부의",
    "GGA-TEXT-001C929B": "관할 아래로 돌아갔고……",
    "GGA-TEXT-001C92AB": "뒤에 1년전쟁이라 불린 싸움은",
    "GGA-TEXT-001C92BD": "여기서 끝났다",
    "GGA-TEXT-001C92C8": "때는 우주세기 0080",
    "GGA-TEXT-001C92D6": "초의 일이었다……",
}


def main() -> int:
    decode = {row["record_id"]: row for row in json.loads(DECODE.read_text(encoding="utf-8"))["records"]}
    merged = json.loads(MERGED_IN.read_text(encoding="utf-8"))
    updated = 0
    for row in merged["records"]:
        record_id = str(row.get("record_id") or "")
        ko = TRANSLATIONS.get(record_id)
        if not ko:
            continue
        info = decode.get(record_id)
        if info is None or info.get("unresolved_slots"):
            raise SystemExit(f"refusing unresolved narrative {record_id}")
        row["source_text"] = info["decoded_jp"]
        row["source_decode_status"] = "complete"
        row["source_unresolved_slots"] = []
        row["translation_ko"] = ko
        row["translation_status"] = "translated"
        row["translation_policy"] = "translate"
        row["translation_source"] = "curated_project_data"
        row["translator_notes"] = "12x12-identified decode of table_1C92E8 cinematic line"
        row["overlay_batch_id"] = "table-1c92e8-12x12-20260829"
        updated += 1
    if updated != len(TRANSLATIONS):
        raise SystemExit(f"updated {updated} != overlay {len(TRANSLATIONS)}")
    MERGED_OUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {MERGED_OUT} updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
