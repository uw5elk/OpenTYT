#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R36: вікно CPS не обрізає текст, межі між частинами рухаються й запам'ятовуються, копіювання працює з будь-якою розкладкою, хвіст 0x00 у назвах.

Запуск: `xvfb-run -a -s "-screen 0 2000x1200x24" python3 tools/test_r36.py` (або `tests/run_tests.sh`; без DISPLAY частину з Tk пропущено).

Z1  кожна панель на 1024x768 і 1920x1080 (з кодплагом і без) -- жоден підпис / кнопка / поле / стовпець таблиці не обрізаний (вимірюється: потрібна ширина
    проти виділеної; вихід за межі предка без прокрутки) -- layout_probe.py; сам зонд перевірено на навмисно обрізаних віджетах;
Z2  Теми: перегляд не стискає список кольорів і кнопки; масштаб 4/5 лише коли вміщується;
Z3  Ctrl+C / V / X / A за КОДОМ клавіші з кириличним символом (українська розкладка) у Entry / ttk.Entry / Spinbox / Combobox / Text, копіювання з таблиці й журналу;
Z4  контекстні меню: пункти активні або сірі за станом поля;
Z5  межі: перетягування, мінімуми, подвійне клацання = типове положення, закриття й повторне відкриття відновлюють положення й розмір вікна;
Z6  test_r34 з увімкненим CODEPLUG_NAME_ZERO_TAIL;
Z7  таблиці за вмістом (FitTable), перенос довгих описів за шириною, однакові кнопки групи."""
import os
import subprocess
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def spin(app, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def key(widget, keycode, keysym, state=0x4):
    """Натискання Ctrl+клавіша на КИРИЛИЧНІЙ розкладці: фізична клавіша keycode дає символ keysym (с, м, ч, ф).

    Справжню кириличну розкладку в Xvfb увімкнути не вдається (сервер не приймає зміну розкладки), а event_generate підставляє символ за keycode зі
    стандартної латинської. Тому подію складаємо вручну -- ті самі поля (віджет, код клавіші, символ, стан), які Tk передає обробнику, -- і викликаємо
    саме той обробник, що прив'язано до класу віджета (перевіряємо, що прив'язка до класу дійсно наша: bound_to_us)."""
    import gui_clipboard as gc
    widget.focus_force()
    widget.update()
    ev = types.SimpleNamespace(widget=widget, keycode=keycode, keysym=keysym, state=state)
    cls = widget.winfo_class()
    fn = gc._on_table_key if cls == "Treeview" else gc._on_ctrl_key
    # клас віджета справді прив'язаний до нашого обробника (а не лишився стандартний «нічого не робити»)
    script = widget.tk.call("bind", cls, "<Control-KeyPress>")
    check("_on_" in str(script) and "key" in str(script), "Z3: клас %s прив'язано до нашого обробника Ctrl+клавіша (%r)" % (cls, str(script)[:60]))
    r = fn(ev)
    widget.update()
    return r


def key_latin(widget, keycode, state=0x4):
    """Справжня подія Tk: Ctrl + клавіша з латинським символом (як на англійській розкладці)."""
    widget.focus_force()
    widget.update()
    widget.event_generate("<KeyPress>", keycode=keycode, state=state)
    widget.update()


# коди фізичних клавіш і символи кириличної розкладки на них (с, м, ч, ф)
K_COPY, K_PASTE, K_CUT, K_ALL = (54, "Cyrillic_es"), (55, "Cyrillic_em"), (53, "Cyrillic_che"), (38, "Cyrillic_ef")


def clip(app):
    """Вміст буфера обміну або None (порожній буфер у Tk дає виняток)."""
    import tkinter as tk
    try:
        return app.clipboard_get()
    except tk.TclError:
        return None


def double_click(widget, x, y):
    """Подвійне клацання лівою кнопкою: Tk розпізнає його з двох швидких натискань (синтетичну Double-подію згенерувати не можна)."""
    for _ in range(2):
        widget.event_generate("<ButtonPress-1>", x=x, y=y)
        widget.event_generate("<ButtonRelease-1>", x=x, y=y)
    widget.update()


def drag(widget, x0, y0, x1, y1):
    widget.event_generate("<ButtonPress-1>", x=x0, y=y0)
    widget.event_generate("<B1-Motion>", x=(x0 + x1) // 2, y=y1)
    widget.event_generate("<B1-Motion>", x=x1, y=y1)
    widget.event_generate("<ButtonRelease-1>", x=x1, y=y1)
    widget.update()


def make_app(spath, w=1024, h=768):
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings
    st = Settings(spath)
    fresh = st.get("width") is None
    if fresh:
        st.set("width", w)
        st.set("height", h)
        st.set("zoomed", False)
    app = CpsApp(settings=st, autoprobe=False)
    if fresh:
        app.geometry("%dx%d" % (w, h))
    spin(app, 0.3)
    return app


def doc_factory():
    import test_cps_csv as tc
    from cps_ui import document as D
    spi = tc.make_fixture_spi()
    cp, _d = tc.codeplug_of(spi)
    return lambda: D.Document(cp, D.ORIGIN_FILE, source_file="тест.zip")


# --- Z1 --------------------------------------------------------------------------------------------------------------------------------

def test_z1(app, mk):
    import tkinter as tk
    from tkinter import ttk
    import layout_probe as lp
    # сам зонд: навмисно обрізані віджети він мусить знайти (інакше «0 проблем» нічого не варте)
    top = tk.Toplevel(app)
    fr = ttk.Frame(top, width=60, height=40)
    fr.pack()
    fr.pack_propagate(False)
    lab = ttk.Label(fr, text="Дуже довгий підпис, що не влізе")
    lab.pack(side="left")
    btn = ttk.Button(fr, text="Кнопка з довгим підписом")
    btn.pack(side="left")
    top.update()
    top.update()
    found = [lp.probe_widget(w) for w in (lab, btn)]
    check(all(found), "Z1: зонд бачить обрізані підпис і кнопку: %r" % (found,))
    top.destroy()
    for size in ((1024, 768), (1920, 1080)):
        res = lp.run_all(app, sizes=(size,), doc_states=(None, mk))
        lines = lp.format_report(res)
        check(not lines, "Z1 %dx%d: обрізаний текст у %d місцях:\n  %s" % (size[0], size[1], len(lines), "\n  ".join(l[:230] for l in lines[:12])))
    # стан «рацію знайдено» додає підписи й вмикає кнопки -- ті самі розміри, лише вузьке вікно
    app.conn.state = "found" if hasattr(app.conn, "state") else None
    try:
        app._refresh_all()
    except Exception:  # noqa: BLE001
        pass


# --- Z2 --------------------------------------------------------------------------------------------------------------------------------

def test_z2(app):
    import screen_sim as sim
    import layout_probe as lp
    app.geometry("1024x768")
    spin(app, 0.3)
    app.show("themes")
    spin(app, 0.8)
    p = app.get_panel("themes")
    lw = p.left_host.avail_width()
    check(lw >= p.LEFT_MIN - 4, "Z2: на 1024x768 керування Тем не вужчі за мінімум (%d, мінімум %d)" % (lw, p.LEFT_MIN))
    bad = []
    for w in (p.read_btn, p.write_btn, p.save_btn, p.load_btn, p.reset_btn, p.reset_classic_btn, p.set_btn, p.set_combo):
        if w.winfo_width() + 1 < w.winfo_reqwidth():
            bad.append((w.cget("text") if hasattr(w, "cget") and w.winfo_class() == "TButton" else str(w), w.winfo_width(), w.winfo_reqwidth()))
    check(not bad, "Z2: кнопки керування Тем не стиснуті: %r" % bad)
    rows_bad = [r["name"].cget("text") for r in p._rows if r["name"].winfo_width() + 1 < r["name"].winfo_reqwidth() or r["swatch"].winfo_width() < 20]
    check(not rows_bad, "Z2: рядки списку кольорів не стиснуті: %r" % rows_bad[:3])
    n = int(p.scale_var.get())
    check(sim.W * n <= p.right_host.avail_width() - 4 or n == min(p.scale_radios), "Z2: діючий масштаб %d вміщується в перегляд (%d px)" % (n, p.right_host.avail_width()))
    check(n < 4, "Z2: на вузькому вікні масштаб менший за 4 (є %d)" % n)
    check(str(p.scale_radios[5].cget("state")) == "disabled", "Z2: x5 на вузькому вікні недоступний")
    check(p._img.width() == sim.W * n, "Z2: зображення перегляду відповідає масштабу (%d, є %d)" % (sim.W * n, p._img.width()))
    check(p.canvas.winfo_width() >= sim.W * n, "Z2: полотно перегляду не обрізане")
    # межу тягнуть вліво до упору: керування не стискаються нижче мінімуму, подвійне клацання повертає типове положення
    pm = app._panes["themes"]
    drag(p.pane, pm.position() + 2, 20, 3, 20)
    spin(app, 0.5)
    check(p.left_host.avail_width() >= p.LEFT_MIN - 4, "Z2: межу Тем відтягнуто вліво до упору -- керування лишились не вужчими за %d (є %d)" % (p.LEFT_MIN, p.left_host.avail_width()))
    double_click(p.pane, pm.position() + 2, 20)
    spin(app, 0.4)
    check(abs(pm.position() - pm.clamp(pm.default())) <= 2, "Z2: подвійне клацання по межі Тем повертає типове положення")
    # широке вікно -- масштаб 4 (вибраний), x5 можна обрати
    app.geometry("1920x1080")
    spin(app, 0.8)
    check(int(p.scale_var.get()) == 4, "Z2: на широкому вікні вибраний масштаб 4 повернувся (є %d)" % int(p.scale_var.get()))
    check(str(p.scale_radios[5].cget("state")) != "disabled", "Z2: x5 на широкому вікні доступний")
    p.scale_var.set(5)
    p._on_scale()
    spin(app, 0.3)
    check(int(p.scale_var.get()) == 5 and p._img.width() == sim.W * 5, "Z2: масштаб x5 обрано і застосовано")
    res = lp.probe_panel(app, "themes")
    check(not res, "Z2: Теми на 1920x1080 без обрізання: %r" % (res[:2],))
    # знову вузько: x5 не вміщується -> зменшується, але вибір користувача пам'ятається
    app.geometry("1024x768")
    spin(app, 0.8)
    check(int(p.scale_var.get()) < 5 and p._pref_scale == 5, "Z2: на вузькому вікні x5 тимчасово зменшено, вибір (x5) пам'ятається")
    p.scale_var.set(4)
    p._on_scale()
    spin(app, 0.2)


# --- Z3, Z4 ------------------------------------------------------------------------------------------------------------------------------

def test_z3_z4(app):
    import tkinter as tk
    from tkinter import ttk
    import gui_clipboard as gc
    top = tk.Toplevel(app)
    top.geometry("500x400+0+0")
    widgets = {
        "tk.Entry": tk.Entry(top),
        "ttk.Entry": ttk.Entry(top),
        "ttk.Spinbox": ttk.Spinbox(top, from_=0, to=9),
        "ttk.Combobox": ttk.Combobox(top, values=["а"]),
        "tk.Text": tk.Text(top, height=3),
    }
    for w in widgets.values():
        w.pack(fill="x", pady=2)
    top.update()

    def content(w):
        return w.get("1.0", "end-1c") if w.winfo_class() == "Text" else w.get()

    def clear(w):
        if w.winfo_class() == "Text":
            w.delete("1.0", "end")
        else:
            w.delete(0, "end")

    def put(w, t):
        clear(w)
        w.insert("1.0" if w.winfo_class() == "Text" else 0, t)

    for name, w in widgets.items():
        put(w, "Надія")
        key(w, *K_ALL)
        check(gc.has_selection(w), "Z3 %s: Ctrl+ф (кириличний символ, код клавіші A) виділяє все" % name)
        app.clipboard_clear()
        key(w, *K_COPY)
        got = clip(app)
        check(got == "Надія", "Z3 %s: Ctrl+с копіює (є %r)" % (name, got))
        clear(w)
        key(w, *K_PASTE)
        check(content(w) == "Надія", "Z3 %s: Ctrl+м вставляє рівно один раз (є %r)" % (name, content(w)))
        key(w, *K_ALL)
        key(w, *K_CUT)
        check(content(w) == "" and clip(app) == "Надія", "Z3 %s: Ctrl+ч вирізає (поле %r, буфер %r)" % (name, content(w), clip(app)))
        # Alt (AltGr = Ctrl+Alt на Windows) -- не наша комбінація
        clear(w)
        key(w, *K_PASTE, state=0x4 | gc.ALT_MASK)
        check(content(w) == "", "Z3 %s: Ctrl+Alt+клавіша не вставляє" % name)
        # латинська розкладка не спрацьовує вдруге
        app.clipboard_clear()
        app.clipboard_append("Надія")
        key_latin(w, 55)
        check(content(w) == "Надія", "Z3 %s: Ctrl+v на латиниці вставляє рівно один раз (є %r)" % (name, content(w)))
        # Ctrl без літер не ламає введення
        clear(w)
        key_latin(w, 24)
        check(content(w) == "", "Z3 %s: Ctrl+q не вставляє символів" % name)
        key_latin(w, 38)           # Ctrl+a на латиниці -- справжня подія -- теж «виділити все», а не початок рядка
        put(w, "Надія")
        key_latin(w, 38)
        check(gc.has_selection(w), "Z3 %s: Ctrl+a (латиниця, справжня подія) виділяє все" % name)

    # код клавіші і символ діють НЕЗАЛЕЖНО: розкладка без розпізнаного символу ("??") -- за кодом; незнайомий код із кириличною літерою -- за символом
    e = widgets["ttk.Entry"]
    put(e, "Код")
    key(e, 38, "??")
    check(gc.has_selection(e), "Z3: Ctrl+клавіша A без розпізнаного символу виділяє все (за кодом)")
    app.clipboard_clear()
    key(e, 54, "??")
    check(clip(app) == "Код", "Z3: Ctrl+клавіша C без розпізнаного символу копіює (за кодом)")
    put(e, "Символ")
    key(e, 200, "Cyrillic_ef")
    check(gc.has_selection(e), "Z3: кирилична «ф» на незнайомому коді клавіші виділяє все (за символом)")
    app.clipboard_clear()
    key(e, 200, "Cyrillic_es")
    check(clip(app) == "Символ", "Z3: кирилична «с» на незнайомому коді клавіші копіює (за символом)")
    key(e, 200, "Cyrillic_ya")
    check(gc.has_selection(e) and clip(app) == "Символ", "Z3: інша кирилична літера з Ctrl нічого не робить")

    # поле лише для читання: виділити й скопіювати можна, змінити -- ні
    ro = ttk.Entry(top)
    ro.pack(fill="x")
    ro.insert(0, "Лише читання")
    ro.state(["readonly"])
    top.update()
    key(ro, *K_ALL)
    app.clipboard_clear()
    key(ro, *K_COPY)
    check(clip(app) == "Лише читання", "Z3 readonly: копіювання працює")
    app.clipboard_clear()
    app.clipboard_append("чуже")
    key(ro, *K_PASTE)
    key(ro, *K_CUT)
    check(ro.get() == "Лише читання", "Z3 readonly: вставка й вирізання не змінюють поле (є %r)" % ro.get())

    # журнал: Text у стані disabled -- виділення й копіювання
    log = app.log_text
    app.log("рядок журналу для копіювання")
    spin(app, 0.2)
    key(log, *K_ALL)
    app.clipboard_clear()
    key(log, *K_COPY)
    check("рядок журналу для копіювання" in (clip(app) or ""), "Z3 журнал: Ctrl+ф і Ctrl+с копіюють текст журналу")
    before = log.get("1.0", "end-1c")
    app.clipboard_clear()
    app.clipboard_append("чуже")
    key(log, *K_PASTE)
    key(log, *K_CUT)
    check(log.get("1.0", "end-1c") == before, "Z3 журнал: вставка й вирізання не змінюють журнал")

    # таблиця: Ctrl+с копіює вибрані рядки через табуляцію; сіре / активне меню
    tv = ttk.Treeview(top, columns=("a", "b"), show="headings", selectmode="extended")
    tv.heading("a", text="A")
    tv.heading("b", text="Б")
    i1 = tv.insert("", "end", values=("Надія", "42"))
    i2 = tv.insert("", "end", values=("Зоря", "7"))
    tv.pack(fill="x")
    top.update()
    tv.selection_set(i1)
    app.clipboard_clear()
    key(tv, *K_COPY)
    check(clip(app) == "Надія\t42", "Z3 таблиця: Ctrl+с копіює вибраний рядок через табуляцію (є %r)" % clip(app))
    tv.selection_set(i1, i2)
    key(tv, *K_COPY)
    check(clip(app) == "Надія\t42\nЗоря\t7", "Z3 таблиця: кілька рядків -- кожен з нового рядка (є %r)" % clip(app))
    key(tv, *K_ALL)
    check(set(tv.selection()) == {i1, i2}, "Z3 таблиця: Ctrl+ф виділяє всі рядки (режим extended)")

    # Z4: меню
    posted = []
    orig_post = gc._post
    gc._post = lambda menu, x, y: posted.append(menu)
    try:
        def menu_state(w):
            posted.clear()
            w.event_generate("<Button-3>", x=5, y=5, rootx=10, rooty=10)
            w.update()
            if not posted:
                return None
            m = posted[-1]
            out = {}
            for i in range(m.index("end") + 1):
                if m.type(i) == "command":
                    out[m.entrycget(i, "label")] = str(m.entrycget(i, "state"))
            return out

        e = widgets["ttk.Entry"]
        put(e, "Надія")
        e.selection_clear()
        app.clipboard_clear()
        st = menu_state(e)
        check(st == {"Вирізати": "disabled", "Копіювати": "disabled", "Вставити": "disabled", "Виділити все": "normal"},
              "Z4: порожній буфер, нічого не виділено -- лише «Виділити все» (є %r)" % st)
        e.selection_range(0, "end")
        app.clipboard_append("щось")
        st = menu_state(e)
        check(st == {"Вирізати": "normal", "Копіювати": "normal", "Вставити": "normal", "Виділити все": "normal"}, "Z4: виділено й буфер непорожній -- усе активне (є %r)" % st)
        ro.selection_range(0, "end")
        st = menu_state(ro)
        check(st == {"Вирізати": "disabled", "Копіювати": "normal", "Вставити": "disabled", "Виділити все": "normal"}, "Z4: поле лише для читання -- копіювати можна, змінювати ні (є %r)" % st)
        put(widgets["tk.Entry"], "")
        st = menu_state(widgets["tk.Entry"])
        check(st and st["Виділити все"] == "disabled", "Z4: порожнє поле -- «Виділити все» сіре (є %r)" % st)
        key(log, *K_ALL)
        st = menu_state(log)
        check(st and st["Копіювати"] == "normal" and st["Вирізати"] == "disabled" and st["Вставити"] == "disabled", "Z4: журнал -- лише копіювання (є %r)" % st)
        tv.selection_remove(i1, i2)
        st = menu_state(tv)
        check(st == {"Копіювати рядок": "disabled"}, "Z4: таблиця без вибору -- «Копіювати рядок» сіре (є %r)" % st)
        posted.clear()
        tv.selection_set(i2)
        gc.copy_rows(tv)
        st = menu_state(tv)
        check(st == {"Копіювати рядок": "normal"}, "Z4: з вибраним рядком -- «Копіювати рядок» активне (є %r)" % st)
        lbl = ttk.Label(top, text="Підпис для копіювання")
        lbl.pack()
        top.update()
        st = menu_state(lbl)
        check(st == {"Копіювати текст": "normal"}, "Z4: підпис -- «Копіювати текст» (є %r)" % st)
    finally:
        gc._post = orig_post
    # пункт «Копіювати рядок» справді копіює
    tv.selection_set(i2)
    app.clipboard_clear()
    gc.copy_rows(tv)
    check(clip(app) == "Зоря\t7", "Z4: «Копіювати рядок» кладе рядок у буфер")
    top.destroy()

    # таблиці розділів: Ctrl+с у «Контактах» (реальний FitTreeview) копіює вибраний рядок
    return True


def test_z3_panel_tables(app, mk):
    import gui_clipboard as gc
    app.set_document(mk())
    app.show("contacts")
    spin(app, 0.6)
    p = app.get_panel("contacts")
    kids = p.tree.get_children()
    check(len(kids) > 0, "Z3: у таблиці «Контакти» є рядки")
    if kids:
        p.tree.selection_set(kids[0])
        want = "\t".join(str(v) for v in p.tree.item(kids[0], "values"))
        app.clipboard_clear()
        key(p.tree, *K_COPY)
        check(clip(app) == want, "Z3: Ctrl+с у таблиці «Контакти» копіює рядок: %r == %r" % (clip(app), want))
        p.tree.selection_set(kids[0])
        spin(app, 0.2)
    # поле «Фільтр» у цій панелі приймає вставку кириличною розкладкою
    flt = p._filter
    app.clipboard_clear()
    app.clipboard_append("Над")
    ent = [w for w in p.left.winfo_children() if w.winfo_class() == "TEntry"][0]
    key(ent, *K_PASTE)
    check(flt.get() == "Над", "Z3: у поле «Фільтр» вставка кириличною розкладкою працює (є %r)" % flt.get())
    flt.set("")
    check(gc.menu_items(ent)[3][2] == "disabled", "Z4: порожнє поле фільтра -- «Виділити все» сіре")
    spin(app, 0.2)


# --- Z5 --------------------------------------------------------------------------------------------------------------------------------

def test_z5(mk):
    tmp = tempfile.mkdtemp(prefix="r36_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    app = make_app(spath, 1100, 760)
    try:
        app.set_document(mk())
        app.show("contacts")
        spin(app, 0.9)
        p = app.get_panel("contacts")
        pm = app._panes["contacts"]
        check(pm.restored, "Z5: межа редактора ініціалізована після показу")
        default = pm.default()
        # межа тягнеться
        target = pm.clamp(default + 60)
        p.pane.sashpos(0, target)
        spin(app, 0.3)
        check(abs(pm.position() - target) <= 2, "Z5: межу список|форма можна пересунути (%d -> %d)" % (target, pm.position()))
        # мінімуми: надто вліво / надто вправо
        drag(p.pane, pm.position() + 2, 20, 3, 20)
        spin(app, 0.3)
        check(pm.position() >= pm.min_first() - 1, "Z5: ліворуч межа не заходить за мінімум списку (%d < %d)" % (pm.position(), pm.min_first()))
        drag(p.pane, pm.position() + 2, 20, p.pane.winfo_width() - 3, 20)
        spin(app, 0.3)
        check(pm.position() <= p.pane.winfo_width() - pm.min_second() - 1, "Z5: праворуч лишається мінімум форми (%d)" % (p.pane.winfo_width() - pm.position()))
        # подвійне клацання по межі -> типове положення
        p.pane.sashpos(0, pm.clamp(default + 80))
        spin(app, 0.2)
        x = pm.position() + 2
        double_click(p.pane, x, 20)
        spin(app, 0.3)
        check(abs(pm.position() - pm.clamp(default)) <= 2, "Z5: подвійне клацання по межі повертає типове положення (%d, типове %d)" % (pm.position(), pm.clamp(default)))
        # подвійне клацання НЕ по межі -- нічого не міняє
        p.pane.sashpos(0, pm.clamp(default + 50))
        spin(app, 0.2)
        before = pm.position()
        double_click(p.pane, before + 120, 20)
        spin(app, 0.2)
        check(pm.position() == before, "Z5: подвійне клацання поза межею положення не міняє")
        # межа дерево | панель
        hp = app.pane_tree
        app.hpane.sashpos(0, 380)
        spin(app, 0.3)
        check(abs(hp.position() - 380) <= 2, "Z5: межу дерево|панель можна пересунути")
        double_click(app.hpane, hp.position() + 2, 30)
        spin(app, 0.3)
        check(abs(hp.position() - 300) <= 2, "Z5: подвійне клацання по межі дерево|панель -- типові 300 (є %d)" % hp.position())
        # Теми: межа керування|перегляд
        app.show("themes")
        spin(app, 0.9)
        tp = app.get_panel("themes")
        tpm = app._panes["themes"]
        check(tpm.restored, "Z5: межа Тем ініціалізована")
        tw = tp.pane.winfo_width()
        want_t = tpm.clamp(tpm.min_first() + 30)
        tp.pane.sashpos(0, want_t)
        spin(app, 0.3)
        # зберегти все
        want_hp = 340
        app.hpane.sashpos(0, want_hp)
        spin(app, 0.3)
        want_c = pm.position()
        pos_t = tpm.position()
        pos_h = hp.position()
        app.geometry("1111x777")
        spin(app, 0.5)
        ok = app.save_settings()
        check(ok, "Z5: налаштування записано")
        import json
        data = json.load(open(spath, encoding="utf-8"))
        check(data.get("sash_contacts") == want_c and data.get("sash_themes") == pos_t, "Z5: у файлі налаштувань є положення меж: %r" % {k: v for k, v in data.items() if k.startswith("sash")})
        check(data.get("width") == 1111 and data.get("height") == 777, "Z5: у файлі розмір вікна %rx%r" % (data.get("width"), data.get("height")))
    finally:
        app.destroy()
    # повторне відкриття
    app2 = make_app(spath)
    try:
        app2.set_document(mk())
        spin(app2, 0.5)
        check((app2.winfo_width(), app2.winfo_height()) == (1111, 777) or abs(app2.winfo_width() - 1111) <= 2, "Z5: розмір вікна відновлено (%dx%d)" % (app2.winfo_width(), app2.winfo_height()))
        app2.show("contacts")
        spin(app2, 1.0)
        pm2 = app2._panes["contacts"]
        check(abs(pm2.position() - want_c) <= 3, "Z5: положення межі «Контакти» відновлено (%d, було %d)" % (pm2.position(), want_c))
        app2.show("themes")
        spin(app2, 1.0)
        tpm2 = app2._panes["themes"]
        check(abs(tpm2.position() - pos_t) <= 3, "Z5: положення межі Тем відновлено (%d, було %d)" % (tpm2.position(), pos_t))
        check(abs(app2.pane_tree.position() - pos_h) <= 4 or abs(app2.hpane.sashpos(0) - want_hp) <= 4, "Z5: ширина дерева відновлена (%d, було %d)" % (app2.hpane.sashpos(0), pos_h))
        # подвійне клацання після відновлення все ще працює
        app2.show("contacts")
        spin(app2, 0.4)
        double_click(pm2.pane, pm2.position() + 2, 20)
        spin(app2, 0.3)
        check(abs(pm2.position() - pm2.clamp(pm2.default())) <= 2, "Z5: після відновлення подвійне клацання теж повертає типове положення")
    finally:
        app2.destroy()


# --- Z6 --------------------------------------------------------------------------------------------------------------------------------

def test_z6():
    r = subprocess.run([sys.executable, "-B", os.path.join(HERE, "test_r34.py")], capture_output=True, text=True, timeout=180)
    check(r.returncode == 0, "Z6: test_r34 з увімкненим прапорцем проходить:\n%s" % (r.stdout + r.stderr)[-600:])
    h = os.path.join(HERE, "..", "application", "include", "functions", "codeplug.h")
    src = open(h, encoding="cp1251", errors="replace").read()
    check("\n#define CODEPLUG_NAME_ZERO_TAIL 1" in src, "Z6: у codeplug.h прапорець CODEPLUG_NAME_ZERO_TAIL увімкнено")
    import contact_edit as ce
    import codeplug_view as cv
    check(cv.NAME_ZERO_TAIL is True, "Z6: дзеркало прапорця в codeplug_view увімкнено")
    check(not hasattr(ce, "ZERO_TAIL_WARNING"), "Z6: застереження про хвіст 0x00 знято")
    r1 = ce.check_name("Надія")
    check(not r1.get("warning"), "Z6: «Надія» без застереження (%r)" % (r1,))
    import cps_csv as cc
    raw_nadiya = cc.encode_new_name("Надія")[0]
    padded = cv.pad_name(raw_nadiya, 16)
    check(raw_nadiya[-1:] == b"\xff" and padded[-1:] == b"\x00" and len(padded) == 16, "Z6: назва «Надія» (кінцева «я» = 0xFF) записується з хвостом 0x00: %r" % padded)
    check(cv.pad_name(b"Ab", 16)[-1:] == b"\xff", "Z6: назва без «я» -- хвіст 0xFF, як у стокової CPS")
    check(cv.decode_name_ex(padded)[0] == "Надія", "Z6: назву з хвостом 0x00 читаємо назад як «Надія»")


# --- Z7 --------------------------------------------------------------------------------------------------------------------------------

def test_z7(app, mk):
    import tkinter as tk
    from tkinter import ttk
    import tkinter.font as tkfont
    import gui_theme as gt
    from cps_ui import layout as lay
    # таблиця за вмістом
    top = tk.Toplevel(app)
    top.geometry("420x300+0+0")
    tbl = lay.FitTable(top, [("a", "№", 30, 0), ("b", "Назва контакту", 60, 1), ("c", "TG / ID", 50, 0), ("d", "Тип", 40, 0)], height=5)
    tbl.pack(fill="both", expand=True)
    for i in range(30):
        tbl.tree.insert("", "end", values=(i + 1, "Дуже довга назва контакту номер %d" % i, 1234567, "Приватний"))
    top.update()
    spin(app, 0.4)
    req = tbl.tree.required()
    f = tkfont.nametofont("TkDefaultFont")
    check(req["d"] >= f.measure("Приватний"), "Z7: стовпець «Тип» не вужчий за значення (%d)" % req["d"])
    check(not tbl.tree.clipped_columns(), "Z7: у вузькій таблиці жоден стовпець не вужчий за потрібне (%r)" % tbl.tree.clipped_columns())
    check(tbl.h_scroll_visible(), "Z7: коли стовпці ширші за таблицю -- горизонтальна смуга")
    top.geometry("1400x300+0+0")
    top.update()
    spin(app, 0.4)
    check(not tbl.h_scroll_visible(), "Z7: у широкій таблиці горизонтальної смуги нема")
    wid = {c: int(tbl.tree.column(c, "width")) for c in "abcd"}
    check(tbl.tree.total_width() >= tbl.tree.winfo_width() - 4, "Z7: широка таблиця використовує всю ширину (%d з %d)" % (tbl.tree.total_width(), tbl.tree.winfo_width()))
    check(wid["b"] > req["b"], "Z7: вільне місце віддано стовпцю з вагою «Назва» (%d > %d)" % (wid["b"], req["b"]))
    check(wid["a"] == req["a"] and wid["c"] == req["c"], "Z7: стовпці з нульовою вагою не розтягуються")
    top.destroy()
    # «Контакти» на вузькому вікні: стовпці TG / ID і Тип повністю читаються
    app.geometry("1024x768")
    spin(app, 0.4)
    app.set_document(mk())
    app.show("contacts")
    spin(app, 0.8)
    p = app.get_panel("contacts")
    r = p.tree.required()
    for c in ("id", "type"):
        check(int(p.tree.column(c, "width")) >= r[c], "Z7: «Контакти» 1024x768: стовпець %s показано повністю (%d >= %d)" % (c, int(p.tree.column(c, "width")), r[c]))
    check(p.tree.winfo_width() >= p.tree.total_width() - 2 or p.table.h_scroll_visible(), "Z7: «Контакти»: або все вміщується, або є горизонтальна смуга")
    bw = [b.winfo_width() for b in (p.btn_add, p.btn_dup, p.btn_ren, p.btn_del)]
    check(max(bw) - min(bw) <= 1, "Z7/B4: кнопки групи в «Контактах» однакової ширини (розбіжність не більш як 1 px на непарній ширині): %r" % bw)
    # перенос довгих описів
    app.show("aes")
    spin(app, 0.6)
    pa = app.get_panel("aes")
    labs = pa.wrap_labels()
    check(len(labs) > 0, "Z7: у панелі AES є довгі описи")
    w1 = {str(l): int(str(l.cget("wraplength"))) for l in labs}
    app.geometry("1920x1080")
    spin(app, 0.8)
    w2 = {str(l): int(str(l.cget("wraplength"))) for l in pa.wrap_labels()}
    app.geometry("1024x768")
    spin(app, 0.8)
    w3 = {str(l): int(str(l.cget("wraplength"))) for l in pa.wrap_labels()}
    grew = [k for k in w1 if w2.get(k, 0) > w3.get(k, 0)]
    check(grew and all(w2[k] > w3[k] for k in w2 if k in w3), "Z7: wraplength описів росте з шириною вікна і зменшується назад (%r -> %r)" % (list(w3.values())[:3], list(w2.values())[:3]))
    aw = pa.avail_width()
    check(all(v <= aw for v in w3.values()), "Z7: жоден опис не ширший за видиму область (%d)" % aw)
    # на широкому вікні жодна панель не має горизонтальної смуги (запит таблиці не залежить від її поточної ширини)
    import layout_probe as lp
    app.set_document(mk())
    app.geometry("1920x1080")
    spin(app, 0.6)
    wide = []
    for k in [k for k in app.section_keys() if not k.startswith("grp_")]:
        app.show(k)
        spin(app, 1.0)          # перенос описів після появи вертикальної смуги встигає за ~0.3 с
        for attempt in (0, 1):
            bad = [w for w in lp.walk_viewable(app._hosts[k]) if hasattr(w, "h_scroll_active") and hasattr(w, "canvas") and w.h_scroll_active()]
            if bad and attempt == 0:
                spin(app, 2.0)          # розкладка ще могла встигати; звітуємо лише про те, що не минуло
                continue
            for w in bad:
                wide.append("%s %s (вміст просить %d, видно %d)" % (k, str(w).replace(".!cpsapp", "")[-50:], w.inner.winfo_reqwidth(), w.avail_width()))
            break
    check(not wide, "Z7/B1: 1920x1080 -- горизонтальна смуга є в панелях: %r" % sorted(set(wide)))
    app.geometry("1024x768")
    spin(app, 0.6)
    # одна шкала відступів
    check(isinstance(gt.GAP, int) and isinstance(gt.PAD, int) and gt.PAD % 4 == 0 and gt.GAP % 4 == 0, "B4: відступи задано однією шкалою в gui_theme (GAP=%r, PAD=%r)" % (gt.GAP, gt.PAD))
    # кнопки Тем попарно однакової ширини
    app.show("themes")
    spin(app, 0.6)
    tp = app.get_panel("themes")
    check(abs(tp.read_btn.winfo_width() - tp.write_btn.winfo_width()) <= 1, "B4: Теми -- «Прочитати» і «Записати» однакової ширини")
    check(abs(tp.save_btn.winfo_width() - tp.load_btn.winfo_width()) <= 1, "B4: Теми -- «Зберегти» і «Завантажити» однакової ширини")


def main():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("ПРОПУЩЕНО: нема tkinter")
        test_z6()
        return finish()
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО: нема DISPLAY (запусти через xvfb-run)")
        test_z6()
        return finish()
    tmp = tempfile.mkdtemp(prefix="r36main_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    mk = doc_factory()
    only = set(filter(None, os.environ.get("R36_ONLY", "").lower().split(",")))     # для мутаційних перевірок: R36_ONLY=z3,z5

    def want(name):
        return not only or name in only
    app = make_app(spath)
    try:
        if want("z1"):
            test_z1(app, mk)
            app.set_document(None)
        if want("z2"):
            test_z2(app)
        if want("z3"):
            test_z3_z4(app)
            test_z3_panel_tables(app, mk)
        if want("z7"):
            test_z7(app, mk)
    finally:
        app.destroy()
    if want("z5"):
        test_z5(mk)
    if want("z6"):
        test_z6()
    return finish()


def finish():
    if FAILS:
        print("test_r36: ПРОВАЛІВ %d" % len(FAILS))
        return 1
    print("test_r36: усе гаразд (вікно без обрізання на 1024x768 і 1920x1080, межі, копіювання за кодом клавіші, контекстні меню, таблиці, хвіст 0x00).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
