#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R47: з головного меню прибрано зайвий пункт «Канал» (MENU_CHANNEL_DETAILS; у мовній таблиці `channel_details`, в українській збірці -- «Канал»), під ENABLE_CODEPLUG_MENU.

V1  склад головного меню (препроцесор `gcc -E -P`, конфігурація R44 з ENABLE_CODEPLUG_MENU): MENU_CHANNEL_DETAILS нема; решта пунктів і їхній порядок -- як у базі R46 (git; якщо бази нема -- лише початок «Зона, Канали, Контакти»);
V2  конфігурації БЕЗ ENABLE_CODEPLUG_MENU: пункт на місці (третій після «Зона» і «Контакти»), токени menuSystem.c збігаються з базою R46;
V3  екран не загубився: MENU_CHANNEL_DETAILS лишився в enum, у menuFunctions[] (функція menuChannelDetails -- check_menu_tables.py), і досяжний: «Канали» -> «Змінити» (ccEdit),
    SK2+зелена на екрані каналів і на екрані VFO;
V4  швидкі клавіші: ID MENU_CHANNEL_DETAILS <= 31 (QuickKey -- 5 біт); applicationMain.c відкриває меню за ID зі швидкої клавіші, а не за позицією в списку головного меню;
    нову прив'язку з головного меню зробити вже не можна (menuDisplayMenuList.c бере меню з виділеного пункту списку);
V5  мутанти (текст menuSystem.c): пункт повернули безумовно / прибрали зовсім / поставили під протилежну умову -- перевірка ловить кожного;
V6  підключено до tests/run_tests.sh.
Запуск: python3 tools/test_r47.py    (база для V1/V2: змінна R47_BASE, типово 315f6da)"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import check_menu_tables as cmt           # noqa: E402
import test_r46 as t46                    # noqa: E402

FAILS = []
UI = os.path.join(FW, "application", "source", "user_interface")
R47_BASE = os.environ.get("R47_BASE", "315f6da")
ITEM = "MENU_CHANNEL_DETAILS"

# Очікувана форма пункту в menuSystem.c: після «Контакти» -- ПІД `#if !defined(CODEPLUG_MENU_ENABLED)` (з коментарем), далі #endif
ITEM_RE = re.compile(r"\{\s*6,\s*MENU_CONTACTS_MENU\s*\},\s*\n#if !defined\(CODEPLUG_MENU_ENABLED\)\n(?:\s*//[^\n]*\n)*\s*\{\s*12,\s*MENU_CHANNEL_DETAILS\s*\},\s*\n#endif")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def read(*parts):
    with open(os.path.join(*parts), "rb") as f:
        return f.read().decode("utf-8")


def base_tree():
    """Розпакувати application/ бази у тимчасовий каталог (решта дерева -- посиланнями). -> каталог або None."""
    if not shutil.which("git"):
        return None
    if subprocess.run(["git", "-C", FW, "cat-file", "-e", R47_BASE + "^{commit}"], capture_output=True).returncode != 0:
        return None
    root = tempfile.mkdtemp(prefix="r47_base_")
    tar = subprocess.run(["git", "-C", FW, "archive", R47_BASE, "application"], capture_output=True)
    if tar.returncode != 0:
        shutil.rmtree(root, ignore_errors=True)
        return None
    subprocess.run(["tar", "-x", "-C", root], input=tar.stdout, check=True)
    for entry in os.listdir(FW):
        if entry != "application" and not os.path.exists(os.path.join(root, entry)):
            os.symlink(os.path.join(FW, entry), os.path.join(root, entry))
    return root


def tokens_of(root, rel, incs, defs):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=root, capture_output=True)
    return r.stdout.split() if r.returncode == 0 else None


def test_v1_v2_composition(base):
    if not shutil.which("gcc"):
        print("test_r47: gcc нема -- V1/V2 пропущено")
        return
    incs, cfgs = cmt.load_configs(FW)
    d = dict(cfgs)
    names, enum = t46.cfg_main_menu("R44")
    check(ITEM not in names, "V1: у головному меню (R44, з ENABLE_CODEPLUG_MENU) нема %s; є: %r" % (ITEM, names))
    check(names[:3] == ["MENU_ZONE_LIST", "MENU_CODEPLUG_CHANNELS", "MENU_CONTACTS_MENU"], "V1: початок меню: %r" % names[:3])
    check(ITEM in enum, "V1: %s лишився в enum MENU_SCREENS (екран існує)" % ITEM)
    if base:
        b = cmt.preprocess(base, incs, d["R44"])
        bnames = t46.main_menu(b)
        check(bnames.count(ITEM) == 1, "V1: у базі %s рівно один раз (сам тест має сенс)" % ITEM)
        check([n for n in bnames if n != ITEM] == names, "V1: решта пунктів і порядок -- як у базі: нині %r, база без пункту %r" % (names, [n for n in bnames if n != ITEM]))
    else:
        print("test_r47: бази %s нема -- порівняння решти пунктів з базою пропущено" % R47_BASE)
    flagless = 0
    for name, defs in cfgs:
        if "-DENABLE_CODEPLUG_MENU" in defs:
            continue
        n2, _e2 = t46.cfg_main_menu(name)
        flagless += 1
        check(n2[:3] == ["MENU_ZONE_LIST", "MENU_CONTACTS_MENU", ITEM], "V2: конфігурація %s (без ENABLE_CODEPLUG_MENU) -- стокові пункти: %r" % (name, n2[:3]))
        if base:
            rel = os.path.join("application", "source", "user_interface", "menuSystem.c")
            # R59: ENABLE_ROAM_RETRY законно додає пункт меню; без цього прапорця токени мусять збігатися з базою, тож своє дерево рахуємо без нього
            a, bb = tokens_of(FW, rel, incs, [d for d in defs if d not in ("-DENABLE_ROAM_RETRY", "-DENABLE_VOLUME_PROBE")]), tokens_of(base, rel, incs, [d for d in defs if d != "-DENABLE_VOLUME_PROBE"])
            check(a is not None and a == bb, "V2: конфігурація %s -- токени menuSystem.c без ENABLE_CODEPLUG_MENU змінились відносно %s" % (name, R47_BASE))
    check(flagless > 0, "V2: перевірено хоч одну конфігурацію без прапорця")
    print("test_r47: V2 -- конфігурацій без ENABLE_CODEPLUG_MENU: %d" % flagless)


