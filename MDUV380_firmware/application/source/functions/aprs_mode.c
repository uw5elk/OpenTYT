/*
 * aprs_mode.c -- «Режим APRS» (R10). Опис задуму, пам'яті й порядку входу/виходу -- aprs_mode.h і docs/
 * aprs-rx-feasibility.md, розділ 13; кроки перевірки -- TESTING.md, блок AM.
 *
 * Що тут. Вхід/вихід (паркування рації на частоті APRS, відновлення каналу), налаштування (читання/запис
 * custom-data блоку, типові значення з кодплуга), маяк (ручний, PTT, періодичний), «останній пакет» для монітора.
 * Екран -- user_interface/menuAprsMode.c. Приймач -- functions/aprs_rx.c (R8), у режимі він слухає частоту
 * «каналу» режиму. Модулятор AFSK і сам кадр маяка -- стокові (aprs.c: aprsModeTxBeacon()).
 */
#include "functions/aprs_mode.h"

#if defined(APRS_RX)

#include "main.h"
#include "functions/aprs.h"
#include "functions/aprs_rx.h"
#include "functions/codeplug.h"
#include "functions/settings.h"
#include "functions/trx.h"
#include "functions/ticks.h"
#include "functions/sound.h"
#include "functions/rxPowerSaving.h"
#include "functions/callReplay.h"
#include "hardware/radioHardwareInterface.h"
#include "hardware/HR-C6000.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "usb/usb_com.h"
#include "user_interface/languages/aprsmode_ua.h"
#include <string.h>
#include <stdio.h>
#include <math.h>

#define APRS_MODE_MAGIC        0xA9A5A0D3UL
#define APRS_MODE_SAVE_IDLE_MS 2000U      /* запис налаштувань у флеш -- після паузи в редагуванні (не на кожен крок ←→) */
#define APRS_MODE_BUSY_MAX_MS  3000U      /* скільки чекати вільної частоти перед маяком */
#define APRS_MODE_RETRY_MS     10000UL    /* після невдалого періодичного маяка */
#define APRS_MODE_PTT_GAP_MS   3000U      /* перед повторним маяком від PTT */
#define APRS_MODE_RX_BUSY_MS   600U       /* активність AFSK за останні 600 мс -- частота зайнята */

/* Стан режиму. Лежить у позиченому буфері "Переслухати" (або в статичній структурі в CCM без нього). */
typedef struct
{
	uint32_t               magic;
	aprsModeCfg_t          cfg;
	aprsModeDefaults_t     def;
	aprsModeEff_t          eff;
	CodeplugChannel_t      chan;           /* «канал» режиму: на нього вказує currentChannelData, поки режим активний */
	CodeplugChannel_t     *savedChan;
	bool                   beaconWasRunning;   /* стоковий авто-бікон працював до входу (відновити при виході) */
	bool                   dirty;
	uint32_t               dirtyAtMs;
	/* маяк */
	bool                   reqManual;
	bool                   reqPtt;
	uint32_t               busySinceMs;
	uint32_t               beacons;
	uint32_t               lastBeaconMs;
	uint32_t               nextBeaconMs;   /* 0 -- періодичного нема */
	uint32_t               lastPttMs;
	aprsModeBcnState_t     bcnState;
	/* монітор */
	aprsModeLast_t         last;
	aprsModeUi_t           ui;
#if defined(APRS_MODE_TRACE)
	uint32_t               trSeen;         /* R10-fix: які номери тік-трасування (60..91) уже показано після входу/маяка */
	uint32_t               trT0;           /* R10-fix3: мітка часу (мс) початку передачі -- trxSetTX(); рядок t= на екрані трасування */
#endif
} aprsModeMem_t;

#if defined(ENABLE_CALL_REPLAY)
static inline aprsModeMem_t *mem(void)
{
	size_t n = 0;

	return (aprsModeMem_t *)callReplayBorrow(&n);
}
_Static_assert(sizeof(aprsModeMem_t) <= (500U * 27U), "aprsModeMem_t does not fit the call replay ring");
#else
static aprsModeMem_t s_modeMem __attribute__((section(".aes_ccmram"), aligned(8)));
static inline aprsModeMem_t *mem(void)
{
	return &s_modeMem;
}
#endif

