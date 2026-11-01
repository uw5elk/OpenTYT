# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Супутники» (R35 A): елементи орбіт для екрана супутників рації (custom-data блок SATELLITE_TLE, 25 слотів).

Блок НЕ є частиною кодплага (як і теми): він лежить в області custom-data SPI-флеша, тож «Записати в рацію» тут змінює рацію одразу, окремо від документа.
Формат блока, поля й обмеження -- у tools/sat_tle.py (з коду прошивки). Рація читає елементи при вході на екран супутників.

Порядок роботи: 1) «Прочитати з рації» -- що зараз у слотах; 2) джерело: файл TLE з диска або з мережі (Celestrak; мережа -- лише кнопками, адресу спершу перевір
«Перевірити джерело»); 3) відібрати з завантажених і покласти в слоти або оновити елементи супутників, які вже є; 4) «Записати в рацію» -- зі страховою копією блока
й звіркою читанням. Частоти й субтони супутників у файлі TLE немає -- R54: їх беруть із таблиці частот (формат `satellites.txt` офіційного CPS, tools/sat_table.py;
вбудована стартова таблиця або свій файл) за номером NORAD і задають у формі слота (усі три набори та шлях APRS; при оновленні наявних вони зберігаються)."""
import datetime
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import gui_dialogs as gd
import gui_theme as gt
import sat_table as stb
import sat_tle as st
import sat_update as su

from .layout import FitTable
from .common import output_dir
from .panel import Panel

SOURCES = [("Celestrak: аматорські (перевірено)", st.CELESTRAK_AMATEUR), ("Інша адреса", "")]


def _mhz(v):
    return ("%.6f" % (v / 1e6)).rstrip("0").rstrip(".") if v else ""


def _parse_mhz(text):
    t = (text or "").strip().replace(",", ".")
    if not t:
        return 0
    try:
        v = float(t)
    except ValueError:
        raise st.SatError("частота «%s» не число (МГц)" % text)
    if not (0 <= v <= 4000):
        raise st.SatError("частота %s МГц поза розумними межами" % text)
    return int(round(v * 1e6))


def _parse_ctcss(text):
    """Гц з десятковою частиною -> одиниці 0.1 Гц (так прошивка кладе в txTone), '' -> 0."""
    t = (text or "").strip().replace(",", ".")
    if not t:
        return 0
    try:
        v = float(t)
    except ValueError:
        raise st.SatError("субтон «%s» не число (Гц)" % text)
    if not (0 <= v <= 300):
        raise st.SatError("субтон %s Гц поза межами" % text)
    return int(round(v * 10))


class SatellitesPanel(Panel):
    key = "satellites"
    title = "Супутники"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.slots = []                  # робоча копія слотів (те, що буде записано)
        self.radio_state = None          # st.ST_* після читання
        self.radio_info = ""             # додаткові слова про блок у рації (приховані записи)
        self.base_bytes = None           # build_block(slots) на момент читання/запису -- для «є незаписані зміни»
        self.tles = []                   # завантажені набори елементів (sat_tle.Tle)
        self.tle_view = []               # відфільтровані
        self.src_var = tk.StringVar(value=SOURCES[0][0])
        self.url_var = tk.StringVar(value=SOURCES[0][1])
        self.search_var = tk.StringVar(value="")
        self.name_var = tk.StringVar()
        self.rx_var = tk.StringVar()
        self.tx_var = tk.StringVar()
        self.ctcss_var = tk.StringVar()
        self.arm_var = tk.StringVar()
        self.rx2_var = tk.StringVar()
        self.tx2_var = tk.StringVar()
        self.rx3_var = tk.StringVar()
        self.tx3_var = tk.StringVar()
        self.aprs_var = tk.StringVar()
        self.table_rows = []             # R54: рядки таблиці частот (sat_table.Row)
        self.table_notes = []            # що не вдалося прочитати
        self.table_source = ""           # звідки таблиця (для підпису)
        self.table_verified = None       # R55: datetime.date звірки (вбудована) або зміни файла (своя)
        self.now_override = None         # R55: поточний час для тестів (naive UTC datetime); None -- справжній
        self.fetch_fn = None             # R56: функція мережі (url, timeout) -> bytes; None -- справжня (sat_update.default_fetch); тести підміняють
        self.cache_dir = None            # R56: тека кешу TLE; None -- ~/MD-UV390UKR/cache
        self.detail_open = False         # R56: розгорнутий блок «Детально»
        self._snapshot_reminded = False  # R56: нагадування про повний знімок -- один раз за сесію
        self.last_plan = None            # R56: останній план оновлення (для тестів і підсумку)
        self._build_ui()
        self._load_initial_table()
        self._redraw_slots()

    # --- побудова ---------------------------------------------------------------------------------

    def _build_ui(self):
        self.header("Супутники", purpose="поновити TLE супутників у рації.")
        main = ttk.Frame(self)
        main.pack(fill="x", padx=12, pady=(0, 2))
        self.radio_status_label = ttk.Label(main, text="Рація не прочитана", wraplength=640, justify="left")
        self.radio_status_label.pack(anchor="w")
        self.table_label = ttk.Label(main, text="", wraplength=640, justify="left")
        self.table_label.pack(anchor="w")
        self.recheck_label = ttk.Label(main, text="", wraplength=640, justify="left", foreground=gt.P["warn"])
        act = ttk.Frame(main)
        act.pack(fill="x", pady=(6, 2))
        self._act_row = act
        self.update_btn_all = ttk.Button(act, text="Оновити супутники", style="Big.TButton", command=self._on_update_all)
        self.update_btn_all.pack(side="left")
        self.reg(self.update_btn_all, radio=False)
        self.detail_btn = ttk.Button(act, text="Детально ▸", command=self.toggle_detail)
        self.detail_btn.pack(side="left", padx=16)
        ttk.Label(main, text=("Бере свіжі TLE, показує підсумок і лише після твого підтвердження пише в рацію."),
                  wraplength=640, justify="left", foreground=gt.P["muted"]).pack(anchor="w")
        self.detail = ttk.Frame(self)           # R56: усе старе -- у згорнутому блоці (поведінка не змінена)
        ttk.Label(self.detail, text=("Елементи орбіт (TLE) для екрана супутників рації: до 25 слотів. Блок лежить в окремій області флеша рації, тому «Записати в рацію» "
                                     "тут змінює рацію одразу, окремо від кодплага. TLE застарівають -- зі старими елементами прогноз прольотів неточний."),
                  wraplength=640, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 4))
        box = ttk.LabelFrame(self.detail, text="1. Що в рації (25 слотів)")
        box.pack(fill="x", padx=12, pady=6)
        bar = ttk.Frame(box)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        self.read_btn = ttk.Button(bar, text="Прочитати з рації", command=self._on_read)
        self.read_btn.pack(side="left")
        self.reg(self.read_btn)
        self.write_btn = ttk.Button(bar, text="Записати в рацію...", command=self._on_write)
        self.write_btn.pack(side="left", padx=8)
        self.reg(self.write_btn)
        self.del_btn = ttk.Button(bar, text="Прибрати слот", command=self._on_remove_slot)
        self.del_btn.pack(side="left", padx=8)
        self.up_btn = ttk.Button(bar, text="Вгору", command=lambda: self._move(-1), width=7)
        self.up_btn.pack(side="left")
        self.dn_btn = ttk.Button(bar, text="Вниз", command=lambda: self._move(1), width=7)
        self.dn_btn.pack(side="left", padx=4)
        self.state_label = ttk.Label(box, text="Рацію ще не читали.", foreground=gt.P["muted"], wraplength=640, justify="left")
        self.state_label.pack(anchor="w", padx=8, pady=(0, 2))
        slot_tbl = FitTable(box, [("n", "№", 34, 0), ("name", "Назва", 90, 0), ("epoch", "Епоха", 90, 0), ("age", "Вік TLE", 120, 0), ("inc", "Нахил, °", 70, 0),
                                  ("period", "Період, хв", 80, 0), ("freq", "Частоти", 240, 1)], height=8)
        self.slot_tree = slot_tbl.tree
        slot_tbl.pack(fill="x", padx=8, pady=4)
        self.slot_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_slot_selected())
        self.slot_tree.tag_configure("nofreq", foreground=gt.P["warn"])
        self.slot_tree.tag_configure("stale", foreground=gt.P["warn"])
        self.slot_tree.tag_configure("old", foreground=gt.P["err"])
        self.slot_tree.tag_configure("bad", foreground=gt.P["err"])
        self.stale_label = ttk.Label(box, text="", foreground=gt.P["warn"], wraplength=640, justify="left")
        self.stale_label.pack(anchor="w", padx=8)
        self.issue_label = ttk.Label(box, text="", foreground=gt.P["warn"], wraplength=640, justify="left")
        self.issue_label.pack(anchor="w", padx=8)
        form = ttk.Frame(box)
        form.pack(fill="x", padx=8, pady=(4, 8))
        fields = (
            (0, 0, "Назва (до 8 лат. символів)", self.name_var, 12), (0, 1, "RX, МГц", self.rx_var, 10), (0, 2, "TX, МГц", self.tx_var, 10),
            (0, 3, "Субтон передачі, Гц", self.ctcss_var, 8), (0, 4, "Субтон взведення (передача), Гц", self.arm_var, 8),
            (2, 0, "Шлях APRS (напр. RS0ISS)", self.aprs_var, 12), (2, 1, "APRS RX, МГц", self.rx2_var, 10), (2, 2, "APRS TX, МГц", self.tx2_var, 10),
            (2, 3, "Маяк RX, МГц", self.rx3_var, 10), (2, 4, "Маяк TX, МГц", self.tx3_var, 10))
        for row, col, label, var, w in fields:
            ttk.Label(form, text=label).grid(row=row, column=col, sticky="w", padx=(0, 6), pady=(4 if row else 0, 0))
            ttk.Entry(form, textvariable=var, width=w).grid(row=row + 1, column=col, sticky="w", padx=(0, 6))
        self.apply_btn = ttk.Button(form, text="Застосувати до слота", command=self._on_apply_form)
        self.apply_btn.grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Label(form, text="Порожньо або 0 = цього набору нема. Набір «маяк» -- лише прийом. Приймання завжди без субтону. Субтон передачі 67 Гц вводь як 67, 88,5 -- як 88.5.",
                  wraplength=640, justify="left", foreground=gt.P["muted"]).grid(row=5, column=0, columnspan=5, sticky="w", pady=(2, 0))

        src = ttk.LabelFrame(self.detail, text="2. Джерело елементів")
        src.pack(fill="x", padx=12, pady=6)
        row = ttk.Frame(src)
        row.pack(fill="x", padx=8, pady=(6, 2))
        combo = ttk.Combobox(row, textvariable=self.src_var, values=[s[0] for s in SOURCES], state="readonly", width=42)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", self._on_source_changed)
        ttk.Entry(row, textvariable=self.url_var, width=60).pack(side="left", padx=8, fill="x", expand=True)
        row2 = ttk.Frame(src)
        row2.pack(fill="x", padx=8, pady=(2, 4))
        self.probe_btn = ttk.Button(row2, text="Перевірити джерело", command=self._on_probe)
        self.probe_btn.pack(side="left")
        self.reg(self.probe_btn, radio=False)
        self.net_btn = ttk.Button(row2, text="Завантажити з мережі у файл...", command=self._on_download)
        self.net_btn.pack(side="left", padx=8)
        self.reg(self.net_btn, radio=False)
        self.open_btn = ttk.Button(row2, text="Відкрити файл TLE...", command=self._on_open_file)
        self.open_btn.pack(side="left", padx=8)
        self.reg(self.open_btn, radio=False)
        ttk.Label(src, text=("Мережа вмикається лише кнопками: «Перевірити джерело» запитує перші ~2 КБ і показує, що прийшло; «Завантажити з мережі» кладе весь файл у "
                             "обране тобою місце. Адресу Celestrak перевірено 2026-11-01: відповідь 200, text/plain, близько 16 КБ, справжні набори TLE. Ці кнопки нічого не кешують; "
                             "кнопка «Оновити супутники» кешує відповіді в теці cache поряд зі знімками і не питає Celestrak частіше, ніж раз на %d год." % su.TLE_CACHE_HOURS),
                  wraplength=640, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 2))
        self.src_label = ttk.Label(src, text="Файл не відкрито.", foreground=gt.P["muted"], wraplength=640, justify="left")
        self.src_label.pack(anchor="w", padx=8, pady=(0, 6))

        tbl = ttk.LabelFrame(self.detail, text="3. Таблиця частот")
        tbl.pack(fill="x", padx=12, pady=6)
        self.table_count_label = ttk.Label(tbl, text="", wraplength=640, justify="left")
        self.table_count_label.pack(anchor="w", padx=8, pady=(6, 0))
        self.table_notes_label = ttk.Label(tbl, text="", wraplength=640, justify="left", foreground=gt.P["warn"])
        trow = ttk.Frame(tbl)
        trow.pack(fill="x", padx=8, pady=(6, 2))
        self._tbl_first = trow
        self.add_table_btn = ttk.Button(trow, text="Додати з таблиці", command=self._on_add_table)
        self.add_table_btn.pack(side="left")
        self.fill_table_btn = ttk.Button(trow, text="Заповнити порожні слоти з таблиці", command=self._on_fill_table)
        self.fill_table_btn.pack(side="left", padx=8)
        trow2 = ttk.Frame(tbl)
        trow2.pack(fill="x", padx=8, pady=(2, 2))
        self.open_table_btn = ttk.Button(trow2, text="Відкрити свою таблицю...", command=self._on_open_table)
        self.open_table_btn.pack(side="left")
        self.builtin_table_btn = ttk.Button(trow2, text="Вбудована таблиця", command=self._on_builtin_table)
        self.builtin_table_btn.pack(side="left", padx=8)
        ttk.Label(tbl, text=("Формат -- той самий, що в `satellites.txt` офіційного CPS (можна підкинути новіший файл). Частоти беруться за НОМЕРОМ NORAD; у слотах, "
                             "прочитаних з рації, номера нема -- там збіг за назвою. Вручну введені частоти таблиця не перезаписує. Частоти з таблиці -- з документації "
                             "(tools/satellites_sources.md), на залізі НЕ ПЕРЕВІРЕНІ."),
                  wraplength=640, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 6))

        sel = ttk.LabelFrame(self.detail, text="4. Відбір і слоти")
        sel.pack(fill="both", expand=True, padx=12, pady=6)
        srow = ttk.Frame(sel)
        srow.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(srow, text="Пошук за назвою або номером NORAD:").pack(side="left")
        ttk.Entry(srow, textvariable=self.search_var, width=24).pack(side="left", padx=8)
        self.search_var.trace_add("write", lambda *_a: self._refilter())
        self.counts_label = ttk.Label(sel, text="", wraplength=640, justify="left")
        self.counts_label.pack(anchor="w", padx=8, pady=2)
        body = ttk.Frame(sel)
        body.pack(fill="both", expand=True, padx=8, pady=4)
        tle_tbl = FitTable(body, [("name", "Назва у файлі", 200, 0), ("short", "На рації", 80, 0), ("norad", "NORAD", 60, 0), ("epoch", "Епоха", 90, 0),
                                  ("age", "Вік, дн.", 60, 0), ("note", "Зауваження", 200, 1)], height=9, selectmode="extended")
        self.tle_tree = tle_tbl.tree
        tle_tbl.pack(fill="both", expand=True)
        self.tle_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_counts())
        bar2 = ttk.Frame(sel)
        bar2.pack(fill="x", padx=8, pady=(2, 8))
        self.add_btn = ttk.Button(bar2, text="Додати вибрані у вільні слоти", command=self._on_add)
        self.add_btn.pack(side="left")
        self.replace_btn = ttk.Button(bar2, text="Замінити всі слоти вибраними", command=self._on_replace)
        self.replace_btn.pack(side="left", padx=8)
        self.update_btn = ttk.Button(bar2, text="Оновити елементи наявних слотів за назвою", command=self._on_update_existing)
        self.update_btn.pack(side="left", padx=8)

    # --- слоти ------------------------------------------------------------------------------------

    def _redraw_slots(self, select=None):
        self.slot_tree.delete(*self.slot_tree.get_children())
        for i, s in enumerate(self.slots):
            _days, alvl = st.age_level(s, self.now_override)
            levels = {lvl for lvl, _t in stb.check_slot(s)}
            if "error" in levels:
                tag = ("bad",)
            elif alvl == st.AGE_OLD:
                tag = ("old",)
            elif alvl == st.AGE_STALE:
                tag = ("stale",)
            elif "nofreq" in levels:
                tag = ("nofreq",)
            else:
                tag = ()
            self.slot_tree.insert("", "end", iid=str(i), tags=tag, values=(
                i + 1, s.name, st.epoch_text(s), st.age_text(s, self.now_override), ("%.2f" % s.inclination) if s.inclination is not None else "?",
                ("%.1f" % s.period_min) if s.period_min else "?", s.freq_text()))
        if select is not None and 0 <= select < len(self.slots):
            self.slot_tree.selection_set(str(select))
        stale, has_old = st.age_summary(self.slots, self.now_override)
        self.stale_label.config(text=stale, foreground=gt.P["err"] if has_old else gt.P["warn"])
        self.issue_label.config(text=self.issue_summary())
        self._update_state_label()
        self._update_counts()

    def _update_state_label(self):
        if self.radio_state is None:
            text = "Рацію ще не читали; у таблиці те, що ти зібрав."
        else:
            text = st.STATE_TEXT[self.radio_state]
        text += " Слотів у робочій копії: %d з %d." % (len(self.slots), st.NUM_SLOTS)
        if self.is_dirty():
            text += " Є незаписані зміни."
        if self.radio_info:
            text += " " + self.radio_info
        self.state_label.config(text=text)
        self._update_radio_status()

    def _update_radio_status(self):
        """R56: рядок стану рації у головному вигляді: «У рації: N супутників, найстаріший TLE: X діб» (колір за порогами R55) або «Рація не прочитана»."""
        radio_slots = []
        if self.radio_state is not None and self.base_bytes is not None:
            try:
                radio_slots = st.parse_block(self.base_bytes).slots           # саме те, що в рації (прочитано або записано), а не робоча копія
            except st.SatError:
                radio_slots = []
        text, level = su.radio_status_text(radio_slots, self.radio_state if self.base_bytes is not None else None, self.now_override)
        if self.radio_state is not None and self.is_dirty():
            text += "; у слотах є незаписані зміни"
        color = {"ok": gt.P["fg"], "none": gt.P["muted"], "stale": gt.P["warn"], "old": gt.P["err"]}[level]
        self.radio_status_label.config(text=text, foreground=color)

    def is_dirty(self):
        try:
            return st.build_block(self.slots) != self.base_bytes
        except st.SatError:
            return True

    def selected_slot(self):
        sel = self.slot_tree.selection()
        return int(sel[0]) if sel else None

    def issue_summary(self):
        """Підсумок перевірки частот робочих слотів (без вікон): помилки, попередження, слоти без частот."""
        errors, warns, nofreq = stb.validate_slots(self.slots)
        parts = []
        if errors:
            parts.append("ПОМИЛКИ (записати не вдасться): " + "; ".join(errors))
        if warns:
            parts.append("Попередження: " + "; ".join(warns))
        if nofreq:
            parts.append("Без частот: %s." % ", ".join(l.split("«")[1].split("»")[0] for l in nofreq))
        return " ".join(parts)

    def _on_slot_selected(self):
        i = self.selected_slot()
        if i is None or i >= len(self.slots):
            return
        s = self.slots[i]
        self.name_var.set(s.name)
        self.rx_var.set(_mhz(s.rx1))
        self.tx_var.set(_mhz(s.tx1))
        self.ctcss_var.set(("%g" % (s.ctcss / 10.0)) if s.ctcss else "")
        self.arm_var.set(("%g" % (s.arm / 10.0)) if s.arm else "")
        self.rx2_var.set(_mhz(s.rx2))
        self.tx2_var.set(_mhz(s.tx2))
        self.rx3_var.set(_mhz(s.rx3))
        self.tx3_var.set(_mhz(s.tx3))
        self.aprs_var.set(stb.decode_aprs(s.extra))

    def apply_form(self, index, name, rx, tx, ctcss, arm=None, rx2=None, tx2=None, rx3=None, tx3=None, aprs=None):
        """Застосувати значення форми до слота index (логіка без вікон). SatError -- пояснення, слот не змінюється. Поле None -- не чіпати (старі виклики
        з чотирма полями працюють як раніше); шлях APRS, який не змінився проти поточного, байтів не переписує."""
        s = self.slots[index].copy()
        nm = (name or "").strip()
        if not nm:
            raise st.SatError("назва порожня")
        if len(nm) > st.NAME_LEN or any(not (0x20 <= ord(ch) < 0x7F) for ch in nm):
            raise st.SatError("назва має бути до %d символів ASCII (латиниця, цифри, знаки)" % st.NAME_LEN)
        s.name = nm
        s.rx1, s.tx1 = _parse_mhz(rx), _parse_mhz(tx)
        s.ctcss = _parse_ctcss(ctcss)
        if arm is not None:
            s.arm = _parse_ctcss(arm)
        if rx2 is not None:
            s.rx2 = _parse_mhz(rx2)
        if tx2 is not None:
            s.tx2 = _parse_mhz(tx2)
        if rx3 is not None:
            s.rx3 = _parse_mhz(rx3)
        if tx3 is not None:
            s.tx3 = _parse_mhz(tx3)
        if aprs is not None and aprs.strip() != stb.decode_aprs(s.extra):
            s.extra = stb.encode_aprs(aprs, s.extra)
        self.slots[index] = s
        return s

    def _on_apply_form(self):
        i = self.selected_slot()
        if i is None:
            messagebox.showinfo("Супутники", "Спершу вибери слот у таблиці.", parent=self.shell)
            return
        try:
            self.apply_form(i, self.name_var.get(), self.rx_var.get(), self.tx_var.get(), self.ctcss_var.get(), arm=self.arm_var.get(),
                            rx2=self.rx2_var.get(), tx2=self.tx2_var.get(), rx3=self.rx3_var.get(), tx3=self.tx3_var.get(), aprs=self.aprs_var.get())
        except st.SatError as e:
            messagebox.showerror("Супутники", str(e), parent=self.shell)
            return
        self._redraw_slots(select=i)

    def _on_remove_slot(self):
        i = self.selected_slot()
        if i is None:
            return
        del self.slots[i]
        self._redraw_slots(select=min(i, len(self.slots) - 1))

    def _move(self, d):
        i = self.selected_slot()
        if i is None or not (0 <= i + d < len(self.slots)):
            return
        self.slots[i], self.slots[i + d] = self.slots[i + d], self.slots[i]
        self._redraw_slots(select=i + d)

    # --- читання/запис ----------------------------------------------------------------------------

    def _on_read(self):
        if self.shell.busy:
            return
        if self.is_dirty() and self.slots and not gd.confirm_dialog(self.shell, "Прочитати з рації?", "Читання замінить слоти тим, що зараз у рації; "
                                                                      "незаписані зміни пропадуть. Продовжити?", yes="Прочитати", no="Скасувати"):
            return
        self.shell.run_task(self._read_worker, "Читаю супутники з рації...", plain_errors=True)

    def _read_worker(self):
        ser = cps.open_radio()
        try:
            state, blk, _raw = st.read_slots(ser)
        finally:
            ser.close()
        self.shell.post(lambda: self.apply_read(state, blk))

    def apply_read(self, state, blk):
        self.radio_state = state
        self.radio_info = ""
        self.slots = [s.copy() for s in blk.slots] if blk is not None else []
        if blk is not None and blk.hidden:
            self.radio_info = "У блоці є ще %d записів ПІСЛЯ порожнього слота -- рація їх не бачить, при записі вони зникнуть." % blk.hidden
        try:
            self.base_bytes = st.build_block(self.slots)
        except st.SatError:
            self.base_bytes = None
        self._redraw_slots()

    def _on_write(self):
        if self.shell.busy:
            return
        if self.radio_state in (st.ST_NOREGION, st.ST_BADLEN):
            messagebox.showerror("Супутники", "Записати не можна: %s." % st.STATE_TEXT[self.radio_state], parent=self.shell)
            return
        try:
            st.build_block(self.slots)
        except st.SatError as e:
            messagebox.showerror("Супутники", str(e), parent=self.shell)
            return
        errors, warns, nofreq = stb.validate_slots(self.slots)
        if errors:
            messagebox.showerror("Супутники", "Записати не можна -- частоти поза смугами рації:\n\n" + "\n".join(errors) + "\n\nВиправ їх у формі слота.", parent=self.shell)
            return
        lines = ["У рацію буде записано супутників: %d з %d." % (len(self.slots), st.NUM_SLOTS), ""]
        lines += ["  %d. %s (епоха %s, вік %s; %s)" % (i + 1, s.name, st.epoch_text(s), st.age_text(s, self.now_override), s.freq_text()) for i, s in enumerate(self.slots)]
        stale, _has_old = st.age_summary(self.slots, self.now_override)
        if stale:
            lines += ["", stale]
        if warns:
            lines += ["", "ПОПЕРЕДЖЕННЯ щодо передачі:"] + ["  " + w for w in warns]
        if nofreq:
            lines += ["", "Слоти без частот (екран супутників не покаже частот, передача заблокована): %s." % ", ".join(l.split("«")[1].split("»")[0] for l in nofreq)]
        if self.radio_state is None:
            lines += ["", "Рацію ще не читали: невідомо, що в ній зараз. Запис замінить блок супутників повністю."]
        lines += ["", "Це змінює рацію одразу (поза кодплагом). Спершу блок, що зараз у рації, збережеться у файл-страхову копію. Після запису відкрий екран супутників."]
        if self.confirm_old_slots() is False:
            return
        if not gd.confirm_dialog(self.shell, "Записати супутники в рацію?", "\n".join(lines), yes="Записати", no="Скасувати"):
            return
        snapshot = [s.copy() for s in self.slots]
        self.shell.run_task(lambda: self._write_worker(snapshot), "Записую супутники в рацію...", plain_errors=True, on_done=self._write_done)

    def confirm_old_slots(self):
        """R55 (C2): слоти з червоним віком (понад %d діб) -- окреме явне підтвердження; запис НЕ блокується. None -- таких слотів нема, True / False -- відповідь.""" % st.TLE_AGE_STALE_DAYS
        old = st.old_slots(self.slots, self.now_override)
        if not old:
            return None
        text = ("Елементи орбіти цих слотів старші за %d діб:\n\n" % st.TLE_AGE_STALE_DAYS + "\n".join("  %d. %s -- %d діб" % o for o in old) +
                "\n\nПрогноз прольотів і доплер із таких елементів ненадійні. Завантаж свіжі (крок 2) або запиши все одно.")
        return bool(gd.confirm_dialog(self.shell, "Старі елементи орбіти", text, yes="Записати все одно", no="Скасувати"))

    def _write_worker(self, snapshot):
        ser = cps.open_radio()
        try:
            text, _safety = st.write_slots(ser, snapshot, safety_dir=output_dir(), log=print)
        finally:
            ser.close()
        print(text)
        self.shell.post(lambda: self.mark_written(snapshot))
        return text

    def mark_written(self, snapshot):
        self.radio_state = st.ST_OK
        self.base_bytes = st.build_block(snapshot)
        self._update_state_label()

    def _write_done(self, text):
        messagebox.showinfo("Супутники", text, parent=self.shell)

    # --- R56: «Оновити супутники» одним натисканням --------------------------------------------------

    def toggle_detail(self, open_=None):
        """Згорнути / розгорнути блок «Детально» (усе старе: таблиця слотів, форма, джерело, таблиця частот, відбір)."""
        self.detail_open = (not self.detail_open) if open_ is None else bool(open_)
        if self.detail_open:
            self.detail.pack(fill="both", expand=True)
            self.detail_btn.config(text="Детально ▾")
        else:
            self.detail.pack_forget()
            self.detail_btn.config(text="Детально ▸")
        self.after_idle(self.rewrap)

    def _now(self):
        return self.now_override or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    def _cache_path_dir(self):
        return self.cache_dir or os.path.join(output_dir(), "cache")

    def _read_radio(self):
        """-> (стан, Block|None) -- читання слотів із рації (у робочому потоці)."""
        ser = cps.open_radio()
        try:
            state, blk, _raw = st.read_slots(ser)
        finally:
            ser.close()
        return state, blk

    def _on_update_all(self):
        if self.shell.busy:
            return
        if not self.table_rows:
            messagebox.showinfo("Супутники", "Таблиця частот порожня -- відкрий таблицю в «Детально» (розділ 3).", parent=self.shell)
            return
        need_read = bool(self.shell.conn.found) and self.radio_state is None
        if need_read and self.is_dirty() and self.slots and not gd.confirm_dialog(
                self.shell, "Прочитати з рації?", "Рацію ще не читали, а в слотах є незаписані зміни: читання замінить їх тим, що зараз у рації. Продовжити?",
                yes="Прочитати", no="Скасувати"):
            return
        rows = list(self.table_rows)
        self.shell.run_task(lambda: self.update_fetch(rows, need_read), "Оновлюю супутники: читаю рацію й TLE...", plain_errors=True, ok_status="Підсумок готовий.",
                            on_done=self.update_after_fetch)

    def update_fetch(self, rows, need_read):
        """Робочий потік: прочитати слоти (якщо треба) і взяти TLE. Збій мережі НЕ кидає виняток -- інакше втратилось би прочитане з рації."""
        radio = self._read_radio() if need_read else None
        net_err, res = "", None
        try:
            res = su.fetch_tles(rows, self._now(), self._cache_path_dir(), fetch=self.fetch_fn)
        except su.NetError as e:
            net_err = str(e)
        return radio, res, net_err

    def update_after_fetch(self, data):
        radio, res, net_err = data
        if radio is not None:
            self.apply_read(*radio)
        if net_err:
            messagebox.showerror("Супутники", "%s\n\n(%s)\nНічого не змінено." % (su.NO_NET_TEXT, net_err), parent=self.shell)
            return
        self.update_ask(res)

    def update_summary_text(self, plan, res, now, have_radio, state):
        lines = ["Підсумок оновлення. Поки що НІЧОГО не записано ні в рацію, ні в слоти.", "", su.plan_text(plan, now)]
        if self.is_dirty():
            lines += ["", "У слотах уже були незаписані зміни -- вони теж увійдуть у запис."]
        if res is not None:
            src = "з кешу" if su.GROUP_KEY in res.from_cache else "з мережі"
            lines += ["", "TLE: група amateur Celestrak (%s); окремих запитів за номером: %d." % (src, len([u for u in res.requests if "CATNR" in u]))]
            if res.errors:
                lines.append("Не вдалося запитати: " + "; ".join(res.errors) + ".")
        stale, _has_old = st.age_summary(plan.slots, now)
        lines.append("Вік TLE у слотах після оновлення: %s" % (stale or "усі свіжі."))
        old = st.old_slots(plan.slots, now)
        if old:
            lines += ["", "СТАРІ елементи (понад %d діб) лишаються: %s. Прогноз прольотів і доплер із них ненадійні; запис потребує явної згоди (кнопка нижче)." % (
                st.TLE_AGE_STALE_DAYS, ", ".join("%s (%d діб)" % (n, d) for _i, n, d in old))]
        if plan.warns:
            lines += ["", "ПОПЕРЕДЖЕННЯ щодо передачі:"] + ["  " + w for w in plan.warns]
        if plan.nofreq:
            lines += ["", "Слоти без частот (екран супутників не покаже частот, передача заблокована): %s." % ", ".join(l.split("«")[1].split("»")[0] for l in plan.nofreq)]
        if state in (st.ST_NOREGION, st.ST_BADLEN):
            lines += ["", "Записати в рацію не можна: %s." % st.STATE_TEXT[state]]
        elif not have_radio:
            lines += ["", "Рацію не знайдено -- запис не пропонується. «Лише в документ» залишить результат у слотах (розділ «Детально») для запису пізніше."]
        else:
            lines += ["", "«Записати в рацію» змінює рацію одразу (поза кодплагом): спершу блок, що зараз у рації, збережеться у файл-страхову копію, потім запис і звірка читанням; "
                          "після запису слоти буде перечитано."]
            if not self._snapshot_reminded:
                lines += ["", "Перед ПЕРШИМ записом за сесію зроби повний знімок рації (розділ «Бекап і відновлення»), якщо ще не робив."]
        return "\n".join(lines)

    def update_ask(self, res):
        """Побудувати план у пам'яті, показати ОДНЕ вікно підсумку й виконати вибір. Скасувати / Лише в документ нічого не пишуть у рацію."""
        now = self._now()
        plan = su.build_plan(self.slots, self.table_rows, res.tles, now)
        self.last_plan = plan
        have_radio = bool(self.shell.conn.found)
        state = self.radio_state
        can_write = self.can_write_plan(plan)
        text = self.update_summary_text(plan, res, now, have_radio, state)
        if not plan.changed:
            gd.text_dialog(self.shell, "Оновити супутники", text)
            return
        old = st.old_slots(plan.slots, now)
        buttons = []
        if can_write:
            buttons.append(("Записати все одно (є старі TLE)" if old else "Записати в рацію", "radio"))
        buttons += [("Лише в документ", "doc"), ("Скасувати", "cancel")]
        if can_write:
            self._snapshot_reminded = True
        choice = gd.choice_dialog(self.shell, "Оновити супутники", text, buttons, default_index=len(buttons) - 1)
        self.update_apply_choice(plan, choice)

    def can_write_plan(self, plan):
        """Запис у рацію дозволений: рацію знайдено й слоти прочитано, блок придатний, помилок перевірки частот нема."""
        return bool(self.shell.conn.found) and self.radio_state not in (None, st.ST_NOREGION, st.ST_BADLEN) and not plan.errors

    def update_apply_choice(self, plan, choice):
        if choice not in ("radio", "doc"):
            return                    # скасовано: слоти й рація не змінені
        if choice == "radio" and not self.can_write_plan(plan):
            messagebox.showerror("Супутники", "Записати в рацію зараз не можна (рацію не знайдено, блок непридатний або є помилки перевірки частот). Нічого не записано.", parent=self.shell)
            return
        try:
            st.build_block(plan.slots)
        except st.SatError as e:
            messagebox.showerror("Супутники", str(e), parent=self.shell)
            return
        self.slots = [s.copy() for s in plan.slots]
        self._redraw_slots()
        if choice == "doc":
            self.shell.set_status("Супутники: оновлено лише в слотах; у рацію не записано.", "info")
            return
        snapshot = [s.copy() for s in self.slots]
        self.shell.run_task(lambda: self._update_write_worker(snapshot), "Записую супутники в рацію...", plain_errors=True, on_done=self._update_write_done)

    def _update_write_worker(self, snapshot):
        """Той самий безпечний запис, що й кнопка «Записати в рацію» (страхова копія, звірка читанням у st.write_slots), потім перечитування слотів."""
        ser = cps.open_radio()
        try:
            text, _safety = st.write_slots(ser, snapshot, safety_dir=output_dir(), log=print)
        finally:
            ser.close()
        print(text)
        radio, err = None, ""
        try:
            radio = self._read_radio()
        except Exception as e:  # noqa: BLE001 -- запис уже відбувся; збій перечитування не має його «скасувати»
            err = str(e)
        return text, radio, err

    def _update_write_done(self, data):
        text, radio, err = data
        if radio is not None:
            self.apply_read(*radio)
            done = su.done_text(self.slots, self._now())
            messagebox.showinfo("Супутники", done + "\n\n" + text, parent=self.shell)
        else:
            self.mark_written(self.slots)
            messagebox.showinfo("Супутники", text + "\n\nПеречитати слоти не вдалося: %s. Натисни «Прочитати з рації» в «Детально»." % err, parent=self.shell)

    # --- джерело ----------------------------------------------------------------------------------

    def _on_source_changed(self, _e=None):
        for name, url in SOURCES:
            if name == self.src_var.get():
                self.url_var.set(url)

    def _on_probe(self):
        if self.shell.busy:
            return
        url = self.url_var.get().strip()
        self.shell.run_task(lambda: st.probe_text(st.probe_url(url)), "Перевіряю джерело...", plain_errors=True, ok_status="Джерело перевірено.",
                            on_done=lambda t: messagebox.showinfo("Перевірка джерела", t, parent=self.shell))

    def _on_download(self):
        if self.shell.busy:
            return
        url = self.url_var.get().strip()
        path = filedialog.asksaveasfilename(parent=self.shell, title="Куди зберегти файл TLE", defaultextension=".tle", initialdir=output_dir(),
                                            initialfile=cps.timestamp_name("tle", ".txt"), filetypes=[("Файл TLE", "*.tle *.txt"), ("Усі файли", "*.*")])
        if not path:
            return
        self.shell.run_task(lambda: self._download_worker(url, path), "Завантажую елементи орбіт...", plain_errors=True, ok_status="Завантажено.",
                            on_done=lambda p: self.load_file(p))

    def _download_worker(self, url, path):
        n = st.download(url, path)
        print("Завантажено %d Б у %s" % (n, path))
        return path

    def _on_open_file(self):
        path = filedialog.askopenfilename(parent=self.shell, title="Файл TLE", initialdir=output_dir(), filetypes=[("Файл TLE", "*.tle *.txt"), ("Усі файли", "*.*")])
        if path:
            self.load_file(path)

    def load_file(self, path):
        try:
            tles, notes = st.read_tle_file(path)
        except OSError as e:
            messagebox.showerror("Супутники", "Файл не відкрито: %s" % e, parent=self.shell)
            return
        self.set_tles(tles, notes, path)

    def set_tles(self, tles, notes=(), source=""):
        """Прийняти розібрані набори (логіка без вікон)."""
        self.tles = list(tles)
        bad = [t for t in tles if not t.ok]
        text = "Файл %s: наборів елементів %d" % (source or "(текст)", len(tles))
        if bad:
            text += ", з них непридатних %d (причини в таблиці)" % len(bad)
        if notes:
            text += ". " + "; ".join(notes)
        self.src_label.config(text=text + ".")
        self._refilter()

    # --- відбір -----------------------------------------------------------------------------------

    def _refilter(self):
        self.tle_view = st.filter_tles(self.tles, self.search_var.get())
        self.tle_tree.delete(*self.tle_tree.get_children())
        for i, t in enumerate(self.tle_view):
            e = t.epoch
            age = (st.datetime.datetime.now(st.datetime.timezone.utc).replace(tzinfo=None) - e).total_seconds() / 86400.0 if e else None
            note = "; ".join(t.problems + t.warnings)
            self.tle_tree.insert("", "end", iid=str(i), values=(t.name, t.short_name(), t.catalog, e.strftime("%Y-%m-%d") if e else "?",
                                                                 ("%d" % age) if age is not None else "?", note))
        self._update_counts()

    def chosen_tles(self):
        out = []
        for iid in self.tle_tree.selection():
            t = self.tle_view[int(iid)]
            if t.ok:
                out.append(t)
        return out

    def _update_counts(self):
        chosen = len(self.chosen_tles())
        text = st.counts_line(len(self.tle_view), chosen, len(self.slots))
        if self.tles and len(self.tle_view) != len(self.tles):
            text += " (з %d у файлі)" % len(self.tles)
        self.counts_label.config(text=text)

    def add_chosen(self, tles=None, replace=False):
        """Додати вибрані (або передані) набори в слоти. Повертає, скільки не влізло."""
        tles = self.chosen_tles() if tles is None else tles
        self.slots, dropped = stb.merge_add_table(self.slots, tles, stb.by_norad(self.table_rows), replace=replace)
        self._redraw_slots()
        return dropped

    def _on_add(self):
        tles = self.chosen_tles()
        if not tles:
            messagebox.showinfo("Супутники", "Вибери рядки у списку елементів (Ctrl/Shift -- кілька).", parent=self.shell)
            return
        free = st.NUM_SLOTS - len(self.slots)
        if len(tles) > free and not messagebox.askyesno("Супутники", "Вибрано %d, а вільних слотів %d. Буде додано лише перші %d. Продовжити?" % (len(tles), free, max(0, free)),
                                                         parent=self.shell):
            return
        self.add_chosen(tles)

    def _on_replace(self):
        tles = self.chosen_tles()
        if not tles:
            messagebox.showinfo("Супутники", "Вибери рядки у списку елементів.", parent=self.shell)
            return
        if self.slots and not messagebox.askyesno("Супутники", "Усі поточні слоти (%d) буде замінено вибраними (%d), частоти й субтони пропадуть. Продовжити?" % (
                len(self.slots), len(tles)), parent=self.shell):
            return
        self.add_chosen(tles, replace=True)

    def plan_update(self):
        """-> (вибір {індекс слота: Tle}, неоднозначні [(індекс, [Tle...])], не знайдено [індекс])."""
        matches = st.match_updates(self.slots, self.tles)
        chosen, ambiguous = {}, []
        for i, hits in matches:
            if len(hits) == 1:
                chosen[i] = hits[0]
            else:
                ambiguous.append((i, hits))
        missing = [i for i in range(len(self.slots)) if i not in chosen and i not in {a for a, _h in ambiguous}]
        return chosen, ambiguous, missing

    def _on_update_existing(self):
        if not self.slots:
            messagebox.showinfo("Супутники", "У слотах нічого нема -- спершу прочитай рацію або додай супутники.", parent=self.shell)
            return
        if not self.tles:
            messagebox.showinfo("Супутники", "Спершу відкрий файл TLE.", parent=self.shell)
            return
        chosen, ambiguous, missing = self.plan_update()
        lines = ["Збіг за НАЗВОЮ (у слоті немає номера NORAD):", ""]
        for i, t in sorted(chosen.items()):
            lines.append("  слот %d «%s»  <-  %s (епоха %s)" % (i + 1, self.slots[i].name, t.name, t.epoch.strftime("%Y-%m-%d") if t.epoch else "?"))
        for i, hits in ambiguous:
            lines.append("  слот %d «%s»: неоднозначно (%s) -- НЕ оновлюю" % (i + 1, self.slots[i].name, ", ".join(h.name for h in hits)))
        for i in missing:
            lines.append("  слот %d «%s»: у файлі збігу нема -- лишається" % (i + 1, self.slots[i].name))
        lines += ["", "Назва, частоти й субтони лишаються, міняються лише елементи орбіти."]
        if not chosen:
            messagebox.showinfo("Супутники", "\n".join(lines), parent=self.shell)
            return
        if not gd.confirm_dialog(self.shell, "Оновити елементи?", "\n".join(lines), yes="Оновити", no="Скасувати"):
            return
        self.slots = st.apply_updates(self.slots, chosen)
        self._redraw_slots()

    # --- таблиця частот (R54) ---------------------------------------------------------------------

    def user_table_path(self):
        """Своя таблиця: шлях із налаштувань оболонки, а коли його нема -- ~/MD-UV390UKR/satellites.txt (якщо файл є). '' -- нема."""
        from pathlib import Path
        try:
            p = self.shell.settings.get("sat_table")
        except AttributeError:
            p = None
        if p and os.path.isfile(p):
            return p
        near = str(Path.home() / "MD-UV390UKR" / stb.TABLE_FILE)
        return near if os.path.isfile(near) else ""

    def _load_initial_table(self):
        path = self.user_table_path()
        if path:
            self.load_table_file(path, remember=False)
        else:
            self.load_builtin_table()

    def today(self):
        return self.now_override.date() if self.now_override is not None else None

    def _toggle(self, label, text, **pack):
        """Підпис, що займає місце лише коли в ньому є текст (головний вигляд має вміщатись без прокрутки)."""
        label.config(text=text)
        if text and not getattr(label, "_shown", False):
            label.pack(**pack)
            label._shown = True
        elif not text and getattr(label, "_shown", False):
            label.pack_forget()
            label._shown = False

    def set_table(self, rows, notes, source, verified=None, kind=None):
        """kind -- «вбудована» / «файл» для підпису дати; verified -- datetime.date звірки (вбудована) чи зміни файла (своя)."""
        self.table_rows, self.table_notes, self.table_source, self.table_verified = list(rows), list(notes), source, verified
        text = "Таблиця: %s." % (stb.table_date_text(kind, verified, self.today()) if kind else source)
        self.table_count_label.config(text="Рядків у таблиці: %d." % len(rows))
        notes_text = ""
        if notes:
            text += " Пропущено через помилки: %d (подробиці -- «Детально»)." % len(notes)
            notes_text = "Пропущені рядки таблиці:\n  " + "\n  ".join(notes[:8]) + ("\n  ..." if len(notes) > 8 else "")
            for n in notes:
                print("Таблиця частот супутників: " + n)
        self.table_label.config(text=text)
        self._toggle(self.table_notes_label, notes_text, anchor="w", padx=8, before=self._tbl_first)
        self._toggle(self.recheck_label, stb.table_recheck_text(verified, self.today()), anchor="w", before=self._act_row)

    def load_builtin_table(self):
        rows, notes = stb.default_rows()
        self.set_table(rows, notes, "вбудована стартова", verified=stb.builtin_verified_date(), kind="вбудована")

    def load_table_file(self, path, remember=True):
        """Прочитати свою таблицю. False -- файл не прочитано або в ньому нема жодного рядка (поточна таблиця лишається)."""
        try:
            rows, notes = stb.read_table_file(path)
        except OSError as e:
            messagebox.showerror("Супутники", "Файл таблиці не відкрито: %s" % e, parent=self.shell)
            return False
        if not rows:
            messagebox.showerror("Супутники", "У файлі нема жодного придатного рядка таблиці.\n" + "\n".join(notes[:8]), parent=self.shell)
            return False
        self.set_table(rows, notes, "файл " + path, verified=stb.file_date(path), kind="файл " + path)
        if remember:
            try:
                self.shell.settings.set("sat_table", path)
                self.shell.settings.save()
            except AttributeError:
                pass
        return True

    def _on_open_table(self):
        path = filedialog.askopenfilename(parent=self.shell, title="Таблиця частот супутників (satellites.txt)", initialdir=output_dir(),
                                          filetypes=[("Таблиця супутників", "*.txt *.csv"), ("Усі файли", "*.*")])
        if path:
            self.load_table_file(path)

    def _on_builtin_table(self):
        self.load_builtin_table()
        try:
            self.shell.settings.set("sat_table", "")
            self.shell.settings.save()
        except AttributeError:
            pass

    def add_from_table(self):
        """Логіка «Додати з таблиці» без вікон -> AddReport."""
        self.slots, rep = stb.add_from_table(self.slots, self.table_rows, self.tles)
        self._redraw_slots()
        return rep

    def _on_add_table(self):
        if not self.tles:
            messagebox.showinfo("Супутники", "Спершу відкрий або завантаж файл TLE (крок 2): TLE беруться з нього за номером NORAD.", parent=self.shell)
            return
        if not self.table_rows:
            messagebox.showinfo("Супутники", "Таблиця порожня.", parent=self.shell)
            return
        rep = self.add_from_table()
        messagebox.showinfo("Супутники", stb.report_text(rep, len(self.table_rows)), parent=self.shell)

    def fill_from_table(self):
        """Логіка «Заповнити порожні слоти» без вікон -> (заповнено, уручну, без збігу, неоднозначних)."""
        self.slots, filled, manual, nomatch, ambiguous = stb.fill_existing(self.slots, self.table_rows)
        self._redraw_slots()
        return filled, manual, nomatch, ambiguous

    def _on_fill_table(self):
        if not self.slots:
            messagebox.showinfo("Супутники", "У слотах нічого нема -- спершу прочитай рацію або додай супутники.", parent=self.shell)
            return
        filled, manual, nomatch, ambiguous = self.fill_from_table()
        lines = ["Збіг за НАЗВОЮ (у слоті немає номера NORAD).", "Заповнено: %s." % (", ".join(filled) or "нічого")]
        if manual:
            lines.append("Уже мають свої частоти -- не чіпаю: %s." % ", ".join(manual))
        if nomatch:
            lines.append("У таблиці немає такої назви: %s." % ", ".join(nomatch))
        if ambiguous:
            lines.append("Назва зустрічається в таблиці кілька разів -- не чіпаю: %s." % ", ".join(ambiguous))
        messagebox.showinfo("Супутники", "\n".join(lines), parent=self.shell)
