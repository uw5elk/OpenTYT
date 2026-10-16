/*
 * aprs_rx_parse.c -- розбір прийнятих кадрів APRS (R8). Опис і обґрунтування -- aprs_rx_parse.h.
 * Чистий C без заліза: той самий файл збирає хост-тест tests/test_aprs_rx_parse.c.
 */
#include "functions/aprs_rx_parse.h"

#if defined(ENABLE_APRS_RX)

#include <string.h>
#include <stdio.h>
#include <math.h>

#if defined(ENABLE_AES)
#include "functions/dmr_sms_text.h"     /* dmrSmsCp1251ToUcs2() / dmrSmsUcs2ToCp1251(): таблиця cp1251 <-> Unicode для SMS */
#endif

/* ===================================================================================== */
/* AX.25 UI                                                                               */
/* ===================================================================================== */

/* Позивний з 7-байтового адресного поля: 6 символів (байт >> 1), пробіли обрізано, SSID у бітах 1-4.
 * false -- символи не A-Z/0-9/пробіл або порожній. */
static bool addrToStr(const uint8_t *a, char *out, bool *hBit)
{
	int n = 0;

	for (int i = 0; i < 6; i++)
	{
		uint8_t c = (uint8_t)(a[i] >> 1);

		if (c == ' ')
		{
			continue;
		}
		if (!(((c >= 'A') && (c <= 'Z')) || ((c >= '0') && (c <= '9'))))
		{
			return false;
		}
		if ((a[i] & 0x01U) != 0U)
		{
			return false;   /* ознака «кінець адрес» усередині позивного -- не адреса */
		}
		out[n++] = (char)c;
	}
	if (n == 0)
	{
		return false;
	}
	uint8_t ssid = (uint8_t)((a[6] >> 1) & 0x0FU);
	if (ssid != 0U)
	{
		out[n++] = '-';
		if (ssid >= 10U)
		{
			out[n++] = '1';
			ssid = (uint8_t)(ssid - 10U);
		}
		out[n++] = (char)('0' + ssid);
	}
	out[n] = 0;
	if (hBit != NULL)
	{
		*hBit = ((a[6] & 0x80U) != 0U);
	}
	return true;
}

bool aprsAx25Parse(const uint8_t *f, uint16_t len, aprsAx25_t *out)
{
	memset(out, 0, sizeof(*out));
	if (len < 16U)
	{
		return false;
	}
	if (!addrToStr(f, out->dst, NULL) || !addrToStr(f + 7, out->src, NULL))
	{
		return false;
	}

	/* Цифіпітери: адреси йдуть, доки в байті SSID не стоїть біт 0 (кінець адрес). */
	uint16_t pos = 14;
	size_t pathLen = 0;
	int digis = 0;
	bool last = ((f[13] & 0x01U) != 0U);

	while (!last)
	{
		if ((digis >= 8) || ((uint16_t)(pos + 7U + 2U) > len))
		{
			return false;
		}
		char d[APRS_CALL_LEN];
		bool h = false;
		if (!addrToStr(f + pos, d, &h))
		{
			return false;
		}
		size_t dl = strlen(d);
		if (pathLen + dl + 2U < sizeof(out->path))
		{
			if (pathLen > 0U)
			{
				out->path[pathLen++] = ',';
			}
			memcpy(&out->path[pathLen], d, dl);
			pathLen += dl;
			if (h)
			{
				out->path[pathLen++] = '*';
			}
			out->path[pathLen] = 0;
		}
		last = ((f[pos + 6U] & 0x01U) != 0U);
		pos = (uint16_t)(pos + 7U);
		digis++;
	}

	if (((uint16_t)(pos + 2U) > len) || (f[pos] != 0x03U) || (f[pos + 1U] != 0xF0U))
	{
		return false;   /* не UI-кадр з PID «без 3-го рівня» */
	}
	out->info = f + pos + 2U;
	out->infoLen = (uint16_t)(len - pos - 2U);
	return true;
}

/* ---- third-party ("}") -- R11-fix ------------------------------------------------------------------------- */
/* Формат (APRS-IS, «IGate Details», aprs-is.net/IGateDetails.aspx -- звірено дослівно): i-gate шле в ефір
 *     IGATECALL>APRS,GATEPATH:}FROMCALL>TOCALL,TCPIP,IGATECALL*:оригінальне info
 * тобто info кадру шлюзу = '}' + повний вкладений кадр у текстовому вигляді; шлях вкладеного кадру завжди містить «TCPIP,IGATECALL*»
 * (це захист від повернення в APRS-IS). Таблицю DTI з APRS101 ('}' = «Third-party traffic») бачили, а тіло розділу 17 PDF автоматично
 * не читається (витяг обривається раніше) -- тому правила нижче (один рівень, ліміт заголовка 120 Б) -- наші, обережні. */

static bool isDig(uint8_t c);

#define APRS_TP_HEAD_MAX   120U     /* заголовок "SRC>DST,path:" довший за це -- не наш формат (8 цифіпітерів по 9 + позивні ~ 100) */

/* Позивний вкладеного заголовка: 1..6 символів A-Z/0-9 (регістр не важливий), далі необов'язково «-SSID» (1..15 без нулів попереду;
 * «-0» -- те саме, що без SSID). Результат (ВЕРХНІЙ регістр, SSID 0 без суфікса) -- у out. */
static bool tpCall(const uint8_t *p, size_t n, char out[APRS_CALL_LEN])
{
	size_t k = 0, i = 0;

	while ((i < n) && (p[i] != '-'))
	{
		uint8_t c = p[i];

		if ((c >= 'a') && (c <= 'z'))
		{
			c = (uint8_t)(c - 'a' + 'A');
		}
		if ((k >= 6U) || (!(((c >= 'A') && (c <= 'Z')) || isDig(c))))
		{
			return false;
		}
		out[k++] = (char)c;
		i++;
	}
	if (k == 0U)
	{
		return false;
	}
	if (i < n)   /* p[i] == '-' */
	{
		size_t sl = n - i - 1U;
		unsigned v;

		if ((sl < 1U) || (sl > 2U) || (!isDig(p[i + 1U])) || ((sl == 2U) && ((!isDig(p[i + 2U])) || (p[i + 1U] == '0'))))
		{
			return false;
		}
		v = (unsigned)(p[i + 1U] - '0');
		if (sl == 2U)
		{
			v = (v * 10U) + (unsigned)(p[i + 2U] - '0');
		}
		if (v > 15U)
		{
			return false;
		}
		if (v != 0U)
		{
			out[k++] = '-';
			if (v >= 10U)
			{
				out[k++] = '1';
				v -= 10U;
			}
			out[k++] = (char)('0' + v);
		}
	}
	out[k] = 0;
	return true;
}

bool aprsAx25Unwrap(aprsAx25_t *ax)
{
	const uint8_t *in = ax->info;
	size_t n = ax->infoLen;
	size_t lim, s, i, pl = 0;
	char src[APRS_CALL_LEN] = { 0 }, dst[APRS_CALL_LEN] = { 0 }, path[APRS_PATH_LEN] = { 0 };

	/* не '}' або вже розгорнуто (один рівень: подвійне '}' далі стане «інше») */
	if (ax->tp || (in == NULL) || (n < 5U) || (in[0] != '}'))
	{
		return false;
	}
	lim = (n < APRS_TP_HEAD_MAX) ? n : APRS_TP_HEAD_MAX;

	for (i = 1U; (i < lim) && (in[i] != '>'); i++)
	{
	}
	if ((i >= lim) || (tpCall(in + 1, i - 1U, src) == false))
	{
		return false;   /* нема '>' або джерело не схоже на позивний */
	}
	s = i + 1U;
	for (i = s; (i < lim) && (in[i] != ',') && (in[i] != ':'); i++)
	{
	}
	if ((i >= lim) || (tpCall(in + s, i - s, dst) == false))
	{
		return false;
	}
	if (in[i] == ',')
	{
		for (i++; (i < lim) && (in[i] != ':'); i++)
		{
			uint8_t c = in[i];

			if ((c >= 'a') && (c <= 'z'))
			{
				c = (uint8_t)(c - 'a' + 'A');
			}
			if (!(((c >= 'A') && (c <= 'Z')) || isDig(c) || (c == ',') || (c == '*') || (c == '-') || (c == '.') || (c == '_')))
			{
				return false;   /* побитий байт у шляху */
			}
			if ((pl + 1U) < sizeof(path))
			{
				path[pl++] = (char)c;   /* зайве просто відсікається: шлях лише для показу */
			}
		}
		if (i >= lim)
		{
			return false;   /* нема ':' -- заголовок обрізано */
		}
	}
	path[pl] = 0;
	/* in[i] == ':' -- далі справжнє info (може бути порожнім: тоді «інше») */
	memcpy(ax->gate, ax->src, sizeof(ax->gate));
	memcpy(ax->src, src, sizeof(ax->src));
	memcpy(ax->dst, dst, sizeof(ax->dst));
	memcpy(ax->path, path, sizeof(ax->path));
	ax->info = in + i + 1U;
	ax->infoLen = (uint16_t)(n - (i + 1U));
	ax->tp = true;
	return true;
}

/* ---- R15: кадр у текстовому вигляді (TNC-2) -------------------------------------------------------------- */
static size_t rawPut(char *out, size_t cap, size_t n, const char *s, size_t sl)
{
	for (size_t i = 0; (i < sl) && ((n + 1U) < cap); i++)
	{
		out[n++] = s[i];
	}
	return n;
}

static size_t rawPutInfo(char *out, size_t cap, size_t n, const uint8_t *info, size_t len)
{
	for (size_t i = 0; (i < len) && ((n + 1U) < cap); i++)
	{
		out[n++] = ((info[i] < 0x20U) || (info[i] > 0x7EU)) ? '.' : (char)info[i];
	}
	return n;
}

size_t aprsAx25ToText(const uint8_t *f, uint16_t len, char *out, size_t cap)
{
	char c[APRS_CALL_LEN];
	size_t n = 0;
	uint16_t pos = 14;
	bool last;
	int digis = 0;

	if ((out == NULL) || (cap == 0U))
	{
		return 0;
	}
	out[0] = 0;
	if ((f == NULL) || (len < 16U) || (!addrToStr(f + 7, c, NULL)))
	{
		return 0;
	}
	n = rawPut(out, cap, n, c, strlen(c));
	n = rawPut(out, cap, n, ">", 1U);
	if (!addrToStr(f, c, NULL))
	{
		out[0] = 0;
		return 0;
	}
	n = rawPut(out, cap, n, c, strlen(c));
	last = ((f[13] & 0x01U) != 0U);
	while (!last)
	{
		bool h = false;

		if ((digis >= 8) || ((uint16_t)(pos + 7U + 2U) > len) || (!addrToStr(f + pos, c, &h)))
		{
			out[0] = 0;
			return 0;
		}
		n = rawPut(out, cap, n, ",", 1U);
		n = rawPut(out, cap, n, c, strlen(c));
		if (h)
		{
			n = rawPut(out, cap, n, "*", 1U);
		}
		last = ((f[pos + 6U] & 0x01U) != 0U);
		pos = (uint16_t)(pos + 7U);
		digis++;
	}
	if (((uint16_t)(pos + 2U) > len) || (f[pos] != 0x03U) || (f[pos + 1U] != 0xF0U))
	{
		out[0] = 0;
		return 0;
	}
	n = rawPut(out, cap, n, ":", 1U);
	n = rawPutInfo(out, cap, n, f + pos + 2U, (size_t)(len - pos - 2U));
	out[n] = 0;
	return n;
}

