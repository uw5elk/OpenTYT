#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX7 (хост): «Подвійний прийом» -- ручка лише по каналах, червона = канал <-> VFO; «Мін.гучність» -- коліно K = 32 (одна константа).
  А   СПРАВЖНІ dualHandleKey()/dualIsVfoStepKey()/dualIsSquelchKey(): ручка на картці-каналі -- канали (A -- стоковий крок зони, B -- dualStepB),
      ручка на картці-VFO -- частота (як ручка в стоковому VFO), з VFO на канал ручка не виводить; коротка червона -- dualRedToggle(), довга/PRESS -- без дій,
      SK1/SK2 + червона -- стокові; СПРАВЖНІ dualStepB() + dcStepPos()/dcFindPos(): коло B лише по каналах (VFO в колі нема); dcStepExt/dualStepA прибрано
  Б   СПРАВЖНІ dualRedToggle()/dualTune()/dualSwapBufs()/dualBCopyValid()/dualBReset() з моделлю блоку 18 (тип A, тип B, номер B): A канал <-> VFO A,
      B канал <-> VFO B, повернення на той самий канал, дві картки незалежно, A == B, старий запис «B = VFO A», видалений канал B; набір цифр має пріоритет
      (dualEntryKey раніше за dualHandleKey); мутанти «червона на B перемикає A», «тип VFO затирає номер B», «повернення на інший канал»
  В   volume_low_logic.h: K = VOLLOW_KNEE = 32 (одне місце), неперервність у n = K, монотонність повного рівня (DMR/FM), межі таблиць; таблиця В3 для K 16/24/32
