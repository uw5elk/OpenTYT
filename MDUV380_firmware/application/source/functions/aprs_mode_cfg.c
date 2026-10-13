/*
 * aprs_mode_cfg.c -- налаштування «Режиму APRS» (R10). Опис -- у aprs_mode_cfg.h.
 * Чистий C без заліза; у типовій збірці (без ENABLE_APRS_RX) порожній translation unit.
 */
#include "functions/aprs_mode_cfg.h"

#if defined(ENABLE_APRS_RX)

#include <string.h>
#include <stdio.h>
#include "user_interface/languages/aprsmode_ua.h"

#define APRSM_MAGIC0      'A'
#define APRSM_MAGIC1      'M'
#define APRSM_VERSION     1U
#define APRSM_SUM_SEED    0x5AU

static const uint8_t intervalMin[APRSM_INTERVALS] = { 0U, 5U, 10U, 15U, 30U, 60U };

uint8_t aprsModeIntervalMinutes(uint8_t idx)
{
	return (idx < APRSM_INTERVALS) ? intervalMin[idx] : 0U;
}

uint32_t aprsModeIntervalMs(uint8_t idx)
{
	return (uint32_t)aprsModeIntervalMinutes(idx) * 60000UL;
}

/* ---- позивні й шляхи ------------------------------------------------------------------------------- */

static bool isCallChar(char c)
{
	return (((c >= 'A') && (c <= 'Z')) || ((c >= '0') && (c <= '9')));
}

bool aprsModeCallValid(const char *s)
{
	size_t n = 0;

	if (s == NULL)
	{
		return false;
	}
	while (s[n] != 0)
	{
		if ((n >= 6U) || (isCallChar(s[n]) == false))
		{
			return false;
		}
		n++;
	}
	return (n >= 1U);
}

bool aprsModePathValid(const char *s)
{
	return (s != NULL) && ((s[0] == 0) || aprsModeCallValid(s));
}

size_t aprsModeNormCall(char *dst, size_t dstSize, const char *src)
{
	size_t n = 0;

	if ((dst == NULL) || (dstSize == 0U))
	{
		return 0;
	}
	while ((src != NULL) && (*src != 0) && (n < 6U) && ((n + 1U) < dstSize))
	{
		char c = *src++;

		if ((c >= 'a') && (c <= 'z'))
		{
			c = (char)(c - 'a' + 'A');
		}
		if (isCallChar(c) == false)
		{
			continue;   /* пропуски, дефіси тощо відкидаємо */
		}
		dst[n++] = c;
	}
	dst[n] = 0;
	return n;
}

/* ---- частота ------------------------------------------------------------------------------------------ */

bool aprsModeFreqValid(uint32_t f)
{
	return (((f >= 13500000UL) && (f <= 17400000UL)) || ((f >= 40000000UL) && (f <= 48000000UL)));
}

bool aprsModeParseFreq(const char *s, uint32_t *f10Hz)
{
	uint32_t ip = 0, fp = 0;
	int ni = 0, nf = 0;
	bool dot = false;

	if ((s == NULL) || (f10Hz == NULL))
	{
		return false;
	}
	for (; *s != 0; s++)
	{
		if ((*s >= '0') && (*s <= '9'))
		{
			if (dot == false)
			{
				if (++ni > 3)
				{
					return false;
				}
				ip = ip * 10U + (uint32_t)(*s - '0');
			}
			else
			{
				if (++nf > 5)
				{
					return false;   /* крок 10 Гц: 5 знаків після крапки в МГц */
				}
				fp = fp * 10U + (uint32_t)(*s - '0');
			}
		}
		else if (((*s == '.') || (*s == ',')) && (dot == false))
		{
			dot = true;
		}
		else
		{
			return false;
		}
	}
	if (ni == 0)
	{
		return false;
	}
	for (int i = nf; i < 5; i++)
	{
		fp *= 10U;
	}
	uint32_t f = ip * 100000UL + fp;
	if (aprsModeFreqValid(f) == false)
	{
		return false;
	}
	*f10Hz = f;
	return true;
}

void aprsModeFormatFreq(char *b, size_t n, uint32_t f10Hz)
{
	uint32_t ip = f10Hz / 100000UL;
	uint32_t fp = f10Hz % 100000UL;
	char frac[8];
	int len;

	snprintf(frac, sizeof(frac), "%05lu", (unsigned long)fp);
	len = 5;
	while ((len > 3) && (frac[len - 1] == '0'))
	{
		len--;
	}
	frac[len] = 0;
	snprintf(b, n, "%lu.%s", (unsigned long)ip, frac);
}