size_t aprsAx25AppendUnwrapped(char *out, size_t cap, size_t curLen, const aprsAx25_t *ax)
{
	static const char mark[] = " => ";
	size_t need, n;

	if ((out == NULL) || (ax == NULL) || (!ax->tp) || (ax->info == NULL) || (cap == 0U) || (curLen >= cap))
	{
		return curLen;
	}
	/* спершу рахуємо, скільки треба, щоб не тримати зайвий буфер на стеку: вкладений кадр або влазить цілком, або не дописується */
	need = (sizeof(mark) - 1U) + strlen(ax->src) + 1U + strlen(ax->dst) + ((ax->path[0] != 0) ? (1U + strlen(ax->path)) : 0U) + 1U + ax->infoLen;
	if ((curLen + need + 1U) > cap)
	{
		return curLen;
	}
	n = curLen;
	n = rawPut(out, cap, n, mark, sizeof(mark) - 1U);
	n = rawPut(out, cap, n, ax->src, strlen(ax->src));
	n = rawPut(out, cap, n, ">", 1U);
	n = rawPut(out, cap, n, ax->dst, strlen(ax->dst));
	if (ax->path[0] != 0)
	{
		n = rawPut(out, cap, n, ",", 1U);
		n = rawPut(out, cap, n, ax->path, strlen(ax->path));
	}
	n = rawPut(out, cap, n, ":", 1U);
	n = rawPutInfo(out, cap, n, ax->info, ax->infoLen);
	out[n] = 0;
	return n;
}

/* ===================================================================================== */
/* Текст                                                                                  */
/* ===================================================================================== */

bool aprsIsUtf8(const uint8_t *p, size_t n)
{
	size_t i = 0;

	while (i < n)
	{
		uint8_t c = p[i];

		if (c < 0x80U)
		{
			i++;
		}
		else if ((c >= 0xC2U) && (c <= 0xDFU))
		{
			if ((i + 1U >= n) || ((p[i + 1U] & 0xC0U) != 0x80U))
			{
				return false;
			}
			i += 2U;
		}
		else if ((c >= 0xE0U) && (c <= 0xEFU))
		{
			if ((i + 2U >= n) || ((p[i + 1U] & 0xC0U) != 0x80U) || ((p[i + 2U] & 0xC0U) != 0x80U))
			{
				return false;
			}
			if ((c == 0xE0U) && (p[i + 1U] < 0xA0U))
			{
				return false;   /* надмірне кодування */
			}
			if ((c == 0xEDU) && (p[i + 1U] >= 0xA0U))
			{
				return false;   /* сурогат */
			}
			i += 3U;
		}
		else if ((c >= 0xF0U) && (c <= 0xF4U))
		{
			if ((i + 3U >= n) || ((p[i + 1U] & 0xC0U) != 0x80U) || ((p[i + 2U] & 0xC0U) != 0x80U) || ((p[i + 3U] & 0xC0U) != 0x80U))
			{
				return false;
			}
			if (((c == 0xF0U) && (p[i + 1U] < 0x90U)) || ((c == 0xF4U) && (p[i + 1U] >= 0x90U)))
			{
				return false;
			}
			i += 4U;
		}
		else
		{
			return false;   /* 0x80..0xC1, 0xF5..0xFF: у UTF-8 так не починається символ */
		}
	}
	return true;
}

/* Один байт cp1251 -> байт екрана: керівні -> пробіл, 0x7F -> '?'. */
static char cp1251Safe(uint8_t c)
{
	if (c < 0x20U)
	{
		return ' ';
	}
	if (c == 0x7FU)
	{
		return '?';
	}
	return (char)c;
}

size_t aprsDecodeText(const uint8_t *in, size_t n, char *out, size_t outSize)
{
	size_t o = 0;

	if (outSize == 0U)
	{
		return 0;
	}
	if (aprsIsUtf8(in, n))
	{
		size_t i = 0;

		while ((i < n) && (o + 1U < outSize))
		{
			uint8_t c = in[i];
			uint32_t u;

			if (c < 0x80U)
			{
				u = c;
				i++;
			}
			else if (c < 0xE0U)
			{
				u = ((uint32_t)(c & 0x1FU) << 6) | (in[i + 1U] & 0x3FU);
				i += 2U;
			}
			else if (c < 0xF0U)
			{
				u = ((uint32_t)(c & 0x0FU) << 12) | ((uint32_t)(in[i + 1U] & 0x3FU) << 6) | (in[i + 2U] & 0x3FU);
				i += 3U;
			}
			else
			{
				u = 0x10000U;   /* поза BMP (емодзі) -- у cp1251 немає */
				i += 4U;
			}
#if defined(ENABLE_AES)
			out[o++] = (u > 0xFFFFU) ? '?' : cp1251Safe(dmrSmsUcs2ToCp1251((uint16_t)u));
#else
			out[o++] = (u < 0x80U) ? cp1251Safe((uint8_t)u) : '?';
#endif
		}
	}
	else
	{
		for (size_t i = 0; (i < n) && (o + 1U < outSize); i++)
		{
			out[o++] = cp1251Safe(in[i]);
		}
	}
	out[o] = 0;
	/* хвостові пробіли (CR/LF у кінці пакета) не потрібні */
	while ((o > 0U) && (out[o - 1U] == ' '))
	{
		out[--o] = 0;
	}
	return o;
}

/* ===================================================================================== */
/* Розбір APRS                                                                            */
/* ===================================================================================== */

static bool isDig(uint8_t c)
{
	return (c >= '0') && (c <= '9');
}

/* Цифра позиції: пробіл (неоднозначність) = 0. */
static int posDigit(uint8_t c)
{
	if (c == ' ')
	{
		return 0;
	}
	return isDig(c) ? (c - '0') : -1;
}

/* градуси + хвилини з сотими (v = хвилини * 100) -> мікроградуси */
static int32_t degMinToU(int deg, int minHund)
{
	return (int32_t)((int64_t)deg * 1000000LL + ((int64_t)minHund * 500LL) / 3LL);
}

/* «DDMM.hhN/DDDMM.hhW»+символ: s -- початок, n -- скільки байтів є. */
static bool parseUncompressed(const uint8_t *s, size_t n, aprsPacket_t *p)
{
	if ((n < 19U) || (s[4] != '.') || (s[14] != '.'))
	{
		return false;
	}
	int d[12];
	static const uint8_t idx[12] = { 0, 1, 2, 3, 5, 6, 9, 10, 11, 12, 13, 15 };

	for (int i = 0; i < 12; i++)
	{
		d[i] = posDigit(s[idx[i]]);
		if (d[i] < 0)
		{
			return false;
		}
	}
	int hh2 = posDigit(s[16]);
	if (hh2 < 0)
	{
		return false;
	}
	uint8_t ns = s[7];
	uint8_t ew = s[17];
	if (((ns != 'N') && (ns != 'S')) || ((ew != 'E') && (ew != 'W')))
	{
		return false;
	}
	int latDeg = d[0] * 10 + d[1];
	int latMin = d[2] * 10 + d[3];
	int latHun = d[4] * 10 + d[5];
	int lonDeg = d[6] * 100 + d[7] * 10 + d[8];
	int lonMin = d[9] * 10 + d[10];
	int lonHun = d[11] * 10 + hh2;
	if ((latDeg > 90) || (latMin > 59) || (lonDeg > 180) || (lonMin > 59))
	{
		return false;
	}
	p->latU = degMinToU(latDeg, latMin * 100 + latHun);
	p->lonU = degMinToU(lonDeg, lonMin * 100 + lonHun);
	if ((p->latU > 90000000) || (p->lonU > 180000000))
	{
		return false;
	}
	if (ns == 'S')
	{
		p->latU = -p->latU;
	}
	if (ew == 'W')
	{
		p->lonU = -p->lonU;
	}
	return true;
}

/* Стиснута позиція: s[0] таблиця, s[1..4] lat, s[5..8] lon (base91), s[9] символ, s[10..12] csT. */
static bool parseCompressed(const uint8_t *s, size_t n, aprsPacket_t *p)
{
	if (n < 13U)
	{
		return false;
	}
	int64_t v[2] = { 0, 0 };

	for (int k = 0; k < 2; k++)
	{
		for (int i = 0; i < 4; i++)
		{
			uint8_t c = s[1 + k * 4 + i];
			if ((c < 33U) || (c > 123U))
			{
				return false;
			}
			v[k] = v[k] * 91 + (c - 33);
		}
	}
	/* lat = 90 - v/380926, lon = -180 + v/190463 (градуси) */
	p->latU = (int32_t)(90000000LL - (v[0] * 1000000LL) / 380926LL);
	p->lonU = (int32_t)(-180000000LL + (v[1] * 1000000LL) / 190463LL);
	return (p->latU >= -90000000) && (p->latU <= 90000000) && (p->lonU >= -180000000) && (p->lonU <= 180000000);
}

/* Цифра Mic-E з символу призначення: 0..9, або -1. */
static int micEDigit(uint8_t c)
{
	if (isDig(c))
	{
		return c - '0';
	}
	if ((c >= 'A') && (c <= 'J'))
	{
		return c - 'A';
	}
	if ((c >= 'P') && (c <= 'Y'))
	{
		return c - 'P';
	}
	if ((c == 'K') || (c == 'L') || (c == 'Z'))
	{
		return 0;   /* пробіл (неоднозначність) */
	}
	return -1;
}

static bool parseMicE(const aprsAx25_t *ax, aprsPacket_t *p)
{
	const uint8_t *in = ax->info;

	if ((ax->infoLen < 9U) || (strlen(ax->dst) < 6U))
	{
		return false;
	}
	int dd[6];

	for (int i = 0; i < 6; i++)
	{
		dd[i] = micEDigit((uint8_t)ax->dst[i]);
		if (dd[i] < 0)
		{
			return false;
		}
	}
	bool north = ((uint8_t)ax->dst[3] >= 'P');
	bool lonOffset = ((uint8_t)ax->dst[4] >= 'P');
	bool west = ((uint8_t)ax->dst[5] >= 'P');

	if ((in[1] < 28U) || (in[2] < 28U) || (in[3] < 28U))
	{
		return false;
	}
	int lonDeg = in[1] - 28;
	if (lonOffset)
	{
		lonDeg += 100;
	}
	if ((lonDeg >= 180) && (lonDeg <= 189))
	{
		lonDeg -= 80;
	}
	else if ((lonDeg >= 190) && (lonDeg <= 199))
	{
		lonDeg -= 190;
	}
	int lonMin = in[2] - 28;
	if (lonMin >= 60)
	{
		lonMin -= 60;
	}
	int lonHun = in[3] - 28;

	int latDeg = dd[0] * 10 + dd[1];
	int latMin = dd[2] * 10 + dd[3];
	int latHun = dd[4] * 10 + dd[5];
	if ((latDeg > 90) || (latMin > 59) || (lonDeg > 180) || (lonMin > 59) || (lonHun > 99))
	{
		return false;
	}
	p->latU = degMinToU(latDeg, latMin * 100 + latHun);
	p->lonU = degMinToU(lonDeg, lonMin * 100 + lonHun);
	if ((p->latU > 90000000) || (p->lonU > 180000000))
	{
		return false;
	}
	if (!north)
	{
		p->latU = -p->latU;
	}
	if (west)
	{
		p->lonU = -p->lonU;
	}
	return true;
}

