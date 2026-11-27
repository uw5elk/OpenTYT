/*
 * test_dmr_sms_flash.c -- R106-SMSSTORE: сховище SMS DMR у власному кільці секторів SPI-флешу (ENABLE_SMS_STORE_FLASH).
 * Лінкує СПРАВЖНІ functions/dmr_sms.c і functions/sms_flash_store.c; SPI-флеш -- модель NOR (стирання -> 0xFF, програмування 1 -> 0),
 * custom-data блок 7 -- окремий образ; прийом -- справжній шлях dmrSmsRxBurst/dmrSmsRxTick на записі BBD_0004 (CONFIRMED, нам -> квитанція).
 * «Перезапуск» = dmrSmsRuntimeInit() + dmrSmsInit() (як applicationMain.c). Головний цикл = dmrSmsRxTick() + dmrSmsStoreTick() раз на 1 мс.
 *
 *  1  міграція (рішення 2, «б»): блок 7 з SMS (v3, v2, «MSGS») -> переписаний порожнім образом тієї самої довжини, SMS НЕ перенесено, кільце
 *     не чіпалось; повторний старт -- блок 7 більше не пишеться; блока 7 нема -- не створюється
 *  2  нове SMS -> рівно один запис у кільце, ПІСЛЯ квитанції й не раніше ніж через 2 с тиші після останнього burst-а; перезапуск -- воно є
 *  3  «прочитано» -> запис через 60 с (не раніше), перезапуск -- прочитане; без змін -- 0 операцій флешу за 10 хв
 *  4  кілька змін за 60 с -> один запис; відлік від ПЕРШОЇ зміни
 *  5  вхід у меню (dmrSmsReloadStore) не скасовує ще не записане «прочитано»
 *  6  передача / режим CPS відкладають запис; після -- записується
 *  7  вимкнення (dmrSmsStoreFlush) одразу після прийому (квитанція ще не пішла) і з незаписаним «прочитано» -- усе в кільці
 *  8  20 SMS -> кільце по колу (кожен слот 2-3 стирання), останні 20 після перезапуску, custom-data за весь час не писалась
 */
#include <stdio.h>
#include <string.h>
#include "functions/dmr_sms.h"
#include "functions/dmr_sms_pdu.h"
#include "functions/dmr_data.h"
#include "functions/settings.h"
#include "functions/codeplug.h"
#include "functions/trx.h"
#include "functions/sound.h"
#include "functions/ticks.h"
#include "functions/sms_flash_store.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiGlobals.h"
#include "crypto/dmr_aes.h"
#include "crypto/dmr_aes_hook.h"

#if !defined(SMS_STORE_FLASH)
#error "test_dmr_sms_flash: потрібні -DENABLE_SMS_STORE_FLASH -DENABLE_AES -DENABLE_DMR_DATA"
#endif

/* ============================ заглушки заліза ============================ */
static uint32_t s_now = 1000;
uint32_t ticksGetMillis(void) { return s_now; }
uint32_t trxDMRID = 0x26EA0F;
uint32_t trxTalkGroupOrPcId = 9;
volatile bool trxIsTransmitting = false;
volatile bool trxTransmissionEnabled = false;
static int s_menu = 0;
int menuSystemGetCurrentMenuNumber(void) { return s_menu; }
static CodeplugChannel_t s_chan;
CodeplugChannel_t *currentChannelData = &s_chan;
CodeplugRxGroup_t currentRxGroupData;
const int16_t MELODY_ACK_BEEP[1] = { 0 };
const int16_t MELODY_SMS_RECEIVED_BEEP[1] = { 0 };
bool settingsIsOptionBitSet(bitfieldOptions_t bit) { (void)bit; return false; }
uint8_t codeplugChannelGetFlag(CodeplugChannel_t *c, ChannelFlag_t f) { (void)c; (void)f; return 0; }
void displayLightTrigger(bool k) { (void)k; }
void uiNotificationShow(uiNotificationType_t t, uiNotificationID_t i, uint32_t ms, const char *m, bool r)
{ (void)t; (void)i; (void)ms; (void)m; (void)r; }
void soundSetMelody(const int16_t *m) { (void)m; }
int dmrAesEnsureCustomDataRegion(void) { return 1; }
void dmrAesLoadKeys(void) { }
uint8_t dmrAesTxKeyId(void) { return 0; }
static time_t_custom s_rtc = 1791235800U;
time_t_custom getRtcTime_custom(void) { return s_rtc; }

