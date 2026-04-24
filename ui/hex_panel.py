"""
Hex-dump panel — lazy scrolling, full-file support.

전체 파일을 청크 단위로 필요할 때만 렌더링한다.
  - 스크롤이 하단 90% 에 닿으면 다음 청크를 자동 추가 (append-only)
  - scroll_to_offset() 호출 시 해당 offset이 미로드 상태면 먼저 로드 후 이동

레이아웃 (한 줄):
    XXXXXXXX  XX XX ... XX XX  ASCII...
"""

import tkinter as tk
from tkinter import ttk

_BYTES_PER_LINE  = 16
_INITIAL_BYTES   = 8_192   # 초기 512 lines
_CHUNK_BYTES     = 8_192   # 스크롤마다 추가할 크기 (512 lines)
_LOAD_TRIGGER    = 0.90    # 스크롤 하단이 이 비율 이상이면 다음 청크 로드

_HEX_START = 10            # 줄 내 hex 블록 시작 컬럼
_HEX_BYTE  = 3             # "XX " — 바이트당 3 chars


class HexPanel(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._raw: bytes = b''
        self._loaded_end: int = 0      # 현재 Text에 렌더된 마지막 바이트 위치
        self._loading: bool = False    # 재진입 방지
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.text = tk.Text(
            self,
            font=('Courier New', 9),
            state='disabled',
            wrap='none',
            bg='#1e1e1e',
            fg='#d4d4d4',
            insertbackground='white',
            selectbackground='#3a6ea5',
            selectforeground='#ffffff',
            exportselection=False,   # 포커스 잃어도 선택 유지
            cursor='arrow',
        )

        self._vsb = ttk.Scrollbar(self, orient='vertical',   command=self.text.yview)
        hsb       = ttk.Scrollbar(self, orient='horizontal', command=self.text.xview)

        # yscrollcommand 를 가로채서 하단 근접 여부를 감지한다.
        self.text.configure(
            yscrollcommand=self._on_yscroll,
            xscrollcommand=hsb.set,
        )

        self.text.grid(row=0, column=0, sticky='nsew')
        self._vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 색상 태그
        self.text.tag_configure('offset_col', foreground='#858585')
        self.text.tag_configure('ascii_col',  foreground='#ce9178')
        self.text.tag_configure('highlight',  background='#264f78', foreground='#ffffff')
        self.text.tag_configure('note',       foreground='#6a9955',
                                              font=('Courier New', 9, 'italic'))

    # ------------------------------------------------------------------
    # yscrollcommand 인터셉트 — 하단 감지
    # ------------------------------------------------------------------

    def _on_yscroll(self, first: str, last: str):
        self._vsb.set(first, last)
        if float(last) >= _LOAD_TRIGGER and self._loaded_end < len(self._raw):
            self.text.after_idle(self._load_chunk)

    # ------------------------------------------------------------------
    # 데이터 로드
    # ------------------------------------------------------------------

    def load_bytes(self, raw: bytes):
        self._raw = raw
        self._loaded_end = 0
        self._loading = False

        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.configure(state='disabled')

        self._load_chunk(initial=True)

    def _load_chunk(self, initial: bool = False):
        """다음 청크를 Text 위젯 끝에 추가한다."""
        if self._loading:
            return
        if self._loaded_end >= len(self._raw):
            return

        self._loading = True
        chunk_size = _INITIAL_BYTES if initial else _CHUNK_BYTES
        start = self._loaded_end
        end   = min(start + chunk_size, len(self._raw))

        self.text.configure(state='normal')

        # 기존 "로딩 중" 안내 줄 제거
        if self.text.mark_names().__contains__('chunk_end'):
            self.text.delete('chunk_end', 'end')

        # 새 줄 삽입
        sep = 10 + _BYTES_PER_LINE * 3 - 1   # = 57, hex↔ascii 구분 위치
        for byte_offset in range(start, end, _BYTES_PER_LINE):
            chunk_line = self._raw[byte_offset: byte_offset + _BYTES_PER_LINE]
            hex_part   = ' '.join(f'{b:02X}' for b in chunk_line)
            hex_part   = hex_part.ljust(_BYTES_PER_LINE * 3 - 1)
            ascii_part = ''.join(chr(b) if 0x20 <= b < 0x7F else '.' for b in chunk_line)
            line = f'{byte_offset:08X}  {hex_part}  {ascii_part}'

            self.text.insert('end', line[:8],       'offset_col')
            self.text.insert('end', line[8:sep])
            self.text.insert('end', line[sep:sep+2])
            self.text.insert('end', line[sep+2:],   'ascii_col')
            self.text.insert('end', '\n')

        self._loaded_end = end

        # 아직 남은 바이트가 있으면 안내 표시 + mark 저장
        remaining = len(self._raw) - self._loaded_end
        if remaining > 0:
            self.text.mark_set('chunk_end', 'end-1c')
            self.text.mark_gravity('chunk_end', 'left')
            self.text.insert(
                'end',
                f'\n  … {remaining:,} bytes 더 있음 — 스크롤하면 로드됩니다 …\n',
                'note',
            )

        self.text.configure(state='disabled')
        self._loading = False

    # ------------------------------------------------------------------
    # 특정 offset 으로 스크롤 + 하이라이트
    # ------------------------------------------------------------------

    def scroll_to_offset(self, offset: int, length: int = 4):
        """
        offset 위치로 스크롤하고 헤더+value 영역을 마우스 선택처럼 표시.
        hex 열과 ASCII 열 양쪽 모두 sel 태그로 강조한다.
        """
        if not self._raw or offset < 0 or offset >= len(self._raw):
            return

        # 미로드 구간이면 먼저 로드
        if offset >= self._loaded_end:
            target = offset + _CHUNK_BYTES
            while self._loaded_end <= target and self._loaded_end < len(self._raw):
                self._load_chunk()

        # 헤더(최대 12 byte) 포함 전체 태그 영역 선택
        total      = max(length, 1) + 12
        end_offset = min(offset + total, self._loaded_end)

        # ASCII 열 시작: "XXXXXXXX  " (10) + hex (16*3-1=47) + "  " (2) = col 59
        _ASCII_START = _HEX_START + _BYTES_PER_LINE * _HEX_BYTE + 1  # = 59

        self.text.tag_remove('highlight', '1.0', 'end')

        cur = offset
        while cur < end_offset:
            line_idx     = cur // _BYTES_PER_LINE
            byte_in_line = cur % _BYTES_PER_LINE
            bytes_this   = min(end_offset - cur, _BYTES_PER_LINE - byte_in_line)
            line_no      = line_idx + 1

            # hex 영역
            col_start = _HEX_START + byte_in_line * _HEX_BYTE
            col_end   = col_start + bytes_this * _HEX_BYTE - 1
            self.text.tag_add('highlight', f'{line_no}.{col_start}', f'{line_no}.{col_end}')

            # ASCII 영역
            asc_start = _ASCII_START + byte_in_line
            asc_end   = asc_start + bytes_this
            self.text.tag_add('highlight', f'{line_no}.{asc_start}', f'{line_no}.{asc_end}')

            cur += bytes_this

        self.text.see(f'{offset // _BYTES_PER_LINE + 1}.0')

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self):
        self._raw = b''
        self._loaded_end = 0
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.configure(state='disabled')
