# -*- coding: utf-8 -*-
"""gui_clipboard.py -- R36 B3: копіювання / вставляння / вирізання / «виділити все» у ВСІХ полях і таблицях, незалежно від розкладки клавіатури.

Проблема: стандартні прив'язки Tk (Ctrl+C / Ctrl+V / ...) спрацьовують за СИМВОЛОМ, який дає розкладка для фізичної клавіші. З українською чи
російською розкладкою фізична «V» видає «м», і Ctrl+V не розпізнається. Рішення тут -- ОДНА глобальна прив'язка на рівні КЛАСІВ віджетів
(bind_class: Entry / TEntry / Text / Spinbox / TSpinbox / TCombobox), що дивиться на КОД фізичної клавіші (event.keycode), а не на символ.
Кожне поле й кожен новий діалог отримують це автоматично; окремо підключати нічого не треба.

Коди фізичних клавіш (QWERTY-положення): Windows -- віртуальні коди VK_A/C/V/X = 65/67/86/88; X11 (evdev, у т. ч. Xvfb) -- 38/54/55/53.
Додатково розпізнається символ українських/російських літер, що стоять на тих клавішах (с, м, ч, ф), -- про всяк випадок для платформ, де код клавіші
не збігається. Alt (на Windows -- AltGr = Ctrl+Alt) комбінацію скасовує, щоб не красти введення символів.

Контекстне меню (права кнопка): Вирізати / Копіювати / Вставити / Виділити все. Недоступне не зникає, а сіре: «Вирізати» й «Вставити» -- лише в
редагованому полі, «Копіювати» -- коли щось виділено, «Вставити» -- коли в буфері є текст. Для таблиць (Treeview): Ctrl+C і пункт «Копіювати рядок»
кладуть у буфер вибрані рядки, значення стовпців розділено табуляцією (так вставляється в Excel). Для підписів (ttk.Label) -- «Копіювати текст».
Поля лише для читання й журнал (Text у стані disabled) дозволяють виділення мишею та копіювання."""
import sys
import tkinter as tk

import gui_theme as gt

# Коди фізичних клавіш (QWERTY): Windows VK та X11 evdev.
KEYCODES = {
    "copy": (67, 54),
    "paste": (86, 55),
    "cut": (88, 53),
    "all": (65, 38),
}
# Літери українських/російських розкладок на тих самих клавішах (keysym Tk): c -> с, v -> м, x -> ч, a -> ф
KEYSYMS = {
    "copy": ("Cyrillic_es", "Cyrillic_ES", "c", "C"),
    "paste": ("Cyrillic_em", "Cyrillic_EM", "v", "V"),
    "cut": ("Cyrillic_che", "Cyrillic_CHE", "x", "X"),
    "all": ("Cyrillic_ef", "Cyrillic_EF", "a", "A"),
}
CLASSES = ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "TCombobox")
TABLE_CLASSES = ("Treeview",)
ALT_MASK = 0x20000 if sys.platform == "win32" else 0x8
CTRL_MASK = 0x4
SHIFT_MASK = 0x1

LABELS = {"cut": "Вирізати", "copy": "Копіювати", "paste": "Вставити", "all": "Виділити все",
          "row": "Копіювати рядок", "text": "Копіювати текст"}


def action_for(event):
    """'copy' / 'paste' / 'cut' / 'all' для натискання Ctrl+<фізична клавіша>, або None (зокрема, коли затиснуто Alt)."""
    state = int(getattr(event, "state", 0) or 0)
    if not state & CTRL_MASK or state & ALT_MASK:
        return None
    kc = getattr(event, "keycode", None)
    for act, codes in KEYCODES.items():
        if kc in codes:
            return act
    sym = str(getattr(event, "keysym", "") or "")
    for act, syms in KEYSYMS.items():
        if sym in syms:
            return act
    return None


# --- стан віджета -----------------------------------------------------------------------------------------------------------------

