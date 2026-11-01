/*
 * wake_hop.c -- R58: клей прототипу «перехід на інший канал під утримуваним PTT».
 * Див. wake_hop.h. Лише з -DENABLE_WAKE_HOP_TEST. Усі виклики -- із задачі UI (uiTxScreen.c):
 * кодплаг, дисплей і мелодії з ISR/задачі HRC6000 не чіпаємо (R57 §6).
 *
 * Принципи:
 *  - кодплаг НЕ змінюється, «останній канал зони» (LUCZ) НЕ змінюється -- тож повернення
 *    на вихідний канал це звичайний uiChannelModeLoadChannelData(false,false);
 *  - канал вантажиться в *currentChannelData (== channelScreenChannelData у режимі каналів), решта
 *    глобального стану (група прийому, поточний контакт) -- те, що робить uiChannelModeLoadChannelData,
 *    але БЕЗ settingsSet(...) і без озвучення/запису в кодплаг;
 *  - кандидат -- наступний за поточним цифровий канал зони по колу (до 2 стрибків, не повертаючись
 *    на вихідний).
 */
#include "functions/wake_hop.h"

#if defined(ENABLE_WAKE_HOP_TEST)

#include <string.h>
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "functions/codeplug.h"
#include "functions/settings.h"
#include "functions/trx.h"
#include "functions/sound.h"
#include "functions/wake_diag.h"
#include "functions/dmr_rctl_cfg.h"
#include "hardware/HR-C6000.h"
#include "hardware/radioHardwareInterface.h"
#include "functions/ticks.h"

static uint8_t  s_hops;      /* зроблено стрибків у цьому утриманні PTT */
static bool     s_away;      /* зараз на каналі, відмінному від вихідного */
static unsigned s_origPos;   /* позиція вихідного каналу в кільці */
static unsigned s_curPos;    /* позиція поточного каналу в кільці */

static bool ringIsAllChannels(void)
{
	return CODEPLUG_ZONE_IS_ALLCHANNELS(currentZone);
}

static unsigned ringCount(void)
{
	return (ringIsAllChannels() ? (unsigned)CODEPLUG_CHANNELS_MAX : (unsigned)currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone);
}

/* Номер каналу кодплагу на позиції кільця; 0 -- такої позиції немає. */
static int ringChannelNumber(unsigned pos)
{
	if (ringIsAllChannels())
	{
		return (int)pos + CODEPLUG_CHANNELS_MIN;
	}

	return ((pos < (unsigned)currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone) ? (int)currentZone.channels[pos] : 0);
}

static unsigned ringStartPos(void)
{
	int16_t last = codeplugGetLastUsedChannelInCurrentZone();

	return (ringIsAllChannels() ? (unsigned)((last > 0) ? (last - 1) : 0) : (unsigned)last);
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
	info->inhibited = (dmrRctlIsInhibited() != 0);
	info->rxFreq    = ch->rxFreq;
	info->txFreq    = ch->txFreq;
}

static bool posIsUsable(unsigned pos, void *ctx)
{
	CodeplugChannel_t cand;
	wakeHopChan_t info;
	int num;

	(void)ctx;

	if (pos == s_origPos)   /* на вихідний не повертаємось */
	{
		return false;
	}

	num = ringChannelNumber(pos);

	if ((num < CODEPLUG_CHANNELS_MIN) || (num > CODEPLUG_CHANNELS_MAX))
	{
		return false;
	}

	if (ringIsAllChannels() && (codeplugAllChannelsIndexIsInUse(num) == false))
	{
		return false;
	}

	codeplugChannelGetDataForIndex(num, &cand);
	fillChanInfo(&cand, &info);

	return wakeHopChannelUsable(&info);
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

void wakeHopBegin(void)
{
	s_hops = 0U;
	s_away = false;
	s_origPos = ringStartPos();
	s_curPos = s_origPos;
}

bool wakeHopTry(void)
{
	unsigned next;

	if ((wakeHopMayHop(s_hops) == false) ||
			(menuSystemGetRootMenuNumber() != UI_CHANNEL_MODE) ||
			(trxGetMode() != RADIO_MODE_DIGITAL) ||
			(settingsUsbMode == USB_MODE_HOTSPOT) ||
			uiDataGlobal.reverseRepeaterChannel || uiDataGlobal.talkaround ||
			(ringCount() < 2U))
	{
		return false;
	}

	if (wakeHopFindNext(s_curPos, ringCount(), posIsUsable, NULL, &next) == false)
	{
		return false;
	}

	/* Усе, що може відмовитись, перевірено; далі -- сам перехід. */
	wakeDiagHop(ticksGetMillis(), (int16_t)ringChannelNumber(next));
	roamLoadChannel(ringChannelNumber(next));
	s_curPos = next;
	s_away = true;
	s_hops++;
	HRC6000RestartWakeForRoam();

	return true;
}

void wakeHopRestore(void)
{
	if (s_away)
	{
		s_away = false;
		s_hops = WAKE_HOP_MAX_HOPS;   /* до наступного wakeHopBegin() більше не стрибаємо */
		uiChannelModeLoadChannelData(false, false);
	}
}

#endif /* ENABLE_WAKE_HOP_TEST */
