/*
 * test_roam_cfg.c -- R59: формат custom-data блоку «Роумінгу» (СПРАВЖНІЙ application/source/functions/roam_cfg.c).
 * Розбір/збірка/обмеження 1..5/типові значення. Збирається з -DENABLE_ROAM_RETRY -DROAM_CFG_HOST_TEST.
 * Той самий формат читає й пише CPS (tools/roam_cfg.py) -- розкладка перевіряється там тестом на ці самі байти.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/roam_cfg.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

int main(void)
{
	roamOnFlashCfg_t raw;
	bool en = true;
	uint8_t hops = 0;

	CHECK(sizeof(roamOnFlashCfg_t) == 8, "блок рівно 8 байт (є %u)", (unsigned)sizeof(roamOnFlashCfg_t));
	CHECK(ROAM_HOPS_MIN == 1U && ROAM_HOPS_MAX == 5U && ROAM_HOPS_DEFAULT == 2U, "межі 1..5, типово 2");

	roamCfgBuild(&raw, true, 3);
	CHECK(memcmp(raw.magic, "ROAM", 4) == 0 && raw.version == 1U && raw.enabled == 1U && raw.maxHops == 3U && raw.reserved == 0U, "збірка: ROAM, версія 1, увімкнено, 3 стрибки");
	{
		const uint8_t want[8] = { 'R', 'O', 'A', 'M', 1, 1, 3, 0 };
		CHECK(memcmp(&raw, want, 8) == 0, "точні байти: 52 4F 41 4D 01 01 03 00");
	}
	CHECK(roamCfgParse(&raw, &en, &hops) && en && hops == 3U, "розбір повертає те, що збирали");

	roamCfgBuild(&raw, false, 5);
	CHECK(roamCfgParse(&raw, &en, &hops) && !en && hops == 5U, "вимкнено, 5");

	roamCfgBuild(&raw, true, 0);
	CHECK(raw.maxHops == ROAM_HOPS_DEFAULT, "0 стрибків при збірці -> типове");
	roamCfgBuild(&raw, true, 9);
	CHECK(raw.maxHops == ROAM_HOPS_DEFAULT, "9 стрибків при збірці -> типове");

	roamCfgBuild(&raw, true, 3);
	raw.maxHops = 0U;
	CHECK(roamCfgParse(&raw, &en, &hops) && hops == ROAM_HOPS_DEFAULT, "розбір: 0 у блоці -> типове");
	raw.maxHops = 200U;
	CHECK(roamCfgParse(&raw, &en, &hops) && hops == ROAM_HOPS_DEFAULT, "розбір: 200 у блоці -> типове");
	raw.maxHops = 3U; raw.enabled = 7U;
	CHECK(roamCfgParse(&raw, &en, &hops) && en, "розбір: будь-яке ненульове enabled -> увімкнено");

	roamCfgBuild(&raw, true, 3);
	raw.magic[0] = 'X';
	CHECK(!roamCfgParse(&raw, &en, &hops), "чужий magic -> блоку нема");
	roamCfgBuild(&raw, true, 3);
	raw.version = 2U;
	CHECK(!roamCfgParse(&raw, &en, &hops), "інша версія -> блоку нема (типові значення)");
	memset(&raw, 0xFF, sizeof(raw));
	CHECK(!roamCfgParse(&raw, &en, &hops), "стерта флеш (FF) -> блоку нема");
	memset(&raw, 0, sizeof(raw));
	CHECK(!roamCfgParse(&raw, &en, &hops), "нулі -> блоку нема");
	CHECK(!roamCfgParse(NULL, &en, &hops) && !roamCfgParse(&raw, NULL, &hops) && !roamCfgParse(&raw, &en, NULL), "NULL безпечний");

	CHECK(roamCfgClampHops(1) == 1 && roamCfgClampHops(5) == 5 && roamCfgClampHops(0) == 2 && roamCfgClampHops(6) == 2, "clamp: 1,5 лишаються; 0,6 -> 2");

	/* ---- R60: номер списку роумінгу в байті 37 запису каналу (мітка 0xC0 | N) ---- */
	CHECK(ROAM_LISTS_COUNT == 10U && ROAM_LIST_BYTE_OFFSET == 37U && ROAM_LIST_TAG == 0xC0U && ROAM_LIST_TAG_MASK == 0xF0U, "списків 10; байт 37; мітка 0xC0");
	for (unsigned n = 1U; n <= 10U; n++)
	{
		CHECK(roamListToByte((uint8_t)n) == (0xC0U | n) && roamListFromByte(roamListToByte((uint8_t)n)) == n, "список %u <-> байт 0x%02X", n, 0xC0U | n);
	}
	CHECK(roamListToByte(0) == 0x00U, "список 0 -> байт 0x00");
	CHECK(roamListToByte(11) == 0x00U && roamListToByte(15) == 0x00U && roamListToByte(255) == 0x00U, "числа поза 1..10 -> байт 0x00 (не пишемо сміття)");
	{
		unsigned nonzero = 0U;
		bool onlyTagged = true;

		for (unsigned b = 0U; b < 256U; b++)
		{
			uint8_t l = roamListFromByte((uint8_t)b);

			if (l != 0U)
			{
				nonzero++;
				if ((b < 0xC1U) || (b > 0xCAU) || (l != (b & 0x0FU))) { onlyTagged = false; }
			}
		}
		CHECK(nonzero == 10U && onlyTagged, "з 256 значень байта списком читаються рівно 0xC1..0xCA");
	}
	CHECK(roamListFromByte(0x00) == 0 && roamListFromByte(0xFF) == 0 && roamListFromByte(0xA1) == 0 && roamListFromByte(0xC0) == 0 &&
			roamListFromByte(0xCB) == 0 && roamListFromByte(0xCF) == 0 && roamListFromByte(0x01) == 0 && roamListFromByte(0x0A) == 0,
			"сміття (0x00, 0xFF, 0xA1 -- мітка AES, 0xC0, 0xCB, 0xCF, 0x01, 0x0A) = «списку нема»");

	/* ---- R64: імена списків (блок 16: 10 x 16 Б, cp1251, хвіст 0x00) ---- */
	{
		uint8_t blk[ROAM_NAMES_BLOCK_LEN];
		char out[ROAM_NAME_LEN + 1U];
		const uint8_t uk[8] = { 0xAAU, 0xB2U, 0xAFU, 0xA5U, 0xBAU, 0xB3U, 0xBFU, 0xB4U };   /* ЄІЇҐєіїґ */
		char name[ROAM_NAME_LEN + 8U];

		CHECK(ROAM_NAME_LEN == 16U && ROAM_NAMES_BLOCK_LEN == 160U, "ім'я 16 Б, блок 160 Б");

		memset(blk, 0xEEU, sizeof(blk));
		CHECK(roamNameEncode(blk, 1, "\xCA\xE8\xBF\xE2") == 4U && memcmp(blk, "\xCA\xE8\xBF\xE2\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00", 16) == 0, "Encode: «Київ» (CA E8 BF E2) + хвіст 0x00 до кінця слота");
		CHECK(blk[16] == 0xEEU && blk[159] == 0xEEU, "Encode: чужі слоти не чіпає");
		CHECK(roamNameDecode(blk, 1, out) == 4U && memcmp(out, "\xCA\xE8\xBF\xE2", 5) == 0, "Decode: назад «Київ», завершено нулем");

		memset(blk, 0, sizeof(blk));
		memcpy(name, uk, 8);
		name[8] = 0;
		CHECK(roamNameEncode(blk, 3, name) == 8U && memcmp(&blk[32], uk, 8) == 0 && blk[40] == 0U && blk[47] == 0U, "ЄІЇҐєіїґ: слот 3 = зсув 32, хвіст 0x00");
		CHECK(roamNameDecode(blk, 3, out) == 8U && memcmp(out, uk, 8) == 0, "ЄІЇҐєіїґ читається назад");
		CHECK(roamNameDecode(blk, 2, out) == 0U && out[0] == 0, "порожній слот -> довжина 0, out = \"\"");

		memset(name, 0xFF, 16);   /* 16 x «я» (0xFF) */
		name[16] = 'Z';           /* зайвий символ відкидається */
		name[17] = 0;
		memset(blk, 0, sizeof(blk));
		CHECK(roamNameEncode(blk, 10, name) == 16U && blk[144] == 0xFFU && blk[159] == 0xFFU, "довше 16 обрізається до 16; слот 10 = зсув 144");
		CHECK(roamNameDecode(blk, 10, out) == 16U && out[16] == 0 && (uint8_t)out[0] == 0xFFU, "16 символів без хвоста читаються цілком, out[16] = 0");

		memset(blk, 0xEEU, sizeof(blk));
		CHECK(roamNameEncode(blk, 4, "ab   ") == 2U && blk[48] == 'a' && blk[49] == 'b' && blk[50] == 0U, "кінцеві пробіли відкидаються");
		CHECK(roamNameEncode(blk, 4, "   ") == 0U && blk[48] == 0U, "самі пробіли = порожнє ім'я, слот обнулено");
		CHECK(roamNameEncode(blk, 4, "a\x01zz") == 1U && blk[49] == 0U, "байт < 0x20 -- кінець імені");

		memset(blk, 0xEEU, sizeof(blk));
		CHECK(roamNameEncode(blk, 0, "x") == 0U && roamNameEncode(blk, 11, "x") == 0U && blk[0] == 0xEEU && blk[159] == 0xEEU, "список 0 і 11: блок не змінено");
		CHECK(roamNameDecode(blk, 0, out) == 0U && out[0] == 0 && roamNameDecode(blk, 11, out) == 0U && out[0] == 0, "Decode: список 0 і 11 -> порожньо");

		memset(blk, 0, sizeof(blk));
		blk[0] = 'A'; blk[1] = 'b'; blk[2] = 0x07U; blk[3] = 'c';
		memset(&blk[16], 'X', 16);
		blk[32] = ' '; blk[33] = ' ';
		CHECK(roamNameDecode(blk, 1, out) == 2U && strcmp(out, "Ab") == 0, "Decode: сміття після керівного байта відкидається");
		CHECK(roamNameDecode(blk, 2, out) == 16U && strlen(out) == 16U, "Decode: повний слот без нуля");
		CHECK(roamNameDecode(blk, 3, out) == 0U, "Decode: самі пробіли = порожньо");
		CHECK(roamNameDecode(NULL, 1, out) == 0U && out[0] == 0, "Decode: NULL безпечний");
		CHECK(roamNameEncode(NULL, 1, "x") == 0U && roamNameEncode(blk, 1, NULL) == 0U, "Encode: NULL безпечний");
	}

	printf(fails ? "ПРОВАЛ: %d\n" : "ВСІ ПЕРЕВІРКИ ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
