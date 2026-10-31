# -*- coding: utf-8 -*-
"""Розділ «Налаштування рації → База позивних» (R31): база DMR ID у рацію, щоб на екрані «Останні почуті» замість номера показувався позивний.

Джерело -- файл CSV/JSON (з диска або завантажений з мережі ЛИШЕ за явним натисканням), далі фільтри (регіон за префіксом DMR ID, бездіяльність у днях, ліміт записів),
вибір колонок тексту й довжини запису, лічильники ДО запису, запис в область №1 бази (sector-safe, страхова копія, прогрес, скасування, звірка).
Базу з рації можна зберегти у файл і потім завантажити з файла (щоб не тягнути з мережі повторно). Логіка -- у tools/dmr_db.py; тут лише вікно.
Область №2 (на ній таблиця ключів AES) і голосові підказки не чіпаються ніколи."""
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import dmr_db as db
import gui_theme as gt

from .layout import FitTable, combo_width
from .common import output_dir
from .panel import Panel

# R50: типове джерело -- Radioid user.csv (адреса й колонки перевірено 2026-10-31). Усе змінюється в панелі й запам'ятовується між запусками.
SOURCES = [("Radioid.net user.csv (перевірено 2026-10-31)", db.RADIOID_CSV_URL),
           ("ContactLists GD77, увесь світ (формат перевірено)", db.CONTACTLISTS_URL),
           ("Radioid.net users.json (НЕ ПЕРЕВІРЕНО)", db.RADIOID_JSON_URL),
           ("Інша адреса", "")]
BATCH = 400                    # скільки рядків таблиці вставляємо за один крок (вікно не підвисає: між кроками обробляються події)
SEARCH_DELAY_MS = 250