Запуск: python3 tools/test_r98fix7.py"""
import os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
import test_r98fix5 as F5  # noqa  (гарнес таблиці клавіш; F5 сам вимикає частину compat)
T.COMPAT_A_CHANNEL = False
T.COMPAT_FIX4 = False
T.COMPAT_FIX5 = False
T.COMPAT_FIX6 = False   # бачимо поточні функції (R98-FIX7)
cmt = T.cmt
FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
FN = os.path.join(APP, "source", "functions")
INC = os.path.join(APP, "include")


def run_c(code, inc=False):
    d = tempfile.mkdtemp(prefix="r98f7_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w"] + (["-I", INC] if inc else []) + ["-o", os.path.join(d, "h"), c, "-lm"], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:3000]); return None
        return subprocess.run([os.path.join(d, "h")], capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


kv = F5.kv


# ------------------------------------------------------------------------------------------------ А: таблиця клавіш
KEY_HARNESS = F5.KEY_HARNESS
KEY_HARNESS = KEY_HARNESS.replace('static bool dualStepA(int d) { L("A%+d", d); return stepAret; }', 'static void dualRedToggle(void) { L("X"); }')
KEY_HARNESS = KEY_HARNESS[:KEY_HARNESS.index("int main(void)")] + r"""int main(void)
{
	int SU = 0x02, PR = 0x01, LD = 0x01 | 0x04, LR = 0x01 | 0x04 | 0x08;
	ptrB = 1; P("n1", go(0, 8, SU));                                         /* ручка на B = канал -- канали картки B */
	ptrB = 0; P("n2", go(0, 7, SU));                                         /* ручка на A = канал -- стоковий крок каналу зони (без VFO) */
	ptrB = 0; aVfo = 1; onB = 0; P("n3", go(0, 8, SU));                      /* ручка на A = VFO -- частота VFO A, з VFO не виходить */
	aVfo = 0; ptrB = 1; bVfo = 1; onB = 0; P("n4", go(0, 7, SU));            /* ручка на B = VFO -- рація на B, частота VFO B (униз) */
	onB = 0; P("n5", go(SK2, 8, SU));                                        /* SK2 + ручка на B = VFO -- те саме, що з R98 (крок частоти) */
	onB = 0; P("n6", go(SK1, 8, SU)); bVfo = 0; onB = 0;                     /* SK1 + ручка -- параметр прийому (не частота) */
	ptrB = 1; P("n7", go(0, 8, PR));                                         /* PRESS ручки -- без дій */
	ptrB = 0; P("r1", go(0, 27, SU));                                        /* коротка червона -- канал <-> VFO */
	ptrB = 1; P("r2", go(0, 27, SU));
	P("r3", go(0, 27, PR)); P("r4", go(0, 27, LD)); P("r5", go(0, 27, LR)); /* PRESS / довга / автоповтор -- з'їдаються без дій */
	P("r6", go(SK1, 27, SU)); P("r7", go(SK2, 27, SU));                      /* SK1/SK2 + червона -- стокові (тема день/ніч, повернення ТГ після PC) */
	ptrB = 1; single = 1; P("r8", go(0, 27, SU)); single = 0;                /* A == B: червона -- теж наша */
	return 0;
}
"""
KEY_EXP = {"n1": "1:B+1", "n2": "1:S,D,R", "n3": "1:S,V0+1", "n4": "1:S,T1,V1-1", "n5": "1:S,T1,V1+1", "n6": "1:Q+1", "n7": "1:",
           "r1": "1:X", "r2": "1:X", "r3": "1:", "r4": "1:", "r5": "1:", "r6": "0:", "r7": "0:", "r8": "1:X"}
KEY_NAMES = {"n1": "ручка на B = канал -- крок по каналах B", "n2": "ручка на A = канал -- стоковий крок каналу зони, без кола VFO",
             "n3": "ручка на A = VFO -- частота VFO A (з VFO на канал не виводить)", "n4": "ручка на B = VFO -- частота VFO B",
             "n5": "SK2 + ручка на картці VFO -- крок частоти (як з R98)", "n6": "SK1 + ручка -- шумодав/ТГ", "n7": "PRESS ручки -- без дій",
             "r1": "червона, покажчик на A -- канал <-> VFO", "r2": "червона, покажчик на B -- канал <-> VFO", "r3": "PRESS червоної -- без дій",
             "r4": "довга червона -- без дій", "r5": "автоповтор червоної -- без дій", "r6": "SK1 + червона -- стоковий обробник", "r7": "SK2 + червона -- стоковий обробник",
             "r8": "A == B -- червона теж перемикає"}


def test_keys(t, src):
    sigs = ["static _Bool dualIsVfoStepKey(const uiEvent_t *ev)", "static _Bool dualIsSquelchKey(const uiEvent_t *ev)", "static _Bool dualHandleKey(uiEvent_t *ev)"]
    fns = [T.carve_fn(t, s) for s in sigs]
    hb = F5.hook_block(t)
    check(all(fns) and hb is not None, "А: dualHandleKey / dualIsVfoStepKey / dualIsSquelchKey знайдено")
    if not (all(fns) and hb):
        return
    code = lambda f: KEY_HARNESS.replace("@@FNS@@", "\n".join(f)).replace("@@HOOK@@", hb)
    out = run_c(code(fns))
    check(out is not None, "А: хостова збірка таблиці клавіш")
    o = kv(out)
    for k, v in KEY_EXP.items():
        check(o.get(k) == v, "А/Б (%s): %s -- очікувано «%s», є «%s»" % (k, KEY_NAMES[k], v, o.get(k)))
    vk, hk = fns[0], fns[2]
    muts = (("ручка на картці VFO знову лише з SK2 -- ручка виходить з VFO на канали (старе коло)", "n4", 0,
             vk.replace("((((ev)->buttons & 0x00000002)) == 0) &&", "(((ev)->buttons & 0x00000020) != 0) && ((((ev)->buttons & 0x00000002)) == 0) &&")),
            ("червона з'їдається без дій (як до R98-FIX7)", "r1", 2, hk.replace("dualRedToggle();", ";")),
            ("довга червона теж перемикає", "r4", 2, hk.replace("if (((ev->keys.key == 27) && ((ev->keys.event & (0x02 | 0x04)) == 0x02)))\n   {\n    dualRedToggle();", "if (1)\n   {\n    dualRedToggle();")))
    for what, key, idx, m in muts:
        src_f = fns[idx]
        f2 = list(fns); f2[idx] = m
        mo = kv(run_c(code(f2))) if m != src_f else {}
        check(m != src_f and mo.get(key) not in (None, KEY_EXP[key]), "А/Б (мутант): %s -- ловиться" % what)
    # набір цифр має пріоритет: dualEntryKey -- раніше за dualHandleKey; червона в наборі -- скасування (dualEntryEnd), не перемикання
    i = src.find("static void handleEventCore(uiEvent_t *ev)")
    blk = src[i:i + 4000] if i >= 0 else ""
    check(0 < blk.find("if (dualEntryKey(ev))") < blk.find("if (dualHandleKey(ev))"), "Б4: набір цифр (dualEntryKey) обробляється раніше за правила режиму (dualHandleKey) -- червона в наборі не доходить до перемикання")
    ek = T.carve_fn(t, "static _Bool dualEntryKey(uiEvent_t *ev)") or ""
    m = re.search(r"\(sk == 0\) && \(\(ev->keys\.key == 27\)[^\n]*\n\s*\{(.*?)\n \}", ek, re.S)
    check(m is not None and "dualEntryEnd();" in m.group(1) and "dualRedToggle" not in ek, "Б4: червона під час набору -- dualEntryEnd() (скасування), dualRedToggle не викликається")


# ------------------------------------------------------------------------------------------------ А1: коло B лише по каналах
RING_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
typedef struct { int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_highestIndex; int NOT_IN_CODEPLUGDATA_indexNumber; uint16_t channels[16]; char name[16]; } CodeplugZone_t;
typedef uint16_t (*dcChanAt_t)(int pos, void *ctx);
#define CODEPLUG_ZONE_IS_ALLCHANNELS(z) ((z).NOT_IN_CODEPLUGDATA_indexNumber < 0)
enum { MELODY_ERROR_BEEP = 1 };
enum { SCAN_STATE_SCANNING = 2 };
static CodeplugZone_t currentZone;
static struct { struct { int state; } Scan; } uiDataGlobal;
static int used[1100], chB = 12, typeB = 0, beep = 0, onB = 0, running = 1, lastA = 5;
static uint32_t s_dualKeyMs;
static uint16_t dualZoneChannelAt(int pos, void *ctx) { const CodeplugZone_t *z = ctx ? (const CodeplugZone_t *)ctx : &currentZone; return (pos >= 0 && pos < z->NOT_IN_CODEPLUGDATA_numChannelsInZone && used[z->channels[pos]]) ? z->channels[pos] : 0; }
static const CodeplugZone_t *dualZoneB(CodeplugZone_t *b) { (void)b; return NULL; }
static uint16_t dcChannelB(void) { return (uint16_t)chB; }
static uint16_t dualChannelA(void) { return (uint16_t)lastA; }
static bool dcSetChannelB(uint16_t c, bool p) { (void)p; chB = c; typeB = 0; return true; }
static void dcSetTypeB(uint8_t t) { typeB = t; }
static bool dcBIsVfo(void) { return typeB != 0; }
static void dualBReset(void) {}
static bool dualIsRunning(void) { return running; }
static void dualAutoResume(void) {}
static bool dcIsOnB(void) { return onB; }
static void dualTune(bool b) { (void)b; }
static void dualSetDwell(void) {}
static void soundSetMelody(int m) { (void)m; beep++; }
@@DC@@
@@FNS@@
int main(void)
{
	static const uint16_t z[5] = { 5, 6, 7, 8, 12 };
	used[5] = used[7] = used[12] = 1;
	currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = 5; currentZone.NOT_IN_CODEPLUGDATA_indexNumber = 2; memcpy(currentZone.channels, z, sizeof(z));
	/* f: з 12 (останній) вперед -- 5, 7, 12, 5 (VFO у колі нема); тип лишається «канал» */
	chB = 12; printf("f="); for (int i = 0; i < 4; i++) { dualStepB(1); printf("%d%s", chB, (i < 3) ? "," : ""); }
	printf("\nb="); chB = 5; for (int i = 0; i < 4; i++) { dualStepB(-1); printf("%d%s", chB, (i < 3) ? "," : ""); }
	printf("\nt=%d,%d\n", typeB, beep);
	/* a: B == A дозволено (не пропускається): з 5 вперед -- 7, коли A = 7 */
	lastA = 7; chB = 5; dualStepB(1); printf("a=%d\n", chB); lastA = 5;
	/* o: B не з цієї зони (99) -- крок від A (5 -> 7) */
	chB = 99; dualStepB(1); printf("o=%d\n", chB);
	/* e: зона без придатних каналів -- звук помилки, B не змінюється */
	used[5] = used[7] = used[12] = 0; chB = 12; beep = 0; dualStepB(1); printf("e=%d,%d,%d\n", chB, typeB, beep);
	return 0;
}
"""
RING_EXP = {"f": "5,7,12,5", "b": "12,7,5,12", "t": "0,0", "a": "7", "o": "7", "e": "12,0,1"}


