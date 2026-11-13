#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98 (хост): «Подвійний прийом» -- ЕТАП 1 «VFO в картці» (B = канал або VFO A/B) + Д1-Д3.
  1  кодування типу B у блоці 18 (reserved[0]) і типу A (reserved[1]): старі записи, типи 0/1/2, інше -> 0, тип A ненульовий -> 0 без помилки, ключ (тип, індекс);
  2  замкнений цикл ручки «канали -> VFO A -> VFO B -> перший канал» в обидва боки (dcStepExt), пропуск непридатних позицій;
  3  ізоляція стока в uiVFOModeDualLoad (хостовий прогін справжнього тексту): currentVFONumber / previousVFONumber / overrideTG відновлюються,
     недійсний контакт VFO не пише overrideTG, нових записів (settingsSet) нема; мутанти;
  4  dualTune (справжній текст): A -> VFO B -> A залишає канальний буфер і глобальний стан каналу без змін;
  5  SK2 + ручка на картці B = VFO (dualIsVfoStepKey: таблиця істинності + мутант), крок частоти через стокову stepFrequency (без дубля таблиць);
  6  статика: завантаження каналу при поверненні з передачі, вихід на VFO-екран, швидке меню, червона/VFO-екран під час режиму, Д1 (конверт);
Запуск: python3 tools/test_r98.py"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa  (pp, carve_fn, run_c, rd, APP, FW)
cmt = T.cmt
FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")


# ------------------------------------------------------------------------------------------------ 1-2
CODE1 = r'''
#include <stdio.h>
#include <string.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "%s"
static uint16_t zone[] = {5, 0, 7, 0, 12};
static uint16_t at(int pos, void *ctx) { (void)ctx; return zone[pos]; }
int main(void)
{
	dcOnFlashCfg_t raw; bool en, ptr; uint16_t ch; uint8_t tb, ta;
	/* старий запис R97: резерв нулі -> B = канал */
	memset(&raw, 0, sizeof(raw)); raw.version = 1; raw.flags = 3; raw.chBLo = 0x34; raw.chBHi = 0x01;
	int okp = dcCfgParseEx(&raw, &en, &ptr, &ch, &tb, &ta); printf("old=%%d,%%d,%%d,%%d,%%d,%%d\n", okp, en, ptr, ch, tb, ta);
	/* типи 1/2 з номером каналу, що зберігається */
	raw.reserved[0] = 1; (void)dcCfgParseEx(&raw, &en, &ptr, &ch, &tb, &ta); printf("t1=%%d,%%d\n", tb, ch);
	raw.reserved[0] = 2; (void)dcCfgParseEx(&raw, &en, &ptr, &ch, &tb, &ta); printf("t2=%%d,%%d\n", tb, ch);
	raw.reserved[0] = 3; (void)dcCfgParseEx(&raw, &en, &ptr, &ch, &tb, &ta); printf("t3=%%d\n", tb);
	raw.reserved[0] = 255; (void)dcCfgParseEx(&raw, &en, &ptr, &ch, &tb, &ta); printf("t4=%%d\n", tb);
	/* тип A ненульовий -> читається як 0, без помилки */
	raw.reserved[0] = 0; raw.reserved[1] = 1; okp = dcCfgParseEx(&raw, &en, &ptr, &ch, &tb, &ta); printf("a1=%%d,%%d\n", okp, ta);
	raw.reserved[1] = 2; (void)dcCfgParseEx(&raw, &en, &ptr, &ch, &tb, &ta); printf("a2=%%d\n", ta);
	/* збирання: довжина 8, версія 1, тип B у [4], тип A завжди 0 у [5], решта 0 */
	dcCfgBuildEx(&raw, true, true, 300, 2, 1);
	printf("b1=%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", (int)sizeof(raw), raw.version, raw.flags, raw.chBLo, raw.chBHi, raw.reserved[0], raw.reserved[1], raw.reserved[2], raw.reserved[3]);
	dcCfgBuildEx(&raw, false, false, 7, 9, 0); printf("b2=%%d,%%d\n", raw.reserved[0], raw.chBLo);   /* тип поза 0..2 -> 0 */
	/* старий збирач = типи 0, байт-у-байт як R97 */
	dcOnFlashCfg_t o1, o2; dcCfgBuild(&o1, true, false, 42); dcCfgBuildEx(&o2, true, false, 42, 0, 0);
	printf("c1=%%d,%%d\n", memcmp(&o1, &o2, sizeof(o1)) == 0, o1.reserved[0] | o1.reserved[1] | o1.reserved[2] | o1.reserved[3]);
	/* кругова перевірка типів */
	int ok = 1; for (int t = 0; t <= 2; t++) { dcCfgBuildEx(&raw, true, true, 77, (uint8_t)t, 0); (void)dcCfgParseEx(&raw, &en, &ptr, &ch, &tb, &ta); if (tb != t || ch != 77 || !en || !ptr) ok = 0; }
	printf("rt=%%d\n", ok);
	/* ключ (тип, індекс): канали -- за номером; VFO -- за типом; ніколи -1 */
	printf("k=%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", dcSameTarget(0, 5, 0, 5), dcSameTarget(0, 5, 0, 6), dcSameTarget(0, 5, 1, 5), dcSameTarget(0, 5, 2, 5), dcSameTarget(1, 0, 1, 99), dcSameTarget(1, 0, 2, 0), dcSameTarget(0, 0, 0, 0));
	/* dcStepExt: n=5 позицій {5,-,7,-,12}, VFO A = 5, VFO B = 6; вперед з останнього каналу (позиція 4) -> VFO A -> VFO B -> 0 -> 2 -> 4 */
	int e = 4; printf("f=");
	for (int i = 0; i < 6; i++) { e = dcStepExt(5, e, 1, at, NULL); printf("%%d%%s", e, (i < 5) ? "," : ""); }
	e = 0; printf("\nb=");
	for (int i = 0; i < 6; i++) { e = dcStepExt(5, e, -1, at, NULL); printf("%%d%%s", e, (i < 5) ? "," : ""); }
	printf("\ns0=%%d,%%d,%%d,%%d\n", dcStepExt(5, -1, 1, at, NULL), dcStepExt(5, -1, -1, at, NULL), dcStepExt(5, 99, 1, at, NULL), dcStepExt(5, 99, -1, at, NULL));
	zone[0] = zone[2] = zone[4] = 0;   /* жодного придатного каналу: лишаються VFO */
	e = 6; int e1 = dcStepExt(5, e, 1, at, NULL); int e2 = dcStepExt(5, 5, 1, at, NULL); int e3 = dcStepExt(5, 5, -1, at, NULL);
	printf("v=%%d,%%d,%%d\n", e1, e2, e3);
	printf("z=%%d,%%d\n", dcStepExt(0, -1, 1, at, NULL), dcStepExt(0, 1, 1, at, NULL));   /* порожня зона: VFO A (0) і VFO B (1) */
	return 0;
}
'''


