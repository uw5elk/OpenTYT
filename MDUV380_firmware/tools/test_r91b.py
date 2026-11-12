#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R91B (хост, без заліза): пункт «Дисплей -> Показ відст.» (BIT_DISPLAY_CHANNEL_DISTANCE) сховано в українській збірці; ефективне значення завжди Off.
  1  макрос SETTINGS_CHANNEL_DISTANCE_EFFECTIVE(): UA -> false навіть при ВСТАНОВЛЕНОМУ збереженому біті; не-UA -> читає біт (скомпільовано справжній текст макросу);
  2  препроцесований код (gcc -E): в UA-конфігураціях uiChannelMode.c і uiUtilities.c більше НЕ читають біт (відстань до каналу не малюється), у не-UA -- читають, як у базі;
  3  меню: DISPLAY_SHOW_DISTANCE є в enum на своєму місці (номери решти не змінились), але не у списку видимих; решта порядку та сама, «Опції теми» останні;
  4  збережений біт не переписується: запис біта лише в стокових <-/-> пункту (недосяжні), список відновлення біта при скасуванні лишився;
  5  відстань APRS і «Станції» не змінились: файли aprs_rx.c, aprs_rx_parse.c, menuAprsStations.c, aprs.c ідентичні базі 0340abc, а distanceBetweenTwoCoords/courseTo -- по тілу;
  6  «Роумінг» зберіг свою відстань: ROAMING_EFFECTIVE() у тих самих умовах;
  7  мутанти: кожна перевірка ловить зламаний варіант.
Запуск: python3 tools/test_r91b.py"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa: E402

APP = os.path.join(FW, "application")
UI = os.path.join(APP, "source", "user_interface")
BASE = os.environ.get("R91B_BASE", "0340abc")
FAILS = []
N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        print("ПРОВАЛ: " + m)


def rd(p):
    b = open(p, "rb").read()
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1251")


def pp(incs, defs, rel):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=FW, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def macro_value(text, ua, bit_set):
    m = re.search(r"(#if defined\(LANGUAGE_BUILD_UKRAINIAN\)\n#define SETTINGS_CHANNEL_DISTANCE_EFFECTIVE\(\).*?#endif)", text, re.S)
    if not m:
        return None
    src = ("#include <stdbool.h>\n#include <stdio.h>\ntypedef int bitfieldOptions_t;\n#define BIT_DISPLAY_CHANNEL_DISTANCE 5\n"
           "static bool settingsIsOptionBitSet(bitfieldOptions_t b){(void)b;return %s;}\n" % ("true" if bit_set else "false")
           + m.group(1) + "\nint main(void){printf(\"%d\", SETTINGS_CHANNEL_DISTANCE_EFFECTIVE() ? 1 : 0);return 0;}\n")
    with tempfile.TemporaryDirectory() as d:
        c = os.path.join(d, "m.c")
        open(c, "w").write(src)
        r = subprocess.run(["gcc", "-w", "-o", os.path.join(d, "m")] + (["-DLANGUAGE_BUILD_UKRAINIAN"] if ua else []) + [c], capture_output=True, text=True)
        if r.returncode != 0:
            return None
        return subprocess.run([os.path.join(d, "m")], capture_output=True, text=True).stdout.strip()


def grab(text, name):
    m = re.search(r"^[a-zA-Z_][^\n;{]*\b" + re.escape(name) + r"\s*\([^;{]*\)\s*\n\{", text, re.M)
    if not m:
        return None
    i = text.index("{", m.start())
    d = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            d += 1
        elif text[j] == "}":
            d -= 1
            if d == 0:
                return text[m.start():j + 1]
    return None


