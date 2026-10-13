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
#include "functions/aprs_mode.h"                     /* R11-fix2: лічильники черги повідомлень/ACK (aprsModeMsgBox()); R16: aprsModeHist() */
#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
#include "functions/sms_format.h"                    /* R16: SMS_TIME_HM */
#include "user_interface/uiSms.h"                     /* R16: uiSmsTimeStr() -- час прийому в журналі (як у вікні маяка; є лише в збірці з DMR-даними) */
#endif
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

/* R16: «Пакети» -- журнал останніх APRS_JRN_SLOTS прийнятих кадрів (aprsModeHist()). Список: «> ГГ:ХХ ПОЗИВНИЙ D», найновіший зверху (D -- DTI, перший
 * байт інфо-поля: '!' '=' позиція, '`' Mic-E, ':' повідомлення, '}' кадр через i-gate...). GREEN -- повний текст кадру (TNC-2, до 127 символів) із
 * переносом по СИМВОЛАХ (без пошуку пробілів: це сирі дані), 26 символів у рядку FONT_SIZE_1; RED -- назад до списку. */
#define ST_PKT_COLS   26
#define ST_PKT_ROWS   9
#define PKT_SLOT(ui)  ((int)((ui)->scroll >> 4))      /* PACKET: слот журналу */
#define PKT_TOP(ui)   ((unsigned)((ui)->scroll & 0x0FU))   /* PACKET: перший видимий рядок тексту */

static void drawPktList(void)
{
	aprsRxUi_t *ui = aprsRxUi();
	const aprsHist_t *h = aprsModeHist();
	char buf[40];

	if (h->jrnCount == 0U)
	{
		displayPrintCentered(ST_ROW(4), APRSRX_PKT_EMPTY, FONT_SIZE_1);
		printRow(10, APRSRX_PKTL_HINT);
		return;
	}
	if (ui->scroll >= h->jrnCount)
	{
		ui->scroll = (uint8_t)(h->jrnCount - 1U);
	}
	{
		char st[40];

		statusLine(st, sizeof(st));
		snprintf(buf, sizeof(buf), "%-22.22s%u/%u", st, (unsigned)ui->scroll + 1U, (unsigned)h->jrnCount);   /* R17: номер виділеного запису / скільки їх */
		printRow(0, buf);
	}
	for (int r = 0; r < (int)h->jrnCount; r++)
	{
		const aprsJrnEntry_t *e = aprsJrnNth(h, r);
		char call[APRS_CALL_LEN], tm[12], dti;

		if (e == NULL)
		{
			break;
		}
		aprsJrnSummary(e, call, &dti);
#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
		if (uiSmsTimeStr(e->rxSecs, SMS_TIME_HM, tm, (int)sizeof(tm)) <= 0)
#endif
		{
			snprintf(tm, sizeof(tm), "%s", APRSRX_PKTL_NOTIME);
		}
		snprintf(buf, sizeof(buf), APRSRX_PKTL_ROW, (r == (int)ui->scroll) ? '>' : ' ', tm, call, dti);
		{
			/* R17 Г6: RSSI кадру праворуч (дБм, без одиниці: 4 символи); невідомий -- порожньо */
			int8_t rs = aprsJrnRssiAtSlot(h, aprsJrnSlotOf(h, r));
			size_t l = strlen(buf);

			if (rs != (int8_t)APRS_RSSI_NONE)
			{
				snprintf(buf + l, sizeof(buf) - l, " %4d", (int)rs);
			}
		}
		printRow(1 + r, buf);
	}
	printRow(10, APRSRX_PKTL_HINT);
}

