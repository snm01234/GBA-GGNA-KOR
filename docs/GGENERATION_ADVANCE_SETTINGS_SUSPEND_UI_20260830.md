# G Generation Advance 설정/중단 UI 정적 분석 (2026-08-30)

## 1. 작업 상태

상황메뉴 follow-up 후보는 실측 승인 후 main TIP로 승격했다.

- 승격 후보: `outputs/20260830_ggen_advance_situation_menu/ggen_advance_situation_menu_ko_followup_candidate_20260830.gba`
- 검증 매니페스트: `analysis/ggen_advance_situation_menu_ko_followup_20260830.json`
- 현재 main TIP: `SD Gundam GGeneration Advance (Korean).gba`
- SHA-256: `9fb0b509202951c0fc98a702195052d183d5ea82635739cc9d91fd4b5cdb5d3b`
- 승격 사유: `situation_menu_followup_20260830`
- 이전 main TIP 백업: `integrated/main_tip/backups/20260830T011850Z_situation_menu_followup_20260830/`

이후 첨부 실측 화면의 **설정 화면**과 **중단 처리 경고 팝업**을 원본 일본판 ROM 기준으로 정적 분석했다. 재현 가능한 검증기는 `tools/analyze_ggen_advance_settings_suspend_ui.py`, 결과는 `analysis/ggen_advance_settings_suspend_ui_20260830.json`이며 최종 PASS이다.

---

## 2. 지도 팝업 메뉴에서 두 화면으로 들어가는 경로

지도 팝업 메뉴의 action table은 `0x08D56408`이다. 메뉴 인덱스 기준으로 다음 두 항목이 직접 연결된다.

- index 1 `中断` -> Thumb 함수 `0x08020AAC`
- index 4 `設定` -> Thumb 함수 `0x08020EC8`

따라서 이번 두 화면은 기존에 한글화한 지도 팝업 메뉴의 후속 소비처이며, 서로 다른 렌더 방식으로 구현되어 있다.

---

## 3. 설정 화면: 고정 BG 그래픽 + 동적 선택 그래픽 + 12x12 footer의 혼합 구조

### 3.1 화면 전체를 구성하는 3개 BG 리소스

설정 함수 `0x08020EC8`은 `0x08001D70`을 이용해 세 개의 30x20 BG descriptor를 로드한다. `0x08001D70` 내부에서는 custom LZSS 함수 `0x08001A84`를 사용한다.

| 역할 | 리소스 | literal | draw call | destination | decoded tiles |
|---|---:|---:|---:|---:|---:|
| background A | `0x08C727E4` | `0x08021040` | `0x08020F4C` | `0x0600F800` | 355 |
| background B | `0x08C71984` | `0x08021048` | `0x08020F66` | `0x06007800` | 132 |
| **foreground fixed labels** | **`0x08C70DF0`** | **`0x08021050`** | **`0x08020F8C`** | **`0x0600E800`** | **131** |

세 descriptor는 모두 다음 포맷을 가진다.

`[flags][reserved][width][height][map_rel:u16][map_len:u16][tiles_rel:u16][compressed_len:u16][palette_rel:u16][palette_len:u16]`

foreground `0x08C70DF0`은 특히 다음 값으로 닫힌다.

- dimensions: 30x20
- map rel: `0x0010`
- map bytes: `0x04B0` = 30 x 20 x 2
- compressed tile rel: `0x04C0`
- compressed bytes: `0x0674`
- decompressed: 4192 bytes = 131 4bpp tiles
- palette rel: `0x0B34`
- palette bytes: `0x60`

### 3.2 일본어 항목명은 동적 텍스트가 아니라 foreground atlas에 박힌 타일

foreground map geometry가 첨부 화면의 패널 위치와 직접 일치한다.

- 상단 `各種設定を行います`: map `(x=8,y=1)`, 14x2 tiles
  - 상단 tile IDs `0x005..0x012`
  - 하단 tile IDs `0x013..0x020`
- `攻撃方法の確認`: `(6,5)`, 12x2
  - `0x021..0x02C` / `0x02D..0x038`
- `メッセージの自動送り`: `(4,9)`, 14x2
  - `0x039..0x046` / `0x047..0x054`
- `メッセージ表示速度 / 早い / 遅い`: y=13..14의 foreground strip에 고정 그래픽으로 들어가며, 숫자 선택 버튼이 별도 그래픽으로 위에 합성된다.

