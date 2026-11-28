# -*- coding: utf-8 -*-
"""test_r103tone.py -- R103-TONE-UI: після «Тон-відгуку» на екрані каналу/VFO не лишається відліку «0» і режиму передачі.

Причина (розвідка R103): відлік TX і режим «передача» малює uiChannelModeUpdateScreen(0), коли trxTransmissionEnabled=true і це не маяк
(isTransmittingIgnoringAPRSBeaconing). Під час тону будь-яке перемальовування екрана (сповіщення, таймер) малює «0»; trTxStop() прапор скидав,
а перемальовку не просив. Маяк просить її сам (aprs.c APRS_TX_FINAL_STAGE: displayQSOState = DEFAULT_SCREEN), PTT -- виходом з uiTxScreen.

Хост: СПРАВЖНІЙ application/source/functions/tone_reply.c (-DTONE_REPLY_HOST_TEST) -- стан-машина; з обгортки (TONE_REPLY_ENABLED) береться справжній
код від trTxStart() до кінця toneReplyTick(): trTxStop, toneReplyAbort, toneReplyTick; trTxAllowed і залізо -- заглушки; екран -- модель
(«перемальовка» = якщо displayQSOState != IDLE: запам'ятати, чи прапор передачі зараз піднятий, і скинути в IDLE -- як uiChannelModeUpdateScreen()).
  А  кінець тону за тривалістю, скасування клавішею в тоні, PTT (toneReplyAbort) у тоні, заборона TX у тоні: на екрані каналу й VFO запит
     перемальовки є, після нього малюється БЕЗ відліку (shown=0); перемальовка під час тону (сповіщення) не заважає
  Б  меню (клавіша відкрила інше меню): запиту нема (воно перемалюється саме); скасування в затримці (тон не стартував): запиту нема
  В  60 с: тон рівно 60 с, запит -- лише в кінці, не раніше
  Г  текст: запит лише в trTxStop(), один раз, під умовою «екран каналу/VFO»; усі виходи з тону йдуть через trTxStop()
  Д  мутанти: без запиту перемальовки (індикатор лишається); без перевірки меню; без VFO -- ловляться
Запуск: python3 tools/test_r103tone.py"""
import os, re, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
INC = os.path.join(APP, "include")
SRC = os.path.join(APP, "source", "functions", "tone_reply.c")
HDR = os.path.join(INC, "functions", "tone_reply.h")
FAILS = []
N = [0]
QUIET = [False]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        if not QUIET[0]:
            print("ПРОВАЛ: " + m)


def rd(p):
    return open(p, encoding="utf-8").read()


def carve(text, start, end_marker):
    a = text.index(start)
    return text[a:text.index(end_marker, a)]


WRAP_PRE = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/tone_reply.h"
#define CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG 19
static uint8_t g_flash[8]; static int g_present = 0;
static bool codeplugGetOpenGD77CustomDataBounded(int type, uint8_t *d, int len)
{ if ((type != 19) || !g_present || (len != 8)) return false; memcpy(d, g_flash, 8); return true; }
static bool codeplugSetOpenGD77CustomData(int type, uint8_t *d, int len)
{ if ((type != 19) || (len != 8)) return false; memcpy(g_flash, d, 8); g_present = 1; return true; }