static void drawPacket(void)
{
	aprsRxUi_t *ui = aprsRxUi();
	const aprsJrnEntry_t *e = aprsJrnAtSlot(aprsModeHist(), PKT_SLOT(ui));
	const char *raw = (e != NULL) ? e->text : "";
	size_t len = strlen(raw);
	unsigned lines = (unsigned)((len + (ST_PKT_COLS - 1U)) / ST_PKT_COLS);
	unsigned maxTop = (lines > ST_PKT_ROWS) ? (lines - ST_PKT_ROWS) : 0U;
	unsigned top = PKT_TOP(ui);
	char buf[ST_PKT_COLS + 14];

	if (len == 0U)
	{
		displayPrintCentered(ST_ROW(4), APRSRX_PKT_EMPTY, FONT_SIZE_1);
		printRow(10, APRSRX_PKT_HINT);
		return;
	}
	if (top > maxTop)
	{
		top = maxTop;
		ui->scroll = (uint8_t)((ui->scroll & 0xF0U) | top);
	}
	{
		char ln[24];

		int8_t rs = aprsJrnRssiAtSlot(aprsModeHist(), PKT_SLOT(ui));

		if (rs != (int8_t)APRS_RSSI_NONE)
		{
			snprintf(ln, sizeof(ln), APRSRX_PKT_LEN_RS, (unsigned)len, (int)rs);
		}
		else
		{
			snprintf(ln, sizeof(ln), APRSRX_PKT_LEN, (unsigned)len);
		}
		snprintf(buf, sizeof(buf), "%-22.22s%u/%u", ln, (unsigned)aprsJrnNOfSlot(aprsModeHist(), PKT_SLOT(ui)) + 1U, (unsigned)aprsModeHist()->jrnCount);   /* R17: який запис журналу */
		printRow(0, buf);
	}
	for (unsigned r = 0; r < ST_PKT_ROWS; r++)
	{
		size_t off = (size_t)(top + r) * ST_PKT_COLS;
		size_t n;

		if (off >= len)
		{
			break;
		}
		n = ((len - off) > ST_PKT_COLS) ? ST_PKT_COLS : (len - off);
		memcpy(buf, raw + off, n);
		buf[n] = 0;
		printRow(1 + (int)r, buf);
	}
	if (top > 0U)
	{
		displayFillTriangle(DISPLAY_SIZE_X - 21, 17, DISPLAY_SIZE_X - 25, 24, DISPLAY_SIZE_X - 17, 24, true);        /* є вище */
	}
	if (top < maxTop)
	{
		displayFillTriangle(DISPLAY_SIZE_X - 13, 17, DISPLAY_SIZE_X - 5, 17, DISPLAY_SIZE_X - 9, 24, true);          /* є нижче */
	}
	printRow(10, APRSRX_PKT_HINT);
}

/* Відкрити повний кадр n-го за новизною запису журналу. */
static void pktOpen(aprsRxUi_t *ui, int n)
{
	int slot = aprsJrnSlotOf(aprsModeHist(), n);

	if (slot >= 0)
	{
		ui->view = APRS_RX_VIEW_PACKET;
		ui->scroll = (uint8_t)(slot << 4);
	}
}

/* Назад зі повного кадру до списку журналу з тим самим виділеним записом. */
static void pktBackToList(aprsRxUi_t *ui)
{
	ui->scroll = (uint8_t)aprsJrnNOfSlot(aprsModeHist(), PKT_SLOT(ui));
	ui->view = APRS_RX_VIEW_PKTLIST;
}

/* Вгору/вниз у списку журналу -- по колу. */
static void pktListMove(aprsRxUi_t *ui, int dir)
{
	int cnt = (int)aprsModeHist()->jrnCount;
	int n = (int)ui->scroll + dir;

	if (cnt > 0)
	{
		ui->scroll = (uint8_t)((n < 0) ? (cnt - 1) : ((n >= cnt) ? 0 : n));
	}
}

/* Прокрутка тексту повного кадру (верхню межу виправить drawPacket()). */
static void pktTextMove(aprsRxUi_t *ui, int dir)
{
	unsigned top = PKT_TOP(ui);

	if (((dir > 0) && (top < 15U)) || ((dir < 0) && (top > 0U)))
	{
		ui->scroll = (uint8_t)((ui->scroll & 0xF0U) | (unsigned)((int)top + dir));
	}
}

/* R17 (Г3): напрямок прокрутки. На MDUV380 ручка в меню -- це KEY_LEFT/KEY_RIGHT (menuSystemPreProcessEvent), кнопки UP/DOWN -- KEY_UP/KEY_DOWN.
 * Раніше екран слухав лише UP/DOWN: ручка в «Пакети» не робила нічого. Тепер DOWN і RIGHT -- далі (+1), UP і LEFT -- назад (-1). */
static int navDir(const uiEvent_t *ev)
{
	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN) || KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
	{
		return 1;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_LEFT))
	{
		return -1;
	}
	return 0;
}

/* Скільки рядків займає повний кадр відкритого запису журналу. */
static unsigned pktLines(const aprsRxUi_t *ui)
{
	const aprsJrnEntry_t *e = aprsJrnAtSlot(aprsModeHist(), PKT_SLOT(ui));

	return (e == NULL) ? 0U : (unsigned)((strlen(e->text) + (ST_PKT_COLS - 1U)) / ST_PKT_COLS);
}

/* Вгору/вниз у повному кадрі: довгий текст (більше ST_PKT_ROWS рядків) гортається рядками; кадр, що весь на екрані, -- нічого не гортає,
 * тож стрілки перемикають на сусідній запис журналу (вниз -- старіший). Журнал порожній -- нічого. */
