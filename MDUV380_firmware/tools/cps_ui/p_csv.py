# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → CSV» (R26, CPS-doc): експорт ДОКУМЕНТА в шість CSV і імпорт CSV У ДОКУМЕНТ. Формат CSV не змінено.

Імпорт має ту саму сувору перевірку (усі проблеми одним списком ДО будь-якої зміни; при проблемі документ лишається як був). Після
успішного імпорту таблиці перегляду оновлюються одразу, а рація не чіпається: у неї документ пишеться окремою дією «Записати кодплаг у рацію»
(страхова копія -> діалог зі списком змін -> лише відмінні сектори -> перечитування -> SHA-256)."""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_csv
import cps_link as cps
import gui_dialogs as gd
import gui_theme as gt

from .common import output_dir
from .panel import HINT_NO_DOC, Panel


class CsvPanel(Panel):
    key = "csv"
    title = "CSV"
    CSV_DECIMAL_CHOICES = ("за системою", "кома", "крапка")
    doc_panel = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.csv_session = cps_csv.Session()      # R26: «про cp1251 вже попередили» -- один раз за сеанс
        self.header("CSV", "Обмін відкритого кодплага з CSV у форматі OpenGD77 CPS -- для масових правок у таблиці; точкові -- у відповідних розділах. "
                           "Працює з документом (кодплаг відкривається з рації або з бекапу над розділами); рація тут не чіпається.")
        self.hint = ttk.Label(self, text=HINT_NO_DOC, foreground=gt.P["muted"])

        ex = ttk.LabelFrame(self, text="Експорт (лише читання)")
        ex.pack(fill="x", padx=12, pady=6)
        self.csv_export_button = ttk.Button(ex, text="Зберегти документ у CSV...", command=self._on_export_clicked)
        self.csv_export_button.pack(side="left", padx=8, pady=8)
        self.reg(self.csv_export_button, radio=False, doc=True)

        im = ttk.LabelFrame(self, text="Імпорт (у ДОКУМЕНТ, не в рацію)")
        im.pack(fill="x", padx=12, pady=6)
        self.csv_import_button = ttk.Button(im, text="Імпорт CSV у документ...", command=self._on_import_clicked)
        self.csv_import_button.pack(anchor="w", padx=8, pady=(8, 4))
        self.reg(self.csv_import_button, radio=False, doc=True)
        ttk.Label(im, text=("Спершу перевіряється ВЕСЬ CSV: якщо є проблеми, їх буде показано списком, а документ не зміниться. "
                            "У рацію зміни потраплять лише за дією «Записати кодплаг у рацію» над розділами."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 8))

        opt = ttk.LabelFrame(self, text="Формат чисел")
        opt.pack(fill="x", padx=12, pady=6)
        ttk.Label(opt, text="десятковий знак:").pack(side="left", padx=(8, 4), pady=8)
        self.csv_decimal_var = tk.StringVar(value=self.CSV_DECIMAL_CHOICES[0])
        self.csv_decimal_box = ttk.Combobox(opt, textvariable=self.csv_decimal_var, values=self.CSV_DECIMAL_CHOICES, state="readonly", width=14)
        self.csv_decimal_box.pack(side="left", pady=8)
        self.on_document_changed()

    def on_document_changed(self):
        if self.doc is None:
            self.hint.pack(anchor="w", padx=12, pady=(0, 4), after=self._note_box)
        else:
            self.hint.pack_forget()

    def _csv_decimal(self):
        return {"кома": ",", "крапка": ".", "за системою": None}.get(self.csv_decimal_var.get())

    def _on_export_clicked(self):
        d = self.doc
        if d is None or self.shell.busy:
            return
        parent_dir = filedialog.askdirectory(parent=self.shell, title="Куди покласти теку з CSV", initialdir=output_dir())
        if not parent_dir:
            return
        out = cps.unique_path(parent_dir, cps.timestamp_name("codeplug_csv", ""))
        try:
            paths = d.export_csv(out, self._csv_decimal(), log=self.shell.log)
        except (OSError, cps.CpsError) as e:
            messagebox.showerror("Помилка", "Файли CSV не створено:\n{}".format(e), parent=self.shell)
            return
        folder = os.path.dirname(paths[0]) if paths else out
        messagebox.showinfo("CSV створено", "Шість файлів CSV (формат OpenGD77 CPS + додаткова колонка «Name (readable)»):\n{}".format(folder),
                            parent=self.shell)

    def _on_import_clicked(self):
        d = self.doc
        if d is None or self.shell.busy:
            return
        folder = filedialog.askdirectory(parent=self.shell, title="Тека з CSV (Channels.csv, Contacts.csv, ...)", initialdir=output_dir())
        if not folder:
            return
        self.import_folder(folder)

    def import_folder(self, folder):
        """Імпортувати CSV з теки У документ. Повертає ImportResult або None (відмова/нічого)."""
        d = self.doc
        try:
            tables = cps_csv.read_dir(folder)
            if not tables:
                raise cps_csv.CsvError("у теці %s немає жодного з файлів: %s" % (folder, ", ".join(cps_csv.FILE_NAMES.values())))
            res = d.import_csv(tables, self._csv_decimal(), self.csv_session)
        except cps_csv.CsvImportRefused as e:
            self.shell.log("!!! Імпорт CSV відхилено (проблем: {}). Документ не змінено.".format(len(e.problems)))
            gd.text_dialog(self.shell, "Імпорт CSV відхилено", str(e))
            return None
        except (OSError, cps.CpsError) as e:
            messagebox.showerror("Помилка", "Імпорт CSV не вдався. Документ не змінено.\n\n{}".format(e), parent=self.shell)
            return None
        if not res.any_change():
            messagebox.showinfo("Нічого імпортувати", "CSV не відрізняється від відкритого кодплага. Документ не змінено.", parent=self.shell)
            return res
        self.shell.log("Імпорт CSV у документ: {}".format(res.summary()))
        gd.text_dialog(self.shell, "CSV імпортовано в документ",
                       "\n".join(res.report_lines()) + "\n\n" + res.summary() + "\n\nДокумент змінено; рацію НЕ чіпали. "
                       "Щоб записати зміни в рацію, натисни «Записати кодплаг у рацію» над розділами.")
        return res
