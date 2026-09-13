# G Generation Advance 스테이터스 고정 한자 UI 타일 분석 — 2026-08-29

## 1. 조사 대상

실측 스크린샷에서 일반 대사/설명과 달리 일본어로 남은 다음 고정 라벨을 조사했다.

- 파일럿 능력치: `近接`, `射撃`, `反応`, `操縦系`
- 유닛 능력치: `運動`, `装甲`, `限界`, `移動`
- 유닛 타입 배지: `汎用`

목표는 이 문자열들이 왜 기존 통합 번역/포인터 재배치의 영향을 받지 않는지 확인하고, 안전한 한글화 경로를 고정하는 것이다.

분석 자동화:

- `tools/analyze_ggen_advance_status_ui_tiles.py`
- `analysis/ggen_advance_status_ui_tile_analysis_20260829.json`

## 2. 결론

이 9개 라벨은 **일반 NUL 텍스트가 아니다.**

`integrated/translation/ggen_advance_translation_merged.json`에서 9개 라벨을 standalone `source_text`로 전수 검색한 결과는 모두 0건이다. `近接`, `射撃`, `反応`, `運動`, `装甲`, `限界`, `移動`은 설명/대사 안에 포함된 일반 문자열로는 존재하지만, 스테이터스 화면의 고정 라벨 자체는 별도 텍스트 레코드로 존재하지 않는다. `操縦系`, `汎用`은 standalone 레코드도 없다.

실제 화면은 ROM `0x000E0518`의 UI 리소스 포인터 테이블에서 **BG tilemap 구조체**를 골라 `0x0800277C`로 화면 tilemap VRAM에 복사한다. 따라서 기존 8×16/12×12 문자열 relocation이나 pointer owner 패치만으로는 이 라벨이 바뀌지 않는다.

## 3. 리소스 테이블과 tilemap 구조

공용 리소스 포인터 테이블:

- file: `0x000E0518`
- GBA: `0x080E0518`

각 tilemap 구조는 다음 형식이다.

```text
+0x00 u8 width
+0x01 u8 height
+0x02 u16 reserved
+0x04 u16 cells[width * height]
```

cell의 하위 10비트가 BG tile ID이며 상위 비트는 flip/palette 속성이다.

주요 blitter:

- `0x0800277C`
- 내부에서 cell tile ID와 palette/offset을 조합한 뒤 `0x0800199C`로 BG map에 기록한다.

## 4. 파일럿 스테이터스 고정 라벨

파일럿 화면 경로:

```text
0x0806D350 wrapper
 -> 0x0806BEB8 setup
 -> 0x0806CFC4 renderer
 -> resource table 0x080E0518
```

기본 tilemap:

- table index: `2`
- pointer: `0x080DE548`
- file: `0x000DE548`
- 크기: `32 × 20` tiles = `256 × 160 px`
- 구조체 크기: `1284 bytes`

BG1 설정은 `0x4E05`이며 charblock 1을 사용한다.

- BG1 charblock VRAM base: `0x06004000`

실측 스크린샷과 tilemap 좌표가 정확히 대응한다.

| 라벨 | 한글 목표 | map 좌표 | 크기 | tile IDs |
|---|---|---:|---:|---|
| `近接` | `근접` | `(14,7)` | `4×2` | `044 045 046 047 / 04D 04E 04F 050` |
| `操縦系` | `조종계` | `(20,7)` | `5×2` | `048..04C / 051..055` |
| `射撃` | `사격` | `(14,9)` | `4×2` | `058 059 05A 05B / 062 063 064 065` |
| `EXP` | 유지 | `(20,9)` | `4×2` | `05C..05F / 066..069` |
| `反応` | `반응` | `(14,11)` | `4×2` | `06A..06D / 072..075` |
| `NEXT` | 유지 | `(20,11)` | `4×2` | `06E..071 / 076..079` |

예를 들어 `近接` 첫 행의 map cell 자체는 다음 주소에 있다.

- `0x000DE728`
- `0x000DE72A`
- `0x000DE72C`
- `0x000DE72E`

두 번째 행은 `0x000DE768..0x000DE76E`이다.

이 tile ID들의 실제 BG1 VRAM 위치도 확정 가능하다. 예를 들어 tile `0x044`는:

```text
0x06004000 + 0x044 * 32 = 0x06004880
```

파일럿 고정 라벨에 쓰이는 `0x044..0x079` 계열은 현재 조사한 status resource table 안에서 각 위치가 사실상 독립적으로 사용된다. 따라서 이 영역은 runtime tile override의 좋은 후보이다.

## 5. 유닛 스테이터스 고정 라벨

유닛 화면의 핵심 renderer:

- `0x0806C548`
- 상위 status wrapper: `0x0806B840`
- `0x0806B890`에서 `0x0806C548` 호출 확인

기본 tilemap:

- resource table index: `35`
- pointer: `0x080DF588`
- file: `0x000DF588`
- 크기: `32 × 20` tiles

renderer `0x0806C5EA..0x0806C608`에서:

```text
r5 = 0x06007000
resource = [0x080E0518 + 0x8C]   ; index 35
0x0800277C(...)
```

로 이 map을 직접 사용한다.

유닛 화면 BG1 설정은 `0x4E01`이며 charblock 0이다.

- BG1 charblock VRAM base: `0x06000000`

고정 라벨 위치:

| 라벨 | 한글 목표 | map 좌표 | 크기 | tile IDs |
|---|---|---:|---:|---|
| `運動` | `운동` | `(13,7)` | `4×2` | `146 147 148 149 / 14E 14F 150 151` |
| `装甲` | `장갑` | `(19,7)` | `4×2` | `14A 14B 14C 14D / 152 153 154 155` |
| `限界` | `한계` | `(13,9)` | `4×2` | `156 157 158 159 / 15D 15E 15F 160` |
| `移動` | `이동` | `(19,9)` | `4×2` | `15A 15B 15C 149 / 161 162 150 151` |