static void setText(aprsPacket_t *p, const uint8_t *s, size_t n)
{
	(void)aprsDecodeText(s, n, p->text, sizeof(p->text));
}

/* ---- R13: символ і рух (курс/швидкість) ------------------------------------------------------------------------- */

/* «DDMM.hhN/DDDMM.hhW>»: таблиця s[8], код s[18]. */
static void p_symbol_uncompressed(aprsPacket_t *p, const uint8_t *s)
{
	p->symTable = (char)s[8];
	p->symCode = (char)s[18];
}

/* Стиснута: s[0] -- таблиця (або накладка a..j = цифри 0..9), s[9] -- код, s[10..12] -- cs T. Курс = c*4, швидкість = 1.08^s - 1 вузла;
 * T з типом "висота GGA" (біти 3..4 == 2) курсу/швидкості не дає; c == ' ' -- нема. */
static void p_symbol_compressed(aprsPacket_t *p, const uint8_t *s)
{
	uint8_t t = s[0];

	if ((t >= 'a') && (t <= 'j'))
	{
		t = (uint8_t)('0' + (t - 'a'));   /* накладка: a..j -> 0..9 */
	}
	p->symTable = (char)t;
	p->symCode = (char)s[9];
	/* R14 (Б2): порядок перевірок за специфікацією -- c == ' ' нема даних; тип-байт GGA -- стиснена ВИСОТА; c == '{' -- РАДІУС дії
	 * (а не курс 360 градусів); інакше курс/швидкість. */
	if ((s[10] == ' ') || (s[10] < 33U) || (s[11] < 33U) || (s[12] < 33U))
	{
		return;
	}
	if (((s[12] - 33U) & 0x18U) == 0x10U)
	{
		/* alt(фути) = 1.002^((c-33)*91 + (s-33)) */
		double ft = pow(1.002, (double)((s[10] - 33) * 91 + (s[11] - 33)));

		p->altM = (int32_t)(ft * 0.3048 + 0.5);
		p->hasAlt = true;
	}
	else if (s[10] == '{')
	{
		/* радіус, милі = 2 * 1.08^(s-33) */
		double mi = 2.0 * pow(1.08, (double)(s[11] - 33));

		p->rangeVal = (uint16_t)((mi > 65000.0) ? 65000 : (int)(mi + 0.5));
		p->rangeKm = false;
	}
	else if (s[10] <= 122U)
	{
		unsigned c = s[10] - 33U;
		unsigned sp = s[11] - 33U;

		if (c <= 89U)
		{
			double v = 1.0;

			p->course = (uint16_t)(c * 4U);   /* 0 -- "курсу нема" (0 і 360 не розрізняємо) */
			for (unsigned i = 0; (i < sp) && (i < 100U); i++)
			{
				v *= 1.08;
			}
			p->speedKn = (uint16_t)(v - 1.0 + 0.5);
		}
	}
}

/* Mic-E: info[4..6] = SP DC SE (+28), info[7] -- код символу, info[8] -- таблиця. */
static void p_micE_motion(aprsPacket_t *p, const uint8_t *in)
{
	p->symCode = (char)in[7];
	p->symTable = (char)in[8];
	if ((in[4] >= 28U) && (in[5] >= 28U) && (in[6] >= 28U))
	{
		unsigned sp = in[4] - 28U, dc = in[5] - 28U, se = in[6] - 28U;
		unsigned speed = sp * 10U + dc / 10U;
		unsigned course = (dc % 10U) * 100U + se;

		if (speed >= 800U)
		{
			speed -= 800U;
		}
		if (course >= 400U)
		{
			course -= 400U;
		}
		p->speedKn = (uint16_t)speed;
		p->course = (uint16_t)((course <= 360U) ? course : 0U);
	}
}

/* ---- R14: розширення коментаря --------------------------------------------------------------------------------- */

#define CS_MAXCUT   8U
#define CS_EXT7     0x01U   /* на початку коментаря може бути 7-байтове поле розширення (звичайна позиція, об'єкт, предмет) */

typedef struct
{
	uint16_t s[CS_MAXCUT];
	uint16_t l[CS_MAXCUT];
	uint8_t  n;
} csCuts_t;

static void csCut(csCuts_t *k, size_t s, size_t l)
{
	if ((k->n < CS_MAXCUT) && (l > 0U))
	{
		k->s[k->n] = (uint16_t)s;
		k->l[k->n] = (uint16_t)l;
		k->n++;
	}
}

static bool csCovered(const csCuts_t *k, size_t i)
{
	for (uint8_t j = 0; j < k->n; j++)
	{
		if ((i >= k->s[j]) && (i < ((size_t)k->s[j] + k->l[j])))
		{
			return true;
		}
	}
	return false;
}

/* Ціле з w цифр підряд; -1, якщо не вистачає байтів або не цифра. */
static int csNum(const uint8_t *c, size_t n, int w)
{
	int v = 0;

	if ((size_t)w > n)
	{
		return -1;
	}
	for (int i = 0; i < w; i++)
	{
		if (isDig(c[i]) == false)
		{
			return -1;
		}
		v = v * 10 + (c[i] - '0');
	}
	return v;
}

/* Поле розширення, 7 байт: "ddd/sss" (курс/швидкість; для погодної станції -- вітер у милях/год), "PHGphgd", "RNGnnnn", "DFSshgd".
 * Повертає, скільки байт з'їдено (7 або 0). */
static size_t csExt7(aprsPacket_t *p, const uint8_t *c, size_t n)
{
	if (n < 7U)
	{
		return 0U;
	}
	if (c[3] == '/')
	{
		int a = csNum(c, n, 3);
		int b = csNum(c + 4, n - 4U, 3);

		if ((a < 0) || (b < 0))
		{
			return 0U;
		}
		if (p->symCode == '_')
		{
			/* Б1: у погодній станції це ВІТЕР (мили/год), а не курс станції */
			p->windDeg = (uint16_t)((a <= 360) ? a : 0);
			p->windMph = (uint8_t)((b > 255) ? 255 : b);
			p->wxMask |= APRS_WX_WIND;
		}
		else
		{
			p->course = (uint16_t)((a <= 360) ? a : 0);
			p->speedKn = (uint16_t)b;
		}
		return 7U;
	}
	if ((memcmp(c, "PHG", 3) == 0) || (memcmp(c, "DFS", 3) == 0))
	{
		int v = csNum(c + 3, n - 3U, 4);

		if (v >= 0)
		{
			p->extKind = (c[0] == 'P') ? APRS_EXT_PHG : APRS_EXT_DFS;
			p->extVal = (uint16_t)(((v / 1000) << 12) | (((v / 100) % 10) << 8) | (((v / 10) % 10) << 4) | (v % 10));
			return 7U;
		}
		return 0U;
	}
	if (memcmp(c, "RNG", 3) == 0)
	{
		int v = csNum(c + 3, n - 3U, 4);

		if (v >= 0)
		{
			p->extKind = APRS_EXT_RNG;
			p->extVal = (uint16_t)v;
			return 7U;
		}
	}
	return 0U;
}

/* "nnn.nnnMHz" (10 байт) і необов'язкові " Tnnn"/" Toff"/" Cnnn", " +nnn"/" -nnn" (зсув у десятках кГц), " Rnnm"/" Rnnk". Повертає з'їдене. */
static size_t csFreq(aprsPacket_t *p, const uint8_t *c, size_t n)
{
	size_t at = 10U;

	if ((n < 10U) || (c[3] != '.') || (memcmp(c + 7, "MHz", 3) != 0))
	{
		return 0U;
	}
	int a = csNum(c, n, 3);
	int b = csNum(c + 4, n - 4U, 3);

	if ((a < 0) || (b < 0))
	{
		return 0U;
	}
	p->freqKHz = (uint32_t)a * 1000U + (uint32_t)b;
	if (((at + 5U) <= n) && (c[at] == ' ') && ((c[at + 1U] == 'T') || (c[at + 1U] == 'C') || (c[at + 1U] == 'D')) &&
			((memcmp(c + at + 2U, "off", 3) == 0) || (csNum(c + at + 2U, n - at - 2U, 3) >= 0)))
	{
		memcpy(p->tone, c + at + 1U, 4);
		p->tone[4] = 0;
		at += 5U;
	}
	if (((at + 5U) <= n) && (c[at] == ' ') && ((c[at + 1U] == '+') || (c[at + 1U] == '-')) && (csNum(c + at + 2U, n - at - 2U, 3) >= 0))
	{
		int v = csNum(c + at + 2U, n - at - 2U, 3);

		p->shiftKHz = (int16_t)(((c[at + 1U] == '-') ? -v : v) * 10);
		p->hasShift = true;
		at += 5U;
	}
	if (((at + 5U) <= n) && (c[at] == ' ') && (c[at + 1U] == 'R') && ((c[at + 4U] == 'm') || (c[at + 4U] == 'k')) && (csNum(c + at + 2U, n - at - 2U, 2) >= 0))
	{
		p->rangeVal = (uint16_t)csNum(c + at + 2U, n - at - 2U, 2);
		p->rangeKm = (c[at + 4U] == 'k');
		at += 5U;
	}
	return at;
}

/* Поле погоди: літера + цифри. Повертає ширину значення для відомих літер, 0 -- літера не погодна. */
static int csWxWidth(uint8_t l)
{
	switch (l)
	{
		case 'c': case 's': case 'g': case 'r': case 'p': case 'P': case 'L': case 'l': case '#': case 't': return 3;
		case 'h': return 2;
		case 'b': return 5;
		default:  return 0;
	}
}

/* Погодні поля: послідовність "літера + N цифр" підряд (невідома літера зупиняє розбір -- далі вільний текст/код ПЗ).
 * Значення "..." / пробіли ("немає даних") пропускаються. Повертає з'їдене. */
static size_t csWeather(aprsPacket_t *p, const uint8_t *c, size_t n)
{
	size_t i = 0;
	bool sawC = false;

	while (i < n)
	{
		int w = csWxWidth(c[i]);
		bool ok = true, num = true, neg = false;
		int v = 0;

		if ((w == 0) || ((i + 1U + (size_t)w) > n))
		{
			break;
		}
		for (int k = 0; k < w; k++)
		{
			uint8_t ch = c[i + 1U + (size_t)k];

			if (isDig(ch))
			{
				v = v * 10 + (ch - '0');
			}
			else if ((ch == '-') && (k == 0))
			{
				neg = true;
			}
			else if ((ch == '.') || (ch == ' '))
			{
				num = false;
			}
			else
			{
				ok = false;
			}
		}
		if (ok == false)
		{
			break;
		}
		if (num)
		{
			switch (c[i])
			{
				case 'c': p->windDeg = (uint16_t)((v <= 360) ? v : 0); p->wxMask |= APRS_WX_WIND; sawC = true; break;
				case 's': if (sawC) { p->windMph = (uint8_t)((v > 255) ? 255 : v); } break;   /* "s" після "c" -- швидкість вітру; сама по собі -- сніг */
				case 'g': p->gustMph = (uint8_t)((v > 255) ? 255 : v); p->wxMask |= APRS_WX_GUST; break;
				case 't':
				{
					int f = neg ? -v : v;

					p->tempC = (int16_t)(((f - 32) * 5 + (((f - 32) >= 0) ? 4 : -4)) / 9);   /* °F -> °C з округленням */
					p->wxMask |= APRS_WX_TEMP;
					break;
				}
				case 'h': p->humPct = (uint8_t)((v == 0) ? 100 : v); p->wxMask |= APRS_WX_HUM; break;   /* "h00" -- 100 % */
				case 'b': p->pressDhPa = (uint16_t)v; p->wxMask |= APRS_WX_PRESS; break;
				default: break;
			}
		}
		i += 1U + (size_t)w;
	}
	return i;
}

