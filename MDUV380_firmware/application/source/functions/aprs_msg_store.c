/*
 * aprs_msg_store.c -- R101-APRSMSG: збереження списку «Повідом. APRS» у власних вирівняних секторах SPI-флешу. Опис -- aprs_msg_store.h.
 * Чиста частина -- з APRS_MSG1_UI або APRS_MSG_STORE_HOST_TEST; обгортка (годинник, тики, екран, передача) -- лише в прошивці.
 */
#include "functions/aprs_msg_store.h"

#if defined(APRS_MSG1_UI) || defined(APRS_MSG_STORE_HOST_TEST)

#include <string.h>
#include "functions/sms_format.h"   /* SMS_TIME_VALID_MIN */

/* Стан у вирівнюванні структури: нової пам'яті нема. */
_Static_assert(sizeof(aprsMsgBox_t) == 1336U, "storeSec/storeAge must fit the aprsMsgBox_t padding (1336 B)");

typedef struct
{
	uint32_t magic;
	uint8_t  version;
	uint8_t  count;
	uint8_t  lastNum;
	uint8_t  zero0;
	uint32_t seq;
	uint16_t len;
	uint16_t zero1;
	uint32_t crcData;
	uint32_t crcContent;
	uint32_t crcHdr;          /* CRC32 байтів 0..23 */
	uint8_t  erased[4];       /* не програмуються (0xFF) */
} amsHdr_t;
_Static_assert(sizeof(amsHdr_t) == AMS_HDR_LEN, "slot header must be 32 B");
#define AMS_HDR_PROG_LEN   28   /* програмується одним викликом, ОСТАННІМ */
#define AMS_HDR_CRC_LEN    24

/* CRC-32 (IEEE, без таблиці -- без нових масивів), ланцюжком: crc = amsCrc(crc, ...), початок 0. */
static uint32_t amsCrc(uint32_t crc, const uint8_t *p, uint32_t n)
{
	crc = ~crc;
	while (n-- > 0U)
	{
		crc ^= *p++;
		for (int k = 0; k < 8; k++)
		{
			crc = (crc >> 1) ^ (0xEDB88320UL & (0UL - (crc & 1UL)));
		}
	}
	return ~crc;
}

static uint32_t slotAddr(unsigned slot)
{
	return AMS_REGION_ADDR + ((uint32_t)slot * AMS_SECTOR);
}

/* Серійне порівняння seq: a новіший за b. */
static bool seqNewer(uint32_t a, uint32_t b)
{
	return ((int32_t)(a - b)) > 0;
}

/* ---- потоковий запис/обчислення CRC ---------------------------------------------------------------------- */
typedef struct
{
	uint32_t crcData;
	uint32_t crcContent;
	uint32_t len;
	uint32_t addr;            /* куди програмувати (program) */
	uint32_t n;               /* байтів у buf */
	bool     program;
	bool     ok;
	uint8_t  buf[AMS_CHUNK];
} amsSink_t;

static void sinkFlush(amsSink_t *s)
{
	if (s->program && (s->n > 0U))
	{
		if (SPI_Flash_programBytes(s->addr, s->buf, (int)s->n) == false)
		{
			s->ok = false;
		}
		s->addr += s->n;
	}
	s->n = 0U;
}

/* isTime: у CRC змісту замість 4 байтів часу -- 1 байт «час відомий» (час перераховується щоразу й може «стрибати» на 1 с). */
static void sinkPut(amsSink_t *s, const uint8_t *p, uint32_t n, bool isTime)
{
	s->crcData = amsCrc(s->crcData, p, n);
	if (isTime)
	{
		uint8_t known = ((p[0] | p[1] | p[2] | p[3]) != 0U) ? 1U : 0U;

		s->crcContent = amsCrc(s->crcContent, &known, 1U);
	}
	else
	{
		s->crcContent = amsCrc(s->crcContent, p, n);
	}
	s->len += n;
	if (s->program == false)
	{
		return;
	}
	while (n-- > 0U)
	{
		s->buf[s->n++] = *p++;
		if ((s->n == AMS_CHUNK) || (((s->addr + s->n) % AMS_PAGE) == 0UL))
		{
			sinkFlush(s);   /* шматок ніколи не перетинає межу сторінки */
		}
	}
}

