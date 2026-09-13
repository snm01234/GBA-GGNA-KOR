# Advance 승인 Main TIP

승인·플레이 기준 ROM의 고정 파일명은 프로젝트 루트의 `SD Gundam GGeneration Advance (Korean).gba`다. 이 파일은 Git에 올리지 않는다.

공개 배포물은 `outputs/dist/ggen_advance_ko_v1.0.0.xdelta`다. `ggen_advance_main_tip_manifest.json`은 현재 ROM의 SHA-256, 승격 근거 POC, 번역 정본, 릴리스 버전을 기록한다.

날짜별 POC ROM은 검토 후 `legacy/poc/outputs/`로 옮긴다. 이전 main TIP 스냅샷은 `legacy/main_tip_backups/`에 보존한다. 승인 시에만 `tools/promote_ggen_advance_main_tip.py`가 고정 main TIP을 갱신한다.

