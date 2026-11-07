/*
 * test_codeplug_zonemove.c -- R66C: переміщення каналу в зоні (codeplugZoneMoveChannel). Збирається зі СПРАВЖНІМ application/source/functions/codeplug.c; EEPROM -- образ
 * у пам'яті з тією ж моделлю проходів сектора, що SPI_Flash_write (запис через межу 4 КіБ = два проходи) і бюджетом записів («живлення зникло» після k записів).
 *
 * Ключове:
 *   M1  обмін двох СУСІДНІХ елементів = ОДИН запис рівно 4 байтів у списку зони (1 прохід сектора); решта образу не змінюється (крім LUCZ, коли треба);
 *   M2  вгору/вниз, межі списку, невірні аргументи, віртуальна зона, список лишається щільним і без дублів;
 *   M3  LUCZ іде за тим самим каналом (p <-> p+1), не чіпається, коли вказує деінде; порядок: СПОЧАТКУ список, ПОТІМ LUCZ (2 записи: заголовок + дані);
 *   M4  обрив живлення після КОЖНОГО запису (0..3): кожен канал зони лишається в списку рівно один раз, довжина та сама, LUCZ -- у межах списку;
 *   M5  пара, що перетинає межу 4 КіБ (зона-біт 46 при 80 каналів, пара 15/16; для розкладки 16 у перших 68 бітах меж 4 КіБ немає -- перевіряється вичерпно), відхиляється SECTOR_EDGE БЕЗ жодного запису;
 *       сусідні пари поруч -- проходять одним проходом;
 *   M6  збій запису: WRITE_ERROR, список і LUCZ без змін; поточна зона екрана перечитується.
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

#ifndef ZONE_MOVE_ENABLED
#error "test_codeplug_zonemove.c треба збирати з -DENABLE_ZONE_EDIT -DENABLE_CHANNEL_DELETE -DENABLE_CODEPLUG_MENU -DENABLE_ZONE_RENAME -DENABLE_APRS_RX -DENABLE_AES -DLANGUAGE_BUILD_UKRAINIAN"
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
static int s_budget = -1;      /* скільки ще записів (EEPROM_Write) дозволено; 0 -- «живлення зникло»: запис не виконується */
static int s_nwrites = 0;      /* викликів EEPROM_Write */
static int s_firstPasses = 0;  /* проходи ПЕРШОГО запису (запис списку; далі можуть іти записи LUCZ) */
static int s_passes = 0;       /* проходів «сектор прочитати -> стерти -> записати» (як у SPI_Flash_write: запис через межу 4 КіБ -- ДВА проходи) */
static int s_lastAddr = -1, s_lastSize = 0;
bool EEPROM_Write(int address, uint8_t *buf, int size)
{
	if ((address < 0) || ((address + size) > EEPROM_SIZE)) { return false; }
	if (s_budget == 0) { return false; }
	if (s_budget > 0) { s_budget--; }
	if ((s_failLo >= 0) && (address < s_failHi) && ((address + size) > s_failLo)) { return false; }
	memcpy(&s_eeprom[address], buf, (size_t)size);
	if (s_nwrites == 0) { s_firstPasses = (((address) / 4096) != ((address + size - 1) / 4096)) ? 2 : 1; }
	s_nwrites++;
	s_lastAddr = address; s_lastSize = size;
	s_passes += (((address) / 4096) != ((address + size - 1) / 4096)) ? 2 : 1;
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


static int changedBytes(void)
{
	int n = 0;
	for (int a = 0; a < EEPROM_SIZE; a++) { if (s_eeprom[a] != snap[a]) { n++; } }
	return n;
}
static int changedOutside(int lo, int hi)
{
	int n = 0;
	for (int a = 0; a < EEPROM_SIZE; a++) { if ((s_eeprom[a] != snap[a]) && ((a < lo) || (a >= hi))) { n++; } }
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
static bool sameSet(const uint16_t *a, const uint16_t *b, int n)
{
	for (int i = 0; i < n; i++)
	{
		int ca = 0, cb = 0;
		for (int j = 0; j < n; j++) { if (a[j] == a[i]) { ca++; } if (b[j] == a[i]) { cb++; } }
		if ((ca != 1) || (cb != 1)) { return false; }
	}
	return true;
}
static void resetCounters(void) { s_budget = -1; s_nwrites = 0; s_passes = 0; s_firstPasses = 0; s_lastAddr = -1; s_lastSize = 0; }

/* одна зона-біт `bit` з n каналами 1..n у списку; повертає її номер у списку зон (ординал) */
static int oneZone(int perZone, int bit, int n)
{
	uint16_t l[80];
	world(perZone);
	memset(s_eeprom + ADDR_ZONEMASK, 0, 32);
	for (int i = 0; i < n; i++) { l[i] = (uint16_t)(i + 1); }
	addZone(bit, "Zona", l, n);
	setChannelsInUse(100);
	codeplugZonesInitCache();
	codeplugInitLastUsedChannelInZone();
	return 0;
}

int main(void)
{
	/* ---------- M1: один запис 4 байти ---------- */
	{
		const uint16_t before[] = { 1, 2, 3, 4, 5 };
		const uint16_t afterDown[] = { 1, 3, 2, 4, 5 };
		const uint16_t afterUp[] = { 1, 3, 2, 4, 5 };
		int z = oneZone(80, 7, 5);
		CodeplugZoneEditResult_t r;
		(void)afterUp;
		CHECK(listIs(z, before, 5), "M1: початковий список 1..5");
		snapshot(); resetCounters();
		r = codeplugZoneMoveChannel(z, 1, +1);   /* канал на позиції 1 (№2) -- вниз */
		CHECK(r == CODEPLUG_ZONE_EDIT_OK, "M1: вниз -- OK (%d)", (int)r);
		CHECK(listIs(z, afterDown, 5), "M1: порядок 1,3,2,4,5");
		CHECK(s_nwrites == 1 && s_lastSize == 4 && s_lastAddr == recAddr(7) + 16 + 2 * 1, "M1: один запис 4 байти за адресою %d (було %d записів, %d байтів за %d)", recAddr(7) + 18, s_nwrites, s_lastSize, s_lastAddr);
		CHECK(s_passes == 1, "M1: один прохід сектора (%d)", s_passes);
		CHECK(changedOutside(recAddr(7) + 18, recAddr(7) + 22) == 0, "M1: поза цими 4 байтами образ не змінився");
		/* вгору -- назад */
		snapshot(); resetCounters();
		r = codeplugZoneMoveChannel(z, 2, -1);
		CHECK(r == CODEPLUG_ZONE_EDIT_OK && listIs(z, before, 5), "M1: вгору повертає 1,2,3,4,5 (%d)", (int)r);
		CHECK(s_nwrites == 1 && s_passes == 1, "M1: вгору -- один запис, один прохід");
		/* нулі після кінця списку лишились (щільний список) */
		{
			CodeplugZone_t zz; memset(&zz, 0, sizeof zz); codeplugZoneGetDataForNumber(z, &zz);
			CHECK(zz.NOT_IN_CODEPLUGDATA_numChannelsInZone == 5, "M1: довжина списку 5");
		}
	}

	/* ---------- M2: межі й аргументи ---------- */
	{
		int z = oneZone(80, 3, 4);
		uint16_t base[] = { 1, 2, 3, 4 };
		snapshot(); resetCounters();
		CHECK(codeplugZoneMoveChannel(z, 0, -1) == CODEPLUG_ZONE_EDIT_BAD_POSITION, "M2: перший вгору -- BAD_POSITION");
		CHECK(codeplugZoneMoveChannel(z, 3, +1) == CODEPLUG_ZONE_EDIT_BAD_POSITION, "M2: останній вниз -- BAD_POSITION");
		CHECK(codeplugZoneMoveChannel(z, 4, -1) == CODEPLUG_ZONE_EDIT_BAD_POSITION, "M2: позиція за списком");
		CHECK(codeplugZoneMoveChannel(z, -1, +1) == CODEPLUG_ZONE_EDIT_BAD_POSITION, "M2: від'ємна позиція");
		CHECK(codeplugZoneMoveChannel(z, 1, 0) == CODEPLUG_ZONE_EDIT_NOT_REAL, "M2: dir=0 відхилено");
		CHECK(codeplugZoneMoveChannel(z, 1, 2) == CODEPLUG_ZONE_EDIT_NOT_REAL, "M2: dir=2 відхилено");
		CHECK(codeplugZoneMoveChannel(z, 1, -2) == CODEPLUG_ZONE_EDIT_NOT_REAL, "M2: dir=-2 відхилено");
		CHECK(codeplugZoneMoveChannel(codeplugZonesGetCount() - 1, 0, +1) == CODEPLUG_ZONE_EDIT_NOT_REAL, "M2: віртуальна «Всі канали» не переміщується");
		CHECK(codeplugZoneMoveChannel(9, 0, +1) == CODEPLUG_ZONE_EDIT_NOT_REAL, "M2: номер зони поза списком");
		CHECK(s_nwrites == 0 && changedBytes() == 0 && listIs(z, base, 4), "M2: жодного запису, образ без змін");
		/* послідовність кроків: переносимо канал 1 в кінець, потім назад */
		for (int k = 0; k < 3; k++) { CHECK(codeplugZoneMoveChannel(z, k, +1) == CODEPLUG_ZONE_EDIT_OK, "M2: крок вниз %d", k); }
		{ uint16_t w[] = { 2, 3, 4, 1 }; CHECK(listIs(z, w, 4), "M2: канал 1 в кінці"); }
		for (int k = 3; k > 0; k--) { CHECK(codeplugZoneMoveChannel(z, k, -1) == CODEPLUG_ZONE_EDIT_OK, "M2: крок вгору %d", k); }
		CHECK(listIs(z, base, 4), "M2: повернули 1,2,3,4");
		/* 16-канальна розкладка */
		z = oneZone(16, 3, 4);
		CHECK(codeplugZoneMoveChannel(z, 2, -1) == CODEPLUG_ZONE_EDIT_OK, "M2: розкладка 16 -- OK");
		{ uint16_t w[] = { 1, 3, 2, 4 }; CHECK(listIs(z, w, 4), "M2: розкладка 16: 1,3,2,4"); }
		CHECK(s_lastAddr == recAddr(3) + 16 + 2 * 1 && s_lastSize == 4, "M2: розкладка 16: запис за %d", recAddr(3) + 18);
	}

	/* ---------- M3: LUCZ ---------- */
	{
		int z = oneZone(80, 4, 5);
		int bit = 4;
		/* LUCZ на p=2 (канал 3); рухаємо його вниз -> LUCZ=3 */
		codeplugSetLastUsedChannelInZone(bit, 2);
		snapshot(); resetCounters();
		CHECK(codeplugZoneMoveChannel(z, 2, +1) == CODEPLUG_ZONE_EDIT_OK, "M3: вниз OK");
		CHECK(codeplugGetLastUsedChannelInZone(bit) == 3, "M3: LUCZ пішов за каналом: 2 -> 3 (%d)", (int)codeplugGetLastUsedChannelInZone(bit));
		CHECK(s_nwrites == 3 && s_passes == 3, "M3: записів 3 = список + заголовок LUCZ + дані LUCZ (%d, проходів %d)", s_nwrites, s_passes);
		/* вгору: канал 3 (тепер на позиції 3) вгору -> LUCZ=2 */
		resetCounters();
		CHECK(codeplugZoneMoveChannel(z, 3, -1) == CODEPLUG_ZONE_EDIT_OK && codeplugGetLastUsedChannelInZone(bit) == 2, "M3: вгору: LUCZ 3 -> 2");
		/* LUCZ на сусідній позиції p+1 (канал, з яким міняємось): рухаємо p вниз -> LUCZ=p */
		codeplugSetLastUsedChannelInZone(bit, 3);
		resetCounters();
		CHECK(codeplugZoneMoveChannel(z, 2, +1) == CODEPLUG_ZONE_EDIT_OK && codeplugGetLastUsedChannelInZone(bit) == 2, "M3: LUCZ на сусідньому (3) -> 2");
		/* LUCZ деінде: не чіпається і не пишеться */
		codeplugSetLastUsedChannelInZone(bit, 0);
		resetCounters();
		CHECK(codeplugZoneMoveChannel(z, 2, +1) == CODEPLUG_ZONE_EDIT_OK && codeplugGetLastUsedChannelInZone(bit) == 0, "M3: LUCZ деінде -- без змін");
		CHECK(s_nwrites == 1 && s_passes == 1, "M3: LUCZ деінде -- лише запис списку (%d)", s_nwrites);
		/* канал за LUCZ той самий до і після (через список) */
		{
			uint16_t b4[5], a4[5];
			int lu = 1;
			codeplugSetLastUsedChannelInZone(bit, lu);
			listOf(z, b4);
			CHECK(codeplugZoneMoveChannel(z, 1, +1) == CODEPLUG_ZONE_EDIT_OK, "M3: ще крок");
			listOf(z, a4);
			CHECK(b4[lu] == a4[codeplugGetLastUsedChannelInZone(bit)], "M3: LUCZ вказує на ТОЙ САМИЙ канал (було %u, стало %u)", (unsigned)b4[lu], (unsigned)a4[codeplugGetLastUsedChannelInZone(bit)]);
		}
	}

	/* ---------- M4: обрив живлення після кожного запису ---------- */
	{
		for (int perZone = 16; perZone <= 80; perZone += 64)
		{
			for (int scenario = 0; scenario < 3; scenario++)
			{
				for (int cut = 0; cut <= 4; cut++)
				{
					int z = oneZone(perZone, 6, 6);
					uint16_t orig[6], now[6];
					int bit = 6, n;
					int lu = (scenario == 0) ? 2 : ((scenario == 1) ? 3 : 0);   /* 0 -- LUCZ на рухомому, 1 -- на сусідньому, 2 -- деінде */
					codeplugSetLastUsedChannelInZone(bit, lu);
					listOf(z, orig);
					resetCounters();
					s_budget = cut;   /* дозволено cut записів, далі «живлення зникло» */
					(void)codeplugZoneMoveChannel(z, 2, +1);
					s_budget = -1;
					codeplugZonesInitCache();            /* «перезапуск»: кеш з образу */
					codeplugInitLastUsedChannelInZone();  /* LUCZ -- з образу (заголовка в образі нема -> нулі, якщо LUCZ не дописано) */
					n = listOf(z, now);
					CHECK(n == 6 && sameSet(orig, now, 6), "M4: розкладка %d, LUCZ-сценарій %d, обрив після %d записів: канали по одному разу (%u %u %u %u %u %u)", perZone, scenario, cut,
						(unsigned)now[0], (unsigned)now[1], (unsigned)now[2], (unsigned)now[3], (unsigned)now[4], (unsigned)now[5]);
					CHECK(codeplugGetLastUsedChannelInZone(bit) < 6, "M4: LUCZ у межах списку (%d)", (int)codeplugGetLastUsedChannelInZone(bit));
				}
			}
		}
	}

	/* ---------- M5: межа сектора ---------- */
	{
		struct { int perZone, bit, lo; } edge[] = { { 80, 46, 15 } };
		for (int e = 0; e < 1; e++)
		{
			int perZone = edge[e].perZone, bit = edge[e].bit, lo = edge[e].lo;
			int st = 16 + 2 * perZone;
			int addr = 0x8030 + bit * st + 16 + 2 * lo;
			int z = oneZone(perZone, bit, perZone);
			uint16_t l[80];
			CHECK(((addr / 4096) != ((addr + 3) / 4096)), "M5: незалежна перевірка: пара (%d,%d) зони-біта %d при %d каналах перетинає межу сектора (адреса %d)", lo, lo + 1, bit, perZone, addr);
			listOf(z, l);
			snapshot(); resetCounters();
			{ int rr = codeplugZoneMoveChannel(z, lo, +1); CHECK(rr == CODEPLUG_ZONE_EDIT_SECTOR_EDGE, "M5: вниз через межу -- SECTOR_EDGE (отримано %d, бiт %d, роз %d)", rr, bit, perZone); }
			CHECK(codeplugZoneMoveChannel(z, lo + 1, -1) == CODEPLUG_ZONE_EDIT_SECTOR_EDGE, "M5: вгору через межу -- SECTOR_EDGE");
			CHECK(s_nwrites == 0 && changedBytes() == 0, "M5: жодного запису, образ без змін (%d записів)", s_nwrites);
			/* поруч -- одним проходом */
			resetCounters();
			CHECK(codeplugZoneMoveChannel(z, lo - 1, +1) == CODEPLUG_ZONE_EDIT_OK && s_passes == 1, "M5: пара (%d,%d) поруч -- один прохід (%d)", lo - 1, lo, s_passes);
			resetCounters();
			CHECK(codeplugZoneMoveChannel(z, lo + 1, +1) == CODEPLUG_ZONE_EDIT_OK && s_passes == 1, "M5: пара (%d,%d) поруч -- один прохід (%d)", lo + 1, lo + 2, s_passes);
		}
		/* усі пари всіх розташувань: або прохід один, або SECTOR_EDGE -- жодного запису у ДВА проходи */
		for (int perZone = 16; perZone <= 80; perZone += 64)
		{
			int bad = 0, edgeCnt = 0, total = 0;
			for (int bit = 0; bit < 68; bit += 1)   /* лише «справжні» зони: ліміт CODEPLUG_ZONES_MAX */
			{
				int n = perZone;
				int z = oneZone(perZone, bit, n);
				for (int lo = 0; lo + 1 < n; lo += 1)
				{
					CodeplugZoneEditResult_t r;
					resetCounters();
					r = codeplugZoneMoveChannel(z, lo, +1);
					total++;
					if (r == CODEPLUG_ZONE_EDIT_SECTOR_EDGE) { edgeCnt++; if (s_nwrites != 0) { bad++; } }
					else if (r == CODEPLUG_ZONE_EDIT_OK) { if (s_firstPasses != 1) { bad++; } }
					else { bad++; }
				}
			}
			CHECK(bad == 0, "M5: розкладка %d: усі %d пар усіх зон, що вміщає образ -- один прохід або SECTOR_EDGE без запису (відхилено %d пар, порушень %d)", perZone, total, edgeCnt, bad);
		}
	}

	/* ---------- M6: збій запису, поточна зона ---------- */
	{
		int z = oneZone(80, 2, 4);
		uint16_t base[] = { 1, 2, 3, 4 };
		codeplugSetLastUsedChannelInZone(2, 1);
		s_failLo = recAddr(2) + 16; s_failHi = recAddr(2) + 16 + 8;
		snapshot(); resetCounters();
		CHECK(codeplugZoneMoveChannel(z, 1, +1) == CODEPLUG_ZONE_EDIT_WRITE_ERROR, "M6: збій запису -- WRITE_ERROR");
		CHECK(listIs(z, base, 4) && codeplugGetLastUsedChannelInZone(2) == 1 && changedBytes() == 0, "M6: список і LUCZ без змін");
		s_failLo = s_failHi = -1;
		/* поточна зона екрана перечитується */
		z = oneZone(80, 2, 4);
		codeplugZoneGetDataForNumber(z, &currentZone);
		CHECK(codeplugZoneMoveChannel(z, 0, +1) == CODEPLUG_ZONE_EDIT_OK, "M6: крок");
		CHECK(currentZone.channels[0] == 2 && currentZone.channels[1] == 1, "M6: currentZone перечитано (%u %u)", (unsigned)currentZone.channels[0], (unsigned)currentZone.channels[1]);
	}

	printf(fails ? "\ntest_codeplug_zonemove: ПРОВАЛІВ: %d\n" : "\ntest_codeplug_zonemove: усе гаразд\n", fails);
	return fails ? 1 : 0;
}