#if defined(APRS_MODE_TRACE)
/* R10-fix: ТИМЧАСОВЕ трасування на екран. Не залежить від сповіщень (displayRenderWithoutNotification) і не чіпає стан
 * режиму; номер видно, поки екран не перемалюють. Якщо зависає САМ displayRender() -- на склі лишиться ПОПЕРЕДНІЙ номер. */
/* v != TRACE_NO_V: під номером ще й додаткове значення (лічильник/довжина). Нижче -- мінімальний залишок стека
 * поточного завдання в БАЙТАХ (uxTaskGetStackHighWaterMark): якщо він близький до 0, зависання -- переповнення стека. */
#define TRACE_NO_V  0xFFFFFFFFUL

/* R10-fix3: ГАРАНТІЯ, що кадр на склі відповідає останньому виконаному кроку.
 * Рендер (displayRenderRows) синхронний: HAL_DMA_PollForTransfer(HAL_MAX_DELAY) чекає кінця пересилки в FSMC. Але якщо
 * DMA2/Stream0 застряг у стані «зайнято», HAL_DMA_Start() мовчки повертає HAL_BUSY і екран НЕ оновлюється -- тоді номер
 * на склі відстає від коду. Тому перед малюванням: стан не READY -> примусовий HAL_DMA_Abort() і позначка «DMA!» на екрані;
 * після малювання: чекаємо READY (до 50 мс) і ще 30 мс, поки кадр дійде до скла. Маяк у трасуванні повільніший -- це нормально. */
static void traceDraw(unsigned int n, unsigned long v, bool hex)
{
	char b[12];
	char c[24];
	bool dmaFixed = false;

	if (HAL_DMA_GetState(&hdma_memtomem_dma2_stream0) != HAL_DMA_STATE_READY)
	{
		(void)HAL_DMA_Abort(&hdma_memtomem_dma2_stream0);
		dmaFixed = true;
	}
	snprintf(b, sizeof(b), "%u", n);
	displayClearBuf();
	displayPrintCentered(2, "APRS TRACE", FONT_SIZE_2);
	if (aprsModeIsActive() && (mem()->trT0 != 0U))
	{
		snprintf(c, sizeof(c), "t=%lu ms", (unsigned long)(ticksGetMillis() - mem()->trT0));   /* від trxSetTX() */
		displayPrintCentered(20, c, FONT_SIZE_2);
	}
	displayPrintCentered(48, b, FONT_SIZE_4);
	if (v != TRACE_NO_V)
	{
		if (hex)
		{
			snprintf(c, sizeof(c), "0x%08lX", v);
		}
		else
		{
			snprintf(c, sizeof(c), "v=%lu", v);
		}
		displayPrintCentered(86, c, FONT_SIZE_2);
	}
	if (dmaFixed)
	{
		snprintf(c, sizeof(c), "stk %lu B DMA!", (unsigned long)uxTaskGetStackHighWaterMark(NULL) * (unsigned long)sizeof(StackType_t));
	}
	else
	{
		snprintf(c, sizeof(c), "stk %lu B", (unsigned long)uxTaskGetStackHighWaterMark(NULL) * (unsigned long)sizeof(StackType_t));
	}
	displayPrintCentered(106, c, FONT_SIZE_2);
	displayRenderWithoutNotification();

	{
		uint32_t t0 = ticksGetMillis();

		while ((HAL_DMA_GetState(&hdma_memtomem_dma2_stream0) != HAL_DMA_STATE_READY) && ((ticksGetMillis() - t0) < 50U))
		{
			vTaskDelay(1U);
		}
	}
	vTaskDelay((30U / portTICK_PERIOD_MS));
}

void aprsModeTrace(unsigned int n)
{
	traceDraw(n, TRACE_NO_V, false);
}

