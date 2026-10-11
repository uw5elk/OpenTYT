/*
 * aprs_afsk.c -- демодулятор Bell 202 і приймач кадрів AX.25 (R3). Опис ланцюжка -- у aprs_afsk.h.
 * Чистий C без заліза й без libm: той самий файл збирає хост-тест tests/test_aprs_afsk.c.
 * Таблиці кореляції -- cos/sin(2*pi*f*k/8000), згенеровано python-скриптом (8 знаків); їх
 * правильність перевіряє сам хост-тест декодуванням (а сигнал генератора -- multimon-ng).
 */
#include "functions/aprs_afsk.h"

#if defined(ENABLE_APRS_RX)

#include <string.h>

/* ---- параметри (підібрано хост-тестом; див. docs/aprs-rx-feasibility.md, розділ 7) ---------- */
#ifndef AFSK_ENV_K
#define AFSK_ENV_K          0.02f       /* швидкість середнього рівня тону (~50 відліків = 7,5 біта) */
#endif
#ifndef AFSK_PLL_LOCKED
#define AFSK_PLL_LOCKED     0.65f       /* підтягування фази тактів на переході, коли йде кадр */
#endif
#ifndef AFSK_PLL_SEARCH
#define AFSK_PLL_SEARCH     0.45f       /* ... і коли кадру немає (швидше захоплення) */
#endif
#ifndef AFSK_NOTCH_R
#define AFSK_NOTCH_R        0.985f      /* радіус полюсів режекції: смуга -3 дБ ~ (1-r)*fs/pi ~ 38 Гц */
#endif

/* 2^32 * 1200 / 8000: крок фазового акумулятора тактів на один відлік (afskSetSampleRate() --
 * поправка на виміряну частоту дискретизації). */
#define AFSK_PLL_STEP       644245094u

/* Смуговий 900-2500 Гц, Баттерворт 4-го порядку (scipy.signal.butter(2, [900, 2500], 'bandpass',
 * fs=8000, output='sos')): { b0, b1, b2, a1, a2 } для кожної секції. */
static const float s_bp[2][5] =
{
	{ 0.20657208f,  0.41314417f, 0.20657208f,  0.37236352f, 0.38656884f },
	{ 1.00000000f, -2.00000000f, 1.00000000f, -1.05610092f, 0.50654810f }
};

/* FIR Гільберта, 15 відводів (вікно Геммінга, h[n] = 2/(pi n) для непарних n): уявна частина
 * аналітичного сигналу; дійсна -- той самий відлік, затриманий на 7. АЧХ 900-3000 Гц: 0,98-1,01.
 * R4: без нього короткий кореляційний фільтр дійсного сигналу має «дзеркало» на 2f, і модуль
 * пульсує на +-15 % -- хост-тест: перекіс -12 дБ навіть без шуму декодувався лише на 17 %. */
static const float s_hb[AFSK_HILB_LEN] =
{
	-0.00727565f, 0.0f, -0.03223775f, 0.0f, -0.13631295f, 0.0f, -0.60761899f, 0.0f,
	 0.60761899f, 0.0f,  0.13631295f, 0.0f,  0.03223775f, 0.0f,  0.00727565f
};

/* Кореляційні фільтри: cos/sin(2*pi*f*k/8000), k = 0..AFSK_CORR_LEN-1 (M -- 1200, S -- 2200). */
#if AFSK_CORR_LEN == 8
static const float s_cM[AFSK_CORR_LEN] =
{
	 1.00000000f,  0.58778525f, -0.30901699f, -0.95105652f, -0.80901699f, -0.00000000f,  0.80901699f,
	 0.95105652f
};
static const float s_sM[AFSK_CORR_LEN] =
{
	 0.00000000f,  0.80901699f,  0.95105652f,  0.30901699f, -0.58778525f, -1.00000000f, -0.58778525f,
	 0.30901699f
};
static const float s_cS[AFSK_CORR_LEN] =
{
	 1.00000000f, -0.15643447f, -0.95105652f,  0.45399050f,  0.80901699f, -0.70710678f, -0.58778525f,
	 0.89100652f
};
static const float s_sS[AFSK_CORR_LEN] =
{
	 0.00000000f,  0.98768834f, -0.30901699f, -0.89100652f,  0.58778525f,  0.70710678f, -0.80901699f,
	-0.45399050f
};
#else
#error "AFSK_CORR_LEN: tables only for 8"  /* таблиці є лише для цих довжин */
#endif


/* ---- допоміжні ------------------------------------------------------------- */

