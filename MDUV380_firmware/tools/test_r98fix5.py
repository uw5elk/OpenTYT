#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX5 (хост): «Подвійний прийом» -- єдина логіка керування, нова розкладка карток і шапки, стоковий «Dual Watch» VFO замінено нашим режимом.
  А   керування: СПРАВЖНІ dualHandleKey()/dualIsVfoStepKey()/dualIsSquelchKey() (таблиця клавіш у режимі) і блок режиму з handleEventCore() (клавіші-параметри --
      на картку з покажчиком); СПРАВЖНІ dualTune()/dualSquelchStep()/channelTgStep()/dualCardTgIdx() -- ТГ A і B незалежні, переживають цикли A<->B, PTT іде з ТГ
      картки; робоча копія B (правки B живуть, як правки A); SK2 + ручка на B -- перший канал наступної/попередньої зони (СПРАВЖНІ dualZoneStepB()/dualStepB()/
      codeplugZoneStep()/dcStepExt()/dcFindPos()); uiVFOModeDualTgStep(); dualVfoKeyDone() (ТС-перекриття картки VFO); мутанти
  Б   розкладка: СПРАВЖНІ dualRenderRow()/dualMeterRow()/dualRow4Text()/dualCardMem()/dualDestination()/... + lcDistArrowAfter(): кожен намальований елемент лежить
      рівно в одній зоні картки, зони не перетинаються (обидві картки, значки D і A разом, замок, відстань + стрілка, набір, VFO); шапка «DW»; мутанти
  В   стоковий Dual Watch: пункт меню запускає наш режим, двигун вирізано в збірці з режимом, без прапорця -- токени як у базі
Запуск: python3 tools/test_r98fix5.py"""
import os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
T.COMPAT_A_CHANNEL = False   # справжні функції
T.COMPAT_FIX4 = False        # без заморожених функцій R98-FIX4
cmt = T.cmt
FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
BASE = "7205514"   # HEAD після R98-FIX4 у дереві розробки (у клоні власника хеш інший -- тоді ПРОПУСК)


def base_available():
    return subprocess.run(["git", "cat-file", "-e", BASE + "^{commit}"], cwd=FW, capture_output=True).returncode == 0


def run_c(code):
    d = tempfile.mkdtemp(prefix="r98f5_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:3000]); return None
        return subprocess.run([os.path.join(d, "h")], capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def kv(out):
    return dict(l.split("=", 1) for l in (out or "").splitlines() if "=" in l)


SETTERS = r"""
#define GENS(T, N) static void settingsSet##N(T *p, T v) { *p = v; setCalls++; } static void settingsInc##N(T *p, T v) { *p = (T)(*p + v); setCalls++; } static void settingsDec##N(T *p, T v) { *p = (T)(*p - v); setCalls++; }
static int setCalls = 0;
static void settingsSetBOOL(_Bool *p, _Bool v) { *p = v; setCalls++; }
GENS(int8_t, INT8) GENS(uint8_t, UINT8) GENS(int16_t, INT16) GENS(uint16_t, UINT16) GENS(int32_t, INT32) GENS(uint32_t, UINT32)
"""

# ------------------------------------------------------------------------------------------------ А: ТГ A/B, робоча копія B
TUNE_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
typedef struct { char name[16]; uint32_t rxFreq; uint32_t txFreq; uint8_t chMode; uint8_t libreDMR_Power; uint8_t sql; uint8_t rxGroupList; uint16_t contact; } CodeplugChannel_t;
enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
#define SETTINGS_CHANNEL_MODE 0
#define SETTINGS_VFO_A_MODE 1
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 };
enum { MENU_STATUS_LIST_TYPE = 1, MENU_STATUS_FORCE_FIRST = 2 };
enum { UI_CHANNEL_MODE = 3 };
enum { MELODY_ERROR_BEEP = 1 };
enum { PROMPT_SEQUENCE_CONTACT_TG_OR_PC = 1, PROMPT_THRESHOLD_3 = 3, PROMPT_SQUENCE_SQUELCH = 4 };
enum { NOTIFICATION_TYPE_SQUELCH = 1, NOTIFICATION_ID_SQUELCH = 2 };
enum { TRX_RX_FREQ_BAND = 0 };
#define CODEPLUG_MAX_VARIABLE_SQUELCH 21
#define CODEPLUG_MIN_VARIABLE_SQUELCH 1
struct { int16_t currentIndexInTRxGroupList[3]; uint32_t overrideTG; uint8_t squelchDefaults[3]; } nonVolatileSettings;
struct { char name[16]; int NOT_IN_CODEPLUG_numTGsInGroup; } currentRxGroupData;
struct { int displayQSOState; int currentSelectedChannelNumber; } uiDataGlobal;
struct { int trxCurrentBand[2]; } radioDev, *currentRadioDevice = &radioDev;
static int menuChannelExitStatus;
@@SETTERS@@
static CodeplugChannel_t chans[20], settingsVFOChannel[2], channelScreenChannelData, scanNextChannelData, *currentChannelData = &channelScreenChannelData;
static int onB = 0, aVfo = 0, bVfo = 0, bVfoIdx = 0, chB = 7, ptrB = 0, single = 0, reads = 0, beep = 0, vfoTg = -99, vfoTgDir = 0, vfoDirty = 0, groupN[8], lastA = 3;
static int16_t s_dualTgIdxA; static uint8_t s_dualTgIdxB, s_dualBKeep;
static bool dcIsOnB(void) { return onB; }
static void dcSetOnB(bool b) { onB = b; }
static bool dcBIsVfo(void) { return bVfo; }
static bool dcAIsVfo(void) { return aVfo; }
static uint16_t dcChannelB(void) { return (uint16_t)chB; }
static bool dcPointerB(void) { return ptrB; }
static bool dualSingle(void) { return single; }
static uint8_t dualVfoIdx(void) { return (uint8_t)bVfoIdx; }
static uint8_t dualCardVfo(bool isB) { return (uint8_t)(isB ? bVfoIdx : 0); }
static bool dualOnVfoNow(void) { return onB ? bVfo : aVfo; }
static void dualSuspend(void) {}
static void lastHeardClearLastID(void) {}
static void dmrAesRxRetune(void) {}
static void codeplugChannelGetDataForIndex(int i, CodeplugChannel_t *c) { *c = chans[i]; reads++; }
static void setGroup(const CodeplugChannel_t *c) { currentRxGroupData.name[0] = (c->rxGroupList != 0) ? 'G' : 0; currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup = (c->rxGroupList != 0) ? groupN[c->rxGroupList] : 0; }
/* модель стокового uiChannelModeLoadChannelData(): mem == 0 -- канал зони з кодплага в буфер; список прийому каналу; індекс ТГ поза списком -> 0 */
static void uiChannelModeLoadChannelData(bool mem, bool x) { (void)x; if (!mem) { channelScreenChannelData = chans[lastA]; reads++; } setGroup(currentChannelData);
	int n = currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup; if ((n > 0) && (nonVolatileSettings.currentIndexInTRxGroupList[0] > (n - 1))) nonVolatileSettings.currentIndexInTRxGroupList[0] = 0; }
static void uiVFOModeDualLoad(uint8_t v, bool f) { (void)f; currentChannelData = &settingsVFOChannel[v]; setGroup(currentChannelData); }
static void uiVFOModeDualTgStep(uint8_t v, int d) { vfoTg = v; vfoTgDir = d; }
static void soundSetMelody(int m) { (void)m; beep++; }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
static void announceItem(int a, int b) { (void)a; (void)b; }
static void menuPrivateCallClear(void) {}
static void updateTrxID(void) {}
static bool isQSODataAvailableForCurrentTalker(void) { return false; }
static void uiUtilityRenderQSODataAndUpdateScreen(void) {}
static int addTimerCallback(void (*f)(void), int t, int m, bool r) { (void)f; (void)t; (void)m; (void)r; return 0; }
static void uiNotificationShow(int a, int b, int c, const char *d, bool e) { (void)a; (void)b; (void)c; (void)d; (void)e; }
static void settingsSetVFODirty(void) { vfoDirty++; }
static bool dualBufHoldsB(void) { return (dcIsOnB() && (currentChannelData == &channelScreenChannelData)); }
@@FNS@@
static void mk(int i, const char *nm, int mode, int grp, uint32_t f) { memset(&chans[i], 0, sizeof(chans[i])); memcpy(chans[i].name, nm, strlen(nm)); chans[i].rxFreq = f; chans[i].txFreq = f; chans[i].chMode = mode; chans[i].rxGroupList = grp; chans[i].libreDMR_Power = 1; }
static void setup(void)
{
	groupN[1] = 4; groupN[2] = 3; groupN[5] = 3;
	mk(3, "ChanA", RADIO_MODE_DIGITAL, 1, 43300000); mk(7, "ChanB", RADIO_MODE_DIGITAL, 2, 43400000); mk(9, "ChanFM", RADIO_MODE_ANALOG, 0, 14500000); mk(11, "NoList", RADIO_MODE_DIGITAL, 0, 43500000);
	settingsVFOChannel[1] = chans[7]; settingsVFOChannel[1].rxGroupList = 5; settingsVFOChannel[0] = chans[9];
	channelScreenChannelData = chans[3]; currentChannelData = &channelScreenChannelData; setGroup(currentChannelData);
	onB = 0; aVfo = 0; bVfo = 0; bVfoIdx = 0; chB = 7; ptrB = 0; single = 0; beep = 0; vfoTg = -99; vfoTgDir = 0; vfoDirty = 0;
	nonVolatileSettings.currentIndexInTRxGroupList[0] = 0; nonVolatileSettings.currentIndexInTRxGroupList[1] = 0; nonVolatileSettings.currentIndexInTRxGroupList[2] = 0; nonVolatileSettings.overrideTG = 0;
	s_dualTgIdxA = 0; s_dualTgIdxB = 0; s_dualBKeep = 0; memset(&scanNextChannelData, 0, sizeof(scanNextChannelData));
}
#define IDX nonVolatileSettings.currentIndexInTRxGroupList[0]
int main(void)
{
	/* t1: SK1 + ручка на B (DMR) двічі -> ТГ B = 2; цикли A<->B: на A індекс 0 (A не змінено), на B -- 2 (пережив цикли); потім SK1 + ручка на A -> A = 1, B лишився 2 */
	setup(); ptrB = 1; dualSquelchStep(1); dualSquelchStep(1);
	printf("t1=%d", IDX);
	for (int i = 0; i < 3; i++) { dualTune(0); printf(",A%d", IDX); dualTune(1); printf(",B%d", IDX); }
	ptrB = 0; dualSquelchStep(1); printf(",a%d", IDX); dualTune(1); printf(",b%d", IDX); dualTune(0); printf(",a%d\n", IDX);
	/* t1d: показ (dualCardTgIdx) -- з будь-якого боку той самий ТГ картки */
	printf("t1d=%d,%d", dualCardTgIdx(0, 0), dualCardTgIdx(1, 0)); dualTune(1); printf(",%d,%d\n", dualCardTgIdx(0, 0), dualCardTgIdx(1, 0));
	/* t5: індекс змінено на B іншим шляхом (меню/стокова клавіша) -- вибір B зберігається при поверненні на A */
	setup(); ptrB = 1; dualTune(1); IDX = 1; dualTune(0); printf("t5=%d", IDX); dualTune(1); printf(",%d\n", IDX);
	/* t1w: «вниз» по колу (0 -> останній) на B */
	setup(); ptrB = 1; dualSquelchStep(-1); printf("t1w=%d,%d\n", IDX, s_dualTgIdxB);
	/* t2: DMR без списку прийому (лише контакт) -- звук помилки, індекс не змінюється */
	setup(); chB = 11; ptrB = 1; dualSquelchStep(1); printf("t2=%d,%d\n", beep, IDX);
	/* t3: картка VFO B (DMR) -- uiVFOModeDualTgStep(1, -1) */
	setup(); bVfo = 1; bVfoIdx = 1; ptrB = 1; dualSquelchStep(-1); printf("t3=%d,%d,%d\n", vfoTg, vfoTgDir, beep);
	/* t4: FM B -- шумодав (типовий 5 -> 6), ТГ не чіпається */
	setup(); chB = 9; nonVolatileSettings.squelchDefaults[0] = 5; ptrB = 1; dualSquelchStep(1); printf("t4=%d,%d\n", channelScreenChannelData.sql, IDX);
	/* c1: правка A (потужність 9) і правка B (потужність 5) живуть через цикли */
	setup(); channelScreenChannelData.libreDMR_Power = 9; dualTune(1); printf("c1=%d", currentChannelData->libreDMR_Power); currentChannelData->libreDMR_Power = 5;
	for (int i = 0; i < 3; i++) { dualTune(0); printf(",A%d", currentChannelData->libreDMR_Power); dualTune(1); printf(",B%d", currentChannelData->libreDMR_Power); }
	printf("\n");
	/* c2: зміна B (dualBReset + інший канал) -- B з кодплага */
	dualBReset(); chB = 9; dualTune(1); printf("c2=%d,%s\n", currentChannelData->libreDMR_Power, currentChannelData->name);
	/* c3: копію B переписав стоковий код (інша назва) -- B з кодплага, не стара копія */
	setup(); dualTune(1); currentChannelData->libreDMR_Power = 5; dualTune(0); memcpy(scanNextChannelData.name, "Other", 5); dualTune(1); printf("c3=%d\n", currentChannelData->libreDMR_Power);
	/* c4: A = VFO, B = канал: копія B -- у канальному буфері */
	setup(); aVfo = 1; currentChannelData = &settingsVFOChannel[0]; memset(&channelScreenChannelData, 0, sizeof(channelScreenChannelData));
	dualTune(1); currentChannelData->libreDMR_Power = 5; dualTune(0); printf("c4=%d", (currentChannelData == &settingsVFOChannel[0])); dualTune(1); printf(",%d\n", currentChannelData->libreDMR_Power);
	/* c5: перший захід на B читає кодплаг один раз; повторні -- звірка копії (одне читання на захід, як до FIX5) */
	setup(); reads = 0; dualTune(1); dualTune(0); dualTune(1); dualTune(0); printf("c5=%d\n", reads);
	return 0;
}
"""


