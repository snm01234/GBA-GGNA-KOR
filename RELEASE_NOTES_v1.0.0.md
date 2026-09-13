# v1.0.0

`v1.0.0`은 SD Gundam G Generation Advance 한국어 패치의 첫 공개 릴리스입니다.

현재 승인 메인 TIP(`SD Gundam GGeneration Advance (Korean).gba`)을 기준으로, 합법적으로 소유한 일본판 16 MiB 원본 ROM에 적용하는 xdelta를 배포합니다. 결과 ROM은 32 MiB이며, 원본 ROM 바이트는 패치 파일에 들어가지 않습니다.

## 배포 기준

- 메인 TIP SHA-256: `04447b928ebfc29ff33cd39aea9907f659da095279fa8ffcfc523b9ed329183e`
- xdelta: `outputs/dist/ggen_advance_ko_v1.0.0.xdelta`
- 승격 근거: 블루 데스티니 I 표기 반영 등 2026-09-13 승인 메인 TIP
- 라운드트립: 원본에 xdelta를 다시 적용하면 메인 TIP과 byte-exact

## 알림

이 저장소에는 원본 ROM, 한국어 메인 TIP, 세이브, 테스트 ROM이 포함되지 않습니다. 로컬 작업용 과거 백업과 POC 테스트 ROM은 `legacy/`에만 두고 Git에서는 제외합니다.

## Galmuri 폰트 라이선스

v1.0.0 한글 글리프는 Lee Minseo가 제작한 Galmuri 폰트 소프트웨어를 사용해 래스터했습니다. Galmuri는 **SIL Open Font License 1.1** 적용 대상이며 프로젝트 MIT License와 별개입니다. 폰트 바이너리는 공개 Git/Release asset에 포함하지 않습니다. 고지와 원문은 `NOTICE.md`, `docs/GALMURI_OFL.txt`를 참고하세요.

## 면책

이 패치는 비공식·비상업 팬 작업물이며, 법이 허용하는 범위에서 현 상태 그대로 제공됩니다. 자세한 권리 구분과 사용자 책임은 `LICENSE`, `NOTICE.md`, `docs/LEGAL_NOTICE.md`를 확인하세요.

