# -*- coding: utf-8 -*-
"""Спільні дрібниці CPS-оболонки. Нічого протокольного тут немає -- код перенесено з gui_flasher.py без змін логіки."""
import glob
import os
import sys
from pathlib import Path

import tkinter as tk

import gui_theme as gt

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
    """Вмикає копіювання/вставляння/вирізання в текстовому полі Tkinter так, щоб воно ГАРАНТОВАНО працювало на Windows з
    українською (чи будь-якою нелатинською) розкладкою клавіатури.

    Проблема, яку це виправляє: стандартні прив'язки Ctrl+C/Ctrl+V у Tk на Windows спрацьовують за КОДОМ СИМВОЛУ, який дає
    поточна розкладка для фізичної клавіші -- а не за самою фізичною клавішею. З українською розкладкою фізична клавіша «V»
    видає не 'v', а кирилицю («м»), тому Ctrl+V не розпізнається як вставляння і поле здається «заблокованим для вставки».
    Пункту контекстного меню (по правій кнопці миші) в ttk.Entry також немає за замовчуванням.

    Рішення -- два незалежні шляхи:
      1) контекстне меню правої кнопки миші (Вирізати/Копіювати/Вставити/Виділити все) -- клік не залежить від розкладки;
      2) прив'язка по event.keycode (апаратний код фізичної клавіші), а не по event.keysym: Ctrl+V/C/X/A спрацьовують
         незалежно від розкладки. Коди клавіш однакові на Windows (VK_*) і на X11/Linux (evdev) для QWERTY-сумісної клавіатури.
    """
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
