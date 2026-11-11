/*
 * test_ta_diag.c -- R88: діагностика сирого Talker Alias і GPS-блока LC (functions/ta_diag.c, лише ENABLE_TA_DIAG).
 *
 * УВАГА: усі вхідні дані тут СИНТЕТИЧНІ (реальних захоплень з ефіру в репозиторії немає -- їх і має дати ця діагностична збірка).
 * Кодувальники TA / GPS нижче написано ОКРЕМО за описом ETSI TS 102 361-2 (бітовий потік: 2 біти формат, 5 біт довжина, далі дані),
 * а не копією декодера, щоб тест не підтверджував власні помилки.
 *
 *  1  taDiagHex: порожній ввід, межі буфера, великі літери;
 *  2  taDiagParseHeader / taDiagFormatName;
 *  3  taDiagDecode: 7-біт (різні довжини, до 31 символу), ISO-8, "UTF-8", UTF-16 (латиниця і '?' для не-Latin), відсутні блоки;
 *  4  межі й мутанти: NULL, destLen 0/1/2, довжина 0, довжина 31, недовгий (нульовий) хвіст, сміттєвий заголовок;
 *  5  taDiagParseGps: відомі координати (обидва знаки), межі, код похибки, NULL;
 *  6  taDiagFmtDeg: знак, нулі, від'ємне < 1 градуса;
 *  7  taDiagFlcoRow: перенесення рядка по 16 символів, порожня гістограма, курсор;
 *  8  запис викликів: ротація за srcId, повтор блока не збільшує taSeen, кільце на 3, насичення 255, FW-текст, гістограма всіх LC.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "functions/ta_diag.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* --- СИНТЕТИЧНІ кодувальники (ETSI-бітовий потік) --- */
static void putBits(uint8_t *buf, size_t *bitPos, uint32_t v, int n)
{
	for (int i = n - 1; i >= 0; i--)
	{
		size_t p = (*bitPos)++;
		if ((v >> i) & 1U) { buf[p / 8U] |= (uint8_t)(0x80U >> (p % 8U)); }
	}
}
static void enc7(uint8_t *buf32, const char *text)
{
	size_t bit = 0, n = strlen(text);
	memset(buf32, 0, 32);
	putBits(buf32, &bit, 0, 2);
	putBits(buf32, &bit, (uint32_t)n, 5);
	for (size_t i = 0; i < n; i++) { putBits(buf32, &bit, (uint8_t)text[i] & 0x7FU, 7); }
}
static void enc8(uint8_t *buf32, uint8_t fmt, const char *text)
{
	size_t n = strlen(text);
	memset(buf32, 0, 32);
	buf32[0] = (uint8_t)((fmt << 6) | (n << 1));
	memcpy(buf32 + 1, text, n);
}
static void enc16(uint8_t *buf32, const uint16_t *u, size_t n)
{
	memset(buf32, 0, 32);
	buf32[0] = (uint8_t)((3U << 6) | (n << 1));
	for (size_t i = 0; i < n; i++) { buf32[1 + 2 * i] = (uint8_t)(u[i] >> 8); buf32[2 + 2 * i] = (uint8_t)(u[i] & 0xFF); }
}
static void encGps(uint8_t *d7, double lat, double lon, uint8_t err)
{
	int32_t lonI = (int32_t)lrint(lon * 33554432.0 / 360.0);
	int32_t latI = (int32_t)lrint(lat * 16777216.0 / 180.0);
	uint32_t lu = (uint32_t)lonI & 0x1FFFFFFU, la = (uint32_t)latI & 0xFFFFFFU;
	d7[0] = (uint8_t)(((lu >> 24) & 1U) | ((err & 7U) << 1));
	d7[1] = (uint8_t)(lu >> 16); d7[2] = (uint8_t)(lu >> 8); d7[3] = (uint8_t)lu;
	d7[4] = (uint8_t)(la >> 16); d7[5] = (uint8_t)(la >> 8); d7[6] = (uint8_t)la;
}

static void lcCall(uint8_t *lc, uint8_t flco, uint32_t tg, uint32_t src)
{
	memset(lc, 0, 12);
	lc[0] = flco;
	lc[3] = (uint8_t)(tg >> 16); lc[4] = (uint8_t)(tg >> 8); lc[5] = (uint8_t)tg;
	lc[6] = (uint8_t)(src >> 16); lc[7] = (uint8_t)(src >> 8); lc[8] = (uint8_t)src;
}
static void lcData(uint8_t *lc, uint8_t flco, const uint8_t *d7)
{
	memset(lc, 0, 12);
	lc[0] = flco;
	lc[1] = 0x00;
	memcpy(&lc[2], d7, 7);
}

