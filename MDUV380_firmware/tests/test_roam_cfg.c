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

	printf(fails ? "ПРОВАЛ: %d\n" : "ВСІ ПЕРЕВІРКИ ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
