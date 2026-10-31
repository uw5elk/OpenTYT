# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → VFO A / VFO B» (R-next, Y5): перегляд і правка VFO документа. Поля -- ті ж колонки, що й у каналу (без назви, номера й прапорців зон).
Показуються значення, ЗБЕРЕЖЕНІ в кодплазі: рація читає їх з кодплага при вмиканні, а записує назад лише при вимкненні, тож живий VFO рації може відрізнятись.
Запис у рацію -- звичайна дія «Записати кодплаг у рацію» (cps_restore), після неї рація перезавантажується без збереження пам'яті й бере VFO з кодплага (див. vfo_edit.py)."""
import tkinter as tk
from tkinter import ttk

import cps_csv as cc
import codeplug_edit as ced
import gui_theme as gt
import table_edit as te
import vfo_edit as ve

from .p_channels import CTCSS, NONE_LABEL, TYPE_LABELS
from .panel import HINT_NO_DOC, Panel

LABELS = {"Channel Type": "Тип", "Rx Frequency": "RX, МГц", "Tx Frequency": "TX, МГц", "Bandwidth (kHz)": "Смуга, кГц (аналог)",
          "RX Tone": "Тон RX (None / CTCSS / DCS)", "TX Tone": "Тон TX (None / CTCSS / DCS)", "Squelch": "Шумодав",
          "Colour Code": "Колір-код (0..15)", "Timeslot": "Таймслот", "Contact": "Контакт", "TG List": "Список прийому", "Power": "Потужність"}


