/*
 * aprs_msg.c -- повідомлення APRS (R11). Опис -- include/functions/aprs_msg.h.
 *
 * Що перевірено за специфікацією (APRS101 розділ 14 / protocol.txt, aprs.org), а що -- ні:
 *  - формат ":ADDRESSEE_:текст{номер": адресат -- рівно 9 символів, доповнених ПРОБІЛАМИ; номер після '{', 1..5 символів,
 *    БЕЗ закриваючої дужки; ACK -- ":ADDRESSEE_:ack<номер>", «повертає копію номера»; повідомлення без номера не підтверджується
 *    -- ПЕРЕВІРЕНО (опис протоколу protocol.txt).
 *  - довжина тексту 67 символів і заборона '|', '~', '{' в тексті -- за APRS101 розділ 14; сам PDF автоматично прочитати не
 *    вдалось (витяг обривається до розділу 14), тому ця частина -- з пам'яті про специфікацію, НЕ перевірена по тексту.
 *    Для коментарів позицій APRS101 (розділ 5) заборону '|' і '~' підтверджує дослівно («reserved for TNC channel switching»).
 *    Забороняємо всі три символи (безпечніше), а також ':' -- за вимогою брифу R11 (в APRS101 ':' у тексті допустимий).
 *  - як це побачать приймачі (APRSdroid, aprs.fi, FT1D) -- НЕ перевірено, потрібне залізо (TESTING.md, блок AV).
 */
#include "functions/aprs_msg.h"

#if defined(ENABLE_APRS_RX)

#include <string.h>
#include "functions/aprs_mode_cfg.h"

/* ---- символи й текст ------------------------------------------------------------------------------------ */

size_t aprsMsgCharBytes(uint8_t c)
{
	if (c < 0x80U)
	{
		if ((c < 0x20U) || (c == 0x7FU) || (c == ':') || (c == '|') || (c == '~') || (c == '{'))
		{
			return 0U;
		}
		return 1U;
	}
	{
		uint16_t u = aprsModeCp1251ToUcs2(c);

		if (u == (uint16_t)'?')
		{
			return 0U;   /* у шрифті рації й так нема; в ефір не пускаємо */
		}
		return (u < 0x800U) ? 2U : 3U;
	}
}

size_t aprsMsgUtf8Len(const char *cp)
{
	size_t n = 0;

	for (; (cp != NULL) && (*cp != 0); cp++)
	{
		size_t l = aprsMsgCharBytes((uint8_t)*cp);

		n += (l == 0U) ? 1U : l;
	}
	return n;
}

bool aprsMsgCanAppend(const char *cur, uint8_t c)
{
	size_t l = aprsMsgCharBytes(c);

	return (l != 0U) && ((aprsMsgUtf8Len(cur) + l) <= APRS_MSG_UTF8_MAX);
}

int aprsMsgTextCheck(const char *cp)
{
	bool any = false;

	for (; (cp != NULL) && (*cp != 0); cp++)
	{
		if (aprsMsgCharBytes((uint8_t)*cp) == 0U)
		{
			return AMSG_TEXT_ILLEGAL;
		}
		if (*cp != ' ')
		{
			any = true;
		}
	}
	return any ? AMSG_TEXT_OK : AMSG_TEXT_EMPTY;
}

size_t aprsMsgToUtf8(const char *cp, char *out, size_t cap)
{
	size_t n = 0;

	if ((out == NULL) || (cap == 0U))
	{
		return 0U;
	}
	for (; (cp != NULL) && (*cp != 0); cp++)
	{
		uint8_t c = (uint8_t)*cp;
		size_t l = aprsMsgCharBytes(c);
		uint16_t u = (uint16_t)'?';

		if (l == 0U)
		{
			l = 1U;   /* заборонений -> '?' */
		}
		else if (c >= 0x80U)
		{
			u = aprsModeCp1251ToUcs2(c);
		}
		else
		{
			u = c;
		}
		if (((n + l) > APRS_MSG_UTF8_MAX) || ((n + l + 1U) > cap))
		{
			break;   /* літера не влазить -- не рвемо її */
		}
		if (l == 1U)
		{
			out[n] = (char)u;
		}
		else if (l == 2U)
		{
			out[n] = (char)(0xC0U | (u >> 6));
			out[n + 1U] = (char)(0x80U | (u & 0x3FU));
		}
		else
		{
			out[n] = (char)(0xE0U | (u >> 12));
			out[n + 1U] = (char)(0x80U | ((u >> 6) & 0x3FU));
			out[n + 2U] = (char)(0x80U | (u & 0x3FU));
		}
		n += l;
	}
	out[n] = 0;
	return n;
}

