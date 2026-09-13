# GGeneration Advance status badge follow-up — 持 / 盾 / 万 (2026-08-30)

## 기준

- canonical main TIP: `SD Gundam GGeneration Advance (Korean).gba`
- main TIP SHA-256: `f033b480bb36aabed3533bdea6dc0ff6da7884ea4ff1e9372cf662edb3295fd6`
- main TIP manifest promotion reason: `approved_action_menu_focusrounded_20260830`
- clean Japanese ROM SHA-256: `75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772`
- active status atlas pointer: `0x09240000` (`file 0x01240000`)
- active decoded atlas: 16,608 bytes / 519 tiles

이번 후속은 현재 main TIP 안에 이미 적재되어 있는 승인 status atlas를 직접 기준으로 잡는다. 과거 status PoC를 다시 합성하지 않고, 요청된 세 그래픽의 측정된 tile payload만 변경한다.

## 1. `持 -> 지`

첨부 화면의 `持`는 별도 1x2 resource가 아니라 **resource[40] lower-status panel 내부에 박힌 8x16 plaque**로 확인했다.

- resource[40] file offset: `0x000DFF9C`
- lower-status renderer: `0x0806C934`
- 경로: `0x0806C934 -> resource_table[40] (+0xA0) -> 0x0800277C`
- panel 배치: tile-row `y=12`
- plaque 좌표: resource[40] local pixel `x=139..146`, `y=0..15`
- 관련 tiles: `0x176`, `0x177`, `0x17D`, `0x17E`
- 네 tile은 resource[40] 전용으로 확인했다.

원본 plaque의 8x16 frame은 기존 weapon mini-badge의 `left_single` native green 배경과 정렬되는 구조다. 일본어 glyph/shadow를 남기지 않도록 해당 8x16 window 전체를 native green template로 먼저 복원한 뒤 `Galmuri7.bdf`의 `지`를 native 크기로 배치했다.

- 글리프 BBX: 6x7
- 8x16 plaque 안에 중앙 배치
- face palette index: `10`
- contour palette index: `4`
- plaque 바깥의 인접 픽셀은 그대로 보존
- 별도 normal/focus resource 없음

## 2. `盾 -> 방패`

`盾`는 resource[47]이다. ROM 자체 12x12 Japanese glyph와 shape 비교 시 `盾`가 **score 1.0**으로 일치했고, runtime에서도 unit-type selector의 7번째 항목으로 닫힌다.

- resource[47] file offset: `0x000E0218`
- tiles:
  - top: `0x172 0x1D8 0x1D9 0x1DA`
  - bottom: `0x1DB 0x1DC 0x1DD 0x1DE`
- runtime: `0x0806C620 -> 0x08005518 -> resource_table[40 + unit_type]`
- `unit_type=7 -> resource[47]`
- blitter: `0x0800277C`

주의점은 첫 tile `0x172`가 resource[40]과 공유된다는 점이다. 따라서 resource[47] 전체를 재드로잉하지 않고 **중앙 16px만** 지운 뒤 `방패`를 그렸다.

- 변경 private tiles: `0x1D8`, `0x1D9`, `0x1DC`, `0x1DD`
- 공유 tile `0x172`: byte-exact 보존
- 좌우 rounded frame: byte-exact 보존
- font: `Galmuri11-Condensed.bdf`
- renderer: native 8x16 condensed cell x 2
- face palette index: `10`
- full contour palette index: `5`
- 별도 normal/focus resource 없음

## 3. `万 -> 만`

무장 row 오른쪽의 `万`은 resource[52]이고, 기존 `間 -> 간`은 바로 다음 resource[53]이다.

- resource[52] file offset: `0x000E024C`
- tiles: `0x1E3`, `0x1E4`, `0x1E5`, `0x1E6`
- resource[53] file offset: `0x000E0258`
- existing `간` tiles: `0x1E7..0x1EA`
- weapon-row renderer: `0x0806CA68`
- selector: `0x0806CCA8..0x0806CCE4`
- 이 구간에서 resource[52]/[53]를 선택하고 `0x0800277C`로 출력한다.

resource[52]의 Japanese glyph shape도 `万`과 강하게 일치하고, 첨부 실측에서 resource[53]의 `간`과 같은 위치의 alternate가 `万`으로 확인되므로 의미와 호출 경로가 모두 닫힌다.

`만`은 승인된 `간`과 같은 방식으로 처리했다.

- native green 16x16 background template 재사용
- `Galmuri7.bdf` 7x7 `만` 중앙 배치
- face palette index: `15`
- contour palette index: `4`
- resource[53] `간`은 byte-exact 보존
- 별도 normal/focus resource 없음

## 안전성 / 변경 범위

builder: `tools/build_ggen_advance_status_badge_followup_20260830.py`

변경된 decoded atlas tile은 정확히 12개다.

`0x176, 0x177, 0x17D, 0x17E, 0x1D8, 0x1D9, 0x1DC, 0x1DD, 0x1E3, 0x1E4, 0x1E5, 0x1E6`

검증 결과:

- current main TIP SHA gate: PASS
- 세 source tile 묶음이 clean JP와 동일함: PASS
- original 16 MiB: byte-exact unchanged
- palette: unchanged
- tilemaps: unchanged
- resource pointer: unchanged (`0x09240000`)
- decoded atlas size: 16,608 bytes 유지
- compressed resource footprint: 유지
- compression round-trip: PASS
- shared `0x172`: unchanged
- 기존 resource[53] `간`: unchanged
- unified/font/development regression: 10/10 PASS

## 후보 ROM

- candidate: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_ji_shield_man_candidate_20260830.gba`
- SHA-256: `2850abab33431007ceb01f0de09e16a781f786dc93dc01fe9c39eb5eded68a06`
- manifest: `analysis/ggen_advance_status_badges_ji_shield_man_20260830.json`
- preview: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_ji_shield_man_preview_20260830.png`
- ROM-level changed bytes vs current main TIP: 222 bytes
- main TIP: **미승격 / 실측 대기**

## 실측 확인 포인트

1. 첫 번째 UI lower-status panel에서 기존 `持` 위치가 `지`로 보이는지 확인한다. 원본 일본어 획/그림자가 남지 않아야 하며, 오른쪽 pale panel 경계가 깨지지 않아야 한다.
2. `盾`가 나오던 unit-type/effect badge에서 `방패` 두 글자가 Galmuri11 Condensed 계열로 정상 출력되는지 확인한다. 특히 좌측 rounded edge가 찌그러지지 않아야 한다.
3. 무장 row 오른쪽에서 기존 `万`이 나오던 행이 `만`으로 바뀌는지 확인한다. 바로 아래/다른 행의 기존 `간`과 크기, green background, contour tone을 비교한다.
4. 여러 unit/weapon row를 전환해 기존 `간`, `사/근/단/전`, `남은횟수`, lower-status panel frame이 그대로인지 확인한다.
5. 세 대상 모두 독립 focus overlay를 사용하지 않으므로 cursor/focus 이동 시 별도의 일본어 focus 잔상이 생기지 않아야 한다. 만약 상태 전환에서만 원문이 재등장한다면 atlas 외 별도 OBJ/runtime overlay 소비처를 추가 추적한다.
