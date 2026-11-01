/*
 * wake_diag.c -- R58: журнал сеансів пробудження ретранслятора. Порожній translation unit без
 * -DENABLE_WAKE_DIAG (типова й користувацькі збірки). Опис і межі -- у wake_diag.h.
 */
#include "functions/wake_diag.h"

#if defined(ENABLE_WAKE_DIAG)

#include <string.h>
#include <stdio.h>

/* Кільце сеансів -- у CCM: у діагностичній збірці main RAM лишається ~1,7 КБ (CI), а CCM -- кілька КБ.
 * CCM стартовий код не обнуляє, тож wakeDiagInit() викликає HRC6000InitTask() до першого сеансу;
 * лічильник s_count (.bss, надійно 0) не пускає читання кільця раніше за перший запис. */
static wakeDiagSession_t s_ring[WAKE_DIAG_SESSIONS] __attribute__((section(".ccmram")));   /* CCM-INIT(wakeDiagInit) */

static uint8_t  s_cur;           /* індекс найновішого сеансу в кільці */
static uint8_t  s_count;         /* скільки сеансів записано (0..WAKE_DIAG_SESSIONS) */
static uint32_t s_t0;            /* now на старті найновішого сеансу */
static bool     s_open;          /* сеанс ще чекає на AWAKEN/TX/FAILED */
static bool     s_hopPending;    /* наступний сеанс почнеться після стрибка */
static uint16_t s_directTx;      /* передач RMO без пробудження (ретранслятор уже "тримав" слот) */

void wakeDiagReset(void)
{
	memset(s_ring, 0, sizeof(s_ring));
	s_cur = 0;
	s_count = 0;
	s_t0 = 0;
	s_open = false;
	s_hopPending = false;
	s_directTx = 0;
}

void wakeDiagInit(void)
{
	wakeDiagReset();
}

static uint16_t relMs(uint32_t now)
{
	uint32_t d = now - s_t0;

	return (d >= (uint32_t)WAKE_DIAG_NONE) ? (uint16_t)(WAKE_DIAG_NONE - 1U) : (uint16_t)d;
}

static wakeDiagSession_t *curSession(void)
{
	return (s_count == 0U) ? NULL : &s_ring[s_cur];
}

void wakeDiagBegin(uint32_t now, int16_t chan, uint32_t rxFreq, uint32_t txFreq, uint8_t cc, uint16_t to0)
{
	uint8_t prev = WAKE_DIAG_PREV_NONE;
	uint8_t next = 0U;
	wakeDiagSession_t *s;

	if (s_count != 0U)
	{
		const wakeDiagSession_t *p = &s_ring[s_cur];

		prev = (p->tAwaken != WAKE_DIAG_NONE) ? WAKE_DIAG_PREV_OK :
				((p->tFail != WAKE_DIAG_NONE) ? WAKE_DIAG_PREV_FAIL : WAKE_DIAG_PREV_CANCEL);
		next = (uint8_t)((s_cur + 1U) % WAKE_DIAG_SESSIONS);
	}

	s = &s_ring[next];
	memset(s, 0, sizeof(*s));
	s->rxFreq = rxFreq;
	s->txFreq = txFreq;
	s->chan = (uint16_t)chan;
	s->cc = cc;
	s->flags = (uint8_t)(prev | (s_hopPending ? WAKE_DIAG_FLAG_HOP_START : 0U));
	s->to0 = to0;
	s->tAwaken = WAKE_DIAG_NONE;
	s->tTx = WAKE_DIAG_NONE;
	s->tFail = WAKE_DIAG_NONE;
	s->hopT = WAKE_DIAG_NONE;
	for (unsigned i = 0U; i < WAKE_DIAG_PKT_MAX; i++)
	{
		s->pktT[i] = WAKE_DIAG_NONE;
	}
	for (unsigned i = 0U; i < WAKE_DIAG_ZERO_MAX; i++)
	{
		s->zeroT[i] = WAKE_DIAG_NONE;
	}

	s_hopPending = false;
	s_t0 = now;
	s_cur = next;
	if (s_count < WAKE_DIAG_SESSIONS)
	{
		s_count++;
	}
	s_open = true;
}

void wakeDiagPacket(uint32_t now)
{
	wakeDiagSession_t *s = s_open ? curSession() : NULL;

	if (s == NULL)
	{
		return;
	}
	if (s->pkts < WAKE_DIAG_PKT_MAX)
	{
		s->pktT[s->pkts] = relMs(now);
	}
	if (s->pkts < 255U)
	{
		s->pkts++;
	}
}

void wakeDiagZero(uint32_t now)
{
	wakeDiagSession_t *s = s_open ? curSession() : NULL;

	if (s == NULL)
	{
		return;
	}
	if (s->zeros < WAKE_DIAG_ZERO_MAX)
	{
		s->zeroT[s->zeros] = relMs(now);
	}
	if (s->zeros < 255U)
	{
		s->zeros++;
	}
}

