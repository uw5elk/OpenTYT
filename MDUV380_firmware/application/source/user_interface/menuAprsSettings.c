/*
 * menuAprsSettings.c -- «Налаштування» меню «APRS» (R17 Г1): групи (Моя станція / Маяк / Розумний маяк / Позиція / Приймач / Скинути),
 * редактор полів (текст / число / вибір символу), стокові параметри бікона. Логіка збереження -- functions/aprs_mode.c
 * (aprsModeSettingsSessionOpen() / aprsModeMsgSessionClose()), екран не залежить від того, чи увімкнено «Слухати APRS».
 */
#include "functions/aprs_rx_cfg.h"
#include "user_interface/menuAprsSettings.h"
#include "user_interface/menuAprsStations.h"   /* R19: спільний малювальник списків у стоковому шрифті */

#if defined(APRS_RX)

#include "functions/aprs.h"
#include "functions/codeplug.h"
#include "functions/settings.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "functions/aprs_rx.h"
#include "functions/trx.h"
#include "functions/ticks.h"
#include "functions/sound.h"
#include "functions/aprs_icons.h"   /* R17: піктограми в переліку символів */
#include "user_interface/languages/aprsmode_ua.h"
#include "user_interface/languages/aprsrx_ua.h"
#include "user_interface/uiSmsKeys.h"   /* підказка літер і шпаргалка розкладки -- спільні з SMS */
#include <stdio.h>
#include <stddef.h>
#include <string.h>

extern const uint16_t initialIntervalsInSecs[];

#define AM_ROW(n)           (16 + ((n) * 10))
#define AM_FREQ_STEP        1250UL         /* 12,5 кГц в одиницях 10 Гц */

/* ---- допоміжне ----------------------------------------------------------------------------------------------- */

static void printRow(int row, const char *text)
{
	displayPrintAt(0, AM_ROW(row), text, FONT_SIZE_1);
}

/* R17: зміну відхилено, бо маяк іде зараз. Раніше settingsStep()/settingsGreen() мовчки виходили -- якщо aprsTxProgress ніколи не вертався в IDLE,
 * УСІ налаштування «не змінювались» без жодного пояснення. Тепер це видно: сповіщення + звук. */
static void notifyTxBusy(void)
{
	uiNotificationShowShort(1500, APRSM_TX_BUSY, true);
	soundSetMelody(MELODY_ERROR_BEEP);
}

static const char *fieldLabel(int f)
{
	switch (f)
	{
		case APRSM_F_FREQ:       return APRSM_L_FREQ;
		case APRSM_F_CALL:       return APRSM_L_CALL;
		case APRSM_F_SSID:       return APRSM_L_SSID;
		case APRSM_F_PATH1:      return APRSM_L_PATH1;
		case APRSM_F_PATH2:      return APRSM_L_PATH2;
		case APRSM_F_SYMBOL:     return APRSM_L_SYMBOL;
		case APRSM_F_COMMENT:    return APRSM_L_COMMENT;
		case APRSM_F_LAT:        return APRSM_L_LAT;
		case APRSM_F_LON:        return APRSM_L_LON;
		case APRSM_F_AMB:        return APRSM_L_AMB;
		case APRSM_F_INTERVAL:   return APRSM_L_INTERVAL;
		case APRSM_F_SQL:        return APRSM_L_SQL;
		default:                 return APRSM_L_RESET;
	}
}

static bool fieldIsNumeric(int f)
{
	return ((f == APRSM_F_FREQ) || (f == APRSM_F_LAT) || (f == APRSM_F_LON));
}

static bool fieldHasEditor(int f)
{
	return ((f == APRSM_F_FREQ) || (f == APRSM_F_CALL) || (f == APRSM_F_PATH1) || (f == APRSM_F_PATH2) || (f == APRSM_F_SYMBOL) ||
			(f == APRSM_F_COMMENT) || (f == APRSM_F_LAT) || (f == APRSM_F_LON));
}

static void pathStr(char *b, size_t n, const char *name, uint8_t ssid)
{
	if (name[0] == 0)
	{
		snprintf(b, n, "%s", APRSM_V_EMPTY);
	}
	else
	{
		if (ssid == 0U)
		{
			snprintf(b, n, "%s", name);   /* SSID 0 -- без «-0» (R11-fix) */
		}
		else
		{
			snprintf(b, n, APRSM_V_PATH_FMT, name, (unsigned)ssid);
		}
	}
}

static void symbolStr(char *b, size_t n, const aprsModeEff_t *e)
{
	const char *name = aprsModeSymbolName(e->iconTable, e->iconIndex);
	char t = (e->iconTable == 0U) ? '/' : '\\';
	char c = (char)('!' + e->iconIndex);

	if (name == NULL)
	{
		name = aprsSymbolNameEx(t, c);   /* R17: і назви додаткової таблиці */
	}
	if (name != NULL)
	{
		snprintf(b, n, APRSM_PK_VAL, t, c, name);
	}
	else
	{
		snprintf(b, n, APRSM_PK_VAL_RAW, t, c, (unsigned)e->iconIndex);
	}
}

/* Значення поля налаштувань для рядка списку (до 15 символів, далі обрізається у printf). */
static void fieldValue(int f, char *b, size_t n)
{
	const aprsModeEff_t *e = aprsModeEff();
	const aprsModeCfg_t *c = aprsModeCfg();
	char t[20];

	switch (f)
	{
		case APRSM_F_FREQ:
			aprsModeFormatFreq(t, sizeof(t), e->freq);
			snprintf(b, n, APRSM_V_FREQ, t);
			break;
		case APRSM_F_CALL:
			snprintf(b, n, APRSM_V_CALL_FMT, (e->call[0] != 0) ? e->call : APRSM_V_NONE);
			break;
		case APRSM_F_SSID:
			snprintf(b, n, "%u", (unsigned)e->ssid);
			break;
		case APRSM_F_PATH1:
			pathStr(b, n, e->path[0], e->pathSsid[0]);
			break;
		case APRSM_F_PATH2:
			pathStr(b, n, e->path[1], e->pathSsid[1]);
			break;
		case APRSM_F_SYMBOL:
			symbolStr(b, n, e);
			break;
		case APRSM_F_COMMENT:
			snprintf(b, n, "%s", (e->comment[0] != 0) ? e->comment : APRSM_V_EMPTY);
			break;
		case APRSM_F_LAT:
		case APRSM_F_LON:
			if (e->hasPos)
			{
				aprsModeFormatCoord(b, n, (f == APRSM_F_LAT) ? e->latU : e->lonU);
			}
			else
			{
				snprintf(b, n, "%s", APRSM_V_NONE);
			}
			break;
		case APRSM_F_AMB:
			snprintf(b, n, "%u", (unsigned)e->ambiguity);
			break;
		case APRSM_F_INTERVAL:
			if (c->interval == 0U)
			{
				snprintf(b, n, "%s", APRSM_V_INT_OFF);
			}
			else
			{
				snprintf(b, n, APRSM_V_INT_FMT, (unsigned)aprsModeIntervalMinutes(c->interval));
			}
			break;
		case APRSM_F_SQL:
			if (c->sql == 0U)
			{
				snprintf(b, n, "%s", APRSM_V_SQL_DEF);
			}
			else
			{
				snprintf(b, n, APRSM_V_SQL_FMT, (unsigned)((c->sql - 1U) * 5U));
			}
			break;
		default:
			snprintf(b, n, "%s", aprsModeUi()->resetArmed ? APRSM_V_RESET_ASK : APRSM_V_RESET);
			break;
	}
}

