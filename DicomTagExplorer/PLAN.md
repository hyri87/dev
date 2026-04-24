# 로컬 DICOM 파일 분석 Tool — 개발 계획서

## 개요

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Hyetoria |
| 언어 | Python 3.14.3 |
| 목적 | 로컬 DICOM 파일의 태그 구조 · 이미지 · 헥스 덤프를 분석하는 데스크톱 뷰어 |
| 참조 UI | Victoria DICOM Viewer 스타일 |
| 실행 파일 | `dist/Hyetoria.exe` (단일 exe, `--onefile`) |

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

## 기술 스택

| 역할 | 라이브러리 | 버전 |
|------|-----------|------|
| DICOM 파싱 | `pydicom` | 3.0.2 |
| GUI 프레임워크 | `tkinter` | 표준 라이브러리 |
| 드래그 앤 드롭 | `tkinterdnd2` | 0.4.3 |
| 이미지 렌더링 | `Pillow` | 12.2.0 |
| 수치 연산 (WW/WL) | `numpy` | 2.4.4 |
| 압축 디코딩 | `pylibjpeg[all]` | 2.1.0 |
| 비디오 디코딩 | `imageio[ffmpeg]` | 2.37.3 |
| exe 패키징 | `PyInstaller` | 6.19.0 |

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
│   ├── tag_tree.py      # ttk.Treeview 태그 트리 패널 + 검색 바 + 복사/팝업
│   ├── hex_panel.py     # 헥스 덤프 패널 (lazy scroll)
│   └── image_panel.py   # DICOM 이미지 뷰어 패널 (멀티프레임 · 비디오 재생)
├── assets/
│   └── hyetoria.ico     # 앱 아이콘 (256/128/64/48/32/16px)
├── dist/
│   └── Hyetoria.exe     # 배포용 단일 실행 파일
├── requirements.txt
├── PLAN.md              # 이 문서
└── DEV_DOC.md           # 상세 개발 문서
```

---

## 개발 단계

### Phase 1 — 프로젝트 셋업 ✅
- [x] 프로젝트 폴더 구조 생성
- [x] `requirements.txt` 작성
- [x] 의존성 설치 확인

### Phase 2 — DICOM 파싱 모듈 (`dicom_parser.py`) ✅
- [x] `pydicom`으로 `.dcm` 파일 로드
- [x] 각 태그에서 TAG / VR / Length / Name / Value / Offset 추출
- [x] Sequence(SQ) 타입 태그를 재귀적 트리 구조(dict/list)로 변환
- [x] Pixel Data 태그 분리 (이미지 렌더링용)
- [x] `_collect_offsets()` — 직접 바이너리 파싱으로 top-level offset 수집
  - pydicom 내부 API(`DicomFile`, `data_element_generator`) 미사용 (3.x 호환)
- [x] YBR→RGB 컬러 변환 (`_convert_ybr_to_rgb`)
- [x] PIL fallback 디코딩 (`_decode_via_pil`)
- [x] Lazy import (`_ensure_pydicom()`) — 앱 시작 속도 최적화

### Phase 3 — 태그 트리 패널 (`ui/tag_tree.py`) ✅
- [x] `ttk.Treeview`로 6개 컬럼 구성 (TAG / VR / Length / Name / Value / Offset)
- [x] Sequence 태그는 자식 노드로 재귀 삽입 (파란색 `#0055aa`)
- [x] 최초 오픈 시 모든 노드 collapsed 상태로 표시
- [x] "Expand All" / "Collapse All" 버튼
- [x] 행 클릭 시 해당 태그의 hex offset 위치로 Hex 패널 연동 + 하이라이트
- [x] 홀짝 행 배경색 교대 (`#f5f5f5` / `#ffffff`)
- [x] **Value 복사 기능**
  - 우클릭 컨텍스트 메뉴 (Value 복사 / 행 전체 복사)
  - Ctrl+C 단축키 → Value 복사
- [x] **더블클릭 Value 팝업**
  - 마우스 드래그로 일부 텍스트 선택 가능
  - 팝업 내 더블클릭 → 전체 선택
  - Ctrl+C 복사, Enter / ESC로 닫기

### Phase 4 — 검색 바 (`ui/tag_tree.py` 내장) ✅
- [x] Ctrl+F로 검색 바 표시/숨김
- [x] TAG · VR · Name · Value 대상 대소문자 무시 실시간 검색
- [x] 매치: 노란색(`#ffe566`) / 현재 포커스: 진한 오렌지(`#ff6b00`) — 검정 글자
- [x] 결과가 접힌 Sequence 안에 있으면 부모 노드 자동 펼침 후 스크롤
- [x] 매치 카운터 표시 (`3 / 12`)

### Phase 5 — 헥스 덤프 패널 (`ui/hex_panel.py`) ✅
- [x] 전체 파일 lazy scroll — 파일 크기 제한 없음 (8 KiB 단위 append)
- [x] 형식: `XXXXXXXX  XX XX ... XX  ASCII`
- [x] 다크 테마 (`#1e1e1e` 배경)
- [x] 태그 선택 시 해당 offset으로 자동 스크롤 + `highlight` 태그 하이라이트
  - `sel` 태그 미사용 — `state='disabled'` 위젯은 `sel` 표시 불가

