# 한글패치 적용 가이드

이 문서는 **v1.0.0** `ggen_advance_ko_v1.0.0.xdelta`를 원본 GBA ROM에 적용하는 방법을 설명합니다.

## 1. 준비물

- **합법적으로 소유한 일본판 원본 ROM**: `SD Gundam GGeneration Advance (Japan).gba`
- 패치 파일: `outputs/dist/ggen_advance_ko_v1.0.0.xdelta`
- xdelta 패치를 적용할 프로그램
  - GUI: Delta Patcher 등 xdelta3 호환 프론트엔드
  - CLI: xdelta3, 또는 이 저장소의 `tools/apply_ggen_advance_main_tip_xdelta.py`

패치 파일에는 원본 ROM이 포함되어 있지 않습니다.

## 2. 원본 ROM 확인

지원하는 원본은 **16 MiB (16,777,216 bytes)** 입니다.

SHA-256:

`75F362524E1278A77A6F165502F8363A943C8D23F69ECF518355AD8702483772`

Windows PowerShell에서는 다음처럼 확인할 수 있습니다.

```powershell
Get-FileHash ".\SD Gundam GGeneration Advance (Japan).gba" -Algorithm SHA256
```

값이 다르면 다른 덤프/수정본일 가능성이 있으므로 그대로 패치하지 않는 것을 권장합니다.

## 3. GUI로 적용

Delta Patcher/xdeltaUI 계열 프로그램에서는 보통 다음과 같이 지정합니다. 현재 배포 xdelta는 구버전 호환을 위해 VCDIFF secondary compression(LZMA)과 application header를 사용하지 않습니다.

- **Original file / Source**: **합법적으로 소유한 일본판 원본 `.gba`**
- **XDelta patch**: `ggen_advance_ko_v1.0.0.xdelta`
- **Output file**: 새 파일 이름의 `.gba`

원본 파일 자체를 덮어쓰기보다 새 출력 파일을 만드는 것을 권장합니다.

## 4. CLI로 적용

저장소 루트에서:

```bash
python tools/apply_ggen_advance_main_tip_xdelta.py --original "SD Gundam GGeneration Advance (Japan).gba" --xdelta outputs/dist/ggen_advance_ko_v1.0.0.xdelta --out "SD Gundam GGeneration Advance (Korean).gba"
```

또는 xdelta3 직접 호출:

```bash
xdelta3 -d -f -s "SD Gundam GGeneration Advance (Japan).gba" outputs/dist/ggen_advance_ko_v1.0.0.xdelta "SD Gundam GGeneration Advance (Korean).gba"
```

## 5. 결과 확인

적용이 끝나면 출력 파일은 **32 MiB (33,554,432 bytes)** 여야 합니다.

SHA-256:

`04447B928EBFC29FF33CD39AEA9907F659DA095279FA8FFCFC523B9ED329183E`

```powershell
Get-FileHash ".\SD Gundam GGeneration Advance (Korean).gba" -Algorithm SHA256
```

해시가 다르면 원본이 다르거나, 이미 패치된 파일에 다시 적용했거나, 다른 프론트엔드 옵션이 섞인 경우가 많습니다. 원본을 다시 확인하고 새 출력 파일로 재적용하세요.

## 6. 라이선스와 면책

이 패치는 비공식·비상업 팬 작업물입니다. 자체 작성 코드·문서는 [`LICENSE`](LICENSE)의 MIT License를 따르고, 한글 글리프에 사용한 Galmuri 폰트는 SIL Open Font License 1.1을 따릅니다. 원 게임 ROM·상표·원문에 대한 이용 허락은 부여하지 않습니다.

자세한 범위는 [`NOTICE.md`](NOTICE.md)와 [`docs/LEGAL_NOTICE.md`](docs/LEGAL_NOTICE.md)를 확인하세요.
