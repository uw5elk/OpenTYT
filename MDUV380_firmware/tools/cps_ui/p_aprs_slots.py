# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → APRS-слоти»: до 8 APRS-конфігів станції ДОКУМЕНТА (CodeplugAPRSConfig_t, 64 Б на слот): назва, SSID, шляхи,
символ, коментар, позиція, неточність, частота TX й прапорці (300 бод / без звуку / позиція / QSY). Формати й довжини полів не змінено --
кодування ті самі, що й в імпорті CSV (codeplug_edit.py). Правки лягають у документ; у рацію -- лише дією «Записати в рацію».
Бікон (режим, інтервал, потужність) і шумодав приймача -- окремо, у «Налаштування рації → APRS: бікон і позивний» (вони пишуться в рацію
напряму, поза кодплагом)."""
import tkinter as tk
from tkinter import ttk, messagebox

import codeplug_edit as ced
import cps_csv as cc
import gui_dialogs as gd
import gui_theme as gt

from .panel import HINT_NO_DOC, Panel

TEXT_FIELDS = (("name", "Назва (до 8 байтів)", 12), ("ssid", "SSID (0..15)", 5), ("via1", "Via 1", 8), ("via1_ssid", "Via 1 SSID (0..15)", 5),
               ("via2", "Via 2", 8), ("via2_ssid", "Via 2 SSID (0..15)", 5), ("icon_table", "Таблиця символів (0..255)", 6),
               ("icon", "Символ (0..255)", 6), ("comment", "Коментар (до 24 символів)", 30), ("ambiguity", "Неточність позиції (0..7)", 5),
               ("lat", "Широта, ° (±90)", 12), ("lon", "Довгота, ° (±180)", 12), ("tx_freq", "Частота TX, МГц (0 -- не задано)", 12))
FLAG_FIELDS = (("use_position", "Використовувати позицію з цього конфіга"), ("qsy", "Додавати QSY-інформацію (частоту)"),
               ("baud300", "300 бод (замість 1200)"), ("silent", "Без звуку при передачі бікона"))


class AprsSlotsPanel(Panel):
    key = "aprs_slots"
    title = "APRS-слоти"
    doc_panel = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.vars = {k: tk.StringVar() for k, _l, _w in TEXT_FIELDS}
        self.flags = {k: tk.BooleanVar() for k, _l in FLAG_FIELDS}
        self.current = None            # 0-based слот, який редагується; None -- новий
        self._new_mode = False
        self._can_apply = False
        self._loading = False
        self._item_slot = {}
        self.header("APRS-слоти", "Конфіги станції APRS у кодплазі (до %d). Зміни потрапляють у документ; рація змінюється лише за дією «Записати в "
                                  "рацію» над розділами." % 8)
        self.hint = ttk.Label(self, text=HINT_NO_DOC, foreground=gt.P["muted"])

        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=4)
        self.tree = ttk.Treeview(top, columns=("n", "name", "comment"), show="headings", selectmode="browse", height=5)
        for c, t, w in (("n", "№", 40), ("name", "Назва", 140), ("comment", "Коментар", 300)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(side="left", fill="x", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        side = ttk.Frame(top)
        side.pack(side="left", padx=8, anchor="n")
        self.new_button = ttk.Button(side, text="Новий слот", command=self._on_new)
        self.new_button.pack(fill="x", pady=2)
        self.del_button = ttk.Button(side, text="Видалити слот", command=self._on_delete)
        self.del_button.pack(fill="x", pady=2)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=6)
        self.apply_button = ttk.Button(bar, text="Застосувати до документа", command=self._on_apply)
        self.apply_button.pack(side="left")
        self.reload_button = ttk.Button(bar, text="Повернути значення з документа", command=self._reload_form)
        self.reload_button.pack(side="left", padx=8)
        self.msg = ttk.Label(self, text="", wraplength=620, justify="left")
        self.msg.pack(anchor="w", padx=12, pady=(0, 4))
        self.form = ttk.LabelFrame(self, text="Слот")
        self.form.pack(fill="x", padx=12, pady=6)
        self.entries = {}
        for key, label, width in TEXT_FIELDS:
            f = ttk.Frame(self.form)
            f.pack(fill="x", padx=8, pady=2)
            ttk.Label(f, text=label, width=32).pack(side="left")
            e = ttk.Entry(f, textvariable=self.vars[key], width=width)
            e.pack(side="left")
            self.entries[key] = e
            self.vars[key].trace_add("write", lambda *_: self._validate())
        self.checks = {}
        for key, label in FLAG_FIELDS:
            c = ttk.Checkbutton(self.form, text=label, variable=self.flags[key], command=self._validate)
            c.pack(anchor="w", padx=8, pady=1)
            self.checks[key] = c
        self.on_document_changed()

    # --- список слотів ---

    def on_document_changed(self):
        d = self.doc
        self.tree.delete(*self.tree.get_children())
        self._item_slot = {}
        if d is None:
            self.hint.pack(anchor="w", padx=12, pady=(0, 4), after=self._note_box)
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
        d = self.doc
        if d is None or self.shell.busy or self.current is None:
            return
        slot = self.current
        users = ced.aprs_users(d.image, slot)
        text = "Видалити APRS-слот №%d з документа?" % (slot + 1)
        if users:
            text += "\n\nЙого використовують канали: %s. Посилання в них стане порожнім." % ", ".join("№%d «%s»" % u for u in users[:8])
        if not gd.confirm_dialog(self.shell, "Видалити слот?", text, yes="Видалити", no="Скасувати"):
            return
        try:
            d.delete_aprs_slot(slot)
        except ced.CodeplugEditError as e:
            messagebox.showerror("APRS-слот", str(e), parent=self.shell)
            return
        self.current = None
        self.on_document_changed()
        self.shell.set_status("APRS-слот видалено з документа.", "ok")