/* Час запису в UTC с для флешу (0 -- невідомо). */
static uint32_t entryUtc(const aprsMsgEntry_t *e, uint32_t now, uint32_t clk)
{
	uint32_t age;

	if (e->noTime == AMS_NOTIME_ABS)
	{
		return e->ms;   /* з флешу, годинника тоді не було -- абсолютний час зберігається як є */
	}
	if ((e->noTime != 0U) || (clk < SMS_TIME_VALID_MIN))
	{
		return 0U;
	}
	age = (now - e->ms) / 1000U;
	if ((age > APRS_MSG_TIME_AGE_MAX_S) || (age > clk) || ((clk - age) < SMS_TIME_VALID_MIN))
	{
		return 0U;
	}
	return clk - age;
}

static uint8_t storedStatus(const aprsMsgEntry_t *e)
{
	/* черга передачі не зберігається: «чекає»/«надіслано» без ACK після перезапуску -- «!» */
	if ((e->dir == AMSG_DIR_OUT) && ((e->status == AMSG_ST_WAIT) || (e->status == AMSG_ST_SENT)))
	{
		return AMSG_ST_NOACK;
	}
	return e->status;
}

static uint8_t lastNumEff(const aprsMsgBox_t *b)
{
	return (b->numSeeded != 0U) ? b->lastNum : 0U;
}

static void putStr(amsSink_t *s, const char *str, uint32_t max)
{
	uint8_t l = 0U;

	while ((l < max) && (str[l] != 0))
	{
		l++;
	}
	sinkPut(s, &l, 1U, false);
	sinkPut(s, (const uint8_t *)str, l, false);
}

/* Образ списку -> s. Повертає кількість записів. */
static uint8_t serialize(const aprsMsgBox_t *b, uint32_t now, uint32_t clk, amsSink_t *s)
{
	uint8_t count = 0U;
	uint8_t ln = lastNumEff(b);

	s->crcContent = amsCrc(s->crcContent, &ln, 1U);   /* номер {NN} -- теж зміст (лише в заголовку, не в даних) */
	for (unsigned i = 0U; i < APRS_MSG_LIST_MAX; i++)
	{
		const aprsMsgEntry_t *e = &b->list[i];
		uint32_t t;
		uint8_t hd[6];

		if (e->used == 0U)
		{
			continue;
		}
		t = entryUtc(e, now, clk);
		hd[0] = (uint8_t)t;
		hd[1] = (uint8_t)(t >> 8);
		hd[2] = (uint8_t)(t >> 16);
		hd[3] = (uint8_t)(t >> 24);
		hd[4] = (uint8_t)((e->dir & 1U) | ((storedStatus(e) & 7U) << 1) | ((e->unread != 0U) ? 0x10U : 0U));
		hd[5] = e->attempts;
		sinkPut(s, hd, 4U, true);
		sinkPut(s, &hd[4], 2U, false);
		putStr(s, e->call, AMS_CALL_MAX);
		putStr(s, e->id, AMS_ID_MAX);
		putStr(s, e->text, AMS_TEXT_MAX);
		count++;
	}
	return count;
}

/* ---- читання ------------------------------------------------------------------------------------------- */
static bool hdrRead(unsigned slot, amsHdr_t *h)
{
	if (SPI_Flash_read(slotAddr(slot), (uint8_t *)h, (int)sizeof(*h)) == false)
	{
		return false;
	}
	return (h->magic == AMS_MAGIC) && (h->version == AMS_VERSION) && (h->count <= APRS_MSG_LIST_MAX) && (h->len <= AMS_PAYLOAD_MAX) &&
			(h->crcHdr == amsCrc(0U, (const uint8_t *)h, AMS_HDR_CRC_LEN));
}

