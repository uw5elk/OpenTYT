/*
 * test_aprs_probe_dsp.c -- R2: рівень і тони 1200/2200 Гц для екрана «APRS проба»
 * (functions/aprs_probe_dsp.c). Синтетичні сигнали при 8000 Гц (I2S, блок 160) і 9600 Гц
 * (АЦП, блок 192): правильний «переможець», амплітуди, RMS, DC, пік, дБ.
 */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "functions/aprs_probe_dsp.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

#define PI 3.14159265358979323846

/* Детермінований шум (LCG), щоб тест не залежав від rand() платформи. */
static uint32_t s_seed = 1;
static double noise(void)
{
	s_seed = s_seed * 1103515245u + 12345u;
	return ((double)((s_seed >> 8) & 0xFFFF) / 65535.0) - 0.5;   /* -0.5..0.5 */
}

typedef struct
{
	uint32_t fs;
	uint16_t n;
	const char *name;
	int32_t lo, hi;     /* межі сирих відліків (int16 або 12-біт АЦП) */
	int32_t dc;
} src_t;

static const src_t SRC_I2S = { AP_FS_I2S, 160, "I2S 8000 Гц", -32768, 32767, 0 };
static const src_t SRC_ADC = { AP_FS_ADC, 192, "ADC 9600 Гц", 0, 4095, 2048 };

/* Проганяє 3 вікна (перше -- «розгін» опорного рівня), повертає результат останнього. */
static apResult_t run(const src_t *s, double f1, double a1, double f2, double a2, double noiseAmp, double phase)
{
	apChan_t ch;
	apResult_t r = { 0 };
	int wins = 0;
	long i = 0;

	apChanInit(&ch, s->fs, s->n, 12, s->dc);
	while (wins < 3)
	{
		double t = (double)i / (double)s->fs;
		double v = s->dc + a1 * sin(2 * PI * f1 * t + phase) + a2 * sin(2 * PI * f2 * t + 0.7) + noiseAmp * noise();
		long x = lround(v);
		if (x < s->lo) { x = s->lo; }
		if (x > s->hi) { x = s->hi; }
		if (apChanPush(&ch, (int32_t)x, &r))
		{
			wins++;
		}
		i++;
	}
	return r;
}

/* Bell 202: безперервна фаза, 1200 бод, випадкові біти (як у пакеті APRS). */
static apResult_t runAfsk(const src_t *s, double amp)
{
	apChan_t ch;
	apResult_t r = { 0 };
	int wins = 0;
	long i = 0;
	double ph = 0.0;
	double f = 1200.0;
	double spb = (double)s->fs / 1200.0;
	double nextBit = spb;

	apChanInit(&ch, s->fs, s->n, 12, s->dc);
	while (wins < 3)
	{
		if ((double)i >= nextBit)
		{
			nextBit += spb;
			if (noise() > 0.0) { f = (f == 1200.0) ? 2200.0 : 1200.0; }   /* NRZI: «0» -- зміна тону */
		}
		ph += 2 * PI * f / (double)s->fs;
		long x = lround(s->dc + amp * sin(ph));
		if (apChanPush(&ch, (int32_t)x, &r))
		{
			wins++;
		}
		i++;
	}
	return r;
}

static int near(double v, double ref, double tolPct)
{
	return fabs(v - ref) <= fabs(ref) * tolPct / 100.0;
}