/* ---- адресат ------------------------------------------------------------------------------------------- */

bool aprsMsgNormCall(char out[APRS_MSG_CALL_LEN], const char *in)
{
	char t[APRS_MSG_CALL_LEN];
	size_t n = 0;
	const char *dash = NULL;

	out[0] = 0;
	if (in == NULL)
	{
		return false;
	}
	for (; *in != 0; in++)
	{
		char c = *in;

		if ((c >= 'a') && (c <= 'z'))
		{
			c = (char)(c - 'a' + 'A');
		}
		if (n >= APRS_MSG_ADDR_LEN)
		{
			return false;
		}
		if (c == '-')
		{
			if ((n == 0U) || (dash != NULL))
			{
				return false;   /* '-' на початку або другий '-' */
			}
			dash = &t[n];
		}
		else if (((c < 'A') || (c > 'Z')) && ((c < '0') || (c > '9')))
		{
			return false;
		}
		t[n++] = c;
	}
	if (n == 0U)
	{
		return false;
	}
	t[n] = 0;
	if (dash != NULL)
	{
		const char *s = dash + 1;
		unsigned v = 0;
		size_t sl = strlen(s);

		if ((sl < 1U) || (sl > 2U) || (s[0] < '0') || (s[0] > '9') || ((sl == 2U) && ((s[1] < '0') || (s[1] > '9'))))
		{
			return false;
		}
		v = (unsigned)(s[0] - '0');
		if (sl == 2U)
		{
			if (s[0] == '0')
			{
				return false;   /* «-07»: пишемо «-7» */
			}
			v = (v * 10U) + (unsigned)(s[1] - '0');
		}
		if (v > 15U)
		{
			return false;
		}
		if (v == 0U)
		{
			t[dash - t] = 0;   /* «-0» -- те саме, що без SSID */
		}
	}
	memcpy(out, t, strlen(t) + 1U);
	return true;
}

/* ---- кадр ----------------------------------------------------------------------------------------------- */

static size_t buildHead(char *out, size_t cap, const char *to)
{
	size_t tl = strlen(to);

	if ((tl == 0U) || (tl > APRS_MSG_ADDR_LEN) || (cap < (APRS_MSG_ADDR_LEN + 3U)))
	{
		return 0U;
	}
	out[0] = ':';
	memcpy(out + 1, to, tl);
	memset(out + 1 + tl, ' ', APRS_MSG_ADDR_LEN - tl);
	out[1U + APRS_MSG_ADDR_LEN] = ':';
	return APRS_MSG_ADDR_LEN + 2U;
}

size_t aprsMsgBuildMessage(char *out, size_t cap, const char *to, const char *cp, const char *id)
{
	char norm[APRS_MSG_CALL_LEN];
	char trimmed[APRS_MSG_JOB_TEXT_LEN];
	size_t n, idl = 0, tl;

	if ((out == NULL) || (to == NULL) || (cp == NULL) || (aprsMsgNormCall(norm, to) == false) || (aprsMsgTextCheck(cp) != AMSG_TEXT_OK))
	{
		return 0U;
	}
	if (id != NULL)
	{
		idl = strlen(id);
		if (idl >= APRS_MSG_ID_LEN)
		{
			return 0U;
		}
	}
	tl = strlen(cp);
	if (tl >= sizeof(trimmed))
	{
		tl = sizeof(trimmed) - 1U;
	}
	memcpy(trimmed, cp, tl);
	while ((tl > 0U) && (trimmed[tl - 1U] == ' '))
	{
		tl--;
	}
	trimmed[tl] = 0;

	n = buildHead(out, cap, norm);
	if ((n == 0U) || ((n + APRS_MSG_UTF8_MAX + 1U + idl + 1U) > cap))
	{
		return 0U;   /* буфер має вміщати найгірший випадок: 67 байт + '{' + номер + NUL */
	}
	n += aprsMsgToUtf8(trimmed, out + n, cap - n);
	if (idl != 0U)
	{
		out[n++] = '{';
		memcpy(out + n, id, idl);
		n += idl;
	}
	out[n] = 0;
	return n;
}

