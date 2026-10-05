/*
 * test_dmr_sms_text.c -- ui4: текст SMS cp1251 <-> UTF-16LE і dst-IP приватних SMS.
 * Лінкує СПРАВЖНІ functions/dmr_sms_text.c, dmr_sms_pdu.c (білдер IPv4/UDP/TMS),
 * crypto/dmr_aes.c (розбір вхідного тексту) і dmr_sms_fix.c (перевірка IPv4/UDP checksum).
 * Кириличних літералів у .c немає (файл UTF-8, шрифт рації -- cp1251): лише байти, згенеровані
 * з Python codecs 'cp1251' / 'utf-16-le'.
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

/* 66 українських літер (33 великі + 33 малі, абетка з Ґ Є І Ї): cp1251 і Unicode. */
static const uint8_t  UA_CP[66]  = { 0xC0, 0xC1, 0xC2, 0xC3, 0xA5, 0xC4, 0xC5, 0xAA, 0xC6, 0xC7, 0xC8, 0xB2, 0xAF, 0xC9, 0xCA, 0xCB, 0xCC, 0xCD, 0xCE, 0xCF, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDC, 0xDE, 0xDF, 0xE0, 0xE1, 0xE2, 0xE3, 0xB4, 0xE4, 0xE5, 0xBA, 0xE6, 0xE7, 0xE8, 0xB3, 0xBF, 0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEE, 0xEF, 0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFC, 0xFE, 0xFF };
static const uint16_t UA_UCS[66] = { 0x0410, 0x0411, 0x0412, 0x0413, 0x0490, 0x0414, 0x0415, 0x0404, 0x0416, 0x0417, 0x0418, 0x0406, 0x0407, 0x0419, 0x041A, 0x041B, 0x041C, 0x041D, 0x041E, 0x041F, 0x0420, 0x0421, 0x0422, 0x0423, 0x0424, 0x0425, 0x0426, 0x0427, 0x0428, 0x0429, 0x042C, 0x042E, 0x042F, 0x0430, 0x0431, 0x0432, 0x0433, 0x0491, 0x0434, 0x0435, 0x0454, 0x0436, 0x0437, 0x0438, 0x0456, 0x0457, 0x0439, 0x043A, 0x043B, 0x043C, 0x043D, 0x043E, 0x043F, 0x0440, 0x0441, 0x0442, 0x0443, 0x0444, 0x0445, 0x0446, 0x0447, 0x0448, 0x0449, 0x044C, 0x044E, 0x044F };

/* «Привіт, Ґанок! Їжак є.» -- cp1251 і UTF-16LE (як шле стокова). */
static const uint8_t MSG_CP[] = { 0xCF, 0xF0, 0xE8, 0xE2, 0xB3, 0xF2, 0x2C, 0x20, 0xA5, 0xE0, 0xED, 0xEE, 0xEA, 0x21, 0x20, 0xAF, 0xE6, 0xE0, 0xEA, 0x20, 0xBA, 0x2E };
static const uint8_t MSG_U16[] = { 0x1F, 0x04, 0x40, 0x04, 0x38, 0x04, 0x32, 0x04, 0x56, 0x04, 0x42, 0x04, 0x2C, 0x00, 0x20, 0x00, 0x90, 0x04, 0x30, 0x04, 0x3D, 0x04, 0x3E, 0x04, 0x3A, 0x04, 0x21, 0x00, 0x20, 0x00, 0x07, 0x04, 0x36, 0x04, 0x30, 0x04, 0x3A, 0x04, 0x20, 0x00, 0x54, 0x04, 0x2E, 0x00 };

/* IPv4-заголовок СТОКОВОЇ з ефіру (BBD_0004, «Hello», 12.38.234.41 -> 12.38.234.15, IP-ID 0) і
 * перші 6 Б UDP (порти 4007, довжина 28). Байт TMS стокова шле E0, ми A0 -- тому UDP checksum
 * різний; він перевіряється окремо (dmrSmsPduIpUdpOk). */
static const uint8_t STOCK_IP[20] = { 0x45,0x00,0x00,0x30,0x00,0x00,0x00,0x00,0x40,0x11,0x8e,0x38,
                                      0x0c,0x26,0xea,0x29,0x0c,0x26,0xea,0x0f };
static const uint8_t STOCK_UDP6[6] = { 0x0f,0xa7,0x0f,0xa7,0x00,0x1c };

