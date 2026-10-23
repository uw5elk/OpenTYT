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
#include "functions/aprs_fault.h"   /* R10-fix4: крок трасування -> backup-регістри, kick сторожа */

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
#include "hardware/SPI_Flash.h"   /* R17: ensureCustomRegion() */
#include "io/buttons.h"
#include "user_interface/languages/aprsmode_ua.h"
#include <string.h>
#include <stdio.h>
#include <math.h>

extern const uint16_t initialIntervalsInSecs[];   /* aprs.c */

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
	aprsModeStore_t        store;          /* APRS-unify: слот конфігу APRS + ім'я рації -- ЄДИНЕ сховище станційних полів (cfg лишився «чернеткою») */
	uint8_t                slotIdx;        /* номер слота (1..8), з яким працюємо */
	bool                   blockLoaded;    /* блок режиму був у флеші */
	bool                   storeDirty;     /* слот змінено, ще не записано в кодплуг */
	bool                   nameDirty;      /* ім'я рації змінено, ще не записано */
	CodeplugChannel_t      chan;           /* «канал» режиму: на нього вказує currentChannelData, поки режим активний */
	CodeplugChannel_t     *savedChan;
	bool                   beaconWasRunning;   /* стоковий авто-бікон працював до входу (відновити при виході) */
	bool                   dirty;
	bool                   saveFailShown;   /* R17: «Не збережено» уже показано в цьому сеансі */
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
	/* R17 Г1: «Передати маяк» з меню: 0 -- нема; 1 -- повідомити про результат; 2 -- повідомити й вийти з режиму (режим був увімкнений лише заради маяка) */
	uint8_t                oneShot;
	aprsModeUi_t           ui;   /* лишається для aprsModeEnter() (m->ui.page); екрани живуть у блоці сесії (msgSessionUi()) */
	/* R11-fix2: список і черга повідомлень APRS більше НЕ тут -- це ПОСТІЙНИЙ блок (bgBox()), що живе й поза режимом. */
#if defined(APRS_MODE_TRACE)
	uint32_t               trSeen;         /* R10-fix: які номери тік-трасування (60..91) уже показано після входу/маяка */
#endif
} aprsModeMem_t;

#if defined(ENABLE_CALL_REPLAY)
static inline aprsModeMem_t *mem(void)
{
	size_t n = 0;

	return (aprsModeMem_t *)callReplayBorrow(&n);
}
_Static_assert(sizeof(aprsModeMem_t) <= (CALL_REPLAY_GROUPS * CALL_REPLAY_GROUP_BYTES), "aprsModeMem_t does not fit the call replay ring");
/* R11-fix2: ПОСТІЙНИЙ блок повідомлень -- у зарезервованій частині буфера «Переслухати», яку режим не позичає (callReplay.c). */
_Static_assert(sizeof(aprsMsgBox_t) <= CALL_REPLAY_APRS_BOX_BYTES, "aprsMsgBox_t does not fit the call replay APRS reserve");
_Static_assert(sizeof(aprsModeUi_t) <= CALL_REPLAY_APRS_UI_BYTES, "aprsModeUi_t does not fit the call replay APRS reserve (standalone messages screen)");
_Static_assert((CALL_REPLAY_APRS_BOX_BYTES % 8U) == 0U, "standalone messages screen must stay 8-aligned");
/* R13: стан екрана «Повідом. APRS» без режиму -- за блоком повідомлень у тому самому резерві. */
static inline aprsModeUi_t *msgSessionUi(void)
{
	size_t n = 0;

	return (aprsModeUi_t *)(void *)((uint8_t *)callReplayReserved(&n) + CALL_REPLAY_APRS_BOX_BYTES);
}
/* R16: історія прийому (журнал кадрів + маяк кожної станції) -- у тому ж резерві, за блоком і станом екрана. Обнуляє callReplayBorrowReset(). */
_Static_assert(sizeof(aprsHist_t) <= CALL_REPLAY_APRS_HIST_BYTES, "aprsHist_t does not fit the call replay APRS reserve");
_Static_assert(CALL_REPLAY_APRS_BOX_BYTES + CALL_REPLAY_APRS_UI_BYTES + CALL_REPLAY_APRS_HIST_BYTES == CALL_REPLAY_APRS_RESERVE_BYTES, "APRS reserve layout");
_Static_assert(((CALL_REPLAY_APRS_BOX_BYTES + CALL_REPLAY_APRS_UI_BYTES) % 8U) == 0U, "history block must stay 8-aligned");
static inline aprsHist_t *histBlk(void)
{
	size_t n = 0;

	return (aprsHist_t *)(void *)((uint8_t *)callReplayReserved(&n) + CALL_REPLAY_APRS_BOX_BYTES + CALL_REPLAY_APRS_UI_BYTES);
}
static inline aprsMsgBox_t *bgBox(void)
{
	size_t n = 0;

	return (aprsMsgBox_t *)callReplayReserved(&n);
}
#else
static aprsModeMem_t s_modeMem __attribute__((section(".aes_ccmram"), aligned(8)));   /* CCM-INIT(aprsModeEnter): memset перед першим використанням; усі читачі діють лише при aprsModeIsActive() */
static inline aprsModeMem_t *mem(void)
{
	return &s_modeMem;
}
static aprsMsgBox_t s_msgBox __attribute__((section(".aes_ccmram"), aligned(8)));   /* CCM-INIT(aprsMsgBgInit) */
static aprsModeUi_t s_msgUi __attribute__((section(".aes_ccmram"), aligned(8)));    /* R13: екран «Повідом. APRS» без режиму (збірка без «Переслухати»); CCM-INIT(aprsModeMsgSessionOpen) */
static inline aprsModeUi_t *msgSessionUi(void)
{
	return &s_msgUi;
}
static inline aprsMsgBox_t *bgBox(void)
{
	return &s_msgBox;
}
static aprsHist_t s_hist __attribute__((section(".aes_ccmram"), aligned(8)));   /* CCM-INIT(aprsMsgBgInit): R16, збірка без «Переслухати» */
static inline aprsHist_t *histBlk(void)
{
	return &s_hist;
}
#endif

