#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gui_theme.py -- R26 V3: темна тема для всіх вікон прошивальника (головне, AES, RCTL, перегляд кодплуга, діалоги).

ОДНА палітра -- словник PALETTE нижче. Жодного кольору в інших файлах прошивальника рядком «#rrggbb» бути не повинно
(тест test_gui_theme.py обходить файли й шукає літерали). Тема одна й завжди увімкнена: перемикача нема (брифом так задано).

Що покрито: ttk Frame / LabelFrame / Label / Button / Entry / Spinbox / Combobox / Checkbutton / Radiobutton / Notebook / Treeview /
Scrollbar / Progressbar / Separator + класичні tk Text / ScrolledText / Listbox / Menu / Toplevel (їх ttk-стиль не торкається).

ЩО ЛИШАЄТЬСЯ СВІТЛИМ (обмеження платформи, а не недогляд): системні діалоги messagebox.* і filedialog.* -- їх малює сама ОС
(Windows), Tk змінити їх колір не може. Підтвердження запису й довгі списки проблем показує НАШ діалог (gui_dialogs.py) -- він темний.

Контраст: кожна пара «текст / тло», що реально зустрічається, має відношення яскравостей не менше 4,5 : 1 (WCAG AA) --
CONTRAST_PAIRS нижче, перевіряє test_gui_theme.py. Стан не передається лише кольором: у кожного стану є слово (Готово / Помилка / ...).
"""

PALETTE = {
    "bg": "#171a21",            # тло вікон
    "surface": "#20242d",       # панелі, рамки, шапки таблиць, вкладки
    "field": "#11141a",         # поля вводу, таблиці, журнал
    "fg": "#e8eaef",            # основний текст
    "muted": "#a6acb8",         # другорядний текст (версія, автор, підказки)
    "border": "#3d4455",        # рамки й розділювачі
    "accent": "#7db4ff",        # посилання, фокус, індикатор
    "button_bg": "#2c3240",
    "button_hover": "#3a4256",
    "button_fg": "#e8eaef",
    "disabled_bg": "#1c2028",
    "disabled_fg": "#8d95a4",
    "select_bg": "#2f5597",     # виділення в таблицях і текстових полях
    "select_fg": "#ffffff",
    "ok": "#62d58f",            # статус «Готово»
    "info": "#82c4ff",          # статус «іде робота»
    "warn": "#e6b84a",          # попередження («заблоковано», «обережно»)
    "err": "#ff8279",           # помилка
}

# Пари (текст, тло), контраст яких мусить бути >= 4,5. Тло -- із найгіршим для цього тексту набором.
CONTRAST_PAIRS = [
    ("fg", "bg"), ("fg", "surface"), ("fg", "field"),
    ("muted", "bg"), ("muted", "surface"), ("muted", "field"),
    ("button_fg", "button_bg"), ("button_fg", "button_hover"),
    ("disabled_fg", "disabled_bg"), ("disabled_fg", "bg"),
    ("select_fg", "select_bg"),
    ("ok", "bg"), ("ok", "surface"), ("ok", "field"),
    ("info", "bg"), ("info", "surface"), ("info", "field"),
    ("warn", "bg"), ("warn", "surface"), ("warn", "field"),
    ("err", "bg"), ("err", "surface"), ("err", "field"),
    ("accent", "bg"), ("accent", "surface"), ("accent", "field"),
]

P = PALETTE


def _lum(h):
    h = h.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    """Відношення контрастності WCAG двох кольорів «#rrggbb»."""
    la, lb = _lum(a), _lum(b)
    if la < lb:
        la, lb = lb, la
    return (la + 0.05) / (lb + 0.05)