static void t1_hex(void)
{
	char o[8];
	const uint8_t b[] = { 0x0A, 0xFF, 0x00, 0x5C };

	CHECK(taDiagHex(o, sizeof(o), b, 4) == 6 && strcmp(o, "0AFF00") == 0, "1a: обрізано по місцю (7 байт буфера -> 3 байти): '%s'", o);
	CHECK(taDiagHex(o, sizeof(o), b, 0) == 0 && o[0] == 0, "1b: n = 0 -> порожній рядок");
	CHECK(taDiagHex(o, 1, b, 4) == 0 && o[0] == 0, "1c: outSize 1 -> лише нуль");
	CHECK(taDiagHex(o, 0, b, 4) == 0, "1d: outSize 0 не пише");
	CHECK(taDiagHex(NULL, 4, b, 4) == 0, "1e: NULL out не падає");
	char o2[16];
	CHECK(taDiagHex(o2, sizeof(o2), b, 4) == 8 && strcmp(o2, "0AFF005C") == 0, "1f: великі літери '%s'", o2);
	CHECK(taDiagHex(o2, sizeof(o2), NULL, 4) == 0 && o2[0] == 0, "1g: NULL b -> порожній рядок");
}

static void t2_hdr(void)
{
	taDiagHdr_t h;
	taDiagParseHeader(0x4B, &h);   /* 01 00101 1 */
	CHECK(h.format == 1 && h.size == 5 && h.bit0 == 1, "2a: 0x4B -> ISO8 len 5 bit0 1");
	taDiagParseHeader(0xFE, &h);
	CHECK(h.format == 3 && h.size == 31 && h.bit0 == 0, "2b: 0xFE -> UTF16 len 31");
	taDiagParseHeader(0x00, &h);
	CHECK(h.format == 0 && h.size == 0 && h.bit0 == 0, "2c: 0x00 -> 7BIT len 0");
	CHECK(strcmp(taDiagFormatName(0), "7BIT") == 0 && strcmp(taDiagFormatName(1), "ISO8") == 0 &&
	      strcmp(taDiagFormatName(2), "UTF8") == 0 && strcmp(taDiagFormatName(3), "UTF16") == 0 && strcmp(taDiagFormatName(7), "UTF16") == 0, "2d: імена форматів");
}

static void t3_decode(void)
{
	uint8_t buf[32];
	char d[32];
	const char *samples[] = { "UT1ABC", "A", "UT1ABC KN28ab", "UT1ABC 50.45 30.52", "0123456789012345678901234567890" /* 31 */ };

	for (size_t i = 0; i < sizeof(samples) / sizeof(samples[0]); i++)
	{
		enc7(buf, samples[i]);
		size_t n = taDiagDecode(buf, d, sizeof(d));
		CHECK(n == strlen(samples[i]) && strcmp(d, samples[i]) == 0, "3a%zu: 7-біт '%s' -> '%s'", i, samples[i], d);
	}
	enc8(buf, 1, "UT1ABC KN28ab");
	CHECK(taDiagDecode(buf, d, sizeof(d)) == 13 && strcmp(d, "UT1ABC KN28ab") == 0, "3b: ISO-8 -> '%s'", d);
	enc8(buf, 2, "UT1ABC");
	CHECK(strcmp((taDiagDecode(buf, d, sizeof(d)), d), "UT1ABC") == 0, "3c: 'UTF-8' копіюється як 8-біт");
	{
		/* cp1251 'При' = D0 C0 E8 -- прошивка віддає байти як є */
		const char cyr[] = { (char)0xCF, (char)0xF0, (char)0xE8, 0 };
		enc8(buf, 1, cyr);
		taDiagDecode(buf, d, sizeof(d));
		CHECK(memcmp(d, cyr, 4) == 0, "3d: ISO-8 з кириличними кодами не псується");
	}
	{
		const uint16_t u[] = { 'U', 'T', '1', 0x0416 /* кирилична Ж -> '?' */, 'A' };
		enc16(buf, u, 5);
		size_t n = taDiagDecode(buf, d, sizeof(d));
		CHECK(n == 5 && strcmp(d, "UT1?A") == 0, "3e: UTF-16, не-Latin -> '?': '%s'", d);
	}
	{
		const uint16_t u[] = { 'U', 'T', 'X' };
		enc16(buf, u, 3);
		buf[0] = (uint8_t)((3U << 6) | (2U << 1));   /* у заголовку довжина 2, а даних 3 -- довжина має обмежувати */
		CHECK(taDiagDecode(buf, d, sizeof(d)) == 2 && strcmp(d, "UT") == 0, "3e2: UTF-16, довжина із заголовка обмежує: '%s'", d);
	}
	/* лише блок 0 (решта блоків відсутні -> нулі) */
	enc7(buf, "UT1ABC");
	memset(buf + 7, 0, 25);
	CHECK(taDiagDecode(buf, d, sizeof(d)) == 6 && strcmp(d, "UT1ABC") == 0, "3f: тільки перший блок, решта нулі");
}

