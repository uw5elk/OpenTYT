# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Загальні налаштування» (R-next, Y2): лише те, що є в кодплазі І справді читається прошивкою -- пароль на старті (прапорець +
PIN) і тривалості DTMF. Решта 40-байтового блоку «загальних налаштувань» прошивка OpenGD77 не читає, тому тут її нема (див. general_edit.py).
Зміни лягають у документ (зірочка в заголовку вікна); у рацію -- лише дією «Записати кодплаг у рацію»."""
import tkinter as tk
from tkinter import ttk, messagebox

import codeplug_edit as ced
import general_edit as ge
import gui_dialogs as gd
import gui_theme as gt

from .panel import HINT_NO_DOC, Panel


class GeneralPanel(Panel):
    key = "general"
    title = "Загальні налаштування"
    doc_panel = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.header("Загальні налаштування", "Тільки те, що рація справді читає з кодплага: пароль на старті й тривалості DTMF. Зміни потрапляють "
                                              "у документ; рація змінюється лише за дією «Записати кодплаг у рацію».")
        self.hint = ttk.Label(self, text=HINT_NO_DOC, foreground=gt.P["muted"])
        self.enable = tk.BooleanVar()
        self.pin = tk.StringVar()
        self.dt = {f[0]: tk.StringVar() for f in ge.DTMF_FIELDS}
        self.infos = {}
        self.entries = {}
        self._odd = False

        self.box_pwd = ttk.LabelFrame(self, text="Пароль при вмиканні")
        self.box_pwd.pack(fill="x", padx=12, pady=6)
        self.chk = ttk.Checkbutton(self.box_pwd, text="Питати PIN-код при кожному вмиканні рації", variable=self.enable)
        self.chk.pack(anchor="w", padx=8, pady=(6, 2))
        f = ttk.Frame(self.box_pwd)
        f.pack(fill="x", padx=8, pady=3)
        ttk.Label(f, text="PIN-код (цифри)", width=34).pack(side="left")
        e = ttk.Entry(f, textvariable=self.pin, width=10)
        e.pack(side="left")
        self.entries["pwd_pin"] = e
        self.infos["pwd_pin"] = ttk.Label(f, text="", foreground=gt.P["muted"], wraplength=380, justify="left")
        self.infos["pwd_pin"].pack(side="left", padx=10)
        ttk.Label(self.box_pwd, text=("Увага: рація питатиме PIN при кожному вмиканні (EEPROM 0x7519, 0x751C). Запам'ятайте його: на екрані "
                                      "вмикання рація не пропустить далі без цього PIN."),
                  wraplength=560, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 6))
        self.pin.trace_add("write", lambda *_: self._validate())
        self.enable.trace_add("write", lambda *_: self._validate())

        self.box_dtmf = ttk.LabelFrame(self, text="Сигналізація DTMF (тривалості)")
        self.box_dtmf.pack(fill="x", padx=12, pady=6)
        for key, addr, lo, hi, label, mult, unit in ge.DTMF_FIELDS:
            f = ttk.Frame(self.box_dtmf)
            f.pack(fill="x", padx=8, pady=3)
            ttk.Label(f, text=label, width=34).pack(side="left")
            e = ttk.Entry(f, textvariable=self.dt[key], width=6)
            e.pack(side="left")
            self.entries[key] = e
            self.infos[key] = ttk.Label(f, text="", foreground=gt.P["muted"], wraplength=460, justify="left")
            self.infos[key].pack(side="left", padx=10)
            self.dt[key].trace_add("write", lambda *_: self._validate())
        ttk.Label(self.box_dtmf, text=("Рація читає ці значення один раз при вмиканні -- після запису перезавантажте її (запис з «Записати кодплаг у рацію» "
                                       "перезавантажує сам). Швидкість 0 заборонена: прошивка ділила б на нуль."),
                  wraplength=560, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 6))

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=6)
        self.apply_button = ttk.Button(bar, text="Застосувати до документа", command=self._on_apply)
        self.apply_button.pack(side="left")
        self.reload_button = ttk.Button(bar, text="Повернути значення з документа", command=self.on_document_changed)
        self.reload_button.pack(side="left", padx=8)
        self.table_button = ttk.Button(bar, text="Звідки ці поля...", command=self._show_table)
        self.table_button.pack(side="left")
        self.on_document_changed()

    # --- вміст ---

    def on_document_changed(self):
        d = self.doc
        if d is None:
            self.hint.pack(anchor="w", padx=12, pady=(0, 4), after=self._note_box)
            self.enable.set(False)
            self.pin.set("")
            for v in self.dt.values():
                v.set("")
            self._odd = False
        else:
            self.hint.pack_forget()
            v = ge.general_values(d.image)
            self.enable.set(v["pwd_enable"])
            self._odd = v["pwd_pin_odd"]
            self.pin.set("" if self._odd else v["pwd_pin"])
            for key in self.dt:
                self.dt[key].set(str(v[key]))
        self._validate()

    def _current(self):
        """Значення форми для перевірки/застосування: PIN дається, лише коли користувач його чіпав або вмикає пароль."""
        out = {"pwd_enable": bool(self.enable.get()), "pwd_pin": self.pin.get().strip()}
        for key in self.dt:
            t = self.dt[key].get().strip()
            out[key] = int(t) if t.isdigit() and t.isascii() else None
        return out

    def _validate(self):
        d = self.doc
        if d is None:
            self._can_apply = False
            for info in self.infos.values():
                info.config(text="")
            for e in self.entries.values():
                e.config(state="disabled")
            self.chk.config(state="disabled")
            for b in (self.apply_button, self.reload_button):
                b.config(state="disabled")
            return
        ok_all = True
        cur = ge.general_values(d.image)
        form = self._current()
        bad = ge.check_values(form, keys=[k for k in self.dt if form[k] != cur[k]])
        bad_stored = ge.check_values({k: cur[k] for k in cur if k.startswith("dtmf_")})
        pin_text = self.pin.get().strip()
        pin_touched = pin_text != ("" if self._odd else cur["pwd_pin"])
        if not form["pwd_enable"] and not pin_touched:
            bad.pop("pwd_pin", None)
        if self._odd and not pin_touched and form["pwd_enable"] and cur["pwd_enable"]:
            bad.pop("pwd_pin", None)
        changed = False
        for key in ["pwd_pin"] + list(self.dt):
            if key == "pwd_pin":
                if key in bad:
                    self.infos[key].config(text=bad[key], foreground=gt.P["err"])
                    ok_all = False
                else:
                    note = ("PIN у кодплазі нестандартний -- задайте новий, щоб його замінити." if self._odd and not pin_touched
                            else ("до %d цифр" % ge.PIN_DIGITS_MAX))
                    self.infos[key].config(text=note, foreground=gt.P["muted"])
                continue
            fld = [f for f in ge.DTMF_FIELDS if f[0] == key][0]
            if key in bad:
                self.infos[key].config(text=bad[key], foreground=gt.P["err"])
                ok_all = False
            elif key in bad_stored and form[key] == cur[key]:
                self.infos[key].config(text="у кодплазі %d -- поза межами прошивки; не змінено, задайте своє" % cur[key], foreground=gt.P["warn"])
            else:
                x, mult, unit = form[key], fld[5], fld[6]
                if mult:
                    txt = "= %d %s" % (x * mult, unit)
                else:
                    txt = "тон і пауза по %d мс (1000 / (2 x %d))" % (1000 // (x * 2), x)       # uiUtilities.c: duration = 1000 / (rate * 2)
                self.infos[key].config(text=txt, foreground=gt.P["muted"])
                changed |= x != cur[key]
        changed |= form["pwd_enable"] != cur["pwd_enable"] or (pin_touched and bool(pin_text))
        self._can_apply = bool(ok_all and changed)
        self.apply_button.config(state="normal" if (self._can_apply and not self.shell.busy) else "disabled")
        for e in self.entries.values():
            e.config(state="normal")
        self.chk.config(state="normal")
        self.reload_button.config(state="normal")

    def after_refresh(self):
        self._validate()

    def _on_apply(self):
        d = self.doc
        if d is None or self.shell.busy or not self._can_apply:
            return
        form = self._current()
        cur = ge.general_values(d.image)
        pin_text = form["pwd_pin"]
        values = {"pwd_enable": form["pwd_enable"]}
        if pin_text and (pin_text != cur["pwd_pin"] or cur["pwd_pin_odd"]):
            values["pwd_pin"] = pin_text
        for key in self.dt:
            values[key] = form[key]
        if form["pwd_enable"] and not cur["pwd_enable"]:
            if not gd.confirm_dialog(self.shell, "Увімкнути пароль?", "Після запису в рацію вона питатиме PIN при кожному вмиканні. "
                                     "Запам'ятайте PIN. Увімкнути?", yes="Увімкнути", no="Скасувати"):
                return
        try:
            res = ge.apply_general(d.image, **values)
            changed = d.apply(res)
        except (ced.CodeplugEditError, ValueError) as e:
            messagebox.showerror("Загальні налаштування", str(e), parent=self.shell)
            return
        self.shell.set_status("Загальні налаштування змінено в документі." if changed else "Змін немає.", "ok" if changed else "info")

    def _show_table(self):
        rows = ge.field_table()
        text = "Поле  ->  адреса  ->  діапазон  (де прошивка це читає)\n\n" + "\n\n".join(
            "%s\n  адреса: %s\n  діапазон: %s\n  прошивка: %s" % r for r in rows)
        text += ("\n\nЧого тут НЕМАЄ і чому: решта 40 байтів «загальних налаштувань» (0x00E0..0x0107) прошивка OpenGD77 не читає; швидкі клавіші "
                 "(0x7524) вона захищає від запису з CPS; блок пристрою (0x80) і LUCZ (0x6000) -- службові.")
        gd.text_dialog(self.shell, "Звідки ці поля", text)
