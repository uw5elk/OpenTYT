/*
 * test_dmr_sms_store.c -- ui6: сховище SMS v3 (заголовок запису 12 Б, [8..11] = час) і
 * перетворення v2 -> v3 під час завантаження. Лінкує СПРАВЖНІЙ functions/dmr_sms.c; флеш
 * (блок MESSAGES), годинник, UI й data-TX -- заглушки нижче.
 *
 * Випадки: повне v2-сховище (не влазить після розширення -- найстаріші відкидаються), порожнє,
 * пошкоджене (ланцюжок v2 не сходиться), v3 без змін, геттер часу, годинник не виставлено.
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

/* ============================ заглушки ==================================== */
static uint32_t s_now = 1000;
uint32_t ticksGetMillis(void) { return s_now; }
uint32_t trxDMRID = 0x26EA0F;
uint32_t trxTalkGroupOrPcId = 9;
volatile bool trxIsTransmitting = false;
static CodeplugChannel_t s_chan;
CodeplugChannel_t *currentChannelData = &s_chan;
CodeplugRxGroup_t currentRxGroupData;
const int16_t MELODY_ACK_BEEP[1] = { 0 };
const int16_t MELODY_SMS_RECEIVED_BEEP[1] = { 0 };
bool settingsIsOptionBitSet(bitfieldOptions_t bit) { (void)bit; return false; }
uint8_t codeplugChannelGetFlag(CodeplugChannel_t *c, ChannelFlag_t f) { (void)c; (void)f; return 0; }

/* Блок MESSAGES у «флеші»: 1352 Б, як справжній. */
#define BLK_SIZE 1352
static uint8_t s_flash[BLK_SIZE];
static int     s_flashValid;
static int     s_flashWrites;
bool codeplugGetOpenGD77CustomDataBounded(CodeplugCustomDataType_t t, uint8_t *b, int m)
{
	if ((t == CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES) && s_flashValid)
	{
		memcpy(b, s_flash, (size_t)((m < BLK_SIZE) ? m : BLK_SIZE));
		return true;
	}
	return false;
}
bool codeplugSetOpenGD77CustomData(CodeplugCustomDataType_t t, uint8_t *b, int l)
{
	if (t == CODEPLUG_CUSTOM_DATA_TYPE_MESSAGES)
	{
		memcpy(s_flash, b, (size_t)((l < BLK_SIZE) ? l : BLK_SIZE));
		s_flashValid = 1;
		s_flashWrites++;
	}
	return true;
}
void displayLightTrigger(bool k) { (void)k; }
void uiNotificationShow(uiNotificationType_t t, uiNotificationID_t i, uint32_t ms, const char *m, bool r)
{ (void)t; (void)i; (void)ms; (void)m; (void)r; }
void soundSetMelody(const int16_t *m) { (void)m; }
int dmrAesEnsureCustomDataRegion(void) { return 1; }
void dmrAesLoadKeys(void) { }
uint8_t dmrAesTxKeyId(void) { return 0; }
static time_t_custom s_rtc = 1791235800U;   /* 2026-10-05 21:30:00 UTC */
time_t_custom getRtcTime_custom(void) { return s_rtc; }

int  dmrDataTxActive(void) { return 0; }
int  dmrDataTxBusy(void)   { return 0; }
void dmrDataTxDiag(uint16_t out[4]) { memset(out, 0, 4 * sizeof out[0]); }
void dmrDataTxDiagReset(void) { }
uint32_t dmrDataTxLastKeyMs(void) { return 0; }
uint32_t dmrDataTxLastSlotStartMs(void) { return 0; }
uint32_t dmrDataTxLastStartMs(void) { return 0; }
void dmrDataTxLoad(const uint8_t *b, uint8_t n) { (void)b; (void)n; }
void dmrDataTxLoadFast(const uint8_t *b, uint8_t n) { (void)b; (void)n; }
int  dmrDataTxLoadDelayedEx(const uint8_t *b, uint8_t n, uint16_t d, int f) { (void)b; (void)n; (void)d; (void)f; return 1; }

