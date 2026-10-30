/*
 * test_codeplug_zoneedit.c -- R43: редагування зон з рації. Збирається зі СПРАВЖНІМ application/source/functions/codeplug.c (codeplugZoneAddChannel, codeplugZoneRemoveChannelAt,
 * codeplugZoneCreate, codeplugZoneDelete, читання codeplugZoneGetDataForNumber); EEPROM -- образ у пам'яті. Адреси записів рахуються тут НЕЗАЛЕЖНО від прошивки
 * (0x8030 + біт * (16 + 2 * каналів у зоні); маска зон 0x8010).
 *
 * Ключове:
 *   Z1  додати канал у КІНЕЦЬ (запис лише 2 байтів), вийняти зі ЗСУВОМ (кінець списку -- перший нуль, дірки не допустимі), межі (перший, останній, єдиний, заповнена зона);
 *   Z2  створити зону в першому вільному біті, видалити зону (лише біт у масці), межа кількості зон, остання зона, автовизначення розкладки 16/80 каналів;
 *   Z3  поточна зона: ординал перераховується, рація лишається на ТІЙ САМІЙ зоні; видалена поточна -> «Всі канали»; екранна зона currentZone оновлюється.
 * ЗНІМОК-ДИФ усього образу EEPROM у кожному кроці: зміни мають лишитись у дозволеній ділянці.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include "functions/codeplug.h"
#include "functions/codeplug_zone.h"
#include "functions/codeplug_zoneedit.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiLocalisation.h"

#ifndef ZONE_EDIT_ENABLED
#error "test_codeplug_zoneedit.c треба збирати з -DENABLE_ZONE_EDIT -DENABLE_ZONE_RENAME -DENABLE_APRS_RX -DENABLE_AES -DLANGUAGE_BUILD_UKRAINIAN"
#endif

#define EEPROM_SIZE 0x10000
static uint8_t s_eeprom[EEPROM_SIZE];
uint8_t SPI_Flash_sectorbuffer[4096];
CodeplugZone_t currentZone;
static stringsTable_t s_lang;
const stringsTable_t *currentLanguage = &s_lang;
static int s_failLo = -1, s_failHi = -1;
static int s_writes = 0;

bool EEPROM_Read(int address, uint8_t *buf, int size)
{
	if ((address < 0) || ((address + size) > EEPROM_SIZE)) { return false; }
	memcpy(buf, &s_eeprom[address], (size_t)size);
	return true;
}
bool EEPROM_Write(int address, uint8_t *buf, int size)
{
	if ((address < 0) || ((address + size) > EEPROM_SIZE)) { return false; }
	if ((s_failLo >= 0) && (address < s_failHi) && ((address + size) > s_failLo)) { return false; }
	memcpy(&s_eeprom[address], buf, (size_t)size);
	s_writes++;
	return true;
}
bool SPI_Flash_read(uint32_t a, uint8_t *b, int n) { (void)a; memset(b, 0xFF, (size_t)n); return true; }
bool SPI_Flash_write(uint32_t a, uint8_t *b, int n) { (void)a; (void)b; (void)n; return true; }
bool SPI_Flash_writePage(uint32_t a, uint8_t *b) { (void)a; (void)b; return true; }
bool SPI_Flash_eraseSector(uint32_t a) { (void)a; return true; }

extern uint8_t codeplugZonesInUseCache[32];
extern uint8_t codeplugAllChannelsCache[128];

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

#define ADDR_ZONES    0x8030
#define ADDR_ZONEMASK 0x8010
#define ADDR_LUCZ     0x6000

static int stride(void) { return 16 + 2 * codeplugChannelsPerZone; }
static int recAddr(int bit) { return ADDR_ZONES + bit * stride(); }

static void addZone(int bit, const char *name16, const uint16_t *list, int n)
{
	uint8_t *p = &s_eeprom[recAddr(bit)];
	memset(p, 0xFF, 16);
	memcpy(p, name16, strlen(name16));
	memset(p + 16, 0, (size_t)(2 * codeplugChannelsPerZone));
	for (int i = 0; i < n; i++) { memcpy(p + 16 + 2 * i, &list[i], 2); }
	s_eeprom[ADDR_ZONEMASK + bit / 8] |= (uint8_t)(1U << (bit % 8));
}

static void setChannelsInUse(int upTo)
{
	memset(codeplugAllChannelsCache, 0, sizeof(codeplugAllChannelsCache));
	for (int c = 1; c <= upTo; c++) { codeplugAllChannelsCache[(c - 1) / 8] |= (uint8_t)(1U << ((c - 1) % 8)); }
}

static void world(int perZone)
{
	memset(s_eeprom, 0, sizeof(s_eeprom));
	codeplugChannelsPerZone = perZone;
	strcpy((char *)s_lang.all_channels, "All");
	memset(&currentZone, 0, sizeof(currentZone));
	currentZone.NOT_IN_CODEPLUGDATA_indexNumber = -1;
	s_failLo = s_failHi = -1;
	s_writes = 0;
	setChannelsInUse(100);
	/* біти 0, 2, 5 (дірки на 1, 3, 4): номер у списку 0,1,2 НЕ збігається з бітом */
	{ uint16_t a[] = { 1, 2, 3 };     addZone(0, "Alpha", a, 3); }
	{ uint16_t b[] = { 4, 5 };        addZone(2, "Bravo", b, 2); }
	{ uint16_t c[] = { 6, 4 };        addZone(5, "Charlie", c, 2); }
	codeplugZonesInitCache();
	codeplugInitLastUsedChannelInZone();   /* без заголовка LUCZ в образі -> усе нулі */
}

