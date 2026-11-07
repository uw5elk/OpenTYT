/*
 * uiNameEditor.c -- R64: спільний редактор короткої назви (див. uiNameEditor.h). Код перенесено з menuZoneList.c (R42) без зміни поведінки.
 */
#include "user_interface/uiNameEditor.h"

#if defined(UI_NAME_EDITOR)

#include <string.h>
#include <stdio.h>
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/uiLocalisation.h"
#include "functions/sms_multitap.h"
#include "functions/ticks.h"
#include "io/keyboard.h"
#include "user_interface/languages/aprsmode_ua.h"   /* APRSM_L_MTHINT -- підказка "#:режим", та сама, що в редакторі контакту */

#define NE_KEY(b)   ((b)[17])
#define NE_IDX(b)   ((b)[18])
#define NE_MODE(b)  ((b)[19])

static uint32_t neGetMs(const char *buf)
{
	uint32_t v;

	memcpy(&v, &buf[24], sizeof(v));
	return v;
}

static void neSetMs(char *buf, uint32_t v)
{
	memcpy(&buf[24], &v, sizeof(v));
}

static uint8_t neMode(const char *buf)
{
	return (((uint8_t)NE_MODE(buf)) < SMS_MT_MODES) ? (uint8_t)NE_MODE(buf) : (uint8_t)SMS_MT_DEFAULT;
}

void nameEdInit(char *buf, const char *name)
{
	memset(buf, 0, NAME_ED_STATE_LEN);
	if (name != NULL)
	{
		strncpy(buf, name, NAME_ED_CAP);   /* [16] лишається 0 */
	}
	NE_KEY(buf) = 0;
	NE_IDX(buf) = 0;
	NE_MODE(buf) = (char)((buf[0] == 0) ? SMS_MT_UA_UP : SMS_MT_UA_LO);   // порожня назва починається з великої
	neSetMs(buf, 0);
	NAME_ED_ACTIVE(buf) = 1;
}

void nameEdClose(char *buf)
{
	NAME_ED_ACTIVE(buf) = 0;
}

void nameEdCommit(char *buf)
{
	if (NE_KEY(buf) != 0)
	{
		smsMt_t mt = { NE_KEY(buf), (uint8_t)NE_IDX(buf) };
		int16_t p = (int16_t)(strlen(buf) - 1U);   // символ перегляду -- в останній позиції рядка

		smsMtCommit(&mt, &p);
		NE_KEY(buf) = 0;
		NE_IDX(buf) = 0;
	}
}

void nameEdDraw(const char *buf, const char *title)
{
	char line[NAME_ED_CAP + 2];
	char cnt[12];
	int n = (int)strlen(buf);
	const char *lbl = smsMtModeLabel(neMode(buf));
	int16_t chipW = (int16_t)((strlen(lbl) * 6U) + 4U);

	if (n > NAME_ED_CAP)
	{
		n = NAME_ED_CAP;
	}
	memcpy(line, buf, (size_t)n);
	if (n < NAME_ED_CAP)
	{
		line[n++] = '_';   // курсор: наступний символ піде сюди
	}
	line[n] = 0;

	displayClearBuf();
	menuDisplayTitle(title);
	displayThemeApply(THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	displayPrintCore(0, 48, line, FONT_SIZE_3, TEXT_ALIGN_CENTER, false);
	displayThemeApply(THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_BG);

	// Індикатор режиму набору, підказка "#:режим" і лічильник -- внизу, як в редакторі назви контакту
	displayFillRect(0, 108, chipW, 10, false);
	displayPrintCore(2, 109, lbl, FONT_SIZE_1, TEXT_ALIGN_LEFT, true);
	displayPrintAt((uint16_t)(chipW + 4), 109, APRSM_L_MTHINT, FONT_SIZE_1);
	snprintf(cnt, sizeof(cnt), "%d/%d", (int)strlen(buf), NAME_ED_CAP);
	displayPrintCore(0, 109, cnt, FONT_SIZE_1, TEXT_ALIGN_RIGHT, false);
	displayRender();
}

// Текстова клавіша (цифри/"*" -- на натисканні, "#" -- на відпусканні: режим набору). true -- стан змінено (перемалювати).
static bool neKey(char *buf, uiEvent_t *ev)
{
	char k = (char)ev->keys.key;
	uint8_t mode = neMode(buf);
	smsMt_t mt = { NE_KEY(buf), (uint8_t)NE_IDX(buf) };
	int16_t p = (int16_t)strlen(buf);

	if (mt.key != 0)
	{
		p--;   // підтверджений текст закінчується перед символом, що гортається
	}

	if (k == KEY_HASH)
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH) == false)
		{
			return false;   // без перемальовування, як було в редакторі зони
		}
		smsMtCommit(&mt, &p);
		NE_MODE(buf) = (char)smsMtModeNext(mode);
	}
	else
	{
		if ((ev->keys.event & KEY_MOD_LONG) || ((ev->keys.event & KEY_MOD_PRESS) == 0) || (smsMtKeyMap(mode, k) == NULL))
		{
			return false;
		}

		uint32_t now = ticksGetMillis();
		bool same = (mt.key == k) && ((now - neGetMs(buf)) < SMS_MT_TIMEOUT_MS);

		if (smsMtKey(&mt, mode, k, same, buf, &p, NAME_ED_CAP) == 1)
		{
			neSetMs(buf, now);
		}
	}

	NE_KEY(buf) = mt.key;
	NE_IDX(buf) = (char)mt.idx;
	return true;
}

bool nameEdHandleKey(char *buf, const char *title, uiEvent_t *ev)
{
	if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))
	{
		smsMt_t mt = { NE_KEY(buf), (uint8_t)NE_IDX(buf) };
		int16_t p = (int16_t)strlen(buf);

		if (mt.key != 0)
		{
			p--;   // підтверджений текст закінчується перед символом, що гортається
		}
		smsMtBackspace(&mt, buf, &p);
		NE_KEY(buf) = mt.key;
		NE_IDX(buf) = (char)mt.idx;
		nameEdDraw(buf, title);
		return true;
	}

	if (((ev->keys.key >= '0') && (ev->keys.key <= '9')) || (ev->keys.key == '*') || (ev->keys.key == KEY_HASH))
	{
		if (neKey(buf, ev))
		{
			nameEdDraw(buf, title);
		}
		return true;
	}

	return false;
}

/* R65A: див. заголовок. */
void nameEdFitLabel(char *out, unsigned num, const char *name, unsigned total)
{
	char head[8];
	unsigned h = (unsigned)snprintf(head, sizeof(head), "%u ", num);
	unsigned room = (total > h) ? (total - h) : 0U;
	unsigned n = (unsigned)strlen(name);

	memcpy(out, head, h);
	if (n <= room)
	{
		memcpy(out + h, name, n + 1U);
	}
	else if (room >= 3U)
	{
		memcpy(out + h, name, room - 2U);
		out[h + room - 2U] = '.';
		out[h + room - 1U] = '.';
		out[h + room] = 0;
	}
	else
	{
		out[h] = 0;
	}
}

#endif /* UI_NAME_EDITOR */