static void mainLoopFor(uint32_t ms)
{
	for (uint32_t t = 0; t < ms; t++) { s_now++; dmrSmsRxTick(); }
}

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* ============================ образ блока v2 =============================== */
/* Заголовок блока: "MSGV", version, rsvd, used (LE16), nextSeq (LE16), далі data[1342]. */
#define HDR_BLK 10
static int s_v2Used;
static void v2Begin(void)
{
	memset(s_flash, 0, sizeof s_flash);
	memcpy(s_flash, "MSGV", 4);
	s_flash[4] = 2;
	s_v2Used = 0;
}
/* Запис v2: [0]=flags [1]=textLen [2..3]=seq [4..7]=peer [8..]=text. Повертає 0, якщо не влазить. */
static int v2Add(uint8_t flags, uint16_t seq, uint32_t peer, const char *text)
{
	int tl = (int)strlen(text);
	if (s_v2Used + 8 + tl > (BLK_SIZE - HDR_BLK)) { return 0; }
	uint8_t *d = s_flash + HDR_BLK + s_v2Used;
	d[0] = (uint8_t)(0x01 | flags); d[1] = (uint8_t)tl;
	d[2] = (uint8_t)seq; d[3] = (uint8_t)(seq >> 8);
	d[4] = (uint8_t)peer; d[5] = (uint8_t)(peer >> 8); d[6] = (uint8_t)(peer >> 16); d[7] = (uint8_t)(peer >> 24);
	memcpy(d + 8, text, (size_t)tl);
	s_v2Used += 8 + tl;
	return 1;
}
static void v2End(uint16_t nextSeq)
{
	s_flash[6] = (uint8_t)s_v2Used; s_flash[7] = (uint8_t)(s_v2Used >> 8);
	s_flash[8] = (uint8_t)nextSeq;  s_flash[9] = (uint8_t)(nextSeq >> 8);
	s_flashValid = 1;
}

/* Типовий 20-символьний текст номер k. */
static void text20(int k, char *out)
{
	snprintf(out, 21, "Message number %05d", k);
}

