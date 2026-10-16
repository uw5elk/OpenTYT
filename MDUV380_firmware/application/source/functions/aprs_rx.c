/*
 * aprs_rx.c -- справжній фоновий приймач APRS (R8). Опис -- у aprs_rx.h, обґрунтування -- docs/
 * aprs-rx-feasibility.md, розділ 12, кроки перевірки -- TESTING.md, блок AJ.
 *
 * Ядро (R3-R7) НЕ змінено: демодулятор AFSK 1200 + AX.25 (aprs_afsk.c), розгортка фону з авто-режекцією
 * і детектор nbits (aprs_probe_dsp.c) -- ті самі, що в діагностичному екрані «APRS проба». Тут лише
 * клей: коли слухати (життєвий цикл), кільце блоків I2S, обробка в головному циклі, розбір кадрів.
 *
 * Обробка НЕ залежить від відкритого екрана: aprsRxTick() кличе applicationMain.c з головного циклу
 * (після aprsBeaconingTick()), а переривання DMA лише копіює блок у кільце. Нічого не блокує UI: за тік
 * обробляється до APRS_RX_BLOCKS_PER_TICK блоків по 20 мс звуку, а єдина довга операція -- запис
 * повідомлення нам у флеш (як і в SMS).
 */
#include "functions/aprs_rx.h"

#if defined(APRS_RX)

#include "main.h"
#include "interfaces/i2s.h"
#include "functions/sound.h"
#include "functions/trx.h"
#include "functions/voicePrompts.h"
#include "functions/rxPowerSaving.h"
#include "functions/ticks.h"
#include "functions/aprs.h"
#include "functions/settings.h"
#include "functions/aprs_afsk.h"
#include "usb/usb_com.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/languages/aprsrx_ua.h"
#include "functions/aprs_mode.h"   /* R10: у «Режимі APRS» приймач слухає власну частоту режиму */
#if defined(ENABLE_CALL_REPLAY)
#include "functions/callReplay.h"
#endif
#if defined(APRS_RX_PROBE)
#include "functions/aprs_rx_probe.h"
#endif
#include <string.h>
#include <stdio.h>

/* Стан лише в CCM (секція .aes_ccmram -- у самому кінці CCM, стокові об'єкти .ccmram не зсуваються).
 * Стартап CCM не обнуляє -- див. aprsRxInit(). */
#define APRS_RX_CCM        __attribute__((section(".aes_ccmram")))
#define APRS_RX_MAGIC      0xA9A5BEEFUL

#define APRS_RX_BLOCK          160U     /* відліків L у половині буфера I2S (20 мс) */
#define APRS_RX_SLOTS          14U      /* 280 мс запасу */
#define APRS_RX_BLOCKS_PER_TICK 2U
#define APRS_RX_RETRY_MS       250U
#define APRS_RX_RETRY_SLOW_MS  2000U    /* після APRS_RX_FAILS_SLOW невдалих стартів поспіль */
#define APRS_RX_FAILS_SLOW     5U
#define APRS_RX_NOTCH_QUIET    100U     /* блоків (2 с) без серій прапорців -- можна міняти режекцію */
#define APRS_RX_WS_PERIOD_US   125U     /* 8 кГц */
#define APRS_RX_FS_MIN_MS      10000U   /* частоту дискретизації міряємо 10 с */
#define APRS_RX_BANNER_MS      3000U
#define APRS_RX_NOTE_TEXT      96

/* Кільце -- у буфері звуку AMBE/підказок/хотспоту (4800 Б). Хто ще його використовує -- розділ 12 docs;
 * на час голосових підказок / «Переслухати» / проби / хотспоту приймач зупинений і кільце не чіпає. */
#define APRS_RX_RING_BASE   ((uint16_t *)(void *)&audioAndHotspotDataBuffer)
_Static_assert(sizeof(audioAndHotspotDataBuffer) >= (APRS_RX_SLOTS * APRS_RX_BLOCK * sizeof(uint16_t)),
		"aprs rx ring does not fit audioAndHotspotDataBuffer");

typedef struct
{
	uint32_t          magic;
	bool              engaged;       /* приймач потрібен (канал APRS тощо), еко-рівень узято */
	volatile bool     i2sRunning;
	bool              ecoForced;
	bool              scaled;        /* перезапуски через nbits вичерпано -- працюємо зі шкалою */
	uint8_t           triesLeft;
	uint8_t           failsInRow;
	uint32_t          freq;          /* частота APRS поточного сеансу (в одиницях rxFreq каналу) */
	uint32_t          lastEvalMs, lastCfgMs, tryAtMs, holdUntilMs;
	/* кільце: пише переривання DMA, читає тік */
	volatile uint8_t  head, tail;
	volatile uint32_t isrBlocks;
	volatile uint32_t lastBlockMs;
	/* калібрування HAL і частота дискретизації */
	uint32_t          halCycles, halPerUs;
	uint32_t          fsT0Ms, fsB0, fsAppliedHz;
	/* DSP (ядро R3-R7) */
	apFmtDet_t        det;
	afskDemod_t       demod;
	apBg_t            bg;
	uint16_t          quiet;
	uint16_t          notchHz;
	/* власний позивний і позиція (оновлюються раз на APRS_RX_CFG_MS) */
	char              ownCall[8];
	uint8_t           ownSsid;
	bool              ownHasPos;
	int32_t           ownLatU, ownLonU;
	/* відкладені дії з кадру: виконуються після блока, а не всередині демодулятора */
	struct
	{
		bool          banner;
		bool          msg;
		uint8_t       type;
		bool          hasGeo;
		uint32_t      distM;
		uint16_t      bearing;
		char          call[APRS_CALL_LEN];
		char          note[APRS_RX_NOTE_TEXT];   /* «CALL: текст» для сховища SMS і картки */
	} pend;
	aprsRxWin_t       win;           /* R13: вікно маяка */
	aprsRxStats_t     st;
	aprsRxUi_t        ui;
	aprsRxDb_t        db;
} aprsRxState_t;

static aprsRxState_t s_rx APRS_RX_CCM;   /* CCM-INIT(aprsRxInit) */

/* ============================================================================================== */
/* Допоміжне                                                                                       */
/* ============================================================================================== */

static inline bool stateValid(void)
{
	return (s_rx.magic == APRS_RX_MAGIC);
}

static void setWhy(aprsRxWhy_t why)
{
	s_rx.st.why = (uint8_t)why;
}

aprsRxUi_t *aprsRxUi(void)
{
	return &s_rx.ui;
}

const aprsRxDb_t *aprsRxDb(void)
{
	return &s_rx.db;
}

const aprsRxStats_t *aprsRxStats(void)
{
	return &s_rx.st;
}

bool aprsRxIsRunning(void)
{
	return stateValid() && s_rx.engaged && s_rx.i2sRunning;
}

