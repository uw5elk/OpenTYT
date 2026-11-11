#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R46: розділ «Кодплаг» розформовано -- «Зона», «Канали», «Контакти» стали пунктами головного меню.

W1  склад головного меню (препроцесор `gcc -E -P`, конфігурація R44 з ENABLE_CODEPLUG_MENU): «Зона» (MENU_ZONE_LIST), «Канали», «Контакти» -- по одному разу й саме в цьому порядку (R47: «Канал» звідти прибрано);
    «Кодплагу» в enum і в меню нема; у конфігураціях без ENABLE_CODEPLUG_MENU -- стокові пункти без «Каналів»;
W2  підписи пунктів з мовної таблиці (cp1251): «Зона», «Канали», «Контакти»; підпис «Встановити» (cp_set_zone) є, останній у блоці R44/R46;
W3  швидкі клавіші: усі пункти головного меню, крім «Каналів», мають ID <= 31 (QuickKey -- 5 біт); «Канали» -- єдиний виняток, і код не дає прив'язати до нього швидку клавішу;
W4  SK2+колесо (selectPrevNextZone) не залежить від меню «Зона»: тіло функції не звертається до MENU_ZONE_LIST/menuZoneList/ZL_*;
W5  збірка БЕЗ ENABLE_CODEPLUG_MENU не змінилась: токени `gcc -E -P` змінених файлів у кожній конфігурації без прапорця збігаються з базою R46 (git; якщо бази нема -- пропущено);
W6  підключено до tests/run_tests.sh.
Запуск: python3 tools/test_r46.py"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import check_menu_tables as cmt           # noqa: E402

