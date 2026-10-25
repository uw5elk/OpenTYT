# -*- coding: utf-8 -*-
"""Каркас редакторів кодплага з документа (CPS-fix2 / етап 3): «список записів ліворуч, форма праворуч, кнопки Додати / Дублювати /
Перейменувати / Видалити» (T0.5). Правка кожного запису застосовується до документа ОДРАЗУ (окремої кнопки «ОК» нема): панель лише збирає
значення й викликає функцію table_edit.* -- вона проганяє рядки через cps_csv.import_csv (T0.2), тобто перевірки ті самі, що в імпорті CSV.

Видалення запису, на який хтось посилається, ніколи не мовчазне (T0.3): показується, хто посилається, і пропонується «Скасувати» або
«Видалити разом із посиланнями»."""
import tkinter as tk
from tkinter import ttk

import cps_csv as cc
import gui_dialogs as gd
import gui_theme as gt
import table_edit as te

from .layout import FitTable, equal_buttons
from .panel import HINT_NO_DOC, Panel


class EditorPanel(Panel):
    """Нащадок задає: kind, title, hint_text, columns, entities(img), build_form(parent), load_form(), ask_new(img)."""
    scroll = True
    doc_panel = True
    kind = ""                       # tg / zone / channel
    noun = "запис"                  # «список прийому», «зона», «канал»
    columns = ()                    # [(id, заголовок, ширина, розтягувати?)]
    hint_text = ""
    list_width = 330                # (застаріле: тепер ширина списку -- межа PanedWindow; лишається для сумісності)

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.dp = cc.system_decimal_point()
        self.sel = None                         # ідентифікатор вибраного запису (слот / біт / номер)
        self._item_ident = {}
        self._loading = False
        self._filter = tk.StringVar()
        self.header(self.title, self.hint_text)
        self.hint = ttk.Label(self, text=HINT_NO_DOC, foreground=gt.P["muted"])
        self.msg = ttk.Label(self, text="", wraplength=640, justify="left")
        self.body = ttk.Frame(self)
        self.msg.pack(anchor="w", fill="x", padx=gt.PAD, pady=(0, 4))
        self.body.pack(fill="both", expand=True, padx=gt.PAD, pady=(0, gt.GAP))
        # R36 B2: список і форма розділені межею, яку можна тягнути (подвійне клацання -- типове положення, положення запам'ятовується)
        self.pane = ttk.PanedWindow(self.body, orient="horizontal")
        self.pane.pack(fill="both", expand=True)
        left = ttk.Frame(self.pane)
        self.left = left
        ttk.Label(left, text="Фільтр за назвою:").pack(anchor="w")
        ttk.Entry(left, textvariable=self._filter).pack(fill="x", pady=(0, 4))
        self._filter.trace_add("write", lambda *_: self._fill_list())
        spec = [(cid, text, width, 1 if stretch else 0) for cid, text, width, stretch in self.columns]
        self.table = FitTable(left, spec, height=10)
        self.tree = self.table.tree
        self.table.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.count_label = ttk.Label(left, text="", foreground=gt.P["muted"])
        self.count_label.pack(anchor="w", pady=2)
        bars = ttk.Frame(left)
        bars.pack(fill="x", pady=2)
        self.btn_add = ttk.Button(bars, text="Додати...", command=self._on_add)
        self.btn_dup = ttk.Button(bars, text="Дублювати", command=self._on_dup)
        self.btn_ren = ttk.Button(bars, text="Перейменувати...", command=self._on_rename)
        self.btn_del = ttk.Button(bars, text="Видалити...", command=self._on_delete)
        equal_buttons(self.btn_add, self.btn_dup, self.btn_ren, self.btn_del)
        for i, b in enumerate((self.btn_add, self.btn_dup, self.btn_ren, self.btn_del)):
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
            self.reg(b, radio=False, doc=True)
        bars.columnconfigure(0, weight=1, uniform="btn")
        bars.columnconfigure(1, weight=1, uniform="btn")
        self._bars = bars
        self.right = ttk.Frame(self.pane)
        self.pane.add(left, weight=0)
        self.pane.add(self.right, weight=1)
        self.right.bind("<Configure>", self._on_right_resize)
        self.build_form(self.right)
        self.shell.register_pane(self.key, self.pane, default=self._default_left, min_first=self._min_left, min_second=lambda: 320)
        self.on_document_changed()

    def _on_right_resize(self, e):
        """Права частина (форма) змінила ширину -- від руху межі чи вікна: форма перелаштовується, довгі підписи переносяться за її шириною."""
        self.relayout(max(200, e.width))
        self.rewrap()

    def _min_left(self):
        """Найменша ширина списку: дві кнопки в ряд і стовпці без обрізання заголовків (довгі значення прокручуються)."""
        heads = sum(max(w, 40) for _c, _t, w, _s in self.columns)
        return max(self._bars.winfo_reqwidth(), min(heads + 24, 330))

    def _default_left(self):
        """Типова ширина списку: стовпці за вмістом (але від 260 до 460 px)."""
        nat = sum(self.tree.required().values()) + 24
        return max(260, min(460, nat))

    def relayout(self, form_width):
        """Нащадки перелаштовують форму під доступну ширину."""

    # --- що задають нащадки -------------------------------------------------------------------------------------------

    def entities(self, img):
        """[(ident, значення колонок)] у порядку кодплага."""
        raise NotImplementedError

    def build_form(self, parent):
        raise NotImplementedError

    def load_form(self):
        """Заповнити форму за self.sel і поточним документом."""
        raise NotImplementedError

    def ask_new(self, img):
        """Діалог «Додати»: повертає fn(img) -> ImportResult або None (скасовано)."""
        raise NotImplementedError

    def clear_form(self):
        """Форма без вибраного запису / без документа."""

    # --- документ ---------------------------------------------------------------------------------------------------------

    def ids(self, img):
        return [i for i, _v in self.entities(img)]

    def on_document_changed(self):
        d = self.doc
        if d is None:
            self.sel = None
            self._fill_list()                  # R33: без документа в схованій таблиці не лишаються рядки попереднього
            self.body.pack_forget()
            self.msg.pack_forget()
            self.hint.pack(anchor="w", padx=gt.PAD, pady=(0, 4), after=self._note_box)
            self.clear_form()
            return
        self.hint.pack_forget()
        if not self.body.winfo_manager():
            self.msg.pack(anchor="w", fill="x", padx=gt.PAD, pady=(0, 4))
            self.body.pack(fill="both", expand=True, padx=gt.PAD, pady=(0, gt.GAP))
        self._fill_list()
        self.load_form()

    def _fill_list(self):
        d = self.doc
        self.tree.delete(*self.tree.get_children())
        self._item_ident = {}
        if d is None:
            return
        needle = self._filter.get().strip().casefold()
        ents = self.entities(d.image)
        shown, pick = 0, None
        for ident, values in ents:
            if needle and not any(needle in str(v).casefold() for v in values):
                continue
            item = self.tree.insert("", "end", values=values)
            self._item_ident[item] = ident
            shown += 1
            if ident == self.sel:
                pick = item
        if self.sel not in [i for i, _v in ents]:
            self.sel = None
        self.count_label.config(text=("Показано %d з %d" % (shown, len(ents))) if needle else ("Усього: %d" % len(ents)))
        if pick is not None:
            self._loading = True
            try:
                self.tree.selection_set(pick)
                self.tree.see(pick)
            finally:
                self._loading = False

    def _on_select(self, _e):
        if self._loading:
            return
        sel = self.tree.selection()
        ident = self._item_ident.get(sel[0]) if sel else None
        if ident == self.sel:
            return
        self.sel = ident
        self.show_message("")
        self.load_form()
        self.after_refresh()

    # --- повідомлення ------------------------------------------------------------------------------------------------------

    def show_message(self, text, kind="muted"):
        color = {"muted": gt.P["muted"], "ok": gt.P["ok"], "err": gt.P["err"], "warn": gt.P["warn"]}[kind]
        self.msg.config(text=text, foreground=color)

    def after_refresh(self):
        enabled = self.doc is not None and not self.shell.busy
        one = enabled and self.sel is not None
        for b in (self.btn_dup, self.btn_ren, self.btn_del):
            b.config(state="normal" if one else "disabled")
        self.btn_add.config(state="normal" if enabled else "disabled")
        self.form_state(enabled and self.sel is not None)

    def form_state(self, enabled):
        """Нащадки вмикають/вимикають поля форми."""

    # --- застосування до документа ------------------------------------------------------------------------------------------

    def run_edit(self, fn, select_new=False, select=None):
        """fn(img) -> ImportResult. True -- правку прийнято (або змін не було). TableEditError показується в рядку повідомлення."""
        d = self.doc
        if d is None or self.shell.busy:
            return False
        before = set(self.ids(d.image))
        try:
            res = fn(d.image)
        except te.TableEditError as e:
            self.show_message("\n".join(e.problems), "err")
            return False
        if select_new:
            new = [i for i in self.ids(res.image) if i not in before]
            if new:
                self.sel = new[0]
        elif select is not None:
            self.sel = select
        changed = d.apply(res)
        lines = ["%s: %s" % x for x in (res.added + res.changed)] + ["Видалено -- %s: %s" % x for x in res.removed]
        if not changed:
            self.show_message("Змін відносно документа немає.", "muted")
        else:
            self.show_message("; ".join(lines[:6]) + (" ..." if len(lines) > 6 else ""), "ok")
            if res.warnings:
                self.show_message(self.msg.cget("text") + "\n" + "\n".join("Увага: " + w for w in res.warnings), "warn")
            self.shell.set_status("Документ змінено: %s." % (lines[0] if lines else "правка"), "ok")
        return True

    # --- кнопки -------------------------------------------------------------------------------------------------------------

    def _on_add(self):
        d = self.doc
        if d is None or self.shell.busy:
            return
        fn = self.ask_new(d.image)
        if fn is not None:
            self.run_edit(fn, select_new=True)

    def _on_dup(self):
        d = self.doc
        if d is None or self.shell.busy or self.sel is None:
            return
        ident = self.sel
        self.run_edit(lambda img: te.duplicate_entity(img, self.kind, ident, self.dp), select_new=True)

    def _on_rename(self):
        d = self.doc
        if d is None or self.shell.busy or self.sel is None:
            return
        ident = self.sel
        old = dict(te.entity_names(d.image, self.kind)).get(ident, "")
        name = gd.name_dialog(self.shell, "Перейменувати", "Нова назва (%s):" % self.noun, old,
                              check=lambda t: te.name_problem(d.image, self.kind, t, exclude=ident), ok="Перейменувати")
        if name is not None and name != old:
            self.run_edit(lambda img: te.rename_entity(img, self.kind, ident, name, self.dp))

    def _on_delete(self):
        d = self.doc
        if d is None or self.shell.busy or self.sel is None:
            return
        ident = self.sel
        name = dict(te.entity_names(d.image, self.kind)).get(ident, "")
        refs = te.references(d.image, self.kind, ident)
        cascade = gd.delete_choice(self.shell, self.noun, name, refs.text() if refs else None)
        if cascade is None:
            return
        self.sel = None
        self.run_edit(lambda img: te.delete_entity(img, self.kind, ident, self.dp, cascade=cascade))


