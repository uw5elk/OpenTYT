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

from .common import output_dir
from .panel import Panel

SOURCES = [("Radioid.net (users.json)", db.RADIOID_JSON_URL), ("Radioid.net (user.csv, адресу не перевірено)", db.RADIOID_CSV_URL),
           ("HamDigital (адресу вкажи сам)", ""), ("Інша адреса", "")]


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
        self.src_var = tk.StringVar(value=SOURCES[0][0])
        self.url_var = tk.StringVar(value=SOURCES[0][1])
        self.prefix_var = tk.StringVar(value="255")
        self.days_var = tk.StringVar(value="")
        self.limit_var = tk.StringVar(value="")
        self.chars_var = tk.StringVar(value=str(db.DEFAULT_TEXT_CHARS))
        self.cols_var = tk.StringVar(value=",".join(db.DEFAULT_COLUMNS))
        self._build_ui()

    def _build_ui(self):
        self.header("База позивних DMR ID", "Щоб на екрані «Останні почуті» замість номера з'являвся позивний. База лежить в області №1 флеша рації (0x50000..0x8FFFF); "
                                            "область №2, де зберігаються ключі AES, і голосові підказки цей розділ не чіпає.")
        src = ttk.LabelFrame(self, text="1. Джерело")
        src.pack(fill="x", padx=12, pady=6)
        row = ttk.Frame(src)
        row.pack(fill="x", padx=8, pady=(6, 2))
        self.src_box = ttk.Combobox(row, textvariable=self.src_var, values=[s[0] for s in SOURCES], state="readonly", width=42)
        self.src_box.pack(side="left")
        self.src_box.bind("<<ComboboxSelected>>", self._on_source_changed)
        ttk.Entry(row, textvariable=self.url_var, width=60).pack(side="left", padx=8, fill="x", expand=True)
        row2 = ttk.Frame(src)
        row2.pack(fill="x", padx=8, pady=(2, 6))
        self.net_btn = ttk.Button(row2, text="Завантажити з мережі у файл...", command=self._on_download)
        self.net_btn.pack(side="left")
        self.reg(self.net_btn, radio=False)
        self.open_btn = ttk.Button(row2, text="Відкрити файл з диска (CSV, JSON)...", command=self._on_open_source)
        self.open_btn.pack(side="left", padx=8)
        self.reg(self.open_btn, radio=False)
        ttk.Label(src, text="Мережа вмикається лише цією кнопкою; завантажене лягає у файл, який ти обереш, у репозиторії нічого не кешується. Мережі нема -- відкрий файл, завантажений вручну.",
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 2))
        self.src_label = ttk.Label(src, text="Файл не відкрито.", foreground=gt.P["muted"], wraplength=600, justify="left")
        self.src_label.pack(anchor="w", padx=8, pady=(0, 6))

        flt = ttk.LabelFrame(self, text="2. Відбір і вигляд запису")
        flt.pack(fill="x", padx=12, pady=6)
        grid = ttk.Frame(flt)
        grid.pack(fill="x", padx=8, pady=6)
        fields = [("Регіон -- початок DMR ID (через кому; порожньо = усі)", self.prefix_var, 14),
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

        rad = ttk.LabelFrame(self, text="3. Рація")
        rad.pack(fill="x", padx=12, pady=6)
        bar = ttk.Frame(rad)
        bar.pack(fill="x", padx=8, pady=(6, 2))
        self.write_btn = ttk.Button(bar, text="Записати базу в рацію...", command=self._on_write)
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
        self.load_btn = ttk.Button(bar2, text="Завантажити базу з файлу (.bin або повний знімок .zip)...", command=self._on_load_db)
        self.load_btn.pack(side="left", padx=8)
        self.reg(self.load_btn, radio=False)
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
        if self.shell.busy:
            return
        path = filedialog.askopenfilename(parent=self.shell, title="Файл бази позивних", initialdir=output_dir(),
                                          filetypes=[("CSV або JSON", "*.csv *.json *.txt"), ("Усі файли", "*.*")])
        if not path:
            return
        self.shell.run_task(lambda: (db.read_source_file(path), path), "Читаю файл бази...", plain_errors=True, on_done=self._source_loaded, ok_status="Файл прочитано.")

    def _source_loaded(self, res):
        self.source, label = res
        self.image = None
        self.job = None
        s = self.source
        self.src_label.config(text="Файл: %s -- рядків з ID: %d%s%s." % (label, len(s.rows), (", пропущено нерозпізнаних: %d" % s.skipped) if s.skipped else "",
                                                                         ", є колонка дати активності" if s.has_date else ", колонки дати активності нема"))
        self.summary.config(text="Тисни «Порахувати», щоб побачити, скільки записів вийде.")

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
                      self._int_or_none(self.limit_var, "ліміт записів"), db.parse_columns(self.cols_var.get()), int(self.chars_var.get()))

    def _on_count(self):
        try:
            job = self.make_job()
        except db.DbError as e:
            messagebox.showerror("База позивних", str(e), parent=self.shell)
            return
        self.job = job
        self.image = None
        text = job.summary()
        pv = job.preview()
        if pv:
            text += "\nНа екрані рації виглядатиме так (перші записи):\n  " + "\n  ".join(pv)
        self.summary.config(text=text)

    # --- запис -----------------------------------------------------------------------------------

    def _image_to_write(self):
        if self.image is not None:
            return self.image
        if self.job is None:
            self.job = self.make_job()
        return self.job.image()

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

    def _on_load_db(self):
        if self.shell.busy:
            return
        path = filedialog.askopenfilename(parent=self.shell, title="Файл бази (образ або повний знімок)", initialdir=output_dir(),
                                          filetypes=[("Образ бази або повний знімок", "*.bin *.zip"), ("Усі файли", "*.*")])
        if not path:
            return
        try:
            self.load_db_path(path)
        except db.DbError as e:
            messagebox.showerror("База позивних", "Файл не підійшов: %s" % e, parent=self.shell)

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