def apply(root):
    """Налаштувати тему для всього застосунку. Викликається ОДИН раз для кореневого вікна (до створення віджетів)."""
    from tkinter import ttk
    root.configure(bg=P["bg"])
    # запасний шлях для КЛАСИЧНИХ tk-віджетів, що створюються пізніше (Frame/Scrollbar/Label/Button/...): ttk-стиль на них не діє
    for pat, val in (("*Frame.background", P["bg"]), ("*Toplevel.background", P["bg"]), ("*Label.background", P["bg"]),
                     ("*Label.foreground", P["fg"]), ("*Scrollbar.background", P["button_bg"]), ("*Scrollbar.troughColor", P["field"]),
                     ("*Scrollbar.activeBackground", P["button_hover"]), ("*Scrollbar.highlightBackground", P["bg"]),
                     ("*Menu.background", P["surface"]), ("*Menu.foreground", P["fg"]), ("*Menu.activeBackground", P["select_bg"]),
                     ("*Menu.activeForeground", P["select_fg"]), ("*Text.background", P["field"]), ("*Text.foreground", P["fg"]),
                     ("*Listbox.background", P["field"]), ("*Listbox.foreground", P["fg"])):
        root.option_add(pat, val)
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except Exception:          # noqa: BLE001 -- clam є в кожному Tk 8.5+, але лишаємо запас
        pass
    st.configure(".", background=P["bg"], foreground=P["fg"], fieldbackground=P["field"], bordercolor=P["border"],
                 lightcolor=P["border"], darkcolor=P["border"], troughcolor=P["field"], focuscolor=P["accent"],
                 insertcolor=P["fg"], selectbackground=P["select_bg"], selectforeground=P["select_fg"])
    st.map(".", foreground=[("disabled", P["disabled_fg"])], background=[("disabled", P["disabled_bg"])])

    st.configure("TFrame", background=P["bg"])
    st.configure("TLabel", background=P["bg"], foreground=P["fg"])
    st.configure("TLabelframe", background=P["bg"], bordercolor=P["border"], lightcolor=P["border"], darkcolor=P["border"])
    st.configure("TLabelframe.Label", background=P["bg"], foreground=P["fg"])
    st.configure("TSeparator", background=P["border"])

    st.configure("TButton", background=P["button_bg"], foreground=P["button_fg"], bordercolor=P["border"], lightcolor=P["button_bg"],
                 darkcolor=P["button_bg"], focusthickness=1, focuscolor=P["accent"], padding=(8, 3))
    st.map("TButton",
           background=[("disabled", P["disabled_bg"]), ("pressed", P["select_bg"]), ("active", P["button_hover"])],
           foreground=[("disabled", P["disabled_fg"])],
           lightcolor=[("disabled", P["disabled_bg"]), ("active", P["button_hover"])],
           darkcolor=[("disabled", P["disabled_bg"]), ("active", P["button_hover"])])

    for name in ("TCheckbutton", "TRadiobutton"):
        st.configure(name, background=P["bg"], foreground=P["fg"], indicatorbackground=P["field"], indicatorforeground=P["accent"],
                     indicatorcolor=P["field"], focuscolor=P["accent"])
        st.map(name, background=[("active", P["bg"])], foreground=[("disabled", P["disabled_fg"])],
               indicatorcolor=[("selected", P["accent"]), ("disabled", P["disabled_bg"])],
               indicatorbackground=[("disabled", P["disabled_bg"])])

    for name in ("TEntry", "TSpinbox"):
        st.configure(name, fieldbackground=P["field"], foreground=P["fg"], insertcolor=P["fg"], bordercolor=P["border"],
                     lightcolor=P["border"], darkcolor=P["border"], selectbackground=P["select_bg"], selectforeground=P["select_fg"])
        st.map(name, fieldbackground=[("disabled", P["disabled_bg"]), ("readonly", P["surface"])],
               foreground=[("disabled", P["disabled_fg"])], bordercolor=[("focus", P["accent"])])
    st.configure("TSpinbox", arrowcolor=P["fg"], background=P["button_bg"])
    st.configure("TCombobox", fieldbackground=P["field"], background=P["button_bg"], foreground=P["fg"], arrowcolor=P["fg"],
                 bordercolor=P["border"], lightcolor=P["border"], darkcolor=P["border"], insertcolor=P["fg"],
                 selectbackground=P["select_bg"], selectforeground=P["select_fg"])
    st.map("TCombobox", fieldbackground=[("disabled", P["disabled_bg"]), ("readonly", P["surface"])],
           foreground=[("disabled", P["disabled_fg"]), ("readonly", P["fg"])],
           background=[("active", P["button_hover"]), ("disabled", P["disabled_bg"])],
           selectbackground=[("readonly", P["select_bg"])], selectforeground=[("readonly", P["select_fg"])],
           arrowcolor=[("disabled", P["disabled_fg"])], bordercolor=[("focus", P["accent"])])
    # випадний список Combobox -- це класичний tk.Listbox, ttk його не стилізує
    root.option_add("*TCombobox*Listbox.background", P["field"])
    root.option_add("*TCombobox*Listbox.foreground", P["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", P["select_bg"])
    root.option_add("*TCombobox*Listbox.selectForeground", P["select_fg"])
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    st.configure("TNotebook", background=P["bg"], bordercolor=P["border"], lightcolor=P["border"], darkcolor=P["border"], tabmargins=(2, 4, 2, 0))
    st.configure("TNotebook.Tab", background=P["surface"], foreground=P["muted"], bordercolor=P["border"], lightcolor=P["surface"],
                 darkcolor=P["surface"], padding=(10, 4))
    st.map("TNotebook.Tab", background=[("selected", P["button_bg"]), ("active", P["button_hover"])],
           foreground=[("selected", P["fg"]), ("active", P["fg"])],
           lightcolor=[("selected", P["button_bg"])], darkcolor=[("selected", P["button_bg"])])

    st.configure("Treeview", background=P["field"], fieldbackground=P["field"], foreground=P["fg"], bordercolor=P["border"],
                 lightcolor=P["border"], darkcolor=P["border"], rowheight=22)
    st.map("Treeview", background=[("selected", P["select_bg"])], foreground=[("selected", P["select_fg"])])
    st.configure("Treeview.Heading", background=P["surface"], foreground=P["fg"], bordercolor=P["border"], lightcolor=P["surface"],
                 darkcolor=P["surface"], relief="flat", padding=(6, 3))
    st.map("Treeview.Heading", background=[("active", P["button_hover"])], foreground=[("active", P["fg"])])

    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar", "TScrollbar"):
        st.configure(name, background=P["button_bg"], troughcolor=P["field"], bordercolor=P["border"], arrowcolor=P["fg"],
                     lightcolor=P["button_bg"], darkcolor=P["button_bg"], gripcount=0)
        st.map(name, background=[("active", P["button_hover"]), ("disabled", P["disabled_bg"])],
               arrowcolor=[("disabled", P["disabled_fg"])])

    for name in ("Horizontal.TProgressbar", "Vertical.TProgressbar", "TProgressbar"):
        st.configure(name, background=P["accent"], troughcolor=P["field"], bordercolor=P["border"], lightcolor=P["accent"],
                     darkcolor=P["accent"])
    st.configure("TPanedwindow", background=P["bg"])
    st.configure("Sash", background=P["border"], bordercolor=P["border"])


def style_window(win):
    """Тло для tk.Toplevel / tk.Tk (ttk-стиль на нього не діє)."""
    win.configure(bg=P["bg"])


def style_text(w, mono=True):
    """Класичний tk.Text / ScrolledText / Listbox."""
    opts = dict(bg=P["field"], fg=P["fg"], insertbackground=P["fg"], selectbackground=P["select_bg"], selectforeground=P["select_fg"],
                relief="flat", highlightthickness=1, highlightbackground=P["border"], highlightcolor=P["accent"], borderwidth=0)
    try:
        w.configure(**opts)
    except Exception:          # noqa: BLE001 -- Listbox не має insertbackground
        opts.pop("insertbackground", None)
        w.configure(**opts)
    # ScrolledText = Text + класичні Frame і Scrollbar: їх теж треба перефарбувати
    if hasattr(w, "frame"):
        w.frame.configure(bg=P["bg"])
    if hasattr(w, "vbar"):
        style_scrollbar(w.vbar)


def style_scrollbar(sb):
    sb.configure(bg=P["button_bg"], troughcolor=P["field"], activebackground=P["button_hover"], highlightbackground=P["bg"],
                 highlightthickness=0, relief="flat", borderwidth=0, elementborderwidth=1)


def style_menu(m):
    m.configure(bg=P["surface"], fg=P["fg"], activebackground=P["select_bg"], activeforeground=P["select_fg"], disabledforeground=P["disabled_fg"],
                borderwidth=0, relief="flat")


def walk(widget):
    """Усі нащадки віджета (включно з ним) -- для тесту, що обходить дерево."""
    yield widget
    for ch in widget.winfo_children():
        yield from walk(ch)
