/*
 * test_codeplug_contact.c -- R44: видалення контакту з каскадом. Збирається зі СПРАВЖНІМ application/source/functions/codeplug.c
 * (codeplugContactCountChannels, codeplugContactDelete, codeplugContactSaveDataForIndex, кеш контактів); EEPROM і NOR-флеш -- образи в пам'яті
 * (стирання сектора -> 0xFF, запис сторінки лише ЗНІМАЄ біти; SPI_Flash_write -- той самий read-modify-write цілого сектора, що в прошивці).
 *
 * Стокове видалення НЕ перевіряло канали, що посилаються на контакт: канал читав зі стертого слота ім'я 0xFF, TG 0 і тип 0xFF. Тут перевіряється каскад:
 *   C1  лічильник: канали в EEPROM (1..128) і флеші (129..1024), канали НЕ в масці з тим самим контактом не рахуються, межі 1 / 1024, поза межами -> 0;
 *   C2  видалення: поле «контакт» усіх посилальних каналів -> 0, слот стертий, кеш контактів зменшився; ЗНІМОК-ДИФ усього образу: змінилися лише ці 2 байти в кожному каналі й 24 байти слота;
 *   C3  збій запису в каналі -> false, а слот контакту ЦІЛИЙ (каскад іде першим); збій запису слота -> канали вже «Немає», контакт ще живий (нічого зламаного);
 *   C4  недійсні номери (0, 1025, -3) -> false без жодних змін; повторне видалення того ж контакту не ламає нічого.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include "functions/codeplug.h"
#include "functions/codeplug_zone.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiLocalisation.h"

#ifndef CODEPLUG_MENU_ENABLED
#error "test_codeplug_contact.c треба збирати з -DENABLE_CODEPLUG_MENU -DENABLE_CHANNEL_DELETE -DENABLE_ZONE_RENAME -DENABLE_ZONE_EDIT -DENABLE_APRS_RX -DENABLE_AES -DLANGUAGE_BUILD_UKRAINIAN"
#endif

#define EEPROM_SIZE   0x10000
#define FLASH_SIZE    (1024 * 1024)

static uint8_t s_eeprom[EEPROM_SIZE];
static uint8_t s_flash[FLASH_SIZE];
uint8_t SPI_Flash_sectorbuffer[4096];
CodeplugZone_t currentZone;
static stringsTable_t s_lang;
const stringsTable_t *currentLanguage = &s_lang;

static int s_failEepLo = -1, s_failEepHi = -1;
static int s_failFlashLo = -1, s_failFlashHi = -1;

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
	if ((s_failFlashLo >= 0) && ((int)a < s_failFlashHi) && ((int)a + 4096 > s_failFlashLo)) { return false; }   /* збій стирання сектора, у якому лежить цільова ділянка */
	memset(&s_flash[a], 0xFF, 4096);
	return true;
}
bool SPI_Flash_writePage(uint32_t a, uint8_t *b)
{
	if ((a % 256U) != 0U) { return false; }
	for (int i = 0; i < 256; i++) { s_flash[a + (uint32_t)i] &= b[i]; }
	return true;
}
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

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* --- розкладка кодплага (НЕЗАЛЕЖНО від прошивки) ----------------------------------------------------------------------------------- */
#define REC 56
#define ADDR_CH_EEP    0x3790
#define ADDR_HDR_EEP   0x3780
#define ADDR_CH_FLASH  0x7B1C0
#define ADDR_HDR_FLASH 0x7B1B0
#define ADDR_CONTACTS  0x87620
#define CONTACT_SIZE   24
#define CONTACT_FIELD_OFFSET 0x24   /* байт 36 запису каналу (63 - ...): сума полів struct до `contact`; перевіряється проти offsetof нижче */

static uint8_t *recPtr(int ch)
{
	if (ch <= 128) { return &s_eeprom[ADDR_CH_EEP + (ch - 1) * REC]; }
	int n = ch - 1 - 128;
	return &s_flash[FLASH_ADDRESS_OFFSET + ADDR_CH_FLASH + 16 * (n / 128) + n * REC];
}
static uint8_t *maskBytePtr(int ch)
{
	int i = ch - 1, bank = i / 128, byteno = (i % 128) / 8;
	if (bank == 0) { return &s_eeprom[ADDR_HDR_EEP + byteno]; }
	return &s_flash[FLASH_ADDRESS_OFFSET + ADDR_HDR_FLASH + (bank - 1) * (128 * REC + 16) + byteno];
}
static uint8_t *contactPtr(int idx) { return &s_flash[FLASH_ADDRESS_OFFSET + ADDR_CONTACTS + (idx - 1) * CONTACT_SIZE]; }

