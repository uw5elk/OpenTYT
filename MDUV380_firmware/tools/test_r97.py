#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R97 (хост): «Подвійний прийом» по каналах кодплага (ENABLE_DUAL_CHANNEL).
  1  блок 18 (dual_channel.c, хостова компіляція з -DDUAL_CHANNEL_HOST_TEST): розбір/збирання, версія, межі номера B, перевірка пари,
     вибір каналу для PTT (dcTxOnB), крок по каналах зони для валкодера (dcStepPos/dcFindPos);
  2  рушій: dualScanning() і uiChannelModeDualPrepareTx() вирізано зі справжнього тексту uiChannelMode.c (gcc -E, конфігурація DUALCH) і прогнано
     хостовим gcc: чергування A<->B, утримання «Затр. скан.» (HOLD), відновлення чергування, вибір каналу PTT за станом; «Тип скану» не читається;
  3  звичайне сканування не змінилось: scanning() (без вставки R97), scanStart, scanSearchForNextChannel, scanApplyNextChannel, scanStop,
     uiChannelModeStopScanning (без вставки) -- токени як у базі (R97_BASE);
  4  збірки без прапорця: токени ВСІХ application/source/**/*.c для AES0 (без дефайнів), ENDATA (англійська) і UA -- як у базі;
     прапорець в англійській збірці (DUALCHEN) -- мертвий;
  5  мовні поля: в ukrainian.h/english.h/uiLanguage.h, останні, під ENABLE_DUAL_CHANNEL, ширина;
  7  R97-FIX: у швидкому меню пункт читається ДО menuSystemPopPreviousMenu() (статично + мутант), dualQuickMenuApply() хостово (setB -> dcSetChannelB(dualChannelA()), інакше On/Off);
  8  R97-FIX2: шапка за станом (dualRenderScreen хостово + мутант), гаряча клавіша -- довге ▼ (dualSetMode/dualHotkeyToggle хостово, статично: без автоповтору, SK2/SK1, набір номера), вибір A/B у «Всіх каналах» (-1) на справжніх codeplug*LastUsed*;
  6  CPS не ламає невідомий блок 18: розбір області, ущільнення, файл налаштувань, план відновлення (custom_region.py, custom_compact.py).
