# G Generation Advance `持 -> 지` 전 소비처 follow-up — 2026-08-30

## 1. 작업 기준

현재 canonical main TIP을 처음부터 다시 확인하고 해당 ROM에서 조사/후보 생성을 진행했다.

- canonical: `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256: `f033b480bb36aabed3533bdea6dc0ff6da7884ea4ff1e9372cf662edb3295fd6`
- manifest promotion reason: `approved_action_menu_focusrounded_20260830`
- status resource table: `0x080E0518`
- active status atlas pointer: `0x09240000`
- active atlas file offset: `0x01240000`
- decoded atlas: `16,608 bytes = 519 tiles`

직전 후보 `ggen_advance_status_badges_ji_shield_man_candidate_20260830.gba` 실측에서는 `盾 -> 방패`, `万 -> 만`은 정상 승인되었으나 두 문제가 확인됐다.

1. resource[40]의 `持 -> 지` 오른쪽에 원본 일본어의 점 형태 잔여가 남음
2. `持`가 resource[40] 한 곳만의 그래픽이 아니며 유닛 정보/리스트/상세 계열의 다른 화면에도 반복됨

따라서 이번 follow-up은 단일 위치 보정이 아니라 status resource family 전체를 스캔해 `持` 소비처를 폐쇄한 뒤 후보 ROM으로 통합한다.

## 2. 전수 검색 결과

분석기:

- `tools/analyze_ggen_advance_hold_badge_consumers_20260830.py`
- `analysis/ggen_advance_hold_badge_consumers_20260830.json`

clean Japanese status atlas의 resource[14] 왼쪽 `持` face를 기준으로 6x11 palette-index-10 boolean pattern을 만들고, resource table 69개 전체에서 palette index `1..15`를 모두 검색했다.

정확히 일치한 resource는 다음 5개뿐이다.

| resource | file offset | 구조 | 역할 |
|---:|---:|---|---|
| 12 | `0x000DEAD8` | 1x2 | standalone / right-rounded `持` plaque |
| 14 | `0x000DEAE8` | 2x2 | `持` shared prefix + 상태 suffix |
| 40 | `0x000DFF9C` | 32x8 | lower-status panel 내부 embedded `持` |
| 62 | `0x000E04C0` | 2x2 | `持` shared prefix + alternate suffix A |
| 63 | `0x000E04CC` | 2x2 | `持` shared prefix + alternate suffix B |

다른 palette index에서 동일 face가 발견된 경우도 없다. 따라서 현재 `0x080E0518` status graphics family 안의 `持` 고정 그래픽 소비처는 위 5개 resource로 폐쇄된다.

### 2.1 공유 구조

resource[14]/[62]/[63]은 `持` 왼쪽 prefix tile을 공유한다.

- top: `0x09F`
- bottom: `0x0A0`
- owner resources: `[14, 62, 63]`

오른쪽 suffix는 서로 다르며 수정하지 않는다.

- resource[14] suffix: `0x09D / 0x09E`
- resource[62] suffix: `0x1EF / 0x1F0`
- resource[63] suffix: `0x1F1 / 0x1F2`

resource[12]의 `持`는 별도 private tiles `0x09B / 0x09C`이다.

resource[40]의 embedded `持`는 16x16 tile block `0x176/0x177/0x17D/0x17E` 안에 들어 있다.

## 3. 호출 경로

### 3.1 full unit/status information — `0x0806C548`

`0x0806C678..0x0806C71C`에서 unit flags를 조사한 뒤 resource index를 선택한다.

- `0x0C` = resource[12]
- `0x0E` = resource[14]
- `0x3E` = resource[62]
- `0x3F` = resource[63]

조건 accessor는 `0x08005538`, `0x08005D24`, `0x08005484` 계열이며 선택 후:

```text
resource_table[index]
 -> 0x0800277C
```

로 표시된다.

### 3.2 split/list/detail unit information — `0x0806C10C`

`0x0806C166..0x0806C1FC`에서도 같은 조건 family가 resource[12]/[14]/[62]/[63]을 선택하고:

```text
resource_table[index]
 -> 0x0800269C
```

로 그린다.

첨부 실측의 유닛 리스트/상세 화면에서 `持`가 계속 남은 것이 이 경로와 맞는다.

### 3.3 lower-status panel — `0x0806C934`

기존에 먼저 식별했던 경로다.

```text
0x0806C934
 -> resource_table[40] (+0xA0)
 -> 0x0800277C
