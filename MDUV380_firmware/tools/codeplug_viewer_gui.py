#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codeplug_viewer_gui.py -- перегляд кодплага (контакти, групи RX, зони, канали, APRS, DTMF) і редактор вкладки «Контакти».

CPS-doc (етап 2): джерело даних -- ДОКУМЕНТ (cps_ui.document.Document), а не знімок рації. Це ttk.Frame, що вбудовується в праву область
(панель «Перегляд кодплага»). Правки контактів одразу лягають у документ; у рацію вікно нічого не пише. Стару назву CodeplugViewerWindow
лишено псевдонімом. Діалоги (ContactDialog, підтвердження) прив'язуються до верхнього вікна.

Уся логіка (декодування назв, фільтри сміття) -- у codeplug_view.py та contact_edit.py; тут лише Tk. Назви показуються як рядки Unicode
(W2.4), колонка «Кодування» каже, як їх прочитано (GBK / cp1251 / ASCII), кнопка зберігає ВИДИМУ таблицю в CSV (UTF-8).
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import codeplug_view as cv
import gui_theme as gt
import gui_dialogs as gd
import contact_edit as ce
import cps_csv as cc
import table_edit as te

# ширини колонок за назвою (пікселі); решта -- 120
_WIDTHS = {"№": 50, "Назва": 190, "TG / ID": 100, "Тип": 80, "Кодування": 80, "Контактів": 80, "Склад": 420, "Каналів": 70,
           "Канали": 420, "RX, МГц": 100, "TX, МГц": 100, "Режим": 70}


