/*
 * aprs_rx_probe.c -- діагностика «APRS проба» (R3): I2S від HR-C6000 -> демодулятор AFSK 1200 +
 * AX.25 і розгортка фону, окремі лічильники для 6 варіантів регістрів кодека.
 * Опис -- у aprs_rx_probe.h, план і результати -- docs/aprs-rx-feasibility.md (розділи 6-7),
 * кроки перевірки -- TESTING.md, блоки AD (R2) і AE (R3).
 *
 * Що чіпаємо і як повертаємо (як у R2):
 *   - регістри HR-C6000 0xE0, 0x36, 0x10 (сторінка 4): на вході ЧИТАЄМО поточні значення
 *     й на виході пишемо саме їх (якщо читання неправдоподібне -- штатні FM: 0x89/0x02/0x80);
 *     після цього, якщо зараз іде прийом (підсилювач RF увімкнено), -- radioSetAudioPath(true),
 *     як це робить trx.c на початку прийому;
 *   - I2S3: лише через I2SProbeStart/Stop (i2s.c), прапорці повертаються в «вільно»;
 *   - еко-режим приймача: рівень 0 на час проби, потім -- попередній.
 * R3 прибрав джерело Б (PC3/ADC2/TIM7): на Plus 10W там нічого немає.
 * R5: у FM-прийомі звук у півслові I2S -- лише біти 0..9 (доповнення до двох), біт 10 --
 * випадковий (+-1024 «фону»); обробка бере 10-бітний відлік (apSample10), USB-запис -- сирий.
 * R6: формат буває й справжнім 16-бітним (R5 на залізі) -- автовизначення на кожному блоці
 * (apFmtDetBlock), «16» зводиться до масштабу «10»; сторінка «регістри» читає регістри кодека
 * раз на секунду; лічильники подій, що переписують регістри (шумодав, біпи, підказки), і
 * діагностика старту I2S (такти від фронту WS, рівень WS, прапорець FRE веденого I2S).
 * R7: детектор nbits (apFmtDetBlock; слово -- k однакових сміттєвих бітів над (16-k) бітами відліку),
 * детермінований старт I2S (i2s.c: WS-синхронізація й вмикання I2SE з вимкненими перериваннями,
 * T_start, сторінка «фаза»), розгортка T_start (кнопка 5, сторінка «скан»), регістри SPI3/I2S3ext
 * раз на секунду, FRE за останню секунду, кадри окремо для кожного nbits.
 * Поза екраном проби (aprsRxProbeIsOn() == false) жоден шлях DMR/AMBE/FM не змінено.
 */
#include "functions/aprs_rx_probe.h"
#include "functions/aprs_rx.h"   /* R8: aprsRxSuspendForAudio() -- проба бере I2S і кільце у приймача */

#if defined(APRS_RX_PROBE)

#include "main.h"
#include "interfaces/i2s.h"
#include "interfaces/hr-c6000_spi.h"
#include "functions/sound.h"
#include "functions/trx.h"
#include "functions/voicePrompts.h"
#include "functions/rxPowerSaving.h"
#include "functions/ticks.h"
#include "hardware/radioHardwareInterface.h"
#include <string.h>

/* Стан лише в CCM (стартап її не обнуляє -- див. aprsRxProbeInit()). Секція .aes_ccmram
 * лежить у самому кінці CCM (лінкер-скрипт), тож стокові об'єкти .ccmram не зсуваються. */
#define APRS_PROBE_CCM   __attribute__((section(".aes_ccmram")))
#define APRS_PROBE_MAGIC 0xA9A5C0DEUL

#define APRS_PROBE_BLOCK            160U   /* відліків L у половині буфера I2S (20 мс) */
#define APRS_PROBE_BLOCKS_PER_TICK  2U     /* обробка за один тік (~0,5 мс на блок при 72 МГц) */
#define APRS_PROBE_RETRY_MS         250U
#define APRS_PROBE_NOTCH_QUIET      100U   /* блоків (2 с) без серій прапорців -- можна міняти режекцію */
#define APRS_PROBE_FS_MIN_MS        5000U  /* частоту дискретизації показуємо після 5 с */

/* Кільце блоків -- у буфері звуку AMBE/підказок/хотспоту (4800 Б, CCM). У FM-прийомі з
 * пробою він простоює: DMR немає, хотспот вимкнено, а на час голосової підказки I2S проби
 * зупиняється і кільце після неї починається спочатку.
 * R4: два розклади. Звичайний -- лише канал L, 14 блоків по 160 (280 мс запасу). На час
 * USB-запису «обидва канали, як є» -- уся половина DMA (160 кадрів L,R = 320 півслів), 7 блоків
 * (140 мс). Демодулятор бере L з будь-якого розкладу. */
#define APRS_PROBE_RING_BASE   ((uint16_t *)(void *)&audioAndHotspotDataBuffer)
#define APRS_PROBE_SLOTS_MONO   14U
#define APRS_PROBE_SLOTS_STEREO 7U
#define APRS_PROBE_SLOTS_MAX    APRS_PROBE_SLOTS_MONO
_Static_assert(sizeof(audioAndHotspotDataBuffer) >= (APRS_PROBE_SLOTS_MONO * APRS_PROBE_BLOCK * sizeof(uint16_t)),
		"probe ring (mono) does not fit audioAndHotspotDataBuffer");     /* кільце не вміщається */
_Static_assert(sizeof(audioAndHotspotDataBuffer) >= (APRS_PROBE_SLOTS_STEREO * 2U * APRS_PROBE_BLOCK * sizeof(uint16_t)),
		"probe ring (stereo) does not fit audioAndHotspotDataBuffer");   /* кільце не вміщається */

/* USB-запис (R4): відповідь -- заголовок і цілі блоки, скільки влазить у буфер відповіді. */
#define APRS_PROBE_USB_VER      1U
#define APRS_PROBE_USB_HDR      20U
#define APRS_PROBE_USB_MAX_SECS 120U
#define APRS_PROBE_USB_IDLE_MS  2000U  /* ПК мовчить довше -- стоп запису, щоб кільце не стояло */

/* R6: регістри HR-C6000 (сторінка 4) для сторінки «регістри» -- аудіокодек/I2S і все, що пишуть
 * FM-прийом/передача, біпи й підказки (docs/aprs-rx-feasibility.md, розділ 10.3). Порядок -- як
 * на екрані: E0..EF, далі по 4 у рядку (R7: 0x25, 0x35, 0x21, 0x2F прибрано -- місце під SPI3). */
static const uint8_t s_regAddr[APRS_PROBE_NUM_REGS] =
{
	0xE0, 0xE1, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7,
	0xE8, 0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xEF,
	0x06, 0x10, 0x26, 0x34,
	0x36, 0x37, 0x22, 0x60
};
#define APRS_PROBE_REGS_MS      1000U
_Static_assert(sizeof(((aprsProbeDiag_t *)0)->regs) == (I2S_PROBE_NREGS * sizeof(uint16_t)), "aprsProbeDiag_t.regs != I2S_PROBE_NREGS");

/* Штатні FM-значення -- на випадок, якщо прочитати не вдалося. */
#define REG_E0_FM   0x89
#define REG_36_FM   0x02
#define REG_10_FM   0x80

