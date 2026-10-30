/*
 * test_codeplug_chandel.c -- R41: видалення каналу з меню рації. Тест збирається зі СПРАВЖНІМ application/source/functions/codeplug.c
 * (codeplugChannelDelete, codeplugChannelCountZones, ...) і справжнім codeplug_chandel.h; EEPROM і SPI-флеш -- образи в пам'яті, а флеш веде себе
 * як NOR (стирання сектора -> 0xFF, запис сторінки лише ЗНІМАЄ біти) і має ТОЙ САМИЙ read-modify-write цілого сектора, що справжній SPI_Flash_write.
 *
 * Адреси в тесті рахуються НЕЗАЛЕЖНО від codeplug_chandel.h (з розкладки кодплага: банк 0 -- EEPROM, банки 1..7 -- флеш із 16-байтовою маскою перед кожним
 * банком), тож помилка в формулі адреси в прошивці тут видна.
 *
 * Ключова перевірка -- ЗНІМОК-ДИФ: до й після видалення порівнюється ВЕСЬ образ EEPROM і флешу, і змінитися можуть тільки дозволені місця
 * (байт маски, запис каналу, записи тих зон, де канал стояв, блок LUCZ). Жоден сусідній канал/зона/контакт не зачеплено.
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

#define EEPROM_SIZE   0x10000
#define FLASH_SIZE    (1024 * 1024)

static uint8_t s_eeprom[EEPROM_SIZE];
static uint8_t s_flash[FLASH_SIZE];     /* індекс = адреса з FLASH_ADDRESS_OFFSET */
uint8_t SPI_Flash_sectorbuffer[4096];
CodeplugZone_t currentZone;
static stringsTable_t s_lang;
const stringsTable_t *currentLanguage = &s_lang;

/* збій запису: адреса в [lo, hi) (EEPROM) або [lo, hi) (флеш, адреса з офсетом) */
static int s_failEepLo = -1, s_failEepHi = -1;
static int s_failFlashLo = -1, s_failFlashHi = -1;
static int s_flashEraseCount = 0;

bool EEPROM_Read(int address, uint8_t *buf, int size)
{
	if ((address < 0) || ((address + size) > EEPROM_SIZE)) { return false; }
	memcpy(buf, &s_eeprom[address], (size_t)size);
	return true;
}
bool EEPROM_Write(int address, uint8_t *buf, int size)
{
	if ((address < 0) || ((address + size) > EEPROM_SIZE)) { return false; }
	if ((s_failEepLo >= 0) && (address < s_failEepHi) && ((address + size) > s_failEepLo)) { return false; }
	memcpy(&s_eeprom[address], buf, (size_t)size);
	return true;
}
bool SPI_Flash_read(uint32_t a, uint8_t *b, int n)
{
	if ((a + (uint32_t)n) > FLASH_SIZE) { return false; }
	memcpy(b, &s_flash[a], (size_t)n);
	return true;
}
bool SPI_Flash_eraseSector(uint32_t a)
{
	if ((a % 4096U) != 0U) { return false; }
	memset(&s_flash[a], 0xFF, 4096);
	s_flashEraseCount++;
	return true;
}
bool SPI_Flash_writePage(uint32_t a, uint8_t *b)
{
	if ((a % 256U) != 0U) { return false; }
	for (int i = 0; i < 256; i++) { s_flash[a + (uint32_t)i] &= b[i]; }   /* NOR: запис лише знімає біти */
	return true;
}
/* копія логіки справжнього SPI_Flash_write (application/source/hardware/SPI_Flash.c): ціле-секторний read-modify-write */
bool SPI_Flash_write(uint32_t addr, uint8_t *dataBuf, int size)
{
	if ((s_failFlashLo >= 0) && ((int)addr < s_failFlashHi) && ((int)addr + size > s_failFlashLo)) { return false; }
	while (size > 0)
	{
		uint32_t sector = addr / 4096U;
		int inSector = (int)(((sector + 1U) * 4096U) - addr);
		int n = (size < inSector) ? size : inSector;

		SPI_Flash_read(sector * 4096U, SPI_Flash_sectorbuffer, 4096);
		memcpy(SPI_Flash_sectorbuffer + (addr - sector * 4096U), dataBuf, (size_t)n);
		if (!SPI_Flash_eraseSector(sector * 4096U)) { return false; }
		for (int i = 0; i < 16; i++) { if (!SPI_Flash_writePage(sector * 4096U + (uint32_t)(i * 256), SPI_Flash_sectorbuffer + i * 256)) { return false; } }
		addr += (uint32_t)n; dataBuf += n; size -= n;
	}
	return true;
}

