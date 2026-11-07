# -*- coding: utf-8 -*-
"""Блок «Станція (слоти)» панелі «Кодплаг → APRS»: до 8 APRS-конфігів станції ДОКУМЕНТА (CodeplugAPRSConfig_t, 64 Б на слот): назва, SSID, шляхи,
символ, коментар, позиція, неточність, частота TX й прапорці (300 бод / без звуку / позиція / QSY). Формати й довжини полів не змінено --
кодування ті самі, що й в імпорті CSV (codeplug_edit.py). Правки лягають у документ; у рацію -- лише дією «Записати кодплаг у рацію».
Символ задається двома числами (як у кодплазі) -- і графічно: «Обрати символ...» відкриває сітку тих самих іконок, що малює рація (CPS-fix3 V2).
Бікон (режим, інтервал, потужність) і шумодав приймача -- у сусідньому блоці тієї ж панелі (p_aprs.py): вони пишуться в рацію напряму, поза кодплагом."""
import tkinter as tk
from tkinter import ttk, messagebox

import aprs_symbols as asym
import codeplug_edit as ced
import cps_csv as cc
import gui_dialogs as gd
import gui_theme as gt
import table_edit as te

from .layout import FitTable
from .panel import HINT_NO_DOC

TEXT_FIELDS = (("name", "Назва (до 8 байтів)", 12), ("ssid", "SSID (0..15)", 5), ("via1", "Via 1", 8), ("via1_ssid", "Via 1 SSID (0..15)", 5),
               ("via2", "Via 2", 8), ("via2_ssid", "Via 2 SSID (0..15)", 5), ("icon_table", "Таблиця символів (0 основна, 1 додаткова)", 6),
               ("icon", "Символ (індекс = код - 33, 0..93)", 6), ("comment", "Коментар (до 24 символів)", 30), ("ambiguity", "Неточність позиції (0..7)", 5),
               ("lat", "Широта, ° (±90)", 12), ("lon", "Довгота, ° (±180)", 12), ("tx_freq", "Частота TX, МГц (0 -- не задано)", 12))
FLAG_FIELDS = (("use_position", "Використовувати позицію з цього конфіга"), ("qsy", "Додавати QSY-інформацію (частоту)"),
               ("baud300", "300 бод (замість 1200)"), ("silent", "Без звуку при передачі бікона"))


