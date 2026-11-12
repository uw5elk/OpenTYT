#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R94-Б (хост): GPS у меню української збірки приховано; ефективний режим GPS = Off.
  1  gcc -E (усі MDUV380-конфігурації CI): у menuGeneralOptions.c нема GENERAL_OPTIONS_GPS, у menuSystem.c нема MENU_GPS у головному меню, GENERAL_CHANNELS_ARE_READ_ONLY і далі на тих самих номерах (перелік без GPS);
  2  макрос SETTINGS_GPS_MODE_EFFECTIVE (settings.h) компілюється gcc: UA+FORK_NO_GPS_MENU -> завжди GPS_MODE_OFF для будь-якого збереженого значення; не-UA -> як SETTINGS_GPS_MODE_GET;
  3  споживачі (значок GPS у шапці, відстань, копіювання координат) беруть ефективний режим в UA і стоковий у не-UA (gcc -E);
  4  збережений біт не переписується: у джерелах нема settingsSet(...gpsModeAndBaudsIndex...) у нових місцях; gps.c/usb_com.c/uiHotspot.c не змінено відносно бази;
  5  мутанти. Запуск: python3 tools/test_r94b.py"""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); FW = os.path.dirname(HERE); sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa
APP = os.path.join(FW, "application"); UI = "application/source/user_interface/"
BASE = os.environ.get("R94B_BASE", "accf134")
FAILS = []; N = [0]
def check(c, m):
    N[0] += 1
    if not c: FAILS.append(m); print("ПРОВАЛ: " + m)
def pp(incs, defs, rel):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=FW, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
def macro_eval(ua, vals):
    sh = open(os.path.join(APP, "include/functions/settings.h"), encoding="utf-8").read()
    i = sh.index("#define SETTINGS_GPS_MODE_GET"); j = sh.index("#endif", sh.index("SETTINGS_GPS_MODE_EFFECTIVE(x) SETTINGS_GPS_MODE_GET"))
    body = sh[i:j]
    src = "#include <stdio.h>\n#include <stdint.h>\n#define HAS_GPS 1\n#define FORK_NO_GPS_MENU 1\n" + ("#define LANGUAGE_BUILD_UKRAINIAN 1\n" if ua else "") + \
          "enum {GPS_NOT_DETECTED, GPS_MODE_OFF, GPS_MODE_ON, GPS_MODE_ON_NMEA, GPS_MODE_ON_LOG};\ntypedef struct { uint8_t gpsModeAndBaudsIndex; } S;\n" + body + "#endif\nint main(void){ S s;\n"
    for v in vals: src += "s.gpsModeAndBaudsIndex=%d; printf(\"%%d\\n\", (int)SETTINGS_GPS_MODE_EFFECTIVE(s));\n" % v
    src += "return 0;}\n"
    d = tempfile.mkdtemp(); c = os.path.join(d, "t.c"); open(c, "w").write(src)
    r = subprocess.run(["gcc", "-w", "-o", os.path.join(d, "t"), c], capture_output=True)
    if r.returncode: return None
    return [int(x) for x in subprocess.run([os.path.join(d, "t")], capture_output=True, text=True).stdout.split()]
def main():
    incs, cfgs = cmt.load_configs(FW); cf = dict(cfgs)
    for n in ("FULLUSER", "UA", "APRSRX", "LCDIST", "AES0", "AES1", "ENDATA"):
        t = pp(incs, cf[n], UI + "menuGeneralOptions.c")
        check(t is not None and not re.search(r"\bGENERAL_OPTIONS_GPS\b", t), n + ": пункту «Загальні опції -> GPS» нема")
        t = pp(incs, cf[n], UI + "menuSystem.c")
        check(t is not None and not re.search(r"\bMENU_GPS\s*\}", t), n + ": у головному меню нема GPS")
    vals = [0, 1, 2, 3, 4, 0x12, 0x2A]
    ua = macro_eval(True, vals); non = macro_eval(False, vals)
    check(ua == [1] * len(vals), "UA: ефективний режим = Off (%r)" % ua)
    check(non == [v & 0x0F for v in vals], "не-UA: як SETTINGS_GPS_MODE_GET (%r)" % non)
    for n in ("FULLUSER", "UA"):
        t = pp(incs, cf[n], UI + "uiUtilities.c")
        check(t is not None and "(uint8_t)GPS_MODE_OFF) >= GPS_MODE_ON" in t, n + ": значок GPS у шапці бере ефективний режим")
        t = pp(incs, cf[n], UI + "uiChannelMode.c")
        check(t is not None and t.count("(uint8_t)GPS_MODE_OFF)") >= 4, n + ": uiChannelMode.c: відстань бере ефективний режим")
        t = pp(incs, cf[n], UI + "menuChannelDetails.c")
        check(t is not None and "(uint8_t)GPS_MODE_OFF) >= GPS_MODE_ON" in t, n + ": menuChannelDetails.c: копіювання координат")
    for n in ("AES0", "AES1"):
        t = pp(incs, cf[n], UI + "uiUtilities.c")
        check(t is not None and "(uint8_t)GPS_MODE_OFF" not in t and "gpsModeAndBaudsIndex & 0x0F) >= GPS_MODE_ON" in t, n + " (не-UA): значок як у стоку")
    for f in ("application/source/interfaces/gps.c", "application/source/usb/usb_com.c", UI + "uiHotspot.c", UI + "menuGPS.c"):
        r = subprocess.run(["git", "-C", FW, "diff", "--quiet", BASE, "--", f]); 
        check(r.returncode == 0, f + " не змінено")
    # мутант: макрос без UA-гілки
    sh = open(os.path.join(APP, "include/functions/settings.h"), encoding="utf-8").read()
    check("#define SETTINGS_GPS_MODE_EFFECTIVE(x) SETTINGS_GPS_MODE_GET(x)" in sh and "(uint8_t)GPS_MODE_OFF" in sh, "settings.h: обидві гілки макроса")
    print("test_r94b: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0])); return 1 if FAILS else 0
if __name__ == "__main__": sys.exit(main())