def tune_fns(t):
    sigs = ["static void dualSwapBufs(void)", "static _Bool dualBCopyValid(const CodeplugChannel_t *copy)", "static void dualBReset(void)",
            "static inline __attribute__((always_inline)) void channelTgStep(int dir)", "static inline __attribute__((always_inline)) void channelSquelchStep(int dir)",
            "static void dualTune(_Bool toB)", "static void dualSquelchStep(int dir)", "static int16_t dualCardTgIdx(_Bool isB, uint8_t vfoType)"]
    return [T.carve_fn(t, s) for s in sigs]


def test_tg_copy(t):
    fns = tune_fns(t)
    check(all(fns), "А2/А5: dualTune/dualSquelchStep/channelTgStep/dualCardTgIdx/робоча копія B знайдено")
    if not all(fns):
        return
    code = lambda f: TUNE_HARNESS.replace("@@SETTERS@@", SETTERS).replace("@@FNS@@", "\n".join(f))
    out = run_c(code(fns))
    check(out is not None, "А2/А5: хостова збірка")
    o = kv(out)
    exp = {"t1": "2,A0,B2,A0,B2,A0,B2,a1,b2,a1", "t1d": "1,2,1,2", "t1w": "2,2", "t2": "1,0", "t3": "1,-1,0", "t4": "6,0", "t5": "0,1",
           "c1": "1,A9,B5,A9,B5,A9,B5", "c2": "1,ChanFM", "c3": "1", "c4": "1,5", "c5": "2"}
    for k, v in exp.items():
        check(o.get(k) == v, "А2/А5 (%s): %s -- очікувано %s, є %s" % (k, {
            "t1": "ТГ B змінюється SK1 + ручкою, не змінює ТГ A, переживає цикли A<->B; ТГ A змінюється окремо (PTT з картки йде з індексом, що стоїть після налаштування на неї)",
            "t1d": "показ ТГ картки однаковий, де б не стояла рація",
            "t1w": "крок «вниз» по колу на B (0 -> останній у списку з 3)",
            "t2": "DMR без списку прийому -- звук помилки, індекс не змінюється",
            "t3": "картка VFO (DMR) -- крок ТГ VFO через uiVFOModeDualTgStep (VFO B, вниз)",
            "t4": "FM -- шумодав (стоковий крок від типового), ТГ не чіпається",
            "t5": "ТГ, змінений на B іншим шляхом, зберігається за B при поверненні на A",
            "c1": "правки A (потужність 9) і B (потужність 5) живуть через цикли A<->B",
            "c2": "новий B -- з кодплага",
            "c3": "копію B переписано іншим каналом -- B з кодплага (звірка назви/частот)",
            "c4": "A = VFO: копія B у канальному буфері переживає цикл",
            "c5": "читань флешу не більше, ніж до FIX5 (по одному на захід на B)"}[k], v, o.get(k)))
    tune = fns[5]
    muts = (("ТГ B спільний з A (індекс B не підставляється)", "t1", tune.replace("nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE] = (int16_t)s_dualTgIdxB;", "")),
            ("вибір B не зберігається при поверненні на A", "t5", tune.replace("if (dcBIsVfo() == 0)\n   {\n    s_dualTgIdxB = (uint8_t)nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];\n   }", "")),
            ("повернення на A копіює замість обміну (правки B губляться)", "c1", tune.replace("if (bufHoldsB)\n  {\n   dualSwapBufs();\n  }", "if (bufHoldsB)\n  {\n   memcpy(&channelScreenChannelData, &scanNextChannelData, sizeof(CodeplugChannel_t));\n  }")))
    for what, key, m in muts:
        f2 = list(fns); f2[5] = m
        mo = kv(run_c(code(f2))) if m != tune else {}
        check(m != tune and mo.get(key) not in (None, exp[key]), "А2/А5 (мутант): %s -- ловиться" % what)
    bc = fns[1]
    m = re.sub(r"\{.*\}", "{ return (s_dualBKeep != 0U); }", bc, flags=re.S)
    f2 = list(fns); f2[1] = m
    mo = kv(run_c(code(f2)))
    check(mo.get("c3") not in (None, exp["c3"]), "А5 (мутант): копія B без звірки з кодплагом -- ловиться")


