/*
 * menuAprsMode.c -- екран «Повідом. APRS» меню «APRS» (R11, R13, R15; R17 Г1: «Режим APRS» зі сторінками «Монітор»/«Станції»/«Налаштування» прибрано --
 * налаштування тепер у menuAprsSettings.c, станції й пакети -- menuAprsStations.c, «Слухати APRS» -- пункт menuAprsHub.c).
 * Список (Нове / Вхідні / Надіслані), читання з перенесенням за словами великим шрифтом, «Нове» (адресат Latin + текст кирилицею, multitap),
 * «Відповісти»; логіка й черга -- aprs_msg.c / aprs_mode.c (aprsMsgBgTick() працює на будь-якому екрані).
 * Стан екрана -- у aprsModeUi() (блок сесії в резерві постійного блока повідомлень; нових змінних у main RAM нема).
 */
#include "user_interface/menuAprsMode.h"

#if defined(APRS_RX)

#include "user_interface/menuAprsStations.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "functions/aprs_rx.h"
#include "functions/trx.h"
#include "functions/ticks.h"
#include "functions/sound.h"
#include "user_interface/languages/aprsmode_ua.h"
#include "user_interface/languages/aprsmsg_ua.h"
#include "user_interface/uiSmsKeys.h"   /* R11-fix2: підказка літер і шпаргалка розкладки -- спільні з SMS */
#include <stdio.h>
#include <string.h>

#define AM_ROW(n)           (16 + ((n) * 10))

/* ---- допоміжне ----------------------------------------------------------------------------------------------- */

static void printRow(int row, const char *text)
{
	displayPrintAt(0, AM_ROW(row), text, FONT_SIZE_1);
}

/* ---- R11: сторінка «Повідомлення» ---------------------------------------------------------------------------- */

#define AM_MSG_REDRAW_MS    500U
#define AM_MSG_COLS         20           /* і великий шрифт 8x16, і малий 8x8 -- по 8 px на символ, 20 у рядку на екрані 160 px (як UI_SMS_COLS у DMR) */

/* R15: шрифт тексту повідомлень -- ТОЙ САМИЙ біт «Шрифт SMS» (BIT_SMS_FONT_SMALL), що й у SMS DMR (menuMessages.c): великий 8x16 (типово)
 * або малий 8x8. Правило те саме, що в читанні/наборі DMR. lineH -- крок рядків читання, lineHc -- крок рядків набору. */
typedef struct
{
	ucFont_t font;
	int16_t  glyphH;
	int16_t  lineH;    /* читання */
	int16_t  lineHc;   /* набір */
} amMsgFont_t;

static amMsgFont_t amMsgFont(void)
{
	amMsgFont_t f;
	bool big = (settingsIsOptionBitSet(BIT_SMS_FONT_SMALL) == false);

	f.font   = big ? FONT_SIZE_3 : FONT_SIZE_2;
	f.glyphH = big ? FONT_SIZE_3_HEIGHT : FONT_SIZE_2_HEIGHT;
	f.lineH  = big ? FONT_SIZE_3_HEIGHT : 11;
	f.lineHc = big ? FONT_SIZE_3_HEIGHT : 14;
	return f;
}


static const char *msgStatusWord(uint8_t st)
{
	switch (st)
	{
		case AMSG_ST_WAIT:  return APRSMSG_ST_WAIT;
		case AMSG_ST_SENT:  return APRSMSG_ST_SENT;
		case AMSG_ST_ACK:   return APRSMSG_ST_ACK;
		case AMSG_ST_NOACK: return APRSMSG_ST_NOACK;
		default:            return "";
	}
}

static void msgAgeStr(char *b, size_t n, const aprsMsgEntry_t *e, uint32_t now)
{
	if (e->noTime)
	{
		snprintf(b, n, "%s", APRSMSG_L_NOTIME);
	}
	else
	{
		menuAprsStationsAgeStr(b, n, (uint32_t)(now - e->ms) / 1000U);
	}
}

/* R15: перший екран «Повідом. APRS» -- Нове / Вхідні / Надіслані. R18: «Вхідні n/m» (n -- прочитані, m -- усього вхідних), «Надіслані» -- усі записи
 * напрямку (раніше рахувалась черга передачі і після відправки була 0), четвертий пункт -- «[Видалити всі]». Великий шрифт, смуга вибору. */