bool aprsRxBusy(uint32_t ms)
{
	/* Блок -- 20 мс; «quiet» рахує блоки без серій прапорців. Кадр у розборі або прапорці за останні ms мс. */
	uint32_t blocks = (ms + 19U) / 20U;

	return stateValid() && s_rx.engaged && s_rx.i2sRunning && ((s_rx.demod.inFrame != 0) || (s_rx.quiet < blocks));
}

bool aprsRxOwnPosition(int32_t *latU, int32_t *lonU)
{
	if ((stateValid() == false) || (s_rx.ownHasPos == false))
	{
		return false;
	}
	*latU = s_rx.ownLatU;
	*lonU = s_rx.ownLonU;
	return true;
}

bool aprsRxStationGeo(const aprsStation_t *st, uint32_t *distM, uint16_t *bearing)
{
	if ((st == NULL) || ((st->flags & APRS_ST_HASPOS) == 0U) || (stateValid() == false) || (s_rx.ownHasPos == false))
	{
		return false;
	}
	aprsGeo(s_rx.ownLatU, s_rx.ownLonU, st->latU, st->lonU, distM, bearing);
	return true;
}

uint32_t aprsRxAgeSec(const aprsStation_t *st)
{
	if ((st == NULL) || (st->call[0] == 0))
	{
		return 0xFFFFFFFFUL;
	}
	return (uint32_t)(ticksGetMillis() - st->lastMs) / 1000U;
}

void aprsRxFormatGeo(char *buf, size_t size, uint32_t distM, uint16_t bearing)
{
	/* R20 Ж1: буквений сектор -- лише коли азимут визначений (distM >= APRS_BEARING_MIN_M); відстань показуємо завжди. */
	const char *sector = aprsBearingKnown(distM) ? aprsBearingName(bearing) : "";
	const char *sp = aprsBearingKnown(distM) ? " " : "";

	if (distM < 1000U)
	{
		snprintf(buf, size, "%lu" APRSRX_M "%s%s", (unsigned long)distM, sp, sector);
	}
	else if (distM < 10000U)
	{
		uint32_t t = (distM + 50U) / 100U;   /* десяті частки км */
		snprintf(buf, size, "%lu.%lu" APRSRX_KM " %s", (unsigned long)(t / 10U), (unsigned long)(t % 10U), sector);
	}
	else
	{
		snprintf(buf, size, "%lu" APRSRX_KM " %s", (unsigned long)((distM + 500U) / 1000U), sector);
	}
}

void aprsRxFormatDist(char *buf, size_t size, uint32_t distM)
{
	if (distM < 1000U)
	{
		snprintf(buf, size, "%lu" APRSRX_M, (unsigned long)distM);
	}
	else if (distM < 10000U)
	{
		uint32_t t = (distM + 50U) / 100U;   /* десяті частки км */
		snprintf(buf, size, "%lu.%lu" APRSRX_KM, (unsigned long)(t / 10U), (unsigned long)(t % 10U));
	}
	else
	{
		snprintf(buf, size, "%lu" APRSRX_KM, (unsigned long)((distM + 500U) / 1000U));
	}
}

void aprsRxClear(void)
{
	if (stateValid() == false)
	{
		return;
	}
	aprsDbInit(&s_rx.db);
	aprsHistClear(aprsModeHist());   /* R16: список станцій скинуто -- дані маяків (індекс як у db.st[]) і журнал теж */
	memset(&s_rx.pend, 0, sizeof(s_rx.pend));
	/* лічильники подій -- до нуля, поточні стани лишаємо */
	uint8_t state = s_rx.st.state, why = s_rx.st.why, nbits = s_rx.st.nbits, tries = s_rx.st.triesLeft;
	bool scaled = s_rx.st.scaled;
	memset(&s_rx.st, 0, sizeof(s_rx.st));
	s_rx.st.state = state;
	s_rx.st.why = why;
	s_rx.st.nbits = nbits;
	s_rx.st.triesLeft = tries;
	s_rx.st.scaled = scaled;
	s_rx.det.switches = 0;
}

static uint32_t cyclesPerUs(void)
{
	uint32_t hclk = HAL_RCC_GetHCLKFreq();
	return (hclk >= 1000000U) ? (hclk / 1000000U) : 1U;
}

/* ============================================================================================== */
/* Переривання DMA: лише скласти блок у кільце                                                      */
/* ============================================================================================== */

void aprsRxI2SBlock(uint32_t bufNum)
{
	if ((stateValid() == false) || (s_rx.i2sRunning == false) || (bufNum >= NUM_I2S_BUFFERS))
	{
		return;
	}

	/* Запобіжник: на час голосової підказки / передачі кільце (спільне з wavbuffer) не чіпаємо навіть
	 * якщо тік ще не встиг зупинити приймач. */
	if (voicePromptsIsPlaying() || trxTransmissionEnabled || trxIsTransmitting)
	{
		s_rx.st.gateDrops++;
		return;
	}

	uint8_t h = s_rx.head;
	uint8_t next = (uint8_t)((h + 1U) % APRS_RX_SLOTS);
	s_rx.isrBlocks++;
	s_rx.lastBlockMs = ticksGetMillis();
	if (next == s_rx.tail)
	{
		s_rx.st.overflows++;   /* тік не встигає -- блок губимо; демодулятор переживе як шум */
		return;
	}

	/* Половина буфера: 160 стерео-кадрів (L, R), 20 мс при 8 кГц; лівий канал -- парні півслова. */
	const uint16_t *src = &i2s_Rx_Buffer[bufNum][0][0];
	uint16_t *dst = APRS_RX_RING_BASE + ((uint32_t)h * APRS_RX_BLOCK);
	for (uint32_t i = 0; i < APRS_RX_BLOCK; i++)
	{
		dst[i] = src[2U * i];
	}
	__DMB();
	s_rx.head = next;
}

/* ============================================================================================== */
/* DSP                                                                                             */
/* ============================================================================================== */

/* R16: вікно = запис маяка (ті самі поля, ПЕРШІ в структурі) + active + call: відкриття вікна станції -- один memcpy запису. Хвостове вирівнювання запису
 * може накрити байт active -- тому active і call завжди виставляються ПІСЛЯ memcpy (winOpenFromRec(), frameDispatch()). */
_Static_assert(sizeof(aprsRxWin_t) >= sizeof(aprsBcnRec_t), "aprsRxWin_t must be able to hold the aprsBcnRec_t fields");
_Static_assert(offsetof(aprsRxWin_t, hasGeo) == offsetof(aprsBcnRec_t, hasGeo) && offsetof(aprsRxWin_t, text) == offsetof(aprsBcnRec_t, text) && offsetof(aprsRxWin_t, symCode) == offsetof(aprsBcnRec_t, symCode),
		"aprsRxWin_t and aprsBcnRec_t field layout must match");

static void frameDispatch(const uint8_t *frame, uint16_t len);

static void onFrame(const uint8_t *frame, uint16_t len, bool fcsOk, void *ctx)
{
	(void)ctx;
	if (fcsOk == false)
	{
		s_rx.st.framesBad++;
		return;
	}
	s_rx.st.framesOk++;
	frameDispatch(frame, len);
}

