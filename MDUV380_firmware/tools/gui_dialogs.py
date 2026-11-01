#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gui_dialogs.py -- R26 V3: темні діалоги з прокруткою. Замінюють messagebox там, де текст довгий (підтвердження запису зі
списком змін, перелік проблем імпорту CSV): системний messagebox і тема не дружать, і довгий текст у ньому не прокручується.

Усі функції викликаються ЛИШЕ з головного потоку Tk. Модальні: чекають закриття вікна."""
import tkinter as tk
from tkinter import ttk, scrolledtext

import gui_theme as gt

# R50: пам'ять розміру діалогів. Хто завгодно (CpsApp) кладе сюди об'єкт з get(key, default)/set(key, value)/save() -- типово settings.Settings;
# без нього діалоги поводяться як раніше (розмір за вмістом). Ключ -- вид діалогу, не його заголовок (заголовки містять назви каналів тощо).
GEOMETRY_STORE = None
MIN_DIALOG = (320, 180)                 # менше цього діалог зберегти не дозволяємо (збережене сміття не має робити вікно непридатним)


def _parse_size(text):
    """'640x480' -> (640, 480) або None."""
    try:
        w, h = str(text).lower().split("x")
        w, h = int(w), int(h)
    except (ValueError, AttributeError):
        return None
    return (w, h) if w >= MIN_DIALOG[0] and h >= MIN_DIALOG[1] else None


def remember_window(win, key, minsize=None, fit=False):
    """Зробити діалог зміннорозмірним і запам'ятовувати його розмір між запусками. Збережений розмір застосовується (не більший за екран), нове
    положення -- по центру над головним вікном. Розмір записується в GEOMETRY_STORE при закритті діалогу.

    fit=True (R50-fix): мінімальний розмір діалогу -- не число в пікселях, а розмір, якого вимагає його вміст при цьому шрифті й масштабі екрана
    (Windows 125-150 %, інший шрифт): зменшити діалог так, щоб щось обрізалось, не можна; збережений менший розмір теж піднімається до цього."""
    win.resizable(True, True)
    if minsize:
        win.minsize(*minsize)
    store = GEOMETRY_STORE
    sk = "dlg_" + key
    win.update_idletasks()
    w, h = win.winfo_reqwidth(), win.winfo_reqheight()
    saved = _parse_size(store.get(sk)) if store is not None else None
    try:
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    except tk.TclError:
        sw = sh = 10 ** 6

    def refit_height(width, height):
        """Підписи, що переносяться (autowrap), після першого розміщення можуть захотіти більше висоти -- даємо її, поки вміщується в екран."""
        for _ in range(3):
            win.update_idletasks()
            need = win.winfo_reqheight()
            if need <= height or need > sh:
                break
            height = need
            win.geometry("%dx%d" % (width, height))
        return height

    try:
        if fit:
            # мінімум = що вимагає вміст при ЦЬОМУ шрифті й масштабі (з урахуванням переносу підписів на цій ширині)
            win.geometry("%dx%d" % (min(w, sw), min(h, sh)))
            h = min(refit_height(min(w, sw), min(h, sh)), sh)
            w = min(w, sw)
            win.minsize(max(w, (minsize or (0, 0))[0]), max(h, (minsize or (0, 0))[1]))
        if saved:
            w, h = max(w, saved[0]), max(h, saved[1])
        mw, mh = (minsize or (0, 0))
        w = max(w, mw)
        h = max(h, mh)
        w, h = min(w, sw), min(h, sh)
        top = win.master.winfo_toplevel()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - w) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - h) // 3)
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        if not saved and not fit:
            h = refit_height(w, h)
    except tk.TclError:
        pass

    def on_destroy(e):
        if e.widget is not win or store is None:
            return
        cur = win._r50_size
        if cur and cur[0] >= MIN_DIALOG[0] and cur[1] >= MIN_DIALOG[1]:
            store.set(sk, "%dx%d" % cur)
            try:
                store.save()
            except Exception:  # noqa: BLE001 -- збереження розміру ніколи не заважає роботі
                pass

    def on_conf(e):
        if e.widget is win:
            win._r50_size = (e.width, e.height)
    win._r50_size = None
    win.bind("<Configure>", on_conf, add="+")
    win.bind("<Destroy>", on_destroy, add="+")


def _slug(title):
    """Коротка стабільна частина ключа з заголовка діалогу (щоб велике підтвердження запису не розтягувало маленьке «Видалити?»)."""
    t = "".join(c if c.isalnum() else "_" for c in str(title).lower())
    return t[:40].strip("_") or "x"


def autowrap(label, container, margin=28, floor=180):
    """Підпис, що переноситься за шириною контейнера (діалог можна розтягнути -- текст не лишається вузьким і не обрізається)."""
    def fit(e=None):
        w = container.winfo_width()
        if w > 1:
            label.config(wraplength=max(floor, w - margin))
    container.bind("<Configure>", fit, add="+")
    return label


def _build(parent, title, text, buttons, default_index, width=84, height=26, key="text", minsize=(560, 320)):
    """Повертає (Toplevel, словник-результат). buttons: [(підпис, значення)]."""
    win = tk.Toplevel(parent)
    gt.style_window(win)
    win.title(title)
    win.transient(parent.winfo_toplevel())
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
    remember_window(win, "%s_%s" % (key, _slug(title)), minsize)
    return win, result


def confirm_dialog(parent, title, text, yes="Так", no="Ні"):
    """Так/Ні з прокрутимим текстом. Типово фокус на «Ні». Закриття вікна = «Ні»."""
    win, res = _build(parent, title, text, [(yes, True), (no, False)], 1, key="confirm")
    win.grab_set()
    parent.wait_window(win)
    return bool(res["value"])


def text_dialog(parent, title, text, close="Закрити"):
    """Лише читання, одна кнопка."""
    win, _res = _build(parent, title, text, [(close, None)], 0, key="text")
    win.grab_set()
    parent.wait_window(win)


def choice_dialog(parent, title, text, buttons, default_index=0):
    """Вибір з кількох кнопок. buttons: [(підпис, значення)] -- ПЕРША в списку стоїть крайньою правою (і має фокус, якщо default_index = 0).
    Закриття вікна без вибору повертає None."""
    win, res = _build(parent, title, text, buttons, default_index, width=70, height=10, key="choice")
    win.grab_set()
    parent.wait_window(win)
    return res["value"]


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
    """Мале вікно діалогу. Розмір запам'ятовується (remember_window) -- викликач після створення вмісту викликає win.remember(ключ, мінімум)."""
    win = tk.Toplevel(parent)
    gt.style_window(win)
    win.title(title)
    win.transient(parent.winfo_toplevel())
    win.resizable(True, True)
    win.remember = lambda key, minsize=None: remember_window(win, key, minsize)
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
    msg = autowrap(ttk.Label(body, text="", wraplength=380, justify="left"), body)
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
    win.remember("name", None)
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
    m1 = autowrap(ttk.Label(body, text="", wraplength=380, justify="left"), body)
    m1.pack(anchor="w", pady=2)
    ttk.Label(body, text=prompt2).pack(anchor="w", pady=(6, 0))
    e2 = ttk.Entry(body, textvariable=v2, width=40)
    e2.pack(fill="x", pady=4)
    m2 = autowrap(ttk.Label(body, text="", wraplength=380, justify="left"), body)
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
    win.remember("two_field", None)
    win.grab_set()
    parent.wait_window(win)
    return result["value"]