/* Варіанти R3 (результати R2: тони розрізняються, мікрофон вимкнено): { 0xE0, 0x36, 0x10, № у R2 }. */
static const uint8_t s_variants[APRS_PROBE_NUM_VARIANTS][4] =
{
	{ 0x89, 0x02, 0x80,  1 },   /* штатні регістри FM-прийому */
	{ 0x89, 0x12, 0x80,  3 },
	{ 0x8B, 0x02, 0x80,  7 },
	{ 0x8B, 0x12, 0x80,  9 },
	{ 0x83, 0x02, 0x80, 10 },
	{ 0x83, 0x12, 0x80, 12 }
};

/* R7: розгортка T_start (кнопка 5). */
typedef struct
{
	uint8_t           active;
	uint8_t           idx;          /* T = 2 * idx */
	uint8_t           rep;          /* перезапусків для цього T зроблено */
	uint8_t           phase;        /* 0 -- треба перезапуск I2S, 1 -- чекаємо вердикт */
	uint8_t           first;        /* nbits першого вердикту цього T */
	uint8_t           mixed;
	uint8_t           nVerd;        /* вердиктів для цього T */
	uint16_t          savedT;       /* T_start до розгортки */
	uint32_t          t0;           /* мс: останній перезапуск */
} aprsScan_t;

typedef struct
{
	uint32_t          magic;        /* APRS_PROBE_MAGIC -- екран відкрито */
	uint8_t           variant;
	uint8_t           status;       /* aprsProbeStatus_t */
	bool              engaged;      /* регістри збережено, джерело вибрано (лише у FM) */
	volatile bool     i2sRunning;
	bool              readOk;
	bool              notchAuto;
	bool              lastRf, lastMelody;
	uint8_t           savedE0, saved36, saved10;
	int               savedEco;
	uint32_t          lastApplyMs, lastTryMs;
	/* кільце: пише переривання DMA, читають тік (tail) і USB-запис (usbTail) */
	volatile uint8_t  head, tail, usbTail;
	uint8_t           slots;        /* 14 (L) або 7 (L,R) */
	uint8_t           stereo;       /* розклад кільця: 1 -- уся половина DMA */
	uint32_t          slotSeq[APRS_PROBE_SLOTS_MAX];   /* номер блока від початку запису */
	volatile uint32_t seqCounter;
	/* колбеки DMA (R4): половина / повний і порушення черговості (дві однакові поспіль) */
	volatile uint32_t cbHalf, cbFull, cbOrder;
	volatile uint8_t  cbLast;
	/* USB-запис */
	volatile bool     capActive;
	bool              capDone;
	uint8_t           capStereo;
	uint16_t          capTotal;     /* блоків замовлено */
	uint32_t          capSent;
	volatile uint32_t capLost;
	uint32_t          capPollMs;    /* останній запит ПК: без запитів > 2 с запис зупиняється сам */
	volatile uint32_t isrBlocks;    /* блоків від старту I2S (для частоти дискретизації) */
	volatile uint32_t overflows;
	volatile uint32_t lastBlockMs;
	/* частота дискретизації */
	uint32_t          fsT0Ms, fsB0;
	uint32_t          fsHz, fsSecs;
	uint32_t          fsAppliedHz;
	/* обробка */
	uint32_t          blocks;       /* оброблених з останнього старту */
	uint16_t          quiet;        /* блоків без нових серій прапорців */
	uint16_t          notchHz;
	bool              lastPrompt;
	uint8_t           fmtMode;      /* APRS_PROBE_FMT_AUTO / _10 / _11 / _16 (кнопка *) */
	apFmtDet_t        det;          /* R7: детектор nbits */
	/* R7: детермінований старт I2S, діагностика SPI3/I2S3ext */
	aprsProbeDiag_t   diag;
	uint32_t          halCycles;    /* тривалість HAL у попередньому старті (0 -- ще не міряли) */
	uint16_t          tStart;       /* T_start, мкс після фронту WS */
	uint16_t          winPeak;      /* пік |s| з початку вікна розгортки */
	uint8_t           nbSlotN[APRS_PROBE_NB_SLOTS];     /* nbits слота (0 -- вільний) */
	uint16_t          nbSlotOk[APRS_PROBE_NB_SLOTS];
	uint16_t          nbSlotBad[APRS_PROBE_NB_SLOTS];
	aprsScan_t        scan;
	uint8_t           scanCode[APRS_PROBE_SCAN_N];
	/* R6: події, після яких стоковий код переписує регістри кодека */
	uint32_t          evSqOpen, evSqClose, evBeep, evPrompt;
	/* R6: регістри кодека, прочитані з чипа (сторінка «регістри») */
	uint8_t           regVal[APRS_PROBE_NUM_REGS];
	uint32_t          regOkMask;    /* біт i -- regVal[i] прочитано */
	uint32_t          regReadMs;    /* 0 -- ще не читали */
	afskDemod_t       demod;
	apBg_t            bg;
	apStream_t        stream;       /* R4: безперервність тону 1200 Гц на межах блоків */
	aprsProbeVar_t    var[APRS_PROBE_NUM_VARIANTS];
} aprsProbeState_t;

static aprsProbeState_t s_probe APRS_PROBE_CCM;   /* CCM-INIT(aprsRxProbeInit) */

static inline bool stateValid(void)
{
	return (s_probe.magic == APRS_PROBE_MAGIC);
}

void aprsRxProbeInit(void)
{
	memset(&s_probe, 0, sizeof(s_probe));
}

bool aprsRxProbeIsOn(void)
{
	return stateValid();
}

uint8_t aprsRxProbeVariant(void)
{
	return stateValid() ? s_probe.variant : 0;
}

uint8_t aprsRxProbeVariantR2(uint8_t v)
{
	return (v < APRS_PROBE_NUM_VARIANTS) ? s_variants[v][3] : 0;
}

aprsProbeStatus_t aprsRxProbeStatus(void)
{
	return stateValid() ? (aprsProbeStatus_t)s_probe.status : APRS_PROBE_ST_IDLE;
}

void aprsRxProbeVariantRegs(uint8_t v, uint8_t *e0, uint8_t *r36, uint8_t *r10)
{
	if (v >= APRS_PROBE_NUM_VARIANTS)
	{
		v = 0;
	}
	*e0 = s_variants[v][0];
	*r36 = s_variants[v][1];
	*r10 = s_variants[v][2];
}

bool aprsRxProbeSavedRegs(uint8_t *e0, uint8_t *r36, uint8_t *r10, bool *readOk)
{
	if ((stateValid() == false) || (s_probe.engaged == false))
	{
		return false;
	}
	*e0 = s_probe.savedE0;
	*r36 = s_probe.saved36;
	*r10 = s_probe.saved10;
	*readOk = s_probe.readOk;
	return true;
}

const aprsProbeVar_t *aprsRxProbeStats(uint8_t v)
{
	return &s_probe.var[(v < APRS_PROBE_NUM_VARIANTS) ? v : 0];
}

