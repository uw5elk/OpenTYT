#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX6 (хост): «Подвійний прийом» -- шапка без стокових полів, переходи звичайний режим <-> DW без зміни каналу/VFO, виділення обраної картки, 4 рядки.
  А   СПРАВЖНІ uiUtilityRenderHeader() (маршрутизація на шапку режиму), uiChannelModeDualHeader(), dualRenderHeader() + модель джерел (тік RSSI у паузі,
      headerRowIsDirty: CC/заряд/потужність, RedrawHeaderOnly, UpdateScreen): у DW -- лише шапка режиму; мутанти «стокова шапка при зміні CC / у паузі»
  Б   СПРАВЖНІ dualStart()/dualLeaveOnB()/dualDisable()/dualApplyReturnA(): вхід не перестроює рацію, вихід -- на картці з її правками, без проміжного каналу
  В/Г СПРАВЖНІ dualRenderRow()/dualMeterRow()/... + lcDistArrowAfter(): рамка обраної (2 px, колір виділення) / необраної (1 px, декор), 4 рядки, кожен
      примітив -- у своєму елементі, елементи не перетинаються, усе в полі вмісту; знімки PNG через screen_sim (справжні шрифти прошивки)
  Е   CPS: блок 18 переживає розбір / файл налаштувань / запис області байт-у-байт; опис формату
Запуск: python3 tools/test_r98fix6.py [--png КАТАЛОГ]"""
import os, re, shutil, struct, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
T.COMPAT_A_CHANNEL = False
T.COMPAT_FIX4 = False
T.COMPAT_FIX5 = False
import test_r98fix5 as F5  # noqa  (гарнеси й допоміжні; F5 знову вимикає compat -- для цього файлу те саме)
T.COMPAT_FIX5 = False
cmt = T.cmt
FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
run_c = F5.run_c; kv = F5.kv

# ------------------------------------------------------------------------------------------------ А: шапка
HDR_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
enum { UI_CHANNEL_MODE = 3, UI_VFO_MODE = 4 };
static char lg[200]; static int menu = UI_CHANNEL_MODE, shown = 1;
#define L(s) do { if (lg[0]) strcat(lg, ","); strcat(lg, s); } while (0)
static int menuSystemGetCurrentMenuNumber(void) { return menu; }
static bool uiChannelModeDualScreenShown(void) { return shown; }
static void uiUtilityRenderHeaderDw(bool f) { (void)f; L("DW"); }
static void uiUtilityRenderHeaderCore(bool a, bool b, bool f, void *ov) { (void)a; (void)b; (void)f; (void)ov; L("STOCK"); }
@@FNS@@
/* модель джерел шапки (applicationMain.c headerRowIsDirty, тік RSSI uiChannelMode(), uiUtilityRedrawHeaderOnly, UpdateScreen) -- як у коді */
static void srcHeaderDirty(void) { if ((menu == UI_CHANNEL_MODE) && uiChannelModeDualHeader(false)) { } else { uiUtilityRenderHeader(false, false, false); } }
static void srcRssiPaused(void) { uiUtilityRenderHeader(false, false, false); }
static void srcRedrawOnly(void) { if ((menu == UI_CHANNEL_MODE) && uiChannelModeDualScreenShown()) { uiChannelModeDualRenderHeader(false); } else { uiUtilityRenderHeader(false, false, false); } }
static void srcScreen(void) { dualRenderHeader(false); }
int main(void)
{
	lg[0] = 0; srcHeaderDirty(); printf("h1=%s\n", lg);   /* зміна CC (HR-C6000), заряд, потужність -- headerRowIsDirty */
	lg[0] = 0; srcRssiPaused(); printf("h2=%s\n", lg);    /* тік RSSI у паузі (прийом / утримання в режимі) */
	lg[0] = 0; srcRedrawOnly(); printf("h3=%s\n", lg);    /* uiUtilityRedrawHeaderOnly (потужність SK2+▲/▼, сповіщення) */
	lg[0] = 0; srcScreen(); printf("h4=%s\n", lg);        /* кадр екрана режиму */
	shown = 0; lg[0] = 0; srcHeaderDirty(); srcRssiPaused(); printf("h5=%s\n", lg); shown = 1;   /* екрана режиму нема -- стокова */
	menu = UI_VFO_MODE; lg[0] = 0; srcRssiPaused(); printf("h6=%s\n", lg); menu = UI_CHANNEL_MODE;   /* інший екран -- стокова */
	return 0;
}
"""


