# -*- coding: utf-8 -*-
"""Символи APRS у вікні CPS (CPS-fix3 V2): намальовані іконки, сітка вибору й підпис символу.

Зображення -- ТІ САМІ, що на рації: tools/aprs_icons_data.py згенеровано tools/aprs_icons_gen.py з tools/aprs_icons.txt (того самого джерела, з якого
генерується application/source/functions/aprs_icons.c; байти збігаються з пулом прошивки, це перевіряє тест). Нічого не перемальовано.
Частина без Tk (decode, symbol_text) тестується без дисплея; Tk потрібен лише для PhotoImage і діалогу вибору.

У слоті кодплага два байти -- у ФОРМАТІ ПРОШИВКИ (R70): таблиця 0 -- основна '/', будь-що інше (1) -- додаткова '\\'; індекс = код символу - 33 ('!' -> 0 ... '~' -> 93).
Так їх читає рація: aprs.c (`iconIndex + '!'`, `iconTable == 0 ? '/' : '\\'`) і aprs_mode_cfg.c. Усі функції нижче, що беруть (table_raw, index_raw), працюють саме в цьому форматі;
пара (ASCII-таблиця, ASCII-код) потрібна лише для малювання піктограм (ICONS ключується '/'+код або '\\'+код). Накладки (цифра/літера поверх символу) слот не зберігає.
(Логіка збігається з aprsIconFind() у aprs_icons.c.)
"""
try:
    from aprs_icons_data import ICONS
except ImportError:      # не повинно статися: файл у репозиторії; без нього сітка просто недоступна, а числа працюють
    ICONS = {}

W = H = 24


def available():
    return bool(ICONS)


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


ICON_MAX = 93             # найбільший індекс ('~' - '!'), APRSM_ICON_MAX у прошивці


def raw_to_pair(table_raw, index_raw):
    """(таблиця, індекс) слота -> (ASCII-таблиця '/' або '\\', ASCII-код) -- ТАК РАЦІЯ ЧИТАЄ слот (aprs.c:581-582: таблиця != 0 -- додаткова). None -- індекс поза '!'..'~'."""
    if not (0 <= index_raw <= ICON_MAX):
        return None
    return ("/" if table_raw == 0 else "\\"), index_raw + 33


def pair_to_raw(table, code):
    """(ASCII-таблиця '/' або '\\', ASCII-код '!'..'~') -> байти слота (0/1, код - 33)."""
    return (0 if table == "/" else 1), code - 33


def is_known(table_raw, index_raw):
    """Чи є в наборі рації зображення для цього символу слота (інакше рація малює рамку зі знаком символу)."""
    p = raw_to_pair(table_raw, index_raw)
    return p is not None and entry(*p) is not None


def unknown_text(table_raw, index_raw):
    """Словами: чому символа слота нема в наборі рації. Формат -- прошивки (таблиця 0/1, індекс = код - 33)."""
    if not (0 <= index_raw <= ICON_MAX):
        return ("У слоті індекс %d поза набором (0..%d). Стоковий бікон передасть за ним байт %d, який не є символом APRS, а «Режим APRS» підставить '>'. "
                "Оберіть символ: «Обрати символ...»." % (index_raw, ICON_MAX, (index_raw + 33) & 0xFF))
    tbl, code = raw_to_pair(table_raw, index_raw)
    return ("У слоті записано символ '%s' (%s таблиця, індекс %d), якого немає в наборі рації. Рація намалює для нього рамку зі знаком. Оберіть інший: «Обрати символ...»."
            % (chr(code), "основна" if tbl == "/" else "додаткова", index_raw))


def symbol_text(table_raw, index_raw):
    """Підпис під полями -- ЯК РАЦІЯ ПРОЧИТАЄ слот: «'>' (індекс 29), основна '/' таблиця -- авто»; таблиця > 1 прошивка читає як додаткову (з поясненням)."""
    p = raw_to_pair(table_raw, index_raw)
    if p is None:
        return unknown_text(table_raw, index_raw)
    tbl, code = p
    tn = "основна '/'" if tbl == "/" else "додаткова '\\'"
    ent = entry(tbl, code)
    extra = "; таблицю %d рація читає як додаткову" % table_raw if table_raw > 1 else ""
    if ent is None:
        return "'%s' (індекс %d), %s таблиця -- зображення в наборі рації нема (код зарезервований)%s" % (chr(code), index_raw, tn, extra)
    return "'%s' (індекс %d), %s таблиця -- %s%s" % (chr(code), index_raw, tn, ent[0], extra)


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


def photo_raw(master, table_raw, index_raw, scale=1, ink="#e8eaef", paper=None):
    """Піктограма слота (формат прошивки) або None."""
    p = raw_to_pair(table_raw, index_raw)
    return photo(master, p[0], p[1], scale, ink, paper) if p else None


def pick_symbol(parent, table_value, code_value, preselect=True):
    """Сітка піктограм: перемикач таблиць, підпис під курсором, «Обрати». Приймає й повертає (таблиця, індекс) слота у ФОРМАТІ ПРОШИВКИ (0/1, код - 33) або None.
    Накладок слот не зберігає, тому їх у сітці нема."""
    import tkinter as tk
    from tkinter import ttk
    import gui_dialogs as gd
    import gui_theme as gt

    win = gd._small_window(parent, "Символ APRS")
    win.minsize(560, 420)
    cur_t = "/" if table_value == 0 else "\\"
    state = {"table": cur_t, "code": (code_value + 33) if (preselect and 0 <= code_value <= ICON_MAX and entry(cur_t, code_value + 33)) else None, "result": None}
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
            tr, ir = pair_to_raw(state["table"], code)
            info.config(text=symbol_text(tr, ir))
        ok_btn.config(state="normal" if state["code"] is not None else "disabled")
        for c, lab in cells.items():
            lab.config(bg=gt.P["select_bg"] if c == state["code"] else gt.P["field"])

    def choose(code):
        state["code"] = code
        refresh_info()

    def finish():
        if state["code"] is None:
            return
        state["result"] = pair_to_raw(state["table"], state["code"])
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