static bool csIsB91(uint8_t c)
{
	return (c >= 33U) && (c <= 123U);
}

/* '!DAO!': додаткова точність до мінут позиції. Велика літера датуму -- цифра = тисячні частки хвилини (1/60000 градуса ~ 16.7 мкград);
 * мала -- base91, (знак - 33) * 1.10 соту частку сотої хвилини (~ 1.83 мкград на одиницю). Пробіл -- точності нема. Знак -- від нуля (S/W -- у мінус). */
static void csDao(aprsPacket_t *p, uint8_t datum, uint8_t a, uint8_t o)
{
	int32_t la = 0, lo = 0;

	if ((datum >= 'A') && (datum <= 'Z'))
	{
		la = isDig(a) ? (((int32_t)(a - '0') * 1000 + 30) / 60) : 0;
		lo = isDig(o) ? (((int32_t)(o - '0') * 1000 + 30) / 60) : 0;
	}
	else if ((a >= 33U) && (a <= 123U) && (o >= 33U) && (o <= 123U))
	{
		la = ((int32_t)(a - 33U) * 11 + 3) / 6;
		lo = ((int32_t)(o - 33U) * 11 + 3) / 6;
	}
	p->latU += (p->latU < 0) ? -la : la;
	p->lonU += (p->lonU < 0) ? -lo : lo;
}

/* Витягти з коментаря розширення (за порядком специфікації: розширення, частота, погода; далі "/A=", телеметрія "|..|", "!DAO!" де завгодно),
 * решту -- чистий текст у cp1251 (aprsDecodeText) у out. c -- сирі байти коментаря (n байт). Один прохід; на стеку лише список вирізок
 * (8 x 4 Б). ';' як розділювач ніде не використовується (коментар може його містити). */
static void commentStrip(aprsPacket_t *p, const uint8_t *c, size_t n, char *out, size_t outSize, unsigned flags)
{
	csCuts_t k;
	size_t pos = 0;
	size_t o = 0;
	bool pendingCut = false;

	k.n = 0;
	if (outSize == 0U)
	{
		return;
	}
	/* R16 (ВА1): службові байти в кінці (CR 0x0D, LF 0x0A, усе < 0x20) -- не частина коментаря */
	while ((n > 0U) && (c[n - 1U] < 0x20U))
	{
		n--;
	}
	if (flags & CS_EXT7)
	{
		pos += csExt7(p, c, n);
	}
	pos += csFreq(p, c + pos, n - pos);
	if (p->symCode == '_')
	{
		pos += csWeather(p, c + pos, n - pos);
	}
	csCut(&k, 0, pos);

	for (size_t i = pos; i < n; i++)
	{
		if (csCovered(&k, i))
		{
			continue;
		}
		/* висота "/A=nnnnnn" (9 байт, у футах, може бути "/A=-00123") */
		if (((i + 9U) <= n) && (c[i] == '/') && (c[i + 1U] == 'A') && (c[i + 2U] == '=') && (isDig(c[i + 3U]) || (c[i + 3U] == '-')) &&
				(csNum(c + i + 4U, n - i - 4U, 5) >= 0))
		{
			long ft = (long)csNum(c + i + 4U, n - i - 4U, 5);

			if (c[i + 3U] == '-')
			{
				ft = -ft;
			}
			else
			{
				ft += (long)(c[i + 3U] - '0') * 100000L;
			}
			p->altM = (int32_t)((ft * 3048L + ((ft >= 0) ? 5000L : -5000L)) / 10000L);
			p->hasAlt = true;
			csCut(&k, i, 9U);
			i += 8U;
			continue;
		}
		/* телеметрія base91: '|' + 2..7 пар знаків + '|' */
		if (c[i] == '|')
		{
			size_t j = i + 1U;

			while ((j < n) && csIsB91(c[j]))
			{
				j++;
			}
			if ((j < n) && (c[j] == '|') && ((j - i - 1U) >= 4U) && ((j - i - 1U) <= 14U) && (((j - i - 1U) & 1U) == 0U))
			{
				csCut(&k, i, j - i + 1U);
				i = j;
				continue;
			}
		}
		/* '!DAO!' (5 байт): '!' датум точність точність '!' */
		if ((c[i] == '!') && ((i + 5U) <= n) && (c[i + 4U] == '!'))
		{
			uint8_t d = c[i + 1U];
			bool up = (d >= 'A') && (d <= 'Z');
			bool lo = (d >= 'a') && (d <= 'z');

			if ((up && (isDig(c[i + 2U]) || (c[i + 2U] == ' ')) && (isDig(c[i + 3U]) || (c[i + 3U] == ' '))) ||
					(lo && ((csIsB91(c[i + 2U]) && csIsB91(c[i + 3U])) || ((c[i + 2U] == ' ') && (c[i + 3U] == ' ')))))
			{
				csCut(&k, i, 5U);
				csDao(p, d, c[i + 2U], c[i + 3U]);
				i += 4U;
				continue;
			}
		}
	}

	/* зібрати решту: пропустити вирізки, не лишати подвійні пробіли на швах і пробіли на початку */
	for (size_t i = 0; (i < n) && (o + 1U < outSize); i++)
	{
		if (csCovered(&k, i))
		{
			pendingCut = true;
			continue;
		}
		if ((c[i] == ' ') && ((o == 0U) || (pendingCut && (out[o - 1U] == ' '))))
		{
			pendingCut = false;
			continue;
		}
		pendingCut = false;
		out[o++] = (char)c[i];
	}
	if (k.n > 0U)
	{
		while ((o > 0U) && (out[o - 1U] == ' '))
		{
			o--;   /* після вирізок на кінці лишається пробіл -- прибрати */
		}
	}
	/* не лишати обірваного UTF-8 на хвості (текст обрізано по місцю) */
	{
		size_t b = o;

		while ((b > 0U) && ((((uint8_t)out[b - 1U]) & 0xC0U) == 0x80U))
		{
			b--;
		}
		if ((b > 0U) && (((uint8_t)out[b - 1U]) >= 0xC0U))
		{
			uint8_t lead = (uint8_t)out[b - 1U];
			size_t need = (lead >= 0xF0U) ? 4U : ((lead >= 0xE0U) ? 3U : 2U);

			if ((o - (b - 1U)) < need)
			{
				o = b - 1U;
			}
		}
	}
	(void)aprsDecodeText((const uint8_t *)out, o, out, outSize);   /* на місці: результат не довший за вхід */
}

/* Поле позиції (звичайне 19 Б або стиснуте 13 Б) на s: координати, символ, курс/швидкість/висота/радіус зі стисненої. used -- довжина поля. */
static bool parsePosField(aprsPacket_t *p, const uint8_t *s, size_t rest, size_t *used)
{
	if (rest == 0U)
	{
		return false;
	}
	if (isDig(s[0]) || (s[0] == ' '))
	{
		if (!parseUncompressed(s, rest, p))
		{
			return false;
		}
		*used = 19U;
		p_symbol_uncompressed(p, s);
		return true;
	}
	if ((s[0] == '/') || (s[0] == '\\') || ((s[0] >= 'A') && (s[0] <= 'Z')) || ((s[0] >= 'a') && (s[0] <= 'j')))
	{
		if (!parseCompressed(s, rest, p))
		{
			return false;
		}
		p->compressed = true;
		*used = 13U;
		p_symbol_compressed(p, s);
		return true;
	}
	return false;
}

/* Ім'я об'єкта/предмета перед коментарем: збігається зі src -- не пишемо; знятий з обліку -- "[знято]" (cp1251, рядок з ескейпами, щоб
 * файл лишався ASCII). Результат: "ІМ'Я: ", "ІМ'Я [знято]: ", "[знято]: " або порожньо. Повертає довжину префікса в p->text. */
static size_t namePrefix(aprsPacket_t *p, const aprsAx25_t *ax, const uint8_t *nm, size_t nl, bool killed)
{
	char tmp[10];
	size_t l = (nl > 9U) ? 9U : nl;
	size_t o = 0;

	for (size_t i = 0; i < l; i++)
	{
		tmp[i] = ((nm[i] >= 0x20U) && (nm[i] < 0x7FU)) ? (char)nm[i] : '?';
	}
	while ((l > 0U) && (tmp[l - 1U] == ' '))
	{
		l--;
	}
	tmp[l] = 0;
	p->text[0] = 0;
	if ((l > 0U) && (strcmp(tmp, ax->src) != 0))
	{
		o = (size_t)snprintf(p->text, sizeof(p->text), "%s", tmp);
	}
	if (killed)
	{
		o += (size_t)snprintf(p->text + o, sizeof(p->text) - o, "%s[\xE7\xED\xFF\xF2\xEE]", (o > 0U) ? " " : "");
	}
	if (o > 0U)
	{
		o += (size_t)snprintf(p->text + o, sizeof(p->text) - o, ": ");
	}
	return (o < sizeof(p->text)) ? o : (sizeof(p->text) - 1U);
}

/* Об'єкт ';' (відмітка часу 7 байт) або предмет ')' (часу нема). true -- розібрано. */
static bool parseNamed(const aprsAx25_t *ax, aprsPacket_t *p, bool isObject)
{
	const uint8_t *in = ax->info;
	size_t n = ax->infoLen;
	size_t nameLen, at, used = 0, pre;
	const uint8_t *s;

	if (isObject)
	{
		if ((n < 31U) || ((in[10] != '*') && (in[10] != '_')))
		{
			return false;
		}
		for (int i = 11; i < 17; i++)
		{
			if (isDig(in[i]) == false)
			{
				return false;
			}
		}
		if ((in[17] != 'z') && (in[17] != 'h') && (in[17] != '/'))
		{
			return false;
		}
		nameLen = 9U;
		p->killed = (in[10] == '_');
		at = 18U;
	}
	else
	{
		size_t t = 0;

		for (size_t i = 4U; (i < n) && (i <= 10U); i++)
		{
			if ((in[i] == '!') || (in[i] == '_'))
			{
				t = i;
				break;
			}
		}
		if ((t == 0U) || (n < (t + 1U + 13U)))
		{
			return false;
		}
		nameLen = t - 1U;
		p->killed = (in[t] == '_');
		at = t + 1U;
	}
	s = in + at;
	if (!parsePosField(p, s, n - at, &used))
	{
		return false;
	}
	pre = namePrefix(p, ax, in + 1, nameLen, p->killed);
	commentStrip(p, s + used, n - at - used, p->text + pre, sizeof(p->text) - pre, p->compressed ? 0U : CS_EXT7);
	return true;
}