/* R18: у діагностичній збірці (ENABLE_APRS_RX_PROBE) видалення вимкнено -- не вистачає місця до адреси кодека (aprs_rx_cfg.h, APRS_R18_UI). */
#if defined(APRS_R18_UI)
#define AM_HOME_ITEMS  4
#else
#define AM_HOME_ITEMS  3
#endif
static void drawMsgHome(void)
{
	aprsMsgBox_t *b = aprsModeMsgBox();
	aprsMsgUi_t *mu = &aprsModeUi()->msg;
	char buf[24];

	for (int i = 0; i < AM_HOME_ITEMS; i++)
	{
		int16_t y = (int16_t)(24 + (i * 22));
		bool sel = (i == (int)mu->scroll);

		switch (i)
		{
			case 0:  snprintf(buf, sizeof(buf), "%s", APRSMSG_H_NEW); break;
			case 1:  snprintf(buf, sizeof(buf), APRSMSG_H_IN, aprsMsgDirCount(b, AMSG_DIR_IN) - aprsMsgUnreadCount(b), aprsMsgDirCount(b, AMSG_DIR_IN)); break;
			case 2:  snprintf(buf, sizeof(buf), APRSMSG_H_OUT, aprsMsgDirCount(b, AMSG_DIR_OUT)); break;
#if defined(APRS_R18_UI)
			default: snprintf(buf, sizeof(buf), "%s", APRSMSG_H_DELALL); break;
#else
			default: buf[0] = 0; break;
#endif
		}
		if (sel)
		{
			displayFillRect(0, (int16_t)(y - 1), DISPLAY_SIZE_X, 18, false);   /* смуга вибору (false -- колір переднього плану) */
		}
		displayPrintCore(2, y, buf, FONT_SIZE_3, TEXT_ALIGN_LEFT, sel);
	}
	displayPrintCentered(112, APRSMSG_H_HINT, FONT_SIZE_1);
}

/* R15: список одного напрямку (mu->dirFilter): «Вхідні» -- маркер '*' у непрочитаних; «Надіслані» -- слово стану (чекає/надіслано/ACK).
 * mu->sel -- номер у відфільтрованому списку; індекс у b->list дає aprsMsgNth(). */
static void drawMsgList(void)
{
	aprsMsgBox_t *b = aprsModeMsgBox();
	aprsMsgUi_t *mu = &aprsModeUi()->msg;
	const bool out = (mu->dirFilter == AMSG_DIR_OUT);
	unsigned count = aprsMsgDirCount(b, mu->dirFilter);
	uint32_t now = ticksGetMillis();
	char buf[40], age[8];

	snprintf(buf, sizeof(buf), out ? APRSMSG_L_HDR_OUT : APRSMSG_L_HDR, out ? aprsMsgPendingCount(b) : aprsMsgUnreadCount(b), count);
	printRow(0, buf);
	if (count == 0U)
	{
		displayPrintCentered(AM_ROW(4), APRSMSG_L_EMPTY, FONT_SIZE_1);
		printRow(10, APRSMSG_L_HINT_S);
		return;
	}
	if (mu->sel >= count)
	{
		mu->sel = (uint8_t)(count - 1U);
	}
	for (unsigned i = 0; i < count; i++)
	{
		int ri = aprsMsgNth(b, mu->dirFilter, i);
		const aprsMsgEntry_t *e;
		char mark;

		if (ri < 0)
		{
			break;
		}
		e = &b->list[ri];
		mark = (out == false) && e->unread ? '*' : ' ';
		msgAgeStr(age, sizeof(age), e, now);
		/* маркер вибору(1) + ознака(1) + позивний(9) + пробіл(1) + текст або стан(9) + вік(5) = 26 символів */
		snprintf(buf, sizeof(buf), "%c%c%-9.9s %-9.9s%5.5s", (i == mu->sel) ? '>' : ' ', mark, e->call,
				out ? msgStatusWord(e->status) : e->text, age);
		printRow(1 + (int)i, buf);
	}
#if defined(APRS_R18_UI)
	printRow(9, APRSMSG_L_HINT_D);    /* R18: видалення -- SK2+GREEN, як у «Повідомленнях» DMR */
#endif
	printRow(10, APRSMSG_L_HINT_S);   /* R17: сторінок режиму нема */
}

#if defined(APRS_R18_UI)
/* R18 Д1: підтвердження видалення (один запис або всі). mu->err: 1 -- всі; mu->reply -- вигляд, куди повернутись по RED. Видаляє лише GREEN. */
static void drawMsgConfirm(void)
{
	aprsMsgBox_t *b = aprsModeMsgBox();
	aprsMsgUi_t *mu = &aprsModeUi()->msg;
	char buf[28];

	if (mu->err != 0U)
	{
		displayPrintCentered(34, APRSMSG_Q_ALL, FONT_SIZE_3);
		snprintf(buf, sizeof(buf), APRSMSG_Q_COUNT, aprsMsgListCount(b));
		displayPrintCentered(58, buf, FONT_SIZE_1);
	}
	else
	{
		int ri = aprsMsgNth(b, mu->dirFilter, mu->sel);

		displayPrintCentered(34, APRSMSG_Q_ONE, FONT_SIZE_3);
		if (ri >= 0)
		{
			/* що саме видаляємо: позивний і початок тексту (до 26 символів) */
			snprintf(buf, sizeof(buf), "%.9s:%.16s", b->list[ri].call, b->list[ri].text);
			displayPrintCentered(58, buf, FONT_SIZE_1);
		}
	}
	displayPrintCentered(112, APRSMSG_Q_HINT, FONT_SIZE_1);
}
#endif