/* ---- custom-data: блок 7 (MESSAGES) ---- */
#define BLK_SIZE 1352
static uint8_t s_blk7[BLK_SIZE];
static int     s_blk7Valid;
static int     s_cdWrites;            /* будь-який запис custom-data */
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *b, int m)
{
	if ((t == CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES) && s_blk7Valid) { memcpy(b, s_blk7, (size_t)((m < BLK_SIZE) ? m : BLK_SIZE)); return true; }
	return false;
}
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *b, int l)
{
	s_cdWrites++;
	if (t == CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES)
	{
		if (!s_blk7Valid || (l != BLK_SIZE)) { return false; }   /* блок не створюємо й довжину не міняємо -- як codeplug.c для чужої довжини */
		memcpy(s_blk7, b, (size_t)l);
	}
	return true;
}

/* ---- data-TX: квитанція ---- */
static int      s_txLoads;
static uint32_t s_txLoadMs;
#define TX_BUSY_MS 150
static int txWindow(uint32_t from) { return (s_txLoads > 0) && ((s_now - s_txLoadMs) >= from) && ((s_now - s_txLoadMs) < TX_BUSY_MS); }
int  dmrDataTxActive(void) { return txWindow(15); }
int  dmrDataTxBusy(void)   { return txWindow(0); }
void dmrDataTxDiag(uint16_t out[4]) { memset(out, 0, 4 * sizeof out[0]); }
void dmrDataTxDiagReset(void) { }
uint32_t dmrDataTxLastKeyMs(void) { return 0; }
uint32_t dmrDataTxLastSlotStartMs(void) { return 0; }
uint32_t dmrDataTxLastStartMs(void) { return ((s_txLoads > 0) && ((s_now - s_txLoadMs) >= 20)) ? (s_txLoadMs + 20) : 0; }
void dmrDataTxLoad(const uint8_t *b, uint8_t n) { (void)b; (void)n; }
void dmrDataTxLoadFast(const uint8_t *b, uint8_t n) { (void)b; (void)n; }
int  dmrDataTxLoadDelayedEx(const uint8_t *b, uint8_t n, uint16_t d, int f) { (void)b; (void)n; (void)d; (void)f; s_txLoads++; s_txLoadMs = s_now; return 1; }

/* ---- SPI-флеш: модель NOR на ділянці кільця ---- */
#define FL_BASE 0x40000UL
#define FL_SIZE 0x10000UL
static uint8_t  s_fl[FL_SIZE];
static int      s_erases, s_progs, s_outside;
static long     s_slotErases[SMSF_SLOTS];
static uint32_t s_lastBurst;          /* коли тест востаннє подав burst */
static int      s_badErase;           /* стирання, коли не можна: квитанція/передача/тиша < 2 с/CPS */
static uint32_t s_lastEraseMs;
bool SPI_Flash_read(uint32_t a, uint8_t *buf, int n)
{
	for (int i = 0; i < n; i++) { buf[i] = ((a + i >= FL_BASE) && (a + i < FL_BASE + FL_SIZE)) ? s_fl[a + i - FL_BASE] : 0xFF; }
	return true;
}
bool SPI_Flash_eraseSector(uint32_t a)
{
	if ((a % 4096U) || (a < SMSF_REGION_ADDR) || (a >= SMSF_REGION_ADDR + SMSF_SLOTS * 4096U)) { s_outside++; return false; }
	if (dmrDataTxBusy() || trxTransmissionEnabled || trxIsTransmitting || ((s_now - s_lastBurst) < SMSF_QUIET_MS) || (s_menu == UI_CPS))
	{
		s_badErase++;
		printf("  (стирання в недозволений час: t=%u, від burst %u мс, busy=%d, tx=%d/%d, меню=%d)\n", (unsigned)s_now, (unsigned)(s_now - s_lastBurst),
				dmrDataTxBusy(), (int)trxTransmissionEnabled, (int)trxIsTransmitting, s_menu);
	}
	memset(&s_fl[a - FL_BASE], 0xFF, 4096);
	s_erases++; s_slotErases[(a - SMSF_REGION_ADDR) / 4096U]++; s_lastEraseMs = s_now;
	return true;
}
bool SPI_Flash_programBytes(uint32_t a, const uint8_t *buf, int n)
{
	if ((n <= 0) || ((a & 0xFFU) + (uint32_t)n > 256U) || (a < SMSF_REGION_ADDR) || (a + (uint32_t)n > SMSF_REGION_ADDR + SMSF_SLOTS * 4096U)) { s_outside++; return false; }
	for (int i = 0; i < n; i++) { s_fl[a - FL_BASE + i] &= buf[i]; }
	s_progs++;
	return true;
}