/* заглушки заліза й екрана */
enum { QSO_DISPLAY_IDLE = 0, QSO_DISPLAY_DEFAULT_SCREEN, QSO_DISPLAY_CALLER_DATA, QSO_DISPLAY_CALLER_DATA_UPDATE };
enum { UI_CHANNEL_MODE = 3, UI_VFO_MODE = 4, UI_OTHER = 9 };
enum { KEY_EVENT = 1, BUTTON_EVENT = 2 };
enum { RADIO_MODE_ANALOG = 0, RADIO_MODE_DIGITAL = 1 };
enum { RADIO_DEVICE_PRIMARY = 0 };
enum { LED_GREEN = 0, LED_RED = 1 };
enum { AUDIO_AMP_CHANNEL_RF = 2 };
enum { ECOPHASE_POWERSAVE_INACTIVE = 0 };
typedef struct { int hasEvent; int events; } uiEvent_t;
typedef struct { uint32_t txFreq; int txTone; int rxTone; } chan_t;
static chan_t g_chan = { 145500000U, 0, 0 };
static chan_t *currentChannelData = &g_chan;
static struct { int displayQSOState; } uiDataGlobal;
static bool trxTransmissionEnabled, trxIsTransmitting;
static int g_menu, g_allowed, g_rf, g_tone;
static uint32_t g_now;
static void rxPowerSavingSetState(int s) { (void)s; }
static void LedWrite(int l, int v) { (void)l; (void)v; }
static void HRC6000ClearIsWakingState(void) {}
static void trxSetTxCSS(int t) { (void)t; }
static void trxSetRxCSS(int d, int t) { (void)d; (void)t; }
static void trxSetTX(void) { trxTransmissionEnabled = true; trxIsTransmitting = true; }
static void trxSetTone1(int f) { g_tone = f; }
static bool AT1846sToneDevSave(uint16_t *d) { *d = 0x2E; return true; }   /* R113: девіація каналу */
static void AT1846sToneDevRestore(uint16_t d) { (void)d; }
static void trxActivateRx(bool b) { (void)b; }
static uint32_t ticksGetMillis(void) { return g_now; }
static int trxGetMode(void) { return RADIO_MODE_ANALOG; }
static int audioAmpGetStatus(void) { return (g_rf && !trxTransmissionEnabled) ? AUDIO_AMP_CHANNEL_RF : 0; }
static int menuSystemGetCurrentMenuNumber(void) { return g_menu; }
'''

WRAP_MAIN = r'''
static bool trTxAllowed(void) { return g_allowed != 0; }
@@B@@

static int shownTx, redraws, txRedraws;
/* модель uiChannelModeUpdateScreen()/uiVFOModeUpdateScreen(): якщо просили перемальовку -- малюємо (з відліком, якщо прапор піднятий) і скидаємо в IDLE */
static void screen(void)
{
	if (uiDataGlobal.displayQSOState != QSO_DISPLAY_IDLE)
	{
		shownTx = trxTransmissionEnabled ? 1 : 0;
		uiDataGlobal.displayQSOState = QSO_DISPLAY_IDLE;
		redraws++;
		if (trxTransmissionEnabled) txRedraws++;
	}
}

/* Сценарій. Конфіг: тривалість dur с, затримка 1 с, увімкнено, поріг 1 с. Сигнал 200..1700 мс (1,5 с >= порогу), далі затримка 1 с -> тон.
 * keyAt -- мс, коли «натиснуто клавішу»; abortAt -- мс, коли PTT (toneReplyAbort); offAt -- мс, коли TX стає забороненим; mid -- 1: у тоні (+500 мс)
 * хтось просить перемальовку (сповіщення), mid=0: ні. */
static void scen(const char *tag, int menu, unsigned dur, int keyAt, int abortAt, int offAt, int mid)
{
	uint8_t b[8] = { 3, 0, 1, 1, 0xB0, 0x04, 1, 0 };
	uint32_t tStart = 0, tEnd = 0;
	int req = -1, wasTx = 0, reqBeforeEnd = 0;
	uiEvent_t ev;

	b[1] = (uint8_t)dur;
	memcpy(g_flash, b, 8); g_present = 1;
	toneReplyLoad();
	toneReplySetEnabled(true);
	g_menu = menu; g_allowed = 1; trxTransmissionEnabled = false; trxIsTransmitting = false; g_tone = 0;
	uiDataGlobal.displayQSOState = QSO_DISPLAY_IDLE; shownTx = 0; redraws = 0; txRedraws = 0;
	for (uint32_t t = 0; t <= 2700U + dur * 1000U + 4000U; t += 10U)
	{
		g_now = 100000U + t;
		g_rf = ((t >= 200U) && (t < 1700U)) ? 1 : 0;
		if ((offAt >= 0) && (t >= (uint32_t)offAt)) g_allowed = 0;
		memset(&ev, 0, sizeof ev);
		if ((keyAt >= 0) && (t == (uint32_t)keyAt)) { ev.hasEvent = 1; ev.events = KEY_EVENT; }
		if (mid && trxTransmissionEnabled && (tStart != 0) && (t == tStart + 500U)) uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
		toneReplyTick(&ev);
		if ((abortAt >= 0) && (t == (uint32_t)abortAt)) toneReplyAbort();
		if (trxTransmissionEnabled && !wasTx) tStart = t;
		if (!trxTransmissionEnabled && wasTx) { tEnd = t; req = uiDataGlobal.displayQSOState; }
		if (!trxTransmissionEnabled && !wasTx && (tStart != 0) && (tEnd == 0)) { /* не буває */ }
		wasTx = trxTransmissionEnabled ? 1 : 0;
		if (trxTransmissionEnabled && (uiDataGlobal.displayQSOState == QSO_DISPLAY_DEFAULT_SCREEN) && !mid) reqBeforeEnd = 1;
		screen();
	}
	printf("%s start=%u end=%u req=%d shown=%d redraws=%d txRedraws=%d reqBeforeEnd=%d tone=%d tx=%d\n", tag, tStart, tEnd, req, shownTx, redraws, txRedraws, reqBeforeEnd, g_tone, (int)trxTransmissionEnabled);
}