### Phase 6 — 이미지 뷰어 패널 (`ui/image_panel.py`) ✅
- [x] WW/WL 윈도잉 적용 → grayscale 렌더링
- [x] WW/WL 기본값: DICOM 태그 우선, 없으면 min/max 자동
- [x] 패널 리사이즈 시 자동 재렌더링
- [x] 이미지 없는 파일 → "No Image Data" / 오류 메시지 표시
- [x] **멀티프레임**: 슬라이더 + ◀/▶ + ▶/⏸ 재생 + 마우스 휠
- [x] **컬러 영상**: RGB/RGBA 원본 표시, YBR→RGB 자동 변환
- [x] Lazy import (`_ensure_imaging()`) — 앱 시작 속도 최적화

### Phase 7 — 비디오 DICOM 지원 (`dicom_parser.py`) ✅
- [x] MPEG2 / MPEG4 / HEVC 전송 구문 지원 (9종)
- [x] `LazyVideoReader` — on-demand 프레임 디코딩 (RAM 절약)
- [x] FPS 자동 감지: CineRate → RecommendedDisplayFrameRate → FrameTime
- [x] 비디오 디코딩 실패 시 로그 파일 생성 (`%TEMP%\hyetoria_error.log`)

### Phase 8 — 파일 열기 및 D&D (`ui/app.py`, `main.py`) ✅
- [x] 툴바 "파일 열기" 버튼 → `filedialog.askopenfilename`
- [x] 드래그 앤 드롭 (tkinterdnd2, 공백 포함 경로 처리)
- [x] **커맨드라인 인수** — `Hyetoria.exe <filepath>` 자동 로드
  - Windows 파일 연결 등록 후 `.dcm` 더블클릭으로 바로 열기
- [x] 로드 후 타이틀바에 파일 경로, 상태바에 태그 수 / 파일 크기 표시

### Phase 9 — 빌드 및 최적화 ✅
- [x] PyInstaller 단일 `.exe` 패키징 (`--onefile --windowed`)
- [x] 앱 아이콘 (`assets/hyetoria.ico`)
- [x] `--copy-metadata imageio` (PackageNotFoundError 방지)
- [x] Lazy import로 시작 속도 최적화 (~340ms → ~64ms, 소스 기준)

---

## 주요 동작 흐름

```
파일 로드 (버튼 / D&D / argv)
    │
    ▼
dicom_parser.py — pydicom으로 파싱 (lazy import)
    ├── 트리 데이터 → tag_tree.py (Treeview 갱신, 모두 collapse)
    ├── 원시 바이트 → hex_panel.py (헥스 덤프 갱신)
    └── Pixel Data  → image_panel.py (이미지 렌더링, lazy import)

태그 행 클릭
    └── hex_panel.py — 해당 offset으로 스크롤 + highlight 태그

태그 행 더블클릭
    └── Value 팝업 — 텍스트 선택·복사 가능

태그 행 우클릭
    └── 컨텍스트 메뉴 — Value 복사 / 행 전체 복사

Ctrl+F → 검색
    └── tag_tree.py — 실시간 검색 + 매치 하이라이트 + 자동 스크롤
```

---

## 알려진 제한 사항

| 항목 | 내용 |
|------|------|
| Sequence 내부 Offset | 중첩 태그 offset 미지원 (top-level만) |
| 비디오 역방향 seek | reader 재오픈 필요 → 대형 파일에서 다소 느릴 수 있음 |
| 멀티프레임 컬러 WW/WL | 컬러 프레임은 윈도잉 미적용 (원본 RGB 그대로 표시) |
| HEVC 재생 | ffmpeg 지원 여부에 따라 일부 환경에서 미동작 가능 |

---

## 향후 개선 아이디어

- [ ] WW/WL 마우스 드래그 조절
- [ ] 멀티프레임 컬러 영상 WW/WL 지원
- [ ] 비디오 seek 최적화 (keyframe index 캐싱)
- [ ] Tag 값 편집 및 저장
- [ ] 여러 파일 탭으로 동시 열기
- [ ] DICOM SR (Structured Report) 텍스트 렌더링

---

## 참고 사항

- Windows 환경에서 `tkinterdnd2` D&D는 `TkinterDnD.Tk()`를 루트 윈도우로 사용해야 동작함
- `--copy-metadata imageio` 필수 — 없으면 exe에서 `PackageNotFoundError` 발생
- `_collect_offsets()`는 pydicom 내부 API 대신 `struct`로 직접 바이너리 파싱 (pydicom 3.x 호환)
- 헥스 하이라이트는 `highlight` 커스텀 태그 사용 (`sel` 태그는 disabled 위젯에서 미표시)
- 검색 하이라이트는 검정 글자 고정 (흰 글자 사용 시 선택 해제 후 안 보이는 문제 방지)