FAILS = []
UI = os.path.join(FW, "application", "source", "user_interface")
LANG = os.path.join(FW, "application", "include", "user_interface", "languages")
R46_BASE = os.environ.get("R46_BASE", "11850ce")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def read(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def main_menu(src):
    """-> список ID-імен меню з mainMenuItems[] препроцесованого menuSystem.c."""
    m = re.search(r"mainMenuItems\s*\[\s*\]\s*=\s*\{", src)
    if not m:
        raise ValueError("mainMenuItems[] не знайдено")
    end = cmt._balanced(src, m.end() - 1, "{", "}")
    names = []
    for item in cmt._split_top(src[m.end():end]):
        mm = re.search(r",\s*(\w+)\s*\}\s*$", item)
        names.append(mm.group(1) if mm else item)
    return names


def cfg_main_menu(name):
    incs, cfgs = cmt.load_configs(FW)
    defs = dict(cfgs)[name]
    src = cmt.preprocess(FW, incs, defs)
    return main_menu(src), cmt.parse_enum(src)


def test_w1_menu_composition():
    if not shutil.which("gcc"):
        print("test_r46: gcc нема -- W1 пропущено")
        return
    names, enum = cfg_main_menu("R44")
    want = ["MENU_ZONE_LIST", "MENU_CODEPLUG_CHANNELS", "MENU_CONTACTS_MENU"]   # R47: «Канал» (MENU_CHANNEL_DETAILS) з цього меню прибрано
    check(names[:3] == want and "MENU_CHANNEL_DETAILS" not in names, "W1: початок головного меню (R44) = %r, має бути %r і без MENU_CHANNEL_DETAILS" % (names[:3], want))
    for n in ("MENU_ZONE_LIST", "MENU_CODEPLUG_CHANNELS", "MENU_CONTACTS_MENU"):
        check(names.count(n) == 1, "W1: пункт %s у головному меню рівно один раз (є %d)" % (n, names.count(n)))
    check("MENU_CODEPLUG" not in enum and "MENU_CODEPLUG_ZONES" not in enum, "W1: у enum MENU_SCREENS нема MENU_CODEPLUG / MENU_CODEPLUG_ZONES")
    check(list(enum).index("MENU_CODEPLUG_CHANNELS") == list(enum).index("NUM_MENU_ENTRIES") - 1, "W1: MENU_CODEPLUG_CHANNELS -- останній перед NUM_MENU_ENTRIES")
    # конфігурації без прапорця: стокові три пункти, без «Каналів»
    for cfg in ("UA", "R44NODEL", "R44LITE"):
        n2, e2 = cfg_main_menu(cfg)
        check(n2[:3] == ["MENU_ZONE_LIST", "MENU_CONTACTS_MENU", "MENU_CHANNEL_DETAILS"] and "MENU_CODEPLUG_CHANNELS" not in n2 and "MENU_CODEPLUG_CHANNELS" not in e2,
              "W1: конфігурація %s (без меню «Канали») -- стокові пункти: %r" % (cfg, n2[:4]))


def lang_fields():
    t = open(os.path.join(LANG, "uiLanguage.h"), "rb").read().decode("latin-1")
    return re.findall(r"const char (\w+)\[LANGUAGE_TEXTS_LENGTH\]", t)


def lang_value(fn, field):
    t = open(os.path.join(LANG, fn), "rb").read().decode("cp1251", errors="replace")
    m = re.search(r'^\.%s\s*=\s*"([^"]*)"' % re.escape(field), t, re.M)
    return m.group(1) if m else None


def test_w2_labels():
    f = lang_fields()
    check(f[3] == "zone" and f[6] == "contacts", "W2: рядки 3 і 6 мовної таблиці -- zone і contacts (стокові пункти «Зона» / «Контакти»): %r %r" % (f[3], f[6]))
    check(lang_value("ukrainian.h", "zone") == "Зона" and lang_value("ukrainian.h", "contacts") == "Контакти", "W2: «Зона» / «Контакти» в ukrainian.h")
    check(lang_value("ukrainian.h", "cp_channels") == "Канали", "W2: «Канали» в ukrainian.h")
    check(lang_value("ukrainian.h", "cp_set_zone") == "Встановити", "W2: «Встановити» в ukrainian.h")
    check(lang_value("english.h", "cp_set_zone") is not None, "W2: cp_set_zone є в english.h")
    blk = f[f.index("cp_channels"):]
    check(blk[-1] == "cp_set_zone" and "codeplug_menu" not in f, "W2: cp_set_zone -- останнє поле структури; codeplug_menu прибрано: хвіст %r" % blk[-3:])
    for fld in ("cp_rename", "cp_zone_chans", "cp_delete"):
        check(lang_value("ukrainian.h", fld) is not None, "W2: поле дії %s є" % fld)


def test_w3_quickkeys():
    if not shutil.which("gcc"):
        return
    names, enum = cfg_main_menu("R44")
    high = [n for n in names if enum.get(n, 0) > 31]
    check(high == ["MENU_CODEPLUG_CHANNELS"], "W3: у головному меню (R44) лише «Канали» має ID > 31; є: %r" % high)
    disp = read(os.path.join(UI, "menuDisplayMenuList.c"))
    check(re.search(r"#if defined\(CODEPLUG_MENU_ENABLED\)( \|\| defined\(ENABLE_ROAM_RETRY\))?[^\n]*\n[^#]*?menuNum <= 31\)\)\s*\n#else\s*\n\s*if \(menuDataGlobal\.currentMenuList\[menuDataGlobal\.currentItemIndex\]\.menuNum != -1\)\s*\n#endif", disp, re.S) is not None,
          "W3: SK2+цифра на пункті з ID > 31 відсікається під CODEPLUG_MENU_ENABLED (R59: або ENABLE_ROAM_RETRY), стокова гілка без змін")


def test_w4_wheel_independent():
    ucm = read(os.path.join(UI, "uiChannelMode.c"))
    m = re.search(r"static void selectPrevNextZone\(bool nextZone\)\n\{.*?\n\}\n", ucm, re.S)
    check(m is not None, "W4: selectPrevNextZone знайдено")
    if m:
        body = m.group(0)
        check(not re.search(r"MENU_ZONE_LIST|menuZoneList|ZL_EDIT|zeSetActive|s_zoneMap", body), "W4: SK2+колесо (selectPrevNextZone) не торкається меню «Зона»")
        check("codeplugZoneStep" in body, "W4: перемикання йде через codeplugZoneStep")
    # і навпаки: вибір зони в меню не змінює кроків колеса -- codeplugZoneStep/zoneStepUsable не згадують menuZoneList
    check("menuZoneList" not in ucm and "MENU_ZONE_LIST" not in ucm, "W4: uiChannelMode.c узагалі не залежить від екрана зон")


FILES = ["menuSystem.c", "menuZoneList.c", "menuDisplayMenuList.c", "menuCodeplug.c", "menuContactList.c", "menuContactDetails.c", "uiChannelMode.c"]


def tokens_of(root, rel, incs, defs):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=root, capture_output=True)   # байти: мовні файли в cp1251
    return r.stdout.split() if r.returncode == 0 else None