/* ---- координати ---------------------------------------------------------------------------------------- */

bool aprsModeParseCoord(const char *s, bool isLat, int32_t *u)
{
	bool neg = false, dot = false;
	int ni = 0, nf = 0;
	int64_t ip = 0, fp = 0;

	if ((s == NULL) || (u == NULL))
	{
		return false;
	}
	if (*s == '-')
	{
		neg = true;
		s++;
	}
	for (; *s != 0; s++)
	{
		if ((*s >= '0') && (*s <= '9'))
		{
			if (dot == false)
			{
				if (++ni > 3)
				{
					return false;
				}
				ip = ip * 10 + (*s - '0');
			}
			else
			{
				if (++nf > 6)
				{
					return false;
				}
				fp = fp * 10 + (*s - '0');
			}
		}
		else if (((*s == '.') || (*s == ',')) && (dot == false))
		{
			dot = true;
		}
		else
		{
			return false;
		}
	}
	if (ni == 0)
	{
		return false;
	}
	for (int i = nf; i < 6; i++)
	{
		fp *= 10;
	}
	int64_t v = ip * 1000000 + fp;
	int64_t lim = isLat ? 90000000 : 180000000;
	if (v > lim)
	{
		return false;
	}
	*u = (int32_t)(neg ? -v : v);
	return true;
}

void aprsModeFormatCoord(char *b, size_t n, int32_t u)
{
	uint32_t a = (u < 0) ? (uint32_t)(-(int64_t)u) : (uint32_t)u;
	char frac[8];
	int len;

	snprintf(frac, sizeof(frac), "%06lu", (unsigned long)(a % 1000000UL));
	len = 6;
	while ((len > 4) && (frac[len - 1] == '0'))
	{
		len--;
	}
	frac[len] = 0;
	snprintf(b, n, "%s%lu.%s", (u < 0) ? "-" : "", (unsigned long)(a / 1000000UL), frac);
}

int32_t aprsModeFixed24ToMicro(const uint8_t b[3])
{
	uint32_t v = ((uint32_t)b[2] << 16) | ((uint32_t)b[1] << 8) | (uint32_t)b[0];
	int32_t ip = (int32_t)((v & 0x7FFFFFU) >> 15);
	int32_t dp = (int32_t)(v & 0x7FFFU);
	int32_t r = ip * 1000000 + dp * 100;   /* частка -- у 1E-4 градуса = 100 мікроградусів */

	return (v & 0x800000U) ? -r : r;
}

/* ---- коментар: cp1251 -> UTF-8 ------------------------------------------------------------------------- */

/* cp1251 -> Unicode для коментаря. Власна компактна таблиця (кирилиця й українські літери), а не dmrSmsCp1251ToUcs2():
 * та існує лише в збірці з AES + DMR_DATA, а «Режим APRS» збирається і без них. Усе, чого шрифт рації й так не має, -- '?'. */
uint16_t aprsModeCp1251ToUcs2(uint8_t c)   /* R11: не static -- нею користується aprs_msg.c (повідомлення) */
{
	if (c >= 0xC0U)
	{
		return (uint16_t)(0x0410U + (c - 0xC0U));   /* А..Я, а..я */
	}
	switch (c)
	{
		case 0xA8: return 0x0401U;   /* Ё */
		case 0xB8: return 0x0451U;   /* ё */
		case 0xA5: return 0x0490U;   /* Ґ */
		case 0xB4: return 0x0491U;   /* ґ */
		case 0xAA: return 0x0404U;   /* Є */
		case 0xBA: return 0x0454U;   /* є */
		case 0xB2: return 0x0406U;   /* І */
		case 0xB3: return 0x0456U;   /* і */
		case 0xAF: return 0x0407U;   /* Ї */
		case 0xBF: return 0x0457U;   /* ї */
		case 0xB9: return 0x2116U;   /* № */
		default:   return (uint16_t)'?';
	}
}