여기서 중요한 구조가 하나 확인된다.

`移動`는 `運動`의 tile `0x149`, `0x150`, `0x151`을 재사용한다. 즉 이것은 문자열 데이터가 아니라 **화면용 글자/조각 타일을 실제로 공유하는 그래픽 atlas 구조**다.

따라서 일본어 tile ID 하나를 의미 단위로 무작정 한글 타일로 바꾸는 방식은 위험하다. `運動`과 `移動`이 같은 일본어 `動` 그래픽 일부를 공유하기 때문이다.

## 6. `汎用` 동적 타입 배지

`汎用`은 unit base map에 고정되어 있지 않고 유닛 타입에 따라 별도 4×2 chunk를 추가로 그린다.

유닛 레코드 accessor:

- unit record resolver: `0x080045B0`
- unit type accessor: `0x08005518`
- 실제 읽는 필드: unit record `+0x19`

renderer `0x0806C620..0x0806C640`의 선택식은 다음과 같다.

```text
unit_type = accessor_0x08005518(unit_id)
chunk = resource_table[40 + unit_type]
blit(chunk, logical_x=58, y=9)
```

BG map의 가로 wrap 때문에 logical x=58은 실제 화면 x=26 tile, 즉 `208 px` 위치가 된다. 이는 실측 스크린샷의 우측 타입 배지 위치와 맞는다.

건탱크를 역추적하면 세 변형 모두:

- unit record `+0x19 = 1`
- 따라서 `resource_table[41]`
- pointer `0x080E01A0`
- file `0x000E01A0`
- size `4×2`
- tile IDs:
  - top: `1A8 1A9 1AA 1AB`
  - bottom: `1AC 1AD 1AE 1AF`

이 4×2 chunk가 실측 화면의 `汎用` 배지임을 구조적으로 확정할 수 있다.

한글 목표는 `범용`이다.

unit BG1 charblock 0 기준 해당 VRAM 범위는:

- `0x06003500 .. 0x060035FF`

이다.

## 7. 왜 기존 한글화에서 남았는가

이 영역은 지금까지의 일반 텍스트 번역 경로와 완전히 다르다.

기존 일반 텍스트:

```text
ROM text stream
 -> pointer / runtime consumer
 -> 8×16 or 12×12 glyph renderer
```

이번 스테이터스 라벨:

```text
ROM status resource table
 -> fixed 32×20 tilemap / 4×2 chunk
 -> tile ID
 -> BG charblock의 이미 준비된 graphic tile
```

따라서:

- 번역 JSON에 문자열을 추가하는 것만으로 해결되지 않음
- text pointer relocation과 무관
- 8×16/12×12 source string census에서도 standalone 레코드가 안 나오는 것이 정상
- `EXP`, `NEXT`도 일반 ASCII 문자열 레코드가 아니라 같은 fixed tilemap 일부임

## 8. 구현 방향

### 권장: status 진입 시 해당 VRAM tile만 한국어로 override

현재는 다음 정보가 모두 확보됐다.

- 어느 renderer가 화면을 구성하는지
- 어느 map cell이 어떤 라벨인지
- tile ID가 무엇인지
- pilot/unit 각각 BG1 charblock가 어디인지
- `汎用`이 어떤 동적 chunk인지

따라서 공용 일본어 UI atlas 원본 전체를 수정하기보다 **status 화면이 만들어진 뒤 필요한 tile slot만 한국어 raster로 덮어쓰는 방식**이 가장 국소적이다.

예상 방식:

1. 확장 ROM에 한국어 라벨 4bpp tile payload 저장
2. pilot status 진입 시 charblock1의 대상 tile slot에 copy
3. unit status 진입 시 charblock0의 대상 tile slot에 copy
4. map 구조와 수치/레이아웃/팔레트는 그대로 유지
5. `EXP`, `NEXT`는 건드리지 않음
6. `汎用`은 type=1의 `1A8..1AF`에 `범용` raster 적용

파일럿 라벨 tile들은 status resource 범위에서 독립성이 높아 직접 override하기 쉽다.

유닛 라벨은 `運動`/`移動`의 `149/150/151` 공유가 있으므로 두 방법 중 하나가 필요하다.

- `운동`/`이동`에서 공통 `동` 부분을 동일한 tile 조합으로 설계
- 또는 `移動`의 공유 cell 3개를 새 전용 tile ID로 remap

두 번째가 더 명시적이고 향후 수정도 쉽다.

### 대안: map을 blank 처리하고 일반 한글 text renderer overlay

가능하지만 기존 status renderer에 추가 draw call이 필요하고, 현재 고정 라벨의 색/배경/정렬을 맞추려면 별도 스타일 조정이 필요하다. 따라서 첫 POC는 전용 4bpp tile override가 더 안전하다.

## 9. 고정 규격 한글 타일 오버레이 POC 구현

사용자 요청에 따라 원본 UI 자산의 규격과 팔레트를 바꾸지 않고, 일본어 라벨이 있던 사각형만 원래 배경색으로 지운 뒤 한글을 다시 그리는 방식으로 테스트 ROM을 구현했다.

구현 도구:

- `tools/build_ggen_advance_status_ui_tile_overlay_poc.py`

테스트 ROM:

- `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_poc_20260829.gba`
- SHA-256: `ff4e06c6f674a817d7eeb1b1c640991f3e243d2c1e29260969843e833c6600e0`

검증 자료:

- `analysis/ggen_advance_status_ui_tile_overlay_poc_20260829.json`
- `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_preview_20260829.png`

구현 규칙:

1. 원본 `0x000DC848` UI atlas를 게임과 동일한 custom LZSS 규칙으로 해제한다.
2. 해제 전/후 타일 자산 규격을 유지하며 decoded atlas 크기는 **16,608 bytes**로 고정한다.
3. 타일 포맷은 원본과 동일한 **GBA 4bpp 8×8**을 유지한다.
4. 팔레트 데이터는 전혀 수정하지 않는다. 원본 UI atlas에서 이미 사용하는 색 인덱스만 재사용한다.
   - 배경: palette index `5`
   - 한글 전경: palette index `10`
   - 한글 그림자: palette index `11`
5. 각 일본어 라벨의 측정된 4×2 또는 5×2 tile rectangle 내부만 background index 5로 채운다.
6. 같은 rectangle 안에 `Galmuri11.bdf` native 12×12 bitmap으로 한글을 중앙 정렬해 그린다. rectangle 밖 픽셀은 수정하지 않는다.
7. `移動`은 원본에서 `運動`과 tile `149/150/151`을 공유하므로 직접 덮어쓰지 않는다. 전체 status resource tilemap에서 미사용이 확인된 `0x1F3-0x1FA` 8개 tile을 이동 전용으로 사용하고, 기존 32×20 unit tilemap의 해당 8 cell 값만 remap한다.
8. 수정 atlas는 32 MiB ROM의 graphics append 영역 `0x01240000`에 저장하고 `resource_table[0]`만 `0x09240000`으로 redirect한다. 화면/타일맵 규격은 변경하지 않는다.
9. custom LZSS는 literal-only stream으로 다시 생성했으며 게임 decoder와 동일한 해제 루틴으로 round-trip byte exact 검증했다.
10. 원본 half의 허용 변경은 resource pointer 4 bytes와 `移動` remap 8 tile cells뿐이다. 이 외 unexpected changed byte는 **0**으로 검증했다.

적용 라벨:

- `近接 → 근접`
- `射撃 → 사격`
- `反応 → 반응`
- `操縦系 → 조종계`
- `運動 → 운동`
- `装甲 → 장갑`
- `限界 → 한계`
- `移動 → 이동`
- `汎用 → 범용`

빌드 결과는 `PASS`이며 `palette_modified=false`, decoded atlas `16,608 → 16,608`, compression round-trip `true`이다.

### 9.1 v1 실측 문제와 투명 배경 v2 수정

v1 실측 화면에서는 한글 라벨의 4×2/5×2 rectangle 전체가 어두운 색으로 덮였다. 원인은 `render_label()`이 모든 픽셀을 palette index `5`로 초기화했기 때문이다. 이 방식은 일본어 제거에는 성공했지만 underlying status panel까지 가려 원본과 다른 큰 불투명 박스를 만들었다.

v2는 다음 규칙으로 다시 생성했다.

- 라벨 tile의 기본 픽셀: palette index `0` = BG 투명
- 한글 전경: 기존 palette index `10`
- 한글 +1,+1 drop shadow: v1 전체 박스에 쓰던 어두운 palette index `5`
- glyph/shadow 이외 픽셀은 모두 `0`으로 남김
- 별도 배경 사각형을 그리지 않음
- palette 데이터, atlas 크기, 8×8 4bpp 규격, tilemap 크기는 변경하지 않음

따라서 어두운 색은 한글 그림자 픽셀에만 남고 나머지는 BG 아래의 원래 status panel이 비친다.

v2 산출물:

- `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_transparent_v2_20260829.gba`
- SHA-256 `1d19da3f7b03ff7bc70d70a0476aad281cfdcfb0e238fa966b9d8be28f314f9f`
- manifest `analysis/ggen_advance_status_ui_tile_overlay_transparent_v2_20260829.json`
- preview `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_transparent_v2_preview_20260829.png`

정적 gate는 모든 라벨에서 투명 픽셀이 실제 존재하는지와 사용 pixel index가 `{0,5,10}`만인지 검사한다. decoded atlas는 여전히 **16,608 bytes**, palette 수정은 **0**, 원본 half unexpected change는 **0**이다.

## 10. 실측 확인 항목

메인 TIP은 아직 변경하지 않았다. 위 POC에서 다음을 실측한다.

1. 파일럿 화면: `근접 / 사격 / 반응 / 조종계`
2. 유닛 화면: `운동 / 장갑 / 한계 / 이동`
3. 건탱크 등 범용 타입: `범용`
4. `EXP / NEXT`, 수치, portrait, unit graphic, 창 테두리, 배경색이 기존과 동일한지 확인
5. 일본어 잔여 픽셀이나 한글이 rectangle 밖으로 넘치는 현상이 없는지 확인

실측 승인 후 같은 방식으로 main TIP 승격을 진행한다.

## 11. v2 분홍 배경 실측 원인과 native-background/full-outline v3

`transparent_v2` 실측에서 라벨 사각형이 분홍색으로 보였다. 원인을 원본 atlas와 실측 화면 좌표를 다시 대조해 확정했다.

- 이 status BG에서 palette index `0`은 투명으로 합성되는 값이 아니라 **실측상 분홍색으로 보이는 활성 색**이다.
- 더 중요한 점은 일본어 라벨 tile이 별도의 투명 text overlay가 아니라 **노란 status panel 배경 자체를 포함한 완성형 4bpp tile**이라는 점이다.
- 따라서 v2처럼 글자 외 영역을 index `0`으로 초기화하면 아래 노란 BG가 드러나는 것이 아니라 원래 tile 안의 노란 panel scanline을 제거하고 분홍색 index `0`을 직접 표시하게 된다.

원본의 공용 빈 panel tile `0x012`을 해독하면 상단 8 scanline은 정확히 다음과 같다.

