/*
 * tone_reply.c -- R99-TONE: «Тон-відгук». Див. tone_reply.h. Лише FM.
 * Чиста частина (стан-машина, блок, межі) -- з TONE_REPLY_ENABLED або TONE_REPLY_HOST_TEST; обгортка з залізом -- лише TONE_REPLY_ENABLED.
 */
#include "functions/tone_reply.h"

#if defined(TONE_REPLY_ENABLED) || defined(TONE_REPLY_HOST_TEST)

#include <string.h>

void toneReplyCfgDefaults(toneReplyCfg_t *c)
{
	c->freqHz = TONE_REPLY_FREQ_DEF;
	c->durS = TONE_REPLY_DUR_DEF_S;
	c->delayS = TONE_REPLY_DELAY_DEF_S;
	c->threshS = TONE_REPLY_THRESH_DEF_S;
}

void toneReplyCfgClamp(toneReplyCfg_t *c)
{
	if (c->freqHz < TONE_REPLY_FREQ_MIN)
	{
		c->freqHz = TONE_REPLY_FREQ_MIN;
	}
	if (c->freqHz > TONE_REPLY_FREQ_MAX)
	{
		c->freqHz = TONE_REPLY_FREQ_MAX;
	}
	c->freqHz = (uint16_t)(((c->freqHz + (TONE_REPLY_FREQ_STEP / 2U)) / TONE_REPLY_FREQ_STEP) * TONE_REPLY_FREQ_STEP);
	if (c->freqHz > TONE_REPLY_FREQ_MAX)
	{
		c->freqHz = TONE_REPLY_FREQ_MAX;
	}
	if (c->durS < TONE_REPLY_DUR_MIN_S)
	{
		c->durS = TONE_REPLY_DUR_MIN_S;
	}
	if (c->durS > TONE_REPLY_DUR_MAX_S)
	{
		c->durS = TONE_REPLY_DUR_MAX_S;
	}
	if (c->delayS < TONE_REPLY_DELAY_MIN_S)
	{
		c->delayS = TONE_REPLY_DELAY_MIN_S;
	}
	if (c->delayS > TONE_REPLY_DELAY_MAX_S)
	{
		c->delayS = TONE_REPLY_DELAY_MAX_S;
	}
	if (c->threshS < TONE_REPLY_THRESH_MIN_S)
	{
		c->threshS = TONE_REPLY_THRESH_MIN_S;
	}
	if (c->threshS > TONE_REPLY_THRESH_MAX_S)
	{
		c->threshS = TONE_REPLY_THRESH_MAX_S;
	}
}

/* v1 (×100 мс) -> секунди: округлення ВГОРУ (0,5 с -> 1 с), далі межі нових констант. */
static uint8_t trDsToS(uint8_t ds)
{
	return (uint8_t)((ds + 9U) / 10U);
}

int toneReplyCfgParse(const toneReplyOnFlash_t *raw, toneReplyCfg_t *c, bool *enabled)
{
	toneReplyCfgDefaults(c);
	*enabled = false;
	if ((raw->version != TONE_REPLY_CFG_VERSION) && (raw->version != TONE_REPLY_CFG_V2) && (raw->version != TONE_REPLY_CFG_V1))
	{
		return 0;   /* блоку нема / невідома версія / сміття -- типові, вимкнено */
	}
	c->freqHz = (uint16_t)(raw->freqLo | ((uint16_t)raw->freqHi << 8));
	if (raw->version == TONE_REPLY_CFG_V1)
	{
		c->durS = trDsToS(raw->dur);      /* R99-TONE: «увімкнено» не зберігалось -- лишається 0 */
		c->delayS = trDsToS(raw->delay);
	}
	else
	{
		c->durS = raw->dur;
		c->delayS = raw->delay;
		*enabled = ((raw->flags & TONE_REPLY_FLAG_ENABLED) != 0U);
		if (raw->version == TONE_REPLY_CFG_VERSION)
		{
			c->threshS = raw->thresh;     /* v2: поріг був константою -- лишається типовий (TONE_REPLY_THRESH_DEF_S, з toneReplyCfgDefaults) */
		}
	}
	toneReplyCfgClamp(c);
	return (int)raw->version;
}