Порівняння з комітом бази стійке до його відсутності: без коміта -- ПРОПУСК з повідомленням.
Запуск: python3 tools/test_r97.py"""
import os, re, shutil, struct, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); FW = os.path.dirname(HERE); sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa
APP = os.path.join(FW, "application"); LANG = os.path.join(APP, "include", "user_interface", "languages")
BASE = os.environ.get("R97_BASE", "7fa5fe8")
FAILS = []; N = [0]
DUAL_FIELDS = ["dual_rx", "dual_set_b", "dual_title", "dual_b_saved", "dual_err_no_b", "dual_err_b_gone", "dual_err_b_is_a", "dual_on", "dual_off", "dual_zone_all"]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


def rd(p, enc="utf-8"): return open(p, "rb").read().decode(enc)


def pp(root, incs, defs, rel):
    for _attempt in range(2):   # один повтор: поодинокий збій запуску gcc не має давати хибну «різницю токенів»
        r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=root, capture_output=True)
        if r.returncode == 0:
            return r.stdout.decode("cp1251", "replace")
    return None


def carve_fn(text, sig):
    """Функція від сигнатури sig до парної закривальної дужки (лічба { })."""
    i = -1
    for m in re.finditer(re.escape(sig), text):
        if text[m.end():].lstrip().startswith("{"):   # визначення, а не оголошення «...;»
            i = m.start(); break
    if i < 0:
        return None
    j = text.index("{", i); depth = 0
    for k in range(j, len(text)):
        if text[k] == "{": depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return text[i:k + 1]
    return None


def run_c(code, extra=()):
    d = tempfile.mkdtemp(prefix="r97_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-I", os.path.join(APP, "include")] + list(extra) + ["-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:1500]); return None
        return subprocess.run([os.path.join(d, "h")], capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ 1
def test_block18():
    code = r'''
#include <stdio.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "%s"
static uint16_t zone[] = {5, 0, 7, 9, 12};
static uint16_t at(int pos, void *ctx) { (void)ctx; return zone[pos]; }
int main(void)
{
	dcOnFlashCfg_t r; bool e, p; uint16_t ch;
	printf("size=%%u\n", (unsigned)sizeof(r));
	dcCfgBuild(&r, true, true, 300); printf("b1=%%d,%%d,%%d,%%d,%%d,%%d\n", r.version, r.flags, r.chBLo, r.chBHi, r.reserved[0], r.reserved[3]);
	{ int ok = dcCfgParse(&r, &e, &p, &ch); printf("p1=%%d,%%d,%%d,%%u\n", ok, e, p, ch); }
	dcCfgBuild(&r, false, false, 1025); { int ok = dcCfgParse(&r, &e, &p, &ch); printf("p2=%%d,%%d,%%d,%%u\n", ok, e, p, ch); }
	r.version = 2; { int ok = dcCfgParse(&r, &e, &p, &ch); printf("p3=%%d,%%d,%%d,%%u\n", ok, e, p, ch); }
	memset(&r, 0xFF, sizeof(r)); { int ok = dcCfgParse(&r, &e, &p, &ch); printf("p4=%%d,%%d,%%d,%%u\n", ok, e, p, ch); }
	r.version = 1; r.flags = 3; r.chBLo = 0x00; r.chBHi = 0x04; { int ok = dcCfgParse(&r, &e, &p, &ch); printf("p5=%%d,%%d,%%d,%%u\n", ok, e, p, ch); }
	printf("c=%%d,%%d,%%d,%%d,%%d\n", dcCheckPair(10, 0, false), dcCheckPair(10, 20, false), dcCheckPair(10, 10, true), dcCheckPair(10, 20, true), dcCheckPair(10, 2000, true));
	printf("tx=%%d%%d%%d%%d%%d%%d%%d%%d\n", dcTxOnB(0,0,0), dcTxOnB(0,0,1), dcTxOnB(0,1,0), dcTxOnB(0,1,1), dcTxOnB(1,0,0), dcTxOnB(1,0,1), dcTxOnB(1,1,0), dcTxOnB(1,1,1));
	printf("s=%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", dcStepPos(5, 0, 1, 9, at, NULL), dcStepPos(5, 2, 1, 9, at, NULL), dcStepPos(5, 4, 1, 9, at, NULL),
			dcStepPos(5, 0, -1, 9, at, NULL), dcStepPos(5, -1, 1, 0, at, NULL), dcStepPos(5, -1, -1, 0, at, NULL), dcStepPos(0, 0, 1, 0, at, NULL));
	static uint16_t one[] = {9}; zone[0] = 0;
	printf("f=%%d,%%d,%%d\n", dcFindPos(5, 12, at, NULL), dcFindPos(5, 99, at, NULL), dcFindPos(5, 0, at, NULL));
	(void)one;
	{ uint16_t z2[] = {9, 9}; (void)z2; }
	zone[0] = 9; zone[1] = 9; zone[2] = 9; zone[3] = 9; zone[4] = 9;
	printf("n=%%d\n", dcStepPos(5, 0, 1, 9, at, NULL));
	return 0;
}
''' % os.path.join(APP, "source", "functions", "dual_channel.c")
    out = run_c(code)
    check(out is not None, "блок 18: хостова збірка dual_channel.c")
    if out is None:
        return
    o = dict(l.split("=", 1) for l in out.split())
    check(o["size"] == "8", "блок 18: 8 байт (є %s)" % o["size"])
    check(o["b1"] == "1,3,44,1,0,0", "блок 18: збирання (версія 1, біти 0/1, 300 = 0x012C LE, резерв 0): %s" % o["b1"])
    check(o["p1"] == "1,1,1,300", "блок 18: розбір назад: %s" % o["p1"])
    check(o["p2"] == "1,0,0,0", "блок 18: номер B поза 1..1024 -> 0 «не задано»: %s" % o["p2"])
    check(o["p3"] == "0,0,0,0" and o["p4"] == "0,0,0,0", "блок 18: невідома версія / стерта флеш (0xFF) -> вимкнено, A, B не задано: %s %s" % (o["p3"], o["p4"]))
    check(o["p5"] == "1,1,1,1024", "блок 18: межа 1024: %s" % o["p5"])
    check(o["c"] == "1,2,3,0,1", "перевірка пари: нема B / B видалено / B==A / OK / поза межами: %s" % o["c"])
    check(o["tx"] == "01010011", "PTT: без активності -- покажчик; прийом/утримання -- де рація зараз: %s" % o["tx"])
    check(o["s"] == "2,4,0,4,0,4,-1", "валкодер: крок з пропуском порожньої позиції й A, по колу, назад, від краю, порожня зона: %s" % o["s"])
    check(o["f"] == "4,-1,-1", "валкодер: пошук позиції B: %s" % o["f"])
    check(o["n"] == "-1", "валкодер: у зоні лише A -- кроку нема: %s" % o["n"])


# ------------------------------------------------------------------------------------------------ 2
HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "%(dc)s"
enum { SCAN_STATE_SCANNING = 0, SCAN_STATE_SHORT_PAUSED, SCAN_STATE_PAUSED };
enum { SCAN_TYPE_NORMAL_STEP = 0, SCAN_TYPE_DUAL_WATCH, SCAN_TYPE_DUAL_CHANNEL };
enum { RADIO_MODE_NONE, RADIO_MODE_ANALOG, RADIO_MODE_DIGITAL };
enum { DMR_STATE_IDLE = 0, DMR_STATE_RX_1 = 1 };
enum { DMR_MODE_AUTO = 0, DMR_MODE_DMO, DMR_MODE_RMO };
enum { RADIO_DEVICE_PRIMARY = 0 };
enum { AUDIO_AMP_CHANNEL_RF = (1 << 1) };
enum { QSO_DISPLAY_IDLE = 0, QSO_DISPLAY_DEFAULT_SCREEN = 1 };
enum { UI_CHANNEL_MODE = 7, UI_VFO_MODE = 8 };
struct { struct { bool active; int scanType; int state; struct { int timeout; } timer; int dwellTime; int stepTimeMilliseconds; } Scan; int displayQSOState; } uiDataGlobal;
struct { int dmrCcTsFilter; int scanDelay; } nonVolatileSettings;
struct { int trxDMRModeRx; } dev, *currentRadioDevice = &dev;
int slotState = 0, dmrMonitorCapturedTS = -1;
static int mode = RADIO_MODE_ANALOG, carrier = 0, sync = 0, rf = 0, menu = UI_CHANNEL_MODE, onB = 0, ptrB = 0, txHold = 0, tunes = 0, hdr = 0;
int trxGetMode(void) { return mode; }
int trxGetDMRTimeSlot(void) { return 0; }
bool HRC6000HasGotSync(void) { return sync; }
bool trxCarrierDetected(int d) { (void)d; return carrier; }
uint32_t audioAmpGetStatus(void) { return rf ? 0xFFFFu : 0u; }
void hidesChannelDetails(void) {}
bool dcIsOnB(void) { return onB; }
bool dcPointerB(void) { return ptrB; }
void dcSetTxHold(bool h) { txHold = h; }
int menuSystemGetCurrentMenuNumber(void) { return menu; }
void uiUtilityRedrawHeaderOnly(bool a, bool b, bool c) { (void)a; (void)b; (void)c; hdr++; }
static void dualTune(bool toB) { onB = toB; tunes++; }
static void dualSetDwell(void) { uiDataGlobal.Scan.dwellTime = 40; uiDataGlobal.Scan.timer.timeout = 40; }
%(fns)s
static void ticks(int n) { for (int i = 0; i < n; i++) { if (uiDataGlobal.Scan.active) dualScanning(); } }
static void reset(void) { uiDataGlobal.Scan.active = true; uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL; uiDataGlobal.Scan.state = SCAN_STATE_SCANNING;
	uiDataGlobal.Scan.stepTimeMilliseconds = 30; dualSetDwell(); onB = 0; tunes = 0; hdr = 0; carrier = sync = rf = 0; mode = RADIO_MODE_ANALOG; nonVolatileSettings.scanDelay = 2; }
int main(void)
{
	// а) FM без сигналу: по черзі A/B кожні dwell+1 тіків, імена не перемальовуються (лише шапка)
	reset(); ticks(41 * 6); printf("alt=%%d,%%d,%%d\n", tunes, onB, hdr);
	// б) несуча на B: коротка пауза, звук -> утримання scanDelay*1000, поки є звук, рація на B
	reset(); ticks(41); carrier = 1; ticks(5); int st1 = uiDataGlobal.Scan.state; rf = 1; ticks(3); int st2 = uiDataGlobal.Scan.state, to = uiDataGlobal.Scan.timer.timeout;
	ticks(5000); int stay = (onB == 1) && (tunes == 1);
	carrier = 0; rf = 0; ticks(1990); int still = (onB == 1); uiDataGlobal.displayQSOState = QSO_DISPLAY_IDLE; ticks(20); int dq0 = uiDataGlobal.displayQSOState; printf("hold=%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", st1, st2, to, stay, still, onB, uiDataGlobal.Scan.state); printf("holdscr=%%d,%%d\n", dq0 == QSO_DISPLAY_DEFAULT_SCREEN, hdr);
	// в) DMR slow: синхронізація -> пауза (1 надкадр + 1 TS) * 4
	reset(); mode = RADIO_MODE_DIGITAL; uiDataGlobal.Scan.stepTimeMilliseconds = 200; ticks(10); sync = 1; ticks(1); printf("dmr=%%d,%%d\n", uiDataGlobal.Scan.state, uiDataGlobal.Scan.timer.timeout);
	// г) PTT: без активності -- покажчик; під час утримання -- де рація; не той екран / не працює -- false
	reset(); ptrB = 1; int r1 = uiChannelModeDualPrepareTx(); printf("ptt1=%%d,%%d,%%d,%%d\n", r1, onB, txHold, uiDataGlobal.Scan.active);
	reset(); onB = 1; ptrB = 0; uiDataGlobal.Scan.state = SCAN_STATE_PAUSED; int r2 = uiChannelModeDualPrepareTx(); printf("ptt2=%%d,%%d,%%d\n", r2, onB, tunes);
	reset(); ptrB = 0; onB = 1; int r3 = uiChannelModeDualPrepareTx(); printf("ptt3=%%d,%%d\n", r3, onB);
	reset(); menu = UI_VFO_MODE; txHold = 0; int r4 = uiChannelModeDualPrepareTx(); menu = UI_CHANNEL_MODE;
	reset(); uiDataGlobal.Scan.scanType = SCAN_TYPE_NORMAL_STEP; int r5 = uiChannelModeDualPrepareTx(); printf("ptt4=%%d,%%d,%%d\n", r4, r5, txHold);
	return 0;
}
'''


def test_engine(incs, cf):
    if "DUALCH" not in cf:
        check(False, "конфігурація DUALCH є в syntax_check.sh"); return
    t = pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    check(t is not None, "uiChannelMode.c препроцесується в DUALCH")
    if t is None:
        return
    fns = [carve_fn(t, s) for s in ("static _Bool dualIsRunning(void)", "static void dualScanning(void)", "_Bool uiChannelModeDualPrepareTx(void)")]
    check(all(fns), "знайдено dualIsRunning / dualScanning / uiChannelModeDualPrepareTx")
    if not all(fns):
        return
    check("scanModePause" not in fns[1], "рушій режиму не читає «Тип скану» (утримання завжди HOLD, STOP/PAUSE режим не вимикають)")
    check("codeplugSetLastUsedChannelInZone" not in t[t.find("static void dualTune(_Bool toB)"):t.find("static uint16_t dualChannelA(void)")],
          "dualTune() не пише «останній канал зони»")
    out = run_c(HARNESS % {"dc": os.path.join(APP, "source", "functions", "dual_channel.c"), "fns": "\n".join(fns)})
    check(out is not None, "хостова збірка рушія")
    if out is None:
        return
    o = dict(l.split("=", 1) for l in out.split())
    check(o.get("alt") == "6,0,0", "чергування A<->B: 6 перемикань за 6 витримок; R97-FIX2: шапка при перемиканні НЕ перемальовується (статична «[DW]»): %s" % o.get("alt"))
    check(o.get("hold") == "1,2,1999,1,1,0,0", "утримання: SHORT_PAUSED -> PAUSED (scanDelay*1000, мінус поточний тік), поки є звук -- на B; після -- поновлення на A: %s" % o.get("hold"))
    check(o.get("holdscr") == "1,0", "R97-FIX2: перехід із виклику/утримання в чергування -- повне перемальовування екрана (QSO_DISPLAY_DEFAULT_SCREEN), шапка окремо не малюється: %s" % o.get("holdscr"))
    check(o.get("dmr") == "1,1559", "DMR slow: синхронізація -> пауза ((TIMESLOT*12)+TIMESLOT)*4 мінус поточний тік: %s" % o.get("dmr"))
    check(o.get("ptt1") == "1,1,1,0", "PTT без активності, покажчик на B: рація на B, утримання після TX, Scan.active знято: %s" % o.get("ptt1"))
    check(o.get("ptt2") == "1,1,0", "PTT під час утримання на B при покажчику на A: передача на B (без перелаштування): %s" % o.get("ptt2"))
    check(o.get("ptt3") == "1,0", "PTT без активності, покажчик на A, рація на B: перелаштування на A: %s" % o.get("ptt3"))
    check(o.get("ptt4") == "0,0,0", "PTT не з екрана каналу / не в режимі -- стоковий шлях: %s" % o.get("ptt4"))


# ------------------------------------------------------------------------------------------------ 3, 4
SCAN_FNS = ["static void scanning(void)", "static void scanStart(_Bool longPressBeep)", "static void scanSearchForNextChannel(void)",
            "static void scanApplyNextChannel(void)", "static void scanStop(_Bool loadChannel)", "void uiChannelModeStopScanning(void)"]


def strip_dual(fn):
    fn = re.sub(r"if \(uiDataGlobal\.Scan\.scanType == SCAN_TYPE_DUAL_CHANNEL\)\s*\{\s*dualScanning\(\);\s*return;\s*\}", "", fn)
    fn = re.sub(r"if \(dualIsRunning\(\)\)\s*\{\s*dualSuspend\(\);\s*return;\s*\}", "", fn)
    return fn.split()


def test_vs_base(incs, cfgs):
    cf = dict(cfgs)
    if subprocess.run(["git", "-C", FW, "cat-file", "-e", BASE + "^{commit}"], capture_output=True).returncode != 0:
        print("ПРОПУСК: база недоступна (CI/клон без історії): порівняння звичайного сканування й збірок без прапорця з %s не виконано" % BASE)
        return
    root = tempfile.mkdtemp(prefix="r97_base_")
    try:
        tar = subprocess.run(["git", "-C", FW, "archive", BASE, "application"], capture_output=True)
        subprocess.run(["tar", "-x", "-C", root], input=tar.stdout, check=True)
        for e in os.listdir(FW):
            if e != "application" and not os.path.exists(os.path.join(root, e)):
                os.symlink(os.path.join(FW, e), os.path.join(root, e))
        # 3: звичайне сканування в конфігурації з прапорцем
        a = pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
        b = pp(root, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
        for s in SCAN_FNS:
            fa, fb = carve_fn(a or "", s), carve_fn(b or "", s)
            check(fa is not None and fb is not None and strip_dual(fa) == fb.split(), "звичайне сканування не змінилось (DUALCH, крім вставки R97): %s" % s.split("(")[0])
        # 4: усі .c без прапорця
        empty = os.path.join(root, "r97_empty.c"); open(empty, "w").write("\n")   # новий файл у базі відсутній: без прапорця він має давати порожню одиницю трансляції
        files = sorted(os.path.relpath(os.path.join(d, f), FW) for d, _s, fs in os.walk(os.path.join(APP, "source")) for f in fs if f.endswith(".c"))
        for name in ("AES0", "ENDATA", "UA"):
            bad = []
            for rel in files:
                ta, tb = pp(FW, incs, cf[name], rel), pp(root, incs, cf[name], (rel if os.path.exists(os.path.join(root, rel)) else empty))
                if (ta or "").split() != (tb or "").split():
                    bad.append(rel)
            check(bad == [], "%s: токени всіх %d файлів .c як у базі %s (без прапорця R97 нічого не змінилось): %r" % (name, len(files), BASE, bad[:5]))
        # DUALCHEN: прапорець в англійській збірці мертвий
        bad = []
        for rel in ("application/source/user_interface/uiChannelMode.c", "application/source/applicationMain.c", "application/source/functions/dual_channel.c",
                    "application/source/functions/rxPowerSaving.c", "application/source/functions/wake_hop.c"):
            if (pp(FW, incs, cf["DUALCHEN"], rel) or "").split() != (pp(root, incs, cf["DUALCHEN"], (rel if os.path.exists(os.path.join(root, rel)) else empty)) or "").split():
                bad.append(rel)
        check(bad == [], "DUALCHEN (англійська з прапорцем): код режиму мертвий, токени як у базі: %r" % bad)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ 5
def fields(t): return [m.group(1) for m in re.finditer(r"^\.(\w+)\s*=", t, re.M)]


def test_lang():
    ua = rd(os.path.join(LANG, "ukrainian.h"), "cp1251"); en = rd(os.path.join(LANG, "english.h"), "cp1251")
    st = rd(os.path.join(LANG, "uiLanguage.h"))
    check(fields(ua)[-len(DUAL_FIELDS):] == DUAL_FIELDS and fields(en)[-len(DUAL_FIELDS):] == DUAL_FIELDS, "мовні поля R97 -- останні в ukrainian.h і english.h")
    m = re.search(r"#if defined\(ENABLE_DUAL_CHANNEL\)\n((?:.*\n)*?)#endif\n#endif\n\} stringsTable_t;", st)
    check(m is not None and re.findall(r"const char (\w+)\[", m.group(1)) == DUAL_FIELDS, "uiLanguage.h: поля R97 останні, під ENABLE_DUAL_CHANNEL усередині блоку UA")
    vals = dict(re.findall(r'^\.(dual_\w+)\s*=\s*"([^"]*)"', ua, re.M))
    check(all(len(v) <= 16 for v in vals.values()) and len(vals["dual_rx"] + ":Off") <= 16, "ширина: усі <= 16, «Подв. прийом:Off» <= 16: %r" % vals)
    c = rd(os.path.join(APP, "source", "user_interface", "uiChannelMode.c"))
    check(not re.search(r'"[^"\n]*[А-Яа-яІіЇїЄєҐґ][^"\n]*"', re.sub(r"//[^\n]*", "", c)), "у uiChannelMode.c нема кириличних рядкових літералів")


# ------------------------------------------------------------------------------------------------ 6
def test_cps():
    import custom_region as cr
    import custom_compact as cc
    payload = bytes([1, 3, 0x2C, 0x01, 0, 0, 0, 0])
    region = bytearray(b"\xff" * cr.REGION_LEN)
    region[0:12] = cr.MAGIC + b"\x00" * 4
    off = 12
    for typ, pl in ((0x7E000000 + 5, bytes(64)), (15, bytes(8)), (18, payload), (17, b"\x02"), (99, b"xyz")):   # 99 -- справді невідомий тип   # перший -- вилучений блок (є що ущільнювати)
        region[off:off + 8] = struct.pack("<ii", typ, len(pl)); region[off + 8:off + 8 + len(pl)] = pl; off += 8 + len(pl)
    r = cr.parse_region(bytes(region))
    b18 = r.by_type().get(18)
    check(b18 is not None and b18.payload == payload and not r.problems, "CPS: розбір області бачить блок 18 як є")
    check(cr.type_name(18) == "DUAL_CHANNEL_CFG" and r.by_type().get(99) is not None and r.by_type()[99].payload == b"xyz", "CPS: тип 18 у таблиці назв (R97); невідомий тип (99) теж розбирається як є")
    check(b18 is not None and cr.default_selected(b18) and not cr.is_retired(18), "CPS: блок 18 типово відновлюється (не стан, не вилучений, не секрет)")
    try:
        text = cr.settings_to_text(r.blocks)
        back = {b.type: b.payload for b in cr.settings_from_text(text)[0]}
        check(back.get(18) == payload and back.get(99) == b"xyz", "CPS: файл налаштувань переносить блок 18 (і невідомий) байт-у-байт")
    except Exception as e:  # noqa
        check(False, "CPS: файл налаштувань з блоком 18: %s" % e)
    try:
        plan, why = cc.plan_compaction(bytes(region))
        check(plan is not None, "CPS: план ущільнення є (%s)" % why)
        if plan is not None:
            r2 = cr.parse_region(bytes(plan.expected))
            check(r2.by_type().get(18) is not None and r2.by_type()[18].payload == payload and r2.by_type().get(99) is not None and (0x7E000000 + 5) not in r2.by_type(),
                  "CPS: ущільнення прибирає вилучений блок і зберігає блок 18 байт-у-байт")
    except Exception as e:  # noqa
        check(False, "CPS: ущільнення з блоком 18: %s" % e)



# ------------------------------------------------------------------------------------------------ 7 (R97-FIX)
QM_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
enum { NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2 };
static const int MELODY_ERROR_BEEP[1];
struct { char dual_b_saved[17]; char dual_on[17]; char dual_off[17]; } lang = { "B saved", "ON", "OFF" }, *currentLanguage = &lang;
static int chA = 0, inUse = 1, menuVal = 0, enabled = 0, setBcalls = 0, setBval = 0, notif = 0, beep = 0, enCalls = 0, enVal = -1, resume = 0, disable = 0, pairErr = 0;
static dcPairCheck_t pair = DC_PAIR_OK;
static uint32_t s_dualKeyMs = 77;
static uint16_t dualChannelA(void) { return (uint16_t)chA; }
bool codeplugAllChannelsIndexIsInUse(int ch) { (void)ch; return inUse; }
void soundSetMelody(const int *m) { (void)m; beep++; }
bool dcSetChannelB(uint16_t ch, bool now) { setBcalls++; setBval = ch; (void)now; return true; }
void uiNotificationShow(int t, int id, uint32_t ms, const char *msg, bool imm) { (void)t; (void)id; (void)ms; (void)msg; (void)imm; notif++; }
bool dcMenuValue(void) { return menuVal; }
bool dcIsEnabled(void) { return enabled; }
static dcPairCheck_t dualCheckPair(void) { return pair; }
static void dualShowPairError(dcPairCheck_t e) { (void)e; pairErr++; }
void dcSetTxHold(bool h) { (void)h; }
bool dcSetEnabled(bool on, bool now) { (void)now; enCalls++; enVal = on; enabled = on; return true; }
static void dualAutoResume(void) { resume++; }
static void dualDisable(void) { disable++; enabled = 0; }
void uiChannelModeUpdateScreen(int x) { (void)x; }
%(fn)s
static void reset(void) { chA = 0; inUse = 1; menuVal = 0; enabled = 0; setBcalls = 0; setBval = 0; notif = 0; beep = 0; enCalls = 0; enVal = -1; resume = 0; disable = 0; pairErr = 0; pair = DC_PAIR_OK; }
int main(void)
{
	reset(); chA = 42; dualQuickMenuApply(true); printf("b1=%%d,%%d,%%d,%%d\n", setBcalls, setBval, notif, enCalls);
	reset(); chA = 42; enabled = 1; menuVal = 1; dualQuickMenuApply(true); printf("b2=%%d,%%d,%%d,%%d\n", setBcalls, setBval, enabled, disable);
	reset(); chA = 42; inUse = 0; dualQuickMenuApply(true); printf("b3=%%d,%%d\n", setBcalls, beep);
	reset(); chA = 42; menuVal = 1; dualQuickMenuApply(false); printf("o1=%%d,%%d,%%d,%%d\n", setBcalls, enCalls, enVal, resume);
	reset(); chA = 42; menuVal = 1; pair = DC_PAIR_NO_B; dualQuickMenuApply(false); printf("o2=%%d,%%d,%%d\n", pairErr, enCalls, setBcalls);
	reset(); chA = 42; enabled = 1; menuVal = 0; dualQuickMenuApply(false); printf("o3=%%d,%%d\n", disable, setBcalls);
	reset(); chA = 42; dualQuickMenuApply(false); printf("o4=%%d,%%d,%%d\n", setBcalls, enCalls, disable);
	return 0;
}
"""