#if defined(APRS_MODE_TRACE)
/* R10-fix (R10-fix5: ПОСТІЙНЕ під APRS_RX): трасування на екран. Не залежить від сповіщень (displayRenderWithoutNotification) і не чіпає стан
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
	/* R10-fix4: крок і час пишемо в backup-регістри ДО малювання (там же сторож і звіт збою читають «останній крок»), а t=
	 * береться звідти ж, а не зі стану режиму: в r10fix3 рядок t= на залізі не з'являвся (залежав від mem()->trT0 і
	 * aprsModeIsActive()) -- тепер він є на КОЖНОМУ кадрі, відлік від початку серії (мітка перед trxSetTX, або перший крок
	 * після паузи > 3 с). */
	uint32_t tMs = aprsFaultTraceNote((uint32_t)n, (uint32_t)((v == TRACE_NO_V) ? 0UL : v));

	if (HAL_DMA_GetState(&hdma_memtomem_dma2_stream0) != HAL_DMA_STATE_READY)
	{
		(void)HAL_DMA_Abort(&hdma_memtomem_dma2_stream0);
		dmaFixed = true;
	}
	snprintf(b, sizeof(b), "%u", n);
	displayClearBuf();
	displayPrintCentered(2, "APRS TRACE F4", FONT_SIZE_2);   /* F4 -- маркер збірки R10-fix4 (видно, яка прошивка на залізі) */
	snprintf(c, sizeof(c), "t=%lu ms", (unsigned long)tMs);
	displayPrintCentered(20, c, FONT_SIZE_2);
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
	APRS_FAULT_KICK();
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
	aprsFaultTraceMark();   /* R10-fix4: t=0 у backup-регістрах (не залежить від стану режиму) */
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

static bool saveCfg(aprsModeMem_t *m);   /* R17: потрібна сесії налаштувань раніше за визначення */
static uint32_t periodMs(void);

bool aprsModeIsActive(void)
{
	return (aprsRxUi()->modeOn != 0U);
}

/* R17 Г1: стан екранів («Повідом. APRS», «Налаштування») ЗАВЖДИ в блоці сесії (резерв постійного блока), а не в позиченому буфері режиму: екрани
 * живуть і з увімкненим «Слухати APRS», і без нього. mem()->ui тепер лише для aprsModeEnter(). */
aprsModeUi_t *aprsModeUi(void)
{
#if defined(ENABLE_CALL_REPLAY)
	return msgSessionUi();
#else
	return &s_msgUi;
#endif
}

/* Сесія екрана: msgOn == 1 -- «Повідом. APRS»; 2 -- «Налаштування» (разом із сесією налаштувань: кільце позичене, стан у mem()). */
bool aprsModeMsgSessionOpen(void)
{
	aprsModeUi_t *u;

	if (aprsRxUi()->msgOn != 0U)
	{
		aprsModeMsgSessionClose();   /* інша сесія (налаштування) -- спершу її (зберегти, віддати кільце) */
	}
	u = aprsModeUi();
	memset(u, 0, sizeof(*u));
	u->page = APRS_MODE_PAGE_MESSAGES;
	aprsRxUi()->msgOn = 1U;
	return true;
}

bool aprsModeCfgSessionActive(void)
{
	return (aprsRxUi()->msgOn == 2U) && (aprsRxUi()->modeOn == 0U);
}

void aprsModeMsgSessionClose(void)
{
	if (aprsModeCfgSessionActive())
	{
		aprsModeMem_t *m = mem();   /* кільце позичене сесією -- mem() його не обнуляє */

		if (m->dirty)
		{
			(void)saveCfg(m);
		}
		/* стокові параметри бікона: застосувати, лише якщо вони змінилися (aprsBeaconingSetSettings() сама порівнює і тоді перезапускає бікон) */
		aprsBeaconingSetSettings(&aprsSettingsCopy);
		(void)aprsBeaconCfgStore();   /* APRS-unify: блок налаштувань бікона -- основне сховище (разом із «Вікном маяка», яке застосовується одразу) */
		settingsSaveIfNeeded(true);
		resetOriginalSettingsData();
#if defined(ENABLE_CALL_REPLAY)
		callReplayRelease();
#endif
	}
	aprsRxUi()->msgOn = 0U;
}

bool aprsModeMsgSessionActive(void)
{
	return (aprsRxUi()->msgOn != 0U);
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

	if ((m->nextBeaconMs == 0U) || (periodMs() == 0U))
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
	m->blockLoaded = true;
	if ((codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG, blk, (int)sizeof(blk)) == false) ||
			(aprsModeCfgFromBytes(&m->cfg, blk, sizeof(blk)) == false))
	{
		aprsModeCfgInit(&m->cfg);   /* блоку нема (нова установка) або він зіпсований -- усе типове */
		m->blockLoaded = false;
	}
}

/* R17 (Г2): регіон custom-data у флеші рації, де його ще ніхто не ініціалізував (усе 0xFF), НЕ має "OpenGD77"-магії -- і codeplugSetOpenGD77CustomData()
 * тоді мовчки повертає false: блок ніколи не записується. Раніше saveCfg() ні готував регіон, ні дивився на результат -- налаштування режиму жили
 * лише в RAM, а після виходу з меню «APRS» і повторного входу знову були типовими (символ -- «людина» з конфігу кодплуга). Решта форку (ключі AES, теми,
 * RCTL, SMS) викликає dmrAesEnsureCustomDataRegion() ПЕРЕД записом -- тут те саме, але без залежності від ENABLE_AES. Ту саму магію (12 байт, далі 0xFF --
 * порожній блок) пише й вона; SPI_Flash_write робить read-modify-write сектора, решту регіону не чіпає. */
static bool ensureCustomRegion(void)
{
	uint8_t hdr[12];

	if (SPI_Flash_read(FLASH_ADDRESS_OFFSET + 0, hdr, 12) == false)
	{
		return false;
	}
	if (memcmp(hdr, "OpenGD77", 8) == 0)
	{
		return true;
	}
	memcpy(hdr, "OpenGD77", 8);
	hdr[8] = hdr[9] = hdr[10] = hdr[11] = 0xFF;
	return SPI_Flash_write(FLASH_ADDRESS_OFFSET + 0, hdr, 12);
}

/* APRS-unify: слот і ім'я рації -> кодплуг (лише якщо змінено; самі функції запису порівнюють байти з наявними й EEPROM_Write викликають, тільки коли вони різні). */
static bool saveStore(aprsModeMem_t *m)
{
	bool ok = true;

	if (m->nameDirty)
	{
		char nm[APRSM_NAME_RAW_LEN + 1U];
		size_t k = 0;

		while ((k < APRSM_NAME_RAW_LEN) && (m->store.name[k] != 0xFFU) && (m->store.name[k] != 0U))
		{
			nm[k] = (char)m->store.name[k];
			k++;
		}
		nm[k] = 0;
		ok = codeplugSetRadioName(nm, NULL);
	}
	if (m->storeDirty)
	{
		if (codeplugAPRSSetDataForIndex((int)m->slotIdx, (const CodeplugAPRSConfig_t *)(const void *)&m->store.raw, NULL))
		{
			m->store.rawValid = true;
		}
		else
		{
			ok = false;
		}
	}
	m->storeDirty = m->nameDirty = false;
	return ok;
}

