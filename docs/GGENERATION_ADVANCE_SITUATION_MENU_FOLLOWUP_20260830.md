# G Generation Advance 상황 메뉴 후속 수정 (2026-08-30)

## 대상

- 기준 메인 TIP: `SD Gundam GGeneration Advance (Korean).gba`
- 기준 SHA-256: `973f4a6fd94b27a08835ee309624a5dd87a43b03ce0bcbca453e9e3291c1ffe1`
- 이전 후보: `outputs/20260830_ggen_advance_situation_menu/ggen_advance_situation_menu_ko_candidate_20260830.gba`
- 후속 후보: `outputs/20260830_ggen_advance_situation_menu/ggen_advance_situation_menu_ko_followup_candidate_20260830.gba`
- 후속 후보 SHA-256: `9fb0b509202951c0fc98a702195052d183d5ea82635739cc9d91fd4b5cdb5d3b`
- 정적 검증 매니페스트: `analysis/ggen_advance_situation_menu_ko_followup_20260830.json`
- 라벨 비교 프리뷰: `outputs/20260830_ggen_advance_situation_menu/ggen_advance_situation_menu_fixed_labels_followup_preview_20260830.png`

## 1. 아군/적군 라벨 배경 문제

이전 구현은 고정 라벨의 일본어 글자 영역을 지울 때 `CLEAR_ZONES` 전체를 좌/우 경계색으로 다시 채웠다. `自軍`, `敵軍`, `友軍` 영역의 경계 샘플이 팔레트 index 2였기 때문에, 실제 원본에 존재하던 내부 하이라이트/그라데이션까지 index 2로 평탄화되어 인게임에서 짙은 갈색 직사각형처럼 보였다.

후속 구현은 `自軍` / `敵軍` / `友軍`의 원본 12x12 글리프를 일본판 폰트에서 복원하여 실제 고정 그래픽과 정렬한 뒤, **원본 글리프 + 1px contour footprint만** 제거한다. 나머지 원본 배경/하이라이트 픽셀은 그대로 둔다. 한글은 그 위에 face index `0xB`, contour index `0x4`로 다시 렌더하며 contour는 한글 글리프 주변 1px로 제한한다.

정적 정렬 결과:

| 역할 | 원본 글리프 origin | 원본 글리프 매치율 | 원본 footprint 밖 변경 |
| --- | --- | ---: | ---: |
| 아군 (`自軍`) | `(6, 3)` | 1.000000 | 0 px |
| 적군 (`敵軍`) | `(6, 3)` | 1.000000 | 0 px |
| 우군 (`友軍`) | `(7, 3)` | 1.000000 | 0 px |

`턴 수`, `함`은 기존 후보에서 실측 정상인 경로를 유지했다.

## 2. 하단 12x12 조건 텍스트 원인

### 2.1 `:` -> `값`

검증된 일본판 12x12 charmap에서 `:`는 전각 `：`와 대응하는 slot `0x00E3` / token `0xE003`으로 해석된다. 그러나 현재 승인된 메인 TIP의 active 12x12 폰트에서는 같은 slot `0x00E3`이 이미 한글 `값` 글리프로 페인트되어 있었다. 따라서 payload가 `0xE003`을 올바르게 내보내더라도 실제 화면에서는 `값`이 그려졌다.

기존 `compatibility_slots()`가 전각 `：`를 ASCII `:`의 punctuation alias로 보호하지 못한 것이 재발 원인이었다. `tools/build_ggen_advance_unified_rom_poc.py`에도 ASCII/전각 alias를 함께 보호하도록 수정했다.

현재 메인 TIP 자체의 `값` 소비자를 깨뜨리지 않기 위해 `0x00E3`을 원복하지 않았다. 대신 남은 일본어 12x12 live slot, 이미 페인트된 한글 slot, 예약/특수/compatibility slot을 모두 제외한 467개 안전 후보 중 사용되지 않는 원본 CJK slot `0x0785`를 골라 일본판 `：` 글리프를 복사했다.

- 조건용 `:`: slot `0x0785`, token `0xE6A5`
- 폰트 수정 위치: file offset `0x0100875A`
- active 12x12 폰트에서 이 override slot 이외의 변경은 없음
- 실제 변경 바이트: 17 bytes

### 2.2 `멸` -> `릭`, `라` -> `땐`