size_t aprsModeCommentToUtf8(const char *cp1251, char *out, size_t cap)
{
	size_t n = 0;

	if ((out == NULL) || (cap == 0U))
	{
		return 0;
	}
	for (; (cp1251 != NULL) && (*cp1251 != 0); cp1251++)
	{
		uint8_t c = (uint8_t)*cp1251;
		uint16_t u;
		uint8_t enc[3];
		size_t el;

		if (c < 0x20U)
		{
			c = ' ';   /* керівні в ефір не пускаємо */
		}
		u = (c < 0x80U) ? (uint16_t)c : aprsModeCp1251ToUcs2(c);
		if (u < 0x80U)
		{
			enc[0] = (uint8_t)u;
			el = 1;
		}
		else if (u < 0x800U)
		{
			enc[0] = (uint8_t)(0xC0U | (u >> 6));
			enc[1] = (uint8_t)(0x80U | (u & 0x3FU));
			el = 2;
		}
		else
		{
			enc[0] = (uint8_t)(0xE0U | (u >> 12));
			enc[1] = (uint8_t)(0x80U | ((u >> 6) & 0x3FU));
			enc[2] = (uint8_t)(0x80U | (u & 0x3FU));
			el = 3;
		}
		if (((n + el) > APRSM_COMMENT_AIR_MAX) || ((n + el + 1U) > cap))
		{
			break;   /* символ не влазить -- не рвемо його посередині */
		}
		memcpy(out + n, enc, el);
		n += el;
	}
	out[n] = 0;
	return n;
}

/* ---- символи ------------------------------------------------------------------------------------------- */

typedef struct { char code; const char *name; } namedSym_t;

static const namedSym_t named[] =
{
	{ '>', APRSM_SYM_CAR },
	{ '[', APRSM_SYM_HUMAN },
	{ '-', APRSM_SYM_HOUSE },
	{ 'b', APRSM_SYM_BIKE },
	{ '<', APRSM_SYM_MOTO },
	{ 'k', APRSM_SYM_TRUCK },
	{ 'v', APRSM_SYM_VAN },
	{ '#', APRSM_SYM_DIGI },
	{ 'r', APRSM_SYM_REPEATER },
	{ 'Y', APRSM_SYM_YACHT },
	/* R14: решта первинної таблиці (лише для показу на вікні маяка; перебір власного символу -- перші NAMED_CYCLE) */
	{ '!', APRSM_SYM_P_21 },
	{ '$', APRSM_SYM_P_24 },
	{ '%', APRSM_SYM_P_25 },
	{ '&', APRSM_SYM_P_26 },
	{ '\'', APRSM_SYM_P_27 },
	{ '(', APRSM_SYM_P_28 },
	{ ')', APRSM_SYM_P_29 },
	{ '*', APRSM_SYM_P_2A },
	{ '+', APRSM_SYM_P_2B },
	{ '/', APRSM_SYM_P_2F },
	{ ':', APRSM_SYM_P_3A },
	{ ';', APRSM_SYM_P_3B },
	{ '=', APRSM_SYM_P_3D },
	{ '?', APRSM_SYM_P_3F },
	{ '@', APRSM_SYM_P_40 },
	{ 'A', APRSM_SYM_P_41 },
	{ 'B', APRSM_SYM_P_42 },
	{ 'C', APRSM_SYM_P_43 },
	{ 'F', APRSM_SYM_P_46 },
	{ 'G', APRSM_SYM_P_47 },
	{ 'H', APRSM_SYM_P_48 },
	{ 'I', APRSM_SYM_P_49 },
	{ 'K', APRSM_SYM_P_4B },
	{ 'L', APRSM_SYM_P_4C },
	{ 'N', APRSM_SYM_P_4E },
	{ 'O', APRSM_SYM_P_4F },
	{ 'P', APRSM_SYM_P_50 },
	{ 'R', APRSM_SYM_P_52 },
	{ 'S', APRSM_SYM_P_53 },
	{ 'T', APRSM_SYM_P_54 },
	{ 'U', APRSM_SYM_P_55 },
	{ 'V', APRSM_SYM_P_56 },
	{ 'W', APRSM_SYM_P_57 },
	{ 'X', APRSM_SYM_P_58 },
	{ '\\', APRSM_SYM_P_5C },
	{ ']', APRSM_SYM_P_5D },
	{ '^', APRSM_SYM_P_5E },
	{ '_', APRSM_SYM_P_5F },
	{ '`', APRSM_SYM_P_60 },
	{ 'a', APRSM_SYM_P_61 },
	{ 'c', APRSM_SYM_P_63 },
	{ 'd', APRSM_SYM_P_64 },
	{ 'e', APRSM_SYM_P_65 },
	{ 'f', APRSM_SYM_P_66 },
	{ 'g', APRSM_SYM_P_67 },
	{ 'h', APRSM_SYM_P_68 },
	{ 'j', APRSM_SYM_P_6A },
	{ 'l', APRSM_SYM_P_6C },
	{ 'm', APRSM_SYM_P_6D },
	{ 'n', APRSM_SYM_P_6E },
	{ 'o', APRSM_SYM_P_6F },
	{ 'p', APRSM_SYM_P_70 },
	{ 's', APRSM_SYM_P_73 },
	{ 'u', APRSM_SYM_P_75 },
	{ 'y', APRSM_SYM_P_79 },
	{ 'z', APRSM_SYM_P_7A },
};
#define NAMED_COUNT  (sizeof(named) / sizeof(named[0]))
#define NAMED_CYCLE  10U   /* власний символ крутиться по перших десяти -- як до R14 */

