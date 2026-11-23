#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R91A (хост, без заліза): переноси меню української збірки. Перевіряє ПРЕПРОЦЕСОВАНИЙ код (gcc -E) і вихідні тексти; екрани малюються лише на залізі.
  1  головне меню: «Про прошивку» (MENU_FIRMWARE_INFO) у UA-конфігураціях сховано, порядок решти -- як до R91A; у НЕ-UA конфігураціях таблиці без змін;
  2  «Налаштування»: MENU_FIRMWARE_INFO -- ОСТАННІЙ пункт, MENU_THEME прибрано, порядок решти -- як до R91A (UA); НЕ-UA без змін;
  3  «Дисплей»: enum -- старі пункти на тих самих номерах (швидкі клавіші), DISPLAY_THEME_OPTIONS -- ПІСЛЯ них; у списку видимих «Гучності» нема, «Опції теми» останні;
  4  «Гучність» завжди On: макрос SETTINGS_VISUAL_VOLUME_EFFECTIVE() = true (UA) / біт (не-UA), єдине читання BIT_VISUAL_VOLUME у applicationMain.c йде через нього;
     збережений біт не переписується (меню його не змінює: пункт не видно);
  5  «Опції теми» у «Дисплеї»: вхід вправо -> menuSystemPushNewMenu(MENU_THEME); назад з «Теми» і «Про прошивку» -- menuSystemPopPreviousMenu (стек: повертає туди, звідки відкрили);
  6  спливаюче вікно «Затр.шуму» (sql_open_delay_hint1..3) прибрано (пункт існує лише в UA збірці: SQL_OPEN_DELAY_ENABLED); поля stringsTable_t на місці;
  7  мутанти: кожна перевірка має ловити зламаний варіант.
ДАНІ: «старі» списки (до R91A) -- з виводу gcc -E бази 0340abc (R88), зафіксовані константами нижче; це не синтетика, а виміряний стан бази.
Запуск: python3 tools/test_r91a.py"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa: E402

UI = os.path.join(FW, "application", "source", "user_interface")
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


def pp(incs, defs, src):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [src], cwd=FW, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def table(t, name):
    m = re.search(name + r"\[\]\s*=\s*\{(.*?)\};", t, re.S)
    return re.findall(r"MENU_[A-Z0-9_]+", m.group(1)) if m else None


# --- стан бази 0340abc (виміряно gcc -E) ---------------------------------------------------------------------------------------------
OLD_MAIN_UA = ['MENU_ZONE_LIST', 'MENU_CODEPLUG_CHANNELS', 'MENU_CONTACTS_MENU', 'MENU_FIRMWARE_INFO', 'MENU_OPTIONS', 'MENU_LAST_HEARD', 'MENU_RADIO_INFOS', 'MENU_SATELLITE',
               'MENU_MESSAGES', 'MENU_APRS_HUB', 'MENU_RCTL_REMOTE']
OLD_OPT_UA = ['MENU_GENERAL', 'MENU_RADIO', 'MENU_DISPLAY', 'MENU_SOUND', 'MENU_CALIBRATION', 'MENU_THEME', 'MENU_AES_KEYS', 'MENU_RCTL_CONFIG']
OLD_MAIN_NONUA = ['MENU_ZONE_LIST', 'MENU_CONTACTS_MENU', 'MENU_CHANNEL_DETAILS', 'MENU_RSSI_SCREEN', 'MENU_FIRMWARE_INFO', 'MENU_OPTIONS', 'MENU_LAST_HEARD',
                  'MENU_RADIO_INFOS', 'MENU_SATELLITE']
