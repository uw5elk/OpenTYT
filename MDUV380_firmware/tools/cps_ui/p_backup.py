# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Бекап і відновлення»: бекап у .zip (R24, лише читання), перегляд бекапу, відновлення (R25, ЗАПИС у рацію;
заблоковано константою cps_restore.RESTORE_UNLOCKED). Логіку перенесено з gui_flasher.py без змін."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import cps_restore as cps_rest
import gui_theme as gt

from .common import output_dir
from .panel import Panel


def show_restore_result(res):
    """Підсумок запису в рацію шляхом відновлення (спільний для відновлення, імпорту CSV, змін контактів і позивного)."""
    if res.get("cancelled"):
        messagebox.showinfo("Скасовано", "Рацію не змінено.\nСтрахова копія лишилась:\n{}".format(res["safetyCopy"]))
    elif res.get("nothingToDo"):
        messagebox.showinfo("Нічого відновлювати", "Рація вже містить цей кодплаг (крім калібрування й квіккеїв).\n"
                                                   "Страхова копія:\n{}".format(res["safetyCopy"]))
    else:
        what = "Зміни записано й перевірено" if res.get("report") is not None else "Кодплаг відновлено й перевірено"
        messagebox.showinfo("Готово", "{} (записано секторів: {} з {}, {} с).\n"
                                      "Рація перезавантажується.\n\nСтрахова копія стану ДО запису:\n{}".format(
                                          what, res["sectorsWritten"], res["sectorsTotal"], res["seconds"], res["safetyCopy"]))


def close_quietly(ser):
    """Закрити порт, не падаючи: після команди перезавантаження (C 6 1) порт міг уже зникнути."""
    try:
        ser.close()
    except Exception:  # noqa: BLE001
        pass


class BackupPanel(Panel):
    key = "backup"
    title = "Бекап і відновлення"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.full_snapshot_var = tk.BooleanVar(value=False)
        self.header("Бекап і відновлення", "Бекап читає кодплаг із рації й зберігає його в .zip у теці MD-UV390UKR (у домашній теці). "
                                           "Рація має бути у звичайному режимі (не в DFU).")

        box = ttk.LabelFrame(self, text="Бекап (лише читання)")
        box.pack(fill="x", padx=12, pady=6)
        self.backup_button = ttk.Button(box, text="Бекап кодплага", command=self._on_backup_clicked)
        self.backup_button.pack(anchor="w", padx=8, pady=(8, 4))
        self.reg(self.backup_button)
        ttk.Checkbutton(box, text="повний знімок (+ голосові підказки і ключі AES)", variable=self.full_snapshot_var).pack(anchor="w", padx=8, pady=(0, 8))

        view = ttk.LabelFrame(self, text="Перегляд і правка бекапу")
        view.pack(fill="x", padx=12, pady=6)
        self.view_file_button = ttk.Button(view, text="Відкрити бекап у перегляді...", command=self._on_view_file_clicked)
        self.view_file_button.pack(anchor="w", padx=8, pady=8)
        self.reg(self.view_file_button, radio=False)        # файл читається з диска, рація не потрібна

        rest = ttk.LabelFrame(self, text="Відновлення (ЗАПИС у рацію)")
        rest.pack(fill="x", padx=12, pady=6)
        self.restore_button = ttk.Button(rest, text="Відновити кодплаг...", command=self._on_restore_clicked)
        self.restore_button.pack(anchor="w", padx=8, pady=(8, 4))
        self.reg(self.restore_button, radio=True, write=True)
        self.restore_note = ttk.Label(rest, text="" if cps_rest.RESTORE_UNLOCKED else cps_rest.LOCKED_CAPTION, foreground=gt.P["warn"],
                                      wraplength=600, justify="left")
        self.restore_note.pack(anchor="w", padx=8, pady=(0, 8))

    def after_refresh(self):
        self.restore_note.config(text="" if cps_rest.RESTORE_UNLOCKED else cps_rest.LOCKED_CAPTION)

    # --- бекап ---

    def _on_backup_clicked(self):
        full = bool(self.full_snapshot_var.get())
        self.shell.run_task(lambda: self._backup_worker(full), "Читаю кодплаг з рації (бекап)...")

    def _backup_worker(self, full_snapshot=False):
        ser = cps.open_radio()
        try:
            data, manifest = cps.backup_codeplug(cps.CpsLink(ser), self.shell.cps_progress, full_snapshot=full_snapshot)
        finally:
            ser.close()
        path = cps.unique_path(output_dir(), cps.timestamp_name("codeplug_backup", ".zip"))
        with open(path, "wb") as f:
            f.write(data)
        print("Збережено: {}".format(path))
        print("Прошивка в рації: {} (radioType {}), читання тривало {} с.".format(
            manifest["radio"]["gitRevision"], manifest["radio"]["radioType"], manifest["durationSeconds"]))
        print("SHA-256 EEPROM: {}".format(manifest["parts"]["eeprom"]["sha256"]))
        print("SHA-256 флеш:   {}".format(manifest["parts"]["flash"]["sha256"]))
        if full_snapshot:
            print("ПОВНИЙ ЗНІМОК: у файлі ключі AES -- зберігай його як секрет.")
        return [path]

    # --- перегляд бекапу: відкривається як ДОКУМЕНТ (тим самим, що й «Відкрити з бекапу» над розділами) ---

    def _on_view_file_clicked(self):
        if self.shell.busy:
            return
        if self.shell.doc_open_file():
            self.shell.show("viewer")

    # --- відновлення (ЗАПИС у рацію) ---

    def _on_restore_clicked(self):
        if self.shell.busy or not cps_rest.RESTORE_UNLOCKED:
            return
        path = filedialog.askopenfilename(title="Бекап, з якого відновити кодплаг", initialdir=output_dir(),
                                          filetypes=[("Бекап кодплага (.zip)", "*.zip")])
        if not path:
            return
        self.shell.run_task(lambda: self._restore_worker(path), "Відновлюю кодплаг...", on_done=show_restore_result,
                            fail_suffix="\n\nСтан рації описано вище. Не вимикай програму, поки не прочитаєш повідомлення.",
                            reconnect_ms=6000)

    def _restore_worker(self, path):
        ser = cps.open_radio()
        try:
            return cps_rest.restore_codeplug(cps.CpsLink(ser), path, self.shell.confirm_from_worker, self.shell.cps_progress, log=print)
        finally:
            close_quietly(ser)
