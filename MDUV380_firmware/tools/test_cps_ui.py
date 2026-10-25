#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тест CPS-shell (етап 1): оболонка tools/cps_ui під віртуальним дисплеєм (`xvfb-run -a python3 tools/test_cps_ui.py`).

Перевіряє: вікно створюється; дерево має всі очікувані пункти; вибір КОЖНОГО пункту відкриває його панель без винятку (і в стані «рації
нема», і в стані «рацію знайдено», і під час операції); недоступні дії вимкнені З ПОЯСНЕННЯМ, а не зникають; налаштування (розмір вікна,
останній розділ, журнал) переживають перезапуск; підключення кешується (повторного пошуку без «Оновити» нема); фонове завдання
пише в спільний журнал і знімає блокування; gui_flasher.py лишився тонким запуском.

Без tkinter або без DISPLAY тест друкує «ПРОПУЩЕНО» й повертає 0 (щоб не валити хости без Tk).
"""
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FAILS = []

# Очікуване дерево: (ключ, видимий текст, батько)
EXPECTED = [
    ("grp_radio", "Рація", ""),
    ("conn", "Підключення і стан", "grp_radio"),
    ("flash", "Прошивка", "grp_radio"),
    ("shot", "Знімок екрана", "grp_radio"),
    ("grp_codeplug", "Кодплаг", ""),
    ("backup", "Бекап і відновлення", "grp_codeplug"),
    ("basic", "Основна інформація", "grp_codeplug"),
    ("general", "Загальні налаштування", "grp_codeplug"),
    ("channels", "Канали", "grp_codeplug"),
    ("vfo", "VFO A / VFO B", "grp_codeplug"),
    ("zones", "Зони", "grp_codeplug"),
    ("contacts", "Контакти", "grp_codeplug"),
    ("tglists", "Списки прийому", "grp_codeplug"),
    ("dtmf", "DTMF-контакти", "grp_codeplug"),
    ("aprs", "APRS", "grp_codeplug"),
    ("csv", "CSV", "grp_codeplug"),
    ("grp_settings", "Налаштування рації", ""),
    ("aes", "AES-ключі", "grp_settings"),
    ("rctl", "Віддалене керування (RCTL)", "grp_settings"),
    ("themes", "Теми", "grp_settings"),
    ("allsettings", "Усі налаштування", "grp_settings"),
    ("dmrdb", "База позивних", "grp_settings"),
]


FIRST_OF = {"grp_radio": "conn", "grp_codeplug": "backup", "grp_settings": "aes"}


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def test_launcher_is_thin():
    src = open(os.path.join(HERE, "gui_flasher.py"), encoding="utf-8").read()
    code = [l for l in src.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    check(len(src.splitlines()) < 80, "gui_flasher.py -- тонкий запуск (<80 рядків), зараз %d" % len(src.splitlines()))
    check("from cps_ui.app import" in src and "main()" in src, "gui_flasher.py імпортує cps_ui.app і викликає main()")
    check(not any(re.match(r"\s*class\s", l) for l in code), "у gui_flasher.py нема класів")


def _spin(app, seconds=0.5):
    """Прокрутити цикл подій (з паузами), щоб відпрацювали after()/after_idle()."""
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


def _widgets(w):
    yield w
    for c in w.winfo_children():
        yield from _widgets(c)


def _buttons(panel):
    return [w for w in _widgets(panel) if w.winfo_class() == "TButton"]


def test_gui():
    try:
        import tkinter  # noqa: F401
        import tkinter.ttk
    except ImportError:
        print("ПРОПУЩЕНО: нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО: нема DISPLAY (запусти через xvfb-run)")
        return
    try:
        from cps_ui.app import CpsApp, SECTIONS
        from cps_ui.settings import Settings
        import cps_restore as cr
    except ImportError as e:
        print("ПРОПУЩЕНО: нема залежностей для вікна (%s)" % e)
        return

    tmp = tempfile.mkdtemp(prefix="cpsui_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath

    app = CpsApp(settings=Settings(spath), autoprobe=False)
    try:
        app.update()
        # --- дерево ---
        tree = app.tree
        for key, text, parent in EXPECTED:
            check(tree.exists(key), "дерево: є пункт %s" % key)
            if tree.exists(key):
                check(tree.item(key, "text") == text, "дерево: %s = «%s» (є «%s»)" % (key, text, tree.item(key, "text")))
                check(tree.parent(key) == parent, "дерево: %s лежить у %r" % (key, parent))
        all_items = list(tree.get_children()) + [c for g in tree.get_children() for c in tree.get_children(g)]
        check(len(all_items) == len(EXPECTED), "дерево: рівно %d пунктів (є %d)" % (len(EXPECTED), len(all_items)))
        check(sum(len(s[2]) for s in SECTIONS) == 19, "SECTIONS: 19 панелей (R28: +теми екрана, R30: +усі налаштування, R31: +база позивних)")

        # --- стан 1: рації нема ---
        app.conn.mark_absent()
        app._refresh_all()
        for key, _t, _p in EXPECTED:
            app.show(key)
            app.update()
            want = FIRST_OF.get(key, key)           # Q2: ключ групи веде до її першого розділу
            check(app.current_key == want, "вибір %s відкрив розділ %s (є %s)" % (key, want, app.current_key))
            panel = app.get_panel(want)
            check(panel.winfo_exists() and panel.winfo_ismapped(), "панель %s видима" % want)
            others = [k for k in app._hosts if k != want and app._hosts[k].winfo_ismapped()]
            check(not others, "відкрита лише одна панель, а видно ще %s" % others)
        # дії, що потребують рації, вимкнені з поясненням
        for key in ("shot", "backup", "aes", "rctl"):
            panel = app.get_panel(key)
            app.show(key)
            app.update()
            check(panel.note is not None and "не знайдено" in panel.note.cget("text"), "%s: пояснення «рацію не знайдено» (є %r)" %
                  (key, panel.note.cget("text") if panel.note else None))
            radio_btns = [r[0] for r in panel._regs if r[1]]
            check(radio_btns and all(str(w.cget("state")) == "disabled" for w in radio_btns), "%s: кнопки, що потребують рації, вимкнені" % key)
        # без рації лишаються доступними: перегляд бекапу, CSV з бекапу, прошивка (рація може бути в DFU), оновлення
        app.show("backup"); app.update()
        check(str(app.get_panel("backup").view_file_button.cget("state")) == "normal", "без рації: «Відкрити бекап у перегляді» доступна")
        check(str(app.docbtn["open_file"].cget("state")) == "normal", "без рації: «Відкрити з бекапу» над розділами доступна")
        check(str(app.docbtn["open_radio"].cget("state")) == "disabled", "без рації: «Відкрити з рації» вимкнена")
        check("не знайдено" in app.docbar_note.cget("text"), "без рації: біля кнопок документа є причина (%r)" % app.docbar_note.cget("text"))
        app.show("flash"); app.update()
        check(str(app.get_panel("flash").flash_button.cget("state")) == "normal", "без рації: «ПРОШИТИ» доступна (рація може бути в DFU)")
        app.show("conn"); app.update()
        cp = app.get_panel("conn")
        check("не знайдено" in cp.vals["state"].cget("text"), "підключення: стан «не знайдено»")
        # CB1: рядка заряду, прапорця діагностики і блоку TX-ключа більше нема
        check("battery" not in cp.vals and "Заряд" not in " ".join(str(w.cget("text")) for w in _walk(cp) if "text" in w.keys()), "CB1: рядка «Заряд акумулятора» нема")
        app.show("shot"); app.update()
        check(not any(isinstance(w, tkinter.ttk.Checkbutton) for w in _walk(app.get_panel("shot"))), "CB1: у «Знімок екрана» нема прапорця діагностики")
        app.show("aes"); app.update()
        aes_texts = [str(w.cget("text")) for w in _walk(app.get_panel("aes")) if "text" in w.keys()]
        check(not any("TX" in t and "ключ" in t.lower() and "слот" not in t.lower() for t in aes_texts) and not hasattr(app.get_panel("aes"), "tx_btn"),
              "CB1: в «AES-ключі» нема блоку «Активний ключ для передачі (TX)»: %r" % [t for t in aes_texts if "TX" in t])
        app.show("conn"); app.update()
        check(tree.item("aes", "tags") and "dim" in tree.item("aes", "tags"), "дерево: AES приглушений без рації")
        check(not tree.item("flash", "tags"), "дерево: «Прошивка» не приглушена")

        # --- стан 2: рацію знайдено ---
        app.conn.state, app.conn.port, app.conn.searched = "found", "COM9", True
        app.conn.info = {"radioType": 6, "gitRevision": "abc1234", "buildDateTime": "20261010120000", "flashId": 1, "features": 0}
        app._refresh_all()
        for key, _t, _p in EXPECTED:
            app.show(key)
            app.update()
        app.show("conn"); app.update()
        check("COM9" in cp.vals["port"].cget("text") and "abc1234" in cp.vals["fw"].cget("text"), "підключення: порт і версія показані")
        check("MD-UV380" in cp.vals["model"].cget("text"), "підключення: модель показана")
        app.show("shot"); app.update()
        check(str(app.get_panel("shot").shot_button.cget("state")) == "normal", "з рацією: «Знімок екрана» доступний")
        check(not app.get_panel("shot").note.cget("text"), "з рацією: пояснення зникло")
        check(not tree.item("aes", "tags"), "дерево: AES не приглушений, коли рація є")
        # блокування відновлення зберігається окремо від наявності рації
        old = cr.RESTORE_UNLOCKED
        try:
            cr.RESTORE_UNLOCKED = False
            app.show("backup"); app.update()
            b = app.get_panel("backup")
            check(str(b.restore_button.cget("state")) == "disabled" and cr.LOCKED_CAPTION in b.restore_note.cget("text"), "відновлення заблоковане з підписом")
            import test_cps_csv as _tc0
            from cps_ui import document as _D0
            _cp0, _d0 = _tc0.codeplug_of(_tc0.make_fixture_spi())
            app.set_document(_D0.Document(_cp0, _D0.ORIGIN_FILE, source_file="x.zip"))
            app.update()
            check(str(app.docbtn["write"].cget("state")) == "disabled" and cr.LOCKED_CAPTION in app.docbar_note.cget("text"),
                  "запис документа заблокований з підписом біля кнопки")
            cr.RESTORE_UNLOCKED = True
            app._refresh_all()
            check(str(app.docbtn["write"].cget("state")) == "normal", "розблоковано + рація + документ: «Записати в рацію» доступна")
            app.set_document(None)
        finally:
            cr.RESTORE_UNLOCKED = old

        # --- фонове завдання: спільний журнал, блокування, повернення ---
        got = []
        app.clear_log()
        import threading
        hold = threading.Event()
        ok = app.run_task(lambda: (print("рядок з потоку"), hold.wait(5), "результат")[2], "Тестове завдання...", on_done=got.append)
        check(ok and app.busy, "завдання стартувало й виставило busy")
        check(not app.run_task(lambda: None, "друге"), "друге завдання під час першого відхилено (один USB)")
        app.show("shot"); app.update()
        check(str(app.get_panel("shot").shot_button.cget("state")) == "disabled", "під час завдання кнопки вимкнені")
        check("зачекай" in app.get_panel("shot").note.cget("text").lower(), "під час завдання є пояснення")
        hold.set()
        for _ in range(100):
            app.update()
            if not app.busy:
                break
            time.sleep(0.02)
        check(not app.busy and got == ["результат"], "завдання завершилось: on_done отримав результат (%r)" % got)
        check("рядок з потоку" in app.log_text.get("1.0", "end"), "print() з потоку потрапив у спільний журнал")
        check(str(app.get_panel("shot").shot_button.cget("state")) == "normal", "після завдання кнопки знову доступні")

        # --- підключення кешується: повторного пошуку без запиту нема ---
        import cps_ui.connection as cn
        calls = []
        orig = cn.cps.find_port
        cn.cps.find_port = lambda: (calls.append(1), None)[1]
        try:
            app.refresh_connection(force=True)
            for _ in range(100):
                app.update()
                if not app.busy:
                    break
                time.sleep(0.02)
            n1 = len(calls)
            for key, _t, _p in EXPECTED:
                app.show(key)
                app.update()
            check(n1 == 1 and len(calls) == 1, "пошук рації: один раз на «Оновити», далі кеш (викликів %d)" % len(calls))
            check(app.conn.state == "absent", "після «Оновити» без рації: стан absent")
        finally:
            cn.cps.find_port = orig

        # --- Q1: панель заповнює область на мінімальному й великому розмірі вікна ---
        import test_cps_csv as tc
        _spi = tc.make_fixture_spi()
        _cp, _d = tc.codeplug_of(_spi)
        from cps_ui import document as _D
        app.set_document(_D.Document(_cp, _D.ORIGIN_FILE, source_file="тест.zip"))
        leaf = [k for k in app.section_keys() if k not in FIRST_OF]
        for (W, H) in ((760, 520), (1800, 1000)):
            app.geometry("%dx%d" % (W, H))
            for _ in range(4):
                app.update()
            rw, rh = app.right.winfo_width(), app.right.winfo_height() - app.docbar.winfo_height()
            check(rw >= W - 420 and rh >= H - 270, "Q1 %dx%d: область панелі велика (%dx%d)" % (W, H, rw, rh))
            for key in leaf:
                app.show(key)
                for _ in range(3):
                    app.update()
                host = app._hosts[key]
                check(host.winfo_width() >= rw - 2 and host.winfo_height() >= rh - 2,
                      "Q1 %dx%d: %s заповнює область (%dx%d з %dx%d)" % (W, H, key, host.winfo_width(), host.winfo_height(), rw, rh))
                pan = app.get_panel(key)
                check(pan.winfo_width() >= rw - 24, "Q1 %dx%d: панель %s на всю ширину (%d з %d)" % (W, H, key, pan.winfo_width(), rw))
                if key == "aes" and W > 1000:
                    ke = app.get_panel("aes").key_entry
                    check(ke.winfo_width() >= 0.5 * rw, "Q1: поле ключа AES розтягується (%d з %d)" % (ke.winfo_width(), rw))
            if W > 1000:
                app.show("aprs")
                for _ in range(3):
                    app.update()
                ap = app.get_panel("aprs")
                check(ap._wide is True, "Q1: на широкому вікні APRS у двох колонках")
                check(int(str(ap.note.cget("wraplength"))) > 700, "Q1: пояснення переносяться за шириною панелі (%s)" % ap.note.cget("wraplength"))
            else:
                app.show("aprs")
                for _ in range(3):
                    app.update()
                check(app.get_panel("aprs")._wide is False, "Q1: на малому вікні APRS в одну колонку")
        app.set_document(None)
        app.geometry("1000x700")
        for _ in range(4):
            app.update()
        # Q6.1: дерево на всю висоту лівої колонки
        left = app.tree.master
        check(app.tree.winfo_y() + app.tree.winfo_height() >= left.winfo_height() - 2, "Q6.1: дерево тягнеться до низу лівої колонки")

        # --- Q2: клік по групі в дереві відкриває перший розділ; кнопок-дублікатів дерева нема ---
        for g, first in FIRST_OF.items():
            tree.selection_set(g)
            app.update()
            check(app.current_key == first, "Q2: клік по групі %s відкрив %s (є %s)" % (g, first, app.current_key))
            check(str(tree.item(g, "open")) in ("1", "True", "true"), "Q2: група %s розгорнута" % g)
        titles = {t for _k, t, _p in EXPECTED}
        dup = []
        for key in app.section_keys():
            if key in FIRST_OF:
                continue
            for w in _buttons(app.get_panel(key)):
                if str(w.cget("text")) in titles and key != "shot":          # «Знімок екрана» у своїй панелі -- дія, а не перехід
                    dup.append((key, str(w.cget("text"))))
        check(not dup, "Q2: кнопок-дублікатів назв дерева нема: %r" % dup)

        # --- Q5/Q4: смужка прогресу -- лише під час операції ---
        app.update()
        check(not app.progress.winfo_ismapped(), "Q5: у спокої смужки прогресу не видно")
        status_children = [w for w in _widgets(app) if w.winfo_class() == "TEntry" and not str(w).startswith(str(app.right))]
        check(not status_children, "Q4: у вікні поза панелями нема полів вводу без підпису: %r" % status_children)
        gate = threading.Event()
        app.run_task(lambda: gate.wait(5), "Тривала операція...")
        app.update()
        check(app.progress.winfo_ismapped(), "Q5: під час операції смужка видна")
        check("Тривала операція" in app.status_label.cget("text"), "Q5: рядок стану каже, що відбувається")
        gate.set()
        for _ in range(200):
            app.update()
            if not app.busy:
                break
            time.sleep(0.02)
        app.update()
        check(not app.progress.winfo_ismapped(), "Q5: після завершення смужку сховано")
        def boom():
            raise RuntimeError("тестова помилка")
        import tkinter.messagebox as mb
        old_err = mb.showerror
        mb.showerror = lambda *a, **k: None
        try:
            app.run_task(boom, "Операція з помилкою...", plain_errors=True)
            app.update()
            check(app.progress.winfo_ismapped(), "Q5: під час операції (що впаде) смужка видна")
            for _ in range(200):
                app.update()
                if not app.busy:
                    break
                time.sleep(0.02)
            app.update()
        finally:
            mb.showerror = old_err
        check(not app.progress.winfo_ismapped(), "Q5: після помилки смужку теж сховано")

        # --- журнал згортається ---
        was = app._log_open
        app.toggle_log(); app.update()
        check(app._log_open != was and (app.log_frame.winfo_ismapped() == app._log_open), "журнал згортається/розгортається")
        app.toggle_log(); app.update()
        check(app._log_open == was, "журнал повертається")

        # --- налаштування переживають перезапуск ---
        app.show("rctl")
        app.geometry("910x600")
        for _ in range(4):
            app.update()
        app.vpane.sashpos(0, app.vpane.winfo_height() - 250)       # Q3.2: користувач потягнув межу журналу
        app.hpane.sashpos(0, 380)                                   # Q6.2: і межу лівої колонки
        app.update()
        check(app.save_settings(), "налаштування записано")
        check(app.settings.get("log_height") and abs(app.settings.get("log_height") - 250) <= 8, "Q3.2: висота журналу в налаштуваннях: %r" % app.settings.get("log_height"))
        check(app.settings.get("left_width") and abs(app.settings.get("left_width") - 380) <= 4, "Q6.2: ширина колонки в налаштуваннях: %r" % app.settings.get("left_width"))
    finally:
        app.destroy()
    app2 = CpsApp(settings=Settings(spath), autoprobe=False)
    try:
        _spin(app2)
        lh2 = app2.vpane.winfo_height() - app2.vpane.sashpos(0)
        check(abs(lh2 - 250) <= 8, "Q3.2: висота журналу відновлена після перезапуску (%d)" % lh2)
        check(abs(app2.hpane.sashpos(0) - 380) <= 4, "Q6.2: ширина колонки відновлена після перезапуску (%d)" % app2.hpane.sashpos(0))
        check(app2.current_key == "rctl", "після перезапуску відкрито останній розділ: %r" % app2.current_key)
        check(app2.settings.get("width") == 910 and app2.settings.get("height") == 600, "розмір вікна запам'ятовано: %r" % ((app2.settings.get("width"), app2.settings.get("height")),))
        check(tuple(app2.geometry().split("+")[0].split("x")) == ("910", "600"), "вікно відкрилось 910x600: %s" % app2.geometry())
    finally:
        app2.destroy()
    # зіпсований файл налаштувань не заважає запуску
    with open(spath, "w", encoding="utf-8") as f:
        f.write("{не json")
    app3 = CpsApp(settings=Settings(spath), autoprobe=False)
    try:
        app3.geometry("1000x700")
        _spin(app3)
        check(app3.current_key == "conn", "зіпсовані налаштування: стандартний розділ")
        lh3 = app3.vpane.winfo_height() - app3.vpane.sashpos(0)
        check(60 <= lh3 <= 150 and lh3 < 0.25 * app3.winfo_height(), "Q3.1: типова висота журналу низька: %d з %d" % (lh3, app3.winfo_height()))
        check(app3.log_text.cget("height") == 4, "Q3.1: журнал на 4 рядки")
    finally:
        app3.destroy()


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)


def main():
    test_launcher_is_thin()
    test_gui()
    if FAILS:
        print("test_cps_ui: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_cps_ui: усі перевірки пройшли (дерево, кожен розділ відкривається, вимкнення з поясненням, кеш підключення, налаштування).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
