# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → APRS: бікон і позивний» (APRS-unify L5.4): налаштування бікона (custom-data тип 14), шумодав
приймача APRS (байт 4 блоку «Режиму APRS», тип 13). Позивний (ім'я рації, EEPROM 0x00E0) тут лише ПОКАЗУЄТЬСЯ: міняється він в одному
місці -- «Кодплаг → Основна інформація» (CPS-fix2 S1) і потрапляє в рацію разом із кодплагом. Те саме можна міняти з меню рації;
сховище одне. Станція (SSID, шляхи, символ, коментар, позиція...) -- у розділі «Кодплаг → APRS-слоти» (там працюють із документом кодплага). Рація має бути УВІМКНЕНА У
ЗВИЧАЙНОМУ РЕЖИМІ (не в DFU). Бікон рація підхоплює на старті -- після запису перезапусти її, інакше меню рації може записати
поверх старі значення з пам'яті. Логіку перенесено з gui_flasher.AprsBeaconWindow без змін."""
import tkinter as tk
from tkinter import ttk, messagebox

import aprs_beacon_cfg as abc_
import cps_link as cps
import gui_theme as gt

from .panel import Panel


class AprsPanel(Panel):
    key = "aprs"
    title = "APRS: бікон і позивний"
    radio_only = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.vars = {}
        self._build_ui()

    def _row(self, parent, label, make):
        """Рядок «підпис + поле». Поле створюється фабрикою make(рядок) -- саме В рядку (у старому вікні воно створювалось у
        батьківській рамці, і підписи та поля розсипались по різних місцях)."""
        f = ttk.Frame(parent)
        f.pack(fill="x", padx=8, pady=2)
        ttk.Label(f, text=label, width=34).pack(side="left")
        widget = make(f)
        widget.pack(side="left")
        return widget

    def _build_ui(self):
        self.header("APRS: бікон і позивний")
        ttk.Label(self, text=("Одне місце для кожного налаштування: позивний -- «Кодплаг → Основна інформація», бікон -- тут, станція -- «Кодплаг → APRS-слоти». "
                              "Після запису бікона перезапусти рацію."), wraplength=600, justify="left", foreground=gt.P["warn"]).pack(anchor="w", padx=12, pady=(0, 6))

        # Рамки лежать у двох колонках, коли панель широка (>= 900 px), і одна під одною, коли вузька (_relayout).
        self.cols = ttk.Frame(self)
        self.cols.pack(fill="x", padx=12, pady=0)
        self.col_a = ttk.Frame(self.cols)
        self.col_b = ttk.Frame(self.cols)
        self.cols.bind("<Configure>", self._relayout)
        self._wide = None
        who = ttk.LabelFrame(self.col_a, text="Позивний (лише перегляд) і приймач")
        who.pack(fill="x", padx=0, pady=4)
        self.vars["call"] = tk.StringVar()
        self.vars["call_doc"] = tk.StringVar()
        self.call_radio_label = self._row(who, "Позивний у рації", lambda f: ttk.Label(f, textvariable=self.vars["call"], width=12))
        self.call_doc_label = self._row(who, "Позивний у документі", lambda f: ttk.Label(f, textvariable=self.vars["call_doc"], width=12))
        self.call_note = ttk.Label(who, text="", wraplength=420, justify="left", foreground=gt.P["muted"])
        self.call_note.pack(anchor="w", padx=8, pady=(0, 4))
        link = ttk.Button(who, text="Змінити позивний: Кодплаг → Основна інформація", command=lambda: self.shell.show("basic"))
        link.pack(anchor="w", padx=8, pady=(0, 6))
        self.vars["sql"] = tk.StringVar(value="0")
        self._row(who, "Шумодав приймача APRS (0..21)", lambda f: ttk.Spinbox(f, from_=0, to=abc_.SQL_MAX, textvariable=self.vars["sql"], width=6))

        bc = ttk.LabelFrame(self.col_a, text="Бікон")
        bc.pack(fill="x", pady=4)
        self.vars["mode"] = tk.StringVar(value=abc_.MODE_NAMES[0])
        self._row(bc, "Режим", lambda f: ttk.Combobox(f, textvariable=self.vars["mode"], values=abc_.MODE_NAMES, state="readonly", width=14))
        self.vars["interval"] = tk.StringVar()
        ivals = ["%d с" % x if x < 60 else "%d хв" % (x // 60) for x in abc_.INITIAL_SECS]
        self._intervals = ivals
        self.vars["interval"].set(ivals[abc_.DEFAULT_BEACON["interval"]])
        self._row(bc, "Інтервал (стоковий)", lambda f: ttk.Combobox(f, textvariable=self.vars["interval"], values=ivals, state="readonly", width=14))
        self.vars["power"] = tk.StringVar(value="0")
        self._row(bc, "Потужність (0 -- як канал, 1..15)", lambda f: ttk.Spinbox(f, from_=0, to=15, textvariable=self.vars["power"], width=6))
        self.vars["source"] = tk.StringVar(value="Позиція каналу")
        self._row(bc, "Джерело позиції", lambda f: ttk.Combobox(f, textvariable=self.vars["source"], values=["Позиція каналу", "GPS"], state="readonly", width=14))
        self.vars["decay"] = tk.BooleanVar(value=True)
        self.vars["compressed"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(bc, text="Алгоритм затухання", variable=self.vars["decay"]).pack(anchor="w", padx=8)
        ttk.Checkbutton(bc, text="Стиснений формат позиції", variable=self.vars["compressed"]).pack(anchor="w", padx=8)
        self.vars["bcnwin"] = tk.StringVar(value=abc_.BCNWIN_NAMES[0])
        self._row(bc, "Вікно маяків приймача", lambda f: ttk.Combobox(f, textvariable=self.vars["bcnwin"], values=abc_.BCNWIN_NAMES, state="readonly", width=14))

        sm = ttk.LabelFrame(self.col_b, text="Розумний маяк")
        sm.pack(fill="x", pady=4)
        for key, label in (("slow", "Повільно, хв (1..100)"), ("fast", "Швидко, с (10..180)"), ("low", "Мала швидкість, км/год (2..30)"),
                           ("high", "Велика швидкість, км/год (2..90)"), ("angle", "Кут повороту, ° (5..90)"), ("slope", "Нахил повороту (1..255)"),
                           ("time", "Час повороту, с (5..180)")):
            lo, hi = abc_.RANGES[key]
            self.vars[key] = tk.StringVar(value=str(abc_.DEFAULT_BEACON[key]))
            self._row(sm, label, lambda f: ttk.Spinbox(f, from_=lo, to=hi, textvariable=self.vars[key], width=6))

        btn = ttk.Frame(self)
        btn.pack(fill="x", padx=12, pady=6)
        self.read_btn = ttk.Button(btn, text="Прочитати з рації", command=self._on_read)
        self.read_btn.pack(side="left")
        self.write_beacon_btn = ttk.Button(btn, text="Записати бікон і шумодав", command=self._on_write_beacon)
        self.write_beacon_btn.pack(side="left", padx=8)
        for b in (self.read_btn, self.write_beacon_btn):
            self.reg(b)
        ttk.Label(self, text="Натисни «Прочитати з рації», щоб підтягнути поточні значення.", foreground=gt.P["info"]).pack(anchor="w", padx=12)
        self.on_document_changed()

    def _relayout(self, e):
        wide = e.width >= 900
        if wide == self._wide:
            return
        self._wide = wide
        for w in (self.col_a, self.col_b):
            w.grid_forget()
        for c in (0, 1):
            self.cols.columnconfigure(c, weight=1 if wide else 0)
        if wide:
            self.col_a.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
            self.col_b.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        else:
            self.cols.columnconfigure(0, weight=1)
            self.col_a.grid(row=0, column=0, sticky="nsew")
            self.col_b.grid(row=1, column=0, sticky="nsew")

    def _apply_state(self, st):
        if st.get("call") is not None:
            self.vars["call"].set(st["call"] or "(не заданий)")
            self._radio_call = st["call"]
            self.on_document_changed()
        if st.get("sql") is not None:
            self.vars["sql"].set(str(st["sql"]))
        d = st.get("beacon")
        if d:
            self.vars["mode"].set(abc_.MODE_NAMES[d["mode"]])
            self.vars["interval"].set(self._intervals[d["interval"]])
            self.vars["power"].set(str(d["power"]))
            self.vars["source"].set("Позиція каналу" if d["source"] == "channel" else "GPS")
            self.vars["decay"].set(d["decay"])
            self.vars["compressed"].set(d["compressed"])
            self.vars["bcnwin"].set(abc_.BCNWIN_NAMES[d["bcnwin"]])
            for k in ("slow", "fast", "low", "high", "angle", "slope", "time"):
                self.vars[k].set(str(d[k]))

    def _collect(self):
        """Поля вікна -> (dict бікона, sql). abc_.AprsCfgError -- погане значення."""
        def num(k):
            try:
                return int(self.vars[k].get())
            except ValueError:
                raise abc_.AprsCfgError("%s: потрібне ціле число" % k)
        d = {
            "mode": abc_.MODE_NAMES.index(self.vars["mode"].get()),
            "interval": self._intervals.index(self.vars["interval"].get()),
            "power": num("power"),
            "source": "channel" if self.vars["source"].get() == "Позиція каналу" else "gps",
            "decay": bool(self.vars["decay"].get()), "compressed": bool(self.vars["compressed"].get()),
            "bcnwin": abc_.BCNWIN_NAMES.index(self.vars["bcnwin"].get()),
        }
        for k in ("slow", "fast", "low", "high", "angle", "slope", "time"):
            d[k] = num(k)
        abc_.beacon_build(d)    # перевірка меж
        sql = num("sql")
        abc_.mode_block_with_sql(None, sql)
        return d, sql

    _radio_call = None      # позивний, прочитаний з рації кнопкою «Прочитати з рації» (None -- ще не читали)

    def on_document_changed(self):
        """Показати позивний документа поряд із прочитаним з рації і сказати, що саме потрапить у рацію (S1.2)."""
        import codeplug_edit as ced
        d = self.doc
        if d is None:
            self.vars["call_doc"].set("(документ не відкрито)")
            self.call_note.config(text="Позивний у рації цією панеллю не змінюється. Його правлять у «Кодплаг → Основна інформація» (потрібен відкритий кодплаг).")
            return
        doc_call = ced.basic_values(d.image)["callsign"]
        self.vars["call_doc"].set(doc_call or "(не заданий)")
        if self._radio_call is None:
            self.call_note.config(text="Натисни «Прочитати з рації», щоб порівняти позивний документа з позивним у рації.")
        elif (self._radio_call or "") == (doc_call or ""):
            self.call_note.config(text="Позивний у документі збігається з позивним у рації.")
        else:
            self.call_note.config(text="Різні позивні. У рацію потрапить позивний ДОКУМЕНТА (%s) -- разом із кодплагом, дією «Записати в рацію»; "
                                       "позивний у рації (%s) буде замінено." % (doc_call or "порожній", self._radio_call or "порожній"),
                                  foreground=gt.P["warn"])
            return
        self.call_note.config(foreground=gt.P["muted"])

    def _run(self, fn, text, reconnect_ms=None):
        self.shell.run_task(fn, text, plain_errors=True, reconnect_ms=reconnect_ms)

    def _on_read(self):
        if not self.shell.busy:
            self._run(self._read_worker, "Читаю...")

    def _on_write_beacon(self):
        if self.shell.busy:
            return
        try:
            d, sql = self._collect()
        except abc_.AprsCfgError as e:
            messagebox.showerror("Помилка", str(e))
            return
        self._run(lambda: self._write_worker(d, sql), "Записую...")

    def _connect(self):
        return cps.open_radio()

    def _read_worker(self):
        ser = self._connect()
        try:
            st = abc_.read_state(ser)
            link = cps.CpsLink(ser)
            st["call"] = abc_.callsign_decode(link.read(cps.CPS_ACCESS_EEPROM, abc_.CALLSIGN_ADDR, abc_.CALLSIGN_LEN))
            self.shell.post(lambda: self._apply_state(st))
            print("Позивний: {}. Шумодав: {}. Бікон: {}".format(st["call"] or "(не заданий)", "типовий" if st["sql"] is None else st["sql"],
                                                                abc_.describe(st["beacon"])))
        finally:
            ser.close()

    def _write_worker(self, d, sql):
        ser = self._connect()
        try:
            for line in abc_.write_state(ser, beacon=d, sql=sql):
                print(line)
            print("Перезапусти рацію, щоб вона підхопила новий бікон.")
        finally:
            ser.close()
