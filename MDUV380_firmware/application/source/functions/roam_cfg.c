/*
 * roam_cfg.c -- R59: налаштування «Роумінгу» (custom-data блок №15). Див. roam_cfg.h.
 * Лише з -DENABLE_ROAM_RETRY.
 */
#include "functions/roam_cfg.h"

#if defined(ENABLE_ROAM_RETRY)

#include <string.h>

uint8_t roamListFromByte(uint8_t b)
{
	uint8_t n = (uint8_t)(b & ROAM_LIST_VALUE_MASK);

	if (((b & ROAM_LIST_TAG_MASK) != ROAM_LIST_TAG) || (n < 1U) || (n > ROAM_LISTS_COUNT))
	{
		return 0U;
	}

	return n;
}

uint8_t roamListToByte(uint8_t list)
{
	if ((list < 1U) || (list > ROAM_LISTS_COUNT))
	{
		return 0U;
	}

	return (uint8_t)(ROAM_LIST_TAG | list);
}

uint8_t roamCfgClampHops(uint8_t hops)
{
	if ((hops < ROAM_HOPS_MIN) || (hops > ROAM_HOPS_MAX))
	{
		return (uint8_t)ROAM_HOPS_DEFAULT;
	}

	return hops;
}

bool roamCfgParse(const roamOnFlashCfg_t *raw, bool *enabled, uint8_t *maxHops)
{
	if ((raw == NULL) || (enabled == NULL) || (maxHops == NULL) ||
			(memcmp(raw->magic, ROAM_CFG_MAGIC, 4) != 0) || (raw->version != ROAM_CFG_VERSION))
	{
		return false;
	}

	*enabled = (raw->enabled != 0U);
	*maxHops = roamCfgClampHops(raw->maxHops);

	return true;
}

void roamCfgBuild(roamOnFlashCfg_t *raw, bool enabled, uint8_t maxHops)
{
	memset(raw, 0, sizeof(*raw));
	memcpy(raw->magic, ROAM_CFG_MAGIC, 4);
	raw->version = (uint8_t)ROAM_CFG_VERSION;
	raw->enabled = (enabled ? 1U : 0U);
	raw->maxHops = roamCfgClampHops(maxHops);
}

/* R64: слот імені -> довжина (до першого байта < 0x20 або 16), далі кінцеві пробіли відкидаються. */
static unsigned nameSlotLen(const uint8_t *slot)
{
	unsigned n = 0U;

	while ((n < ROAM_NAME_LEN) && (slot[n] >= 0x20U))
	{
		n++;
	}
	while ((n > 0U) && (slot[n - 1U] == 0x20U))
	{
		n--;
	}

	return n;
}

unsigned roamNameDecode(const uint8_t *block, uint8_t list, char *out)
{
	unsigned n;

	out[0] = 0;

	if ((block == NULL) || (list < 1U) || (list > ROAM_LISTS_COUNT))
	{
		return 0U;
	}

	n = nameSlotLen(&block[(unsigned)(list - 1U) * ROAM_NAME_LEN]);
	memcpy(out, &block[(unsigned)(list - 1U) * ROAM_NAME_LEN], n);
	out[n] = 0;

	return n;
}

unsigned roamNameEncode(uint8_t *block, uint8_t list, const char *name)
{
	uint8_t slot[ROAM_NAME_LEN];
	unsigned n = 0U;

	if ((block == NULL) || (name == NULL) || (list < 1U) || (list > ROAM_LISTS_COUNT))
	{
		return 0U;
	}

	memset(slot, 0, sizeof(slot));
	while ((n < ROAM_NAME_LEN) && ((uint8_t)name[n] >= 0x20U))
	{
		slot[n] = (uint8_t)name[n];
		n++;
	}
	n = nameSlotLen(slot);
	memset(&slot[n], 0, ROAM_NAME_LEN - n);
	memcpy(&block[(unsigned)(list - 1U) * ROAM_NAME_LEN], slot, ROAM_NAME_LEN);

	return n;
}

