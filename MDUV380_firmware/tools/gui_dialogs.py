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
    win.transient(parent.winfo_toplevel())
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


def choice_dialog(parent, title, text, buttons, default_index=0):
    """Вибір з кількох кнопок. buttons: [(підпис, значення)] -- ПЕРША в списку стоїть крайньою правою (і має фокус, якщо default_index = 0).
    Закриття вікна без вибору повертає None."""
    win, res = _build(parent, title, text, buttons, default_index, width=70, height=10)
    win.grab_set()
    parent.wait_window(win)
    return res["value"]


def list_choice_dialog(parent, title, text, labels):
    """Вибір одного рядка зі списку (з фільтром). Повертає індекс у `labels` або None (скасовано / закрито). R39: ручний вибір каналу для самоперевірки S3."""
    win = _small_window(parent, title)
    win.minsize(520, 460)
    result = {"value": None}
    flt = tk.StringVar()
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=12, pady=(12, 4))
    ttk.Label(body, text=text, wraplength=480, justify="left").pack(anchor="w")
    ttk.Label(body, text="Фільтр списку:").pack(anchor="w", pady=(6, 0))
    ttk.Entry(body, textvariable=flt).pack(fill="x", pady=2)
    frame = ttk.Frame(body)
    frame.pack(fill="both", expand=True, pady=4)
    lb = tk.Listbox(frame, selectmode="browse", exportselection=False, height=12)
    gt.style_text(lb)
    sb = gt.AutoScrollbar(frame, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    lb.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    shown = []                  # індекси в labels того, що видно після фільтра
    ok_btn = None

    def fill(*_a):
        lb.delete(0, "end")
        shown.clear()
        needle = flt.get().strip().casefold()
        for i, label in enumerate(labels):
            if not needle or needle in label.casefold():
                shown.append(i)
                lb.insert("end", label)
        refresh()

    def refresh(_e=None):
        if ok_btn is not None:
            ok_btn.config(state="normal" if lb.curselection() else "disabled")

    def finish(value):
        result["value"] = value
        win.destroy()

    def accept(_e=None):
        sel = lb.curselection()
        if sel:
            finish(shown[sel[0]])
    lb.bind("<<ListboxSelect>>", refresh)
    lb.bind("<Double-Button-1>", accept)
    flt.trace_add("write", fill)
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(4, 12))
    ok_btn = ttk.Button(bar, text="Обрати", command=accept)
    ok_btn.pack(side="right", padx=(8, 0))
    ttk.Button(bar, text="Не обирати", command=lambda: finish(None)).pack(side="right")
    win.bind("<Escape>", lambda _e: finish(None))
    win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    fill()
    win.update_idletasks()
    win.grab_set()
    parent.wait_window(win)
    return result["value"]


def delete_choice(parent, noun, name, refs_text=None):
    """Єдиний діалог видалення запису документа (редактори контактів / списків / зон / каналів і блок APRS-слотів, R28).
    refs_text -- перелік тих, хто на запис посилається (te.Refs.text()); None/порожній -- посилань нема.
    Повертає None (скасовано), False (видалити, посилань нема) або True (видалити разом із посиланнями)."""
    if refs_text:
        text = ("Видалити %s «%s»?\n\nНа нього посилаються:\n%s\n\n«Скасувати» -- нічого не міняти.\n«Видалити разом із посиланнями» -- запис "
                "зникне, а посилання буде прибрано (елемент списку / зони викреслюється, поле каналу стає «None»)." % (noun, name, refs_text))
        choice = choice_dialog(parent, "Запис використовується", text, [("Скасувати", "cancel"), ("Видалити разом із посиланнями", "cascade")], 0)
        return True if choice == "cascade" else None
    if not confirm_dialog(parent, "Видалити?", "Видалити %s «%s» з документа?" % (noun, name), yes="Видалити", no="Скасувати"):
        return None
    return False


# ----------------------------------------------------------------------------------------------------------------------------
#  CPS-fix2 / етап 3: діалоги редакторів списків прийому, зон і каналів
# ----------------------------------------------------------------------------------------------------------------------------

def _small_window(parent, title):
    win = tk.Toplevel(parent)
    gt.style_window(win)
    win.title(title)
    win.transient(parent.winfo_toplevel())
    win.resizable(True, True)
    return win


def _live_check(check, text):
    """check(text) -> None (усе гаразд) | текст проблеми. Повертає (ok, повідомлення, колір)."""
    try:
        problem = check(text) if check else None
    except Exception as e:  # noqa: BLE001 -- перевірка не має валити діалог
        problem = str(e)
    if problem:
        return False, problem, gt.P["err"]
    return True, "Назва підходить.", gt.P["muted"]


