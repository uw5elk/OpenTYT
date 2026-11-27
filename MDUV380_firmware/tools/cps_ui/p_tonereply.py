# -*- coding: utf-8 -*-
"""Розділ «Дані → Тон-відгук» (R100, R102, R110): налаштування custom-data блоку 19 (tools/tone_reply_cfg.py) -- частина ДОКУМЕНТА, як «Роумінг» (R75):
поля читаються з документа, «Застосувати до документа» вносить правку, у рацію все йде однією дією «Записати в рацію» над розділами (страхова
копія області, sector-safe запис, звірка читанням -- doc_actions). Блок 19 -- налаштування (custom_region: kind = setting), тож він і в бекапі/знімку,
і у файлі «Усі налаштування», і в типовому виборі відновлення.

Межі й типові значення -- з application/include/functions/tone_reply.h (у .exe -- дзеркало, звірене тестом). Старий формат R99 (v1, ×100 мс)
показується мігрованим (секунди вгору, вимкнено, поріг типовий), формат R100 (v2) -- з типовим порогом 1,0 с, формат R102 (v3) -- поріг у секундах ×10; записується завжди v4 (R110: поле «Поріг сигналу» з кроком 0,1 с,
кома або крапка, округлення до 0,1).
Попередження (не блокують): увімкнено; увімкнено і поріг 0; увімкнено -- захисту від зациклення двох рацій НЕМАЄ; увімкнено і тривалість > 10 с.
Діє лише в прошивці зі збіркою «тон-відгук» (ENABLE_TONE_REPLY, build-ukrainian); в інших збірках блок ігнорується."""
import tkinter as tk
from tkinter import ttk, messagebox

import gui_theme as gt
import tone_reply_cfg as trc

from . import document as D
from .layout import equal_buttons
from .panel import Panel


