# SD Gundam G Generation Advance 통합 번역 시트 작업 현황

작성 기준: **2026-08-29**  
작업 상태: **ID커맨드 설명·효과·진 무장까지 32 MiB PoC 반영. 실측에서 `ID커맨드없음`만 일본어**  
대상 프로젝트: `D:\monoeye\advance`  
승인 main TIP: `SD Gundam GGeneration Advance (Korean).gba`  
SHA-256 `408600fc6e136dc5b9ade25a0107ee621caee276388d7e5122718496a8997dd7`
승격 근거 POC: `outputs/20260829_ggen_advance_unified_rom/ggen_advance_unified_translation_poc_20260834.gba`  
활성 번역 정본: `integrated/translation/ggen_advance_translation_merged.json`  
단일 통합 workbook: `integrated/translation/ggen_advance_translation_master.xlsx`

## 1. 작업 목적과 적용 원칙

게임 내 텍스트와 포인터 소스를 하나의 통합 시트로 관리하고, 구조 단위 배치로 한국어 번역을 누적 반영하는 작업이다.

- 대화문은 직역보다 자연스러운 의역을 우선한다.
- 건담 시리즈 고유명사와 기존 용어를 우선 재사용한다.
- 포인터, raw byte, 슬롯, 길이, `<S>` 같은 제어 표식은 번역과 분리해 보존한다.
- 원문 해독이 불완전한 항목은 추정 번역으로 채우지 않고 `pending`으로 남긴다.
- 통합 XLSX는 번역 초안 산출물이며, 이번 작업에서는 ROM에 직접 쓰지 않았다.

## 2. 통합 소스 기준

| 항목 | 수량 |
|---|---:|
| 현재 병합 전체 레코드 | **20,088** |
| canonical 레코드 | **19,713** |
| alias 레코드 | 375 |
| owner 엔트리 | **21,951** |
| 제외 엔트리 | 12,263 |
| 번역 완료 | **17,786** |
| pending | **1,093** |
| needs_review | **156** |
| preserve 대상 | 678 |

불변 원본은 다음 파일이다.

`analysis/ggen_advance_unified_source_20260827.json`

ROM SHA-256:

`75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772`

## 3. 현재 누적 결과

| 상태 | 수량 |
|---|---:|
| 번역 완료 | **17,786** |
| 번역 대기 | **1,093** |
| needs_review | **156** |
| preserve | 678 |
| alias | 375 |
| 누적 오버레이 batch | **29** |
| overlay 반영 record | **14,849** |

위 표는 2026-08-29 현재 중앙 정본의 실제 record 필드 기준이다. 아래 날짜별 배치 표는 당시 작업 경과를 보존하는 historical snapshot이다.

이번 작업에서 새로 반영한 구조 배치는 다음과 같다.

| 배치 | 신규 레코드 | 내용 |
|---|---:|---|
| `map-script-complete-20260828` | 8,089 | 슬롯 닫힌 맵 인라인 대사. unique JP 6,928. 공백 156은 needs_review |
| **합계** | **8,089** | 이전 6,760에서 시트 번역 14,693으로 증가 (공백 156 제외) |

직전(같은 날) 배치는 다음과 같다.

| 배치 | 신규 레코드 | 내용 |
|---|---:|---|
| `scenario-pending-dialogue-20260828` | 1,064 | 12×12 전량 폐쇄 후 시나리오 대사. unique JP 994 |
| `scenario-pending-bark-20260828` | 390 | 미사용 바크 라벨. 화자·종류만, `＠` 유지 |
| **합계** | **1,454** | 이전 5,306에서 6,760으로 증가 |

직전(같은 날) 배치는 다음과 같다.

| 배치 | 신규 레코드 | 내용 |
|---|---:|---|
| `fully-decoded-bark-templates` | 865 | 미사용 바크 슬롯 라벨. 화자명은 기존 용어, `＠` 자리는 유지 |
| `reserved-prefix-heavy-gun-0002` | 2 | 예약 접두만 남은 헤비건. 본문은 기존 `헤비건` |
| **합계** | **867** | 이전 4,439에서 5,306으로 증가 |