/* ============================ запис BBD_0004 ============================= */
static const uint8_t HDR[12] = { 0x43,0x4c,0x26,0xea,0x0f,0x26,0xea,0x29,0x84,0x08,0xa8,0x51 };
static const uint8_t BLK[4][18] = {
	{ 0x01,0xee,0x45,0x00,0x00,0x30,0x00,0x00,0x00,0x00,0x40,0x11,0x8e,0x38,0x0c,0x26,0xea,0x29 },
	{ 0x02,0x3a,0x0c,0x26,0xea,0x0f,0x0f,0xa7,0x0f,0xa7,0x00,0x1c,0x6f,0xc9,0x00,0x12,0xe0,0x00 },
	{ 0x05,0x7a,0x99,0x04,0x0d,0x00,0x0a,0x00,0x48,0x00,0x65,0x00,0x6c,0x00,0x6c,0x00,0x6f,0x00 },
	{ 0x07,0xb2,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xec,0xfc,0x3c,0xeb },
};
#define SLOT_MS 60

static void mainLoopFor(uint32_t ms)
{
	for (uint32_t t = 0; t < ms; t++) { s_now++; dmrSmsRxTick(); dmrSmsStoreTick(); }
}
static void burst(int type, const uint8_t *b)
{
	s_lastBurst = s_now;
	dmrSmsRxDiagBurst(type, 1);
	if (b) { dmrSmsRxBurst(type, b); }
}
/* Одна передача стокової: 14 CSBK-преамбул, заголовок, 4 блоки rate-3/4, термінатор. */
static void attempt(void)
{
	for (int i = 0; i < 14; i++) { burst(3, NULL); mainLoopFor(SLOT_MS); }
	s_lastBurst = s_now;
	dmrSmsRxDiagBurst(6, 1);
	if (dmrSmsRxHdrAccept(1, HDR)) { dmrSmsRxBurst(6, HDR); }
	mainLoopFor(SLOT_MS);
	for (int b = 0; b < 4; b++) { burst(8, BLK[b]); mainLoopFor(SLOT_MS); }
	dmrSmsRxReset();   /* термінатор: у SMS-збирач не йде (s_lastRxBurstMs не оновлюється) */
	mainLoopFor(SLOT_MS);
}
static void reboot(void) { dmrSmsRuntimeInit(); dmrSmsInit(); }
static void freshRadio(void)
{
	memset(s_fl, 0xFF, sizeof s_fl); s_erases = s_progs = s_outside = 0; memset(s_slotErases, 0, sizeof s_slotErases);
	s_blk7Valid = 0; s_cdWrites = 0; s_txLoads = 0; s_badErase = 0; s_menu = 0; trxTransmissionEnabled = false;
	reboot();
}

