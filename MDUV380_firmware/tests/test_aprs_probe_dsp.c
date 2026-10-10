/*
 * test_aprs_probe_dsp.c -- R2: рівень і тони 1200/2200 Гц для екрана «APRS проба»
 * (functions/aprs_probe_dsp.c). Синтетичні сигнали при 8000 Гц (I2S, блок 160) і 9600 Гц
 * (АЦП, блок 192): правильний «переможець», амплітуди, RMS, DC, пік, дБ.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

/* ---- R5/R7: формат відліку I2S RX ------------------------------------------------- */
static void testFmt(void)
{
	printf(" формат відліку (apSampleN, масштаб 10 біт):\n");
	CHECK(apSampleN(0x0000, 10) == 0 && apSampleN(0x01FF, 10) == 511 && apSampleN(0x0200, 10) == -512 && apSampleN(0x03FF, 10) == -1,
			"nbits=10: 0 / 511 / -512 / -1");
	CHECK(apSampleN(0xFC05, 10) == 5 && apSampleN(0xFFFF, 10) == -1 && apSampleN(0x0400, 10) == 0 && apSampleN(0xFE00, 10) == -512,
			"nbits=10 ігнорує біти 10..15: 0xFC05 -> 5, 0xFFFF -> -1, 0x0400 -> 0, 0xFE00 -> -512");
	CHECK(apSampleN(0x0005, 0) == 5 && apSampleN(0x03FF, 0) == -1, "nbits=0 (вердикту ще нема) -- як 10");
	/* nbits=11: біти 0..10, знак у біті 10, масштаб >> 1; сміття в бітах 11..15 */
	CHECK(apSampleN(0x03FF, 11) == 511 && apSampleN(0x0400, 11) == -512 && apSampleN(0x07FF, 11) == -1 &&
			apSampleN(0xF805, 11) == 2 && apSampleN(0xFC00, 11) == -512,
			"nbits=11: 0x03FF -> 511, 0x0400 -> -512, 0x07FF -> -1, 0xF805 -> 2, 0xFC00 -> -512");
	/* nbits=16: v >> 6; nbits=8: ліворуч на 2 */
	CHECK(apSampleN(0xFC05, 16) == -16 && apSampleN(0x7FFF, 16) == 511 && apSampleN(0x8000, 16) == -512 && apSampleN(0x003F, 16) == 0,
			"nbits=16: 0xFC05 -> -16, 0x7FFF -> 511, 0x8000 -> -512, 0x003F -> 0");
	CHECK(apSampleN(0x007F, 8) == 508 && apSampleN(0x0080, 8) == -512 && apSampleN(0xFF01, 8) == 4,
			"nbits=8: 0x007F -> 508, 0x0080 -> -512, 0xFF01 -> 4");
	{
		const uint16_t u[8] = { 0x0005, 0xFC05, 0x03FE, 0xFDE0, 0x0400, 0x01E0, 0x0200, 0xFFFF };
		/* nbits=10:            5       5      -2       480      0       480     -512    -1 */
		int16_t out[8], raw[8];
		apFmt_t f;
		apFmtInit(&f);
		apFmtExtract(&f, u, 1, 8, 10, out);
		apFmtExtract(NULL, u, 1, 8, 16, raw);
		CHECK(f.n == 8 && f.nearLim == 3 && f.peak == 512, "статистика: |s| >= 480 -- %lu (480, 480, -512), пік %u", (unsigned long)f.nearLim, f.peak);
		CHECK(out[0] == 5 && out[1] == 5 && out[2] == -2 && out[5] == 480 && raw[1] == -16, "відліки: nbits=10 / nbits=16 (0xFC05 = -1019 -> -16)");
		uint16_t lr[4] = { 0xFC07, 0x1234, 0x0003, 0x5678 };
		int16_t l[2];
		apFmtExtract(NULL, lr, 2, 2, 10, l);
		CHECK(l[0] == 7 && l[1] == 3, "L,R як у кадрі I2S: береться L (крок 2)");
	}
}

/* ---- R7: детектор nbits -------------------------------------------------------------- *
 * Генератор -- 16-бітний сигнал v (тон 1200/2200 по черзі, як AFSK, + гауссів шум). Упаковка:
 *   nbits < 16: слово = (k однакових випадкових бітів) << nbits | ((v >> k) & маска),  k = 16 - nbits
 *               (модель з docs/aprs-rx-feasibility.md, розділ 11; k = 6 -- запис R4, k = 5 -- R6);
 *   nbits = 16: слово = v. */