/* true -- блок записано І прочитано назад однаковим. Невдача -- одне сповіщення «Не збережено» за сеанс (далі тихо: не дратуємо на кожному кроці). */
static bool saveCfg(aprsModeMem_t *m)
{
	uint8_t blk[APRSM_BLOCK_LEN], back[APRSM_BLOCK_LEN];
	bool ok;

	aprsModeCfgToBytes(&m->cfg, blk);
	memset(back, 0, sizeof(back));
	ok = ensureCustomRegion() &&
			codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG, blk, (int)sizeof(blk)) &&
			codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG, back, (int)sizeof(back)) &&
			(memcmp(blk, back, sizeof(blk)) == 0);
	ok = saveStore(m) && ok;
	m->dirty = false;
	if ((ok == false) && (m->saveFailShown == false))
	{
		m->saveFailShown = true;
		uiNotificationShowShort(1500, APRSM_SAVE_FAIL, true);
		soundSetMelody(MELODY_ERROR_BEEP);
	}
	return ok;
}

/* APRS-unify: слот, з яким працюємо, -- той, що призначено каналу, з якого зайшли (aprsConfigIndex); немає чи недійсний -- слот №1; конфігів у кодплузі нема
 * зовсім -- заготовка (aprsModeStoreBlank()), яка потрапить у кодплуг під номером 1 лише після першої зміни. Ім'я рації читаємо з кодплуга. */
static void loadStore(aprsModeMem_t *m)
{
	CodeplugAPRSConfig_t cp;
	char nm[16];
	int cnt = codeplugAPRSConfigGetCount();
	int idx = 1;

	_Static_assert(sizeof(aprsModeRawCfg_t) == sizeof(CodeplugAPRSConfig_t), "aprsModeRawCfg_t != CodeplugAPRSConfig_t");
	if ((m->savedChan != NULL) && (m->savedChan->aprsConfigIndex != 0U) && ((int)m->savedChan->aprsConfigIndex <= cnt))
	{
		idx = (int)m->savedChan->aprsConfigIndex;
	}
	m->slotIdx = (uint8_t)idx;
	aprsModeStoreBlank(&m->store);
	if (codeplugAPRSGetDataForIndex(idx, &cp))
	{
		memcpy(&m->store.raw, &cp, sizeof(m->store.raw));
		m->store.rawValid = true;
	}
	memset(nm, 0, sizeof(nm));
	codeplugGetRadioName(nm);
	memset(m->store.name, 0xFF, sizeof(m->store.name));
	memcpy(m->store.name, nm, strnlen(nm, sizeof(m->store.name)));
	m->storeDirty = m->nameDirty = false;
}

static void buildDefaults(aprsModeMem_t *m)
{
	bool posOk = settingsLocationIsValid();
	int32_t latU = 0, lonU = 0;

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
	/* заготовка слота теж повноцінний конфіг (rawValid для DefaultsBuild -- завжди true): інакше правки в ній не потрапили б у типові значення */
	aprsModeDefaultsBuild(&m->def, &m->store.raw, true, (const char *)m->store.name, posOk, latU, lonU);
}

/* ---- APRS-unify (L5.3): блок налаштувань стокового бікона ---------------------------------------------------------------------------------------- */

static uint8_t clampU8(uint8_t v, uint8_t lo, uint8_t hi)
{
	return (v < lo) ? lo : ((v > hi) ? hi : v);
}

/* Блок -> працюючі налаштування (на старті, ПЕРЕД aprsBeaconingInit()). restoreDefaults == true (скидання налаштувань при вмиканні) -- блок НЕ застосовується,
 * навпаки, його перезаписують з поточних (типових). Блока нема чи він зіпсований -- створюється з поточних налаштувань. */
void aprsBeaconCfgBoot(bool restoreDefaults)
{
	uint8_t blk[APRSB_BLOCK_LEN];
	aprsBeaconCfg_t c;

	memset(blk, 0, sizeof(blk));
	if ((restoreDefaults == false) &&
			codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_APRS_BEACON_CFG, blk, (int)sizeof(blk)) &&
			aprsBeaconCfgFromBytes(&c, blk, sizeof(blk)))
	{
		aprsBeaconingSettings_t st;

		aprsBeaconingGetSettings(&st);
		st.mode = (aprsBeaconingMode_t)c.mode;
		st.power = c.power;
		st.initialInterval = clampU8(c.initialInterval, APRS_BEACON_INITIAL_INTERVAL_MIN, APRS_BEACON_INITIAL_INTERVAL_MAX);
		/* стан: лише 4 збережувані біти (канал / GPS / затухання / стиснення); решта (HAS_*, ENABLED) -- поточні, змінні */
		st.state = (aprsBeaconingStates_t)(((uint8_t)st.state & 0xE1U) | (uint8_t)((c.stateBits & 0x0FU) << 1));
		st.smart.slowRate = clampU8(c.slowRate, APRS_SMART_BEACON_SLOW_RATE_MIN, APRS_SMART_BEACON_SLOW_RATE_MAX);
		st.smart.fastRate = clampU8(c.fastRate, APRS_SMART_BEACON_FAST_RATE_MIN, APRS_SMART_BEACON_FAST_RATE_MAX);
		st.smart.lowSpeed = clampU8(c.lowSpeed, APRS_SMART_BEACON_LOW_SPEED_MIN, APRS_SMART_BEACON_LOW_SPEED_MAX);
		st.smart.highSpeed = clampU8(c.highSpeed, APRS_SMART_BEACON_HIGH_SPEED_MIN, APRS_SMART_BEACON_HIGH_SPEED_MAX);
		st.smart.turnAngle = clampU8(c.turnAngle, APRS_SMART_BEACON_TURN_ANGLE_MIN, APRS_SMART_BEACON_TURN_ANGLE_MAX);
		st.smart.turnSlope = clampU8(c.turnSlope, APRS_SMART_BEACON_TURN_SLOPE_MIN, APRS_SMART_BEACON_TURN_SLOPE_MAX);
		st.smart.turnTime = clampU8(c.turnTime, APRS_SMART_BEACON_TURN_TIME_MIN, APRS_SMART_BEACON_TURN_TIME_MAX);
		aprsBeaconingBootSet(&st);
		aprsRxBcnWinSetMode(c.bcnWin);
		return;
	}
	(void)aprsBeaconCfgStore();
}

