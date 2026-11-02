/*
 * wake_hop.c -- R59: клей «Роумінгу» (автоперехід на наступний канал зі списку під утримуваним PTT).
 * Див. wake_hop.h. Лише з -DENABLE_ROAM_RETRY. Усі виклики -- із задачі UI (uiTxScreen.c, меню «Роумінг»):
 * кодплаг, дисплей і мелодії з ISR/задачі HRC6000 не чіпаємо (R57 §6).
 *
 * Принципи:
 *  - кодплаг при ПЕРЕХОДІ не змінюється, «останній канал зони» (LUCZ) і nonVolatileSettings не змінюються --
 *    після перезапуску рація стартує з каналу, збереженого в зоні;
 *  - канал вантажиться в *currentChannelData (== channelScreenChannelData у режимі каналів) через roamLoadChannel();
 *  - стан «знайдений канал» (s_active/s_num) каже uiChannelModeLoadChannelData() НЕ перезаписувати
 *    uiDataGlobal.currentSelectedChannelNumber номером «останнього каналу зони» при поверненні з екрана передачі
 *    (інакше збереження каналу пішло б у чужий запис). Будь-яка явна зміна каналу користувачем (LoadChannelData(false,..))
 *    стан скидає.
 */
#include "functions/wake_hop.h"

#if defined(ENABLE_ROAM_RETRY)

#include <stddef.h>
#include <string.h>
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "functions/codeplug.h"
#include "functions/settings.h"
#include "functions/trx.h"
#include "functions/sound.h"
#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)
#include "functions/dmr_rctl_cfg.h"   // dmrRctlIsInhibited
#endif
#include "hardware/HR-C6000.h"
#include "hardware/radioHardwareInterface.h"
#include "functions/ticks.h"
#if defined(ENABLE_WAKE_DIAG)
#include "functions/wake_diag.h"
#endif

/* Скалярний стан -- звичайна статична пам'ять (нулі на старті = «нічого не знайдено»). */
static bool     s_active;      /* рація на каналі, знайденому автопереходом (поза «останнім каналом зони») */
static uint16_t s_num;         /* номер цього каналу в кодплазі, коли s_active */
static bool     s_listMode;    /* у цьому PTT роумінг дозволений (увімкнено і вихідний канал у списку) */
static uint8_t  s_hops;        /* зроблено стрибків у цьому утриманні PTT */
static bool     s_away;        /* зараз на каналі, відмінному від вихідного */
static bool     s_success;     /* на новому каналі пробудження дійшло до AWAKEN */
static bool     s_origRoamed;  /* вихідний канал цього PTT уже був «знайденим» */
static uint16_t s_origNum;     /* номер вихідного каналу */
static uint16_t s_curNum;      /* номер поточного (останнього випробуваного) каналу */

/* Випробувані «ключі» -- у CCM (на старті там сміття: скидається в wakeHopBegin() перед будь-яким читанням). */
static wakeHopTried_t s_tried __attribute__((section(".ccmram")));   /* CCM-INIT(wakeHopBegin) */

bool roamIsActive(void)
{
	return s_active;
}

uint16_t roamActiveChannel(void)
{
	return s_num;
}

void roamClear(void)
{
	s_active = false;
}

static void fillChanInfo(const CodeplugChannel_t *ch, wakeHopChan_t *info)
{
	CodeplugChannel_t *w = (CodeplugChannel_t *)ch;   /* codeplugChannelGetFlag не const-коректна; лише читає */

	info->digital   = (ch->chMode == RADIO_MODE_DIGITAL);
	info->forceDmo  = (codeplugChannelGetFlag(w, CHANNEL_FLAG_FORCE_DMO) != 0);
	info->rxOnly    = (codeplugChannelGetFlag(w, CHANNEL_FLAG_RX_ONLY) != 0);
	/* Ті самі умови, що на початку екрана передачі (uiTxScreen.c). */
	info->txAllowed = ((nonVolatileSettings.txFreqLimited == BAND_LIMITS_NONE) || trxCheckFrequencyInAmateurBand(ch->txFreq));
	info->inBand    = ((trxGetBandFromFrequency(ch->rxFreq) != FREQUENCY_OUT_OF_BAND) && (trxGetBandFromFrequency(ch->txFreq) != FREQUENCY_OUT_OF_BAND));
#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)
	info->inhibited = (dmrRctlIsInhibited() != 0);
#else
	info->inhibited = false;
#endif
	info->rxFreq    = ch->rxFreq;
	info->txFreq    = ch->txFreq;
	info->colourCode = ch->txColor;
}