/* ---- редактор поля ------------------------------------------------------------------------------------------- */

/* ---- R17: вибір символу (один пункт «Символ»: перелік назв із піктограмою; для символів без назви -- «вручну»: таблиця + код) ----------------- */

#define AM_SYM_VISIBLE   3     /* R17 Г5: піктограми 24x24 -- три рядки в списку */
#define AM_SYM_ROW_H     27    /* піктограма 24x24 + проміжок 3 px */

/* Стан вибору лежить у полях редактора (розмір aprsModeUi_t не росте): mtMode -- вручну, cap -- таблиця, err -- код, pos -- номер у переліку. */
static void symPickLoad(const aprsModeEdit_t *ed, aprsSymPick_t *p)
{
	p->manual = ed->mtMode;
	p->table = ed->cap;
	p->index = ed->err;
	p->pos = (uint8_t)ed->pos;
}

static void symPickStore(aprsModeEdit_t *ed, const aprsSymPick_t *p)
{
	ed->mtMode = p->manual;
	ed->cap = p->table;
	ed->err = p->index;
	ed->pos = (int16_t)p->pos;
}

/* Піктограма 24x24; символу без піктограми -- рамка зі знаком. onBar -- малюємо на смузі вибору (кольори навпаки). */
static void symDrawIcon(int16_t x, int16_t y, uint8_t table, uint8_t index, bool onBar)
{
	char t = (table == 0U) ? '/' : '\\';
	char c = (char)('!' + index);
	bool ov = false;
	const uint8_t *ic = aprsIconFind(t, c, &ov);
	char one[2];

	if (ic != NULL)
	{
		displayDrawXBitmap(x, y, ic, APRS_ICON_W, APRS_ICON_H, (onBar == false));
	}
	else
	{
		one[0] = c;
		one[1] = 0;
		displayDrawRect(x, y, APRS_ICON_W, APRS_ICON_H, (onBar == false));
		displayPrintCore((int16_t)(x + 8), (int16_t)(y + 4), one, FONT_SIZE_3, TEXT_ALIGN_LEFT, onBar);   /* R20 Ж2.6: знак 8x16 по центру рамки */
	}
}

#if defined(ENABLE_APRS_RX_PROBE)
/* R20 Ж2: діагностичний екран «Таблиця символів» (лише diag): сітка 6x4 піктограм 24x24, сторінка 0..7 (0..3 -- первинна '/', 4..7 -- додаткова '\\').
 * Символ без піктограми -- рамка зі знаком (Ж2.6): так видно, яких піктограм бракує. Стану не має (сторінку тримає викликач) -- RAM 0. */
void menuAprsSymTableDraw(unsigned page)
{
	char title[24];
	uint8_t table = (page < MENU_APRS_SYMTAB_PAGES / 2U) ? 0U : 1U;
	unsigned base = (page % (MENU_APRS_SYMTAB_PAGES / 2U)) * MENU_APRS_SYMTAB_PER_PAGE;
	unsigned i;

	displayClearBuf();
	snprintf(title, sizeof(title), APRSM_DIAG_SYMTAB_T, (table == 0U) ? '/' : '\\', (page % (MENU_APRS_SYMTAB_PAGES / 2U)) + 1U);
	menuDisplayTitle(title);
	for (i = 0U; i < MENU_APRS_SYMTAB_PER_PAGE; i++)
	{
		unsigned idx = base + i;

		if (idx >= 94U)
		{
			break;
		}
		symDrawIcon((int16_t)(2 + ((i % 6U) * 26U)), (int16_t)(AM_ROW(0) + ((i / 6U) * 26U)), table, (uint8_t)idx, false);
	}
	displayRender();
}
#endif

static void symEditDraw(void)
{
	const aprsModeEdit_t *ed = &aprsModeUi()->edit;
	aprsSymPick_t p;
	char buf[40];

	symPickLoad(ed, &p);
	displayClearBuf();
	if (p.manual)
	{
		const char *nm;
		uint8_t tt, ii;

		menuDisplayTitle(APRSM_PK_T_MAN);
		snprintf(buf, sizeof(buf), APRSM_PK_TBL, (p.table == 0U) ? APRSM_V_TBL_PRI : APRSM_V_TBL_SEC);
		printRow(0, buf);
		snprintf(buf, sizeof(buf), APRSM_PK_CODE, (char)('!' + p.index), (unsigned)p.index);
		printRow(1, buf);
		aprsSymPickResult(&p, &tt, &ii);
		symDrawIcon(4, AM_ROW(3), tt, ii, false);
		nm = aprsSymbolNameEx((tt == 0U) ? '/' : '\\', (char)('!' + ii));
		displayPrintCore(32, (int16_t)(AM_ROW(3) + 8), (nm != NULL) ? nm : APRSM_PK_NONAME, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
		printRow(10, APRSM_PK_H_MAN);
	}
	else
	{
		int n = (int)aprsSymbolListCount();
		int top = (int)p.pos - (AM_SYM_VISIBLE / 2);

		if (top > (n - AM_SYM_VISIBLE))
		{
			top = n - AM_SYM_VISIBLE;
		}
		if (top < 0)
		{
			top = 0;
		}
		snprintf(buf, sizeof(buf), APRSM_PK_T_LIST, (unsigned)p.pos + 1U, (unsigned)n);
		menuDisplayTitle(buf);
		for (int r = 0; (r < AM_SYM_VISIBLE) && ((top + r) < n); r++)
		{
			uint8_t tt, ii;
			const char *nm = NULL;
			bool sel = ((top + r) == (int)p.pos);
			int16_t y = (int16_t)(19 + (r * AM_SYM_ROW_H));

			if (aprsSymbolListGet((unsigned)(top + r), &tt, &ii, &nm) == false)
			{
				break;
			}
			if (sel)
			{
				displayFillRect(0, (int16_t)(y - 1), DISPLAY_SIZE_X, 26, false);   /* смуга вибору */
			}
			symDrawIcon(3, y, tt, ii, sel);
			snprintf(buf, sizeof(buf), APRSM_PK_VAL, (tt == 0U) ? '/' : '\\', (char)('!' + ii), nm);
			displayPrintCore(32, (int16_t)(y + 8), buf, FONT_SIZE_1, TEXT_ALIGN_LEFT, sel);
		}
		printRow(10, APRSM_PK_H_LIST);
	}
	displayRender();
}

/* Події вибору символу. Перелік: ручка/стрілки гортають, GREEN -- вибрати, # -- вручну, RED -- скасувати.
 * Вручну: ручка/←→ -- код, ↑↓ -- таблиця, # -- назад до переліку. */
static bool symEditEvent(uiEvent_t *ev)
{
	aprsModeEdit_t *ed = &aprsModeUi()->edit;
	aprsSymPick_t p;

	if ((ev->hasEvent == false) || ((ev->events & KEY_EVENT) == 0))
	{
		return false;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		ed->active = 0U;
		return true;
	}
	symPickLoad(ed, &p);
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		aprsModeCfg_t *c = aprsModeCfg();
		uint8_t t, i;

		aprsSymPickResult(&p, &t, &i);
		c->iconTable = t;
		c->iconIndex = i;
		c->ov |= APRSM_OV_ICON;
		aprsModeCfgChanged(APRSM_OV_ICON);
		ed->active = 0U;
		return true;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH))
	{
		aprsSymPickToggle(&p);
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
	{
		aprsSymPickStep(&p, 1);
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))
	{
		aprsSymPickStep(&p, -1);
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_DOWN) || KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		if (p.manual)
		{
			aprsSymPickTable(&p);
		}
		else
		{
			aprsSymPickStep(&p, KEYCHECK_PRESS(ev->keys, KEY_DOWN) ? 1 : -1);
		}
	}
	else
	{
		return false;
	}
	symPickStore(ed, &p);
	return true;
}