/* Працюючі налаштування -> блок. Пише лише якщо байти відрізняються від наявних. */
bool aprsBeaconCfgStore(void)
{
	aprsBeaconingSettings_t st;
	aprsBeaconCfg_t c;
	uint8_t blk[APRSB_BLOCK_LEN], cur[APRSB_BLOCK_LEN];

	aprsBeaconingGetSettings(&st);
	c.mode = (uint8_t)st.mode;
	c.power = st.power;
	c.initialInterval = st.initialInterval;
	c.stateBits = (uint8_t)(((uint8_t)st.state >> 1) & 0x0FU);
	c.slowRate = st.smart.slowRate;
	c.fastRate = st.smart.fastRate;
	c.lowSpeed = st.smart.lowSpeed;
	c.highSpeed = st.smart.highSpeed;
	c.turnAngle = st.smart.turnAngle;
	c.turnSlope = st.smart.turnSlope;
	c.turnTime = st.smart.turnTime;
	c.bcnWin = aprsRxBcnWinMode();
	aprsBeaconCfgToBytes(&c, blk);
	memset(cur, 0, sizeof(cur));
	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_APRS_BEACON_CFG, cur, (int)sizeof(cur)) && (memcmp(cur, blk, sizeof(blk)) == 0))
	{
		return true;
	}
	return ensureCustomRegion() && codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_APRS_BEACON_CFG, blk, (int)sizeof(blk));
}

/* Одноразова міграція старого блоку (оверрайди, інтервал, qsyOff, позивник) у слот / ім'я рації / стоковий initialInterval -- aprsModeMigrate(). */
static void unifyMigrate(aprsModeMem_t *m)
{
	aprsBeaconingSettings_t st;
	uint8_t init;
	unsigned r;

	if (m->cfg.ov & APRSM_OV_MIGRATED)
	{
		return;
	}
	aprsBeaconingGetSettings(&st);
	init = st.initialInterval;
	r = aprsModeMigrate(&m->cfg, &m->store, &m->def, &init, initialIntervalsInSecs, (unsigned)APRS_BEACON_INITIAL_INTERVAL_MAX + 1U);
	m->storeDirty = ((r & APRSM_FOLD_RAW) != 0U);
	m->nameDirty = ((r & APRSM_FOLD_NAME) != 0U);
	if (r & APRSM_FOLD_INIT)
	{
		st.initialInterval = init;
		aprsBeaconingSetSettings(&st);   /* перезапускає стоковий бікон і сам упаковує в nonVolatileSettings */
		(void)aprsBeaconCfgStore();
	}
	buildDefaults(m);
	if (m->blockLoaded || ((r & ~APRSM_FOLD_BLOCK) != 0U))   /* свіжа установка без змін -- блок не пишемо */
	{
		(void)saveCfg(m);
	}
}

/* «Канал» режиму: аналоговий FM, 25 кГц (APRS-ui M1; було 12,5 кГц -- в шапці "FMN"), без CSS і
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
	codeplugChannelSetFlag(&m->chan, CHANNEL_FLAG_BW_25K, APRS_BEACON_BW_25K ? 1 : 0);   /* APRS-ui M1: 25 кГц */
}

#if defined(APRS_R21_QSY)
/* R21 З4: рядок QSY для коментаря маяка -- з каналу, з якого зайшли в режим (savedChan; під час режиму currentChannelData вказує на «канал» режиму з
 * частотою APRS, а не на канал користувача). Правила стокової (aprs.c): частота RX, тон RX (CTCSS «C», DCS «D»; цифровий канал -- без тону), зсув TX-RX,
 * смуга 25 кГц -- великі літери, 12,5 -- малі. Порожній рядок -- QSY вимкнено в налаштуваннях або каналу нема. */
static void qsyForChannel(const aprsModeMem_t *m, char *out, size_t cap)
{
	const CodeplugChannel_t *ch = m->savedChan;
	char kind = 0;
	unsigned val = 0;
	bool wide = true;

	if (cap > 0U)
	{
		out[0] = 0;
	}
	if (((m->eff.flags & APRSM_RAW_FLAG_QSY) == 0U) || (ch == NULL))
	{
		return;
	}
	if ((ch->chMode == RADIO_MODE_ANALOG) && (ch->rxTone != CODEPLUG_CSS_TONE_NONE))
	{
		CodeplugCSSTypes_t t = codeplugGetCSSType(ch->rxTone);

		if (t == CSS_TYPE_CTCSS)
		{
			kind = 'C';
			val = (unsigned)(ch->rxTone / 10U);
		}
		else if (t & CSS_TYPE_DCS)
		{
			kind = 'D';
			val = (unsigned)(ch->rxTone & ~CSS_TYPE_DCS_MASK);
		}
	}
	if (ch->chMode == RADIO_MODE_ANALOG)
	{
		wide = (codeplugChannelGetFlag((CodeplugChannel_t *)ch, CHANNEL_FLAG_BW_25K) != 0U);
	}
	(void)aprsModeQsyFormat(out, cap, ch->rxFreq, ch->txFreq, kind, val, wide);
}

#endif /* APRS_R21_QSY */