static void pktFrameMove(aprsRxUi_t *ui, int dir)
{
	if (pktLines(ui) > ST_PKT_ROWS)
	{
		pktTextMove(ui, dir);
	}
	else
	{
		int cnt = (int)aprsModeHist()->jrnCount;
		int n = aprsJrnNOfSlot(aprsModeHist(), PKT_SLOT(ui)) + dir;

		if (cnt > 0)
		{
			pktOpen(ui, (n < 0) ? (cnt - 1) : ((n >= cnt) ? 0 : n));
		}
	}
}

/* R16: маяк саме цієї станції (дані маяка кожної станції -- в aprsModeHist(), індекс як у списку станцій) */
static bool cardBeaconAvail(const aprsRxUi_t *ui)
{
	return aprsRxBeaconAvail(ui->cardCall);
}

/* R16: '*' на картці -- вікно маяка ЦІЄЇ станції; позиційних пакетів від неї не було -- сповіщення. */
static void cardBeaconOpen(const aprsRxUi_t *ui)
{
	if (aprsRxWindowShowStation(ui->cardCall) == false)
	{
		uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, APRSRX_BCN_NONE_ST, true);
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

	snprintf(buf, sizeof(buf), "%s%s%s", s->call, (s->flags & APRS_ST_MICE) ? " " APRSRX_CARD_MICE : "", (s->flags & APRS_ST_TP) ? " " APRSRX_CARD_TP : "");
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
	{
		/* R17 Г6: RSSI останнього позиційного пакета станції (запис маяка), якщо відомий */
		const aprsBcnRec_t *br = aprsHistBeaconOf(aprsModeHist(), db, s);

		if ((br != NULL) && (br->rssiDbm != (int8_t)APRS_RSSI_NONE))
		{
			snprintf(buf, sizeof(buf), APRSRX_CARD_LAST_RS, b, (int)br->rssiDbm);
		}
		else
		{
			snprintf(buf, sizeof(buf), APRSRX_CARD_LAST, b);
		}
	}
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
	printRow(9, cardBeaconAvail(ui) ? APRSRX_HINT_CARD2B : APRSRX_HINT_CARD2);   /* R15 */
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
	/* R11-fix: скільки кадрів прийшло через i-gate (third-party "}") і було розгорнуто до справжнього відправника */
	snprintf(buf, sizeof(buf), "3P unwrapped %u", (unsigned)aprsRxDb()->tpUnwrapped);
	printRow(7, buf);
	/* R11-fix2: повідомлення/ACK. rx -- до нас (УСІ копії), ak a>b -- ACK сформовано>передано, L -- ACK не пішов (lost),
	 * q -- довжина черги. Нижче -- останній ПЕРЕДАНИЙ ACK як інфо-поле: порівняти з "raw packets" на aprs.fi. */
	{
		const aprsMsgBox_t *mb = aprsModeMsgBox();

		snprintf(buf, sizeof(buf), "rx%lu ak%lu>%lu L%lu q%u", ST_CAP(mb->stats.rx, 999), ST_CAP(mb->stats.ackFormed, 999),
				ST_CAP(mb->stats.ackSent, 999), ST_CAP(mb->stats.ackLost, 99), aprsMsgQueueLen(mb));
		printRow(8, buf);
		snprintf(buf, sizeof(buf), ">%s", (mb->lastAckText[0] != 0) ? mb->lastAckText : "-");
		printRow(9, buf);
	}
	printRow(10, APRSRX_HINT_DIAG);
}

