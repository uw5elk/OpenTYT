#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_r113tonedev.py -- R113-TONEDEV: «Тон-відгук» не лишає девіацію 0x40 (радіо-шар AT1846sSelectVoiceChannel(TONE1) ставить її понад таблицю смуги).

СПРАВЖНІ тексти функцій із прошивки (AT1846sSelectVoiceChannel, I2C_AT1846_set_register_with_mask, AT1846sToneDevSave/Restore, trTxStart/trTxStop)
збираються хостовим gcc з моделлю регістрів AT1846S (0x59 -- девіація, біти 15:6) і моделлю trxSetTone1 (як trx.c/radioSetTone1).
  Д1  стокова поведінка (без правки): під час тону 0x59[15:6] = 0x40, і ПІСЛЯ тону теж 0x40 (гілка MIC «відновлює» вже перезаписане значення) -- вада відтворена.
  Д2  з правкою: під час тону 0x59 == значення каналу (12,5 кГц 0x0B90 і 25 кГц 0x0BA0, повністю, включно з нижніми бітами), після тону -- те саме.
  Д3  читання 0x59 не вдалося -- 0x59 не пишеться правкою (поведінка як стокова), без падіння.
  Д4  скасування (toneReplyAbort -> trTxStop) -- те саме, що штатний кінець: це той самий trTxStop.
  Д5  статичне: `*deviation = 0x40;` у AT1846S.c не змінено; uiTxScreen.c (стокова 1750 Гц) без викликів нових функцій; обгортки -- під ENABLE_TONE_REPLY.
  Д6  мутанти: «без Save», «без Restore у start», «без Restore у stop» -- падають.
Що НЕ доводить: справжній AT1846S (модель регістрів -- маска/зсув як у коді, але не чіп), слух на другій рації -- дослід FTD1..FTD6 (TESTING.md).
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
APP = os.path.join(FW, "application")
TR = os.path.join(APP, "source", "functions", "tone_reply.c")
AT = os.path.join(APP, "source", "hardware", "AT1846S.c")
ATH = os.path.join(APP, "include", "hardware", "AT1846S.h")
TX = os.path.join(APP, "source", "user_interface", "uiTxScreen.c")
FAILS = []
N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        print("ПРОВАЛ:", m)


def rd(p):
    return open(p, encoding="utf-8").read()