static void editOpen(int field)
{
	aprsModeUi_t *u = aprsModeUi();
	aprsModeEdit_t *ed = &u->edit;
	const aprsModeEff_t *e = aprsModeEff();

	memset(ed, 0, sizeof(*ed));
	ed->active = 1U;
	ed->field = (uint8_t)field;
	if (field == APRSM_F_SYMBOL)
	{
		aprsSymPick_t p;

		aprsSymPickInit(&p, e->iconTable, e->iconIndex);
		symPickStore(ed, &p);
		return;
	}
	switch (field)
	{
		case APRSM_F_FREQ:
			ed->cap = 10U;
			break;   /* числові поля -- з порожнього рядка */
		case APRSM_F_LAT:
		case APRSM_F_LON:
			ed->cap = 11U;
			break;
		case APRSM_F_CALL:
			ed->cap = 6U;
			ed->mtMode = SMS_MT_LAT_UP;
			snprintf(ed->buf, sizeof(ed->buf), "%s", e->call);
			break;
		case APRSM_F_PATH1:
		case APRSM_F_PATH2:
		{
			int p = (field == APRSM_F_PATH1) ? 0 : 1;

			ed->cap = 8U;   /* «WIDE1-1» */
			ed->mtMode = SMS_MT_LAT_UP;
			if (e->path[p][0] != 0)
			{
				if (e->pathSsid[p] == 0U)
				{
					snprintf(ed->buf, sizeof(ed->buf), "%s", e->path[p]);   /* SSID 0 -- без «-0» (R11-fix) */
				}
				else
				{
					snprintf(ed->buf, sizeof(ed->buf), "%s-%u", e->path[p], (unsigned)e->pathSsid[p]);
				}
			}
			break;
		}
		default:   /* COMMENT */
			ed->cap = APRSM_COMMENT_MAX;
			ed->mtMode = SMS_MT_DEFAULT;
			snprintf(ed->buf, sizeof(ed->buf), "%s", e->comment);
			break;
	}
	ed->pos = (int16_t)strlen(ed->buf);
}

static void editDraw(void)
{
	aprsModeEdit_t *ed = &aprsModeUi()->edit;
	char buf[40], t[24];
	bool numeric = fieldIsNumeric(ed->field);
	int row = 1;

	if (ed->field == APRSM_F_SYMBOL)
	{
		symEditDraw();
		return;
	}
	displayClearBuf();
	menuDisplayTitle(fieldLabel(ed->field));
	if (numeric)
	{
		fieldValue(ed->field, t, sizeof(t));
		snprintf(buf, sizeof(buf), APRSM_E_NOW, t);
		printRow(row++, buf);
	}
	/* Рядок введення з курсором; поточний символ, що гортається, вже в buf. */
	snprintf(buf, sizeof(buf), "%s%s", ed->buf, (ed->mt.key == 0) ? "_" : "");
	displayPrintAt(0, AM_ROW(row + 1), buf, (ed->cap <= 12U) ? FONT_SIZE_2 : FONT_SIZE_1);
	row += 3;
	if (numeric == false)
	{
		snprintf(buf, sizeof(buf), APRSM_E_MODE, smsMtModeLabel(ed->mtMode));
		printRow(row++, buf);
	}
	switch (ed->field)
	{
		case APRSM_F_FREQ:    printRow(row++, APRSM_E_RANGE_FREQ);  break;
		case APRSM_F_LAT:     printRow(row++, APRSM_E_RANGE_LAT);   break;
		case APRSM_F_LON:     printRow(row++, APRSM_E_RANGE_LON);   break;
		case APRSM_F_CALL:    printRow(row++, APRSM_E_FMT_CALL);    break;
		case APRSM_F_COMMENT: printRow(row++, APRSM_E_FMT_COMMENT); break;
		default:              printRow(row++, APRSM_E_FMT_PATH);    break;
	}
	if (numeric)
	{
		printRow(row++, APRSM_E_EMPTY_CANCEL);
	}
	if (ed->err)
	{
		printRow(8, APRSM_E_ERR);
	}
	if (ed->field == APRSM_F_LAT || ed->field == APRSM_F_LON)
	{
		printRow(9, APRSM_E_HINT_COORD);
	}
	else if (numeric)
	{
		printRow(9, APRSM_E_HINT_NUM);
	}
	else
	{
		printRow(9, APRSM_E_HINT_TEXT);
	}
	printRow(10, numeric ? APRSM_E_HINT_BS : APRSM_E_HINT1);
	displayRender();
}

/* Текст редактора без хвостових пробілів. */
static void editTrimmed(const aprsModeEdit_t *ed, char *out, size_t n)
{
	size_t len = strlen(ed->buf);

	if (len >= n)
	{
		len = n - 1U;
	}
	memcpy(out, ed->buf, len);
	out[len] = 0;
	while ((len > 0U) && (out[len - 1U] == ' '))
	{
		out[--len] = 0;
	}
}