즉 이 일본어는 translation sheet의 텍스트 포인터를 바꾸는 방식으로는 없어지지 않는다. **고정 BG 그래픽을 직접 다시 그려야 한다.**

### 3.3 ON/OFF와 1/2/3/4는 별도 그래픽 조합

설정 화면의 선택 컨트롤은 helper `0x08020C54`가 `0x08D562B4`의 6개 16-byte record를 읽어 합성한다.

| record | 위치 메타 | 의미 |
|---:|---:|---|
| 0 | x=20,y=5 | ON/OFF 첫 선택지 |
| 1 | x=25,y=5 | ON/OFF 둘째 선택지 |
| 2 | x=18,y=13 | 속도 1 |
| 3 | x=20,y=13 | 속도 2 |
| 4 | x=22,y=13 | 속도 3 |
| 5 | x=24,y=13 | 속도 4 |

두 번째 ON/OFF 행은 같은 record 0/1을 y 오프셋을 더해 재사용한다. 따라서 현재 language-neutral한 `ON/OFF`, `1/2/3/4`는 이번 고정 일본어 타일 수정과 분리해서 보존할 수 있다.

### 3.4 하단 `G GENERATION ADVANCE`는 다른 경로

하단 타이틀 원본 문자열은 `0x081BE8C4`의 `Gジェネレーション アドバンス`이며, `0x0802100A -> 0x08000CA0`을 통해 **12x12 텍스트 렌더러**로 그려진다. 현재 main TIP에서는 기존 번역 파이프라인에 의해 이미 `G 제네레이션 어드밴스`로 출력된다.

따라서 이 부분은 고정 그래픽 수정 대상이 아니다.

### 3.5 권장 한글화 방식

`0x08C70DF0` foreground 하나만 재구성하는 것이 가장 안전하다.

1. 원본 foreground descriptor의 map/frame/background/palette를 보존한다.
2. 일본어 글리프 footprint만 제거한다.
3. 원본 황색 fill/짙은 갈색 contour 인상을 유지한 한글을 다시 렌더한다.
4. 압축 크기가 바뀌므로 expansion 영역에 새 resource를 배치한다.
5. 유일한 foreground literal `0x08021050`만 새 리소스로 redirect한다.
6. `0x08C71984`, `0x08C727E4`, ON/OFF 및 숫자 컨트롤, footer text path는 건드리지 않는다.

초기 번역안:

- `各種設定を行います` -> `각종 설정을 합니다`
- `攻撃方法の確認` -> `공격방법 확인`
- `メッセージの自動送り` -> `메시지 자동 진행`
- `メッセージ表示速度` -> `메시지 표시 속도`
- `早い` -> `빠름`
- `遅い` -> `느림`

후보 ROM 구현 시 각 strip의 실제 픽셀 폭을 재측정해서 필요하면 문구를 더 압축한다.

---

## 4. 중단 경고 팝업: 텍스트 렌더러가 아니라 shared OBJ sprite animation

### 4.1 중단 함수에는 12x12 문자열 draw가 없다

중단 함수 `0x08020AAC..0x08020C2C`를 전수 검사했으며 `0x08000CA0` 호출은 **0건**이다.

경고창은 다음 경로로 생성된다.

- resource literal: `0x08020B98` -> `0x08C7504C`
- `0x08020B10 -> 0x08012B04`, animation ID = **11**
- 저장/중단 처리: `0x08020B2A -> 0x08061984`
- 처리 후 `0x08020B56 -> 0x08012B04`, animation ID = **5**

즉 첨부 화면의

- `中断処理を行っています`
- `電源を切らないでください`

두 줄은 문자열 DB가 아니라 **animation 11의 OBJ tile graphics**에 포함되어 있다.

### 4.2 shared sprite resource 구조

`0x08C7504C`는 공용 sprite resource이다.

- kind/header field: 0 / 6
- graphics rel: `0x0E04`
- graphics file offset: `0x00C75E50`
- palette rel: `0x2EC4`
- palette file offset: `0x00C77F10`
- graphics span: `0x20C0` bytes = **262 tiles**
- animations: **12개**, IDs 0..11

animation 11 record는 resource 기준 `+0xC2C`, file offset `0x00C75C78`부터 시작하고 OBJ 12개로 구성된다.