int main(void)
{
	printf("test_dmr_sms_store:\n");
	char t[32];

	/* 1. Повне сховище v2 з 20-символьних повідомлень: v2 вміщує 1342/28 = 47, v3 -- 1342/32 = 41.
	 * Після перетворення -- 41 найновіше, порядок і тексти ті самі, час 0. */
	{
		v2Begin();
		int n = 0;
		for (int k = 1; ; k++)
		{
			text20(k, t);
			uint8_t fl = (k % 3 == 0) ? DMR_SMS_FLAG_OUTGOING : (uint8_t)DMR_SMS_FLAG_UNREAD;
			if (!v2Add(fl, (uint16_t)k, 0x26EA00U + (uint32_t)k, t)) { break; }
			n++;
		}
		v2End((uint16_t)(n + 1));
		printf("       v2: %d повідомлень по 20 символів (%d Б з %d)\n", n, s_v2Used, BLK_SIZE - HDR_BLK);
		CHECK(n == 47, "v2 вміщує 47 двадцятисимвольних");
		s_flashWrites = 0;
		dmrSmsInit();
		int in = dmrSmsCount(0), out = dmrSmsCount(1);
		printf("       v3 після перетворення: вхідних %d, надісланих %d\n", in, out);
		CHECK(in + out == 41, "v3: 41 найновіше (відкинуто 6 найстаріших)");
		/* Найстаріше, що лишилось, -- №7; найновіше -- №47. Перевіряємо всі тексти й seq. */
		int ok = 1, seen = 0;
		for (int f = 0; f < 2; f++)
		{
			for (int i = 0; i < dmrSmsCount(f); i++)
			{
				const dmrSmsMessage_t *m = dmrSmsGet(f, i);
				int k = (int)(m->peerId - 0x26EA00U);
				text20(k, t);
				if ((m->seq != k) || (m->textLen != 20) || memcmp(m->text, t, 20) || (k < 7) ||
						(((k % 3 == 0) ? 1 : 0) != f) || (dmrSmsGetTime(f, i) != 0)) { ok = 0; }
				seen++;
			}
		}
		CHECK(ok && (seen == 41), "тексти, seq, теки, отримувач -- без змін; час 0; №1..6 відкинуто");
		CHECK(dmrSmsGet(0, 0)->seq == 47 || dmrSmsGet(1, 0)->seq == 47, "найновіше -- №47");
		CHECK(dmrSmsUnreadCount() == (int)(((47 - 6) - ((47 / 3) - (6 / 3)))), "непрочитані збереглись (%d)", dmrSmsUnreadCount());
		CHECK(s_flashWrites == 0, "перетворення саме у флеш не пише (v2 там лишається до першої зміни)");
		CHECK(s_flash[4] == 2, "на флеші досі v2");

		/* Нове повідомлення після перетворення: v3 у флеші, час відправлення записано. */
		dmrSmsSend("New after upgrade!!!", 0x26EA29, 0, 0);
		mainLoopFor(2000);
		CHECK(s_flashWrites >= 1 && s_flash[4] == 3, "перша зміна пише вже v3 (version 3)");
		const dmrSmsMessage_t *m = dmrSmsGet(1, 0);
		CHECK(m && m->textLen == 20 && memcmp(m->text, "New after upgrade!!!", 20) == 0, "надіслане -- найновіше у «Надісланих»");
		CHECK(dmrSmsGetTime(1, 0) == (uint32_t)s_rtc, "час відправлення = годинник (%u)", (unsigned)dmrSmsGetTime(1, 0));
		CHECK(dmrSmsCount(0) + dmrSmsCount(1) == 41, "41 після додавання (одне найстаріше витіснено)");

		/* Перезавантаження: v3 читається як є. */
		int c0 = dmrSmsCount(0), c1 = dmrSmsCount(1);
		dmrSmsInit();
		CHECK(dmrSmsCount(0) == c0 && dmrSmsCount(1) == c1 && dmrSmsGetTime(1, 0) == (uint32_t)s_rtc,
				"v3 після перезавантаження -- те саме, з часом");
	}

	/* 2. Порожнє v2 -> порожнє v3. */
	{
		v2Begin();
		v2End(1);
		dmrSmsInit();
		CHECK(dmrSmsCount(0) == 0 && dmrSmsCount(1) == 0, "порожнє v2 -> порожнє v3");
		dmrSmsSend("Hi", 0x26EA29, 0, 0);
		mainLoopFor(2000);
		CHECK(dmrSmsCount(1) == 1 && s_flash[4] == 3, "і в нього пишеться v3");
	}

	/* 3. Кілька v2 (влазять повністю) -> v3 без втрат. */
	{
		v2Begin();
		v2Add(DMR_SMS_FLAG_UNREAD, 10, 111, "first");
		v2Add(DMR_SMS_FLAG_OUTGOING, 11, 222, "");
		v2Add(DMR_SMS_FLAG_UNREAD | DMR_SMS_FLAG_FOREIGN, 12, 333, "third message");
		v2End(13);
		dmrSmsInit();
		const dmrSmsMessage_t *a = dmrSmsGet(0, 0);
		const dmrSmsMessage_t *b;
		CHECK(dmrSmsCount(0) == 2 && dmrSmsCount(1) == 1, "3 записи: 2 вхідні, 1 надіслане");
		CHECK(a && a->peerId == 333 && a->textLen == 13 && !memcmp(a->text, "third message", 13) && (a->flags & DMR_SMS_FLAG_FOREIGN),
				"найновіше вхідне -- FOREIGN, текст цілий");
		b = dmrSmsGet(1, 0);
		CHECK(b && b->peerId == 222 && b->textLen == 0, "порожній текст переніс коректно");
		a = dmrSmsGet(0, 1);
		CHECK(a && a->peerId == 111 && a->textLen == 5 && !memcmp(a->text, "first", 5), "перше вхідне");
	}

	/* 4. Пошкоджене v2: ланцюжок не сходиться -> порожнє сховище (як і раніше). */
	{
		v2Begin();
		v2Add(DMR_SMS_FLAG_UNREAD, 1, 1, "abc");
		v2Add(DMR_SMS_FLAG_UNREAD, 2, 2, "defgh");
		s_v2Used -= 2;            /* used не на межі запису */
		v2End(3);
		dmrSmsInit();
		CHECK(dmrSmsCount(0) == 0 && dmrSmsCount(1) == 0, "пошкоджене v2 (used посеред запису) -> порожньо");

		v2Begin();
		v2Add(DMR_SMS_FLAG_UNREAD, 1, 1, "abc");
		s_flash[HDR_BLK + 1] = 200;   /* textLen > 144 */
		v2End(2);
		dmrSmsInit();
		CHECK(dmrSmsCount(0) == 0, "пошкоджене v2 (textLen 200) -> порожньо");

		v2Begin();
		v2End(1);
		s_flash[6] = 0xFF; s_flash[7] = 0xFF;   /* used > розміру */
		dmrSmsInit();
		CHECK(dmrSmsCount(0) == 0, "used > 1342 -> порожньо");

		/* Версія 3, але ланцюжок -- з 8-байтових заголовків (v2): не сходиться -> порожньо. */
		v2Begin();
		v2Add(DMR_SMS_FLAG_UNREAD, 1, 1, "ab");
		v2Add(DMR_SMS_FLAG_UNREAD, 2, 2, "cd");
		v2End(3);
		s_flash[4] = 3;
		dmrSmsInit();
		CHECK(dmrSmsCount(0) == 0, "версія 3 з ланцюжком v2 -> порожньо (не читаємо сміття як час)");

		v2Begin(); v2End(1); s_flash[4] = 7;
		dmrSmsInit();
		CHECK(dmrSmsCount(0) == 0, "невідома версія -> порожньо");
	}

	/* 5. Годинник не виставлено (рік < 2025) -> час 0. */
	{
		v2Begin(); v2End(1);
		dmrSmsInit();
		s_rtc = 946684800U;   /* 2000-01-01 */
		dmrSmsSend("old clock", 0x26EA29, 0, 0);
		mainLoopFor(2000);
		CHECK(dmrSmsCount(1) == 1 && dmrSmsGetTime(1, 0) == 0, "годинник 2000 року -> час 0 (невідомо)");
		s_rtc = 1735689600U;  /* 2025-01-01 00:00:00 -- межа: вже вважається виставленим */
		dmrSmsSend("new clock", 0x26EA29, 0, 0);
		mainLoopFor(2000);
		CHECK(dmrSmsGetTime(1, 0) == 1735689600U && dmrSmsGetTime(1, 1) == 0, "2025-01-01 -> записано; старе -- 0");
		CHECK(dmrSmsGetTime(1, 5) == 0 && dmrSmsGetTime(0, 0) == 0, "поза межами -> 0");
	}

	/* 6. Місткість v3: 20-символьних -- 41 (v2 -- 47). */
	{
		v2Begin(); v2End(1);
		dmrSmsInit();
		s_rtc = 1791235800U;
		for (int k = 0; k < 60; k++)
		{
			text20(k, t);
			dmrSmsSend(t, 0x26EA29, 0, 0);
			mainLoopFor(1200);
		}
		printf("       v3: після 60 надісланих лишилось %d\n", dmrSmsCount(1));
		CHECK(dmrSmsCount(1) == 41, "v3 вміщує 41 двадцятисимвольне");
	}

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