void aprsModeTraceV(unsigned int n, unsigned int v)
{
	traceDraw(n, (unsigned long)v, false);
}

void aprsModeTraceH(unsigned int n, unsigned long v)
{
	traceDraw(n, v, true);
}

/* Мітка «передача почалась» (перед trxSetTX): далі кожен кадр трасування показує t= від неї. */
void aprsModeTraceMark(void)
{
	if (aprsModeIsActive())
	{
		mem()->trT0 = (ticksGetMillis() != 0U) ? ticksGetMillis() : 1U;
	}
}

void aprsModeTraceT(unsigned int n)
{
	aprsModeMem_t *m;

	if ((aprsModeIsActive() == false) || (n < 60U) || (n > 91U))
	{
		return;
	}
	m = mem();
	if ((m->trSeen & (1UL << (n - 60U))) == 0U)
	{
		m->trSeen |= (1UL << (n - 60U));
		aprsModeTrace(n);
	}
}

/* Новий «сеанс» тік-трасування (після входу в режим і перед маяком): усі номери 60..91 знову показуються один раз. */
static void traceTickReset(void)
{
	if (aprsModeIsActive())
	{
		mem()->trSeen = 0U;
	}
}
#endif

/* ---- допоміжне ---------------------------------------------------------------------------------------- */

bool aprsModeIsActive(void)
{
	return (aprsRxUi()->modeOn != 0U);
}

aprsModeUi_t *aprsModeUi(void)
{
	return &mem()->ui;
}

aprsModeCfg_t *aprsModeCfg(void)
{
	return &mem()->cfg;
}

const aprsModeEff_t *aprsModeEff(void)
{
	return &mem()->eff;
}

const aprsModeDefaults_t *aprsModeDefaults(void)
{
	return &mem()->def;
}

const aprsModeLast_t *aprsModeLast(void)
{
	return &mem()->last;
}

uint32_t aprsModeBeaconCount(void)
{
	return mem()->beacons;
}

uint32_t aprsModeLastBeaconAgeSec(void)
{
	aprsModeMem_t *m = mem();

	return (m->lastBeaconMs == 0U) ? 0xFFFFFFFFUL : ((ticksGetMillis() - m->lastBeaconMs) / 1000U);
}

uint32_t aprsModeNextBeaconSec(void)
{
	aprsModeMem_t *m = mem();
	uint32_t now = ticksGetMillis();

	if ((m->nextBeaconMs == 0U) || (m->eff.interval == 0U))
	{
		return 0xFFFFFFFFUL;
	}
	return (m->nextBeaconMs > now) ? ((m->nextBeaconMs - now + 999U) / 1000U) : 0U;
}

aprsModeBcnState_t aprsModeBeaconState(void)
{
	return mem()->bcnState;
}

bool aprsModeIsTransmitting(void)
{
	return (aprsTxProgress != APRS_TX_IDLE);
}

/* ---- налаштування: флеш і типові значення ------------------------------------------------------------------- */

static void loadCfg(aprsModeMem_t *m)
{
	uint8_t blk[APRSM_BLOCK_LEN];

	memset(blk, 0, sizeof(blk));
	if ((codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG, blk, (int)sizeof(blk)) == false) ||
			(aprsModeCfgFromBytes(&m->cfg, blk, sizeof(blk)) == false))
	{
		aprsModeCfgInit(&m->cfg);   /* блоку нема (нова установка) або він зіпсований -- усе типове */
	}
}

static void saveCfg(aprsModeMem_t *m)
{
	uint8_t blk[APRSM_BLOCK_LEN];

	aprsModeCfgToBytes(&m->cfg, blk);
	(void)codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG, blk, (int)sizeof(blk));
	m->dirty = false;
}

