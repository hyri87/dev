# Hyetoria — DICOM Viewer 개발 문서

## 개요

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Hyetoria |
| 목적 | 로컬 DICOM 파일의 태그 구조 · 이미지 · 헥스 덤프를 분석하는 데스크톱 뷰어 |
| 언어 | Python 3.14.3 |
| 개발일 | 2026-04-21 |
| 최종 수정 | 2026-04-23 |
| 실행 파일 | `dist/Hyetoria/Hyetoria.exe` |

---

## 환경 및 의존성

| 라이브러리 | 버전 | 용도 |
|-----------|------|------|
| pydicom | 3.0.2 | DICOM 파일 파싱 |
| Pillow | 12.2.0 | 이미지 렌더링 (PIL → ImageTk) |
| numpy | 2.4.4 | WW/WL 픽셀 연산 |
| tkinterdnd2 | 0.4.3 | 드래그 앤 드롭 지원 |
| pylibjpeg[all] | 2.1.0 | JPEG / JPEG-LS / JPEG2000 / RLE 압축 디코딩 |
| imageio[ffmpeg] | 2.37.3 | MPEG2 / MPEG4 / HEVC 비디오 프레임 디코딩 |
| tkinter | 표준 라이브러리 | GUI 프레임워크 |
| PyInstaller | 6.19.0 | 단일 .exe 패키징 |

---

## 파일 구조

```
dicom_viewer/
├── main.py              # 진입점 — TkinterDnD.Tk() 루트 생성, argv 파일 자동 로드
├── dicom_parser.py      # DICOM 파싱 모듈 (태그 트리 · 픽셀 · 비디오)
├── build_icon.py        # 아이콘 생성 스크립트
├── ui/
│   ├── __init__.py
│   ├── app.py           # 메인 윈도우 레이아웃, 단축키, D&D, 파일 로드
│   ├── tag_tree.py      # ttk.Treeview 태그 트리 패널 + 검색 바
│   ├── hex_panel.py     # 헥스 덤프 패널 (lazy scroll)
│   └── image_panel.py   # DICOM 이미지 뷰어 패널 (멀티프레임 · 비디오 재생)
├── assets/
│   └── hyetoria.ico     # 앱 아이콘 (256/128/64/48/32/16px)
├── dist/
│   └── Hyetoria.exe     # 배포용 단일 실행 파일
├── requirements.txt
├── PLAN.md              # 초기 개발 계획서
└── DEV_DOC.md           # 이 문서
```

---

## UI 레이아웃

```
┌──────────────────────────────────────────────────────────────────┐
│  [파일 열기]  |  [Expand All]  [Collapse All]       상태 메시지  │  ← 툴바
├──────────────────────────────────────────────────────────────────┤
│  TAG  │VR│Len│Name    │Value             │Offset                 │
│  ├(0002,0000) File Meta Len  ...                                  │
│  ├(0002,0002) SOP Class UID  ...              ← 태그 트리        │
│  ├(0008,0060) Modality       ...                                  │
│  ├[-](FFFE,E000) Sequence Item                                    │
│  │   └(0008,0100) Code Value ...                                  │
│  └ ...                                                            │
├─────────────────────────────────┬────────────────────────────────┤
│  XXXXXXXX  XX XX ... XX  ASCII  │                                │
│  (Hex Dump — lazy scroll)       │     DICOM 이미지 뷰어          │
│                                 │   (컬러 / 그레이스케일)        │
│                                 │  WW =  4096  WL =  2047        │
│                                 │  [▶/⏸][◀][══슬라이더══][▶]   │
└─────────────────────────────────┴────────────────────────────────┘
│  [Ctrl+F 검색 바 — 태그 트리 하단에 표시]                        │
└──────────────────────────────────────────────────────────────────┘
```

> **레이아웃 구조**: 상단 태그 트리 (전체 너비) / 하단 좌 헥스 덤프 + 하단 우 이미지 뷰어
> 각 구분선은 드래그로 크기 조절 가능

---

## 기능 목록

### 파일 열기
- **툴바 버튼** "파일 열기" → `filedialog.askopenfilename` (`.dcm`, `.ima`, `*.*`)
- **드래그 앤 드롭** — 창 위에 파일을 드롭하면 자동 로드
  - 공백 포함 경로: `{중괄호}` 포맷 파싱 처리 (tkinterdnd2 Windows 동작)
  - 복수 파일 드롭 시 첫 번째 파일만 열림
