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
import json, os, re, shutil, struct, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); FW = os.path.dirname(HERE); sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa
APP = os.path.join(FW, "application"); LANG = os.path.join(APP, "include", "user_interface", "languages")
BASE = os.environ.get("R97_BASE", "7fa5fe8")
FAILS = []; N = [0]
DUAL_FIELDS = ["dual_rx", "dual_set_b", "dual_title", "dual_b_saved", "dual_err_no_b", "dual_err_b_gone", "dual_err_b_is_a", "dual_on", "dual_off", "dual_zone_all", "dual_rx_on", "dual_wait"]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


def rd(p, enc="utf-8"): return open(p, "rb").read().decode(enc)


def pp(root, incs, defs, rel):
    for _attempt in range(2):   # один повтор: поодинокий збій запуску gcc не має давати хибну «різницю токенів»
        r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w", "-Wno-builtin-macro-redefined", "-D__TIME__=\"00:00:00\"", "-D__DATE__=\"Jan  1 2000\""] + incs + defs + [rel], cwd=root, capture_output=True)   # __TIME__ у заголовку давав хибну різницю токенів на межі секунди
        if r.returncode == 0:
            return r.stdout.decode("cp1251", "replace")
    return None


# R98-FIX4: A може бути VFO (тип A у RAM/блоці 18). Старі тести (R97..R98-FIX3) моделюють A = канал: у вирізаних функціях нові помічники типу A
# замінюються їхнім значенням для A = канал (dcTypeA() = 0), тож гарнеси попередніх ітерацій лишаються чинними. tools/test_r98fix4.py вимикає це
# (COMPAT_A_CHANNEL = False) і перевіряє справжні функції з A = VFO.
COMPAT_A_CHANNEL = True
_PAREN = r"((?:[^()]|\((?:[^()]|\([^()]*\))*\))*)"


def _compat_enable_inline(text):
    """Тіло dualEnable() з typeCur = канал -- як було в dualSetMode(true) до R98-FIX4 (без «A для повернення», без авто B = VFO)."""
    i = -1
    for m in re.finditer(re.escape("static _Bool dualEnable(uint8_t typeCur)"), text):
        if text[m.end():].lstrip().startswith("{"):
            i = m.start(); break
    if i < 0:
        return None
    j = text.index("{", i); d = 0
    for k in range(j, len(text)):
        if text[k] == "{": d += 1
        elif text[k] == "}":
            d -= 1
            if d == 0:
                body = text[j + 1:k]; break
    body = body.replace("uint16_t idxCur = ((typeCur == 0U) ? dualChannelA() : 0U);", "uint16_t idxCur = dualChannelA();")
    body = body.replace(" dcSetTypeA(typeCur);\n", "").replace(" dcSetOnB(0);\n", "")
    body = re.sub(r"if \(typeCur != 0U\)\s*\{[^{}]*\}\s*else if", "if", body)
    body = re.sub(r"uint8_t rt;\s*uint16_t ri;\s*if \(dcSameTarget\(typeCur, idxCur, dcTypeB\(\), dcChannelB\(\)\) && dcGetReturnA\(&rt, &ri\)\)\s*\{[^{}]*\}", "", body)
    body = body.replace("(dualIsRunning() == 0) && (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE)", "dualIsRunning() == 0")
    body = body.replace("return 0;", "return;").replace("return 1;", "")
    return "{" + body + "}"


def compat_a_channel(f, text=None):
    if text is not None and "if (dualEnable((uint8_t)0U) == 0)" in f:
        inl = _compat_enable_inline(text)
        if inl:
            f = re.sub(r"if \(dualEnable\(\(uint8_t\)0U\) == 0\)\s*\{\s*return;\s*\}", lambda m: inl, f)
    f = f.replace("dualBReset();", "s_dualSqlB = 0U;").replace("s_dualZoneB = 0U;", ";")   # R98-FIX5 -> R98-FIX3/4 (див. COMPAT_FIX4)
    f = re.sub(r"uint16_t retIdx = \(dcAIsVfo\(\) \? 0U : dualChannelA\(\)\);", "uint16_t retIdx = 0U;", f)
    f = f.replace("dualBSameAsA() && dualBExists()", "dualBSameAsA() && (dcBIsVfo() || ((dcChannelB() >= 1U) && (dcChannelB() <= 1024U) && codeplugAllChannelsIndexIsInUse(dcChannelB())))")
    f = f.replace("(dcIsOnB() || dcAIsVfo())", "dcIsOnB()")
    f = f.replace("dualOnVfoNow()", "(dcIsEnabled() && dcIsOnB() && dcBIsVfo())")
    f = re.sub(r"dualCardIsVfo\(" + _PAREN + r"\)", r"((\1) ? dcBIsVfo() : 0)", f)
    f = re.sub(r"dualCardVfo\(" + _PAREN + r"\)", r"((\1) ? dualVfoIdx() : 0)", f)
    f = re.sub(r"dualLeaveOnVfo\(" + _PAREN + r"\);", "dualLeaveOnVfo();", f)
    f = re.sub(r"\(void\)dcDisableWithReturnA\(" + _PAREN + r"\);", "(void)dcSetEnabled(0, 1);", f)
    f = f.replace("channelScreenChannelData.rxFreq = 0U;", ";").replace("channelScreenChannelData.rxFreq = 0;", ";")
    f = f.replace("dcAIsVfo()", "0").replace("dcTypeA()", "0").replace("dualIsAKey(ev)", "0")
    f = re.sub(r"dcSetTypeA\(" + _PAREN + r"\);", ";", f)
    return f


# R98-FIX5: функції «Подвійного прийому», змінені в R98-FIX5 (керування, розкладка, робоча копія B), старі тести (R97..R98-FIX4) бачать у вигляді
# R98-FIX4 -- препроцесований текст бази 7205514, заморожений у tools/testdata/r98fix4_dw_frozen.json (база в CI/клоні може бути недоступна).
# Їхні гарнеси моделюють світ до FIX5 (s_dualSqlB, dualIsAKey, шапка обраного каналу); нову поведінку перевіряє tools/test_r98fix5.py (COMPAT_FIX4 = False).
COMPAT_FIX4 = True
# R98-FIX6: те саме для функцій, змінених у R98-FIX6 (переходи, розкладка 4 рядки): тести R97..R98-FIX5 бачать їх у вигляді R98-FIX5 (база e29eeb7,
# tools/testdata/r98fix5_dw_frozen.json); нову поведінку перевіряє tools/test_r98fix6.py (COMPAT_FIX5 = False).
COMPAT_FIX5 = True
# R98-FIX7: функції, змінені в R98-FIX7 (ручка лише по каналах, червона = канал <-> VFO, dcStepExt прибрано), тести R97..R98-FIX6 бачать у вигляді
# R98-FIX6 (база dda0a43, tools/testdata/r98fix6_dw_frozen.json); нову поведінку перевіряє tools/test_r98fix7.py (COMPAT_FIX6 = False).
COMPAT_FIX6 = True
_FROZEN = {}


def _frozen(fname, name):
    if fname not in _FROZEN:
        try:
            _FROZEN[fname] = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata", fname), encoding="utf-8"))
        except (OSError, ValueError):
            _FROZEN[fname] = {}
    return _FROZEN[fname].get(name)


def frozen_fix4(name):
    return _frozen("r98fix4_dw_frozen.json", name)


def frozen_fix5(name):
    return _frozen("r98fix5_dw_frozen.json", name)


def frozen_fix6(name):
    return _frozen("r98fix6_dw_frozen.json", name)