def name_dialog(parent, title, prompt, initial="", check=None, ok="Гаразд"):
    """Один рядок тексту з живою перевіркою (check(текст) -> None або текст проблеми). Кнопка неактивна, поки є проблема.
    Повертає текст або None (скасовано)."""
    win = _small_window(parent, title)
    result = {"value": None}
    var = tk.StringVar(value=initial)
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=12, pady=(12, 4))
    ttk.Label(body, text=prompt).pack(anchor="w")
    entry = ttk.Entry(body, textvariable=var, width=40)
    entry.pack(fill="x", pady=4)
    msg = ttk.Label(body, text="", wraplength=380, justify="left")
    msg.pack(anchor="w", pady=2)
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(4, 12))

    def finish(value):
        result["value"] = value
        win.destroy()
    ok_btn = ttk.Button(bar, text=ok, command=lambda: finish(var.get()))
    ok_btn.pack(side="right", padx=(8, 0))
    ttk.Button(bar, text="Скасувати", command=lambda: finish(None)).pack(side="right")

    def update(*_a):
        good, text, color = _live_check(check, var.get())
        msg.config(text=text, foreground=color)
        ok_btn.config(state="normal" if good else "disabled")
    var.trace_add("write", update)
    update()
    win.bind("<Return>", lambda _e: ok_btn.invoke() if str(ok_btn.cget("state")) == "normal" else None)
    win.bind("<Escape>", lambda _e: finish(None))
    win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    entry.focus_set()
    entry.select_range(0, "end")
    win.update_idletasks()
    win.grab_set()
    parent.wait_window(win)
    return result["value"]


def two_field_dialog(parent, title, prompt1, prompt2, check1, check2, initial1="", initial2="", ok="Гаразд"):
    """Два рядки тексту (напр. назва й код) з живою перевіркою кожного (check(текст) -> None або текст проблеми). Кнопка неактивна, поки є
    проблема в будь-якому. Повертає (текст1, текст2) або None (скасовано)."""
    win = _small_window(parent, title)
    result = {"value": None}
    v1, v2 = tk.StringVar(value=initial1), tk.StringVar(value=initial2)
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=12, pady=(12, 4))
    ttk.Label(body, text=prompt1).pack(anchor="w")
    e1 = ttk.Entry(body, textvariable=v1, width=40)
    e1.pack(fill="x", pady=4)
    m1 = ttk.Label(body, text="", wraplength=380, justify="left")
    m1.pack(anchor="w", pady=2)
    ttk.Label(body, text=prompt2).pack(anchor="w", pady=(6, 0))
    e2 = ttk.Entry(body, textvariable=v2, width=40)
    e2.pack(fill="x", pady=4)
    m2 = ttk.Label(body, text="", wraplength=380, justify="left")
    m2.pack(anchor="w", pady=2)
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(4, 12))

    def finish(value):
        result["value"] = value
        win.destroy()
    ok_btn = ttk.Button(bar, text=ok, command=lambda: finish((v1.get(), v2.get())))
    ok_btn.pack(side="right", padx=(8, 0))
    ttk.Button(bar, text="Скасувати", command=lambda: finish(None)).pack(side="right")

    def update(*_a):
        g1, t1, c1 = _live_check(check1, v1.get())
        g2, t2, c2 = _live_check(check2, v2.get())
        m1.config(text=t1, foreground=c1)
        m2.config(text=t2.replace("Назва підходить.", "Код підходить."), foreground=c2)
        ok_btn.config(state="normal" if (g1 and g2) else "disabled")
    v1.trace_add("write", update)
    v2.trace_add("write", update)
    update()
    win.bind("<Return>", lambda _e: ok_btn.invoke() if str(ok_btn.cget("state")) == "normal" else None)
    win.bind("<Escape>", lambda _e: finish(None))
    win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    e1.focus_set()
    win.update_idletasks()
    win.grab_set()
    parent.wait_window(win)
    return result["value"]