int main(void)
{
	printf("test_dmr_sms_text:\n");

	/* 1. 66 літер туди й назад. */
	{
		int ok = 1;
		for (int i = 0; i < 66; i++)
		{
			if (dmrSmsCp1251ToUcs2(UA_CP[i]) != UA_UCS[i]) { ok = 0; printf("    cp %02X -> %04X (треба %04X)\n", UA_CP[i], dmrSmsCp1251ToUcs2(UA_CP[i]), UA_UCS[i]); }
			if (dmrSmsUcs2ToCp1251(UA_UCS[i]) != UA_CP[i]) { ok = 0; printf("    U+%04X -> %02X (треба %02X)\n", UA_UCS[i], dmrSmsUcs2ToCp1251(UA_UCS[i]), UA_CP[i]); }
		}
		CHECK(ok, "усі 66 українських літер (з Ґ Є І Ї): cp1251 -> Unicode -> cp1251");
	}
	/* 2. Уся таблица cp1251: друковані байти переживають коло; 0x98 (не визначено) -> '?'. */
	{
		int ok = 1;
		for (int c = 0x20; c < 0x100; c++)
		{
			if ((c == 0x7F) || (c == 0x98)) { continue; }
			if (dmrSmsUcs2ToCp1251(dmrSmsCp1251ToUcs2((uint8_t)c)) != c) { ok = 0; printf("    байт %02X не пережив коло\n", c); }
		}
		CHECK(ok, "уся таблиця cp1251 0x20..0xFF (крім 0x7F, 0x98): коло без втрат");
		CHECK(dmrSmsCp1251ToUcs2(0x98) == '?', "0x98 (не визначений у cp1251) -> '?'");
		CHECK(dmrSmsCp1251ToUcs2(0xB9) == 0x2116 && dmrSmsUcs2ToCp1251(0x2116) == 0xB9, "No (0xB9) <-> U+2116");
		CHECK(dmrSmsUcs2ToCp1251(0x263A) == '?' && dmrSmsUcs2ToCp1251(0x00E9) == '?', "невідомі (U+263A, U+00E9) -> '?'");
		CHECK(dmrSmsUcs2ToCp1251(0x000D) == ' ' && dmrSmsUcs2ToCp1251(0x000A) == ' ', "CR/LF -> пробіл");
	}
	/* 3. PDU з кирилицею: UTF-16LE у ефірі рівно як у стокової; розбір назад -- без втрат. */
	{
		uint8_t pdu[400];
		int n = (int)sizeof MSG_CP;
		int pl = dmrSmsPduBuildPlaintext((const char *)MSG_CP, n, 0x26EA0F, 0x26EA29, 0, 0x93, 0x1234, pdu);
		CHECK(pl == 38 + 2 * n && memcmp(pdu + 38, MSG_U16, sizeof MSG_U16) == 0, "TX: текст у PDU -- UTF-16LE U+04xx (%d символів)", n);
		CHECK(dmrSmsPduIpUdpOk(pdu, pl), "TX: IPv4 і UDP checksum валідні");
		char out[200];
		int r = dmr_sms_text_from_plaintext(pdu, pl, out, sizeof out);
		CHECK(r == n && memcmp(out, MSG_CP, (size_t)n) == 0, "RX: розбір назад у cp1251 без втрат (%d)", r);
	}
	/* 3б. Шифрований шлях (AES-256-ECB цілих 16-байтних блоків, хвіст відкритий -- як dmrSmsSend()
	 * і стокова): розшифровка dmr_sms_rx_decrypt() дає той самий текст cp1251. */
	{
		uint8_t key[32]; for (int i = 0; i < 32; i++) { key[i] = (uint8_t)(0xA0 + i); }
		uint8_t pdu[400];
		int n = (int)sizeof MSG_CP;
		int pl = dmrSmsPduBuildPlaintext((const char *)MSG_CP, n, 0x26EA0F, 0x26EA29, 0, 0x93, 0x4321, pdu);
		for (int i = 0; i + 16 <= pl; i += 16) { aes256_ecb_encrypt(key, pdu + i); }
		char out[200];
		int r = dmr_sms_rx_decrypt(pdu, pl, key, out, sizeof out);
		CHECK(r == n && memcmp(out, MSG_CP, (size_t)n) == 0, "шифроване SMS з кирилицею: зашифрували -> розшифрували без втрат");
	}
	/* 4. Вхідний текст з невідомим символом і CR/LF: '?' і пробіли, нічого не губиться мовчки. */
	{
		uint8_t pdu[400];
		const char *t = "ab";
		int pl = dmrSmsPduBuildPlaintext(t, 2, 0x26EA29, 0x26EA0F, 0, 0x90, 1, pdu);
		/* підмінити текст: 'a' CR LF U+263A 'b' -- довжини IP не міняємо: 'a' + U+263A */
		pdu[38] = 0x3A; pdu[39] = 0x26;   /* U+263A замість 'a' */
		char out[16];
		int r = dmr_sms_text_from_plaintext(pdu, pl, out, sizeof out);
		CHECK(r == 2 && out[0] == '?' && out[1] == 'b', "RX: U+263A -> '?' (не відкинуто)");
	}
	/* 5. dst-IP: приватне -- 12.x (побайтово як IPv4-заголовок стокової), групове -- 225.x. */
	{
		uint8_t pdu[200];
		int pl = dmrSmsPduBuildPlaintext("Hello", 5, 0x26EA29, 0x26EA0F, 0, 0x99, 0x0000, pdu);
		CHECK(memcmp(pdu, STOCK_IP, 20) == 0, "приватне: IPv4-заголовок байт-у-байт як у стокової (dst 12.38.234.15, checksum 8e38)");
		CHECK(memcmp(pdu + 20, STOCK_UDP6, 6) == 0, "приватне: UDP порти 4007/4007, довжина 28 -- як у стокової");
		CHECK(dmrSmsPduIpUdpOk(pdu, pl), "приватне: UDP checksum (псевдозаголовок з dst 12.x) валідний");
		pl = dmrSmsPduBuildPlaintext("Hello", 5, 0x26EA29, 9, 1, 0x99, 0x0000, pdu);
		CHECK(pdu[16] == 0xE1 && pdu[19] == 9 && dmrSmsPduIpUdpOk(pdu, pl), "групове: dst 225.0.0.9, checksum-и валідні");
	}

	printf(fails ? "ПРОВАЛ (%d)\n" : "ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