void toneReplyCfgBuild(toneReplyOnFlash_t *raw, const toneReplyCfg_t *c, bool enabled)
{
	memset(raw, 0, sizeof(*raw));
	raw->version = TONE_REPLY_CFG_VERSION;
	raw->dur = c->durS;
	raw->delay = c->delayS;
	raw->flags = (enabled ? TONE_REPLY_FLAG_ENABLED : 0U);
	raw->freqLo = (uint8_t)(c->freqHz & 0xFFU);
	raw->freqHi = (uint8_t)(c->freqHz >> 8);
	raw->thresh = c->threshS;
}

/*
 * Стан-машина (R102: без паузи-сторожа після відгуку):
 *   ЧЕКАЮ (IDLE) -- шумодав ВІДКРИВСЯ (спостережено закрито -> відкрито) і передача дозволена -> RX;
 *   RX -- сигнал закрився: тривав >= порогу (cfg->threshS, с) -> DELAY, інакше (короткий сплеск) -> ЧЕКАЮ без відгуку;
 *   DELAY -- минула затримка і передача дозволена -> TX (тон); новий сигнал під час затримки -> знову RX (відгук після нього);
 *   TX -- тривалість, але не більше TONE_REPLY_DUR_MAX_S (жорстка межа) -> WAITCLOSE (зупинка тону); скасування (PTT, клавіша, зміна частоти) або заборона TX -- так само.
 * WAITCLOSE -- НЕ пауза (часу не чекає), а умова коректності «свіже відкриття»: у ЧЕКАЮ машина переходить лише коли шумодав закритий і передача
 * дозволена. Без цього відгук запускався б від стану «шумодав уже відкритий» -- зразу після власної передачі (тон, PTT), на старті, при вмиканні функції,
 * при поверненні на екран каналу, після скасування -- без жодного нового сигналу. Сигнал під час власного тону не чутний (рація передає): після тону
 * потрібне свіже закриття, а потім -- свіже відкриття.
 * Скасування (PTT, клавіша, зміна каналу): у затримці й тоні -- WAITCLOSE. Заборона TX у ЧЕКАЮ/RX/ЗАТРИМЦІ -- WAITCLOSE (цикл відкинуто).
 * Вимкнення функції -- зупинка тону (якщо йшов) і WAITCLOSE: при повторному вмиканні відкритий шумодав не запускає відгук.
 * Захисту від зациклення двох рацій з увімкненою функцією НЕМАЄ (рішення власника).
 */