/* Малює рядки [first, first + rows) тексту, розбитого aprsMsgWrapLine() з шириною cols. Повертає загальну кількість рядків. */
static int drawWrapped(const char *t, int len, int first, int rows, int16_t y0, ucFont_t font, int16_t lineH)
{
	int pos = 0, line = 0;

	while (pos < len)
	{
		int ls, nx;
		int n = aprsMsgWrapLine(t, len, pos, AM_MSG_COLS, &ls, &nx);

		if (ls >= len)
		{
			break;
		}
		if ((line >= first) && (line < (first + rows)) && (n > 0))
		{
			char one[AM_MSG_COLS + 2];

			memcpy(one, t + ls, (size_t)n);
			one[n] = 0;
			displayPrintCore(0, (int16_t)(y0 + ((line - first) * lineH)), one, font, TEXT_ALIGN_LEFT, false);
		}
		line++;
		pos = nx;
	}
	return line;
}

static void drawMsgRead(void)
{
	aprsMsgBox_t *b = aprsModeMsgBox();
	aprsMsgUi_t *mu = &aprsModeUi()->msg;
	int ri = aprsMsgNth(b, mu->dirFilter, mu->sel);
	const aprsMsgEntry_t *e = &b->list[(ri >= 0) ? ri : 0];
	char buf[48], age[8];
	const int16_t y0 = 38;
	const amMsgFont_t f = amMsgFont();
	const int rows = ((111 - y0 - f.glyphH) / f.lineH) + 1;
	int total, maxTop;

	snprintf(buf, sizeof(buf), (e->dir == AMSG_DIR_OUT) ? APRSMSG_R_TO : APRSMSG_R_FROM, e->call);
	printRow(0, buf);
	msgAgeStr(age, sizeof(age), e, ticksGetMillis());
	if (e->dir == AMSG_DIR_OUT)
	{
		snprintf(buf, sizeof(buf), "%s %s", msgStatusWord(e->status), age);
		if ((e->id[0] != 0) && (strlen(buf) <= 19U))
		{
			snprintf(buf + strlen(buf), sizeof(buf) - strlen(buf), " {%s", e->id);
		}
	}
	else
	{
		snprintf(buf, sizeof(buf), "%s", age);
	}
	printRow(1, buf);

	total = drawWrapped(e->text, (int)strlen(e->text), 0, 0, y0, f.font, f.lineH);   /* лише порахувати */
	maxTop = (total > rows) ? (total - rows) : 0;
	if (mu->readTop > maxTop)
	{
		mu->readTop = (uint8_t)maxTop;
	}
	(void)drawWrapped(e->text, (int)strlen(e->text), mu->readTop, rows, y0, f.font, f.lineH);
	displayPrintCentered(112, APRSMSG_R_HINT, FONT_SIZE_1);
	if (mu->readTop > 0U)
	{
		displayFillTriangle(4, 112, 0, 119, 8, 119, true);                                   /* є вище */
	}
	if (mu->readTop < maxTop)
	{
		displayFillTriangle(DISPLAY_SIZE_X - 9, 112, DISPLAY_SIZE_X - 1, 112, DISPLAY_SIZE_X - 5, 119, true);   /* є нижче */
	}
}

/* R15: заголовок сторінки «Повідомлення» за виглядом */
static const char *msgPageTitle(void)
{
	const aprsMsgUi_t *mu = &aprsModeUi()->msg;

	if (mu->view == APRS_MSG_VIEW_READ)
	{
		return APRSMSG_TITLE_READ;
	}
	if (mu->view == APRS_MSG_VIEW_LIST)
	{
		return (mu->dirFilter == AMSG_DIR_OUT) ? APRSMSG_TITLE_OUT : APRSMSG_TITLE_IN;
	}
	return APRSMSG_TITLE;
}

static void drawMsgPage(void)
{
	aprsMsgUi_t *mu = &aprsModeUi()->msg;

	if (mu->view == APRS_MSG_VIEW_HOME)
	{
		drawMsgHome();
	}
#if defined(APRS_R18_UI)
	else if (mu->view == APRS_MSG_VIEW_CONFIRM)
	{
		drawMsgConfirm();
	}
#endif
	else if ((mu->view == APRS_MSG_VIEW_READ) && (aprsMsgNth(aprsModeMsgBox(), mu->dirFilter, mu->sel) >= 0))
	{
		drawMsgRead();
	}
	else
	{
		mu->view = (mu->view == APRS_MSG_VIEW_READ) ? APRS_MSG_VIEW_LIST : mu->view;   /* запис зник (витіснено новими) -- назад до списку */
		drawMsgList();
	}
}