class MembersEditor(EditorPanel):
    """Редактор складу з упорядкованих посилань (список прийому: контакти; зона: канали): дві колонки «Доступні» ↔ «У списку»."""
    members_noun = "елементів"
    list_width = 270

    # що задають нащадки
    def candidates(self, img):
        """[(номер, підпис)] усіх можливих елементів."""
        raise NotImplementedError

    def members(self, img, ident):
        raise NotImplementedError

    def limit(self, img):
        raise NotImplementedError

    def build_form(self, parent):
        self.title_label = ttk.Label(parent, text="", font=("Segoe UI", 11, "bold"), wraplength=380, justify="left")
        self.title_label.pack(anchor="w", pady=(0, 2))
        self.counter = ttk.Label(parent, text="")
        self.counter.pack(anchor="w", pady=(0, 6))
        cols = ttk.Frame(parent)
        cols.pack(fill="both", expand=True)
        self.cols = cols
        self._wide = None
        self._lbl_avail = ttk.Label(cols, text="Доступні")
        self._lbl_cur = ttk.Label(cols, text="У %s" % self.members_where)
        self._avail_filter = tk.StringVar()
        self._avail_filter.trace_add("write", lambda *_: self._fill_lists())
        self._avail_fr, self.avail_lb = self._listbox(cols)
        self._cur_fr, self.cur_lb = self._listbox(cols)
        self._mid = ttk.Frame(cols)
        self.btn_in = ttk.Button(self._mid, text="Додати →", command=self._on_in)
        self.btn_out = ttk.Button(self._mid, text="← Прибрати", command=self._on_out)
        self.btn_up = ttk.Button(self._mid, text="Вгору ↑", command=lambda: self._on_move(-1))
        self.btn_down = ttk.Button(self._mid, text="Вниз ↓", command=lambda: self._on_move(1))
        self._mid_buttons = (self.btn_in, self.btn_out, self.btn_up, self.btn_down)
        equal_buttons(*self._mid_buttons)
        self._filter_fr = ttk.Frame(cols)
        ttk.Label(self._filter_fr, text="Фільтр:").pack(side="left")
        ttk.Entry(self._filter_fr, textvariable=self._avail_filter).pack(side="left", fill="x", expand=True, padx=4)
        self._layout_members(True)
        self.avail_lb.bind("<Double-Button-1>", lambda _e: self._on_in())
        self.cur_lb.bind("<Double-Button-1>", lambda _e: self._on_out())
        self._avail_nums, self._cur_nums = [], []
        self._reselect = []

    members_where = "списку"

    def relayout(self, form_width):
        wide = form_width >= 520
        if wide != self._wide:
            self._layout_members(wide)

    def _layout_members(self, wide):
        """Широко: «Доступні | кнопки | У списку» в один ряд; вузько: ті самі частини одна під одною (кнопки в рядок)."""
        self._wide = wide
        cols = self.cols
        for w in (self._lbl_avail, self._lbl_cur, self._avail_fr, self._cur_fr, self._mid, self._filter_fr):
            w.grid_forget()
        for b in self._mid_buttons:
            b.grid_forget()
        for i in range(6):
            cols.rowconfigure(i, weight=0)
        for i in range(3):
            cols.columnconfigure(i, weight=0, uniform="")
        if wide:
            cols.columnconfigure(0, weight=1, uniform="m")
            cols.columnconfigure(2, weight=1, uniform="m")
            cols.rowconfigure(1, weight=1)
            self._lbl_avail.grid(row=0, column=0, sticky="w")
            self._lbl_cur.grid(row=0, column=2, sticky="w")
            self._avail_fr.grid(row=1, column=0, sticky="nsew")
            self._mid.grid(row=1, column=1, padx=8)
            self._cur_fr.grid(row=1, column=2, sticky="nsew")
            self._filter_fr.grid(row=2, column=0, sticky="ew", pady=(4, 0))
            for i, b in enumerate(self._mid_buttons):
                b.grid(row=i, column=0, sticky="ew", pady=3)
        else:
            cols.columnconfigure(0, weight=1)
            cols.rowconfigure(2, weight=1)
            cols.rowconfigure(5, weight=1)
            self._lbl_avail.grid(row=0, column=0, sticky="w")
            self._filter_fr.grid(row=1, column=0, sticky="ew", pady=(2, 2))
            self._avail_fr.grid(row=2, column=0, sticky="nsew")
            self._mid.grid(row=3, column=0, pady=4)
            self._lbl_cur.grid(row=4, column=0, sticky="w")
            self._cur_fr.grid(row=5, column=0, sticky="nsew")
            for i, b in enumerate(self._mid_buttons):
                b.grid(row=i // 2, column=i % 2, padx=2, pady=1, sticky="ew")

    def _listbox(self, parent):
        fr = ttk.Frame(parent)
        lb = tk.Listbox(fr, selectmode="extended", exportselection=False, height=8, activestyle="none", width=10)
        gt.style_text(lb)
        sb = gt.AutoScrollbar(fr, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        fr.rowconfigure(0, weight=1)
        fr.columnconfigure(0, weight=1)
        return fr, lb

    def clear_form(self):
        self.title_label.config(text="")
        self.counter.config(text="")
        for lb in (self.avail_lb, self.cur_lb):
            lb.delete(0, "end")
        self._avail_nums, self._cur_nums = [], []

    def load_form(self):
        d = self.doc
        if d is None or self.sel is None:
            self.clear_form()
            self.title_label.config(text="Оберіть запис ліворуч або натисніть «Додати...»" if d is not None else "")
            return
        self._labels = dict(self.candidates(d.image))
        self._cur_nums = list(self.members(d.image, self.sel))
        name = dict(te.entity_names(d.image, self.kind)).get(self.sel, "")
        self.title_label.config(text="«%s»" % name)
        self._fill_lists()
        self.after_refresh()

    def _fill_lists(self):
        d = self.doc
        if d is None or self.sel is None:
            return
        lim = self.limit(d.image)
        keep = list(self._reselect)
        self._reselect = []
        self.cur_lb.delete(0, "end")
        for n in self._cur_nums:
            self.cur_lb.insert("end", self._labels.get(n, "#%d (відсутній)" % n))
        for i, n in enumerate(self._cur_nums):
            if n in keep:
                self.cur_lb.selection_set(i)
        needle = self._avail_filter.get().strip().casefold()
        self.avail_lb.delete(0, "end")
        self._avail_nums = []
        for n, label in self._labels.items():
            if n in self._cur_nums or (needle and needle not in label.casefold()):
                continue
            self._avail_nums.append(n)
            self.avail_lb.insert("end", label)
        full = len(self._cur_nums) >= lim
        self.counter.config(text="%d з %d %s%s. Порядок має значення." % (len(self._cur_nums), lim, self.members_noun,
                                                                           " -- ліміт кодплага досягнуто" if full else ""),
                            foreground=gt.P["warn"] if full else gt.P["fg"])

    def form_state(self, enabled):
        st = "normal" if enabled else "disabled"
        for b in (self.btn_in, self.btn_out, self.btn_up, self.btn_down):
            b.config(state=st)

    def _apply_members(self, numbers, reselect=()):
        ident = self.sel
        self._reselect = list(reselect)
        self.run_edit(lambda img: te.set_members(img, self.kind, ident, numbers, self.dp))
        self._reselect = []

    def _on_in(self):
        d = self.doc
        if d is None or self.sel is None or self.shell.busy:
            return
        pick = [self._avail_nums[i] for i in self.avail_lb.curselection()]
        if not pick:
            self.show_message("Оберіть ліворуч, що додати.", "warn")
            return
        new = self._cur_nums + pick
        lim = self.limit(d.image)
        if len(new) > lim:
            self.show_message("Не можна додати: у %s може бути не більше %d %s -- такий ліміт кодплага (зараз %d, додаєте %d)." % (
                self.members_where, lim, self.members_noun, len(self._cur_nums), len(pick)), "err")
            return
        self._apply_members(new, reselect=pick)

    def _on_out(self):
        if self.doc is None or self.sel is None or self.shell.busy:
            return
        pick = {self._cur_nums[i] for i in self.cur_lb.curselection()}
        if not pick:
            self.show_message("Оберіть праворуч, що прибрати.", "warn")
            return
        new = [n for n in self._cur_nums if n not in pick]
        if not new:
            self.show_message("Не можна прибрати всі елементи: порожній запис рація не використовує. Щоб прибрати його повністю, натисніть "
                              "«Видалити...».", "err")
            return
        self._apply_members(new)

    def _on_move(self, step):
        if self.doc is None or self.sel is None or self.shell.busy:
            return
        idx = list(self.cur_lb.curselection())
        if not idx:
            self.show_message("Оберіть праворуч, що пересунути.", "warn")
            return
        order = list(self._cur_nums)
        marked = [self._cur_nums[i] for i in idx]
        rng = idx if step < 0 else reversed(idx)
        for i in rng:
            j = i + step
            if 0 <= j < len(order) and order[j] not in marked:
                order[i], order[j] = order[j], order[i]
        if order == self._cur_nums:
            return
        self._apply_members(order, reselect=marked)
