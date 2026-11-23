# -*- coding: utf-8 -*-
"""test_r102tone.py -- R102-TONE: «Тон-відгук» без сторожа; регульований поріг сигналу; умова «свіже відкриття»; блок 19 v3.

Хост: СПРАВЖНІЙ application/source/functions/tone_reply.c (-DTONE_REPLY_HOST_TEST) -- стан-машина toneReplyStep і блок 19 (toneReplyCfgParse/Build).
  А  КОЖЕН сигнал >= порогу дає рівно один відгук; серія з 10 сигналів поспіль -- 10 відгуків, без пауз (крім затримки й тривалості тону);
     сигнал, що почався ЗРАЗУ (в тому самому кроці) після власного тону, не «свіжий» -- пропускається (документовано)
  Б  сигнал < порогу -- без відгуку; поріг 0 -- відгук на будь-яке відкриття (навіть один крок); поріг 5 с; ">=": рівно поріг -- відгук
  В  свіже закриття: шумодав відкритий на старті / зразу після власного тону / при вмиканні функції / на вході на екран, де передача дозволена --
     відгуку нема, доки шумодав не буде спостережено закритим; після закриття -- новий сигнал знову відповідається
  Г  скасування (клавіша/PTT) у затримці й у тоні, заборони TX (до затримки, у затримці, під час сигналу, у тоні), вимкнення в тоні, жорстка межа 60 с
  Д  модель двох рацій: обидві з функцією -- відповіді можуть йти НЕСКІНЧЕННО (тест ДОКУМЕНТУЄ це як відому властивість, у моделі -- обмежена кількість
     кроків; захисту від зациклення у прошивці немає -- рішення власника); одна з функцією -- кожен сигнал іншої дає рівно ОДИН відгук
  Е  блок 19: v3 запис/читання (поріг), міграція v2 -> v3 (поріг 1, «увімкнено» зберігається), v1 -> v3, невідома версія/сміття -- типові
  Є  мутанти: є пауза після відгуку; нема умови свіжого закриття; поріг ігнорується; поріг не зберігається; v2 бере поріг з байта [6]; жорстка межа
Запуск: python3 tools/test_r102tone.py"""
import os, re, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
SRC = os.path.join(APP, "source", "functions", "tone_reply.c")
HDR = os.path.join(APP, "include", "functions", "tone_reply.h")
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


HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "functions/tone_reply.h"

#define BASE 100000U
typedef struct { uint32_t a, b; } iv_t;
static int inIv(const iv_t *v, int n, uint32_t t) { for (int i = 0; i < n; i++) if ((t >= v[i].a) && (t < v[i].b)) return 1; return 0; }
static toneReplyCfg_t cfgOf(int d, int dl, int th) { toneReplyCfg_t c; c.freqHz = 1000; c.durS = (uint8_t)d; c.delayS = (uint8_t)dl; c.threshS = (uint8_t)th; return c; }

/* Одна рація. sig -- інтервали, коли в ефірі сигнал (чути, якщо рація сама не передає); na -- коли передача ЗАБОРОНЕНА; dis -- функцію вимкнено;
 * cn -- моменти скасування (клавіша/PTT, один крок). Початковий стан -- WAITCLOSE, як після toneReplyLoad(); cold=0 -- перед сценарієм один крок із
 * ЗАКРИТИМ шумодавом (як на рації: шумодав зазвичай закритий на старті), cold=1 -- без нього (шумодав відкритий вже на першому кроці). */
static void run(const char *tag, toneReplyCfg_t c, const iv_t *sig, int ns, const iv_t *na, int nna, const iv_t *dis, int nd, const uint32_t *cn, int nc, uint32_t end, int cold)
{
	toneReplySm_t s; memset(&s, 0, sizeof s);
	s.state = TR_ST_WAITCLOSE;
	if (cold == 0) (void)toneReplyStep(&s, BASE - 10U, 1, 0, 1, 0, &c);
	printf("%s", tag);
	for (uint32_t t = 0; t <= end; t += 10)
	{
		int rx = inIv(sig, ns, t) && (s.state != TR_ST_TX);
		int allowed = !inIv(na, nna, t), en = !inIv(dis, nd, t), cancel = 0;
		for (int i = 0; i < nc; i++) if (cn[i] == t) cancel = 1;
		int act = toneReplyStep(&s, BASE + t, en, rx, allowed, cancel, &c);
		if (act == TR_ACT_START) printf(" S%u", (unsigned)t);
		if (act == TR_ACT_STOP) printf(" E%u", (unsigned)t);
	}
	printf("\n");
}
#define RUN(tag, c, sig, na, dis, cn, end) run(tag, c, sig, sizeof(sig)/sizeof(sig[0]), na, sizeof(na)/sizeof(na[0]), dis, sizeof(dis)/sizeof(dis[0]), cn, sizeof(cn)/sizeof(cn[0]), end, 0)
#define RUNCOLD(tag, c, sig, na, dis, cn, end) run(tag, c, sig, sizeof(sig)/sizeof(sig[0]), na, sizeof(na)/sizeof(na[0]), dis, sizeof(dis)/sizeof(dis[0]), cn, sizeof(cn)/sizeof(cn[0]), end, 1)