/* Підказка літер клавіші, що гортається, і шпаргалка розкладки (D) -- ТА САМА реалізація, що в «Повідомленнях» DMR (uiSmsKeys.c, ui7). */
static void msgKeyHint(int16_t x, int16_t y)
{
	aprsMsgUi_t *mu = &aprsModeUi()->msg;

	uiSmsKeyHint(mu->mtMode, mu->mt.key, mu->mt.idx, x, y);
}

/* Екран набору (адресат або текст) -- на весь екран, великий шрифт. */
static void drawMsgCompose(void)
{
	aprsMsgUi_t *mu = &aprsModeUi()->msg;
	bool isCall = (mu->view == APRS_MSG_VIEW_CALL);
	const char *src = isCall ? mu->call : mu->text;
	char cur[APRS_MSG_JOB_TEXT_LEN + 4];
	char buf[40];
	const char *lbl = smsMtModeLabel(mu->mtMode);
	int16_t chipW = (int16_t)((strlen(lbl) * 6U) + 4U);
	const amMsgFont_t f = amMsgFont();
	const bool big = (f.font == FONT_SIZE_3);
	int16_t y0 = isCall ? 30 : (big ? 26 : 22);                  /* малий шрифт -- як у наборі DMR: 5 рядків по 14 px від y = 22, усе над рядком режиму (y 95) */
	int rows = isCall ? 2 : (big ? 4 : 5);
	int len, total, first;

	if (mu->layout)
	{
		/* D: шпаргалка розкладки поточного режиму (Cyrillic/Latin/цифри) -- як у SMS; будь-яка клавіша -- назад до набору */
		snprintf(buf, sizeof(buf), APRSMSG_K_TITLE, lbl);
		uiSmsKeyLayoutDraw(mu->mtMode, buf, APRSMSG_K_BACK);
		return;
	}
	displayClearBuf();
	menuDisplayTitle((isCall || (mu->reply == 0U)) ? APRSMSG_TITLE_NEW : APRSMSG_TITLE_REPLY);
	if (isCall)
	{
		printRow(0, APRSMSG_C_CALL);
	}
	else
	{
		snprintf(buf, sizeof(buf), APRSMSG_C_TO, mu->call);
		printRow(0, buf);
	}
	/* текст із курсором: символ, що гортається, вже в буфері; без нього -- підкреслення */
	snprintf(cur, sizeof(cur), "%s%s", src, (mu->mt.key == 0) ? "_" : "");
	len = (int)strlen(cur);
	total = drawWrapped(cur, len, 0, 0, y0, f.font, f.lineHc);
	first = (total > rows) ? (total - rows) : 0;   /* вікно іде за курсором: показуємо останні рядки */
	(void)drawWrapped(cur, len, first, rows, y0, f.font, f.lineHc);
	if (mu->err)
	{
		printRow(isCall ? 6 : 7, isCall ? APRSMSG_E_CALL : APRSMSG_E_TEXT);
	}

	displayFillRect(0, 95, chipW, 10, false);
	displayPrintCore(2, 96, lbl, FONT_SIZE_1, TEXT_ALIGN_LEFT, true);
	if (mu->mt.key != 0)
	{
		msgKeyHint((int16_t)(chipW + 4), 96);
	}
	else if (isCall == false)
	{
		snprintf(buf, sizeof(buf), APRSMSG_C_LEFT, (unsigned)(APRS_MSG_UTF8_MAX - aprsMsgUtf8Len(mu->text)));
		displayPrintCore(0, 96, buf, FONT_SIZE_1, TEXT_ALIGN_RIGHT, false);
		displayPrintAt((uint16_t)(chipW + 4), 96, APRSMSG_C_MODE_HINT, FONT_SIZE_1);
	}
	else
	{
		displayPrintAt((uint16_t)(chipW + 4), 96, APRSMSG_C_MODE_HINT, FONT_SIZE_1);
	}
	displayPrintCentered(106, isCall ? APRSMSG_C_CALL_HINT : APRSMSG_C_HINT1, FONT_SIZE_1);
	displayPrintCentered(116, isCall ? APRSMSG_C_CALL_KEYS : APRSMSG_C_HINT2, FONT_SIZE_1);
}

static void msgNotify(const char *txt)
{
	uiNotificationShowShort(1500, txt, true);
	soundSetMelody(MELODY_ERROR_BEEP);
}

