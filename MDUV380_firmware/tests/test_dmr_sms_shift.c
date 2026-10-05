/*
 * test_dmr_sms_shift.c -- ui5/ui5b: кирилиця від Z3DMR зі зсунутими старшими байтами UTF-16
 * (claude/sms-protocol.md, розділ 7) і те, що правильні PDU лишаються без змін.
 * Лінкує СПРАВЖНІ crypto/dmr_aes.c (dmr_sms_text_from_plaintext), functions/dmr_sms_text.c,
 * dmr_sms_pdu.c (білдер PDU для синтетичних випадків), dmr_sms_fix.c (IPv4/UDP checksum).
 * Кириличних літералів немає (файл UTF-8): лише байти cp1251.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "functions/dmr_sms_text.h"
#include "functions/dmr_sms_pdu.h"
#include "functions/dmr_sms_fix.h"
#include "crypto/dmr_aes.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static int hex2bin(const char *h, uint8_t *out)
{
	int n = 0;
	while (h[0] && h[1])
	{
		unsigned v;
		sscanf(h, "%2x", &v);
		out[n++] = (uint8_t)v;
		h += 2;
	}
	return n;
}

static void dumpCp(const char *what, const char *s, int n)
{
	printf("       %s:", what);
	for (int i = 0; i < n; i++) { printf(" %02X", (uint8_t)s[i]); }
	printf("\n");
}

/* Справжній PDU з ефіру: Z3DMR -> стокова -> форк, «Привіт іІєЄїЇґҐ» (80 Б, CRC32/IPv4/UDP ок). */
static const char Z3_HEX[] =
	"45000044000f000040118e150c26ea0f0c26ea290fa70fa70030c7530026e00081040d000a041f04400438043204"
	"5604420020045604060454040404570407049104900000000000000000001d766693";
/* «Привіт іІєЄїЇґҐ» у cp1251. */
static const uint8_t Z3_WANT[] = { 0xCF, 0xF0, 0xE8, 0xE2, 0xB3, 0xF2, 0x20, 0xB3, 0xB2, 0xBA, 0xAA, 0xBF, 0xAF, 0xB4, 0xA5 };

/* Стоковий «Hello» (правильний UTF-16LE). */
static const char HELLO_HEX[] =
	"450000300006000040118e320c26ea290c26ea0f0fa70fa7001c6ac90012e0009e040d000a00480065006c006c006f"
	"00000000000000000000000000bce8ce3e";

/* Зсунути правильний PDU так, як це робить Z3DMR: старший байт символу k -> pdu[37 + 2k],
 * молодший лишається на pdu[38 + 2k]; байт після останнього молодшого -- 0 (як в ефірі). */
static void shiftLikeZ3(uint8_t *pdu, int pl)
{
	int nch = (pl - 38) / 2;
	uint8_t hi[200];
	for (int k = 0; k < nch; k++) { hi[k] = pdu[39 + 2 * k]; }
	for (int k = 0; k < nch; k++) { pdu[37 + 2 * k] = hi[k]; }
	pdu[38 + 2 * nch - 1] = 0;
}

/* Зібрати PDU з тексту cp1251 (правильний UTF-16LE), за потреби зсунути, розібрати. */
static int roundTrip(const uint8_t *cp, int n, int shift, char *out, int outMax)
{
	uint8_t pdu[400];
	int pl = dmrSmsPduBuildPlaintext((const char *)cp, n, 0x26EA0F, 0x26EA29, 0, 0x81, 0x000F, pdu);
	if (shift) { shiftLikeZ3(pdu, pl); }
	return dmr_sms_text_from_plaintext(pdu, pl, out, outMax);
}

static void caseSynth(const char *name, const uint8_t *cp, int n, int shift)
{
	char out[200];
	int r = roundTrip(cp, n, shift, out, sizeof out);
	int ok = (r == n) && (memcmp(out, cp, (size_t)n) == 0);
	CHECK(ok, "%s %s -> без змін", shift ? "зсунутий" : "правильний", name);
	if (!ok) { dumpCp("отримано", out, r > 0 ? r : 0); dumpCp("очікувано", (const char *)cp, n); }
}


