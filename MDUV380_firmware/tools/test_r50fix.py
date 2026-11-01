#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R50-fix: тести верстки не залежать від випадкового шрифту хоста чи CI.

S1  вікно CPS (усі розділи, крім «Супутники» -- це R52; БЕЗ інших винятків, R51) на 1024x768 при сценаріях шрифт × масштаб (system / DejaVu Sans × 100/125/150 %): жоден підпис, кнопка,
    поле чи заголовок рамки не обрізані (layout_probe). Стан «з кодплагом» -- на найбільшому масштабі кожного шрифту, «без кодплага» -- на всіх;
S2  Q1 (область панелі при мінімальному й великому вікні): «службова» висота (меню, панель документа, журнал) росте разом із шрифтом, тому межа масштабується
    з відсотком; число для 100 % -- те саме, що в test_cps_ui (310 / 270 px);
S5  мінімальний розмір головного вікна = 760x520 × масштаб (не більше екрана); на ньому верхня панель документа не обрізана, область панелі не менша за 200 px × масштаб;
S3  зонд у цьому режимі справді бачить обрізання: звужене поле списку на DejaVu Sans 100 % знайдено;
S4  «Відновити…» перевіряє test_r50.py (F2.2); тут лише підключення до run_tests.sh.
Запуск: xvfb-run -a python3.12 tools/test_r50fix.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []
FW = os.path.dirname(HERE)
EXCLUDE = {"satellites"}          # розділ «Супутники» -- зона R52; його знахідки лише названо у звіті (DejaVu Sans 100 %: список джерел 375 px у полі 356 px)
SMALL_CHROME, BIG_CHROME = 310, 270   # межі test_cps_ui Q1 при 100 %


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def sc_list(root):
    import font_scenarios as fs
    return [sc for sc in fs.scenarios(root, families=(None, "DejaVu Sans")) if sc[1] in (100, 125, 150)]


