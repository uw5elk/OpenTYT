#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX3 (хост): цифри в «Подвійному прийомі», шумодав з режиму, червоні сегменти S-метра, стрілка після «[відстань]», центр наконечника.
  А  набір цифр для картки з покажчиком (СПРАВЖНІ dualEntry*(): номер каналу A/B, частота VFO, зелена/червона, ▼, з'їдання ручки/▲/довгого ▼) + мутанти;
     А0 -- доказ причини вади по тексту бази (цифри -> стоковий прямий номер ПОЗИЦІЇ зони, рація -> A, набране не видно, чергування стоїть)
  Б  SK1 + ручка: СПРАВЖНІ dualIsSquelchKey()/dualSquelchStep()/channelSquelchStep() (межі, старт від типового, FM/DMR, A/B/VFO) і СПРАВЖНІЙ dualTune()
     (зміна B не губиться після циклів A<->B) + мутанти; стокові ▲/▼ -- той самий крок
  В  останні 2 з 9 сегментів S-метра картки -- THEME_ITEM_FG_RSSI_BAR_S9P (СПРАВЖНІЙ dualMeterRow)
  Г  стрілка одразу після «[відстань]» (СПРАВЖНІ displayContactTextInfos/displaySplitOrSpanText/qsoShowNameWithDistance через драйвер test_r92) + мутант
  Д  центр наконечника = центр описаного кола (СПРАВЖНІЙ aprs_chevron.c, паритет з CPS screen_views.chevron_geom) + мутант
Запуск: python3 tools/test_r98fix3.py"""
import math, os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
cmt = T.cmt
FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
FN = os.path.join(APP, "source", "functions")
BASE = "650dec4"   # HEAD після R98-FIX2 у дереві розробки (у клоні власника хеш інший -- тоді ПРОПУСК)


def base_available():
    return subprocess.run(["git", "cat-file", "-e", BASE + "^{commit}"], cwd=FW, capture_output=True).returncode == 0


def base_file(rel):
    r = subprocess.run(["git", "show", "%s:MDUV380_firmware/%s" % (BASE, rel)], cwd=FW, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def run_c(code, args=()):
    d = tempfile.mkdtemp(prefix="r98f3_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-o", os.path.join(d, "h"), c, "-lm"], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:2500]); return None
        return subprocess.run([os.path.join(d, "h")] + list(args), capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


def kv(out):
    return dict(l.split("=", 1) for l in (out or "").splitlines() if "=" in l)


# ------------------------------------------------------------------------------------------------ А
ENTRY_STUBS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
typedef struct { uint8_t event; char key; } keyboardCode_t;
typedef struct { uint32_t buttons; keyboardCode_t keys; } uiEvent_t;
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 };
enum { UI_CHANNEL_MODE = 3, UI_OTHER = 4 };
enum { PROMPT_0 = 100, PROMPT_POINT = 200 };
static const int MELODY_ERROR_BEEP[1], MELODY_NACK_BEEP[1];
static struct { int displayQSOState; bool displayChannelSettings; struct { int index; char digits[12]; } FreqEnter; } uiDataGlobal;
static struct { int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_indexNumber; } currentZone;
static struct { char gotoChannel[17]; } lang = { "До" }, *currentLanguage = &lang;
static int directChannelNumber; static uint32_t s_dualKeyMs = 777; static uint8_t s_dualSqlB = 9;
static int en = 1, menu = UI_CHANNEL_MODE, ptrB, bVfo, onB, single, vfoIdx = 1;
static int suspends, tunes, lastTune = -1, resumes, chB = 3, lastUsedZone = -99, lastUsedPos = -99, loads, loadMem = -1, freqCalls, freqLast, beepErr, beepNack, prompts;
static int used[1100]; static int zoneCh[8] = { 5, 12, 30 }; static int zoneN = 3;
static bool dcIsEnabled(void) { return en; }
static int menuSystemGetCurrentMenuNumber(void) { return menu; }
static bool dcPointerB(void) { return ptrB; }
static bool dcBIsVfo(void) { return bVfo; }
static bool dcIsOnB(void) { return onB; }
static bool dualSingle(void) { return single; }
static uint8_t dualVfoIdx(void) { return (uint8_t)vfoIdx; }
static void dualSuspend(void) { suspends++; }
static void dualTune(bool b) { tunes++; lastTune = b; onB = b; }
static void dualAutoResume(void) { resumes++; }
static bool dcSetChannelB(uint16_t c, bool p) { (void)p; chB = c; return true; }
static bool codeplugAllChannelsIndexIsInUse(int c) { return (c >= 1 && c <= 1024) ? used[c] : 0; }
static uint16_t dualZoneChannelAt(int pos, void *ctx) { (void)ctx; return (pos >= 0 && pos < zoneN && used[zoneCh[pos]]) ? zoneCh[pos] : 0; }
static int dcFindPos(int n, uint16_t ch, uint16_t (*at)(int, void *), void *ctx) { for (int i = 0; i < n; i++) { if (at(i, ctx) == ch) return i; } return -1; }
static void codeplugSetLastUsedChannelInZone(int z, int16_t p) { lastUsedZone = z; lastUsedPos = p; }
static void uiChannelModeLoadChannelData(bool m, bool v) { (void)v; loads++; loadMem = m; }
static bool uiVFOModeDualFreqEnter(uint8_t v, int f) { (void)v; freqCalls++; freqLast = f; if ((f >= 14400000 && f <= 14800000) || (f >= 43000000 && f <= 44000000)) return true; beepErr++; return false; }
static void freqEnterReset(void) { memset(uiDataGlobal.FreqEnter.digits, '-', 12); uiDataGlobal.FreqEnter.index = 0; }
static int freqEnterRead(int a, int b, bool simple) { int r = 0; (void)simple; for (int i = a; i < b; i++) { r *= 10; if (uiDataGlobal.FreqEnter.digits[i] >= '0' && uiDataGlobal.FreqEnter.digits[i] <= '9') r += uiDataGlobal.FreqEnter.digits[i] - '0'; } return r; }
static void soundSetMelody(const int *m) { if (m == MELODY_ERROR_BEEP) beepErr++; else if (m == MELODY_NACK_BEEP) beepNack++; }
static void voicePromptsInit(void) {}
static void voicePromptsAppendPrompt(int p) { (void)p; prompts++; }
static void voicePromptsPlay(void) {}
static int menuGetKeypadKeyValue(uiEvent_t *ev, bool d) { (void)d; if ((ev->keys.event & 0x08) && ev->keys.key >= '0' && ev->keys.key <= '9') return ev->keys.key - '0'; return 99; }
@@FNS@@
static uiEvent_t E(char key, int event, uint32_t btn) { uiEvent_t e; e.buttons = btn; e.keys.key = key; e.keys.event = (uint8_t)event; return e; }
#define PRESS 0x08
#define UP 0x02
#define LONGDN (0x01 | 0x04)
static int key(char k, int event, uint32_t btn) { uiEvent_t e = E(k, event, btn); return dualEntryKey(&e); }
static int digit(char k) { int a = key(k, PRESS, 0); int b = key(k, UP, 0); return a && b; }
static void reset(void) { directChannelNumber = 0; freqEnterReset(); suspends = tunes = resumes = loads = freqCalls = beepErr = beepNack = prompts = 0; lastTune = -1; chB = 3; lastUsedZone = lastUsedPos = -99; loadMem = -1; onB = 0; ptrB = 0; bVfo = 0; single = 0; en = 1; menu = UI_CHANNEL_MODE; uiDataGlobal.displayChannelSettings = 0; currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone = zoneN; currentZone.NOT_IN_CODEPLUGDATA_indexNumber = 2; s_dualSqlB = 9; }
static void text(char *o) { char l2[17]; dualEntryText(l2, sizeof l2); strcpy(o, l2); }
int main(void)
{
	char t[32];
	used[5] = used[12] = used[30] = used[40] = used[1024] = 1;
	/* a1: покажчик на B (канал): «1» «2» -> поле «До 12_», зелена -> новий B, чергування поновлено */
	reset(); ptrB = 1; int h1 = digit('1') && digit('2'); text(t);
	int g = key(13, UP, 0);
	printf("a1=%d,%s,%d,%d,%d,%d,%d,%d\n", h1, t, g, chB, directChannelNumber, suspends > 0, resumes, s_dualSqlB);
	/* a2: B -- невикористаний номер 13 -> звук помилки, B той самий, набір завершено */
	reset(); ptrB = 1; digit('1'); digit('3'); key(13, UP, 0); printf("a2=%d,%d,%d\n", chB, beepErr, directChannelNumber);
	/* a3: покажчик на A, звичайна зона, номер 12 = позиція 1 у зоні */
	reset(); digit('1'); digit('2'); key(13, UP, 0); printf("a3=%d,%d,%d,%d,%d\n", lastUsedZone, lastUsedPos, loads, loadMem, beepErr);
	/* a4: A -- номер 40 використаний, але не в цій зоні -> помилка, канал не змінено */
	reset(); digit('4'); digit('0'); key(13, UP, 0); printf("a4=%d,%d,%d\n", lastUsedPos, loads, beepErr);
	/* a5: A у «Всіх каналах» -- будь-який використаний (40), «останній» = абсолютний номер */
	reset(); currentZone.NOT_IN_CODEPLUGDATA_indexNumber = -1; digit('4'); digit('0'); key(13, UP, 0); printf("a5=%d,%d,%d\n", lastUsedZone, lastUsedPos, loads);
	/* a6: A, рація на B (виклик на B) -- спершу на A, далі завантаження */
	reset(); onB = 1; digit('5'); key(13, UP, 0); printf("a6=%d,%d,%d\n", lastTune, lastUsedPos, loads);
	/* a7: картка VFO: 4 3 5 1 2 5 -> «435.125--», зелена -> частота 43512500 */
	reset(); ptrB = 1; bVfo = 1; digit('4'); digit('3'); digit('5'); digit('1'); digit('2'); digit('5'); text(t);
	key(13, UP, 0); printf("a7=%s,%d,%d,%d,%d\n", t, freqCalls, freqLast, directChannelNumber, lastTune);
	/* a8: VFO, 8 цифр -- підтвердження саме (як у стоку) */
	reset(); ptrB = 1; bVfo = 1; onB = 1; { const char *s = "14550000"; for (int i = 0; s[i]; i++) digit(s[i]); } printf("a8=%d,%d,%d\n", freqCalls, freqLast, directChannelNumber);
	/* a9: VFO поза діапазоном, зелена -> помилка, цифри лишаються */
	reset(); ptrB = 1; bVfo = 1; onB = 1; digit('9'); digit('9'); digit('9'); key(13, UP, 0); text(t); printf("a9=%d,%d,%s,%d\n", directChannelNumber, beepErr, t, uiDataGlobal.FreqEnter.index);
	/* a10: VFO 8 цифр поза діапазоном -> остання цифра стерта, звук помилки */
	reset(); ptrB = 1; bVfo = 1; onB = 1; { const char *s = "99900000"; for (int i = 0; s[i]; i++) digit(s[i]); } printf("a10=%d,%d,%d\n", uiDataGlobal.FreqEnter.index, beepErr, directChannelNumber);
	/* a11: червона скасовує (канал -- без NACK; VFO -- NACK); канал не змінено */
	reset(); ptrB = 1; digit('1'); digit('2'); int r1 = key(27, UP, 0); printf("a11=%d,%d,%d,%d\n", r1, chB, directChannelNumber, resumes);
	reset(); ptrB = 1; bVfo = 1; digit('4'); key(27, UP, 0); printf("a11v=%d,%d,%d\n", beepNack, freqCalls, directChannelNumber);
	/* a12: під час набору ручка, ▲, довге ▼, SK1+ручка, SK2+▼ -- з'їдаються, набір і B не змінюються */
	reset(); ptrB = 1; digit('1'); digit('2');
	int e1 = key(8, UP, 0), e2 = key(7, UP, 0), e3 = key(9, UP, 0), e4 = key(10, LONGDN, 0), e5 = key(8, UP, 0x02), e6 = key(9, UP, 0x20);
	printf("a12=%d%d%d%d%d%d,%d,%d,%d\n", e1, e2, e3, e4, e5, e6, directChannelNumber, chB, tunes);
	/* a13: ▼ стирає останню цифру; стерли все -- набір завершено */
	reset(); ptrB = 1; digit('1'); digit('2'); key(10, PRESS, 0); int a13a = directChannelNumber; key(10, PRESS, 0); printf("a13=%d,%d,%d\n", a13a, directChannelNumber, resumes);
	/* a14: > 1024 -- цифра не береться */
	reset(); ptrB = 1; digit('1'); digit('0'); digit('2'); digit('5'); printf("a14=%d,%d\n", directChannelNumber, beepErr);
	/* a15: режим вимкнено / інше меню / панель SK1 / SK1+цифра (стокові гарячі клавіші APRS) -- не наші */
	reset(); en = 0; int s1 = key('1', PRESS, 0); reset(); menu = UI_OTHER; int s2 = key('1', PRESS, 0); reset(); uiDataGlobal.displayChannelSettings = 1; int s3 = key('1', PRESS, 0);
	reset(); int s4 = key('1', PRESS, 0x02); reset(); int s5 = key(13, UP, 0); reset(); int s6 = key(8, UP, 0);
	printf("a15=%d%d%d%d%d%d\n", s1, s2, s3, s4, s5, s6);
	/* a16: перша цифра 0 -- з'їдається, набір не починається; довге 0 / 8 під час набору -- набір скинуто, клавіша -- стоку */
	reset(); int z = key('0', PRESS, 0); printf("a16=%d,%d\n", z, directChannelNumber);
	reset(); digit('8'); int l8 = key('8', LONGDN, 0); printf("a17=%d,%d\n", l8, directChannelNumber);
	/* a18: A == B (single), покажчик на B -- набір для B */
	reset(); ptrB = 1; single = 1; digit('4'); digit('0'); key(13, UP, 0); printf("a18=%d,%d\n", chB, lastUsedPos);
	return 0;
}
'''

ENTRY_EXP = {"a1": "1,До 12_,1,12,0,1,1,0", "a2": "3,1,0", "a3": "2,1,1,0,0", "a4": "-99,0,1", "a5": "-1,40,1", "a6": "0,0,1",
             "a7": "435.125--,1,43512500,0,1", "a8": "1,14550000,0", "a9": "-1,1,999.-----,3", "a10": "7,1,-1",
             "a11": "1,3,0,1", "a11v": "1,0,0", "a12": "111111,12,3,0", "a13": "1,0,1", "a14": "102,1", "a15": "000000",
             "a16": "1,0", "a17": "0,0", "a18": "40,-99"}

ENTRY_SIGS = ("static void dualEntryEnd(void)", "static _Bool dualEntryApplyChannel(int num)", "static _Bool dualEntryApplyFreq(void)",
              "static void dualEntryDigit(int keyval)", "static _Bool dualEntryKey(uiEvent_t *ev)", "static void dualEntryText(char *l2, size_t size)")


def test_part_a(t):
    fns = [T.carve_fn(t, s) for s in ENTRY_SIGS]
    check(all(fns), "А: функції набору знайдено: %s" % [s for s, f in zip(ENTRY_SIGS, fns) if not f])
    if not all(fns):
        return
    src = "\n".join(fns)
    out = run_c(ENTRY_STUBS.replace("@@FNS@@", src))
    o = kv(out)
    bad = {k: (o.get(k), v) for k, v in ENTRY_EXP.items() if o.get(k) != v}
    check(out is not None and not bad, "А: модель набору (канал A/B, VFO, зелена/червона, ▼, з'їдання ручки/▲/довгого ▼, межі, A поза зоною, A==B): %s" % bad)
    muts = (("стара поведінка: цифри йдуть у стоковий набір (набору режиму нема)", src.replace("static _Bool dualEntryKey(uiEvent_t *ev)\n{", "static _Bool dualEntryKey(uiEvent_t *ev)\n{\n return 0;")),
            ("номер A як ПОЗИЦІЯ зони (стоковий прямий номер)", src.replace("(allCh ? num : dcFindPos(", "(allCh ? num : (num - 1) + 0 * dcFindPos(")),
            ("під час набору ручка не з'їдається", src.replace(" uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;\n return 1;\n}", " uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;\n return (keyval < 10) || (ev->keys.key == 13) || (ev->keys.key == 27) || (ev->keys.key == 10);\n}")),
            ("червона не скасовує", re.sub(r"else if \(\(sk == 0\) && \(\(ev->keys\.key == 27\)[^\n]*\n\s*\{", "else if (0)\n {", src, count=1)),
            ("B без перевірки «використовується»", src.replace("|| (codeplugAllChannelsIndexIsInUse(num) == 0)", "")),
            ("VFO: підтвердження без налаштування на VFO", src.replace("if (dcIsOnB() == 0)\n {\n  dualTune(1);\n }", "")))
    for what, m in muts:
        mo = run_c(ENTRY_STUBS.replace("@@FNS@@", m)) if m != src else None
        mk = kv(mo)
        check(m != src and mo is not None and any(mk.get(k) != v for k, v in ENTRY_EXP.items()), "А (мутант): %s -- ловиться" % what)
    # відображення: рядок 2 картки з покажчиком
    uc = T.rd(os.path.join(UI, "uiChannelMode.c"))
    rr = uc[uc.find("static void dualRenderRow("):]
    rr = rr[:rr.find("\n}\n")]
    check("if ((directChannelNumber != 0) && (isB == dcPointerB()))\n\t{\n\t\tdualEntryText(l2, sizeof(l2));" in rr and rr.find("dualEntryText(l2") > rr.find("dualCallerText(l2);"),
          "А1: набране видно в рядку 2 картки з покажчиком (поверх абонента/ТГ), інша картка не змінюється")
    he = uc[uc.find("static void handleEventCore(uiEvent_t *ev)\n#else"):]
    check(he.find("if (dualEntryKey(ev))") > 0 and he.find("if (dualEntryKey(ev))") < he.find("bool dwRunning = dualIsRunning();") < he.find("dualTune(false);"),
          "А4: набір перехоплюється ДО решти логіки режиму (до повернення рації на A для «чужих» клавіш)")
    au = uc[uc.find("static void dualAutoResume(void)\n{"):]
    check("(directChannelNumber != 0)" in au[:900], "А5: поки набір триває (директ-номер або -1 частоти) -- чергування не поновлюється; після -- dualAutoResume()")
    # А0: доказ причини по тексту бази
    if base_available():
        b = base_file("application/source/user_interface/uiChannelMode.c") or ""
        bh = b[b.find("static bool dualHandleKey(uiEvent_t *ev)\n{"):]
        bh = bh[:bh.find("\n}\n")]
        bhe = b[b.find("static void handleEventCore(uiEvent_t *ev)\n#else"):]
        bhe = bhe[:bhe.find("if (uiDataGlobal.Scan.active && (ev->events & KEY_EVENT))")]
        brr = b[b.find("static void dualRenderRow("):]
        brr = brr[:brr.find("\n}\n")]
        ok = ("menuGetKeypadKeyValue" not in bh and "directChannelNumber" not in bh and
              "if (dcIsOnB() && (ev->keys.key != KEY_GREEN)" in bhe and "dualTune(false);" in bhe and
              "directChannelNumber = (directChannelNumber * 10) + keyval;" in b and "(directChannelNumber - 1) < currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone" in b and
              "directChannelNumber" not in brr and "(directChannelNumber != 0)" in b[b.find("static void dualAutoResume(void)\n{"):][:900])
        check(ok, "А0 (база %s): цифри режим не обробляв -> стоковий прямий номер (ПОЗИЦІЯ в зоні), перед ним рація -> A (обрана картка A), на картці набране не видно, чергування стоїть до зеленої/червоної" % BASE)
        bdh = b[b.find("static bool dualHoldScreen(void)\n{"):][:1200]
        check("(directChannelNumber != 0)" in bdh, "А0: під час невидимого набору екран режиму лишався (dualHoldScreen) -- ручка/▲▼ поза чергуванням ішли в стокові обробники (зміна каналу A, ТГ/шумодав)")
    else:
        print("ПРОПУСК: база недоступна (CI/клон без історії): А0 по тексту бази не перевірено")


# ------------------------------------------------------------------------------------------------ Б
SQL_STUBS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
typedef struct { uint8_t event; char key; } keyboardCode_t;
typedef struct { uint32_t buttons; keyboardCode_t keys; } uiEvent_t;
enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 }; enum { UI_CHANNEL_MODE = 3 }; enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 };
enum { PROMPT_SQUENCE_SQUELCH = 1, PROMPT_THRESHOLD_3 = 3, NOTIFICATION_TYPE_SQUELCH = 5, NOTIFICATION_ID_SQUELCH = 6, TRX_RX_FREQ_BAND = 0 };
static const int CODEPLUG_MIN_VARIABLE_SQUELCH = 1, CODEPLUG_MAX_VARIABLE_SQUELCH = 21;
static const int MELODY_ERROR_BEEP[1];
typedef struct { uint8_t sql; uint8_t chMode; char tag; } CodeplugChannel_t;
static CodeplugChannel_t bufA = { 0, 1, 'A' }, bufB = { 5, 1, 'B' }, vfo = { 7, 1, 'V' }, *currentChannelData = &bufA;
static struct { uint8_t squelchDefaults[3]; } nonVolatileSettings = { { 10, 11, 12 } };
static struct { int trxCurrentBand[2]; } dev = { { 1, 1 } }, *currentRadioDevice = &dev;
static struct { int displayQSOState; } uiDataGlobal;
static int directChannelNumber; static uint8_t s_dualSqlB;
static int en = 1, ptrB, bVfo, onB, single, notif, beep, vfoDirty, suspends;
static bool dcIsEnabled(void) { return en; }
static int menuSystemGetCurrentMenuNumber(void) { return UI_CHANNEL_MODE; }
static bool dcPointerB(void) { return ptrB; }
static bool dcBIsVfo(void) { return bVfo; }
static bool dcIsOnB(void) { return onB; }
static bool dualSingle(void) { return single; }
static void dualSuspend(void) { suspends++; }
static void dualTune(bool b) { onB = b; currentChannelData = (b ? (bVfo ? &vfo : &bufB) : &bufA); }
static void announceItem(int a, int b) { (void)a; (void)b; }
static void uiNotificationShow(int a, int b, int c, void *d, bool e) { (void)a; (void)b; (void)c; (void)d; (void)e; notif++; }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
static void soundSetMelody(const int *m) { (void)m; beep++; }
static void settingsSetVFODirty(void) { vfoDirty++; }
@@FNS@@
static uiEvent_t E(char key, int event, uint32_t btn) { uiEvent_t e; e.buttons = btn; e.keys.key = key; e.keys.event = (uint8_t)event; return e; }
static void reset(void) { bufA.sql = 0; bufA.chMode = 1; bufB.sql = 5; bufB.chMode = 1; vfo.sql = 7; vfo.chMode = 1; currentChannelData = &bufA; onB = 0; ptrB = 0; bVfo = 0; single = 0; notif = beep = vfoDirty = suspends = 0; s_dualSqlB = 0; directChannelNumber = 0; en = 1; }
int main(void)
{
	/* ключ: SK1 + ручка -- так; SK2 + ручка, ручка без SK1, SK1 + інша клавіша, під час набору -- ні */
	uiEvent_t k1 = E(8, 2, 0x02), k2 = E(8, 2, 0x20), k3 = E(8, 2, 0), k4 = E(9, 2, 0x02), k5 = E(7, 2, 0x02);
	int q1 = dualIsSquelchKey(&k1), q2 = dualIsSquelchKey(&k2), q3 = dualIsSquelchKey(&k3), q4 = dualIsSquelchKey(&k4), q5 = dualIsSquelchKey(&k5);
	directChannelNumber = 12; int q6 = dualIsSquelchKey(&k1); directChannelNumber = 0; en = 0; int q7 = dualIsSquelchKey(&k1); en = 1;
	printf("k=%d%d%d%d%d%d%d\n", q1, q2, q3, q4, q5, q6, q7);
	/* A, sql 0 -> старт від типового для діапазону (11) -> 12; сповіщення; B-перекриття не чіпається */
	reset(); dualSquelchStep(1); printf("s1=%d,%d,%d,%d\n", bufA.sql, notif, s_dualSqlB, onB);
	/* A вниз від 0 -> 10; межі: 21 -> 21, 1 -> 1 */
	reset(); dualSquelchStep(-1); int d1 = bufA.sql; bufA.sql = 21; dualSquelchStep(1); int d2 = bufA.sql; bufA.sql = 1; dualSquelchStep(-1); printf("s2=%d,%d,%d\n", d1, d2, bufA.sql);
	/* покажчик на B (канал), рація на A -> на B, крок 5 -> 6, s_dualSqlB = 6 */
	reset(); ptrB = 1; dualSquelchStep(1); printf("s3=%d,%d,%d,%d\n", onB, bufB.sql, s_dualSqlB, bufA.sql);
	/* покажчик на A, рація на B -> на A */
	reset(); onB = 1; currentChannelData = &bufB; bufA.sql = 4; dualSquelchStep(1); printf("s4=%d,%d,%d\n", onB, bufA.sql, bufB.sql);
	/* покажчик на B = VFO -> крок 7 -> 8, settingsSetVFODirty, s_dualSqlB не чіпається */
	reset(); ptrB = 1; bVfo = 1; dualSquelchStep(1); printf("s5=%d,%d,%d\n", vfo.sql, vfoDirty, s_dualSqlB);
	/* DMR -> звук помилки, нічого не змінено */
	reset(); ptrB = 1; bufB.chMode = 2; dualSquelchStep(1); printf("s6=%d,%d,%d,%d\n", beep, bufB.sql, notif, s_dualSqlB);
	/* A == B (single), покажчик на B -> діє на A (один канал) */
	reset(); ptrB = 1; single = 1; bufA.sql = 4; dualSquelchStep(1); printf("s7=%d,%d,%d\n", onB, bufA.sql, s_dualSqlB);
	return 0;
}
'''
SQL_EXP = {"k": "1000100", "s1": "12,1,0,0", "s2": "10,21,1", "s3": "1,6,6,0", "s4": "0,5,5", "s5": "8,1,0", "s6": "1,5,0,0", "s7": "0,5,0"}

# справжній dualTune: перекриття sql для B після перечитування з кодплага, кілька циклів A<->B
TUNE_SQL = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
typedef struct { uint32_t rxFreq; uint8_t sql; char tag; } CodeplugChannel_t;
static CodeplugChannel_t channelScreenChannelData, scanNextChannelData, settingsVFOChannel[2];
static CodeplugChannel_t *currentChannelData;
static struct { int currentSelectedChannelNumber; } uiDataGlobal;
static struct { int16_t currentIndexInTRxGroupList[4]; } nonVolatileSettings;
#define SETTINGS_CHANNEL_MODE 0
static int16_t s_dualTgIdxA; static uint8_t s_dualSqlB;
static int onB, bIsVfo;
static bool dcIsOnB(void) { return onB; }
static void dcSetOnB(bool b) { onB = b; }
static bool dcBIsVfo(void) { return bIsVfo; }
static uint16_t dcChannelB(void) { return 7; }
static uint8_t dualVfoIdx(void) { return 0; }
static void lastHeardClearLastID(void) { }
static void dmrAesRxRetune(void) { }
static void uiVFOModeDualLoad(uint8_t i, bool b) { (void)i; (void)b; }
static void codeplugChannelGetDataForIndex(uint16_t ch, CodeplugChannel_t *c) { memset(c, 0, sizeof *c); c->rxFreq = 1000u + ch; c->sql = 3; c->tag = 'B'; }
static void uiChannelModeLoadChannelData(bool m, bool v) { (void)m; (void)v; }
static void settingsSetBOOL(bool *p, bool v) { *p = v; }
static void settingsSetINT8(int8_t *p, int8_t v) { *p = v; }
static void settingsSetUINT8(uint8_t *p, uint8_t v) { *p = v; }
static void settingsSetINT16(int16_t *p, int16_t v) { *p = v; }
static void settingsSetUINT16(uint16_t *p, uint16_t v) { *p = v; }
static void settingsSetINT32(int32_t *p, int32_t v) { *p = v; }
static void settingsSetUINT32(uint32_t *p, uint32_t v) { *p = v; }
@@FN@@
int main(void)
{
	onB = 0; currentChannelData = &channelScreenChannelData; channelScreenChannelData.rxFreq = 438500; channelScreenChannelData.sql = 9; channelScreenChannelData.tag = 'A';
	dualTune(1); int b0 = channelScreenChannelData.sql;                    /* без перекриття -- з кодплага (3) */
	s_dualSqlB = 8; channelScreenChannelData.sql = 8;                      /* крок шумодава на B */
	int ok = 1;
	for (int i = 0; i < 4; i++) { dualTune(0); if (channelScreenChannelData.sql != 9 || channelScreenChannelData.tag != 'A') ok = 0; dualTune(1); if (channelScreenChannelData.sql != 8) ok = 0; }
	printf("t=%d,%d\n", b0, ok);
	return 0;
}
'''


def test_part_b(t):
    sigs = ("static inline __attribute__((always_inline)) void channelSquelchStep(int dir)", "static _Bool dualIsSquelchKey(const uiEvent_t *ev)", "static void dualSquelchStep(int dir)")
    fns = [T.carve_fn(t, s) for s in sigs]
    check(all(fns), "Б: функції шумодава знайдено")
    if all(fns):
        src = "\n".join(fns)
        out = run_c(SQL_STUBS.replace("@@FNS@@", src))
        o = kv(out)
        bad = {k: (o.get(k), v) for k, v in SQL_EXP.items() if o.get(k) != v}
        check(out is not None and not bad, "Б: SK1+ручка -- крок шумодава картки з покажчиком (межі 1..21, старт від типового, FM/DMR, A/B/VFO, A==B): %s" % bad)
        muts = (("без старту від типового", src.replace("if(currentChannelData->sql == 0)", "if(0)")), ("без межі зверху", src.replace("if (currentChannelData->sql < CODEPLUG_MAX_VARIABLE_SQUELCH)", "if (1)")),
                ("DMR не відсікається", src.replace("if (currentChannelData->chMode != RADIO_MODE_ANALOG)", "if (0)")),
                ("зміна B не запам'ятовується", src.replace("s_dualSqlB = currentChannelData->sql;", "")),
                ("діє на картку, де рація, а не на покажчик", src.replace("if (toB != dcIsOnB())", "if (0)")))
        for what, m in muts:
            mo = run_c(SQL_STUBS.replace("@@FNS@@", m)) if m != src else None
            mk = kv(mo)
            check(m != src and mo is not None and any(mk.get(k) != v for k, v in SQL_EXP.items()), "Б (мутант): %s -- ловиться" % what)
    fn = T.carve_fn(t, "static void dualTune(_Bool toB)"); bh = T.carve_fn(t, "static _Bool dualBufHoldsB(void)")
    check(fn is not None and bh is not None, "Б2: dualTune знайдено")
    if fn and bh:
        out = run_c(TUNE_SQL.replace("@@FN@@", bh + "\n" + fn))
        check(kv(out).get("t") == "3,1", "Б2: шумодав B = канал не губиться після 4 циклів A<->B (кодплаг дає 3, перекриття 8), A лишається своїм (9): %s" % (out or "").strip())
        m = fn.replace("channelScreenChannelData.sql = s_dualSqlB;", "")
        mo = run_c(TUNE_SQL.replace("@@FN@@", bh + "\n" + m)) if m != fn else None
        check(m != fn and kv(mo).get("t") != "3,1", "Б2 (мутант): «зміна B губиться» (без перекриття після перечитування) -- ловиться")
    # стокові ▲/▼ -- той самий крок (одна функція), без прапорця -- стокова (перевіряє ще й sha типової збірки)
    uc = T.rd(os.path.join(UI, "uiChannelMode.c"))
    check(uc.count("channelSquelchStep(1);") == 1 and uc.count("channelSquelchStep(-1);") == 1 and uc.count("channelSquelchStep(dir);") == 1,
          "Б1: стокові ▲/▼ і режим -- одна функція кроку (без дубліката логіки)")
    cs = uc[uc.find("void channelSquelchStep(int dir)\n{"):]
    cs = cs[:cs.find("\n}\n")]
    if base_available():
        b = base_file("application/source/user_interface/uiChannelMode.c") or ""
        check(uc.count("currentChannelData->sql++;") == b.count("currentChannelData->sql++;") and uc.count("currentChannelData->sql--;") == b.count("currentChannelData->sql--;") and
              "currentChannelData->sql++;" in cs and "currentChannelData->sql--;" in cs, "Б1: крок шумодава екрана каналу перенесено в channelSquelchStep (не скопійовано): лічильник ++/-- як у базі")
    else:
        print("ПРОПУСК: база недоступна (CI/клон без історії): Б1 порівняння з базою не виконано")
    # s_dualSqlB скидається при КОЖНІЙ зміні B у режимі
    sets = [m.start() for m in re.finditer(r"dcSetChannelB\(|dcSetTypeB\(", uc)]
    lines = [uc.count("\n", 0, p) + 1 for p in sets]
    near = [("s_dualSqlB = 0U;" in uc[max(0, p - 700):p]) for p in sets]
    check(all(near) and len(sets) >= 3, "Б2: перекриття шумодава B скидається при кожній зміні B (рядки %s)" % lines)


# ------------------------------------------------------------------------------------------------ В
METER = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
enum { THEME_ITEM_FG_DEFAULT = 1, THEME_ITEM_BG, THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_FG_RSSI_BAR, THEME_ITEM_FG_RSSI_BAR_S9P, THEME_ITEM_FG_DECORATION };
enum { FONT_SIZE_1 = 1 }; enum { TEXT_ALIGN_LEFT = 0 }; enum { RADIO_DEVICE_PRIMARY = 0 };
#define SMETER_S0 -129
@@DEFS@@
static int rssi, fg, fills[32][2], nf, rects;
static int trxGetRSSIdBm(int d) { (void)d; return rssi; }
static void displayThemeApply(int f, int b) { (void)b; fg = f; }
static void displayThemeResetToDefault(void) {}
static void displayFillRect(int x, int y, int w, int h, bool inv) { (void)y; (void)h; (void)inv; if (w == 10) { fills[nf][0] = x; fills[nf][1] = fg; nf++; } }
static void displayDrawRect(int x, int y, int w, int h, bool c) { (void)x; (void)y; (void)w; (void)h; (void)c; rects++; }
static void displayPrintCore(int x, int y, const char *s, int f, int a, bool i) { (void)x; (void)y; (void)s; (void)f; (void)a; (void)i; }
@@FN@@
int main(void)
{
	int lv[] = { -40, -93, -97, -129 };
	for (int k = 0; k < 4; k++) { rssi = lv[k]; nf = 0; rects = 0; dualMeterRow(0); printf("m%d=", k); for (int i = 0; i < nf; i++) printf("%d", (fills[i][1] == THEME_ITEM_FG_RSSI_BAR_S9P) ? 2 : ((fills[i][1] == THEME_ITEM_FG_RSSI_BAR) ? 1 : 0)); printf(",%d\n", rects); }
	return 0;
}
'''


def test_part_v(t):
    fn = T.carve_fn(t, "static void dualMeterRow(int16_t y)")
    uc = T.rd(os.path.join(UI, "uiChannelMode.c"))
    defs = "".join(l + "\n" for l in uc[uc.find("#define DW_CARD_X"):uc.find("// Текст абонента")].splitlines() if l.startswith("#define")).replace("DISPLAY_Y_POS_BAR", "10")
    check(fn is not None, "В: dualMeterRow знайдено")
    if not fn:
        return
    out = run_c(METER.replace("@@DEFS@@", defs).replace("@@FN@@", fn))
    o = kv(out)
    exp = {"m0": "111111122,0", "m1": "111111122,0", "m2": "11111112,1", "m3": ",9"}
    check(o == exp, "В: сильний сигнал -- сегменти 1..7 звичайним кольором смуги, 8..9 -- THEME_ITEM_FG_RSSI_BAR_S9P; незаповнені -- контур: %s" % o)
    m = fn.replace("THEME_ITEM_FG_RSSI_BAR_S9P", "THEME_ITEM_FG_RSSI_BAR")
    mo = run_c(METER.replace("@@DEFS@@", defs).replace("@@FN@@", m))
    check(m != fn and kv(mo) != exp, "В (мутант): усі сегменти одного кольору -- ловиться")
    hx = T.rd(os.path.join(APP, "include", "hardware", "HX8353E.h"))
    check("THEME_ITEM_FG_RSSI_BAR_S9P," in hx and "> S9" in hx[hx.find("THEME_ITEM_FG_RSSI_BAR_S9P"):][:120], "В: колір -- наявний елемент теми «смуга понад S9», нового кольору нема")


# ------------------------------------------------------------------------------------------------ Г
def test_part_g():
    import test_r92 as R
    lc = T.rd(os.path.join(FN, "lc_distance.c")); ui = T.rd(os.path.join(UI, "uiUtilities.c"))
    exe, err = R.build(lc, ui, tag="r98f3g_")
    check(exe is not None, "Г: драйвер шапки виклику (test_r92) зібрано: %s" % err[-400:] if exe is None else "")
    if exe is None:
        return
    lat, lon = R.offset_point(19000.0, 135.0)
    names = ["UR5ABC", "UT3UBR Bohdan", "BohdanKryvyi Rih", "BohdanKryvyiRihUkraine", "UR5ABC Bohdan Kryvyi Rih Dnipropetrovska obl",
             "Petro", "UR5ABCDEFGHIJKLMNOPQRSTU", "UR5ABC Bohdanovych Kryvyi"]
    bad = []; seen = 0; after = 0
    for split in (0, 1, 2):
        for dbl in (0, 1):
            for nm in names:
                cmd = "CASE|2|%d|1|%d|%f|%f|%f|%f|%s|%s" % (split, dbl, R.MY[0], R.MY[1], lat, lon, "", nm)
                rows = R.drive(exe, [cmd])
                prints = []
                for l in rows:
                    mm = re.match(r"P (\d+) (\d+) \[(.*)\]$", l)
                    if mm:
                        prints.append((int(mm.group(1)), int(mm.group(2)), mm.group(3)))
                xs, ys = [], []
                for l in rows:
                    if l.startswith("D "):
                        a = list(map(int, l.split()[1:])); xs += [a[0], a[2]]; ys += [a[1], a[3]]
                lab = [p for p in prints if "]" in p[2]]
                if not xs:
                    if lab and (split == 0 and len(lab[0][2]) <= 16):
                        bad.append(("нема стрілки", split, dbl, nm))
                    continue
                seen += 1
                if not lab:
                    bad.append(("стрілка без підпису", split, dbl, nm)); continue
                y, f, txt = lab[-1]
                w = 8 if f == 3 else 6
                h = (16 if f == 3 else 8) * (2 if dbl else 1)
                n = min(len(txt), 160 // w)
                x0 = (160 - w * n) >> 1; x1 = x0 + w * n
                # заглушка драйвера друкує y без подвоєння для другого підрядка -- беремо середину за логікою displaySplitOrSpanText
                cx0, cx1 = min(xs), max(xs)
                if not (cx0 >= x1 + 1 and cx0 <= x1 + 2 + 2 or max(xs) >= 159 - 1):
                    bad.append(("не одразу після тексту", split, dbl, nm, x1, cx0, cx1))
                if cx1 > 159 or cx0 < 0:
                    bad.append(("за екраном", split, dbl, nm, cx0, cx1))
                # не перекриває жоден надрукований рядок (по горизонталі в межах його висоти)
                for (py, pf, pt) in prints:
                    pw = 8 if pf == 3 else 6
                    ph = (16 if pf == 3 else 8) * (2 if (dbl and pf == 3) else 1)
                    pn = min(len(pt), 160 // pw)
                    px0 = (160 - pw * pn) >> 1; px1 = px0 + pw * pn
                    if not (max(ys) < py or min(ys) >= py + ph) and not (cx1 < px0 or cx0 >= px1):
                        bad.append(("перекриває текст", split, dbl, nm, pt, cx0, cx1, px0, px1))
                if abs(((min(ys) + max(ys)) / 2.0) - (y + (h if (f == 3) else 8 * (2 if dbl else 1)) / 2.0)) > 6:
                    bad.append(("не в рядку підпису", split, dbl, nm, y, min(ys), max(ys)))
                after += 1
    check(seen >= 20 and not bad, "Г: стрілка одразу після «[відстань]» у тому самому рядку (усі режими розділення, подвійна висота, короткі/довгі імена, з пробілом і без), у межах екрана, не перекриває текст: %d випадків, вади %s" % (seen, bad[:3]))
    # мутант: стара позиція (праве поле рядка)
    m = lc.replace("	a->cx = (int16_t)(left + (LC_ARROW_CELL / 2));", "	a->cx = (int16_t)(screenW - LC_ARROW_MARGIN);")
    exe2, _ = R.build(m, ui, tag="r98f3gm_")
    caught = False
    if exe2:
        rows = R.drive(exe2, ["CASE|2|0|1|0|%f|%f|%f|%f||UR5ABC" % (R.MY[0], R.MY[1], lat, lon)])
        xs = [int(v) for l in rows if l.startswith("D ") for v in l.split()[1::2]]
        caught = bool(xs) and min(xs) > (((160 - 8 * len("UR5ABC [19km]")) >> 1) + 8 * len("UR5ABC [19km]") + 4)
    check(m != lc and caught, "Г (мутант): стара позиція (праве поле, x=147..156) -- ловиться")
    # координати для результату
    pr = []
    for nm in ("UR5ABC", "BohdanKryvyi Rih", "UR5ABC Bohdan Kryvyi Rih Dnipropetrovska obl"):
        for split in (0, 1):
            rows = R.drive(exe, ["CASE|2|%d|1|0|%f|%f|%f|%f||%s" % (split, R.MY[0], R.MY[1], lat, lon, nm)])
            xs = [int(v) for l in rows if l.startswith("D ") for v in l.split()[1::2]]
            ys = [int(v) for l in rows if l.startswith("D ") for v in l.split()[2::2]]
            lab = [l for l in rows if re.match(r"P \d+ \d+ \[.*\]\]$", l)]
            pr.append("%s|%s|%s|x=%s..%s y=%s..%s" % (["один рядок", "два рядки", "авто"][split], nm, lab[-1] if lab else "-", min(xs) if xs else "-", max(xs) if xs else "-", min(ys) if ys else "-", max(ys) if ys else "-"))
    print("Г координати:\n  " + "\n  ".join(pr))


# ------------------------------------------------------------------------------------------------ Д
CHEV = r'''
#include <stdio.h>
#include "functions/aprs_chevron.h"
int main(int argc, char **argv)
{
	int len = atoi(argv[1]);
	for (int b = 0; b < 360; b += 15) { aprsChevron_t c; aprsChevronGeom(&c, 80, 64, (int16_t)len, (uint16_t)b); printf("%d %d %d %d %d %d %d %d %d\n", b, c.tx, c.ty, c.lx, c.ly, c.rx, c.ry, c.nx, c.ny); }
	return 0;
}
'''


def chev_build(chev_c):
    d = tempfile.mkdtemp(prefix="r98f3d_")
    c = os.path.join(d, "m.c"); open(c, "w").write("#include <stdlib.h>\n" + CHEV)
    cc = os.path.join(d, "aprs_chevron.c"); open(cc, "w", encoding="utf-8").write(chev_c)
    exe = os.path.join(d, "m")
    r = subprocess.run(["gcc", "-std=gnu11", "-w", "-I" + os.path.join(APP, "include"), "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_APRS_RX", "-o", exe, c, cc, "-lm"], capture_output=True)
    return (exe if r.returncode == 0 else None), d


def chev_rows(exe, ln):
    out = subprocess.run([exe, str(ln)], capture_output=True).stdout.decode()
    return [list(map(int, l.split())) for l in out.splitlines()]


def inscribed_ok(rows, ln):
    for b, tx, ty, lx, ly, rx, ry, nx, ny in rows:
        ds = [math.hypot(x - 80, y - 64) for x, y in ((tx, ty), (lx, ly), (rx, ry))]
        if max(ds) - min(ds) > 1.5 or abs(max(ds) - 1.16 * ln) > 1.0:
            return False, (b, [round(v, 2) for v in ds])
    return True, None


def test_part_d():
    src = T.rd(os.path.join(FN, "aprs_chevron.c"))
    worst = []
    for ln in (18, 15, 4):
        exe, d = chev_build(src)
        check(exe is not None, "Д: aprs_chevron.c зібрано")
        if exe is None:
            return
        rows = chev_rows(exe, ln)
        ok, why = inscribed_ok(rows, ln)
        check(len(rows) == 24 and ok, "Д: len %d, азимути 0..345 крок 15: вістря й обидві кутові точки на однаковій відстані (1.16*len ±1) від центру кола: %s" % (ln, why))
        # паритет з CPS
        import screen_views as sv
        par = all([tuple(r[1:]) == tuple(v for p in sv.chevron_geom(80, 64, ln, r[0]) for v in p) for r in rows])
        check(par, "Д: передпоказ CPS (screen_views.chevron_geom) дає ті самі вершини, що прошивка (len %d)" % ln)
        worst.append((ln, max(max(math.hypot(x - 80, y - 64) for x, y in ((r[1], r[2]), (r[3], r[4]), (r[5], r[6]))) for r in rows)))
        shutil.rmtree(d, ignore_errors=True)
    print("Д найбільший радіус вершин (px): %s" % worst)
    m = src.replace("const double sh = 0.16 * L;", "const double sh = 0.0 * L;")
    exe, d = chev_build(m)
    ok, _ = inscribed_ok(chev_rows(exe, 18), 18) if exe else (True, None)
    check(m != src and exe is not None and ok is False, "Д (мутант): старий центр (середина осі) -- ловиться (кутові точки далі від центру, ніж вістря)")
    shutil.rmtree(d, ignore_errors=True)


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    incs, cfgs = cmt.load_configs(FW)
    cf = dict(cfgs)
    t = T.pp(FW, incs, cf["DUALCH"], "application/source/user_interface/uiChannelMode.c") or ""
    test_part_a(t)
    test_part_b(t)
    test_part_v(t)
    test_part_g()
    test_part_d()
    print("test_r98fix3: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