int toneReplyStep(toneReplySm_t *s, uint32_t now, bool enabled, bool rxOpen, bool txAllowed, bool cancel, const toneReplyCfg_t *cfg)
{
	uint32_t dur;

	if (enabled == false)
	{
		bool wasTx = (s->state == TR_ST_TX);

		s->state = TR_ST_WAITCLOSE;
		s->t = now;
		return (wasTx ? TR_ACT_STOP : TR_ACT_NONE);
	}

	switch (s->state)
	{
		case TR_ST_IDLE:
			if (txAllowed == false)
			{
				s->state = TR_ST_WAITCLOSE;   /* передача заборонена (інший екран, TX inhibit, власна передача...) -- потрібне свіже закриття */
				s->t = now;
			}
			else if (rxOpen && (cancel == false))
			{
				s->state = TR_ST_RX;
				s->t = now;
			}
			else if (cancel)
			{
				s->state = TR_ST_WAITCLOSE;   /* користувач щось натиснув: відкритий зараз шумодав не є «свіжим» сигналом */
				s->t = now;
			}
			break;

		case TR_ST_RX:
			if (txAllowed == false)
			{
				s->state = TR_ST_WAITCLOSE;   /* під час сигналу заборонено передачу -- цикл відкинуто */
				s->t = now;
			}
			else if (rxOpen == false)
			{
				if ((now - s->t) >= ((uint32_t)cfg->threshS * 1000U))
				{
					s->state = TR_ST_DELAY;
				}
				else
				{
					s->state = TR_ST_IDLE;
				}
				s->t = now;
			}
			break;

		case TR_ST_DELAY:
			if (cancel || (txAllowed == false))
			{
				s->state = TR_ST_WAITCLOSE;   /* скасовано, або передачу заборонено (інший екран, TX inhibit...) -- цикл відкинуто */
				s->t = now;
			}
			else if (rxOpen)
			{
				s->state = TR_ST_RX;   /* знову сигнал -- відгук після нього */
				s->t = now;
			}
			else if ((now - s->t) >= ((uint32_t)cfg->delayS * 1000U))
			{
				s->t = now;
				s->state = TR_ST_TX;   /* txAllowed перевірено вище */
				return TR_ACT_START;
			}
			break;

		case TR_ST_TX:
			dur = (uint32_t)((cfg->durS > TONE_REPLY_DUR_MAX_S) ? TONE_REPLY_DUR_MAX_S : cfg->durS) * 1000U;   /* жорстка межа навіть при пошкодженому значенні */
			if (cancel || (txAllowed == false) || ((now - s->t) >= dur))
			{
				s->state = TR_ST_WAITCLOSE;
				s->t = now;
				return TR_ACT_STOP;
			}
			break;

		case TR_ST_WAITCLOSE:
		default:
			if ((rxOpen == false) && txAllowed)
			{
				s->state = TR_ST_IDLE;   /* шумодав закрито спостережено -- наступне відкриття буде «свіжим» */
				s->t = now;
			}
			break;
	}
	return TR_ACT_NONE;
}

#endif

#if defined(TONE_REPLY_ENABLED)

#include "functions/codeplug.h"
#include "functions/settings.h"
#include "functions/sound.h"
#include "functions/ticks.h"
#include "functions/trx.h"
#include "functions/rxPowerSaving.h"
#include "functions/aprs.h"
#include "functions/dual_channel.h"
#include "hardware/HR-C6000.h"
#include "io/LEDs.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#if defined(HAS_GPS)
#include "interfaces/gps.h"
#endif
#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)
#include "functions/dmr_rctl_cfg.h"
#endif

/* Стан -- у RAM (звичайний .bss, не CCM), без масивів: ~22 Б. */
static toneReplySm_t  s_trSm;
static toneReplyCfg_t s_trCfg;     /* поточні (меню редагує їх) */
static toneReplyCfg_t s_trSaved;   /* те, що в блоці 19 (порівняння перед записом і «скасувати» в меню) */
static uint32_t       s_trTxFreq;  /* частота передачі на старті тону: інша -- канал змінено, тон зупиняється */
static uint8_t        s_trEnabled;        /* R100: зберігається в блоці 19 ([3] біт 0) */
static uint8_t        s_trEnabledSaved;   /* те, що в блоці 19: біт 0 -- «увімкнено»; TR_SAVED_OLD -- у флеші ще v1/v2 (GREEN у меню запише v3 навіть без змін) */
#define TR_SAVED_OLD          0x02U

void toneReplyLoad(void)
{
	toneReplyOnFlash_t raw;

	memset(&raw, 0, sizeof(raw));
	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG, (uint8_t *)&raw, (int)sizeof(raw)) == false)
	{
		memset(&raw, 0, sizeof(raw));   /* блоку нема -- типові значення */
	}
	{
		bool en = false;

		int ver = toneReplyCfgParse(&raw, &s_trCfg, &en);   /* v1 -- мігровані значення, у флеші лишається v1 до збереження користувачем */

		s_trEnabled = (en ? 1U : 0U);
		s_trSaved = s_trCfg;
		s_trEnabledSaved = (uint8_t)(s_trEnabled | (((ver == (int)TONE_REPLY_CFG_V1) || (ver == (int)TONE_REPLY_CFG_V2)) ? TR_SAVED_OLD : 0U));   /* v1/v2 -- у флеші лишається, доки користувач не збереже */
	}
	s_trSm.state = TR_ST_WAITCLOSE;   /* на старті нічого не передається; відгук -- лише від сигналу, що відкрив шумодав ПІСЛЯ старту (свіже відкриття) */
	s_trSm.t = 0U;
	s_trTxFreq = 0U;
}