/* nbits, яким обробляється зараз: вердикт детектора; поки його нема -- 16 (початок обрано так, щоб формат
 * був справжній 16-бітний, R7). */
static uint8_t effNbits(void)
{
	return (s_rx.det.nbits != 0U) ? s_rx.det.nbits : (uint8_t)AP_NBITS_TRUE16;
}

/* Демодулятор і розгортка -- з нуля (новий старт I2S / змінився формат). Режекція -- заново з фону. */
static void dspReset(void)
{
	afskInit(&s_rx.demod, onFrame, NULL);
	if (s_rx.fsAppliedHz != 0U)
	{
		afskSetSampleRate(&s_rx.demod, s_rx.fsAppliedHz);
	}
	apBgInit(&s_rx.bg);
	s_rx.notchHz = 0;
	s_rx.quiet = APRS_RX_NOTCH_QUIET;
}

static void processBlock(const int16_t *x)
{
	afskDemod_t *d = &s_rx.demod;
	apBgResult_t br;

	afskProcess(d, x, (int)APRS_RX_BLOCK);

	if (d->nFlagSeq != 0)
	{
		s_rx.quiet = 0;
	}
	else if (s_rx.quiet < 0xFFFFU)
	{
		s_rx.quiet++;
	}
	d->nOk = d->nBad = d->nFlagSeq = 0;

	if (apBgBlock(&s_rx.bg, x, &br))
	{
		/* Режекція -- лише поза пакетами (2 с без серій прапорців і не посеред кадру): інакше розгортка
		 * бачила б тони самого APRS. Частоту дає розгортка (уточнена до ~1 Гц). */
		if ((s_rx.quiet >= APRS_RX_NOTCH_QUIET) && (d->inFrame == 0))
		{
			float hz = apBgNotchHz(&br);
			uint16_t ihz = (uint16_t)(hz + 0.5f);
			if (ihz != s_rx.notchHz)
			{
				afskSetNotchHz(d, hz);
				s_rx.notchHz = ihz;
			}
		}
	}
	s_rx.st.blocks++;
}

static void measureFs(void)
{
	uint32_t b = s_rx.isrBlocks;

	if (s_rx.fsT0Ms == 0U)
	{
		if (b > 0U)
		{
			s_rx.fsT0Ms = (s_rx.lastBlockMs != 0U) ? s_rx.lastBlockMs : 1U;
			s_rx.fsB0 = b;
		}
		return;
	}

	uint32_t dt = s_rx.lastBlockMs - s_rx.fsT0Ms;   /* від блока до блока -- без похибки тіку */
	if (dt >= APRS_RX_FS_MIN_MS)
	{
		uint64_t samples = (uint64_t)(b - s_rx.fsB0) * APRS_RX_BLOCK;
		uint32_t fs = (uint32_t)((samples * 1000U + (dt / 2U)) / dt);
		s_rx.st.fsHz = fs;
		/* Поправка тактів демодулятора -- лише коли відхилення помітне (> 0,1 %) і правдоподібне. */
		if ((fs != s_rx.fsAppliedHz) && ((fs < 7992U) || (fs > 8008U) || (s_rx.fsAppliedHz != 0U)))
		{
			afskSetSampleRate(&s_rx.demod, fs);
			s_rx.fsAppliedHz = fs;
		}
		/* нове вікно, щоб значення не застарівало за довгий сеанс */
		s_rx.fsT0Ms = s_rx.lastBlockMs;
		s_rx.fsB0 = b;
	}
}

/* ============================================================================================== */
/* I2S                                                                                             */
/* ============================================================================================== */

static void i2sStop(void)
{
	if (s_rx.i2sRunning)
	{
		s_rx.i2sRunning = false;
		I2SProbeAbort();
	}
}

static void ringReset(void)
{
	s_rx.head = 0;
	s_rx.tail = 0;
	s_rx.isrBlocks = 0;
	s_rx.lastBlockMs = ticksGetMillis();
	s_rx.fsT0Ms = 0;
	s_rx.fsB0 = 0;
}

/* Запуск I2S з детермінованою фазою (R7, i2s.c): I2SE вмикається через APRS_RX_T_START_US після фронту WS.
 * Перший запуск спершу двічі міряє тривалість HAL (старт-стоп без затримки). Повертає причину невдачі або
 * APRS_RX_WHY_NONE. */
static aprsRxWhy_t i2sTryStart(void)
{
	if (voicePromptsIsPlaying() || g_TX_SAI_in_use || isSending || isReceiving)
	{
		return APRS_RX_WHY_BUSY;
	}

	uint32_t perUs = cyclesPerUs();
	uint32_t period = perUs * APRS_RX_WS_PERIOD_US;
	uint32_t tCyc = (uint32_t)APRS_RX_T_START_US * perUs;
	uint32_t act = 0, ws = 0;
	bool ok = true;

	if ((s_rx.halCycles == 0U) || (s_rx.halPerUs != perUs))
	{
		/* калібрування: два старт-стопи без затримки; тривалість HAL беремо з другого (код уже в кеші) */
		for (int pass = 0; (pass < 2) && ok; pass++)
		{
			uint32_t h = 0;
			ok = I2SProbeStart(0U, period, &h, &act, &ws);
			if (ok)
			{
				I2SProbeAbort();
				s_rx.halCycles = h;
				s_rx.halPerUs = perUs;
			}
		}
	}

	ringReset();
	dspReset();
	apFmtDetRestart(&s_rx.det);   /* новий старт -- новий формат: вердикт забуто */
	if (ok)
	{
		s_rx.i2sRunning = true;   /* до старту: перше переривання може прийти одразу */
		ok = I2SProbeStart(tCyc, period, &s_rx.halCycles, &act, &ws);
	}

	if (ok == false)
	{
		s_rx.i2sRunning = false;
		return (g_TX_SAI_in_use ? APRS_RX_WHY_BUSY : APRS_RX_WHY_NO_WS);
	}

	s_rx.st.starts++;
	s_rx.st.tMeasUs = (uint16_t)(act / perUs);
	s_rx.st.halUs = (uint16_t)(s_rx.halCycles / perUs);
	(void)I2SProbeStatusRegs();   /* скинути FRE, що лишився з попереднього сеансу */
	return APRS_RX_WHY_NONE;
}

/* ============================================================================================== */
/* Життєвий цикл                                                                                   */
/* ============================================================================================== */

