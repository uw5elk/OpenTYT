# -*- coding: utf-8 -*-
"""Розділ «Рація → Прошивка»: донор кодека, файл .bin, ПРОШИТИ, драйвер DFU (Zadig). Логіку перенесено з gui_flasher.py БЕЗ змін."""
import configparser
import os
import time
import webbrowser
from tkinter import ttk, filedialog, messagebox

import opengd77_stm32_firmware_loader as loader
import dmr_reboot_dfu as reboot
import gui_theme as gt

from .common import CONFIG_FILENAME, ZADIG_URL, find_bundled_firmware, load_usb_backend
from .panel import Panel

try:
    import serial  # той самий пакет, яким уже користується dmr_reboot_dfu.py
except ImportError:
    serial = None


class FlashPanel(Panel):
    key = "flash"
    title = "Прошивка"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.backend = load_usb_backend()
        self.donor_path = self._load_saved_donor()
        self.firmware_path = find_bundled_firmware()

        self.header("Прошивка", "Рація може бути і в звичайному режимі (тоді її буде переведено в DFU автоматично), і вже в DFU.")

        donor_frame = ttk.LabelFrame(self, text="Донор кодека AMBE (файл MD9600 V5)")
        donor_frame.pack(fill="x", padx=12, pady=6)
        self.donor_label = ttk.Label(donor_frame, text="", wraplength=560, justify="left")
        self.donor_label.pack(anchor="w", padx=8, pady=(6, 2))
        self.donor_btn = ttk.Button(donor_frame, text="Обрати файл донора...", command=self._pick_donor)
        self.donor_btn.pack(anchor="w", padx=8, pady=(0, 8))
        self.reg(self.donor_btn, radio=False)

        # Секція прошивки видима ЗАВЖДИ: вбудована береться за типову, але можна обрати інший .bin -- діагностичну збірку або
        # aes/def з артефактів CI (без перезбирання .exe).
        fw_frame = ttk.LabelFrame(self, text="Прошивка")
        fw_frame.pack(fill="x", padx=12, pady=6)
        self.firmware_label = ttk.Label(fw_frame, text="", wraplength=560, justify="left")
        self.firmware_label.pack(anchor="w", padx=8, pady=(6, 2))
        self.fw_btn = ttk.Button(fw_frame, text="Обрати файл прошивки...", command=self._pick_firmware)
        self.fw_btn.pack(anchor="w", padx=8, pady=(0, 8))
        self.reg(self.fw_btn, radio=False)

        action = ttk.Frame(self)
        action.pack(fill="x", padx=12, pady=6)
        self.flash_button = ttk.Button(action, text="ПРОШИТИ", command=self._on_flash_clicked)
        self.flash_button.pack(side="left")
        self.reg(self.flash_button, radio=False)     # доступна й без «знайденої» рації: у DFU вона для пошуку невидима
        self.zadig_button = ttk.Button(action, text="Драйвер DFU (Zadig)", command=lambda: webbrowser.open(ZADIG_URL))
        self.zadig_button.pack(side="left", padx=8)
        ttk.Label(self, wraplength=640, justify="left", foreground=gt.P["muted"],
                  text=("Кнопка «ПРОШИТИ» доступна, навіть коли рацію не знайдено: рація в режимі DFU не відповідає CPS-протоколу, "
                        "тому пошук її не бачить. Якщо рації нема взагалі, прошивка скаже про це після натискання.")).pack(
            anchor="w", padx=12, pady=(0, 6))
        self._refresh_donor_label()
        self._refresh_firmware_label()

    # --- донор -------------------------------------------------------------

    def _load_saved_donor(self):
        """Читаємо той самий ini-файл, яким користується CLI-прошивальник (~/.gd77firmwareloader.ini) -- обраний тут донор одразу
        бачить і CLI, і навпаки."""
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILENAME)
        loader.config = cfg  # patch_and_download_firmware() читає саме цю глобальну змінну
        try:
            path = cfg["GLOBAL"]["SourceSTM32Firmware"]
        except KeyError:
            path = ""
        return path if (path and os.path.isfile(path)) else ""

    def _save_donor(self, path):
        cfg = getattr(loader, "config", None) or configparser.ConfigParser()
        cfg.read(CONFIG_FILENAME)
        if "GLOBAL" not in cfg:
            cfg["GLOBAL"] = {}
        cfg["GLOBAL"]["SourceSTM32Firmware"] = path
        with open(CONFIG_FILENAME, "w") as f:
            cfg.write(f)
        loader.config = cfg

    def _pick_donor(self):
        path = filedialog.askopenfilename(
            title="Обери файл донора кодека (MD9600-CSV(2571V5)-V26.45.bin)",
            filetypes=[("Файл прошивки", "*.bin"), ("Усі файли", "*.*")],
        )
        if not path:
            return

        checksum = loader.GetSHA256Checksum(path)
        if checksum != loader.FW2645_SHA256_Checksum:
            messagebox.showerror(
                "Не той файл",
                "Контрольна сума не збігається з донором MD9600-CSV(2571V5)-V26.45.bin.\n\n"
                "Це або інший файл, або пошкоджене завантаження. З ним DMR не запрацює -- "
                "оберіть правильний файл, або натисніть \"ПРОШИТИ\" без донора для тесту "
                "тільки FM-частини.",
            )
            return

        self.donor_path = path
        self._save_donor(path)
        self._refresh_donor_label()

    def _refresh_donor_label(self):
        if self.donor_path:
            self.donor_label.config(text="Донор перевірено: " + self.donor_path, foreground=gt.P["ok"])
        else:
            self.donor_label.config(text="Донор не обрано -- прошивка піде тільки в режимі FM, без DMR.", foreground=gt.P["warn"])

    # --- прошивка (файл) ----------------------------------------------------

    def _pick_firmware(self):
        path = filedialog.askopenfilename(title="Обери файл прошивки (.bin)", filetypes=[("Файл прошивки", "*.bin"), ("Усі файли", "*.*")])
        if not path:
            return
        self.firmware_path = path
        self._refresh_firmware_label()

    def _refresh_firmware_label(self):
        if self.firmware_path:
            name = os.path.basename(self.firmware_path)
            bundled = " (вбудована)" if self.firmware_path == find_bundled_firmware() else ""
            self.firmware_label.config(text="Прошивка: " + name + bundled, foreground=gt.P["ok"])
        else:
            self.firmware_label.config(text="Файл прошивки не знайдено -- обери вручну.", foreground=gt.P["err"])

    # --- сама прошивка (у фоновому потоці) ------------------------------------

    def _on_flash_clicked(self):
        if self.shell.busy:
            return

        if not self.firmware_path or not os.path.isfile(self.firmware_path):
            messagebox.showerror("Немає прошивки", "Спершу оберіть файл прошивки.")
            return

        if not self.donor_path:
            if not messagebox.askyesno(
                "Без донора кодека",
                "Донор кодека не обрано або не пройшов перевірку.\n\n"
                "Прошити БЕЗ DMR (тільки FM, для тесту решти змін)?",
            ):
                return

        if not messagebox.askokcancel(
            "Прошити рацію?",
            "Переконайся, що USB-кабель підключено, а рація увімкнена.\n\n"
            "Прошивка займе приблизно хвилину. Не від'єднуй кабель, поки не "
            "з'явиться повідомлення \"Готово\".",
        ):
            return

        self.shell.log("Починаю прошивку: " + os.path.basename(self.firmware_path))
        self.shell.run_task(self._flash_worker, "Прошиваю...", on_done=self._on_flash_finished, ok_status=None, reconnect_ms=4000)

    def _connect_kwargs(self):
        kwargs = {"idVendor": loader.defaultVID, "idProduct": loader.defaultPID}
        if self.backend is not None:
            kwargs["backend"] = self.backend
        return kwargs

    def _try_connect(self):
        try:
            loader.init(**self._connect_kwargs())
            return True
        except Exception:
            return False

    def _try_auto_reboot_to_dfu(self):
        """Якщо рація ще у звичайному режимі (не в DFU), автоматично переводимо її туди самою тільки командою по USB -- так само,
        як робить окремий dmr_reboot_dfu.py. Спрацьовує тільки на збірках з ENABLE_DMR_DATA=1; якщо рація вже в DFU або команда не
        спрацювала -- нічого страшного, просто повертаємо False і пробуємо підключитись напряму."""
        if serial is None:
            return False

        port = reboot.find_port()
        if not port:
            return False

        self.shell.log("Рація у звичайному режимі, переводжу в DFU автоматично...")
        try:
            with serial.Serial(port, 115200, timeout=0.5) as ser:
                ser.reset_input_buffer()
                ser.write(bytes([reboot.CMD, reboot.SUB_REBOOT_DFU]))
                ser.flush()
        except serial.SerialException:
            pass  # порт міг зникнути, бо рація вже почала перезавантажуватись -- це очікувано

        time.sleep(2.0)
        return True

    def _flash_worker(self):
        """Повертає (успіх, причина) -- розбір результату в _on_flash_finished()."""
        ok = False
        reason = None
        try:
            connected = self._try_connect()

            if not connected:
                self._try_auto_reboot_to_dfu()
                connected = self._try_connect()

            if not connected:
                reason = "no_dfu"
            else:
                def progress_cb(addr, offset, size, strPrefix=None):
                    pct = int(offset * 100 / size) if size else 0
                    self.shell.post_progress(pct)

                loader.patch_and_download_firmware(self.firmware_path, None, loader.FWPlatformOutput.MD_UV380, progress_cb)
                ok = True
        except SystemExit as e:
            reason = "exit_{}".format(e.code)
        except Exception as e:  # noqa: BLE001 -- показуємо будь-яку помилку користувачу, не ховаємо
            reason = "exception: {}".format(e)
        return ok, reason

    def _on_flash_finished(self, result):
        ok, reason = result
        if ok:
            self.shell.set_progress(100)
            self.shell.set_status("Готово! Можна від'єднати USB.", "ok")
            self.shell.log("*** Готово.")
            messagebox.showinfo("Готово", "Прошивку завершено. Можна від'єднати USB і увімкнути рацію звичайним способом.")
            return

        self.shell.set_status("Не вдалося прошити.", "err")

        if reason == "no_dfu":
            self.shell.log("!!! Рацію не знайдено в режимі DFU.")
            messagebox.showerror(
                "Рацію не знайдено",
                "Не вдалося підключитись до рації в режимі DFU.\n\n"
                "Найчастіші причини:\n"
                "1. USB-кабель не підключено або рація вимкнена.\n"
                "2. Це перший запуск на цьому комп'ютері -- Windows ще не має "
                "драйвера для режиму DFU. Натисни кнопку \"Драйвер DFU (Zadig)\", "
                "постав Zadig, тоді запусти прошивку ще раз (Zadig працює тільки "
                "коли рація вже в DFU -- увімкни її, утримуючи бічні кнопки, якщо "
                "автоматичний перехід не спрацював).\n"
                "3. Стара прошивка на рації не вміє автоматично йти в DFU -- "
                "увімкни рацію вручну, утримуючи бічні кнопки, і спробуй ще раз.",
            )
        else:
            self.shell.log("!!! Помилка: {}".format(reason))
            messagebox.showerror("Помилка прошивки", "Щось пішло не так: {}\n\nПодробиці -- у журналі внизу вікна.".format(reason))