def carve_fn(text, sig):
    """Функція від сигнатури sig до парної закривальної дужки (лічба { })."""
    m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\(", sig)
    for on, fn_ in ((COMPAT_FIX4, frozen_fix4), (COMPAT_FIX5, frozen_fix5), (COMPAT_FIX6, frozen_fix6)):
        fz = fn_(m.group(1)) if (on and m) else None
        p = fz.find(sig) if fz is not None else -1
        if 0 <= p < 24:
            fz = fz[p:]
            return compat_a_channel(fz, text) if COMPAT_A_CHANNEL else fz
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
                return compat_a_channel(text[i:k + 1], text) if COMPAT_A_CHANNEL else text[i:k + 1]
    return None


def _dc_stepext_compat(code):
    """R98-FIX7 А3: dcStepExt (коло «канали -> VFO A -> VFO B») з прошивки прибрано; старі гарнеси (заморожені dualStepA/dualStepB R98-FIX6) його
    викликають -- для них дописується заморожене визначення R98-FIX6 (tools/testdata/r98fix6_dw_frozen.json). Нову поведінку перевіряє test_r98fix7.py."""
    if (not COMPAT_FIX6) or ("dcStepExt(" not in code) or ("dual_channel.c" not in code):
        return code
    try:
        src = open(os.path.join(APP, "source", "functions", "dual_channel.c"), encoding="utf-8").read()
    except OSError:
        return code
    fz = frozen_fix6("dcStepExt")
    if ("int dcStepExt(" in src) or (fz is None):
        return code
    return code + "\n/* R98-FIX7: заморожений dcStepExt R98-FIX6 (сумісність старих тестів) */\n" + fz + "\n"


def run_c(code, extra=()):
    code = _dc_stepext_compat(code)
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
    check(o["c"] == "1,2,0,0,1", "перевірка пари (R97-FIX6): нема B / B видалено / B==A тепер OK / OK / поза межами: %s" % o["c"])
    check(o["tx"] == "01010011", "PTT: без активності -- покажчик; прийом/утримання -- де рація зараз: %s" % o["tx"])
    check(o["s"] == "2,4,0,4,0,4,-1", "валкодер: крок з пропуском порожньої позиції й A, по колу, назад, від краю, порожня зона: %s" % o["s"])
    check(o["f"] == "4,-1,-1", "валкодер: пошук позиції B: %s" % o["f"])
    check(o["n"] == "-1", "валкодер: у зоні лише A -- кроку нема: %s" % o["n"])


# ------------------------------------------------------------------------------------------------ 2
HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
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
    fn = re.sub(r"if \(dcIsEnabled\(\) && dcIsOnB\(\)\)\s*\{\s*uiChannelModeLoadChannelData\(1, 1\);\s*\}\s*else", "", fn)   # R98-FIX1 В3: вставка в uiChannelModeStopScanning
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
        # R98-FIX2 Л: підказка літер у назві каналу -- окрема українська можливість (не режим), її файли перевіряє tools/test_r98fix2.py;
        # прототипи keypadAlphaPreviewMap/uiSmsKeyHintMap у заголовках вирізаються тим самим фільтром, що й R96-вставки (r96_tokfilter.py).
        from r96_tokfilter import strip_r96
        # R98-FIX7 В: volume_low.c -- окрема можливість ENABLE_VOLUME_LOW (коліно K = 32 замість 16), її перевіряють tools/test_r78.py і tests/test_volume_low.c.
        l_files = ("application/source/io/keyboard.c", "application/source/user_interface/uiSmsKeys.c", "application/source/user_interface/menuChannelDetails.c",
                   "application/source/functions/volume_low.c")
        for name in ("AES0", "ENDATA", "UA"):
            bad = []
            for rel in files:
                if rel in l_files:
                    continue
                ta, tb = pp(FW, incs, cf[name], rel), pp(root, incs, cf[name], (rel if os.path.exists(os.path.join(root, rel)) else empty))
                if strip_r96((ta or "").encode()).split() != strip_r96((tb or "").encode()).split():
                    bad.append(rel)
            check(bad == [], "%s: токени всіх %d файлів .c як у базі %s (без прапорця R97 нічого не змінилось): %r" % (name, len(files), BASE, bad[:5]))
        # DUALCHEN: прапорець в англійській збірці мертвий
        bad = []
        for rel in ("application/source/user_interface/uiChannelMode.c", "application/source/applicationMain.c", "application/source/functions/dual_channel.c",
                    "application/source/functions/rxPowerSaving.c", "application/source/functions/wake_hop.c"):
            if strip_r96((pp(FW, incs, cf["DUALCHEN"], rel) or "").encode()).split() != strip_r96((pp(root, incs, cf["DUALCHEN"], (rel if os.path.exists(os.path.join(root, rel)) else empty)) or "").encode()).split():
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
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
enum { NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2 };
static const int MELODY_ERROR_BEEP[1];
struct { char dual_b_saved[17]; char dual_on[17]; char dual_off[17]; } lang = { "B saved", "ON", "OFF" }, *currentLanguage = &lang;
static int chA = 0, inUse = 1, menuVal = 0, enabled = 0, setBcalls = 0, setBval = 0, notif = 0, beep = 0, enCalls = 0, enVal = -1, resume = 0, disable = 0, pairErr = 0;
static dcPairCheck_t pair = DC_PAIR_OK;
static int onBq = 0;
bool dcIsOnB(void) { return onBq; }
static uint32_t s_dualKeyMs = 77;
static uint16_t dualChannelA(void) { return (uint16_t)chA; }
bool codeplugAllChannelsIndexIsInUse(int ch) { (void)ch; return inUse; }
void soundSetMelody(const int *m) { (void)m; beep++; }
bool dcSetChannelB(uint16_t ch, bool now) { setBcalls++; setBval = ch; (void)now; pair = DC_PAIR_OK; return true; }
void uiNotificationShow(int t, int id, uint32_t ms, const char *msg, bool imm) { (void)t; (void)id; (void)ms; (void)msg; (void)imm; notif++; }
bool dcMenuValue(void) { return menuVal; }
bool dcIsEnabled(void) { return enabled; }
static dcPairCheck_t dualCheckPair(void) { return pair; }
static void dualShowPairError(dcPairCheck_t e) { (void)e; pairErr++; }
void dcSetTxHold(bool h) { (void)h; }
bool dcSetEnabled(bool on, bool now) { (void)now; enCalls++; enVal = on; enabled = on; return true; }
static void dualAutoResume(void) { resume++; }
static void dualDisable(void) { disable++; enabled = 0; }
static int running = 0, updCalls = 0;
static bool dualIsRunning(void) { return running; }
void uiChannelModeUpdateScreen(int x) { (void)x; updCalls++; }
enum { UI_CHANNEL_MODE = 7 };
int menuSystemGetCurrentMenuNumber(void) { return UI_CHANNEL_MODE; }   /* R98: dualSetMode не малює канальний екран, якщо вже на VFO-екрані */
%(fn)s
static void reset(void) { chA = 0; inUse = 1; menuVal = 0; enabled = 0; setBcalls = 0; setBval = 0; notif = 0; beep = 0; enCalls = 0; enVal = -1; resume = 0; disable = 0; pairErr = 0; pair = DC_PAIR_OK; onBq = 0; }
int main(void)
{
	reset(); chA = 42; menuVal = 1; dualQuickMenuApply(); printf("o1=%%d,%%d,%%d,%%d\n", setBcalls, enCalls, enVal, resume);
	reset(); chA = 42; menuVal = 1; pair = DC_PAIR_NO_B; dualQuickMenuApply(); printf("o2=%%d,%%d,%%d\n", pairErr, enCalls, setBcalls);
	reset(); chA = 42; enabled = 1; menuVal = 0; dualQuickMenuApply(); printf("o3=%%d,%%d\n", disable, setBcalls);
	reset(); chA = 42; dualQuickMenuApply(); printf("o4=%%d,%%d,%%d\n", setBcalls, enCalls, disable);
	return 0;
}
"""



def qm_case_problems(src):
    """Статично: у case «Подв. прийом» після menuSystemPopPreviousMenu() -- жодного menuDataGlobal (Pop перезаписує currentItemIndex)."""
    m = re.search(r"case CH_SCREEN_QUICK_MENU_DUAL_CHANNEL:[^\n]*\n\t*\{(.*?)\breturn;", src, re.S)
    if m is None:
        return ["case пункту R97 у швидкому меню не знайдено"]
    body = m.group(1)
    p = []
    i_pop = body.find("menuSystemPopPreviousMenu();")
    if i_pop < 0:
        p.append("Pop не знайдено")
    if i_pop >= 0 and "menuDataGlobal" in body[i_pop:]:
        p.append("після Pop ще читається menuDataGlobal")
    return p


def test_quickmenu_fix(incs, cf):
    src = rd(os.path.join(APP, "source", "user_interface", "uiChannelMode.c"))
    check(qm_case_problems(src) == [], "R97-FIX: у case «Подв. прийом» після Pop стан меню не читається: %r" % qm_case_problems(src))
    bug = src.replace("menuSystemPopPreviousMenu();\n\t\t\t\t\tdualQuickMenuApply();", "menuSystemPopPreviousMenu();\n\t\t\t\t\tdualQuickMenuApply(menuDataGlobal.currentItemIndex);", 1)
    check(bug != src and qm_case_problems(bug) != [], "R97-FIX (мутант): читання стану меню після Pop ловиться")
    blk = src[src.find("#define DUAL_RESUME_QUIET_MS"):src.find("#endif // DUAL_CHANNEL_ENABLED")]
    check(blk and "menuDataGlobal" not in blk, "R97-FIX: у блоці R97 (рушій/екран/клавіші) стан меню не читається")
    if "DUALCH" not in cf:
        return
    t = pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    fn = [carve_fn(t or "", "static void dualSetMode(_Bool on, _Bool notify)"), carve_fn(t or "", "static void dualQuickMenuApply(void)")]
    check(all(fn), "R97-FIX: dualQuickMenuApply і dualSetMode знайдено")
    if not all(fn):
        return
    fn = "\n".join(fn)
    out = run_c(QM_HARNESS % {"fn": fn})
    check(out is not None, "R97-FIX: хостова збірка dualQuickMenuApply")
    if out is None:
        return
    o = dict(l.split("=", 1) for l in out.split())
    check(o.get("o1") == "0,1,1,1", "«Подв. прийом» On: вмикає й запускає, B не чіпає: %s" % o.get("o1"))
    check(o.get("o2") == "0,1,1", "R98-FIX1: «Подв. прийом» On без B (A=42 існує): B = A автоматично, помилки нема, режим вмикається: %s" % o.get("o2"))
    check(o.get("o3") == "1,0", "«Подв. прийом» Off: вимикає: %s" % o.get("o3"))
    check(o.get("o4") == "0,0,0", "«Подв. прийом» без зміни значення: нічого: %s" % o.get("o4"))


# ------------------------------------------------------------------------------------------------ 8 (R97-FIX2)
HK_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
enum { NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2 };
static const int MELODY_ERROR_BEEP[1];
struct { char dual_b_saved[17]; char dual_on[17]; char dual_off[17]; } lang = { "B saved", "ON", "OFF" }, *currentLanguage = &lang;
static int chA = 0, inUse = 1, menuVal = 0, enabled = 0, setBcalls = 0, setBval = 0, notif = 0, beep = 0, enCalls = 0, enVal = -1, resume = 0, disable = 0, pairErr = 0, lastNotifOn = -1;
static dcPairCheck_t pair = DC_PAIR_OK;
static int onBq = 0;
bool dcIsOnB(void) { return onBq; }
static uint32_t s_dualKeyMs = 77;
static uint16_t dualChannelA(void) { return (uint16_t)chA; }
bool codeplugAllChannelsIndexIsInUse(int ch) { (void)ch; return inUse; }
void soundSetMelody(const int *m) { (void)m; beep++; }
bool dcSetChannelB(uint16_t ch, bool now) { setBcalls++; setBval = ch; (void)now; pair = DC_PAIR_OK; return true; }
void uiNotificationShow(int t, int id, uint32_t ms, const char *msg, bool imm) { (void)t; (void)id; (void)ms; (void)imm; notif++; lastNotifOn = (msg == lang.dual_on); }
bool dcMenuValue(void) { return menuVal; }
bool dcIsEnabled(void) { return enabled; }
static dcPairCheck_t dualCheckPair(void) { return pair; }
static void dualShowPairError(dcPairCheck_t e) { (void)e; pairErr++; beep++; }
void dcSetTxHold(bool h) { (void)h; }
bool dcSetEnabled(bool on, bool now) { (void)now; enCalls++; enVal = on; enabled = on; return true; }
static void dualAutoResume(void) { resume++; }
static void dualDisable(void) { disable++; enabled = 0; }
static int running = 0, updCalls = 0;
static bool dualIsRunning(void) { return running; }
void uiChannelModeUpdateScreen(int x) { (void)x; updCalls++; }
enum { UI_CHANNEL_MODE = 7 };
int menuSystemGetCurrentMenuNumber(void) { return UI_CHANNEL_MODE; }   /* R98: dualSetMode не малює канальний екран, якщо вже на VFO-екрані */
%(fn)s
static void reset(void) { chA = 0; inUse = 1; menuVal = 0; enabled = 0; setBcalls = 0; setBval = 0; notif = 0; beep = 0; enCalls = 0; enVal = -1; resume = 0; disable = 0; pairErr = 0; pair = DC_PAIR_OK; lastNotifOn = -1; onBq = 0; }
int main(void)
{
	reset(); chA = 42; menuVal = 1; dualQuickMenuApply(); printf("o1=%%d,%%d,%%d,%%d,%%d\n", setBcalls, enCalls, enVal, resume, notif);
	reset(); chA = 42; menuVal = 1; pair = DC_PAIR_NO_B; dualQuickMenuApply(); printf("o2=%%d,%%d,%%d\n", pairErr, enCalls, setBcalls);
	reset(); chA = 42; enabled = 1; menuVal = 0; dualQuickMenuApply(); printf("o3=%%d,%%d,%%d\n", disable, setBcalls, notif);
	reset(); chA = 42; dualQuickMenuApply(); printf("o4=%%d,%%d,%%d\n", setBcalls, enCalls, disable);
	/* гаряча клавіша (довге ▼): та сама логіка */
	reset(); dualHotkeyToggle(); printf("h1=%%d,%%d,%%d,%%d,%%d,%%d\n", enCalls, enVal, resume, notif, lastNotifOn, pairErr);
	reset(); enabled = 1; dualHotkeyToggle(); printf("h2=%%d,%%d,%%d,%%d,%%d\n", disable, enabled, notif, lastNotifOn, enCalls);
	reset(); pair = DC_PAIR_NO_B; dualHotkeyToggle(); printf("h3=%%d,%%d,%%d,%%d,%%d\n", pairErr, beep, enCalls, notif, enabled);
	reset(); pair = DC_PAIR_B_DELETED; dualHotkeyToggle(); printf("h4=%%d,%%d,%%d\n", pairErr, enCalls, notif);
	reset(); chA = 5; pair = DC_PAIR_OK; updCalls = 0; dualHotkeyToggle(); printf("h5=%%d,%%d,%%d,%%d\n", pairErr, enCalls, notif, updCalls);   /* R97-FIX6: A==B -- не помилка */
	reset(); running = 1; pair = DC_PAIR_OK; updCalls = 0; dualHotkeyToggle(); printf("h7=%%d,%%d,%%d\n", pairErr, enCalls, updCalls); running = 0;
	reset(); dualHotkeyToggle(); dualHotkeyToggle(); printf("h6=%%d,%%d,%%d,%%d\n", enCalls, disable, enabled, notif);
	return 0;
}
"""

RS_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
enum { SCAN_STATE_SCANNING = 0, SCAN_STATE_SHORT_PAUSED, SCAN_STATE_PAUSED };
enum { SCAN_TYPE_NORMAL_STEP = 0, SCAN_TYPE_DUAL_CHANNEL = 2 };
enum { QSO_DISPLAY_IDLE = 0, QSO_DISPLAY_DEFAULT_SCREEN, QSO_DISPLAY_CALLER_DATA, QSO_DISPLAY_CALLER_DATA_UPDATE };
enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
enum { THEME_ITEM_FG_CHANNEL_CONTACT, THEME_ITEM_BG };
enum { CHANNEL_FLAG_BW_25K = 1, CHANNEL_FLAG_TIMESLOT_TWO = 2 };
#define FONT_SIZE_3 3
typedef struct { uint8_t chMode; uint8_t txColor; uint8_t flags; uint8_t NOT_IN_CODEPLUG_flag; } CodeplugChannel_t;
typedef struct { CodeplugChannel_t *ch; uint8_t mode; uint8_t bw25; uint8_t ts; uint8_t cc; } uiHeaderOverride_t;
struct { struct { bool active; int scanType; int state; } Scan; int displayQSOState, displayQSOStatePrev; bool isDisplayingQSOData; uint32_t receivedPcId; } uiDataGlobal;
struct { char dual_title[17]; } lang, *currentLanguage = &lang;
struct { uint32_t overrideTG; } nonVolatileSettings;
#define CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE 0x01
#define CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK 0x02
typedef int Channel_t;
#define CHANNEL_CHANNEL 2
#define CHANNEL_VFO_A 0
#define CHANNEL_VFO_B 1
static int gMan = 0, gOv = 0, gLastChan = -1; static uint8_t gTsFlags = 1;
int8_t tsGetManualOverride(Channel_t c) { gLastChan = c; return gMan; }
bool tsIsContactHasBeenOverridden(Channel_t c) { gLastChan = c; return gOv; }
static int vtB = 0;   /* R98: тип B (0 канал, 1 VFO A, 2 VFO B) */
static CodeplugChannel_t settingsVFOChannel[2];
bool dcBIsVfo(void) { return vtB != 0; }
uint8_t dcTypeB(void) { return (uint8_t)vtB; }
bool dcSameTarget(uint8_t ta, uint16_t ia, uint8_t tb, uint16_t ib) { return (ta == tb) && ((ta == 0) ? (ia == ib) : true); }
static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags);
static uint32_t dualDestination(const CodeplugChannel_t *ch, char *out, bool *numOnly, uint8_t *tsFlags) { (void)ch; out[0] = 0; *numOnly = false; *tsFlags = gTsFlags; return 0; }
static int plain = 0, plainDW = -1, forCalls = 0, clears = 0, renders = 0, rows = 0, mode = RADIO_MODE_ANALOG, ptrB = 0, chA = 1, chB = 2, redraw = 0, rssi = 0;
static uiHeaderOverride_t got; static CodeplugChannel_t chans[8];
static int dummyItem; static void *LinkHead = 0;
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
static int rxTg = 0;
uint32_t HRC6000GetReceivedTgOrPcId(void) { return rxTg; }
static bool dualActivity(bool *cardB);
static bool dualSingle(void);
void lastHeardClearLastID(void) {}
void displayThemeApply(int a, int b) { (void)a; (void)b; }
void displayThemeResetToDefault(void) {}
void displayPrintCentered(int y, const char *t, int f) { (void)y; (void)t; (void)f; }
int onBflag = 0;
int rowSel[2], rowAct[2], rowCal[2], en = 1, carrier = 0, gRowVt[2];
#define DC_CH_MIN 1
#define DC_CH_MAX 1024
#define RADIO_DEVICE_PRIMARY 0
bool dcIsEnabled(void) { return en; }
bool trxCarrierDetected(int d) { (void)d; return carrier; }
void dualRenderRow(int y, bool isB, uint16_t ch, uint8_t vt, bool sel, bool a, bool cal) { (void)y; (void)ch; gRowVt[isB] = vt; rowSel[isB] = sel; rowAct[isB] = a; rowCal[isB] = cal; rows++; }
bool dualSelectedIsB(void) { return (uiDataGlobal.Scan.state != SCAN_STATE_SCANNING) ? (bool)onBflag : (bool)ptrB; }
uint16_t dualChannelA(void) { return chA; }
uint16_t dcChannelB(void) { return chB; }
bool dcPointerB(void) { return ptrB; }
bool dcIsOnB(void) { return onBflag; }
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
			printf("rr%%d%%d=%%d,%%d,%%d,%%d\n", st, ptrB, rowSel[0], rowAct[0], rowSel[1], rowAct[1]);
		}
	}
	/* рація на B, активність: RX-мітка на B, статусний рядок «Прийом на B» */
	onBflag = 1; ptrB = 0; uiDataGlobal.Scan.active = true; uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL; uiDataGlobal.Scan.state = SCAN_STATE_PAUSED; dualRenderScreen();
	printf("rb=%%d,%%d,%%d,%%d\n", rowSel[0], rowAct[0], rowSel[1], rowAct[1]);
	onBflag = 0;
	/* R97-FIX6: A==B (режим ввімкнено, чергування не йде): обраний -- за покажчиком, активність -- несуча/виклик на картці покажчика */
	uiDataGlobal.Scan.active = false; uiDataGlobal.Scan.scanType = SCAN_TYPE_NORMAL_STEP; uiDataGlobal.Scan.state = SCAN_STATE_SCANNING; chB = chA; en = 1;
	ptrB = 0; carrier = 0; dualRenderScreen(); printf("sg1=%%d,%%d,%%d,%%d\n", rowSel[0], rowAct[0], rowSel[1], rowAct[1]);
	ptrB = 1; carrier = 1; dualRenderScreen(); printf("sg2=%%d,%%d,%%d,%%d\n", rowSel[0], rowAct[0], rowSel[1], rowAct[1]);
	ptrB = 0; carrier = 0; rxTg = 91; mode = RADIO_MODE_DIGITAL; LinkHead = &dummyItem; uiDataGlobal.displayQSOState = QSO_DISPLAY_CALLER_DATA; dualRenderScreen();
	printf("sg3=%%d,%%d,%%d,%%d,%%d,%%d\n", rowSel[0], rowAct[0], rowCal[0], rowSel[1], rowAct[1], rowCal[1]);
	rxTg = 0; LinkHead = 0; mode = RADIO_MODE_ANALOG; uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; chB = 2;
	en = 0; chB = chA; carrier = 1; dualRenderScreen(); printf("sg4=%%d,%%d\n", rowAct[0], rowAct[1]);   /* режим вимкнено: не «single» -- активності нема */
	en = 1; chB = 2;
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
	/* R98 Д2: ТС у шапці обраного каналу -- ефективний (канал 1: ТС2 у записі) */
	uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL; uiDataGlobal.Scan.active = true; uiDataGlobal.Scan.state = SCAN_STATE_SCANNING; ptrB = 0; chA = 1; chB = 2;
	gMan = 0; gOv = 0; gTsFlags = 1; dualRenderScreen(); int e1 = got.ts;                            /* NO_TS: ТС каналу = 2 -> 1 (0-based) */
	gTsFlags = 0; dualRenderScreen(); int e2 = got.ts;                                               /* контакт TS1 (маска 0) -> 0 */
	gTsFlags = 2; dualRenderScreen(); int e3 = got.ts;                                               /* контакт TS2 -> 1 */
	gTsFlags = 1; gMan = 1; dualRenderScreen(); int e4 = got.ts;                                     /* ручне ТС1 -> 0 */
	gTsFlags = 0; gMan = 1; gOv = 1; dualRenderScreen(); int e5 = got.ts;                            /* контакт перекрито вручну на ТС1 -> 0 */
	gOv = 0; gMan = 0; nonVolatileSettings.overrideTG = 91; gTsFlags = 0; dualRenderScreen(); int e6 = got.ts; nonVolatileSettings.overrideTG = 0;   /* перекриття ТГ -> ТС каналу 2 -> 1 */
	printf("ets=%%d,%%d,%%d,%%d,%%d,%%d\n", e1, e2, e3, e4, e5, e6);
	/* R98 В3: картка B = VFO -- шапка з запису VFO (режим/смуга/СС), ТС -- ефективний для ЦЬОГО VFO (CHANNEL_VFO_A/B), без звернення до каналу; рядок B несе тип */
	settingsVFOChannel[0].chMode = RADIO_MODE_DIGITAL; settingsVFOChannel[0].txColor = 3; settingsVFOChannel[0].flags = 0; settingsVFOChannel[0].NOT_IN_CODEPLUG_flag = 0x01;
	settingsVFOChannel[1].chMode = RADIO_MODE_ANALOG; settingsVFOChannel[1].txColor = 0; settingsVFOChannel[1].flags = CHANNEL_FLAG_BW_25K; settingsVFOChannel[1].NOT_IN_CODEPLUG_flag = 0x03;
	ptrB = 1; vtB = 1; gTsFlags = 1; gMan = 0; gLastChan = -1; plain = 0; forCalls = 0; dualRenderScreen(); int v1m = got.mode, v1c = got.cc, v1t = got.ts, v1ch = gLastChan, v1p = plain, v1vt = gRowVt[1];
	vtB = 2; gLastChan = -1; dualRenderScreen(); int v2m = got.mode, v2b = got.bw25, v2ch = gLastChan, v2vt = gRowVt[1];
	vtB = 1; ptrB = 0; dualRenderScreen(); int v3m = got.mode, v3vt = gRowVt[0];
	printf("vf=%%d,%%d,%%d,%%d,%%d,%%d|%%d,%%d,%%d,%%d|%%d,%%d\n", v1m, v1c, v1t, v1ch, v1p, v1vt, v2m, v2b, v2ch, v2vt, v3m, v3vt);
	vtB = 0; ptrB = 1;
	return 0;
}
"""

DIS_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#include <string.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "%(dc)s"
enum { SCAN_STATE_SCANNING = 0, SCAN_STATE_SHORT_PAUSED, SCAN_STATE_PAUSED };
enum { SCAN_TYPE_NORMAL_STEP = 0, SCAN_TYPE_DUAL_CHANNEL = 2 };
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 };
enum { NOTIFICATION_TYPE_MESSAGE = 1, NOTIFICATION_ID_CARD = 2 };
typedef struct { uint16_t channels[80]; int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_highestIndex; int NOT_IN_CODEPLUGDATA_indexNumber; } zone_t;
static zone_t currentZone;
struct { int16_t currentZone; } nonVolatileSettings;
struct { char dual_zone_all[17]; } lang, *currentLanguage = &lang;
struct { struct { bool active; int scanType; int state; } Scan; int displayQSOState; } uiDataGlobal;
static int zoneSets = 0, notif = 0, loads = 0, suspends = 0, tunes = 0, initCalls = 0, lastZ = -99, lastV = -99, onB = 0, enabled = 1, holdClr = 0, scanNextChannelReady = 1, ptrB = 0; static uint16_t chB = 0;
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
bool dcPointerB(void) { return ptrB; }
void dcSetOnB(bool b) { onB = b; }
uint16_t dcChannelB(void) { return chB; }
void dcSetTxHold(bool h) { (void)h; holdClr++; }
bool dcSetEnabled(bool on, bool now) { (void)now; enabled = on; return 1; }
static bool dualIsRunning(void) { return uiDataGlobal.Scan.active && uiDataGlobal.Scan.scanType == SCAN_TYPE_DUAL_CHANNEL; }
static void dualTune(bool toB) { tunes++; onB = toB; }
static int bVfo = 0, leaveVfo = 0;   /* R98: B = VFO; «лишитись на VFO» -- лічильник замість виходу в VFO-екран */
bool dcBIsVfo(void) { return bVfo; }
static void dualLeaveOnVfo(void) { leaveVfo++; onB = 0; }
%(fns)s
static void setup(int zoneIdx, int n, int c0, int c1, int c2, uint16_t b, int run, int onb, int ptr, int st)
{
	memset(&currentZone, 0, sizeof(currentZone)); currentZone.NOT_IN_CODEPLUGDATA_indexNumber = zoneIdx; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = n;
	currentZone.NOT_IN_CODEPLUGDATA_highestIndex = (zoneIdx < 0 ? 1024 : n); currentZone.channels[0] = c0; currentZone.channels[1] = c1; currentZone.channels[2] = c2;
	chB = b; onB = onb; enabled = 1; zoneSets = notif = loads = suspends = tunes = initCalls = 0; lastZ = lastV = -99; scanNextChannelReady = 1; ptrB = ptr;
	nonVolatileSettings.currentZone = zoneIdx; uiDataGlobal.Scan.active = run; uiDataGlobal.Scan.scanType = SCAN_TYPE_DUAL_CHANNEL; uiDataGlobal.Scan.state = st;
}
static void rep(const char *n) { printf("%%s=%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", n, lastZ, lastV, zoneSets, notif, loads, onB, enabled, uiDataGlobal.Scan.active, suspends, tunes, nonVolatileSettings.currentZone); }
int main(void)
{
	/* R97-FIX4: ОБРАНИЙ канал -- активність (state != SCANNING): де рація (onB); чергування: покажчик; режим зупинено (не чергує): де стоїть рація */
	setup(3, 3, 3, 7, 9, 7, 1, 1, 0, 2); dualDisable(); rep("d1");  /* виклик на B (покажчик на A), B у поточній зоні (позиція 1) -> лишаємось на B */
	setup(3, 3, 3, 7, 9, 7, 1, 0, 1, 0); dualDisable(); rep("d1b"); /* чергування, покажчик на B, рація фізично на A -> на B */
	setup(3, 3, 3, 7, 9, 12, 1, 1, 1, 2); dualDisable(); rep("d2"); /* B не з поточної зони -> «Всі канали» */
	setup(-1, 5, 0, 0, 0, 7, 1, 1, 1, 2); dualDisable(); rep("d3"); /* поточна зона «Всі канали» */
	setup(3, 3, 3, 7, 9, 7, 1, 1, 0, 0); dualDisable(); rep("d4");  /* чергування, покажчик на A, рація на B -> на A */
	setup(3, 3, 3, 7, 9, 7, 1, 0, 1, 2); dualDisable(); rep("d4b"); /* виклик на A (покажчик на B) -> лишаємось на A */
	setup(3, 3, 3, 7, 9, 8, 1, 1, 1, 2); dualDisable(); rep("d5");  /* B видалено -> на A */
	setup(3, 3, 3, 7, 9, 3, 0, 1, 0, 0); dualDisable(); rep("d6");  /* режим зупинено меню на B (не чергує) -> лишаємось на B, позиція 0 */
	setup(3, 3, 3, 7, 9, 0, 0, 1, 0, 0); dualDisable(); rep("d7");  /* B не задано, рація на B (зіпсований стан) -> на A */
	setup(3, 3, 3, 7, 9, 7, 0, 0, 1, 0); dualDisable(); rep("d8");  /* режим зупинено меню на A -> лишаємось на A (покажчик не враховується) */
	/* dualSuspend() налаштовує рацію на ОБРАНИЙ канал */
	setup(3, 3, 3, 7, 9, 7, 1, 1, 0, 0); dualSuspend(); printf("s1=%%d,%%d,%%d,%%d\n", onB, tunes, uiDataGlobal.Scan.active, uiDataGlobal.Scan.scanType);   /* чергування, покажчик A, рація на B -> A */
	setup(3, 3, 3, 7, 9, 7, 1, 0, 1, 0); dualSuspend(); printf("s2=%%d,%%d,%%d,%%d\n", onB, tunes, uiDataGlobal.Scan.active, uiDataGlobal.Scan.scanType);   /* чергування, покажчик B, рація на A -> B */
	setup(3, 3, 3, 7, 9, 7, 1, 1, 0, 2); dualSuspend(); printf("s3=%%d,%%d,%%d,%%d\n", onB, tunes, uiDataGlobal.Scan.active, uiDataGlobal.Scan.scanType);   /* виклик на B -> лишається на B */
	setup(3, 3, 3, 7, 9, 7, 1, 0, 1, 2); dualSuspend(); printf("s4=%%d,%%d,%%d,%%d\n", onB, tunes, uiDataGlobal.Scan.active, uiDataGlobal.Scan.scanType);   /* виклик на A -> лишається на A */
	/* R98 В6: B = VFO -- «лишитись на обраному» = вихід на VFO-екран (dualLeaveOnVfo), канальна гілка (dualLeaveOnB: зона, номер, завантаження) не чіпається */
	bVfo = 1; setup(3, 3, 3, 7, 9, 7, 1, 0, 1, 0); leaveVfo = 0; dualDisable(); printf("dv1=%%d,%%d,%%d,%%d,%%d\n", leaveVfo, enabled, loads, lastZ, uiDataGlobal.Scan.active);   /* чергування, покажчик на B (VFO) */
	bVfo = 1; setup(3, 3, 3, 7, 9, 7, 1, 1, 0, 2); leaveVfo = 0; dualDisable(); printf("dv2=%%d,%%d,%%d,%%d,%%d\n", leaveVfo, enabled, loads, lastZ, uiDataGlobal.Scan.active);   /* виклик на B (VFO) */
	bVfo = 1; setup(3, 3, 3, 7, 9, 7, 1, 0, 0, 0); leaveVfo = 0; dualDisable(); printf("dv3=%%d,%%d,%%d,%%d,%%d\n", leaveVfo, enabled, loads, lastZ, uiDataGlobal.Scan.active);   /* покажчик на A -- VFO-екран не відкривається */
	bVfo = 1; setup(3, 3, 3, 7, 9, 7, 0, 1, 0, 0); leaveVfo = 0; dualDisable(); printf("dv4=%%d,%%d,%%d,%%d,%%d\n", leaveVfo, enabled, loads, lastZ, uiDataGlobal.Scan.active);   /* режим зупинено меню на B (VFO) */
	bVfo = 1; setup(3, 3, 3, 7, 9, 7, 1, 0, 1, 0); dualSuspend(); printf("sv=%%d,%%d\n", onB, tunes);   /* dualSuspend на обраний B = VFO */
	bVfo = 0;
	setup(3, 3, 3, 7, 9, 8, 1, 0, 1, 0); dualSuspend(); printf("s5=%%d,%%d,%%d,%%d\n", onB, tunes, uiDataGlobal.Scan.active, uiDataGlobal.Scan.scanType);   /* покажчик на B, але B видалено -> A */
	return 0;
}
"""

