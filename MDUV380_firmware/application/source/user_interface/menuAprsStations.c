/*
 * menuAprsStations.c -- екран «APRS станції» (R8). Сторінки:
 *   список  -- до 16 станцій, найновіша зверху: «UW5ELK-7 3.2км NE 2хв» (позивний, відстань і сектор
 *              азимуту від нашої позиції, вік останнього пакета); у шапці -- стан приймача;
 *   картка  -- позивний, тип, позиція, відстань, лічильник пакетів, вік, шлях, останній коментар/статус
 *              (за вкладкою ENTER=GREEN зі списку; вгору/вниз -- сусідня станція);
 *   діагностика -- лічильники приймача (# зі списку; 0 -- скинути): що зупиняло, скільки кадрів, nbits.
 * Керування: вгору/вниз -- рядок; GREEN -- картка; # -- діагностика; RED -- назад / вихід.
 * Перемальовування -- раз на 500 мс (вік) і на кожну подію. Дані -- лише читання aprsRxDb()/aprsRxStats().
 * Стан екрана -- у aprsRxUi() (CCM приймача): окремі змінні коштували б main RAM.
 */
#include "user_interface/menuAprsStations.h"

#if defined(APRS_RX)

#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "functions/ticks.h"
#include "user_interface/languages/aprsrx_ua.h"
#include "user_interface/languages/aprsmode_ua.h"   /* R10: підказка вбудованої сторінки */
#include "user_interface/menuAprsMode.h"              /* R11: «Відповісти» з картки */
#include <stdio.h>
#include <string.h>

#define ST_ROW(n)         (16 + ((n) * 10))
#define ST_REDRAW_MS      500U
#define ST_LIST_ROWS      9           /* рядки 1..9; рядок 0 -- стан приймача, 10 -- підказка */
#define ST_CAP(v, m)      ((unsigned long)(((v) > (m)) ? (m) : (v)))

static void printRow(int row, const char *text)
{
	displayPrintAt(0, ST_ROW(row), text, FONT_SIZE_1);
}

/* Вік: 45с / 12хв / 5г / 3д. */
static void ageStr(char *b, size_t n, uint32_t sec)
{
	if (sec < 60U)
	{
		snprintf(b, n, APRSRX_AGE_S, (unsigned long)sec);
	}
	else if (sec < 3600U)
	{
		snprintf(b, n, APRSRX_AGE_M, (unsigned long)(sec / 60U));
	}
	else if (sec < 86400U)
	{
		snprintf(b, n, APRSRX_AGE_H, (unsigned long)(sec / 3600U));
	}
	else
	{
		snprintf(b, n, APRSRX_AGE_D, (unsigned long)(sec / 86400U));
	}
}

static const char *typeStr(uint8_t type)
{
	switch (type)
	{
		case APRS_T_POSITION: return APRSRX_T_POS;
		case APRS_T_MESSAGE:  return APRSRX_T_MSG;
		case APRS_T_STATUS:   return APRSRX_T_STATUS;
		default:              return APRSRX_T_OTHER;
	}
}

static const char *whyStr(uint8_t why)
{
	switch (why)
	{
		case APRS_RX_WHY_NOT_APRS: return APRSRX_OFF_NOT_APRS;
		case APRS_RX_WHY_NOT_FM:   return APRSRX_OFF_NOT_FM;
		case APRS_RX_WHY_TX:       return APRSRX_OFF_TX;
		case APRS_RX_WHY_SCAN:     return APRSRX_OFF_SCAN;
		case APRS_RX_WHY_PROMPT:   return APRSRX_OFF_PROMPT;
		case APRS_RX_WHY_REPLAY:   return APRSRX_OFF_REPLAY;
		case APRS_RX_WHY_MENU:     return APRSRX_OFF_MENU;
		case APRS_RX_WHY_PROBE:    return APRSRX_OFF_PROBE;
		case APRS_RX_WHY_BUSY:     return APRSRX_OFF_BUSY;
		case APRS_RX_WHY_NO_WS:    return APRSRX_OFF_NOWS;
		default:                   return "";
	}
}