static void buildDefaults(aprsModeMem_t *m)
{
	aprsModeRawCfg_t raw;
	CodeplugAPRSConfig_t cp;
	bool ok = false;
	char name[16];
	bool posOk = settingsLocationIsValid();
	int32_t latU = 0, lonU = 0;

	_Static_assert(sizeof(aprsModeRawCfg_t) == sizeof(CodeplugAPRSConfig_t), "aprsModeRawCfg_t != CodeplugAPRSConfig_t");

	/* Конфіг APRS: той, що призначено каналу, з якого зайшли; нема -- перший наявний у кодплузі. */
	if ((m->savedChan != NULL) && (m->savedChan->aprsConfigIndex != 0U))
	{
		ok = codeplugAPRSGetDataForIndex(m->savedChan->aprsConfigIndex, &cp);
	}
	for (int i = 1; (ok == false) && (i <= codeplugAPRSConfigGetCount()); i++)
	{
		ok = codeplugAPRSGetDataForIndex(i, &cp);
	}
	if (ok)
	{
		memcpy(&raw, &cp, sizeof(raw));
	}
	memset(name, 0, sizeof(name));
	codeplugGetRadioName(name);
	if (posOk)
	{
		double la = settingsLocationGetLatitude(), lo = settingsLocationGetLongitude();

		posOk = ((isnan(la) == 0) && (isnan(lo) == 0));
		if (posOk)
		{
			latU = (int32_t)(la * 1000000.0 + ((la >= 0.0) ? 0.5 : -0.5));
			lonU = (int32_t)(lo * 1000000.0 + ((lo >= 0.0) ? 0.5 : -0.5));
		}
	}
	aprsModeDefaultsBuild(&m->def, ok ? &raw : NULL, ok, name, posOk, latU, lonU);
}

/* «Канал» режиму: аналоговий FM, 12,5 кГц (як у QSY бікона: trxSetModeAndBandwidth(ANALOG, false)), без CSS і
 * потужності каналу. Поля, яких не зачепив memset, -- нулі, як у satelliteChannelData. */
static void buildChan(aprsModeMem_t *m)
{
	memset(&m->chan, 0, sizeof(m->chan));
	m->chan.chMode = RADIO_MODE_ANALOG;
	m->chan.rxFreq = m->eff.freq;
	m->chan.txFreq = m->eff.freq;
	m->chan.rxTone = CODEPLUG_CSS_TONE_NONE;
	m->chan.txTone = CODEPLUG_CSS_TONE_NONE;
	m->chan.sql = m->eff.sql;
	m->chan.aprsConfigIndex = 0U;   /* стоковий бікон нічого не знайде для цього «каналу» */
	codeplugChannelSetFlag(&m->chan, CHANNEL_FLAG_BW_25K, 0);
}

static void tune(const aprsModeMem_t *m)
{
	uint32_t f = m->eff.freq;

	AM_TRACE(30);   /* перед radioSetTRxDevice */
	radioSetTRxDevice(RADIO_DEVICE_PRIMARY);
	AM_TRACE(31);   /* перед trxSetFrequency */
	trxSetFrequency(f, f, DMR_MODE_AUTO);
	AM_TRACE(32);   /* перед trxSetModeAndBandwidth */
	trxSetModeAndBandwidth(RADIO_MODE_ANALOG, false);   /* 12,5 кГц -- як у бікона */
	AM_TRACE(33);   /* перед trxSetRxCSS */
	trxSetRxCSS(RADIO_DEVICE_PRIMARY, CODEPLUG_CSS_TONE_NONE);
	AM_TRACE(34);   /* перед trxSetTxCSS */
	trxSetTxCSS(CODEPLUG_CSS_TONE_NONE);
	AM_TRACE(35);   /* перед vTaskDelay(40 мс) */
	vTaskDelay((40U / portTICK_PERIOD_MS));
	AM_TRACE(36);   /* перед trxPostponeReadRSSIAndNoise */
	trxPostponeReadRSSIAndNoise(100);
	AM_TRACE(37);   /* tune() завершено */
}

static void scheduleBeacons(aprsModeMem_t *m, uint32_t now)
{
	m->nextBeaconMs = (m->eff.interval != 0U) ? (now + aprsModeIntervalMs(m->eff.interval)) : 0U;
	if ((m->nextBeaconMs == 0U) && (m->eff.interval != 0U))
	{
		m->nextBeaconMs = 1U;
	}
}

