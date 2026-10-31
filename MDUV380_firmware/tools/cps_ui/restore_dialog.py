# -*- coding: utf-8 -*-
"""R50: одне вікно «Відновити…» замість трьох кнопок і трьох прапорців у розділі «Бекап».

Джерело -- архів бекапу (.zip) або автоматична страхова копія, яку CPS сам зберіг перед записом (codeplug_pre-restore_*.zip,
customdata_pre-restore_*.bin, customdata_pre-compact_*.bin). Що відновити -- прапорці «кодплаг», «область custom-data» (з підпрапорцем «разом із лічильниками RCTL»)
і «ключі AES». Файл розпізнається за змістом (restore_extras.inspect_source): чого в ньому нема, того не можна позначити.
Сам запис і всі запобіжники -- у restore_extras.restore_selected / cps_restore / custom_region / aes_keys_backup (тут їх НЕ змінено).

Логіка вибору без Tk -- restore_plan.py (state_for() і summary_text(); тестуються без дисплея)."""
import datetime
import os
import tkinter as tk
from tkinter import ttk, filedialog

import gui_dialogs as gd
import gui_theme as gt
import restore_extras as rx
from restore_plan import state_for, summary_text   # noqa: F401 -- логіка без Tk

from .common import output_dir

MODE_ARCHIVE = "archive"
MODE_SAFETY = "safety"


