/*
 * wake_hop_sel.c -- R58: чиста логіка вибору каналу для стрибка (без заліза; хостовий тест).
 * Див. wake_hop.h. Лише з -DENABLE_WAKE_HOP_TEST.
 */
#include "functions/wake_hop.h"
#include <stddef.h>

#if defined(ENABLE_WAKE_HOP_TEST)

bool wakeHopChannelUsable(const wakeHopChan_t *c)
{
	if (c == NULL)
	{
		return false;
	}

	return (c->digital && (c->forceDmo == false) && (c->rxOnly == false) && c->txAllowed &&
			c->inBand && (c->inhibited == false) && (c->rxFreq != 0U) && (c->rxFreq != c->txFreq));
}

bool wakeHopMayHop(uint8_t hopsDone)
{
	return (hopsDone < WAKE_HOP_MAX_HOPS);
}

unsigned wakeHopRingPos(unsigned start, unsigned count, unsigned k)
{
	return ((count == 0U) ? 0U : ((start + k) % count));
}

bool wakeHopFindNext(unsigned start, unsigned count, wakeHopUsableFn fn, void *ctx, unsigned *outPos)
{
	if ((fn == NULL) || (outPos == NULL) || (count < 2U))
	{
		return false;
	}

	unsigned steps = count - 1U;   /* один оберт, без стартової позиції */

	if (steps > WAKE_HOP_SCAN_CAP)
	{
		steps = WAKE_HOP_SCAN_CAP;
	}

	for (unsigned k = 1U; k <= steps; k++)
	{
		unsigned pos = wakeHopRingPos(start, count, k);

		if (fn(pos, ctx))
		{
			*outPos = pos;
			return true;
		}
	}

	return false;
}

#endif /* ENABLE_WAKE_HOP_TEST */