# ------------------------------------------------------------------------------------------------ А: таблиця клавіш (dualHandleKey) і блок режиму handleEventCore
KEY_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
typedef struct { uint32_t buttons; uint32_t events; struct { int key; int event; } keys; } uiEvent_t;
enum { UI_CHANNEL_MODE = 3 };
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 };
enum { KEY_EVENT = 1 };
struct { int displayQSOState; } uiDataGlobal;
static char lg[200]; static int en = 1, ptrB = 0, onB = 0, bVfo = 0, aVfo = 0, single = 0, stepAret = 0, running = 1, directChannelNumber = 0, menu = UI_CHANNEL_MODE;
static bool s_dualQuiet; static uint32_t s_dualKeyMs;
#define L(...) do { char b_[24]; snprintf(b_, sizeof(b_), __VA_ARGS__); if (lg[0]) strcat(lg, ","); strcat(lg, b_); } while (0)
static bool dcIsEnabled(void) { return en; }
static bool dcPointerB(void) { return ptrB; }
static bool dcIsOnB(void) { return onB; }
static bool dualCardIsVfo(bool b) { return b ? bVfo : aVfo; }
static uint8_t dualCardVfo(bool b) { return b ? 1 : 0; }
static bool dualOnVfoNow(void) { return onB ? bVfo : aVfo; }
static bool dualSingle(void) { return single; }
static bool dualIsRunning(void) { return running; }
static int menuSystemGetCurrentMenuNumber(void) { return menu; }
static void dualSuspend(void) { L("S"); }
static void dualTune(bool b) { L("T%d", b); onB = b; }
static void uiVFOModeDualStep(uint8_t v, int d) { L("V%d%+d", v, d); }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
static void dualSquelchStep(int d) { L("Q%+d", d); }
static void dualZoneStepB(int d) { L("Z%+d", d); }
static void handleUpKey(uiEvent_t *e) { (void)e; L("U"); }
static void handleDownKey(uiEvent_t *e) { (void)e; L("D"); }
static void dualHotkeyToggle(void) { L("H"); }
static void dcSetPointerB(bool b) { L("P%d", b); }
static void dualStepB(int d) { L("B%+d", d); }
static bool dualStepA(int d) { L("A%+d", d); return stepAret; }
static void dualAutoResume(void) { L("R"); }
static bool dualEntryKey(uiEvent_t *e) { (void)e; return false; }
static int hkRet = 0;
@@FNS@@
static bool hkStub(uiEvent_t *e) { (void)e; return hkRet; }
@@HOOK@@
#define SK1 0x02
#define SK2 0x20
static int go(uint32_t bt, int key, int evb) { uiEvent_t e; memset(&e, 0, sizeof(e)); e.buttons = bt; e.events = KEY_EVENT; e.keys.key = key; e.keys.event = evb; lg[0] = 0; return dualHandleKey(&e); }
static void P(const char *k, int r) { printf("%s=%d:%s\n", k, r, lg); }
int main(void)
{
	int SU = 0x02, LD = 0x01 | 0x04, LR = 0x01 | 0x04 | 0x08;
	ptrB = 1; P("k1", go(0, 8, SU));                                     /* ручка, покажчик на B -- канал/VFO картки B */
	ptrB = 0; stepAret = 0; P("k2", go(0, 7, SU));                       /* ручка, покажчик на A (канал -> канал) -- стоковий крок каналу A */
	ptrB = 1; P("k3", go(SK1, 8, SU));                                   /* SK1 + ручка -- параметр прийому картки з покажчиком */
	ptrB = 1; P("k4", go(SK2, 8, SU));                                   /* SK2 + ручка на картці B = канал -- зона B */
	ptrB = 0; onB = 1; P("k5", go(SK2, 7, SU)); onB = 0;                 /* SK2 + ручка на A (канал) -- стокова зміна зони, спершу на A */
	ptrB = 1; bVfo = 1; P("k6", go(SK2, 8, SU)); bVfo = 0; onB = 0;     /* SK2 + ручка на картці VFO -- крок частоти */
	P("k7", go(0, 9, SU)); P("k8", go(0, 10, SU));                       /* ▲ / ▼ -- покажчик */
	P("k9", go(0, 10, LD)); P("k10", go(0, 10, LR)); P("k11", go(0, 9, LD));   /* довге ▼ -- вимкнення; автоповтор -- нічого; довге ▲ -- з'їдається */
	P("k12", go(0, 27, SU)); P("k13", go(0, '*', SU)); P("k14", go(SK2, 9, SU));  /* червона -- з'їдається; `*`, SK2 + ▲ -- стоковим обробникам */
	ptrB = 1; single = 1; P("k15", go(SK2, 8, SU)); single = 0;         /* A == B -- одна картка (A): зона A */
	ptrB = 1; P("k16", go(SK2, 8, 0x01));                                /* PRESS (не SHORTUP) -- з'їдається без дії */
	/* блок режиму в handleEventCore: клавіші-параметри -- на картку з покажчиком */
	hkRet = 0; running = 1; ptrB = 1; onB = 0; lg[0] = 0; { uiEvent_t e; memset(&e, 0, sizeof(e)); e.events = KEY_EVENT; e.keys.key = '*'; e.keys.event = SU; hook(&e); } printf("h1=%s\n", lg);
	ptrB = 0; onB = 1; lg[0] = 0; { uiEvent_t e; memset(&e, 0, sizeof(e)); e.events = KEY_EVENT; e.keys.key = 9; e.buttons = SK2; e.keys.event = SU; hook(&e); } printf("h2=%s\n", lg);
	ptrB = 1; onB = 0; lg[0] = 0; { uiEvent_t e; memset(&e, 0, sizeof(e)); e.events = KEY_EVENT; e.keys.key = 13; e.keys.event = SU; hook(&e); } printf("h3=%s\n", lg);   /* зелена -- без перемикання */
	ptrB = 1; single = 1; onB = 1; lg[0] = 0; { uiEvent_t e; memset(&e, 0, sizeof(e)); e.events = KEY_EVENT; e.keys.key = '#'; e.keys.event = LD; hook(&e); } printf("h4=%s\n", lg); single = 0;
	en = 0; ptrB = 1; onB = 0; lg[0] = 0; { uiEvent_t e; memset(&e, 0, sizeof(e)); e.events = KEY_EVENT; e.keys.key = '*'; e.keys.event = SU; hook(&e); } printf("h5=%s\n", lg); en = 1;
	return 0;
}
"""


def hook_block(t):
    """Блок режиму з початку handleEventCore() (до стокової обробки сканування) -- як окрема функція hook(ev)."""
    i = t.find("static void handleEventCore(uiEvent_t *ev)\n{")
    if i < 0:
        return None
    j = t.find("if (ev->events & KEY_EVENT)", i)
    k = t.find("if (uiDataGlobal.Scan.active && (ev->events & KEY_EVENT))", j)
    if j < 0 or k < 0:
        return None
    blk = t[j:k].replace("dualHandleKey(ev)", "hkStub(ev)").replace("ticksGetMillis()", "0")
    blk = re.sub(r"\(\(\(ev->keys\.key == 10\)", "(((ev->keys.key == 10)", blk)
    return "static void hook(uiEvent_t *ev)\n{\n" + blk + "\nL(\"stock\");\n}\n"


def test_keys(t, src):
    sigs = ["static _Bool dualIsVfoStepKey(const uiEvent_t *ev)", "static _Bool dualIsSquelchKey(const uiEvent_t *ev)", "static _Bool dualHandleKey(uiEvent_t *ev)"]
    fns = [T.carve_fn(t, s) for s in sigs]
    hb = hook_block(t)
    check(all(fns) and hb is not None, "А0: dualHandleKey / dualIsVfoStepKey / dualIsSquelchKey і блок режиму handleEventCore знайдено")
    if not (all(fns) and hb):
        return
    code = lambda f, h: KEY_HARNESS.replace("@@FNS@@", "\n".join(f)).replace("@@HOOK@@", h)
    out = run_c(code(fns, hb))
    check(out is not None, "А0: хостова збірка таблиці клавіш")
    o = kv(out)
    exp = {"k1": "1:B+1", "k2": "1:A-1,S,D,R", "k3": "1:Q+1", "k4": "1:Z+1", "k5": "1:S,T0,D", "k6": "1:S,T1,V1+1", "k7": "1:P0", "k8": "1:P1",
           "k9": "1:H", "k10": "1:", "k11": "1:", "k12": "1:", "k13": "0:", "k14": "0:", "k15": "1:S,U", "k16": "1:",
           "h1": "S,T1,stock", "h2": "S,T0,stock", "h3": "S,stock", "h4": "S,T0,stock", "h5": "stock"}
    names = {"k1": "ручка на B -- крок картки B", "k2": "ручка на A (канал -> канал) -- стоковий крок каналу A, далі поновлення", "k3": "SK1 + ручка -- параметр прийому (шумодав/ТГ)",
             "k4": "SK2 + ручка на B = канал -- зона B", "k5": "SK2 + ручка на A -- стокова зміна зони, рація спершу на A", "k6": "SK2 + ручка на картці VFO -- крок частоти цього VFO",
             "k7": "▲ -- покажчик на A", "k8": "▼ -- покажчик на B", "k9": "довге ▼ -- вимкнення", "k10": "автоповтор довгого ▼ -- нічого", "k11": "довге ▲ -- з'їдається (вільне)",
             "k12": "червона -- з'їдається", "k13": "`*` -- стоковому обробнику", "k14": "SK2 + ▲ (потужність) -- стоковому обробнику", "k15": "A == B: SK2 + ручка -- зона A",
             "k16": "PRESS SK2 + ручки -- без дії", "h1": "`*` при покажчику на B -- спершу рація на B (а не на A, як до FIX5)", "h2": "SK2 + ▲ при покажчику на A -- спершу на A",
             "h3": "зелена -- на обраному (без перемикання)", "h4": "A == B: довге `#` -- на A", "h5": "режим вимкнено -- блок нічого не робить"}
    for k, v in exp.items():
        check(o.get(k) == v, "А0 (%s): %s -- очікувано «%s», є «%s»" % (k, names[k], v, o.get(k)))
    hk = fns[2]
    muts = (("SK2 + ручка на B міняє зону A", "k4", hk.replace("if (dcPointerB() && (dualSingle() == 0))", "if (0)")),
            ("SK2 + ручка на каналі -- стокова (не правила режиму)", "k4", hk.replace("((ev->keys.key == 8) || (ev->keys.key == 7)))\n {\n  if (((ev->keys.key == ev->keys.key) && ((ev->keys.event & (0x02 | 0x04)) == 0x02)))\n  {\n   int dir", "0)\n {\n  if (1)\n  {\n   int dir")),
            ("довге ▲ не з'їдається", "k11", hk.replace("return 1;\n  case 8:", "return 0;\n  case 8:")))
    for what, key, m in muts:
        f2 = list(fns); f2[2] = m
        mo = kv(run_c(code(f2, hb))) if m != hk else {}
        check(m != hk and mo.get(key) not in (None, exp[key]), "А0 (мутант): %s -- ловиться" % what)
    hm = hb.replace("dualTune(toB);", "dualTune(0);")
    mo = kv(run_c(code(fns, hm)))
    check(hm != hb and mo.get("h1") not in (None, exp["h1"]), "А5 (мутант): клавіша-параметр іде на A при покажчику на B -- ловиться")
    check("dualIsAKey" not in src.replace("dualIsAKey() прибрано", ""), "А0: dualIsAKey прибрано (у режимі всі клавіші й так ідуть у правила режиму)")


# ------------------------------------------------------------------------------------------------ А3: зона для B
ZONE_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
typedef struct { char name[16]; uint16_t channels[80]; int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_highestIndex; int NOT_IN_CODEPLUGDATA_indexNumber; } CodeplugZone_t;
typedef bool (*codeplugZoneUsableFn)(int zoneNum, void *ctx);
typedef uint16_t (*dcChanAt_t)(int pos, void *ctx);
enum { MELODY_ERROR_BEEP = 1, NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2, SCAN_STATE_SCANNING = 0 };
struct { int16_t currentZone; } nonVolatileSettings;
struct { struct { int state; } Scan; } uiDataGlobal;
static CodeplugZone_t zones[6], currentZone;
static int nZones = 5, used[40], beep = 0, setB = -1, lastUsedCalls = 0, typeB = 0, chB0 = 0, isVfoB = 0;
static uint8_t s_dualZoneB; static uint32_t s_dualKeyMs; static uint8_t s_dualTgIdxB, s_dualBKeep;
static char note[20];
static int codeplugZonesGetCount(void) { return nZones; }
static bool codeplugAllChannelsIndexIsInUse(int c) { return (c >= 1) && (c < 40) && used[c]; }
static bool codeplugZoneGetDataForNumber(int z, CodeplugZone_t *b) { if (z < 0 || z >= nZones) return false; *b = zones[z]; return true; }
static bool codeplugZoneIsUsable(int z, CodeplugZone_t *b) { CodeplugZone_t t; if (!b) b = &t; bool ok = codeplugZoneGetDataForNumber(z, b); if (z == nZones - 1) return ok; return ok && b->NOT_IN_CODEPLUGDATA_numChannelsInZone > 0 && codeplugAllChannelsIndexIsInUse(b->channels[0]); }
static void soundSetMelody(int m) { (void)m; beep++; }
static void codeplugUtilConvertBufToDisplayString(char *in, char *out, int n) { memcpy(out, in, n); out[n] = 0; for (int i = n - 1; i >= 0 && (out[i] == ' ' || out[i] == 0); i--) out[i] = 0; }
static bool dcSetChannelB(uint16_t c, bool now) { (void)now; setB = c; chB0 = c; isVfoB = 0; return true; }
static void dcSetTypeB(uint8_t t) { typeB = t; isVfoB = 1; }
static uint16_t dcChannelB(void) { return (uint16_t)chB0; }
static bool dcBIsVfo(void) { return isVfoB; }
static uint8_t dualVfoIdx(void) { return 0; }
static uint16_t dualChannelA(void) { return currentZone.channels[0]; }
static void uiNotificationShow(int a, int b, unsigned t, const char *s, bool f) { (void)a; (void)b; (void)t; (void)f; snprintf(note, sizeof(note), "%s", s); }
static bool dualIsRunning(void) { return false; }
static void dualAutoResume(void) {}
static bool dcIsOnB(void) { return false; }
static void dualTune(bool b) { (void)b; }
static void dualSetDwell(void) {}
static void codeplugSetLastUsedChannelInZone(int z, int p) { (void)z; (void)p; lastUsedCalls++; }
@@FNS@@
static void zone(int i, const char *nm, int n, const int *ch) { memset(&zones[i], 0, sizeof(zones[i])); memcpy(zones[i].name, nm, strlen(nm)); zones[i].NOT_IN_CODEPLUGDATA_numChannelsInZone = n; zones[i].NOT_IN_CODEPLUGDATA_indexNumber = i; for (int k = 0; k < n; k++) zones[i].channels[k] = (uint16_t)ch[k]; }
int main(void)
{
	static const int z0[] = { 1, 2 }, z1[] = { 5, 6 }, z2[] = { 30 }, z3[] = { 8, 9, 10 };
	for (int c = 1; c < 40; c++) used[c] = 1; used[30] = 0; used[3] = 0;
	zone(0, "Zero", 2, z0); zone(1, "One", 2, z1); zone(2, "Bad", 1, z2); zone(3, "Three", 3, z3);
	memset(&zones[4], 0, sizeof(zones[4])); memcpy(zones[4].name, "All", 3); zones[4].NOT_IN_CODEPLUGDATA_indexNumber = -1; zones[4].NOT_IN_CODEPLUGDATA_highestIndex = 39;
	used[1] = 1;
	nonVolatileSettings.currentZone = 0; currentZone = zones[0]; s_dualZoneB = 0; s_dualBKeep = 1; s_dualTgIdxB = 2;
	dualZoneStepB(1); printf("z1=%d,%d,%s,%d,%d,%d,%d\n", setB, s_dualZoneB, note, nonVolatileSettings.currentZone, lastUsedCalls, s_dualBKeep, s_dualTgIdxB);   /* зона 1, перший канал 5; поточна зона і «останній канал» -- не чіпались; копія й ТГ B -- з нуля */
	dualZoneStepB(1); printf("z2=%d,%d\n", setB, s_dualZoneB);              /* зона 2 непридатна (перший канал видалено) -- пропуск, зона 3 */
	dualZoneStepB(1); printf("z3=%d,%d,%s\n", setB, s_dualZoneB, note);     /* «Всі канали» (остання) -- найменший використаний номер (1) */
	dualZoneStepB(1); printf("z4=%d,%d\n", setB, s_dualZoneB);              /* по колу -- зона 0 */
	s_dualZoneB = 0; dualZoneStepB(-1); printf("z5=%d,%d\n", setB, s_dualZoneB);   /* від поточної назад -- «Всі канали» */
	/* ручка на B після вибору зони B -- по каналах зони B (3: 8 -> 9 -> 10 -> VFO A), а не поточної */
	s_dualZoneB = 5; dualZoneStepB(-1); printf("z6=%d,%d", setB, s_dualZoneB); dualStepB(1); printf(",%d", setB); dualStepB(1); printf(",%d", setB); dualStepB(1); printf(",%d,%d\n", isVfoB, typeB);
	/* зону B не вибрано -- ручка на B ходить по поточній зоні, як раніше */
	s_dualZoneB = 0; chB0 = 1; isVfoB = 0; dualStepB(1); printf("z7=%d\n", setB);
	return 0;
}
"""