static void testSource(const src_t *s, double amp)
{
	apResult_t r;

	printf(" %s, амплітуда %.0f:\n", s->name, amp);

	r = run(s, 1200, amp, 2200, 0, amp * 0.02, 0.3);
	CHECK(r.valid && r.winner == AP_WIN_1200, "1200 Гц -- переважає 1200 (a1200=%lu a2200=%lu, %+d дБ)",
			(unsigned long)r.a1200, (unsigned long)r.a2200, r.ratioDb);
	CHECK(near(r.a1200, amp, 3), "1200 Гц -- амплітуда тону ~%.0f (є %lu)", amp, (unsigned long)r.a1200);
	CHECK(r.a2200 < amp * 0.05, "1200 Гц -- 2200 майже нуль (%lu)", (unsigned long)r.a2200);
	CHECK(near(r.rms, amp / sqrt(2.0), 3), "1200 Гц -- RMS ~%.0f (є %lu)", amp / sqrt(2.0), (unsigned long)r.rms);
	CHECK(abs(r.mean - s->dc) <= 2, "1200 Гц -- DC %ld (очікується %ld)", (long)r.mean, (long)s->dc);
	CHECK(near(r.peak, amp, 4), "1200 Гц -- пік ~%.0f (є %lu)", amp, (unsigned long)r.peak);
	CHECK(r.ratioDb >= 25, "1200 Гц -- співвідношення >= 25 дБ (є %+d)", r.ratioDb);

	r = run(s, 2200, amp, 1200, 0, amp * 0.02, 1.1);
	CHECK(r.valid && r.winner == AP_WIN_2200, "2200 Гц -- переважає 2200 (a1200=%lu a2200=%lu, %+d дБ)",
			(unsigned long)r.a1200, (unsigned long)r.a2200, r.ratioDb);
	CHECK(near(r.a2200, amp, 3), "2200 Гц -- амплітуда тону ~%.0f (є %lu)", amp, (unsigned long)r.a2200);
	CHECK(r.ratioDb <= -25, "2200 Гц -- співвідношення <= -25 дБ (є %+d)", r.ratioDb);

	/* Не рівно на біні (генератор тонів у телефоні може бути неточним) -- переможець той самий. */
	r = run(s, 1215, amp, 2200, 0, amp * 0.02, 2.0);
	CHECK(r.winner == AP_WIN_1200, "1215 Гц -- усе одно 1200 (a1200=%lu a2200=%lu)", (unsigned long)r.a1200, (unsigned long)r.a2200);
	r = run(s, 2185, amp, 1200, 0, amp * 0.02, 2.0);
	CHECK(r.winner == AP_WIN_2200, "2185 Гц -- усе одно 2200 (a1200=%lu a2200=%lu)", (unsigned long)r.a1200, (unsigned long)r.a2200);

	/* Обидва тони однакові -- «рівні», ~0 дБ. */
	r = run(s, 1200, amp * 0.5, 2200, amp * 0.5, amp * 0.02, 0.0);
	CHECK(r.winner == AP_WIN_NONE && abs(r.ratioDb) <= 1, "1200+2200 порівну -- «рівні», %+d дБ", r.ratioDb);

	/* Голос/свист на 1000 Гц: обидва тони малі відносно RMS. */
	r = run(s, 1000, amp, 0, 0, amp * 0.02, 0.0);
	CHECK((r.a1200 < r.rms / 4) && (r.a2200 < r.rms / 4) && (r.winner == AP_WIN_WEAK), "1000 Гц -- тони малі, «--» (a1200=%lu a2200=%lu rms=%lu)",
			(unsigned long)r.a1200, (unsigned long)r.a2200, (unsigned long)r.rms);

	/* Пакет AFSK: тон змінюється кожен біт з довільною фазою, тож у блоці 20 мс обидва тони
	 * помітні, але кожен лише ~15-25% амплітуди (не 100%, як у чистого тону), і жоден не
	 * переважає. Саме так пакет і виглядає на екрані: «рівні», обидва числа >> тиші й голосу. */
	r = runAfsk(s, amp);
	CHECK((r.a1200 > amp / 10) && (r.a2200 > amp / 10) && (r.winner == AP_WIN_NONE),
			"AFSK 1200 бод -- обидва тони > 10%%, «рівні» (a1200=%lu a2200=%lu, %+d дБ)",
			(unsigned long)r.a1200, (unsigned long)r.a2200, r.ratioDb);

	/* Тиша. */
	r = run(s, 1200, 0, 2200, 0, 0, 0.0);
	CHECK(r.valid && r.rms == 0 && r.a1200 == 0 && r.a2200 == 0 && r.winner == AP_WIN_WEAK && r.ratioDb == 0,
			"тиша -- RMS 0, тони 0, «--» (немає тону), 0 дБ");

	/* Слабкий шум: тони -- шум, переможця немає, хоч дБ і можуть бути великі. */
	r = run(s, 1200, 0, 2200, 0, amp * 0.05, 0.0);
	CHECK(r.winner == AP_WIN_WEAK || r.winner == AP_WIN_NONE, "лише шум -- без переможця (a1200=%lu a2200=%lu rms=%lu, знак %u)",
			(unsigned long)r.a1200, (unsigned long)r.a2200, (unsigned long)r.rms, (unsigned)r.winner);
}