static void draw(void)
{
	aprsRxUi_t *ui = aprsRxUi();
	uint32_t now = ticksGetMillis();

	ui->lastDrawMs = now;
	displayClearBuf();
	menuDisplayTitle((ui->view == APRS_RX_VIEW_DIAG) ? APRSRX_DIAG_TITLE : ((ui->view == APRS_RX_VIEW_DIAG2) ? APRSRX_DIAG2_TITLE :
			(((ui->view == APRS_RX_VIEW_PACKET) || (ui->view == APRS_RX_VIEW_PKTLIST)) ? APRSRX_PKT_TITLE : APRSRX_TITLE)));
	switch (ui->view)
	{
		case APRS_RX_VIEW_PKTLIST:
			drawPktList();
			break;
		case APRS_RX_VIEW_PACKET:
			drawPacket();
			break;
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

/* R16: пункт «Пакети» меню «APRS»: одразу список журналу; cardCall порожній -- RED виходить з екрана (з картки RED повертає на картку). */
void menuAprsPacketEnter(void)
{
	aprsRxUi_t *ui = aprsRxUi();

	ui->on = 1;
	ui->view = APRS_RX_VIEW_PKTLIST;
	ui->sel = 0;
	ui->scroll = 0;
	ui->cardCall[0] = 0;
	draw();
}

/* R15: пункт «Останній маяк»: вікно найсвіжішого маяка ще раз за збереженими даними (дані й час прийому не змінюються); немає -- сповіщення. */
void menuAprsBeaconShow(void)
{
	if (aprsRxBeaconAvail(NULL) == false)
	{
		uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, APRSRX_BCN_NONE, true);
		return;
	}
	aprsRxWindowShowAgain();
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
				if (ui->view == APRS_RX_VIEW_PACKET)
				{
					pktBackToList(ui);   /* R16: повний кадр -- назад до списку журналу */
					redraw = true;
				}
				else if (ui->view == APRS_RX_VIEW_PKTLIST)
				{
					ui->scroll = 0;
					if (ui->cardCall[0] == 0)
					{
						ui->on = 0;   /* відкрито з меню «APRS» (пункт «Пакети») -- RED виходить з екрана */
						return false;
					}
					ui->view = APRS_RX_VIEW_CARD;   /* відкрито з картки -- назад на картку */
					redraw = true;
				}
				else
				{
					ui->view = APRS_RX_VIEW_LIST;
					redraw = true;
				}
			}
			else if (navDir(ev) != 0)
			{
				int dir = navDir(ev);
				if (ui->view == APRS_RX_VIEW_PACKET)
				{
					pktFrameMove(ui, dir);
				}
				else if (ui->view == APRS_RX_VIEW_PKTLIST)
				{
					pktListMove(ui, dir);
				}
				else if (ui->view == APRS_RX_VIEW_CARD)
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
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (ui->view == APRS_RX_VIEW_PKTLIST))
			{
				pktOpen(ui, (int)ui->scroll);   /* R16: повний кадр виділеного запису журналу */
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
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH) && (ui->view == APRS_RX_VIEW_CARD))
			{
				ui->view = APRS_RX_VIEW_PKTLIST;   /* R16: «Пакети» з картки */
				ui->scroll = 0;
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_STAR) && (ui->view == APRS_RX_VIEW_CARD))
			{
				cardBeaconOpen(ui);   /* R16: вікно маяка САМЕ цієї станції */
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
	if (ui->view == APRS_RX_VIEW_PKTLIST)
	{
		drawPktList();
	}
	else if (ui->view == APRS_RX_VIEW_PACKET)
	{
		drawPacket();
	}
	else if (ui->view == APRS_RX_VIEW_CARD)
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
		if (ui->view == APRS_RX_VIEW_PACKET)
		{
			pktBackToList(ui);   /* R16: повний кадр -> список журналу */
			return 1;
		}
		if (ui->view == APRS_RX_VIEW_PKTLIST)
		{
			ui->scroll = 0;
			ui->view = APRS_RX_VIEW_CARD;   /* R15: журнал відкривають лише з картки -- RED назад на картку */
			return 1;
		}
		if (ui->view != APRS_RX_VIEW_CARD)
		{
			return -1;   // зі списку -- назад на «Монітор»
		}
		ui->view = APRS_RX_VIEW_LIST;
		return 1;
	}
	if (navDir(ev) != 0)
	{
		int dir = navDir(ev);

		if (ui->view == APRS_RX_VIEW_PACKET)
		{
			pktFrameMove(ui, dir);
		}
		else if (ui->view == APRS_RX_VIEW_PKTLIST)
		{
			pktListMove(ui, dir);
		}
		else if (ui->view == APRS_RX_VIEW_CARD)
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
	if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH) && (ui->view == APRS_RX_VIEW_CARD))
	{
		ui->view = APRS_RX_VIEW_PKTLIST;   /* R16 */
		ui->scroll = 0;
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_STAR) && (ui->view == APRS_RX_VIEW_CARD))
	{
		cardBeaconOpen(ui);   /* R16: вікно маяка САМЕ цієї станції */
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (ui->view == APRS_RX_VIEW_PKTLIST))
	{
		pktOpen(ui, (int)ui->scroll);
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (ui->view == APRS_RX_VIEW_CARD))
	{
		(void)menuAprsModeReplyTo(ui->cardCall);   /* R11: «Відповісти» -- режим уже активний: відкриває сторінку «Повідомлення» з набором */
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (ui->view != APRS_RX_VIEW_CARD) && (ui->view != APRS_RX_VIEW_PACKET) && (ui->view != APRS_RX_VIEW_PKTLIST))
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
