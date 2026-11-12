/*
 * dual_channel.c -- R97: «Подвійний прийом» -- сховище (custom-data блок 18) і чиста логіка. Див. dual_channel.h.
 * Лише з -DENABLE_DUAL_CHANNEL (українська збірка UV380); хостовий тест -- з -DDUAL_CHANNEL_HOST_TEST.
 */
#include "functions/dual_channel.h"

#if defined(DUAL_CHANNEL_ENABLED) || defined(DUAL_CHANNEL_HOST_TEST)

#include <string.h>

bool dcCfgParse(const dcOnFlashCfg_t *raw, bool *enabled, bool *pointerB, uint16_t *chB)
{
	uint16_t ch;

	*enabled = false;
	*pointerB = false;
	*chB = 0U;

	if ((raw == NULL) || (raw->version != DC_CFG_VERSION))
	{
		return false;
	}

	ch = (uint16_t)(raw->chBLo | ((uint16_t)raw->chBHi << 8));
	*chB = (((ch >= DC_CH_MIN) && (ch <= DC_CH_MAX)) ? ch : 0U);
	*enabled = ((raw->flags & DC_FLAG_ENABLED) != 0U);
	*pointerB = ((raw->flags & DC_FLAG_POINTER_B) != 0U);
	return true;
}

void dcCfgBuild(dcOnFlashCfg_t *raw, bool enabled, bool pointerB, uint16_t chB)
{
	if ((chB < DC_CH_MIN) || (chB > DC_CH_MAX))
	{
		chB = 0U;
	}

	memset(raw, 0, sizeof(*raw));
	raw->version = (uint8_t)DC_CFG_VERSION;
	raw->flags = (uint8_t)((enabled ? DC_FLAG_ENABLED : 0U) | (pointerB ? DC_FLAG_POINTER_B : 0U));
	raw->chBLo = (uint8_t)(chB & 0xFFU);
	raw->chBHi = (uint8_t)(chB >> 8);
}

dcPairCheck_t dcCheckPair(uint16_t chA, uint16_t chB, bool bInUse)
{
	if ((chB < DC_CH_MIN) || (chB > DC_CH_MAX))
	{
		return DC_PAIR_NO_B;
	}

	if (bInUse == false)
	{
		return DC_PAIR_B_DELETED;
	}

	if (chB == chA)
	{
		return DC_PAIR_B_IS_A;
	}

	return DC_PAIR_OK;
}

bool dcTxOnB(bool activity, bool onB, bool pointerB)
{
	return (activity ? onB : pointerB);
}

int dcStepPos(int n, int fromPos, int dir, uint16_t skip, dcChanAt_t at, void *ctx)
{
	int pos;

	if ((n <= 0) || (at == NULL))
	{
		return -1;
	}

	dir = ((dir < 0) ? -1 : 1);
	pos = (((fromPos < 0) || (fromPos >= n)) ? ((dir > 0) ? (n - 1) : 0) : fromPos);

	for (int i = 0; i < n; i++)
	{
		uint16_t ch;

		pos = ((pos + dir + n) % n);
		ch = at(pos, ctx);

		if ((ch != 0U) && (ch != skip))
		{
			return pos;
		}
	}

	return -1;
}

int dcFindPos(int n, uint16_t ch, dcChanAt_t at, void *ctx)
{
	if ((ch == 0U) || (at == NULL))
	{
		return -1;
	}

	for (int pos = 0; pos < n; pos++)
	{
		if (at(pos, ctx) == ch)
		{
			return pos;
		}
	}

	return -1;
}

#endif /* DUAL_CHANNEL_ENABLED || DUAL_CHANNEL_HOST_TEST */

#if defined(DUAL_CHANNEL_ENABLED)

#include "functions/codeplug.h"

#define DC_SAVE_DELAY_MS    3000U

/* 8 байт звичайної RAM (не CCM; .bss -> нулі = «вимкнено»). */
static struct
{
	uint32_t dirtyMs;       /* коли востаннє змінено покажчик/B (для відкладеного запису) */
	uint16_t chB;
	uint8_t  enabled  : 1;
	uint8_t  pointerB : 1;
	uint8_t  onB      : 1;
	uint8_t  txHold   : 1;
	uint8_t  dirty    : 1;
	uint8_t  menuOn   : 1;
} s_dc;

