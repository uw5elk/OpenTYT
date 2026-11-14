/* R91C (форк): див. functions/lc_distance.h. Увесь файл -- лише під ENABLE_LC_DISTANCE (+ APRS_RX). */
#include "functions/lc_distance.h"

#if defined(LC_DISTANCE)

#include <math.h>
#include <stdio.h>
#include <string.h>

bool lcDistUsable(double lat, double lon)
{
	if (isnan(lat) || isnan(lon))
	{
		return false;
	}

	if ((lat < -90.0) || (lat > 90.0) || (lon < -180.0) || (lon > 180.0))
	{
		return false;
	}

	return !((lat == 0.0) && (lon == 0.0));
}

bool lcDistCompute(double myLat, double myLon, double lat, double lon, uint32_t *distM, uint16_t *bearingDeg)
{
	if ((isnan(myLat) || isnan(myLon) || (myLat < -90.0) || (myLat > 90.0) || (myLon < -180.0) || (myLon > 180.0)) || (lcDistUsable(lat, lon) == false))
	{
		return false;
	}

	double m = distanceBetweenTwoCoords(myLat, myLon, lat, lon, false);
	double brg = courseTo(myLat, myLon, lat, lon);

	*distM = (m < 0.0) ? 0U : (uint32_t)(m + 0.5);
	*bearingDeg = (uint16_t)(((int)(brg + 0.5)) % 360);

	return true;
}

bool lcDistText(char *buf, size_t size, bool ownPositionValid, double myLat, double myLon, double lat, double lon)
{
	uint32_t distM;
	uint16_t brg;

	if ((ownPositionValid == false) || (lcDistCompute(myLat, myLon, lat, lon, &distM, &brg) == false))
	{
		return false;
	}

	aprsRxFormatGeo(buf, size, distM, brg);

	return true;
}

bool lcDistLabel(char *buf, size_t size, bool ownPositionValid, double myLat, double myLon, double lat, double lon, uint16_t *bearingDeg, bool *bearingKnown)
{
	uint32_t distM;

	if ((ownPositionValid == false) || (lcDistCompute(myLat, myLon, lat, lon, &distM, bearingDeg) == false))
	{
		return false;
	}

	aprsRxFormatDist(buf, size, distM);
	*bearingKnown = aprsBearingKnown(distM);

	return true;
}

lcDistRow_t lcDistLabelRow(size_t textLen, bool singleLineOnly, bool autoSplit)
{
	if (textLen < 5U)
	{
		return LC_ROW_NONE;
	}

	if (singleLineOnly || (autoSplit && (textLen <= 16U)))
	{
		return (textLen <= 16U) ? LC_ROW_FIRST : LC_ROW_NONE;
	}

	return LC_ROW_SECOND;
}

void lcDistArrowGeom(lcDistArrow_t *a, int16_t screenW, int16_t rowY, int16_t rowH, uint16_t bearingDeg)
{
	a->cx = (int16_t)(screenW - LC_ARROW_MARGIN);
	a->cy = (int16_t)(rowY + (rowH / 2));
	aprsChevronGeom(&a->g, a->cx, a->cy, LC_ARROW_LEN, bearingDeg);
}

// R98-FIX3 Г: chomp() / getFirstSpacePos() з uiUtilities.c -- та сама логіка над копією (чиста функція, збирається на хості)
static char *lcChomp(char *s)
{
	char *ep = s + strlen(s);

	while ((ep > s) && ((ep[-1] == ' ')))
	{
		ep--;
		*ep = 0;
	}

	while (*s == ' ')
	{
		s++;
	}

	return s;
}

static void lcSpan(lcDistSpan_t *sp, const char *s, int16_t w, int16_t screenW, int16_t y, int16_t h)
{
	int n = (int)strlen(s);

	if ((w * n) > screenW)
	{
		n = (screenW / w);
	}

	sp->x0 = (int16_t)((screenW - (w * n)) >> 1);
	sp->x1 = (int16_t)(sp->x0 + (w * n));
	sp->y = y;
	sp->h = h;
}