```text
66666666
99999999
AAAAAAAA
BBBBBBBB
BBBBBBBB
BBBBBBBB
BBBBBBBB
BBBBBBBB
```

실측 화면의 빈 stat 셀을 16 px 높이로 확인하면 하단은 이 패턴의 수직 대칭이며, 전체 native 배경은 다음 프로필이다.

```text
6, 9, A, B, B, B, B, B,
B, B, B, B, B, A, 9, 6
```

즉 `6=붉은 경계`, `9=주황 bevel`, `A=노랑`, `B=연노랑 panel` 계층을 라벨 tile 자체가 가지고 있다. v3는 모든 한글 라벨 cell을 이 **원본 16 px native background template**으로 먼저 복원하고, 글자와 외곽선 픽셀만 덮는다.

또한 원본 일본어 글꼴 스타일을 다시 확인한 결과 어두운 색은 우하단 drop shadow가 아니라 글자 외곽 전체를 감싸는 1 px contour이다. 따라서 v3는:

- 한글 fill: palette index `10 (A)`
- 외곽선: palette index `5`
- 외곽선 방식: 8-neighbour 1 px dilation
- 글자/외곽선 이외: native background template byte-preserve
- palette index `0`: 생성 라벨에서 사용하지 않음

으로 변경했다.

v3 테스트 ROM:

- `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_nativebg_outline_v3_20260829.gba`
- SHA-256 `5256e47e5028c4c75c47bbff323f3a89fa7444e5aa426a459fb9966d4e216fd7`
- manifest `analysis/ggen_advance_status_ui_tile_overlay_nativebg_outline_v3_20260829.json`
- preview `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_nativebg_outline_v3_preview_20260829.png`

정적 gate는 native background tile `0x012`의 원본 scanline을 byte-level로 확인하고, 모든 비글자/비외곽선 픽셀이 16 px native template과 일치하는지 검증한다. decoded atlas 크기와 palette는 계속 그대로 유지된다.

## 12. v3 실측 승인과 main TIP 반영

사용자 실측에서 v3의 native yellow background + full contour 스타일이 원본 화면과 자연스럽게 맞는 것을 확인했다. 승인본을 재빌드하여 manifest의 `verification.result=PASS`를 고정한 뒤 main TIP으로 승격했다.

- 승인 POC: `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_nativebg_outline_v3_approved_20260829.gba`
- SHA-256: `5256e47e5028c4c75c47bbff323f3a89fa7444e5aa426a459fb9966d4e216fd7`
- manifest: `analysis/ggen_advance_status_ui_tile_overlay_nativebg_outline_v3_approved_20260829.json`
- 당시 main TIP SHA-256: `5256e47e5028c4c75c47bbff323f3a89fa7444e5aa426a459fb9966d4e216fd7`

이 승격은 화면 스타일 승인 근거를 보존하기 위한 중간 checkpoint다. 이후 전수 tile-reference census에서 v3의 `移動` scratch remap 정책에 숨은 충돌 가능성이 발견되어 바로 후속 수정했다.

## 13. UI atlas 전수 census와 v3 scratch-tile 가정 수정

새 전수 감사 도구:

- `tools/analyze_ggen_advance_status_ui_graphic_followup.py`
- 결과: `analysis/ggen_advance_status_ui_graphic_followup_20260829.json`

resource table `0..68`을 모두 파싱하고 decoded atlas의 519개 tile ID 사용처를 합집합으로 조사한 결과:

- 유효 tilemap/resource: **67개**
- decoded atlas tile: **519개**
- 최소 한 resource에서 참조되는 tile: **519개**
- 전역 미사용 tile: **0개**

따라서 v3에서 `移動` 분리를 위해 임시로 선택했던 `0x1F3-0x1FA`는 실제 미사용 영역이 아니었다. 이 8개는 정확히:

- `resource_table[64]`
- file `0x000E04D8`
- `4x2`
- tiles `1F3 1F4 1F5 1F6 / 1F7 1F8 1F9 1FA`

의 정상 소유 자산이다. 현재 화면에서 즉시 부작용이 보이지 않았더라도 장기적으로 다른 UI를 깨뜨릴 수 있으므로 v3의 scratch remap은 폐기했다.

수정 정책은 원본의 `運動/移動` 공유구조 자체를 보존하는 것이다.

- `運動`: `146 147 148 149 / 14E 14F 150 151`
- `移動`: `15A 15B 15C 149 / 161 162 150 151`
- 공유: `149 / 150 / 151`

한국어 `운동 / 이동` 역시 두 번째 음절 `동`이 같고 같은 32x16 중앙 정렬 규칙을 쓰므로, `운동`을 먼저 rasterize한 뒤 `이동`을 rasterize해도 세 공유 tile의 최종 bytes가 **완전히 동일**함을 gate로 검증할 수 있다. 이에 따라 unit tilemap은 원본 그대로 유지하고 resource[64]도 byte exact 보존한다.

## 14. 같은 그래픽 계열 추가 일본어 라벨 및 v4 한글화

승인 화면에서 남아 있던 하단 일본어를 같은 resource family에서 추적했다. `0x0806C934` renderer가 `resource_table + 0xA0`, 즉 **resource[40]**을 읽어 `0x0800277C` tilemap blitter로 그린다.

resource[40]:

- file `0x000DFF9C`
- size `32x8`

스크린샷과 tilemap 좌표를 대조해 다음 다섯 fixed graphic label을 확정했다.