size_t aprsMsgBuildAck(char *out, size_t cap, const char *to, const char *id)
{
	char norm[APRS_MSG_CALL_LEN];
	size_t n, idl;

	if ((out == NULL) || (to == NULL) || (id == NULL) || (id[0] == 0) || (aprsMsgNormCall(norm, to) == false))
	{
		return 0U;
	}
	idl = strlen(id);
	if (idl >= APRS_MSG_ID_LEN)
	{
		return 0U;
	}
	n = buildHead(out, cap, norm);
	if ((n == 0U) || ((n + 3U + idl + 1U) > cap))
	{
		return 0U;
	}
	memcpy(out + n, "ack", 3U);
	n += 3U;
	memcpy(out + n, id, idl);
	n += idl;
	out[n] = 0;
	return n;
}

/* ---- допоміжне: рядки, список -------------------------------------------------------------------------- */

static void setStr(char *dst, size_t cap, const char *src)
{
	size_t n = (src != NULL) ? strlen(src) : 0U;

	if (n >= cap)
	{
		n = cap - 1U;
	}
	if (n != 0U)
	{
		memcpy(dst, src, n);
	}
	dst[n] = 0;
}

static bool eqCI(const char *a, const char *b)
{
	for (;; a++, b++)
	{
		char x = *a, y = *b;

		if ((x >= 'a') && (x <= 'z'))
		{
			x = (char)(x - 'a' + 'A');
		}
		if ((y >= 'a') && (y <= 'z'))
		{
			y = (char)(y - 'a' + 'A');
		}
		if (x != y)
		{
			return false;
		}
		if (x == 0)
		{
			return true;
		}
	}
}

static bool isPending(const aprsMsgEntry_t *e)
{
	return (e->dir == AMSG_DIR_OUT) && ((e->status == AMSG_ST_WAIT) || (e->status == AMSG_ST_SENT));
}

/* Вставити запис на початок списку (найновіше). Якщо повний -- викидаємо найстаріший, що не чекає на передачу/ACK. */
static aprsMsgEntry_t *listInsert(aprsMsgBox_t *b)
{
	int last = -1;

	for (int i = (int)APRS_MSG_LIST_MAX - 1; i >= 0; i--)
	{
		if ((b->list[i].used == 0U) || (isPending(&b->list[i]) == false))
		{
			last = i;
			break;
		}
	}
	if (last < 0)
	{
		return NULL;
	}
	for (int i = last; i > 0; i--)
	{
		b->list[i] = b->list[i - 1];
	}
	memset(&b->list[0], 0, sizeof(b->list[0]));
	b->list[0].used = 1U;
	return &b->list[0];
}

static aprsMsgEntry_t *findOut(aprsMsgBox_t *b, const char *to, const char *id)
{
	for (unsigned i = 0; i < APRS_MSG_LIST_MAX; i++)
	{
		aprsMsgEntry_t *e = &b->list[i];

		if (e->used && isPending(e) && eqCI(e->call, to) && (strcmp(e->id, id) == 0))
		{
			return e;
		}
	}
	return NULL;
}

static void jobFree(aprsMsgBox_t *b, unsigned i)
{
	memset(&b->q[i], 0, sizeof(b->q[i]));
	if (b->inflight == (int8_t)i)
	{
		b->inflight = -1;
	}
}

/* ---- список і черга ------------------------------------------------------------------------------------- */

