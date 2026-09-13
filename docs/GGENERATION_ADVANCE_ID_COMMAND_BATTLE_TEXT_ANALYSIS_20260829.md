# G Generation Advance — 전투/ID 커맨드 일본어 잔존 원인 분석 및 구현 계획

작성일: 2026-08-29  
대상: `SD Gundam GGeneration Advance (Korean).gba` main TIP  
프로젝트 경계: `D:\monoeye\advance` 하위만 사용

## 1. 실측 증상

사용자 실측 스크린샷에서 다음 계열이 한국어 번역 데이터가 존재함에도 일본어로 출력됐다.

- 전투/ID 커맨드 발동 대사
  - `アムロ……行きまーす！`
  - `うわぁぁぁ！！`
  - `ミノフスキー粒子散布！`
  - `ボクにだってやれるんだ！`
  - `俺はザフトのパイロットだ……`
  - `ヒーローはガラじゃ / ねえってのに……！`
  - `戦いは非情さ…… / 手加減はしない！`
- 일부 `IDコマンドなし` 계열
- 스테이터스/무장 화면의 `近接`, `射撃`, `反応`, `操縦系`, `運動`, `装甲`, `限界`, `移動`, `汎用` 등 고정 일본어 라벨

기존 22.55 단계에서 ID 커맨드 설명문과 효과 요약은 상당 부분 정상화됐지만, 실제 전투 중 출력되는 발동 대사는 별도 경로였다.

## 2. 핵심 원인

### 2.1 기존에 번역한 8×16 ID 커맨드 문자열과 전투 발동 12×12 문자열은 별도 데이터다

기존 production DB는 다음 구조를 사용한다.

- 캐릭터 DB: file `0x001A476C`, 256 records, stride `0x78`
- ID 커맨드 subrecord A: `record + 0x24 + command*0x1C`
  - semantic: `id_command_name`
- ID 커맨드 subrecord B: `record + 0x2C + command*0x1C`
  - semantic: `id_command_effect_summary`

이 경로의 다수 문자열은 이미 번역/relocate되어 있다.

하지만 전투 화면의 실제 발동 대사는 이 DB를 그대로 그리지 않는다. 별도의 12×12 전투 대사 테이블이 존재한다.

### 2.2 새로 확인한 전투 발동 테이블

- 테이블 base: file `0x00226984`, GBA `0x08226984`
- entry size: `8` bytes
- physical slots: `768 = 256 characters × 3 commands`
- slots `0..2`: NULL
- live slots: `3..767`, 총 `765`
- 각 entry
  - `+0x00`: 전투 발동 text container pointer
  - `+0x04`: 발동/조건 관련 metadata
- live pointer field 범위: `0x0022699C .. 0x0022817C`
- text payload 범위: 대략 `0x002231B4 .. 0x00226984`

인덱스는 코드상 `character_index * 3 + command_index`와 일치한다. 실측 예:

- table index `20` → character `6`, command `2` → 아스란 계열
- table index `172` → character `57`, command `1` → 키라 계열
- table index `525` → character `175`, command `0` → 무우 계열

### 2.3 접근 코드

핵심 accessor는 `0x0804FB2C`다.

호출부에서 캐릭터 인덱스와 커맨드 인덱스를 받아 8-byte record를 계산한다. 전투 표시 함수 `0x08018058`은 해당 record의 `+0x00` container pointer를 받아 일반 12×12 텍스트 빌더 `0x08000648`로 전달한다.

`0x08018100..0x0801811C`의 루프에서 container는 다음 방식으로 순차 파싱된다.

1. 현재 NUL token stream을 `0x08000648`에 전달
2. 2-byte token을 고려해 NUL까지 스캔
3. NUL 다음 1바이트를 control/continuation marker로 읽음
4. marker가 `0x01` 또는 `0x02`면 container 종료
5. 그 외 marker면 1바이트를 건너뛰고 다음 NUL token stream을 다시 출력

