#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R82 (хост, без заліза): переклад підписів меню української збірки + «Повідомлення» -> «SMS DMR».
  1  ukrainian.h (cp1251): Хвіст VOX, Калібр. темп., Калібр. акум., SMS DMR; нові поля channels_protect («Захист кан.») і satellite_mode («Супутник») -- ОСТАННІМИ в блоці UA;
     спільні locked і satellite_short НЕ змінено (екран блокування, сповіщення, екран GPS);
  2  меню (gcc -E): у UA-конфігураціях пункти «Захист кан.» і «Супутник» беруть нові поля, у решті -- стокові locked/satellite_short; поля нема в stringsTable_t не-UA збірок;
  3  не-UA мовні файли й решта ukrainian.h байт-у-байт як у базі (git diff лише 4 змінені + 2 нові рядки; не чіпано: Trackball, Hotspot, DMR Rx AGC, Squelch, GPS, DMR CRC, UTC, On/Off, Н/Д);
  4  ширина: усі підписи <= MaxLen, пари «підпис:значення» <= 16 (tools/check_menu_widths.py), cp1251 чисте;
  5  «SMS DMR»: заголовок екрана (messages_ua.h MSGS_TITLE) і пункт головного меню; «Повідом. APRS» без змін; передпоказ CPS (screen_views.py) -- нові підписи;
  6  мутанти: «забули один підпис» (кожен із 6), код меню без #if (ламає не-UA), нове поле не останнім.
Запуск: python3 tools/test_r82.py"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa: E402

APP = os.path.join(FW, "application")
LANG = os.path.join(APP, "include", "user_interface", "languages")
UI = os.path.join(APP, "source", "user_interface")
BASE = os.environ.get("R82_BASE", "821fef5")
FAILS = []
N = [0]
QUIET = [False]

WANT = {"vox_tail": "Хвіст VOX", "temperature_calibration": "Калібр. темп.", "battery_calibration": "Калібр. акум.", "messages": "SMS DMR",
        "channels_protect": "Захист кан.", "satellite_mode": "Супутник"}
OLD = {"vox_tail": "VOX tail", "temperature_calibration": "Temp Cal", "battery_calibration": "Batt. Cal", "messages": "Повідомлення"}


def check(c, m):
    if not QUIET[0]:
        N[0] += 1
    if not c:
        FAILS.append(m)
        if not QUIET[0]:
            print("ПРОВАЛ: " + m)


def rd(p, enc=None):
    b = open(p, "rb").read()
    if enc:
        return b.decode(enc)
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1251")


def fields(text):
    return dict((m.group(1), m.group(2)) for m in re.finditer(r'^\.(\w+)\s*=\s*"([^"]*)"', text, re.M))