void aprsMsgInit(aprsMsgBox_t *b, uint32_t seed)
{
	memset(b, 0, sizeof(*b));
	b->inflight = -1;
	b->lastNum = (uint8_t)(seed % 99U);   /* перший номер = lastNum % 99 + 1 */
}

int aprsMsgSend(aprsMsgBox_t *b, const char *to, const char *cp, uint32_t now)
{
	char norm[APRS_MSG_CALL_LEN];
	int slot = -1;
	aprsMsgEntry_t *e;
	uint8_t num;

	if (aprsMsgNormCall(norm, to) == false)
	{
		return AMSG_E_CALL;
	}
	if (aprsMsgTextCheck(cp) != AMSG_TEXT_OK)
	{
		return AMSG_E_TEXT;
	}
	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		if (b->q[i].type == AMSG_JOB_FREE)
		{
			slot = (int)i;
			break;
		}
	}
	if (slot < 0)
	{
		return AMSG_E_FULL;
	}
	e = listInsert(b);
	if (e == NULL)
	{
		return AMSG_E_FULL;
	}
	num = (uint8_t)((b->lastNum % 99U) + 1U);
	b->lastNum = num;

	memset(&b->q[slot], 0, sizeof(b->q[slot]));
	b->q[slot].type = AMSG_JOB_MSG;
	b->q[slot].nextMs = now;
	setStr(b->q[slot].to, sizeof(b->q[slot].to), norm);
	b->q[slot].id[0] = (char)('0' + (num / 10U));
	b->q[slot].id[1] = (char)('0' + (num % 10U));
	b->q[slot].id[2] = 0;
	{
		/* обрізаємо до 67 байт цілими літерами вже тут: у черзі і в списку -- рівно те, що піде в ефір */
		size_t keep = 0, bytes = 0;

		for (; (cp[keep] != 0) && (keep < (APRS_MSG_JOB_TEXT_LEN - 1U)); keep++)
		{
			size_t l = aprsMsgCharBytes((uint8_t)cp[keep]);

			if ((bytes + l) > APRS_MSG_UTF8_MAX)
			{
				break;
			}
			bytes += l;
		}
		memcpy(b->q[slot].text, cp, keep);
		b->q[slot].text[keep] = 0;
	}
	e->dir = AMSG_DIR_OUT;
	e->status = AMSG_ST_WAIT;
	e->ms = now;
	setStr(e->call, sizeof(e->call), norm);
	setStr(e->id, sizeof(e->id), b->q[slot].id);
	setStr(e->text, sizeof(e->text), b->q[slot].text);
	return AMSG_OK;
}

bool aprsMsgOnIncoming(aprsMsgBox_t *b, const char *from, const char *cp, const char *id, uint32_t now)
{
	aprsMsgEntry_t *e;

	if ((from == NULL) || (from[0] == 0))
	{
		return false;
	}
	if ((id != NULL) && (id[0] != 0))
	{
		char cut[APRS_MSG_TEXT_LEN];

		setStr(cut, sizeof(cut), cp);   /* порівнюємо з тим, що ЗБЕРЕЖЕНО (обрізаним), інакше довге повідомлення було б «новим» щоразу */
		for (unsigned i = 0; i < APRS_MSG_LIST_MAX; i++)
		{
			if (b->list[i].used && (b->list[i].dir == AMSG_DIR_IN) && eqCI(b->list[i].call, from) && (strcmp(b->list[i].id, id) == 0) &&
					(strcmp(b->list[i].text, cut) == 0))
			{
				return false;   /* повтор: показуємо один раз */
			}
		}
	}
	e = listInsert(b);
	if (e == NULL)
	{
		return false;
	}
	e->dir = AMSG_DIR_IN;
	e->status = AMSG_ST_NONE;
	e->unread = 1U;
	e->ms = now;
	setStr(e->call, sizeof(e->call), from);
	setStr(e->id, sizeof(e->id), id);
	setStr(e->text, sizeof(e->text), cp);
	if (b->stats.rxNew < 0xFFFFU)
	{
		b->stats.rxNew++;
	}
	return true;
}

