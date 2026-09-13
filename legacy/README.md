# Legacy local archive

이 폴더는 공개 GitHub 저장소에 올리지 않는 로컬 아카이브입니다.

v1.0.0 동결 시 아래를 옮겼습니다.

- `legacy/main_tip_backups/` — 승격 직전 메인 TIP 스냅샷
- `legacy/poc/outputs/` — 날짜별 POC·테스트 ROM과 캡처
- `legacy/dist/` — 버전 없는 구 xdelta (`ggen_advance_ko_main_tip.*`)
- `legacy/analysis/` — 이전 분석 스냅샷, 그리고 최신 메인 TIP에 포함되지 않은 `ggen_advance_translation_merged_*.json`

`savebackup/` 은 레거시가 아닙니다. 로컬 플레이 세이브 폴더로 루트에 유지하며 Git에는 올리지 않습니다.

기록 파일:

- `legacy_asset_manifest.json` — 카테고리 요약
- `MOVE_LOG_20260913_v1_0_0_public_freeze.json` — 백업·POC 이동 로그
- `MOVE_LOG_20260913_translation_merged_cleanup.json` — 번역 병합 스냅샷 정리

현재 공개 배포 기준은 `outputs/dist/ggen_advance_ko_v1.0.0.xdelta` 입니다.
현재 analysis에 남긴 번역 스냅샷은 `ggen_advance_translation_merged_20260913_blue_destiny.json` 하나뿐입니다.
