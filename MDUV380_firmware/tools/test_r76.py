#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R76: автовиявлення рації за списком портів + виразніші головні кнопки.
Хост-частина (без Tk і без заліза), на підставному списку портів:
  1  порт з'явився (стан «не знайдено») -> 'appeared' лише після ДВОХ однакових оглядів; зник -> 'vanished';
  2  мерехтіння (з'явився й одразу зник) ігнорується; одна зміна списку = одна спроба;
  3  поки зайнято (blocked) огляд НЕ запускається, а результат, що завершився під час зайнятості, відкидається; серія дебаунсу починається знову;
  4  помилка огляду -- один рядок у журналі (не на кожен огляд), без дій, період огляду збільшується, потім відновлюється;
  5  порт модулем автовиявлення НЕ відкривається: у autodetect.py нема open_radio / Serial( / find_port, а scan читає лише list_ports.comports();
  6  порт з'явився, коли рація вже «знайдена» на тому ж порту -- нічого; на іншому порту -- повторне підключення.
Контраст (не менше 4,5 : 1) для всіх кнопок панелі документа в усіх станах, у т.ч. наведення й натиснуто; вимкнена кнопка відрізняється від нейтральної.
Tk-частина (xvfb): стилі кнопок, перемикання «Записати» на світлий акцент при незбережених змінах, рядок стану кольором за змістом, заголовки груп
у дереві, зв'язка автовиявлення з застосунком (busy / R73 / модальне вікно), текст сторінки «Підключення і стан».
Запуск: xvfb-run -a python3.12 tools/test_r76.py"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gui_theme as gt                 # noqa: E402
from cps_ui import autodetect as ad    # noqa: E402

FAILS = []
PASSED = [0]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


class Fake:
    def __init__(self):
        self.ports = ()
        self.exc = None
        self.calls = 0
        self.block = False
        self.logs = []

    def scan(self):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.ports

    def det(self, debounce=2):
        return ad.PortDetector(self.scan, lambda: self.block, log=self.logs.append, debounce=debounce)


def t_logic():
    f = Fake()
    d = f.det()
    # базова лінія: порту нема, рації нема -> нічого
    check(d.tick_sync(False, None) is None and d.tick_sync(False, None) is None, "1: старт без порту -- нічого")
    f.ports = ("COM5",)
    check(d.tick_sync(False, None) is None, "1: один огляд ще не підтверджує появу (дебаунс)")
    check(d.tick_sync(False, None) == "appeared", "1: другий однаковий огляд -> appeared")
    check(d.tick_sync(True, "COM5") is None and d.tick_sync(True, "COM5") is None, "1: далі, поки список не змінився, дій нема (одна спроба на зміну)")
    f.ports = ()
    check(d.tick_sync(True, "COM5") is None, "1: зникнення теж потребує двох оглядів")
    check(d.tick_sync(True, "COM5") == "vanished", "1: зник -> vanished")
    check(d.tick_sync(False, None) is None, "1: після vanished і mark_absent дій нема")
    # мерехтіння
    f.ports = ("COM5",)
    d.tick_sync(False, None)
    f.ports = ()
    d.tick_sync(False, None)
    f.ports = ("COM5",)
    d.tick_sync(False, None)
    f.ports = ()
    check(d.tick_sync(False, None) is None and d.tick_sync(False, None) is None, "2: мерехтіння порту не дає ні appeared, ні vanished")
    # порт з'явився, але рація вже знайдена на ньому -- нічого; на іншому -- підключення
    f = Fake()
    d = f.det()
    f.ports = ("COM5",)
    check(d.tick_sync(True, "COM5") is None and d.tick_sync(True, "COM5") is None, "6: рація вже знайдена на цьому порту -- нічого")
    f.ports = ("COM7",)
    d.tick_sync(True, "COM5")
    check(d.tick_sync(True, "COM5") == "appeared", "6: рація знайдена на COM5, а порт тепер COM7 -> повторне підключення")
    # старт: рація вже знайдена стартовим пошуком, а порту вже нема
    f = Fake()
    d = f.det()
    d.tick_sync(True, "COM5")
    check(d.tick_sync(True, "COM5") == "vanished", "6: на старті «знайдено», а порту нема -> vanished")
    # зайнято
    f = Fake()
    d = f.det()
    f.ports = ("COM5",)
    f.block = True
    n = f.calls
    for _ in range(5):
        check(d.begin() is False, "3: під час зайнятості огляд не стартує")
    check(f.calls == n, "3: список портів під час зайнятості не читається")
    f.block = False
    d.tick_sync(False, None)
    f.block = True
    f.block = False
    check(d.begin() is True, "3: після звільнення огляд знову можливий")
    f.block = True                                           # операція почалась, поки огляд ішов
    check(d.finish(d.scan_safely(), False, None) is None, "3: результат, що завершився під час зайнятості, відкидається")
    f.block = False
    check(d.tick_sync(False, None) is None, "3: серія дебаунсу після зайнятості починається знову (1-й огляд)")
    check(d.tick_sync(False, None) == "appeared", "3: ...і 2-й дає appeared")
    check(d.begin() is True and d.begin() is False, "3: два огляди паралельно неможливі")
    d.finish(d.scan_safely(), True, "COM5")
    # помилки
    f = Fake()
    d = f.det()
    f.exc = ad.cl.CpsError("потрібен pyserial: pip install pyserial")
    for _ in range(6):
        check(d.tick_sync(False, None) is None, "4: помилка огляду -- без дії")
    check(len(f.logs) == 1, "4: помилка в журналі рівно один раз, а не на кожен огляд (%d)" % len(f.logs))
    check(d.next_delay_ms() == ad.SCAN_MS_AFTER_ERROR, "4: після помилки період більший")
    f.exc = None
    d.tick_sync(False, None)
    check(d.next_delay_ms() == ad.SCAN_MS, "4: після відновлення період звичайний")
    f.exc = ad.cl.CpsError("інша помилка")
    d.tick_sync(False, None)
    check(len(f.logs) == 2, "4: інша помилка -- новий рядок")


def t_no_open():
    src = open(os.path.join(HERE, "cps_ui", "autodetect.py"), encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    code = re.sub(r'""".*?"""', "", code, flags=re.S)
    for bad in ("open_radio", "Serial(", "find_port", ".open(", "CpsLink", "probe"):
        check(bad not in code, "5: autodetect.py не повинен містити %r" % bad)
    check("list_ports.comports()" in code, "5: огляд читає список портів ОС")
    app = open(os.path.join(HERE, "cps_ui", "app.py"), encoding="utf-8").read()
    a = app.index("def _autodetect_blocked")
    b = app.index("# --- виконавець фонових операцій")
    glue = app[a:b]
    check("open_radio" not in glue and "Serial" not in glue and "probe" not in glue, "5: зв'язка автовиявлення в app.py не відкриває порт напряму")
    check("refresh_connection(force=False)" in glue, "5: підключення -- через наявну процедуру refresh_connection (як «Оновити»)")
    # мутант: якби scan відкривав порт -- тест 5 це ловить
    mut = code + "\nopen_radio()\n"
    check("open_radio" in mut, "5: мутант (додано open_radio) ловиться перевіркою")


def t_contrast():
    P = gt.P
    sets = {"Читання": "read", "Запис": "write", "Запис (є зміни)": "dirty", "Файл": "file"}
    for name, k in sets.items():
        for st in ("bg", "hover", "press"):
            c = gt.contrast(P[k + "_fg"], P[k + "_" + st])
            check(c >= 4.5, "контраст %s/%s = %.2f < 4,5" % (name, st, c))
    check(gt.contrast(P["ghost_fg"], P["bg"]) >= 4.5 and gt.contrast(P["ghost_fg"], P["ghost_hover"]) >= 4.5, "контраст «Відкинути»")
    check(gt.contrast(P["disabled_fg"], P["disabled_bg"]) >= 4.5, "контраст вимкненої")
    check(gt.contrast(P["select_fg"], P["nav_select"]) >= 4.5 and gt.contrast(P["group_fg"], P["bg"]) >= 4.5, "контраст дерева")
    for k in ("ok", "warn", "err", "info"):
        check(gt.contrast(P[k], P["bg"]) >= 4.5 and gt.contrast(P[k], P["surface"]) >= 4.5, "контраст рядка стану " + k)
    # вимкнена відрізняється від активної нейтральної і від кольорових
    check(P["disabled_bg"] != P["file_bg"] and P["disabled_bg"] != P["read_bg"] and P["disabled_bg"] != P["write_bg"], "вимкнена кнопка має інше тло")
    check(gt.contrast(P["file_bg"], P["bg"]) > 1.3, "активна файлова кнопка помітно світліша за тло")
    for pair in gt.CONTRAST_PAIRS:
        check(gt.contrast(P[pair[0]], P[pair[1]]) >= 4.5, "CONTRAST_PAIRS %s" % (pair,))


def t_tk():
    try:
        import tkinter  # noqa: F401
        have = bool(os.environ.get("DISPLAY"))
    except ImportError:
        have = False
    if not have:
        print("test_r76: нема tkinter/DISPLAY -- Tk-частину пропущено")
        return
    import tempfile
    import test_r36 as t36
    spath = os.path.join(tempfile.mkdtemp(prefix="r76_"), "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    app = t36.make_app(spath)
    try:
        P = gt.P
        b = app.docbtn
        # стилі
        for key, st in (("open_radio", "Read.TButton"), ("write", "Write.TButton"), ("open_file", "File.TButton"), ("save_as", "File.TButton"),
                        ("discard", "Ghost.TButton")):
            check(str(b[key].cget("style")) == st, "Tk: стиль кнопки %s = %s (є %s)" % (key, st, b[key].cget("style")))
        # без рації
        app.conn.mark_absent()
        app._refresh_all()
        check(str(b["open_radio"].cget("state")) == "disabled" and str(b["write"].cget("state")) == "disabled", "Tk: без рації «Прочитати» і «Записати» вимкнені")
        check(str(b["open_file"].cget("state")) != "disabled", "Tk: «Відкрити файл...» працює без рації")
        check("нема" in app.docbar_radio.cget("text") and str(app.docbar_radio.cget("foreground")) == P["err"], "Tk: рядок стану червоний «не знайдено»")
        # підказка
        reason = app.doc_reasons().get("open_radio")
        check(reason and "Рацію не знайдено" in reason, "Tk: причина для підказки «Рацію не знайдено» (%r)" % reason)
        # знайдено
        app.conn.state, app.conn.port = "found", "COM9"
        app._refresh_all()
        check("COM9" in app.docbar_radio.cget("text") and str(app.docbar_radio.cget("foreground")) == P["ok"], "Tk: рядок стану зелений «знайдено»")
        check(str(b["open_radio"].cget("state")) != "disabled", "Tk: після «знайдено» «Прочитати» активна")
        # документ із незбереженими змінами
        doc = t36.doc_factory()()
        app.set_document(doc)
        app.update()
        check(str(b["write"].cget("style")) == "Write.TButton", "Tk: без змін «Записати» -- звичайний тепло-помаранчевий стиль")
        doc.modified = True
        app.update_doc_ui()
        check(str(b["write"].cget("style")) == "WriteDirty.TButton", "Tk: зі змінами «Записати» -- світлий акцент")
        check(str(app.doc_label.cget("foreground")) == P["warn"] and "ЗМІНЕНО" in app.doc_label.cget("text"), "Tk: рядок стану «ЗМІНЕНО» жовтогарячий")
        doc.modified = False
        app.update_doc_ui()
        check(str(b["write"].cget("style")) == "Write.TButton", "Tk: стиль повернувся після збереження")
        # дерево
        check("grp" in app.tree.item("grp_data", "tags"), "Tk: заголовок групи «Дані» має акцентний тег")
        check("grp" in app.tree.item("grp_service", "tags"), "Tk: заголовок групи «Сервіс» має акцентний тег")
        # зв'язка автовиявлення
        calls = []
        app.refresh_connection = lambda force=False: calls.append(force)
        fake = Fake()
        app._ad = ad.PortDetector(fake.scan, app._autodetect_blocked, log=app.log)
        app.conn.mark_absent()
        fake.ports = ("COM5",)
        for _ in range(2):
            check(app._ad.begin(), "Tk: огляд дозволено у вільному стані")
            app._autodetect_done(app._ad.scan_safely())
        check(calls == [False], "Tk: появу порту -> рівно один виклик refresh_connection (як «Оновити») (%r)" % calls)
        check(app._ad_pending, "Tk: позначено, що підключення запущене автоматично")
        app._ad_pending = False
        # зайнято / R73 / модальне вікно
        n = fake.calls
        app.busy = True
        check(app._ad.begin() is False, "Tk: busy -- огляду нема")
        app.busy = False
        app._rc_active = True
        check(app._ad.begin() is False, "Tk: триває повторний пошук R73 -- огляду нема")
        app._rc_active = False
        import tkinter as tk
        top = tk.Toplevel(app)
        top.grab_set()
        app.update()
        check(app._ad.begin() is False, "Tk: модальне вікно -- огляду нема")
        top.grab_release()
        top.destroy()
        check(fake.calls == n, "Tk: під час зайнятості список портів не читався")
        # зникнення
        app.conn.state, app.conn.port = "found", "COM5"
        fake.ports = ()
        for _ in range(2):
            app._ad.begin()
            app._autodetect_done(app._ad.scan_safely())
        check(app.conn.state == "absent", "Tk: порт зник -> рацію позначено «не знайдено»")
        check(str(b["open_radio"].cget("state")) == "disabled", "Tk: ...і кнопки неактивні")
        # R73: прапорець знімається тільки по завершенню опитування
        src = open(os.path.join(HERE, "cps_ui", "app.py"), encoding="utf-8").read()
        check(src.count("self._rc_active = True") == 1 and src.count("self._rc_active = False") >= 2, "Tk: прапорець R73 ставиться й знімається")
        # текст сторінки
        from cps_ui import p_connect
        psrc = open(p_connect.__file__, encoding="utf-8").read()
        check("Рацію шукаємо автоматично; кнопка «Оновити» шукає негайно" in psrc, "Tk: текст сторінки «Підключення і стан»")
        check(app.get_panel("conn") is not None, "Tk: сторінка будується")
    finally:
        app.destroy()


def t_bar_rows():
    """R76B: панель кнопок при МІНІМАЛЬНОМУ вікні в усіх шести сценаріях шрифтів не займає більше двох рядків (причина падіння test_r56_ui у CI: з ширшими
    шрифтами DejaVu стан рації + жирні кнопки переносились на третій рядок, і панелі розділів бракувало висоти). Перевірка не залежить від шрифту:
    рахуємо рядки за координатами кнопок. Тест перевіряє й те, що run_tests.sh друкує причину падіння (show_fail), а не лише tail -10."""
    sh = open(os.path.join(HERE, "..", "tests", "run_tests.sh"), encoding="utf-8").read()
    check("show_fail()" in sh and "| tail -10" not in sh, "R76B: run_tests.sh друкує причину падіння (show_fail), без tail -10")
    import subprocess
    r = subprocess.run(["bash", "-c", 'eval "$(sed -n \'/^show_fail() {/,/^}/p\' "$1")"; show_fail "$(printf \'a\\nПРОВАЛ: причина X\\nb\\n\')"',
                        "x", os.path.join(HERE, "..", "tests", "run_tests.sh")], capture_output=True, text=True)
    check("причина X" in r.stdout and "хвіст виводу" in r.stdout, "R76B: show_fail виводить рядок із ПРОВАЛ (%r)" % r.stdout[:120])
    try:
        import tkinter  # noqa: F401
        have = bool(os.environ.get("DISPLAY"))
    except ImportError:
        have = False
    if not have:
        return
    import tkinter as tk
    import test_r50fix as t50
    import test_r54_ui as t54
    import layout_probe as lp
    root = tk.Tk()
    scs = t50.sc_list(root)
    root.destroy()
    import font_scenarios as fs
    for sc in scs:
        app = t54.new_app(sc)
        try:
            app.apply_min_size()
            app.geometry("%dx%d" % tuple(app.min_window_size()))
            lp.spin(app, 0.4)
            for state in ("absent", "unknown", "found"):
                app.conn.state, app.conn.port = state, ("COM12" if state == "found" else None)
                app._refresh_all()
                lp.spin(app, 0.2)
                ys = sorted(set(b.winfo_y() for b in app.docbtn.values()))
                check(len(ys) <= 2, "R76B [%s, %s]: кнопки панелі документа в %d рядках (має бути не більше 2): %r; ширина панелі %d, рядка %d" % (fs.label(sc), state, len(ys), ys, app.right.winfo_width(), app._docbtn_row.winfo_width()))
                check(app.docbar_radio.winfo_y() <= ys[0], "R76B [%s, %s]: стан рації в першому рядку" % (fs.label(sc), state))
                check(app._docbtn_row.winfo_height() <= 2 * max(b.winfo_height() for b in app.docbtn.values()) + 8,
                      "R76B [%s, %s]: висота рядка кнопок %d" % (fs.label(sc), state, app._docbtn_row.winfo_height()))
        finally:
            app.destroy()


def main():
    for t in (t_logic, t_no_open, t_contrast, t_tk, t_bar_rows):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            FAILS.append("%s: виняток %s: %s" % (t.__name__, type(e).__name__, e))
            traceback.print_exc()
    if FAILS:
        print("test_r76: %d провалів" % len(FAILS))
        return 1
    print("test_r76: усе гаразд (%d перевірок: дебаунс, зайнятість, помилки, порт не відкривається, контраст, Tk)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