따라서 이 영역은 단순 `pointer -> 한 문자열`이 아니라 **여러 표시 문자열 + 1-byte continuation/control marker**로 이루어진 전투 대사 container다.

## 3. 스크린샷과 ROM 대응

| 화면 | 12×12 container 실문자열 |
|---|---|
| 아스란 | `俺はザフトのパイロットだ……` / `機体に手を掛けさせる訳には！` |
| 키라 | `うわぁぁぁ！！` |
| 가르마 등 | `ミノフスキー粒子散布！` |
| 아무로 | `アムロ……行きまーす！` |
| 하야토 | `ボクにだってやれるんだ！` |
| 무우 | `ヒーローはガラじゃ` / `ねえってのに……！` |
| 샤아 | `戦いは非情さ……` / `手加減はしない！` |

기존 통합 번역에는 같은/유사한 8×16 `unit_db_subrecord_text_A` 문장이 많이 존재하지만, `0x00223xxx..0x00226xxx` 전투 container 자체는 canonical record로 편입되지 않았기 때문에 main TIP에서 일본어가 남았다.

## 4. charmap 실측 교정

12×12 slot `0x05C9`는 기존 map에서 `腕`으로 오식별되어 `戦いは腕情さ……`로 정적 디코드됐다.

실측 화면은 `戦いは非情さ……`이며, 기존 분석에도 `腕`은 다른 slot(`0x06E5`)과 중복 근거가 존재한다. 따라서:

- `0x05C9: 腕 -> 非`

로 교정한다.

또한 8×16 pending 문장 `機体に手を掛けさせる<0580>には！`는 12×12 실측 평행문장에 의해 `<0580>=訳`의 강한 독립 근거가 생겼다. 이는 8×16 잔여 식별 캠페인에서 별도 승격 검토 대상으로 기록한다.

## 5. 구현 전략

### 단계 A — 구조 추출기 추가

전용 extractor를 추가해 765개의 table entry와 내부 visible stream을 모두 기록한다.

출력에는 최소 다음을 보존한다.

- table index / character index / command index
- table pointer source
- metadata `+0x04`
- container start/end
- 각 visible stream start, raw bytes, decoded JP, unresolved slots
- separator/control marker
- 대응하는 기존 8×16 ID command A/B pointer와 번역 레코드

### 단계 B — 번역 seed 생성

기존 canonical merged source에서 `source_text` exact match가 하나의 한국어 번역으로 결정되는 경우만 자동 seed한다.

추가로 실측 확정 문장은 수동 override로 고정한다. 추정 번역/미해독 슬롯은 자동 승격하지 않는다.

### 단계 C — 1차 runtime redirect 가설과 실측 폐기

초기에는 기존 map-script parser hook의 lookup redirect를 재사용해 각 visible JP stream 주소를 확장 한국어 stream으로 바꾸는 방식을 적용했다. 정적으로는 lookup에 535건이 모두 존재했지만, 실측에서 `ID 커맨드 없음`만 한글이고 키라 `うわぁぁぁ！！`, 무우 `ヒーローはガラじゃ…` 등 실제 발동 전투대사는 일본어 그대로였다.

재추적 결과 이유는 명확했다.

- generic redirect가 후킹하는 draw wrapper는 `0x08000CA8`이다.
- 실제 battle-bark 경로는 `0x0804FB2C`에서 256×3 entry를 얻은 뒤 `0x08018058`로 들어간다.
- `0x08018058`은 entry `+0x00` container pointer를 직접 받고 내부에서 `0x08000648`을 호출한다.
- 따라서 battle-bark는 `0x08000CA8`을 통과하지 않아 기존 lookup redirect를 전혀 보지 않는다.
- `ID 커맨드 없음`이 한글로 보였던 것은 이 bark redirect가 성공한 증거가 아니라, 별도의 기존 `id_command_fallback_text` 경로가 이미 한글화되어 있었기 때문이다.

