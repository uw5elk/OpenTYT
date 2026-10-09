/*
 * aprs_rx_probe.c -- діагностика R2 «APRS проба»: джерела звуку для вимірювань.
 * Опис і обмеження -- у aprs_rx_probe.h, план перевірки -- docs/aprs-rx-feasibility.md
 * (розділ 3 і «Результати проби»), кроки -- TESTING.md, блок AD.
 *
 * Що чіпаємо і як повертаємо:
 *   - регістри HR-C6000 0xE0, 0x36, 0x10 (сторінка 4): на вході ЧИТАЄМО поточні значення
 *     й на виході пишемо саме їх (якщо читання неправдоподібне -- штатні FM: 0x89/0x02/0x80);
 *     після цього, якщо зараз іде прийом (підсилювач RF увімкнено), -- radioSetAudioPath(true),
 *     як це робить trx.c на початку прийому;
 *   - I2S3: лише через I2SProbeStart/Stop (i2s.c), прапорці повертаються в «вільно»;
 *   - PC3 (MODER/PUPDR), ADC2, TIM7 (+ його переривання): на виході -- як було до входу,
 *     тактування ADC2/TIM7 вимикається;
 *   - еко-режим приймача: рівень 0 на час проби, потім -- попередній.
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

/* Скільки блоків Goertzel в одному вікні показу: 12 x 20 мс = 240 мс (і для I2S, і для АЦП). */
#define APRS_PROBE_BLOCKS_PER_WIN   12U
#define APRS_PROBE_I2S_BLOCK        160U   /* відліків L (або R) у половині буфера I2S */
#define APRS_PROBE_ADC_BLOCK        192U   /* 20 мс при 9600 Гц */
#define APRS_PROBE_REAPPLY_MS       250U
#define APRS_PROBE_RETRY_MS         250U

#define APRS_PROBE_TIM7_IRQ_PRIO    6U

/* Штатні FM-значення -- на випадок, якщо прочитати не вдалося. */
#define REG_E0_FM   0x89
#define REG_36_FM   0x02
#define REG_10_FM   0x80

/* Варіанти А: { 0xE0, 0x36, 0x10 }.
 * А1..А12 -- з R1: 0xE0 x 0x36, режим HR-C6000 FM (0x10 = 0x80).
 * А13..А14 -- додатково: 0x10 = 0x6E, як під час голосових підказок (radioSetAudioPath(false)).
 *   Якщо у FM-режимі такту WS немає взагалі, ці два варіанти покажуть, чи є він хоча б так.
 * У варіантах з 0xE0 = 0xC9 мікрофон увімкнено -- свист у СВІЙ мікрофон перевіряє, що сам
 * I2S-шлях живий (TESTING.md, AD2). */
static const uint8_t s_variantsA[APRS_PROBE_NUM_I2S_VARIANTS][3] =
{
	{ 0x89, 0x02, 0x80 }, { 0x89, 0x10, 0x80 }, { 0x89, 0x12, 0x80 },
	{ 0xC9, 0x02, 0x80 }, { 0xC9, 0x10, 0x80 }, { 0xC9, 0x12, 0x80 },
	{ 0x8B, 0x02, 0x80 }, { 0x8B, 0x10, 0x80 }, { 0x8B, 0x12, 0x80 },
	{ 0x83, 0x02, 0x80 }, { 0x83, 0x10, 0x80 }, { 0x83, 0x12, 0x80 },
	{ 0xC9, 0x00, 0x6E }, { 0x89, 0x00, 0x6E }
};

