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

/* ---- R3: розгортка фону ------------------------------------------------------ */

/* 2*cos(2*pi*f/8000), f = 100 + 50*i (згенеровано; хост-тест звіряє з math.h). */
const float apSweepCoeff[AP_SWEEP_BINS] =
{
	 1.99383467f,  1.98613691f,  1.97537668f,  1.96157056f,  1.94473984f,  1.92491047f,  1.90211303f,
	 1.87638267f,  1.84775907f,  1.81628635f,  1.78201305f,  1.74499201f,  1.70528033f,  1.66293922f,
	 1.61803399f,  1.57063386f,  1.52081193f,  1.46864502f,  1.41421356f,  1.35760149f,  1.29889610f,
	 1.23818790f,  1.17557050f,  1.11114047f,  1.04499713f,  0.97724248f,  0.90798100f,  0.83731948f,
	 0.76536686f,  0.69223411f,  0.61803399f,  0.54288090f,  0.46689073f,  0.39018064f,  0.31286893f,
	 0.23507479f,  0.15691819f,  0.07851963f,  0.00000000f, -0.07851963f, -0.15691819f, -0.23507479f,
	-0.31286893f, -0.39018064f, -0.46689073f, -0.54288090f, -0.61803399f, -0.69223411f, -0.76536686f,
	-0.83731948f, -0.90798100f, -0.97724248f, -1.04499713f, -1.11114047f, -1.17557050f, -1.23818790f,
	-1.29889610f, -1.35760149f, -1.41421356f, -1.46864502f, -1.52081193f, -1.57063386f, -1.61803399f,
	-1.66293922f, -1.70528033f, -1.74499201f, -1.78201305f, -1.81628635f, -1.84775907f, -1.87638267f,
	-1.90211303f, -1.92491047f, -1.94473984f, -1.96157056f, -1.97537668f, -1.98613691f, -1.99383467f
};

float apCos2(float hz)
{
	float x = (hz - (float)AP_SWEEP_F0) / (float)AP_SWEEP_STEP;
	if (x <= 0.0f)
	{
		return apSweepCoeff[0];
	}
	if (x >= (float)(AP_SWEEP_BINS - 1))
	{
		return apSweepCoeff[AP_SWEEP_BINS - 1];
	}
	int i = (int)x;
	float t = x - (float)i;
	return apSweepCoeff[i] + t * (apSweepCoeff[i + 1] - apSweepCoeff[i]);
}

void apBgInit(apBg_t *b)
{
	for (int i = 0; i < AP_SWEEP_BINS; i++)
	{
		b->pw[i] = 0.0f;
	}
	b->sumSq = 0.0f;
	b->n = 0;
	b->sum = 0;
	b->part = 0;
	b->rounds = 0;
}

static uint32_t sqrtF(float v)
{
	if (v <= 0.0f)
	{
		return 0;
	}
	if (v > 1.8e19f)
	{
		v = 1.8e19f;
	}
	return apIsqrt64((uint64_t)v);
}