ZONE_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#include <string.h>
#define DUAL_CHANNEL_HOST_TEST 1
#include "functions/dual_channel.h"
#include "%(dc)s"
typedef struct { uint16_t channels[80]; int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_highestIndex; int NOT_IN_CODEPLUGDATA_indexNumber; } zone_t;
static zone_t currentZone;
static uint8_t lastUsedChannelInZoneData[70];
static bool lastUsedChannelInZoneHasChanged;
static int running = 1, resumes = 0;
static uint32_t s_dualKeyMs = 5;
static bool dualIsRunning(void) { return running; }
static void dualAutoResume(void) { resumes++; }
static uint8_t codeplugAllChannelsCache[128];
static uint16_t chB = 0;
static int vt = 0;   /* R98: тип B (0 канал, 1 VFO A, 2 VFO B) */
uint16_t dcChannelB(void) { return chB; }
bool dcSetChannelB(uint16_t c, bool now) { (void)now; chB = c; vt = 0; return true; }
void dcSetTypeB(uint8_t t) { vt = t; }
bool dcBIsVfo(void) { return vt != 0; }
uint8_t dcTypeB(void) { return (uint8_t)vt; }
bool dcIsOnB(void) { return false; }
#define SEQ() (vt ? ((vt == 1) ? -1 : -2) : (int)chB)   /* канал -- номер; VFO A = -1, VFO B = -2 */
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
	/* крок B валкодером від 7: 10, 1024, 1 (обхід через край), 2, 5 (A більше не пропускається), 7 */
	int seq[8], k = 0;
	for (k = 0; k < 6; k++) { dualStepB(1); seq[k] = SEQ(); }
	printf("s1=%%d,%%d,%%d,%%d,%%d,%%d\n", seq[0], seq[1], seq[2], seq[3], seq[4], seq[5]);
	chB = 7; vt = 0; for (k = 0; k < 4; k++) { dualStepB(-1); seq[k] = SEQ(); }
	printf("s2=%%d,%%d,%%d,%%d\n", seq[0], seq[1], seq[2], seq[3]);       /* 5 (A не пропускається), 2, 1, 1024 */
	/* highestIndex < 1024: той самий обхід */
	setUse(1024); codeplugAllChannelsCache[127] = 0; allZone(10); chB = 10; vt = 0; dualStepB(1); printf("s3=%%d\n", SEQ());   /* VFO A (-1): після останнього каналу -- VFO */
	dualStepB(1); dualStepB(1); printf("s3b=%%d,%%d\n", SEQ(), vt);   /* VFO B -> перший канал (1), тип «канал» */
	vt = 2; dualStepB(-1); printf("s3c=%%d\n", SEQ());   /* від VFO B назад -- VFO A */
	dualStepB(-1); printf("s3d=%%d\n", SEQ());   /* від VFO A назад -- останній канал (10) */
	vt = 1; dualStepB(1); printf("s3e=%%d\n", SEQ());   /* від VFO A вперед -- VFO B */
	vt = 0;
	/* A збігається з B у «Всіх каналах» */
	chB = 5; printf("p1=%%d\n", dcCheckPair(dualChannelA(), chB, codeplugAllChannelsIndexIsInUse(chB)));   /* R97-FIX6: B==A -- OK=0 */
	/* B видалено (поза маскою) */
	chB = 6; printf("p2=%%d\n", dcCheckPair(dualChannelA(), chB, codeplugAllChannelsIndexIsInUse(chB)));   /* B_DELETED=2 */
	/* зона з каналами: A = channels[індекс] */
	memset(&currentZone, 0, sizeof(currentZone)); currentZone.NOT_IN_CODEPLUGDATA_indexNumber = 3; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = 3; currentZone.NOT_IN_CODEPLUGDATA_highestIndex = 3;
	currentZone.channels[0] = 2; currentZone.channels[1] = 7; currentZone.channels[2] = 10;
	codeplugSetLastUsedChannelInZone(3, 1); printf("z1=%%d\n", dualChannelA());           /* 7 */
	chB = 10; vt = 0; dualStepB(1); printf("z2=%%d\n", SEQ());                                       /* VFO A (з 10 вперед -- VFO, потім 2) */
	chB = 2; vt = 0; dualStepB(1); printf("z3=%%d\n", SEQ());                                       /* 7 (A не пропускається) */
	/* R97-FIX6: чергування не йде (A==B): після кроку B викликається dualAutoResume() і s_dualKeyMs скидається */
	allZone(1024); setUse(1024); codeplugSetLastUsedChannelInZone(-1, 5); chB = 5; running = 0; resumes = 0; s_dualKeyMs = 5; dualStepB(1);
	printf("n1=%%d,%%d,%%d\n", chB, resumes, (int)s_dualKeyMs); running = 1;
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
    fns = [carve_fn(t, s_) for s_ in ("static Channel_t dualChanOf(const CodeplugChannel_t *ch)", "static uint8_t dualVfoIdx(void)", "static _Bool dualBSameAsA(void)", "static void dualRenderHeader(_Bool force)", "_Bool uiChannelModeDualHeader(_Bool force)", "static void dualRenderScreen(void)", "static _Bool dualActivity(_Bool *cardB)", "static _Bool dualSingle(void)", "static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags)")]
    check(all(fns), "R97-FIX3: знайдено dualRenderHeader / uiChannelModeDualHeader / dualRenderScreen / dualActivity / dualSingle")
    if all(fns):
        pre = "static int directChannelNumber = 0;\nstatic _Bool dualIsRunning(void) { return (uiDataGlobal.Scan.active && (uiDataGlobal.Scan.scanType == SCAN_TYPE_DUAL_CHANNEL)); }\n"
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
            check(o.get("ets") == "1,0,1,0,0,1", "R98 Д2: ТС у шапці обраного каналу -- ефективний (контакт, ручне перекриття, перекриття ТГ), а не ТС запису каналу: %s" % o.get("ets"))
            check(o.get("vf") == "2,3,0,0,0,1|1,1,1,2|2,0", "R98 В3: картка B = VFO -- шапка з запису VFO (режим/смуга/CC), ефективний ТС питає ПРАВИЛЬНИЙ VFO (A=0, B=1), звичайної шапки нема, тип іде в рядок: %s" % o.get("vf"))
            check(o.get("rr00") == "1,0,0,0" and o.get("rr01") == "0,0,1,0", "FIX5/6 З2: чергування -- обраний (покажчик) інвертований, RX-мітки нема: %s / %s" % (o.get("rr00"), o.get("rr01")))
            check(o.get("rr20") == "1,1,0,0" and o.get("rr21") == "1,1,0,0", "FIX5/6 З2: активність на A -- мітка RX і S-метр на A (обраний = де активність, покажчик не важить): %s / %s" % (o.get("rr20"), o.get("rr21")))
            check(o.get("rr10") == o.get("rr20") and o.get("rr11") == o.get("rr21"), "FIX5/6 З2: коротка пауза вважається активністю: %s" % o.get("rr10"))
            check(o.get("rb") == "0,0,1,1", "FIX5/6 З2: активність на B -- мітка RX на B, обрана картка B: %s" % o.get("rb"))
            check(o.get("sg1") == "1,0,0,0" and o.get("sg2") == "0,0,1,1", "FIX6 З1/З2: A==B -- обраний за покажчиком, активність (несуча) -- на картці покажчика: %s / %s" % (o.get("sg1"), o.get("sg2")))
            check(o.get("sg3") == "1,1,1,0,0,0", "FIX6 З1/З2: A==B, виклик DMR -- активність і абонент на картці покажчика: %s" % o.get("sg3"))
            check(o.get("sg4") == "0,0", "FIX6 З1: режим вимкнено -- екран режиму без активності: %s" % o.get("sg4"))
            mut = [fns[0], fns[1], fns[2], fns[3].replace("uiUtilityRenderHeaderForChannel(&ov, force);", "uiUtilityRenderHeader(0, 0, force);"), fns[4], fns[5], fns[6], fns[7], fns[8]]
            mo = run_c(RS_HARNESS % {"fns": pre + "\n".join(mut)})
            check(fns[3] != mut[3] and mo is not None and dict(l.split("=", 1) for l in mo.split()).get("rs00") != o.get("rs00"), "п.2 (мутант): шапка з даних trx замість кодплага ловиться тестом (а)")
    # ---- R97-FIX3 п.1: вимкнення на B ----
    dsf = [carve_fn(t, s_) for s_ in ("static uint16_t dualZoneChannelAt(int pos, void *ctx)", "static _Bool dualBExists(void)", "static _Bool dualSelectedIsB(void)", "static void dualSuspend(void)",
                                      "static void dualLeaveOnB(void)", "static void dualDisable(void)")]
    check(all(dsf), "R97-FIX3/4: знайдено dualZoneChannelAt / dualSelectedIsB / dualSuspend / dualLeaveOnB / dualDisable")
    if all(dsf):
        pre = "static uint16_t dualZoneChannelAt(int pos, void *ctx);\n"
        mk = lambda fl: DIS_HARNESS % {"dc": os.path.join(APP, "source", "functions", "dual_channel.c"), "fns": pre + "\n".join(fl)}
        out = run_c(mk(dsf))
        check(out is not None, "R97-FIX3/4: хостова збірка вимкнення/зупинки на обраному")
        if out is not None:
            o = dict(l.split("=", 1) for l in out.split())
            # формат: зона last-used, значення, змін зони, сповіщень, завантажень каналу, onB, увімкнено, Scan.active, suspend, tune, currentZone
            exp = {"d1": "3,1,0,0,1,0,0,0,0,0,3", "d1b": "3,1,0,0,1,0,0,0,0,0,3", "d2": "-1,12,1,1,1,0,0,0,0,0,9", "d3": "-1,7,0,0,1,0,0,0,0,0,-1",
                   "d4": "-99,-99,0,0,0,0,0,0,0,1,3", "d4b": "-99,-99,0,0,0,0,0,0,0,0,3", "d5": "-99,-99,0,0,0,0,0,0,0,1,3",
                   "d6": "3,0,0,0,1,0,0,0,0,0,3", "d7": "-99,-99,0,0,0,0,0,0,0,1,3", "d8": "-99,-99,0,0,0,0,0,0,0,0,3"}
            names = {"d1": "виклик на B (покажчик на A), B у поточній зоні: last-used = позиція B, зона та сама, без сповіщення",
                     "d1b": "чергування, покажчик на B (рація фізично на A): вихід на B (за покажчиком)",
                     "d2": "B не з поточної зони: зона «Всі канали» (9), last-used(-1) = номер B, сповіщення",
                     "d3": "обраний B у зоні «Всі канали»: last-used(-1) = номер B, зона та сама",
                     "d4": "чергування, покажчик на A, рація на B: вихід на A", "d4b": "виклик на A (покажчик на B): лишаємось на A",
                     "d5": "обраний B, але B видалено: на A", "d6": "режим зупинено меню на B: лишаємось на B, позиція 0",
                     "d7": "рація на B без B (зіпсований стан): на A", "d8": "режим зупинено меню на A: лишаємось на A"}
            for k in exp:
                check(o.get(k) == exp[k], "FIX4 вимкнення %s -- %s: %s" % (k, names[k], o.get(k)))
            sx = {"s1": "0,1,0,0", "s2": "1,1,0,0", "s3": "1,0,0,0", "s4": "0,0,0,0", "s5": "0,0,0,0"}
            sn = {"s1": "чергування, покажчик A, рація на B -> зупинка на A", "s2": "чергування, покажчик B, рація на A -> зупинка на B", "s3": "виклик на B -> лишається на B",
                  "s4": "виклик на A -> лишається на A", "s5": "покажчик на B, але B видалено -> A"}
            for k in sx:
                check(o.get(k) == sx[k], "FIX4 dualSuspend %s -- %s (onB,tunes,active,scanType): %s" % (k, sn[k], o.get(k)))
            vx = {"dv1": "1,0,0,-99,0", "dv2": "1,0,0,-99,0", "dv3": "0,0,0,-99,0", "dv4": "1,0,0,-99,0", "sv": "1,1"}
            for k in vx:
                check(o.get(k) == vx[k], "R98 В6 (B = VFO) %s -- вихід на VFO-екран при обраному VFO, без канальної гілки (лічильник, увімкнено, завантажень, зона, active) / dualSuspend налаштовує VFO: %s" % (k, o.get(k)))
            for what, mut in (("«завжди A»", dsf[5].replace("_Bool stayB = dualSelectedIsB();", "_Bool stayB = 0;")),
                              ("«за станом рації замість обраного»", dsf[2].replace("dcPointerB()", "dcIsOnB()"))):
                fl = list(dsf); fl[5 if "stayB" in mut else 2] = mut
                mo = run_c(mk(fl))
                mm = dict(l.split("=", 1) for l in mo.split()) if mo else {}
                check(mut != (dsf[5] if "stayB" in mut else dsf[2]) and any(mm.get(k) != o.get(k) for k in list(exp) + list(sx) + list(vx)), "FIX4 (мутант): %s ловиться тестами" % what)
    check(src.count("dualDisable()") >= 2 and "dualLeaveOnB();" in src, "R97-FIX3: dualDisable викликається з dualSetMode(off) і dualAutoResume (помилка пари) -- через логіку обраного")
    m_red = re.search(r"case KEY_RED:(.*?)return true;", dk if False else src[src.find("static bool dualHandleKey(uiEvent_t *ev)\n{"):], re.S)
    check(m_red is not None and "dualDisable" not in m_red.group(1) and "dualSuspend" not in m_red.group(1) and "UpdateScreen" not in m_red.group(1),
          "FIX4 З1: червона в режимі нічого не робить (не вимикає режим)")
    hv = src[src.find("static void handleEvent(uiEvent_t *ev)\n{"):]
    hv = hv[:hv.find("if (uiDataGlobal.Scan.active && (ev->events & KEY_EVENT))")]
    check("dualSuspend();" in hv and re.search(r"if \(\(dcIsOnB\(\) != toB\) && \(ev->keys\.key != KEY_GREEN\) && \(KEYCHECK_LONGDOWN\(ev->keys, KEY_FRONT_DOWN\) == false\)\)\s*\{\s*dualTune\(toB\);", hv) is not None,
          "FIX4 З2 (R98-FIX5 А5): «чужі» клавіші -- на картку з покажчиком (було: на A), крім зеленої (меню) і довгого ▼ (вимкнення)")
    ro = src[src.find("// Покажчик на A -- звичайна зміна каналу зони"):]
    ro = ro[:ro.find("return true;")]
    ia, ib, ic, idd = ro.find("s_dualQuiet = true;"), ro.find("handleUpKey(ev);"), ro.find("s_dualQuiet = false;"), ro.find("dualAutoResume();")
    check(0 < ia < ib < ic < idd and "if (dcIsOnB())" in ro[:ia], "FIX4 З4: ручка на A -- UpdateScreen придушено на час кроку каналу (s_dualQuiet), знято до dualAutoResume; перед кроком рація на A")
    us = src[src.find("void uiChannelModeUpdateScreen(int txTimeSecs)\n{"):]
    check(re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)\s*if \(s_dualQuiet\)\s*\{\s*return;\s*\}\s*#endif", us[:600]) is not None,
          "FIX4 З4: uiChannelModeUpdateScreen() на початку виходить при s_dualQuiet (лише під DUAL_CHANNEL_ENABLED)")
    check(re.search(r"static bool\s+s_dualQuiet;", src) is not None and src.count("s_dualQuiet") == 9, "FIX4 З4: одна нова статична змінна (1 Б), s_dualQuiet (FIX5: 8 згадок; R98-FIX5 А3: +1 -- SK2 + ручка на A)")
    # ---- п.2: гаряча клавіша ----
    ev = src[src.find("static void handleEvent(uiEvent_t *ev)\n{"):src.find("static bool dualIsRunning(void)\n{")]
    hk = re.search(r"#if defined\(DUAL_CHANNEL_ENABLED\)\s*else if \(KEYCHECK_LONGDOWN\(ev->keys, KEY_FRONT_DOWN\) && \(KEYCHECK_LONGDOWN_REPEAT\(ev->keys, KEY_FRONT_DOWN\) == false\) &&\s*\(BUTTONCHECK_DOWN\(ev, BUTTON_SK2\) == 0\) && \(BUTTONCHECK_DOWN\(ev, BUTTON_SK1\) == 0\) && \(directChannelNumber == 0\)\)\s*\{[^}]*dualHotkeyToggle\(\);\s*return;\s*\}\s*#endif", ev)
    check(hk is not None, "п.2: handleEvent -- довге ▼ без SK2/SK1 (і без набору номера) викликає dualHotkeyToggle(), без автоповтору")
    dk = src[src.find("static bool dualHandleKey(uiEvent_t *ev)\n{"):src.find("// Увімкнути/вимкнути режим")]
    check("KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN)" in dk and "KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_FRONT_DOWN) == false" in dk and "dualHotkeyToggle();" in dk and
          "BUTTONCHECK_DOWN(ev, BUTTON_SK2) || BUTTONCHECK_DOWN(ev, BUTTON_SK1)" in dk,
          "п.2: dualHandleKey -- у режимі, що чергує, довге ▼ вимикає (без автоповтору; з SK2/SK1 -- не наше)")
    check("KEYCHECK_SHORTUP(ev->keys, KEY_DECREASE)" in ev and "KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN)" not in ev.replace(hk.group(0) if hk else "", "").replace("(KEYCHECK_LONGDOWN(ev->keys, KEY_FRONT_DOWN) == false)", ""),
          "п.2: коротке ▼ (KEY_DECREASE) без змін; довге ▼ більше ніде в handleEvent не використовується")
    check(len(re.findall(r"KEYCHECK_LONGDOWN\(ev->keys,\s*KEY_FRONT_UP", ev)) + len(re.findall(r"KEY_FRONT_UP\s*\n", ev)) >= 1 and "scanStart(true);" in ev,
          "п.2: довге ▲ (старт сканування зони) не зачеплено")
    fn = [carve_fn(t, s) for s in ("static void dualSetMode(_Bool on, _Bool notify)", "static void dualHotkeyToggle(void)", "static void dualQuickMenuApply(void)")]
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
            check(o.get("h4") == "1,0,0" and o.get("h5") == "0,1,1,1" and o.get("h7") == "0,1,0", "R97-FIX6: B видалено -- помилка; A==B -- без помилки, режим ввімкнено, сповіщення «вкл» і екран режиму (чергування не стартує); якщо чергування стартувало -- екран малює dualStart: %s / %s / %s" % (o.get("h4"), o.get("h5"), o.get("h7")))
            check(o.get("h6") == "1,1,0,2", "п.2: два довгі ▼ підряд -- вмикає, потім вимикає: %s" % o.get("h6"))
    # ---- п.3: «Всі канали» (-1) ----
    cp = pp(FW, incs, cf["DUALCH"], "application/source/functions/codeplug.c")
    zf = [carve_fn(t, s) for s in ("static uint16_t dualChannelA(void)", "static uint16_t dualZoneChannelAt(int pos, void *ctx)", "static uint8_t dualVfoIdx(void)", "static void dualStepB(int dir)")]
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
            check(o.get("s1") == "10,1024,-1,-2,1,2", "п.3 (R98 В8): «Всі канали» -- ручка B вгору: 10,1024,VFO A(-1),VFO B(-2),1,2 (замкнений цикл): %s" % o.get("s1"))
            check(o.get("s2") == "5,2,1,-2", "п.3 (R98 В8): «Всі канали» -- ручка B вниз від 7: 5(=A),2,1,а далі VFO B(-2) (в обидва боки): %s" % o.get("s2"))
            check(o.get("s3") == "-1" and o.get("s3b") == "1,0" and o.get("s3c") == "-1" and o.get("s3d") == "10" and o.get("s3e") == "-2",
                  "п.3 (R98 В8): після останнього каналу VFO A, далі VFO B, далі перший канал (тип «канал»); назад -- навпаки: %s,%s,%s,%s,%s" % (o.get("s3"), o.get("s3b"), o.get("s3c"), o.get("s3d"), o.get("s3e")))
            check(o.get("p1") == "0" and o.get("p2") == "2" and o.get("n1") == "7,1,0", "п.3 (R97-FIX6): «Всі канали» -- B=A не помилка (OK), видалений B -- помилка; зміна B без чергування викликає dualAutoResume і скидає s_dualKeyMs: %s/%s/%s" % (o.get("p1"), o.get("p2"), o.get("n1")))
            check(o.get("z1") == "7" and o.get("z2") == "-1" and o.get("z3") == "7", "п.3: звичайна зона -- A=channels[індекс], B по каналах зони: %s,%s,%s" % (o.get("z1"), o.get("z2"), o.get("z3")))
            check(o.get("e1") == "0", "п.3: порожня зона -- A=0 (режим не стартує): %s" % o.get("e1"))
            check(o.get("m1") == "7,2", "п.3: «останній канал» зони -1 і звичайної зони -- різні комірки: %s" % o.get("m1"))


