#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R79: розкладка CPS -- панель документа, дерево, журнал, межі, діалоги.
Хост-частина: збережені налаштування (зіпсований файл, не словник, вікно поза екраном) безпечні; усі модулі з Toplevel роблять вікна зміннорозмірними.
Tk-частина (xvfb), для масштабів 1.0/1.25/1.5/2.0 × (системний, DejaVu, Liberation), сценарій застосовується ДО побудови вікна (реалістичні розміри):
  1  підпис стану рації не перекривається кнопкою поруч (у т.ч. після зміни тексту «рації нема» -> «COM12»: причина R79 -- FlowFrame не перераховувався);
  2  довгий жовтогарячий рядок переноситься: wraplength не більший за ширину панелі, правий край у межах панелі;
  3  дерево: усі пункти досяжні (смуга прокрутки з'являється, коли не вміщується; see() останнього пункту), стовпець не вужчий за найдовшу назву;
  4  межі: перетягування журналу й дерева працює, мінімуми дотримуються, нічого не зникає; (R98-FIX9: кнопок «Збільшити»/«Зменшити» нема -- висоту журналу міняють межею, вона з «хватом»);
  5  діалог: зміннорозмірний, мінімальний розмір задано, віджети розтягуються.
Запуск: xvfb-run -a python3.12 tools/test_r79.py"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []
PASSED = [0]
LONG = ("Запис у рацію: Рацію не знайдено. Підключи USB-кабель і увімкни рацію звичайним способом (НЕ в DFU) -- програма знайде її сама; "
        "«Оновити» у розділі «Підключення і діагностика».")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def t_settings():
    from cps_ui.settings import Settings
    d = tempfile.mkdtemp(prefix="r79_")
    for name, body in (("bad", "{не json"), ("list", "[1,2,3]"), ("empty", ""), ("null", "null")):
        p = os.path.join(d, name + ".json")
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        s = Settings(p)
        check(isinstance(s.data, dict) and s.get("width", 777) == 777, "R79: файл налаштувань «%s» не ламає завантаження" % name)
        check(s.save() and isinstance(json.load(open(p, encoding="utf-8")), dict), "R79: після зіпсованого «%s» файл перезаписується коректно" % name)
    check(Settings(os.path.join(d, "нема.json")).get("x") is None, "R79: файла нема -- типові значення")
    # усі модулі з Toplevel роблять вікна зміннорозмірними
    bad = []
    for root, _dirs, files in os.walk(HERE):
        if "__pycache__" in root:
            continue
        for fn in files:
            if not fn.endswith(".py") or fn.startswith("test_") or fn == "tooltip.py":   # tooltip -- не діалог
                continue
            src = open(os.path.join(root, fn), encoding="utf-8").read()
            if "tk.Toplevel(" in src and not ("remember_window" in src or "resizable(True" in src or "_small_window" in src or "_build(" in src):
                bad.append(fn)
    check(not bad, "R79: модулі з Toplevel без зміннорозмірності: %r" % bad)


def build(sc):
    import font_scenarios as fs
    import cps_ui.app as A
    import test_r54_ui as t54
    orig = A.CpsApp._build_ui

    def patched(self):
        fs.apply(self, sc)
        return orig(self)
    A.CpsApp._build_ui = patched
    try:
        return t54.new_app(None)
    finally:
        A.CpsApp._build_ui = orig


def t_tk():
    import tkinter as tk
    import font_scenarios as fs
    import layout_probe as lp
    import gui_dialogs as gd
    from tkinter import ttk
    root = tk.Tk()
    scs = fs.scenarios(root, families=(None, "DejaVu Sans", "Liberation Sans"), percents=(100, 125, 150, 200))
    root.destroy()
    for sc in scs:
        lab = fs.label(sc)
        app = build(sc)
        try:
            app.apply_min_size()
            mw, mh = app.min_window_size()
            app.geometry("%dx%d" % (mw, mh))
            lp.spin(app, 0.4)
            # 1. стан рації
            for state, port in (("absent", None), ("found", "COM12"), ("found", "COM123456"), ("unknown", None), ("absent", None)):
                app.conn.state, app.conn.port = state, port
                app._refresh_all()
                lp.spin(app, 0.25)
                r = app.docbar_radio
                row1 = [b for b in app.docbtn.values() if abs(b.winfo_y() - r.winfo_y()) < 4 and b.winfo_x() > r.winfo_x()]
                if row1:
                    nxt = min(row1, key=lambda b: b.winfo_x())
                    check(nxt.winfo_x() >= r.winfo_x() + r.winfo_width(), "R79 [%s, %s]: кнопка x=%d налізає на підпис стану (x=%d, w=%d)" % (lab, state, nxt.winfo_x(), r.winfo_x(), r.winfo_width()))
                import tkinter.font as tkfont
                ys = sorted(set(b.winfo_y() for b in app.docbtn.values()))
                check(len(ys) <= 2, "R79B [%s, %s]: кнопки панелі документа в %d рядках (має бути не більше 2): %r; ширина рядка %d" % (lab, state, len(ys), ys, app._docbtn_row.winfo_width()))
                need = tkfont.Font(root=app, font=r.cget("font")).measure(r.cget("text"))
                check(r.winfo_width() >= need, "R79 [%s, %s]: підпис стану обрізано (ширина %d < текст %d)" % (lab, state, r.winfo_width(), need))
            # 2. жовтогарячий рядок
            for size in ((mw, mh), (1000, 680), (1300, 760)):
                app.geometry("%dx%d" % size)
                lp.spin(app, 0.3)
                app.docbar_note.config(text=LONG)
                if not app._docbar_note_shown:
                    app.docbar_note.pack(anchor="w", padx=12, pady=(0, 2))
                    app._docbar_note_shown = True
                lp.spin(app, 0.3)
                bw = app.docbar.winfo_width()
                n = app.docbar_note
                check(int(n.cget("wraplength")) <= bw, "R79 [%s, %s]: wraplength %s > ширини панелі %d" % (lab, size, n.cget("wraplength"), bw))
                check(n.winfo_x() + n.winfo_width() <= bw, "R79 [%s, %s]: рядок виходить за край панелі (%d > %d)" % (lab, size, n.winfo_x() + n.winfo_width(), bw))
            # 3. дерево
            app.geometry("%dx%d" % (mw, mh))
            lp.spin(app, 0.3)
            t = app.tree
            last = None
            for g in t.get_children(""):
                for c in t.get_children(g):
                    last = c
            t.yview_moveto(1.0)              # прокрутити до кінця (see() ttk на неціловому рядку помиляється на один рядок -- це не вада програми)
            lp.spin(app, 0.2)
            bb = t.bbox(last)
            check(bool(bb) and bb[1] >= 0 and bb[1] + bb[3] <= t.winfo_height() + 2, "R79 [%s]: останній пункт дерева недосяжний: bbox=%r h=%d" % (lab, bb, t.winfo_height()))
            first = t.get_children("")[0]
            t.see(first)
            lp.spin(app, 0.2)
            check(bool(t.bbox(first)), "R79 [%s]: перший пункт дерева («%s») недосяжний" % (lab, t.item(first, "text")))
            rows = sum(1 + len(t.get_children(g)) for g in t.get_children(""))
            rowh = max(1, (t.bbox(first) or (0, 0, 0, 20))[3])
            fits = rows * rowh <= t.winfo_height()
            check(app.tree_vsb.winfo_ismapped() == (not fits), "R79 [%s]: смуга прокрутки дерева (видима=%s) не відповідає вмісту (рядків %d×%d px, висота %d)" % (lab, app.tree_vsb.winfo_ismapped(), rows, rowh, t.winfo_height()))
            check(int(t.column("#0", "minwidth")) >= 50, "R79 [%s]: стовпець дерева без мінімальної ширини" % lab)
            # 4. межі
            app.geometry("1100x760")
            lp.spin(app, 0.4)
            pl, pt = app.pane_log, app.pane_tree
            pl.set(0)
            lp.spin(app, 0.2)
            check(pl.position() >= 160, "R79 [%s]: журнал підняли до верху -- верхня частина %d px (має лишитись >= 160)" % (lab, pl.position()))
            pl.set(10 ** 5)
            lp.spin(app, 0.2)
            check(app.vpane.winfo_height() - pl.position() >= 40, "R79 [%s]: журнал стиснуто до %d px (має лишитись >= 40)" % (lab, app.vpane.winfo_height() - pl.position()))
            pt.set(0)
            lp.spin(app, 0.2)
            check(pt.position() >= 160, "R79 [%s]: дерево стиснуто до %d px" % (lab, pt.position()))
            pt.set(10 ** 5)
            lp.spin(app, 0.2)
            check(app.hpane.winfo_width() - pt.position() >= 360, "R79 [%s]: права частина стиснута до %d px (має лишитись >= 360)" % (lab, app.hpane.winfo_width() - pt.position()))
            check(app.docbar.winfo_ismapped() and app.log_text.winfo_ismapped() and app.tree.winfo_ismapped(), "R79 [%s]: після тягання межі щось зникло: docbar=%s log=%s tree=%s" % (lab, app.docbar.winfo_ismapped(), app.log_text.winfo_ismapped(), app.tree.winfo_ismapped()))
            pl.set(app.vpane.winfo_height() - app._default_log_height())
            pt.set(300)
            lp.spin(app, 0.2)
            h0 = app.vpane.winfo_height() - pl.position()
            # R98-FIX9 Г: кнопок «Збільшити»/«Зменшити» над журналом нема (висоту журналу міняють межею мишкою); типова висота -- як і була
            check(not hasattr(app, "log_big_btn") and not hasattr(app, "toggle_log_big"), "R98-FIX9 Г [%s]: у застосунку лишилась кнопка/метод «Збільшити»/«Зменшити» журналу" % lab)
            labels = []
            stack = [app]
            while stack:
                w = stack.pop()
                try:
                    labels.append(str(w.cget("text")))
                except tk.TclError:
                    pass
                stack.extend(w.winfo_children())
            check(not any(t in ("Збільшити", "Зменшити") for t in labels), "R98-FIX9 Г [%s]: у вікні є віджет «Збільшити»/«Зменшити»" % lab)
            want0 = max(app._default_log_height(), app._min_log_height())   # на великих масштабах мінімум (заголовок + 2 рядки) вищий за типові 100 px
            check(abs(h0 - want0) <= 6, "R98-FIX9 Г [%s]: типова висота журналу %d, очікувано ~%d" % (lab, h0, want0))
            # межу видно й легко захопити: зона >= 5 px, «хват» (крапки) задано, на межі курсор зміни розміру
            st = ttk.Style(app)
            thick = int(str(st.lookup("Sash", "sashthickness") or 0))
            grip = int(str(st.lookup("Sash", "gripcount") or 0))
            check(thick >= 5 and grip >= 10, "R98-FIX9 Г3 [%s]: межа журналу -- товщина %d px (>= 5), крапок «хвата» %d (>= 10)" % (lab, thick, grip))
            app.vpane.event_generate("<Motion>", x=app.vpane.winfo_width() // 2, y=app.vpane.sashpos(0) + 2, warp=True)
            lp.spin(app, 0.2)
            check("double_arrow" in str(app.vpane.cget("cursor")), "R98-FIX9 Г3 [%s]: на межі журналу курсор зміни розміру (є «%s»)" % (lab, app.vpane.cget("cursor")))
            pl.set(app.vpane.winfo_height() - app._default_log_height() - 150)
            lp.spin(app, 0.3)
            h1 = app.vpane.winfo_height() - pl.position()
            check(h1 > h0 + 80, "R98-FIX9 Г [%s]: межею журнал збільшується (%d -> %d)" % (lab, h0, h1))
            pl.reset()
            lp.spin(app, 0.3)
            h2 = app.vpane.winfo_height() - pl.position()
            check(abs(h2 - h0) <= 4, "R98-FIX9 Г [%s]: подвійне клацання (reset) повертає типову висоту (%d -> %d)" % (lab, h2, h0))
            # 5. діалог
            win = tk.Toplevel(app)
            ttk.Label(win, text="Тест").pack(fill="both", expand=True)
            gd.remember_window(win, "r79_test", minsize=(300, 200), fit=True)
            lp.spin(app, 0.2)
            check(tuple(win.resizable()) == (1, 1) or tuple(win.resizable()) == (True, True), "R79 [%s]: діалог не зміннорозмірний" % lab)
            mw2, mh2 = win.minsize()
            check(mw2 >= 300 and mh2 >= 200, "R79 [%s]: у діалога нема мінімального розміру" % lab)
            win.destroy()
        finally:
            app.destroy()
    # збережене вікно поза екраном
    app = build(scs[0])
    try:
        sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
        for x, y in ((sw + 500, 10), (-5000, 10), (10, sh + 500), ("a", None), (None, None)):
            app.settings.set("x", x)
            app.settings.set("y", y)
            pos = app._saved_position(900, 600, sw, sh)
            check(pos == "", "R79: збережене положення (%r, %r) поза екраном відкинуто (%r)" % (x, y, pos))
    finally:
        app.destroy()


def main():
    tk_ok = False
    try:
        import tkinter  # noqa: F401
        tk_ok = bool(os.environ.get("DISPLAY"))
    except ImportError:
        pass
    tests = [t_settings] + ([t_tk] if tk_ok else [])
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            FAILS.append("%s: виняток %s: %s" % (t.__name__, type(e).__name__, e))
            traceback.print_exc()
    if FAILS:
        print("test_r79: %d провалів" % len(FAILS))
        return 1
    print("test_r79: усе гаразд (%d перевірок: стан рації, рядок-причина, дерево, межі, діалоги, налаштування)%s." % (PASSED[0], "" if tk_ok else " -- Tk-частину пропущено (нема DISPLAY)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
