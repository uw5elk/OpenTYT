# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → DTMF-контакти» (R-next, Y4): додати / змінити код / перейменувати / видалити DTMF-контакт документа. Рядки ті самі, що в DTMF.csv,
і ідуть через ту саму перевірку імпорту (table_edit.py -> cps_csv.import_csv). Ім'я -- до 16 байтів, код -- до 16 знаків «0-9 A-D * #».
ГІПОТЕЗА (cps_csv.DTMF_ALPHABET): байт коду = індекс знака в «0123456789ABCD*#»; прошивка шле байти коду як є, а завершальний 0xFF обриває код.
Перевіряється на рації кроком CD4."""
import tkinter as tk
from tkinter import ttk

import cps_csv as cc
import gui_dialogs as gd
import gui_theme as gt
import table_edit as te

from .editor_base import EditorPanel
from .layout import FlowFrame


class DtmfPanel(EditorPanel):
    key = "dtmf"
    title = "DTMF-контакти"
    kind = "dtmf"
    noun = "DTMF-контакт"
    hint_text = ("DTMF-контакти кодплага (до %d): ім'я і код із знаків 0-9, A-D, *, #. Зміни потрапляють у документ одразу; рація змінюється лише за "
                 "дією «Записати кодплаг у рацію»." % cc.DTMF_MAX)
    columns = (("name", "Ім'я", 190, True), ("code", "Код", 110, False))

    def entities(self, img):
        return [(s, (name, code)) for s, name, code in te.dtmf_contacts(img)]

    def build_form(self, parent):
        self.code_var = tk.StringVar()
        self.form_title = ttk.Label(parent, text="", font=("Segoe UI", 11, "bold"), wraplength=380, justify="left")
        self.form_title.pack(anchor="w", pady=(0, 6))
        box = ttk.LabelFrame(parent, text="Код")
        box.pack(fill="x", padx=(0, 8))
        row = FlowFrame(box)
        row.pack(fill="x", padx=gt.PAD - 4, pady=6)
        self.code_entry = ttk.Entry(row, textvariable=self.code_var, width=24)
        self.code_apply = ttk.Button(row, text="Застосувати код", command=self.commit_code)
        row.add(self.code_entry)
        row.add(self.code_apply)
        self.code_info = ttk.Label(box, text="", wraplength=420, justify="left", foreground=gt.P["muted"])
        self.code_info.pack(anchor="w", padx=8, pady=(0, 6))
        self.code_entry.bind("<Return>", lambda _e: self.commit_code())
        self.code_var.trace_add("write", lambda *_: self._check_code())
        ttk.Label(parent, text=("Знаки коду: %s. Пробіли ігноруються, регістр не важливий. Ім'я змінюється кнопкою «Перейменувати...». "
                                "Щоб прибрати контакт, натисніть «Видалити...»." % cc.DTMF_ALPHABET),
                  wraplength=420, justify="left", foreground=gt.P["muted"]).pack(anchor="w", pady=8)

    def clear_form(self):
        self._loading = True
        try:
            self.code_var.set("")
        finally:
            self._loading = False
        self.form_title.config(text="")
        self.code_info.config(text="")
        self.form_state(False)

    def load_form(self):
        d = self.doc
        cur = dict((s, (n, c)) for s, n, c in te.dtmf_contacts(d.image)) if d is not None else {}
        if d is None or self.sel not in cur:
            self.clear_form()
            if d is not None:
                self.form_title.config(text="Оберіть контакт ліворуч або натисніть «Додати...»")
            return
        name, code = cur[self.sel]
        self.form_title.config(text="№%d «%s»" % (self.sel + 1, name))
        self._loading = True
        try:
            self.code_var.set(code)
        finally:
            self._loading = False
        self._check_code()
        self.after_refresh()

    def _check_code(self):
        d = self.doc
        if d is None or self.sel is None:
            return
        cur = dict((s, c) for s, _n, c in te.dtmf_contacts(d.image)).get(self.sel, "")
        text = self.code_var.get()
        prob = te.dtmf_code_problem(text)
        norm = "".join(text.split()).upper()
        self.code_info.config(text=prob or ("%d з 16 знаків" % len(norm)), foreground=gt.P["err"] if prob else gt.P["muted"])
        ok = prob is None and norm != cur and not self.shell.busy
        self.code_apply.config(state="normal" if ok else "disabled")

    def form_state(self, enabled):
        self.code_entry.config(state="normal" if enabled else "disabled")
        if not enabled:
            self.code_apply.config(state="disabled")
        else:
            self._check_code()

    def commit_code(self):
        d = self.doc
        if d is None or self.sel is None or self.shell.busy or te.dtmf_code_problem(self.code_var.get()):
            return
        slot, text = self.sel, self.code_var.get()
        if self.run_edit(lambda img: te.dtmf_set_code(img, slot, text, self.dp), select=slot):
            self.load_form()

    def ask_new(self, img):
        got = gd.two_field_dialog(self.shell, "Новий DTMF-контакт", "Ім'я (до 16 байтів):", "Код (0-9 A-D * #, до 16 знаків):",
                                  check1=lambda t: te.name_problem(img, "dtmf", t), check2=lambda t: te.dtmf_code_problem(t), ok="Створити")
        if got is None:
            return None
        name, code = got
        return lambda im: te.dtmf_add(im, name, code, self.dp)