bool aprsRxProbeFs(uint32_t *hz, uint32_t *seconds)
{
	if ((stateValid() == false) || (s_probe.fsHz == 0))
	{
		return false;
	}
	*hz = s_probe.fsHz;
	*seconds = s_probe.fsSecs;
	return true;
}

uint32_t aprsRxProbeBlocks(void)
{
	return s_probe.blocks;
}

uint32_t aprsRxProbeOverflows(void)
{
	return s_probe.overflows;
}

uint32_t aprsRxProbeMsSinceBlock(void)
{
	return ticksGetMillis() - s_probe.lastBlockMs;
}

bool aprsRxProbeNotchAuto(void)
{
	return stateValid() && s_probe.notchAuto;
}

uint16_t aprsRxProbeNotchHz(void)
{
	return stateValid() ? s_probe.notchHz : 0;
}

const apStream_t *aprsRxProbeStream(void)
{
	return &s_probe.stream;
}

const uint16_t *aprsRxProbePllHist(void)
{
	return s_probe.demod.pllHist;
}

void aprsRxProbeDmaCounters(uint32_t *half, uint32_t *full, uint32_t *order)
{
	*half = s_probe.cbHalf;
	*full = s_probe.cbFull;
	*order = s_probe.cbOrder;
}

bool aprsRxProbeCapture(uint32_t *sent, uint32_t *total, uint32_t *lost)
{
	if ((stateValid() == false) || ((s_probe.capActive == false) && (s_probe.capDone == false)))
	{
		return false;
	}
	*sent = s_probe.capSent;
	*total = s_probe.capTotal;
	*lost = s_probe.capLost;
	return true;
}

/* ---- переривання DMA: лише скласти блок у кільце ---------------------------------- */

void aprsRxProbeI2SBlock(uint32_t bufNum)
{
	if ((stateValid() == false) || (s_probe.i2sRunning == false) || (bufNum >= NUM_I2S_BUFFERS))
	{
		return;
	}

	/* Колбеки DMA мають іти строго по черзі: половина (0), повний (1), половина... */
	if (bufNum == 0U)
	{
		s_probe.cbHalf++;
	}
	else
	{
		s_probe.cbFull++;
	}
	if ((s_probe.cbHalf + s_probe.cbFull > 1U) && (bufNum == s_probe.cbLast))
	{
		s_probe.cbOrder++;
	}
	s_probe.cbLast = (uint8_t)bufNum;

	uint8_t h = s_probe.head;
	uint8_t next = (uint8_t)((h + 1U) % s_probe.slots);
	s_probe.isrBlocks++;
	s_probe.lastBlockMs = ticksGetMillis();
	uint32_t seq = s_probe.seqCounter++;
	if ((next == s_probe.tail) || (s_probe.capActive && (next == s_probe.usbTail)))
	{
		/* тік (або USB) не встигає -- блок губимо; демодулятор переживе як шум, запис -- як
		 * пропуск номера блока (ПК-бік підставить тишу й порахує) */
		s_probe.overflows++;
		if (s_probe.capActive && (next == s_probe.usbTail))
		{
			s_probe.capLost++;
		}
		return;
	}

	/* Половина буфера: 2 x 160 півслів = 160 стерео-кадрів (L, R), 20 мс при 8 кГц.
	 * Лівий канал -- парні (як у soundReceiveRefillData()); R2: L і R однакові.
	 * Колбек -- від RX-DMA (HAL: hdmarx->XferHalfCpltCallback), тож ця половина вже вся записана,
	 * а DMA тим часом пише іншу. */
	const uint16_t *src = &i2s_Rx_Buffer[bufNum][0][0];
	if (s_probe.stereo)
	{
		memcpy(APRS_PROBE_RING_BASE + ((uint32_t)h * 2U * APRS_PROBE_BLOCK), src, 2U * APRS_PROBE_BLOCK * sizeof(uint16_t));
	}
	else
	{
		uint16_t *dst = APRS_PROBE_RING_BASE + ((uint32_t)h * APRS_PROBE_BLOCK);
		for (uint32_t i = 0; i < APRS_PROBE_BLOCK; i++)
		{
			dst[i] = src[2U * i];
		}
	}
	s_probe.slotSeq[h] = seq;
	__DMB();
	s_probe.head = next;
}

/* ---- обробка (тік) ---------------------------------------------------------------- */

static void onFrame(const uint8_t *frame, uint16_t len, bool fcsOk, void *ctx)
{
	(void)ctx;
	aprsProbeVar_t *v = &s_probe.var[s_probe.variant];
	if (fcsOk == false)
	{
		/* R4: що саме прийшло з помилкою -- довжина з FCS і перші 16 байтів */
		v->badLen = len;
		memset(v->badHead, 0, sizeof(v->badHead));
		memcpy(v->badHead, frame, (len < sizeof(v->badHead)) ? len : sizeof(v->badHead));
		return;
	}
	if (ax25Summary(frame, len, v->srcDst, sizeof(v->srcDst), v->info, sizeof(v->info)) == false)
	{
		strcpy(v->srcDst, "?");   /* FCS правильний, але адреси не схожі на AX.25 */
	}
}

static uint16_t clip16(uint32_t v)
{
	return (v > 65535U) ? 65535U : (uint16_t)v;
}

/* R7: nbits, яким обробляється зараз. «Авто» -- вердикт детектора (поки його нема -- 10, як у R5). */
static uint8_t effNbits(void)
{
	switch (s_probe.fmtMode)
	{
		case APRS_PROBE_FMT_10:
			return 10U;
		case APRS_PROBE_FMT_11:
			return 11U;
		case APRS_PROBE_FMT_16:
			return 16U;
		default:
			return (s_probe.det.nbits != 0U) ? s_probe.det.nbits : 10U;
	}
}

/* R7: лічильники кадрів окремо для кожного nbits (до 4 значень). */
static void nbSlotAdd(uint8_t nb, uint16_t ok, uint16_t bad)
{
	int freeSlot = -1;
	for (int i = 0; i < (int)APRS_PROBE_NB_SLOTS; i++)
	{
		if (s_probe.nbSlotN[i] == nb)
		{
			s_probe.nbSlotOk[i] = (uint16_t)(s_probe.nbSlotOk[i] + ok);
			s_probe.nbSlotBad[i] = (uint16_t)(s_probe.nbSlotBad[i] + bad);
			return;
		}
		if ((s_probe.nbSlotN[i] == 0U) && (freeSlot < 0))
		{
			freeSlot = i;
		}
	}
	if (freeSlot >= 0)
	{
		s_probe.nbSlotN[freeSlot] = nb;
		s_probe.nbSlotOk[freeSlot] = ok;
		s_probe.nbSlotBad[freeSlot] = bad;
	}
}

static uint8_t tCntBucket(uint8_t nb)
{
	return (nb == 10U) ? 0U : ((nb == 11U) ? 1U : ((nb == 16U) ? 2U : 3U));
}

