/*
 * aprs_probe_dsp.c -- рівень і тони 1200/2200 Гц для екрана «APRS проба» (R2).
 * Опис -- у aprs_probe_dsp.h. Чистий C без заліза: той самий файл збирає хост-тест.
 */
#include "functions/aprs_probe_dsp.h"

#if defined(ENABLE_APRS_RX_PROBE)

#include <stddef.h>

/* 2*cos(2*pi*f/fs). Константами, а не cosf(): так не тягнеться libm, а хост-тест звіряє їх
 * із math.h (tests/test_aprs_probe_dsp.c). */
#define AP_C1200_8000   1.1755705f
#define AP_C2200_8000  (-0.3128689f)
#define AP_C1200_9600   1.4142136f
#define AP_C2200_9600   0.2610524f

/* 1 дБ за амплітудою = 10^(1/20). */
#define AP_DB_STEP      1.1220185f

static void blockReset(apChan_t *c)
{
	c->q1a = c->q2a = 0.0f;
	c->q1b = c->q2b = 0.0f;
	c->idx = 0;
}

static void winReset(apChan_t *c)
{
	c->blocks = 0;
	c->sum = 0;
	c->sumSq = 0;
	c->min = INT32_MAX;
	c->max = INT32_MIN;
	c->p1200 = 0.0f;
	c->p2200 = 0.0f;
	c->n = 0;
}

void apChanInit(apChan_t *c, uint32_t fs, uint16_t blockLen, uint16_t blocksPerWin, int32_t ref)
{
	if (fs == AP_FS_I2S)
	{
		c->c1200 = AP_C1200_8000;
		c->c2200 = AP_C2200_8000;
	}
	else if (fs == AP_FS_ADC)
	{
		c->c1200 = AP_C1200_9600;
		c->c2200 = AP_C2200_9600;
	}
	else
	{
		c->c1200 = 0.0f;
		c->c2200 = 0.0f;
	}
	c->blockLen = (blockLen > 0) ? blockLen : 1;
	c->blocksPerWin = (blocksPerWin > 0) ? blocksPerWin : 1;
	c->ref = ref;
	blockReset(c);
	winReset(c);
}

uint32_t apIsqrt64(uint64_t v)
{
	uint64_t res = 0;
	uint64_t bit = (uint64_t)1 << 62;

	while (bit > v)
	{
		bit >>= 2;
	}
	while (bit != 0)
	{
		if (v >= res + bit)
		{
			v -= res + bit;
			res = (res >> 1) + bit;
		}
		else
		{
			res >>= 1;
		}
		bit >>= 2;
	}
	return (uint32_t)res;
}

int16_t apRatioDb(uint32_t a, uint32_t b)
{
	if ((a == 0) && (b == 0))
	{
		return 0;
	}
	if (b == 0)
	{
		return AP_DB_LIMIT;
	}
	if (a == 0)
	{
		return -AP_DB_LIMIT;
	}

	bool neg = (a < b);
	float r = neg ? ((float)b / (float)a) : ((float)a / (float)b);
	int16_t db = 0;

	/* Округлення до найближчого дБ: порівнюємо з 10^((db+0.5)/20). */
	float edge = 1.0592537f;   /* 10^(0.5/20) */
	while ((r >= edge) && (db < AP_DB_LIMIT))
	{
		db++;
		edge *= AP_DB_STEP;
	}
	return neg ? (int16_t)-db : db;
}

uint8_t apWinner(uint32_t a1200, uint32_t a2200)
{
	/* Переважає -- якщо вдвічі (6 дБ) більше; інакше «рівні». */
	if ((uint64_t)a1200 >= 2ULL * a2200 && (a1200 > 0))
	{
		return AP_WIN_1200;
	}
	if ((uint64_t)a2200 >= 2ULL * a1200 && (a2200 > 0))
	{
		return AP_WIN_2200;
	}
	return AP_WIN_NONE;
}