static void t4_edges(void)
{
	uint8_t buf[32];
	char d[32];
	char big[8];

	memset(buf, 0, sizeof(buf));
	CHECK(taDiagDecode(NULL, d, sizeof(d)) == 0 && d[0] == 0, "4a: NULL буфер");
	CHECK(taDiagDecode(buf, NULL, 8) == 0, "4b: NULL dest");
	CHECK(taDiagDecode(buf, d, 0) == 0 && taDiagDecode(buf, d, 1) == 0, "4c: destLen 0/1");
	CHECK(taDiagDecode(buf, d, sizeof(d)) == 0 && d[0] == 0, "4d: нульовий заголовок (довжина 0)");
	memset(d, 'x', sizeof(d));
	memset(buf, 0xFF, sizeof(buf));   /* UTF16 довжина 31, сміття */
	taDiagDecode(buf, d, sizeof(d));
	CHECK(strlen(d) < sizeof(d), "4e: сміттєвий заголовок 0xFF -- рядок завершено в межах буфера");
	memset(buf, 0xAA, sizeof(buf));
	memset(big, 'y', sizeof(big));
	taDiagDecode(buf, big, 4);
	CHECK(big[4] == 'y', "4f: короткий dest (4) не переписує пам'ять за межами: '%c'", big[4]);
	enc7(buf, "0123456789012345678901234567890");
	memset(d, 'z', sizeof(d));
	taDiagDecode(buf, d, 8);
	CHECK(strlen(d) <= 7, "4g: 7-біт 31 символ у dest 8 -> не більше 7");
	/* мутант: довжина в заголовку більша за наявні дані -- не читає за 32 байти */
	memset(buf, 0, sizeof(buf));
	buf[0] = (uint8_t)(31U << 1);
	CHECK(taDiagDecode(buf, d, sizeof(d)) < sizeof(d), "4h: 7-біт, довжина 31, дані нульові");
	memset(buf, 0, sizeof(buf));
	buf[0] = (uint8_t)((1U << 6) | (31U << 1));
	CHECK(taDiagDecode(buf, d, sizeof(d)) == 0, "4i: ISO-8, довжина 31, але дані нульові -> 0 (не довіряємо довжині)");
}

static void t5_gps(void)
{
	uint8_t d[7];
	int32_t la, lo;
	uint8_t err;
	const struct { double lat, lon; } pts[] = { { 50.4501, 30.5234 }, { -33.8688, 151.2093 }, { 40.7128, -74.0060 }, { -22.9068, -43.1729 },
	                                           { 89.9999, 179.9999 }, { -89.9999, -179.9999 }, { 0.0, 0.0 }, { 0.0001, -0.0001 } };

	for (size_t i = 0; i < sizeof(pts) / sizeof(pts[0]); i++)
	{
		encGps(d, pts[i].lat, pts[i].lon, 3);
		CHECK(taDiagParseGps(d, &la, &lo, &err), "5a%zu: розбір", i);
		CHECK(abs(la - (int32_t)lrint(pts[i].lat * 10000)) <= 1 && abs(lo - (int32_t)lrint(pts[i].lon * 10000)) <= 1 && err == 3,
		      "5b%zu: (%d,%d)e-4 для (%.4f,%.4f), err %u", i, la, lo, pts[i].lat, pts[i].lon, err);
	}
	CHECK(taDiagParseGps(NULL, &la, &lo, &err) == false && taDiagParseGps(d, NULL, &lo, &err) == false && taDiagParseGps(d, &la, NULL, &err) == false, "5c: NULL-аргументи");
	CHECK(taDiagParseGps(d, &la, &lo, NULL), "5d: errIdx необов'язковий");
	/* мутант: усі 0xFF -- не падає, значення в межах формату (lon 25 біт, lat 24 біти) */
	memset(d, 0xFF, sizeof(d));
	taDiagParseGps(d, &la, &lo, &err);
	CHECK(la == 0 && lo == 0, "5e: 0xFF -> обидві координати -1 одиниця формату (~ -0.00001 град.) -> 0 після заокруглення e-4: (%d,%d)", la, lo);
	CHECK(err == 7, "5f: код похибки 7 (біти 3..1 = 111)");
	memset(d, 0, sizeof(d));
	taDiagParseGps(d, &la, &lo, &err);
	CHECK(la == 0 && lo == 0 && err == 0, "5g: нулі -> (0,0)");
}