extern uint8_t codeplugAllChannelsCache[128];
extern uint8_t codeplugZonesInUseCache[32];
extern uint8_t lastUsedChannelInZoneData[];

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* --- розкладка кодплага (незалежно від codeplug_chandel.h) ---------------------------------------------------------------------- */
#define REC 56
#define ZONE_STRIDE (16 + 2 * 80)
#define ADDR_CH_EEP    0x3790
#define ADDR_HDR_EEP   0x3780
#define ADDR_CH_FLASH  0x7B1C0
#define ADDR_HDR_FLASH 0x7B1B0
#define ADDR_ZONES     0x8030
#define ADDR_ZONEMASK  0x8010
#define ADDR_LUCZ      0x6000

static uint8_t *recPtr(int ch)             /* початок запису каналу ch у образі */
{
	if (ch <= 128) { return &s_eeprom[ADDR_CH_EEP + (ch - 1) * REC]; }
	int n = ch - 1 - 128;
	return &s_flash[FLASH_ADDRESS_OFFSET + ADDR_CH_FLASH + 16 * (n / 128) + n * REC];
}
static uint8_t *maskBytePtr(int ch)        /* байт маски «в роботі» каналу ch */
{
	int i = ch - 1, bank = i / 128, byteno = (i % 128) / 8;
	if (bank == 0) { return &s_eeprom[ADDR_HDR_EEP + byteno]; }
	return &s_flash[FLASH_ADDRESS_OFFSET + ADDR_HDR_FLASH + (bank - 1) * (128 * REC + 16) + byteno];
}
static bool maskBit(int ch) { return (*maskBytePtr(ch) >> ((ch - 1) % 8)) & 1; }

static void addChannel(int ch)
{
	*maskBytePtr(ch) |= (uint8_t)(1U << ((ch - 1) % 8));
	memset(recPtr(ch), 0x40 + (ch % 100), REC);     /* впізнаваний вміст; ніколи не 0xFF */
	memcpy(recPtr(ch), "CH", 2);
	recPtr(ch)[2] = (uint8_t)(ch & 0xFF); recPtr(ch)[3] = (uint8_t)(ch >> 8);
}
static void addZone(int bit, const uint16_t *list, int n)
{
	uint8_t *p = &s_eeprom[ADDR_ZONES + bit * ZONE_STRIDE];
	memset(p, 0xFF, 16); memcpy(p, "Zone", 4); p[4] = (uint8_t)('0' + bit % 10); p[5] = 0;
	memset(p + 16, 0, 160);
	for (int i = 0; i < n; i++) { memcpy(p + 16 + 2 * i, &list[i], 2); }
	s_eeprom[ADDR_ZONEMASK + bit / 8] |= (uint8_t)(1U << (bit % 8));
}
static int zoneList(int bit, uint16_t *out)   /* повертає довжину щільного списку (до першого нуля) */
{
	uint8_t *p = &s_eeprom[ADDR_ZONES + bit * ZONE_STRIDE] + 16;
	int n = 0;
	for (; n < 80; n++) { memcpy(&out[n], p + 2 * n, 2); if (out[n] == 0) { break; } }
	return n;
}
static void setLucz(int bit, int idx)         { s_eeprom[ADDR_LUCZ + 4 + bit] = (uint8_t)idx; }
static void setLuczAll(int ch)                { int16_t v = (int16_t)(ch - 1); memcpy(&s_eeprom[ADDR_LUCZ + 4 + 68], &v, 2); }
static int  getLucz(int bit)                  { return s_eeprom[ADDR_LUCZ + 4 + bit]; }
static int  getLuczAll(void)                  { int16_t v; memcpy(&v, &s_eeprom[ADDR_LUCZ + 4 + 68], 2); return v + 1; }