static void tune(const aprsModeMem_t *m)
{
	uint32_t f = m->eff.freq;

	AM_TRACE(30);   /* перед radioSetTRxDevice */
	radioSetTRxDevice(RADIO_DEVICE_PRIMARY);
	AM_TRACE(31);   /* перед trxSetFrequency */
	trxSetFrequency(f, f, DMR_MODE_AUTO);
	AM_TRACE(32);   /* перед trxSetModeAndBandwidth */
	trxSetModeAndBandwidth(RADIO_MODE_ANALOG, APRS_BEACON_BW_25K);   /* APRS-ui M1: 25 кГц (стандарт APRS); у збірках без приймача APRS_BEACON_BW_25K = false */
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

/* APRS-unify (L3): інтервал періодичного маяка режиму -- той самий, що в стокового бікона: initialIntervalsInSecs[initialInterval], і лише коли стоковий
 * режим бікона «Авто» або «Розумний маяк». «Вимкнено» = режим бікона «Вимкн.»/«Вручну»/«PTT» (окремого «вимкнено» для інтервалу нема). 0 -- періодичного нема. */
static uint32_t periodMs(void)
{
	aprsBeaconingSettings_t st;

	aprsBeaconingGetSettings(&st);
	if ((st.mode != APRS_BEACONING_MODE_AUTO) && (st.mode != APRS_BEACONING_MODE_SMART_BEACONING))
	{
		return 0U;
	}
	return (uint32_t)initialIntervalsInSecs[(st.initialInterval <= APRS_BEACON_INITIAL_INTERVAL_MAX) ? st.initialInterval : 0U] * 1000UL;
}

static void scheduleBeacons(aprsModeMem_t *m, uint32_t now)
{
	uint32_t p = periodMs();

	m->nextBeaconMs = (p != 0U) ? (now + p) : 0U;
	if ((m->nextBeaconMs == 0U) && (p != 0U))
	{
		m->nextBeaconMs = 1U;
	}
}

void aprsModeCfgChanged(uint16_t what)
{
	aprsModeMem_t *m = mem();
	uint32_t now = ticksGetMillis();
	uint32_t oldFreq = m->eff.freq;

	/* APRS-unify: чернетку (ov-біти) одразу складаємо в слот; запис у кодплуг -- після паузи (aprsModeCfgSessionTick()/aprsModeTick()) або при закритті сесії */
	if (aprsModeFold(&m->cfg, &m->store, &m->def) & APRSM_FOLD_RAW)
	{
		m->storeDirty = true;
	}
	buildDefaults(m);
	aprsModeEffective(&m->cfg, &m->def, &m->eff);
	m->chan.sql = m->eff.sql;
	/* R17 Г1: у сесії налаштувань (режим не активний, рація стоїть на звичайному каналі) радіо не чіпаємо -- лише перераховуємо й відкладаємо запис */
	if (aprsModeIsActive())
	{
		if (m->eff.freq != oldFreq)
		{
			m->chan.rxFreq = m->chan.txFreq = m->eff.freq;
			if (aprsTxProgress == APRS_TX_IDLE)
			{
				tune(m);
			}
		}
	}
	(void)what;
	m->dirty = true;
	m->dirtyAtMs = now;
}

void aprsModeCfgReset(void)
{
	aprsModeMem_t *m = mem();

	aprsModeCfgInit(&m->cfg);
	m->cfg.ov = APRSM_OV_MIGRATED;   /* станційні поля живуть у кодплузі -- «Скинути» їх не чіпає (це лише шумодав і чернетка) */
	aprsModeCfgChanged(APRSM_OV_ALL);
}

/* APRS-unify: позивний -- ім'я рації (EEPROM 0x00E0). false -- не пройшов перевірку (1..6 символів A-Z 0-9). */
bool aprsModeSetCall(const char *call)
{
	aprsModeMem_t *m = mem();
	bool valid = false;

	if (aprsModeStoreSetCall(&m->store, call, &valid))
	{
		m->nameDirty = true;
	}
	aprsModeCfgChanged(0U);
	return valid;
}

/* APRS-unify: прапорці слота (300 бод, QSY, «тихо», «використовувати позицію») -- APRSM_RAW_FLAG_*. */
void aprsModeSetFlag(uint8_t mask, bool on)
{
	aprsModeMem_t *m = mem();

	aprsModeStoreSetFlag(&m->store, mask, on);
	m->storeDirty = true;
	aprsModeCfgChanged(0U);
}

/* Назва слота (для шапки екрана налаштувань): до 8 символів + NUL. */
void aprsModeSlotName(char out[9])
{
	const aprsModeMem_t *m = mem();
	size_t k = 0;

	while ((k < 8U) && (m->store.raw.name[k] != (char)0xFF) && (m->store.raw.name[k] != 0))
	{
		out[k] = m->store.raw.name[k];
		k++;
	}
	out[k] = 0;
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
	aprsRxUi()->msgOn = 0U;   /* R13: екран «Повідом. APRS» без режиму і сам режим одночасно не живуть */
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
	AM_TRACE(10);  /* перед loadStore/buildDefaults/unifyMigrate */
	loadStore(m);
	buildDefaults(m);
	unifyMigrate(m);
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
		bgBox()->txSeen = 1U;   /* R11-fix2: передачу обірвано синхронно -- фоновий тік мусить відмітити її кінець (пауза 2 с, txActive) */
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

/* ---- R17 Г1: сесія налаштувань і «Передати маяк» з меню ------------------------------------------------------------ */

/* Відкрити сесію налаштувань: режим «Слухати APRS» вимикається (налаштування стокового бікона й режиму змінюються, коли рація НЕ паркована на частоті
 * APRS), кільце «Переслухати» позичається під стан (cfg/def/eff), налаштування читаються з флешу. Радіо не чіпається. false -- зараз не можна (йде передача). */
bool aprsModeSettingsSessionOpen(void)
{
	aprsModeMem_t *m;
	aprsModeUi_t *u;
	size_t sz = 0;
	void *base;

	if (aprsModeCfgSessionActive())
	{
		return true;
	}
	aprsModeExit();   /* ідемпотентно */
	if ((aprsTxProgress != APRS_TX_IDLE) || trxTransmissionEnabled || trxIsTransmitting)
	{
		return false;
	}
	if (aprsRxUi()->msgOn != 0U)
	{
		aprsModeMsgSessionClose();
	}
	callReplayStop();
#if defined(ENABLE_CALL_REPLAY)
	base = callReplayBorrow(&sz);
	if ((sz < sizeof(aprsModeMem_t)) || ((((uintptr_t)base) & 7U) != 0U))
	{
		callReplayRelease();
		return false;
	}
#else
	(void)sz;
	base = &s_modeMem;
#endif
	m = (aprsModeMem_t *)base;
	memset(m, 0, sizeof(*m));
	m->magic = APRS_MODE_MAGIC;
	m->savedChan = currentChannelData;
	loadCfg(m);
	loadStore(m);
	buildDefaults(m);
	unifyMigrate(m);
	aprsModeEffective(&m->cfg, &m->def, &m->eff);
	aprsBeaconingGetSettings(&aprsSettingsCopy);   /* стокові параметри бікона редагуються в копії (як у стоковому меню) і застосовуються при закритті сесії */
#if defined(HAS_GPS) && defined(FORK_NO_GPS_MENU)
	/* APRS-ui M5: GPS у рації нема, рядок «Джерело» прихований -- джерело позиції безальтернативне: «з каналу / вручну». Якщо в блоці (наприклад,
	 * записаному з ПК) стояв біт «GPS», знімаємо його у чернетці; на закритті сесії зміна збережеться тим самим шляхом, що й решта. */
	if ((aprsSettingsCopy.state & APRS_BEACONING_STATE_LOCATION_FROM_GPS) != 0U)
	{
		aprsSettingsCopy.state = (aprsBeaconingStates_t)(((uint8_t)aprsSettingsCopy.state & (uint8_t)~(APRS_BEACONING_STATE_LOCATION_FROM_GPS)) |
				(uint8_t)APRS_BEACONING_STATE_LOCATION_FROM_CHANNEL);
	}
#endif
	u = aprsModeUi();
	memset(u, 0, sizeof(*u));
	u->page = APRS_MODE_PAGE_SETTINGS;
	aprsRxUi()->msgOn = 2U;
	return true;
}

/* З тіка меню: запис у флеш після паузи в редагуванні (як aprsModeTick() у режимі). */
void aprsModeCfgSessionTick(void)
{
	aprsModeMem_t *m;

	if (aprsModeCfgSessionActive() == false)
	{
		return;
	}
	m = mem();
	if (m->dirty && ((ticksGetMillis() - m->dirtyAtMs) >= APRS_MODE_SAVE_IDLE_MS))
	{
		(void)saveCfg(m);
	}
}

/* «Передати маяк». Режим уже слухає -- звичайний запит маяка; ні -- рація «паркується», передає ТИМ САМИМ кодом (aprsModeTick()/aprsModeTxBeacon()) і
 * повертається (aprsModeBeaconOncePoll() виходить з режиму після передачі). false -- зараз не можна. */
bool aprsModeBeaconOnce(void)
{
	aprsModeMem_t *m;

	if (aprsModeIsActive())
	{
		if (aprsModeIsTransmitting())
		{
			return false;
		}
		aprsModeRequestBeacon();
		mem()->oneShot = 1U;
		return true;
	}
	if (aprsModeEnter() == false)
	{
		return false;
	}
	aprsModeRequestBeacon();
	m = mem();
	m->oneShot = 2U;
	return true;
}

bool aprsModeBeaconOnceBusy(void)
{
	return aprsModeIsActive() && (mem()->oneShot != 0U);
}

/* APRS-ui M4: головний екран (канал / VFO) -- чи це він. */
static bool isMainScreenMenu(int menuNumber)
{
	return (menuNumber == UI_CHANNEL_MODE) || (menuNumber == UI_VFO_MODE);
}

/* APRS-ui M4: явний перемалюнок головного екрана після разового маяка (SK1+3).
 * ПРИЧИНА («екран VFO з параметрами каналу, доки не натиснеш кнопку»): акорд SK1+3 починається з натискання SK1, а головний екран за SK1 показує
 * «параметри каналу» (RX/TX-частоти; прапорець uiDataGlobal.displayChannelSettings) і знімає їх лише коли бачить відпускання SK1. Поки йде разовий
 * маяк, тік каналу/VFO повертається зарані (aprsModeBeaconOnceBusy()) і відпускання SK1 ковтає, тож прапорець лишався піднятим, а перемалюнок після
 * виходу з режиму малював саме екран параметрів. Будь-яке наступне натискання доходило до обробника, той бачив «прапорець є, SK1 не затиснуто» і
 * ховав параметри -- тому екран «лагодився» від PTT. Це код стокового uiChannelMode.c/uiVFOMode.c, але чіпаємо тут, у нашому файлі: прапорець
 * знімаємо самі, меню НЕ перемикаємо (швидкі клавіші й сканування залежать від поточного меню). Перемалюнок -- синтетична FUNC_REDRAW, як у
 * uiNotificationHide(); якщо на екрані картка (помилка передачі), її закриття перемалює екран тим самим шляхом, а прапорець уже знято. */
static void repaintMainScreen(void)
{
	uiDataGlobal.displayChannelSettings = false;
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;

	if (uiNotificationIsVisible() == false)
	{
		uiEvent_t redrawEvent = { .buttons = 0, .keys = NO_KEYCODE, .rotary = 0, .function = FUNC_REDRAW, .events = FUNCTION_EVENT, .hasEvent = true,
				.time = ticksGetMillis() };

		menuSystemCallCurrentMenuTick(&redrawEvent);
	}
}

/* Кожен тік меню «APRS». Помилки (зайнято, нема позивного...) уже показала beaconFeedback(); APRS-ui M3: окремого сповіщення «Маяк надіслано» нема --
 * достатньо червоного «APRS» у шапці під час передачі. Режим, увімкнений лише заради маяка, вимикається, коли передачу завершено, і головний екран
 * перемальовується явно (repaintMainScreen()). */
void aprsModeBeaconOncePoll(void)
{
	aprsModeMem_t *m;
	uint8_t what;

	if (aprsModeBeaconOnceBusy() == false)
	{
		return;
	}
	m = mem();
	if (m->reqManual || m->reqPtt || (aprsTxProgress != APRS_TX_IDLE))
	{
		return;   /* ще чекає вільної частоти або передається */
	}
	what = m->oneShot;
	m->oneShot = 0U;
	if ((what == 2U) || (isMainScreenMenu(menuSystemGetCurrentMenuNumber())))
	{
		/* what == 1 на головному екрані: режим там і так вийшов би на наступному тіку (aprsModeTick(), «меню не APRS»), але без перемалювання */
		aprsModeExit();   /* m недійсне; канал/VFO повернуто */
		repaintMainScreen();
	}
}

/* R18 Д5: гаряча клавіша SK1+3 (канал і VFO) -- разовий маяк «Режиму APRS» (колишній пункт меню «Передати маяк»). Заборону TX і зайнятість показує
 * повноекранна картка. Повторне натискання, поки маяк іде, нічого не робить. */
void aprsModeBeaconHotkey(void)
{
	if (aprsModeBeaconOnceBusy())
	{
		return;
	}
	if (txInhibitCheckAndWarn())
	{
		return;
	}
	if (aprsModeBeaconOnce() == false)
	{
		uiNotificationShowShort(1500, APRSM_NOT_NOW, true);
		soundSetMelody(MELODY_ERROR_BEEP);
	}
}

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
		uiNotificationShowShort(1500, txt, true);
		soundSetMelody(MELODY_ERROR_BEEP);
	}
}

