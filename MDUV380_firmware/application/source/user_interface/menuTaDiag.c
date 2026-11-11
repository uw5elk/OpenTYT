/*
 * menuTaDiag.c -- R88: екран «TA diag». Лише збірка з ENABLE_TA_DIAG. Усі рядки ASCII/англійською (мовних файлів не чіпаємо);
 * кожен рядок <= 16 символів (як на екрані «Гучн. проба», R77B). Нічого не пише у кодплаг/флеш і не змінює налаштувань.
 * Клавіші: ВГОРУ/ВНИЗ -- сторінка, ВЛІВО/ВПРАВО -- виклик (старіший/новіший), ЧЕРВОНА/ЗЕЛЕНА -- назад.
 */
#include "user_interface/menuTaDiag.h"

#if defined(TA_DIAG)
#include <stdio.h>
#include <string.h>
#include "applicationMain.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "functions/ticks.h"
#include "hardware/HX8353E.h"
#include "io/keyboard.h"

#define TD_ROW(n)       (16 + ((n) * 10))
#define TD_REDRAW_MS    500U
#define TD_PAGES        6U

static bool s_open;
static uint32_t s_lastDraw;
static uint8_t s_page;       /* 0..TD_PAGES-1 */
static uint8_t s_age;        /* 0 -- найновіший виклик */

static void row(int n, const char *text)
{
	displayPrintAt(0, TD_ROW(n), text, FONT_SIZE_1);
}

static void pageCall(const taDiagRec_t *r)
{
	char buf[SCREEN_LINE_BUFFER_SIZE + 8];
	taDiagHdr_t h;

	if (r == NULL)
	{
		row(0, "No call yet");
		row(1, "Rx a DMR call,");
		row(2, "then open again");
		return;
	}
	snprintf(buf, sizeof(buf), "SRC %lu", (unsigned long)r->srcId);
	row(0, buf);
	snprintf(buf, sizeof(buf), "%s %lu", r->isPc ? "PC" : "TG", (unsigned long)r->tgOrPc);
	row(1, buf);
	snprintf(buf, sizeof(buf), "BLK 4567=%c%c%c%c", (r->taMask & 1U) ? '1' : '0', (r->taMask & 2U) ? '1' : '0',
			(r->taMask & 4U) ? '1' : '0', (r->taMask & 8U) ? '1' : '0');
	row(2, buf);
	snprintf(buf, sizeof(buf), "SEEN %u/%u/%u/%u", r->taSeen[0], r->taSeen[1], r->taSeen[2], r->taSeen[3]);
	row(3, buf);
	if ((r->taMask & 1U) != 0U)
	{
		taDiagParseHeader(r->ta[0][0], &h);
		snprintf(buf, sizeof(buf), "HDR %02X %s L%u", r->ta[0][0], taDiagFormatName(h.format), h.size);
	}
	else
	{
		snprintf(buf, sizeof(buf), "HDR (no blk 4)");
	}
	row(4, buf);
	snprintf(buf, sizeof(buf), "FID %02X %02X %02X %02X", r->taFid[0], r->taFid[1], r->taFid[2], r->taFid[3]);
	row(5, buf);
	if (r->gpsSeen != 0U)
	{
		snprintf(buf, sizeof(buf), "GPS yes x%u", r->gpsSeen);
	}
	else
	{
		snprintf(buf, sizeof(buf), "GPS no");
	}
	row(6, buf);
	snprintf(buf, sizeof(buf), "ALL LC %lu", (unsigned long)taDiagAllFlcoTotal());
	row(7, buf);
	snprintf(buf, sizeof(buf), "PF %lu BAD %lu", (unsigned long)taDiagPfCount(), (unsigned long)taDiagCrcBadCount());
	row(8, buf);
}

static void pageRaw(const taDiagRec_t *r)
{
	char buf[SCREEN_LINE_BUFFER_SIZE + 8];
	char hex[2U * TA_DIAG_BLOCK_LEN + 1U];

	if (r == NULL)
	{
		row(0, "No call yet");
		return;
	}
	for (uint8_t b = 0; b < TA_DIAG_BLOCKS; b++)
	{
		if ((r->taMask & (1U << b)) != 0U)
		{
			(void)taDiagHex(hex, sizeof(hex), r->ta[b], TA_DIAG_BLOCK_LEN);
			snprintf(buf, sizeof(buf), "%u %s", 4U + b, hex);
		}
		else
		{
			snprintf(buf, sizeof(buf), "%u --", 4U + b);
		}
		row(b, buf);
	}
	row(5, "7 bytes per blk");
	row(6, "= LC bytes 2..8");
	row(7, "(not decoded)");
}

static void textRows(int firstRow, const char *label, const char *text)
{
	char line[SCREEN_LINE_BUFFER_SIZE + 8];

	row(firstRow, label);
	taDiagPrintable(line, sizeof(line), text, 0U, 16U);
	row(firstRow + 1, line);
	taDiagPrintable(line, sizeof(line), text, 16U, 16U);
	row(firstRow + 2, line);
}

