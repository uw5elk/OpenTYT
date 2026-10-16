/*
 * test_codeplug_zone.c -- R22 Z1: вибір зон. Тест збирається з СПРАВЖНІМ application/source/functions/codeplug.c
 * (EEPROM, SPI-флеш і мова -- заглушки нижче) і перевіряє те, що зламалось у R19/R21: валкодер SK2+енкодер
 * зупинявся на «сміттєвих» зонах, яких нема в меню «Зони». Тут: єдине правило codeplugZoneIsUsable(), підрахунок
 * codeplugZonesGetCount() (лише перші 68 бітів маски), крок codeplugZoneStep() з codeplug_zone.h.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/codeplug.h"
#include "functions/codeplug_zone.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiLocalisation.h"

/* --- заглушки заліза/мови -------------------------------------------------------------------------------- */
static uint8_t s_eeprom[0x10000];
uint8_t SPI_Flash_sectorbuffer[4096];
CodeplugZone_t currentZone;
static stringsTable_t s_lang;
const stringsTable_t *currentLanguage = &s_lang;

bool EEPROM_Read(int address, uint8_t *buf, int size)
{
	if ((address < 0) || ((address + size) > (int)sizeof(s_eeprom))) { return false; }
	memcpy(buf, &s_eeprom[address], (size_t)size);
	return true;
}
bool EEPROM_Write(int address, uint8_t *buf, int size)
{
	if ((address < 0) || ((address + size) > (int)sizeof(s_eeprom))) { return false; }
	memcpy(&s_eeprom[address], buf, (size_t)size);
	return true;
}
bool SPI_Flash_read(uint32_t a, uint8_t *b, int n) { (void)a; memset(b, 0, (size_t)n); return true; }
bool SPI_Flash_write(uint32_t a, uint8_t *b, int n) { (void)a; (void)b; (void)n; return true; }
bool SPI_Flash_writePage(uint32_t a, uint8_t *b) { (void)a; (void)b; return true; }
bool SPI_Flash_eraseSector(uint32_t a) { (void)a; return true; }

extern uint8_t codeplugAllChannelsCache[128];
extern uint8_t codeplugZonesInUseCache[32];

/* --- допоміжні -------------------------------------------------------------------------------------------- */
static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

#define ZONE_STRIDE (16 + 2 * 80)

static void setChanInUse(int chan)   /* канал chan (1..1024) існує */
{
	chan--;
	codeplugAllChannelsCache[chan / 8] |= (uint8_t)(1U << (chan % 8));
}

static void putZone(int bit, int firstChan, int nChans)   /* зона з номером біта bit: nChans каналів, починаючи з firstChan */
{
	uint8_t *p = &s_eeprom[0x8030 + bit * ZONE_STRIDE];
	memset(p, 0xFF, 16);
	memset(p + 16, 0, 160);
	for (int i = 0; i < nChans; i++)
	{
		uint16_t c = (uint16_t)(firstChan + i);
		memcpy(p + 16 + 2 * i, &c, 2);
	}
	codeplugZonesInUseCache[bit / 8] |= (uint8_t)(1U << (bit % 8));
}

static void putGarbageZone(int bit)   /* біт стоїть, канали -- сміття з флешу: channels[0] поза 1..1024, "numChannels" > 0 */
{
	uint8_t *p = &s_eeprom[0x8030 + (bit % 60) * ZONE_STRIDE];
	memset(p, 0xFF, ZONE_STRIDE);   /* 0xFFFF: нуля нема -> numChannelsInZone = 80, channels[0] = 65535 */
	codeplugZonesInUseCache[bit / 8] |= (uint8_t)(1U << (bit % 8));
}

static void reset(void)
{
	memset(s_eeprom, 0, sizeof(s_eeprom));
	memset(codeplugAllChannelsCache, 0, sizeof(codeplugAllChannelsCache));
	memset(codeplugZonesInUseCache, 0, sizeof(codeplugZonesInUseCache));
	codeplugChannelsPerZone = 80;
	strcpy((char *)s_lang.all_channels, "All");
}

static bool usableCb(int z, void *ctx) { (void)ctx; return codeplugZoneIsUsable(z, NULL); }