/* Шапка: «Слухаю 5/16» або причина, чому приймач не працює. */
static void statusLine(char *b, size_t n)
{
	const aprsRxStats_t *st = aprsRxStats();

	if (st->state == 2)
	{
		snprintf(b, n, APRSRX_STATUS_FMT, APRSRX_LISTENING, (unsigned)aprsDbCount(aprsRxDb()), (unsigned)APRS_STATIONS_MAX);
	}
	else if (st->state == 1)
	{
		snprintf(b, n, "%s %s", APRSRX_WAITING, whyStr(st->why));
	}
	else
	{
		snprintf(b, n, "%s", whyStr(st->why));
	}
}

/* Координата в мікроградусах -> «50.4501» (4 знаки, з мінусом). */
static void coordStr(char *b, size_t n, int32_t u)
{
	uint32_t a = (u < 0) ? (uint32_t)(-(int64_t)u) : (uint32_t)u;
	uint32_t t = (a + 50U) / 100U;   /* 1e-4 градуса */
	snprintf(b, n, "%s%lu.%04lu", (u < 0) ? "-" : "", (unsigned long)(t / 10000U), (unsigned long)(t % 10000U));
}

static void drawList(uint32_t now)
{
	aprsRxUi_t *ui = aprsRxUi();
	const aprsRxDb_t *db = aprsRxDb();
	int count = aprsDbCount(db);
	char buf[40];

	(void)now;
	statusLine(buf, sizeof(buf));
	printRow(0, buf);

	if (count == 0)
	{
		displayPrintCentered(ST_ROW(4), APRSRX_EMPTY, FONT_SIZE_1);
		return;
	}
	if (ui->sel >= count)
	{
		ui->sel = (uint8_t)(count - 1);
	}
	if (ui->sel < ui->scroll)
	{
		ui->scroll = ui->sel;
	}
	else if (ui->sel >= (ui->scroll + ST_LIST_ROWS))
	{
		ui->scroll = (uint8_t)(ui->sel - ST_LIST_ROWS + 1);
	}

	for (int r = 0; r < ST_LIST_ROWS; r++)
	{
		int n = ui->scroll + r;
		const aprsStation_t *s = aprsDbNth(db, n, ticksGetMillis());
		char geo[16], age[8];
		uint32_t dist;
		uint16_t brg;

		if (s == NULL)
		{
			break;
		}
		geo[0] = 0;
		if (aprsRxStationGeo(s, &dist, &brg))
		{
			aprsRxFormatGeo(geo, sizeof(geo), dist, brg);
		}
		ageStr(age, sizeof(age), aprsRxAgeSec(s));
		/* маркер(1) + позивний(9) + відстань(10) + вік(5) = 25 символів <= 26 (рядок FONT_SIZE_1) */
		snprintf(buf, sizeof(buf), "%c%-9s%-10s%5s", (n == ui->sel) ? '>' : ' ', s->call, geo, age);
		printRow(1 + r, buf);
	}
}

static void drawCard(void)
{
	aprsRxUi_t *ui = aprsRxUi();
	const aprsRxDb_t *db = aprsRxDb();
	const aprsStation_t *s = NULL;
	char buf[64], a[40], b[16];
	uint32_t now = ticksGetMillis();
	uint32_t dist;
	uint16_t brg;

	for (int i = 0; i < APRS_STATIONS_MAX; i++)
	{
		if ((db->st[i].call[0] != 0) && (strcmp(db->st[i].call, ui->cardCall) == 0))
		{
			s = &db->st[i];
			break;
		}
	}
	if (s == NULL)
	{
		displayPrintCentered(ST_ROW(4), APRSRX_EMPTY, FONT_SIZE_1);   /* станцію витіснено новішими */
		printRow(10, APRSRX_HINT_CARD);
		return;
	}

	snprintf(buf, sizeof(buf), "%s%s", s->call, (s->flags & APRS_ST_MICE) ? " " APRSRX_CARD_MICE : "");
	printRow(0, buf);
	snprintf(buf, sizeof(buf), APRSRX_CARD_TYPE, typeStr(s->type));
	printRow(1, buf);
	if (s->flags & APRS_ST_HASPOS)
	{
		char la[16], lo[16];
		coordStr(la, sizeof(la), s->latU);
		coordStr(lo, sizeof(lo), s->lonU);
		snprintf(a, sizeof(a), "%s %s", la, lo);
		snprintf(buf, sizeof(buf), APRSRX_CARD_POS, a);
	}
	else
	{
		snprintf(buf, sizeof(buf), "%s", APRSRX_CARD_NOPOS);
	}
	printRow(2, buf);
	if (aprsRxStationGeo(s, &dist, &brg))
	{
		aprsRxFormatGeo(a, sizeof(a), dist, brg);
		snprintf(buf, sizeof(buf), APRSRX_CARD_DIST, a);
	}
	else
	{
		snprintf(buf, sizeof(buf), "%s", APRSRX_CARD_NODIST);
	}
	printRow(3, buf);
	snprintf(buf, sizeof(buf), APRSRX_CARD_PKTS, (unsigned)s->count);
	printRow(4, buf);
	ageStr(b, sizeof(b), (uint32_t)(now - s->lastMs) / 1000U);
	snprintf(buf, sizeof(buf), APRSRX_CARD_LAST, b);
	printRow(5, buf);
	snprintf(buf, sizeof(buf), APRSRX_CARD_PATH, s->path);
	printRow(6, buf);
	/* останній коментар/статус/повідомлення -- до двох рядків по 26 символів */
	{
		char l1[27], l2[27];
		size_t n = strlen(s->text);

		memset(l1, 0, sizeof(l1));
		memset(l2, 0, sizeof(l2));
		memcpy(l1, s->text, (n > 26U) ? 26U : n);
		if (n > 26U)
		{
			memcpy(l2, s->text + 26, (n - 26U > 26U) ? 26U : (n - 26U));
		}
		printRow(7, l1);
		printRow(8, l2);
	}
	printRow(10, APRSRX_HINT_CARD);
}

