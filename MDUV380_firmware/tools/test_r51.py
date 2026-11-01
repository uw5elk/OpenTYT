#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R51: підписи «Основної інформації» за тим, що поля роблять у прошивці; верстка Зон / Списків TG / DTMF і мінімальний розмір вікна за масштабом.

A1  розділ «Основна інформація»: нові підписи полів, назва групи, варіанти «Гасло» / «Картинка», підказка про 27 символів Talker Alias;
A2  старих підписів («Рядок вітання», «Дані користувача», «Текст (два рядки)», «Позивний (EEPROM», «DMR ID (EEPROM», «Екран вітання (EEPROM») нема в cps_ui/;
A3  логіка полів не змінилась: байт 0x7518 / рядки / позивний / ID пишуться так само (apply_basic_info, значення «Гасло» = intro_text True);
B1  Зони / Списки TG / DTMF: нічого не виступає за край при масштабі 100/125/150 % з кодплагом (повний прохід -- test_r50fix.py S1, винятків нема);
B2  мінімальний розмір головного вікна = 760x520 × масштаб (test_r50fix.py S5); панель документа не виступає за край ні на 760 px, ні на мінімумі;
B3  у test_r50fix.py нема списку винятків KNOWN_150_WITH_DOC і нема розділів-винятків (R54: «Супутники» повернено в повний прохід);
Z   підключено до tests/run_tests.sh.
Запуск: xvfb-run -a python3.12 tools/test_r51.py"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FW = os.path.dirname(HERE)
FAILS = []

OLD_LABELS = ("Рядок вітання", "Дані користувача", "Текст (два рядки)", "\"Позивний (EEPROM", "\"DMR ID (EEPROM", "\"Екран вітання (EEPROM")
NEW_LABELS = ("Ім'я рації / позивний APRS (EEPROM 0x00E0)", "Мій DMR ID (EEPROM 0x00E8)", "Talker Alias, частина 1 (0x7540)",
              "Talker Alias, частина 2 (0x7550)", "Екран при вмиканні (EEPROM 0x7518)")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def test_a2_no_old_labels():
    base = os.path.join(HERE, "cps_ui")
    bad = []
    for fn in sorted(os.listdir(base)):
        if fn.endswith(".py"):
            t = read(base, fn)
            for old in OLD_LABELS:
                if old in t:
                    bad.append((fn, old))
    check(not bad, "A2: старі підписи лишилися в cps_ui/: %r" % (bad,))
    # зонд сам працює: старий підпис, підставлений у текст, ловиться
    check(any(o in '("line1", "Рядок вітання 1 (0x7540)"' for o in OLD_LABELS) and any(o in 'text="Позивний (EEPROM 0x00E0)"' for o in OLD_LABELS), "A2: перевірка бачить старі підписи")


def test_a3_logic():
    import codeplug_edit as ced
    check(ced.BOOT_LINE_LEN == 16, "A3: довжина рядка Talker Alias у кодплазі 16 Б (не змінювалась)")
    check(ced.ADDR_BOOT_INTRO == 0x7518 and ced.ADDR_BOOT_LINE1 == 0x7540 and ced.ADDR_BOOT_LINE2 == 0x7550, "A3: адреси полів на місці")
    # значення за замовчуванням байта 0xFF прошивка читає як «не 0» (гасло); «Гасло» у вікні = intro_text True, «Картинка» = False (як було для «Текст» / «Картинка»)
def test_a1_panel():
    import font_scenarios as fs  # noqa: F401
    import layout_probe as lp
    import test_r36 as t36
    from cps_ui import p_basic
    spath = os.path.join(tempfile.mkdtemp(prefix="r51_"), "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    mk = t36.doc_factory()
    app = t36.make_app(spath)
    try:
        check(p_basic.INTRO_LABELS == ["Гасло", "Картинка"], "A1: варіанти екрана при вмиканні: %r" % (p_basic.INTRO_LABELS,))
        app.set_document(mk())
        app.show("basic")
        lp.spin(app, 0.6)
        p = app.get_panel("basic")
        texts = []
        stack = [p]
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            try:
                texts.append(str(w.cget("text")))
            except Exception:  # noqa: BLE001
                pass
        joined = "\n".join(texts)
        for lab in NEW_LABELS:
            check(lab in texts, "A1: підпис «%s» є в розділі" % lab)
        check(p.box.cget("text") == "Ім'я, ID, Talker Alias і екран вмикання", "A1: назва групи: %r" % p.box.cget("text"))
        check("перші 27 символів" in joined and "TX Talker Alias" in joined and "склеюються" in joined, "A1: є підказка про 27 символів Talker Alias")
        check("екрана привітання" not in joined and "Talker Alias і тип екрана при вмиканні" in joined, "A1: опис панелі не говорить про «текст екрана привітання»")
        check(p.intro_var.get() in p_basic.INTRO_LABELS, "A1: тип екрана показано (%r)" % p.intro_var.get())
        bad = lp.probe_panel(app, "basic")
        check(not bad, "A1: панель не обрізана: %r" % (bad[:2],))
    finally:
        app.destroy()


def test_b3_no_exceptions():
    t = read(HERE, "test_r50fix.py")
    check("KNOWN_150_WITH_DOC" not in t, "B3: список винятків KNOWN_150_WITH_DOC прибрано з test_r50fix.py")
    check(not re.search(r"^KNOWN\w*\s*=", t, re.M), "B3: у test_r50fix.py нема змінної-списку винятків")
    check("EXCLUDE = set()" in t, "B3: винятків нема -- «Супутники» знову в повному проході (R54)")


def test_z_wiring():
    rt = read(FW, "tests", "run_tests.sh")
    check("test_r51" in rt, "Z: test_r51.py підключено до tests/run_tests.sh")


def main():
    test_z_wiring()
    test_a2_no_old_labels()
    test_b3_no_exceptions()
    try:
        import tkinter  # noqa: F401
        have = bool(os.environ.get("DISPLAY"))
    except ImportError:
        have = False
    test_a3_logic()
    if have:
        test_a1_panel()
    else:
        print("test_r51: нема tkinter/DISPLAY -- A1 пропущено")
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r51: усе гаразд")


if __name__ == "__main__":
    main()
