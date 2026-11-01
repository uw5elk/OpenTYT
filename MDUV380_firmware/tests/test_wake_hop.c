/*
 * test_wake_hop.c -- R58: вибір каналу для стрибка (СПРАВЖНІЙ application/source/functions/wake_hop_sel.c).
 * Чиста логіка: придатність каналу, ліміт стрибків, кільце, один оберт. Збирається з
 * -DENABLE_WAKE_HOP_TEST -DWAKE_HOP_HOST_TEST.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/wake_hop.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static wakeHopChan_t good(void)
{
	wakeHopChan_t c = { true, false, false, true, true, false, 43000000U + 5000U, 43000000U };
	return c;
}

/* Модель зони: масив ознак «придатний», лічильник викликів колбека. */
typedef struct { const bool *ok; unsigned calls; unsigned lastPos; } zone_t;
static bool zoneUsable(unsigned pos, void *ctx)
{
	zone_t *z = (zone_t *)ctx;
	z->calls++;
	z->lastPos = pos;
	return z->ok[pos];
}

int main(void)
{
	wakeHopChan_t c = good();

	CHECK(wakeHopChannelUsable(&c), "базовий кандидат придатний");
	CHECK(wakeHopChannelUsable(NULL) == false, "NULL -> false");

	c = good(); c.digital = false;   CHECK(!wakeHopChannelUsable(&c), "аналоговий -- ні");
	c = good(); c.forceDmo = true;   CHECK(!wakeHopChannelUsable(&c), "FORCE_DMO -- ні");
	c = good(); c.rxOnly = true;     CHECK(!wakeHopChannelUsable(&c), "лише приймання -- ні");
	c = good(); c.txAllowed = false; CHECK(!wakeHopChannelUsable(&c), "передача заборонена діапазоном -- ні");
	c = good(); c.inBand = false;    CHECK(!wakeHopChannelUsable(&c), "поза діапазоном -- ні");
	c = good(); c.inhibited = true;  CHECK(!wakeHopChannelUsable(&c), "віддалене блокування -- ні");
	c = good(); c.txFreq = c.rxFreq; CHECK(!wakeHopChannelUsable(&c), "rx == tx (симплекс/DMO) -- ні");
	c = good(); c.rxFreq = 0;        CHECK(!wakeHopChannelUsable(&c), "rx == 0 -- ні");

	CHECK(wakeHopMayHop(0) && wakeHopMayHop(1), "0 і 1 стрибок зроблено -- можна ще");
	CHECK(!wakeHopMayHop(2) && !wakeHopMayHop(3) && !wakeHopMayHop(255), "2 і більше -- вже не можна (макс. %u)", (unsigned)WAKE_HOP_MAX_HOPS);

	CHECK(wakeHopRingPos(0, 5, 1) == 1 && wakeHopRingPos(4, 5, 1) == 0 && wakeHopRingPos(3, 5, 4) == 2, "кільце: 0+1, 4+1 -> 0, 3+4 -> 2");
	CHECK(wakeHopRingPos(0, 0, 3) == 0, "count == 0 -> 0 без ділення на нуль");

	/* Пошук: наступний придатний по колу. */
	{
		bool ok[6] = { true, false, true, false, false, true };
		zone_t z = { ok, 0, 0 };
		unsigned out = 99;

		CHECK(wakeHopFindNext(0, 6, zoneUsable, &z, &out) && out == 2, "з 0 -> 2 (1 непридатний)");
		CHECK(wakeHopFindNext(2, 6, zoneUsable, &z, &out) && out == 5, "з 2 -> 5");
		CHECK(wakeHopFindNext(5, 6, zoneUsable, &z, &out) && out == 0, "з 5 -> 0 (по колу)");
	}
	/* Жодного придатного (окрім стартового): false, і стартову позицію не питає. */
	{
		bool ok[4] = { true, false, false, false };
		zone_t z = { ok, 0, 0 };
		unsigned out = 99;

		CHECK(!wakeHopFindNext(0, 4, zoneUsable, &z, &out), "лише стартовий придатний -> false");
		CHECK(z.calls == 3, "перевірено рівно count-1 = 3 позиції (один оберт), а не %u", z.calls);
		CHECK(out == 99, "*outPos не змінено при false");
	}
	/* Один оберт: стартової позиції не повертаємо навіть якщо вона придатна. */
	{
		bool ok[3] = { true, true, true };
		zone_t z = { ok, 0, 0 };
		unsigned out = 99;

		CHECK(wakeHopFindNext(1, 3, zoneUsable, &z, &out) && out == 2, "з 1 -> 2");
		bool ok2[2] = { false, true };
		zone_t z2 = { ok2, 0, 0 };
		CHECK(!wakeHopFindNext(1, 2, zoneUsable, &z2, &out), "зона з 2 каналів, інший непридатний -> false (на стартовий не повертаємось)");
	}
	/* Ліміт сканування і вироджені входи. */
	{
		static bool ok[1024];
		zone_t z = { ok, 0, 0 };
		unsigned out = 99;

		memset(ok, 0, sizeof(ok));
		ok[900] = true;
		CHECK(!wakeHopFindNext(0, 1024, zoneUsable, &z, &out), "придатний лише за межею ліміту сканування -> false");
		CHECK(z.calls == WAKE_HOP_SCAN_CAP, "переглянуто рівно WAKE_HOP_SCAN_CAP = %u позицій (було %u)", (unsigned)WAKE_HOP_SCAN_CAP, z.calls);
		CHECK(!wakeHopFindNext(0, 1, zoneUsable, &z, &out), "count == 1 -> false");
		CHECK(!wakeHopFindNext(0, 0, zoneUsable, &z, &out), "count == 0 -> false");
		CHECK(!wakeHopFindNext(0, 4, NULL, &z, &out), "fn == NULL -> false");
		CHECK(!wakeHopFindNext(0, 4, zoneUsable, &z, NULL), "outPos == NULL -> false");
	}

	printf(fails ? "ПРОВАЛ: %d\n" : "ВСІ ПЕРЕВІРКИ ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
