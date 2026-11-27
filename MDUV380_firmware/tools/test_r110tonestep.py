#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_r110tonestep.py -- R110-TONESTEP: поріг сигналу «Тон-відгуку» з кроком 0,1 с (0..5,0 с, типово 1,0 с), блок 19 v4.

Справжній текст tone_reply.c (хост, -DTONE_REPLY_HOST_TEST) + trmRowText/trmChange з menuToneReply.c (вирізано з файла) + tools/tone_reply_cfg.py.
  П1  межі: 0 / 0,1 / 0,9 / 1,0 / 5,0 с -- збирання/розбір v4, обрізання >50 до 50; рядок меню «Поріг:0.0с» … «Поріг:5.0с», найдовший <= 16 символів.
  П2  «рівно поріг» -- відгук, «на 10 мс менше» -- нема: для 0,1 / 0,5 / 1,0 / 2,3 с (і 0,9 / 5,0); поріг 0 -- будь-яке відкриття (сплеск 10 мс).
  П3  міграція: v3 (цілі секунди) 0..5 -> ×10; v3 6..255 -> 50 (обрізання ДО множення, без переповнення байта); v2 -> 10 з «увімкнено»; v1 -> як R100 + 10;
      сміття -> типові (1000 Гц / 10 с / 2 с / 10), вимкнено; v4 >50 -> 50.
  П4  меню ←/→: крок 0,1 с (1 одиниця), межі 0 і 50 не переходяться.
  П5  C == Python: розбір/збирання на всіх 256 значеннях [6] для v1..v4 і невідомої версії; parse_thresh_s (кома/крапка, округлення до 0,1, межі).
  П6  мутанти: крок у секундах (×1000), поріг ігнорується, «>» замість «>=», без обрізання, v3 не множиться на 10 -- ловляться.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
APP = os.path.join(FW, "application")
INC = os.path.join(APP, "include")
SRC = os.path.join(APP, "source", "functions", "tone_reply.c")
MENU = os.path.join(APP, "source", "user_interface", "menuToneReply.c")
sys.path.insert(0, HERE)
FAILS = []
N = [0]
QUIET = [False]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        if not QUIET[0]:
            print("ПРОВАЛ:", m)


def rd(p):
    return open(p, encoding="utf-8").read()