/* «NAME-S» -> ім'я (A-Z0-9, до 6) і SSID 0..7; порожній рядок -- «шляху нема». */
static bool parsePath(const char *txt, char name[APRSM_CALL_LEN], uint8_t *ssid)
{
	const char *dash = strchr(txt, '-');
	size_t nl = (dash != NULL) ? (size_t)(dash - txt) : strlen(txt);
	char raw[8];

	name[0] = 0;
	*ssid = 0U;
	if (txt[0] == 0)
	{
		return true;
	}
	if ((nl == 0U) || (nl > 6U))
	{
		return false;
	}
	memcpy(raw, txt, nl);
	raw[nl] = 0;
	if ((aprsModeNormCall(name, APRSM_CALL_LEN, raw) != nl) || (aprsModeCallValid(name) == false))
	{
		return false;
	}
	if (dash != NULL)
	{
		dash++;
		if ((dash[0] < '0') || (dash[0] > '9') || (dash[1] != 0) || ((dash[0] - '0') > 7))
		{
			return false;
		}
		*ssid = (uint8_t)(dash[0] - '0');
	}
	return true;
}

/* Прийняти введене. 0 -- збережено, 1 -- невірне значення, 2 -- порожньо в числовому полі (без змін). */
static int editApply(aprsModeEdit_t *ed)
{
	aprsModeCfg_t *c = aprsModeCfg();
	char txt[APRSM_COMMENT_LEN + 2];
	uint16_t bit = 0;

	editTrimmed(ed, txt, sizeof(txt));
	switch (ed->field)
	{
		case APRSM_F_FREQ:
		{
			uint32_t f;

			if (txt[0] == 0)
			{
				return 2;
			}
			if ((aprsModeParseFreq(txt, &f) == false) || (aprsModeFreqValid(f) == false))
			{
				return 1;
			}
			if (aprsModeIsTransmitting())
			{
				notifyTxBusy();   /* R17: частоту посеред маяка не міняємо (радіо не перебудувати) -- і кажемо про це */
				return 2;
			}
			c->freq = f;
			bit = APRSM_OV_FREQ;
			break;
		}
		case APRSM_F_LAT:
		case APRSM_F_LON:
		{
			int32_t u;
			bool isLat = (ed->field == APRSM_F_LAT);

			if (txt[0] == 0)
			{
				return 2;
			}
			if (aprsModeParseCoord(txt, isLat, &u) == false)
			{
				return 1;
			}
			if (isLat)
			{
				c->latU = u;
				bit = APRSM_OV_LAT;
			}
			else
			{
				c->lonU = u;
				bit = APRSM_OV_LON;
			}
			break;
		}
		case APRSM_F_CALL:
		{
			char call[APRSM_CALL_LEN];

			if ((aprsModeNormCall(call, sizeof(call), txt) != strlen(txt)) || (aprsModeCallValid(call) == false))
			{
				return 1;
			}
			memcpy(c->call, call, sizeof(c->call));
			bit = APRSM_OV_CALL;
			break;
		}
		case APRSM_F_PATH1:
		case APRSM_F_PATH2:
		{
			int p = (ed->field == APRSM_F_PATH1) ? 0 : 1;
			char name[APRSM_CALL_LEN];
			uint8_t ssid;

			if (parsePath(txt, name, &ssid) == false)
			{
				return 1;
			}
			memcpy(c->path[p], name, sizeof(c->path[p]));
			c->pathSsid[p] = ssid;
			bit = (p == 0) ? APRSM_OV_PATH1 : APRSM_OV_PATH2;
			break;
		}
		default:   /* COMMENT: cp1251 як є; до 24 символів */
			memset(c->comment, 0, sizeof(c->comment));
			memcpy(c->comment, txt, strnlen(txt, APRSM_COMMENT_MAX));
			bit = APRSM_OV_COMMENT;
			break;
	}
	c->ov |= bit;
	aprsModeCfgChanged(bit);
	return 0;
}

/* Подія редактора. Повертає true, якщо екран треба перемалювати. */
static bool editEvent(uiEvent_t *ev)
{
	aprsModeEdit_t *ed = &aprsModeUi()->edit;
	uint32_t now = ticksGetMillis();
	bool numeric = fieldIsNumeric(ed->field);

	if (ed->field == APRSM_F_SYMBOL)
	{
		return symEditEvent(ev);
	}
	if ((ev->hasEvent == false) || ((ev->events & KEY_EVENT) == 0))
	{
		return false;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		ed->active = 0U;
		return true;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		smsMtCommit(&ed->mt, &ed->pos);
		int r = editApply(ed);

		if (r == 1)
		{
			ed->err = 1U;
			soundSetMelody(MELODY_ERROR_BEEP);
		}
		else
		{
			ed->active = 0U;
		}
		return true;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_LEFT))
	{
		ed->err = 0U;
		if (numeric)
		{
			if (ed->pos > 0)
			{
				ed->buf[--ed->pos] = 0;
			}
		}
		else
		{
			smsMtBackspace(&ed->mt, ed->buf, &ed->pos);
		}
		return true;
	}
	if ((ev->keys.event & KEY_MOD_LONG) || ((ev->keys.event & KEY_MOD_PRESS) == 0))
	{
		return false;
	}

	if (numeric)
	{
		char ch = 0;

		if ((ev->keys.key >= '0') && (ev->keys.key <= '9'))
		{
			ch = (char)ev->keys.key;
		}
		else if (ev->keys.key == KEY_STAR)
		{
			ch = '.';
		}
		else if ((ev->keys.key == KEY_HASH) && (ed->field != APRSM_F_FREQ))
		{
			ch = '-';
		}
		if ((ch != 0) && (ed->pos < (int16_t)ed->cap))
		{
			ed->buf[ed->pos++] = ch;
			ed->buf[ed->pos] = 0;
			ed->err = 0U;
		}
		return true;
	}

	if (ev->keys.key == KEY_HASH)
	{
		smsMtCommit(&ed->mt, &ed->pos);
		ed->mtMode = smsMtModeNext(ed->mtMode);
		return true;
	}
	{
		char k = (char)ev->keys.key;

		if (smsMtKeyMap(ed->mtMode, k) != NULL)
		{
			bool same = (ed->mt.key == k) && ((now - ed->keyMs) < SMS_MT_TIMEOUT_MS);

			ed->err = 0U;
			if (smsMtKey(&ed->mt, ed->mtMode, k, same, ed->buf, &ed->pos, (int)ed->cap) == 1)
			{
				ed->keyMs = now;
			}
			return true;
		}
	}
	return false;
}



static int wrapStep(int v, int dir, int max)   /* 0..max, по колу */
{
	v += dir;
	if (v < 0)
	{
		v = max;
	}
	else if (v > max)
	{
		v = 0;
	}
	return v;
}