static int fails = 0, checks = 0;
#define CHECK(c, ...) do { checks++; if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* блок 7 з двома SMS (v3) */
static void blk7WithSms(int version, const char *magic)
{
	memset(s_blk7, 0, sizeof s_blk7);
	memcpy(s_blk7, magic, 4); s_blk7[4] = (uint8_t)version;
	int hdr = (version == 2) ? 8 : 12, used = 0;
	const char *t[2] = { "Old one", "Old two" };
	for (int k = 0; k < 2; k++)
	{
		uint8_t *d = s_blk7 + 10 + used;
		d[0] = 0x01 | 0x02; d[1] = 7; d[2] = (uint8_t)(k + 1); d[4] = 0x0f; d[5] = 0xea; d[6] = 0x26;
		memcpy(d + hdr, t[k], 7); used += hdr + 7;
	}
	s_blk7[6] = (uint8_t)used; s_blk7[8] = 3;
	s_blk7Valid = 1;
}
static int blk7IsBlank(void)
{
	static const uint8_t head[10] = { 'M','S','G','V', 3, 0, 0, 0, 1, 0 };
	if (memcmp(s_blk7, head, 10) != 0) { return 0; }
	for (int i = 10; i < BLK_SIZE; i++) { if (s_blk7[i]) { return 0; } }
	return 1;
}