static inline float fabsF(float v)
{
	return (v < 0.0f) ? -v : v;
}

/* |I + jQ| ~ max + 3/8 min (похибка до ~7 %, однакова для обох тонів -- на рішення не впливає). */
static inline float magApprox(float i, float q)
{
	float a = fabsF(i), b = fabsF(q);
	return (a > b) ? (a + 0.375f * b) : (b + 0.375f * a);
}

uint16_t ax25Crc(const uint8_t *p, int n)
{
	uint16_t crc = 0xFFFF;
	while (n-- > 0)
	{
		crc ^= *p++;
		for (int i = 0; i < 8; i++)
		{
			crc = (crc & 1) ? ((crc >> 1) ^ 0x8408) : (crc >> 1);
		}
	}
	return (uint16_t)~crc;
}

/* ---- HDLC ------------------------------------------------------------------ */

static void frameEnd(afskDemod_t *d)
{
	if ((d->len < AFSK_FRAME_MIN) || (d->nbits != 7))
	{
		return;   /* закоротко або не кратно 8 бітам (7 бітів прапорця вже в bitbuf) */
	}
	uint16_t crc = ax25Crc(d->frame, d->len - 2);
	bool ok = (d->frame[d->len - 2] == (crc & 0xFF)) && (d->frame[d->len - 1] == (crc >> 8));
	if (ok)
	{
		d->nOk++;
	}
	else
	{
		d->nBad++;
	}
	if (d->cb != NULL)
	{
		/* правильний -- без FCS; помилковий -- як є, з FCS (для діагностики) */
		d->cb(d->frame, (uint16_t)(ok ? (d->len - 2) : d->len), ok, d->ctx);
	}
}

static void hdlcBit(afskDemod_t *d, uint8_t bit)
{
	d->sh = (uint8_t)((d->sh << 1) | bit);
	if (d->sinceFlag < 255)
	{
		d->sinceFlag++;
	}

	if (d->sh == 0x7E)
	{
		if (d->inFrame)
		{
			frameEnd(d);
		}
		if (d->sinceFlag == 8)
		{
			if (d->flagRun < 255)
			{
				d->flagRun++;
			}
			if (d->flagRun == AFSK_FLAG_SEQ)
			{
				d->nFlagSeq++;   /* одна серія -- один раз; 1-3 прапорці в кінці кадру не рахуються */
			}
		}
		else
		{
			d->flagRun = 1;
		}
		d->sinceFlag = 0;
		d->inFrame = 1;
		d->len = 0;
		d->nbits = 0;
		d->bitbuf = 0x80;
		return;
	}
	if ((d->sh & 0x7F) == 0x7F)   /* 7 одиниць -- обрив / тиша */
	{
		d->inFrame = 0;
		return;
	}
	if (d->inFrame == 0)
	{
		return;
	}
	if ((d->sh & 0x3F) == 0x3E)   /* 0 після п'яти одиниць -- вставлений, викидаємо */
	{
		return;
	}
	if (bit)
	{
		d->bitbuf |= 0x100;
	}
	if (d->bitbuf & 1)
	{
		if (d->len >= AFSK_FRAME_MAX)
		{
			d->inFrame = 0;
			return;
		}
		d->frame[d->len++] = (uint8_t)(d->bitbuf >> 1);
		d->bitbuf = 0x80;
		d->nbits = 0;
		return;
	}
	d->bitbuf >>= 1;
	d->nbits++;
}

/* ---- демодулятор ------------------------------------------------------------- */

void afskResync(afskDemod_t *d)
{
	d->pll = 0;
	d->lastData = 0;
	d->lastSample = 0;
	d->sh = 0;
	d->inFrame = 0;
	d->nbits = 0;
	d->flagRun = 0;
	d->sinceFlag = 255;
	d->bitbuf = 0x80;
	d->len = 0;
}

void afskInit(afskDemod_t *d, afskFrameCb_t cb, void *ctx)
{
	memset(d, 0, sizeof(*d));
	d->pllStep = AFSK_PLL_STEP;
	d->cb = cb;
	d->ctx = ctx;
	afskResync(d);
}

void afskSetNotchHz(afskDemod_t *d, float hz)
{
	if (hz <= 0.0f)
	{
		d->notchOn = 0;
	}
	else
	{
		d->nc = apCos2(hz);
		d->notchOn = 1;
	}
	d->nz[0] = d->nz[1] = 0.0f;
}

