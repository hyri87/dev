"""
Image viewer panel.

단일 / 멀티프레임 / MPEG2 / MPEG4 / HEVC 모두 지원.
멀티프레임: 슬라이더 + ◀/▶ + ▶/⏸ 재생 버튼 + 마우스휠 탐색.
컬러 영상(RGB)은 그레이스케일 변환 없이 원본 색상으로 표시.

레이아웃 (grid)
  row 0 : Canvas          (fill, expand)
  row 1 : 슬라이더 바     (멀티프레임만 표시)
  row 2 : Info bar        (WW/WL / 프레임 정보)
"""

import tkinter as tk
from tkinter import ttk

# 무거운 라이브러리는 첫 이미지 표시 시 lazy import
np = None
Image = None
ImageTk = None


def _ensure_imaging():
    global np, Image, ImageTk
    if np is None:
        import numpy
        np = numpy
    if Image is None:
        from PIL import Image as _Im, ImageTk as _ImTk
        Image = _Im
        ImageTk = _ImTk


class ImagePanel(ttk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        self._pixel_array = None
        self._ww: float | None = None
        self._wl: float | None = None
        self._photo = None

        self._num_frames: int  = 1
        self._frame_idx:  int  = 0
        self._fps:        float = 10.0
        self._playing:    bool  = False
        self._after_id           = None   # pending after() call

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=0)
        self.grid_columnconfigure(0, weight=1)

        # ── Canvas ────────────────────────────────────────────────────
        self.canvas = tk.Canvas(self, bg='#111111', highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.canvas.bind('<Configure>',  self._on_resize)
        self.canvas.bind('<MouseWheel>', self._on_mousewheel)
        self.canvas.bind('<Button-4>',   self._on_mousewheel)
        self.canvas.bind('<Button-5>',   self._on_mousewheel)

        # ── 슬라이더 바 (멀티프레임 전용) ────────────────────────────
        slider_bar = tk.Frame(self, bg='#1a1a1a')
        slider_bar.grid(row=1, column=0, sticky='ew')
        slider_bar.grid_remove()
        self._slider_bar = slider_bar

        # ▶/⏸ 재생 버튼
        self._play_btn = ttk.Button(slider_bar, text='▶', width=2,
                                     command=self._toggle_play)
        self._play_btn.pack(side='left', padx=(4, 0))

        ttk.Button(slider_bar, text='◀', width=2,
                   command=self._prev_frame).pack(side='left', padx=(2, 0))

        self._frame_var = tk.IntVar(value=0)
        self._slider = ttk.Scale(
            slider_bar,
            from_=0, to=0,
            orient='horizontal',
            variable=self._frame_var,
            command=self._on_slider_move,
        )
        self._slider.pack(side='left', fill='x', expand=True, padx=4)

        ttk.Button(slider_bar, text='▶', width=2,
                   command=self._next_frame).pack(side='left', padx=(0, 4))

        self._frame_label_var = tk.StringVar(value='')
        tk.Label(slider_bar, textvariable=self._frame_label_var,
                 bg='#1a1a1a', fg='#cccccc',
                 font=('Courier New', 9), width=10).pack(side='left', padx=(0, 6))

        # ── Info bar ─────────────────────────────────────────────────
        self._info_var = tk.StringVar(value='')
        tk.Label(
            self,
            textvariable=self._info_var,
            bg='#222222', fg='#cccccc',
            font=('Courier New', 9),
            anchor='center',
        ).grid(row=2, column=0, sticky='ew')

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_image(self, pixel_array, ww: float | None, wl: float | None,
                   fps: float = 10.0):
        _ensure_imaging()
        self._stop_play()
        self._pixel_array = pixel_array
        self._ww  = ww
        self._wl  = wl
        self._fps = max(1.0, fps)
        self._frame_idx = 0

        self._num_frames = self._count_frames(pixel_array)

        if self._num_frames > 1:
            self._slider.configure(to=self._num_frames - 1)
            self._frame_var.set(0)
            self._slider_bar.grid()
            self._update_frame_label()
        else:
            self._slider_bar.grid_remove()
            self._frame_label_var.set('')

        self._render()

    def show_error(self, message: str):
        """이미지 로드 실패 시 원인 메시지를 캔버스에 표시."""
        self._stop_play()
        self._pixel_array = None
        self._photo = None
        self._num_frames = 1
        self._frame_idx  = 0
        self._slider_bar.grid_remove()
        self.canvas.delete('all')
        cw = self.canvas.winfo_width()  or 300
        ch = self.canvas.winfo_height() or 200
        self.canvas.create_text(
            cw // 2, ch // 2 - 16,
            text='이미지를 표시할 수 없습니다',
            fill='#cc4444',
            font=('Arial', 12, 'bold'),
        )
        self.canvas.create_text(
            cw // 2, ch // 2 + 12,
            text=message,
            fill='#888888',
            font=('Arial', 9),
            width=max(cw - 20, 100),
        )
        self._info_var.set('')

    def clear(self):
        self._stop_play()
        self._pixel_array = None
        self._ww = None
        self._wl = None
        self._photo = None
        self._num_frames = 1
        self._frame_idx  = 0
        self._slider_bar.grid_remove()
        self.canvas.delete('all')
        self._info_var.set('')

    # ------------------------------------------------------------------
    # Play / Pause
    # ------------------------------------------------------------------

    def _toggle_play(self):
        if self._playing:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self):
        if self._num_frames <= 1:
            return
        self._playing = True
        self._play_btn.configure(text='⏸')
        self._play_loop()

    def _stop_play(self):
        self._playing = False
        if hasattr(self, '_play_btn'):
            self._play_btn.configure(text='▶')
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _play_loop(self):
        if not self._playing:
            return
        next_idx = (self._frame_idx + 1) % self._num_frames
        self._go_to_frame(next_idx)
        delay_ms = max(1, int(1000.0 / self._fps))
        self._after_id = self.after(delay_ms, self._play_loop)

    # ------------------------------------------------------------------
    # Frame navigation
    # ------------------------------------------------------------------

    def _prev_frame(self):
        self._stop_play()
        self._go_to_frame(self._frame_idx - 1)

    def _next_frame(self):
        self._stop_play()
        self._go_to_frame(self._frame_idx + 1)

    def _on_slider_move(self, value):
        idx = int(float(value))
        if idx != self._frame_idx:
            self._stop_play()
            self._frame_idx = idx
            self._update_frame_label()
            self._render()

    def _on_mousewheel(self, event):
        if self._num_frames <= 1:
            return
        self._stop_play()
        if hasattr(event, 'num'):
            delta = -1 if event.num == 5 else 1
        else:
            delta = -1 if event.delta < 0 else 1
        self._go_to_frame(self._frame_idx - delta)

    def _go_to_frame(self, idx: int):
        idx = max(0, min(self._num_frames - 1, idx))
        if idx == self._frame_idx:
            return
        self._frame_idx = idx
        self._frame_var.set(idx)
        self._update_frame_label()
        self._render()

    def _update_frame_label(self):
        self._frame_label_var.set(f'{self._frame_idx + 1} / {self._num_frames}')

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _on_resize(self, _event):
        self._render()

    def _render(self):
        self.canvas.delete('all')
        self._photo = None

        if self._pixel_array is None:
            cw = self.canvas.winfo_width()  or 200
            ch = self.canvas.winfo_height() or 200
            self.canvas.create_text(
                cw // 2, ch // 2,
                text='No Image Data',
                fill='#666666',
                font=('Arial', 14),
            )
            self._info_var.set('')
            return

        frame = self._extract_frame(self._pixel_array, self._frame_idx)
        cw    = self.canvas.winfo_width()  or 400
        ch    = self.canvas.winfo_height() or 400

        # ── 컬러 프레임 (RGB / RGBA) ──────────────────────────────────
        if frame.ndim == 3 and frame.shape[2] in (3, 4):
            rgb = frame[:, :, :3].astype(np.uint8)
            img = Image.fromarray(rgb, mode='RGB')
            img.thumbnail((cw, ch), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.create_image(cw // 2, ch // 2, anchor='center',
                                      image=self._photo)
            info = ''

        # ── 그레이스케일 프레임 ──────────────────────────────────────
        else:
            arr = frame if frame.ndim == 2 else frame[:, :, 0]
            ww, wl = self._resolve_window(arr, self._ww, self._wl)
            low  = wl - ww / 2.0
            high = wl + ww / 2.0
            arr  = np.clip(arr.astype(float), low, high)
            arr  = ((arr - low) / (high - low) * 255.0).astype(np.uint8)
            img  = Image.fromarray(arr, mode='L')
            img.thumbnail((cw, ch), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.create_image(cw // 2, ch // 2, anchor='center',
                                      image=self._photo)
            info = f'WW = {int(ww):>6}    WL = {int(wl):>6}'

        if self._num_frames > 1:
            frame_info = f'Frame {self._frame_idx + 1} / {self._num_frames}  ({self._fps:.1f} fps)'
            info = f'{info}    {frame_info}' if info else frame_info
        self._info_var.set(info)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_frames(arr: np.ndarray | None) -> int:
        if arr is None:
            return 1
        if arr.ndim == 2:
            return 1
        if arr.ndim == 3:
            return 1 if arr.shape[2] in (3, 4) else arr.shape[0]
        if arr.ndim == 4:
            return arr.shape[0]
        return 1

    @staticmethod
    def _extract_frame(arr: np.ndarray, idx: int) -> np.ndarray:
        if arr.ndim == 2:
            return arr
        if arr.ndim == 3:
            return arr if arr.shape[2] in (3, 4) else arr[idx]
        if arr.ndim == 4:
            return arr[idx]
        return arr

    @staticmethod
    def _resolve_window(arr: np.ndarray,
                        ww: float | None,
                        wl: float | None) -> tuple[float, float]:
        if ww is None or wl is None:
            mn   = float(arr.min())
            mx   = float(arr.max())
            span = mx - mn or 1.0
            return span, mn + span / 2.0
        return ww, wl
