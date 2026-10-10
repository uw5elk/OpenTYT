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

/* ---- R5: формат відліку I2S RX --------------------------------------------------- */
static void testFmt(void)
{
	printf(" формат відліку (10 біт):\n");
	CHECK(apSample10(0x0000) == 0 && apSample10(0x01FF) == 511 && apSample10(0x0200) == -512 && apSample10(0x03FF) == -1,
			"apSample10: 0 / 511 / -512 / -1");
	CHECK(apSample10(0xFC05) == 5 && apSample10(0xFFFF) == -1 && apSample10(0x0400) == 0 && apSample10(0xFE00) == -512,
			"apSample10 ігнорує біти 10..15: 0xFC05 -> 5, 0xFFFF -> -1, 0x0400 -> 0, 0xFE00 -> -512");
	{
		const uint16_t u[8] = { 0x0005, 0xFC05, 0x03FE, 0xFDE0, 0x0400, 0x01E0, 0x0200, 0xFFFF };
		/* s:                   5       5      -2       480      0       480     -512    -1 */
		int16_t out[8], raw[8];
		apFmt_t f;
		apFmtInit(&f);
		apFmtExtract(&f, u, 1, 8, false, out);
		apFmtExtract(NULL, u, 1, 8, true, raw);
		CHECK(f.n == 8 && f.b10 == 4 && f.nonUni == 1, "статистика: біт10=1 -- %lu з 8, біти 10..15 різні -- %lu (0x0400)",
				(unsigned long)f.b10, (unsigned long)f.nonUni);
		CHECK(f.nearLim == 3 && f.peak == 512, "|s| >= 480 -- %lu (480, 480, -512), пік %u", (unsigned long)f.nearLim, f.peak);
		CHECK(out[0] == 5 && out[1] == 5 && out[2] == -2 && out[5] == 480 && raw[1] == -16,
				"відліки: 10 біт / R6 «16» >> 6 (0xFC05 = -1019 -> -16)");
		uint16_t lr[4] = { 0xFC07, 0x1234, 0x0003, 0x5678 };
		int16_t l[2];
		apFmtExtract(NULL, lr, 2, 2, false, l);
		CHECK(l[0] == 7 && l[1] == 3, "L,R як у кадрі I2S: береться L (крок 2)");
	}
}

/* ---- R6: автовизначення формату ---------------------------------------------------- *
 * Генератор -- 16-бітний сигнал v (тон 1200/2200 по черзі, як AFSK, + гауссів шум). Упаковка:
 *   «16»: слово = v;
 *   «10»: слово = (v >> 6) у бітах 0..9 + випадковий біт, повторений у бітах 10..15 (запис R4:
 *         біт 10 ~50 %, без зв'язку з сигналом).
 * Рівні «10» задаються в одиницях 10 біт (A10), «16» -- у своїх (A16 = 64 * A10 за гіпотезою). */
#define DET_BLK 160
static double s_detT = 0.0;
static void detBlock(uint16_t *u, bool fmt16, double amp16, double noise16, double dc16)
{
	for (int i = 0; i < DET_BLK; i++)
	{
		double f = (fmod(s_detT, 1600.0) < 800.0) ? 1200.0 : 2200.0;
		double x = dc16 + amp16 * sin(2 * PI * f * s_detT / 8000.0) + noise16 * gauss();
		s_detT += 1.0;
		long v = lround(x);
		v = (v > 32767) ? 32767 : ((v < -32768) ? -32768 : v);
		if (fmt16)
		{
			u[i] = (uint16_t)(int16_t)v;
		}
		else
		{
			uint16_t held = (noise() < 0.0) ? 0xFC00U : 0U;
			u[i] = (uint16_t)((((uint16_t)(int16_t)(v >> 6)) & 0x3FFU) | held);
		}
	}
}

/* Подати nb блоків одного формату; повертає номер блока (з 1), на якому детектор уперше дійшов
 * формату fmt16 (0 -- не дійшов), і рахує перемикання в d. */
static int detRun(apFmtDet_t *d, int nb, bool fmt16, double amp16, double noise16, double dc16, bool inFrame)
{
	uint16_t u[DET_BLK];
	int first = 0;
	for (int b = 1; b <= nb; b++)
	{
		detBlock(u, fmt16, amp16, noise16, dc16);
		(void)apFmtDetBlock(d, u, 1, DET_BLK, inFrame);
		if ((first == 0) && ((d->is16 != 0) == fmt16))
		{
			first = b;
		}
	}
	return first;
}