void afskSetSampleRate(afskDemod_t *d, uint32_t fsHz)
{
	if ((fsHz < 7000) || (fsHz > 9000))
	{
		fsHz = AFSK_FS;
	}
	d->pllStep = (uint32_t)((((uint64_t)1200) << 32) / fsHz);
}

void afskProcess(afskDemod_t *d, const int16_t *x, int n)
{
	for (int i = 0; i < n; i++)
	{
		float v = (float)x[i];

		/* 1. смуга 900-2500 Гц (DF2T) */
		for (int s = 0; s < 2; s++)
		{
			const float *c = s_bp[s];
			float y = c[0] * v + d->bp[s][0];
			d->bp[s][0] = c[1] * v - c[3] * y + d->bp[s][1];
			d->bp[s][1] = c[2] * v - c[4] * y;
			v = y;
		}

		/* 2. режекція: (1 - c z^-1 + z^-2) / (1 - r c z^-1 + r^2 z^-2) */
		if (d->notchOn)
		{
			float y = v + d->nz[0];
			d->nz[0] = -d->nc * v + (AFSK_NOTCH_R * d->nc) * y + d->nz[1];
			d->nz[1] = v - (AFSK_NOTCH_R * AFSK_NOTCH_R) * y;
			v = y;
		}

		/* 3. аналітичний сигнал (Гільберт) і кореляція з 1200/2200 на вікні 8 відліків (1 мс) */
		d->hb[d->hbpos] = v;
		float hre = 0.0f, him = 0.0f;
		{
			int q = d->hbpos;
			for (int k = 0; k < AFSK_HILB_LEN; k++)
			{
				him += s_hb[k] * d->hb[q];
				if (k == (AFSK_HILB_LEN / 2))
				{
					hre = d->hb[q];
				}
				q = (q == 0) ? (AFSK_HILB_LEN - 1) : (q - 1);
			}
		}
		d->hbpos = (uint8_t)((d->hbpos + 1 >= AFSK_HILB_LEN) ? 0 : (d->hbpos + 1));

		d->hist[d->hpos] = hre;
		d->histQ[d->hpos] = him;
		float im = 0.0f, qm = 0.0f, is = 0.0f, qs = 0.0f;
		int p = d->hpos;
		for (int k = 0; k < AFSK_CORR_LEN; k++)
		{
			/* (re + j im) * (cos + j sin) */
			float a = d->hist[p], b = d->histQ[p];
			im += a * s_cM[k] - b * s_sM[k];
			qm += a * s_sM[k] + b * s_cM[k];
			is += a * s_cS[k] - b * s_sS[k];
			qs += a * s_sS[k] + b * s_cS[k];
			p = (p == 0) ? (AFSK_CORR_LEN - 1) : (p - 1);
		}
		d->hpos = (uint8_t)((d->hpos + 1 >= AFSK_CORR_LEN) ? 0 : (d->hpos + 1));

		/* 4. рішення з поправкою на перекіс: порівнюємо M/sqrt(eM) і S/sqrt(eS), де eM, eS --
		 * середні рівні тонів, коли кожен «виграє». Без кореня: M^2*eS проти S^2*eM. Повне
		 * нормування (M/eM проти S/eS) на слабшому тоні підсилює і його шум; хост-тест
		 * (R3, R4): «половинне» -- найкраще з перевірених, з Гільбертом тримає перекіс +-12 дБ. */
		float pm = im * im + qm * qm;
		float ps = is * is + qs * qs;
		float m = pm * (d->envS + 1e-3f);
		float s = ps * (d->envM + 1e-3f);
		if (m > s)
		{
			d->envM += AFSK_ENV_K * (magApprox(im, qm) - d->envM);
		}
		else
		{
			d->envS += AFSK_ENV_K * (magApprox(is, qs) - d->envS);
		}
		uint8_t data = (m > s) ? 1 : 0;

		/* 5. такти: відлік біта -- на переповненні акумулятора (середина біта) */
		int32_t prev = d->pll;
		d->pll = (int32_t)((uint32_t)d->pll + d->pllStep);
		if ((prev > 0) && (d->pll < 0))
		{
			/* 6. NRZI: немає зміни тону -- 1, є -- 0 */
			hdlcBit(d, (uint8_t)((data == d->lastSample) ? 1 : 0));
			d->lastSample = data;
		}
		if (data != d->lastData)
		{
			/* Гістограма фази тактів на переході (0 -- ідеал, +-2^31 -- пів біта): лише всередині
			 * кадру після >= 2 прапорців поспіль, тобто на справжньому пакеті, а не на шумі. */
			if (d->inFrame && (d->flagRun >= 2))
			{
				uint32_t bin = ((uint32_t)d->pll + 0x80000000u) >> (32 - 3);
				if (d->pllHist[bin] < 0xFFFF)
				{
					d->pllHist[bin]++;
				}
			}
			d->pll = (int32_t)((float)d->pll * (d->inFrame ? AFSK_PLL_LOCKED : AFSK_PLL_SEARCH));
		}
		d->lastData = data;
	}
}

