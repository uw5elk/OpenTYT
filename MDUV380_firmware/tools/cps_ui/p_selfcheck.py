# -*- coding: utf-8 -*-
"""Розділ «Рація → Самоперевірка» (R38): майстер, який сам проходить ручні перевірки, що зводяться до «прочитати, записати, перечитати, звірити».

Вікно лише керує: сценарії, ризики, знімок, звіт -- у tools/selfcheck.py (без Tk). Правила:
  * сценарії лише читання (зелені) ввімкнені, сценарії запису (жовті) зняті й ДОСТУПНІ ЛИШЕ після повного знімка у файл;
  * сценарії запису просять окреме підтвердження з переліком змін; кожен повертає рацію як була;
  * по завершенні зберігається звіт `selfcheck_РРРР-ММ-ДД_ГГ-ХХ.md` (його й надсилають) з переліком кроків, що лишаються людині (S5)."""
import os
import tkinter as tk
from tkinter import scrolledtext, ttk

import cps_link as cps
import gui_theme as gt
import selfcheck as sc

from .common import output_dir
from .layout import FlowFrame, equal_buttons
from .panel import Panel

RISK_COLOR = {sc.RISK_READ: "ok", sc.RISK_WRITE: "warn"}


class SelfcheckPanel(Panel):
    key = "selfcheck"
    title = "Самоперевірка"
    radio_only = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.vars = {}             # sid -> BooleanVar
        self.checks = {}           # sid -> Checkbutton
        self.snapshot = None       # результат selfcheck.take_snapshot (ставиться з робочого потоку через shell.post)
        self.last_report = None
        self._build_ui()

    # --- побудова ---------------------------------------------------------------------------------

    def _build_ui(self):
        self.header("Самоперевірка рації",
                    "Майстер сам проходить перевірки, що зводяться до «прочитати, записати, перечитати, звірити» (зведений чек-лист, групи 2 і 3). "
                    "Зелені сценарії лише читають. Жовті пишуть у рацію й повертають її як була; вони доступні лише після повного знімка у файл.",
                    purpose="замість сорока ручних кроків пройти ті, що машина робить краще за людину, і отримати один звіт-файл для надсилання.")
        snap = ttk.LabelFrame(self, text="Повний знімок перед записом (обов'язковий)")
        snap.pack(fill="x", padx=gt.PAD, pady=(gt.GAP, gt.GAP))
        self.snap_label = ttk.Label(snap, text="", wraplength=600, justify="left")
        self.snap_label.pack(anchor="w", padx=gt.GAP, pady=(gt.GAP, 2))
        self.snap_btn = ttk.Button(snap, text="Зробити повний знімок", command=self._on_snapshot)
        self.snap_btn.pack(anchor="w", padx=gt.GAP, pady=(2, 2))
        self.reg(self.snap_btn, radio=True)
        ttk.Label(snap, text=("Знімок читає з рації кодплаг, область custom-data, ключі AES, голосові підказки й базу позивних і перевіряє записаний файл за маніфестом. "
                              "Файл СЕКРЕТНИЙ (є ключі AES): не пересилай його. Без знімка сценарії запису недоступні."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=gt.GAP, pady=(0, gt.GAP))

        box = ttk.LabelFrame(self, text="Сценарії")
        box.pack(fill="x", padx=gt.PAD, pady=(gt.GAP, gt.GAP))
        for s in sc.SCENARIOS:
            row = ttk.Frame(box)
            row.pack(fill="x", padx=gt.GAP, pady=1)
            var = tk.BooleanVar(value=s.default_on)
            self.vars[s.sid] = var
            cb = ttk.Checkbutton(row, text="%s  %s" % (s.sid, s.title), variable=var)
            cb.pack(side="left")
            self.checks[s.sid] = cb
            tag = ttk.Label(row, text="  [%s]" % sc.RISK_TEXT[s.risk], foreground=gt.P[RISK_COLOR[s.risk]])
            tag.pack(side="left")
        ttk.Label(box, text=("S4.5 (ключі AES) немає навмисно: ціна помилки надто висока, перевірка ключів лишається ручною (чек-лист 2.7, 3.13). "
                             "Калібрування, ключі AES і база позивних недосяжні для сценаріїв запису; їхній SHA-256 порівнюється до і після."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=gt.GAP, pady=(gt.GAP, gt.GAP))

        bar = FlowFrame(self)
        bar.pack(fill="x", padx=gt.PAD, pady=(2, 2))
        self.run_btn = ttk.Button(bar, text="Пройти вибрані", command=self._on_run)
        self.read_btn = ttk.Button(bar, text="Вибрати всі читальні", command=lambda: self._select(sc.RISK_READ))
        self.none_btn = ttk.Button(bar, text="Зняти все", command=lambda: self._select(None))
        equal_buttons(self.run_btn, self.read_btn, self.none_btn)
        for b in (self.run_btn, self.read_btn, self.none_btn):
            bar.add(b)
        self.reg(self.run_btn, radio=True)

        self.bar = ttk.Progressbar(self, orient="horizontal", mode="determinate", maximum=100)
        self.bar.pack(fill="x", padx=gt.PAD, pady=(gt.GAP, 2))
        self.bar_label = ttk.Label(self, text="", wraplength=600, justify="left")
        self.bar_label.pack(anchor="w", padx=gt.PAD)
        self.log_box = scrolledtext.ScrolledText(self, height=12, state="disabled", font=("Consolas", 9))
        gt.style_text(self.log_box)
        self.log_box.pack(fill="both", expand=True, padx=gt.PAD, pady=(gt.GAP, gt.GAP))
        self.result_label = ttk.Label(self, text="", wraplength=600, justify="left")
        self.result_label.pack(anchor="w", padx=gt.PAD, pady=(0, gt.GAP))
        self._update_snapshot_ui()

    # --- допоміжне ----------------------------------------------------------------------------------

    def _select(self, risk):
        for s in sc.SCENARIOS:
            on = (risk is not None and s.risk == risk)
            if s.risk == sc.RISK_WRITE and not self.snapshot_ready():
                on = False
            self.vars[s.sid].set(on)

    def snapshot_ready(self):
        s = self.snapshot
        return bool(s and s.get("path") and os.path.isfile(s["path"]))

    def selected(self):
        return [s.sid for s in sc.SCENARIOS if self.vars[s.sid].get() and (s.risk == sc.RISK_READ or self.snapshot_ready())]

    def _update_snapshot_ui(self):
        if self.snapshot_ready():
            self.snap_label.config(text="Знімок зроблено: %s" % self.snapshot["path"], foreground=gt.P["ok"])
        else:
            self.snap_label.config(text="Знімка ще немає: сценарії запису вимкнено.", foreground=gt.P["warn"])
        for s in sc.SCENARIOS:
            if s.risk == sc.RISK_WRITE:
                busy = bool(self.shell.busy)
                state = "normal" if (self.snapshot_ready() and not busy) else "disabled"
                self.checks[s.sid].config(state=state)
                if not self.snapshot_ready():
                    self.vars[s.sid].set(False)

    def after_refresh(self):
        self._update_snapshot_ui()

    def _log(self, text):
        """Додати рядок у вікно журналу майстра (безпечно з робочого потоку) і в загальний журнал."""
        print(text)

        def put():
            self.log_box.config(state="normal")
            self.log_box.insert("end", text + "\n")
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.shell.post(put)

    def _progress(self, pct, text=""):
        def put():
            self.bar["value"] = pct
            self.bar_label.config(text=text)
        self.shell.post(put)
        self.shell.cps_progress(pct, text)

    def _make_ctx(self, link):
        ctx = sc.Ctx(link, output_dir(), log=self._log, progress=self._progress)
        ctx.snapshot = self.snapshot
        return ctx

    # --- знімок ---------------------------------------------------------------------------------------

    def _on_snapshot(self):
        if self.shell.busy:
            return
        self.shell.run_task(self.snapshot_worker, "Роблю повний знімок рації...", plain_errors=True, on_done=self._snapshot_done, ok_status="Знімок готовий.")

    def snapshot_worker(self):
        ser = cps.open_radio()
        try:
            ctx = self._make_ctx(cps.CpsLink(ser))
            return sc.take_snapshot(ctx)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def _snapshot_done(self, snap):
        self.snapshot = snap
        self._update_snapshot_ui()
        self.refresh_state()

    # --- прогін -----------------------------------------------------------------------------------------

    def _on_run(self):
        if self.shell.busy:
            return
        ids = self.selected()
        if not ids:
            self.result_label.config(text="Нічого не вибрано.", foreground=gt.P["warn"])
            return
        self.result_label.config(text="", foreground=gt.P["fg"])
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")
        self.shell.run_task(lambda: self.run_worker(ids), "Самоперевірка...", plain_errors=True, on_done=self._run_done, ok_status="Самоперевірку завершено.",
                            reconnect_ms=6000)

    def run_worker(self, ids):
        ser = cps.open_radio()
        try:
            ctx = self._make_ctx(cps.CpsLink(ser))
            return sc.run(ctx, ids, confirm_writes=self.shell.confirm_from_worker)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def _run_done(self, rep):
        self.last_report = rep
        c = rep.counts()
        bad = c[sc.FAIL] + c[sc.ERROR] + c[sc.INTERRUPTED]
        text = "Пройдено %d, не пройдено %d, помилок %d, обірвано %d, пропущено %d.\nЗвіт: %s" % (c[sc.PASS], c[sc.FAIL], c[sc.ERROR], c[sc.INTERRUPTED], c[sc.SKIPPED], rep.path)
        if rep.ctx.loud:
            text = "УВАГА: " + " ".join(rep.ctx.loud[:1]) + "\n" + text
        self.result_label.config(text=text, foreground=gt.P["err" if (bad or rep.ctx.loud) else "ok"])
        self._update_snapshot_ui()