def test_ring(t, tdc):
    fb = T.carve_fn(t, "static void dualStepB(int dir)")
    dc = [T.carve_fn(tdc, s) for s in ("int dcStepPos(int n, int fromPos, int dir, uint16_t skip, dcChanAt_t at, void *ctx)", "int dcFindPos(int n, uint16_t ch, dcChanAt_t at, void *ctx)")]
    check(fb is not None and all(dc), "А1: dualStepB / dcStepPos / dcFindPos знайдено")
    if not (fb and all(dc)):
        return
    check("dcStepExt" not in fb and "DC_TYPE_VFO" not in fb and "dcSetTypeB" not in fb, "А1: dualStepB не виставляє тип VFO і не ходить колом з VFO")
    code = lambda f: RING_HARNESS.replace("@@DC@@", "\n".join(dc)).replace("@@FNS@@", f)
    out = run_c(code(fb))
    check(out is not None, "А1: хостова збірка кола B")
    o = kv(out)
    for k, v in RING_EXP.items():
        check(o.get(k) == v, "А1 (%s): коло ручки на B лише по каналах -- очікувано «%s», є «%s»" % (k, v, o.get(k)))
    # мутант: після останнього каналу -- VFO (старе коло R98)
    m = fb.replace("(void)dcSetChannelB(dualZoneChannelAt(pos, ctx), 0);", "if ((dir > 0) && (from == (n - 1))) { dcSetTypeB(1); } else { (void)dcSetChannelB(dualZoneChannelAt(pos, ctx), 0); }")
    mo = kv(run_c(code(m))) if m != fb else {}
    check(m != fb and (mo.get("f"), mo.get("t")) != (RING_EXP["f"], RING_EXP["t"]), "А1 (мутант): ручка на B виходить на VFO після останнього каналу -- ловиться")


