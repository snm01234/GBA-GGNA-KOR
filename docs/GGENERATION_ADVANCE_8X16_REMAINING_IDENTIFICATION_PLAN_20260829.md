# G Generation Advance 생산/UI 8×16 잔여 1,097 슬롯 식별 계획

작성 기준: 2026-08-29  
작업 루트: `D:\monoeye\advance`  
기준 카탈로그: `analysis/ggen_advance_remaining_identification_20260829.json`

운영 경계: 이 계획과 `advance` 하위 활성 도구는 `D:\monoeye\advance` 내부만을 프로젝트 범위로 사용한다. 상위 `D:\monoeye`의 도구·데이터·자산·문서를 참조하지 않으며, Main TIP 승격·POC 정리·번역 통합 정본 규칙은 [`GGENERATION_ADVANCE_KO_PROGRESS.md`](GGENERATION_ADVANCE_KO_PROGRESS.md)의 §23을 따른다.

## 1. 현재 기준선

- 생산/UI 잔여 고유 텍스트 슬롯: **1,097**
- 폰트: 전부 **8×16**
- pending translate: production **2,148**, non_scenario_ui **1,355**, scenario_map_script **326**
- 잔여 슬롯 hold 분류:
  - `no_single_unknown`: **852**
  - `mixed_frames_held`: **65**
  - `single_collocation`: **180**
- 현재 8×16 verified charmap: **365 슬롯**
- 12×12 시나리오/맵 쪽은 현재 unresolved 0까지 폐쇄되어, 같은 ROM 안의 일본어 문장 corpus로 사용할 수 있다.

## 2. 이번 분석에서 확인한 구조적 주의점

### 2.1 같은 슬롯 번호를 12×12에서 복사하면 안 됨

두 폰트의 슬롯 번호 체계는 다르다. 기존 작업 원칙을 그대로 유지한다.

### 2.2 단순 cross-font 최근접은 승격 근거가 아님

기존 8×16→12×12 직접 shape matcher는 known pair에서 정확도가 낮다. bbox 정규화로 개선은 가능하지만 단독 자동승격 정확도에는 미달한다. 앞으로는 시각 유사도를 **보조 증거**로만 사용한다.

### 2.3 기존 same-ROM corpus 정렬도 조건이 약하면 오탐함

맵 스크립트 corpus를 생산/UI 문자열에 길이+부분 일치로만 맞추면, 이미 아는 suffix만으로 `出動させます` 같은 후보가 유일해져 미지 prefix를 잘못 채울 수 있다. 따라서 `unique candidate` 자체를 exact evidence로 취급하지 않는다.

### 2.4 8×16에서 동일 문자의 중복 슬롯 가능성을 배제하면 안 됨

기존 offset probe는 `used_chars`를 전역 배제한다. 잔여 분석에서는 동일 문자가 다른 슬롯에 다시 존재할 가능성을 열어 둬야 한다. 따라서 `char already used`는 거절 조건이 아니라 충돌/중복 검토 항목이다.

## 3. 식별 파이프라인

### Phase A — same-ROM 정렬기의 정밀도 보정

1. fully decoded 12×12 맵 스크립트의 일본어를 내부 corpus로 만든다.
2. 생산/UI 8×16 row를 길이별 corpus와 정렬한다.
3. 이미 식별된 8×16 슬롯을 anchor로 사용한다.
4. mapped 슬롯 하나를 일부러 숨기는 leave-one-out 검증을 수행한다.
5. 다음 조건별 실제 precision/coverage를 측정한다.
   - anchor 수
   - anchor 비율
   - 미지 슬롯 수
   - 좌/우 anchor 존재 여부
   - 가장 긴 미지 연속구간 길이
   - 후보 수 1 여부
6. 검증 precision이 충분하지 않은 임계값은 실제 잔여 1,097개에 적용하지 않는다.

목표: **고정밀 규칙을 먼저 얻고, coverage는 그 다음 문제로 취급**한다.

### Phase B — 잔여 1,097개 후보 점수화

슬롯마다 다음 증거를 독립적으로 집계한다.

- same-ROM map-script unique alignment vote
- 서로 다른 source_text/frame에서 동일 문자가 반복되는지
- 서로 다른 semantic category에서도 일치하는지
- single-collocation 문맥
- 8×16 bitmap 자체
- 12×12 동일 문자 glyph와의 시각 유사도(보조)
- Windows font exact bitmap probe(보조, 단독 승격 금지)
- 기존 broad/external corpus probe는 참고만 하고 승격 근거에서는 제외

### Phase C — 승격 등급

- **A / promote**: 독립 문맥 2개 이상 + 같은 문자 + 보정된 정렬 규칙 통과, 또는 ROM 내부 구조적 exact evidence
- **B / review**: 문맥은 강하지만 독립성이 부족하거나 시각 보조만 일치
- **C / hold**: 단일 collocation, 후보 충돌, suffix-only 정렬, 외부 corpus만 일치
- **D / blocked**: 현재 anchor가 거의 없어 재해독 근거 부족

### Phase D — 실제 반영

A 등급만 `analysis/ggen_advance_8x16_charmap_supplement_20260828.json`에 provenance와 함께 추가한다.

반영 후 반드시 다음을 재생성/검증한다.

1. pending decode audit
2. remaining identification
3. 생산/UI pending 감소량
4. 기존 verified charmap 충돌 0
5. dictionary regression 0
6. PoC 적용용 charmap에서 아직 살아 있는 일본어 슬롯 침범 0

## 4. 우선순위

1. `single_collocation` 180개 중 고빈도 슬롯
2. `mixed_frames_held` 65개 — 서로 다른 문맥이 있으므로 오히려 강한 교차검증 가능
3. `no_single_unknown` 852개 — 고정밀 alignment로 주변 슬롯이 닫힌 뒤 재분류

빈도만으로 승격하지 않는다. 빈도는 **검증 효율 순서**에만 사용한다.

## 5. 첫 실행 목표

이번 패스에서는 다음을 완료한다.

- leave-one-out same-ROM 정렬 검증 도구 작성
- 실제 precision/coverage 측정
- 잔여 1,097개를 A/B/C/D 후보로 1차 분류
- A가 존재할 경우에만 첫 안전 배치를 적용
- 결과와 다음 큐를 이 문서 및 별도 JSON/보고서에 기록

## 6. 금지 사항

- 12×12 동일 슬롯 번호 복사 금지
- 단일 문장 추정만으로 승격 금지
- broad/external corpus의 단독 투표 승격 금지
- cross-font 최근접 1위만으로 승격 금지
- 불변 unified source 수정 금지
- `D:\monoeye\advance` 밖 파일 수정 금지
