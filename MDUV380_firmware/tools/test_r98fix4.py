#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX4 (хост): повернення в «Подвійний прийом» «як до виходу» + етап 2 VFO (A = канал або VFO, вмикання з екрана VFO).
  А   «A для повернення» у блоці 18 (reserved[1] біти 2..3 + reserved[2..3]): СПРАВЖНІЙ dual_channel.c (розбір/збирання/запис зі сховищем-заглушкою) і СПРАВЖНІ
      dualEnable()/dualApplyReturnA()/dualDisable() з uiChannelMode.c -- вихід на B -> вмикання -> картки як до виходу; інший канал; вихід на A; A видалено;
      зміна зони; старі записи; A = VFO; мутанти
  Б   етап 2: СПРАВЖНІ dualTune()/dualBufHoldsB()/dualCardIsVfo()/dualCardVfo()/dualOnVfoNow()/dualStepA()/dualBSameAsA()/dualSingle() + СПРАВЖНІЙ
      uiVFOModeDualLoad() (ізоляція стока) -- чергування A=VFO<->B=канал, A=VFO A<->B=VFO B, копія A (Б11) для всіх комбінацій, коло ручки на A, рівність,
      вихід на обраному A=VFO; лічильник читань флешу на налаштування (Б14); статика: вмикання з екрана VFO (довге ▼, пункт меню), стоковий Dual Watch,
      пауза APRS/роумінгу (Б13), зона при A=VFO (Б12); мутанти