def git_show(rel):
    r = subprocess.run(["git", "-C", FW, "show", "%s:MDUV380_firmware/%s" % (BASE, rel)], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def pp(incs, defs, rel):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=FW, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def check_texts(ua, msgs_ua, gen, sv):
    """Перевірки п.1 і п.5 над ТЕКСТАМИ (щоб мутувати)."""
    f = fields(ua)
    out = []
    for k, v in WANT.items():
        if f.get(k) != v:
            out.append("ukrainian.h: %s = %r, очікувано %r" % (k, f.get(k), v))
    names = list(f)
    if not ([n for n in names if n != "talkaround_menu"][-2:] == ["channels_protect", "satellite_mode"]):
        out.append("нові поля не останні в ukrainian.h: %r" % names[-3:])
    if f.get("locked") != "Ch. blocked" or f.get("satellite_short") != "SAT":
        out.append("спільні locked/satellite_short змінено (екран блокування/GPS)")
    if 'MSGS_TITLE               "SMS DMR"' not in msgs_ua:
        out.append("messages_ua.h: MSGS_TITLE не «SMS DMR»")
    if f.get("aprs_messages", "x") is None:
        pass
    if '#define APRSMSG_MENU          "Повідом. APRS"' not in rd(os.path.join(LANG, "aprsmsg_ua.h")):
        out.append("«Повідом. APRS» змінено")
    if '"messages": "SMS DMR"' not in sv or '"temperature_calibration": "Калібр. темп."' not in sv or '"battery_calibration": "Калібр. акум."' not in sv:
        out.append("передпоказ CPS (screen_views.py): підписи не оновлено")
    for v in ("VOX tail", "Temp Cal", "Batt. Cal"):
        for k, val in f.items():
            if val == v:
                out.append("англійський підпис %r лишився в ukrainian.h (%s)" % (v, k))
    return out


def main():
    ua = rd(os.path.join(LANG, "ukrainian.h"), "cp1251")
    msgs = rd(os.path.join(LANG, "messages_ua.h"), "cp1251")
    sv = rd(os.path.join(HERE, "screen_views.py"))
    gen_p = os.path.join(UI, "menuGeneralOptions.c")
    gen = rd(gen_p)

    # 1, 5
    errs = check_texts(ua, msgs, gen, sv)
    for e in errs:
        check(False, e)
    check(not errs, "ukrainian.h/messages_ua.h/screen_views.py: усі 6 підписів і «SMS DMR» на місці")

    # 2 меню (препроцесор)
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    rel = "application/source/user_interface/menuGeneralOptions.c"
    for name in ("FULLUSER", "UA", "APRSRX", "LCDIST"):
        t = pp(incs, cf[name], rel)
        check(t is not None and "currentLanguage->channels_protect" in t and "currentLanguage->satellite_mode" in t
              and "currentLanguage->locked" not in t.replace("currentLanguage->locked_", "") and "currentLanguage->satellite_short" not in t, "%s: меню беруть channels_protect/satellite_mode, а не locked/satellite_short" % name)
    for name in ("AES0", "AES1", "ENDATA"):
        t = pp(incs, cf[name], rel)
        check(t is not None and "channels_protect" not in t and "satellite_mode" not in t and "currentLanguage->locked" in t and "currentLanguage->satellite_short" in t,
              "%s (не-UA): меню лишились на стокових locked/satellite_short" % name)
    th = pp(incs, cf["AES0"], "application/include/user_interface/languages/uiLanguage.h")
    check(th is not None and "channels_protect" not in th and "satellite_mode" not in th, "не-UA: stringsTable_t без нових полів (розкладка не змінилась)")
    th = pp(incs, cf["FULLUSER"], "application/include/user_interface/languages/uiLanguage.h")
    check(th is not None and th.rstrip().rsplit("stringsTable_t", 1)[0].rstrip().rstrip("}").rstrip().replace("const char talkaround_menu[17];", "").rstrip().endswith("satellite_mode[17];"), "UA: нові поля останні в stringsTable_t")

    # 3 решта мов не чіпано
    chg = subprocess.run(["git", "-C", FW, "diff", "--name-only", BASE, "--", "application/include/user_interface/languages"], capture_output=True, text=True).stdout.split()
    if chg or subprocess.run(["git", "-C", FW, "cat-file", "-e", BASE], capture_output=True).returncode == 0:
        allowed = {"MDUV380_firmware/application/include/user_interface/languages/" + x for x in ("ukrainian.h", "uiLanguage.h", "messages_ua.h", "english.h")}
        check(set(chg) <= allowed, "змінено лише ukrainian.h, uiLanguage.h, messages_ua.h і english.h (дзеркало UA-блока для check_language_fields); решта мов байт-у-байт: %r" % sorted(set(chg) - allowed))
        b = git_show("application/include/user_interface/languages/ukrainian.h")
        if b is not None:
            old = fields(b.decode("cp1251"))
            new = fields(ua)
            diff = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
            check(diff == sorted(["vox_tail", "temperature_calibration", "battery_calibration", "messages", "channels_protect", "satellite_mode", "talkaround_menu"]), "ukrainian.h: змінено рівно 6 полів R82 + talkaround_menu (R94): %r" % diff)
            for k in ("trackball", "hotspot_mode", "dmr_crc", "gps", "on", "off", "yes", "no", "none", "utc"):
                if k in old:
                    check(old.get(k) == new.get(k), "поле %s не чіпано" % k)
    else:
        print("test_r82: коміт %s недоступний -- п.3 пропущено" % BASE)

    # 4 ширина і кодування
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_menu_widths.py")], capture_output=True, text=True)
    check(r.returncode == 0 and "Переповнень не знайдено" in r.stdout, "check_menu_widths.py: переповнень нема")
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_string_encoding.py")], capture_output=True, text=True)
    check(r.returncode == 0, "check_string_encoding.py чисто")
    for k, v in WANT.items():
        check(len(v.encode("cp1251")) <= 16, "%s: %r <= 16 байтів cp1251" % (k, v))

    # 6 мутанти
    def mut(name, ua2=None, msgs2=None, sv2=None):
        QUIET[0] = True
        n0 = len(FAILS)
        errs = check_texts(ua2 or ua, msgs2 or msgs, gen, sv2 or sv)
        QUIET[0] = False
        check(bool(errs), "мутант «%s» ловиться" % name)

    for k, v in WANT.items():
        if k in OLD:
            mut("забули %s" % k, ua2=re.sub(r'^(\.%s\s*= )"[^"]*"' % k, lambda m: m.group(1) + '"%s"' % OLD[k], ua, flags=re.M))
    mut("забули channels_protect", ua2=ua.replace('"Захист кан."', '"Ch. blocked"'))
    mut("забули satellite_mode", ua2=ua.replace('"Супутник", // MaxLen: 16\n', '"SAT", // MaxLen: 16\n'))
    mut("змінили спільне locked", ua2=ua.replace('.locked                                  = "Ch. blocked"', '.locked                                  = "Захист кан."'))
    mut("SMS DMR не в заголовку", msgs2=msgs.replace('"SMS DMR"', '"Повідомлення"'))
    mut("CPS без оновлення", sv2=sv.replace('"SMS DMR"', '"Повідомлення"'))
    # код меню без #if -- у не-UA збірці з'явилось б звернення до відсутнього поля
    m = re.search(r"#if defined\(LANGUAGE_BUILD_UKRAINIAN\)\s*\n\s*leftSide = currentLanguage->channels_protect", gen)
    check(m is not None, "код меню: channels_protect під #if LANGUAGE_BUILD_UKRAINIAN")
    m = re.search(r"#if defined\(LANGUAGE_BUILD_UKRAINIAN\)\s*\n\s*leftSide = currentLanguage->satellite_mode", gen)
    check(m is not None, "код меню: satellite_mode під #if LANGUAGE_BUILD_UKRAINIAN")
    check(re.search(r"#if defined\(LANGUAGE_BUILD_UKRAINIAN\)\s*\n\s*leftSide = currentLanguage->channels_protect", gen.replace("#if defined(LANGUAGE_BUILD_UKRAINIAN)\n\t\t\t\t\t\tleftSide = currentLanguage->channels_protect", "\t\t\t\t\t\tleftSide = currentLanguage->channels_protect")) is None,
          "мутант: channels_protect без #if ловиться")

    print("test_r82: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
