/*
 * sms_format.c -- перенесення за словами, форма слова для числа, формат часу SMS (ui6).
 * Опис -- у sms_format.h. Чистий модуль: без заліза, без масивів, тестується на хості.
 */
#include "functions/sms_format.h"

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)

int smsWrapLine(const char *s, int len, int start, int w, int *lineStart, int *next)
{
	int p = start;
	while ((p < len) && (s[p] == ' ')) { p++; }
	*lineStart = p;
	if ((p >= len) || (w <= 0))
	{
		*next = len;
		return 0;
	}

	int end;
	if ((len - p) <= w)
	{
		end = len;                         /* залишок влазить повністю */
	}
	else if (s[p + w] == ' ')
	{
		end = p + w;                       /* рівно w символів, далі пробіл -- розрив тут */
	}
	else
	{
		int sp = -1;
		for (int i = p + w - 1; i > p; i--)
		{
			if (s[i] == ' ') { sp = i; break; }
		}
		end = (sp > 0) ? sp : (p + w);     /* слово довше за w -- рубаємо по w */
	}
	*next = end;
	while ((end > p) && (s[end - 1] == ' ')) { end--; }
	return end - p;
}

int smsWrapCount(const char *s, int len, int w)
{
	int n = 0, pos = 0, ls, nx;
	while (pos < len)
	{
		int l = smsWrapLine(s, len, pos, w, &ls, &nx);
		if (l > 0) { n++; }
		if (nx <= pos) { break; }          /* запобіжник: позиція мусить рости */
		pos = nx;
	}
	return n;
}

void smsWrapPos(const char *s, int len, int w, int pos, int *row, int *col)
{
	int r = 0, p = 0, ls, nx;

	if (w <= 0) { *row = 0; *col = 0; return; }
	if (pos < 0) { pos = 0; }
	if (pos > len) { pos = len; }

	while (p < len)
	{
		int l = smsWrapLine(s, len, p, w, &ls, &nx);
		if (l <= 0) { break; }             /* далі лише пробіли */

		/* Кінець «зони» цього рядка: перший непробільний символ наступного (або кінець тексту). */
		int zoneEnd = nx;
		while ((zoneEnd < len) && (s[zoneEnd] == ' ')) { zoneEnd++; }

		if ((pos < zoneEnd) || (zoneEnd >= len))
		{
			int c = pos - ls;
			if (c < 0) { c = 0; }          /* пробіли перед першим рядком тексту */
			if (c < w) { *row = r; *col = c; }
			else       { *row = r + 1; *col = 0; }
			return;
		}
		r++;
		p = nx;
	}
	/* Порожній текст або самі пробіли: просто по w у рядок. */
	*row = pos / w;
	*col = pos % w;
}

int smsPluralForm(int n)
{
	if (n < 0) { n = -n; }
	int d = n % 10, h = n % 100;
	if ((d == 1) && (h != 11)) { return 0; }
	if ((d >= 2) && (d <= 4) && ((h < 12) || (h > 14))) { return 1; }
	return 2;
}

int32_t smsTzOffsetSecs(uint8_t tz)
{
	return (tz & 0x80) ? (int32_t)(((int)(tz & 0x7F) - 64) * (15 * 60)) : 0;
}

/* День і місяць з номера дня від 1970-01-01 (алгоритм H. Hinnant, без таблиць). */
static void civilDayMonth(uint32_t days, int *day, int *month)
{
	uint32_t z = days + 719468U;
	uint32_t era = z / 146097U;
	uint32_t doe = z - era * 146097U;
	uint32_t yoe = (doe - doe / 1460U + doe / 36524U - doe / 146096U) / 365U;
	uint32_t doy = doe - (365U * yoe + yoe / 4U - yoe / 100U);
	uint32_t mp = (5U * doy + 2U) / 153U;
	*day = (int)(doy - (153U * mp + 2U) / 5U + 1U);
	*month = (int)((mp < 10U) ? (mp + 3U) : (mp - 9U));
}

static int put2(char *out, int pos, int outsz, int v)
{
	if (pos + 2 >= outsz) { return pos; }
	out[pos++] = (char)('0' + (v / 10) % 10);
	out[pos++] = (char)('0' + v % 10);
	return pos;
}

static int putc1(char *out, int pos, int outsz, char c)
{
	if (pos + 1 >= outsz) { return pos; }
	out[pos++] = c;
	return pos;
}

int smsTimeFormat(uint32_t t, uint32_t now, int32_t tzSecs, int mode, char *out, int outsz)
{
	if (outsz <= 0) { return 0; }
	out[0] = 0;
	if (t == 0) { return 0; }

	uint32_t lt = (uint32_t)((int64_t)t + tzSecs);
	uint32_t day = lt / 86400U, sec = lt % 86400U;
	int hh = (int)(sec / 3600U), mm = (int)((sec / 60U) % 60U);
	int dd, mo;
	civilDayMonth(day, &dd, &mo);

	int showDate = 0, showTime = 0;
	switch (mode)
	{
		case SMS_TIME_FULL: showDate = 1; showTime = 1; break;
		case SMS_TIME_HM:   showTime = 1; break;
		default:
		{
			int today = 0;
			if (now >= SMS_TIME_VALID_MIN)
			{
				uint32_t ln = (uint32_t)((int64_t)now + tzSecs);
				today = ((ln / 86400U) == day);
			}
			if (today) { showTime = 1; } else { showDate = 1; }
			break;
		}
	}

	int p = 0;
	if (showDate)
	{
		p = put2(out, p, outsz, dd);
		p = putc1(out, p, outsz, '.');
		p = put2(out, p, outsz, mo);
	}
	if (showTime)
	{
		if (showDate) { p = putc1(out, p, outsz, ' '); }
		p = put2(out, p, outsz, hh);
		p = putc1(out, p, outsz, ':');
		p = put2(out, p, outsz, mm);
	}
	out[p] = 0;
	return p;
}

#endif