- **커맨드라인 인수** — `Hyetoria.exe <filepath>` 실행 시 자동 로드
  - Windows 파일 연결(기본 앱) 등록 후 `.dcm` 더블클릭으로 바로 열기 가능
  - GUI 초기화 완료 후 100ms 뒤에 로드 (`root.after(100, ...)`)
- 로드 후 타이틀바에 파일 경로, 상태바에 태그 수 / 파일 크기 표시

### 태그 트리 패널 (`ui/tag_tree.py`)
- 컬럼: **TAG · VR · Length · Name · Value · Offset**
- **(0002,xxxx) File Meta Information 태그 포함** 표시
- 최초 오픈 시 **모든 노드 collapsed** 상태
- **Expand All / Collapse All** 버튼으로 전체 펼치기/닫기
- Sequence(SQ) 태그: 파란색(`#0055aa`)으로 구분, 재귀적 자식 노드 삽입
- **행 클릭 시 헥스 덤프 자동 스크롤 + 하이라이트 연동**
  - 헤더(~12 byte) + Value 전체 영역을 `highlight` 태그로 표시 (파란색 `#264f78`)
  - hex 열 + ASCII 열 동시 강조
- 홀짝 행 배경색 교대 (`#f5f5f5` / `#ffffff`)
- **우클릭 컨텍스트 메뉴** — Value 복사 / 행 전체 복사 (탭 구분, 엑셀 붙여넣기 호환)
- **Ctrl+C** — 선택 행의 Value 복사
- **더블클릭 → Value 팝업**
  - 마우스 드래그로 일부 텍스트 선택 가능
  - 팝업 내 더블클릭 → 전체 선택
  - Ctrl+C로 복사, Enter / ESC로 닫기

### 검색 바 (`ui/tag_tree.py` 내장)
- **Ctrl+F** 로 태그 트리 하단에 검색 바 표시/숨김
- TAG · VR · Name · Value 컬럼 대상 **대소문자 무시** 실시간 검색
- 매치: 노란색(`#ffe566`) / 현재 포커스: 진한 오렌지(`#ff6b00`) — 모두 검정 글자
  - 흰 글자(`foreground='#ffffff'`) 미사용: 선택 해제 시 밝은 배경에서 안 보이는 문제 방지
- 결과가 접힌 Sequence 안에 있으면 **부모 노드 자동 펼침 후 스크롤**
- 매치 카운터 표시 (`3 / 12`)

| 단축키 | 동작 |
|--------|------|
| `Ctrl+F` | 검색 바 열기 |
| `Enter` / `▶` | 다음 결과 |
| `Shift+Enter` / `◀` | 이전 결과 |
| `ESC` / `✕` | 검색 바 닫기 |

### 헥스 덤프 패널 (`ui/hex_panel.py`)
- **전체 파일 lazy scroll** 지원 — 파일 크기 제한 없음
  - 초기 로드: 8 KiB (512 lines)
  - 스크롤 90% 도달 시 8 KiB씩 자동 추가 append
  - 잔여 바이트 안내 메시지 실시간 갱신
- 형식: `XXXXXXXX  XX XX ... XX  ASCII`
- 다크 테마 (`#1e1e1e` 배경) — Offset: 회색, ASCII: 오렌지
- 태그 선택 시 미로드 offset도 **자동 로드 후 스크롤**
- 선택 하이라이트: `highlight` 태그 (파란색 `#264f78`, 흰색 텍스트)
  - `sel` 태그 미사용 — `state='disabled'` 위젯은 포커스 불가라 `sel`이 표시 안 됨

### 이미지 뷰어 패널 (`ui/image_panel.py`)

#### 단일 프레임
- WW/WL 윈도잉 적용 → grayscale 렌더링
- WW/WL 기본값: `(0028,1050)` WindowCenter / `(0028,1051)` WindowWidth 우선, 없으면 min/max 자동 계산
- 패널 리사이즈 시 자동 재렌더링

#### 멀티프레임
- 슬라이더 + `◀/▶` 버튼 + **마우스 휠** 프레임 탐색
- **▶/⏸ 재생 버튼** — FPS에 맞춰 자동 재생/일시정지
- FPS 자동 감지: `CineRate` → `RecommendedDisplayFrameRate` → `FrameTime` → 비디오 메타데이터 순
- Info bar: `WW / WL  Frame X / N  (29.97 fps)` 표시