/* Почати набір. call == NULL -- «Нове» (спершу адресат); інакше «Відповісти» (адресат заданий, одразу текст). */
static void msgComposeStart(const char *call)
{
	aprsMsgUi_t *mu = &aprsModeUi()->msg;

	mu->mt.key = 0;
	mu->mt.idx = 0;
	mu->err = 0U;
	mu->layout = 0U;
	mu->swallowUp = 0U;
	mu->pos = 0;
	mu->text[0] = 0;
	mu->call[0] = 0;
	mu->mtMode = SMS_MT_DEFAULT;
	if (call != NULL)
	{
		snprintf(mu->call, sizeof(mu->call), "%s", call);
		mu->reply = 1U;
		mu->view = APRS_MSG_VIEW_TEXT;
	}
	else
	{
		mu->reply = 0U;
		mu->mtMode = SMS_MT_LAT_UP;
		mu->view = APRS_MSG_VIEW_CALL;
	}
}

/* Допустимість символу c при наборі: адресат -- A-Z, 0-9, '-'; текст -- дозволений символ, що влазить цілим у 67 байт.
 * buf[pos] (символ, що гортається) у розрахунок не входить. */
static bool msgCharOk(bool isCall, char *buf, int16_t pos, uint8_t c)
{
	char keep = buf[pos];
	bool ok;

	if (isCall)
	{
		return ((c >= 'A') && (c <= 'Z')) || ((c >= 'a') && (c <= 'z')) || ((c >= '0') && (c <= '9')) || (c == '-');
	}
	buf[pos] = 0;
	ok = aprsMsgCanAppend(buf, c);
	buf[pos] = keep;
	return ok;
}

/* smsMtKey() з відсівом: символи, яких не можна в повідомленні (':' '|' '~' '{', керівні), і ті, що не влазять у 67 байт, при
 * гортанні пропускаються. Повертає як smsMtKey(): 0 -- нічого, 1 -- у перегляді, 2 -- підтверджено. */
static int msgMtKey(aprsMsgUi_t *mu, bool isCall, char key, bool same, char *buf, int cap)
{
	int r = smsMtKey(&mu->mt, mu->mtMode, key, same, buf, &mu->pos, cap);
	const char *map = smsMtKeyMap(mu->mtMode, key);

	if ((r == 0) || (map == NULL))
	{
		return 0;
	}
	if (r == 2)
	{
		/* єдиний варіант (цифра в «123»), уже підтверджений: pos вже зсунувся */
		uint8_t c = (uint8_t)buf[mu->pos - 1];

		mu->pos--;
		buf[mu->pos] = 0;
		if (msgCharOk(isCall, buf, mu->pos, c) == false)
		{
			return 0;
		}
		buf[mu->pos] = (char)c;
		mu->pos++;
		buf[mu->pos] = 0;
		return 2;
	}
	for (size_t tries = 0; tries <= strlen(map); tries++)
	{
		if (msgCharOk(isCall, buf, mu->pos, (uint8_t)buf[mu->pos]))
		{
			return 1;
		}
		mu->mt.idx++;
		if (map[mu->mt.idx] == 0)
		{
			mu->mt.idx = 0;
		}
		buf[mu->pos] = map[mu->mt.idx];
	}
	buf[mu->pos] = 0;   /* жоден символ клавіші тут не дозволений */
	mu->mt.key = 0;
	mu->mt.idx = 0;
	return 0;
}