/* R16 (ВА2/ВА3): ідентифікатор пристрою Mic-E у коментарі (aprsorg/aprs-deviceid, "Mic-E index").
 * НОВИЙ формат: перший байт '`' (пристрій з повідомленнями) або '\'' (тракер), далі справжній коментар, у кінці ДВА байти-ідентифікатори.
 * СТАРИЙ (Kenwood): перший байт '>' або ']', у кінці ОДИН байт-ідентифікатор або нічого (якщо останній не буква і не цифра -- це він).
 * Повертає TRUE, якщо префікс знайдено; *start / *end -- межі справжнього коментаря всередині c[0..n). */
static bool micEDeviceId(const uint8_t *c, size_t n, size_t *start, size_t *end)
{
	*start = 0U;
	*end = n;
	if (n == 0U)
	{
		return false;
	}
	if ((c[0] == '`') || (c[0] == '\''))
	{
		*start = 1U;
		*end = (n >= 3U) ? (n - 2U) : 1U;   /* коротше за префікс + 2 -- коментаря нема */
		return true;
	}
	if ((c[0] == '>') || (c[0] == ']'))
	{
		uint8_t l = c[n - 1U];

		*start = 1U;
		if ((n >= 2U) && !isDig(l) && !(((l >= 'A') && (l <= 'Z')) || ((l >= 'a') && (l <= 'z'))))
		{
			*end = n - 1U;
		}
		return true;
	}
	return false;
}

/* Mic-E: висота "xxx}" (3 знаки base91 + '}'). Шукаємо '}' у перших 8 байтах c (c -- те, що лишилось після зняття префікса). Байти перед висотою
 * (їх у реальних кадрах нема) вважаємо службовими й відкидаємо. Без префікса -- лише з початку (як раніше). Повертає, скільки байт з початку c зайнято. */
static size_t micEAlt(aprsPacket_t *p, const uint8_t *c, size_t n, bool hadPrefix)
{
	size_t last = hadPrefix ? 7U : 3U;

	for (size_t j = 3U; (j <= last) && (j < n); j++)
	{
		if ((c[j] == '}') && csIsB91(c[j - 3U]) && csIsB91(c[j - 2U]) && csIsB91(c[j - 1U]))
		{
			long v = (long)(c[j - 3U] - 33U) * 8281L + (long)(c[j - 2U] - 33U) * 91L + (long)(c[j - 1U] - 33U) - 10000L;

			p->altM = (int32_t)v;
			p->hasAlt = true;
			return j + 1U;
		}
	}
	return 0U;
}

/* Коментар Mic-E: порядок -- керівні байти в кінці (ВА1), префікс/суфікс пристрою (ВА2/ВА3), потім висота й інші розширення (ВА4). */
static void micEComment(aprsPacket_t *out, const uint8_t *c, size_t n)
{
	size_t st, en, alt;
	bool pre;

	while ((n > 0U) && (c[n - 1U] < 0x20U))
	{
		n--;
	}
	pre = micEDeviceId(c, n, &st, &en);
	alt = micEAlt(out, c + st, en - st, pre);
	commentStrip(out, c + st + alt, en - st - alt, out->text, sizeof(out->text), 0U);
}

/* Текст повідомлення -- спрямований запит ("?APRS?", "?APRSP", "?PING?", "?IGATE?", "?WX?": '?' + ВЕЛИКІ літери/цифри) або метадані телеметрії
 * ("PARM.", "UNIT.", "EQNS.", "BITS."). Людське "?де ти?" (малі літери) запитом не вважається. */
static bool msgIsQueryOrMeta(const uint8_t *t, size_t n)
{
	if ((n >= 5U) && ((memcmp(t, "PARM.", 5) == 0) || (memcmp(t, "UNIT.", 5) == 0) || (memcmp(t, "EQNS.", 5) == 0) || (memcmp(t, "BITS.", 5) == 0)))
	{
		return true;
	}
	if ((n >= 2U) && (t[0] == '?'))
	{
		size_t i = 1;

		while ((i < n) && (((t[i] >= 'A') && (t[i] <= 'Z')) || isDig(t[i])))
		{
			i++;
		}
		return (i >= 3U) && ((i == n) || (t[i] == '?') || (t[i] == ' ') || (t[i] == '{'));
	}
	return false;
}

/* Повідомлення: ":" + адресат(9, пробіли) + ":" + текст [+ "{номер"] */
static void parseMessage(const aprsAx25_t *ax, aprsPacket_t *p)
{
	const uint8_t *in = ax->info;
	size_t n = ax->infoLen;

	if ((n < 11U) || (in[10] != ':'))
	{
		return;   /* лишається APRS_T_OTHER */
	}
	if (msgIsQueryOrMeta(in + 11, n - 11U))
	{
		return;   /* R14: запит ("?APRS?") або метадані телеметрії -- не повідомлення: без ACK, у чат не потрапляє, текст видно як «інше» */
	}
	size_t k = 0;
	for (size_t i = 0; i < 9U; i++)
	{
		uint8_t c = in[1U + i];
		if ((c >= 'a') && (c <= 'z'))
		{
			c = (uint8_t)(c - 'a' + 'A');
		}
		if ((c < 0x20U) || (c > 0x7EU))
		{
			return;
		}
		p->msgTo[k++] = (char)c;
	}
	while ((k > 0U) && (p->msgTo[k - 1U] == ' '))
	{
		k--;
	}
	p->msgTo[k] = 0;
	if (k == 0U)
	{
		return;
	}
	p->type = APRS_T_MESSAGE;

	const uint8_t *t = in + 11;
	size_t tl = n - 11U;

	/* номер повідомлення: останній '{' не далі 6 байтів від кінця, далі -- не порожньо й без пробілів */
	for (size_t i = tl; i > 0U; i--)
	{
		if (t[i - 1U] == '{')
		{
			size_t idl = tl - i;
			if ((idl >= 1U) && (idl <= 5U))
			{
				memcpy(p->msgId, &t[i], idl);
				p->msgId[idl] = 0;
				tl = i - 1U;
			}
			break;
		}
		if ((tl - i) > 5U)
		{
			break;
		}
	}
	/* ack/rej: «ack12», «rej12» без номера повідомлення */
	if ((p->msgId[0] == 0) && (tl >= 4U) && (tl <= 8U) &&
			((memcmp(t, "ack", 3) == 0) || (memcmp(t, "rej", 3) == 0)))
	{
		p->msgAck = true;
	}
	setText(p, t, tl);
}

/* ---- R14 етап 3: сирий NMEA ('$GPRMC', '$GPGGA') і Maidenhead-грід '[IO91SX]' ----------------------------------------------------- */

/* NMEA: поле n (0 -- назва речення) без копіювання; false -- поля нема. */
static bool nmeaField(const uint8_t *s, size_t len, unsigned n, const uint8_t **f, size_t *fl)
{
	size_t i = 0;

	for (unsigned k = 0; k < n; k++)
	{
		while ((i < len) && (s[i] != ','))
		{
			i++;
		}
		if (i >= len)
		{
			return false;
		}
		i++;
	}
	*f = s + i;
	*fl = 0;
	while (((i + *fl) < len) && (s[i + *fl] != ','))
	{
		(*fl)++;
	}
	return true;
}

/* "ddmm.mmmm" (або dddmm.mmmm) + N/S/E/W -> мікроградуси; degDigits 2 або 3. */
static bool nmeaCoord(const uint8_t *f, size_t fl, const uint8_t *h, size_t hl, unsigned degDigits, int32_t *out)
{
	long deg = 0, minx = 0;
	unsigned dec = 0;
	size_t i = degDigits;
	bool dot = false;

	if ((fl < (size_t)(degDigits + 3U)) || (hl != 1U))
	{
		return false;
	}
	for (size_t k = 0; k < degDigits; k++)
	{
		if (isDig(f[k]) == false) { return false; }
		deg = deg * 10 + (f[k] - '0');
	}
	if ((isDig(f[i]) == false) || (isDig(f[i + 1U]) == false))
	{
		return false;
	}
	minx = (f[i] - '0') * 10 + (f[i + 1U] - '0');
	for (i += 2U; i < fl; i++)
	{
		if ((f[i] == '.') && (dot == false))
		{
			dot = true;
		}
		else if (dot && isDig(f[i]))
		{
			if (dec < 4U)
			{
				minx = minx * 10 + (f[i] - '0');
				dec++;
			}
		}
		else
		{
			return false;
		}
	}
	while (dec < 4U)
	{
		minx *= 10;
		dec++;
	}
	/* хвилини * 10000 -> мікроградуси: (minx / 1e4) * 1e6 / 60 = minx * 5 / 3 */
	long v = deg * 1000000L + (minx * 5L + 1L) / 3L;
	if (((h[0] != 'N') && (h[0] != 'S') && (h[0] != 'E') && (h[0] != 'W')) || (v > ((degDigits == 2U) ? 90000000L : 180000000L)))
	{
		return false;
	}
	*out = (int32_t)(((h[0] == 'S') || (h[0] == 'W')) ? -v : v);
	return true;
}

/* Число з десятковою крапкою (до 3 знаків) -> округлене ціле. */
static bool nmeaNum(const uint8_t *f, size_t fl, long *out)
{
	long v = 0;
	size_t i = 0;
	bool neg = false;

	if ((fl > 0U) && (f[0] == '-'))
	{
		neg = true;
		i = 1U;
	}
	if (i >= fl)
	{
		return false;
	}
	for (; (i < fl) && isDig(f[i]); i++)
	{
		v = v * 10 + (f[i] - '0');
	}
	if ((i < fl) && (f[i] == '.'))
	{
		if (((i + 1U) < fl) && isDig(f[i + 1U]) && ((f[i + 1U] - '0') >= 5))
		{
			v++;
		}
		i = fl;
	}
	if (i != fl)
	{
		return false;
	}
	*out = neg ? -v : v;
	return true;
}