bool lcDistLabelTail(const char *text, bool singleLineOnly, bool autoSplit, bool dblHeight, int16_t screenW, int16_t firstY, int16_t secondY, lcDistSpan_t *tail, lcDistSpan_t *above)
{
	char buf[64];
	size_t len = strlen(text);
	const int16_t h3 = (int16_t)(16 * (dblHeight ? 2 : 1));
	const int16_t h1 = (int16_t)(8 * (dblHeight ? 2 : 1));

	above->h = 0;

	if (lcDistLabelRow(len, singleLineOnly, autoSplit) == LC_ROW_NONE)
	{
		return false;
	}

	if (singleLineOnly || (autoSplit && (len <= 16U)))
	{
		// displayContactTextInfos(): перші 16 символів -> chomp -> перший рядок (8x16)
		memcpy(buf, text, 16);
		buf[16] = 0;
		lcSpan(tail, lcChomp(buf), 8, screenW, firstY, h3);
		return true;
	}

	const char *sp = strchr(text, ' ');
	char *rest;

	if (sp != NULL)
	{
		snprintf(buf, sizeof(buf), "%s", (sp + 1));   // позивний -- у першому рядку, решта -- у другому
	}
	else
	{
		snprintf(buf, sizeof(buf), "%s", (text + 16));   // «пилка»: перші 16 -- у першому рядку
	}

	rest = lcChomp(buf);

	size_t L = strlen(rest);

	if (L == 0U)
	{
		return false;
	}

	if (L <= 16U)
	{
		lcSpan(tail, rest, 8, screenW, secondY, h3);   // displaySplitOrSpanText(): до 16 -- один рядок 8x16
		return true;
	}

	int nLines = (int)((L / 21U) + (((L % 21U) != 0U) ? 1U : 0U));

	if (nLines > 2)
	{
		nLines = 2;
		L = 42U;
	}

	if (nLines == 1)
	{
		lcSpan(tail, rest, 6, screenW, (int16_t)(secondY + 4), h1);   // 17..21 -- один рядок 6x8, на 4 px нижче
		return true;
	}

	char b[64];
	size_t bl = ((L + 1U) < strlen(rest)) ? (L + 1U) : strlen(rest);   // memcpy(buffer, text, len + 1) і buffer[len + 1] = 0

	memcpy(b, rest, bl);
	b[bl] = 0;

	char *p = b + 20;

	while ((*p != ' ') && (p > b))
	{
		p--;
	}

	size_t rest2 = (size_t)((b + strlen(b)) - p) - ((*p == ' ') ? 1U : 0U);
	char l1[64];
	char l2[64];

	if (rest2 > 21U)
	{
		memcpy(l1, b, 21);
		l1[21] = 0;
		snprintf(l2, sizeof(l2), "%s", (b + 21));
	}
	else
	{
		*p = 0;
		snprintf(l1, sizeof(l1), "%s", b);
		snprintf(l2, sizeof(l2), "%s", (p + 1));
	}

	lcSpan(above, lcChomp(l1), 6, screenW, secondY, h1);
	lcSpan(tail, lcChomp(l2), 6, screenW, (int16_t)(secondY + h1), h1);
	return true;
}

void lcDistArrowAfter(lcDistArrow_t *a, const lcDistSpan_t *tail, const lcDistSpan_t *above, int16_t screenW, uint16_t bearingDeg)
{
	// по вертикалі -- середина рядка; рядок 6x8 нижчий за комірку (8 < 10) -- комірка від верху рядка вниз, щоб не зачепити підрядок над
	int16_t cy = (int16_t)(tail->y + (((tail->h > LC_ARROW_CELL) ? tail->h : LC_ARROW_CELL) / 2));
	int16_t left = (int16_t)(tail->x1 + LC_ARROW_GAP);
	int16_t top = (int16_t)(cy - (LC_ARROW_CELL / 2));

	// комірка заходить на підрядок над (по вертикалі) -- і від його кінця теж LC_ARROW_GAP
	if ((above->h > 0) && (top < (above->y + above->h)) && ((above->x1 + LC_ARROW_GAP) > left))
	{
		left = (int16_t)(above->x1 + LC_ARROW_GAP);
	}

	if ((left + LC_ARROW_CELL) > screenW)
	{
		left = (int16_t)(screenW - LC_ARROW_CELL);   // до краю не влазить -- найближча позиція праворуч, у межах екрана
	}

	a->cx = (int16_t)(left + (LC_ARROW_CELL / 2));
	a->cy = cy;
	aprsChevronGeom(&a->g, a->cx, a->cy, LC_ARROW_LEN, bearingDeg);
}

#endif /* LC_DISTANCE */