/* Подія набору. Повертає true, якщо екран треба перемалювати. */
static bool msgComposeEvent(uiEvent_t *ev)
{
	aprsMsgUi_t *mu = &aprsModeUi()->msg;
	bool isCall = (mu->view == APRS_MSG_VIEW_CALL);
	char *buf = isCall ? mu->call : mu->text;
	int cap = isCall ? (int)APRS_MSG_ADDR_LEN : (int)APRS_MSG_UTF8_MAX;
	uint32_t now = ticksGetMillis();

	if ((ev->hasEvent == false) || ((ev->events & KEY_EVENT) == 0))
	{
		return false;
	}
	if (mu->layout)
	{
		/* шпаргалка відкрита: лише нове НАТИСКАННЯ закриває її (як layoutEvent() у menuMessages.c); текст не чіпається */
		if ((ev->keys.event & KEY_MOD_PRESS) && ((ev->keys.event & KEY_MOD_LONG) == 0))
		{
			mu->swallowUp = (ev->keys.event & KEY_MOD_UP) ? 0U : (uint8_t)ev->keys.key;   /* валкодер шле натискання й відпускання разом */
			mu->layout = 0U;
			return true;
		}
		return false;
	}
	if (mu->swallowUp != 0U)
	{
		/* відпускання клавіші, що закрила шпаргалку, -- RED/GREEN діють на відпусканні й інакше вийшли б із набору */
		if ((ev->keys.key == mu->swallowUp) && (ev->keys.event & KEY_MOD_UP))
		{
			mu->swallowUp = 0U;
			return false;
		}
		if (ev->keys.event & KEY_MOD_PRESS)
		{
			mu->swallowUp = 0U;
		}
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		smsMtCommit(&mu->mt, &mu->pos);   /* символ, що гортається, -- у текст */
		mu->layout = 1U;
		return true;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		smsMtCommit(&mu->mt, &mu->pos);
		if ((isCall == false) && (mu->reply == 0U))
		{
			mu->view = APRS_MSG_VIEW_CALL;   /* із тексту -- назад до адресата */
			mu->pos = (int16_t)strlen(mu->call);
			mu->mtMode = SMS_MT_LAT_UP;
		}
		else
		{
			mu->view = (mu->reply == 0U) ? APRS_MSG_VIEW_HOME : APRS_MSG_VIEW_LIST;   /* R15: «Нове» -- назад до першого екрана; «Відповісти» -- до списку */
		}
		mu->err = 0U;
		return true;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		smsMtCommit(&mu->mt, &mu->pos);
		buf[mu->pos] = 0;
		if (isCall)
		{
			char norm[APRS_MSG_CALL_LEN];

			if (aprsMsgNormCall(norm, mu->call) == false)
			{
				mu->err = 1U;
				soundSetMelody(MELODY_ERROR_BEEP);
				return true;
			}
			snprintf(mu->call, sizeof(mu->call), "%s", norm);
			mu->view = APRS_MSG_VIEW_TEXT;
			mu->mtMode = SMS_MT_DEFAULT;
			mu->pos = (int16_t)strlen(mu->text);
			mu->err = 0U;
			return true;
		}
		{
			int r = aprsModeMsgSend(mu->call, mu->text);

			if (r == AMSG_OK)
			{
				mu->view = APRS_MSG_VIEW_LIST;
				mu->dirFilter = AMSG_DIR_OUT;   /* R15: показуємо «Надіслані» -- нове повідомлення там найперше */
				mu->scroll = 2U;
				mu->sel = 0U;
				mu->err = 0U;
			}
			else if (r == -2)
			{
				msgNotify(APRSMSG_E_OFF);   /* R13: поза режимом -- стоковий APRS вимкнено/призупинено, повідомлення не передалось би */
			}
			else if (r < 0)
			{
				msgNotify(APRSM_ERR_NOCALL);
			}
			else if (r == AMSG_E_FULL)
			{
				msgNotify(APRSMSG_E_FULL);
			}
			else if (r == AMSG_E_CALL)
			{
				msgNotify(APRSMSG_E_CALL);
			}
			else
			{
				mu->err = 1U;   /* порожній текст */
				soundSetMelody(MELODY_ERROR_BEEP);
			}
		}
		return true;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_LEFT))
	{
		mu->err = 0U;
		smsMtBackspace(&mu->mt, buf, &mu->pos);
		return true;
	}
	if ((ev->keys.event & KEY_MOD_LONG) || ((ev->keys.event & KEY_MOD_PRESS) == 0))
	{
		return false;
	}
	if (ev->keys.key == KEY_HASH)
	{
		smsMtCommit(&mu->mt, &mu->pos);
		mu->mtMode = smsMtModeNext(mu->mtMode);
		return true;
	}
	{
		char k = (char)ev->keys.key;

		if (smsMtKeyMap(mu->mtMode, k) != NULL)
		{
			bool same = (mu->mt.key == k) && ((now - mu->keyMs) < SMS_MT_TIMEOUT_MS);

			mu->err = 0U;
			if (msgMtKey(mu, isCall, k, same, buf, cap) == 1)
			{
				mu->keyMs = now;
			}
			return true;
		}
	}
	return false;
}

/* Читання: сусіднє повідомлення (dir +1 -- старіше). На краях нічого. */
static void msgReadGo(int dir)
{
	aprsMsgBox_t *b = aprsModeMsgBox();
	aprsMsgUi_t *mu = &aprsModeUi()->msg;
	int n = (int)mu->sel + dir;
	int ri;

	if ((n < 0) || (n >= (int)aprsMsgDirCount(b, mu->dirFilter)))
	{
		return;
	}
	ri = aprsMsgNth(b, mu->dirFilter, (unsigned)n);
	if (ri < 0)
	{
		return;
	}
	mu->sel = (uint8_t)n;
	mu->readTop = 0U;
	aprsMsgMarkRead(b, (unsigned)ri);
}

