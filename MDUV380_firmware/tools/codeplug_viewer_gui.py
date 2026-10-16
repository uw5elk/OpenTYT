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
import gui_theme as gt
import gui_dialogs as gd
import contact_edit as ce
import cps_csv as cc
import cps_restore as cr

# ширини колонок за назвою (пікселі); решта -- 120
_WIDTHS = {"№": 50, "Назва": 190, "TG / ID": 100, "Тип": 80, "Кодування": 80, "Контактів": 80, "Склад": 420, "Каналів": 70,
           "Канали": 420, "RX, МГц": 100, "TX, МГц": 100, "Режим": 70}


class CodeplugViewerWindow(tk.Toplevel):
    def __init__(self, parent, codeplug, source_text, csv_dir, write_contacts=None):
        """write_contacts(ops, window) -- обробник «Записати зміни в рацію» (редактор контактів, R26 V2); None -- вікно лише для перегляду
        (так для перегляду бекап-файла: правки там вводити нема сенсу -- файл не рація)."""
        super().__init__(parent)
        gt.style_window(self)
        self.title("Кодплуг: " + source_text)
        self.geometry("900x520")
        self.minsize(640, 360)
        self.codeplug = codeplug
        self.csv_dir = csv_dir
        self.tables = codeplug.tables()
        self.trees = []
        self.write_contacts = write_contacts
        self.img = cc.Image.from_codeplug(codeplug)
        self.ops = []                    # операції редактора контактів (contact_edit)
        self.contact_tree = None
        self._item_ref = {}

        head = ttk.Label(self, text="%s -- %s. Позивний %s, DMR ID %d. %s" % (
            source_text, codeplug.manifest.get("createdUtc", "прямо з рації"), codeplug.callsign() or "(порожньо)", codeplug.dmr_id(),
            "Вкладка «Контакти» редагується; у рацію пишеться лише за кнопкою «Записати зміни в рацію...»."
            if write_contacts is not None else "Лише перегляд: у рацію нічого не записується."),
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
            if key == "contacts" and self.write_contacts is not None:
                self.contact_tree = tree
                self._build_contact_editor(frame, tree, cols)

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


    # =====================================================================================
    #  R26 V2: редактор контактів (лише вкладка «Контакти» у вікні «з рації»)
    # =====================================================================================

    def _virtual_contacts(self):
        """[(ключ, номер або 'нов.', назва, id, тип, кодування, стан)] -- початкові контакти з накладеними операціями."""
        out = []
        deleted = {o["slot"] for o in self.ops if o["op"] == "delete"}
        edits = {o["slot"]: o for o in self.ops if o["op"] == "edit"}
        for (number, name, ident, ctype, raw, enc) in self.codeplug.contacts():
            slot = number - 1
            state = ""
            if slot in deleted:
                state = "видалятиметься"
            elif slot in edits:
                e = edits[slot]
                if e.get("name") is not None:
                    name, enc = e["name"], ce.check_name(e["name"])["enc"] or enc
                if e.get("id") is not None:
                    ident = e["id"]
                if e.get("type") is not None:
                    ctype = e["type"]
                state = "змінено"
            out.append((("slot", slot), str(number), name, ident, ctype, enc, state))
        for i, o in enumerate([o for o in self.ops if o["op"] == "add"]):
            out.append((("add", i), "нов.", o["name"], o["id"], o["type"], ce.check_name(o["name"])["enc"], "новий"))
        return out

    def _build_contact_editor(self, frame, tree, cols):
        tree.configure(columns=list(cols) + ["Стан"])
        for c in list(cols) + ["Стан"]:
            tree.heading(c, text=c)
            tree.column(c, width=_WIDTHS.get(c, 120 if c != "Стан" else 120), anchor="w", stretch=False)
        bar = ttk.Frame(frame)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.btn_edit = ttk.Button(bar, text="Змінити...", command=self._on_edit_contact)
        self.btn_edit.pack(side="left")
        self.btn_add = ttk.Button(bar, text="Додати...", command=self._on_add_contact)
        self.btn_add.pack(side="left", padx=6)
        self.btn_del = ttk.Button(bar, text="Видалити", command=self._on_delete_contact)
        self.btn_del.pack(side="left")
        self.btn_undo = ttk.Button(bar, text="Скасувати всі зміни", command=self._on_undo_all)
        self.btn_undo.pack(side="left", padx=6)
        self.btn_write = ttk.Button(bar, text="Записати зміни в рацію...", command=self._on_write)
        self.btn_write.pack(side="right")
        self.edit_note = ttk.Label(bar, text="", foreground=gt.P["warn"])
        self.edit_note.pack(side="right", padx=8)
        self._refresh_contacts()

    def _refresh_contacts(self):
        tree = self.contact_tree
        tree.delete(*tree.get_children())
        self._item_ref = {}
        for key, number, name, ident, ctype, enc, state in self._virtual_contacts():
            item = tree.insert("", "end", values=(number, name, str(ident), cv.CALL_TYPES.get(ctype, "тип %d" % ctype), enc, state))
            self._item_ref[item] = key
        n = len(self.ops)
        locked = not cr.RESTORE_UNLOCKED
        self.btn_write.config(state="normal" if (n and not locked) else "disabled")
        self.btn_undo.config(state="normal" if n else "disabled")
        self.edit_note.config(text=(cr.LOCKED_CAPTION if locked else ("Змін у черзі: %d" % n if n else "")))

    def _selected_key(self):
        sel = self.contact_tree.selection()
        return self._item_ref.get(sel[0]) if sel else None

    def _on_add_contact(self):
        d = ContactDialog(self, "Новий контакт", "", "", 0)
        if d.result:
            self.ops.append({"op": "add", "name": d.result["name"], "id": d.result["id"], "type": d.result["type"]})
            self._refresh_contacts()

    def _on_edit_contact(self):
        key = self._selected_key()
        if key is None:
            messagebox.showinfo("Змінити", "Спершу виділи контакт у таблиці.", parent=self)
            return
        virt = {k: (n, name, i, t) for (k, n, name, i, t, _e, _s) in self._virtual_contacts()}
        _n, name, ident, ctype = virt[key]
        d = ContactDialog(self, "Контакт %s" % (key[1] + 1 if key[0] == "slot" else "(новий)"), name, str(ident), ctype)
        if not d.result:
            return
        if key[0] == "add":
            adds = [o for o in self.ops if o["op"] == "add"]
            adds[key[1]].update(name=d.result["name"], id=d.result["id"], type=d.result["type"])
        else:
            slot = key[1]
            orig = next(c for c in self.codeplug.contacts() if c[0] - 1 == slot)
            self.ops = [o for o in self.ops if not (o["op"] in ("edit", "delete") and o["slot"] == slot)]
            op = {"op": "edit", "slot": slot, "expect_name": orig[4], "name": None, "id": None, "type": None}
            if d.result["name"] != orig[1]:
                op["name"] = d.result["name"]
            if d.result["id"] != orig[2]:
                op["id"] = d.result["id"]
            if d.result["type"] != orig[3]:
                op["type"] = d.result["type"]
            if op["name"] is not None or op["id"] is not None or op["type"] is not None:
                self.ops.append(op)
        self._refresh_contacts()

    def _on_delete_contact(self):
        key = self._selected_key()
        if key is None:
            messagebox.showinfo("Видалити", "Спершу виділи контакт у таблиці.", parent=self)
            return
        if key[0] == "add":
            adds = [o for o in self.ops if o["op"] == "add"]
            self.ops.remove(adds[key[1]])
        else:
            slot = key[1]
            warn = ce.delete_warning(self.img, slot)
            if warn and not gd.confirm_dialog(self, "Видалити контакт?", warn + "\n\nВсе одно додати видалення в чергу?",
                                              yes="Додати в чергу", no="Скасувати"):
                return
            orig = next(c for c in self.codeplug.contacts() if c[0] - 1 == slot)
            self.ops = [o for o in self.ops if not (o["op"] in ("edit", "delete") and o["slot"] == slot)]
            self.ops.append({"op": "delete", "slot": slot, "expect_name": orig[4]})
        self._refresh_contacts()

    def _on_undo_all(self):
        self.ops = []
        self._refresh_contacts()

    def _on_write(self):
        if not self.ops or not cr.RESTORE_UNLOCKED or self.write_contacts is None:
            return
        self.write_contacts(list(self.ops), self)


class ContactDialog(tk.Toplevel):
    """Правка одного контакту: назва (з живим лічильником байтів), TG/ID, тип виклику. self.result = {name, id, type} або None."""

    def __init__(self, parent, title, name, ident, ctype):
        super().__init__(parent)
        gt.style_window(self)
        self.title(title)
        self.transient(parent)
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