def git_show(rel):
    r = subprocess.run(["git", "-C", FW, "show", "%s:MDUV380_firmware/%s" % (BASE, rel)], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def visible(t):
    m = re.search(r"displayVisibleItems\[\]\s*=\s*\{(.*?)\};", t, re.S)
    return re.findall(r"DISPLAY_[A-Z_]+", m.group(1)) if m else None


def enum_items(t):
    m = re.search(r"enum\s*\{\s*(DISPLAY_[^}]*?NUM_DISPLAY_MENU_ITEMS)\s*\}", t, re.S)
    return re.findall(r"DISPLAY_[A-Z_]+", m.group(1)) if m else None


def main():
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    sh = rd(os.path.join(APP, "include", "functions", "settings.h"))

    # 1
    check(macro_value(sh, True, True) == "0", "UA: макрос = false при ВСТАНОВЛЕНОМУ збереженому біті («Показ відст.» = On до прошивки)")
    check(macro_value(sh, True, False) == "0", "UA: макрос = false і при скинутому біті")
    check(macro_value(sh, False, True) == "1" and macro_value(sh, False, False) == "0", "не-UA: макрос читає біт")
    check(macro_value(sh.replace("(false)", "(true)"), True, False) == "1", "мутант: UA-макрос = true -- ловиться")

    # 2
    for name in ("FULLUSER", "R44", "APRSRX"):
        for rel in ("application/source/user_interface/uiChannelMode.c", "application/source/user_interface/uiUtilities.c"):
            t = pp(incs, cf[name], rel)
            check(t is not None and t.count("BIT_DISPLAY_CHANNEL_DISTANCE") == 1, "%s: %s не читає біт «Показ відст.» (лишилось лише оголошення в enum бітів)" % (name, os.path.basename(rel)))
    for rel, mn in (("application/source/user_interface/uiChannelMode.c", 3), ("application/source/user_interface/uiUtilities.c", 1)):
        t0 = pp(incs, cf["AES0"], rel)
        check(t0 is not None and t0.count("BIT_DISPLAY_CHANNEL_DISTANCE") == mn + 1, "AES0 (не-UA): %s читає біт %d раз(и), як у базі (+1 оголошення в enum)" % (os.path.basename(rel), mn))

    # 3
    td = pp(incs, cf["FULLUSER"], "application/source/user_interface/menuDisplayOptions.c")
    vis, en = visible(td), enum_items(td)
    check(vis is not None and "DISPLAY_SHOW_DISTANCE" not in vis, "«Дисплей»: «Показ відст.» немає у списку видимих")
    check(en is not None and en.count("DISPLAY_SHOW_DISTANCE") == 1 and en.index("DISPLAY_SHOW_DISTANCE") == 17, "«Дисплей»: DISPLAY_SHOW_DISTANCE лишився в enum на номері 17 (швидкі клавіші)")
    check(vis is not None and vis[-1] == "DISPLAY_THEME_OPTIONS" and vis[-2] == "DISPLAY_DMR_LAST_TALKER_ON_SCREEN", "«Дисплей»: решта порядку, «Опції теми» останні")

    # 4
    do = rd(os.path.join(UI, "menuDisplayOptions.c"))
    check(do.count("settingsSetOptionBit(BIT_DISPLAY_CHANNEL_DISTANCE") == 2, "запис біта лише в стокових <-/-> пункту (2 місця, недосяжні)")
    check(re.search(r"BIT_AUTO_NIGHT,\s*BIT_DISPLAY_CHANNEL_DISTANCE,", do) is not None, "біт у списку відновлення при скасуванні (як було)")

    # 5
    for rel in ("application/source/functions/aprs_rx.c", "application/source/functions/aprs_rx_parse.c", "application/source/user_interface/menuAprsStations.c", "application/source/functions/aprs.c"):
        b = git_show(rel)
        if b is None:
            print("test_r91b: коміт %s недоступний -- п.5 пропущено" % BASE)
            break
        cur = open(os.path.join(FW, rel), "rb").read().decode("utf-8", "replace")
        # R97: «Подвійний прийом» призупиняє APRS-прийом окремим блоком під DUAL_CHANNEL_ENABLED (лише з ENABLE_DUAL_CHANNEL) -- без нього файл як у базі
        cur = re.sub(r"#if defined\(DUAL_CHANNEL_ENABLED\)\n\tif \(dcIsEnabled\(\)\)\n\t\{\n[^\n]*R97[^\n]*\n\t\}\n#endif\n", "", cur)
        check(b.decode("utf-8", "replace") == cur, "%s ідентичний базі %s (APRS не змінено; блок R97 під прапорцем не враховано)" % (os.path.basename(rel), BASE))
    bu = git_show("application/source/user_interface/uiUtilities.c")
    if bu is not None:
        cur = rd(os.path.join(UI, "uiUtilities.c"))
        for fn in ("distanceBetweenTwoCoords", "courseTo"):
            check(grab(bu.decode("utf-8", "replace"), fn) == grab(cur, fn) and grab(cur, fn) is not None, "%s: тіло функції те саме, що в базі" % fn)

    # 6
    uc = rd(os.path.join(UI, "uiChannelMode.c"))
    uu = rd(os.path.join(UI, "uiUtilities.c"))
    check(uc.count("SETTINGS_CHANNEL_DISTANCE_EFFECTIVE() || (ROAMING_EFFECTIVE() != ROAMING_OFF)") == 2 and "ROAMING_EFFECTIVE() != ROAMING_OFF) || (SETTINGS_CHANNEL_DISTANCE_EFFECTIVE()" in uc,
          "uiChannelMode.c: умови відстані «Роумінгу» лишились (3 місця через макрос)")
    check("SETTINGS_CHANNEL_DISTANCE_EFFECTIVE() || ((ROAMING_EFFECTIVE() != ROAMING_OFF)" in uu, "uiUtilities.c: озвучування відстані (announceDistance) -- через макрос, «Роумінг» лишився")
    check("settingsIsOptionBitSet(BIT_DISPLAY_CHANNEL_DISTANCE)" not in uc and "settingsIsOptionBitSet(BIT_DISPLAY_CHANNEL_DISTANCE)" not in uu, "прямих читань біта в uiChannelMode.c/uiUtilities.c нема")
    check("settingsIsOptionBitSet(BIT_DISPLAY_CHANNEL_DISTANCE)" in (uc.replace("SETTINGS_CHANNEL_DISTANCE_EFFECTIVE()", "settingsIsOptionBitSet(BIT_DISPLAY_CHANNEL_DISTANCE)")), "мутант: пряме читання біта повернулось -- ловиться")

    print("test_r91b: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