void aprsModeCfgChanged(uint16_t what)
{
	aprsModeMem_t *m = mem();
	uint32_t now = ticksGetMillis();
	uint32_t oldFreq = m->eff.freq;
	uint8_t oldInterval = m->eff.interval;

	aprsModeEffective(&m->cfg, &m->def, &m->eff);
	m->chan.sql = m->eff.sql;
	if (m->eff.freq != oldFreq)
	{
		m->chan.rxFreq = m->chan.txFreq = m->eff.freq;
		if (aprsTxProgress == APRS_TX_IDLE)
		{
			tune(m);
		}
	}
	if (m->eff.interval != oldInterval)
	{
		scheduleBeacons(m, now);
	}
	(void)what;
	m->dirty = true;
	m->dirtyAtMs = now;
}

void aprsModeCfgReset(void)
{
	aprsModeMem_t *m = mem();

	aprsModeCfgInit(&m->cfg);
	aprsModeCfgChanged(APRSM_OV_ALL);
}

/* ---- вхід / вихід -------------------------------------------------------------------------------------------- */

bool aprsModeEnter(void)
{
	aprsModeMem_t *m;
	size_t sz = 0;
	int root = menuSystemGetRootMenuNumber();
	void *base;

	AM_TRACE(1);   /* вхід у aprsModeEnter */
	if (aprsModeIsActive())
	{
		return true;
	}
	if (((root != UI_CHANNEL_MODE) && (root != UI_VFO_MODE)) || (settingsUsbMode == USB_MODE_HOTSPOT) ||
			(aprsTxProgress != APRS_TX_IDLE) || trxTransmissionEnabled || trxIsTransmitting)
	{
		return false;
	}
	AM_TRACE(2);   /* перевірки пройдено */

	if (uiDataGlobal.Scan.active)
	{
		AM_TRACE(3);   /* перед зупинкою сканування */
		if (root == UI_VFO_MODE)
		{
			uiVFOModeStopScanning();
		}
		else
		{
			uiChannelModeStopScanning();
		}
		AM_TRACE(4);   /* сканування зупинено */
	}

	AM_TRACE(5);   /* перед callReplayStop */
	callReplayStop();   /* відтворення йде з цього ж буфера; позичене кільце стане недійсним */
	AM_TRACE(6);   /* перед aprsRxSuspendForAudio */
	aprsRxSuspendForAudio();   /* приймач R8 (він зараз міг слухати канал) -- негайно, до перебудови радіо */
	AM_TRACE(7);   /* перед callReplayBorrow */

#if defined(ENABLE_CALL_REPLAY)
	base = callReplayBorrow(&sz);
	if (sz < sizeof(aprsModeMem_t))
	{
		callReplayRelease();
		return false;
	}
#else
	(void)sz;
	base = &s_modeMem;
#endif
	/* R10-fix: захист -- невирівняний стан дав би UsageFault (LDM/STM/LDRD) і вічний while(1). Краще відмовити у вході. */
	if ((((uintptr_t)base) & 7U) != 0U)
	{
#if defined(ENABLE_CALL_REPLAY)
		callReplayRelease();
#endif
		return false;
	}
	AM_TRACE(8);   /* перед memset стану режиму */
	m = (aprsModeMem_t *)base;
	memset(m, 0, sizeof(*m));
	m->magic = APRS_MODE_MAGIC;
	m->savedChan = currentChannelData;

	AM_TRACE(9);   /* перед loadCfg */
	loadCfg(m);
	AM_TRACE(10);  /* перед buildDefaults */
	buildDefaults(m);
	AM_TRACE(11);  /* перед aprsModeEffective */
	aprsModeEffective(&m->cfg, &m->def, &m->eff);
	AM_TRACE(12);  /* перед buildChan */
	buildChan(m);

	/* стоковий авто-бікон на час режиму -- призупинити (він би QSY-нув на частоту конфігу каналу) */
	AM_TRACE(13);  /* перед aprsBeaconingGetMode/IsSuspended */
	m->beaconWasRunning = ((aprsBeaconingGetMode() != APRS_BEACONING_MODE_OFF) && (aprsBeaconingIsSuspended() == false));
	if (m->beaconWasRunning)
	{
		AM_TRACE(14);  /* перед aprsBeaconingSetSuspend(true) */
		aprsBeaconingSetSuspend(true);
	}

	AM_TRACE(15);  /* перед підміною currentChannelData */
	currentChannelData = &m->chan;
	AM_TRACE(16);  /* перед tune() (далі 30..37) */
	tune(m);

	AM_TRACE(17);  /* перед scheduleBeacons */
	scheduleBeacons(m, ticksGetMillis());
	m->bcnState = APRS_MODE_BCN_NONE;
	m->ui.page = APRS_MODE_PAGE_MONITOR;
	aprsRxUi()->view = APRS_RX_VIEW_LIST;
	aprsRxUi()->sel = 0;
	aprsRxUi()->scroll = 0;
	AM_TRACE(18);  /* перед modeOn = 1 */
	aprsRxUi()->modeOn = 1U;   /* з цього моменту приймач R8 слухає частоту «каналу» режиму */
	AM_TRACE(19);  /* aprsModeEnter завершено (return true) */
	return true;
}

