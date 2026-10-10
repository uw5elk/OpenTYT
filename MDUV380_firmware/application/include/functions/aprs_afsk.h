/*
 * aprs_afsk.h -- демодулятор Bell 202 (AFSK 1200 бод, 1200/2200 Гц) і приймач кадрів AX.25
 * для екрана «APRS проба» (R3). Вхід -- відліки I2S RX 8000 Гц (канал L), int16.
 *
 * Ланцюжок (обґрунтування -- docs/aprs-rx-feasibility.md, розділ 7):
 *   1. смуговий фільтр 900-2500 Гц: 2 біквади Баттерворта (4-й порядок), прибирає й DC;
 *   2. режекторний біквад (необов'язково, r = 0,985, смуга ~38 Гц): частота -- з розгортки фону
 *      (aprs_probe_dsp.c, уточнення між точками сітки), якщо там вузька завада;
 *   3. аналітичний сигнал (FIR Гільберта, 15 відводів) і два комплексні кореляційні фільтри
 *      (1200 і 2200 Гц) на вікні AFSK_CORR_LEN = 8 відліків (1 мс), потужність I^2 + Q^2;
 *   4. рішення з поправкою на перекіс рівнів тонів (деемфазис HR-C6000, «twist»): кожен тон
 *      ділиться на корінь зі свого середнього рівня (див. .c);
 *   5. цифрова ФАПЧ тактів 1200 бод (фазовий акумулятор int32, підтягування на кожному переході;
 *      6,67 відліку на біт -- без цілого кроку);
 *   6. NRZI, вилучення бітстафінгу, прапорці 0x7E, FCS CRC-16/X.25.
 *
 * Стан -- одна структура (у прошивці -- CCM), коефіцієнти -- const у flash. Без libm.
 * Хост-тест: tests/test_aprs_afsk.c.
 */
#ifndef _OPENGD77_APRS_AFSK_H_
#define _OPENGD77_APRS_AFSK_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_APRS_RX_PROBE)

#define AFSK_FS             8000
/* Вікно кореляції 8 відліків = 1 мс (1,2 біта): fs/8 = 1000 Гц -- рівно рознесення тонів, тож
 * фільтр 1200 має нуль на 2200 і навпаки. 6, 7, 9, 10 перевірено хост-тестом -- гірше. */
#define AFSK_CORR_LEN       8
#define AFSK_FRAME_MAX      332     /* AX.25: 7*10 адрес + 2 + 256 info + 2 FCS = 330 */
#define AFSK_FRAME_MIN      17      /* 2 адреси + контроль + FCS */
#define AFSK_FLAG_SEQ       4       /* прапорців поспіль, щоб зарахувати серію (преамбулу) */

#include "functions/aprs_probe_dsp.h"   /* apCos2() -- коефіцієнт режекції з таблиці розгортки */

#define AFSK_HILB_LEN       15      /* відводів FIR Гільберта */

/* Кадр між прапорцями (>= AFSK_FRAME_MIN байт, кратний 8 бітам). fcsOk -- len БЕЗ FCS;
 * інакше -- len з FCS (для діагностики «що саме прийшло»). */
typedef void (*afskFrameCb_t)(const uint8_t *frame, uint16_t len, bool fcsOk, void *ctx);

typedef struct
{
	/* фільтри */
	float    bp[2][2];          /* стан DF2T двох біквадів смуги */
	float    nz[2];             /* стан режекторного */
	float    nc;                /* 2cos(w0) режекторного */
	uint8_t  notchOn;
	uint32_t pllStep;           /* 2^32 * 1200 / fs */
	/* кореляція */
	float    hb[AFSK_HILB_LEN];    /* вхід FIR Гільберта */
	uint8_t  hbpos;
	float    hist[AFSK_CORR_LEN];  /* аналітичний сигнал: дійсна */
	float    histQ[AFSK_CORR_LEN]; /* ... і уявна частина */
	uint8_t  hpos;
	/* середні рівні тонів (поправка на перекіс) */
	float    envM, envS;
	/* такти */
	int32_t  pll;
	uint8_t  lastData;          /* знак виходу демодулятора на попередньому відліку */
	uint8_t  lastSample;        /* попередній узятий біт (до NRZI) */
	/* HDLC */
	uint8_t  sh;                /* останні 8 бітів після NRZI */
	uint8_t  inFrame;
	uint8_t  nbits;             /* бітів у поточному неповному байті */
	uint8_t  flagRun;           /* прапорців поспіль із кроком 8 бітів */
	uint8_t  sinceFlag;         /* бітів від останнього прапорця (насичується) */
	uint16_t bitbuf;
	uint16_t len;
	uint8_t  frame[AFSK_FRAME_MAX];
	/* лічильники подій (викликач читає й обнуляє) */
	uint16_t nOk;               /* кадрів з правильним FCS */
	uint16_t nBad;              /* кадрів (>= AFSK_FRAME_MIN байт, кратних 8 біт) з помилковим FCS */
	uint16_t nFlagSeq;          /* серій прапорців (>= AFSK_FLAG_SEQ поспіль) -- преамбули пакетів */
	uint16_t pllHist[8];        /* фаза тактів на переходах (лише в кадрі після >= 2 прапорців):
	                             * бін i -- [i/8 - 1/2, (i+1)/8 - 1/2) біта; 3 і 4 -- біля ідеалу */
	afskFrameCb_t cb;           /* виклик на кожен кадр (правильний чи ні; може бути NULL) */
	void    *ctx;
} afskDemod_t;

void afskInit(afskDemod_t *d, afskFrameCb_t cb, void *ctx);
/* Режекторний фільтр на частоті hz (з розгортки фону, з точністю до ~1 Гц); hz <= 0 -- вимкнути. */
void afskSetNotchHz(afskDemod_t *d, float hz);
/* Поправка тактів на виміряну частоту дискретизації (7000..9000 Гц, інакше -- 8000). */
void afskSetSampleRate(afskDemod_t *d, uint32_t fsHz);
void afskProcess(afskDemod_t *d, const int16_t *x, int n);
/* Скинути лише HDLC/такти (напр. після паузи у відліках), фільтри й лічильники лишити. */
void afskResync(afskDemod_t *d);

/* CRC-16/X.25 (поліном 0x1021 відзеркалений, поч. 0xFFFF, інверсія в кінці). */
uint16_t ax25Crc(const uint8_t *p, int n);
/* Підсумок кадру для екрана: «SRC-n>DST-n» (до 19 симв.) і початок поля info
 * (непридатні до друку -> '.'). false -- кадр не схожий на AX.25. */
bool ax25Summary(const uint8_t *f, int len, char *srcDst, int sdSize, char *info, int infoSize);
/* R4: «як є» -- адреси перших двох полів (байти >> 1, SSID) навіть з помилкового кадру:
 * «SRC-n>DST-n», непридатні до друку символи -> '.'. Щоб на око бачити, чи адреса читається. */
void ax25LooseAddr(const uint8_t *f, int len, char *out, int size);

#endif /* ENABLE_APRS_RX_PROBE */
#endif /* _OPENGD77_APRS_AFSK_H_ */