따라서 parser runtime redirect 방식은 battle-bark 적용 경로로 **폐기**한다.

### 단계 C-2 — 256×3 table pointer 직접 재배치

수정 방식은 실제 consumer가 읽는 table `+0x00` pointer를 새 container로 바꾸는 것이다.

- 번역이 하나라도 있는 container만 32 MiB 확장영역에 재구성한다.
- 번역된 NUL stream만 한국어 12×12 token으로 교체한다.
- 같은 container 안의 pending JP stream은 원본 bytes를 그대로 복사한다.
- 각 stream 뒤 `0x03` continuation / `0x01` terminal marker와 tail padding을 byte exact 보존한다.
- table entry `+0x00` pointer만 확장 container 주소로 수정한다.
- table entry `+0x04` activation/condition metadata는 전 768 slot 모두 원본과 byte exact 유지한다.
- 원본 `0x002231B4..0x00226984` payload는 수정하지 않는다.

이 방식은 `0x08018058`이 실제로 읽는 pointer 자체를 바꾸므로 generic draw hook의 존재 여부와 무관하게 발동 전투대사에 직접 적용된다.

### 단계 D — 회귀 검증

최소 고정 실측 케이스:

1. 아무로 `アムロ……行きまーす！`
2. 키라 `うわぁぁぁ！！`
3. 가르마/공용 `ミノフスキー粒子散布！`
4. 하야토 `ボクにだってやれるんだ！`
5. 아스란 2-stream container
6. 무우 2-stream container
7. 샤아 2-stream container

정적 검증:

- 765 live table entries 유지
- 번역이 없는 container pointer는 원본 불변
- 번역이 있는 container pointer는 확장영역으로만 이동
- `+0x04` metadata는 768 physical slot 전부 원본 불변
- 원본 battle-bark payload 불변
- rebuilt container의 marker/tail 구조 byte exact
- original 16 MiB 예상외 변경 0
- 한국어 encode failed 0
- 기존 map-script hook 회귀 없음

## 6. 별도 문제로 분리할 영역

`近接`, `射撃`, `反応`, `操縦系`, `運動`, `装甲`, `限界`, `移動`, `汎用` 등 스테이터스 화면 라벨은 이번 전투-bark table과 별도다.

현재 화면/정적 근거상 이들은 일반 NUL text stream보다 **타일/고정 UI 그래픽 또는 별도 tilemap label** 가능성이 높다. 전투 발동 대사 복구 완료 후 그래픽 리소스 family로 따로 추적한다.

## 7. 현재 결론

일본어 잔존의 주원인은 번역문 자체의 누락이 아니라 **실제 전투 renderer가 소비하는 12×12 전용 256×3 battle-text family가 통합 추출 대상에서 빠진 것**이다.

따라서 구현은 `0x00226984` family 완전 추출 → 번역 seed → touched container 재구성 → 256×3 table +0 pointer 재배치 → 실측 회귀 테스트 순서로 진행한다. main TIP 승격은 해당 POC의 정적/실측 검증 후에만 수행한다.

## 8. 1차 구현 결과

### 8.1 구조 추출 완료

추가 도구:

- `tools/extract_ggen_advance_id_command_battle_barks.py`
- 산출물: `analysis/ggen_advance_id_command_battle_barks_20260829.json`

실제 runtime loop와 동일한 규칙으로 765 container를 전수 파싱한 결과:

| 항목 | 수치 |
|---|---:|
| live table entries | **765** |
| parser에 전달되는 NUL streams | **1,788** |
| 실제 비어 있지 않은 text streams | **1,023** |
| empty placeholder streams | **765** |
| container당 parser streams | 2개 507건 / 3개 258건 |
| continuation marker `0x03` | **1,023** |
| terminal marker `0x01` | **765** |
| 12×12 완전 해독 streams | **1,788** |
| partial streams | **0** |