/* '$GPRMC' / '$GPGGA' (талкер будь-який: другий символ -- літера) з перевіркою контрольної суми '*hh'. true -- позицію взято. */
static bool parseNmea(const aprsAx25_t *ax, aprsPacket_t *p)
{
	const uint8_t *in = ax->info;
	size_t n = ax->infoLen;
	const uint8_t *f1, *f2, *f3, *f4;
	size_t l1, l2, l3, l4;
	size_t star = 0;
	uint8_t x = 0;
	bool rmc;
	long v;

	if ((n < 20U) || (in[1] != 'G') || (in[2] < 'A') || (in[2] > 'Z') || (in[6] != ','))
	{
		return false;
	}
	for (size_t i = 1; i < n; i++)
	{
		if (in[i] == '*')
		{
			star = i;
			break;
		}
		x ^= in[i];
	}
	if ((star == 0U) || ((star + 3U) > n))
	{
		return false;
	}
	{
		int h1 = (in[star + 1U] >= 'a') ? (in[star + 1U] - 'a' + 10) : ((in[star + 1U] >= 'A') ? (in[star + 1U] - 'A' + 10) : (in[star + 1U] - '0'));
		int h2 = (in[star + 2U] >= 'a') ? (in[star + 2U] - 'a' + 10) : ((in[star + 2U] >= 'A') ? (in[star + 2U] - 'A' + 10) : (in[star + 2U] - '0'));

		if ((h1 < 0) || (h1 > 15) || (h2 < 0) || (h2 > 15) || (((h1 << 4) | h2) != x))
		{
			return false;   /* контрольна сума не збіглась */
		}
	}
	rmc = (memcmp(in + 3, "RMC", 3) == 0);
	if ((rmc == false) && (memcmp(in + 3, "GGA", 3) != 0))
	{
		return false;
	}
	{
		const uint8_t *s = in + 1;
		size_t len = star - 1U;
		const uint8_t *fv;
		size_t lv;

		if (rmc)
		{
			/* 0 name, 1 time, 2 status, 3 lat, 4 N/S, 5 lon, 6 E/W, 7 speed(kn), 8 course */
			if ((nmeaField(s, len, 2, &fv, &lv) == false) || (lv != 1U) || (fv[0] != 'A'))
			{
				return false;
			}
			if ((nmeaField(s, len, 3, &f1, &l1) == false) || (nmeaField(s, len, 4, &f2, &l2) == false) ||
					(nmeaField(s, len, 5, &f3, &l3) == false) || (nmeaField(s, len, 6, &f4, &l4) == false))
			{
				return false;
			}
		}
		else
		{
			/* 0 name, 1 time, 2 lat, 3 N/S, 4 lon, 5 E/W, 6 quality, 7 sats, 8 hdop, 9 alt, 10 M */
			if ((nmeaField(s, len, 6, &fv, &lv) == false) || (lv != 1U) || (fv[0] == '0'))
			{
				return false;
			}
			if ((nmeaField(s, len, 2, &f1, &l1) == false) || (nmeaField(s, len, 3, &f2, &l2) == false) ||
					(nmeaField(s, len, 4, &f3, &l3) == false) || (nmeaField(s, len, 5, &f4, &l4) == false))
			{
				return false;
			}
		}
		if ((nmeaCoord(f1, l1, f2, l2, 2U, &p->latU) == false) || (nmeaCoord(f3, l3, f4, l4, 3U, &p->lonU) == false))
		{
			return false;
		}
		if (rmc)
		{
			if (nmeaField(s, len, 7, &fv, &lv) && nmeaNum(fv, lv, &v) && (v >= 0))
			{
				p->speedKn = (uint16_t)((v > 999) ? 999 : v);
			}
			if (nmeaField(s, len, 8, &fv, &lv) && nmeaNum(fv, lv, &v) && (v > 0) && (v <= 360))
			{
				p->course = (uint16_t)v;
			}
		}
		else if (nmeaField(s, len, 9, &fv, &lv) && nmeaNum(fv, lv, &v))
		{
			p->altM = (int32_t)v;
			p->hasAlt = true;
		}
	}
	snprintf(p->text, sizeof(p->text), "NMEA G%c%s", (char)in[2], rmc ? "RMC" : "GGA");
	return true;
}

/* Maidenhead '[IO91SX]' / '[IO91]': центр квадрата (4 знаки -- 2 x 1 град., 6 знаків -- 5' x 2.5'). */
static bool parseGrid(const aprsAx25_t *ax, aprsPacket_t *p)
{
	const uint8_t *in = ax->info;
	size_t n = ax->infoLen;
	uint8_t g[6];
	size_t gl;
	int32_t lon, lat;

	if (n < 5U)
	{
		return false;
	}
	for (size_t i = 0; i < 4U; i++)
	{
		g[i] = in[1U + i];
		if (i < 2U)
		{
			if ((g[i] >= 'a') && (g[i] <= 'z')) { g[i] = (uint8_t)(g[i] - 'a' + 'A'); }
			if ((g[i] < 'A') || (g[i] > 'R')) { return false; }
		}
		else if (isDig(g[i]) == false)
		{
			return false;
		}
	}
	gl = 4U;
	if ((n >= 7U) && (in[5] != ']'))
	{
		g[4] = in[5];
		g[5] = in[6];
		for (size_t i = 4; i < 6U; i++)
		{
			if ((g[i] >= 'a') && (g[i] <= 'z')) { g[i] = (uint8_t)(g[i] - 'a' + 'A'); }
			if ((g[i] < 'A') || (g[i] > 'X')) { return false; }
		}
		gl = 6U;
	}
	lon = -180000000 + (int32_t)(g[0] - 'A') * 20000000 + (int32_t)(g[2] - '0') * 2000000;
	lat = -90000000 + (int32_t)(g[1] - 'A') * 10000000 + (int32_t)(g[3] - '0') * 1000000;
	if (gl == 4U)
	{
		lon += 1000000;
		lat += 500000;
	}
	else
	{
		lon += (int32_t)(g[4] - 'A') * 83333 + 41667;   /* підквадрат 5' = 1/12 градуса */
		lat += (int32_t)(g[5] - 'A') * 41667 + 20833;   /* 2.5' = 1/24 градуса */
	}
	p->lonU = lon;
	p->latU = lat;
	snprintf(p->text, sizeof(p->text), "grid %.*s", (int)gl, (const char *)g);
	return true;
}

/* R14: погода без позиції ("_" + MMDDHHMM + поля) -- розібрані поля текстом ("25C 50% 1026.5hPa w310/6km/h g10"), далі хвіст (код ПЗ). */
static void wxText(aprsPacket_t *p, const uint8_t *rest, size_t rn)
{
	char *t = p->text;
	size_t cap = sizeof(p->text);
	size_t o = 0;

	t[0] = 0;
	if (p->wxMask & APRS_WX_TEMP)
	{
		o += (size_t)snprintf(t + o, cap - o, "%dC ", (int)p->tempC);
	}
	if (p->wxMask & APRS_WX_HUM)
	{
		o += (size_t)snprintf(t + o, cap - o, "%u%% ", (unsigned)p->humPct);
	}
	if (p->wxMask & APRS_WX_PRESS)
	{
		o += (size_t)snprintf(t + o, cap - o, "%u.%uhPa ", (unsigned)(p->pressDhPa / 10U), (unsigned)(p->pressDhPa % 10U));
	}
	if (p->wxMask & APRS_WX_WIND)
	{
		o += (size_t)snprintf(t + o, cap - o, "w%u/%ukm/h ", (unsigned)p->windDeg, (unsigned)(((unsigned long)p->windMph * 1609UL + 500UL) / 1000UL));
	}
	if (p->wxMask & APRS_WX_GUST)
	{
		o += (size_t)snprintf(t + o, cap - o, "g%u ", (unsigned)(((unsigned long)p->gustMph * 1609UL + 500UL) / 1000UL));
	}
	for (size_t i = 0; (i < rn) && ((o + 1U) < cap); i++)
	{
		t[o++] = ((rest[i] >= 0x20U) && (rest[i] < 0x7FU)) ? (char)rest[i] : ' ';
	}
	while ((o > 0U) && (t[o - 1U] == ' '))
	{
		o--;
	}
	t[(o < cap) ? o : (cap - 1U)] = 0;
}

void aprsPacketParse(const aprsAx25_t *ax, aprsPacket_t *out)
{
	memset(out, 0, sizeof(*out));
	out->type = APRS_T_OTHER;
	if ((ax->info == NULL) || (ax->infoLen == 0U))
	{
		return;
	}
	const uint8_t *in = ax->info;
	size_t n = ax->infoLen;
	uint8_t c = in[0];

	/* R14: для усього, що не розібрано (тип «інше»), у картці видно сире інфополе -- це і є діагностика */
	setText(out, in, n);

	switch (c)
	{
		case '!':
		case '=':
		case '/':
		case '@':
		{
			size_t at = ((c == '/') || (c == '@')) ? 8U : 1U;   /* з відміткою часу: ще 7 символів */
			size_t used = 0;

			if (n <= at)
			{
				return;
			}
			if (parsePosField(out, in + at, n - at, &used) == false)
			{
				return;   /* "!!" (Ultimeter) та інше -- «інше» із сирим текстом */
			}
			out->type = APRS_T_POSITION;
			out->hasPos = true;
			commentStrip(out, in + at + used, n - at - used, out->text, sizeof(out->text), out->compressed ? 0U : CS_EXT7);
			break;
		}

		case ';':
			if (parseNamed(ax, out, true))
			{
				out->type = APRS_T_POSITION;
				out->hasPos = true;
			}
			break;

		case ')':
			if (parseNamed(ax, out, false))
			{
				out->type = APRS_T_POSITION;
				out->hasPos = true;
			}
			break;

		case '`':
		case '\'':
		case 0x1C:
		case 0x1D:
			if (parseMicE(ax, out))
			{
				out->type = APRS_T_POSITION;
				out->hasPos = true;
				out->micE = true;
				p_micE_motion(out, in);   /* R13: символ, курс, швидкість */
				micEComment(out, in + 9, n - 9U);   /* R16 (ВА): ідентифікатор пристрою, висота "xxx}", решта коментаря */
			}
			break;

		case ':':
			parseMessage(ax, out);
			break;

		case '_':
			/* погода без позиції: позиції нема -- тип лишається «інше» (вікно маяка не відкривається), але поля розбираємо в текст */
			if ((n > 9U) && isDig(in[1]) && isDig(in[2]) && isDig(in[3]) && isDig(in[4]) && isDig(in[5]) && isDig(in[6]) && isDig(in[7]) && isDig(in[8]))
			{
				size_t used = csWeather(out, in + 9, n - 9U);

				if (out->wxMask != 0U)
				{
					wxText(out, in + 9 + used, n - 9U - used);
				}
			}
			break;

		case '$':
			if (parseNmea(ax, out))
			{
				out->type = APRS_T_POSITION;
				out->hasPos = true;
			}
			break;

		case '[':
			if (parseGrid(ax, out))
			{
				out->type = APRS_T_POSITION;
				out->hasPos = true;
			}
			break;

		case '<':
			/* можливості станції (Direwolf IBEACON: "<IGATE,MSG_CNT=0,...") */
			out->type = APRS_T_STATUS;
			setText(out, in + 1, n - 1U);
			break;

		case '>':
		{
			size_t at = 1U;

			/* необов'язкова відмітка часу «DDHHMMz» */
			if ((n >= 8U) && isDig(in[1]) && isDig(in[2]) && isDig(in[3]) && isDig(in[4]) && isDig(in[5]) && isDig(in[6]) && (in[7] == 'z'))
			{
				at = 8U;
			}
			out->type = APRS_T_STATUS;
			setText(out, in + at, n - at);
			break;
		}

		default:
			break;   /* решта DTI -- «інше» із сирим текстом */
	}
}

bool aprsMsgIsForUs(const char *msgTo, const char *ownCall, uint8_t ownSsid)
{
	char want[APRS_CALL_LEN];
	size_t k = 0;

	for (size_t i = 0; (ownCall[i] != 0) && (i < 6U); i++)
	{
		char c = ownCall[i];
		if ((c >= 'a') && (c <= 'z'))
		{
			c = (char)(c - 'a' + 'A');
		}
		if (c == ' ')
		{
			break;
		}
		want[k++] = c;
	}
	if ((k == 0U) || (ownSsid > 15U))
	{
		return false;
	}
	want[k] = 0;

	char full[APRS_CALL_LEN + 3];
	strcpy(full, want);
	if (ownSsid != 0U)
	{
		size_t l = strlen(full);
		full[l++] = '-';
		if (ownSsid >= 10U)
		{
			full[l++] = '1';
			full[l++] = (char)('0' + (ownSsid - 10U));
		}
		else
		{
			full[l++] = (char)('0' + ownSsid);
		}
		full[l] = 0;
	}
	if (strcmp(msgTo, full) == 0)
	{
		return true;
	}
	if (ownSsid == 0U)
	{
		char z[APRS_CALL_LEN + 3];
		snprintf(z, sizeof(z), "%s-0", want);
		return (strcmp(msgTo, z) == 0);
	}
	return false;
}