/* R14: додаткова таблиця '\\' (накладка -- знак таблиці -- на назву не впливає) */
static const namedSym_t namedAlt[] =
{
	{ '!', APRSM_SYM_A_21 },
	{ '#', APRSM_SYM_A_23 },
	{ '$', APRSM_SYM_A_24 },
	{ '&', APRSM_SYM_A_26 },
	{ '+', APRSM_SYM_A_2B },
	{ '-', APRSM_SYM_A_2D },
	{ '>', APRSM_SYM_A_3E },
	{ 'K', APRSM_SYM_A_4B },
	{ 'L', APRSM_SYM_A_4C },
	{ 'O', APRSM_SYM_A_4F },
	{ 'P', APRSM_SYM_A_50 },
	{ 'R', APRSM_SYM_A_52 },
	{ 'S', APRSM_SYM_A_53 },
	{ 'U', APRSM_SYM_A_55 },
	{ 'W', APRSM_SYM_A_57 },
	{ 'Y', APRSM_SYM_A_59 },
	{ '^', APRSM_SYM_A_5E },
	{ '_', APRSM_SYM_A_5F },
	{ 'k', APRSM_SYM_A_6B },
	{ 'n', APRSM_SYM_A_6E },
	{ 's', APRSM_SYM_A_73 },
	{ 'u', APRSM_SYM_A_75 },
	{ 'v', APRSM_SYM_A_76 },
};
#define NAMEDALT_COUNT  (sizeof(namedAlt) / sizeof(namedAlt[0]))

const char *aprsSymbolNameEx(char table, char code)
{
	const namedSym_t *t = (table == '/') ? named : namedAlt;
	size_t n = (table == '/') ? NAMED_COUNT : NAMEDALT_COUNT;

	for (size_t i = 0; i < n; i++)
	{
		if (t[i].code == code)
		{
			return t[i].name;
		}
	}
	return NULL;
}

const char *aprsModeSymbolName(uint8_t table, uint8_t index)
{
	return aprsSymbolNameEx((table == 0U) ? '/' : '\\', (char)('!' + index));
}

void aprsModeSymbolNextNamed(uint8_t *table, uint8_t *index)
{
	/* з будь-якого символу -- до першого названого, що йде ПІСЛЯ нього в списку; не названий -- до першого */
	size_t cur = NAMED_CYCLE;

	if (*table == 0U)
	{
		for (size_t i = 0; i < NAMED_CYCLE; i++)
		{
			if (named[i].code == (char)('!' + *index))
			{
				cur = i;
				break;
			}
		}
	}
	size_t next = (cur == NAMED_CYCLE) ? 0U : ((cur + 1U) % NAMED_CYCLE);
	*table = 0U;
	*index = (uint8_t)(named[next].code - '!');
}

/* ---- збереження -------------------------------------------------------------------------------------------- */

void aprsModeCfgInit(aprsModeCfg_t *c)
{
	memset(c, 0, sizeof(*c));
}

static void put32(uint8_t *p, uint32_t v)
{
	p[0] = (uint8_t)v;
	p[1] = (uint8_t)(v >> 8);
	p[2] = (uint8_t)(v >> 16);
	p[3] = (uint8_t)(v >> 24);
}

static uint32_t get32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint8_t sum8(const uint8_t *b, size_t n)
{
	uint8_t s = APRSM_SUM_SEED;

	for (size_t i = 0; i < n; i++)
	{
		s = (uint8_t)(s + b[i]);
	}
	return s;
}

