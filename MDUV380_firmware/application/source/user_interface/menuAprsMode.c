/*
 * menuAprsMode.c -- екран «Режиму APRS» (R10). Сторінки (валкодер / ←→ / ↑↓ -- між ними, де це не заважає):
 *   1 «Монітор»      -- частота, стан, сигнал, кадри ок/пом, біт (nbits), останній пакет, маяки; GREEN -- маяк;
 *   2 «Станції»      -- список R8 (16 станцій) і картка станції (спільний код з menuAprsStations.c);
 *   3 «Налаштування» -- частота, позивний, SSID, шлях 1/2, символ, коментар, позиція, неточність, інтервал
 *                       маяка, шумодав, «Скинути»; значення міняються ←→ (перелічувані) або в редакторі (GREEN).
 * Місце під «Повідомлення» (R11) зарезервовано в нумерації сторінок (aprs_mode.h), у R10 його нема.
 * Стан екрана -- у aprsModeUi() (позичений буфер режиму): окремі змінні коштували б main RAM.
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
#include <stdio.h>
#include <string.h>

#define AM_ROW(n)           (16 + ((n) * 10))
#define AM_MON_REDRAW_MS    250U
#define AM_ST_REDRAW_MS     500U
#define AM_VISIBLE          10             /* рядки налаштувань 0..9; 10 -- підказка */
#define AM_CAP(v, m)        ((unsigned long)(((v) > (m)) ? (m) : (v)))
#define AM_FREQ_STEP        1250UL         /* 12,5 кГц в одиницях 10 Гц */

/* ---- допоміжне ----------------------------------------------------------------------------------------------- */

static void printRow(int row, const char *text)
{
	displayPrintAt(0, AM_ROW(row), text, FONT_SIZE_1);
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
		case APRSM_F_ICON_TABLE: return APRSM_L_ICON_TABLE;
		case APRSM_F_ICON_CODE:  return APRSM_L_ICON_CODE;
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
	return ((f == APRSM_F_FREQ) || (f == APRSM_F_CALL) || (f == APRSM_F_PATH1) || (f == APRSM_F_PATH2) ||
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
		snprintf(b, n, APRSM_V_PATH_FMT, name, (unsigned)ssid);
	}
}