모든 765 pointer는 unique/strict increasing이며 첫 container `0x002231B4`, 마지막 `0x00226978`, payload boundary `0x00226984`를 확인했다.

### 8.2 번역 seed overlay 구축

추가 도구/데이터:

- `tools/build_ggen_advance_id_command_bark_overlay.py`
- `integrated/translation/ggen_advance_id_command_battle_barks.json`

안전 seed 정책:

- 같은 character/command의 기존 8×16 A 문자열과 JP가 완전히 같은 경우만 재사용
- canonical merged source의 record/segment JP exact match가 한국어 하나로 결정되는 경우만 재사용
- 실측 스크린샷 확정 문장 수동 override
- `IDコマンドなし` / `IDコマンド無し`는 의미가 고정된 placeholder이므로 `ID 커맨드 없음`으로 통일
- partial/유사문장/문장분할은 자동 번역 금지

현재 1,023 text streams 중:

| 상태 | 수치 |
|---|---:|
| translated | **535** |
| pending | **488** |
| 기존 8×16 A exact 재사용 | 166 |
| canonical exact source/segment 재사용 | 29 |
| measured/manual | 340 = placeholder 333 + 실측 문장 7 |
| unresolved glyph pending | 9 |
| 그 외 safe exact 없음 | 479 |

pending 488은 고유 JP **431개**다. 초기에는 complete 479 + partial 9였으나, 아래 10개 battle-bark 문맥 슬롯을 추가 폐쇄해 현재는 **1,788 parser stream 전체가 complete**다.

### 8.3 runtime redirect 1차 적용 — 정적 PASS / 실측 실패

`tools/build_ggen_advance_unified_rom_poc.py`와 `tools/patch_ggen_advance_map_script_inline_poc.py`를 확장했다.

- battle-bark는 `id_command_battle_bark` 12×12 scope로 분류
- pending JP bark가 쓰는 glyph를 live-12×12 보호 집합에 포함
- translated bark는 32 MiB 확장영역에 12×12 한국어 stream으로 allocate
- 기존 map-script parser lookup에 원본 bark stream 주소 → 확장 한국어 주소 redirect 추가
- 원본 `0x002231B4..0x00226984` container payload는 쓰지 않음
- 원본 `0x00226984..0x00228184` 256×3 table/metadata도 쓰지 않음

1차 POC:

- 최신: `outputs/20260829_ggen_advance_unified_rom/ggen_advance_unified_translation_poc_20260838_idbark_charmap.gba`
- SHA-256: `e26bd9180f42505f8a39b780840746087bcfd5371ad7648f42c26fb544ec4d40`
- manifest: `analysis/ggen_advance_unified_rom_poc_20260838_idbark_charmap.json`
- apply charmap: `analysis/ggen_advance_korean_apply_charmap_20260838_idbark_charmap.json`

`20260838`은 bark 문맥 charmap 10개를 추가 폐쇄한 재빌드다. 현재 535 translated stream의 실제 한국어 payload는 바뀌지 않았기 때문에 `20260837`과 ROM SHA-256은 동일하다.

정적 빌드 결과:

- ID-bark runtime redirects: **535**
- 전체 runtime redirects: **2,885**
- map-script + runtime lookup entries: **24,981**
- ID-bark encode failed: **0**
- original-half unexpected changed bytes: **0**
- original bark payload unchanged: **PASS**
- original bark table/metadata unchanged: **PASS**
- 기존 map-script bank unchanged: **PASS**

### 8.4 1차 전용 회귀 verifier — lookup 존재만 검증해 실사용 경로를 놓침

추가 도구:

- `tools/verify_ggen_advance_id_command_bark_poc.py`

검증 PASS:

- translated bark 535건 모두 lookup redirect 존재
- destination은 전부 expanded half
- destination bytes가 현재 apply-charmap으로 재인코드한 한국어와 byte exact 일치
- pending 488건은 bark redirect 없음
- `IDコマンドなし` 330건 + `IDコマンド無し` 3건 모두 회귀 고정
- 아스란/키라/무우/샤아 실측 문장 각각 lookup/payload 검증
- original bark container/table/metadata byte exact 유지

### 8.5 battle-bark partial 9행 / 미확정 10슬롯 폐쇄

실제 bark 문맥만으로 의미가 고정되는 미확정 10슬롯을 correction overlay에 추가했다.

- `0x062B=蜂`, `0x071D=巣` → `蜂の巣になりたくなければな！`
- `0x07A0=突`, `0x07A1=貫` → `突貫（とっかん）します！`
- `0x07AB=吐` → `憎しみを育てる血を吐き出せ！`
- `0x026C=玉` → `目ん玉ひんむいて`
- `0x071F=贄` → `まだ生贄が足りないと`
- `0x067E=罰` → `天罰とはこのことか！`
- `0x06E9=吠` → `ギャンギャン吠えんなよ……`
- `0x05A4=肌` → `この肌触りこそ戦争よ！`

이 결과 extractor의 decode status가 **complete 1,788 / partial 0**이 됐다. 기존 forensic 12×12 charmap을 직접 덮어쓰지 않고 `analysis/ggen_advance_12x12_runtime_measurement_corrections_20260829.json`에 근거를 보존했다.

### 8.6 실측 피드백 후 table-pointer 방식으로 수정 (20260829)

`20260838` 실측 결과:

- `ID 커맨드 없음`: 한글 정상
- 키라 `うわぁぁぁ！！`: 일본어 잔존
- 무우 `ヒーローはガラじゃ / ねえってのに……！`: 일본어 잔존

이 결과로 8.3의 generic runtime redirect가 실제 battle renderer에 도달하지 않는 것이 확정됐다. `ID 커맨드 없음`은 별도 fallback UI 경로가 한글화된 것이었다.

수정한 빌더는 touched container를 통째로 확장영역에 재구성하고, `0x00226984` table의 각 entry `+0x00` pointer만 새 container로 바꾼다. `+0x04` metadata 및 원본 payload는 유지한다.

현재 통계:

| 항목 | 수치 |
|---|---:|
| translated text streams | **535** |
| pending text streams | **488** |
| pointer가 이동한 container | **521** |
| 완전 번역 container | **445** |
| 일부 번역 + 원문 보존 mixed container | **76** |
| 원본 pointer 유지 container | **244** |
| metadata 변경 | **0 / 768** |
| encode failed | **0** |

새 POC:

- `outputs/20260829_ggen_advance_unified_rom/ggen_advance_unified_translation_poc_20260839_idbark_tableptr.gba`
- SHA-256 `226abbfc68e06f8447156ea8adcedd2c49a53b3558923d928a10ae5a55c3da81`
- manifest `analysis/ggen_advance_unified_rom_poc_20260839_idbark_tableptr.json`
- apply charmap `analysis/ggen_advance_korean_apply_charmap_20260839_idbark_tableptr.json`

전용 verifier도 table consumer 기준으로 다시 작성했다. 각 765 entry에 대해 원본/후보 pointer와 metadata를 비교하고, 이동된 container는 확장영역의 실제 bytes를 stream별 한국어 재인코드 + 원문 pending + separator/tail 구조와 비교한다.

검증 결과 **PASS**:

- table pointer patches **521**
- fully translated containers **445**
- mixed containers **76**
- metadata unchanged **768/768**
- original bark payload unchanged
- generic runtime redirect dependency **없음**
- 키라/무우/아스란/샤아/ID 없음 실측 기준 phrase가 새 container 안에 존재함
- unified pipeline unit tests **6/6 PASS**

특히 후보 ROM에서 직접 확인한 pointer:

- 키라 `うわぁぁぁ！！`: table `0x00226EE4` → 새 container `0x0908CF8F`, 한국어 `우와아아앗!!`
- 무우 `ヒーローはガラじゃ…`: table `0x002279EC` → 새 container `0x0908E4FA`, `히어로는 겉모습이` + `아니라니까……!`

사용자 실측에서 `20260839`의 키라/무우 발동 대사가 실제 전투 화면에서 한글로 정상 출력되는 것을 확인했다. 따라서 table `+0x00` container-pointer 재배치 방식은 실사용 경로 기준으로 승인됐다.

### 8.7 잔여 488 stream 전량 번역 및 765 container 완전 한글화 (20260829)

실측 승인 후 남아 있던 **488 stream / 고유 JP 431문구**를 추가 번역했다. 별도 curated source를 두어 기존 exact seed와 분리했다.

- 수동 정본: `integrated/translation/ggen_advance_id_command_battle_bark_manual_ko_20260829.json`
- 통합 overlay: `integrated/translation/ggen_advance_id_command_battle_barks.json`
- 전체 text stream: **1,023 / 1,023 translated**
- pending: **0**
- curated manual 적용 stream: **501**
- measured/manual: **340**
- canonical exact: **29**
- parallel 8×16 A exact: **153**
- 모든 한국어 stream 표시 길이: **15셀 이하**, 최대 15

표시 폭을 넘기지 않도록 긴 번역은 의미를 유지하면서 전투 대사에 맞게 축약했다. 조니 라이덴의 `紅い稲妻`는 프로젝트 용어에 맞춰 `진홍의 번개`로 통일했다.

완전 한글화 POC:

- `outputs/20260829_ggen_advance_unified_rom/ggen_advance_unified_translation_poc_20260840_idbark_fullko.gba`
- SHA-256 `a6f90c38fbe7c3e1f5734ac10b80349ae2eeac53545cbfd2d2236bfdd574e5d1`
- manifest `analysis/ggen_advance_unified_rom_poc_20260840_idbark_fullko.json`
- apply charmap `analysis/ggen_advance_korean_apply_charmap_20260840_idbark_fullko.json`

빌드 결과:

| 항목 | 결과 |
|---|---:|
| battle-bark translated streams | **1,023 / 1,023** |
| pending | **0** |
| moved table pointers | **765 / 765 live entries** |
| fully translated containers | **765 / 765** |
| mixed containers | **0** |
| metadata changed | **0 / 768** |
| bark encode failed | **0** |
| original bark payload changed | **0** |
| unexpected original-half changes | **0** |

전용 verifier를 고정 수치가 아니라 현재 overlay/manifest에서 기대값을 계산하도록 수정했고, `20260840`에 대해 다음을 다시 확인했다.

- translated **1,023**, pending **0**
- table pointer patches **765**
- fully translated containers **765**, mixed **0**
- metadata byte exact **768/768**
- 원본 bark payload byte exact
- generic runtime redirect dependency 없음
- 기존 키라/무우/아스란/샤아/ID 없음 실측 회귀 문구 유지
- `tools/test_ggen_advance_unified_pipeline.py` **6/6 PASS**

이 POC를 승인 main TIP으로 승격 대상으로 사용했다.

### 8.8 main TIP 승격 완료

사용자 실측로 table-pointer 방식이 정상 동작함을 확인한 뒤 `20260840`을 `tools/promote_ggen_advance_main_tip.py`로 canonical main TIP에 승격했다.

- main: `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256: `a6f90c38fbe7c3e1f5734ac10b80349ae2eeac53545cbfd2d2236bfdd574e5d1`
- manifest: `integrated/main_tip/ggen_advance_main_tip_manifest.json`
- 이전 main 백업: `integrated/main_tip/backups/20260829T091227Z_full_id_command_battle_bark_ko_20260829/`

승격 후 main ROM 자체를 다시 전용 verifier에 넣어 **1,023 translated / pending 0 / table patches 765 / full containers 765 / metadata 768/768 unchanged**를 재확인했다.