Q_HARNESS = r"""
#include <stdio.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#include <stdint.h>
typedef struct { int dummy; } uiEvent_t;
enum { UI_CHANNEL_MODE = 5, UI_OTHER = 9 };
#define DUAL_RESUME_QUIET_MS 1000U
static bool s_dualQuiet;
static uint32_t s_dualKeyMs, g_now;
static int directChannelNumber, g_menu = UI_CHANNEL_MODE, g_en = 1, g_run = 0, g_scanActive = 0, g_det = 0, g_stock = 0, g_dual = 0, g_scn = 0;
struct { struct { int active; int toneActive; } Scan; int displayChannelSettings; } uiDataGlobal;
struct { int isEnabled; } monitorModeData;
static int trxTransmissionEnabled;
#define DC_CH_MIN 1
#define DC_CH_MAX 1024
static int g_chA = 1, g_chB = 2;
static uint16_t dcChannelB(void) { return (uint16_t)g_chB; }
static uint16_t dualChannelA(void) { return (uint16_t)g_chA; }
static bool codeplugAllChannelsIndexIsInUse(int c) { (void)c; return true; }
static int g_bVfo = 0;   /* R98: тип B (0 канал, 1/2 VFO) */
static bool dcBIsVfo(void) { return g_bVfo != 0; }
static uint8_t dcTypeB(void) { return (uint8_t)g_bVfo; }
static bool dcSameTarget(uint8_t ta, uint16_t ia, uint8_t tb, uint16_t ib) { return (ta == tb) && ((ta == 0) ? (ia == ib) : true); }
static bool dualSingle(void);
static bool dcIsEnabled(void) { return g_en; }
static bool dualIsRunning(void) { return g_run; }
static int menuSystemGetCurrentMenuNumber(void) { return g_menu; }
static uint32_t ticksGetMillis(void) { return g_now; }
static bool aprsModeIsActive(void) { return false; }
static bool dualHoldScreen(void);
static void dualQuietEnd(void);
void uiChannelModeUpdateScreen(int t)
{
	(void)t;
	if (s_dualQuiet) { return; }
	if ((dualIsRunning() || dualHoldScreen()) && (uiDataGlobal.displayChannelSettings == 0)) { g_dual++; } else { g_stock++; }
}
static int scenario;
static void handleEventCore(uiEvent_t *ev)
{
	(void)ev;
	s_dualKeyMs = g_now;
	if (g_en) { s_dualQuiet = true; }   // повторює хук: тиша на весь обробник
	switch (scenario)
	{
		case 0: uiChannelModeUpdateScreen(0); uiChannelModeUpdateScreen(0); uiChannelModeUpdateScreen(0); break;   // обробник кілька разів малює
		case 1: g_menu = UI_OTHER; break;                                                                          // відкрито інше меню
		case 2: uiDataGlobal.Scan.active = 1; uiChannelModeUpdateScreen(0); break;                                 // стартувало звичайне сканування
		case 3: uiChannelModeUpdateScreen(0); g_menu = UI_OTHER; break;                                            // малює і йде в меню
		case 4: directChannelNumber = 5; uiChannelModeUpdateScreen(0); break;                                      // цифра: набір номера
		case 5: break;                                                                                             // нічого не малює
		case 6: g_en = 0; uiChannelModeUpdateScreen(0); break;                                                     // обробник вимкнув режим
		default: break;
	}
}
%(fns)s
int main(void)
{
	for (int sc = 0; sc <= 6; sc++)
	{
		scenario = sc; s_dualQuiet = false; g_menu = UI_CHANNEL_MODE; g_en = 1; g_run = 0; uiDataGlobal.Scan.active = 0; directChannelNumber = 0;
		g_stock = g_dual = 0; g_now = 5000U; s_dualKeyMs = 0U;
		uiEvent_t e; handleEvent(&e);
		printf("k%%d=%%d,%%d,%%d\n", sc, (int)s_dualQuiet, g_stock, g_dual);
	}
	// вікно паузи: після клавіші 1 с екран режиму, потім стоковий (режим чекає); набраний номер тримає екран режиму
	scenario = 5; s_dualQuiet = false; g_menu = UI_CHANNEL_MODE; g_en = 1; g_run = 0; uiDataGlobal.Scan.active = 0; directChannelNumber = 0; g_now = 7000U; s_dualKeyMs = 0U;
	uiEvent_t e2; handleEvent(&e2);
	g_stock = g_dual = 0; g_now = 7500U; uiChannelModeUpdateScreen(0); int a1 = g_dual;
	g_now = 8100U; uiChannelModeUpdateScreen(0); int a2 = g_stock;
	directChannelNumber = 3; g_dual = 0; uiChannelModeUpdateScreen(0); int a3 = g_dual;
	g_en = 0; directChannelNumber = 0; g_now = 7500U; g_stock = 0; uiChannelModeUpdateScreen(0); int a4 = g_stock;
	g_en = 1; uiDataGlobal.displayChannelSettings = 1; g_stock = 0; g_dual = 0; uiChannelModeUpdateScreen(0); int a5 = g_stock;
	g_en = 1; uiDataGlobal.displayChannelSettings = 0; g_chB = g_chA; g_now = 9000U; g_dual = 0; uiChannelModeUpdateScreen(0); int a6 = g_dual; g_chB = 2;   /* A==B: екран режиму й поза вікном паузи */
	g_bVfo = 1; g_chB = g_chA; g_now = 9000U; g_dual = 0; g_stock = 0; uiChannelModeUpdateScreen(0); int a7 = g_stock; g_bVfo = 0; g_chB = 2;   /* R98 В4: канал A і VFO на B -- НЕ «однакові» (навіть з тим самим номером у запасі) */
	printf("w=%%d,%%d,%%d,%%d,%%d,%%d,%%d\n", a1, a2, a3, a4, a5, a6, a7);
	return 0;
}
"""