/* ======================= ui5b: фіксовані рядки й 3000 випадкових фраз ======================= */
/* Фіксовані рядки брифу ui5b (cp1251; згенеровано з tools/sms_shift_ref.py FIXED). */
static const char * const FIXED[] = {
	"\340", "\362", "\245", "\340\340\340\340\340", "\340\341\342", "OK\344\356\341\360\345",
	"1\344\356\341\360\345", "\362\345\361\362123", "DMR\352\340", "\344\356\341\360\345!",
	"\344\356\341\360\345)", "Hi,\357\360\350\342\263\362", "OK, \344\356\341\360\345",
	"Hi, \301\356\343\344\340\355!",
	"\317\360\350\342\263\362, \377\352 \361\357\360\340\342\350\077",
	"\344\356\341\360\345 \344\377\352\363\376",
	"\317\360\350\342\263\362 \263\262\272\252\277\257\264\245", "73!", "QSL\077", "Hello", "ok",
	"2550213",
};
/* Словник генератора -- той самий, що в tools/sms_shift_ref.py (cp1251). */
static const char * const UA_WORDS[] = {
	"\357\360\350\342\263\362", "\344\356\341\360\345", "\344\377\352\363\376", "\377\352",
	"\361\357\360\340\342\350", "\277\346\340\352", "\264\340\355\356\352", "\272",
	"\371\356\361\374", "\347\342'\377\347\356\352", "\357\360\350\351\356\354", "\367\363\376",
	"\362\345\341\345", "\344\356\341\360\350\351", "\344\345\355\374", "\342\345\367\263\360",
	"\341\363\344\363", "\355\340", "\354\263\361\366\263", "\367\345\360\345\347",
	"\365\342\350\353\350\355", "\352\340\355\340\353", "\360\340\366\263\377",
	"\341\340\362\340\360\345\377", "\361\263\344\340\272", "\277\344\363",
	"\344\356\344\356\354\363", "\342\361\345", "\343\340\360\340\347\344", "\376\355\340\352",
	"\377\341\353\363\352\356", "\370\353\377\365", "\366\263\353\374", "\364\356\362\356",
	"\362\350\370\340", "\357\345\360\345\342\263\360\352\340", "\361\350\343\355\340\353",
	"\361\353\340\341\352\350\351", "\301\356\343\344\340\355", "\312\350\277\342",
	"\313\374\342\263\342", "\323\352\360\340\277\355\340", "\262\360\350\355\340",
	"\252\342\343\345\355", "\257\346\340\352\345\342\350\367", "\245\363\344\347\374", "\356\352",
};

static const char * const EN_WORDS[] = {
	"hello", "ok", "yes", "no", "copy", "roger", "test", "radio", "check", "good", "morning", "net",
	"qsl", "qth", "rst", "dmr", "Hi", "OK", "QSL", "DMR", "CQ", "TNX", "GM",
};

static const char * const CALLS[] = {
	"UW5ELK", "UR5EQF", "UT7UA", "US0IZ", "DL1ABC", "EM3XYZ", "UX1UA", "UR3QTW",
};
#define PHRASES_HASH 0x2E0EAC54U   /* FNV-1a 3000 фраз seed 1 -- tools/sms_shift_ref.py */

/* Мінімальний IPv4/UDP/TMS -- рівно як build_pdu() у tools/sms_shift_ref.py (декодер читає лише
 * версію/протокол IP, довжину IP і заголовок TMS 0D 00 0A 00). shifted = 0: правильний UTF-16LE;
 * 1: як Z3DMR -- UTF-16BE з байта 37 (LF = 0A у pdu[36]), сирітський байт у кінці = 00. */
static int buildPdu(const char *cp, int shifted, uint8_t *pdu)
{
	int n = (int)strlen(cp), p = 34;
	memset(pdu, 0, 34);
	pdu[p++] = 0x0D; pdu[p++] = 0x00; pdu[p++] = 0x0A;
	if (!shifted) { pdu[p++] = 0x00; }
	for (int k = 0; k < n; k++)
	{
		uint16_t u = dmrSmsCp1251ToUcs2((uint8_t)cp[k]);
		if (!shifted) { pdu[p++] = (uint8_t)u; pdu[p++] = (uint8_t)(u >> 8); }
		else          { pdu[p++] = (uint8_t)(u >> 8); pdu[p++] = (uint8_t)u; }
	}
	if (shifted) { pdu[p++] = 0x00; }
	pdu[0] = 0x45; pdu[9] = 0x11;
	pdu[2] = (uint8_t)(p >> 8); pdu[3] = (uint8_t)p;
	return p;
}

/* Обидва кодування мають прочитатись рівно як текст. Повертає кількість провалів (0..2). */
static int checkBoth(const char *cp, const char *what)
{
	int bad = 0;
	for (int sh = 0; sh < 2; sh++)
	{
		uint8_t pdu[400];
		char out[200];
		int pl = buildPdu(cp, sh, pdu);
		int r = dmr_sms_text_from_plaintext(pdu, pl, out, sizeof out);
		if ((r != (int)strlen(cp)) || (memcmp(out, cp, strlen(cp)) != 0))
		{
			bad++;
			printf("  FAIL %s (%s)\n", what, sh ? "зсунутий" : "правильний");
			dumpCp("отримано", out, r > 0 ? r : 0);
			dumpCp("очікувано", cp, (int)strlen(cp));
		}
	}
	return bad;
}