직전(같은 날) 배치는 다음과 같다.

| 배치 | 신규 레코드 | 내용 |
|---|---:|---|
| `fully-decoded-scenario-dialogue` | 920 | 슬롯이 닫힌 시나리오 전투 대사 |
| `fully-decoded-production-labels` | 220 | 슬롯이 닫힌 생산/전투 라벨 |

직전(같은 날 오전) 배치는 다음과 같다.

| 배치 | 신규 레코드 | 내용 |
|---|---:|---|
| `scenario-decoded-dialogue-0208` | 208 | 슬롯 완전 해독 전투 대사. `〜セリフ`+＠ 템플릿은 제외 |
| `decoded-safe-labels-0015` | 15 | 동방불패, OZ 사관, 비트/퍼넬 등 안전 짧은 라벨 |

2026-08-27 마지막 배치는 다음과 같다.

| 배치 | 신규 레코드 | 내용 |
|---|---:|---|
| `unit-name-reserved-0054` | 54 | 예약 표식만 남은 기체명 |
| `known-series-0013` | 13 | 해독 가능한 건담 시리즈·브랜드 라벨 |
| `decoded-supplement-0039` | 39 | 보조 글리프로 완전 복원된 무기·인물·라벨 |

기존 누적 배치는 다음과 같다.

- 고정 UI 보정 4개 배치: 40건씩, 총 160건
- 안전 기체명: 481건
- 안전 인물명: 227건
- 기체명 alternate tail: 13건
- 고정 짧은 라벨: 190건
- static tail: 3건
- 시나리오 전투 문장: 500 + 394 + 214건
- 시나리오 템플릿: 158 + 293 + 106 + 230 + 1건
- 마지막 구조 배치(08-27): 54 + 13 + 39건
- 2026-08-28 오전: 시나리오 슬롯 해독 대사 208 + 안전 라벨 15
- 2026-08-28 낮: fully_decoded 시나리오 920 + 생산 라벨 220
- 2026-08-28 오후: 미사용 바크 템플릿 865 + 예약 접두 헤비건 2
- 2026-08-28 저녁: 시나리오 leftover 폐쇄분 대사 1,064 + 바크 390

## 4. 사용자 용어 수정 반영

다음 수정은 통합 오버레이에 반영되었다.

- `하이곡` → `하이고크`
- `빅로` → `비그로`

## 5. 산출물

통합 병합 결과:

`analysis/ggen_advance_translation_merged_20260827.json`

최종 XLSX (08-27 스냅샷):

`outputs/20260827_ggen_advance_unified_translation/ggen_advance_unified_translation_20260827.xlsx`

08-28 통합 XLSX는 PNG 미리보기를 생략한 뒤 저장에 성공했다. 수식 오류는 0건이며 ROM 쓰기 플래그는 `false`다.

`outputs/20260828_ggen_advance_unified_translation/ggen_advance_unified_translation_20260827.xlsx`

글리프 정적 분석 산출물:

- `analysis/ggen_advance_12x12_offset_charmap_20260828.json` — 12×12 검증 슬롯 1,160 (오프셋 exact match +67, 시각 확인)
- `analysis/ggen_advance_8x16_charmap_supplement_20260828.json` — 사전 bijection 8×16 280슬롯
- `analysis/ggen_advance_pending_decode_audit_20260828.json`
- `analysis/ggen_advance_scenario_decoded_dialogue_ko_20260828.json`
- `analysis/ggen_advance_12x12_identified_charmap_20260828.json` — 12×12 **1,219**
- `analysis/ggen_advance_8x16_charmap_supplement_20260828.json` — 8×16 **340**
- `analysis/ggen_advance_remaining_identification_20260828.json` — pending 6,964건 전수 분류 + 잔여 슬롯 hold를 **폰트×슬롯**으로 분리 (1,329)
- `analysis/ggen_advance_remaining_glyph_priority_20260828.json`
- `analysis/ggen_advance_pending_decode_audit_20260828.json`