/* ---- R11: повідомлення APRS ------------------------------------------------------------------------------------- */

aprsMsgBox_t *aprsModeMsgBox(void)
{
	return bgBox();
}

/* Старт прошивки (applicationMain.c, ПІСЛЯ callReplayBorrowReset()): CCM там сміття, блок постійний. Годинник рації тут ще не читаємо
 * (ранній старт) -- лічильник номерів «розсіюється» ним при першому нашому повідомленні (aprsModeMsgSend()). */
void aprsMsgBgInit(void)
{
	aprsMsgInit(bgBox(), ticksGetMillis() / 997U);
#if !defined(ENABLE_CALL_REPLAY)
	memset(&s_hist, 0, sizeof(s_hist));   /* з «Переслухати» резерв обнуляє callReplayBorrowReset() */
#endif
}

aprsHist_t *aprsModeHist(void)
{
	return histBlk();
}

bool aprsModeHasCall(void)
{
	return aprsModeIsActive() && aprsModeCallValid(mem()->eff.call);
}

/* R13 (П.6): ПОТОЧНИЙ власний позивний-SSID для нового завдання черги — «CALL» або «CALL-SS». У «Режимі APRS» — позивний/SSID режиму,
 * поза ним — ім'я рації + SSID зі стокового конфігу APRS (рівно те, з чим передавав би бікон і що приймач вважає «нами»). Далі цей рядок
 * копіюється в завдання й НЕ змінюється, де б не був користувач. false — власного допустимого позивного нема. */
