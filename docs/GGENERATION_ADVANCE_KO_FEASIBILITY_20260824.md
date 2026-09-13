# SD Gundam G Generation Advance 한국어 패치 타당성 조사

조사일: 2026-08-24  
대상: 로컬 `advance/SD Gundam GGeneration Advance (Japan).gba`  
결론: **한국어 패치 가능. 기술 난도는 중상이며 Mono-Eye Gundams WSC 패치의 단순 포팅은 불가능하다.**

현재 구현/검증 상태 요약: [`GGENERATION_ADVANCE_KO_PROGRESS.md`](GGENERATION_ADVANCE_KO_PROGRESS.md)

이 문서는 상세 기술 근거와 조사 히스토리를 유지하고, 위 progress 문서는 현재 production 기준값과 다음 작업 순서를 요약한다.

운영 경계: 이 문서 및 `advance/docs` 하위 문서가 참조하는 현재 프로젝트 경계는 `D:\monoeye\advance`다. 활성 빌드·데이터·문서는 상위 `D:\monoeye` 폴더를 참조하지 않으며, Main TIP·POC 정리·단일 번역 통합경로 규칙은 위 progress 문서 §23을 따른다.

## 1. ROM 식별과 무결성

| 항목 | 값 |
|---|---|
| 크기 | 16,777,216 bytes (16 MiB) |
| GBA title | `GGENE A` |
| game code | `BGAJ` |
| maker code | `B2` |
| CRC32 | `7DAF215C` |
| MD5 | `275EA9783E76AF29846CC3EE5675C62A` |
| SHA-256 | `75F362524E1278A77A6F165502F8363A943C8D23F69ECF518355AD8702483772` |
| ARM entry | `0x080000C0` (`EA00002E`) |
| header complement | 저장 `02`, 계산 `02`, 정상 |
| save library signature | `EEPROM_V124` at file `0x00FCD61C` |

원본 ROM은 조사 중 변경하지 않았다. `advance/` 전체는 `.gitignore` 대상이다.

## 2. 텍스트 인코딩과 사전

Shift-JIS(CP932) 및 UTF-16LE로 `ガンダム`, `アムロ`, `シャア`, `攻撃`, `セーブ` 등 대표 문자열을 검색했으나 일치 항목이 없었다. 텍스트는 게임 전용 인코딩을 사용한다.

Thumb 코드로 확인한 실제 파서는 다음과 같다.

- `0x0800118C`: `00`을 종료로 처리한다.
- `01–DF`: 1바이트 글자 코드다.
- `E0–FF`: 다음 바이트를 읽어 16비트 토큰을 만든다.
- `E000–EFFF`: 글자 토큰이다. 내부 글리프 슬롯 `00E0–10DF`로 정규화한다.
- `F000–FFFF`: 사전 토큰이다. 파서는 16비트 오프셋 테이블을 통해 대상 문자열을 찾은 뒤 `0x0800118C`를 다시 호출할 수 있는 재귀 구조다.
- 실제 사전 테이블은 모드별로 `0x08093850`, `0x080A42A8`에 있으며 각각 **319개** 엔트리다.
- 실제 사용 사전 토큰 범위는 `F000–F13E`다.
- 다만 원본 ROM의 319개 사전 엔트리를 전수 해석한 결과 **사전 엔트리 내부의 `Fxxx` 참조는 0건**이다. 즉 엔진은 재귀를 지원하지만 현재 기본 사전은 모두 literal glyph만 포함하는 1단계 치환이다.

이 구조는 WSC판의 1/2바이트 글자와 사전 토큰 개념에 가깝지만 코드·주소·사전 형식은 별개다.

### 정적으로 확인된 텍스트 규모

연속 ROM 포인터가 NUL 종료 토큰 스트림의 정확한 다음 시작점을 가리키는 조건으로 보수적으로 선별했다.

- 신뢰도 높은 packed text table: **456개**
- 고유 문자열 시작점: **2,948개**
- 토큰 스트림 합계(종료 NUL 포함): **57,843 bytes**
- 평균 문자열 크기: **19.62 bytes**
- 고유 literal glyph code: **1,284개**
- 사용된 사전 토큰: **231개**
- 확인된 최대 글자 토큰: `E703`
- 문자열 대부분은 file `0x0017xxxx–0x0018xxxx`에 밀집한다.

이는 packed pointer table만 센 하한값이다. 이벤트 명령 안에 직접 들어간 문자열, 이미지형 문구, 비연속 테이블은 추가 조사 대상이다.

### 확인된 호출 관계

초기 pointer-run 휴리스틱에서는 `0x00FCE2D8`과 `0x00FCDF78` 주변을 각각 200/202-entry 문자열 테이블로 보았으나, 후속 R3 dataflow와 strict token 검증에서 이 해석은 **폐기**했다. 두 주소는 서로 다른 구조가 연속 배치된 heterogeneous 영역이다.

현재 direct indexed text owner로 정적으로 확정한 범위는 다음과 같다.

- `0x001C92E8`: 114 entries
- `0x00FCDF78`: direct draw가 접근하는 prefix 13 entries (`0–12`)
- `0x00FCE128`: 22 entries (`FCDF78`의 물리 offset 108에 있으나 별도 owner/domain)
- `0x00FCE2A8`: 12 physical slots 중 10 text entries (`2`, `11`은 NULL)
- `0x00FCE2D8`: 69 pointer fields. 과거에는 23×3으로 물리 grouping했지만, 2026-08-26 재분석에서 runtime은 byte index 기반 **flat lookup + adjacent pair**로 접근함을 확인했다. physical entry 69부터는 adjacent code-pointer data
- `0x08000CA0`: 공통 텍스트 출력 래퍼
- `0x08000648`, `0x0800072C`: 문자열 구성/포맷 경로
- `0x0800118C`, `0x080011BC`: 글자·사전 토큰 파서

따라서 텍스트 추출기, 사전 재작성기, 포인터 재배치기와 렌더러 후킹 지점을 모두 정적으로 구축할 수 있다. 다만 **연속 ROM pointer run 자체는 text table 확정 근거로 사용하지 않는다.**

## 3. 글꼴과 렌더러

두 개의 독립 글꼴 경로가 존재한다.

| 용도 | ROM 주소 | 형식 | 슬롯 | 렌더 함수 |
|---|---:|---|---:|---:|
| 큰 글꼴 | `0x0808AC40` | 12×12, 1bpp, 18 bytes/glyph | 1,992 | `0x08001354` |
| 작은 글꼴 | `0x08094028` | 8×16, 2bpp, 32 bytes/glyph | 2,068 | `0x08001298` |

- 12×12 글꼴은 `0x08093850` 사전 블록 직전까지 정확히 1,992 슬롯이다.
- 8×16 글꼴은 `0x080A42A8` 사전 블록 직전까지 정확히 2,068 슬롯이다.
- 실제 글꼴을 두 형식으로 렌더링해 영문·가나·한자 글리프가 정상적으로 확인됐다.
- 한국어판은 동일한 글자 매핑으로 **두 글꼴을 모두** 생성해야 한다.

번역문에 등장하는 한글 음절만 선별하면 약 2천 슬롯 안에서 해결될 가능성이 높다. 슬롯이 부족하면 ROM 확장 영역에 한글 글꼴 페이지를 추가하고 두 렌더 함수에 확장 페이지 분기를 넣어야 한다.

## 4. ROM 공간과 재배치

- file `0x00FCED40–0x00FFFFFF`는 연속 `FF` **201,408 bytes**다.
- 직전에는 라이브러리 포인터 테이블과 0/FF 경계가 명확하다.
- 정확한 시작 주소 `0x08FCED40`을 가리키는 32비트 포인터는 ROM에서 발견되지 않았다.
- 이 구간은 코드 cave, 새 포인터 테이블, 작은 글꼴/사전 POC를 위한 유력 후보지만 런타임 검증 전에는 확정 free space로 간주하지 않는다.

필요하면 16 MiB ROM 뒤에 데이터를 붙여 32 MiB로 확장할 수 있다. GBA의 평면 ROM 주소에서는 appended file `0x01000000`이 `0x09000000`이 되므로 WSC처럼 ROM 앞에 8 MiB를 삽입하거나 뱅크 스위칭을 유지할 필요가 없다. 새 주소는 Thumb 코드에서 literal load + `bx`/함수 포인터로 접근하는 편이 안전하다.

## 5. 압축 조사

표준 GBA BIOS LZ77/RLE 헤더 후보를 구조적으로 검사했으나 확정 가능한 블록은 없었다. RLE처럼 끝까지 해석되는 후보를 4bpp 타일로 렌더링했을 때 모두 정상 그래픽이 아니어서 거짓 양성으로 판정했다.

- 텍스트: 압축 파일이 아니라 포인터 기반 토큰 스트림과 재귀 사전으로 확인
- 글꼴: ROM에서 직접 읽는 raw 12×12 1bpp / 8×16 2bpp 테이블로 확인
- 기타 UI 이미지: 게임 전용 포맷 또는 별도 패킹 가능성이 있어 추가 조사 필요

## 6. 선행 패치 증거

Advance汉化组이 이 게임의 중국어 패치를 완성했다. 제작팀 공지에는 프로그램, 글꼴, 번역, 테스트 담당이 명시되어 있고, 2025년 공지 기준 v2.0에서 EEPROM 저장 형식까지 수정했다고 설명한다.