static void bgClose(apBg_t *b, apBgResult_t *out)
{
	const float rounds = (float)AP_SWEEP_ROUNDS;
	float *mean = b->pw;   /* середнє -- на місці сум (вікно однаково скидається після) */
	float floorP = 0.0f;
	int k1 = 0, k2 = -1;

	for (int i = 0; i < AP_SWEEP_BINS; i++)
	{
		mean[i] /= rounds;
		floorP += mean[i];
		if (mean[i] > mean[k1])
		{
			k1 = i;
		}
	}
	floorP /= (float)AP_SWEEP_BINS;
	for (int i = 0; i < AP_SWEEP_BINS; i++)
	{
		if ((i >= k1 - 2) && (i <= k1 + 2))
		{
			continue;
		}
		if ((k2 < 0) || (mean[i] > mean[k2]))
		{
			k2 = i;
		}
	}

	/* Уточнення топ-1: для прямокутного вікна |X(k+1)| / |X(k)| = d / (1 - d), де d -- зсув частоти
	 * в бінах від k у бік сусіда, тобто d = |X(k+1)| / (|X(k)| + |X(k+1)|). Шум віднімаємо за
	 * середнім рівнем (оцінка «підлоги»). */
	int kn = k1;
	if ((k1 > 0) && ((k1 + 1 >= AP_SWEEP_BINS) || (mean[k1 - 1] > mean[k1 + 1])))
	{
		kn = k1 - 1;
	}
	else if (k1 + 1 < AP_SWEEP_BINS)
	{
		kn = k1 + 1;
	}
	float ak = (float)sqrtF(mean[k1] - floorP);
	float an = (kn != k1) ? (float)sqrtF(mean[kn] - floorP) : 0.0f;
	float d = ((ak + an) > 0.0f) ? (an / (ak + an)) : 0.0f;
	float f1 = (float)(AP_SWEEP_F0 + AP_SWEEP_STEP * k1) + ((kn > k1) ? d : -d) * (float)AP_SWEEP_STEP;

	/* Амплітуда синусоїди з поправкою на sinc зсуву: A = 2|X(k)| / (N sinc d),
	 * sinc d ~ 1 - (pi d)^2/6 + (pi d)^4/120 (d <= 0,5: похибка < 0,1 %). */
	float pd2 = 9.8696044f * d * d;
	float sinc = 1.0f - pd2 / 6.0f + (pd2 * pd2) / 120.0f;
	float a1 = (2.0f * (float)sqrtF(mean[k1])) / ((float)AP_SWEEP_N * sinc);

	uint32_t n = b->n;
	float var = (n > 0) ? (b->sumSq / (float)n) : 0.0f;
	uint32_t rms = sqrtF(var);

	out->f1 = f1;
	out->a1 = (uint32_t)(a1 + 0.5f);
	{
		/* RMS тону = A / sqrt(2) */
		float sh = (rms > 0) ? ((a1 * 0.70710678f * 100.0f) / (float)rms) : 0.0f;
		out->share1 = (uint8_t)((sh > 100.0f) ? 100.0f : (sh + 0.5f));
	}
	out->f2 = (uint16_t)(AP_SWEEP_F0 + AP_SWEEP_STEP * ((k2 < 0) ? 0 : k2));
	out->a2 = (k2 < 0) ? 0 : ((2U * sqrtF(mean[k2])) / AP_SWEEP_N);
	out->rms = rms;
	out->mean = (n > 0) ? (int32_t)(b->sum / (int32_t)n) : 0;
	out->valid = (n > 0) ? 1 : 0;
}

bool apBgBlock(apBg_t *b, const int16_t *x, apBgResult_t *out)
{
	/* Рівень: середнє блока й сума квадратів відхилень від нього (DC не псує точність float). */
	int32_t s = 0;
	for (int i = 0; i < AP_SWEEP_N; i++)
	{
		s += x[i];
	}
	int32_t m = s / AP_SWEEP_N;
	int64_t sq = 0;
	for (int i = 0; i < AP_SWEEP_N; i++)
	{
		int32_t dv = x[i] - m;
		sq += (int64_t)dv * dv;
	}
	b->sumSq += (float)sq;
	b->sum += s;
	b->n += AP_SWEEP_N;

	/* Своя група частот (Goertzel; частоти рівно на бінах -- DC не заважає). */
	int k0 = b->part * AP_SWEEP_PER_BLOCK;
	int k1 = k0 + AP_SWEEP_PER_BLOCK;
	if (k1 > AP_SWEEP_BINS)
	{
		k1 = AP_SWEEP_BINS;
	}
	for (int k = k0; k < k1; k++)
	{
		float c = apSweepCoeff[k];
		float q1 = 0.0f, q2 = 0.0f;
		for (int i = 0; i < AP_SWEEP_N; i++)
		{
			float q0 = (float)(x[i] - m) + c * q1 - q2;
			q2 = q1;
			q1 = q0;
		}
		b->pw[k] += (q1 * q1) + (q2 * q2) - (c * q1 * q2);
	}

	if (k1 >= AP_SWEEP_BINS)
	{
		b->part = 0;
		if (++b->rounds >= AP_SWEEP_ROUNDS)
		{
			bgClose(b, out);
			apBgInit(b);
			return true;
		}
	}
	else
	{
		b->part++;
	}
	return false;
}

float apBgNotchHz(const apBgResult_t *r)
{
	float f = r->f1;
	if ((r->valid == 0) || (r->share1 < 50) || (f < 900.0f) || (f > 2500.0f))
	{
		return 0.0f;
	}
	if (((f > 1100.0f) && (f < 1300.0f)) || ((f > 2100.0f) && (f < 2300.0f)))
	{
		return 0.0f;
	}
	return f;
}

/* ---- R4: безперервність потоку ------------------------------------------------- */

/* cos/sin(2*pi*1200*n/8000) = cos/sin(2*pi*3n/20): період -- 20 відліків. */
static const float s_c1200[20] =
{
	1.00000000f, 0.58778525f, -0.30901699f, -0.95105652f, -0.80901699f,
	-0.00000000f, 0.80901699f, 0.95105652f, 0.30901699f, -0.58778525f,
	-1.00000000f, -0.58778525f, 0.30901699f, 0.95105652f, 0.80901699f,
	0.00000000f, -0.80901699f, -0.95105652f, -0.30901699f, 0.58778525f
};
static const float s_s1200[20] =
{
	0.00000000f, 0.80901699f, 0.95105652f, 0.30901699f, -0.58778525f,
	-1.00000000f, -0.58778525f, 0.30901699f, 0.95105652f, 0.80901699f,
	0.00000000f, -0.80901699f, -0.95105652f, -0.30901699f, 0.58778525f,
	1.00000000f, 0.58778525f, -0.30901699f, -0.95105652f, -0.80901699f
};