| 원문 | 한글 | map 위치 | tiles |
|---|---|---|---|
| `ID効果` | `ID효과` | `(1,0)` 4x2 | `0C3..0C6 / 0CA..0CD` |
| `攻撃` | `공격` | `(0,2)` 4x2 | `17F..182 / 18A..18D` |
| `残り回数` | `남은횟수` | `(18,2)` 7x2 | `183..189 / 18E..194` |
| `命中` | `명중` | `(0,4)` 4x2 | `195..198 / 199..19C` |
| `回避` | `회피` | `(0,6)` 4x2 | `1A0..1A3 / 1A4..1A7` |

`ID効果`의 8개 tile은 resource[16,17,18,19,40]에서 같은 위치로 공유되어 있어 공통 UI header 자산임을 확인했다. 나머지 네 라벨은 resource[40] 전용 tile이다.

`ID효과`는 32px 폭에 4문자를 넣어야 하므로 프로젝트의 native `Galmuri11-Condensed.bdf` 8x16을 사용하고, 나머지는 기존 승인 style과 같은 `Galmuri11.bdf` 12x12 + native background + 8-neighbour contour로 작성했다. 별도 확대 이미지나 새 규격을 만들지 않는다.

v4 결과:

- POC: `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v4_20260829.gba`
- SHA-256: `7d167107d574bace3f090d0a84d1be3f96cb772100df8150a87a4bc987fd3d28`
- manifest: `analysis/ggen_advance_status_ui_tile_overlay_followup_v4_20260829.json`
- preview: `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v4_preview_20260829.png`

검증:

- 총 한글화 graphic label **14종**
- decoded atlas **16,608 -> 16,608 bytes**
- palette 수정 **0**
- tilemap 수정 **0**
- original-half 변경 허용 **resource_table[0] 4 bytes만**
- original-half unexpected change **0**
- `운동/이동` shared tiles byte-identical **PASS**
- resource[64] `0x1F3-0x1FA` byte exact 보존 **PASS**
- custom LZSS round-trip **PASS**
- 기존 unified/development regression tests **10/10 PASS**

v4를 canonical main TIP으로 승격했다.

- main: `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256: `7d167107d574bace3f090d0a84d1be3f96cb772100df8150a87a4bc987fd3d28`
- 이전 v3 main backup: `integrated/main_tip/backups/20260829T110907Z_status_ui_followup_lower_labels_resource64_collision_fix_20260829/`

추가로 같은 atlas의 **4x2 word-chunk** resource가 여러 개 더 존재한다. `resource[41]`은 실측으로 `汎用 -> 범용`이 확정됐고, 후속 ROM-font bitmap 대조로 `resource[42..46]`도 아래와 같이 식별했다. `47`, `64`, `65`는 아직 의미가 확정되지 않았으므로 수정하지 않는다.

## 15. unit-type 4x2 badge 추가 식별 및 v5 반영

resource[41..47]은 `0x08005518`이 반환하는 unit record `+0x19` 값을 사용해 `resource_table[40 + type]`로 선택되는 같은 계열의 4x2 badge다. 화면 추정만으로 번역하지 않기 위해 badge의 밝은 글자 mask를 ROM 자체의 identified 12x12 Japanese font bitmap과 직접 비교했다. 각 glyph는 ±2 px 정렬 탐색으로 Dice 유사도를 구했다.

확정 결과:

| resource | 원문 | 한글 | 대표 glyph shape score |
|---|---|---|---|
| 41 | `汎用` | `범용` | 기존 실측 확정 |
| 42 | `宇宙` | `우주` | `宇 0.821`, `宙 0.956` (`宙` slot `0x04F2`) |
| 43 | `地上` | `지상` | `地 0.923`, `上 0.725` |
| 44 | `万能` | `만능` | `万 0.692`, `能 0.981` |
| 45 | `水陸` | `수륙` | `水 0.750`, `陸 0.976` |
| 46 | `飛行` | `비행` | `飛 0.903`, `行 0.889` |

각 badge는 4x2 / 32x16 규격을 그대로 사용하며 v3에서 승인된 native background + full contour 방식으로 다시 그렸다. 새 tile ID나 tilemap remap은 사용하지 않는다.

v5:

- `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v5_20260829.gba`
- SHA-256 `a6d78ed62929f1df6d52460f6a5dcb24b24cfb8de9f8cf9145cf7d2980e77971`
- manifest `analysis/ggen_advance_status_ui_tile_overlay_followup_v5_20260829.json`
- preview `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v5_preview_20260829.png`

최종 status fixed-graphic 적용 수는 **19종**이다. 기존 9종 + resource40 하단 5종 + unit-type 추가 5종이다.

v5 검증은 v4와 동일한 안전 gate를 유지한다.

- decoded atlas `16,608 bytes` 유지
- palette 수정 0
- tilemap 수정 0
- original-half unexpected change 0
- `운동/이동` shared tile bytes 동일
- resource[64] `1F3..1FA` 원본 보존
- LZSS round-trip PASS
- unified/development regression 10/10 PASS

v5를 canonical main TIP으로 최종 승격했다.

- main: `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256: `a6d78ed62929f1df6d52460f6a5dcb24b24cfb8de9f8cf9145cf7d2980e77971`
- main/candidate byte-equal: `true`
- 이전 v4 main backup: `integrated/main_tip/backups/20260829T111535Z_status_ui_type_badges_and_lower_labels_full_followup_20260829/`

현재 같은 구조에서 미확정으로 남긴 것은 `resource[47]`, `resource[64]`, `resource[65]`이다. 특히 resource64는 v3 scratch 충돌을 발견한 실제 소유 resource이므로 의미를 확인하기 전까지 byte exact 보존한다.

## 16. `ID효과` 우측 일본어 잔여 실측과 spill-tail v6 수정

v5 실측에서 `ID효과` 본문은 정상 한글화됐지만 바로 오른쪽에 원본 `ID効果`의 마지막 글자 일부가 남는 현상이 확인됐다. 처음에는 라벨 전체가 6x2라고 단순화할 수 있어 보였지만 resource[16..19]와 resource[40]을 다시 셀 단위로 대조한 결과 실제 구조는 더 세분화되어 있었다.