/* ===================================================================================== */
/* Географія                                                                              */
/* ===================================================================================== */

#define APRS_DEG_TO_RAD   0.017453292519943295
#define APRS_EARTH_R_M    6372795.0     /* як у uiUtilities.c distanceBetweenTwoCoords() */

void aprsGeo(int32_t latAU, int32_t lonAU, int32_t latBU, int32_t lonBU, uint32_t *distM, uint16_t *bearingDeg)
{
	double lat1 = (double)latAU * 1e-6 * APRS_DEG_TO_RAD;
	double lat2 = (double)latBU * 1e-6 * APRS_DEG_TO_RAD;
	double dlon = ((double)lonBU - (double)lonAU) * 1e-6 * APRS_DEG_TO_RAD;
	double s1 = sin(lat1), c1 = cos(lat1), s2 = sin(lat2), c2 = cos(lat2);
	double sd = sin(dlon), cd = cos(dlon);

	/* відстань: формула Ловерінга/Ламерса, як distanceBetweenTwoCoords() (стійка до малих відстаней) */
	double a = c1 * s2 - s1 * c2 * cd;
	double b = c2 * sd;
	double num = sqrt(a * a + b * b);
	double den = s1 * s2 + c1 * c2 * cd;
	double ang = atan2(num, den);
	double m = ang * APRS_EARTH_R_M;
	*distM = (m < 0.0) ? 0U : (uint32_t)(m + 0.5);

	/* азимут: як courseTo() */
	double y = sd * c2;
	double x = c1 * s2 - s1 * c2 * cd;
	double brg = atan2(y, x) / APRS_DEG_TO_RAD;
	if (brg < 0.0)
	{
		brg += 360.0;
	}
	int ib = (int)(brg + 0.5);
	*bearingDeg = (uint16_t)(ib % 360);
}

const char *aprsBearingName(uint16_t deg)
{
	static const char *const names[8] = { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };

	return names[((deg % 360U) * 2U + 45U) / 90U % 8U];
}

/* ===================================================================================== */
/* Дедуплікація й список станцій                                                          */
/* ===================================================================================== */

static uint32_t fnv(uint32_t h, const uint8_t *p, size_t n)
{
	for (size_t i = 0; i < n; i++)
	{
		h ^= p[i];
		h *= 16777619UL;
	}
	return h;
}

static uint32_t hashSrcInfo(const aprsAx25_t *ax)
{
	uint32_t h = 2166136261UL;

	h = fnv(h, (const uint8_t *)ax->src, strlen(ax->src) + 1U);
	return fnv(h, ax->info, ax->infoLen);
}

void aprsDbInit(aprsRxDb_t *db)
{
	memset(db, 0, sizeof(*db));
}

bool aprsDbIsDuplicate(aprsRxDb_t *db, const aprsAx25_t *ax, uint32_t nowMs)
{
	uint32_t h = hashSrcInfo(ax);

	for (int i = 0; i < APRS_DEDUP_SLOTS; i++)
	{
		if ((db->dedup[i].ms != 0U) && (db->dedup[i].hash == h) && ((uint32_t)(nowMs - db->dedup[i].ms) <= APRS_DEDUP_MS))
		{
			db->dups++;
			return true;
		}
	}
	db->dedup[db->dedupNext].hash = h;
	db->dedup[db->dedupNext].ms = (nowMs != 0U) ? nowMs : 1U;
	db->dedupNext = (uint8_t)((db->dedupNext + 1U) % APRS_DEDUP_SLOTS);
	return false;
}

bool aprsDbMsgSeen(aprsRxDb_t *db, const aprsAx25_t *ax, const aprsPacket_t *pkt, uint32_t nowMs)
{
	uint32_t h = hashSrcInfo(ax);

	(void)pkt;
	for (int i = 0; i < APRS_MSG_SEEN_SLOTS; i++)
	{
		if ((db->seen[i].ms != 0U) && (db->seen[i].hash == h) && ((uint32_t)(nowMs - db->seen[i].ms) <= APRS_MSG_SEEN_MS))
		{
			return true;
		}
	}
	db->seen[db->seenNext].hash = h;
	db->seen[db->seenNext].ms = (nowMs != 0U) ? nowMs : 1U;
	db->seenNext = (uint8_t)((db->seenNext + 1U) % APRS_MSG_SEEN_SLOTS);
	return false;
}

static void copyTrunc(char *dst, size_t dstSize, const char *src)
{
	size_t n = strlen(src);

	if (n >= dstSize)
	{
		n = dstSize - 1U;
	}
	memcpy(dst, src, n);
	dst[n] = 0;
}

aprsStation_t *aprsDbUpdate(aprsRxDb_t *db, const aprsAx25_t *ax, const aprsPacket_t *pkt, uint32_t nowMs)
{
	aprsStation_t *s = NULL;
	aprsStation_t *freeSlot = NULL;
	aprsStation_t *oldest = NULL;
	uint32_t oldestAge = 0;

	for (int i = 0; i < APRS_STATIONS_MAX; i++)
	{
		aprsStation_t *c = &db->st[i];

		if (c->call[0] == 0)
		{
			if (freeSlot == NULL)
			{
				freeSlot = c;
			}
			continue;
		}
		if (strcmp(c->call, ax->src) == 0)
		{
			s = c;
			break;
		}
		uint32_t age = (uint32_t)(nowMs - c->lastMs);
		if ((oldest == NULL) || (age > oldestAge))
		{
			oldest = c;
			oldestAge = age;
		}
	}

	if (s == NULL)
	{
		/* нова станція: вільний запис, а коли їх нема -- НАЙСТАРІШИЙ (найбільший вік) */
		s = (freeSlot != NULL) ? freeSlot : oldest;
		memset(s, 0, sizeof(*s));
		copyTrunc(s->call, sizeof(s->call), ax->src);
	}

	s->type = pkt->type;
	s->lastMs = nowMs;
	if (s->count < 0xFFFFU)
	{
		s->count++;
	}
	copyTrunc(s->path, sizeof(s->path), ax->path);
	if (ax->tp)
	{
		s->flags |= APRS_ST_TP;
	}
	else
	{
		s->flags &= (uint8_t)~APRS_ST_TP;
	}
	if (pkt->hasPos)
	{
		s->flags |= APRS_ST_HASPOS;
		s->latU = pkt->latU;
		s->lonU = pkt->lonU;
		if (pkt->micE)
		{
			s->flags |= APRS_ST_MICE;
		}
		else
		{
			s->flags &= (uint8_t)~APRS_ST_MICE;
		}
	}
	if (pkt->text[0] != 0)
	{
		copyTrunc(s->text, sizeof(s->text), pkt->text);
	}
	return s;
}

int aprsDbCount(const aprsRxDb_t *db)
{
	int n = 0;

	for (int i = 0; i < APRS_STATIONS_MAX; i++)
	{
		if (db->st[i].call[0] != 0)
		{
			n++;
		}
	}
	return n;
}

const aprsStation_t *aprsDbNth(const aprsRxDb_t *db, int n, uint32_t nowMs)
{
	const aprsStation_t *prev = NULL;
	uint32_t prevAge = 0;

	if (n < 0)
	{
		return NULL;
	}
	for (int rank = 0; rank <= n; rank++)
	{
		const aprsStation_t *best = NULL;
		uint32_t bestAge = 0;

		for (int i = 0; i < APRS_STATIONS_MAX; i++)
		{
			const aprsStation_t *c = &db->st[i];

			if (c->call[0] == 0)
			{
				continue;
			}
			uint32_t age = (uint32_t)(nowMs - c->lastMs);
			/* наступний за новизною: вік не менший за попередній, а серед рівних -- вищий індекс за вже взяті */
			if ((prev != NULL) && ((age < prevAge) || ((age == prevAge) && (c <= prev))))
			{
				continue;
			}
			if ((best == NULL) || (age < bestAge))
			{
				best = c;
				bestAge = age;
			}
		}
		if (best == NULL)
		{
			return NULL;
		}
		prev = best;
		prevAge = bestAge;
	}
	return prev;
}

/* ===================================================================================== */
/* R13: вікно маяка                                                                       */
/* ===================================================================================== */

bool aprsBeaconWindowWanted(aprsBcnWinMode_t mode, const aprsPacket_t *pkt, bool isNewStation)
{
	if ((pkt == NULL) || (pkt->type != APRS_T_POSITION))
	{
		return false;
	}
	switch (mode)
	{
		case APRS_BCNWIN_OFF:
			return false;
		case APRS_BCNWIN_NEW:
			return isNewStation;
		case APRS_BCNWIN_ALL:
		default:
			return true;
	}
}

static int16_t iround(double v)
{
	return (int16_t)(v + ((v >= 0.0) ? 0.5 : -0.5));
}

void aprsArrowGeom(aprsArrow_t *a, int16_t cx, int16_t cy, int16_t len, uint16_t bearingDeg)
{
	const double rad = 0.017453292519943295;
	double b = (double)(bearingDeg % 360U) * rad;
	double dx = sin(b);
	double dy = -cos(b);              /* екран: y росте вниз, північ -- угору */
	double wl = (double)len * 0.4;
	double wa = 28.0 * rad;
	double ca = cos(wa), sa = sin(wa);

	if (wl < 4.0)
	{
		wl = 4.0;
	}
	a->tx = (int16_t)iround((double)cx + dx * (double)len);
	a->ty = (int16_t)iround((double)cy + dy * (double)len);
	/* напрям "назад" від вістря = (-dx,-dy), повернутий на +-wa */
	a->lx = (int16_t)iround((double)a->tx + (-dx * ca - (-dy) * sa) * wl);
	a->ly = (int16_t)iround((double)a->ty + (-dx * sa + (-dy) * ca) * wl);
	a->rx = (int16_t)iround((double)a->tx + (-dx * ca + (-dy) * sa) * wl);
	a->ry = (int16_t)iround((double)a->ty + (dx * sa + (-dy) * ca) * wl);
}