static const iv_t NOIV[1] = { { 0, 0 } };
static const uint32_t NOCN[1] = { 0xFFFFFFFFU };

/* серія з n сигналів по 2 с з періодом p мс */
static void series(const char *tag, int n, uint32_t p, toneReplyCfg_t c)
{
	iv_t sig[16];
	for (int i = 0; i < n; i++) { sig[i].a = (uint32_t)i * p; sig[i].b = sig[i].a + 2000U; }
	run(tag, c, sig, n, NOIV, 1, NOIV, 1, NOCN, 1, (uint32_t)n * p + 20000U, 0);
}

/* власна передача користувача [1000, 1000 + len): передача заборонена, приймач глухий; шумодав відкрито (шум/сигнал) з моменту відпускання PTT до 20 с.
 * Паритет кроку перебираємо len = 1000..1030 -- відгуку бути не повинно (відкритий після власної передачі шумодав -- не свіжий сигнал). */
static void ownTx(const char *tag, toneReplyCfg_t c)
{
	int n = 0;
	for (uint32_t len = 1000; len <= 1030; len += 10)
	{
		toneReplySm_t s; memset(&s, 0, sizeof s); s.state = TR_ST_WAITCLOSE; (void)toneReplyStep(&s, BASE - 10U, 1, 0, 1, 0, &c);
		for (uint32_t t = 0; t <= 40000; t += 10)
		{
			int mine = (t >= 1000) && (t < 1000 + len);
			int rx = !mine && (t >= 1000 + len - 20) && (t < 20000);
			if (toneReplyStep(&s, BASE + t, 1, rx, !mine, 0, &c) == TR_ACT_START) n++;
		}
	}
	printf("%s %d\n", tag, n);
}

/* дві рації: A (cfg a) і B (cfg b) чують одна одну (не свій тон). Людина передає [0, 2000) і чутна обом. nsteps -- обмеження кроків моделі (мс). */
static void two(const char *tag, toneReplyCfg_t a_c, int a_en, toneReplyCfg_t b_c, int b_en, uint32_t end)
{
	toneReplySm_t a, b; memset(&a, 0, sizeof a); memset(&b, 0, sizeof b);
	a.state = TR_ST_WAITCLOSE; b.state = TR_ST_WAITCLOSE;
	int txA = 0, txB = 0, nA = 0, nB = 0; uint32_t lastStart = 0;
	for (uint32_t t = 0; t <= end; t += 10)
	{
		int human = (t >= 100) && (t < 2100);
		int ra = (human || txB) && !txA, rb = (human || txA) && !txB;
		int x = toneReplyStep(&a, BASE + t, a_en, ra, 1, 0, &a_c), y = toneReplyStep(&b, BASE + t, b_en, rb, 1, 0, &b_c);
		if (x == TR_ACT_START) { txA = 1; nA++; lastStart = t; } else if (x == TR_ACT_STOP) txA = 0;
		if (y == TR_ACT_START) { txB = 1; nB++; lastStart = t; } else if (y == TR_ACT_STOP) txB = 0;
	}
	printf("%s %d %d %d %d %u\n", tag, nA, nB, txA, txB, (unsigned)lastStart);
}

/* одна рація A з функцією, станція X (без функції): n сигналів по 2 с з періодом p; X сама не відповідає на тони A */
static void oneWithPlain(const char *tag, int n, uint32_t p, toneReplyCfg_t c)
{
	toneReplySm_t s; memset(&s, 0, sizeof s); s.state = TR_ST_WAITCLOSE;
	int nA = 0, tx = 0; uint32_t end = (uint32_t)n * p + 200000U;
	for (uint32_t t = 0; t <= end; t += 10)
	{
		int human = 0; for (int i = 0; i < n; i++) if ((t >= (uint32_t)i * p + 100U) && (t < (uint32_t)i * p + 2100U)) human = 1;
		int act = toneReplyStep(&s, BASE + t, 1, human && !tx, 1, 0, &c);
		if (act == TR_ACT_START) { tx = 1; nA++; } else if (act == TR_ACT_STOP) tx = 0;
	}
	printf("%s %d %d\n", tag, nA, tx);
}