static uint8_t snap[EEPROM_SIZE];
static void snapshot(void) { memcpy(snap, s_eeprom, sizeof(snap)); }
static int stray(int lo, int hi)
{
	int n = 0;
	for (int a = 0; a < EEPROM_SIZE; a++) { if ((s_eeprom[a] != snap[a]) && ((a < lo) || (a >= hi))) { n++; } }
	return n;
}
static int changed(void)
{
	int n = 0;
	for (int a = 0; a < EEPROM_SIZE; a++) { if (s_eeprom[a] != snap[a]) { n++; } }
	return n;
}
/* зміни поза [lo,hi) І поза ділянкою LUCZ (0x6000..0x6000+4+sizeof) */
static int strayNoLucz(int lo, int hi)
{
	int n = 0;
	for (int a = 0; a < EEPROM_SIZE; a++)
	{
		if ((s_eeprom[a] != snap[a]) && ((a < lo) || (a >= hi)) && ((a < ADDR_LUCZ) || (a >= (ADDR_LUCZ + 80)))) { n++; }
	}
	return n;
}

static int listOf(int zoneNum, uint16_t *out)
{
	CodeplugZone_t z;
	memset(&z, 0, sizeof(z));
	codeplugZoneGetDataForNumber(zoneNum, &z);
	for (int i = 0; i < z.NOT_IN_CODEPLUGDATA_numChannelsInZone; i++) { out[i] = z.channels[i]; }
	return z.NOT_IN_CODEPLUGDATA_numChannelsInZone;
}
static bool listIs(int zoneNum, const uint16_t *want, int n)
{
	uint16_t got[80];
	int cnt = listOf(zoneNum, got);
	return (cnt == n) && (memcmp(got, want, (size_t)(2 * n)) == 0);
}
static void shownName(int zoneNum, char *out17)
{
	CodeplugZone_t z;
	memset(&z, 0, sizeof(z));
	codeplugZoneGetDataForNumber(zoneNum, &z);
	codeplugUtilConvertBufToString(z.name, out17, 16);
}
static int tailZero(int bit, int from, int perZone)
{
	/* усі позиції списку від from до кінця запису -- нулі */
	for (int i = from; i < perZone; i++)
	{
		if ((s_eeprom[recAddr(bit) + 16 + 2 * i] != 0) || (s_eeprom[recAddr(bit) + 16 + 2 * i + 1] != 0)) { return 0; }
	}
	return 1;
}

