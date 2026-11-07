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
#error "test_codeplug_rxgroup.c треба збирати з -DENABLE_CODEPLUG_MENU -DENABLE_CHANNEL_DELETE -DENABLE_ZONE_RENAME -DENABLE_ZONE_EDIT -DENABLE_APRS_RX -DENABLE_AES -DLANGUAGE_BUILD_UKRAINIAN"
#endif

#define EEPROM_SIZE   0x10000
#define FLASH_SIZE    (1024 * 1024)

static uint8_t s_eeprom[EEPROM_SIZE];
static uint8_t s_flash[FLASH_SIZE];
uint8_t SPI_Flash_sectorbuffer[4096];
CodeplugZone_t currentZone;
static stringsTable_t s_lang;
const stringsTable_t *currentLanguage = &s_lang;

static bool takeBudget_fwd(void);
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
	if (!takeBudget_fwd()) { return false; }
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
static int s_budget = -1;     /* скільки ще записів (SPI_Flash_write/EEPROM_Write) дозволено; 0 -- «живлення зникло»: запис не виконується; -1 -- без ліміту */
static int s_passes = 0;      /* скільки проходів «прочитати сектор -> стерти -> записати» зроблено (як у справжньому SPI_Flash_write) */
static int s_nwrites = 0;     /* скільки викликів запису (флеш + EEPROM) */
static bool takeBudget(void)
{
	if (s_budget == 0) { return false; }
	if (s_budget > 0) { s_budget--; }
	s_nwrites++;
	return true;
}
static bool takeBudget_fwd(void) { return takeBudget(); }
bool SPI_Flash_write(uint32_t addr, uint8_t *dataBuf, int size)
{
	/* ТОЙ САМИЙ алгоритм, що application/source/hardware/SPI_Flash.c: flashEndSector = (addr + size) / 4096, тож запис, який закінчується РІВНО на межі сектора, робить і другий прохід. */
	uint32_t sector = addr / 4096U, endSector = (addr + (uint32_t)size) / 4096U;
	int n = (sector != endSector) ? (int)(endSector * 4096U - addr) : size;

	if (!takeBudget()) { return false; }
	if ((s_failFlashLo >= 0) && ((int)addr < s_failFlashHi) && ((int)addr + size > s_failFlashLo)) { return false; }
	SPI_Flash_read(sector * 4096U, SPI_Flash_sectorbuffer, 4096);
	memcpy(SPI_Flash_sectorbuffer + (addr - sector * 4096U), dataBuf, (size_t)n);
	if (!SPI_Flash_eraseSector(sector * 4096U)) { return false; }
	for (int i = 0; i < 16; i++) { if (!SPI_Flash_writePage(sector * 4096U + (uint32_t)(i * 256), SPI_Flash_sectorbuffer + i * 256)) { return false; } }
	s_passes++;
	if (sector != endSector)
	{
		SPI_Flash_read(endSector * 4096U, SPI_Flash_sectorbuffer, 4096);
		memcpy(SPI_Flash_sectorbuffer, dataBuf + n, (size_t)(size - n));
		if (!SPI_Flash_eraseSector(endSector * 4096U)) { return false; }
		for (int i = 0; i < 16; i++) { if (!SPI_Flash_writePage(endSector * 4096U + (uint32_t)(i * 256), SPI_Flash_sectorbuffer + i * 256)) { return false; } }
		s_passes++;
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
#define ADDR_RXLEN     0x8D620
#define ADDR_RX        0x8D6A0
#define RXREC          80
#define ADDR_VFO_A     0x7590

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
static void setChannel(int ch, int grp, bool inMask)
{
	if (inMask) { *maskBytePtr(ch) |= (uint8_t)(1U << ((ch - 1) % 8)); }
	memset(recPtr(ch), 0x40 + (ch % 100), REC);
	memcpy(recPtr(ch), "CH", 2);
	recPtr(ch)[offsetof(CodeplugChannel_t, rxGroupList)] = (uint8_t)grp;
}
static int channelGrp(int ch) { return recPtr(ch)[offsetof(CodeplugChannel_t, rxGroupList)]; }
static uint8_t *vfoGrp(int v) { return &s_eeprom[ADDR_VFO_A + v * 56 + (int)offsetof(CodeplugChannel_t, rxGroupList)]; }

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
	/* вільні слоти списків: довжина 0 (таблиця довжин нульова), тіла 0xFF */
	memset(&s_flash[FLASH_ADDRESS_OFFSET + ADDR_RXLEN], 0, 76);
	s_failEepLo = s_failEepHi = s_failFlashLo = s_failFlashHi = -1;
	s_budget = -1; s_passes = 0; s_nwrites = 0;
	codeplugChannelsPerZone = 80;
	codeplugInitCaches();
}
static void reinit(void) { codeplugInitCaches(); }

static uint8_t snapE[EEPROM_SIZE];
static uint8_t snapF[FLASH_SIZE];
static void snapshot(void) { memcpy(snapE, s_eeprom, sizeof(snapE)); memcpy(snapF, s_flash, sizeof(snapF)); }
static void restore(void) { memcpy(s_eeprom, snapE, sizeof(snapE)); memcpy(s_flash, snapF, sizeof(snapF)); s_nwrites = 0; s_passes = 0; reinit(); }
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
static range_t R_flash(int addr, int len) { range_t r; r.flash = true; r.lo = FLASH_ADDRESS_OFFSET + addr; r.hi = r.lo + len; return r; }
static range_t R_chField(int ch)
{
	range_t r; uint8_t *p = recPtr(ch) + offsetof(CodeplugChannel_t, rxGroupList);
	r.flash = (ch > 128); r.lo = (int)(p - (r.flash ? s_flash : s_eeprom)); r.hi = r.lo + 1; return r;
}

extern const int CODEPLUG_ADDR_RX_GROUP, CODEPLUG_ADDR_RX_GROUP_LEN;
static uint8_t *lenPtr(int slot) { return &s_flash[FLASH_ADDRESS_OFFSET + ADDR_RXLEN + slot - 1]; }
static uint8_t *bodyPtr(int slot) { return &s_flash[FLASH_ADDRESS_OFFSET + ADDR_RX + (slot - 1) * RXREC]; }

/* Світ: 40 контактів, канали -> списки (на межах EEPROM/флешу й банків), канали поза маскою теж із посиланням, VFO A -> 3. Списки 1 «Alfa»(1,2,3), 3 «Bravo»(4), 30 «Zulu»(5,6). */
static const int CH_USED[] = { 1, 2, 50, 127, 128, 129, 130, 256, 257, 600, 1024 };
#define NUSED ((int)(sizeof(CH_USED) / sizeof(CH_USED[0])))
static void putGroup(int slot, const char *name, const uint16_t *m, int n)
{
	uint16_t buf[32] = { 0 };
	memset(bodyPtr(slot), 0, RXREC);
	memset(bodyPtr(slot), 0xFF, 16);
	memcpy(bodyPtr(slot), name, strlen(name));
	memcpy(bodyPtr(slot) + 16, m, (size_t)n * 2U);
	(void)buf;
	*lenPtr(slot) = (uint8_t)n;
}
static void world(void)
{
	static const uint16_t a[] = { 1, 2, 3 }, b[] = { 4 }, z[] = { 5, 6 };
	reset();
	for (int i = 1; i <= 40; i++) { char nm[16]; snprintf(nm, sizeof nm, "TG%d", i); addContact(i, nm, 1000U + (uint32_t)i); }
	putGroup(1, "Alfa", a, 3);
	putGroup(3, "Bravo", b, 1);
	putGroup(30, "Zulu", z, 2);
	setChannel(1, 3, true); setChannel(2, 1, true); setChannel(50, 3, true); setChannel(127, 30, true); setChannel(128, 3, true);
	setChannel(129, 3, true); setChannel(130, 1, true); setChannel(256, 3, true); setChannel(257, 0, true); setChannel(600, 3, true); setChannel(1024, 3, true);
	setChannel(3, 3, false); setChannel(700, 3, false);     /* НЕ в роботі */
	*vfoGrp(0) = 3; *vfoGrp(1) = 1;
	reinit();
}

static uint16_t mem(int slot, int i) { return (uint16_t)(bodyPtr(slot)[16 + 2 * i] | (bodyPtr(slot)[17 + 2 * i] << 8)); }

extern uint8_t codeplugRXGroupCache[];
/* інваріант живлення: кожен канал «в роботі» з ненульовим списком посилається на ІСНУЮЧИЙ список */
static bool noDanglingRefs(void)
{
	for (int i = 0; i < NUSED; i++)
	{
		int g = channelGrp(CH_USED[i]);
		if ((g != 0) && (*lenPtr(g) == 0)) { return false; }
	}
	return true;
}
/* кеш == таблиця довжин у флеші */
static bool cacheMatchesFlash(void)
{
	for (int s = 1; s <= 76; s++) { if (codeplugRXGroupCache[s - 1] != *lenPtr(s)) { return false; } }
	return true;
}
/* Режими для tools/test_r65b.py (сумісність з CPS у обидва боки): RXG_MODE=dump -- прошивка створює два списки й пише образ таблиці довжин + записів у файл RXG_FILE;
 * RXG_MODE=load -- читає такий образ (зібраний CPS-кодом) і друкує, що бачить прошивка (назва в hex, склад, СТОКОВИЙ codeplugRxGroupGetDataForIndex). */
static int modeDump(const char *file)
{
	static const uint16_t a[] = { 7, 8, 9 }, b[] = { 1, 2, 3, 4 };
	int sl = 0;
	FILE *f;

	world();
	if (codeplugRxGroupCreate("\xCA\xE8\xBF\xE2", a, 3, &sl) != CODEPLUG_RXGROUP_OK) { return 2; }
	if (codeplugRxGroupCreate("\xC7\xEE\xF0\xFF", b, 4, &sl) != CODEPLUG_RXGROUP_OK) { return 2; }   /* «Зоря» -- кінець 0xFF, хвіст 0x00 */
	f = fopen(file, "wb");
	if (f == NULL) { return 3; }
	fwrite(lenPtr(1), 1, 76, f);
	fwrite(bodyPtr(1), 1, 76 * RXREC, f);
	fclose(f);
	return 0;
}
static int modeLoad(const char *file)
{
	FILE *f;
	CodeplugRxGroup_t g;

	world();
	f = fopen(file, "rb");
	if (f == NULL) { return 3; }
	memset(lenPtr(1), 0, 76);
	if ((fread(lenPtr(1), 1, 76, f) != 76) || (fread(bodyPtr(1), 1, 76 * RXREC, f) != 76 * RXREC)) { fclose(f); return 4; }
	fclose(f);
	reinit();
	for (int s = 1; s <= 76; s++)
	{
		char nm[17]; uint16_t m[32]; int n;
		if (!codeplugRxGroupExists(s)) { continue; }
		codeplugRxGroupGetName(s, nm);
		n = codeplugRxGroupGetMembers(s, m);
		printf("SLOT %d NAME ", s);
		for (size_t i = 0; nm[i]; i++) { printf("%02X", (unsigned)(uint8_t)nm[i]); }
		printf(" MEM");
		for (int i = 0; i < n; i++) { printf(" %u", (unsigned)m[i]); }
		(void)codeplugRxGroupGetDataForIndex(s, &g);
		printf(" STOCK %d\n", g.NOT_IN_CODEPLUG_numTGsInGroup);
	}
	return 0;
}

int main(void)
{
	const char *mode = getenv("RXG_MODE"), *file = getenv("RXG_FILE");
	if ((mode != NULL) && (file != NULL)) { return (mode[0] == 'd') ? modeDump(file) : modeLoad(file); }
	printf("test_codeplug_rxgroup:\n");

	/* ---------- G1: розкладка ---------- */
	{
		int straddle = 0;
		for (int i = 0; i < 76; i++)
		{
			int lo = FLASH_ADDRESS_OFFSET + ADDR_RX + i * RXREC, hi = lo + RXREC - 1;
			if ((lo / 4096) != (hi / 4096)) { straddle++; }
		}
		CHECK(straddle == 0, "G1: жоден із 76 записів не перетинає межу 4 КБ сектора (перетинають: %d)", straddle);
		CHECK((FLASH_ADDRESS_OFFSET + ADDR_RX + 30 * RXREC) % 4096 == 0, "G1: запис №30 (з нуля) починається рівно з межі сектора");
		CHECK(((ADDR_RXLEN + 75) / 4096) == (ADDR_RX / 4096) && (ADDR_RXLEN / 4096) == ((ADDR_RX + 29 * RXREC) / 4096), "G1: таблиця довжин лежить у тому ж секторі, що й записи 0..29");
		CHECK(CODEPLUG_RXGROUP_DATA_STRUCT_SIZE == RXREC && CODEPLUG_RX_GROUPLIST_MAX == 76 && offsetof(CodeplugChannel_t, rxGroupList) == 43, "G1: сталі: запис 80, 76 списків, зсув O_GROUP 43 (є %d)", (int)offsetof(CodeplugChannel_t, rxGroupList));
		CHECK(CODEPLUG_ADDR_RX_GROUP == ADDR_RX && CODEPLUG_ADDR_RX_GROUP_LEN == ADDR_RXLEN && CODEPLUG_ADDR_VFO_A_CHANNEL == ADDR_VFO_A, "G1: адреси збігаються з прошивкою");
	}

	/* ---------- G2: читання ---------- */
	world();
	CHECK(codeplugRxGroupCount() == 3 && codeplugRxGroupNthSlot(0) == 1 && codeplugRxGroupNthSlot(1) == 3 && codeplugRxGroupNthSlot(2) == 30 && codeplugRxGroupNthSlot(3) == 0, "G2: існують слоти 1, 3, 30 (ординали 0,1,2)");
	CHECK(codeplugRxGroupExists(1) && !codeplugRxGroupExists(2) && !codeplugRxGroupExists(0) && !codeplugRxGroupExists(77) && !codeplugRxGroupExists(-1), "G2: exists: межі");
	{
		char nm[17]; uint16_t m[32];
		codeplugRxGroupGetName(3, nm);
		CHECK(strcmp(nm, "Bravo") == 0, "G2: назва слота 3 (є «%s»)", nm);
		codeplugRxGroupGetName(2, nm);
		CHECK(nm[0] == 0, "G2: назва вільного слота порожня");
		CHECK(codeplugRxGroupGetMembers(1, m) == 3 && m[0] == 1 && m[2] == 3 && m[3] == 0, "G2: склад слота 1 = 1,2,3");
		CHECK(codeplugRxGroupGetMembers(2, m) == 0, "G2: склад вільного слота = 0");
	}

	/* ---------- G3: створення ---------- */
	{
		static const uint16_t mm[] = { 7, 8, 9 };
		char nm[17]; uint16_t m[32]; int slot = 0;
		CodeplugRxGroup_t g;
		world(); snapshot();
		s_passes = 0; s_nwrites = 0;
		CHECK(codeplugRxGroupCreate("\xCA\xE8\xBF\xE2", mm, 3, &slot) == CODEPLUG_RXGROUP_OK && slot == 2, "G3: перший вільний слот = 2 (є %d)", slot);
		CHECK(s_nwrites == 2, "G3: рівно 2 записи: тіло, потім довжина (є %d)", s_nwrites);
		CHECK(s_passes == 2, "G3: слот 2 -> 2 проходи сектора (тіло + довжина; обидва в секторі 0x8D000) (є %d)", s_passes);
		CHECK(*lenPtr(2) == 3 && codeplugRXGroupCache[1] == 3 && cacheMatchesFlash(), "G3: довжина 3 у флеші й у кеші");
		CHECK(memcmp(bodyPtr(2), "\xCA\xE8\xBF\xE2\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF", 16) == 0, "G3: назва «Київ» у cp1251, хвіст 0xFF");
		CHECK(mem(2, 0) == 7 && mem(2, 1) == 8 && mem(2, 2) == 9 && mem(2, 3) == 0 && bodyPtr(2)[16 + 6] == 0 && bodyPtr(2)[79] == 0, "G3: uint16 LE номери 7,8,9, далі нулі до кінця запису");
		{
			range_t al[2] = { R_flash(ADDR_RX + 1 * RXREC, RXREC), R_flash(ADDR_RXLEN + 1, 1) };
			CHECK(strayChanges(al, 2) == 0, "G3: знімок-диф: змінилось лише тіло слота 2 і його байт довжини (сторонніх: %d)", strayChanges(al, 2));
		}
		CHECK(codeplugRxGroupGetDataForIndex(2, &g) && g.NOT_IN_CODEPLUG_numTGsInGroup == 3 && g.NOT_IN_CODEPLUG_contactsTG[0] == 1007U && g.NOT_IN_CODEPLUG_contactsTG[2] == 1009U && memcmp(g.name, "\xCA\xE8\xBF\xE2", 4) == 0, "G3: СТОКОВЕ читання codeplugRxGroupGetDataForIndex бачить список (3 TG: 1007..1009)");
		codeplugRxGroupGetName(2, nm);
		CHECK(strcmp(nm, "\xCA\xE8\xBF\xE2") == 0, "G3: назва читається назад");
		CHECK(codeplugRxGroupGetMembers(2, m) == 3, "G3: склад читається назад");

		/* слот 30 (початок сектора): запис закінчується не на межі, а ось слот 29 -- закінчується рівно на 0x8E000 */
		world();
		for (int s = 1; s <= 76; s++) { if (!codeplugRxGroupExists(s)) { char n2[8]; snprintf(n2, sizeof n2, "L%d", s); static const uint16_t one[] = { 1 }; int sl; if (codeplugRxGroupCreate(n2, one, 1, &sl) != CODEPLUG_RXGROUP_OK) { break; } } }
		CHECK(codeplugRxGroupCount() == 76, "G3: усі 76 слотів заповнюються (є %d)", codeplugRxGroupCount());
		{
			static const uint16_t one[] = { 1 }; int sl = 0;
			CHECK(codeplugRxGroupCreate("Extra", one, 1, &sl) == CODEPLUG_RXGROUP_FULL, "G3: 77-й список -> FULL");
		}
		/* вільний слот у середині заповнюється першим */
		world();
		{
			static const uint16_t one[] = { 1 }; int sl = 0;
			CHECK(codeplugRxGroupDelete(1) == CODEPLUG_RXGROUP_OK, "G3: підготовка: видалено слот 1");
			CHECK(codeplugRxGroupCreate("New", one, 1, &sl) == CODEPLUG_RXGROUP_OK && sl == 1, "G3: звільнений слот 1 використовується першим (є %d)", sl);
		}
	}

	/* ---------- G3b: проходи секторів на межі ---------- */
	{
		static const uint16_t mm[] = { 11, 12, 13 };
		world();
		CHECK((FLASH_ADDRESS_OFFSET + ADDR_RX + 30 * RXREC) % 4096 == 0, "G3b: запис слота 30 закінчується рівно на межі сектора -> SPI_Flash_write робить 2 проходи (другий даремний, той самий вміст)");
		snapshot();
		s_passes = 0;
		CHECK(codeplugRxGroupSetMembers(30, mm, 3) == CODEPLUG_RXGROUP_OK, "G3b: склад слота 30 змінено (2 -> 3 контакти)");
		CHECK(s_passes == 3, "G3b: слот 30 -> 3 проходи: склад (+ даремний другий) + довжина (є %d)", s_passes);
		{
			range_t al[2] = { R_flash(ADDR_RX + 29 * RXREC + 16, 64), R_flash(ADDR_RXLEN + 29, 1) };
			CHECK(strayChanges(al, 2) == 0, "G3b: попри даремний другий прохід, байти сусіднього сектора не змінились (сторонніх: %d)", strayChanges(al, 2));
		}
	}

	/* ---------- G4: правила назви ---------- */
	{
		static const uint16_t one[] = { 1 };
		int sl = 0;
		world();
		CHECK(codeplugRxGroupCreate("", one, 1, &sl) == CODEPLUG_RXGROUP_NAME_EMPTY, "G4: порожня назва -> NAME_EMPTY");
		CHECK(codeplugRxGroupCreate("   ", one, 1, &sl) == CODEPLUG_RXGROUP_NAME_EMPTY, "G4: самі пробіли -> NAME_EMPTY");
		CHECK(codeplugRxGroupCreate("Alfa", one, 1, &sl) == CODEPLUG_RXGROUP_NAME_DUP, "G4: назва існуючого списку -> NAME_DUP");
		CHECK(codeplugRxGroupCreate("alfa", one, 1, &sl) == CODEPLUG_RXGROUP_OK, "G4: інший регістр -- інша назва (як у CPS: порівняння точне)");
		{
			char n16[17]; memset(n16, 'A', 15); n16[15] = (char)0xFF; n16[16] = 0;
			CHECK(codeplugRxGroupNameCheck(n16, 0) == CODEPLUG_RXGROUP_NAME_TAIL, "G4: 16 байтів із кінцевим 0xFF («я») -> NAME_TAIL");
			memset(n16, 'B', 16); n16[16] = 0;
			CHECK(codeplugRxGroupNameCheck(n16, 0) == CODEPLUG_RXGROUP_OK, "G4: рівно 16 символів без «я» -- дозволено");
			memset(n16, 'C', 15); n16[15] = 'D'; n16[16] = 'E'; n16[17 - 1] = 'E';
		}
		{
			char z[8] = "Zor\xFF"; char out[17];
			CHECK(codeplugRxGroupCreate(z, one, 1, &sl) == CODEPLUG_RXGROUP_OK, "G4: «Зоря»-подібна назва (кінець 0xFF) створюється");
			codeplugRxGroupGetName(sl, out);
			CHECK(strcmp(out, z) == 0 && bodyPtr(sl)[4] == 0x00, "G4: ... хвіст 0x00, назва читається цілою (є «%s»), літера не втрачена", out);
		}
		CHECK(codeplugRxGroupNameCheck("Alfa", 1) == CODEPLUG_RXGROUP_OK, "G4: своя назва при перейменуванні -- не дублікат");
		CHECK(codeplugRxGroupNameCheck("Alfa", 3) == CODEPLUG_RXGROUP_NAME_DUP, "G4: назва іншого списку при перейменуванні -- дублікат");
	}

	/* ---------- G5: склад при створенні ---------- */
	{
		uint16_t big[40]; int sl = 0;
		world();
		for (int i = 0; i < 40; i++) { big[i] = (uint16_t)(i + 1); }
		snapshot();
		CHECK(codeplugRxGroupCreate("X", big, 0, &sl) == CODEPLUG_RXGROUP_BAD_ARG, "G5: порожній склад (0) -> BAD_ARG: список без контактів не існує");
		CHECK(codeplugRxGroupCreate("X", big, 33, &sl) == CODEPLUG_RXGROUP_BAD_ARG, "G5: 33 контакти -> BAD_ARG");
		CHECK(codeplugRxGroupCreate("X", big, 32, &sl) == CODEPLUG_RXGROUP_OK, "G5: рівно 32 -- дозволено");
		CHECK(*lenPtr(sl) == 32 && mem(sl, 31) == 32, "G5: довжина 32, останній контакт на місці");
		restore(); snapshot();
		big[1] = big[0];
		CHECK(codeplugRxGroupCreate("X", big, 3, &sl) == CODEPLUG_RXGROUP_DUP_MEMBER, "G5: дубль контакту -> DUP_MEMBER");
		big[1] = 0;
		CHECK(codeplugRxGroupCreate("X", big, 3, &sl) == CODEPLUG_RXGROUP_BAD_ARG, "G5: контакт 0 -> BAD_ARG");
		big[1] = 1025;
		CHECK(codeplugRxGroupCreate("X", big, 3, &sl) == CODEPLUG_RXGROUP_BAD_ARG, "G5: контакт 1025 -> BAD_ARG");
		{ range_t none[1] = { R_flash(0, 0) }; CHECK(strayChanges(none, 1) == 0 && s_nwrites == 0, "G5: жодна відмова нічого не записала (записів: %d)", s_nwrites); }
	}

	/* ---------- G6: перейменування ---------- */
	{
		world(); snapshot();
		s_nwrites = 0; s_passes = 0;
		CHECK(codeplugRxGroupRename(3, "Charlie") == CODEPLUG_RXGROUP_OK, "G6: перейменовано слот 3");
		{
			range_t al[1] = { R_flash(ADDR_RX + 2 * RXREC, 16) };
			CHECK(strayChanges(al, 1) == 0, "G6: змінились ЛИШЕ 16 байтів назви (сторонніх: %d)", strayChanges(al, 1));
		}
		CHECK(s_nwrites == 1 && s_passes == 1, "G6: один запис, один прохід сектора (записів %d, проходів %d)", s_nwrites, s_passes);
		{ char nm[17]; codeplugRxGroupGetName(3, nm); CHECK(strcmp(nm, "Charlie") == 0 && *lenPtr(3) == 1 && mem(3, 0) == 4, "G6: назва нова, довжина й склад не чіпано"); }
		restore(); snapshot();
		CHECK(codeplugRxGroupRename(3, "Alfa") == CODEPLUG_RXGROUP_NAME_DUP, "G6: на назву іншого списку -> NAME_DUP");
		CHECK(codeplugRxGroupRename(3, "") == CODEPLUG_RXGROUP_NAME_EMPTY, "G6: порожня -> NAME_EMPTY");
		CHECK(codeplugRxGroupRename(2, "Q") == CODEPLUG_RXGROUP_BAD_ARG, "G6: вільний слот -> BAD_ARG");
		CHECK(codeplugRxGroupRename(0, "Q") == CODEPLUG_RXGROUP_BAD_ARG && codeplugRxGroupRename(77, "Q") == CODEPLUG_RXGROUP_BAD_ARG, "G6: слот 0 і 77 -> BAD_ARG");
		{ range_t none[1] = { R_flash(0, 0) }; CHECK(strayChanges(none, 1) == 0 && s_nwrites == 0, "G6: відмови нічого не записали"); }
		CHECK(codeplugRxGroupRename(1, "Alfa") == CODEPLUG_RXGROUP_OK, "G6: своя назва -- ок");
	}

	/* ---------- G7: склад ---------- */
	{
		static const uint16_t g1[] = { 20, 21, 22, 23, 24 }, g2[] = { 3 }, dup[] = { 3, 3 };
		world(); snapshot();
		s_nwrites = 0;
		CHECK(codeplugRxGroupSetMembers(1, g1, 5) == CODEPLUG_RXGROUP_OK, "G7: склад слота 1 -> 5 контактів");
		{
			range_t al[2] = { R_flash(ADDR_RX + 16, 64), R_flash(ADDR_RXLEN, 1) };
			CHECK(strayChanges(al, 2) == 0, "G7: змінились лише 64 байти складу й байт довжини (сторонніх: %d)", strayChanges(al, 2));
		}
		CHECK(s_nwrites == 2 && *lenPtr(1) == 5 && cacheMatchesFlash() && memcmp(bodyPtr(1), "Alfa", 4) == 0, "G7: 2 записи (склад, довжина); назва ціла");
		{ uint16_t m[32]; CHECK(codeplugRxGroupGetMembers(1, m) == 5 && m[4] == 24, "G7: склад читається"); }
		s_nwrites = 0;
		CHECK(codeplugRxGroupSetMembers(1, g1, 5) == CODEPLUG_RXGROUP_OK && s_nwrites == 1, "G7: та сама довжина -> один запис (довжину не переписуємо) (записів %d)", s_nwrites);
		CHECK(codeplugRxGroupSetMembers(1, g2, 1) == CODEPLUG_RXGROUP_OK && *lenPtr(1) == 1 && mem(1, 1) == 0 && mem(1, 4) == 0, "G7: усічення до 1: хвіст склада обнулено");
		restore(); snapshot(); s_nwrites = 0;
		CHECK(codeplugRxGroupSetMembers(1, dup, 2) == CODEPLUG_RXGROUP_DUP_MEMBER, "G7: дубль -> DUP_MEMBER");
		CHECK(codeplugRxGroupSetMembers(1, g2, 0) == CODEPLUG_RXGROUP_BAD_ARG, "G7: 0 контактів -> BAD_ARG (щоб прибрати список, є «Видалити»)");
		CHECK(codeplugRxGroupSetMembers(2, g2, 1) == CODEPLUG_RXGROUP_BAD_ARG, "G7: вільний слот -> BAD_ARG");
		{ range_t none[1] = { R_flash(0, 0) }; CHECK(strayChanges(none, 1) == 0 && s_nwrites == 0, "G7: відмови нічого не записали"); }
	}

	/* ---------- G8: видалення з каскадом ---------- */
	{
		int refs[] = { 1, 50, 128, 129, 256, 600, 1024 };   /* канали зі списком 3 у роботі */
		range_t al[16]; int na = 0;
		world();
		CHECK(codeplugRxGroupCountChannels(3) == 7, "G8: лічильник: список 3 -> 7 каналів (канали 3 і 700 поза маскою не рахуються) (є %d)", codeplugRxGroupCountChannels(3));
		CHECK(codeplugRxGroupCountChannels(1) == 2 && codeplugRxGroupCountChannels(30) == 1 && codeplugRxGroupCountChannels(2) == 0 && codeplugRxGroupCountChannels(0) == 0 && codeplugRxGroupCountChannels(77) == 0, "G8: лічильник інших списків і меж");
		for (int i = 0; i < 7; i++) { al[na++] = R_chField(refs[i]); }
		al[na++] = R_flash(ADDR_RXLEN + 2, 1);
		al[na++] = R_flash(ADDR_RX + 2 * RXREC, RXREC);
		{ range_t v; v.flash = false; v.lo = ADDR_VFO_A + (int)offsetof(CodeplugChannel_t, rxGroupList); v.hi = v.lo + 1; al[na++] = v; }
		snapshot();
		CHECK(codeplugRxGroupDelete(3) == CODEPLUG_RXGROUP_OK, "G8: видалено список 3");
		CHECK(strayChanges(al, na) == 0, "G8: знімок-диф EEPROM+флешу: змінились лише поля списку в 7 каналах, VFO A, байт довжини й тіло слота (сторонніх: %d)", strayChanges(al, na));
		{
			int bad = 0;
			for (int i = 0; i < 7; i++) { if (channelGrp(refs[i]) != 0) { bad++; } }
			CHECK(bad == 0, "G8: усі 7 каналів зі списком 3 -> 0 («Немає»)");
		}
		CHECK(channelGrp(3) == 3 && channelGrp(700) == 3, "G8: канали поза маскою не чіпано");
		CHECK(channelGrp(2) == 1 && channelGrp(127) == 30 && channelGrp(130) == 1 && channelGrp(257) == 0, "G8: канали з іншими списками цілі");
		CHECK(*vfoGrp(0) == 0 && *vfoGrp(1) == 1, "G8: VFO A (було 3) -> 0, VFO B (було 1) цілий");
		CHECK(*lenPtr(3) == 0 && codeplugRXGroupCache[2] == 0 && !codeplugRxGroupExists(3) && cacheMatchesFlash(), "G8: довжина 0, кеш 0");
		{ int z = 0; for (int i = 0; i < RXREC; i++) { z |= bodyPtr(3)[i]; } CHECK(z == 0, "G8: тіло слота обнулено"); }
		CHECK(codeplugRxGroupExists(1) && codeplugRxGroupExists(30) && memcmp(bodyPtr(1), "Alfa", 4) == 0, "G8: інші списки цілі");
		{
			int bad = 0;
			for (int i = 0; i < NUSED; i++) { int ch = CH_USED[i]; if (!((memcmp(recPtr(ch), "CH", 2) == 0) && (recPtr(ch)[REC - 1] == (uint8_t)(0x40 + (ch % 100))))) { bad++; } }
			CHECK(bad == 0, "G8: решта байтів записів каналів цілі");
		}
		CHECK(codeplugRxGroupDelete(3) == CODEPLUG_RXGROUP_BAD_ARG && codeplugRxGroupDelete(0) == CODEPLUG_RXGROUP_BAD_ARG && codeplugRxGroupDelete(77) == CODEPLUG_RXGROUP_BAD_ARG, "G8: повторне/недійсне видалення -> BAD_ARG");
	}

	/* ---------- G9: збій запису ---------- */
	{
		world(); snapshot();
		s_failFlashLo = FLASH_ADDRESS_OFFSET + ADDR_CH_FLASH; s_failFlashHi = s_failFlashLo + 8 * 1024;    /* банк каналів у флеші недоступний */
		CHECK(codeplugRxGroupDelete(3) == CODEPLUG_RXGROUP_WRITE_ERROR, "G9: збій запису в каналі -> WRITE_ERROR");
		CHECK(codeplugRxGroupExists(3) && *lenPtr(3) == 1 && memcmp(bodyPtr(3), "Bravo", 5) == 0, "G9: список ЦІЛИЙ (каскад іде першим)");
		CHECK(noDanglingRefs(), "G9: жоден канал не посилається на неіснуючий список");
		restore(); s_failFlashLo = s_failFlashHi = -1;
		CHECK(codeplugRxGroupDelete(3) == CODEPLUG_RXGROUP_OK, "G9: після зняття збою видалення завершується");
	}

	/* ---------- G9b: збій запису САМОЇ довжини -- кеш мусить лишитись правдою ---------- */
	{
		world(); snapshot();
		s_failFlashLo = FLASH_ADDRESS_OFFSET + ADDR_RXLEN + 29; s_failFlashHi = s_failFlashLo + 1;
		CHECK(codeplugRxGroupDelete(30) == CODEPLUG_RXGROUP_WRITE_ERROR, "G9b: збій запису байта довжини -> WRITE_ERROR");
		CHECK(codeplugRxGroupExists(30) && *lenPtr(30) == 2 && cacheMatchesFlash(), "G9b: список 30 лишився, кеш == флеш (довжина 2)");
		s_failFlashLo = s_failFlashHi = -1;
	}

	/* ---------- G10: обрив живлення в КОЖНІЙ точці ---------- */
	{
		static const uint16_t mm[] = { 7, 8, 9 }, g1[] = { 20, 21, 22, 23, 24 };
		int nWrites;
		world(); snapshot();
		s_budget = -1; s_nwrites = 0;
		(void)codeplugRxGroupDelete(3);
		nWrites = s_nwrites;
		CHECK(nWrites >= 9, "G10: видалення списку 3 = %d записів (7 каналів + VFO + довжина + тіло)", nWrites);
		for (int k = 0; k <= nWrites; k++)
		{
			restore(); s_budget = k;
			(void)codeplugRxGroupDelete(3);
			s_budget = -1;
			reinit();
			if (!(noDanglingRefs() && cacheMatchesFlash() && (codeplugRxGroupExists(3) ? (memcmp(bodyPtr(3), "Bravo", 5) == 0 && mem(3, 0) == 4) : true)))
			{
				CHECK(false, "G10: видалення, обрив після %d записів: dangling=%d кеш=%d", k, !noDanglingRefs(), !cacheMatchesFlash());
				break;
			}
			if (k == nWrites) { CHECK(true, "G10: видалення -- обрив після КОЖНОГО з %d записів: нема посилань на неіснуючий список, кеш == флеш, живий список цілий", nWrites + 1); }
		}
		restore(); s_budget = -1; s_nwrites = 0;
		{ int sl; (void)codeplugRxGroupCreate("New", mm, 3, &sl); }
		nWrites = s_nwrites;
		for (int k = 0; k <= nWrites; k++)
		{
			restore(); s_budget = k;
			{ int sl = 0; (void)codeplugRxGroupCreate("New", mm, 3, &sl); }
			s_budget = -1; reinit();
			{
				bool ex = codeplugRxGroupExists(2);
				bool full = ex && (memcmp(bodyPtr(2), "New\xFF", 4) == 0) && mem(2, 0) == 7 && mem(2, 2) == 9 && *lenPtr(2) == 3;
				if (!(cacheMatchesFlash() && (!ex || full)))
				{
					CHECK(false, "G10: створення, обрив після %d записів: список існує, але тіло неповне", k);
					break;
				}
			}
			if (k == nWrites) { CHECK(true, "G10: створення -- обрив після КОЖНОГО з %d записів: список або не існує, або існує ПОВНІСТЮ", nWrites + 1); }
		}
		restore(); s_budget = -1; s_nwrites = 0;
		(void)codeplugRxGroupSetMembers(1, g1, 5);
		nWrites = s_nwrites;
		for (int k = 0; k <= nWrites; k++)
		{
			restore(); s_budget = k;
			(void)codeplugRxGroupSetMembers(1, g1, 5);
			s_budget = -1; reinit();
			{
				bool ok = codeplugRxGroupExists(1) && (memcmp(bodyPtr(1), "Alfa", 4) == 0) && cacheMatchesFlash() && (mem(1, 0) == 1 || mem(1, 0) == 20);
				if (!ok) { CHECK(false, "G10: склад, обрив після %d записів: список зіпсовано", k); break; }
			}
			if (k == nWrites) { CHECK(true, "G10: склад -- обрив після КОЖНОГО з %d записів: список існує, назва ціла, склад старий або новий", nWrites + 1); }
		}
	}

	printf("%s (%d)\n", fails ? "ПРОВАЛ" : "усе гаразд", fails);
	return fails ? 1 : 0;
}