def test_header(t, tu, src, am):
    fr = T.carve_fn(tu, "void uiUtilityRenderHeader(_Bool isVFODualWatchScanning, _Bool isVFOSweepScanning, _Bool forceBatteryDisplay)")
    fh = T.carve_fn(t, "_Bool uiChannelModeDualHeader(_Bool force)")
    fd = T.carve_fn(t, "static void dualRenderHeader(_Bool force)")
    fo = T.carve_fn(t, "void uiChannelModeDualRenderHeader(_Bool force)")
    check(all((fr, fh, fd, fo)), "А: uiUtilityRenderHeader / uiChannelModeDualHeader / dualRenderHeader знайдено")
    if not all((fr, fh, fd, fo)):
        return
    code = lambda fs: HDR_HARNESS.replace("@@FNS@@", "\n".join(fs))
    o = kv(run_c(code([fd, fo, fh, fr])))
    exp = {"h1": "DW", "h2": "DW", "h3": "DW", "h4": "DW", "h5": "STOCK,STOCK", "h6": "STOCK"}
    check(o == exp, "А2: на екрані режиму шапку малює лише шапка режиму («DW», заряд, час) з усіх джерел; поза ним -- стокова: %s" % o)
    m = re.sub(r"\{\s*if \(\(menuSystemGetCurrentMenuNumber\(\) == UI_CHANNEL_MODE\) && uiChannelModeDualScreenShown\(\)\)\s*\{\s*uiUtilityRenderHeaderDw\(forceBatteryDisplay\);\s*return;\s*\}", "{", fr)
    mo = kv(run_c(code([fd, fo, fh, m])))
    check(m != fr and mo.get("h2") == "STOCK", "А3 (мутант): без маршрутизації тік RSSI у паузі (прийом) малює стокову шапку -- ловиться")
    mh = fh.replace("if (uiChannelModeDualScreenShown() == 0)", "if (1)")
    mo = kv(run_c(code([fd, fo, mh, m])))
    check(mh != fh and mo.get("h1") == "STOCK", "А3 (мутант): стокова шапка при зміні CC (headerRowIsDirty) -- ловиться")
    # статика: усі викликачі стокової шапки в uiChannelMode/applicationMain ідуть через uiUtilityRenderHeader (маршрутизація)
    calls = re.findall(r"uiUtilityRenderHeaderCore\(", src + am)
    check(calls == [], "А1: uiChannelMode.c / applicationMain.c не кличуть ядро шапки напряму (лише через маршрутизацію)")
    uu = T.rd(os.path.join(UI, "uiUtilities.c"))
    core_calls = [m.start() for m in re.finditer(r"uiUtilityRenderHeaderCore\(", uu)]
    check(len(core_calls) == 4, "А1: ядро шапки викликають лише uiUtilityRenderHeader (маршрутизація), ...ForChannel і ...Dw (+ визначення): %d" % len(core_calls))