class ToneReplyPanel(Panel):
    key = "tonereply"
    title = "Тон-відгук"
    doc_panel = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self._state = None          # стан блока в документі (dict tone_reply_cfg.parse_payload) або None -- документа/області нема
        self._build_ui()

    def _row(self, parent, label, make):
        f = ttk.Frame(parent)
        f.pack(fill="x", padx=8, pady=2)
        ttk.Label(f, text=label, width=34).pack(side="left")
        w = make(f)
        w.pack(side="left")
        return w

    def _build_ui(self):
        self.header("Тон-відгук", purpose="перевірка покриття й антени: рація у FM після почутого сигналу сама відповідає тоном заданої частоти й тривалості.")
        ttk.Label(self, text=("Лише FM і лише в прошивці зі збіркою «тон-відгук». Відгук -- на КОЖЕН сигнал, що тривав щонайменше порогу (%s..%s с, крок 0,1; 0 -- будь-яке відкриття шумодава), коли шумодав "
                              "закрився і минула затримка. Позивного у відповіді нема. Паузи після відгуку й захисту від зациклення немає: дві рації з "
                              "увімкненою функцією відповідатимуть одна одній без кінця -- вмикайте лише на одній. На рації: головне меню → «Тон-відгук»."
                              % (trc.fmt_thresh(trc.THRESH_MIN), trc.fmt_thresh(trc.THRESH_MAX))),
                  wraplength=620, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 6))
        box = ttk.LabelFrame(self, text="Налаштування тон-відгуку -- частина документа")
        box.pack(fill="x", padx=12, pady=4)
        self.v_enabled = tk.BooleanVar(value=False)
        self.v_freq = tk.StringVar(value=str(trc.FREQ_DEF))
        self.v_dur = tk.StringVar(value=str(trc.DUR_DEF))
        self.v_delay = tk.StringVar(value=str(trc.DELAY_DEF))
        self.v_thresh = tk.StringVar(value=trc.fmt_thresh(trc.THRESH_DEF, "."))
        self.cb_enabled = ttk.Checkbutton(box, text="Тон-відгук увімкнено", variable=self.v_enabled, command=self.refresh_warnings)
        self.cb_enabled.pack(anchor="w", padx=8, pady=(4, 2))
        self.sp_freq = self._row(box, "Частота тону, Гц (%d..%d, крок %d)" % (trc.FREQ_MIN, trc.FREQ_MAX, trc.FREQ_STEP),
                                 lambda f: ttk.Spinbox(f, from_=trc.FREQ_MIN, to=trc.FREQ_MAX, increment=trc.FREQ_STEP, textvariable=self.v_freq, width=7))
        self.sp_dur = self._row(box, "Тривалість тону, с (%d..%d)" % (trc.DUR_MIN, trc.DUR_MAX),
                                lambda f: ttk.Spinbox(f, from_=trc.DUR_MIN, to=trc.DUR_MAX, increment=trc.STEP_S, textvariable=self.v_dur, width=7,
                                                      command=self.refresh_warnings))
        self.sp_delay = self._row(box, "Затримка перед тоном, с (%d..%d)" % (trc.DELAY_MIN, trc.DELAY_MAX),
                                  lambda f: ttk.Spinbox(f, from_=trc.DELAY_MIN, to=trc.DELAY_MAX, increment=trc.STEP_S, textvariable=self.v_delay, width=7))
        self.sp_thresh = self._row(box, "Поріг сигналу, с (%s..%s, крок 0,1)" % (trc.fmt_thresh(trc.THRESH_MIN), trc.fmt_thresh(trc.THRESH_MAX)),
                                   lambda f: ttk.Spinbox(f, from_=trc.THRESH_MIN / 10.0, to=trc.THRESH_MAX / 10.0, increment=trc.THRESH_STEP / 10.0, format="%.1f",
                                                         textvariable=self.v_thresh, width=7, command=self.refresh_warnings))
        self.v_dur.trace_add("write", lambda *_: self.refresh_warnings())
        self.v_thresh.trace_add("write", lambda *_: self.refresh_warnings())
        btn = ttk.Frame(box)
        btn.pack(fill="x", padx=8, pady=6)
        self.apply_btn = ttk.Button(btn, text="Застосувати до документа", command=self._on_apply)
        self.reload_btn = ttk.Button(btn, text="Повернути значення з документа", command=self.on_document_changed)
        equal_buttons(self.apply_btn, self.reload_btn)
        self.apply_btn.pack(side="left")
        self.reload_btn.pack(side="left", padx=8)
        self.state_label = ttk.Label(box, text="", foreground=gt.P["muted"], wraplength=600, justify="left")
        self.state_label.pack(anchor="w", padx=8, pady=(0, 6))
        self.warn_label = ttk.Label(self, text="", foreground=gt.P["warn"], wraplength=620, justify="left")
        self.warn_label.pack(anchor="w", padx=12, pady=(2, 8))
        self.on_document_changed()

    # ------------------------------------------------------------------ документ

    def _region_ok(self):
        d = self.doc
        return d is not None and d.region is not None

    def on_document_changed(self):
        """Форма = блок 19 з документа (або типові значення, якщо блока нема)."""
        d = self.doc
        ok = self._region_ok()
        if ok:
            st, raw = trc.read_state(None, store=d.region)
            self._state = st
            self.v_enabled.set(st["enabled"])
            self.v_freq.set(str(st["freq"]))
            self.v_dur.set(str(st["dur"]))
            self.v_delay.set(str(st["delay"]))
            self.v_thresh.set(trc.fmt_thresh(st["thresh_ds"], "."))
            if raw is None:
                text, fg = "У документі блока тон-відгуку немає -- %s." % trc.describe(st).split(" -- ", 1)[1], gt.P["muted"]
            elif st["version"] == trc.VERSION_V1:
                text, fg = ("У документі старий формат R99 (×100 мс): показано в секундах (округлено вгору), «увімкнено» -- вимкнено. "
                            "Поріг сигналу -- типовий (%s с). «Застосувати до документа» запише новий формат (v4)." % trc.fmt_thresh(trc.THRESH_DEF)), gt.P["warn"]
            elif st["version"] == trc.VERSION_V2:
                text, fg = ("У документі формат R100 (без порогу сигналу): поріг показано типовим (%s с), решта -- як є. «Застосувати до документа» запише новий "
                            "формат (v4)." % trc.fmt_thresh(trc.THRESH_DEF)), gt.P["warn"]
            elif st["version"] == trc.VERSION_V3:
                text, fg = ("У документі формат R102 (поріг у цілих секундах): поріг показано як %s с, решта -- як є. «Застосувати до документа» запише новий "
                            "формат (v4, крок порогу 0,1 с)." % trc.fmt_thresh(st["thresh_ds"])), gt.P["warn"]
            elif st["version"] == 0:
                text, fg = "Блок тон-відгуку недійсний (прошивка читає його як типові значення, вимкнено).", gt.P["warn"]
            else:
                text, fg = "У документі: " + trc.describe(st) + ".", gt.P["muted"]
            self.state_label.config(text=text, foreground=fg)
        else:
            self._state = None
            self.state_label.config(text=("У документа нема налаштувань рації (файл створено старою версією) -- відкрий кодплаг з рації, щоб їх змінити."
                                          if d is not None else "Відкрий кодплаг з рації або з файла."), foreground=gt.P["muted"])
        for b in (self.apply_btn, self.reload_btn):
            b.config(state="normal" if ok and not self.shell.busy else "disabled")
        self.refresh_warnings()

    def after_refresh(self):
        ok = self._region_ok() and not self.shell.busy
        for b in (self.apply_btn, self.reload_btn):
            b.config(state="normal" if ok else "disabled")

    # ------------------------------------------------------------------ попередження

    def warnings(self):
        try:
            dur = int(str(self.v_dur.get()).strip())
        except ValueError:
            dur = 0
        try:
            th = trc.parse_thresh_s(self.v_thresh.get())
        except trc.ToneCfgError:
            th = trc.THRESH_DEF
        return trc.warnings(bool(self.v_enabled.get()), dur, th)

    def refresh_warnings(self):
        w = self.warnings()
        self.warn_label.config(text=("Увага:\n- " + "\n- ".join(w)) if w else "")

    # ------------------------------------------------------------------ застосування

    def _collect(self):
        """Поля форми -> (enabled, freq, dur, delay, thresh_ds). ToneCfgError -- погане значення. Поріг -- секунди з комою або крапкою, округлення до 0,1."""
        vals = []
        for name, var in (("частота", self.v_freq), ("тривалість", self.v_dur), ("затримка", self.v_delay)):
            try:
                vals.append(int(str(var.get()).strip()))
            except ValueError:
                raise trc.ToneCfgError("%s: потрібне ціле число" % name)
        vals.append(trc.parse_thresh_s(self.v_thresh.get()))
        trc.check_values(*vals)
        return (bool(self.v_enabled.get()),) + tuple(vals)

    def _on_apply(self):
        d = self.doc
        if not self._region_ok() or self.shell.busy:
            return
        try:
            en, f, du, dl, th = self._collect()
            scratch = d.scratch_region()
            trc.write_state(None, en, f, du, dl, th, store=scratch)
            changed = d.apply_region(scratch, {trc.TYPE_TONE_REPLY_CFG: "Тон-відгук"})
        except (trc.ToneCfgError, RuntimeError, D.DocumentError) as e:
            messagebox.showerror("Тон-відгук", str(e), parent=self.shell)
            return
        self.on_document_changed()
        self.shell.set_status("Тон-відгук змінено в документі." if changed else "Змін немає.", "ok" if changed else "info")