static bool dataCrcOk(unsigned slot, const amsHdr_t *h)
{
	uint8_t buf[AMS_CHUNK];
	uint32_t crc = 0U;
	uint32_t a = slotAddr(slot) + AMS_HDR_LEN;
	uint32_t left = h->len;

	while (left > 0U)
	{
		uint32_t n = (left > AMS_CHUNK) ? AMS_CHUNK : left;

		if (SPI_Flash_read(a, buf, (int)n) == false)
		{
			return false;
		}
		crc = amsCrc(crc, buf, n);
		a += n;
		left -= n;
	}
	return (crc == h->crcData);
}

/* Найновіший слот із цілим заголовком (і, якщо checkData, -- даними), крім позначених у skip. -1 -- нема. */
static int newestSlot(amsHdr_t *out, bool checkData, uint32_t skip)
{
	int best = -1;
	amsHdr_t h;

	for (unsigned i = 0U; i < AMS_SLOTS; i++)
	{
		if (((skip >> i) & 1U) || (hdrRead(i, &h) == false) || (checkData && (dataCrcOk(i, &h) == false)))
		{
			continue;
		}
		if ((best < 0) || seqNewer(h.seq, out->seq))
		{
			best = (int)i;
			*out = h;
		}
	}
	return best;
}

typedef struct
{
	uint32_t addr;
	uint32_t left;
	uint32_t pos;
	uint32_t n;
	bool     ok;
	uint8_t  buf[AMS_CHUNK];
} amsReader_t;

static uint8_t rdByte(amsReader_t *r)
{
	if (r->pos >= r->n)
	{
		uint32_t n = (r->left > AMS_CHUNK) ? AMS_CHUNK : r->left;

		if ((n == 0U) || (SPI_Flash_read(r->addr, r->buf, (int)n) == false))
		{
			r->ok = false;
			return 0U;
		}
		r->addr += n;
		r->left -= n;
		r->n = n;
		r->pos = 0U;
	}
	return r->buf[r->pos++];
}

static bool rdStr(amsReader_t *r, char *out, uint32_t max)
{
	uint8_t l = rdByte(r);

	if (l > max)
	{
		r->ok = false;
		return false;
	}
	for (uint8_t i = 0U; i < l; i++)
	{
		out[i] = (char)rdByte(r);
		if (out[i] == 0)
		{
			r->ok = false;   /* у збереженому рядку нуля бути не може */
		}
	}
	out[l] = 0;
	return r->ok;
}

static void clearList(aprsMsgBox_t *b)
{
	memset(b->list, 0, sizeof(b->list));
}

/* Розібрати слот у список. false -- формат не той (список очищено). */
static bool parseSlot(aprsMsgBox_t *b, unsigned slot, const amsHdr_t *h, uint32_t now, uint32_t clk)
{
	amsReader_t r;

	clearList(b);
	memset(&r, 0, sizeof(r));
	r.addr = slotAddr(slot) + AMS_HDR_LEN;
	r.left = h->len;
	r.ok = true;
	for (unsigned i = 0U; (i < h->count) && r.ok; i++)
	{
		aprsMsgEntry_t *e = &b->list[i];
		uint32_t t = 0U;
		uint8_t fl;
		uint8_t st;

		for (int k = 0; k < 4; k++)
		{
			t |= ((uint32_t)rdByte(&r)) << (8 * k);
		}
		fl = rdByte(&r);
		e->attempts = rdByte(&r);
		st = (uint8_t)((fl >> 1) & 7U);
		if ((fl & 0xE0U) || (st > AMSG_ST_NOACK) || (((fl & 1U) == AMSG_DIR_IN) && (st != AMSG_ST_NONE)))
		{
			r.ok = false;
			break;
		}
		e->used = 1U;
		e->dir = (uint8_t)(fl & 1U);
		e->status = ((e->dir == AMSG_DIR_OUT) && ((st == AMSG_ST_WAIT) || (st == AMSG_ST_SENT))) ? AMSG_ST_NOACK : st;
		e->unread = (uint8_t)(((fl & 0x10U) != 0U) ? 1U : 0U);
		(void)rdStr(&r, e->call, AMS_CALL_MAX);
		(void)rdStr(&r, e->id, AMS_ID_MAX);
		(void)rdStr(&r, e->text, AMS_TEXT_MAX);
		/* час: годинник є -- «мс прийому» = now - вік (за модулем 2^32, вік <= 45 діб); нема -- абсолютний час зберігається в ms (noTime = 2) */
		if (t == 0U)
		{
			e->noTime = 1U;
			e->ms = now;
		}
		else if ((clk >= SMS_TIME_VALID_MIN) && (clk >= t) && ((clk - t) <= APRS_MSG_TIME_AGE_MAX_S))
		{
			e->noTime = 0U;
			e->ms = now - ((clk - t) * 1000U);
		}
		else
		{
			e->noTime = AMS_NOTIME_ABS;
			e->ms = t;
		}
	}
	if ((r.ok == false) || (r.left != 0U) || (r.pos != r.n))
	{
		clearList(b);
		return false;
	}
	return true;
}

