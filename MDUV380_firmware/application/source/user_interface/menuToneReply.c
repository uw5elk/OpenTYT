/*
 * menuToneReply.c -- R100-TONE / R102-TONE: головне меню -> «Тон-відгук». П'ять рядків «підпис:значення» (як «Опції рації»):
 *   «Тон-відгук:Увімк/Вимк», «Частота:1000» (TONE_REPLY_FREQ_MIN..MAX, крок TONE_REPLY_FREQ_STEP), «Тривал:10с» (с), «Затрим:2с» (с),
 *   «Поріг:1с» (TONE_REPLY_THRESH_MIN_S..MAX_S, крок TONE_REPLY_STEP_S; 0 -- будь-яке відкриття шумодава).
 * ↑/↓ -- рядок, ←/→ -- значення; GREEN -- запис блоку 19 (v3; якщо змінилось або у флеші ще v1/v2) і вихід; RED -- повернення збереженого і вихід.
 * Будь-який інший вихід з екрана (без GREEN) -- теж повернення збереженого (exit-callback), як у «Опціях рації».
 * Лише під TONE_REPLY_ENABLED (ENABLE_TONE_REPLY + українська + UV380). Рядки -- languages/tonereply_ua.h (cp1251).
 */
#include "functions/tone_reply.h"   /* лише він -- до #if: без прапорця файл порожній (токени збірок без ENABLE_TONE_REPLY як у базі; test_r46/test_r97) */

#if defined(TONE_REPLY_ENABLED)

#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"
#include <stdio.h>
#include <string.h>
#include "user_interface/languages/tonereply_ua.h"

enum { TRM_ON = 0, TRM_FREQ, TRM_DUR, TRM_DELAY, TRM_THRESH, TRM_ROWS };

static void trmUpdate(void);
static void trmExit(void *data);

/* Текст рядка «підпис:значення»; *opt -- з якого символу значення (колір значення). */
static void trmRowText(int row, char *buf, size_t cap, int *opt)
{
	const toneReplyCfg_t *c = toneReplyCfg();
	const char *l;

	switch (row)
	{
		case TRM_ON:
			l = TONEREPLY_MENU_ON;
			snprintf(buf, cap, "%s:%s", l, (toneReplyIsEnabled() ? TONEREPLY_ON : TONEREPLY_OFF));
			break;
		case TRM_FREQ:
			l = TONEREPLY_MENU_FREQ;
			snprintf(buf, cap, "%s:%u", l, (unsigned)c->freqHz);
			break;
		case TRM_DUR:
			l = TONEREPLY_MENU_DUR;
			snprintf(buf, cap, "%s:%u%s", l, (unsigned)c->durS, TONEREPLY_SEC);
			break;
		case TRM_DELAY:
			l = TONEREPLY_MENU_DELAY;
			snprintf(buf, cap, "%s:%u%s", l, (unsigned)c->delayS, TONEREPLY_SEC);
			break;
		default:
			l = TONEREPLY_MENU_THRESH;
			snprintf(buf, cap, "%s:%u%s", l, (unsigned)c->threshS, TONEREPLY_SEC);
			break;
	}
	*opt = (int)strlen(l) + 1;
}

static void trmUpdate(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE];

	displayClearBuf();
	menuDisplayTitle(TONEREPLY_MAIN);
	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int opt = 0;
		int mNum = menuGetMenuOffset(TRM_ROWS, i);

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY)
		{
			continue;
		}
		if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)
		{
			break;
		}
		trmRowText(mNum, buf, sizeof(buf), &opt);
		menuDisplayEntry(i, mNum, buf, opt, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	}
	displayRender();
}

/* ←/→: увімкнути/вимкнути; частота -- крок TONE_REPLY_FREQ_STEP; тривалість, затримка і поріг -- крок TONE_REPLY_STEP_S (межі -- toneReplyCfgClamp). */
static void trmChange(int row, int dir)
{
	toneReplyCfg_t *c = toneReplyCfg();

	switch (row)
	{
		case TRM_ON:
			toneReplySetEnabled(dir > 0);
			break;
		case TRM_FREQ:
			c->freqHz = (uint16_t)((dir > 0) ? (c->freqHz + TONE_REPLY_FREQ_STEP) :
					((c->freqHz > (TONE_REPLY_FREQ_MIN + TONE_REPLY_FREQ_STEP)) ? (c->freqHz - TONE_REPLY_FREQ_STEP) : TONE_REPLY_FREQ_MIN));
			break;
		case TRM_DUR:
			c->durS = (uint8_t)((dir > 0) ? (c->durS + TONE_REPLY_STEP_S) :
					((c->durS > (TONE_REPLY_DUR_MIN_S + TONE_REPLY_STEP_S)) ? (c->durS - TONE_REPLY_STEP_S) : TONE_REPLY_DUR_MIN_S));
			break;
		case TRM_DELAY:
			c->delayS = (uint8_t)((dir > 0) ? (c->delayS + TONE_REPLY_STEP_S) :
					((c->delayS > (TONE_REPLY_DELAY_MIN_S + TONE_REPLY_STEP_S)) ? (c->delayS - TONE_REPLY_STEP_S) : TONE_REPLY_DELAY_MIN_S));
			break;
		default:
			c->threshS = (uint8_t)((dir > 0) ? (c->threshS + TONE_REPLY_STEP_S) :
					((c->threshS > (TONE_REPLY_THRESH_MIN_S + TONE_REPLY_STEP_S)) ? (c->threshS - TONE_REPLY_STEP_S) : TONE_REPLY_THRESH_MIN_S));
			break;
	}
	toneReplyCfgClamp(c);
}

static void trmExit(void *data)
{
	(void)data;
	toneReplyMenuCancel();   /* без GREEN -- як було (після GREEN збережене = поточне, тож це нічого не змінює) */
}

menuStatus_t menuToneReply(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
		menuDataGlobal.currentItemIndex = 0;
		menuDataGlobal.numItems = TRM_ROWS;
		menuSystemRegisterExitCallback(trmExit, NULL);
		trmUpdate();
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	if (ev->hasEvent == false)
	{
		return MENU_STATUS_SUCCESS;
	}
	if ((ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		trmUpdate();
		return MENU_STATUS_SUCCESS;
	}
	if ((ev->events & KEY_EVENT) == 0)
	{
		return MENU_STATUS_SUCCESS;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, TRM_ROWS);
		trmUpdate();
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, TRM_ROWS);
		trmUpdate();
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_LEFT))
	{
		trmChange(menuDataGlobal.currentItemIndex, (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) ? 1 : -1));
		trmUpdate();
		return MENU_STATUS_SUCCESS;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		(void)toneReplySave();   /* блок 19 (v3) -- якщо змінилось або у флеші ще v1/v2; «увімкнено» теж зберігається */
		menuSystemPopPreviousMenu();
		return MENU_STATUS_SUCCESS;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		toneReplyMenuCancel();
		menuSystemPopPreviousMenu();
		return MENU_STATUS_SUCCESS;
	}
	return MENU_STATUS_SUCCESS;
}

#endif