static void processBlock(const int16_t *x)
{
	aprsProbeVar_t *v = &s_probe.var[s_probe.variant];
	afskDemod_t *d = &s_probe.demod;
	apBgResult_t br;

	afskProcess(d, x, APRS_PROBE_BLOCK);
	apStreamBlock(&s_probe.stream, x);
	for (uint32_t i = 0; i < APRS_PROBE_BLOCK; i++)
	{
		uint16_t a = (uint16_t)((x[i] < 0) ? -x[i] : x[i]);
		if (a > s_probe.winPeak)
		{
			s_probe.winPeak = a;
		}
	}

	if (d->nFlagSeq != 0)
	{
		s_probe.quiet = 0;
	}
	else if (s_probe.quiet < 0xFFFF)
	{
		s_probe.quiet++;
	}
	v->ok = (uint16_t)(v->ok + d->nOk);
	v->bad = (uint16_t)(v->bad + d->nBad);
	v->flagSeq = (uint16_t)(v->flagSeq + d->nFlagSeq);
	if ((s_probe.fmtMode != APRS_PROBE_FMT_AUTO) || (s_probe.det.nbits != 0U))
	{
		nbSlotAdd(effNbits(), d->nOk, d->nBad);   /* R7: кадри окремо для кожного nbits */
	}
	d->nOk = d->nBad = d->nFlagSeq = 0;

	if (apBgBlock(&s_probe.bg, x, &br))
	{
		v->bgValid = 1;
		v->f1 = (uint16_t)(br.f1 + 0.5f);
		v->a1 = clip16(br.a1);
		v->share1 = br.share1;
		v->f2 = br.f2;
		v->a2 = clip16(br.a2);
		v->rms = clip16(br.rms);
		v->dc = (int16_t)((br.mean > 32767) ? 32767 : ((br.mean < -32768) ? -32768 : br.mean));
		v->peak = s_probe.winPeak;
		s_probe.winPeak = 0;

		/* Режекція -- лише поза пакетами (2 с без серій прапорців і не посеред кадру): інакше
		 * розгортка бачила б тони самого APRS. Частоту дає розгортка (уточнена до ~1 Гц). */
		if (s_probe.notchAuto && (s_probe.quiet >= APRS_PROBE_NOTCH_QUIET) && (d->inFrame == 0))
		{
			float hz = apBgNotchHz(&br);
			uint16_t ihz = (uint16_t)(hz + 0.5f);
			if (ihz != s_probe.notchHz)
			{
				afskSetNotchHz(d, hz);
				s_probe.notchHz = ihz;
			}
		}
	}
	s_probe.blocks++;
}

static void measureFs(void)
{
	uint32_t b = s_probe.isrBlocks;

	if (s_probe.fsT0Ms == 0)
	{
		if (b > 0)
		{
			s_probe.fsT0Ms = s_probe.lastBlockMs;
			s_probe.fsB0 = b;
			if (s_probe.fsT0Ms == 0)
			{
				s_probe.fsT0Ms = 1;
			}
		}
		return;
	}

	uint32_t dt = s_probe.lastBlockMs - s_probe.fsT0Ms;   /* від блока до блока -- без похибки тіку */
	if (dt >= APRS_PROBE_FS_MIN_MS)
	{
		uint64_t samples = (uint64_t)(b - s_probe.fsB0) * APRS_PROBE_BLOCK;
		s_probe.fsHz = (uint32_t)((samples * 1000U + (dt / 2U)) / dt);
		s_probe.fsSecs = dt / 1000U;
		/* Поправка тактів демодулятора -- коли відхилення помітне (> 0,1 %) і правдоподібне. */
		if ((s_probe.fsSecs >= 10U) && (s_probe.fsHz != s_probe.fsAppliedHz) &&
				((s_probe.fsHz < 7992U) || (s_probe.fsHz > 8008U) || (s_probe.fsAppliedHz != 0U)))
		{
			afskSetSampleRate(&s_probe.demod, s_probe.fsHz);
			s_probe.fsAppliedHz = s_probe.fsHz;
		}
	}
}

static void ringLayout(bool stereo)
{
	s_probe.stereo = stereo ? 1 : 0;
	s_probe.slots = stereo ? APRS_PROBE_SLOTS_STEREO : APRS_PROBE_SLOTS_MONO;
	s_probe.head = 0;
	s_probe.tail = 0;
	s_probe.usbTail = 0;
}

static void ringReset(void)
{
	ringLayout(s_probe.capActive && s_probe.capStereo);
	s_probe.cbLast = 1;   /* перший колбек -- половина (0) */
	s_probe.cbHalf = 0;
	s_probe.cbFull = 0;
	s_probe.cbOrder = 0;
	s_probe.isrBlocks = 0;
	s_probe.overflows = 0;
	s_probe.blocks = 0;
	s_probe.lastBlockMs = ticksGetMillis();
	s_probe.fsT0Ms = 0;
	s_probe.fsB0 = 0;
	s_probe.fsHz = 0;
	s_probe.fsSecs = 0;
}

/* Демодулятор і розгортка -- з нуля (новий варіант / новий старт I2S). Режекція -- заново з фону. */
static void dspReset(void)
{
	afskInit(&s_probe.demod, onFrame, NULL);
	if (s_probe.fsAppliedHz != 0U)
	{
		afskSetSampleRate(&s_probe.demod, s_probe.fsAppliedHz);
	}
	apBgInit(&s_probe.bg);
	apStreamInit(&s_probe.stream);
	s_probe.notchHz = 0;
	s_probe.quiet = APRS_PROBE_NOTCH_QUIET;   /* серій прапорців ще не було */
}

/* ---- I2S ----------------------------------------------------------------------- */

static void i2sStop(void)
{
	if (s_probe.i2sRunning)
	{
		s_probe.i2sRunning = false;
		I2SProbeStop();
	}
}

/* R7: запуск I2S з детермінованою фазою (i2s.c): I2SE вмикається через T_start після фронту WS.
 * Перший запуск після відкриття спершу двічі міряє тривалість HAL (старт-стоп без затримки). */
#define APRS_PROBE_WS_PERIOD_US   125U   /* 8 кГц */

static uint32_t cyclesPerUs(void)
{
	uint32_t hclk = HAL_RCC_GetHCLKFreq();
	return (hclk >= 1000000U) ? (hclk / 1000000U) : 1U;
}

static void i2sTryStart(void)
{
	if (voicePromptsIsPlaying() || g_TX_SAI_in_use)
	{
		s_probe.status = APRS_PROBE_ST_BUSY;
		return;
	}

	uint32_t perUs = cyclesPerUs();
	uint32_t period = perUs * APRS_PROBE_WS_PERIOD_US;
	uint32_t tCyc = (uint32_t)s_probe.tStart * perUs;
	uint32_t act = 0, ws = 0;
	bool ok = true;

	if (s_probe.halCycles == 0U)
	{
		/* калібрування: два старт-стопи без затримки; тривалість HAL беремо з другого (код уже в кеші) */
		for (int pass = 0; (pass < 2) && ok; pass++)
		{
			uint32_t h = 0;
			ok = I2SProbeStart(0U, period, &h, &act, &ws);
			if (ok)
			{
				I2SProbeStop();
				s_probe.halCycles = h;
			}
		}
	}

	ringReset();
	dspReset();
	apFmtDetRestart(&s_probe.det);   /* новий старт -- новий формат: вердикт забуто */
	if (ok)
	{
		s_probe.i2sRunning = true;   /* до старту: перше переривання може прийти одразу */
		ok = I2SProbeStart(tCyc, period, &s_probe.halCycles, &act, &ws);
	}

	if (ok)
	{
		s_probe.status = APRS_PROBE_ST_RUNNING;
		s_probe.diag.starts++;
		s_probe.diag.tSetUs = s_probe.tStart;
		s_probe.diag.tMeasUs = (uint16_t)(act / perUs);
		s_probe.diag.halUs = (uint16_t)(s_probe.halCycles / perUs);
		s_probe.diag.wsAfter = (uint8_t)ws;
		(void)I2SProbeStatusRegs();   /* скинути FRE, що лишився з попереднього сеансу */
	}
	else
	{
		s_probe.i2sRunning = false;
		s_probe.status = (g_TX_SAI_in_use ? APRS_PROBE_ST_BUSY : APRS_PROBE_ST_NO_WS);
	}
}