/* xorshift32 і генератор фраз -- той самий порядок викликів, що в sms_shift_ref.py. */
static uint32_t s_rng;
static uint32_t rngNext(void)
{
	uint32_t x = s_rng;
	x ^= x << 13; x ^= x >> 17; x ^= x << 5;
	s_rng = x;
	return x;
}
static uint32_t rngBelow(uint32_t n) { return rngNext() % n; }

/* Перша літера слова -- велика (cp1251), як str.upper() у Python для перших літер словника. */
static char upperCp(char ch)
{
	uint8_t c = (uint8_t)ch;
	if ((c >= 'a') && (c <= 'z')) { return (char)(c - 0x20); }
	if (c >= 0xE0)                { return (char)(c - 0x20); }
	switch (c)
	{
		case 0xB3: return (char)0xB2;   /* і */
		case 0xBF: return (char)0xAF;   /* ї */
		case 0xBA: return (char)0xAA;   /* є */
		case 0xB4: return (char)0xA5;   /* ґ */
	}
	return ch;
}

#define NELEM(a) ((uint32_t)(sizeof(a) / sizeof((a)[0])))

static void phrase(char *out)
{
	int pos = 0;
	uint32_t nw = 1 + rngBelow(6);
	out[0] = 0;
	for (uint32_t k = 0; k < nw; k++)
	{
		char w[32];
		uint32_t t = rngBelow(10);
		if (t < 5)
		{
			strcpy(w, UA_WORDS[rngBelow(NELEM(UA_WORDS))]);
			if ((k == 0) && rngBelow(2)) { w[0] = upperCp(w[0]); }
		}
		else if (t < 7) { strcpy(w, EN_WORDS[rngBelow(NELEM(EN_WORDS))]); }
		else if (t < 8) { strcpy(w, CALLS[rngBelow(NELEM(CALLS))]); }
		else            { snprintf(w, sizeof w, "%u", (unsigned)rngBelow(100000)); }
		if (rngBelow(4) == 0)
		{
			size_t l = strlen(w);
			w[l] = ",.!\077:)"[rngBelow(6)]; w[l + 1] = 0;
		}
		pos += sprintf(out + pos, "%s%s", k ? " " : "", w);
	}
}

