/*
 * test_codeplug_zonerename.c -- R42: перейменування зони. Збирається зі СПРАВЖНІМ application/source/functions/codeplug.c (codeplugZoneRename, читання назви
 * codeplugZoneGetDataForNumber + codeplugUtilConvertBufToString, запис codeplugUtilConvertStringToBuf з хвостом 0x00 -- R34/R36); EEPROM -- образ у пам'яті.
 * Адреси запису зони рахуються тут НЕЗАЛЕЖНО від прошивки (0x8030 + біт * (16 + 2 * каналів у зоні)).
 *
 * Ключове: ЗНІМОК-ДИФ усього образу EEPROM -- після перейменування змінитися можуть лише 16 байтів назви потрібної зони; список каналів зони, сусідні зони,
 * маска зон, канали -- ні. Кінцева «я» (0xFF у cp1251) переживає запис і читання.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include "functions/codeplug.h"
#include "functions/codeplug_zone.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiLocalisation.h"

#ifndef ZONE_RENAME_ENABLED
#error "test_codeplug_zonerename.c треба збирати з -DENABLE_ZONE_RENAME -DENABLE_APRS_RX -DENABLE_AES -DLANGUAGE_BUILD_UKRAINIAN"
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

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

#define ADDR_ZONES    0x8030
#define ADDR_ZONEMASK 0x8010

static int stride(void) { return 16 + 2 * codeplugChannelsPerZone; }

static void addZone(int bit, const char *name16, const uint16_t *list, int n)
{
	uint8_t *p = &s_eeprom[ADDR_ZONES + bit * stride()];
	memset(p, 0xFF, 16);
	memcpy(p, name16, strlen(name16));
	memset(p + 16, 0, (size_t)(2 * codeplugChannelsPerZone));
	for (int i = 0; i < n; i++) { memcpy(p + 16 + 2 * i, &list[i], 2); }
	s_eeprom[ADDR_ZONEMASK + bit / 8] |= (uint8_t)(1U << (bit % 8));
}

static void world(int perZone)
{
	memset(s_eeprom, 0, sizeof(s_eeprom));
	codeplugChannelsPerZone = perZone;
	strcpy((char *)s_lang.all_channels, "All");
	memset(&currentZone, 0, sizeof(currentZone));
	currentZone.NOT_IN_CODEPLUGDATA_indexNumber = -1;
	s_failLo = s_failHi = -1;
	/* біти 0, 2, 5 -- щоб номер зони в списку (0,1,2) НЕ збігався з бітом (0,2,5): перевірка, що пишемо за бітом, а не за номером */
	{ uint16_t a[] = { 1, 2, 3 };  addZone(0, "Alpha", a, 3); }
	{ uint16_t b[] = { 4, 5 };     addZone(2, "Bravo", b, 2); }
	{ uint16_t c[] = { 6 };        addZone(5, "Charlie", c, 1); }
	codeplugZonesInitCache();
}

static uint8_t snap[EEPROM_SIZE];
static void snapshot(void) { memcpy(snap, s_eeprom, sizeof(snap)); }
/* скільки байтів образу змінилося поза [lo, hi) */
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

/* назва зони з номером zoneNum у списку, як її показує меню (ConvertBufToString) */
static void shownName(int zoneNum, char *out17)
{
	CodeplugZone_t z;
	memset(&z, 0, sizeof(z));
	codeplugZoneGetDataForNumber(zoneNum, &z);
	codeplugUtilConvertBufToString(z.name, out17, 16);
}

/* cp1251: «Зоря» = CD E0 F0 FF? -- Ні: З=C7 о=EE р=F0 я=FF */
#define ZORYA   "\xC7\xEE\xF0\xFF"
#define NADIYA  "\xCD\xE0\xE4\xB3\xFF"          /* «Надія» (і = B3), закінчується на я */
#define POLYANA "\xCF\xEE\xEB\xFF\xED\xE0"      /* «Поляна»: я посеред назви */