static void t6_deg(void)
{
	char o[24];
	taDiagFmtDeg(o, sizeof(o), 504501);  CHECK(strcmp(o, "50.4501") == 0, "6a: '%s'", o);
	taDiagFmtDeg(o, sizeof(o), -305234); CHECK(strcmp(o, "-30.5234") == 0, "6b: '%s'", o);
	taDiagFmtDeg(o, sizeof(o), -1);      CHECK(strcmp(o, "-0.0001") == 0, "6c: '%s'", o);
	taDiagFmtDeg(o, sizeof(o), 0);       CHECK(strcmp(o, "0.0000") == 0, "6d: '%s'", o);
	taDiagFmtDeg(o, sizeof(o), -1800000);CHECK(strcmp(o, "-180.0000") == 0, "6e: '%s'", o);
	taDiagFmtDeg(o, 5, 504501);          CHECK(strlen(o) == 4, "6f: коротший буфер обрізає, не падає: '%s'", o);
}

static void t7_flco(void)
{
	uint8_t cnt[64];
	char row[24];
	size_t cur = 0;
	int rows = 0;

	memset(cnt, 0, sizeof(cnt));
	CHECK(taDiagFlcoRow(cnt, &cur, row, sizeof(row), 16) == false, "7a: порожня гістограма");
	cnt[0] = 12; cnt[3] = 1; cnt[4] = 2; cnt[5] = 2; cnt[6] = 2; cnt[7] = 2; cnt[8] = 1; cnt[0x3F] = 255;
	cur = 0;
	while (taDiagFlcoRow(cnt, &cur, row, sizeof(row), 16))
	{
		CHECK(strlen(row) <= 16, "7b%d: рядок '%s' <= 16", rows, row);
		rows++;
	}
	CHECK(rows >= 2, "7c: гістограма займає кілька рядків (%d)", rows);
	cur = 0;
	taDiagFlcoRow(cnt, &cur, row, sizeof(row), 16);
	CHECK(strncmp(row, "00:12 03:1", 10) == 0, "7d: перший рядок починається з '00:12 03:1': '%s'", row);
	cur = 0; memset(cnt, 0, 64); cnt[0x3F] = 255;
	taDiagFlcoRow(cnt, &cur, row, sizeof(row), 16);
	CHECK(strcmp(row, "3F:255") == 0, "7e: максимальний індекс і насичення: '%s'", row);
	CHECK(taDiagFlcoRow(NULL, &cur, row, sizeof(row), 16) == false && taDiagFlcoRow(cnt, NULL, row, sizeof(row), 16) == false, "7f: NULL-аргументи");
	cur = 0;
	CHECK(taDiagFlcoRow(cnt, &cur, row, 4, 16) == false || strlen(row) < 4, "7g: крихітний вихідний буфер не переповнюється");
	{
		char pr[8];
		const char s[] = { 'A', 0x01, 'b', 0x7F, (char)0xCF, 0 };
		taDiagPrintable(pr, sizeof(pr), s, 0, 8);
		CHECK(pr[0] == 'A' && pr[1] == '.' && pr[2] == 'b' && pr[3] == '.' && (uint8_t)pr[4] == 0xCF && pr[5] == 0, "7h: друкований вигляд ('.' для керувальних, 0xCF як є)");
	}
}

