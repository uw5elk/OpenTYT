/*
 * codeplug_zone.h -- R22 Z1: ЧИСТА (без заліза) логіка вибору зон: підрахунок бітів маски «зона в роботі»,
 * пошук n-ї зони, єдине правило «зона справжня» і крок валкодера по зонах. Лише static inline -- без нових
 * .c-файлів; той самий файл збирає хост-тест tests/test_codeplug_zone.c.
 *
 * НАВІЩО. Раніше два шляхи вибору зони мали РІЗНІ фільтри: меню «Зони» (buildZoneMap) відкидало «сміттєві»
 * зони, а SK2+енкодер (selectPrevNextZone) -- ні, і валкодер зупинявся на зонах, яких нема в меню (їхні
 * «канали» -- сміття з флешу). Тепер обидва викликають codeplugZoneIsUsable() (codeplug.c), яка спирається
 * на codeplugZoneUsableCheck() звідси.
 */
#ifndef _OPENGD77_CODEPLUG_ZONE_H_
#define _OPENGD77_CODEPLUG_ZONE_H_

#include <stdint.h>
#include <stdbool.h>

/* Скільки бітів маски «зона в роботі» справжні. Маска в EEPROM -- 32 байти (256 бітів), але зон у кодплузі
 * не більше CODEPLUG_ZONES_MAX = 68 (codeplug.c статично перевіряє збіг). Біти за межею -- сміття. */
#define CODEPLUG_ZONE_MASK_BITS   68

static inline bool codeplugZoneMaskBit(const uint8_t *mask, int bit)
{
	return (bit >= 0) && (bit < CODEPLUG_ZONE_MASK_BITS) && (((mask[bit >> 3] >> (bit & 7)) & 0x01U) != 0U);
}

/* Кількість зон у масці (лише перші CODEPLUG_ZONE_MASK_BITS бітів). Віртуальну «Всі канали» не рахує. */
static inline int codeplugZoneMaskCount(const uint8_t *mask)
{
	int n = 0;

	for (int bit = 0; bit < CODEPLUG_ZONE_MASK_BITS; bit++)
	{
		if (codeplugZoneMaskBit(mask, bit))
		{
			n++;
		}
	}
	return n;
}

/* Номер біта n-ї (з нуля) зони маски або -1, якщо такої нема. */
static inline int codeplugZoneMaskNthBit(const uint8_t *mask, int n)
{
	int count = -1;

	for (int bit = 0; bit < CODEPLUG_ZONE_MASK_BITS; bit++)
	{
		if (codeplugZoneMaskBit(mask, bit) && (++count == n))
		{
			return bit;
		}
	}
	return -1;
}

/* Єдине правило «справжня зона»: дані зони прочитано, у ній є канали І перший канал реально існує в таблиці
 * in-use. Це відсіює порожні зони, «сміттєві» (numChannels зі сміття, channels[0] поза межами) і зони, чий
 * перший канал видалили. */
static inline bool codeplugZoneUsableCheck(bool readOk, int numChannelsInZone, bool firstChannelInUse)
{
	return readOk && (numChannelsInZone > 0) && firstChannelInUse;
}

typedef bool (*codeplugZoneUsableFn)(int zoneNum, void *ctx);

/* Крок валкодера по зонах. numZones включає віртуальну «Всі канали» (остання, номер numZones - 1): вона
 * зупиняє крок завжди. Інші зони пропускаються, поки usable() каже «ні». Цикл обмежено numZones кроками --
 * кожна зона відвідується не більше разу, тож завжди завершується (найгірше -- на «Всі канали»).
 * Некоректний cur (поза діапазоном) трактується як «Всі канали». */
static inline int codeplugZoneStep(int cur, int numZones, bool next, codeplugZoneUsableFn usable, void *ctx)
{
	if ((cur < 0) || (cur >= numZones))
	{
		cur = numZones - 1;
	}

	for (int guard = 0; guard < numZones; guard++)
	{
		if (next)
		{
			cur = (cur + 1 >= numZones) ? 0 : (cur + 1);
		}
		else
		{
			cur = (cur == 0) ? (numZones - 1) : (cur - 1);
		}

		if ((cur == (numZones - 1)) || usable(cur, ctx))
		{
			break;
		}
	}

	return cur;
}

#endif /* _OPENGD77_CODEPLUG_ZONE_H_ */
