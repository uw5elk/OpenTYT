#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R66 (хост-перевірки). Розділи додаються по комітах.

A  R66A: індикатор роумінгу на екрані передачі («Р>» малювалось як «Ð>»):
   A1 передумова: у шрифті 16x32 (FONT_SIZE_4, UA) код 0xD0 -- латинська «D з рискою» (збігається з гліфом звичайного charset.h), а не «P»;
   A2 передумова: кириличні гліфи в 16x32 є лише для А И Й К Л М О П Т У;
   A3 у малих шрифтах (6x8, 8x16) код 0xD0 -- кирилична «Р» (відрізняється від латинської «D з рискою»), тож індикатор «Р<N>» на екрані каналу малюється правильно;
   A4 ROAM_IND_SPARE (його малює 16x32): лише ASCII, і кожен символ має непорожній гліф у 16x32; мутант «кирилична Р» ловиться.
B  R66B: шпаргалка розкладки в редакторах назви (uiNameEditor.c, хост з заглушками):
   B1 ВНИЗ відкриває шпаргалку, символ, що гортається, підтверджено в текст; редактор малює шпаргалку (а не поле набору);
   B2 поки шпаргалка відкрита, жодна клавіша (зелена/червона теж) не доходить до викликача (nameEdSheetEvent повертає true);
   B3 клавіша, що закрила шпаргалку, -- її відпускання ковтається один раз (зелена не зберігає), наступна клавіша -- ні; валкодер (натискання+відпускання разом) нічого не ковтає;
   B4 довге утримання не закриває; текст і режим набору шпаргалка не змінює; мутанти (6) ловляться;
   B5 усі споживачі редактора викликають nameEdSheetEvent ДО обробки зеленої/червоної; рядки в cp1251 вміщаються; APRS-налаштування (user-only APRS_R66_SHEET).
C  R66C: переміщення (канал у зоні, TG у списку прийому):
   C1 move_ua.h -- cp1251, не UTF-8; кожен рядок повідомлення <= 16 символів (FONT_SIZE_3 = 8 px, екран 128 px); рядки дій теж <= 16 символів (рядок списку меню);
   C2 набір #define в move_ui.h (англ.) збігається з move_ua.h; англ. рядки ASCII;
   C3 codeplugZoneMoveChannel / codeplugRxGroupMoveMember викликаються лише з menuZoneList.c / menuRxGroups.c, в першому -- під ZONE_MOVE_ENABLED;
   C4 move_ui.h підключається у menuZoneList.c під ZONE_MOVE_ENABLED, в menuRxGroups.c -- у блоці RXGROUP_UI_ENABLED;
D  R66D: тон передачі супутника за набором 1/2/3 (ENABLE_SAT_TONE_SYNC):
   D1 у menuSatelliteScreen.c рівно ДВА присвоєння txTone через satelliteTxToneFor (клавіші 1/2/3 і calculateActiveSatelliteData), кожне всередині #if defined(ENABLE_SAT_TONE_SYNC);
      стокове присвоєння в selectSatellite не чіпано; заголовок підключається лише під прапорцем;
   D2 прапорець у Makefile, обох кроках build.yml, syntax_check.sh; тон взведення (uiTxScreen.c) не змінено;
   D3 мутанти satellite_tone.h (не той набір, нема межі, NULL) валять tests/test_sat_tone.c.
Запуск: python3 tools/test_r66.py"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
INC = os.path.join(ROOT, "application", "include")
import font16_probe as F      # noqa: E402

