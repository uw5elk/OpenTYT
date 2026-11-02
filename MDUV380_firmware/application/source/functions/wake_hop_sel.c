/*
 * wake_hop_sel.c -- R59: чиста логіка вибору каналу зі списку роумінгу (без заліза; хостовий тест).
 * Див. wake_hop.h. Лише з -DENABLE_ROAM_RETRY.
 */
#include "functions/wake_hop.h"
#include <stddef.h>

#if defined(ENABLE_ROAM_RETRY)

bool wakeHopChannelUsable(const wakeHopChan_t *c)
{
	if (c == NULL)
	{
		return false;
	}

	return (c->digital && (c->forceDmo == false) && (c->rxOnly == false) && c->txAllowed &&
			c->inBand && (c->inhibited == false) && (c->rxFreq != 0U) && (c->rxFreq != c->txFreq));
}

void wakeHopTriedReset(wakeHopTried_t *t)
{
	if (t != NULL)
	{
		t->n = 0U;
		for (unsigned i = 0U; i < WAKE_HOP_TRIED_MAX; i++)
		{
			t->rx[i] = 0U;
			t->tx[i] = 0U;
			t->cc[i] = 0U;
		}
	}
}

bool wakeHopTriedHas(const wakeHopTried_t *t, uint32_t rx, uint32_t tx, uint8_t cc)
{
	if (t == NULL)
	{
		return false;
	}

	for (unsigned i = 0U; (i < t->n) && (i < WAKE_HOP_TRIED_MAX); i++)
	{
		if ((t->rx[i] == rx) && (t->tx[i] == tx) && (t->cc[i] == cc))
		{
			return true;
		}
	}

	return false;
}

bool wakeHopTriedAdd(wakeHopTried_t *t, uint32_t rx, uint32_t tx, uint8_t cc)
{
	if ((t == NULL) || (t->n >= WAKE_HOP_TRIED_MAX))
	{
		return false;
	}

	t->rx[t->n] = rx;
	t->tx[t->n] = tx;
	t->cc[t->n] = cc;
	t->n++;

	return true;
}

bool wakeHopCandidateOk(const wakeHopChan_t *c, const wakeHopTried_t *t)
{
	return (wakeHopChannelUsable(c) && (wakeHopTriedHas(t, c->rxFreq, c->txFreq, c->colourCode) == false));
}

bool wakeHopMayRoam(bool cfgEnabled, bool currentInList)
{
	return (cfgEnabled && currentInList);
}

bool wakeHopMayHop(uint8_t hopsDone, uint8_t maxHops)
{
	uint8_t lim = maxHops;

	if (lim < ROAM_HOPS_MIN)
	{
		lim = ROAM_HOPS_MIN;
	}
	if (lim > ROAM_HOPS_MAX)
	{
		lim = ROAM_HOPS_MAX;
	}

	return (hopsDone < lim);
}

bool wakeHopShouldRestore(bool away, bool success)
{
	return (away && (success == false));
}

bool wakeHopFindNext(unsigned startNum, unsigned minNum, unsigned maxNum, wakeHopCandFn fn, void *ctx, unsigned *outNum)
{
	if ((fn == NULL) || (outNum == NULL) || (minNum == 0U) || (maxNum <= minNum) ||
			(startNum < minNum) || (startNum > maxNum))
	{
		return false;
	}

	unsigned span = (maxNum - minNum) + 1U;

	for (unsigned k = 1U; k < span; k++)   /* один оберт; k == span повернуло б на стартовий */
	{
		unsigned num = minNum + (((startNum - minNum) + k) % span);

		if (fn(num, ctx))
		{
			*outNum = num;
			return true;
		}
	}

	return false;
}

#endif /* ENABLE_ROAM_RETRY */
