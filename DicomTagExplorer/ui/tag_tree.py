"""
Tag tree panel — displays DICOM tags in a collapsible Treeview.

Columns : TAG | VR | Length | Name | Value | Offset

Search bar (F5)
  - 태그/VR/Name/Value 전체에서 대소문자 무시 검색
  - Enter / ▶ : 다음 결과,  Shift+Enter / ◀ : 이전 결과
  - ESC / ✕   : 검색 닫기
"""

import tkinter as tk
from tkinter import ttk


class TagTreePanel(ttk.Frame):
    def __init__(self, parent, on_tag_select=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._on_tag_select = on_tag_select

        self._row_counter   = 0
        self._item_base_tags: dict[str, tuple] = {}   # item_id → base tags

        # search state
        self._match_items: list[str] = []
        self._match_idx: int = -1

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        columns = ('vr', 'length', 'name', 'value', 'offset')
        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show='tree headings',
            selectmode='browse',
        )

        # --- headings ---
        self.tree.heading('#0',     text='TAG',    anchor='w')
        self.tree.heading('vr',     text='VR',     anchor='w')
        self.tree.heading('length', text='Length', anchor='e')
        self.tree.heading('name',   text='Name',   anchor='w')
        self.tree.heading('value',  text='Value',  anchor='w')
        self.tree.heading('offset', text='Offset', anchor='w')

        # --- column widths ---
        self.tree.column('#0',     width=130, stretch=False, anchor='w')
        self.tree.column('vr',     width=40,  stretch=False, anchor='w')
        self.tree.column('length', width=65,  stretch=False, anchor='e')
        self.tree.column('name',   width=210, stretch=True,  anchor='w')
        self.tree.column('value',  width=220, stretch=True,  anchor='w')
        self.tree.column('offset', width=85,  stretch=False, anchor='w')

        # --- scrollbars ---
        vsb = ttk.Scrollbar(self, orient='vertical',   command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # --- row colour tags (configure before match tags so match wins) ---
        self.tree.tag_configure('odd',           background='#f5f5f5')
        self.tree.tag_configure('even',          background='#ffffff')
        self.tree.tag_configure('seq',           foreground='#0055aa')
        self.tree.tag_configure('match',         background='#ffe566', foreground='#000000')
        self.tree.tag_configure('current_match', background='#ff6b00', foreground='#000000')

        # --- selection callback ---
        self.tree.bind('<<TreeviewSelect>>', self._on_select)

        # --- copy value ---
        self.tree.bind('<Control-c>',       self._copy_value)
        self.tree.bind('<Button-3>',        self._show_context_menu)
        self.tree.bind('<Double-Button-1>', self._show_value_popup)

        self._context_menu = tk.Menu(self, tearoff=0)
        self._context_menu.add_command(label='Value 복사', command=self._copy_value)
        self._context_menu.add_command(label='행 전체 복사', command=self._copy_row)

        # --- search bar (hidden by default) ---
        self._build_search_bar()

    def _build_search_bar(self):
        bar = ttk.Frame(self, relief='groove', padding=(4, 3))
        # row=2, spans both tree and scrollbar columns
        bar.grid(row=2, column=0, columnspan=2, sticky='ew')
        bar.grid_remove()   # hidden initially
        self._search_bar = bar

        ttk.Label(bar, text='검색:').pack(side='left', padx=(0, 4))

        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(bar, textvariable=self._search_var, width=28)
        self._search_entry.pack(side='left', padx=(0, 4))
        self._search_entry.bind('<Return>',         lambda _e: self._step(+1))
        self._search_entry.bind('<Shift-Return>',   lambda _e: self._step(-1))
        self._search_entry.bind('<Escape>',         lambda _e: self.hide_search())
        self._search_var.trace_add('write',         lambda *_: self._run_search())

        ttk.Button(bar, text='◀', width=2, command=lambda: self._step(-1)).pack(side='left')
        ttk.Button(bar, text='▶', width=2, command=lambda: self._step(+1)).pack(side='left', padx=(2, 6))

        self._match_label_var = tk.StringVar(value='')
        ttk.Label(bar, textvariable=self._match_label_var,
                  foreground='#555555', width=10).pack(side='left')

        ttk.Button(bar, text='✕', width=2,
                   command=self.hide_search).pack(side='right', padx=(4, 0))

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_nodes(self, nodes: list):
        """Replace all tree content with *nodes*. All items start collapsed."""
        self.tree.delete(*self.tree.get_children())
        self._item_base_tags.clear()
        self._row_counter = 0
        self._clear_search_state()
        self._insert_nodes('', nodes)

    def _insert_nodes(self, parent_id: str, nodes: list):
        for node in nodes:
            is_seq   = bool(node.get('children'))
            row_tag  = 'odd' if self._row_counter % 2 else 'even'
            base_tags = (row_tag, 'seq') if is_seq else (row_tag,)
            self._row_counter += 1

            item_id = self.tree.insert(
                parent_id, 'end',
                text=node['tag'],
                values=(
                    node['vr'],
                    node['length'],
                    node['name'],
                    node['value'],
                    node['offset'],
                ),
                open=False,
                tags=base_tags,
            )
            self._item_base_tags[item_id] = base_tags

            if is_seq:
                self._insert_nodes(item_id, node['children'])

    # ------------------------------------------------------------------
    # Expand / Collapse all
    # ------------------------------------------------------------------

    def expand_all(self):
        self._set_open('', True)

    def collapse_all(self):
        self._set_open('', False)

    def _set_open(self, parent: str, state: bool):
        for item in self.tree.get_children(parent):
            self.tree.item(item, open=state)
            self._set_open(item, state)

    # ------------------------------------------------------------------
    # Search bar — show / hide
    # ------------------------------------------------------------------

    def show_search(self):
        self._search_bar.grid()
        self._search_entry.focus_set()
        self._search_entry.select_range(0, 'end')

    def hide_search(self):
        self._search_bar.grid_remove()
        self._clear_highlights()
        self._clear_search_state()
        self.tree.focus_set()

    # ------------------------------------------------------------------
    # Search logic
    # ------------------------------------------------------------------

    def _run_search(self):
        """Called whenever the search entry text changes."""
        self._clear_highlights()
        query = self._search_var.get().strip().lower()
        if not query:
            self._clear_search_state()
            return

        self._match_items = []
        self._walk_and_match('', query)
        self._match_idx = 0 if self._match_items else -1
        self._apply_highlights()
        self._jump_to_current()

    def _walk_and_match(self, parent: str, query: str):
        """Recursively walk all tree items and collect matching ones."""
        for item in self.tree.get_children(parent):
            tag_text = self.tree.item(item, 'text') or ''
            vr, length, name, value, offset = self.tree.item(item, 'values')
            haystack = f'{tag_text} {vr} {name} {value}'.lower()
            if query in haystack:
                self._match_items.append(item)
            self._walk_and_match(item, query)

    def _step(self, direction: int):
        """Navigate to next (+1) or previous (-1) match."""
        if not self._match_items:
            return
        self._match_idx = (self._match_idx + direction) % len(self._match_items)
        self._apply_highlights()
        self._jump_to_current()

    def _apply_highlights(self):
        """Paint all matches yellow, current match orange."""
        for i, item in enumerate(self._match_items):
            base = self._item_base_tags.get(item, ())
            if i == self._match_idx:
                self.tree.item(item, tags=base + ('current_match',))
            else:
                self.tree.item(item, tags=base + ('match',))

        n = len(self._match_items)
        if n == 0:
            self._match_label_var.set('결과 없음')
        else:
            self._match_label_var.set(f'{self._match_idx + 1} / {n}')

    def _jump_to_current(self):
        """Expand parent chain and scroll current match into view."""
        if self._match_idx < 0 or not self._match_items:
            return
        item = self._match_items[self._match_idx]
        # expand all ancestors
        parent = self.tree.parent(item)
        chain  = []
        while parent:
            chain.append(parent)
            parent = self.tree.parent(parent)
        for ancestor in reversed(chain):
            self.tree.item(ancestor, open=True)
        self.tree.see(item)
        self.tree.selection_set(item)

    def _clear_highlights(self):
        for item in self._match_items:
            base = self._item_base_tags.get(item, ())
            self.tree.item(item, tags=base)

    def _clear_search_state(self):
        self._match_items = []
        self._match_idx   = -1
        self._match_label_var.set('') if hasattr(self, '_match_label_var') else None

    # ------------------------------------------------------------------
    # Selection → hex panel callback
    # ------------------------------------------------------------------

    def _on_select(self, _event):
        if not self._on_tag_select:
            return
        sel = self.tree.selection()
        if not sel:
            return
        offset_str = self.tree.set(sel[0], 'offset')
        length_str = self.tree.set(sel[0], 'length')
        if offset_str:
            try:
                offset = int(offset_str, 16)
                length = int(length_str) if length_str and length_str.isdigit() else 4
                self._on_tag_select(offset, length)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Copy helpers
    # ------------------------------------------------------------------

    def _selected_item(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _copy_value(self, _event=None):
        item = self._selected_item()
        if not item:
            return
        value = self.tree.set(item, 'value')
        self.clipboard_clear()
        self.clipboard_append(value)

    def _copy_row(self, _event=None):
        item = self._selected_item()
        if not item:
            return
        tag    = self.tree.item(item, 'text')
        vr     = self.tree.set(item, 'vr')
        length = self.tree.set(item, 'length')
        name   = self.tree.set(item, 'name')
        value  = self.tree.set(item, 'value')
        offset = self.tree.set(item, 'offset')
        row = f'{tag}\t{vr}\t{length}\t{name}\t{value}\t{offset}'
        self.clipboard_clear()
        self.clipboard_append(row)

    def _show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self._context_menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    # Value popup (더블클릭)
    # ------------------------------------------------------------------

    def _show_value_popup(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return

        tag_text = self.tree.item(item, 'text')
        name     = self.tree.set(item, 'name')
        value    = self.tree.set(item, 'value')

        popup = tk.Toplevel(self)
        popup.title('Value')
        popup.resizable(True, True)
        popup.transient(self.winfo_toplevel())

        # 헤더 레이블
        header = f'{tag_text}  {name}' if name else tag_text
        lbl = tk.Label(popup, text=header, anchor='w',
                       font=('Segoe UI', 9, 'bold'))
        lbl.pack(fill='x', padx=10, pady=6)

        # 선택 가능한 Text 위젯 — state='normal' 유지, 키 입력만 차단
        frame = tk.Frame(popup, bd=1, relief='sunken')
        frame.pack(fill='both', expand=True, padx=10, pady=2)

        txt = tk.Text(
            frame,
            font=('Courier New', 10),
            wrap='word',
            height=5,
            bd=0,
            bg='#f8f8f8',
            fg='#1a1a1a',
            insertwidth=0,
            selectbackground='#3a8ee6',
            selectforeground='#ffffff',
        )
        vsb = tk.Scrollbar(frame, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        txt.pack(side='left', fill='both', expand=True)

        txt.insert('1.0', value)

        # 편집 차단 (선택·복사는 허용)
        def _block_edit(e):
            if e.keysym in ('c', 'C') and (e.state & 0x4):
                return  # Ctrl+C 통과
            if e.keysym in ('a', 'A') and (e.state & 0x4):
                return  # Ctrl+A 통과
            return 'break'
        txt.bind('<Key>', _block_edit)

        # 더블클릭 → 전체 선택
        def _select_all(e):
            txt.tag_add('sel', '1.0', 'end-1c')
            return 'break'
        txt.bind('<Double-Button-1>', _select_all)

        # 닫기 버튼
        btn_frame = tk.Frame(popup)
        btn_frame.pack(fill='x', padx=10, pady=6)
        tk.Button(btn_frame, text='닫기', width=8,
                  command=popup.destroy).pack(side='right')

        # 팝업 위치: 화면 중앙 기준, 클릭 위치 근처
        popup.update_idletasks()
        pw = max(popup.winfo_reqwidth(), 400)
        ph = popup.winfo_reqheight()
        popup.geometry(f'{pw}x{ph}')
        x = self.winfo_rootx() + self.winfo_width() // 2 - pw // 2
        y = self.winfo_rooty() + event.y + 20
        popup.geometry(f'+{x}+{y}')

        txt.focus_set()
        for w in (popup, txt):
            w.bind('<Escape>', lambda _e: popup.destroy())
            w.bind('<Return>', lambda _e: popup.destroy())