static bool ownIdent(char out[APRS_MSG_CALL_LEN])
{
	char call[8];
	uint8_t ssid = 0U;
	bool hp;
	int32_t la, lo;
	size_t n = 0;

	memset(call, 0, sizeof(call));
	if (aprsModeOwnInfo(call, &ssid, &hp, &la, &lo) == false)
	{
		aprsRxInfo_t info;

		if (aprsBeaconingGetRxInfo(&info, true) == false)
		{
			return false;
		}
		for (int i = 0; (i < 6) && (info.call[i] != 0) && (info.call[i] != ' '); i++)
		{
			char c = info.call[i];

			call[i] = ((c >= 'a') && (c <= 'z')) ? (char)(c - 'a' + 'A') : c;
		}
		ssid = info.ssid;
	}
	if ((aprsModeCallValid(call) == false) || (ssid > 15U))
	{
		return false;
	}
	n = strlen(call);
	memcpy(out, call, n);
	if (ssid != 0U)
	{
		out[n++] = '-';
		if (ssid >= 10U)
		{
			out[n++] = '1';
			out[n++] = (char)('0' + (ssid - 10U));
		}
		else
		{
			out[n++] = (char)('0' + ssid);
		}
	}
	out[n] = 0;
	return true;
}

/* Нове повідомлення в чергу. -1 — власного позивного нема; -2 — поза режимом і APRS вимкнено/призупинено (не передасться). Інакше AMSG_*. */
int aprsModeMsgSend(const char *to, const char *cp1251Text)
{
	char from[APRS_MSG_CALL_LEN];

	if (ownIdent(from) == false)
	{
		return -1;
	}
	if ((aprsModeIsActive() == false) && (aprsBeaconingMessagesAllowed() == false))
	{
		return -2;
	}
	{
		aprsMsgBox_t *b = bgBox();

		if (b->numSeeded == 0U)
		{
			/* перший номер -- «випадковий», щоб новий сеанс (перезапуск рації) не повторював номери попереднього */
			b->numSeeded = 1U;
			b->lastNum = (uint8_t)(((uint32_t)getRtcTime_custom() + (ticksGetMillis() / 997U)) % 99U);
		}
		return aprsMsgSend(b, to, cp1251Text, ticksGetMillis(), from);
	}
}

/* Вільна частота? У режимі -- за шумодавом «каналу» режиму; поза ним -- за активністю AFSK і несучою поточного каналу. */
static bool bgChannelBusy(void)
{
	if (aprsModeIsActive())
	{
		return channelBusy(mem());
	}
	return aprsRxBusy(APRS_MODE_RX_BUSY_MS) || (LedRead(LED_GREEN) != 0);
}

/* R11-fix2: ФОНОВА черга передачі повідомлень і ACK -- з головного циклу (applicationMain.c), ПЕРЕД aprsBeaconingTick(), тож ACK іде
 * раніше за періодичний бікон. Працює однаково в «Режимі APRS», на головному екрані, в меню, у списку станцій.
 * Умови передачі: APRS увімкнено, жодна інша передача/сканування, PTT не натиснуто, хотспот не вхопив рацію; зайнята частота --
 * чекаємо до 10 с, далі передаємо; між двома передачами пауза >= 2 с (все це в aprsMsgPoll()).
 * Шлях в ефір: у режимі -- aprsModeTxMessage() (рація вже на частоті APRS); поза режимом -- aprsBeaconingSendMessage() (QSY на
 * частоту APRS і назад, як у бікона). Перед передачею синхронно зупиняється приймач (aprsRxStopForTx() усередині обох), після --
 * його вмикає aprsRxTick(). */
void aprsMsgBgTick(void)
{
	aprsMsgBox_t *b = bgBox();
	uint32_t now = ticksGetMillis();
	char info[APRS_MSG_ADDR_LEN + 3U + APRS_MSG_UTF8_MAX + 8U + 8U];
	size_t n;
	bool txOk, modeOn;
	aprsModeTxResult_t r;

	if (aprsTxProgress != APRS_TX_IDLE)
	{
		b->txSeen = 1U;
		return;   /* передача йде (або стокова машина завершує її) */
	}
	if (b->txSeen)
	{
		b->txSeen = 0U;
		aprsMsgTxEnded(b, now);   /* кінець будь-якої передачі (маяк теж) -- від нього пауза 2 с */
	}
	if (aprsMsgQueueLen(b) == 0U)
	{
		return;
	}

	modeOn = aprsModeIsActive();
	if ((modeOn == false) && (aprsBeaconingMessagesAllowed() == false))
	{
		/* APRS вимкнено/бікон призупинено, режим закрито: ні ACK, ні повтори не підуть. Кому ACK уже не потрібен -- знімаємо, щоб
		 * вони не спрацювали пізніше, коли APRS знову ввімкнуть. Стан «чекає» наших повідомлень -> «без ACK». */
		aprsMsgCancelAll(b);
		return;
	}

	txOk = (trxTransmissionEnabled == false) && (trxIsTransmitting == false) && (uiDataGlobal.Scan.active == false) &&
			(settingsUsbMode != USB_MODE_HOTSPOT) && ((buttonsRead() & BUTTON_PTT) == 0U);
	n = aprsMsgPoll(b, now, bgChannelBusy(), txOk, info, sizeof(info));
	if (n == 0U)
	{
		return;
	}
	{
		const char *from = aprsMsgInflightFrom(b);   /* R13 (П.6): відправник зафіксовано в завданні — однаковий для всіх повторів */

		r = modeOn ? aprsModeTxMessage(&mem()->eff, info, from) : aprsBeaconingSendMessage(info, from);
	}
	switch (r)
	{
		case APRS_MODE_TX_OK:
			aprsMsgTxDone(b, now, true, false);
			b->txSeen = 1U;   /* кінець відмітимо, щойно aprsTxProgress знову стане IDLE */
			break;
		case APRS_MODE_TX_BUSY:
			aprsMsgTxDone(b, now, false, false);   /* зайнято чимось іншим -- спробуємо ще, спроба рахується */
			break;
		default:
			aprsMsgTxDone(b, now, false, true);    /* заборона TX, не FM, поза діапазоном, нема позивного -- марно повторювати */
			if (modeOn)
			{
				beaconFeedback((r == APRS_MODE_TX_INHIBIT) ? APRS_MODE_BCN_INHIBIT : ((r == APRS_MODE_TX_BAND) ? APRS_MODE_BCN_BAND :
						((r == APRS_MODE_TX_NOCALL) ? APRS_MODE_BCN_NOCALL : APRS_MODE_BCN_FAILED)));
			}
			break;
	}
}

