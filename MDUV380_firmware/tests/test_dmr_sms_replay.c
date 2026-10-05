/*
 * test_dmr_sms_replay.c -- реплей запису BBD_0004 (2026-10-04) через СПРАВЖНІЙ збирач SMS
 * (functions/dmr_sms.c: dmrSmsRxDiagBurst / dmrSmsRxHdrAccept / dmrSmsRxBurst / dmrSmsRxReset /
 * dmrSmsRxTick), а не через копію. Залізо (HR-C6000, флеш, UI, звук, data-TX) -- заглушки нижче.
 *
 * Стокова 0x26EA29 шле форку 0x26EA0F те саме CONFIRMED rate-3/4 ТРИЧІ (0,87 / 6,76 / 12,52 с),
 * байти всіх спроб ідентичні. У полі PDU з валідним CRC32 склався лише з 3-ї спроби
 * (квитанція -- після 3-ї), хоча всі burst-и дійшли до SMS-хука (ISR т6 3, т8 12).
 *
 * Тест відтворює порядок ISR (HR-C6000.c, hrc6000SmsDataHook): на КОЖЕН data-burst
 * dmrSmsRxDiagBurst(), для 6 -- dmrSmsRxHdrAccept() + dmrSmsRxBurst(), для 8 -- dmrSmsRxBurst();
 * CRC-валідний TERM_LC -- dmrSmsRxReset() (як гілка термінатора в ISR); між burst-ами (60 мс,
 * DMO) крутиться головний цикл dmrSmsRxTick(). Вимога: PDU і квитанція -- вже з ПЕРШОЇ спроби.
 */
#include <stdint.h>
#include <stdbool.h>
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
#include "user_interface/menuSystem.h"
#include "user_interface/uiGlobals.h"
#include "crypto/dmr_aes.h"
#include "crypto/dmr_aes_hook.h"

/* ============================ заглушки заліза ============================ */
static uint32_t s_now = 1000;
uint32_t ticksGetMillis(void) { return s_now; }

uint32_t trxDMRID = 0x26EA0F;                 /* форк */
uint32_t trxTalkGroupOrPcId = 9;
volatile bool trxIsTransmitting = false;
static CodeplugChannel_t s_chan;
CodeplugChannel_t *currentChannelData = &s_chan;
CodeplugRxGroup_t currentRxGroupData;
const int16_t MELODY_ACK_BEEP[1] = { 0 };
const int16_t MELODY_SMS_RECEIVED_BEEP[1] = { 0 };

bool settingsIsOptionBitSet(bitfieldOptions_t bit) { (void)bit; return false; }
uint8_t codeplugChannelGetFlag(CodeplugChannel_t *c, ChannelFlag_t f) { (void)c; (void)f; return 0; }
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *b, int m) { (void)t; (void)b; (void)m; return false; }
/* Запис у флеш на рації блокує головний цикл на сотні мс. Рахуємо, скільки записів припало
 * на вікно «квитанція в черзі -> ключування/передача» (diag5: саме вони давали етап 2 = 228 мс). */
static int      s_txLoads;
static uint32_t s_txLoadMs;
#define TX_BUSY_MS 150   /* модель: 15 мс до ключування + ~135 мс передачі квитанції */
static int s_flashWrites, s_flashInTxWindow;
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *b, int l)
{
	(void)t; (void)b; (void)l;
	s_flashWrites++;
	if ((s_txLoads > 0) && ((s_now - s_txLoadMs) < TX_BUSY_MS)) { s_flashInTxWindow++; }
	return true;
}
void displayLightTrigger(bool k) { (void)k; }
static int s_notes;
void uiNotificationShow(uiNotificationType_t t, uiNotificationID_t i, uint32_t ms, const char *m, bool r)
{ (void)t; (void)i; (void)ms; (void)m; (void)r; s_notes++; }
void soundSetMelody(const int16_t *m) { (void)m; }
int dmrAesEnsureCustomDataRegion(void) { return 1; }
void dmrAesLoadKeys(void) { }
uint8_t dmrAesTxKeyId(void) { return 0; }

/* data-TX: лише фіксуємо, коли й що поставлено в ефір (квитанція). */
static uint8_t  s_txQ[64];
/* Модель dmr_data: після Load черга «зайнята» (Busy) ще до ключування; Active -- з 15-ї мс. */
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
int  dmrDataTxLoadDelayedEx(const uint8_t *b, uint8_t n, uint16_t d, int f)
{
	(void)d; (void)f;
	s_txLoads++; s_txLoadMs = s_now;
	memcpy(s_txQ, b, (n * BURST_STRIDE) < (int)sizeof s_txQ ? (size_t)(n * BURST_STRIDE) : sizeof s_txQ);
	return 1;
}

