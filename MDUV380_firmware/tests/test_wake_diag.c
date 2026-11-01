/*
 * test_wake_diag.c -- R58: журнал сеансів пробудження (СПРАВЖНІЙ application/source/functions/wake_diag.c).
 * Час подається параметром, залізо не потрібне. Збирається з -DENABLE_WAKE_DIAG (та ще раз з
 * -DLANGUAGE_BUILD_UKRAINIAN -- рядки екрана мають влізти в 26 символів).
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/wake_diag.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)rd16(p) | ((uint32_t)rd16(p + 2) << 16); }

int main(void)
{
	wakeDiagSession_t s;
	uint8_t buf[WAKE_DIAG_DUMP_HDR + (WAKE_DIAG_SESSIONS * WAKE_DIAG_REC_LEN) + 16];
	char line[40];

	printf("розмір запису: sizeof=%u REC_LEN=%u\n", (unsigned)sizeof(wakeDiagSession_t), (unsigned)WAKE_DIAG_REC_LEN);
	CHECK(sizeof(wakeDiagSession_t) == WAKE_DIAG_REC_LEN, "sizeof(wakeDiagSession_t) == WAKE_DIAG_REC_LEN (без хвостового вирівнювання)");

	wakeDiagInit();
	CHECK(wakeDiagCount() == 0U, "після Init журнал порожній");
	CHECK(wakeDiagGet(0, &s) == false, "Get(0) на порожньому журналі -- false");
	CHECK(wakeDiagDump(buf, sizeof(buf)) == (int)WAKE_DIAG_DUMP_HDR, "порожній дамп = лише заголовок");

	/* Події без відкритого сеансу -- ігноруються (а TX лічиться як пряма передача). */
	wakeDiagPacket(10); wakeDiagZero(10); wakeDiagAwaken(10); wakeDiagFail(10); wakeDiagToggle(3); wakeDiagIntTimeout();
	CHECK(wakeDiagCount() == 0U, "події без Begin нічого не створюють");
	wakeDiagTxStart(100);
	CHECK(wakeDiagDirectTx() == 1U, "TX без сеансу -> directTx = 1");

	/* Сеанс 1: to0=0 (випадок B), 3 пакети, AWAKEN, TX. */
	wakeDiagBegin(1000, 42, 43000000U + 5000U, 43000000U, 7, 0);
	wakeDiagPacket(1000); wakeDiagPacket(1060); wakeDiagPacket(1120);
	wakeDiagToggle(2); wakeDiagToggle(1); wakeDiagToggle(5);
	wakeDiagIntTimeout();
	wakeDiagAwaken(1500);
	wakeDiagAwaken(1600);   /* другий AWAKEN не перезаписує перший */
	wakeDiagTxStart(1700);
	CHECK(wakeDiagCount() == 1U, "1 сеанс");
	CHECK(wakeDiagGet(0, &s), "Get(0)");
	CHECK(s.chan == 42 && s.cc == 7 && s.to0 == 0, "chan/cc/to0");
	CHECK(s.pkts == 3 && s.pktT[0] == 0 && s.pktT[1] == 60 && s.pktT[2] == 120, "пакети 0/60/120 мс");
	CHECK(s.pktT[3] == WAKE_DIAG_NONE, "четвертого пакета нема -> NONE");
	CHECK(s.tAwaken == 500 && s.tTx == 700 && s.tFail == WAKE_DIAG_NONE, "Awaken=500 Tx=700 Fail=NONE");
	CHECK(s.maxToggle == 5 && s.intTmo == 1, "maxToggle=5 intTmo=1");
	CHECK((s.flags & WAKE_DIAG_FLAG_PREV_MASK) == WAKE_DIAG_PREV_NONE, "перший сеанс: prev = NONE");
	wakeDiagTxStart(1800);
	CHECK(wakeDiagDirectTx() == 2U, "друга TX того ж сеансу -> directTx++ (сеанс уже закрито)");
	wakeDiagPacket(1900);
	CHECK(wakeDiagGet(0, &s) && s.pkts == 3, "після TX сеанс закритий: пакети не рахуються");

	/* Сеанс 2: «нулі» таймера, FAILED; prev = OK. */
	wakeDiagBegin(5000, 42, 1, 2, 7, 600);
	wakeDiagZero(5600); wakeDiagZero(6200); wakeDiagZero(6800);
	wakeDiagFail(6800);
	wakeDiagGet(0, &s);
	CHECK((s.flags & WAKE_DIAG_FLAG_PREV_MASK) == WAKE_DIAG_PREV_OK, "сеанс 2: prev = OK");
	CHECK(s.to0 == 600 && s.zeros == 3 && s.zeroT[0] == 600 && s.zeroT[2] == 1800, "нулі 600/1200/1800");
	CHECK(s.tFail == 1800 && s.tAwaken == WAKE_DIAG_NONE, "Fail=1800, Awaken=NONE");
	wakeDiagAwaken(7000);
	CHECK(wakeDiagGet(0, &s) && s.tAwaken == WAKE_DIAG_NONE, "після FAILED сеанс закритий");

	/* Сеанс 3: prev = FAIL; обірваний -> сеанс 4 бачить CANCEL. */
	wakeDiagBegin(9000, 43, 1, 2, 7, 0);
	wakeDiagGet(0, &s);
	CHECK((s.flags & WAKE_DIAG_FLAG_PREV_MASK) == WAKE_DIAG_PREV_FAIL, "сеанс 3: prev = FAIL");
	wakeDiagBegin(9500, 43, 1, 2, 7, 0);
	wakeDiagGet(0, &s);
	CHECK((s.flags & WAKE_DIAG_FLAG_PREV_MASK) == WAKE_DIAG_PREV_CANCEL, "сеанс 4: prev = CANCEL (3 не дійшов ні до AWAKEN, ні до FAILED)");
	CHECK(wakeDiagCount() == 4U, "4 сеанси");

	/* Стрибок: сеанс закривається, наступний позначений HOP_START. */
	wakeDiagHop(9900, 44);
	wakeDiagGet(0, &s);
	CHECK(s.hopT == 400 && s.hopChan == 44, "hopT=400 hopChan=44");
	wakeDiagPacket(9950);
	CHECK(wakeDiagGet(0, &s) && s.pkts == 0, "після Hop сеанс закритий");
	wakeDiagBegin(10000, 44, 1, 2, 7, 0);
	wakeDiagGet(0, &s);
	CHECK((s.flags & WAKE_DIAG_FLAG_HOP_START) != 0 && s.chan == 44, "сеанс після Hop: HOP_START, chan=44");
	wakeDiagBegin(10100, 44, 1, 2, 7, 0);
	wakeDiagGet(0, &s);
	CHECK((s.flags & WAKE_DIAG_FLAG_HOP_START) == 0, "наступний за ним уже без HOP_START");

	/* Насичення лічильників і часу. */
	wakeDiagBegin(20000, 1, 1, 2, 7, 0);
	for (int i = 0; i < 300; i++) { wakeDiagPacket(20000 + (uint32_t)i); wakeDiagZero(20000 + (uint32_t)i); wakeDiagIntTimeout(); }
	wakeDiagGet(0, &s);
	CHECK(s.pkts == 255 && s.zeros == 255 && s.intTmo == 255, "лічильники насичуються на 255");
	CHECK(s.pktT[WAKE_DIAG_PKT_MAX - 1] == WAKE_DIAG_PKT_MAX - 1, "збережено лише перші WAKE_DIAG_PKT_MAX часів");
	wakeDiagPacket(20000U + 100000U);
	wakeDiagBegin(30000, 1, 1, 2, 7, 0);
	wakeDiagAwaken(30000U + 200000U);
	wakeDiagGet(0, &s);
	CHECK(s.tAwaken == (WAKE_DIAG_NONE - 1U), "час > 65 с насичується на 0xFFFE, а не збігається з NONE");

	/* TX через >20 с після старту -- уже не «наша» передача. */
	wakeDiagBegin(40000, 1, 1, 2, 7, 0);
	wakeDiagAwaken(40100);
	uint16_t d0 = wakeDiagDirectTx();
	wakeDiagTxStart(40000U + 25000U);
	CHECK(wakeDiagDirectTx() == d0 + 1U, "TX через 25 с після старту -> directTx, а не tTx");
	wakeDiagGet(0, &s);
	CHECK(s.tTx == WAKE_DIAG_NONE, "tTx не записано");

	/* Кільце: після WAKE_DIAG_SESSIONS+5 сеансів лишається рівно WAKE_DIAG_SESSIONS, найновіший першим. */
	wakeDiagReset();
	for (unsigned i = 0; i < WAKE_DIAG_SESSIONS + 5U; i++)
	{
		wakeDiagBegin(1000U * i, (int16_t)(100 + i), 1, 2, 3, 0);
	}
	CHECK(wakeDiagCount() == WAKE_DIAG_SESSIONS, "кільце тримає рівно %u сеансів", (unsigned)WAKE_DIAG_SESSIONS);
	wakeDiagGet(0, &s);
	CHECK(s.chan == 100 + WAKE_DIAG_SESSIONS + 4U, "age 0 -- найновіший");
	wakeDiagGet(WAKE_DIAG_SESSIONS - 1U, &s);
	CHECK(s.chan == 100 + 5U, "age %u -- найстарший з тих, що лишилися", (unsigned)(WAKE_DIAG_SESSIONS - 1U));
	CHECK(wakeDiagGet(WAKE_DIAG_SESSIONS, &s) == false, "age == кількість -- false");

	/* Дамп: заголовок і розкладка LE. */
	wakeDiagReset();
	wakeDiagBegin(100, 0x1234, 0x01020304U, 0x0A0B0C0DU, 9, 0x0258);
	wakeDiagPacket(100); wakeDiagPacket(160);
	wakeDiagZero(700);
	wakeDiagAwaken(900);
	wakeDiagTxStart(1000);
	int n = wakeDiagDump(buf, sizeof(buf));
	CHECK(n == (int)(WAKE_DIAG_DUMP_HDR + WAKE_DIAG_REC_LEN), "довжина дампу 1 сеансу = 8 + 52");
	CHECK(buf[0] == WAKE_DIAG_DUMP_VER && buf[1] == WAKE_DIAG_SESSIONS && buf[2] == 1 && buf[3] == 0, "заголовок: ver, макс, кількість");
	const uint8_t *r = buf + WAKE_DIAG_DUMP_HDR;
	CHECK(rd32(r) == 0x01020304U && rd32(r + 4) == 0x0A0B0C0DU, "rx/tx LE");
	CHECK(rd16(r + 8) == 0x1234 && r[10] == 9 && r[11] == 0, "chan LE, cc, flags");
	CHECK(rd16(r + 12) == 0x0258, "to0 LE");
	CHECK(rd16(r + 14) == 800 && rd16(r + 16) == 900 && rd16(r + 18) == WAKE_DIAG_NONE, "tAwaken/tTx/tFail");
	CHECK(r[24] == 2 && r[25] == 1, "pkts=2 zeros=1");
	CHECK(rd16(r + 28) == 0 && rd16(r + 30) == 60 && rd16(r + 32) == WAKE_DIAG_NONE, "pktT");
	CHECK(rd16(r + 40) == 600, "zeroT[0]");
	CHECK(WAKE_DIAG_REC_LEN == 52U && (40U + 2U * WAKE_DIAG_ZERO_MAX) == WAKE_DIAG_REC_LEN, "кінець запису збігається з REC_LEN");

	/* Обрізання дампу: старші сеанси відкидаються з кінця. */
	for (unsigned i = 0; i < 5; i++) { wakeDiagBegin(2000U + i, (int16_t)(200 + i), 1, 2, 3, 0); }
	n = wakeDiagDump(buf, (int)(WAKE_DIAG_DUMP_HDR + 2U * WAKE_DIAG_REC_LEN + 3U));
	CHECK(n == (int)(WAKE_DIAG_DUMP_HDR + 2U * WAKE_DIAG_REC_LEN) && buf[2] == 2, "місця на 2 записи -> віддано 2 найновіші");
	CHECK(rd16(buf + WAKE_DIAG_DUMP_HDR + 8) == 204, "перший у дампі -- найновіший (chan 204)");
	CHECK(wakeDiagDump(buf, 3) == 0, "буфер менший за заголовок -> 0");

	/* Текст екрана. */
	wakeDiagGet(0, &s);
	for (unsigned l = 0; l < WAKE_DIAG_LINES; l++)
	{
		memset(line, 'X', sizeof(line)); line[sizeof(line) - 1] = 0;
		bool ok = wakeDiagLine(&s, 0, 6, wakeDiagDirectTx(), l, line, 27);
		CHECK(ok && strlen(line) <= 26U, "рядок %u влазить у 26 символів (довжина %u): \"%s\"", l, (unsigned)strlen(line), line);
	}
	CHECK(wakeDiagLine(&s, 0, 6, 0, WAKE_DIAG_LINES, line, 27) == false, "рядка %u нема", (unsigned)WAKE_DIAG_LINES);
	CHECK(wakeDiagLine(NULL, 0, 6, 0, 0, line, 27) == false, "NULL-сеанс -> false");

#if !defined(LANGUAGE_BUILD_UKRAINIAN)
	/* Англійський варіант: перевіряємо точний текст першого рядка. */
	wakeDiagReset();
	wakeDiagBegin(0, 42, 43012500U, 43000000U, 7, 0);
	wakeDiagGet(0, &s);
	wakeDiagLine(&s, 0, 1, 0, 0, line, 27);
	CHECK(strcmp(line, "#42 RX 430.1250 CC7") == 0, "рядок 1: \"%s\"", line);
	wakeDiagLine(&s, 0, 1, 0, 1, line, 27);
	CHECK(strcmp(line, "TX 430.0000 to0=0") == 0, "рядок 2: \"%s\"", line);
#endif

	printf(fails ? "ПРОВАЛ: %d\n" : "ВСІ ПЕРЕВІРКИ ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