# ------------------------------------------------------------------------------------------------ Б: червона = канал <-> VFO (справжні dualRedToggle + dualTune)
SETTERS = F5.SETTERS
TOGGLE_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
typedef struct { char name[16]; uint32_t rxFreq; uint32_t txFreq; uint8_t chMode; uint8_t libreDMR_Power; uint8_t sql; uint8_t rxGroupList; uint16_t contact; } CodeplugChannel_t;
enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
#define SETTINGS_CHANNEL_MODE 0
#define SETTINGS_VFO_A_MODE 1
#define CH_DETAILS_VFO_CHANNEL -1
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 };
enum { UI_CHANNEL_MODE = 3 };
enum { MELODY_ERROR_BEEP = 1 };
enum { DC_TYPE_CHANNEL = 0, DC_TYPE_VFO_A = 1, DC_TYPE_VFO_B = 2 };
struct { int16_t currentIndexInTRxGroupList[3]; uint32_t overrideTG; } nonVolatileSettings;
struct { char name[16]; int NOT_IN_CODEPLUG_numTGsInGroup; } currentRxGroupData;
struct { int displayQSOState; int currentSelectedChannelNumber; } uiDataGlobal;
@@SETTERS@@
static CodeplugChannel_t chans[20], settingsVFOChannel[2], channelScreenChannelData, scanNextChannelData, *currentChannelData = &channelScreenChannelData;
static int onB = 0, typeA = 0, typeB = 0, chB = 7, ptrB = 0, reads = 0, beep = 0, lastA = 3, used[32], resumes = 0, running = 0, suspends = 0;
static int16_t s_dualTgIdxA; static uint8_t s_dualTgIdxB, s_dualBKeep; static uint32_t s_dualKeyMs = 77;
static bool dcIsEnabled(void) { return true; }
static bool dcIsOnB(void) { return onB; }
static void dcSetOnB(bool b) { onB = b; }
static uint8_t dcTypeA(void) { return (uint8_t)typeA; }
static uint8_t dcTypeB(void) { return (uint8_t)typeB; }
static bool dcBIsVfo(void) { return typeB != 0; }
static bool dcAIsVfo(void) { return typeA != 0; }
static void dcSetTypeA(uint8_t t) { typeA = t; }
static void dcSetTypeB(uint8_t t) { typeB = t; }   /* як справжній: номер каналу B не чіпає */
static uint16_t dcChannelB(void) { return (uint16_t)chB; }
static bool dcPointerB(void) { return ptrB; }
static bool codeplugAllChannelsIndexIsInUse(int c) { return (c > 0) && (c < 32) && used[c]; }
static void dualSuspend(void) { suspends++; }
static void dualAutoResume(void) { resumes++; }
static bool dualIsRunning(void) { return running; }
static void lastHeardClearLastID(void) {}
static void dmrAesRxRetune(void) {}
static void codeplugChannelGetDataForIndex(int i, CodeplugChannel_t *c) { *c = chans[i]; reads++; }
static void uiChannelModeLoadChannelData(bool mem, bool x) { (void)x; if (!mem) { channelScreenChannelData = chans[lastA]; reads++; } }
static void uiVFOModeDualLoad(uint8_t v, bool f) { (void)f; currentChannelData = &settingsVFOChannel[v]; }
static void soundSetMelody(int m) { (void)m; beep++; }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
@@FNS@@
static void mk(int i, const char *nm, uint32_t f) { memset(&chans[i], 0, sizeof(chans[i])); memcpy(chans[i].name, nm, strlen(nm)); chans[i].rxFreq = f; chans[i].txFreq = f; chans[i].chMode = RADIO_MODE_DIGITAL; chans[i].libreDMR_Power = 1; used[i] = 1; }
static void setup(void)
{
	mk(3, "ChanA", 43300000); mk(7, "ChanB", 43400000); mk(9, "Other", 14500000);
	memset(settingsVFOChannel, 0, sizeof(settingsVFOChannel)); memcpy(settingsVFOChannel[0].name, "VfoA", 4); memcpy(settingsVFOChannel[1].name, "VfoB", 4);
	channelScreenChannelData = chans[3]; currentChannelData = &channelScreenChannelData; memset(&scanNextChannelData, 0, sizeof(scanNextChannelData));
	onB = 0; typeA = 0; typeB = 0; chB = 7; ptrB = 0; beep = 0; lastA = 3; resumes = 0; running = 0; s_dualKeyMs = 77; uiDataGlobal.displayQSOState = 0;
	s_dualTgIdxA = 0; s_dualTgIdxB = 0; s_dualBKeep = 0; nonVolatileSettings.currentIndexInTRxGroupList[0] = 0;
}
static const char *nm(void) { static char b[17]; memcpy(b, currentChannelData->name, 16); b[16] = 0; return b; }
static const char *at(bool b) { dualTune(b); return nm(); }
int main(void)
{
	/* a1: A = канал 3 (правка «потужність 9»), покажчик на A: червона -> VFO A; ще раз -> той самий канал 3 (з кодплага, як стоково: правка каналу на VFO не переноситься) */
	setup(); channelScreenChannelData.libreDMR_Power = 9; dualRedToggle(); printf("a1=%d,%s,%d,%d,%d", typeA, nm(), resumes, (int)s_dualKeyMs, uiDataGlobal.displayQSOState);
	dualRedToggle(); printf(",%d,%s,%d,%d\n", typeA, nm(), currentChannelData->libreDMR_Power, (currentChannelData == &channelScreenChannelData));
	/* b1: B = канал 7, покажчик на B, рація на A: червона -> тип B = VFO B, номер 7 лишається, рація не перестроюється; на B -- VFO B; ще раз -> канал 7 */
	setup(); ptrB = 1; dualRedToggle(); printf("b1=%d,%d,%d,%s", typeB, chB, onB, nm()); printf(",%s", at(1)); printf(",%s", at(0));
	dualRedToggle(); printf(",%d,%d", typeB, chB); printf(",%s\n", at(1));
	/* b2: рація на B (канал 7, правка B 5): червона -> одразу на VFO B; ще раз -> канал 7 з кодплага; A (правка 9) ціла */
	setup(); channelScreenChannelData.libreDMR_Power = 9; ptrB = 1; dualTune(1); currentChannelData->libreDMR_Power = 5; s_dualBKeep = 1;
	dualRedToggle(); printf("b2=%d,%s,%d", typeB, nm(), s_dualBKeep); dualRedToggle(); printf(",%d,%s,%d", typeB, nm(), currentChannelData->libreDMR_Power);
	printf(",%s", at(0)); printf(",%d\n", currentChannelData->libreDMR_Power);
	/* d1: дві картки незалежно: A -> VFO A, B -> VFO B; цикли A<->B; потім назад: A -> канал 3, B -> канал 7 */
	setup(); dualRedToggle(); ptrB = 1; dualRedToggle(); printf("d1=%d,%d", typeA, typeB);
	for (int i = 0; i < 2; i++) { printf(",%s", at(1)); printf(",%s", at(0)); }
	ptrB = 0; dualRedToggle(); ptrB = 1; dualRedToggle(); printf(",%d,%d,%d", typeA, typeB, chB); printf(",%s", at(0)); printf(",%s\n", at(1));
	/* e1: вхід з VFO B: A = VFO B, B = канал 7; червона на B -> B = VFO B (A == B, без збою); ще раз на B -> B знову канал 7, A не змінено */
	setup(); typeA = 2; currentChannelData = &settingsVFOChannel[1]; ptrB = 1; dualRedToggle(); printf("e1=%d,%d,%d", typeA, typeB, chB);
	dualRedToggle(); printf(",%d,%d,%d", typeA, typeB, chB); printf(",%s\n", at(1));
	/* o1: старий запис R98..R98-FIX5 «B = VFO A», номер 7: червона на B -> канал 7 (номер не втрачено) */
	setup(); typeB = 1; ptrB = 1; dualRedToggle(); printf("o1=%d,%d,%d", typeB, chB, beep); printf(",%s\n", at(1));
	/* x1: B = VFO B, закріплений канал видалено (або 0): звук помилки, лишаємось на VFO, нічого не перемикаємо */
	setup(); typeB = 2; chB = 9; used[9] = 0; ptrB = 1; resumes = 0; dualRedToggle(); printf("x1=%d,%d,%d,%d", typeB, chB, beep, resumes);
	setup(); typeB = 2; chB = 0; ptrB = 1; dualRedToggle(); printf(",%d,%d\n", typeB, beep); used[9] = 1;
	/* a2: A = VFO A, рація на B (виклик на B), покажчик на A: червона -> рація на A, канал 3 */
	setup(); typeA = 1; currentChannelData = &settingsVFOChannel[0]; dualTune(1); dualRedToggle(); printf("a2=%d,%d,%s\n", typeA, onB, nm());
	return 0;
}
"""
TOGGLE_EXP = {"a1": "1,VfoA,1,0,1,0,ChanA,1,1", "b1": "2,7,0,ChanA,VfoB,ChanA,0,7,ChanB", "b2": "2,VfoB,0,0,ChanB,1,ChanA,9",
              "d1": "1,2,VfoB,VfoA,VfoB,VfoA,0,0,7,ChanA,ChanB", "e1": "2,2,7,2,0,7,ChanB", "o1": "0,7,0,ChanB", "x1": "2,9,1,0,2,1", "a2": "0,0,ChanA"}
TOGGLE_NAMES = {"a1": "картка A: канал -> VFO A -> той самий канал (правка каналу на VFO не переноситься), чергування -- одразу",
                "b1": "картка B: канал -> VFO B (номер B лишається) -> канал 7; рація без активності не перестроюється",
                "b2": "картка B, рація на B: одразу на VFO B і назад на канал 7 з кодплага; правка A ціла",
                "d1": "A у VFO A і B у VFO B одночасно, чергування між ними; повернення -- на свої канали",
                "e1": "A = VFO B (вхід з екрана VFO B), червона на B -> A == B без збою; ще раз -- B знову канал 7",
                "o1": "старий запис «B = VFO A» -> червона -> закріплений канал 7",
                "x1": "закріплений канал B видалено / не задано -- звук помилки, лишаємось на VFO",
                "a2": "A = VFO A, рація на B, покажчик на A: червона -> рація на A, канал 3"}
TOGGLE_SIGS = ["static void dualSwapBufs(void)", "static _Bool dualBCopyValid(const CodeplugChannel_t *copy)", "static void dualBReset(void)",
               "static _Bool dualBufHoldsB(void)", "static uint8_t dualVfoIdx(void)", "static _Bool dualCardIsVfo(_Bool isB)", "static uint8_t dualCardVfo(_Bool isB)",
               "static _Bool dualOnVfoNow(void)", "static void dualTune(_Bool toB)", "static void dualRedToggle(void)"]


def test_toggle(t):
    fns = [T.carve_fn(t, s) for s in TOGGLE_SIGS]
    check(all(fns), "Б: dualRedToggle / dualTune / робоча копія B знайдено: %s" % [s.split("(")[0] for s, f in zip(TOGGLE_SIGS, fns) if not f])
    if not all(fns):
        return
    code = lambda f: TOGGLE_HARNESS.replace("@@SETTERS@@", SETTERS).replace("@@FNS@@", "\n".join(f))
    out = run_c(code(fns))
    check(out is not None, "Б: хостова збірка червоної (справжні dualRedToggle + dualTune)")
    o = kv(out)
    for k, v in TOGGLE_EXP.items():
        check(o.get(k) == v, "Б (%s): %s -- очікувано «%s», є «%s»" % (k, TOGGLE_NAMES[k], v, o.get(k)))
    rt = fns[-1]
    muts = (("червона на B перемикає A", "b1", rt.replace("if (dcPointerB())", "if (0)", 1)),
            ("тип VFO затирає номер каналу B", "b1", rt.replace("dcSetTypeB(2U);", "chB = 0; dcSetTypeB(2U);")),
            ("повернення A -- на інший канал", "a1", rt.replace("currentChannelData = &channelScreenChannelData;\n   uiChannelModeLoadChannelData(0, 1);", "currentChannelData = &channelScreenChannelData;\n   lastA = 9;\n   uiChannelModeLoadChannelData(0, 1);")),
            ("повернення B -- на VFO A замість каналу", "o1", rt.replace("dcSetTypeB(0U);", "dcSetTypeB(1U);")),
            ("A -> VFO B замість VFO A", "a1", rt.replace("dcSetTypeA(1U);", "dcSetTypeA(2U);")),
            ("видалений канал B не перевіряється", "x1", rt.replace("(codeplugAllChannelsIndexIsInUse(dcChannelB()) == 0)", "0")))
    for what, key, m in muts:
        f2 = list(fns); f2[-1] = m
        mo = kv(run_c(code(f2))) if m != rt else {}
        check(m != rt and mo.get(key) not in (None, TOGGLE_EXP[key]), "Б (мутант): %s -- ловиться" % what)


# ------------------------------------------------------------------------------------------------ А3: мертвий код кола прибрано
def test_dead(src):
    dcc = T.rd(os.path.join(FN, "dual_channel.c")); dch = T.rd(os.path.join(INC, "functions", "dual_channel.h"))
    vm = T.rd(os.path.join(UI, "uiVFOMode.c"))
    check("int dcStepExt(" not in dcc and "int dcStepExt(" not in dch and "dcStepExt(" not in src, "А3: dcStepExt (коло «канали -> VFO A -> VFO B») прибрано з прошивки")
    check("dualStepA" not in src, "А3: dualStepA прибрано (ручка на A = канал -- стоковий крок зони, на A = VFO -- частота)")
    check("червона в режимі\n// нічого не робить" not in src and "Клавішу з'їдаємо без дій -- стокова червона" not in src, "А3/Б6: коментарі «червона нічого не робить» оновлено")
    check("void uiVFOModeDualStep(uint8_t vfo, int dir)" in vm, "А2: крок частоти картки VFO -- стокова stepFrequency через uiVFOModeDualStep (як ручка в стоковому VFO)")


# ------------------------------------------------------------------------------------------------ В: гучність, K = 32
VOL_C = r"""
#include <stdio.h>
#include "functions/volume_low_logic.h"
int main(void)
{
	static const int ks[3] = { 16, 24, 32 }, ns[10] = { 0, 2, 4, 8, 12, 16, 20, 24, 28, 31 };
	for (int a = 0; a < 3; a++)
	{
		int K = ks[a];
		printf("K%d=", K);
		for (int i = 0; i < 10; i++) { int xd = vlExtraDb(ns[i], K, 36), xf = vlExtraDb(ns[i], K, 23); printf("%d/%d/%02X%s", xd, xf, vlFmLow(xf), (i < 9) ? "," : ""); }
		int mono = 1, cont = (vlExtraDb(K, K, 36) == 0) && (vlExtraDb(K, K, 23) == 0), bnd = 1, maxd = 0;
		for (int n = 1; n <= 62; n++)
		{
			for (int d = 0; d < 2; d++)
			{
				int D = d ? 23 : 36, e0 = vlExtraDb(n - 1, K, D), e1 = vlExtraDb(n, K, D);
				if (((n - 31) - e1) < ((n - 1 - 31) - e0)) mono = 0;
				if ((e1 > D) || (e0 > D)) bnd = 0;
				if ((d == 0) && ((e0 - e1) > maxd)) maxd = e0 - e1;
			}
		}
		printf("|%d,%d,%d,%d\n", mono, cont, bnd, maxd);
	}
	printf("knee=%d,%d,%d,%d\n", vlKnee(VOLLOW_FIXED_MODE), vlKnee(vlEffectiveMode(0)), vlKnee(vlEffectiveMode(0xFF)), vlKnee(0));
	return 0;
}
"""
VOL_EXP32 = "36/23/0F,34/22/10,32/20/14,27/17/1D,23/14/29,18/12/33,14/9/48,9/6/66,5/3/90,1/1/B6"


def test_volume():
    lg = T.rd(os.path.join(INC, "functions", "volume_low_logic.h"))
    vl = T.rd(os.path.join(FN, "volume_low.c"))
    defs = re.findall(r"^#define VOLLOW_KNEE\s+(\d+)U", lg, re.M)
    check(defs == ["32"], "В1: коліно -- одна іменована константа VOLLOW_KNEE = 32 (визначень: %s)" % defs)
    check("static const uint8_t k[" not in lg and "VOLLOW_KNEE" in (T.carve_fn(lg, "static inline uint8_t vlKnee(uint8_t mode)") or ""), "В1: таблиці колін 8/16/24 нема -- vlKnee повертає VOLLOW_KNEE")
    check(re.search(r"VOLLOW_DEPTH_DMR_DB\s+36U", lg) and re.search(r"VOLLOW_DEPTH_FM_DB\s+23U", lg) and re.search(r"VOLLOW_FM_FLOOR_LOW\s+0x0FU", lg),
          "В1: D_DMR 36, D_FM 23, підлога FM 0x0F не змінені")
    check("s_mode = vlEffectiveMode(0U);" in vl and "codeplugGet" not in (T.carve_fn(vl, "void volumeLowLoad(void)") or "x codeplugGet"), "В1: блок 17 і далі не читається (режим фіксований)")
    out = run_c(VOL_C, inc=True)
    check(out is not None, "В2: хостова збірка кривої")
    o = kv(out)
    print("В3 (рахує код; n = 0,2,4,8,12,16,20,24,28,31; extra DMR дБ / extra FM дБ / FM low-byte; |монотонність,неперервність,межі,макс. крок extra DMR):")
    for K in (16, 24, 32):
        print("  K %d: %s" % (K, o.get("K%d" % K)))
    for K in (16, 24, 32):
        tail = (o.get("K%d" % K) or "|").split("|")[1]
        check(tail.split(",")[:3] == ["1", "1", "1"], "В2: K %d -- повний рівень не спадає, у n = K extra = 0, таблиці в межах: %s" % (K, tail))
    check((o.get("K32") or "").split("|")[0] == VOL_EXP32, "В3: K 32 -- значення кривої (DMR/FM/low-byte) як розраховано: %s" % o.get("K32"))
    check(o.get("knee") == "32,32,32,0", "В1: фіксований режим -> K 32 (що б не лежало в блоці 17), режим 0 -> 0: %s" % o.get("knee"))


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    t = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c") or ""
    tdc = T.pp(FW, incs, cf["DUALCH"], "application/source/functions/dual_channel.c") or ""
    check(t != "" and tdc != "", "препроцесування uiChannelMode.c / dual_channel.c (DUALCH)")
    test_keys(t, src)
    test_ring(t, tdc)
    test_toggle(t)
    test_dead(src)
    test_volume()
    print("test_r98fix7: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