static void drawDiag(void)
{
	const aprsRxStats_t *st = aprsRxStats();
	const aprsRxDb_t *db = aprsRxDb();
	char buf[40], nb[8];

	if (st->nbits == 0U)
	{
		snprintf(nb, sizeof(nb), "%s", APRSRX_DIAG_NOBITS);
	}
	else
	{
		snprintf(nb, sizeof(nb), "%u", (unsigned)st->nbits);
	}
	snprintf(buf, sizeof(buf), "st=%u nb=%s try=%u%s", (unsigned)st->state, nb, (unsigned)st->triesLeft, st->scaled ? " S" : "");
	printRow(0, buf);
	snprintf(buf, sizeof(buf), "start %lu fail %lu rs %lu", ST_CAP(st->starts, 9999), ST_CAP(st->startFails, 9999), ST_CAP(st->nbitsRestarts, 9999));
	printRow(1, buf);
	snprintf(buf, sizeof(buf), "frm ok %lu bad %lu", ST_CAP(st->framesOk, 99999), ST_CAP(st->framesBad, 99999));
	printRow(2, buf);
	snprintf(buf, sizeof(buf), "pkt %lu dup %lu oth %lu", ST_CAP(db->total, 99999), ST_CAP(db->dups, 9999), ST_CAP(db->other, 9999));
	printRow(3, buf);
	snprintf(buf, sizeof(buf), "blk %lu ovf %lu gate %lu", ST_CAP(st->blocks, 999999), ST_CAP(st->overflows, 9999), ST_CAP(st->gateDrops, 9999));
	printRow(4, buf);
	snprintf(buf, sizeof(buf), "fs %lu T %u hal %u", ST_CAP(st->fsHz, 99999), (unsigned)st->tMeasUs, (unsigned)st->halUs);
	printRow(5, buf);
	snprintf(buf, sizeof(buf), "tx%lu pr%lu rp%lu sc%lu", ST_CAP(st->stops[APRS_RX_WHY_TX], 999), ST_CAP(st->stops[APRS_RX_WHY_PROMPT], 999),
			ST_CAP(st->stops[APRS_RX_WHY_REPLAY], 999), ST_CAP(st->stops[APRS_RX_WHY_SCAN], 999));
	printRow(6, buf);
	snprintf(buf, sizeof(buf), "nf%lu na%lu mn%lu pb%lu", ST_CAP(st->stops[APRS_RX_WHY_NOT_FM], 999), ST_CAP(st->stops[APRS_RX_WHY_NOT_APRS], 999),
			ST_CAP(st->stops[APRS_RX_WHY_MENU], 999), ST_CAP(st->stops[APRS_RX_WHY_PROBE], 999));
	printRow(7, buf);
	snprintf(buf, sizeof(buf), "msg %lu bnr %lu sw %lu", ST_CAP(st->msgStored, 999), ST_CAP(st->banners, 9999), ST_CAP(st->det_switches, 999));
	printRow(8, buf);
	statusLine(buf, sizeof(buf));
	printRow(9, buf);
	printRow(10, APRSRX_HINT_DIAG);
}