def test_fix5_z1(incs, cf):
    src = rd(os.path.join(APP, "source", "user_interface", "uiChannelMode.c"))
    t = pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    check(t is not None, "FIX5 З1: uiChannelMode.c препроцесується в DUALCH")
    if t is None:
        return
    # ---- структура ----
    ia = src.find("static void handleEventCore(uiEvent_t *ev)\n#else")
    ib = src.find("if (uiDataGlobal.Scan.active && (ev->events & KEY_EVENT))")
    hk = src[ia:ib]
    check(ia > 0 and "s_dualQuiet = true;" in hk and hk.find("dualSuspend();") < hk.find("s_dualQuiet = true;") < hk.find("dualTune(toB);"),
          "FIX5 З1: хук handleEventCore -- «тиша» вмикається після dualSuspend() і до будь-якої стокової обробки клавіші")
    check(re.search(r"static void handleEvent\(uiEvent_t \*ev\)\s*\{\s*uint16_t tsBefore = nonVolatileSettings\.tsManualOverride;\s*handleEventCore\(ev\);\s*dualVfoKeyDone\(ev, tsBefore\);\s*dualQuietEnd\(\);\s*\}", src) is not None,
          "FIX5 З1: handleEvent -- обгортка: handleEventCore (+ R98-FIX5 А5 dualVfoKeyDone) + dualQuietEnd() (єдиний вихід, жодного return повз скидання)")
    check(len(re.findall(r"\bhandleEvent\(ev\)", src)) == 1 and src.count("handleEventCore(ev);") == 1,
          "FIX5 З1: handleEvent викликається з тих самих місць (1 виклик у uiChannelMode), обгортка викликає Core")
    check(len(re.findall(r"s_dualQuiet = true;", src)) == 3 and len(re.findall(r"s_dualQuiet = false;", src)) == 2,
          "FIX5 З1: «тиша» вмикається у трьох місцях (ручка на A, хук, R98-FIX5 А3: SK2 + ручка на A -- стокова зміна зони), скидається у двох (ручка на A, dualQuietEnd)")
    us = src[src.find("void uiChannelModeUpdateScreen(int txTimeSecs)\n{"):]
    check(re.search(r"if \(\(dualIsRunning\(\) \|\| dualHoldScreen\(\)\) && \(uiDataGlobal\.displayChannelSettings == false\) && \(isTransmitting == false\)\)\s*\{\s*dualRenderScreen\(\);", us[:1400]) is not None,
          "FIX5 З1: UpdateScreen малює екран режиму і в паузі після клавіші (dualHoldScreen), а не лише під час чергування")
    qe = carve_fn(t, "static void dualQuietEnd(void)")
    hs = carve_fn(t, "static _Bool dualHoldScreen(void)") + "\n" + carve_fn(t, "static _Bool dualSingle(void)")
    check(qe is not None and hs is not None, "FIX5 З1: знайдено dualQuietEnd / dualHoldScreen")
    # ---- хост: обгортка + dualQuietEnd + dualHoldScreen (справжній код) ----
    he = carve_fn(t, "static void handleEvent(uiEvent_t *ev)")
    bsa = carve_fn(t, "static _Bool dualBSameAsA(void)") or ""
    if qe and hs and he and bsa:
        def mk(q, h, w):
            return Q_HARNESS % {"fns": "\n".join([bsa, h, q, w])}
        out = run_c(mk(qe, hs, he))
        check(out is not None, "FIX5 З1: хостова збірка обгортки/dualQuietEnd/dualHoldScreen")
        if out is not None:
            o = dict(l.split("=", 1) for l in out.split())
            exp = {"k0": "0,0,1", "k1": "0,0,0", "k2": "0,1,0", "k3": "0,0,0", "k4": "0,0,1", "k5": "0,0,1", "k6": "0,1,0"}
            nm = {"k0": "обробник малює тричі -- стокового 0, екран режиму рівно 1", "k1": "відкрито інше меню -- нічого не малюється (екран належить меню)",
                  "k2": "стартувало звичайне сканування -- один стоковий (екран сканування), екрана режиму нема",
                  "k3": "малює і йде в меню -- нічого", "k4": "цифра (набір номера) -- екран режиму з номером, стокового нема",
                  "k5": "обробник нічого не малює -- екран режиму перемальовано один раз", "k6": "обробник вимкнув режим -- один стоковий екран"}
            for k in exp:
                check(o.get(k) == exp[k], "FIX5 З1 клавіша %s (тиша,стокових,режиму): %s -- %s" % (k, nm[k], o.get(k)))
            check(all(o.get(k, "x").startswith("0,") for k in exp), "FIX5 З1 інваріант: після будь-якої клавіші s_dualQuiet == false")
            check(o.get("w") == "1,1,1,1,1,1,1", "FIX5/6 З1: пауза <1 с -- екран режиму; >1 с -- стоковий (режим чекає); набраний номер тримає екран режиму; режим вимкнено -- стоковий; деталі SK1 -- стоковий; A==B -- екран режиму без вікна паузи: %s" % o.get("w"))
            muts = (("тишу не знято", qe.replace("s_dualQuiet = 0;", "")),
                    ("екран наприкінці не малюється", qe.replace("uiChannelModeUpdateScreen(0);", "")),
                    ("малюється і в іншому меню", qe.replace("if (menuSystemGetCurrentMenuNumber() == UI_CHANNEL_MODE)", "if (1)")))
            for what, q2 in muts:
                mo = run_c(mk(q2, hs, he))
                mm = dict(l.split("=", 1) for l in mo.split()) if mo else {}
                check(q2 != qe and any(mm.get(k) != o.get(k) for k in exp), "FIX5 З1 (мутант): %s -- ловиться тестами" % what)
            mo = run_c(mk(qe, hs.replace("((directChannelNumber != 0) || ", "(0 || "), he))
            mm = dict(l.split("=", 1) for l in mo.split()) if mo else {}
            check(mm.get("w") != o.get("w") or mm.get("k4") != o.get("k4"), "FIX5 З1 (мутант): набраний номер не тримає екран режиму -- ловиться")