class StationBlock(ttk.LabelFrame):
    """Рамка в панелі APRS: працює з документом (host.doc), сама нічого в рацію не пише."""

    def __init__(self, parent, host):
        super().__init__(parent, text="Станція (слоти) -- частина документа")
        self.host = host
        self.shell = host.shell
        self.vars = {k: tk.StringVar() for k, _l, _w in TEXT_FIELDS}
        self.flags = {k: tk.BooleanVar() for k, _l in FLAG_FIELDS}
        self.current = None            # 0-based слот, який редагується; None -- новий
        self._new_mode = False
        self._can_apply = False
        self._loading = False
        self._item_slot = {}
        ttk.Label(self, text=("Конфіги станції APRS у кодплазі (до 8). Зміни потрапляють у документ; рація змінюється лише за дією «Записати кодплаг у "
                              "рацію» над розділами."), wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(4, 2))
        self.hint = ttk.Label(self, text=HINT_NO_DOC, foreground=gt.P["muted"])

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=4)
        self._top = top
        tbl = FitTable(top, [("n", "№", 40, 0), ("name", "Назва", 140, 0), ("comment", "Коментар", 300, 1)], height=5)
        self.tree = tbl.tree
        tbl.pack(side="left", fill="x", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        side = ttk.Frame(top)
        side.pack(side="left", padx=8, anchor="n")
        self.new_button = ttk.Button(side, text="Новий слот", command=self._on_new)
        self.new_button.pack(fill="x", pady=2)
        self.del_button = ttk.Button(side, text="Видалити слот", command=self._on_delete)
        self.del_button.pack(fill="x", pady=2)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=6)
        self.apply_button = ttk.Button(bar, text="Застосувати до документа", command=self._on_apply)
        self.apply_button.pack(side="left")
        self.reload_button = ttk.Button(bar, text="Повернути значення з документа", command=self._reload_form)
        self.reload_button.pack(side="left", padx=8)
        self.msg = ttk.Label(self, text="", wraplength=620, justify="left")
        self.msg.pack(anchor="w", padx=8, pady=(0, 4))
        self.form = ttk.LabelFrame(self, text="Слот")
        self.form.pack(fill="x", padx=8, pady=6)
        self.entries = {}
        for key, label, width in TEXT_FIELDS:
            self.vars[key].trace_add("write", lambda *_: self._validate())
            if key == "icon_table":
                continue                       # Y1: числових полів символу нема -- таблиця й код живуть лише в прихованих змінних, їх задає сітка
            f = ttk.Frame(self.form)
            f.pack(fill="x", padx=8, pady=2)
            if key == "icon":
                self._build_symbol_row(f)
                continue
            ttk.Label(f, text=label, width=32).pack(side="left")
            e = ttk.Entry(f, textvariable=self.vars[key], width=width)
            e.pack(side="left")
            self.entries[key] = e
        self.checks = {}
        for key, label in FLAG_FIELDS:
            c = ttk.Checkbutton(self.form, text=label, variable=self.flags[key], command=self._validate)
            c.pack(anchor="w", padx=8, pady=1)
            self.checks[key] = c
        self.on_document_changed()

    # --- символ (Y1): лише іконка, підпис під нею й «Обрати символ...»; чисел для вводу нема ---

    def _build_symbol_row(self, row):
        self._symbol_img = None
        ttk.Label(row, text="Символ APRS", width=32).pack(side="left", anchor="n")
        col = ttk.Frame(row)
        col.pack(side="left")
        self.symbol_preview = tk.Label(col, bd=1, relief="solid", bg=gt.P["field"], fg=gt.P["muted"], text="--", width=6, height=3)
        self.symbol_preview.pack(anchor="w")
        self.symbol_info = ttk.Label(col, text="", wraplength=360, justify="left", foreground=gt.P["muted"])
        self.symbol_info.pack(anchor="w", pady=(2, 4))
        self.symbol_button = ttk.Button(col, text="Обрати символ...", command=self._on_pick_symbol)
        self.symbol_button.pack(anchor="w")
        if not asym.available():
            self.symbol_button.config(state="disabled")
            self.symbol_info.config(text="Набір іконок недоступний у цій збірці CPS: символ не можна ні переглянути, ні змінити.")
        for k in ("icon_table", "icon"):
            self.vars[k].trace_add("write", lambda *_: self._update_symbol())

    def _symbol_numbers(self):
        try:
            return int(self.vars["icon_table"].get()), int(self.vars["icon"].get())
        except ValueError:
            return None

    def _update_symbol(self):
        if not asym.available():
            return
        nums = self._symbol_numbers()
        img, color = None, gt.P["muted"]
        if nums is None:
            text, color = "Символ у слоті не розпізнано. Оберіть його: «Обрати символ...».", gt.P["warn"]
        else:
            if asym.is_known(*nums):
                img = asym.photo_raw(self, nums[0], nums[1], scale=2)
                text = asym.symbol_text(*nums)
            else:
                text, color = asym.unknown_text(*nums), gt.P["warn"]
        self._symbol_img = img            # PhotoImage треба тримати посиланням
        if img is not None:
            self.symbol_preview.config(image=img, width=img.width(), height=img.height(), text="")
        else:
            self.symbol_preview.config(image="", text="--", width=6, height=3, fg=gt.P["muted"])
        self.symbol_info.config(text=text, foreground=color)

    def _on_pick_symbol(self):
        nums = self._symbol_numbers()
        if nums is None or not asym.is_known(*nums):
            nums = (0 if not nums or nums[0] == 0 else 1, ord(">") - 33)      # сітка відкривається на звичайному символі ('>', індекс 29), не на «порожньому»
            known = False
        else:
            known = True
        got = asym.pick_symbol(self.shell, nums[0], nums[1], preselect=known)
        if got is not None:
            self.vars["icon_table"].set(str(got[0]))
            self.vars["icon"].set(str(got[1]))

    # --- список слотів ---

    @property
    def doc(self):
        return self.host.doc

    def on_document_changed(self):
        d = self.doc
        self.tree.delete(*self.tree.get_children())
        self._item_slot = {}
        if d is None:
            self.hint.pack(anchor="w", padx=8, pady=(0, 4), before=self._top)
            self._reload_form()
            return
        self.hint.pack_forget()
        for slot, rec in d.image.aprs():
            item = self.tree.insert("", "end", values=(slot + 1, cc.readable_text(rec[:ced.APRS_NAME_LEN]), ced.aprs_values(rec)["comment"]))
            self._item_slot[item] = slot
        self._reload_form()

    def _on_select(self, _e):
        sel = self.tree.selection()
        if sel and self._item_slot.get(sel[0]) != self.current or (sel and self._new_mode):
            self._new_mode = False
            self.current = self._item_slot.get(sel[0])
            self._reload_form()

    def _on_new(self):
        if self.doc is None:
            return
        self._new_mode = True
        self.current = None
        self.tree.selection_set(())
        self._reload_form()

    def _reload_form(self):
        """Поля форми з документа: вибраний слот; у режимі «новий слот» -- типові значення; порожній документ -- одразу новий слот."""
        d = self.doc
        if d is None:
            self._new_mode, self.current = False, None
            self._set_form({})
        else:
            slots = dict(d.image.aprs())
            if not self._new_mode and self.current not in slots:
                self.current = min(slots) if slots else None
            if self.current is None:
                self._new_mode = True
                self._set_form(ced.new_aprs_values())
            else:
                self._new_mode = False
                self._set_form(ced.aprs_values(slots[self.current]))
                for item, slot in self._item_slot.items():
                    if slot == self.current and self.tree.selection() != (item,):
                        self.tree.selection_set(item)
        self._validate()

    def _set_form(self, values):
        self._loading = True
        try:
            for key, _l, _w in TEXT_FIELDS:
                self.vars[key].set(str(values.get(key, "")))
            for key, _l in FLAG_FIELDS:
                self.flags[key].set(bool(values.get(key, False)))
        finally:
            self._loading = False
        self._update_symbol()

    def _values(self):
        v = {k: self.vars[k].get() for k, _l, _w in TEXT_FIELDS}
        v.update({k: bool(self.flags[k].get()) for k, _l in FLAG_FIELDS})
        return v

    # --- перевірка й застосування ---

    def _validate(self):
        if self._loading:
            return
        d = self.doc
        can = False
        text, color = "", gt.P["muted"]
        if d is not None:
            try:
                res = ced.apply_aprs_slot(d.image, self.current, self._values())
                if res.any_change():
                    can = True
                    text, color = "Готово до застосування: %s." % "; ".join(t for _s, t in (res.added + res.changed)), gt.P["ok"]
                else:
                    text = "Змін відносно документа немає."
            except ced.CodeplugEditError as e:
                text, color = "\n".join(e.problems), gt.P["err"]
        self._can_apply = can
        self.msg.config(text=text, foreground=color)
        busy = self.shell.busy
        self.apply_button.config(state="normal" if (can and not busy) else "disabled")
        self.new_button.config(state="normal" if (d is not None and not busy and len(d.image.aprs()) < 8) else "disabled")
        self.del_button.config(state="normal" if (d is not None and not busy and self.current is not None) else "disabled")
        self.reload_button.config(state="normal" if d is not None else "disabled")
        for e in self.entries.values():
            e.config(state="normal" if d is not None else "disabled")
        if asym.available():
            self.symbol_button.config(state="normal" if d is not None else "disabled")
        for c in self.checks.values():
            c.config(state="normal" if d is not None else "disabled")

    def after_refresh(self):
        self._validate()

    def _on_apply(self):
        d = self.doc
        if d is None or self.shell.busy or not self._can_apply:
            return
        try:
            d.edit_aprs_slot(self.current, self._values())
        except ced.CodeplugEditError as e:
            messagebox.showerror("APRS-слот", str(e), parent=self.shell)
            return
        if self._new_mode:                       # новий слот зайняв наступний за останнім
            self._new_mode = False
            self.current = len(d.image.aprs()) - 1
        self.on_document_changed()
        self.shell.set_status("APRS-слот змінено в документі.", "ok")

    def _on_delete(self):
        """Те саме, що видалення зони / списку прийому (table_edit.delete_entity + gd.delete_choice): є канали з посиланням на слот -- вибір
        «Скасувати» / «Видалити разом із посиланнями» (поле APRS у цих каналах стане «None»); посилань нема -- звичайне підтвердження."""
        d = self.doc
        if d is None or self.shell.busy or self.current is None:
            return
        slot = self.current
        prob = te.aprs_delete_problem(d.image, slot)
        if prob:
            messagebox.showerror("APRS-слот", prob, parent=self.shell)
            return
        name = cc.readable_text(dict(d.image.aprs())[slot][:8])
        refs = te.references(d.image, "aprs", slot)
        cascade = gd.delete_choice(self.shell, "APRS-слот №%d" % (slot + 1), name, refs.text() if refs else None)
        if cascade is None:
            return
        try:
            res = te.delete_entity(d.image, "aprs", slot, cc.system_decimal_point(), cascade=cascade)
            d.apply(res)
        except te.TableEditError as e:
            messagebox.showerror("APRS-слот", "\n".join(e.problems), parent=self.shell)
            return
        self.current = None
        self.on_document_changed()
        self.shell.set_status("APRS-слот видалено з документа.", "ok")