FAILS = []
PASSED = [0]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def small_font(name):
    t = open(os.path.join(INC, "hardware", "HX8353E_charset_UA.h"), encoding="latin-1").read()
    i = t.index("const uint8_t " + name + "[]")
    j = t.index("};", i)
    body = re.sub(r"//[^\n]*", "", t[t.index("{", i) + 1:j])
    return bytes(int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|\b\d+\b", body))


def small_glyph(f, c):
    bpc = f[7]
    o = 8 + (c - f[2]) * bpc
    return f[o:o + bpc]


def indicator_ok(value, f32):
    """Кожен символ -- ASCII і має непорожній гліф у 16x32."""
    for ch in value:
        if ord(ch) > 0x7E:
            return False
        if ch != " " and not any("#" in r for r in F.glyph(f32, ord(ch))):
            return False
    return True



B_HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiNameEditor.h"
#include "functions/sms_multitap.h"

uiDataGlobal_t uiDataGlobal;
static stringsTable_t s_lang;
const stringsTable_t *currentLanguage = &s_lang;
static uint32_t s_now;
uint32_t ticksGetMillis(void) { return s_now; }
static char s_rec[2048];
static void rec(const char *fmt, ...) { va_list a; va_start(a, fmt); size_t n = strlen(s_rec); vsnprintf(s_rec + n, sizeof s_rec - n, fmt, a); va_end(a); }
void displayClearBuf(void) { rec("CLR;"); }
void displayRender(void) { rec("RND;"); }
void menuDisplayTitle(const char *t) { rec("TITLE[%s];", t); }
void displayThemeApply(themeItem_t fg, themeItem_t bg) { (void)fg; (void)bg; }
int displayPrintCore(int16_t x, int16_t y, const char *t, ucFont_t f, ucTextAlign_t a, bool inv) { (void)x;(void)y;(void)f;(void)a;(void)inv; rec("CORE[%s];", t); return 0; }
void displayFillRect(int16_t x, int16_t y, int16_t w, int16_t h, bool inv) { (void)x;(void)y;(void)w;(void)h;(void)inv; }
void displayPrintAt(uint16_t x, uint16_t y, const char *t, ucFont_t f) { (void)x;(void)y;(void)f; rec("AT[%s];", t); }
void displayPrintCentered(uint16_t y, const char *t, ucFont_t f) { (void)f; rec("CEN(%u)[%s];", y, t); }
void uiSmsKeyLayoutDraw(uint8_t mode, const char *title, const char *hint) { rec("SHEET(%d)[%s][%s];", (int)mode, title, hint); }

static int fails;
#define CK(c, ...) do { if (!(c)) { fails++; printf("ПРОВАЛ: " __VA_ARGS__); printf("\n"); } } while (0)
static uiEvent_t ke(char key, int event) { uiEvent_t e; memset(&e, 0, sizeof e); e.hasEvent = true; e.events = KEY_EVENT; e.keys.key = key; e.keys.event = (uint8_t)event; return e; }

int main(void)
{
	char *b = uiDataGlobal.MessageBox.message;
	uiEvent_t e;

	/* B1: ВНИЗ відкриває шпаргалку; гортаний символ підтверджено */
	memset(b, 0, 68);
	nameEdInit(b, "Ab");
	s_now = 100000;
	e = ke('2', KEY_MOD_PRESS); (void)nameEdHandleKey(b, "T", &e);   /* гортаємо клавішу 2 */
	CK(b[17] == '2', "B1: символ гортається (key=%d)", b[17]);
	s_rec[0] = 0;
	e = ke(KEY_DOWN, KEY_MOD_PRESS | KEY_MOD_DOWN);
	CK(nameEdHandleKey(b, "T", &e), "B1: ВНИЗ спожито");
	CK(b[21] == 1, "B1: шпаргалку відкрито");
	CK(b[17] == 0, "B1: символ, що гортався, підтверджено (key=%d)", b[17]);
	CK(strstr(s_rec, "SHEET(") != NULL && strstr(s_rec, "AT[") == NULL, "B1: малюється шпаргалка, не поле набору: %s", s_rec);
	CK(strlen(b) == 3, "B1: підтверджений символ у тексті (len=%d)", (int)strlen(b));
	{
		char before[17]; uint8_t mode = (uint8_t)b[19];
		memcpy(before, b, 17);
		/* B2: жодна клавіша не доходить до викликача, шпаргалка лишається, поки не НАТИСКАННЯ */
		e = ke(KEY_DOWN, KEY_MOD_UP);
		CK(nameEdSheetEvent(b, "T", &e) && b[21] == 1, "B2: відпускання ВНИЗ не закриває");
		e = ke(KEY_GREEN, KEY_MOD_PRESS | KEY_MOD_LONG);
		CK(nameEdSheetEvent(b, "T", &e) && b[21] == 1, "B4: довге утримання не закриває");
		e = ke(KEY_GREEN, KEY_MOD_PRESS);
		CK(nameEdSheetEvent(b, "T", &e), "B2: натискання зеленої спожито");
		CK(b[21] == 0 && b[22] == KEY_GREEN, "B3: закрито, чекаємо відпускання зеленої (sheet=%d swallow=%d)", b[21], b[22]);
		e = ke(KEY_GREEN, KEY_MOD_UP);
		CK(nameEdSheetEvent(b, "T", &e), "B3: відпускання зеленої ковтнуто (не збереження)");
		CK(b[22] == 0, "B3: ковтання зняте");
		e = ke(KEY_GREEN, KEY_MOD_UP);
		CK(!nameEdSheetEvent(b, "T", &e), "B3: наступна зелена -- вже звичайна (зберегти)");
		CK(memcmp(before, b, 17) == 0 && (uint8_t)b[19] == mode, "B4: текст і режим шпаргалка не змінила");
	}
	/* B3: червона так само */
	e = ke(KEY_DOWN, KEY_MOD_PRESS); (void)nameEdHandleKey(b, "T", &e);
	e = ke(KEY_RED, KEY_MOD_PRESS); CK(nameEdSheetEvent(b, "T", &e), "B3: червона закриває, спожита");
	e = ke(KEY_RED, KEY_MOD_UP);    CK(nameEdSheetEvent(b, "T", &e), "B3: відпускання червоної ковтнуто");
	/* B3: інша клавіша після закриття скидає ковтання */
	e = ke(KEY_DOWN, KEY_MOD_PRESS); (void)nameEdHandleKey(b, "T", &e);
	e = ke('5', KEY_MOD_PRESS); CK(nameEdSheetEvent(b, "T", &e) && b[22] == '5', "B3: цифра закрила, чекаємо її відпускання");
	e = ke(KEY_RED, KEY_MOD_PRESS); CK(!nameEdSheetEvent(b, "T", &e) && b[22] == 0, "B3: нова клавіша -- ковтання скинуто, подія звичайна");
	/* B3: валкодер -- натискання й відпускання однією подією: нічого не ковтаємо */
	e = ke(KEY_DOWN, KEY_MOD_PRESS); (void)nameEdHandleKey(b, "T", &e);
	e = ke(KEY_GREEN, KEY_MOD_PRESS | KEY_MOD_UP); CK(nameEdSheetEvent(b, "T", &e) && b[22] == 0 && b[21] == 0, "B3: натискання+відпускання разом -- нічого не ковтаємо");
	/* без шпаргалки подія не чіпається */
	e = ke(KEY_GREEN, KEY_MOD_UP); CK(!nameEdSheetEvent(b, "T", &e), "B2: без шпаргалки -- подія звичайна");
	/* не клавіша */
	{ uiEvent_t f; memset(&f, 0, sizeof f); f.hasEvent = true; f.events = FUNCTION_EVENT; CK(!nameEdSheetEvent(b, "T", &f), "B2: не KEY_EVENT -- не чіпаємо"); }
	/* ініціалізація чистить стан шпаргалки */
	b[21] = 1; b[22] = 7; nameEdInit(b, ""); CK(b[21] == 0 && b[22] == 0, "B1: nameEdInit скидає шпаргалку");
	/* перемалювання при відкритій шпаргалці лишає шпаргалку */
	b[21] = 1; s_rec[0] = 0; nameEdDraw(b, "T"); CK(strstr(s_rec, "SHEET(") != NULL, "B1: перемалювання лишає шпаргалку");
	/* підказка під полем набору (шпаргалка закрита) */
	b[21] = 0; s_rec[0] = 0; nameEdDraw(b, "T"); CK(strstr(s_rec, "CEN(96)[") != NULL, "B1: підказка про ВНИЗ під полем набору");
	printf(fails ? "ПРОВАЛІВ: %d\n" : "B_OK\n", fails);
	return fails ? 1 : 0;
}
'''

B_MUTANTS = [
    ("ВНИЗ не відкриває шпаргалку", "NE_SHEET(buf) = 1;", "NE_SHEET(buf) = 0;"),
    ("шпаргалка не пропускає подій до викликача (повертає false)", "		return true;   // поки шпаргалка відкрита", "		return false;   // поки шпаргалка відкрита"),
    ("відпускання закривальної клавіші не ковтається", "NE_SWALLOW(buf) = (char)((ev->keys.event & KEY_MOD_UP) ? 0 : ev->keys.key);", "NE_SWALLOW(buf) = 0;"),
    ("довге утримання закриває", "if ((ev->keys.event & KEY_MOD_PRESS) && ((ev->keys.event & KEY_MOD_LONG) == 0))\n\t\t{\n\t\t\tNE_SHEET(buf) = 0;", "if (ev->keys.event & KEY_MOD_PRESS)\n\t\t{\n\t\t\tNE_SHEET(buf) = 0;"),
    ("символ не підтверджується перед шпаргалкою", "		nameEdCommit(buf);\n		NE_SHEET(buf) = 1;", "		NE_SHEET(buf) = 1;"),
    ("перемалювання ховає шпаргалку", "	if (NE_SHEET(buf) != 0)\n	{\n		/* R66B: шпаргалка", "	if (0)\n	{\n		/* R66B: шпаргалка"),
]


def b_build(td, src_text, tag):
    import test_r64_editor as t64
    hc = os.path.join(td, "h_%s.c" % tag)
    open(hc, "w", encoding="utf-8").write(B_HARNESS)
    sc = os.path.join(td, "ne_%s.c" % tag)
    open(sc, "w", encoding="utf-8").write(src_text)
    exe = os.path.join(td, "b_%s" % tag)
    cmd = ["gcc", "-O1", "-w", "-std=gnu11"] + t64.incs() + t64.DEFS + ["-DENABLE_ZONE_RENAME", hc, sc, t64.MULTITAP, "-Wl,--unresolved-symbols=ignore-all", "-o", exe]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    return exe if r.returncode == 0 else None, r.stderr[-400:]


def section_b():
    import shutil
    import tempfile
    if not shutil.which("gcc"):
        print("test_r66: нема gcc -- розділ B пропущено")
        return
    src = open(os.path.join(ROOT, "application", "source", "user_interface", "uiNameEditor.c"), encoding="utf-8").read()
    with tempfile.TemporaryDirectory() as td:
        exe, err = b_build(td, src, "ok")
        check(exe is not None, "B: збірка тесту: " + err)
        if exe is None:
            return
        r = subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=60)
        check(r.returncode == 0 and "B_OK" in r.stdout, "B1-B4: хост-тест редактора: " + r.stdout[-600:])
        for i, (name, old, new) in enumerate(B_MUTANTS):
            old = old.replace("\\n", "\n").replace("\\t", "\t")
            new = new.replace("\\n", "\n").replace("\\t", "\t")
            if src.count(old) != 1:
                check(False, "B4: мутант «%s»: шаблон знайдено %d раз(ів), треба 1 (код змінився -- онови мутант)" % (name, src.count(old)))
                continue
            exe2, err2 = b_build(td, src.replace(old, new, 1), "m%d" % i)
            if exe2 is None:
                check(False, "B4: мутант «%s» не збирається: %s" % (name, err2))
                continue
            r2 = subprocess.run([exe2], capture_output=True, text=True, errors="replace", timeout=60)
            check(r2.returncode != 0, "B4: мутант «%s» -- тест мусить провалитись" % name)

    # B5: порядок викликів у споживачах + рядки
    ui = os.path.join(ROOT, "application", "source", "user_interface")
    for fn, buf in (("menuZoneList.c", "ZR_BUF"), ("menuRoam.c", "ROAM_ED_BUF"), ("menuAESKeys.c", "AESK_ED_BUF"), ("menuRxGroups.c", "RXG_BUF")):
        t = open(os.path.join(ui, fn), encoding="utf-8").read()
        i = t.find("nameEdSheetEvent(" + buf)
        g = t.find("KEYCHECK_SHORTUP(ev->keys, KEY_GREEN)", i) if i >= 0 else -1
        check(i >= 0 and g > i, "B5: %s: nameEdSheetEvent викликається ДО обробки зеленої" % fn)
    t = open(os.path.join(ui, "menuAprsSettings.c"), encoding="utf-8").read()
    depth_in = False
    outside = []
    for ln in t.split("\n"):
        if ln.startswith("#if defined(APRS_R66_SHEET)"):
            depth_in = True
        elif depth_in and ln.startswith("#endif"):
            depth_in = False
        elif (not depth_in) and ("NAMED_" in ln or ".layout" in ln or ".swallowUp" in ln or "uiSmsKeyLayoutDraw" in ln):
            outside.append(ln.strip())
    check(t.count("#if defined(APRS_R66_SHEET)") == 5 and not outside, "B5: APRS-налаштування: усі правки R66B під APRS_R66_SHEET (поза блоками: %r)" % outside)
    cfg = open(os.path.join(INC, "functions", "aprs_rx_cfg.h"), encoding="utf-8").read()
    m = re.search(r"#if defined\(ENABLE_APRS_RX\) && !defined\(ENABLE_APRS_RX_PROBE\)\n#define APRS_R66_SHEET 1", cfg)
    check(m is not None, "B5: APRS_R66_SHEET -- лише user (не probe/diag)")
    h = open(os.path.join(INC, "user_interface", "languages", "nameed_ua.h"), "rb").read().decode("cp1251")
    for mm in re.finditer(r'#define\s+(NAMED_\w+)\s+"((?:[^"\\]|\\.)*)"', h):
        val = mm.group(2).replace("%s", "XXXX")
        check(len(val) <= 26, "B5: %s: %d знаків (>26 для шрифту 6x8 на 160 px)" % (mm.group(1), len(val)))


def section_c():
    ua_b = open(os.path.join(INC, "user_interface", "languages", "move_ua.h"), "rb").read()
    try:
        ua_b.decode("utf-8")
        utf = True
    except UnicodeDecodeError:
        utf = False
    check(not utf, "C1: move_ua.h -- cp1251, не валідний UTF-8")
    ua = ua_b.decode("cp1251")
    en = open(os.path.join(INC, "user_interface", "move_ui.h"), encoding="utf-8").read()
    en = en[en.index("#else"):]
    pat = re.compile(r'#define\s+(MV_\w+)\s+"([^"]*)"')
    u = dict(pat.findall(ua))
    e = dict(pat.findall(en))
    check(set(u) == set(e) and len(u) == 7, "C2: однаковий набір MV_* (укр %d, англ %d)" % (len(u), len(e)))
    for k, v in u.items():
        lines = v.replace("\\n", "\n").split("\n")
        lim = 16
        check(all(len(x) <= lim for x in lines), "C1: %s %r -- рядки <= %d символів" % (k, v, lim))
    for k, v in e.items():
        check(all(ord(c) < 128 for c in v), "C2: англ. %s -- ASCII" % k)
        lim = 16
        check(all(len(x) <= lim for x in v.replace("\\n", "\n").split("\n")), "C2: англ. %s -- рядки <= %d" % (k, lim))
    ui = os.path.join(ROOT, "application", "source", "user_interface")
    zl = open(os.path.join(ui, "menuZoneList.c"), encoding="cp1251", errors="replace").read()
    rg = open(os.path.join(ui, "menuRxGroups.c"), encoding="cp1251", errors="replace").read()
    check("codeplugZoneMoveChannel" in zl and "codeplugRxGroupMoveMember" in rg, "C3: виклики на місці")
    # перший виклик у menuZoneList.c -- всередині #if defined(ZONE_MOVE_ENABLED)
    i = zl.index("codeplugZoneMoveChannel")
    pre = zl[:i]
    depth_ok = pre.rfind("#if defined(ZONE_MOVE_ENABLED)") > pre.rfind("#endif")
    check(depth_ok, "C3: codeplugZoneMoveChannel у menuZoneList.c -- під #if ZONE_MOVE_ENABLED")
    for dirn, _, files in os.walk(ui):
        for f in files:
            if f.endswith(".c") and f not in ("menuZoneList.c", "menuRxGroups.c"):
                t = open(os.path.join(dirn, f), encoding="cp1251", errors="replace").read()
                check("codeplugZoneMoveChannel" not in t and "codeplugRxGroupMoveMember" not in t, "C3: %s не викликає функції переміщення" % f)
    check(zl.count('#include "user_interface/move_ui.h"') == 1 and zl.rfind("#if defined(ZONE_MOVE_ENABLED)", 0, zl.index("move_ui.h")) > zl.rfind("#endif", 0, zl.index("move_ui.h")), "C4: menuZoneList.c підключає move_ui.h під ZONE_MOVE_ENABLED")
    j = rg.index("move_ui.h")
    check(rg.rfind("RXGROUP_UI_ENABLED", 0, j) > rg.rfind("#endif", 0, j), "C4: menuRxGroups.c підключає move_ui.h у блоці RXGROUP_UI_ENABLED")


def section_d():
    import tempfile
    ui = os.path.join(ROOT, "application", "source", "user_interface", "menuSatelliteScreen.c")
    t = open(ui, encoding="utf-8", errors="replace").read()
    sites = [m.start() for m in re.finditer(r"currentChannelData->txTone\s*=\s*satelliteTxToneFor\(", t)]
    check(len(sites) == 2, "D1: присвоєнь через satelliteTxToneFor: %d (мусить 2)" % len(sites))
    for i in sites:
        pre = t[:i]
        check(pre.rfind("#if defined(ENABLE_SAT_TONE_SYNC)") > pre.rfind("#endif"), "D1: присвоєння @%d всередині #if ENABLE_SAT_TONE_SYNC" % i)
    k = t.index("static void selectSatellite(uint32_t selectedSatellite)\n{")
    sel = t[k:t.index("\n}\n", k)]
    check("currentChannelData->txTone = currentActiveSatellite->freqs[currentSatelliteFreqIndex].txCTCSS;" in sel, "D1: стокове присвоєння в selectSatellite збережено")
    # перше присвоєння -- в обробнику клавіш (перед needsUpdate-виходом), друге -- у calculateActiveSatelliteData
    kh = t.index("if (needsUpdate)")
    check(sites[0] > kh and sites[0] < t.index("updateScreen(ev, false, true);", kh), "D1: перше присвоєння -- в обробнику клавіш 1/2/3, до updateScreen")
    kc = t.index("static void calculateActiveSatelliteData(bool forceFrequencyUpdate)\n{")
    check(sites[1] > kc, "D1: друге присвоєння -- в calculateActiveSatelliteData")
    inc = t.index('#include "functions/satellite_tone.h"')
    check(t.rfind("#if defined(ENABLE_SAT_TONE_SYNC)", 0, inc) > t.rfind("#endif", 0, inc), "D1: заголовок підключається лише під прапорцем")
    mk = open(os.path.join(ROOT, "Makefile"), encoding="utf-8").read()
    check("ifeq ($(ENABLE_SAT_TONE_SYNC),1)\nDEFS += -DENABLE_SAT_TONE_SYNC" in mk, "D2: Makefile")
    yml = open(os.path.join(ROOT, "..", ".github", "workflows", "build.yml"), encoding="utf-8").read()
    check(yml.count("ENABLE_SAT_TONE_SYNC=1") == yml.count("ENABLE_RXGROUP_EDIT=1") and yml.count("ENABLE_SAT_TONE_SYNC=1") >= 2, "D2: build.yml -- у кожному кроці з ENABLE_RXGROUP_EDIT=1 (%d)" % yml.count("ENABLE_SAT_TONE_SYNC=1"))
    sc = open(os.path.join(HERE, "syntax_check.sh"), encoding="utf-8").read()
    check("DEFS_SATTONE=" in sc and "SATTONEBARE)" in sc and "-DENABLE_SAT_TONE_SYNC)" in sc, "D2: syntax_check.sh")
    tx = open(os.path.join(ROOT, "application", "source", "user_interface", "uiTxScreen.c"), encoding="utf-8", errors="replace").read()
    check("SAT_TONE" not in tx, "D2: uiTxScreen.c (тон взведення) не чіпано")
    # D3: мутанти
    hdr = os.path.join(INC, "functions", "satellite_tone.h")
    h = open(hdr, encoding="utf-8").read()
    muts = [("не той набір", "return sat->freqs[idx].txCTCSS;", "return sat->freqs[0].txCTCSS;"),
            ("нема межі набору", "|| ((unsigned)idx > (unsigned)SATELLITE_OTHER_FREQ)", ""),
            ("нема перевірки NULL", "(sat == NULL) ||", ""),
            ("тон взведення замість тону передачі", "return sat->freqs[idx].txCTCSS;", "return sat->freqs[idx].armCTCSS;")]
    sh = open(os.path.join(ROOT, "tests", "run_tests.sh"), encoding="utf-8").read()
    fw = ROOT
    incs = re.search(r'FW_INCS="(.*?)"\n', sh, re.S).group(1).replace("\\\n", " ").replace("$FW", fw).split()
    xf = re.search(r'\[test_sat_tone\]="\$FW_INCS ([^"]*)"', sh).group(1).split()
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "functions"))
        for name, a, b in muts + [("оригінал", "", "")]:
            src = h if name == "оригінал" else h.replace(a, b)
            if name != "оригінал":
                check(h.count(a) == 1 or name == "нема межі набору" or name == "нема перевірки NULL", "D3: фрагмент мутанта «%s» знайдено" % name)
                check(src != h, "D3: мутант «%s» змінює файл" % name)
            open(os.path.join(td, "functions", "satellite_tone.h"), "w", encoding="utf-8").write(src)
            exe = os.path.join(td, "t")
            r = subprocess.run(["gcc", "-O1", "-w", "-I", td] + incs + xf + ["-o", exe, os.path.join(ROOT, "tests", "test_sat_tone.c")], capture_output=True, text=True, cwd=ROOT)
            if r.returncode != 0:
                check(False, "D3: «%s» не збирається: %s" % (name, r.stderr[-200:]))
                continue
            rc = subprocess.run([exe], capture_output=True, text=True).returncode
            if name == "оригінал":
                check(rc == 0, "D3: оригінал проходить")
            else:
                check(rc != 0, "D3: мутант «%s» убито" % name)


def main():
    ua = F.load(os.path.join(INC, "hardware", "HX8353E_charset_UA.h"))
    lat = F.load(os.path.join(INC, "hardware", "HX8353E_charset.h"))
    check(F.glyph(ua, 0xD0) == F.glyph(lat, 0xD0), "A1: 16x32 UA: гліф 0xD0 збігається з латинським (Ð)")
    check(F.glyph(ua, 0xD0) != F.glyph(ua, 0x50), "A1: 16x32 UA: гліф 0xD0 не є «P»")
    cyr = [c for c in range(0xC0, 0x100) if F.glyph(ua, c) != F.glyph(lat, c)]
    check(bytes(cyr).decode("cp1251") == "АИЙКЛМОПТУ", "A2: кириличні гліфи 16x32: %r" % bytes(cyr).decode("cp1251"))
    f6, f8 = small_font("font_6x8"), small_font("font_8x16")
    lat6 = small_font("font_6x8")
    check(small_glyph(f6, 0xD0) != small_glyph(f6, 0x44) and small_glyph(f8, 0xD0) != small_glyph(f8, 0x44), "A3: у 6x8 і 8x16 0xD0 не є латинською «D»")
    # у малих шрифтах «Р» відрізняється від «Ð» звичайного charset.h
    latf8 = None
    t = open(os.path.join(INC, "hardware", "HX8353E_charset.h"), encoding="latin-1").read()
    i = t.index("const uint8_t font_8x16[]")
    j = t.index("};", i)
    body = re.sub(r"//[^\n]*", "", t[t.index("{", i) + 1:j])
    latf8 = bytes(int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|\b\d+\b", body))
    check(small_glyph(f8, 0xD0) != small_glyph(latf8, 0xD0), "A3: 8x16 UA: 0xD0 -- не латинська Ð")

    h = open(os.path.join(INC, "user_interface", "languages", "roam_ua.h"), "rb").read().decode("cp1251")
    m = re.search(r'#define\s+ROAM_IND_SPARE\s+"([^"]*)"', h)
    check(m is not None, "A4: ROAM_IND_SPARE знайдено")
    val = m.group(1) if m else ""
    check(indicator_ok(val, ua), "A4: ROAM_IND_SPARE %r -- ASCII з гліфами в 16x32" % val)
    check(not indicator_ok("Р>", ua), "A4: мутант «кирилична Р» ловиться")
    check(not indicator_ok("\xd0>", ua), "A4: мутант «0xD0» ловиться")
    check(val.startswith("R") and val.endswith(">"), "A4: індикатор -- «R>»")
    rui = open(os.path.join(INC, "user_interface", "roam_ui.h"), encoding="utf-8", errors="replace").read()
    m2 = re.search(r'#define\s+ROAM_IND_SPARE\s+"([^"]*)"', rui)
    check(m2 is not None and m2.group(1) == val, "A4: англійський варіант збігається з українським")

    section_b()
    section_c()
    section_d()
    print("test_r66: %d перевірок, провалів %d" % (PASSED[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
