/*
 * test_dmr_sms_shift.c -- ui5: кирилиця від Z3DMR зі зсунутими старшими байтами UTF-16
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

	printf(fails ? "ПРОВАЛЕНО: %d\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
