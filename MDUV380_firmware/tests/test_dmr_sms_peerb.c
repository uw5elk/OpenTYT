/*
 * test_dmr_sms_peerb.c -- R98-FIX2 Д: біт 31 слова peerId запису SMS = «вхідне прийнято на картці B» («Подвійний прийом»).
 * Лінкує СПРАВЖНІЙ functions/dmr_sms.c (з -DENABLE_DUAL_CHANNEL: гілка прийому ставить біт за uiChannelModeDualOnCardB(), тут -- заглушка).
 * Реальний шлях прийому (dmrSmsRxBurst/dmrSmsRxTick) на записі BBD_0004; сховище -- справжній флеш-образ.
 * Перевіряє: біт ставиться лише на вхідних при ввімкненому режимі на B; dmrSmsGet()/dmrSmsNewestInbox() віддають ЧИСТИЙ ID; рахунок за картками
 * (dmrSmsUnreadCountB) -- один прохід по сховищу; читання/видалення/перезавантаження/перенумерація не ламають прив'язку; «Надіслані» бита не мають.
 */
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

/* ПЕРЕВИЗНАЧЕННЯ: режим на B -- керує тестом */
static int s_onB;
bool uiChannelModeDualOnCardB(void) { return s_onB != 0; }


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
/* ui2: блок режиму TX SMS (1 байт) моделюємо окремо; -1 -- блоку ще немає (нова установка). */
static int s_txModeStored = -1;
static uint8_t s_flash[1352];
static int     s_flashValid;
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *b, int m)
{
	if ((t == CODEPLUG_CUSTOM_DATA_TYPE_SMS_TX_MODE) && (s_txModeStored >= 0) && (m >= 1)) { b[0] = (uint8_t)s_txModeStored; return true; }
	if ((t == CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES) && s_flashValid) { memcpy(b, s_flash, (size_t)((m < 1352) ? m : 1352)); return true; }
	return false;
}
/* Запис у флеш на рації блокує головний цикл на сотні мс. Рахуємо, скільки записів припало
 * на вікно «квитанція в черзі -> ключування/передача» (diag5: саме вони давали етап 2 = 228 мс). */