def test_encoding_and_cycle():
    dc = os.path.join(APP, "source", "functions", "dual_channel.c")
    out = T.run_c(CODE1 % dc)
    check(out is not None, "R98 В1/В8: хостова збірка dual_channel.c")
    if out is None:
        return
    o = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    check(o.get("old") == "1,1,1,308,0,0", "В1: старий запис R97 (резерв = нулі) читається як «B -- канал», решта полів без змін: %s" % o.get("old"))
    check(o.get("t1") == "1,308" and o.get("t2") == "2,308", "В1: типи 1 (VFO A) і 2 (VFO B) читаються, номер каналу B зберігається: %s %s" % (o.get("t1"), o.get("t2")))
    check(o.get("t3") == "0" and o.get("t4") == "0", "В1: невідомий тип -> 0 (канал): %s %s" % (o.get("t3"), o.get("t4")))
    check(o.get("a1") == "1,0" and o.get("a2") == "0", "В1: тип A (reserved[1]) ненульовий -> 0, розбір без помилки: %s %s" % (o.get("a1"), o.get("a2")))
    check(o.get("b1") == "8,1,3,44,1,2,0,0,0", "В1: збирання -- 8 байт, версія 1, прапорці, номер B (300), тип B у [4], тип A у [5] завжди 0, [6..7] нулі: %s" % o.get("b1"))
    check(o.get("b2") == "0,7", "В1: тип поза 0..2 при збиранні -> 0: %s" % o.get("b2"))
    check(o.get("c1") == "1,0", "В1: старий збирач дає той самий запис, що Ex з типами 0 (байт-у-байт, резерв нулі): %s" % o.get("c1"))
    check(o.get("rt") == "1", "В1: збирання -> розбір для типів 0/1/2 зберігає все")
    check(o.get("k") == "1,0,0,0,1,0,1", "В4: ключ рівності (тип, індекс): канали -- за номером, VFO -- за типом, канал != VFO, два різні VFO не рівні: %s" % o.get("k"))
    check(o.get("f") == "5,6,0,2,4,5" and o.get("b") == "6,5,4,2,0,6", "В8: цикл ручки вперед 4(позиція 12) -> VFO A -> VFO B -> 0 -> 2 -> 4 -> VFO A, назад -- навпаки; непридатні позиції (1,3) пропущено: %s | %s" % (o.get("f"), o.get("b")))
    check(o.get("s0") == "0,6,0,6", "В8: старт без позиції (від краю): вперед -> перший канал, назад -> VFO B: %s" % o.get("s0"))
    check(o.get("v") == "6,6,5" or o.get("v") == "5,6,6", "В8: зона без придатних каналів -- лишаються VFO A/B (цикл не зависає): %s" % o.get("v"))
    check(o.get("z") == "0,0" or o.get("z") == "0,1" or o.get("z") == "1,0", "В8: порожня зона (n=0) -- VFO A/B: %s" % o.get("z"))