def test_v3_reachable():
    cp = read(UI, "menuCodeplug.c")
    m = re.search(r"static void ccEdit\(void\)\n\{.*?\n\}\n", cp, re.S)
    check(m is not None and ("menuSystemPushNewMenu(%s)" % ITEM) in m.group(0), "V3: «Канали» -> «Змінити» (ccEdit) відкриває %s" % ITEM)
    check(len(re.findall(r"\bccEdit\b", cp)) >= 2, "V3: ccEdit підключено до дій «Каналів» (не лише оголошено)")
    for fn in ("uiChannelMode.c", "uiVFOMode.c"):
        t = read(UI, fn)
        check(re.search(r"BUTTON_SK2\)\)\s*\n\s*\{\s*\n\s*menuSystemPushNewMenu\(%s\);" % ITEM, t) is not None, "V3: SK2+зелена в %s відкриває %s" % (fn, ITEM))
    sysc = read(UI, "menuSystem.c")
    check("&menuChannelDetails" in sysc or "menuChannelDetails" in sysc, "V3: menuChannelDetails лишилась у menuFunctions[]")


def test_v4_quickkeys():
    if shutil.which("gcc"):
        _n, enum = t46.cfg_main_menu("R44")
        check(0 < enum.get(ITEM, 99) <= 31, "V4: ID %s = %r вміщується в 5 біт QuickKey (збережені швидкі клавіші лишаються чинними)" % (ITEM, enum.get(ITEM)))
    am = read(FW, "application", "source", "applicationMain.c")
    check("int menuFunction = QUICKKEY_MENUID(keyFunction);" in am and "menuSystemPushNewMenu(menuFunction);" in am,
          "V4: швидка клавіша відкриває меню за ID (QUICKKEY_MENUID -> menuSystemPushNewMenu), а не за позицією в mainMenuItems[]")
    dl = read(UI, "menuDisplayMenuList.c")
    check("saveQuickkeyMenuIndex(ev->keys.key, menuDataGlobal.currentMenuList[menuDataGlobal.currentItemIndex].menuNum, 0, 0);" in dl,
          "V4: нова прив'язка SK2+цифра береться з виділеного пункту списку -- прибраного пункту в списку нема, тож на нього нову клавішу не призначити")


def mutants(text):
    """-> [(опис, змінений текст)] для menuSystem.c."""
    m = ITEM_RE.search(text)
    if not m:
        return []
    block = m.group(0)
    item_line = re.search(r"\{\s*12,\s*MENU_CHANNEL_DETAILS\s*\},", block).group(0)
    contacts = re.match(r"\{\s*6,\s*MENU_CONTACTS_MENU\s*\},", block).group(0)
    return [
        ("пункт повернули безумовно (прапорець не прибирає)", text.replace(block, contacts + "\n\t" + item_line)),
        ("пункт прибрано зовсім (зникає і в збірках без прапорця)", text.replace(block, contacts)),
        ("умова навпаки (пункт лишився лише з прапорцем)", text.replace(block, block.replace("#if !defined(CODEPLUG_MENU_ENABLED)", "#if defined(CODEPLUG_MENU_ENABLED)"))),
        ("«Контакти» зникли разом з «Каналом»", text.replace(block, "#if !defined(CODEPLUG_MENU_ENABLED)\n\t" + item_line + "\n#endif")),
    ]


def test_v5_mutants():
    src = read(UI, "menuSystem.c")
    check(ITEM_RE.search(src) is not None, "V5: пункт стоїть у menuSystem.c у очікуваній формі (під #if !defined(CODEPLUG_MENU_ENABLED))")
    ms = mutants(src)
    check(len(ms) == 4, "V5: зібрано 4 мутанти (шаблон знайдено)")
    for desc, txt in ms:
        check(txt != src, "V5: мутант «%s» справді змінює текст" % desc)
        check(ITEM_RE.search(txt) is None, "V5: мутант «%s» НЕ піймано перевіркою форми" % desc)


def test_v6_wiring():
    rt = read(FW, "tests", "run_tests.sh")
    check("test_r47" in rt, "V6: test_r47.py підключено до tests/run_tests.sh")


def main():
    base = base_tree()
    try:
        test_v1_v2_composition(base)
    finally:
        if base:
            shutil.rmtree(base, ignore_errors=True)
    test_v3_reachable()
    test_v4_quickkeys()
    test_v5_mutants()
    test_v6_wiring()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r47: усе гаразд")


if __name__ == "__main__":
    main()