/* Подія списку/читання. Повертає: 0 -- нічого, 1 -- перемалювати. */
static int msgPageEvent(uiEvent_t *ev)
{
	aprsModeUi_t *u = aprsModeUi();
	aprsMsgUi_t *mu = &u->msg;
	aprsMsgBox_t *b = aprsModeMsgBox();
	unsigned count = aprsMsgDirCount(b, mu->dirFilter);

	if ((ev->hasEvent == false) || ((ev->events & KEY_EVENT) == 0))
	{
		return 0;
	}
	if (mu->view == APRS_MSG_VIEW_HOME)
	{
		/* R15: перший екран -- Нове / Вхідні / Надіслані (як «Повідомлення» DMR) */
		if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN) || KEYCHECK_PRESS(ev->keys, KEY_LEFT) || KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
		{
			/* R17: ручка (LEFT/RIGHT) гортає так само, як ↑↓ -- сторінок режиму більше нема */
			int n = (int)mu->scroll + ((KEYCHECK_PRESS(ev->keys, KEY_DOWN) || KEYCHECK_PRESS(ev->keys, KEY_RIGHT)) ? 1 : -1);

			mu->scroll = (uint8_t)((n < 0) ? (AM_HOME_ITEMS - 1) : ((n > (AM_HOME_ITEMS - 1)) ? 0 : n));
			return 1;
		}
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			if (mu->scroll == 0U)
			{
				msgComposeStart(NULL);
			}
#if defined(APRS_R18_UI)
			else if (mu->scroll == 3U)
			{
				if (aprsMsgListCount(b) == 0U)
				{
					msgNotify(APRSMSG_L_EMPTY);   /* нічого видаляти */
				}
				else
				{
					mu->err = 1U;                       /* видалити ВСІ */
					mu->reply = APRS_MSG_VIEW_HOME;
					mu->view = APRS_MSG_VIEW_CONFIRM;
				}
			}
#endif
			else
			{
				mu->dirFilter = (mu->scroll == 1U) ? AMSG_DIR_IN : AMSG_DIR_OUT;
				mu->view = APRS_MSG_VIEW_LIST;
				mu->sel = 0U;
			}
			return 1;
		}
		if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			return -1;   /* R17: RED закриває екран і повертає в меню «APRS» */
		}
		return 0;
	}
#if defined(APRS_R18_UI)
	if (mu->view == APRS_MSG_VIEW_CONFIRM)
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			if (mu->err != 0U)
			{
				(void)aprsMsgDeleteAll(b);
				mu->view = APRS_MSG_VIEW_HOME;
				mu->scroll = 0U;
			}
			else
			{
				int ri = aprsMsgNth(b, mu->dirFilter, mu->sel);

				if (ri >= 0)
				{
					(void)aprsMsgDelete(b, (unsigned)ri);
				}
				mu->view = APRS_MSG_VIEW_LIST;   /* sel підправить drawMsgList() */
			}
			mu->err = 0U;
			return 1;
		}
		if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			mu->view = (mu->reply == APRS_MSG_VIEW_HOME) ? APRS_MSG_VIEW_HOME : (mu->reply == APRS_MSG_VIEW_READ) ? APRS_MSG_VIEW_READ : APRS_MSG_VIEW_LIST;
			mu->err = 0U;
			return 1;
		}
		return 0;
	}
	if (((mu->view == APRS_MSG_VIEW_READ) || (mu->view == APRS_MSG_VIEW_LIST)) && KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && BUTTONCHECK_DOWN(ev, BUTTON_SK2)
			&& (mu->sel < count) && (aprsMsgNth(b, mu->dirFilter, mu->sel) >= 0))
	{
		/* R18 Д1: SK2+GREEN -- видалити поточний запис (з підтвердженням), як у «Повідомленнях» DMR */
		mu->err = 0U;
		mu->reply = mu->view;
		mu->view = APRS_MSG_VIEW_CONFIRM;
		return 1;
	}
#endif
	if (mu->view == APRS_MSG_VIEW_READ)
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			mu->view = APRS_MSG_VIEW_LIST;
			return 1;
		}
		if (KEYCHECK_PRESS(ev->keys, KEY_UP) && (mu->readTop > 0U))
		{
			mu->readTop--;
			return 1;
		}
		if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
		{
			mu->readTop++;   /* верхню межу виправить drawMsgRead() */
			return 1;
		}
		if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
		{
			msgReadGo(+1);
			return 1;
		}
		if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))
		{
			msgReadGo(-1);
			return 1;
		}
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (mu->sel < count) && (aprsMsgNth(b, mu->dirFilter, mu->sel) >= 0))
		{
			char norm[APRS_MSG_CALL_LEN];

			if (aprsMsgNormCall(norm, b->list[aprsMsgNth(b, mu->dirFilter, mu->sel)].call))
			{
				msgComposeStart(norm);
			}
			else
			{
				msgNotify(APRSMSG_E_CALL);
			}
			return 1;
		}
		return 0;
	}

	/* список (R15: одного напрямку); RED -- назад до першого екрана */
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		mu->view = APRS_MSG_VIEW_HOME;
		return 1;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN) || KEYCHECK_PRESS(ev->keys, KEY_LEFT) || KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
	{
		/* R17: ручка (LEFT/RIGHT) гортає список так само, як ↑↓ (раніше була без дії) */
		int n = (int)mu->sel + ((KEYCHECK_PRESS(ev->keys, KEY_DOWN) || KEYCHECK_PRESS(ev->keys, KEY_RIGHT)) ? 1 : -1);

		if (count > 0U)
		{
			mu->sel = (uint8_t)((n < 0) ? (int)(count - 1U) : ((n >= (int)count) ? 0 : n));   // по колу
		}
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (count > 0U))
	{
		if (mu->sel >= count)
		{
			mu->sel = (uint8_t)(count - 1U);
		}
		mu->view = APRS_MSG_VIEW_READ;
		mu->readTop = 0U;
		aprsMsgMarkRead(b, (unsigned)aprsMsgNth(b, mu->dirFilter, mu->sel));
		return 1;
	}
	return 0;
}