static void t8_records(void)
{
	uint8_t lc[12], d7[7];
	uint8_t buf[32];
	taDiagInit();
	CHECK(taDiagGet(0) == NULL && taDiagCount() == 0, "8a: порожньо після ініціалізації");

	lcCall(lc, 0x00, 91, 2301234);
	taDiagCallLC(lc);
	CHECK(taDiagCount() == 1 && taDiagGet(0)->srcId == 2301234 && taDiagGet(0)->tgOrPc == 91 && taDiagGet(0)->isPc == 0, "8b: виклик TG 91 від 2301234");

	enc7(buf, "UT1ABC KN28ab");
	for (int b = 0; b < 4; b++)
	{
		memcpy(d7, buf + 7 * b, 7);
		lcData(lc, (uint8_t)(4 + b), d7);
		taDiagCallLC(lc);
		taDiagCallLC(lc);        /* повтор того самого блока */
	}
	const taDiagRec_t *r = taDiagGet(0);
	CHECK(r->taMask == 0x0F && r->taSeen[0] == 1 && r->taSeen[3] == 1, "8c: усі 4 блоки; повтор не збільшує taSeen (%u,%u)", r->taSeen[0], r->taSeen[3]);
	{
		uint8_t glued[32];
		char dg[32];
		taDiagGlue(r, glued);
		taDiagDecode(glued, dg, sizeof(dg));
		CHECK(memcmp(glued, buf, 28) == 0 && strcmp(dg, "UT1ABC KN28ab") == 0, "8d: склейка блоків збігається з вихідним TA: '%s'", dg);
	}
	/* змінений вміст блока 5 -> taSeen = 2 */
	memcpy(d7, buf + 7, 7); d7[0] ^= 0x10;
	lcData(lc, 5, d7);
	taDiagCallLC(lc);
	CHECK(taDiagGet(0)->taSeen[1] == 2, "8e: змінений вміст -> taSeen 2");

	encGps(d7, 50.4501, 30.5234, 1);
	lcData(lc, 8, d7);
	taDiagCallLC(lc);
	taDiagCallLC(lc);
	CHECK(taDiagGet(0)->gpsSeen == 1 && memcmp(taDiagGet(0)->gpsRaw, d7, 7) == 0, "8f: блок GPS записано, повтор не рахується");

	taDiagFwText("UT1ABC KN28ab");
	CHECK(strcmp(taDiagGet(0)->fwText, "UT1ABC KN28ab") == 0, "8g: текст декодера прошивки");
	{
		char longTxt[64];
		memset(longTxt, 'q', 63); longTxt[63] = 0;
		taDiagFwText(longTxt);
		CHECK(strlen(taDiagGet(0)->fwText) == 31, "8h: довгий FW-текст обрізається до 31");
	}
	/* новий виклик (інший srcId) -- ротація */
	lcCall(lc, 0x03, 2301234, 3109999);
	taDiagCallLC(lc);
	CHECK(taDiagCount() == 2 && taDiagGet(0)->isPc == 1 && taDiagGet(0)->srcId == 3109999 && taDiagGet(1)->srcId == 2301234, "8i: ротація; приватний виклик");
	CHECK(taDiagGet(0)->taMask == 0, "8j: новий запис порожній");
	/* той самий виклик знову (той самий srcId) -- без нового запису */
	taDiagCallLC(lc);
	CHECK(taDiagCount() == 2, "8k: той самий srcId не плодить записів");
	/* кільце на 3 */
	for (uint32_t s = 1; s <= 5; s++)
	{
		lcCall(lc, 0x00, 91, 4000000 + s);
		taDiagCallLC(lc);
	}
	CHECK(taDiagCount() == TA_DIAG_RECORDS && taDiagGet(0)->srcId == 4000005 && taDiagGet(2)->srcId == 4000003 && taDiagGet(3) == NULL, "8l: кільце тримає 3 останніх");
	/* насичення */
	taDiagInit();
	lcCall(lc, 0x00, 1, 1);
	for (int i = 0; i < 400; i++) { taDiagCallLC(lc); taDiagRawLC(lc); }
	CHECK(taDiagGet(0)->flco[0] == 255 && taDiagAllFlco()[0] == 255 && taDiagAllFlcoTotal() == 400, "8m: лічильники насичуються на 255; загальний рахунок 400");
	/* TA без виклику -- запис без ID; PF-біт у гістограмі за FLCO & 0x3F */
	taDiagInit();
	lcData(lc, 0x84, d7);   /* PF + FLCO 4 */
	taDiagRawLC(lc);
	taDiagCallLC(lc);
	CHECK(taDiagCount() == 1 && taDiagGet(0)->srcId == 0 && taDiagPfCount() == 1 && taDiagAllFlco()[4] == 1 && taDiagGet(0)->flco[4] == 1, "8n: PF=1 рахується окремо, FLCO = 4");
	taDiagNoteBadCrc(); taDiagNoteBadCrc();
	CHECK(taDiagCrcBadCount() == 2, "8o: лічильник поганих CRC");
	taDiagRawLC(NULL); taDiagCallLC(NULL); taDiagFwText(NULL);
	CHECK(1, "8p: NULL-аргументи не падають");
}

int main(void)
{
	t1_hex(); t2_hdr(); t3_decode(); t4_edges(); t5_gps(); t6_deg(); t7_flco(); t8_records();
	printf("%s (помилок: %d)\n", fails ? "ПРОВАЛ" : "ПРОЙДЕНО", fails);
	return fails ? 1 : 0;
}
