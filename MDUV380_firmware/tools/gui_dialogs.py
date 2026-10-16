#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gui_dialogs.py -- R26 V3: темні діалоги з прокруткою. Замінюють messagebox там, де текст довгий (підтвердження запису зі
списком змін, перелік проблем імпорту CSV): системний messagebox і тема не дружать, і довгий текст у ньому не прокручується.

Усі функції викликаються ЛИШЕ з головного потоку Tk. Модальні: чекають закриття вікна."""
import tkinter as tk
from tkinter import ttk, scrolledtext

import gui_theme as gt


def _build(parent, title, text, buttons, default_index, width=84, height=26):
    """Повертає (Toplevel, словник-результат). buttons: [(підпис, значення)]."""
    win = tk.Toplevel(parent)
    gt.style_window(win)
    win.title(title)
    win.transient(parent)
    win.minsize(560, 320)
    result = {"value": None}
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=12, pady=(12, 6))
    txt = scrolledtext.ScrolledText(body, width=width, height=height, wrap="word", font=("Consolas", 9))
    gt.style_text(txt)
    txt.insert("1.0", text)
    txt.configure(state="disabled")
    txt.pack(fill="both", expand=True)
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(0, 12))
    btns = []
    for i, (label, value) in enumerate(buttons):
        def cmd(v=value):
            result["value"] = v
            win.destroy()
        b = ttk.Button(bar, text=label, command=cmd)
        b.pack(side="right", padx=(8, 0))
        btns.append(b)
    win.protocol("WM_DELETE_WINDOW", win.destroy)
    win.bind("<Escape>", lambda _e: win.destroy())
    if btns:
        # кнопки пакуються справа наліво: перша в списку -- крайня права; фокус -- на «безпечній» (default_index)
        btns[default_index].focus_set()
    win._dialog_text = txt
    return win, result


def confirm_dialog(parent, title, text, yes="Так", no="Ні"):
    """Так/Ні з прокрутимим текстом. Типово фокус на «Ні». Закриття вікна = «Ні»."""
    win, res = _build(parent, title, text, [(yes, True), (no, False)], 1)
    win.grab_set()
    parent.wait_window(win)
    return bool(res["value"])


def text_dialog(parent, title, text, close="Закрити"):
    """Лише читання, одна кнопка."""
    win, _res = _build(parent, title, text, [(close, None)], 0)
    win.grab_set()
    parent.wait_window(win)