int main(void)
{
	printf("test_aprs_probe_dsp:\n");

	/* Константи Goertzel проти math.h. */
	apChan_t c;
	apChanInit(&c, AP_FS_I2S, 160, 12, 0);
	CHECK(fabs(c.c1200 - 2 * cos(2 * PI * 1200 / 8000)) < 1e-6 && fabs(c.c2200 - 2 * cos(2 * PI * 2200 / 8000)) < 1e-6,
			"коефіцієнти 8000 Гц збігаються з cos()");
	apChanInit(&c, AP_FS_ADC, 192, 12, 2048);
	CHECK(fabs(c.c1200 - 2 * cos(2 * PI * 1200 / 9600)) < 1e-6 && fabs(c.c2200 - 2 * cos(2 * PI * 2200 / 9600)) < 1e-6,
			"коефіцієнти 9600 Гц збігаються з cos()");
	CHECK((160 * 1200) % 8000 == 0 && (160 * 2200) % 8000 == 0 && (192 * 1200) % 9600 == 0 && (192 * 2200) % 9600 == 0,
			"обидві частоти -- рівно на біні (k цілі) для 160@8000 і 192@9600");

	/* Вікно закривається рівно кожні blockLen*blocksPerWin відліків. */
	{
		apChan_t w;
		apResult_t r;
		int first = -1, second = -1;
		apChanInit(&w, AP_FS_I2S, 160, 12, 0);
		for (int i = 0; i < 160 * 12 * 2; i++)
		{
			if (apChanPush(&w, 0, &r))
			{
				if (first < 0) { first = i; } else { second = i; }
			}
		}
		CHECK(first == 160 * 12 - 1 && second == 160 * 12 * 2 - 1, "вікно -- кожні 1920 відліків (240 мс при 8 кГц)");
	}

	/* Допоміжні. */
	{
		int ok = 1;
		uint64_t vals[] = { 0, 1, 2, 3, 4, 15, 16, 17, 1000000, 4294967295ULL, 4294967296ULL, 1ULL << 62, 18446744073709551615ULL };
		for (unsigned i = 0; i < sizeof(vals) / sizeof(vals[0]); i++)
		{
			uint64_t r = apIsqrt64(vals[i]);
			if (!((r * r <= vals[i]) && ((r + 1) * (r + 1) > vals[i] || r == 0xFFFFFFFFULL))) { ok = 0; printf("    isqrt(%llu)=%llu\n", (unsigned long long)vals[i], (unsigned long long)r); }
		}
		s_seed = 7;
		for (int i = 0; i < 20000; i++)
		{
			uint64_t v = ((uint64_t)s_seed << 20) ^ (uint64_t)(i * 2654435761u);
			noise();
			uint64_t r = apIsqrt64(v);
			if (!((r * r <= v) && ((r + 1) * (r + 1) > v))) { ok = 0; break; }
		}
		CHECK(ok, "apIsqrt64 -- floor(sqrt) на межових і 20000 випадкових");
	}
	CHECK(apRatioDb(1000, 100) == 20 && apRatioDb(100, 1000) == -20, "дБ: 10x = +20, 0.1x = -20");
	CHECK(apRatioDb(2, 1) == 6 && apRatioDb(1, 1) == 0, "дБ: 2x = +6, 1x = 0");
	CHECK(apRatioDb(5, 0) == AP_DB_LIMIT && apRatioDb(0, 5) == -AP_DB_LIMIT && apRatioDb(0, 0) == 0, "дБ: межі й нулі");
	CHECK(apRatioDb(4000000000u, 1) == AP_DB_LIMIT, "дБ: обмеження %d", AP_DB_LIMIT);
	CHECK(apWinner(200, 100) == AP_WIN_1200 && apWinner(199, 100) == AP_WIN_NONE && apWinner(100, 200) == AP_WIN_2200
			&& apWinner(0, 0) == AP_WIN_NONE, "переможець -- лише з перевагою вдвічі (6 дБ)");

	s_seed = 1;
	testSource(&SRC_I2S, 8000.0);
	testSource(&SRC_I2S, 300.0);
	testSource(&SRC_ADC, 800.0);
	testSource(&SRC_ADC, 60.0);

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