# ------------------------------------------------------------------------------------------------ 3
ISO_HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
enum { CHANNEL_FLAG_FORCE_DMO = 1 };
enum { DMR_MODE_DMO = 1, DMR_MODE_AUTO = 2 };
#define RADIO_DEVICE_PRIMARY 0
typedef struct { uint32_t rxFreq; uint32_t txFreq; uint8_t chMode; uint8_t libreDMR_Power; uint8_t rxGroupList; uint8_t flags; } CodeplugChannel_t;
typedef struct { char name[16]; uint32_t tgNumber; } CodeplugContact_t;
typedef struct { int NOT_IN_CODEPLUG_numTGsInGroup; } CodeplugRxGroup_t;
struct { uint8_t currentVFONumber; uint32_t overrideTG; } nonVolatileSettings;
static uint8_t previousVFONumber = 0xFF;
CodeplugChannel_t settingsVFOChannel[2], *currentChannelData;
int lastLoadedRxGroup = -1; CodeplugRxGroup_t currentRxGroupData;
static int gValid = 1, probes = 0, loads = 0, seenVfo = -1, seenPrev = -1, rxgLoads = 0, clears = 0; static uint32_t seenOv = 77, tuneRx = 0, tuneTx = 0; static CodeplugChannel_t *seenCur;
void HRC6000ClearActiveDMRID(void) { clears++; }
void radioSetTRxDevice(int d) { (void)d; }
void trxSetFrequency(uint32_t rx, uint32_t tx, int m) { tuneRx = rx; tuneTx = tx; (void)m; }
int codeplugChannelGetFlag(CodeplugChannel_t *c, int f) { return (c->flags & f) != 0; }
bool codeplugRxGroupGetDataForIndex(int i, CodeplugRxGroup_t *g) { (void)i; g->NOT_IN_CODEPLUG_numTGsInGroup = 2; rxgLoads++; return true; }
void uiVFOLoadContact(CodeplugContact_t *c) { probes++; memset(c, 0, sizeof(*c)); if (gValid) { memcpy(c->name, "TG", 2); c->tgNumber = 91; } }
void uiVFOModeLoadChannelData(bool force)   /* модель стока: читає поточний VFO, при нульовому перекритті й недійсному контакті пише 9 (як settingsSet) */
{
	(void)force; loads++; seenVfo = nonVolatileSettings.currentVFONumber; seenOv = nonVolatileSettings.overrideTG; seenPrev = previousVFONumber; seenCur = currentChannelData;
	if ((currentChannelData->chMode == RADIO_MODE_DIGITAL) && (nonVolatileSettings.overrideTG == 0) && (gValid == 0)) { nonVolatileSettings.overrideTG = 9; }
	previousVFONumber = nonVolatileSettings.currentVFONumber;
}
%s
static void setup(uint8_t cur, uint32_t ov, uint8_t prev, int mode, int valid)
{
	memset(settingsVFOChannel, 0, sizeof(settingsVFOChannel));
	settingsVFOChannel[0].rxFreq = 43012500U; settingsVFOChannel[0].txFreq = 43012500U; settingsVFOChannel[0].chMode = (uint8_t)mode; settingsVFOChannel[0].libreDMR_Power = 3; settingsVFOChannel[0].rxGroupList = 1;
	settingsVFOChannel[1].rxFreq = 14550000U; settingsVFOChannel[1].txFreq = 14610000U; settingsVFOChannel[1].chMode = (uint8_t)mode; settingsVFOChannel[1].libreDMR_Power = 4; settingsVFOChannel[1].rxGroupList = 0;
	nonVolatileSettings.currentVFONumber = cur; nonVolatileSettings.overrideTG = ov; previousVFONumber = prev; gValid = valid; probes = loads = rxgLoads = clears = 0; seenVfo = seenPrev = -1; seenOv = 77; lastLoadedRxGroup = -1;
	currentChannelData = (CodeplugChannel_t *)0;
}
static void rep(const char *n) { printf("%%s=%%d,%%d,%%d|%%d,%%d,%%u|%%d,%%d\n", n, nonVolatileSettings.currentVFONumber, previousVFONumber, (int)nonVolatileSettings.overrideTG, seenVfo, seenPrev, (unsigned)seenOv, probes, loads); }
int main(void)
{
	setup(0, 0, 0xFF, RADIO_MODE_DIGITAL, 1); uiVFOModeDualLoad(1, true); rep("i1");     /* стоковий VFO A, ТГ дійсний: B-налаштування бачить VFO 1, previous != VFO (свіже налаштування), потім усе повернуто */
	setup(0, 0, 0x00, RADIO_MODE_DIGITAL, 0); uiVFOModeDualLoad(0, false); rep("i2");    /* недійсний контакт: стока бачить 9, але після -- перекриття знову 0, нічого не записано */
	setup(1, 91, 0x01, RADIO_MODE_DIGITAL, 1); uiVFOModeDualLoad(0, true); rep("i3");    /* було перекриття ТГ 91 -- стока його бачить, і воно лишається 91 */
	setup(0, 0, 0xFF, RADIO_MODE_ANALOG, 1); uiVFOModeDualLoad(1, false); rep("i4");     /* FM -- без проби контакту (probes = 0) */
	setup(0, 0, 0, RADIO_MODE_DIGITAL, 1); uiVFOModeDualLoad(1, false);
	printf("c=%%d,%%d,%%u,%%u,%%d,%%d\n", (int)(seenCur == &settingsVFOChannel[1]), (int)(currentChannelData == &settingsVFOChannel[1]), (unsigned)tuneRx, (unsigned)tuneTx, settingsVFOChannel[1].libreDMR_Power, clears);   /* currentChannelData = запис VFO; потужність скинуто на головну; частоти з запису */
	setup(0, 0, 0, RADIO_MODE_DIGITAL, 1); uiVFOModeDualLoad(0, false); printf("g=%%d,%%d\n", rxgLoads, lastLoadedRxGroup);   /* група VFO завантажена */
	setup(0, 0, 0, RADIO_MODE_DIGITAL, 1); uiVFOModeDualLoad(1, false); printf("h=%%d,%%d\n", rxgLoads, lastLoadedRxGroup);   /* VFO B без групи -- не читається */
	return 0;
}
'''


def test_isolation(incs, cf):
    src = T.rd(os.path.join(UI, "uiVFOMode.c"))
    i = src.find("void uiVFOModeDualLoad(")
    body = src[i:src.find("\n}\n", i)]
    check(i > 0 and "settingsSet(" not in body, "В2: uiVFOModeDualLoad не користується settingsSet (брудного прапорця немає, нових записів нема)")
    check("#if defined(DUAL_CHANNEL_ENABLED)" in src[:i][-4000:] and src.find("#endif", i) > i, "В2: uiVFOModeDualLoad/Step -- лише під DUAL_CHANNEL_ENABLED")
    if "DUALCH" not in cf:
        check(False, "конфігурація DUALCH є"); return
    t = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiVFOMode.c")
    fn = T.carve_fn(t or "", "void uiVFOModeDualLoad(uint8_t vfo, _Bool freshTune)")
    check(fn is not None, "В2: uiVFOModeDualLoad знайдено у препроцесованому тексті")
    if fn is None:
        return
    out = T.run_c(ISO_HARNESS % fn)
    check(out is not None, "В2: хостова збірка uiVFOModeDualLoad")
    if out is None:
        return
    o = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    check(o.get("i1") == "0,255,0|1,0,0|1,1", "В2: після налаштування на VFO B стокові currentVFONumber(0)/previousVFONumber(255)/overrideTG(0) -- як були; стока бачила VFO 1, previous != VFO: %s" % o.get("i1"))
    check(o.get("i2") == "0,0,0|0,0,9|1,1", "В2: недійсний контакт VFO -- стока бачить ТГ 9 (як після її лікування), але перекриття ТГ після виклику знову 0: %s" % o.get("i2"))
    check(o.get("i3") == "1,1,91|0,1,91|0,1", "В2: перекриття ТГ 91 лишається 91 (стока його бачила), проба контакту не потрібна: %s" % o.get("i3"))
    check(o.get("i4") == "0,255,0|1,1,0|0,1", "В2: FM VFO -- без проби контакту: %s" % o.get("i4"))
    check(o.get("c") == "1,1,43012500,43012500,0,1" or o.get("c") == "1,1,14550000,14610000,0,1", "В2: currentChannelData = запис потрібного VFO, частоти приймання/передачі з нього (VFO B: 145.5/146.1), потужність -- головна, активний DMR-ID скинуто: %s" % o.get("c"))
    check(o.get("g") == "1,1" and o.get("h") == "0,-1", "В2: група прийому VFO завантажується лише якщо задана: %s %s" % (o.get("g"), o.get("h")))
    # мутанти
    for what, mut in (("перекриття ТГ не відновлюється", fn.replace("nonVolatileSettings.overrideTG = savedOverride;", "")),
                      ("поточний VFO не відновлюється", fn.replace("nonVolatileSettings.currentVFONumber = savedVfo;", "")),
                      ("previousVFONumber не відновлюється", fn.replace("previousVFONumber = savedPrev;", "")),
                      ("недійсний контакт лікується через перекриття назавжди", re.sub(r"nonVolatileSettings\.overrideTG = savedOverride;", "nonVolatileSettings.overrideTG = nonVolatileSettings.overrideTG;", fn))):
        mo = T.run_c(ISO_HARNESS % mut)
        check(mut != fn and mo is not None and mo != out, "В2 (мутант): %s -- ловиться тестами" % what)


# ------------------------------------------------------------------------------------------------ 4
TUNE_HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#define CH_DETAILS_VFO_CHANNEL -1
#define SETTINGS_CHANNEL_MODE 0
typedef struct { uint32_t rxFreq; uint8_t chMode; } CodeplugChannel_t;
struct { int16_t currentIndexInTRxGroupList[3]; } nonVolatileSettings;
struct { int currentSelectedChannelNumber; } uiDataGlobal;
static CodeplugChannel_t channelScreenChannelData, settingsVFOChannel[2], *currentChannelData;
static int onB = 0, bVfo = 0, vfoIdx = 0, getData = 0, loadsMem = 0, loadsNo = 0, vfoLoads = 0, vfoFresh = 0, vfoLast = -1, tgSets = 0, clears = 0; static uint16_t chB = 7;
static int16_t s_dualTgIdxA;
bool settingsSetBOOL(bool *p, bool v) { (void)p; (void)v; return 0; }
bool settingsSetINT8(int8_t *p, int8_t v) { (void)p; (void)v; return 0; }
bool settingsSetUINT8(uint8_t *p, uint8_t v) { (void)p; (void)v; return 0; }
bool settingsSetINT16(int16_t *p, int16_t v) { *p = v; tgSets++; return 1; }
bool settingsSetUINT16(uint16_t *p, uint16_t v) { (void)p; (void)v; return 0; }
bool settingsSetINT32(int32_t *p, int32_t v) { (void)p; (void)v; return 0; }
bool settingsSetUINT32(uint32_t *p, uint32_t v) { (void)p; (void)v; return 0; }
bool dcIsOnB(void) { return onB; }
void dcSetOnB(bool b) { onB = b; }
bool dcBIsVfo(void) { return bVfo; }
uint16_t dcChannelB(void) { return chB; }
static uint8_t dualVfoIdx(void) { return (uint8_t)vfoIdx; }
void lastHeardClearLastID(void) { clears++; }
void codeplugChannelGetDataForIndex(int ch, CodeplugChannel_t *c) { (void)ch; getData++; c->rxFreq = 1000 + ch; }
void uiChannelModeLoadChannelData(bool mem, bool vp) { (void)vp; if (mem) loadsMem++; else loadsNo++; if (!mem) uiDataGlobal.currentSelectedChannelNumber = 5; else uiDataGlobal.currentSelectedChannelNumber = chB; }
void uiVFOModeDualLoad(uint8_t v, bool fresh) { vfoLoads++; vfoLast = v; vfoFresh = fresh; }
%s
int main(void)
{
	channelScreenChannelData.rxFreq = 12345; currentChannelData = &channelScreenChannelData; uiDataGlobal.currentSelectedChannelNumber = 5; nonVolatileSettings.currentIndexInTRxGroupList[0] = 4;
	/* A (канал) -> B = VFO B */
	bVfo = 1; vfoIdx = 1; dualTune(true);
	printf("t1=%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", onB, currentChannelData == &settingsVFOChannel[1], uiDataGlobal.currentSelectedChannelNumber, getData, loadsMem + loadsNo, vfoLoads, vfoLast);
	printf("t1b=%%d,%%d\n", (int)channelScreenChannelData.rxFreq, vfoFresh);
	/* B = VFO B -> назад на A: канальний буфер знову поточний, канал A завантажується звичайним шляхом */
	nonVolatileSettings.currentIndexInTRxGroupList[0] = 9;   /* B міг би зіпсувати індекс ТГ (для VFO -- не псує, але перевіряємо повернення) */
	dualTune(false);
	printf("t2=%%d,%%d,%%d,%%d,%%d,%%d\n", onB, currentChannelData == &channelScreenChannelData, uiDataGlobal.currentSelectedChannelNumber, loadsNo, vfoLoads, nonVolatileSettings.currentIndexInTRxGroupList[0]);
	/* B = VFO A: тип -> VFO 0 */
	vfoIdx = 0; getData = 0; dualTune(true); printf("t3=%%d,%%d,%%d\n", vfoLast, currentChannelData == &settingsVFOChannel[0], getData);
	dualTune(false);
	/* B = канал: старий шлях (читає запис каналу, номер B) */
	bVfo = 0; getData = 0; vfoLoads = 0; dualTune(true);
	printf("t4=%%d,%%d,%%d,%%d,%%d\n", currentChannelData == &channelScreenChannelData, getData, vfoLoads, uiDataGlobal.currentSelectedChannelNumber, loadsMem);
	return 0;
}
'''