```

resource[40] 안에 별도 embedded `持`가 존재한다.

## 4. 오른쪽 점 잔여 원인

직전 구현은 resource[40] 16x16 block에서 x=`3..10` 8px plaque만 원래 배경으로 복원한 뒤 `지`를 그렸다.

하지만 실제 일본어 `持` face의 셀 정렬은 x=`5..12`이다. 즉 일본어 원문이 replacement plaque보다 오른쪽으로 2px 더 걸쳐 있다.

정적 측정 결과:

- old replacement plaque: `x=3..10`
- Japanese source face cell: `x=5..12`
- geometric face/contour 중 old window 오른쪽에 남는 픽셀: `19`
- 실제 x=11/12에서 adjacent native panel fill과 다른 source pixel: **22 pixels**

이 22 pixels는 palette `4/5/9/A` 계열의 원문 face/outline/highlight 조각이다. 즉 직전 후보의 “오른쪽 점 3개”는 `지` 글꼴 자체 문제가 아니라 **일본어 source glyph tail을 x=11/12에서 지우지 않은 것**이다.

follow-up에서는 기존 `지`의 plaque 위치 x=3..10은 그대로 유지하고, x=11/12의 원문 tail 22 pixels만 같은 scanline의 x=13 native panel fill로 복원한다. 그 밖의 panel geometry는 byte/pixel exact 보존한다.

## 5. 구현

새 builder:

- `tools/build_ggen_advance_hold_badge_full_followup_20260830.py`

### resource[12]

- tiles: `0x09B / 0x09C`
- 원본 1x2 right-rounded badge 규격 유지
- background: 승인된 `left_single` native template을 수평 반전한 right-rounded template
- `지`: `Galmuri7.bdf`, native 6x7, 8x16 중앙
- face index `10`, contour index `4`

### resource[14]/[62]/[63]

- shared tiles: `0x09F / 0x0A0`
- connected native background만 재구성
- `지`: Galmuri7 native 6x7
- 오른쪽 suffix tiles는 전부 byte exact 보존

공유 prefix 한 번만 수정하므로 세 resource의 모든 상태 조합에 동시에 적용된다.

### resource[40]

- 기존 `지` plaque placement `x=3..10` 유지
- `left_single` background + Galmuri7 `지`
- source Japanese tail `x=11/12` 22 pixels 추가 clear
- 주변 panel은 그대로 보존

### `방패`, `만`

사용자 실측에서 자연스럽다고 승인된 직전 구현을 그대로 carry-forward 한다.

- `盾 -> 방패`: resource[47], private central tiles만 변경, shared `0x172` 보존
- `万 -> 만`: resource[52], 기존 `間 -> 간`과 같은 green badge 스타일

## 6. 후보 ROM

- candidate: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_full_followup_candidate_20260830.gba`
- SHA-256: `de69dbc5f20a83784a1edc39760e3a4a5cb73210b584964fcb0c2070b6ca0ad1`
- manifest: `analysis/ggen_advance_status_badges_hold_full_followup_20260830.json`
- preview: `outputs/20260830_ggen_advance_status_badges/ggen_advance_status_badges_hold_full_followup_preview_20260830.png`

변경 atlas tile은 16개다.

```text
09B 09C 09F 0A0
176 177 17D 17E
1D8 1D9 1DC 1DD
1E3 1E4 1E5 1E6
```

ROM byte diff는 현재 main TIP 대비 `326 bytes`이며 모두 active status atlas allocation 내부다.

## 7. 정적 검증

PASS 항목:

- 69개 status resource 전수 `持` face scan
- exact source resources = `[12, 14, 40, 62, 63]`
- alternate palette exact copy = 0
- resource[14]/[62]/[63] suffix byte exact 보존
- resource[64]/[65] scan 결과 `持` 아님 + byte exact 보존
- `盾` shared tile `0x172` 보존
- 기존 resource[53] `간` 보존
- palette 변경 0
- tilemap/resource 구조 변경 0
- status resource pointer 변경 0
- decoded atlas `16,608 bytes` 유지
- literal-only compression footprint 유지 + round-trip PASS
- original 16 MiB byte exact
- regression tests `10/10 PASS`

## 8. 실측 체크포인트

1. 첫 번째 lower-status 화면에서 `지` 오른쪽의 점 3개/일본어 tail이 완전히 사라졌는지 확인한다.
2. full unit information 화면에서 기존 `持`가 모든 상태 변형에서 `지`로 표시되는지 확인한다.
3. 첨부한 split/list/detail unit 화면에서도 모든 `持`가 `지`로 표시되는지 확인한다.
4. 상태를 바꿔 resource[14]/[62]/[63]의 오른쪽 suffix가 달라질 때, `지`만 공통 유지되고 suffix가 깨지지 않는지 확인한다.
5. 이미 승인된 `방패`, `만`이 직전 후보와 동일하게 자연스러운지 확인한다.
6. 기존 `간`, resource64/65, 다른 status badge에 회귀가 없는지 확인한다.

현재 후보는 **실측 대기이며 main TIP에는 승격하지 않았다.**