/* Умови, які зупиняють приймач НЕГАЙНО (дешеві перевірки щотіку). */
static aprsRxWhy_t hardBlock(void)
{
	if (trxTransmissionEnabled || trxIsTransmitting || (aprsTxProgress != APRS_TX_IDLE))
	{
		return APRS_RX_WHY_TX;
	}
	if (voicePromptsIsPlaying())
	{
		return APRS_RX_WHY_PROMPT;
	}
#if defined(ENABLE_CALL_REPLAY)
	if (callReplayIsPlaying())
	{
		return APRS_RX_WHY_REPLAY;
	}
#endif
#if defined(APRS_RX_PROBE)
	if (aprsRxProbeIsOn())
	{
		return APRS_RX_WHY_PROBE;
	}
#endif
	switch (menuSystemGetCurrentMenuNumber())
	{
		case UI_HOTSPOT_MODE:
		case UI_CPS:
		case UI_TX_SCREEN:
		case UI_SPLASH_SCREEN:
		case UI_POWER_OFF:
		case MENU_CALIBRATION:
			return APRS_RX_WHY_MENU;
		default:
			break;
	}
	if (settingsUsbMode == USB_MODE_HOTSPOT)
	{
		return APRS_RX_WHY_MENU;
	}
	return APRS_RX_WHY_NONE;
}

/* Чи це зараз канал APRS: аналоговий FM, не сканування, APRS увімкнено і RX-частота == частота APRS.
 * Без EEPROM (aprsBeaconingGetRxInfo(full == false)). */
static aprsRxWhy_t evalWanted(uint32_t *freqOut)
{
	aprsRxInfo_t info;

	if ((trxGetMode() != RADIO_MODE_ANALOG) || (currentChannelData->chMode != RADIO_MODE_ANALOG))
	{
		return APRS_RX_WHY_NOT_FM;
	}
	if (aprsModeIsActive())
	{
		/* R10: «Режим APRS» -- слухаємо завжди, на частоті «каналу» режиму (currentChannelData вказує на нього) */
		*freqOut = currentChannelData->rxFreq;
		return APRS_RX_WHY_NONE;
	}
	if (uiDataGlobal.Scan.active)
	{
		return APRS_RX_WHY_SCAN;
	}
	if ((aprsBeaconingGetRxInfo(&info, false) == false) || (info.freq == 0U) || (info.freq != currentChannelData->rxFreq))
	{
		return APRS_RX_WHY_NOT_APRS;
	}
	*freqOut = info.freq;
	return APRS_RX_WHY_NONE;
}

static void refreshCfg(uint32_t now)
{
	aprsRxInfo_t info;

	s_rx.lastCfgMs = now;
	if (aprsModeIsActive())
	{
		/* R10: власний позивний/SSID/позиція -- з налаштувань режиму */
		char mc[8];
		uint8_t mssid;
		bool mpos;
		int32_t mlat, mlon;

		if (aprsModeOwnInfo(mc, &mssid, &mpos, &mlat, &mlon))
		{
			memset(s_rx.ownCall, 0, sizeof(s_rx.ownCall));
			for (int i = 0; (i < 6) && (mc[i] != 0); i++)
			{
				s_rx.ownCall[i] = mc[i];
			}
			s_rx.ownSsid = mssid;
			s_rx.ownHasPos = mpos;
			s_rx.ownLatU = mlat;
			s_rx.ownLonU = mlon;
		}
		return;
	}
	if (aprsBeaconingGetRxInfo(&info, true) == false)
	{
		return;
	}
	memset(s_rx.ownCall, 0, sizeof(s_rx.ownCall));
	for (int i = 0; (i < 6) && (info.call[i] != 0); i++)
	{
		s_rx.ownCall[i] = info.call[i];
	}
	s_rx.ownSsid = info.ssid;
	s_rx.ownHasPos = info.hasPos;
	if (info.hasPos)
	{
		/* double -> мікроградуси (округлення до найближчого) */
		s_rx.ownLatU = (int32_t)(info.lat * 1000000.0 + ((info.lat >= 0.0) ? 0.5 : -0.5));
		s_rx.ownLonU = (int32_t)(info.lon * 1000000.0 + ((info.lon >= 0.0) ? 0.5 : -0.5));
	}
}

static void ecoForce(void)
{
	if (rxPowerSavingGetLevel() != 0)
	{
		rxPowerSavingSetLevel(0);   /* приймач не вимикається посеред пакета */
		s_rx.ecoForced = true;
	}
}

static void engage(uint32_t now, uint32_t freq)
{
	s_rx.engaged = true;
	s_rx.freq = freq;
	s_rx.scaled = false;
	s_rx.triesLeft = APRS_RX_NBITS_TRIES;
	s_rx.failsInRow = 0;
	s_rx.tryAtMs = 0;
	s_rx.st.state = 1;
	s_rx.st.why = APRS_RX_WHY_NONE;
	s_rx.st.nbits = 0;
	s_rx.st.scaled = false;
	apFmtDetInit(&s_rx.det);
	refreshCfg(now);
	ecoForce();
}

static void disengage(aprsRxWhy_t why)
{
	if (s_rx.engaged == false)
	{
		return;
	}
	i2sStop();
	if (s_rx.ecoForced)
	{
		rxPowerSavingSetLevel(nonVolatileSettings.ecoLevel);   /* повернути рівень, як при виході з хотспоту */
		s_rx.ecoForced = false;
	}
	s_rx.engaged = false;
	s_rx.st.state = 0;
	s_rx.st.why = (uint8_t)why;
	if (why < APRS_RX_WHY_MAX)
	{
		s_rx.st.stops[why]++;
	}
}

void aprsRxStopForTx(void)
{
	if ((stateValid() == false) || (s_rx.i2sRunning == false))
	{
		return;
	}
	/* Як aprsRxSuspendForAudio(): I2S -- негайно. Решту (еко-рівень, стан «чекає») тік зробить сам, побачивши
	 * передачу (hardBlock). Пауза HOLD не дає тіку перезапустити I2S у проміжку між стартом і прапорцями TX. */
	i2sStop();
	s_rx.holdUntilMs = ticksGetMillis() + APRS_RX_HOLD_MS;
	if (s_rx.engaged)
	{
		s_rx.st.state = 1;
	}
	if (s_rx.st.syncStops < 0xFFFFU)
	{
		s_rx.st.syncStops++;
	}
}

void aprsRxNoteI2sEvent(aprsRxI2sEvent_t ev)
{
	/* Може прийти з будь-якого контексту (в т.ч. з задачі HR-C6000): лише інкремент у вже ініціалізованому стані. */
	if (stateValid() == false)
	{
		return;
	}
	if ((ev == APRS_RX_I2S_EV_WS_TIMEOUT) && (s_rx.st.wsTimeouts < 0xFFFFU))
	{
		s_rx.st.wsTimeouts++;
	}
	else if ((ev == APRS_RX_I2S_EV_ABORT_TIMEOUT) && (s_rx.st.abortTimeouts < 0xFFFFU))
	{
		s_rx.st.abortTimeouts++;
	}
}

void aprsRxSuspendForAudio(void)
{
	if (stateValid() == false)
	{
		return;
	}
	/* Негайно, без очікування переривання: далі код сам запускає свій I2S / пише в буфер звуку. Решту
	 * (еко-рівень, стан) тік зробить на наступній ітерації, побачивши підказку/відтворення/пробу. */
	i2sStop();
	s_rx.holdUntilMs = ticksGetMillis() + APRS_RX_HOLD_MS;
	if (s_rx.engaged)
	{
		s_rx.st.state = 1;
	}
}

