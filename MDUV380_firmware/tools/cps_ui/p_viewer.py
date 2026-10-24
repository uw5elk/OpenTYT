# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Перегляд кодплага»: теперішнє вікно перегляду (codeplug_viewer_gui), вбудоване в праву область.
Джерело -- рація (тоді вкладка «Контакти» редагується, запис іде шляхом відновлення) або файл бекапу (лише перегляд)."""
import os
from tkinter import ttk

import contact_edit
import cps_link as cps
import codeplug_view as cpview
import codeplug_viewer_gui
import gui_theme as gt
from tkinter import filedialog, messagebox

from .common import output_dir
from .p_backup import show_restore_result, close_quietly
from .panel import Panel

PLACEHOLDER = "Кодплаг не відкрито. Відкрий його з рації або з файлу бекапу."


class ViewerPanel(Panel):
    key = "viewer"
    title = "Перегляд кодплага"
    scroll = False          # таблиці мають власну прокрутку й розтягуються на всю область

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.viewer = None
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(bar, text="Перегляд кодплага", font=("Segoe UI", 13, "bold")).pack(side="left")
        self.view_radio_button = ttk.Button(bar, text="Відкрити з рації", command=self._on_view_radio_clicked)
        self.view_radio_button.pack(side="right")
        self.reg(self.view_radio_button)
        self.view_file_button = ttk.Button(bar, text="Відкрити бекап...", command=self._on_view_file_clicked)
        self.view_file_button.pack(side="right", padx=8)
        self.reg(self.view_file_button, radio=False)
        self.make_note()
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.placeholder = ttk.Label(self.body, text=PLACEHOLDER, foreground=gt.P["muted"], wraplength=600, justify="left")
        self.placeholder.pack(anchor="nw", pady=8)

    # --- відкриття ---

    def open_codeplug(self, cp, source_text, writable):
        """Показати кодплаг у цій панелі. writable=True -- джерело рація: вкладка «Контакти» редагується."""
        self.close_viewer()
        self.placeholder.pack_forget()
        self.viewer = codeplug_viewer_gui.CodeplugViewer(
            self.body, cp, source_text, output_dir(), write_contacts=self._write_contacts if writable else None, on_close=self.close_viewer)
        self.viewer.pack(fill="both", expand=True)

    def close_viewer(self, message=PLACEHOLDER):
        if self.viewer is not None:
            try:
                self.viewer.destroy()
            except Exception:  # noqa: BLE001
                pass
            self.viewer = None
        self.placeholder.config(text=message)
        self.placeholder.pack(anchor="nw", pady=8)

    def _on_view_file_clicked(self):
        if self.shell.busy:
            return
        path = filedialog.askopenfilename(title="Бекап кодплага", initialdir=output_dir(),
                                          filetypes=[("Бекап кодплага (.zip)", "*.zip"), ("Усі файли", "*.*")])
        if not path:
            return
        try:
            cp, _manifest = cpview.codeplug_from_backup(path)
        except (OSError, cps.CpsError) as e:
            messagebox.showerror("Помилка", "Не вдалося прочитати бекап:\n{}".format(e))
            return
        self.open_codeplug(cp, os.path.basename(path), writable=False)

    def _on_view_radio_clicked(self):
        self.shell.run_task(self._view_radio_worker, "Читаю кодплаг з рації для перегляду...",
                            on_done=lambda cp: self.open_codeplug(cp, "прямо з рації", writable=True), fail_suffix="")

    def _view_radio_worker(self):
        ser = cps.open_radio()
        try:
            cp, _manifest = cpview.codeplug_from_radio(cps.CpsLink(ser), self.shell.cps_progress)
        finally:
            ser.close()
        return cp

    # --- запис змін контактів із вікна перегляду (R26 V2) ---

    def _write_contacts(self, ops, viewer):
        if self.shell.busy:
            return
        self.shell.run_task(lambda: self._write_contacts_worker(ops), "Записую зміни контактів...", on_done=self._contacts_written,
                            fail_suffix="\n\nЯкщо про відмову сказано «Нічого не записано» -- рація не змінена.", reconnect_ms=6000)

    def _write_contacts_worker(self, ops):
        ser = cps.open_radio()
        try:
            return contact_edit.apply_to_radio(cps.CpsLink(ser), ops, self.shell.confirm_from_worker, self.shell.cps_progress, log=print,
                                               out_dir=output_dir())
        finally:
            close_quietly(ser)

    def _contacts_written(self, res):
        if res.get("nothingToDo") and not res.get("safetyCopy"):
            messagebox.showinfo("Нічого записувати", "Зміни не відрізняються від того, що вже є в рації.")
            return
        show_restore_result(res)
        if not res.get("cancelled"):
            self.close_viewer("Знімок застарів: відкрий кодплаг із рації ще раз.")      # знімок застарів