`ID효과`의 한글 본문이 들어가는 공통 body는 기존 분석대로 4x2다.

- top: `0C3 0C4 0C5 0C6`
- bottom: `0CA 0CB 0CC 0CD`

그러나 원본 일본어의 마지막 glyph는 이 body 오른쪽의 **추가 1 cell**까지 걸쳐 있다.

resource[40]에서는:

- spill top `0x173`
- spill bottom `0x178`

을 사용한다. 이 두 tile은 resource40에서만 쓰이며, native panel background 위에 일본어 마지막 glyph의 왼쪽 부분이 남아 있는 형태다. 실제 clean atlas에서 `0x173/0x178`의 오른쪽 3px는 native background와 byte-equivalent이고, glyph residue는 왼쪽 5px에 집중되어 있음을 확인했다.

resource[16..19]에서는 같은 glyph tail의 왼쪽 5px를:

- `0x0C7`
- `0x0CE`

에 공유하고, 오른쪽 3px에는 별도의 panel-edge geometry가 들어 있다. 이어지는:

- `0x0C8`
- `0x0CF`

는 edge tile이므로 지우면 안 된다.

따라서 v6 수정은 라벨을 억지로 6x2로 다시 중앙 정렬하지 않는다. `ID효과` 4x2 본문의 위치와 글꼴은 그대로 유지하고, 일본어가 실제로 넘친 spill 부분만 제거한다.

- resource40 `0x173/0x178`: 전체를 원본 native panel background로 복원
- shared `0x0C7/0x0CE`: 왼쪽 5px만 native background로 복원
- shared `0x0C7/0x0CE` 오른쪽 3px: 원본 edge geometry byte-preserve
- `0x0C8/0x0CF`: byte exact 보존
- palette / tilemap / atlas size 변경 없음

builder에 `clear_id_effect_residual_tail()`을 추가했으며, clean atlas에서 shared/resource40 tail의 왼쪽 5px가 동일하다는 것과 resource40 tail 오른쪽 3px가 native background라는 것을 gate로 검증한다. 분석 도구 `tools/analyze_ggen_advance_status_ui_graphic_followup.py`도 이 spill-tail 구조를 별도 항목으로 기록하도록 갱신했다.

v6 후보:

- `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v6_ideffect_tailfix_20260829.gba`
- SHA-256 `c94eff42d4ee7f446ab51648a419f7826aa0b90bd8840706a3af7ea7832ffca6`
- manifest `analysis/ggen_advance_status_ui_tile_overlay_followup_v6_ideffect_tailfix_20260829.json`

정적 검증:

- resource40 spill `0x173/0x178` == native background: PASS
- shared `0x0C7/0x0CE` 왼쪽 5px clear: PASS
- shared `0x0C7/0x0CE` 오른쪽 3px edge preserve: PASS
- `0x0C8/0x0CF` exact preserve: PASS
- regression tests 10/10 PASS
- decoded atlas 16,608 bytes 유지 / palette 수정 0 / tilemap 수정 0

v6를 canonical main TIP으로 승격했다.