int main(void)
{
	printf("test_dmr_sms_flash:\n");

	/* 1. міграція «б» */
	{
		static const char *mg[3] = { "MSGV", "MSGV", "MSGS" };
		static const int ver[3] = { 3, 2, 1 };
		for (int v = 0; v < 3; v++)
		{
			memset(s_fl, 0xFF, sizeof s_fl); s_erases = s_progs = 0; s_cdWrites = 0;
			blk7WithSms(ver[v], mg[v]);
			reboot();
			CHECK(s_cdWrites == 1 && blk7IsBlank(), "1: блок 7 (%s v%d) з SMS -> переписаний порожнім образом 1352 Б (записів %d)", mg[v], ver[v], s_cdWrites);
			CHECK(dmrSmsCount(0) == 0 && dmrSmsCount(1) == 0, "1: старі SMS не перенесено (рішення «б»)");
			CHECK(s_erases == 0 && s_progs == 0, "1: кільце не чіпалось (стирань %d, програмувань %d)", s_erases, s_progs);
			reboot();
			CHECK(s_cdWrites == 1, "1: повторний старт -- блок 7 більше не пишеться");
		}
		freshRadio();
		CHECK(s_cdWrites == 0 && !s_blk7Valid && dmrSmsCount(0) == 0, "1: блока 7 нема -- не створюється, сховище порожнє");
	}

	/* 2. нове SMS -> один запис після квитанції й тиші */
	freshRadio();
	attempt();
	uint32_t endRx = s_lastBurst;
	CHECK(dmrSmsCount(0) == 0 && dmrSmsUnreadCount() == 1, "2: прийнято; поки квитанція винна -- вхідне відкладене (у сховищі ще нема)");
	mainLoopFor(1500);
	CHECK(s_txLoads == 1 && dmrSmsCount(0) == 1, "2: квитанція пішла (%d), вхідне в сховищі", s_txLoads);
	CHECK(s_erases == 0, "2: запису у флеш ще нема (тиша < 2 с)");
	mainLoopFor(2000);
	CHECK(s_erases == 1, "2: рівно один запис у кільце (%d)", s_erases);
	CHECK(s_badErase == 0 && (s_lastEraseMs - endRx) >= SMSF_QUIET_MS, "2: стирання не в квитанції/передачі і через %u мс тиші (погані %d)", (unsigned)(s_lastEraseMs - endRx), s_badErase);
	mainLoopFor(120000);
	CHECK(s_erases == 1, "2: далі без змін -- без записів");
	reboot();
	CHECK(dmrSmsCount(0) == 1 && dmrSmsUnreadCount() == 1, "2: перезапуск -- SMS на місці, непрочитане");
	CHECK(dmrSmsGet(0, 0) && strcmp(dmrSmsGet(0, 0)->text, "Hello") == 0, "2: текст «%s»", dmrSmsGet(0, 0) ? dmrSmsGet(0, 0)->text : "?");

	/* 3. «прочитано» -- через 60 с; без змін -- 0 операцій */
	{
		int e0 = s_erases;
		dmrSmsMarkRead(0, 0);
		mainLoopFor(58000);
		CHECK(s_erases == e0, "3: «прочитано» -- за 58 с запису нема");
		mainLoopFor(3000);
		CHECK(s_erases == e0 + 1, "3: через ~60 с -- один запис (%d)", s_erases - e0);
		reboot();
		CHECK(dmrSmsUnreadCount() == 0 && dmrSmsCount(0) == 1, "3: перезапуск -- прочитане");
		int p0 = s_progs; e0 = s_erases;
		mainLoopFor(600000);
		CHECK(s_erases == e0 && s_progs == p0, "3: 10 хв без змін -- 0 операцій флешу");
	}

	/* 4. кілька змін за 60 с -- один запис, відлік від першої */
	{
		attempt(); mainLoopFor(31000);   /* > 30 с між однаковими PDU -- інакше дублікат (Task #34) */
		attempt(); mainLoopFor(31000);
		CHECK(dmrSmsCount(0) == 3 && dmrSmsUnreadCount() == 2, "4: ще два вхідні");
		int e0 = s_erases;
		uint32_t tFirst = s_now; (void)tFirst;
		dmrSmsMarkRead(0, 0);
		mainLoopFor(40000);
		dmrSmsMarkRead(0, 1);
		mainLoopFor(15000);
		dmrSmsDelete(0, 2);
		mainLoopFor(4000);
		CHECK(s_erases == e0, "4: за 59 с після першої зміни -- ще нема (записів %d, останній через %d мс)", s_erases - e0, (int)(s_lastEraseMs - tFirst));
		mainLoopFor(3000);
		CHECK(s_erases == e0 + 1, "4: три зміни -> один запис через ~60 с від ПЕРШОЇ (%d)", s_erases - e0);
		mainLoopFor(120000);
		CHECK(s_erases == e0 + 1, "4: далі -- без записів");
		reboot();
		CHECK(dmrSmsCount(0) == 2 && dmrSmsUnreadCount() == 0, "4: перезапуск -- 2 вхідні, усі прочитані");
	}

	/* 5. вхід у меню не скасовує незаписане «прочитано» */
	{
		attempt(); mainLoopFor(5000);
		CHECK(dmrSmsUnreadCount() == 1, "5: нове непрочитане");
		dmrSmsMarkAllRead();
		dmrSmsReloadStore();   /* menuMessages: вхід у меню */
		CHECK(dmrSmsUnreadCount() == 0, "5: після входу в меню -- прочитане лишилось прочитаним");
		mainLoopFor(62000);
		reboot();
		CHECK(dmrSmsUnreadCount() == 0 && dmrSmsCount(0) == 3, "5: записалось -- після перезапуску прочитане");
	}

	/* 6. передача / CPS відкладають */
	{
		int e0 = s_erases;
		dmrSmsDelete(0, 0);
		trxTransmissionEnabled = true;
		mainLoopFor(120000);
		CHECK(s_erases == e0, "6: поки передача -- запису нема");
		trxTransmissionEnabled = false;
		mainLoopFor(10);
		CHECK(s_erases == e0 + 1, "6: передача скінчилась -- записано");
		dmrSmsDelete(0, 0);
		s_menu = UI_CPS;
		mainLoopFor(120000);
		CHECK(s_erases == e0 + 1, "6: режим CPS -- запису нема");
		s_menu = 0;
		mainLoopFor(10);
		CHECK(s_erases == e0 + 2 && s_badErase == 0, "6: вийшли з CPS -- записано; поганих стирань %d", s_badErase);
		reboot();
		CHECK(dmrSmsCount(0) == 1, "6: перезапуск -- лишилось одне вхідне");
	}

	/* 7. вимкнення: одразу після прийому (квитанція ще не пішла -- вхідне відкладене) і з незаписаним «прочитано» */
	{
		attempt();
		int e0 = s_erases;
		CHECK(dmrSmsCount(0) == 1 && dmrSmsUnreadCount() == 1, "7: нове вхідне ще відкладене (квитанція винна)");
		int bad0 = s_badErase;
		dmrSmsStoreFlush();   /* вимкнення пише одразу, без гейтів (квитанція тут неважлива) */
		s_badErase = bad0;
		CHECK(s_erases == e0 + 1, "7: дозапис при вимкненні -- один запис (%d)", s_erases - e0);
		reboot();
		CHECK(dmrSmsCount(0) == 2 && dmrSmsUnreadCount() == 1, "7: після «вимкнення» -- відкладене вхідне збережено");
		mainLoopFor(5000);
		dmrSmsMarkAllRead();
		dmrSmsStoreFlush();
		reboot();
		CHECK(dmrSmsUnreadCount() == 0, "7: незаписане «прочитано» -- дописано при вимкненні");
		e0 = s_erases;
		dmrSmsStoreFlush();
		CHECK(s_erases == e0, "7: вимкнення без змін -- без запису");
	}

	/* 7b. R108-FLUSHFIX: перезавантаження з CPS ('C' 6 0/6 1) викликає dmrSmsStoreFlush() у режимі CPS (UI_CPS): відкладене вхідне має потрапити у
	 * кільце, хоч звичайний тік у CPS мовчить (крок 6). Гейту «не UI_CPS» у Flush нема. */
	{
		attempt();
		int e0 = s_erases;
		int bad0 = s_badErase;
		CHECK(dmrSmsCount(0) == 2 && dmrSmsUnreadCount() == 1, "7b: нове вхідне ще відкладене (у списку %d, непрочитаних %d)", dmrSmsCount(0), dmrSmsUnreadCount());
		s_menu = UI_CPS;
		mainLoopFor(120000);
		CHECK(s_erases == e0, "7b: у режимі CPS звичайний тік не пише (%d)", s_erases - e0);
		dmrSmsStoreFlush();   /* те саме, що cpsFlushDeferredStores() перед NVIC_SystemReset */
		s_menu = 0;
		s_badErase = bad0;    /* стирання в CPS тут -- саме те, що треба (як у кроці 7 для вимкнення) */
		CHECK(s_erases == e0 + 1, "7b: Flush у CPS -- один запис (%d)", s_erases - e0);
		reboot();
		CHECK(dmrSmsCount(0) == 3, "7b: після перезавантаження з CPS -- відкладене вхідне збережено (%d)", dmrSmsCount(0));
		mainLoopFor(5000);
		dmrSmsMarkAllRead();
		s_menu = UI_CPS;
		dmrSmsStoreFlush();
		s_menu = 0;
		s_badErase = bad0;
		reboot();
		CHECK(dmrSmsUnreadCount() == 0, "7b: «прочитано» (до ~60 с відкладення) дописано з CPS");
	}

	/* 8. кільце по колу */
	{
		memset(s_slotErases, 0, sizeof s_slotErases);
		int e0 = s_erases;
		for (int k = 0; k < 20; k++) { attempt(); mainLoopFor(31000); }   /* > 30 с: інакше той самий PDU -- дублікат (Task #34) */
		CHECK(s_erases == e0 + 20, "8: 20 SMS -> 20 записів (%d)", s_erases - e0);
		int okw = 1; for (unsigned i = 0; i < SMSF_SLOTS; i++) { if (s_slotErases[i] < 2 || s_slotErases[i] > 3) { okw = 0; } }
		CHECK(okw, "8: кожен слот -- 2..3 стирання (%ld %ld %ld %ld %ld %ld %ld %ld)", s_slotErases[0], s_slotErases[1], s_slotErases[2],
				s_slotErases[3], s_slotErases[4], s_slotErases[5], s_slotErases[6], s_slotErases[7]);
		reboot();
		CHECK(dmrSmsCount(0) == 23 && dmrSmsUnreadCount() == 20, "8: перезапуск -- 23 вхідні (22 + одне з кроку 7b), 20 непрочитаних (%d/%d)", dmrSmsCount(0), dmrSmsUnreadCount());
		CHECK(s_cdWrites == 0, "8: custom-data за весь час не писалась (%d)", s_cdWrites);
		CHECK(s_outside == 0 && s_badErase == 0, "8: поза ділянкою -- %d, стирань у недозволений час -- %d", s_outside, s_badErase);
	}

	printf("CHECKS %d FAILS %d\n", checks, fails);
	return fails ? 1 : 0;
}