OLD_OPT_NONUA = ['MENU_GENERAL', 'MENU_RADIO', 'MENU_DISPLAY', 'MENU_SOUND', 'MENU_LANGUAGE', 'MENU_CALIBRATION', 'MENU_THEME', 'MENU_APRS']
OLD_DISPLAY_ENUM = ['DISPLAY_TYPE_STYLE', 'DISPLAY_MENU_BRIGHTNESS', 'DISPLAY_MENU_BRIGHTNESS_NIGHT', 'DISPLAY_MENU_BRIGHTNESS_OFF', 'DISPLAY_MENU_BACKLIGHT_MODE',
                    'DISPLAY_MENU_TIMEOUT', 'DISPLAY_MENU_SCREEN_INVERT', 'DISPLAY_AUTO_NIGHT', 'DISPLAY_MENU_CONTACT_DISPLAY_ORDER',
                    'DISPLAY_MENU_CONTACT_DISPLAY_SPLIT_CONTACT', 'DISPLAY_TIME_IN_HEADER', 'DISPLAY_BATTERY_UNIT_IN_HEADER', 'DISPLAY_EXTENDED_INFOS',
                    'DISPLAY_VISUAL_VOLUME', 'DISPLAY_ALL_LEDS_ENABLED', 'DISPLAY_TIMEZONE_VALUE', 'DISPLAY_TIME_UTC_OR_LOCAL', 'DISPLAY_SHOW_DISTANCE',
                    'DISPLAY_DMR_LAST_TALKER_ON_SCREEN']


def good_ua_main(new, old=OLD_MAIN_UA):
    exp = [x for x in old if x != "MENU_FIRMWARE_INFO"]
    extra = [x for x in new[len(exp):] if x not in ("MENU_ROAM", "MENU_RXGROUPS", "MENU_TONE_REPLY")]   # R59/R65B/R100 додають пункти в кінець
    return "MENU_FIRMWARE_INFO" not in new and new[:len(exp)] == exp and not extra


def good_ua_opt(new, old=OLD_OPT_UA):
    return new[-1:] == ["MENU_FIRMWARE_INFO"] and "MENU_THEME" not in new and new[:-1] == [x for x in old if x != "MENU_THEME"]


def display_enum(t):
    m = re.search(r"enum\s*\{\s*(DISPLAY_[^}]*?NUM_DISPLAY_MENU_ITEMS)\s*\}", t, re.S)
    return re.findall(r"DISPLAY_[A-Z_]+", m.group(1)) if m else None


def display_visible(t):
    m = re.search(r"displayVisibleItems\[\]\s*=\s*\{(.*?)\};", t, re.S)
    return re.findall(r"DISPLAY_[A-Z_]+", m.group(1)) if m else None


def good_enum(new):
    return new[:len(OLD_DISPLAY_ENUM)] == OLD_DISPLAY_ENUM and new[len(OLD_DISPLAY_ENUM):] == ["DISPLAY_THEME_OPTIONS"]


def good_visible(v):
    return "DISPLAY_VISUAL_VOLUME" not in v and v[-1:] == ["DISPLAY_THEME_OPTIONS"] and v.count("DISPLAY_THEME_OPTIONS") == 1


def macro_value(text, ua):
    """Збирає макрос з settings.h разом із заглушкою біта й повертає його значення при НЕвстановленому біті."""
    m = re.search(r"(#if defined\(LANGUAGE_BUILD_UKRAINIAN\)\n#define SETTINGS_VISUAL_VOLUME_EFFECTIVE\(\).*?#endif)", text, re.S)
    if not m:
        return None
    src = "#include <stdbool.h>\n#include <stdio.h>\ntypedef int bitfieldOptions_t;\n#define BIT_VISUAL_VOLUME 18\nstatic bool settingsIsOptionBitSet(bitfieldOptions_t b){(void)b;return false;}\n" \
          + m.group(1) + "\nint main(void){printf(\"%d\", SETTINGS_VISUAL_VOLUME_EFFECTIVE() ? 1 : 0);return 0;}\n"
    with tempfile.TemporaryDirectory() as d:
        c = os.path.join(d, "m.c")
        open(c, "w").write(src)
        r = subprocess.run(["gcc", "-w", "-o", os.path.join(d, "m")] + (["-DLANGUAGE_BUILD_UKRAINIAN"] if ua else []) + [c], capture_output=True, text=True)
        if r.returncode != 0:
            return None
        return subprocess.run([os.path.join(d, "m")], capture_output=True, text=True).stdout.strip()