/* ←→ у налаштуваннях: перелічувані поля. */
static void settingsStep(int f, int dir)
{
	aprsModeCfg_t *c = aprsModeCfg();
	const aprsModeEff_t *e = aprsModeEff();
	uint16_t bit = 0;

	switch (f)
	{
		case APRSM_F_FREQ:
		{
			uint32_t f = (dir > 0) ? (e->freq + AM_FREQ_STEP) : (e->freq - AM_FREQ_STEP);

			if (aprsModeIsTransmitting())
			{
				notifyTxBusy();   /* R17: перебудова радіо посеред маяка неможлива; решту налаштувань можна міняти й під час маяка (кадр уже складено) */
				return;
			}
			if (aprsModeFreqValid(f))
			{
				c->freq = f;
				bit = APRSM_OV_FREQ;
			}
			break;
		}
		case APRSM_F_SSID:
			c->ssid = (uint8_t)wrapStep(e->ssid, dir, 15);
			bit = APRSM_OV_SSID;
			break;
		case APRSM_F_SYMBOL:
		{
			/* ручка на пункті «Символ»: крок по переліку названих (а для символу без назви -- по коду) без відкриття вибору */
			aprsSymPick_t p;
			uint8_t t, i;

			aprsSymPickInit(&p, e->iconTable, e->iconIndex);
			aprsSymPickStep(&p, dir);
			aprsSymPickResult(&p, &t, &i);
			c->iconTable = t;
			c->iconIndex = i;
			bit = APRSM_OV_ICON;
			break;
		}
		case APRSM_F_AMB:
			c->ambiguity = (uint8_t)wrapStep(e->ambiguity, dir, 7);
			bit = APRSM_OV_AMB;
			break;
		case APRSM_F_INTERVAL:
			c->interval = (uint8_t)wrapStep(c->interval, dir, APRSM_INTERVALS - 1);
			bit = 0x8000U;   /* не оверрайд: сам інтервал */
			break;
		case APRSM_F_SQL:
			c->sql = (uint8_t)wrapStep(c->sql, dir, APRSM_SQL_MAX);
			bit = 0x8000U;
			break;
		default:
			return;
	}
	if (bit != 0x8000U)
	{
		c->ov |= bit;
	}
	aprsModeCfgChanged(bit);
}


/* ================================================================================================================ */
/* R17 Г1: меню «Налаштування» -- групи (Моя станція / Маяк / Розумний маяк / Позиція / Приймач / Скинути).           */
/*                                                                                                                  */
/* Рядки двох видів:                                                                                                */
/*  - поля «Режиму APRS» (APRSM_F_*: позивний, SSID, символ, коментар, шляхи, позиція, частота, шумодав...) -- лежать у */
/*    aprsModeCfg() і пишуться у флеш після паузи в редагуванні (aprsModeCfgSessionTick()) або при закритті сесії;     */
/*  - стокові налаштування бікона (AS_S_*: режим, потужність, інтервал, стиснення, розумний маяк, джерело позиції) -- */
/*    редагуються в aprsSettingsCopy, як у стоковому меню «Налаштування APRS», і застосовуються при закритті сесії   */
/*    (aprsModeMsgSessionClose()); «Вікно маяка» застосовується одразу (aprsRxBcnWinSetMode() побічних дій не має).   */
/* Стан екрана -- у aprsModeUi() (блок сесії, нових змінних нема): u->msg.view -- рівень (0 групи, 1 рядки),          */
/* u->scroll -- група, u->sel -- рядок у групі, u->resetArmed -- «Скинути»: перше GREEN натиснуто.                    */
/* ================================================================================================================ */

#define AS_LEVEL(u)      ((u)->msg.view)
#define AS_LEVEL_GROUPS  0U
#define AS_LEVEL_ROWS    1U

/* Стокові рядки: номери від 32, щоб не збігатися з APRSM_F_*. */
enum
{
	AS_S_MODE = 32, AS_S_POWER, AS_S_BINT, AS_S_COMPR, AS_S_SLOW, AS_S_FAST, AS_S_LOWSPD, AS_S_HISPD, AS_S_ANGLE, AS_S_SLOPE,
	AS_S_TIME, AS_S_DECAY, AS_S_SOURCE, AS_S_BCNWIN, AS_S_QSY   /* R21 З4: QSY у коментарі маяка -- у блоці режиму, не в стокових налаштуваннях (рядок є лише при APRS_R21_QSY) */
};

enum { AS_G_STATION = 0, AS_G_BEACON, AS_G_SMART, AS_G_POS, AS_G_RX, AS_G_RESET, AS_G_COUNT };

static const uint8_t asRowsStation[] = { APRSM_F_CALL, APRSM_F_SSID, APRSM_F_SYMBOL, APRSM_F_COMMENT };
static const uint8_t asRowsBeacon[] = { AS_S_MODE, AS_S_POWER, AS_S_BINT, APRSM_F_PATH1, APRSM_F_PATH2, AS_S_COMPR,
#if defined(APRS_R21_QSY)
		AS_S_QSY,
#endif
		APRSM_F_INTERVAL };
static const uint8_t asRowsSmart[] = { AS_S_SLOW, AS_S_FAST, AS_S_LOWSPD, AS_S_HISPD, AS_S_ANGLE, AS_S_SLOPE, AS_S_TIME, AS_S_DECAY };
static const uint8_t asRowsPos[] = { AS_S_SOURCE, APRSM_F_LAT, APRSM_F_LON, APRSM_F_AMB };
static const uint8_t asRowsRx[] = { APRSM_F_FREQ, APRSM_F_SQL, AS_S_BCNWIN };

typedef struct
{
	const uint8_t *rows;
	uint8_t        n;
	const char    *name;
} asGroup_t;

#define AS_N(a)  ((uint8_t)(sizeof(a) / sizeof((a)[0])))

static const asGroup_t asGroups[AS_G_COUNT] =
{
	{ asRowsStation, AS_N(asRowsStation), APRSM_G_STATION },
	{ asRowsBeacon,  AS_N(asRowsBeacon),  APRSM_G_BEACON },
	{ asRowsSmart,   AS_N(asRowsSmart),   APRSM_G_SMART },
	{ asRowsPos,     AS_N(asRowsPos),     APRSM_G_POS },
	{ asRowsRx,      AS_N(asRowsRx),      APRSM_G_RX },
	{ NULL,          0U,                  APRSM_G_RESET }
};

static int asRowId(const aprsModeUi_t *u)
{
	const asGroup_t *g = &asGroups[(u->scroll < AS_G_COUNT) ? u->scroll : 0U];

	return (u->sel < g->n) ? (int)g->rows[u->sel] : -1;
}

/* Стокові рядки -- таблицями (менше коду: діагностична збірка впритул до фіксованої адреси кодека). Числові: поле aprsSettingsCopy.smart.* (зсув, межі
 * стокового меню, крок із SK2); перелічувані: індекс 0..count-1 (режим бікона, джерело позиції, вікно маяка, стиснення, затухання). */
typedef struct
{
	uint8_t     id;
	uint8_t     off;     /* зсув поля в aprsBeaconingSettings_t */
	uint8_t     lo;
	uint8_t     hi;
	uint8_t     step;    /* крок при утриманні SK2 */
	uint8_t     mul;     /* множник показу (нахил: 10) */
	const char *label;
	const char *fmt;
} asNum_t;

