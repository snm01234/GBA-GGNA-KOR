# G Generation Advance main TIP ss1/ss2 그래픽 타일 후속 분석

기준 ROM은 canonical main TIP `SD Gundam GGeneration Advance (Korean).gba`이며 SHA-256은 `431a425a384f9f6a3f19447edd8a5bd9f28391404ea7b297fe42c43b4d5c4a1d`다. `ss1`, `ss2`의 내장 ROM CRC는 모두 main TIP의 `0x9DA433AD`와 일치한다. 이번 범위에서 `ss3`~`ss6`은 제외했다.

## 미완료 분석 정정

기존 `analyze_ggen_advance_remaining_ui_*_20260902.py`는 현재 세이브스테이트의 화면 번호와 대상 라벨이 어긋나 있었다. 특히 ss1/ss2 분석에 다른 화면 라벨이 들어가 있었으므로, 현재 PNG 프리뷰와 IWRAM/VRAM을 다시 기준으로 소유자를 결속했다.

## ss1

화면의 `搭載 / 降ろす / 移動 / 変形`은 OBJ 패키지 `0x08C3F130`이다. 패키지는 80개 원본 graphic tile과 13개 animation을 가지며, 실제 ss1에서 animation `0,1,2,3,4,11`이 resident 상태다.

- animation `0..3`: 일반 라벨
- animation `4..7`: 포커스 라벨
- animation `8..11`: 비활성 팔레트로 일반 graphic lookup을 재사용하지만 lookup table 자체는 독립

따라서 화면에 보인 일반 상태만 고치면 포커스 또는 비활성 상태에서 일본어가 다시 나타난다. 테스트 ROM은 `0..11`의 독립 lookup을 모두 `탑재 / 내리기 / 이동 / 변형`으로 교체했다. 원본 패키지는 보존하고 `0x092F0000`에 전용 clone을 만들었으며, 유일한 direct consumer `0x00066CE8`만 clone으로 돌렸다.

## ss2

후속 실측에서 이 영역은 긴 문구 두 줄이 아니라 `移動 / 限界 / 汎用 / 装甲`의 2행×2열 독립 라벨임이 확인됐다. 표시 그래픽은 현재 main TIP에 이미 존재하는 전용 패키지 clone `0x092D8000`의 animation 3이며, 네 라벨은 각각 32×16 raster cell이다.

- `移動` canvas `(128,24)-(160,40)` → `이동`
- `限界` canvas `(176,24)-(208,40)` → `한계`
- `汎用` canvas `(112,40)-(144,56)`, native glyph origin `(116,42)` → `범용`
- `装甲` canvas `(156,40)-(188,56)`, native glyph origin `(160,42)` → `장갑`
- direct consumers: `0x00072484`, `0x00072778`, `0x00072998`, `0x00072E08`

첫 후보의 `이동타입 / 현재소속` 72×16 덮어쓰기는 오독으로 폐기한다. v2는 공용 status atlas, 타일맵, 팔레트를 수정하지 않고 `0x092D8000` animation 3의 네 cell lookup과 새 private tile만 후보 ROM 안에서 재구성한다.

## 실측 피드백 반영 v2

- ss1 focus에서 원본 일본어 contour가 남은 원인은 focus contour가 palette index `1`인데 첫 후보가 `4`를 지운 것이었다. v2는 face `12`와 contour `1`을 모두 clear한 뒤 같은 native focus 색으로 다시 그린다.
- `변형` animation은 화면 x=208에 anchor되어 실제 가시 폭이 32px뿐이다. 첫 후보가 48px body 중앙에 한글을 배치해 오른쪽이 잘렸으므로, v2는 clear 범위는 유지하되 paint 범위를 local x=4..31로 제한해 24px 한글 전체가 보이게 한다.
- 첫 후보 ROM은 실측 오류 근거로 보존하며 승격 대상에서 제외한다.
- 추가 피드백에 따라 ss1은 팔레트값 일괄 clear를 폐기했다. 네 native 행의 동일 좌표를 교차 대조해 일본어 glyph/contour 아래의 공통 붉은 cap·dark label-bed 픽셀을 복원한 뒤, 원문 glyph origin `(7,2)`에 한글을 그린다.
- ss2의 최종 행·열은 `이동 | 한계` / `범용 | 장갑`이며, 각 한글 glyph origin을 원문 기준 `(cell x+3, cell y+2)`로 맞춘다.
- v3에서는 일본어 face/contour만 골라 지우는 방식을 중단했다. ss1은 blank body의 동일 scanline으로 label bed 전체를 재구성하고, ss2는 각 cell의 frame 안쪽 전체를 native body index로 초기화한다. 이 방식으로 팔레트 순환 시 점멸하던 제3 shadow layer까지 제거한다.

## 실측 피드백 반영 v4

- ss1의 glyph origin 왼쪽에 남은 1~2px shadow까지 제거하도록 재구성 시작점을 local x=4로 확장했다. red/orange 계열의 명확한 cap 픽셀은 원본을 유지하고, 나머지는 같은 animation의 blank body x=56 scanline으로 복원한다.
- ss2는 단색 사각형 fill을 폐기했다. 네 cell을 각각 같은 행의 무문자 위치에서 scanline 복사해 원래 프레임·그라데이션을 복원한다.
- ss2 실측 원문 origin은 `이동 (131,26)`, `한계 (179,26)`, `범용 (116,42)`, `장갑 (160,42)`다. 특히 범용/장갑은 v3보다 각각 15px/19px 왼쪽으로 보정한다.
- 같은 결함이 있던 개발 계열 private clone 네 종(`develop`, `dismantle_popup`, `supply`, `remodel_popup`)도 함께 재생성한다. `개조/강화/보급/처분` 및 같은 패키지 버튼은 외곽 3px와 상하 2px의 원본 red/orange/brown rim을 byte-exact 유지하고 내부 well만 정리한다.

