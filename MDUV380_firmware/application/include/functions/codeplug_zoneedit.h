/*
 * codeplug_zoneedit.h -- R43: ЧИСТА (без заліза) логіка редагування зон з рації: додати канал у кінець, вийняти зі зсувом, створити й видалити зону.
 * Лише static inline; той самий файл збирає хост-тест tests/test_codeplug_zoneedit.c, а codeplug.c викликає ці ж функції.
 *
 * Правила, з яких виходить код (прочитано з codeplug.c, перевірено R41 на залізі):
 *   - список каналів зони ЩІЛЬНИЙ: кінець -- перший нуль; навігація по зоні не переходить дірку, тож виймання = ЗСУВ решти вліво, а не обнулення позиції;
 *   - маска зон «в роботі» (EEPROM 0x8010) може мати ДІРКИ: codeplugZoneMaskNthBit() шукає n-ту ПОСТАВЛЕНУ позицію, тож видалення зони = зняти біт, без зсуву
 *     записів (кодплаг не вимагає щільності зон, на відміну від списку каналів);
 *   - ЗАТЕ номер зони в меню (ординал) = кількість поставлених бітів ліворуч, тож створення/видалення зони зсуває ординали зон правіше. nonVolatileSettings.currentZone
 *     -- саме ординал, і його треба перерахувати (codeplugZoneOrdinalOfBit), інакше рація мовчки стане на ІНШУ зону.
 */
#ifndef _OPENGD77_CODEPLUG_ZONEEDIT_H_
#define _OPENGD77_CODEPLUG_ZONEEDIT_H_

#include <stdint.h>
#include <stdbool.h>
#include "functions/codeplug_zone.h"

/* ---- маска зон ----------------------------------------------------------------------------------------------------------------- */

/* Перший вільний біт (0..CODEPLUG_ZONE_MASK_BITS-1) або -1, якщо вільних нема. Дірку в нумерації зайнято першою: так кодплаг не росте даремно. */
static inline int codeplugZoneMaskFirstFree(const uint8_t *mask)
{
	for (int bit = 0; bit < CODEPLUG_ZONE_MASK_BITS; bit++)
	{
		if (!codeplugZoneMaskBit(mask, bit))
		{
			return bit;
		}
	}
	return -1;
}

static inline void codeplugZoneMaskSetBit(uint8_t *mask, int bit)
{
	if ((bit >= 0) && (bit < CODEPLUG_ZONE_MASK_BITS))
	{
		mask[bit >> 3] = (uint8_t)(mask[bit >> 3] | (1U << (bit & 7)));
	}
}

static inline void codeplugZoneMaskClearBit(uint8_t *mask, int bit)
{
	if ((bit >= 0) && (bit < CODEPLUG_ZONE_MASK_BITS))
	{
		mask[bit >> 3] = (uint8_t)(mask[bit >> 3] & (uint8_t)~(1U << (bit & 7)));
	}
}

/* Ординал зони (позиція в меню) за номером біта: скільки поставлених бітів ЛІВОРУЧ. -1, якщо біт не стоїть (зони нема). */
static inline int codeplugZoneOrdinalOfBit(const uint8_t *mask, int bit)
{
	int n = 0;

	if (!codeplugZoneMaskBit(mask, bit))
	{
		return -1;
	}
	for (int b = 0; b < bit; b++)
	{
		if (codeplugZoneMaskBit(mask, b))
		{
			n++;
		}
	}
	return n;
}

/* Яким має стати nonVolatileSettings.currentZone після зміни маски, щоб рація лишилась на ТІЙ САМІЙ зоні.
 *   curBit -- номер біта поточної зони ДО зміни, або -1, якщо поточна була «Всі канали»;
 *   newMask -- маска ПІСЛЯ зміни.
 * Якщо зона зникла (біта нема) або була «Всі канали» -- «Всі канали» (остання за ординалом = кількість зон). */