#define AS_NUM(i, f, lo, hi, st, mul, lb, fm)  { (i), (uint8_t)offsetof(aprsBeaconingSettings_t, f), (lo), (hi), (st), (mul), (lb), (fm) }
static const asNum_t asNums[] =
{
	AS_NUM(AS_S_SLOW,   smart.slowRate,  APRS_SMART_BEACON_SLOW_RATE_MIN,  APRS_SMART_BEACON_SLOW_RATE_MAX,  10U, 1U,  APRSM_L_SLOW,   APRSM_V_MIN),
	AS_NUM(AS_S_FAST,   smart.fastRate,  APRS_SMART_BEACON_FAST_RATE_MIN,  APRS_SMART_BEACON_FAST_RATE_MAX,  10U, 1U,  APRSM_L_FAST,   APRSM_V_SEC),
	AS_NUM(AS_S_LOWSPD, smart.lowSpeed,  APRS_SMART_BEACON_LOW_SPEED_MIN,  APRS_SMART_BEACON_LOW_SPEED_MAX,  4U,  1U,  APRSM_L_LOWSPD, APRSM_V_KMH),
	AS_NUM(AS_S_HISPD,  smart.highSpeed, APRS_SMART_BEACON_HIGH_SPEED_MIN, APRS_SMART_BEACON_HIGH_SPEED_MAX, 10U, 1U,  APRSM_L_HISPD,  APRSM_V_KMH),
	AS_NUM(AS_S_ANGLE,  smart.turnAngle, APRS_SMART_BEACON_TURN_ANGLE_MIN, APRS_SMART_BEACON_TURN_ANGLE_MAX, 10U, 1U,  APRSM_L_ANGLE,  APRSM_V_DEG),
	AS_NUM(AS_S_SLOPE,  smart.turnSlope, APRS_SMART_BEACON_TURN_SLOPE_MIN, APRS_SMART_BEACON_TURN_SLOPE_MAX, 10U, 10U, APRSM_L_SLOPE,  APRSM_V_PLAIN),
	AS_NUM(AS_S_TIME,   smart.turnTime,  APRS_SMART_BEACON_TURN_TIME_MIN,  APRS_SMART_BEACON_TURN_TIME_MAX,  10U, 1U,  APRSM_L_TIME,   APRSM_V_SEC),
	AS_NUM(AS_S_BINT,   initialInterval, APRS_BEACON_INITIAL_INTERVAL_MIN, APRS_BEACON_INITIAL_INTERVAL_MAX, 1U,  1U,  APRSM_L_BINT,   NULL),   /* показ -- asStockValue() */
	AS_NUM(AS_S_POWER,  power,           0U,                               0U,                               1U,  1U,  APRSM_L_POWER,  NULL)    /* верхня межа -- у asStockStep() (залежить від кодплуга) */
};

typedef struct
{
	uint8_t     id;
	uint8_t     count;
	const char *label;
	const char *names[5];
} asEnum_t;

static const asEnum_t asEnums[] =
{
	{ AS_S_MODE,   5U, APRSM_L_BMODE,  { APRSM_V_BM0, APRSM_V_BM1, APRSM_V_BM2, APRSM_V_BM3, APRSM_V_BM4 } },
	{ AS_S_COMPR,  2U, APRSM_L_COMPR,  { APRSM_V_OFF, APRSM_V_ON } },
	{ AS_S_DECAY,  2U, APRSM_L_DECAY,  { APRSM_V_OFF, APRSM_V_ON } },
	{ AS_S_SOURCE, 2U, APRSM_L_SOURCE, { APRSM_V_SRC_CH, APRSM_V_SRC_GPS } },
#if defined(APRS_R21_QSY)
	{ AS_S_QSY,    2U, APRSM_L_QSY,    { APRSM_V_OFF, APRSM_V_ON } },
#endif
	{ AS_S_BCNWIN, 3U, APRSM_L_BCNWIN, { APRSRX_OPT_BCNWIN_ALL, APRSRX_OPT_BCNWIN_NEW, APRSRX_OPT_BCNWIN_OFF } }
};

static const asNum_t *asNumOf(int r)
{
	for (unsigned i = 0; i < (sizeof(asNums) / sizeof(asNums[0])); i++)
	{
		if (asNums[i].id == r)
		{
			return &asNums[i];
		}
	}
	return NULL;
}

static const asEnum_t *asEnumOf(int r)
{
	for (unsigned i = 0; i < (sizeof(asEnums) / sizeof(asEnums[0])); i++)
	{
		if (asEnums[i].id == r)
		{
			return &asEnums[i];
		}
	}
	return NULL;
}

static const char *asLabel(int r)
{
	const asNum_t *n;
	const asEnum_t *e;

	if (r < AS_S_MODE)
	{
		return fieldLabel(r);
	}
	n = asNumOf(r);
	if (n != NULL)
	{
		return n->label;
	}
	e = asEnumOf(r);
	return (e != NULL) ? e->label : "";
}

static uint8_t asEnumGet(int r)
{
	const aprsBeaconingSettings_t *s = &aprsSettingsCopy;

	switch (r)
	{
		case AS_S_MODE:   return (uint8_t)s->mode;
		case AS_S_COMPR:  return ((s->state & APRS_BEACONING_STATE_COMPRESSED_FORMAT) != 0U) ? 1U : 0U;
		case AS_S_DECAY:  return ((s->state & APRS_BEACONING_STATE_DECAY_ALGO_ENABLED) != 0U) ? 1U : 0U;
		case AS_S_SOURCE: return ((s->state & APRS_BEACONING_STATE_LOCATION_FROM_GPS) != 0U) ? 1U : 0U;
#if defined(APRS_R21_QSY)
		case AS_S_QSY:    return (aprsModeCfg()->qsyOff != 0U) ? 0U : 1U;   /* R21 З4 */
#endif
		default:          return aprsRxBcnWinMode();
	}
}

