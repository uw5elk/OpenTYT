/*
 * menuAprsHub.c -- меню «APRS» (R8-fix, п.5; R17 Г1: єдине меню). Див. menuAprsHub.h.
 *
 * Це власний простий список (а не menuDisplayMenuList): «APRS станції» (R8), «Повідом. APRS» (R11), «Налаштування» (R17) і «APRS проба» (R2) --
 * не окремі меню, а екрани, які цей список приймає всередину (поки aprsRxUi()->on / aprsModeMsgSessionActive() / aprsModeCfgSessionActive() /
 * aprsRxProbeIsOn(), усі тіки й події належать їм).
 *
 * R17 Г1: пункти (порядок = порядок на екрані):
 *   «Слухати:Вимк/Увімк» -- перемикач «Слухати APRS» (aprsModeEnter()/aprsModeExit(); частота -- у заголовку); «Передати маяк» -- разовий маяк, працює і з
 *   вимкненим «Слухати» (рація паркується, передає, повертається); «APRS станції»; «Повідом. APRS»; «Пакети»; «Налаштування»; [«APRS проба»].
 * Стокове меню «Налаштування APRS» («Опції рації» -> APRS) не чіпано.
 *
 * QuickKey: пункти цього меню швидкими клавішами НЕ прив'язуються (SK2+цифра ігнорується) -- це дії, а не налаштування. Існуючі QuickKey на
 * стокові пункти «Опцій рації» не зачеплено (докладно -- docs, розділ 12.2).
 */
#include "user_interface/menuAprsHub.h"

#if defined(APRS_RX)

#include "user_interface/uiGlobals.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/menuAprsStations.h"
#include "user_interface/menuAprsRxProbe.h"
#include "user_interface/menuAprsMode.h"
#include "user_interface/menuAprsSettings.h"
#include "functions/aprs_mode.h"
#include "functions/sound.h"
#include "user_interface/languages/aprsmode_ua.h"
#include "user_interface/languages/aprsrx_ua.h"
#include "user_interface/languages/aprsmsg_ua.h"

/* Порядок пунктів = порядок на екрані. Нові пункти додавати СЮДИ, у відповідному місці. */
enum
{
	APRS_HUB_LISTEN = 0,
	APRS_HUB_BEACON,      /* R17: «Передати маяк» */
	APRS_HUB_STATIONS,
	APRS_HUB_MESSAGES,
	APRS_HUB_PACKET,      /* R15/R16: «Пакети» -- журнал останніх прийнятих кадрів */
	APRS_HUB_SETTINGS,
#if defined(APRS_RX_PROBE)
	APRS_HUB_PROBE,
#endif
	APRS_HUB_NUM
};

static menuStatus_t hubExitCode = MENU_STATUS_SUCCESS;

static const char *itemName(int n, char *buf, size_t cap)
{
	switch (n)
	{
		case APRS_HUB_LISTEN:
			if (buf == NULL)
			{
				return APRSM_H_LISTEN;
			}
			snprintf(buf, cap, APRSM_H_LISTEN_FMT, aprsModeIsActive() ? APRSM_H_ON : APRSM_H_OFF);
			return buf;
		case APRS_HUB_BEACON:   return APRSM_H_BEACON;
		case APRS_HUB_STATIONS: return APRSRX_TITLE;
		case APRS_HUB_PACKET:   return APRSRX_HUB_PKT;
		case APRS_HUB_MESSAGES:
		{
			/* R11-fix2: непрочитані повідомлення APRS -- у назві пункту (вхідні більше не потрапляють у «Повідомлення» DMR).
			 * Буфер -- на стеку викликача (updateScreen()): статичний масив коштував би main RAM. */
			unsigned unread = aprsMsgUnreadCount(aprsModeMsgBox());

			if ((unread == 0U) || (buf == NULL))
			{
				return APRSMSG_MENU;
			}
			snprintf(buf, cap, APRSMSG_MENU_NEW, (unread > 99U) ? 99U : unread);
			return buf;
		}
		case APRS_HUB_SETTINGS: return APRSM_H_SETTINGS;
#if defined(APRS_RX_PROBE)
		case APRS_HUB_PROBE:    return APRSRX_HUB_PROBE;
#endif
		default:                return "";
	}
}

static void updateScreen(bool isFirstRun)
{
	char nameBuf[24];
	char title[24];

	displayClearBuf();
	if (aprsModeIsActive())
	{
		char f[16];

		aprsModeFormatFreq(f, sizeof(f), aprsModeEff()->freq);
		snprintf(title, sizeof(title), APRSM_H_TITLE_ON, f);   /* слухаємо: частота -- у заголовку */
		menuDisplayTitle(title);
	}
	else
	{
		menuDisplayTitle(currentLanguage->APRS);
	}

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset(APRS_HUB_NUM, i);

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY)
		{
			continue;
		}
		else if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)
		{
			break;
		}

		menuDisplayEntry(i, mNum, itemName(mNum, nameBuf, sizeof(nameBuf)), 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_COLOUR_NONE, THEME_ITEM_BG);

		if (i == 0)
		{
			/* Підписи пунктів -- рядки форка, не currentLanguage: голосової підказки для них нема (так само, як
			 * для форкових пунктів «Опцій рації»). На першому вході звучить лише назва меню з menuAprsHub(). */
			if (!isFirstRun)
			{
				voicePromptsInit();
			}
			promptsPlayNotAfterTx();
		}
	}

	displayRender();
}

static void notifyNotNow(void)
{
	uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, APRSM_NOT_NOW, true);
	soundSetMelody(MELODY_ERROR_BEEP);
}

