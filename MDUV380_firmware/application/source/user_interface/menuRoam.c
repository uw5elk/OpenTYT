/*
 * menuRoam.c -- R59: пункт головного меню «Роумінг» (ENABLE_ROAM_RETRY).
 *
 * Пункти: «Автоперехід» (Вимк/Увімк), «Макс. стрибків» (1..5), «Цей у списку» (Так/Ні: прапорець ROAMING поточного
 * каналу стандартним збереженням запису кодплагу), «Список» (лише перегляд: номер + назва, гортання), а з ENABLE_WAKE_DIAG
 * ще «Журнал пробудж.» (перенесено сюди з «Повідомлень»; логіка журналу й USB 0xB7 без змін).
 *
 * Налаштування (увімкнено/стрибки) пишуться в custom-data блок №15 лише при зміні користувачем (roam_cfg.c).
 * Рядки -- roam_ui.h (укр. з languages/roam_ua.h), не stringsTable_t. Сама логіка автопереходу -- wake_hop*.c.
 */
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"

#if defined(ENABLE_ROAM_RETRY)

#include <string.h>
#include "user_interface/roam_ui.h"
#include "functions/roam_cfg.h"
#include "functions/wake_hop.h"
#include "functions/codeplug.h"
#include "functions/ticks.h"
#include "io/keyboard.h"
#if defined(ENABLE_WAKE_DIAG)
#include "functions/wake_diag.h"
#endif

enum { ROAM_VIEW_MAIN = 0, ROAM_VIEW_LIST, ROAM_VIEW_WAKE };

enum { ROAM_ROW_AUTO = 0, ROAM_ROW_HOPS, ROAM_ROW_CUR, ROAM_ROW_LIST
#if defined(ENABLE_WAKE_DIAG)
	, ROAM_ROW_WAKE
#endif
	, ROAM_ROWS };

#define ROAM_LIST_ROWS     9      /* рядків списку на екрані (FONT_SIZE_1, крок 10 px) */
#define ROAM_REFRESH_MS    500    /* журнал оновлюється сам, поки оператор дивиться */

/* Стан екрана -- у CCM (на старті там сміття: обнуляється на isFirstRun до будь-якого читання). */
static struct
{
	uint8_t  view;
	uint16_t listTop;     /* номер каналу першого видимого рядка списку (0 -- списку нема) */
	uint16_t listPos;     /* порядковий номер цього рядка у списку (0..) */
	uint16_t listCount;   /* скільки каналів у списку */
#if defined(ENABLE_WAKE_DIAG)
	uint8_t  wakeAge;     /* який сеанс журналу показано (0 = найновіший) */
	ticksTimer_t wakeTimer;
#endif
} s_roam __attribute__((section(".ccmram")));   /* CCM-INIT(menuRoam) -- memset(&s_roam) на isFirstRun, до будь-якого читання */

static void mainUpdate(void);
static void mainEvent(uiEvent_t *ev, menuStatus_t *ec);
static void listUpdate(void);
static void listEvent(uiEvent_t *ev);
static void listOpen(void);
#if defined(ENABLE_WAKE_DIAG)
static void wakeUpdate(void);
static void wakeEvent(uiEvent_t *ev);
#endif

menuStatus_t menuRoam(uiEvent_t *ev, bool isFirstRun)
{
	menuStatus_t exitCode = MENU_STATUS_SUCCESS;

	if (isFirstRun)
	{
		memset(&s_roam, 0, sizeof(s_roam));
		s_roam.view = ROAM_VIEW_MAIN;
		s_roam.listCount = (uint16_t)roamListCount();   // скан кодплагу -- раз на вхід у меню, а не на кожне перемалювання
		menuDataGlobal.currentItemIndex = 0;
		menuDataGlobal.numItems = ROAM_ROWS;
		mainUpdate();
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	/* Синтетична FUNC_REDRAW (картку-сповіщення закрито, у буфері лишилась лише вона) -- перемалювати поточний екран. */
	if (ev->hasEvent && (ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		switch (s_roam.view)
		{
			case ROAM_VIEW_LIST: listUpdate(); break;
#if defined(ENABLE_WAKE_DIAG)
			case ROAM_VIEW_WAKE: wakeUpdate(); break;
#endif
			default:             mainUpdate(); break;
		}
		return exitCode;
	}

	switch (s_roam.view)
	{
		case ROAM_VIEW_LIST:
			if (ev->hasEvent) { listEvent(ev); }
			break;
#if defined(ENABLE_WAKE_DIAG)
		case ROAM_VIEW_WAKE:
			if (ev->hasEvent) { wakeEvent(ev); }
			if ((s_roam.view == ROAM_VIEW_WAKE) && ticksTimerHasExpired(&s_roam.wakeTimer))
			{
				wakeUpdate();
			}
			break;
#endif
		default:
			if (ev->hasEvent) { mainEvent(ev, &exitCode); }
			break;
	}

	return exitCode;
}

/* ============================ ГОЛОВНИЙ ЕКРАН ============================ */
static void mainUpdate(void)
{
	char buf[24];

	displayClearBuf();
	menuDisplayTitle(ROAM_MENU_NAME);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset(ROAM_ROWS, i);

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY) { continue; }
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)   { break; }

		switch (mNum)
		{
			case ROAM_ROW_AUTO: snprintf(buf, sizeof buf, ROAM_ROW_AUTO_FMT, (roamCfgIsEnabled() ? ROAM_ON_S : ROAM_OFF_S)); break;
			case ROAM_ROW_HOPS: snprintf(buf, sizeof buf, ROAM_ROW_HOPS_FMT, (unsigned)roamCfgMaxHops()); break;
			case ROAM_ROW_CUR:
				/* У режимі VFO поточного «каналу кодплагу» нема -- показуємо «Ні» (дія дасть пояснення). */
				snprintf(buf, sizeof buf, ROAM_ROW_CUR_FMT,
						((menuSystemGetRootMenuNumber() == UI_CHANNEL_MODE) && roamCurrentInList()) ? ROAM_YES_S : ROAM_NO_S);
				break;
			case ROAM_ROW_LIST: snprintf(buf, sizeof buf, ROAM_ROW_LIST_FMT, (unsigned)s_roam.listCount); break;
#if defined(ENABLE_WAKE_DIAG)
			case ROAM_ROW_WAKE: snprintf(buf, sizeof buf, WAKE_ITEM); break;
#endif
			default:            buf[0] = 0; break;
		}

		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}

	displayRender();
}