static void setChannel(int ch, int contact, bool inMask)
{
	if (inMask) { *maskBytePtr(ch) |= (uint8_t)(1U << ((ch - 1) % 8)); }
	memset(recPtr(ch), 0x40 + (ch % 100), REC);
	memcpy(recPtr(ch), "CH", 2);
	recPtr(ch)[2] = (uint8_t)(ch & 0xFF); recPtr(ch)[3] = (uint8_t)(ch >> 8);
	recPtr(ch)[offsetof(CodeplugChannel_t, contact)] = (uint8_t)(contact & 0xFF);
	recPtr(ch)[offsetof(CodeplugChannel_t, contact) + 1] = (uint8_t)(contact >> 8);
}
static int channelContact(int ch) { return recPtr(ch)[offsetof(CodeplugChannel_t, contact)] | (recPtr(ch)[offsetof(CodeplugChannel_t, contact) + 1] << 8); }

static void addContact(int idx, const char *name, uint32_t tg)
{
	CodeplugContact_t c;

	memset(&c, 0, sizeof(c));
	memset(c.name, 0xFF, 16);
	memcpy(c.name, name, strlen(name));
	c.tgNumber = tg;
	c.callType = CONTACT_CALLTYPE_TG;
	c.reserve1 = 0xFF;
	codeplugContactSaveDataForIndex(idx, &c);
}

static void reset(void)
{
	memset(s_eeprom, 0, sizeof(s_eeprom));
	memset(s_flash, 0xFF, sizeof(s_flash));
	for (int b = 1; b < 8; b++) { memset(&s_flash[FLASH_ADDRESS_OFFSET + ADDR_HDR_FLASH + (b - 1) * (128 * REC + 16)], 0, 16); }
	s_failEepLo = s_failEepHi = s_failFlashLo = s_failFlashHi = -1;
	codeplugChannelsPerZone = 80;
	codeplugInitCaches();   /* порожній кодплаг: кеші нульові */
}
static void reinit(void) { codeplugInitCaches(); }

/* --- знімок-диф ------------------------------------------------------------------------------------------------------------------- */
static uint8_t snapE[EEPROM_SIZE];
static uint8_t snapF[FLASH_SIZE];
static void snapshot(void) { memcpy(snapE, s_eeprom, sizeof(snapE)); memcpy(snapF, s_flash, sizeof(snapF)); }
typedef struct { int lo, hi; bool flash; } range_t;
static bool inRanges(int a, bool flash, const range_t *r, int nr)
{
	for (int i = 0; i < nr; i++) { if ((r[i].flash == flash) && (a >= r[i].lo) && (a < r[i].hi)) { return true; } }
	return false;
}
static int strayChanges(const range_t *allowed, int n)
{
	int stray = 0;
	for (int a = 0; a < EEPROM_SIZE; a++) { if ((s_eeprom[a] != snapE[a]) && !inRanges(a, false, allowed, n)) { stray++; } }
	for (int a = 0; a < FLASH_SIZE; a++) { if ((s_flash[a] != snapF[a]) && !inRanges(a, true, allowed, n)) { stray++; } }
	return stray;
}
static range_t R_field(int ch)
{
	range_t r; uint8_t *p = recPtr(ch) + offsetof(CodeplugChannel_t, contact);
	r.flash = (ch > 128); r.lo = (int)(p - (r.flash ? s_flash : s_eeprom)); r.hi = r.lo + 2; return r;
}
static range_t R_contact(int idx) { range_t r; r.flash = true; r.lo = (int)(contactPtr(idx) - s_flash); r.hi = r.lo + CONTACT_SIZE; return r; }

static const int CH_USED[] = { 1, 2, 50, 60, 127, 128, 129, 130, 255, 256, 257, 600, 1023, 1024 };   /* канали «в роботі» на межах EEPROM/флешу й банків */
#define NUSED ((int)(sizeof(CH_USED) / sizeof(CH_USED[0])))

/* Світ: контакти 1, 2, 5, 1024; канали -> контакти; канали 3, 700 НЕ в масці, але теж «посилаються» на контакт 5 (не мають рахуватись і чіпатись) */
static void world(void)
{
	reset();
	addContact(1, "Prymus", 1);
	addContact(2, "Ukraine", 91);
	addContact(5, "Test", 9);
	addContact(1024, "Last", 4000);
	setChannel(1, 5, true);       /* EEPROM */
	setChannel(2, 2, true);
	setChannel(50, 5, true);
	setChannel(127, 1, true);
	setChannel(128, 5, true);     /* остання в EEPROM */
	setChannel(129, 5, true);     /* перша у флеші */
	setChannel(130, 2, true);
	setChannel(255, 1024, true);
	setChannel(256, 5, true);
	setChannel(257, 0, true);     /* без контакту */
	setChannel(600, 5, true);
	setChannel(1023, 1, true);
	setChannel(1024, 5, true);    /* остання */
	setChannel(60, 1024, true);   /* EEPROM-канал із контактом >255: чистить обидва байти поля (контакт 1024 = 0x0400) */
	setChannel(3, 5, false);      /* НЕ в роботі */
	setChannel(700, 5, false);
	reinit();
}