def func(text, sig):
    a = text.index(sig)
    b = text.index("\n}\n", a) + 3
    return text[a:b]


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#define taskENTER_CRITICAL() ((void)0)
#define taskEXIT_CRITICAL() ((void)0)
#define AT1846_VOICE_CHANNEL_TONE1 0x10
#define AT1846_VOICE_CHANNEL_TONE2 0x20
#define AT1846_VOICE_CHANNEL_DTMF  0x30
#define AT1846_VOICE_CHANNEL_MIC   0x40
/* модель регістрів AT1846S (без кешу): 16-бітові значення */
static uint16_t R[256]; static int g_readFail, g_w59;
bool radioReadReg2byte(uint8_t reg, uint8_t *h, uint8_t *l) { if (g_readFail && reg == 0x59) { g_readFail = 0; return false; }   /* збій лише першого читання -- того, що робить Save */ *h = R[reg] >> 8; *l = R[reg] & 0xff; return true; }
bool radioWriteReg2byte(uint8_t reg, uint8_t h, uint8_t l) { if (reg == 0x59) g_w59++; R[reg] = (uint16_t)((h << 8) | l); return true; }
bool radioSetClearReg2byteWithMask(uint8_t reg, uint8_t m1, uint8_t m2, uint8_t v1, uint8_t v2)
{ uint8_t h, l; if (!radioReadReg2byte(reg, &h, &l)) return false; h = v1 | (h & m1); l = v2 | (l & m2); return radioWriteReg2byte(reg, h, l); }
@@SET@@
@@SEL@@
@@WRAP@@
/* trx.c: trxSelectVoiceChannel/radioSetTone1 -- збережені значення статичні (0xff), радіо-шар їх заповнює/відновлює */
static uint8_t trxSaveVoiceGainTx = 0xff; static uint16_t trxSaveDeviation = 0xff;
static void trxSetTone1(int f) { AT1846sSelectVoiceChannel(f > 0 ? AT1846_VOICE_CHANNEL_TONE1 : AT1846_VOICE_CHANNEL_MIC, &trxSaveVoiceGainTx, &trxSaveDeviation); }
/* заглушки tone_reply.c */
typedef struct { uint32_t txFreq; int txTone; int rxTone; } chan_t;
static chan_t g_chan = { 145500000U, 0, 0 }; static chan_t *currentChannelData = &g_chan;
typedef struct { uint32_t freqHz; } cfg_t; static cfg_t s_trCfg = { 1000 };
static uint32_t s_trTxFreq;
enum { ECOPHASE_POWERSAVE_INACTIVE = 0, LED_GREEN = 0, LED_RED = 1, RADIO_DEVICE_PRIMARY = 0, UI_CHANNEL_MODE = 3, UI_VFO_MODE = 4, QSO_DISPLAY_DEFAULT_SCREEN = 1 };
static struct { int displayQSOState; } uiDataGlobal; static bool trxTransmissionEnabled, trxIsTransmitting;
static void rxPowerSavingSetState(int s) { (void)s; } static void LedWrite(int l, int v) { (void)l; (void)v; } static void HRC6000ClearIsWakingState(void) {}
static void trxSetTxCSS(int t) { (void)t; } static void trxSetRxCSS(int d, int t) { (void)d; (void)t; }
static void trxSetTX(void) { trxTransmissionEnabled = true; trxIsTransmitting = true; } static void trxActivateRx(bool b) { (void)b; }
static int menuSystemGetCurrentMenuNumber(void) { return UI_CHANNEL_MODE; }
static uint16_t s_trDev; static bool s_trDevOk;
@@START@@
@@STOP@@
static int dev(void) { return R[0x59] >> 6; }
int main(void)
{
	static const uint16_t init[2] = { 0x0B90, 0x0BA0 };   /* таблиці смуги: 12,5 і 25 кГц */
	for (int i = 0; i < 2; i++)
	{
		for (int mode = 0; mode < 3; mode++)   /* 0 -- правка, 1 -- стокова (лише trxSetTone1), 2 -- читання 0x59 не вдається */
		{
			memset(R, 0, sizeof R); R[0x41] = 0x0055; R[0x59] = init[i]; trxSaveVoiceGainTx = 0xff; trxSaveDeviation = 0xff; g_w59 = 0; g_readFail = (mode == 2) ? 1 : 0;
			s_trDevOk = false; trxTransmissionEnabled = trxIsTransmitting = false;
			if (mode == 1) trxSetTone1(1000); else trTxStart();
			printf("I%d M%d during %04X %d\n", i, mode, R[0x59], dev());
			if (mode == 1) trxSetTone1(0); else trTxStop();
			printf("I%d M%d after  %04X %d gain41=%04X\n", i, mode, R[0x59], dev(), R[0x41]);
		}
	}
	return 0;
}
'''


def build(tr_text, at_text):
    h = HARNESS
    wrap = func(at_text, "bool AT1846sToneDevSave(") + func(at_text, "void AT1846sToneDevRestore(")
    sel = func(at_text, "void AT1846sSelectVoiceChannel(").replace("#warning REASON FOR HARDCODED VALUE ??\n", "")
    setf = func(at_text, "void I2C_AT1846_set_register_with_mask(")
    h = h.replace("@@SET@@", setf).replace("@@SEL@@", sel).replace("@@WRAP@@", wrap)
    h = h.replace("@@START@@", func(tr_text, "static void trTxStart(void)")).replace("@@STOP@@", func(tr_text, "static void trTxStop(void)"))
    return h


def run(tr_text, at_text, tag):
    with tempfile.TemporaryDirectory() as t:
        c = os.path.join(t, "h.c")
        open(c, "w", encoding="utf-8").write(build(tr_text, at_text))
        r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-Wno-unused-variable", "-o", os.path.join(t, "h"), c], capture_output=True, text=True)
        if r.returncode != 0:
            check(False, "%s: збірка harness: %s" % (tag, r.stderr[-600:]))
            return None
        r = subprocess.run([os.path.join(t, "h")], capture_output=True, text=True)
        out = {}
        for ln in r.stdout.splitlines():
            m = re.match(r"I(\d) M(\d) (during|after)\s+([0-9A-F]{4}) (\d+)", ln)
            if m:
                out[(int(m.group(1)), int(m.group(2)), m.group(3))] = (int(m.group(4), 16), int(m.group(5)))
        return out


def verdict(out):
    """Список порушень очікуваної поведінки (порожній -- усе гаразд)."""
    bad = []
    init = (0x0B90, 0x0BA0)
    for i in (0, 1):
        for key, want_dev in ((("during"), None), (("after"), None)):
            pass
        # правка (режим 0): девіація каналу і під час, і після тону
        for ph in ("during", "after"):
            v = out.get((i, 0, ph))
            if v is None or v[0] != init[i]:
                bad.append("правка I%d %s: 0x59=%s (чекали %04X)" % (i, ph, ("%04X" % v[0]) if v else "?", init[i]))
        # стокова вада відтворена: 0x40 під час і після
        for ph in ("during", "after"):
            v = out.get((i, 1, ph))
            if v is None or v[1] != 0x40:
                bad.append("стокова I%d %s: dev=%s (чекали 0x40 -- вада має відтворюватись)" % (i, ph, v))
        # читання 0x59 не вдалося: як стокова
        for ph in ("during", "after"):
            v = out.get((i, 2, ph))
            if v is None or v[1] != 0x40:
                bad.append("збій читання I%d %s: dev=%s (чекали стокову 0x40, без запису правкою)" % (i, ph, v))
    return bad


def main():
    tr, at = rd(TR), rd(AT)
    out = run(tr, at, "Д1-Д4")
    if out is not None:
        check(len(out) == 12, "Д1: harness дав %d рядків (чекали 12)" % len(out))
        bad = verdict(out)
        check(not bad, "Д1-Д4: " + "; ".join(bad[:6]))
        print("модель: 12,5 кГц під час тону 0x%04X, після 0x%04X; стокова: під час dev=0x%X, після dev=0x%X" %
              (out[(0, 0, "during")][0], out[(0, 0, "after")][0], out[(0, 1, "during")][1], out[(0, 1, "after")][1]))
    # Д5
    check("*deviation = 0x40;" in at, "Д5: у AT1846S.c лишився `*deviation = 0x40;` (стокова поведінка радіо-шару не змінена)")
    atc = at[at.index("void AT1846sSelectVoiceChannel("):]
    atc = atc[:atc.index("\n}\n")]
    check("ToneDev" not in atc, "Д5: AT1846sSelectVoiceChannel не викликає нових функцій")
    txs = rd(TX)
    check("AT1846sToneDev" not in txs and "trxSetTone1(1750)" in txs, "Д5: uiTxScreen.c (стокова 1750 Гц) не чіпано")
    check(re.search(r"#if defined\(ENABLE_TONE_REPLY\)\nbool AT1846sToneDevSave\(", at) is not None, "Д5: обгортки в AT1846S.c -- під #if defined(ENABLE_TONE_REPLY)")
    check(re.search(r"#if defined\(ENABLE_TONE_REPLY\)\n[^#]*AT1846sToneDevSave\([^#]*AT1846sToneDevRestore\([^#]*#endif", rd(ATH), re.S) is not None, "Д5: оголошення в AT1846S.h -- під #if defined(ENABLE_TONE_REPLY)")
    start = func(tr, "static void trTxStart(void)")
    check(start.index("AT1846sToneDevSave") < start.index("trxSetTone1(") < start.index("AT1846sToneDevRestore"), "Д5: trTxStart: Save -> trxSetTone1 -> Restore")
    stop = func(tr, "static void trTxStop(void)")
    check(stop.index("trxSetTone1(0)") < stop.index("AT1846sToneDevRestore"), "Д5: trTxStop: trxSetTone1(0) -> Restore")
    # Д6 мутанти
    for name, t2 in (("без Save (s_trDevOk = false)", tr.replace("s_trDevOk = AT1846sToneDevSave(&s_trDev);", "s_trDevOk = false;")),
                     ("без Restore у start", re.sub(r"(trxSetTone1\(\(int\)s_trCfg\.freqHz\);[^\n]*\n\tif \(s_trDevOk\)\n\t\{\n)\t\tAT1846sToneDevRestore\(s_trDev\);\n", r"\1", tr, count=1)),
                     ("без Restore у stop", re.sub(r"(trxSetTone1\(0\);[^\n]*\n\tif \(s_trDevOk\)\n\t\{\n[^\n]*\n)\t\tAT1846sToneDevRestore\(s_trDev\);\n", r"\1", tr, count=1))):
        check(t2 != tr, "Д6: мутант «%s» застосовано" % name)
        o2 = run(t2, at, "мутант " + name)
        check(o2 is not None and bool(verdict(o2)), "Д6: мутант «%s» не спіймано" % name)
    print("test_r113tonedev: перевірок %d, провалів %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
