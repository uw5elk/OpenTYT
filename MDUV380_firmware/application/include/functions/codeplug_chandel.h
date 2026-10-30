/*
 * codeplug_chandel.h -- R41: ЧИСТА (без заліза) логіка видалення каналу з рації. Лише static inline; той самий файл
 * використовує codeplug.c (під ENABLE_CHANNEL_DELETE) і хост-тест tests/test_codeplug_chandel.c.
 *
 * ПРАВИЛА (R41 M2).
 *  1. Номер каналу НЕ зсувається. Видалення = очистити біт у масці «канал у роботі» + стерти сам запис (0xFF). Жодного ущільнення таблиці
 *     каналів: зони посилаються на канали за номером.
 *  2. Зона -- це щільний список uint16 (кінець -- перший нуль, див. codeplugZoneGetDataForNumber). Прибрати канал із зони = прибрати
 *     його номер зі списку й зсунути ХВІСТ списку на місце; НОМЕРИ інших каналів не міняються.
 *  3. «Остання позиція в зоні» (LUCZ, байт на зону) після цього треба поправити: позиція -- це індекс у списку зони, а список зсунувся.
 */
#ifndef _OPENGD77_CODEPLUG_CHANDEL_H_
#define _OPENGD77_CODEPLUG_CHANDEL_H_

#include <stdint.h>
#include <stdbool.h>

#define CODEPLUG_CHDEL_CHANNELS_MIN        1
#define CODEPLUG_CHDEL_CHANNELS_MAX        1024
#define CODEPLUG_CHDEL_CHANNELS_PER_BANK   128
#define CODEPLUG_CHDEL_CHANNEL_SIZE        56     /* CODEPLUG_CHANNEL_DATA_STRUCT_SIZE */
#define CODEPLUG_CHDEL_BANK_HEADER_SIZE    16     /* маска «в роботі» одного банку: 128 бітів */

/* ---- маска «канал у роботі» (весь кеш: 8 банків x 16 байтів) -------------------------------------------------------------------- */

static inline bool codeplugChanMaskIsSet(const uint8_t *mask, int index)
{
	if ((index < CODEPLUG_CHDEL_CHANNELS_MIN) || (index > CODEPLUG_CHDEL_CHANNELS_MAX))
	{
		return false;
	}
	index--;
	return ((mask[index / 8] >> (index % 8)) & 0x01) != 0;
}

/* Очищає біт каналу index (1..1024). Повертає true, якщо біт стояв. */
static inline bool codeplugChanMaskClear(uint8_t *mask, int index)
{
	if (!codeplugChanMaskIsSet(mask, index))
	{
		return false;
	}
	index--;
	mask[index / 8] &= (uint8_t)~(1U << (index % 8));
	return true;
}

static inline int codeplugChanMaskCount(const uint8_t *mask)
{
	int n = 0;

	for (int i = 0; i < (CODEPLUG_CHDEL_CHANNELS_MAX / 8); i++)
	{
		n += __builtin_popcount(mask[i]);
	}
	return n;
}

/* Найбільший номер каналу в масці або 0, якщо маска порожня. */
static inline int codeplugChanMaskHighest(const uint8_t *mask)
{
	for (int idx = CODEPLUG_CHDEL_CHANNELS_MAX; idx >= CODEPLUG_CHDEL_CHANNELS_MIN; idx--)
	{
		if (codeplugChanMaskIsSet(mask, idx))
		{
			return idx;
		}
	}
	return 0;
}

/* Найближчий ДАЛІ за after канал у масці з переходом через кінець (after може бути 0 -- тоді це перший канал). 0, якщо в масці нічого нема.
 * Сам канал after не повертається, якщо він єдиний (тоді результат -- він же, якщо ще стоїть у масці). */
static inline int codeplugChanMaskNextInUse(const uint8_t *mask, int after)
{
	for (int step = 1; step <= CODEPLUG_CHDEL_CHANNELS_MAX; step++)
	{
		int idx = ((after - 1 + step) % CODEPLUG_CHDEL_CHANNELS_MAX) + 1;

		if (codeplugChanMaskIsSet(mask, idx))
		{
			return idx;
		}
	}
	return 0;
}

/* ---- адреси ------------------------------------------------------------------------------------------------------------------- */