def is_editable(w):
    try:
        if w.winfo_class() == "Text":
            return str(w.cget("state")) == "normal"
        if hasattr(w, "instate"):                       # ttk: Entry / Combobox / Spinbox
            return not (w.instate(["disabled"]) or w.instate(["readonly"]))
        return str(w.cget("state")) == "normal"         # класичні Entry / Spinbox
    except tk.TclError:
        return False


def has_selection(w):
    try:
        if w.winfo_class() == "Text":
            return bool(w.tag_ranges("sel"))
        return bool(w.selection_present())
    except (tk.TclError, AttributeError):
        return False


def has_content(w):
    try:
        if w.winfo_class() == "Text":
            return bool(w.get("1.0", "end-1c"))
        return bool(str(w.get()))
    except (tk.TclError, AttributeError):
        return False


def clipboard_has_text(w):
    try:
        return bool(w.clipboard_get())
    except tk.TclError:
        return False


def select_all(w):
    try:
        if w.winfo_class() == "Text":
            w.tag_add("sel", "1.0", "end-1c")
            w.mark_set("insert", "1.0")
        else:
            w.selection_range(0, "end")
            w.icursor("end")
    except (tk.TclError, AttributeError):
        pass


def _copy_selection(w):
    """Копіювання без залежності від стану віджета: у disabled-Text і readonly-полі стандартний <<Copy>> теж працює, але прямий шлях надійніший."""
    try:
        if w.winfo_class() == "Text":
            ranges = w.tag_ranges("sel")
            if not ranges:
                return False
            text = w.get(ranges[0], ranges[1])
        else:
            if not w.selection_present():
                return False
            text = w.selection_get()
        w.clipboard_clear()
        w.clipboard_append(text)
        return True
    except (tk.TclError, AttributeError):
        return False


def do_action(w, act):
    """Виконати 'copy' / 'paste' / 'cut' / 'all' над віджетом. True -- дію виконано."""
    if act == "all":
        select_all(w)
        return True
    if act == "copy":
        return _copy_selection(w)
    if not is_editable(w):
        return False
    if act == "cut":
        if _copy_selection(w):
            w.event_generate("<<Clear>>")
            return True
        return False
    if act == "paste":
        if not clipboard_has_text(w):
            return False
        w.event_generate("<<Paste>>")
        return True
    return False


def menu_items(w):
    """[(ключ, підпис, 'normal' | 'disabled')] -- те, що покаже контекстне меню поля w (для меню й для тесту)."""
    sel, edit = has_selection(w), is_editable(w)
    return [
        ("cut", LABELS["cut"], "normal" if (edit and sel) else "disabled"),
        ("copy", LABELS["copy"], "normal" if sel else "disabled"),
        ("paste", LABELS["paste"], "normal" if (edit and clipboard_has_text(w)) else "disabled"),
        ("all", LABELS["all"], "normal" if has_content(w) else "disabled"),
    ]


# --- таблиці ----------------------------------------------------------------------------------------------------------------------

def row_text(tree, iid):
    """Один рядок таблиці: значення стовпців через табуляцію (для дерева без стовпців -- його текст)."""
    vals = [str(v) for v in tree.item(iid, "values")]
    show = str(tree.cget("show"))
    if "tree" in show.split() and tree.item(iid, "text"):
        vals.insert(0, str(tree.item(iid, "text")))
    if not vals:
        vals = [str(tree.item(iid, "text"))]
    return "\t".join(vals)


def selected_rows_text(tree):
    return "\n".join(row_text(tree, i) for i in tree.selection())


def copy_rows(tree):
    """Вибрані рядки таблиці в буфер обміну. False, якщо нічого не вибрано."""
    text = selected_rows_text(tree)
    if not text:
        return False
    tree.clipboard_clear()
    tree.clipboard_append(text)
    return True


