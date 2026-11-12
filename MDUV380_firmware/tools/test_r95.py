#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R95 (хост): переклад підписів меню української збірки.
  1  ukrainian.h (cp1251): нові значення на місці (key_long, key_repeat, dmr_filter_timeout, private_call_handling, tx_inhibit, priority_order, info; нові поля talker_beep, contact_lines, contact_order_0..3 -- ОСТАННІ в блоці UA);
  2  старі тексти зникли з українського меню (поля, що змінено, не мають старого значення);
  3  спільні поля `talker`, `contact`, `auto_lock`, `audio_prompt` не змінено проти старих значень; коли «Автоблок.»/«Звуки» лишаються -- це свідомо (ширина);
  4  нові поля є в english.h (дзеркало в UA-блоці) і в uiLanguage.h; не-UA stringsTable_t їх не має (gcc -E);
  5  меню: у UA-збірках пункти беруть нові поля, у не-UA -- стокові (gcc -E); значення «Пріор.» -- 4 нових рядки з мовних полів; масив contactOrders у не-UA лишився;
  6  tools/check_menu_widths.py без переповнень;
  7  мутанти.
Порівняння з комітом бази (R95_BASE) стійке до його відсутності: без коміта -- ПРОПУСК з повідомленням.
Запуск: python3 tools/test_r95.py"""
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); FW = os.path.dirname(HERE); sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa
APP = os.path.join(FW, "application"); LANG = os.path.join(APP, "include", "user_interface", "languages"); UI = "application/source/user_interface/"
BASE = os.environ.get("R95_BASE", "2bf7a41")
FAILS = []; N = [0]; Q = [False]
WANT = {"key_long": "Довгий нат.", "key_repeat": "Повт. клав.", "dmr_filter_timeout": "Утрим. слота", "private_call_handling": "Прив. викл.", "tx_inhibit": "Заборона TX",
        "priority_order": "Пріор.", "info": "Позначки", "talker_beep": "Біп абон.", "contact_lines": "Рядки",
        "contact_order_0": "КП/БД/TA", "contact_order_1": "БД/КП/TA", "contact_order_2": "TA/КП/БД", "contact_order_3": "TA/БД/КП"}
OLD = {"key_long": "Довге нат.", "key_repeat": "Повтор", "dmr_filter_timeout": "Час фільтра", "private_call_handling": "Дозвіл PC", "tx_inhibit": "Блок. TX", "priority_order": "Порядок", "info": "Інфо"}
SHARED = {"talker": "Абонент", "contact": "Контакт", "auto_lock": "Автоблок.", "audio_prompt": "Звуки"}
NEW_TAIL = ["talker_beep", "contact_lines", "contact_order_0", "contact_order_1", "contact_order_2", "contact_order_3"]
def check(c, m):
    if not Q[0]: N[0] += 1
    if not c:
        FAILS.append(m)
        if not Q[0]: print("ПРОВАЛ: " + m)
def rd(p, enc="utf-8"): return open(p, "rb").read().decode(enc)
def fields(t): return dict((m.group(1), m.group(2)) for m in re.finditer(r'^\.(\w+)\s*=\s*"([^"]*)"', t, re.M))
def pp(incs, defs, rel):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=FW, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
def texts_ok(ua):
    f = fields(ua); o = []
    for k, v in WANT.items():
        if f.get(k) != v: o.append("%s = %r, очікувано %r" % (k, f.get(k), v))
    for k, v in OLD.items():
        if f.get(k) == v: o.append("старий текст %r лишився в %s" % (v, k))
    for k, v in SHARED.items():
        if f.get(k) != v: o.append("спільне поле %s змінено: %r" % (k, f.get(k)))
    names = list(f)
    if [n for n in names if n != "talkaround_menu"][-6:] != NEW_TAIL: o.append("нові поля не останні в блоці UA")
    return o
def main():
    ua = rd(os.path.join(LANG, "ukrainian.h"), "cp1251")
    e = texts_ok(ua)
    for x in e: check(False, x)
    check(not e, "ukrainian.h: нові значення на місці, старих нема, спільні поля цілі")
    en = rd(os.path.join(LANG, "english.h"), "cp1251"); fe = fields(en)
    for k in NEW_TAIL: check(k in fe, "english.h має поле " + k)
    incs, cfgs = cmt.load_configs(FW); cf = dict(cfgs)
    th = pp(incs, cf["AES0"], "application/include/user_interface/languages/uiLanguage.h")
    check(th and not any(k in th for k in NEW_TAIL), "не-UA: stringsTable_t без нових полів")
    th = pp(incs, cf["FULLUSER"], "application/include/user_interface/languages/uiLanguage.h")
    check(th and all(k in th for k in NEW_TAIL), "UA: stringsTable_t має нові поля")
    for n in ("FULLUSER", "UA"):
        t = pp(incs, cf[n], UI + "menuSoundOptions.c"); check(t and "currentLanguage->talker_beep" in t and "currentLanguage->talker, currentLanguage->both" in t, n + ": пункт «Біп абон.» бере talker_beep, значення «Звук RX» -- talker")
        t = pp(incs, cf[n], UI + "menuDisplayOptions.c"); check(t and "contact_lines" in t and "contact_order_3" in t and "contactOrders" not in t, n + ": «Рядки» і «Пріор.» з нових полів, масиву contactOrders нема")
    for n in ("AES0", "AES1", "ENDATA"):
        t = pp(incs, cf[n], UI + "menuSoundOptions.c"); check(t and "talker_beep" not in t and "leftSide = currentLanguage->talker;" in t, n + " (не-UA): стокове talker")
        t = pp(incs, cf[n], UI + "menuDisplayOptions.c"); check(t and "contact_lines" not in t and "contact_order" not in t and '"Ct/DB/TA"' in t and "leftSide = currentLanguage->contact;" in t, n + " (не-UA): contactOrders і contact як були")
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_menu_widths.py")], capture_output=True, text=True); check(r.returncode == 0 and "Переповнень не знайдено" in r.stdout, "check_menu_widths: переповнень нема")
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_string_encoding.py")], capture_output=True, text=True); check(r.returncode == 0, "check_string_encoding чисто")
    dsp = rd(os.path.join(APP, "source", "user_interface", "menuDisplayOptions.c")); snd = rd(os.path.join(APP, "source", "user_interface", "menuSoundOptions.c"))
    check(not re.search(r'"[^"\n]*[А-Яа-яІіЇїЄєҐґ][^"\n]*"', re.sub(r"//[^\n]*", "", dsp + snd)), "у .c нема кириличних рядкових літералів")
    wf = os.path.join(FW, "..", ".github", "workflows")
    if os.path.isdir(wf):
        txt = "".join(rd(os.path.join(wf, f)) for f in sorted(os.listdir(wf)) if f.endswith((".yml", ".yaml")))
        check("ubuntu-latest" not in txt and "ubuntu-24.04" in txt, "CI: ubuntu-latest замінено на ubuntu-24.04")
    else:
        print("ПРОПУСК: .github/workflows відсутній")
    # база
    if subprocess.run(["git", "-C", FW, "cat-file", "-e", BASE + "^{commit}"], capture_output=True).returncode == 0:
        b = subprocess.run(["git", "-C", FW, "show", "%s:MDUV380_firmware/application/include/user_interface/languages/ukrainian.h" % BASE], capture_output=True)
        old = fields(b.stdout.decode("cp1251")); new = fields(ua)
        d = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        check(d == sorted(list(OLD) + NEW_TAIL), "ukrainian.h: змінено рівно очікувані поля: %r" % d)
    else:
        print("ПРОПУСК: база недоступна (CI/клон без історії): ukrainian.h «змінено рівно очікувані поля» -- не перевірено (база %s)" % BASE)
    # мутанти
    def mut(n, u): Q[0] = True; o = texts_ok(u); Q[0] = False; check(bool(o), "мутант «%s» ловиться" % n)
    mut("забули key_long", ua.replace('"Довгий нат."', '"Довге нат."'))
    mut("старий info", ua.replace('"Позначки"', '"Інфо"'))
    mut("змінили спільне talker", ua.replace('.talker                                  = "Абонент"', '.talker                                  = "Біп абон."'))
    mut("змінили auto_lock", ua.replace('"Автоблок."', '"Автоблокування"'))
    mut("порядок значень", ua.replace('"КП/БД/TA"', '"БД/КП/TA"', 1))
    print("test_r95: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0])); return 1 if FAILS else 0
if __name__ == "__main__": sys.exit(main())