def pick_dialog(parent, title, name_prompt, items, limit, check=None, ok="Створити", noun="елементів", initial=""):
    """Назва + вибір елементів (мінімум 1, не більше limit) зі списку items [(значення, підпис)]. Порядок результату -- як у списку.
    Повертає (назва, [значення]) або None."""
    win = _small_window(parent, title)
    result = {"value": None}
    var = tk.StringVar(value=initial)
    flt = tk.StringVar()
    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=12, pady=(12, 4))
    ttk.Label(body, text=name_prompt).pack(anchor="w")
    entry = ttk.Entry(body, textvariable=var, width=40)
    entry.pack(fill="x", pady=4)
    msg = autowrap(ttk.Label(body, text="", wraplength=420, justify="left"), body)
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
    win.remember("pick", (460, 460))
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
    msg = autowrap(ttk.Label(body, text="", wraplength=380, justify="left"), body)
    msg.pack(anchor="w", pady=2)
    box = ttk.LabelFrame(body, text="Тип")
    box.pack(fill="x", pady=6)
    r1 = ttk.Radiobutton(box, text="Аналоговий (FM)", variable=kind, value="analog")
    r1.pack(anchor="w", padx=8, pady=2)
    r2 = ttk.Radiobutton(box, text="Цифровий (DMR)", variable=kind, value="digital")
    r2.pack(anchor="w", padx=8, pady=2)
    autowrap(ttk.Label(body, text="Частоти RX/TX нового каналу -- типові (145,50000 МГц): змініть їх у формі.", wraplength=380, justify="left",
                       foreground=gt.P["muted"]), body).pack(anchor="w", pady=2)
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
    win.remember("new_channel", None)
    win.grab_set()
    parent.wait_window(win)
    return result["value"]


