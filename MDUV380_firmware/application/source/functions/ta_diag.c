/*
 * ta_diag.c -- R88: діагностика сирого Talker Alias і GPS-блока LC. Див. include/functions/ta_diag.h.
 * Увесь файл під ENABLE_TA_DIAG: у звичайних збірках він порожній (жодного байта в прошивці).
 */
#include "functions/ta_diag.h"

#if defined(TA_DIAG)
#include <string.h>
#include <stdio.h>

/* ------------------------------------------------------------------ чисті функції ------------------------------------------------------------------ */

size_t taDiagHex(char *out, size_t outSize, const uint8_t *b, size_t n)
{
	static const char digits[] = "0123456789ABCDEF";
	size_t o = 0;

	if ((out == NULL) || (outSize == 0U))
	{
		return 0U;
	}
	for (size_t i = 0; (b != NULL) && (i < n) && ((o + 2U) < outSize); i++)
	{
		out[o++] = digits[b[i] >> 4];
		out[o++] = digits[b[i] & 0x0F];
	}
	out[o] = 0;
	return o;
}

void taDiagParseHeader(uint8_t b0, taDiagHdr_t *h)
{
	h->format = (uint8_t)((b0 >> 6U) & 0x03U);
	h->size   = (uint8_t)((b0 >> 1U) & 0x1FU);
	h->bit0   = (uint8_t)(b0 & 0x01U);
}

const char *taDiagFormatName(uint8_t format)
{
	static const char *const names[4] = { "7BIT", "ISO8", "UTF8", "UTF16" };

	return names[format & 0x03U];
}

size_t taDiagDecode(const uint8_t *buf, char *dest, size_t destLen)
{
	taDiagHdr_t h;
	size_t t2 = 0U;

	if ((dest == NULL) || (destLen < 2U))
	{
		return 0U;
	}
	memset(dest, 0, destLen);
	if (buf == NULL)
	{
		return 0U;
	}
	taDiagParseHeader(buf[0], &h);

	switch (h.format)
	{
		case 0U:   /* 7 біт -- той самий цикл, що в decodeTA(): перша група з 7 біт відкидається */
			{
				uint8_t t1 = 0U, c = 0U;

				for (size_t i = 0U; (i < TA_DIAG_BUF_LEN) && (t2 < h.size) && (t2 < (destLen - 1U)); i++)
				{
					for (int j = 7; j >= 0; j--)
					{
						c = (uint8_t)((c << 1U) | (buf[i] >> j));
						if (++t1 == 7U)
						{
							if ((i > 0U) && (t2 < (destLen - 1U)))
							{
								dest[t2++] = (char)(c & 0x7FU);
							}
							t1 = 0U;
							c = 0U;
						}
					}
				}
			}
			break;

		case 1U:   /* ISO-8 біт */
		case 2U:   /* "UTF-8": прошивка копіює як 8-біт */
			{
				size_t n = destLen - 1U;

				if (n > (TA_DIAG_BUF_LEN - 1U))
				{
					n = TA_DIAG_BUF_LEN - 1U;
				}
				memcpy(dest, buf + 1U, n);
				for (size_t i = 0; i < n; i++)
				{
					if (dest[i] == 0)
					{
						break;
					}
					t2++;
				}
			}
			break;

		default:   /* UTF-16: беруться молодші байти, інакше '?' */
			for (size_t i = 0U; (i < 15U) && (t2 < h.size) && (t2 < (destLen - 1U)); i++)
			{
				dest[t2++] = (buf[2U * i + 1U] == 0U) ? (char)buf[2U * i + 2U] : '?';
			}
			break;
	}
	return strlen(dest);
}

void taDiagGlue(const taDiagRec_t *r, uint8_t *buf)
{
	memset(buf, 0, TA_DIAG_BUF_LEN);
	for (size_t b = 0; b < TA_DIAG_BLOCKS; b++)
	{
		if ((r->taMask & (1U << b)) != 0U)
		{
			memcpy(buf + (b * TA_DIAG_BLOCK_LEN), r->ta[b], TA_DIAG_BLOCK_LEN);
		}
	}
}