이전 상황 메뉴 builder는 현재 분석 데이터로 `build_apply_charmap()`을 다시 실행하여 슬롯을 재계산했다. 하지만 승인된 메인 TIP은 과거 allocator 결과로 이미 폰트가 페인트되어 있으므로, 현재 재계산 결과와 실제 active 폰트가 달라질 수 있다.

Stage 1 이전 후보의 실제 토큰/슬롯은 다음과 같았다.

- `멸`을 token `0xE07A` / slot `0x015A`로 인코딩했으나, 승인 메인 TIP의 slot `0x015A` 실제 글리프는 `릭`
- `라`를 token `0xE069` / slot `0x0149`로 인코딩했으나, 승인 메인 TIP의 slot `0x0149` 실제 글리프는 `땐`

후속 builder는 allocator를 재실행하지 않고 **승인 메인 TIP의 active 12x12 폰트를 Galmuri11 원본 raster와 exact match하여 실제 슬롯을 역복구**한다. 조건문에서 사용하는 72개 한글 글리프가 모두 유일하게 복구되었다.

요청된 anchor 최종값:

| 문자 | slot | token | painted glyph 검증 |
| --- | ---: | ---: | --- |
| `:` | `0x0785` | `0xE6A5` | 일본판 `：` raster exact match |
| `전` | `0x07AD` | `0xE6CD` | Galmuri11 exact match |
| `멸` | `0x015E` | `0xE07E` | Galmuri11 exact match |
| `키` | `0x0703` | `0xE623` | Galmuri11 exact match |
| `라` | `0x014C` | `0xE06C` | Galmuri11 exact match |

Stage 1 후속 후보의 실제 슬롯열도 `:`=`0x0785`, `멸`=`0x015E`, `라`=`0x014C`로 확인했다.

## 3. 승패 조건 56 pair 전수 재검증

상황 메뉴 selector `0x08012408`가 소비할 수 있는 56개 unique pair 전체를 다시 생성했다.

- fallback unique pair: 38
- flag override unique pair: 18
- fallback pointer field: 64개 전부 redirect
- override literal: 18개 전부 redirect
- 총 56 pair 모두 새 payload의 token -> slot 확장 -> **active font slot 의미 기준 runtime decode**를 다시 수행
- 56 / 56 pair가 목표 한글 victory/defeat 문자열과 완전 일치
- 모든 문장은 기존 화면 제한인 19 cells 이하 유지
- 요청 anchor `:`, `전`, `멸`, `키`, `라`는 token / slot / painted glyph 3단계 모두 PASS

## 4. 정적 검증 결과

`analysis/ggen_advance_situation_menu_ko_followup_20260830.json` 기준 PASS:

- 5개 고정 라벨 rebuild
- atlas 202 tiles
- `MS` 변경 없음
- extra overlay map 변경 없음
- 아군/적군/우군 원본 배경: source/Korean glyph 영역 밖 변경 0 px
- contour: 한글 glyph 주변 1px 제한
- 56 pair 전부 runtime slot decode PASS
- 64 fallback + 18 override pointer redirect PASS
- 상황 메뉴 Thumb code 변경 없음
- 기존 한글 글리프 변경 없음
- active 12x12 font 수정은 조건용 colon override slot 하나에만 한정
- 전체 변경은 선언된 상황 메뉴/조건/colon override 범위 안에 한정

## 5. 인게임 실측 포인트

1. 동일 상황 메뉴를 열어 `아군`, `적군` 라벨 내부에 이전 후보처럼 평탄한 짙은 갈색 사각형이 생기지 않는지 확인한다. 원본의 붉은 라벨 하이라이트/밴딩/프레임이 글자 주변에도 이어져야 한다.
2. `턴 수`, `함`은 이전 후보와 동일한 정상 표시인지 확인한다.
3. Stage 1 조건이 정확히 `승리조건:적군 전멸` / `패배조건:키라 격파`로 표시되는지 확인한다. 특히 `:`가 `값`으로, `멸`이 `릭`으로, `라`가 `땐`으로 보이지 않아야 한다.
4. 조건이 바뀌는 다른 스테이지의 fallback pair를 최소 1개, flag에 따라 바뀌는 override pair를 최소 1개 추가 확인한다. 정적 검증은 56개 전부 완료되어 있으므로 이 실측은 selector/runtime 화면 경로 확인용이다.
5. 제3군이 있는 상황에서는 `우군` 라벨도 같은 배경 보존 방식이 적용됐으므로 함께 확인한다.

실측 이상이 없으면 이 follow-up 후보를 메인 TIP 승격 대상으로 사용할 수 있다.
