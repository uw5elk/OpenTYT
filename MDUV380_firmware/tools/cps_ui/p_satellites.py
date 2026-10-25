# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → Супутники» (R35 A): елементи орбіт для екрана супутників рації (custom-data блок SATELLITE_TLE, 25 слотів).

Блок НЕ є частиною кодплага (як і теми): він лежить в області custom-data SPI-флеша, тож «Записати в рацію» тут змінює рацію одразу, окремо від документа.
Формат блока, поля й обмеження -- у tools/sat_tle.py (з коду прошивки). Рація читає елементи при вході на екран супутників.

Порядок роботи: 1) «Прочитати з рації» -- що зараз у слотах; 2) джерело: файл TLE з диска або з мережі (Celestrak; мережа -- лише кнопками, адресу спершу перевір
«Перевірити джерело»); 3) відібрати з завантажених і покласти в слоти або оновити елементи супутників, які вже є; 4) «Записати в рацію» -- зі страховою копією блока
й звіркою читанням. Частоти й субтони супутників у файлі TLE немає -- їх задають у формі слота (при оновленні наявних вони зберігаються)."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import gui_dialogs as gd
import gui_theme as gt
import sat_tle as st

from .layout import FitTable
from .common import output_dir
from .panel import Panel

SOURCES = [("Celestrak: аматорські супутники (НЕ ПЕРЕВІРЕНО)", st.CELESTRAK_AMATEUR), ("Інша адреса", "")]


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
        self._build_ui()
        self._redraw_slots()

    # --- побудова ---------------------------------------------------------------------------------

    def _build_ui(self):
        self.header("Супутники", "Елементи орбіт (TLE) для екрана супутників рації: до 25 слотів. Блок лежить в окремій області флеша рації, тому «Записати в рацію» "
                                 "тут змінює рацію одразу, окремо від кодплага. TLE застарівають -- зі старими елементами прогноз прольотів неточний.",
                    purpose="поновити елементи орбіт супутників у рації (прогноз прольотів і доплер).")
        box = ttk.LabelFrame(self, text="1. Що в рації (25 слотів)")
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
        slot_tbl = FitTable(box, [("n", "№", 34, 0), ("name", "Назва", 90, 0), ("epoch", "Епоха", 90, 0), ("age", "Вік, дн.", 70, 0), ("inc", "Нахил, °", 70, 0),
                                  ("period", "Період, хв", 80, 0), ("freq", "Частоти", 240, 1)], height=8)
        self.slot_tree = slot_tbl.tree
        slot_tbl.pack(fill="x", padx=8, pady=4)
        self.slot_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_slot_selected())
        self.stale_label = ttk.Label(box, text="", foreground=gt.P["warn"], wraplength=640, justify="left")
        self.stale_label.pack(anchor="w", padx=8)
        form = ttk.Frame(box)
        form.pack(fill="x", padx=8, pady=(4, 8))
        for col, (label, var, w) in enumerate((("Назва (до 8 лат. символів)", self.name_var, 12), ("RX, МГц", self.rx_var, 12), ("TX, МГц", self.tx_var, 12),
                                               ("Субтон TX, Гц", self.ctcss_var, 8))):
            ttk.Label(form, text=label).grid(row=0, column=col, sticky="w", padx=(0, 6))
            ttk.Entry(form, textvariable=var, width=w).grid(row=1, column=col, sticky="w", padx=(0, 6))
        self.apply_btn = ttk.Button(form, text="Застосувати до слота", command=self._on_apply_form)
        self.apply_btn.grid(row=1, column=4, padx=8)

        src = ttk.LabelFrame(self, text="2. Джерело елементів")
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
                             "обране тобою місце. Адресу Celestrak взято з брифу й у цій збірці НЕ перевірено -- не вважай її робочою, доки не побачив вміст. Нічого не кешується."),
                  wraplength=640, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 2))
        self.src_label = ttk.Label(src, text="Файл не відкрито.", foreground=gt.P["muted"], wraplength=640, justify="left")
        self.src_label.pack(anchor="w", padx=8, pady=(0, 6))

        sel = ttk.LabelFrame(self, text="3. Відбір і слоти")
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
            age = s.age_days()
            self.slot_tree.insert("", "end", iid=str(i), values=(
                i + 1, s.name, st.epoch_text(s), ("%d" % age) if age is not None else "?", ("%.2f" % s.inclination) if s.inclination is not None else "?",
                ("%.1f" % s.period_min) if s.period_min else "?", s.freq_text()))
        if select is not None and 0 <= select < len(self.slots):
            self.slot_tree.selection_set(str(select))
        stale = st.stale_text(self.slots)
        self.stale_label.config(text=stale)
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

    def is_dirty(self):
        try:
            return st.build_block(self.slots) != self.base_bytes
        except st.SatError:
            return True

    def selected_slot(self):
        sel = self.slot_tree.selection()
        return int(sel[0]) if sel else None

    def _on_slot_selected(self):
        i = self.selected_slot()
        if i is None or i >= len(self.slots):
            return
        s = self.slots[i]
        self.name_var.set(s.name)
        self.rx_var.set(_mhz(s.rx1))
        self.tx_var.set(_mhz(s.tx1))
        self.ctcss_var.set(("%g" % (s.ctcss / 10.0)) if s.ctcss else "")

    def apply_form(self, index, name, rx, tx, ctcss):
        """Застосувати значення форми до слота index (логіка без вікон). SatError -- пояснення, слот не змінюється."""
        s = self.slots[index].copy()
        nm = (name or "").strip()
        if not nm:
            raise st.SatError("назва порожня")
        if len(nm) > st.NAME_LEN or any(not (0x20 <= ord(ch) < 0x7F) for ch in nm):
            raise st.SatError("назва має бути до %d символів ASCII (латиниця, цифри, знаки)" % st.NAME_LEN)
        s.name = nm
        s.rx1, s.tx1 = _parse_mhz(rx), _parse_mhz(tx)
        s.ctcss = _parse_ctcss(ctcss)
        self.slots[index] = s
        return s

    def _on_apply_form(self):
        i = self.selected_slot()
        if i is None:
            messagebox.showinfo("Супутники", "Спершу вибери слот у таблиці.", parent=self.shell)
            return
        try:
            self.apply_form(i, self.name_var.get(), self.rx_var.get(), self.tx_var.get(), self.ctcss_var.get())
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
        lines = ["У рацію буде записано супутників: %d з %d." % (len(self.slots), st.NUM_SLOTS), ""]
        lines += ["  %d. %s (епоха %s, %s)" % (i + 1, s.name, st.epoch_text(s), s.freq_text()) for i, s in enumerate(self.slots)]
        stale = st.stale_text(self.slots)
        if stale:
            lines += ["", stale]
        if self.radio_state is None:
            lines += ["", "Рацію ще не читали: невідомо, що в ній зараз. Запис замінить блок супутників повністю."]
        lines += ["", "Це змінює рацію одразу (поза кодплагом). Спершу блок, що зараз у рації, збережеться у файл-страхову копію. Після запису відкрий екран супутників."]
        if not gd.confirm_dialog(self.shell, "Записати супутники в рацію?", "\n".join(lines), yes="Записати", no="Скасувати"):
            return
        snapshot = [s.copy() for s in self.slots]
        self.shell.run_task(lambda: self._write_worker(snapshot), "Записую супутники в рацію...", plain_errors=True, on_done=self._write_done)

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
        self.slots, dropped = st.merge_add(self.slots, tles, replace=replace)
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