/* усі зони, на яких може зупинитись валкодер за один повний оберт (вперед) */
static int walk(int start, bool next, int *outZones, int max)
{
	int n = 0, cur = start, numZones = codeplugZonesGetCount();

	for (int i = 0; i < max; i++)
	{
		cur = codeplugZoneStep(cur, numZones, next, usableCb, NULL);
		outZones[n++] = cur;
		if (cur == start) { break; }
	}
	return n;
}

int main(void)
{
	int seen[400];

	printf("test_codeplug_zone:\n");

	/* 1. Сміттєва зона між двома справжніми: валкодер її пропускає, меню -- теж (одне правило). */
	reset();
	setChanInUse(1); setChanInUse(2); setChanInUse(10);
	putZone(0, 1, 2);        /* зона 0: канали 1,2 */
	putGarbageZone(1);       /* сміття */
	putZone(2, 10, 1);       /* зона 2: канал 10 */
	CHECK(codeplugZonesGetCount() == 4, "3 біти в масці -> 3 зони + «Всі канали» = 4 (є %d)", codeplugZonesGetCount());
	CHECK(codeplugZoneIsUsable(0, NULL) == true,  "справжня зона 0 придатна");
	CHECK(codeplugZoneIsUsable(1, NULL) == false, "сміттєва зона 1 НЕ придатна");
	CHECK(codeplugZoneIsUsable(2, NULL) == true,  "справжня зона 2 придатна");
	CHECK(codeplugZoneIsUsable(3, NULL) == true,  "«Всі канали» завжди придатна");
	CHECK(codeplugZoneStep(0, 4, true, usableCb, NULL) == 2,  "вперед з 0: 1 (сміття) пропущено -> 2");
	CHECK(codeplugZoneStep(2, 4, false, usableCb, NULL) == 0, "назад з 2: 1 (сміття) пропущено -> 0");
	CHECK(codeplugZoneStep(2, 4, true, usableCb, NULL) == 3,  "вперед з 2 -> «Всі канали»");
	CHECK(codeplugZoneStep(3, 4, true, usableCb, NULL) == 0,  "вперед зі «Всі канали» -> 0 (коло)");
	CHECK(codeplugZoneStep(0, 4, false, usableCb, NULL) == 3, "назад з 0 -> «Всі канали»");

	/* 2. Зона з видаленим першим каналом -- теж не придатна (як у меню). */
	reset();
	setChanInUse(2);
	putZone(0, 1, 2);   /* перший канал 1 не існує, другий існує */
	CHECK(codeplugZoneIsUsable(0, NULL) == false, "перший канал видалено -> зона не придатна");

	/* 3. Порожня зона (біт стоїть, каналів нема). */
	reset();
	putZone(0, 0, 0);
	CHECK(codeplugZoneIsUsable(0, NULL) == false, "порожня зона не придатна");

	/* 4. Усі сміттєві, крім однієї: зупиняємось на ній, не зациклюємось. */
	reset();
	setChanInUse(5);
	for (int b = 0; b < 10; b++) { putGarbageZone(b); }
	putZone(6, 5, 1);
	{
		int n = walk(codeplugZonesGetCount() - 1, true, seen, 50);
		bool only6 = true;
		for (int i = 0; i < n; i++) { if ((seen[i] != 6 - 0 + 0) && (seen[i] != codeplugZonesGetCount() - 1)) { only6 = false; } }
		CHECK(codeplugZonesGetCount() == 11, "10 бітів -> 11 зон (є %d)", codeplugZonesGetCount());
		CHECK(n == 2, "повний оберт вперед = 2 зупинки (справжня + «Всі канали»), є %d", n);
		CHECK(only6, "єдині зупинки: справжня зона та «Всі канали»");
		n = walk(codeplugZonesGetCount() - 1, false, seen, 50);
		CHECK(n == 2, "назад теж 2 зупинки (є %d)", n);
	}

	/* 5. Усі сміттєві: валкодер не зациклюється, стає на «Всі канали». */
	reset();
	for (int b = 0; b < 12; b++) { putGarbageZone(b); }
	CHECK(codeplugZoneStep(0, codeplugZonesGetCount(), true, usableCb, NULL) == 12, "усе сміття вперед -> «Всі канали» (12)");
	CHECK(codeplugZoneStep(5, codeplugZonesGetCount(), false, usableCb, NULL) == 12, "усе сміття назад -> «Всі канали» (12)");

	/* 6. Біт за межею 68 (позиція 100): кількість зон не росте. */
	reset();
	setChanInUse(1);
	putZone(0, 1, 1);
	CHECK(codeplugZonesGetCount() == 2, "до сміттєвого біта: 2 (є %d)", codeplugZonesGetCount());
	codeplugZonesInUseCache[100 / 8] |= (uint8_t)(1U << (100 % 8));
	codeplugZonesInUseCache[255 / 8] |= (uint8_t)(1U << (255 % 8));
	CHECK(codeplugZonesGetCount() == 2, "біти 100 і 255 (за межею 68) кількість не збільшують (є %d)", codeplugZonesGetCount());
	codeplugZonesInUseCache[67 / 8] |= (uint8_t)(1U << (67 % 8));
	CHECK(codeplugZonesGetCount() == 3, "біт 67 (остання допустима позиція) рахується (є %d)", codeplugZonesGetCount());
	codeplugZonesInUseCache[68 / 8] |= (uint8_t)(1U << (68 % 8));
	CHECK(codeplugZonesGetCount() == 3, "біт 68 (перша позиція за межею) не рахується (є %d)", codeplugZonesGetCount());
	{
		CodeplugZone_t z;
		CHECK(codeplugZoneGetDataForNumber(2, &z) == true && CODEPLUG_ZONE_IS_ALLCHANNELS(z), "номер count-1 -- «Всі канали»");
	}

	/* 7. «Всі канали» доступна завжди. */
	reset();
	CHECK(codeplugZonesGetCount() == 1, "порожня маска -> лише «Всі канали»");
	CHECK(codeplugZoneIsUsable(0, NULL) == true, "єдина зона = «Всі канали», придатна");
	CHECK(codeplugZoneStep(0, 1, true, usableCb, NULL) == 0, "крок з єдиною зоною лишає її");
	CHECK(codeplugZoneStep(0, 1, false, usableCb, NULL) == 0, "крок назад з єдиною зоною лишає її");

	/* 8. Некоректний поточний номер зони (поза діапазоном). */
	reset();
	setChanInUse(1);
	putZone(0, 1, 1);
	CHECK(codeplugZoneStep(200, 2, true, usableCb, NULL) == 0, "поточна 200 при 2 зонах, вперед -> 0 (не сміття)");
	CHECK(codeplugZoneStep(200, 2, false, usableCb, NULL) == 0, "поточна 200 при 2 зонах, назад -> 0");
	CHECK(codeplugZoneStep(-3, 2, true, usableCb, NULL) == 0, "поточна -3, вперед -> 0");

	/* 9. Меню і валкодер бачать ОДНЕ Й ТЕ САМЕ: на змішаному наборі повний оберт валкодера = множина зон меню. */
	reset();
	for (int c = 1; c <= 30; c++) { setChanInUse(c); }
	putZone(0, 1, 3); putGarbageZone(1); putZone(2, 4, 5); putZone(3, 0, 0); putGarbageZone(4); putZone(5, 9, 2);
	putZone(60, 20, 3); putGarbageZone(61); putZone(67, 25, 2);
	{
		int total = codeplugZonesGetCount(), menu[80], mn = 0, n;
		for (int z = 0; z < total; z++) { if (codeplugZoneIsUsable(z, NULL)) { menu[mn++] = z; } }
		n = walk(total - 1, true, seen, 100);
		CHECK(n == mn, "кількість зупинок валкодера за оберт (%d) = кількість зон меню (%d)", n, mn);
		bool same = (n == mn);
		for (int i = 0; same && (i < n); i++) { if (seen[i] != menu[(i + 0) % mn] && !(i == n - 1 && seen[i] == total - 1)) { same = false; } }
		/* порядок: валкодер від «Всі канали» вперед = 0,2,5(.. справжні за зростанням), «Всі канали» */
		CHECK(same, "зупинки валкодера = зони меню в тому ж порядку");
		n = walk(total - 1, false, seen, 100);
		CHECK(n == mn, "назад теж %d зупинок (є %d)", mn, n);
	}

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