pending 식별 분류 스냅샷(최초 6,964건) 대비 현재 반영은 다음과 같다.

| 분류 | 배치 전 | 이번까지 반영 | 의미 |
|---|---:|---:|---|
| unused_bark_template | 865 | 865 | `セリフ`+＠ 미사용 슬롯 라벨. 화자명·종류만 번역, `＠` 유지 |
| fully_decoded | 1,420 | 1,140 | 클린 문장만 번역. bijection 잔재 280건은 pending |
| reserved_markers_only | 2 | 2 | 헤비건 예약 접두 |
| single_unknown_text_slot | 1,736 | 0 | 텍스트 슬롯 1개만 남음. 추정 금지 |
| few_unknown_text_slots | 1,549 | 0 | 2–3개 |
| many_unknown_text_slots | 1,392 | 0 | 4개 이상 |
| 사전 319엔트리 | 316 완전 / 3 구멍 |  |  |

이번 추가(근거 있는 슬롯만, 번호 복사 금지): 12×12 `進`/`始`/`訳`, 8×16 `身`/`下`/`許`. 사전 3구멍은 그대로 `しXと`·양쪽 미지 페어 2건.

## 6. 남은 작업과 재개 시 주의점

이 절의 3,985건 수치는 **2026-08-28 시트 스냅샷**이다. 2026-08-29 권위는 §16–§17과 `ggen_advance_translation_merged_20260834.json`(translated **17,786** / pending **1,093** / needs_review **156**)이다.

시나리오 해독은 불변 `source_text`의 가나 초안을 믿지 말고 **원본 slot 리스트 + 보정 저번 가나**로 다시 읽어야 한다. 8×16 corpus 투표 맵(`min2`)은 `07FB→ア` 같은 오탐이 있어 승격하지 않는다. 해독되지 않은 슬롯을 임의로 추정해 번역하는 방식은 사용하지 않는다.

재개 시 지켜야 할 파일 경계는 다음과 같다.

1. `analysis/ggen_advance_unified_source_20260827.json`은 수정하지 않는다.
2. 기존 배치 오버레이는 20260827 identity `e07223…1382f9`를 유지한다.
3. 활성 권위 병합 정본은 `integrated/translation/ggen_advance_translation_merged.json`이다. `analysis/ggen_advance_translation_merged_20260834.json`은 승격 근거 historical snapshot이며, 번역 merge 자체는 ROM에 쓰지 않는다.
4. 같은 슬롯 번호라도 12×12 라벨을 8×16에 복사하지 않는다.
5. 어색한 표현의 후속 교정은 별도 보정 배치로 처리한다.

현재 플레이 체크포인트는 승인 main TIP `SD Gundam GGeneration Advance (Korean).gba`이며, §16의 `…poc_20260834.gba`는 승격 근거다. 상세 로그는 `docs/GGENERATION_ADVANCE_KO_PROGRESS.md` §22.53–22.56이다.

## 7. 통합시트 밖 커버리지 감사 (20260828)

질문: 시트 약 1만 건이 원본 ROM 인게임 텍스트 전수가 아니라면, 시나리오·전투대사·ID커맨드가 시트 밖에 남아 있는가.

도구: `tools/audit_ggen_advance_unified_coverage.py`  
산출: `analysis/ggen_advance_unified_coverage_audit_20260828.json`  
결과: **PASS**. owner-proven family는 시트와 불일치 0. 승격 후보 0. 불변 소스와 XLSX는 행을 추가하지 않았다.