#define DET_BLK 160
static double s_detT = 0.0;
static void detBlock(uint16_t *u, int nbits, double amp16, double noise16)
{
	for (int i = 0; i < DET_BLK; i++)
	{
		double f = (fmod(s_detT, 1600.0) < 800.0) ? 1200.0 : 2200.0;
		double x = amp16 * sin(2 * PI * f * s_detT / 8000.0) + noise16 * gauss();
		s_detT += 1.0;
		long v = lround(x);
		v = (v > 32767) ? 32767 : ((v < -32768) ? -32768 : v);
		if (nbits >= 16)
		{
			u[i] = (uint16_t)(int16_t)v;
		}
		else
		{
			int k = 16 - nbits;
			uint32_t mask = (1UL << nbits) - 1UL;
			uint32_t garbage = (noise() < 0.0) ? (0xFFFFU << nbits) & 0xFFFFU : 0U;
			u[i] = (uint16_t)((((uint32_t)(int32_t)v >> k) & mask) | garbage);
		}
	}
}

/* nb блоків одного формату: номер блока (з 1), на якому детектор уперше дав nbits; -1 -- ніколи;
 * *wrong -- скільки блоків проголосували за ІНШИЙ (хибний, ненульовий) nbits. */
static int detRun(apFmtDet_t *d, int nb, int nbits, double amp16, double noise16, bool inFrame, int *wrong)
{
	uint16_t u[DET_BLK];
	int first = -1;
	for (int b = 1; b <= nb; b++)
	{
		detBlock(u, nbits, amp16, noise16);
		(void)apFmtDetBlock(d, u, 1, DET_BLK, inFrame);
		if ((d->lastVote != 0) && (d->lastVote != nbits) && (wrong != NULL))
		{
			(*wrong)++;
		}
		if ((first < 0) && (d->nbits == nbits))
		{
			first = b;
		}
	}
	return first;
}