void wakeDiagAwaken(uint32_t now)
{
	wakeDiagSession_t *s = s_open ? curSession() : NULL;

	if ((s != NULL) && (s->tAwaken == WAKE_DIAG_NONE))
	{
		s->tAwaken = relMs(now);
	}
}

void wakeDiagTxStart(uint32_t now)
{
	wakeDiagSession_t *s = s_open ? curSession() : NULL;

	/* AWAKEN був, TX ще ні, і сеанс свіжий (<20 с: інакше це чужа передача після обірваного сеансу). */
	if ((s != NULL) && (s->tAwaken != WAKE_DIAG_NONE) && (s->tTx == WAKE_DIAG_NONE) && ((now - s_t0) < 20000U))
	{
		s->tTx = relMs(now);
		s_open = false;
	}
	else if (s_directTx < 0xFFFFU)
	{
		s_directTx++;
	}
}

void wakeDiagFail(uint32_t now)
{
	wakeDiagSession_t *s = s_open ? curSession() : NULL;

	if (s != NULL)
	{
		s->tFail = relMs(now);
		s_open = false;
	}
}

void wakeDiagToggle(uint8_t value)
{
	wakeDiagSession_t *s = s_open ? curSession() : NULL;

	if ((s != NULL) && (value > s->maxToggle))
	{
		s->maxToggle = value;
	}
}

void wakeDiagIntTimeout(void)
{
	wakeDiagSession_t *s = s_open ? curSession() : NULL;

	if ((s != NULL) && (s->intTmo < 255U))
	{
		s->intTmo++;
	}
}

void wakeDiagHop(uint32_t now, int16_t newChan)
{
	wakeDiagSession_t *s = curSession();

	if (s != NULL)
	{
		s->hopT = relMs(now);
		s->hopChan = (uint16_t)newChan;
	}
	s_open = false;
	s_hopPending = true;
}

uint8_t wakeDiagCount(void)
{
	return s_count;
}

uint16_t wakeDiagDirectTx(void)
{
	return s_directTx;
}

bool wakeDiagGet(uint8_t age, wakeDiagSession_t *out)
{
	if ((age >= s_count) || (out == NULL))
	{
		return false;
	}
	*out = s_ring[(uint8_t)((s_cur + WAKE_DIAG_SESSIONS - age) % WAKE_DIAG_SESSIONS)];
	return true;
}

static uint8_t *putU16(uint8_t *p, uint16_t v)
{
	*p++ = (uint8_t)v;
	*p++ = (uint8_t)(v >> 8);
	return p;
}

static uint8_t *putU32(uint8_t *p, uint32_t v)
{
	p = putU16(p, (uint16_t)v);
	return putU16(p, (uint16_t)(v >> 16));
}

/* Запис (WAKE_DIAG_REC_LEN = 52 Б, LE): rx u32, tx u32, chan u16, cc u8, flags u8, to0 u16, tAwaken u16, tTx u16, tFail u16,
 * hopT u16, hopChan u16, pkts u8, zeros u8, maxToggle u8, intTmo u8, pktT[6] u16, zeroT[6] u16. */
static uint8_t *putRecord(uint8_t *p, const wakeDiagSession_t *s)
{
	p = putU32(p, s->rxFreq);
	p = putU32(p, s->txFreq);
	p = putU16(p, s->chan);
	*p++ = s->cc;
	*p++ = s->flags;
	p = putU16(p, s->to0);
	p = putU16(p, s->tAwaken);
	p = putU16(p, s->tTx);
	p = putU16(p, s->tFail);
	p = putU16(p, s->hopT);
	p = putU16(p, s->hopChan);
	*p++ = s->pkts;
	*p++ = s->zeros;
	*p++ = s->maxToggle;
	*p++ = s->intTmo;
	for (unsigned i = 0U; i < WAKE_DIAG_PKT_MAX; i++)
	{
		p = putU16(p, s->pktT[i]);
	}
	for (unsigned i = 0U; i < WAKE_DIAG_ZERO_MAX; i++)
	{
		p = putU16(p, s->zeroT[i]);
	}
	return p;
}

int wakeDiagDump(uint8_t *buf, int max)
{
	uint8_t *p = buf;
	unsigned n = s_count;
	wakeDiagSession_t s;

	if ((buf == NULL) || (max < (int)WAKE_DIAG_DUMP_HDR))
	{
		return 0;
	}
	while ((n > 0U) && ((int)(WAKE_DIAG_DUMP_HDR + (n * WAKE_DIAG_REC_LEN)) > max))
	{
		n--;
	}

	*p++ = WAKE_DIAG_DUMP_VER;
	*p++ = (uint8_t)WAKE_DIAG_SESSIONS;
	*p++ = (uint8_t)n;
	*p++ = 0U;
	p = putU16(p, s_directTx);
	p = putU16(p, 0U);   /* резерв */

	for (unsigned age = 0U; age < n; age++)
	{
		(void)wakeDiagGet((uint8_t)age, &s);
		p = putRecord(p, &s);
	}
	return (int)(p - buf);
}