void aprsMsgCountRx(aprsMsgBox_t *b)
{
	if (b->stats.rx < 0xFFFFU)
	{
		b->stats.rx++;
	}
}

static void statInc(uint16_t *v)
{
	if (*v < 0xFFFFU)
	{
		(*v)++;
	}
}

bool aprsMsgQueueAck(aprsMsgBox_t *b, const char *to, const char *id, uint32_t now)
{
	int slot = -1;

	if ((to == NULL) || (to[0] == 0) || (id == NULL) || (id[0] == 0) || (strlen(id) >= APRS_MSG_ID_LEN))
	{
		return false;   /* без номера ACK не потрібен (APRS101) */
	}
	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		if ((b->q[i].type == AMSG_JOB_ACK) && eqCI(b->q[i].to, to) && (strcmp(b->q[i].id, id) == 0))
		{
			return false;   /* такий ACK уже чекає */
		}
		if ((slot < 0) && (b->q[i].type == AMSG_JOB_FREE))
		{
			slot = (int)i;
		}
	}
	if ((b->lastAckMs != 0U) && ((now - b->lastAckMs) < APRS_MSG_ACK_REPEAT_MS) && eqCI(b->lastAckTo, to) && (strcmp(b->lastAckId, id) == 0))
	{
		return false;   /* щойно відповіли на цей самий (дубль через інший діджі) */
	}
	if (slot < 0)
	{
		/* Черга без місця: ACK важливіший за наше повідомлення, що ще не в ефірі (без ACK відправник повторюватиме до безкінечності).
		 * Витісняємо НАЙСТАРІШЕ таке повідомлення -- воно стає «без ACK»; те, що вже в ефірі (inflight), не чіпаємо. */
		int victim = -1;

		for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
		{
			if ((b->q[i].type == AMSG_JOB_MSG) && (b->inflight != (int8_t)i) &&
					((victim < 0) || ((int32_t)(b->q[victim].nextMs - b->q[i].nextMs) > 0)))
			{
				victim = (int)i;
			}
		}
		if (victim < 0)
		{
			statInc(&b->stats.ackLost);
			return false;   /* усі слоти -- ACK або передача в ефірі: відправник повторить, і ми підтвердимо тоді */
		}
		{
			aprsMsgEntry_t *e = findOut(b, b->q[victim].to, b->q[victim].id);

			if (e != NULL)
			{
				e->status = AMSG_ST_NOACK;
			}
		}
		jobFree(b, (unsigned)victim);
		slot = victim;
	}
	memset(&b->q[slot], 0, sizeof(b->q[slot]));
	statInc(&b->stats.ackFormed);
	b->q[slot].type = AMSG_JOB_ACK;
	b->q[slot].nextMs = now;   /* негайно, без повторів */
	setStr(b->q[slot].to, sizeof(b->q[slot].to), to);
	setStr(b->q[slot].id, sizeof(b->q[slot].id), id);
	return true;
}

bool aprsMsgOnAckRx(aprsMsgBox_t *b, const char *from, const char *id, bool isRej)
{
	bool found = false;

	if ((from == NULL) || (id == NULL) || (id[0] == 0))
	{
		return false;
	}
	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		if ((b->q[i].type == AMSG_JOB_MSG) && eqCI(b->q[i].to, from) && (strcmp(b->q[i].id, id) == 0))
		{
			aprsMsgEntry_t *e = findOut(b, b->q[i].to, b->q[i].id);

			if (e != NULL)
			{
				e->status = isRej ? AMSG_ST_NOACK : AMSG_ST_ACK;
			}
			jobFree(b, i);
			found = true;
		}
	}
	return found;
}

static void expire(aprsMsgBox_t *b, uint32_t now)
{
	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		aprsMsgJob_t *j = &b->q[i];

		if ((j->type == AMSG_JOB_MSG) && (b->inflight != (int8_t)i) && (j->attempts >= APRS_MSG_ATTEMPTS) && ((int32_t)(now - j->nextMs) >= 0))
		{
			aprsMsgEntry_t *e = findOut(b, j->to, j->id);

			if (e != NULL)
			{
				e->status = AMSG_ST_NOACK;
			}
			jobFree(b, i);
		}
	}
}