static void asEnumSet(int r, uint8_t v)
{
	aprsBeaconingSettings_t *s = &aprsSettingsCopy;
	uint8_t bit = 0U;

	switch (r)
	{
		case AS_S_MODE:
			s->mode = (aprsBeaconingMode_t)v;
			return;
		case AS_S_BCNWIN:
			aprsRxBcnWinSetMode(v);
			return;
#if defined(APRS_R21_QSY)
		case AS_S_QSY:
			aprsModeCfg()->qsyOff = (v != 0U) ? 0U : 1U;   /* R21 З4: у блоці режиму; запис у флеш -- як у решти полів (aprsModeCfgChanged) */
			aprsModeCfgChanged(0x8000U);
			return;
#endif
		case AS_S_COMPR:  bit = (uint8_t)APRS_BEACONING_STATE_COMPRESSED_FORMAT; break;
		case AS_S_DECAY:  bit = (uint8_t)APRS_BEACONING_STATE_DECAY_ALGO_ENABLED; break;
		default:          /* AS_S_SOURCE: канал / GPS -- два біти стану (інший скидається) */
			s->state = (aprsBeaconingStates_t)(((uint8_t)s->state & (uint8_t)~(APRS_BEACONING_STATE_LOCATION_FROM_CHANNEL | APRS_BEACONING_STATE_LOCATION_FROM_GPS)) |
					(uint8_t)((v != 0U) ? APRS_BEACONING_STATE_LOCATION_FROM_GPS : APRS_BEACONING_STATE_LOCATION_FROM_CHANNEL));
			return;
	}
	s->state = (aprsBeaconingStates_t)((v != 0U) ? ((uint8_t)s->state | bit) : ((uint8_t)s->state & (uint8_t)~bit));
}

static void asStockValue(int r, char *b, size_t n)
{
	const aprsBeaconingSettings_t *s = &aprsSettingsCopy;
	const asNum_t *nm = asNumOf(r);

	if (nm == NULL)
	{
		const asEnum_t *e = asEnumOf(r);
		uint8_t v = asEnumGet(r);

		snprintf(b, n, "%s", ((e != NULL) && (v < e->count)) ? e->names[v] : APRSM_V_NONE);
		return;
	}
	if (r == AS_S_POWER)
	{
		if (s->power == 0U)
		{
			snprintf(b, n, "%s", APRSM_V_PWR_CH);
		}
		else
		{
			snprintf(b, n, "%s%s", getPowerLevel((uint8_t)(s->power - 1U)), getPowerLevelUnit((uint8_t)(s->power - 1U)));
		}
		return;
	}
	if (r == AS_S_BINT)
	{
		unsigned tenths = (unsigned)(((uint32_t)initialIntervalsInSecs[(s->initialInterval <= APRS_BEACON_INITIAL_INTERVAL_MAX) ? s->initialInterval : 0U] * 10U) / 60U);

		if ((tenths % 10U) != 0U)
		{
			snprintf(b, n, APRSM_V_MIN_D, tenths / 10U, tenths % 10U);
		}
		else
		{
			snprintf(b, n, APRSM_V_MIN, tenths / 10U);
		}
		return;
	}
	snprintf(b, n, nm->fmt, (unsigned)(((const uint8_t *)s)[nm->off]) * (unsigned)nm->mul, 176);   /* 176 -- знак градуса для APRSM_V_DEG */
}

static void asValue(int r, char *b, size_t n)
{
	if (r >= AS_S_MODE)
	{
		asStockValue(r, b, n);
	}
	else
	{
		fieldValue(r, b, n);
	}
}

/* ←→ на стоковому рядку. big -- SK2 утримується: крок як у стоковому меню. */
static void asStockStep(int r, int dir, bool big)
{
	const asNum_t *nm = asNumOf(r);

	if (nm == NULL)
	{
		const asEnum_t *e = asEnumOf(r);
		int v = (int)asEnumGet(r) + dir;

		if ((e != NULL) && (v >= 0) && (v < (int)e->count))
		{
#if !defined(HAS_GPS)
			if (r == AS_S_SOURCE)
			{
				return;   /* GPS нема -- єдине джерело: позиція каналу */
			}
#endif
			asEnumSet(r, (uint8_t)v);
		}
		return;
	}
	{
		uint8_t *f = &((uint8_t *)&aprsSettingsCopy)[nm->off];
		int hi = (r == AS_S_POWER) ? (MAX_POWER_SETTING_NUM + CODEPLUG_MIN_PER_CHANNEL_POWER) : (int)nm->hi;
		int v = (int)*f + (dir * ((big && (r != AS_S_POWER)) ? (int)nm->step : 1));

		*f = (uint8_t)((v < (int)nm->lo) ? nm->lo : ((v > hi) ? hi : v));
	}
}

/* «Скинути налаштування»: поля режиму -- типові (aprsModeCfgReset()), стокові параметри бікона, що є в цьому меню, -- типові значення прошивки.
 * «Режим» бікона НЕ чіпаємо (тихо вимкнути чи ввімкнути передачу користувачу не обіцяли). */
static void asResetAll(void)
{
	aprsBeaconingSettings_t *s = &aprsSettingsCopy;

	aprsModeCfgReset();
	s->power = 0U;
	s->initialInterval = APRS_BEACON_INITIAL_INTERVAL_DEFAULT;
	s->state = (aprsBeaconingStates_t)(((uint8_t)s->state & (uint8_t)~(APRS_BEACONING_STATE_LOCATION_FROM_GPS)) |
			(uint8_t)(APRS_BEACONING_STATE_LOCATION_FROM_CHANNEL | APRS_BEACONING_STATE_DECAY_ALGO_ENABLED | APRS_BEACONING_STATE_COMPRESSED_FORMAT));
	s->smart.slowRate = APRS_SMART_BEACON_SLOW_RATE_DEFAULT;
	s->smart.fastRate = APRS_SMART_BEACON_FAST_RATE_DEFAULT;
	s->smart.lowSpeed = APRS_SMART_BEACON_LOW_SPEED_DEFAULT;
	s->smart.highSpeed = APRS_SMART_BEACON_HIGH_SPEED_DEFAULT;
	s->smart.turnAngle = APRS_SMART_BEACON_TURN_ANGLE_DEFAULT;
	s->smart.turnSlope = APRS_SMART_BEACON_TURN_SLOPE_DEFAULT;
	s->smart.turnTime = APRS_SMART_BEACON_TURN_TIME_DEFAULT;
	aprsRxBcnWinSetMode(0U);
}

/* Рядок списку груп: «Скинути налаштув.» у режимі підтвердження показує запит. */
static void asGroupText(int g, char *buf, size_t cap, int *opt)
{
	const aprsModeUi_t *u = aprsModeUi();
	const char *name = asGroups[g].name;

	(void)opt;
	if ((g == AS_G_RESET) && u->resetArmed)
	{
		name = APRSM_G_RESET_ASK;
	}
	snprintf(buf, cap, "%s", name);
}

/* Рядок поля групи: «мітка:значення», значення -- кольором опцій. Частота без « МГц» -- щоб влізла в 18 стовпців. */
static void asRowText(int r, char *buf, size_t cap, int *opt)
{
	const aprsModeUi_t *u = aprsModeUi();
	const asGroup_t *g = &asGroups[(u->scroll < AS_G_COUNT) ? u->scroll : 0U];
	int id = g->rows[r];
	const char *lbl = asLabel(id);
	char val[32];

	if (id == APRSM_F_FREQ)
	{
		aprsModeFormatFreq(val, sizeof(val), aprsModeEff()->freq);
	}
	else
	{
		asValue(id, val, sizeof(val));
	}
	snprintf(buf, cap, "%s:%s", lbl, val);
	*opt = (int)strlen(lbl) + 1;
}

