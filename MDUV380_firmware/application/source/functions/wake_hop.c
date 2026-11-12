/*
 * wake_hop.c -- R59: клей «Роумінгу» (автоперехід на наступний канал зі списку під утримуваним PTT).
 * Див. wake_hop.h. Лише з -DENABLE_ROAM_RETRY. Усі виклики -- із задачі UI (uiTxScreen.c, меню «Роумінг»):
 * кодплаг, дисплей і мелодії з ISR/задачі HRC6000 не чіпаємо (R57 §6).
 *
 * R60: списків 10; номер списку каналу -- байт 37 запису (з міткою, roam_cfg.h). Кандидат -- канал з ТИМ САМИМ номером списку,
 * що й у поточного (вихідного) каналу; решта правил R59 без змін.
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

/* R60: байт списку в записі каналу -- це саме поле _UNUSED_1 (зсув 37); змінилась розкладка структури -- збірка зупиниться тут, а не мовчки читатиме не той байт. */
_Static_assert(offsetof(CodeplugChannel_t, _UNUSED_1) == ROAM_LIST_BYTE_OFFSET, "ROAM_LIST_BYTE_OFFSET != offsetof(CodeplugChannel_t, _UNUSED_1)");

/* R60: номер списку каналу num кодплагу: зайнятий запис -> з байта 37 (читається лише він), інакше 0. */
uint8_t roamChannelList(int num)
{
	CodeplugChannel_t tmp;

	if (codeplugAllChannelsIndexIsInUse(num) == false)
	{
		return 0U;
	}

	tmp._UNUSED_1 = 0U;
	codeplugChannelGetDataWithOffsetAndLengthForIndex(num, &tmp, (uint8_t)ROAM_LIST_BYTE_OFFSET, 1);

	return roamListFromByte(tmp._UNUSED_1);
}

uint8_t roamRecList(const CodeplugChannel_t *rec)
{
	return roamListFromByte(rec->_UNUSED_1);
}

void roamRecSetList(CodeplugChannel_t *rec, uint8_t list)
{
	rec->_UNUSED_1 = roamListToByte(list);
	/* Старий прапорець R59 прошивка більше не читає; знімаємо його, щоб одноразове перетворення «старий прапорець -> список 1» у CPS
	 * не оживило канал, якому список уже явно задано (або скасовано). */
	codeplugChannelSetFlag(rec, CHANNEL_FLAG_ROAMING, 0U);
}

/* Крок списку запису на dir (+1/-1) без обертання: на межі 0 / ROAM_LISTS_COUNT нічого не міняє (true). false -- крок вгору відхилено,
 * бо канал не може бути в списку; крок вниз (зняти зі списку) дозволено завжди. */
bool roamRecStepList(CodeplugChannel_t *rec, int dir)
{
	int cur = (int)roamRecList(rec);
	int want = cur + dir;

	if ((want < 0) || (want > (int)ROAM_LISTS_COUNT))
	{
		return true;
	}

	if ((dir > 0) && (roamRecSuitable(rec) == false))
	{
		return false;
	}

	roamRecSetList(rec, (uint8_t)want);
	return true;
}

uint8_t roamCurrentList(void)
{
	return roamRecList(currentChannelData);
}

