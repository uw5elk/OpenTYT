/*
 * test_aprs_afsk.c -- R3: демодулятор Bell 202 + AX.25 (functions/aprs_afsk.c) на синтетичному
 * AFSK 1200 бод при 8000 Гц, з реальним кадром APRS і відомим FCS.
 *
 * Генератор тут же: кадр -> FCS -> бітстафінг -> NRZI -> AFSK з неперервною фазою; далі білий
 * гауссів шум (SNR -- відношення RMS сигналу до RMS шуму в усій смузі 0-4000 Гц), перекіс тонів,
 * розстройка частоти, синусоїда-завада, DC. Шум детермінований (власний LCG + Бокс-Мюллер).
 *
 * Перевіряє: CRC-16/X.25 (контрольне значення й еталонний кадр), підсумок AX.25, декодування
 * за різних умов, поріг SNR, відсутність хибних кадрів на шумі й «голосі», таблиці коефіцієнтів.
 * З -DAFSK_TUNE друкує таблицю «частка декодованих кадрів від SNR» (для підбору параметрів).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "functions/aprs_afsk.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

#define PI 3.14159265358979323846
#define FS 8000.0

/* ---- детермінований шум ---------------------------------------------------- */
static uint64_t s_rng = 1;
static double urand(void)
{
	s_rng = s_rng * 6364136223846793005ULL + 1442695040888963407ULL;
	return ((double)(s_rng >> 11) + 0.5) / 9007199254740992.0;   /* (0, 1) */
}
static double grand(void)
{
	return sqrt(-2.0 * log(urand())) * cos(2.0 * PI * urand());
}

/* ---- кадр AX.25 ------------------------------------------------------------ */
static int putAddr(uint8_t *p, const char *call, int ssid, int last)
{
	int i = 0;
	for (; i < 6 && call[i]; i++) { p[i] = (uint8_t)(call[i] << 1); }
	for (; i < 6; i++) { p[i] = (uint8_t)(' ' << 1); }
	p[6] = (uint8_t)(0x60 | (ssid << 1) | (last ? 1 : 0));
	return 7;
}

/* UR5EAA-9 > APDR16 через WIDE1-1, UI, PID F0 -- типовий пакет APRSdroid. */
static const char *INFO = "=4926.40N/03201.60E$OpenTYT R3 test 73";
static int buildFrame(uint8_t *f)
{
	int n = 0;
	n += putAddr(&f[n], "APDR16", 0, 0);
	n += putAddr(&f[n], "UR5EAA", 9, 0);
	n += putAddr(&f[n], "WIDE1", 1, 1);
	f[n++] = 0x03;
	f[n++] = 0xF0;
	memcpy(&f[n], INFO, strlen(INFO));
	n += (int)strlen(INFO);
	uint16_t crc = ax25Crc(f, n);
	f[n++] = (uint8_t)(crc & 0xFF);
	f[n++] = (uint8_t)(crc >> 8);
	return n;   /* з FCS */
}

/* Біти в ефірі (до NRZI): прапорці + дані з бітстафінгом (LSB першим) + прапорці. */
static int buildBits(const uint8_t *f, int n, int preFlags, int postFlags, uint8_t *bits)
{
	int nb = 0, ones = 0;
	for (int k = 0; k < preFlags; k++) { for (int b = 0; b < 8; b++) { bits[nb++] = (0x7E >> b) & 1; } }
	for (int i = 0; i < n; i++)
	{
		for (int b = 0; b < 8; b++)
		{
			uint8_t bit = (f[i] >> b) & 1;
			bits[nb++] = bit;
			if (bit) { if (++ones == 5) { bits[nb++] = 0; ones = 0; } } else { ones = 0; }
		}
	}
	for (int k = 0; k < postFlags; k++) { for (int b = 0; b < 8; b++) { bits[nb++] = (0x7E >> b) & 1; } }
	return nb;
}

typedef struct
{
	double snrDb;      /* RMS сигналу / RMS шуму, 0-4000 Гц; > 90 -- без шуму */
	double amp;        /* амплітуда AFSK (int16) */
	double twistDb;    /* рівень 2200 відносно 1200 */
	double fOff;       /* розстройка обох тонів, Гц */
	double baudErr;    /* відносна похибка швидкості, напр. 0.01 */
	double intF;       /* частота завади, Гц (0 -- немає) */
	double intRel;     /* амплітуда завади відносно amp */
	double dc;
	int frames;        /* кадрів поспіль у записі */
	double lead;       /* фон перед першим пакетом, с */
} sig_t;

