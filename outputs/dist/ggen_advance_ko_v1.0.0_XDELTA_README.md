# ggen_advance_ko_v1.0.0 xdelta

**합법적으로 소유한 일본판 원본 16 MiB GBA ROM**에 적용하면 **32 MiB** 한국어 메인 TIP이 됩니다.

원본 16 MiB는 파일 앞쪽에 그대로 두고, 추가 16 MiB(`0x01000000–0x01FFFFFF`)에
한글 글꼴·텍스트를 붙입니다. xdelta3(VCDIFF)는 원본을 소스로 COPY하므로
원본 ROM 바이트는 패치 파일에 들어가지 않습니다.

## 입력

- 원본: `SD Gundam GGeneration Advance (Japan).gba` · 16 MiB · SHA-256 `75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772`
- 메인 TIP: `SD Gundam GGeneration Advance (Korean).gba` · 32 MiB · SHA-256 `04447b928ebfc29ff33cd39aea9907f659da095279fa8ffcfc523b9ed329183e`

## 패치

- 파일: `ggen_advance_ko_v1.0.0.xdelta`
- xdelta SHA-256: `92217ba98120a1f2c679ff19f7e2b570e68bfdb417a359d0def15a8f5265576f`
- 크기: **772492** bytes
- 원본 ROM 포함: **아니오** (`embeds_original_rom: false`)
- 16 MiB→32 MiB 라운드트립: **True**

## 적용

### GUI (Delta Patcher 등 xdelta3 프론트엔드)

1. 합법적으로 소유한 일본판 원본 16 MiB ROM 준비 및 백업
2. Original file = 원본 `.gba`, XDelta patch = `ggen_advance_ko_v1.0.0.xdelta`, Output = 새 32 MiB `.gba`
3. 결과 SHA-256이 `04447b928ebfc29ff33cd39aea9907f659da095279fa8ffcfc523b9ed329183e`인지 확인

xdelta **3.2 armor(BLAKE3)**, **VCDIFF secondary compression**,
**application header**를 모두 끄고 plain VCDIFF로 인코딩했습니다.

### CLI

```bash
python tools/apply_ggen_advance_main_tip_xdelta.py --original "SD Gundam GGeneration Advance (Japan).gba" --xdelta outputs/dist/ggen_advance_ko_v1.0.0.xdelta --out outputs/dist/ggen_advance_ko_from_xdelta.gba
```

또는:

```bash
xdelta3 -d -f -s "SD Gundam GGeneration Advance (Japan).gba" outputs/dist/ggen_advance_ko_v1.0.0.xdelta outputs/dist/ggen_advance_ko_from_xdelta.gba
```

