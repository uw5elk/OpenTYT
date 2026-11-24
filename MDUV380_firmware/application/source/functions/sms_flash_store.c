/*
 * sms_flash_store.c -- R106-SMSSTORE: кільце слотів зі сховищем SMS DMR у власних секторах SPI-флешу. Опис -- sms_flash_store.h.
 * Лише чиста частина (образ, слоти, CRC); політика запису й міграція блока 7 -- у dmr_sms.c під SMS_STORE_FLASH.
 * Без прапорця файл порожній (типова збірка не змінюється).
 */
#include "functions/sms_flash_store.h"

#if defined(SMS_STORE_FLASH) || defined(SMS_STORE_HOST_TEST)

#include <string.h>

typedef struct
{
	uint32_t magic;
	uint8_t  version;
	uint8_t  zero0;
	uint16_t len;             /* довжина образу */
	uint32_t seq;
	uint32_t crcImg;
	uint32_t crcHdr;          /* CRC32 байтів 0..15 */
	uint8_t  erased[12];      /* не програмуються (0xFF) */
} smsfHdr_t;
_Static_assert(sizeof(smsfHdr_t) == SMSF_HDR_LEN, "slot header must be 32 B");
_Static_assert(SMSF_HDR_PROG_LEN == 20U, "header bytes 0..19 are programmed last");

/* CRC-32 (IEEE, без таблиці -- без нових масивів), ланцюжком: crc = smsfCrc(crc, ...), початок 0. */
static uint32_t smsfCrc(uint32_t crc, const uint8_t *p, uint32_t n)
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
	return SMSF_REGION_ADDR + ((uint32_t)slot * SMSF_SECTOR);
}

/* Серійне порівняння seq: a новіший за b (переповнення u32 безпечне). */
static bool seqNewer(uint32_t a, uint32_t b)
{
	return ((int32_t)(a - b)) > 0;
}

/* Цілий заголовок: magic, версія, довжина в межах, CRC заголовка. */
static bool hdrRead(unsigned slot, smsfHdr_t *h)
{
	if (SPI_Flash_read(slotAddr(slot), (uint8_t *)h, (int)sizeof(*h)) == false)
	{
		return false;
	}
	return (h->magic == SMSF_MAGIC) && (h->version == SMSF_VERSION) && (h->zero0 == 0U) &&
			(h->len >= SMSF_IMG_MIN) && (h->len <= SMSF_IMG_MAX) &&
			(h->crcHdr == smsfCrc(0U, (const uint8_t *)h, SMSF_HDR_CRC_LEN));
}

/* CRC образу у флеші (читання шматками на стеку). */
static bool imgCrcOk(unsigned slot, const smsfHdr_t *h)
{
	uint8_t buf[SMSF_CHUNK];
	uint32_t crc = 0U;
	uint32_t a = slotAddr(slot) + SMSF_HDR_LEN;
	uint32_t left = h->len;

	while (left > 0U)
	{
		uint32_t n = (left > SMSF_CHUNK) ? SMSF_CHUNK : left;

		if (SPI_Flash_read(a, buf, (int)n) == false)
		{
			return false;
		}
		crc = smsfCrc(crc, buf, n);
		a += n;
		left -= n;
	}
	return (crc == h->crcImg);
}