| 독립 재구성 | 시트 canonical | 누락 |
|---|---:|---:|
| production 4,069 | 4,069 | 0 |
| 시나리오 디렉터리 unique 5,343 (pointer 5,345, null slot 89) | scenario_main 5,343 | 0 |
| UI rendered 1,739 | UI 1,529 + production 교집합 210 | 0 |
| ID커맨드 producer 2,018 | name 369 + effect 119 + description 862 + inactive 668 (+ fallback 2는 direct-PC) | 0 |
| 전투조건 family | 236 | producer 대비 0 |

제외 풀 12,263 분류:

| 분류 | 건수 | 판정 |
|---|---:|---|
| UI review_only, draw 없는 selector | 1,432 | 승격 금지 (availability/bit check만) |
| UI review_only이지만 같은 스트림이 이미 rendered | 48 | 이미 시트에 있음 |
| 스캔이 review_only 타깃과 중복 | 1,359 | 이중 집계 |
| canonical 스트림 내부(중간 포인터) | 143 | 오탐 |
| 스캔 잔여, producer/렌더러 owner 없음 | 9,281 | 번역 큐 아님 |

CA0 196곳 중 시트에 없는 PC 리터럴 2건(`0x00D58C90`, `0x00D58FE4`)은 `bstgmain.c` / `D2` 디버그 문자열이다. F54 리터럴 1건(`0x00FCE3C8`)은 포인터 테이블이며 첫 타깃 `0x001BE9D7`은 이미 시트에 있다. 셋 모두 승격하지 않는다.

스캔 잔여 9,281은 헤더/코드/기타 데이터/디버그 테일에 흩어져 있고, 시나리오 뱅크·ID커맨드 테이블에서 빠진 항목이 아니다. 포인터가 토큰 문법만 만족하는 오탐으로 남긴다.

따라서 **시트 밖 미분석 시나리오/전투대사/ID커맨드 누락은 없다**고 본 감사는 **디렉터리·포인터 owner 가족**에 한정된다. 맵 컷신 대사는 U32 owner가 없는 인라인 바이트코드라 그 스캔에 안 잡혔고, §11에서 8,415행으로 시트화했다.

## 8. 통합시트 → 32 MiB 확장 ROM 적용 (20260828)

확인된 번역 초안 6,760건을 **별도 32 MiB PoC ROM**에 넣었다. 불변 소스·20260825 한글 charmap plan·원본 16 MiB 폰트 바이트는 건드리지 않는다. 병합 JSON의 `rom_write_performed`도 그대로이며, 이번 쓰기는 아래 산출 파일뿐이다.

도구: `tools/build_ggen_advance_unified_rom_poc.py`  
ROM: `outputs/20260828_ggen_advance_unified_rom/ggen_advance_unified_translation_poc_20260828.gba` (32 MiB, SHA-256 `e12be04b5491b0d6183b8bfd8a62a379bb971d19af46e0ea04c6b9f7a2362d46`)  
매니페스트: `analysis/ggen_advance_unified_rom_poc_20260828.json`  
적용용 charmap: `analysis/ggen_advance_korean_apply_charmap_20260828.json`  
오버레이 identity: `e07223d4665cd834e01f1548b3960e1a920bc25d8f41f7a1355a0e48621382f9`  
정적 게이트: **PASS** (원본 반쪽 예기치 않은 변경 0, 원본 폰트 보존, strong tail·헤더 보존, 재배치 payload 9,586건 일치, `pending_scenario_unmoved` 0)

| 범위 | 한국어 재배치 | 원문 유지 |
|---|---:|---:|
| production 4,069 | 1,243 (예약 접두 384 포함) | 2,826 (컨테이너는 옮기되 원문 바이트) |
| scenario_main 5,343 | **5,343** | 0 |
| non_scenario_ui unique 1,529 | 174 | 1,355 (원본 포인터 유지) |
| **합계 ready 6,760** | **6,760** | encode 실패 0 |