/* ------------------------------ текст екрана ------------------------------ */

static const char *prevName(uint8_t flags)
{
	switch (flags & WAKE_DIAG_FLAG_PREV_MASK)
	{
		case WAKE_DIAG_PREV_OK:     return WAKE_PREV_OK_S;
		case WAKE_DIAG_PREV_FAIL:   return WAKE_PREV_FAIL_S;
		case WAKE_DIAG_PREV_CANCEL: return WAKE_PREV_CNCL_S;
		default:                    return WAKE_PREV_NONE_S;
	}
}

static void timeStr(char *b, int sz, uint16_t t)
{
	if (t == WAKE_DIAG_NONE)
	{
		snprintf(b, (size_t)sz, "-");
	}
	else
	{
		snprintf(b, (size_t)sz, "%u", (unsigned)t);
	}
}

/* head != 0 -- перший рядок ("Pkt%u:" + перші три часи), інакше продовження (наступні три). */
static void timesLine(char *buf, int bufSize, const char *headFmt, unsigned total, const uint16_t *t,
		unsigned stored, bool head)
{
	unsigned from = head ? 0U : 3U;
	int len;
	char tmp[8];

	if (head)
	{
		snprintf(buf, (size_t)bufSize, headFmt, total);
	}
	else
	{
		snprintf(buf, (size_t)bufSize, "     ");
	}
	len = (int)strlen(buf);

	for (unsigned i = from; (i < (from + 3U)) && (i < stored) && (i < total); i++)
	{
		timeStr(tmp, (int)sizeof(tmp), t[i]);
		len += snprintf(buf + len, (size_t)(bufSize - len), " %s", tmp);
		if (len >= bufSize)
		{
			break;
		}
	}
}

bool wakeDiagLine(const wakeDiagSession_t *s, unsigned age, unsigned total, unsigned directTx,
		unsigned line, char *buf, int bufSize)
{
	char a[8], b[8], c[8];

	(void)age;
	(void)total;

	if ((s == NULL) || (buf == NULL) || (bufSize < 8) || (line >= WAKE_DIAG_LINES))
	{
		return false;
	}

	switch (line)
	{
		case 0:
			snprintf(buf, (size_t)bufSize, WAKE_L1_FMT, (unsigned)s->chan,
					(unsigned long)(s->rxFreq / 100000U), (unsigned long)((s->rxFreq % 100000U) / 10U), (unsigned)s->cc);
			break;
		case 1:
			snprintf(buf, (size_t)bufSize, WAKE_L2_FMT,
					(unsigned long)(s->txFreq / 100000U), (unsigned long)((s->txFreq % 100000U) / 10U), (unsigned)s->to0);
			break;
		case 2:
			snprintf(buf, (size_t)bufSize, WAKE_L3_FMT, prevName(s->flags),
					((s->flags & WAKE_DIAG_FLAG_HOP_START) != 0U) ? WAKE_YES_S : WAKE_NO_S, directTx);
			break;
		case 3:
			timesLine(buf, bufSize, WAKE_PKT_FMT, s->pkts, s->pktT, WAKE_DIAG_PKT_MAX, true);
			break;
		case 4:
			timesLine(buf, bufSize, WAKE_PKT_FMT, s->pkts, s->pktT, WAKE_DIAG_PKT_MAX, false);
			break;
		case 5:
			timesLine(buf, bufSize, WAKE_ZERO_FMT, s->zeros, s->zeroT, WAKE_DIAG_ZERO_MAX, true);
			break;
		case 6:
			timesLine(buf, bufSize, WAKE_ZERO_FMT, s->zeros, s->zeroT, WAKE_DIAG_ZERO_MAX, false);
			break;
		case 7:
			timeStr(a, (int)sizeof(a), s->tAwaken);
			timeStr(b, (int)sizeof(b), s->tTx);
			timeStr(c, (int)sizeof(c), s->tFail);
			snprintf(buf, (size_t)bufSize, WAKE_L7_FMT, a, b, c);
			break;
		default:
			timeStr(a, (int)sizeof(a), s->hopT);
			snprintf(buf, (size_t)bufSize, WAKE_L8_FMT, (unsigned)s->maxToggle, (unsigned)s->intTmo, a, (unsigned)s->hopChan);
			break;
	}
	return true;
}

#endif /* ENABLE_WAKE_DIAG */