def qm_case_problems(src):
    """Статично: у case «Подв. прийом»/«Встановити як B» пункт меню читається ДО menuSystemPopPreviousMenu(), після Pop -- жодного menuDataGlobal."""
    m = re.search(r"case CH_SCREEN_QUICK_MENU_DUAL_CHANNEL:[^\n]*\n\t*case CH_SCREEN_QUICK_MENU_SET_B:(.*?)\breturn;", src, re.S)
    if m is None:
        return ["case пунктів R97 у швидкому меню не знайдено"]
    body = m.group(1)
    p = []
    i_pop = body.find("menuSystemPopPreviousMenu();")
    i_read = body.find("menuDataGlobal.currentItemIndex == CH_SCREEN_QUICK_MENU_SET_B")
    if i_pop < 0:
        p.append("Pop не знайдено")
    elif i_read < 0 or i_read > i_pop:
        p.append("пункт меню читається ПІСЛЯ menuSystemPopPreviousMenu() (Pop перезаписує currentItemIndex)")
    if i_pop >= 0 and "menuDataGlobal" in body[i_pop:]:
        p.append("після Pop ще читається menuDataGlobal")
    return p


def test_quickmenu_fix(incs, cf):
    src = rd(os.path.join(APP, "source", "user_interface", "uiChannelMode.c"))
    check(qm_case_problems(src) == [], "R97-FIX: у case «Подв. прийом»/«Встановити як B» пункт береться ДО Pop: %r" % qm_case_problems(src))
    bug = src.replace("bool setB = (menuDataGlobal.currentItemIndex == CH_SCREEN_QUICK_MENU_SET_B);\n", "", 1).replace(
        "dualQuickMenuApply(setB);", "dualQuickMenuApply(menuDataGlobal.currentItemIndex == CH_SCREEN_QUICK_MENU_SET_B);", 1)
    check(bug != src and qm_case_problems(bug) != [], "R97-FIX (мутант): старий порядок (читання після Pop) ловиться")
    blk = src[src.find("#define DUAL_RESUME_QUIET_MS"):src.find("#endif // DUAL_CHANNEL_ENABLED")]
    check(blk and "menuDataGlobal" not in blk, "R97-FIX: у блоці R97 (рушій/екран/клавіші) стан меню не читається")
    if "DUALCH" not in cf:
        return
    t = pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    fn = [carve_fn(t or "", "static void dualSetMode(_Bool on, _Bool notify)"), carve_fn(t or "", "static void dualQuickMenuApply(_Bool setB)")]
    check(all(fn), "R97-FIX: dualQuickMenuApply і dualSetMode знайдено")
    if not all(fn):
        return
    fn = "\n".join(fn)
    out = run_c(QM_HARNESS % {"fn": fn})
    check(out is not None, "R97-FIX: хостова збірка dualQuickMenuApply")
    if out is None:
        return
    o = dict(l.split("=", 1) for l in out.split())
    check(o.get("b1") == "1,42,1,0", "«Встановити як B»: dcSetChannelB(dualChannelA()) + сповіщення, стан режиму не чіпає: %s" % o.get("b1"))
    check(o.get("b2") == "1,42,1,0", "«Встановити як B» при ввімкненому режимі: B = A, режим лишається ввімкненим (чекає іншого A): %s" % o.get("b2"))
    check(o.get("b3") == "0,1", "«Встановити як B» на неіснуючому каналі: нічого не пише, звук помилки: %s" % o.get("b3"))
    check(o.get("o1") == "0,1,1,1", "«Подв. прийом» On: вмикає й запускає, B не чіпає: %s" % o.get("o1"))
    check(o.get("o2") == "1,0,0", "«Подв. прийом» On без B: сповіщення, режим не вмикається: %s" % o.get("o2"))
    check(o.get("o3") == "1,0", "«Подв. прийом» Off: вимикає: %s" % o.get("o3"))
    check(o.get("o4") == "0,0,0", "«Подв. прийом» без зміни значення: нічого: %s" % o.get("o4"))