/* Розкладка блоку (APRSM_BLOCK_LEN = 72):
 *  0..1 'A','M'   2 версія   3 interval   4 sql   5..6 ov   7 ambiguity
 *  8..11 freq   12..18 call   19 ssid   20..26 path1   27 path1Ssid   28..34 path2   35 path2Ssid
 *  36 iconTable   37 iconIndex   38..62 comment(25)   63..66 latU   67..70 lonU   71 контрольна сума (байти 0..70) */
void aprsModeCfgToBytes(const aprsModeCfg_t *c, uint8_t out[APRSM_BLOCK_LEN])
{
	memset(out, 0, APRSM_BLOCK_LEN);
	out[0] = APRSM_MAGIC0;
	out[1] = APRSM_MAGIC1;
	out[2] = APRSM_VERSION;
	out[3] = c->interval;
	out[4] = c->sql;
	out[5] = (uint8_t)c->ov;
	out[6] = (uint8_t)(c->ov >> 8);
	out[7] = c->ambiguity;
	put32(&out[8], c->freq);
	memcpy(&out[12], c->call, APRSM_CALL_LEN);
	out[19] = c->ssid;
	memcpy(&out[20], c->path[0], APRSM_CALL_LEN);
	out[27] = c->pathSsid[0];
	memcpy(&out[28], c->path[1], APRSM_CALL_LEN);
	out[35] = c->pathSsid[1];
	out[36] = c->iconTable;
	out[37] = c->iconIndex;
	memcpy(&out[38], c->comment, APRSM_COMMENT_LEN);
	put32(&out[63], (uint32_t)c->latU);
	put32(&out[67], (uint32_t)c->lonU);
	out[71] = sum8(out, 71);
}

bool aprsModeCfgFromBytes(aprsModeCfg_t *c, const uint8_t *b, size_t len)
{
	aprsModeCfgInit(c);
	if ((b == NULL) || (len != APRSM_BLOCK_LEN) || (b[0] != APRSM_MAGIC0) || (b[1] != APRSM_MAGIC1) ||
			(b[2] != APRSM_VERSION) || (b[71] != sum8(b, 71)))
	{
		return false;
	}
	c->interval = (b[3] < APRSM_INTERVALS) ? b[3] : 0U;
	c->sql = (b[4] <= APRSM_SQL_MAX) ? b[4] : 0U;
	c->ov = (uint16_t)(b[5] | ((uint16_t)b[6] << 8)) & APRSM_OV_ALL;
	c->ambiguity = b[7];
	c->freq = get32(&b[8]);
	memcpy(c->call, &b[12], APRSM_CALL_LEN);
	c->call[APRSM_CALL_LEN - 1U] = 0;
	c->ssid = b[19];
	memcpy(c->path[0], &b[20], APRSM_CALL_LEN);
	c->path[0][APRSM_CALL_LEN - 1U] = 0;
	c->pathSsid[0] = b[27];
	memcpy(c->path[1], &b[28], APRSM_CALL_LEN);
	c->path[1][APRSM_CALL_LEN - 1U] = 0;
	c->pathSsid[1] = b[35];
	c->iconTable = b[36];
	c->iconIndex = b[37];
	memcpy(c->comment, &b[38], APRSM_COMMENT_LEN);
	c->comment[APRSM_COMMENT_LEN - 1U] = 0;
	c->latU = (int32_t)get32(&b[63]);
	c->lonU = (int32_t)get32(&b[67]);

	/* Поля, що не пройшли перевірку, знімаються з оверрайдів (береться типове значення). */
	if ((c->ov & APRSM_OV_FREQ) && (aprsModeFreqValid(c->freq) == false))
	{
		c->ov &= (uint16_t)~APRSM_OV_FREQ;
	}
	if ((c->ov & APRSM_OV_CALL) && (aprsModeCallValid(c->call) == false))
	{
		c->ov &= (uint16_t)~APRSM_OV_CALL;
	}
	if ((c->ov & APRSM_OV_SSID) && (c->ssid > 15U))
	{
		c->ov &= (uint16_t)~APRSM_OV_SSID;
	}
	if ((c->ov & APRSM_OV_PATH1) && ((aprsModePathValid(c->path[0]) == false) || (c->pathSsid[0] > 7U)))
	{
		c->ov &= (uint16_t)~APRSM_OV_PATH1;
	}
	if ((c->ov & APRSM_OV_PATH2) && ((aprsModePathValid(c->path[1]) == false) || (c->pathSsid[1] > 7U)))
	{
		c->ov &= (uint16_t)~APRSM_OV_PATH2;
	}
	if ((c->ov & APRSM_OV_ICON) && ((c->iconTable > 1U) || (c->iconIndex > APRSM_ICON_MAX)))
	{
		c->ov &= (uint16_t)~APRSM_OV_ICON;
	}
	if ((c->ov & APRSM_OV_LAT) && ((c->latU < -90000000L) || (c->latU > 90000000L)))
	{
		c->ov &= (uint16_t)~APRSM_OV_LAT;
	}
	if ((c->ov & APRSM_OV_LON) && ((c->lonU < -180000000L) || (c->lonU > 180000000L)))
	{
		c->ov &= (uint16_t)~APRSM_OV_LON;
	}
	if ((c->ov & APRSM_OV_AMB) && (c->ambiguity > 7U))
	{
		c->ov &= (uint16_t)~APRSM_OV_AMB;
	}
	return true;
}