def test_w5_default_unchanged():
    if not shutil.which("gcc") or not shutil.which("git"):
        print("test_r46: нема gcc/git -- W5 пропущено")
        return
    chk = subprocess.run(["git", "-C", FW, "cat-file", "-e", R46_BASE + "^{commit}"], capture_output=True)
    if chk.returncode != 0:
        print("test_r46: коміт бази %s недоступний -- W5 пропущено (задай R46_BASE)" % R46_BASE)
        return
    import tempfile
    incs, cfgs = cmt.load_configs(FW)
    root = tempfile.mkdtemp(prefix="r46_base_")
    try:
        # база: увесь application/ з коміту (include + source) -- щоб порівнювати і заголовки
        tar = subprocess.run(["git", "-C", FW, "archive", R46_BASE, "application"], capture_output=True)
        if tar.returncode != 0:
            print("test_r46: git archive не вдався -- W5 пропущено")
            return
        subprocess.run(["tar", "-x", "-C", root], input=tar.stdout, check=True)
        for entry in os.listdir(FW):           # решта дерева (драйвери, SDK) -- посиланнями: -I у конфігураціях відносні
            if entry != "application" and not os.path.exists(os.path.join(root, entry)):
                os.symlink(os.path.join(FW, entry), os.path.join(root, entry))
        n = 0
        for name, defs in cfgs:
            if "-DENABLE_CODEPLUG_MENU" in defs:
                continue
            for fn in FILES:
                if fn == "menuZoneList.c" and "-DENABLE_ZONE_RENAME" in defs:
                    continue       # R64: редактор імені винесено в uiNameEditor.c -- токени файла законно інші; еквівалентність доводить tools/test_r64_editor.py (диф-тест 51 тис. кроків)
                if fn == "uiChannelMode.c":
                    continue       # R74: стоковий «Roaming» приховано безумовно на платформі форку (HAS_GPS+FORK_NO_GPS_MENU) -- токени законно інші; еквівалентність доводить tools/test_r74.py (C-стенд quickMenuVisibleItem)
                rel = os.path.join("application", "source", "user_interface", fn)
                # R59: ENABLE_ROAM_RETRY законно додає пункт меню; без цього прапорця токени мусять збігатися з базою, тож своє дерево рахуємо без нього
                a, b = tokens_of(FW, rel, incs, [d for d in defs if d not in ("-DENABLE_ROAM_RETRY", "-DENABLE_VOLUME_PROBE", "-DENABLE_VOLUME_LOW", "-DENABLE_TA_DIAG")]), tokens_of(root, rel, incs, [d for d in defs if d not in ("-DENABLE_VOLUME_PROBE", "-DENABLE_VOLUME_LOW")])
                if a is None and b is None:
                    continue       # файл не збирається в цій конфігурації однаково в обох (напр. нема потрібних прапорців)
                n += 1
                check(a is not None and a == b, "W5: конфігурація %s, %s -- токени без ENABLE_CODEPLUG_MENU змінились відносно %s" % (name, fn, R46_BASE))
        check(n > 0, "W5: порівняно хоч одну пару файл/конфігурація")
        print("test_r46: W5 -- порівняно %d пар (конфігурація, файл) без ENABLE_CODEPLUG_MENU" % n)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_w6_wiring():
    rt = read(os.path.join(FW, "tests", "run_tests.sh"))
    check("test_r46" in rt, "W6: test_r46.py підключено до tests/run_tests.sh")


def main():
    test_w1_menu_composition()
    test_w2_labels()
    test_w3_quickkeys()
    test_w4_wheel_independent()
    test_w5_default_unchanged()
    test_w6_wiring()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r46: усе гаразд")


if __name__ == "__main__":
    main()