size_t aprsMsgPoll(aprsMsgBox_t *b, uint32_t now, bool busy, bool txOk, char *info, size_t cap)
{
	int pick = -1;
	size_t n;

	expire(b, now);
	if ((b->inflight >= 0) || (b->txActive != 0U))
	{
		return 0U;
	}
	if ((b->lastTxMs != 0U) && ((now - b->lastTxMs) < APRS_MSG_GAP_MS))
	{
		return 0U;
	}
	/* пріоритет ACK, далі найраніше замовлене повідомлення, яке вже можна (нова спроба / перша) */
	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		const aprsMsgJob_t *j = &b->q[i];

		if ((j->type == AMSG_JOB_FREE) || ((int32_t)(now - j->nextMs) < 0) || ((j->type == AMSG_JOB_MSG) && (j->attempts >= APRS_MSG_ATTEMPTS)))
		{
			continue;
		}
		if (j->type == AMSG_JOB_ACK)
		{
			pick = (int)i;
			break;
		}
		if ((pick < 0) || ((int32_t)(b->q[pick].nextMs - j->nextMs) > 0))
		{
			pick = (int)i;
		}
	}
	if ((pick < 0) || (txOk == false))
	{
		b->busySinceMs = 0U;
		return 0U;
	}
	if (busy)
	{
		if (b->busySinceMs == 0U)
		{
			b->busySinceMs = (now != 0U) ? now : 1U;
		}
		if ((now - b->busySinceMs) < APRS_MSG_BUSY_MAX_MS)
		{
			return 0U;
		}
	}
	b->busySinceMs = 0U;

	if (b->q[pick].type == AMSG_JOB_ACK)
	{
		n = aprsMsgBuildAck(info, cap, b->q[pick].to, b->q[pick].id);
	}
	else
	{
		n = aprsMsgBuildMessage(info, cap, b->q[pick].to, b->q[pick].text, b->q[pick].id);
	}
	if (n == 0U)
	{
		/* кадр не складається (недійсний адресат/текст) -- не зациклюємось: завдання знімаємо */
		if (b->q[pick].type == AMSG_JOB_MSG)
		{
			aprsMsgEntry_t *e = findOut(b, b->q[pick].to, b->q[pick].id);

			if (e != NULL)
			{
				e->status = AMSG_ST_NOACK;
			}
		}
		else
		{
			statInc(&b->stats.ackLost);
		}
		jobFree(b, (unsigned)pick);
		return 0U;
	}
	b->inflight = (int8_t)pick;
	return n;
}

void aprsMsgTxDone(aprsMsgBox_t *b, uint32_t now, bool ok, bool fatal)
{
	int i = b->inflight;

	if (ok)
	{
		b->txActive = 1U;   /* кадр пішов у ефір, навіть якщо його завдання встигли зняти (прийшов ACK) */
	}
	if (i < 0)
	{
		return;
	}
	b->inflight = -1;
	if (b->q[i].type == AMSG_JOB_ACK)
	{
		if (ok)
		{
			b->lastAckMs = (now != 0U) ? now : 1U;
			setStr(b->lastAckTo, sizeof(b->lastAckTo), b->q[i].to);
			setStr(b->lastAckId, sizeof(b->lastAckId), b->q[i].id);
			(void)aprsMsgBuildAck(b->lastAckText, sizeof(b->lastAckText), b->q[i].to, b->q[i].id);
			statInc(&b->stats.ackSent);
			jobFree(b, (unsigned)i);   /* ПЕРЕДАНИЙ ACK не повторюється: відправник, що не почув, повторить повідомлення -- і дістане новий */
			return;
		}
		if (fatal || (++b->q[i].attempts >= APRS_MSG_ACK_TRIES))
		{
			statInc(&b->stats.ackLost);
			jobFree(b, (unsigned)i);
			return;
		}
		b->q[i].nextMs = now + APRS_MSG_ACK_RETRY_MS;   /* передачу не вдалось почати (зайнято чимось іншим) -- ще раз за мить */
		return;
	}
	if (b->q[i].type != AMSG_JOB_MSG)
	{
		return;
	}
	{
		aprsMsgJob_t *j = &b->q[i];
		aprsMsgEntry_t *e = findOut(b, j->to, j->id);

		if (fatal)
		{
			if (e != NULL)
			{
				e->status = AMSG_ST_NOACK;
			}
			jobFree(b, (unsigned)i);
			return;
		}
		j->attempts++;
		if (ok)
		{
			statInc(&b->stats.msgSent);
		}
		j->nextMs = now + APRS_MSG_RETRY_MS;
		if (e != NULL)
		{
			e->attempts = j->attempts;
			if (ok)
			{
				e->status = AMSG_ST_SENT;
			}
		}
	}
}