/* ============================================================================================== */
/* Кадри: розбір, список станцій, повідомлення, банер                                               */
/* ============================================================================================== */

static bool bannerAllowed(void)
{
	int m = menuSystemGetCurrentMenuNumber();

	/* Лише головні екрани (канал/VFO): у меню налаштувань, на екрані TX, під час підказок банер
	 * заважав би. Чужий банер (SMS, гучність...) не перекриваємо. */
	if ((m != UI_CHANNEL_MODE) && (m != UI_VFO_MODE))
	{
		return false;
	}
	if (voicePromptsIsPlaying() || trxTransmissionEnabled || trxIsTransmitting)
	{
		return false;
	}
	if (uiNotificationIsVisible() && (uiNotificationGetId() != NOTIFICATION_ID_MESSAGE))
	{
		return false;
	}
	return true;
}

static const char *typeName(uint8_t type)
{
	switch (type)
	{
		case APRS_T_POSITION: return APRSRX_T_POS;
		case APRS_T_MESSAGE:  return APRSRX_T_MSG;
		case APRS_T_STATUS:   return APRSRX_T_STATUS;
		default:              return APRSRX_T_OTHER;
	}
}


/* ============================================================================================== */
/* R13: вікно маяка -- повноекранна картка за позиційним пакетом                                    */
/* ============================================================================================== */

/* Налаштування «Вікно маяка» -- 2 вільні біти bitfieldOptions (settings.h): 00 «Усі», 01 «Лише нові», 10 «Вимк.»; 11 читається як «Усі». */
uint8_t aprsRxBcnWinMode(void)
{
	uint8_t v = (uint8_t)((settingsIsOptionBitSet(BIT_APRS_BCN_WIN_LO) ? 1U : 0U) | (settingsIsOptionBitSet(BIT_APRS_BCN_WIN_HI) ? 2U : 0U));

	return (v >= 3U) ? (uint8_t)APRS_BCNWIN_ALL : v;
}

void aprsRxBcnWinSetMode(uint8_t mode)
{
	if (mode > (uint8_t)APRS_BCNWIN_OFF)
	{
		mode = (uint8_t)APRS_BCNWIN_ALL;
	}
	settingsSetOptionBit(BIT_APRS_BCN_WIN_LO, ((mode & 1U) != 0U));
	settingsSetOptionBit(BIT_APRS_BCN_WIN_HI, ((mode & 2U) != 0U));
}

const aprsRxWin_t *aprsRxWindow(void)
{
	return &s_rx.win;
}

static bool winIsShown(void)
{
	return uiNotificationIsVisible() && (uiNotificationGetId() == NOTIFICATION_ID_APRS_BEACON);
}

/* Вікно можна показувати лише на головних екранах (канал/VFO) і коли нічого не заважає: не передача, не підказка, не «Переслухати»,
 * не сканування, не хотспот/CPS. Меню налаштувань, набір тексту, «Режим APRS» -- це інші екрани (menuSystemGetCurrentMenuNumber()). */
static bool winAllowed(void)
{
	int m = menuSystemGetCurrentMenuNumber();

	if ((m != UI_CHANNEL_MODE) && (m != UI_VFO_MODE))
	{
		return false;
	}
	if (uiDataGlobal.Scan.active)
	{
		return false;
	}
	return (hardBlock() == APRS_RX_WHY_NONE);
}

/* R16: показати вікно за записом маяка станції dbIdx (позивний -- з db.st[]). Запис копіюється у s_rx.win -- це лише буфер малювання, дані
 * в історії (aprsModeHist()) не змінюються. Далі вікно живе за правилами winTick() (ручний режим). */
static void winOpenFromRec(const aprsBcnRec_t *rec, const aprsStation_t *st)
{
	aprsRxWin_t *w = &s_rx.win;

	memset(w, 0, sizeof(*w));
	memcpy(w, rec, sizeof(*rec));
	snprintf(w->call, sizeof(w->call), "%s", st->call);
	w->flags |= AWIN_F_MANUAL;
	w->active = true;
	uiNotificationShow(NOTIFICATION_TYPE_SMS, NOTIFICATION_ID_APRS_BEACON, 60000, NULL, true);
}

static const aprsStation_t *stationByCall(const char *call)
{
	for (int i = 0; i < APRS_STATIONS_MAX; i++)
	{
		if ((s_rx.db.st[i].call[0] != 0) && (strcmp(s_rx.db.st[i].call, call) == 0))
		{
			return &s_rx.db.st[i];
		}
	}
	return NULL;
}

bool aprsRxBeaconAvail(const char *call)
{
	if (stateValid() == false)
	{
		return false;
	}
	if (call == NULL)
	{
		int i = -1;

		return (aprsHistBeaconLast(aprsModeHist(), &i) != NULL);
	}
	{
		const aprsStation_t *st = stationByCall(call);

		return (st != NULL) && (aprsHistBeaconOf(aprsModeHist(), &s_rx.db, st) != NULL);
	}
}

/* R15: «Останній маяк» -- показати вікно ще раз за збереженими даними найсвіжішого маяка. Дані НЕ переписуються (час прийому лишається старий). Нема що
 * показувати -- нічого не робить; викликач сам перевіряє це (aprsRxBeaconAvail(NULL)) і пише користувачеві. */
void aprsRxWindowShowAgain(void)
{
	int i = -1;
	const aprsBcnRec_t *rec;

	if (stateValid() == false)
	{
		return;
	}
	rec = aprsHistBeaconLast(aprsModeHist(), &i);
	if (rec != NULL)
	{
		winOpenFromRec(rec, &s_rx.db.st[i]);
	}
}

/* R16: вікно маяка САМЕ цієї станції. false -- станції нема або позиційних пакетів від неї не було. */
bool aprsRxWindowShowStation(const char *call)
{
	const aprsStation_t *st;
	const aprsBcnRec_t *rec;

	if ((stateValid() == false) || (call == NULL))
	{
		return false;
	}
	st = stationByCall(call);
	rec = (st != NULL) ? aprsHistBeaconOf(aprsModeHist(), &s_rx.db, st) : NULL;
	if (rec == NULL)
	{
		return false;
	}
	winOpenFromRec(rec, st);
	return true;
}

/* R17 Г4: список станцій вікна й позиція поточної (за позивним вікна). Повертає кількість; *pos = -1, якщо станції вікна в списку нема. */
static int winOrder(uint8_t *order, int max, int *pos)
{
	int n = aprsHistBeaconOrder(aprsModeHist(), &s_rx.db, ticksGetMillis(), order, max);
	const aprsStation_t *cur = stationByCall(s_rx.win.call);

	*pos = (cur != NULL) ? aprsBeaconOrderFind(order, n, (int)(cur - &s_rx.db.st[0])) : -1;
	return n;
}