/* ---- регістри HR-C6000 --------------------------------------------------------- */

static void regsSave(void)
{
	uint8_t e0 = 0, r36 = 0, r10 = 0;
	bool ok = (SPI0ReadPageRegByte(0x04, 0xE0, &e0) == kStatus_Success);
	ok = ok && (SPI0ReadPageRegByte(0x04, 0x36, &r36) == kStatus_Success);
	ok = ok && (SPI0ReadPageRegByte(0x04, 0x10, &r10) == kStatus_Success);

	/* Чи читаються 0x36/0x10 взагалі -- невідомо (0xE0 читається: на ньому стоїть
	 * SPI0ClearPageRegByteWithMask у HRC6000SetMic). Тому приймаємо лише значення, які пише
	 * сама прошивка, інакше -- штатні FM. */
	bool plausible = ((r36 == 0x00) || (r36 == 0x02)) && ((r10 == 0x80) || (r10 == 0x6E));
	s_probe.readOk = ok && plausible;
	s_probe.savedE0 = ok ? e0 : REG_E0_FM;
	s_probe.saved36 = s_probe.readOk ? r36 : REG_36_FM;
	s_probe.saved10 = s_probe.readOk ? r10 : REG_10_FM;
}

static void regsWrite(uint8_t e0, uint8_t r36, uint8_t r10)
{
	SPI0WritePageRegByte(0x04, 0xE0, e0);
	SPI0WritePageRegByte(0x04, 0x36, r36);
	SPI0WritePageRegByte(0x04, 0x10, r10);
}

static void regsRestore(void)
{
	regsWrite(s_probe.savedE0, s_probe.saved36, s_probe.saved10);
	if (audioAmpGetStatus() & AUDIO_AMP_CHANNEL_RF)
	{
		radioSetAudioPath(true);   /* прийом іде -- FM-звук у динамік, як після trx.c */
	}
}

static void regsApplyVariant(void)
{
	regsWrite(s_variants[s_probe.variant][0], s_variants[s_probe.variant][1], s_variants[s_probe.variant][2]);
	s_probe.lastApplyMs = ticksGetMillis();
}

/* ---- керування ------------------------------------------------------------------ */

static void sourceStart(void)
{
	i2sStop();
	regsApplyVariant();
	s_probe.lastTryMs = ticksGetMillis();
	i2sTryStart();
}

static void engage(void)
{
	regsSave();
	s_probe.engaged = true;
	s_probe.lastRf = ((audioAmpGetStatus() & AUDIO_AMP_CHANNEL_RF) != 0);
	s_probe.lastMelody = soundMelodyIsPlaying();
	sourceStart();
}

static void disengage(void)
{
	if (s_probe.engaged)
	{
		i2sStop();
		regsRestore();
		s_probe.engaged = false;
	}
}

static bool isFmRx(void)
{
	return (trxGetMode() == RADIO_MODE_ANALOG) && (trxTransmissionEnabled == false);
}

void aprsRxProbeOpen(void)
{
	aprsRxProbeClose();
	aprsRxSuspendForAudio();   /* R8: фоновий приймач APRS віддає I2S і кільце пробі (тік не відновить його, поки проба відкрита) */

	memset(&s_probe, 0, sizeof(s_probe));
	s_probe.magic = APRS_PROBE_MAGIC;
	s_probe.variant = 0;
	s_probe.status = APRS_PROBE_ST_IDLE;
	s_probe.notchAuto = true;
	s_probe.fmtMode = APRS_PROBE_FMT_AUTO;
	apFmtDetInit(&s_probe.det);          /* до першого вердикту обробка йде як «10», як у R5 */
	s_probe.tStart = APRS_PROBE_T_START_US;
	s_probe.diag.tSetUs = s_probe.tStart;
	dspReset();

	s_probe.savedEco = rxPowerSavingGetLevel();
	rxPowerSavingSetLevel(0);   /* приймач не вимикається посеред пакета */

	if (isFmRx())
	{
		engage();
	}
	else
	{
		s_probe.status = APRS_PROBE_ST_NOT_FM;
	}
}

void aprsRxProbeClose(void)
{
	if (stateValid() == false)
	{
		return;
	}
	disengage();
	rxPowerSavingSetLevel(s_probe.savedEco);
	s_probe.magic = 0;
}

void aprsRxProbeSelect(int delta)
{
	if (stateValid() == false)
	{
		return;
	}
	if (s_probe.scan.active)
	{
		return;   /* під час розгортки T_start регістри кодека не чіпаємо */
	}
	int v = (int)s_probe.variant + delta;
	while (v < 0)
	{
		v += APRS_PROBE_NUM_VARIANTS;
	}
	s_probe.variant = (uint8_t)(v % APRS_PROBE_NUM_VARIANTS);

	if (s_probe.engaged)
	{
		sourceStart();   /* регістри нового варіанта; демодулятор і розгортка -- з нуля */
	}
}

void aprsRxProbeResetCurrent(void)
{
	if (stateValid())
	{
		memset(&s_probe.var[s_probe.variant], 0, sizeof(aprsProbeVar_t));
		memset(s_probe.demod.pllHist, 0, sizeof(s_probe.demod.pllHist));
		apStreamInit(&s_probe.stream);
		s_probe.cbHalf = 0;
		s_probe.cbFull = 0;
		s_probe.cbOrder = 0;
		/* R7: перемикання детектора й кадри по nbits -- теж (поточний вердикт лишається) */
		s_probe.det.switches = 0;
		memset(s_probe.nbSlotN, 0, sizeof(s_probe.nbSlotN));
		memset(s_probe.nbSlotOk, 0, sizeof(s_probe.nbSlotOk));
		memset(s_probe.nbSlotBad, 0, sizeof(s_probe.nbSlotBad));
		s_probe.winPeak = 0;
	}
}

void aprsRxProbeToggleFormat(void)
{
	if (stateValid())
	{
		s_probe.fmtMode = (uint8_t)((s_probe.fmtMode + 1U) % APRS_PROBE_FMT_MODES);
		dspReset();   /* фільтри й такти, налаштовані на інший формат, -- з нуля */
	}
}

uint8_t aprsRxProbeFormatMode(void)
{
	return stateValid() ? s_probe.fmtMode : APRS_PROBE_FMT_AUTO;
}

uint8_t aprsRxProbeNbits(void)
{
	return stateValid() ? effNbits() : 10U;
}