static void asDraw(void)
{
	aprsModeUi_t *u = aprsModeUi();

	u->lastDrawMs = ticksGetMillis();
	if (u->edit.active)
	{
		editDraw();
		return;
	}
	displayClearBuf();
	if (AS_LEVEL(u) == AS_LEVEL_GROUPS)
	{
		menuDisplayTitle(APRSM_SET_TITLE);
		menuAprsListDraw(AS_G_COUNT, (int)u->scroll, asGroupText);
		printRow(10, APRSM_S_HINT_G);
	}
	else
	{
		const asGroup_t *g = &asGroups[(u->scroll < AS_G_COUNT) ? u->scroll : 0U];

		menuDisplayTitle(g->name);
		menuAprsListDraw((int)g->n, (int)u->sel, asRowText);
		printRow(10, APRSM_S_HINT_R);
	}
	displayRender();
}

/* GREEN на рядку: редактор (текст/число/символ) або перемикач. */
static void asRowGreen(int r)
{
	if (r < 0)
	{
		return;
	}
	if (r >= AS_S_MODE)
	{
		if ((r == AS_S_COMPR) || (r == AS_S_DECAY)
#if defined(APRS_R21_QSY)
				|| (r == AS_S_QSY)
#endif
				)
		{
			asEnumSet(r, (uint8_t)(asEnumGet(r) ^ 1U));
		}
		return;
	}
	if (fieldHasEditor(r))
	{
		editOpen(r);
	}
}

/* Подія списку (поза редактором). -1 -- вийти з «Налаштувань», 0 -- нічого, 1 -- перемалювати. */
static int asLevelEvent(uiEvent_t *ev)
{
	aprsModeUi_t *u = aprsModeUi();
	bool up, down;

	if ((ev->hasEvent == false) || ((ev->events & KEY_EVENT) == 0))
	{
		return 0;
	}
	/* ручка (LEFT/RIGHT) і ↑↓ -- обидва гортають список груп; у рядках ↑↓ -- рядки, ручка -- значення */
	up = KEYCHECK_PRESS(ev->keys, KEY_UP);
	down = KEYCHECK_PRESS(ev->keys, KEY_DOWN);
	if (AS_LEVEL(u) == AS_LEVEL_GROUPS)
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			return -1;
		}
		up = up || KEYCHECK_PRESS(ev->keys, KEY_LEFT);
		down = down || KEYCHECK_PRESS(ev->keys, KEY_RIGHT);
		if (up || down)
		{
			u->scroll = (uint8_t)wrapStep(u->scroll, down ? 1 : -1, AS_G_COUNT - 1);
			u->resetArmed = 0U;
			return 1;
		}
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			if (u->scroll == AS_G_RESET)
			{
				if (u->resetArmed)
				{
					u->resetArmed = 0U;
					if (aprsModeIsTransmitting())
					{
						notifyTxBusy();
					}
					else
					{
						asResetAll();
					}
				}
				else
				{
					u->resetArmed = 1U;
				}
				return 1;
			}
			AS_LEVEL(u) = AS_LEVEL_ROWS;
			u->sel = 0U;
			return 1;
		}
		return 0;
	}

	/* рівень рядків */
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		AS_LEVEL(u) = AS_LEVEL_GROUPS;
		return 1;
	}
	if (up || down)
	{
		u->sel = (uint8_t)wrapStep(u->sel, down ? 1 : -1, asGroups[u->scroll].n - 1);
		return 1;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_LEFT))
	{
		int r = asRowId(u);
		int dir = KEYCHECK_PRESS(ev->keys, KEY_RIGHT) ? 1 : -1;

		if (r >= AS_S_MODE)
		{
			asStockStep(r, dir, BUTTONCHECK_DOWN(ev, BUTTON_SK2));
		}
		else if (r >= 0)
		{
			settingsStep(r, dir);
		}
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		asRowGreen(asRowId(u));
		return 1;
	}
#if defined(APRS_R21_MENU)
	/* R21 З5: пресети розумного маяка -- цифри 0..6, як у стоковому екрані (Default, Car, e-Bike, Bike, Walking, Sailing, APRSdroid); лише в групі «Розумний маяк» */
	if ((u->scroll == AS_G_SMART) && KEYCHECK_SHORTUP_NUMBER(ev->keys) && (BUTTONCHECK_DOWN(ev, (BUTTON_SK1 | BUTTON_SK2)) == 0))
	{
		const char *nm = NULL;
		const aprsSmartBeaconingSettings_t *pr = aprsSmartPresetGet((unsigned)(ev->keys.key - '0'), &nm);

		if (pr != NULL)
		{
			memcpy(&aprsSettingsCopy.smart, pr, sizeof(aprsSmartBeaconingSettings_t));
			uiNotificationShowShort(1000, nm, false);
			return 1;
		}
	}
#endif
	return 0;
}

/* ---- публічне ---------------------------------------------------------------------------------------------------- */

bool menuAprsSettingsEnter(void)
{
	aprsModeUi_t *u;

	if (aprsModeSettingsSessionOpen() == false)
	{
		uiNotificationShowShort(1500, APRSM_NOT_NOW, true);
		soundSetMelody(MELODY_ERROR_BEEP);
		return false;
	}
	u = aprsModeUi();
	AS_LEVEL(u) = AS_LEVEL_GROUPS;
	u->scroll = 0U;
	u->sel = 0U;
	asDraw();
	return true;
}

/* Кожен тік меню «APRS», поки відкрито «Налаштування». false -- користувач вийшов (RED з групп): сесію закрито (записано), треба перемалювати меню. */
bool menuAprsSettingsTick(uiEvent_t *ev)
{
	aprsModeUi_t *u = aprsModeUi();
	uint32_t now = ticksGetMillis();
	bool redraw = false;

	if (aprsModeCfgSessionActive() == false)
	{
		return false;
	}
	aprsModeCfgSessionTick();   /* запис у флеш після паузи в редагуванні */
	if (u->edit.active)
	{
		redraw = editEvent(ev);
		/* символ, що гортається, підтверджується сам через ~1 с */
		if (u->edit.active && (u->edit.mt.key != 0) && ((now - u->edit.keyMs) >= SMS_MT_TIMEOUT_MS))
		{
			smsMtCommit(&u->edit.mt, &u->edit.pos);
			redraw = true;
		}
	}
	else
	{
		int r = asLevelEvent(ev);

		if (r < 0)
		{
			aprsModeMsgSessionClose();   /* записати налаштування режиму, застосувати стокові, віддати кільце */
			return false;
		}
		redraw = (r > 0);
	}
	if ((ev->hasEvent) && (ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		redraw = true;
	}
	if (redraw)
	{
		asDraw();
	}
	return true;
}

#endif /* APRS_RX */
