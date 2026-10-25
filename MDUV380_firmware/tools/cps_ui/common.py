# -*- coding: utf-8 -*-
"""Спільні дрібниці CPS-оболонки. Нічого протокольного тут немає -- код перенесено з gui_flasher.py без змін логіки."""
import glob
import os
import sys
from pathlib import Path

CONFIG_FILENAME = str(Path.home() / ".gd77firmwareloader.ini")
ZADIG_URL = "https://zadig.akeo.ie/"
APP_TITLE = "TYT MD-UV390UKR"


def resource_path(name):
    """Шлях до файлу, вбудованого поруч зі скомпільованим .exe (PyInstaller кладе їх у тимчасову теку sys._MEIPASS), або в теці
    tools/ при запуску з джерела (для розробки/тестування без збірки .exe). Пакет cps_ui лежить на рівень глибше за tools/."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, name)


def load_usb_backend():
    """У .exe не можна покладатись на автопошук libusb-1.0.dll (немає «сусіднього python.exe в PATH», як при ручному запуску) --
    підключаємо вбудовану копію явно. Якщо запущено з джерела і dll поруч немає -- повертаємо None, pyusb сам спробує знайти
    системну бібліотеку (як завжди)."""
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
    """Короткий підпис збірки (коміт+дата), якщо CI його поклав поруч. Використовуй цей рядок у звітах про проблеми -- він каже,
    ЯКУ саме збірку тестували."""
    path = resource_path("build_info.txt")
    if os.path.isfile(path):
        try:
            info = open(path, encoding="utf-8").read().strip()
            # Назву форка у вікні не показуємо -- лишаємо тільки коміт і дату. Чистимо ТУТ, а не лише в CI: у вже зібраних .exe
            # лежить старий build_info.txt із префіксом, і без цієї обрізки він показувався б і далі.
            for prefix in ("OpenGD77-AES256-fork,", "OpenGD77-AES256-fork"):
                if info.startswith(prefix):
                    info = info[len(prefix):].lstrip(" ,")
                    break
            return info
        except OSError:
            pass
    return "збірка з джерела (без build_info.txt)"


def output_dir():
    """Тека для знімків, бекапів і страхових копій: ~/MD-UV390UKR (створюється за потреби)."""
    d = Path.home() / "MD-UV390UKR"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def enable_entry_clipboard(entry):
    """Сумісність зі старими викликами. З R36 копіювання/вставляння/вирізання за КОДОМ фізичної клавіші (незалежно від розкладки) і контекстне
    меню працюють для ВСІХ полів і таблиць разом: одна глобальна прив'язка на класи віджетів (gui_clipboard.py). Тут лише гарантуємо, що вона
    ввімкнена (повторний виклик нічого не робить), -- окремих прив'язок на поле більше нема, щоб меню й дії не спрацьовували двічі."""
    import gui_clipboard
    gui_clipboard.install(entry)


class QueueWriter:
    """Перехоплює print() з бібліотечного коду (loader/reboot друкують прямо в stdout, це нормально для CLI) і жене рядки в чергу
    для показу у вікні -- без цього фонового потоку GUI-текст і бібліотечний текст переплутались би між собою, а Tkinter не можна
    безпечно оновлювати з чужого потоку напряму."""

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
