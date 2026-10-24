# -*- coding: utf-8 -*-
"""Символи APRS у вікні CPS (CPS-fix3 V2): намальовані іконки, сітка вибору й підпис символу.

Зображення -- ТІ САМІ, що на рації: tools/aprs_icons_data.py згенеровано tools/aprs_icons_gen.py з tools/aprs_icons.txt (того самого джерела, з якого
генерується application/source/functions/aprs_icons.c; байти збігаються з пулом прошивки, це перевіряє тест). Нічого не перемальовано.
Частина без Tk (decode, symbol_text) тестується без дисплея; Tk потрібен лише для PhotoImage і діалогу вибору.

У кодплазі «таблиця» й «символ» -- два байти (0..255) -- ASCII-коди: таблиця '/' (47) первинна, '\\' (92) додаткова; символ -- '!'..'~' (33..126).
Решта значень таблиці в додатковій таблиці APRS -- накладка (цифра або літера поверх символу): іконка тоді береться з додаткової таблиці, а накладка зберігається.
(Логіка збігається з aprsIconFind() у aprs_icons.c: '/' -- первинна, '\\' і накладки 0-9, A-Z -- додаткова, інакше іконки нема.)"""
try:
    from aprs_icons_data import ICONS
except ImportError:      # не повинно статися: файл у репозиторії; без нього сітка просто недоступна, а числа працюють
    ICONS = {}

W = H = 24
PRIMARY, ALTERNATE = ord("/"), ord("\\")


def available():
    return bool(ICONS)


def table_char(table_value):
    """'/' для первинної таблиці, '\\' для додаткової (і для накладок), None -- значення не схоже на таблицю."""
    if table_value == PRIMARY:
        return "/"
    if table_value == ALTERNATE or 0x30 <= table_value <= 0x39 or 0x41 <= table_value <= 0x5A:      # накладка -- цифра або велика літера (як aprsIconFind)
        return "\\"
    return None


def codes(table):
    """[(код, назва)] піктограм таблиці ('/' або '\\') за зростанням коду."""
    return sorted(((ord(k[1]), v[0]) for k, v in ICONS.items() if k[0] == table))


def entry(table, code):
    return ICONS.get(table + chr(code)) if 0x21 <= code <= 0x7E else None