def test_zone(t, tdc):
    sigs = ["static inline int codeplugZoneStep(int cur, int numZones, _Bool next, codeplugZoneUsableFn usable, void *ctx)", "static _Bool zoneStepUsable(int zoneNum, void *ctx)",
            "static uint16_t dualZoneChannelAt(int pos, void *ctx)", "static const CodeplugZone_t *dualZoneB(CodeplugZone_t *buf)", "static void dualBReset(void)",
            "static void dualZoneStepB(int dir)", "static void dualStepB(int dir)"]
    fns = [T.carve_fn(t, s) for s in sigs]
    dc = [T.carve_fn(tdc, s) for s in ("int dcStepExt(int n, int fromExt, int dir, dcChanAt_t at, void *ctx)", "int dcFindPos(int n, uint16_t ch, dcChanAt_t at, void *ctx)")]
    check(all(fns) and all(dc), "А3: dualZoneStepB / dualStepB / codeplugZoneStep / dcStepExt / dcFindPos знайдено")
    if not (all(fns) and all(dc)):
        return
    code = lambda f: ZONE_HARNESS.replace("@@FNS@@", "\n".join(dc + f))
    out = run_c(code(fns))
    check(out is not None, "А3: хостова збірка зони B")
    o = kv(out)
    exp = {"z1": "5,2,One,0,0,0,0", "z2": "8,4", "z3": "1,5,All", "z4": "1,1", "z5": "1,5", "z6": "8,4,9,10,1,1", "z7": "2"}
    names = {"z1": "SK2 + ручка на B -- перший канал НАСТУПНОЇ зони; поточна зона, A і «останній канал зони» не змінюються; копія і ТГ B -- з нуля; сповіщення -- назва зони",
             "z2": "непридатна зона (видалений перший канал) пропускається, як у стоку", "z3": "«Всі канали» -- найменший використаний номер",
             "z4": "по колу (після «Всі канали» -- зона 0)", "z5": "назад від поточної зони -- «Всі канали» (остання)", "z6": "ручка на B ходить по вибраній зоні B, далі VFO A",
             "z7": "зону B не вибрано -- ручка на B по поточній зоні"}
    for k, v in exp.items():
        check(o.get(k) == v, "А3 (%s): %s -- очікувано %s, є %s" % (k, names[k], v, o.get(k)))
    zs = fns[5]
    muts = (("відлік завжди від поточної зони (зона B не запам'ятовується)", "z2", zs.replace("((int)s_dualZoneB - 1) : (int)nonVolatileSettings.currentZone", "(int)nonVolatileSettings.currentZone : (int)nonVolatileSettings.currentZone")),
            ("береться останній, а не перший канал зони", "z1", zs.replace("(i < n) && (ch == 0U)", "(i < n)")))
    for what, key, m in muts:
        f2 = list(fns); f2[5] = m
        mo = kv(run_c(code(f2))) if m != zs else {}
        check(m != zs and mo.get(key) not in (None, exp[key]), "А3 (мутант): %s -- ловиться" % what)


# ------------------------------------------------------------------------------------------------ А2: ТГ VFO, А5: ТС-перекриття картки VFO
VFO_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#define SETTINGS_VFO_A_MODE 1
struct { uint8_t currentVFONumber; int16_t currentIndexInTRxGroupList[3]; uint32_t overrideTG; } nonVolatileSettings;
struct { int NOT_IN_CODEPLUG_numTGsInGroup; } currentRxGroupData;
@@SETTERS@@
static int trxSeenVfo = -1, trxSeenIdx = -1;
static void menuPrivateCallClear(void) {}
static void updateTrxID(void) { trxSeenVfo = nonVolatileSettings.currentVFONumber; trxSeenIdx = nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_VFO_A_MODE + nonVolatileSettings.currentVFONumber]; }
@@FN@@
#define I(v) nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_VFO_A_MODE + (v)]
int main(void)
{
	currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup = 3; nonVolatileSettings.currentVFONumber = 0; I(0) = 1; I(1) = 2;
	uiVFOModeDualTgStep(1, 1); printf("v1=%d,%d,%d,%d,%d\n", I(1), I(0), nonVolatileSettings.currentVFONumber, trxSeenVfo, trxSeenIdx);   /* VFO B: 2 -> 0 по колу; VFO A не чіпано; поточний VFO стока відновлено */
	uiVFOModeDualTgStep(1, -1); printf("v2=%d\n", I(1));                                                                             /* 0 -> 2 */
	nonVolatileSettings.overrideTG = 91; uiVFOModeDualTgStep(1, 1); printf("v3=%d,%u\n", I(1), (unsigned)nonVolatileSettings.overrideTG);   /* перекриття -- кроку нема, перекриття скинуто (як у стоку) */
	currentRxGroupData.NOT_IN_CODEPLUG_numTGsInGroup = 1; uiVFOModeDualTgStep(0, 1); printf("v4=%d\n", I(0));                         /* один ТГ -- кроку нема */
	return 0;
}
"""

TSFIX_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
typedef struct { uint32_t buttons; uint32_t events; struct { int key; int event; } keys; } uiEvent_t;
enum { KEY_EVENT = 1, UI_CHANNEL_MODE = 3, CHANNEL_VFO_A = 0, CHANNEL_VFO_B = 1, CHANNEL_CHANNEL = 2 };
struct { uint16_t tsManualOverride; } nonVolatileSettings;
@@SETTERS@@
static int onVfo = 1, vfoCard = 1, loads = 0, dirty = 0, menu = UI_CHANNEL_MODE;
static bool dualOnVfoNow(void) { return onVfo; }
static uint8_t dualCardVfo(bool b) { (void)b; return (uint8_t)vfoCard; }
static bool dcIsOnB(void) { return true; }
static int menuSystemGetCurrentMenuNumber(void) { return menu; }
static void uiVFOModeDualLoad(uint8_t v, bool f) { (void)v; (void)f; loads++; }
static void settingsSetVFODirty(void) { dirty++; }
@@FN@@
static void key(int k, uint32_t bt) { uiEvent_t e; memset(&e, 0, sizeof(e)); e.events = KEY_EVENT; e.keys.key = k; e.buttons = bt;
	uint16_t before = nonVolatileSettings.tsManualOverride; nonVolatileSettings.tsManualOverride = (uint16_t)(before | (2U << 4) | (1U << 8)); dualVfoKeyDone(&e, before); }
int main(void)
{
	/* стоковий `*` на екрані каналу записав ТС2 і «контакт перекрито» у відро каналу (біти 4..5, біт 8); картка -- VFO B */
	nonVolatileSettings.tsManualOverride = 0x0001; key('*', 0); printf("s1=%04x,%d,%d\n", nonVolatileSettings.tsManualOverride, loads, dirty);
	onVfo = 0; nonVolatileSettings.tsManualOverride = 0; loads = dirty = 0; key('*', 0); printf("s2=%04x,%d,%d\n", nonVolatileSettings.tsManualOverride, loads, dirty);   /* картка-канал -- без змін */
	onVfo = 1; nonVolatileSettings.tsManualOverride = 0; loads = dirty = 0; { uiEvent_t e; memset(&e, 0, sizeof(e)); e.events = KEY_EVENT; e.keys.key = 9; e.buttons = 0x20; dualVfoKeyDone(&e, 0); } printf("s3=%04x,%d,%d\n", nonVolatileSettings.tsManualOverride, loads, dirty);   /* SK2 + ▲ (потужність) -- запис VFO */
	return 0;
}
"""


def test_vfo(tv, t):
    fn = T.carve_fn(tv, "void uiVFOModeDualTgStep(uint8_t vfo, int dir)")
    check(fn is not None, "А2: uiVFOModeDualTgStep знайдено")
    if fn:
        code = lambda f: VFO_HARNESS.replace("@@SETTERS@@", SETTERS).replace("@@FN@@", f)
        o = kv(run_c(code(fn)))
        exp = {"v1": "0,1,0,1,0", "v2": "2", "v3": "2,0", "v4": "1"}
        check(all(o.get(k) == v for k, v in exp.items()), "А2: ТГ VFO -- по колу, лише без перекриття (перекриття скидається), свій індекс VFO, поточний VFO стока на час виклику = цей VFO і відновлюється: %s" % o)
        m = fn.replace("SETTINGS_VFO_A_MODE + vfo", "SETTINGS_VFO_A_MODE")
        mo = kv(run_c(code(m)))
        check(m != fn and mo.get("v1") != exp["v1"], "А2 (мутант): індекс ТГ не того VFO -- ловиться")
    fk = T.carve_fn(t, "static void dualVfoKeyDone(const uiEvent_t *ev, uint16_t tsBefore)")
    check(fk is not None, "А5: dualVfoKeyDone знайдено")
    if fk:
        code = lambda f: TSFIX_HARNESS.replace("@@SETTERS@@", SETTERS).replace("@@FN@@", f)
        o = kv(run_c(code(fk)))
        exp = {"s1": "0089,1,1", "s2": "0120,0,0", "s3": "0000,0,1"}
        check(all(o.get(k) == v for k, v in exp.items()), "А5: `*` на картці VFO B -- ТС2 і «контакт перекрито» переїхали з відра каналу у відро VFO B (біти 2..3, біт 7), відро каналу як було, VFO перечитано, запис VFO; на картці-каналі -- нічого: %s" % o)
        m = fk.replace("if (now != tsBefore)", "if (0)")
        mo = kv(run_c(code(m)))
        check(mo.get("s1") != exp["s1"], "А5 (мутант): ТС-перекриття лишається у відрі каналу -- ловиться")


