#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codeplug_viewer_gui.py -- R25 W2: вікно перегляду кодплуга (контакти, групи RX, зони, канали). ТІЛЬКИ ЧИТАННЯ.

Джерело -- уже розібраний codeplug_view.Codeplug (з бекап-файла або з прямого читання рації: це ті самі байти).
Уся логіка (декодування назв, фільтри сміття) -- у codeplug_view.py; тут лише Tk. Назви показуються як рядки Unicode
(W2.4), колонка «Кодування» каже, як їх прочитано (GBK / cp1251 / ASCII), кнопка зберігає ВИДИМУ таблицю в CSV (UTF-8).
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import codeplug_view as cv

# ширини колонок за назвою (пікселі); решта -- 120
_WIDTHS = {"№": 50, "Назва": 190, "TG / ID": 100, "Тип": 80, "Кодування": 80, "Контактів": 80, "Склад": 420, "Каналів": 70,
           "Канали": 420, "RX, МГц": 100, "TX, МГц": 100, "Режим": 70}


class CodeplugViewerWindow(tk.Toplevel):
    def __init__(self, parent, codeplug, source_text, csv_dir):
        super().__init__(parent)
        self.title("Кодплуг: " + source_text)
        self.geometry("900x520")
        self.minsize(640, 360)
        self.codeplug = codeplug
        self.csv_dir = csv_dir
        self.tables = codeplug.tables()
        self.trees = []

        head = ttk.Label(self, text="%s -- %s. Позивний %s, DMR ID %d. Лише перегляд: у рацію нічого не записується." % (
            source_text, codeplug.manifest.get("createdUtc", "прямо з рації"), codeplug.callsign() or "(порожньо)", codeplug.dmr_id()),
            wraplength=860, justify="left")
        head.pack(fill="x", padx=10, pady=(8, 4))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=4)
        for key, title, cols, rows in self.tables:
            frame = ttk.Frame(self.nb)
            self.nb.add(frame, text="%s (%d)" % (title, len(rows)))
            tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
            for c in cols:
                tree.heading(c, text=c)
                tree.column(c, width=_WIDTHS.get(c, 120), anchor="w", stretch=(c in ("Склад", "Канали")))
            for r in rows:
                tree.insert("", "end", values=r)
            vs = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            hs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
            tree.grid(row=0, column=0, sticky="nsew")
            vs.grid(row=0, column=1, sticky="ns")
            hs.grid(row=1, column=0, sticky="ew")
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            self.trees.append(tree)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Button(bar, text="Зберегти цю таблицю в CSV...", command=self._export_csv).pack(side="left")
        ttk.Button(bar, text="Закрити", command=self.destroy).pack(side="right")

    def current_table(self):
        idx = self.nb.index(self.nb.select())
        return self.tables[idx]

    def _export_csv(self):
        key, title, cols, rows = self.current_table()
        path = filedialog.asksaveasfilename(parent=self, title="Зберегти таблицю «%s»" % title, defaultextension=".csv",
                                            initialdir=self.csv_dir, initialfile="codeplug_%s.csv" % key,
                                            filetypes=[("CSV (UTF-8)", "*.csv")])
        if not path:
            return
        try:
            cv.write_csv(path, cols, rows)
        except OSError as e:
            messagebox.showerror("Помилка", "Не вдалося зберегти файл:\n%s" % e, parent=self)
            return
        messagebox.showinfo("Готово", "Збережено (%d рядків):\n%s" % (len(rows), os.path.abspath(path)), parent=self)
