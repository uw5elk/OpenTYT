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


/* ---- R3: розгортка фону ---------------------------------------------------- */
static double gauss(void)
{
	double u1 = (noise() + 0.5) * 0.999 + 0.0005, u2 = noise() + 0.5;
	return sqrt(-2.0 * log(u1)) * cos(2 * PI * u2);
}

/* Подає вікно розгортки (24 блоки по 160) з тоном(ами) і шумом, повертає результат. */
static apBgResult_t sweep(double f1, double a1, double f2, double a2, double noiseRms, double dc)
{
	apBg_t b;
	apBgResult_t r = { 0 };
	int16_t blk[AP_SWEEP_N];
	long t = 0;
	apBgInit(&b);
	for (int k = 0; k < 200; k++)
	{
		for (int i = 0; i < AP_SWEEP_N; i++, t++)
		{
			double v = dc + a1 * sin(2 * PI * f1 * t / 8000.0 + 0.4) + a2 * sin(2 * PI * f2 * t / 8000.0 + 1.3) + noiseRms * gauss();
			blk[i] = (int16_t)lround(v);
		}
		if (apBgBlock(&b, blk, &r))
		{
			return r;
		}
	}
	return r;
}

static void testSweep(void)
{
	apBgResult_t r;
	printf(" розгортка фону 100..3900 Гц:\n");

	r = sweep(1712, 900, 0, 0, 50, 0);
	CHECK(r.valid && fabs(r.f1 - 1712) < 3 && near(r.a1, 900, 5) && r.share1 >= 90,
			"тон 1712 Гц (між точками сітки) + слабкий шум: топ-1 %.1f Гц, A=%lu, частка %u %%",
			r.f1, (unsigned long)r.a1, r.share1);
	CHECK(apBgNotchHz(&r) > 1700 && apBgNotchHz(&r) < 1725, "вузька завада 1712 у смузі -- режекція на %.1f Гц", apBgNotchHz(&r));

	r = sweep(1200, 500, 0, 0, 30, -300);
	CHECK(fabs(r.f1 - 1200) < 2 && r.share1 >= 90 && apBgNotchHz(&r) == 0.0f,
			"тон 1200 (сам сигнал APRS) -- топ-1 %.1f Гц, але режекції немає (з'їла б тон)", r.f1);

	r = sweep(600, 400, 0, 0, 30, 2000);
	CHECK(fabs(r.f1 - 600) < 2 && apBgNotchHz(&r) == 0.0f && abs(r.mean - 2000) <= 2,
			"тон 600 Гц (поза смугою) -- режекції немає (смуговий і так прибере); DC %ld", (long)r.mean);

	r = sweep(1000, 0, 0, 0, 700, 0);
	CHECK(r.share1 <= 20 && apBgNotchHz(&r) == 0.0f && near(r.rms, 700, 5),
			"білий шум RMS 700: частка топ-1 %u %% (широкий шум), RMS %lu", r.share1, (unsigned long)r.rms);

	r = sweep(2850, 600, 433, 300, 40, 0);
	CHECK(fabs(r.f1 - 2850) < 3 && (r.f2 >= 400 && r.f2 <= 450) && near(r.a2, 300, 30),
			"два тони 2850 і 433 Гц: топ-1 %.1f, топ-2 %u Гц (A2=%lu)", r.f1, r.f2, (unsigned long)r.a2);

	r = sweep(1712, 500, 0, 0, 700, 0);
	CHECK(fabs(r.f1 - 1712) < 6 && r.share1 >= 30 && r.share1 <= 60,
			"тон 500 у шумі 700: топ-1 %.1f Гц, частка %u %% (між вузьким і широким)", r.f1, r.share1);
}


/* ---- R4: безперервність потоку --------------------------------------------------- */
/* 200 блоків тону f (амплітуда a, шум nz); на межі кожного блока викинути (d > 0) або
 * продублювати (d < 0) |d| відліків -- як зробили б розриви DMA. */
static apStream_t streamRun(double f, double a, double nz, int d)
{
	apStream_t st;
	int16_t blk[160];
	double t = 0.0;
	apStreamInit(&st);
	for (int b = 0; b < 200; b++)
	{
		for (int i = 0; i < 160; i++)
		{
			blk[i] = (int16_t)lround(a * sin(2 * PI * f * t / 8000.0 + 0.3) + nz * gauss());
			t += 1.0;
		}
		t += (double)d;   /* d > 0: наступний блок починається пізніше (відліки загубились) */
		apStreamBlock(&st, blk);
	}
	return st;
}

static void testStream(void)
{
	apStream_t st;
	printf(" безперервність потоку (тон 1200 Гц, 200 блоків):\n");

	CHECK(fabs(apAtan2Deg(1, 1) - 45) < 0.01 && fabs(apAtan2Deg(-1, -1) + 135) < 0.01 && fabs(apAtan2Deg(0, -1) - 180) < 0.01,
			"apAtan2Deg: 45 / -135 / 180 град");

	st = streamRun(1200, 600, 60, 0);
	CHECK(st.blocks >= 199 && st.jumpsB == 0 && st.jumpsIn == 0 && st.maxB < 15 && fabs(apStreamOffsetHz(&st)) < 0.3,
			"безперервний потік: стрибків на межі %lu, всередині %lu, макс %u град, розстройка %.2f Гц",
			(unsigned long)st.jumpsB, (unsigned long)st.jumpsIn, st.maxB, apStreamOffsetHz(&st));

	st = streamRun(1201, 600, 60, 0);
	CHECK(st.jumpsB == 0 && fabs(apStreamOffsetHz(&st) - 1.0) < 0.3,
			"тон 1201 Гц: стрибків немає, розстройка %.2f Гц (~+1)", apStreamOffsetHz(&st));

	st = streamRun(1200, 600, 60, 1);
	CHECK(st.jumpsB >= 190 && st.jumpsIn == 0 && st.maxB >= 45 && st.maxB <= 65,
			"втрата 1 відліку на кожній межі: стрибків на межі %lu (з ~199), всередині %lu, макс %u град (~54)",
			(unsigned long)st.jumpsB, (unsigned long)st.jumpsIn, st.maxB);

	st = streamRun(1200, 600, 60, -2);
	CHECK(st.jumpsB >= 190 && st.jumpsIn == 0 && st.maxB >= 95 && st.maxB <= 120,
			"дубль 2 відліків: стрибків на межі %lu, макс %u град (~108)", (unsigned long)st.jumpsB, st.maxB);

	st = streamRun(1200, 0, 700, 0);
	CHECK(st.blocks <= 2, "лише шум RMS 700 (як фон R2): блоків з «тоном» -- %lu з 200", (unsigned long)st.blocks);

	st = streamRun(1200, 1000, 500, 0);
	CHECK(st.blocks >= 190 && st.jumpsB <= 4 && st.jumpsIn <= 4,
			"тон 1000 у шумі 500, без розривів: стрибків на межі %lu, всередині %lu (шумові -- рівно в обох)",
			(unsigned long)st.jumpsB, (unsigned long)st.jumpsIn);
	st = streamRun(1200, 1000, 500, 1);
	CHECK(st.jumpsB >= 150 && st.jumpsIn <= 4,
			"тон 1000 у шумі 500, втрата 1 відліку: на межі %lu, всередині %lu -- різниця очевидна",
			(unsigned long)st.jumpsB, (unsigned long)st.jumpsIn);
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
	testSweep();
	testStream();

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