ROW_HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static unsigned char s_dualSqlB;   /* R98-FIX3 Б: перекриття шумодава B (dualTune/dualStepB/dualSetMode) */
#include <string.h>
#define DISPLAY_SIZE_X 160
#define DISPLAY_SIZE_Y 128
#define DISPLAY_Y_POS_BAR 10
#define DC_CH_MIN 1
#define DC_CH_MAX 1024
#define SMETER_S0 -129
#define RADIO_DEVICE_PRIMARY 0
#define CHANNEL_FLAG_BW_25K 1
#define CHANNEL_FLAG_TIMESLOT_TWO 2
enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
enum { FONT_SIZE_1 = 1, FONT_SIZE_3 = 3, FONT_SIZE_4 = 4 };
enum { TEXT_ALIGN_LEFT = 0 };
enum { THEME_ITEM_FG_DECORATION, THEME_ITEM_BG, THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_FG_CHANNEL_CONTACT, THEME_ITEM_FG_CHANNEL_CONTACT_INFO, THEME_ITEM_FG_DEFAULT, THEME_ITEM_FG_RSSI_BAR, THEME_ITEM_FG_RSSI_BAR_S9P };
static int directChannelNumber;   /* R98-FIX3 А: набору нема */
static void dualEntryText(char *l2, size_t n) { (void)l2; (void)n; }
static bool dcPointerB(void) { return false; }   /* R98-FIX3 А: покажчик для показу набору (набору тут нема) */
enum { CONTACT_DISPLAY_PRIO_CC_DB_TA, CONTACT_DISPLAY_PRIO_DB_CC_TA, CONTACT_DISPLAY_PRIO_TA_CC_DB };
enum { CONTACT_CALLTYPE_TG = 0, CONTACT_CALLTYPE_PC };
#define TG_CALL_FLAG 0x00
#define PC_CALL_FLAG 0x03
#define ALL_CALL_VALUE 16777215
#define SETTINGS_CHANNEL_MODE 0
#define SETTINGS_VFO_A_MODE 1
#define DC_TYPE_CHANNEL 0U
#define DC_TYPE_VFO_A 1U
#define DC_TYPE_VFO_B 2U
typedef int ContactCalltype_t;
typedef int CodeplugCSSTypes_t;
#define CSS_TYPE_NONE 1
#define CSS_TYPE_CTCSS 2
#define CSS_TYPE_DCS 0x8000
typedef struct { char name[16]; uint32_t rxFreq; uint8_t chMode; uint16_t contact; uint8_t txColor; uint16_t rxTone; uint16_t txTone; uint8_t flags; uint8_t encrypt; uint8_t rxGroupList; uint8_t NOT_IN_CODEPLUG_flag; } CodeplugChannel_t;
typedef struct { char name[16]; uint32_t tgNumber; uint8_t callType; uint8_t reserve1; } CodeplugContact_t;
#define CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE 0x01
#define CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK 0x02
typedef int Channel_t;
#define CHANNEL_CHANNEL 2
#define CHANNEL_VFO_A 0
#define CHANNEL_VFO_B 1
static int gMan = 0, gOv = 0, gUnD = 0, gUnA = 0, lines = 0, gLastChan = -1, gGetData = 0;
static void chkp(int x, int y);
int8_t tsGetManualOverride(Channel_t c) { gLastChan = c; return gMan; }
bool tsIsContactHasBeenOverridden(Channel_t c) { gLastChan = c; return gOv; }
static CodeplugChannel_t settingsVFOChannel[2];
unsigned uiUnreadCount(char k) { return (k == 'D') ? gUnD : ((k == 'A') ? gUnA : 0U); }
unsigned uiUnreadCountCard(bool cardB) { return cardB ? 0U : (unsigned)gUnD; }   /* R98-FIX1 Д: SMS DMR за карткою; на B власних SMS нема -- показується APRS */
void displayDrawLine(int a, int b, int c, int d, bool inv) { (void)inv; chkp(a, b); chkp(c, d); lines++; }
typedef struct { char contact[32]; char talkerAlias[32]; char talkgroup[17]; double locationLat, locationLon; } LinkItem_t;
#define LC_DIST_LABEL_SIZE 16
bool settingsLocationIsValid(void) { return false; }   /* R98-FIX2 К1: власної позиції нема -- відстань на картці не додається */
double settingsLocationGetLatitude(void) { return 0.0; }
double settingsLocationGetLongitude(void) { return 0.0; }
bool lcDistLabel(char *b, size_t n, bool ok, double a, double c, double d, double e, uint16_t *br, bool *bk) { (void)b; (void)n; (void)ok; (void)a; (void)c; (void)d; (void)e; (void)br; (void)bk; return false; }
struct { int contactDisplayPriority; uint32_t overrideTG; int currentIndexInTRxGroupList[3]; } nonVolatileSettings;
struct { char tg[8]; char pc[8]; char all_call[12]; } lang, *currentLanguage = &lang;
static LinkItem_t item; static LinkItem_t *LinkHead = &item;
static int rssi = -200, bad = 0, locks = 0, lockX = 0, lockY = 0;
static CodeplugChannel_t chans[1100]; static char used[1100]; static CodeplugContact_t cts[8];
static int cx0 = 0, cy0 = 0, cx1 = 159, cy1 = 127;
static char texts[40][40]; static int nt = 0, ntri = 0, litSeg = 0, outSeg = 0;
static void chk(int x, int y, int w, int h) { if (x < cx0 || y < cy0 || x + w - 1 > cx1 || y + h - 1 > cy1) bad++; }
static void chkp(int x, int y) { chk(x, y, 1, 1); }
bool codeplugAllChannelsIndexIsInUse(int ch) { return used[ch]; }
void codeplugChannelGetDataForIndex(int ch, CodeplugChannel_t *c) { gGetData++; *c = chans[ch]; }
int codeplugChannelGetFlag(CodeplugChannel_t *c, int f) { return (c->flags & f) != 0; }
bool codeplugContactGetDataForIndex(int i, CodeplugContact_t *c) { if (i <= 0 || i >= 8 || i == 7) { memset(c, 0, sizeof(*c)); memcpy(c->name, "TG 9            ", 16); c->tgNumber = 9; c->callType = CONTACT_CALLTYPE_TG; c->reserve1 = 0xff; return false; } *c = cts[i]; return true; }
uint32_t codeplugContactGetPackedId(CodeplugContact_t *c) { return (c->callType == CONTACT_CALLTYPE_PC) ? (c->tgNumber | ((uint32_t)PC_CALL_FLAG << 24)) : c->tgNumber; }
int codeplugRxGroupGetContactAt(int idx, int pos, int *num)
{
	static const int g1[2] = { 3, 2 };
	*num = 0;
	if (idx == 1) { *num = 2; return g1[(pos < 0 || pos >= 2) ? 0 : pos]; }
	return 0;   /* 0 -- списку нема; 2 -- порожній */
}
int codeplugContactIndexByTGorPC(uint32_t id, ContactCalltype_t t, CodeplugContact_t *c, uint8_t ts) { (void)ts; if (id == 91 && t == CONTACT_CALLTYPE_TG) { memset(c, 0, sizeof(*c)); memcpy(c->name, "TG Ukraine      ", 16); c->reserve1 = 0; return 1; } return -1; }
void codeplugUtilConvertBufToDisplayString(char *in, char *out, int len) { memcpy(out, in, len); out[len] = 0; for (int i = len - 1; i >= 0 && out[i] == ' '; i--) out[i] = 0; }
int codeplugGetCSSType(uint16_t t) { return ((t == 0xFFFF) || (t == 0)) ? CSS_TYPE_NONE : ((t & 0x8000) ? CSS_TYPE_DCS : CSS_TYPE_CTCSS); }
size_t dcsPrintf(char *d, size_t m, char *prefix, uint16_t tone) { (void)prefix; (void)tone; return (size_t)snprintf(d, m, "D023N"); }
char *chomp(char *s) { int n = strlen(s); while (n > 0 && s[n-1] == ' ') s[--n] = 0; return s; }
int uiChannelDataHasAes(CodeplugChannel_t *c) { return c->encrypt; }
void uiDrawAesIconAt(int x, int y) { locks++; lockX = x; lockY = y; chk(x, y, 10, 9); }
void displayThemeApply(int a, int b) { (void)a; (void)b; }
void displayThemeResetToDefault(void) {}
void displayDrawRect(int x, int y, int w, int h, bool inv) { (void)inv; chk(x, y, w, h); if (w == 10 && h == 10) outSeg++; }
void displayFillRect(int x, int y, int w, int h, bool inv) { (void)inv; chk(x, y, w, h); if (w == 10 && h == 10) litSeg++; }
void displayFillTriangle(int a, int b, int c, int d, int e, int f, bool inv) { (void)inv; chk(a, b, 1, 1); chk(c, d, 1, 1); chk(e, f, 1, 1); ntri++; }
int displayPrintCore(int x, int y, const char *t, int f, int al, bool inv)
{
	int w = (f == FONT_SIZE_1) ? 6 : (f == FONT_SIZE_3 ? 8 : 16), h = (f == FONT_SIZE_1) ? 8 : (f == FONT_SIZE_3 ? 16 : 32);
	(void)al; (void)inv;
	chk(x, y, (int)strlen(t) * w, h);   /* текст не обрізається: має вміститись у картку повністю */
	strncpy(texts[nt], t, 39); nt++;
	return 0;
}
int trxGetRSSIdBm(int d) { (void)d; return rssi; }
%(fns)s
static void reset(void) { nt = ntri = bad = litSeg = outSeg = locks = lines = 0; }
static void full(int y) { cx0 = 1; cy0 = y; cx1 = 158; cy1 = y + 56; }
int main(void)
{
	strcpy(lang.tg, "TG"); strcpy(lang.pc, "PC");
	for (int i = 1; i < 1100; i++) { memset(chans[i].name, 'W', 16); used[i] = 1; chans[i].rxFreq = 14550000U; chans[i].chMode = RADIO_MODE_ANALOG; chans[i].rxTone = 0xFFFF; chans[i].txTone = 0xFFFF; chans[i].txColor = 1; chans[i].flags = 0; chans[i].encrypt = 0; }
	used[1025] = 0;
	chans[1024].rxFreq = 44612500U; chans[1024].rxTone = 670; chans[1024].txTone = 670; chans[1024].flags = CHANNEL_FLAG_BW_25K;
	chans[5].chMode = RADIO_MODE_DIGITAL; chans[5].contact = 2; chans[5].txColor = 15; chans[5].flags = CHANNEL_FLAG_TIMESLOT_TWO; memcpy(cts[2].name, "TG Ukraine 255  ", 16);
	chans[6].chMode = RADIO_MODE_DIGITAL; chans[6].contact = 7;                       /* контакт не читається */
	chans[8].chMode = RADIO_MODE_DIGITAL; chans[8].contact = 3; memset(cts[3].name, ' ', 16); cts[3].tgNumber = 91;           /* ім'я порожнє -- «TG 91» */
	chans[9].chMode = RADIO_MODE_DIGITAL; chans[9].contact = 4; memset(cts[4].name, ' ', 16); cts[4].tgNumber = 1234; cts[4].callType = CONTACT_CALLTYPE_PC;
	chans[10].chMode = RADIO_MODE_DIGITAL; chans[10].contact = 0;                       /* контакт не заданий */
	chans[11].rxTone = 0x8000 | 023; chans[11].txTone = 0x8000 | 023; chans[11].flags = 0;                               /* FM DCS, 12.5k */
	chans[12].encrypt = 1;
	chans[13].chMode = RADIO_MODE_DIGITAL; chans[13].contact = 2; chans[13].rxGroupList = 1; chans[13].txColor = 1;   /* список прийому: [3, 2] */
	chans[14].chMode = RADIO_MODE_DIGITAL; chans[14].contact = 2; chans[14].rxGroupList = 2; chans[14].txColor = 1;   /* порожній список -> контакт каналу */
	cts[2].tgNumber = 255; cts[2].reserve1 = CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE; cts[3].reserve1 = CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;
	chans[15].chMode = RADIO_MODE_DIGITAL; chans[15].contact = 5; chans[15].txColor = 1; cts[5].tgNumber = 5; memcpy(cts[5].name, "TS2 contact     ", 16); cts[5].reserve1 = CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK;   /* канал TS1, контакт -> TS2 */
	chans[16].chMode = RADIO_MODE_DIGITAL; chans[16].contact = 6; chans[16].txColor = 1; chans[16].flags = CHANNEL_FLAG_TIMESLOT_TWO; cts[6].tgNumber = 6; memcpy(cts[6].name, "TS1 contact     ", 16); cts[6].reserve1 = 0;   /* канал TS2, контакт -> TS1 */ cts[3].callType = CONTACT_CALLTYPE_TG; strcpy(lang.all_call, "All call");
	/* r1: A, FM, 4-значний номер, 16-символьна назва, CTCSS 67.0, 25k; обраний + активний */
	full(11); reset(); dualRenderRow(11, false, 1024, 0, true, true, false);
	printf("r1=%%d,%%d,%%d|%%s|%%s|%%s|%%s|%%d,%%d\n", bad, ntri, nt, texts[1], texts[2], texts[3], texts[4], litSeg, outSeg);
	full(71); reset(); dualRenderRow(71, true, 5, 0, false, false, false);
	printf("r2=%%d,%%d,%%d|%%s|%%s|%%s\n", bad, ntri, nt, texts[1], texts[2], texts[3]);
	strcpy(item.contact, "ID:1234567"); strcpy(item.talkerAlias, "ABCDEFGHIJKLMNOP"); strcpy(item.talkgroup, "TG 9123456789012"); nonVolatileSettings.contactDisplayPriority = CONTACT_DISPLAY_PRIO_TA_CC_DB;
	reset(); dualRenderRow(71, true, 5, 0, true, true, true);
	printf("r3=%%d,%%d|%%s|%%s\n", bad, nt, texts[2], texts[3]);
	reset(); dualRenderRow(71, true, 1025, 0, false, false, false);
	printf("r4=%%d|%%s|%%s|%%s\n", bad, texts[1], texts[2], texts[3]);
	reset(); dualRenderRow(71, true, 6, 0, false, false, false); printf("r5=%%d|%%s\n", bad, texts[2]);
	reset(); dualRenderRow(71, true, 8, 0, false, false, false); printf("r6=%%d|%%s\n", bad, texts[2]);
	reset(); dualRenderRow(71, true, 9, 0, false, false, false); printf("r7=%%d|%%s\n", bad, texts[2]);
	reset(); dualRenderRow(71, true, 10, 0, false, false, false); printf("r8=%%d|%%s|%%s\n", bad, texts[2], texts[3]);
	reset(); dualRenderRow(71, true, 11, 0, false, false, false); printf("r9=%%d|%%s|%%s\n", bad, texts[2], texts[3]);
	reset(); dualRenderRow(71, true, 3, 0, false, false, false); printf("r10=%%d|%%s\n", bad, texts[3]);
	nonVolatileSettings.currentIndexInTRxGroupList[0] = 0; reset(); dualRenderRow(71, true, 13, 0, false, false, false); printf("g0=%%d|%%s|%%s\n", bad, texts[2], texts[3]);
	nonVolatileSettings.currentIndexInTRxGroupList[0] = 1; reset(); dualRenderRow(71, true, 13, 0, false, false, false); printf("g1=%%d|%%s|%%s\n", bad, texts[2], texts[3]);
	nonVolatileSettings.currentIndexInTRxGroupList[0] = 9; reset(); dualRenderRow(71, true, 13, 0, false, false, false); printf("g9=%%d|%%s\n", bad, texts[2]);
	nonVolatileSettings.currentIndexInTRxGroupList[0] = 0; reset(); dualRenderRow(71, true, 14, 0, false, false, false); printf("g2=%%d|%%s\n", bad, texts[2]);
	nonVolatileSettings.overrideTG = 91; reset(); dualRenderRow(71, true, 5, 0, true, false, false); printf("o1=%%d|%%s|%%s\n", bad, texts[2], texts[3]);
	reset(); dualRenderRow(71, true, 5, 0, false, false, false); printf("o2=%%d|%%s|%%s\n", bad, texts[2], texts[3]);
	nonVolatileSettings.overrideTG = ((uint32_t)PC_CALL_FLAG << 24) | 2550213U; reset(); dualRenderRow(71, true, 5, 0, true, false, false); printf("o3=%%d|%%s|%%s\n", bad, texts[2], texts[3]);
	nonVolatileSettings.overrideTG = ALL_CALL_VALUE; reset(); dualRenderRow(71, true, 5, 0, true, false, false); printf("o4=%%d|%%s|%%s\n", bad, texts[2], texts[3]);
	nonVolatileSettings.overrideTG = 0;
	/* Д3: хост-модель PTT -- стокове завантаження каналу (uiChannelModeLoadChannelData ~844-863) окремо від dualDestination: пакований ТГ/ПК, що піде в ефір */
	{
		int mism = 0, total = 0;
		int chs[8] = { 5, 6, 8, 9, 10, 13, 14, 15 };
		uint32_t ovs[3] = { 0, 91, ((uint32_t)PC_CALL_FLAG << 24) | 2550213U };
		for (int ci = 0; ci < 8; ci++)
			for (int oi = 0; oi < 3; oi++)
				for (int idx = 0; idx < 3; idx++)
				{
					CodeplugChannel_t *c = &chans[chs[ci]];
					CodeplugContact_t k;
					int num, gc = codeplugRxGroupGetContactAt(c->rxGroupList, idx, &num);
					uint32_t want, got; char nm[17]; bool no; uint8_t fl;
					nonVolatileSettings.currentIndexInTRxGroupList[0] = idx;
					nonVolatileSettings.overrideTG = ovs[oi];
					if (gc != 0 && idx < num) (void)codeplugContactGetDataForIndex(gc, &k);   /* стоково: група дійсна й індекс у списку -- контакт групи (поза списком load скидає індекс у 0) */
					else if (gc != 0) (void)codeplugContactGetDataForIndex(gc, &k);
					else (void)codeplugContactGetDataForIndex(c->contact, &k);
					want = (ovs[oi] != 0) ? ovs[oi] : codeplugContactGetPackedId(&k);
					got = dualDestination(c, nm, &no, &fl);
					total++; if (want != got) mism++;
				}
		nonVolatileSettings.overrideTG = 0; nonVolatileSettings.currentIndexInTRxGroupList[0] = 0;
		printf("ptt=%%d,%%d\n", mism, total);
	}
	/* Д2: ефективний ТС */
	reset(); dualRenderRow(71, true, 15, 0, false, false, false); printf("t1=%%s\n", texts[3]);   /* контакт TS2, канал TS1 */
	reset(); dualRenderRow(71, true, 16, 0, false, false, false); printf("t2=%%s\n", texts[3]);   /* контакт TS1, канал TS2 */
	reset(); dualRenderRow(71, true, 5, 0, false, false, false); printf("t3=%%s\n", texts[3]);    /* NO_TS_OVERRIDE: ТС каналу (TS2) */
	gMan = 1; gOv = 0; reset(); dualRenderRow(71, true, 5, 0, false, false, false); printf("t4=%%s\n", texts[3]);   /* ручне перекриття ТС каналу -> TS1 */
	gMan = 1; gOv = 1; reset(); dualRenderRow(71, true, 15, 0, false, false, false); printf("t5=%%s\n", texts[3]);   /* контакт перекрито вручну -> TS1 */
	gMan = 0; gOv = 1; reset(); dualRenderRow(71, true, 15, 0, false, false, false); printf("t6=%%s\n", texts[3]);   /* прапор «перекрито» без значення -> за контактом TS2 */
	gMan = 0; gOv = 0; nonVolatileSettings.overrideTG = 91; reset(); dualRenderRow(71, true, 15, 0, false, false, false); printf("t7=%%s\n", texts[3]); nonVolatileSettings.overrideTG = 0;   /* перекриття ТГ: ТС контакту не діє -> ТС каналу TS1 */
	/* Д1: конверт непрочитаних у квадраті літери */
	full(11); gUnD = 3; reset(); dualRenderRow(11, false, 3, 0, false, false, false); printf("u1=%%d,%%d,%%d,%%s\n", bad, lines, outSeg, texts[nt - 1]);
	gUnD = 0; gUnA = 12; reset(); dualRenderRow(11, false, 3, 0, true, false, false); printf("u2=%%d,%%d\n", bad, lines);   /* A -- лише на картці B */
	full(71); reset(); dualRenderRow(71, true, 3, 0, true, false, false); { int ap = 0; for (int i = 0; i < nt; i++) { if (strcmp(texts[i], "A+") == 0) { ap = 1; } } printf("u3=%%d,%%d,%%d\n", bad, lines, ap); }   /* R98-FIX2 Д3: APRS -- інвертований значок «A»+число праворуч у рядку 1, без конверта */
	gUnA = 0; reset(); dualRenderRow(71, true, 3, 0, false, false, false); printf("u4=%%d,%%d\n", bad, lines);
	reset(); dualRenderRow(71, true, 12, 0, false, false, false); printf("k1=%%d,%%d,%%d,%%d\n", bad, locks, lockX, lockY);
	reset(); dualRenderRow(71, true, 3, 0, false, false, false); printf("k2=%%d\n", locks);
	/* R98 В3: картка B = VFO -- «VFO A»/«VFO B», дані прямо із запису VFO (без читання кодплага), ТГ за списком VFO (SETTINGS_VFO_A_MODE+VFO), ТС -- VFO */
	memset(&settingsVFOChannel[0], 0, sizeof(CodeplugChannel_t)); memset(&settingsVFOChannel[1], 0, sizeof(CodeplugChannel_t));
	settingsVFOChannel[0].chMode = RADIO_MODE_DIGITAL; settingsVFOChannel[0].rxFreq = 43012500U; settingsVFOChannel[0].rxGroupList = 1; settingsVFOChannel[0].contact = 5; settingsVFOChannel[0].txColor = 7; settingsVFOChannel[0].NOT_IN_CODEPLUG_flag = 0x01; settingsVFOChannel[0].encrypt = 1;
	settingsVFOChannel[1].chMode = RADIO_MODE_ANALOG; settingsVFOChannel[1].rxFreq = 14550000U; settingsVFOChannel[1].rxTone = 0xFFFF; settingsVFOChannel[1].txTone = 0xFFFF; settingsVFOChannel[1].NOT_IN_CODEPLUG_flag = 0x03; settingsVFOChannel[1].flags = CHANNEL_FLAG_BW_25K;
	nonVolatileSettings.currentIndexInTRxGroupList[1] = 1; nonVolatileSettings.currentIndexInTRxGroupList[2] = 0; nonVolatileSettings.currentIndexInTRxGroupList[0] = 0;
	full(71); gGetData = 0; gLastChan = -1; locks = 0; reset(); dualRenderRow(71, true, 5, DC_TYPE_VFO_A, true, false, false);
	printf("va=%%d,%%d,%%d,%%d|%%s|%%s|%%s\n", bad, gGetData, gLastChan, locks, texts[1], texts[2], texts[3]);   /* ТГ -- 2-й у групі VFO A (контакт 2 = «TG Ukraine 255», NO_TS_OVERRIDE -> TS1 з запису VFO) */
	nonVolatileSettings.currentIndexInTRxGroupList[1] = 0; reset(); dualRenderRow(71, true, 5, DC_TYPE_VFO_A, false, false, false);
	printf("vb=%%d|%%s|%%s\n", bad, texts[2], texts[3]);   /* перший у групі: контакт 3 («TG 91»; NO_TS_OVERRIDE) */
	nonVolatileSettings.currentIndexInTRxGroupList[1] = 1; gLastChan = -1; reset(); dualRenderRow(71, true, 5, DC_TYPE_VFO_B, false, false, false);
	printf("vc=%%d,%%d|%%s|%%s|%%s\n", bad, gLastChan, texts[1], texts[2], texts[3]);   /* VFO B -- FM: «VFO B», частота в рядку 2, смуга 25k, без прочерків */
	settingsVFOChannel[1].rxTone = 670; settingsVFOChannel[1].txTone = 670; reset(); dualRenderRow(71, true, 5, DC_TYPE_VFO_B, false, false, false);
	printf("vd=%%d|%%s\n", bad, texts[3]);   /* CTCSS + смуга */
	gMan = 2; gOv = 0; reset(); dualRenderRow(71, true, 5, DC_TYPE_VFO_A, false, false, false);
	printf("ve=%%s\n", texts[3]); gMan = 0;   /* ручне перекриття ТС цього VFO -> TS2 */
	nonVolatileSettings.currentIndexInTRxGroupList[1] = 0;
	/* S-метр активної картки: (виходів,залито,контурних) */
	for (int k = 0; k < 6; k++)
	{
		int v[6] = { -200, -130, -125, -109, -93, -20 };
		rssi = v[k]; full(11); reset(); dualRenderRow(11, false, 3, 0, false, true, false);
		printf("m%%d=%%d,%%d,%%d\n", k, bad, litSeg, outSeg);
	}
	reset(); dualRenderRow(11, false, 3, 0, false, false, false); printf("m9=%%d,%%d,%%d\n", bad, litSeg, outSeg);   /* неактивна -- без смуги */
	return 0;
}
"""


def test_fix7_a1():
    """А1 (R97-FIX7): верхня лінія картки A (y=DW_CARD_A_Y) не затирається шапкою. Модель кадрового буфера + інваріанти меж заливки."""
    ui = rd(os.path.join(APP, "source", "user_interface", "uiChannelMode.c"))
    am = rd(os.path.join(APP, "source", "applicationMain.c"))
    uu = rd(os.path.join(APP, "source", "user_interface", "uiUtilities.c"))
    barY = int(re.search(r"#define DISPLAY_Y_POS_BAR\s+(\d+)", rd(os.path.join(APP, "include", "hardware", "HX8353E_display.h"))).group(1)) if os.path.exists(os.path.join(APP, "include", "hardware", "HX8353E_display.h")) else 10
    cardY = barY + 1
    check(re.search(r"#define DW_CARD_A_Y\s+\(DISPLAY_Y_POS_BAR \+ 1\)", ui) is not None, "FIX7 А1: верх картки A = DISPLAY_Y_POS_BAR + 1 (=%d)" % cardY)
    # (1) заливка у applicationMain.c на екрані режиму -- лише DISPLAY_Y_POS_BAR, 14 px -- лише поза ним
    i = am.find("if ((currentMenu == UI_CHANNEL_MODE) && uiChannelModeDualScreenShown())")
    j = am.find("displayFillRect(0, 0, DISPLAY_SIZE_X, 14, true);", i)
    seg = am[i:j] if (i >= 0 and j > i) else ""
    check(i >= 0 and "displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_Y_POS_BAR, true);" in seg and seg.count("else") == 1,
          "FIX7 А1: headerRowIsDirty на екрані режиму заливає лише рядок шапки (DISPLAY_Y_POS_BAR), а не 14 px")
    # (2) uiUtilityRedrawHeaderOnly: гілка екрана режиму до стокових clearRows(0,2)
    k = uu.find("void uiUtilityRedrawHeaderOnly(")
    body = uu[k:uu.find("\n}\n", k)]
    d = body.find("uiChannelModeDualScreenShown()")
    c = body.find("displayClearRows(0, 2, false)")
    check(d >= 0 and c > d and "displayFillRect(0, 0, DISPLAY_SIZE_X, DISPLAY_Y_POS_BAR, true);" in body[d:c] and "return;" in body[d:c],
          "FIX7 А1: uiUtilityRedrawHeaderOnly на екрані режиму чистить лише DISPLAY_Y_POS_BAR і виходить до displayClearRows(0,2)")
    # (3) тік RSSI: clearRows(0,2) лише коли екран режиму не показано
    t = ui.find("displayClearRows(0, 2, false)")
    check(t > 0 and "uiChannelModeDualScreenShown() == false" in ui[max(0, t - 400):t], "FIX7 А1: RSSI-тік не чистить рядки 0..2 на екрані режиму")
    # (4) модель кадрового буфера: порядок «картки -> заливки шапки з обох шляхів -> шапка» лінію y=cardY не чіпає
    W, H = 160, 128
    buf = [[0] * W for _ in range(H)]
    for x in range(1, 159):
        buf[cardY][x] = 1                       # верхня лінія картки A
    def fill(h):
        for y in range(min(h, H)):
            for x in range(W):
                buf[y][x] = 0
    fill(barY)                                 # applicationMain / RedrawHeaderOnly на екрані режиму
    fill(barY)                                 # ядро шапки (uiUtilityRenderHeaderCore: displayFillRect(0,0,W,DISPLAY_Y_POS_BAR))
    check(all(buf[cardY][x] == 1 for x in range(1, 159)), "FIX7 А1 (модель): після заливок шапки верхня лінія картки A (y=%d) ціла" % cardY)
    fill(14)                                   # старий шлях -- мутант: лінію стирає
    check(not all(buf[cardY][x] == 1 for x in range(1, 159)), "FIX7 А1 (мутант моделі): стара заливка 14 px стирає лінію -- модель це ловить")
    cs = re.search(r"displayFillRect\(0, 0, DISPLAY_SIZE_X, DISPLAY_Y_POS_BAR, true\);", uu[uu.find("static void uiUtilityRenderHeaderCore"):])
    check(cs is not None, "FIX7 А1: ядро шапки чистить рівно DISPLAY_Y_POS_BAR рядків (y=0..%d)" % (barY - 1))


def test_fix5_z2(incs, cf):
    src = rd(os.path.join(APP, "source", "user_interface", "uiChannelMode.c"))
    t = pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c")
    check(t is not None, "FIX6 З2/З3: uiChannelMode.c препроцесується в DUALCH")
    if t is None:
        return
    if "#define DW_SQ_X" not in src:
        print("ПРОПУСК: FIX6 З2/З3 -- розкладку карток R97-FIX6 (квадрат з літерою 16x32, 3 рядки) замінено (R98-FIX5 Б2 -- 5 рядків, R98-FIX6 Г -- 4 рядки); показ і координати перевіряє tools/test_r98fix6.py")
        return
    # ---- геометрія з макросів (кожна константа -- з коду) ----
    D = {"DISPLAY_Y_POS_BAR": 10}
    for m in re.finditer(r"^#define (DW_\w+)\s+(.+?)(?:\s*//.*)?$", src, re.M):
        try:
            D[m.group(1)] = int(eval(re.sub(r"\b(DW_\w+|DISPLAY_Y_POS_BAR)", lambda x: str(D[x.group(1)]), m.group(2).strip())))
        except Exception:
            pass
    need = ["DW_UN_DY", "DW_UN_LETTER_X", "DW_UN_ENV_X", "DW_UN_NUM_X", "DW_CARD_X", "DW_CARD_W", "DW_CARD_H", "DW_CARD_A_Y", "DW_CARD_B_Y", "DW_SQ_X", "DW_SQ_W", "DW_SQ_DY", "DW_SQ_H", "DW_LETTER_X", "DW_LETTER_DY", "DW_ARROW_DY", "DW_TXT_X",
            "DW_LINE1_DY", "DW_LINE2_DY", "DW_LINE3_DY", "DW_LINE3_MAX", "DW_LOCK_X", "DW_LOCK_DY", "DW_METER_DY", "DW_METER_H", "DW_TAG_W", "DW_METER_X", "DW_METER_SEG_W", "DW_METER_STEP", "DW_METER_SEGS"]
    check(all(k in D for k in need), "FIX6 З2: усі геометричні константи DW_* знайдено й обчислено")
    if not all(k in D for k in need):
        return
    g = type("G", (), D)
    cardR = g.DW_CARD_X + g.DW_CARD_W - 1
    check(g.DW_CARD_A_Y == 11 and g.DW_CARD_A_Y > 9, "FIX6 З2: картки починаються одразу під шапкою (текст шапки y=0..9 = DISPLAY_Y_POS_BAR-1)")
    check(g.DW_CARD_B_Y >= g.DW_CARD_A_Y + g.DW_CARD_H + 1 and g.DW_CARD_B_Y + g.DW_CARD_H == 128, "FIX6 З2: картки без накладання; B закінчується на останньому рядку екрана (y=127)")
    check(g.DW_SQ_X >= g.DW_CARD_X + 1 and g.DW_SQ_X + g.DW_SQ_W <= g.DW_TXT_X and g.DW_SQ_DY >= 1 and g.DW_SQ_DY + g.DW_SQ_H <= g.DW_CARD_H - 1,
          "FIX6 З2: квадрат з літерою всередині картки й лівіше тексту")
    check(g.DW_LETTER_X >= g.DW_SQ_X and g.DW_LETTER_X + 16 <= g.DW_SQ_X + g.DW_SQ_W and g.DW_LETTER_DY + 32 <= g.DW_ARROW_DY and g.DW_ARROW_DY + 5 <= g.DW_SQ_DY + g.DW_SQ_H,
          "FIX6 З2: літера 16x32 у квадраті, ▸ (5 px) під літерою й у квадраті")
    check(g.DW_TXT_X + 21 * 6 - 1 <= cardR - 1, "FIX6 З3: рядок 1 -- номер (до 4 цифр) + пробіл + 16 символів назви = 21 символ FONT_SIZE_1 -- вміщується в картку")
    check(g.DW_TXT_X + 16 * 8 - 1 <= cardR - 1, "FIX6 З3: рядок 2 -- 16 символів FONT_SIZE_3 вміщується в картку")
    check(g.DW_TXT_X + g.DW_LINE3_MAX * 6 <= g.DW_LOCK_X, "FIX6 З3: рядок 3 (до 19 символів FONT_SIZE_1) не заходить на замок AES")
    check(g.DW_LOCK_X + 10 <= cardR and g.DW_LOCK_DY + 9 <= g.DW_METER_DY and g.DW_LOCK_DY >= g.DW_LINE3_DY - 1, "FIX6 З2: замок AES (10x9) у картці, у рядку 3, над смугою активності")
    check(g.DW_LINE1_DY + 8 <= g.DW_LINE2_DY and g.DW_LINE2_DY + 16 <= g.DW_LINE3_DY and g.DW_LINE3_DY + 8 <= g.DW_METER_DY and g.DW_METER_DY + g.DW_METER_H <= g.DW_CARD_H - 1,
          "FIX6 З3: рядки 1 (8), 2 (16), 3 (8) і смуга активності (10) не перетинаються й лишаються в картці")
    check(g.DW_TXT_X + g.DW_TAG_W <= g.DW_METER_X and g.DW_METER_X + (g.DW_METER_SEGS - 1) * g.DW_METER_STEP + g.DW_METER_SEG_W - 1 <= cardR - 1 and g.DW_METER_SEG_W <= g.DW_METER_STEP,
          "FIX6 З2: мітка RX і 9 сегментів S-метра в межах картки без накладання")
    check("DW_SEP_Y" not in src and "dualRenderStatus" not in src and "dual_rx_on" not in src.replace("// ", "") .split("static void dualCallerText")[0] + "x" and
          "currentLanguage->dual_rx_on" not in src and "currentLanguage->dual_wait" not in src,
          "FIX6 З2: нижній рядок і роздільник прибрано (dual_rx_on/dual_wait у коді не використовуються)")
    check("uiDrawAesEnabledIcon();" not in src[src.find("static void dualRenderScreen(void)\n{"):], "FIX6 З2: замок AES шапки (x=147,y=14) у dualRenderScreen не малюється -- він у картці")
    # ---- хост: справжні dualRenderRow / dualMeterRow / dualCallerText ----
    fn = [carve_fn(t, s_) for s_ in ("static Channel_t dualChanOf(const CodeplugChannel_t *ch)", "static void dualCallerText(char *text17)", "static void dualMeterRow(int16_t y)", "static uint32_t dualDestination(const CodeplugChannel_t *ch, char *out, _Bool *numOnly, uint8_t *tsFlags)", "static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags)",
                                     "static size_t dualToneOne(char *dst, size_t size, const char *mark, uint16_t tone)", "static void dualFmToneLine(char *l3, size_t size, uint16_t rxTone, uint16_t txTone, _Bool bw25)",   # R98-FIX2 К2
                                     "static void dualRenderRow(int16_t y, _Bool isB, uint16_t ch, uint8_t vfoType, _Bool selected, _Bool active, _Bool callerHere)")]
    fda = carve_fn(t, "static void dualAppendDistance(char *l3)")   # R98-FIX2 К1 (лише з LC_DISTANCE)
    if fda:
        fn.insert(-1, fda)
    check(all(fn), "FIX6 З3: знайдено dualCallerText / dualMeterRow / dualDestination / dualRenderRow")
    if not all(fn):
        return
    defs = "".join(l + "\n" for l in (src[src.find("#define DW_CARD_X"):src.find("// Текст абонента")]).splitlines() if l.startswith("#define"))
    defs = defs.replace("DISPLAY_Y_POS_BAR", "10")
    out = run_c(ROW_HARNESS % {"fns": defs + "\n".join(fn)})
    check(out is not None, "FIX6 З3: хостова збірка карток")
    if out is None:
        return
    o = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
    f = lambda k: o.get(k, "").split("|")
    r1 = f("r1")
    check(r1[0].split(",")[:3] == ["0", "1", "5"] and r1[1] == "1024 " + "W" * 16 and r1[2] == "FM 446.12500" and r1[3] == "67.0 25k" and r1[4] == "RX",
          "FIX6 З3 (r1): A=1024, 16-символьна назва, FM: ряд 1 «1024 WWWW…», ряд 2 «FM 446.12500», ряд 3 «67.0 25k» (R98-FIX2 К2: однакові RX/TX -- один тон), мітка RX, ▸ є, нічого не виходить за картку: %s" % o.get("r1"))
    r2 = f("r2")
    check(r2[0].split(",")[:3] == ["0", "0", "4"] and r2[1] == "5 " + "W" * 16 and r2[2] == "TG Ukraine 255" and r2[3] == "TS2 CC15 TG255",
          "FIX6 З3 (r2): неактивна DMR-картка -- контакт каналу, «TS2 CC15 ТГ255», без ▸ і RX: %s" % o.get("r2"))
    r3 = f("r3")
    check(r3[0].split(",")[:2] == ["0", "5"] and r3[1] == "ABCDEFGHIJKLMNOP" and r3[2] == "TS2 CC15 TG 9123456",
          "FIX6 З3 (r3): виклик -- 16-символьний абонент у рядку 2; рядок 3 -- «TS2 CC15 ТГ виклику», обрізаний до 19 символів: %s" % o.get("r3"))
    r4 = f("r4")
    check(r4[0] == "0" and r4[1] == "1025" and r4[2] == "" and r4[3] == "", "FIX7 А3: неіснуючий канал -- лише номер, рядки 2-3 порожні, без «---»: %s" % o.get("r4"))
    check(f("r5") == ["0", "TG 9"], "FIX7 А2: DMR, контакт каналу недійсний -- рація передає на ТГ 9 (запасний контакт codeplugContactGetDataForIndex), так і показано: %s" % o.get("r5"))
    check(f("r6") == ["0", "TG 91"], "FIX7 А2: DMR, ім'я контакту порожнє -- «TG 91»: %s" % o.get("r6"))
    check(f("r7") == ["0", "PC 1234"], "FIX7 А2: DMR, контакт приватний без імені -- «PC 1234»: %s" % o.get("r7"))
    check(f("r8") == ["0", "TG 9", "TS1 CC1 TG9"], "FIX7 А2/А3: DMR, контакт не заданий -- «TG 9» (реальне призначення), рядок 3 «TS1 CC1 TG9», без «--»: %s" % o.get("r8"))
    check(f("r9") == ["0", "FM 145.50000", "D023N 12.5k"], "FIX6 З3 (r9): FM DCS -- «D023N 12.5k» (R98-FIX2 К2): %s" % o.get("r9"))
    check(f("r10") == ["0", "12.5k"], "FIX7 А3: FM без тону -- лише смуга «12.5k», без прочерка: %s" % o.get("r10"))
    check(f("g0") == ["0", "TG 91", "TS1 CC1"] and f("g1") == ["0", "TG Ukraine 255", "TS1 CC1 TG255"] and f("g9") == ["0", "TG 91"] and f("g2") == ["0", "TG Ukraine 255"],
          "FIX7 А2: список прийому каналу -- контакт на позиції індексу ТГ (поза списком -> перший); порожній список -> контакт каналу: %s %s %s %s" % (o.get("g0"), o.get("g1"), o.get("g9"), o.get("g2")))
    check(f("o1") == ["0", "TG Ukraine", "TS2 CC15 TG91"] and f("o2") == ["0", "TG Ukraine", "TS2 CC15 TG91"],
          "R98 Д3: перекриття ТГ глобальне -- PTT з будь-якої картки піде з ним, тож обидві DMR-картки його показують: %s / %s" % (o.get("o1"), o.get("o2")))
    check(f("o3") == ["0", "PC 2550213", "TS2 CC15"] and f("o4") == ["0", "All call", "TS2 CC15 TG16777215"],
          "FIX7 А2: перекриття -- приватний без імені «PC 2550213» (без дубля числа), «All call» і число вміщується рівно в 19 символів: %s / %s" % (o.get("o3"), o.get("o4")))
    check(o.get("ptt") == "0,72", "R98 Д3: показ збігається з реальним призначенням PTT (модель стокового завантаження каналу): канали з контактом/списком/без контакту x перекриття ТГ (немає/ТГ/ПК) x індекс ТГ: %s" % o.get("ptt"))
    check(f("t1") == ["TS2 CC1 TG5"] and f("t2") == ["TS1 CC1 TG6"] and f("t3") == ["TS2 CC15 TG255"],
          "R98 Д2: ефективний ТС -- контакт TS2 при каналі TS1, контакт TS1 при каналі TS2, NO_TS_OVERRIDE -> ТС каналу: %s %s %s" % (o.get("t1"), o.get("t2"), o.get("t3")))
    check(f("t4") == ["TS1 CC15 TG255"] and f("t5") == ["TS1 CC1 TG5"] and f("t6") == ["TS2 CC1 TG5"] and f("t7") == ["TS1 CC1 TG91"],
          "R98 Д2: ручне перекриття ТС (канал / контакт), прапор без значення, перекриття ТГ скасовує ТС контакту: %s %s %s %s" % (o.get("t4"), o.get("t5"), o.get("t6"), o.get("t7")))
    check(o.get("u1") == "0,2,0,3" and o.get("u2") == "0,0" and o.get("u3") == "0,0,1" and o.get("u4") == "0,0",
          "R98 Д1 / R98-FIX2 Д3: «D» -- у квадраті літери картки-джерела; APRS на B -- значок «A+» без конверта; в межах картки, без лічильника -- нічого; понад 9 -- «+»: %s %s %s %s" % (o.get("u1"), o.get("u2"), o.get("u3"), o.get("u4")))
    check(g.DW_UN_LETTER_X >= g.DW_SQ_X + 1 and g.DW_UN_NUM_X + 6 - 1 <= g.DW_SQ_X + g.DW_SQ_W - 2 and g.DW_UN_ENV_X + 8 + 1 <= g.DW_UN_NUM_X and g.DW_UN_LETTER_X + 6 + 1 <= g.DW_UN_ENV_X
          and g.DW_UN_DY > g.DW_ARROW_DY + 4 and g.DW_UN_DY + 8 <= g.DW_SQ_DY + g.DW_SQ_H - 1,
          "R98 Д1: індикатор у квадраті: літера x=4..9, конверт 8x6 x=11..18, число x=20..25 (≤ x=25 -- внутрішня межа квадрата), під ▸ й над нижньою рамкою")
    check(f("va") == ["0,0,0,0", "VFO A 430.12500", "TG Ukraine 255", "TS1 CC7 TG255"] and f("vb") == ["0", "TG 91", "TS1 CC7"],
          "R98 В3: картка VFO A (DMR) -- рядок 1 «VFO A» + частота, ТГ за списком VFO (SETTINGS_VFO_A_MODE+VFO), ефективний ТС/CC, без читання кодплага, ТС питає CHANNEL_VFO_A, замка нема: %s / %s" % (o.get("va"), o.get("vb")))
    check(f("vc") == ["0,-1", "VFO B", "FM 145.50000", "25k"] and f("vd") == ["0", "67.0 25k"] and o.get("ve") == "TS2 CC7 TG255",
          "R98 В3: картка VFO B (FM) -- «VFO B», частота в рядку 2, смуга/CTCSS без прочерків; ручне перекриття ТС цього VFO враховано: %s / %s / %s" % (o.get("vc"), o.get("vd"), o.get("ve")))
    check(o.get("k1") == "0,1,145,104" and o.get("k2") == "0", "FIX6 З2: замок AES -- лише на картці каналу з ключем, у (145, y+33), у межах картки: %s / %s" % (o.get("k1"), o.get("k2")))
    exp = {"m0": "0,0,9", "m1": "0,0,9", "m2": "0,1,8", "m3": "0,5,4", "m4": "0,9,0", "m5": "0,9,0"}
    for k in exp:
        check(o.get(k, "").startswith(exp[k]) or ",".join(o.get(k, "").split(",")[:3]) == exp[k], "FIX6 З2 (%s): сегментований S-метр -- (виходів,залито,контурних) = %s: %s" % (k, exp[k], o.get(k)))
    check(o.get("m9") == "0,0,0", "FIX6 З2: неактивна картка -- без смуги й S-метра: %s" % o.get("m9"))
    # ---- мутанти ----
    base = out
    rr = fn[-1]   # R98-FIX2: між dualEffectiveTs і dualRenderRow -- функції тонів/відстані (fn[5:-1])
    mid = fn[5:-1]
    mutd = (("перекриття ТГ ігнорується", fn[3].replace("nonVolatileSettings.overrideTG != 0", "0"), fn[4]), ("список прийому ігнорується", fn[3].replace("if (ci == 0)", "if (1)"), fn[4]),
            ("ТС контакту ігнорується", fn[3], re.sub(r"\(tsFlags & 0x01\)\s*==\s*0x00", "0", fn[4])),
            ("ТС каналу замість ефективного", fn[3], "static uint8_t dualEffectiveTs(const CodeplugChannel_t *ch, uint8_t tsFlags) { (void)tsFlags; return (codeplugChannelGetFlag((CodeplugChannel_t *)ch, CHANNEL_FLAG_TIMESLOT_TWO) != 0) ? 2U : 1U; }"))
    muts = (("VFO-тип ігнорується (картка VFO читається як канал)", re.sub(r"_Bool isVfo = \(vfoType != [^)]*\);", "_Bool isVfo = 0;", rr)),
            ("замок AES завжди", rr.replace("uiChannelDataHasAes(&tmp)", "1")), ("конверт завжди", rr.replace("if (un > 0U)", "if (1)")),
            ("S-метр завжди", re.sub(r"if \(active\)(\s*\{\s*dualMeterRow)", r"if (1)\1", rr, count=1)))
    for what, mf in muts:
        if mf == rr:
            check(False, "FIX6 (мутант) %s: заміна не відбулась" % what); continue
        mo = run_c(ROW_HARNESS % {"fns": defs + "\n".join([fn[0], fn[1], fn[2], fn[3], fn[4]] + mid + [mf])})
        check(mo is not None and mo != base, "FIX6 (мутант): %s -- ловиться тестами" % what)
    for what, md, me in mutd:
        if md == fn[3] and me == fn[4]:
            check(False, "R98 (мутант) %s: заміна не відбулась" % what); continue
        mo = run_c(ROW_HARNESS % {"fns": defs + "\n".join([fn[0], fn[1], fn[2], md, me] + mid + [rr])})
        check(mo is not None and mo != base, "R98 (мутант): %s -- ловиться тестами" % what)
    # А3: у dual-коді не лишилось рядків-прочерків
    blk = src[src.find("static uint32_t dualDestination"):src.find("bool uiChannelModeDualScreenShown")]
    check(re.search(r'"-{2,}"', blk) is None and re.search(r'"-{2,}"', src[src.find("static void dualRenderScreen"):src.find("void uiChannelModeColdStart")]) is None, "FIX7 А3: у коді карток нема рядків-прочерків («--», «---»)")

def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    test_block18()
    incs, cfgs = cmt.load_configs(FW)
    test_engine(incs, dict(cfgs))
    test_quickmenu_fix(incs, dict(cfgs))
    test_fix2(incs, dict(cfgs))
    test_fix5_z1(incs, dict(cfgs))
    test_fix5_z2(incs, dict(cfgs))
    test_fix7_a1()
    test_lang()
    test_cps()
    test_vs_base(incs, cfgs)
    print("test_r97: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