/* R8-fix: друга діагностична сторінка -- лічильники I2S (повна розкладка: docs, розділ 12.2). */
static void drawDiag2(void)
{
	const aprsRxStats_t *st = aprsRxStats();
	char buf[40];

	statusLine(buf, sizeof(buf));
	printRow(0, buf);
	snprintf(buf, sizeof(buf), APRSRX_D2_STARTS, ST_CAP(st->starts, 99999));
	printRow(1, buf);
	snprintf(buf, sizeof(buf), APRSRX_D2_FAILS, ST_CAP(st->startFails, 99999));
	printRow(2, buf);
	snprintf(buf, sizeof(buf), APRSRX_D2_WS, ST_CAP(st->wsTimeouts, 9999));
	printRow(3, buf);
	snprintf(buf, sizeof(buf), APRSRX_D2_SYNC, ST_CAP(st->syncStops, 9999));
	printRow(4, buf);
	snprintf(buf, sizeof(buf), APRSRX_D2_ABORT, ST_CAP(st->abortTimeouts, 9999));
	printRow(5, buf);
	snprintf(buf, sizeof(buf), APRSRX_D2_TICKTX, ST_CAP(st->stops[APRS_RX_WHY_TX], 99999));
	printRow(6, buf);
	printRow(10, APRSRX_HINT_DIAG);
}

static void draw(void)
{
	aprsRxUi_t *ui = aprsRxUi();
	uint32_t now = ticksGetMillis();

	ui->lastDrawMs = now;
	displayClearBuf();
	menuDisplayTitle((ui->view == APRS_RX_VIEW_DIAG) ? APRSRX_DIAG_TITLE : ((ui->view == APRS_RX_VIEW_DIAG2) ? APRSRX_DIAG2_TITLE : APRSRX_TITLE));
	switch (ui->view)
	{
		case APRS_RX_VIEW_CARD:
			drawCard();
			break;
		case APRS_RX_VIEW_DIAG:
			drawDiag();
			break;
		case APRS_RX_VIEW_DIAG2:
			drawDiag2();
			break;
		default:
			drawList(now);
			printRow(10, APRSRX_HINT_LIST);
			break;
	}
	displayRender();
}

void menuAprsStationsEnter(void)
{
	aprsRxUi_t *ui = aprsRxUi();

	ui->on = 1;
	ui->view = APRS_RX_VIEW_LIST;
	ui->sel = 0;
	ui->scroll = 0;
	ui->cardCall[0] = 0;
	draw();
}

void menuAprsStationsClose(void)
{
	aprsRxUi()->on = 0;
}

/* Сусідня станція на картці: dir = +1 -- старіша (нижче у списку), -1 -- новіша. */
static void cardGo(int dir)
{
	aprsRxUi_t *ui = aprsRxUi();
	int count = aprsDbCount(aprsRxDb());
	int next = (int)ui->sel + dir;

	if ((next < 0) || (next >= count))
	{
		return;
	}
	const aprsStation_t *s = aprsDbNth(aprsRxDb(), next, ticksGetMillis());
	if (s != NULL)
	{
		ui->sel = (uint8_t)next;
		snprintf(ui->cardCall, sizeof(ui->cardCall), "%s", s->call);
	}
}