static void reset(void)
{
	memset(s_eeprom, 0, sizeof(s_eeprom));
	memset(s_flash, 0xFF, sizeof(s_flash));
	/* заголовки банків 1..7 у флеші -- нулі (нема каналів), як у порожньому кодплазі */
	for (int b = 1; b < 8; b++) { memset(&s_flash[FLASH_ADDRESS_OFFSET + ADDR_HDR_FLASH + (b - 1) * (128 * REC + 16)], 0, 16); }
	memcpy(&s_eeprom[ADDR_LUCZ], "LUCZ", 4);
	s_failEepLo = s_failEepHi = s_failFlashLo = s_failFlashHi = -1;
	codeplugChannelsPerZone = 80;
	strcpy((char *)s_lang.all_channels, "All");
}
static void initCaches(void)   /* як після завантаження рації */
{
	codeplugZonesInitCache();
	codeplugAllChannelsInitCache();
	codeplugInitLastUsedChannelInZone();
}

/* --- знімок-диф ------------------------------------------------------------------------------------------------------------------ */
typedef struct { int lo, hi; bool flash; } range_t;       /* [lo, hi) в образі */
static uint8_t snapE[EEPROM_SIZE];
static uint8_t snapF[FLASH_SIZE];
static void snapshot(void) { memcpy(snapE, s_eeprom, sizeof(snapE)); memcpy(snapF, s_flash, sizeof(snapF)); }
static bool inRanges(int a, bool flash, const range_t *r, int nr)
{
	for (int i = 0; i < nr; i++) { if ((r[i].flash == flash) && (a >= r[i].lo) && (a < r[i].hi)) { return true; } }
	return false;
}
/* скільки байтів образу змінилося ПОЗА дозволеними діапазонами */
static int strayChanges(const range_t *allowed, int n)
{
	int stray = 0;
	for (int a = 0; a < EEPROM_SIZE; a++) { if ((s_eeprom[a] != snapE[a]) && !inRanges(a, false, allowed, n)) { stray++; } }
	for (int a = 0; a < FLASH_SIZE; a++) { if ((s_flash[a] != snapF[a]) && !inRanges(a, true, allowed, n)) { stray++; } }
	return stray;
}
static range_t R_rec(int ch)  { range_t r; uint8_t *p = recPtr(ch); bool fl = (ch > 128); r.flash = fl; r.lo = (int)(p - (fl ? s_flash : s_eeprom)); r.hi = r.lo + REC; return r; }
static range_t R_mask(int ch) { range_t r; uint8_t *p = maskBytePtr(ch); bool fl = (ch > 128); r.flash = fl; r.lo = (int)(p - (fl ? s_flash : s_eeprom)); r.hi = r.lo + 1; return r; }
static range_t R_zone(int bit){ range_t r; r.flash = false; r.lo = ADDR_ZONES + bit * ZONE_STRIDE; r.hi = r.lo + ZONE_STRIDE; return r; }
static range_t R_lucz(void)   { range_t r; r.flash = false; r.lo = ADDR_LUCZ; r.hi = ADDR_LUCZ + 4 + 70; return r; }

static bool recIsBlank(int ch) { const uint8_t *p = recPtr(ch); for (int i = 0; i < REC; i++) { if (p[i] != 0xFF) { return false; } } return true; }
static bool recIntact(int ch)  { return (memcmp(recPtr(ch), "CH", 2) == 0) && (recPtr(ch)[2] == (uint8_t)(ch & 0xFF)) && (recPtr(ch)[REC - 1] == (uint8_t)(0x40 + (ch % 100))); }