bool aprsRxWindowStep(int step)
{
	uint8_t order[APRS_STATIONS_MAX];
	int pos;
	int n;
	int to;
	bool wasManual;
	const aprsStation_t *st;
	const aprsBcnRec_t *rec;

	if ((stateValid() == false) || (s_rx.win.active == false))
	{
		return false;
	}
	n = winOrder(order, APRS_STATIONS_MAX, &pos);
	if ((n == 0) || ((n == 1) && (pos == 0)))
	{
		return false;
	}
	to = aprsBeaconOrderStep(pos, n, step);
	if (to < 0)
	{
		return false;
	}
	st = &s_rx.db.st[order[to]];
	rec = aprsHistBeaconOf(aprsModeHist(), &s_rx.db, st);
	if (rec == NULL)
	{
		return false;
	}
	wasManual = ((s_rx.win.flags & AWIN_F_MANUAL) != 0U);
	winOpenFromRec(rec, st);
	if (wasManual == false)
	{
		s_rx.win.flags &= (uint8_t)~AWIN_F_MANUAL;   /* вікно, відкрите пакетом, лишається «живим»: гасне за правилами winTick() */
	}
	return true;
}

bool aprsRxWindowPos(int *n, int *m)
{
	uint8_t order[APRS_STATIONS_MAX];
	int pos;
	int cnt;

	if ((stateValid() == false) || (s_rx.win.active == false))
	{
		return false;
	}
	cnt = winOrder(order, APRS_STATIONS_MAX, &pos);
	if (pos < 0)
	{
		return false;
	}
	*n = pos + 1;
	*m = cnt;
	return true;
}

void aprsRxWindowDismiss(void)
{
	if (stateValid())
	{
		s_rx.win.active = false;
	}
}

/* Повернути вікно на екран і зняти, коли причина зникла. Викликається щотіку (дешево: кілька порівнянь). Правила:
 *  - вікно активне, але показувати не можна (меню, передача, підказка, сканування...) -- знімаємо й ЗАБУВАЄМО: наступний пакет покаже нове;
 *  - вікно активне, а на екрані стійка картка SMS / Call Alert / повідомлення APRS -- віддаємо їй екран і забуваємо;
 *  - вікно активне, а зараз тимчасова картка (гучність, банер) -- чекаємо, поки вона зникне, тоді показуємо знову;
 *  - канал більше не APRS (приймач вимкнувся, ми не слухаємо) -- знімаємо: вікно закривало б екран іншого каналу. */
static void winTick(void)
{
	if (s_rx.win.active == false)
	{
		return;
	}
	if (s_rx.win.flags & AWIN_F_MANUAL)
	{
		/* R15: вікно відкрито з меню («Останній маяк»). Воно, як і звичайне, тримається до RED, але не прив'язане до головного екрана і
		 * каналу APRS: знімаємо лише там, де звичайне (передача, підказка, «Переслухати», хотспот/CPS...), і віддаємо екран стійкій картці. */
		if (hardBlock() != APRS_RX_WHY_NONE)
		{
			if (winIsShown())
			{
				uiNotificationHide(true);
			}
			s_rx.win.active = false;
			return;
		}
		if (winIsShown())
		{
			return;
		}
		if (uiNotificationIsVisible())
		{
			if (uiNotificationIsSms()
#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
					|| uiNotificationIsCallAlert()
#endif
					)
			{
				s_rx.win.active = false;
			}
			return;
		}
		uiNotificationShow(NOTIFICATION_TYPE_SMS, NOTIFICATION_ID_APRS_BEACON, 60000, NULL, true);
		return;
	}
	if ((winAllowed() == false) || (s_rx.engaged == false))
	{
		if (winIsShown())
		{
			uiNotificationHide(true);
		}
		s_rx.win.active = false;
		return;
	}
	if (winIsShown())
	{
		return;
	}
	if (uiNotificationIsVisible())
	{
		if (uiNotificationIsSms()
#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
				|| uiNotificationIsCallAlert()
#endif
				)
		{
			s_rx.win.active = false;   /* вхідне повідомлення важливіше й стійке -- вікно не повертаємо */
		}
		return;   /* тимчасова картка -- дочекаємось */
	}
	displayLightTrigger(false);
	uiNotificationShow(NOTIFICATION_TYPE_SMS, NOTIFICATION_ID_APRS_BEACON, 60000, NULL, true);
}

static void flushPending(void)
{
	if ((s_rx.pend.banner == false) && (s_rx.pend.msg == false))
	{
		return;
	}
	if (hardBlock() != APRS_RX_WHY_NONE)
	{
		return;   /* передача/підказка -- відкладемо до наступного тіку */
	}

	if (s_rx.pend.msg)
	{
		int n = (int)strlen(s_rx.pend.note);
		s_rx.pend.msg = false;
		s_rx.pend.banner = false;
		s_rx.st.msgStored++;   /* R11-fix2: сховище SMS НЕ чіпаємо -- повідомлення вже у списку «Повідом. APRS» (aprsMsgBgNewMessage()) */
		char note[APRS_RX_NOTE_TEXT + 8];
		snprintf(note, sizeof(note), "APRS %s", s_rx.pend.note);
		/* Так само, як вхідне SMS: будимо підсвітку, картка на весь екран до RED і сигнал. */
		displayLightTrigger(false);
		uiNotificationShow(NOTIFICATION_TYPE_SMS, NOTIFICATION_ID_APRS_MSG, 60000, note, true);   /* R11-fix2: власний id -- картка малює ЦЕЙ текст, а не останнє SMS зі сховища */
		soundSetMelody(MELODY_SMS_RECEIVED_BEEP);
		(void)n;
		return;
	}

	s_rx.pend.banner = false;
	if (bannerAllowed())
	{
		char l2[24];
		char buf[48];

		if (s_rx.pend.hasGeo)
		{
			aprsRxFormatGeo(l2, sizeof(l2), s_rx.pend.distM, s_rx.pend.bearing);
		}
		else
		{
			snprintf(l2, sizeof(l2), "%s", typeName(s_rx.pend.type));
		}
		snprintf(buf, sizeof(buf), APRSRX_BANNER_FMT, s_rx.pend.call, l2);
		uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, APRS_RX_BANNER_MS, buf, true);
		s_rx.st.banners++;
	}
}