static void saveCfg(bool enabled, uint8_t hops)
{
	if (roamCfgSave(enabled, hops) == false)
	{
		uiNotificationShowShort(1500, ROAM_MSG_SAVE_ERR, true);
	}
}

static void toggleCurrent(void)
{
	const char *msg;

	if (menuSystemGetRootMenuNumber() != UI_CHANNEL_MODE)
	{
		msg = ROAM_MSG_NOT_CHANNEL;
	}
	else if (roamCurrentInList())
	{
		msg = (roamToggleCurrent() ? ROAM_MSG_REMOVED : ROAM_MSG_SAVE_ERR);
	}
	else if (roamCurrentSuitable() == false)
	{
		msg = ROAM_MSG_UNSUITABLE;
	}
	else
	{
		msg = (roamToggleCurrent() ? ROAM_MSG_ADDED : ROAM_MSG_SAVE_ERR);
	}

	s_roam.listCount = (uint16_t)roamListCount();   // прапорець міг змінитись
	mainUpdate();
	uiNotificationShowShort(1500, msg, true);
}

static void mainEvent(uiEvent_t *ev, menuStatus_t *ec)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, ROAM_ROWS);
		*ec |= MENU_STATUS_LIST_TYPE; mainUpdate(); return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, ROAM_ROWS);
		*ec |= MENU_STATUS_LIST_TYPE; mainUpdate(); return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		menuSystemPopPreviousMenu(); return;
	}

	bool right = KEYCHECK_PRESS(ev->keys, KEY_RIGHT);
	bool left  = KEYCHECK_PRESS(ev->keys, KEY_LEFT);
	bool green = KEYCHECK_SHORTUP(ev->keys, KEY_GREEN);

	if ((right || left || green) == false) { return; }

	switch (menuDataGlobal.currentItemIndex)
	{
		case ROAM_ROW_AUTO:
			saveCfg((roamCfgIsEnabled() == false), roamCfgMaxHops());
			mainUpdate();
			break;
		case ROAM_ROW_HOPS:
		{
			int hops = (int)roamCfgMaxHops();

			if (left)  { hops = (hops > (int)ROAM_HOPS_MIN) ? (hops - 1) : (int)ROAM_HOPS_MAX; }
			else       { hops = (hops < (int)ROAM_HOPS_MAX) ? (hops + 1) : (int)ROAM_HOPS_MIN; }

			saveCfg(roamCfgIsEnabled(), (uint8_t)hops);
			mainUpdate();
			break;
		}
		case ROAM_ROW_CUR:
			toggleCurrent();
			break;
		case ROAM_ROW_LIST:
			if (green) { listOpen(); }
			break;
#if defined(ENABLE_WAKE_DIAG)
		case ROAM_ROW_WAKE:
			if (green)
			{
				s_roam.view = ROAM_VIEW_WAKE;
				s_roam.wakeAge = 0;
				wakeUpdate();
			}
			break;
#endif
		default:
			break;
	}
}

/* ============================ СПИСОК (лише перегляд) ============================ */
static void listOpen(void)
{
	s_roam.listCount = (uint16_t)roamListCount();
	s_roam.listTop = (uint16_t)((s_roam.listCount > 0U) ? roamListStep(0, 1) : 0);
	s_roam.listPos = 0U;
	s_roam.view = ROAM_VIEW_LIST;
	listUpdate();
}