static int32_t roundE4(double v)
{
	return (int32_t)((v * 10000.0) + ((v > 0.0) ? 0.5 : -0.5));
}

bool taDiagParseGps(const uint8_t *d7, int32_t *latE4, int32_t *lonE4, uint8_t *errIdx)
{
	if ((d7 == NULL) || (latE4 == NULL) || (lonE4 == NULL))
	{
		return false;
	}
	/* d7[0..6] == LC[2..8]; у decodeGPSPosition() це data[2..8] */
	uint32_t lonU = ((uint32_t)(d7[0] & 0x01U) << 31) | ((uint32_t)d7[1] << 23) | ((uint32_t)d7[2] << 15) | ((uint32_t)d7[3] << 7);
	int32_t lonI = ((int32_t)lonU) >> 7;
	uint32_t latU = ((uint32_t)d7[4] << 24) | ((uint32_t)d7[5] << 16) | ((uint32_t)d7[6] << 8);
	int32_t latI = ((int32_t)latU) >> 8;

	*lonE4 = roundE4(((double)lonI * 360.0) / 33554432.0);
	*latE4 = roundE4(((double)latI * 180.0) / 16777216.0);
	if (errIdx != NULL)
	{
		*errIdx = (uint8_t)((d7[0] & 0x0EU) >> 1U);
	}
	return true;
}

void taDiagFmtDeg(char *out, size_t outSize, int32_t e4)
{
	uint32_t a = (e4 < 0) ? (uint32_t)(-(int64_t)e4) : (uint32_t)e4;

	snprintf(out, outSize, "%s%lu.%04lu", (e4 < 0) ? "-" : "", (unsigned long)(a / 10000U), (unsigned long)(a % 10000U));
}

bool taDiagFlcoRow(const uint8_t *cnt, size_t *cursor, char *out, size_t outSize, size_t width)
{
	size_t o = 0;

	if ((cnt == NULL) || (cursor == NULL) || (out == NULL) || (outSize == 0U))
	{
		return false;
	}
	out[0] = 0;
	while (*cursor < TA_DIAG_FLCO_COUNT)
	{
		char tok[8];
		int tl;

		if (cnt[*cursor] == 0U)
		{
			(*cursor)++;
			continue;
		}
		tl = snprintf(tok, sizeof(tok), "%02X:%u", (unsigned)*cursor, (unsigned)cnt[*cursor]);
		if (tl < 0)
		{
			break;
		}
		if ((o != 0U) && ((o + 1U + (size_t)tl) > width))
		{
			break;      /* токен піде в наступний рядок */
		}
		if ((o + (o ? 1U : 0U) + (size_t)tl + 1U) > outSize)
		{
			break;
		}
		if (o != 0U)
		{
			out[o++] = ' ';
		}
		memcpy(out + o, tok, (size_t)tl);
		o += (size_t)tl;
		out[o] = 0;
		(*cursor)++;
	}
	return (o != 0U);
}

void taDiagPrintable(char *out, size_t outSize, const char *src, size_t offset, size_t n)
{
	size_t o = 0;

	if ((out == NULL) || (outSize == 0U))
	{
		return;
	}
	for (size_t i = 0; (src != NULL) && (i < n) && ((o + 1U) < outSize); i++)
	{
		unsigned char ch = (unsigned char)src[offset + i];

		if (ch == 0U)
		{
			break;
		}
		out[o++] = ((ch < 0x20U) || (ch == 0x7FU)) ? '.' : (char)ch;
	}
	out[o] = 0;
}

/* ------------------------------------------------------------------ запам'ятовування ------------------------------------------------------------------ */

static taDiagRec_t s_rec[TA_DIAG_RECORDS];
static size_t s_head;          /* індекс найновішого запису */
static size_t s_count;         /* скільки записів заведено (до TA_DIAG_RECORDS) */
static uint8_t s_allFlco[TA_DIAG_FLCO_COUNT];
static uint32_t s_allTotal;
static uint32_t s_pf;
static uint32_t s_crcBad;