static void testDet(void)
{
	printf(" R6: автовизначення формату (блоки по 160, рішення за %d блоки з доказом):\n", AP_DET_STREAK);
	apFmtDet_t d;
	int worst = 0;

	/* 1. Рішення з протилежного формату -- за <= AP_DET_STREAK блоків (кожен блок має доказ). */
	{
		static const struct { bool f16; double a16, n16; const char *name; } c[] =
		{
			{ true,     0,     3, "«16» тиша (шум 3)" },
			{ true,     0,   200, "«16» шум 200" },
			{ true,  8000,   300, "«16» гучно (тон 8000)" },
			{ true, 25000,  1000, "«16» дуже гучно (25000)" },
			{ false,    0,  3*64, "«10» тиша (шум 3 у 10 бітах)" },
			{ false,    0, 56*64, "«10» шум RMS 56 (як запис R4)" },
			{ false, 300*64, 20*64, "«10» пакет: тон 300 + шум 20" },
		};
		bool all = true;
		for (unsigned k = 0; k < sizeof(c) / sizeof(c[0]); k++)
		{
			apFmtDetInit(&d, !c[k].f16);
			int first = detRun(&d, 50, c[k].f16, c[k].a16, c[k].n16, 0, false);
			printf("      %-32s -> рішення на блоці %d, перемикань %lu\n", c[k].name, first, (unsigned long)d.switches);
			all = all && (first >= 1) && (first <= AP_DET_STREAK) && (d.switches == 1);
			worst = (first > worst) ? first : worst;
		}
		CHECK(all, "з протилежного формату -- правильне рішення не пізніше блока %d (%d мс), рівно одне перемикання",
				worst, worst * 20);
	}

	/* 2. Без хибних перемикань: довгий потік правильного формату з різними рівнями. */
	{
		static const double lv10[][2] = { { 0, 1 }, { 0, 3 }, { 0, 56 }, { 300, 20 }, { 361, 0 }, { 400, 30 }, { 450, 40 }, { 0, 0 } };
		static const double lv16[][2] = { { 0, 1 }, { 0, 50 }, { 400, 30 }, { 700, 50 }, { 900, 20 }, { 3000, 300 }, { 20000, 2000 }, { 0, 0 } };
		uint32_t ev10 = 0, ev16 = 0;
		apFmtDetInit(&d, false);
		for (int rep = 0; rep < 20; rep++)
		{
			for (unsigned k = 0; k < 8; k++)
			{
				(void)detRun(&d, 20, false, lv10[k][0] * 64, lv10[k][1] * 64, 0, false);
			}
		}
		bool ok10 = (d.switches == 0) && (d.is16 == 0);
		ev10 = d.ev10; ev16 = d.ev16;
		printf("      «10», 3200 блоків (тиша..пік 450): доказів 10/16 -- %lu/%lu, перемикань %lu\n",
				(unsigned long)ev10, (unsigned long)ev16, (unsigned long)d.switches);
		apFmtDetInit(&d, true);
		for (int rep = 0; rep < 20; rep++)
		{
			for (unsigned k = 0; k < 8; k++)
			{
				(void)detRun(&d, 20, true, lv16[k][0], lv16[k][1], 0, false);
			}
		}
		bool ok16 = (d.switches == 0) && (d.is16 != 0);
		printf("      «16», 3200 блоків (тиша..20000): доказів 10/16 -- %lu/%lu, перемикань %lu\n",
				(unsigned long)d.ev10, (unsigned long)d.ev16, (unsigned long)d.switches);
		CHECK(ok10 && ok16 && (ev16 == 0) && (d.ev10 == 0), "довгі потоки правильного формату -- 0 хибних перемикань і 0 хибних доказів");
	}

	/* 3. Зміна формату посеред потоку (як перезапуск I2S): 16 -> 10 -> 16. */
	{
		apFmtDetInit(&d, true);
		int a = detRun(&d, 40, true, 3000, 200, 0, false);
		int b = detRun(&d, 40, false, 200 * 64, 10 * 64, 0, false);
		int c = detRun(&d, 40, true, 0, 5, 0, false);
		CHECK((a == 1) && (b >= 1) && (b <= AP_DET_STREAK) && (c >= 1) && (c <= AP_DET_STREAK) && (d.switches == 2),
				"16 -> 10 -> 16 посеред потоку: рішення на блоці %d і %d після зміни, перемикань %lu", b, c, (unsigned long)d.switches);
	}

	/* 4. Посеред кадру демодулятора формат не міняється: чекаємо кінця кадру, але не довше за
	 *    AP_DET_HOLD_MAX блоків. */
	{
		apFmtDetInit(&d, false);
		int inF = detRun(&d, 30, true, 3000, 200, 0, true);    /* «кадр» триває: доказ 16, але чекаємо */
		int after = detRun(&d, 5, true, 3000, 200, 0, false); /* кадр скінчився */
		bool held = (inF == 0) && (after == 1) && (d.switches == 1);
		apFmtDetInit(&d, false);
		int capped = detRun(&d, AP_DET_HOLD_MAX + AP_DET_STREAK + 5, true, 3000, 200, 0, true);
		CHECK(held && (capped == AP_DET_HOLD_MAX + AP_DET_STREAK),
				"посеред кадру -- чекає (0 перемикань за 30 блоків), після кадру -- одразу; «вічний» кадр -- не довше за %d блоків (%d)",
				AP_DET_HOLD_MAX, capped);
	}

	/* 5. Блоки без доказу (16 біт у смузі 512..1024 без тиші) не перемикають і не рвуть серію. */
	{
		apFmtDetInit(&d, true);
		int f = detRun(&d, 200, true, 800, 20, 0, false);
		CHECK((d.switches == 0) && (f == 1), "«16» з тоном 800 (неоднозначна смуга) -- перемикань %lu, доказів 10/16 %lu/%lu",
				(unsigned long)d.switches, (unsigned long)d.ev10, (unsigned long)d.ev16);
	}
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
	testFmt();
	testDet();

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