# ------------------------------------------------------------------------------------------------ Б: переходи
TR_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
typedef struct { char name[16]; uint32_t rxFreq; uint32_t txFreq; uint8_t chMode; uint8_t libreDMR_Power; } CodeplugChannel_t;
typedef struct { int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_indexNumber; uint16_t channels[8]; } CodeplugZone_t;
typedef uint16_t (*dcChanAt_t)(int pos, void *ctx);
enum { SCAN_TYPE_NORMAL_STEP = 0, SCAN_TYPE_DUAL_CHANNEL = 5, SCAN_STATE_SCANNING = 0, SCAN_STATE_PAUSED = 2, QSO_DISPLAY_DEFAULT_SCREEN = 1, NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2 };
#define SETTINGS_CHANNEL_MODE 0
struct { int16_t currentZone; int16_t currentIndexInTRxGroupList[3]; uint8_t scanDelay; } nonVolatileSettings;
struct { struct { bool active; int scanType; int state; bool lastIteration; int direction; int stepTimeMilliseconds; struct { int timeout; } timer; } Scan; int displayQSOState; bool talkaround; } uiDataGlobal;
struct { char dual_zone_all[16]; } lang, *currentLanguage = &lang;
static CodeplugZone_t currentZone; static CodeplugChannel_t channelScreenChannelData, scanNextChannelData, chans[20], *currentChannelData = &channelScreenChannelData;
static int directChannelNumber = 0, onB = 0, ptrB = 0, bVfo = 0, aVfo = 0, running = 0, chB = 7, lastUsed = -99, freqReset = 0, enabled = 1;
static bool scanNextChannelReady; static int16_t s_dualTgIdxA; static uint8_t s_dualTgIdxB, s_dualBKeep;
static char lg[300];
#define L(...) do { char b_[32]; snprintf(b_, sizeof(b_), __VA_ARGS__); if (lg[0]) strcat(lg, ","); strcat(lg, b_); } while (0)
@@SETTERS@@
static void voicePromptsTerminate(void) {}
static bool voicePromptsIsPlaying(void) { return false; }
static int settingsGetScanStepTimeMilliseconds(void) { return 100; }
static void dualSetDwell(void) { L("dwell"); }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
static void dualTune(bool b) { L("T%d", b); if (b && !bVfo) { if (!(onB && currentChannelData == &channelScreenChannelData)) { channelScreenChannelData = chans[chB]; if (s_dualBKeep) channelScreenChannelData.libreDMR_Power = 5; } currentChannelData = &channelScreenChannelData; } onB = b; }
static bool dualBufHoldsB(void) { return (onB && (currentChannelData == &channelScreenChannelData)); }
static void dcSetOnB(bool b) { onB = b; }
static bool dcIsOnB(void) { return onB; }
static uint16_t dcChannelB(void) { return (uint16_t)chB; }
static void lastHeardClearLastID(void) {}
static uint16_t dualZoneChannelAt(int pos, void *ctx) { (void)ctx; return (pos >= 0 && pos < currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone) ? currentZone.channels[pos] : 0; }
static int dcFindPos(int n, uint16_t ch, dcChanAt_t at, void *ctx) { for (int i = 0; i < n; i++) if (at(i, ctx) == ch) return i; return -1; }
static void codeplugSetLastUsedChannelInZone(int z, int16_t p) { (void)z; lastUsed = p; }
static int codeplugZonesGetCount(void) { return 3; }
static void uiChannelInitializeCurrentZone(void) { currentZone.NOT_IN_CODEPLUGDATA_indexNumber = -1; L("zoneAll"); }
static void uiNotificationShow(int a, int b, unsigned t, const char *s, bool f) { (void)a; (void)b; (void)t; (void)s; (void)f; }
static void uiChannelModeLoadChannelData(bool mem, bool x) { (void)x; L("load%d", mem); }
static void freqEnterReset(void) { freqReset++; }
static bool dualSelectedIsB(void) { return ptrB; }
static uint8_t dcTypeA(void) { return aVfo; }
static bool dcAIsVfo(void) { return aVfo; }
static uint16_t dualChannelA(void) { return 3; }
static bool dcBIsVfo(void) { return bVfo; }
static void dcSetTxHold(bool b) { (void)b; }
static bool dcDisableWithReturnA(uint8_t t, uint16_t i) { (void)t; (void)i; enabled = 0; L("off"); return true; }
static bool dcSetEnabled(bool e, bool n) { (void)n; enabled = e; L("off"); return true; }
static void dualLeaveOnVfo(uint8_t v) { L("vfo%d", v); }
static uint8_t dualVfoIdx(void) { return 1; }
static uint8_t dualCardVfo(bool b) { (void)b; return 0; }
static bool dualIsRunning(void) { return running; }
static void dualSuspend(void) { L("S"); }
static bool dcSameTarget(uint8_t a, uint16_t b, uint8_t c, uint16_t d) { return (a == c) && (a != 0 || b == d); }
static uint8_t dcTypeB(void) { return bVfo ? 2 : 0; }
static bool codeplugAllChannelsIndexIsInUse(int c) { return c > 0 && c < 20; }
static void dcSetPointerB(bool b) { ptrB = b; }
static void dcSetTypeA(uint8_t t) { (void)t; }
static void codeplugChannelGetDataForIndex(int i, CodeplugChannel_t *c) { *c = chans[i]; }
@@FNS@@
static void setup(void) { lg[0] = 0; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = 3; currentZone.NOT_IN_CODEPLUGDATA_indexNumber = 0; currentZone.channels[0] = 3; currentZone.channels[1] = 7; currentZone.channels[2] = 9;
	for (int i = 0; i < 20; i++) { memset(&chans[i], 0, sizeof(chans[i])); chans[i].name[0] = 'a' + i; chans[i].rxFreq = 100 + i; chans[i].libreDMR_Power = 1; }
	channelScreenChannelData = chans[3]; currentChannelData = &channelScreenChannelData; onB = 0; ptrB = 0; bVfo = 0; aVfo = 0; running = 1; chB = 7; lastUsed = -99; directChannelNumber = 0; freqReset = 0; s_dualBKeep = 0; s_dualTgIdxB = 0; enabled = 1; }