static void testDet(void)
{
	printf(" R7: детектор nbits (блоки по 160, вердикт за %d однакових голоси):\n", AP_DET_STREAK);
	apFmtDet_t d;

	/* 1. Вердикт для nbits = 8..15 і 16: шум RMS 56 (10 біт; запис R4) у масштабі 16 біт, плюс тиша,
	 *    плюс пакет. Не пізніше блока AP_DET_STREAK, жодного хибного голосу. */
	{
		static const struct { double a16, n16; const char *name; } lv[] =
		{
			{ 0, 3.0 * 64, "тиша (шум 3 у 10 бітах)" },
			{ 0, 56.0 * 64, "шум RMS 56 (як запис R4)" },
			{ 300.0 * 64 * 0.5, 20.0 * 64, "пакет: тон 150 + шум 20 (10 біт)" },
		};
		bool all = true;
		int worst = 0, wrongAll = 0;
		for (int nbits = 8; nbits <= 15; nbits++)
		{
			for (unsigned k = 0; k < sizeof(lv) / sizeof(lv[0]); k++)
			{
				int wrong = 0;
				apFmtDetInit(&d);
				int first = detRun(&d, 50, nbits, lv[k].a16, lv[k].n16, false, &wrong);
				all = all && (first >= 1) && (first <= AP_DET_STREAK) && (d.switches == 0) && (d.nbits == nbits);
				wrongAll += wrong;
				worst = (first > worst) ? first : worst;
				if (nbits >= 10 && nbits <= 12)
				{
					printf("      nbits=%-2d %-34s -> вердикт на блоці %d, хибних голосів %d\n", nbits, lv[k].name, first, wrong);
				}
			}
		}
		CHECK(all && (wrongAll == 0), "nbits=8..15, три рівні: вердикт не пізніше блока %d (%d мс), без перемикань і без хибних голосів (%d)",
				worst, worst * 20, wrongAll);
	}

	/* 2. Справжні 16 біт: sigma 3600 і 300 (ТЗ R7), тиша, гучно -- вердикт 16, жодного голосу за сміття. */
	{
		/* verdict = 0: чистий гучний тон майже без шуму -- профіль має «обрив» (c[j-1] великий), детектор
		 * нейтральний (вердикту немає, але й хибного голосу теж) */
		static const struct { double a16, n16; int verdict; const char *name; } lv[] =
		{
			{ 0, 3600, 1, "sigma 3600" }, { 0, 300, 1, "sigma 300" }, { 0, 30, 1, "sigma 30" }, { 0, 3, 1, "тиша (шум 3)" },
			{ 8000, 3000, 1, "тон 8000 + шум 3000" }, { 600, 20, 0, "чистий тон 600 (обрив)" },
			{ 3000, 200, 0, "чистий тон 3000 (обрив)" }, { 25000, 1000, 0, "чистий тон 25000 (обрив)" },
		};
		bool all = true;
		int wrongAll = 0, worst = 0;
		for (unsigned k = 0; k < sizeof(lv) / sizeof(lv[0]); k++)
		{
			int wrong = 0;
			apFmtDetInit(&d);
			int first = detRun(&d, 50, 16, lv[k].a16, lv[k].n16, false, &wrong);
			printf("      16 біт %-26s -> вердикт на блоці %d, хибних голосів %d\n", lv[k].name, first, wrong);
			if (lv[k].verdict)
			{
				all = all && (first >= 1) && (first <= AP_DET_STREAK + 3) && (d.switches == 0);   /* нейтральні блоки на межі c[top] ~ 0,3 затримують серію */
				worst = (first > worst) ? first : worst;
			}
			wrongAll += wrong;
		}
		CHECK(all && (wrongAll == 0), "справжні 16 біт (sigma 3600/300/30, тиша, тон + шум): вердикт 16 не пізніше блока %d, хибних голосів %d", worst, wrongAll);
	}

	/* 3. Гучні пакети в режимі зі сміттям (|s| часто >= 2^(j-2)): голос або правильний, або нейтральний,
	 *    ніколи не «16» і не чужий nbits (відхилення від ТЗ: див. aprs_probe_dsp.h). */
	{
		int wrongAll = 0, neutral = 0, total = 0;
		for (int nbits = 10; nbits <= 12; nbits++)
		{
			for (int a10 = 100; a10 <= 700; a10 += 50)   /* амплітуда тону в одиницях 10 біт (>= 512 -- перекидання) */
			{
				uint16_t u[DET_BLK];
				apFmtDet_t t;
				apFmtDetInit(&t);
				for (int b = 0; b < 40; b++)
				{
					detBlock(u, nbits, a10 * 64.0 * ((a10 > 480) ? 0.6 : 1.0), 20.0 * 64);
					uint8_t v = apFmtVote(&t, u, 1, DET_BLK);
					total++;
					neutral += (v == 0);
					wrongAll += (v != 0) && (v != nbits);
				}
			}
		}
		CHECK(wrongAll == 0, "гучні пакети в режимі зі сміттям: хибних голосів 0 (нейтральних %d з %d)", neutral, total);
	}

	/* 4. Довгі потоки правильного формату -- без хибних перемикань. */
	{
		static const double lv[][2] = { { 0, 1 }, { 0, 3 }, { 0, 56 }, { 300, 20 }, { 361, 0 }, { 400, 30 }, { 450, 40 }, { 0, 0 } };
		static const double lv16[][2] = { { 0, 1 }, { 0, 3 }, { 0, 300 }, { 0, 3600 }, { 3000, 3000 }, { 8000, 3000 }, { 12000, 2000 }, { 0, 0 } };
		static const int fmts[] = { 10, 11, 12, 16 };
		bool all = true;
		for (unsigned f = 0; f < 4; f++)
		{
			int wrong = 0;
			apFmtDetInit(&d);
			for (int rep = 0; rep < 20; rep++)
			{
				for (unsigned k = 0; k < 8; k++)
				{
					/* рівні сміттєвих форматів задані в одиницях 10 біт -> у 16 біт *64; для 16 біт -- свій набір */
					if (fmts[f] == 16)
					{
						(void)detRun(&d, 20, 16, lv16[k][0], lv16[k][1], false, &wrong);
					}
					else
					{
						(void)detRun(&d, 20, fmts[f], lv[k][0] * 64, lv[k][1] * 64, false, &wrong);
					}
				}
			}
			printf("      nbits=%-2d, 3200 блоків: перемикань %lu, хибних голосів %d, вердикт %u\n", fmts[f], (unsigned long)d.switches, wrong, d.nbits);
			all = all && (d.switches == 0) && (d.nbits == fmts[f]) && (wrong == 0);
		}
		CHECK(all, "довгі потоки правильного формату (10/11/12/16 біт) -- 0 хибних перемикань і 0 хибних голосів");
	}

	/* 5. Зміна формату посеред потоку (як перезапуск I2S): 16 -> 10 -> 11 -> 16. */
	{
		apFmtDetInit(&d);
		int a = detRun(&d, 40, 16, 0, 3000, false, NULL);
		int b = detRun(&d, 40, 10, 200 * 64, 10 * 64, false, NULL);
		int c = detRun(&d, 40, 11, 0, 56 * 64, false, NULL);
		int e = detRun(&d, 40, 16, 0, 300, false, NULL);
		CHECK((a >= 1) && (b >= 1) && (b <= AP_DET_STREAK) && (c >= 1) && (c <= AP_DET_STREAK) && (e >= 1) && (e <= AP_DET_STREAK) && (d.switches == 3),
				"16 -> 10 -> 11 -> 16 посеред потоку: вердикт на блоці %d / %d / %d після зміни, змін %lu", b, c, e, (unsigned long)d.switches);
		/* новий старт I2S: вердикт забуто, перший вердикт змін не рахує */
		apFmtDetRestart(&d);
		CHECK((d.nbits == 0) && (d.switches == 3), "apFmtDetRestart: вердикту нема, switches лишився (%lu)", (unsigned long)d.switches);
		(void)detRun(&d, 10, 11, 0, 56 * 64, false, NULL);
		CHECK((d.nbits == 11) && (d.switches == 3), "перший вердикт після рестарту (nbits=11) не рахується як перемикання");
	}

	/* 6. Посеред кадру демодулятора nbits не міняється: чекаємо кінця кадру, але не довше за AP_DET_HOLD_MAX. */
	{
		apFmtDetInit(&d);
		(void)detRun(&d, 10, 10, 0, 56 * 64, false, NULL);
		int inF = detRun(&d, 30, 16, 0, 3000, true, NULL);    /* «кадр» триває: голоси за 16, але чекаємо */
		int after = detRun(&d, 5, 16, 0, 3000, false, NULL);  /* кадр скінчився */
		bool held = (inF < 0) && (after == 1) && (d.switches == 1);
		apFmtDetInit(&d);
		(void)detRun(&d, 10, 10, 0, 56 * 64, false, NULL);
		int capped = detRun(&d, AP_DET_HOLD_MAX + AP_DET_STREAK + 5, 16, 0, 3000, true, NULL);
		CHECK(held && (capped == AP_DET_HOLD_MAX + AP_DET_STREAK),
				"посеред кадру -- чекає (0 змін за 30 блоків), після кадру -- одразу; «вічний» кадр -- не довше за %d блоків (%d)", AP_DET_HOLD_MAX, capped);
	}

	/* 7. Реальні блоки: 200 блоків шуму без пакетів із запису R4 (k = 6, tests/fixtures/aprs_i2s_k6_noise.bin;
	 *    запис містить позицію власника -- у репозиторії лише блоки без пакета: RMS <= 75, пік <= 250). */
	{
		char path[512];
		const char *slash = strrchr(__FILE__, '/');
		snprintf(path, sizeof(path), "%.*sfixtures/aprs_i2s_k6_noise.bin", (int)(slash ? (slash - __FILE__ + 1) : 0), __FILE__);
		FILE *fp = fopen(path, "rb");
		if (fp == NULL)
		{
			CHECK(0, "фікстура %s не відкрилась", path);
		}
		else
		{
			static uint16_t fx[200 * DET_BLK];
			size_t nw = fread(fx, sizeof(uint16_t), sizeof(fx) / sizeof(fx[0]), fp);
			fclose(fp);
			int nb = (int)(nw / DET_BLK), v10 = 0, other = 0;
			apFmtDetInit(&d);
			for (int b = 0; b < nb; b++)
			{
				uint8_t v = apFmtVote(NULL, &fx[b * DET_BLK], 1, DET_BLK);
				v10 += (v == 10);
				other += (v != 10);
				(void)apFmtDetBlock(&d, &fx[b * DET_BLK], 1, DET_BLK, false);
			}
			CHECK((nb == 200) && (v10 == 200) && (other == 0) && (d.nbits == 10) && (d.switches == 0),
					"реальний шум (запис R4, k=6): %d з %d блоків -- голос 10, вердикт %u, перемикань %lu", v10, nb, d.nbits, (unsigned long)d.switches);
		}
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