bool menuAprsStationsTick(uiEvent_t *ev)
{
	aprsRxUi_t *ui = aprsRxUi();
	bool redraw = false;

	if (ev->hasEvent)
	{
		if (ev->events & KEY_EVENT)
		{
			if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				if (ui->view == APRS_RX_VIEW_LIST)
				{
					ui->on = 0;
					return false;
				}
				ui->view = APRS_RX_VIEW_LIST;
				redraw = true;
			}
			else if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN))
			{
				int dir = KEYCHECK_PRESS(ev->keys, KEY_DOWN) ? 1 : -1;
				if (ui->view == APRS_RX_VIEW_CARD)
				{
					cardGo(dir);
				}
				else if (ui->view == APRS_RX_VIEW_LIST)
				{
					int count = aprsDbCount(aprsRxDb());
					int n = (int)ui->sel + dir;
					if (count > 0)
					{
						ui->sel = (uint8_t)((n < 0) ? (count - 1) : ((n >= count) ? 0 : n));   /* по колу */
					}
				}
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (ui->view == APRS_RX_VIEW_LIST))
			{
				const aprsStation_t *s = aprsDbNth(aprsRxDb(), ui->sel, ticksGetMillis());
				if (s != NULL)
				{
					snprintf(ui->cardCall, sizeof(ui->cardCall), "%s", s->call);
					ui->view = APRS_RX_VIEW_CARD;
				}
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (ui->view == APRS_RX_VIEW_CARD))
			{
				/* R11: «Відповісти» -- набір повідомлення цій станції; екран «APRS станції» закриється, відкриється «Режим APRS» */
				if (menuAprsModeReplyTo(ui->cardCall))
				{
					return true;
				}
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH) && (ui->view == APRS_RX_VIEW_LIST))
			{
				ui->view = APRS_RX_VIEW_DIAG;
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH) && (ui->view == APRS_RX_VIEW_DIAG))
			{
				ui->view = APRS_RX_VIEW_DIAG2;   /* R8-fix: лічильники I2S */
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH) && (ui->view == APRS_RX_VIEW_DIAG2))
			{
				ui->view = APRS_RX_VIEW_DIAG;
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_0) && ((ui->view == APRS_RX_VIEW_DIAG) || (ui->view == APRS_RX_VIEW_DIAG2)))
			{
				aprsRxClear();   /* лічильники і список -- до нуля */
				ui->sel = 0;
				ui->scroll = 0;
				redraw = true;
			}
		}

		if ((ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
		{
			redraw = true;
		}
	}

	if (redraw || ((ticksGetMillis() - ui->lastDrawMs) >= ST_REDRAW_MS))
	{
		draw();
	}
	return true;
}

/* ---- R10: сторінка «Станції» «Режиму APRS» -- той самий список і картка, але без власного заголовка/діагностики ---- */

void menuAprsStationsDrawEmbedded(void)
{
	aprsRxUi_t *ui = aprsRxUi();

	if ((ui->view == APRS_RX_VIEW_DIAG) || (ui->view == APRS_RX_VIEW_DIAG2))
	{
		ui->view = APRS_RX_VIEW_LIST;   /* діагностика (обидві сторінки) лишається в екрані «APRS станції» */
	}
	if (ui->view == APRS_RX_VIEW_CARD)
	{
		drawCard();
	}
	else
	{
		drawList(ticksGetMillis());
		printRow(10, APRSM_ST_HINT);
	}
}

int menuAprsStationsKeyEmbedded(uiEvent_t *ev)
{
	aprsRxUi_t *ui = aprsRxUi();

	if ((ev->hasEvent == false) || ((ev->events & KEY_EVENT) == 0))
	{
		return 0;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		if (ui->view != APRS_RX_VIEW_CARD)
		{
			return -1;   // зі списку -- назад на «Монітор»
		}
		ui->view = APRS_RX_VIEW_LIST;
		return 1;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		int dir = KEYCHECK_PRESS(ev->keys, KEY_DOWN) ? 1 : -1;

		if (ui->view == APRS_RX_VIEW_CARD)
		{
			cardGo(dir);
		}
		else
		{
			int count = aprsDbCount(aprsRxDb());
			int n = (int)ui->sel + dir;

			if (count > 0)
			{
				ui->sel = (uint8_t)((n < 0) ? (count - 1) : ((n >= count) ? 0 : n));   // по колу
			}
		}
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (ui->view == APRS_RX_VIEW_CARD))
	{
		(void)menuAprsModeReplyTo(ui->cardCall);   /* R11: «Відповісти» -- режим уже активний: відкриває сторінку «Повідомлення» з набором */
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (ui->view != APRS_RX_VIEW_CARD))
	{
		const aprsStation_t *s = aprsDbNth(aprsRxDb(), ui->sel, ticksGetMillis());

		if (s != NULL)
		{
			snprintf(ui->cardCall, sizeof(ui->cardCall), "%s", s->call);
			ui->view = APRS_RX_VIEW_CARD;
		}
		return 1;
	}
	return 0;
}

const char *menuAprsStationsTypeStr(uint8_t type)
{
	return typeStr(type);
}

void menuAprsStationsAgeStr(char *b, size_t n, uint32_t sec)
{
	ageStr(b, n, sec);
}

#endif /* APRS_RX */
