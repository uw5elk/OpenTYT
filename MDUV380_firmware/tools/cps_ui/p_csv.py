# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → CSV» (R26): експорт з рації, експорт з бекапу, імпорт у рацію, вибір десяткового знака. Експорт ЛИШЕ читає;
імпорт іде ТІЄЮ САМОЮ дорогою, що й «Відновити кодплаг» (страхова копія -> діалог зі списком змін -> лише відмінні сектори ->
перечитування -> SHA-256) і блокується тією ж константою. Логіку перенесено з gui_flasher.py без змін."""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_csv
import cps_link as cps
import cps_restore as cps_rest
import gui_theme as gt

from .common import output_dir
from .p_backup import show_restore_result, close_quietly
from .panel import Panel


class CsvPanel(Panel):
    key = "csv"
    title = "CSV"
    CSV_DECIMAL_CHOICES = ("за системою", "кома", "крапка")

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.csv_session = cps_csv.Session()      # R26: «про cp1251 вже попередили» -- один раз за сеанс
        self.header("CSV", "Обмін кодплага з CSV у форматі OpenGD77 CPS. Рація має бути у звичайному режимі (не в DFU).")

        ex = ttk.LabelFrame(self, text="Експорт (лише читання)")
        ex.pack(fill="x", padx=12, pady=6)
        self.csv_export_radio_button = ttk.Button(ex, text="CSV з рації...", command=self._on_csv_export_radio_clicked)
        self.csv_export_radio_button.pack(side="left", padx=8, pady=8)
        self.reg(self.csv_export_radio_button)
        self.csv_export_file_button = ttk.Button(ex, text="CSV з бекапу...", command=self._on_csv_export_file_clicked)
        self.csv_export_file_button.pack(side="left", padx=8, pady=8)
        self.reg(self.csv_export_file_button, radio=False)

        im = ttk.LabelFrame(self, text="Імпорт (ЗАПИС у рацію)")
        im.pack(fill="x", padx=12, pady=6)
        self.csv_import_button = ttk.Button(im, text="Імпорт CSV у рацію...", command=self._on_csv_import_clicked)
        self.csv_import_button.pack(anchor="w", padx=8, pady=(8, 4))
        self.reg(self.csv_import_button, radio=True, write=True)
        self.import_note = ttk.Label(im, text="" if cps_rest.RESTORE_UNLOCKED else cps_rest.LOCKED_CAPTION, foreground=gt.P["warn"],
                                     wraplength=600, justify="left")
        self.import_note.pack(anchor="w", padx=8, pady=(0, 8))

        opt = ttk.LabelFrame(self, text="Формат чисел")
        opt.pack(fill="x", padx=12, pady=6)
        ttk.Label(opt, text="десятковий знак:").pack(side="left", padx=(8, 4), pady=8)
        self.csv_decimal_var = tk.StringVar(value=self.CSV_DECIMAL_CHOICES[0])
        self.csv_decimal_box = ttk.Combobox(opt, textvariable=self.csv_decimal_var, values=self.CSV_DECIMAL_CHOICES, state="readonly", width=14)
        self.csv_decimal_box.pack(side="left", pady=8)

    def after_refresh(self):
        self.import_note.config(text="" if cps_rest.RESTORE_UNLOCKED else cps_rest.LOCKED_CAPTION)

    def _csv_decimal(self):
        return {"кома": ",", "крапка": ".", "за системою": None}.get(self.csv_decimal_var.get())

    def _csv_new_export_dir(self, parent_dir):
        name = cps.timestamp_name("codeplug_csv", "")
        return cps.unique_path(parent_dir, name)

    def _on_csv_export_radio_clicked(self):
        if self.shell.busy:
            return
        parent_dir = filedialog.askdirectory(title="Куди покласти теку з CSV", initialdir=output_dir())
        if not parent_dir:
            return
        out = self._csv_new_export_dir(parent_dir)
        dp = self._csv_decimal()
        self.shell.run_task(lambda: self._csv_export_radio_worker(out, dp), "Читаю кодплаг з рації для CSV...",
                            on_done=self._csv_export_done, fail_suffix="\n\nФайли CSV не створено.")

    def _csv_export_radio_worker(self, out, dp):
        ser = cps.open_radio()
        try:
            return cps_csv.export_from_radio(cps.CpsLink(ser), out, dp, progress=self.shell.cps_progress, log=print)
        finally:
            ser.close()

    def _on_csv_export_file_clicked(self):
        if self.shell.busy:
            return
        path = filedialog.askopenfilename(title="Бекап кодплага", initialdir=output_dir(),
                                          filetypes=[("Бекап кодплага (.zip)", "*.zip"), ("Усі файли", "*.*")])
        if not path:
            return
        parent_dir = filedialog.askdirectory(title="Куди покласти теку з CSV", initialdir=os.path.dirname(path))
        if not parent_dir:
            return
        out = self._csv_new_export_dir(parent_dir)
        dp = self._csv_decimal()
        self.shell.run_task(lambda: cps_csv.export_from_backup(path, out, dp, log=print), "Експортую бекап у CSV...",
                            on_done=self._csv_export_done, fail_suffix="\n\nФайли CSV не створено.")

    def _csv_export_done(self, paths):
        folder = os.path.dirname(paths[0]) if paths else "?"
        messagebox.showinfo("CSV створено", "Шість файлів CSV (формат OpenGD77 CPS + додаткова колонка «Name (readable)»):\n{}".format(folder))

    def _on_csv_import_clicked(self):
        if self.shell.busy or not cps_rest.RESTORE_UNLOCKED:
            return
        folder = filedialog.askdirectory(title="Тека з CSV (Channels.csv, Contacts.csv, ...)", initialdir=output_dir())
        if not folder:
            return
        dp = self._csv_decimal()
        self.shell.run_task(lambda: self._csv_import_worker(folder, dp), "Імпортую CSV у рацію...", on_done=self._csv_import_done,
                            fail_suffix="\n\nЯкщо про відмову сказано «Нічого не записано» -- рація не змінена.", reconnect_ms=6000)

    def _csv_import_worker(self, folder, dp):
        ser = cps.open_radio()
        try:
            return cps_csv.import_to_radio(cps.CpsLink(ser), folder, self.shell.confirm_from_worker, self.shell.cps_progress, log=print,
                                           session=self.csv_session, dp=dp, out_dir=output_dir())
        finally:
            close_quietly(ser)

    def _csv_import_done(self, res):
        if res.get("nothingToDo") and not res.get("safetyCopy"):
            messagebox.showinfo("Нічого імпортувати", "CSV не відрізняється від кодплага рації. Записувати нічого.")
            return
        show_restore_result(res)