/* ---- типові значення ---------------------------------------------------------------------------------------- */

/* Рядок кодплуга (name[n]) -> позивний/шлях: до NUL/0xFF/пробілу, лише допустимі символи. */
static void rawToCall(char *dst, const char *src, size_t n)
{
	size_t k = 0;

	for (size_t i = 0; (i < n) && (k < 6U); i++)
	{
		uint8_t c = (uint8_t)src[i];

		if ((c == 0U) || (c == 0xFFU) || (c == ' '))
		{
			break;
		}
		if ((c >= 'a') && (c <= 'z'))
		{
			c = (uint8_t)(c - 'a' + 'A');
		}
		if (isCallChar((char)c) == false)
		{
			break;
		}
		dst[k++] = (char)c;
	}
	dst[k] = 0;
}

void aprsModeDefaultsBuild(aprsModeDefaults_t *d, const aprsModeRawCfg_t *raw, bool rawValid,
		const char *radioName, bool settingsPosValid, int32_t settingsLatU, int32_t settingsLonU)
{
	memset(d, 0, sizeof(*d));

	/* запасні значення: WIDE1-1, WIDE2-1, автомобіль, 144.800 МГц */
	d->freq = 0;
	snprintf(d->path[0], sizeof(d->path[0]), "WIDE1");
	d->pathSsid[0] = 1;
	snprintf(d->path[1], sizeof(d->path[1]), "WIDE2");
	d->pathSsid[1] = 1;
	d->iconTable = 0;
	d->iconIndex = (uint8_t)('>' - '!');
	d->ssid = 0;
	d->ambiguity = 0;
	if (settingsPosValid)
	{
		d->hasPos = true;
		d->latU = settingsLatU;
		d->lonU = settingsLonU;
	}
	if (radioName != NULL)
	{
		rawToCall(d->call, radioName, 6);
	}

	if ((raw == NULL) || (rawValid == false))
	{
		return;
	}
	d->hasCfg = true;
	d->freq = raw->txFrequency;
	d->ssid = (raw->senderSSID <= 15U) ? raw->senderSSID : 0U;
	for (int p = 0; p < 2; p++)
	{
		char tmp[APRSM_CALL_LEN];

		rawToCall(tmp, raw->paths[p].name, 6);
		if ((p == 1) && (tmp[0] == 0))
		{
			d->path[1][0] = 0;   /* другий шлях у конфігу порожній -- його і нема */
			d->pathSsid[1] = 0;
		}
		else if (tmp[0] != 0)
		{
			memcpy(d->path[p], tmp, sizeof(tmp));
			d->pathSsid[p] = (raw->paths[p].ssid <= 7U) ? raw->paths[p].ssid : 0U;
		}
		else if (p == 0)
		{
			d->path[0][0] = 0;   /* у конфігу першого шляху нема -- без шляху */
			d->pathSsid[0] = 0;
		}
	}
	d->iconTable = (raw->iconTable == 0U) ? 0U : 1U;
	d->iconIndex = (raw->iconIndex <= APRSM_ICON_MAX) ? raw->iconIndex : (uint8_t)('>' - '!');
	{
		size_t k = 0;

		for (size_t i = 0; (i < 24U) && (k < APRSM_COMMENT_MAX); i++)
		{
			uint8_t c = (uint8_t)raw->comment[i];

			if ((c == 0U) || (c == 0xFFU))
			{
				break;
			}
			d->comment[k++] = (char)c;
		}
		d->comment[k] = 0;
	}
	d->ambiguity = (uint8_t)((raw->flags & APRSM_RAW_FLAG_AMB_MASK) >> 5);
	if (raw->flags & APRSM_RAW_FLAG_USE_POSITION)
	{
		d->hasPos = true;
		d->latU = aprsModeFixed24ToMicro(raw->latitude);
		d->lonU = aprsModeFixed24ToMicro(raw->longitude);
	}
}