def main():
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    ua_cfgs = [n for n, d in cfgs if any("LANGUAGE_BUILD_UKRAINIAN" in x for x in d)]
    check(len(ua_cfgs) >= 5, "є UA-конфігурації syntax_check.sh (%d)" % len(ua_cfgs))

    # 1, 2: таблиці меню
    for name in ("R44", "FULLUSER"):
        t = pp(incs, cf[name], "application/source/user_interface/menuSystem.c")
        check(t is not None, "%s: menuSystem.c препроцесується" % name)
        if t is None:
            continue
        main_l, opt_l = table(t, "mainMenuItems"), table(t, "optionsMenuItems")
        check(good_ua_main(main_l), "%s: «Про прошивку» зник з головного меню, решта -- у старому порядку" % name)
        check(good_ua_opt(opt_l), "%s: «Про прошивку» останній у «Налаштуваннях», «Опцій теми» там нема, решта -- у старому порядку" % name)
        check(main_l.index("MENU_OPTIONS") == OLD_MAIN_UA.index("MENU_OPTIONS") - 1, "%s: «Налаштування» стоять там само (мінус прибраний пункт)" % name)
        # мутанти
        check(not good_ua_main(main_l + ["MENU_FIRMWARE_INFO"]), "мутант: пункт лишився в головному меню -- ловиться")
        check(not good_ua_opt(opt_l[:-1]), "мутант: пункт не доданий у «Налаштування» -- ловиться")
        check(not good_ua_opt(["MENU_FIRMWARE_INFO"] + opt_l[:-1]), "мутант: пункт доданий НЕ останнім -- ловиться")
        check(not good_ua_opt(opt_l[:-1] + ["MENU_THEME", "MENU_FIRMWARE_INFO"]), "мутант: «Опції теми» лишились у «Налаштуваннях» -- ловиться")
    for name, old_m, old_o in (("AES0", OLD_MAIN_NONUA, OLD_OPT_NONUA),):
        t = pp(incs, cf[name], "application/source/user_interface/menuSystem.c")
        check(table(t, "mainMenuItems") == old_m and table(t, "optionsMenuItems") == old_o, "%s (не-UA): таблиці меню без змін" % name)

    # 3: «Дисплей»
    t = pp(incs, cf["FULLUSER"], "application/source/user_interface/menuDisplayOptions.c")
    check(t is not None, "FULLUSER: menuDisplayOptions.c препроцесується")
    if t:
        en, vis = display_enum(t), display_visible(t)
        check(en is not None and good_enum(en[:-1]), "«Дисплей»: старі пункти enum на тих самих номерах, «Опції теми» -- після них")
        check(vis is not None and good_visible(vis), "«Дисплей»: у списку видимих нема «Гучності», «Опції теми» -- останні")
        if vis:
            rest_old = [x for x in OLD_DISPLAY_ENUM if x not in ("DISPLAY_TYPE_STYLE", "DISPLAY_VISUAL_VOLUME")]
            # R91B потім ховає і «Показ відст.»: тест сумісний з обома станами (до і після R91B)
            check([x for x in vis[:-1] if x != "DISPLAY_SHOW_DISTANCE"] == [x for x in rest_old if x != "DISPLAY_SHOW_DISTANCE"],
                  "«Дисплей»: порядок решти видимих пунктів -- як у базі (мінус «Розмір тексту» R19 і «Гучність»)")
            check(not good_visible(vis + ["DISPLAY_VISUAL_VOLUME"]), "мутант: «Гучність» лишилась у списку -- ловиться")
            check(not good_visible(vis[:-1]), "мутант: нема «Опцій теми» -- ловиться")
        if en:
            check(not good_enum(["DISPLAY_THEME_OPTIONS"] + en[:-2]), "мутант: «Опції теми» вставлені НЕ в кінець enum -- ловиться")
    t0 = pp(incs, cf["AES0"], "application/source/user_interface/menuDisplayOptions.c")
    check(t0 is not None and "DISPLAY_THEME_OPTIONS" not in t0, "AES0 (не-UA): «Опцій теми» у «Дисплеї» нема")

    # 4: «Гучність» завжди On
    sh = rd(os.path.join(FW, "application", "include", "functions", "settings.h"))
    check(macro_value(sh, True) == "1", "UA: SETTINGS_VISUAL_VOLUME_EFFECTIVE() = true при НЕвстановленому збереженому біті")
    check(macro_value(sh, False) == "0", "не-UA: макрос читає біт (при невстановленому -- false)")
    check(macro_value(sh.replace("(true)", "(false)"), True) == "0", "мутант: макрос завжди false -- ловиться")
    am = rd(os.path.join(FW, "application", "source", "applicationMain.c"))
    check(am.count("SETTINGS_VISUAL_VOLUME_EFFECTIVE()") == 1 and "settingsIsOptionBitSet(BIT_VISUAL_VOLUME)" not in am, "applicationMain.c читає «Гучність» лише через макрос")
    reads = []
    for root, _d, files in os.walk(os.path.join(FW, "application", "source")):
        for f in files:
            if f.endswith(".c") and "BIT_VISUAL_VOLUME" in rd(os.path.join(root, f)):
                reads.append(f)
    check(sorted(reads) == ["menuDisplayOptions.c"], "BIT_VISUAL_VOLUME згадується лише в меню «Дисплей» (%s)" % ",".join(sorted(reads)))
    do = rd(os.path.join(UI, "menuDisplayOptions.c"))
    check("settingsSetOptionBit(BIT_VISUAL_VOLUME" in do and do.count("settingsSetOptionBit(BIT_VISUAL_VOLUME") == 2, "єдині записи біта -- стокові <-/-> пункту (недосяжні: пункт не видно)")

    # 5: вхід у «Опції теми» і навігація назад
    check(re.search(r"case DISPLAY_THEME_OPTIONS:\s*menuSystemPushNewMenu\(MENU_THEME\);\s*(/\*.*?\*/)?\s*return;", do) is not None, "вправо на «Опції теми» -> menuSystemPushNewMenu(MENU_THEME)")
    check(not re.search(r"case DISPLAY_THEME_OPTIONS:\s*menuSystemPushNewMenu\(MENU_THEME\);\s*(/\*.*?\*/)?\s*return;", do.replace("menuSystemPushNewMenu(MENU_THEME)", "menuSystemPushNewMenu(MENU_FIRMWARE_INFO)")), "мутант: вхід веде не в «Тему» -- ловиться")
    th = rd(os.path.join(UI, "menuThemeOptions.c"))
    fw = rd(os.path.join(UI, "menuFirmwareInfoScreen.c"))
    check("KEYCHECK_SHORTUP(ev->keys, KEY_RED)" in th and "menuSystemPopPreviousMenu()" in th, "«Тема»: червона = menuSystemPopPreviousMenu (повертає в «Дисплей»)")
    check("case KEY_RED:" in fw and "menuSystemPopPreviousMenu()" in fw, "«Про прошивку»: червона = menuSystemPopPreviousMenu (повертає в «Налаштування»)")
    check(not re.search(r"MENU_(OPTIONS|MAIN_MENU)", fw), "«Про прошивку» не прив'язана до головного меню (виходить стеком)")
    ms = rd(os.path.join(UI, "menuSystem.c"))
    check("{ menuThemeOptions,         NULL, NULL, 0 }" in ms and "{ menuFirmwareInfoScreen,   NULL, NULL, 0 }" in ms, "обидва екрани лишились у menuFunctions[] (швидкі клавіші на старі ID працюють)")

    # 6: спливаюче вікно «Затр.шуму»
    ts = pp(incs, cf["FULLUSER"], "application/source/user_interface/menuSoundOptions.c")
    check(ts is not None and "currentLanguage->sql_open_delay_hint" not in ts and "sqlOpenDelayPack" in ts, "UA: вікна-підказки «Затр.шуму» у коді нема, сам пункт на місці")
    check(ts is not None and "currentLanguage->sql_open_delay_hint" not in ts, "UA: жодного читання sql_open_delay_hint1..3 (вікно прибрано)")
    src = rd(os.path.join(UI, "menuSoundOptions.c"))
    check("sql_open_delay_hint" not in re.sub(r"/\*.*?\*/", "", src, flags=re.S) and "uiNotificationShow" not in src.split("OPTIONS_SQL_OPEN_DELAY:")[1].split("break;")[0],
          "menuSoundOptions.c: у пункті «Затр.шуму» нема виклику вікна")
    lang = rd(os.path.join(FW, "application", "include", "user_interface", "languages", "uiLanguage.h"))
    check(all(("sql_open_delay_hint%d" % i) in lang for i in (1, 2, 3)), "поля sql_open_delay_hint1..3 у stringsTable_t не видалено")

    print("test_r91a: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
