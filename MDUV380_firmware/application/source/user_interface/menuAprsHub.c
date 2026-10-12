/*
 * menuAprsHub.c -- меню «APRS» (R8-fix, п.5). Див. menuAprsHub.h.
 *
 * Це власний простий список (а не menuDisplayMenuList): «Режим APRS» (R10), «APRS станції» (R8) і «APRS проба» (R2) --
 * не окремі меню, а режими з власним екраном, які цей список приймає всередину (так само, як це робили
 * «Опції рації» в R8/R10: поки aprsModeIsActive() / aprsRxUi()->on / aprsRxProbeIsOn(), усі тіки й події належать їм).
 * R8-fix2: єдине меню «APRS» -- «Режим APRS» переїхав сюди з «Опцій рації» (R10 тримав його там, бо новий ID меню
 * коштує RAM; ID MENU_APRS_HUB уже оплачено, другого меню не плодимо).
 *
 * QuickKey: пункти цього меню швидкими клавішами НЕ прив'язуються (SK2+цифра ігнорується) -- це дії, а не
 * налаштування. Існуючі QuickKey на стокові пункти «Опцій рації» не зачеплено: пункти R8 прибрано з КІНЦЯ
 * списку «Опцій рації», індекси стокових пунктів не змінилися (докладно -- docs, розділ 12.2).
 */
#include "user_interface/menuAprsHub.h"

#if defined(APRS_RX)

#include "user_interface/uiGlobals.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/menuAprsStations.h"
#include "user_interface/menuAprsRxProbe.h"
#include "user_interface/menuAprsMode.h"
#include "functions/aprs_mode.h"
#include "user_interface/languages/aprsmode_ua.h"
#include "user_interface/languages/aprsrx_ua.h"
#include "user_interface/languages/aprsmsg_ua.h"

/* Порядок пунктів = порядок на екрані. Нові пункти додавати СЮДИ, у відповідному місці:
 *   APRS_HUB_MODE, APRS_HUB_STATIONS, APRS_HUB_MESSAGES (R11), APRS_HUB_SETTINGS, [APRS_HUB_PROBE] */
enum
{
	APRS_HUB_MODE = 0,
	APRS_HUB_STATIONS,
	APRS_HUB_MESSAGES,
	APRS_HUB_SETTINGS,
#if defined(APRS_RX_PROBE)
	APRS_HUB_PROBE,
#endif
	APRS_HUB_NUM
};

static menuStatus_t hubExitCode = MENU_STATUS_SUCCESS;

static const char *itemName(int n)
{
	switch (n)
	{
		case APRS_HUB_MODE:     return APRSM_MENU;
		case APRS_HUB_STATIONS: return APRSRX_TITLE;
		case APRS_HUB_MESSAGES: return APRSMSG_MENU;
		case APRS_HUB_SETTINGS: return APRSRX_HUB_SETTINGS;
#if defined(APRS_RX_PROBE)
		case APRS_HUB_PROBE:    return APRSRX_HUB_PROBE;
#endif
		default:                return "";
	}
}

static void updateScreen(bool isFirstRun)
{
	displayClearBuf();
	menuDisplayTitle(currentLanguage->APRS);

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

		menuDisplayEntry(i, mNum, itemName(mNum), 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_COLOUR_NONE, THEME_ITEM_BG);

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

static void openItem(int n)
{
	switch (n)
	{
		case APRS_HUB_MODE:
			AM_TRACE(50);   /* R10-fix: хаб, GREEN на «Режим APRS»: перед menuAprsModeEnter() (далі 51, 1..19, 30..37, 52, 84..86) */
			(void)menuAprsModeEnter();   /* R10: дія, а не налаштування. Не вдалося -- сповіщення, список лишається */
			break;
		case APRS_HUB_STATIONS:
			menuAprsStationsEnter();
			break;
		case APRS_HUB_MESSAGES:
			(void)menuAprsModeEnterMessages();   /* R11: режим відкривається одразу на сторінці «Повідомлення» (черга й ACK живуть у режимі) */
			break;
		case APRS_HUB_SETTINGS:
			menuSystemPushNewMenu(MENU_APRS);   /* стокове меню налаштувань APRS: посилання, QuickKey на нього не змінилися */
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
	aprsModeExit();            /* R10: вихід із меню будь-яким шляхом -- вийти з «Режиму APRS» (ідемпотентно) */
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
		aprsModeExit();            /* R10: повернення сюди з активним режимом -- несумісно, виходимо з режиму */
		menuAprsStationsClose();   /* повернення сюди -- екрани вже закриті (push нового меню); про всяк випадок */
#if defined(APRS_RX_PROBE)
		aprsRxProbeClose();
#endif

		updateScreen(true);
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	hubExitCode = MENU_STATUS_SUCCESS;

	/* Поки активний «Режим APRS» / відкрито «APRS станції» / «APRS проба», екран і всі події належать їм
	 * (режим -- раніше за станції: він має власні сторінки). */
	if (aprsModeIsActive())
	{
		if (menuAprsModeTick(ev) == false)
		{
			updateScreen(false);   /* RED на «Моніторі»: режим уже вимкнено -- перемалювати список */
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