int aprsMsgStoreLoadCore(aprsMsgBox_t *b, uint32_t now, uint32_t clk)
{
	uint32_t skip = 0U;

	for (unsigned tries = 0U; tries < AMS_SLOTS; tries++)
	{
		amsHdr_t h;
		int s = newestSlot(&h, true, skip);

		if (s < 0)
		{
			break;
		}
		if (parseSlot(b, (unsigned)s, &h, now, clk))
		{
			if (h.lastNum != 0U)
			{
				b->lastNum = h.lastNum;   /* нумерація {NN} продовжується, а не «розсіюється» заново */
				b->numSeeded = 1U;
			}
			b->storeAge = 0U;
			b->storeSec = (uint8_t)(now / 1000U);
			return s;
		}
		skip |= (1UL << (unsigned)s);   /* CRC цілий, а формат ні -- пробуємо старший */
	}
	clearList(b);
	return -1;
}

static uint32_t contentCrc(const aprsMsgBox_t *b, uint32_t now, uint32_t clk, uint8_t *count)
{
	amsSink_t s;

	memset(&s, 0, sizeof(s));
	*count = serialize(b, now, clk, &s);
	return s.crcContent;
}

bool aprsMsgStoreDirtyCore(const aprsMsgBox_t *b, uint32_t now, uint32_t clk)
{
	amsHdr_t h;
	uint8_t count;
	uint32_t c = contentCrc(b, now, clk, &count);

	if (newestSlot(&h, true, 0U) < 0)   /* з перевіркою даних -- той самий слот, що взяло б завантаження */
	{
		return (count > 0U);   /* у флеші нічого, у списку теж -- писати нічого */
	}
	return (c != h.crcContent);
}

bool aprsMsgStoreSaveCore(aprsMsgBox_t *b, uint32_t now, uint32_t clk)
{
	amsHdr_t h;
	amsHdr_t newest;
	int nw = newestSlot(&newest, true, 0U);
	int target = -1;
	uint32_t oldestSeq = 0U;
	amsSink_t s;
	uint8_t count;

	/* куди: спершу слот без цілого заголовка (порожній/зіпсований), інакше найстаріший; найновіший НІКОЛИ */
	for (unsigned i = 0U; i < AMS_SLOTS; i++)
	{
		if ((int)i == nw)
		{
			continue;
		}
		if (hdrRead(i, &h) == false)
		{
			target = (int)i;
			break;
		}
		if ((target < 0) || seqNewer(oldestSeq, h.seq))
		{
			target = (int)i;
			oldestSeq = h.seq;
		}
	}
	if (target < 0)
	{
		return false;
	}
	/* заголовок -- із «сухого» проходу (лише CRC і довжина) */
	memset(&s, 0, sizeof(s));
	count = serialize(b, now, clk, &s);
	memset(&h, 0xFF, sizeof(h));
	h.magic = AMS_MAGIC;
	h.version = AMS_VERSION;
	h.count = count;
	h.lastNum = lastNumEff(b);
	h.zero0 = 0U;
	h.seq = (nw >= 0) ? (newest.seq + 1U) : 1U;
	h.len = (uint16_t)s.len;
	h.zero1 = 0U;
	h.crcData = s.crcData;
	h.crcContent = s.crcContent;
	h.crcHdr = amsCrc(0U, (const uint8_t *)&h, AMS_HDR_CRC_LEN);

	if (SPI_Flash_eraseSector(slotAddr((unsigned)target)) == false)
	{
		return false;
	}
	/* 1) дані */
	memset(&s, 0, sizeof(s));
	s.program = true;
	s.ok = true;
	s.addr = slotAddr((unsigned)target) + AMS_HDR_LEN;
	(void)serialize(b, now, clk, &s);
	sinkFlush(&s);
	if (s.ok == false)
	{
		return false;
	}
	/* 2) заголовок -- ОСТАННІМ: до цього слот не вважається цілим */
	if (SPI_Flash_programBytes(slotAddr((unsigned)target), (const uint8_t *)&h, AMS_HDR_PROG_LEN) == false)
	{
		return false;
	}
	{
		amsHdr_t back;

		return hdrRead((unsigned)target, &back) && (back.seq == h.seq) && dataCrcOk((unsigned)target, &back);   /* звірка читанням */
	}
}

