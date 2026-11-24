#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R94-А (хост): переклад «Ключі AES» (заголовок екрана), «Роумінг» (перевірка, що вже так), «Без репітера» (швидке меню каналу).
  1  ukrainian.h (cp1251): talkaround_menu = «Без репітера» ОСТАННІМ полем UA; спільне talkaround = «Talkaround» (голосова підказка) і roaming = «Roaming» (швидке меню) не змінено;
  2  gcc -E: у UA-конфігураціях menuAESKeys.c бере currentLanguage->aes_keys, uiChannelMode.c -- talkaround_menu; у не-UA лишились "AES Keys" і talkaround, поля talkaround_menu нема;
  3  UA: ROAM_MENU_NAME = «Роумінг» (roam_ua.h), голосова підказка uiUtilities.c бере talkaround;
  4  ширина (check_menu_widths) і cp1251; змінено рівно 1 поле ukrainian.h відносно бази;
  5  мутанти. Запуск: python3 tools/test_r94a.py"""
import os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa
APP = os.path.join(FW, "application"); LANG = os.path.join(APP, "include", "user_interface", "languages"); UI = os.path.join(APP, "source", "user_interface")
FAILS = []; N = [0]; Q = [False]
def check(c, m):
    if not Q[0]: N[0] += 1
    if not c:
        FAILS.append(m)
        if not Q[0]: print("ПРОВАЛ: " + m)
def rd(p, enc="utf-8"): return open(p, "rb").read().decode(enc)
def fields(t): return dict((m.group(1), m.group(2)) for m in re.finditer(r'^\.((?!dual_)\w+)\s*=\s*"([^"]*)"', t, re.M))   # R97: поля dual_* -- пізніші (test_r97)
def pp(incs, defs, rel):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=FW, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
def texts_ok(ua):
    f = fields(ua); o = []
    if f.get("talkaround_menu") != "Без репітера": o.append("talkaround_menu")
    if [n for n in f if not n.startswith(("talker_beep", "contact_lines", "contact_order_"))][-1] != "talkaround_menu": o.append("talkaround_menu не останнє (після нього лише поля R95)")
    if f.get("talkaround") != "Talkaround": o.append("спільне talkaround змінено")
    if f.get("roaming") != "Roaming": o.append(".roaming змінено")
    if f.get("aes_keys") != "Ключі AES": o.append("aes_keys")
    return o
def main():
    ua = rd(os.path.join(LANG, "ukrainian.h"), "cp1251")
    e = texts_ok(ua)
    for x in e: check(False, x)
    check(not e, "ukrainian.h: підписи на місці, спільні поля не змінено")
    incs, cfgs = cmt.load_configs(FW); cf = dict(cfgs)
    ka = "application/source/user_interface/menuAESKeys.c"; ch = "application/source/user_interface/uiChannelMode.c"
    for n in ("FULLUSER", "UA"):
        t = pp(incs, cf[n], ch); check(t and "talkaround_menu" in t, n + ": швидке меню бере talkaround_menu")
    uu = rd(os.path.join(UI, "uiUtilities.c")); check("voicePromptsAppendLanguageString(currentLanguage->talkaround)" in uu, "голосова підказка (uiUtilities.c) лишилась на talkaround")
    roam = rd(os.path.join(LANG, "roam_ua.h"), "cp1251")
    check('#define ROAM_MENU_NAME        "Роумінг"' in roam, "roam_ua.h: ROAM_MENU_NAME = «Роумінг»")
    for n in ("AES0", "AES1", "ENDATA"):
        t = pp(incs, cf[n], ch); check(t and "talkaround_menu" not in t and "currentLanguage->talkaround;" in t, n + " (не-UA): talkaround")
    t = pp(incs, cf["AES1"], ka) or ""
    check('"AES Keys"' in t and "currentLanguage->aes_keys" not in t.split("menuDisplayTitle")[1] if "menuDisplayTitle" in t else False, "AES1 (не-UA): заголовок «AES Keys» як у базі")
    t = pp(incs, cf["FULLUSER"], ka) or ""
    check("menuDisplayTitle(currentLanguage->aes_keys)" in t, "UA: заголовок = aes_keys")
    th = pp(incs, cf["AES0"], "application/include/user_interface/languages/uiLanguage.h"); check(th and "talkaround_menu" not in th, "не-UA: stringsTable_t без нового поля")
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_menu_widths.py")], capture_output=True, text=True); check(r.returncode == 0 and "Переповнень не знайдено" in r.stdout, "check_menu_widths")
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_string_encoding.py")], capture_output=True, text=True); check(r.returncode == 0, "check_string_encoding")
    # мутанти
    def mut(n, ua2): Q[0] = True; e = texts_ok(ua2); Q[0] = False; check(bool(e), "мутант «%s»" % n)
    mut("забули підпис", ua.replace('"Без репітера"', '"Talkaround"'))
    mut("змінили спільне talkaround", ua.replace('.talkaround                              = "Talkaround"', '.talkaround                              = "Без репітера"'))
    mut("змінили .roaming", ua.replace('.roaming                                 = "Roaming"', '.roaming                                 = "Роумінг"'))
    print("test_r94a: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0])); return 1 if FAILS else 0
if __name__ == "__main__": sys.exit(main())