static void frameDispatch(const uint8_t *frame, uint16_t len)
{
	aprsAx25_t ax;
	aprsPacket_t pkt;
	uint32_t now = ticksGetMillis();

	if (aprsAx25Parse(frame, len, &ax) == false)
	{
		return;   /* не AX.25 UI (або адреси не схожі) */
	}
	s_rx.db.total++;
	/* R16: журнал кадрів (TNC-2, 127 символів + час) для екрана «Пакети» -- ДО розгортання third-party й ДО відсіву дублікатів: показуємо те, що справді
	 * прийшло в ефір (кадр через i-gate видно з '}'). Блок -- у резерві «Переслухати» (aprsModeHist()), вільний CCM не чіпаємо. */
	int rssi = trxGetRSSIdBm(RADIO_DEVICE_PRIMARY);   /* R17 Г6: останній відлік RSSI (оновлюється головним циклом, поки приймач слухає); на момент розбору кадру несучої могло вже й не бути -- гіпотеза, перевіряється на залізі (BC13) */

	(void)aprsJrnAdd(aprsModeHist(), (uint32_t)uiDataGlobal.dateTimeSecs, frame, len, rssi);
	/* R11-fix: i-gate загортає пакет з APRS-IS у third-party ("}SRC>DST,path:info"). Розгортаємо ДО розбору: далі (банер, список станцій,
	 * дедуплікація, ACK відправнику) скрізь ax.src -- СПРАВЖНІЙ відправник, а не шлюз. Один рівень (див. aprsAx25Unwrap()). */
	if (aprsAx25Unwrap(&ax))
	{
		if (s_rx.db.tpUnwrapped < 0xFFFFU)
		{
			s_rx.db.tpUnwrapped++;
		}
	}
	aprsPacketParse(&ax, &pkt);   /* R11: розбір ДО відсіву дублікатів -- ACK на повторене відправником повідомлення потрібен і для дубліката */
	if ((pkt.type == APRS_T_MESSAGE) && s_rx.ownCall[0] && aprsMsgIsForUs(pkt.msgTo, s_rx.ownCall, s_rx.ownSsid))
	{
		/* R11-fix2: незалежно від «Режиму APRS»: ACK на наше -- скасувати повтори; повідомлення з номером -- ACK у фонову чергу
		 * НЕГАЙНО і на КОЖНУ копію (і на дублікат нижче: відправник повторює, доки не почує ACK). Рішення «показувати чи ні» -- пізніше. */
		aprsMsgBgOnMessage(&ax, &pkt);
	}
	if (aprsDbIsDuplicate(&s_rx.db, &ax, now))
	{
		return;   /* той самий (джерело, info) у межах 30 с -- один пакет */
	}

	if (pkt.type == APRS_T_OTHER)
	{
		s_rx.db.other++;
	}
	aprsStation_t *st = aprsDbUpdate(&s_rx.db, &ax, &pkt, now);
	/* R16: дані маяка КОЖНОЇ станції -- паралельний масив, індекс як у db.st[]. Нова станція (в тому числі та, що витіснила найстарішу) -- запис слота
	 * обнуляється ПЕРШИМ ділом, інакше вона показала б чужий маяк. Далі кожен позиційний пакет перезаписує запис станції. */
	aprsHistStationTouch(aprsModeHist(), &s_rx.db, st);
	if ((pkt.type == APRS_T_POSITION) && (st != NULL))
	{
		uint32_t bd = 0;
		uint16_t bb = 0;
		bool bg = aprsRxStationGeo(st, &bd, &bb);

		(void)aprsHistBeaconFill(aprsModeHist(), &s_rx.db, st, &pkt, bg, bd, bb, (uint32_t)uiDataGlobal.dateTimeSecs, rssi);
	}

	/* Повідомлення нам: тільки справжнє (не ack/rej), раніше не віддане. ACK уже поставлено вище (aprsMsgBgOnMessage(), на кожну копію);
	 * тут лише рішення «показувати чи ні». Повторна копія (відправник чекає ACK) користувачу вдруге не показується і банера станції
	 * не дає. Сховище SMS не чіпаємо. */
	bool msgCopy = false;

	if ((pkt.type == APRS_T_MESSAGE) && (pkt.msgAck == false) && (s_rx.ownCall[0] != 0) &&
			aprsMsgIsForUs(pkt.msgTo, s_rx.ownCall, s_rx.ownSsid))
	{
		if (aprsDbMsgSeen(&s_rx.db, &ax, &pkt, now))
		{
			msgCopy = true;
		}
		else if (aprsMsgBgNewMessage(&ax, &pkt))   /* у список «Повідом. APRS» (постійний блок) -- і в режимі, і поза ним */
		{
			s_rx.win.active = false;   /* R13: повідомлення важливіше за вікно маяка -- картка повідомлення замінить його на екрані */
			if (s_rx.pend.msg)
			{
				flushPending();   /* два повідомлення за один блок -- перше віддаємо зараз */
			}
			snprintf(s_rx.pend.note, sizeof(s_rx.pend.note), "%s: %s", ax.src, pkt.text);
			s_rx.pend.msg = true;
		}
	}

	/* R13: позиційний пакет -- вікно маяка замість банера (якщо дозволено налаштуванням і зараз можна). Дані копіюємо з пакета: у записі
	 * станції немає ні символу, ні курсу. Повідомлення нам важливіше -- воно залишає за собою екран (pend.msg), вікно тоді не готуємо. */
	bool bcnWin = false;
	/* R15: дані вікна зберігаємо для КОЖНОГО позиційного пакета (щоб «Останній маяк» міг показати його й тоді, коли пакет прийшов у меню або
	 * вікно вимкнено в налаштуваннях); показується воно за тими самими правилами, що й раніше (wantShow). Вікно, що зараз на екрані або чекає
	 * показу, інший пакет не підміняє, якщо сам не стає вікном -- як і було. */
	bool wantShow = (s_rx.pend.msg == false) && (msgCopy == false) &&
			aprsBeaconWindowWanted((aprsBcnWinMode_t)aprsRxBcnWinMode(), &pkt, ((st != NULL) && (st->count <= 1U))) && winAllowed();
	bool canFill = wantShow || ((pkt.type == APRS_T_POSITION) && (s_rx.pend.msg == false) && (msgCopy == false) &&
			(s_rx.win.active == false) && (winIsShown() == false));

	if (canFill)
	{
		aprsRxWin_t *w = &s_rx.win;
		const aprsBcnRec_t *rec = aprsHistBeaconOf(aprsModeHist(), &s_rx.db, st);

		memset(w, 0, sizeof(*w));
		if (rec != NULL)
		{
			memcpy(w, rec, sizeof(*rec));   /* R16: вікно = запис маяка (ті самі поля) + active + call; час і відстань -- на момент прийому */
		}
		w->active = wantShow;
		snprintf(w->call, sizeof(w->call), "%s", ax.src);
		bcnWin = wantShow;
		if (wantShow && winIsShown())
		{
			uiNotificationShow(NOTIFICATION_TYPE_SMS, NOTIFICATION_ID_APRS_BEACON, 60000, NULL, true);   /* уже на екрані -- лише оновлюємо вміст */
		}
	}

	/* Банер: кожен новий недублікат. */
	if ((s_rx.pend.msg == false) && (msgCopy == false) && (bcnWin == false))
	{
		s_rx.pend.banner = true;
		s_rx.pend.type = pkt.type;
		snprintf(s_rx.pend.call, sizeof(s_rx.pend.call), "%s", ax.src);
		s_rx.pend.hasGeo = aprsRxStationGeo(st, &s_rx.pend.distM, &s_rx.pend.bearing);
	}
}

/* ============================================================================================== */
/* Тік                                                                                             */
/* ============================================================================================== */