# ------------------------------------------------------------------------------------------------ 8 (R97-FIX2)
HK_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
enum { NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2 };
static const int MELODY_ERROR_BEEP[1];
struct { char dual_b_saved[17]; char dual_on[17]; char dual_off[17]; } lang = { "B saved", "ON", "OFF" }, *currentLanguage = &lang;
static int chA = 0, inUse = 1, menuVal = 0, enabled = 0, setBcalls = 0, setBval = 0, notif = 0, beep = 0, enCalls = 0, enVal = -1, resume = 0, disable = 0, pairErr = 0, lastNotifOn = -1;
static dcPairCheck_t pair = DC_PAIR_OK;
static uint32_t s_dualKeyMs = 77;
static uint16_t dualChannelA(void) { return (uint16_t)chA; }
bool codeplugAllChannelsIndexIsInUse(int ch) { (void)ch; return inUse; }
void soundSetMelody(const int *m) { (void)m; beep++; }
bool dcSetChannelB(uint16_t ch, bool now) { setBcalls++; setBval = ch; (void)now; return true; }
void uiNotificationShow(int t, int id, uint32_t ms, const char *msg, bool imm) { (void)t; (void)id; (void)ms; (void)imm; notif++; lastNotifOn = (msg == lang.dual_on); }
bool dcMenuValue(void) { return menuVal; }
bool dcIsEnabled(void) { return enabled; }
static dcPairCheck_t dualCheckPair(void) { return pair; }
static void dualShowPairError(dcPairCheck_t e) { (void)e; pairErr++; beep++; }
void dcSetTxHold(bool h) { (void)h; }
bool dcSetEnabled(bool on, bool now) { (void)now; enCalls++; enVal = on; enabled = on; return true; }
static void dualAutoResume(void) { resume++; }
static void dualDisable(void) { disable++; enabled = 0; }
void uiChannelModeUpdateScreen(int x) { (void)x; }
%(fn)s
static void reset(void) { chA = 0; inUse = 1; menuVal = 0; enabled = 0; setBcalls = 0; setBval = 0; notif = 0; beep = 0; enCalls = 0; enVal = -1; resume = 0; disable = 0; pairErr = 0; pair = DC_PAIR_OK; lastNotifOn = -1; }
int main(void)
{
	reset(); chA = 42; dualQuickMenuApply(true); printf("b1=%%d,%%d,%%d,%%d\n", setBcalls, setBval, notif, enCalls);
	reset(); chA = 42; enabled = 1; menuVal = 1; dualQuickMenuApply(true); printf("b2=%%d,%%d,%%d,%%d\n", setBcalls, setBval, enabled, disable);
	reset(); chA = 42; inUse = 0; dualQuickMenuApply(true); printf("b3=%%d,%%d\n", setBcalls, beep);
	reset(); chA = 42; menuVal = 1; dualQuickMenuApply(false); printf("o1=%%d,%%d,%%d,%%d,%%d\n", setBcalls, enCalls, enVal, resume, notif);
	reset(); chA = 42; menuVal = 1; pair = DC_PAIR_NO_B; dualQuickMenuApply(false); printf("o2=%%d,%%d,%%d\n", pairErr, enCalls, setBcalls);
	reset(); chA = 42; enabled = 1; menuVal = 0; dualQuickMenuApply(false); printf("o3=%%d,%%d,%%d\n", disable, setBcalls, notif);
	reset(); chA = 42; dualQuickMenuApply(false); printf("o4=%%d,%%d,%%d\n", setBcalls, enCalls, disable);
	/* гаряча клавіша (довге ▼): та сама логіка */
	reset(); dualHotkeyToggle(); printf("h1=%%d,%%d,%%d,%%d,%%d,%%d\n", enCalls, enVal, resume, notif, lastNotifOn, pairErr);
	reset(); enabled = 1; dualHotkeyToggle(); printf("h2=%%d,%%d,%%d,%%d,%%d\n", disable, enabled, notif, lastNotifOn, enCalls);
	reset(); pair = DC_PAIR_NO_B; dualHotkeyToggle(); printf("h3=%%d,%%d,%%d,%%d,%%d\n", pairErr, beep, enCalls, notif, enabled);
	reset(); pair = DC_PAIR_B_DELETED; dualHotkeyToggle(); printf("h4=%%d,%%d,%%d\n", pairErr, enCalls, notif);
	reset(); pair = DC_PAIR_B_IS_A; dualHotkeyToggle(); printf("h5=%%d,%%d,%%d\n", pairErr, enCalls, notif);
	reset(); dualHotkeyToggle(); dualHotkeyToggle(); printf("h6=%%d,%%d,%%d,%%d\n", enCalls, disable, enabled, notif);
	return 0;
}
"""

RS_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
enum { SCAN_STATE_SCANNING = 0, SCAN_STATE_SHORT_PAUSED, SCAN_STATE_PAUSED };
enum { SCAN_TYPE_NORMAL_STEP = 0, SCAN_TYPE_DUAL_CHANNEL = 2 };
enum { QSO_DISPLAY_IDLE = 0, QSO_DISPLAY_DEFAULT_SCREEN, QSO_DISPLAY_CALLER_DATA, QSO_DISPLAY_CALLER_DATA_UPDATE };
enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
enum { THEME_ITEM_FG_CHANNEL_CONTACT, THEME_ITEM_BG };
enum { CHANNEL_FLAG_BW_25K = 1, CHANNEL_FLAG_TIMESLOT_TWO = 2 };
#define FONT_SIZE_3 3
typedef struct { uint8_t chMode; uint8_t txColor; uint8_t flags; } CodeplugChannel_t;
typedef struct { CodeplugChannel_t *ch; uint8_t mode; uint8_t bw25; uint8_t ts; uint8_t cc; } uiHeaderOverride_t;
struct { struct { bool active; int scanType; int state; } Scan; int displayQSOState, displayQSOStatePrev; bool isDisplayingQSOData; uint32_t receivedPcId; } uiDataGlobal;
struct { char dual_title[17]; } lang, *currentLanguage = &lang;
static int plain = 0, plainDW = -1, forCalls = 0, clears = 0, renders = 0, rows = 0, mode = RADIO_MODE_ANALOG, ptrB = 0, chA = 1, chB = 2, redraw = 0, rssi = 0;
static uiHeaderOverride_t got; static CodeplugChannel_t chans[8];
static void *LinkHead = 0;
void displayClearBuf(void) { clears++; }
void uiUtilityRenderHeader(bool dw, bool sweep, bool force) { (void)force; (void)sweep; plain++; plainDW = dw; }
void uiUtilityRenderHeaderForChannel(const uiHeaderOverride_t *ov, bool force) { (void)force; forCalls++; got = *ov; got.ch = 0; got.mode = ov->mode; }
void uiUtilityRedrawHeaderOnly(bool a, bool b, bool c) { (void)a; (void)b; (void)c; redraw++; }
void uiUtilityDrawRSSIBarGraph(void) { rssi++; }
bool codeplugAllChannelsIndexIsInUse(int ch) { return (ch >= 1) && (ch <= 7); }
void codeplugChannelGetDataForIndex(int ch, CodeplugChannel_t *c) { *c = chans[ch]; }
int codeplugChannelGetFlag(CodeplugChannel_t *c, int f) { return (c->flags & f) != 0; }
uint32_t buttonsRead(void) { return 0; }
int trxGetMode(void) { return mode; }
uint32_t HRC6000GetReceivedTgOrPcId(void) { return 0; }
void lastHeardClearLastID(void) {}
void displayThemeApply(int a, int b) { (void)a; (void)b; }
void displayThemeResetToDefault(void) {}
void displayPrintCentered(int y, const char *t, int f) { (void)y; (void)t; (void)f; }
void dualRenderRow(int y, bool isB, uint16_t ch, bool p, bool a) { (void)y; (void)isB; (void)ch; (void)p; (void)a; rows++; }
void dualRenderCaller(void) {}
uint16_t dualChannelA(void) { return chA; }
uint16_t dcChannelB(void) { return chB; }
bool dcPointerB(void) { return ptrB; }
bool dcIsOnB(void) { return false; }
void uiDrawAesEnabledIcon(void) {}
void displayRender(void) { renders++; }
%(fns)s
int main(void)
{
	chans[1].chMode = RADIO_MODE_DIGITAL; chans[1].txColor = 5; chans[1].flags = CHANNEL_FLAG_TIMESLOT_TWO;
	chans[2].chMode = RADIO_MODE_ANALOG; chans[2].txColor = 0; chans[2].flags = CHANNEL_FLAG_BW_25K;
	for (int st = SCAN_STATE_SCANNING; st <= SCAN_STATE_PAUSED; st++)
	{
		for (ptrB = 0; ptrB <= 1; ptrB++)
		{
			plain = 0; plainDW = -1; forCalls = 0; rows = 0; renders = 0; redraw = 0; rssi = 0; got.mode = got.bw25 = got.ts = got.cc = 0;
			uiDataGlobal.Scan.active = true; uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL; uiDataGlobal.Scan.state = st;
			dualRenderScreen();
			printf("rs%%d%%d=%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", st, ptrB, plain, plainDW, forCalls, got.mode, got.bw25, got.ts, got.cc, rows, renders, redraw + rssi);
		}
	}
	/* uiChannelModeDualHeader (applicationMain): true лише при чергуванні без активності */
	ptrB = 1; uiDataGlobal.Scan.active = true; uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL; uiDataGlobal.Scan.state = SCAN_STATE_SCANNING; forCalls = 0;
	int h1 = uiChannelModeDualHeader(false); int f1 = forCalls;
	uiDataGlobal.Scan.state = SCAN_STATE_PAUSED; int h2 = uiChannelModeDualHeader(false);
	uiDataGlobal.Scan.state = SCAN_STATE_SCANNING; uiDataGlobal.Scan.active = false; int h3 = uiChannelModeDualHeader(false);
	uiDataGlobal.Scan.active = true; uiDataGlobal.Scan.scanType = SCAN_TYPE_NORMAL_STEP; int h4 = uiChannelModeDualHeader(false);
	printf("hd=%%d,%%d,%%d,%%d,%%d\n", h1, f1, h2, h3, h4);
	/* B недійсний -- запасний варіант: справжня шапка */
	uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL; uiDataGlobal.Scan.active = true; ptrB = 1; chB = 99; plain = 0; forCalls = 0; dualRenderScreen();
	printf("bad=%%d,%%d\n", plain, forCalls);
	return 0;
}
"""