bool toneReplyIsEnabled(void)
{
	return (s_trEnabled != 0U);
}

void toneReplySetEnabled(bool on)
{
	s_trEnabled = (on ? 1U : 0U);
}

bool toneReplyIsTransmitting(void)
{
	return (s_trSm.state == TR_ST_TX);
}

toneReplyCfg_t *toneReplyCfg(void)
{
	return &s_trCfg;
}

bool toneReplySave(void)
{
	toneReplyOnFlash_t raw;

	toneReplyCfgClamp(&s_trCfg);
	if ((s_trCfg.freqHz == s_trSaved.freqHz) && (s_trCfg.durS == s_trSaved.durS) && (s_trCfg.delayS == s_trSaved.delayS) && (s_trCfg.threshS == s_trSaved.threshS) &&
			(s_trEnabled == (s_trEnabledSaved & 1U)) && ((s_trEnabledSaved & TR_SAVED_OLD) == 0U))
	{
		return true;   /* нічого не змінилось і у флеші вже v3 -- флеш не чіпаємо (v1/v2 лишається, доки не збережено) */
	}
	toneReplyCfgBuild(&raw, &s_trCfg, (s_trEnabled != 0U));
	if (codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG, (uint8_t *)&raw, (int)sizeof(raw)))
	{
		s_trSaved = s_trCfg;
		s_trEnabledSaved = s_trEnabled;   /* біт TR_SAVED_OLD знято: у флеші v3 */
		return true;
	}
	return false;
}

void toneReplyMenuCancel(void)
{
	s_trCfg = s_trSaved;
	s_trEnabled = (uint8_t)(s_trEnabledSaved & 1U);   /* v1 -- вимкнено (v1 «увімкнено» не зберігав); v2/v3 -- збережене */
}

/* Чи можна передати тон зараз. Лише екран каналу/VFO, FM-канал з частотою TX, без «лише прийом», TX inhibit, межі діапазону, hotspot,
 * сканування, «Подвійний прийом» (не підтримується), RCTL-блокування, чужої передачі (APRS, SMS, користувач). */
static bool trTxAllowed(void)
{
	int m = menuSystemGetCurrentMenuNumber();

	if ((m != UI_CHANNEL_MODE) && (m != UI_VFO_MODE))
	{
		return false;
	}
	if ((trxGetMode() != RADIO_MODE_ANALOG) || (currentChannelData->chMode != RADIO_MODE_ANALOG) || (currentChannelData->txFreq == 0U))
	{
		return false;
	}
	if ((codeplugChannelGetFlag(currentChannelData, CHANNEL_FLAG_RX_ONLY) != 0) || settingsIsOptionBitSet(BIT_TX_INHIBIT))
	{
		return false;
	}
	if ((nonVolatileSettings.txFreqLimited != BAND_LIMITS_NONE) && (trxCheckFrequencyInAmateurBand(currentChannelData->txFreq) == false))
	{
		return false;
	}
	if ((settingsUsbMode == USB_MODE_HOTSPOT) || uiDataGlobal.Scan.active || uiDataGlobal.Scan.toneActive)
	{
		return false;
	}
#if defined(DUAL_CHANNEL_ENABLED)
	if (dcIsEnabled())
	{
		return false;
	}
#endif
#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)
	if (dmrRctlIsInhibited())
	{
		return false;
	}
#endif
	if ((s_trSm.state != TR_ST_TX) && (trxTransmissionEnabled || trxIsTransmitting || aprsBeaconingIsTransmitting()))
	{
		return false;
	}
	return true;
}