#define MAX_SAMPLES 400000
static int16_t s_buf[MAX_SAMPLES];

/* Генерує запис: тиша-шум 0,3 с, далі frames пакетів (по 30 прапорців преамбули), між ними 0,2 с. */
static int synth(const sig_t *p, const uint8_t *frame, int flen)
{
	static uint8_t bits[4000];
	int nb = buildBits(frame, flen, 30, 3, bits);
	double spb = FS / (1200.0 * (1.0 + p->baudErr));
	double g2200 = pow(10.0, p->twistDb / 20.0);
	double ph = urand() * 2 * PI, phI = urand() * 2 * PI;
	int n = 0;

	for (int fr = 0; fr < p->frames; fr++)
	{
		int gap = (int)(FS * (fr == 0 ? p->lead : 0.2)) + (int)(urand() * 7);
		for (int i = 0; i < gap && n < MAX_SAMPLES; i++, n++) { s_buf[n] = 0; }
		uint8_t level = (urand() > 0.5);   /* стан NRZI на початку */
		double tEnd = 0.0;                  /* кінець поточного біта, у відліках від початку пакета */
		long ns = 0;
		for (int b = 0; b < nb; b++)
		{
			if (bits[b] == 0) { level ^= 1; }
			double f = (level ? 1200.0 : 2200.0) + p->fOff;
			double a = level ? 1.0 : g2200;
			tEnd += spb;
			while ((double)ns < tEnd)
			{
				ph += 2 * PI * f / FS;
				if (n < MAX_SAMPLES) { s_buf[n++] = (int16_t)lround(p->amp * a * sin(ph)); }
				ns++;
			}
		}
	}
	for (int i = 0; i < (int)(FS * 0.3) && n < MAX_SAMPLES; i++, n++) { s_buf[n] = 0; }

	/* SNR -- відносно справжнього RMS сигналу (лише відліки пакетів; з перекосом він інший) */
	double sq = 0.0;
	long ns2 = 0;
	for (int i = 0; i < n; i++) { if (s_buf[i] != 0) { sq += (double)s_buf[i] * s_buf[i]; ns2++; } }
	double sigRms = (ns2 > 0) ? sqrt(sq / ns2) : 0.0;
	double noiseRms = (p->snrDb > 90) ? 0.0 : sigRms / pow(10.0, p->snrDb / 20.0);

	/* шум, завада, DC -- поверх усього запису */
	for (int i = 0; i < n; i++)
	{
		double v = s_buf[i] + p->dc;
		if (noiseRms > 0) { v += noiseRms * grand(); }
		if (p->intF > 0) { v += p->amp * p->intRel * sin(2 * PI * p->intF * i / FS + phI); }
		if (v > 32767) { v = 32767; }
		if (v < -32768) { v = -32768; }
		s_buf[i] = (int16_t)lround(v);
	}
	return n;
}

/* ---- приймач ---------------------------------------------------------------- */
typedef struct { int good; int match; int bad; int badLen; uint8_t badHead[16]; char sd[24]; char info[48]; } rx_t;

static uint8_t s_ref[AFSK_FRAME_MAX];
static int s_refLen;

static void onFrame(const uint8_t *f, uint16_t len, bool ok, void *ctx)
{
	rx_t *r = (rx_t *)ctx;
	if (!ok)
	{
		r->bad++;
		r->badLen = len;
		memcpy(r->badHead, f, (len < 16) ? len : 16);
		return;
	}
	r->good++;
	if ((len == s_refLen - 2) && (memcmp(f, s_ref, len) == 0)) { r->match++; }
	ax25Summary(f, len, r->sd, sizeof(r->sd), r->info, sizeof(r->info));
}

static afskDemod_t s_d;

/* Режекція: NOTCH_OFF -- вимкнена; NOTCH_AUTO -- як у прошивці: частоту дає розгортка фону
 * (apBg), застосовується лише коли за останні ~2 с не було серій прапорців; > 0 -- задано, Гц. */
#define NOTCH_OFF   (-1.0)
#define NOTCH_AUTO  (-2.0)
static apBg_t s_bg;
static float s_lastNotch;
static uint32_t s_fsHz = 0;   /* 0 -- не задавати (8000) */