def test_tune(incs, cf):
    t = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    fn = T.carve_fn(t or "", "static void dualTune(_Bool toB)")
    check(fn is not None, "В2: dualTune знайдено")
    if fn is None:
        return
    out = T.run_c(TUNE_HARNESS % fn)
    check(out is not None, "В2: хостова збірка dualTune")
    if out is None:
        return
    o = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    check(o.get("t1") == "1,1,-1,0,0,1,1" and o.get("t1b") == "12345,1",
          "В2: B = VFO B -- рація на B, currentChannelData = запис VFO B, номер вибраного = CH_DETAILS_VFO_CHANNEL, канальний буфер і канальне завантаження НЕ чіпаються, VFO налаштовано ізольовано (свіже): %s %s" % (o.get("t1"), o.get("t1b")))
    check(o.get("t2") == "0,1,5,1,1,9" or o.get("t2") == "0,1,5,1,1,4",
          "В2: назад на A -- currentChannelData знову канальний буфер, канал A завантажується звичайним шляхом (номер 5), VFO-завантажень не додалось: %s" % o.get("t2"))
    check(o.get("t3") == "0,1,0", "В2: B = VFO A -- VFO 0, без читання каналу: %s" % o.get("t3"))
    check(o.get("t4") == "1,1,0,7,1", "В2: B = канал -- старий шлях (читає запис каналу, номер B), VFO не налаштовується: %s" % o.get("t4"))
    k = fn.rfind("currentChannelData = &channelScreenChannelData;")
    mut = fn[:k] + fn[k + len("currentChannelData = &channelScreenChannelData;"):]
    mo = T.run_c(TUNE_HARNESS % mut)
    check(mut != fn and mo is not None and mo != out, "В2 (мутант): без повернення currentChannelData на канальний буфер -- ловиться")
    mut = re.sub(r"uiVFOModeDualLoad\(dualVfoIdx\(\), 1\);", "codeplugChannelGetDataForIndex(dcChannelB(), &channelScreenChannelData); uiChannelModeLoadChannelData(1, 0);", fn)
    mo = T.run_c(TUNE_HARNESS % mut) if mut != fn else None
    check(mut != fn and mo != out, "В2 (мутант): тип 1 трактується як канал -- ловиться")


