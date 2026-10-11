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

/* Повідомлення: ":" + адресат(9, пробіли) + ":" + текст [+ "{номер"] */
static void parseMessage(const aprsAx25_t *ax, aprsPacket_t *p)
{
	const uint8_t *in = ax->info;
	size_t n = ax->infoLen;

	if ((n < 11U) || (in[10] != ':'))
	{
		return;   /* лишається APRS_T_OTHER */
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

	switch (c)
	{
		case '!':
		case '=':
		case '/':
		case '@':
		{
			size_t at = ((c == '/') || (c == '@')) ? 8U : 1U;   /* з відміткою часу: ще 7 символів */

			if (n <= at)
			{
				return;
			}
			const uint8_t *s = in + at;
			size_t rest = n - at;
			size_t used;

			if (isDig(s[0]) || (s[0] == ' '))
			{
				if (!parseUncompressed(s, rest, out))
				{
					return;
				}
				used = 19U;
			}
			else if ((s[0] == '/') || (s[0] == '\\') || ((s[0] >= 'A') && (s[0] <= 'Z')) || ((s[0] >= 'a') && (s[0] <= 'j')))
			{
				if (!parseCompressed(s, rest, out))
				{
					return;
				}
				out->compressed = true;
				used = 13U;
			}
			else
			{
				return;
			}
			out->type = APRS_T_POSITION;
			out->hasPos = true;
			setText(out, s + used, rest - used);
			break;
		}

		case '`':
		case '\'':
		case 0x1C:
		case 0x1D:
			if (parseMicE(ax, out))
			{
				out->type = APRS_T_POSITION;
				out->hasPos = true;
				out->micE = true;
				setText(out, in + 9, n - 9U);   /* після символу й таблиці (info[7], info[8]) */
			}
			break;

		case ':':
			parseMessage(ax, out);
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
			break;   /* об'єкти, погода, телеметрія, запити... -- «інше» */
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
	if (k == 0U)
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

#endif /* ENABLE_APRS_RX */