def pick_dialog(parent, title, name_prompt, items, limit, check=None, ok="Створити", noun="елементів", initial=""):
    """Назва + вибір елементів (мінімум 1, не більше limit) зі списку items [(значення, підпис)]. Порядок результату -- як у списку.
    Повертає (назва, [значення]) або None."""
    win = _small_window(parent, title)
    win.minsize(460, 460)
    result = {"value": None}
    var = tk.StringVar(value=initial)
    flt = tk.StringVar()
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=12, pady=(12, 4))
    ttk.Label(body, text=name_prompt).pack(anchor="w")
    entry = ttk.Entry(body, textvariable=var, width=40)
    entry.pack(fill="x", pady=4)
    msg = ttk.Label(body, text="", wraplength=420, justify="left")
    msg.pack(anchor="w", pady=2)
    ttk.Label(body, text="Фільтр списку:").pack(anchor="w", pady=(6, 0))
    ttk.Entry(body, textvariable=flt).pack(fill="x", pady=2)
    frame = ttk.Frame(body)
    frame.pack(fill="both", expand=True, pady=4)
    lb = tk.Listbox(frame, selectmode="extended", exportselection=False, height=12)
    gt.style_text(lb)
    sb = gt.AutoScrollbar(frame, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=sb.set)
    lb.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    count = ttk.Label(body, text="")
    count.pack(anchor="w")
    chosen = []                 # значення, відмічені користувачем (зберігаються, поки список фільтрується)
    shown = []

    def fill(*_a):
        lb.delete(0, "end")
        shown.clear()
        needle = flt.get().strip().casefold()
        for value, label in items:
            if not needle or needle in label.casefold():
                shown.append(value)
                lb.insert("end", label)
                if value in chosen:
                    lb.selection_set("end")
        refresh()

    def on_select(_e=None):
        vis = set(lb.curselection())
        for i, value in enumerate(shown):
            if i in vis and value not in chosen:
                chosen.append(value)
            elif i not in vis and value in chosen:
                chosen.remove(value)
        refresh()

    ok_btn = None

    def refresh():
        good, text, color = _live_check(check, var.get())
        n = len(chosen)
        if good and n == 0:
            good, text, color = False, "Оберіть хоча б один елемент (порожнього запису рація не використовує).", gt.P["warn"]
        elif good and n > limit:
            good, text, color = False, "Забагато: обрано %d, ліміт кодплага -- %d %s." % (n, limit, noun), gt.P["err"]
        msg.config(text=text, foreground=color)
        count.config(text="Обрано: %d з %d" % (n, limit))
        if ok_btn is not None:
            ok_btn.config(state="normal" if good else "disabled")
    lb.bind("<<ListboxSelect>>", on_select)
    flt.trace_add("write", fill)
    var.trace_add("write", lambda *_a: refresh())
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(4, 12))

    def finish(value):
        result["value"] = value
        win.destroy()
    ok_btn = ttk.Button(bar, text=ok, command=lambda: finish((var.get(), [v for v, _l in items if v in chosen])))
    ok_btn.pack(side="right", padx=(8, 0))
    ttk.Button(bar, text="Скасувати", command=lambda: finish(None)).pack(side="right")
    win.bind("<Escape>", lambda _e: finish(None))
    win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    fill()
    entry.focus_set()
    win.update_idletasks()
    win.grab_set()
    parent.wait_window(win)
    return result["value"]


def new_channel_dialog(parent, title, check=None, base_label=None):
    """Назва нового каналу + тип (аналоговий / цифровий). base_label -- підпис вибраного каналу: з'являється прапорець «взяти за основу»
    (тоді тип береться з нього). Повертає (назва, цифровий?, за_основою?) або None."""
    win = _small_window(parent, title)
    result = {"value": None}
    var = tk.StringVar()
    kind = tk.StringVar(value="analog")
    use_base = tk.BooleanVar(value=False)
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=12, pady=(12, 4))
    ttk.Label(body, text="Назва нового каналу:").pack(anchor="w")
    entry = ttk.Entry(body, textvariable=var, width=40)
    entry.pack(fill="x", pady=4)
    msg = ttk.Label(body, text="", wraplength=380, justify="left")
    msg.pack(anchor="w", pady=2)
    box = ttk.LabelFrame(body, text="Тип")
    box.pack(fill="x", pady=6)
    r1 = ttk.Radiobutton(box, text="Аналоговий (FM)", variable=kind, value="analog")
    r1.pack(anchor="w", padx=8, pady=2)
    r2 = ttk.Radiobutton(box, text="Цифровий (DMR)", variable=kind, value="digital")
    r2.pack(anchor="w", padx=8, pady=2)
    ttk.Label(body, text="Частоти RX/TX нового каналу -- типові (145,50000 МГц): змініть їх у формі.", wraplength=380, justify="left",
              foreground=gt.P["muted"]).pack(anchor="w", pady=2)
    if base_label:
        ttk.Checkbutton(body, text="Узяти значення з вибраного каналу: %s (тип береться з нього)" % base_label, variable=use_base,
                        command=lambda: [w.config(state="disabled" if use_base.get() else "normal") for w in (r1, r2)]).pack(anchor="w", pady=4)
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(4, 12))

    def finish(value):
        result["value"] = value
        win.destroy()
    ok_btn = ttk.Button(bar, text="Створити", command=lambda: finish((var.get(), kind.get() == "digital", bool(use_base.get()))))
    ok_btn.pack(side="right", padx=(8, 0))
    ttk.Button(bar, text="Скасувати", command=lambda: finish(None)).pack(side="right")

    def update(*_a):
        good, text, color = _live_check(check, var.get())
        msg.config(text=text, foreground=color)
        ok_btn.config(state="normal" if good else "disabled")
    var.trace_add("write", update)
    update()
    win.bind("<Escape>", lambda _e: finish(None))
    win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    entry.focus_set()
    win.update_idletasks()
    win.grab_set()
    parent.wait_window(win)
    return result["value"]