void aprsModeExit(void)
{
	aprsModeMem_t *m;
	CodeplugChannel_t *saved;
	bool wasRunning;
	int root;

	if (aprsModeIsActive() == false)
	{
		return;
	}
	AM_TRACE(300);  /* aprsModeExit: вхід (режим активний) */
	m = mem();
	if (m->dirty)
	{
		AM_TRACE(301);  /* перед saveCfg */
		saveCfg(m);
	}
	if (aprsTxProgress != APRS_TX_IDLE)
	{
		AM_TRACE(302);  /* перед aprsModeAbortTx */
		aprsModeAbortTx();   /* примусовий вихід посеред маяка (вимкнення, push меню) */
	}
	AM_TRACE(303);  /* перед aprsRxSuspendForAudio */
	aprsRxSuspendForAudio();   /* приймач -- негайно; далі радіо перебудовується */
	aprsRxUi()->modeOn = 0U;

	saved = m->savedChan;
	wasRunning = m->beaconWasRunning;
	currentChannelData = saved;
	AM_TRACE(304);  /* перед callReplayRelease */
#if defined(ENABLE_CALL_REPLAY)
	callReplayRelease();   /* m недійсне; кільце знову порожнє, "Запис RX" повернуто */
#endif
	m = NULL;

	root = menuSystemGetRootMenuNumber();
	AM_TRACE(305);  /* перед перезавантаженням каналу/VFO */
	if (root == UI_CHANNEL_MODE)
	{
		uiChannelModeLoadChannelData(true, false);
	}
	else
	{
		uiVFOModeLoadChannelData(false);
	}
	AM_TRACE(306);  /* перед aprsBeaconingResetTimers */
	aprsBeaconingResetTimers();
	if (wasRunning)
	{
		aprsBeaconingSetSuspend(false);
	}
	AM_TRACE(307);  /* aprsModeExit завершено */
}

/* ---- маяк ----------------------------------------------------------------------------------------------------- */

void aprsModeRequestBeacon(void)
{
	AM_TRACE(200);  /* aprsModeRequestBeacon: вхід (GREEN на «Моніторі») */
	if (aprsModeIsActive())
	{
#if defined(APRS_MODE_TRACE)
		traceTickReset();   /* тік-трасування знову покаже кожен номер один раз */
#endif
		mem()->reqManual = true;
		AM_TRACE(201);  /* reqManual виставлено; далі маяк піде з aprsModeTick() */
	}
}