한글 831자에 글리프를 그렸다(8×16 447 / 12×12 763). 남은 일본어가 아직 쓰는 슬롯은 칠하지 않는다. 생산·시나리오 양쪽에 나오는 글자만 두 폰트 모두 비어 있는 슬롯(`free_both`)을 쓰고, 한쪽 문맥만 있는 글자는 해당 폰트만 칠한다. 바크 패딩 `＠`는 ASCII `@`가 아니라 원본 토큰 `E641`(슬롯 `0x0721`)을 유지한다.

추가 포인터: 시나리오 디렉터리 5,345, dynamic 무기 삽입 1,468, UI 174(+ production 교집합 210). 텍스트 커서는 `0x0107FA84`이며 영역 잔여 약 1.84 MiB다. pending 3,503은 추정 번역 없이 일본어로 남긴다.

## 9. 시나리오 pending 1,454 잔여 12×12 전량 폐쇄 (20260828)

POC 재빌드보다 먼저, 시나리오 leftover 12×12 **192칸을 0**으로 닫았다. 불변 소스·기존 32 MiB PoC·오버레이는 그대로다. 추정 번역 없음. 8×16 번호 복사 없음.

방법: 원본 slot 리스트 + 보정 저번 가나 + identified 12×12. leftover==1 프레임이 서로 다른 복합어로 일치하고 글리프가 맞을 때만 승격. 이미 다른 칸에 있는 한자면 남은 읽기를 쓴다 (`遠距離` not `長`, `総員` not `乗`, `重力` not `引力`, `根絶やし` not `根こそぎ`).

12×12 identified **1,234 → 1,426** (+192). 적용 도구: `tools/apply_ggen_advance_scenario_pending_promotions.py`.

| 시나리오 pending 1,454 | 결과 |
|---|---:|
| 슬롯 완전 대사 | **1,064** |
| 슬롯 완전 바크 템플릿 | **390** |
| 아직 미해독 | **0** |
| 잔여 12×12 슬롯 (시나리오 소비) | **0** |

닫힌 일본어: `analysis/ggen_advance_scenario_pending_closed_strings_20260828.json` (대사 unique 994 / 바크 unique 174). 번역 초안·merge·PoC는 §10.

사전 319는 여전히 **316 완전 / 3 구멍**. 12×12 `0x012F`=ぶ로 `しぶと`는 닫혔고, 8×16 `0x0115`는 투표 1이라 승격하지 않는다. 나머지 구멍은 `尻`+`0x05CC`, `0x07A0`+`0x07A1`.

시트 전체 잔여 텍스트 슬롯은 **8×16 1,122칸**뿐이며, 이번 1순위 범위가 아니다.

## 10. 시나리오 leftover 초안 오버레이 → merge → PoC (20260828)

슬롯이 닫힌 1,454행을 오버레이로 옮겼다. 불변 소스 미수정. compact JSON은 overlays `rglob`에 잡히지 않게 `analysis/`에만 둔다.

- 대사 unique 994 → `analysis/ggen_advance_scenario_pending_dialogue_ko_20260828.json`
- 오버레이: `scenario_pending_dialogue_1454.json` (1,064) + `scenario_pending_bark_0390.json` (390)
- merge **PASS**: translated 6,760 / pending 3,503 / overlay identity `e07223…1382f9`

첫 PoC에서 시나리오 31건이 한글 apply charmap에 없는 일본어 가나(`ー` `っ` `ッ` `ぁ` `ぉ` `ぇ` `い` `ォ`) 때문에 encode_failed로 원문 포인터에 남았다. KO에서 장음·작은 가나를 한글로만 고친 뒤 overlay·unique 맵을 동기화하고 merge·PoC를 다시 돌렸다.

재빌드 결과: `scenario_main` 5,343 전부 재배치, encode_failed 0, `pending_scenario_unmoved` 0. XLSX 재내보내기 도구는 이 워크스페이스에 없어 merge+PoC만 본경로로 두었다.

## 11. 맵 이벤트 인라인 대사 시트화 (20260828)

