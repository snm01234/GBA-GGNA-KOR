# GBA 그래픽 캡처 준비

대사/문자 엔진을 읽지 않고, 실행 중 그래픽 메모리만 수집하기 위한 준비물이다.

## 준비 상태

- 원본 롬: `SD Gundam GGeneration Advance (Japan).gba`
- 원본 SHA-256: `75f362524e1278a77a6f165502f8363a943c8d23f69ecf518355ad8702483772`
- 에뮬레이터: `D:\monoeye\out\bizhawk_profile\EmuHawk.exe`
- 코어: BizHawk 2.11.1의 `mgba.dll`
- 메모리 도메인: VRAM, PALRAM, OAM, IWRAM, EWRAM, ROM, System Bus 확인 완료

## 기본 캡처

```powershell
python tools\run_gba_graphics_capture.py --tag original_graphics
```

`graphics_runtime_capture` 아래에 VRAM(0x18000), 팔레트(0x400), OAM(0x400),
작업 RAM 스냅샷과 화면 PNG, 실행 리포트가 생성된다. 현재 기본 실행은 4,200프레임의
결정적 입력 경로이며, 실행한 장면에서 실제로 사용된 그래픽 상태를 수집한다.

## 전달 경로 보조 추적

```powershell
python tools\run_gba_graphics_capture.py --frames 600 --bus-trace --tag graphics_bus_probe
```

`--bus-trace`는 VRAM·팔레트·OAM·DMA 레지스터에 대한 CPU 쓰기를 프레임별로 요약한다.
현재 mGBA 실행에서는 이벤트 등록은 성공했지만 콜백이 0건이어서, 이 결과를 “DMA가
없다”는 뜻으로 해석하지 않는다. 기본 스냅샷 캡처는 정상 동작하므로 이후 오프라인
분석은 스냅샷과 원본 롬을 기준으로 진행한다.

## 현재 생성된 기준 캡처

`original_graphics_baseline_runtime_report.json`에 원본 해시, 에뮬레이터 경로,
덤프 목록과 프레임별 실행 정보가 기록되어 있다. 기준 실행에서는 VRAM 1,115개,
팔레트 26개, OAM 492개, IWRAM/EWRAM 각 36개, 화면 36장을 확보했다.

전체 게임 그래픽을 빠짐없이 얻으려면 다음 단계에서 장면별 입력/세이브스테이트를
추가해 각 메뉴·전투·유닛·연출 상태를 순차적으로 캡처해야 한다.