## 실측 피드백 반영 v5

- ss1 `탑재/내리기/이동/변형` 계열은 v4 결과를 그대로 유지한다.
- ss2 `이동` cell의 scanline 복원 범위를 x=128..159 전체에서 실제 glyph/shadow 범위 x=130..156으로 축소해, 왼쪽 원본 cap/gradient 2px와 오른쪽 경계를 보존한다.
- 개발 메뉴는 inner well을 정리한 뒤에도 frame에 걸쳐 남던 일본어를 제거한다. face/contour와 2px 이내에 붙은 palette-index 4 shadow만 contaminated raster로 분류하고, 해당 외곽 픽셀은 같은 행의 가장 가까운 clean native gradient 픽셀로 복원한다. 따라서 독립된 brown frame 픽셀은 유지된다.

## 실측 피드백 반영 v6 (2026-09-03)

- ss1과 ss2 네 라벨의 배치 및 raster는 v5 결과를 그대로 유지한다.
- 개발 메뉴 버튼은 inner well 전체를 단색으로 초기화하지 않는다. 검출된 일본어 face/contour와 인접한 제3 shadow 픽셀만 선택적으로 복원한다.
- 복원색은 원본 버튼의 같은 scanline에 남아 있는 clean 배경에서 산출한다. 따라서 `개조`, `강화`, `캔슬`, 실행 버튼 등의 상하 음영과 좌우 round-cap gradient가 사각형으로 평탄화되지 않는다.

## 테스트 ROM과 검증

### v6 선택적 그라데이션 복원 후보

- ROM: `outputs/20260902_ggen_advance_ss1_ss2_graphics/ggen_advance_ss1_ss2_graphics_ko_test_v6_20260903.gba`
- SHA-256: `4b42cd2d6750687d78bfb0c0f2761a794f75a39eca4744b0c4809b1f019fcfed`
- 개발 메뉴 비교 프리뷰: `outputs/20260902_ggen_advance_ss1_ss2_graphics/ggen_advance_development_family_gradient_preview_v6_20260903.png`
- ss1/ss2 patch manifest는 v5와 동일하며 unified/development 회귀 테스트는 모두 PASS다.

### v7 48px 메뉴 구분선 복원 후보

- ROM: `outputs/20260902_ggen_advance_ss1_ss2_graphics/ggen_advance_ss1_ss2_graphics_ko_test_v7_20260903.gba`
- SHA-256: `573708bf97d82f3d0cf8169c79cde7627a479e9cb611b4e6b20b15aaf72b7e06`
- `개조/강화/보급/처분` 48px 버튼만 일본어 raster 추적 거리를 2px로 제한해 normal의 brown shading과 focus의 dark-blue separator를 보존한다.
- 64px 캔슬/실행 계열과 ss1/ss2는 v6 결과를 유지한다.

- ROM: `outputs/20260902_ggen_advance_ss1_ss2_graphics/ggen_advance_ss1_ss2_graphics_ko_test_20260902.gba`
- SHA-256: `2a355a377bdc7b4b1d3f6b5914743c7950f621270003b0eb431fa516d183c3ca`
- 변경 바이트: 7,248
- 정적 매니페스트: `analysis/ggen_advance_ss1_ss2_graphics_ko_test_20260902.json`
- 원본/한글 그래픽 프리뷰: `outputs/20260902_ggen_advance_ss1_ss2_graphics/ggen_advance_ss1_ss2_graphics_ko_preview_20260902.png`
- 기존 unified/development 회귀 테스트: 모두 PASS
- canonical main TIP: 변경 없음

정적 구조 검증은 PASS다. main TIP 승격 전 실제 화면에서 일반/포커스/비활성 전환, ss2 두 행의 배경 경계와 글자 잔상 여부를 확인해야 한다.

## v7 + ss5/ss6 v3 통합 승격 (2026-09-03)

- v7 SS1/SS2 및 개발 메뉴 그래픽과 `ggen_advance_remaining_ui_ss5_ss6_candidate_v3_20260903.gba`를 통합해 canonical main TIP에 반영했다.
- 두 후보가 공유하던 임시 클론 주소 충돌을 해소했다. SS6는 개발 메뉴와 공유하는 `0x092C8000` 리소스에 v3 animation 6 패치를 재적용했고, SS5 전용 클론은 `0x01F00000`으로 재배치한 뒤 `0x0006F074` 소비자 포인터를 갱신했다.
- canonical main TIP SHA-256: `5104ff7a16a3548031e874927230e3e30555bf08040773613f99c3f5dd634248`
- 이전 main TIP 백업: `integrated/main_tip/backups/20260902T152637Z_user_requested_v7_ss5_ss6_integration_20260903/`
- 통합 후보 매니페스트: `analysis/ggen_advance_v7_ss5_ss6_integrated_candidate_20260903.json`