맵 컷신 대사는 디렉터리 5,343(`scenario_main`, 전투 바크)이 아니라 이벤트 바이트코드 `0x00F00000–0x00FC0000`의 opcode `0x18` 인라인 12×12 스트림이다. 화자/초상은 `17 E6 08 id 00`, 박스 개시는 `17 34 18`(드물게 `17 10 18`), 같은 화자의 다음 박스는 `00 18`. `08 11 09`는 삽입 제어가 아니라 글리프 `「G」`.

불변 소스 `ggen_advance_unified_source_20260827.json`은 수정하지 않았다. 기존 오버레이 identity도 20260827 merge에 남긴다.

도구: `tools/extract_ggen_advance_map_script_dialogue.py`, `tools/apply_ggen_advance_map_script_slot_promotions.py`, `tools/build_ggen_advance_map_script_sheet.py`

| 항목 | 수량 |
|---|---:|
| 맵 스크립트 레코드 | **8,415** |
| 해독 완료 | **8,089** |
| 잔여 슬롯 있는 행 | **326** (leftover 1칸 297 / 2칸 26 / 3칸 3) |
| 12×12 승격 (이 뱅크 leftover==1 만장일치) | **101** (배치1 16 + 배치2 51 + 배치3 32 + 배치4 2) |
| 12×12 identified | 1,426 → **1,527** |
| 맵 뱅크 잔여 고유 슬롯 | **177** (혼재·단일 문맥, 승격 거부) |

스크린샷 3문장 시트 행:

- `GGA-MAPSCRIPT-00F57825` なにっ！ / 敵艦が接近中だと！？ → 뭐라고！ / 적함이 접근 중이라고！？
- `GGA-MAPSCRIPT-00F57845` 艦種ナスカ級 / ザフトの高速戦艦です → 함종 나스카급 / 자프트의 고속 전함입니다
- `GGA-MAPSCRIPT-00F57870` ラミアス大尉に連絡！ / 「G」の搬入を急がせろ！ → 라미아스 대위에게 연락！ / 「G」 반입을 서두르게！

산출:

- `analysis/ggen_advance_map_script_translation_source_20260828.json`
- `analysis/ggen_advance_map_script_unified_records_20260828.json`
- `analysis/ggen_advance_map_script_dialogue_ko_20260828.json` (unique 6,928)
- `analysis/ggen_advance_translation_overlays/map_script_complete_8089.json`
- `analysis/ggen_advance_translation_merged_20260828.json` (번역 14,693 + 맵 leftover 326 pending)

시트 합계 canonical **19,356** / translated **14,693** / 대기 **3,985** (생산·UI 3,503 + 맵 leftover 326 + 공백 박스 156). leftover 0인 8,089행 중 **7,933**은 한국어 초안이고, 공백 박스 156은 `needs_review`, **326행**은 잔여 슬롯이라 pending이다. 잔여는 准将/少尉(`0x03B9`), 父/護(`0x0410`), 呪/縛(`0x05A2`), 選/生(`0x0550`), 禁/視(`0x026E`)처럼 한 칸이 서로 다른 한자로 읽히는 혼재이므로 추정 승격하지 않는다.

인라인 길이가 바뀌면 스크립트 점프가 밀리므로 맵 뱅크 일본어 바이트는 그대로 두고, 그리기만 재배치 한글로 넘긴다. PoC는 §12.

## 12. 맵 인라인 한국어 PoC (20260828)

시트 7,933행(세그먼트 12,304)을 32 MiB PoC에 넣었다. 불변 소스·20260825 charmap plan·맵 뱅크 `0x00F00000–0x00FC0000` 원문·원본 16 MiB 폰트는 건드리지 않는다. leftover 326과 공백 박스 156은 원문 유지.