static void run(int perZone)
{
	char got[20];
	printf("\n--- каналів у зоні: %d ---\n", perZone);

	/* список: 0 -> біт 0, 1 -> біт 2, 2 -> біт 5, 3 -> «Всі канали» */
	world(perZone);
	CHECK(codeplugZonesGetCount() == 4, "зон у списку: 3 справжні + «Всі канали» (%d)", codeplugZonesGetCount());

	/* Z2.1: звичайна назва, зона з бітом 2 (номер у списку 1) */
	snapshot();
	CHECK(codeplugZoneRename(1, "Novyny") == CODEPLUG_ZONE_RENAME_OK, "Z2.1 перейменування зони №1 OK");
	shownName(1, got);
	CHECK(strcmp(got, "Novyny") == 0, "Z2.1 меню бачить нову назву (%s)", got);
	CHECK(stray(ADDR_ZONES + 2 * stride(), ADDR_ZONES + 2 * stride() + 16) == 0, "Z2.1 змінено лише 16 байтів назви біта 2; поза ними 0 (знімок-диф)");
	CHECK(memcmp(&s_eeprom[ADDR_ZONES + 2 * stride() + 16], &snap[ADDR_ZONES + 2 * stride() + 16], (size_t)(2 * perZone)) == 0, "Z2.1 список каналів зони не змінився");
	shownName(0, got); CHECK(strcmp(got, "Alpha") == 0, "Z2.1 сусідня зона №0 (%s)", got);
	shownName(2, got); CHECK(strcmp(got, "Charlie") == 0, "Z2.1 сусідня зона №2 (%s)", got);
	CHECK(memcmp(&s_eeprom[ADDR_ZONES + 2 * stride() + 6], "\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF", 10) == 0, "Z2.1 хвіст назви -- 0xFF (як пише стокова CPS)");

	/* Z2.2: кінцева «я» переживає запис (хвіст 0x00) */
	snapshot();
	CHECK(codeplugZoneRename(0, ZORYA) == CODEPLUG_ZONE_RENAME_OK, "Z2.2 «Зоря» записано");
	{
		uint8_t *p = &s_eeprom[ADDR_ZONES + 0 * stride()];
		CHECK(memcmp(p, ZORYA, 4) == 0 && p[4] == 0x00 && p[15] == 0x00, "Z2.2 у кодплазі: З о р я 00 ... (хвіст 0x00), не FF");
	}
	shownName(0, got);
	CHECK(strcmp(got, ZORYA) == 0 && strlen(got) == 4, "Z2.2 меню бачить усі 4 літери, кінцева «я» на місці (len=%d)", (int)strlen(got));
	CHECK(stray(ADDR_ZONES, ADDR_ZONES + 16) == 0, "Z2.2 змінено лише назву зони біта 0");

	CHECK(codeplugZoneRename(2, NADIYA) == CODEPLUG_ZONE_RENAME_OK, "Z2.2 «Надія» записано");
	shownName(2, got); CHECK(strcmp(got, NADIYA) == 0, "Z2.2 «Надія» читається цілою");

	/* я посеред назви -- звичайний хвіст 0xFF, назва ціла */
	CHECK(codeplugZoneRename(1, POLYANA) == CODEPLUG_ZONE_RENAME_OK, "Z2.2 «Поляна» записано");
	{
		uint8_t *p = &s_eeprom[ADDR_ZONES + 2 * stride()];
		CHECK(p[6] == 0xFF && p[15] == 0xFF, "Z2.2 «Поляна»: хвіст 0xFF (кінцевий символ не «я»)");
	}
	shownName(1, got); CHECK(strcmp(got, POLYANA) == 0, "Z2.2 «Поляна» читається цілою (len=%d)", (int)strlen(got));

	/* Z2.3: межа довжини */
	{
		const char *n16 = "ABCDEFGHIJKLMNOP";                       /* рівно 16, без «я» */
		const char *n15ya = "ABCDEFGHIJKLMN\xFF";                   /* 15 байтів, останній «я» -> хвіст 0x00 (1 байт) */
		const char *n16ya = "ABCDEFGHIJKLMNO\xFF";                  /* 16 байтів, останній «я» -> місця для хвоста нема */
		const char *n17 = "ABCDEFGHIJKLMNOPQ";

		snapshot();
		CHECK(codeplugZoneRename(0, n16) == CODEPLUG_ZONE_RENAME_OK, "Z2.3 16 символів приймається");
		shownName(0, got); CHECK(strcmp(got, n16) == 0 && strlen(got) == 16, "Z2.3 16 символів читаються цілими");
		CHECK(stray(ADDR_ZONES, ADDR_ZONES + 16) == 0, "Z2.3 16 символів: не виходить за 16 байтів назви (сусідній запис не зачеплено)");

		CHECK(codeplugZoneRename(0, n15ya) == CODEPLUG_ZONE_RENAME_OK, "Z2.3 15 символів з «я» наприкінці приймається");
		CHECK(s_eeprom[ADDR_ZONES + 15] == 0x00, "Z2.3 хвіст з одного байта 0x00");
		shownName(0, got); CHECK(strcmp(got, n15ya) == 0 && strlen(got) == 15, "Z2.3 «я» наприкінці 15 символів збереглась (len=%d)", (int)strlen(got));

		snapshot();
		CHECK(codeplugZoneRename(0, n16ya) == CODEPLUG_ZONE_RENAME_AMBIGUOUS_TAIL, "Z2.3 16 символів і «я» наприкінці відхилено (місця для хвоста нема)");
		CHECK(changed() == 0, "Z2.3 при відхиленні кодплаг не змінюється");
		CHECK(codeplugZoneRename(0, n17) == CODEPLUG_ZONE_RENAME_TOO_LONG, "Z2.3 17 символів відхилено");
		CHECK(changed() == 0, "Z2.3 17 символів: кодплаг не змінюється");
	}

	/* Z2.4: порожня назва */
	snapshot();
	CHECK(codeplugZoneRename(0, "") == CODEPLUG_ZONE_RENAME_EMPTY, "Z2.4 порожня назва відхилена");
	CHECK(changed() == 0, "Z2.4 порожня назва: кодплаг не змінюється (запис з name[0] == 0xFF прошивка вважала б порожнім)");

	/* Z2.5: «Всі канали» і неіснуючі номери */
	snapshot();
	CHECK(codeplugZoneRename(3, "Novyny") == CODEPLUG_ZONE_RENAME_NOT_REAL, "Z2.5 «Всі канали» перейменувати не можна");
	CHECK(codeplugZoneRename(4, "Novyny") == CODEPLUG_ZONE_RENAME_NOT_REAL, "Z2.5 номер за межами списку");
	CHECK(codeplugZoneRename(-1, "Novyny") == CODEPLUG_ZONE_RENAME_NOT_REAL, "Z2.5 від'ємний номер");
	CHECK(codeplugZoneRename(100, "Novyny") == CODEPLUG_ZONE_RENAME_NOT_REAL, "Z2.5 номер 100");
	CHECK(changed() == 0 && s_writes >= 0, "Z2.5 жодного байта кодплага не змінено");
	shownName(3, got); CHECK(strcmp(got, "All") == 0, "Z2.5 «Всі канали» лишились з мовної таблиці (%s)", got);

	/* Z2.6: збій запису */
	snapshot();
	s_failLo = ADDR_ZONES; s_failHi = ADDR_ZONES + 8 * stride();
	CHECK(codeplugZoneRename(1, "Novyny2") == CODEPLUG_ZONE_RENAME_WRITE_ERROR, "Z2.6 збій EEPROM -> WRITE_ERROR");
	s_failLo = s_failHi = -1;
	CHECK(changed() == 0, "Z2.6 при збої кодплаг не змінено");

	/* Z2.7: зона на екрані каналу (currentZone) оновлюється */
	world(perZone);
	currentZone.NOT_IN_CODEPLUGDATA_indexNumber = 2;              /* поточна зона -- біт 2 (номер у списку 1) */
	memcpy(currentZone.name, "Bravo\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF", 16);
	CHECK(codeplugZoneRename(1, ZORYA) == CODEPLUG_ZONE_RENAME_OK, "Z2.7 перейменування поточної зони");
	CHECK(memcmp(currentZone.name, ZORYA, 4) == 0 && currentZone.name[4] == 0x00, "Z2.7 currentZone.name оновлено байтами кодплага");
	currentZone.NOT_IN_CODEPLUGDATA_indexNumber = 0;
	memcpy(currentZone.name, "Alpha\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF", 16);
	CHECK(codeplugZoneRename(1, "Bravo2") == CODEPLUG_ZONE_RENAME_OK, "Z2.7 перейменування НЕ поточної зони");
	CHECK(memcmp(currentZone.name, "Alpha", 5) == 0, "Z2.7 currentZone інша зона -- не чіпаємо");

	/* Z2.8: повторне перейменування -- без залишків попередньої назви */
	world(perZone);
	CHECK(codeplugZoneRename(0, "Long name here!!") == CODEPLUG_ZONE_RENAME_OK, "Z2.8 довга назва");
	CHECK(codeplugZoneRename(0, "Ab") == CODEPLUG_ZONE_RENAME_OK, "Z2.8 коротка назва поверх довгої");
	shownName(0, got); CHECK(strcmp(got, "Ab") == 0, "Z2.8 без залишків (%s)", got);
	CHECK(s_eeprom[ADDR_ZONES + 2] == 0xFF && s_eeprom[ADDR_ZONES + 15] == 0xFF, "Z2.8 хвіст 0xFF після коротшої назви");
}

int main(void)
{
	run(80);
	run(16);
	printf("\n%s (%d провалів)\n", fails ? "ПРОВАЛ" : "OK", fails);
	return fails ? 1 : 0;
}