void aprsRxInit(void)
{
	memset(&s_rx, 0, sizeof(s_rx));
	aprsDbInit(&s_rx.db);
	aprsHistClearBeacons(aprsModeHist());   /* R16: список станцій порожній -- записи маяків (індекс як у db.st[]) теж */
	apFmtDetInit(&s_rx.det);
	s_rx.magic = APRS_RX_MAGIC;
}

static void processBlocks(uint32_t now)
{
	(void)now;
	for (uint32_t k = 0; (k < APRS_RX_BLOCKS_PER_TICK) && s_rx.i2sRunning && (s_rx.tail != s_rx.head); k++)
	{
		uint8_t t = s_rx.tail;
		int16_t x[APRS_RX_BLOCK];
		const uint16_t *src;

		__DMB();
		src = APRS_RX_RING_BASE + ((uint32_t)t * APRS_RX_BLOCK);

		/* Детектор nbits (R7) рахує завжди; посеред кадру демодулятора формат не міняється. */
		uint8_t effBefore = effNbits();
		uint8_t known = s_rx.det.nbits;
		if (apFmtDetBlock(&s_rx.det, src, 1, (int)APRS_RX_BLOCK, (s_rx.demod.inFrame != 0)) && (known == 0U))
		{
			s_rx.st.nbits = s_rx.det.nbits;
			if ((s_rx.det.nbits != AP_NBITS_TRUE16) && (s_rx.scaled == false))
			{
				if (s_rx.triesLeft > 0U)
				{
					/* Не справжні 16 біт: перезапускаємо I2S з паузою (фаза старту зрушилась). */
					s_rx.triesLeft--;
					s_rx.st.triesLeft = s_rx.triesLeft;
					s_rx.st.nbitsRestarts++;
					i2sStop();
					s_rx.tryAtMs = ticksGetMillis() + APRS_RX_NBITS_PAUSE_MS;
					s_rx.st.state = 1;
					return;
				}
				/* Спроби вичерпано -- працюємо з тим форматом, що є (шкала nbits -> 10 біт). */
				s_rx.scaled = true;
				s_rx.st.scaled = true;
				s_rx.st.nbitsScaled++;
			}
		}
		if (effNbits() != effBefore)
		{
			dspReset();   /* формат змінився: усе, що набрали досі, -- з іншого формату */
		}
		s_rx.st.det_switches = s_rx.det.switches;
		s_rx.st.nbits = s_rx.det.nbits;

		apFmtExtract(NULL, src, 1, (int)APRS_RX_BLOCK, effNbits(), x);
		processBlock(x);
		s_rx.tail = (uint8_t)((t + 1U) % APRS_RX_SLOTS);
	}
}

void aprsRxTick(void)
{
	if (stateValid() == false)
	{
		return;
	}

	uint32_t now = ticksGetMillis();
	aprsRxWhy_t why;

	winTick();   /* R13: вікно маяка живе й тоді, коли приймач зупинено (передача, підказка): тік знімає його сам */
	AM_TRACE_T(64);   /* R10-fix: aprsRxTick у режимі, перший тік (перед hardBlock) */
	why = hardBlock();

	if (why != APRS_RX_WHY_NONE)
	{
		s_rx.holdUntilMs = now + APRS_RX_HOLD_MS;
		AM_TRACE_T(65);   /* hardBlock != NONE: перед disengage */
		disengage(why);
		setWhy(why);
		return;   /* відкладені дії чекають, поки умова зникне */
	}

	AM_TRACE_T(66);   /* перед flushPending */
	flushPending();
	AM_TRACE_T(67);   /* після flushPending */

	if (s_rx.engaged == false)
	{
		if ((now < s_rx.holdUntilMs) || ((s_rx.lastEvalMs != 0U) && ((now - s_rx.lastEvalMs) < APRS_RX_EVAL_MS)))
		{
			return;
		}
		s_rx.lastEvalMs = (now != 0U) ? now : 1U;
		uint32_t freq = 0;
		why = evalWanted(&freq);
		if (why != APRS_RX_WHY_NONE)
		{
			setWhy(why);
			return;
		}
		AM_TRACE_T(68);   /* перед engage (refreshCfg, ecoForce) */
		engage(now, freq);
		AM_TRACE_T(69);   /* після engage */
	}
	else
	{
		/* Дешеві перевірки щотіку: канал/режим не змінились. Повна -- раз на APRS_RX_EVAL_MS. */
		if ((trxGetMode() != RADIO_MODE_ANALOG) || (currentChannelData->rxFreq != s_rx.freq))
		{
			disengage((trxGetMode() != RADIO_MODE_ANALOG) ? APRS_RX_WHY_NOT_FM : APRS_RX_WHY_NOT_APRS);
			return;
		}
		if ((now - s_rx.lastEvalMs) >= APRS_RX_EVAL_MS)
		{
			uint32_t freq = 0;
			s_rx.lastEvalMs = (now != 0U) ? now : 1U;
			why = evalWanted(&freq);
			if ((why != APRS_RX_WHY_NONE) || (freq != s_rx.freq))
			{
				disengage((why != APRS_RX_WHY_NONE) ? why : APRS_RX_WHY_NOT_APRS);
				return;
			}
		}
		if ((now - s_rx.lastCfgMs) >= APRS_RX_CFG_MS)
		{
			refreshCfg(now);
		}
		ecoForce();   /* стоковий код міг повернути еко-рівень (екран каналу, меню) */
	}

	/* I2S міг зупинити хтось інший (soundTerminateSound() тощо) -- тоді перезапуск. */
	if (s_rx.i2sRunning && (I2SProbeIsRunning() == false))
	{
		s_rx.i2sRunning = false;
		s_rx.tryAtMs = now + APRS_RX_RETRY_MS;
		s_rx.st.state = 1;
	}

	if ((s_rx.i2sRunning == false) && (now >= s_rx.holdUntilMs) && (now >= s_rx.tryAtMs))
	{
		aprsRxWhy_t r;

		AM_TRACE_T(70);   /* перед i2sTryStart (I2SProbeStart, PRIMASK) */
		r = i2sTryStart();
		AM_TRACE_T(71);   /* після i2sTryStart */
		if (r == APRS_RX_WHY_NONE)
		{
			s_rx.st.state = 2;
			s_rx.failsInRow = 0;
			s_rx.st.why = APRS_RX_WHY_NONE;
		}
		else
		{
			s_rx.st.startFails++;
			s_rx.st.why = (uint8_t)r;
			if (s_rx.failsInRow < 255U)
			{
				s_rx.failsInRow++;
			}
			/* нема такту WS -- не смикати переривання (PRIMASK) щочверть секунди вічно */
			s_rx.tryAtMs = now + ((s_rx.failsInRow >= APRS_RX_FAILS_SLOW) ? APRS_RX_RETRY_SLOW_MS : APRS_RX_RETRY_MS);
		}
	}

	if (s_rx.i2sRunning)
	{
		AM_TRACE_T(72);   /* перед processBlocks */
		processBlocks(now);
		AM_TRACE_T(73);   /* після processBlocks */
		measureFs();
	}
}

#endif /* APRS_RX */
