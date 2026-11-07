/*
 * test_aes_key_name.c -- R64C: перетворення cp1251 <-> UTF-16LE для імен слотів AES-ключів (СПРАВЖНІЙ application/source/crypto/aes_key_name.c).
 * Збирається з -DAES_KEY_NAME_HOST_TEST. Повну звірку всіх 256 байтів і всіх 65536 кодових одиниць з Python cp1251 робить tools/test_aes_key_name.py
 * (цей файл з аргументом --dump друкує таблиці).
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/aes_key_name.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

int main(int argc, char **argv)
{
	if ((argc > 1) && (strcmp(argv[1], "--dump") == 0))
	{
		for (unsigned b = 0U; b < 256U; b++)
		{
			printf("B %u %u\n", b, (unsigned)aesNameCp1251ToUnicode((uint8_t)b));
		}
		for (unsigned u = 0U; u < 65536U; u++)
		{
			printf("U %u %u\n", u, (unsigned)aesNameUnicodeToCp1251((uint16_t)u));
		}
		return 0;
	}

	{
		uint8_t f[AESN_FIELD_LEN];
		char out[AESN_CHARS + 1U];
		unsigned n;

		CHECK(AESN_CHARS == 16U && AESN_FIELD_LEN == 32U, "16 символів = 32 байти UTF-16LE");

		/* ЄІЇҐєіїґ: cp1251 AA B2 AF A5 BA B3 BF B4 <-> U+0404 U+0406 U+0407 U+0490 U+0454 U+0456 U+0457 U+0491 */
		{
			const uint8_t cp[9] = { 0xAAU, 0xB2U, 0xAFU, 0xA5U, 0xBAU, 0xB3U, 0xBFU, 0xB4U, 0 };
			const uint16_t uc[8] = { 0x0404U, 0x0406U, 0x0407U, 0x0490U, 0x0454U, 0x0456U, 0x0457U, 0x0491U };

			n = aesNameToField((const char *)cp, f);
			CHECK(n == 8U, "ЄІЇҐєіїґ -> 8 символів");
			for (unsigned i = 0U; i < 8U; i++)
			{
				CHECK((f[i * 2U] == (uint8_t)(uc[i] & 0xFFU)) && (f[(i * 2U) + 1U] == (uint8_t)(uc[i] >> 8)), "символ %u -> U+%04X (UTF-16LE)", i, (unsigned)uc[i]);
			}
			CHECK(memcmp(&f[16], "\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0", 16) == 0, "решта поля -- нулі");
			n = aesNameFromField(f, out);
			CHECK(n == 8U && memcmp(out, cp, 9) == 0, "назад: ЄІЇҐєіїґ");
		}

		n = aesNameToField("", f);
		CHECK(n == 0U && f[0] == 0U && f[31] == 0U, "порожнє ім'я -> усе поле нулі");

		{
			char sixteen[18];

			memset(sixteen, 'a', 16);
			sixteen[16] = 'Z';
			sixteen[17] = 0;
			n = aesNameToField(sixteen, f);
			CHECK(n == 16U && f[30] == 'a' && f[31] == 0U, "довше 16 обрізається до 16 (поле заповнене цілком)");
			n = aesNameFromField(f, out);
			CHECK(n == 16U && out[16] == 0 && out[15] == 'a', "16 символів без нуля читаються цілком, out[16] = 0");
		}

		n = aesNameToField("ab  ", f);
		CHECK(n == 2U && f[2] == 'b' && f[4] == 0U, "кінцеві пробіли відкидаються");
		n = aesNameToField("a\x01zz", f);
		CHECK(n == 1U && f[2] == 0U, "байт < 0x20 -- кінець імені");
		n = aesNameToField("a\x98" "b", f);
		CHECK(n == 3U && f[2] == '?' && f[3] == 0U && f[4] == 'b', "байта 0x98 нема в cp1251 -> '?'");

		/* стерта флеш (FF FF) -- кінець; сурогати/китайські -> '?' */
		memset(f, 0xFF, sizeof(f));
		CHECK(aesNameFromField(f, out) == 0U && out[0] == 0, "стерта флеш (FF) = порожнє ім'я");
		memset(f, 0, sizeof(f));
		f[0] = 'A'; f[2] = 0x2DU; f[3] = 0x4EU; f[4] = 0x00U; f[5] = 0xD8U; f[6] = 'B';   /* A, U+4E2D (中), U+D800 (сурогат), B */
		n = aesNameFromField(f, out);
		CHECK(n == 4U && out[0] == 'A' && out[1] == '?' && out[2] == '?' && out[3] == 'B', "поза cp1251 (中, сурогат) -> '?': %s", out);
		memset(f, 0, sizeof(f));
		f[0] = 'A'; f[2] = 0x05U; f[4] = 'C';
		n = aesNameFromField(f, out);
		CHECK(n == 3U && out[1] == '?', "керівний U+0005 -> '?'");

		/* стандартне ім'я = десяткове keyId */
		{
			uint8_t d[AESN_FIELD_LEN];

			memset(d, 0, sizeof(d));
			d[0] = '7';
			CHECK(aesNameIsDefault(7, d) && !aesNameIsDefault(8, d), "стандартне «7» для ключа 7, не для 8");
			memset(d, 0, sizeof(d));
			d[0] = '1'; d[2] = '2';
			CHECK(aesNameIsDefault(12, d) && !aesNameIsDefault(2, d) && !aesNameIsDefault(1, d), "стандартне «12» для ключа 12");
			memset(d, 0, sizeof(d));
			CHECK(aesNameIsDefault(3, d), "порожнє поле = імені нема");
			memset(d, 0xFF, sizeof(d));
			CHECK(aesNameIsDefault(3, d), "стерте поле (FF) = імені нема");
			memset(d, 0, sizeof(d));
			d[0] = '7'; d[2] = 'x';
			CHECK(!aesNameIsDefault(7, d), "«7x» -- власне ім'я");
		}

		/* оборотність cp1251 -> Unicode -> cp1251 для всіх байтів, що є в cp1251 */
		{
			bool ok = true;
			unsigned cnt = 0U;

			for (unsigned b = 0x20U; b < 256U; b++)
			{
				if (b == 0x98U) { continue; }
				if (aesNameUnicodeToCp1251(aesNameCp1251ToUnicode((uint8_t)b)) != (uint8_t)b) { ok = false; }
				cnt++;
			}
			CHECK(ok && cnt == 223U, "оборотність: 223 байти (0x20..0xFF без 0x98) проходять туди й назад");
		}
	}

	printf(fails ? "ПРОВАЛ: %d\n" : "ВСІ ПЕРЕВІРКИ ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