/* Режим відкрито на сторінці «Повідомлення»: список зверху. */
static void msgOpenPage(void)
{
	aprsModeUi_t *u = aprsModeUi();

	u->page = APRS_MODE_PAGE_MESSAGES;
	u->resetArmed = 0U;
	u->msg.view = APRS_MSG_VIEW_HOME;   /* R15: спершу Нове / Вхідні / Надіслані */
	u->msg.dirFilter = AMSG_DIR_IN;
	u->msg.scroll = 0U;
	u->msg.sel = 0U;
	u->msg.readTop = 0U;
	u->msg.err = 0U;
	u->msg.mt.key = 0;
	u->msg.mt.idx = 0;
}


/* ---- екран --------------------------------------------------------------------------------------------------- */

static bool msgComposing(const aprsModeUi_t *u)
{
	return (u->msg.view == APRS_MSG_VIEW_CALL) || (u->msg.view == APRS_MSG_VIEW_TEXT);
}

static void draw(void)
{
	aprsModeUi_t *u = aprsModeUi();

	u->lastDrawMs = ticksGetMillis();
	if (msgComposing(u))
	{
		drawMsgCompose();   /* R11: набір -- на весь екран, з власним заголовком */
		displayRender();
		return;
	}
	displayClearBuf();
	menuDisplayTitle(msgPageTitle());
	drawMsgPage();
	displayRender();
}

/* «Повідом. APRS» у меню «APRS» -- канал, режим радіо й приймач не чіпаємо (працює і з увімкненим «Слухати APRS», і без нього). Читання, «Відповісти», «Нове»;
 * надсилання -- у фонову чергу (aprsMsgBgTick()). Закриває RED з першого екрана (menuAprsModeTick() -> false). */
bool menuAprsMsgEnter(void)
{
	if (aprsModeMsgSessionOpen() == false)
	{
		return false;
	}
	msgOpenPage();
	draw();
	return true;
}

bool menuAprsModeReplyTo(const char *call)
{
	char norm[APRS_MSG_CALL_LEN];

	if ((call == NULL) || (aprsMsgNormCall(norm, call) == false))
	{
		msgNotify(APRSMSG_E_CALL);   /* об'єкти, станції з нестандартним позначенням -- адресатом бути не можуть */
		return false;
	}
	if (aprsModeMsgSessionOpen() == false)
	{
		return false;
	}
	aprsRxUi()->on = 0;   /* екран станцій закриваємо: далі всі тіки меню належать екрану повідомлень */
	msgOpenPage();
	msgComposeStart(norm);
	draw();
	return true;
}

bool menuAprsModeTick(uiEvent_t *ev)
{
	aprsModeUi_t *u = aprsModeUi();
	uint32_t now = ticksGetMillis();
	bool redraw = false;

	if (msgComposing(u))
	{
		/* R11: набір повідомлення (адресат/текст) -- свій обробник; символ, що гортається, підтверджується сам через ~1 с */
		redraw = msgComposeEvent(ev);
		if ((u->msg.mt.key != 0) && ((now - u->msg.keyMs) >= SMS_MT_TIMEOUT_MS))
		{
			smsMtCommit(&u->msg.mt, &u->msg.pos);
			redraw = true;
		}
	}
	else
	{
		int r = msgPageEvent(ev);

		if (r < 0)
		{
			aprsModeMsgSessionClose();
			return false;
		}
		redraw = (r > 0);
	}

	if ((ev->hasEvent) && (ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		redraw = true;
	}
	if ((redraw == false) && (msgComposing(u) == false) && ((now - u->lastDrawMs) >= AM_MSG_REDRAW_MS))
	{
		redraw = true;
	}
	if (redraw)
	{
		draw();
	}
	return true;
}

#endif /* APRS_RX */
