# 일본식 계급명 한국식 계급명 통일

현재 기본 한글 ROM과 통합 번역 데이터를 대상으로 계급명을 점검했다. 원문 슬롯을 확인한 결과 `E1 F4 E4 29`(12×12 슬롯 `0x02D4`+`0x0509`)를 쓰는 맵 대사 5곳은 기존 데이터의 `艦長` 표기가 잘못된 것이며 실제 원문은 `伍長`이다. 이 다섯 곳의 `함장`을 모두 `하사`로 바꿨다.

확인된 대상은 다음과 같다.

- `GGA-MAPSCRIPT-00F52035` 모린 하사의 셔틀로
- `GGA-MAPSCRIPT-00F52F5E` 키타무라 하사
- `GGA-MAPSCRIPT-00F6DED6` 우몬 하사는?
- `GGA-MAPSCRIPT-00F75A1E` 와이즈먼 하사,어떻게된거지?
- `GGA-MAPSCRIPT-00F75A90` 와이즈먼 하사,

일반 계급명 전수 대조에서 발견된 추가 오역도 함께 수정했다. `GGA-MAPSCRIPT-00FA7BE5`와 `GGA-MAPSCRIPT-00F87FAC`의 `少佐`를 `소령`으로, `GGA-TEXT-0017C64D`의 `大佐が`를 문법에 맞춰 `대령이`로 바꿨다. 계급 대응은 `伍長→하사`, `軍曹→중사`, `曹長→상사`, `兵長→병장`, `上等兵→상병`, `一等兵→일병`, `二等兵→이병`, `准尉→준위`, `少尉→소위`, `中尉→중위`, `大尉→대위`, `少佐→소령`, `中佐→중령`, `大佐→대령`, `准将→준장`, `少将→소장`, `中将→중장`, `大将→대장`, `元帥→원수`로 적용했다. 기존 통합 데이터의 `軍曹` 6곳도 후속 계급 대응 점검에서 `중사`로 바로잡았다. 실제 함장인 다른 `艦長` 표기는 유지했다. 실제 함장 문자열은 별도 슬롯 `E1 1D E4 29`를 사용한다.

맵 스크립트와 생산 텍스트의 기존 NUL payload를 먼저 현재 32MiB ROM에서 재인코딩해 일치 여부를 확인한 뒤, 길이가 같은 payload 22바이트만 교체했다. 두 개씩 존재하는 맵 lookup 사본도 모두 같은 주소를 가리키는지 검사했다. 이어서 `軍曹` 6곳(샌더스·군조 호칭)을 `중사`로 교체한 후속 후보에서 payload 12바이트를 추가 교체했다. 원본 맵 스크립트 뱅크와 포인터, 헤더, SAV는 보존했다. 에뮬레이터 실행 검증은 수행하지 않았고 정적 ROM·폰트·payload 검증을 통과했다.

빌더: `tools/patch_ggen_advance_rank_terms_20260908.py`, `tools/patch_ggen_advance_rank_equivalents_20260908.py`

후보 및 검증 리포트: `outputs/20260908_ggen_advance_rank_terms/manifest.json`, `outputs/20260908_ggen_advance_rank_equivalents/manifest.json`

번역 스냅샷: `analysis/ggen_advance_translation_merged_20260908_rank_terms.json`