void aprsModeOnPtt(void)
{
	aprsModeMem_t *m;
	uint32_t now = ticksGetMillis();

	if (aprsModeIsActive() == false)
	{
		return;
	}
	m = mem();
	if ((m->lastPttMs != 0U) && ((now - m->lastPttMs) < APRS_MODE_PTT_GAP_MS))
	{
		return;
	}
	AM_TRACE(205);  /* aprsModeOnPtt: PTT прийнято (після перевірки паузи 3 с) */
#if defined(APRS_MODE_TRACE)
	traceTickReset();
#endif
	m->lastPttMs = now;
	m->reqPtt = true;
	AM_TRACE(206);  /* reqPtt виставлено; далі маяк піде з aprsModeTick() */
}

static bool channelBusy(const aprsModeMem_t *m)
{
	/* кадр/прапорці AFSK за останні 0,6 с -- хтось передає пакет; несуча за шумодавом "каналу" режиму -- теж.
	 * Якщо шумодав відкрито на 0 % (sql == 1), індикатор несучої світить завжди -- його не враховуємо. */
	if (aprsRxBusy(APRS_MODE_RX_BUSY_MS))
	{
		return true;
	}
	return (m->eff.sql != 1U) && (LedRead(LED_GREEN) != 0);
}

static void beaconFeedback(aprsModeBcnState_t st)
{
	const char *txt = NULL;

	switch (st)
	{
		case APRS_MODE_BCN_NOCALL:  txt = APRSM_ERR_NOCALL; break;
		case APRS_MODE_BCN_NOPOS:   txt = APRSM_ERR_NOPOS; break;
		case APRS_MODE_BCN_INHIBIT: txt = APRSM_ERR_INHIBIT; break;
		case APRS_MODE_BCN_BAND:    txt = APRSM_ERR_BAND; break;
		case APRS_MODE_BCN_BUSY_CH: txt = APRSM_ERR_BUSYCH; break;
		case APRS_MODE_BCN_FAILED:  txt = APRSM_ERR_FAILED; break;
		case APRS_MODE_BCN_TOOBIG:  txt = APRSM_ERR_TOOBIG; break;
		default: break;
	}
	if (txt != NULL)
	{
		uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, txt, true);
		soundSetMelody(MELODY_ERROR_BEEP);
	}
}