- [Advance汉化组 v2.0 배포 공지](https://www.bilibili.com/opus/1105317577462120454)

이는 글꼴 교체, 전체 텍스트 재배치, 이미지 수정, 저장 호환성까지 실제 하드웨어 계열에서 해결 가능함을 보여주는 강한 선행 증거다. 공개 빌드 소스나 기술 문서는 찾지 못했다.

## 7. WSC 패치에서 재사용 가능한 것

| 구성 | 재사용성 | 비고 |
|---|---|---|
| 번역 데이터 구조·용어집·문맥 리뷰 | 높음 | 게임별 원문 추출 후 동일 QA 방식 적용 가능 |
| Galmuri 기반 비트맵 생성 | 중간 | 출력 패커를 12×12 1bpp/8×16 2bpp로 새로 작성 |
| TBL/사전/폭 감사 개념 | 중간 | GBA 코드 체계와 319-entry 사전에 맞춰 재구현 |
| ROM 입출력·포인터 재배치 | 낮음 | WSC bank/segment 대신 `0x08000000` 32비트 포인터 사용 |
| 런타임 후킹 코드 | 없음 | x86 계열 WSC 코드를 ARM7TDMI Thumb로 새로 작성 |
| BizHawk/Oswan 검증 | 없음 | mGBA 디버거·스크립트·세이브 회귀 테스트 필요 |

## 8. 주요 위험

1. 12×12와 8×16 두 글꼴 경로를 모두 맞춰야 한다.
2. `F000–F13E` 재귀 사전을 정확히 재구축하지 않으면 문자열 길이와 포인터가 깨진다.
3. 240×160 화면의 메뉴 폭·줄바꿈·이름 칸을 별도로 감사해야 한다.
4. 일부 문구가 이미지에 포함되어 있어 타일 그래픽 수정이 필요할 수 있다.
5. 원본은 `EEPROM_V124`를 사용하므로 에뮬레이터뿐 아니라 EEPROM save/load 회귀 검증이 필요하다.
6. 같은 게임의 중국어 패치가 저장 형식을 별도로 수정했다는 점은 flashcart/VC 환경 차이를 초기에 시험해야 함을 뜻한다.

## 9. 권장 1차 POC

1. mGBA 디버거에서 원본 부팅·메뉴·대사·EEPROM 저장 기준선을 만든다.
2. 319-entry 사전과 두 글꼴의 정확한 charmap을 추출한다.
3. 사용 빈도가 낮은 글리프 슬롯 10–20개에 한글을 넣어 12×12/8×16 두 글꼴을 동시에 교체한다.
4. `0x00FCE2D8` 포인터 테이블의 메뉴 문자열 하나와 `0x0017xxxx–0x0018xxxx` 대사 하나를 한국어로 교체한다.
5. 부팅, 메뉴, 전투 전후 대사, 저장/불러오기를 확인한다.
6. POC가 통과하면 32 MiB append 확장, 전체 추출/삽입, BPS/xdelta 배포 파이프라인으로 확장한다.

중국어 **패치 파일 또는 사용자가 합법적으로 생성한 중국어 패치 적용본**을 추가 입력으로 확보하면 원본과의 바이너리 diff를 통해 렌더러 후킹, 새 글꼴 배치, 이미지 수정, EEPROM 대응 지점을 빠르게 역추적할 수 있다. ROM 자체를 공개 저장소에 넣지는 않는다.

## 10. mGBA 코어 한글 출력 POC 결과

결과: **PASS**. 저장소에 포함된 BizHawk 2.11.1의 GBA 코어 `dll/mgba.dll`로 후보 ROM을 실행해 첫 대사 화면에서 한글 비트맵이 실제로 출력되는 것을 확인했다.

### 생성물과 재현 도구

- `tools/build_ggen_advance_ko_poc.py`: 원본 SHA-256을 확인한 뒤 별도 POC ROM을 만든다.
- `tools/bizhawk_ggen_advance_ko_poc.lua`: 타이틀부터 새 게임 첫 대사까지 3,601프레임을 자동 진행하고 120프레임마다 캡처한다.
- `tools/run_ggen_advance_ko_poc.py`: 원본/후보를 동일 입력으로 실행하고 프레임 2,041 대조 이미지와 JSON 보고서를 만든다.
- ROM·매니페스트·캡처는 Git에 들어가지 않는 `advance/poc/` 아래에 생성된다.

POC에는 두 단계가 들어 있다.

1. `E6D0–E6D3`를 내부 슬롯 `07B0–07B3`에 대응시켜 두 글꼴에 `한글출력` 네 글리프를 넣었다.
2. 첫 대사에서 즉시 보이도록 `--broad-runtime-aliases` 모드는 공유 렌더 슬롯 `0001–07C7`을 반복 한글 패턴으로 임시 치환한다. 이는 실행 가시성만 위한 것이며 번역 데이터가 아니다.

### 실행 증거

| 항목 | 결과 |
|---|---|
| 프런트엔드 | BizHawk 2.11.1 |
| GBA 코어 | `out/bizhawk_profile/dll/mgba.dll` |
| 코어 SHA-256 | `BA398A56E62CE1E4280FE96834CBBE4E6469B7070F34DA313EC3D4637C4979E1` |
| Lua 시스템 로그 | `SYSTEM=GBA` |
| 후보 SHA-256 | `9F6A46E0524CAB154BD2FEF596DDEC8E8313C46B1CF152C578905C9A2C658A8F` |
| 후보 SHA-1 / 에뮬레이터 ROM hash | `95ADCD08CEBE65F75996CCAD71E0D62D67EE2DF1` / 일치 |
| 자동 진행 | 3,601 frames, 정상 종료 |
| 한글 확인 프레임 | 2,041 |
| 원본 대비 변경 픽셀 | 769 / 38,400 |
| 차이 bounding box | `(8, 114)–(143, 156)` — 화자명·대사 텍스트 영역 |

대조 이미지에서 배경과 인물 이미지는 동일하고 화자명·대사만 일본어에서 한글 비트맵으로 바뀐다. 따라서 ARM 텍스트 파서가 한글용 슬롯을 선택하고, GBA 런타임 렌더러가 Galmuri 기반 픽셀을 화면에 그리는 전체 경로가 확인됐다.

이 POC가 증명하지 않는 범위는 전체 번역, 자연스러운 한글 charmap, 폭/줄바꿈, 두 글꼴 모드 각각의 모든 UI, EEPROM 저장 회귀다. 다음 단계는 broad alias를 제거하고 실제 메뉴·대사 포인터만 `한글출력` 문자열로 재배치하는 최소 패치다.

## 11. 후속 정적 분석: 텍스트 엔진 확정 구조

POC 이후 실제 번역기/삽입기 구현에 필요한 부분을 Thumb 코드와 원본 데이터로 추가 검증했다.

### 11.1 토큰 디코더의 정확한 산식

`0x0800118C`는 NUL까지 토큰 스트림을 순회한다. `01–DF`는 그대로 16비트 내부 슬롯으로 넘기고, `E0–FF`는 다음 바이트와 결합한 16비트 토큰으로 `0x080011BC`에 전달한다.

`0x080011BC`에서 확인된 두 핵심 산식은 다음과 같다.

```text
E000–EFFF literal glyph:
    slot = (token + 0x20E0) & 0xFFFF

F000–FFFF dictionary token:
    index = token - 0xF000
    relative = u16(dictionary_base + index * 2)
    entry = dictionary_base + relative
```

사전 엔트리는 다시 `0x0800118C`에 전달되므로 코드상 재귀 확장이 가능하다. 하지만 원본의 두 319-entry 사전을 전수 검사한 결과 실제 사전 엔트리 안에는 `Fxxx` 토큰이 하나도 없었다. 따라서 현 ROM에서 실제 최대 사전 확장 깊이는 **1단계**다.

### 11.2 모드 선택과 메모리 레이아웃

텍스트 객체 `+0x64`의 최하위 비트가 두 글꼴/사전 모드를 선택한다. 관련 포인터는 다음과 같이 짝을 이룬다.

| 모드 | 글꼴 | 사전 | config | 출력 함수 | 문자 진행폭 |
|---|---:|---:|---:|---:|---:|
| bit 0 = 0 | `0x08094028` 8×16 2bpp | `0x080A42A8` | `0x080A4A2C` | `0x08001298` | 8 px |
| bit 0 = 1 | `0x0808AC40` 12×12 1bpp | `0x08093850` | `0x08093FD8` | `0x08001354` | 12 px |

ROM의 모드 포인터 테이블도 직접 확인했다.

- file `0x00D53D3C`: `0x080A4A2C`, `0x08093FD8` — config 포인터
- file `0x00D53D44`: `0x080A42A8`, `0x08093850` — dictionary 포인터
- `0x08001238`: 모드 비트에 따라 8 px / 12 px 렌더러를 선택

실제 연속 배치는 다음과 같다.

```text
0x0008AC40  12x12 font, 1992 * 18 bytes
0x00093850  12x12 dictionary, 0x788 bytes
0x00093FD8  12x12 config, 0x50 bytes
0x00094028  8x16 font, 2068 * 32 bytes
0x000A42A8  8x16 dictionary, 0x784 bytes
0x000A4A2C  8x16 config
```

글꼴 시작 주소는 각각 코드 내 literal로 한 곳에서 직접 참조되고, 사전/config는 위 모드 포인터 테이블을 통해 간접 참조된다.

### 11.3 319-entry 사전 전수 검사

두 사전의 첫 halfword는 모두 `0x027E`다. 이 값은 payload 시작까지의 상대 오프셋이면서 동시에 `638 / 2 = 319`로 엔트리 수를 결정한다. 앞의 638 bytes는 단조 증가하는 `u16` 상대 오프셋 테이블이고 뒤에 NUL 종료 토큰 문자열 319개가 연속 배치된다.

| 항목 | 8×16 사전 | 12×12 사전 |
|---|---:|---:|
| 엔트리 | 319 | 319 |
| offset table | 638 B | 638 B |
| payload 공간 | 1,286 B | 1,290 B |
| 실제 엔트리 합계 | 1,284 B | 1,288 B |
| 사전 내부 `Fxxx` 참조 | 0 | 0 |
| 고유 literal glyph slot | 265 | 265 |
| 한 엔트리 최대 글자 수 | 7 | 7 |

두 모드 사전은 **raw token sequence가 같은 엔트리가 0/319**로, 단순 복제본이 아니다. 반면 대응 엔트리의 표시 글자 수는 **319/319 전부 동일**하다.

더 중요한 점은 대응 엔트리 안의 같은 글자 위치 864곳을 서로 매칭했을 때 다음 결과가 나온다는 것이다.

- 관측된 8×16 glyph slot: 265개
- 관측된 12×12 glyph slot: 265개
- 8×16 → 12×12 매핑 충돌: **0**
- 12×12 → 8×16 역매핑 충돌: **0**
- 따라서 사전만으로 확보한 모드 간 glyph slot bijection: **265개**

즉 두 모드는 문자 의미는 같지만 서로 다른 내부 slot 번호를 사용하는 charmap이다. 이 265개 대응표는 일본어 charmap 복구와 두 폰트 동시 한글화에 직접 사용할 수 있다.

재현용 read-only 분석기는 Git 추적 가능한 `tools/analyze_ggen_advance_dictionary.py`와 `tools/analyze_ggen_advance_text_engine.py`에 두었다. 전자는 319-entry 사전과 265-slot bijection을, 후자는 모드 포인터·renderer special slot·format jump table·Thumb BL 호출처·확정 text pointer table xref를 재검증한다. 둘 다 원본 ROM을 변경하지 않는다. 분석 작업 폴더 `advance/`에도 동일한 로컬 사본이 있으나 해당 폴더 전체는 `.gitignore` 대상이다. 필요하면 다음과 같이 JSON을 출력할 수 있다.

```powershell
python tools/analyze_ggen_advance_dictionary.py `
  "advance/SD Gundam GGeneration Advance (Japan).gba" `
  --out "advance/dictionary_analysis.json"

python tools/analyze_ggen_advance_text_engine.py `
  "advance/SD Gundam GGeneration Advance (Japan).gba" `
  --out "advance/text_engine_analysis.json"
```

### 11.4 8×16 렌더러의 특수 슬롯

`0x08001298`은 일반 glyph를 `font_base + slot * 32`에서 읽기 전에 config 값 일부를 비교하여 별도 렌더 경로로 보낸다. 정적으로 확인된 8×16 특수 비교 필드는 다음과 같다.

| config offset | slot |
|---:|---:|
| `+0x2C` | `0x07FB` |
| `+0x2E` | `0x07F8` |
| `+0x30` | `0x07FC` |
| `+0x32` | `0x07FD` |
| `+0x36` | `0x07FE` |
| `+0x4C` | `0x0813` |

8×16 글꼴의 전체 슬롯은 `0x0000–0x0813`이므로 이 값들은 대부분 테이블 끝부분에 있다. **한글 글리프를 빈 슬롯처럼 보이는 후반부에 무작정 덮어쓰면 안 된다.** 실제 한글 charmap 할당기는 renderer-special slot과 config-reserved slot을 제외해야 한다.

### 11.5 `0x0800072C`는 일반 텍스트가 아닌 format descriptor 경로

`0x0800072C`는 `0x20–0x78` 범위 바이트를 89-entry jump table로 분기한다. 하지만 실제 jump target은 7개뿐이다.

- 대부분의 코드: no-op/default 경로
- `0x20`, `0x25`, `0x2F`, `0x78`: config에서 특정 내부 glyph/special 값을 삽입
- `0x43`: 가변인자에서 16비트 token을 받아 `0x080011BC`에 전달
- `0x53`: 포인터 인자를 받아 `0x0800118C`로 NUL token stream을 삽입
- `0x2B`, `0x42`, `0x44`, `0x46`, `0x50`, `0x53`, `0x54`, `0x58` 계열: 숫자/문자열/폭 등의 가변인자를 해석하는 공통 formatting 경로

따라서 이 함수가 참조하는 데이터는 일반 dialogue string과 동일한 규칙으로 직접 번역하면 안 된다. 추출기에서는 최소한 `plain token stream`과 `format descriptor`를 별도 레코드 타입으로 나누어 보존해야 한다.

### 11.6 주요 함수의 정적 호출 규모

Thumb `BL`을 ROM 전체에서 역추적한 결과는 다음과 같다.

| 함수 | 역할 | 직접 `BL` 호출처 |
|---|---|---:|
| `0x08000648` | 일반 token stream 구성 | 50 |
| `0x0800072C` | format descriptor 구성 | 3 |
| `0x08000CA0` | 공통 텍스트 draw wrapper | 196 |
| `0x0800118C` | NUL token stream parser | 12 |
| `0x080011BC` | 단일 token/dictionary dispatch | 2 |
| `0x08001238` | 모드별 렌더 loop | 2 |
| `0x08001298` | 8×16 renderer | 1 |
| `0x08001354` | 12×12 renderer | 1 |

이 수치는 직접 `BL`만 센 것이며 함수 포인터/간접 호출은 포함하지 않는다. 그래도 `0x08000CA0` 호출처 196곳을 역분류하면 UI·도감·대사·전투 텍스트의 실제 source table을 체계적으로 확장할 수 있다.

### 11.7 POC pointer-run 해석의 후속 교정

POC에서 `0x08FCE2D8`, `0x08FCDF78`이 실제 draw 코드에서 참조되는 것은 맞다. 그러나 초기 분석은 **그 주소 뒤의 연속 ROM pointer 전체를 동일 text table로 간주한 점이 잘못**이었다.

원인은 기존 parser가 `E0–FF` lead 뒤의 임의 2-byte 값을 구조적으로 허용하고 NUL까지만 도달하면 문자열처럼 판정했기 때문이다. 이 규칙으로는 Thumb 코드도 우연히 NUL-terminated token stream처럼 보일 수 있다. 실제로 `FCE2D8` 후반의 code target에서 runtime dictionary 범위를 벗어난 `F766`, `FC20`, `FE00` 등이 검출됐다.

후속 strict gate는 다음만 text token으로 허용한다.

- single-byte glyph: `01–DF`
- extended literal: `E000–E733` (`E733` → 8×16 font 마지막 slot `0813`)
- dictionary: `F000–F13E` (실제 319-entry 사전)

코드의 index 생성식까지 추적한 최종 direct indexed owner는:

- `FCE2D8`: **69 pointer fields**. historical 23×3은 물리 grouping일 뿐이며 runtime은 flat byte-index lookup + adjacent pair를 사용한다. entry 69부터 adjacent code-pointer table
- `FCDF78`: `0x080603CA` 경로에서 **indices 0–12**. 같은 UI가 index field `+0x25`를 modulo 13으로 갱신
- `FCE128`: **22 entries**, `0x08064D38`이 `0–10`을 만들고 caller가 조건부로 `+11`
- `FCE2A8`: **12 physical slots / 10 text entries**, indices `2`, `11`은 NULL

따라서 이 문서에서 과거의 `FCE2D8=200 text`, `FCDF78=202 text` 수치는 모두 **superseded**로 본다. POC 자체가 해당 주소의 text path를 증명한 사실과, 물리 run 전체가 text라는 가정은 분리해야 한다.

## 12. 전체 한글화용 추출/삽입 설계

현재까지의 정적 근거로 보면 가장 안전한 1차 전체 번역 구조는 다음과 같다.

1. **plain token stream 추출**
   - pointer source, target offset, raw bytes, token list, terminator를 모두 보존한다.
   - 원문 복원 전에도 raw round-trip이 100% 가능해야 한다.
2. **format descriptor 분리**
   - `0x0800072C` 경로는 일반 텍스트와 별도 schema로 저장한다.
   - 가변인자 소비 개수와 token/string 삽입 opcode를 보존한다.
3. **원문 charmap 복구**
   - 8×16/12×12 atlas에서 실제 일본어 Unicode를 복구한다.
   - 사전에서 얻은 265-slot bijection을 seed/검증표로 사용한다.
4. **한글 charmap은 두 모드에서 의미를 통일**
   - 동일 한글 문자가 8×16/12×12에서 각각 대응하는 안전 slot을 갖도록 allocator를 만든다.
   - renderer/config reserved slot은 제외한다.
5. **한국어 번역문은 초기에 사전 재압축을 하지 않는다.**
   - 한국어 문자열은 가능한 한 literal glyph token만 사용해 새 영역으로 relocate한다.
   - 원본 `F000–F13E` 사전은 그대로 두어 기존 미번역/시스템 텍스트의 호환성을 유지한다.
   - ROM 여유가 충분하므로 정확성이 확보된 뒤에만 한국어용 사전 최적화를 고려한다.
6. **포인터 소스별 재배치**
   - 32-bit ROM pointer table은 새 문자열 주소로 갱신한다.
   - 이벤트 명령 내부 포인터/inline token stream은 별도 탐지 후 처리한다.
7. **정적 round-trip gate**
   - 번역을 적용하지 않은 상태에서 `extract → rebuild` 결과가 원본과 동일한지 먼저 검증한다.
   - pointer count, terminator, format arg count, glyph slot 범위, reserved slot 침범을 자동 감사한다.

이 방식이면 WSC 작업에서 문제가 되었던 제어코드 오판정·후행 레코드 침범을 초기에 구조적으로 차단할 수 있다.

## 13. 남은 정적 분석 우선순위

현재 시점에서 실제 번역 투입 전에 남은 핵심은 다음 순서가 적절하다.

1. **일본어 charmap 전수 복구**: 실제 사용 literal slot → Unicode 대응표 생성.
2. **`0x08000CA0` 196개 호출처 분류**: UI/도감/유닛명/인물명/대사/전투문구 source table 지도 작성.
3. **plain text table 전수 확정**: 기존 456개 packed 후보를 code xref와 교차해 신뢰도 등급화.
4. **inline/event text 탐지**: pointer table 밖의 token stream이 이벤트 바이트코드 안에 직접 들어가는지 조사.
5. **format descriptor opcode 완전 명세**: 현재 구조가 잡힌 `0x0800072C`의 7개 handler를 인자 단위로 명명.
6. **free-space 검증**: `0x00FCED40–0x00FFFFFF` 전체를 즉시 free로 확정하지 말고 코드 참조·런타임 접근을 추가 확인. 필요하면 32 MiB append 방식으로 회피.
7. **폭/줄바꿈 규칙 분석**: 8 px/12 px 고정 진행 외에 메뉴별 clipping, 행 수, 자동 줄바꿈 여부를 호출처별로 기록.

현재까지의 결론은 **한글 표시 가능성뿐 아니라 전체 추출·재삽입 파이프라인도 정적으로 구현 가능한 구조가 충분히 확인되었다**는 것이다. 가장 큰 남은 작업은 암호화/압축 해제보다 charmap과 문맥별 source table 분류다.

## 14. ROM 용량·번역 데이터 규모·32 MiB 확장 검토

재현용 분석기는 `tools/analyze_ggen_advance_capacity.py`에 추가했다. 원본 ROM을 변경하지 않고 현재 16 MiB 내부의 00/FF 연속구간, 텍스트 후보군의 실제 raw 크기와 사전 확장 후 표시 글자 수, 두 글꼴의 크기, 한국어 literal-token 저장 시나리오를 계산한다.

```powershell
python tools/analyze_ggen_advance_capacity.py `
  "advance/SD Gundam GGeneration Advance (Japan).gba" `
  --reference-ko-dir data
```

### 14.1 현재 16 MiB ROM의 여유공간

정적으로 가장 신뢰할 수 있는 연속 후보 공간은 ROM 끝의 다음 구간이다.

| 구간 | 크기 | 내용 | 판정 |
|---|---:|---|---|
| `0x00FCED40–0x00FFFFFF` | **201,408 B / 196.688 KiB** | 전부 `FF` | 강한 free-space 후보 |

ROM 전체에서 256 bytes 이상 이어지는 `00/FF` run은 350개, 합계 494,732 bytes다. 그러나 끝의 201,408-byte `FF` run을 제외하면 데이터 중간에 삽입된 0 padding이 대부분이다.

- embedded run 중 1 KiB 이상: 39개 / 합계 144,617 B
- embedded run 중 4 KiB 이상: 8개 / 합계 93,563 B

이 embedded padding은 소유 구조를 확인하기 전에는 번역용 공간으로 계산하지 않는다. 즉 **16 MiB 유지안을 검토할 때 확실한 예산은 약 196.7 KiB만 잡는 것이 안전하다.**

### 14.2 현재 확인된 번역 대상 텍스트 규모

아직 `0x08000CA0` 호출처를 대사/UI/도감/인명 등으로 완전히 분류하지 않았으므로 아래 수치는 순수 '대사 수'가 아니라 **엔진 텍스트 전체 후보량**이다.

| 범위 | 문자열 | 현재 raw | 사전 확장 후 표시 unit | 현재 길이를 전부 2-byte literal로 저장 |
|---|---:|---:|---:|---:|
| 고신뢰 packed 하한 | 2,948 | 57,843 B | 44,364 | 91,676 B |
| candidate table 내부 | 7,831 | 122,002 B | 94,568 | 196,967 B |
| 모든 pointer-run 비어있지 않은 후보 | **8,012** | **129,644 B** | **100,597** | **209,206 B** |

8,012-string 범위에는 원본 사전 토큰이 12,211회 들어 있고, 2-byte literal token이 17,171회, 1-byte token이 62,868회 사용된다. 원본은 사전과 1-byte charmap 덕분에 동일 표시 길이를 모두 2-byte literal로 저장하는 경우보다 약 38% 작다.

한국어 번역 길이를 원문의 표시 unit 대비 0.8×/1.0×/1.2×/1.4×로 가정하고 모든 한국어 문자를 2-byte extended glyph로 보수적으로 저장하면 8,012-string 범위는 다음과 같다.

| 한국어 표시 길이 가정 | 예상 문자열 공간 |
|---:|---:|
| 0.8× | 175,110 B |
| 1.0× | **209,206 B** |
| 1.2× | 257,622 B |
| 1.4× | 298,134 B |

따라서 **아무 압축도 하지 않고 모든 한글을 2바이트로 쓰는 전체 번역은 1.0× 길이부터 196.7 KiB tail을 텍스트만으로 약 7.8 KiB 초과한다.**

고신뢰 2,948-string 범위만 보면 1.0×가 91,676 B이므로 16 MiB에서도 충분하지만, 이것은 전체 번역량의 하한일 뿐이다.

### 14.3 글꼴이 차지하는 공간

현재 ROM의 두 폰트는 다음 크기다.

| 폰트 | 슬롯 | bytes/glyph | 전체 크기 |
|---|---:|---:|---:|
| 12×12 1bpp | 1,992 | 18 | 35,856 B |
| 8×16 2bpp | 2,068 | 32 | 66,176 B |
| 합계 | - | - | **102,032 B** |

같은 한글 한 글자를 두 모드에 추가 저장하면 `18 + 32 = 50 bytes`가 필요하다.

| 추가 한글 glyph | 두 폰트 추가량 |
|---:|---:|
| 1,000 | 50,000 B |
| 1,200 | 60,000 B |
| 1,500 | 75,000 B |
| 1,800 | 90,000 B |
| 1,990 | 99,500 B |

기존 일본어 슬롯을 재할당하면 폰트 **ROM 증가량은 0**이다. 반대로 원본 폰트를 보존한 채 새 한글 페이지를 추가하면 위 공간이 추가로 필요하다.

현 WSC 프로젝트의 `data/**/*_ko.json` 107개를 참고용으로 스캔하면 역사적/중간 번역까지 포함해 한글 음절 종류가 **1,007개**다. 따라서 Advance 번역도 비슷한 어휘 분포라면 1,200개 정도의 한글 음절 슬롯은 현실적인 초기 예산이다. 단, 실제 Advance 최종 번역문이 나오면 반드시 다시 계산한다.

### 14.4 1-byte 한글 charmap을 쓰면 16 MiB도 기술적으로 가능

이 엔진은 plain token stream에서 `01–DF`를 1-byte glyph로 사용할 수 있어 최대 223개 1-byte slot을 활용할 수 있다. 모든 한글을 무조건 2-byte `Exxx`로 저장할 필요는 없다.

WSC 참고 corpus의 한글 빈도는 다음과 같다.

| 상위 한글 음절 | 한글 출현 커버리지 |
|---:|---:|
| 100 | 67.67% |
| 150 | 77.44% |
| 180 | **81.50%** |
| 200 | 83.69% |
| 223 | 85.75% |

예를 들어 180개 slot을 빈도 높은 한글에 쓰고 나머지 43개 1-byte code를 공백·숫자·문장부호·특수문자 보존에 남기는 모델을 적용하면, 8,012-string / 원문과 동일 표시 길이의 한국어 텍스트는 빈도 투영상 약 **127,224 B**까지 줄어든다. tail에는 폰트 전 기준 약 74,184 B가 남는다.

150개 한글만 1-byte로 쓰는 더 보수적인 모델도 약 131,303 B로 계산된다. 따라서 다음 조합은 16 MiB에서도 가능성이 있다.

- 기존 두 폰트 슬롯을 대규모 재사용해 폰트 증가량을 0에 가깝게 유지
- 빈도 높은 한글 150~180개를 1-byte code에 배치
- 나머지 한글은 `E000–EFFF` 2-byte token 사용
- 필요하면 한국어 사전으로 추가 압축
- 기존 문자열 영역도 안전한 범위에서 재활용

하지만 이는 **'공간을 맞추기 위한 인코딩 최적화'가 패치 구조를 강하게 제약하는 설계**다. 향후 미확인 텍스트, 이미지형 한글화, 디버그 데이터, 포인터/테이블 사본, 정렬 padding이 추가되면 다시 공간을 쪼개야 한다.

### 14.5 사전의 공간 영향

현재 원본 두 사전의 합계는 **3,852 B**에 불과하다. 초기 한글화에서는 원본 사전을 그대로 두고 한국어를 literal token으로 출력하면 사전 때문에 추가 공간이 들지 않는다.

한국어용 319-entry 사전을 두 모드에 새로 만든다고 가정해도 평균 엔트리 길이에 따른 크기는 다음 수준이다.

| 평균 사전 문자열 | 두 모드 합계 |
|---:|---:|
| 3 glyph | 5,742 B |
| 4 glyph | 7,018 B |
| 5 glyph | 8,294 B |
| 6 glyph | 9,570 B |

따라서 사전 자체는 32 MiB 확장의 결정 요인이 아니다. 주요 용량은 **전체 번역 문자열 + 한글 폰트 + 이후 이미지/그래픽 데이터**다.

### 14.6 32 MiB append 방식의 정적 적합성

16 MiB ROM 뒤에 16 MiB를 append하면 새 file offset `0x01000000`은 GBA ROM 주소 **`0x09000000`**이 되고 마지막은 `0x09FFFFFF`가 된다.

이 주소 모델은 mGBA의 현재 공개 소스(`include/mgba/internal/gba/memory.h`)와도 일치한다. 해당 구현은 `GBA_BASE_ROM0 = 0x08000000`, `GBA_BASE_ROM0_EX = 0x09000000`, `GBA_SIZE_ROM0 = 0x02000000`으로 정의한다. 즉 `0x08000000–0x09FFFFFF`를 하나의 32 MiB Game Pak ROM0 창으로 다루는 설계다. 다만 프로젝트가 실제 사용하는 BizHawk 2.11.1 번들 mGBA core에서의 동작은 아래 runtime trace로 별도 확정한다.

현재 확인된 텍스트 엔진은 이 방식과 잘 맞는다.

1. **텍스트 포인터**
   - 확인된 테이블은 32-bit absolute ROM pointer를 저장한다.
   - lookup한 주소를 `r3`로 그대로 `0x08000CA0`에 넘긴다.
   - parser는 전달된 포인터를 직접 순회하므로 새 문자열을 `0x09000000+`에 두고 포인터만 수정하는 구조가 가능하다.
2. **사전**
   - file `0x00D53D44`의 모드 테이블은 두 dictionary base를 32-bit pointer로 보관한다.
   - 따라서 새 사전 전체를 확장 영역에 복사하고 이 두 포인터만 새 주소로 교체할 수 있다.
3. **config**
   - file `0x00D53D3C`도 32-bit config pointer 두 개를 가진다.
4. **폰트**
   - 8×16 base `0x08094028`의 직접 literal은 file `0x00001350` 한 곳에서 확인됐다.
   - 12×12 base `0x0808AC40`의 직접 literal은 file `0x00001388` 한 곳에서 확인됐다.
   - 현재와 같은 slot 수/형식을 유지한 새 폰트 전체를 확장 영역으로 옮기는 경우 이 두 32-bit literal을 새 `0x09xxxxxx` 주소로 바꾸는 설계가 가능하다.
   - 기존보다 slot 수 자체를 늘리는 경우에는 별도의 범위/인덱스 분석이 추가로 필요하다.

즉 WSC의 bank 확장처럼 복잡한 뱅크 관리가 필요한 구조가 아니라, **텍스트·사전은 absolute pointer relocation, 폰트는 base literal 교체**로 분리할 수 있다.

### 14.7 16 MiB와 32 MiB 비교

| 항목 | 16 MiB 유지 | 32 MiB 확장 |
|---|---|---|
| 강한 신규 연속공간 | 196.7 KiB | **+16 MiB** |
| 전체 text 1.0× / 모두 2-byte | 안 맞음(약 7.8 KiB 초과) | 충분 |
| 1-byte 빈도 최적화 | 필요성이 높음 | 선택 사항 |
| 기존 font slot 재사용 | 사실상 권장 | 불필요, 원본 보존 가능 |
| 한국어 dictionary | 공간 절약을 위해 유용 | 후순위 최적화 가능 |
| 이미지/추가 데이터 여유 | 작음 | 매우 큼 |
| 구현 복잡성 | 공간 allocator/압축이 복잡 | pointer relocation이 단순 |
| 디버깅/회귀 | 변경 영역이 분산될 수 있음 | 새 영역으로 격리 가능 |

매우 보수적인 32 MiB 예산으로 다음을 동시에 잡아도:

- 8,012-string 한국어 길이 1.4×, 모두 2-byte: 298,134 B
- 새 한글 glyph 1,990개를 두 폰트에 추가: 99,500 B
- 319-entry 한국어 사전 2종, 평균 6 glyph: 9,570 B

합계는 **407,204 B**, 추가된 16 MiB의 약 **2.43%**에 불과하다. 약 **16,370,012 B (약 15.61 MiB)**가 계속 남는다.

### 14.8 권장 결정

**배포용 메인 설계는 32 MiB 확장을 권장한다.**

16 MiB 유지도 기술적으로는 가능성이 높다. 특히 1-byte 빈도 charmap + 기존 폰트 slot 재사용 + 한국어 사전 압축을 결합하면 현재 추정 텍스트는 들어갈 수 있다. 그러나 그 장점은 최종 ROM이 16 MiB라는 것뿐이고, 대신 charmap·사전·free-space allocator가 번역 초기부터 용량 제약을 받는다.

반대로 32 MiB는 텍스트를 우선 **압축하지 않은 명확한 레코드 단위**로 배치하고 원본 포인터를 새 영역으로 옮길 수 있다. 원본 일본어 폰트와 사전을 그대로 보존한 상태에서 새 한글 폰트/사전을 별도 블록으로 만들 수 있어 디버깅과 rollback도 쉽다. WSC 패치에서 경험한 레코드 침범·공간 압박 문제를 피하기에도 이 방식이 유리하다.

다음 검증 단계는 **32 MiB minimal relocation POC**다. 원본 뒤에 `FF` 16 MiB를 append한 뒤, 코드에서 실제 호출이 확인된 문자열 하나를 `0x09000000+`에 두고 기존 pointer 하나만 변경하여 BizHawk/mGBA에서 출력되는지 확인한다. 그 다음 dictionary base와 두 font base도 각각 확장 영역으로 옮기는 독립 POC를 만들면 32 MiB를 production layout으로 확정할 수 있다.

## 15. 32 MiB relocation POC 구현 상태

용량 검토 후 실제 production layout을 검증하기 위한 32 MiB POC 도구를 추가했다.

- `tools/build_ggen_advance_32m_relocation_poc.py`
- `tools/bizhawk_ggen_advance_32m_relocation.lua`
- `tools/run_ggen_advance_32m_relocation_poc.py`

빌더는 원본 16 MiB를 직접 수정하지 않고 메모리에서 32 MiB로 확장한다. `--dry-run`에서는 파일을 쓰지 않고 전체 후보를 구성한 뒤 relocation을 정적으로 검증할 수 있다.

### 15.1 확장 영역 POC layout

현재 POC의 deterministic layout은 다음과 같다.

| 객체 | file offset | GBA address | 크기 |
|---|---:|---:|---:|
| root marker | `0x01000000` | `0x09000000` | 3 또는 9 B |
| 8×16 dictionary | `0x01000100` | `0x09000100` | 1,924 B |
| 12×12 dictionary | `0x01000900` | `0x09000900` | 1,928 B |
| 12×12 font | `0x01002000` | `0x09002000` | 35,856 B |
| 8×16 font | `0x0100B000` | `0x0900B000` | 66,176 B |

POC에서는 가독성과 디버깅을 위해 객체 사이에 의도적으로 충분한 alignment/gap을 둔다. production allocator에서는 이 위치를 고정 ABI로 취급할 필요는 없다.

### 15.2 세 단계 격리 검증

빌더는 `text`, `dict`, `full` 세 단계를 제공한다.

#### `text`

- ROM을 정확히 32 MiB로 확장
- file `0x01000000` / address `0x09000000`에 literal `한글출력` marker 저장
- bytes: `E6 D0 E6 D1 E6 D2 E6 D3 00`
- 당시 주소창 접근성 stress-test를 위해 `0x00FCE2D8` 뒤 200 slots와 `0x00FCDF78` 뒤 202 slots를 marker로 일괄 redirect. **후속 strict 분석 결과 이 두 물리 run 전체가 text라는 가정은 폐기했으며, 이 동작은 production extractor가 아니라 초기 broad POC에만 해당한다.**
- marker에 필요한 기존 font slot `07B0–07B3`만 원본 폰트에서 POC 한글 glyph로 교체
- dictionary/font base는 원본 주소 유지

이 단계는 **32 MiB 후반부의 plain token stream을 parser가 직접 읽는지**만 분리 검증한다.

#### `dict`

`text`의 확장 구조에 다음을 추가한다.

- 두 319-entry dictionary를 확장 영역으로 복사
- `0x00D53D44`를 다음으로 변경
  - 8×16: `0x09000100`
  - 12×12: `0x09000900`
- root marker는 literal marker가 아니라 `F1 3E 00`, 즉 dictionary token **`F13E`** 하나로 변경

`F13E`를 선택한 이유는 두 원본 dictionary 모두 마지막 entry index 318의 고정 span이 **10 bytes**이기 때문이다.

- 8×16 `F13E` entry relative offset: `0x077A`
- 12×12 `F13E` entry relative offset: `0x077E`
- 두 entry 모두 span: 10 B
- `한글출력` literal payload: 9 B

따라서 확장 dictionary 사본의 `F13E` entry 안에 `E6 D0 E6 D1 E6 D2 E6 D3 00`을 넣고 남는 1 byte만 NUL로 유지할 수 있다. 다른 entry offset을 움직이지 않는다.

실행 경로는 다음과 같이 강제된다.

`0x09000000` root → `F13E` → relocated dictionary → `한글출력` literal tokens

따라서 이 단계가 통과하면 단순히 `0x09xxxxxx` 문자열만 읽은 것이 아니라 **dictionary base relocation과 dictionary-relative entry lookup까지 실제 실행**된 것이다.

#### `full`

`dict`에 다음을 추가한다.

- 12×12 전체 폰트를 `0x09002000`으로 복사
- 8×16 전체 폰트를 `0x0900B000`으로 복사
- 한글 POC glyph는 확장 폰트 사본의 slot `07B0–07B3`에만 기록
- 원본 font bytes는 그대로 보존
- file `0x00001388`의 12×12 base literal → `0x09002000`
- file `0x00001350`의 8×16 base literal → `0x0900B000`

실행 경로는 최종적으로 다음이 된다.

`0x09000000` root → `F13E` → `0x09000xxx` dictionary → literal glyph token → `0x0900xxxx` font

즉 `full`은 **text + dictionary + font의 세 종류 absolute/base relocation을 한 번에 통과하는 production-layout 축소판**이다.

### 15.3 현재 정적 검증 결과

세 단계 모두 `--dry-run` 전체 구성/검증을 통과했다.

| stage | output | marker | dictionary relocated | font relocated | static |
|---|---:|---|---|---|---|
| `text` | 32 MiB | literal 9 B | 아니오 | 아니오 | PASS |
| `dict` | 32 MiB | `F13E 00` 3 B | 예 | 아니오 | PASS |
| `full` | 32 MiB | `F13E 00` 3 B | 예 | 예 | PASS |

정적 verifier는 다음을 검사한다.

- 정확히 `33,554,432 B`인지
- root marker가 `0x09000000`에 존재하는지
- 초기 broad POC가 의도적으로 patch한 두 physical pointer-run의 402 slots가 모두 새 marker address인지
- dictionary 사본 및 `F13E` replacement가 예상 위치/길이인지
- `0x00D53D44`의 dictionary base pointer가 새 주소인지
- `full`에서 두 font base literal이 새 주소인지
- `full`에서 **원본 두 font 영역이 byte-identical**인지
- marker glyph slot `07B0–07B3`가 실제 사용 font base에 존재하는지
- GBA header `0xA0–0xBF`가 원본과 동일한지

`full` dry-run에서 원본 16 MiB 쪽의 실제 changed byte는 **1,623 B**뿐이다. 변경 원인은 두 font-base literal 8 B, dictionary-base table 8 B, 그리고 두 text pointer table의 새 주소값이다. 새 payload 때문에 원본 데이터 블록을 덮는 영역은 없다.

또한 기존 강한 tail 후보 `0x00FCED40–0x00FFFFFF`는 `full`에서도 **원본과 byte-identical**하다. 즉 32 MiB 설계를 택하면 기존 196.7 KiB tail을 번역 데이터 저장소로 소비하지 않고 비상/호환 영역으로 그대로 남겨둘 수 있다.

현재 POC의 append payload가 차지하는 최고 file offset은 `0x0101B280`으로, append 시작점에서 **111,232 B (108.625 KiB)** 범위 안에 marker + 두 사전 + 두 전체 폰트가 모두 들어간다. 나머지 추가 영역은 계속 `FF`로 남는다.

현재 구현의 정적 dry-run SHA-256은 다음과 같다.

- `text`: `2030951b286fe11d5edae1647761aa3c833ea7738d07726ec304f6034ebb0230`
- `dict`: `3a048f5af50808eef576bdbe9f98a3486375336c6dc4a89912b72ab5d09092ee`
- `full`: `89798853d1ff0abfe032a36a9ce439ee7072c9871d753e429c143e5e13bf9910`

이 값은 현재 POC 구현의 재현성 확인용이며, layout이나 probe payload가 바뀌면 새 manifest의 SHA-256을 canonical 값으로 사용한다.

### 15.4 런타임 검증은 화면 비교보다 주소 실행을 직접 추적

기존 Korean-display POC처럼 화면에 한글이 보이는지만 확인하면, 기존 font alias가 우연히 보인 것인지 `0x09000000+` data를 실제 읽은 것인지 구분하기 어렵다.

새 Lua trace는 다음 CPU 지점을 직접 관찰한다.

1. parser `0x0800118C`
   - `R1 == 0x09000000` → `EXPANDED_TEXT_HIT`
2. recursive parser `0x0800118C`
   - `R1 == 0x0900087A` → relocated 8×16 `F13E` entry
   - `R1 == 0x0900107E` → relocated 12×12 `F13E` entry
   - 둘 중 하나 → `EXPANDED_DICT_ENTRY_HIT`
3. 8×16 renderer 내부 `0x08001322`
   - `R4`가 `0x0900B000–0x0901B27F` 안이면 `EXPANDED_FONT8_HIT`
4. 12×12 renderer 내부 `0x080013A2`
   - `R6`가 `0x09002000–0x0900AC0F` 안이면 `EXPANDED_FONT12_HIT`

POC별 PASS 조건은 다음과 같다.

- `text`: expanded text root hit 필수
- `dict`: expanded text root + relocated dictionary entry hit 필수
- `full`: expanded text root + relocated dictionary entry + relocated font range hit 필수

따라서 `full` PASS는 **mGBA가 32 MiB ROM을 부팅했다**는 수준을 넘어, 게임의 원래 text engine이 `0x09xxxxxx`의 문자열/사전/폰트 데이터를 실제로 소비했다는 직접 증거가 된다.

### 15.5 재현 명령

정적 write-free 검증:

```powershell
python tools/build_ggen_advance_32m_relocation_poc.py `
  "advance/SD Gundam GGeneration Advance (Japan).gba" `
  --font-zip assets/fonts/Galmuri.zip `
  --stage full `
  --dry-run
```

실제 `full` 후보 생성:

```powershell
python tools/build_ggen_advance_32m_relocation_poc.py `
  "advance/SD Gundam GGeneration Advance (Japan).gba" `
  --font-zip assets/fonts/Galmuri.zip `
  --stage full `
  --out "advance/poc/SD Gundam GGeneration Advance (32M Full Relocation POC).gba" `
  --manifest "advance/poc/ggen_advance_32m_full_relocation_poc.json"
```

BizHawk 2.11.1 / mGBA runtime trace:

```powershell
python tools/run_ggen_advance_32m_relocation_poc.py `
  --candidate "advance/poc/SD Gundam GGeneration Advance (32M Full Relocation POC).gba" `
  --stage full `
  --out-dir "advance/poc/mgba_runtime_32m_full" `
  --manifest "advance/poc/ggen_advance_32m_full_relocation_poc.json"
```

`text`와 `dict`도 `--stage`와 출력 파일명만 바꾸어 동일하게 독립 검증한다.

### 15.6 production 판단 기준

`full` runtime trace가 PASS하면 **32 MiB 확장 자체를 더 이상 실험적 우회책으로 취급하지 않고 production 기본 layout으로 승격**하는 것이 적절하다.

그 이후 구현은 다음 원칙으로 진행할 수 있다.

- 원본 16 MiB는 가능한 한 pointer/base patch와 최소 hook만 둔다.
- 번역문, 한글 dictionary, 한글 font, 향후 그래픽 자산은 `0x09000000+` allocator가 관리한다.
- 한국어 text는 초기에는 압축하지 않고 명확한 NUL token stream 단위로 배치한다.
- charmap/폭/문맥 구조가 확정된 뒤에만 1-byte 빈도 최적화나 한국어 dictionary 압축을 적용한다.
- production 빌더는 source offset, new offset, pointer source, encoded bytes, terminator를 manifest에 기록한다.

이 구조에서는 앞서 계산한 0.4 MiB 수준의 보수적 전체 한글화 예산이 16 MiB append 공간의 극히 일부만 사용하므로, **공간을 맞추기 위한 위험한 in-place 재사용보다 구조적 안전성과 round-trip 검증을 우선**할 수 있다.

## 16. 32 MiB production 제약 감사 및 allocator

32 MiB를 실제 메인 구조로 쓰기 전에 `tools/analyze_ggen_advance_32m_constraints.py`로 확인된 text/dictionary/font 경로에 16 MiB 경계를 암묵적으로 가정하는 연산이 있는지 다시 감사했다.

### 16.1 포인터 전달 경로

확인 결과 다음 여섯 항목이 모두 정적 PASS다.

1. `0x08000CA0` draw wrapper가 입력 `r3` text pointer를 `r8`에 보존한 뒤 `0x08000648` 호출 시 다시 `r3`로 전달
2. `0x08000648`이 해당 `r3`를 parser의 `r1`로 그대로 전달
3. `0x0800118C`이 `r1`을 `r4`로 복사한 뒤 `ldrb [r4]`, `r4 += 1` 방식으로 직접 순회
4. dictionary mode table에서 base를 **32-bit `ldr`**로 읽고 relative `u16` offset을 단순 가산
5. 8×16 renderer는 `font_base + slot*32`
6. 12×12 renderer는 `font_base + slot*18`

이 확인된 실행 경로에는 pointer를 16 MiB 범위로 자르는 `AND/BIC` 또는 유사 pointer truncation이 없다. 초기 linear disassembly에서 `0x08001350`이 `ANDS`처럼 보였던 것은 실제 명령이 아니라 **8×16 font base inline literal 데이터**를 코드로 오해한 것이었고, 실행 범위를 바로잡은 뒤 blocker는 0건이다.

따라서 현재 정적 결론은:

> **confirmed text/dictionary/font path에서 32 MiB 사용을 막는 정적 제약을 찾지 못했다.**

또한 known base의 exact 32-bit ROM 참조도 다시 확인했다.

- 8×16 font base `0x08094028`: file `0x00001350` 1곳
- 12×12 font base `0x0808AC40`: file `0x00001388` 1곳
- dictionary pointer table `0x08D53D44`: file `0x000011F4` 1곳

ROM 전체에 `00FFFFFF`, `01FFFFFF` 같은 mask처럼 보이는 4-byte 패턴은 많이 있지만 대부분 graphics/data의 우연한 값이므로, **raw byte pattern은 pointer-mask 증거로 사용하지 않는다.** 실행이 확인된 코드 경로의 실제 명령만 blocker 판정에 사용한다.

### 16.2 production append partition

향후 빌더가 16 MiB append 영역을 무질서하게 소비하지 않도록 `tools/ggen_advance_32m_layout.py`를 추가했다.

| region | file range | GBA range 시작 | capacity | 용도 |
|---|---|---:|---:|---|
| `static` | `01000000–0103FFFF` | `09000000` | 256 KiB | font/dictionary/charmap/static tables |
| `text` | `01040000–0123FFFF` | `09040000` | 2 MiB | relocated token streams |
| `graphics` | `01240000–0163FFFF` | `09240000` | 4 MiB | 타이틀/UI/tile/sprite 번역 자산 |
| `future` | `01640000–01EFFFFF` | `09640000` | 8.75 MiB | overflow/후속 시스템 |
| `metadata` | `01F00000–01FFFFFF` | `09F00000` | 1 MiB | optional build/debug metadata |

allocator는 object name 중복, alignment, region 경계, append 경계, object overlap을 모두 실패 처리한다. 모든 allocation은 file offset과 `0x08000000 + file_offset` GBA address를 함께 manifest로 기록한다.

### 16.3 보수적 reference plan

현재 파악된 실제/예상 용량보다 큰 reference budget을 넣어 allocator를 검증했다.

- 12×12 전체 font: 35,856 B
- 8×16 전체 font: 66,176 B
- 두 원본 크기 dictionary: 1,924 + 1,928 B
- charmap/encoding table 예산: 16 KiB
- 전체 한국어 text 예산: **320 KiB**
  - 앞서 계산한 1.4× / all-2-byte 예상치 298,134 B보다 큼
- graphics 예산: 2 MiB
- build metadata 예산: 64 KiB

총 payload는 **2,612,636 B**, 추가 16 MiB의 **15.5725%**다.

중요한 region별 잔여량은 다음과 같다.

- `static`: 122,268 B payload 후 약 **136.5 KiB** 추가 여유
- `text`: 320 KiB 사용 후 약 **1.69 MiB** 여유
- `graphics`: 2 MiB 사용 후 **2 MiB** 여유
- `future`: **8.75 MiB 전체 미사용**
- `metadata`: 64 KiB 사용 후 **960 KiB** 여유

따라서 32 MiB production에서는 텍스트 압축이나 기존 font slot 파괴가 **공간 확보를 위한 필수 조건이 아니다.** 먼저 안전한 literal/relocation 구조로 완성한 뒤 필요할 때만 최적화한다.

## 17. `0x08000CA0` draw callsite source-map 정밀 분석

공통 text draw wrapper `0x08000CA0`의 direct Thumb `BL`은 **196곳**이다. 초기에는 nearby literal만 보았으나, 이후 `tools/analyze_ggen_advance_draw_r3_sources.py`로 실제 `r3` 정의를 backward-slice하고 producer 함수까지 추적했다.

Capstone이 중간 literal pool에서 디스어셈블을 끊어 오래된 `r3` 정의를 잡는 문제도 발견되어 `skipdata`와 branch-local 수동 검증으로 교정했다. 최종 구조 분류는 다음과 같다.

| 분류 | draw callsite |
|---|---:|
| 순수 static ROM source | **192** |
| static variant + runtime fallback hybrid | **2** |
| runtime RAM indirection | **2** |
| 구조적으로 분류 완료 | **196 / 196 (100%)** |

static ROM source coverage는 **97.959%**다. hybrid 두 곳은 `0x0001C746`, `0x0001C760`, 순수 runtime-indirect 두 곳은 `0x0001C63E`, `0x0005F860`이다.

### 17.1 strict direct indexed text owner

최신 dataflow/index-domain 분석에서 direct indexed owner는 **5개 / 228 text entries**다.

| file owner | physical slots | text entries | 도달 범위 근거 |
|---:|---:|---:|---|
| `0x001C92E8` | 114 | **114** | 114-entry direct pointer table |
| `0x00FCDF78` | 13 | **13** | `0x080603CA`; runtime `+0x25` field가 modulo 13 |
| `0x00FCE128` | 22 | **22** | `0x08064D38` → `0–10`, caller가 조건부 `+11` |
| `0x00FCE2A8` | 12 | **10** | 4×3 sparse; indices `2`, `11`은 NULL |
| `0x00FCE2D8` | 69 | **69** | flat byte-index lookup + adjacent pair; historical 23×3 physical grouping, entry 69부터 code-pointer data |

`tools/extract_ggen_advance_confirmed_text.py`의 stage-1도 이 5개 owner만 남기도록 교정했다.

현재 stage-1 strict 결과:

- pointer records: **228**
- unique targets: **221**
- unique raw bytes: **2,483 B**
- unique expanded display units: **1,781**
- parse → re-encode: **228/228 PASS**
- 8×16/12×12 dictionary expansion unit 수: 전부 동일

과거 nearby-pointer 휴리스틱에 들어갔던 `0x000E57A0`, `0x00D58F88`, `0x00D58FB0`는 최신 direct `r3` dataflow owner가 아니다. 특히 `D58FB0` 후반은 `0x0806C9xx` 코드 포인터를 포함하므로 production text source에서 제거했다.

### 17.2 기존 packed-table 휴리스틱의 한계가 확인됨

`0x00FCE2A8`은 실제 draw code가 직접 참조하고 두 entry 모두 valid token stream이지만, entry가 2개뿐이라 기존 `text_table_probe.json`의 candidate 기준에는 잡히지 않았다.

반대로 위 7개 중 다수는 `credible_packed_tables`에는 들어가지 않는다. 이는 packed adjacency가 낮거나 target이 여러 data 영역으로 퍼져 있기 때문이다.

따라서 전체 번역 source 확정 기준은 다음 순서가 더 안전하다.

1. **code xref로 draw path에 연결됨** → 최우선 확정
2. table entries가 전부 valid token stream → 구조 확정
3. packed adjacency/lead-byte ratio → 보조 confidence

즉 기존 `456 credible packed tables`는 좋은 하한선이지만 전체 번역 대상을 대표하는 상한선은 아니다.

### 17.3 direct-string과 unresolved callsite의 다음 작업

123 direct-string callsite 주변에서 발견되는 ROM token-stream literal은 중복을 제거하면 현재 약 **80개 target 후보**로 모인다. 이 중 상당수는 file `0x001Bxxxx`에 집중되어 있다. 다만 현재 방식은 callsite 앞 96 bytes의 literal pool을 함께 보기 때문에 인접 함수용 literal이 섞일 수 있어, 이 80개를 바로 '확정 문자열'로 승격하지 않는다.

다음 source-map 단계는:

- 123곳에서 **마지막 `r3` write를 register 단위로 backward slice**해 실제 전달 target만 확정
- 47 unresolved callsite는 caller argument / table lookup / function return으로 source 종류 분류
- 7 canonical table은 호출 함수와 index 생성식을 분석해 UI/도감/유닛/인물/대사/전투 문구로 semantic category 부여
- 이 결과와 기존 456 packed 후보를 교차해 `confirmed / referenced / heuristic` 3등급 source map 생성

이 작업이 끝나면 전체 한글화 extractor가 '그럴듯한 문자열을 전수 스캔'하는 방식이 아니라 **실제 renderer로 도달하는 source를 중심으로 추출**할 수 있다.

## 18. 확정 text extractor와 32 MiB no-op relocation plan

source-map 1차 결과를 실제 번역 파이프라인에 연결하기 위해 다음 두 도구를 추가했다.

- `tools/extract_ggen_advance_confirmed_text.py`
- `tools/plan_ggen_advance_confirmed_text_relocation.py`

### 18.1 code-xref-confirmed extractor

현재 extractor 범위는 section 17에서 strict하게 확정한 **5개 direct indexed text owner**다. 과거의 200/202-entry 연속 pointer-run 휴리스틱은 사용하지 않는다.

추출 record는 최소한 다음 정보를 보존한다.

- `record_id`
- source table / table file offset
- pointer index
- pointer source file offset
- 원본 32-bit pointer value
- target file offset
- NUL 포함 raw bytes
- token list
- token kind
- terminator
- dictionary expansion 후 display unit 수
- parse → re-encode 동일성

현재 검증 결과:

| 항목 | 결과 |
|---|---:|
| strict direct indexed owners | **5** |
| pointer records | **228** |
| unique target streams | **221** |
| duplicate target를 갖는 unique target | 7 |
| pointer-reference 기준 raw bytes | 2,593 B |
| unique target raw bytes | **2,483 B** |
| single-byte tokens | 1,025 |
| extended literal tokens | 536 |
| dictionary tokens | 134 |
| reference 기준 expanded display units | 1,869 |
| unique target expanded display units | **1,781** |

가장 중요한 gate는 다음 두 가지다.

1. **228/228 strict parse → re-encode byte-identical**
2. dictionary token을 8×16/12×12 사전으로 각각 확장했을 때 **228/228 표시 unit 수 동일**

즉 현재 확정 구간은 Unicode charmap이 아직 없어도 구조 손실 없이 추출/재구성할 수 있다.

### 18.2 dictionary expansion을 extractor에 포함한 이유

원본 stream의 `F000–F13E`는 저장 공간에서는 2-byte token 하나지만 화면에서는 여러 글자를 만든다. 따라서 번역 폭/길이 예산은 raw token count가 아니라 dictionary expansion 후 display unit을 기준으로 봐야 한다.

현재 221 unique stage-1 stream은 raw token storage보다 display unit이 더 크며, 두 font mode의 dictionary가 서로 다른 literal slot 번호를 쓰더라도 대응 entry의 논리 글자 수는 동일하다. 이 특성을 extractor에서 자동 감사하도록 했다.

향후 record schema에서는 최소한 다음 세 길이를 분리한다.

- `raw byte length`
- `encoded token count`
- `expanded display unit count`

### 18.3 no-op 32 MiB relocation plan

`plan_ggen_advance_confirmed_text_relocation.py`는 위 221 unique stage-1 stream을 원문 그대로 production `text` region에 한 번씩만 pack한다.

현재 deterministic plan:

- blob file start: **`0x01040000`**
- blob GBA address start: **`0x09040000`**
- blob end-exclusive: `0x010409B3`
- unique streams: **221**
- blob size: **2,483 B**
- blob SHA-256: `3d786732abca9483b5141770d6c41bee5744c234acd8bf2f996e76623e1c32dd`
- pointer patch records: **228**
- unique new pointer values: **221**
- 2 MiB text region utilization: **0.1184%**
- text region remaining: **2,094,669 B**

verification:

- extractor raw round-trip: PASS
- relocation blob reconstruction: PASS
- 모든 new target가 `0x01040000–0x0123FFFF` 안: PASS
- 모든 new pointer가 GBA `0x09xxxxxx` window: PASS
- duplicate-reference sharing semantics 보존: PASS

### 18.4 duplicate target 처리 원칙

228 pointer entries를 228개의 별도 문자열로 복사하지 않는다. 동일 원본 target을 참조하는 entry는 relocation 후에도 하나의 새 stream을 공유한다.

따라서:

- **228 pointer patches**
- **221 relocated streams**

이 구조가 된다.

이는 원본의 alias/share 관계를 no-op rebuild에서 그대로 보존한다. 실제 번역에서 같은 원문을 문맥 때문에 다르게 번역해야 한다면 그때 해당 reference만 **명시적으로 detach**하는 방식으로 바꾼다. 자동으로 duplicate를 분리하지 않는다.

### 18.5 인접 heterogeneous owner 처리

`0x00FCDF78`과 `0x00FCE128`은 물리적으로 같은 인접 pointer 영역에 놓여 있지만 **하나의 202-entry text table이 아니다.** 현재 code/dataflow로 확정된 domain은 다음처럼 별도 owner로 취급한다.

- `FCDF78[0..12]`: 13-entry text owner
- `FCE128[0..21]`: 22-entry text owner
- 그 사이/뒤의 pointer 값은 다른 데이터·코드 owner가 섞이므로 text로 자동 승격하지 않는다.

relocation planner도 두 owner의 실제 pointer field만 개별 patch한다.

### 18.6 production text rebuild의 다음 gate

이제 실제 번역 삽입기는 다음 순서로 만들 수 있다.

1. confirmed extractor record 읽기
2. charmap으로 일본어 token → Unicode 복원
3. 번역 문자열 → Korean token encode
4. duplicate/share 정책 적용
5. `text` allocator에서 variable-length stream 배치
6. pointer source를 new `0x09xxxxxx` address로 갱신
7. 모든 stream NUL/slot/reserved-code 감사
8. untranslated 상태에서 먼저 no-op 32 MiB rebuild가 runtime-equivalent인지 확인

즉 stage-1 strict owner **221 unique stream**에 대해서는 추출 → 구조 보존 → 32 MiB relocation 계획까지 하나의 재현 가능한 파이프라인으로 연결되었다. 전체 reachable corpus는 다음 section의 stage-2 파이프라인이 담당한다.

### 18.7 32 MiB no-op rebuild 메모리 검증

`tools/build_ggen_advance_32m_confirmed_text_relocation.py`를 추가해 위 relocation plan을 실제 32 MiB bytearray에 적용하고 전체 정적 검증했다.

이 후보는 번역/폰트/사전을 전혀 변경하지 않는다.

- 원본 ROM 16 MiB 그대로 유지
- 뒤에 `FF` 16 MiB append
- 221 unique raw stream을 `0x01040000`부터 byte-identical 복사
- 228 confirmed pointer field만 새 `0x0904xxxx` 주소로 갱신
- 원본 target stream은 삭제/overwrite하지 않음

현재 dry-run 결과:

- output size: **33,554,432 B**
- output SHA-256: `d9f2bc5113cbe2f75fd3ae1642729b8a6b8b0ba2a6a45fba0e31f252c13486ab`
- relocated blob SHA-256: `3d786732abca9483b5141770d6c41bee5744c234acd8bf2f996e76623e1c32dd`
- relocated blob: **2,483 B / 221 streams**
- patched pointer records: **228**
- 원본 16 MiB 내 실제 changed bytes: **911 B**
- allowed pointer field 밖 unexpected changed bytes: **0**
- `0x00FCED40–0x00FFFFFF` strong tail: byte-identical
- original target streams: byte-identical
- relocated stream parse/token 비교: **221/221 동일**

중요한 점은 실제 diff가 모두 228개의 허용된 pointer source field 안에만 있다는 것이다.

이 후보의 runtime 기대값은 **원본과 화면/동작이 동일**한 것이다. 따라서 실제 `.gba`를 생성해 BizHawk/mGBA에서 동일 입력으로 비교했을 때 화면이 달라지면 번역 문제가 아니라 32 MiB relocation 자체의 문제로 즉시 격리할 수 있다.

런타임에서 이 no-op 후보가 pixel-equivalent PASS하면, 그 다음에는 동일 allocator/pointer map에 한국어 encode 결과만 넣으면 된다. 즉 32 MiB 구조 검증과 번역 품질 검증을 서로 분리할 수 있다.

## 19. Stage-2 reachable corpus, 전체 relocation, Unicode seed export

stage-1 direct indexed owner만으로는 전체 번역 source를 대표하지 못하므로 `tools/extract_ggen_advance_reachable_text.py`에서 `0x08000CA0`의 direct call 196곳을 R3 dataflow와 producer 모델로 확장했다. 이 단계에서는 direct literal, strict indexed owner, producer DB field, direct struct field, length-prefixed pair, u16-relative paired block을 서로 다른 reference schema로 보존한다.

### 19.1 전체 source-map 결과

현재 구조 분류는 다음과 같다.

- direct draw calls: **196/196 구조 분류 완료**
- static ROM source로 직접 커버: **192/196 = 97.959%**
- static + runtime hybrid: 2곳
- runtime RAM indirection: 2곳
- unique reachable token streams: **3,911**
- unique target raw bytes: **61,007 B**
- expanded display units: **42,364**
- patchable 32-bit pointer sources: **3,943**
- 모든 record parse → encode round-trip: PASS
- 8×16/12×12 dictionary expansion display-unit 수 일치: PASS

특히 strict token gate는 실제 renderer가 사용하는 범위만 허용한다.

- single byte: `01–DF`
- extended literal: `E000–E733`
- dictionary: `F000–F13E`

이 gate 때문에 예전 연속 pointer-run에서 Thumb code를 text로 오인하던 `F766`, `FE00`, `FC20` 계열 false-positive를 제거할 수 있었다.

### 19.2 Stage-2 32 MiB no-op relocation

`tools/plan_ggen_advance_reachable_text_relocation.py`는 reference encoding을 세 종류로 분리해 relocation한다.

1. 일반 u32 pointer → NUL token stream
2. 18개 length-prefixed paired-stream variant
3. `0x081BF908`의 256×3 u16-relative paired-text block

현재 payload는 다음과 같다.

| 구간 | 새 file range | 크기 |
|---|---:|---:|
| u16-relative pair block | `0x01040000–0x01048C93` | 35,988 B |
| length-prefixed pairs | `0x01048C94–0x01048F69` | 726 B |
| ordinary u32 streams | `0x01048F6C–0x0104F477` | 25,868 B |
| 합계 |  | **62,582 B** |

추가 검증 결과:

- ordinary unique streams: **2,345**
- ordinary u32 patch fields: **3,925**
- total u32 patch fields: **3,944**
- text region 사용률: **2.984%**
- 원본 16 MiB actual changed bytes: **15,774 B**
- allowed patch byte positions: 15,776 B
- 허용 영역 밖 unexpected 변경: **0 B**
- relocated payload byte-identical: PASS
- original text payload 보존: PASS
- strong tail `0x00FCED40–0x00FFFFFF` 보존: PASS
- dry-run output SHA-256: `aab7dab78674d69f3a129213e009bebeffa9b0622b01805cea2f6c728b1b0b00`

따라서 실제 production text relocation 기준은 stage-1의 221-stream 최소집합이 아니라 이 stage-2 구조를 사용한다.

`relative_256x3` family는 charmap 복구 중 고빈도 반복 glyph가 보여 false-positive 가능성을 다시 감사했다. 재검증 결과 `0x0804DC30`은 실제로 `index = row*3 + column`을 계산하고 `0x081BF908`의 u16 relative offset을 읽어 `base+offset`을 문자열 포인터로 반환한다. 두 실제 caller(`0x0801FC6C`, `0x0803ABDC`)는 반환 포인터를 첫 줄 draw에 사용한 뒤 첫 NUL을 건너 같은 pair의 두 번째 문자열을 다음 줄에 draw한다. 또한 765개 pair가 다음 relative offset 경계를 765/765 정확히 채운다. 따라서 이 block은 구조 데이터 오인이 아니라 **실제 2행 텍스트/template table**로 유지한다. 765 pair 중 고유 pair는 184개이며 가장 많이 반복되는 default pair가 333회 저장되어 있어 고빈도 slot 분포를 설명한다.

### 19.3 일본어 charmap seed 복구

`tools/analyze_ggen_advance_charmap.py`는 업그레이드 파츠, 고신뢰 unit-name, 일부 명확한 weapon-name known plaintext를 ROM glyph slot에 정렬한다. 현재 결과는:

- known-plaintext anchors: **107**
- verified glyph slots: **128**
- verified Unicode characters: **127**
- slot conflict: **0**
- 허용된 Unicode alias: `M`이 `0x000B`와 `0x0012` 두 slot에 존재
- anchor length mismatch: **0**
- mapped display units: **14,211 / 42,364 = 33.545%**
- 완전 디코드 streams: **660 / 3,911 = 16.875%**

예를 들어 `ザクⅡF`, `ガンタンク`, `シャア専用ザク`, `ライデン専用ザク`, `陸戦型ガンダム`, `コア・ブースター`, `GP01ゼフィランサス`, `ガンダムMkⅡ`, `量産型キュベレイ`, `V2ガンダム`, `ホワイトベース`, `ヒートホーク`, `メガ粒子砲` 등이 slot 충돌 없이 복원된다. 동일 Unicode가 둘 이상의 실제 font slot에 존재하는 것은 alias로 보존하고, 서로 다른 Unicode가 같은 slot을 요구하는 경우만 conflict로 처리한다. 확인되지 않은 glyph는 추측으로 Unicode를 지정하지 않는다.

### 19.4 Unicode seed exporter

`tools/export_ggen_advance_unicode_seed.py`를 추가했다. 이 도구는 stage-2 corpus 전체를 다음 두 형식으로 내보낼 수 있다.

- JSON: full source/reference provenance를 포함한 machine-readable record
- TSV: 번역 검수/편집용 평면 시트

각 record는 최소한 다음을 보존한다.

- target file offset / ROM pointer
- raw token bytes / token sequence
- dictionary-expanded glyph slot sequence
- 현재 seed로 복원한 일본어 Unicode
- unresolved/reserved slot 목록
- source type / producer family / reference 목록
- patchable reference 수
- 빈 `translation_ko`, `notes` 필드

미확정 slot은 `<07FB>` 같은 placeholder로 남기며 임의 문자를 넣지 않는다. 현재 export 상태는:

- records: **3,911**
- complete: **660**
- partial: **2,669**
- unmapped: **582**
- unresolved unique slots: **1,012**
  - reserved unresolved: 6
  - non-reserved unresolved: 1,006
- 예상 JSON UTF-8 크기: **7,342,969 B**
- 예상 TSV UTF-8 크기: **1,379,063 B**
- TSV data rows: **3,911**

JSON/TSV 양쪽 모두 파일을 쓰지 않는 `--summary-only` 실행에서 메모리 직렬화와 row-count gate를 통과했다.

재현 명령:

```bash
PYTHONIOENCODING=utf-8 python tools/export_ggen_advance_unicode_seed.py "advance/SD Gundam GGeneration Advance (Japan).gba" --summary-only
```

실제 번역용 파일이 필요할 때는 `--json-out` / `--tsv-out`을 지정한다. production insertion 단계에서는 이 export의 `translation_ko`를 별도 한국어 charmap/encoder에 입력하고, 원본 `references`와 relocation schema를 그대로 사용한다.

### 19.5 다음 구현 우선순위

다음 단계는 Unicode seed를 더 넓히되 추측 기반 전체 charset 생성을 피하는 것이다.

1. 현재 완전/부분 디코드 unit·weapon·pilot 명칭에서 추가 known-plaintext anchor 확보
2. **1,012 unresolved slot**을 frequency와 source family별로 분류
3. reserved/icon/control slot과 일반 일본어 glyph를 분리
4. 일본어 charmap coverage가 충분히 올라오면 번역 TSV를 고정 schema로 생성
5. 한국어 font slot allocator + Unicode→token encoder 구현
6. untranslated no-op stage-2 32 MiB runtime-equivalence 검증 후 실제 한국어 문자열 삽입

이 순서를 따르면 32 MiB 확장, 텍스트 source-map, 일본어 복호화, 한국어 인코딩을 서로 독립적으로 검증할 수 있다.

## 20. 한국어 glyph slot allocator 설계

`tools/plan_ggen_advance_korean_slots.py`를 추가해 renderer slot 수를 늘리지 않고 두 font mode가 공통으로 사용할 수 있는 literal glyph 영역을 계산했다.

### 20.1 두 font mode의 공통 literal 범위

현재 font slot 수는 다음과 같다.

- 8×16: 2,068 slots
- 12×12: 1,992 slots

따라서 양쪽 font에서 같은 slot 번호를 안전하게 직접 사용할 수 있는 상한은 `0x07C7`이다. extended literal token의 정규화식은 기존과 동일하다.

`slot = (token + 0x20E0) & 0xFFFF`

이때 두 mode 공통 extended literal 영역은 정확히:

- slot: **`0x00E0–0x07C7`**
- token: **`0xE000–0xE6E7`**
- capacity: **1,768 glyphs**

이다. 따라서 한국어 production charmap은 우선 이 범위만 사용하고 `E6E8+`는 12×12 font 범위를 넘으므로 사용하지 않는다.

### 20.2 현재 일본어 corpus와 config가 점유한 범위

Stage-2 3,911 streams를 두 mode dictionary로 각각 전개하고, 양쪽 config `+0x00–+0x4C`의 u16 slot 값을 보수적으로 전부 예약했다.

- 8×16 Stage-2 사용 extended slots: **890**
- 12×12 Stage-2 사용 extended slots: **895**
- 두 mode 사용 집합 + config/compatibility 예약 합집합: **928**
- config-owned shared extended slots: **25**
- compatibility-preserved shared extended slots: **14**
- config + compatibility 예약 합집합: **29**
- config에는 없지만 compatibility 때문에 추가 보존되는 slot: **4** (`0x00E9`, `0x00EA`, `0x00ED`, `0x0109`)
- 현재 Stage-2 양 mode에서 모두 미사용이며 config/compatibility 예약에도 없는 bootstrap 후보: **840**

이 840개는 초기 POC/bootstrap 후보로는 유용하지만, 아직 2개 hybrid + 2개 RAM-indirection draw 경로가 남아 있으므로 **전역적으로 unused라고 단정하지 않는다.**

### 20.3 full-conversion 정책

완전 한글화 후에는 일본어 문자열과 일본어 dictionary가 새 Korean token stream으로 교체되므로, 원본 일본어 glyph가 차지하던 shared extended slot을 단계적으로 회수할 수 있다.

config와 compatibility 예약의 합집합 29개를 보수적으로 계속 보존할 경우:

- full-conversion Korean candidate slots: **1,739**
- renderer slot 확장: **불필요**
- `01–DF` 1-byte 코드의 한글 재할당: **초기에는 불필요**

기존 WSC 한국어 프로젝트 데이터 107개 파일에서 얻은 reference corpus는 고유 한글 음절 **1,007개**다. 이 값을 Advance 번역의 근사 상한으로 사용할 경우:

- 1,739 − 1,007 = **732 glyph slots 여유**

가 남는다. 실제 Advance 최종 번역의 고유 음절 수는 별도로 측정해야 하지만, 현재 수치상으로는 2-byte shared literal charmap만으로 충분할 가능성이 높다.

### 20.4 권장 인코딩 단계

초기 production 구현은 다음 순서를 권장한다.

1. `01–DF` 원래 1-byte token은 그대로 유지한다.
2. 한국어 음절은 `E000–E6E7` shared literal 범위에 배치한다.
3. 32 MiB 확장 영역에 복사한 8×16/12×12 font의 동일 slot에 동일 Unicode glyph를 렌더한다.
4. 부분 한글화 단계에서는 아직 일본어로 남은 stream이 사용하는 slot을 회수하지 않는다.
5. 번역 완료 stream이 늘어날 때 해당 일본어 glyph slot의 reference count가 0이 된 경우에만 reclaim 가능 상태로 전환한다.
6. 최종 Advance 번역 corpus가 1,739 glyph를 실제로 초과하는 경우에만 1-byte 빈도 최적화 또는 renderer 확장을 재검토한다.

이 방식은 공간 최적화를 먼저 하기보다 **원문 보존, 부분 번역 안전성, rollback 가능성**을 우선한다. 현재 32 MiB 추가 공간이 충분하므로 텍스트 압축과 1-byte 한글 최적화는 기능 검증 후의 선택 사항으로 남길 수 있다.

### 20.5 reference Korean charmap의 실제 배치 검증

`tools/plan_ggen_advance_korean_charmap.py`는 기존 WSC 한국어 corpus의 1,007개 고유 한글 음절을 출현 빈도 순으로 실제 slot/token에 배치한다.

현재 결과:

- reference files: 107
- unique Hangul syllables: **1,007**
- Hangul occurrences: **85,034**
- bootstrap capacity: **840**
- full-conversion capacity: **1,739**
- bootstrap assigned: **840**
- reclaim assigned: **167**
- 최종 미사용 full-conversion slots: **732**
- bootstrap 840글자가 reference Hangul 출현을 커버하는 비율: **99.72%**

reclaim 167자는 Stage-2에서 현재 일본어 사용 빈도가 가장 낮은 slot부터 배정했다. 실제 선택된 167개 slot의 `8×16 + 12×12` Stage-2 occurrence 합계는 모두 **1–2회**다. 따라서 고빈도 한국어는 일본어 미사용 slot에 먼저 배치하고, 매우 희귀한 한국어 음절만 번역 진행 후 회수 가능한 일본어 slot을 요구한다.

모든 assignment는 다음 gate를 통과한다.

- Hangul 1,007자 ↔ slot 1,007개 일대일
- token 1,007개 중복 없음
- 모든 token `E000–E6E7`
- `token → slot → token` round-trip PASS
- 1-byte Hangul token 사용 0

### 20.6 Unicode→token codec

`tools/ggen_advance_korean_codec.py`를 추가했다. 이 codec은 Korean charmap과 현재 검증된 일본어 seed를 결합한다.

- Hangul: 위 1,007자 deterministic Korean assignment 사용
- 공백/영문/숫자 등: 기존 검증 glyph 중 양 font mode에서 안전하게 token화 가능한 slot을 passthrough로 사용
- 같은 Unicode가 여러 slot에 존재하면 1-byte token을 우선하고 그 다음 낮은 token을 사용
- 미확정 Unicode는 추측하지 않고 즉시 오류
- `E6E7`보다 큰 Korean literal token은 절대 emit하지 않음

검증 결과:

- Hangul chars: **1,007**
- Hangul unique tokens: **1,007**
- verified compatibility passthrough chars: **32**
- reference Hangul 1,007자를 한 문자열로 encode: **2,015 B including NUL**
- one-byte Hangul emitted: **False**
- sample `건담 GP01`:
  - tokens: `E6B0 E697 01 09 0C 02 E000`
  - bytes: `E6 B0 E6 97 01 09 0C 02 E0 00 00`
  - NUL 포함 11 B

### 20.7 Korean font blob build

`tools/build_ggen_advance_korean_font_blobs.py`는 동일 Korean assignment를 12×12와 8×16 원본-format font 사본의 **같은 slot 번호**에 렌더한다.

bootstrap 840 glyph 결과:

- 12×12 blob: 35,856 B
  - SHA-256 `9a7c5c4cf741d08a5cfa7b19af89f7d6dca4603555231195ebd3e48c65f184b3`
  - changed bytes 13,955
- 8×16 blob: 66,176 B
  - SHA-256 `2cdcdd5f032175dc0c1f7a1ff33a988b69ace947d16efa89eb73f0270f9fa1b7`
  - changed bytes 18,815
- blank rendered Korean glyphs: 0 / 0
- 선택하지 않은 slot 변경: 0 / 0
- PASS

full 1,007 glyph 결과:

- 12×12 SHA-256 `9629a6a9a2798e5efc6d65b2dabf6bb4dca8960b8b62fd86b613bc51d665ceed`
- 8×16 SHA-256 `7ecd46cc472fa5f73612525a77fd0ed1ff7997cd10fd48049256fda5b3a67685`
- blank rendered Korean glyphs: 0 / 0
- 선택하지 않은 slot 변경: 0 / 0
- PASS

두 전체 font blob은 production `static` region에서:

- 12×12: file `0x01000000`, GBA `0x09000000`
- 8×16: file `0x01008C20`, GBA `0x09008C20`
- static region payload: **102,032 B / 38.922%**
- 남은 static 영역: **160,096 B**

이 방식은 font slot count 자체를 바꾸지 않으므로 renderer index-range patch가 필요 없다.

### 20.8 production-shaped Korean bootstrap POC

`tools/build_ggen_advance_32m_korean_bootstrap_poc.py`는 위 요소를 하나의 32 MiB 메모리 후보로 결합한다.

구조:

- relocated 12×12 font copy → `0x09000000`
- relocated 8×16 font copy → `0x09008C20`
- runtime proof에 필요한 **`한/글/출/력` 4개 slot만** 두 font copy에서 Korean glyph로 교체
- 나머지 836 bootstrap candidate slot을 포함한 모든 비선택 slot은 원본 font와 byte-identical
- literal `한글출력` marker → `0x09040000`
- marker tokens: **`E6B6 E335 E561 E6A8`**
- marker 4글자 모두 bootstrap assignment
- strict Stage-1 pointer fields 228개만 marker로 redirect
- font base literal 2곳만 새 font로 redirect
- dictionary는 원본 유지

초기 구현은 840 bootstrap glyph를 모두 font copy에 렌더했지만, 아직 2개 hybrid + 2개 RAM-indirection draw path가 남아 있다는 점을 고려해 runtime proof 후보는 **4-glyph minimal-marker 방식으로 축소**했다. standalone font builder의 840/1,007 glyph production 결과는 그대로 유지한다.

메모리 검증 결과:

- output size: 33,554,432 B
- output SHA-256: **`dcd4df2a93a39d00ec26ba3a3f47f9fb367b217ec9f9c9e0db2e6a1691e9224d`**
- selected Korean glyphs in relocated fonts: **4 / mode**
- minimal-marker 12×12 font SHA-256: `742bf6ba7092f9d8ee4f6e6adcd10be73ebbb6fbfce50b962d10d5f52ecd2766`
- minimal-marker 8×16 font SHA-256: `c4bf5556d6e06c5f642f17de92719719194bac84f464de7ce2b2bfd3a0c087d1`
- 원본 half에서 허용 가능한 patch byte positions: 920
- 실제 changed bytes: 919
- unexpected changed bytes: **0**
- original font blocks: byte-identical
- strong tail `0x00FCED40–0x00FFFFFF`: byte-identical
- GBA header: byte-identical
- appended font/marker payload: exact
- marker strict parse round-trip: PASS
- 전체 verification: **PASS**

### 20.9 bootstrap runtime trace 준비

실제 BizHawk 2.11.1 / mGBA 실행용으로 다음을 추가했다.

- `tools/bizhawk_ggen_advance_korean_bootstrap.lua`
- `tools/run_ggen_advance_korean_bootstrap_poc.py`

Lua runtime PASS 조건은 화면 비교만이 아니다.

1. parser `0x0800118C`에서 `R1 == 0x09040000` 직접 관측
2. 8×16 renderer `0x08001322`에서 `R4`가 `0x09008C20–0x09018E9F`에 들어가는 것을 관측하거나
3. 12×12 renderer `0x080013A2`에서 `R6`가 `0x09000000–0x09008C0F`에 들어가는 것을 관측
4. text hit + font hit가 모두 있어야 overall PASS

현재 DevSpace 실행 규칙상 shell 명령으로 새 binary `.gba`를 생성하지 않았기 때문에 runtime 실행만 pending이다. 후보 builder와 runtime runner는 실제 파일을 명시적으로 지정했을 때 사용할 수 있도록 준비돼 있다. Python 문법 검사는 PASS했고 로컬 shell에는 독립 Lua interpreter가 없어 Lua syntax는 BizHawk 로딩 시 최종 확인한다.

### 20.10 재검증 checkpoint (2026-08-24 11:55 KST)

연결 불안정 이후 현재 checkout을 다시 열어 production 경로를 처음부터 재검증했다.

- 관련 `*ggen_advance*.py` **26개 syntax PASS**
- Stage-2 reachable relocation: **62,582 B / 3,944 u32 patch fields / unexpected 0 / PASS**
- Stage-2 dry-run SHA-256: `aab7dab78674d69f3a129213e009bebeffa9b0622b01805cea2f6c728b1b0b00`
- Japanese charmap seed: **107 anchors / 128 slots / 127 Unicode chars / slot conflict 0**
- Unicode coverage: **14,211 / 42,364 = 33.545%**, complete **660 / 3,911**
- shared Korean literal domain: `E000–E6E7`, 1,768 slots
- bootstrap Korean slots: **840**
- config + compatibility reserved union: **29**
- full-conversion Korean capacity: **1,739**
- reference Hangul 1,007자 배치 후 여유: **732 slots**
- Korean codec: **1,007 Hangul / 32 compatibility passthrough chars / one-byte Hangul 0**
- standalone font build: bootstrap **840 PASS**, full **1,007 PASS**, 기존 검증 SHA-256 유지
- runtime POC는 안전성 검토 후 **840-glyph font가 아니라 4-glyph minimal-marker font**로 축소
- minimal-marker 32 MiB candidate: **PASS**, unexpected original-half changes **0**
- minimal-marker candidate SHA-256: `dcd4df2a93a39d00ec26ba3a3f47f9fb367b217ec9f9c9e0db2e6a1691e9224d`

따라서 현재 정적 production pipeline에서 새 blocker는 없다. 남은 결정적 gate는 **실제 32 MiB candidate 파일 생성 → BizHawk 2.11.1/mGBA에서 parser `0x09040000` hit + relocated font hit를 직접 관측하는 runtime proof**다.
