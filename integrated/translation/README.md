# Advance 번역 통합 정본

이 디렉터리는 `advance` 프로젝트의 활성 번역 통합경로다.

- 정본 JSON: `ggen_advance_translation_merged.json`
- 단일 검토·관리 workbook: `ggen_advance_translation_master.xlsx`
- QA 미리보기: `previews/`
- 정본 메타데이터: `ggen_advance_translation_manifest.json`

`analysis/`의 날짜별 병합 파일과 `outputs/`의 날짜별 시트는 historical snapshot이며, 새 승인 빌드의 번역 입력으로 직접 사용하지 않는다. 정본 JSON은 `tools/sync_ggen_advance_translation_master.py`, workbook은 `tools/build_ggen_advance_unified_translation_workbook.mjs`로 갱신한다.

모든 경로는 `D:\monoeye\advance`를 루트로 해석하며, 상위 프로젝트 폴더 참조를 금지한다.