int main(void)
{
	printf("DEFAULT=%d\n", QSO_DISPLAY_DEFAULT_SCREEN);
	scen("NORM_CH",   UI_CHANNEL_MODE, 2, -1, -1, -1, 1);
	scen("NORM_VFO",  UI_VFO_MODE,     2, -1, -1, -1, 1);
	scen("NORM_QUIET",UI_CHANNEL_MODE, 2, -1, -1, -1, 0);
	scen("KEY_TX",    UI_CHANNEL_MODE, 10, 3200, -1, -1, 1);
	scen("PTT_TX",    UI_CHANNEL_MODE, 10, -1, 3200, -1, 1);
	scen("OFF_TX",    UI_VFO_MODE,     10, -1, -1, 3200, 1);
	scen("MENU_END",  UI_OTHER,        2, -1, -1, -1, 1);
	scen("MENU_KEY",  UI_OTHER,        10, 3200, -1, -1, 0);
	scen("KEY_DELAY", UI_CHANNEL_MODE, 2, 2000, -1, -1, 0);
	scen("LONG60",    UI_CHANNEL_MODE, 60, -1, -1, -1, 1);
	return 0;
}
'''


def build_run(src_text, hdr_text):
    d = tempfile.mkdtemp(prefix="r103tone_")
    try:
        os.makedirs(os.path.join(d, "functions"))
        open(os.path.join(d, "functions", "tone_reply.h"), "w", encoding="utf-8").write(hdr_text)
        pure = os.path.join(d, "pure.c"); open(pure, "w", encoding="utf-8").write(src_text)
        a = carve(src_text, "static toneReplySm_t  s_trSm;", "/* Чи можна передати тон зараз.")
        end = src_text.rindex("\n#endif")
        b = src_text[src_text.index("/* Передача тону -- як маяк APRS"):end]
        wp = os.path.join(d, "w.c")
        open(wp, "w", encoding="utf-8").write(WRAP_PRE + a + WRAP_MAIN.replace("@@B@@", b))
        exe = os.path.join(d, "h")
        r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-DTONE_REPLY_HOST_TEST", "-I" + d, "-I" + INC, "-o", exe, wp, pure],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-2500:]
        return subprocess.run([exe], capture_output=True, text=True, timeout=120).stdout, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def parse(out):
    res = {}
    for ln in out.splitlines():
        if ln.startswith("DEFAULT="):
            res["_DEFAULT"] = int(ln.split("=")[1]); continue
        p = ln.split()
        if len(p) > 1:
            res[p[0]] = {kv.split("=")[0]: int(kv.split("=")[1]) for kv in p[1:] if "=" in kv}
    return res


def host_checks(out, tag=""):
    ok = True

    def want(c, m):
        nonlocal ok
        check(c, m + tag)
        if not c:
            ok = False
    r = parse(out)
    D = r.get("_DEFAULT", -1)
    want(D == 1, "0: модель: DEFAULT_SCREEN = 1")
    # А: кінець тону -> запит перемальовки, після нього без відліку; перемальовка під час тону була (відлік «0» малювався)
    for nm, dur in (("NORM_CH", 2), ("NORM_VFO", 2)):
        s = r.get(nm, {})
        want(s.get("start", 0) > 0 and abs((s.get("end", 0) - s.get("start", 0)) - dur * 1000) <= 10, "А (%s): тон стартував і тривав %d с: %r" % (nm, dur, s))
        want(s.get("txRedraws", 0) >= 1, "А (%s): у тоні була перемальовка (відлік «0» намальовано) -- сценарій має сенс: %r" % (nm, s))
        want(s.get("req") == D, "А (%s): у тому ж кроці, де тон зупинився, є запит перемальовки: %r" % (nm, s))
        want(s.get("shown") == 0, "А (%s): останнє намальоване -- БЕЗ відліку/режиму передачі: %r" % (nm, s))
        want(s.get("tone") == 0 and s.get("tx") == 0, "А (%s): тон і передавач вимкнено: %r" % (nm, s))
    s = r.get("NORM_QUIET", {})
    want(s.get("req") == D and s.get("shown") == 0 and s.get("reqBeforeEnd") == 0, "А (тиша): без чужих перемальовок у тоні -- запит лише в кінці, не раніше: %r" % s)
    for nm in ("KEY_TX", "PTT_TX", "OFF_TX"):
        s = r.get(nm, {})
        want(s.get("start", 0) > 0 and 3190 <= s.get("end", 0) <= 3210 and s.get("req") == D and s.get("shown") == 0 and s.get("tx") == 0,
             "А (%s): тон скасовано (клавіша/PTT/заборона TX) -- запит перемальовки, без відліку: %r" % (nm, s))
    # Б: меню -- запиту нема; скасування в затримці -- тон не стартував, запиту нема
    s = r.get("MENU_END", {})
    want(s.get("start", 0) > 0 and s.get("req") == 0, "Б (меню, кінець тону): запиту перемальовки нема: %r" % s)
    s = r.get("MENU_KEY", {})
    want(s.get("start", 0) > 0 and s.get("req") == 0, "Б (меню, клавіша): запиту нема: %r" % s)
    s = r.get("KEY_DELAY", {})
    want(s.get("start", 0) == 0 and s.get("req") == -1 and s.get("redraws") == 0 and s.get("tx") == 0, "Б (скасування в затримці): тон не стартував, перемальовок нема: %r" % s)
    # В: 60 с
    s = r.get("LONG60", {})
    want(abs((s.get("end", 0) - s.get("start", 0)) - 60000) <= 10 and s.get("req") == D and s.get("shown") == 0 and s.get("txRedraws") == 1,
         "В: 60 с -- тон рівно 60 с, запит у кінці, у тоні лише одна (чужа) перемальовка: %r" % s)
    return ok


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема -- НЕ «пройдено»"); FAILS.append("gcc нема"); return finish()
    src, hdr = rd(SRC), rd(HDR)
    out, err = build_run(src, hdr)
    check(out is not None, "0: хостова збірка (tone_reply.c + trTxStop/Abort/Tick + заглушки): %s" % err)
    if out is None:
        return finish()
    host_checks(out)

    # Г: текст
    stop = carve(src, "static void trTxStop(void)", "void toneReplyAbort(void)")
    check(src.count("displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN") == 1 and "displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN" in stop,
          "Г1: запит перемальовки -- один, у trTxStop()")
    check("(m == UI_CHANNEL_MODE) || (m == UI_VFO_MODE)" in stop, "Г2: запит лише на екрані каналу/VFO")
    tail = src[src.index("void toneReplyAbort(void)"):]
    check(tail.count("trTxStop();") == 2, "Г3: тон зупиняється лише через trTxStop(): Abort і Tick (STOP) -- 2 виклики")
    check("trxSetTone1(0);" in stop and "trxTransmissionEnabled = false;" in stop and stop.index("trxIsTransmitting = false;") < stop.index("displayQSOState"),
          "Г4: запит -- після скидання прапорів передачі (екран малюється вже без передачі)")

    # Д: мутанти
    def mut(name, a, b):
        s2 = src.replace(a, b, 1)
        if s2 == src:
            check(False, "Д (%s): шаблон не знайдено" % name); return
        o2, e2 = build_run(s2, hdr)
        if o2 is None:
            check(True, "Д (%s): не збирається -- ловиться" % name); return
        n0 = len(FAILS); QUIET[0] = True
        ok = host_checks(o2, " [m]")
        QUIET[0] = False; del FAILS[n0:]
        check(not ok, "Д (%s): ловиться" % name)

    mut("без скидання стану -- індикатор лишається", "uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;", "(void)uiDataGlobal;")
    mut("без перевірки меню", "if ((m == UI_CHANNEL_MODE) || (m == UI_VFO_MODE))", "if (1)")
    mut("без екрана VFO", "if ((m == UI_CHANNEL_MODE) || (m == UI_VFO_MODE))", "if (m == UI_CHANNEL_MODE)")
    return finish()


def finish():
    print("test_r103tone: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
