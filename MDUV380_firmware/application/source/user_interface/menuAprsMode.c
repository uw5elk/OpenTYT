/*
 * menuAprsMode.c -- екран «Режиму APRS» (R10). Сторінки (валкодер / ←→ / ↑↓ -- між ними, де це не заважає):
 *   1 «Монітор»      -- частота, стан, сигнал, кадри ок/пом, біт (nbits), останній пакет, маяки; GREEN -- маяк;
 *   2 «Станції»      -- список R8 (16 станцій) і картка станції (спільний код з menuAprsStations.c);
 *   3 «Налаштування» -- частота, позивний, SSID, шлях 1/2, символ, коментар, позиція, неточність, інтервал
 *                       маяка, шумодав, «Скинути»; значення міняються ←→ (перелічувані) або в редакторі (GREEN).
 *   3 «Повідомлення» (R11) -- список (8: вхідні + наші зі станом), читання з перенесенням за словами великим шрифтом, «Нове»
 *                       (адресат Latin + текст кирилицею, multitap), «Відповісти»; логіка й черга -- aprs_msg.c / aprs_mode.c;
 *   4 «Налаштування» -- (було 3-ю до R11).
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
#include "user_interface/languages/aprsmsg_ua.h"
#include "user_interface/uiSmsKeys.h"   /* R11-fix2: підказка літер і шпаргалка розкладки -- спільні з SMS */
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

	if (last->valid && last->tp)
	{
		/* R11-fix: останній пакет прийшов через i-gate (third-party): рядок 5 -- справжній відправник, тут -- шлюз */
		snprintf(buf, sizeof(buf), APRSM_M_3P, last->gate);
		printRow(9, buf);
	}
	else
	{
		printRow(9, APRSM_M_NORX);
	}
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


/* ---- R11: сторінка «Повідомлення» ---------------------------------------------------------------------------- */

#define AM_MSG_REDRAW_MS    500U
#define AM_MSG_COLS         20           /* великий шрифт 8x16 на екрані 160 px */
#define AM_MSG_FONT         FONT_SIZE_3
#define AM_MSG_LINE_H       FONT_SIZE_3_HEIGHT

static void gotoPage(int dir);

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

static void drawMsgList(void)
{
	aprsMsgBox_t *b = aprsModeMsgBox();
	aprsMsgUi_t *mu = &aprsModeUi()->msg;
	unsigned count = aprsMsgListCount(b);
	uint32_t now = ticksGetMillis();
	char buf[40], age[8];

	snprintf(buf, sizeof(buf), APRSMSG_L_HDR, aprsMsgUnreadCount(b), aprsMsgPendingCount(b));
	printRow(0, buf);
	if (count == 0U)
	{
		displayPrintCentered(AM_ROW(4), APRSMSG_L_EMPTY, FONT_SIZE_1);
		printRow(10, APRSMSG_L_HINT);
		return;
	}
	if (mu->sel >= count)
	{
		mu->sel = (uint8_t)(count - 1U);
	}
	for (unsigned i = 0; i < count; i++)
	{
		const aprsMsgEntry_t *e = &b->list[i];
		char mark = (e->dir == AMSG_DIR_OUT) ? '<' : (e->unread ? '*' : ' ');

		msgAgeStr(age, sizeof(age), e, now);
		/* маркер(1) + ознака(1) + позивний(9) + пробіл(1) + текст або стан(9) + вік(5) = 26 символів */
		snprintf(buf, sizeof(buf), "%c%c%-9.9s %-9.9s%5.5s", (i == mu->sel) ? '>' : ' ', mark, e->call,
				(e->dir == AMSG_DIR_OUT) ? msgStatusWord(e->status) : e->text, age);
		printRow(1 + (int)i, buf);
	}
	printRow(10, APRSMSG_L_HINT);
}

/* Малює рядки [first, first + rows) тексту, розбитого aprsMsgWrapLine() з шириною cols. Повертає загальну кількість рядків. */
static int drawWrapped(const char *t, int len, int first, int rows, int16_t y0)
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
			displayPrintCore(0, (int16_t)(y0 + ((line - first) * AM_MSG_LINE_H)), one, AM_MSG_FONT, TEXT_ALIGN_LEFT, false);
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
	const aprsMsgEntry_t *e = &b->list[(mu->sel < APRS_MSG_LIST_MAX) ? mu->sel : 0U];
	char buf[48], age[8];
	const int16_t y0 = 38;
	const int rows = ((111 - y0 - AM_MSG_LINE_H) / AM_MSG_LINE_H) + 1;
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

	total = drawWrapped(e->text, (int)strlen(e->text), 0, 0, y0);   /* лише порахувати */
	maxTop = (total > rows) ? (total - rows) : 0;
	if (mu->readTop > maxTop)
	{
		mu->readTop = (uint8_t)maxTop;
	}
	(void)drawWrapped(e->text, (int)strlen(e->text), mu->readTop, rows, y0);
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