### 4.3 초기 144x32 가설 — 후속 실측으로 폐기됨

animation 11의 OBJ tile 범위:

`0..15`, `16..23`, `24..27`, `28..35`, `36..43`, `44..51`, `52..59`, `60..63`, `64..65`, **`66..97`**, **`98..129`**, **`130..137`**

마지막 세 OBJ는 각각 다음 크기로 결합된다.

- tiles 66..97: 64x32
- tiles 98..129: 64x32
- tiles 130..137: 16x32

합계 **144x32**로, 첨부 팝업의 느낌표 오른쪽에 있는 두 줄 경고문 영역과 정확히 대응한다. 앞쪽 tiles 0..65는 경고 아이콘/프레임 계열이다.

따라서 경고 아이콘과 프레임을 재작성할 필요 없이 **문자 그래픽 영역만 교체**할 수 있다.

### 4.4 초기 destination-tile 해석 — 후속 실측으로 source lookup 해석으로 정정됨

`0x08C7504C` 포인터는 원본 ROM에서 5곳이 소비한다.

- `0x0801212C`
- `0x080121CC`
- `0x08020B98` ← 이번 중단 화면
- `0x08026B6C`
- `0x0807385C`

전체 12 animation의 OBJ tile 범위를 전수 비교한 결과:

- animation 0..9는 tile 66 이상을 사용하지 않는다.
- **animation 10과 11만 tiles 66..137을 공유한다.**

따라서 글로벌 `0x08C7504C`의 66..137을 직접 덮어쓰면 다른 곳에서 쓰는 animation 10까지 바뀔 수 있다. 현재 의미가 확인되지 않은 animation 10을 함께 변경하는 것은 위험하다.

### 4.5 초기 권장 방식 — clone 방향은 유지, 내부 tile 해석은 8절에서 수정

가장 안전한 방식은 **shared sprite bank clone + consumer-specific redirect**이다.

1. `0x08C7504C` 전체 resource를 expansion 영역으로 복제한다.
2. 복제본의 animation 11 text graphics만 수정한다.
3. tiles 0..65의 느낌표/프레임은 원본 그대로 유지한다.
4. 원본 shared resource는 전혀 수정하지 않는다.
5. 오직 suspend 함수의 literal `0x08020B98`만 clone 주소로 redirect한다.
6. 같은 clone에서 처리 후 animation 5를 호출해도 animation 5는 tiles 0..43만 사용하므로 안전하다.

초기 문구안:

- `중단 처리 중입니다`
- `전원을 끄지 마세요`

144x32 영역에 2행으로 충분히 들어갈 수 있으며, 후보 구현 시 Galmuri 계열 raster와 원본 갈색 outline/황색 face의 실제 팔레트 인덱스를 맞춘다.

---

## 5. 유사 케이스 한글화 정책

이번 분석으로 이후 잔여 UI를 세 유형으로 나누어 처리할 수 있다.

### A. fixed BG label

설정 화면의 일본어 항목명과 같은 유형.

- descriptor -> tilemap -> compressed atlas -> palette를 닫는다.
- 원본 프레임/하이라이트/배경 픽셀을 보존한다.
- 글리프 footprint만 제거 후 한글 재렌더한다.
- 압축 크기 변경 시 resource를 relocation하고 해당 literal만 redirect한다.

### B. shared OBJ message

중단 경고와 같은 유형.

- resource pointer 전 소비처를 먼저 전수 검색한다.
- animation별 OAM tile range를 계산해 공유 tile 여부를 감사한다.
- 공유가 있으면 글로벌 in-place patch를 금지한다.
- 특정 화면 전용 clone을 만들고 그 소비처 literal만 redirect한다.

### C. dynamic token text

설정 화면 footer와 같은 유형.

- 실제 12x12/8x16 renderer 호출 여부를 확인한다.
- 기존 번역 포인터/relocation 파이프라인을 우선 사용한다.
- 상황메뉴에서 확인한 것처럼 encode token -> slot -> active painted glyph까지 일치 검증한다.

### D. language-neutral choice graphics

ON/OFF, 1..4처럼 번역 필요성이 낮은 공용 UI는 다른 한글화 대상과 분리하여 보존한다. 공유자산을 불필요하게 건드리지 않는 것을 우선한다.

---

## 6. 다음 구현 권장 순서

