"""
Main application window.

Layout
------
Toolbar  : [파일 열기]  |  [Expand All]  [Collapse All]
Left pane (vertical split)
  - top  : TagTreePanel
  - bottom : HexPanel
Right pane : ImagePanel

Drag-and-drop is handled via tkinterdnd2.
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tkinterdnd2 import DND_FILES

from ui.tag_tree   import TagTreePanel
from ui.hex_panel  import HexPanel
from ui.image_panel import ImagePanel


class DicomViewerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('Hyetoria')
        self.root.geometry('1400x860')
        self.root.minsize(900, 600)

        self._setup_ui()
        self._setup_dnd()
        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        # ── toolbar ────────────────────────────────────────────────────
        toolbar = ttk.Frame(self.root, relief='flat')
        toolbar.pack(fill='x', padx=6, pady=(6, 2))

        ttk.Button(toolbar, text='파일 열기', width=10,
                   command=self._open_file).pack(side='left', padx=(0, 4))

        ttk.Separator(toolbar, orient='vertical').pack(
            side='left', fill='y', padx=6)

        ttk.Button(toolbar, text='Expand All',   width=11,
                   command=self._expand_all).pack(side='left', padx=2)
        ttk.Button(toolbar, text='Collapse All', width=11,
                   command=self._collapse_all).pack(side='left', padx=2)

        # status label (right side of toolbar)
        self._status_var = tk.StringVar(value='파일을 열거나 창으로 드래그하세요.')
        ttk.Label(toolbar, textvariable=self._status_var,
                  foreground='#666666').pack(side='right', padx=4)

        # ── main paned window (vertical: top=태그트리 | bottom=헥스+이미지) ──
        v_pane = ttk.PanedWindow(self.root, orient='vertical')
        v_pane.pack(fill='both', expand=True, padx=6, pady=(2, 6))

        # top: tag tree
        self.tag_tree = TagTreePanel(v_pane, on_tag_select=self._on_tag_select)
        v_pane.add(self.tag_tree, weight=6)

        # bottom: horizontal split (hex dump | image viewer)
        h_pane = ttk.PanedWindow(v_pane, orient='horizontal')
        v_pane.add(h_pane, weight=4)

        self.hex_panel = HexPanel(h_pane)
        h_pane.add(self.hex_panel, weight=5)

        self.image_panel = ImagePanel(h_pane)
        h_pane.add(self.image_panel, weight=5)

    # ------------------------------------------------------------------
    # Drag-and-drop
    # ------------------------------------------------------------------

    def _setup_shortcuts(self):
        self.root.bind('<Control-f>', lambda _e: self.tag_tree.show_search())

    def _setup_dnd(self):
        self.root.drop_target_register(DND_FILES)
        self.root.dnd_bind('<<Drop>>', self._on_drop)

    def _on_drop(self, event):
        path = self._parse_dnd_path(event.data)
        if path:
            self._load_file(path)

    @staticmethod
    def _parse_dnd_path(data: str) -> str:
        """
        tkinterdnd2 wraps paths with spaces in {braces}.
        Multiple files are space-separated.  We take the first file only.
        """
        data = data.strip()
        if data.startswith('{'):
            end = data.find('}')
            if end != -1:
                return data[1:end]
        # No braces — might be multiple space-separated paths; take first
        return data.split()[0] if data else ''

    # ------------------------------------------------------------------
    # File opening
    # ------------------------------------------------------------------

    def _open_file(self):
        path = filedialog.askopenfilename(
            title='DICOM 파일 열기',
            filetypes=[
                ('DICOM Files', '*.dcm *.DCM *.ima *.IMA'),
                ('All Files',   '*.*'),
            ],
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str):
        if not os.path.isfile(path):
            messagebox.showerror('오류', f'파일을 찾을 수 없습니다:\n{path}')
            return

        self._status_var.set(f'로딩 중… {os.path.basename(path)}')
        self.root.update_idletasks()

        try:
            from dicom_parser import parse_dicom
            nodes, raw_bytes, pixel_array, pixel_error, ww, wl, fps = parse_dicom(path)
        except Exception as exc:
            messagebox.showerror(
                'DICOM 파싱 오류',
                f'파일을 읽는 중 오류가 발생했습니다:\n{exc}',
            )
            self._status_var.set('로드 실패.')
            return

        self.tag_tree.load_nodes(nodes)
        self.hex_panel.load_bytes(raw_bytes)

        if pixel_array is not None:
            self.image_panel.show_image(pixel_array, ww, wl, fps)
        else:
            msg = pixel_error or 'Pixel Data 없음'
            self.image_panel.show_error(msg)

        tag_count = len(nodes)
        filename  = os.path.basename(path)
        self.root.title(f'Hyetoria — {filename}  [{path}]')
        self._status_var.set(f'{tag_count} tags   |   {len(raw_bytes):,} bytes   |   {filename}')

    # ------------------------------------------------------------------
    # Toolbar callbacks
    # ------------------------------------------------------------------

    def _expand_all(self):
        self.tag_tree.expand_all()

    def _collapse_all(self):
        self.tag_tree.collapse_all()

    def _on_tag_select(self, offset: int, length: int = 4):
        self.hex_panel.scroll_to_offset(offset, length)