static void listUpdate(void)
{
	char buf[40];

	displayClearBuf();
	snprintf(buf, sizeof buf, ROAM_LIST_TITLE_FMT, (unsigned)((s_roam.listCount > 0U) ? (s_roam.listPos + 1U) : 0U), (unsigned)s_roam.listCount);
	menuDisplayTitle(buf);

	if (s_roam.listCount == 0U)
	{
		displayPrintCentered(50, ROAM_LIST_EMPTY, FONT_SIZE_1);
	}
	else
	{
		int num = (int)s_roam.listTop;

		for (unsigned row = 0U; (row < ROAM_LIST_ROWS) && ((s_roam.listPos + row) < s_roam.listCount) && (num != 0); row++)
		{
			CodeplugChannel_t ch;
			char name[17];

			codeplugChannelGetDataWithOffsetAndLengthForIndex(num, &ch, 0, (int)sizeof(ch.name));
			codeplugUtilConvertBufToDisplayString(ch.name, name, 16);
			snprintf(buf, sizeof buf, "%4d %s", num, name);
			displayPrintAt(2, (int16_t)(16 + (10 * (int)row)), buf, FONT_SIZE_1);

			num = roamListStep(num, 1);
		}
	}

	displayPrintCentered(112, ROAM_LIST_HINT, FONT_SIZE_1);
	displayRender();
}

static void listEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		if ((s_roam.listCount > 0U) && ((s_roam.listPos + 1U) < s_roam.listCount))
		{
			s_roam.listTop = (uint16_t)roamListStep((int)s_roam.listTop, 1);
			s_roam.listPos++;
		}
		listUpdate();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		if ((s_roam.listCount > 0U) && (s_roam.listPos > 0U))
		{
			s_roam.listTop = (uint16_t)roamListStep((int)s_roam.listTop, -1);
			s_roam.listPos--;
		}
		listUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		s_roam.view = ROAM_VIEW_MAIN;
		menuDataGlobal.currentItemIndex = ROAM_ROW_LIST;   // повернутись на рядок «Список»
		mainUpdate();
	}
}

#if defined(ENABLE_WAKE_DIAG)
/* ============================ ЖУРНАЛ ПРОБУДЖЕННЯ (R58, перенесено з «Повідомлень») ============================ */
/* Журнал сеансів пробудження ретранслятора (functions/wake_diag.c): по одному сеансу на екран, 9 рядків FONT_SIZE_1.
 * DOWN -- старіший сеанс, UP -- новіший, довге GREEN -- скинути журнал, RED -- назад. Розшифровка -- TESTING.md, блок DF/DG.
 * Журнал тепер показує й стрибки автопереходу (поле «hop» останнього рядка). */
static void wakeUpdate(void)
{
	char buf[40];
	wakeDiagSession_t ws;
	unsigned total = wakeDiagCount();

	displayClearBuf();
	if (total == 0U)
	{
		snprintf(buf, sizeof buf, WAKE_TITLE_FMT, 0U, 0U);
		menuDisplayTitle(buf);
		displayPrintCentered(50, WAKE_EMPTY, FONT_SIZE_1);
	}
	else
	{
		if (s_roam.wakeAge >= total) { s_roam.wakeAge = (uint8_t)(total - 1U); }
		(void)wakeDiagGet(s_roam.wakeAge, &ws);
		snprintf(buf, sizeof buf, WAKE_TITLE_FMT, (unsigned)s_roam.wakeAge + 1U, total);
		menuDisplayTitle(buf);
		for (unsigned line = 0U; line < WAKE_DIAG_LINES; line++)
		{
			if (wakeDiagLine(&ws, s_roam.wakeAge, total, wakeDiagDirectTx(), line, buf, (int)sizeof buf))
			{
				displayPrintAt(2, (int16_t)(16 + (10 * (int)line)), buf, FONT_SIZE_1);
			}
		}
	}
	displayPrintCentered(112, WAKE_HINT, FONT_SIZE_1);
	displayRender();

	ticksTimerStart(&s_roam.wakeTimer, ROAM_REFRESH_MS);
}

static void wakeEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0) { return; }
	if (KEYCHECK_LONGDOWN(ev->keys, KEY_GREEN))
	{
		wakeDiagReset();
		s_roam.wakeAge = 0;
		wakeUpdate();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		if (((unsigned)s_roam.wakeAge + 1U) < wakeDiagCount()) { s_roam.wakeAge++; }
		wakeUpdate();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		if (s_roam.wakeAge > 0U) { s_roam.wakeAge--; }
		wakeUpdate();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		s_roam.view = ROAM_VIEW_MAIN;
		menuDataGlobal.currentItemIndex = ROAM_ROW_WAKE;   // повернутись на рядок «Журнал пробудж.»
		mainUpdate();
	}
}
#endif /* ENABLE_WAKE_DIAG */

#endif /* ENABLE_ROAM_RETRY */