void aprsArrowPoly(aprsArrowPoly_t *p, int16_t cx, int16_t cy, int16_t len, uint16_t bearingDeg)
{
	const double rad = 0.017453292519943295;
	const double b = (double)(bearingDeg % 360U) * rad;
	const double dx = sin(b);
	const double dy = -cos(b);        /* вісь стрілки на екрані (y вниз, північ угору) */
	const double px = -dy;            /* перпендикуляр: вісь, повернута на +90° */
	const double py = dx;
	double hl = (double)len * 0.4;    /* довжина вістря */
	const double hw = 5.0;            /* півширина вістря */
	const double sw = 2.0;            /* півширина стрижня (4 px) */
	double s;
	/* (u, v) -> екран; пари для трикутників: стрижень (0,-sw)(s,-sw)(s,sw) і (0,-sw)(s,sw)(0,sw); вістря (s,-hw)(len,0)(s,hw) -- всі з додатним
	 * орієнтованим кутом у (u, v), обертання його зберігає */
	double u[9], v[9];

	if (hl < 4.0)
	{
		hl = 4.0;
	}
	s = (double)len - hl;
	if (s < 1.0)
	{
		s = 1.0;
	}
	u[0] = 0; v[0] = -sw;  u[1] = s; v[1] = -sw;  u[2] = s; v[2] = sw;
	u[3] = 0; v[3] = -sw;  u[4] = s; v[4] = sw;   u[5] = 0; v[5] = sw;
	u[6] = s; v[6] = -hw;  u[7] = (double)len; v[7] = 0;  u[8] = s; v[8] = hw;
	for (int i = 0; i < 9; i++)
	{
		p->t[i / 3].x[i % 3] = iround((double)cx + (u[i] * dx) + (v[i] * px));
		p->t[i / 3].y[i % 3] = iround((double)cy + (u[i] * dy) + (v[i] * py));
	}
	p->tipX = p->t[2].x[1];
	p->tipY = p->t[2].y[1];
}

bool aprsBearingKnown(uint32_t distM)
{
	return distM >= APRS_BEARING_MIN_M;
}

bool aprsBeaconArrowVisible(bool hasGeo, uint32_t distM)
{
	return hasGeo && aprsBearingKnown(distM);   /* R20 Ж1: було distM > 0 -- на часткових метрах стрілка й «270°» були шумом */
}

uint16_t aprsKnotsToKmh(uint16_t kn)
{
	return (uint16_t)((((uint32_t)kn * 1852U) + 500U) / 1000U);
}

/* ===================================================================================== */
/* R16: історія прийому -- журнал кадрів і дані маяка кожної станції                      */
/* ===================================================================================== */

void aprsHistClear(aprsHist_t *h)
{
	memset(h, 0, sizeof(*h));
}

void aprsHistClearBeacons(aprsHist_t *h)
{
	memset(h->bcn, 0, sizeof(h->bcn));
	h->lastBcn1 = 0U;
}

static int histIdx(const aprsRxDb_t *db, const aprsStation_t *s)
{
	if ((db == NULL) || (s == NULL) || (s < &db->st[0]) || (s >= &db->st[APRS_STATIONS_MAX]))
	{
		return -1;
	}
	return (int)(s - &db->st[0]);
}

void aprsHistStationTouch(aprsHist_t *h, const aprsRxDb_t *db, const aprsStation_t *s)
{
	int i = histIdx(db, s);

	/* count == 1 -- запис станції щойно створено (aprsDbUpdate() робить memset): вільний слот АБО витіснена найстаріша станція, чиї дані
	 * маяка ще лежать у цьому слоті. Станція, що вже була, має count >= 2 (count насичується на 65535 і не скидається). */
	if ((i >= 0) && (s->count <= 1U))
	{
		memset(&h->bcn[i], 0, sizeof(h->bcn[i]));
		if (h->lastBcn1 == (uint8_t)(i + 1))
		{
			h->lastBcn1 = 0U;
		}
	}
}

const aprsBcnRec_t *aprsHistBeaconFill(aprsHist_t *h, const aprsRxDb_t *db, const aprsStation_t *s, const aprsPacket_t *pkt,
		bool hasGeo, uint32_t distM, uint16_t bearing, uint32_t rxSecs, int rssiDbm)
{
	int i = histIdx(db, s);
	aprsBcnRec_t *r;

	if (i < 0)
	{
		return NULL;
	}
	r = &h->bcn[i];
	memset(r, 0, sizeof(*r));
	r->rssiDbm = aprsRssiClamp(rssiDbm);
	r->hasGeo = hasGeo;
	r->bearing = bearing;
	r->distM = distM;
	r->course = pkt->course;
	r->speedKn = pkt->speedKn;
	r->altM = pkt->altM;
	r->flags = (uint8_t)(AWIN_F_VALID | (pkt->hasAlt ? AWIN_F_ALT : 0U) | (pkt->hasShift ? AWIN_F_SHIFT : 0U) | (pkt->rangeKm ? AWIN_F_RANGE_KM : 0U));
	r->extKind = pkt->extKind;
	r->wxMask = pkt->wxMask;
	if (pkt->wxMask != 0U)
	{
		r->u.wx.tempC = pkt->tempC;
		r->u.wx.pressDhPa = pkt->pressDhPa;
		r->u.wx.windDeg = pkt->windDeg;
		r->u.wx.humPct = pkt->humPct;
		r->u.wx.windMph = pkt->windMph;
		r->u.wx.gustMph = pkt->gustMph;
	}
	else
	{
		r->u.r.freqKHz = pkt->freqKHz;
		r->u.r.shiftKHz = pkt->shiftKHz;
		r->u.r.extVal = pkt->extVal;
		r->u.r.rangeVal = pkt->rangeVal;
		memcpy(r->u.r.tone, pkt->tone, sizeof(r->u.r.tone));
	}
	r->symTable = pkt->symTable;
	r->symCode = pkt->symCode;
	r->rxSecs = rxSecs;
	copyTrunc(r->text, sizeof(r->text), s->text);
	h->lastBcn1 = (uint8_t)(i + 1);
	return r;
}

const aprsBcnRec_t *aprsHistBeaconOf(const aprsHist_t *h, const aprsRxDb_t *db, const aprsStation_t *s)
{
	int i = histIdx(db, s);

	if ((i < 0) || (s->call[0] == 0) || ((h->bcn[i].flags & AWIN_F_VALID) == 0U))
	{
		return NULL;
	}
	return &h->bcn[i];
}

const aprsBcnRec_t *aprsHistBeaconLast(const aprsHist_t *h, int *dbIdx)
{
	int i = (int)h->lastBcn1 - 1;

	if ((i < 0) || (i >= APRS_STATIONS_MAX) || ((h->bcn[i].flags & AWIN_F_VALID) == 0U))
	{
		return NULL;
	}
	if (dbIdx != NULL)
	{
		*dbIdx = i;
	}
	return &h->bcn[i];
}

int aprsHistBeaconOrder(const aprsHist_t *h, const aprsRxDb_t *db, uint32_t nowMs, uint8_t *out, int max)
{
	int n = 0;

	for (int rank = 0; (rank < APRS_STATIONS_MAX) && (n < max); rank++)
	{
		const aprsStation_t *s = aprsDbNth(db, rank, nowMs);

		if (s == NULL)
		{
			break;
		}
		if (((s->flags & APRS_ST_HASPOS) != 0U) && (aprsHistBeaconOf(h, db, s) != NULL))
		{
			out[n++] = (uint8_t)(s - &db->st[0]);
		}
	}
	return n;
}

int aprsBeaconOrderFind(const uint8_t *order, int count, int dbIdx)
{
	for (int i = 0; i < count; i++)
	{
		if ((int)order[i] == dbIdx)
		{
			return i;
		}
	}
	return -1;
}

int aprsBeaconOrderStep(int pos, int count, int step)
{
	if (count <= 0)
	{
		return -1;
	}
	if ((pos < 0) || (pos >= count))
	{
		return (step < 0) ? (count - 1) : 0;
	}
	pos += (step < 0) ? -1 : 1;
	if (pos < 0)
	{
		pos = count - 1;
	}
	if (pos >= count)
	{
		pos = 0;
	}
	return pos;
}

int8_t aprsRssiClamp(int dBm)
{
	if (dBm == 0)
	{
		return (int8_t)APRS_RSSI_NONE;
	}
	if (dBm < -127)
	{
		return (int8_t)-127;
	}
	return (int8_t)((dBm > -1) ? -1 : dBm);
}

bool aprsJrnAdd(aprsHist_t *h, uint32_t rxSecs, const uint8_t *frame, uint16_t len, int rssiDbm)
{
	aprsJrnEntry_t *e = &h->jrn[h->jrnHead % APRS_JRN_SLOTS];

	/* Пишемо просто в слот (стек не чіпаємо). Слот при повному кільці -- НАЙСТАРІШИЙ запис: невдалий розбір його вже зіпсував, тож
	 * прибираємо його з журналу (count--), а head не рухаємо. */
	if (aprsAx25ToText(frame, len, e->text, sizeof(e->text)) == 0U)
	{
		e->text[0] = 0;
		if (h->jrnCount >= APRS_JRN_SLOTS)
		{
			h->jrnCount = (uint8_t)(APRS_JRN_SLOTS - 1U);
		}
		return false;
	}
	e->rxSecs = rxSecs;
	h->jrnRssi[h->jrnHead % APRS_JRN_SLOTS] = aprsRssiClamp(rssiDbm);
	h->jrnHead = (uint8_t)((h->jrnHead + 1U) % APRS_JRN_SLOTS);
	if (h->jrnCount < APRS_JRN_SLOTS)
	{
		h->jrnCount++;
	}
	return true;
}

const aprsJrnEntry_t *aprsJrnNth(const aprsHist_t *h, int n)
{
	if ((n < 0) || (n >= (int)h->jrnCount) || (n >= APRS_JRN_SLOTS))
	{
		return NULL;
	}
	return &h->jrn[((int)h->jrnHead + APRS_JRN_SLOTS - 1 - n) % APRS_JRN_SLOTS];
}

int aprsJrnSlotOf(const aprsHist_t *h, int n)
{
	if ((n < 0) || (n >= (int)h->jrnCount) || (n >= APRS_JRN_SLOTS))
	{
		return -1;
	}
	return ((int)h->jrnHead + APRS_JRN_SLOTS - 1 - n) % APRS_JRN_SLOTS;
}

const aprsJrnEntry_t *aprsJrnAtSlot(const aprsHist_t *h, int slot)
{
	if ((slot < 0) || (slot >= APRS_JRN_SLOTS) || (h->jrn[slot].text[0] == 0))
	{
		return NULL;
	}
	return &h->jrn[slot];
}

int aprsJrnNOfSlot(const aprsHist_t *h, int slot)
{
	int n;

	if ((slot < 0) || (slot >= APRS_JRN_SLOTS))
	{
		return 0;
	}
	n = ((int)h->jrnHead + APRS_JRN_SLOTS - 1 - slot) % APRS_JRN_SLOTS;
	return (n < (int)h->jrnCount) ? n : 0;
}

int8_t aprsJrnRssiAtSlot(const aprsHist_t *h, int slot)
{
	if ((slot < 0) || (slot >= APRS_JRN_SLOTS) || (h->jrn[slot].text[0] == 0))
	{
		return (int8_t)APRS_RSSI_NONE;
	}
	return h->jrnRssi[slot];
}

void aprsJrnSummary(const aprsJrnEntry_t *e, char *call, char *dti)
{
	size_t i = 0;
	const char *c;

	call[0] = 0;
	*dti = '-';
	if (e == NULL)
	{
		return;
	}
	while ((e->text[i] != 0) && (e->text[i] != '>') && (i < (APRS_CALL_LEN - 1U)))
	{
		call[i] = e->text[i];
		i++;
	}
	call[i] = 0;
	c = strchr(e->text, ':');
	if ((c != NULL) && (c[1] != 0))
	{
		*dti = c[1];
	}
}

#endif /* ENABLE_APRS_RX */