static uint32_t toneAmp(float pSum, uint16_t blocks, uint16_t blockLen)
{
	if (blocks == 0)
	{
		return 0;
	}
	/* Синусоїда амплітуди A рівно на біні дає |X| = A*N/2, тобто A = 2*sqrt(P)/N. */
	float n = (float)blockLen;
	float a2 = (4.0f * (pSum / (float)blocks)) / (n * n);
	if (a2 < 0.0f)
	{
		a2 = 0.0f;
	}
	if (a2 > 4.0e18f)
	{
		a2 = 4.0e18f;
	}
	return apIsqrt64((uint64_t)a2);
}

static void winClose(apChan_t *c, apResult_t *out)
{
	uint32_t n = c->n;
	int32_t mean = c->ref;
	uint32_t rms = 0;

	if (n > 0)
	{
		/* var * n^2 = n*sumSq - sum^2 (усе цілочисельно: n <= ~2300, |x - ref| <= 65535). */
		int64_t s = c->sum;
		uint64_t s2 = (uint64_t)(s < 0 ? -s : s);
		s2 *= s2;
		uint64_t nq = (uint64_t)n * c->sumSq;
		uint64_t varN2 = (nq > s2) ? (nq - s2) : 0;
		rms = apIsqrt64(varN2 / ((uint64_t)n * n));

		/* Округлення середнього до найближчого цілого (і для від'ємних). */
		int64_t q = (s >= 0) ? ((s + (int64_t)(n / 2)) / (int64_t)n) : -((-s + (int64_t)(n / 2)) / (int64_t)n);
		mean = c->ref + (int32_t)q;
	}

	if (out != NULL)
	{
		out->mean = mean;
		out->rms = rms;
		if (n > 0)
		{
			int32_t up = c->max - mean;
			int32_t dn = mean - c->min;
			if (up < 0) { up = 0; }
			if (dn < 0) { dn = 0; }
			out->peak = (uint32_t)((up > dn) ? up : dn);
		}
		else
		{
			out->peak = 0;
		}
		out->a1200 = toneAmp(c->p1200, c->blocks, c->blockLen);
		out->a2200 = toneAmp(c->p2200, c->blocks, c->blockLen);
		out->ratioDb = apRatioDb(out->a1200, out->a2200);
		out->winner = apWinner(out->a1200, out->a2200);
		{
			uint32_t strong = (out->a1200 > out->a2200) ? out->a1200 : out->a2200;
			uint32_t floorAmp = rms / 8U;
			if (floorAmp < 2U)
			{
				floorAmp = 2U;
			}
			if (strong < floorAmp)
			{
				out->winner = AP_WIN_WEAK;
			}
		}
		out->valid = (n > 0) ? 1 : 0;
		out->n = n;
	}

	c->ref = mean;   /* наступне вікно -- відносно щойно виміряного DC */
	winReset(c);
}

bool apChanPush(apChan_t *c, int32_t x, apResult_t *out)
{
	int32_t d = x - c->ref;
	float fd = (float)d;
	float s;

	c->sum += d;
	c->sumSq += (uint64_t)((int64_t)d * (int64_t)d);
	if (x < c->min) { c->min = x; }
	if (x > c->max) { c->max = x; }
	c->n++;

	s = fd + c->c1200 * c->q1a - c->q2a;
	c->q2a = c->q1a;
	c->q1a = s;
	s = fd + c->c2200 * c->q1b - c->q2b;
	c->q2b = c->q1b;
	c->q1b = s;

	if (++c->idx >= c->blockLen)
	{
		c->p1200 += (c->q1a * c->q1a) + (c->q2a * c->q2a) - (c->c1200 * c->q1a * c->q2a);
		c->p2200 += (c->q1b * c->q1b) + (c->q2b * c->q2b) - (c->c2200 * c->q1b * c->q2b);
		blockReset(c);

		if (++c->blocks >= c->blocksPerWin)
		{
			winClose(c, out);
			return true;
		}
	}
	return false;
}

#endif /* ENABLE_APRS_RX_PROBE */