1. **설정 foreground 후보**
   - `0x08C70DF0` clone/rebuild
   - 6개 일본어 고정 라벨만 한글화
   - 원본 배경/outline 보존 감사
2. **중단 경고 후보**
   - `0x08C7504C` clone
   - animation 11의 144x32 text area만 한글화
   - `0x08020B98`만 redirect
3. 각 후보를 현재 승인 main TIP `9fb0b509...` 기준으로 생성
4. 설정 화면과 중단 화면을 각각 실측
5. 정상 시 main TIP 순차 승격

분석 단계에서는 원본/승인 main TIP의 관련 그래픽 리소스를 수정하지 않았으며, 정적 분석만 수행했다.

---

## 7. 1차 통합 후보 ROM 구현 — 실측 실패, main TIP 미승격 (20260830)

요청에 따라 현재 승인 main TIP `9fb0b509...`을 부모로 설정 화면과 중단 경고를 한 후보 ROM에 구현했다.

- builder: `tools/build_ggen_advance_settings_suspend_ui_ko_poc.py`
- candidate: `outputs/20260830_ggen_advance_settings_suspend_ui/ggen_advance_settings_suspend_ui_ko_candidate_20260830.gba`
- SHA-256: `e33a6915f6128b515779b07640822fba212595adf125c03c8ded64b349c1c770`
- manifest: `analysis/ggen_advance_settings_suspend_ui_ko_20260830.json`
- settings preview: `outputs/20260830_ggen_advance_settings_suspend_ui/ggen_advance_settings_ui_ko_preview_20260830.png`
- suspend preview: `outputs/20260830_ggen_advance_settings_suspend_ui/ggen_advance_suspend_warning_ko_preview_20260830.png`

### 7.1 설정 화면 구현

foreground `0x08C70DF0`을 원본 위치에서 직접 수정하지 않고 expansion `0x01270000` / GBA `0x09270000`에 clone했다. 구현 중 원본 atlas를 다시 감사한 결과 `メッセージの自動送り`와 `メッセージ表示速度`가 `0x039..0x03E`, `0x047..0x04C` prefix tiles를 실제로 공유한다는 점을 확인했다. 따라서 source tile ID를 그대로 repaint하면 두 한국어 문구가 서로 덮어쓰게 된다.

이를 피하기 위해 네 대상 strip 모두 clone 안에서 **private tile detach**를 수행했다. 원본 131 tiles는 clone 안에서도 byte-exact로 보존하고, 대상 138 map cells에만 새 tile IDs `131..268`을 연속 할당했다. 최종 cloned atlas는 269 tiles이다. 원본 map의 비대상 cells 및 원본 resource 자체는 변하지 않는다.

적용 문구:

- `각종 설정을 합니다`
- `공격방법 확인`
- `메시지 자동 진행`
- `메시지 표시속도`
- `빠름`
- `느림`

고정 문구는 Galmuri11 native 12x12, face index 10 / contour index 5 / background index 11로 렌더했다. 속도 행의 중앙 x=139..197은 ON/OFF/1..4 선택 그래픽과의 충돌을 피하기 위해 원본 상태를 유지했다. 설정 전용 literal `0x08021050`만 `0x09270000`으로 redirect했으며 ON/OFF/1..4 option table과 footer 12x12 문자열 포인터는 byte-exact로 유지했다.

### 7.2 중단 경고 구현

shared sprite resource `0x08C7504C` 전체 12,164 bytes를 expansion `0x01274000` / GBA `0x09274000`으로 clone했다. 원본 shared resource와 나머지 네 소비처는 전혀 수정하지 않았고, 중단 함수의 literal `0x08020B98`만 clone을 보도록 변경했다.

animation 11의 마지막 세 OBJ가 차지하는 tiles `66..137`만 다시 구성했다. 외곽 2px은 원본을 보존하고 144x32 내부 scanline별 warm-panel background mode를 복구한 뒤 다음 두 줄을 Galmuri11 12x12로 렌더했다.

- `중단 처리 중입니다`
- `전원을 끄지 마세요`

clone의 animation/OAM header와 palette는 원본 byte-exact이고 변경 graphic tile은 `66..137` 72개에만 한정된다. 이 부분은 고정 문자열 포인터가 아니라 OBJ graphic 자체를 재구성한 첫 후보이므로, 실제 화면에서는 **황색 내부 패널의 그라데이션/경계가 자연스러운지와 갈색 글자 색/outline 인상**을 우선 실측한다.