static void runAddRemove(int perZone)
{
	char got[20];
	uint16_t l1[] = { 4, 5, 10 };
	printf("\n--- Z1: каналів у зоні: %d ---\n", perZone);
	world(perZone);
	CHECK(codeplugZonesGetCount() == 4, "зон у списку: 3 справжні + «Всі канали» (%d)", codeplugZonesGetCount());

	/* Z1.1 додавання в кінець; зона №1 -- біт 2 */
	snapshot();
	CHECK(codeplugZoneAddChannel(1, 10) == CODEPLUG_ZONE_EDIT_OK, "Z1.1 канал 10 додано в зону №1 (біт 2)");
	CHECK(listIs(1, l1, 3), "Z1.1 список зони: 4, 5, 10 (у КІНЕЦЬ)");
	CHECK(changed() <= 2, "Z1.1 змінено не більше 2 байтів образу (%d; старший байт номера каналу 0 і так)", changed());
	CHECK(stray(recAddr(2) + 16 + 4, recAddr(2) + 16 + 6) == 0, "Z1.1 і вони -- саме порожня позиція списку №2 (знімок-диф)");
	shownName(1, got); CHECK(strcmp(got, "Bravo") == 0, "Z1.1 назва зони не зачеплена (%s)", got);

	/* Z1.2 дубль */
	snapshot();
	CHECK(codeplugZoneAddChannel(1, 10) == CODEPLUG_ZONE_EDIT_ALREADY_IN_ZONE, "Z1.2 канал, що вже є в зоні, не додається вдруге");
	CHECK(changed() == 0, "Z1.2 образ не змінено");

	/* Z1.3 неіснуючий канал, не та зона */
	snapshot();
	CHECK(codeplugZoneAddChannel(1, 150) == CODEPLUG_ZONE_EDIT_CHANNEL_NOT_IN_USE, "Z1.3 каналу 150 нема в масці");
	CHECK(codeplugZoneAddChannel(1, 0) == CODEPLUG_ZONE_EDIT_CHANNEL_NOT_IN_USE, "Z1.3 канал 0 -- не канал");
	CHECK(codeplugZoneAddChannel(1, 1025) == CODEPLUG_ZONE_EDIT_CHANNEL_NOT_IN_USE, "Z1.3 канал 1025 поза межами");
	CHECK(codeplugZoneAddChannel(3, 7) == CODEPLUG_ZONE_EDIT_NOT_REAL, "Z1.3 «Всі канали» -- не зона для додавання");
	CHECK(codeplugZoneAddChannel(-1, 7) == CODEPLUG_ZONE_EDIT_NOT_REAL, "Z1.3 номер -1");
	CHECK(codeplugZoneAddChannel(9, 7) == CODEPLUG_ZONE_EDIT_NOT_REAL, "Z1.3 номер поза списком");
	CHECK(changed() == 0, "Z1.3 образ не змінено");

	/* Z1.4 заповнена зона: додаємо до межі, далі -- відмова, сусідній запис цілий */
	world(perZone);
	for (int ch = 7; ch <= 100; ch++)
	{
		if (listOf(1, (uint16_t[80]){0}) >= perZone) { break; }
		if (codeplugZoneAddChannel(1, ch) != CODEPLUG_ZONE_EDIT_OK) { break; }
	}
	{
		uint16_t tmp[80];
		CHECK(listOf(1, tmp) == perZone, "Z1.4 зона заповнена до межі (%d каналів)", listOf(1, tmp));
	}
	snapshot();
	{
		int free_ch = 0;
		for (int ch = 1; ch <= 100; ch++) { uint16_t t[80]; int n = listOf(1, t); int in = 0; for (int i = 0; i < n; i++) { if (t[i] == ch) { in = 1; } } if (!in) { free_ch = ch; break; } }
		if (free_ch != 0)
		{
			CHECK(codeplugZoneAddChannel(1, free_ch) == CODEPLUG_ZONE_EDIT_ZONE_FULL, "Z1.4 зона заповнена -- додавання відмовлено словами (ZONE_FULL), канал %d", free_ch);
		}
		else
		{
			CHECK(1, "Z1.4 (усі канали вже в зоні -- ZONE_FULL перевірено для 16)");
		}
	}
	CHECK(changed() == 0, "Z1.4 при відмові образ не змінено, сусідній запис цілий");

	/* Z1.5 додавання в порожню зону та стара мітка LUCZ */
	world(perZone);
	{
		uint16_t none[1] = { 0 };
		addZone(1, "Empty", none, 0);
		codeplugZonesInitCache();
	}
	CHECK(codeplugZonesGetCount() == 5, "Z1.5 є порожня зона (5 у списку)");
	codeplugSetLastUsedChannelInZone(1, 7);   /* сміття від зони, що стояла тут раніше */
	CHECK(codeplugZoneAddChannel(1, 33) == CODEPLUG_ZONE_EDIT_OK, "Z1.5 додано в порожню зону (№1 -- біт 1)");
	{
		uint16_t w[] = { 33 };
		CHECK(listIs(1, w, 1), "Z1.5 список: один канал");
	}
	CHECK(codeplugGetLastUsedChannelInZone(1) == 0, "Z1.5 «останній канал у зоні» став 0 (було сміття 7 поза списком)");

	/* Z1.6 збій запису */
	world(perZone);
	snapshot();
	s_failLo = recAddr(2); s_failHi = recAddr(2) + stride();
	CHECK(codeplugZoneAddChannel(1, 10) == CODEPLUG_ZONE_EDIT_WRITE_ERROR, "Z1.6 збій EEPROM -> WRITE_ERROR");
	CHECK(changed() == 0, "Z1.6 образ не змінено");
	s_failLo = s_failHi = -1;

	/* Z1.7 екранна зона оновлюється */
	world(perZone);
	codeplugZoneGetDataForNumber(1, &currentZone);
	CHECK(currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone == 2, "Z1.7 currentZone: 2 канали до");
	codeplugZoneAddChannel(1, 20);
	CHECK(currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone == 3 && currentZone.channels[2] == 20, "Z1.7 currentZone бачить новий канал без перезапуску");

	/* ----- вийняти ----- */
	printf("--- Z1b: виймання зі зсувом (%d) ---\n", perZone);
	{
		uint16_t a1[] = { 1, 3 }, a2[] = { 2, 3 }, a3[] = { 1, 2 };
		world(perZone);
		snapshot();
		CHECK(codeplugZoneRemoveChannelAt(0, 1) == CODEPLUG_ZONE_EDIT_OK, "Z1b.1 вийнято середній (поз. 1) із зони №0 (1,2,3)");
		CHECK(listIs(0, a1, 2), "Z1b.1 решта зсунулась ліворуч: 1, 3 (без дірки)");
		CHECK(tailZero(0, 2, perZone), "Z1b.1 звільнене місце в кінці списку -- нуль");
		CHECK(strayNoLucz(recAddr(0) + 16 + 2, recAddr(0) + 16 + 6) == 0, "Z1b.1 змінено лише хвіст списку від позиції 1 (знімок-диф)");
		CHECK(codeplugAllChannelsIndexIsInUse(2), "Z1b.1 САМ канал 2 лишився в масці «в роботі»");
		{
			uint16_t b[] = { 4, 5 };
			CHECK(listIs(1, b, 2), "Z1b.1 сусідня зона не зачеплена");
		}

		world(perZone);
		CHECK(codeplugZoneRemoveChannelAt(0, 0) == CODEPLUG_ZONE_EDIT_OK && listIs(0, a2, 2), "Z1b.2 вийнято ПЕРШИЙ: 2, 3");
		world(perZone);
		CHECK(codeplugZoneRemoveChannelAt(0, 2) == CODEPLUG_ZONE_EDIT_OK && listIs(0, a3, 2), "Z1b.3 вийнято ОСТАННІЙ: 1, 2");
		CHECK(tailZero(0, 2, perZone), "Z1b.3 хвіст нульовий");

		world(perZone);
		{
			uint16_t one[] = { 9 };
			addZone(1, "Solo", one, 1);
			codeplugZonesInitCache();
		}
		CHECK(codeplugZoneRemoveChannelAt(1, 0) == CODEPLUG_ZONE_EDIT_OK, "Z1b.4 вийнято ЄДИНИЙ канал зони");
		{
			CodeplugZone_t z;
			memset(&z, 0, sizeof(z));
			codeplugZoneGetDataForNumber(1, &z);
			CHECK(z.NOT_IN_CODEPLUGDATA_numChannelsInZone == 0, "Z1b.4 зона порожня, але ЛИШИЛАСЬ (запис і назва цілі)");
		}
		CHECK(codeplugAllChannelsIndexIsInUse(9), "Z1b.4 канал 9 лишився в масці");

		world(perZone);
		snapshot();
		CHECK(codeplugZoneRemoveChannelAt(0, 3) == CODEPLUG_ZONE_EDIT_BAD_POSITION, "Z1b.5 позиція = довжина списку -> BAD_POSITION");
		CHECK(codeplugZoneRemoveChannelAt(0, -1) == CODEPLUG_ZONE_EDIT_BAD_POSITION, "Z1b.5 позиція -1 -> BAD_POSITION");
		CHECK(codeplugZoneRemoveChannelAt(3, 0) == CODEPLUG_ZONE_EDIT_NOT_REAL, "Z1b.5 «Всі канали» -> NOT_REAL");
		CHECK(changed() == 0, "Z1b.5 образ не змінено");

		/* канал 4 стоїть у двох зонах (Bravo і Charlie) -- виймання з однієї не чіпає іншу */
		world(perZone);
		CHECK(codeplugZoneRemoveChannelAt(1, 0) == CODEPLUG_ZONE_EDIT_OK, "Z1b.6 канал 4 вийнято з Bravo");
		{
			uint16_t ch[] = { 6, 4 };
			CHECK(listIs(2, ch, 2), "Z1b.6 у Charlie канал 4 лишився");
		}
	}

	/* Z1b.7 «останній канал у зоні» (LUCZ) */
	printf("--- Z1b.7: LUCZ ---\n");
	world(perZone);
	codeplugSetLastUsedChannelInZone(0, 1);
	codeplugZoneRemoveChannelAt(0, 1);
	CHECK(codeplugGetLastUsedChannelInZone(0) == 1, "Z1b.7a вийнято САМ запис під LUCZ (поз. 1 з 3) -> LUCZ=1 (наступний канал зайняв місце)");
	world(perZone);
	codeplugSetLastUsedChannelInZone(0, 2);
	codeplugZoneRemoveChannelAt(0, 2);
	CHECK(codeplugGetLastUsedChannelInZone(0) == 0, "Z1b.7b вийнято ОСТАННІЙ під LUCZ -> LUCZ=0 (перший)");
	world(perZone);
	codeplugSetLastUsedChannelInZone(0, 2);
	codeplugZoneRemoveChannelAt(0, 0);
	CHECK(codeplugGetLastUsedChannelInZone(0) == 1, "Z1b.7c вийнято запис ЛІВОРУЧ від LUCZ -> LUCZ-1 (той самий канал)");
	world(perZone);
	codeplugSetLastUsedChannelInZone(0, 0);
	codeplugZoneRemoveChannelAt(0, 2);
	CHECK(codeplugGetLastUsedChannelInZone(0) == 0, "Z1b.7d вийнято запис праворуч від LUCZ -> LUCZ без змін");
	world(perZone);
	{
		uint16_t one[] = { 9 };
		addZone(1, "Solo", one, 1);
		codeplugZonesInitCache();
	}
	codeplugSetLastUsedChannelInZone(1, 0);
	codeplugZoneRemoveChannelAt(1, 0);
	CHECK(codeplugGetLastUsedChannelInZone(1) == 0, "Z1b.7e єдиний канал -> LUCZ=0");

	/* Z1b.8 збій запису під час виймання: LUCZ не змінюється */
	world(perZone);
	codeplugSetLastUsedChannelInZone(0, 0);
	snapshot();
	s_failLo = recAddr(0); s_failHi = recAddr(0) + stride();
	CHECK(codeplugZoneRemoveChannelAt(0, 0) == CODEPLUG_ZONE_EDIT_WRITE_ERROR, "Z1b.8 збій EEPROM -> WRITE_ERROR");
	CHECK(changed() == 0, "Z1b.8 образ не змінено");
	s_failLo = s_failHi = -1;

	/* Z1b.9 екранна зона */
	world(perZone);
	codeplugZoneGetDataForNumber(0, &currentZone);
	codeplugZoneRemoveChannelAt(0, 1);
	CHECK(currentZone.NOT_IN_CODEPLUGDATA_numChannelsInZone == 2 && currentZone.channels[1] == 3, "Z1b.9 currentZone бачить зсув без перезапуску");

	/* Z1b.10 дубль у списку: вийнято лише один запис */
	world(perZone);
	{
		uint16_t dup[] = { 5, 5, 6 };
		uint16_t want[] = { 5, 6 };
		addZone(1, "Dup", dup, 3);
		codeplugZonesInitCache();
		CHECK(codeplugZoneRemoveChannelAt(1, 0) == CODEPLUG_ZONE_EDIT_OK && listIs(1, want, 2), "Z1b.10 дубль 5,5,6: вийнято один запис -> 5, 6");
	}
}

