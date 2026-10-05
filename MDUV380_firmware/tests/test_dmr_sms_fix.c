/*
 * test_dmr_sms_fix.c -- fix7: програмна корекція 1-2 сусідніх трибітів у rate-3/4 PDU.
 * Лінкує СПРАВЖНІ functions/dmr_sms_fix.c і dmr_sms_pdu.c.
 *
 *  1. Знімки з рації #8 і #12 (2026-10-05, «Діагностика 4») мають виправитись РІВНО на ефірні
 *     байти HackRF. #12 -- дві помилки в різних блоках (блок 0 у заголовку IPv4 + блок 2).
 *  2. Синтетика: валідні PDU + випадкова 1-2-трибітна помилка в одному блоці -> виправлено
 *     на оригінал; помилка в заголовку IPv4 + друга в іншому блоці -> теж.
 *  3. 3+ трибіти, помилки в кількох блоках поза заголовком -> НІКОЛИ не «виправлено» хибно.
 *  4. Час корекції на хості (середній / найгірший).
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>
#include "functions/dmr_sms_pdu.h"
#include "functions/dmr_sms_fix.h"
#include "functions/dmr_sms.h"   /* DMR_SMS_TEXT_MAX */

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static int hex(const char *s, uint8_t *out)
{
	int n = 0;
	while (s[0] && s[1]) { unsigned v; sscanf(s, "%2x", &v); out[n++] = (uint8_t)v; s += 2; }
	return n;
}

/* PDU з сирих 18-байтних блоків: службові 2 Б відкидаються, як у збирачі dmr_sms.c. */
static int pduOf(const char *const *blk, int n, uint8_t *pdu)
{
	for (int b = 0; b < n; b++)
	{
		uint8_t raw[18];
		hex(blk[b], raw);
		memcpy(pdu + 16 * b, raw + 2, 16);
	}
	return 16 * n;
}

static int verifyPlain(const uint8_t *pdu, int len, void *ctx) { (void)ctx; return dmrSmsPduIpUdpOk(pdu, len); }

static double nowUs(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1e6 + ts.tv_nsec / 1e3;
}

static void snapshot(const char *name, const char *const *rx, const char *const *air, int n, int expErr)
{
	uint8_t p[128], a[128];
	int len = pduOf(rx, n, p);
	pduOf(air, n, a);
	CHECK(dmrSmsPduCrc32(a, len) == (((uint32_t)a[len-4] << 24) | ((uint32_t)a[len-3] << 16) | ((uint32_t)a[len-2] << 8) | a[len-1]),
	      "%s: ефірний PDU має валідний CRC32", name);
	CHECK(dmrSmsPduIpUdpOk(a, len) && !dmrSmsPduIpUdpOk(p, len), "%s: IPv4/UDP валідні в ефірному, невалідні в прийнятому", name);
	dmrSmsFixInfo_t info;
	double t0 = nowUs();
	int r = dmrSmsPduFix34(p, len, 1, verifyPlain, NULL, &info);
	double dt = nowUs() - t0;
	printf("       %s: результат %d, змін %u, якір %u (якорів %u), збігів CRC %u, прийнятних %u, кандидатів %u, %.0f мкс\n",
	       name, r, info.nerr, info.anchored, info.anchors, info.crcMatches, info.verified, (unsigned)info.tested, dt);
	for (int k = 0; k < info.nerr; k++)
	{
		printf("         блок %u трибіт %u ширина %u значення %02o\n", info.err[k].blk, info.err[k].tri, info.err[k].width, info.err[k].val);
	}
	CHECK(r == DMR_SMS_FIX_OK && memcmp(p, a, len) == 0 && info.nerr == expErr,
	      "%s: виправлено рівно на ефірні байти (%d змін)", name, expErr);
}

/* ============ синтетика ============ */
static uint32_t rng = 12345;
static uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }

static int makePdu(uint8_t *pdu)
{
	char text[64];
	int tl = 1 + (int)(rnd() % 40);
	for (int i = 0; i < tl; i++) { text[i] = (char)(0x20 + rnd() % 95); }
	int pl = dmrSmsPduBuildPlaintext(text, tl, 0x26EA29, 0x26EA0F, (uint8_t)rnd(), (uint16_t)rnd(), pdu);
	int len = ((pl + 4 + 15) / 16) * 16;
	memset(pdu + pl, 0, (size_t)(len - pl));
	uint32_t c = dmrSmsPduCrc32(pdu, len);
	pdu[len-4] = (uint8_t)(c >> 24); pdu[len-3] = (uint8_t)(c >> 16); pdu[len-2] = (uint8_t)(c >> 8); pdu[len-1] = (uint8_t)c;
	return len;
}

/* Незалежна від dmr_sms_fix.c мапа: сирий біт r блока b -> байт PDU 16b + r/8 - 2. */
static void flipTri(uint8_t *pdu, int b, int t, int v)
{
	for (int i = 0; i < 3; i++)
	{
		if (((v >> (2 - i)) & 1) == 0) { continue; }
		int r = 3 * t + i;
		if (r < 16) { continue; }
		pdu[16 * b + r / 8 - 2] ^= (uint8_t)(0x80 >> (r % 8));
	}
}

