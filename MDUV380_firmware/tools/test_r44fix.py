#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R44-fix (оновлено в R46): HardFault при відкритті меню «Кодплаг» (strlen(0x1DC69F44) у menuDisplayEntry). R46 розформував «Кодплаг» -- тепер сторожовий приклад той самий механізм
на єдиному форковому меню за межею швидких клавіш, «Канали» (MENU_CODEPLUG_CHANNELS): якщо його запис у data[] знову стане позиційним, data[] стане коротшим за enum.

Причина (код, а не мовні рядки): `menuDataGlobal.data[]` -- масив ЗМІННОЇ довжини, що ініціалізується ПОЗИЦІЙНО, а в enum MENU_SCREENS перед MENU_CODEPLUG стоять шість
меню без таблиць (AES_KEYS, MESSAGES, RCTL_REMOTE, RCTL_CONFIG, CALL_REPLAY, APRS_HUB), для яких NULL-заглушок у data[] нема. `&menuDataCodeplug` лягало на позицію 40,
а MENU_CODEPLUG = 46 -> data[46] читалось за межами масиву -> сміттєві items/numItems -> сміттєвий stringOffset -> strlen(сміття).

Z0  розбір: tools/check_menu_tables.py на поточному дереві проходить; на позиційному записі (як у R44) ПАДАЄ і називає data[] коротшим за enum; на справжньому menuSystem.c з коміту R44 теж падає;
Z1  мутанти menuSystem.c (позиційний запис, зсув на 1, нема явного індексу, чужа таблиця, пропущений елемент menuFunctions[], не та функція) -- усі падають;
Z2  виконання на хості: menuSystem.c зі збірки R44 скомпільовано, data[] має рівно NUM_MENU_ENTRIES елементів (довжину дає `nm -S`), data[MENU_CODEPLUG_CHANNELS] == NULL, таблиці головного меню / контактів /
    Options на своїх місцях; на позиційному записі -- data[] коротший за enum;
