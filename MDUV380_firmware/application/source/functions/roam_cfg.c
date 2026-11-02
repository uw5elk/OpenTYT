/*
 * roam_cfg.c -- R59: налаштування «Роумінгу» (custom-data блок №15). Див. roam_cfg.h.
 * Лише з -DENABLE_ROAM_RETRY.
 */
#include "functions/roam_cfg.h"

#if defined(ENABLE_ROAM_RETRY)

#include <string.h>

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

#if !defined(ROAM_CFG_HOST_TEST)

#include "functions/codeplug.h"

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
