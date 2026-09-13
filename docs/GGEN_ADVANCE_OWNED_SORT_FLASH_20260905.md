# 소유수·정렬 전환 플래시 공통 수정 후보

사용자 실측: actual_paths 후보 `76685ae9...`에서 보급의 최종 소유수는 PASS.
보급/처분 진입 및 정렬 이름·배치중 등 커서 전환에는 일본어 플래시가 남음.

공통 프레임 훅 `0x08063194 -> 0x09F20000`의 기존 실행 순서는
`1322C -> 13544 -> 1928 -> 정렬 한글 보정`이다.
`1928 -> 85054`는 `swi 5`(VBlankIntrWait)를 실행한다.
소유수 보정도 이 전체 호출이 반환된 뒤 실행되므로 두 보정 모두 프레임
대기 뒤에 놓여 있다. 이는 전환 원본 타일이 보정 전 표시될 수 있는 경계다.

이번 후보는 정렬 보정 뒤 모든 gate 통과/탈락 경로가 새 tail로 모이게 하고,
거기서 순수 소유수 보정 후 기존 1928을 한 번 호출한다. 순수 소유수 helper는
기존 helper를 재배치하되 내부 63194 호출만 NOP 처리하여 재귀를 방지한다.
정렬/소유수 gate와 번역 payload는 그대로 보존한다.

- 빌더: `tools/build_ggen_advance_owned_sort_pre_wait_20260905.py`
- ROM: `outputs/20260905_ggen_advance_owned_sort_pre_wait/ggen_advance_owned_sort_pre_wait_candidate_20260905.gba`
- SHA-256: `3f05793cb1a32c940c0889c11bd7b5dfaef02a5127b3ad0e95b06ff4b084a442`
- 분석: `analysis/ggen_advance_owned_sort_pre_wait_candidate_20260905.json`
- 정적 검증 PASS, 전환 실측 PENDING, 메인 미승격.

실측은 동봉 SAV로 새 부팅 후 보급/처분 진입, 커서 이동, 정렬 다섯 항목의
normal/focus 전환을 확인한다. IRQ에서 이후 다시 쓰는지 또는 최초 표시 전에
gate가 성립하는지는 아직 계측되지 않았으므로 무플래시를 확정하지 않는다.

과거 설명 정정: `0300177C == 2`는 취소 입력 대기이며 전송 완료 조건이 아니다.
`D350/CFC4`를 所有数 생산자로 확정한 근거는 없으며 해당 훅 후보들은 실측 FAIL.
`C4654C anim 8`과 플래크 크롬의 일부 타일 일치도 글자 생산자 확정 근거가 아니다.