/* Чи канал num у списку роумінгу: зайнятий запис кодплагу з прапорцем ROAMING (читається лише один байт). */
static bool chanInList(int num)
{
	CodeplugChannel_t tmp;

	if (codeplugAllChannelsIndexIsInUse(num) == false)
	{
		return false;
	}

	tmp.LibreDMR_flag1 = 0U;
	codeplugChannelGetDataWithOffsetAndLengthForIndex(num, &tmp, (uint8_t)offsetof(CodeplugChannel_t, LibreDMR_flag1), 1);

	return ((tmp.LibreDMR_flag1 & CODEPLUG_CHANNEL_LIBREDMR_FLAG1_ROAMING) != 0U);
}

static bool candidateIsOk(unsigned num, void *ctx)
{
	CodeplugChannel_t cand;
	wakeHopChan_t info;

	(void)ctx;

	if (chanInList((int)num) == false)
	{
		return false;
	}

	codeplugChannelGetDataForIndex((int)num, &cand);
	fillChanInfo(&cand, &info);

	return wakeHopCandidateOk(&info, &s_tried);
}

/*
 * Завантажити канал num як поточний БЕЗ запису в кодплаг/налаштування. Повторює те, що робить
 * uiChannelModeLoadChannelData() для цифрового каналу, але рахує групу прийому локально (кеш
 * currentRxGroupData / lastLoadedRxGroup та nonVolatileSettings не чіпаємо).
 */
static void roamLoadChannel(int num)
{
	CodeplugRxGroup_t rg;
	int tgIdx = nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE];
	bool rgValid;
	uint32_t channelDMRId;

	codeplugChannelGetDataForIndex(num, currentChannelData);
	uiDataGlobal.currentSelectedChannelNumber = num;

	HRC6000ClearActiveDMRID();

	trxSetFrequency(currentChannelData->rxFreq, currentChannelData->txFreq, DMR_MODE_AUTO);
	trxSetModeAndBandwidth(RADIO_MODE_DIGITAL, (codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_BW_25K) != 0));

	channelDMRId = codeplugChannelGetOptionalDMRID(currentChannelData);

	if (uiDataGlobal.manualOverrideDMRId != 0)
	{
		trxDMRID = uiDataGlobal.manualOverrideDMRId;
	}
	else
	{
		trxDMRID = ((channelDMRId == 0) ? uiDataGlobal.userDMRId : channelDMRId);
	}

	trxSetDMRColourCode(currentChannelData->txColor);
	HRC6000ClearColorCodeSynchronisation();

	rgValid = codeplugRxGroupGetDataForIndex(currentChannelData->rxGroupList, &rg);

	if (rgValid && (tgIdx > (rg.NOT_IN_CODEPLUG_numTGsInGroup - 1)))
	{
		tgIdx = 0;
	}

	if (rgValid && (tgIdx < rg.NOT_IN_CODEPLUG_numTGsInGroup))
	{
		codeplugContactGetDataForIndex(rg.contacts[tgIdx], &currentContactData);
	}
	else
	{
		codeplugContactGetDataForIndex(currentChannelData->contact, &currentContactData);
	}

	trxUpdateTsForCurrentChannelWithSpecifiedContact(&currentContactData);

	trxTalkGroupOrPcId = ((nonVolatileSettings.overrideTG == 0) ? codeplugContactGetPackedId(&currentContactData) : nonVolatileSettings.overrideTG);

	trxConfigurePA_DAC_ForFrequencyBand();
}

bool roamCurrentInList(void)
{
	return (codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_ROAMING) != 0);
}

bool roamCurrentSuitable(void)
{
	wakeHopChan_t info;

	fillChanInfo(currentChannelData, &info);

	return (wakeHopChannelUsable(&info) && (uiDataGlobal.currentSelectedChannelNumber >= CODEPLUG_CHANNELS_MIN) &&
			(uiDataGlobal.currentSelectedChannelNumber <= CODEPLUG_CHANNELS_MAX));
}

bool roamToggleCurrent(void)
{
	CodeplugChannel_t rec;
	int num = uiDataGlobal.currentSelectedChannelNumber;
	bool want = (roamCurrentInList() == false);

	if ((menuSystemGetRootMenuNumber() != UI_CHANNEL_MODE) || (num < CODEPLUG_CHANNELS_MIN) || (num > CODEPLUG_CHANNELS_MAX))
	{
		return false;
	}

	/* Свіжий запис із кодплагу (а не екранна копія з тимчасовими правками в ОЗП), міняємо лише прапорець. */
	codeplugChannelGetDataForIndex(num, &rec);
	codeplugChannelSetFlag(&rec, CHANNEL_FLAG_ROAMING, (want ? 1U : 0U));

	if (codeplugChannelSaveDataForIndex(num, &rec) == false)
	{
		return false;
	}

	codeplugChannelSetFlag(currentChannelData, CHANNEL_FLAG_ROAMING, (want ? 1U : 0U));

	return true;
}