- main: `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256: `c94eff42d4ee7f446ab51648a419f7826aa0b90bd8840706a3af7ea7832ffca6`
- candidate/main byte-equal: `true`
- 이전 v5 main backup: `integrated/main_tip/backups/20260829T113702Z_status_ui_id_effect_spill_tail_fix_20260829/`

## 17. 무장 행 소형 그래픽 v7/v8 보정

v7 실측에서 `실 / 공 / 명 / 탄` 한글 본문은 표시됐지만 원본 일본어의 검은 그림자 획이 뒤에 남았다. 원인은 소형 녹색 배지의 원본 glyph를 D/E/F 밝은 픽셀만으로 오판정한 것이다. 실제 glyph는 **palette index 4의 검은 그림자/외곽선 + D/E/F 본문 계열**로 구성된다. v7은 D/E/F만 지웠기 때문에 index 4의 일본어 그림자가 남았고, 한글 외곽선도 index 13을 사용해 원본의 검은 그림자 스타일과 달랐다.

v8에서는 원본 4/D/E/F glyph footprint 전체를 측정된 native green background scanline으로 복원한 후, 한글을 **index 15 본문 + index 4 8방향 1px 검은 외곽선**으로 다시 그린다. palette 데이터, 8x8 4bpp 규격, resource 크기와 tilemap cell은 변경하지 않는다.

무장 행 반복 resource는 다음과 같다.

- resource[36] `0x000DFA8C`: 1행
- resource[37] `0x000DFB10`: 2행
- resource[38] `0x000DFC14`: 3행
- resource[39] `0x000DFD98`: 4행

고정 소형 라벨은 `実 -> 실`, `攻 -> 공`, `命 -> 명`, `弾 -> 탄`이다.

우측 2글자 무장 종류는 고정 `射程`이 아니라 별도 동적 4x2 resource 조합임을 추가 확인했다.

- resource[54] `射単` -> `사단`
- resource[55] `近単` -> `근단`
- resource[56] `射全` -> `사전`
- resource[57] `近全` -> `근전`

원본도 글자 타일을 공유한다.

- `射`: `0x168 / 0x16E`
- `近`: `0x1ED / 0x1EE`
- `単`: `0x1EB / 0x1EC`
- `全`: `0x169 / 0x16F`

한글도 `사/근 + 단/전`으로 같은 공유 구조를 유지한다. resource[49]/[50]의 다른 1글자 무장 타입 배지는 의미가 확정되지 않아 보존한다.

v8 테스트 ROM:

`outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v8_weaponbadges_shadow_categories_20260829.gba`

SHA-256: `e64b75330ce56415782b89f982f56e046699161ef511e0f86c800a084c2032c3`

정적 검증은 palette 수정 0, status tilemap 수정 0, decoded atlas 16,608 bytes 유지, compression round-trip PASS, 기존 회귀 테스트 10/10 PASS다. 메인 TIP은 아직 v6 상태를 유지하며 v8은 실측 확인 전까지 후보로 둔다.

## 18. v9 — Galmuri9 소형 배지 + `間 -> 간`

v8 실측에서 `실 / 공 / 명 / 탄 / 사 / 근 / 단 / 전`은 구조적으로 정상 교체됐지만 8x16 셀 안에서 Galmuri11-Condensed가 원본 소형 배지보다 크게 보였다. v9에서는 이 8개 공유 glyph만 `Galmuri9.bdf`로 교체한다. Galmuri9의 한글 BBX는 8x9 또는 9x9이므로 9px 폭 glyph는 nearest-neighbour로 8x9에 맞추고, 원본 8x16 셀의 세로 중앙에 배치한다. 1px 8방향 검은 contour(index 4)와 밝은 본문(index 15), 원본 green badge background 복원 규칙은 그대로 유지한다.

누락된 `間`은 status resource[53]에서 별도 2x2, 즉 16x16 badge임을 확정했다.

- resource[53]: file `0x000E0258`
- tiles: `0x1E7 0x1E8 / 0x1E9 0x1EA`
- 원본 dark interior: palette index 4
- 원본 `間` bright strokes: D/E/F 계열

따라서 `間`은 작은 8x16 glyph로 축소하지 않고 사용자 실측 요구대로 **가운데 큰 `간`**으로 처리한다. D/E/F 원문 stroke만 index 4 background로 복원한 뒤 `Galmuri11` native 12x12 `간`을 16x16 중앙 `(2,2)`에 배치하고 index 15로 렌더한다. frame/background와 resource/tilemap 규격은 그대로다.

v9 후보:

- `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v9_galmuri9_interval_20260829.gba`
- SHA-256 `27457fd21bf751fe5ad669d7822bc17b006461aeda85afd25359eecaa20a811f`
- manifest `analysis/ggen_advance_status_ui_tile_overlay_followup_v9_galmuri9_interval_20260829.json`

검증: decoded atlas 16,608 bytes 유지 / palette 수정 0 / tilemap 수정 0 / `間 -> 간` 55 source pixels clear + 34 Korean ink pixels / weapon glyph 8종 Galmuri9 적용 / compression round-trip PASS / regression 10/10 PASS.

## 19. 전투 무장 UI는 별도 D54 그래픽 family

v9 조사에서 status 화면과 전투 무장 선택 화면이 **같은 타일을 다른 위치에서 재사용하는 구조가 아님**을 확정했다. status 화면은 `0x000E0518 -> 0x000DC848` family를 사용하지만 전투 화면은 완전히 별개의 resource table/atlas를 사용한다.

- battle resource table: file `0x000D54E4`, GBA `0x080D54E4`
- battle compressed atlas: file `0x000D45DC`
- decoded size: 6,080 bytes = 190개의 4bpp 8x8 tile
- base battle UI: resource[2] `0x000D4F4C`, 30x20 tilemap
- weapon-list 반복 구간: base map tile row `6-13`
- dynamic overlays: resource[3..8] 4x2, resource[9..13] 2x2, resource[14..16] 3x2
- renderer: `0x0801D09C`
- battle table literal refs: file `0x0001D10C`, `0x0001D468`, `0x0001D574`

status 쪽 `実/攻/命/弾/射/近/単/全/間` 대상 20개 tile payload를 battle atlas 190개 tile과 byte exact로 전수 대조했지만 **동일 tile은 0개**였다. 따라서 v8/v9에서 status atlas pointer만 redirect해도 전투 화면 일본어가 그대로 남는 것이 정상적인 구조적 결과다.

근거 analyzer:

- `tools/analyze_ggen_advance_battle_weapon_ui_tiles.py`
- `analysis/ggen_advance_battle_weapon_ui_tiles_20260829.json`

후속 battle 패치는 status tile ID를 복사하지 않고 D54 family의 consumer/index 의미를 개별 폐쇄한 뒤, D54 atlas 자체를 원본 크기/팔레트 그대로 별도 재빌드해야 한다.

## 20. v10 — `間 -> 간` black-fill 제거 + Galmuri7 소형 badge

v9 실측에서 두 가지 추가 문제가 확인됐다.

1. `間 -> 간` 16x16 badge는 `간` 자체가 아니라 badge 내부 전체가 검은색으로 보였다. v9는 resource[53]의 palette index 4 dark interior를 그대로 유지했기 때문이다.
2. `공` 등 Galmuri9 소형 glyph는 9px 폭 glyph를 8px tile column으로 축소하는 과정에서 모음 형태가 찌그러질 수 있었다. 실제 `공`이 `긍`처럼 보인 실측이 이에 해당한다.

v10에서는 두 문제를 다음과 같이 수정한다.

### 20.1 `間 -> 간` 16x16 badge

- resource[53] / file `0x000E0258`
- tiles `0x1E7 0x1E8 / 0x1E9 0x1EA`
- 원본 2x2 / 16x16 규격 유지
- palette 데이터 변경 없음

v9의 dark index-4 full interior를 더 이상 배경으로 쓰지 않는다. 같은 status atlas의 동적 category badge에서 측정한 native green 16x16 background pattern을 그대로 복원한다.

- background palette: `6/7/8/9/A` 계열만 사용
- `간` font: `Galmuri7.bdf`, native 7x7
- 배치: 16x16 중앙
- 본문: palette index 15
- contour: palette index 4, 8방향 1px

검증에서 v10 `간` badge의 palette index 4 픽셀 수는 **52개**이며 manifest의 contour pixel 수도 정확히 **52개**다. 즉 index 4는 더 이상 배경 fill로 존재하지 않고 `간` 주변 contour에만 사용된다.

### 20.2 소형 무장 badge Galmuri7 전환

`실/공/명/탄/사/근/단/전` 8종은 Galmuri9 대신 `Galmuri7.bdf` native glyph를 사용한다. Galmuri7 Korean BBX는 6x7 또는 7x7이며, **리사이즈 없이** 기존 8x16 cell 중앙에 배치한다. 이로써 v9의 9px→8px horizontal resize가 완전히 제거되며 `공`의 모음/받침 왜곡 경로도 사라진다.

- `공` Galmuri7 native ink: 23 pixels
- output `공` ink: 23 pixels
- horizontal resize: 없음
- 기존 native green background 복원 + palette 4 contour + palette 15 ink 정책은 유지

v10 후보:

- `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v10_galmuri7_intervalbg_20260829.gba`
- SHA-256 `4cfd9bcaeadf33e068848ba0e4e45bc8bec2e0d62e0cf7a0fdbd508ac389998f`
- manifest `analysis/ggen_advance_status_ui_tile_overlay_followup_v10_galmuri7_intervalbg_20260829.json`
- preview `outputs/20260829_ggen_advance_status_ui/ggen_advance_status_ui_tile_overlay_followup_v10_galmuri7_intervalbg_preview_20260829.png`

검증: decoded atlas 16,608 bytes 유지 / palette 수정 0 / tilemap 수정 0 / original-half unexpected change 0 / compression round-trip PASS / regression 10/10 PASS.

사용자 실측에서 v10의 `간` native background, Galmuri7 `실/공/명/탄/사/근/단/전` 표시가 모두 정상 확인되어 main TIP으로 승격했다.

- canonical main TIP: `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256: `4cfd9bcaeadf33e068848ba0e4e45bc8bec2e0d62e0cf7a0fdbd508ac389998f`
- promotion reason: `approved_status_ui_galmuri7_interval_background_v10_20260829`