static bool candidateIsOk(unsigned num, void *ctx)
{
	CodeplugChannel_t cand;
	wakeHopChan_t info;

	(void)ctx;

	/* Той самий номер списку, що й у вихідного/поточного каналу (на знайденому каналі він такий самий). Дешевий відсів: один байт. */
	if (wakeHopListMatch(roamCurrentList(), roamChannelList((int)num)) == false)
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

bool roamRecSuitable(const CodeplugChannel_t *rec)
{
	wakeHopChan_t info;

	fillChanInfo(rec, &info);
	info.inhibited = false;   /* віддалене блокування -- тимчасовий стан, а не властивість запису: у список канал це не забороняє */

	return wakeHopChannelUsable(&info);
}

bool roamCurrentSuitable(void)
{
	return (roamRecSuitable(currentChannelData) && (uiDataGlobal.currentSelectedChannelNumber >= CODEPLUG_CHANNELS_MIN) &&
			(uiDataGlobal.currentSelectedChannelNumber <= CODEPLUG_CHANNELS_MAX));
}

roamAssign_t roamChannelAssign(int num, uint8_t list)
{
	CodeplugChannel_t rec;
	uint8_t oldByte;
	bool oldFlag;

	if ((num < CODEPLUG_CHANNELS_MIN) || (num > CODEPLUG_CHANNELS_MAX) || (list > ROAM_LISTS_COUNT) || (codeplugAllChannelsIndexIsInUse(num) == false))
	{
		return ROAM_ASSIGN_BAD;
	}

	if (settingsIsOptionBitSet(BIT_CHANNELS_ARE_READ_ONLY))
	{
		return ROAM_ASSIGN_READONLY;
	}

	/* Свіжий запис із кодплагу (а не екранна копія з тимчасовими правками в ОЗП); міняємо лише байт списку й старий прапорець. */
	codeplugChannelGetDataForIndex(num, &rec);

	if ((list != 0U) && (roamRecSuitable(&rec) == false))
	{
		return ROAM_ASSIGN_UNSUITABLE;
	}

	oldByte = rec._UNUSED_1;
	oldFlag = (codeplugChannelGetFlag(&rec, CHANNEL_FLAG_ROAMING) != 0U);
	roamRecSetList(&rec, list);

	if ((rec._UNUSED_1 != oldByte) || oldFlag)   /* вже саме це -- не пишемо (знос флеша/EEPROM) */
	{
		if (codeplugChannelSaveDataForIndex(num, &rec) == false)
		{
			return ROAM_ASSIGN_ERR;
		}
	}

	if ((menuSystemGetRootMenuNumber() == UI_CHANNEL_MODE) && (uiDataGlobal.currentSelectedChannelNumber == num))
	{
		roamRecSetList(currentChannelData, list);
	}

	return ROAM_ASSIGN_OK;
}

unsigned roamListCount(uint8_t list)
{
	unsigned n = 0U;

	if ((list < 1U) || (list > ROAM_LISTS_COUNT))
	{
		return 0U;
	}

	for (int num = CODEPLUG_CHANNELS_MIN; num <= CODEPLUG_CHANNELS_MAX; num++)
	{
		if (roamChannelList(num) == list)
		{
			n++;
		}
	}

	return n;
}

static int stepCircle(int fromNum, int dir, uint8_t list, bool anyInUse)
{
	int span = (CODEPLUG_CHANNELS_MAX - CODEPLUG_CHANNELS_MIN) + 1;
	int start = ((fromNum >= CODEPLUG_CHANNELS_MIN) && (fromNum <= CODEPLUG_CHANNELS_MAX)) ? fromNum : ((dir >= 0) ? (CODEPLUG_CHANNELS_MIN - 1) : (CODEPLUG_CHANNELS_MAX + 1));

	for (int k = 1; k <= span; k++)
	{
		int num = start + ((dir >= 0) ? k : -k);

		/* По колу в межах CODEPLUG_CHANNELS_MIN..MAX. */
		num = ((num - CODEPLUG_CHANNELS_MIN) % span + span) % span + CODEPLUG_CHANNELS_MIN;

		if (anyInUse ? codeplugAllChannelsIndexIsInUse(num) : (roamChannelList(num) == list))
		{
			return num;
		}
	}

	return 0;
}

int roamListStep(uint8_t list, int fromNum, int dir)
{
	if ((list < 1U) || (list > ROAM_LISTS_COUNT))
	{
		return 0;
	}

	return stepCircle(fromNum, dir, list, false);
}

int roamChannelStep(int fromNum, int dir)
{
	return stepCircle(fromNum, dir, 0U, true);
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
	if (wakeHopMayRoam(roamCfgIsEnabled(), roamCurrentList()) &&
#if defined(DUAL_CHANNEL_ENABLED)
			(dcIsEnabled() == false) &&   /* R97: «Подвійний прийом» -- автоперехід роумінгу призупинено (налаштування не змінюються) */
#endif
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
