#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R74 (хостові перевірки без заліза): слот APRS у «Деталях каналу» і прихований стоковий «Roaming» у швидкому меню.
 1  нумерація швидкого меню НЕ зсунута (enum), прихований пункт пропускається в списку й гортанні (C-стенд із функцією з коду);
 2  усі місця, де значення nonVolatileSettings.roaming ВИКОРИСТОВУЄТЬСЯ для роботи, беруть ROAMING_EFFECTIVE(); сирі лишились лише там, де значення копіюється/порівнюється;
 3  без прапорця (макро не визначено) ROAMING_EFFECTIVE() = сире значення, пункт не ховається;
 4  R74B: «Поз.слота» -> «Джерело:Слот/Рація» (cp1251, ≤16, лише укр.+HAS_GPS+FORK_NO_GPS_MENU; прапорець не чіпано); частину A (слот у «Деталях каналу») скасовано;
 5  наш роумінг за списками (ENABLE_ROAM_RETRY) не зачеплено.
Запуск: python3 tools/test_r74.py (потрібен gcc)"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "application")
UI = os.path.join(APP, "source", "user_interface")
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ: " + msg)


def rd(*p, enc="latin-1"):
    with open(os.path.join(*p), encoding=enc) as f:
        return f.read()


def test_enum_unchanged():
    h = rd(APP, "include", "user_interface", "menuSystem.h")
    body = h[h.index("CH_SCREEN_QUICK_MENU_COPY2VFO"):h.index("NUM_CH_SCREEN_QUICK_MENU_ITEMS")]
    names = re.findall(r"^\s*(CH_SCREEN_QUICK_MENU_\w+)", body, re.M)
    order = names[:9]
    check(order == ["CH_SCREEN_QUICK_MENU_COPY2VFO", "CH_SCREEN_QUICK_MENU_COPY_FROM_VFO", "CH_SCREEN_QUICK_MENU_FILTER_FM", "CH_SCREEN_QUICK_MENU_FILTER_DMR",
                    "CH_SCREEN_QUICK_MENU_DMR_CC_SCAN", "CH_SCREEN_QUICK_MENU_FILTER_DMR_TS", "CH_SCREEN_QUICK_MENU_TALKAROUND", "CH_SCREEN_QUICK_MENU_ROAMING",
                    "CH_SCREEN_QUICK_MENU_AUDIO_MUTE"], "порядок enum швидкого меню (номери швидких клавіш) не змінено: %r" % order)
    check("CH_SCREEN_QUICK_MENU_ROAMING" in names and names.index("CH_SCREEN_QUICK_MENU_ROAMING") == 7, "пункт ROAMING лишився в enum під номером 7 (не видалено)")


def test_skip_logic_c():
    src = rd(UI, "uiChannelMode.c")
    m = re.search(r"static int quickMenuVisibleItem\(int loopOffset\)\n\{.*?\n\}\n", src, re.S)
    check(m is not None, "функція quickMenuVisibleItem є в uiChannelMode.c")
    if not m:
        return
    prog = r'''
#include <stdio.h>
#define NUM_CH_SCREEN_QUICK_MENU_ITEMS 12
#define CH_SCREEN_QUICK_MENU_ROAMING 7
static struct { int currentItemIndex; } menuDataGlobal;
%s
int main(void)
{
	int bad = 0;
	for (int cur = 0; cur < NUM_CH_SCREEN_QUICK_MENU_ITEMS; cur++)
	{
		if (cur == CH_SCREEN_QUICK_MENU_ROAMING) continue;
		menuDataGlobal.currentItemIndex = cur;
		for (int i = -3; i <= 3; i++)
		{
			int v = quickMenuVisibleItem(i);
			if (v == CH_SCREEN_QUICK_MENU_ROAMING || v < 0 || v >= NUM_CH_SCREEN_QUICK_MENU_ITEMS) bad++;
			printf("%%d %%d %%d\n", cur, i, v);
		}
	}
	printf("BAD %%d\n", bad);
	return 0;
}
''' % m.group(0).encode("latin-1").decode("utf-8", "replace")
    with tempfile.TemporaryDirectory() as d:
        c = os.path.join(d, "t.c")
        with open(c, "w") as f:
            f.write(prog)
        r = subprocess.run(["gcc", "-O0", "-o", os.path.join(d, "t"), c], capture_output=True, text=True)
        check(r.returncode == 0, "C-стенд зібрався: %s" % r.stderr[:200])
        if r.returncode:
            return
        out = subprocess.run([os.path.join(d, "t")], capture_output=True, text=True).stdout.split("\n")
    check("BAD 0" in out, "список ніколи не показує прихований пункт")
    rows = {}
    for line in out:
        p = line.split()
        if len(p) == 3 and p[0] != "BAD":
            rows[(int(p[0]), int(p[1]))] = int(p[2])
    # пункти після колишнього «Roaming» лишаються доступні під своїми номерами: з 6 вперед -> 8, з 8 назад -> 6
    check(rows[(6, 1)] == 8 and rows[(8, -1)] == 6 and rows[(6, 0)] == 6 and rows[(8, 0)] == 8, "сусіди прихованого пункту: 6 -> 8, 8 -> 6, номери самих пунктів ті самі")
    check(rows[(11, 1)] == 0 and rows[(0, -1)] == 11, "обгортка кінця/початку списку працює")
    check(rows[(5, 3)] == 9 and rows[(9, -3)] == 5, "кроки через прихований пункт рахуються без нього (5 +3 = 9)")