int main(void)
{
	/* b1: вхід (старт чергування) -- рація не перестроюється (раніше: спершу на A) */
	setup(); onB = 1; dualStart(false); printf("b1=%s,onB%d\n", lg, onB);
	/* b2: вихід на обраній B, рація на A (чергування за покажчиком): спершу прямо на B (копія з правками), «останній канал зони» = позиція B, завантаження з пам'яті */
	setup(); ptrB = 1; s_dualBKeep = 1; dualLeaveOnB(); printf("b2=%s,last%d,pwr%d\n", lg, lastUsed, channelScreenChannelData.libreDMR_Power);
	/* b3: вихід на B, рація вже на B -- без повторного налаштування */
	setup(); ptrB = 1; dualTune(1); lg[0] = 0; dualLeaveOnB(); printf("b3=%s\n", lg);
	/* b4: B з іншої зони -- «Всі канали», номер = B */
	setup(); ptrB = 1; chB = 15; dualLeaveOnB(); printf("b4=%s,last%d\n", lg, lastUsed);
	/* b5: вихід під час набору цифр -- набір скасовано (не потрапляє в стоковий набір звичайного екрана) */
	setup(); ptrB = 0; running = 0; directChannelNumber = 12; dualDisable(); printf("b5=%d,%d,%s\n", directChannelNumber, freqReset, lg);
	/* b6: вихід на обраній A (канал), чергування -- зупинка на A, рація не перестроюється повторно */
	setup(); ptrB = 0; dualDisable(); printf("b6=%s\n", lg);
	/* b7: вхід з «A для повернення», рація на B (поточна ціль == B): копія B = те, що в буфері (правки звичайного режиму), ТГ B = поточний */
	setup(); onB = 0; currentChannelData = &channelScreenChannelData; channelScreenChannelData = chans[7]; nonVolatileSettings.currentIndexInTRxGroupList[0] = 2;
	{ bool r = dualApplyReturnA(0, 3); printf("b7=%d,onB%d,ptr%d,keep%d,tgB%d,tgA%d\n", r, onB, ptrB, s_dualBKeep, s_dualTgIdxB, s_dualTgIdxA); }
	return 0;
}
"""


def test_transitions(t):
    sigs = ["static _Bool dualStart(_Bool holdCurrent)", "static void dualLeaveOnB(void)", "static void dualDisable(void)", "static _Bool dualApplyReturnA(uint8_t rt, uint16_t ri)"]
    fns = [T.carve_fn(t, s) for s in sigs]
    check(all(fns), "Б: dualStart / dualLeaveOnB / dualDisable / dualApplyReturnA знайдено")
    if not all(fns):
        return
    code = lambda f: TR_HARNESS.replace("@@SETTERS@@", F5.SETTERS).replace("@@FNS@@", "\n".join(f))
    out = run_c(code(fns))
    o = kv(out)
    exp = {"b1": "dwell,onB1", "b2": "T1,load1,last1,pwr5", "b3": "load1", "b4": "T1,zoneAll,load1,last15", "b5": "0,1,off", "b6": "S,off", "b7": "1,onB1,ptr1,keep1,tgB2,tgA2"}
    names = {"b1": "вхід: чергування стартує з картки, на якій рація стоїть (без стрибка на A)",
             "b2": "вихід на B, рація на A: спершу прямо на B (робоча копія з правками -- потужність 5), «останній канал зони» = позиція B, завантаження з пам'яті (не з кодплага)",
             "b3": "вихід на B, рація на B: без повторного налаштування", "b4": "вихід на B з іншої зони: «Всі канали», номер = B",
             "b5": "вихід під час набору: набір скасовано", "b6": "вихід на A: зупинка на A",
             "b7": "вхід з «A для повернення» (рація на B): лишається на B, копія B = буфер (правки звичайного режиму), ТГ B = поточний"}
    for k, v in exp.items():
        check(o.get(k) == v, "Б (%s): %s -- очікувано %s, є %s" % (k, names[k], v, o.get(k)))
    muts = ((0, "вхід стрибає на A (стара поведінка)", "b1", fns[0].replace("dualSetDwell();\n }\n uiDataGlobal.displayQSOState", "if (dcIsOnB()) { dualTune(0); }\n  dualSetDwell();\n }\n uiDataGlobal.displayQSOState")),
            (1, "вихід на B перечитує кодплаг (правки губляться)", "b2", fns[1].replace("uiChannelModeLoadChannelData(1, 0);", "uiChannelModeLoadChannelData(0, 0);")),
            (1, "вихід на B не переходить на B (рація лишається на A)", "b2", re.sub(r"if \(dualBufHoldsB\(\) == 0\)\s*\{\s*dualTune\(1\);\s*\}", "", fns[1])),
            (2, "набір не скасовується", "b5", re.sub(r"if \(directChannelNumber != 0\)\s*\{\s*directChannelNumber = 0;\s*freqEnterReset\(\);\s*\}", "", fns[2])),
            (3, "копія B не береться з буфера", "b7", fns[3].replace("s_dualBKeep = 1U;", "")))
    for idx, what, key, m in muts:
        f2 = list(fns); f2[idx] = m
        mo = kv(run_c(code(f2)))
        check(m != fns[idx] and mo.get(key) not in (None, exp[key]), "Б (мутант): %s -- ловиться" % what)


# ------------------------------------------------------------------------------------------------ В/Г: розкладка
ROW_HARNESS = F5.ROW_HARNESS
ROW_HARNESS = ROW_HARNESS.replace("enum { THEME_ITEM_FG_DECORATION, THEME_ITEM_BG, THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_FG_CHANNEL_CONTACT, THEME_ITEM_FG_CHANNEL_CONTACT_INFO, THEME_ITEM_FG_DEFAULT, THEME_ITEM_FG_RSSI_BAR, THEME_ITEM_FG_RSSI_BAR_S9P };",
                                  "enum { THEME_ITEM_FG_DECORATION, THEME_ITEM_BG, THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_FG_CHANNEL_CONTACT, THEME_ITEM_FG_CHANNEL_CONTACT_INFO, THEME_ITEM_FG_DEFAULT, THEME_ITEM_FG_RSSI_BAR, THEME_ITEM_FG_RSSI_BAR_S9P, THEME_ITEM_BG_MENU_ITEM_SELECTED };\n"
                                  "static const char *THN[] = { \"FG_DECORATION\", \"BG\", \"FG_CHANNEL_NAME\", \"FG_CHANNEL_CONTACT\", \"FG_CHANNEL_CONTACT_INFO\", \"FG_DEFAULT\", \"FG_RSSI_BAR\", \"FG_RSSI_BAR_S9P\", \"BG_MENU_ITEM_SELECTED\" };\nstatic int curFg = 0, curBg = 1;")
ROW_HARNESS = ROW_HARNESS.replace("typedef struct { int x, y, w, h; char kind; char txt[24]; int inv; } prim_t;", "typedef struct { int x, y, w, h; char kind; char txt[24]; int inv; int fg, bg, font; } prim_t;")
ROW_HARNESS = ROW_HARNESS.replace("pr[np].inv = inv; snprintf", "pr[np].inv = inv; pr[np].fg = curFg; pr[np].bg = curBg; pr[np].font = 0; snprintf")
ROW_HARNESS = ROW_HARNESS.replace("void displayThemeApply(int a, int b) { (void)a; (void)b; }", "void displayThemeApply(int a, int b) { curFg = a; curBg = b; }")
ROW_HARNESS = ROW_HARNESS.replace("void displayThemeResetToDefault(void) {}", "void displayThemeResetToDefault(void) { curFg = THEME_ITEM_FG_DEFAULT; curBg = THEME_ITEM_BG; }")
ROW_HARNESS = ROW_HARNESS.replace("(void)al; if (t[0]) add('T', x, y, (int)strlen(t) * w, h, t, inv); return 0; }", "(void)al; if (t[0]) { add('T', x, y, (int)strlen(t) * w, h, t, inv); pr[np - 1].font = f; } return 0; }")
ROW_HARNESS = ROW_HARNESS.replace('printf("%s%c:%d:%d:%d:%d:%d:%s", i ? ";" : "", pr[i].kind, pr[i].x, pr[i].y - y, pr[i].w, pr[i].h, pr[i].inv, pr[i].txt);',
                                  'printf("%s%c:%d:%d:%d:%d:%d:%s:%d:%s", i ? ";" : "", pr[i].kind, pr[i].x, pr[i].y - y, pr[i].w, pr[i].h, pr[i].inv, THN[pr[i].fg], pr[i].font, pr[i].txt);')
# сценарії FIX6 (замість сценаріїв FIX5)
_MAIN_A = ROW_HARNESS.index("	/* a1: картка A")
_MAIN_B = ROW_HARNESS.index("	return 0;\n}", _MAIN_A)
ROW_HARNESS = ROW_HARNESS[:_MAIN_A] + r"""	/* назви -- реалістичні (латиниця, як у кодплагах): канал 39 «R2 Kyiv 145.7» (13 символів), канал 5 «Brandmeister 91» */
	memset(chans[39].name, ' ', 16); memcpy(chans[39].name, "R2 Kyiv 145.7", 13); memset(chans[5].name, ' ', 16); memcpy(chans[5].name, "Brandmeister 91", 15);
	memset(chans[11].name, ' ', 16); memcpy(chans[11].name, "Simplex FM", 10); memset(chans[12].name, ' ', 16); memcpy(chans[12].name, "UR0LL repeater", 14);
	chans[12].chMode = RADIO_MODE_ANALOG; chans[12].rxFreq = 14560000U; chans[12].rxTone = 885; chans[12].txTone = 885; chans[12].flags = CHANNEL_FLAG_BW_25K;
	chans[39] = chans[5]; memset(chans[39].name, ' ', 16); memcpy(chans[39].name, "R2 Kyiv 145.7", 13); chans[39].encrypt = 0;
	chans[13] = chans[5]; memset(chans[13].name, ' ', 16); memcpy(chans[13].name, "Long name 16 chr", 16); chans[13].encrypt = 1;
	channelScreenChannelData = chans[39];
	/* s1: чергування, обидві картки канали; обрана A, неактивні обидві */
	ROW("s1a", 11, false, 39, 0, true, false, false); ROW("s1b", 71, true, 12, 0, false, false, false);
	/* s2: прийом DMR на A -- абонент, відстань і стрілка, S-метр */
	own = 1; known = 1; rssi = -70; strcpy(item.contact, "ID:2550213"); strcpy(item.talkerAlias, "UR5EQF Bogdan"); strcpy(item.talkgroup, "TG 91234567");
	ROW("s2a", 11, false, 39, 0, true, true, true); ROW("s2b", 71, true, 12, 0, false, false, false);
	/* s3: прийом FM на B (обрана B -- активність), сильний сигнал (червоні сегменти) */
	rssi = -60; ROW("s3a", 11, false, 39, 0, false, false, false); ROW("s3b", 71, true, 12, 0, true, true, false);
	/* s4: B = VFO B (DMR), конверти «D» (на A і на B) і APRS «A» (на B), замок на A, довга назва A */
	unD[0] = 3; unD[1] = 2; unA = 12; rssi = -200;
	ROW("s4a", 11, false, 13, 0, false, false, false); ROW("s4b", 71, true, 0, 2, true, false, false);
	/* s5: набір цифр на B (покажчик на B) */
	unD[0] = unD[1] = 0; unA = 0; ptrB = 1; directChannelNumber = 12; ROW("s5a", 11, false, 39, 0, false, false, false); ROW("s5b", 71, true, 12, 0, true, false, false); directChannelNumber = 0; ptrB = 0;
	/* s6: найгірший рядок 1: довга назва + усі три значки (замок, APRS, D) на B = канал з ключем */
	unD[1] = 9; unA = 3; ROW("s6b", 71, true, 13, 0, false, false, false); unD[1] = 0; unA = 0;
	/* s7: виклик без азимуту -- відстань без стрілки */
	known = 0; ROW("s7a", 11, false, 39, 0, true, true, true); known = 1;