#### 컬러 영상
- RGB/RGBA 컬러 프레임: 그레이스케일 변환 없이 원본 색상 표시
- YBR 계열 (`YBR_FULL`, `YBR_PARTIAL_420` 등) → RGB 자동 변환
  1. `pydicom.pixels.convert_color_space()` (pydicom 3.x 공식)
  2. BT.601 수동 YCbCr→RGB 행렬 연산
  3. PIL JPEG fragment 직접 디코딩 fallback

#### 이미지 없는 파일
- Pixel Data 없음: "No Image Data" 표시
- 디코딩 실패: 실제 오류 메시지 + 로그 경로 표시

### 비디오 DICOM 지원 (`dicom_parser.py`)

지원 전송 구문:

| UID | 형식 |
|-----|------|
| 1.2.840.10008.1.2.4.100 | MPEG2 Main Profile / Main Level |
| 1.2.840.10008.1.2.4.101 | MPEG2 Main Profile / High Level |
| 1.2.840.10008.1.2.4.102 | MPEG-4 AVC/H.264 High Profile 4.1 |
| 1.2.840.10008.1.2.4.103 | MPEG-4 AVC/H.264 BD |
| 1.2.840.10008.1.2.4.104 | MPEG-4 AVC/H.264 High Profile 4.2 2D |
| 1.2.840.10008.1.2.4.105 | MPEG-4 AVC/H.264 High Profile 4.2 3D |
| 1.2.840.10008.1.2.4.106 | MPEG-4 AVC/H.264 Stereo |
| 1.2.840.10008.1.2.4.110 | HEVC/H.265 Main |
| 1.2.840.10008.1.2.4.111 | HEVC/H.265 Main 10 |

**LazyVideoReader** — 전체 프레임을 RAM에 올리지 않고 on-demand 1장씩 디코딩
- 예: MPEG2 248 MB / 8106 프레임 → RAM 사용 ~1 MB (프레임 1장)
- 역방향 seek 시 reader 재오픈
- 임시 파일(`.mpg` / `.mp4`)은 객체 소멸 시 자동 삭제

---

## 핵심 모듈 설명

### `main.py` — 진입점

```python
# GUI 초기화 후 커맨드라인 인수로 전달된 파일 자동 로드
if len(sys.argv) > 1:
    root.after(100, lambda: app._load_file(sys.argv[1]))
```

### 시작 속도 최적화 — Lazy Import

무거운 라이브러리를 앱 시작 시 즉시 로드하지 않고, 실제 필요한 시점까지 지연.

| 모듈 | 로드 시점 |
|------|---------|
| `pydicom` | 파일 열기 첫 호출 시 (`_ensure_pydicom()`) |
| `numpy` | 이미지 표시 첫 호출 시 (`_ensure_imaging()`) |
| `PIL` (Pillow) | 이미지 표시 첫 호출 시 (`_ensure_imaging()`) |
| `dicom_parser` 모듈 전체 | `_load_file()` 내에서 `from dicom_parser import parse_dicom` |

**효과**: 윈도우 표시까지 ~340ms → **~64ms** (소스 기준)

### `dicom_parser.py` — `_collect_offsets(filepath)` 구현

pydicom 내부 API(`DicomFile`, `data_element_generator`) 대신 **직접 바이너리 파싱** 방식 사용.

```
파일 구조 파싱 순서
  1. 128바이트 프리앰블 + "DICM" 매직 확인
  2. (0002,xxxx) File Meta → 항상 Explicit VR Little Endian
  3. 이후 태그 → 전송 구문(Implicit/Explicit) 따름
  4. Long VR (OB/OW/SQ 등): Tag(4) + VR(2) + Reserved(2) + Length(4) = 12바이트 헤더
  5. Short VR: Tag(4) + VR(2) + Length(2) = 8바이트 헤더
  6. (7FE0,xxxx) 이후 중단
```

> **`DicomFile` / `data_element_generator` 미사용 이유**: pydicom 3.x에서 내부 API 변경으로
> 오프셋 수집이 silently 실패하여 태그 클릭 시 헥스 연동이 동작하지 않는 버그가 있었음.

### `dicom_parser.py` — `parse_dicom(filepath)` 반환값

```python
nodes, raw_bytes, pixel_array, pixel_error, ww, wl, fps = parse_dicom(filepath)
```