static void pageText(const taDiagRec_t *r)
{
	char buf[SCREEN_LINE_BUFFER_SIZE + 8];
	char hex[2U * 7U + 1U];
	char dg[TA_DIAG_FW_TEXT_LEN];
	uint8_t glue[TA_DIAG_BUF_LEN];

	if (r == NULL)
	{
		row(0, "No call yet");
		return;
	}
	taDiagGlue(r, glue);
	(void)taDiagDecode(glue, dg, sizeof(dg));
	textRows(0, "FW text:", r->fwText);
	textRows(3, "DG text:", dg);
	snprintf(buf, sizeof(buf), "LEN FW%u DG%u %s", (unsigned)strlen(r->fwText), (unsigned)strlen(dg), (strcmp(r->fwText, dg) == 0) ? "=" : "DIFF");
	row(6, buf);
	(void)taDiagHex(hex, sizeof(hex), (const uint8_t *)r->fwText, 7U);
	snprintf(buf, sizeof(buf), "FW0 %s", hex);
	row(7, buf);
	(void)taDiagHex(hex, sizeof(hex), (const uint8_t *)dg, 7U);
	snprintf(buf, sizeof(buf), "DG0 %s", hex);
	row(8, buf);
}

static void pageGps(const taDiagRec_t *r)
{
	char buf[SCREEN_LINE_BUFFER_SIZE + 8];
	char hex[2U * TA_DIAG_BLOCK_LEN + 1U];
	char num[16];
	int32_t lat, lon;
	uint8_t err;

	if (r == NULL)
	{
		row(0, "No call yet");
		return;
	}
	snprintf(buf, sizeof(buf), "GPS seen %u", r->gpsSeen);
	row(0, buf);
	if (r->gpsSeen == 0U)
	{
		row(1, "no LC 0x08 block");
		return;
	}
	snprintf(buf, sizeof(buf), "FID %02X", r->gpsFid);
	row(1, buf);
	(void)taDiagHex(hex, sizeof(hex), r->gpsRaw, TA_DIAG_BLOCK_LEN);
	snprintf(buf, sizeof(buf), "R %s", hex);
	row(2, buf);
	(void)taDiagParseGps(r->gpsRaw, &lat, &lon, &err);
	taDiagFmtDeg(num, sizeof(num), lat);
	snprintf(buf, sizeof(buf), "LAT %s", num);
	row(3, buf);
	taDiagFmtDeg(num, sizeof(num), lon);
	snprintf(buf, sizeof(buf), "LON %s", num);
	row(4, buf);
	snprintf(buf, sizeof(buf), "ERR idx %u", err);
	row(5, buf);
	row(6, ((lat >= -900000) && (lat <= 900000) && (lon >= -1800000) && (lon <= 1800000)) ? "range ok" : "OUT OF RANGE");
}

static void pageFlco(const uint8_t *cnt, const char *head)
{
	char line[SCREEN_LINE_BUFFER_SIZE + 8];
	size_t cursor = 0U;
	int n = 1;

	row(0, head);
	while ((n < 9) && taDiagFlcoRow(cnt, &cursor, line, sizeof(line), 16U))
	{
		row(n++, line);
	}
	if (n == 1)
	{
		row(1, "(none)");
	}
}

static void draw(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE + 8];
	const taDiagRec_t *r = taDiagGet(s_age);
	size_t cnt = taDiagCount();

	s_lastDraw = ticksGetMillis();
	displayClearBuf();
	snprintf(buf, sizeof(buf), "TA R%u/%u P%u/%u", (cnt != 0U) ? (unsigned)(s_age + 1U) : 0U, (unsigned)cnt, (unsigned)(s_page + 1U), (unsigned)TD_PAGES);
	menuDisplayTitle(buf);

	switch (s_page)
	{
		case 0: pageCall(r); break;
		case 1: pageRaw(r); break;
		case 2: pageText(r); break;
		case 3: pageGps(r); break;
		case 4:
			if (r != NULL) { pageFlco(r->flco, "Call FLCO hex:cnt"); } else { row(0, "No call yet"); }
			break;
		default:
			pageFlco(taDiagAllFlco(), "All LC hex:cnt");
			break;
	}
	row(9, "UD page LR call");
	displayRender();
}

void menuTaDiagEnter(void)
{
	s_open = true;
	s_page = 0U;
	s_age = 0U;
	draw();
}

bool menuTaDiagIsOpen(void)
{
	return s_open;
}

void menuTaDiagClose(void)
{
	s_open = false;
}

bool menuTaDiagTick(uiEvent_t *ev)
{
	bool redraw = false;

	if (ev->hasEvent && (ev->events & KEY_EVENT))
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_RED) || KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			s_open = false;
			return false;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
		{
			s_page = (uint8_t)((s_page + 1U) % TD_PAGES);
			redraw = true;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
		{
			s_page = (uint8_t)((s_page + TD_PAGES - 1U) % TD_PAGES);
			redraw = true;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
		{
			if (s_age > 0U)
			{
				s_age--;
			}
			redraw = true;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))
		{
			if ((size_t)(s_age + 1U) < taDiagCount())
			{
				s_age++;
			}
			redraw = true;
		}
	}
	if (ev->hasEvent && (ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		redraw = true;
	}
	if (redraw || ((ticksGetMillis() - s_lastDraw) >= TD_REDRAW_MS))
	{
		draw();
	}
	return true;
}
#endif /* TA_DIAG */