def test_roaming_uses():
    gate = rd(APP, "include", "functions", "roaming_gate.h")
    check("define ROAMING_STOCK_HIDDEN" in gate and "ROAMING_EFFECTIVE() (ROAMING_OFF)" in gate and "ROAMING_EFFECTIVE() (nonVolatileSettings.roaming)" in gate
          and "defined(HAS_GPS) && defined(FORK_NO_GPS_MENU)" in gate, "roaming_gate.h: прапорець HAS_GPS && FORK_NO_GPS_MENU; без нього макро = сире значення")
    raw = []
    for root, _d, files in os.walk(os.path.join(APP, "source")):
        for fn in files:
            if fn.endswith(".c"):
                for i, line in enumerate(rd(root, fn).split("\n"), 1):
                    if re.search(r"nonVolatileSettings\.roaming\b", line):
                        raw.append((fn, i, line.strip()))
    allowed = [r for r in raw if r[0] == "uiChannelMode.c"]
    others = [r for r in raw if r[0] not in ("uiChannelMode.c", "settings.c")]
    check(not others, "поза uiChannelMode.c/settings.c сирого nonVolatileSettings.roaming нема: %r" % others)
    kinds = sorted(re.sub(r".*(tmpRoaming = nonVolatileSettings\.roaming;|nonVolatileSettings\.roaming != uiDataGlobal|nonVolatileSettings\.roaming = uiDataGlobal).*", r"\1", r[2]) for r in allowed)
    check(len(allowed) == 3 and all("tmpRoaming" in r[2] or "uiDataGlobal.QuickMenu" in r[2] for r in allowed),
          "у uiChannelMode.c сирі лише 3 місця (копія у тимчасове, порівняння, запис із тимчасового): %r" % [(r[1], r[2][:60]) for r in allowed])
    for fn in ("uiChannelMode.c", "uiUtilities.c", "menuRadioInfos.c", "menuChannelDetails.c"):
        check('#include "functions/roaming_gate.h"' in rd(UI, fn), "%s підключає roaming_gate.h" % fn)
    s = rd(UI, "uiChannelMode.c")
    check("ROAMING_EFFECTIVE() != ROAMING_OFF" in s and "ROAMING_EFFECTIVE() >= ROAMING_5KM" in s and s.count("ROAMING_EFFECTIVE()") >= 8, "робочі умови роумінгу беруть ROAMING_EFFECTIVE()")
    # ключове: збережене значення не переписується під прапорцем -- тимчасове береться з сирого, тож порівняння з ним завжди «без змін»
    check("tmpRoaming = nonVolatileSettings.roaming;" in s, "тимчасове значення береться з сирого -> вихід із меню не переписує збережене значення")


def test_flag_off_build():
    """Без макро HAS_GPS/FORK_NO_GPS_MENU: ROAMING_EFFECTIVE() = сире значення, ROAMING_STOCK_HIDDEN не визначено."""
    prog = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