| 반환값 | 타입 | 내용 |
|--------|------|------|
| `nodes` | `list[dict]` | 태그 트리 노드 (재귀, File Meta 포함) |
| `raw_bytes` | `bytes` | 파일 전체 원본 바이트 |
| `pixel_array` | `ndarray \| LazyVideoReader \| None` | 픽셀 데이터 |
| `pixel_error` | `str \| None` | 디코딩 실패 시 오류 메시지 |
| `ww` | `float \| None` | Window Width |
| `wl` | `float \| None` | Window Center |
| `fps` | `float` | 재생 FPS (기본 10.0) |

### 주요 처리 흐름

```
parse_dicom(filepath)
  ├─ pydicom.dcmread()
  ├─ _collect_offsets()      — 직접 바이너리 파싱으로 top-level offset 수집
  ├─ _build_nodes(file_meta) — (0002,xxxx) File Meta 태그 트리화
  ├─ _build_nodes(ds)        — Main dataset 태그 트리화
  └─ 픽셀 처리
       ├─ [비디오 TS]  → _decode_video() → LazyVideoReader
       └─ [일반 TS]    → _get_pixel_array()
                            ├─ ds.pixel_array
                            ├─ YBR 감지 시 → _convert_ybr_to_rgb()
                            └─ 실패 시      → _decode_via_pil() (PIL fallback)
```

### `LazyVideoReader` 동작

```
__getitem__(idx)
  ├─ idx > last_idx  → 순방향: 기존 reader 사용 (빠름)
  └─ idx <= last_idx → 역방향: reader 재오픈 후 ffmpeg seek
```

---

## 실행 방법

### 배포 exe 실행
```
dist\Hyetoria\Hyetoria.exe               ← 더블클릭, Python 설치 불필요
dist\Hyetoria\Hyetoria.exe path\to\file  ← 파일 경로 인수 전달 시 자동 로드
```

> 배포 시 `dist\Hyetoria\` 폴더 전체를 zip으로 묶어 전달

### 소스에서 실행
```bash
cd C:\00_WORK\01_Source\dicom_viewer
python main.py
python main.py path\to\file.dcm   # 파일 직접 열기
```

### Windows 파일 연결 등록 (.dcm 더블클릭으로 열기)
탐색기에서 `.dcm` 파일 우클릭 → **"연결 프로그램" → "다른 앱 선택"** → `dist\Hyetoria.exe` 지정

---

## 빌드 방법

```bash
cd C:\00_WORK\01_Source\dicom_viewer
python -m PyInstaller --onedir --windowed -y ^
  --name "Hyetoria" ^
  --icon "assets/hyetoria.ico" ^
  --copy-metadata imageio ^
  main.py
# 결과물: dist\Hyetoria\Hyetoria.exe
```

> **`--onedir` 사용 이유**: `--onefile`은 실행 시마다 ~62MB 압축 해제 → 수 초 지연.
> `--onedir`는 폴더 형태로 파일이 미리 풀려 있어 즉시 실행됨.

> **`-y` 플래그**: 기존 `dist\Hyetoria\` 폴더 자동 삭제 후 재빌드 (확인 프롬프트 생략).

> **`--copy-metadata imageio` 필수**: `imageio`가 import 시 `importlib.metadata`로 자신의 버전을 조회함.  
> 이 플래그 없이 빌드하면 exe에서 `PackageNotFoundError: No package metadata was found for imageio` 오류 발생.

> **빌드 전 앱 종료 필수**: `dist\Hyetoria\Hyetoria.exe` 실행 중이면 `PermissionError` 발생.

---

## 알려진 제한 사항

| 항목 | 내용 |
|------|------|
| Sequence 내부 Offset | 중첩 태그 offset 미지원 (top-level만) |
| 비디오 역방향 seek | reader 재오픈 필요 → 대형 파일에서 다소 느릴 수 있음 |
| 멀티프레임 컬러 WW/WL | 컬러 프레임은 윈도잉 미적용 (원본 RGB 그대로 표시) |
| HEVC 재생 | ffmpeg 지원 여부에 따라 일부 환경에서 미동작 가능 |

---

## 오류 진단

비디오 디코딩 실패 시 로그 파일 생성:
```
%TEMP%\hyetoria_error.log
```
이미지 패널에도 오류 메시지 + 로그 경로 표시됨.

---

## 향후 개선 아이디어

- [ ] WW/WL 마우스 드래그 조절
- [ ] 멀티프레임 컬러 영상 WW/WL 지원
- [ ] 비디오 seek 최적화 (keyframe index 캐싱)
- [ ] Tag 값 편집 및 저장
- [ ] 여러 파일 탭으로 동시 열기
- [ ] DICOM SR (Structured Report) 텍스트 렌더링