/* Найновіший слот із цілими заголовком і образом, крім позначених у skip. -1 -- нема. */
static int newestSlot(smsfHdr_t *out, uint32_t skip)
{
	int best = -1;
	smsfHdr_t h;

	for (unsigned i = 0U; i < SMSF_SLOTS; i++)
	{
		if (((skip >> i) & 1U) || (hdrRead(i, &h) == false) || (imgCrcOk(i, &h) == false))
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

int smsfLoadCore(uint8_t *img, uint32_t maxLen)
{
	smsfHdr_t h;
	uint32_t skip = 0U;

	for (unsigned tries = 0U; tries < SMSF_SLOTS; tries++)
	{
		int s = newestSlot(&h, skip);

		if (s < 0)
		{
			break;
		}
		if (h.len <= maxLen)
		{
			memset(img, 0, maxLen);
			/* прямо в образ; CRC ще раз -- уже по прочитаному (між двома читаннями флеш міг не дочитатись) */
			if (SPI_Flash_read(slotAddr((unsigned)s) + SMSF_HDR_LEN, img, (int)h.len) && (smsfCrc(0U, img, h.len) == h.crcImg))
			{
				return (int)h.len;
			}
		}
		skip |= (1UL << (unsigned)s);   /* наступний за seq */
	}
	memset(img, 0, maxLen);
	return -1;
}

bool smsfSameCore(const uint8_t *img, uint32_t len)
{
	smsfHdr_t h;

	return (newestSlot(&h, 0U) >= 0) && (h.len == len) && (h.crcImg == smsfCrc(0U, img, len));
}

/* Програмування len байт з адреси a шматками до межі сторінки -- прямо з img (без 256-Б буфера). */
static bool programSpan(uint32_t a, const uint8_t *p, uint32_t len)
{
	while (len > 0U)
	{
		uint32_t room = SMSF_PAGE - (a % SMSF_PAGE);
		uint32_t n = (len < room) ? len : room;

		if (SPI_Flash_programBytes(a, p, (int)n) == false)
		{
			return false;
		}
		a += n;
		p += n;
		len -= n;
	}
	return true;
}

/* Звірка читанням: у флеші рівно p[0..len) з адреси a. */
static bool verifySpan(uint32_t a, const uint8_t *p, uint32_t len)
{
	uint8_t buf[SMSF_CHUNK];

	while (len > 0U)
	{
		uint32_t n = (len > SMSF_CHUNK) ? SMSF_CHUNK : len;

		if ((SPI_Flash_read(a, buf, (int)n) == false) || (memcmp(buf, p, n) != 0))
		{
			return false;
		}
		a += n;
		p += n;
		len -= n;
	}
	return true;
}

bool smsfSaveCore(const uint8_t *img, uint32_t len)
{
	smsfHdr_t h;
	smsfHdr_t newest;
	int nw;
	int target = -1;
	uint32_t oldestSeq = 0U;

	if ((len < SMSF_IMG_MIN) || (len > SMSF_IMG_MAX))
	{
		return false;
	}
	nw = newestSlot(&newest, 0U);
	/* куди: спершу слот без цілого заголовка (порожній/зіпсований), інакше найстаріший; найновіший цілий -- НІКОЛИ */
	for (unsigned i = 0U; i < SMSF_SLOTS; i++)
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

	memset(&h, 0xFF, sizeof(h));
	h.magic = SMSF_MAGIC;
	h.version = SMSF_VERSION;
	h.zero0 = 0U;
	h.len = (uint16_t)len;
	h.seq = (nw >= 0) ? (newest.seq + 1U) : 1U;
	h.crcImg = smsfCrc(0U, img, len);
	h.crcHdr = smsfCrc(0U, (const uint8_t *)&h, SMSF_HDR_CRC_LEN);

	if (SPI_Flash_eraseSector(slotAddr((unsigned)target)) == false)
	{
		return false;
	}
	/* 1) образ */
	if (programSpan(slotAddr((unsigned)target) + SMSF_HDR_LEN, img, len) == false)
	{
		return false;
	}
	/* 2) заголовок -- ОСТАННІМ: до цього слот не вважається цілим */
	if (SPI_Flash_programBytes(slotAddr((unsigned)target), (const uint8_t *)&h, (int)SMSF_HDR_PROG_LEN) == false)
	{
		return false;
	}
	/* 3) звірка читанням: заголовок і образ байт-у-байт */
	return verifySpan(slotAddr((unsigned)target), (const uint8_t *)&h, SMSF_HDR_PROG_LEN) &&
			verifySpan(slotAddr((unsigned)target) + SMSF_HDR_LEN, img, len);
}

#endif /* SMS_STORE_FLASH || SMS_STORE_HOST_TEST */