const apFmtDet_t *aprsRxProbeFormatDet(void)
{
	return &s_probe.det;
}

bool aprsRxProbeNbSlot(uint8_t i, uint8_t *nbits, uint16_t *ok, uint16_t *bad)
{
	if ((stateValid() == false) || (i >= APRS_PROBE_NB_SLOTS) || (s_probe.nbSlotN[i] == 0U))
	{
		return false;
	}
	*nbits = s_probe.nbSlotN[i];
	*ok = s_probe.nbSlotOk[i];
	*bad = s_probe.nbSlotBad[i];
	return true;
}

const aprsProbeDiag_t *aprsRxProbeDiag(void)
{
	return &s_probe.diag;
}

void aprsRxProbeTAdjust(int delta)
{
	if ((stateValid() == false) || s_probe.scan.active)
	{
		return;
	}
	int t = (int)s_probe.tStart + delta;
	t = (t < 0) ? 0 : ((t > (int)APRS_PROBE_T_MAX_US) ? (int)APRS_PROBE_T_MAX_US : t);
	if ((uint16_t)t != s_probe.tStart)
	{
		s_probe.tStart = (uint16_t)t;
		s_probe.diag.tSetUs = s_probe.tStart;
		memset(s_probe.diag.tCnt, 0, sizeof(s_probe.diag.tCnt));
	}
}

void aprsRxProbeEvents(uint32_t *sqOpen, uint32_t *sqClose, uint32_t *beeps, uint32_t *prompts)
{
	*sqOpen = s_probe.evSqOpen;
	*sqClose = s_probe.evSqClose;
	*beeps = s_probe.evBeep;
	*prompts = s_probe.evPrompt;
}

void aprsRxProbeRegsRefresh(void)
{
	if ((stateValid() == false) || (s_probe.engaged == false))
	{
		return;
	}
	uint32_t now = ticksGetMillis();
	if ((s_probe.regReadMs != 0U) && ((now - s_probe.regReadMs) < APRS_PROBE_REGS_MS))
	{
		return;
	}
	s_probe.regReadMs = (now != 0U) ? now : 1U;
	s_probe.regOkMask = 0;
	for (uint32_t i = 0; i < APRS_PROBE_NUM_REGS; i++)
	{
		uint8_t v = 0;
		if (SPI0ReadPageRegByte(0x04, s_regAddr[i], &v) == kStatus_Success)
		{
			s_probe.regVal[i] = v;
			s_probe.regOkMask |= (1UL << i);
		}
	}
}

bool aprsRxProbeReg(uint8_t i, uint8_t *addr, uint8_t *val)
{
	if (i >= APRS_PROBE_NUM_REGS)
	{
		return false;
	}
	*addr = s_regAddr[i];
	*val = s_probe.regVal[i];
	return stateValid() && (s_probe.regReadMs != 0U) && ((s_probe.regOkMask & (1UL << i)) != 0U);
}

void aprsRxProbeRestartI2S(void)
{
	if (stateValid() && s_probe.engaged && (s_probe.scan.active == false))
	{
		i2sStop();
		s_probe.lastTryMs = ticksGetMillis();
		i2sTryStart();   /* регістри не пишемо -- лише новий старт I2S */
	}
}

/* ---- R7: розгортка T_start ------------------------------------------------------- */

#define SCAN_STABLE_MIN   3U   /* найкоротший ряд сусідніх T з однаковим nbits для «авто-фази» */

bool aprsRxProbeScanBest(uint16_t *tFrom, uint16_t *tTo, uint8_t *nbits, uint16_t *centre)
{
	uint32_t bestLen = 0, bestStart = 0;
	uint32_t i = 0;

	while (i < APRS_PROBE_SCAN_N)
	{
		uint8_t c = s_probe.scanCode[i];
		uint32_t j = i + 1U;
		if ((c >= AP_NBITS_MIN) && (c <= AP_NBITS_TRUE16))
		{
			while ((j < APRS_PROBE_SCAN_N) && (s_probe.scanCode[j] == c))
			{
				j++;
			}
			if (((j - i) >= SCAN_STABLE_MIN) && ((j - i) > bestLen))
			{
				bestLen = j - i;
				bestStart = i;
			}
		}
		i = j;
	}
	if (bestLen == 0U)
	{
		return false;
	}
	*tFrom = (uint16_t)(bestStart * APRS_PROBE_T_STEP_US);
	*tTo = (uint16_t)((bestStart + bestLen - 1U) * APRS_PROBE_T_STEP_US);
	*nbits = s_probe.scanCode[bestStart];
	*centre = (uint16_t)((bestStart + (bestLen - 1U) / 2U) * APRS_PROBE_T_STEP_US);   /* середина (для парної довжини -- лівіше) */
	return true;
}

static void scanFinish(bool cancel)
{
	uint16_t from, to, centre;
	uint8_t nb;
	uint16_t t = s_probe.scan.savedT;

	s_probe.scan.active = 0;
	/* «Авто-фаза»: ряд сусідніх T зі стійким nbits -> T_start у його середину; ні -- T до розгортки. */
	if ((cancel == false) && aprsRxProbeScanBest(&from, &to, &nb, &centre))
	{
		t = centre;
	}
	s_probe.tStart = t;
	s_probe.diag.tSetUs = t;
	memset(s_probe.diag.tCnt, 0, sizeof(s_probe.diag.tCnt));
	if (s_probe.engaged)
	{
		i2sStop();
		s_probe.lastTryMs = ticksGetMillis();
		i2sTryStart();
	}
}

void aprsRxProbeScanToggle(void)
{
	if ((stateValid() == false) || (s_probe.engaged == false))
	{
		return;
	}
	if (s_probe.scan.active)
	{
		scanFinish(true);
		return;
	}
	memset(s_probe.scanCode, 0, sizeof(s_probe.scanCode));
	memset(&s_probe.scan, 0, sizeof(s_probe.scan));
	s_probe.scan.savedT = s_probe.tStart;
	s_probe.scan.active = 1;
	s_probe.tStart = 0;
	s_probe.diag.tSetUs = 0;
	memset(s_probe.diag.tCnt, 0, sizeof(s_probe.diag.tCnt));
}

bool aprsRxProbeScanActive(void)
{
	return stateValid() && (s_probe.scan.active != 0U);
}

void aprsRxProbeScanProgress(uint8_t *idx, uint8_t *rep)
{
	*idx = s_probe.scan.idx;
	*rep = s_probe.scan.rep;
}

uint8_t aprsRxProbeScanCode(uint8_t idx)
{
	return (stateValid() && (idx < APRS_PROBE_SCAN_N)) ? s_probe.scanCode[idx] : 0U;
}

/* Один крок автомата розгортки (з тіку): перезапуск I2S з поточним T -> чекаємо вердикт детектора
 * (<= 400 мс) -> записуємо -> наступний перезапуск; після APRS_PROBE_SCAN_REPS -- наступний T. */
