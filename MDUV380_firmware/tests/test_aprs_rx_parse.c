/*
 * test_aprs_rx_parse.c -- R8: розбір кадрів APRS (functions/aprs_rx_parse.c).
 *
 * Усі кадри СИНТЕТИЧНІ: збираються власними кодувальниками цього файлу (адреси AX.25, звичайна й
 * стиснута позиція, Mic-E за зворотним алгоритмом, повідомлення). Позивні -- вигадані (N0CALL,
 * TEST-n), координати -- довільні (приклади зі специфікації APRS та рівники). Жодного реального
 * ефірного кадра й нічиєї справжньої позиції.
 *
 * Перевіряє: AX.25 UI (SSID, цифіпітери, H-біт, відмова на не-UI), позиція (звичайна з відмітками
 * часу й неоднозначністю, стиснута, Mic-E в усіх півкулях і діапазонах довготи), повідомлення
 * (адресат, номер, ack, «нам / не нам»), статус, «інше», UTF-8 і не-UTF-8 текст, дедуплікацію 30 с,
 * повтори повідомлень, список станцій (заміна найстарішого, порядок), відстань і азимут.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "functions/aprs_rx_parse.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* ---- кодувальники ------------------------------------------------------------------ */

static int putAddr(uint8_t *p, const char *call, int ssid, int last, int hbit)
{
	int i = 0;

	for (; (i < 6) && call[i]; i++) { p[i] = (uint8_t)(call[i] << 1); }
	for (; i < 6; i++) { p[i] = (uint8_t)(' ' << 1); }
	p[6] = (uint8_t)(0x60 | (ssid << 1) | (last ? 1 : 0) | (hbit ? 0x80 : 0));
	return 7;
}

/* src-ssid > dst через digis (до 2: «WIDE1», ssid 1, та «WIDE2», ssid 1) */
static int buildFrame(uint8_t *f, const char *dst, const char *src, int srcSsid, int nDigi, int firstDigiUsed, const uint8_t *info, int infoLen)
{
	int n = 0;

	n += putAddr(&f[n], dst, 0, 0, 0);
	n += putAddr(&f[n], src, srcSsid, nDigi == 0, 0);
	if (nDigi >= 1) { n += putAddr(&f[n], "WIDE1", 1, nDigi == 1, firstDigiUsed); }
	if (nDigi >= 2) { n += putAddr(&f[n], "WIDE2", 1, 1, 0); }
	f[n++] = 0x03;
	f[n++] = 0xF0;
	memcpy(&f[n], info, (size_t)infoLen);
	return n + infoLen;
}

static int parseInfo(const char *dst, const char *info, aprsAx25_t *ax, aprsPacket_t *pk, uint8_t *buf)
{
	int n = buildFrame(buf, dst, "N0CALL", 7, 0, 0, (const uint8_t *)info, (int)strlen(info));

	if (!aprsAx25Parse(buf, (uint16_t)n, ax)) { return 0; }
	aprsPacketParse(ax, pk);
	return 1;
}

/* мікроградуси з градусів/хвилин/сотих */
static int32_t dm(int deg, int min, int hun)
{
	return (int32_t)(deg * 1000000LL + (min * 100LL + hun) * 500LL / 3LL);
}

/* Mic-E: info[0..8] за зворотним алгоритмом (lat/lon у градусах, хвилинах, сотих хвилини). */
static void encodeMicE(char *dst6, uint8_t *info, int latDeg, int latMin, int latHun, int north,
		int lonDeg, int lonMin, int lonHun, int west)
{
	int d[6] = { latDeg / 10, latDeg % 10, latMin / 10, latMin % 10, latHun / 10, latHun % 10 };
	int lonOff = (lonDeg >= 100);

	for (int i = 0; i < 6; i++) { dst6[i] = (char)('0' + d[i]); }
	if (north) { dst6[3] = (char)('P' + d[3]); }
	if (lonOff) { dst6[4] = (char)('P' + d[4]); }
	if (west) { dst6[5] = (char)('P' + d[5]); }
	dst6[6] = 0;

	info[0] = '`';
	if (lonDeg >= 100) { info[1] = (uint8_t)(lonDeg - 100 + 28); }
	else if (lonDeg < 10) { info[1] = (uint8_t)(190 + lonDeg + 28); }
	else { info[1] = (uint8_t)(lonDeg + 28); }
	info[2] = (uint8_t)((lonMin < 10 ? lonMin + 60 : lonMin) + 28);
	info[3] = (uint8_t)(lonHun + 28);
	info[4] = 28 + 12; info[5] = 28 + 3; info[6] = 28 + 40;   /* швидкість/курс -- не розбираються */
	info[7] = '>'; info[8] = '/';
}

static void testMicE(const char *name, int latDeg, int latMin, int latHun, int north, int lonDeg, int lonMin, int lonHun, int west)
{
	uint8_t info[32], fr[120];
	char dst[8];
	aprsAx25_t ax;
	aprsPacket_t pk;

	encodeMicE(dst, info, latDeg, latMin, latHun, north, lonDeg, lonMin, lonHun, west);
	strcpy((char *)&info[9], "Mic-E test");
	int n = buildFrame(fr, dst, "TEST", 9, 1, 1, info, 9 + 10);
	int ok = aprsAx25Parse(fr, (uint16_t)n, &ax);
	if (ok) { aprsPacketParse(&ax, &pk); }
	int32_t wantLat = dm(latDeg, latMin, latHun) * (north ? 1 : -1);
	int32_t wantLon = dm(lonDeg, lonMin, lonHun) * (west ? -1 : 1);
	CHECK(ok && (pk.type == APRS_T_POSITION) && pk.micE && pk.hasPos && (pk.latU == wantLat) && (pk.lonU == wantLon),
			"Mic-E %s: lat %d lon %d (чекаємо %d %d), текст «%s»", name, ok ? pk.latU : 0, ok ? pk.lonU : 0, wantLat, wantLon, ok ? pk.text : "");
}

/* стиснута позиція: base91 з чотирьох символів */
static void b91(uint8_t *o, int64_t v)
{
	for (int i = 3; i >= 0; i--) { o[i] = (uint8_t)(33 + (v % 91)); v /= 91; }
}

/* R11-fix: кадр шлюзу (SP5WWP-10 > APRS) з заданим info (байти), розбір AX.25, РОЗГОРТАННЯ third-party, розбір пакета.
 * Повертає результат aprsAx25Unwrap() (1/0) або -1, якщо кадр шлюзу не розібрано. */
static int tpParseBytes(const uint8_t *info, int infoLen, aprsAx25_t *ax, aprsPacket_t *pk, uint8_t *buf)
{
	int n = buildFrame(buf, "APRS", "SP5WWP", 10, 0, 0, info, infoLen);
	int u;

	if (!aprsAx25Parse(buf, (uint16_t)n, ax)) { memset(pk, 0, sizeof(*pk)); return -1; }
	u = aprsAx25Unwrap(ax) ? 1 : 0;
	aprsPacketParse(ax, pk);
	return u;
}

static int tpParse(const char *info, aprsAx25_t *ax, aprsPacket_t *pk, uint8_t *buf)
{
	return tpParseBytes((const uint8_t *)info, (int)strlen(info), ax, pk, buf);
}

/* ---- R14: кадри з реального логу Direwolf (шлюз UW5ELK-1 і наш маяк US5EX-7), розбір від довільного src ---------------------- */
static int parseFrom(const char *src, int ssid, const uint8_t *info, int infoLen, aprsAx25_t *ax, aprsPacket_t *pk, uint8_t *buf)
{
	int n = buildFrame(buf, "APDW18", src, ssid, 0, 0, info, infoLen);

	if (!aprsAx25Parse(buf, (uint16_t)n, ax)) { memset(pk, 0, sizeof(*pk)); return 0; }
	aprsPacketParse(ax, pk);
	return 1;
}

static int pf(const char *src, int ssid, const char *info, aprsAx25_t *ax, aprsPacket_t *pk, uint8_t *buf)
{
	return parseFrom(src, ssid, (const uint8_t *)info, (int)strlen(info), ax, pk, buf);
}

/* стиснута позиція, 13 байт */
static void encC(uint8_t *o, double lat, double lon, char table, char code, uint8_t c, uint8_t s, uint8_t t)
{
	o[0] = (uint8_t)table;
	b91(o + 1, (int64_t)(380926.0 * (90.0 - lat) + 0.5));
	b91(o + 5, (int64_t)(190463.0 * (180.0 + lon) + 0.5));
	o[9] = (uint8_t)code; o[10] = c; o[11] = s; o[12] = t;
}

#define BEACON_IG "UW5ELK-1 *010000z4753.25N/03316.86Er438.950MHz T082 -760 DMR/D-Star/YSF/FM Repeater; 144.800MHz APRS Tx-Rx-iGate"