void taDiagInit(void)
{
	memset(s_rec, 0, sizeof(s_rec));
	memset(s_allFlco, 0, sizeof(s_allFlco));
	s_head = 0U;
	s_count = 0U;
	s_allTotal = 0U;
	s_pf = 0U;
	s_crcBad = 0U;
}

static taDiagRec_t *newRecord(void)
{
	s_head = (s_count == 0U) ? 0U : ((s_head + 1U) % TA_DIAG_RECORDS);
	if (s_count < TA_DIAG_RECORDS)
	{
		s_count++;
	}
	memset(&s_rec[s_head], 0, sizeof(taDiagRec_t));
	return &s_rec[s_head];
}

static void sat(uint8_t *c)
{
	if (*c < 255U)
	{
		(*c)++;
	}
}

void taDiagNoteBadCrc(void)
{
	s_crcBad++;
}

void taDiagRawLC(const uint8_t *lc)
{
	if (lc == NULL)
	{
		return;
	}
	s_allTotal++;
	if ((lc[0] & 0x80U) != 0U)
	{
		s_pf++;
	}
	sat(&s_allFlco[lc[0] & 0x3FU]);
}

void taDiagCallLC(const uint8_t *lc)
{
	uint8_t flco;
	taDiagRec_t *r;

	if (lc == NULL)
	{
		return;
	}
	flco = (uint8_t)(lc[0] & 0x3FU);
	r = (s_count != 0U) ? &s_rec[s_head] : NULL;

	if ((flco == 0x00U) || (flco == 0x03U))     /* TG_CALL_FLAG / PC_CALL_FLAG */
	{
		uint32_t src = ((uint32_t)lc[6] << 16) | ((uint32_t)lc[7] << 8) | lc[8];

		if ((r == NULL) || (r->srcId != src))
		{
			r = newRecord();
			r->srcId = src;
			r->tgOrPc = ((uint32_t)lc[3] << 16) | ((uint32_t)lc[4] << 8) | lc[5];
			r->isPc = (flco == 0x03U) ? 1U : 0U;
		}
	}
	else if (r == NULL)
	{
		r = newRecord();       /* TA/GPS до першого LC виклику -- запис без ID */
	}
	sat(&r->flco[flco]);

	if ((flco >= 0x04U) && (flco <= 0x07U))
	{
		size_t b = (size_t)(flco - 0x04U);

		if (((r->taMask & (1U << b)) == 0U) || (memcmp(r->ta[b], &lc[2], TA_DIAG_BLOCK_LEN) != 0))
		{
			sat(&r->taSeen[b]);
		}
		r->taMask = (uint8_t)(r->taMask | (1U << b));
		r->taFid[b] = lc[1];
		memcpy(r->ta[b], &lc[2], TA_DIAG_BLOCK_LEN);
	}
	else if (flco == 0x08U)
	{
		if ((r->gpsSeen == 0U) || (memcmp(r->gpsRaw, &lc[2], TA_DIAG_BLOCK_LEN) != 0))
		{
			sat(&r->gpsSeen);
		}
		r->gpsFid = lc[1];
		memcpy(r->gpsRaw, &lc[2], TA_DIAG_BLOCK_LEN);
	}
}

void taDiagFwText(const char *talkerAlias)
{
	if ((s_count == 0U) || (talkerAlias == NULL))
	{
		return;
	}
	memcpy(s_rec[s_head].fwText, talkerAlias, TA_DIAG_FW_TEXT_LEN - 1U);
	s_rec[s_head].fwText[TA_DIAG_FW_TEXT_LEN - 1U] = 0;
}

const taDiagRec_t *taDiagGet(size_t age)
{
	if (age >= s_count)
	{
		return NULL;
	}
	return &s_rec[(s_head + TA_DIAG_RECORDS - age) % TA_DIAG_RECORDS];
}

size_t taDiagCount(void)
{
	return s_count;
}

uint32_t taDiagAllFlcoTotal(void)
{
	return s_allTotal;
}

const uint8_t *taDiagAllFlco(void)
{
	return s_allFlco;
}

uint32_t taDiagPfCount(void)
{
	return s_pf;
}

uint32_t taDiagCrcBadCount(void)
{
	return s_crcBad;
}

#endif /* TA_DIAG */