Запуск: python3 tools/test_r98fix4.py"""
import os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
T.COMPAT_A_CHANNEL = False   # справжні функції R98-FIX4 (без заміни помічників типу A)
cmt = T.cmt
FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
FN = os.path.join(APP, "source", "functions")
BASE = "b555f8a"   # HEAD після R98-FIX3 у дереві розробки (у клоні власника хеш інший -- тоді ПРОПУСК)


def base_available():
    return subprocess.run(["git", "cat-file", "-e", BASE + "^{commit}"], cwd=FW, capture_output=True).returncode == 0


def base_file(rel):
    r = subprocess.run(["git", "show", "%s:MDUV380_firmware/%s" % (BASE, rel)], cwd=FW, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def run_c(code):
    code = T._dc_stepext_compat(code)   # R98-FIX7 А3: заморожений dcStepExt для заморожених dualStepA/dualStepB R98-FIX6
    d = tempfile.mkdtemp(prefix="r98f4_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-I", os.path.join(APP, "include"), "-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:3000]); return None
        return subprocess.run([os.path.join(d, "h")], capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def kv(out):
    return dict(l.split("=", 1) for l in (out or "").splitlines() if "=" in l)


def state_part(dc_text):
    """Справжній стан dual_channel.c (частина під DUAL_CHANNEL_ENABLED) -- без codeplug.h (сховище -- заглушка в гарнесі)."""
    a = dc_text.index('#include "functions/codeplug.h"')
    b = dc_text.index("#endif /* DUAL_CHANNEL_ENABLED */")
    return dc_text[a + len('#include "functions/codeplug.h"'):b]


PRELUDE = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "@@DCH@@"
#include "@@DCC@@"
/* ---- сховище custom-data (заглушка): один блок 18 ---- */
#define CODEPLUG_CUSTOM_DATA_TYPE_DUAL_CHANNEL_CFG 18
static uint8_t g_blk[8]; static int g_have, g_writes;
bool codeplugGetOpenGD77CustomDataBounded(int t, uint8_t *d, int n) { (void)t; if (!g_have) return false; memcpy(d, g_blk, (size_t)n); return true; }
bool codeplugSetOpenGD77CustomData(int t, uint8_t *d, int n) { (void)t; memcpy(g_blk, d, (size_t)n); g_have = 1; g_writes++; return true; }
@@STATE@@
'''


def prelude(dc_text):
    dch = os.path.join(APP, "include", "functions", "dual_channel.h")
    return PRELUDE.replace("@@DCH@@", dch).replace("@@DCC@@", os.path.join(FN, "dual_channel.c")).replace("@@STATE@@", state_part(dc_text))


# ------------------------------------------------------------------------------------------------ А: блок 18
CFG_MAIN = r'''
int main(void)
{
	dcOnFlashCfg_t r; bool en, ptr; uint16_t ch; uint8_t tb, ta, rt; uint16_t ri;
	/* старий запис (R97..R98-FIX3): reserved = 0 -> тип A канал, «A для повернення» нема */
	memset(&r, 0, sizeof r); r.version = 1; r.flags = 1; r.chBLo = 12; dcCfgParseEx(&r, &en, &ptr, &ch, &tb, &ta);
	printf("old=%d,%d,%d\n", ta, dcCfgGetReturnA(&r, &rt, &ri), ri);
	/* тип A (біти 0..1) і «A для повернення» (біти 2..3 + [2..3]) -- незалежно */
	dcCfgBuildEx(&r, true, true, 12, 0, 2); dcCfgSetReturnA(&r, 0, 300); dcCfgParseEx(&r, &en, &ptr, &ch, &tb, &ta);
	int g = dcCfgGetReturnA(&r, &rt, &ri);
	printf("b1=%d,%d,%d,%d,%02X,%02X,%02X\n", ta, g, rt, ri, r.reserved[1], r.reserved[2], r.reserved[3]);
	dcCfgSetReturnA(&r, 1, 0); g = dcCfgGetReturnA(&r, &rt, &ri); dcCfgParseEx(&r, &en, &ptr, &ch, &tb, &ta); printf("b2=%d,%d,%d,%d,%02X\n", g, rt, ri, ta, r.reserved[1]);
	dcCfgSetReturnA(&r, 2, 0); g = dcCfgGetReturnA(&r, &rt, &ri); printf("b3=%d,%d\n", g, rt);
	dcCfgSetReturnA(&r, 0, 0); g = dcCfgGetReturnA(&r, &rt, &ri); printf("b4=%d\n", g);            /* канал 0 -- нема */
	r.reserved[1] = 0x07; r.reserved[2] = 0x01; r.reserved[3] = 0x10; g = dcCfgGetReturnA(&r, &rt, &ri); dcCfgParseEx(&r, &en, &ptr, &ch, &tb, &ta); printf("b5=%d,%d\n", g, ta);   /* канал 4097 -- нема; тип A 3 -> 0 */
	/* запис: dcFlush переносить «A для повернення» з флешу; dcDisableWithReturnA пише його одним записом */
	memset(g_blk, 0, 8); g_have = 0; dcLoad(); dcSetChannelB(12, true); dcSetEnabled(true, true);
	int w0 = g_writes; dcDisableWithReturnA(0, 5); int w1 = g_writes;
	dcGetReturnA(&rt, &ri); int keep1 = ri; dcSetPointerB(false); dcFlush(); dcGetReturnA(&rt, &ri);
	printf("w=%d,%d,%d,%d,%d\n", w1 - w0, keep1, ri, dcIsEnabled(), g_blk[5] & 0x0C);
	dcSetTypeA(2); dcFlush(); dcLoad(); printf("ta=%d,%d\n", dcTypeA(), dcAIsVfo());
	return 0;
}
'''
CFG_EXP = {"old": "0,0,0", "b1": "2,1,0,300,06,2C,01", "b2": "1,1,0,2,0A", "b3": "1,2", "b4": "0", "b5": "0,0", "w": "1,5,5,0,4", "ta": "2,1"}


def test_part_a_cfg():
    dc = T.rd(os.path.join(FN, "dual_channel.c"))
    out = run_c(prelude(dc) + CFG_MAIN)
    o = kv(out)
    bad = {k: (o.get(k), v) for k, v in CFG_EXP.items() if o.get(k) != v}
    check(out is not None and not bad, "А1/Б7: розкладка reserved[1..3] (тип A біти 0..1, «A для повернення» біти 2..3 + номер), старі записи = як до FIX4, перенесення при dcFlush, вимкнення з поверненням -- один запис: %s" % bad)
    m = dc.replace("		dcCfgCopyReturnA(&want, &cur);", "")
    mo = run_c(prelude(m) + CFG_MAIN)
    check(m != dc and kv(mo).get("w") != CFG_EXP["w"], "А1 (мутант): dcFlush затирає «A для повернення» -- ловиться")
    # reserved[2..3] ніде більше не використовується (шумодав B у R98-FIX3 -- RAM s_dualSqlB)
    hits = []
    for root, _, files in os.walk(os.path.join(APP, "source")):
        for f in files:
            if f.endswith(".c"):
                t = T.rd(os.path.join(root, f))
                if re.search(r"reserved\[(2|3)\]", t) and f != "dual_channel.c":
                    hits.append(f)
    tools_hits = [f for f in os.listdir(HERE) if f.endswith(".py") and f not in ("test_r98fix4.py",) and "DUAL_CHANNEL" in T.rd(os.path.join(HERE, f)) and re.search(r"reserved\[(2|3)\]", T.rd(os.path.join(HERE, f)))]
    check(not hits, "А1: reserved[2..3] блоку 18 у прошивці читає/пише лише dual_channel.c: %s" % hits)
    print("А1: python-інструменти, що згадують reserved[2..3] разом із DUAL_CHANNEL: %s" % tools_hits)


# ------------------------------------------------------------------------------------------------ А: картки як до виходу (справжні функції режиму)
UI_STUBS = r'''
typedef struct { uint32_t rxFreq; uint8_t power; uint8_t sql; char tag; uint16_t num; } CodeplugChannel_t;
static CodeplugChannel_t channelScreenChannelData, scanNextChannelData, settingsVFOChannel[2], *currentChannelData = &channelScreenChannelData;
static struct { int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_indexNumber; int NOT_IN_CODEPLUGDATA_highestIndex; uint16_t channels[16]; } currentZone;
static struct { struct { bool active; int scanType; int state; } Scan; int displayQSOState; int currentSelectedChannelNumber; } uiDataGlobal;
enum { SCAN_TYPE_NORMAL_STEP = 0 }; enum { SCAN_STATE_SCANNING = 0 }; enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 }; enum { UI_CHANNEL_MODE = 3 };
enum { DC_PAIR_OK_ = 0 };
static bool scanNextChannelReady; static uint8_t s_dualSqlB; static uint32_t s_dualKeyMs;
static int used[1100]; static int lastUsed = 5; static int selB, leftB, leftVfo = -1, resumes, errs, suspends, tunes;
static uint16_t dualChannelA(void) { return (uint16_t)lastUsed; }   /* «останній канал зони» як абсолютний номер (модель) */
static bool codeplugAllChannelsIndexIsInUse(int c) { return (c >= 1 && c <= 1024) ? used[c] : 0; }
static uint16_t dualZoneChannelAt(int pos, void *ctx) { (void)ctx; return (pos >= 0 && pos < currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone && used[currentZone.channels[pos]]) ? currentZone.channels[pos] : 0; }
static void codeplugSetLastUsedChannelInZone(int z, int16_t p) { (void)z; lastUsed = (currentZone.NOT_IN_CODEPLUGDATA_indexNumber < 0) ? p : currentZone.channels[p]; }
static void codeplugChannelGetDataForIndex(int ch, CodeplugChannel_t *c) { memset(c, 0, sizeof *c); c->rxFreq = 1000u + (uint32_t)ch; c->power = 1; c->tag = 'C'; c->num = (uint16_t)ch; }
static dcPairCheck_t dualCheckPair(void) { uint16_t b = dcChannelB(); if (dcBIsVfo()) return DC_PAIR_OK; return dcCheckPair(dualChannelA(), b, codeplugAllChannelsIndexIsInUse(b)); }
static void dualShowPairError(dcPairCheck_t e) { (void)e; errs++; }
static void dualAutoResume(void) { resumes++; }
static bool dualIsRunning(void) { return false; }
static int menuSystemGetCurrentMenuNumber(void) { return UI_CHANNEL_MODE; }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
static bool dualSelectedIsB(void) { return selB; }
static uint8_t dualVfoIdx(void) { return (dcTypeB() == DC_TYPE_VFO_B) ? 1 : 0; }
static void dualLeaveOnVfo(uint8_t v) { leftVfo = v; dcSetOnB(false); }
static void dualLeaveOnB(void) { leftB++; lastUsed = dcChannelB(); dcSetOnB(false); }
static void dualSuspend(void) { suspends++; }
static void dualTune(bool b) { tunes++; dcSetOnB(b); }
@@FNS@@
static void zone(int all, int n, const int *ch) { currentZone.NOT_IN_CODEPLUGDATA_indexNumber = all ? -1 : 2; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = n; for (int i = 0; i < n; i++) currentZone.channels[i] = (uint16_t)ch[i]; }
static void st(const char *n) { printf("%s=A%d:%d,B%d:%d,ptr%d,onB%d,en%d,stash%d,buf%d\n", n, dcTypeA(), dualChannelA(), dcTypeB(), dcChannelB(), dcPointerB(), dcIsOnB(), dcIsEnabled(), scanNextChannelData.num, channelScreenChannelData.num); }
int main(void)
{
	int z1[] = { 5, 7, 12 }, z2[] = { 7, 12 };
	used[5] = used[7] = used[12] = 1;
	/* r1: A=5, B=12, режим, вихід на B (обраний B) -> рація на B (зона: last-used = 12) -> вмикання -> A=5, B=12, покажчик на B, рація на B */
	zone(0, 3, z1); memset(g_blk, 0, 8); g_have = 0; dcLoad(); dcSetChannelB(12, true); lastUsed = 5;
	dualEnable(0); selB = 1; dualDisable(); channelScreenChannelData.num = 12; currentChannelData = &channelScreenChannelData;
	dualEnable(0); st("r1");
	/* r2: вихід на B -> інший канал (7) -> вмикання -> A = 7 (звичайне правило) */
	selB = 1; dualDisable(); lastUsed = 7; selB = 0; dualEnable(0); st("r2");
	/* r3: вихід на A (обраний A) -> вмикання -> як було (A = поточний 7), «A для повернення» не перезаписано виходом на A */
	uint8_t rt; uint16_t ri; dcGetReturnA(&rt, &ri); int before = ri;
	selB = 0; dualDisable(); dcGetReturnA(&rt, &ri); int after = ri; dualEnable(0); st("r3"); printf("r3k=%d,%d\n", before, after);
	/* r4: вихід на B (A=7), колишній A видалено -> вмикання -> A = поточний (12) -> A==B */
	lastUsed = 7; dualEnable(0); selB = 1; dualDisable(); used[7] = 0; dualEnable(0); st("r4"); used[7] = 1;
	/* r5: вихід на B (A=5), зону змінено (5 не в зоні) -> A = поточний */
	zone(0, 3, z1); lastUsed = 5; dualEnable(0); selB = 1; dualDisable(); zone(0, 2, z2); dualEnable(0); st("r5");
	/* r6: «Всі канали» -- будь-який використаний */
	zone(1, 0, z1); lastUsed = 5; dualEnable(0); selB = 1; dualDisable(); dualEnable(0); st("r6");
	/* r11: «Всі канали», вихід на B (A=5), колишній A видалено -> A = поточний (12) */
	zone(1, 0, z1); lastUsed = 5; dualEnable(0); selB = 1; dualDisable(); used[5] = 0; lastUsed = 12; dualEnable(0); st("r11"); used[5] = 1;
	/* r7: старий запис (reserved = 0) -> як до FIX4 */
	zone(0, 3, z1); memset(g_blk, 0, 8); g_blk[0] = 1; g_blk[1] = 0; g_blk[2] = 12; g_have = 1; dcLoad(); lastUsed = 12; dualEnable(0); st("r7");
	/* r8: A = VFO A (з екрана VFO), B = 12; вихід на B -> вмикання з каналу 12 -> A = VFO A, покажчик на B */
	memset(g_blk, 0, 8); g_have = 0; dcLoad(); dcSetChannelB(12, true); dualEnable(1); selB = 1; dualDisable(); lastUsed = 12; dualEnable(0); st("r8");
	/* r9: вмикання з VFO B, B не задано -> авто B = VFO B (A == B) */
	memset(g_blk, 0, 8); g_have = 0; dcLoad(); dualEnable(2); st("r9"); printf("r9s=%d\n", dualSingle());
	/* r10: вихід на обраному A = VFO -> екран VFO з цим VFO; канальний буфер (тримав B) позначено порожнім */
	memset(g_blk, 0, 8); g_have = 0; dcLoad(); dcSetChannelB(12, true); dualEnable(2); channelScreenChannelData.rxFreq = 1012; selB = 0; dualDisable(); printf("r10=%d,%d,%d\n", leftVfo, (int)channelScreenChannelData.rxFreq, dcIsEnabled());
	return 0;
}
'''
UI_EXP = {"r1": "A0:5,B0:12,ptr1,onB1,en1,stash5,buf12", "r2": "A0:7,B0:12,ptr1,onB0,en1,stash5,buf12", "r3k": "5,5",
          "r4": "A0:12,B0:12,ptr1,onB0,en1", "r5": "A0:12,B0:12,ptr1,onB0,en1", "r6": "A0:5,B0:12,ptr1,onB1,en1", "r7": "A0:12,B0:12,ptr0,onB0,en1", "r11": "A0:12,B0:12,ptr1,onB0,en1",
          "r8": "A1:12,B0:12,ptr1,onB1,en1", "r9": "A2:", "r9s": "1", "r10": "1,0,0"}
UI_SIGS = ("static _Bool dualApplyReturnA(uint8_t rt, uint16_t ri)", "static _Bool dualEnable(uint8_t typeCur)", "static uint8_t dualCardVfo(_Bool isB)",
           "static void dualDisable(void)", "static _Bool dualBSameAsA(void)", "static _Bool dualBExists(void)", "static _Bool dualSingle(void)")


def ui_check(o):
    bad = {}
    for k, v in UI_EXP.items():
        got = o.get(k) or ""
        if not got.startswith(v):
            bad[k] = (got, v)
    return bad


def test_part_a_ui(t):
    dc = T.rd(os.path.join(FN, "dual_channel.c"))
    fns = [T.carve_fn(t, s) for s in UI_SIGS]
    check(all(fns), "А2: функції вмикання/виходу знайдено: %s" % [s for s, f in zip(UI_SIGS, fns) if not f])
    if not all(fns):
        return
    src = "\n".join(fns)
    out = run_c(prelude(dc) + UI_STUBS.replace("@@FNS@@", src))
    o = kv(out)
    bad = ui_check(o)
    check(out is not None and not bad, "А2-А5: картки як до виходу (вихід на B -> вмикання), інший канал, вихід на A, A видалено, зміна зони, «Всі канали», старі записи, A = VFO, A==B VFO, вихід на A = VFO: %s" % bad)
    for line in (out or "").splitlines():
        if line.startswith("r1=") or line.startswith("r8="):
            print("   " + line)
    muts = (("«A для повернення» не зберігається", src.replace("(void)dcDisableWithReturnA(retType, retIdx);", "(void)dcSetEnabled(0, 1);")),
            ("зберігається при виході на A", src.replace(" dcSetTxHold(0);\n (void)dcSetEnabled(0, 1);\n uiDataGlobal.displayQSOState", " dcSetTxHold(0);\n (void)dcDisableWithReturnA(retType, retIdx);\n uiDataGlobal.displayQSOState")),
            ("відновлює недійсний (видалений) A", src.replace("if (codeplugAllChannelsIndexIsInUse(ri) == 0)\n  {\n   return 0;\n  }", "")),
            ("відновлює A з іншої зони", src.replace("if (pos < 0)\n  {\n   return 0;\n  }", "if (pos < 0)\n  {\n   pos = 0;\n  }")),
            ("вихід на A = VFO іде в екран каналів", src.replace("dualLeaveOnVfo(dualCardVfo(0));", ";")),
            ("рівність за номером (без типу)", src.replace("return dcSameTarget(dcTypeA(), dualChannelA(), dcTypeB(), dcChannelB());", "return (dualChannelA() == dcChannelB());")))
    for what, m in muts:
        mo = run_c(prelude(dc) + UI_STUBS.replace("@@FNS@@", m)) if m != src else None
        check(m != src and mo is not None and ui_check(kv(mo)), "А/Б (мутант): %s -- ловиться" % what)


# ------------------------------------------------------------------------------------------------ Б: чергування, копія A (Б11), коло ручки, ізоляція VFO, читання флешу (Б14)
TUNE_STUBS = r'''
typedef struct { uint32_t rxFreq; uint32_t txFreq; uint8_t power; uint8_t sql; uint8_t chMode; uint8_t libreDMR_Power; uint8_t rxGroupList; uint8_t flags; char tag; uint16_t num; } CodeplugChannel_t;
typedef struct { char name[16]; uint32_t tgNumber; } CodeplugContact_t;
typedef struct { char name[16]; int NOT_IN_CODEPLUG_numTGsInGroup; } CodeplugRxGroup_t;
static CodeplugChannel_t channelScreenChannelData, scanNextChannelData, settingsVFOChannel[2], *currentChannelData = &channelScreenChannelData;
static CodeplugRxGroup_t currentRxGroupData; static int lastLoadedRxGroup = -1;
static struct { uint8_t currentVFONumber; uint32_t overrideTG; int16_t currentIndexInTRxGroupList[4]; } nonVolatileSettings;
static uint8_t previousVFONumber;
static struct { int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_indexNumber; int NOT_IN_CODEPLUGDATA_highestIndex; uint16_t channels[16]; } currentZone;
static struct { struct { bool active; int scanType; int state; } Scan; int displayQSOState; int currentSelectedChannelNumber; } uiDataGlobal;
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 }; enum { UI_CHANNEL_MODE = 3 }; enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
#define SETTINGS_CHANNEL_MODE 0
#define CH_DETAILS_VFO_CHANNEL -1
#define RADIO_DEVICE_PRIMARY 0
#define CHANNEL_FLAG_FORCE_DMO 1
enum { DMR_MODE_DMO = 1, DMR_MODE_AUTO = 2 };
static int16_t s_dualTgIdxA; static uint8_t s_dualSqlB; static uint32_t s_dualKeyMs; static int directChannelNumber;
static int used[1100]; static int lastUsed = 5, reads, contactReads, groupReads, vfoLoads, loadsMem = -1, beeps, resumes;
static int16_t g_ovrStock = 0;
static void lastHeardClearLastID(void) {}
static void dmrAesRxRetune(void) {}
static uint16_t dualChannelA(void) { return (uint16_t)lastUsed; }
static uint8_t dualVfoIdx(void) { return (dcTypeB() == DC_TYPE_VFO_B) ? 1 : 0; }
static bool codeplugAllChannelsIndexIsInUse(int c) { return (c >= 1 && c <= 1024) ? used[c] : 0; }
static uint16_t dualZoneChannelAt(int pos, void *ctx) { (void)ctx; return (pos >= 0 && pos < currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone && used[currentZone.channels[pos]]) ? currentZone.channels[pos] : 0; }
static void codeplugSetLastUsedChannelInZone(int z, int16_t p) { (void)z; lastUsed = (currentZone.NOT_IN_CODEPLUGDATA_indexNumber < 0) ? p : currentZone.channels[p]; }
static void codeplugChannelGetDataForIndex(int ch, CodeplugChannel_t *c) { reads++; memset(c, 0, sizeof *c); c->rxFreq = 1000u + (uint32_t)ch; c->power = 1; c->tag = 'C'; c->num = (uint16_t)ch; c->chMode = 1; }
/* стокове завантаження каналу: з пам'яті -- буфер як є; інакше -- «останній канал зони» з кодплага (читання) */
static void uiChannelModeLoadChannelData(bool mem, bool vp) { (void)vp; loadsMem = mem; if (!mem) codeplugChannelGetDataForIndex(lastUsed, &channelScreenChannelData); }
static void settingsSetBOOL(bool *p, bool v) { *p = v; }
static void settingsSetINT8(int8_t *p, int8_t v) { *p = v; }
static void settingsSetUINT8(uint8_t *p, uint8_t v) { *p = v; }
static void settingsSetINT16(int16_t *p, int16_t v) { *p = v; }
static void settingsSetUINT16(uint16_t *p, uint16_t v) { *p = v; }
static void settingsSetINT32(int32_t *p, int32_t v) { *p = v; }
static void settingsSetUINT32(uint32_t *p, uint32_t v) { *p = v; }
/* стоковий VFO (для справжнього uiVFOModeDualLoad): стокове завантаження VFO псує глобальний стан -- ізоляція має його повернути */
static void HRC6000ClearActiveDMRID(void) {}
static void radioSetTRxDevice(int d) { (void)d; }
static void trxSetFrequency(uint32_t a, uint32_t b, int m) { (void)a; (void)b; (void)m; }
static int codeplugChannelGetFlag(CodeplugChannel_t *c, int f) { (void)c; (void)f; return 0; }
static bool codeplugRxGroupGetDataForIndex(int i, CodeplugRxGroup_t *g) { (void)i; groupReads++; memset(g, 0, sizeof *g); return true; }
static void uiVFOLoadContact(CodeplugContact_t *c) { contactReads++; memset(c, 0, sizeof *c); strcpy(c->name, "TG"); c->tgNumber = 91; }
static void uiVFOModeLoadChannelData(bool f) { (void)f; vfoLoads++; contactReads++; nonVolatileSettings.overrideTG = 9; previousVFONumber = nonVolatileSettings.currentVFONumber; }
static void dualSuspend(void) {}
static void dualAutoResume(void) { resumes++; }
static bool dualIsRunning(void) { return false; }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
static int menuSystemGetCurrentMenuNumber(void) { return UI_CHANNEL_MODE; }
static void soundSetMelody(const int *m) { (void)m; beeps++; }
static const int MELODY_ERROR_BEEP[1];
@@FNS@@
static void zone(int n, const int *ch) { currentZone.NOT_IN_CODEPLUGDATA_indexNumber = 2; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = n; for (int i = 0; i < n; i++) currentZone.channels[i] = (uint16_t)ch[i]; }
static int where(void) { return (currentChannelData == &channelScreenChannelData) ? 0 : ((currentChannelData == &settingsVFOChannel[0]) ? 1 : 2); }
static void setup(int ta, int tb, int chb) { memset(g_blk, 0, 8); g_have = 0; dcLoad(); dcSetChannelB((uint16_t)chb, true); if (tb) dcSetTypeB((uint8_t)tb); dcSetTypeA((uint8_t)ta); dcSetEnabled(true, true);
	codeplugChannelGetDataForIndex(5, &channelScreenChannelData); channelScreenChannelData.power = 9; channelScreenChannelData.tag = 'A';   /* A (канал 5) з незбереженою правкою «потужність 9» */
	memset(&scanNextChannelData, 0, sizeof scanNextChannelData); lastUsed = 5; currentChannelData = (ta ? &settingsVFOChannel[ta - 1] : &channelScreenChannelData);
	nonVolatileSettings.currentVFONumber = 0; previousVFONumber = 1; nonVolatileSettings.overrideTG = 0; dcSetOnB(false); }
int main(void)
{
	int z[] = { 5, 7, 12 };
	used[5] = used[7] = used[12] = 1; zone(3, z);
	settingsVFOChannel[0].rxFreq = 43500000; settingsVFOChannel[1].rxFreq = 14550000; settingsVFOChannel[0].tag = 'V'; settingsVFOChannel[1].tag = 'W';
	/* комбінації A/B x канал/VFO: 3 цикли A<->B; після -- рація на A, правка A (канал) жива, ізоляція стока (currentVFONumber 0, previous 1, overrideTG 0) */
	int combos[4][2] = { { 0, 0 }, { 0, 2 }, { 1, 0 }, { 1, 2 } };
	for (int k = 0; k < 4; k++)
	{
		setup(combos[k][0], combos[k][1], 12);
		int ok = 1;
		for (int i = 0; i < 3; i++)
		{
			dualTune(true); int wb = where(); char tb = currentChannelData->tag;
			dualTune(false); int wa = where(); char ta = currentChannelData->tag;
			if (combos[k][1] == 0 && (wb != 0 || tb != 'C')) ok = 0;            /* B = канал 12 -- у канальному буфері */
			if (combos[k][1] == 2 && (wb != 2 || tb != 'W')) ok = 0;            /* B = VFO B */
			if (combos[k][0] == 0 && (wa != 0 || ta != 'A' || channelScreenChannelData.power != 9)) ok = 0;   /* A = канал -- з правкою */
			if (combos[k][0] == 1 && (wa != 1 || ta != 'V')) ok = 0;            /* A = VFO A */
		}
		printf("c%d=%d,%d,%d,%u,%c\n", k, ok, nonVolatileSettings.currentVFONumber, previousVFONumber, (unsigned)nonVolatileSettings.overrideTG, scanNextChannelData.tag ? scanNextChannelData.tag : '-');
	}
	/* Б11: A = канал (правка 9) -> ручкою на VFO -> на B (канал) і назад -> ручкою назад на канал: канал свіжо з кодплага (1), а не стара копія (9) і не B */
	setup(0, 0, 12); lastUsed = 12; dualStepA(1); int s1 = dcTypeA(); dualTune(true); dualTune(false); int s2 = where();
	dualStepA(1); int s3 = dcTypeA(); dualStepA(1); printf("k=%d,%d,%d,%d,%d,%d,%c\n", s1, s2, s3, dcTypeA(), lastUsed, channelScreenChannelData.power, channelScreenChannelData.tag);
	/* коло ручки на A: з 12 (останній) вперед -> VFO A -> VFO B -> 5; назад з 5 -> VFO B -> VFO A -> 12 */
	setup(0, 0, 7); lastUsed = 12; int f[4]; for (int i = 0; i < 3; i++) { dualStepA(1); f[i] = dcAIsVfo() ? -(int)dcTypeA() : lastUsed; }
	int bk[3]; for (int i = 0; i < 3; i++) { dualStepA(-1); bk[i] = dcAIsVfo() ? -(int)dcTypeA() : lastUsed; }
	printf("ring=%d,%d,%d|%d,%d,%d\n", f[0], f[1], f[2], bk[0], bk[1], bk[2]);
	/* канал -> канал: стоковий шлях (false) */
	setup(0, 0, 7); lastUsed = 5; printf("st=%d\n", dualStepA(1));
	/* Б5 рівність: VFO A == VFO A; VFO A != VFO B з тією самою частотою; канал 12 != VFO; канал/канал за номером */
	setup(1, 1, 12); int e1 = dualBSameAsA(); settingsVFOChannel[1].rxFreq = settingsVFOChannel[0].rxFreq; setup(1, 2, 12); int e2 = dualBSameAsA(); setup(1, 0, 5); int e3 = dualBSameAsA(); setup(0, 0, 5); int e4 = dualBSameAsA();
	printf("eq=%d,%d,%d,%d\n", e1, e2, e3, e4); settingsVFOChannel[1].rxFreq = 14550000;
	/* Б14: читання флешу на одне налаштування (кодплаг-канал / контакт / група) */
	setup(0, 0, 12); reads = contactReads = groupReads = 0; dualTune(true); int rc = reads, cc = contactReads, gc = groupReads;
	setup(0, 1, 12); reads = contactReads = groupReads = 0; settingsVFOChannel[0].chMode = 2; settingsVFOChannel[0].rxGroupList = 3; lastLoadedRxGroup = -1; dualTune(true); int rv = reads, cv = contactReads, gv = groupReads;
	printf("io=%d,%d,%d|%d,%d,%d\n", rc, cc, gc, rv, cv, gv);
	return 0;
}
'''
TUNE_EXP = {"c0": "1,0,1,0,A", "c1": "1,0,1,0,-", "c2": "1,0,1,0,-", "c3": "1,0,1,0,-", "k": "1,1,2,0,5,1,C", "ring": "-1,-2,5|-2,-1,12", "st": "0", "eq": "1,0,0,1"}
TUNE_SIGS = ("static uint8_t dualCardVfo(_Bool isB)", "static _Bool dualCardIsVfo(_Bool isB)", "static _Bool dualOnVfoNow(void)", "static _Bool dualBufHoldsB(void)",
             "static void dualTune(_Bool toB)", "static _Bool dualStepA(int dir)", "static _Bool dualBSameAsA(void)")


def tune_check(o):
    bad = {}
    for k, v in TUNE_EXP.items():
        got = o.get(k)
        if got != v:
            bad[k] = (got, v)
    return bad


def test_part_b(t, tv):
    dc = T.rd(os.path.join(FN, "dual_channel.c"))
    fns = [T.carve_fn(t, s) for s in TUNE_SIGS]
    vl = T.carve_fn(tv, "void uiVFOModeDualLoad(uint8_t vfo, _Bool freshTune)")
    check(all(fns) and vl is not None, "Б: функції чергування/кола/ізоляції знайдено")
    if not (all(fns) and vl):
        return
    src = vl + "\n" + "\n".join(fns)
    out = run_c(prelude(dc) + TUNE_STUBS.replace("@@FNS@@", src))
    o = kv(out)
    bad = tune_check(o)
    check(out is not None and not bad, "Б3/Б5/Б11/Б4: чергування для A/B x канал/VFO (ізоляція стока VFO, копія A лише для A = канал), перехід A канал<->VFO без старої копії, коло ручки на A, рівність за (тип, індекс): %s" % bad)
    io = o.get("io", "")
    print("Б14: читання на одне налаштування (кодплаг-канал, контакт, група): канал B: %s; VFO B (DMR, група 3, не кешована): %s" % tuple(io.split("|")) if "|" in io else "Б14: %s" % io)
    muts = (("A = VFO трактується як канал", re.sub(r"if \(dcAIsVfo\(\)\)(\s*\{\s*currentChannelData = &settingsVFOChannel\[dualCardVfo\(0\)\];)", r"if (0)\1", src)),
            ("ізоляція не відновлює стан стока", src.replace(" nonVolatileSettings.overrideTG = savedOverride;\n nonVolatileSettings.currentVFONumber = savedVfo;\n previousVFONumber = savedPrev;", "")),
            ("копія A відновлюється при A = VFO", src.replace("if ((bufHoldsB == 0) && (dcAIsVfo() == 0))", "if (bufHoldsB == 0)")),
            ("перехід VFO -> канал відновлює стару копію", src.replace("currentChannelData = &channelScreenChannelData;\n  uiChannelModeLoadChannelData(0, 1);", "currentChannelData = &channelScreenChannelData;\n  memcpy(&channelScreenChannelData, &scanNextChannelData, sizeof(CodeplugChannel_t));\n  uiChannelModeLoadChannelData(1, 1);")),
            ("рівність за номером -1 / без типу", src.replace("return dcSameTarget(dcTypeA(), dualChannelA(), dcTypeB(), dcChannelB());", "return (dcBIsVfo() == dcAIsVfo());")))
    for what, m in muts:
        mo = run_c(prelude(dc) + TUNE_STUBS.replace("@@FNS@@", m)) if m != src else None
        check(m != src and mo is not None and tune_check(kv(mo)), "Б (мутант): %s -- ловиться" % what)


# ------------------------------------------------------------------------------------------------ Б: статика
def test_static():
    uc = T.rd(os.path.join(UI, "uiChannelMode.c"))
    vm = T.rd(os.path.join(UI, "uiVFOMode.c"))
    ms = T.rd(os.path.join(APP, "include", "user_interface", "menuSystem.h"))
    # Б1: вмикання з VFO -- у режимі каналів, стоковий перехід екрана
    ef = uc[uc.find("bool uiChannelModeDualEnableFromVfo(uint8_t vfo)\n{"):]
    ef = ef[:ef.find("\n}\n")]
    check("dualEnable((vfo == 1U) ? (uint8_t)DC_TYPE_VFO_B : (uint8_t)DC_TYPE_VFO_A)" in ef and "menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, true);" in ef and "codeplugSetLastUsedChannelInZone" not in ef and "settingsSet(" not in ef,
          "Б1: вмикання з екрана VFO: A = поточний VFO, стоковий перехід на екран каналів (зона/канал/«останній канал зони» не змінюються, налаштувань не пише)")
    fr = uc[uc.find("static menuStatus_t uiChannelModeFirstRun(void)"):]
    fr = fr[:fr.find("if ((uiDataGlobal.displayQSOState == QSO_DISPLAY_CALLER_DATA)")]
    check(fr.find("if (dualOnVfoNow())") > 0 and fr.find("if (dualOnVfoNow())") < fr.find("if (currentChannelData->rxFreq != 0U)") and "#if defined(DUAL_CHANNEL_ENABLED)" in fr,
          "Б1/Б12: перший запуск екрана каналів при A (або B) = VFO -- налаштування VFO, канал зони не читається (зміна зони при A = VFO лишає A = VFO)")
    # Б2: довге ▼ і пункт меню у VFO
    ld = vm[vm.find("KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN)\n#else"):]
    ld = ld[:1500]
    check("VFO_SCREEN_OPERATION_SCAN" in ld and ld.find("uiVFOModeStopScanning();") < ld.find("vfoDualStart();") and "KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_FRONT_DOWN) == false" in ld,
          "Б2: довге ▼ у VFO: стокова зупинка сканування частот лишається першою, у звичайному режимі -- вмикання режиму (без автоповтору й SK)")
    en = ms[ms.find("enum VFO_SCREEN_QUICK_MENU_ITEMS"):]
    en = en[:en.find("};")]
    check("VFO_SCREEN_QUICK_MENU_DUAL_CHANNEL" not in en and "VFO_SCREEN_QUICK_MENU_DUAL_CHANNEL" not in vm,
          "Б2 (R98-FIX5 В2): пункт «Подв. прийом» у кінці швидкого меню VFO прибрано -- наш режим запускає стоковий пункт «Dual Watch» (test_r98fix5)")
    # Б15: стоковий Dual Watch -- без змін; наш не вмикається разом зі стоковим
    vs = vm[vm.find("static void vfoDualStart(void)\n{"):]
    vs = vs[:vs.find("\n}\n")]
    check("(screenOperationMode[nonVolatileSettings.currentVFONumber] != VFO_SCREEN_OPERATION_NORMAL) || uiDataGlobal.Scan.active" in vs and "MELODY_ERROR_BEEP" in vs,
          "Б15: поки стоковий Dual Watch / сканування / розгортка VFO активні -- наш режим не вмикається (звук помилки)")
    if base_available():
        b = base_file("application/source/user_interface/uiVFOMode.c") or ""
        def blk(x):
            i = x.find("case VFO_SCREEN_QUICK_MENU_DUAL_SCAN:\n\t\t\t\t\tuiDataGlobal.Scan.active = true;")
            return x[i:x.find("break;", i)] if i >= 0 else None
        check(blk(vm) is not None and blk(vm) == blk(b), "Б15: стоковий пункт «Dual Watch» (VFO_SCREEN_QUICK_MENU_DUAL_SCAN) -- без змін відносно бази %s" % BASE)
        bm = base_file("application/include/user_interface/menuSystem.h") or ""
        be = bm[bm.find("enum VFO_SCREEN_QUICK_MENU_ITEMS"):]
        be = be[:be.find("NUM_VFO_SCREEN_QUICK_MENU_ITEMS")]
        check(en.startswith(be.rstrip()), "Б2: стокові пункти швидкого меню VFO й їхній порядок -- як у базі")
    else:
        print("ПРОПУСК: база недоступна (CI/клон без історії): порівняння стокового Dual Watch з базою не виконано")
    # Б13: пауза APRS-прийому й автопереходу роумінгу -- за станом режиму, не за екраном
    ax = T.rd(os.path.join(FN, "aprs_rx.c")); wh = T.rd(os.path.join(FN, "wake_hop.c"))
    i = ax.find("dcIsEnabled()")
    ctx = ax[max(0, i - 400):i + 400]
    check(i > 0 and "UI_CHANNEL_MODE" not in ctx and "menuSystemGetCurrentMenuNumber" not in ctx, "Б13: aprs_rx.c призупиняє приймач за dcIsEnabled(), без прив'язки до екрана (DW з екрана VFO -- так само)")
    # роумінг: стокова умова «лише в режимі каналів» (екран режиму -- завжди екран каналів, і з VFO теж) + окремий доданок «режим вимкнено»
    check("(dcIsEnabled() == false) &&" in wh and "(menuSystemGetRootMenuNumber() == UI_CHANNEL_MODE) &&" in wh, "Б13: wake_hop.c -- автоперехід роумінгу вимкнено, поки режим ввімкнено (окремий доданок; екран режиму -- екран каналів і при вмиканні з VFO)")
    mut = ax.replace("if (dcIsEnabled())", "if (dcIsEnabled() && (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE))", 1)
    i = mut.find("dcIsEnabled()")
    check(mut != ax and "UI_CHANNEL_MODE" in mut[max(0, i - 400):i + 400], "Б13 (мутант): пауза APRS лише з екрана каналів -- статична перевірка ловить")
    # Б3: усі «рація на VFO»-гілки -- спільні для A і B
    check("uiVFOModeDualLoad(dualCardVfo(dcIsOnB()), false);" in uc and "uiVFOModeDualLoad(dualCardVfo(false), true);" in uc and "bool uiChannelModeDualOnVfo(void)\n{\n\treturn dualOnVfoNow();" in uc,
          "Б3: повернення з передачі/меню, чергування і меню на обраному VFO -- однаково для A = VFO і B = VFO")
    check("bool freq = dualCardIsVfo(dcPointerB());" in uc and "uiVFOModeDualFreqEnter(dualCardVfo(dcIsOnB())" in uc and "uiVFOModeDualStep(dualCardVfo(dcIsOnB())" in uc and
          "if (dualOnVfoNow())\n\t{\n\t\tsettingsSetVFODirty();" in uc,
          "Б3: цифри (частота), SK2 + ручка (крок), SK1 + ручка (шумодав, запис VFO) -- на картці VFO з покажчиком (A або B)")
    check("dualRenderRow(DW_CARD_A_Y, false, dualChannelA(), dcTypeA()," in uc, "Б3: картка A малюється за своїм типом (канал/VFO)")
    # Б9: нових масивів/змінних нема (тип A -- у вільних бітах s_dc)
    dcc = T.rd(os.path.join(FN, "dual_channel.c"))
    sd = dcc[dcc.find("static struct\n{"):dcc.find("} s_dc;")]
    check("uint8_t  typeA    : 2;" in sd and sd.count("[") == 0, "Б9: тип A -- 2 біти у вільних бітах байта прапорців s_dc (розмір структури той самий), масивів нема")


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    t = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c") or ""
    tv = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiVFOMode.c") or ""
    test_part_a_cfg()
    test_part_a_ui(t)
    test_part_b(t, tv)
    test_static()
    print("test_r98fix4: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