void aprsModeEffective(const aprsModeCfg_t *c, const aprsModeDefaults_t *d, aprsModeEff_t *e)
{
	memset(e, 0, sizeof(*e));

	e->freq = (c->ov & APRSM_OV_FREQ) ? c->freq : ((d->freq != 0U) ? d->freq : APRSM_FREQ_DEFAULT);
	if (aprsModeFreqValid(e->freq) == false)
	{
		e->freq = APRSM_FREQ_DEFAULT;
	}
	memcpy(e->call, (c->ov & APRSM_OV_CALL) ? c->call : d->call, APRSM_CALL_LEN);
	e->ssid = (c->ov & APRSM_OV_SSID) ? c->ssid : d->ssid;
	memcpy(e->path[0], (c->ov & APRSM_OV_PATH1) ? c->path[0] : d->path[0], APRSM_CALL_LEN);
	e->pathSsid[0] = (c->ov & APRSM_OV_PATH1) ? c->pathSsid[0] : d->pathSsid[0];
	memcpy(e->path[1], (c->ov & APRSM_OV_PATH2) ? c->path[1] : d->path[1], APRSM_CALL_LEN);
	e->pathSsid[1] = (c->ov & APRSM_OV_PATH2) ? c->pathSsid[1] : d->pathSsid[1];
	e->iconTable = (c->ov & APRSM_OV_ICON) ? c->iconTable : d->iconTable;
	e->iconIndex = (c->ov & APRSM_OV_ICON) ? c->iconIndex : d->iconIndex;
	memcpy(e->comment, (c->ov & APRSM_OV_COMMENT) ? c->comment : d->comment, APRSM_COMMENT_LEN);
	e->ambiguity = (c->ov & APRSM_OV_AMB) ? c->ambiguity : d->ambiguity;
	e->interval = c->interval;
	e->sql = c->sql;

	/* Позиція: широта й довгота можуть бути задані окремо; відсутню беремо з типової. */
	bool latOv = ((c->ov & APRSM_OV_LAT) != 0U), lonOv = ((c->ov & APRSM_OV_LON) != 0U);
	if ((latOv || d->hasPos) && (lonOv || d->hasPos))
	{
		e->hasPos = true;
		e->latU = latOv ? c->latU : d->latU;
		e->lonU = lonOv ? c->lonU : d->lonU;
	}
}

void aprsModeToBeaconCfg(const aprsModeEff_t *e, aprsModeRawCfg_t *out)
{
	memset(out, 0, sizeof(*out));
	snprintf(out->name, sizeof(out->name), "APRSM");
	out->senderSSID = e->ssid;
	/* aprsSendPacket() завжди кладе в заголовок щонайменше один шлях (другий -- лише якщо strlen(name) != 0).
	 * Перший шлях порожній, а другий є -- другий стає першим; обидва порожні -- WIDE1-1 (повністю без
	 * шляху прошивка передати не вміє). */
	int src0 = 0, src1 = 1;
	if (e->path[0][0] == 0)
	{
		src0 = 1;
		src1 = -1;
	}
	for (int p = 0; p < 2; p++)
	{
		int s = (p == 0) ? src0 : src1;

		if ((s >= 0) && (e->path[s][0] != 0))
		{
			memcpy(out->paths[p].name, e->path[s], strnlen(e->path[s], 6U));
			out->paths[p].ssid = e->pathSsid[s];
		}
	}
	if (out->paths[0].name[0] == 0)
	{
		memcpy(out->paths[0].name, "WIDE1", 5);
		out->paths[0].ssid = 1;
	}
	out->iconTable = e->iconTable;
	out->iconIndex = e->iconIndex;
	out->txFrequency = 0U;   /* QSY не потрібен: режим уже стоїть на частоті APRS */
	out->flags = (uint8_t)((e->ambiguity & 0x07U) << 5);   /* без USE_POSITION: позиція йде окремо */
}

#endif /* ENABLE_APRS_RX */
