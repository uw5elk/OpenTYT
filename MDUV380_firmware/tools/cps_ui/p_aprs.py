# -*- coding: utf-8 -*-
"""Розділ «Дані → APRS» (R75): станція (слоти), бікон і приймач -- УСЕ в документі.
  * «Станція (слоти)» (p_aprs_slots.StationBlock) -- конфіги станції в кодплазі документа;
  * «Бікон і приймач» -- налаштування стокового бікона (custom-data тип 14) і шумодав приймача APRS (байт 4 блоку «Режиму APRS», тип 13).
    R75: власних кнопок читання/запису рації тут більше нема -- поля читаються з документа, «Застосувати до документа» вносить правку, у рацію
    все йде однією дією «Записати в рацію» над розділами. Бікон рація підхоплює на старті -- після запису перезапусти її.
Позивний (ім'я рації, EEPROM 0x00E0) тут лише ПОКАЗУЄТЬСЯ довідково: міняється в «Основна інформація».
"""
import tkinter as tk
from tkinter import ttk, messagebox

import aprs_beacon_cfg as abc_
import gui_theme as gt

from .p_aprs_slots import StationBlock
from . import document as D
from .panel import Panel


class AprsPanel(Panel):
    key = "aprs"
    title = "APRS"
    doc_panel = True            # блок «Станція (слоти)» працює з документом; блок бікона без рації вимкнений кнопками (reg)

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
        self.header("APRS", "Один розділ, два шляхи запису: «Станція (слоти)» живе в документі кодплага, «Бікон і приймач» пишеться в рацію негайно.")

        # --- позивний: довідково ---
        who = ttk.LabelFrame(self, text="Позивний (лише перегляд)")
        who.pack(fill="x", padx=12, pady=4)
        self.vars["call"] = tk.StringVar()      # (R75: лишено для сумісності; показує позивний документа)
        self.vars["call_doc"] = tk.StringVar()
        self.call_doc_label = self._row(who, "Позивний у документі", lambda f: ttk.Label(f, textvariable=self.vars["call_doc"], width=12))
        self.call_note = ttk.Label(who, text="", wraplength=520, justify="left", foreground=gt.P["muted"])
        self.call_note.pack(anchor="w", padx=8, pady=(0, 4))
        link = ttk.Button(who, text="Змінити позивний: Кодплаг → Основна інформація", command=lambda: self.shell.show("basic"))
        link.pack(anchor="w", padx=8, pady=(0, 6))

        # --- станція (документ) ---
        self.station = StationBlock(self, self)
        self.station.pack(fill="x", padx=12, pady=6)

        # --- бікон і приймач (рація, негайно) ---
        radio_box = ttk.LabelFrame(self, text="Бікон і приймач (налаштування рації, входять у документ)")
        radio_box.pack(fill="x", padx=12, pady=6)
        self.radio_box = radio_box
        ttk.Label(radio_box, text=("Ці налаштування лежать у рації, а не в кодплазі, але тепер вони частина документа: змінюй тут, потім «Застосувати до документа», "
                                   "а в рацію все піде разом дією «Записати в рацію» над розділами. Після запису перезапусти рацію -- вона підхоплює бікон на старті."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(4, 2))

        # Рамки лежать у двох колонках, коли панель широка (>= 900 px), і одна під одною, коли вузька (_relayout).
        self.cols = ttk.Frame(radio_box)
        self.cols.pack(fill="x", padx=8, pady=0)
        self.col_a = ttk.Frame(self.cols)
        self.col_b = ttk.Frame(self.cols)
        self.cols.bind("<Configure>", self._relayout)
        self._wide = None
        bc = ttk.LabelFrame(self.col_a, text="Бікон")
        self.beacon_frame = bc
        bc.pack(fill="x", pady=4)
        self.vars["mode"] = tk.StringVar(value=abc_.MODE_NAMES[0])
        self.mode_combo = self._row(bc, "Режим", lambda f: ttk.Combobox(f, textvariable=self.vars["mode"], values=abc_.MODE_NAMES_UI, state="readonly", width=14))
        self.vars["interval"] = tk.StringVar()
        ivals = ["%d с" % x if x < 60 else "%d хв" % (x // 60) for x in abc_.INITIAL_SECS]
        self._intervals = ivals
        self.vars["interval"].set(ivals[abc_.DEFAULT_BEACON["interval"]])
        self._row(bc, "Інтервал (стоковий)", lambda f: ttk.Combobox(f, textvariable=self.vars["interval"], values=ivals, state="readonly", width=14))
        self.vars["power"] = tk.StringVar(value="0")
        self._row(bc, "Потужність при QSY (0 -- як канал)", lambda f: ttk.Spinbox(f, from_=0, to=15, textvariable=self.vars["power"], width=6))
        ttk.Label(bc, text="Рівень 1..15. Діє тільки коли в слоті APRS задана частота передачі (QSY): тоді кадр іде з цією потужністю. Без QSY передача йде з потужністю каналу.",
                  wraplength=360, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 4))
        self.vars["source"] = tk.StringVar(value="Позиція каналу")
        if not abc_.FORK_NO_GPS:    # R69 B1: без GPS-приймача рядок прихований; змінна лишається -- блок пишеться з її значенням
            self._row(bc, "Джерело позиції", lambda f: ttk.Combobox(f, textvariable=self.vars["source"], values=["Позиція каналу", "GPS"], state="readonly", width=17))
        self.vars["decay"] = tk.BooleanVar(value=True)
        self.vars["compressed"] = tk.BooleanVar(value=True)
        if not abc_.FORK_NO_GPS:    # R70 A3: без GPS затухання вимкнено скрізь -- чекбокс прихований, у рацію йде «вимкнено»
            ttk.Checkbutton(bc, text="Алгоритм затухання", variable=self.vars["decay"]).pack(anchor="w", padx=8)
        ttk.Checkbutton(bc, text="Стиснений формат позиції", variable=self.vars["compressed"]).pack(anchor="w", padx=8)
        ttk.Label(bc, text=("Яку позицію рація передає: якщо в слоті APRS увімкнено «Використовувати позицію» -- координати слота; інакше -- координати, збережені в рації. "
                            "Немає ні тих, ні тих -- кадр не передається."),
                  wraplength=360, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(4, 4))

        rx = ttk.LabelFrame(self.col_a, text="Приймач")
        self.rx_frame = rx
        rx.pack(fill="x", pady=4)
        self.vars["sql"] = tk.StringVar(value="0")
        self._row(rx, "Шумодав приймача APRS (0..21)", lambda f: ttk.Spinbox(f, from_=0, to=abc_.SQL_MAX, textvariable=self.vars["sql"], width=6))
        self.vars["bcnwin"] = tk.StringVar(value=abc_.BCNWIN_NAMES[0])      # R69 B3: «Вікно маяків» належить приймачу (так і в меню рації)
        self._row(rx, "Вікно маяків приймача", lambda f: ttk.Combobox(f, textvariable=self.vars["bcnwin"], values=abc_.BCNWIN_NAMES, state="readonly", width=14))

        sm = ttk.LabelFrame(self.col_b, text="Розумний маяк")
        self.smart_frame = sm
        if not abc_.FORK_NO_GPS:    # R69 B1: розумному маяку потрібні швидкість і курс (GPS); без приймача панель прихована, значення полів зберігаються
            sm.pack(fill="x", pady=4)
        for key, label in (("slow", "Повільно, хв (1..100)"), ("fast", "Швидко, с (10..180)"), ("low", "Мала швидкість, км/год (2..30)"),
                           ("high", "Велика швидкість, км/год (2..90)"), ("angle", "Кут повороту, ° (5..90)"), ("slope", "Нахил повороту (1..255)"),
                           ("time", "Час повороту, с (5..180)")):
            lo, hi = abc_.RANGES[key]
            self.vars[key] = tk.StringVar(value=str(abc_.DEFAULT_BEACON[key]))
            self._row(sm, label, lambda f: ttk.Spinbox(f, from_=lo, to=hi, textvariable=self.vars[key], width=6))

        btn = ttk.Frame(radio_box)
        btn.pack(fill="x", padx=8, pady=6)
        self.apply_btn = ttk.Button(btn, text="Застосувати до документа", command=self._on_apply)
        self.apply_btn.pack(side="left")
        self.reload_btn = ttk.Button(btn, text="Повернути значення з документа", command=self.on_document_changed)
        self.reload_btn.pack(side="left", padx=8)
        self.region_note = ttk.Label(radio_box, text="", wraplength=600, justify="left", foreground=gt.P["muted"])
        self.region_note.pack(anchor="w", padx=8, pady=(0, 6))
        self.on_document_changed()

    def on_avail(self, avail):
        """Дві колонки лише коли ВИДИМА ширина панелі вміщує обидві (за шириною розтягнутого вмісту рахувати не можна -- він сам росте від двох колонок)."""
        self._relayout(None, avail)

    def _relayout(self, e, avail=None):
        avail = avail or self.avail_width()
        wide = avail >= 960
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
        if st.get("call") is not None:        # (R75: лише для сумісності з тестами; позивний береться з документа)
            self.vars["call"].set(st["call"] or "(не заданий)")
        if st.get("sql") is not None:
            self.vars["sql"].set(str(st["sql"]))
        d = st.get("beacon")
        if d:
            d = abc_.no_gps_apply(d)     # R69 B2: показуємо те, що рація реально використає (без GPS: «канал», «Розумний» -> «Авто»)
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
        d = abc_.no_gps_apply(d)    # R69 B2: без GPS у рацію пишемо лише «канал» і «Авто» замість «Розумного» (прошивка робить те саме при завантаженні блока)
        abc_.beacon_build(d)    # перевірка меж
        sql = num("sql")
        abc_.mode_block_with_sql(None, sql)
        return d, sql

    def after_refresh(self):
        if hasattr(self, "station"):
            self.station.after_refresh()
        self._update_buttons()

    def on_document_changed(self):
        """Показати позивний документа й значення бікона/шумодава з документа."""
        if hasattr(self, "station"):
            self.station.on_document_changed()
        d = self.doc
        if d is not None and d.region is not None:
            self._apply_state(abc_.read_state(None, store=d.region))
            self.region_note.config(text="")
        else:
            self.region_note.config(text=("У документа нема налаштувань рації (файл створено старою версією) -- відкрий кодплаг з рації, "
                                          "щоб їх змінити." if d is not None else "Відкрий кодплаг з рації або з файла."))
        self._update_call_note()
        self._update_buttons()

    def _update_buttons(self):
        d = self.doc
        ok = d is not None and d.region is not None and not self.shell.busy
        for b in (self.apply_btn, self.reload_btn):
            b.config(state="normal" if ok else "disabled")

    def _update_call_note(self):
        import codeplug_edit as ced
        d = self.doc
        if d is None:
            self.vars["call_doc"].set("(документ не відкрито)")
            self.call_note.config(text="Позивний міняється в «Основна інформація».")
            return
        doc_call = ced.basic_values(d.image)["callsign"]
        self.vars["call_doc"].set(doc_call or "(не заданий)")
        self.vars["call"].set(doc_call or "(не заданий)")
        self.call_note.config(text="Позивний правиться в розділі «Основна інформація» і йде в рацію разом із кодплагом.", foreground=gt.P["muted"])

    def _on_apply(self):
        d = self.doc
        if d is None or d.region is None or self.shell.busy:
            return
        try:
            beacon, sql = self._collect()
            scratch = d.scratch_region()
            abc_.write_state(None, beacon=beacon, sql=sql, store=scratch)
            changed = d.apply_region(scratch, {abc_.TYPE_APRS_BEACON_CFG: "APRS: стоковий бікон", abc_.TYPE_APRS_MODE_CFG: "APRS: шумодав приймача"})
        except (abc_.AprsCfgError, D.DocumentError) as e:
            messagebox.showerror("APRS: бікон і приймач", str(e), parent=self.shell)
            return
        self.shell.set_status("Бікон і шумодав змінено в документі." if changed else "Змін немає.", "ok" if changed else "info")