class VfoPanel(Panel):
    key = "vfo"
    title = "VFO A / VFO B"
    doc_panel = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.dp = cc.system_decimal_point()
        self.header("VFO A / VFO B", "Частоти й режим VFO, збережені в кодплазі. Рація читає їх при вмиканні, а живий VFO записує в кодплаг лише при "
                                      "вимкненні -- тому тут те, що збережено, а не те, що рація має в пам'яті зараз. Зміни потрапляють у документ; "
                                      "рація змінюється лише за дією «Записати кодплаг у рацію».")
        self.hint = ttk.Label(self, text=HINT_NO_DOC, foreground=gt.P["muted"])
        self.which = tk.IntVar(value=0)
        self.vars = {c: tk.StringVar() for c in ve.VFO_COLUMNS}
        self.widgets = {}
        self._ref_numbers = {}
        self._loaded = {}
        self._loading = False
        self._digital = False
        self.body = ttk.Frame(self)
        self.body.pack(fill="x", padx=12, pady=4)
        sel = ttk.Frame(self.body)
        sel.pack(fill="x", pady=(0, 4))
        for n, name in enumerate(ve.VFO_NAMES):
            ttk.Radiobutton(sel, text=name, value=n, variable=self.which, command=self._on_switch).pack(side="left", padx=(0, 12))
        self.state_label = ttk.Label(self.body, text="", wraplength=560, justify="left")
        self.state_label.pack(anchor="w", pady=(0, 4))
        self.init_button = ttk.Button(self.body, text="Заповнити типовими значеннями (аналоговий, 145,5 МГц)", command=self._on_init)
        box = ttk.LabelFrame(self.body, text="Поля VFO")
        box.pack(fill="x", pady=4)
        self.box = box
        sep = self.dp
        for col in ve.VFO_COLUMNS:
            row = ttk.Frame(box)
            row.pack(fill="x", padx=8, pady=2)
            ttk.Label(row, text=LABELS[col], width=30).pack(side="left")
            var = self.vars[col]
            if col == "Channel Type":
                w = ttk.Combobox(row, textvariable=var, values=[TYPE_LABELS["Analogue"], TYPE_LABELS["Digital"]], state="readonly", width=24)
                w.bind("<<ComboboxSelected>>", lambda _e: self._on_type())
            elif col == "Bandwidth (kHz)":
                w = ttk.Combobox(row, textvariable=var, values=["12%s5" % sep, "25"], state="readonly", width=24)
            elif col in ("RX Tone", "TX Tone"):
                w = ttk.Combobox(row, textvariable=var, values=["None"] + [t.replace(".", sep) for t in CTCSS], width=24)
            elif col == "Squelch":
                w = ttk.Combobox(row, textvariable=var, values=["Master"] + ["%d%%" % (5 * (k - 1)) for k in range(1, 22)], width=24)
            elif col == "Colour Code":
                w = ttk.Spinbox(row, textvariable=var, from_=0, to=15, width=8)
            elif col == "Timeslot":
                w = ttk.Combobox(row, textvariable=var, values=["1", "2"], state="readonly", width=24)
            elif col in ve.REF_COLUMNS:
                w = ttk.Combobox(row, textvariable=var, values=[NONE_LABEL], state="readonly", width=36)
            elif col == "Power":
                w = ttk.Combobox(row, textvariable=var, values=["Master"] + cc.POWER_NAMES, state="readonly", width=24)
            else:
                w = ttk.Entry(row, textvariable=var, width=26)
            w.pack(side="left")
            self.widgets[col] = w
            var.trace_add("write", lambda *_: self._refresh_buttons())
        self.info = ttk.Label(self.body, text="", wraplength=560, justify="left")
        self.info.pack(anchor="w", pady=2)
        bar = ttk.Frame(self.body)
        bar.pack(fill="x", pady=6)
        self.bar = bar
        self.apply_button = ttk.Button(bar, text="Застосувати до документа", command=self._on_apply)
        self.apply_button.pack(side="left")
        self.reload_button = ttk.Button(bar, text="Повернути значення з документа", command=self.on_document_changed)
        self.reload_button.pack(side="left", padx=8)
        ttk.Label(self, text=("Частоти -- з комою або крапкою, як у CSV. Допустимі діапазони рації (trx.c): %s. Поза ними прошивка при вмиканні мовчки замінила б "
                              "весь VFO значеннями за замовчуванням, тому такі частоти тут відхиляються." % ve.band_text()),
                  wraplength=560, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 8))
        self.on_document_changed()

    # --- вміст ---

    def _on_switch(self):
        self.on_document_changed()

    def on_document_changed(self):
        d = self.doc
        if d is None:
            self.hint.pack(anchor="w", padx=12, pady=(0, 4), after=self._note_box)
            self.body.pack_forget()
            return
        self.hint.pack_forget()
        if not self.body.winfo_manager():
            self.body.pack(fill="x", padx=12, pady=4)
        n = self.which.get()
        img = d.image
        vals = ve.vfo_values(img, n, self.dp)
        refs = ve.vfo_refs(img, n)
        self._digital = vals["Channel Type"].strip().casefold().startswith("dig")
        self._loading = True
        try:
            for col in ve.VFO_COLUMNS:
                if col == "Channel Type":
                    self.vars[col].set(TYPE_LABELS["Digital" if self._digital else "Analogue"])
                elif col in ve.REF_COLUMNS:
                    opts = te.ref_options(img, ve.REF_COLUMNS[col])
                    labels = {k: lab for k, lab in opts}
                    self._ref_numbers[col] = {lab: k for k, lab in opts}
                    self._ref_numbers[col][NONE_LABEL] = 0
                    k = refs[col]
                    label = NONE_LABEL if k == 0 else labels.get(k, "#%d (відсутній запис)" % k)
                    if k and k not in labels:
                        self._ref_numbers[col][label] = k
                    self.widgets[col].config(values=[NONE_LABEL] + [lab for _k, lab in opts] + ([label] if k and k not in labels else []))
                    self.vars[col].set(label if self._digital else "")
                else:
                    self.vars[col].set(vals[col])
                self._loaded[col] = self._value(col)
        finally:
            self._loading = False
        if vals["freq_ok"]:
            self.state_label.config(text="%s: значення збережені в кодплазі." % ve.VFO_NAMES[n], foreground=gt.P["muted"])
            self.init_button.pack_forget()
            if not self.box.winfo_manager():
                self.box.pack(fill="x", pady=4, after=self.state_label)
                self.info.pack(anchor="w", pady=2, after=self.box)
                self.bar.pack(fill="x", pady=6, after=self.info)
        else:
            for w in (self.box, self.info, self.bar):          # сміття в полях не показуємо: лишається пояснення й кнопка заповнення
                w.pack_forget()
            self.state_label.config(text=("%s у кодплазі порожній або з частотою поза діапазонами рації (RX %s, TX %s). Рація при вмиканні замінить його значеннями "
                                          "за замовчуванням. Можна заповнити типовими значеннями тут." % (ve.VFO_NAMES[n], vals["Rx Frequency"], vals["Tx Frequency"])),
                                    foreground=gt.P["warn"])
            self.init_button.pack(anchor="w", pady=(0, 4), after=self.state_label)
        self.info.config(text="")
        self._refresh_buttons()

    def _value(self, col):
        v = self.vars[col].get()
        return str(v).strip()

    def _changes(self):
        """({колонка: текст}, {посилання: номер}) для полів, що відрізняються від завантажених і актуальні для типу."""
        ch, refs = {}, {}
        for col in ve.VFO_COLUMNS:
            if col == "Channel Type" or self._value(col) == self._loaded.get(col):
                continue
            if not te.applicable(col, self._digital):
                continue
            if col in ve.REF_COLUMNS:
                refs[col] = self._ref_numbers.get(col, {}).get(self._value(col), 0)
            else:
                ch[col] = self._value(col)
        return ch, refs

    def _refresh_buttons(self):
        d = self.doc
        for col, w in self.widgets.items():
            ok = d is not None and (col == "Channel Type" or te.applicable(col, self._digital))
            ftype_ro = col in ("Channel Type", "Bandwidth (kHz)", "Timeslot", "Power") or col in ve.REF_COLUMNS
            w.config(state=("readonly" if ftype_ro else "normal") if ok else "disabled")
        if getattr(self, "_loading", False):
            return
        ch, refs = self._changes()
        self.apply_button.config(state="normal" if (d is not None and (ch or refs) and not self.shell.busy) else "disabled")
        self.reload_button.config(state="normal" if d is not None else "disabled")

    def after_refresh(self):
        self._refresh_buttons()

    # --- дії ---

    def _run(self, fn):
        d = self.doc
        if d is None or self.shell.busy:
            return False
        try:
            res = fn(d.image)
        except ced.CodeplugEditError as e:
            self.info.config(text="\n".join(e.problems), foreground=gt.P["err"])
            return False
        changed = d.apply(res)
        self.shell.set_status("VFO змінено в документі." if changed else "Змін немає.", "ok" if changed else "info")
        return True

    def _on_type(self):
        if self._loading:
            return
        digital = self.vars["Channel Type"].get() == TYPE_LABELS["Digital"]
        if digital == self._digital:
            return
        n = self.which.get()
        if not self._run(lambda img: ve.vfo_edit(img, n, {"Channel Type": "Digital" if digital else "Analogue"}, self.dp)):
            self.on_document_changed()

    def _on_apply(self):
        ch, refs = self._changes()
        if not (ch or refs):
            return
        n = self.which.get()
        if self._run(lambda img: ve.vfo_edit(img, n, ch, self.dp, refs=refs)):
            self.on_document_changed()

    def _on_init(self):
        n = self.which.get()
        if self._run(lambda img: ve.vfo_init(img, n, self.dp)):
            self.on_document_changed()