도구: `tools/build_ggen_advance_unified_rom_poc.py`, `tools/patch_ggen_advance_map_script_inline_poc.py`  
ROM: `outputs/20260828_ggen_advance_unified_rom/ggen_advance_unified_translation_poc_20260828.gba` (32 MiB, SHA-256 `af88f18f8b91b08a9c315498d76dad0abb15be2a0404bd67772496eaec64d96c`)  
매니페스트: `analysis/ggen_advance_unified_rom_poc_20260828.json`  
적용용 charmap: `analysis/ggen_advance_korean_apply_charmap_20260828.json`  
부모 overlay identity `e07223…1382f9` 유지. 맵 overlay identity `18b01b2c…573541c9`.

방법: 원문 인라인은 스크립트 PC용으로 남기고, `0x0800118C` 진입/`0x080011B4` 종료와 `0x08000CA8` 드로우만 8바이트 트램폴린한다. 룩업 키는 세그먼트 시작 GBA 주소. 히트 시 한글 스트림을 그리고, 파서 반환값은 원문 NUL 주소라 호출측 `+1`이 일본어 바이트코드를 계속 걷는다. 맵 한글은 12×12 identified+apply-charmap으로 인코드한다(`G`는 슬롯 `0x0011`, ASCII 1바이트 폴백 없음).

정적 게이트: **PASS**. 맵 뱅크 변경 0, 훅 24바이트만 원본 반쪽에 추가, encode_failed 0, `pending_scenario_unmoved` 0. leftover가 쓰는 `尉`(`0x0158`)는 12×12에 한글을 칠하지 않았다.

| 범위 | 한국어 | 원문 유지 |
|---|---:|---:|
| 맵 translated 7,933 | **7,933** (세그먼트 12,304 룩업) | 0 |
| 맵 leftover pending | 0 | **326** |
| 맵 공백 needs_review | 0 | **156** |
| scenario_main 5,343 | 5,343 | 0 |

한글 1,013자. 생산·맵이 같이 쓰는 글자 중 `free_both`가 32칸 모자라면 8×16/12×12 슬롯을 쪼개 배정한다(토큰은 폰트별로 다름). 텍스트 커서 `0x010D7A2C`.

## 13. 20260831 시트 재적용 PoC (20260829)

병합 시트 translated 16,543을 다시 넣었다. 원본 16 MiB는 그대로 두고 산출만 갱신한다.

ROM: `outputs/20260829_ggen_advance_unified_rom/ggen_advance_unified_translation_poc_20260831.gba`  
SHA-256 `4b6e9b05937861a493b79e6038892a58c86ab0b1803e4959118d222ebe915f21`  
한글: Galmuri11.bdf / Galmuri11-Condensed.bdf 네이티브 BDF (Bold·Galmuri7 stretch 없음). 동일 파일을 `outputs/20260828_ggen_advance_font_tests/ggen_advance_galmuri11_12x12_galmuri11condensed_8x16_native_basic.gba`에도 두었다.  
매니페스트: `analysis/ggen_advance_unified_rom_poc_20260831.json`

| 범위 | 한국어 | 원문 유지 |
|---|---:|---:|
| production | 1,079 + 예약접두 384 | 2,606 |
| non_scenario_ui | 1,478 | 51 |
| scenario_main | 5,343 | 0 |
| 맵 컷신 | **8,259** (세그먼트 12,909) | 공백 156 |

정적 게이트 PASS. 도감은 12×12 인코드. 맵 leftover 326은 훅 룩업에 포함.

## 14. 글리프 침범 교정 + 시네마틱 나레이션 (20260832)

`I`/`ポ`/`対` live 12×12 슬롯에 한글을 칠하지 않는다. `table_1C92E8` 나레이션 75줄을 12×12로 해독·번역. 맵 훅에 opcode `0x18` 별칭.

시트 `ggen_advance_translation_merged_20260832.json`  
ROM `…poc_20260832.gba` SHA-256 `f3f6b8f3ca93d4e91921e8e97faebe44f025d1a5837dea9637ca3616e13a10e8`

