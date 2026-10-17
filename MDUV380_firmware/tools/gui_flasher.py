#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenGD77-AES256-fork -- простий GUI-прошивальник для тестування "з коробки".

Ідея: не кожен тестер має бажання/навички ставити Python, pip-пакети, копіювати
libusb-1.0.dll і пам'ятати два різні VID:PID (звичайний режим і DFU). Цей файл --
тонка обгортка з вікном і двома кнопками навколо вже перевіреного коду
opengd77_stm32_firmware_loader.py та dmr_reboot_dfu.py. Жоден протокольний код
(DFU-команди, злиття кодека) тут НЕ дублюється і не переписується -- обидва модулі
імпортуються як є, щоб GUI і CLI завжди прошивали побайтово однаково.

Збирається в один портативний .exe через PyInstaller на GitHub Actions
(windows-latest) -- дивись job build-gui-flasher у .github/workflows/build.yml.
При збірці поруч кладуться:
  - openuv380-10w.bin      -- поточна українська прошивка (щоб не якати ЇЇ окремо);
  - libusb-1.0.dll         -- бо в .exe немає "сусіднього python.exe в PATH",
                               на який можна покластись, як при ручному запуску;
  - build_info.txt         -- короткий хеш коміту й дата збірки (для звітів "у мене
                               не працює" -- видно ЯКУ саме збірку тестували).

Драйвер WinUSB для режиму DFU (0483:DF11) цей інструмент НЕ ставить -- це
обмеження Windows, а не наше: без нього жоден інструмент (ні CLI, ні цей GUI) не
побачить рацію в завантажувачі. Раз на комп'ютер це робиться вручну через Zadig
(кнопка "Драйвер DFU (Zadig)" відкриє сторінку із завантаженням).
"""

import os
import sys
import glob
import time
import queue
import threading
import webbrowser
import configparser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# --- Перевірені модулі проєкту, що роблять усю фактичну роботу ---------------------
import opengd77_stm32_firmware_loader as loader
import dmr_reboot_dfu as reboot
import aes_key_store            # CPS-протокол (flash_read/flash_write_block/find_port) --
                                 # той самий, перевірений код, що й у CLI-версії
import stock_key_table as skt   # wrap/unwrap-логіка стокової таблиці ключів (без USB)
import custom_data as cd        # безпечний read/write custom-data блоків (тема/AES-селектор/
                                 # RCTL і т.д. в ОДНОМУ регіоні -- див. коментар у custom_data.py)
import rctl_config as rctl      # формат блоку "RCTL" (allowlist віддаленого керування)
import cps_link as cps          # R24: знімок екрана і бекап кодплуга (лише читання, без залежностей крім pyserial)
import cps_restore as cps_rest  # R25: відновлення кодплуга (ЗАПИС; заблоковано константою RESTORE_UNLOCKED)
import codeplug_view as cpview  # R25: розбір вмісту кодплуга (спільне декодування назв)
import codeplug_viewer_gui      # R25: вікно перегляду (R26 V2: редактор контактів на вкладці «Контакти»)
import contact_edit             # R26 V2: операції над контактами -> запис шляхом відновлення з бекапу
import cps_csv                  # R26: експорт/імпорт CSV (формат OpenGD77 CPS); імпорт іде шляхом відновлення з бекапу
import gui_theme as gt          # R26 V3: темна тема (одна палітра)
import gui_dialogs as gd        # R26 V3: темні діалоги підтвердження й довгих повідомлень

try:
    import serial  # той самий пакет, яким уже користується dmr_reboot_dfu.py
except ImportError:
    serial = None


CONFIG_FILENAME = str(Path.home() / ".gd77firmwareloader.ini")
ZADIG_URL = "https://zadig.akeo.ie/"


def resource_path(name):
    """Шлях до файлу, вбудованого поруч зі скомпільованим .exe (PyInstaller кладе
    їх у тимчасову теку sys._MEIPASS), або поруч зі скриптом при запуску з джерела
    (для розробки/тестування без збірки .exe)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def load_usb_backend():
    """У .exe не можна покладатись на автопошук libusb-1.0.dll (немає "сусіднього
    python.exe в PATH", як при ручному запуску) -- підключаємо вбудовану копію явно.
    Якщо запущено з джерела і dll поруч немає -- повертаємо None, pyusb сам
    спробує знайти системну бібліотеку (як завжди)."""
    try:
        import usb.backend.libusb1
    except ImportError:
        return None

    dll = resource_path("libusb-1.0.dll")
    if os.path.isfile(dll):
        return usb.backend.libusb1.get_backend(find_library=lambda x: dll)
    return None


def find_bundled_firmware():
    """Прошивка, вбудована поруч зі скомпільованим .exe."""
    matches = sorted(glob.glob(resource_path("openuv380-10w*.bin")))
    return matches[0] if matches else None


def read_build_info():
    """Короткий підпис збірки (коміт+дата), якщо CI його поклав поруч. Використовуй
    цей рядок у звітах про проблеми -- він каже, ЯКУ саме збірку тестували."""
    path = resource_path("build_info.txt")
    if os.path.isfile(path):
        try:
            info = open(path, encoding="utf-8").read().strip()
            # Назву форка у вікні не показуємо -- лишаємо тільки коміт і дату. Чистимо ТУТ,
            # а не лише в CI: у вже зібраних .exe лежить старий build_info.txt із префіксом,
            # і без цієї обрізки він показувався б і далі.
            for prefix in ("OpenGD77-AES256-fork,", "OpenGD77-AES256-fork"):
                if info.startswith(prefix):
                    info = info[len(prefix):].lstrip(" ,")
                    break
            return info
        except OSError:
            pass
    return "збірка з джерела (без build_info.txt)"


def enable_entry_clipboard(entry):
    """Вмикає копіювання/вставляння/вирізання в текстовому полі Tkinter так, щоб
    воно ГАРАНТОВАНО працювало на Windows з українською (чи будь-якою нелатинською)
    розкладкою клавіатури.

    Проблема, яку це виправляє: стандартні прив'язки Ctrl+C/Ctrl+V у Tk на Windows
    спрацьовують за КОДОМ СИМВОЛУ, який дає поточна розкладка для фізичної клавіші --
    а не за самою фізичною клавішею. З українською розкладкою фізична клавіша "V"
    видає не 'v', а кирилицю ("м"), тому Ctrl+V не розпізнається як вставляння і
    поле здається "заблокованим для вставки", хоча насправді просто не спрацьовує
    прив'язка. Пункту контекстного меню (по правій кнопці миші) в ttk.Entry також
    немає за замовчуванням -- тому користувачу взагалі нема як вставити ключ.

    Рішення -- два незалежні шляхи, кожен обходить проблему розкладки по-своєму:
      1) Контекстне меню правої кнопки миші (Вирізати/Копіювати/Вставити/Виділити
         все) -- клік мишею не залежить від розкладки клавіатури взагалі, тому
         працює завжди, на будь-якій ОС і розкладці.
      2) Прив'язка по event.keycode (апаратний код фізичної клавіші), а не по
         event.keysym (символ, залежний від розкладки) -- Ctrl+V/C/X/A тепер
         спрацьовують незалежно від того, яка розкладка активна. Коди клавіш V/C/X/A
         однакові на Windows (віртуальні коди VK_*) і на X11/Linux (evdev-коди) для
         звичайної розкладки QWERTY-сумісної фізичної клавіатури.
    """
    # --- 1) контекстне меню правої кнопки миші --------------------------------
    menu = tk.Menu(entry, tearoff=0)
    gt.style_menu(menu)
    menu.add_command(label="Вирізати", command=lambda: entry.event_generate("<<Cut>>"))
    menu.add_command(label="Копіювати", command=lambda: entry.event_generate("<<Copy>>"))
    menu.add_command(label="Вставити", command=lambda: entry.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Виділити все", command=lambda: entry.selection_range(0, "end"))

    def _show_context_menu(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    entry.bind("<Button-3>", _show_context_menu)

    # --- 2) Ctrl+V/C/X/A за фізичним кодом клавіші, а не символом розкладки ---
    # 'V','C','X','A' -- віртуальні коди Windows (VK_*) і типові X11/evdev-коди
    # тих самих фізичних клавіш на PC-клавіатурі.
    KEYCODES_PASTE = (86, 118, 47, 55)
    KEYCODES_COPY = (67, 99, 54, 25)
    KEYCODES_CUT = (88, 120, 53, 45)
    KEYCODES_SELECT_ALL = (65, 97, 38, 24)

    def _on_ctrl_key(event):
        kc = event.keycode
        if kc in KEYCODES_PASTE:
            entry.event_generate("<<Paste>>")
            return "break"
        if kc in KEYCODES_COPY:
            entry.event_generate("<<Copy>>")
            return "break"
        if kc in KEYCODES_CUT:
            entry.event_generate("<<Cut>>")
            return "break"
        if kc in KEYCODES_SELECT_ALL:
            entry.selection_range(0, "end")
            return "break"
        return None

    entry.bind("<Control-Key>", _on_ctrl_key)


class QueueWriter:
    """Перехоплює print() з бібліотечного коду (loader/reboot друкують прямо в
    stdout, це нормально для CLI) і жене рядки в чергу для показу у вікні -- без
    цього фонового потоку GUI-текст і бібліотечний текст переплутались би між
    собою, а Tkinter не можна безпечно оновлювати з чужого потоку напряму."""

    def __init__(self, q):
        self.q = q
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf or "\r" in self._buf:
            sep = "\n" if "\n" in self._buf else "\r"
            line, self._buf = self._buf.split(sep, 1)
            line = line.strip()
            if line:
                self.q.put(("log", line))

    def flush(self):
        pass


class FlasherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        gt.apply(self)            # R26 V3: темна тема -- до створення будь-яких віджетів
        self.title("TYT MD-UV390UKR")
        self.geometry("760x560")
        self.minsize(700, 520)
        self._maximize()

        self.queue = queue.Queue()
        self.backend = load_usb_backend()
        self.flashing = False
        self.cps_busy = False   # R24: іде знімок екрана, бекап, перегляд, відновлення або CSV
        self.csv_session = cps_csv.Session()   # R26: «про cp1251 вже попередили» -- один раз за сеанс
        self._cps_on_done = None
        self._cps_fail_suffix = "\n\nФайл не збережено."

        self.donor_path = self._load_saved_donor()
        self.firmware_path = find_bundled_firmware()
        self.build_info = read_build_info()

        self._build_ui()
        self._refresh_donor_label()
        self._refresh_firmware_label()
        self.after(50, self._poll_queue)

    def _maximize(self):
        """R18 Д8: вікно відкривається розгорнутим на весь екран. "zoomed" є лише в Windows/macOS-Tk, на Linux -- атрибут "-zoomed";
        якщо немає ні того, ні іншого -- розмір екрана вручну. Тому обгорнуто в try/except: збій тут не має заважати запуску."""
        try:
            self.state("zoomed")
            return
        except tk.TclError:
            pass
        try:
            self.attributes("-zoomed", True)
            return
        except tk.TclError:
            pass
        try:
            self.geometry("%dx%d+0+0" % (self.winfo_screenwidth(), self.winfo_screenheight()))
        except tk.TclError:
            pass   # лишається звичайний розмір 760x560

    # --- інтерфейс -------------------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        header = ttk.Label(self, text="TYT MD-UV390UKR",
                            font=("Segoe UI", 13, "bold"))
        header.pack(anchor="w", **pad)

        info = ttk.Label(self, text=self.build_info, foreground=gt.P["muted"])
        info.pack(anchor="w", padx=12)

        author = ttk.Label(self, text="Автор: UW5ELK", foreground=gt.P["muted"])
        author.pack(anchor="w", padx=12)

        # --- Крок 1: донор кодека ---
        # Нумерацію кроків прибрано разом із секцією «2. Прошивка»: самотнє «1.»
        # виглядало б так, наче крок загубився.
        donor_frame = ttk.LabelFrame(self, text="Донор кодека AMBE (файл MD9600 V5)")
        donor_frame.pack(fill="x", **pad)

        self.donor_label = ttk.Label(donor_frame, text="", wraplength=500, justify="left")
        self.donor_label.pack(anchor="w", padx=8, pady=(6, 2))

        ttk.Button(donor_frame, text="Обрати файл донора...",
                   command=self._pick_donor).pack(anchor="w", padx=8, pady=(0, 8))

        # --- Крок 2: прошивка ---
        # Коли прошивка вбудована в .exe (штатний випадок для флоту), цієї секції НЕМАЄ
        # зовсім: ні назви файлу, ні кнопки вибору. Оператору нема чого обирати -- шиється
        # рівно та прошивка, що приїхала разом із програмою, і зайвий вибір лише дає шанс
        # залити не те. Секція не пакується взагалі (а не ховається), тож порожнього місця
        # після неї не лишається.
        # Запасний шлях: якщо вбудованої прошивки немає (запуск із джерел) -- секція
        # з'являється, інакше шити було б нічим.
        self.firmware_label = ttk.Label(self, text="", wraplength=500, justify="left")
        if not self.firmware_path:
            fw_frame = ttk.LabelFrame(self, text="Прошивка")
            fw_frame.pack(fill="x", **pad)

            self.firmware_label = ttk.Label(fw_frame, text="", wraplength=500, justify="left")
            self.firmware_label.pack(anchor="w", padx=8, pady=(6, 2))

            ttk.Button(fw_frame, text="Обрати файл прошивки...",
                       command=self._pick_firmware).pack(anchor="w", padx=8, pady=(0, 8))

        # --- Крок 3: прошити ---
        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)

        self.flash_button = ttk.Button(action_frame, text="ПРОШИТИ",
                                       command=self._on_flash_clicked)
        self.flash_button.pack(side="left")

        self.zadig_button = ttk.Button(action_frame, text="Драйвер DFU (Zadig)",
                                       command=lambda: webbrowser.open(ZADIG_URL))
        self.zadig_button.pack(side="left", padx=8)

        self.aes_button = ttk.Button(action_frame, text="Керування AES-ключами...",
                                     command=self._open_aes_key_manager)
        self.aes_button.pack(side="left", padx=8)

        self.rctl_button = ttk.Button(action_frame, text="Віддалене керування (RCTL)...",
                                      command=self._open_rctl_config)
        self.rctl_button.pack(side="left", padx=8)

        # R24: читання з рації. Другий рядок, бо в першому вже чотири кнопки і шість у 700 пікселів не влізуть.
        # Знімок і бекап ЛИШЕ ЧИТАЮТЬ: у рацію нічого не записується. (Третій рядок нижче -- перегляд і відновлення, R25.)
        read_frame = ttk.Frame(self)
        read_frame.pack(fill="x", padx=12, pady=(0, 6))

        self.shot_button = ttk.Button(read_frame, text="Знімок екрана",
                                      command=self._on_screenshot_clicked)
        self.shot_button.pack(side="left")

        self.backup_button = ttk.Button(read_frame, text="Бекап кодплуга",
                                        command=self._on_backup_clicked)
        self.backup_button.pack(side="left", padx=8)

        self.shot_diag_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(read_frame, text="знімок: діагностика (обидва порядки байтів + сирий буфер)",
                        variable=self.shot_diag_var).pack(side="left", padx=8)

        self.full_snapshot_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(read_frame, text="повний знімок (+ голосові підказки і ключі AES)",
                        variable=self.full_snapshot_var).pack(side="left", padx=8)

        # R25: перегляд (лише читання) і відновлення (ПИШЕ в рацію; кнопка вимкнена, доки Богдан не підтвердить BK8).
        view_frame = ttk.Frame(self)
        view_frame.pack(fill="x", padx=12, pady=(0, 6))

        self.view_file_button = ttk.Button(view_frame, text="Переглянути бекап...", command=self._on_view_file_clicked)
        self.view_file_button.pack(side="left")

        self.view_radio_button = ttk.Button(view_frame, text="Переглянути кодплуг з рації", command=self._on_view_radio_clicked)
        self.view_radio_button.pack(side="left", padx=8)

        self.restore_button = ttk.Button(view_frame, text="Відновити кодплуг...", command=self._on_restore_clicked)
        self.restore_button.pack(side="left", padx=8)
        self.restore_note = ttk.Label(view_frame, text="" if cps_rest.RESTORE_UNLOCKED else cps_rest.LOCKED_CAPTION,
                                      foreground=gt.P["warn"])
        self.restore_note.pack(side="left")

        # R26: обмін кодплуга з CSV (формат OpenGD77 CPS). Експорт ЛИШЕ читає; імпорт іде ТІЄЮ САМОЮ дорогою, що й «Відновити кодплуг»
        # (страхова копія -> діалог зі списком змін -> лише відмінні сектори -> перечитування -> SHA-256) і блокується тією ж константою.
        csv_frame = ttk.Frame(self)
        csv_frame.pack(fill="x", padx=12, pady=(0, 6))

        self.csv_export_radio_button = ttk.Button(csv_frame, text="CSV з рації...", command=self._on_csv_export_radio_clicked)
        self.csv_export_radio_button.pack(side="left")

        self.csv_export_file_button = ttk.Button(csv_frame, text="CSV з бекапу...", command=self._on_csv_export_file_clicked)
        self.csv_export_file_button.pack(side="left", padx=8)

        self.csv_import_button = ttk.Button(csv_frame, text="Імпорт CSV у рацію...", command=self._on_csv_import_clicked)
        self.csv_import_button.pack(side="left", padx=8)

        ttk.Label(csv_frame, text="десятковий знак:").pack(side="left", padx=(12, 4))
        self.csv_decimal_var = tk.StringVar(value=self.CSV_DECIMAL_CHOICES[0])
        self.csv_decimal_box = ttk.Combobox(csv_frame, textvariable=self.csv_decimal_var, values=self.CSV_DECIMAL_CHOICES, state="readonly", width=14)
        self.csv_decimal_box.pack(side="left")
        self._refresh_restore_button(True)      # кнопки відновлення й імпорту CSV: вимкнені, доки RESTORE_UNLOCKED == False

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=12, pady=(0, 6))

        self.status_label = ttk.Label(self, text="Готово до роботи.", foreground=gt.P["ok"])
        self.status_label.pack(anchor="w", padx=12)

        # --- журнал ---
        log_frame = ttk.LabelFrame(self, text="Журнал")
        log_frame.pack(fill="both", expand=True, **pad)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, state="disabled",
                                                    font=("Consolas", 9))
        gt.style_text(self.log_text)
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    # --- донор -------------------------------------------------------------

    def _load_saved_donor(self):
        """Читаємо той самий ini-файл, яким користується CLI-прошивальник
        (~/.gd77firmwareloader.ini) -- обраний тут донор одразу бачить і CLI,
        і навпаки, обраний у CLI одразу підхоплюється тут."""
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
            self.donor_label.config(
                text="Донор перевірено: " + self.donor_path, foreground=gt.P["ok"]
            )
        else:
            self.donor_label.config(
                text="Донор не обрано -- прошивка піде тільки в режимі FM, без DMR.",
                foreground=gt.P["warn"],
            )

    # --- прошивка (файл) ----------------------------------------------------

    def _pick_firmware(self):
        path = filedialog.askopenfilename(
            title="Обери файл прошивки (.bin)",
            filetypes=[("Файл прошивки", "*.bin"), ("Усі файли", "*.*")],
        )
        if not path:
            return
        self.firmware_path = path
        self._refresh_firmware_label()

    def _refresh_firmware_label(self):
        if self.firmware_path:
            name = os.path.basename(self.firmware_path)
            bundled = " (вбудована)" if self.firmware_path == find_bundled_firmware() else ""
            self.firmware_label.config(
                text="Прошивка: " + name + bundled, foreground=gt.P["ok"]
            )
        else:
            self.firmware_label.config(
                text="Файл прошивки не знайдено -- обери вручну.", foreground=gt.P["err"]
            )

    # --- лог/прогрес ---------------------------------------------------------

    def _log(self, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "done":
                    self._on_flash_finished(*payload)
                elif kind == "cpsdone":
                    self._on_cps_finished(*payload)
                elif kind == "confirm":
                    self._on_confirm_request(*payload)
                elif kind == "status":
                    self.status_label.config(text=payload, foreground=gt.P["info"])
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    # --- сама прошивка (у фоновому потоці) ------------------------------------

    def _on_flash_clicked(self):
        if self.flashing or self.cps_busy:
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

        self.flashing = True
        self.flash_button.config(state="disabled")
        self.progress["value"] = 0
        self.status_label.config(text="Прошиваю...", foreground=gt.P["info"])
        self._log("=" * 40)
        self._log("Починаю прошивку: " + os.path.basename(self.firmware_path))

        thread = threading.Thread(target=self._flash_worker, daemon=True)
        thread.start()

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
        """Якщо рація ще у звичайному режимі (не в DFU), автоматично переводимо її
        туди самою тільки командою по USB -- так само, як робить окремий
        dmr_reboot_dfu.py. Спрацьовує тільки на збірках з ENABLE_DMR_DATA=1; якщо
        рація вже в DFU (переведена вручну кнопками) або команда не спрацювала --
        нічого страшного, просто повертаємо False і пробуємо підключитись напряму."""
        if serial is None:
            return False

        port = reboot.find_port()
        if not port:
            return False

        self.queue.put(("log", "Рація у звичайному режимі, переводжу в DFU автоматично..."))
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
        old_stdout = sys.stdout
        sys.stdout = QueueWriter(self.queue)
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
                    self.queue.put(("progress", pct))

                loader.patch_and_download_firmware(
                    self.firmware_path, None, loader.FWPlatformOutput.MD_UV380, progress_cb
                )
                ok = True
        except SystemExit as e:
            reason = "exit_{}".format(e.code)
        except Exception as e:  # noqa: BLE001 -- показуємо будь-яку помилку користувачу, не ховаємо
            reason = "exception: {}".format(e)
        finally:
            sys.stdout = old_stdout
            self.queue.put(("done", (ok, reason)))

    # --- R24: знімок екрана і бекап кодплуга (лише читання, звичайний режим рації) -----

    def _cps_output_dir(self):
        d = Path.home() / "MD-UV390UKR"
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def _set_cps_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        for b in (self.shot_button, self.backup_button, self.flash_button, self.view_file_button, self.view_radio_button,
                  self.csv_export_radio_button, self.csv_export_file_button):
            b.config(state=state)
        self._refresh_restore_button(enabled)

    def _refresh_restore_button(self, enabled):
        """W1.11: кнопка відновлення НІКОЛИ не вмикається, доки cps_restore.RESTORE_UNLOCKED == False."""
        self.restore_button.config(state="normal" if (enabled and cps_rest.RESTORE_UNLOCKED) else "disabled")
        self.csv_import_button.config(state="normal" if (enabled and cps_rest.RESTORE_UNLOCKED) else "disabled")      # імпорт = запис = те саме блокування

    def _on_screenshot_clicked(self):
        diag = bool(self.shot_diag_var.get())
        self._run_cps_task(lambda: self._screenshot_worker(diag), "Знімаю екран рації...")

    def _on_backup_clicked(self):
        full = bool(self.full_snapshot_var.get())
        self._run_cps_task(lambda: self._backup_worker(full), "Читаю кодплуг з рації (бекап)...")

    # --- R25: перегляд ---

    def _on_view_file_clicked(self):
        if self.flashing or self.cps_busy:
            return
        path = filedialog.askopenfilename(title="Бекап кодплуга", initialdir=self._cps_output_dir(),
                                          filetypes=[("Бекап кодплуга (.zip)", "*.zip"), ("Усі файли", "*.*")])
        if not path:
            return
        try:
            cp, _manifest = cpview.codeplug_from_backup(path)
        except (OSError, cps.CpsError) as e:
            messagebox.showerror("Помилка", "Не вдалося прочитати бекап:\n{}".format(e))
            return
        codeplug_viewer_gui.CodeplugViewerWindow(self, cp, os.path.basename(path), self._cps_output_dir())

    def _on_view_radio_clicked(self):
        self._run_cps_task(self._view_radio_worker, "Читаю кодплуг з рації для перегляду...",
                           on_done=self._show_viewer_from_radio, fail_suffix="")

    def _view_radio_worker(self):
        ser = cps.open_radio()
        try:
            cp, _manifest = cpview.codeplug_from_radio(cps.CpsLink(ser), self._cps_progress)
        finally:
            ser.close()
        return cp

    def _show_viewer_from_radio(self, cp):
        codeplug_viewer_gui.CodeplugViewerWindow(self, cp, "прямо з рації", self._cps_output_dir(), write_contacts=self._write_contacts)

    # --- R26 V2: запис змін контактів із вікна перегляду ---

    def _write_contacts(self, ops, viewer):
        if self.flashing or self.cps_busy:
            return
        self._edit_viewer = viewer
        self._run_cps_task(lambda: self._write_contacts_worker(ops), "Записую зміни контактів...", on_done=self._contacts_written,
                           fail_suffix="\n\nЯкщо про відмову сказано «Нічого не записано» -- рація не змінена.")

    def _write_contacts_worker(self, ops):
        ser = cps.open_radio()
        try:
            return contact_edit.apply_to_radio(cps.CpsLink(ser), ops, self._confirm_from_worker, self._cps_progress, log=print,
                                               out_dir=self._cps_output_dir())
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001 -- після C 6 1 порт може зникнути
                pass

    def _contacts_written(self, res):
        if res.get("nothingToDo") and not res.get("safetyCopy"):
            messagebox.showinfo("Нічого записувати", "Зміни не відрізняються від того, що вже є в рації.")
            return
        self._restore_done(res)
        if not res.get("cancelled") and getattr(self, "_edit_viewer", None) is not None:
            try:
                self._edit_viewer.destroy()      # знімок застарів: відкрий перегляд ще раз
            except tk.TclError:
                pass
            self._edit_viewer = None

    # --- R26: CSV ---

    CSV_DECIMAL_CHOICES = ("за системою", "кома", "крапка")

    def _csv_decimal(self):
        return {"кома": ",", "крапка": ".", "за системою": None}.get(self.csv_decimal_var.get())

    def _csv_new_export_dir(self, parent_dir):
        name = cps.timestamp_name("codeplug_csv", "")
        return cps.unique_path(parent_dir, name)

    def _on_csv_export_radio_clicked(self):
        if self.flashing or self.cps_busy:
            return
        parent_dir = filedialog.askdirectory(title="Куди покласти теку з CSV", initialdir=self._cps_output_dir())
        if not parent_dir:
            return
        out = self._csv_new_export_dir(parent_dir)
        dp = self._csv_decimal()
        self._run_cps_task(lambda: self._csv_export_radio_worker(out, dp), "Читаю кодплуг з рації для CSV...",
                           on_done=self._csv_export_done, fail_suffix="\n\nФайли CSV не створено.")

    def _csv_export_radio_worker(self, out, dp):
        ser = cps.open_radio()
        try:
            return cps_csv.export_from_radio(cps.CpsLink(ser), out, dp, progress=self._cps_progress, log=print)
        finally:
            ser.close()

    def _on_csv_export_file_clicked(self):
        if self.flashing or self.cps_busy:
            return
        path = filedialog.askopenfilename(title="Бекап кодплуга", initialdir=self._cps_output_dir(),
                                          filetypes=[("Бекап кодплуга (.zip)", "*.zip"), ("Усі файли", "*.*")])
        if not path:
            return
        parent_dir = filedialog.askdirectory(title="Куди покласти теку з CSV", initialdir=os.path.dirname(path))
        if not parent_dir:
            return
        out = self._csv_new_export_dir(parent_dir)
        dp = self._csv_decimal()
        self._run_cps_task(lambda: cps_csv.export_from_backup(path, out, dp, log=print), "Експортую бекап у CSV...",
                           on_done=self._csv_export_done, fail_suffix="\n\nФайли CSV не створено.")

    def _csv_export_done(self, paths):
        folder = os.path.dirname(paths[0]) if paths else "?"
        messagebox.showinfo("CSV створено", "Шість файлів CSV (формат OpenGD77 CPS + додаткова колонка «Name (readable)»):\n{}".format(folder))

    def _on_csv_import_clicked(self):
        if self.flashing or self.cps_busy or not cps_rest.RESTORE_UNLOCKED:
            return
        folder = filedialog.askdirectory(title="Тека з CSV (Channels.csv, Contacts.csv, ...)", initialdir=self._cps_output_dir())
        if not folder:
            return
        dp = self._csv_decimal()
        self._run_cps_task(lambda: self._csv_import_worker(folder, dp), "Імпортую CSV у рацію...", on_done=self._csv_import_done,
                           fail_suffix="\n\nЯкщо про відмову сказано «Нічого не записано» -- рація не змінена.")

    def _csv_import_worker(self, folder, dp):
        ser = cps.open_radio()
        try:
            return cps_csv.import_to_radio(cps.CpsLink(ser), folder, self._confirm_from_worker, self._cps_progress, log=print,
                                           session=self.csv_session, dp=dp, out_dir=self._cps_output_dir())
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001 -- після C 6 1 порт може зникнути
                pass

    def _csv_import_done(self, res):
        if res.get("nothingToDo") and not res.get("safetyCopy"):
            messagebox.showinfo("Нічого імпортувати", "CSV не відрізняється від кодплуга рації. Записувати нічого.")
            return
        self._restore_done(res)

    # --- R25: відновлення (ЗАПИС у рацію) ---

    def _on_restore_clicked(self):
        if self.flashing or self.cps_busy or not cps_rest.RESTORE_UNLOCKED:
            return
        path = filedialog.askopenfilename(title="Бекап, з якого відновити кодплуг", initialdir=self._cps_output_dir(),
                                          filetypes=[("Бекап кодплуга (.zip)", "*.zip")])
        if not path:
            return
        self._run_cps_task(lambda: self._restore_worker(path), "Відновлюю кодплуг...", on_done=self._restore_done,
                           fail_suffix="\n\nСтан рації описано вище. Не вимикай програму, поки не прочитаєш повідомлення.")

    def _restore_worker(self, path):
        ser = cps.open_radio()
        try:
            return cps_rest.restore_codeplug(cps.CpsLink(ser), path, self._confirm_from_worker, self._cps_progress, log=print)
        finally:
            try:
                ser.close()
            except Exception:  # noqa: BLE001 -- рація після C 6 1 перезавантажується, порт може зникнути
                pass

    def _confirm_from_worker(self, text, _plan):
        """Викликається з робочого потоку: питання показує головний потік, цей потік чекає на відповідь."""
        done = threading.Event()
        answer = {"yes": False}
        self.queue.put(("confirm", (text, done, answer)))
        done.wait()
        return answer["yes"]

    def _on_confirm_request(self, text, done, answer):
        answer["yes"] = bool(gd.confirm_dialog(self, "Підтвердження запису в рацію", text, yes="Записати в рацію", no="Скасувати"))
        done.set()

    def _restore_done(self, res):
        if res.get("cancelled"):
            messagebox.showinfo("Скасовано", "Рацію не змінено.\nСтрахова копія лишилась:\n{}".format(res["safetyCopy"]))
        elif res.get("nothingToDo"):
            messagebox.showinfo("Нічого відновлювати", "Рація вже містить цей кодплуг (крім калібрування й квіккеїв).\n"
                                                       "Страхова копія:\n{}".format(res["safetyCopy"]))
        else:
            what = "Зміни записано й перевірено" if res.get("report") is not None else "Кодплуг відновлено й перевірено"
            messagebox.showinfo("Готово", "{} (записано секторів: {} з {}, {} с).\n"
                                          "Рація перезавантажується.\n\nСтрахова копія стану ДО запису:\n{}".format(
                                              what, res["sectorsWritten"], res["sectorsTotal"], res["seconds"], res["safetyCopy"]))

    def _run_cps_task(self, fn, status_text, on_done=None, fail_suffix="\n\nФайл не збережено."):
        if self.flashing or self.cps_busy:
            return
        self._cps_on_done = on_done
        self._cps_fail_suffix = fail_suffix
        self.cps_busy = True
        self._set_cps_buttons(False)
        self.progress["value"] = 0
        self.status_label.config(text=status_text, foreground=gt.P["info"])
        self._log("=" * 30)
        self._log(status_text)

        def worker():
            old_stdout = sys.stdout
            sys.stdout = QueueWriter(self.queue)
            ok, reason, result = False, None, None
            try:
                result = fn()
                ok = True
            except cps.CpsError as e:
                reason = str(e)
            except Exception as e:  # noqa: BLE001 -- показуємо будь-яку помилку, не ховаємо
                reason = "несподівана помилка: {}".format(e)
            finally:
                sys.stdout = old_stdout
                self.queue.put(("cpsdone", (ok, reason, result)))

        threading.Thread(target=worker, daemon=True).start()

    def _cps_progress(self, pct, text):
        self.queue.put(("progress", pct))
        self.queue.put(("status", text))

    def _screenshot_worker(self, diagnostic):
        ser = cps.open_radio()
        try:
            # ВАЖЛИВО: команду "C",0 (екран CPS) тут НЕ надсилаємо -- знімок мав би показати поточний екран рації, а не екран CPS.
            paths = cps.take_screenshot(cps.CpsLink(ser), self._cps_output_dir(), diagnostic=diagnostic,
                                        progress=lambda d, t: self.queue.put(("progress", int(100.0 * d / t))))
        finally:
            ser.close()
        for p in paths:
            print("Збережено: {}".format(p))
        return paths

    def _backup_worker(self, full_snapshot=False):
        ser = cps.open_radio()
        try:
            data, manifest = cps.backup_codeplug(cps.CpsLink(ser), self._cps_progress, full_snapshot=full_snapshot)
        finally:
            ser.close()
        path = cps.unique_path(self._cps_output_dir(), cps.timestamp_name("codeplug_backup", ".zip"))
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

    def _on_cps_finished(self, ok, reason, result):
        self.cps_busy = False
        self._set_cps_buttons(True)
        on_done, self._cps_on_done = self._cps_on_done, None
        if ok:
            self.progress["value"] = 100
            self.status_label.config(text="Готово.", foreground=gt.P["ok"])
            if on_done is not None:
                on_done(result)
            else:
                messagebox.showinfo("Готово", "Збережено:\n" + "\n".join(result or []))
        else:
            self.status_label.config(text="Не вдалося.", foreground=gt.P["err"])
            self._log("!!! Помилка: {}".format(reason))
            full = "{}{}".format(reason, self._cps_fail_suffix)
            if full.count("\n") > 8 or len(full) > 700:          # довгий перелік проблем імпорту -- у темному вікні з прокруткою
                gd.text_dialog(self, "Помилка", full)
            else:
                messagebox.showerror("Помилка", full)

    # --- AES-ключі (окреме вікно -- інший стан USB, рація НЕ в DFU) -----------

    def _open_aes_key_manager(self):
        AesKeyManagerWindow(self)

    def _open_rctl_config(self):
        RctlConfigWindow(self)

    def _on_flash_finished(self, ok, reason):
        self.flashing = False
        self.flash_button.config(state="normal")

        if ok:
            self.progress["value"] = 100
            self.status_label.config(text="Готово! Можна від'єднати USB.", foreground=gt.P["ok"])
            self._log("*** Готово.")
            messagebox.showinfo("Готово", "Прошивку завершено. Можна від'єднати USB і "
                                           "увімкнути рацію звичайним способом.")
            return

        self.status_label.config(text="Не вдалося прошити.", foreground=gt.P["err"])

        if reason == "no_dfu":
            self._log("!!! Рацію не знайдено в режимі DFU.")
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
            self._log("!!! Помилка: {}".format(reason))
            messagebox.showerror("Помилка прошивки", "Щось пішло не так: {}\n\n"
                                  "Подробиці -- у журналі внизу вікна.".format(reason))


class AesKeyManagerWindow(tk.Toplevel):
    """Окреме вікно для додавання/видалення AES-256 ключів шифрування голосу.

    ІНША фізична фаза USB, ніж прошивка: рація тут має бути у ЗВИЧАЙНОМУ
    робочому режимі (VID:PID 1fc9:0094, той самий CPS-протокол, яким
    користується офіційна CPS-програма) -- НЕ в DFU-завантажувачі. Тому це
    окреме вікно, а не ще один розділ у вікні прошивки: змішувати два різні
    очікувані стани рації в одному екрані тільки б плутало користувача.

    Ключі зберігаються у форматі стокової таблиці TYT (не в кастомних даних
    OpenGD77) -- див. tools/stock_key_table.py й коментар при
    STOCK_KEY_TABLE_BASE у dmr_aes_hook.c. Сам протокольний код читання/запису
    флеш (flash_read/flash_write_block/find_port) береться з aes_key_store.py
    як є -- нічого не дублюється."""

    def __init__(self, parent):
        super().__init__(parent)
        gt.style_window(self)
        self.title("TYT MD-UV390UKR -- AES-ключі шифрування")
        self.geometry("480x520")
        self.minsize(440, 460)

        self.queue = queue.Queue()
        self.busy = False

        self._build_ui()
        self.after(50, self._poll_queue)

    # --- інтерфейс -------------------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        note = ttk.Label(
            self,
            text=("Рація має бути УВІМКНЕНА У ЗВИЧАЙНОМУ РЕЖИМІ (не в DFU!). "
                  "Матеріал ключа ніде на екрані не показується -- лише факт "
                  "\"зайнято/порожньо\"."),
            wraplength=440, justify="left", foreground=gt.P["warn"],
        )
        note.pack(anchor="w", **pad)

        key_frame = ttk.LabelFrame(self, text="Слот ключа (1..15)")
        key_frame.pack(fill="x", **pad)

        row1 = ttk.Frame(key_frame)
        row1.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(row1, text="ID ключа:").pack(side="left")
        self.keyid_var = tk.IntVar(value=1)
        ttk.Spinbox(row1, from_=1, to=15, width=4, textvariable=self.keyid_var).pack(side="left", padx=6)

        row2 = ttk.Frame(key_frame)
        row2.pack(fill="x", padx=8, pady=2)
        ttk.Label(row2, text="Ключ (64 hex):").pack(side="left")
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(row2, textvariable=self.key_var, width=40, font=("Consolas", 9))
        self.key_entry.pack(side="left", padx=6, fill="x", expand=True)
        # Явно вмикаємо вставку/копіювання -- інакше на Windows з українською
        # розкладкою клавіатури Ctrl+V у це поле не спрацьовує (див. докладний
        # коментар при enable_entry_clipboard() вище).
        enable_entry_clipboard(self.key_entry)

        self.show_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(key_frame, text="показувати введений ключ", variable=self.show_var,
                        command=self._toggle_key_visibility).pack(anchor="w", padx=8)

        row3 = ttk.Frame(key_frame)
        row3.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Button(row3, text="Записати ключ", command=self._on_write_key).pack(side="left")
        ttk.Button(row3, text="Очистити ключ", command=self._on_clear_key).pack(side="left", padx=8)

        tx_frame = ttk.LabelFrame(self, text="Активний ключ для передачі (TX)")
        tx_frame.pack(fill="x", **pad)
        row4 = ttk.Frame(tx_frame)
        row4.pack(fill="x", padx=8, pady=8)
        ttk.Label(row4, text="TX-ключ (0 = вимк.):").pack(side="left")
        self.txkey_var = tk.IntVar(value=0)
        ttk.Spinbox(row4, from_=0, to=15, width=4, textvariable=self.txkey_var).pack(side="left", padx=6)
        ttk.Button(row4, text="Встановити", command=self._on_set_tx_key).pack(side="left", padx=8)

        ttk.Button(self, text="Оновити список зайнятих слотів",
                  command=self._on_refresh_slots).pack(anchor="w", padx=12)

        self.status_label = ttk.Label(self, text="Готово.", foreground=gt.P["ok"])
        self.status_label.pack(anchor="w", padx=12, pady=(4, 0))

        log_frame = ttk.LabelFrame(self, text="Журнал")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, state="disabled",
                                                    font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    def _toggle_key_visibility(self):
        self.key_entry.config(show="" if self.show_var.get() else "*")

    # --- лог/прогрес ---------------------------------------------------------

    def _log(self, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self._on_worker_finished(*payload)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    # --- валідація вводу -------------------------------------------------------

    def _read_key32(self):
        text = self.key_var.get().strip().replace(" ", "")
        try:
            key = bytes.fromhex(text)
        except ValueError:
            messagebox.showerror("Невірний ключ", "Ключ має бути рядком із 64 шістнадцяткових символів (0-9, A-F).")
            return None
        if len(key) != 32:
            messagebox.showerror("Невірний ключ", "Ключ має бути рівно 64 hex-символи (32 байти), зараз {}.".format(len(text)))
            return None
        return key

    # --- дії користувача ---------------------------------------------------------

    def _on_write_key(self):
        if self.busy:
            return
        key32 = self._read_key32()
        if key32 is None:
            return
        key_id = self.keyid_var.get()
        if not messagebox.askokcancel(
            "Записати ключ?",
            "Записати ключ у слот {} на рації?\n\n"
            "Переконайся, що рація увімкнена у ЗВИЧАЙНОМУ режимі (не в DFU).".format(key_id),
        ):
            return
        self._run_worker(lambda: self._write_key_worker(key_id, key32),
                         "Записую ключ {}...".format(key_id))

    def _on_clear_key(self):
        if self.busy:
            return
        key_id = self.keyid_var.get()
        if not messagebox.askokcancel(
            "Очистити ключ?",
            "Стерти ключ у слоті {} на рації? Цю дію не можна скасувати.".format(key_id),
        ):
            return
        self._run_worker(lambda: self._clear_key_worker(key_id),
                         "Очищую ключ {}...".format(key_id))

    def _on_set_tx_key(self):
        if self.busy:
            return
        tx_id = self.txkey_var.get()
        self._run_worker(lambda: self._set_tx_key_worker(tx_id),
                         "Встановлюю активний TX-ключ = {}...".format(tx_id))

    def _on_refresh_slots(self):
        if self.busy:
            return
        self._run_worker(self._refresh_slots_worker, "Читаю зайняті слоти...")

    # --- фонові операції (у потоці) ------------------------------------------------

    def _connect(self):
        port = aes_key_store.find_port()
        if not port:
            raise RuntimeError(
                "рацію не знайдено у звичайному режимі (VID:PID 1fc9:0094). "
                "Переконайся, що вона увімкнена звичайним способом (НЕ в DFU) і кабель підключено."
            )
        ser = serial.Serial(port, 115200, timeout=0.6)
        aes_key_store.show_cps(ser)
        return ser

    def _write_key_worker(self, key_id, key32):
        with self._connect() as ser:
            addr = skt.entry_addr(key_id)
            existing = aes_key_store.flash_read(ser, addr, skt.STOCK_KEY_ENTRY_LEN)
            entry = skt.build_entry(key_id, key32, existing_entry100=existing if len(existing) == skt.STOCK_KEY_ENTRY_LEN else None)
            aes_key_store.flash_write_block(ser, addr, entry)
            readback = aes_key_store.flash_read(ser, addr, skt.STOCK_KEY_ENTRY_LEN)
            ok = (readback == entry)
            print("Ключ {}: записано, звірка {}.".format(key_id, "OK" if ok else "НЕЗБІГ (спробуй ще раз)"))

    def _clear_key_worker(self, key_id):
        with self._connect() as ser:
            addr = skt.entry_addr(key_id)
            existing = aes_key_store.flash_read(ser, addr, skt.STOCK_KEY_ENTRY_LEN)
            entry = skt.build_entry(key_id, skt.BLANK_KEY, existing_entry100=existing if len(existing) == skt.STOCK_KEY_ENTRY_LEN else None)
            aes_key_store.flash_write_block(ser, addr, entry)
            print("Ключ {}: очищено (позначено як порожній слот).".format(key_id))

    def _set_tx_key_worker(self, tx_id):
        with self._connect() as ser:
            payload = cd.read_block(ser, aes_key_store.TYPE_AES_KEYS, aes_key_store.AESK_BLOCK_LEN)
            payload = bytearray(payload) if payload else aes_key_store.fresh_payload()
            if payload[:4] != b"AESK":
                payload = bytearray(aes_key_store.fresh_payload())
            payload[5] = tx_id & 0xFF

            ok, msg = cd.write_block(ser, aes_key_store.TYPE_AES_KEYS, bytes(payload))
            if not ok:
                raise RuntimeError(msg)
            print("Активний TX-ключ встановлено: {}.".format(tx_id if tx_id else "вимкнено (0)"))

    def _refresh_slots_worker(self):
        with self._connect() as ser:
            occupied = []
            for key_id in range(skt.STOCK_KEY_MIN_ID, skt.STOCK_KEY_MAX_ID + 1):
                entry = aes_key_store.flash_read(ser, skt.entry_addr(key_id), skt.STOCK_KEY_ENTRY_LEN)
                if len(entry) != skt.STOCK_KEY_ENTRY_LEN:
                    continue
                entry_type, _name, wrapped = skt.parse_entry(entry)
                if entry_type in (skt.STOCK_KEY_TYPE_AES256, skt.STOCK_KEY_TYPE_AES256B):
                    if skt.is_key_present(skt.unwrap_key(wrapped)):
                        occupied.append(key_id)

            payload = cd.read_block(ser, aes_key_store.TYPE_AES_KEYS, aes_key_store.AESK_BLOCK_LEN)
            tx_id = payload[5] if payload else 0

            empty = [i for i in range(skt.STOCK_KEY_MIN_ID, skt.STOCK_KEY_MAX_ID + 1) if i not in occupied]
            print("Зайняті слоти: {}".format(", ".join(map(str, occupied)) if occupied else "немає"))
            print("Порожні слоти: {}".format(", ".join(map(str, empty)) if empty else "немає"))
            print("Активний TX-ключ: {}".format(tx_id if tx_id else "вимкнено (0)"))

    def _run_worker(self, fn, status_text):
        self.busy = True
        self.status_label.config(text=status_text, foreground=gt.P["info"])
        self._log("=" * 30)
        self._log(status_text)

        def worker():
            old_stdout = sys.stdout
            sys.stdout = QueueWriter(self.queue)
            ok, reason = False, None
            try:
                fn()
                ok = True
            except Exception as e:  # noqa: BLE001 -- показуємо будь-яку помилку, не ховаємо
                reason = str(e)
            finally:
                sys.stdout = old_stdout
                self.queue.put(("done", (ok, reason)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_worker_finished(self, ok, reason):
        self.busy = False
        if ok:
            self.status_label.config(text="Готово.", foreground=gt.P["ok"])
        else:
            self.status_label.config(text="Помилка.", foreground=gt.P["err"])
            self._log("!!! Помилка: {}".format(reason))
            messagebox.showerror("Помилка", "Щось пішло не так: {}".format(reason))


class RctlConfigWindow(tk.Toplevel):
    """Дозволи «приймати команди віддаленого керування» (RCTL --
    functions/dmr_rctl_cfg.c). Пише блок "RCTL" у custom-data (CHIRP-стиль:
    прошивка лише читає, сама не пише).

    Модель довіри (2026-09-03, за зразком Motorola/Hytera): жодного окремого списку
    довірених ID -- сам канальний AES-ключ (той самий, що голос/SMS) є межею довіри.

    2026-09-18: окремого перемикача «enabled» більше немає. Єдина точка правди --
    які САМЕ команди дозволені (по чекбоксу на тип: Ввімкнення/Перевірка/Моніторинг/
    Вимкнення). enabled похідний: позначено хоч одну -> RCTL увімкнено; жодної ->
    вимкнено. build_payload() виставляє байт enabled сам, тож поля у флеші не можуть
    розійтися (раніше саме це давало «у прошивальнику Off, у меню все On»).

    Окремо -- чекбокс видимості пункту «Доступ RCTL» в меню Опцій рації (це вигляд,
    не дозволи: гейт дозволів діє незалежно від того, чи видно пункт).

    ВАЖЛИВО: це вікно НЕ надсилає саму команду Radio Check в ефір -- команда йде
    рація-рації по DMR, а не через USB/CPS. Тут лише налаштовуються дозволи (fail
    closed: порожня маска = вимкнено, доки не позначено явно)."""

    def __init__(self, parent):
        super().__init__(parent)
        gt.style_window(self)
        self.title("TYT MD-UV390UKR -- Віддалене керування (RCTL)")
        self.geometry("480x500")
        self.minsize(440, 460)

        self.queue = queue.Queue()
        self.busy = False

        self._build_ui()
        self.after(50, self._poll_queue)

    def _build_ui(self):
        pad = {"padx": 12, "pady": 6}

        note = ttk.Label(
            self,
            text=("Познач, які САМЕ команди ця рація прийматиме від БУДЬ-КОГО, хто знає "
                  "ключ шифрування каналу (як у Motorola/Hytera -- окремого списку ID "
                  "немає). Жодної позначки = RCTL вимкнено (рація не приймає нічого). "
                  "Окремого перемикача «увімкнено» більше немає: увімкнено = дозволена "
                  "хоч одна команда. Рація має бути УВІМКНЕНА У ЗВИЧАЙНОМУ РЕЖИМІ (не в DFU)."),
            wraplength=440, justify="left", foreground=gt.P["warn"],
        )
        note.pack(anchor="w", **pad)

        # 2026-09-18: замість одного «enabled» -- по чекбоксу на КОЖЕН тип команди, тими ж
        # назвами, що й у меню рації «Доступ RCTL». enabled = (позначено хоч одну) -- пише
        # rctl_config.build_payload() сам. Порядок за вимогою: Ввімкнення, Перевірка,
        # Моніторинг, Вимкнення.
        cmd_frame = ttk.LabelFrame(self, text="Дозволені команди")
        cmd_frame.pack(fill="x", padx=12, pady=(4, 0))
        self.cmd_vars = {}
        RCTL_CMDS = [
            ("revive",  "Ввімкнення", rctl.ALLOW_REVIVE),
            ("check",   "Перевірка",  rctl.ALLOW_CHECK),
            ("monitor", "Моніторинг", rctl.ALLOW_MONITOR),
            ("stun",    "Вимкнення",  rctl.ALLOW_STUN),
        ]
        self._rctl_cmd_bits = {key: bit for key, _lbl, bit in RCTL_CMDS}
        for key, label, _bit in RCTL_CMDS:
            v = tk.BooleanVar(value=False)
            self.cmd_vars[key] = v
            ttk.Checkbutton(cmd_frame, text=label, variable=v).pack(anchor="w", padx=8, pady=1)

        self.menu_visible_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Показувати пункт «Доступ RCTL» в меню Опцій на рації",
                        variable=self.menu_visible_var).pack(anchor="w", padx=12, pady=(4, 0))
        ttk.Label(
            self,
            text=("Лише вигляд: сховати пункт можна, щоб боєць не міг сам собі вимкнути "
                  "приймання команд у полі. Дозволи (checkbox вище) працюють незалежно "
                  "від видимості пункту."),
            wraplength=440, justify="left", foreground=gt.P["muted"],
        ).pack(anchor="w", padx=12, pady=(0, 0))

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", **pad)
        ttk.Button(btn_row, text="Прочитати поточний стан", command=self._on_read).pack(side="left")
        ttk.Button(btn_row, text="Записати на рацію", command=self._on_write).pack(side="left", padx=8)

        self.status_label = ttk.Label(self, text="Натисни «Прочитати поточний стан».", foreground=gt.P["info"])
        self.status_label.pack(anchor="w", padx=12, pady=(4, 0))

        log_frame = ttk.LabelFrame(self, text="Журнал")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, state="disabled",
                                                    font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    # --- лог/прогрес -------------------------------------------------------------

    def _log(self, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "state":
                    self._apply_state(payload)
                elif kind == "done":
                    self._on_worker_finished(*payload)
        except queue.Empty:
            pass
        self.after(50, self._poll_queue)

    def _apply_state(self, state):
        # Показуємо ЕФЕКТИВНУ маску (state["allow"]): на legacy-рації, де enabled=0 при
        # ненульовій сирій масці, галочки будуть зняті -- і запис нормалізує до чесного
        # вимкненого стану, не воскрешаючи прихований дозвіл.
        allow = state.get("allow", 0)
        for key, bit in self._rctl_cmd_bits.items():
            self.cmd_vars[key].set(bool(allow & bit))
        self.menu_visible_var.set(not state.get("menu_hidden", False))

    def _selected_mask(self):
        mask = 0
        for key, bit in self._rctl_cmd_bits.items():
            if self.cmd_vars[key].get():
                mask |= bit
        return mask

    # --- дії користувача -----------------------------------------------------------

    def _on_read(self):
        if self.busy:
            return
        self._run_worker(self._read_worker, "Читаю поточний стан...")

    def _on_write(self):
        if self.busy:
            return
        mask = self._selected_mask()
        menu_hidden = not self.menu_visible_var.get()
        if mask:
            if not messagebox.askokcancel(
                "Увімкнути RCTL?",
                "Ця рація прийматиме позначені команди віддаленого керування від "
                "БУДЬ-КОГО, хто знає ключ шифрування каналу -- без окремого списку "
                "довірених ID (як у Motorola/Hytera). Продовжити?",
            ):
                return
        if menu_hidden:
            if not messagebox.askokcancel(
                "Сховати пункт меню?",
                "Пункт «Доступ RCTL» зникне з меню Опцій на рації -- боєць не зможе сам "
                "собі увімкнути/вимкнути приймання команд у полі. Повернути видимість "
                "можна лише звідси, з прошивальника. Продовжити?",
            ):
                return
        self._run_worker(lambda: self._write_worker(mask, menu_hidden), "Записую...")

    # --- фонові операції -----------------------------------------------------------

    def _connect(self):
        port = aes_key_store.find_port()
        if not port:
            raise RuntimeError(
                "рацію не знайдено у звичайному режимі (VID:PID 1fc9:0094). "
                "Переконайся, що вона увімкнена звичайним способом (НЕ в DFU) і кабель підключено."
            )
        ser = serial.Serial(port, 115200, timeout=0.6)
        aes_key_store.show_cps(ser)
        return ser

    def _read_worker(self):
        with self._connect() as ser:
            payload = cd.read_block(ser, rctl.TYPE_RCTL_CONFIG, rctl.PAYLOAD_LEN)
            state = rctl.parse_payload(payload) if payload else {
                "version": rctl.VERSION, "enabled": False, "allow": 0,
                "menu_hidden": False, "monitor_secs": 0,
            }
            self.queue.put(("state", state))
            names = [n for n, b in rctl.ALLOW_NAMES if state.get("allow", 0) & b] or ["-"]
            print("Стан: RCTL={}, дозволи=[{}], пункт меню={}".format(
                "увімкнено" if state.get("allow") else "вимкнено",
                ",".join(names),
                "схований" if state.get("menu_hidden") else "видимий"))

    def _write_worker(self, mask, menu_hidden):
        with self._connect() as ser:
            # monitor_secs -- зберігаємо те, що вже є на рації (тривалістю Monitor це вікно
            # не керує: rctl_config.py, за потреби). enabled НЕ пишемо окремо -- він похідний
            # від маски (build_payload виставляє його сам). Маска -- єдина точка правди.
            current = cd.read_block(ser, rctl.TYPE_RCTL_CONFIG, rctl.PAYLOAD_LEN)
            cur = rctl.parse_payload(current) if current else None
            monitor_secs = cur["monitor_secs"] if cur else 0

            payload = rctl.build_payload(mask, monitor_secs, menu_hidden)
            ok, msg = cd.write_block(ser, rctl.TYPE_RCTL_CONFIG, payload)
            if not ok:
                raise RuntimeError(msg)
            rb = cd.read_block(ser, rctl.TYPE_RCTL_CONFIG, rctl.PAYLOAD_LEN)
            verify_ok = (rb == payload)
            names = [n for n, b in rctl.ALLOW_NAMES if mask & b] or ["-"]
            print("Записано ({}), RCTL={}, дозволи=[{}], пункт меню={}. Звірка читанням: {}.".format(
                msg, "увімкнено" if mask else "вимкнено", ",".join(names),
                "схований" if menu_hidden else "видимий",
                "OK" if verify_ok else "НЕЗБІГ"))

    def _run_worker(self, fn, status_text):
        self.busy = True
        self.status_label.config(text=status_text, foreground=gt.P["info"])
        self._log("=" * 30)
        self._log(status_text)

        def worker():
            old_stdout = sys.stdout
            sys.stdout = QueueWriter(self.queue)
            ok, reason = False, None
            try:
                fn()
                ok = True
            except Exception as e:  # noqa: BLE001
                reason = str(e)
            finally:
                sys.stdout = old_stdout
                self.queue.put(("done", (ok, reason)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_worker_finished(self, ok, reason):
        self.busy = False
        if ok:
            self.status_label.config(text="Готово.", foreground=gt.P["ok"])
        else:
            self.status_label.config(text="Помилка.", foreground=gt.P["err"])
            self._log("!!! Помилка: {}".format(reason))
            messagebox.showerror("Помилка", "Щось пішло не так: {}".format(reason))


def main():
    try:
        app = FlasherApp()
        app.mainloop()
    except Exception as e:  # noqa: BLE001 -- останній рубіж: показати хоч щось, а не мовчки згаснути
        import traceback
        detail = traceback.format_exc()
        try:
            messagebox.showerror("Помилка запуску", "{}\n\n{}".format(e, detail))
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0, "{}\n\n{}".format(e, detail), "TYT MD-UV390UKR -- Помилка запуску", 0x10
                )
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