void aprsModeTick(void)
{
	aprsModeMem_t *m;
	uint32_t now;
	bool manual, periodic;

	if (aprsModeIsActive() == false)
	{
		return;
	}
	AM_TRACE_T(60);   /* перший тік aprsModeTick після входу/маяка */
	m = mem();
	now = ticksGetMillis();

	/* Режим живе лише всередині меню «APRS» і лише коли хотспот не вхопив рацію. */
	if ((menuSystemGetCurrentMenuNumber() != MENU_APRS_HUB) || (settingsUsbMode == USB_MODE_HOTSPOT))
	{
		AM_TRACE(61);   /* aprsModeTick: меню не «APRS» (або хотспот) -- виходимо з режиму */
		aprsModeExit();
		return;
	}

	if (m->dirty && ((now - m->dirtyAtMs) >= APRS_MODE_SAVE_IDLE_MS))
	{
		AM_TRACE(62);   /* перед saveCfg у aprsModeTick */
		saveCfg(m);
	}

	if (aprsTxProgress != APRS_TX_IDLE)
	{
		return;   /* передача йде (або стокова машина завершує її) */
	}
	if ((m->bcnState == APRS_MODE_BCN_SENT) && (m->lastBeaconMs != 0U) && ((now - m->lastBeaconMs) > 3000U))
	{
		m->bcnState = APRS_MODE_BCN_NONE;   /* «Передано» на екрані -- кілька секунд */
	}

	manual = (m->reqManual || m->reqPtt);
	periodic = ((manual == false) && (m->eff.interval != 0U) && (m->nextBeaconMs != 0U) && ((int32_t)(now - m->nextBeaconMs) >= 0));
	if ((manual == false) && (periodic == false))
	{
		m->busySinceMs = 0U;
		return;
	}

	AM_TRACE_T(63);   /* маяк замовлено: перед channelBusy() (тік: лише перший раз) */
	if (channelBusy(m))
	{
		if (m->busySinceMs == 0U)
		{
			m->busySinceMs = (now != 0U) ? now : 1U;
		}
		if ((now - m->busySinceMs) < APRS_MODE_BUSY_MAX_MS)
		{
			m->bcnState = APRS_MODE_BCN_BUSY_CH;
			return;   /* приймач далі працює -- чекаємо, поки пакет, що займає частоту, закінчиться */
		}
		/* зайнято весь час очікування */
		m->busySinceMs = 0U;
		m->reqManual = m->reqPtt = false;
		if (periodic)
		{
			m->nextBeaconMs = now + APRS_MODE_RETRY_MS;
		}
		m->bcnState = APRS_MODE_BCN_BUSY_CH;
		if (manual)
		{
			beaconFeedback(APRS_MODE_BCN_BUSY_CH);
		}
		return;
	}
	m->busySinceMs = 0U;
	m->reqManual = m->reqPtt = false;

	{
		aprsModeTxResult_t r;
		aprsModeBcnState_t st;

		AM_TRACE(211);   /* частота вільна: перед aprsModeTxBeacon() (далі 220..) */
		r = aprsModeTxBeacon(&m->eff);
		AM_TRACE(212);   /* aprsModeTxBeacon() повернув керування */

		switch (r)
		{
			case APRS_MODE_TX_OK:      st = APRS_MODE_BCN_SENT; break;
			case APRS_MODE_TX_NOCALL:  st = APRS_MODE_BCN_NOCALL; break;
			case APRS_MODE_TX_NOPOS:   st = APRS_MODE_BCN_NOPOS; break;
			case APRS_MODE_TX_INHIBIT: st = APRS_MODE_BCN_INHIBIT; break;
			case APRS_MODE_TX_BAND:    st = APRS_MODE_BCN_BAND; break;
			case APRS_MODE_TX_TOOBIG:  st = APRS_MODE_BCN_TOOBIG; break;
			default:                   st = APRS_MODE_BCN_FAILED; break;
		}
		m->bcnState = st;
		if (st == APRS_MODE_BCN_SENT)
		{
			m->beacons++;
			m->lastBeaconMs = (now != 0U) ? now : 1U;
		}
		else if (manual)
		{
			beaconFeedback(st);
		}
		/* Після будь-якої спроби (навіть невдалої через налаштування) періодичний відлік іде далі, а не щоциклу. */
		if (m->eff.interval != 0U)
		{
			m->nextBeaconMs = now + ((st == APRS_MODE_BCN_SENT) ? aprsModeIntervalMs(m->eff.interval) : APRS_MODE_RETRY_MS);
		}
	}
}

/* ---- для приймача -------------------------------------------------------------------------------------------- */

bool aprsModeOwnInfo(char call[8], uint8_t *ssid, bool *hasPos, int32_t *latU, int32_t *lonU)
{
	const aprsModeEff_t *e;

	if (aprsModeIsActive() == false)
	{
		return false;
	}
	e = &mem()->eff;
	memset(call, 0, 8);
	memcpy(call, e->call, 6);
	*ssid = e->ssid;
	*hasPos = e->hasPos;
	*latU = e->latU;
	*lonU = e->lonU;
	return true;
}

void aprsModeOnFrame(const aprsAx25_t *ax, const aprsPacket_t *pkt, bool hasGeo, uint32_t distM, uint16_t bearing)
{
	aprsModeMem_t *m;

	if (aprsModeIsActive() == false)
	{
		return;
	}
	m = mem();
	m->last.valid = true;
	m->last.type = pkt->type;
	m->last.hasGeo = hasGeo;
	m->last.distM = distM;
	m->last.bearing = bearing;
	m->last.ms = ticksGetMillis();
	snprintf(m->last.src, sizeof(m->last.src), "%s", ax->src);
	snprintf(m->last.dst, sizeof(m->last.dst), "%s", ax->dst);
}

#endif /* APRS_RX */