Z3  мовні поля: check_language_fields.py проходить на дереві (в т.ч. на R44 -- мовні рядки не були причиною) і ловить підкладені вади (бракує ініціалізатора, порядок,
    зайвий ініціалізатор, інша умова #if, нове поле структури без значення);
Z4  збірка без розділу «Кодплаг» не змінилась: токени `gcc -E -P` menuSystem.c без ENABLE_CODEPLUG_MENU збігаються з R44 (git show dc1aedc), якщо є git-історія;
Z5  перевірки підключено до tests/run_tests.sh і до CI (build.yml).
Запуск: python3 tools/test_r44fix.py"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import check_language_fields as clf       # noqa: E402
import check_menu_tables as cmt           # noqa: E402

FAILS = []
SRC = os.path.join(FW, "application", "source", "user_interface", "menuSystem.c")
LANG = os.path.join(FW, "application", "include", "user_interface", "languages")
R44_BASE = os.environ.get("R44_BASE", "dc1aedc")

OLD_BLOCK = """#if defined(CODEPLUG_MENU_ENABLED)
				NULL,// R44-стиль: позиційний запис без явного індексу
#endif
"""


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def read(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def write(path, text):
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def new_block(src):
    """Поточний блок R44 у `.data` (з явними індексами)."""
    m = re.search(r"#if defined\(CODEPLUG_MENU_ENABLED\)\n\t\t\t\t/\* R44-fix:.*?\[MENU_CODEPLUG_CHANNELS\] = NULL,[^\n]*\n#endif\n", src, re.S)
    return m.group(0) if m else None


def make_root(menusystem_text):
    """Мінімальний «корінь» для check_menu_tables: усе -- символічні посилання на справжнє дерево, крім menuSystem.c, який підмінено."""
    root = tempfile.mkdtemp(prefix="r44fix_")
    for name in os.listdir(FW):
        if name == "application":
            continue
        os.symlink(os.path.join(FW, name), os.path.join(root, name))
    app = os.path.join(root, "application")
    os.makedirs(os.path.join(app, "source", "user_interface"))
    os.symlink(os.path.join(FW, "application", "include"), os.path.join(app, "include"))
    write(os.path.join(app, "source", "user_interface", "menuSystem.c"), menusystem_text)
    return root


def run_tables(root, only=None):
    """-> (код, вивід) check_menu_tables.py на корені."""
    cmd = [sys.executable, os.path.join(HERE, "check_menu_tables.py"), "--root", root, "--quiet"]
    if only:
        cmd += ["--only", only]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ----------------------------------------------------------------------------------------------------------------------
#  Z0/Z1: таблиці меню
# ----------------------------------------------------------------------------------------------------------------------

def test_z0_z1_tables():
    src = read(SRC)
    blk = new_block(src)
    check(blk is not None, "Z0: у menuSystem.c є виправлений блок R44-fix з явними індексами")
    if blk is None:
        return
    check("[MENU_CODEPLUG_CHANNELS] = NULL" in blk, "Z0: явний індекс «Канали»")
    rc, out = run_tables(FW)
    check(rc == 0, "Z0: check_menu_tables проходить на виправленому дереві: %s" % out[-400:])

    # --- R44 до виправлення: старий блок на місці нового ---
    root = make_root(src.replace(blk, OLD_BLOCK))
    try:
        rc, out = run_tables(root)
        check(rc == 1, "Z0: check_menu_tables ПАДАЄ на коді R44 (старий блок): rc=%s" % rc)
        check("data[] має 41 елементів, а меню в enum -- 47" in out and "ЗА межами" in out, "Z0: називає вихід за межі масиву (41 проти 47): %s" % out[-500:])
        check("R44" in out.split("ПРОВАЛ")[-1], "Z0: називає конфігурацію R44")
        # інші конфігурації на тому самому коді -- лише R44 має меню «Канали» (решта без нього проходять)
        rc2, out2 = run_tables(root, "AES0,AES1,UA,CHDEL,R43,R44LITE,R44NODEL")
        check(rc2 == 0, "Z0: конфігурації без пунктів «Зона/Канали/Контакти» цей код не ламає: %s" % out2[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if os.path.isdir(os.path.join(os.path.dirname(FW), ".git")) or True:
        try:
            old = subprocess.run(["git", "-C", FW, "show", "%s:MDUV380_firmware/application/source/user_interface/menuSystem.c" % R44_BASE], capture_output=True)
            if old.returncode == 0:
                root = make_root(old.stdout.decode("utf-8"))
                try:
                    rc, out = run_tables(root)
                    check(rc == 1, "Z0: на справжньому menuSystem.c з коміту %s перевірка падає: %s" % (R44_BASE, out[-300:]))
                finally:
                    shutil.rmtree(root, ignore_errors=True)
            else:
                print("test_r44fix: коміт %s недоступний -- звірку на справжньому R44 пропущено (є підстановка старого блока вище)" % R44_BASE)
        except OSError:
            print("test_r44fix: git недоступний -- звірку на справжньому R44 пропущено")

    # --- мутанти ---
    mutants = [
        ("позиційні заглушки замість явних індексів (як було)", lambda s: s.replace(blk, OLD_BLOCK)),
        ("індекс зсунуто на 1", lambda s: s.replace("[MENU_CODEPLUG_CHANNELS] = NULL", "[MENU_CODEPLUG_CHANNELS - 1] = NULL")),
        ("нема явного індексу (масив коротший за enum)", lambda s: s.replace("\t\t\t\t[MENU_CODEPLUG_CHANNELS] = NULL,// R46: головне меню -> «Канали»\n", "")),
        ("чужа таблиця в data[]", lambda s: s.replace("[MENU_CODEPLUG_CHANNELS] = NULL", "[MENU_CODEPLUG_CHANNELS] = &menuDataContact")),
        ("пропущено елемент menuFunctions[] (меню APRS)", lambda s: s.replace("\t\t{ menuAprsHub,              NULL, NULL, 0 },// R8-fix: меню «APRS»\n", "")),
        ("не та функція на MENU_CODEPLUG_CHANNELS", lambda s: s.replace("{ menuCodeplugChannels,     NULL, NULL, 0 }", "{ menuZoneList,             NULL, NULL, 0 }")),
        ("зайвий елемент menuFunctions[] посеред", lambda s: s.replace("\t\t{ menuZoneList,             NULL, NULL, 0 },\n", "\t\t{ menuZoneList,             NULL, NULL, 0 },\n\t\t{ menuZoneList,             NULL, NULL, 0 },\n", 1)),
        ("MENU_OPTIONS: таблиця Options підмінена на головну", lambda s: s.replace("&menuDataOptions,// Options", "&menuDataMainMenu,// Options")),
    ]
    for name, fn in mutants:
        mutated = fn(src)
        check(mutated != src, "Z1: мутант «%s» справді змінює файл" % name)
        root = make_root(mutated)
        try:
            rc, out = run_tables(root, "R44,UA,AES1,APRSRX")
            check(rc == 1, "Z1: мутант «%s» не спійманий (rc=%s): %s" % (name, rc, out[-200:]))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    print("test_r44fix: мутантів таблиць меню перевірено %d" % len(mutants))


# ----------------------------------------------------------------------------------------------------------------------
#  Z2: виконання на хості
# ----------------------------------------------------------------------------------------------------------------------

PROBE = r'''
#include <stdio.h>
#include <stddef.h>
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
int main(void)
{
	printf("off=%d ptr=%d num=%d\n", (int)offsetof(menuDataGlobal_t, data), (int)sizeof(void *), (int)NUM_MENU_ENTRIES);
	printf("main=%d contact=%d options=%d\n", menuDataGlobal.data[MENU_MAIN_MENU] == &menuDataMainMenu, menuDataGlobal.data[MENU_CONTACTS_MENU] == &menuDataContact,
	       menuDataGlobal.data[MENU_OPTIONS] == &menuDataOptions);
	printf("tail=%d\n", (menuDataGlobal.data[MENU_CODEPLUG_CHANNELS] == NULL) ? 1 : 0);
	return 0;
}
'''


def run_probe(menusystem_text, tmp):
    """Компілює menuSystem.c (конфігурація R44) і зонд, що читає data[MENU_CODEPLUG]. -> dict або None, якщо компілятора нема."""
    if not shutil.which("gcc"):
        return None
    incs, cfgs = cmt.load_configs(FW)
    defs = dict(cfgs)["R44"]
    src_path = os.path.join(tmp, "menuSystem.c")
    probe_path = os.path.join(tmp, "probe.c")
    write(src_path, menusystem_text)
    write(probe_path, PROBE)
    obj, exe = os.path.join(tmp, "ms.o"), os.path.join(tmp, "probe")
    # -I на каталог з підміненим файлом не потрібен: усі #include в ньому -- з application/include
    r = subprocess.run(["gcc", "-std=gnu11", "-w", "-no-pie", "-c"] + incs + defs + [src_path, "-o", obj], cwd=FW, capture_output=True, text=True)
    check(r.returncode == 0, "Z2: menuSystem.c (R44) компілюється на хості: %s" % r.stderr[-300:])
    if r.returncode != 0:
        return {}
    r = subprocess.run(["gcc", "-std=gnu11", "-w", "-no-pie"] + incs + defs + [probe_path, obj, "-o", exe, "-Wl,--unresolved-symbols=ignore-all"], cwd=FW, capture_output=True, text=True)
    check(r.returncode == 0, "Z2: зонд злінковано: %s" % r.stderr[-300:])
    if r.returncode != 0:
        return {}
    out = subprocess.run([exe], capture_output=True, text=True).stdout
    res = dict(re.findall(r"(\w+)=(-?\d+)", out))
    # довжина data[] -- з розміру символа menuDataGlobal в об'єкті: (розмір - зсув поля data) / розмір вказівника
    nm = subprocess.run(["nm", "-S", obj], capture_output=True, text=True).stdout
    m = re.search(r"^\w+\s+(\w+)\s+[dD]\s+menuDataGlobal$", nm, re.M)
    if m and "off" in res and "ptr" in res:
        res["datalen"] = str((int(m.group(1), 16) - int(res["off"])) // int(res["ptr"]))
    return res


def test_z2_runtime():
    src = read(SRC)
    blk = new_block(src)
    tmp = tempfile.mkdtemp(prefix="r44fix_rt_")
    try:
        res = run_probe(src, tmp)
        if res is None:
            print("test_r44fix: gcc нема -- розділ Z2 пропущено")
            return
        check(res.get("datalen") is not None and res.get("datalen") == res.get("num"), "Z2: data[] має рівно NUM_MENU_ENTRIES елементів: %r" % res)
        check(res.get("main") == "1" and res.get("contact") == "1" and res.get("options") == "1", "Z2: таблиці головного меню / контактів / Options на своїх місцях: %r" % res)
        check(res.get("tail") == "1", "Z2: data[MENU_CODEPLUG_CHANNELS] читається в межах масиву і дорівнює NULL (а не сміття): %r" % res)
        # на позиційному записі data[] коротший за enum
        old = run_probe(src.replace(blk, OLD_BLOCK), tmp)
        check(old and old.get("datalen") is not None and old.get("datalen") != old.get("num"), "Z2: на позиційному записі data[] коротший за enum (вада відтворена): %r" % (old,))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------------------------------------------------
#  Z3: мовні поля
# ----------------------------------------------------------------------------------------------------------------------

def lang_root(edit=None):
    """Тимчасовий корінь лише з languages/*.h; `edit` -- {ім'я файла: функція(текст)->текст}. Файли в cp1251 читаються як latin-1 (байти не втрачаються)."""
    root = tempfile.mkdtemp(prefix="r44fix_lang_")
    dst = os.path.join(root, clf.LANG_REL)
    os.makedirs(dst)
    for fn in os.listdir(LANG):
        p = os.path.join(LANG, fn)
        if os.path.isfile(p) and fn.endswith(".h"):
            with open(p, "rb") as f:
                data = f.read()
            if edit and fn in edit:
                data = edit[fn](data.decode("latin-1")).encode("latin-1")
            with open(os.path.join(dst, fn), "wb") as f:
                f.write(data)
    return root


def run_lang(root):
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_language_fields.py"), "--root", root, "--quiet"], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def line_of(text, field):
    m = re.search(r"^\.%s\s*=.*\n" % re.escape(field), text, re.M)
    return m


def test_z3_language():
    rc, out = run_lang(FW)
    check(rc == 0, "Z3: check_language_fields проходить на дереві: %s" % out[-400:])
    # R44 (старий блок) -- мовні файли ті самі: перевірка мусить проходити (мовні рядки причиною НЕ були)
    old_ok = True
    try:
        for fn in ("ukrainian.h", "english.h", "uiLanguage.h"):
            r = subprocess.run(["git", "-C", FW, "show", "%s:MDUV380_firmware/application/include/user_interface/languages/%s" % (R44_BASE, fn)], capture_output=True)
            if r.returncode != 0:
                old_ok = False
                break
        if old_ok:
            root = tempfile.mkdtemp(prefix="r44fix_langold_")
            dst = os.path.join(root, clf.LANG_REL)
            shutil.copytree(LANG, dst)
            for fn in ("ukrainian.h", "english.h", "uiLanguage.h"):
                r = subprocess.run(["git", "-C", FW, "show", "%s:MDUV380_firmware/application/include/user_interface/languages/%s" % (R44_BASE, fn)], capture_output=True)
                with open(os.path.join(dst, fn), "wb") as f:
                    f.write(r.stdout)
            rc, out = run_lang(root)
            check(rc == 0, "Z3: на мовних файлах коміту R44 перевірка мовних полів ПРОХОДИТЬ (рядки не були причиною HardFault): %s" % out[-300:])
            shutil.rmtree(root, ignore_errors=True)
    except OSError:
        pass

    def caught(name, edit, want):
        root = lang_root(edit)
        try:
            rc, out = run_lang(root)
            check(rc == 1, "Z3: вада «%s» не спіймана (rc=%s): %s" % (name, rc, out[-200:]))
            for w in want:
                check(w in out, "Z3: вада «%s»: у виводі нема «%s»: %s" % (name, w, out[-400:]))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    # 1. у ukrainian.h бракує ініціалізатора останнього поля розділу «Кодплаг»
    caught("нема ініціалізатора cp_set_zone", {"ukrainian.h": lambda t: t.replace(line_of(t, "cp_set_zone").group(0), "")}, ["cp_set_zone", "ukrainian.h", "ПОЛЕ БЕЗ ЗНАЧЕННЯ"])
    # 2. два сусідні ініціалізатори переставлено
    def swap(t):
        a, b = line_of(t, "cp_edit").group(0), line_of(t, "cp_delete").group(0)
        return t.replace(a + b, b + a)
    caught("переставлено cp_edit і cp_delete", {"ukrainian.h": swap}, ["ПОРЯДОК", "ukrainian.h"])
    # 3. зайвий ініціалізатор, якого нема в структурі
    caught("зайвий ініціалізатор", {"english.h": lambda t: t.replace(line_of(t, "cp_becomes_none").group(0), line_of(t, "cp_becomes_none").group(0) + '.cp_unknown = "x",\n')}, ["ЗАЙВИЙ ІНІЦІАЛІЗАТОР", "cp_unknown"])
    # 4. поле під іншою умовою #if, ніж у структурі: ініціалізатор винесено з #if ENABLE_CODEPLUG_MENU
    def other_if(t):
        m = line_of(t, "cp_channels")
        head = t[:m.start()]
        i = head.rindex("#if defined(ENABLE_CODEPLUG_MENU)")
        return head[:i] + head[i:].replace("#if defined(ENABLE_CODEPLUG_MENU)", "#if defined(ENABLE_ZONE_EDIT)", 1) + t[m.start():]
    caught("інша умова #if у файлі", {"ukrainian.h": other_if}, ["ukrainian.h"])
    # 5. нове поле структури без значень у файлах
    caught("нове поле структури без значення", {"uiLanguage.h": lambda t: t.replace("   const char cp_becomes_none[LANGUAGE_TEXTS_LENGTH];\n", "   const char cp_becomes_none[LANGUAGE_TEXTS_LENGTH];\n   const char cp_new_field[LANGUAGE_TEXTS_LENGTH];\n")},
           ["cp_new_field", "ПОЛЕ БЕЗ ЗНАЧЕННЯ"])
    # 6. нове поле вставлено НЕ в кінець структури (посеред) -- файли мають те саме поле, але в іншому місці
    def mid(t):
        return t.replace("   const char menu[LANGUAGE_TEXTS_LENGTH];// Menu number  1\n", "   const char menu[LANGUAGE_TEXTS_LENGTH];// Menu number  1\n   const char cp_mid[LANGUAGE_TEXTS_LENGTH];\n")
    caught("поле вставлено посеред структури", {"uiLanguage.h": mid}, ["cp_mid"])
    # 7. дубль ініціалізатора
    caught("дубль ініціалізатора", {"ukrainian.h": lambda t: t.replace(line_of(t, "cp_edit").group(0), line_of(t, "cp_edit").group(0) * 2)}, ["ДУБЛЬ"])
    # 8. стокова мова втратила поле, яке НЕ в списку відомих прогалин
    caught("стокова мова без поля", {"german.h": lambda t: t.replace(line_of(t, "battery").group(0), "")}, ["german.h", "battery"])
    print("test_r44fix: мовних вад підкладено 8, усі спіймані")
    # R46: розформований розділ не лишив слідів у мовній структурі
    ui = open(os.path.join(LANG, "uiLanguage.h"), "rb").read().decode("latin-1")
    check("codeplug_menu" not in ui and "cp_set_zone" in ui, "Z3: поле codeplug_menu прибрано, cp_set_zone додано останнім у блоці R44/R46")


# ----------------------------------------------------------------------------------------------------------------------
#  Z4/Z5
# ----------------------------------------------------------------------------------------------------------------------

def tokens(root, defs, incs):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + ["application/source/user_interface/menuSystem.c"], cwd=root, capture_output=True, text=True)
    return r.stdout.split() if r.returncode == 0 else None


def test_z4_default_unchanged():
    if not shutil.which("gcc") or not shutil.which("git"):
        print("test_r44fix: нема gcc/git -- Z4 пропущено")
        return
    old = subprocess.run(["git", "-C", FW, "show", "%s:MDUV380_firmware/application/source/user_interface/menuSystem.c" % R44_BASE], capture_output=True)
    if old.returncode != 0:
        print("test_r44fix: коміт %s недоступний -- Z4 пропущено" % R44_BASE)
        return
    incs, cfgs = cmt.load_configs(FW)
    root = make_root(old.stdout.decode("utf-8"))
    try:
        for name, defs in cfgs:
            if name in ("R44", "ROAM", "AESNAMES", "ROAMAESNAMES", "RXG", "FULLUSER", "SATTONE"):
                continue                       # конфігурації з ENABLE_CODEPLUG_MENU -- саме їх R46 і змінює (ROAM = R44 + ENABLE_ROAM_RETRY; R64: AESNAMES/ROAMAESNAMES -- похідні від R44; R65: RXG/FULLUSER додають пункт «Списки прийому»; R66D: SATTONE = R44 + прапорець супутника)
            # R59: ENABLE_ROAM_RETRY законно додає останній пункт меню; без цього прапорця токени мусять збігатися з базою, тож порівнюємо без нього
            a, b = tokens(FW, [d for d in defs if d != "-DENABLE_ROAM_RETRY"], incs), tokens(root, [d for d in defs if d != "-DENABLE_ROAM_RETRY"], incs)
            check(a is not None and a == b, "Z4: конфігурація %s -- токени menuSystem.c не змінились відносно R44" % name)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_z5_wiring():
    rt = read(os.path.join(FW, "tests", "run_tests.sh"))
    check("check_language_fields.py" in rt and "check_menu_tables.py" in rt, "Z5: обидві перевірки підключено до tests/run_tests.sh")
    check("test_r44fix" in rt, "Z5: test_r44fix.py підключено до tests/run_tests.sh")
    wf = os.path.join(os.path.dirname(FW), ".github", "workflows", "build.yml")
    if os.path.isfile(wf):
        y = read(wf)
        check("check_language_fields.py" in y and "check_menu_tables.py" in y, "Z5: обидві перевірки підключено до CI (build.yml)")
        check(y.index("check_language_fields.py") < y.index("run_tests.sh"), "Z5: у CI перевірки йдуть до хостових тестів")


def main():
    test_z0_z1_tables()
    test_z2_runtime()
    test_z3_language()
    test_z4_default_unchanged()
    test_z5_wiring()
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        sys.exit(1)
    print("test_r44fix: усе гаразд")


if __name__ == "__main__":
    main()