# ------------------------------------------------------------------------------------------------ 5
KEY_HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#define BUTTON_SK1 1
#define BUTTON_SK2 2
#define BUTTONCHECK_DOWN(e, sk) (((e)->buttons & sk))
enum { KEY_ROTARY_INCREMENT = 10, KEY_ROTARY_DECREMENT = 11, KEY_GREEN = 5 };
enum { UI_CHANNEL_MODE = 3 };
typedef struct { uint32_t buttons; struct { int key; } keys; } uiEvent_t;
static int en = 1, ptrB = 1, vfo = 1, menu = UI_CHANNEL_MODE;
bool dcIsEnabled(void) { return en; }
bool dcPointerB(void) { return ptrB; }
bool dcBIsVfo(void) { return vfo; }
int menuSystemGetCurrentMenuNumber(void) { return menu; }
%s
static int go(uint32_t b, int key) { uiEvent_t e; e.buttons = b; e.keys.key = key; return dualIsVfoStepKey(&e); }   /* SK2 = 0x20, SK1 = 0x02, ручка: 8 (+) / 7 (-) -- як у справжніх макросах */
int main(void)
{
	printf("a=%%d,%%d,%%d,%%d\n", go(0x20, 8), go(0x20, 7), go(0x20, 5), go(0, 8));          /* SK2+ручка (обидва напрямки) -- так; SK2+інша клавіша / ручка без SK2 -- ні */
	printf("b=%%d,%%d\n", go(0x22, 8), go(0x02, 8));                                          /* SK1 разом з SK2 / лише SK1 -- ні */
	vfo = 0; printf("c=%%d\n", go(0x20, 8)); vfo = 1;                                       /* B = канал -- ні (SK2+ручка там -- стокова зміна зони) */
	ptrB = 0; printf("d=%%d\n", go(0x20, 8)); ptrB = 1;                                     /* покажчик на A -- ні */
	en = 0; printf("e=%%d\n", go(0x20, 8)); en = 1;                                         /* режим вимкнено -- ні */
	menu = 9; printf("f=%%d\n", go(0x20, 8)); menu = UI_CHANNEL_MODE;                       /* не екран каналу -- ні */
	return 0;
}
'''


def test_sk2(incs, cf):
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    t = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    fn = T.carve_fn(t or "", "static _Bool dualIsVfoStepKey(const uiEvent_t *ev)")
    check(fn is not None, "В8: dualIsVfoStepKey знайдено")
    if fn:
        out = T.run_c(KEY_HARNESS % fn)
        check(out is not None, "В8: хостова збірка dualIsVfoStepKey")
        if out:
            o = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
            check(o.get("a") == "1,1,0,0" and o.get("b") == "0,0" and o.get("c") == "0" and o.get("d") == "0" and o.get("e") == "0" and o.get("f") == "0",
                  "В8: SK2 + ручка -- крок частоти ЛИШЕ при ввімкненому режимі, покажчику на B, B = VFO, екрані каналу, без SK1: %s" % out.replace("\n", " "))
            for what, mut in (("тип B не перевіряється", fn.replace("dcBIsVfo() && ", "")), ("покажчик не перевіряється", fn.replace("dcPointerB() && ", "")), ("SK2 не перевіряється", fn.replace("(((ev)->buttons & 0x00000020)) &&", ""))):
                mo = T.run_c(KEY_HARNESS % mut)
                check(mut != fn and mo is not None and mo != out, "В8 (мутант): %s -- ловиться" % what)
    # статика: ручка/SK2 на VFO-картці
    hk = src[src.find("static bool dualHandleKey(uiEvent_t *ev)\n{"):]
    hk = hk[:hk.find("// Увімкнути/вимкнути режим")]
    check(hk.find("dualIsVfoStepKey(ev)") < hk.find("BUTTONCHECK_DOWN(ev, BUTTON_SK2) || BUTTONCHECK_DOWN(ev, BUTTON_SK1)") and "uiVFOModeDualStep(dualVfoIdx()" in hk,
          "В8: у dualHandleKey SK2+ручка на картці VFO обробляється ДО загального «SK2/SK1 -- не наші» і викликає uiVFOModeDualStep")
    check(re.search(r"if \(dwRunning \|\| dualSingle\(\) \|\| dualIsVfoStepKey\(ev\)\)", src) is not None, "В8: хук handleEvent пропускає SK2+ручку на VFO-картці в dualHandleKey навіть коли чергування вже зупинене паузою")
    vs = T.rd(os.path.join(UI, "uiVFOMode.c"))
    st = vs[vs.find("void uiVFOModeDualStep("):]
    st = st[:st.find("\n}\n")]
    check("stepFrequency(VFO_FREQ_STEP_TABLE[" in st and "settingsSetVFODirty();" in st and "selectedFreq = savedFocus;" in st and "currentVFONumber = savedVfo;" in st,
          "В8: крок частоти -- стокова stepFrequency() і стокова таблиця кроків VFO_FREQ_STEP_TABLE, фокус/поточний VFO відновлено, збереження стокове (settingsSetVFODirty)")
    check(re.search(r"\{\s*250\s*,\s*500", src) is None and "VFO_FREQ_STEP_TABLE[" not in src, "В8: таблиці кроків у uiChannelMode.c не дубльовані")


# ------------------------------------------------------------------------------------------------ 6
def test_static():
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    am = T.rd(os.path.join(APP, "source", "applicationMain.c"))
    uu = T.rd(os.path.join(UI, "uiUtilities.c"))
    # В2/В5: повернення з екрана передачі/меню на B = VFO -- ізольоване налаштування, до канальних гілок
    ld = src[src.find("void uiChannelModeLoadChannelData("):]
    ld = ld[:ld.find("HRC6000ClearActiveDMRID();")]
    ia = ld.find("dcIsOnB() && dcBIsVfo()"); ib = ld.find("if (useChannelDataInMemory && dcIsOnB())")
    check(0 < ia < ib and "uiVFOModeDualLoad(dualVfoIdx(), false);\n\t\treturn;" in ld and "CH_DETAILS_VFO_CHANNEL" in ld,
          "В5: повернення з передачі/меню на B = VFO -- uiChannelModeLoadChannelData налаштовує VFO ізольовано і виходить ДО канальних гілок (номер каналу B для VFO не береться)")
    check("dcSetTxHold(true);" in src[src.find("bool uiChannelModeDualPrepareTx(void)"):src.find("bool uiChannelModeDualPrepareTx(void)") + 900] and "dualTune(toB);" in src[src.find("bool uiChannelModeDualPrepareTx(void)"):src.find("bool uiChannelModeDualPrepareTx(void)") + 900],
          "В5: PTT з картки VFO -- той самий шлях PrepareTx: dualTune(toB) (VFO налаштовується), утримання «Затр. скан.» після передачі")
    check("snprintf(nameBuf, NAME_BUFFER_LEN, \"VFO %c\", (char)('A' + dualVfoIdx()));" in src, "В5: екран передачі з картки VFO показує «VFO A/B» (стокове ім'я VFO порожнє)")
    check("codeplugChannelSaveDataForIndex(" not in src[src.find("static void dualTune(bool toB)"):src.find("static uint16_t dualChannelA(void)")], "В2: dualTune не пише запис каналу (VFO ніколи не потрапляє в канал)")
    # В6: вихід на обраному VFO
    dd = src[src.find("static void dualDisable(void)"):]
    dd = dd[:dd.find("\n}\n")]
    check(dd.find("(void)dcSetEnabled(false, true);") < dd.find("dualLeaveOnVfo();") and "if (dcBIsVfo())" in dd,
          "В6: вихід (довге ▼) при обраному VFO -- режим вимикається ДО переходу на VFO-екран, далі dualLeaveOnVfo()")
    lv = src[src.find("static void dualLeaveOnVfo(void)"):]
    lv = lv[:lv.find("\n}\n")]
    check("settingsSet(nonVolatileSettings.currentVFONumber, v);" in lv and "menuSystemPopAllAndDisplaySpecificRootMenu(UI_VFO_MODE, true);" in lv and "dcSetOnB(false);" in lv and "codeplugSetLastUsedChannelInZone" not in lv,
          "В6: «лишитись на VFO» -- стокове перемикання поточного VFO + стоковий вхід у VFO-екран; «останній канал зони»/зона не змінюються")
    sm = src[src.find("static void dualSetMode(bool on, bool notify)"):]
    sm = sm[:sm.find("static void dualHotkeyToggle")]
    check(sm.count("menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE") == 2, "В6: після виходу на VFO-екран канальний екран і сповіщення не малюються (дві перевірки меню в dualSetMode)")
    # швидке меню на обраному VFO
    qk = src[src.find("quickKeyApply: // branching here when to quickkey was used."):]
    qk = qk[:qk.find("switch(menuDataGlobal.currentItemIndex)\n\t\t\t{\n\t\t\t\tcase CH_SCREEN_QUICK_MENU_COPY2VFO:")]
    for item in ("COPY2VFO", "COPY_FROM_VFO", "TALKAROUND", "SET_B", "DELETE", "ZONE_REMOVE"):
        check("case CH_SCREEN_QUICK_MENU_%s:" % item in qk, "В6: пункт швидкого меню «%s» на обраному VFO -- сигнал помилки, стан не змінюється" % item)
    check("dcIsEnabled() && dcIsOnB() && dcBIsVfo()" in qk and "MELODY_ERROR_BEEP" in qk and "return;" in qk, "В6: захист пунктів меню діє лише коли рація на B = VFO, піп помилки, вихід без дій")
    # В7: червона/VFO-екран під час режиму (UV380: перехід у VFO -- стокова КОРОТКА червона)
    hk = src[src.find("static bool dualHandleKey(uiEvent_t *ev)\n{"):]
    hk = hk[:hk.find("// Увімкнути/вимкнути режим")]
    check(re.search(r"case KEY_RED:.*?return true;", hk, re.S) is not None, "В7: під час чергування/«A==B» червона (стокова «в VFO») з'їдається -- режим не залишає екран каналу (рішення власника FIX4)")
    ar = src[src.find("static void dualAutoResume(void)\n{"):]
    ar = ar[:ar.find("\n}\n")]
    check("(menuSystemGetCurrentMenuNumber() != UI_CHANNEL_MODE)" in ar, "В7: чергування НЕ відновлюється під VFO-екраном/іншим меню (dualAutoResume лише на екрані каналу); повернення на канал -- самовідновлення")
    hv = src[src.find("static void handleEventCore(uiEvent_t *ev)\n#else"):]
    check("if (dcIsOnB() && (ev->keys.key != KEY_GREEN) && (KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN) == false))" in hv[:2500] and "dualTune(false);" in hv[:2500],
          "В7: у паузі після клавіші (режим зупинено, рація на B) стокова червона (в VFO) спершу повертає рацію на A (канальний буфер), тоді стока відкриває VFO-екран")
    # В4 / В6: пара для VFO
    cp = src[src.find("static dcPairCheck_t dualCheckPair(void)"):]
    cp = cp[:cp.find("\n}\n")]
    check("if (dcBIsVfo())" in cp and "return DC_PAIR_OK;" in cp, "В4: B = VFO -- пара завжди дійсна (VFO існує), без номера каналу")
    check("dcSameTarget((uint8_t)DC_TYPE_CHANNEL, dualChannelA(), dcTypeB(), dcChannelB())" in src, "В4: рівність A/B -- за ключем (тип, індекс), не за «-1»")
    # В9: пам'ять
    dcc = T.rd(os.path.join(APP, "source", "functions", "dual_channel.c"))
    sd = dcc[dcc.find("static struct\n{"):dcc.find("} s_dc;")]
    check("uint8_t  typeB;" in sd and sd.count("[") == 0, "В9: тип B -- байт у колишньому вирівнюванні s_dc (8 байт), масивів/нових змінних нема")
    check(re.search(r"^static [a-z_0-9]+ [a-zA-Z_0-9]+\[", dcc, re.M) is None, "В9: у dual_channel.c нових статичних масивів нема")
    # Д1: конверт
    check("static bool dualEnvelopeInCards(void)" in uu and uu.count("if (dualEnvelopeInCards())") == 2, "Д1: конверт непрочитаних у шапці вимкнено на екрані карток (SMS і APRS), на інших екранах -- як було")
    rowb = src[src.find("static void dualRenderRow("):src.find("static bool dualActivity(")]
    check("uiUnreadCount(isB ? 'A' : 'D')" in rowb and "drawMsgEnvelope" not in rowb, "Д1: індикатор у квадраті літери картки (D на A, A на B); стокова шапкова функція в картках не викликається")
    # Д3: показ перекриття ТГ -- на обох DMR-картках (глобальне)
    check("nonVolatileSettings.overrideTG != 0" in src[src.find("static uint32_t dualDestination(const"):src.find("static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags)\n{")], "Д3: dualDestination враховує глобальне перекриття ТГ (показ = реальний PTT)")
    # символи: «VFO A/B» -- латиниця, без нових полів мови
    lang = T.rd(os.path.join(T.LANG, "ukrainian.h"), "cp1251")
    check("\"VFO A\"" not in lang and "vfo_a" not in lang.lower().replace("vfo_a_", ""), "В3: «VFO A/B» -- латиниця в коді, нових мовних полів нема")


def main():
    if not T.shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    test_encoding_and_cycle()
    test_isolation(incs, cf)
    if "DUALCH" in cf:
        test_tune(incs, cf)
        test_sk2(incs, cf)
    else:
        check(False, "конфігурація DUALCH є в syntax_check.sh")
    test_static()
    print("test_r98: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
