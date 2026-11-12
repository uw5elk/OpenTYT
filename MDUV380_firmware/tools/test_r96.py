#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R96 (хост): правки за польовою перевіркою R95.
  А1  «Кор.темп.» / «Кор. акум.»: підпис + найгірше динамічне значення <= 16 (check_menu_widths, розділ 3б; тут -- ще й арифметика старих підписів як «мутант»);
  А2  uiLockScreen.c: TIMEOUT_MS = 2000 в UA-збірці, 500 в інших (gcc -E);
  А3  menuAESKeys.c: UA -- «Ключ N:» + uiDrawTickMark, без «Key %d:%s»; не-UA -- «Key %d:%s»; галочка винесена з menuMessages.c;
  А4  роумінг: UA ROAM_PICK_ROW_FMT == «%u», ROAM_PICK_TITLE_FMT == «Список %u»; англійські -- «List %u» обидва;
  А5  швидкі клавіші: quickkeyIsEmpty() і диспетчер applicationMain.c скомпільовано хостовим gcc зі справжнього тексту (gcc -E) і прогнано на 0xFFFF, 0x8000, 0, контакті, меню;
      у не-UA збірці поведінка 0xFFFF стокова;
  А6  «Джерело».
Порівняння з комітом бази (R96_BASE) стійке до його відсутності: без коміта -- ПРОПУСК з повідомленням.
Запуск: python3 tools/test_r96.py"""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); FW = os.path.dirname(HERE); sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa
APP = os.path.join(FW, "application"); LANG = os.path.join(APP, "include", "user_interface", "languages"); SRC = "application/source/"
BASE = os.environ.get("R96_BASE", "6b85587")
FAILS = []; N = [0]
def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)
def rd(p, enc="utf-8"): return open(p, "rb").read().decode(enc)
def fields(t): return dict((m.group(1), m.group(2)) for m in re.finditer(r'^\.(\w+)\s*=\s*"([^"]*)"', t, re.M))
def pp(incs, defs, rel):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=FW, capture_output=True)
    return r.stdout.decode("cp1251", "replace") if r.returncode == 0 else None
def carve(t, start, end_marker):
    i = t.index(start); j = t.index(end_marker, i); return t[i:j + len(end_marker)]
def run_c(code):
    d = tempfile.mkdtemp(prefix="r96_", dir=os.path.expanduser("~"))
    c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
    r = subprocess.run(["gcc", "-std=gnu11", "-w", "-o", os.path.join(d, "h"), c], capture_output=True)
    if r.returncode != 0: print(r.stderr.decode()[:600]); return None
    return subprocess.run([os.path.join(d, "h")], capture_output=True).stdout.decode().split()
def main():
    ua = rd(os.path.join(LANG, "ukrainian.h"), "cp1251"); f = fields(ua)
    # А1 / А6
    check(f.get("temperature_calibration") == "Кор.темп." and f.get("battery_calibration") == "Кор. акум.", "А1: підписи «Кор.темп.» і «Кор. акум.»")
    check(len("Кор.темп.:+9.5°C") == 16 and len("Кор. акум.:+0.5V") == 16, "А1: арифметика 16 символів")
    check(len("Калібр. темп.:+9.5°C") > 16 and len("Калібр. акум.:+0.5V") > 16, "А1 (мутант): старі підписи не влізли б -- розділ 3б їх би зловив")
    r = subprocess.run([sys.executable, os.path.join(HERE, "check_menu_widths.py")], capture_output=True, text=True)
    check(r.returncode == 0 and "3б" in r.stdout and "Переповнень не знайдено" in r.stdout, "А1: check_menu_widths має розділ 3б і без переповнень")
    check("Кор.темп.:+9.5" in r.stdout and "Кор. акум.:+0.5V" in r.stdout, "А1: розділ 3б друкує найгірші значення")
    cw = rd(os.path.join(HERE, "check_menu_widths.py"))
    check("GENERAL_OPTIONS_MENU_TEMPERATURE_CALIBRATON" in cw and "GENERAL_OPTIONS_MENU_BATTERY_CALIBRATON" in cw, "А1: перевірка читає формати з menuGeneralOptions.c")
    check(f.get("priority_order") == "Джерело" and len("Джерело:КП/БД/TA") == 16, "А6: «Джерело» (+ «Джерело:КП/БД/TA» = 16)")
    check(f.get("auto_lock") == "Автоблок." and f.get("talker") == "Абонент", "спільні поля не зачеплено")
    incs, cfgs = cmt.load_configs(FW); cf = dict(cfgs)
    # А2
    for n, want in (("FULLUSER", "2000"), ("UA", "2000"), ("AES0", "500"), ("AES1", "500")):
        t = pp(incs, cf[n], SRC + "user_interface/uiLockScreen.c")
        m = re.search(r"TIMEOUT_MS\s*=\s*(\d+)", t or "")
        check(m and m.group(1) == want, "А2 %s: TIMEOUT_MS = %s (є %s)" % (n, want, m.group(1) if m else None))
    # А3
    for n in ("FULLUSER", "UA"):
        t = pp(incs, cf[n], SRC + "user_interface/menuAESKeys.c")
        if t is None: print("ПРОПУСК А3 %s: menuAESKeys.c не препроцесується в цій конфігурації" % n); continue
        check("uiDrawTickMark(" in t and "keyIsSet" in t and '"Key %d:%s"' not in t and "Ключ %d:" in t, "А3 %s: «Ключ %%d:» + галочка, без «Key %%d:%%s»" % n)
    t = pp(incs, cf["AES1"], SRC + "user_interface/menuAESKeys.c")
    check(t and '"Key %d:%s"' in t and "keyIsSet" not in t and "AESK_LIST_FMT" not in t, "А3 AES1 (не-UA): «Key %d:%s» як було, без галочки")
    mm = rd(os.path.join(APP, "source", "user_interface", "menuMessages.c"))
    check("uiDrawTickMark" in mm and "cy + 11 + k" not in mm, "А3: галочка в menuMessages.c -- виклик спільної uiDrawTickMark, копії нема")
    ak = rd(os.path.join(APP, "source", "user_interface", "menuAESKeys.c"))
    check("displayDrawLine" not in ak and "THEME_ITEM_FG_OPTIONS_VALUE" in ak.split("uiDrawTickMark(")[-1][:300], "А3: у menuAESKeys.c немає власного малювання, колір THEME_ITEM_FG_OPTIONS_VALUE")
    uu = rd(os.path.join(APP, "source", "user_interface", "uiUtilities.c"))
    check(uu.count("cx + 7), (int16_t)(cy + 5 + k)") == 1, "А3: одне тіло галочки (uiUtilities.c)")
    # А4
    d = tempfile.mkdtemp(prefix="r96_", dir=os.path.expanduser("~")); p = os.path.join(d, "roam.c")
    open(p, "w").write('#include "user_interface/roam_ui.h"\nROWFMT ROAM_PICK_ROW_FMT\nTTLFMT ROAM_PICK_TITLE_FMT\n')
    for n, row, ttl in (("FULLUSER", '"%u"', '"Список %u"'), ("AES1", '"List %u"', '"List %u"')):
        t = pp(incs, cf[n] + ([] if n == "FULLUSER" else ["-DENABLE_DMR_DATA", "-DENABLE_ROAM_RETRY"]), p) or ""
        check(("ROWFMT " + row) in t and ("TTLFMT " + ttl) in t, "А4 %s: ROAM_PICK_ROW_FMT=%s, ROAM_PICK_TITLE_FMT=%s" % (n, row, ttl))
    mr = rd(os.path.join(APP, "source", "user_interface", "menuRoam.c"))
    check(mr.count("pickRowText(buf, sizeof buf, s_roam.list, true)") == 2 and "(unsigned)(mNum + 1), false)" in mr, "А4: перелік -- голий формат, заголовок дій і підтвердження -- ROAM_PICK_TITLE_FMT")
    # А5
    for n, ukr in (("FULLUSER", True), ("UA", True), ("AES0", False), ("AES1", False)):
        cp = pp(incs, cf[n], SRC + "functions/codeplug.c")
        if cp is None: print("ПРОПУСК А5 %s: codeplug.c не препроцесується" % n); continue
        fn = carve(cp, "static _Bool quickkeyIsEmpty", "\n}\n")
        code = ("#include <stdio.h>\n#include <stdint.h>\n#include <stdbool.h>\nstatic uint16_t slot;\nuint16_t codeplugGetQuickkeyFunctionID(char k){(void)k;return slot;}\n" + fn +
                '\nint main(void){uint16_t s[]={0xFFFF,0x8000,0,5,0x8000|(7<<10),0x0400};for(int i=0;i<6;i++){slot=s[i];printf("%d ",quickkeyIsEmpty(\'1\',0x1234));}'
                'slot=0xFFFF;printf("%d",quickkeyIsEmpty(\'1\',0x8000));return 0;}\n')
        # CODEPLUG_CONTACTS_MIN/MAX вже розгорнуто препроцесором
        out = run_c(code)
        # 0xFFFF; 0x8000; 0; контакт 5 (зайнятий); меню (зайнятий); 0x0400 (контакт 1024: на межі)
        exp_ua = ["1", "1", "1", "0", "0", "0", "1"]; exp_st = ["0", "1", "1", "0", "0", "0", "1"]
        e = exp_ua if ukr else exp_st
        check(out is not None and out[:6] == e[:6] and out[6] == e[6], "А5 %s: quickkeyIsEmpty {0xFFFF,0x8000,0,контакт5,меню,0x400,clear}=%s (є %s)" % (n, e, out))
        am = pp(incs, cf[n], SRC + "applicationMain.c")
        if am is None: print("ПРОПУСК А5 %s: applicationMain.c не препроцесується" % n); continue
        blk = carve(am, "keyFunction = codeplugGetQuickkeyFunctionID(keys.key);", "int menuFunction = ((keyFunction>>10) & 0x1f);") if "int menuFunction = ((keyFunction>>10) & 0x1f);" in am else None
        if blk is None:
            m = re.search(r"keyFunction = codeplugGetQuickkeyFunctionID\(keys\.key\);.*?int menuFunction = [^;]*;", am, re.S); blk = m.group(0) if m else None
        check(blk is not None, "А5 %s: знайдено код диспетчера" % n)
        if blk:
            code = ("#include <stdio.h>\n#include <stdint.h>\nstatic uint16_t slot;\nuint16_t codeplugGetQuickkeyFunctionID(char k){(void)k;return slot;}\n"
                    "struct{char key;} keys={'1'};\nvoid disp(uint16_t s,int*kf,int*mf){int keyFunction;slot=s;\n" + blk + "\n*kf=keyFunction;*mf=menuFunction;}\n"
                    'int main(void){uint16_t s[]={0xFFFF,0,0x8000|(30<<10),5};for(int i=0;i<4;i++){int a,b;disp(s[i],&a,&b);printf("%d:%d ",a,b);}return 0;}\n')
            out = run_c(code)
            e = ["0:0", "0:0", "%d:30" % (0x8000 | (30 << 10)), "5:0"] if ukr else ["%d:31" % 0xFFFF, "0:0", "%d:30" % (0x8000 | (30 << 10)), "5:0"]
            check(out == e, "А5 %s: диспетчер {0xFFFF,0,меню30,контакт5} -> %s (є %s)" % (n, e, out))
    # фільтр токенів (test_r46/r47/r78): вирізає лише R96-вставки
    from r96_tokfilter import strip_r96
    check(strip_r96(b"a if ((data == 0x8000) || (0) || (x)) b") == strip_r96(b"a if ((data == 0x8000) || (x)) b"), "фільтр: не-UA `|| (0)` вирізається")
    check(strip_r96(b"if (((keyFunction) == 0xFFFF)) { keyFunction = 0; } int m;").strip() == b"int m;", "фільтр: диспетчер UA вирізається")
    check(strip_r96(b"if ((a == 0xFFFF)) { b = 0; }") == b"if ((a == 0xFFFF)) { b = 0; }", "фільтр (мутант): чужий код не вирізається")
    # база
    if subprocess.run(["git", "-C", FW, "cat-file", "-e", BASE + "^{commit}"], capture_output=True).returncode == 0:
        b = subprocess.run(["git", "-C", FW, "show", "%s:MDUV380_firmware/application/include/user_interface/languages/ukrainian.h" % BASE], capture_output=True)
        old = fields(b.stdout.decode("cp1251")); dd = sorted(k for k in set(old) | set(f) if old.get(k) != f.get(k))
        check(dd == ["battery_calibration", "priority_order", "temperature_calibration"], "ukrainian.h проти бази: змінено лише 3 поля: %r" % dd)
    else:
        print("ПРОПУСК: база недоступна (CI/клон без історії): порівняння ukrainian.h з комітом %s не виконано" % BASE)
    print("test_r96: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0])); return 1 if FAILS else 0
if __name__ == "__main__": sys.exit(main())