### 7.3 정적 검증

최종 builder 재실행 결과 PASS이다.

- changed bytes: 21,025
- 설정 clone runtime parse: PASS
- 설정 original 131 clone tiles byte-exact: PASS
- 설정 대상 138 map cells private remap: PASS
- 설정 dynamic option/footer: unchanged
- 중단 clone runtime parse: PASS
- animation 11 OAM: unchanged
- 원본 shared suspend resource: unchanged
- 다른 4개 shared-resource consumer: unchanged
- Thumb instructions: 두 resource literal을 제외하고 unchanged
- 전체 변경 범위: 두 expansion clone + 두 32-bit literal 안으로 제한

main TIP에는 아직 승격하지 않았으며 실측 승인 전 후보 상태로 유지한다.

---

## 8. 실측 실패 원인 정정 및 follow-up 후보 (20260830)

1차 후보 `e33a6915...`를 실제 기기/에뮬레이터 화면에서 확인한 결과 두 구조 가설에 각각 다른 오류가 있음이 확인되었다. 설정 화면은 한글 라벨 자체는 정상이나 `ON/OFF`, `1/2/3/4` 조각이 라벨 영역을 침범했고, 중단 경고는 일본어 본문이 거의 그대로 남은 채 한글 조각만 좌측 프레임 부근에 잘못 나타났다. 따라서 1차 후보는 **실측 실패 / main TIP 미승격**으로 확정한다.

### 8.1 설정 화면: 269-tile clone의 VRAM ownership 충돌

설정 함수의 실제 runtime tile base를 다시 닫았다.

- fixed foreground load base: `0x08020F6A`의 `movs r2,#0xC9` -> runtime tile **0x0C9 (201)**
- dynamic option base: 초기 `0x0C9`에 `0xC8`을 더해 **0x191 (401)**
- 따라서 fixed foreground가 사용할 수 있는 최대 decoded tile 수는 `0x191 - 0x0C9 = 200 tiles`
- 원본 foreground: **131 tiles**, runtime `201..331`, 안전
- 1차 후보: **269 tiles**, runtime `201..469`, dynamic option 시작 `401`과 **69 tiles 중첩**

즉 private detach 자체가 잘못된 것이 아니라, 138개 대상 map cell을 모두 신규 tile `131..268`로 확장한 것이 option compositor의 VRAM 영역을 침범한 직접 원인이었다.

follow-up builder에서는 네 대상 strip을 먼저 독립 raster로 만든 뒤, map 전체 사용처를 감사하여 **비대상 cell이 전혀 참조하지 않는 원본 tile slot만 scratch로 재사용**한다. 렌더된 138 cell은 126개 unique payload로 정리되며 original slots `5..129` 안에서 모두 해결되어 **추가 tile 0개 / 최종 decoded tiles 131개**다. 비대상 map cell과 그들이 참조하는 tile payload는 byte-exact로 보존된다.

follow-up runtime 범위:

- foreground: `0x0C9 + 131 = 0x14C` exclusive
- option start: `0x191`
- 여유: `0x45 = 69 tiles`
- 따라서 ON/OFF / 속도 숫자 compositor와 **VRAM overlap 없음**

### 8.2 중단 경고: OAM destination tile과 ROM source tile을 혼동한 것이 원인

1차 분석의 가장 큰 오류는 animation 11 OAM `attr2`의 `66..137`을 resource 내부 source graphic tile ID로 해석한 것이다. 실제 resource format은 다음과 같다.

1. animation record 안의 OAM `attr2` = **OBJ VRAM destination tile ID**
2. OAM list 직후 별도 u16 table = **resource-local source graphic tile ID**
3. animation 11은 destination 138 tile 위치에 대응하는 source lookup **138 entries**를 가진다.

따라서 1차 후보가 resource graphics `66..137` 자체를 고쳐도 실제 경고문 source는 거의 바뀌지 않고, 그 source tiles를 쓰는 다른 그림 조각만 한글 파편으로 변한다. 실측의 "일본어 본문 유지 + 좌측 한글 조각"이 이 구조와 정확히 일치한다.

또한 문구 영역도 마지막 세 OBJ의 144x32가 전부가 아니었다. 실제 OAM geometry는 다음 8개 OBJ가 한 패널을 만든다.