int main(void)
{
	toneReplyCfg_t c = cfgOf(1, 1, 1);
	/* А */
	series("SER10", 10, 4020, c);       /* 10 сигналів, період 4,02 с: кожен чутно закритим перед наступним */
	series("SER10B", 10, 4010, c);      /* наступний сигнал починається в тому самому кроці, що й кінець тону -- «не свіжий» */
	series("SER10C", 10, 3600, c);      /* наступний сигнал з'являється ще ДО кінця тону -- чути лише після тону: не свіжий, відкритий */
	{ iv_t sig[] = { { 0, 2000 } }; RUN("ONE", c, sig, NOIV, NOIV, NOCN, 20000); }
	/* Б */
	{ iv_t sig[] = { { 0, 900 } }; RUN("SHORT", c, sig, NOIV, NOIV, NOCN, 20000); }
	{ iv_t sig[] = { { 0, 1000 } }; RUN("EQ1", c, sig, NOIV, NOIV, NOCN, 20000); }
	{ iv_t sig[] = { { 0, 10 } }; RUN("BLIP1", c, sig, NOIV, NOIV, NOCN, 20000); }
	{ iv_t sig[] = { { 0, 10 } }; toneReplyCfg_t c0 = cfgOf(1, 1, 0); RUN("BLIP0", c0, sig, NOIV, NOIV, NOCN, 20000); }
	{ iv_t sig[] = { { 0, 100 } }; toneReplyCfg_t c0 = cfgOf(1, 1, 0); RUN("S100_0", c0, sig, NOIV, NOIV, NOCN, 20000); }
	{ iv_t sig[] = { { 0, 4990 } }; toneReplyCfg_t c5 = cfgOf(1, 1, 5); RUN("T5SHORT", c5, sig, NOIV, NOIV, NOCN, 30000); }
	{ iv_t sig[] = { { 0, 5000 } }; toneReplyCfg_t c5 = cfgOf(1, 1, 5); RUN("T5EQ", c5, sig, NOIV, NOIV, NOCN, 30000); }
	{ iv_t sig[] = { { 0, 3000 } }; toneReplyCfg_t c2 = cfgOf(1, 1, 3); RUN("T3EQ", c2, sig, NOIV, NOIV, NOCN, 30000); }
	{ iv_t sig[] = { { 0, 2990 } }; toneReplyCfg_t c2 = cfgOf(1, 1, 3); RUN("T3SHORT", c2, sig, NOIV, NOIV, NOCN, 30000); }
	/* В */
	{ iv_t sig[] = { { 0, 3000 } }; RUNCOLD("OPENSTART", c, sig, NOIV, NOIV, NOCN, 20000); }                      /* шумодав відкритий на старті -- мовчимо */
	{ iv_t sig[] = { { 0, 3000 }, { 9000, 11000 } }; RUNCOLD("OPENSTART2", c, sig, NOIV, NOIV, NOCN, 30000); }    /* ...а новий сигнал після закриття -- відповідаємо */
	{ iv_t sig[] = { { 0, 2000 }, { 3500, 30000 } }; RUN("AFTERTX", c, sig, NOIV, NOIV, NOCN, 50000); }       /* під час власного тону відкрився постійний шум: після тону -- не «свіжий» */
	{ iv_t sig[] = { { 0, 8000 } }; iv_t dis[] = { { 0, 5000 } }; RUN("ENABLE", c, sig, NOIV, dis, NOCN, 30000); } /* функцію ввімкнено при відкритому шумодаві */
	{ iv_t sig[] = { { 0, 8000 }, { 12000, 14000 } }; iv_t dis[] = { { 0, 5000 } }; RUN("ENABLE2", c, sig, NOIV, dis, NOCN, 40000); }
	{ iv_t sig[] = { { 1000, 9000 } }; iv_t na[] = { { 0, 6000 } }; RUN("SCREEN", c, sig, na, NOIV, NOCN, 30000); }                 /* сигнал почався на іншому екрані */
	{ iv_t sig[] = { { 1000, 9000 }, { 12000, 14000 } }; iv_t na[] = { { 0, 6000 } }; RUN("SCREEN2", c, sig, na, NOIV, NOCN, 40000); }
	/* Г */
	{ iv_t sig[] = { { 0, 2000 } }; uint32_t cn[] = { 2500 }; RUN("CANCD", c, sig, NOIV, NOIV, cn, 20000); }                        /* клавіша в затримці -- без відгуку */
	{ iv_t sig[] = { { 0, 2000 }, { 2600, 4600 } }; uint32_t cn[] = { 2500 }; RUN("CANCD2", c, sig, NOIV, NOIV, cn, 30000); }     /* ...але новий, свіжий сигнал після скасування -- відповідаємо */
	{ iv_t sig[] = { { 0, 2000 } }; uint32_t cn[] = { 3500 }; RUN("CANCT", c, sig, NOIV, NOIV, cn, 20000); }                        /* PTT у тоні -- зупинка в той самий крок */
	{ iv_t sig[] = { { 0, 2000 }, { 3200, 30000 } }; uint32_t cn[] = { 3500 }; RUN("CANCT2", c, sig, NOIV, NOIV, cn, 50000); }     /* після скасування відкритий шум -- не «свіжий» */
	{ iv_t sig[] = { { 0, 2000 } }; iv_t na[] = { { 0, 20000 } }; RUN("NOTX", c, sig, na, NOIV, NOCN, 30000); }
	{ iv_t sig[] = { { 0, 2000 }, { 22000, 24000 } }; iv_t na[] = { { 2500, 3000 } }; RUN("NOTXD", c, sig, na, NOIV, NOCN, 40000); }  /* заборона до кінця затримки -- цикл відкинуто; новий сигнал -- відповідаємо */
	{ iv_t sig[] = { { 0, 3000 } }; iv_t na[] = { { 1000, 1500 } }; RUN("NOTXRX", c, sig, na, NOIV, NOCN, 30000); }               /* заборона під час сигналу -- цикл відкинуто */
	{ iv_t sig[] = { { 0, 2000 } }; iv_t na[] = { { 3500, 3700 } }; RUN("NOTXT", c, sig, na, NOIV, NOCN, 20000); }                  /* заборона в тоні -- зупинка */
	{ iv_t sig[] = { { 0, 2000 } }; iv_t dis[] = { { 3500, 99999 } }; RUN("DISAB", c, sig, NOIV, dis, NOCN, 20000); }
	{ toneReplyCfg_t big = cfgOf(200, 0, 1); iv_t sig[] = { { 0, 2000 } }; RUN("HARD", big, sig, NOIV, NOIV, NOCN, 100000); }     /* «зламана» тривалість -- не більше 60 с */
	ownTx("OWNTX", c);
	/* Д */
	{ toneReplyCfg_t a = cfgOf(1, 1, 1), b = cfgOf(1, 3, 1); two("PING", a, 1, b, 1, 800000U); }           /* затримки 1 і 3 с: відповіді йдуть без кінця */
	{ toneReplyCfg_t a = cfgOf(1, 1, 1); two("SYM", a, 1, a, 1, 800000U); }                                /* однакові: тони одночасні, обмін завмирає */
	{ toneReplyCfg_t a = cfgOf(1, 1, 1); two("ONLYA", a, 1, a, 0, 800000U); }                              /* B без функції: A відповідає людині ОДИН раз, B не відповідає */
	oneWithPlain("PLAIN10", 10, 6000, c);
	oneWithPlain("PLAIN10Z", 10, 6000, cfgOf(1, 0, 0));
	/* Д2: частота обміну по всій таблиці налаштувань (затримка 0/1/10 × тривалість 1/30/60 обох рацій) */
	{
		int lv[] = { 0, 1, 10 }, dv[] = { 1, 30, 60 }; int inf = 0, tot = 0, quiet = 0;
		for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) for (int k = 0; k < 3; k++) for (int l = 0; l < 3; l++)
		{
			toneReplySm_t a, b; memset(&a, 0, sizeof a); memset(&b, 0, sizeof b); a.state = b.state = TR_ST_WAITCLOSE;
			toneReplyCfg_t ca = cfgOf(dv[i], lv[j], 1), cb = cfgOf(dv[k], lv[l], 1); int txA = 0, txB = 0; uint32_t last = 0, E = 3000000U;
			for (uint32_t t = 0; t <= E; t += 50)
			{
				int human = (t >= 100) && (t < 2100);
				int ra = (human || txB) && !txA, rb = (human || txA) && !txB;
				int x = toneReplyStep(&a, BASE + t, 1, ra, 1, 0, &ca), y = toneReplyStep(&b, BASE + t, 1, rb, 1, 0, &cb);
				if (x == TR_ACT_START) { txA = 1; last = t; } else if (x == TR_ACT_STOP) txA = 0;
				if (y == TR_ACT_START) { txB = 1; last = t; } else if (y == TR_ACT_STOP) txB = 0;
			}
			tot++; if (last > E - 400000U) inf++; else quiet++;
		}
		printf("GRID %d %d %d\n", tot, inf, quiet);
	}
	/* Е */
	{
		toneReplyOnFlash_t raw; toneReplyCfg_t k = cfgOf(37, 7, 3), r; bool en = false; const uint8_t *p = (const uint8_t *)&raw; int v;
		k.freqHz = 2450;
		toneReplyCfgBuild(&raw, &k, true);
		v = toneReplyCfgParse(&raw, &r, &en);
		printf("V3 %d %u %u %u %u %d size=%u %02x%02x%02x%02x%02x%02x%02x%02x\n", v, r.freqHz, r.durS, r.delayS, r.threshS, (int)en, (unsigned)sizeof raw, p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7]);
		{ const uint8_t b2[8] = { 2, 30, 5, 1, 0xB0, 0x04, 0, 0 }; memcpy(&raw, b2, 8); v = toneReplyCfgParse(&raw, &r, &en);
		  printf("V2 %d %u %u %u %u %d\n", v, r.freqHz, r.durS, r.delayS, r.threshS, (int)en); }
		{ const uint8_t b2[8] = { 2, 30, 5, 0, 0xB0, 0x04, 4, 9 }; memcpy(&raw, b2, 8); v = toneReplyCfgParse(&raw, &r, &en);
		  printf("V2B %d %u %u %u %u %d\n", v, r.freqHz, r.durS, r.delayS, r.threshS, (int)en); }
		{ const uint8_t b1[8] = { 1, 5, 25, 1, 0xD6, 0x06, 0, 0 }; memcpy(&raw, b1, 8); v = toneReplyCfgParse(&raw, &r, &en);
		  printf("V1 %d %u %u %u %u %d\n", v, r.freqHz, r.durS, r.delayS, r.threshS, (int)en); }
		{ const uint8_t bj[8] = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF }; memcpy(&raw, bj, 8); v = toneReplyCfgParse(&raw, &r, &en);
		  printf("JUNK %d %u %u %u %u %d\n", v, r.freqHz, r.durS, r.delayS, r.threshS, (int)en); }
		{ const uint8_t b3[8] = { 3, 30, 5, 1, 0xB0, 0x04, 99, 0 }; memcpy(&raw, b3, 8); v = toneReplyCfgParse(&raw, &r, &en);
		  printf("V3BIG %d %u %u %u %u %d\n", v, r.freqHz, r.durS, r.delayS, r.threshS, (int)en); }
		{ int tt[] = { 0, 1, 2, 3, 4, 5 }; printf("V3EACH"); for (int i = 0; i < 6; i++) { toneReplyCfg_t q = cfgOf(10, 2, tt[i]); q.freqHz = 1000; toneReplyCfgBuild(&raw, &q, false); toneReplyCfgParse(&raw, &r, &en); printf(" %u", r.threshS); } printf("\n"); }
		{ toneReplyCfg_t q = cfgOf(10, 2, 200); toneReplyCfgClamp(&q); printf("CLAMPT %u\n", q.threshS); }
	}
	return 0;
}
'''


def build(src_text, hdr_text=None):
    d = tempfile.mkdtemp(prefix="r102tone_")
    try:
        inc = os.path.join(APP, "include")
        extra = []
        if hdr_text is not None:
            os.makedirs(os.path.join(d, "functions"))
            open(os.path.join(d, "functions", "tone_reply.h"), "w", encoding="utf-8").write(hdr_text)
            extra = ["-I" + d]
        srcp = os.path.join(d, "tone_reply.c"); open(srcp, "w", encoding="utf-8").write(src_text)
        hp = os.path.join(d, "h.c"); open(hp, "w").write(HARNESS)
        exe = os.path.join(d, "h")
        r = subprocess.run(["gcc", "-std=gnu11", "-Wall", "-Wno-unused-function", "-DTONE_REPLY_HOST_TEST"] + extra + ["-I" + inc, "-o", exe, hp, srcp], capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-1800:]
        return subprocess.run([exe], capture_output=True, text=True, timeout=300).stdout, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def parse(out):
    res = {}
    for l in out.splitlines():
        p = l.split(None, 1)
        if not p:
            continue
        res[p[0]] = p[1] if len(p) > 1 else ""
    return res


def events(v):
    return [(x[0], int(x[1:])) for x in (v or "").split()] if v is not None else None


def core_checks(out, tag=""):
    L = parse(out)
    ok = [True]

    def want(c, m):
        ok[0] = ok[0] and bool(c)
        check(c, m + tag)

    def ev(name):
        return events(L.get(name))

    def S(name):
        return [t for (k, t) in (ev(name) or []) if k == "S"]
    # А
    want(ev("ONE") == [("S", 3000), ("E", 4000)], "А0: сигнал 2 с -> тон після затримки 1 с (3000 мс) тривалістю 1 с: %r" % ev("ONE"))
    s10 = S("SER10")
    want(len(s10) == 10 and all(s10[i] == i * 4020 + 3000 for i in range(10)),
         "А1: серія з 10 сигналів (період 4,02 с, тон 3..4 с після початку) -- РІВНО 10 відгуків, без пауз між ними: %r" % s10)
    s10b = S("SER10B")
    want(len(s10b) == 5, "А2: сигнал, що почався в тому самому кроці, коли скінчився власний тон, -- не «свіжий» і пропускається (5 з 10): %r" % s10b)
    s10c = S("SER10C")
    want(len(s10c) == 5, "А3: сигнал, що з'явився ще під час власного тону й відкритий після нього -- не «свіжий» (5 з 10): %r" % s10c)
    # Б
    want(ev("SHORT") == [], "Б1: сигнал 0,9 с при порозі 1 с -- без відгуку: %r" % ev("SHORT"))
    want(ev("EQ1") == [("S", 2000), ("E", 3000)], "Б2: сигнал рівно поріг (1 с) -- відгук (>=): %r" % ev("EQ1"))
    want(ev("BLIP1") == [], "Б3: сплеск в один крок при порозі 1 с -- без відгуку: %r" % ev("BLIP1"))
    want(ev("BLIP0") == [("S", 1010), ("E", 2010)], "Б4: поріг 0 -- відгук на будь-яке відкриття (навіть один крок 10 мс): %r" % ev("BLIP0"))
    want(ev("S100_0") == [("S", 1100), ("E", 2100)], "Б4: поріг 0, сигнал 0,1 с -- відгук: %r" % ev("S100_0"))
    want(ev("T5SHORT") == [], "Б5: поріг 5 с, сигнал 4,99 с -- без відгуку: %r" % ev("T5SHORT"))
    want(ev("T5EQ") == [("S", 6000), ("E", 7000)], "Б5: поріг 5 с, сигнал рівно 5 с -- відгук: %r" % ev("T5EQ"))
    want(ev("T3EQ") == [("S", 4000), ("E", 5000)] and ev("T3SHORT") == [], "Б6: поріг 3 с: 3,00 с -- відгук, 2,99 с -- ні: %r %r" % (ev("T3EQ"), ev("T3SHORT")))
    # В
    want(ev("OPENSTART") == [], "В1: шумодав відкритий на старті -- без відгуку, навіть після його закриття: %r" % ev("OPENSTART"))
    want(ev("OPENSTART2") == [("S", 12000), ("E", 13000)], "В1: після спостереженого закриття новий сигнал -- відгук: %r" % ev("OPENSTART2"))
    want(ev("AFTERTX") == [("S", 3000), ("E", 4000)], "В2: відкритий зразу після власного тону шумодав (шум 3,5..30 с) -- нового відгуку нема: %r" % ev("AFTERTX"))
    want(ev("ENABLE") == [], "В3: функцію ввімкнено при відкритому шумодаві -- без відгуку: %r" % ev("ENABLE"))
    want(ev("ENABLE2") == [("S", 15000), ("E", 16000)], "В3: після закриття новий сигнал -- відгук: %r" % ev("ENABLE2"))
    want(ev("SCREEN") == [], "В4: сигнал почався, поки передача заборонена (інший екран), і триває на екрані каналу -- без відгуку: %r" % ev("SCREEN"))
    want(ev("SCREEN2") == [("S", 15000), ("E", 16000)], "В4: новий сигнал на екрані каналу -- відгук: %r" % ev("SCREEN2"))
    # Г
    want(ev("CANCD") == [], "Г1: клавіша/PTT у затримці -- відгуку нема: %r" % ev("CANCD"))
    want(ev("CANCD2") == [("S", 5600), ("E", 6600)], "Г1: новий сигнал після скасування й спостереженого закриття -- відгук: %r" % ev("CANCD2"))
    want(ev("CANCT") == [("S", 3000), ("E", 3500)], "Г2: PTT у тоні -- зупинка в той самий крок: %r" % ev("CANCT"))
    want(ev("CANCT2") == [("S", 3000), ("E", 3500)], "Г2: після скасування відкритий шум -- нового відгуку нема: %r" % ev("CANCT2"))
    want(ev("NOTX") == [], "Г3: передача заборонена -- мовчить: %r" % ev("NOTX"))
    want(ev("NOTXD") == [("S", 25000), ("E", 26000)], "Г3: заборона в затримці -- цикл відкинуто, новий сигнал після неї -- відгук: %r" % ev("NOTXD"))
    want(ev("NOTXRX") == [], "Г3: заборона під час сигналу -- цикл відкинуто: %r" % ev("NOTXRX"))
    want(ev("NOTXT") == [("S", 3000), ("E", 3500)], "Г3: заборона в тоні -- зупинка: %r" % ev("NOTXT"))
    want(L.get("OWNTX") == "0", "В5: відкритий шумодав у момент відпускання власної передачі (PTT) -- відгуку нема, для будь-якого паритету кроку: %r" % L.get("OWNTX"))
    want(ev("DISAB") == [("S", 3000), ("E", 3500)], "Г4: вимкнення в тоні -- зупинка: %r" % ev("DISAB"))
    want(ev("HARD") == [("S", 2010), ("E", 62010)], "Г5: «зламана» тривалість 200 с -- не більше 60 с (жорстка межа): %r" % ev("HARD"))
    # Д
    ping = (L.get("PING") or "").split()
    sym = (L.get("SYM") or "").split()
    onl = (L.get("ONLYA") or "").split()
    want(len(ping) == 5 and int(ping[0]) + int(ping[1]) >= 100 and int(ping[4]) >= 700000,
         "Д1: дві рації з функцією, затримки 1 і 3 с: відповіді йдуть БЕЗ КІНЦЯ -- у моделі 800 с їх %s, остання на %s мс (обмеження моделі: 800 с) -- ВІДОМА властивість: %r" %
         (int(ping[0]) + int(ping[1]) if len(ping) == 5 else "?", ping[4] if len(ping) == 5 else "?", ping))
    want(len(sym) == 5 and int(sym[0]) == 1 and int(sym[1]) == 1 and sym[2] == "0" and sym[3] == "0", "Д2: однакові налаштування -- тони одночасні, обмін завмирає (по одному відгуку): %r" % sym)
    want(len(onl) == 5 and int(onl[0]) == 1 and int(onl[1]) == 0 and onl[2] == "0", "Д3: одна рація з функцією: на один сигнал -- ОДИН відгук, друга мовчить: %r" % onl)
    want(L.get("PLAIN10") == "10 0" and L.get("PLAIN10Z") == "10 0", "Д4: один передавач без функції, 10 сигналів -- рівно 10 відгуків (кожен -- один), нічого зайвого: %r %r" % (L.get("PLAIN10"), L.get("PLAIN10Z")))
    g = (L.get("GRID") or "").split()
    want(len(g) == 3 and int(g[0]) == 81 and int(g[1]) >= 1 and int(g[1]) + int(g[2]) == 81,
         "Д5: таблиця 81 поєднання (затримка 0/1/10 с × тривалість 1/30/60 с): безкінечний обмін у %s, затихає у %s -- ВІДОМА властивість, захисту нема: %r" % (g[1] if len(g) == 3 else "?", g[2] if len(g) == 3 else "?", g))
    # Е
    want(L.get("V3") == "3 2450 37 7 3 1 size=8 0325070192090300", "Е1: блок 19 v3 -- запис/читання (частота, тривалість, затримка, поріг, «увімкнено»), 8 Б: %r" % L.get("V3"))
    want(L.get("V2") == "2 1200 30 5 1 1", "Е2: v2 -> v3: поріг типовий 1 с, «увімкнено» і решта збережені: %r" % L.get("V2"))
    want(L.get("V2B") == "2 1200 30 5 1 0", "Е2: у v2 байти [6..7] ігноруються (поріг 1 с): %r" % L.get("V2B"))
    want(L.get("V1") == "1 1750 1 3 1 0", "Е3: v1 -> мігровано (секунди вгору), вимкнено, поріг 1 с: %r" % L.get("V1"))
    want(L.get("JUNK") == "0 1000 10 2 1 0", "Е4: сміття -- типові (1000 Гц, 10 с, 2 с, поріг 1 с), вимкнено: %r" % L.get("JUNK"))
    want(L.get("V3BIG") == "3 1200 30 5 5 1", "Е5: v3 з порогом 99 -- обрізано до 5 с: %r" % L.get("V3BIG"))
    want(L.get("V3EACH") == "0 1 2 3 4 5" and L.get("CLAMPT") == "5", "Е6: всі значення порога 0..5 проходять збирання/розбір; 200 -> 5: %r %r" % (L.get("V3EACH"), L.get("CLAMPT")))
    return ok[0]


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема -- НЕ «пройдено»")
        FAILS.append("gcc нема")
        return finish()
    src, hdr = rd(SRC), rd(HDR)
    out, err = build(src)
    check(out is not None, "0: хостова збірка tone_reply.c: %s" % err)
    if out is None:
        return finish()
    core_checks(out)
    # Ж: код і константи
    check(not re.search(r"GUARD", src) and not re.search(r"GUARD", hdr) and "THRESH_MS" not in src and "THRESH_MS" not in hdr, "Ж1: сторожа (GUARD, THRESH_MS) у коді й заголовку нема")
    check("TR_ST_WAITCLOSE" in hdr and "умова коректності" in hdr and "НЕ пауза" in hdr, "Ж2: стан WAITCLOSE описано як умову коректності, а не паузу (заголовок)")
    check("НЕ пауза" in src and "свіже відкриття" in src and "Захисту від зациклення двох рацій з увімкненою функцією НЕМАЄ" in src, "Ж2: те саме в коді; про відсутність захисту від зациклення -- сказано")
    check("TONE_REPLY_THRESH_MIN_S  0U" in hdr and "TONE_REPLY_THRESH_MAX_S  5U" in hdr and "TONE_REPLY_THRESH_DEF_S  1U" in hdr and "TONE_REPLY_CFG_VERSION   3U" in hdr and "TONE_REPLY_CFG_LEN       8" in hdr,
          "Ж3: константи: поріг 0..5 с, типово 1 с; версія блока 3; довжина блока 8 (не змінилась)")
    am = rd(os.path.join(APP, "source", "functions", "tone_reply.c"))
    ld = am[am.index("void toneReplyLoad(void)"):]
    ld = ld[:ld.index("\n}\n")]
    check("s_trSm.state = TR_ST_WAITCLOSE;" in ld, "Ж4: на старті стан WAITCLOSE (відкритий шумодав на старті не запускає відгук)")
    ab = am[am.index("void toneReplyAbort(void)"):]
    ab = ab[:ab.index("\n}\n")]
    check(ab.count("TR_ST_WAITCLOSE") >= 2 and "TR_ST_GUARD" not in ab, "Ж5: PTT (toneReplyAbort) -- у WAITCLOSE, не в паузу")
    tk = am[am.index("void toneReplyTick(const void *evp)"):]
    tk = tk[:tk.index("\n}\n")]
    check("(s_trEnabled == 0U) && (s_trSm.state == TR_ST_WAITCLOSE)" in tk, "Ж6: вимкнена функція -- дешевий вихід лише з WAITCLOSE (інші стани доходять до toneReplyStep й скидаються)")

    # Є: мутанти
    def mut(name, a, b, which="src"):
        s2, h2 = src, hdr
        if which == "src":
            s2 = src.replace(a, b, 1)
            changed = s2 != src
        else:
            h2 = hdr.replace(a, b, 1)
            changed = h2 != hdr
        if not changed:
            check(False, "Є (%s): шаблон не знайдено" % name)
            return
        o2, e2 = build(s2, h2 if which != "src" else None)
        if o2 is None:
            check(True, "Є (%s): не збирається -- ловиться" % name)
            return
        n0 = len(FAILS)
        QUIET[0] = True
        ok = core_checks(o2, " [m]")
        QUIET[0] = False
        del FAILS[n0:]
        check(not ok, "Є (%s): ловиться" % name)
    mut("є пауза 5 с після відгуку (повернення сторожа)", "if ((rxOpen == false) && txAllowed)", "if ((now - s->t) >= 5000U && (rxOpen == false) && txAllowed && (cancel == false))")
    mut("є пауза 71 с після відгуку", "if ((rxOpen == false) && txAllowed)", "if ((now - s->t) >= 71000U && (rxOpen == false) && txAllowed && (cancel == false))")
    mut("нема умови свіжого закриття", "if ((rxOpen == false) && txAllowed)", "if (1)")
    mut("закриття без перевірки дозволу передачі", "if ((rxOpen == false) && txAllowed)", "if ((rxOpen == false) && (cancel == false))")
    mut("поріг ігнорується", "if ((now - s->t) >= ((uint32_t)cfg->threshS * 1000U))", "if ((now - s->t) >= 1000U)")
    mut("поріг без «>=» (суворо більше)", "if ((now - s->t) >= ((uint32_t)cfg->threshS * 1000U))", "if ((now - s->t) > ((uint32_t)cfg->threshS * 1000U))")
    mut("поріг не зберігається", "raw->thresh = c->threshS;", "raw->thresh = 1U;")
    mut("поріг v3 не читається", "c->threshS = raw->thresh;", "(void)raw->thresh;")
    mut("v2 бере поріг з байта [6]", "if (raw->version == TONE_REPLY_CFG_VERSION)\n\t\t{\n\t\t\tc->threshS = raw->thresh;", "if (1)\n\t\t{\n\t\t\tc->threshS = raw->thresh;")
    mut("без межі порогу", "if (c->threshS > TONE_REPLY_THRESH_MAX_S)\n\t{\n\t\tc->threshS = TONE_REPLY_THRESH_MAX_S;\n\t}", "")
    mut("без жорсткої межі тривалості", "dur = (uint32_t)((cfg->durS > TONE_REPLY_DUR_MAX_S) ? TONE_REPLY_DUR_MAX_S : cfg->durS) * 1000U;", "dur = (uint32_t)cfg->durS * 1000U;")
    mut("без скасування в тоні", "if (cancel || (txAllowed == false) || ((now - s->t) >= dur))", "if ((txAllowed == false) || ((now - s->t) >= dur))")
    mut("заборона в RX не відкидає цикл", "if (txAllowed == false)\n\t\t\t{\n\t\t\t\ts->state = TR_ST_WAITCLOSE;   /* під час сигналу заборонено передачу -- цикл відкинуто */\n\t\t\t\ts->t = now;\n\t\t\t}\n\t\t\telse if (rxOpen == false)",
        "if (0)\n\t\t\t{\n\t\t\t\ts->state = TR_ST_WAITCLOSE;\n\t\t\t\ts->t = now;\n\t\t\t}\n\t\t\telse if (rxOpen == false)")
    mut("вимкнення функції не вводить у WAITCLOSE", "s->state = TR_ST_WAITCLOSE;\n\t\ts->t = now;\n\t\treturn (wasTx ? TR_ACT_STOP : TR_ACT_NONE);", "s->state = TR_ST_IDLE;\n\t\ts->t = now;\n\t\treturn (wasTx ? TR_ACT_STOP : TR_ACT_NONE);")
    return finish()


def finish():
    print("test_r102tone: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
