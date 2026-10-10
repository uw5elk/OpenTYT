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
 * Поза екраном проби (aprsRxProbeIsOn() == false) жоден шлях DMR/AMBE/FM не змінено.
 */
#include "functions/aprs_rx_probe.h"

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
#define APRS_PROBE_RING             12U    /* блоків у кільці: 240 мс запасу на повільний тік */
#define APRS_PROBE_BLOCKS_PER_TICK  2U     /* обробка за один тік (~0,5 мс на блок при 72 МГц) */
#define APRS_PROBE_REAPPLY_MS       250U
#define APRS_PROBE_RETRY_MS         250U
#define APRS_PROBE_NOTCH_QUIET      100U   /* блоків (2 с) без серій прапорців -- можна міняти режекцію */
#define APRS_PROBE_FS_MIN_MS        5000U  /* частоту дискретизації показуємо після 5 с */

/* Кільце блоків -- у буфері звуку AMBE/підказок/хотспоту (4800 Б, CCM). У FM-прийомі з
 * пробою він простоює: DMR немає, хотспот вимкнено, а на час голосової підказки I2S проби
 * зупиняється і кільце після неї починається спочатку. */
#define APRS_PROBE_RING_BUF   ((int16_t (*)[APRS_PROBE_BLOCK])(void *)&audioAndHotspotDataBuffer)
_Static_assert(sizeof(audioAndHotspotDataBuffer) >= (APRS_PROBE_RING * APRS_PROBE_BLOCK * sizeof(int16_t)),
		"probe ring does not fit audioAndHotspotDataBuffer");   /* кільце не вміщається */

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
	/* кільце: пише переривання DMA, читає тік */
	volatile uint8_t  head, tail;
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
	afskDemod_t       demod;
	apBg_t            bg;
	aprsProbeVar_t    var[APRS_PROBE_NUM_VARIANTS];
} aprsProbeState_t;

static aprsProbeState_t s_probe APRS_PROBE_CCM;

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

/* ---- переривання DMA: лише скласти блок у кільце ---------------------------------- */

void aprsRxProbeI2SBlock(uint32_t bufNum)
{
	if ((stateValid() == false) || (s_probe.i2sRunning == false) || (bufNum >= NUM_I2S_BUFFERS))
	{
		return;
	}

	uint8_t h = s_probe.head;
	uint8_t next = (uint8_t)((h + 1U) % APRS_PROBE_RING);
	s_probe.isrBlocks++;
	s_probe.lastBlockMs = ticksGetMillis();
	if (next == s_probe.tail)
	{
		s_probe.overflows++;   /* тік не встигає -- блок губимо, демодулятор переживе як шум */
		return;
	}

	/* Половина буфера: 2 x 160 півслів = 160 стерео-кадрів (L, R), 20 мс при 8 кГц.
	 * Лівий канал -- парні (як у soundReceiveRefillData()); R2: L і R однакові. */
	int16_t *dst = APRS_PROBE_RING_BUF[h];
	int o = 0;
	for (int j = 0; j < 2; j++)
	{
		for (int i = 0; i < (WAV_BUFFER_SIZE / 2); i++)
		{
			dst[o++] = (int16_t)i2s_Rx_Buffer[bufNum][j][2 * i];
		}
	}
	__DMB();
	s_probe.head = next;
}

/* ---- обробка (тік) ---------------------------------------------------------------- */

static void onFrame(const uint8_t *frame, uint16_t len, void *ctx)
{
	(void)ctx;
	aprsProbeVar_t *v = &s_probe.var[s_probe.variant];
	if (ax25Summary(frame, len, v->srcDst, sizeof(v->srcDst), v->info, sizeof(v->info)) == false)
	{
		strcpy(v->srcDst, "?");   /* FCS правильний, але адреси не схожі на AX.25 */
	}
}

static uint16_t clip16(uint32_t v)
{
	return (v > 65535U) ? 65535U : (uint16_t)v;
}

static void processBlock(const int16_t *x)
{
	aprsProbeVar_t *v = &s_probe.var[s_probe.variant];
	afskDemod_t *d = &s_probe.demod;
	apBgResult_t br;

	afskProcess(d, x, APRS_PROBE_BLOCK);

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

static void ringReset(void)
{
	s_probe.head = 0;
	s_probe.tail = 0;
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

static void i2sTryStart(void)
{
	if (voicePromptsIsPlaying() || g_TX_SAI_in_use)
	{
		s_probe.status = APRS_PROBE_ST_BUSY;
		return;
	}

	ringReset();
	dspReset();
	s_probe.i2sRunning = true;   /* до старту: перше переривання може прийти одразу */
	if (I2SProbeStart())
	{
		s_probe.status = APRS_PROBE_ST_RUNNING;
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

	memset(&s_probe, 0, sizeof(s_probe));
	s_probe.magic = APRS_PROBE_MAGIC;
	s_probe.variant = 0;
	s_probe.status = APRS_PROBE_ST_IDLE;
	s_probe.notchAuto = true;
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

	/* Голосова підказка має пріоритет: віддаємо їй I2S і чекаємо. */
	if (prompt)
	{
		i2sStop();
		s_probe.status = APRS_PROBE_ST_BUSY;
	}
	else
	{
		/* Стоковий код переписує 0x36/0x10 на початку прийому (trx.c) і на біпах (sound.c) --
		 * повертаємо регістри варіанта: одразу після таких подій і раз на 250 мс. */
		if ((melody == false) &&
				((rf != s_probe.lastRf) || s_probe.lastMelody || ((now - s_probe.lastApplyMs) >= APRS_PROBE_REAPPLY_MS)))
		{
			regsApplyVariant();
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
		processBlock(APRS_PROBE_RING_BUF[t]);
		s_probe.tail = (uint8_t)((t + 1U) % APRS_PROBE_RING);
	}
	if (s_probe.i2sRunning)
	{
		measureFs();
	}

	s_probe.lastRf = rf;
	s_probe.lastMelody = melody;
}

#endif /* APRS_RX_PROBE */