/* Передача тону -- як маяк APRS (aprs.c) і стокова передача FM (uiTxScreen.c): тон CTCSS/DCS каналу, передавач, генератор тону AT1846S. */
static void trTxStart(void)
{
	s_trTxFreq = currentChannelData->txFreq;
	rxPowerSavingSetState(ECOPHASE_POWERSAVE_INACTIVE);
#if defined(HAS_GPS)
	if (SETTINGS_GPS_MODE_GET(nonVolatileSettings) > GPS_MODE_OFF)
	{
		gpsDataInputStartStop(false);
	}
#endif
	LedWrite(LED_GREEN, 0);
	LedWrite(LED_RED, 1);
	HRC6000ClearIsWakingState();
	trxSetTxCSS(currentChannelData->txTone);
	trxSetTX();
	trxSetTone1((int)s_trCfg.freqHz);   /* мікрофон вимкнено на час тону (radioSetTone1) */
}

static void trTxStop(void)
{
	trxSetTone1(0);                     /* тон вимкнено, мікрофон повернуто */
	trxTransmissionEnabled = false;
	LedWrite(LED_RED, 0);
#if defined(HAS_GPS)
	if (SETTINGS_GPS_MODE_GET(nonVolatileSettings) > GPS_MODE_OFF)
	{
		gpsDataInputStartStop(true);
	}
#endif
	trxSetRxCSS(RADIO_DEVICE_PRIMARY, currentChannelData->rxTone);
	trxActivateRx(true);
	trxIsTransmitting = false;
	/* R103-TONE-UI: прапор передачі скинуто, але екран каналу/VFO міг бути намальований у час тону (відлік «0», режим передачі) --
	 * перемальовку ніхто не просив (маяк просить в aprs.c APRS_TX_FINAL_STAGE, PTT -- виходом з uiTxScreen). Просимо так само, як маяк:
	 * повна перемальовка в наступному циклі екрана. Лише на екрані каналу/VFO: на меню (клавіша скасувала тон) воно перемалюється саме. */
	{
		int m = menuSystemGetCurrentMenuNumber();

		if ((m == UI_CHANNEL_MODE) || (m == UI_VFO_MODE))
		{
			uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN;
		}
	}
}

void toneReplyAbort(void)
{
	if (s_trSm.state == TR_ST_TX)
	{
		trTxStop();
		s_trSm.state = TR_ST_WAITCLOSE;
		s_trSm.t = ticksGetMillis();
	}
	else if ((s_trSm.state == TR_ST_DELAY) || (s_trSm.state == TR_ST_RX) || (s_trSm.state == TR_ST_IDLE))
	{
		s_trSm.state = TR_ST_WAITCLOSE;   /* PTT: шумодав відкритий -- не «свіжий» сигнал після передачі */
		s_trSm.t = ticksGetMillis();
	}
}

void toneReplyTick(const void *evp)
{
	const uiEvent_t *ev = (const uiEvent_t *)evp;
	bool cancel;
	bool rxOpen;
	int act;

	if ((s_trEnabled == 0U) && (s_trSm.state == TR_ST_WAITCLOSE))
	{
		return;   /* вимкнено -- нічого не робимо (дешевий вихід); машина вже в WAITCLOSE */
	}

	cancel = (ev->hasEvent && ((ev->events & (KEY_EVENT | BUTTON_EVENT)) != 0));   /* будь-яка клавіша/кнопка (PTT, ручка, меню) */
	if ((s_trSm.state == TR_ST_TX) && (currentChannelData->txFreq != s_trTxFreq))
	{
		cancel = true;   /* канал змінено не клавішею (роумінг тощо) */
	}
	rxOpen = ((s_trSm.state != TR_ST_TX) && (trxGetMode() == RADIO_MODE_ANALOG) && ((audioAmpGetStatus() & AUDIO_AMP_CHANNEL_RF) != 0));

	act = toneReplyStep(&s_trSm, ticksGetMillis(), (s_trEnabled != 0U), rxOpen, trTxAllowed(), cancel, &s_trCfg);
	if (act == TR_ACT_START)
	{
		trTxStart();
	}
	else if (act == TR_ACT_STOP)
	{
		trTxStop();
	}
}

#endif