def table_menu_items(tree):
    return [("row", LABELS["row"], "normal" if tree.selection() else "disabled")]


# --- обробники подій --------------------------------------------------------------------------------------------------------------

def _on_ctrl_key(event):
    act = action_for(event)
    if act is None:
        return None
    do_action(event.widget, act)
    return "break"          # навіть якщо дія недоступна (нічого вставляти) -- стандартна прив'язка за символом не має спрацювати вдруге


def _on_table_key(event):
    act = action_for(event)
    if act == "copy":
        copy_rows(event.widget)
        return "break"
    if act == "all" and str(event.widget.cget("selectmode")) == "extended":
        event.widget.selection_set(event.widget.get_children())
        return "break"
    return None


def _post(menu, x, y):
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()


def _build_menu(parent, items, commands):
    m = tk.Menu(parent, tearoff=0)
    gt.style_menu(m)
    for key, label, state in items:
        if key == "sep":
            m.add_separator()
        else:
            m.add_command(label=label, state=state, command=commands[key])
    return m


def _on_context(event):
    w = event.widget
    try:
        w.focus_set()
    except tk.TclError:
        pass
    items = menu_items(w)
    cmds = {k: (lambda k=k: do_action(w, k)) for k, _l, _s in items}
    _post(_build_menu(w, items, cmds), event.x_root, event.y_root)
    return "break"


def _is_nav(tree):
    """Дерево розділів ліворуч -- навігація, а не таблиця даних: меню копіювання рядка йому не потрібне."""
    try:
        return str(tree.cget("style")).startswith("Nav.")
    except tk.TclError:
        return False


def _on_table_context(event):
    tree = event.widget
    if _is_nav(tree):
        return None
    try:
        tree.focus_set()
        row = tree.identify_row(event.y)
        if row and row not in tree.selection():
            tree.selection_set(row)
    except tk.TclError:
        pass
    items = table_menu_items(tree)
    _post(_build_menu(tree, items, {"row": lambda: copy_rows(tree)}), event.x_root, event.y_root)
    return "break"


def _on_label_context(event):
    lbl = event.widget
    try:
        text = str(lbl.cget("text"))
    except tk.TclError:
        return None
    items = [("text", LABELS["text"], "normal" if text else "disabled")]

    def _copy():
        lbl.clipboard_clear()
        lbl.clipboard_append(text)
    _post(_build_menu(lbl, items, {"text": _copy}), event.x_root, event.y_root)
    return "break"


def _on_text_press(event):
    """Disabled-Text (журнал, довідники) не бере фокус сам -- без нього Ctrl+C не потрапляє у віджет."""
    w = event.widget
    try:
        if str(w.cget("state")) == "disabled":
            w.focus_set()
    except tk.TclError:
        pass
    return None


def install(widget):
    """Увімкнути глобальні прив'язки для всього інтерпретатора Tcl, до якого належить widget (достатньо одного виклику; повторні -- нічого не роблять)."""
    root = widget._root()
    if getattr(root, "_gui_clipboard_installed", False):
        return
    for cls in CLASSES:
        root.bind_class(cls, "<Control-KeyPress>", _on_ctrl_key)
        root.bind_class(cls, "<Control-Key-a>", _on_ctrl_key)       # на X11 Tk за замовчуванням ставить сюди «початок рядка» -- робимо як у Windows: виділити все
        root.bind_class(cls, "<Control-Key-A>", _on_ctrl_key)
        root.bind_class(cls, "<Button-3>", _on_context)
    root.bind_class("Text", "<Button-1>", _on_text_press, add="+")
    for cls in TABLE_CLASSES:
        root.bind_class(cls, "<Control-KeyPress>", _on_table_key)
        root.bind_class(cls, "<Button-3>", _on_table_context)
    root.bind_class("TLabel", "<Button-3>", _on_label_context)
    root.bind_class("Label", "<Button-3>", _on_label_context)
    root._gui_clipboard_installed = True