/* ============================ запис BBD_0004 ============================= */
static const uint8_t HDR[12] = { 0x43,0x4c,0x26,0xea,0x0f,0x26,0xea,0x29,0x84,0x08,0xa8,0x51 };
static const uint8_t BLK[4][18] = {
	{ 0x01,0xee,0x45,0x00,0x00,0x30,0x00,0x00,0x00,0x00,0x40,0x11,0x8e,0x38,0x0c,0x26,0xea,0x29 },
	{ 0x02,0x3a,0x0c,0x26,0xea,0x0f,0x0f,0xa7,0x0f,0xa7,0x00,0x1c,0x6f,0xc9,0x00,0x12,0xe0,0x00 },
	{ 0x05,0x7a,0x99,0x04,0x0d,0x00,0x0a,0x00,0x48,0x00,0x65,0x00,0x6c,0x00,0x6c,0x00,0x6f,0x00 },
	{ 0x07,0xb2,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0xec,0xfc,0x3c,0xeb },
};
#define SLOT_MS 60   /* DMO: один burst відправника раз на 60 мс */

static void mainLoopFor(uint32_t ms)
{
	for (uint32_t t = 0; t < ms; t++) { s_now++; dmrSmsRxTick(); }
}

/* Одна спроба стокової: 14 CSBK-преамбул, заголовок, 4 блоки rate-3/4, TERM_LC.
 * blk -- які блоки слати (diag6: зіпсовані/переставлені), hwOk -- біт i: HW CRC блока i «валідний». */
static void attemptEx(const uint8_t (*blk)[18], uint8_t hwOk)
{
	uint8_t csbk[12] = { 0xbd,0x00,0x80,0x00,0x26,0xea,0x0f,0x26,0xea,0x29,0,0 };
	for (int i = 0; i < 14; i++)
	{
		dmrSmsRxDiagBurst(3, 1);              /* CSBK у SMS-збирач не йде, лише лічильник/тиша */
		(void)csbk;
		mainLoopFor(SLOT_MS);
	}
	dmrSmsRxDiagBurst(6, 1);
	if (dmrSmsRxHdrAccept(1, HDR)) { dmrSmsRxBurst(6, HDR); }
	mainLoopFor(SLOT_MS);
	for (int b = 0; b < 4; b++)
	{
		dmrSmsRxDiagBurst(8, (hwOk >> b) & 1); /* rate-3/4: HW CRC зазвичай «поганий» -- як у полі */
		dmrSmsRxBurst(8, blk[b]);
		mainLoopFor(SLOT_MS);
	}
	/* CRC-валідний TERM_LC: гілка термінатора в ISR -> dmrSmsRxReset() і вихід ДО SMS-хука. */
	dmrSmsRxReset();
	mainLoopFor(SLOT_MS);
}
static void attempt(void) { attemptEx(BLK, 0); }

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