""" + ROW_HARNESS[_MAIN_B:]

ROW_SIGS = ["static Channel_t dualChanOf(const CodeplugChannel_t *ch)", "static void dualCallerText(char *text17)", "static void dualMeterRow(int16_t y)",
            "static uint32_t dualDestination(const CodeplugChannel_t *ch, char *out, _Bool *numOnly, uint8_t *tsFlags, int16_t tgIdx)",
            "static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags)", "static size_t dualToneOne(char *dst, size_t size, const char *mark, uint16_t tone)",
            "static void dualFmToneLine(char *l3, size_t size, uint16_t rxTone, uint16_t txTone, _Bool bw25)",
            "static void dualModePowerText(char *out, size_t size, const CodeplugChannel_t *rec)",
            "static _Bool dualDistText(char *out, size_t size, _Bool callerHere, uint16_t *bearing, _Bool *bearingKnown)",
            "static const CodeplugChannel_t *dualCardMem(_Bool isB, const CodeplugChannel_t *tmp)", "static int16_t dualCardTgIdx(_Bool isB, uint8_t vfoType)",
            "static void dualRenderRow(int16_t y, _Bool isB, uint16_t ch, uint8_t vfoType, _Bool selected, _Bool active, _Bool callerHere)"]


def prims_of(line):
    out = []
    for it in (line or "").split(";"):
        f = it.split(":", 8)
        if len(f) == 9:
            out.append({"k": f[0], "x": int(f[1]), "y": int(f[2]), "w": int(f[3]), "h": int(f[4]), "inv": int(f[5]), "fg": f[6], "font": int(f[7]), "t": f[8]})
    return out


def box(p):
    return (p["x"], p["y"], p["x"] + p["w"] - 1, p["y"] + p["h"] - 1)


def union(bs):
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def elements(D, ps):
    """Кожен примітив -> рівно один елемент картки (за правилами розкладки з констант); повертає (елементи {назва: [примітиви]}, нерозпізнані)."""
    el = {}; bad = []
    unx = [p["x"] for p in ps if p["k"] == "T" and p["t"] == "D" and p["font"] == 1]
    unx = unx[0] if unx else None
    for p in ps:
        b = box(p)
        if p["k"] == "r" and p["w"] >= 150:
            name = "frame"
        elif p["k"] in "fr" and p["x"] == D["DW_IN_L"] and p["w"] == D["DW_LET_W"] and p["y"] == D["DW_ROW1_DY"]:
            name = "letter"
        elif p["k"] == "T" and p["t"] in ("A", "B") and p["font"] == 3 and p["x"] == D["DW_LET_X"]:
            name = "letter"
        elif p["k"] == "k":
            name = "lock"
        elif (p["k"] == "f" and p["w"] == D["DW_AP_W"] and p["h"] == D["DW_AP_H"]) or (p["k"] == "T" and p["inv"] == 1 and p["t"][:1] == "A" and p["font"] == 1 and p["y"] < D["DW_ROW2_DY"]):
            name = "aprs"
        elif unx is not None and p["y"] < D["DW_ROW2_DY"] and unx <= p["x"] <= unx + D["DW_UN_W"] - 1 and p["k"] in "Trl":
            name = "D"
        elif p["k"] == "T" and p["font"] == 3 and p["y"] == D["DW_ROW1_DY"]:
            name = "row1"
        elif p["k"] == "T" and p["font"] == 3 and p["y"] == D["DW_ROW2_DY"]:
            name = "row2"
        elif p["k"] == "T" and p["y"] == D["DW_ROW3_DY"]:
            name = "row3L" if p["x"] == D["DW_IN_L"] else "row3R"
        elif p["k"] in "tl" and p["y"] >= D["DW_ARROW_DY"] and b[3] <= D["DW_ARROW_DY"] + D["DW_ARROW_CELL"] - 1:
            name = "arrow"
        elif p["y"] >= D["DW_ROW4_DY"]:
            name = "meter"
        else:
            bad.append(p); continue
        el.setdefault(name, []).append(p)
    return el, bad


def analyse(D, line):
    ps = prims_of(line)
    el, bad = elements(D, ps)
    boxes = {}
    for k, v in el.items():
        if k == "frame":
            continue
        boxes[k] = union([box(p) for p in v])
    if "arrow" in boxes:   # комірка стрілки 10x10
        x0, y0, x1, y1 = boxes["arrow"]
        cx = (x0 + x1) // 2
        boxes["arrow"] = (cx - 5, D["DW_ARROW_DY"], cx + 4, D["DW_ARROW_DY"] + D["DW_ARROW_CELL"] - 1)
    if "meter" in boxes:
        boxes["meter"] = (D["DW_IN_L"], D["DW_ROW4_DY"], D["DW_IN_R"], D["DW_ROW4_DY"] + D["DW_METER_H"] - 1)
    names = sorted(boxes)
    ov = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if not F5.disjoint(boxes[a], boxes[b])]
    out = [k for k, b in boxes.items() if b[0] < D["DW_IN_L"] or b[2] > D["DW_IN_R"] or b[1] < D["DW_ROW1_DY"] or b[3] > D["DW_ROW4_DY"] + D["DW_METER_H"] - 1]
    txt = {k: [p["t"] for p in v if p["k"] == "T"] for k, v in el.items()}
    return ps, el, boxes, bad, ov, out, txt


def snapshots(D, o, png_dir):
    """Г4: PNG через screen_sim (справжні шрифти прошивки з HX8353E_charset_UA.h, стокова денна тема). Шапка -- як uiUtilityRenderHeaderDw («DW», заряд, час);
    замок AES -- спрощений контур 10x9 (справжній значок малює uiDrawAesIconAt, у моделі його бітмапа нема)."""
    import screen_sim as sim
    import theme_edit as te
    colors = te.stock_colors("day")
    try:
        from PIL import Image
    except ImportError:
        print("ПРОПУСК: PIL нема -- PNG не згенеровано"); return
    states = (("1", "s1a", "s1b"), ("2", "s2a", "s2b"), ("3", "s3a", "s3b"), ("4", "s4a", "s4b"), ("5", "s5a", "s5b"))
    FONT = {1: sim.FONT_1, 3: sim.FONT_3}
    for n, ka, kb in states:
        d = sim.Display()
        d.theme_apply(sim.IT["FG_HEADER_TEXT"], sim.IT["BG_HEADER_TEXT"]); d.fill_rect(0, 0, 160, 10, True)
        d.print_core(1, 2, "DW", sim.FONT_1, sim.ALIGN_LEFT, False)
        d.print_core(160 - 30 - 3 - 18, 2, "87%", sim.FONT_1, sim.ALIGN_LEFT, False)
        d.print_core(160 - 30, 2, "12:34", sim.FONT_1, sim.ALIGN_LEFT, False)
        for key, y0 in ((ka, D["DW_CARD_A_Y"]), (kb, D["DW_CARD_B_Y"])):
            for p in prims_of(o.get(key)):
                d.theme_apply(sim.IT[p["fg"]], sim.IT["BG"])
                x, y = p["x"], p["y"] + y0
                if p["k"] == "T":
                    d.print_core(x, y, p["t"], FONT.get(p["font"], sim.FONT_1), sim.ALIGN_LEFT, bool(p["inv"]))
                elif p["k"] == "f":
                    d.fill_rect(x, y, p["w"], p["h"], bool(p["inv"]))
                elif p["k"] == "r":
                    d.draw_rect(x, y, p["w"], p["h"], bool(p["inv"]))
                elif p["k"] == "l" and p["y"] < D["DW_ARROW_DY"]:
                    d.draw_line(x, y, x + p["w"] - 1, y + p["h"] - 1, True)   # лінії конверта (горизонтальні/похилі -- як у прошивці, з кутів прямокутника)
                elif p["k"] == "k":
                    d.theme_apply(sim.IT["FG_CHANNEL_NAME"], sim.IT["BG"])
                    d.draw_rect(x, y + 3, 10, 6, True); d.draw_rect(x + 2, y, 6, 4, True)
            arr = [p for p in prims_of(o.get(key)) if p["k"] == "t"]
            if arr:   # стрілка: справжня геометрія aprsChevronGeom (screen_views.chevron_geom), центр комірки, азимут сценарію 45°
                cx = (min(p["x"] for p in arr) + max(p["x"] + p["w"] - 1 for p in arr)) // 2
                cy = (min(p["y"] for p in arr) + max(p["y"] + p["h"] - 1 for p in arr)) // 2 + y0
                import screen_views as sv
                tip, lft, rgt, notch = sv.chevron_geom(cx, cy, 4, 45)
                d.theme_apply(sim.IT["FG_CHANNEL_CONTACT_INFO"], sim.IT["BG"])
                d.fill_triangle(tip[0], tip[1], lft[0], lft[1], notch[0], notch[1], True)
                d.fill_triangle(tip[0], tip[1], rgt[0], rgt[1], notch[0], notch[1], True)
        img = Image.frombytes("RGB", (160, 128), sim.render_rgb(d, colors)).resize((480, 384), Image.NEAREST)
        path = os.path.join(png_dir, "R98FIX6-%s.png" % n)
        img.save(path)
        print("PNG: %s" % path)


# ------------------------------------------------------------------------------------------------ Е: CPS
def test_cps():
    import custom_region as cr
    payload = bytes([1, 0x03, 0x2A, 0x01, 2, 0x0D, 0x05, 0x00])   # увімкнено + покажчик B, B = 298, тип B = VFO B, A = VFO A, «A для повернення» = VFO B... номер 5
    other = bytes(range(16))
    blocks = [(4, other * 4), (18, payload), (17, b"\x01")]
    data = bytearray(b"\xff" * cr.REGION_LEN)
    data[:8] = cr.MAGIC
    data[8:12] = b"\x00\x00\x00\x00"
    addr = cr.REGION_HDR
    for tp, pl in blocks:
        data[addr:addr + 8] = struct.pack("<ii", tp, len(pl)); data[addr + 8:addr + 8 + len(pl)] = pl; addr += 8 + len(pl)
    r = cr.parse_region(bytes(data))
    b18 = [b for b in r.blocks if b.type == 18]
    check(not r.problems and b18 and b18[0].payload == payload, "Е1: розбір області: блок 18 (8 Б: тип B, біти типу A і «A для повернення», номер) -- байт-у-байт")
    txt = cr.settings_to_text(r.blocks)
    back = cr.settings_from_text(txt)
    bb = [b for b in (back if isinstance(back, list) else back[0]) if getattr(b, "type", None) == 18] if back else []
    check(bb and bb[0].payload == payload, "Е1: файл налаштувань (запис -> читання) -- блок 18 байт-у-байт")
    buf = bytearray(data)
    try:
        cr.simulate_write(buf, 18, payload)
        r2 = cr.parse_region(bytes(buf))
        ok = [b.payload for b in r2.blocks if b.type == 18] == [payload]
    except Exception as e:   # noqa
        ok = False; print(e)
    check(ok, "Е1: запис області (той самий алгоритм пошуку слота, що прошивка) -- блок 18 без змін")
    d18 = cr.BLOCK_TYPES[18][2]
    check("тип B" in d18 and "A для повернення" in d18 and "[6..7]" in d18, "Е2: опис блоку 18 у custom_region.py -- поточний формат (тип B, типи A, номер «A для повернення»)")
    dh = T.rd(os.path.join(APP, "include", "functions", "dual_channel.h"))
    check("[6..7] R98-FIX4: номер каналу «A для повернення»" in dh and "біти 2..3 -- тип «A для повернення»" in dh, "Е2/Д1: опис формату в dual_channel.h -- поточний")


def test_audit(src):
    used = lambda m: len(re.findall(r"\b%s\b" % m, src)) > 1
    unused = [m for m in re.findall(r"^#define (DW_\w+)", src, re.M) if not used(m)]
    check(unused == [], "Д1: невикористаних констант DW_* нема: %s" % unused)
    check("dualRow4Text" not in src and "dualAppendDistance" not in src and "DW_SQ_" not in src and "DW_LINE" not in src, "Д1: залишків старої розкладки (рядок 4/5, квадрат) нема")
    check("char num[24];" in src[src.find("static void dualRenderRow("):], "Д3: буфер числа ТГ/ID у рядку 3 -- з запасом під «PC»/«TG» будь-якої довжини мови")


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    global INCS, CF
    INCS, cfgs = cmt.load_configs(FW)
    CF = dict(cfgs)
    F5.INCS, F5.CF = INCS, CF
    png = None
    if "--png" in sys.argv:
        png = sys.argv[sys.argv.index("--png") + 1]
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    am = T.rd(os.path.join(APP, "source", "applicationMain.c"))
    t = T.pp(FW, INCS, CF["DUALCH"], "application/source/user_interface/uiChannelMode.c") or ""
    tu = T.pp(FW, INCS, CF["DUALCH"], "application/source/user_interface/uiUtilities.c") or ""
    check(t != "" and tu != "", "препроцесування uiChannelMode.c / uiUtilities.c (DUALCH)")
    test_header(t, tu, src, am)
    test_transitions(t)
    test_cps()
    test_audit(src)
    print("test_r98fix6: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


INCS = None; CF = None

if __name__ == "__main__":
    sys.exit(main())