static void symbolStr(char *b, size_t n, const aprsModeEff_t *e)
{
	const char *name = aprsModeSymbolName(e->iconTable, e->iconIndex);
	char c = (char)('!' + e->iconIndex);

	if (name != NULL)
	{
		snprintf(b, n, "%c %s", c, name);
	}
	else
	{
		snprintf(b, n, "%c (%u)", c, (unsigned)e->iconIndex);
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
		case APRSM_F_ICON_TABLE:
			snprintf(b, n, "%s", (e->iconTable == 0U) ? APRSM_V_TBL_PRI : APRSM_V_TBL_SEC);
			break;
		case APRSM_F_ICON_CODE:
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

/* ---- сторінка «Монітор» ------------------------------------------------------------------------------------- */

static void drawMonitor(void)
{
	const aprsModeEff_t *e = aprsModeEff();
	const aprsRxStats_t *st = aprsRxStats();
	const aprsModeLast_t *last = aprsModeLast();
	uint32_t now = ticksGetMillis();
	char buf[48], f[16], t[16], g[16], a[8];
	const char *state;
	uint32_t nextSec, beacons;
	aprsModeBcnState_t bs = aprsModeBeaconState();

	aprsModeFormatFreq(f, sizeof(f), e->freq);
	snprintf(buf, sizeof(buf), APRSM_M_FREQ, f);
	printRow(0, buf);

	/* Стан: передача > чекання вільної частоти > результат маяка/помилка > прийом. */
	if (aprsModeIsTransmitting())
	{
		state = APRSM_M_ST_TX;
	}
	else
	{
		switch (bs)
		{
			case APRS_MODE_BCN_BUSY_CH:  state = APRSM_M_ST_WAIT; break;
			case APRS_MODE_BCN_SENT:     state = APRSM_M_ST_SENT; break;
			case APRS_MODE_BCN_NOCALL:   state = APRSM_ERR_NOCALL; break;
			case APRS_MODE_BCN_NOPOS:    state = APRSM_ERR_NOPOS; break;
			case APRS_MODE_BCN_INHIBIT:  state = APRSM_ERR_INHIBIT; break;
			case APRS_MODE_BCN_BAND:     state = APRSM_ERR_BAND; break;
			case APRS_MODE_BCN_FAILED:   state = APRSM_ERR_FAILED; break;
			case APRS_MODE_BCN_TOOBIG:   state = APRSM_ERR_TOOBIG; break;
			default:                     state = (st->state == 2U) ? APRSM_M_ST_LISTEN : APRSM_M_ST_START; break;
		}
	}
	snprintf(buf, sizeof(buf), APRSM_M_STATE, state);
	printRow(1, buf);

	snprintf(buf, sizeof(buf), APRSM_M_RSSI, trxGetRSSIdBm(RADIO_DEVICE_PRIMARY), aprsRxBusy(600U) ? '*' : ' ');
	printRow(2, buf);

	snprintf(buf, sizeof(buf), APRSM_M_FRAMES, AM_CAP(st->framesOk, 99999UL), AM_CAP(st->framesBad, 99999UL));
	printRow(3, buf);

	if (st->nbits == 0U)
	{
		snprintf(t, sizeof(t), "%s", APRSM_V_EMPTY);
	}
	else
	{
		snprintf(t, sizeof(t), "%u", (unsigned)st->nbits);
	}
	snprintf(buf, sizeof(buf), APRSM_M_FORMAT, t, (unsigned)aprsDbCount(aprsRxDb()), (unsigned)APRS_STATIONS_MAX);
	printRow(4, buf);

	if (last->valid)
	{
		snprintf(buf, sizeof(buf), APRSM_M_LAST, last->src, last->dst);
		printRow(5, buf);
		g[0] = 0;
		if (last->hasGeo)
		{
			aprsRxFormatGeo(g, sizeof(g), last->distM, last->bearing);
		}
		menuAprsStationsAgeStr(a, sizeof(a), (uint32_t)(now - last->ms) / 1000U);
		snprintf(buf, sizeof(buf), "%s %s %s", menuAprsStationsTypeStr(last->type), g, a);
		printRow(6, buf);
	}
	else
	{
		printRow(5, APRSM_M_NOPKT);
	}

	beacons = aprsModeBeaconCount();
	if (beacons == 0U)
	{
		printRow(7, APRSM_M_BEACONS0);
	}
	else
	{
		menuAprsStationsAgeStr(a, sizeof(a), aprsModeLastBeaconAgeSec());
		snprintf(buf, sizeof(buf), APRSM_M_BEACONS, AM_CAP(beacons, 9999UL), a);
		printRow(7, buf);
	}

	nextSec = aprsModeNextBeaconSec();
	if (nextSec != 0xFFFFFFFFUL)
	{
		snprintf(buf, sizeof(buf), APRSM_M_NEXT, (unsigned)(nextSec / 60U), (unsigned)(nextSec % 60U));
		printRow(8, buf);
	}
	else
	{
		printRow(8, APRSM_M_MANUAL);
	}

	printRow(9, APRSM_M_NORX);
	printRow(10, APRSM_M_HINT);
}

/* ---- сторінка «Налаштування» ------------------------------------------------------------------------------- */

static void drawSettings(void)
{
	aprsModeUi_t *u = aprsModeUi();
	char buf[48], val[32];

	if (u->sel < u->scroll)
	{
		u->scroll = u->sel;
	}
	else if (u->sel >= (u->scroll + AM_VISIBLE))
	{
		u->scroll = (uint8_t)(u->sel - AM_VISIBLE + 1);
	}
	for (int r = 0; r < AM_VISIBLE; r++)
	{
		int f = u->scroll + r;

		if (f >= APRSM_F_COUNT)
		{
			break;
		}
		fieldValue(f, val, sizeof(val));
		/* маркер(1) + мітка(9) + пробіл(1) + значення(<=15) = 26 символів */
		snprintf(buf, sizeof(buf), "%c%-9s %.15s", (f == u->sel) ? '>' : ' ', fieldLabel(f), val);
		printRow(r, buf);
	}
	printRow(10, APRSM_S_HINT);
}

/* ---- редактор поля ------------------------------------------------------------------------------------------- */

static void editOpen(int field)
{
	aprsModeUi_t *u = aprsModeUi();
	aprsModeEdit_t *ed = &u->edit;
	const aprsModeEff_t *e = aprsModeEff();

	memset(ed, 0, sizeof(*ed));
	ed->active = 1U;
	ed->field = (uint8_t)field;
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
				snprintf(ed->buf, sizeof(ed->buf), "%s-%u", e->path[p], (unsigned)e->pathSsid[p]);
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
			if ((aprsModeParseFreq(txt, &f) == false) || (aprsModeFreqValid(f) == false) || aprsModeIsTransmitting())
			{
				return 1;
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

/* ---- сторінки: події ---------------------------------------------------------------------------------------- */

static void gotoPage(int dir)
{
	aprsModeUi_t *u = aprsModeUi();
	int p = (int)u->page + dir;

	if (p < 0)
	{
		p = APRS_MODE_PAGES - 1;
	}
	else if (p >= APRS_MODE_PAGES)
	{
		p = 0;
	}
	u->page = (uint8_t)p;
	u->resetArmed = 0U;
	if (u->page == APRS_MODE_PAGE_STATIONS)
	{
		aprsRxUi()->view = APRS_RX_VIEW_LIST;
	}
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
static void settingsStep(int dir)
{
	aprsModeUi_t *u = aprsModeUi();
	aprsModeCfg_t *c = aprsModeCfg();
	const aprsModeEff_t *e = aprsModeEff();
	uint16_t bit = 0;

	if (aprsModeIsTransmitting())
	{
		return;   /* посеред маяка нічого не міняємо */
	}
	switch (u->sel)
	{
		case APRSM_F_FREQ:
		{
			uint32_t f = (dir > 0) ? (e->freq + AM_FREQ_STEP) : (e->freq - AM_FREQ_STEP);

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
		case APRSM_F_ICON_TABLE:
			c->iconTable = (e->iconTable == 0U) ? 1U : 0U;
			c->iconIndex = e->iconIndex;
			bit = APRSM_OV_ICON;
			break;
		case APRSM_F_ICON_CODE:
			c->iconTable = e->iconTable;
			c->iconIndex = (uint8_t)wrapStep(e->iconIndex, dir, APRSM_ICON_MAX);
			bit = APRSM_OV_ICON;
			break;
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

/* GREEN у налаштуваннях. */
static void settingsGreen(void)
{
	aprsModeUi_t *u = aprsModeUi();

	if (u->sel == APRSM_F_RESET)
	{
		if (u->resetArmed)
		{
			u->resetArmed = 0U;
			if (aprsModeIsTransmitting() == false)
			{
				aprsModeCfgReset();
			}
		}
		else
		{
			u->resetArmed = 1U;
		}
		return;
	}
	if (aprsModeIsTransmitting())
	{
		return;
	}
	if (u->sel == APRSM_F_ICON_CODE)
	{
		/* швидкий перебір: наступний з названих символів (авто, людина, дім...) */
		aprsModeCfg_t *c = aprsModeCfg();
		const aprsModeEff_t *e = aprsModeEff();
		uint8_t t = e->iconTable, i = e->iconIndex;

		aprsModeSymbolNextNamed(&t, &i);
		c->iconTable = t;
		c->iconIndex = i;
		c->ov |= APRSM_OV_ICON;
		aprsModeCfgChanged(APRSM_OV_ICON);
		return;
	}
	if (fieldHasEditor(u->sel))
	{
		editOpen(u->sel);
	}
}

/* Подія сторінки (поза редактором). Повертає: -1 -- вийти з режиму, 0 -- нічого, 1 -- перемалювати. */
static int pageEvent(uiEvent_t *ev)
{
	aprsModeUi_t *u = aprsModeUi();

	if ((ev->hasEvent == false) || ((ev->events & KEY_EVENT) == 0))
	{
		return 0;
	}

	switch (u->page)
	{
		case APRS_MODE_PAGE_MONITOR:
			if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				if (aprsModeIsTransmitting())
				{
					return 0;   /* посеред маяка не виходимо */
				}
				return -1;
			}
			if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
			{
				aprsModeRequestBeacon();
				return 1;
			}
			if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_DOWN))
			{
				gotoPage(+1);
				return 1;
			}
			if (KEYCHECK_PRESS(ev->keys, KEY_LEFT) || KEYCHECK_PRESS(ev->keys, KEY_UP))
			{
				gotoPage(-1);
				return 1;
			}
			return 0;

		case APRS_MODE_PAGE_STATIONS:
			if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
			{
				gotoPage(+1);
				return 1;
			}
			if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))
			{
				gotoPage(-1);
				return 1;
			}
			{
				int r = menuAprsStationsKeyEmbedded(ev);

				if (r < 0)
				{
					u->page = APRS_MODE_PAGE_MONITOR;   /* RED зі списку -- на «Монітор» */
					return 1;
				}
				return r;
			}

		default:   /* APRS_MODE_PAGE_SETTINGS */
			if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				u->page = APRS_MODE_PAGE_MONITOR;
				u->resetArmed = 0U;
				return 1;
			}
			if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN))
			{
				u->sel = (uint8_t)wrapStep(u->sel, KEYCHECK_PRESS(ev->keys, KEY_DOWN) ? 1 : -1, APRSM_F_COUNT - 1);
				u->resetArmed = 0U;
				return 1;
			}
			if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_LEFT))
			{
				settingsStep(KEYCHECK_PRESS(ev->keys, KEY_RIGHT) ? 1 : -1);
				return 1;
			}
			if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
			{
				settingsGreen();
				return 1;
			}
			if (KEYCHECK_SHORTUP(ev->keys, KEY_STAR))
			{
				gotoPage(+1);
				return 1;
			}
			if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH))
			{
				gotoPage(-1);
				return 1;
			}
			return 0;
	}
}