static inline int codeplugZoneCurrentAfterChange(const uint8_t *newMask, int curBit)
{
	int ord = (curBit >= 0) ? codeplugZoneOrdinalOfBit(newMask, curBit) : -1;

	return (ord >= 0) ? ord : codeplugZoneMaskCount(newMask);
}

/* ---- список каналів зони -------------------------------------------------------------------------------------------------------- */

/* Позиція channel у щільному списку або -1. */
static inline int codeplugZoneListFind(const uint16_t *list, int count, uint16_t channel)
{
	for (int i = 0; i < count; i++)
	{
		if (list[i] == channel)
		{
			return i;
		}
	}
	return -1;
}

/* Додає channel у КІНЕЦЬ. Повертає нову довжину або -1, якщо список заповнений (count >= cap) чи channel == 0 (нуль -- ознака кінця списку). */
static inline int codeplugZoneListAppend(uint16_t *list, int count, int cap, uint16_t channel)
{
	if ((channel == 0U) || (count < 0) || (count >= cap))
	{
		return -1;
	}
	list[count] = channel;
	return count + 1;
}

/* Виймає запис на позиції pos, решту зсуває вліво, звільнене місце в кінці обнуляє (кінець списку -- нуль). Повертає нову довжину або -1, якщо pos поза списком.
 * Видаляє ЛИШЕ цей запис (на відміну від codeplugZoneListRemove з R41, що прибирає всі входження каналу). */
static inline int codeplugZoneListRemoveAt(uint16_t *list, int count, int pos)
{
	if ((pos < 0) || (pos >= count))
	{
		return -1;
	}
	for (int i = pos; i < (count - 1); i++)
	{
		list[i] = list[i + 1];
	}
	list[count - 1] = 0;
	return count - 1;
}

/* Нова позиція «останнього каналу в зоні» (LUCZ) після виймання запису pos. count -- довжина ДО виймання, oldIdx -- позиція LUCZ ДО.
 *   - зона спорожніла -> 0;
 *   - вийнято запис ЛІВОРУЧ від oldIdx -> oldIdx - 1 (той самий канал);
 *   - вийнято САМ запис oldIdx -> наступний канал зайняв його місце (позиція та сама), а якщо вийнято останній -- перший (0);
 *   - вийнято запис праворуч -> без змін. */
static inline int codeplugZoneIndexAfterRemoveAt(int count, int pos, int oldIdx)
{
	int newCount = count - 1;

	if (newCount <= 0)
	{
		return 0;
	}
	if (pos < oldIdx)
	{
		return oldIdx - 1;
	}
	if (pos == oldIdx)
	{
		return (oldIdx >= newCount) ? 0 : oldIdx;
	}
	return oldIdx;
}

/* ---- вибір каналу зі списку ------------------------------------------------------------------------------------------------------ */

/* n-й (з нуля) канал, що стоїть у масці каналів (8 банків x 16 байтів, біт (номер-1)%8 байта (номер-1)/8), або 0, якщо n поза межами.
 * Список вибору читає канали ПО ОДНОМУ з кодплага, без копії в пам'яті. */
static inline int codeplugChanMaskNth(const uint8_t *mask, int n)
{
	int seen = -1;

	if (n < 0)
	{
		return 0;
	}
	for (int idx = 0; idx < 1024; idx++)
	{
		if (((mask[idx >> 3] >> (idx & 7)) & 0x01U) != 0U)
		{
			if (++seen == n)
			{
				return idx + 1;
			}
		}
	}
	return 0;
}

/* Скільки каналів стоїть у масці (весь кеш: 8 банків x 16 байтів). Це число пунктів у списку вибору. */
static inline int codeplugChanMaskPopcount(const uint8_t *mask)
{
	int n = 0;

	for (int i = 0; i < 128; i++)
	{
		for (int b = 0; b < 8; b++)
		{
			n += (mask[i] >> b) & 0x01;
		}
	}
	return n;
}

#endif /* _OPENGD77_CODEPLUG_ZONEEDIT_H_ */