static void openItem(int n)
{
	switch (n)
	{
		case APRS_HUB_LISTEN:
			if (aprsModeIsActive())
			{
				if (aprsModeIsTransmitting())
				{
					uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, APRSM_TX_BUSY, true);
					soundSetMelody(MELODY_ERROR_BEEP);
				}
				else
				{
					aprsModeExit();
				}
			}
			else if (aprsModeEnter() == false)
			{
				notifyNotNow();
			}
			updateScreen(false);   /* значення пункту й заголовок змінилися */
			break;
		case APRS_HUB_BEACON:
			if (aprsModeBeaconOnce() == false)
			{
				notifyNotNow();
			}
			updateScreen(false);
			break;
		case APRS_HUB_STATIONS:
			menuAprsStationsEnter();
			break;
		case APRS_HUB_PACKET:
			menuAprsPacketEnter();
			break;
		case APRS_HUB_MESSAGES:
			/* Читання, «Відповісти», «Нове» -- з увімкненим «Слухати APRS» і без нього (чергу й ACK веде aprsMsgBgTick() на будь-якому екрані). */
			(void)menuAprsMsgEnter();
			break;
		case APRS_HUB_SETTINGS:
			(void)menuAprsSettingsEnter();   /* вимикає «Слухати»; не вдалося (передача) -- сповіщення, список лишається */
			break;
#if defined(APRS_RX_PROBE)
		case APRS_HUB_PROBE:
			menuAprsRxProbeEnter();
			break;
#endif
		default:
			break;
	}
}

static void handleEvent(uiEvent_t *ev)
{
	if (ev->events & BUTTON_EVENT)
	{
		if (repeatVoicePromptOnSK1(ev))
		{
			return;
		}
	}

	if (ev->events & FUNCTION_EVENT)
	{
		if (ev->function == FUNC_REDRAW)
		{
			updateScreen(false);
		}
		return;
	}

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, APRS_HUB_NUM);
		updateScreen(false);
		hubExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, APRS_HUB_NUM);
		updateScreen(false);
		hubExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) || KEYCHECK_SHORTUP(ev->keys, KEY_RIGHT))
	{
		openItem(menuDataGlobal.currentItemIndex);
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		menuSystemPopPreviousMenu();
	}
}

static void exitCallback(void *data)
{
	(void)data;
	aprsModeExit();            /* вихід із меню будь-яким шляхом -- вийти з «Слухати APRS» (ідемпотентно) */
	aprsModeMsgSessionClose(); /* ... і закрити екрани «Повідом. APRS» / «Налаштування» (налаштування -- записати й застосувати) */
	resetOriginalSettingsData();   /* копія стокових налаштувань APRS (aprsSettingsCopy) більше не потрібна */
	menuAprsStationsClose();   /* вихід із меню будь-яким шляхом (PopAll, PTT...) -- закрити екрани, які воно приймало */
#if defined(APRS_RX_PROBE)
	aprsRxProbeClose();
#endif
}

menuStatus_t menuAprsHub(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
		menuDataGlobal.numItems = APRS_HUB_NUM;
		menuDataGlobal.menuOptionsSetQuickkey = 0;
		menuDataGlobal.menuOptionsTimeout = 0;

		voicePromptsInit();
		voicePromptsAppendPrompt(PROMPT_SILENCE);
		voicePromptsAppendLanguageString(currentLanguage->APRS);
		voicePromptsAppendLanguageString(currentLanguage->menu);
		voicePromptsAppendPrompt(PROMPT_SILENCE);

		menuSystemRegisterExitCallback(exitCallback, NULL);
		aprsModeExit();            /* повернення сюди з активним режимом -- несумісно, виходимо з режиму */
		aprsModeMsgSessionClose(); /* ... і з екранів повідомлень/налаштувань */
		menuAprsStationsClose();   /* повернення сюди -- екрани вже закриті (push нового меню); про всяк випадок */
#if defined(APRS_RX_PROBE)
		aprsRxProbeClose();
#endif

		updateScreen(true);
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	hubExitCode = MENU_STATUS_SUCCESS;

	/* «Передати маяк» без «Слухати»: результат і повернення каналу після передачі */
	if (aprsModeBeaconOnceBusy())
	{
		aprsModeBeaconOncePoll();
		if (aprsModeBeaconOnceBusy() == false)
		{
			updateScreen(false);   /* режим, увімкнений лише заради маяка, вимкнено -- перемалювати список */
		}
	}

	/* Поки відкрито «Налаштування» / «Повідом. APRS» / «APRS станції» / «APRS проба», екран і всі події належать їм. */
	if (aprsModeCfgSessionActive())
	{
		if (menuAprsSettingsTick(ev) == false)
		{
			updateScreen(false);   /* RED зі списку груп: сесію закрито -- перемалювати меню */
		}
		return hubExitCode;
	}
	if (aprsModeMsgSessionActive())
	{
		if (menuAprsModeTick(ev) == false)
		{
			updateScreen(false);   /* RED з першого екрана «Повідом. APRS»: уже закрито -- перемалювати список */
		}
		return hubExitCode;
	}
	if (aprsRxUi()->on)
	{
		if (menuAprsStationsTick(ev) == false)
		{
			updateScreen(false);
		}
		return hubExitCode;
	}
#if defined(APRS_RX_PROBE)
	if (aprsRxProbeIsOn())
	{
		if (menuAprsRxProbeTick(ev) == false)
		{
			updateScreen(false);
		}
		return hubExitCode;
	}
#endif

	if (ev->hasEvent)
	{
		handleEvent(ev);
	}
	return hubExitCode;
}

#endif /* APRS_RX */