DIS_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "%(dc)s"
enum { SCAN_STATE_SCANNING = 0 };
enum { SCAN_TYPE_NORMAL_STEP = 0, SCAN_TYPE_DUAL_CHANNEL = 2 };
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 };
enum { NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2 };
typedef struct { uint16_t channels[80]; int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_highestIndex; int NOT_IN_CODEPLUGDATA_indexNumber; } zone_t;
static zone_t currentZone;
struct { int16_t currentZone; } nonVolatileSettings;
struct { char dual_zone_all[17]; } lang, *currentLanguage = &lang;
struct { struct { bool active; int scanType; int state; } Scan; int displayQSOState; } uiDataGlobal;
static int zoneSets = 0, notif = 0, loads = 0, suspends = 0, tunes = 0, initCalls = 0, lastZ = -99, lastV = -99, onB = 0, enabled = 1, holdClr = 0, scanNextChannelReady = 1; static uint16_t chB = 0;
bool settingsSetBOOL(bool *p, bool v) { (void)p; (void)v; return 0; }
bool settingsSetINT8(int8_t *p, int8_t v) { (void)p; (void)v; return 0; }
bool settingsSetUINT8(uint8_t *p, uint8_t v) { (void)p; (void)v; return 0; }
bool settingsSetINT16(int16_t *p, int16_t v) { *p = v; zoneSets++; return 1; }
bool settingsSetUINT16(uint16_t *p, uint16_t v) { (void)p; (void)v; return 0; }
bool settingsSetINT32(int32_t *p, int32_t v) { (void)p; (void)v; return 0; }
bool settingsSetUINT32(uint32_t *p, uint32_t v) { (void)p; (void)v; return 0; }
int codeplugZonesGetCount(void) { return 10; }
void uiChannelInitializeCurrentZone(void) { initCalls++; memset(&currentZone, 0, sizeof(currentZone)); currentZone.NOT_IN_CODEPLUGDATA_indexNumber = -1; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = 5; currentZone.NOT_IN_CODEPLUGDATA_highestIndex = 1024; }
int16_t codeplugSetLastUsedChannelInZone(int z, int16_t v) { lastZ = z; lastV = v; return v; }
bool codeplugAllChannelsIndexIsInUse(int ch) { return (ch == 3 || ch == 7 || ch == 9 || ch == 12); }
void uiNotificationShow(int t, int id, uint32_t ms, const char *msg, bool imm) { (void)t; (void)id; (void)ms; (void)msg; (void)imm; notif++; }
void uiChannelModeLoadChannelData(bool mem, bool vp) { (void)vp; if (mem == 0) loads++; }
void lastHeardClearLastID(void) {}
bool dcIsOnB(void) { return onB; }
void dcSetOnB(bool b) { onB = b; }
uint16_t dcChannelB(void) { return chB; }
void dcSetTxHold(bool h) { (void)h; holdClr++; }
bool dcSetEnabled(bool on, bool now) { (void)now; enabled = on; return 1; }
static bool dualIsRunning(void) { return uiDataGlobal.Scan.active && uiDataGlobal.Scan.scanType == SCAN_TYPE_DUAL_CHANNEL; }
static void dualSuspend(void) { suspends++; onB = 0; uiDataGlobal.Scan.active = false; }
static void dualTune(bool toB) { tunes++; onB = toB; }
%(fns)s
static void setup(int zoneIdx, int n, int c0, int c1, int c2, uint16_t b, int run, int onb)
{
	memset(&currentZone, 0, sizeof(currentZone)); currentZone.NOT_IN_CODEPLUGDATA_indexNumber = zoneIdx; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = n;
	currentZone.NOT_IN_CODEPLUGDATA_highestIndex = (zoneIdx < 0 ? 1024 : n); currentZone.channels[0] = c0; currentZone.channels[1] = c1; currentZone.channels[2] = c2;
	chB = b; onB = onb; enabled = 1; zoneSets = notif = loads = suspends = tunes = initCalls = 0; lastZ = lastV = -99; scanNextChannelReady = 1;
	nonVolatileSettings.currentZone = zoneIdx; uiDataGlobal.Scan.active = run; uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL; uiDataGlobal.Scan.state = 2;
}
static void rep(const char *n) { printf("%%s=%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", n, lastZ, lastV, zoneSets, notif, loads, onB, enabled, uiDataGlobal.Scan.active, suspends, tunes, nonVolatileSettings.currentZone); }
int main(void)
{
	setup(3, 3, 3, 7, 9, 7, 1, 1); dualDisable(); rep("d1");       /* B у поточній зоні (позиція 1) */
	setup(3, 3, 3, 7, 9, 12, 1, 1); dualDisable(); rep("d2");      /* B не з поточної зони -> «Всі канали» */
	setup(-1, 5, 0, 0, 0, 7, 1, 1); dualDisable(); rep("d3");      /* поточна зона «Всі канали» */
	setup(3, 3, 3, 7, 9, 7, 1, 0); dualDisable(); rep("d4");       /* рація на A -- лишається на A */
	setup(3, 3, 3, 7, 9, 8, 1, 1); dualDisable(); rep("d5");       /* B видалено -> як раніше, на A */
	setup(3, 3, 3, 7, 9, 3, 0, 1); dualDisable(); rep("d6");       /* режим не чергує, рація на B (після TX): лишаємось на B, позиція 0 */
	setup(3, 3, 3, 7, 9, 0, 0, 1); dualDisable(); rep("d7");       /* B не задано, рація на B (зіпсований стан) -> на A */
	return 0;
}
"""

ZONE_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "%(dc)s"
typedef struct { uint16_t channels[80]; int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_highestIndex; int NOT_IN_CODEPLUGDATA_indexNumber; } zone_t;
static zone_t currentZone;
static uint8_t lastUsedChannelInZoneData[70];
static bool lastUsedChannelInZoneHasChanged;
static uint8_t codeplugAllChannelsCache[128];
static uint16_t chB = 0;
uint16_t dcChannelB(void) { return chB; }
bool dcSetChannelB(uint16_t c, bool now) { (void)now; chB = c; return true; }
bool dcIsOnB(void) { return false; }
enum { SCAN_STATE_SCANNING = 0 };
struct { struct { int state; } Scan; } uiDataGlobal;
static const int MELODY_ERROR_BEEP[1];
static int beeps = 0;
void soundSetMelody(const int *m) { (void)m; beeps++; }
static void dualTune(bool t) { (void)t; }
static void dualSetDwell(void) {}
static void setUse(int ch) { ch--; codeplugAllChannelsCache[ch / 8] |= (uint8_t)(1u << (ch %% 8)); }
%(fns)s
static void allZone(int hi) { memset(&currentZone, 0, sizeof(currentZone)); currentZone.NOT_IN_CODEPLUGDATA_indexNumber = -1; currentZone.NOT_IN_CODEPLUGDATA_highestIndex = hi;
	int n = 0; for (int c = 1; c <= 1024; c++) if (codeplugAllChannelsIndexIsInUse(c)) n++; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = n; }
int main(void)
{
	memset(codeplugAllChannelsCache, 0, sizeof(codeplugAllChannelsCache));
	setUse(1); setUse(2); setUse(5); setUse(7); setUse(10); setUse(1024);
	/* «Всі канали»: A = номер каналу, збережений як (номер-1) у int16 -- ЯК у стоку (handleUpKey пише номер) */
	allZone(1024);
	codeplugSetLastUsedChannelInZone(-1, 5);
	printf("a1=%%d\n", dualChannelA());                                   /* 5 */
	codeplugSetLastUsedChannelInZone(-1, 1024);
	printf("a2=%%d\n", dualChannelA());                                   /* 1024 */
	codeplugSetLastUsedChannelInZone(-1, 5); chB = 7;
	printf("a3=%%d\n", dcCheckPair(dualChannelA(), chB, codeplugAllChannelsIndexIsInUse(chB)));   /* OK=0 */
	/* крок B валкодером від 7: 10, 1024, 1 (обхід через край), 2, (5 = A пропускається) 7 */
	int seq[8], k = 0;
	for (k = 0; k < 6; k++) { dualStepB(1); seq[k] = chB; }
	printf("s1=%%d,%%d,%%d,%%d,%%d,%%d\n", seq[0], seq[1], seq[2], seq[3], seq[4], seq[5]);
	chB = 7; for (k = 0; k < 4; k++) { dualStepB(-1); seq[k] = chB; }
	printf("s2=%%d,%%d,%%d,%%d\n", seq[0], seq[1], seq[2], seq[3]);       /* 2 (5=A пропущено), 1, 1024, 10 */
	/* highestIndex < 1024: той самий обхід */
	setUse(1024); codeplugAllChannelsCache[127] = 0; allZone(10); chB = 10; dualStepB(1); printf("s3=%%d\n", chB);   /* 1 */
	/* A збігається з B у «Всіх каналах» */
	chB = 5; printf("p1=%%d\n", dcCheckPair(dualChannelA(), chB, codeplugAllChannelsIndexIsInUse(chB)));   /* B_IS_A=3 */
	/* B видалено (поза маскою) */
	chB = 6; printf("p2=%%d\n", dcCheckPair(dualChannelA(), chB, codeplugAllChannelsIndexIsInUse(chB)));   /* B_DELETED=2 */
	/* зона з каналами: A = channels[індекс] */
	memset(&currentZone, 0, sizeof(currentZone)); currentZone.NOT_IN_CODEPLUGDATA_indexNumber = 3; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = 3; currentZone.NOT_IN_CODEPLUGDATA_highestIndex = 3;
	currentZone.channels[0] = 2; currentZone.channels[1] = 7; currentZone.channels[2] = 10;
	codeplugSetLastUsedChannelInZone(3, 1); printf("z1=%%d\n", dualChannelA());           /* 7 */
	chB = 10; dualStepB(1); printf("z2=%%d\n", chB);                                       /* 2 (з 10 -> 2; A=7 пропущено не потрібно) */
	chB = 2; dualStepB(1); printf("z3=%%d\n", chB);                                       /* 10 (7=A пропущено) */
	/* порожня зона / «Всі канали» без каналів: A = 0 */
	allZone(0); currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = 0; printf("e1=%%d\n", dualChannelA());
	/* «Всі канали» й зона не змішують «останній канал» (різні комірки) */
	allZone(1024); codeplugSetLastUsedChannelInZone(-1, 7); codeplugSetLastUsedChannelInZone(3, 2);
	printf("m1=%%d,%%d\n", codeplugGetLastUsedChannelInZone(-1), codeplugGetLastUsedChannelInZone(3));   /* 7,2 */
	return 0;
}
"""


