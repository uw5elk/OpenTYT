# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Бекап і відновлення»: бекап у .zip (R24, лише читання), перегляд бекапу, відновлення (R25, ЗАПИС у рацію;
заблоковано константою cps_restore.RESTORE_UNLOCKED). Логіку перенесено з gui_flasher.py без змін."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import cps_link as cps
import cps_restore as cps_rest
import custom_region as cr
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
        self.region_var = tk.BooleanVar(value=False)            # R30: відновити також область custom-data (типово ВИМКНЕНО)
        self.region_state_var = tk.BooleanVar(value=False)      # R30: разом з лічильниками RCTL (стан; типово вимкнено)
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
        self.region_check = ttk.Checkbutton(rest, text="відновити також область custom-data (теми, SMS, RCTL, APRS, вибір ключа AES)", variable=self.region_var)
        self.region_check.pack(anchor="w", padx=8, pady=(0, 2))
        self.region_state_check = ttk.Checkbutton(rest, text="разом з лічильниками RCTL (стан прошивки, не налаштування)", variable=self.region_state_var)
        self.region_state_check.pack(anchor="w", padx=28, pady=(0, 2))
        self.region_only_button = ttk.Button(rest, text="Відновити лише область custom-data...", command=self._on_restore_region_clicked)
        self.region_only_button.pack(anchor="w", padx=8, pady=(4, 4))
        self.reg(self.region_only_button, radio=True, write=True)
        ttk.Label(rest, text=("Область custom-data лежить окремо від кодплага; у бекапі вона окремим файлом. Прапорець вимкнено: тоді відновлення кодплага її не чіпає. "
                              "Перед записом ти побачиш, які блоки будуть перезаписані. Бекап, зроблений до R30, області не має -- її тоді не чіпаю."),
                  wraplength=600, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=8, pady=(0, 4))
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
        cd_part = manifest["parts"].get(cr.PART_KEY)
        if cd_part:
            print("Область custom-data: {} Б, SHA-256 {}; блоки: {}.".format(
                cd_part["length"], cd_part["sha256"], ", ".join("{} ({} Б)".format(b["name"], b["length"]) for b in cd_part["blocks"]) or "жодного"))
            if any(b.get("secret") for b in cd_part["blocks"]):
                print("УВАГА: у блоці AES є ключовий матеріал -- зберігай файл як секрет.")
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
        with_region = bool(self.region_var.get())
        include_state = with_region and bool(self.region_state_var.get())
        self.shell.run_task(lambda: self._restore_worker(path, with_region, include_state), "Відновлюю кодплаг...", on_done=self._show_restore_done,
                            fail_suffix="\n\nСтан рації описано вище. Не вимикай програму, поки не прочитаєш повідомлення.",
                            reconnect_ms=6000)

    def _show_restore_done(self, out):
        show_restore_result(out["codeplug"])
        if out.get("region") is not None:
            self._show_region_result(out["region"])

    @staticmethod
    def _show_region_result(res):
        if res.get("absent"):
            messagebox.showinfo("Область custom-data", res["text"])
        else:
            tail = ("\n\nСтрахова копія області до запису:\n{}".format(res["safetyCopy"])) if res.get("safetyCopy") else ""
            failed = bool(res.get("result") and res["result"].get("failed"))
            (messagebox.showerror if failed else messagebox.showinfo)("Область custom-data", res["text"] + tail)

    def _on_restore_region_clicked(self):
        if self.shell.busy or not cps_rest.RESTORE_UNLOCKED:
            return
        path = filedialog.askopenfilename(title="Бекап, з якого відновити область custom-data", initialdir=output_dir(),
                                          filetypes=[("Бекап кодплага (.zip)", "*.zip")])
        if not path:
            return
        include_state = bool(self.region_state_var.get())
        self.shell.run_task(lambda: self._restore_region_worker(path, include_state), "Відновлюю область custom-data...", on_done=self._show_region_result,
                            fail_suffix="\n\nЗаписані блоки лишаються записаними; решту не чіпали.", plain_errors=True, reconnect_ms=6000)

    def _restore_region_worker(self, path, include_state):
        ser = cps.open_radio()
        try:
            return cr.restore_region(cps.CpsLink(ser), path, self.shell.confirm_from_worker, include_state=include_state,
                                     progress=self.shell.cps_progress, log=print)
        finally:
            close_quietly(ser)

    def _restore_worker(self, path, with_region=False, include_state=False):
        ser = cps.open_radio()
        try:
            return cr.restore_codeplug_and_region(cps.CpsLink(ser), path, self.shell.confirm_from_worker, self.shell.cps_progress, log=print,
                                                  with_region=with_region, include_state=include_state)
        finally:
            close_quietly(ser)