/* Повідомлення/ACK, адресовані нам, ДО відсіву дублікатів (aprs_rx.c, frameDispatch()): ПОЗА залежністю від того, чи відкрито режим.
 * ACK на наше -- скасувати повтори; повідомлення з номером -- ACK негайно, на КОЖНУ копію (відправник повторює, доки не почує). */
void aprsMsgBgOnMessage(const aprsAx25_t *ax, const aprsPacket_t *pkt)
{
	aprsMsgBox_t *b = bgBox();

	if (pkt->type != APRS_T_MESSAGE)
	{
		return;
	}
	if (pkt->msgAck)
	{
		/* текст «ack12» / «rej12» (parseMessage гарантує довжину 4..8) */
		if (strlen(pkt->text) >= 4U)
		{
			(void)aprsMsgOnAckRx(b, ax->src, pkt->text + 3, pkt->text[0] == 'r');
		}
		return;
	}
	aprsMsgCountRx(b);
	if (pkt->msgId[0] != 0)
	{
		(void)aprsMsgQueueAck(b, ax->src, pkt->msgId, ticksGetMillis(), pkt->msgTo);   /* R13 (П.6): ACK від того, КОМУ адресовано (msgTo), а не від поточного налаштування */
	}
}

/* Нове (недублікат) повідомлення нам -- у список; у режимі ще й зсув вибраного рядка. true -- додано (нове). */
bool aprsMsgBgNewMessage(const aprsAx25_t *ax, const aprsPacket_t *pkt)
{
	aprsMsgBox_t *b = bgBox();

	if (aprsMsgOnIncoming(b, ax->src, pkt->text, pkt->msgId, ticksGetMillis()) == false)
	{
		return false;
	}
	if (aprsRxUi()->msgOn == 1U)
	{
		aprsModeUi_t *u = aprsModeUi();   /* R17: екран «Повідом. APRS» відкрито (з режимом чи без) */

		if (u->msg.sel > 0U)
		{
			u->msg.sel++;   /* нове зверху: вибраний запис зсунувся на один вниз */
			if (u->msg.sel >= APRS_MSG_LIST_MAX)
			{
				u->msg.sel = (uint8_t)(APRS_MSG_LIST_MAX - 1U);
			}
		}
	}
	return true;
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

	/* Режим живе лише в меню «APRS» і лише коли хотспот не вхопив рацію. R18: єдиний виняток -- разовий маяк (SK1+3) з головного екрана (канал/VFO),
	 * поки він не завершився: меню «Слухати» нема, режим вмикається тільки заради цього маяка. */
	{
		int curMenu = menuSystemGetCurrentMenuNumber();
		bool oneShotOnMain = (m->oneShot != 0U) && ((curMenu == UI_CHANNEL_MODE) || (curMenu == UI_VFO_MODE));

		if (((curMenu != MENU_APRS_HUB) && (oneShotOnMain == false)) || (settingsUsbMode == USB_MODE_HOTSPOT))
		{
			AM_TRACE(61);   /* aprsModeTick: меню не «APRS» (або хотспот) -- виходимо з режиму */
			aprsModeExit();
			return;
		}
	}
	if (m->oneShot != 0U)
	{
		aprsModeBeaconOncePoll();   /* R18: головний екран меню «APRS» не тікає -- опитуємо тут; може вийти з режиму */
		if (aprsModeIsActive() == false)
		{
			return;
		}
	}

	if (m->dirty && ((now - m->dirtyAtMs) >= APRS_MODE_SAVE_IDLE_MS))
	{
		AM_TRACE(62);   /* перед saveCfg у aprsModeTick */
		saveCfg(m);
	}

	if (aprsTxProgress != APRS_TX_IDLE)
	{
		return;   /* передача йде (або стокова машина завершує її); її кінець відмічає aprsMsgBgTick() */
	}
	if (aprsMsgAckPending(bgBox()) != 0U)
	{
		return;   /* R11-fix2: ACK чекає передачі -- він ПЕРШИЙ, маяк (запит лишається) іде після нього */
	}
	if ((m->bcnState == APRS_MODE_BCN_SENT) && (m->lastBeaconMs != 0U) && ((now - m->lastBeaconMs) > 3000U))
	{
		m->bcnState = APRS_MODE_BCN_NONE;   /* «Передано» на екрані -- кілька секунд */
	}

	manual = (m->reqManual || m->reqPtt);
	periodic = ((manual == false) && (periodMs() != 0U) && (m->nextBeaconMs != 0U) && ((int32_t)(now - m->nextBeaconMs) >= 0));
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
	if (aprsMsgGapOk(bgBox(), now) == false)
	{
		return;   /* R11: від кінця попередньої передачі (повідомлення чи маяка) не минуло 2 с -- запит лишається */
	}
	m->reqManual = m->reqPtt = false;

	{
		aprsModeTxResult_t r;
		aprsModeBcnState_t st;
#if defined(APRS_R21_QSY)
		char qsy[APRSM_QSY_LEN];
#endif

		AM_TRACE(211);   /* частота вільна: перед aprsModeTxBeacon() (далі 220..) */
#if defined(APRS_R21_QSY)
		qsyForChannel(m, qsy, sizeof(qsy));   /* R21 З4 */
		r = aprsModeTxBeacon(&m->eff, qsy);
#else
		r = aprsModeTxBeacon(&m->eff, NULL);
#endif
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
		if (periodMs() != 0U)
		{
			m->nextBeaconMs = now + ((st == APRS_MODE_BCN_SENT) ? periodMs() : APRS_MODE_RETRY_MS);
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

#endif /* APRS_RX */