def test_fix2(incs, cf):
    src = rd(os.path.join(APP, "source", "user_interface", "uiChannelMode.c"))
    uu = rd(os.path.join(APP, "source", "user_interface", "uiUtilities.c"), "utf-8")
    am = rd(os.path.join(APP, "source", "applicationMain.c"))
    # ---- п.1: шапка (статично) ----
    check("scanType != SCAN_TYPE_DUAL_CHANNEL" in uu and "R97-FIX2" in uu, "п.1: uiUtilityRenderHeader -- у режимі подвійного прийому шапка не блимає (scanIsActive без SCAN_TYPE_DUAL_CHANNEL, лише під DUAL_CHANNEL_ENABLED)")
    check(re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)\s*//[^\n]*\n\s*(//[^\n]*\n\s*)*bool scanIsActive = \(\(uiDataGlobal\.Scan\.active && \(uiDataGlobal\.Scan\.scanType != SCAN_TYPE_DUAL_CHANNEL\)\) \|\| uiDataGlobal\.Scan\.toneActive\);\s*#else\s*bool scanIsActive = \(uiDataGlobal\.Scan\.active \|\| uiDataGlobal\.Scan\.toneActive\);\s*#endif", uu) is not None,
          "п.1: зміна scanIsActive -- лише під DUAL_CHANNEL_ENABLED, інакше рядок стоковий")
    blk = src[src.find("static void dualScanning(void)\n{"):src.find("// ---- валкодер на рядку B")]
    check("uiUtilityRedrawHeaderOnly" not in blk, "п.1: dualScanning() не перемальовує шапку при перемиканні A/B")
    tick = src[src.find("if ((ev->time - m) > RSSI_UPDATE_COUNTER_RELOAD)"):]
    tick = tick[:tick.find("if (uiNotificationIsVisible())")]
    check(re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)\s*if \(rxPowerSavingIsRxOn\(\) && \(\(dualIsRunning\(\) && \(uiDataGlobal\.Scan\.state == SCAN_STATE_SCANNING\)\) == false\)\)[^\n]*\n#else\s*if \(rxPowerSavingIsRxOn\(\)\)\s*#endif", tick) is not None,
          "п.1: RSSI-тік -- під час чергування (SCANNING) без S-метра й виводу на екран (під DUAL_CHANNEL_ENABLED, стоковий рядок збережено)")
    check(re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)[^\n]*\n(?:\s*//[^\n]*\n)*\s*if \(\(currentMenu == UI_CHANNEL_MODE\) && uiChannelModeDualHeader\(\(buttons & BUTTON_SK1\) == BUTTON_SK1\)\)", am) is not None and "uiChannelModeDualHeaderStatic" not in am,
          "R97-FIX3: applicationMain (headerRowIsDirty: батарея/CC) -- під час чергування без активності та сама шапка обраного каналу, що й на екрані режиму (статичне «[DW]» скасовано)")
    check("uiChannelModeDualHeaderStatic" not in src and "uiUtilityRenderHeader((uiDataGlobal.Scan.state == SCAN_STATE_SCANNING)" not in src, "R97-FIX3: статичне «[DW]» (isVFODualWatchScanning=true) у dualRenderScreen/applicationMain скасовано")
    # ---- R97-FIX3 п.2: ядро шапки (статично) ----
    core = uu[uu.find("static void uiUtilityRenderHeaderCore("):uu.find("void uiUtilityRedrawHeaderOnly(")]
    check("#define trxGetMode() ((ov != NULL)" in uu and "#undef trxGetMode" in uu and core.count("trxGetDMRColourCode()") >= 1 and "(ov == NULL)" in core and "currentChannelData = ov->ch;" in core and "currentChannelData = savedChannelData;" in core,
          "R97-FIX3: ядро шапки читає режим/смугу/TS/CC з ov, тони/потужність -- з каналу ov, макроси діють лише в ядрі")
    check(re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)\s*if \(\(isVFODualWatchScanning == false\) && \(ov == NULL\)\)[^\n]*\n#else\s*if \(isVFODualWatchScanning == false\)\s*#endif\s*\{\s*if \(isTransmittingIgnoringAPRSBeaconing\(\) == false\)\s*\{\s*if \(!isVFOSweepScanning\)\s*\{\s*uiUtilityDrawRSSIBarGraph\(\);", uu) is not None,
          "R97-FIX3: з ov (обраний канал без активності) смуга S-метра НЕ малюється; без ov -- стоковий рядок")
    check(re.search(r"static (bool|uint\w+_t|int\w*) s_hdr", uu) is None, "R97-FIX3: нових статичних змінних у шапці нема")
    if "DUALCH" not in cf:
        check(False, "конфігурація DUALCH є в syntax_check.sh"); return
    t = pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    check(t is not None, "п.1-3: uiChannelMode.c препроцесується в DUALCH")
    if t is None:
        return
    # ---- R97-FIX3 п.2: dualRenderScreen/dualRenderHeader хостово ----
    fns = [carve_fn(t, s_) for s_ in ("static void dualRenderHeader(_Bool force)", "_Bool uiChannelModeDualHeader(_Bool force)", "static void dualRenderScreen(void)")]
    check(all(fns), "R97-FIX3: знайдено dualRenderHeader / uiChannelModeDualHeader / dualRenderScreen")
    if all(fns):
        pre = "static _Bool dualIsRunning(void) { return (uiDataGlobal.Scan.active && (uiDataGlobal.Scan.scanType == SCAN_TYPE_DUAL_CHANNEL)); }\n"
        out = run_c(RS_HARNESS % {"fns": pre + "\n".join(fns)})
        check(out is not None, "R97-FIX3: хостова збірка шапки екрана режиму")
        if out is not None:
            o = dict(l.split("=", 1) for l in out.split())
            # формат: звичайних шапок, isVFODualWatchScanning, шапок з кодплага, режим, bw25, ts, cc, рядків, рендерів, (RedrawHeaderOnly+S-метр)
            check(o.get("rs00") == "0,-1,1,2,0,1,5,2,1,0", "п.2 (а): чергування, покажчик на A (DMR TS2 CC5): шапка з кодплага A, звичайної нема, S-метр/RedrawHeaderOnly не кличуться: %s" % o.get("rs00"))
            check(o.get("rs01") == "0,-1,1,1,1,0,0,2,1,0", "п.2 (а): чергування, покажчик на B (FM 25 кГц): шапка з кодплага B: %s" % o.get("rs01"))
            check(o.get("rs10") == "1,0,0,0,0,0,0,2,1,0" and o.get("rs11") == "1,0,0,0,0,0,0,2,1,0" and o.get("rs20") == "1,0,0,0,0,0,0,2,1,0" and o.get("rs21") == "1,0,0,0,0,0,0,2,1,0",
                  "п.2 (б): виклик/утримання -- справжня шапка (isVFODualWatchScanning=false, не «[DW]»), покажчик значення не має: %s %s %s %s" % (o.get("rs10"), o.get("rs11"), o.get("rs20"), o.get("rs21")))
            check(o.get("hd") == "1,1,0,0,0", "п.2 (в): uiChannelModeDualHeader (applicationMain) -- true лише при чергуванні без активності: %s" % o.get("hd"))
            check(o.get("bad") == "1,0", "п.2 (г): недійсний канал -- запасна справжня шапка: %s" % o.get("bad"))
            mut = [fns[0].replace("uiUtilityRenderHeaderForChannel(&ov, force);", "uiUtilityRenderHeader(0, 0, force);"), fns[1], fns[2]]
            mo = run_c(RS_HARNESS % {"fns": pre + "\n".join(mut)})
            check(fns[0] != mut[0] and mo is not None and dict(l.split("=", 1) for l in mo.split()).get("rs00") != o.get("rs00"), "п.2 (мутант): шапка з даних trx замість кодплага ловиться тестом (а)")
    # ---- R97-FIX3 п.1: вимкнення на B ----
    dsf = [carve_fn(t, s_) for s_ in ("static uint16_t dualZoneChannelAt(int pos, void *ctx)", "static void dualLeaveOnB(void)", "static void dualDisable(void)")]
    check(all(dsf), "R97-FIX3: знайдено dualZoneChannelAt / dualLeaveOnB / dualDisable")
    if all(dsf):
        out = run_c(DIS_HARNESS % {"dc": os.path.join(APP, "source", "functions", "dual_channel.c"), "fns": "static uint16_t dualZoneChannelAt(int pos, void *ctx);\n" + "\n".join(dsf[0:1] + dsf[1:])})
        check(out is not None, "R97-FIX3: хостова збірка вимкнення на B")
        if out is not None:
            o = dict(l.split("=", 1) for l in out.split())
            # формат: зона last-used, значення, змін зони, сповіщень, завантажень каналу, onB, увімкнено, Scan.active, suspend, tune, currentZone
            exp = {"d1": "3,1,0,0,1,0,0,0,0,0,3", "d2": "-1,12,1,1,1,0,0,0,0,0,9", "d3": "-1,7,0,0,1,0,0,0,0,0,-1", "d4": "-99,-99,0,0,0,0,0,0,1,0,3",
                   "d5": "-99,-99,0,0,0,0,0,0,1,0,3", "d6": "3,0,0,0,1,0,0,0,0,0,3", "d7": "-99,-99,0,0,0,0,0,0,0,1,3"}
            names = {"d1": "на B, B у поточній зоні: last-used = позиція B, зона та сама, без сповіщення", "d2": "на B, B з іншої зони: зона «Всі канали» (9), last-used(-1) = номер B, сповіщення",
                     "d3": "на B у зоні «Всі канали»: last-used(-1) = номер B, зона та сама", "d4": "на A: як раніше (dualSuspend), канал не перезавантажується",
                     "d5": "на B, але B видалено: як раніше на A", "d6": "режим не чергує, рація на B (після TX): лишаємось на B, позиція 0", "d7": "рація на B без B (зіпсований стан): на A"}
            for k in exp:
                check(o.get(k) == exp[k], "п.1 %s -- %s: %s" % (k, names[k], o.get(k)))
            bug = [dsf[0], dsf[1], dsf[2].replace("_Bool stayB = (dcIsOnB()", "_Bool stayB = (0 && dcIsOnB()")]
            mo = run_c(DIS_HARNESS % {"dc": os.path.join(APP, "source", "functions", "dual_channel.c"), "fns": "static uint16_t dualZoneChannelAt(int pos, void *ctx);\n" + "\n".join(bug)})
            check(bug[2] != dsf[2] and mo is not None and dict(l.split("=", 1) for l in mo.split()).get("d1") != o.get("d1"), "п.1 (мутант): старий dualDisable (завжди на A) ловиться тестом d1")
    check(src.count("dualDisable()") >= 3 and "dualLeaveOnB();" in src, "R97-FIX3: dualDisable викликається з RED, dualSetMode(off) і dualAutoResume (помилка пари) -- усі через нову логіку")
    # ---- п.2: гаряча клавіша ----
    ev = src[src.find("static void handleEvent(uiEvent_t *ev)\n{"):src.find("static bool dualIsRunning(void)\n{")]
    hk = re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)\s*else if \(KEYCHECK_LONGDOWN\(ev->keys, KEY_FRONT_DOWN\) && \(KEYCHECK_LONGDOWN_REPEAT\(ev->keys, KEY_FRONT_DOWN\) == false\) &&\s*\(BUTTONCHECK_DOWN\(ev, BUTTON_SK2\) == 0\) && \(BUTTONCHECK_DOWN\(ev, BUTTON_SK1\) == 0\) && \(directChannelNumber == 0\)\)\s*\{[^}]*dualHotkeyToggle\(\);\s*return;\s*\}\s*#endif", ev)
    check(hk is not None, "п.2: handleEvent -- довге ▼ без SK2/SK1 (і без набору номера) викликає dualHotkeyToggle(), без автоповтору")
    dk = src[src.find("static bool dualHandleKey(uiEvent_t *ev)\n{"):src.find("// Увімкнути/вимкнути режим")]
    check("KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN)" in dk and "KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_FRONT_DOWN) == false" in dk and "dualHotkeyToggle();" in dk and
          "BUTTONCHECK_DOWN(ev, BUTTON_SK2) || BUTTONCHECK_DOWN(ev, BUTTON_SK1)" in dk,
          "п.2: dualHandleKey -- у режимі, що чергує, довге ▼ вимикає (без автоповтору; з SK2/SK1 -- не наше)")
    check("KEYCHECK_SHORTUP(ev->keys, KEY_DECREASE)" in ev and "KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN)" not in ev.replace(hk.group(0) if hk else "", ""),
          "п.2: коротке ▼ (KEY_DECREASE) без змін; довге ▼ більше ніде в handleEvent не використовується")
    check(len(re.findall(r"KEYCHECK_LONGDOWN\(ev->keys,\s*KEY_FRONT_UP", ev)) + len(re.findall(r"KEY_FRONT_UP\s*\n", ev)) >= 1 and "scanStart(true);" in ev,
          "п.2: довге ▲ (старт сканування зони) не зачеплено")
    fn = [carve_fn(t, s) for s in ("static void dualSetMode(_Bool on, _Bool notify)", "static void dualHotkeyToggle(void)", "static void dualQuickMenuApply(_Bool setB)")]
    check(all(fn), "п.2: знайдено dualSetMode / dualHotkeyToggle / dualQuickMenuApply")
    if all(fn):
        out = run_c(HK_HARNESS % {"fn": "\n".join(fn)})
        check(out is not None, "п.2: хостова збірка гарячої клавіші")
        if out is not None:
            o = dict(l.split("=", 1) for l in out.split())
            check(o.get("o1") == "0,1,1,1,0", "п.2: пункт меню «Подв. прийом» On -- як раніше (без сповіщення «вкл»): %s" % o.get("o1"))
            check(o.get("o3") == "1,0,0", "п.2: пункт меню Off -- як раніше (без сповіщення): %s" % o.get("o3"))
            check(o.get("h1") == "1,1,1,1,1,0", "п.2: довге ▼ при вимкненому режимі й валідній парі: вмикає, запускає чергування, сповіщення «вкл»: %s" % o.get("h1"))
            check(o.get("h2") == "1,0,1,0,0", "п.2: довге ▼ при ввімкненому режимі: вимикає, сповіщення «вимк»: %s" % o.get("h2"))
            check(o.get("h3") == "1,1,0,0,0", "п.2: довге ▼ без B: «B не задано» + звук помилки, режим не вмикається, сповіщення «вкл» нема: %s" % o.get("h3"))
            check(o.get("h4") == "1,0,0" and o.get("h5") == "1,0,0", "п.2: канал B видалено / B збігається з A -- помилка, режим не вмикається: %s / %s" % (o.get("h4"), o.get("h5")))
            check(o.get("h6") == "1,1,0,2", "п.2: два довгі ▼ підряд -- вмикає, потім вимикає: %s" % o.get("h6"))
    # ---- п.3: «Всі канали» (-1) ----
    cp = pp(FW, incs, cf["DUALCH"], "application/source/functions/codeplug.c")
    zf = [carve_fn(t, s) for s in ("static uint16_t dualChannelA(void)", "static uint16_t dualZoneChannelAt(int pos, void *ctx)", "static void dualStepB(int dir)")]
    cf2 = [carve_fn(cp or "", s) for s in ("int16_t codeplugGetLastUsedChannelInZone(int zoneNum)", "int16_t codeplugGetLastUsedChannelNumberInCurrentZone(void)",
                                          "int16_t codeplugSetLastUsedChannelInZone(int zoneNum, int16_t channelNum)", "_Bool codeplugAllChannelsIndexIsInUse(int index)")]
    check(all(zf) and all(cf2), "п.3: знайдено dualChannelA/dualZoneChannelAt/dualStepB (uiChannelMode.c) і codeplug*LastUsed*/codeplugAllChannelsIndexIsInUse (codeplug.c)")
    if all(zf) and all(cf2):
        out = run_c(ZONE_HARNESS % {"dc": os.path.join(APP, "source", "functions", "dual_channel.c"), "fns": "\n".join(cf2 + zf)})
        check(out is not None, "п.3: хостова збірка вибору A/B у «Всіх каналах»")
        if out is not None:
            o = dict(l.split("=", 1) for l in out.split())
            check(o.get("a1") == "5" and o.get("a2") == "1024", "п.3: «Всі канали» -- A = номер каналу з «останнього каналу зони» (справжні codeplug*LastUsed*): %s/%s" % (o.get("a1"), o.get("a2")))
            check(o.get("a3") == "0", "п.3: «Всі канали» -- пара A=5, B=7 валідна: %s" % o.get("a3"))
            check(o.get("s1") == "10,1024,1,2,7,10", "п.3: «Всі канали» -- валкодер B вгору: 10,1024,1,2,(5=A пропущено)7,10: %s" % o.get("s1"))
            check(o.get("s2") == "2,1,1024,10", "п.3: «Всі канали» -- валкодер B вниз від 7: 2 (A=5 пропущено),1,1024,10: %s" % o.get("s2"))
            check(o.get("s3") == "1", "п.3: «Всі канали», найвищий канал 10: обхід через край на 1: %s" % o.get("s3"))
            check(o.get("p1") == "3" and o.get("p2") == "2", "п.3: «Всі канали» -- B=A і видалений B виявляються: %s/%s" % (o.get("p1"), o.get("p2")))
            check(o.get("z1") == "7" and o.get("z2") == "2" and o.get("z3") == "10", "п.3: звичайна зона -- A=channels[індекс], B по каналах зони: %s,%s,%s" % (o.get("z1"), o.get("z2"), o.get("z3")))
            check(o.get("e1") == "0", "п.3: порожня зона -- A=0 (режим не стартує): %s" % o.get("e1"))
            check(o.get("m1") == "7,2", "п.3: «останній канал» зони -1 і звичайної зони -- різні комірки: %s" % o.get("m1"))


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    test_block18()
    incs, cfgs = cmt.load_configs(FW)
    test_engine(incs, dict(cfgs))
    test_quickmenu_fix(incs, dict(cfgs))
    test_fix2(incs, dict(cfgs))
    test_lang()
    test_cps()
    test_vs_base(incs, cfgs)
    print("test_r97: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