int main(void)
{
	printf("test_dmr_sms_shift:\n");

	/* 1. Справжній PDU від Z3DMR. */
	{
		uint8_t pdu[128];
		int len = hex2bin(Z3_HEX, pdu);
		CHECK(len == 80, "Z3DMR: PDU 80 Б (%d)", len);
		int iplen = (pdu[2] << 8) | pdu[3];
		CHECK(dmrSmsPduIpUdpOk(pdu, iplen), "Z3DMR: IPv4 і UDP checksum сходяться (псує відправник, не ефір)");
		CHECK(pdu[37] == 0x04, "Z3DMR: ознака зсуву -- pdu[37] = 0x04 замість 0x00");
		char out[64];
		int r = dmr_sms_text_from_plaintext(pdu, len, out, sizeof out);
		int ok = (r == (int)sizeof Z3_WANT) && (memcmp(out, Z3_WANT, sizeof Z3_WANT) == 0);
		CHECK(ok, "Z3DMR: «Привіт іІєЄїЇґҐ» (15 символів, %d)", r);
		if (!ok) { dumpCp("отримано", out, r > 0 ? r : 0); dumpCp("очікувано", (const char *)Z3_WANT, sizeof Z3_WANT); }
		/* Шифрований шлях спільний: та сама функція після розшифровки. */
		uint8_t key[32]; for (int i = 0; i < 32; i++) { key[i] = (uint8_t)(0x11 * i); }
		uint8_t enc[128]; memcpy(enc, pdu, (size_t)len);
		for (int i = 0; i + 16 <= iplen; i += 16) { aes256_ecb_encrypt(key, enc + i); }
		r = dmr_sms_rx_decrypt(enc, len, key, out, sizeof out);
		CHECK((r == (int)sizeof Z3_WANT) && (memcmp(out, Z3_WANT, sizeof Z3_WANT) == 0),
				"Z3DMR шифрований (AES-256-ECB цілих блоків): той самий текст");
	}

	/* 2. Стоковий «Hello» -- без змін. */
	{
		uint8_t pdu[128];
		int len = hex2bin(HELLO_HEX, pdu);
		int iplen = (pdu[2] << 8) | pdu[3];
		CHECK(dmrSmsPduIpUdpOk(pdu, iplen), "стоковий Hello: IPv4 і UDP checksum сходяться");
		char out[64];
		int r = dmr_sms_text_from_plaintext(pdu, len, out, sizeof out);
		CHECK(r == 5 && memcmp(out, "Hello", 5) == 0, "стоковий Hello -> «Hello»");
	}

	/* 3. Синтетичні. */
	{
		static const uint8_t OK_DOBRE[]  = { 'O', 'K', ',', ' ', 0xE4, 0xEE, 0xE1, 0xF0, 0xE5 };            /* «OK, добре» */
		static const uint8_t DOBRE_DYA[] = { 0xE4, 0xEE, 0xE1, 0xF0, 0xE5, ' ', 0xE4, 0xFF, 0xEA, 0xF3, 0xFE }; /* «добре дякую» */
		static const uint8_t OK_FULL[]   = { 'O', 'K', ',', ' ', 0xE4, 0xEE, 0xE1, 0xF0, 0xE5, ' ', 0xE4, 0xFF, 0xEA, 0xF3, 0xFE }; /* «OK, добре дякую» */
		static const uint8_t A[]  = { 0xE0 };   /* а */
		static const uint8_t T[]  = { 0xF2 };   /* т */
		static const uint8_t GG[] = { 0xA5 };   /* Ґ */
		static const uint8_t A5[] = { 0xE0, 0xE0, 0xE0, 0xE0, 0xE0 };   /* «ааааа» */
		static const uint8_t HELLO73[] = { 'H', 'e', 'l', 'l', 'o', ' ', '7', '3' };

		caseSynth("«OK, добре»", OK_DOBRE, sizeof OK_DOBRE, 1);
		caseSynth("«OK, добре»", OK_DOBRE, sizeof OK_DOBRE, 0);
		caseSynth("«добре дякую»", DOBRE_DYA, sizeof DOBRE_DYA, 0);
		caseSynth("«добре дякую»", DOBRE_DYA, sizeof DOBRE_DYA, 1);
		caseSynth("«OK, добре дякую»", OK_FULL, sizeof OK_FULL, 1);
		caseSynth("«OK, добре дякую»", OK_FULL, sizeof OK_FULL, 0);
		caseSynth("«а»", A, sizeof A, 1);
		caseSynth("«т»", T, sizeof T, 1);
		caseSynth("«Ґ»", GG, sizeof GG, 1);
		caseSynth("«ааааа»", A5, sizeof A5, 1);
		caseSynth("«а»", A, sizeof A, 0);
		caseSynth("«ааааа»", A5, sizeof A5, 0);
		caseSynth("«Hello 73»", HELLO73, sizeof HELLO73, 0);
		caseSynth("«Hello 73»", HELLO73, sizeof HELLO73, 1);
	}

	/* 4. ui5b: фіксовані рядки брифу -- обидва кодування без змін. */
	{
		int bad = 0;
		for (uint32_t k = 0; k < NELEM(FIXED); k++) { bad += checkBoth(FIXED[k], "фіксований рядок"); }
		CHECK(bad == 0, "ui5b: %u фіксованих рядків x 2 кодування -- провалів %d", (unsigned)NELEM(FIXED), bad);
	}
	/* 5. ui5b: 3000 випадкових фраз (seed 1) -- обидва кодування без змін; ті самі фрази, що в
	 * tools/sms_shift_ref.py (звіряємо FNV-1a). */
	{
		uint32_t h = 0x811C9DC5U;
		int bad = 0;
		s_rng = 1;
		for (int n = 0; n < 3000; n++)
		{
			char ph[256];
			phrase(ph);
			for (const char *q = ph; ; q++)
			{
				uint8_t b = (*q != 0) ? (uint8_t)*q : (uint8_t)'\n';
				h = (h ^ b) * 0x01000193U;
				if (*q == 0) { break; }
			}
			bad += checkBoth(ph, "випадкова фраза");
		}
		CHECK(h == PHRASES_HASH, "ui5b: фрази ті самі, що в sms_shift_ref.py (FNV-1a %08X)", (unsigned)h);
		CHECK(bad == 0, "ui5b: 3000 випадкових фраз x 2 кодування -- провалів %d", bad);
	}
	/* 6. ui5b: відома межа (див. claude/sms-protocol.md, розд. 7) -- латиниця впритул до слова на «Р»
	 * з розділовим знаком: правильний «OKРація?» читається як зсунутий «OK аціяп». Фіксуємо, щоб
	 * зміна поведінки не пройшла непоміченою. */
	{
		static const char OK_RATSIA[] = "OK\320\340\366\263\377\077";   /* «OKРація?» */
		uint8_t pdu[100]; char out[64];
		int pl = buildPdu(OK_RATSIA, 0, pdu);
		int r = dmr_sms_text_from_plaintext(pdu, pl, out, sizeof out);
		CHECK(r == 8 && memcmp(out, OK_RATSIA, 8) != 0, "ui5b: відома межа «OKРація?» (правильний) -- читається зсунутим, як і в еталоні");
	}

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