- upper 32px: objects **9, 10, 11**
- lower 16px: objects **2, 3, 4, 5, 6**
- 합계: x `-60..84`, y `-24..24` = **144x48**
- icon/frame: objects 0/1
- right edge: objects 7/8

source lookup에서는 lower text가 `0x0D4..0x0E4`, upper text가 `0x0E5..0x105` 계열을 실제로 사용한다. 이 source-map 구조를 기준으로 두 줄 원문을 다시 조립하면 palette 역할도 명확해진다.

- glyph face: index **11**
- dark-brown contour: index **2**
- yellow panel fill: indices **9/10**

follow-up은 original shared resource나 original 262 source graphic tiles를 하나도 다시 쓰지 않는다. suspend 전용 clone 안에서 다음 방식으로 수정한다.

1. 원본 262 source tiles는 clone 안에서도 byte-exact 유지
2. 144x48의 text band만 재구성
3. 필요한 새 tile payload **53개**를 source IDs `262..314`로 append
4. animation 11의 target objects `2..6, 9..11` source lookup 108 entries 중 실제 필요한 **67 entries만** private source IDs로 remap
5. objects 0/1, 7/8 및 다른 animation source lookup은 유지
6. graphics가 늘어난 만큼 palette relative offset을 `0x2EC4 -> 0x3564`로 이동하고 palette bytes 자체는 byte-exact 유지
7. 원본 shared resource를 사용하는 나머지 네 consumer는 계속 `0x08C7504C`를 사용하고, suspend literal `0x08020B98`만 clone을 사용

한글 두 줄은 144x48 native panel 기준 y=10 / y=26에 배치했다.

- `중단 처리 중입니다`
- `전원을 끄지 마세요`

### 8.3 현재 main TIP 재기준화

작업을 재개하면서 canonical main TIP이 별도 승인 작업으로 이미 갱신되어 있음을 확인했다.

- 현재 main TIP SHA-256: `3e11caab45d1a1497b40498887926686fa37e2e726078fbf09a2bb3bf312e853`
- manifest promotion reason: `marker_clan_source_gated_restoration_20260830`
- 직전 `9fb0b509...` main TIP의 변경을 보존한 후속 승인본

따라서 builder/analyzer의 parent hash를 고정 문자열로 두지 않고, `integrated/main_tip/ggen_advance_main_tip_manifest.json`의 SHA와 실제 canonical ROM SHA가 일치하는지를 매 실행 시 gate하도록 변경했다. 설정/중단 대상 original resource와 두 literal이 아직 untouched인지도 별도로 gate하므로 unrelated main TIP 승격을 보존하면서 안전하게 재기준화할 수 있다.

### 8.4 follow-up 산출물

- analyzer: `tools/analyze_ggen_advance_settings_suspend_ui.py`
- static report: `analysis/ggen_advance_settings_suspend_ui_20260830.json`
- builder: `tools/build_ggen_advance_settings_suspend_ui_ko_poc.py`
- candidate: `outputs/20260830_ggen_advance_settings_suspend_ui/ggen_advance_settings_suspend_ui_ko_followup_candidate_20260830.gba`
- candidate SHA-256: `64ac3e7e83a2c02b7b108dafa3a6e4fafb32f6ee9ecc0dea44d47cd7b556de33`
- manifest: `analysis/ggen_advance_settings_suspend_ui_ko_followup_20260830.json`
- settings preview: `outputs/20260830_ggen_advance_settings_suspend_ui/ggen_advance_settings_ui_ko_followup_preview_20260830.png`
- suspend preview: `outputs/20260830_ggen_advance_settings_suspend_ui/ggen_advance_suspend_warning_ko_followup_preview_20260830.png`
- changed bytes vs current main TIP: `17,806`
- settings clone: `6,028 bytes`, decoded **131 tiles**
- suspend clone: `13,860 bytes`, original 262 source tiles + 53 private source tiles

최종 정적 검증은 PASS다. 변경은 expansion의 두 clone 및 settings/suspend 두 32-bit resource literal 범위에만 제한된다. 이 follow-up은 아직 main TIP에 승격하지 않았으며 **설정의 ON/OFF/숫자 침범 해소와 중단 경고의 실제 2행 한글 위치를 재실측해야 한다.**