static void scanStep(uint32_t now)
{
	aprsScan_t *sc = &s_probe.scan;

	if (sc->active == 0U)
	{
		return;
	}
	if (sc->phase == 0U)
	{
		i2sStop();
		s_probe.lastTryMs = now;
		i2sTryStart();
		sc->t0 = ticksGetMillis();
		sc->phase = 1;
		return;
	}

	bool have = s_probe.i2sRunning && (s_probe.det.nbits != 0U);
	if ((have == false) && ((now - sc->t0) < APRS_PROBE_SCAN_WAIT_MS))
	{
		return;
	}
	if (have)
	{
		uint8_t nb = s_probe.det.nbits;
		if (sc->nVerd == 0U)
		{
			sc->first = nb;
		}
		else if (nb != sc->first)
		{
			sc->mixed = 1;
		}
		if (sc->nVerd < 255U)
		{
			sc->nVerd++;
		}
		uint8_t *cnt = &s_probe.diag.tCnt[tCntBucket(nb)];
		if (*cnt < 255U)
		{
			(*cnt)++;
		}
	}
	sc->rep++;
	sc->phase = 0;
	if (sc->rep >= APRS_PROBE_SCAN_REPS)
	{
		s_probe.scanCode[sc->idx] = (sc->nVerd == 0U) ? APRS_PROBE_SCAN_NONE :
				(((sc->mixed != 0U) || (sc->nVerd < APRS_PROBE_SCAN_REPS)) ? APRS_PROBE_SCAN_MIXED : sc->first);
		sc->idx++;
		sc->rep = 0;
		sc->first = 0;
		sc->mixed = 0;
		sc->nVerd = 0;
		if (sc->idx >= APRS_PROBE_SCAN_N)
		{
			scanFinish(false);
			return;
		}
		s_probe.tStart = (uint16_t)(sc->idx * APRS_PROBE_T_STEP_US);
		s_probe.diag.tSetUs = s_probe.tStart;
		memset(s_probe.diag.tCnt, 0, sizeof(s_probe.diag.tCnt));
	}
}

void aprsRxProbeToggleNotch(void)
{
	if (stateValid())
	{
		s_probe.notchAuto = !s_probe.notchAuto;
		if (s_probe.notchAuto == false)
		{
			afskSetNotchHz(&s_probe.demod, 0.0f);
			s_probe.notchHz = 0;
		}
	}
}

void aprsRxProbeService(void)
{
	if (stateValid() == false)
	{
		return;
	}

	if (isFmRx() == false)
	{
		disengage();
		s_probe.status = APRS_PROBE_ST_NOT_FM;
		return;
	}
	if (s_probe.engaged == false)
	{
		engage();
		return;
	}

	uint32_t now = ticksGetMillis();
	bool prompt = voicePromptsIsPlaying();
	bool melody = soundMelodyIsPlaying();
	bool rf = ((audioAmpGetStatus() & AUDIO_AMP_CHANNEL_RF) != 0);

	/* R6: події, після яких стоковий код переписує регістри кодека (розділ 10.3): відкриття
	 * шумодава -- radioSetAudioPath(true) (0x36, 0x10); біп -- 0x36 і 0x06; підказка -- 0x36, 0x10. */
	if (rf && (s_probe.lastRf == false))
	{
		s_probe.evSqOpen++;
	}
	else if ((rf == false) && s_probe.lastRf)
	{
		s_probe.evSqClose++;
	}
	if (melody && (s_probe.lastMelody == false))
	{
		s_probe.evBeep++;
	}
	if (prompt && (s_probe.lastPrompt == false))
	{
		s_probe.evPrompt++;
	}

	/* Голосова підказка має пріоритет: віддаємо їй I2S і чекаємо. */
	if (prompt)
	{
		i2sStop();
		s_probe.status = APRS_PROBE_ST_BUSY;
	}
	else
	{
		/* Стоковий код переписує 0x36/0x10 на початку прийому (trx.c), на біпах (sound.c) і на
		 * підказках (voicePrompts.c) -- повертаємо регістри варіанта одразу після таких подій.
		 * R4: періодичне перезаписування раз на 250 мс прибрано -- [гіпотеза] запис 0x10 (режим)
		 * посеред прийому може скидати тракт HR-C6000, а штатний А1 його й не потребує. */
		if ((melody == false) && ((rf != s_probe.lastRf) || s_probe.lastMelody || s_probe.lastPrompt) && (s_probe.scan.active == 0U))
		{
			regsApplyVariant();   /* R7: під час розгортки T_start регістри кодека не пишемо */
		}

		/* I2S міг зупинити хтось інший (soundTerminateSound() тощо) -- тоді перезапуск. */
		if (s_probe.i2sRunning && (I2SProbeIsRunning() == false))
		{
			s_probe.i2sRunning = false;
			s_probe.status = APRS_PROBE_ST_WAIT;
		}

		if ((s_probe.i2sRunning == false) && ((now - s_probe.lastTryMs) >= APRS_PROBE_RETRY_MS))
		{
			s_probe.lastTryMs = now;
			i2sTryStart();
		}
	}

	/* Обробка накопичених блоків. */
	for (uint32_t k = 0; (k < APRS_PROBE_BLOCKS_PER_TICK) && s_probe.i2sRunning && (s_probe.tail != s_probe.head); k++)
	{
		uint8_t t = s_probe.tail;
		__DMB();
		/* R7: відлік для обробки -- nbits бітів, зведені до масштабу 10 біт (apSampleN); кільце
		 * лишається сирим, бо з нього ж читає USB-запис. */
		int16_t x[APRS_PROBE_BLOCK];
		const uint16_t *src = APRS_PROBE_RING_BASE + ((uint32_t)t * (s_probe.stereo ? (2U * APRS_PROBE_BLOCK) : APRS_PROBE_BLOCK));
		int stride = s_probe.stereo ? 2 : 1;
		/* Детектор рахує завжди (і в ручних режимах -- щоб бачити, що він каже); посеред кадру
		 * демодулятора nbits не міняється. */
		{
			uint8_t effBefore = effNbits();
			uint8_t known = s_probe.det.nbits;
			if (apFmtDetBlock(&s_probe.det, src, stride, APRS_PROBE_BLOCK, (s_probe.demod.inFrame != 0)))
			{
				if (known == 0U)
				{
					uint8_t *cnt = &s_probe.diag.tCnt[tCntBucket(s_probe.det.nbits)];   /* вердикт після (пере)запуску */
					if ((*cnt < 255U) && (s_probe.scan.active == 0U))
					{
						(*cnt)++;
					}
				}
				if (effNbits() != effBefore)
				{
					/* формат змінився: усе, що демодулятор і розгортка набрали досі, -- з іншого формату */
					dspReset();
				}
			}
		}
		apFmtExtract(&s_probe.var[s_probe.variant].fmt, src, stride, APRS_PROBE_BLOCK, effNbits(), x);
		processBlock(x);
		s_probe.tail = (uint8_t)((t + 1U) % s_probe.slots);
	}
	if (s_probe.i2sRunning)
	{
		measureFs();

		/* R7: SR веденого I2S (SPI3) і I2S3ext раз на тік. FRE («WS змінився в неочікуваний момент»)
		 * скидається читанням SR -- рахуємо опитування з FRE за останню секунду (R6 рахував усю
		 * сесію, і лічильник завжди насичувався). Раз на секунду -- регістри SPI3/I2S3ext. */
		uint32_t sr = I2SProbeStatusRegs();
		aprsProbeDiag_t *g = &s_probe.diag;
		g->sr[0] = (uint16_t)(sr & 0xFFFFU);
		g->sr[1] = (uint16_t)(sr >> 16);
		if (g->sr[0] & SPI_SR_FRE)
		{
			g->freRxCur++;
		}
		if (g->sr[1] & SPI_SR_FRE)
		{
			g->freTxCur++;
		}
		g->srErrCur[0] |= (uint16_t)(g->sr[0] & (SPI_SR_UDR | SPI_SR_OVR | SPI_SR_FRE));
		g->srErrCur[1] |= (uint16_t)(g->sr[1] & (SPI_SR_UDR | SPI_SR_OVR | SPI_SR_FRE));
		if ((now - g->secMs) >= 1000U)
		{
			g->secMs = now;
			g->freRxSec = g->freRxCur;
			g->freTxSec = g->freTxCur;
			g->freRxCur = g->freTxCur = 0;
			g->srErr[0] = g->srErrCur[0];
			g->srErr[1] = g->srErrCur[1];
			g->srErrCur[0] = g->srErrCur[1] = 0;
			I2SProbeRegs(g->regs);
			g->regsValid = 1;
		}
	}

	scanStep(now);

	/* ПК перестав забирати блоки (закрили програму, витягли кабель) -- запис зупиняємо, інакше
	 * повне кільце (usbTail стоїть) губило б усі блоки й демодулятору. */
	if (s_probe.capActive && ((now - s_probe.capPollMs) > APRS_PROBE_USB_IDLE_MS))
	{
		s_probe.capActive = false;
		s_probe.capDone = true;
	}

	s_probe.lastRf = rf;
	s_probe.lastMelody = melody;
	s_probe.lastPrompt = prompt;
}

