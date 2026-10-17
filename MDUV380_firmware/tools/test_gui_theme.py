#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тест R26 V3 (T8): темна тема. Обходить дерево віджетів УСІХ вікон прошивальника під віртуальним дисплеєм і перевіряє,
що жодне тло не світле, а текст контрастний. Контраст палітри перевіряється завжди; частина з Tk -- лише коли є tkinter і дисплей
(Xvfb: `xvfb-run -a python3 tools/test_gui_theme.py`); інакше друкує «ПРОПУЩЕНО» й повертає 0, щоб не валити хости без Tk.

Що тест НЕ доводить: системні діалоги messagebox/filedialog лишаються світлими (малює ОС) -- це зафіксовано в gui_theme.py і звіті R26.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gui_theme as gt  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def test_palette():
    for a, b in gt.CONTRAST_PAIRS:
        c = gt.contrast(gt.P[a], gt.P[b])
        check(c >= 4.5, "контраст %s на %s = %.2f (< 4,5)" % (a, b, c))
    for k, v in gt.P.items():
        check(re.fullmatch(r"#[0-9a-f]{6}", v) is not None, "палітра: %s = %r не #rrggbb" % (k, v))
    for k in ("bg", "surface", "field", "button_bg", "button_hover", "disabled_bg", "select_bg"):
        check(gt._lum(gt.P[k]) < 0.2, "тло %s має бути темним (яскравість %.2f)" % (k, gt._lum(gt.P[k])))
    # жодних кольорових літералів поза палітрою
    for fn in ("gui_flasher.py", "codeplug_viewer_gui.py", "gui_dialogs.py"):
        src = open(os.path.join(HERE, fn), encoding="utf-8").read()
        bad = re.findall(r"[\"']#[0-9a-fA-F]{3,6}[\"']", src)
        check(not bad, "%s: кольорові літерали поза палітрою: %r" % (fn, bad))
    src = open(os.path.join(HERE, "gui_flasher.py"), encoding="utf-8").read()
    check("gt.apply(self)" in src, "FlasherApp викликає gt.apply")
    check(len(re.findall(r"gt\.style_window\(self\)", src)) >= 2, "обидва Toplevel (AES, RCTL) викликають gt.style_window")


def light(color_hex):
    return gt._lum(color_hex) > 0.25


def to_hex(root, color):
    r, g, b = root.winfo_rgb(color)
    return "#%02x%02x%02x" % (r >> 8, g >> 8, b >> 8)


def test_widget_tree():
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("ПРОПУЩЕНО: нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО: нема DISPLAY (запусти через xvfb-run)")
        return
    try:
        import gui_flasher as gf
        import gui_dialogs as gd
        import codeplug_viewer_gui as cvg
        import cps_link as cl
        import test_cps_csv as tc
    except ImportError as e:
        print("ПРОПУЩЕНО: нема залежностей для вікон (%s)" % e)
        return
    app = gf.FlasherApp()
    try:
        app.update()
        spi = tc.make_fixture_spi()
        cp, _data = tc.codeplug_of(spi)
        wins = [app, gf.AesKeyManagerWindow(app), gf.RctlConfigWindow(app), cvg.CodeplugViewerWindow(app, cp, "тест", HERE)]
        dlg, _r = gd._build(app, "Тест", "Рядок 1\nРядок 2", [("Так", True), ("Ні", False)], 1)
        wins.append(dlg)
        pop_menu = tk.Menu(app, tearoff=0)
        gt.style_menu(pop_menu)
        wins.append(pop_menu)
        # випадний список Combobox
        cb = ttk.Combobox(app, values=("а", "б"), state="readonly")
        cb.pack()
        app.update()
        pop = app.tk.call("ttk::combobox::PopdownWindow", str(cb))
        lb_bg = str(app.tk.call(str(pop) + ".f.l", "cget", "-background"))
        for w in wins:
            w.update()
        style = ttk.Style(app)
        seen = {}
        for win in wins:
            for w in gt.walk(win):
                cls = w.winfo_class()
                seen[cls] = seen.get(cls, 0) + 1
                if cls.startswith("T") or cls in ("Treeview",):
                    bg = style.lookup(cls, "troughcolor" if cls == "TProgressbar" else "background") or style.lookup(".", "background")
                    bg = to_hex(app, bg) if bg else gt.P["bg"]
                    check(not light(bg), "%s %s: ttk-тло %s світле" % (cls, w, bg))
                    fg = style.lookup(cls, "foreground") or style.lookup(".", "foreground")
                    if fg and cls != "TProgressbar":
                        check(gt.contrast(to_hex(app, fg), bg if cls != "TEntry" else gt.P["field"]) >= 4.5,
                              "%s %s: контраст тексту %s на %s < 4,5" % (cls, w, fg, bg))
                else:
                    try:
                        bg = to_hex(app, w.cget("background"))
                    except tk.TclError:
                        continue
                    check(not light(bg), "%s %s: tk-тло %s світле (тема не застосована)" % (cls, w, bg))
                    try:
                        fg = to_hex(app, w.cget("foreground"))
                        check(gt.contrast(fg, bg) >= 4.5, "%s %s: контраст %s на %s < 4,5" % (cls, w, fg, bg))
                    except tk.TclError:
                        pass
        # кольори статусів вікна прошивальника -- зі словом, і з контрастом на тлі
        for lab in (app.status_label,):
            fg = to_hex(app, str(lab.cget("foreground")))
            check(gt.contrast(fg, gt.P["bg"]) >= 4.5 and lab.cget("text"), "статус «%s»: колір %s контрастний і є слово" % (lab.cget("text"), fg))
        check(not light(to_hex(app, lb_bg)), "випадний список Combobox темний: %s" % lb_bg)
        # Treeview-рядки й виділення
        sel = style.lookup("Treeview", "background", ["selected"])
        check(sel and not light(to_hex(app, sel)), "виділений рядок Treeview темний")
        # перевірка, що в дереві справді були всі потрібні типи віджетів
        for need in ("TButton", "TLabel", "TFrame", "TEntry", "TCheckbutton", "Treeview", "TScrollbar", "TProgressbar", "Text", "TCombobox", "TNotebook"):
            check(need in seen or need == "TEntry" and "TEntry" in seen, "у вікнах був віджет %s (є що перевіряти)" % need)
        # clam
        check(style.theme_use() == "clam", "ttk-тема clam")
    finally:
        app.destroy()


def main():
    test_palette()
    test_widget_tree()
    if FAILS:
        print("test_gui_theme: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_gui_theme: усі перевірки пройшли (контраст палітри >= 4,5; дерево віджетів усіх вікон темне).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