class DmrDbPanel(Panel):
    key = "dmrdb"
    title = "База позивних"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.source = None              # dmr_db.Source із файла
        self.job = None                 # dmr_db.Job після «Порахувати»
        self.image = None               # готовий образ з файла бази (має перевагу над відбором)
        self.image_name = ""
        self.cancel_event = threading.Event()
        st = getattr(shell, "settings", None)
        url0 = (st.get("dmrdb_url") if st is not None else None) or SOURCES[0][1]
        label0 = next((n for n, u in SOURCES if u == url0 and u), SOURCES[-1][0])
        self.src_var = tk.StringVar(value=label0)
        self.url_var = tk.StringVar(value=url0)
        self.prefix_var = tk.StringVar(value=self._saved(st, "dmrdb_prefix", ",".join(db.DEFAULT_PREFIXES)))
        self.country_var = tk.StringVar(value=self._saved(st, "dmrdb_countries", ",".join(db.DEFAULT_COUNTRIES)))
        self.days_var = tk.StringVar(value="")
        self.limit_var = tk.StringVar(value="")
        self.chars_var = tk.StringVar(value=str(db.DEFAULT_TEXT_CHARS))
        self.cols_var = tk.StringVar(value=",".join(db.DEFAULT_COLUMNS))
        self._build_ui()

    @staticmethod
    def _saved(st, key, default):
        v = st.get(key) if st is not None else None
        return default if v is None else str(v)

    def _remember(self):
        """Запам'ятати джерело й відбір (settings.py); помилки запису не заважають."""
        st = getattr(self.shell, "settings", None)
        if st is None:
            return
        st.set("dmrdb_url", self.url_var.get().strip())
        st.set("dmrdb_prefix", self.prefix_var.get().strip())
        st.set("dmrdb_countries", self.country_var.get().strip())
        try:
            st.save()
        except Exception:  # noqa: BLE001
            pass

    def _build_ui(self):
        self.header("База позивних DMR ID", "Щоб на екрані «Останні почуті» замість номера з'являвся позивний. База лежить в області №1 флеша рації (0x50000..0x8FFFF); "
                                            "область №2, де зберігаються ключі AES, і голосові підказки цей розділ не чіпає.")
        src = ttk.LabelFrame(self, text="1. Джерело")
        src.pack(fill="x", padx=12, pady=6)
        row = ttk.Frame(src)
        row.pack(fill="x", padx=8, pady=(6, 2))
        self.src_box = ttk.Combobox(row, textvariable=self.src_var, values=[s[0] for s in SOURCES], state="readonly", width=42)
        combo_width(self.src_box, minimum=42)
        self.src_box.pack(side="left")
        self.src_box.bind("<<ComboboxSelected>>", self._on_source_changed)
        ttk.Entry(row, textvariable=self.url_var, width=60).pack(side="left", padx=8, fill="x", expand=True)
        row2 = ttk.Frame(src)
        row2.pack(fill="x", padx=8, pady=(2, 6))
        self.probe_btn = ttk.Button(row2, text="Перевірити джерело", command=self._on_probe)
        self.probe_btn.pack(side="left")
        self.reg(self.probe_btn, radio=False)
        self.net_btn = ttk.Button(row2, text="Завантажити з мережі у файл...", command=self._on_download)
        self.net_btn.pack(side="left", padx=8)
        self.reg(self.net_btn, radio=False)
        self.open_btn = ttk.Button(row2, text="Відкрити файл…", command=self._on_open_source)
        self.open_btn.pack(side="left", padx=8)
        self.reg(self.open_btn, radio=False)
        ttk.Label(src, text=("Джерело вже задано (Radioid user.csv). Мережа вмикається лише кнопками «Перевірити джерело» (запитує перші ~2 КБ і показує, що прийшло) та «Завантажити з мережі у файл» "
                             "(весь файл у обране тобою місце); у репозиторії нічого не кешується. «Відкрити файл…» розпізнає сам: CSV чи JSON (з них збирається база -- далі відбір) або "
                             "готовий образ .bin / повний знімок .zip (він іде в рацію як є, відбір не діє). Мережі нема -- відкрий файл, завантажений вручну. Файли на весь світ "
                             "обов'язково звужуй: регіоном (початок DMR ID) і/або країною. "
                             "HamDigital: прямої адреси у відкритому доступі нема -- потрібен власний обліковий запис на amateurradio.digital; завантаж файл звідти вручну й відкрий його."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 2))
        self.src_label = ttk.Label(src, text="Файл не відкрито.", foreground=gt.P["muted"], wraplength=600, justify="left")
        self.src_label.pack(anchor="w", padx=8, pady=(0, 6))

        flt = ttk.LabelFrame(self, text="2. Відбір і вигляд запису")
        flt.pack(fill="x", padx=12, pady=6)
        grid = ttk.Frame(flt)
        grid.pack(fill="x", padx=8, pady=6)
        fields = [("Регіон -- початок DMR ID (через кому; порожньо = без цього фільтра)", self.prefix_var, 14),
                  ("Країна -- колонка COUNTRY (через кому; порожньо = без цього фільтра; з регіоном діє як «або»)", self.country_var, 24),
                  ("Не активні довше, ніж (днів; порожньо = не фільтрувати)", self.days_var, 8),
                  ("Не більше записів (порожньо = без ліміту)", self.limit_var, 8),
                  ("Колонки тексту і їх порядок (%s)" % ", ".join(db.COLUMN_NAMES), self.cols_var, 28)]
        for r, (label, var, w) in enumerate(fields):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(grid, textvariable=var, width=w).grid(row=r, column=1, sticky="w", padx=8, pady=2)
        ttk.Label(grid, text="Довжина тексту (символів; запис %s Б)" % "15 / 18 / 21").grid(row=len(fields), column=0, sticky="w", pady=2)
        ttk.Combobox(grid, textvariable=self.chars_var, values=[str(c) for c in db.TEXT_CHARS_CHOICES], state="readonly", width=6).grid(
            row=len(fields), column=1, sticky="w", padx=8, pady=2)
        self.count_btn = ttk.Button(flt, text="Порахувати", command=self._on_count)
        self.count_btn.pack(anchor="w", padx=8, pady=(0, 4))
        self.reg(self.count_btn, radio=False)
        self.summary = ttk.Label(flt, text="", wraplength=600, justify="left")
        self.summary.pack(anchor="w", padx=8, pady=(0, 6))

        tbl = ttk.LabelFrame(self, text="Список, що піде в рацію (усі записи)")
        tbl.pack(fill="both", expand=True, padx=12, pady=6)
        self.counts_label = ttk.Label(tbl, text="Тисни «Порахувати» -- тут з'явиться повний список.", wraplength=600, justify="left")
        self.counts_label.pack(anchor="w", padx=8, pady=(6, 2))
        srow = ttk.Frame(tbl)
        srow.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(srow, text="Пошук (ID або позивний):").pack(side="left")
        self.search_var = tk.StringVar(value="")
        self.search_entry = ttk.Entry(srow, textvariable=self.search_var, width=24)
        self.search_entry.pack(side="left", padx=8)
        self.search_var.trace_add("write", self._on_search_changed)
        self.shown_label = ttk.Label(srow, text="", foreground=gt.P["muted"])
        self.shown_label.pack(side="left", padx=8)
        body = ttk.Frame(tbl)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tbl = FitTable(body, [("id", "DMR ID", 90, 0), ("call", "Позивний", 120, 0), ("text", "Текст у записі (що покаже рація)", 360, 1)], height=12)
        self.tree = tbl.tree
        for col, title, _w, _wt in tbl.tree.fit_spec:
            self.tree.heading(col, text=title, command=lambda c=col: self._sort_by(c))
        tbl.pack(fill="both", expand=True)
        self.table_all = []             # [(id, позивний, текст)] -- усе, що піде в рацію
        self.table_view = []            # відфільтроване й відсортоване
        self.table_sort = ("id", False)
        self.table_gen = 0              # номер поточного наповнення (старі кроки after() самі припиняються)
        self.table_filling = False
        self.table_after = None
        self.search_after = None

        rad = ttk.LabelFrame(self, text="3. Рація")
        rad.pack(fill="x", padx=12, pady=6)
        bar = ttk.Frame(rad)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        self.write_btn = ttk.Button(bar, text="Записати базу позивних в рацію...", command=self._on_write)
        self.write_btn.pack(side="left")
        self.reg(self.write_btn, radio=True, write=True)
        self.cancel_btn = ttk.Button(bar, text="Скасувати запис", command=self._on_cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)
        self.what_btn = ttk.Button(bar, text="Що зараз у рації", command=self._on_what)
        self.what_btn.pack(side="left", padx=8)
        self.reg(self.what_btn)
        bar2 = ttk.Frame(rad)
        bar2.pack(fill="x", padx=8, pady=(2, 2))
        self.save_btn = ttk.Button(bar2, text="Зберегти базу з рації у файл...", command=self._on_save_db)
        self.save_btn.pack(side="left")
        self.reg(self.save_btn)
        self.what_label = ttk.Label(rad, text="", wraplength=600, justify="left")
        self.what_label.pack(anchor="w", padx=8, pady=(2, 2))
        ttk.Label(rad, text=("Запис займає хвилини: база в 17 тисяч записів -- це десятки 4-КіБ секторів, кожен пишеться окремо. Спершу обнуляється заголовок бази, заголовок пишеться останнім, тож "
                             "обірваний запис дає «бази нема», а не базу зі сміттям. Перед записом стара область зберігається у файл поруч із іншими файлами CPS. Після запису рація перезавантажується."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 6))

    # --- джерело ---------------------------------------------------------------------------------

    def _on_source_changed(self, _e=None):
        for name, url in SOURCES:
            if name == self.src_var.get():
                self.url_var.set(url)

    def _on_download(self):
        if self.shell.busy:
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showinfo("База позивних", "Вкажи адресу файла бази в полі поряд з вибором джерела.", parent=self.shell)
            return
        if not messagebox.askyesno("Завантажити з мережі", "Буде завантажено файл:\n%s\n\nРозмір і час побачиш у журналі під час завантаження. Продовжити?" % url, parent=self.shell):
            return
        self._remember()
        name = os.path.basename(url.split("?")[0]) or "dmr_users.csv"
        dest = filedialog.asksaveasfilename(parent=self.shell, title="Куди зберегти завантажений файл", initialdir=output_dir(), initialfile=name)
        if not dest:
            return
        self.shell.run_task(lambda: self._download_worker(url, dest), "Завантажую базу з мережі...", plain_errors=True, on_done=self._source_loaded, ok_status="Файл завантажено.")

    def _download_worker(self, url, dest):
        got, secs = db.download(url, dest, self.shell.cps_progress, log=print)
        print("Завантажено %.1f МБ за %.0f с: %s" % (got / 1048576.0, secs, dest))
        return db.read_source_file(dest), "%s (завантажено %.1f МБ за %.0f с)" % (dest, got / 1048576.0, secs)

    def _on_open_source(self):
        """R50: одне «Відкрити файл…». CSV/JSON -> джерело для складання бази (далі відбір); .bin / повний знімок .zip -> готовий образ (відбір не діє)."""
        if self.shell.busy:
            return
        path = filedialog.askopenfilename(parent=self.shell, title="Файл бази позивних (CSV, JSON, образ .bin або знімок .zip)", initialdir=output_dir(),
                                          filetypes=[("База позивних: CSV, JSON, .bin, .zip", "*.csv *.json *.txt *.bin *.zip"), ("Усі файли", "*.*")])
        if not path:
            return
        try:
            kind = db.detect_file_kind(path)
        except OSError as e:
            messagebox.showerror("База позивних", "Файл не прочитано: %s" % e, parent=self.shell)
            return
        if kind == "image":
            try:
                self.load_db_path(path)
            except db.DbError as e:
                messagebox.showerror("База позивних", "Файл не підійшов: %s" % e, parent=self.shell)
            return
        self.shell.run_task(lambda: (db.read_source_file(path), path), "Читаю файл бази...", plain_errors=True, on_done=self._source_loaded, ok_status="Файл прочитано.")

    _on_load_db = _on_open_source      # стара назва (раніше була друга кнопка для готового образу)

    def _source_loaded(self, res):
        self.source, label = res
        self.image = None
        self.job = None
        s = self.source
        self.src_label.config(text="Файл: %s -- рядків з ID: %d%s%s." % (label, len(s.rows), (", пропущено нерозпізнаних: %d" % s.skipped) if s.skipped else "",
                                                                         ", є колонка дати активності" if s.has_date else ", колонки дати активності нема")
                              + ("\nРозпізнано: %s." % s.describe() if s.columns else "")
                              + ("\n" + "; ".join(s.notes) + "." if s.notes else ""))
        cap = db.capacity(db.rec_len_for(int(self.chars_var.get())))
        self.summary.config(text="У файлі %d записів; в область №1 вміщується %d (запис %d Б). %s" % (
            len(s.rows), cap, db.rec_len_for(int(self.chars_var.get())),
            "Тисни «Порахувати» -- побачиш, скільки лишиться після фільтрів і що саме запишеться." if len(s.rows) <= cap else
            "Файл БІЛЬШИЙ за місткість -- обов'язково задай регіон (початок DMR ID) або ліміт і тисни «Порахувати»."))
        self._clear_table("Тисни «Порахувати» -- тут з'явиться повний список.")

    # --- перевірка джерела (P2.2) ----------------------------------------------------------------

    def _on_probe(self):
        if self.shell.busy:
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showinfo("База позивних", "Вкажи адресу в полі поряд з вибором джерела.", parent=self.shell)
            return
        self.shell.run_task(lambda: db.probe_url(url), "Перевіряю джерело (перші ~2 КБ)...", plain_errors=True,
                            on_done=lambda res: self._probe_done(url, res), ok_status="Джерело перевірено.")

    def _probe_done(self, url, res):
        text = "Джерело: %s\n%s" % (url, db.probe_text(res))
        self.src_label.config(text=text)
        print(text)

    # --- відбір ----------------------------------------------------------------------------------

    def _int_or_none(self, var, what):
        t = var.get().strip()
        if not t:
            return None
        if not t.isdigit():
            raise db.DbError("%s: потрібне ціле число, а не «%s»" % (what, t))
        return int(t)

    def make_job(self):
        if self.source is None:
            raise db.DbError("спершу відкрий або завантаж файл бази")
        return db.Job(self.source, db.parse_prefixes(self.prefix_var.get()), self._int_or_none(self.days_var, "дні бездіяльності"),
                      self._int_or_none(self.limit_var, "ліміт записів"), db.parse_columns(self.cols_var.get()), int(self.chars_var.get()),
                      countries=db.parse_countries(self.country_var.get()))

    def _on_count(self):
        try:
            job = self.make_job()
        except db.DbError as e:
            messagebox.showerror("База позивних", str(e), parent=self.shell)
            return
        self.job = job
        self.image = None
        self._remember()
        self.summary.config(text=job.summary())
        self.show_table(job.table_rows(), job.counts_line() + ("\n" + job.dropped_text() if job.dropped else ""))

    # --- таблиця всіх записів (P4) ---------------------------------------------------------------

    def _clear_table(self, text):
        self.table_gen += 1
        self.table_filling = False
        self.table_all, self.table_view = [], []
        self.tree.delete(*self.tree.get_children())
        self.counts_label.config(text=text)
        self.shown_label.config(text="")

    def show_table(self, rows, counts_text):
        """Показати ВСІ записи, що підуть у рацію. rows -- [(ID, позивний, текст)]. Наповнення порціями (BATCH рядків за крок), вікно не підвисає."""
        self.table_all = list(rows)
        self.counts_label.config(text=counts_text)
        self._refilter()

    def _query(self):
        return self.search_var.get().strip()

    def _refilter(self):
        q = self._query().upper()
        rows = self.table_all
        if q:
            rows = [r for r in rows if q in str(r[0]) or q in r[1].upper()]
        col, rev = self.table_sort
        idx = {"id": 0, "call": 1, "text": 2}[col]
        if col == "id":
            rows = sorted(rows, key=lambda r: r[0], reverse=rev)
        else:
            rows = sorted(rows, key=lambda r: (r[idx].upper(), r[0]), reverse=rev)
        self.table_view = rows
        self._fill_tree()

    def _fill_tree(self):
        self.table_gen += 1
        gen = self.table_gen
        if self.table_after is not None:
            try:
                self.after_cancel(self.table_after)
            except Exception:  # noqa: BLE001
                pass
            self.table_after = None
        self.tree.delete(*self.tree.get_children())
        self.table_filling = True
        self._fill_step(gen, 0)

    def _fill_step(self, gen, pos):
        if gen != self.table_gen:                  # почалось нове наповнення -- це старе припиняємо
            return
        chunk = self.table_view[pos:pos + BATCH]
        for r in chunk:
            self.tree.insert("", "end", values=r)
        pos += len(chunk)
        total, allrows = len(self.table_view), len(self.table_all)
        self.shown_label.config(text="показано %d з %d" % (pos, total) + (" (відібрано пошуком з %d)" % allrows if total != allrows else ""))
        if pos < total:
            self.table_after = self.after(1, lambda: self._fill_step(gen, pos))
        else:
            self.table_filling = False
            self.table_after = None

    def _on_search_changed(self, *_a):
        if self.search_after is not None:
            try:
                self.after_cancel(self.search_after)
            except Exception:  # noqa: BLE001
                pass
        self.search_after = self.after(SEARCH_DELAY_MS, self._do_search)

    def _do_search(self):
        self.search_after = None
        self._refilter()

    def _sort_by(self, col):
        cur, rev = self.table_sort
        self.table_sort = (col, (not rev) if cur == col else False)
        names = {"id": "DMR ID", "call": "Позивний", "text": "Текст у записі (що покаже рація)"}
        for c, t in names.items():
            self.tree.heading(c, text=t + ((" \u25bc" if self.table_sort[1] else " \u25b2") if c == col else ""))
        self._refilter()

    # --- запис -----------------------------------------------------------------------------------

    def _image_to_write(self):
        if self.image is not None:
            return self.image
        if self.job is None:
            self.job = self.make_job()
        if self.job.dropped:
            # P4.3: більше, ніж вміщується -- пишемо перші за ID, і користувач має це підтвердити словами
            if not messagebox.askyesno("База позивних", "Усі відібрані записи в область №1 не вміщуються.\n\n%s\n%s\n\nЗаписати вміщуване?" % (
                    self.job.counts_line(), self.job.dropped_text()), parent=self.shell):
                raise db.DbError("запис скасовано: набір більший за місткість")
        return self.job.image(truncate=True)

    def _on_write(self):
        if self.shell.busy:
            return
        try:
            image = self._image_to_write()
        except db.DbError as e:
            messagebox.showerror("База позивних", str(e), parent=self.shell)
            return
        self.cancel_event.clear()
        self.cancel_btn.config(state="normal")
        self.shell.run_task(lambda: self._write_worker(image), "Записую базу в рацію...", plain_errors=True, on_done=self._write_done,
                            fail_suffix="\n\nСтан бази описано в журналі.", reconnect_ms=8000)

    def _write_worker(self, image):
        ser = cps.open_radio()
        try:
            return db.write_db(cps.CpsLink(ser), image, self.shell.confirm_from_worker, progress=self.shell.cps_progress, log=print, safety_dir=output_dir(),
                               cancel=self.cancel_event.is_set)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def _write_done(self, res):
        self.cancel_btn.config(state="disabled")
        bad = res.get("failed") or (res.get("written") and res.get("verified") is False)
        (messagebox.showerror if bad else messagebox.showinfo)("База позивних", res["text"], parent=self.shell)

    def _on_cancel(self):
        self.cancel_event.set()
        self.shell.set_status("Скасування: зупинюсь на межі поточного сектора...", "warn")

    # --- що в рації / файл бази ------------------------------------------------------------------

    def _on_what(self):
        if self.shell.busy:
            return
        self.shell.run_task(self._what_worker, "Читаю заголовок бази з рації...", plain_errors=True, on_done=self._what_done, ok_status="Прочитано.")

    def _what_worker(self):
        ser = cps.open_radio()
        try:
            return db.read_radio_header(cps.CpsLink(ser))
        finally:
            ser.close()

    def _what_done(self, img):
        if not img.rec_len:
            self.what_label.config(text="У рації бази позивних нема (або заголовок пошкоджено): %s" % "; ".join(img.problems))
            return
        lines = ["У рації: база формату %s, записів %d по %d Б%s." % (img.mode, img.count, img.rec_len, "" if img.in_area1 else " -- НЕ вміщується в область №1")]
        lines += img.warnings
        self.what_label.config(text="\n".join(lines))

    def _on_save_db(self):
        if self.shell.busy:
            return
        path = filedialog.asksaveasfilename(parent=self.shell, title="Зберегти базу з рації у файл", defaultextension=".bin", initialdir=output_dir(),
                                            initialfile=cps.timestamp_name("dmr_database", ".bin"), filetypes=[("Образ бази (*.bin)", "*.bin"), ("Усі файли", "*.*")])
        if not path:
            return
        self.shell.run_task(lambda: self._save_worker(path), "Читаю базу з рації...", plain_errors=True,
                            on_done=lambda r: messagebox.showinfo("База позивних", r, parent=self.shell), ok_status="Базу збережено.")

    def _save_worker(self, path):
        ser = cps.open_radio()
        try:
            data = db.read_radio_db(cps.CpsLink(ser), self.shell.cps_progress)
        finally:
            ser.close()
        db.save_db_file(path, data)
        img = db.parse_image(data, want_records=False)
        extra = "" if img.in_area1 else "\nУВАГА: база довша за область №1 -- у файл потрапила лише частина з області №1."
        return "Збережено %d записів (%d Б): %s%s" % (min(img.count, db.capacity(img.rec_len)), len(data), path, extra)

    def load_db_path(self, path):
        """Завантажити готовий образ з файла; відбір (крок 2) тоді не застосовується. DbError -- пояснення, поточний стан не змінюється."""
        data = db.load_db_file(path)
        img = db.parse_image(data, want_records=True)
        bad = db.validate_for_write(img)
        self.image, self.image_name = data, os.path.basename(path)
        self.job = None
        text = "Готовий образ: %s -- %d записів по %d Б (формат %s)." % (self.image_name, img.count, img.rec_len, img.mode)
        if bad:
            text += "\nЗаписати в рацію не можна: " + "; ".join(bad)
        text += "".join("\n" + w for w in img.warnings)
        self.summary.config(text=text)
        self.show_table([(rid, "", t) for rid, t in img.records], "У образі з файла %s: записів %d (позивний окремо не зберігається -- лише текст запису)." % (self.image_name, img.count))
