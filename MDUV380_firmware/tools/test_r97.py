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
  6  CPS не ламає невідомий блок 18: розбір області, ущільнення, файл налаштувань, план відновлення (custom_region.py, custom_compact.py).
Порівняння з комітом бази стійке до його відсутності: без коміта -- ПРОПУСК з повідомленням.
Запуск: python3 tools/test_r97.py"""
import os, re, shutil, struct, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); FW = os.path.dirname(HERE); sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa
APP = os.path.join(FW, "application"); LANG = os.path.join(APP, "include", "user_interface", "languages")
BASE = os.environ.get("R97_BASE", "7fa5fe8")
FAILS = []; N = [0]
DUAL_FIELDS = ["dual_rx", "dual_set_b", "dual_title", "dual_b_saved", "dual_err_no_b", "dual_err_b_gone", "dual_err_b_is_a"]


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
	carrier = 0; rf = 0; ticks(1990); int still = (onB == 1); ticks(20); printf("hold=%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", st1, st2, to, stay, still, onB, uiDataGlobal.Scan.state);
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
    check(o.get("alt") == "6,0,6", "чергування A<->B: 6 перемикань за 6 витримок, кожне -- лише шапка: %s" % o.get("alt"))
    check(o.get("hold") == "1,2,1999,1,1,0,0", "утримання: SHORT_PAUSED -> PAUSED (scanDelay*1000, мінус поточний тік), поки є звук -- на B; після -- поновлення на A: %s" % o.get("hold"))
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


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    test_block18()
    incs, cfgs = cmt.load_configs(FW)
    test_engine(incs, dict(cfgs))
    test_lang()
    test_cps()
    test_vs_base(incs, cfgs)
    print("test_r97: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