## 15. 나레이션 폭 단축 + alt print-setup (20260833)

가운데 정렬 나레이션 4줄을 ≤16칸으로 단축. 추출에 `17 1C/1D/EE/35/03 18`과 체인 `01 18` 추가 → 맵 8,772행(신규 357). 356줄 번역.

시트 `ggen_advance_translation_merged_20260833.json`  
ROM `…poc_20260833.gba` SHA-256 `1f3df99d6307163f09a4db10ef8ecc8caf62f4a175b6aca18bc689443d54c90b`  
맵 encoded 8,615 / kept_original 157. 나레이션·오프닝 대사 실측 통과.

## 16. ID커맨드 설명·효과·진 무장 (20260834)

설명문은 12×12인데 8×16으로 읽고 있어 pending → 원문 JP + `위력`/`명중`만 한글. 756줄 12×12 번역. 효과 요약 118/119. 진 무장 3 + `돌격`. `ID 설명 없음` 등 3줄.

시트 `ggen_advance_translation_merged_20260834.json`  
ROM `…poc_20260834.gba` SHA-256 `408600fc6e136dc5b9ade25a0107ee621caee276388d7e5122718496a8997dd7`

| PoC 범위 | 한국어 | 원문 유지 |
|---|---:|---:|
| production 4,069 | 1,966 + 예약접두 384 | 1,719 |
| non_scenario_ui | 1,478 | 51 |
| scenario_main | 5,343 | 0 |
| 맵 컷신 | **8,615** (세그먼트 13,481) | **157** |

정적 게이트 PASS. 실측: 설명/효과/진 무장/우와아아아 한글. **`ID커맨드없음`만 일본어.**

`GGA-TEXT-001BE746` 시트는 `ID 커맨드 없음`. 화면 잔존은 다른 카피/빈 ID이름 필드 가능성. `001BE74E` 툴팁은 3슬롯 미해독.

## 17. 향후 과제

1. `ID커맨드없음` 실제 드로우 스트림 (`001BE746` vs 유닛 DB 빈 슬롯 vs `001BE74E`).
2. 스테이터스/무장 아이콘 한자 → 타일 경로.
3. 무장명 잔여 ~13, ID커맨드 이름 pending 129 (이름 12×12 인코드 변경 금지).
4. 8×16 잔여 unique·맵 leftover 157·설명문 빈 슬롯 106. mixed_frames 승격 금지.
5. 원본 16 MiB 쓰기 금지. 추정 번역 금지. `1T`/`HP`/`↑` 유지.

## 18. 현재 정본 경로와 advance 독립 운영

- 이 문서의 현재 통합 정본은 `integrated/translation/ggen_advance_translation_merged.json` 하나이며, 통합 workbook은 `integrated/translation/ggen_advance_translation_master.xlsx` 하나다. `analysis/`의 날짜별 병합 JSON과 `outputs/`의 날짜별 workbook은 historical evidence로만 유지한다.
- 승인 플레이·배포 ROM은 `SD Gundam GGeneration Advance (Korean).gba`로 고정한다. 날짜별 POC는 `tools/promote_ggen_advance_main_tip.py`를 거쳐서만 main TIP으로 승격한다.
- main TIP 승격 후 최종 반영되지 않은 POC 테스트롬과 임시 산출물은 정기적으로 분류하여 `legacy/poc/`로 이동하거나, 삭제 근거를 매니페스트에 남긴 뒤 제거한다.
- `D:\monoeye\advance`가 프로젝트 경계다. `advance` 하위의 활성 도구·데이터·문서는 상위 `D:\monoeye`의 도구·데이터·자산·문서를 참조하지 않으며, `..` 탈출·상위 절대 경로·상위 프로젝트 의존 import를 금지한다. 상세 규칙은 [`GGENERATION_ADVANCE_KO_PROGRESS.md`](GGENERATION_ADVANCE_KO_PROGRESS.md)의 §23을 따른다.