def decode(data_hex):
    """72 байти XBM (hex) -> 24 рядки по 24 символи '#'/'.'. Молодший біт байта -- ліворуч (як displayDrawXBitmap)."""
    raw = bytes.fromhex(data_hex)
    rows = []
    for y in range(H):
        rows.append("".join("#" if (raw[y * 3 + x // 8] >> (x % 8)) & 1 else "." for x in range(W)))
    return rows


def is_known(table_value, code_value):
    """Чи є в наборі рації зображення для цього символу (інакше рація малює рамку зі знаком символу)."""
    t = table_char(table_value)
    return t is not None and entry(t, code_value) is not None


def unknown_text(table_value, code_value):
    """Словами: чому символа в слоті нема в наборі рації й що робити (Y1.3). Чисел для вводу не пропонуємо."""
    if code_value == 0:
        return "Символ не обрано. Оберіть його: «Обрати символ...»."
    where = "у цій таблиці" if table_char(table_value) else "у такій таблиці"
    return ("У слоті записано символ, якого немає в наборі рації (таблиця %d, код %d: %s). Рація намалює для нього рамку зі знаком. "
            "Оберіть інший: «Обрати символ...»." % (table_value, code_value, where))


def symbol_text(table_value, code_value):
    """Підпис під полями: «'>' (код 62) -- Авто» або чому зображення нема."""
    t = table_char(table_value)
    ch = chr(code_value) if 0x21 <= code_value <= 0x7E else None
    if ch is None:
        return "код %d: символ APRS -- це '!'...'~' (33..126)" % code_value
    ent = entry(t, code_value) if t else None
    tn = "основна '/'" if t == "/" else "додаткова '\\'"
    if t is None:
        return "'%s' (код %d): таблиця %d не схожа на '/' чи '\\'" % (ch, code_value, table_value)
    if ent is None:
        return "'%s' (код %d), %s таблиця -- зображення в наборі рації нема (код зарезервований)" % (ch, code_value, tn)
    extra = "" if table_value in (PRIMARY, ALTERNATE) else "; накладка '%s'" % chr(table_value)
    return "'%s' (код %d), %s таблиця -- %s%s" % (ch, code_value, tn, ent[0], extra)


# ---------------------------------------------------------------------------------------------------------------------------------
#  Tk
# ---------------------------------------------------------------------------------------------------------------------------------

def photo(master, table, code, scale=1, ink="#e8eaef", paper=None):
    """tk.PhotoImage піктограми або None, якщо її нема. paper=None -- прозоре тло не підтримує PhotoImage на всіх Tk, тож тло завжди заповнюється."""
    ent = entry(table, code)
    if ent is None:
        return None
    import tkinter as tk
    import gui_theme as gt
    paper = paper or gt.P["field"]
    img = tk.PhotoImage(master=master, width=W, height=H)
    rows = decode(ent[1])
    img.put(" ".join("{" + " ".join(ink if c == "#" else paper for c in r) + "}" for r in rows))
    return img.zoom(scale, scale) if scale > 1 else img


def pick_symbol(parent, table_value, code_value, preselect=True):
    """Сітка піктограм: перемикач таблиць, підпис під курсором, «Обрати». Повертає (таблиця, символ) як числа або None.
    Якщо поточна таблиця -- накладка (не '/' і не '\\'), при виборі з додаткової таблиці накладка лишається."""
    import tkinter as tk
    from tkinter import ttk
    import gui_dialogs as gd
    import gui_theme as gt

    win = gd._small_window(parent, "Символ APRS")
    win.minsize(560, 420)
    cur_t = table_char(table_value) or "/"
    state = {"table": cur_t, "code": code_value if (preselect and entry(cur_t, code_value)) else None, "result": None}
    tvar = tk.StringVar(value=cur_t)
    top = ttk.Frame(win)
    top.pack(fill="x", padx=12, pady=(12, 4))
    ttk.Label(top, text="Таблиця:").pack(side="left")
    grid_host = ttk.Frame(win)
    grid_host.pack(fill="both", expand=True, padx=12, pady=4)
    info = ttk.Label(win, text="", wraplength=520, justify="left")
    info.pack(anchor="w", padx=12, pady=(2, 4))
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=12, pady=(4, 12))
    ok_btn = ttk.Button(bar, text="Обрати")
    ok_btn.pack(side="right", padx=(8, 0))
    ttk.Button(bar, text="Скасувати", command=win.destroy).pack(side="right")
    cells = {}
    images = []            # PhotoImage треба тримати посиланнями, інакше Tk їх прибере

    def refresh_info(hover=None):
        code = hover if hover is not None else state["code"]
        if code is None:
            info.config(text="Оберіть символ: наведіть курсор -- побачите код і назву.")
        else:
            tv = ord(state["table"])
            if state["table"] == "\\" and table_char(table_value) == "\\" and table_value != ALTERNATE:
                tv = table_value
            info.config(text=symbol_text(tv, code))
        ok_btn.config(state="normal" if state["code"] is not None else "disabled")
        for c, lab in cells.items():
            lab.config(bg=gt.P["select_bg"] if c == state["code"] else gt.P["field"])

    def choose(code):
        state["code"] = code
        refresh_info()

    def finish():
        if state["code"] is None:
            return
        t = ord(state["table"])
        if state["table"] == "\\" and table_char(table_value) == "\\" and table_value != ALTERNATE:
            t = table_value          # накладку не губимо
        state["result"] = (t, state["code"])
        win.destroy()
    ok_btn.config(command=finish)

    def build():
        for w in grid_host.winfo_children():
            w.destroy()
        cells.clear()
        del images[:]
        cols = 12
        for i, (code, name) in enumerate(codes(state["table"])):
            img = photo(win, state["table"], code, scale=2)
            lab = tk.Label(grid_host, image=img, bd=0, padx=3, pady=3, bg=gt.P["field"], cursor="hand2")
            images.append(img)
            lab.grid(row=i // cols, column=i % cols, padx=1, pady=1)
            lab.bind("<Enter>", lambda _e, c=code: refresh_info(c))
            lab.bind("<Leave>", lambda _e: refresh_info())
            lab.bind("<Button-1>", lambda _e, c=code: choose(c))
            lab.bind("<Double-Button-1>", lambda _e, c=code: (choose(c), finish()))
            cells[code] = lab
        if state["code"] is not None and state["code"] not in cells:
            state["code"] = None
        refresh_info()

    def on_table():
        state["table"] = tvar.get()
        build()
    ttk.Radiobutton(top, text="Основна «/»", variable=tvar, value="/", command=on_table).pack(side="left", padx=8)
    ttk.Radiobutton(top, text="Додаткова «\\»", variable=tvar, value="\\", command=on_table).pack(side="left")
    build()
    win.bind("<Escape>", lambda _e: win.destroy())
    win.bind("<Return>", lambda _e: finish())
    win.update_idletasks()
    win.grab_set()
    parent.wait_window(win)
    return state["result"]