static void testR14(void)
{
	aprsAx25_t ax;
	aprsPacket_t pk;
	uint8_t b[400];
	char in[260];

	printf("== R14 T1: об'єкт ';' (реальний кадр [0L]) ==\n");
	pf("UW5ELK", 1, ";" BEACON_IG, &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && pk.hasPos && !pk.killed, "тип -- позиція, об'єкт живий");
	CHECK((pk.latU == dm(47, 53, 25)) && (pk.lonU == dm(33, 16, 86)), "позиція 47.887500 / 33.281000 (%d %d)", pk.latU, pk.lonU);
	CHECK((pk.symTable == '/') && (pk.symCode == 'r'), "символ /r (репітер): %c%c", pk.symTable, pk.symCode);
	CHECK(pk.freqKHz == 438950U, "частота 438.950 МГц (%u кГц)", pk.freqKHz);
	CHECK(!strcmp(pk.tone, "T082"), "тон T082 («%s»)", pk.tone);
	CHECK(pk.hasShift && (pk.shiftKHz == -7600), "зсув -7.60 МГц (%d кГц)", pk.shiftKHz);
	CHECK(!strcmp(pk.text, "DMR/D-Star/YSF/FM Repeater; 144.800MHz APRS Tx-Rx-iGate"), "текст без полів, ';' у коментарі цілий: «%s»", pk.text);
	CHECK((pk.course == 0) && (pk.speedKn == 0), "курсу/швидкості нема");

	printf("== R14 T2: знятий об'єкт '_' ==\n");
	pf("UW5ELK", 1, ";UW5ELK-1 _010000z4753.25N/03316.86Er438.950MHz T082 -760 text", &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && pk.hasPos && pk.killed && (pk.freqKHz == 438950U) && !strcmp(pk.text, "[\xE7\xED\xFF\xF2\xEE]: text"), "позиція є, ознака «знято» у тексті (cp1251): «%s»", pk.text);

	printf("== R14 T3: стиснутий об'єкт; ім'я != src ==\n");
	{
		uint8_t c13[13];

		encC(c13, 47.8875, 33.281, '/', 'r', ' ', ' ', 0x21);
		snprintf(in, sizeof(in), ";REPEAT-2 *010000h");
		memcpy(in + strlen(in), c13, 13);
		strcpy(in + 18 + 13, "438.950MHz T082 -760 rpt");
		pf("UW5ELK", 1, in, &ax, &pk, b);
		CHECK((pk.type == APRS_T_POSITION) && pk.compressed && (labs((long)pk.latU - dm(47, 53, 25)) < 20) && (labs((long)pk.lonU - dm(33, 16, 86)) < 20),
				"стиснута позиція після часу 'h' (%d %d)", pk.latU, pk.lonU);
		CHECK((pk.freqKHz == 438950U) && !strcmp(pk.text, "REPEAT-2: rpt"), "ім'я != src -> префікс: «%s»", pk.text);
		pf("REPEAT", 2, in, &ax, &pk, b);
		CHECK(!strcmp(pk.text, "rpt"), "ім'я == src -> без префікса: «%s»", pk.text);
	}

	printf("== R14 T4: обрізаний об'єкт ==\n");
	for (int cut = 1; cut <= 30; cut += 3)
	{
		snprintf(in, sizeof(in), "%.*s", cut, ";UW5ELK-1 *010000z4753.25N/03316.86Er");
		pf("UW5ELK", 1, in, &ax, &pk, b);
		if (cut < 31)
		{
			if (pk.type != APRS_T_OTHER) { printf("  FAIL обрізано до %d байт: тип %d\n", cut, pk.type); fails++; }
		}
	}
	pf("UW5ELK", 1, ";UW5ELK-1 *010000z4753.25N/0", &ax, &pk, b);
	CHECK((pk.type == APRS_T_OTHER) && (pk.text[0] != 0), "обрізаний -- «інше» із сирим текстом: «%s»", pk.text);
	pf("UW5ELK", 1, ";UW5ELK-1 X010000z4753.25N/03316.86Er", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "поганий прапорець об'єкта -- «інше»");

	printf("== R14 T5: предмет ')' ==\n");
	pf("N0CALL", 7, ")AID #2!4903.50N/07201.75WAhello", &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && pk.hasPos && !pk.killed && (pk.symCode == 'A') && !strcmp(pk.text, "AID #2: hello"), "предмет живий: «%s»", pk.text);
	pf("N0CALL", 7, ")AID #2_4903.50N/07201.75WAhello", &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && pk.killed && (pk.latU == dm(49, 3, 50)) && !strncmp(pk.text, "AID #2 [\xE7\xED\xFF\xF2\xEE]: hello", 14), "предмет знятий");
	pf("N0CALL", 7, ")AID #2!4903.50N/0", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "обрізаний предмет -- «інше»");
	pf("N0CALL", 7, ")AB!4903.50N/07201.75WA", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "ім'я предмета коротше за 3 -- «інше»");

	printf("== R14 T6: '<' можливості станції ==\n");
	pf("UW5ELK", 1, "<IGATE,MSG_CNT=0,PKT_CNT=0,DIR_CNT=0,LOC_CNT=0,RF_CNT=0", &ax, &pk, b);
	CHECK((pk.type == APRS_T_STATUS) && !strcmp(pk.text, "IGATE,MSG_CNT=0,PKT_CNT=0,DIR_CNT=0,LOC_CNT=0,RF_CNT=0"), "статус, текст видно: «%s»", pk.text);

	printf("== R14 T7: наш кадр US5EX-7 (еталон регресії) ==\n");
	pf("US5EX", 7, "!/65RzVx.&[  !144.800MHz Toff +000 TYT MD-UV390", &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && pk.compressed && (pk.symTable == '/') && (pk.symCode == '['), "позиція, символ /[ (%c%c)", pk.symTable, pk.symCode);
	CHECK((pk.course == 0) && (pk.speedKn == 0) && !pk.hasAlt && (pk.rangeVal == 0), "курсу/швидкості/висоти/радіуса нема");
	CHECK((pk.freqKHz == 144800U) && !strcmp(pk.tone, "Toff") && pk.hasShift && (pk.shiftKHz == 0), "144.800, Toff, зсув 0");
	CHECK(!strcmp(pk.text, "TYT MD-UV390"), "текст «%s»", pk.text);

	printf("== R14 T8 (Б1): '_' -- вітер, а не курс ==\n");
	pf("N0CALL", 7, "!4903.50N/07201.75W_310/004g006t077r000p000h50b10265", &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && (pk.symCode == '_') && (pk.course == 0) && (pk.speedKn == 0), "курсу і швидкості станції нема");
	CHECK((pk.wxMask & APRS_WX_WIND) && (pk.windDeg == 310) && (pk.windMph == 4) && (pk.wxMask & APRS_WX_GUST) && (pk.gustMph == 6), "вітер 310 / 4 mph, порив 6");
	CHECK((pk.wxMask & APRS_WX_TEMP) && (pk.tempC == 25) && (pk.wxMask & APRS_WX_HUM) && (pk.humPct == 50) && (pk.wxMask & APRS_WX_PRESS) && (pk.pressDhPa == 10265),
			"t 25 °C, 50 %%, 1026.5 гПа (%d %u %u)", pk.tempC, pk.humPct, pk.pressDhPa);
	CHECK(pk.text[0] == 0, "текст порожній: «%s»", pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W_220/004g005t-05h00b09720 Davis", &ax, &pk, b);
	CHECK((pk.tempC == -21) && (pk.humPct == 100) && (pk.pressDhPa == 9720) && !strcmp(pk.text, "Davis"), "t-05 -> -21 °C, h00 -> 100 %%, текст «%s»", pk.text);

	printf("== R14 T9 (Б2): стиснута, c == '{' -- радіус ==\n");
	{
		uint8_t c13[13];

		encC(c13, 49.0, 20.0, '/', '#', '{', 33 + 10, 0x21);
		in[0] = '!'; memcpy(in + 1, c13, 13); in[14] = 0;
		pf("N0CALL", 7, in, &ax, &pk, b);
		CHECK((pk.course == 0) && (pk.speedKn == 0) && (pk.rangeVal == 4) && !pk.rangeKm, "радіус 2*1.08^10 = 4.3 милі -> %u", pk.rangeVal);
	}

	printf("== R14 T10 (Б2): стиснута з висотою GGA ==\n");
	{
		uint8_t c13[13];
		double ft = pow(1.002, 37.0 * 91.0 + 86.0);

		encC(c13, 49.0, 20.0, '/', '>', 33 + 37, 33 + 86, 33 + 0x10);
		in[0] = '!'; memcpy(in + 1, c13, 13); in[14] = 0;
		pf("N0CALL", 7, in, &ax, &pk, b);
		CHECK(pk.hasAlt && (pk.altM == (int32_t)(ft * 0.3048 + 0.5)) && (pk.course == 0) && (pk.speedKn == 0), "висота %d м (чекаємо %d), курсу нема", pk.altM, (int)(ft * 0.3048 + 0.5));
		encC(c13, 49.0, 20.0, '/', '>', 33 + 22, 33 + 10, 0x21 + 0x2);
		in[0] = '!'; memcpy(in + 1, c13, 13);
		pf("N0CALL", 7, in, &ax, &pk, b);
		CHECK(!pk.hasAlt && (pk.course == 88) && (pk.speedKn == 1), "звичайний cs: курс %u, швидкість %u", pk.course, pk.speedKn);
	}

	printf("== R14 T11 (Б3): Mic-E, висота 'xxx}' ==\n");
	{
		uint8_t info[48], fr[140];
		char dst[8];
		int n;

		encodeMicE(dst, info, 33, 25, 64, 1, 112, 7, 58, 1);
		memcpy(&info[9], "`\"3z}_$", 8);   /* R16: префікс + висота + порожній коментар + суфікс */
		n = buildFrame(fr, dst, "TEST", 9, 0, 0, info, 17);
		aprsAx25Parse(fr, (uint16_t)n, &ax);
		aprsPacketParse(&ax, &pk);
		CHECK(pk.micE && pk.hasAlt && (pk.altM == 8) && !pk.text[0], "висота %d м, текст «%s» (без \"3z}, суфікса)", pk.altM, pk.text);
		memcpy(&info[9], "\"3z}hello", 9);
		n = buildFrame(fr, dst, "TEST", 9, 0, 0, info, 18);
		aprsAx25Parse(fr, (uint16_t)n, &ax);
		aprsPacketParse(&ax, &pk);
		CHECK(pk.hasAlt && (pk.altM == 8) && !strcmp(pk.text, "hello"), "висота без байта типу: текст «%s»", pk.text);
		memcpy(&info[9], "`plain_$", 8);
		n = buildFrame(fr, dst, "TEST", 9, 0, 0, info, 17);
		aprsAx25Parse(fr, (uint16_t)n, &ax);
		aprsPacketParse(&ax, &pk);
		CHECK(!pk.hasAlt && !strcmp(pk.text, "plain"), "без висоти: префікс і суфікс знято, текст «%s»", pk.text);
	}

	printf("== R14 T12: '/A=' у середині ==\n");
	pf("N0CALL", 7, "!4903.50N/07201.75W>Hello /A=001234 world", &ax, &pk, b);
	CHECK(pk.hasAlt && (pk.altM == 376) && !strcmp(pk.text, "Hello world"), "висота %d м, текст «%s»", pk.altM, pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W>/A=-00123", &ax, &pk, b);
	CHECK(pk.hasAlt && (pk.altM == -37) && (pk.text[0] == 0), "від'ємна висота %d м", pk.altM);

	printf("== R14 T13: телеметрія в коментарі ==\n");
	pf("N0CALL", 7, "!4903.50N/07201.75W>hello |ss11|", &ax, &pk, b);
	CHECK(!strcmp(pk.text, "hello"), "|ss11| вирізано: «%s»", pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W>hello |ss1122334455!\"|", &ax, &pk, b);
	CHECK(!strcmp(pk.text, "hello"), "|ss1122334455!\"| вирізано: «%s»", pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W>a |b| c", &ax, &pk, b);
	CHECK(!strcmp(pk.text, "a |b| c"), "не телеметрія (замало знаків) -- лишається: «%s»", pk.text);

	printf("== R14 T14: !DAO! ==\n");
	pf("N0CALL", 7, "!4903.50N/07201.75W>hello !W23!", &ax, &pk, b);
	CHECK(!strcmp(pk.text, "hello"), "!W23! вирізано: «%s»", pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W>hello !w..! x", &ax, &pk, b);
	CHECK(!strcmp(pk.text, "hello x"), "!w..! вирізано: «%s»", pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W>Hi!!", &ax, &pk, b);
	CHECK(!strcmp(pk.text, "Hi!!"), "не DAO -- лишається: «%s»", pk.text);

	printf("== R14 T15: PHG / RNG / DFS ==\n");
	pf("N0CALL", 7, "!4903.50N/07201.75W#PHG5360digi", &ax, &pk, b);
	CHECK((pk.extKind == APRS_EXT_PHG) && (pk.extVal == 0x5360) && !strcmp(pk.text, "digi"), "PHG5360: %u %04x «%s»", pk.extKind, pk.extVal, pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W#RNG0025 rng", &ax, &pk, b);
	CHECK((pk.extKind == APRS_EXT_RNG) && (pk.extVal == 25) && !strcmp(pk.text, "rng"), "RNG0025: %u %u «%s»", pk.extKind, pk.extVal, pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W\\DFS2360", &ax, &pk, b);
	CHECK((pk.extKind == APRS_EXT_DFS) && (pk.extVal == 0x2360) && (pk.text[0] == 0), "DFS2360");

	printf("== R14 AA5: курс/швидкість 088/010 ==\n");
	pf("N0CALL", 7, "!4903.50N/07201.75W>088/010 mobile", &ax, &pk, b);
	CHECK((pk.course == 88) && (pk.speedKn == 10) && !strcmp(pk.text, "mobile"), "курс %u, швидкість %u, текст «%s»", pk.course, pk.speedKn, pk.text);
	pf("N0CALL", 7, "!4903.50N/07201.75W>088/010144.800MHz", &ax, &pk, b);
	CHECK((pk.course == 88) && (pk.freqKHz == 144800U), "курс і частота підряд");

	printf("== R14: погода без позиції '_' ==\n");
	pf("N0CALL", 7, "_10090556c220s004g005t077r000p000P000h50b09900wRSW", &ax, &pk, b);
	CHECK((pk.type == APRS_T_OTHER) && !pk.hasPos, "тип лишається «інше», позиції нема (вікно не відкриється)");
	CHECK((pk.wxMask & APRS_WX_WIND) && (pk.windDeg == 220) && (pk.windMph == 4) && (pk.gustMph == 5) && (pk.tempC == 25) && (pk.humPct == 50) && (pk.pressDhPa == 9900),
			"поля: вітер %u/%u mph, порив %u, %d C, %u %%, %u", pk.windDeg, pk.windMph, pk.gustMph, pk.tempC, pk.humPct, pk.pressDhPa);
	CHECK(!strcmp(pk.text, "25C 50% 990.0hPa w220/6km/h g8 wRSW"), "текст: «%s»", pk.text);
	pf("N0CALL", 7, "_1009xx56c220s004", &ax, &pk, b);
	CHECK((pk.type == APRS_T_OTHER) && (strstr(pk.text, "c220") != NULL), "не MMDDHHMM -- сирий текст");
	pf("N0CALL", 7, "_10090556", &ax, &pk, b);
	CHECK((pk.type == APRS_T_OTHER) && (pk.wxMask == 0), "лише відмітка часу -- без падіння");

	printf("== R14 T16: third-party із вкладеним шляхом ==\n");
	{
		int u = tpParse("}UW5ELK-1>APDW18,TCPIP*,qAC,T2UKRAINE:!4753.25NR03316.86E&438.950MHz T082 -760 DMR", &ax, &pk, b);

		CHECK((u == 1) && ax.tp && !strcmp(ax.src, "UW5ELK-1") && (pk.type == APRS_T_POSITION) && (pk.freqKHz == 438950U) && (pk.symTable == 'R') && (pk.symCode == '&'),
				"розгорнуто: src %s, таблиця-накладка %c, код %c", ax.src, pk.symTable, pk.symCode);
		u = tpParse("}UW5ELK-1>APDW18,TCPIP*,qAC,T2.POLC_1:>status", &ax, &pk, b);
		CHECK((u == 1) && (pk.type == APRS_T_STATUS), "'.' і '_' у шляху дозволені");
	}

	printf("== R14 T17: DTI, які ми не розбираємо -> «інше» із текстом ==\n");
	{
		const char *dti = "\"#$%&(*+,-.0123456789?ATU\\]^_a{|~";
		int bad = 0;

		for (size_t i = 0; dti[i]; i++)
		{
			snprintf(in, sizeof(in), "%cxyz unparsed 12345", dti[i]);
			pf("N0CALL", 7, in, &ax, &pk, b);
			if ((pk.type != APRS_T_OTHER) || (strstr(pk.text, "unparsed") == NULL)) { printf("  FAIL DTI '%c': тип %d, текст «%s»\n", dti[i], pk.type, pk.text); bad++; }
		}
		pf("N0CALL", 7, "!!xyz unparsed", &ax, &pk, b);
		if ((pk.type != APRS_T_OTHER) || (strstr(pk.text, "unparsed") == NULL)) { bad++; }
		pf("N0CALL", 7, "[xyz unparsed", &ax, &pk, b);
		if ((pk.type != APRS_T_OTHER) || (strstr(pk.text, "unparsed") == NULL)) { bad++; }
		CHECK(bad == 0, "усі непідтримувані DTI -- «інше» з непорожнім текстом");
	}

	printf("== R14: станція в списку -- src, не ім'я об'єкта; прапорець i-gate ==\n");
	{
		static aprsRxDb_t db;

		memset(&db, 0, sizeof(db));
		pf("UW5ELK", 1, ";" BEACON_IG, &ax, &pk, b);
		aprsStation_t *st = aprsDbUpdate(&db, &ax, &pk, 1000);
		CHECK((st != NULL) && !strcmp(st->call, "UW5ELK-1") && (st->flags & APRS_ST_HASPOS) && !(st->flags & APRS_ST_TP), "запис за src, без прапорця TP");
		tpParse("}UW5ELK-1>APDW18:!4753.25NR03316.86E&x", &ax, &pk, b);
		st = aprsDbUpdate(&db, &ax, &pk, 2000);
		CHECK((st != NULL) && (st->flags & APRS_ST_TP) && (aprsDbCount(&db) == 1), "через i-gate: прапорець TP, той самий запис");
	}
}

/* NMEA-речення з правильною контрольною сумою */
static void nmea(char *out, size_t cap, const char *body)
{
	uint8_t x = 0;

	for (size_t i = 0; body[i]; i++) { x ^= (uint8_t)body[i]; }
	snprintf(out, cap, "$%s*%02X", body, x);
}

static void testStage3(void)
{
	aprsAx25_t ax;
	aprsPacket_t pk;
	uint8_t b[400];
	char in[200];

	printf("== R14 етап 3: '!DAO!' застосовується ==\n");
	pf("N0CALL", 7, "!4903.50N/07201.75W>x !W29!", &ax, &pk, b);
	CHECK((pk.latU == dm(49, 3, 50) + 33) && (pk.lonU == -dm(72, 1, 75) - 150) && !strcmp(pk.text, "x"), "!W29!: широта +33 мкград (2 тис. хв), довгота -150 (9 тис. хв) (%d %d)", pk.latU - dm(49, 3, 50), pk.lonU + dm(72, 1, 75));
	pf("N0CALL", 7, "!4903.50S/07201.75E>!w+5!", &ax, &pk, b);
	CHECK((pk.latU == -(dm(49, 3, 50) + (10 * 11 + 3) / 6)) && (pk.lonU == dm(72, 1, 75) + (20 * 11 + 3) / 6), "!w+5!: base91, знак від нуля (%d %d)", pk.latU, pk.lonU);
	pf("N0CALL", 7, "!4903.50N/07201.75W>!W  !", &ax, &pk, b);
	CHECK((pk.latU == dm(49, 3, 50)) && (pk.lonU == -dm(72, 1, 75)), "два пробіли -- без змін");

	printf("== R14 етап 3: запити, метадані телеметрії, бюлетені ==\n");
	pf("N0CALL", 7, ":N0CALL-7 :?APRS?", &ax, &pk, b);
	CHECK((pk.type == APRS_T_OTHER) && (strstr(pk.text, "?APRS?") != NULL), "?APRS? -- не повідомлення, текст видно");
	pf("N0CALL", 7, ":N0CALL-7 :?APRSP", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "?APRSP -- не повідомлення");
	pf("N0CALL", 7, ":N0CALL-7 :?IGATE?", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "?IGATE? -- не повідомлення");
	pf("N0CALL", 7, ":N0CALL-7 :PARM.Vin,Temp", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "PARM. -- не повідомлення");
	pf("N0CALL", 7, ":N0CALL-7 :UNIT.V,C", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "UNIT. -- не повідомлення");
	pf("N0CALL", 7, ":N0CALL-7 :EQNS.0,5,0", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "EQNS. -- не повідомлення");
	pf("N0CALL", 7, ":N0CALL-7 :BITS.11111111,Test", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "BITS. -- не повідомлення");
	pf("N0CALL", 7, ":N0CALL-7 :?where are you{12", &ax, &pk, b);
	CHECK((pk.type == APRS_T_MESSAGE) && !strcmp(pk.msgId, "12"), "людське \"?where...\" -- звичайне повідомлення з номером");
	pf("N0CALL", 7, ":N0CALL-7 :?? hi", &ax, &pk, b);
	CHECK(pk.type == APRS_T_MESSAGE, "\"?? hi\" -- повідомлення");
	pf("N0CALL", 7, ":N0CALL-7 :PARMA test", &ax, &pk, b);
	CHECK(pk.type == APRS_T_MESSAGE, "\"PARMA test\" (без крапки) -- повідомлення");
	pf("N0CALL", 7, ":BLN1     :Meeting tonight", &ax, &pk, b);
	CHECK((pk.type == APRS_T_MESSAGE) && !aprsMsgIsForUs(pk.msgTo, "N0CALL", 7), "BLN1 -- не нам (ACK не йде)");

	printf("== R14 етап 3: NMEA ==\n");
	nmea(in + 0, sizeof(in), "GPRMC,092751.000,A,5321.6802,N,00630.3372,W,10.6,31.66,280511,,,A");
	pf("N0CALL", 7, in, &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && pk.hasPos && (labs((long)pk.latU - 53361337L) <= 2) && (labs((long)pk.lonU + 6505620L) <= 2) && (pk.speedKn == 11) && (pk.course == 32) && !strcmp(pk.text, "NMEA GPRMC"),
			"GPRMC: %d %d, %u вуз., курс %u, «%s»", pk.latU, pk.lonU, pk.speedKn, pk.course, pk.text);
	nmea(in, sizeof(in), "GNGGA,092750.000,5321.6802,S,00630.3372,E,1,8,1.03,61.7,M,55.2,M,,");
	pf("N0CALL", 7, in, &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && (pk.latU < 0) && (pk.lonU > 0) && pk.hasAlt && (pk.altM == 62) && !strcmp(pk.text, "NMEA GNGGA"), "GNGGA: S/E, висота %d м, «%s»", pk.altM, pk.text);
	nmea(in, sizeof(in), "GPRMC,092751.000,V,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A");
	pf("N0CALL", 7, in, &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "RMC зі статусом V -- «інше»");
	nmea(in, sizeof(in), "GPGGA,092750.000,5321.6802,N,00630.3372,W,0,8,1.03,61.7,M,55.2,M,,");
	pf("N0CALL", 7, in, &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "GGA без фіксації (якість 0) -- «інше»");
	nmea(in, sizeof(in), "GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A");
	in[strlen(in) - 1] ^= 1;
	pf("N0CALL", 7, in, &ax, &pk, b);
	CHECK((pk.type == APRS_T_OTHER) && !pk.hasPos, "хибна контрольна сума -- «інше»");
	pf("N0CALL", 7, "$GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "без контрольної суми -- «інше»");
	nmea(in, sizeof(in), "GPRMC,092751.000,A,5321.68,N,00630.3372,W,0.06,31.66,280511,,,A");
	pf("N0CALL", 7, in, &ax, &pk, b);
	CHECK(pk.type == APRS_T_POSITION, "коротка дробова частина -- ок");
	nmea(in, sizeof(in), "GPRMC,092751.000,A,9121.6802,N,00630.3372,W,0.06,31.66,280511,,,A");
	pf("N0CALL", 7, in, &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "широта понад 90 -- «інше»");
	nmea(in, sizeof(in), "GPXXX,1,2,3,4,5,6,7,8,9,10");
	pf("N0CALL", 7, in, &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "інше речення -- «інше»");
	pf("N0CALL", 7, "$GPRMC,0927*", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "обірване речення -- без падіння");

	printf("== R14 етап 3: Maidenhead-грід ==\n");
	pf("N0CALL", 7, "[IO91SX]", &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && (labs((long)pk.latU - 51979167L) < 1500) && (labs((long)pk.lonU + 458333L) < 1500) && !strcmp(pk.text, "grid IO91SX"),
			"[IO91SX]: %d %d «%s»", pk.latU, pk.lonU, pk.text);
	pf("N0CALL", 7, "[io91]", &ax, &pk, b);
	CHECK((pk.type == APRS_T_POSITION) && (pk.latU == 51500000) && (pk.lonU == -1000000) && !strcmp(pk.text, "grid IO91"), "[io91]: %d %d", pk.latU, pk.lonU);
	pf("N0CALL", 7, "[ZZ91]", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "[ZZ91] -- не грід");
	pf("N0CALL", 7, "[IO9]", &ax, &pk, b);
	CHECK(pk.type == APRS_T_OTHER, "обірваний грід -- «інше»");
}


/* Як parseFrom(), але кадр лежить у купі РІВНО за розміром -- ASan ловить будь-яке читання за кінцем інфополя. */
static int parseExact(const char *src, int ssid, const uint8_t *info, int infoLen, aprsAx25_t *ax, aprsPacket_t *pk)
{
	uint8_t tmp[400];
	int n = buildFrame(tmp, "APDW18", src, ssid, 0, 0, info, infoLen);
	uint8_t *h = (uint8_t *)malloc((size_t)n);
	int ok;

	memcpy(h, tmp, (size_t)n);
	ok = aprsAx25Parse(h, (uint16_t)n, ax);
	if (ok)
	{
		(void)aprsAx25Unwrap(ax);
		aprsPacketParse(ax, pk);
	}
	else
	{
		memset(pk, 0, sizeof(*pk));
	}
	/* ax->info вказує в h: звільняти лише після розбору */
	free(h);
	return ok;
}

/* Усі префікси й випадкові спотворення типових кадрів: жодного падіння/виходу за межі (під ASan/UBSan -- справжня перевірка) */
static void testFuzz(void)
{
	static const char *samples[] =
	{
		";" BEACON_IG,
		")AID #2!4903.50N/07201.75WAhello |ss11| !W23!",
		"!/65RzVx.&[  !144.800MHz Toff +000 TYT MD-UV390 /A=001234",
		"!4903.50N/07201.75W_310/004g006t077r000p000h50b10265",
		"@092345z4903.50N/07201.75W>088/010PHG5360 test",
		"_10090556c220s004g005t077r000p000P000h50b09900wRSW",
		"<IGATE,MSG_CNT=0,PKT_CNT=0",
		"$GPRMC,092751.000,A,5321.6802,N,00630.3372,W,0.06,31.66,280511,,,A*45",
		"[IO91SX]",
		":N0CALL-7 :Hello{12",
		"`CF\"l#![/`\"3z}_",
		"}UW5ELK-1>APDW18,TCPIP*,qAC,T2UKRAINE:!4753.25NR03316.86E&438.950MHz T082 -760 DMR",
	};
	aprsAx25_t ax;
	aprsPacket_t pk;
	uint8_t info[160];
	unsigned long seed = 12345UL;
	int n = 0, bad = 0;

	printf("== R14: префікси й спотворення кадрів (під ASan/UBSan) ==\n");
	for (size_t s = 0; s < (sizeof(samples) / sizeof(samples[0])); s++)
	{
		size_t l = strlen(samples[s]);

		for (size_t cut = 0; cut <= l; cut++)
		{
			memcpy(info, samples[s], cut);
			if (parseExact("UW5ELK", 1, info, (int)cut, &ax, &pk)) { n++; }
			if (strlen(pk.text) >= sizeof(pk.text)) { bad++; }
		}
		for (int k = 0; k < 2000; k++)
		{
			memcpy(info, samples[s], l);
			for (int m = 0; m < 3; m++)
			{
				seed = seed * 1103515245UL + 12345UL;
				info[(seed >> 8) % l] = (uint8_t)(seed >> 16);
			}
			if (parseExact("UW5ELK", 1, info, (int)l, &ax, &pk)) { n++; }
			if (strlen(pk.text) >= sizeof(pk.text)) { bad++; }
		}
	}
	CHECK(bad == 0, "розібрано %d спотворених кадрів, тексти в межах", n);
}

/* ---- R15: кадр у вигляді TNC-2 для екрана «Останній пакет» ---------------------------------------------- */
/* Кадр з довільним числом цифіпітерів (до 8): digi i -- «D<i>» з SSID i; hmask -- які мають біт H. Повертає довжину. */
static int buildDigiFrame(uint8_t *f, int nDigi, unsigned hmask, const uint8_t *info, int infoLen)
{
	int n = 0;

	n += putAddr(&f[n], "APRS", 0, 0, 0);
	n += putAddr(&f[n], "N0CALL", 7, nDigi == 0, 0);
	for (int i = 1; i <= nDigi; i++)
	{
		char nm[4] = { 'D', (char)('0' + i), 0, 0 };

		n += putAddr(&f[n], nm, i, i == nDigi, (hmask >> i) & 1U);
	}
	f[n++] = 0x03;
	f[n++] = 0xF0;
	memcpy(&f[n], info, (size_t)infoLen);
	return n + infoLen;
}

/* Копія РІВНО потрібного розміру в купі -- ASan/UBSan ловлять вихід за кадр. */
static uint8_t *exactCopy(const uint8_t *f, int n)
{
	uint8_t *h = (uint8_t *)malloc((size_t)n);

	memcpy(h, f, (size_t)n);
	return h;
}

static void testRawText(void)
{
	uint8_t fr[700];
	char out[APRS_RAW_TEXT_MAX + 8];

	printf("== R15: сирий пакет (TNC-2) ==\n");
	{
		const char *inf = "!4903.50N/07201.75W-Test";
		int n = buildFrame(fr, "APRS", "N0CALL", 7, 2, 1, (const uint8_t *)inf, (int)strlen(inf));
		uint8_t *h = exactCopy(fr, n);
		size_t l = aprsAx25ToText(h, (uint16_t)n, out, sizeof(out));

		CHECK(l == strlen(out) && !strcmp(out, "N0CALL-7>APRS,WIDE1-1*,WIDE2-1:!4903.50N/07201.75W-Test"), "2 цифіпітери, H-біт: [%s]", out);
		free(h);
	}
	{
		/* 8 цифіпітерів (шлях у aprsAx25_t обрізано до 23 символів -- тут має бути ВЕСЬ) і недрукованi байти info */
		const uint8_t inf[] = { 'A', 0x01, 'B', 0xFF, 'C', 0x0D, 0x80, 'D', 0x7F, 0x00, 'E' };
		int n = buildDigiFrame(fr, 8, (1U << 3), inf, (int)sizeof(inf));
		uint8_t *h = exactCopy(fr, n);
		aprsAx25_t ax;
		size_t l = aprsAx25ToText(h, (uint16_t)n, out, sizeof(out));

		CHECK(l == strlen(out) && !strcmp(out, "N0CALL-7>APRS,D1-1,D2-2,D3-3*,D4-4,D5-5,D6-6,D7-7,D8-8:A.B.C..D..E"), "8 цифіпітерів, недруковані -> '.': [%s]", out);
		CHECK(aprsAx25Parse(h, (uint16_t)n, &ax) && strlen(ax.path) < strlen("D1-1,D2-2,D3-3*,D4-4,D5-5,D6-6,D7-7,D8-8"), "шлях у aprsAx25_t справді обрізано (тому беремо з кадру)");
		free(h);
	}
	{
		/* довге info (300 Б): рівно 255 символів + NUL */
		uint8_t inf[300];
		int n;
		uint8_t *h;
		size_t l;

		for (int i = 0; i < 300; i++) { inf[i] = (uint8_t)('a' + (i % 26)); }
		n = buildDigiFrame(fr, 0, 0, inf, 300);
		h = exactCopy(fr, n);
		memset(out, 'Z', sizeof(out));
		l = aprsAx25ToText(h, (uint16_t)n, out, APRS_RAW_TEXT_MAX);
		CHECK(l == 255U && out[255] == 0 && strlen(out) == 255U, "довге info: 255 символів, NUL на місці (l=%zu)", l);
		CHECK(!strncmp(out, "N0CALL-7>APRS:abcdefghij", 24), "початок збережено");
		CHECK(out[APRS_RAW_TEXT_MAX] == 'Z', "за буфером (cap) нічого не записано");
		free(h);
	}
	{
		/* малий cap: завжди NUL, довжина cap-1; cap == 1 -> порожній рядок */
		const uint8_t inf[] = "hello";
		int n = buildDigiFrame(fr, 1, 0, inf, 5);
		uint8_t *h = exactCopy(fr, n);

		memset(out, 'Z', sizeof(out));
		CHECK(aprsAx25ToText(h, (uint16_t)n, out, 10U) == 9U && out[9] == 0 && out[10] == 'Z' && !strncmp(out, "N0CALL-7>", 9), "cap=10 -> 9 символів + NUL");
		CHECK(aprsAx25ToText(h, (uint16_t)n, out, 1U) == 0U && out[0] == 0, "cap=1 -> порожній рядок");
		CHECK(aprsAx25ToText(h, (uint16_t)n, NULL, 10U) == 0U && aprsAx25ToText(h, (uint16_t)n, out, 0U) == 0U, "NULL і cap=0 -- без падіння");
		free(h);
	}
	{
		/* не AX.25 UI: коротке, без PID, 9 цифіпітерів -> порожньо */
		uint8_t g[20] = { 0 };
		int n;
		uint8_t *h;

		memset(out, 'Z', sizeof(out));
		CHECK(aprsAx25ToText(g, 10U, out, sizeof(out)) == 0U && out[0] == 0, "кадр < 16 Б -> порожньо");
		h = exactCopy(g, 20);
		CHECK(aprsAx25ToText(h, 20U, out, sizeof(out)) == 0U && out[0] == 0, "сміття -> порожньо");
		free(h);
		n = buildDigiFrame(fr, 2, 0, (const uint8_t *)"x", 1);
		fr[n - 3] = 0x04;   /* контрольне поле не 0x03 */
		h = exactCopy(fr, n);
		CHECK(aprsAx25ToText(h, (uint16_t)n, out, sizeof(out)) == 0U && out[0] == 0, "не UI-кадр -> порожньо");
		free(h);
	}
	{
		/* third-party: сирий текст = кадр шлюзу, слідом -- розгорнутий */
		const char *inf = "}SRC1>APRS,TCPIP,GATE*:!4903.50N/07201.75W-Hi";
		int n = buildDigiFrame(fr, 0, 0, (const uint8_t *)inf, (int)strlen(inf));
		uint8_t *h = exactCopy(fr, n);
		aprsAx25_t ax;
		size_t l;

		CHECK(aprsAx25Parse(h, (uint16_t)n, &ax), "кадр шлюзу розібрано");
		l = aprsAx25ToText(h, (uint16_t)n, out, sizeof(out));
		CHECK(!strcmp(out, "N0CALL-7>APRS:}SRC1>APRS,TCPIP,GATE*:!4903.50N/07201.75W-Hi"), "сирий текст містить '}' і вкладений заголовок: [%s]", out);
		CHECK(aprsAx25AppendUnwrapped(out, sizeof(out), l, &ax) == l, "без розгортання (tp=false) -- нічого не дописано");
		CHECK(aprsAx25Unwrap(&ax), "розгорнуто");
		{
			size_t l2 = aprsAx25AppendUnwrapped(out, sizeof(out), l, &ax);

			CHECK(l2 > l && l2 == strlen(out) && !strcmp(out + l, " => SRC1>APRS,TCPIP,GATE*:!4903.50N/07201.75W-Hi"), "розгорнутий варіант слідом: [%s]", out + l);
		}
		/* не влазить цілком -- не дописується зовсім */
		l = aprsAx25ToText(h, (uint16_t)n, out, sizeof(out));
		CHECK(aprsAx25AppendUnwrapped(out, l + 20U, l, &ax) == l && out[l] == 0, "не влазить -- без змін");
		free(h);
	}
}

/* ---- R16 (ВА): ідентифікатор пристрою Mic-E ------------------------------------------------------------ */
static void parseMicEInfo(const uint8_t *head9, const uint8_t *tail, int tailLen, int lonDeg, int lonMin, int lonHun, aprsPacket_t *pk)
{
	uint8_t info[64], fr[160];
	char dst[8];
	aprsAx25_t ax;
	int n;

	encodeMicE(dst, info, 49, 3, 50, 1, lonDeg, lonMin, lonHun, 0);
	memcpy(info, head9, 9);
	memcpy(&info[9], tail, (size_t)tailLen);
	n = buildFrame(fr, dst, "UW5ELK", 6, 0, 0, info, 9 + tailLen);
	memset(pk, 0, sizeof *pk);
	CHECK(aprsAx25Parse(fr, (uint16_t)n, &ax), "кадр розібрано на рівні AX.25");
	aprsPacketParse(&ax, pk);
}

static void testR16Mice(void)
{
	aprsPacket_t pk;

	printf("== R16 ВА: ідентифікатор пристрою Mic-E ==\n");
	{
		/* UW5ELK-7 (Yaesu FT1D), кадр з Direwolf: info = `=6$l<SP><0x1c>[/ + `_$ + CR */
		static const uint8_t h[9] = { '`', '=', '6', '$', 'l', ' ', 0x1c, '[', '/' };
		static const uint8_t t[] = { '`', '_', '$', 0x0d };

		parseMicEInfo(h, t, 4, 33, 26, 8, &pk);
		CHECK(pk.micE && (pk.type == APRS_T_POSITION) && (pk.symTable == '/') && (pk.symCode == '[') && !pk.hasAlt && (pk.text[0] == 0),
				"FT1D: символ %c%c, висота %d, текст «%s» (порожній)", pk.symTable, pk.symCode, pk.hasAlt, pk.text);
	}
	{
		/* UW5ELK-6 (Kenwood TH-D74): info = '=,ll<SP><0x1c>K\ + >"4B}^ + CR */
		static const uint8_t h[9] = { '\'', '=', ',', 'l', 'l', ' ', 0x1c, 'K', '\\' };
		static const uint8_t t[] = { '>', '"', '4', 'B', '}', '^', 0x0d };

		parseMicEInfo(h, t, 7, 33, 16, 80, &pk);
		CHECK(pk.micE && (pk.symTable == '\\') && (pk.symCode == 'K') && pk.hasAlt && (pk.altM == 43) && (pk.text[0] == 0),
				"TH-D74: символ %c%c, висота %d м, текст «%s» (порожній)", pk.symTable, pk.symCode, pk.altM, pk.text);
	}
	{
		/* новий формат зі справжнім коментарем між префіксом і суфіксом */
		static const uint8_t h[9] = { '`', '=', '6', '$', 'l', ' ', 0x1c, '[', '/' };
		static const uint8_t t[] = { '`', 'H', 'e', 'l', 'l', 'o', ' ', 'U', 'A', '_', '$', 0x0d };

		parseMicEInfo(h, t, 12, 33, 26, 8, &pk);
		CHECK(!strcmp(pk.text, "Hello UA") && !pk.hasAlt, "новий формат + коментар: «%s»", pk.text);
	}
	{
		/* старий формат: висота, справжній коментар, суфікс */
		static const uint8_t h[9] = { '\'', '=', ',', 'l', 'l', ' ', 0x1c, 'K', '\\' };
		static const uint8_t t[] = { '>', '"', '4', 'B', '}', 'q', 'S', 'l', 'o', 'n', '=', 0x0d, 0x0a };

		parseMicEInfo(h, t, 13, 33, 16, 80, &pk);
		CHECK(pk.hasAlt && (pk.altM == 43) && !strcmp(pk.text, "qSlon"), "старий формат + коментар: «%s» висота %d", pk.text, pk.altM);
	}
	{
		/* старий формат без суфікса: останній байт -- буква, лишається */
		static const uint8_t h[9] = { '\'', '=', ',', 'l', 'l', ' ', 0x1c, 'K', '\\' };
		static const uint8_t t[] = { ']', 'o', 'k', 'D' };

		parseMicEInfo(h, t, 4, 33, 16, 80, &pk);
		CHECK(!strcmp(pk.text, "okD"), "старий формат, суфікса нема: «%s»", pk.text);
	}
	{
		/* вироджені: лише префікс; префікс + 1 байт; новий формат з двох байтів */
		static const uint8_t h[9] = { '`', '=', '6', '$', 'l', ' ', 0x1c, '[', '/' };
		static const uint8_t t1[] = { '`' };
		static const uint8_t t2[] = { '`', '_' };
		static const uint8_t t3[] = { '>' };

		parseMicEInfo(h, t1, 1, 33, 26, 8, &pk);
		CHECK(pk.micE && !pk.text[0], "лише префікс '`': порожньо");
		parseMicEInfo(h, t2, 2, 33, 26, 8, &pk);
		CHECK(pk.micE && !pk.text[0], "'`' + 1 байт: порожньо");
		parseMicEInfo(h, t3, 1, 33, 26, 8, &pk);
		CHECK(pk.micE && !pk.text[0], "лише '>': порожньо");
		parseMicEInfo(h, t1, 0, 33, 26, 8, &pk);
		CHECK(pk.micE && !pk.text[0], "коментаря нема взагалі");
	}
	{
		/* ВА1: керівні байти в кінці зрізаються й у звичайному (не Mic-E) коментарі */
		aprsAx25_t ax;
		aprsPacket_t q;
		uint8_t b[160];

		pf("N0CALL", 7, "!4903.50N/07201.75W>Hello\r\n", &ax, &q, b);
		CHECK(!strcmp(q.text, "Hello"), "CR LF зрізано в звичайному коментарі: «%s»", q.text);
		pf("N0CALL", 7, "!4903.50N/07201.75W>\r", &ax, &q, b);
		CHECK(!q.text[0], "лише CR -- порожній коментар");
	}
}

int main(void)
{
	aprsAx25_t ax;
	aprsPacket_t pk;
	uint8_t fr[400];

	printf("== AX.25 UI ==\n");
	{
		const char *inf = "!4903.50N/07201.75W-Test";
		int n = buildFrame(fr, "APRS", "N0CALL", 7, 2, 1, (const uint8_t *)inf, (int)strlen(inf));
		int ok = aprsAx25Parse(fr, (uint16_t)n, &ax);
		CHECK(ok && !strcmp(ax.src, "N0CALL-7") && !strcmp(ax.dst, "APRS") && !strcmp(ax.path, "WIDE1-1*,WIDE2-1") &&
				(ax.infoLen == strlen(inf)) && !memcmp(ax.info, inf, strlen(inf)),
				"джерело «%s», призначення «%s», шлях «%s», info %u Б", ok ? ax.src : "", ok ? ax.dst : "", ok ? ax.path : "", ok ? ax.infoLen : 0);

		n = buildFrame(fr, "APRS", "TEST", 0, 0, 0, (const uint8_t *)inf, (int)strlen(inf));
		ok = aprsAx25Parse(fr, (uint16_t)n, &ax);
		CHECK(ok && !strcmp(ax.src, "TEST") && (ax.path[0] == 0), "SSID 0 -- без суфікса; без цифіпітерів шлях порожній");

		n = buildFrame(fr, "APRS", "TEST", 15, 0, 0, (const uint8_t *)inf, (int)strlen(inf));
		ok = aprsAx25Parse(fr, (uint16_t)n, &ax);
		CHECK(ok && !strcmp(ax.src, "TEST-15"), "SSID 15 -> «%s»", ok ? ax.src : "");

		n = buildFrame(fr, "APRS", "TEST", 1, 0, 0, (const uint8_t *)inf, (int)strlen(inf));
		fr[14] = 0x04;   /* контроль не 0x03 */
		CHECK(!aprsAx25Parse(fr, (uint16_t)n, &ax), "контроль != 0x03 -- не UI");
		n = buildFrame(fr, "APRS", "TEST", 1, 0, 0, (const uint8_t *)inf, (int)strlen(inf));
		fr[15] = 0xCF;
		CHECK(!aprsAx25Parse(fr, (uint16_t)n, &ax), "PID != 0xF0 -- відмова");
		n = buildFrame(fr, "APRS", "TEST", 1, 0, 0, (const uint8_t *)inf, (int)strlen(inf));
		fr[7] = (uint8_t)('#' << 1);
		CHECK(!aprsAx25Parse(fr, (uint16_t)n, &ax), "сміття в позивному джерела -- відмова");
		CHECK(!aprsAx25Parse(fr, 10, &ax), "закороткий кадр -- відмова");
		/* немає біта «кінець адрес»: адреси не закінчуються */
		n = buildFrame(fr, "APRS", "TEST", 1, 0, 0, (const uint8_t *)inf, (int)strlen(inf));
		fr[13] &= 0xFE;
		CHECK(!aprsAx25Parse(fr, (uint16_t)n, &ax), "без кінця адрес -- відмова (а не вихід за межі)");
	}

	printf("== позиція: звичайна ==\n");
	{
		uint8_t b[300];
		parseInfo("APRS", "!4903.50N/07201.75W-Test 001234", &ax, &pk, b);
		CHECK((pk.type == APRS_T_POSITION) && pk.hasPos && !pk.micE && !pk.compressed &&
				(pk.latU == dm(49, 3, 50)) && (pk.lonU == -dm(72, 1, 75)) && !strcmp(pk.text, "Test 001234"),
				"«!» 49°03.50'N 072°01.75'W: %d %d, коментар «%s»", pk.latU, pk.lonU, pk.text);
		parseInfo("APRS", "=3325.64S/11207.74E>", &ax, &pk, b);
		CHECK((pk.type == APRS_T_POSITION) && (pk.latU == -dm(33, 25, 64)) && (pk.lonU == dm(112, 7, 74)) && (pk.text[0] == 0),
				"«=» півкулі S/E, довгота > 100: %d %d", pk.latU, pk.lonU);
		parseInfo("APRS", "/092345z4903.50N/07201.75W>comment", &ax, &pk, b);
		CHECK((pk.type == APRS_T_POSITION) && (pk.latU == dm(49, 3, 50)) && !strcmp(pk.text, "comment"), "«/» з відміткою часу DDHHMMz");
		parseInfo("APRS", "@092345z4903.50N/07201.75W>x", &ax, &pk, b);
		CHECK((pk.type == APRS_T_POSITION) && (pk.lonU == -dm(72, 1, 75)), "«@» з відміткою часу");
		parseInfo("APRS", "!49  .  N/072  .  W-", &ax, &pk, b);
		CHECK((pk.type == APRS_T_POSITION) && (pk.latU == dm(49, 0, 0)) && (pk.lonU == -dm(72, 0, 0)), "неоднозначність (пробіли) = 0");
		parseInfo("APRS", "!9100.00N/00000.00E-", &ax, &pk, b);
		CHECK(pk.type == APRS_T_OTHER, "широта > 90 -- відмова (інше)");
		parseInfo("APRS", "!4960.00N/07201.75W-", &ax, &pk, b);
		CHECK(pk.type == APRS_T_OTHER, "хвилини > 59 -- відмова");
		parseInfo("APRS", "!4903.50X/07201.75W-", &ax, &pk, b);
		CHECK(pk.type == APRS_T_OTHER, "півкуля не N/S -- відмова");
		parseInfo("APRS", "!4903.50N/0720", &ax, &pk, b);
		CHECK(pk.type == APRS_T_OTHER, "обірваний пакет -- відмова");
	}

	printf("== позиція: стиснута ==\n");
	{
		/* lat 49.5, lon -72.75 -> base91 за специфікацією: v = 380926 * (90 - lat), 190463 * (180 + lon) */
		uint8_t info[40], b[300];
		double lat = 49.5, lon = -72.75;
		int64_t vlat = (int64_t)(380926.0 * (90.0 - lat));
		int64_t vlon = (int64_t)(190463.0 * (180.0 + lon));
		info[0] = '!'; info[1] = '/';
		b91(&info[2], vlat); b91(&info[6], vlon);
		info[10] = '>'; info[11] = ' '; info[12] = 's'; info[13] = 'T';
		memcpy(&info[14], "compressed", 11);
		int n = buildFrame(b, "APRS", "TEST", 3, 0, 0, info, 14 + 10);
		int ok = aprsAx25Parse(b, (uint16_t)n, &ax);
		if (ok) { aprsPacketParse(&ax, &pk); }
		CHECK(ok && (pk.type == APRS_T_POSITION) && pk.compressed && pk.hasPos &&
				(abs(pk.latU - 49500000) <= 6) && (abs(pk.lonU + 72750000) <= 6) && !strcmp(pk.text, "compressed"),
				"стиснута 49.5 / -72.75: %d %d, коментар «%s»", ok ? pk.latU : 0, ok ? pk.lonU : 0, ok ? pk.text : "");
		/* символ у діапазоні A-Z таблиці (накладка) також стиснутий формат */
		info[1] = 'A';
		n = buildFrame(b, "APRS", "TEST", 3, 0, 0, info, 14 + 10);
		aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
		CHECK((pk.type == APRS_T_POSITION) && pk.compressed, "стиснута з накладкою 'A'");
		info[2] = 0x7F;   /* поза діапазоном base91 */
		n = buildFrame(b, "APRS", "TEST", 3, 0, 0, info, 14 + 10);
		aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
		CHECK(pk.type == APRS_T_OTHER, "символ поза base91 -- відмова");
	}

	printf("== позиція: Mic-E ==\n");
	testMicE("N/W, довгота 72", 49, 3, 50, 1, 72, 1, 75, 1);
	testMicE("N/E, довгота 112 (зсув +100)", 33, 25, 64, 1, 112, 7, 74, 0);
	testMicE("S/E, довгота 151", 33, 51, 12, 0, 151, 12, 34, 0);
	testMicE("N/E, довгота 5 (0-9°)", 52, 30, 7, 1, 5, 9, 99, 0);
	testMicE("N/W, довгота 0", 51, 28, 0, 1, 0, 0, 1, 1);
	testMicE("N/E, довгота 100..109", 10, 0, 0, 1, 105, 59, 99, 0);
	testMicE("N/E, довгота 179", 64, 59, 59, 1, 179, 30, 15, 0);
	testMicE("N/E, довгота 35 (десятки)", 50, 27, 0, 1, 30, 31, 0, 0);
	{
		/* Mic-E з поганим призначенням (не Mic-E символи) і закороткий info */
		uint8_t info[16] = { '`', 30 + 28, 20 + 28, 5 + 28, 40, 40, 40, '>', '/' };
		int n = buildFrame(fr, "ZZZZZZ", "TEST", 1, 0, 0, info, 9);
		aprsAx25Parse(fr, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
		CHECK(pk.type == APRS_T_OTHER || pk.hasPos, "призначення з 'Z' -- без падіння");
		n = buildFrame(fr, "?????1", "TEST", 1, 0, 0, info, 9);
		aprsAx25Parse(fr, (uint16_t)n, &ax);   /* '?' -- не позивний: Ax25Parse відмовить */
		n = buildFrame(fr, "ABCDEF", "TEST", 1, 0, 0, info, 5);
		aprsAx25Parse(fr, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
		CHECK(pk.type == APRS_T_OTHER, "Mic-E з обірваним info -- відмова");
	}

	printf("== R13: символ, курс, швидкість ==\n");
	{
		uint8_t b[300];
		/* звичайна: таблиця '/', код '>' , "090/045" на початку коментаря -- курс 90, 45 вузлів; з тексту прибрано */
		parseInfo("APRS", "!4903.50N/07201.75W>090/045Рух", &ax, &pk, b);
		CHECK((pk.type == APRS_T_POSITION) && (pk.symTable == '/') && (pk.symCode == '>') && (pk.course == 90) && (pk.speedKn == 45),
				"звичайна: символ %c%c, курс %u, швидкість %u", pk.symTable, pk.symCode, pk.course, pk.speedKn);
		CHECK(strncmp(pk.text, "090/045", 7) != 0 && pk.text[0] != 0, "«CCC/SSS» прибрано з коментаря: «%s»", pk.text);
		parseInfo("APRS", "!4903.50N\\07201.75W#comment", &ax, &pk, b);
		CHECK((pk.symTable == '\\') && (pk.symCode == '#') && (pk.course == 0) && (pk.speedKn == 0) && !strcmp(pk.text, "comment"), "альтернативна таблиця, руху нема");
		parseInfo("APRS", "!4903.50N/07201.75W-000/000", &ax, &pk, b);
		CHECK((pk.course == 0) && (pk.speedKn == 0) && (pk.text[0] == 0), "000/000 -- не рухається, поля нульові");
		parseInfo("APRS", "!4903.50N/07201.75W-12/345", &ax, &pk, b);
		CHECK((pk.course == 0) && (pk.speedKn == 0) && !strcmp(pk.text, "12/345"), "не схоже на CCC/SSS -- коментар не чіпаємо");
		parseInfo("APRS", "!4903.50N/07201.75W>361/010x", &ax, &pk, b);
		CHECK((pk.course == 0) && (pk.speedKn == 10), "курс 361 -- недійсний (0), швидкість лишається");
		parseInfo("APRS", ">status text", &ax, &pk, b);
		CHECK((pk.type == APRS_T_STATUS) && (pk.symCode == 0) && (pk.course == 0), "статус -- символу й руху нема");

		/* стиснута: символ '>' , cs = (c, s): курс = c*4, швидкість = 1.08^s - 1 */
		{
			uint8_t info[40];
			int n;

			memset(info, 0, sizeof(info));
			info[0] = '!'; info[1] = '/';
			b91(&info[2], (int64_t)(380926.0 * (90.0 - 49.5)));
			b91(&info[6], (int64_t)(190463.0 * (180.0 - 72.75)));
			info[10] = '>';
			info[11] = (uint8_t)(33 + 45);   /* c: 45*4 = 180° */
			info[12] = (uint8_t)(33 + 20);   /* s: 1.08^20 - 1 = 3.66 -> 4 вузли */
			info[13] = (uint8_t)(33 + 0x20);   /* T: тип NMEA GGA = 0 -- курс/швидкість діє (біти 3..4 == 0) */
			n = buildFrame(b, "APRS", "TEST", 3, 0, 0, info, 14);
			aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
			CHECK(pk.compressed && (pk.symTable == '/') && (pk.symCode == '>') && (pk.course == 180) && (pk.speedKn == 4),
					"стиснута: символ %c%c, курс %u, швидкість %u", pk.symTable, pk.symCode, pk.course, pk.speedKn);
			info[1] = 'A';   /* накладка 'A' */
			n = buildFrame(b, "APRS", "TEST", 3, 0, 0, info, 14);
			aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
			CHECK(pk.symTable == 'A', "накладка A збережена");
			info[1] = 'a';   /* накладка a..j = цифри 0..9 */
			n = buildFrame(b, "APRS", "TEST", 3, 0, 0, info, 14);
			aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
			CHECK(pk.symTable == '0', "накладка 'a' -> '0'");
			info[11] = ' ';   /* cs = "  " -- нема */
			n = buildFrame(b, "APRS", "TEST", 3, 0, 0, info, 14);
			aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
			CHECK((pk.course == 0) && (pk.speedKn == 0), "cs порожній -- руху нема");
			info[11] = (uint8_t)(33 + 45); info[13] = (uint8_t)(33 + 0x10);   /* T: біти 3..4 == 2 -- висота GGA */
			n = buildFrame(b, "APRS", "TEST", 3, 0, 0, info, 14);
			aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
			CHECK((pk.course == 0) && (pk.speedKn == 0), "T=висота GGA -- cs не курс/швидкість");
		}

		/* Mic-E: SP=12 DC=3 SE=40 (testMicE) -> швидкість 120 вузлів, курс 340; символ '>' таблиця '/' */
		{
			uint8_t info[32];
			char dst[8];
			int n;

			encodeMicE(dst, info, 49, 3, 50, 1, 72, 1, 75, 1);
			n = buildFrame(fr, dst, "TEST", 9, 0, 0, info, 9);
			aprsAx25Parse(fr, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
			CHECK(pk.micE && (pk.symCode == '>') && (pk.symTable == '/') && (pk.speedKn == 120) && (pk.course == 340),
					"Mic-E: символ %c%c, швидкість %u, курс %u", pk.symTable, pk.symCode, pk.speedKn, pk.course);
			info[4] = 28 + 82; info[5] = 28 + 45; info[6] = 28 + 90;   /* SP=82 -> 820+4=824 -> -800 = 24; DC=45 -> 4, 5; курс 500+90=590?-> 5*100+90=590 -400=190 */
			n = buildFrame(fr, dst, "TEST", 9, 0, 0, info, 9);
			aprsAx25Parse(fr, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
			CHECK((pk.speedKn == 24) && (pk.course == 190), "Mic-E: швидкість >= 800 і курс >= 400 -- поправки: %u/%u", pk.speedKn, pk.course);
		}
	}

	printf("== R13: вікно маяка: геометрія стрілки, режими, одиниці ==\n");
	{
		aprsArrow_t ar;
		static const struct { uint16_t b; int16_t tx, ty; } want[] =
		{
			{ 0, 80, 34 }, { 90, 110, 64 }, { 180, 80, 94 }, { 270, 50, 64 }, { 359, 79, 34 }, { 360, 80, 34 }, { 450, 110, 64 }
		};
		for (unsigned i = 0; i < sizeof(want) / sizeof(want[0]); i++)
		{
			aprsArrowGeom(&ar, 80, 64, 30, want[i].b);
			CHECK((ar.tx == want[i].tx) && (ar.ty == want[i].ty), "азимут %u: вістря (%d,%d), чекаємо (%d,%d)", want[i].b, ar.tx, ar.ty, want[i].tx, want[i].ty);
		}
		/* 45° -- діагональ: вістря в правому верхньому квадранті */
		aprsArrowGeom(&ar, 80, 64, 30, 45);
		CHECK((ar.tx == 101) && (ar.ty == 43), "азимут 45: (%d,%d)", ar.tx, ar.ty);

		/* крила: для півночі -- симетричні, нижче вістря, ліве лівіше за вістря */
		aprsArrowGeom(&ar, 80, 64, 30, 0);
		CHECK((ar.lx < ar.tx) && (ar.rx > ar.tx) && (ar.lx + ar.rx == 2 * ar.tx) && (ar.ly == ar.ry) && (ar.ly > ar.ty),
				"північ: крила (%d,%d) і (%d,%d) від вістря (%d,%d)", ar.lx, ar.ly, ar.rx, ar.ry, ar.tx, ar.ty);
		/* схід: вістря справа, крила лівіше від нього, одне вище, інше нижче */
		aprsArrowGeom(&ar, 80, 64, 30, 90);
		CHECK((ar.lx < ar.tx) && (ar.rx < ar.tx) && (ar.ly != ar.ry) && (ar.ly + ar.ry == 2 * ar.ty), "схід: крила (%d,%d) і (%d,%d)", ar.lx, ar.ly, ar.rx, ar.ry);
		/* південь і захід: вістря далі від центру, крила ближче до центру, ніж вістря */
		aprsArrowGeom(&ar, 80, 64, 30, 180);
		CHECK((ar.ly < ar.ty) && (ar.ry < ar.ty), "південь: крила вище вістря");
		aprsArrowGeom(&ar, 80, 64, 30, 270);
		CHECK((ar.lx > ar.tx) && (ar.rx > ar.tx), "захід: крила правіше вістря");
		/* довжина крила не менше 4 px навіть для крихітної стрілки; усі точки в межах 3*len від центру (без виходу за екран при len<=30) */
		aprsArrowGeom(&ar, 80, 64, 6, 135);
		CHECK((abs(ar.lx - ar.tx) + abs(ar.ly - ar.ty)) >= 3, "мала стрілка: крило видно");
		/* усі 360 азимутів: вістря на відстані len +-1 від центру */
		{
			int bad = 0;

			for (int d = 0; d < 360; d++)
			{
				aprsArrowGeom(&ar, 80, 64, 30, (uint16_t)d);
				int dx = ar.tx - 80, dy = ar.ty - 64;
				int r2 = dx * dx + dy * dy;

				if ((r2 < 29 * 29) || (r2 > 31 * 31)) { bad++; }
			}
			CHECK(bad == 0, "вістря на колі len=30 для всіх азимутів (поза допуском: %d)", bad);
		}

		/* нульова відстань / нема геопозиції */
		CHECK(aprsBeaconArrowVisible(true, 5) && !aprsBeaconArrowVisible(true, 0) && !aprsBeaconArrowVisible(false, 1000), "стрілка: є геопозиція й відстань > 0");

		/* режими вікна */
		{
			aprsPacket_t p;

			memset(&p, 0, sizeof(p));
			p.type = APRS_T_POSITION; p.hasPos = true;
			CHECK(aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &p, false) && aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &p, true), "«Усі»: кожен позиційний");
			CHECK(!aprsBeaconWindowWanted(APRS_BCNWIN_NEW, &p, false) && aprsBeaconWindowWanted(APRS_BCNWIN_NEW, &p, true), "«Лише нові»: тільки нова станція");
			CHECK(!aprsBeaconWindowWanted(APRS_BCNWIN_OFF, &p, true), "«Вимк.»: ніколи");
			p.micE = true;
			CHECK(aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &p, false), "Mic-E теж");
			p.compressed = true; p.micE = false;
			CHECK(aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &p, false), "стиснута теж");
			p.hasPos = false;
			CHECK(aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &p, true) && !aprsBeaconWindowWanted(APRS_BCNWIN_OFF, &p, true), "R13: пакет без координат -- вікно є (без стрілки), режим «Вимк.» його вимикає");
			p.hasPos = true; p.type = APRS_T_STATUS;
			CHECK(!aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &p, true), "статус -- вікна нема");
			p.type = APRS_T_MESSAGE;
			CHECK(!aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &p, true), "повідомлення -- вікна маяка нема");
			CHECK(!aprsBeaconWindowWanted(APRS_BCNWIN_ALL, NULL, true), "NULL -- без падіння");
		}
		/* R13: справжні кадри: з координатами, без них (сміття після '!'), і рішення вікна/стрілки в обох станах "нашої позиції" */
		{
			uint8_t bb[300];
			aprsAx25_t ax2;
			aprsPacket_t pk2;

			parseInfo("APRS", "!4903.50N/07201.75W>/A=001234 mobile", &ax2, &pk2, bb);
			CHECK((pk2.type == APRS_T_POSITION) && pk2.hasPos && (pk2.symCode == '>') && aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &pk2, false),
					"пакет з позицією -- вікно, символ %c%c", pk2.symTable, pk2.symCode);
			CHECK(aprsBeaconArrowVisible(true, 12345U) && !aprsBeaconArrowVisible(false, 12345U), "наша позиція невідома (hasGeo=false) -- стрілки й відстані нема");
			parseInfo("APRS", "!xxxxxxxxxxxxxxxxxxx", &ax2, &pk2, bb);
			CHECK(!pk2.hasPos && !aprsBeaconArrowVisible(pk2.hasPos, 1000U), "пакет без позиції: hasPos=0 -- стрілки нема (тип %d)", (int)pk2.type);
			CHECK((pk2.type != APRS_T_POSITION) || aprsBeaconWindowWanted(APRS_BCNWIN_ALL, &pk2, true), "позиційний пакет без координат -- вікно без стрілки, не падіння");
		}
		CHECK((aprsKnotsToKmh(0) == 0) && (aprsKnotsToKmh(1) == 2) && (aprsKnotsToKmh(10) == 19) && (aprsKnotsToKmh(45) == 83) && (aprsKnotsToKmh(120) == 222), "вузли -> км/год");
	}

	printf("== повідомлення ==\n");
	{
		uint8_t b[300];
		parseInfo("APRS", ":N0CALL-7 :Hello there{123", &ax, &pk, b);
		CHECK((pk.type == APRS_T_MESSAGE) && !strcmp(pk.msgTo, "N0CALL-7") && !strcmp(pk.msgId, "123") && !strcmp(pk.text, "Hello there") && !pk.msgAck,
				"адресат «%s», номер «%s», текст «%s»", pk.msgTo, pk.msgId, pk.text);
		CHECK(aprsMsgIsForUs(pk.msgTo, "N0CALL", 7), "це нам: N0CALL-7");
		CHECK(!aprsMsgIsForUs(pk.msgTo, "N0CALL", 9), "не нам: інший SSID");
		CHECK(!aprsMsgIsForUs(pk.msgTo, "N0CALX", 7), "не нам: інший позивний");
		CHECK(aprsMsgIsForUs(pk.msgTo, "n0call  ", 7), "регістр і хвостові пробіли власного позивного ігноруються");
		parseInfo("APRS", ":N0CALL   :no id here", &ax, &pk, b);
		CHECK((pk.type == APRS_T_MESSAGE) && (pk.msgId[0] == 0) && !strcmp(pk.msgTo, "N0CALL"), "без номера; адресат без SSID");
		CHECK(aprsMsgIsForUs(pk.msgTo, "N0CALL", 0), "SSID 0: «N0CALL» -- нам");
		CHECK(!aprsMsgIsForUs(pk.msgTo, "N0CALL", 7), "адресат без SSID -- не для N0CALL-7");
		parseInfo("APRS", ":N0CALL-0 :zero", &ax, &pk, b);
		CHECK(aprsMsgIsForUs(pk.msgTo, "N0CALL", 0), "SSID 0: «N0CALL-0» -- теж нам");
		parseInfo("APRS", ":N0CALL-7 :ack123", &ax, &pk, b);
		CHECK((pk.type == APRS_T_MESSAGE) && pk.msgAck, "ack -- msgAck");
		parseInfo("APRS", ":N0CALL-7 :rej9", &ax, &pk, b);
		CHECK((pk.type == APRS_T_MESSAGE) && pk.msgAck, "rej -- msgAck");
		parseInfo("APRS", ":N0CALL-7 :acknowledged the thing{5", &ax, &pk, b);
		CHECK((pk.type == APRS_T_MESSAGE) && !pk.msgAck, "звичайний текст на 'ack...' з номером -- не ack");
		parseInfo("APRS", ":BLN1     :Bulletin text", &ax, &pk, b);
		CHECK((pk.type == APRS_T_MESSAGE) && !strcmp(pk.msgTo, "BLN1") && !aprsMsgIsForUs(pk.msgTo, "N0CALL", 7), "бюлетень -- не нам");
		parseInfo("APRS", ":N0CALL-7 text without colon-position", &ax, &pk, b);
		CHECK(pk.type == APRS_T_OTHER, "формат повідомлення зіпсований -- інше");
		parseInfo("APRS", ":N0CALL-7 :x{123456", &ax, &pk, b);
		CHECK((pk.type == APRS_T_MESSAGE) && (pk.msgId[0] == 0), "номер довший за 5 -- не номер");
	}

	printf("== статус, інше ==\n");
	{
		uint8_t b[300];
		parseInfo("APRS", ">On the air", &ax, &pk, b);
		CHECK((pk.type == APRS_T_STATUS) && !strcmp(pk.text, "On the air"), "статус");
		parseInfo("APRS", ">092345zOn the air", &ax, &pk, b);
		CHECK((pk.type == APRS_T_STATUS) && !strcmp(pk.text, "On the air"), "статус з відміткою часу");
		parseInfo("APRS", ";LEADER   *092345z4903.50N/07201.75W-", &ax, &pk, b);
		CHECK((pk.type == APRS_T_POSITION) && pk.hasPos && !pk.killed && (pk.symCode == '-') && !strncmp(pk.text, "LEADER", 6), "R14: об'єкт -- позиція (було «інше»)");
		parseInfo("APRS", "_10090556c220s004g005t077", &ax, &pk, b);
		CHECK(pk.type == APRS_T_OTHER, "погода -- «інше»");
		parseInfo("APRS", "T#005,199,000,255,073,123,01101001", &ax, &pk, b);
		CHECK(pk.type == APRS_T_OTHER, "телеметрія -- «інше»");
		parseInfo("APRS", "", &ax, &pk, b);   /* порожній info */
		CHECK(pk.type == APRS_T_OTHER, "порожній info");
	}

	printf("== текст: UTF-8 і cp1251 ==\n");
	{
		char out[80];
		/* «Привіт» у UTF-8 */
		const uint8_t u8[] = { 0xD0, 0x9F, 0xD1, 0x80, 0xD0, 0xB8, 0xD0, 0xB2, 0xD1, 0x96, 0xD1, 0x82 };
		CHECK(aprsIsUtf8(u8, sizeof(u8)), "«Привіт» в UTF-8 -- коректний UTF-8");
		aprsDecodeText(u8, sizeof(u8), out, sizeof(out));
		/* cp1251: П=CF р=F0 и=E8 в=E2 і=B3 т=F2 */
		const uint8_t want[] = { 0xCF, 0xF0, 0xE8, 0xE2, 0xB3, 0xF2, 0 };
		CHECK(!strcmp(out, (const char *)want), "UTF-8 «Привіт» -> байти cp1251");

		/* те саме, уже в cp1251 (не коректний UTF-8: 0xCF 0xF0 ...) */
		const uint8_t c1[] = { 0xCF, 0xF0, 0xE8, 0xE2, 0xB3, 0xF2 };
		CHECK(!aprsIsUtf8(c1, sizeof(c1)), "cp1251-байти -- не UTF-8");
		aprsDecodeText(c1, sizeof(c1), out, sizeof(out));
		CHECK(!strcmp(out, (const char *)want), "cp1251 проходить як є");

		/* ґ Ґ є ї в UTF-8 */
		const uint8_t spec[] = { 0xD2, 0x91, 0xD2, 0x90, 0xD1, 0x94, 0xD1, 0x97 };
		aprsDecodeText(spec, sizeof(spec), out, sizeof(out));
		const uint8_t wantS[] = { 0xB4, 0xA5, 0xBA, 0xBF, 0 };
		CHECK(!strcmp(out, (const char *)wantS), "ґ Ґ є ї: UTF-8 -> cp1251 (0xB4 0xA5 0xBA 0xBF)");

		/* змішано: ASCII + UTF-8 + керівні */
		const uint8_t mix[] = { 'H', 'i', ' ', 0xD0, 0x96, '\r', '\n', 'x', ' ', ' ' };
		aprsDecodeText(mix, sizeof(mix), out, sizeof(out));
		CHECK(!strcmp(out, "Hi \xC6  x"), "ASCII + «Ж» + CR LF -> пробіли, хвостові пробіли знято (%s)", out);

		/* емодзі (4 байти) -> '?', символ поза cp1251 (U+20AC €) -> '?' або символ таблиці */
		const uint8_t emo[] = { 'o', 'k', ' ', 0xF0, 0x9F, 0x98, 0x80 };
		CHECK(aprsIsUtf8(emo, sizeof(emo)), "емодзі -- коректний UTF-8");
		aprsDecodeText(emo, sizeof(emo), out, sizeof(out));
		CHECK(!strcmp(out, "ok ?"), "емодзі -> «?» (%s)", out);

		/* недійсний UTF-8: обірвана послідовність, надмірне кодування, сурогат, 0xC0/0xFF */
		const uint8_t bad1[] = { 0xD0 };
		const uint8_t bad2[] = { 0xC0, 0x80 };
		const uint8_t bad3[] = { 0xED, 0xA0, 0x80 };
		const uint8_t bad4[] = { 0xFF };
		const uint8_t bad5[] = { 0xE0, 0x80, 0x80 };
		CHECK(!aprsIsUtf8(bad1, 1) && !aprsIsUtf8(bad2, 2) && !aprsIsUtf8(bad3, 3) && !aprsIsUtf8(bad4, 1) && !aprsIsUtf8(bad5, 3),
				"обірваний / надмірний / сурогат / 0xFF -- не UTF-8");
		CHECK(aprsIsUtf8((const uint8_t *)"plain ASCII", 11), "чистий ASCII -- UTF-8");

		/* повідомлення з кирилицею цілим кадром */
		uint8_t b[300];
		uint8_t info[60];
		int il = 0;
		memcpy(info, ":N0CALL-7 :", 11); il = 11;
		memcpy(&info[il], u8, sizeof(u8)); il += (int)sizeof(u8);
		memcpy(&info[il], "{7", 2); il += 2;
		int n = buildFrame(b, "APRS", "TEST", 2, 0, 0, info, il);
		aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
		CHECK((pk.type == APRS_T_MESSAGE) && !strcmp(pk.text, (const char *)want) && !strcmp(pk.msgId, "7"), "повідомлення «Привіт{7» UTF-8 -> cp1251, номер 7");
		il = 11;
		memcpy(&info[il], c1, sizeof(c1)); il += (int)sizeof(c1);
		n = buildFrame(b, "APRS", "TEST", 2, 0, 0, info, il);
		aprsAx25Parse(b, (uint16_t)n, &ax); aprsPacketParse(&ax, &pk);
		CHECK((pk.type == APRS_T_MESSAGE) && !strcmp(pk.text, (const char *)want), "повідомлення «Привіт» у cp1251 -- читається");
	}

	printf("== дедуплікація ==\n");
	{
		static aprsRxDb_t db;
		uint8_t b[300];
		aprsAx25_t a1, a2;
		uint8_t b2[300];
		aprsDbInit(&db);
		int n = buildFrame(b, "APRS", "TEST", 1, 0, 0, (const uint8_t *)"!4903.50N/07201.75W-A", 21);
		aprsAx25Parse(b, (uint16_t)n, &a1);
		CHECK(!aprsDbIsDuplicate(&db, &a1, 1000), "перший пакет -- не дублікат");
		CHECK(aprsDbIsDuplicate(&db, &a1, 1000 + 29999), "той самий через 29,999 с -- дублікат");
		CHECK(!aprsDbIsDuplicate(&db, &a1, 1000 + 30001), "через 30,001 с від першого -- знову новий (вікно не продовжується дублікатом)");
		n = buildFrame(b2, "APRS", "TEST", 1, 0, 0, (const uint8_t *)"!4903.50N/07201.75W-B", 21);
		aprsAx25Parse(b2, (uint16_t)n, &a2);
		CHECK(!aprsDbIsDuplicate(&db, &a2, 1000 + 30002), "інший info -- не дублікат");
		/* той самий info, інша станція */
		n = buildFrame(b2, "APRS", "TEST", 2, 0, 0, (const uint8_t *)"!4903.50N/07201.75W-B", 21);
		aprsAx25Parse(b2, (uint16_t)n, &a2);
		CHECK(!aprsDbIsDuplicate(&db, &a2, 1000 + 30003), "та сама info, інше джерело (SSID) -- не дублікат");
		/* той самий пакет іншим шляхом (цифіпітер) -- дублікат */
		n = buildFrame(b2, "APRS", "TEST", 1, 1, 1, (const uint8_t *)"!4903.50N/07201.75W-A", 21);
		aprsAx25Parse(b2, (uint16_t)n, &a2);
		CHECK(aprsDbIsDuplicate(&db, &a2, 1000 + 30002 + 100), "той самий пакет через цифіпітер -- дублікат (шлях у хеш не входить)");
		/* переповнення лічильника мс (49 діб) */
		aprsDbInit(&db);
		CHECK(!aprsDbIsDuplicate(&db, &a1, 0xFFFFFF00UL), "перехід через 2^32 мс: перший");
		CHECK(aprsDbIsDuplicate(&db, &a1, 0xFFFFFF00UL + 5000UL), "... дублікат через 5 с (після переходу)");

		/* повтори повідомлень без ACK */
		aprsDbInit(&db);
		uint8_t mi[] = ":N0CALL-7 :hi{1";
		n = buildFrame(b, "APRS", "TEST", 1, 0, 0, mi, (int)strlen((char *)mi));
		aprsAx25Parse(b, (uint16_t)n, &a1);
		aprsPacketParse(&a1, &pk);
		CHECK(!aprsDbMsgSeen(&db, &a1, &pk, 5000), "повідомлення вперше");
		CHECK(aprsDbMsgSeen(&db, &a1, &pk, 5000 + 120000), "повтор через 2 хв -- вже бачили");
		CHECK(!aprsDbMsgSeen(&db, &a1, &pk, 5000 + 600001), "через 10 хв 0,001 с -- знову");
	}

	printf("== список станцій ==\n");
	{
		static aprsRxDb_t db;
		aprsDbInit(&db);
		aprsPacket_t p;
		aprsAx25_t a;
		uint8_t b[200];
		char call[8];

		memset(&p, 0, sizeof(p));
		p.type = APRS_T_POSITION; p.hasPos = true; p.latU = 50000000; p.lonU = 30000000;
		strcpy(p.text, "first");
		for (int i = 0; i < APRS_STATIONS_MAX; i++)
		{
			snprintf(call, sizeof(call), "ST%d", i);
			int n = buildFrame(b, "APRS", call, 1, 0, 0, (const uint8_t *)"!", 1);
			aprsAx25Parse(b, (uint16_t)n, &a);
			aprsDbUpdate(&db, &a, &p, 1000UL + (uint32_t)i * 100UL);
		}
		CHECK(aprsDbCount(&db) == APRS_STATIONS_MAX, "16 станцій записано (%d)", aprsDbCount(&db));
		/* оновити ST0 (найстаріша) -- вона має стати найновішою і НЕ замінюватись */
		int n = buildFrame(b, "APRS", "ST0", 1, 0, 0, (const uint8_t *)"!", 1);
		aprsAx25Parse(b, (uint16_t)n, &a);
		aprsStation_t *s0 = aprsDbUpdate(&db, &a, &p, 5000);
		CHECK(!strcmp(s0->call, "ST0-1") && (s0->count == 2) && (aprsDbCount(&db) == APRS_STATIONS_MAX), "ST0-1 оновлено (лічильник %u), станцій %d", s0->count, aprsDbCount(&db));
		/* 17-та станція замінює НАЙСТАРІШУ: тепер це ST1-1 (lastMs 1100) */
		n = buildFrame(b, "APRS", "NEW", 0, 0, 0, (const uint8_t *)"!", 1);
		aprsAx25Parse(b, (uint16_t)n, &a);
		p.type = APRS_T_STATUS; p.hasPos = false; strcpy(p.text, "status");
		aprsStation_t *sn = aprsDbUpdate(&db, &a, &p, 6000);
		int has1 = 0, hasNew = 0;
		for (int i = 0; i < APRS_STATIONS_MAX; i++)
		{
			if (!strcmp(db.st[i].call, "ST1-1")) { has1 = 1; }
			if (!strcmp(db.st[i].call, "NEW")) { hasNew = 1; }
		}
		CHECK(!has1 && hasNew && (aprsDbCount(&db) == APRS_STATIONS_MAX) && (sn->count == 1) && !(sn->flags & APRS_ST_HASPOS),
				"17-та замінила найстарішу (ST1-1), записів лишилось 16; нова без позиції");
		/* порядок: найновіша -- NEW (6000), далі ST0-1 (5000), далі ST15-1 (2500) ... */
		const aprsStation_t *x0 = aprsDbNth(&db, 0, 7000);
		const aprsStation_t *x1 = aprsDbNth(&db, 1, 7000);
		const aprsStation_t *x2 = aprsDbNth(&db, 2, 7000);
		const aprsStation_t *x15 = aprsDbNth(&db, 15, 7000);
		CHECK(x0 && x1 && x2 && x15 && !strcmp(x0->call, "NEW") && !strcmp(x1->call, "ST0-1") && !strcmp(x2->call, "ST15-1") && !strcmp(x15->call, "ST2-1"),
				"порядок за новизною: %s, %s, %s, ..., %s", x0 ? x0->call : "?", x1 ? x1->call : "?", x2 ? x2->call : "?", x15 ? x15->call : "?");
		CHECK(aprsDbNth(&db, 16, 7000) == NULL && aprsDbNth(&db, -1, 7000) == NULL, "поза межами -- NULL");
		/* текст і позиція не затираються порожнім пакетом */
		n = buildFrame(b, "APRS", "ST3", 1, 0, 0, (const uint8_t *)"!", 1);
		aprsAx25Parse(b, (uint16_t)n, &a);
		memset(&p, 0, sizeof(p)); p.type = APRS_T_OTHER;
		aprsStation_t *s3 = aprsDbUpdate(&db, &a, &p, 7000);
		CHECK((s3->flags & APRS_ST_HASPOS) && !strcmp(s3->text, "first") && (s3->type == APRS_T_OTHER), "порожній пакет не стирає позицію й коментар, тип -- останній");
		/* довгий коментар обрізається до APRS_STATION_TEXT-1 */
		memset(&p, 0, sizeof(p)); p.type = APRS_T_STATUS;
		memset(p.text, 'x', 70);
		aprsStation_t *s4 = aprsDbUpdate(&db, &a, &p, 7100);
		CHECK(strlen(s4->text) == APRS_STATION_TEXT - 1U, "довгий текст обрізано до %u", (unsigned)strlen(s4->text));
		/* перехід лічильника мс: вік рахується за модулем 2^32 */
		aprsDbInit(&db);
		memset(&p, 0, sizeof(p)); p.type = APRS_T_STATUS;
		n = buildFrame(b, "APRS", "OLD", 1, 0, 0, (const uint8_t *)"!", 1); aprsAx25Parse(b, (uint16_t)n, &a);
		aprsDbUpdate(&db, &a, &p, 0xFFFFFFF0UL);
		n = buildFrame(b, "APRS", "NEWER", 1, 0, 0, (const uint8_t *)"!", 1); aprsAx25Parse(b, (uint16_t)n, &a);
		aprsDbUpdate(&db, &a, &p, 20UL);
		CHECK(!strcmp(aprsDbNth(&db, 0, 100)->call, "NEWER-1"), "порядок після переходу лічильника мс");
	}

	printf("== R11-fix: third-party (i-gate, префікс '}') ==\n");
	{
		uint8_t b[400];
		const char *m = "}UW5ELK-5>APDR16,TCPIP,SP5WWP-10*::US5EX-7  :test{5";
		const uint8_t *infoBefore;
		int u;

		/* БАЗОВА лінія -- те, що було до виправлення: без розгортання пакет «інше», а джерело -- шлюз */
		{
			int n = buildFrame(b, "APRS", "SP5WWP", 10, 0, 0, (const uint8_t *)m, (int)strlen(m));
			CHECK(aprsAx25Parse(b, (uint16_t)n, &ax), "кадр шлюзу розібрано як AX.25");
			aprsPacketParse(&ax, &pk);
			CHECK((pk.type == APRS_T_OTHER) && !strcmp(ax.src, "SP5WWP-10") && !ax.tp,
					"без розгортання: «інше», джерело -- шлюз «%s» (це й був баг: банер «пакет від gateway»)", ax.src);
		}

		/* повідомлення нам, латиниця (пакет Богдана: UW5ELK-5 -> US5EX-7 через APRS-IS) */
		u = tpParse(m, &ax, &pk, b);
		CHECK(u == 1 && ax.tp, "розгорнуто");
		CHECK(!strcmp(ax.src, "UW5ELK-5") && !strcmp(ax.dst, "APDR16") && !strcmp(ax.path, "TCPIP,SP5WWP-10*") && !strcmp(ax.gate, "SP5WWP-10"),
				"справжній відправник «%s», призначення «%s», шлях «%s», шлюз «%s»", ax.src, ax.dst, ax.path, ax.gate);
		CHECK((pk.type == APRS_T_MESSAGE) && !pk.msgAck && !strcmp(pk.msgTo, "US5EX-7") && !strcmp(pk.msgId, "5") && !strcmp(pk.text, "test"),
				"повідомлення: адресат «%s», номер «%s», текст «%s»", pk.msgTo, pk.msgId, pk.text);
		CHECK(aprsMsgIsForUs(pk.msgTo, "US5EX", 7), "... і воно НАМ (US5EX-7)");
		CHECK(!aprsMsgIsForUs(pk.msgTo, "US5EX", 0) && !aprsMsgIsForUs(pk.msgTo, "US5EX", 1), "... а US5EX і US5EX-1 -- ні");

		/* ack від справжнього відправника через шлюз */
		u = tpParse("}UW5ELK-5>APDR16,TCPIP,SP5WWP-10*::US5EX-7  :ack12", &ax, &pk, b);
		CHECK(u == 1 && !strcmp(ax.src, "UW5ELK-5") && (pk.type == APRS_T_MESSAGE) && pk.msgAck, "ack через шлюз: msgAck, джерело -- справжнє");

		/* кирилиця UTF-8 («Привіт ґ Ґ є ї») через шлюз */
		{
			static const uint8_t head[] = "}UW5ELK-5>APDR16,TCPIP,SP5WWP-10*::US5EX-7  :";
			static const uint8_t body[] = { 0xD0, 0x9F, 0xD1, 0x80, 0xD0, 0xB8, 0xD0, 0xB2, 0xD1, 0x96, 0xD1, 0x82, ' ',
					0xD2, 0x91, 0xD2, 0x90, 0xD1, 0x94, 0xD1, 0x97, '{', '7' };
			static const uint8_t want[] = { 0xCF, 0xF0, 0xE8, 0xE2, 0xB3, 0xF2, ' ', 0xB4, 0xA5, 0xBA, 0xBF, 0 };
			uint8_t inf[120];
			int hl = (int)sizeof(head) - 1;

			memcpy(inf, head, (size_t)hl);
			memcpy(inf + hl, body, sizeof(body));
			u = tpParseBytes(inf, hl + (int)sizeof(body), &ax, &pk, b);
			CHECK(u == 1 && (pk.type == APRS_T_MESSAGE) && !strcmp(pk.msgId, "7") && !strcmp(pk.text, (const char *)want),
					"кирилиця UTF-8 -> cp1251 (Привіт ґ Ґ є ї), номер «%s»", pk.msgId);
		}

		/* позиція через шлюз */
		u = tpParse("}N0CALL-9>APRS,TCPIP,SP5WWP-10*:!4903.50N/07201.75W-Test", &ax, &pk, b);
		CHECK(u == 1 && !strcmp(ax.src, "N0CALL-9") && (pk.type == APRS_T_POSITION) && pk.hasPos && (pk.latU == dm(49, 3, 50)) &&
				(pk.lonU == -dm(72, 1, 75)) && !strcmp(pk.text, "Test"), "позиція через шлюз: %d %d, «%s»", pk.latU, pk.lonU, pk.text);
		u = tpParse("}N0CALL-9>APRS,TCPIP*:>On the air", &ax, &pk, b);
		CHECK(u == 1 && (pk.type == APRS_T_STATUS) && !strcmp(pk.text, "On the air"), "статус через шлюз");

		/* Mic-E через шлюз: призначення ВКЛАДЕНОГО кадру (а не шлюзу) несе широту */
		{
			uint8_t info[32], inf[120];
			char dst[8];
			int hl;

			encodeMicE(dst, info, 49, 3, 50, 1, 72, 1, 75, 1);
			strcpy((char *)&info[9], "Mic-E test");
			hl = snprintf((char *)inf, sizeof(inf), "}N0CALL-9>%s,TCPIP,SP5WWP-10*:", dst);
			memcpy(inf + hl, info, 9 + 10);
			u = tpParseBytes(inf, hl + 9 + 10, &ax, &pk, b);
			CHECK(u == 1 && !strcmp(ax.dst, dst) && (pk.type == APRS_T_POSITION) && pk.micE && (pk.latU == dm(49, 3, 50)) && (pk.lonU == -dm(72, 1, 75)) &&
					!strcmp(pk.text, "Mic-E test"), "Mic-E через шлюз: %d %d, «%s»", pk.latU, pk.lonU, pk.text);
		}

		/* рівно ОДИН рівень: подвійне '}' не розгортається вдруге -- «інше» */
		u = tpParse("}A1B>APRS,TCPIP*:}C2D>APRS,TCPIP*:!4903.50N/07201.75W-x", &ax, &pk, b);
		CHECK(u == 1 && (pk.type == APRS_T_OTHER) && !strcmp(ax.src, "A1B") && ax.tp, "подвійне '}': розгорнуто один раз, пакет -- «інше», джерело «%s»", ax.src);
		infoBefore = ax.info;
		CHECK(!aprsAx25Unwrap(&ax) && (ax.info == infoBefore) && !strcmp(ax.src, "A1B"), "повторний Unwrap -- відмова, кадр не змінився");

		/* порожнє вкладене info: розгортається, пакет «інше» */
		u = tpParse("}UW5ELK-5>APRS,TCPIP*:", &ax, &pk, b);
		CHECK(u == 1 && (ax.infoLen == 0) && (pk.type == APRS_T_OTHER) && !strcmp(ax.src, "UW5ELK-5"), "порожнє вкладене info");

		/* SSID вкладеного позивного: -0 знімається, -1/-7/-15 лишаються, -07/-16/-00 -- відмова */
		u = tpParse("}UW5ELK-0>APRS:>x", &ax, &pk, b);
		CHECK(u == 1 && !strcmp(ax.src, "UW5ELK"), "«-0» -> без суфікса («%s»)", ax.src);
		u = tpParse("}uw5elk-1>aprs:>x", &ax, &pk, b);
		CHECK(u == 1 && !strcmp(ax.src, "UW5ELK-1") && !strcmp(ax.dst, "APRS"), "нижній регістр -> ВЕРХНІЙ, «-1»");
		u = tpParse("}UW5ELK-7>APRS:>x", &ax, &pk, b);
		CHECK(u == 1 && !strcmp(ax.src, "UW5ELK-7"), "«-7»");
		u = tpParse("}UW5ELK-15>APRS:>x", &ax, &pk, b);
		CHECK(u == 1 && !strcmp(ax.src, "UW5ELK-15"), "«-15»");
		CHECK(tpParse("}UW5ELK-07>APRS:>x", &ax, &pk, b) == 0, "«-07» -- відмова");
		CHECK(tpParse("}UW5ELK-16>APRS:>x", &ax, &pk, b) == 0, "«-16» -- відмова");
		CHECK(tpParse("}UW5ELK-00>APRS:>x", &ax, &pk, b) == 0, "«-00» -- відмова");
		CHECK(tpParse("}UW5ELK->APRS:>x", &ax, &pk, b) == 0, "«-» без цифри -- відмова");
		CHECK(tpParse("}UW5ELKX>APRS:>x", &ax, &pk, b) == 0, "позивний довший за 6 -- відмова");

		/* обрізані й побиті заголовки: false, кадр шлюзу НЕ змінений, пакет -- «інше», жодного виходу за межі */
		{
			static const char *const bad[] = {
				"}", "}U", "}UW5ELK-5", "}UW5ELK-5>", "}UW5ELK-5>APDR16", "}UW5ELK-5>APDR16,TCPIP,SP5WWP-10*",
				"}>APRS:x", "}UW5ELK-5>:x", "}UW5ELK 5>APRS:x", "}UW5#LK>APRS:x", "}UW5ELK-5>AP RS:x",
				"}UW5ELK-5>APRS,TC PIP:x", "}UW5ELK-5>APRS,TCP\x01IP:x", "}UW5ELK-5>APRS,TCPIP",
				"}UW5ELK-5,APRS:x", "}:x", "}>:"
			};
			int allBad = 1, allSame = 1, allOther = 1;

			for (size_t k = 0; k < sizeof(bad) / sizeof(bad[0]); k++)
			{
				u = tpParse(bad[k], &ax, &pk, b);
				if (u != 0) { allBad = 0; printf("   [не відмовило: %s]\n", bad[k]); }
				if (strcmp(ax.src, "SP5WWP-10") || ax.tp) { allSame = 0; }
				if (pk.type != APRS_T_OTHER) { allOther = 0; }
			}
			CHECK(allBad, "обрізані/побиті заголовки -- Unwrap відмовляє");
			CHECK(allSame, "... кадр шлюзу не змінено (джерело лишається шлюзом, tp = false)");
			CHECK(allOther, "... пакет -- «інше»");
		}
		{
			/* заголовок без ':' довший за ліміт (120 Б) -- відмова, а не читання за межами; довгий, але в межах ліміту шлях -- обрізається */
			uint8_t inf[300];
			memset(inf, 'A', sizeof(inf));
			inf[0] = '}'; inf[1] = 'A'; inf[2] = '>'; inf[3] = 'B'; inf[4] = ',';
			CHECK(tpParseBytes(inf, 250, &ax, &pk, b) == 0, "шлях без ':' на 250 Б -- відмова");
			inf[200] = ':';
			CHECK(tpParseBytes(inf, 250, &ax, &pk, b) == 0, "':' за межею 120 Б заголовка -- відмова");
			memset(inf, 'A', sizeof(inf));
			inf[0] = '}'; inf[1] = 'A'; inf[2] = '>'; inf[3] = 'B'; inf[4] = ',';
			inf[100] = ':';
			u = tpParseBytes(inf, 120, &ax, &pk, b);
			CHECK(u == 1 && (strlen(ax.path) < sizeof(ax.path)) && (ax.infoLen == 19), "довгий шлях: обрізається до %u, info %u Б", (unsigned)strlen(ax.path), (unsigned)ax.infoLen);
		}
		{
			/* псевдовипадковий фарш після '}' (фіксоване зерно): не падати; якщо розгорнуто -- info усередині кадру */
			uint32_t seed = 12345U;
			int outside = 0, unwrapped = 0;

			for (int it = 0; it < 20000; it++)
			{
				uint8_t inf[96];
				int len = 1 + (int)(seed % 90U);

				for (int i = 0; i < len; i++) { seed = seed * 1664525U + 1013904223U; inf[i] = (uint8_t)(seed >> 24); }
				inf[0] = '}';
				if ((it & 1) && (len > 12)) { memcpy(inf + 1, "AB1CD>APRS,X", 12); inf[7 + (it % 5)] = ':'; }
				u = tpParseBytes(inf, len, &ax, &pk, b);
				if (u == 1)
				{
					unwrapped++;
					if ((ax.info < b) || ((ax.info + ax.infoLen) > (b + sizeof(b))) || (ax.infoLen > len)) { outside++; }
				}
			}
			CHECK(outside == 0, "20000 випадкових кадрів з '}' -- без виходу за межі (розгорнуто %d)", unwrapped);
		}

		/* дедуплікація: той самий пакет напряму і через шлюз -- ОДИН пакет і ОДНА станція */
		{
			static aprsRxDb_t db;
			aprsAx25_t direct, gated;
			aprsPacket_t pd, pg;
			uint8_t b1[200], b2[200];
			const char *inner = ":US5EX-7  :test{5";
			char viaGate[120];
			int n1, n2;

			aprsDbInit(&db);
			n1 = buildFrame(b1, "APDR16", "UW5ELK", 5, 0, 0, (const uint8_t *)inner, (int)strlen(inner));
			snprintf(viaGate, sizeof(viaGate), "}UW5ELK-5>APDR16,TCPIP,SP5WWP-10*:%s", inner);
			n2 = buildFrame(b2, "APRS", "SP5WWP", 10, 0, 0, (const uint8_t *)viaGate, (int)strlen(viaGate));
			CHECK(aprsAx25Parse(b1, (uint16_t)n1, &direct) && aprsAx25Parse(b2, (uint16_t)n2, &gated) && aprsAx25Unwrap(&gated), "прямий і через шлюз розібрано");
			aprsPacketParse(&direct, &pd);
			aprsPacketParse(&gated, &pg);
			CHECK(!strcmp(direct.src, gated.src) && (direct.infoLen == gated.infoLen) && !memcmp(direct.info, gated.info, direct.infoLen),
					"джерело й info однакові після розгортання");
			CHECK(!aprsDbIsDuplicate(&db, &direct, 1000) && aprsDbIsDuplicate(&db, &gated, 4000), "прямий, потім через шлюз (+3 с) -- дублікат");
			CHECK(!aprsDbMsgSeen(&db, &direct, &pd, 1000) && aprsDbMsgSeen(&db, &gated, &pg, 4000), "... і для «повідомлення вже віддавали»");
			aprsDbUpdate(&db, &direct, &pd, 1000);
			aprsDbUpdate(&db, &gated, &pg, 4000);
			CHECK((aprsDbCount(&db) == 1) && !strcmp(aprsDbNth(&db, 0, 5000)->call, "UW5ELK-5") && (aprsDbNth(&db, 0, 5000)->count == 2),
					"у списку один рядок UW5ELK-5 (шлюзу там нема)");
			aprsDbInit(&db);
			CHECK(!aprsDbIsDuplicate(&db, &gated, 1000) && aprsDbIsDuplicate(&db, &direct, 2000), "спершу через шлюз, потім напряму -- дублікат");
		}
	}

	printf("== R11-fix: адресат повідомлення («нам / не нам») ==\n");
	{
		uint8_t b[300];
		struct { const char *info; const char *call; unsigned ssid; int want; const char *what; } t[] = {
			{ ":US5EX-7  :x{1", "US5EX", 7, 1, "точний збіг US5EX-7" },
			{ ":US5EX-7  :x{1", "us5ex", 7, 1, "власний позивний у нижньому регістрі" },
			{ ":us5ex-7  :x{1", "US5EX", 7, 1, "адресат у нижньому регістрі" },
			{ ":US5EX-7:x{1", "US5EX", 7, 0, "адресат коротший за 9 без пробілів -- формат зіпсований, не вважаємо своїм" },
			{ ":US5EX-7   :x{1", "US5EX", 7, 0, "10-й символ не ':' -- формат зіпсований" },
			{ ":US5EX -7 :x{1", "US5EX", 7, 0, "пробіл усередині («US5EX -7») -- не наш" },
			{ ": US5EX-7 :x{1", "US5EX", 7, 0, "пробіл попереду -- не наш" },
			{ ":US5EX-70 :x{1", "US5EX", 7, 0, "US5EX-70 -- не US5EX-7" },
			{ ":US5EX-07 :x{1", "US5EX", 7, 0, "«-07» -- не наш (SSID без нулів)" },
			{ ":US5EX-7  :x{1", "US5EX", 8, 0, "інший SSID" },
			{ ":US5EX    :x{1", "US5EX", 0, 1, "SSID 0: голий позивний" },
			{ ":US5EX-0  :x{1", "US5EX", 0, 1, "SSID 0: «-0» теж" },
			{ ":US5EX    :x{1", "US5EX", 7, 0, "адресат без SSID -- не для US5EX-7" },
			{ ":US5EX-1  :x{1", "US5EX", 1, 1, "SSID 1" },
			{ ":US5EX-15 :x{1", "US5EX", 15, 1, "SSID 15" },
			{ ":US5EX-15 :x{1", "US5EX", 5, 0, "15 не 5" },
			{ ":US5EX-1  :x{1", "US5EX", 11, 0, "1 не 11" },
			{ ":US5EX-7  :x{1", "US5EX", 16, 0, "власний SSID 16 (сміття) -- ніколи" },
			{ ":US5EX-7  :x{1", "", 7, 0, "власного позивного нема -- ніколи" },
		};

		for (size_t k = 0; k < sizeof(t) / sizeof(t[0]); k++)
		{
			parseInfo("APRS", t[k].info, &ax, &pk, b);
			CHECK((pk.type == APRS_T_MESSAGE) ? (aprsMsgIsForUs(pk.msgTo, t[k].call, (uint8_t)t[k].ssid) == (t[k].want != 0)) : (t[k].want == 0),
					"%s", t[k].what);
		}
	}

	printf("== R11-fix: SSID у розборі адреси (0, 1, 7, 10, 15) ==\n");
	{
		static const struct { int ssid; const char *want; } t[] = { { 0, "TEST" }, { 1, "TEST-1" }, { 7, "TEST-7" }, { 10, "TEST-10" }, { 15, "TEST-15" } };
		uint8_t b[100];

		for (size_t k = 0; k < sizeof(t) / sizeof(t[0]); k++)
		{
			int n = buildFrame(b, "APRS", "TEST", t[k].ssid, 0, 0, (const uint8_t *)">x", 2);
			CHECK(aprsAx25Parse(b, (uint16_t)n, &ax) && !strcmp(ax.src, t[k].want), "SSID %d -> «%s»", t[k].ssid, t[k].want);
		}
	}

	printf("== відстань і азимут ==\n");
	{
		uint32_t d;
		uint16_t brg;
		aprsGeo(0, 0, 0, 1000000, &d, &brg);
		CHECK((labs((long)d - 111226) < 60) && (brg == 90), "1° по екватору на схід: %u м, азимут %u", d, brg);
		aprsGeo(0, 0, 1000000, 0, &d, &brg);
		CHECK((labs((long)d - 111226) < 60) && (brg == 0), "1° на північ: %u м, азимут %u", d, brg);
		aprsGeo(0, 0, -1000000, 0, &d, &brg);
		CHECK((brg == 180), "на південь: азимут %u", brg);
		aprsGeo(0, 0, 0, -1000000, &d, &brg);
		CHECK((brg == 270), "на захід: азимут %u", brg);
		aprsGeo(50000000, 30000000, 50000000, 30000000, &d, &brg);
		CHECK(d == 0, "та сама точка: %u м", d);
		/* незалежна перевірка гаверсинусом на довільній парі */
		int32_t la = 50450000, lo = 30523000, lb = 49839000, lob = 24029000;   /* ~ 470 км */
		aprsGeo(la, lo, lb, lob, &d, &brg);
		double r = 6372795.0, k = 3.14159265358979323846 / 180.0;
		double p1 = la * 1e-6 * k, p2 = lb * 1e-6 * k, dl = (lob - lo) * 1e-6 * k;
		double h = sin((p2 - p1) / 2) * sin((p2 - p1) / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2);
		double ref = 2 * r * asin(sqrt(h));
		CHECK(fabs((double)d - ref) < ref * 0.0005, "довільна пара: %u м (гаверсинус %.0f м)", d, ref);
		CHECK((brg > 240) && (brg < 270), "... азимут на захід-південний захід: %u", brg);
		/* через антимеридіан */
		aprsGeo(0, 179500000, 0, -179500000, &d, &brg);
		CHECK((labs((long)d - 111226) < 60) && (brg == 90), "через антимеридіан: %u м, азимут %u", d, brg);
		CHECK(!strcmp(aprsBearingName(0), "N") && !strcmp(aprsBearingName(22), "N") && !strcmp(aprsBearingName(23), "NE") &&
				!strcmp(aprsBearingName(45), "NE") && !strcmp(aprsBearingName(67), "NE") && !strcmp(aprsBearingName(68), "E") &&
				!strcmp(aprsBearingName(90), "E") && !strcmp(aprsBearingName(135), "SE") && !strcmp(aprsBearingName(180), "S") &&
				!strcmp(aprsBearingName(225), "SW") && !strcmp(aprsBearingName(270), "W") && !strcmp(aprsBearingName(315), "NW") &&
				!strcmp(aprsBearingName(337), "NW") && !strcmp(aprsBearingName(338), "N") && !strcmp(aprsBearingName(359), "N"),
				"сектори азимуту (8 по 45°)");
	}

	testR14();
	testR16Mice();
	testStage3();
	testRawText();
	testFuzz();

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
