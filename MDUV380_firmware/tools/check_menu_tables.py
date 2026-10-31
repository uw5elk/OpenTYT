#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R44-fix F3: звіряє таблиці меню в menuSystem.c з переліком `enum MENU_SCREENS` (menuSystem.h) у КОЖНІЙ конфігурації tools/syntax_check.sh.

Навіщо. Меню пов'язані з enum ПОЗИЦІЙНО: `menuFunctions[]` і `menuDataGlobal.data[]` ініціалізуються без індексів, тож пропущений або зайвий елемент у будь-якій з
умовних гілок (#if ENABLE_AES / ENABLE_CALL_REPLAY / APRS_RX / HAS_COLOURS ...) мовчки зсуває ВСІ наступні меню. R44 саме так і впав: `&menuDataCodeplug` лягло на
позицію 40 (бракувало шести NULL для AES/RCTL/CALL_REPLAY/APRS_HUB), а MENU_CODEPLUG = 46; `data[]` -- масив змінної довжини, тож data[46] був читанням за його межами ->
сміттєвий вказівник -> HardFault на `strlen(0x1DC69F44)` при відкритті меню. Мовні рядки ні до чого: перевірка мовних полів (check_language_fields.py) на R44 проходить.

Що перевіряється для кожної конфігурації (препроцесор `gcc -E -P` -- умови обчислює компілятор, не ми):
  A. `menuFunctions[]` має рівно стільки елементів, скільки значень enum (NUM_MENU_ENTRIES);
  B. функція на позиції відомого меню -- та, що очікується (таблиця EXPECTED_FUNCS: головне, зони, Options, перегляд каналу, повідомлення, APRS, Кодплаг...);
  C. кожен НЕ-NULL елемент `data[]` лежить на позиції СВОГО меню (EXPECTED_DATA); невідомий елемент -- провал (додай його в таблицю свідомо);
  E. кожне меню зі списком пунктів (EXPECTED_DATA) має свою таблицю саме на своїй позиції (а не NULL);
  D. якщо в конфігурації є меню «Кодплаг» (їхні ID -- поза межами стокового масиву), `data[]` має покривати ВСІ значення enum: читання `data[ID]` для будь-якого меню
     (menuSystem.c: menuSystemPushNewMenu/Pop, menuDisplayMenuList.c) інакше виходить за масив. Для решти конфігурацій це лише примітка: так у стоку (data[] коротший за enum).

Лише читання; потрібен gcc (як для syntax_check.sh). Код виходу 1 -- є розбіжності.   Запуск: python3 tools/check_menu_tables.py [--root КАТАЛОГ_MDUV380_firmware] [--only ІМ'Я,ІМ'Я] [--quiet]"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
SRC_REL = os.path.join("application", "source", "user_interface", "menuSystem.c")

# --- очікування: назва enum -> функція в menuFunctions[] ---
EXPECTED_FUNCS = {
    "MENU_MAIN_MENU": "menuDisplayMenuList",
    "MENU_CONTACTS_MENU": "menuDisplayMenuList",
    "MENU_ZONE_LIST": "menuZoneList",
    "MENU_RADIO_INFOS": "menuRadioInfos",
    "MENU_RSSI_SCREEN": "menuRSSIScreen",
    "MENU_LAST_HEARD": "menuLastHeard",
    "MENU_OPTIONS": "menuDisplayMenuList",
    "MENU_GENERAL": "menuGeneralOptions",
    "MENU_CONTACT_LIST": "menuContactList",
    "MENU_CONTACT_DETAILS": "menuContactDetails",
    "MENU_LANGUAGE": "menuLanguage",
    "MENU_CALIBRATION": "menuCalibration",
    "UI_CHANNEL_QUICK_MENU": "uiChannelModeQuickMenu",
    "UI_VFO_QUICK_MENU": "uiVFOModeQuickMenu",
    "MENU_CHANNEL_DETAILS": "menuChannelDetails",
    "MENU_FIRMWARE_INFO": "menuFirmwareInfoScreen",
    "MENU_APRS": "menuAPRSOptions",
    "MENU_AES_KEYS": "menuAESKeys",
    "MENU_MESSAGES": "menuMessages",
    "MENU_RCTL_REMOTE": "menuRCTLRemote",
    "MENU_RCTL_CONFIG": "menuRCTLConfig",
    "MENU_CALL_REPLAY": "menuCallReplay",
    "MENU_APRS_HUB": "menuAprsHub",
    "UI_MESSAGE_BOX": "uiMessageBox",
    "UI_HOTSPOT_MODE": "menuHotspotMode",
    "UI_CPS": "uiCPS",
    "MENU_NUMERICAL_ENTRY": "menuNumericalEntry",
    "UI_TX_SCREEN": "menuTxScreen",
    "UI_SPLASH_SCREEN": "uiSplashScreen",
    "UI_POWER_OFF": "uiPowerOff",
    "UI_VFO_MODE": "uiVFOMode",
    "UI_CHANNEL_MODE": "uiChannelMode",
    "UI_LOCK_SCREEN": "menuLockScreen",
    "UI_PRIVATE_CALL": "menuPrivateCall",
    "MENU_CONTACT_NEW": "menuContactDetails",
    "MENU_THEME_ITEMS_BROWSER": "menuThemeItemsBrowser",
    "MENU_COLOUR_PICKER": "menuColourPicker",
    "MENU_CODEPLUG": "menuDisplayMenuList",
    "MENU_CODEPLUG_CHANNELS": "menuCodeplugChannels",
    "MENU_CODEPLUG_ZONES": "menuZoneList",
}
# --- очікування: таблиця в data[] -> меню, якому вона належить ---
EXPECTED_DATA = {
    "menuDataMainMenu": "MENU_MAIN_MENU",
    "menuDataContact": "MENU_CONTACTS_MENU",
    "menuDataOptions": "MENU_OPTIONS",
    "menuDataCodeplug": "MENU_CODEPLUG",
}
# меню, чиї ID лежать ПОЗА стоковим масивом data[] (додані форком після межі швидких клавіш): для них покриття data[] обов'язкове
FORK_MENU_MARKER = "MENU_CODEPLUG"


def load_configs(root):
    """INCS і набори прапорців усіх конфігурацій з tools/syntax_check.sh (одне джерело правди з перевіркою синтаксису)."""
    path = os.path.join(root, "tools", "syntax_check.sh")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    a = text.index("\nINCS=(")
    b = text.index("# Щоб побачити попередження")
    snippet = text[a:b] + '''
printf 'INCS\\t%s\\n' "${INCS[*]}"
for cfg in "${CONFIGS[@]}"; do
	declare -n d="DEFS_${cfg}"
	printf 'CFG\\t%s\\t%s\\n' "$cfg" "${d[*]}"
	unset -n d
done
'''
    r = subprocess.run(["bash", "-c", "set -u\n" + snippet], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("не вдалося прочитати конфігурації з syntax_check.sh: " + r.stderr.strip()[:300])
    incs, cfgs = [], []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if parts[0] == "INCS":
            incs = parts[1].split()
        elif parts[0] == "CFG":
            cfgs.append((parts[1], parts[2].split() if len(parts) > 2 else []))
    if not incs or not cfgs:
        raise RuntimeError("syntax_check.sh не дав ні INCS, ні CONFIGS (змінився формат файла?)")
    return incs, cfgs


def preprocess(root, incs, defs):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [SRC_REL], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("gcc -E не пройшов: " + r.stderr.strip()[:400])
    return r.stdout


def _balanced(text, start, open_ch, close_ch):
    """Індекс закривної дужки для відкривної на позиції `start`."""
    depth = 0
    for k in range(start, len(text)):
        c = text[k]
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return k
    raise ValueError("незбалансовані дужки")


def _split_top(body):
    """Розбиває тіло ініціалізатора за комами верхнього рівня."""
    out, depth, cur = [], 0, []
    for c in body:
        if c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        if c == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
    last = "".join(cur).strip()
    if last:
        out.append(last)
    return out


def parse_enum(src):
    m = re.search(r"enum\s+MENU_SCREENS\s*\{", src)
    if not m:
        raise ValueError("enum MENU_SCREENS не знайдено")
    end = _balanced(src, m.end() - 1, "{", "}")
    vals, nxt = {}, 0
    for item in _split_top(src[m.end():end]):
        if "=" in item:
            name, expr = [x.strip() for x in item.split("=", 1)]
            nxt = int(expr) if re.fullmatch(r"-?\d+", expr) else vals[expr]
        else:
            name = item
        vals[name] = nxt
        nxt += 1
    return vals


def parse_data(src, enum):
    """`menuDataGlobal.data` -> (довжина масиву, {позиція: вираз})."""
    m = re.search(r"menuDataGlobal_t\s+menuDataGlobal\s*=\s*\{", src)
    if not m:
        raise ValueError("ініціалізатор menuDataGlobal не знайдено")
    end = _balanced(src, m.end() - 1, "{", "}")
    body = src[m.end():end]
    m2 = re.search(r"\.data\s*=\s*\{", body)
    if not m2:
        raise ValueError(".data = { ... } не знайдено")
    e2 = _balanced(body, m2.end() - 1, "{", "}")
    idx, entries = 0, {}
    for item in _split_top(body[m2.end():e2]):
        dm = re.match(r"\[\s*(\w+|\d+)\s*\]\s*=\s*(.*)$", item, re.S)
        if dm:
            key = dm.group(1)
            idx = int(key) if key.isdigit() else enum[key]
            item = dm.group(2).strip()
        entries[idx] = item
        idx += 1
    return (max(entries) + 1 if entries else 0), entries


def parse_functions(src):
    m = re.search(r"menuFunctionData_t\s+menuFunctions\s*\[\s*\]\s*=\s*\{", src)
    if not m:
        raise ValueError("menuFunctions[] не знайдено")
    end = _balanced(src, m.end() - 1, "{", "}")
    funcs = []
    for item in _split_top(src[m.end():end]):
        im = re.match(r"\{\s*(\w+)", item)
        funcs.append(im.group(1) if im else item)
    return funcs


def is_null(expr):
    return expr.replace(" ", "") in ("NULL", "((void*)0)", "0")


def check_config(name, src):
    """-> (список провалів, список приміток) для одного препроцесованого menuSystem.c."""
    errs, notes = [], []
    enum = parse_enum(src)
    num = enum["NUM_MENU_ENTRIES"]
    by_id = {}
    for k, v in enum.items():
        if v >= 0 and k != "NUM_MENU_ENTRIES":
            by_id.setdefault(v, k)
    funcs = parse_functions(src)
    # A
    if len(funcs) != num:
        errs.append("menuFunctions[] має %d елементів, а enum MENU_SCREENS -- %d (NUM_MENU_ENTRIES): усі меню після розбіжності зсунуті" % (len(funcs), num))
    # B
    for mname, fn in EXPECTED_FUNCS.items():
        if mname in enum and enum[mname] < len(funcs) and funcs[enum[mname]] != fn:
            errs.append("menuFunctions[%d] (%s) = %s, очікувалось %s" % (enum[mname], mname, funcs[enum[mname]], fn))
    # C, D
    length, entries = parse_data(src, enum)
    for pos, expr in sorted(entries.items()):
        if is_null(expr):
            continue
        tbl = expr.lstrip("&").strip()
        if tbl not in EXPECTED_DATA:
            errs.append("data[%d] = %s: невідома таблиця меню -- додай її в EXPECTED_DATA (check_menu_tables.py) свідомо, з очікуваним меню" % (pos, expr))
            continue
        want = enum.get(EXPECTED_DATA[tbl])
        if want is None:
            errs.append("data[%d] = %s: у цій конфігурації нема меню %s" % (pos, expr, EXPECTED_DATA[tbl]))
        elif want != pos:
            errs.append("data[%d] = %s, а меню %s має ID %d: таблиця лежить на чужій позиції (data[%d] -- %s)%s" % (
                pos, expr, EXPECTED_DATA[tbl], want, want, "NULL/нема" if want not in entries or is_null(entries.get(want, "NULL")) else entries[want],
                "; різниця %+d (бракує/зайвих елементів перед нею)" % (want - pos)))
    # E. меню зі списком мають СВОЮ таблицю на своїй позиції (інакше menuDisplayMenuList читає NULL/сміття)
    for tbl, mname in EXPECTED_DATA.items():
        if mname in enum:
            expr = entries.get(enum[mname], "NULL")
            if expr.lstrip("&").strip() != tbl:
                errs.append("data[%d] (%s) = %s, а має бути &%s: меню відкриється без таблиці пунктів" % (enum[mname], mname, "NULL/нема" if is_null(expr) else expr, tbl))
    if FORK_MENU_MARKER in enum:
        if length < num:
            errs.append("data[] має %d елементів, а меню в enum -- %d: data[%d..%d] читається ЗА межами масиву змінної довжини (сміттєвий вказівник -> HardFault)" % (length, num, length, num - 1))
    elif length < num:
        notes.append("data[] має %d елементів < %d значень enum (так у стоку; читання data[ID>=%d] -- за масивом, у цій конфігурації без наслідків лише поки там NULL)" % (length, num, length))
    return errs, notes, {"enum": num, "functions": len(funcs), "data": length}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--only", default="", help="лише ці конфігурації (через кому)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    incs, cfgs = load_configs(args.root)
    only = {x for x in args.only.split(",") if x}
    bad, total = [], 0
    for name, defs in cfgs:
        if only and name not in only:
            continue
        total += 1
        try:
            errs, notes, info = check_config(name, preprocess(args.root, incs, defs))
        except (RuntimeError, ValueError, KeyError) as e:
            bad.append("[%s] не вдалося розібрати: %s" % (name, e))
            continue
        for e in errs:
            bad.append("[%s] %s" % (name, e))
        if not args.quiet:
            print("  %-14s enum %2d, menuFunctions %2d, data[] %2d%s" % (name, info["enum"], info["functions"], info["data"], "  (коротший за enum, як у стоку)" if notes else ""))
    if bad:
        print("\nПРОВАЛ: таблиці меню не збігаються з enum MENU_SCREENS (%d):" % len(bad))
        seen = set()
        for b in bad:
            key = b.split("] ", 1)[1] if "] " in b else b
            if key in seen:
                continue
            seen.add(key)
            others = [x.split("]")[0][1:] for x in bad if (x.split("] ", 1)[1] if "] " in x else x) == key]
            print("  - %s: %s%s" % (others[0], key, ("  (так само в: %s)" % ", ".join(others[1:])) if len(others) > 1 else ""))
        sys.exit(1)
    print("check_menu_tables: усе гаразд (%d конфігурацій: menuFunctions[] і data[] збігаються з enum MENU_SCREENS)" % total)


if __name__ == "__main__":
    main()