/* Де лежить запис каналу index (1..1024). Банк 0 (канали 1..128) -- EEPROM: eepromChannels + (index-1)*56. Банки 1..7 -- флеш (адреса кодплага,
 * без FLASH_ADDRESS_OFFSET): flashChannels + 16 * (n / 128) + n * 56, де n = index - 1 - 128; кожні 128 записів стоїть 16-байтова маска наступного
 * банку (так само рахують codeplugChannelGetDataWithOffsetAndLengthForIndex / codeplugChannelSaveDataForIndex). -1, якщо index поза 1..1024. */
static inline int codeplugChanRecordAddr(int index, int eepromChannels, int flashChannels, bool *inFlash)
{
	if ((index < CODEPLUG_CHDEL_CHANNELS_MIN) || (index > CODEPLUG_CHDEL_CHANNELS_MAX))
	{
		return -1;
	}
	index--;
	if (index < CODEPLUG_CHDEL_CHANNELS_PER_BANK)
	{
		*inFlash = false;
		return eepromChannels + index * CODEPLUG_CHDEL_CHANNEL_SIZE;
	}
	index -= CODEPLUG_CHDEL_CHANNELS_PER_BANK;
	*inFlash = true;
	return flashChannels + (CODEPLUG_CHDEL_BANK_HEADER_SIZE * (index / CODEPLUG_CHDEL_CHANNELS_PER_BANK)) + (index * CODEPLUG_CHDEL_CHANNEL_SIZE);
}

/* Де лежить БАЙТ маски, що містить біт каналу index. Банк 0 -- EEPROM: eepromHeader + byteInBank; банки 1..7 -- флеш (адреса кодплага):
 * flashHeader + (bank-1) * (128*56 + 16) + byteInBank. cacheOffset -- байт у загальному кеші маски (8 x 16 байтів). -1, якщо index поза 1..1024. */
static inline int codeplugChanMaskByteAddr(int index, int eepromHeader, int flashHeader, bool *inFlash, int *cacheOffset)
{
	if ((index < CODEPLUG_CHDEL_CHANNELS_MIN) || (index > CODEPLUG_CHDEL_CHANNELS_MAX))
	{
		return -1;
	}
	index--;
	int bank = index / CODEPLUG_CHDEL_CHANNELS_PER_BANK;
	int byteno = (index % CODEPLUG_CHDEL_CHANNELS_PER_BANK) / 8;

	*cacheOffset = index / 8;
	if (bank == 0)
	{
		*inFlash = false;
		return eepromHeader + byteno;
	}
	*inFlash = true;
	return flashHeader + ((bank - 1) * (CODEPLUG_CHDEL_CHANNELS_PER_BANK * CODEPLUG_CHDEL_CHANNEL_SIZE + CODEPLUG_CHDEL_BANK_HEADER_SIZE)) + byteno;
}

/* ---- список каналів зони -------------------------------------------------------------------------------------------------------- */

/* Скільки разів channel стоїть у ЩІЛЬНОМУ списку зони list[0..count). */
static inline int codeplugZoneListCount(const uint16_t *list, int count, uint16_t channel)
{
	int n = 0;

	for (int i = 0; i < count; i++)
	{
		if (list[i] == channel)
		{
			n++;
		}
	}
	return n;
}

/* Нова позиція «останнього каналу в зоні» після прибирання channel зі списку. oldIdx -- позиція ДО прибирання. Канали, що стояли ліворуч від oldIdx і лишаються,
 * зсувають позицію; якщо прибрано сам поточний канал, на його місце стає наступний (а коли він був останнім -- перший: навігація по зоні кільцева).
 * Порожній список -> 0. */
static inline int codeplugZoneIndexAfterRemove(const uint16_t *list, int count, uint16_t channel, int oldIdx)
{
	int kept = 0;
	int newCount = count - codeplugZoneListCount(list, count, channel);

	for (int i = 0; (i < oldIdx) && (i < count); i++)
	{
		if (list[i] != channel)
		{
			kept++;
		}
	}
	if (newCount <= 0)
	{
		return 0;
	}
	return (kept >= newCount) ? 0 : kept;
}

/* Прибирає ВСІ входження channel зі щільного списку list[0..count), решту зсуває вліво, звільнені місця в кінці заповнює нулями (кінець списку --
 * перший нуль). Повертає, скільки входжень прибрано. Номери інших каналів не змінюються. */
static inline int codeplugZoneListRemove(uint16_t *list, int count, uint16_t channel)
{
	int w = 0;

	for (int r = 0; r < count; r++)
	{
		if (list[r] != channel)
		{
			list[w++] = list[r];
		}
	}
	for (int i = w; i < count; i++)
	{
		list[i] = 0;
	}
	return count - w;
}

#endif /* _OPENGD77_CODEPLUG_CHANDEL_H_ */