float apAtan2Deg(float y, float x)
{
	float ax = (x < 0.0f) ? -x : x;
	float ay = (y < 0.0f) ? -y : y;
	if ((ax < 1e-20f) && (ay < 1e-20f))
	{
		return 0.0f;
	}
	float a = (ax > ay) ? (ay / ax) : (ax / ay);
	float q = a * a;
	float r = ((((0.0208351f * q - 0.0851330f) * q + 0.1801410f) * q - 0.3302995f) * q + 0.9998660f) * a;
	if (ay > ax)
	{
		r = 1.57079633f - r;
	}
	if (x < 0.0f)
	{
		r = 3.14159265f - r;
	}
	if (y < 0.0f)
	{
		r = -r;
	}
	return r * 57.2957795f;
}

void apStreamInit(apStream_t *st)
{
	st->prevRe = st->prevIm = 0.0f;
	st->havePrev = 0;
	st->blocks = st->jumpsB = st->jumpsIn = 0;
	st->maxB = st->maxIn = 0;
	st->amp = 0;
	st->sumDphi = 0.0f;
	st->nDphi = 0;
}

static void halfPhasor(const int16_t *x, int n0, float *re, float *im)
{
	float r = 0.0f, i = 0.0f;
	for (int n = n0; n < n0 + 80; n++)
	{
		int k = n % 20;
		r += (float)x[n] * s_c1200[k];
		i -= (float)x[n] * s_s1200[k];
	}
	*re = r;
	*im = i;
}

/* Кут між фазорами (b відносно a), град, 0..180. */
static float angleBetween(float aRe, float aIm, float bRe, float bIm)
{
	float re = bRe * aRe + bIm * aIm;   /* b * conj(a) */
	float im = bIm * aRe - bRe * aIm;
	float d = apAtan2Deg(im, re);
	return (d < 0.0f) ? -d : d;
}

static uint16_t clampDeg(float d)
{
	return (uint16_t)((d > 180.0f) ? 180.0f : (d + 0.5f));
}

void apStreamBlock(apStream_t *st, const int16_t *x)
{
	float r1, i1, r2, i2;
	halfPhasor(x, 0, &r1, &i1);
	halfPhasor(x, 80, &r2, &i2);

	/* амплітуда синусоїди: |X| = A * N / 2, N = 80 */
	float m1 = r1 * r1 + i1 * i1, m2 = r2 * r2 + i2 * i2;
	float a2 = (m1 < m2) ? m1 : m2;                 /* слабша половина */
	uint32_t amp = (2U * apIsqrt64((uint64_t)a2)) / 80U;
	st->amp = (uint16_t)((amp > 65535U) ? 65535U : amp);

	/* Шум: дисперсія блока мінус потужність тону. Амплітуда DFT від білого шуму на 80 відліках --
	 * ~2 * sigma / sqrt(80) = 0,22 * sigma; тон рахуємо, якщо він >= 4x цього (0,9 * sigma):
	 * тоді шумовий розкид фази між половинами ~13 град і поріг 30 град майже не спрацьовує
	 * сам. Для порівняння завжди є контроль -- стрибки всередині блока. */
	float sum = 0.0f, sq = 0.0f;
	for (int n = 0; n < 160; n++)
	{
		sum += (float)x[n];
		sq += (float)x[n] * (float)x[n];
	}
	float var = sq / 160.0f - (sum / 160.0f) * (sum / 160.0f);
	float resVar = var - 0.5f * (float)amp * (float)amp;
	if (resVar < 0.0f)
	{
		resVar = 0.0f;
	}
	float minAmp = 0.9f * (float)apIsqrt64((uint64_t)resVar);
	if (minAmp < (float)AP_STREAM_MIN_AMP)
	{
		minAmp = (float)AP_STREAM_MIN_AMP;
	}

	/* тон є і рівний в обох половинах (не початок/кінець передачі) */
	bool tone = ((float)amp >= minAmp) && (m1 < 4.0f * m2) && (m2 < 4.0f * m1);
	if (tone)
	{
		float dIn = angleBetween(r1, i1, r2, i2);
		st->blocks++;
		if (dIn > (float)AP_STREAM_JUMP_DEG)
		{
			st->jumpsIn++;
		}
		if (clampDeg(dIn) > st->maxIn)
		{
			st->maxIn = clampDeg(dIn);
		}
		/* розстройка: знаковий зсув фази за 10 мс */
		{
			float re = r2 * r1 + i2 * i1, im = i2 * r1 - r2 * i1;
			st->sumDphi += apAtan2Deg(im, re);
			st->nDphi++;
		}
		if (st->havePrev)
		{
			float dB = angleBetween(st->prevRe, st->prevIm, r1, i1);
			if (dB > (float)AP_STREAM_JUMP_DEG)
			{
				st->jumpsB++;
			}
			if (clampDeg(dB) > st->maxB)
			{
				st->maxB = clampDeg(dB);
			}
		}
	}
	st->prevRe = r2;
	st->prevIm = i2;
	st->havePrev = tone ? 1 : 0;
}