/* Блоками по 160, як у прошивці. */
static rx_t runRx(int n, double notch)
{
	rx_t r;
	memset(&r, 0, sizeof(r));
	afskInit(&s_d, onFrame, &r);
	if (s_fsHz) { afskSetSampleRate(&s_d, s_fsHz); }
	afskSetNotchHz(&s_d, (notch > 0) ? (float)notch : 0.0f);
	apBgInit(&s_bg);
	s_lastNotch = 0;
	int quiet = 1000;   /* серій прапорців ще не було -- «тихо» з самого початку */
	uint16_t lastFlags = 0;
	for (int i = 0; i + 160 <= n; i += 160)
	{
		afskProcess(&s_d, &s_buf[i], 160);
		if (notch == NOTCH_AUTO)
		{
			if (s_d.nFlagSeq != lastFlags) { lastFlags = s_d.nFlagSeq; quiet = 0; } else if (quiet < 1000) { quiet++; }
			apBgResult_t br;
			if (apBgBlock(&s_bg, &s_buf[i], &br) && (quiet >= 100) && (s_d.inFrame == 0))
			{
				float hz = apBgNotchHz(&br);
				if (hz != s_lastNotch) { afskSetNotchHz(&s_d, hz); s_lastNotch = hz; }
			}
		}
	}
	return r;
}

static sig_t base(void)
{
	sig_t p = { 99, 600, 0, 0, 0, 0, 0, 0, 1, 0.3 };
	return p;
}

/* Частка декодованих кадрів (рівно еталонних) з trials записів по frames кадрів. */
static double rate(sig_t p, int trials, double notch, int *falseOk)
{
	int ok = 0, tot = 0, bad = 0;
	for (int t = 0; t < trials; t++)
	{
		int n = synth(&p, s_ref, s_refLen);
		rx_t r = runRx(n, notch);
		ok += r.match;
		bad += r.good - r.match;
		tot += p.frames;
	}
	if (falseOk) { *falseOk = bad; }
	return (double)ok / tot;
}

static double findThreshold(sig_t p, int trials, double notch)
{
	/* найменший SNR (крок 0,5 дБ, 0..30), з якого частка >= 90 % і далі не падає нижче */
	double thr = 99;
	for (double snr = 30.0; snr >= -2.0; snr -= 0.5)
	{
		p.snrDb = snr;
		if (rate(p, trials, notch, NULL) >= 0.9) { thr = snr; } else { break; }
	}
	return thr;
}