/* ---- сценарії ------------------------------------------------------------------------------------------------------------------- */
static const int SAMPLE[] = { 1, 2, 3, 5, 7, 9, 127, 128, 129, 130, 255, 256, 257, 300, 511, 512, 513, 1023, 1024 };
#define NSAMPLE ((int)(sizeof(SAMPLE) / sizeof(SAMPLE[0])))

static void world(void)
{
	reset();
	for (int i = 0; i < NSAMPLE; i++) { addChannel(SAMPLE[i]); }
	{ uint16_t z0[] = { 3, 5, 7 };          addZone(0, z0, 3); }
	{ uint16_t z1[] = { 5, 9, 5, 300 };     addZone(1, z1, 4); }     /* 5 двічі в одній зоні */
	{ uint16_t z2[] = { 1, 2, 3, 5 };       addZone(2, z2, 4); }
	{ uint16_t z3[] = { 129, 130, 1024 };   addZone(5, z3, 3); }     /* біт 5: зони 3,4 -- «дірка» в масці зон */
	initCaches();
}

int main(void)
{
	printf("test_codeplug_chandel:\n");

	/* ---------- Z1/Z3: розкладка -- кожен зразковий канал, усі межі банків ---------- */
	{
		int bad = 0;
		for (int i = 0; i < NSAMPLE; i++)
		{
			int ch = SAMPLE[i];
			world();
			CodeplugChannelDeleteResult_t r = codeplugChannelDelete(ch);
			bool ok = (r == CODEPLUG_CHANNEL_DELETE_OK) && !maskBit(ch) && recIsBlank(ch) && !codeplugAllChannelsIndexIsInUse(ch);
			for (int k = 0; k < NSAMPLE; k++) { if ((SAMPLE[k] != ch) && (!maskBit(SAMPLE[k]) || !recIntact(SAMPLE[k]) || !codeplugAllChannelsIndexIsInUse(SAMPLE[k]))) { ok = false; } }
			/* ПОЗА маскою, записом, зонами й LUCZ нічого не змінилося: звужуємо до зон, де канал справді стояв */
			if (!ok) { bad++; printf("  деталі: канал %d: r=%d maskBit=%d blank=%d\n", ch, (int)r, (int)maskBit(ch), (int)recIsBlank(ch)); }
		}
		CHECK(bad == 0, "Z1/Z3: видалення кожного з %d зразкових каналів (межі банків: 1,128,129,256,257,512,513,1024): маска й запис очищені, решта цілі", NSAMPLE);
	}

	/* ---------- Z1: знімок-диф -- змінитися можуть лише дозволені місця ---------- */
	{
		int bad = 0;
		for (int i = 0; i < NSAMPLE; i++)
		{
			int ch = SAMPLE[i];
			range_t allowed[16]; int na = 0;

			world();
			/* дозволено: маска, запис, LUCZ і ЛИШЕ ті зони, де канал стояв */
			allowed[na++] = R_rec(ch); allowed[na++] = R_mask(ch); allowed[na++] = R_lucz();
			for (int b = 0; b < 68; b++)
			{
				uint16_t l[81]; int n = zoneList(b, l);
				for (int k = 0; k < n; k++) { if (l[k] == ch) { allowed[na++] = R_zone(b); break; } }
			}
			snapshot();
			(void)codeplugChannelDelete(ch);
			if (strayChanges(allowed, na) != 0) { bad++; printf("  деталі: канал %d: сторонніх змін %d\n", ch, strayChanges(allowed, na)); }
		}
		CHECK(bad == 0, "Z1: знімок-диф усього EEPROM+флешу: поза маскою/записом/LUCZ/зонами, де канал стояв, не змінився жоден байт");
	}

	/* ---------- Z2: канал у трьох зонах (5: Z0 середина, Z1 двічі, Z2 кінець) ---------- */
	{
		uint16_t l[81]; int n;
		world();
		CHECK(codeplugChannelCountZones(5) == 3, "Z2: канал 5 у 3 справжніх зонах (двічі в одній -- рахується раз), є %d", codeplugChannelCountZones(5));
		CHECK(codeplugChannelCountZones(1024) == 1, "Z2: канал 1024 в 1 зоні (є %d)", codeplugChannelCountZones(1024));
		CHECK(codeplugChannelCountZones(2) == 1, "Z2: канал 2 в 1 зоні (є %d)", codeplugChannelCountZones(2));
		CHECK(codeplugChannelCountZones(513) == 0, "Z2: канал 513 в жодній зоні (є %d)", codeplugChannelCountZones(513));
		CHECK(codeplugChannelCountZones(6) == 0, "Z2: неіснуючий канал 6 -- 0 зон");
		CHECK(codeplugChannelDelete(5) == CODEPLUG_CHANNEL_DELETE_OK, "Z2: видалення 5 успішне");
		n = zoneList(0, l); CHECK((n == 2) && (l[0] == 3) && (l[1] == 7) && (l[2] == 0), "Z2: Z0 -> {3,7}: щільний список, номери не змінилися (є n=%d %d,%d)", n, l[0], l[1]);
		n = zoneList(1, l); CHECK((n == 2) && (l[0] == 9) && (l[1] == 300) && (l[2] == 0), "Z2: Z1 -> {9,300}: обидва входження прибрано (є n=%d %d,%d)", n, l[0], l[1]);
		n = zoneList(2, l); CHECK((n == 3) && (l[0] == 1) && (l[1] == 2) && (l[2] == 3) && (l[3] == 0), "Z2: Z2 -> {1,2,3} (є n=%d)", n);
		n = zoneList(5, l); CHECK((n == 3) && (l[0] == 129) && (l[1] == 130) && (l[2] == 1024), "Z2: незачеплена зона Z5 цілком така сама");
		CHECK(codeplugChannelCountZones(5) == 0, "Z2: після видалення 5 -- у 0 зонах");
		for (int b = 0; b < 68; b++) { n = zoneList(b, l); for (int k = 0; k < n; k++) { if (l[k] == 5) { CHECK(false, "Z2: у зоні %d лишилось посилання на 5", b); } } }
		/* зона з дірою: навігація по зонах не зламалась (число зон те саме) */
		CHECK(codeplugZonesGetCount() == 5, "Z2: 4 зони в масці + «Всі канали» = 5 (є %d)", codeplugZonesGetCount());
	}

	/* ---------- Z3: єдиний канал ---------- */
	{
		reset(); addChannel(77);
		{ uint16_t z[] = { 77 }; addZone(0, z, 1); }
		initCaches(); snapshot();
		CHECK(codeplugChannelCountInUse() == 1, "Z3: у кодплазі 1 канал");
		CHECK(codeplugChannelDelete(77) == CODEPLUG_CHANNEL_DELETE_LAST, "Z3: єдиний канал -> LAST");
		CHECK(strayChanges(NULL, 0) == 0, "Z3: образ EEPROM+флеш НЕ змінився (відмова без побічних записів)");
		CHECK(maskBit(77) && recIntact(77) && codeplugAllChannelsIndexIsInUse(77), "Z3: канал 77 на місці");
	}

	/* ---------- Z3: канал, якого нема, і номери поза межами ---------- */
	{
		world(); snapshot();
		CHECK(codeplugChannelDelete(6) == CODEPLUG_CHANNEL_DELETE_NOT_IN_USE, "Z3: 6 не в роботі -> NOT_IN_USE");
		CHECK(codeplugChannelDelete(0) == CODEPLUG_CHANNEL_DELETE_NOT_IN_USE, "Z3: 0 -> NOT_IN_USE");
		CHECK(codeplugChannelDelete(1025) == CODEPLUG_CHANNEL_DELETE_NOT_IN_USE, "Z3: 1025 -> NOT_IN_USE");
		CHECK(codeplugChannelDelete(-4) == CODEPLUG_CHANNEL_DELETE_NOT_IN_USE, "Z3: -4 -> NOT_IN_USE");
		CHECK(strayChanges(NULL, 0) == 0, "Z3: образ не змінився");
		/* повторне видалення того ж каналу */
		CHECK(codeplugChannelDelete(9) == CODEPLUG_CHANNEL_DELETE_OK, "Z3: 9 видалено");
		CHECK(codeplugChannelDelete(9) == CODEPLUG_CHANNEL_DELETE_NOT_IN_USE, "Z3: повторно 9 -> NOT_IN_USE");
	}

	/* ---------- лічильники «Всі канали» ---------- */
	{
		CodeplugZone_t z;
		world();
		CHECK(codeplugChannelCountInUse() == NSAMPLE, "кількість каналів у роботі = %d (є %d)", NSAMPLE, codeplugChannelCountInUse());
		codeplugZoneGetDataForNumber(codeplugZonesGetCount() - 1, &z);
		CHECK(z.NOT_IN_CODEPLUGDATA_numChannelsInZone == NSAMPLE, "«Всі канали»: numChannels = %d (є %d)", NSAMPLE, z.NOT_IN_CODEPLUGDATA_numChannelsInZone);
		CHECK(z.NOT_IN_CODEPLUGDATA_highestIndex == 1024, "«Всі канали»: highest = 1024 (є %d)", z.NOT_IN_CODEPLUGDATA_highestIndex);
		(void)codeplugChannelDelete(1024);
		codeplugZoneGetDataForNumber(codeplugZonesGetCount() - 1, &z);
		CHECK(z.NOT_IN_CODEPLUGDATA_numChannelsInZone == NSAMPLE - 1, "після видалення 1024: numChannels = %d (є %d)", NSAMPLE - 1, z.NOT_IN_CODEPLUGDATA_numChannelsInZone);
		CHECK(z.NOT_IN_CODEPLUGDATA_highestIndex == 1023, "після видалення 1024: highest = 1023 (є %d)", z.NOT_IN_CODEPLUGDATA_highestIndex);
		(void)codeplugChannelDelete(1023);
		codeplugZoneGetDataForNumber(codeplugZonesGetCount() - 1, &z);
		CHECK(z.NOT_IN_CODEPLUGDATA_highestIndex == 513, "після видалення 1023: highest = 513 (є %d)", z.NOT_IN_CODEPLUGDATA_highestIndex);
	}

	/* ---------- Z4: активний канал -- LUCZ ---------- */
	{
		/* Z0 = {3,5,7}: LUCZ=1 (канал 5, середина) -> після видалення 5 це {3,7}, позиція 1 = 7 (наступний) */
		world(); setLucz(0, 1); initCaches();
		(void)codeplugChannelDelete(5);
		CHECK(getLucz(0) == 1, "Z4: Z0 {3,5,7}, активний 5 (поз.1) -> поз.1 = 7, наступний (є %d)", getLucz(0));
		/* LUCZ=2 (канал 7, кінець), видаляємо 7 -> {3,5}: позиція 2 поза списком -> перший (0) */
		world(); setLucz(0, 2); initCaches();
		(void)codeplugChannelDelete(7);
		CHECK(getLucz(0) == 0, "Z4: Z0 {3,5,7}, активний 7 (останній) -> поз.0, перший (є %d)", getLucz(0));
		/* LUCZ=2 (канал 7), видаляємо 3 (лівіше) -> {5,7}: позиція 1 (той самий канал 7) */
		world(); setLucz(0, 2); initCaches();
		(void)codeplugChannelDelete(3);
		CHECK(getLucz(0) == 1, "Z4: Z0 {3,5,7}, активний 7, видаляємо лівіший 3 -> поз.1 (той самий канал 7) (є %d)", getLucz(0));
		/* LUCZ=0 (канал 3), видаляємо 7 (правіше) -> поз.0 лишається */
		world(); setLucz(0, 0); initCaches();
		(void)codeplugChannelDelete(7);
		CHECK(getLucz(0) == 0, "Z4: активний 3, видаляємо правіший 7 -> поз.0 без змін (є %d)", getLucz(0));
		/* «Всі канали»: активний 300 -> наступний у роботі 511 */
		world(); setLuczAll(300); initCaches();
		(void)codeplugChannelDelete(300);
		CHECK(getLuczAll() == 511, "Z4: «Всі канали», активний 300 -> 511, наступний (є %d)", getLuczAll());
		/* найвищий 1024 -> з переходом через кінець на найнижчий (1) */
		world(); setLuczAll(1024); initCaches();
		(void)codeplugChannelDelete(1024);
		CHECK(getLuczAll() == 1, "Z4: «Всі канали», активний 1024 -> 1, з переходом через кінець (є %d)", getLuczAll());
		/* «Всі канали», активний інший -> LUCZ не чіпаємо */
		world(); setLuczAll(7); initCaches();
		(void)codeplugChannelDelete(300);
		CHECK(getLuczAll() == 7, "Z4: «Всі канали», активний 7, видаляємо 300 -> LUCZ без змін (є %d)", getLuczAll());
		/* зона спорожніла: Z0 = {9} */
		reset(); addChannel(9); addChannel(4); { uint16_t z[] = { 9 }; addZone(0, z, 1); }
		initCaches();
		CHECK(codeplugZoneIsUsable(0, NULL), "Z4: зона {9} придатна до видалення");
		(void)codeplugChannelDelete(9);
		CHECK(!codeplugZoneIsUsable(0, NULL), "Z4: після видалення єдиного каналу зона порожня -> НЕ придатна (меню її не покаже, uiChannelInitializeCurrentZone піде на «Всі канали»)");
		CHECK(codeplugChannelNextInUse(0) == 4, "Z4: перший канал «Всіх каналів» = 4 (є %d)", codeplugChannelNextInUse(0));
	}

	/* ---------- CQ7: перезапуск -- стан із образу ---------- */
	{
		uint8_t before[128];
		world(); (void)codeplugChannelDelete(300); (void)codeplugChannelDelete(5); (void)codeplugChannelDelete(129);
		memcpy(before, codeplugAllChannelsCache, 128);
		initCaches();
		CHECK(memcmp(before, codeplugAllChannelsCache, 128) == 0, "CQ7: після «перезапуску» (читання кешів із образу) маска та сама");
		CHECK(!codeplugAllChannelsIndexIsInUse(300) && !codeplugAllChannelsIndexIsInUse(5) && !codeplugAllChannelsIndexIsInUse(129) &&
				codeplugAllChannelsIndexIsInUse(130), "CQ7: 300, 5, 129 видалені, 130 живий");
		CHECK(codeplugChannelCountInUse() == NSAMPLE - 3, "CQ7: лишилось %d каналів (є %d)", NSAMPLE - 3, codeplugChannelCountInUse());
	}

	/* ---------- збій запису: порядок «зони -> маска -> ...» і відмова без побічних наслідків ---------- */
	{
		/* збій запису БАЙТА МАСКИ (канал у EEPROM): канал лишається живий, видалення відхилено */
		world(); setLuczAll(5); initCaches();
		s_failEepLo = ADDR_HDR_EEP; s_failEepHi = ADDR_HDR_EEP + 16;
		CHECK(codeplugChannelDelete(5) == CODEPLUG_CHANNEL_DELETE_WRITE_ERROR, "збій запису маски (EEPROM) -> WRITE_ERROR");
		CHECK(codeplugAllChannelsIndexIsInUse(5) && maskBit(5) && recIntact(5), "збій маски: канал 5 живий (кеш, маска, запис)");
		CHECK(getLuczAll() == 5, "збій маски: LUCZ «Всіх каналів» не зачеплено");
		/* збій запису маски у ФЛЕШІ */
		world(); initCaches();
		s_failFlashLo = FLASH_ADDRESS_OFFSET + ADDR_HDR_FLASH; s_failFlashHi = s_failFlashLo + 8 * (128 * REC + 16);
		CHECK(codeplugChannelDelete(300) == CODEPLUG_CHANNEL_DELETE_WRITE_ERROR, "збій запису маски (флеш) -> WRITE_ERROR");
		CHECK(codeplugAllChannelsIndexIsInUse(300) && maskBit(300) && recIntact(300), "збій маски (флеш): канал 300 живий");
		/* збій запису зони: маску ще не чіпали -> канал живий */
		world(); initCaches();
		s_failEepLo = ADDR_ZONES; s_failEepHi = ADDR_ZONES + 8 * ZONE_STRIDE;
		CHECK(codeplugChannelDelete(5) == CODEPLUG_CHANNEL_DELETE_WRITE_ERROR, "збій запису зони -> WRITE_ERROR");
		CHECK(codeplugAllChannelsIndexIsInUse(5) && maskBit(5) && recIntact(5), "збій зони: маска ще не чіпана, канал 5 живий");
	}

	/* ---------- цілісність флешу: сусідні канали в тому ж секторі ---------- */
	{
		/* канали 300 і 301 лежать у сусідніх записах одного сектора: видалення 300 не псує 301 і заголовки банків */
		world(); addChannel(301); initCaches();
		(void)codeplugChannelDelete(300);
		CHECK(recIsBlank(300) && recIntact(301) && maskBit(301) && !maskBit(300), "флеш: сусід 301 цілий після видалення 300 (RMW сектора)");
		/* запис, що перетинає межу сектора (кожен 73-й приблизно) */
		int cross = 0;
		for (int ch = 130; ch <= 1024; ch++)
		{
			int n = ch - 1 - 128; int pos = ADDR_CH_FLASH + 16 * (n / 128) + n * REC;
			if ((pos / 4096) != ((pos + REC - 1) / 4096) && cross < 4)
			{
				world(); addChannel(ch); addChannel(ch + 1 > 1024 ? ch - 1 : ch + 1); initCaches();
				int nb = (ch + 1 > 1024) ? ch - 1 : ch + 1;
				(void)codeplugChannelDelete(ch);
				CHECK(recIsBlank(ch) && recIntact(nb) && !maskBit(ch), "флеш: запис %d перетинає межу сектора -- стертий повністю, сусід %d цілий", ch, nb);
				cross++;
			}
		}
		CHECK(cross == 4, "флеш: знайдено й перевірено 4 записи на межі сектора (є %d)", cross);
	}

	/* ---------- 16-канальні зони (старий формат кодплага) ---------- */
	{
		reset(); codeplugChannelsPerZone = 16;
		for (int c = 1; c <= 6; c++) { addChannel(c); }
		{
			uint8_t *p = &s_eeprom[ADDR_ZONES + 0 * (16 + 2 * 16)];
			uint16_t l[] = { 2, 4, 6 };
			memset(p, 0xFF, 16); memcpy(p, "Old", 4); memset(p + 16, 0, 32);
			for (int i = 0; i < 3; i++) { memcpy(p + 16 + 2 * i, &l[i], 2); }
			s_eeprom[ADDR_ZONEMASK] |= 1;
		}
		initCaches();
		CHECK(codeplugChannelCountZones(4) == 1, "16-канальна зона: канал 4 в 1 зоні");
		CHECK(codeplugChannelDelete(4) == CODEPLUG_CHANNEL_DELETE_OK, "16-канальна зона: видалення 4");
		{
			uint8_t *p = &s_eeprom[ADDR_ZONES];
			uint16_t a, b, c; memcpy(&a, p + 16, 2); memcpy(&b, p + 18, 2); memcpy(&c, p + 20, 2);
			CHECK((a == 2) && (b == 6) && (c == 0), "16-канальна зона -> {2,6} (є %d,%d,%d)", a, b, c);
		}
		codeplugChannelsPerZone = 80;
	}

	printf("%s\n", fails ? "ПРОВАЛ" : "УСЕ ДОБРЕ");
	return fails ? 1 : 0;
}