static void drawMsgPage(void)
{
	if (aprsModeUi()->msg.view == APRS_MSG_VIEW_READ)
	{
		drawMsgRead();
	}
	else
	{
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
	int16_t y0 = isCall ? 30 : 26;
	int rows = isCall ? 2 : 4;
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
	total = drawWrapped(cur, len, 0, 0, y0);
	first = (total > rows) ? (total - rows) : 0;   /* вікно іде за курсором: показуємо останні рядки */
	(void)drawWrapped(cur, len, first, rows, y0);
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
	uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, txt, true);
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
			mu->view = APRS_MSG_VIEW_LIST;
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
				mu->sel = 0U;
				mu->err = 0U;
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

	if ((n < 0) || (n >= (int)aprsMsgListCount(b)))
	{
		return;
	}
	mu->sel = (uint8_t)n;
	mu->readTop = 0U;
	aprsMsgMarkRead(b, (unsigned)n);
}

/* Подія списку/читання. Повертає: 0 -- нічого, 1 -- перемалювати. */
static int msgPageEvent(uiEvent_t *ev)
{
	aprsModeUi_t *u = aprsModeUi();
	aprsMsgUi_t *mu = &u->msg;
	aprsMsgBox_t *b = aprsModeMsgBox();
	unsigned count = aprsMsgListCount(b);

	if ((ev->hasEvent == false) || ((ev->events & KEY_EVENT) == 0))
	{
		return 0;
	}
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
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && (mu->sel < count))
		{
			char norm[APRS_MSG_CALL_LEN];

			if (aprsMsgNormCall(norm, b->list[mu->sel].call))
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

	/* список */
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		u->page = APRS_MODE_PAGE_MONITOR;
		return 1;
	}
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
	if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		int n = (int)mu->sel + (KEYCHECK_PRESS(ev->keys, KEY_DOWN) ? 1 : -1);

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
		aprsMsgMarkRead(b, mu->sel);
		return 1;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_STAR))
	{
		msgComposeStart(NULL);
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
	u->msg.view = APRS_MSG_VIEW_LIST;
	u->msg.sel = 0U;
	u->msg.readTop = 0U;
	u->msg.err = 0U;
	u->msg.mt.key = 0;
	u->msg.mt.idx = 0;
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
	else if (u->page == APRS_MODE_PAGE_MESSAGES)
	{
		msgOpenPage();
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
		case APRS_MODE_PAGE_MESSAGES:
			return msgPageEvent(ev);

		case APRS_MODE_PAGE_MONITOR:
			if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				if (aprsModeIsTransmitting())
				{
					return 0;   /* посеред маяка не виходимо */
				}
				/* R11-fix2: черга повідомлень/ACK фонова -- вихід з режиму її НЕ скасовує (підтвердження «RED ще раз» прибрано) */
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
	if ((u->page == APRS_MODE_PAGE_MESSAGES) && ((u->msg.view == APRS_MSG_VIEW_CALL) || (u->msg.view == APRS_MSG_VIEW_TEXT)))
	{
		drawMsgCompose();   /* R11: набір -- на весь екран, з власним заголовком */
		displayRender();
		return;
	}
	displayClearBuf();
	snprintf(title, sizeof(title), APRSM_TITLE_FMT, (unsigned)(u->page + 1U), (unsigned)APRS_MODE_PAGES);
	menuDisplayTitle((u->page == APRS_MODE_PAGE_MESSAGES) ? ((u->msg.view == APRS_MSG_VIEW_READ) ? APRSMSG_TITLE_READ : APRSMSG_TITLE) : title);
	AM_TRACE_T(85);   /* draw(): перед малюванням сторінки */
	switch (u->page)
	{
		case APRS_MODE_PAGE_MONITOR:
			drawMonitor();
			break;
		case APRS_MODE_PAGE_STATIONS:
			menuAprsStationsDrawEmbedded();
			break;
		case APRS_MODE_PAGE_MESSAGES:
			drawMsgPage();
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

bool menuAprsModeEnterMessages(void)
{
	if (aprsModeEnter() == false)
	{
		uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, APRSM_NOT_NOW, true);
		soundSetMelody(MELODY_ERROR_BEEP);
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
	if (aprsModeIsActive() == false)
	{
		bool wasOn = (aprsRxUi()->on != 0U);

		aprsRxUi()->on = 0;   /* «APRS станції» (R8) закриваємо: далі всі тіки меню належать режиму */
		if (aprsModeEnter() == false)
		{
			aprsRxUi()->on = wasOn ? 1U : 0U;   /* не вийшло -- лишаємось на картці станції */
			uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 1500, APRSM_NOT_NOW, true);
			soundSetMelody(MELODY_ERROR_BEEP);
			return false;
		}
	}
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
	else if ((u->page == APRS_MODE_PAGE_MESSAGES) && ((u->msg.view == APRS_MSG_VIEW_CALL) || (u->msg.view == APRS_MSG_VIEW_TEXT)))
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
		bool composing = (u->page == APRS_MODE_PAGE_MESSAGES) && ((u->msg.view == APRS_MSG_VIEW_CALL) || (u->msg.view == APRS_MSG_VIEW_TEXT));
		uint32_t period = (u->page == APRS_MODE_PAGE_MONITOR) ? AM_MON_REDRAW_MS :
				((u->page == APRS_MODE_PAGE_STATIONS) ? AM_ST_REDRAW_MS :
				((u->page == APRS_MODE_PAGE_MESSAGES) ? (composing ? 0xFFFFFFFFUL : AM_MSG_REDRAW_MS) : 0xFFFFFFFFUL));

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