static int      s_txLoads;
static uint32_t s_txLoadMs;
#define TX_BUSY_MS 150   /* модель: 15 мс до ключування + ~135 мс передачі квитанції */
static int s_flashWrites, s_flashInTxWindow;
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *b, int l)
{
	if (t == CODEPLUG_CUSTOM_DATA_TYPE_SMS_TX_MODE) { s_txModeStored = b[0]; return true; }
	if (t == CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES) { memcpy(s_flash, b, (size_t)((l < 1352) ? l : 1352)); s_flashValid = 1; }
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
/* ui6: час запису SMS -- годинник рації (секунди UTC). */
static time_t_custom s_rtc = 1791235800U;   /* 2026-10-05 21:30:00 UTC */
time_t_custom getRtcTime_custom(void) { return s_rtc; }

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
/* ui2: наше SMS -- яку чергу побудовано (перший data-заголовок) і чи швидкий кінець. */
static uint8_t s_sendHdr0;
static int     s_sendFast = -1;
static void noteSend(const uint8_t *b, uint8_t n, int fast)
{
	s_sendFast = fast;
	s_sendHdr0 = 0;
	for (int i = 0; i < n; i++) { if (b[i * BURST_STRIDE] == DTB_DATA_HEADER) { s_sendHdr0 = b[i * BURST_STRIDE + 1]; break; } }
}
void dmrDataTxLoad(const uint8_t *b, uint8_t n) { noteSend(b, n, 0); }
void dmrDataTxLoadFast(const uint8_t *b, uint8_t n) { noteSend(b, n, 1); }
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

/* ---- «сира» перевірка флеш-образу: [0..3]="MSGV", [4]=версія, [6..7]=used, [8..9]=nextSeq, далі записи v3: [0]=flags [1]=textLen [2..3]=seq [4..7]=peer [8..11]=час [12..]=текст */
#define HDR_BLK 10
static uint16_t rawUsed(void) { return (uint16_t)(s_flash[6] | (s_flash[7] << 8)); }
static int rawCount(void)
{
	int n = 0;
	for (int o = 0; o < rawUsed(); o += 12 + s_flash[HDR_BLK + o + 1]) { n++; }
	return n;
}
static uint32_t rawPeer(int k)
{
	int o = 0;
	for (int i = 0; i < k; i++) { o += 12 + s_flash[HDR_BLK + o + 1]; }
	const uint8_t *e = s_flash + HDR_BLK + o;
	return (uint32_t)e[4] | ((uint32_t)e[5] << 8) | ((uint32_t)e[6] << 16) | ((uint32_t)e[7] << 24);
}
static uint8_t rawFlags(int k)
{
	int o = 0;
	for (int i = 0; i < k; i++) { o += 12 + s_flash[HDR_BLK + o + 1]; }
	return s_flash[HDR_BLK + o];
}

/* ---- образ v2 (peer зберігається як є) для сценаріїв перенумерації та «сміття» у старшому байті */
static int s_v2Used;
static void v2Begin(void) { memset(s_flash, 0, sizeof s_flash); memcpy(s_flash, "MSGV", 4); s_flash[4] = 2; s_v2Used = 0; }
static void v2Add(uint8_t flags, uint16_t seq, uint32_t peer, const char *text)
{
	int tl = (int)strlen(text);
	uint8_t *d = s_flash + HDR_BLK + s_v2Used;
	d[0] = (uint8_t)(0x01 | flags); d[1] = (uint8_t)tl; d[2] = (uint8_t)seq; d[3] = (uint8_t)(seq >> 8);
	d[4] = (uint8_t)peer; d[5] = (uint8_t)(peer >> 8); d[6] = (uint8_t)(peer >> 16); d[7] = (uint8_t)(peer >> 24);
	memcpy(d + 8, text, (size_t)tl);
	s_v2Used += 8 + tl;
}
static void v2End(uint16_t nextSeq)
{
	s_flash[6] = (uint8_t)s_v2Used; s_flash[7] = (uint8_t)(s_v2Used >> 8);
	s_flash[8] = (uint8_t)nextSeq;  s_flash[9] = (uint8_t)(nextSeq >> 8);
	s_flashValid = 1;
}

#define PEER 0x26EA29u
#define ONB  0x80000000u

int main(void)
{
	printf("test_dmr_sms_peerb:\n");
	uint32_t t;

	/* 1. Режим вимкнено / рація на A: запис БЕЗ біта; рахунок B = 0 */
	s_flashValid = 0; memset(s_flash, 0, sizeof s_flash);
	dmrSmsInit();
	s_onB = 0;
	attempt(); mainLoopFor(3000);
	CHECK(dmrSmsCount(0) == 1 && dmrSmsUnreadCount() == 1, "A: одне вхідне, непрочитане");
	CHECK(rawCount() == 1 && rawPeer(0) == PEER, "A: у флеші peer = чистий ID без біта 31 (0x%08X)", (unsigned)rawPeer(0));
	CHECK(dmrSmsUnreadCountB() == 0, "A: рахунок картки B = 0");
	CHECK(dmrSmsGet(0, 0)->peerId == PEER, "A: dmrSmsGet() -> ID");

	/* 2. Рація на B: біт 31 у збереженому слові; зовнішній peerId чистий; рахунок B = 1 (одразу після прийому, до запису з відкладеного, і після) */
	s_onB = 1;
	dmrSmsInit();
	attempt();
	CHECK(dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 2, "B: одразу після прийому рахунки: B=1, усього=2 (відкладене вхідне враховано)");
	CHECK(dmrSmsNewestInbox(&t)->peerId == PEER, "B: dmrSmsNewestInbox() -> чистий ID (банер)");
	mainLoopFor(3000);
	CHECK(dmrSmsCount(0) == 2 && rawCount() == 2, "B: два вхідні у сховищі");
	CHECK(rawPeer(1) == (PEER | ONB), "B: у флеші peer = ID | біт 31 (0x%08X)", (unsigned)rawPeer(1));
	CHECK(rawPeer(0) == PEER, "B: попередній запис (A) не змінився");
	CHECK(dmrSmsGet(0, 0)->peerId == PEER && dmrSmsGet(0, 1)->peerId == PEER, "B: dmrSmsGet() віддає чистий ID для обох записів (без біта 31)");
	CHECK(dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 2, "B: після запису: B=1, усього=2 (A=1)");

	/* 3. Перезавантаження сховища (перезапуск) -- прив'язка зберігається */
	dmrSmsInit();
	CHECK(dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 2 && dmrSmsGet(0, 0)->peerId == PEER, "перезапуск: B=1, усього=2, ID чистий");

	/* 4. Читання повідомлення з B зменшує лише B */
	dmrSmsMarkRead(0, 0);
	CHECK(dmrSmsUnreadCountB() == 0 && dmrSmsUnreadCount() == 1, "прочитано з B: B=0, усього=1 (A лишилось)");
	dmrSmsInit();
	CHECK(dmrSmsUnreadCountB() == 0 && dmrSmsUnreadCount() == 1 && rawPeer(1) == (PEER | ONB), "після перезапуску так само; біт у записі лишається (читання його не чіпає)");

	/* 5. Ще одне на B; прочитати з A -- лише A */
	s_onB = 1; dmrSmsInit(); attempt(); mainLoopFor(3000);
	CHECK(dmrSmsCount(0) == 3 && dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 2, "ще одне на B: B=1, усього=2");
	dmrSmsMarkRead(0, 2);   /* найстаріше -- прийняте на A */
	CHECK(dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 1, "прочитано з A: B лишається 1, усього=1");

	/* 6. «Надіслані» бита не мають, рахунки не змінюються */
	s_onB = 1;
	dmrSmsSend("out", PEER, 0, 0); mainLoopFor(3000);
	CHECK(dmrSmsCount(1) == 1 && dmrSmsGet(1, 0)->peerId == PEER, "надіслане: ID чистий");
	int outIdx = -1;
	for (int k = 0; k < rawCount(); k++) { if (rawFlags(k) & DMR_SMS_FLAG_OUTGOING) { outIdx = k; } }
	CHECK(outIdx >= 0 && (rawPeer(outIdx) & ONB) == 0 && rawPeer(outIdx) == PEER, "надіслане: у флеші без біта 31 (навіть при ввімкненому B)");
	CHECK(dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 1, "надіслане не змінило рахунки");

	/* 7. Видалення непрочитаного з B */
	dmrSmsDelete(0, 0);
	CHECK(dmrSmsUnreadCountB() == 0 && dmrSmsUnreadCount() == 0 && dmrSmsCount(0) == 2, "видалено непрочитане з B: B=0, усього=0");

	/* 8. Очищення теки і «усе прочитано» */
	s_onB = 1; dmrSmsInit(); attempt(); mainLoopFor(3000);
	CHECK(dmrSmsUnreadCountB() == 1, "нове на B: B=1");
	dmrSmsMarkAllRead();
	CHECK(dmrSmsUnreadCountB() == 0 && dmrSmsUnreadCount() == 0, "«усе прочитано»: B=0, усього=0");
	s_onB = 1; dmrSmsInit(); attempt(); mainLoopFor(3000);
	CHECK(dmrSmsUnreadCountB() == 1, "нове на B після цього: B=1");
	dmrSmsDeleteAll(0);
	CHECK(dmrSmsCount(0) == 0 && dmrSmsUnreadCountB() == 0 && dmrSmsUnreadCount() == 0, "очищено вхідні: B=0, усього=0");

	/* 9. Перенумерація seq (nextSeq біля 0xFFFF): записи з бітом переживають її */
	v2Begin();
	v2Add(DMR_SMS_FLAG_UNREAD, 1, PEER | ONB, "on B");
	v2Add(DMR_SMS_FLAG_UNREAD, 2, PEER, "on A");
	v2End(0xFFFC);
	s_onB = 0; dmrSmsInit();
	CHECK(dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 2, "образ з прив'язкою: B=1, усього=2");
	for (int k = 0; k < 8; k++) { dmrSmsSend("wrap", PEER, 0, 0); mainLoopFor(1500); }
	CHECK(dmrSmsCount(0) == 2 && dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 2, "після 8 надісланих (seq перейшов 0xFFFF): B=1, усього=2");
	{
		int okId = 1;
		for (int i = 0; i < dmrSmsCount(0); i++) { if (dmrSmsGet(0, i)->peerId != PEER) { okId = 0; } }
		CHECK(okId, "після перенумерації ID чисті");
	}

	/* 10. Витіснення найстарішого (повне сховище): рахунок B рахує лише наявні записи */
	v2Begin();
	v2Add(DMR_SMS_FLAG_UNREAD, 1, PEER | ONB, "oldest unread B message text padding padding padding padding padding padding padding padding padding");
	v2End(2);
	s_onB = 0; dmrSmsInit();
	CHECK(dmrSmsUnreadCountB() == 1, "старе непрочитане на B на місці");
	for (int k = 0; k < 40; k++) { dmrSmsSend("fill fill fill fill fill fill fill fill fill fill fill", PEER, 0, 0); mainLoopFor(1200); }
	CHECK(dmrSmsCount(0) == 0 && dmrSmsUnreadCountB() == 0 && dmrSmsUnreadCount() == 0, "найстаріше витіснено -- B=0 (рахунок не тримає привидів)");

	/* 11. «Сміття» у старшому байті (іншa прошивка / поламаний запис): ID чистий, B лише за біту 31 */
	v2Begin();
	v2Add(DMR_SMS_FLAG_UNREAD, 1, 0x7F000000u | PEER, "garbage top byte 7F");
	v2Add(DMR_SMS_FLAG_UNREAD, 2, 0x55000000u | PEER, "garbage top byte 55");
	v2Add(DMR_SMS_FLAG_UNREAD, 3, 0xFF000000u | PEER, "top byte FF");
	v2End(4);
	s_onB = 0; dmrSmsInit();
	{
		int ok = 1;
		for (int i = 0; i < 3; i++) { if (dmrSmsGet(0, i)->peerId != PEER) { ok = 0; } }
		CHECK(ok, "будь-який старший байт знімається маскою 0x00FFFFFF: ID чистий");
	}
	CHECK(dmrSmsUnreadCountB() == 1 && dmrSmsUnreadCount() == 3, "B рахується лише за бітом 31 (0xFF.. -- так)");

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