#if !defined(ROAM_CFG_HOST_TEST)

#include "functions/codeplug.h"

bool roamNameGet(uint8_t list, char *out)
{
	uint8_t block[ROAM_NAMES_BLOCK_LEN];

	out[0] = 0;

	if ((list < 1U) || (list > ROAM_LISTS_COUNT))
	{
		return false;
	}

	memset(block, 0, sizeof(block));
	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_ROAM_NAMES, block, (int)sizeof(block)) == false)
	{
		return false;
	}

	(void)roamNameDecode(block, list, out);
	return true;
}

bool roamNameSet(uint8_t list, const char *name)
{
	uint8_t block[ROAM_NAMES_BLOCK_LEN];
	uint8_t want[ROAM_NAMES_BLOCK_LEN];

	if ((list < 1U) || (list > ROAM_LISTS_COUNT) || (name == NULL))
	{
		return false;
	}

	memset(block, 0, sizeof(block));
	(void)codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_ROAM_NAMES, block, (int)sizeof(block));   /* блоку нема -- нулі */

	memcpy(want, block, sizeof(want));
	(void)roamNameEncode(want, list, name);

	if (memcmp(want, block, sizeof(want)) == 0)
	{
		/* Нічого не міняється. Блоку на флеші може й не бути (порожнє ім'я порожнього) -- тоді писати нічого. */
		return true;
	}

	if (codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_ROAM_NAMES, want, (int)sizeof(want)) == false)
	{
		return false;
	}

	/* Перевірка перечитуванням (слот у флеші справді змінився). */
	memset(block, 0, sizeof(block));
	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_ROAM_NAMES, block, (int)sizeof(block)) == false)
	{
		return false;
	}

	return (memcmp(block, want, sizeof(block)) == 0);
}

/* Звичайна статична пам'ять (не CCM): читається раз на PTT, пишеться рідко. Нуль = «вимкнено»,
 * maxHops 0 віддається getter-ом як типове значення -- явної ініціалізації не потребує. */
static bool    s_enabled;
static uint8_t s_maxHops;

void roamCfgLoad(void)
{
	roamOnFlashCfg_t raw;
	bool en = false;
	uint8_t hops = (uint8_t)ROAM_HOPS_DEFAULT;

	memset(&raw, 0, sizeof(raw));

	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_ROAM_CFG, (uint8_t *)&raw, (int)sizeof(raw)) &&
			roamCfgParse(&raw, &en, &hops))
	{
		s_enabled = en;
		s_maxHops = hops;
	}
	else
	{
		s_enabled = false;
		s_maxHops = (uint8_t)ROAM_HOPS_DEFAULT;
	}
}

bool roamCfgIsEnabled(void)
{
	return s_enabled;
}

uint8_t roamCfgMaxHops(void)
{
	return roamCfgClampHops(s_maxHops);
}

bool roamCfgSave(bool enabled, uint8_t maxHops)
{
	roamOnFlashCfg_t cur;
	roamOnFlashCfg_t want;
	bool curEn = false;
	uint8_t curHops = 0U;

	roamCfgBuild(&want, enabled, maxHops);
	memset(&cur, 0, sizeof(cur));

	/* Знос флеша: якщо там уже саме це -- не пишемо. */
	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_ROAM_CFG, (uint8_t *)&cur, (int)sizeof(cur)) &&
			roamCfgParse(&cur, &curEn, &curHops) && (curEn == enabled) && (curHops == want.maxHops))
	{
		s_enabled = enabled;
		s_maxHops = want.maxHops;
		return true;
	}

	if (codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_ROAM_CFG, (uint8_t *)&want, (int)sizeof(want)))
	{
		s_enabled = enabled;
		s_maxHops = want.maxHops;
		return true;
	}

	return false;
}

#endif /* !ROAM_CFG_HOST_TEST */

#endif /* ENABLE_ROAM_RETRY */