static void runCreateDelete(int perZone)
{
	char got[20];
	int16_t cur;
	int ord = -1;
	printf("\n--- Z2/Z3: створити/видалити зону (каналів у зоні: %d) ---\n", perZone);

	/* Z2.1 створення в першому вільному біті (дірка 1) */
	world(perZone);
	cur = 3;   /* «Всі канали» */
	snapshot();
	CHECK(codeplugZoneCreate("Delta", &cur, &ord) == CODEPLUG_ZONE_EDIT_OK, "Z2.1 зону «Delta» створено");
	CHECK(codeplugZonesGetCount() == 5, "Z2.1 зон у списку стало 4 справжні + «Всі канали»");
	CHECK((s_eeprom[ADDR_ZONEMASK] & 0x02) != 0, "Z2.1 біт 1 (перша дірка) у масці поставлено");
	CHECK(ord == 1, "Z2.1 нова зона має ординал 1 (між Alpha і Bravo): %d", ord);
	shownName(1, got); CHECK(strcmp(got, "Delta") == 0, "Z2.1 меню бачить нову зону на місці №1 (%s)", got);
	CHECK(listIs(1, (uint16_t[]){0}, 0), "Z2.1 список каналів порожній");
	CHECK(strayNoLucz(recAddr(1), recAddr(1) + stride()) == 1, "Z2.1 поза записом нової зони змінився рівно 1 байт (байт маски) -- решту образу не зачеплено");
	{
		int ok = 1;
		for (int i = 0; i < 2 * perZone; i++) { if (s_eeprom[recAddr(1) + 16 + i] != 0) { ok = 0; } }
		CHECK(ok, "Z2.1 канали нової зони -- нулі, не 0xFF (сміття зникло б з навігації)");
	}
	CHECK(cur == 4, "Z2.1 «Всі канали» тепер №4: cur=%d", cur);

	/* Z2.2 назви */
	world(perZone);
	cur = 0; snapshot(); s_writes = 0;
	CHECK(codeplugZoneCreate("", &cur, &ord) == CODEPLUG_ZONE_EDIT_NAME_EMPTY, "Z2.2 порожня назва -> NAME_EMPTY");
	CHECK(codeplugZoneCreate("12345678901234567", &cur, &ord) == CODEPLUG_ZONE_EDIT_NAME_TOO_LONG, "Z2.2 17 символів -> NAME_TOO_LONG");
	CHECK(codeplugZoneCreate("123456789012345\xFF", &cur, &ord) == CODEPLUG_ZONE_EDIT_NAME_TOO_LONG, "Z2.2 16 символів із «я» наприкінці -> відхилено");
	CHECK(changed() == 0 && s_writes == 0, "Z2.2 при відхиленні назви нічого не записано");
	CHECK(codeplugZoneCreate("\xC7\xEE\xF0\xFF", &cur, &ord) == CODEPLUG_ZONE_EDIT_OK, "Z2.2 «Зоря» (кінцева «я») створено");
	{
		const uint8_t *p = &s_eeprom[recAddr(ord < 0 ? 1 : 1)];
		(void)p;
		int bit = codeplugZoneMaskNthBit(codeplugZonesInUseCache, ord);
		const uint8_t *r = &s_eeprom[recAddr(bit)];
		CHECK(r[3] == 0xFF && r[4] == 0x00, "Z2.2 «я» (0xFF) і за нею хвіст 0x00: читання не з'їсть літеру");
	}
	shownName(ord, got); CHECK(strcmp(got, "\xC7\xEE\xF0\xFF") == 0, "Z2.2 назва читається цілою");

	/* Z2.3 межа кількості зон: заповнюємо до CODEPLUG_ZONES_MAX */
	world(perZone);
	cur = 0;
	{
		int made = 0;
		char nm[8];
		while (made < 200)
		{
			snprintf(nm, sizeof(nm), "Z%d", made);
			if (codeplugZoneCreate(nm, &cur, &ord) != CODEPLUG_ZONE_EDIT_OK) { break; }
			made++;
		}
		CHECK(codeplugZonesGetCount() - 1 == (int)CODEPLUG_ZONES_MAX, "Z2.3 зон стало рівно %d (межа CODEPLUG_ZONES_MAX), створено %d", (int)CODEPLUG_ZONES_MAX, made);
	}
	snapshot(); s_writes = 0;
	CHECK(codeplugZoneCreate("Extra", &cur, &ord) == CODEPLUG_ZONE_EDIT_NO_FREE_ZONE, "Z2.3 понад межу -> NO_FREE_ZONE (говоримо словами)");
	CHECK(changed() == 0 && s_writes == 0, "Z2.3 при відмові нічого не записано");

	/* Z2.4 видалення: лише біт маски; запис не стирається; сусіди цілі */
	world(perZone);
	cur = 3;
	snapshot();
	CHECK(codeplugZoneDelete(1, &cur) == CODEPLUG_ZONE_EDIT_OK, "Z2.4 зону №1 (Bravo, біт 2) видалено");
	CHECK(codeplugZonesGetCount() == 3, "Z2.4 лишилось 2 справжні + «Всі канали»");
	CHECK(strayNoLucz(ADDR_ZONEMASK, ADDR_ZONEMASK + 32) == 0, "Z2.4 змінено лише маску зон (запис видаленої зони НЕ стирається; записи сусідів цілі)");
	CHECK((s_eeprom[ADDR_ZONEMASK] & 0x04) == 0 && (s_eeprom[ADDR_ZONEMASK] & 0x21) == 0x21, "Z2.4 знято біт 2, біти 0 і 5 стоять");
	shownName(0, got); CHECK(strcmp(got, "Alpha") == 0, "Z2.4 №0 = Alpha (%s)", got);
	shownName(1, got); CHECK(strcmp(got, "Charlie") == 0, "Z2.4 №1 = Charlie: ординал зсунувся, ЗАПИС ні (%s)", got);
	CHECK(cur == 2, "Z2.4 «Всі канали» тепер №2: cur=%d", cur);
	CHECK(codeplugAllChannelsIndexIsInUse(4) && codeplugAllChannelsIndexIsInUse(5), "Z2.4 канали видаленої зони (4, 5) ЦІЛІ в масці каналів");
	{
		uint16_t ch[] = { 6, 4 };
		CHECK(listIs(1, ch, 2), "Z2.4 у Charlie канал 4 лишився");
	}
	CHECK(codeplugZoneDelete(2, &cur) == CODEPLUG_ZONE_EDIT_NOT_REAL, "Z2.4 «Всі канали» видалити не можна");
	CHECK(codeplugZoneDelete(-1, &cur) == CODEPLUG_ZONE_EDIT_NOT_REAL, "Z2.4 номер -1 не зона");

	/* Z2.5 остання зона: видаляємо всі, лишаються «Всі канали» */
	world(perZone);
	cur = 0;
	CHECK(codeplugZoneDelete(2, &cur) == CODEPLUG_ZONE_EDIT_OK && codeplugZoneDelete(1, &cur) == CODEPLUG_ZONE_EDIT_OK && codeplugZoneDelete(0, &cur) == CODEPLUG_ZONE_EDIT_OK,
			"Z2.5 видалено всі три зони");
	CHECK(codeplugZonesGetCount() == 1, "Z2.5 у списку лише «Всі канали» (%d)", codeplugZonesGetCount());
	{
		CodeplugZone_t z;
		memset(&z, 0, sizeof(z));
		CHECK(codeplugZoneGetDataForNumber(0, &z) && CODEPLUG_ZONE_IS_ALLCHANNELS(z), "Z2.5 №0 = віртуальна «Всі канали»");
		CHECK(codeplugZoneIsUsable(0, NULL), "Z2.5 і вона придатна");
	}
	CHECK(cur == 0, "Z2.5 поточна = 0 = «Всі канали»: cur=%d", cur);
	CHECK(codeplugZoneStep(0, 1, true, NULL, NULL) == 0, "Z2.5 крок валкодера по зонах лишається на «Всі канали» (не зависає)");
	CHECK(codeplugZoneCreate("Again", &cur, &ord) == CODEPLUG_ZONE_EDIT_OK && ord == 0 && cur == 1, "Z2.5 зону можна створити знову (з нуля); «Всі канали» стала №1");

	/* Z2.6 збої запису */
	world(perZone);
	cur = 3; snapshot();
	s_failLo = ADDR_ZONEMASK; s_failHi = ADDR_ZONEMASK + 32;
	CHECK(codeplugZoneCreate("Fail", &cur, &ord) == CODEPLUG_ZONE_EDIT_WRITE_ERROR, "Z2.6 збій запису МАСКИ при створенні -> WRITE_ERROR");
	CHECK(codeplugZonesGetCount() == 4 && cur == 3, "Z2.6 кеш маски й поточна зона не змінились (зона невидима: запис є, біта нема)");
	s_failLo = s_failHi = -1;
	world(perZone);
	cur = 3; snapshot();
	s_failLo = recAddr(1); s_failHi = recAddr(1) + stride();
	CHECK(codeplugZoneCreate("Fail", &cur, &ord) == CODEPLUG_ZONE_EDIT_WRITE_ERROR, "Z2.6 збій запису ЗАПИСУ зони -> WRITE_ERROR");
	CHECK(changed() == 0 && codeplugZonesGetCount() == 4, "Z2.6 образ не змінено, маска не торкнута (порядок: спершу запис, потім біт)");
	s_failLo = s_failHi = -1;
	world(perZone);
	cur = 3; snapshot();
	s_failLo = ADDR_ZONEMASK; s_failHi = ADDR_ZONEMASK + 32;
	CHECK(codeplugZoneDelete(1, &cur) == CODEPLUG_ZONE_EDIT_WRITE_ERROR, "Z2.6 збій запису маски при видаленні -> WRITE_ERROR");
	CHECK(codeplugZonesGetCount() == 4 && cur == 3, "Z2.6 кеш маски не змінено, зона на місці");
	s_failLo = s_failHi = -1;

	/* Z2.7 автовизначення розкладки 16/80 за байтом 0x806F переживає створення/видалення */
	world(perZone);
	cur = 0;
	codeplugZoneDelete(0, &cur);                       /* знімаємо біт 0 */
	codeplugZoneCreate("Nova", &cur, &ord);            /* займе біт 0 (перший вільний) */
	codeplugZoneCreate("ABCDEFGHIJKLMNOP", &cur, &ord);/* 16 символів: займе біт 1 */
	{
		int saved = codeplugChannelsPerZone;
		codeplugChannelsPerZone = 16;
		codeplugInitChannelsPerZone();
		CHECK(codeplugChannelsPerZone == perZone, "Z2.7 після створень codeplugInitChannelsPerZone() визначає ту саму розкладку: %d (байт 0x806F = 0x%02X)", codeplugChannelsPerZone, s_eeprom[0x806F]);
		codeplugChannelsPerZone = saved;
	}

	/* ----- Z3: поточна зона ----- */
	printf("--- Z3: поточна зона (%d) ---\n", perZone);
	world(perZone);
	cur = 2;   /* Charlie (біт 5) */
	codeplugZoneDelete(0, &cur);
	CHECK(cur == 1, "Z3.1 видалено зону ПЕРЕД поточною -> ординал поточної 2 -> 1 (та сама Charlie): %d", cur);
	shownName(cur, got); CHECK(strcmp(got, "Charlie") == 0, "Z3.1 за новим ординалом справді Charlie (%s)", got);

	world(perZone);
	cur = 2;
	codeplugZoneDelete(2, &cur);
	CHECK(cur == 2 && codeplugZonesGetCount() - 1 == 2, "Z3.2 видалено САМУ поточну -> «Всі канали» (№2 = кількість зон): %d", cur);

	world(perZone);
	cur = 1;   /* Bravo */
	codeplugZoneDelete(2, &cur);
	CHECK(cur == 1, "Z3.3 видалено зону ПІСЛЯ поточної -> ординал без змін: %d", cur);

	world(perZone);
	cur = 2;   /* Charlie, біт 5 */
	codeplugZoneCreate("Gap", &cur, &ord);   /* займе біт 1 -- ліворуч від Charlie */
	CHECK(cur == 3, "Z3.4 нова зона в дірці ЛІВОРУЧ від поточної -> ординал 2 -> 3: %d", cur);
	shownName(cur, got); CHECK(strcmp(got, "Charlie") == 0, "Z3.4 за новим ординалом справді Charlie (%s)", got);

	world(perZone);
	cur = 0;
	codeplugZoneCreate("Gap", &cur, &ord);
	CHECK(cur == 0, "Z3.5 нова зона ПІСЛЯ поточної (Alpha, №0) -> ординал без змін: %d", cur);

	world(perZone);
	cur = 3;   /* «Всі канали» */
	codeplugZoneCreate("Gap", &cur, &ord);
	CHECK(cur == 4, "Z3.6 поточна «Всі канали»: після створення вона №4 (cur=%d)", cur);
	codeplugZoneDelete(1, &cur);
	CHECK(cur == 3, "Z3.6 і після видалення -- №3 (cur=%d)", cur);

	world(perZone);
	CHECK(codeplugZoneCreate("NoCur", NULL, NULL) == CODEPLUG_ZONE_EDIT_OK, "Z3.7 NULL замість поточної зони і ординала дозволено (створення)");
	CHECK(codeplugZoneDelete(0, NULL) == CODEPLUG_ZONE_EDIT_OK, "Z3.7 NULL дозволено (видалення)");

	/* Z3.8 після видалення в LUCZ біта нуль, створення на тому ж біті стартує з 0 */
	world(perZone);
	cur = 3;
	codeplugSetLastUsedChannelInZone(2, 1);
	codeplugZoneDelete(1, &cur);   /* біт 2 */
	CHECK(codeplugGetLastUsedChannelInZone(2) == 0, "Z3.8 LUCZ видаленої зони обнулено");
	codeplugSetLastUsedChannelInZone(1, 7);
	codeplugZoneCreate("New", &cur, &ord);   /* біт 1 */
	CHECK(codeplugGetLastUsedChannelInZone(1) == 0, "Z3.8 LUCZ нової зони стартує з 0 (стара мітка 7 скинута)");
}