# ------------------------------------------------------------------------------------------------ Б: розкладка
ROW_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#define CHANNEL_FLAG_BW_25K 1
#define CHANNEL_FLAG_TIMESLOT_TWO 2
enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
enum { FONT_SIZE_1 = 1, FONT_SIZE_3 = 3, FONT_SIZE_4 = 4 };
enum { TEXT_ALIGN_LEFT = 0 };
enum { THEME_ITEM_FG_DECORATION, THEME_ITEM_BG, THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_FG_CHANNEL_CONTACT, THEME_ITEM_FG_CHANNEL_CONTACT_INFO, THEME_ITEM_FG_DEFAULT, THEME_ITEM_FG_RSSI_BAR, THEME_ITEM_FG_RSSI_BAR_S9P };
enum { CONTACT_DISPLAY_PRIO_CC_DB_TA, CONTACT_DISPLAY_PRIO_DB_CC_TA, CONTACT_DISPLAY_PRIO_TA_CC_DB };
enum { CONTACT_CALLTYPE_TG = 0, CONTACT_CALLTYPE_PC };
#define TG_CALL_FLAG 0x00
#define PC_CALL_FLAG 0x03
#define ALL_CALL_VALUE 16777215
#define SETTINGS_CHANNEL_MODE 0
#define SETTINGS_VFO_A_MODE 1
#define RADIO_DEVICE_PRIMARY 0
#define SMETER_S0 -129
#define SMETER_S9 -93
typedef int ContactCalltype_t; typedef int CodeplugCSSTypes_t; typedef int Channel_t;
#define CSS_TYPE_NONE 1
#define CSS_TYPE_CTCSS 2
#define CSS_TYPE_DCS 0x8000
#define CHANNEL_CHANNEL 2
#define CHANNEL_VFO_A 0
#define CHANNEL_VFO_B 1
#define CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE 0x01
#define CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK 0x02
typedef struct { char name[16]; uint32_t rxFreq; uint32_t txFreq; uint8_t chMode; uint8_t libreDMR_Power; uint16_t contact; uint8_t txColor; uint16_t rxTone; uint16_t txTone; uint8_t flags; uint8_t encrypt; uint8_t rxGroupList; uint8_t NOT_IN_CODEPLUG_flag; } CodeplugChannel_t;
typedef struct { char name[16]; uint32_t tgNumber; uint8_t callType; uint8_t reserve1; } CodeplugContact_t;
typedef struct { int16_t tx, ty, lx, ly, rx, ry, nx, ny; } aprsChevron_t;
typedef struct { aprsChevron_t g; int16_t cx, cy; } lcDistArrow_t;
typedef struct { int16_t x0, x1; int16_t y, h; } lcDistSpan_t;
typedef struct { char contact[32]; char talkerAlias[32]; char talkgroup[17]; double locationLat, locationLon; } LinkItem_t;
struct { int contactDisplayPriority; uint32_t overrideTG; int16_t currentIndexInTRxGroupList[3]; uint8_t txPowerLevel; } nonVolatileSettings;
struct { char tg[8]; char pc[8]; char all_call[12]; } lang, *currentLanguage = &lang;
static LinkItem_t item; static LinkItem_t *LinkHead = &item;
static CodeplugChannel_t chans[40], settingsVFOChannel[2], channelScreenChannelData, scanNextChannelData; static char used[40]; static CodeplugContact_t cts[8];
static int16_t s_dualTgIdxA; static uint8_t s_dualTgIdxB, s_dualBKeep;
static int onB = 0, aVfo = 0, single = 0, ptrB = 0, bufB = 0, directChannelNumber = 0, unD[2], unA = 0, rssi = -200, own = 0, known = 1, letterInv = -1;
static bool dcIsOnB(void) { return onB; }
static bool dcAIsVfo(void) { return aVfo; }
static bool dualSingle(void) { return single; }
static bool dcPointerB(void) { return ptrB; }
static bool dualBufHoldsB(void) { return bufB; }
static void dualEntryText(char *l2, size_t n) { snprintf(l2, n, "1234567890123456"); }
unsigned uiUnreadCountCard(bool b) { return (unsigned)unD[b ? 1 : 0]; }
unsigned uiUnreadCount(char k) { return (k == 'A') ? (unsigned)unA : 0U; }
int8_t tsGetManualOverride(Channel_t c) { (void)c; return 0; }
bool tsIsContactHasBeenOverridden(Channel_t c) { (void)c; return 0; }
bool codeplugAllChannelsIndexIsInUse(int ch) { return (ch > 0) && (ch < 40) && used[ch]; }
void codeplugChannelGetDataForIndex(int ch, CodeplugChannel_t *c) { *c = chans[ch]; }
int codeplugChannelGetFlag(CodeplugChannel_t *c, int f) { return (c->flags & f) != 0; }
bool codeplugContactGetDataForIndex(int i, CodeplugContact_t *c) { if (i <= 0 || i >= 8) { memset(c, 0, sizeof(*c)); memcpy(c->name, "TG 9            ", 16); c->tgNumber = 9; c->reserve1 = 0xff; return false; } *c = cts[i]; return true; }
uint32_t codeplugContactGetPackedId(CodeplugContact_t *c) { return (c->callType == CONTACT_CALLTYPE_PC) ? (c->tgNumber | ((uint32_t)PC_CALL_FLAG << 24)) : c->tgNumber; }
int codeplugRxGroupGetContactAt(int g, int pos, int *num) { *num = 0; if (g == 1) { static const int l[3] = { 2, 3, 4 }; *num = 3; return l[(pos < 0 || pos > 2) ? 0 : pos]; } return 0; }
int codeplugContactIndexByTGorPC(uint32_t id, ContactCalltype_t t, CodeplugContact_t *c, uint8_t ts) { (void)id; (void)t; (void)c; (void)ts; return -1; }
void codeplugUtilConvertBufToDisplayString(char *in, char *out, int len) { memcpy(out, in, len); out[len] = 0; for (int i = len - 1; i >= 0 && (out[i] == ' ' || out[i] == 0); i--) out[i] = 0; }
int codeplugGetCSSType(uint16_t t) { return ((t == 0xFFFF) || (t == 0)) ? CSS_TYPE_NONE : ((t & 0x8000) ? CSS_TYPE_DCS : CSS_TYPE_CTCSS); }
size_t dcsPrintf(char *d, size_t m, char *prefix, uint16_t tone) { (void)prefix; (void)tone; return (size_t)snprintf(d, m, "D023N"); }
char *chomp(char *s) { int n = strlen(s); while (n > 0 && s[n-1] == ' ') s[--n] = 0; return s; }
int uiChannelDataHasAes(CodeplugChannel_t *c) { return c->encrypt; }
const char *getPowerLevel(uint8_t l) { static char b[8]; snprintf(b, sizeof(b), "P%u", (unsigned)l); return b; }
const char *getPowerLevelUnit(uint8_t l) { (void)l; return "W"; }
const char *uiSafeStr(const char *s) { return s ? s : ""; }
bool settingsLocationIsValid(void) { return own; }
double settingsLocationGetLatitude(void) { return 50.0; }
double settingsLocationGetLongitude(void) { return 30.0; }
bool lcDistLabel(char *b, size_t n, bool ok, double a, double c, double d, double e, uint16_t *br, bool *bk) { (void)ok; (void)a; (void)c; (void)d; (void)e; snprintf(b, n, "1234km"); *br = 45; *bk = known; return true; }
void aprsChevronGeom(aprsChevron_t *g, int16_t cx, int16_t cy, int16_t len, uint16_t b) { (void)b; g->tx = cx; g->ty = cy - len; g->lx = cx - len; g->ly = cy + len; g->rx = cx + len; g->ry = cy + len; g->nx = cx; g->ny = cy + 1; }
int trxGetRSSIdBm(int d) { (void)d; return rssi; }
/* ---- запис усього, що намальовано (прямокутники в абсолютних координатах) ---- */
typedef struct { int x, y, w, h; char kind; char txt[24]; int inv; } prim_t;
static prim_t pr[200]; static int np = 0;
static void add(char k, int x, int y, int w, int h, const char *t, int inv) { if (np < 200) { pr[np].kind = k; pr[np].x = x; pr[np].y = y; pr[np].w = w; pr[np].h = h; pr[np].inv = inv; snprintf(pr[np].txt, sizeof(pr[np].txt), "%s", t ? t : ""); np++; } }
void displayThemeApply(int a, int b) { (void)a; (void)b; }
void displayThemeResetToDefault(void) {}
void displayDrawRect(int x, int y, int w, int h, bool inv) { add('r', x, y, w, h, 0, inv); }
void displayFillRect(int x, int y, int w, int h, bool inv) { add('f', x, y, w, h, 0, inv); }
void displayDrawLine(int a, int b, int c, int d, bool inv) { int x0 = a < c ? a : c, y0 = b < d ? b : d; add('l', x0, y0, (a > c ? a - c : c - a) + 1, (b > d ? b - d : d - b) + 1, 0, inv); }
void displayFillTriangle(int a, int b, int c, int d, int e, int f, bool inv) { int x0 = a, x1 = a, y0 = b, y1 = b; if (c < x0) x0 = c; if (e < x0) x0 = e; if (c > x1) x1 = c; if (e > x1) x1 = e; if (d < y0) y0 = d; if (f < y0) y0 = f; if (d > y1) y1 = d; if (f > y1) y1 = f; add('t', x0, y0, x1 - x0 + 1, y1 - y0 + 1, 0, inv); }
void uiDrawAesIconAt(int x, int y) { add('k', x, y, 10, 9, 0, 0); }
int displayPrintCore(int x, int y, const char *t, int f, int al, bool inv) { int w = (f == FONT_SIZE_1) ? 6 : (f == FONT_SIZE_3 ? 8 : 16), h = (f == FONT_SIZE_1) ? 8 : (f == FONT_SIZE_3 ? 16 : 32); (void)al; if (t[0]) add('T', x, y, (int)strlen(t) * w, h, t, inv); return 0; }
@@FNS@@
static void dump(const char *k, int y)
{
	printf("%s=", k);
	for (int i = 0; i < np; i++) printf("%s%c:%d:%d:%d:%d:%d:%s", i ? ";" : "", pr[i].kind, pr[i].x, pr[i].y - y, pr[i].w, pr[i].h, pr[i].inv, pr[i].txt);
	printf("\n");
}
#define ROW(k, y, b, ch, vt, sel, act, cl) do { np = 0; dualRenderRow((y), (b), (ch), (vt), (sel), (act), (cl)); dump((k), (y)); } while (0)
int main(void)
{
	strcpy(lang.tg, "TG"); strcpy(lang.pc, "PC"); strcpy(lang.all_call, "All call");
	for (int i = 1; i < 40; i++) { used[i] = 1; memset(chans[i].name, 'W', 16); chans[i].rxFreq = chans[i].txFreq = 14550000U; chans[i].chMode = RADIO_MODE_ANALOG; chans[i].rxTone = chans[i].txTone = 0xFFFF; chans[i].txColor = 1; chans[i].libreDMR_Power = 0; }
	chans[5].chMode = RADIO_MODE_DIGITAL; chans[5].contact = 2; chans[5].txColor = 15; chans[5].encrypt = 1; chans[5].libreDMR_Power = 5; memcpy(cts[2].name, "TG Ukraine 255  ", 16); cts[2].tgNumber = 255; cts[2].reserve1 = CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;
	chans[6].chMode = RADIO_MODE_DIGITAL; chans[6].rxGroupList = 1; chans[6].txColor = 2; memcpy(chans[6].name, "List", 4); memset(chans[6].name + 4, ' ', 12);
	memcpy(cts[3].name, "TG Three        ", 16); cts[3].tgNumber = 3; memcpy(cts[4].name, "TG Four         ", 16); cts[4].tgNumber = 4; cts[3].reserve1 = cts[4].reserve1 = CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;
	chans[11].rxTone = 0x8000 | 023; chans[11].txTone = 670; chans[11].flags = CHANNEL_FLAG_BW_25K;
	nonVolatileSettings.txPowerLevel = 7;
	settingsVFOChannel[1] = chans[6]; settingsVFOChannel[1].rxFreq = 43012500U; settingsVFOChannel[1].NOT_IN_CODEPLUG_flag = 3;
	/* a1: картка A, DMR, канал 39 з 16-символьною назвою, обрана, активна (S-метр), замок, виклик з відстанню і стрілкою, «D» = 3 */
	own = 1; known = 1; unD[0] = 3; rssi = -60; strcpy(item.contact, "ID:1234567"); strcpy(item.talkerAlias, "CALLSIGN NAME 16"); strcpy(item.talkgroup, "TG 91");
	chans[39] = chans[5]; channelScreenChannelData = chans[39];
	ROW("a1", 11, false, 39, 0, true, true, true);
	/* b1: картка B, FM, DCS/CTCSS, «D» = 2 (джерело B) і APRS 12 («+») разом, не обрана, неактивна */
	unD[1] = 2; unA = 12; ROW("b1", 71, true, 11, 0, false, false, false);
	/* b2: картка B = VFO B (DMR), обрана, активна, лише APRS */
	unD[1] = 0; unA = 1; ROW("b2", 71, true, 0, 2, true, true, false);
	/* b3: набір номера для картки з покажчиком (B) -- поле в рядку 2 */
	unA = 0; ptrB = 1; directChannelNumber = 12; ROW("b3", 71, true, 11, 0, true, false, false); directChannelNumber = 0; ptrB = 0;
	/* b4: B = канал зі списком прийому, рація на A: показано ТГ B (s_dualTgIdxB = 2 -> «TG Four»), на рядку 4 -- загальна потужність (P7W) */
	s_dualTgIdxB = 2; nonVolatileSettings.currentIndexInTRxGroupList[0] = 0; ROW("b4", 71, true, 6, 0, false, false, false);
	/* a2: та сама картка як A (рація на A) -- індекс із налаштувань (0 -> «TG Two»? контакт 2) */
	ROW("a2", 11, false, 6, 0, false, false, false);
	/* a3: незбережена правка A (потужність 3 у канальному буфері, та сама назва/частоти) -- видно на картці (P2W) */
	channelScreenChannelData = chans[5]; channelScreenChannelData.libreDMR_Power = 3; ROW("a3", 11, false, 5, 0, false, false, false);
	/* a4: найдовші рядки: виклик без азимуту (стрілки нема), відстань не влазить -- рядок 4 без неї */
	channelScreenChannelData = chans[39]; known = 0; ROW("a4", 11, false, 39, 0, true, true, true); known = 1;
	return 0;
}
"""

ROW_SIGS = ["static Channel_t dualChanOf(const CodeplugChannel_t *ch)", "static void dualCallerText(char *text17)", "static void dualMeterRow(int16_t y)",
            "static uint32_t dualDestination(const CodeplugChannel_t *ch, char *out, _Bool *numOnly, uint8_t *tsFlags, int16_t tgIdx)",
            "static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags)", "static size_t dualToneOne(char *dst, size_t size, const char *mark, uint16_t tone)",
            "static void dualFmToneLine(char *l3, size_t size, uint16_t rxTone, uint16_t txTone, _Bool bw25)",
            "static void dualRow4Text(char *l4, size_t size, const CodeplugChannel_t *rec, _Bool callerHere, uint16_t *bearing, _Bool *bearingKnown)",
            "static const CodeplugChannel_t *dualCardMem(_Bool isB, const CodeplugChannel_t *tmp)", "static int16_t dualCardTgIdx(_Bool isB, uint8_t vfoType)",
            "static void dualRenderRow(int16_t y, _Bool isB, uint16_t ch, uint8_t vfoType, _Bool selected, _Bool active, _Bool callerHere)"]


def consts(src):
    D = {"DISPLAY_Y_POS_BAR": 10}
    for m in re.finditer(r"^#define (DW_\w+)\s+(.+?)(?:\s*//.*)?$", src, re.M):
        try:
            D[m.group(1)] = int(eval(re.sub(r"\b(DW_\w+|DISPLAY_Y_POS_BAR)", lambda x: str(D[x.group(1)]), m.group(2).strip())))
        except Exception:
            pass
    return D


def zones(D, un, ap, arrow):
    """Зони картки (відносно y картки): x0, y0, x1, y1 включно."""
    res = (D["DW_UN_W"] if un else 0) + (D["DW_AP_RES"] if ap else 0)
    ax = D["DW_AP_X_WITH_D"] if un else D["DW_AP_X_ALONE"]
    z = {"frame": None,
         "letter": (D["DW_LET_BOX_X"], D["DW_LET_BOX_DY"], D["DW_LET_BOX_X"] + D["DW_LET_BOX_W"] - 1, D["DW_LET_BOX_DY"] + D["DW_LET_BOX_H"] - 1),
         "row1": (D["DW_TXT_X"], D["DW_LINE1_DY"], D["DW_IN_R"] - res, D["DW_LINE1_DY"] + 7),
         "row2": (D["DW_TXT_X"], D["DW_LINE2_DY"], D["DW_TXT_X"] + 16 * 8 - 1, D["DW_LINE2_DY"] + 15),
         "row3": (D["DW_FULL_X"], D["DW_LINE3_DY"], D["DW_FULL_X"] + D["DW_LINE3_MAX"] * 6 - 1, D["DW_LINE3_DY"] + 7),
         "lock": (D["DW_LOCK_X"], D["DW_LOCK_DY"], D["DW_LOCK_X"] + 9, D["DW_LOCK_DY"] + 8),
         "row4": (D["DW_FULL_X"], D["DW_LINE4_DY"], (arrow[0] - 1) if arrow else (D["DW_FULL_X"] + D["DW_LINE4_MAX"] * 6 - 1), D["DW_LINE4_DY"] + 7),
         "meter": (D["DW_FULL_X"], D["DW_METER_DY"], D["DW_IN_R"], D["DW_METER_DY"] + D["DW_METER_H"] - 1)}
    if un:
        z["D"] = (D["DW_UN_X"], D["DW_LINE1_DY"], D["DW_IN_R"], D["DW_LINE1_DY"] + 7)
    if ap:
        z["APRS"] = (ax, D["DW_AP_DY"], ax + D["DW_AP_W"] - 1, D["DW_AP_DY"] + D["DW_AP_H"] - 1)
    if arrow:
        z["arrow"] = arrow
    return z


def inside(p, zz):
    x0, y0, x1, y1 = zz
    return p[0] >= x0 and p[1] >= y0 and p[0] + p[2] - 1 <= x1 and p[1] + p[3] - 1 <= y1


def disjoint(a, b):
    return a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]


def analyse(D, line):
    prims = []
    for it in (line or "").split(";"):
        f = it.split(":", 6)
        if len(f) == 7:
            prims.append((int(f[1]), int(f[2]), int(f[3]), int(f[4]), f[0], int(f[5]), f[6]))
    tris = [p for p in prims if p[4] == "t"]
    arrow = None
    if tris:
        x0 = min(p[0] for p in tris); y0 = min(p[1] for p in tris)
        x1 = max(p[0] + p[2] - 1 for p in tris); y1 = max(p[1] + p[3] - 1 for p in tris)
        cx = (x0 + x1) // 2
        arrow = (cx - 5 + 1, D["DW_ARROW_DY"], cx - 5 + 10, D["DW_ARROW_DY"] + 9)   # комірка LC_ARROW_CELL 10x10 навколо наконечника
    un = any(p[4] == "T" and p[6] == "D" and p[0] == D["DW_UN_X"] for p in prims)
    ap = any(p[4] == "f" and p[2] == D["DW_AP_W"] and p[3] == D["DW_AP_H"] for p in prims)
    z = zones(D, un, ap, arrow)
    bad = []
    for p in prims:
        if p[4] == "r" and p[0] == D["DW_CARD_X"] and p[1] == 0 and p[2] == D["DW_CARD_W"] and p[3] == D["DW_CARD_H"]:
            continue   # рамка картки
        hits = [k for k, zz in z.items() if zz and inside(p, zz)]
        if not hits:
            bad.append(p)
    names = [k for k in z if z[k]]
    ov = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if not disjoint(z[a], z[b])]
    txt = [p[6] for p in prims if p[4] == "T"]
    return prims, z, bad, ov, txt, arrow


def test_layout(t, src):
    if "#define DW_ROW1_DY" in src:
        print("ПРОПУСК: Б2/Б3 -- розкладку 5 рядків R98-FIX5 замінено в R98-FIX6 Г (4 рядки); зони, накладання й вміст перевіряє tools/test_r98fix6.py")
        return None
    D = consts(src)
    need = ["DW_CARD_X", "DW_CARD_W", "DW_CARD_H", "DW_CARD_A_Y", "DW_CARD_B_Y", "DW_IN_R", "DW_LET_BOX_X", "DW_LET_BOX_DY", "DW_LET_BOX_W", "DW_LET_BOX_H", "DW_LET_X", "DW_LET_DY",
            "DW_TXT_X", "DW_FULL_X", "DW_LINE1_DY", "DW_LINE2_DY", "DW_LINE3_DY", "DW_LINE3_MAX", "DW_LOCK_X", "DW_LOCK_DY", "DW_LINE4_DY", "DW_LINE4_MAX", "DW_ARROW_DY",
            "DW_METER_DY", "DW_METER_H", "DW_TAG_W", "DW_METER_X", "DW_METER_SEG_W", "DW_METER_STEP", "DW_METER_SEGS", "DW_METER_HOT", "DW_UN_X", "DW_UN_ENV_X", "DW_UN_NUM_X", "DW_UN_W",
            "DW_AP_W", "DW_AP_DY", "DW_AP_H", "DW_AP_X_ALONE", "DW_AP_X_WITH_D", "DW_AP_RES"]
    check(all(k in D for k in need), "Б3: усі константи розкладки DW_* знайдено й обчислено: нема %s" % [k for k in need if k not in D])
    if not all(k in D for k in need):
        return
    g = type("G", (), D)
    check(g.DW_CARD_A_Y == 11 and g.DW_CARD_B_Y + g.DW_CARD_H == 128 and g.DW_CARD_B_Y >= g.DW_CARD_A_Y + g.DW_CARD_H, "Б2: дві рівні картки (57 px) під шапкою, без накладання, B до y=127")
    check(g.DW_IN_R == g.DW_CARD_X + g.DW_CARD_W - 3, "Б3: остання внутрішня колонка -- на 1 px лівіше рамки")
    check(g.DW_LET_X >= g.DW_LET_BOX_X + 1 and g.DW_LET_X + 8 <= g.DW_LET_BOX_X + g.DW_LET_BOX_W - 1 and g.DW_LET_DY + 16 <= g.DW_LET_BOX_DY + g.DW_LET_BOX_H - 1 and g.DW_LET_BOX_X + g.DW_LET_BOX_W < g.DW_TXT_X,
          "Б2: мала літера 8x16 (половина 16x32) у рамці 10x18, лівіше рядків 1-2")
    check(g.DW_LET_BOX_DY + g.DW_LET_BOX_H - 1 < g.DW_LINE3_DY, "Б2: рамка літери закінчується над рядком 3 (рядки 3-5 -- на всю ширину)")
    check(g.DW_LINE1_DY + 8 <= g.DW_LINE2_DY and g.DW_LINE2_DY + 16 <= g.DW_LOCK_DY and g.DW_LINE2_DY + 16 <= g.DW_LINE3_DY and g.DW_LOCK_DY + 9 <= g.DW_ARROW_DY and g.DW_LINE3_DY + 8 <= g.DW_ARROW_DY and
          g.DW_ARROW_DY + 10 <= g.DW_METER_DY and g.DW_LINE4_DY >= g.DW_ARROW_DY and g.DW_LINE4_DY + 8 <= g.DW_ARROW_DY + 10 and g.DW_METER_DY + g.DW_METER_H <= g.DW_CARD_H - 1 and g.DW_AP_DY >= 1,
          "Б3: рядки 1 (8), 2 (16), 3 (8) / замок (9), 4 (8, стрілка 10), 5 (S-метр) по вертикалі не перетинаються й лишаються в картці")
    check(g.DW_TXT_X + 16 * 8 - 1 <= g.DW_IN_R and g.DW_FULL_X + g.DW_LINE3_MAX * 6 <= g.DW_LOCK_X and g.DW_LOCK_X + 10 <= g.DW_IN_R + 1, "Б3: рядок 2 (16 символів 8x16) і рядок 3 (до 23 символів) не заходять на замок / за край")
    last = g.DW_METER_X + (g.DW_METER_SEGS - 1) * g.DW_METER_STEP + g.DW_METER_SEG_W - 1
    check(g.DW_FULL_X + g.DW_TAG_W <= g.DW_METER_X and last <= g.DW_IN_R and g.DW_METER_SEG_W <= g.DW_METER_STEP and g.DW_METER_SEGS == 11 and g.DW_METER_HOT == 2,
          "Б2: S-метр на всю ширину картки: мітка RX x=%d..%d, 11 сегментів x=%d..%d (з них 2 останні червоні -- S9+10/S9+20)" % (g.DW_FULL_X, g.DW_FULL_X + g.DW_TAG_W - 1, g.DW_METER_X, last))
    check(g.DW_UN_X + 6 < g.DW_UN_ENV_X and g.DW_UN_ENV_X + 8 < g.DW_UN_NUM_X and g.DW_UN_NUM_X + 6 - 1 == g.DW_IN_R and g.DW_AP_X_ALONE + g.DW_AP_W - 1 == g.DW_IN_R and
          g.DW_AP_X_WITH_D + g.DW_AP_W < g.DW_UN_X and g.DW_IN_R + 1 - g.DW_UN_X < g.DW_UN_W and g.DW_AP_RES >= g.DW_AP_W + 2,
          "Б2: значки праворуч у рядку 1: SMS «D» x=%d..%d; APRS сам x=%d..%d, поряд з «D» x=%d..%d -- без накладання" % (g.DW_UN_X, g.DW_IN_R, g.DW_AP_X_ALONE, g.DW_IN_R, g.DW_AP_X_WITH_D, g.DW_AP_X_WITH_D + g.DW_AP_W - 1))
    fns = [T.carve_fn(t, s) for s in ROW_SIGS]
    tl = T.pp(FW, INCS, CF["DUALCH"], "application/source/functions/lc_distance.c") or ""
    fa = T.carve_fn(tl, "void lcDistArrowAfter(lcDistArrow_t *a, const lcDistSpan_t *tail, const lcDistSpan_t *above, int16_t screenW, uint16_t bearingDeg)")
    check(all(fns) and fa is not None, "Б2: функції картки і lcDistArrowAfter знайдено: %s" % [s.split("(")[0] for s, f in zip(ROW_SIGS, fns) if not f])
    if not (all(fns) and fa):
        return
    code = lambda f: ROW_HARNESS.replace("@@FNS@@", fa + "\n" + "\n".join(f))
    out = run_c(code(fns))
    check(out is not None, "Б2: хостова збірка карток")
    o = kv(out)
    res = {}
    for k in ("a1", "b1", "b2", "b3", "b4", "a2", "a3", "a4"):
        prims, z, bad, ov, txt, arrow = analyse(D, o.get(k))
        res[k] = (prims, txt, arrow)
        check(o.get(k) is not None and not bad and not ov, "Б3 (%s): кожен елемент -- у своїй зоні картки, зони не перетинаються: поза зонами %s, перетини %s" % (k, bad[:3], ov))
    p, txt, arrow = res["a1"]
    check(len(txt) >= 6 and txt[0] == "A" and txt[1].startswith("39 WWWW") and len(txt[1]) == (D["DW_IN_R"] + 1 - D["DW_TXT_X"] - D["DW_UN_W"]) // 6 and "D" in txt and "3" in txt,
          "Б2 (a1): рядок 1 «номер назва» обрізаний перед значком «D» (%d символів), значок «D» з числом: %s" % ((D["DW_IN_R"] + 1 - D["DW_TXT_X"] - D["DW_UN_W"]) // 6, txt))
    check("CALLSIGN NAME 16" in txt and any(x.startswith("TS") and "CC15" in x and "TG 91" in x for x in txt) and any(x == "DMR P4W 1234km" for x in txt) and arrow is not None,
          "Б2 (a1): рядок 2 -- абонент, рядок 3 -- TS/CC/ТГ виклику, рядок 4 -- режим + потужність каналу (рівень 5 -> P4) + відстань, стрілка одразу після: %s" % txt)
    lt = [x for x in p if x[4] == "T" and x[6] == "A"][0]
    lb = [x for x in p if x[0] == D["DW_LET_BOX_X"] and x[2] == D["DW_LET_BOX_W"]]
    check(lt[5] == 1 and lb and lb[0][4] == "f", "Б2 (a1): обрана картка -- рамка літери залита, літера інверсна")
    check(any(x[4] == "k" for x in p) and any(x[4] == "T" and x[6] == "RX" for x in p), "Б2 (a1): замок AES і S-метр (активна)")
    if arrow:
        r4 = [x for x in p if x[4] == "T" and x[6].startswith("DMR")][0]
        check(arrow[0] - (r4[0] + r4[2]) == 2 + 1 or arrow[0] - (r4[0] + r4[2]) in (2, 3), "Б2 (a1): стрілка -- одразу після тексту рядка 4 (зазор LC_ARROW_GAP): текст до x=%d, комірка від x=%d" % (r4[0] + r4[2] - 1, arrow[0]))
    segs = [x for x in p if x[4] in "fr" and x[2] == D["DW_METER_SEG_W"] and x[3] == D["DW_METER_H"]]
    check(len(segs) == D["DW_METER_SEGS"], "Б2 (a1): S-метр -- %d сегментів: %d" % (D["DW_METER_SEGS"], len(segs)))
    p, txt, arrow = res["b1"]
    lt = [x for x in p if x[4] == "T" and x[6] == "B"][0]
    lb = [x for x in p if x[0] == D["DW_LET_BOX_X"] and x[2] == D["DW_LET_BOX_W"]]
    check(lt[5] == 0 and lb and lb[0][4] == "r", "Б2 (b1): не обрана -- рамка літери контуром, літера звичайна")
    check("A+" in txt and "D" in txt and "2" in txt and any(x.startswith("11 WWW") for x in txt) and not any(x[6] == "RX" for x in p),
          "Б2 (b1): «D» (картка-джерело B) і APRS «A+» разом, рядок 1 обрізаний перед обома, неактивна -- без S-метра: %s" % txt)
    check(any(x == "FM 145.50000" for x in txt) and any(x.startswith("RD023N T67.0 25k") for x in txt) and any(x == "FM P7W" for x in txt),
          "Б2 (b1): FM -- частота в рядку 2, тони RX/TX + смуга в рядку 3, рядок 4 -- «FM» + загальна потужність (P7W): %s" % txt)
    p, txt, arrow = res["b2"]
    check(any(x.startswith("VFO B 430.12500") for x in txt) and "A1" in txt and any(x == "DMR P7W" for x in txt) and any(x[6] == "RX" for x in p),
          "Б2 (b2): картка VFO B -- «VFO B частота», ТГ VFO, рядок 4 -- загальна потужність, S-метр: %s" % txt)
    p, txt, arrow = res["b3"]
    check("1234567890123456" in txt, "Б2 (b3): поле набору -- у рядку 2 картки з покажчиком: %s" % txt)
    check("TG Four" in res["b4"][1] and "TG Two" not in res["b4"][1], "А2/Б2 (b4): картка B (рація на A) показує свій ТГ (s_dualTgIdxB), не ТГ A: %s" % res["b4"][1])
    check("TG Ukraine 255" in res["a2"][1] and "TG Four" not in res["a2"][1], "А2/Б2 (a2): картка A (рація на A) -- ТГ з індексу налаштувань (0 -> перший у списку), не ТГ B: %s" % res["a2"][1])
    check("DMR P2W" in res["a3"][1], "Б2 (a3): незбережена правка A (потужність у канальному буфері) -- видно на картці (DMR P2W): %s" % res["a3"][1])
    check(res["a4"][2] is None and "DMR P4W 1234km" in res["a4"][1], "Б2 (a4): азимут не визначений -- відстань без стрілки: %s" % res["a4"][1])
    # мутанти
    rr = fns[-1]
    muts = (("рядок 1 не обрізається перед значками", "b1", rr.replace("l1[l1max] = 0;", ";")),
            ("APRS завжди праворуч (на місці «D»)", "b1", rr.replace("int16_t ax = ((un > 0U) ? 119 : 143);", "int16_t ax = 143;")),
            ("ТГ B береться зі спільного індексу", "b4", None))
    for what, key, m in muts:
        f2 = list(fns)
        if m is None:
            f2[9] = re.sub(r"return \(isB \? \(int16_t\)s_dualTgIdxB : s_dualTgIdxA\);", "return nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];", fns[9])
            mo = kv(run_c(code(f2)))
            check(f2[9] != fns[9] and "TG Four" not in (mo.get(key) or ""), "Б2 (мутант): %s -- ловиться" % what)
            continue
        f2[-1] = m
        mo = kv(run_c(code(f2)))
        _p, _z, bad, ov, _t, _a = analyse(D, mo.get(key))
        check(m != rr and (bad or ov), "Б3 (мутант): %s -- накладання ловиться" % what)
    mr = fns[2].replace("for (int i = 1; i <= 11; i++)", "for (int i = 1; i <= 12; i++)")
    f2 = list(fns); f2[2] = mr
    mo = kv(run_c(code(f2)))
    _p, _z, bad, ov, _t, _a = analyse(D, mo.get("a1"))
    check(mr != fns[2] and bad, "Б3 (мутант): 12-й сегмент S-метра за краєм картки -- ловиться")
    return D


def test_header(src, uu):
    hd = src[src.find("static void dualRenderHeader(bool force)\n{"):]
    hd = hd[:hd.find("\n}\n")]
    check("uiUtilityRenderHeaderDw(force);" in hd and "codeplugChannelGetDataForIndex" not in hd, "Б1: шапка режиму -- uiUtilityRenderHeaderDw (лише «DW», заряд, час) у будь-якому стані")
    hh = src[src.find("bool uiChannelModeDualHeader(bool force)\n{"):]
    hh = hh[:hh.find("\n}\n")]
    check("uiChannelModeDualScreenShown() == false" in hh, "Б1: applicationMain малює шапку режиму щоразу, коли показано екран режиму (і під час виклику)")
    core = uu[uu.find("static void uiUtilityRenderHeaderCore("):uu.find("void uiUtilityRenderHeader(bool isVFODualWatchScanning, bool isVFOSweepScanning, bool forceBatteryDisplay)\n{")]
    a = core.find("if (dwOnly)"); b = core.find("switch(radioMode)"); c = core.find("// Power"); d = core.find("}   // R98-FIX5 Б1"); e = core.find("// Display battery percentage/voltage")
    check(0 < a < b < c < d < e and '"DW"' in core[a:b] and "(dwOnly == false)" in core[e:e + 900] or ("&& (dwOnly == false)" in core),
          "Б1: у шапці режиму режим/TS/тони/APRS/потужність/CC пропущено (блок else), «DW» ліворуч, GPS не показано, заряд і час -- стокові")
    check("uiHeaderOverride_t ov = { .ch = NULL" in uu, "Б1: шапка режиму -- ov.ch == NULL (ознака dwOnly), нових статичних змінних нема")


def test_v(tv, tvn, vsrc, ms):
    en = ms[ms.find("enum VFO_SCREEN_QUICK_MENU_ITEMS"):]
    en = en[:en.find("};")]
    check("VFO_SCREEN_QUICK_MENU_DUAL_CHANNEL" not in en and "VFO_SCREEN_QUICK_MENU_DUAL_CHANNEL" not in vsrc, "В2: пункт «Подв. прийом» у кінці швидкого меню VFO прибрано (останній -- номери не зсуваються)")
    check(en.find("VFO_SCREEN_QUICK_MENU_TONE_SCAN,") < en.find("VFO_SCREEN_QUICK_MENU_DUAL_SCAN,") < en.find("VFO_SCREEN_QUICK_MENU_FREQ_BIND_MODE,"), "В1: стоковий пункт «Dual Watch» -- на своєму місці")
    mq = re.search(r"case VFO_SCREEN_QUICK_MENU_DUAL_SCAN:\s*menuDataGlobal\.menuOptionsTimeout = 0;", tv)
    seg = tv[mq.start():mq.start() + 300] if mq else ""
    check(mq is not None and "menuSystemPopPreviousMenu();" in seg and "vfoDualStart();" in seg and seg.find("vfoDualStart();") < seg.find("return;"),
          "В1: у збірці з режимом пункт «Dual Watch» -- назад на екран VFO і vfoDualStart() (як довге ▼): наш режим")
    rq = tv[tv.find("static void updateQuickMenuScreen("):]
    j = rq.find("case VFO_SCREEN_QUICK_MENU_DUAL_SCAN:")
    check(j > 0 and "currentLanguage->dual_watch" in rq[j:j + 120], "В1: підпис пункту той самий («Dual Watch», стокове мовне поле)")
    check(re.search(r"scanType = SCAN_TYPE_DUAL_WATCH", tv) is None and re.search(r"=\s*VFO_SCREEN_OPERATION_DUAL_SCAN\s*;", tv) is None,
          "В3: у збірці з режимом стоковий Dual Watch не вмикається ніде (нема присвоєнь SCAN_TYPE_DUAL_WATCH / VFO_SCREEN_OPERATION_DUAL_SCAN) -- решта його гілок мертва")
    check("Select and set the next VFO" not in vsrc[vsrc.find("#if !defined(DUAL_CHANNEL_ENABLED)   // R98-FIX5 В3: у збірці"):][:30] and
          "nonVolatileSettings.currentVFONumber = (1 - nonVolatileSettings.currentVFONumber);" not in tv and "settingsVFOChannel[CHANNEL_VFO_B].rxFreq, 1, 1, 2);" not in tv,
          "В3: двигун (перемикання VFO A<->B у scanning()) і екран двох частот у збірці з режимом вирізано")
    check("uiVFOModeDualWatchIsScanning" not in tv.replace("uiVFOModeDualWatchIsScanning()", "") or "bool uiVFOModeDualWatchIsScanning(void)\n{" not in tv,
          "В3: uiVFOModeDualWatchIsScanning у збірці з режимом -- макрос false (виклики згортаються)")
    check(re.search(r"scanType = SCAN_TYPE_DUAL_WATCH", tvn or "") is not None and "nonVolatileSettings.currentVFONumber = (1 - nonVolatileSettings.currentVFONumber);" in (tvn or ""),
          "В3: без прапорця стоковий Dual Watch на місці")
    vd = vsrc[vsrc.find("static void vfoDualStart(void)\n{"):]
    vd = vd[:vd.find("\n}\n")]
    check("VFO_SCREEN_OPERATION_NORMAL" in vd and "uiDataGlobal.Scan.active" in vd and "uiChannelModeDualEnableFromVfo(" in vd, "В1: vfoDualStart -- не під час сканування частот/розгортки (звук помилки), інакше вмикання з VFO")


def test_tokens():
    """Без прапорця -- токени змінених файлів як у базі 7205514 (з фільтром r96_tokfilter: channelTgStep/channelSquelchStep розгортаються)."""
    if not base_available():
        print("ПРОПУСК: база %s недоступна (CI/клон без історії): порівняння токенів з базою не виконано" % BASE)
        return
    from r96_tokfilter import strip_r96
    root = tempfile.mkdtemp(prefix="r98f5b_")
    try:
        subprocess.run("git -C %s archive %s MDUV380_firmware | tar -x -C %s" % (os.path.dirname(FW), BASE, root), shell=True, check=True)
        broot = os.path.join(root, "MDUV380_firmware")
        files = ["application/source/user_interface/uiChannelMode.c", "application/source/user_interface/uiVFOMode.c", "application/source/user_interface/uiUtilities.c",
                 "application/source/applicationMain.c", "application/source/user_interface/menuSystem.c"]
        for name in ("AES0", "ENDATA", "UA"):
            bad = [rel for rel in files if strip_r96((T.pp(FW, INCS, CF[name], rel) or "").encode()).split() != strip_r96((T.pp(broot, INCS, CF[name], rel) or "").encode()).split()]
            check(bad == [], "В3/Б1: %s (без прапорця): токени як у базі %s: %r" % (name, BASE, bad))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_static(src):
    ru = src[src.find("bool dwRunning = dualIsRunning();"):src.find("if (uiDataGlobal.Scan.active && (ev->events & KEY_EVENT))")]
    check(re.search(r"if \(dcIsEnabled\(\)\)\s*\{\s*if \(dualHandleKey\(ev\)\)", ru) is not None and "bool toB = (dcPointerB() && (dualSingle() == false));" in ru,
          "А0/А5: у режимі всі клавіші -- спершу dualHandleKey; решта -- на картку з покажчиком (A == B -- A)")
    st = src[src.find("static uint8_t  s_dualTgIdxB;"):][:900]
    check("static uint8_t  s_dualBKeep;" in st and "static uint8_t  s_dualZoneB;" in st and "s_dualSqlB" not in src.replace("замість s_dualSqlB", ""),
          "А2/А3/А5: RAM -- три однобайтні змінні (ТГ B, ознака копії B, зона B); s_dualSqlB прибрано (його роль -- у копії B)")
    sw = src[src.find("static void dualSwapBufs(void)\n{"):]
    sw = sw[:sw.find("\n}\n")]
    check("CodeplugChannel_t t" not in sw and "uint8_t t = a[i];" in sw, "А5: обмін буферів -- побайтово, без тимчасового запису на стеку/в RAM (нових буферів нема)")
    check(src.count("dualSwapBufs();") >= 4, "А5: обмін у dualTune (B->VFO, A->B, B->A) і при A: канал -> VFO (dualStepA)")


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    global INCS, CF
    INCS, cfgs = cmt.load_configs(FW)
    CF = dict(cfgs)
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    vsrc = T.rd(os.path.join(UI, "uiVFOMode.c"))
    uu = T.rd(os.path.join(UI, "uiUtilities.c"))
    ms = T.rd(os.path.join(APP, "include", "user_interface", "menuSystem.h"))
    t = T.pp(FW, INCS, CF["DUALCH"], "application/source/user_interface/uiChannelMode.c") or ""
    tv = T.pp(FW, INCS, CF["DUALCH"], "application/source/user_interface/uiVFOMode.c") or ""
    tvn = T.pp(FW, INCS, CF["AES0"], "application/source/user_interface/uiVFOMode.c") or ""
    tdc = T.pp(FW, INCS, CF["DUALCH"], "application/source/functions/dual_channel.c") or ""
    check(t != "" and tv != "" and tdc != "", "препроцесування uiChannelMode.c / uiVFOMode.c / dual_channel.c (DUALCH)")
    test_static(src)
    test_keys(t, src)
    test_tg_copy(t)
    test_zone(t, tdc)
    test_vfo(tv, t)
    test_layout(t, src)
    test_header(src, uu)
    test_v(tv, tvn, vsrc, ms)
    test_tokens()
    print("test_r98fix5: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


INCS = None; CF = None

if __name__ == "__main__":
    sys.exit(main())