class CodeplugViewer(ttk.Frame):
    """Таблиці ДОКУМЕНТА (cps_ui.document.Document): контакти, групи RX, зони, канали, APRS, DTMF. Єдине джерело даних -- документ;
    вкладка «Контакти» редагується, і кожна правка одразу лягає в документ (а не в чергу): у рацію нічого не пишеться, поки
    користувач не вибере «Записати в рацію» у панелі документа. Зміни документа (імпорт CSV, відкидання тощо) вікно підхоплює через
    refresh()."""

    def __init__(self, parent, document, csv_dir, is_busy=None):
        """is_busy() -- чи йде операція з рацією (тоді кнопки правки вимкнено, щоб не міняти документ, який зараз записується)."""
        super().__init__(parent)
        self.document = document
        self.csv_dir = csv_dir
        self.is_busy = is_busy or (lambda: False)
        self.trees = {}
        self.frames = {}
        self.contact_tree = None
        self._item_ref = {}
        self.tables = document.tables()

        self.head = ttk.Label(self, text="", wraplength=760, justify="left")
        self.head.pack(fill="x", padx=10, pady=(8, 4))
        self.head.bind("<Configure>", lambda e: self.head.config(wraplength=max(320, e.width - 8)))       # перенос за шириною панелі

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=4)
        for key, title, cols, rows in self.tables:
            frame = ttk.Frame(self.nb)
            self.nb.add(frame, text="%s (%d)" % (title, len(rows)))
            tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
            for c in cols:
                tree.heading(c, text=c)
                tree.column(c, width=_WIDTHS.get(c, 120), anchor="w", stretch=(c in ("Склад", "Канали")))
            vs = gt.AutoScrollbar(frame, orient="vertical", command=tree.yview)
            hs = gt.AutoScrollbar(frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
            tree.grid(row=0, column=0, sticky="nsew")
            vs.grid(row=0, column=1, sticky="ns")
            hs.grid(row=1, column=0, sticky="ew")
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            self.trees[key] = tree
            self.frames[key] = frame
            if key == "contacts":
                self.contact_tree = tree
                self._build_contact_editor(frame, tree)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 8))
        ttk.Button(bar, text="Зберегти цю таблицю в CSV...", command=self._export_csv).pack(side="left")
        self.refresh()

    # --- вміст ---

    def refresh(self):
        """Перечитати всі таблиці з документа (після правки, імпорту CSV, відкидання змін)."""
        self.tables = self.document.tables()
        for key, title, _cols, rows in self.tables:
            tree = self.trees.get(key)
            if tree is None:
                continue
            tree.delete(*tree.get_children())
            self.nb.tab(self.frames[key], text="%s (%d)" % (title, len(rows)))
            if key == "contacts":
                self._item_ref = {}
                for r in rows:
                    item = tree.insert("", "end", values=r)
                    self._item_ref[item] = int(r[0]) - 1               # слот контакту (номер - 1)
            else:
                for r in rows:
                    tree.insert("", "end", values=r)
        cp = self.document.view()
        self.head.config(text="%s. Позивний %s, DMR ID %d. Вкладка «Контакти» редагується; усе, що ви змінюєте, лягає в документ і "
                              "потрапить у рацію лише за дією «Записати в рацію»." % (
                                  self.document.status_text(), cp.callsign() or "(порожньо)", cp.dmr_id()))
        self.set_editable(not self.is_busy())

    def set_editable(self, on):
        for b in (self.btn_edit, self.btn_add, self.btn_del):
            b.config(state="normal" if on else "disabled")

    def current_table(self):
        idx = self.nb.index(self.nb.select())
        return self.tables[idx]

    def _export_csv(self):
        key, title, cols, rows = self.current_table()
        path = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title="Зберегти таблицю «%s»" % title, defaultextension=".csv",
                                            initialdir=self.csv_dir, initialfile="codeplug_%s.csv" % key,
                                            filetypes=[("CSV (UTF-8)", "*.csv")])
        if not path:
            return
        try:
            cv.write_csv(path, cols, rows)
        except OSError as e:
            messagebox.showerror("Помилка", "Не вдалося зберегти файл:\n%s" % e, parent=self.winfo_toplevel())
            return
        messagebox.showinfo("Готово", "Збережено (%d рядків):\n%s" % (len(rows), os.path.abspath(path)), parent=self.winfo_toplevel())

    # =====================================================================================
    #  Редактор контактів (вкладка «Контакти»): правки одразу йдуть у документ
    # =====================================================================================

    def _build_contact_editor(self, frame, tree):
        bar = ttk.Frame(frame)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.btn_edit = ttk.Button(bar, text="Змінити...", command=self._on_edit_contact)
        self.btn_edit.pack(side="left")
        self.btn_add = ttk.Button(bar, text="Додати...", command=self._on_add_contact)
        self.btn_add.pack(side="left", padx=6)
        self.btn_del = ttk.Button(bar, text="Видалити", command=self._on_delete_contact)
        self.btn_del.pack(side="left")

    def _selected_slot(self):
        sel = self.contact_tree.selection()
        return self._item_ref.get(sel[0]) if sel else None

    def _original(self, slot):
        return next((c for c in self.document.view().contacts() if c[0] - 1 == slot), None)

    def _apply(self, ops):
        """Накласти операції на документ. Помилка -- документ не змінено, текст показується одним вікном."""
        try:
            self.document.edit_contacts(ops)
        except ce.ContactEditError as e:
            messagebox.showerror("Контакти", str(e), parent=self.winfo_toplevel())
            return False
        return True

    def _on_add_contact(self):
        if self.is_busy():
            return
        d = ContactDialog(self, "Новий контакт", "", "", 0)
        if d.result:
            self._apply([{"op": "add", "name": d.result["name"], "id": d.result["id"], "type": d.result["type"]}])

    def _on_edit_contact(self):
        if self.is_busy():
            return
        slot = self._selected_slot()
        if slot is None:
            messagebox.showinfo("Змінити", "Спершу виділи контакт у таблиці.", parent=self.winfo_toplevel())
            return
        orig = self._original(slot)
        if orig is None:
            return
        d = ContactDialog(self, "Контакт %d" % (slot + 1), orig[1], str(orig[2]), orig[3])
        if not d.result:
            return
        op = {"op": "edit", "slot": slot, "expect_name": orig[4], "name": None, "id": None, "type": None}
        if d.result["name"] != orig[1]:
            op["name"] = d.result["name"]
        if d.result["id"] != orig[2]:
            op["id"] = d.result["id"]
        if d.result["type"] != orig[3]:
            op["type"] = d.result["type"]
        if op["name"] is not None or op["id"] is not None or op["type"] is not None:
            self._apply([op])

    def _on_delete_contact(self):
        if self.is_busy():
            return
        slot = self._selected_slot()
        if slot is None:
            messagebox.showinfo("Видалити", "Спершу виділи контакт у таблиці.", parent=self.winfo_toplevel())
            return
        orig = self._original(slot)
        if orig is None:
            return
        refs = te.references(self.document.image, "contact", slot)
        if refs:
            # T0.3: запис, на який хтось посилається, не видаляється мовчки -- показуємо, хто посилається, і даємо вибір
            text = ("Видалити контакт №%d «%s»?\n\nНа нього посилаються:\n%s\n\n«Скасувати» -- нічого не міняти.\n«Видалити разом із посиланнями» -- контакт "
                    "зникне, його буде викреслено зі списків прийому, а поле «Контакт» у каналах стане «None»." % (slot + 1, orig[1], refs.text()))
            choice = gd.choice_dialog(self.winfo_toplevel(), "Контакт використовується", text,
                                      [("Скасувати", "cancel"), ("Видалити разом із посиланнями", "cascade")], 0)
            if choice != "cascade":
                return
            try:
                self.document.apply(te.delete_entity(self.document.image, "contact", slot, cc.system_decimal_point(), cascade=True))
            except te.TableEditError as e:
                messagebox.showerror("Контакти", str(e), parent=self.winfo_toplevel())
            return
        self._apply([{"op": "delete", "slot": slot, "expect_name": orig[4]}])