int main(void)
{
	printf("test_dmr_sms_replay:\n");
	dmrSmsInit();

	int ackAfter = 0;
	for (int k = 1; k <= 3; k++)
	{
		attempt();
		mainLoopFor(600);                          /* пауза після спроби -- час на квитанцію */
		uint32_t d[7]; dmrSmsRxDiag(d);
		dmrSmsDiagScreen_t s; dmrSmsDiagScreenGet(&s);
		printf("       спроба %d: PDU зібрано %u, квитанцій у черзі %u, віддано в dmr_data %d\n",
		       k, (unsigned)d[5], (unsigned)s.ackQueued, s_txLoads);
		if ((ackAfter == 0) && (s_txLoads > 0)) { ackAfter = k; }
		mainLoopFor(5000);                         /* ~5,6 с між спробами */
	}
	CHECK(ackAfter == 1, "квитанція поставлена в ефір після спроби %d (має бути 1)", ackAfter);

	/* Квитанція -- рівно та, що стокова приймає: 01 40 26ea29 26ea0f 00 08 (N(S)=0). */
	uint8_t exp[12]; dmrSmsPduAckHeader(0x26EA29, 0x26EA0F, 0, exp);
	CHECK(s_txQ[0] == DTB_DATA_HEADER && memcmp(s_txQ + 1, exp, 12) == 0,
	      "черга квитанції = заголовок 01 40 26ea29 26ea0f 00 08 (без преамбул)");

	/* Лічильники сторінки 3 «Діагностики» на чистому реплеї: 3 PDU, жодних втрат. */
	{
		dmrSmsDiagScreen_t g; dmrSmsDiagScreenGet(&g);
		printf("       стор.3: PDU %u, CRC %u, безЗаг %u, зайнято %u, переп %u, зайві %u, не_нам %u, зіпс %u, забір %u мс\n",
		       g.pduOk, g.crcFail, g.blkNoHdr, g.blkBusy, g.blkOvf, g.blkExtra, g.tickNotUs, g.tickBad, g.pickMaxMs);
		CHECK(g.pduOk == 3 && g.crcFail == 0 && g.blkNoHdr == 0 && g.blkBusy == 0 && g.blkOvf == 0 &&
		      g.blkExtra == 0 && g.tickNotUs == 0 && g.tickBad == 0, "лічильники стор. 3: 3 PDU, втрат 0");
		CHECK(g.dbsnBad == 0 && g.hw8Ok == 0, "стор. 4: DBSN по порядку (0 розбіжностей), HW-ok т8 = 0");
		dmrSmsBadSnapInfo_t si;
		CHECK(dmrSmsBadSnapInfo(&si) == 0, "стор. 4: чистий реплей -- знімка «CRC пог» нема");
	}

	/* diag5, етап 2 (228 мс): жодного запису у флеш, поки квитанція в черзі або в ефірі;
	 * а вхідне SMS однаково записане -- після передачі. */
	printf("       записів у флеш: усього %d, у вікні квитанції %d\n", s_flashWrites, s_flashInTxWindow);
	CHECK(s_flashInTxWindow == 0, "у вікні «черга -> ключування -> передача» флеш не пишеться");
	CHECK(s_flashWrites > 0, "вхідне SMS записано у флеш після передачі квитанції");

	/* ===== fix7: корекція трибітів; diag6: знімок лише невиправлених ===== */
	printf("       fix7: спроба з одним зіпсованим трибітом у блоці 2 -> має виправитись\n");
	dmrSmsDiagScreenReset();
	{
		uint8_t bad[4][18];
		memcpy(bad, BLK, sizeof bad);
		bad[2][10] ^= 0x04;                          /* один біт навантаження (один трибіт) */
		int before = s_txLoads;
		attemptEx((const uint8_t (*)[18])bad, 0x02);
		mainLoopFor(600);
		dmrSmsDiagScreen_t g; dmrSmsDiagScreenGet(&g);
		dmrSmsBadSnapInfo_t si;
		printf("       стор.3: CRC пог %u, корекц ок %u неод %u нема %u, %u мс\n", g.crcFail, g.fixOk, g.fixAmb, g.fixNone, g.fixLastMs);
		CHECK(g.crcFail == 1 && g.fixOk == 1 && g.fixAmb == 0 && g.fixNone == 0, "CRC пог 1 -> «Корекц ок» 1");
		CHECK(s_txLoads == before + 1, "виправлений PDU квитовано (квитанція в ефір)");
		CHECK(dmrSmsBadSnapInfo(&si) == 0, "виправлений PDU у знімок «Діагностики 4» НЕ потрапляє");
		CHECK(g.hw8Ok == 1, "HW-ok т8 = 1");
	}
	printf("       diag6/fix7: помилки у двох блоках поза заголовком IPv4 (2 і 3) -> «нема», знімок\n");
	{
		uint8_t bad[4][18];
		memcpy(bad, BLK, sizeof bad);
		bad[2][10] ^= 0x04;
		bad[3][5]  ^= 0x10;
		int before = s_txLoads;
		attemptEx((const uint8_t (*)[18])bad, 0x02);
		mainLoopFor(600);
		dmrSmsDiagScreen_t g; dmrSmsDiagScreenGet(&g);
		dmrSmsBadSnapInfo_t si;
		int n = dmrSmsBadSnapInfo(&si);
		CHECK(g.crcFail == 2 && g.fixOk == 1 && g.fixNone == 1 && s_txLoads == before, "CRC пог 2, «нема» 1, квитанції немає");
		CHECK(n == 4 && si.len == 18 && si.seq == 2 && si.hwOk == 0x02, "знімок: 4 блоки по 18 Б, №2, маска HW 02");
		CHECK(memcmp(si.hdr, HDR, 12) == 0, "знімок: сирий заголовок = 434c26ea0f26ea298408a851");
		int same = 1;
		for (int b = 0; b < 4; b++)
		{
			uint16_t ms = 0;
			const uint8_t *k = dmrSmsBadSnapBlock(b, &ms);
			if (!k || memcmp(k, bad[b], 18) != 0 || ms != (uint16_t)(SLOT_MS * (b + 1))) { same = 0; }
		}
		CHECK(same, "знімок: сирі блоки байт-у-байт як прийнято (не «виправлені»), час 60/120/180/240 мс");
		CHECK(si.crcWant == 0xecfc3cebu && si.crcGot != si.crcWant, "знімок: CRC32 очікуваний ecfc3ceb, фактичний інший (%08x)", (unsigned)si.crcGot);
		CHECK(dmrSmsBadSnapBlock(4, NULL) == NULL, "блока 5 у знімку нема");
		CHECK(g.dbsnBad == 0, "DBSN по порядку");
	}
	printf("       diag6: спроба з переставленими блоками 1 і 2\n");
	{
		uint8_t sw[4][18];
		memcpy(sw, BLK, sizeof sw);
		memcpy(sw[1], BLK[2], 18); memcpy(sw[2], BLK[1], 18);
		attemptEx((const uint8_t (*)[18])sw, 0);
		mainLoopFor(600);
		dmrSmsDiagScreen_t g; dmrSmsDiagScreenGet(&g);
		dmrSmsBadSnapInfo_t si;
		dmrSmsBadSnapInfo(&si);
		CHECK(g.crcFail == 3 && g.dbsnBad == 2 && g.fixNone == 2 && si.seq == 3, "перестановка: CRC пог 3, DBSN пор 2, не «виправлено», знімок №3");
		dmrSmsDiagScreenReset();
		CHECK(dmrSmsBadSnapInfo(&si) == 0, "довге GREEN (скидання) прибирає знімок");
	}
	/* fix7: знімок #12 з рації (2026-10-05) наскрізь через справжній збирач: дві помилки в
	 * різних блоках (заголовок IPv4 + блок 2) -> виправлено, квитанція з N(S)=4. */
	{
		static const uint8_t H12[12] = { 0x43,0x48,0x26,0xea,0x0f,0x26,0xea,0x29,0x84,0x48,0x7c,0x7a };
		static const char *const R12[4] = { "01d045000034000c001440118e280c26ea29", "03e60c26ea0f0fa70fa70020c0bc0016e000",
		                                    "042f85040d000a006d0075d06d0031006100", "07366d006a000000000000000000292ac790" };
		uint8_t b12[4][18];
		for (int b = 0; b < 4; b++) { for (int i = 0; i < 18; i++) { unsigned v; sscanf(R12[b] + 2 * i, "%2x", &v); b12[b][i] = (uint8_t)v; } }
		dmrSmsDiagScreenReset();
		int before = s_txLoads;
		for (int i = 0; i < 14; i++) { dmrSmsRxDiagBurst(3, 1); mainLoopFor(SLOT_MS); }
		dmrSmsRxDiagBurst(6, 1);
		if (dmrSmsRxHdrAccept(1, H12)) { dmrSmsRxBurst(6, H12); }
		mainLoopFor(SLOT_MS);
		for (int b = 0; b < 4; b++) { dmrSmsRxDiagBurst(8, 0); dmrSmsRxBurst(8, b12[b]); mainLoopFor(SLOT_MS); }
		dmrSmsRxReset();
		mainLoopFor(600);
		dmrSmsDiagScreen_t g; dmrSmsDiagScreenGet(&g);
		uint8_t exp[12]; dmrSmsPduAckHeader(0x26EA29, 0x26EA0F, 4, exp);
		CHECK(g.crcFail == 1 && g.fixOk == 1 && s_txLoads == before + 1 && memcmp(s_txQ + 1, exp, 12) == 0,
		      "знімок #12 наскрізь: «Корекц ок» 1, квитанція 01 40 26ea29 26ea0f 00 0c (N(S)=4)");
	}

	/* Після зіпсованих спроб чиста знову збирається з першого разу. */
	{
		int before = s_txLoads;
		attempt();
		mainLoopFor(600);
		dmrSmsDiagScreen_t g; dmrSmsDiagScreenGet(&g);
		CHECK(g.pduOk == 1 && s_txLoads == before + 1, "після зіпсованих -- чиста спроба: PDU і квитанція");
	}

	printf(fails ? "ПРОВАЛ (%d)\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