/* Випадкова помилка з w сусідніх ненульових трибітів у блоці b; tmin/tmax -- межі першого. */
static void injectBurst(uint8_t *pdu, int b, int w, int tmin, int tmax)
{
	int t = tmin + (int)(rnd() % (unsigned)(tmax - tmin + 1));
	for (int k = 0; k < w; k++) { flipTri(pdu, b, t + k, 1 + (int)(rnd() % 7)); }
}

typedef struct { int ok, okWrong, amb, none, unchanged; double maxUs, sumUs; uint32_t maxTested; } stat_t;

static void runOne(uint8_t *p, const uint8_t *orig, int len, stat_t *s)
{
	if (memcmp(p, orig, len) == 0) { s->unchanged++; return; }   /* помилка влучила лише в службові */
	dmrSmsFixInfo_t info;
	double t0 = nowUs();
	int r = dmrSmsPduFix34(p, len, 1, verifyPlain, NULL, &info);
	double dt = nowUs() - t0;
	s->sumUs += dt;
	if (dt > s->maxUs) { s->maxUs = dt; }
	if (info.tested > s->maxTested) { s->maxTested = info.tested; }
	if (r == DMR_SMS_FIX_OK) { if (memcmp(p, orig, len) == 0) { s->ok++; } else { s->okWrong++; } }
	else if (r == DMR_SMS_FIX_AMBIG) { s->amb++; }
	else { s->none++; }
}

static void report(const char *name, int n, const stat_t *s)
{
	printf("       %-44s n=%d: ок %d, ХИБНО %d, неод %d, нема %d (лише службові %d); %.0f/%.0f мкс сер/макс, кандидатів до %u\n",
	       name, n, s->ok, s->okWrong, s->amb, s->none, s->unchanged, s->sumUs / (n ? n : 1), s->maxUs, (unsigned)s->maxTested);
}