## 21. 전투 무장 선택 UI 스크린샷 재측정 및 source-font Galmuri7 POC

사용자 제공 전투화면 스크린샷에서 실제 잔여 일본어는 무장행마다 다음 형태로 확인된다.

- 좌측 1글자: `実`
- 공격값 앞: `攻`
- 명중값 앞: `命`
- 탄수 앞: `弾`
- 우측 분류: `射単` / 동일 계열 `近単`, `射全`, `近全`

스크린샷을 원본 GBA 4x 배율에 맞춰 측정하면 `実/攻/命/弾`은 각각 약 8x13 visible pixels, `射単`은 약 15x13 visible pixels로, **원본 8x16 font cell 한 글자/두 글자 구조**와 일치한다. 현재 승인 main TIP에서 이 원본 8x16 source font bank(file `0x00094028`)의 관련 JP slots는 일본판 ROM과 byte-identical로 그대로 남아 있음도 확인했다. 즉 status E0518/DC848 atlas 한글화와 독립적으로, battle UI가 원본 source-font glyph를 계속 소비할 수 있는 상태다.

측정/문맥으로 고정한 source slot은 다음과 같다.

| 일본어 | 한글 | 8x16 slot | 근거 |
|---|---|---:|---|
| `実` | `실` | `0x0323` | verified 8x16 charmap + screenshot |
| `攻` | `공` | `0x02B7` | verified 8x16 charmap + screenshot |
| `命` | `명` | `0x00D0` | verified 8x16 charmap + screenshot |
| `弾` | `탄` | `0x00C0` | `実体弾`, `無駄弾` weapon/defence corpus evidence |
| `射` | `사` | `0x0324` | verified 8x16 charmap + `射単` screenshot |
| `近` | `근` | `0x0248` | verified 8x16 charmap |
| `単` | `단` | `0x042B` | `<042B><00BB>砲 = 単装砲` + screenshot-shape strongest candidate |
| `全` | `전` | `0x00B9`, `0x05FE` | 두 slot 모두 independently verified `全` duplicate |

전투 화면을 바로 검증할 수 있도록 **원본 8x16 source font의 위 slot만** Galmuri7로 교체하는 최소 POC를 만들었다. 12x12 font, relocated Korean font, D54 atlas, palette, tilemap은 전혀 변경하지 않는다. Galmuri7 6x7/7x7 native bitmap은 horizontal resize 없이 8x16 cell 중앙에 배치한다. battle renderer가 기존처럼 outline/color를 생성한다면 스크린샷의 일본어만 같은 스타일의 작은 한글로 바뀌어야 한다.

- builder: `tools/build_ggen_advance_battle_weapon_font_galmuri7_poc.py`
- POC: `outputs/20260829_ggen_advance_battle_ui/ggen_advance_battle_weapon_font_galmuri7_poc_20260829.gba`
- SHA-256: `0365ad82039a670b9a93adccbb11c4e9a8420d5cf48e74cd4a88518dd512b170`
- manifest: `analysis/ggen_advance_battle_weapon_font_galmuri7_poc_20260829.json`
- preview: `outputs/20260829_ggen_advance_battle_ui/ggen_advance_battle_weapon_font_galmuri7_preview_20260829.png`
- changed bytes: 193, 전부 위 9개의 8x16 source slot 범위 내부
- regression: 10/10 PASS

이 POC는 **실측 전에는 main 승격 금지**다. 만약 전투화면 일본어가 그대로라면 source-font consumer 가설을 폐기하고, 이미 식별한 별도 D54 family의 VRAM consumer를 직접 패치하는 방향으로 전환한다.