int main(void)
{
	runAddRemove(80);
	runAddRemove(16);
	runCreateDelete(80);
	runCreateDelete(16);

	/* чиста логіка: першого вільного біта немає в повній масці, порядок ординалів */
	{
		uint8_t m[32];
		memset(m, 0, sizeof(m));
		CHECK(codeplugZoneMaskFirstFree(m) == 0, "P1 порожня маска -> перший вільний 0");
		codeplugZoneMaskSetBit(m, 0); codeplugZoneMaskSetBit(m, 1); codeplugZoneMaskSetBit(m, 3);
		CHECK(codeplugZoneMaskFirstFree(m) == 2, "P1 дірка на 2 займається першою");
		CHECK(codeplugZoneOrdinalOfBit(m, 3) == 2 && codeplugZoneOrdinalOfBit(m, 2) == -1, "P1 ординал бита 3 = 2, неіснуючого -- -1");
		for (int b = 0; b < CODEPLUG_ZONE_MASK_BITS; b++) { codeplugZoneMaskSetBit(m, b); }
		CHECK(codeplugZoneMaskFirstFree(m) == -1 && codeplugZoneMaskCount(m) == (int)CODEPLUG_ZONES_MAX, "P1 повна маска -> вільного нема");
		codeplugZoneMaskSetBit(m, 70);
		CHECK(codeplugZoneMaskCount(m) == (int)CODEPLUG_ZONES_MAX, "P1 біт за межею 68 не рахується");
	}

	/* список вибору каналу: n-й канал із маски, кількість */
	{
		world(80);
		CHECK(codeplugZoneEditChannelCount() == 100, "P2 у масці 100 каналів (%d)", codeplugZoneEditChannelCount());
		CHECK(codeplugZoneEditNthChannel(0) == 1 && codeplugZoneEditNthChannel(99) == 100 && codeplugZoneEditNthChannel(100) == 0 && codeplugZoneEditNthChannel(-1) == 0,
				"P2 перший 1, останній 100, поза межами 0");
		codeplugAllChannelsCache[0] &= (uint8_t)~0x06;   /* канали 2 і 3 зникли: дірка в нумерації */
		CHECK(codeplugZoneEditChannelCount() == 98, "P2 після дірки -- 98 каналів (%d)", codeplugZoneEditChannelCount());
		CHECK(codeplugZoneEditNthChannel(0) == 1 && codeplugZoneEditNthChannel(1) == 4 && codeplugZoneEditNthChannel(97) == 100, "P2 нумерація проходить через дірку: 1, 4, ..., 100");
		codeplugAllChannelsCache[127] |= 0x80;           /* канал 1024 (флеш-банк 7) */
		CHECK(codeplugZoneEditNthChannel(98) == 1024 && codeplugZoneEditChannelCount() == 99, "P2 канал 1024 (останній банк) доступний у списку вибору");
	}

	printf("\n%s (%d провалів)\n", fails ? "ПРОВАЛ" : "OK", fails);
	return fails ? 1 : 0;
}
