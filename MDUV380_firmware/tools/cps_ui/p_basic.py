# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Основна інформація»: ім'я рації / позивний APRS (EEPROM 0x00E0), мій DMR ID (0x00E8), Talker Alias у двох частинах (0x7540, 0x7550) і тип екрана при вмиканні (0x7518) ДОКУМЕНТА.
R51: підписи приведено до того, що ці поля роблять у прошивці (за кодом: codeplugGetRadioName -> aprs.c; codeplugGetUserDMRID -> settings.c; рядки 0x7540/0x7550 -> HRC6000SetTalkerAlias; 0x7518 -> uiSplashScreen.c).
Правки лягають у документ (зірочка в заголовку вікна); у рацію -- лише дією «Записати в рацію». Формати полів не змінено (codeplug_edit.py)."""
import tkinter as tk
from tkinter import ttk, messagebox

import aprs_beacon_cfg as abc_
import codeplug_edit as ced
import contact_edit as ce
import gui_dialogs as gd
import gui_theme as gt
import table_edit as te

from .panel import HINT_NO_DOC, Panel


INTRO_LABELS = ["Гасло", "Картинка"]
INTRO_NOTE = ("«Картинка» -- прошивка показує картинку з кодплага (її цим розділом не змінюємо), а якщо картинки нема -- гасло. "
              "«Гасло» -- в українській збірці при вмиканні на екрані лише гасло (за кодом uiSplashScreen.c); рядки Talker Alias вище на екран НЕ малюються.")
TA_NOTE = ("Рядки 1+2 склеюються, в ефір іде лише перші 27 символів; на екран в українській збірці не виходять; передаються лише на каналах "
           "з увімкненим TX Talker Alias.")


class BasicInfoPanel(Panel):
    key = "basic"
    title = "Основна інформація"
    doc_panel = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.vars = {k: tk.StringVar() for k in ("callsign", "dmr_id", "line1", "line2")}
        self.intro_var = tk.StringVar()
        self.infos = {}
        self.header("Основна інформація", "Ім'я рації (воно ж позивний APRS), мій DMR ID, Talker Alias і тип екрана при вмиканні з кодплага. Зміни потрапляють "
                                          "у документ; рація змінюється лише за дією «Записати в рацію» над розділами.")
        self.hint = ttk.Label(self, text=HINT_NO_DOC, foreground=gt.P["muted"])
        # R51: назва групи за змістом полів (ім'я/ID/Talker Alias/екран вмикання), а не загальна назва з рядка «було» (див. звіт R51)
        self.box = ttk.LabelFrame(self, text="Ім'я, ID, Talker Alias і екран вмикання")
        self.box.pack(fill="x", padx=12, pady=6)
        self.entries = {}
        # Підпис поля -- рядком над полем (довгі підписи з адресою EEPROM не вміщувались би в один рядок з полем на крупному шрифті), підказка -- праворуч від поля
        # і переноситься за шириною групи.
        for key, label, width, hint in (
                ("callsign", "Ім'я рації / позивний APRS (EEPROM 0x00E0)", 10, "1..6 символів A-Z, 0-9, без SSID -- як у розділі «APRS: бікон»"),
                ("dmr_id", "Мій DMR ID (EEPROM 0x00E8)", 12, "ціле число 1..%d" % ced.DMR_ID_MAX),
                ("line1", "Talker Alias, частина 1 (0x7540)", 24, ""),
                ("line2", "Talker Alias, частина 2 (0x7550)", 24, "")):
            f = ttk.Frame(self.box)
            f.pack(fill="x", padx=8, pady=3)
            ttk.Label(f, text=label).pack(anchor="w")
            row = ttk.Frame(f)
            row.pack(fill="x")
            e = ttk.Entry(row, textvariable=self.vars[key], width=width)
            e.pack(side="left")
            info = gd.autowrap(ttk.Label(row, text=hint, foreground=gt.P["muted"], wraplength=420, justify="left"), self.box, margin=40 + 8 * width, floor=160)
            info.pack(side="left", padx=10)
            self.entries[key] = e
            self.infos[key] = info
            self.vars[key].trace_add("write", lambda *_: self._validate())
        self.ta_label = gd.autowrap(ttk.Label(self.box, text=TA_NOTE, foreground=gt.P["muted"], wraplength=560, justify="left"), self.box, margin=24)
        self.ta_label.pack(anchor="w", padx=8, pady=(0, 4))
        f = ttk.Frame(self.box)
        f.pack(fill="x", padx=8, pady=3)
        ttk.Label(f, text="Екран при вмиканні (EEPROM 0x7518)").pack(anchor="w")
        self.intro_box = ttk.Combobox(f, textvariable=self.intro_var, values=INTRO_LABELS, state="readonly", width=22)
        self.intro_box.pack(anchor="w")
        self.intro_box.bind("<<ComboboxSelected>>", lambda _e: self._validate())
        self.intro_label = gd.autowrap(ttk.Label(self.box, text=INTRO_NOTE, foreground=gt.P["muted"], wraplength=560, justify="left"), self.box, margin=24)
        self.intro_label.pack(anchor="w", padx=8, pady=(2, 6))
        # R33 Q2: підсумок кодплага (раніше його показував «Перегляд кодплага», чиї таблиці дублювали окремі розділи)
        self.sum_box = ttk.LabelFrame(self, text="Склад кодплага")
        self.sum_box.pack(fill="x", padx=12, pady=6)
        self.sum_status = ttk.Label(self.sum_box, text="", wraplength=600, justify="left")
        self.sum_status.pack(anchor="w", padx=8, pady=(6, 2))
        self.sum_counts = ttk.Label(self.sum_box, text="", wraplength=600, justify="left", foreground=gt.P["muted"])
        self.sum_counts.pack(anchor="w", padx=8, pady=(0, 6))
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=6)
        self.apply_button = ttk.Button(bar, text="Застосувати до документа", command=self._on_apply)
        self.apply_button.pack(side="left")
        self.reload_button = ttk.Button(bar, text="Повернути значення з документа", command=self.on_document_changed)
        self.reload_button.pack(side="left", padx=8)
        ttk.Label(self, text=("Кодування рядків Talker Alias -- як у назв каналів (GBK, а якщо літер немає в GB2312 -- cp1251). ГІПОТЕЗА: чи покаже "
                              "кирилицю екран при вмиканні (у збірках, де рядки на екрані є) і чи правильно піде Talker Alias, залежить від прошивки -- "
                              "перевірте на рації (крок CD5)."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 8))
        self.on_document_changed()

    # --- вміст ---

    def _fill_summary(self):
        d = self.doc
        if d is None:
            self.sum_status.config(text="Кодплаг не відкрито.")
            self.sum_counts.config(text="")
            return
        self.sum_status.config(text=d.status_text())
        self.sum_counts.config(text="У кодплазі: " + ", ".join("%s %d" % (n, c) for n, c in te.codeplug_counts(d.image))
                               + ". Кожен вид правиться у своєму розділі дерева.")

    def on_document_changed(self):
        self._fill_summary()
        d = self.doc
        if d is None:
            self.hint.pack(anchor="w", padx=12, pady=(0, 4), after=self._note_box)
            for k, v in self.vars.items():
                v.set("")
            self.intro_var.set("")
        else:
            self.hint.pack_forget()
            b = ced.basic_values(d.image)
            self.vars["callsign"].set(b["callsign"])
            self.vars["dmr_id"].set(str(b["dmr_id"]))
            self.vars["line1"].set(b["line1"])
            self.vars["line2"].set(b["line2"])
            self.intro_var.set(INTRO_LABELS[0 if b["intro_text"] else 1])
        self._validate()

    def _validate(self):
        """Живі підказки до полів; кнопка «Застосувати» доступна лише коли всі поля правильні й щось відрізняється від документа."""
        d = self.doc
        ok_all = d is not None
        cur = ced.basic_values(d.image) if d is not None else None
        changed = False
        try:
            call = abc_.callsign_check(self.vars["callsign"].get())
            self.infos["callsign"].config(text="", foreground=gt.P["muted"])
            changed |= cur is not None and call != cur["callsign"]
        except abc_.AprsCfgError as e:
            self.infos["callsign"].config(text=str(e), foreground=gt.P["err"])
            ok_all = False
        try:
            did = ce.parse_id(self.vars["dmr_id"].get())
            if did < 1:
                raise ValueError("DMR ID: ціле число 1..%d" % ced.DMR_ID_MAX)
            self.infos["dmr_id"].config(text="", foreground=gt.P["muted"])
            changed |= cur is not None and did != cur["dmr_id"]
        except ValueError as e:
            self.infos["dmr_id"].config(text=str(e), foreground=gt.P["err"])
            ok_all = False
        for key in ("line1", "line2"):
            text = self.vars[key].get()
            chk = ced.check_line(text)
            self.infos[key].config(text="%d з %d байтів. %s" % (chk["nbytes"], ced.BOOT_LINE_LEN, chk["message"]),
                                   foreground=gt.P["ok"] if chk["ok"] else gt.P["err"])
            ok_all &= chk["ok"]
            changed |= cur is not None and text != cur[key]
        if cur is not None:
            changed |= (self.intro_var.get() == INTRO_LABELS[0]) != cur["intro_text"]
        self._can_apply = bool(ok_all and changed)
        self.apply_button.config(state="normal" if (self._can_apply and not self.shell.busy) else "disabled")
        for e in self.entries.values():
            e.config(state="normal" if d is not None else "disabled")
        self.reload_button.config(state="normal" if d is not None else "disabled")
        self.intro_box.config(state="readonly" if d is not None else "disabled")

    def after_refresh(self):
        self._validate()

    def _on_apply(self):
        d = self.doc
        if d is None or self.shell.busy or not self._can_apply:
            return
        try:
            did = ce.parse_id(self.vars["dmr_id"].get())
            changed = d.edit_basic(callsign=self.vars["callsign"].get(), dmr_id=did, line1=self.vars["line1"].get(), line2=self.vars["line2"].get(),
                                  intro_text=(self.intro_var.get() == INTRO_LABELS[0]))
        except (ced.CodeplugEditError, ValueError) as e:
            messagebox.showerror("Основна інформація", str(e), parent=self.shell)
            return
        self.shell.set_status("Основну інформацію змінено в документі." if changed else "Змін немає.", "ok" if changed else "info")