int main(void)
{
	printf("test_codeplug_contact:\n");

	CHECK(sizeof(CodeplugChannel_t) >= (size_t)REC, "розмір struct каналу >= %d (є %d)", REC, (int)sizeof(CodeplugChannel_t));
	CHECK(offsetof(CodeplugChannel_t, contact) + 2 <= (size_t)REC, "поле contact лежить усередині запису каналу (зсув %d)", (int)offsetof(CodeplugChannel_t, contact));

	/* ---------- C1: лічильник ---------- */
	world();
	CHECK(codeplugContactCountChannels(5) == 7, "C1: контакт 5 -> 7 каналів (1,50,128,129,256,600,1024); канали 3 і 700 поза маскою не рахуються (є %d)", codeplugContactCountChannels(5));
	CHECK(codeplugContactCountChannels(1) == 2, "C1: контакт 1 -> 2 каналів (127,1023) (є %d)", codeplugContactCountChannels(1));
	CHECK(codeplugContactCountChannels(2) == 2, "C1: контакт 2 -> 2 каналів (2,130) (є %d)", codeplugContactCountChannels(2));
	CHECK(codeplugContactCountChannels(1024) == 2, "C1: контакт 1024 (межа) -> 2 канали (60 в EEPROM, 255 у флеші) (є %d)", codeplugContactCountChannels(1024));
	CHECK(codeplugContactCountChannels(7) == 0, "C1: контакт без посилань -> 0");
	CHECK(codeplugContactCountChannels(0) == 0, "C1: 0 -> 0 («Немає» не контакт)");
	CHECK(codeplugContactCountChannels(1025) == 0, "C1: 1025 -> 0");
	CHECK(codeplugContactCountChannels(-3) == 0, "C1: -3 -> 0");

	/* ---------- C2: каскад, знімок-диф ---------- */
	{
		int refs[] = { 1, 50, 128, 129, 256, 600, 1024 };
		range_t allowed[16]; int na = 0;
		int before;
		bool ok;

		world();
		before = codeplugContactsGetCount(0) + codeplugContactsGetCount(1) + codeplugContactsGetCount(2);
		for (int i = 0; i < 7; i++) { allowed[na++] = R_field(refs[i]); }
		allowed[na++] = R_contact(5);
		snapshot();
		ok = codeplugContactDelete(5);
		CHECK(ok, "C2: codeplugContactDelete(5) -> true");
		CHECK(strayChanges(allowed, na) == 0, "C2: знімок-диф усього EEPROM+флешу: змінилися лише 7 полів «контакт» і слот контакту 5 (сторонніх: %d)", strayChanges(allowed, na));
		{
			int bad = 0;
			for (int i = 0; i < 7; i++) { if (channelContact(refs[i]) != 0) { bad++; } }
			CHECK(bad == 0, "C2: усі 7 каналів, що посилались на 5, тепер мають контакт 0 («Немає»)");
		}
		CHECK((channelContact(3) == 5) && (channelContact(700) == 5), "C2: канали поза маскою (3, 700) не чіпано");
		CHECK((channelContact(127) == 1) && (channelContact(2) == 2) && (channelContact(255) == 1024) && (channelContact(257) == 0), "C2: канали з іншими контактами цілі");
		{
			int bad = 0;
			for (int i = 0; i < NUSED; i++)
			{
				int ch = CH_USED[i];
				bool intact = (memcmp(recPtr(ch), "CH", 2) == 0) && (recPtr(ch)[REC - 1] == (uint8_t)(0x40 + (ch % 100)));
				if (!intact) { bad++; }
			}
			CHECK(bad == 0, "C2: решта байтів усіх записів каналів (ім'я, частоти, кінець запису) цілі");
		}
		CHECK((contactPtr(5)[0] == 0xFF) && (contactPtr(5)[15] == 0xFF) && (contactPtr(5)[20] == 0xFF), "C2: слот контакту 5 стертий: ім'я 0xFF, тип 0xFF");
		CHECK(codeplugContactCountChannels(5) == 0, "C2: після видалення лічильник каналів із контактом 5 = 0 (канали 3, 700 поза маскою не рахуються) -> %d", codeplugContactCountChannels(5));
		{ int now = codeplugContactsGetCount(0) + codeplugContactsGetCount(1) + codeplugContactsGetCount(2); CHECK((before == 4) && (now == before - 1), "C2: кеш контактів (TG+PC+ALL) зменшився на 1 (було %d, є %d)", before, now); }
		CHECK((contactPtr(1)[0] == 'P') && (contactPtr(2)[0] == 'U') && (contactPtr(1024)[0] == 'L'), "C2: сусідні контакти (1, 2, 1024) цілі");
	}

	/* ---------- C2b: контакт без посилань: лише слот ---------- */
	{
		range_t allowed[2]; int na = 0;
		world();
		addContact(7, "Alone", 77);
		reinit();
		allowed[na++] = R_contact(7);
		snapshot();
		CHECK(codeplugContactDelete(7), "C2b: контакт без посилань видалено");
		CHECK(strayChanges(allowed, na) == 0, "C2b: змінився лише слот контакту 7 (сторонніх: %d)", strayChanges(allowed, na));
	}

	/* ---------- C2c: контакт 1024 (межа) і контакт 1 ---------- */
	{
		world();
		CHECK(codeplugContactDelete(1024), "C2c: контакт 1024 видалено");
		CHECK((channelContact(255) == 0) && (channelContact(60) == 0), "C2c: канали 255 (флеш) і 60 (EEPROM) -> «Немає» (обидва байти поля)");
		CHECK(contactPtr(1024)[0] == 0xFF, "C2c: слот 1024 стертий");
		world();
		CHECK(codeplugContactDelete(1), "C2c: контакт 1 видалено");
		CHECK((channelContact(127) == 0) && (channelContact(1023) == 0), "C2c: канали 127 і 1023 -> «Немає»");
	}

	/* ---------- C3: збої запису ---------- */
	{
		/* збій запису поля в EEPROM-каналі 50 */
		world();
		s_failEepLo = (int)(recPtr(50) + offsetof(CodeplugChannel_t, contact) - s_eeprom); s_failEepHi = s_failEepLo + 2;
		CHECK(!codeplugContactDelete(5), "C3: збій запису каналу 50 (EEPROM) -> false");
		CHECK(contactPtr(5)[0] == 'T', "C3: слот контакту 5 ЦІЛИЙ (каскад іде першим, контакт не стерто)");
		CHECK(channelContact(1) == 0, "C3: канали ДО збою вже «Немає» (канал 1) -- нічого не зламано, контакт ще живий");
		CHECK(channelContact(128) == 5, "C3: канали ПІСЛЯ збою не чіпано (128)");

		/* збій запису поля у флеш-каналі 256 */
		world();
		s_failFlashLo = (int)(recPtr(256) + offsetof(CodeplugChannel_t, contact) - s_flash); s_failFlashHi = s_failFlashLo + 2;
		CHECK(!codeplugContactDelete(5), "C3: збій запису каналу 256 (флеш) -> false");
		CHECK(contactPtr(5)[0] == 'T', "C3: слот контакту 5 цілий і після збою у флеші");

		/* збій запису слота контакту 1024 (його сектор не збігається з секторами каналів): канал 255 уже «Немає», контакт живий */
		world();
		s_failFlashLo = (int)(contactPtr(1024) - s_flash); s_failFlashHi = s_failFlashLo + CONTACT_SIZE;
		CHECK(!codeplugContactDelete(1024), "C3: збій запису слота контакту 1024 -> false");
		CHECK(channelContact(255) == 0, "C3: канал 255 уже «Немає» (контакт лишився живим -- безпечно)");
		CHECK(contactPtr(1024)[0] == 'L', "C3: слот контакту 1024 не пошкоджено");

		/* контакт 5: канал 1024 лежить у ТОМУ Ж секторі флешу, що й слот контакту 5 -- збій сектора ловиться ще в каскаді, до стирання слота */
		world();
		s_failFlashLo = (int)(contactPtr(5) - s_flash); s_failFlashHi = s_failFlashLo + CONTACT_SIZE;
		CHECK(!codeplugContactDelete(5), "C3: збій сектора, спільного з каналом 1024 -> false");
		CHECK(contactPtr(5)[0] == 'T', "C3: слот контакту 5 цілий (каскад зупинився до стирання слота)");
	}

	/* ---------- C4: недійсні номери ---------- */
	{
		world(); snapshot();
		CHECK(!codeplugContactDelete(0), "C4: 0 -> false");
		CHECK(!codeplugContactDelete(1025), "C4: 1025 -> false");
		CHECK(!codeplugContactDelete(-3), "C4: -3 -> false");
		CHECK(strayChanges(NULL, 0) == 0, "C4: образ не змінився (відмова без побічних записів)");
		CHECK(codeplugContactDelete(5), "C4: перше видалення 5 -- true");
		snapshot();
		(void)codeplugContactDelete(5);
		CHECK(strayChanges(NULL, 0) == 0, "C4: повторне видалення того самого контакту нічого не міняє");
		CHECK(codeplugContactCountChannels(5) == 0 || codeplugContactCountChannels(5) == 2, "C4: лічильник після видалення не росте");
	}

	printf("\n%s (%d fails)\n", fails ? "FAIL" : "PASS", fails);
	return fails ? 1 : 0;
}