int main(void)
{
	printf("test_dmr_sms_fix:\n");

	static const char *const rx8[]  = { "017b4500002a0009000040118e350ce6ea29", "02f20c26ea0f0fa70fa700160edd000ce000", "05f58d040d000a0031003000000071579d8d" };
	static const char *const air8[] = { "017b4500002a0009000040118e350c26ea29", "02f20c26ea0f0fa70fa700160edd000ce000", "05f58d040d000a0031003000000071579d8d" };
	snapshot("знімок #8", rx8, air8, 3, 1);

	static const char *const rx12[]  = { "01d045000034000c001440118e280c26ea29", "03e60c26ea0f0fa70fa70020c0bc0016e000",
	                                     "042f85040d000a006d0075d06d0031006100", "07366d006a000000000000000000292ac790" };
	static const char *const air12[] = { "01d045000034000c000040118e280c26ea29", "03e60c26ea0f0fa70fa70020c0bc0016e000",
	                                     "042f85040d000a006d0074006d0031006100", "07366d006a000000000000000000292ac790" };
	snapshot("знімок #12", rx12, air12, 4, 2);

	/* Без verify (лише CRC32) #12 у режимі «якір» однаково однозначний -- для довідки. */
	{
		uint8_t p[128];
		int len = pduOf(rx12, 4, p);
		int r = dmrSmsPduFix34(p, len, 0, verifyPlain, NULL, NULL);
		CHECK(r == DMR_SMS_FIX_NONE, "знімок #12 як шифрований (без якоря): дві помилки в різних блоках -> «нема», не хибно");
	}

	uint8_t orig[400], p[400];
	const int N = 3000;

	/* 2. одна помилка 1-2 трибіти в одному блоці */
	for (int w = 1; w <= 2; w++)
	{
		stat_t s; memset(&s, 0, sizeof s);
		for (int i = 0; i < N; i++)
		{
			int len = makePdu(orig);
			memcpy(p, orig, len);
			injectBurst(p, (int)(rnd() % (unsigned)(len / 16)), w, 5, 48 - w);
			runOne(p, orig, len, &s);
		}
		char nm[64]; snprintf(nm, sizeof nm, "1 блок, %d сусідн. трибіт(и)", w);
		report(nm, N, &s);
		CHECK(s.okWrong == 0 && s.ok >= (N - s.unchanged) * 95 / 100, "%s: виправлено >= 95%%, хибних 0", nm);
	}
	/* 2б. заголовок IPv4 + інший блок (як #12) */
	{
		stat_t s; memset(&s, 0, sizeof s);
		for (int i = 0; i < N; i++)
		{
			int len = makePdu(orig);
			memcpy(p, orig, len);
			injectBurst(p, 0, 1 + (int)(rnd() % 2), 6, 45);                 /* блок 0 -- заголовок IPv4 */
			injectBurst(p, 2 + (int)(rnd() % (unsigned)(len / 16 - 2)), 1 + (int)(rnd() % 2), 5, 46);
			runOne(p, orig, len, &s);
		}
		report("заголовок IPv4 + інший блок", N, &s);
		CHECK(s.okWrong == 0 && s.ok >= (N - s.unchanged) * 90 / 100, "заголовок + інший блок: виправлено >= 90%%, хибних 0");
	}

	/* 3. те, що НЕ має виправлятись хибно */
	{
		stat_t s; memset(&s, 0, sizeof s);
		for (int i = 0; i < N; i++)
		{
			int len = makePdu(orig);
			memcpy(p, orig, len);
			injectBurst(p, (int)(rnd() % (unsigned)(len / 16)), 3 + (int)(rnd() % 3), 6, 42);
			runOne(p, orig, len, &s);
		}
		report("3-5 сусідніх трибітів в одному блоці", N, &s);
		CHECK(s.okWrong == 0, "3-5 трибітів: хибних виправлень 0");
	}
	{
		stat_t s; memset(&s, 0, sizeof s);
		for (int i = 0; i < N; i++)
		{
			int len = makePdu(orig);
			if (len < 64) { i--; continue; }
			memcpy(p, orig, len);
			int b1 = 1 + (int)(rnd() % (unsigned)(len / 16 - 1));
			int b2;
			do { b2 = 1 + (int)(rnd() % (unsigned)(len / 16 - 1)); } while (b2 == b1);
			/* блок 1: лише поза заголовком IPv4 (трибіти 17+) */
			injectBurst(p, b1, 1 + (int)(rnd() % 2), (b1 == 1) ? 17 : 5, 46);
			injectBurst(p, b2, 1 + (int)(rnd() % 2), (b2 == 1) ? 17 : 5, 46);
			runOne(p, orig, len, &s);
		}
		report("2 блоки поза заголовком IPv4", N, &s);
		CHECK(s.okWrong == 0, "2 блоки поза заголовком: хибних виправлень 0");
	}
	{
		stat_t s; memset(&s, 0, sizeof s);
		for (int i = 0; i < N; i++)
		{
			int len = makePdu(orig);
			if (len < 64) { i--; continue; }
			memcpy(p, orig, len);
			for (int k = 0; k < 3; k++) { injectBurst(p, (int)(rnd() % (unsigned)(len / 16)), 1 + (int)(rnd() % 2), 5, 46); }
			runOne(p, orig, len, &s);
		}
		report("3 помилки у випадкових блоках", N, &s);
		CHECK(s.okWrong == 0, "3 помилки: хибних виправлень 0");
	}
	{
		/* Повністю випадковий «PDU» (сміття з правильною довжиною) -- нічого не «виправляє». */
		stat_t s; memset(&s, 0, sizeof s);
		for (int i = 0; i < 300; i++)
		{
			int len = 16 * (2 + (int)(rnd() % 7));
			for (int k = 0; k < len; k++) { orig[k] = (uint8_t)rnd(); }
			memcpy(p, orig, len);
			p[0] ^= 1;   /* щоб runOne не вважав «без змін» */
			dmrSmsFixInfo_t info;
			int r = dmrSmsPduFix34(p, len, 1, verifyPlain, NULL, &info);
			if (r == DMR_SMS_FIX_OK) { s.okWrong++; } else if (r == DMR_SMS_FIX_AMBIG) { s.amb++; } else { s.none++; }
		}
		report("випадкове сміття", 300, &s);
		CHECK(s.okWrong == 0, "сміття: «виправлень» 0");
	}

	/* 4. найгірший час: найдовший PDU (24 блоки), помилка в заголовку (режим якоря). */
	{
		char text[200];
		memset(text, 'x', sizeof text);
		int pl = dmrSmsPduBuildPlaintext(text, DMR_SMS_TEXT_MAX, 0x26EA29, 0x26EA0F, 1, 2, orig);
		int len = ((pl + 4 + 15) / 16) * 16;
		memset(orig + pl, 0, (size_t)(len - pl));
		uint32_t c = dmrSmsPduCrc32(orig, len);
		orig[len-4] = (uint8_t)(c >> 24); orig[len-3] = (uint8_t)(c >> 16); orig[len-2] = (uint8_t)(c >> 8); orig[len-1] = (uint8_t)c;
		stat_t s; memset(&s, 0, sizeof s);
		for (int i = 0; i < 200; i++)
		{
			memcpy(p, orig, len);
			injectBurst(p, 0, 2, 6, 45);
			injectBurst(p, len / 16 - 1, 2, 5, 46);
			runOne(p, orig, len, &s);
		}
		char nm[96]; snprintf(nm, sizeof nm, "найдовший PDU %d Б (%d блоків), якір", len, len / 16);
		report(nm, 200, &s);
		CHECK(s.okWrong == 0, "найдовший PDU: хибних 0");
	}

	printf(fails ? "ПРОВАЛ (%d)\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