def describe_file(path):
    try:
        st = os.stat(path)
        return "%s (%s)" % (os.path.basename(path), datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"))
    except OSError:
        return os.path.basename(path)


class RestoreDialog(tk.Toplevel):
    """Модальне вікно. Після закриття `self.spec` -- {"path","kind","codeplug","region","state","keys"} або None (скасовано)."""

    def __init__(self, parent, start_dir=None, initial_path=None):
        super().__init__(parent)
        gt.style_window(self)
        self.title("Відновити…")
        self.transient(parent.winfo_toplevel())
        self.spec = None
        self.start_dir = start_dir or output_dir()
        self.mode_var = tk.StringVar(value=MODE_ARCHIVE)
        self.path_var = tk.StringVar(value=initial_path or "")
        self.safety_var = tk.StringVar(value="")
        self.vars = {"codeplug": tk.BooleanVar(value=True), "region": tk.BooleanVar(value=False), "state": tk.BooleanVar(value=False), "keys": tk.BooleanVar(value=False)}
        self.info = {"kind": rx.KIND_BAD, "why": "Обери файл."}
        self.safety_items = []
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=(12, 4))

        src = ttk.LabelFrame(body, text="1. Звідки")
        src.pack(fill="x", pady=(0, 6))
        r1 = ttk.Frame(src)
        r1.pack(fill="x", padx=8, pady=(6, 2))
        self.rb_archive = ttk.Radiobutton(r1, text="Архів бекапу", variable=self.mode_var, value=MODE_ARCHIVE, command=self._on_mode)
        self.rb_archive.pack(side="left")
        self.path_entry = ttk.Entry(r1, textvariable=self.path_var)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=8)
        self.path_entry.bind("<Return>", lambda _e: self._refresh())
        self.path_entry.bind("<FocusOut>", lambda _e: self._refresh())
        self.pick_btn = ttk.Button(r1, text="Обрати файл…", command=self._pick)
        self.pick_btn.pack(side="left")
        r2 = ttk.Frame(src)
        r2.pack(fill="x", padx=8, pady=(2, 2))
        self.rb_safety = ttk.Radiobutton(r2, text="Автоматична страхова копія (CPS зберіг її сам перед записом)", variable=self.mode_var, value=MODE_SAFETY,
                                         command=self._on_mode)
        self.rb_safety.pack(side="left")
        self.rescan_btn = ttk.Button(r2, text="Оновити список", command=self._scan_safety)
        self.rescan_btn.pack(side="right")
        self.safety_box = ttk.Combobox(src, textvariable=self.safety_var, state="readonly")
        self.safety_box.pack(fill="x", padx=(32, 8), pady=(0, 6))
        self.safety_box.bind("<<ComboboxSelected>>", lambda _e: self._on_safety_picked())
        self.file_label = gd.autowrap(ttk.Label(src, text="", wraplength=500, justify="left", foreground=gt.P["muted"]), src, margin=24)
        self.file_label.pack(anchor="w", padx=8, pady=(0, 6))

        what = ttk.LabelFrame(body, text="2. Що відновити")
        what.pack(fill="x", pady=6)
        self.checks = {}
        for key, text, indent in (("codeplug", "кодплаг (канали, зони, контакти, налаштування кодплага)", 8),
                                  ("region", "область custom-data (теми, SMS, RCTL, APRS, вибір ключа AES)", 8),
                                  ("state", "разом з лічильниками RCTL (стан прошивки, не налаштування)", 30),
                                  ("keys", "ключі AES (перезапишу слоти з архіву; перед записом покажу, які)", 8)):
            cb = ttk.Checkbutton(what, text=text, variable=self.vars[key], command=self._on_check)
            cb.pack(anchor="w", padx=indent, pady=2)
            self.checks[key] = cb
        self.note_label = gd.autowrap(ttk.Label(what, text="", wraplength=500, justify="left", foreground=gt.P["warn"]), what, margin=24)
        self.note_label.pack(anchor="w", padx=8, pady=(2, 6))

        self.summary = gd.autowrap(ttk.Label(body, text="", wraplength=500, justify="left"), body, margin=8)
        self.summary.pack(anchor="w", pady=(4, 4))

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(4, 12))
        self.ok_btn = ttk.Button(bar, text="Відновити", command=self._ok)
        self.ok_btn.pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Скасувати", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._scan_safety()
        self._refresh()
        gd.remember_window(self, "restore", (640, 560))
        self.grab_set()

    # --- джерело ---

    def _dirs(self):
        d = os.path.dirname(os.path.abspath(self.path_var.get())) if self.path_var.get().strip() else None
        return [self.start_dir, d]

    def _scan_safety(self):
        self.safety_items = rx.find_safety_copies(*self._dirs())
        labels = [describe_file(p) for p, _t in self.safety_items]
        self.safety_box.config(values=labels)
        if labels and self.safety_var.get() not in labels:
            self.safety_var.set(labels[0])
        if not labels:
            self.safety_var.set("")
        state = "readonly" if labels else "disabled"
        self.safety_box.config(state=state)

    def _on_safety_picked(self):
        self.mode_var.set(MODE_SAFETY)
        self._refresh()

    def _on_mode(self):
        self._refresh()

    def _pick(self):
        path = filedialog.askopenfilename(parent=self, title="Бекап або страхова копія, з яких відновити", initialdir=self.start_dir,
                                          filetypes=[("Бекап кодплага (.zip) або страхова копія області (.bin)", "*.zip *.bin"), ("Усі файли", "*.*")])
        if path:
            self.path_var.set(path)
            self.mode_var.set(MODE_ARCHIVE)
            self._scan_safety()
            self._refresh()

    def chosen_path(self):
        if self.mode_var.get() == MODE_SAFETY:
            labels = list(self.safety_box.cget("values"))
            try:
                return self.safety_items[labels.index(self.safety_var.get())][0]
            except (ValueError, IndexError):
                return ""
        return self.path_var.get().strip()

    def _current(self):
        return {k: bool(v.get()) for k, v in self.vars.items()}

    def _refresh(self, keep=True):
        path = self.chosen_path()
        new_info = rx.inspect_source(path) if path else {"kind": rx.KIND_BAD, "why": "Обери файл бекапу або страхову копію."}
        changed_file = getattr(self, "_last_path", None) != path
        self._last_path = path
        self.info = new_info
        cur = self._current() if (keep and not changed_file) else None
        st = state_for(new_info, cur)
        self.st = st
        for k, cb in self.checks.items():
            val, enabled = st[k]
            self.vars[k].set(val)
            cb.config(state="normal" if enabled else "disabled")
        if new_info["kind"] == rx.KIND_BAD:
            self.file_label.config(text=new_info.get("why", ""), foreground=gt.P["err"] if path else gt.P["muted"])
        else:
            kind = "архів бекапу" if new_info["kind"] == rx.KIND_ZIP else "страхова копія області custom-data"
            self.file_label.config(text="%s: %s" % (kind, describe_file(path)), foreground=gt.P["muted"])
        self._update_summary()

    def _on_check(self):
        st = state_for(self.info, self._current())
        self.st = st
        for k, cb in self.checks.items():
            val, enabled = st[k]
            self.vars[k].set(val)
            cb.config(state="normal" if enabled else "disabled")
        self._update_summary()

    def _update_summary(self):
        st = self.st
        self.note_label.config(text=st["note"])
        self.summary.config(text=summary_text(self.info, st))
        self.ok_btn.config(state="normal" if st["ok"] else "disabled")

    def _ok(self):
        if not self.st["ok"]:
            return
        self.spec = {"path": self.chosen_path(), "kind": self.info["kind"], "codeplug": self.vars["codeplug"].get(), "region": self.vars["region"].get(),
                     "state": self.vars["state"].get() and self.vars["region"].get(), "keys": self.vars["keys"].get()}
        self.destroy()


def ask_restore(parent, start_dir=None, initial_path=None):
    dlg = RestoreDialog(parent, start_dir, initial_path)
    parent.wait_window(dlg)
    return dlg.spec