# ----------------------------------------------------------------------------------------------------------------------------
#  R50: системні messagebox -> наші зміннорозмірні діалоги (довгі підсумки запису прокручуються, розмір запам'ятовується)
# ----------------------------------------------------------------------------------------------------------------------------

import tkinter.messagebox as _mb

_PRISTINE = {n: getattr(_mb, n) for n in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askyesnocancel")}
_INSTALLED = {}


def _message_dialog(kind, buttons, default_of):
    """kind: 'info' | 'yesno' | 'okcancel' | 'yesnocancel'. buttons: [(підпис, значення)] -- перша крайня права."""
    orig = _PRISTINE[{"info": "showinfo", "yesno": "askyesno", "okcancel": "askokcancel", "yesnocancel": "askyesnocancel"}[kind]]

    def fn(title=None, message=None, **options):
        parent = options.get("parent") or tk._default_root
        if parent is None:
            return orig(title, message, **options)
        text = str(message if message is not None else "")
        lines = text.split("\n") or [""]
        width = max(40, min(84, max(len(l) for l in lines) + 2))
        height = max(3, min(24, sum(max(1, -(-len(l) // width)) for l in lines)))
        default_index = default_of(options.get("default"))
        win, res = _build(parent, str(title or ""), text, buttons, default_index, width=width, height=height, key="msg", minsize=(380, 170))
        win.grab_set()
        parent.wait_window(win)
        v = res["value"]
        if kind == "info":
            return "ok"
        if kind == "yesnocancel":
            return v if v in (True, False) else None
        return v is True
    return fn


def install_message_boxes():
    """Замінити showinfo/showwarning/showerror/askyesno/askokcancel/askyesnocancel зміннорозмірними діалогами. Те, що вже підмінено ззовні
    (наприклад, у тестах), не чіпаємо."""
    info = _message_dialog("info", [("Гаразд", "ok")], lambda d: 0)
    new = {"showinfo": info, "showwarning": info, "showerror": info,
           "askyesno": _message_dialog("yesno", [("Так", True), ("Ні", False)], lambda d: 1 if d == "no" else 0),
           "askokcancel": _message_dialog("okcancel", [("Гаразд", True), ("Скасувати", False)], lambda d: 1 if d == "cancel" else 0),
           "askyesnocancel": _message_dialog("yesnocancel", [("Так", True), ("Ні", False), ("Скасувати", None)], lambda d: {"no": 1, "cancel": 2}.get(d, 0))}
    for name, fn in new.items():
        if getattr(_mb, name) is _PRISTINE[name]:
            setattr(_mb, name, fn)
            _INSTALLED[name] = fn


def uninstall_message_boxes():
    for name, fn in list(_INSTALLED.items()):
        if getattr(_mb, name) is fn:
            setattr(_mb, name, _PRISTINE[name])
        del _INSTALLED[name]