typedef enum { ROAMING_OFF = 0U, ROAMING_MANUAL, ROAMING_5KM } roaming_t;
struct { roaming_t roaming; } nonVolatileSettings = { ROAMING_5KM };
#define SKIP_HEADERS
%s
int main(void)
{
#if defined(ROAMING_STOCK_HIDDEN)
	puts("HIDDEN");
#endif
	printf("EFF %%d\n", (int)ROAMING_EFFECTIVE());
	return 0;
}
'''
    gate = rd(APP, "include", "functions", "roaming_gate.h")
    gate = re.sub(r'#include ".*"\n', "", gate)
    for flags, want in (([], "EFF 2"), (["-DHAS_GPS", "-DFORK_NO_GPS_MENU"], "HIDDEN")):
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "t.c")
            with open(c, "w") as f:
                f.write(prog % gate)
            r = subprocess.run(["gcc"] + flags + ["-o", os.path.join(d, "t"), c], capture_output=True, text=True)
            check(r.returncode == 0, "стенд макро зібрався %r: %s" % (flags, r.stderr[:200]))
            if r.returncode:
                continue
            out = subprocess.run([os.path.join(d, "t")], capture_output=True, text=True).stdout
            check(want in out and (flags or "HIDDEN" not in out), "прапорці %r: %r" % (flags, out.replace("\n", " | ")))
            if flags:
                check("EFF 0" in out, "з прапорцем збережене значення 5 км не діє: EFF 0")


def test_usepos_label():
    hdr = open(os.path.join(APP, "include", "user_interface", "languages", "aprsmode_ua.h"), "rb").read()
    txt = hdr.decode("cp1251")
    lab = re.search(r'APRSM_L_USEPOS_SRC\s+"([^"]*)"', txt).group(1)
    slot = re.search(r'APRSM_V_USEPOS_SLOT\s+"([^"]*)"', txt).group(1)
    rad = re.search(r'APRSM_V_USEPOS_RADIO\s+"([^"]*)"', txt).group(1)
    check((lab, slot, rad) == ("Джерело", "Слот", "Рація"), "підпис і значення в cp1251: %r" % ((lab, slot, rad),))
    check(all(len(lab + ":" + v) <= 16 for v in (slot, rad)), "рядки «Джерело:Слот/Рація» вміщаються у 16 символів")
    s = rd(UI, "menuAprsSettings.c")
    check("{ AS_S_USEPOS, 2U, APRSM_L_USEPOS_SRC, { APRSM_V_USEPOS_RADIO, APRSM_V_USEPOS_SLOT } }" in s, "значення: [0]=Рація (вимк), [1]=Слот (увімк)")
    check("{ AS_S_USEPOS, 2U, APRSM_L_USEPOS, { APRSM_V_OFF, APRSM_V_ON } }" in s, "стокова гілка (інші збірки) лишилась")
    k = s.index("APRSM_L_USEPOS_SRC")
    check("defined(HAS_GPS) && defined(FORK_NO_GPS_MENU) && defined(LANGUAGE_BUILD_UKRAINIAN)" in s[k - 700:k], "нові рядки лише під HAS_GPS+FORK_NO_GPS_MENU+LANGUAGE_BUILD_UKRAINIAN")
    # прапорець і логіка не чіпані; спільні «Увімк/Вимк» не змінено
    check("flagGet(APRSM_RAW_FLAG_USE_POSITION)" in s and "aprsModeSetFlag(APRSM_RAW_FLAG_USE_POSITION, (v != 0U))" in s, "читання/запис прапорця USE_POSITION як було")
    check(re.search(r'APRSM_V_ON\s+"([^"]*)"', txt).group(1) == "Увімк" and re.search(r'APRSM_V_OFF\s+"([^"]*)"', txt).group(1) == "Вимк", "спільні «Увімк/Вимк» не змінено")
    # «Джерело» (канал/GPS) у групі «Позиція» прихований під FORK_NO_GPS_MENU -- двозначності нема
    m = re.search(r"asRowsPos\[\] = \{\n#if !defined\(FORK_NO_GPS_MENU\)\n\t\tAS_S_SOURCE", s)
    check(m is not None, "стоковий рядок «Джерело» (канал/GPS) у «Позиції» прихований під FORK_NO_GPS_MENU")
    # частину A (підпис слота в «Деталях каналу») скасовано: файлу й макросу нема
    check(not os.path.exists(os.path.join(APP, "include", "user_interface", "languages", "aprsslot_ua.h")), "aprsslot_ua.h видалено")
    cd = rd(UI, "menuChannelDetails.c")
    check("APRS_SLOT" not in cd and "aprsslot" not in cd, "частину A у menuChannelDetails.c прибрано")


def test_roam_lists_untouched():
    s = rd(UI, "uiChannelMode.c")
    check("ENABLE_ROAM_RETRY" in rd(UI, "menuChannelDetails.c") and "roamRecList" in rd(UI, "menuChannelDetails.c"), "роумінг за списками в «Деталях каналу» на місці")


def main():
    test_enum_unchanged()
    test_skip_logic_c()
    test_roaming_uses()
    test_flag_off_build()
    test_usepos_label()
    test_roam_lists_untouched()
    if FAILS:
        print("test_r74: ПРОВАЛІВ %d" % len(FAILS))
        sys.exit(1)
    print("test_r74: усе гаразд")


if __name__ == "__main__":
    main()