/* ---- USB-запис сирих відліків (R4) ---------------------------------------------------- *
 * Опкод CPS 'C' 0xB5 (usb_com.c). Запит: [ 'C', 0xB5, sub, ... ]:
 *   sub 0 -- стан; sub 1 -- старт: [3] = режим (0 -- L, 16 біт; 1 -- L,R як у кадрі I2S),
 *            [4..5] = секунди (BE, 1..120); sub 2 -- читати блоки; sub 3 -- стоп.
 * Відповідь (після [cmd, len_hi, len_lo] у usb_com.c), усе LE:
 *   [0] версія, [1] стан (0 -- гаразд, 1 -- екран проби закрито, 2 -- не FM, 3 -- I2S не йде,
 *   4 -- запису немає), [2] прапорці (біт0 -- йде, біт1 -- завершено, біт2 -- L,R),
 *   [3] варіант (№ з R2), [4..5] блоків у відповіді, [6..9] надіслано блоків усього,
 *   [10..13] втрачено блоків (кільце переповнилось), [14..15] замовлено блоків,
 *   [16..17] виміряна fs, Гц (0 -- ще ні), [18..19] 0;
 *   далі блоки: [номер блока u32][160 x int16 L] або [номер u32][320 x int16 L,R].
 * Запис іде потоком через те саме кільце -- увесь запис ніде не зберігається. */
static void put16(volatile uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
}

static void put32(volatile uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
	p[2] = (uint8_t)(v >> 16);
	p[3] = (uint8_t)(v >> 24);
}

int aprsRxProbeUsb(const volatile uint8_t *req, int reqLen, volatile uint8_t *out, int outMax)
{
	uint8_t sub = (reqLen > 2) ? req[2] : 0;
	uint8_t status = 0;
	uint32_t nBlocks = 0;
	int n = APRS_PROBE_USB_HDR;

	if (outMax < (int)APRS_PROBE_USB_HDR)
	{
		return 0;
	}
	if (stateValid())
	{
		s_probe.capPollMs = ticksGetMillis();
	}

	if (stateValid() == false)
	{
		status = 1;
	}
	else if (s_probe.status == APRS_PROBE_ST_NOT_FM)
	{
		status = 2;
	}

	if ((status == 0) && (sub == 1))
	{
		if (s_probe.i2sRunning == false)
		{
			status = 3;
		}
		else
		{
			uint32_t secs = (reqLen > 5) ? (((uint32_t)req[4] << 8) | req[5]) : 15U;
			if (secs < 1U) { secs = 1U; }
			if (secs > APRS_PROBE_USB_MAX_SECS) { secs = APRS_PROBE_USB_MAX_SECS; }
			/* Новий розклад кільця: на час зміни переривання блок пропускає (i2sRunning). */
			s_probe.i2sRunning = false;
			__DMB();
			s_probe.capStereo = ((reqLen > 3) && (req[3] & 1)) ? 1 : 0;
			s_probe.capTotal = (uint16_t)(secs * 50U);
			s_probe.capSent = 0;
			s_probe.capLost = 0;
			s_probe.capDone = false;
			s_probe.capActive = true;
			s_probe.seqCounter = 0;
			ringLayout(s_probe.capStereo != 0);
			__DMB();
			s_probe.i2sRunning = true;
		}
	}
	else if ((status == 0) && (sub == 2))
	{
		if ((s_probe.capActive == false) && (s_probe.capDone == false))
		{
			status = 4;
		}
		else
		{
			uint32_t words = s_probe.stereo ? (2U * APRS_PROBE_BLOCK) : APRS_PROBE_BLOCK;
			uint32_t bsize = 4U + (words * 2U);
			while (s_probe.capActive && (s_probe.usbTail != s_probe.head) && ((uint32_t)n + bsize <= (uint32_t)outMax))
			{
				uint8_t t = s_probe.usbTail;
				const uint16_t *src = APRS_PROBE_RING_BASE + ((uint32_t)t * words);
				put32(&out[n], s_probe.slotSeq[t]);
				n += 4;
				for (uint32_t i = 0; i < words; i++)
				{
					put16(&out[n], src[i]);
					n += 2;
				}
				s_probe.usbTail = (uint8_t)((t + 1U) % s_probe.slots);
				nBlocks++;
				if (++s_probe.capSent >= s_probe.capTotal)
				{
					s_probe.capActive = false;
					s_probe.capDone = true;
				}
			}
		}
	}
	else if (sub == 3)
	{
		if (stateValid())
		{
			s_probe.capActive = false;
			s_probe.capDone = true;
		}
	}

	out[0] = APRS_PROBE_USB_VER;
	out[1] = status;
	out[2] = (uint8_t)((stateValid() && s_probe.capActive ? 1U : 0U) | (stateValid() && s_probe.capDone ? 2U : 0U) |
			(stateValid() && s_probe.capStereo ? 4U : 0U));
	out[3] = stateValid() ? s_variants[s_probe.variant][3] : 0;
	put16(&out[4], nBlocks);
	put32(&out[6], stateValid() ? s_probe.capSent : 0U);
	put32(&out[10], stateValid() ? s_probe.capLost : 0U);
	put16(&out[14], stateValid() ? s_probe.capTotal : 0U);
	put16(&out[16], stateValid() ? s_probe.fsHz : 0U);
	put16(&out[18], 0U);
	return n;
}

#endif /* APRS_RX_PROBE */