static void convertAbsTimes(aprsMsgBox_t *b, uint32_t now, uint32_t clk)
{
	if (clk < SMS_TIME_VALID_MIN)
	{
		return;
	}
	for (unsigned i = 0U; i < APRS_MSG_LIST_MAX; i++)
	{
		aprsMsgEntry_t *e = &b->list[i];

		if (e->used && (e->noTime == AMS_NOTIME_ABS) && (clk >= e->ms) && ((clk - e->ms) <= APRS_MSG_TIME_AGE_MAX_S))
		{
			e->ms = now - ((clk - e->ms) * 1000U);   /* годинник з'явився: абсолютний час -> вік */
			e->noTime = 0U;
		}
	}
}

bool aprsMsgStoreTickCore(aprsMsgBox_t *b, uint32_t now, uint32_t clk, bool writeAllowed)
{
	uint8_t sec = (uint8_t)(now / 1000U);

	if (sec == b->storeSec)
	{
		return false;   /* раз на секунду */
	}
	b->storeSec = sec;
	convertAbsTimes(b, now, clk);
	if (aprsMsgStoreDirtyCore(b, now, clk) == false)
	{
		b->storeAge = 0U;
		return false;
	}
	if (b->storeAge < AMS_DEFER_S)
	{
		b->storeAge++;
	}
	if ((b->storeAge < AMS_DEFER_S) || (writeAllowed == false))
	{
		return false;
	}
	b->storeAge = 0U;   /* і при збої: наступна спроба -- через AMS_DEFER_S */
	return aprsMsgStoreSaveCore(b, now, clk);
}

bool aprsMsgStoreFlushCore(aprsMsgBox_t *b, uint32_t now, uint32_t clk)
{
	if (aprsMsgStoreDirtyCore(b, now, clk) == false)
	{
		return false;
	}
	b->storeAge = 0U;
	return aprsMsgStoreSaveCore(b, now, clk);
}

#endif

#if defined(APRS_MSG1_UI) && !defined(APRS_MSG_STORE_HOST_TEST)

#include "functions/aprs.h"
#include "functions/aprs_mode.h"
#include "functions/ticks.h"
#include "functions/trx.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiGlobals.h"

static uint32_t clockNow(void)
{
	return (uint32_t)uiDataGlobal.dateTimeSecs;
}

void aprsMsgStoreLoad(void)
{
	(void)aprsMsgStoreLoadCore(aprsModeMsgBox(), ticksGetMillis(), clockNow());
}

void aprsMsgStoreTick(void)
{
	aprsMsgBox_t *b = aprsModeMsgBox();
	/* не під час передачі (UI-задача стоїть на стиранні десятки мс) і не в режимі CPS (USB-команди теж працюють із флешем) */
	bool allowed = (trxTransmissionEnabled == false) && (b->txActive == 0U) && (aprsBeaconingIsTransmitting() == false) &&
			(menuSystemGetCurrentMenuNumber() != UI_CPS);

	(void)aprsMsgStoreTickCore(b, ticksGetMillis(), clockNow(), allowed);
}

void aprsMsgStoreFlush(void)
{
	(void)aprsMsgStoreFlushCore(aprsModeMsgBox(), ticksGetMillis(), clockNow());
}

#endif