void aprsMsgTxEnded(aprsMsgBox_t *b, uint32_t now)
{
	b->txActive = 0U;
	b->lastTxMs = (now != 0U) ? now : 1U;
}

bool aprsMsgGapOk(const aprsMsgBox_t *b, uint32_t now)
{
	return (b->lastTxMs == 0U) || ((now - b->lastTxMs) >= APRS_MSG_GAP_MS);
}

int aprsMsgWrapLine(const char *s, int len, int start, int w, int *lineStart, int *next)
{
	int ls = start, end, brk;

	while ((ls < len) && (s[ls] == ' '))
	{
		ls++;
	}
	if ((ls >= len) || (w < 1))
	{
		*lineStart = len;
		*next = len;
		return 0;
	}
	*lineStart = ls;
	if ((len - ls) <= w)
	{
		end = len;
		*next = len;
	}
	else
	{
		brk = -1;
		for (int i = ls + w; i > ls; i--)
		{
			if (s[i] == ' ')
			{
				brk = i;
				break;
			}
		}
		if (brk > ls)
		{
			end = brk;
			*next = brk + 1;
		}
		else
		{
			end = ls + w;
			*next = end;
		}
	}
	while ((end > ls) && (s[end - 1] == ' '))
	{
		end--;
	}
	return end - ls;
}

void aprsMsgCancelAll(aprsMsgBox_t *b)
{
	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		if (b->q[i].type == AMSG_JOB_MSG)
		{
			aprsMsgEntry_t *e = findOut(b, b->q[i].to, b->q[i].id);

			if (e != NULL)
			{
				e->status = AMSG_ST_NOACK;
			}
		}
		jobFree(b, i);
	}
	b->inflight = -1;
}

unsigned aprsMsgAckPending(const aprsMsgBox_t *b)
{
	unsigned n = 0;

	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		n += (b->q[i].type == AMSG_JOB_ACK) ? 1U : 0U;
	}
	return n;
}

unsigned aprsMsgQueueLen(const aprsMsgBox_t *b)
{
	unsigned n = 0;

	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		n += (b->q[i].type != AMSG_JOB_FREE) ? 1U : 0U;
	}
	return n;
}

unsigned aprsMsgPendingCount(const aprsMsgBox_t *b)
{
	unsigned n = 0;

	for (unsigned i = 0; i < APRS_MSG_QUEUE_MAX; i++)
	{
		n += (b->q[i].type == AMSG_JOB_MSG) ? 1U : 0U;
	}
	return n;
}

unsigned aprsMsgUnreadCount(const aprsMsgBox_t *b)
{
	unsigned n = 0;

	for (unsigned i = 0; i < APRS_MSG_LIST_MAX; i++)
	{
		n += (b->list[i].used && b->list[i].unread) ? 1U : 0U;
	}
	return n;
}

unsigned aprsMsgListCount(const aprsMsgBox_t *b)
{
	unsigned n = 0;

	for (unsigned i = 0; i < APRS_MSG_LIST_MAX; i++)
	{
		n += b->list[i].used ? 1U : 0U;
	}
	return n;
}

void aprsMsgMarkRead(aprsMsgBox_t *b, unsigned idx)
{
	if (idx < APRS_MSG_LIST_MAX)
	{
		b->list[idx].unread = 0U;
	}
}

#endif /* ENABLE_APRS_RX */
