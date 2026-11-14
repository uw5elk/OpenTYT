#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX1 (хост): «Подвійний прийом».
  А  швидке меню без «Встановити як B» (нумерація, статична відсутність), авто B = A при вмиканні (хостова модель справжнього dualSetMode + мутанти);
  Б  аудит зони «Всі канали»: модель (до 1024 слотів, прогалини, межі 1/1024, обгортання, VFO A/B) на справжніх dualStepB/dualZoneChannelAt/dcStepExt/dcFindPos,
     справжні codeplugGet/SetLastUsedChannelInZone (0xFFFF, 0, >1024, невикористаний), dualLeaveOnB, dualChannelA;
  В  таймер QSO у режимі -> екран режиму (справжня функція + мутант), панель SK1 без S-метра (предикат), вихід з меню лишає на ОБРАНОМУ (справжня StopScanning + мутант);
  Г  меню на обраному VFO: відро ТС-перекриття, захист ROAMING, деталі каналу/VFO, «перечитати зону»;
  Д  непрочитані SMS за джерелом: два лічильники (справжній dual_channel.c), хук прийому, показ; мутанти.
Запуск: python3 tools/test_r98fix1.py"""
import os, re, subprocess, sys, tempfile, shutil, random
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
FN = os.path.join(APP, "source", "functions")
INC = os.path.join(APP, "include")
BASE = "a76fb2b"   # коміт бази R98-FIX1 (HEAD після R98)


def run_in(code, stdin="", extra=()):
    """Збирає й запускає хост-програму зі stdin."""
    d = tempfile.mkdtemp(prefix="r98f1_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-I", INC] + list(extra) + ["-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:2000]); return None
        return subprocess.run([os.path.join(d, "h")], input=stdin.encode(), capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def base_available():
    r = subprocess.run(["git", "cat-file", "-e", BASE + "^{commit}"], cwd=FW, capture_output=True)
    return r.returncode == 0


def kv(out):
    return dict(l.split("=", 1) for l in (out or "").splitlines() if "=" in l)


# ------------------------------------------------------------------------------------------------ А
def enum_items(src, name):
    m = re.search(r"enum " + name + r"\s*\{(.*?)\n\};", src, re.S)
    body = m.group(1)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    out = []
    for l in body.splitlines():
        l = l.strip()
        if l.startswith("#") or not l:
            continue
        out.append(l.rstrip(",").split("=")[0].strip())
    return out


AUTOB_HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "@@DC@@"
enum { NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2, UI_CHANNEL_MODE = 7 };
static const int MELODY_ERROR_BEEP[1];
struct { char dual_on[8]; char dual_off[8]; char dual_err_no_b[8]; char dual_err_b_gone[8]; } lang = { "ON", "OFF", "NOB", "GONE" }, *currentLanguage = &lang;
static int chA, chBv, enabled, setCalls, setVal, errNoB, errGone, beeps, enCalls, resume, disableCalls, notif; static unsigned char used[1100];
static uint32_t s_dualKeyMs = 77;
static bool codeplugAllChannelsIndexIsInUse(int c) { return (c >= 1) && (c <= 1024) && used[c]; }
static uint16_t dualChannelA(void) { return (uint16_t)chA; }
static dcPairCheck_t dualCheckPair(void) { return dcCheckPair((uint16_t)chA, (uint16_t)chBv, ((chBv >= 1) && (chBv <= 1024)) ? used[chBv] : false); }
static bool dcSetChannelB(uint16_t ch, bool now) { (void)now; setCalls++; setVal = ch; chBv = ch; return true; }
static void dualShowPairError(dcPairCheck_t e) { if (e == DC_PAIR_NO_B) errNoB++; else errGone++; beeps++; }
static void dcSetTxHold(bool h) { (void)h; }
static bool dcSetEnabled(bool on, bool now) { (void)now; enCalls++; enabled = on; return true; }
static void dualAutoResume(void) { resume++; }
static void dualDisable(void) { disableCalls++; enabled = 0; }
static bool dualIsRunning(void) { return false; }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
static int menuSystemGetCurrentMenuNumber(void) { return UI_CHANNEL_MODE; }
static void uiNotificationShow(int a, int b, uint32_t c, const char *m, bool d) { (void)a; (void)b; (void)c; (void)m; (void)d; notif++; }
@@FN@@
static void reset(int a, int b) { chA = a; chBv = b; enabled = 0; setCalls = 0; setVal = 0; errNoB = errGone = beeps = enCalls = resume = disableCalls = notif = 0; }
static void rep(const char *n) { printf("%s=B%d,set%d/%d,err%d/%d,beep%d,en%d,res%d\n", n, chBv, setCalls, setVal, errNoB, errGone, beeps, enCalls, resume); }
int main(void)
{
	used[42] = used[50] = used[77] = 1;
	reset(42, 0); dualSetMode(true, false); rep("e1");            /* B не задано, A=42 існує -> B=A, режим вмикається без помилки/звуку */
	reset(42, 77); dualSetMode(true, false); rep("e2");           /* B задано -> не змінюється */
	reset(42, 60); dualSetMode(true, false); rep("e3");           /* B видалено (60 не використовується) -> як було: помилка, режим не вмикається */
	reset(0, 0); dualSetMode(true, false); rep("e4");             /* A без допустимого номера -> «B не задано», не вмикаємо */
	reset(43, 0); dualSetMode(true, false); rep("e5");            /* A не використовується -> так само */
	reset(42, 0); dualSetMode(true, false); dualSetMode(false, false); chA = 50; dualSetMode(true, false); rep("e6");   /* повторні вмикання: B лишається 42 */
	reset(42, 0); dualSetMode(true, false); dualSetMode(true, false); rep("e7");
	reset(2000, 0); dualSetMode(true, false); rep("e8");          /* номер A поза 1..1024 */
	return 0;
}
'''


def test_part_a(incs, cf):
    hdr = T.rd(os.path.join(INC, "user_interface", "menuSystem.h"))
    items = enum_items(hdr, "CHANNEL_SCREEN_QUICK_MENU_ITEMS")
    want = ["CH_SCREEN_QUICK_MENU_COPY2VFO", "CH_SCREEN_QUICK_MENU_COPY_FROM_VFO", "CH_SCREEN_QUICK_MENU_FILTER_FM", "CH_SCREEN_QUICK_MENU_FILTER_DMR",
            "CH_SCREEN_QUICK_MENU_DMR_CC_SCAN", "CH_SCREEN_QUICK_MENU_FILTER_DMR_TS", "CH_SCREEN_QUICK_MENU_TALKAROUND", "CH_SCREEN_QUICK_MENU_ROAMING",
            "CH_SCREEN_QUICK_MENU_AUDIO_MUTE", "CH_SCREEN_QUICK_MENU_DELETE", "CH_SCREEN_QUICK_MENU_ZONE_REMOVE", "CH_SCREEN_QUICK_MENU_DUAL_CHANNEL",
            "NUM_CH_SCREEN_QUICK_MENU_ITEMS"]
    check(items == want, "А1: пункти швидкого меню каналу -- без SET_B, порядок решти той самий, «Подв. прийом» ОСТАННІЙ: %r" % items)
    if base_available():
        old = subprocess.run(["git", "show", BASE + ":MDUV380_firmware/application/include/user_interface/menuSystem.h"], cwd=FW, capture_output=True).stdout.decode()
        oi = enum_items(old, "CHANNEL_SCREEN_QUICK_MENU_ITEMS")
        check(oi[:len(want) - 1] == want[:-1] and oi[len(want) - 1] == "CH_SCREEN_QUICK_MENU_SET_B", "А1: у базі SET_B стояв ПІСЛЯ «Подв. прийом» -- нумерація решти пунктів (швидкі клавіші) не зсунулась")
    else:
        print("ПРОПУСК: база недоступна (CI/клон без історії) -- порівняння нумерації з базою")
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    check(re.search(r"QUICK_MENU_SET_B\b", src) is None and re.search(r"QUICK_MENU_SET_B\b", hdr) is None, "А1: статично -- у коді екрана каналу й заголовку меню нема SET_B")
    check("dual_set_b" not in src and "dual_b_saved" not in src, "А1: поля мови dual_set_b/dual_b_saved у коді не використовуються")
    ul = T.rd(os.path.join(T.LANG, "uiLanguage.h"))
    check("dual_set_b[LANGUAGE_TEXTS_LENGTH]" in ul and "dual_b_saved[LANGUAGE_TEXTS_LENGTH]" in ul, "А1: поля мови лишено (порядок полів не змінено)")
    check("dualQuickMenuApply(void)" in src and "bool setB" not in src, "А1: dualQuickMenuApply без параметра setB")
    if "DUALCH" not in cf:
        check(False, "конфігурація DUALCH є"); return
    t = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    fn = T.carve_fn(t or "", "static void dualSetMode(_Bool on, _Bool notify)")
    check(fn is not None, "А2: dualSetMode знайдено")
    if fn is None:
        return
    dc = os.path.join(FN, "dual_channel.c")
    code = AUTOB_HARNESS.replace("@@DC@@", dc)
    out = run_in(code.replace("@@FN@@", fn))
    check(out is not None, "А2: хостова збірка dualSetMode")
    if out is None:
        return
    o = kv(out)
    check(o.get("e1") == "B42,set1/42,err0/0,beep0,en1,res1", "А2: B не задано -> B = A (42), запис, без помилки й звуку, режим вмикається: %s" % o.get("e1"))
    check(o.get("e2") == "B77,set0/0,err0/0,beep0,en1,res1", "А2: B задано -> не змінюється: %s" % o.get("e2"))
    check(o.get("e3") == "B60,set0/0,err0/1,beep1,en0,res0", "А2: «B видалено» -- як було (помилка, режим не вмикається, B не чіпаємо): %s" % o.get("e3"))
    check(o.get("e4") == "B0,set0/0,err1/0,beep1,en0,res0", "А2: A без допустимого номера -- «B не задано», нічого не вигадуємо: %s" % o.get("e4"))
    check(o.get("e5") == "B0,set0/0,err1/0,beep1,en0,res0", "А2: A не використовується -- «B не задано»: %s" % o.get("e5"))
    check(o.get("e6") == "B42,set1/42,err0/0,beep0,en2,res2", "А2: повторні вмикання (з іншим A) B не міняють: %s" % o.get("e6"))
    check(o.get("e7") == "B42,set1/42,err0/0,beep0,en2,res2", "А2: вдруге увімкнути -- запис лише раз: %s" % o.get("e7"))
    check(o.get("e8") == "B0,set0/0,err1/0,beep1,en0,res0", "А2: номер A поза 1..1024 -- не вмикаємо: %s" % o.get("e8"))
    muts = (("B не записується", fn.replace("(void)dcSetChannelB(idxCur, 1);", "")),
            ("після авто B пара не перевіряється (помилка лишається)", re.sub(r"(?m)^\s+chk = dualCheckPair\(\);", "", fn)),
            ("авто B без перевірки використання A", fn.replace(" && codeplugAllChannelsIndexIsInUse(idxCur)", "")),
            ("авто B і при заданому B (перезапис)", fn.replace("if (chk == DC_PAIR_NO_B)", "if (1)")),
            ("авто B і при «B видалено»", fn.replace("if (chk == DC_PAIR_NO_B)", "if (chk != DC_PAIR_OK)")))
    for what, mut in muts:
        mo = run_in(code.replace("@@FN@@", mut)) if mut != fn else None
        check(mut != fn and mo is not None and mo != out, "А2 (мутант): %s -- ловиться" % what)


# ------------------------------------------------------------------------------------------------ Б
ALL_HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#include <string.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "@@DC@@"
enum { NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2, SCAN_STATE_SCANNING = 1 };
static const int MELODY_ERROR_BEEP[1];
struct { char dual_zone_all[8]; } lang = { "ALL" }, *currentLanguage = &lang;
static struct { int16_t NOT_IN_CODEPLUGDATA_indexNumber; uint16_t NOT_IN_CODEPLUGDATA_numChannelsInZone; uint16_t NOT_IN_CODEPLUGDATA_highestIndex; uint16_t channels[80]; } currentZone;
static struct { struct { int state; } Scan; } uiDataGlobal;
static struct { int16_t currentZone; } nonVolatileSettings;
static bool settingsSetBOOL(bool *p, bool v) { *p = v; return 1; }
static bool settingsSetINT8(int8_t *p, int8_t v) { *p = v; return 1; }
static bool settingsSetUINT8(uint8_t *p, uint8_t v) { *p = v; return 1; }
static bool settingsSetINT16(int16_t *p, int16_t v) { *p = v; return 1; }
static bool settingsSetUINT16(uint16_t *p, uint16_t v) { *p = v; return 1; }
static bool settingsSetINT32(int32_t *p, int32_t v) { *p = v; return 1; }
static bool settingsSetUINT32(uint32_t *p, uint32_t v) { *p = v; return 1; }
static uint8_t lastUsedChannelInZoneData[(1U + 68U) + 1];
static int lastUsedChannelInZoneHasChanged;
static unsigned char used[1100]; static int usedCount, usedHigh;
static int typeB, chB, onB, beeps, loadsA, notifs, zonesTotal = 6;
static uint32_t s_dualKeyMs;
static bool codeplugAllChannelsIndexIsInUse(int c) { return (c >= 1) && (c <= 1024) && used[c]; }
static int codeplugZonesGetCount(void) { return zonesTotal; }
static void setAll(void) { currentZone.NOT_IN_CODEPLUGDATA_indexNumber = -1; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = (uint16_t)usedCount; currentZone.NOT_IN_CODEPLUGDATA_highestIndex = (uint16_t)usedHigh; memset(currentZone.channels, 0, sizeof currentZone.channels); }
static void uiChannelInitializeCurrentZone(void) { if (nonVolatileSettings.currentZone == zonesTotal - 1) setAll(); }
static bool dcBIsVfo(void) { return typeB != 0; }
static uint16_t dcChannelB(void) { return (uint16_t)chB; }
static uint8_t dcTypeB(void) { return (uint8_t)typeB; }
static void dcSetTypeB(uint8_t t) { typeB = t; }
static bool dcSetChannelB(uint16_t c, bool now) { (void)now; typeB = 0; chB = c; return true; }
static bool dcIsOnB(void) { return onB; }
static void dcSetOnB(bool b) { onB = b; }
static uint8_t dualVfoIdx(void) { return (uint8_t)(typeB == 2); }
static bool dualIsRunning(void) { return false; }
static void dualAutoResume(void) { }
static void dualTune(bool b) { (void)b; }
static void dualSetDwell(void) { }
static void soundSetMelody(const int *m) { (void)m; beeps++; }
static void lastHeardClearLastID(void) { }
static void uiNotificationShow(int a, int b, uint32_t c, const char *m, bool d) { (void)a; (void)b; (void)c; (void)m; (void)d; notifs++; }
static void uiChannelModeLoadChannelData(bool a, bool b) { (void)a; (void)b; loadsA++; }
@@LUCZ@@
@@FNS@@
static int dualCount;
static void showB(void) { printf("%d,%d;", typeB, chB); }
int main(void)
{
	char cmd[8]; int a, b, n;
	while (scanf("%7s", cmd) == 1)
	{
		if (!strcmp(cmd, "USED")) { memset(used, 0, sizeof used); usedCount = 0; usedHigh = 0; scanf("%d", &n); for (int i = 0; i < n; i++) { scanf("%d", &a); used[a] = 1; usedCount++; if (a > usedHigh) usedHigh = a; } }
		else if (!strcmp(cmd, "ALL")) { nonVolatileSettings.currentZone = (int16_t)(zonesTotal - 1); setAll(); }
		else if (!strcmp(cmd, "ZONE")) { scanf("%d %d", &a, &n); nonVolatileSettings.currentZone = (int16_t)a; memset(&currentZone, 0, sizeof currentZone); currentZone.NOT_IN_CODEPLUGDATA_indexNumber = (int16_t)a; for (int i = 0; i < n; i++) { scanf("%d", &b); currentZone.channels[i] = (uint16_t)b; } currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = (uint16_t)n; currentZone.NOT_IN_CODEPLUGDATA_highestIndex = (uint16_t)n; }
		else if (!strcmp(cmd, "B")) { scanf("%d %d", &a, &b); typeB = a; chB = b; }
		else if (!strcmp(cmd, "STEP")) { scanf("%d", &a); dualStepB(a); showB(); }
		else if (!strcmp(cmd, "SETA")) { scanf("%d", &a); codeplugSetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber, (int16_t)a); }
		else if (!strcmp(cmd, "RAWLUCZ")) { scanf("%d %d", &a, &b); lastUsedChannelInZoneData[68] = (uint8_t)a; lastUsedChannelInZoneData[69] = (uint8_t)b; }
		else if (!strcmp(cmd, "GETA")) { printf("A=%d,get=%d;", dualChannelA(), codeplugGetLastUsedChannelInZone(currentZone.NOT_IN_CODEPLUGDATA_indexNumber)); }
		else if (!strcmp(cmd, "LEAVE")) { onB = 1; loadsA = 0; dualLeaveOnB(); printf("A=%d,onB=%d,zone=%d,idx=%d,loads=%d,notif=%d;", dualChannelA(), onB, nonVolatileSettings.currentZone, currentZone.NOT_IN_CODEPLUGDATA_indexNumber, loadsA, notifs); }
		else if (!strcmp(cmd, "NL")) { printf("\n"); }
	}
	return 0;
}
'''


def model_cycle(positions):
    """Еталон: замкнений цикл позицій (канали зони в порядку позицій, потім VFO A, VFO B)."""
    return [("c", c) for c in positions] + [("v", 1), ("v", 2)]


def ref_step(cycle, cur, d):
    if cur in cycle:
        i = cycle.index(cur)
    else:
        i = -1 if d > 0 else len(cycle)
    return cycle[(i + d) % len(cycle)]


def fmt(item):
    return "%d,%d;" % ((0, item[1]) if item[0] == "c" else (item[1], 0)) if item[0] == "c" else "%d,%d;" % (item[1], 0)


def test_part_b(incs, cf):
    if "DUALCH" not in cf:
        return
    t = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    cp = T.pp(FW, incs, cf["DUALCH"], "application/source/functions/codeplug.c")
    fns = [T.carve_fn(t or "", s) for s in ("static uint16_t dualZoneChannelAt(int pos, void *ctx)", "static uint16_t dualChannelA(void)", "static void dualStepB(int dir)", "static void dualLeaveOnB(void)")]
    lu = [T.carve_fn(cp or "", s) for s in ("int16_t codeplugGetLastUsedChannelInZone(int zoneNum)", "int16_t codeplugSetLastUsedChannelInZone(int zoneNum, int16_t channelNum)",
                                            "int16_t codeplugGetLastUsedChannelNumberInCurrentZone(void)")]
    check(all(fns) and all(lu), "Б: справжні функції знайдено (dualZoneChannelAt/dualChannelA/dualStepB/dualLeaveOnB, LUCZ get/set/number)")
    if not (all(fns) and all(lu)):
        return
    # порядок: LUCZ потрібен до dualChannelA
    code = ALL_HARNESS.replace("@@DC@@", os.path.join(FN, "dual_channel.c")).replace("@@LUCZ@@", "\n".join(lu))
    code = code.replace("@@FNS@@", "\n".join([fns[0], fns[1], fns[2], fns[3]]))
    # --- сценарії кроку B у «Всіх каналах» й у звичайній зоні (еталон -- замкнений цикл)
    random.seed(98)
    scen = []
    sets = [[1, 2, 5, 1024], [1], [1024], [1, 1024], [3, 4, 5, 6, 7], [10, 500, 1000], list(range(1, 30))]
    for _ in range(6):
        sets.append(sorted(random.sample(range(1, 1025), random.randint(2, 40))))
    stdin = []
    expect = []
    for used in sets:
        cyc = model_cycle(used)
        for d in (1, -1):
            for start in cyc:
                seq = ["USED %d %s" % (len(used), " ".join(map(str, used))), "ALL", "B %d %d" % ((0, start[1]) if start[0] == "c" else (start[1], 7)), "STEP %d" % d, "NL"]
                stdin.append("\n".join(seq))
                nxt = ref_step(cyc, start, d)
                prevB = (start[1] if start[0] == "c" else 7)
                expect.append("%d,%d;" % ((0, nxt[1]) if nxt[0] == "c" else (nxt[1], prevB)))
    out = run_in(code, "\n".join(stdin) + "\n")
    check(out is not None, "Б: хостова збірка моделі «Всі канали»")
    if out is None:
        return
    lines = [l for l in out.split("\n") if l != ""]
    bad = [(i, lines[i], expect[i]) for i in range(min(len(lines), len(expect))) if lines[i] != expect[i]]
    check(len(lines) == len(expect) and not bad, "Б1/Б2: «Всі канали» -- крок ручки на B (обидва напрямки, прогалини, межі 1 і 1024, обгортання, VFO A/B): %d сценаріїв, розбіжності: %r" % (len(expect), bad[:3]))
    # звичайна зона: канали зони в порядку позицій (не за зростанням)
    zone = [7, 3, 900, 12]
    cyc = model_cycle(zone)
    stdin = []; expect = []
    for d in (1, -1):
        for start in cyc:
            stdin.append("USED 4 7 3 900 12\nZONE 2 4 %s\nB %d %d\nSTEP %d\nNL" % (" ".join(map(str, zone)), (0 if start[0] == "c" else start[1]), (start[1] if start[0] == "c" else 7), d))
            nxt = ref_step(cyc, start, d)
            prevB = (start[1] if start[0] == "c" else 7)
            expect.append("%d,%d;" % ((0, nxt[1]) if nxt[0] == "c" else (nxt[1], prevB)))
    out = run_in(code, "\n".join(stdin) + "\n")
    lines = [l for l in (out or "").split("\n") if l != ""]
    check(lines == expect, "Б1: звичайна зона -- той самий цикл за порядком позицій у зоні: %r vs %r" % (lines[:4], expect[:4]))
    # B не з поточної зони -- крок від A (позиція A); порожня зона «Всі канали» (немає каналів) -- лише VFO
    out = run_in(code, "USED 3 5 6 9\nZONE 0 2 5 6\nSETA 1\nB 0 9\nSTEP 1\nNL\nSETA 0\nB 0 9\nSTEP -1\nNL\n")
    lines = [l for l in (out or "").split("\n") if l != ""]
    check(lines == ["1,9;", "2,9;"], "Б1: B не з поточної зони -- крок від позиції A: A=6 (остання в зоні з 2) вперед -> VFO A; A=5 (перша) назад -> VFO B: %r" % lines)
    # --- LUCZ «Всі канали»: нормальні значення
    out = run_in(code, "USED 4 1 2 5 1024\nALL\nSETA 5\nGETA\nSETA 1024\nGETA\nSETA 1\nGETA\nNL\nUSED 1 5\nALL\nRAWLUCZ 0 0\nGETA\nNL\nRAWLUCZ 255 255\nGETA\nNL\nRAWLUCZ 255 3\nGETA\nNL\nRAWLUCZ 255 7\nGETA\nNL\n")
    lines = [l for l in (out or "").split("\n") if l != ""]
    check(lines and lines[0] == "A=5,get=5;A=1024,get=1024;A=1,get=1;", "Б1: «Всі канали»: set/get last-used 5/1024/1 -> A = абсолютний номер (останнє зберігається як номер-1, читається +1): %r" % (lines[:1],))
    check(len(lines) >= 5 and lines[1] == "A=1,get=1;", "Б1: LUCZ нулі (немає даних) -> last-used 1, A = 1 (канал 1 може бути невикористаним -- стокова поведінка): %r" % (lines[1:2],))
    check(len(lines) >= 5 and lines[2] == "A=0,get=0;", "Б1: LUCZ 0xFFFF (недійсне) -> last-used 0, A = 0 (недопустимий номер: «Встановити як B»/авто B -> «B не задано»; ГІПОТЕЗА про симптом -- не доведена, див. звіт): %r" % (lines[2:3],))
    check(len(lines) >= 5 and lines[3] == "A=1024,get=1024;", "Б1: LUCZ 0x03FF -> 1024 -- верхня межа допустима: %r" % (lines[3:4],))
    check(len(lines) >= 5 and lines[4] == "A=2048,get=2048;", "Б1: LUCZ 0x07FF (поза діапазоном) -> A = 2048 (>1024): недопустимий номер, авто B/«B не задано» його відхиляє: %r" % (lines[4:5],))
    # --- dualLeaveOnB: «Всі канали» -> номер B як last-used; звичайна зона -> позиція; не з зони -> перехід на «Всі канали»
    out = run_in(code, "USED 4 5 6 9 300\nALL\nB 0 300\nLEAVE\nNL\nZONE 0 2 5 6\nB 0 6\nLEAVE\nNL\nZONE 0 2 5 6\nB 0 9\nLEAVE\nNL\n")
    lines = [l for l in (out or "").split("\n") if l != ""]
    check(lines[:1] == ["A=300,onB=0,zone=5,idx=-1,loads=1,notif=0;"], "Б1: вихід на B у «Всі канали» -- last-used = номер B (A=300), зона лишається «Всі канали»: %r" % (lines[:1],))
    check(lines[1:2] == ["A=6,onB=0,zone=0,idx=0,loads=1,notif=0;"], "Б1: вихід на B у звичайній зоні -- last-used = позиція B у зоні (A=6): %r" % (lines[1:2],))
    check(lines[2:3] == ["A=9,onB=0,zone=5,idx=-1,loads=1,notif=1;"], "Б1: B не з зони -- перехід на «Всі канали» з last-used = номер B, сповіщення: %r" % (lines[2:3],))
    # мутанти
    stdin = "USED 4 1 2 5 1024\nALL\nB 0 5\nSTEP 1\nNL\nUSED 4 5 6 9 300\nALL\nB 0 300\nLEAVE\nNL\n"
    base_out = run_in(code, stdin)
    for what, idx, mutated in (("«Всі канали»: позиція замість абсолютного номера у dualLeaveOnB", 3, fns[3].replace("(int16_t)(wasAll ? b : pos)", "(int16_t)pos")),
                               ("dualZoneChannelAt: без пропуску невикористаних", 0, fns[0].replace("codeplugAllChannelsIndexIsInUse(pos + 1) ? (uint16_t)(pos + 1) : 0U", "(uint16_t)(pos + 1)")),
                               ("dualStepB: n = кількість каналів замість найвищого номера", 2, fns[2].replace("currentZone.NOT_IN_CODEPLUGDATA_highestIndex", "currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone"))):
        check(mutated != fns[idx], "Б (мутант): %s -- зміна застосована" % what)
        mcode = ALL_HARNESS.replace("@@DC@@", os.path.join(FN, "dual_channel.c")).replace("@@LUCZ@@", "\n".join(lu)).replace("@@FNS@@", "\n".join([mutated if i == idx else f for i, f in enumerate(fns)]))
        m = run_in(mcode, stdin)
        check(m is not None and m != base_out, "Б (мутант): %s -- ловиться" % what)


# ------------------------------------------------------------------------------------------------ В
QSO_HARNESS = r'''
#include <stdio.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
enum { UI_CHANNEL_MODE = 3, UI_VFO_MODE = 4 };
static int menu = UI_CHANNEL_MODE, dwShown, stockDraws, dwDraws, avail = 1;
static int menuSystemGetCurrentMenuNumber(void) { return menu; }
static bool uiChannelModeDualScreenShown(void) { return dwShown; }
static void uiChannelModeUpdateScreen(int t) { (void)t; dwDraws++; }
static bool isQSODataAvailableForCurrentTalker(void) { return avail; }
static void displayClearBuf(void) { stockDraws++; }
static void uiUtilityRenderHeader(bool a, bool b, bool c) { (void)a; (void)b; (void)c; stockDraws++; }
static void uiUtilityRenderQSOData(void) { stockDraws++; }
static void displayRender(void) { stockDraws++; }
@@FN@@
int main(void)
{
	dwShown = 1; menu = UI_CHANNEL_MODE; uiUtilityRenderQSODataAndUpdateScreen(); printf("a=%d,%d\n", stockDraws, dwDraws);
	stockDraws = dwDraws = 0; dwShown = 0; uiUtilityRenderQSODataAndUpdateScreen(); printf("b=%d,%d\n", stockDraws > 0, dwDraws);
	stockDraws = dwDraws = 0; dwShown = 1; menu = UI_VFO_MODE; uiUtilityRenderQSODataAndUpdateScreen(); printf("c=%d,%d\n", stockDraws > 0, dwDraws);
	return 0;
}
'''

STOP_HARNESS = r'''
#include <stdio.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#include <stdint.h>
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1, AUDIO_PROMPT_MODE_VOICE_THRESHOLD = 2, ROAMING_OFF = 0, ROAMING_5KM = 3 };
static struct { struct { int active; } Scan; int displayQSOState; uint32_t lastDistanceMillis; double lastDistanceSortLocationLat, lastDistanceSortLocationLon; } uiDataGlobal;
static struct { int audioPromptMode; } nonVolatileSettings;
static struct { int16_t NOT_IN_CODEPLUGDATA_indexNumber; } currentZone;
static int running, enabled, onB, suspends, loadMem = -1, loadVp = -1, loads;
static bool dualIsRunning(void) { return running; }
static void dualSuspend(void) { suspends++; }
static bool dcIsEnabled(void) { return enabled; }
static bool dcIsOnB(void) { return onB; }
static void uiChannelModeLoadChannelData(bool m, bool v) { loadMem = m; loadVp = v; loads++; }
static bool settingsLocationIsValid(void) { return 0; }
static uint32_t ticksGetMillis(void) { return 0; }
static double settingsLocationGetLatitude(void) { return 0; }
static double settingsLocationGetLongitude(void) { return 0; }
@@FN@@
static void go(const char *n, int r, int e, int b, int vp)
{
	running = r; enabled = e; onB = b; nonVolatileSettings.audioPromptMode = vp ? 5 : 0; loadMem = loadVp = -1; loads = suspends = 0; uiDataGlobal.Scan.active = 1;
	uiChannelModeStopScanning();
	printf("%s=loads%d,mem%d,vp%d,susp%d,scan%d\n", n, loads, loadMem, loadVp, suspends, uiDataGlobal.Scan.active);
}
int main(void)
{
	go("s1", 0, 0, 0, 1);   /* режиму нема: стоково -- канал з «останнього каналу зони» (useChannelDataInMemory = 0) */
	go("s2", 0, 1, 0, 1);   /* режим, рація на A: як стоково */
	go("s3", 0, 1, 1, 1);   /* режим, зупинено на обраному B (канал або VFO): перезавантажуємо В ПАМ'ЯТІ -- без стрибка на A */
	go("s4", 1, 1, 0, 1);   /* чергування йде: dualSuspend, нічого не перезавантажуємо тут */
	go("s5", 0, 1, 1, 0);   /* без голосових підказок -- без перезавантаження взагалі */
	return 0;
}
'''

DETAILS_HARNESS = r'''
#include <stdio.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
enum { UI_CHANNEL_MODE = 3, UI_VFO_MODE = 4 };
static int menu = UI_CHANNEL_MODE, enabled, details;
static struct { int displayChannelSettings; } uiDataGlobal;
static bool dcIsEnabled(void) { return enabled; }
static int menuSystemGetCurrentMenuNumber(void) { return menu; }
@@FN@@
int main(void)
{
	for (int e = 0; e < 2; e++) for (int d = 0; d < 2; d++) for (int m = 0; m < 2; m++) { enabled = e; uiDataGlobal.displayChannelSettings = d; menu = m ? UI_CHANNEL_MODE : UI_VFO_MODE; printf("%d", (int)uiChannelModeDualDetailsShown()); }
	printf("\n");
	return 0;
}
'''


def test_part_v(incs, cf):
    uu = T.rd(os.path.join(UI, "uiUtilities.c"))
    i = uu.find("void uiUtilityRenderQSODataAndUpdateScreen(void)")
    body = uu[i:uu.find("\n}\n", i)]
    check(i > 0 and "uiChannelModeDualScreenShown()" in body and body.find("uiChannelModeUpdateScreen(0);") < body.find("displayClearBuf();"),
          "В1: таймер QSO -- у режимі лише екран режиму, стокова шапка/дані QSO не малюються (до displayClearBuf)")
    j = uu.find("void uiUtilityDrawRSSIBarGraph(void)")
    check("uiChannelModeDualDetailsShown()" in uu[j:j + 600], "В2: стоковий S-метр шапки не малюється в панелі деталей SK1 при ввімкненому режимі")
    if "DUALCH" not in cf:
        check(False, "конфігурація DUALCH є"); return
    tu = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiUtilities.c")
    fn = T.carve_fn(tu or "", "void uiUtilityRenderQSODataAndUpdateScreen(void)")
    check(fn is not None, "В1: функція таймера знайдена")
    if fn is not None:
        out = run_in(QSO_HARNESS.replace("@@FN@@", fn))
        o = kv(out)
        check(o.get("a") == "0,1", "В1: екран режиму показано -> стокового малювання нема, один виклик екрана режиму: %s" % o.get("a"))
        check(o.get("b") == "1,0", "В1: режиму нема на екрані -> стокове малювання як було: %s" % o.get("b"))
        check(o.get("c") == "1,0", "В1: не екран каналу -> стокове: %s" % o.get("c"))
        mut = re.sub(r"if \(\(menuSystemGetCurrentMenuNumber\(\) == UI_CHANNEL_MODE\) && uiChannelModeDualScreenShown\(\)\)\s*\{[^}]*\}", "", fn, count=1, flags=re.S)
        mo = run_in(QSO_HARNESS.replace("@@FN@@", mut)) if mut != fn else None
        check(mut != fn and mo is not None and mo != out, "В1 (мутант): без перенаправлення таймер малює стоковий екран у режимі -- ловиться")
    # деталі SK1
    tc = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    fn = T.carve_fn(tc or "", "_Bool uiChannelModeDualDetailsShown(void)")
    check(fn is not None, "В2: предикат панелі деталей знайдено")
    if fn is not None:
        out = run_in(DETAILS_HARNESS.replace("@@FN@@", fn))
        check((out or "").strip() == "00000001", "В2: предикат істинний лише коли режим ввімкнено, панель деталей показано й екран каналу (мапа e,d,m): %r" % (out or "").strip())
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    uses = [m.start() for m in re.finditer(r"uiChannelModeDualDetailsShown\(", src)]
    check(len(uses) == 1, "В2: предикат деталей не використовується у стоковому тіку екрана каналу (лише визначення) -- смуга режиму не малюється поверх панелі")
    # В3
    fn = T.carve_fn(tc or "", "void uiChannelModeStopScanning(void)")
    check(fn is not None, "В3: uiChannelModeStopScanning знайдено")
    if fn is not None:
        out = run_in(STOP_HARNESS.replace("@@FN@@", fn))
        o = kv(out)
        check(o.get("s1") == "loads1,mem0,vp1,susp0,scan0", "В3: режиму нема -- стоково (канал з «останнього каналу зони»): %s" % o.get("s1"))
        check(o.get("s2") == "loads1,mem0,vp1,susp0,scan0", "В3: режим, рація на A -- як стоково: %s" % o.get("s2"))
        check(o.get("s3") == "loads1,mem1,vp1,susp0,scan0", "В3: режим, рація на ОБРАНОМУ B (канал або VFO) -- перезавантаження з пам'яті (ранні гілки B/VFO), без стрибка на A: %s" % o.get("s3"))
        check(o.get("s4") == "loads0,mem-1,vp-1,susp1,scan1", "В3: чергування йде -- dualSuspend як було: %s" % o.get("s4"))
        check(o.get("s5") == "loads0,mem-1,vp-1,susp0,scan0", "В3: без голосових підказок перезавантаження нема: %s" % o.get("s5"))
        mut = fn.replace("if (dcIsEnabled() && dcIsOnB())", "if (0)")
        mo = run_in(STOP_HARNESS.replace("@@FN@@", mut)) if mut != fn else None
        check(mut != fn and mo is not None and mo != out, "В3 (мутант): без гілки обраного B -- стрибок на A ловиться")
    check(("useChannelDataInMemory && dcIsOnB() && dcBIsVfo()" in src or "useChannelDataInMemory && dualOnVfoNow()" in src) and "useChannelDataInMemory && dcIsOnB())" in src,   # R98-FIX4: гілка VFO -- для A теж
          "В3: uiChannelModeLoadChannelData із пам'яті зберігає обраний B: гілка VFO (uiVFOModeDualLoad) і гілка каналу B")


# ------------------------------------------------------------------------------------------------ Г
BUCKET_HARNESS = r'''
#include <stdio.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#include <stdint.h>
enum { CHANNEL_VFO_A = 0, CHANNEL_VFO_B, CHANNEL_CHANNEL };
static int en, onB, vfo, typeB;
static bool dcIsEnabled(void) { return en; }
static bool dcIsOnB(void) { return onB; }
static bool dcBIsVfo(void) { return vfo; }
static uint8_t dcTypeB(void) { return (uint8_t)typeB; }
static uint8_t dualVfoIdx(void) { return (uint8_t)(typeB == 2); }
@@FN@@
static int recorded = -1;
static void tsSetManualOverride(int bucket, int ts) { recorded = bucket; (void)ts; }
static void applyContactTs(void) { tsSetManualOverride(uiChannelModeDualTsBucket(), 2); }   /* як overrideWithSelectedContact()/«Останні» з кореня екрана каналу */
int main(void)
{
	en = 1; onB = 1; vfo = 1; typeB = 2; applyContactTs(); printf("a=%d\n", recorded);   /* VFO B */
	typeB = 1; applyContactTs(); printf("b=%d\n", recorded);                                 /* VFO A */
	vfo = 0; typeB = 0; applyContactTs(); printf("c=%d\n", recorded);                         /* B = канал */
	vfo = 1; typeB = 2; onB = 0; applyContactTs(); printf("d=%d\n", recorded);                /* рація на A */
	onB = 1; en = 0; applyContactTs(); printf("e=%d\n", recorded);                            /* режим вимкнено */
	return 0;
}
'''


def test_part_g(incs, cf):
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    qk = src[src.find("quickKeyApply: // branching here when to quickkey was used."):]
    qk = qk[:qk.find("switch(menuDataGlobal.currentItemIndex)\n\t\t\t{\n\t\t\t\tcase CH_SCREEN_QUICK_MENU_COPY2VFO:")]
    for item in ("COPY2VFO", "COPY_FROM_VFO", "TALKAROUND", "ROAMING", "DELETE", "ZONE_REMOVE"):
        check("case CH_SCREEN_QUICK_MENU_%s:" % item in qk, "Г1: пункт швидкого меню «%s» на обраному VFO -- сигнал помилки, меню лишається" % item)
    for item in ("FILTER_FM", "FILTER_DMR", "DMR_CC_SCAN", "FILTER_DMR_TS", "AUDIO_MUTE", "DUAL_CHANNEL"):
        check("case CH_SCREEN_QUICK_MENU_%s:" % item not in qk, "Г1: безпечний пункт «%s» не блокується" % item)
    # застосування ROAMING стирає currentChannelData->rxFreq -- підстава блокування
    check("currentChannelData->rxFreq = 0U; // force reload of zone" in src, "Г1: підстава -- застосування ROAMING ставить currentChannelData->rxFreq = 0 (на VFO стерло б частоту VFO)")
    cl = T.rd(os.path.join(UI, "menuContactList.c")); lh = T.rd(os.path.join(UI, "menuLastHeard.c"))
    check("CHANNEL_ROOT_TS_BUCKET()" in cl and "CHANNEL_ROOT_TS_BUCKET()" in lh and "? CHANNEL_CHANNEL :" not in cl and "? CHANNEL_CHANNEL :" not in lh,
          "Г1: меню контактів і «Останні» -- ТС-перекриття в відро ОБРАНОГО VFO (не в канальне)")
    hdr = T.rd(os.path.join(INC, "user_interface", "menuSystem.h"))
    check(re.search(r"#else\s*\n#define CHANNEL_ROOT_TS_BUCKET\(\) CHANNEL_CHANNEL", hdr) is not None, "Г1: без режиму макрос = стоковий CHANNEL_CHANNEL (збірка без прапорця не змінюється)")
    cd = T.rd(os.path.join(UI, "menuChannelDetails.c"))
    check("if (uiChannelModeDualOnVfo())" in cd and "rootMenuIsVFO = true;" in cd[cd.find("uiChannelModeDualOnVfo"):cd.find("uiChannelModeDualOnVfo") + 120],
          "Г1: деталі каналу на обраному VFO -- як у VFO-екрані (без канальних пунктів, VFO позначається брудним, без «перечитати зону»)")
    ri = T.rd(os.path.join(UI, "menuRadioInfos.c"))
    check("uiChannelModeDualOnVfo() == false" in ri, "Г1: «Інфо» -> задати місце: на обраному VFO не стираємо rxFreq («перечитати зону»)")
    if "DUALCH" not in cf:
        return
    tc = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    f1 = T.carve_fn(tc or "", "int uiChannelModeDualTsBucket(void)")
    f2 = T.carve_fn(tc or "", "_Bool uiChannelModeDualOnVfo(void)")
    check(f1 is not None and f2 is not None, "Г2: функції відра/ознаки VFO знайдено")
    if f1 is None or f2 is None:
        return
    fn = f2 + "\n" + f1
    out = run_in(BUCKET_HARNESS.replace("@@FN@@", fn))
    o = kv(out)
    check(o.get("a") == "1" and o.get("b") == "0", "Г2: ТС-перекриття на обраному VFO B/VFO A іде у відро VFO B (1) / VFO A (0), НЕ в канальне (2): %s %s" % (o.get("a"), o.get("b")))
    check(o.get("c") == "2" and o.get("d") == "2" and o.get("e") == "2", "Г2: B = канал / рація на A / режим вимкнено -- канальне відро, як у R97: %s %s %s" % (o.get("c"), o.get("d"), o.get("e")))
    mut = fn.replace("(int)(CHANNEL_VFO_A + ((dcIsOnB()) ? dualVfoIdx() : 0))", "(int)CHANNEL_CHANNEL").replace("(int)(CHANNEL_VFO_A + dualVfoIdx())", "(int)CHANNEL_CHANNEL")
    mo = run_in(BUCKET_HARNESS.replace("@@FN@@", mut)) if mut != fn else None
    check(mut != fn and mo is not None and mo != out, "Г2 (мутант): перекриття знову в канальне відро -- ловиться")


# Частину Д (лічильники на картках, хук прийому) замінено в R98-FIX2 (біт 31 peerId): див. tools/test_r98fix2.py та tests/test_dmr_sms_peerb.c


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    test_part_a(incs, cf)
    test_part_b(incs, cf)
    test_part_v(incs, cf)
    test_part_g(incs, cf)
    print("test_r98fix1: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