def new_app(_spath, sc):
    """Свіже вікно зі СВОЇМИ налаштуваннями на кожен сценарій (інакше розмір вікна й межі, збережені попереднім сценарієм, змінюють умови)."""
    import font_scenarios as fs
    import test_r36 as t36
    spath = os.path.join(tempfile.mkdtemp(prefix="r50fix_ui_"), "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    app = t36.make_app(spath)
    fs.apply(app, sc)
    t36.spin(app, 0.3)
    return app


def test_s1_s2():
    import font_scenarios as fs
    import layout_probe as lp
    import test_r36 as t36
    tmp = tempfile.mkdtemp(prefix="r50fix_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    mk = t36.doc_factory()
    import tkinter as tk
    probe_root = tk.Tk()
    scs = sc_list(probe_root)
    probe_root.destroy()
    check(len(scs) >= 3 and {p for _f, p in scs} == {100, 125, 150}, "S1: сценарії охоплюють 100/125/150 %%: %r" % (scs,))
    max_pct = {}
    for fam, pct in scs:
        max_pct[fam] = max(max_pct.get(fam, 0), pct)
    n_runs = 0
    scales = []
    for sc in scs:
        app = new_app(spath, sc)
        try:
            keys = [k for k in app.section_keys() if not k.startswith("grp_") and k not in EXCLUDE]
            # R51: винятків нема -- ні за масштабом, ні за станом кодплага: кожен сценарій проходить розділи і без кодплага, і з ним
            res = lp.run_all(app, sizes=((1024, 768),), keys=keys, doc_states=(None, mk))
            lines = lp.format_report(res)
            check(not lines, "S1 [%s]: обрізаний текст у %d місцях:\n  %s" % (fs.label(sc), len(lines), "\n  ".join(l[:230] for l in lines[:10])))
            n_runs += 1
            # S2: область панелі
            app.set_document(mk())
            k = sc[1] / 100.0
            for (W, H, chrome) in ((760, 520, SMALL_CHROME), (1800, 1000, BIG_CHROME)):
                app.geometry("%dx%d" % (W, H))
                lp.spin(app, 0.4)
                rw, rh = app.right.winfo_width(), app.right.winfo_height() - app.docbar.winfo_height()
                limit = int(round(chrome * k))
                check(rh >= H - limit, "S2 [%s] %dx%d: область панелі %dx%d -- службова висота %d > %d" % (fs.label(sc), W, H, rw, rh, H - rh, limit))
                check(rw >= W - 420 * k - 1, "S2 [%s] %dx%d: область панелі вужча, ніж треба (%d)" % (fs.label(sc), W, H, rw))
            # S5 (R51 Б2): мінімальний розмір головного вікна росте з масштабом, а на ньому верхня панель документа й область панелі не обрізані
            app.apply_min_size()
            mn = app.minsize()
            sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
            want = (min(int(round(760 * k)), max(760, sw - 40)), min(int(round(520 * k)), max(520, sh - 80)))
            check(abs(mn[0] - want[0]) <= 1 and abs(mn[1] - want[1]) <= 1, "S5 [%s]: мінімальний розмір вікна %r, очікувано %r (760x520 × масштаб, не більше екрана)" % (fs.label(sc), mn, want))
            check(mn[0] >= 760 and mn[1] >= 520, "S5 [%s]: мінімум не менший за 760x520 (%r)" % (fs.label(sc), mn))
            app.geometry("%dx%d" % tuple(mn))
            lp.spin(app, 0.5)
            for key in ("basic", "zones", "tglists", "dtmf"):
                app.show(key)
                lp.spin(app, 0.5)
                bad = [(lp._path(w)[-40:], lp.probe_widget(w)) for w in lp.walk_viewable(app.docbar) if lp.probe_widget(w)]
                check(not bad, "S5 [%s] %s на мінімальному розмірі %r: верхня панель обрізана: %r" % (fs.label(sc), key, mn, bad[:2]))
                rw, rh = app.right.winfo_width(), app.right.winfo_height() - app.docbar.winfo_height()
                check(rh >= 200 * k, "S5 [%s] %s на мінімальному розмірі %r: область панелі лише %dx%d" % (fs.label(sc), key, mn, rw, rh))
                bad = lp.probe_panel(app, key)
                check(not bad, "S5 [%s] %s на мінімальному розмірі %r: обрізано: %r" % (fs.label(sc), key, mn, bad[:2]))
            scales.append((sc[1], tuple(mn)))
            app.set_document(None)
        finally:
            try:
                app.update()                     # виконати відкладені after_idle (refit таблиць) ДО знищення вікна -- без «invalid command name» у виводі
            except Exception:  # noqa: BLE001
                pass
            app.destroy()
    by_pct = {}
    for pct, mn in scales:
        by_pct.setdefault(pct, []).append(mn)
    check(min(by_pct[150])[0] > min(by_pct[125])[0] > min(by_pct[100])[0] - 1 and min(by_pct[150])[1] >= min(by_pct[125])[1] >= min(by_pct[100])[1],
          "S5: мінімум росте з масштабом: %r" % (by_pct,))
    print("test_r50fix: S1/S2 -- сценаріїв %d, повних проходів по розділах %d" % (len(scs), n_runs))


def test_s3_probe_sees():
    import font_scenarios as fs
    import layout_probe as lp
    import test_r36 as t36
    tmp = tempfile.mkdtemp(prefix="r50fix3_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    import tkinter as tk
    pr = tk.Tk()
    have = "DejaVu Sans" in set(__import__("tkinter.font", fromlist=["x"]).families(pr))
    pr.destroy()
    sc = ("DejaVu Sans", 100) if have else (None, 150)
    app = new_app(spath, sc)
    try:
        app.show("themes")
        t36.spin(app, 0.6)
        p = app.get_panel("themes")
        check(not lp.probe_panel(app, "themes"), "S3 [%s]: Теми без обрізання у вихідному стані: %r" % (fs.label(sc), lp.probe_panel(app, "themes")[:2]))
        p.screen_combo.config(width=8)                       # навмисно звужене поле
        t36.spin(app, 0.6)
        found = lp.probe_panel(app, "themes")
        check(found, "S3 [%s]: зонд бачить навмисно звужене поле списку екранів" % fs.label(sc))
    finally:
        app.destroy()


def test_s4_wiring():
    rt = open(os.path.join(FW, "tests", "run_tests.sh"), encoding="utf-8").read()
    check("test_r50fix" in rt, "S4: test_r50fix.py підключено до tests/run_tests.sh")


def main():
    test_s4_wiring()
    try:
        import tkinter  # noqa: F401
        have = bool(os.environ.get("DISPLAY"))
    except ImportError:
        have = False
    if have:
        test_s1_s2()
        test_s3_probe_sees()
    else:
        print("test_r50fix: нема tkinter/DISPLAY -- S1-S3 пропущено")
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        for f in FAILS[:6]:                      # run_tests.sh показує лише останні рядки виводу -- причини мають бути серед них
            print("  -", f[:300].replace("\n", " | "))
        sys.exit(1)
    print("test_r50fix: усе гаразд")


if __name__ == "__main__":
    main()