float apStreamOffsetHz(const apStream_t *st)
{
	if (st->nDphi == 0)
	{
		return 0.0f;
	}
	/* град за 10 мс -> Гц: f = (deg / 360) / 0,01 с */
	return (st->sumDphi / (float)st->nDphi) / 3.6f;
}

/* ---- R5: формат відліку I2S RX ------------------------------------------------ */

void apFmtInit(apFmt_t *f)
{
	f->n = f->b10 = f->nonUni = f->nearLim = 0;
	f->peak = 0;
}

void apFmtExtract(apFmt_t *f, const uint16_t *u, int stride, int n, bool is16, int16_t *out)
{
	for (int i = 0; i < n; i++)
	{
		uint16_t w = u[i * stride];
		int16_t s = apSample10(w);
		if (f != NULL)
		{
			uint16_t hi = (uint16_t)(w >> 10);   /* біти 10..15 */
			uint16_t a = (uint16_t)((s < 0) ? -s : s);
			f->n++;
			if (hi & 1U)
			{
				f->b10++;
			}
			if ((hi != 0U) && (hi != 0x3FU))
			{
				f->nonUni++;
			}
			if (a >= AP_FMT_NEAR)
			{
				f->nearLim++;
			}
			if (a > f->peak)
			{
				f->peak = a;
			}
		}
		out[i] = is16 ? apSample16(w) : s;
	}
}

/* ---- R6: автовизначення формату (опис -- у .h) ------------------------------------ */

void apFmtDetInit(apFmtDet_t *d, bool is16)
{
	d->is16 = is16 ? 1U : 0U;
	d->streak = 0;
	d->hold = 0;
	d->switches = 0;
	d->ev10 = 0;
	d->ev16 = 0;
}

uint8_t apFmtEvidence(const uint16_t *u, int stride, int n)
{
	uint32_t nonUni = 0, small = 0, diff = 0, near = 0;

	for (int i = 0; i < n; i++)
	{
		uint16_t w = u[i * stride];
		uint16_t hi = (uint16_t)(w >> 10);
		int16_t s = apSample10(w);
		uint16_t a = (uint16_t)((s < 0) ? -s : s);

		if ((hi != 0U) && (hi != 0x3FU))
		{
			nonUni++;
		}
		if (a < AP_DET_SMALL)
		{
			small++;
			if (((w >> 10) ^ (w >> 9)) & 1U)
			{
				diff++;
			}
		}
		else if (a >= AP_DET_NEAR)
		{
			near++;
		}
	}

	if (nonUni >= AP_DET_NONUNI)
	{
		return AP_EV_16;
	}
	if (small >= AP_DET_MIN_SMALL)
	{
		if (((diff * 4U) >= small) && ((near * 10U) <= (uint32_t)n))
		{
			return AP_EV_10;
		}
		if ((diff * 32U) <= small)
		{
			return AP_EV_16;
		}
	}
	return AP_EV_NONE;
}

bool apFmtDetBlock(apFmtDet_t *d, const uint16_t *u, int stride, int n, bool inFrame)
{
	uint8_t ev = apFmtEvidence(u, stride, n);

	if (ev == AP_EV_10)
	{
		d->ev10++;
	}
	else if (ev == AP_EV_16)
	{
		d->ev16++;
	}

	if (ev == AP_EV_NONE)
	{
		/* блок не голосує: серія не переривається */
	}
	else if ((ev == AP_EV_16) == (d->is16 != 0U))
	{
		d->streak = 0;   /* доказ поточного формату */
		d->hold = 0;
	}
	else if (d->streak < AP_DET_STREAK)
	{
		d->streak++;
	}

	if (d->streak >= AP_DET_STREAK)
	{
		if (inFrame && (d->hold < AP_DET_HOLD_MAX))
		{
			d->hold++;   /* посеред кадру не міняємо -- чекаємо його кінця */
			return false;
		}
		d->is16 = d->is16 ? 0U : 1U;
		d->switches++;
		d->streak = 0;
		d->hold = 0;
		return true;
	}
	return false;
}

#endif /* ENABLE_APRS_RX_PROBE */
