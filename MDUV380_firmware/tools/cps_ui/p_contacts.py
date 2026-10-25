# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Контакти» (R33, Q1): контакти (цифрові) документа -- назва, TG / ID, тип виклику. Додати / дублювати / перейменувати / видалити,
змінити ID і тип. Рядки ті самі, що в Contacts.csv, і ідуть через ту саму перевірку імпорту (table_edit.py -> cps_csv.import_csv). Раніше ці правки
жили всередині таблиць «Перегляду кодплага»; тепер -- окремий розділ у тому самому каркасі, що DTMF-контакти й списки прийому (EditorPanel).
Видалення контакту, на який посилаються списки прийому чи канали, ніколи не мовчазне (T0.3: показується, хто посилається)."""
import tkinter as tk
from tkinter import ttk

import codeplug_viewer_gui as cvg
import contact_edit as ce
import gui_theme as gt
import table_edit as te

from .editor_base import EditorPanel
from .layout import FlowFrame


class ContactsPanel(EditorPanel):
    key = "contacts"
    title = "Контакти"
    kind = "contact"
    noun = "контакт"
    hint_text = ("Цифрові контакти кодплага: назва, TG / ID і тип виклику (група / приват / всім). Зміни потрапляють у документ одразу; рація змінюється "
                 "лише за дією «Записати в рацію».")
    columns = (("num", "№", 46, False), ("name", "Назва", 170, True), ("id", "TG / ID", 90, False), ("type", "Тип", 70, False))

    def entities(self, img):
        return [(s, (s + 1, name, did, ce.CALL_TYPE_LABELS[ty])) for s, name, did, ty, _ts in te.contact_rows(img)]

    def build_form(self, parent):
        self.id_var = tk.StringVar()
        self.type_var = tk.StringVar(value=ce.CALL_TYPE_LABELS[0])
        self.form_title = ttk.Label(parent, text="", font=("Segoe UI", 11, "bold"), wraplength=380, justify="left")
        self.form_title.pack(anchor="w", pady=(0, 6))
        box = ttk.LabelFrame(parent, text="TG / ID і тип виклику")
        box.pack(fill="x", padx=(0, 8))
        row = FlowFrame(box)
        row.pack(fill="x", padx=gt.PAD - 4, pady=6)
        id_pair = ttk.Frame(row)
        ttk.Label(id_pair, text="TG / ID:").pack(side="left")
        self.id_entry = ttk.Entry(id_pair, textvariable=self.id_var, width=12)
        self.id_entry.pack(side="left", padx=(4, 0))
        type_pair = ttk.Frame(row)
        ttk.Label(type_pair, text="Тип:").pack(side="left")
        labels = list(ce.CALL_TYPE_LABELS.values())
        self.type_box = ttk.Combobox(type_pair, textvariable=self.type_var, values=labels, state="readonly", width=max(len(x) for x in labels) + 4)
        self.type_box.pack(side="left", padx=4)
        self.apply_btn = ttk.Button(row, text="Застосувати", command=self.commit)
        row.add(id_pair)
        row.add(type_pair)
        row.add(self.apply_btn)
        self.info = ttk.Label(box, text="", wraplength=420, justify="left", foreground=gt.P["muted"])
        self.info.pack(anchor="w", padx=8, pady=(0, 6))
        self.id_entry.bind("<Return>", lambda _e: self.commit())
        self.id_var.trace_add("write", lambda *_: self._check())
        self.type_box.bind("<<ComboboxSelected>>", lambda _e: self._check())
        self.refs = ttk.Label(parent, text="", wraplength=420, justify="left", foreground=gt.P["muted"])
        self.refs.pack(anchor="w", pady=8)
        ttk.Label(parent, text="Назва змінюється кнопкою «Перейменувати...», новий контакт -- «Додати...». Щоб прибрати контакт, натисніть «Видалити...».",
                  wraplength=420, justify="left", foreground=gt.P["muted"]).pack(anchor="w")

    def _current(self):
        d = self.doc
        if d is None or self.sel is None:
            return None
        return next((r for r in te.contact_rows(d.image) if r[0] == self.sel), None)

    def clear_form(self):
        self._loading = True
        try:
            self.id_var.set("")
            self.type_var.set(ce.CALL_TYPE_LABELS[0])
        finally:
            self._loading = False
        self.form_title.config(text="")
        self.info.config(text="")
        self.refs.config(text="")
        self.form_state(False)

    def load_form(self):
        cur = self._current()
        if cur is None:
            self.clear_form()
            if self.doc is not None:
                self.form_title.config(text="Оберіть контакт ліворуч або натисніть «Додати...»")
            return
        slot, name, did, ty, _ts = cur
        self.form_title.config(text="№%d «%s»" % (slot + 1, name))
        self._loading = True
        try:
            self.id_var.set(str(did))
            self.type_var.set(ce.CALL_TYPE_LABELS[ty])
        finally:
            self._loading = False
        refs = te.references(self.doc.image, "contact", slot)
        self.refs.config(text=("Використовується:\n" + refs.text()) if refs else "Ніхто не посилається на цей контакт.")
        self._check()
        self.after_refresh()

    def _typed(self):
        rev = {v: k for k, v in ce.CALL_TYPE_LABELS.items()}
        return rev.get(self.type_var.get(), 0)

    def _check(self):
        cur = self._current()
        if cur is None or self._loading:
            return
        prob = te.contact_id_problem(self.id_var.get())
        self.info.config(text=prob or "", foreground=gt.P["err"])
        changed = prob is None and (int(self.id_var.get()) != cur[2] or self._typed() != cur[3])
        self.apply_btn.config(state="normal" if (changed and not self.shell.busy) else "disabled")

    def form_state(self, enabled):
        st = "normal" if enabled else "disabled"
        self.id_entry.config(state=st)
        self.type_box.config(state="readonly" if enabled else "disabled")
        if not enabled:
            self.apply_btn.config(state="disabled")
        else:
            self._check()

    def commit(self):
        cur = self._current()
        if cur is None or self.shell.busy or te.contact_id_problem(self.id_var.get()):
            return
        slot, did, ty = cur[0], int(self.id_var.get()), self._typed()
        if did == cur[2] and ty == cur[3]:
            return
        if self.run_edit(lambda img: te.contact_set(img, slot, did if did != cur[2] else None, ty if ty != cur[3] else None, self.dp), select=slot):
            self.load_form()

    def ask_new(self, img):
        dlg = cvg.ContactDialog(self, "Новий контакт", "", "", 0)
        if not dlg.result:
            return None
        r = dlg.result
        return lambda im: te.contact_add(im, r["name"], r["id"], r["type"], self.dp)