/* ---- екран --------------------------------------------------------------------------------------------------- */

static void draw(void)
{
	aprsModeUi_t *u = aprsModeUi();
	char title[24];

	AM_TRACE_T(84);   /* draw(): початок */
	u->lastDrawMs = ticksGetMillis();
	if (u->edit.active)
	{
		editDraw();
		return;
	}
	displayClearBuf();
	snprintf(title, sizeof(title), APRSM_TITLE_FMT, (unsigned)(u->page + 1U), (unsigned)APRS_MODE_PAGES);
	menuDisplayTitle(title);
	AM_TRACE_T(85);   /* draw(): перед малюванням сторінки */
	switch (u->page)
	{
		case APRS_MODE_PAGE_MONITOR:
			drawMonitor();
			break;
		case APRS_MODE_PAGE_STATIONS:
			menuAprsStationsDrawEmbedded();
			break;
		default:
			drawSettings();
			break;
	}
	AM_TRACE_T(86);   /* draw(): сторінку намальовано, перед displayRender() */
	displayRender();
}

bool menuAprsModeEnter(void)
{
	AM_TRACE(51);   /* menuAprsModeEnter: перед aprsModeEnter() (далі 1..19, 30..37) */
	if (aprsModeEnter() == false)
	{
		uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, APRSM_NOT_NOW, true);
		soundSetMelody(MELODY_ERROR_BEEP);
		return false;
	}
	AM_TRACE(52);   /* aprsModeEnter() повернув true; перед першим draw() (далі 84..86) */
	draw();
	return true;
}

bool menuAprsModeTick(uiEvent_t *ev)
{
	aprsModeUi_t *u = aprsModeUi();
	uint32_t now = ticksGetMillis();
	bool redraw = false;

	AM_TRACE_T(80);   /* menuAprsModeTick: перший тік */
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
		int r;

		AM_TRACE_T(81);   /* перед pageEvent */
		r = pageEvent(ev);
		AM_TRACE_T(82);   /* після pageEvent */

		if (r < 0)
		{
			aprsModeExit();
			return false;
		}
		redraw = (r > 0);
	}

	if ((ev->hasEvent) && (ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		redraw = true;
	}
	if ((u->edit.active == 0U) && (redraw == false))
	{
		uint32_t period = (u->page == APRS_MODE_PAGE_MONITOR) ? AM_MON_REDRAW_MS :
				((u->page == APRS_MODE_PAGE_STATIONS) ? AM_ST_REDRAW_MS : 0xFFFFFFFFUL);

		if ((period != 0xFFFFFFFFUL) && ((now - u->lastDrawMs) >= period))
		{
			redraw = true;
		}
	}
	if (redraw)
	{
		draw();
	}
	return true;
}

#endif /* APRS_RX */