void dcLoad(void)
{
	dcOnFlashCfg_t raw;
	bool en, ptr;
	uint16_t ch;

	memset(&raw, 0, sizeof(raw));

	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_DUAL_CHANNEL_CFG, (uint8_t *)&raw, (int)sizeof(raw)) == false)
	{
		memset(&raw, 0, sizeof(raw));   /* блоку нема -- нечинна версія -> типові значення */
	}

	(void)dcCfgParse(&raw, &en, &ptr, &ch);
	s_dc.enabled = (en ? 1U : 0U);
	s_dc.pointerB = (ptr ? 1U : 0U);
	s_dc.chB = ch;
	s_dc.onB = 0U;
	s_dc.txHold = 0U;
	s_dc.dirty = 0U;
}

bool dcIsEnabled(void)
{
	return (s_dc.enabled != 0U);
}

bool dcPointerB(void)
{
	return (s_dc.pointerB != 0U);
}

uint16_t dcChannelB(void)
{
	return s_dc.chB;
}

bool dcIsOnB(void)
{
	return (s_dc.onB != 0U);
}

void dcSetOnB(bool onB)
{
	s_dc.onB = (onB ? 1U : 0U);
}

bool dcTxHoldPending(void)
{
	return (s_dc.txHold != 0U);
}

void dcSetTxHold(bool hold)
{
	s_dc.txHold = (hold ? 1U : 0U);
}

bool dcMenuValue(void)
{
	return (s_dc.menuOn != 0U);
}

void dcSetMenuValue(bool on)
{
	s_dc.menuOn = (on ? 1U : 0U);
}

/* Записати блок, якщо на флеші не те саме (знос). */
bool dcFlush(void)
{
	dcOnFlashCfg_t cur;
	dcOnFlashCfg_t want;

	dcCfgBuild(&want, (s_dc.enabled != 0U), (s_dc.pointerB != 0U), s_dc.chB);
	memset(&cur, 0, sizeof(cur));
	s_dc.dirty = 0U;

	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_DUAL_CHANNEL_CFG, (uint8_t *)&cur, (int)sizeof(cur)) &&
			(memcmp(&cur, &want, sizeof(want)) == 0))
	{
		return true;
	}

	return codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_DUAL_CHANNEL_CFG, (uint8_t *)&want, (int)sizeof(want));
}

void dcFlushPending(void)
{
	if (s_dc.dirty != 0U)
	{
		(void)dcFlush();
	}
}

static void markDirty(void)
{
	s_dc.dirty = 1U;
	s_dc.dirtyMs = 0U;   /* відлік почне dcSaveIfDue() з першого виклику: тут часу не знаємо */
}

bool dcSetEnabled(bool on, bool persistNow)
{
	s_dc.enabled = (on ? 1U : 0U);

	if (persistNow)
	{
		return dcFlush();
	}

	markDirty();
	return true;
}

void dcSetPointerB(bool pointerB)
{
	if ((s_dc.pointerB != 0U) != pointerB)
	{
		s_dc.pointerB = (pointerB ? 1U : 0U);
		markDirty();
	}
}

bool dcSetChannelB(uint16_t chB, bool persistNow)
{
	s_dc.chB = (((chB >= DC_CH_MIN) && (chB <= DC_CH_MAX)) ? chB : 0U);

	if (persistNow)
	{
		return dcFlush();
	}

	markDirty();
	return true;
}

void dcSaveIfDue(uint32_t nowMs)
{
	if (s_dc.dirty == 0U)
	{
		return;
	}

	if (s_dc.dirtyMs == 0U)
	{
		s_dc.dirtyMs = ((nowMs == 0U) ? 1U : nowMs);
		return;
	}

	if ((uint32_t)(nowMs - s_dc.dirtyMs) >= DC_SAVE_DELAY_MS)
	{
		(void)dcFlush();
	}
}

#endif /* DUAL_CHANNEL_ENABLED */
