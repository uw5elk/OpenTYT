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
    ("viewer", "Перегляд кодплага", "grp_codeplug"),
    ("csv", "CSV", "grp_codeplug"),
    ("grp_settings", "Налаштування рації", ""),
    ("aprs", "APRS: бікон і позивний", "grp_settings"),
    ("aes", "AES-ключі", "grp_settings"),
    ("rctl", "Віддалене керування (RCTL)", "grp_settings"),
]


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


def _widgets(w):
    yield w
    for c in w.winfo_children():
        yield from _widgets(c)


def _buttons(panel):
    return [w for w in _widgets(panel) if w.winfo_class() == "TButton"]


def test_gui():
    try:
        import tkinter  # noqa: F401
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
        check(sum(len(s[3]) for s in SECTIONS) == 9, "SECTIONS: 9 панелей")

        # --- стан 1: рації нема ---
        app.conn.mark_absent()
        app._refresh_all()
        for key, _t, _p in EXPECTED:
            app.show(key)
            app.update()
            check(app.current_key == key, "вибір %s відкрив розділ" % key)
            panel = app.get_panel(key)
            check(panel.winfo_exists() and panel.winfo_ismapped(), "панель %s видима" % key)
            others = [k for k in app._hosts if k != key and app._hosts[k].winfo_ismapped()]
            check(not others, "відкрита лише одна панель, а видно ще %s" % others)
        # дії, що потребують рації, вимкнені з поясненням
        for key in ("shot", "backup", "csv", "viewer", "aprs", "aes", "rctl"):
            panel = app.get_panel(key)
            app.show(key)
            app.update()
            check(panel.note is not None and "не знайдено" in panel.note.cget("text"), "%s: пояснення «рацію не знайдено» (є %r)" %
                  (key, panel.note.cget("text") if panel.note else None))
            radio_btns = [w for (w, radio, _w) in panel._regs if radio]
            check(radio_btns and all(str(w.cget("state")) == "disabled" for w in radio_btns), "%s: кнопки, що потребують рації, вимкнені" % key)
        # без рації лишаються доступними: перегляд бекапу, CSV з бекапу, прошивка (рація може бути в DFU), оновлення
        app.show("backup"); app.update()
        check(str(app.get_panel("backup").view_file_button.cget("state")) == "normal", "без рації: «Переглянути бекап» доступна")
        app.show("csv"); app.update()
        check(str(app.get_panel("csv").csv_export_file_button.cget("state")) == "normal", "без рації: «CSV з бекапу» доступна")
        app.show("flash"); app.update()
        check(str(app.get_panel("flash").flash_button.cget("state")) == "normal", "без рації: «ПРОШИТИ» доступна (рація може бути в DFU)")
        app.show("conn"); app.update()
        cp = app.get_panel("conn")
        check("не знайдено" in cp.vals["state"].cget("text"), "підключення: стан «не знайдено»")
        check("недоступно" in cp.vals["battery"].cget("text"), "підключення: заряд -- чесне «недоступно»")
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
            app.show("csv"); app.update()
            c = app.get_panel("csv")
            check(str(c.csv_import_button.cget("state")) == "disabled" and cr.LOCKED_CAPTION in c.import_note.cget("text"), "імпорт CSV заблокований з підписом")
            cr.RESTORE_UNLOCKED = True
            app._refresh_all()
            check(str(c.csv_import_button.cget("state")) == "normal", "розблоковано + рація: імпорт доступний")
        finally:
            cr.RESTORE_UNLOCKED = old

        # --- фонове завдання: спільний журнал, блокування, повернення ---
        got = []
        app.clear_log()
        ok = app.run_task(lambda: (print("рядок з потоку"), "результат")[1], "Тестове завдання...", on_done=got.append)
        check(ok and app.busy, "завдання стартувало й виставило busy")
        check(not app.run_task(lambda: None, "друге"), "друге завдання під час першого відхилено (один USB)")
        app.show("shot"); app.update()
        check(str(app.get_panel("shot").shot_button.cget("state")) == "disabled", "під час завдання кнопки вимкнені")
        check("зачекай" in app.get_panel("shot").note.cget("text").lower(), "під час завдання є пояснення")
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

        # --- журнал згортається ---
        was = app._log_open
        app.toggle_log(); app.update()
        check(app._log_open != was and (app.log_frame.winfo_ismapped() == app._log_open), "журнал згортається/розгортається")
        app.toggle_log(); app.update()
        check(app._log_open == was, "журнал повертається")

        # --- налаштування переживають перезапуск ---
        app.show("rctl")
        app.geometry("910x600")
        app.update()
        check(app.save_settings(), "налаштування записано")
    finally:
        app.destroy()
    app2 = CpsApp(settings=Settings(spath), autoprobe=False)
    try:
        app2.update()
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
        app3.update()
        check(app3.current_key == "conn", "зіпсовані налаштування: стандартний розділ")
    finally:
        app3.destroy()


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