def carve(text, start, end):
    a = text.index(start)
    b = text.index(end, a)
    return text[a:b]


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/tone_reply.h"
#include "user_interface/languages/tonereply_ua.h"
static toneReplyCfg_t g_cfg; static bool g_en;
toneReplyCfg_t *toneReplyCfg(void) { return &g_cfg; }
bool toneReplyIsEnabled(void) { return g_en; }
void toneReplySetEnabled(bool on) { g_en = on; }
enum { TRM_ON = 0, TRM_FREQ, TRM_DUR, TRM_DELAY, TRM_THRESH, TRM_ROWS };
@@ROW@@
@@CHG@@
static toneReplyCfg_t cfgTh(int ds) { toneReplyCfg_t c; c.freqHz = 1000; c.durS = 1; c.delayS = 0; c.threshDs = (uint8_t)ds; return c; }
/* сигнал [0, sig) мс; чи був відгук */
static int reply(int ds, uint32_t sig)
{
	toneReplySm_t s; memset(&s, 0, sizeof s); toneReplyCfg_t c = cfgTh(ds); int st = 0;
	for (uint32_t t = 0; t <= sig + 4000; t += 10)
	{
		int act = toneReplyStep(&s, 100000U + t, true, (t >= 10) && (t < 10 + sig), true, false, &c);
		if (act == TR_ACT_START) { st = 1; }
	}
	return st;
}
int main(void)
{
	int eq[] = { 1, 5, 9, 10, 23, 50 };
	for (int i = 0; i < 6; i++) { printf("EQ %d %d %d\n", eq[i], reply(eq[i], (uint32_t)eq[i] * 100U), reply(eq[i], (uint32_t)eq[i] * 100U - 10U)); }
	printf("ZERO %d %d\n", reply(0, 10), reply(0, 100));
	printf("SIG03 %d %d\n", reply(5, 300), reply(3, 300));
	unsigned b[8];
	while (scanf("%x %x %x %x %x %x %x %x", &b[0], &b[1], &b[2], &b[3], &b[4], &b[5], &b[6], &b[7]) == 8)
	{
		toneReplyOnFlash_t raw; uint8_t *p = (uint8_t *)&raw; toneReplyCfg_t c; bool en = false;
		for (int i = 0; i < 8; i++) p[i] = (uint8_t)b[i];
		int v = toneReplyCfgParse(&raw, &c, &en);
		toneReplyOnFlash_t o; toneReplyCfgBuild(&o, &c, en); const uint8_t *q = (const uint8_t *)&o;
		printf("P %d %d %u %u %u %u ", v, (int)en, c.freqHz, c.durS, c.delayS, c.threshDs);
		for (int i = 0; i < 8; i++) printf("%02x", q[i]);
		printf("\n");
	}
	/* меню */
	int rows[] = { 0, 1, 9, 10, 25, 50 };
	for (int i = 0; i < 6; i++) { char buf[32]; int opt = 0; g_cfg = cfgTh(rows[i]); trmRowText(TRM_THRESH, buf, sizeof buf, &opt); printf("ROW %d %s|%d\n", rows[i], buf, opt); }
	g_cfg = cfgTh(0); trmChange(TRM_THRESH, -1); printf("TMIN %u\n", g_cfg.threshDs);
	g_cfg = cfgTh(50); trmChange(TRM_THRESH, 1); printf("TMAX %u\n", g_cfg.threshDs);
	g_cfg = cfgTh(10); trmChange(TRM_THRESH, 1); printf("TUP %u\n", g_cfg.threshDs);
	g_cfg = cfgTh(10); trmChange(TRM_THRESH, -1); printf("TDN %u\n", g_cfg.threshDs);
	g_cfg = cfgTh(1); trmChange(TRM_THRESH, -1); printf("T1DN %u\n", g_cfg.threshDs);
	return 0;
}
'''


def grid():
    out = []
    for ver in (0, 1, 2, 3, 4, 5, 0xFF):
        for th in range(256):
            f = (300, 1000, 1750, 3000, 3001, 0)[th % 6]
            out.append(bytes([ver, (th * 7) % 256, (th * 3) % 256, th % 4, f & 0xFF, f >> 8, th, th % 3]))
    out.append(bytes([0xFF] * 8))
    out += [bytes([2, 0, 3, 1, 0, 0, 2, 2]), bytes([1, 7, 3, 1, 0xE8, 0x03, 1, 1])]   # явні v2 / v1 для П3
    return out


def run_c(src_text, payloads):
    d = tempfile.mkdtemp(prefix="r110_")
    try:
        menu = rd(MENU)
        row = carve(menu, "static void trmRowText(int row, char *buf, size_t cap, int *opt)", "static void trmUpdate(void)\n{")
        chg = carve(menu, "static void trmChange(int row, int dir)", "static void trmExit(void *data)\n{")
        hp = os.path.join(d, "h.c")
        open(hp, "w", encoding="utf-8").write(HARNESS.replace("@@ROW@@", row).replace("@@CHG@@", chg))
        sp = os.path.join(d, "tone_reply.c")
        open(sp, "w", encoding="utf-8").write(src_text)
        exe = os.path.join(d, "h")
        r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-DTONE_REPLY_HOST_TEST", "-I" + INC, "-o", exe, hp, sp], capture_output=True)
        if r.returncode != 0:
            return None, r.stderr.decode("utf-8", "replace")[-1500:]
        inp = "\n".join(" ".join("%x" % x for x in p) for p in payloads) + "\n"
        o = subprocess.run([exe], input=inp.encode(), capture_output=True, timeout=120).stdout.decode("cp1251")
        return o, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def core(out, trc, payloads, tag=""):
    ok = [True]

    def want(c, m):
        ok[0] = ok[0] and bool(c)
        check(c, m + tag)
    lines = out.splitlines()
    eq = {int(x.split()[1]): (x.split()[2], x.split()[3]) for x in lines if x.startswith("EQ ")}
    want(all(eq.get(k) == ("1", "0") for k in (1, 5, 9, 10, 23, 50)), "П2: рівно поріг -- відгук, на 10 мс менше -- нема (0,1/0,5/0,9/1,0/2,3/5,0 с): %r" % eq)
    z = [x for x in lines if x.startswith("ZERO ")]
    want(z == ["ZERO 1 1"], "П2: поріг 0 -- відгук і на сплеск 10 мс: %r" % z)
    s = [x for x in lines if x.startswith("SIG03 ")]
    want(s == ["SIG03 0 1"], "П2: сигнал 0,3 с: поріг 0,5 -- нема, поріг 0,3 -- є: %r" % s)
    pl = [x for x in lines if x.startswith("P ")]
    want(len(pl) == len(payloads), "П5: C розібрав усі %d блоків (є %d)" % (len(payloads), len(pl)))
    C = {}
    for p, l in zip(payloads, pl):
        C[p] = l.split()[1:]
    # П1 / П3 з C
    def c_of(b):
        return C.get(bytes(b))
    for th in range(256):
        r = c_of([3, (th * 7) % 256, (th * 3) % 256, th % 4, *((300, 1000, 1750, 3000, 3001, 0)[th % 6].to_bytes(2, "little")), th, th % 3])
        want(r is not None and r[0] == "3" and int(r[5]) == (th * 10 if th <= 5 else 50), "П3: v3 поріг %d с -> %s (очікується %d): %r" % (th, r and r[5], th * 10 if th <= 5 else 50, r))
        r4 = c_of([4, (th * 7) % 256, (th * 3) % 256, th % 4, *((300, 1000, 1750, 3000, 3001, 0)[th % 6].to_bytes(2, "little")), th, th % 3])
        want(r4 is not None and r4[0] == "4" and int(r4[5]) == min(th, 50) and r4[6][:2] == "04" and int(r4[6][12:14], 16) == min(th, 50),
             "П1: v4 поріг %d -> %s, запис v4 [6]=%s: %r" % (th, r4 and r4[5], r4 and r4[6][12:14], r4))
    r2 = c_of([2, 0, 3, 1, 0, 0, 2, 2])
    want(r2 is not None and r2[0] == "2" and r2[1] == "1" and r2[5] == "10", "П3: v2 -> поріг 1,0 с, «увімкнено» збережено: %r" % r2)
    r1 = c_of([1, 7, 3, 1, 0xE8, 0x03, 1, 1])
    want(r1 is not None and r1[0] == "1" and r1[1] == "0" and r1[5] == "10", "П3: v1 -> вимкнено, поріг 1,0 с: %r" % r1)
    rj = c_of([0xFF] * 8)
    want(rj == ["0", "0", "1000", "10", "2", "10", "040a0200e8030a00"], "П3: сміття -- типові 1000/10/2/1,0, вимкнено: %r" % rj)
    # П1 меню
    rows = dict(re.findall(r"^ROW (\d+) (.*)$", out, re.M))
    exp = {"0": "Поріг:0.0с|6", "1": "Поріг:0.1с|6", "9": "Поріг:0.9с|6", "10": "Поріг:1.0с|6", "25": "Поріг:2.5с|6", "50": "Поріг:5.0с|6"}
    want(rows == exp, "П1: рядок меню «Поріг:N.Nс»: %r" % rows)
    want(all(len(v.split("|")[0]) <= 16 for v in rows.values()), "П1: рядок меню <= 16 символів")
    # П4
    st = dict(re.findall(r"^(TMIN|TMAX|TUP|TDN|T1DN) (\d+)$", out, re.M))
    want(st == {"TMIN": "0", "TMAX": "50", "TUP": "11", "TDN": "9", "T1DN": "0"}, "П4: ←/→ крок 0,1 с, межі 0 і 5,0 с: %r" % st)
    # П5 C == Python
    if trc is not None:
        mism = []
        for p in payloads:
            st_ = trc.parse_payload(p)
            py = [str(st_["version"]), str(int(st_["enabled"])), str(st_["freq"]), str(st_["dur"]), str(st_["delay"]), str(st_["thresh_ds"]),
                  trc.build_payload(st_["enabled"], st_["freq"], st_["dur"], st_["delay"], st_["thresh_ds"]).hex()]
            if py != C.get(p):
                mism.append((p.hex(), C.get(p), py))
        want(not mism, "П5: Python == C на %d блоках; розбіжностей %d, перші: %r" % (len(payloads), len(mism), mism[:3]))
    return ok[0]


def py_checks(trc):
    cases = {"0": 0, "0,1": 1, "0.1": 1, "0,9": 9, "1": 10, "1,0": 10, " 2.3 ": 23, "5": 50, "5,0": 50, "0,05": 1, "0,04": 0, "1,25": 13, "4,95": 50, "0.15": 2}
    got = {}
    for k in cases:
        try:
            got[k] = trc.parse_thresh_s(k)
        except trc.ToneCfgError as e:
            got[k] = "ERR %s" % e
    check(got == cases, "П5: parse_thresh_s (кома/крапка, округлення до 0,1, половина вгору): %r" % {k: got[k] for k in cases if got[k] != cases[k]})
    bad = 0
    for b in ("5,1", "6", "-0,1", "", "x", "1,2,3", "nan", "inf", "5.05"):
        try:
            trc.parse_thresh_s(b)
        except trc.ToneCfgError:
            bad += 1
    check(bad == 9, "П5: поза межами / не число -- помилка (%d з 9)" % bad)
    check(trc.fmt_thresh(0) == "0,0" and trc.fmt_thresh(10) == "1,0" and trc.fmt_thresh(50, ".") == "5.0", "П5: fmt_thresh")
    check(trc.MIRROR["CFG_VERSION"] == 4 and trc.MIRROR["THRESH_MAX_DS"] == 50 and trc.MIRROR["THRESH_DEF_DS"] == 10 and trc.MIRROR["THRESH_STEP_DS"] == 1 and
          trc.MIRROR["CFG_V3"] == 3, "П5: дзеркало MIRROR -- v4, 0..50, типово 10, крок 1")
    hdr = trc.parse_header()
    check(hdr is not None and all(hdr.get(k) == v for k, v in trc.MIRROR.items()), "П5: MIRROR == tone_reply.h")
    w = trc.warnings(True, 10, 0)
    check(any("сплесків шуму" in x for x in w) and not any("сплесків шуму" in x for x in trc.warnings(True, 10, 1)), "П5: попередження «поріг 0» -- лише для 0, не для 0,1 с")


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема -- test_r110tonestep не виконано (це не «пройдено»)")
        FAILS.append("gcc нема")
        return 1
    import tone_reply_cfg as trc
    src = rd(SRC)
    payloads = grid()
    out, err = run_c(src, payloads)
    check(out is not None, "0: хостова збірка tone_reply.c + menuToneReply (trmRowText/trmChange): %s" % err)
    if out is None:
        print("test_r110tonestep: перевірок %d, провалів %d" % (N[0], len(FAILS)))
        return 1
    core(out, trc, payloads)
    py_checks(trc)

    # П6: мутанти tone_reply.c
    def mut(name, a, b):
        s2 = src.replace(a, b, 1)
        if s2 == src:
            check(False, "П6 (%s): шаблон не знайдено" % name)
            return
        o2, _e = run_c(s2, payloads)
        if o2 is None:
            check(True, "")
            return
        n0 = len(FAILS)
        QUIET[0] = True
        good = core(o2, None, payloads, " [m]")
        QUIET[0] = False
        del FAILS[n0:]
        check(not good, "П6 (%s): ловиться" % name)
    step = "if ((now - s->t) >= ((uint32_t)cfg->threshDs * TONE_REPLY_THRESH_UNIT_MS))"
    mut("крок у секундах", step, "if ((now - s->t) >= ((uint32_t)cfg->threshDs * 1000U))")
    mut("поріг ігнорується", step, "if ((now - s->t) >= 1000U)")
    mut("«>» замість «>=»", step, "if ((now - s->t) > ((uint32_t)cfg->threshDs * TONE_REPLY_THRESH_UNIT_MS))")
    mut("без обрізання", "	if (c->threshDs > TONE_REPLY_THRESH_MAX_DS)\n	{\n		c->threshDs = TONE_REPLY_THRESH_MAX_DS;\n	}", "")
    mut("v3 не множиться на 10", "TONE_REPLY_THRESH_MAX_DS : (raw->thresh * 10U));", "TONE_REPLY_THRESH_MAX_DS : (raw->thresh));")
    mut("v3 без обрізання до множення", "(raw->thresh >= (TONE_REPLY_THRESH_MAX_DS / 10U)) ? TONE_REPLY_THRESH_MAX_DS : (raw->thresh * 10U)", "(uint8_t)(raw->thresh * 10U)")
    print("test_r110tonestep: перевірок %d, провалів %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