CodeplugViewerWindow = CodeplugViewer      # стара назва (зовнішній код)


class ContactDialog(tk.Toplevel):
    """Правка одного контакту: назва (з живим лічильником байтів), TG/ID, тип виклику. self.result = {name, id, type} або None."""

    def __init__(self, parent, title, name, ident, ctype):
        super().__init__(parent)
        gt.style_window(self)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result = None
        self.name_var = tk.StringVar(value=name)
        self.id_var = tk.StringVar(value=ident)
        self.type_var = tk.StringVar(value=ce.CALL_TYPE_LABELS.get(ctype, "Група"))
        f = ttk.Frame(self)
        f.pack(padx=14, pady=12)
        ttk.Label(f, text="Назва:").grid(row=0, column=0, sticky="w")
        self.name_entry = ttk.Entry(f, textvariable=self.name_var, width=34)
        self.name_entry.grid(row=0, column=1, padx=8, pady=3)
        self.name_info = ttk.Label(f, text="", wraplength=360, justify="left")
        self.name_info.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(f, text="TG / ID:").grid(row=2, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.id_var, width=14).grid(row=2, column=1, sticky="w", padx=8, pady=3)
        self.id_info = ttk.Label(f, text="", wraplength=360, justify="left")
        self.id_info.grid(row=3, column=1, sticky="w", padx=8)
        ttk.Label(f, text="Тип виклику:").grid(row=4, column=0, sticky="w")
        ttk.Combobox(f, textvariable=self.type_var, values=list(ce.CALL_TYPE_LABELS.values()), state="readonly", width=12).grid(
            row=4, column=1, sticky="w", padx=8, pady=3)
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=14, pady=(0, 12))
        self.ok_btn = ttk.Button(bar, text="Готово", command=self._ok)
        self.ok_btn.pack(side="right")
        ttk.Button(bar, text="Скасувати", command=self.destroy).pack(side="right", padx=6)
        self.name_var.trace_add("write", lambda *_: self._validate())
        self.id_var.trace_add("write", lambda *_: self._validate())
        self._validate()
        self.name_entry.focus_set()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        parent.wait_window(self)

    def _validate(self):
        chk = ce.check_name(self.name_var.get())
        self.name_info.config(text="%d з %d байтів. %s" % (chk["nbytes"], ce.NAME_LIMIT, chk["message"]),
                              foreground=gt.P["ok"] if chk["ok"] else gt.P["err"])
        try:
            ce.parse_id(self.id_var.get())
            id_ok = True
            self.id_info.config(text="")
        except ValueError as e:
            id_ok = False
            self.id_info.config(text=str(e), foreground=gt.P["err"])
        self.ok_btn.config(state="normal" if (chk["ok"] and id_ok) else "disabled")

    def _ok(self):
        rev = {v: k for k, v in ce.CALL_TYPE_LABELS.items()}
        self.result = {"name": self.name_var.get(), "id": ce.parse_id(self.id_var.get()), "type": rev[self.type_var.get()]}
        self.destroy()