unsigned roamListCount(void)
{
	unsigned n = 0U;

	for (int num = CODEPLUG_CHANNELS_MIN; num <= CODEPLUG_CHANNELS_MAX; num++)
	{
		if (chanInList(num))
		{
			n++;
		}
	}

	return n;
}

int roamListStep(int fromNum, int dir)
{
	int span = (CODEPLUG_CHANNELS_MAX - CODEPLUG_CHANNELS_MIN) + 1;
	int start = ((fromNum >= CODEPLUG_CHANNELS_MIN) && (fromNum <= CODEPLUG_CHANNELS_MAX)) ? fromNum : ((dir >= 0) ? (CODEPLUG_CHANNELS_MIN - 1) : (CODEPLUG_CHANNELS_MAX + 1));

	for (int k = 1; k <= span; k++)
	{
		int num = start + ((dir >= 0) ? k : -k);

		/* По колу в межах CODEPLUG_CHANNELS_MIN..MAX. */
		num = ((num - CODEPLUG_CHANNELS_MIN) % span + span) % span + CODEPLUG_CHANNELS_MIN;

		if (chanInList(num))
		{
			return num;
		}
	}

	return 0;
}

void wakeHopBegin(void)
{
	wakeHopTriedReset(&s_tried);

	s_hops = 0U;
	s_away = false;
	s_success = false;
	s_listMode = false;
	s_origRoamed = s_active;
	s_origNum = (uint16_t)uiDataGlobal.currentSelectedChannelNumber;
	s_curNum = s_origNum;

	/* Роумінг -- лише в режимі каналів, цифровий канал, не хотспот/реверс/talkaround, функція увімкнена,
	 * поточний канал у списку. Одне рішення на PTT. */
	if (wakeHopMayRoam(roamCfgIsEnabled(), roamCurrentInList()) &&
			(menuSystemGetRootMenuNumber() == UI_CHANNEL_MODE) &&
			(trxGetMode() == RADIO_MODE_DIGITAL) &&
			(settingsUsbMode != USB_MODE_HOTSPOT) &&
			(uiDataGlobal.reverseRepeaterChannel == false) && (uiDataGlobal.talkaround == false) &&
			(s_origNum >= CODEPLUG_CHANNELS_MIN) && (s_origNum <= CODEPLUG_CHANNELS_MAX))
	{
		s_listMode = true;
		(void)wakeHopTriedAdd(&s_tried, currentChannelData->rxFreq, currentChannelData->txFreq, currentChannelData->txColor);
	}
}

bool wakeHopTry(void)
{
	unsigned next = 0U;

	if ((s_listMode == false) || (wakeHopMayHop(s_hops, roamCfgMaxHops()) == false) ||
			(menuSystemGetRootMenuNumber() != UI_CHANNEL_MODE) ||
			(trxGetMode() != RADIO_MODE_DIGITAL))
	{
		return false;
	}

	if (wakeHopFindNext(s_curNum, CODEPLUG_CHANNELS_MIN, CODEPLUG_CHANNELS_MAX, candidateIsOk, NULL, &next) == false)
	{
		return false;
	}

	/* Усе, що може відмовитись, перевірено; далі -- сам перехід. */
#if defined(ENABLE_WAKE_DIAG)
	wakeDiagHop(ticksGetMillis(), (int16_t)next);
#endif
	roamLoadChannel((int)next);
	(void)wakeHopTriedAdd(&s_tried, currentChannelData->rxFreq, currentChannelData->txFreq, currentChannelData->txColor);
	s_curNum = (uint16_t)next;
	s_num = (uint16_t)next;
	s_active = true;
	s_away = true;
	s_hops++;
	HRC6000RestartWakeForRoam();

	return true;
}

void wakeHopPoll(void)
{
	if (s_away && (s_success == false) && (HRC6000GetIsWakingState() == WAKING_MODE_AWAKEN))
	{
		s_success = true;
	}
}

void wakeHopRestore(void)
{
	wakeHopPoll();

	if (wakeHopShouldRestore(s_away, s_success))
	{
		if (s_origRoamed)
		{
			roamLoadChannel((int)s_origNum);
			s_num = s_origNum;
			s_active = true;
		}
		else
		{
			roamClear();
			uiChannelModeLoadChannelData(false, false);
		}
	}

	/* успіх: s_active/s_num уже вказують на знайдений канал -- рація лишається на ньому */
	s_away = false;
	s_listMode = false;   /* до наступного wakeHopBegin() більше не стрибаємо */
}

#endif /* ENABLE_ROAM_RETRY */