#if defined(AFSK_TUNE)
int main(void)
{
	s_refLen = buildFrame(s_ref);
	sig_t p = base();
	p.frames = 5;
	printf("L=%d\n", AFSK_CORR_LEN);
	for (double snr = 2; snr <= 16; snr += 1)
	{
		p.snrDb = snr;
		printf("SNR %5.1f: %.2f  (twist+6 %.2f, twist-6 %.2f)\n", snr, rate(p, 8, NOTCH_OFF, NULL),
				(p.twistDb = 6, rate(p, 8, NOTCH_OFF, NULL)), (p.twistDb = -6, rate(p, 8, NOTCH_OFF, NULL)));
		p.twistDb = 0;
	}
	return 0;
}
#else
int main(void)
{
	printf("test_aprs_afsk:\n");

	/* CRC-16/X.25: контрольне значення стандарту. */
	CHECK(ax25Crc((const uint8_t *)"123456789", 9) == 0x906E, "CRC-16/X.25(\"123456789\") = 0x906E");

	s_refLen = buildFrame(s_ref);
	/* Еталонний FCS цього кадру (пораховано незалежно: python3 tools/aprs_afsk_ref.py). */
	CHECK(s_refLen == 63 && s_ref[61] == 0x0F && s_ref[62] == 0xF6, "еталонний кадр: 63 байти, FCS 0xF60F (LSB першим), як у tools/aprs_afsk_ref.py");
	{
		char sd[24], info[48];
		bool ok = ax25Summary(s_ref, s_refLen - 2, sd, sizeof(sd), info, sizeof(info));
		CHECK(ok && strcmp(sd, "UR5EAA-9>APDR16") == 0 && strncmp(info, INFO, 20) == 0,
				"підсумок AX.25: «%s» / «%.20s»", sd, info);
		char sd2[8], info2[8];
		ax25Summary(s_ref, s_refLen - 2, sd2, sizeof(sd2), info2, sizeof(info2));
		CHECK(strlen(sd2) == 7 && strlen(info2) == 7, "підсумок обрізається за розміром буфера");
		CHECK(!ax25Summary((const uint8_t *)"\x01\x02\x03", 3, sd, sizeof(sd), info, sizeof(info)), "сміття -- не AX.25");
	}

	/* Таблиці проти math.h. */
	{
		int ok = 1;
		for (int i = 0; i < AP_SWEEP_BINS; i++)
		{
			if (fabs(apSweepCoeff[i] - 2 * cos(2 * PI * (AP_SWEEP_F0 + AP_SWEEP_STEP * i) / FS)) > 1e-6) { ok = 0; }
		}
		CHECK(ok, "таблиця розгортки 100..3900 Гц / 50 Гц збігається з cos()");
		double worst = 0;
		for (double f = 100; f <= 3900; f += 7.3) { double e = fabs(apCos2((float)f) - 2 * cos(2 * PI * f / FS)); if (e > worst) { worst = e; } }
		CHECK(worst < 0.001, "apCos2 (інтерполяція) -- похибка %.5f < 0,001", worst);
	}

	sig_t p;
	rx_t r;
	int n;

	/* Чистий сигнал: усі 3 кадри, рівно еталон, підсумок. */
	s_rng = 11;
	p = base(); p.frames = 3;
	n = synth(&p, s_ref, s_refLen);
	r = runRx(n, NOTCH_OFF);
	CHECK(r.match == 3 && r.good == 3, "без шуму: 3 з 3 кадрів, FCS правильний (%d/%d)", r.match, r.good);
	CHECK(s_d.nFlagSeq == 3, "серій прапорців (>= %d поспіль): %u (очікується 3 -- по одній на преамбулу)", AFSK_FLAG_SEQ, s_d.nFlagSeq);
	CHECK(strcmp(r.sd, "UR5EAA-9>APDR16") == 0, "SRC>DST: %s", r.sd);

	/* Рівні: дуже тихий і дуже гучний сигнал. */
	p = base(); p.frames = 2; p.amp = 40; p.snrDb = 99;
	n = synth(&p, s_ref, s_refLen); r = runRx(n, NOTCH_OFF);
	CHECK(r.match == 2, "амплітуда 40 (-58 дБFS): %d з 2", r.match);
	p.amp = 20000;
	n = synth(&p, s_ref, s_refLen); r = runRx(n, NOTCH_OFF);
	CHECK(r.match == 2, "амплітуда 20000: %d з 2", r.match);

	/* Поріг SNR (білий шум 0-4000 Гц), 20 записів на крок. */
	s_rng = 21;
	p = base(); p.frames = 1;
	double thr0 = findThreshold(p, 20, NOTCH_OFF);
	printf("    поріг SNR (>= 90 %% кадрів): %.1f дБ\n", thr0);
	CHECK(thr0 <= 12.0, "поріг SNR без перекосу <= 12 дБ (є %.1f)", thr0);
	p.snrDb = thr0 + 3;
	CHECK(rate(p, 20, NOTCH_OFF, NULL) >= 0.95, "SNR поріг+3 дБ: >= 95 %% кадрів");
	p.snrDb = 0;
	CHECK(rate(p, 20, NOTCH_OFF, NULL) <= 0.1, "SNR 0 дБ: майже нічого (не «чудо»: перевірка генератора шуму)");

	/* Перекіс тонів +-6 дБ, розстройка +-50 Гц, похибка швидкості 1 %, DC. */
	p = base(); p.frames = 1; p.snrDb = thr0 + 3;
	p.twistDb = 6;   double tp = rate(p, 20, NOTCH_OFF, NULL);
	p.twistDb = -6;  double tm = rate(p, 20, NOTCH_OFF, NULL);
	CHECK(tp >= 0.9 && tm >= 0.9, "перекіс +6/-6 дБ при SNR поріг+3: %.0f %% / %.0f %%", tp * 100, tm * 100);
	/* R4: деемфазис HR-C6000 може дати більший перекіс -- до +-12 дБ при SNR 20 дБ. */
	{
		const double tw[] = { -12, -9, 9, 12 };
		for (unsigned k = 0; k < 4; k++)
		{
			p.twistDb = tw[k]; p.snrDb = 20;
			double r20 = rate(p, 20, NOTCH_OFF, NULL);
			p.snrDb = 99;
			double rc = rate(p, 10, NOTCH_OFF, NULL);
			CHECK(r20 >= 0.9 && rc >= 0.99, "перекіс %+.0f дБ: без шуму %.0f %%, SNR 20 дБ %.0f %%", tw[k], rc * 100, r20 * 100);
		}
		p.snrDb = thr0 + 3;
	}
	p.twistDb = 0;
	p.fOff = 50;     double fp = rate(p, 20, NOTCH_OFF, NULL);
	p.fOff = -50;    double fm = rate(p, 20, NOTCH_OFF, NULL);
	CHECK(fp >= 0.9 && fm >= 0.9, "розстройка +50/-50 Гц: %.0f %% / %.0f %%", fp * 100, fm * 100);
	p.fOff = 0; p.snrDb = thr0 + 6;
	p.baudErr = 0.01;              double bp = rate(p, 20, NOTCH_OFF, NULL);
	p.baudErr = -0.01;             double bm = rate(p, 20, NOTCH_OFF, NULL);
	CHECK(bp >= 0.9 && bm >= 0.9, "швидкість +1/-1 %% (SNR поріг+6): %.0f %% / %.0f %%", bp * 100, bm * 100);
	p.snrDb = thr0 + 3;
	/* Частота дискретизації 7805 Гц замість 8000 (-2,4 %): біти й тони «швидші» на 2,5 %.
	 * Без поправки -- зрив, з afskSetSampleRate(виміряна) -- декодується. */
	p.baudErr = 0.025; p.fOff = 42;
	double noFix = rate(p, 20, NOTCH_OFF, NULL);
	s_fsHz = 7805;
	double fix = rate(p, 20, NOTCH_OFF, NULL);
	s_fsHz = 0;
	CHECK(fix >= 0.9, "fs 7805 Гц: без поправки %.0f %%, з поправкою тактів %.0f %%", noFix * 100, fix * 100);
	p.baudErr = 0; p.fOff = 0;
	p.baudErr = 0; p.dc = -3000;
	CHECK(rate(p, 20, NOTCH_OFF, NULL) >= 0.9, "DC -3000: >= 90 %%");

	/* Синусоїда-завада 1,5x амплітуди сигналу на кількох частотах (і не на точках сітки).
	 * Поза смугою -- смуговий фільтр; у смузі -- режекція, частоту якої прошивка бере з розгортки
	 * фону (тут -- так само: NOTCH_AUTO, фон 1,5 с перед пакетом). */
	p = base(); p.frames = 1; p.snrDb = thr0 + 6; p.intRel = 1.5; p.lead = 1.5;
	{
		const double fIn[] = { 300, 3600, 1712, 1033, 1460, 1985, 2437 };
		for (unsigned k = 0; k < sizeof(fIn) / sizeof(fIn[0]); k++)
		{
			p.intF = fIn[k];
			bool inBand = (fIn[k] >= 900 && fIn[k] <= 2500);
			double rn = rate(p, 20, NOTCH_OFF, NULL);
			if (inBand)
			{
				double ra = rate(p, 20, NOTCH_AUTO, NULL);
				CHECK(ra >= 0.9 && fabs(s_lastNotch - fIn[k]) < 4.0,
						"завада %.0f Гц x1,5 (у смузі): без режекції %.0f %%, авто-режекція на %.1f Гц -- %.0f %%",
						fIn[k], rn * 100, s_lastNotch, ra * 100);
			}
			else
			{
				CHECK(rn >= 0.9, "завада %.0f Гц x1,5 (поза смугою): %.0f %%", fIn[k], rn * 100);
			}
		}
		/* Без завади авто-режекція не вмикається і не шкодить. */
		p.intF = 0; p.intRel = 0;
		double ra = rate(p, 20, NOTCH_AUTO, NULL);
		CHECK(ra >= 0.9 && s_lastNotch == 0.0f, "без завади: авто-режекція вимкнена, %.0f %%", ra * 100);
	}

	/* R4: розриви потоку на межах блоків по 160 (як DMA-половини): викинути / продублювати d
	 * відліків кожні 160. Таблиця -- щоб знати, як це б'є по декодуванню (без шуму). Сторінка
	 * «потік» на рації ловить такі розриви стрибком фази тону (test_aprs_probe_dsp, apStream). */
	{
		const int ds[] = { 0, 1, 2, 4, 8, -1, -2, -4, -8 };
		static int16_t tmp[MAX_SAMPLES];
		double res[9];
		printf("    розриви кожні 160 відліків (без шуму, 10 записів по 2 кадри):");
		for (unsigned k = 0; k < 9; k++)
		{
			int ok = 0, tot = 0;
			sig_t q = base(); q.frames = 2;
			s_rng = 31;
			for (int t = 0; t < 10; t++)
			{
				int n = synth(&q, s_ref, s_refLen), o = 0;
				for (int i = 0; i < n && o < MAX_SAMPLES - 16; i++)
				{
					if ((ds[k] > 0) && ((i % 160) >= 160 - ds[k])) { continue; }
					tmp[o++] = s_buf[i];
					if ((ds[k] < 0) && ((i % 160) == 159)) { for (int j = 0; j < -ds[k]; j++) { tmp[o++] = s_buf[i]; } }
				}
				memcpy(s_buf, tmp, (size_t)o * sizeof(int16_t));
				rx_t r = runRx(o, NOTCH_OFF);
				ok += r.match; tot += q.frames;
			}
			res[k] = (double)ok / tot;
			printf(" %+d:%.0f%%", ds[k], res[k] * 100);
		}
		printf("\n");
		CHECK(res[0] >= 0.99, "без розривів -- усі кадри");
		CHECK(res[2] < 0.5 && res[3] < 0.5 && res[7] < 0.5, "розриви 2+ відліки кожні 160 -- кадри втрачаються (так і має бути видно на рації)");
	}

	/* R5: формат I2S RX у FM-прийомі -- звук у бітах 0..9 (доповнення до двох), біти 10..15 однакові
	 * й випадкові (біт 10 ~50 %), тобто сирий відлік = s + {0, +-1024}. Запис R4: сирі 16 біт -- 0 ок,
	 * 10 біт -- 8 ок. Тут те саме на синтетиці: AFSK у 10-бітному діапазоні, «упаковка» як на рації,
	 * далі apFmtExtract() -- 10 біт або «16 біт як є». Плюс «перекидання» на +-512: що буде, якщо
	 * сигнал вийде за 10 біт (у R4 пік був ~360). */
	{
		static int16_t pack[MAX_SAMPLES];
		const double amps[] = { 150, 300, 400, 450, 900 };
		double res10[5], res16 = 0;
		int nearAny = 0;
		for (unsigned k = 0; k < 5; k++)
		{
			int ok10 = 0, ok16 = 0, tot = 0;
			sig_t q = base(); q.frames = 2; q.amp = amps[k]; q.snrDb = 20;
			s_rng = 51;
			for (int t = 0; t < 10; t++)
			{
				int nn = synth(&q, s_ref, s_refLen);
				uint16_t *u = (uint16_t *)pack;
				for (int i = 0; i < nn; i++)
				{
					/* 10 біт із «перекиданням» (як АЦП/слово кодека), біти 10..15 -- випадкові однакові */
					uint16_t lo = (uint16_t)((uint16_t)s_buf[i] & 0x3FFU);
					u[i] = (uint16_t)(lo | ((urand() < 0.5) ? 0xFC00U : 0U));
				}
				apFmt_t f;
				apFmtInit(&f);
				apFmtExtract(&f, u, 1, nn, false, s_buf);
				if (f.nearLim > 0) { nearAny = 1; }
				rx_t r = runRx(nn, NOTCH_OFF);
				ok10 += r.match;
				if (k == 1)
				{
					apFmtExtract(NULL, u, 1, nn, true, s_buf);
					r = runRx(nn, NOTCH_OFF);
					ok16 += r.match;
				}
				tot += q.frames;
			}
			res10[k] = (double)ok10 / tot;
			if (k == 1) { res16 = (double)ok16 / tot; }
		}
		printf("    10 біт, SNR 20 дБ, амплітуда 150/300/400/450/900: %.0f/%.0f/%.0f/%.0f/%.0f %%\n",
				res10[0] * 100, res10[1] * 100, res10[2] * 100, res10[3] * 100, res10[4] * 100);
		CHECK(res10[0] >= 0.9 && res10[1] >= 0.9 && res10[2] >= 0.9,
				"R5: 10-бітний відлік з випадковим бітом 10 -- з маскою декодується як чистий (150/300/400: %.0f/%.0f/%.0f %%)",
				res10[0] * 100, res10[1] * 100, res10[2] * 100);
		CHECK(res16 <= 0.05, "R5: той самий сигнал «16 біт як є» (+-1024 від біта 10) -- %.0f %% (контроль, як 0 з 16 у R4)", res16 * 100);
		CHECK(res10[3] <= 0.5 && res10[4] <= 0.5 && nearAny, "R5: «перекидання» на +-512 (450 + шум, 900) -- %.0f / %.0f %%: навіть рідкісні вершини за 10 біт ламають кадри, «фон» рахує |s|>=480", res10[3] * 100,
				res10[4] * 100);
	}

	/* R4: кадр із помилковим FCS приходить у зворотний виклик як є (довжина з FCS, перші байти). */
	{
		uint8_t bad[AFSK_FRAME_MAX];
		memcpy(bad, s_ref, (size_t)s_refLen);
		bad[30] ^= 0x10;   /* один біт в info */
		p = base(); p.frames = 1;
		s_rng = 41;
		n = synth(&p, bad, s_refLen);
		r = runRx(n, NOTCH_OFF);
		CHECK(r.good == 0 && r.bad == 1 && r.badLen == s_refLen && memcmp(r.badHead, s_ref, 16) == 0,
				"кадр з помилкою: FCS помилка 1, довжина %d (з FCS), перші 16 байт -- як надіслано", r.badLen);
		{
			char la[24];
			ax25LooseAddr(r.badHead, 16, la, sizeof(la));
			CHECK(strcmp(la, "UR5EAA-9>APDR16") == 0, "адреси «як є» з помилкового кадру: %s", la);
			uint8_t junk[16] = { 0x00, 0xFF, 0x13, 0x88, 0x40, 0x40, 0x61, 0x7E, 0x02, 0x9A, 0x40, 0x40, 0x40, 0x40, 0xE0, 0x00 };
			ax25LooseAddr(junk, 16, la, sizeof(la));
			CHECK(strchr(la, '.') != NULL && strchr(la, '>') != NULL, "сміття: «%s» -- з крапками замість непридатних", la);
		}
		CHECK(s_d.pllHist[3] + s_d.pllHist[4] > 0, "гістограма фази тактів: є переходи біля ідеалу (біни 3/4: %u/%u)",
				s_d.pllHist[3], s_d.pllHist[4]);
	}

	/* Негативні: шум, «голос» (суміш тонів 300-1100 Гц з амплітудною модуляцією), тиша. */
	{
		afskDemod_t *d = &s_d;
		rx_t rr;
		memset(&rr, 0, sizeof(rr));
		afskInit(d, onFrame, &rr);
		s_rng = 99;
		int good = 0, bad = 0;
		for (int sec = 0; sec < 60; sec++)
		{
			for (int i = 0; i < 8000; i++) { s_buf[i] = (int16_t)lround(700 * grand()); }
			for (int i = 0; i < 8000; i += 160) { afskProcess(d, &s_buf[i], 160); }
		}
		good = rr.good; bad = d->nBad;
		CHECK(good == 0, "60 с білого шуму: кадрів з правильним FCS -- %d (помилкових FCS %d, серій прапорців %u)", good, bad, d->nFlagSeq);

		memset(&rr, 0, sizeof(rr));
		afskInit(d, onFrame, &rr);
		double phs[4] = { 0 };
		for (int sec = 0; sec < 60; sec++)
		{
			for (int i = 0; i < 8000; i++)
			{
				double t = (sec * 8000 + i) / FS;
				double env = 0.5 + 0.5 * sin(2 * PI * 3.0 * t);
				double f0 = 140 + 40 * sin(2 * PI * 0.7 * t);
				double v = 0;
				for (int h = 1; h <= 4; h++) { phs[h - 1] += 2 * PI * f0 * (h + 1) / FS; v += sin(phs[h - 1]) / h; }
				s_buf[i] = (int16_t)lround(3000 * env * v + 300 * grand());
			}
			for (int i = 0; i < 8000; i += 160) { afskProcess(d, &s_buf[i], 160); }
		}
		CHECK(rr.good == 0, "60 с «голосу»: кадрів з правильним FCS -- %d", rr.good);
	}

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
#endif