typedef struct
{
	uint32_t          magic;        /* APRS_PROBE_MAGIC -- екран відкрито */
	uint8_t           variant;
	uint8_t           status;       /* aprsProbeStatus_t */
	bool              engaged;      /* регістри збережено, джерело вибрано (лише у FM) */
	bool              i2sRunning;
	bool              adcRunning;
	bool              readOk;
	uint8_t           savedE0, saved36, saved10;
	int               savedEco;
	uint32_t          savedModer, savedPupdr;   /* біти PC3 */
	bool              lastRf, lastMelody;
	uint32_t          lastApplyMs, lastTryMs;
	volatile uint32_t lastResultMs;
	apChan_t          ch[2];
	volatile uint32_t seq;          /* непарне -- ISR саме пише res[] */
	apResult_t        res[2];
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

aprsProbeStatus_t aprsRxProbeStatus(void)
{
	return stateValid() ? (aprsProbeStatus_t)s_probe.status : APRS_PROBE_ST_IDLE;
}

bool aprsRxProbeVariantRegs(uint8_t v, uint8_t *e0, uint8_t *r36, uint8_t *r10)
{
	if (v >= APRS_PROBE_NUM_I2S_VARIANTS)
	{
		return false;
	}
	*e0 = s_variantsA[v][0];
	*r36 = s_variantsA[v][1];
	*r10 = s_variantsA[v][2];
	return true;
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

/* ---- результати (ISR -> екран, seqlock) ---------------------------------- */

static void publish(const apResult_t *r0, const apResult_t *r1)
{
	s_probe.seq++;
	__DMB();
	s_probe.res[0] = *r0;
	if (r1 != NULL)
	{
		s_probe.res[1] = *r1;
	}
	else
	{
		memset(&s_probe.res[1], 0, sizeof(apResult_t));
	}
	__DMB();
	s_probe.seq++;
	s_probe.lastResultMs = ticksGetMillis();
}

bool aprsRxProbeResult(apResult_t out[2], uint32_t *seq)
{
	if (stateValid() == false)
	{
		return false;
	}
	uint32_t s1 = s_probe.seq;
	if ((s1 & 1U) || (s1 == *seq))
	{
		return false;
	}
	__DMB();
	out[0] = s_probe.res[0];
	out[1] = s_probe.res[1];
	__DMB();
	if (s_probe.seq != s1)
	{
		return false;   /* ISR переписав посеред копіювання -- візьмемо наступного разу */
	}
	*seq = s1;
	return true;
}

uint32_t aprsRxProbeMsSinceResult(void)
{
	return ticksGetMillis() - s_probe.lastResultMs;
}

/* ---- джерело А: I2S --------------------------------------------------------- */

void aprsRxProbeI2SBlock(uint32_t bufNum)
{
	apResult_t rl, rr;
	bool doneL = false, doneR = false;

	if ((stateValid() == false) || (s_probe.i2sRunning == false) || (bufNum >= NUM_I2S_BUFFERS))
	{
		return;
	}

	/* Половина буфера: 2 x 160 півслів = 160 стерео-кадрів (L, R), 20 мс при 8 кГц.
	 * Розкладка та сама, що читає soundReceiveRefillData() (лівий канал -- парні). */
	for (int j = 0; j < 2; j++)
	{
		for (int i = 0; i < (WAV_BUFFER_SIZE / 2); i++)
		{
			int16_t l = (int16_t)i2s_Rx_Buffer[bufNum][j][2 * i];
			int16_t r = (int16_t)i2s_Rx_Buffer[bufNum][j][(2 * i) + 1];
			doneL |= apChanPush(&s_probe.ch[0], l, &rl);
			doneR |= apChanPush(&s_probe.ch[1], r, &rr);
		}
	}

	if (doneL)
	{
		publish(&rl, doneR ? &rr : NULL);
	}
}

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

	apChanInit(&s_probe.ch[0], AP_FS_I2S, APRS_PROBE_I2S_BLOCK, APRS_PROBE_BLOCKS_PER_WIN, 0);
	apChanInit(&s_probe.ch[1], AP_FS_I2S, APRS_PROBE_I2S_BLOCK, APRS_PROBE_BLOCKS_PER_WIN, 0);
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

/* ---- джерело Б: PC3 / ADC2 / TIM7 ---------------------------------------------- */

#define PC3_MODER_MASK  (3UL << (3 * 2))
#define PC3_PUPDR_MASK  (3UL << (3 * 2))
#define ADC_SMP13_POS   9U          /* SMPR1: канал 13 -- біти 11:9 */
#define ADC_SMP_144CYC  6UL

void TIM7_IRQHandler(void)
{
	TIM7->SR = ~TIM_SR_UIF;

	if ((stateValid() == false) || (s_probe.adcRunning == false))
	{
		return;
	}

	if (ADC2->SR & ADC_SR_EOC)
	{
		apResult_t r;
		int32_t x = (int32_t)(ADC2->DR & 0x0FFFU);   /* читання DR скидає EOC */
		if (apChanPush(&s_probe.ch[0], x, &r))
		{
			publish(&r, NULL);
		}
	}
	ADC2->CR2 |= ADC_CR2_SWSTART;   /* наступне перетворення; результат -- у наступному перериванні */
}

static void adcStart(void)
{
	apChanInit(&s_probe.ch[0], AP_FS_ADC, APRS_PROBE_ADC_BLOCK, APRS_PROBE_BLOCKS_PER_WIN, 2048);

	/* PC3 -- аналоговий вхід без підтяжок (до цього -- як після скиду, ніде не налаштовано). */
	s_probe.savedModer = GPIOC->MODER & PC3_MODER_MASK;
	s_probe.savedPupdr = GPIOC->PUPDR & PC3_PUPDR_MASK;
	GPIOC->PUPDR &= ~PC3_PUPDR_MASK;
	GPIOC->MODER |= PC3_MODER_MASK;

	/* ADC2: 12 біт, одне перетворення каналу 13, запуск програмно. Подільник тактів -- спільний
	 * з ADC1 (ADC->CCR, MX_ADC1_Init), його не чіпаємо. */
	__HAL_RCC_ADC2_CLK_ENABLE();
	ADC2->CR1 = 0;
	ADC2->CR2 = 0;
	ADC2->SQR1 = 0;
	ADC2->SQR2 = 0;
	ADC2->SQR3 = 13;
	ADC2->SMPR1 = (ADC2->SMPR1 & ~(7UL << ADC_SMP13_POS)) | (ADC_SMP_144CYC << ADC_SMP13_POS);
	ADC2->CR2 = ADC_CR2_ADON;
	for (volatile int i = 0; i < 200; i++)
	{
		/* tSTAB ~3 мкс */
	}
	ADC2->CR2 |= ADC_CR2_SWSTART;

	/* TIM7: переривання 9600 разів на секунду. Такт таймерів APB1 = 2 x PCLK1, якщо APB1 ділиться. */
	uint32_t pclk1 = HAL_RCC_GetPCLK1Freq();
	uint32_t timClk = ((RCC->CFGR & RCC_CFGR_PPRE1) == RCC_CFGR_PPRE1_DIV1) ? pclk1 : (2U * pclk1);
	__HAL_RCC_TIM7_CLK_ENABLE();
	TIM7->CR1 = 0;
	TIM7->PSC = 0;
	TIM7->ARR = ((timClk + (APRS_PROBE_ADC_FS / 2U)) / APRS_PROBE_ADC_FS) - 1U;
	TIM7->EGR = TIM_EGR_UG;
	TIM7->SR = 0;
	TIM7->DIER = TIM_DIER_UIE;
	HAL_NVIC_SetPriority(TIM7_IRQn, APRS_PROBE_TIM7_IRQ_PRIO, 0);
	HAL_NVIC_ClearPendingIRQ(TIM7_IRQn);
	s_probe.adcRunning = true;
	HAL_NVIC_EnableIRQ(TIM7_IRQn);
	TIM7->CR1 = TIM_CR1_CEN;

	s_probe.status = APRS_PROBE_ST_RUNNING;
}

static void adcStop(void)
{
	if (s_probe.adcRunning == false)
	{
		return;
	}
	TIM7->CR1 = 0;
	TIM7->DIER = 0;
	HAL_NVIC_DisableIRQ(TIM7_IRQn);
	TIM7->SR = 0;
	HAL_NVIC_ClearPendingIRQ(TIM7_IRQn);
	s_probe.adcRunning = false;
	__HAL_RCC_TIM7_CLK_DISABLE();

	ADC2->CR2 = 0;
	__HAL_RCC_ADC2_CLK_DISABLE();

	GPIOC->MODER = (GPIOC->MODER & ~PC3_MODER_MASK) | s_probe.savedModer;
	GPIOC->PUPDR = (GPIOC->PUPDR & ~PC3_PUPDR_MASK) | s_probe.savedPupdr;
}

/* ---- регістри HR-C6000 --------------------------------------------------- */

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
	if (s_probe.variant < APRS_PROBE_NUM_I2S_VARIANTS)
	{
		regsWrite(s_variantsA[s_probe.variant][0], s_variantsA[s_probe.variant][1], s_variantsA[s_probe.variant][2]);
	}
	s_probe.lastApplyMs = ticksGetMillis();
}

/* ---- керування ------------------------------------------------------------ */

static void sourceStop(void)
{
	i2sStop();
	adcStop();
}

static void sourceStart(void)
{
	sourceStop();
	s_probe.seq += 2;                 /* старі результати -- недійсні для екрана */
	memset(s_probe.res, 0, sizeof(s_probe.res));
	s_probe.lastResultMs = ticksGetMillis();

	if (s_probe.variant < APRS_PROBE_NUM_I2S_VARIANTS)
	{
		regsApplyVariant();
		s_probe.lastTryMs = ticksGetMillis();
		i2sTryStart();
	}
	else
	{
		/* Б: регістри -- штатні (ті, що були на вході). */
		regsWrite(s_probe.savedE0, s_probe.saved36, s_probe.saved10);
		adcStart();
	}
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
		sourceStop();
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
		sourceStart();
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

	if (s_probe.variant < APRS_PROBE_NUM_I2S_VARIANTS)
	{
		/* Голосова підказка має пріоритет: віддаємо їй I2S і чекаємо. */
		if (prompt)
		{
			if (s_probe.i2sRunning)
			{
				i2sStop();
			}
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
	}

	s_probe.lastRf = rf;
	s_probe.lastMelody = melody;
}

#endif /* APRS_RX_PROBE */