/* ---- AX.25: підсумок для екрана ----------------------------------------------- */

static int addrToText(const uint8_t *a, char *out, int size)
{
	int n = 0;
	for (int i = 0; i < 6; i++)
	{
		char c = (char)(a[i] >> 1);
		if (c == ' ')
		{
			break;
		}
		if ((c < '0') || (c > 'Z') || ((c > '9') && (c < 'A')))
		{
			return -1;
		}
		if (n < size - 1)
		{
			out[n++] = c;
		}
	}
	int ssid = (a[6] >> 1) & 0x0F;
	if (ssid != 0)
	{
		if (n < size - 1) { out[n++] = '-'; }
		if ((ssid >= 10) && (n < size - 1)) { out[n++] = '1'; }
		if (n < size - 1) { out[n++] = (char)('0' + (ssid % 10)); }
	}
	out[n] = 0;
	return n;
}

bool ax25Summary(const uint8_t *f, int len, char *srcDst, int sdSize, char *info, int infoSize)
{
	char dst[10], src[10];
	int na;

	srcDst[0] = 0;
	info[0] = 0;
	if (len < 15)
	{
		return false;
	}
	/* Адреси по 7 байтів; ознака останньої -- біт 0 SSID-байта. */
	for (na = 0; (na * 7 + 6) < len; na++)
	{
		if (f[na * 7 + 6] & 1)
		{
			na++;
			break;
		}
		if (na >= 9)
		{
			return false;
		}
	}
	if ((na < 2) || (na * 7 >= len))
	{
		return false;
	}
	if ((addrToText(&f[0], dst, sizeof(dst)) <= 0) || (addrToText(&f[7], src, sizeof(src)) <= 0))
	{
		return false;
	}

	int si = 0;
	for (const char *p = src; *p && (si < sdSize - 1); p++) { srcDst[si++] = *p; }
	if (si < sdSize - 1) { srcDst[si++] = '>'; }
	for (const char *p = dst; *p && (si < sdSize - 1); p++) { srcDst[si++] = *p; }
	srcDst[si] = 0;

	int pos = na * 7;
	uint8_t ctrl = f[pos++];
	if ((ctrl & 0xEF) == 0x03)   /* UI: за контролем -- PID */
	{
		pos++;
	}
	int ii = 0;
	while ((pos < len) && (ii < infoSize - 1))
	{
		uint8_t c = f[pos++];
		info[ii++] = ((c >= 0x20) && (c < 0x7F)) ? (char)c : '.';
	}
	info[ii] = 0;
	return true;
}

static int looseOne(const uint8_t *a, char *out, int size)
{
	int n = 0;
	int last = 5;
	while ((last >= 0) && ((a[last] >> 1) == ' '))
	{
		last--;
	}
	for (int i = 0; (i <= last) && (n < size - 1); i++)
	{
		char c = (char)(a[i] >> 1);
		out[n++] = ((c >= 0x21) && (c < 0x7F)) ? c : '.';
	}
	int ssid = (a[6] >> 1) & 0x0F;
	if (ssid != 0)
	{
		if (n < size - 1) { out[n++] = '-'; }
		if ((ssid >= 10) && (n < size - 1)) { out[n++] = '1'; }
		if (n < size - 1) { out[n++] = (char)('0' + (ssid % 10)); }
	}
	out[n] = 0;
	return n;
}

void ax25LooseAddr(const uint8_t *f, int len, char *out, int size)
{
	char dst[12], src[12];
	out[0] = 0;
	if ((len < 14) || (size < 4))
	{
		return;
	}
	looseOne(&f[0], dst, sizeof(dst));
	looseOne(&f[7], src, sizeof(src));
	int n = 0;
	for (const char *p = src; *p && (n < size - 1); p++) { out[n++] = *p; }
	if (n < size - 1) { out[n++] = '>'; }
	for (const char *p = dst; *p && (n < size - 1); p++) { out[n++] = *p; }
	out[n] = 0;
}

#endif /* ENABLE_APRS_RX */
