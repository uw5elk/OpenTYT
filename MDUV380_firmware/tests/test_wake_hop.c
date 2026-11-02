/*
 * test_wake_hop.c -- R59: вибір каналу зі СПИСКУ РОУМІНГУ (СПРАВЖНІЙ application/source/functions/wake_hop_sel.c).
 * Чиста логіка: придатність каналу, випробувані (rx, tx, колір-код), ліміт стрибків, кільце по номерах, один оберт,
 * «роумити лише якщо поточний у списку», «повертати вихідний лише без успіху». Збирається з
 * -DENABLE_ROAM_RETRY -DWAKE_HOP_HOST_TEST -DROAM_CFG_HOST_TEST.
 *
 * Клей wake_hop.c (кодплаг, трансівер) на хості не збирається; тут його цикл повторено в simulate() з тих самих
 * чистих функцій -- мутанти (mutants_wake.py) ламають саме їх.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/wake_hop.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

#define NCH 1024U

typedef struct
{
	bool inList;
	bool alive;            /* ретранслятор на цьому каналі відповідає на пробудження */
	wakeHopChan_t info;
} ch_t;

static ch_t tbl[NCH + 1U];

static wakeHopChan_t goodInfo(uint32_t rx, uint8_t cc)
{
	wakeHopChan_t c = { true, false, false, true, true, false, rx, rx - 5000U, cc };   /* ретранслятор: rx != tx */
	return c;
}

static void reset(void)
{
	memset(tbl, 0, sizeof(tbl));
	for (unsigned i = 1U; i <= NCH; i++)
	{
		tbl[i].info = goodInfo(43000000U + (i * 12500U), 1U);   /* кожен канал -- своя пара частот */
	}
}

static void setList(const unsigned *nums, unsigned n)
{
	for (unsigned i = 0U; i < n; i++) { tbl[nums[i]].inList = true; }
}

typedef struct
{
	bool roamed;           /* взагалі пробували стрибати */
	unsigned hops;
	unsigned path[8];
	bool success;
	bool restored;         /* вихідний канал повернуто */
	unsigned finalChan;    /* де рація опинилась у кінці PTT */
} res_t;

static unsigned badCalls;   /* скільки разів колбек спитали про номер поза 1..NCH */

static bool candFn(unsigned num, void *ctx)
{
	if ((num < 1U) || (num > NCH))
	{
		badCalls++;
		return false;
	}

	return tbl[num].inList && wakeHopCandidateOk(&tbl[num].info, (const wakeHopTried_t *)ctx);
}

/* Повторює цикл wake_hop.c: wakeHopBegin() + wakeHopTry() після кожного FAILED + wakeHopRestore(). Вихідний канал мертвий. */
static res_t simulate(unsigned cur, bool enabled, unsigned maxHops)
{
	res_t r;
	wakeHopTried_t t;
	unsigned at = cur;
	bool away = false;

	memset(&r, 0, sizeof(r));
	wakeHopTriedReset(&t);

	if (wakeHopMayRoam(enabled, tbl[cur].inList))
	{
		r.roamed = true;
		(void)wakeHopTriedAdd(&t, tbl[cur].info.rxFreq, tbl[cur].info.txFreq, tbl[cur].info.colourCode);

		/* guard: у справжньому коді цикл обмежений FAILED-ом кожного каналу; тут -- запобіжник від зациклення мутантів */
		for (unsigned guard = 0U; (guard < 40U) && wakeHopMayHop((uint8_t)r.hops, (uint8_t)maxHops); guard++)
		{
			unsigned next = 0U;

			if (wakeHopFindNext(at, 1U, NCH, candFn, &t, &next) == false)
			{
				break;
			}

			(void)wakeHopTriedAdd(&t, tbl[next].info.rxFreq, tbl[next].info.txFreq, tbl[next].info.colourCode);
			at = next;
			away = true;
			if (r.hops < 8U) { r.path[r.hops] = next; }
			r.hops++;

			if (tbl[next].alive)
			{
				r.success = true;
				break;
			}
		}
	}

	r.restored = wakeHopShouldRestore(away, r.success);
	r.finalChan = r.restored ? cur : at;
	return r;
}

int main(void)
{
	wakeHopChan_t c = goodInfo(43000000U, 1U);

	/* ---- придатність ---- */
	CHECK(wakeHopChannelUsable(&c), "базовий кандидат придатний");
	CHECK(wakeHopChannelUsable(NULL) == false, "NULL -> false");
	c = goodInfo(43000000U, 1U); c.digital = false;   CHECK(!wakeHopChannelUsable(&c), "аналоговий -- ні");
	c = goodInfo(43000000U, 1U); c.forceDmo = true;   CHECK(!wakeHopChannelUsable(&c), "FORCE_DMO -- ні");
	c = goodInfo(43000000U, 1U); c.rxOnly = true;     CHECK(!wakeHopChannelUsable(&c), "лише приймання -- ні");
	c = goodInfo(43000000U, 1U); c.txAllowed = false; CHECK(!wakeHopChannelUsable(&c), "передача заборонена діапазоном -- ні");
	c = goodInfo(43000000U, 1U); c.inBand = false;    CHECK(!wakeHopChannelUsable(&c), "поза діапазоном -- ні");
	c = goodInfo(43000000U, 1U); c.inhibited = true;  CHECK(!wakeHopChannelUsable(&c), "віддалене блокування -- ні");
	c = goodInfo(43000000U, 1U); c.txFreq = c.rxFreq; CHECK(!wakeHopChannelUsable(&c), "rx == tx (симплекс) -- ні");
	c = goodInfo(43000000U, 1U); c.rxFreq = 0;        CHECK(!wakeHopChannelUsable(&c), "rx == 0 -- ні");

	/* ---- ліміт стрибків ---- */
	CHECK(wakeHopMayHop(0, 2) && wakeHopMayHop(1, 2) && !wakeHopMayHop(2, 2) && !wakeHopMayHop(3, 2), "ліміт 2: 0 і 1 можна, 2 -- вже ні");
	CHECK(wakeHopMayHop(0, 1) && !wakeHopMayHop(1, 1), "ліміт 1: один стрибок");
	CHECK(wakeHopMayHop(4, 5) && !wakeHopMayHop(5, 5), "ліміт 5: п'ятий можна, шостого ні");
	CHECK(wakeHopMayHop(0, 0) && !wakeHopMayHop(1, 0), "ліміт 0 -> як 1 (нижня межа)");
	CHECK(wakeHopMayHop(4, 99) && !wakeHopMayHop(5, 99), "ліміт 99 -> як 5 (верхня межа)");

	/* ---- множина випробуваних ---- */
	{
		wakeHopTried_t t;
		wakeHopTriedReset(&t);
		CHECK(!wakeHopTriedHas(&t, 1, 2, 3), "порожня множина нічого не містить");
		CHECK(wakeHopTriedAdd(&t, 100, 200, 3) && wakeHopTriedHas(&t, 100, 200, 3), "додано -- є");
		CHECK(!wakeHopTriedHas(&t, 101, 200, 3), "інший rx -- не збіг");
		CHECK(!wakeHopTriedHas(&t, 100, 201, 3), "інший tx -- не збіг");
		CHECK(!wakeHopTriedHas(&t, 100, 200, 4), "інший колір-код -- не збіг");
		for (unsigned i = 1U; i < WAKE_HOP_TRIED_MAX; i++) { CHECK(wakeHopTriedAdd(&t, 1000U + i, 2000U + i, 1), "місце №%u є", i + 1U); }
		CHECK(!wakeHopTriedAdd(&t, 9, 9, 9), "переповнення -> false (місткість %u)", (unsigned)WAKE_HOP_TRIED_MAX);
		CHECK(!wakeHopTriedHas(NULL, 1, 2, 3) && !wakeHopTriedAdd(NULL, 1, 2, 3), "NULL безпечний");
	}

	/* ---- кільце по номерах ---- */
	{
		reset();
		const unsigned L[] = { 5, 10, 20 };
		setList(L, 3);
		wakeHopTried_t t;
		unsigned out = 0U;

		wakeHopTriedReset(&t);
		CHECK(wakeHopFindNext(5, 1, NCH, candFn, &t, &out) && out == 10, "з 5 -> 10");
		CHECK(wakeHopFindNext(10, 1, NCH, candFn, &t, &out) && out == 20, "з 10 -> 20");
		CHECK(wakeHopFindNext(20, 1, NCH, candFn, &t, &out) && out == 5, "з 20 -> 5 (по колу)");
		CHECK(wakeHopFindNext(7, 1, NCH, candFn, &t, &out) && out == 10, "стартовий номер не в списку: з 7 -> 10");
		CHECK(wakeHopFindNext(1024, 1, NCH, candFn, &t, &out) && out == 5, "з 1024 -> 5 (обгортка через межу)");
		CHECK(badCalls == 0U, "колбек ніколи не питали про номер поза 1..%u (було %u разів)", NCH, badCalls);

		/* Один оберт: сам стартовий номер не повертається, навіть якщо він єдиний у списку. */
		reset(); { const unsigned S[] = { 5 }; setList(S, 1); }
		wakeHopTriedReset(&t);
		out = 77U;
		CHECK(!wakeHopFindNext(5, 1, NCH, candFn, &t, &out) && out == 77U, "єдиний канал у списку, старт на ньому -> false (не повертаємось на себе)");
		/* Останній крок оберту: кандидат прямо перед стартом. */
		reset(); { const unsigned P[] = { 19, 20 }; setList(P, 2); }
		wakeHopTriedReset(&t);
		CHECK(wakeHopFindNext(20, 1, NCH, candFn, &t, &out) && out == 19, "кандидат прямо перед стартом (19 перед 20) знаходиться наприкінці оберту");
		reset(); { const unsigned P[] = { 1, 1024 }; setList(P, 2); }
		wakeHopTriedReset(&t);
		CHECK(wakeHopFindNext(1, 1, NCH, candFn, &t, &out) && out == 1024, "з 1 -> 1024 (протилежний край)");
		CHECK(wakeHopFindNext(1024, 1, NCH, candFn, &t, &out) && out == 1, "з 1024 -> 1");
		CHECK(badCalls == 0U, "і на краях діапазону колбек не питали про номер поза 1..%u (було %u)", NCH, badCalls);
		out = 77U;
		CHECK(!wakeHopFindNext(0, 1, NCH, candFn, &t, &out) && !wakeHopFindNext(1025, 1, NCH, candFn, &t, &out), "старт поза діапазоном -> false");
		CHECK(!wakeHopFindNext(5, 1, NCH, NULL, &t, &out) && !wakeHopFindNext(5, 1, NCH, candFn, &t, NULL), "NULL колбек/вихід -> false");
		CHECK(!wakeHopFindNext(5, 0, NCH, candFn, &t, &out) && !wakeHopFindNext(5, 5, 5, candFn, &t, &out), "вироджений діапазон -> false");
		CHECK(out == 77U, "*outNum не змінено при false");
	}

	/* ---- сценарії ---- */
	{
		res_t r;
		const unsigned L[] = { 5, 10, 20 };

		/* 1. поточний мертвий, наступний живий */
		reset(); setList(L, 3); tbl[10].alive = true;
		r = simulate(5, true, 2);
		CHECK(r.roamed && r.hops == 1 && r.path[0] == 10 && r.success && !r.restored && r.finalChan == 10, "5 мертвий, 10 живий -> залишаємось на 10");

		/* 2. по колу */
		reset(); setList(L, 3); tbl[5].alive = true;
		r = simulate(20, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 5 && r.finalChan == 5, "з 20 по колу на 5");

		/* 3. порядок за номером, не за порядком у списку */
		reset(); { const unsigned M[] = { 20, 5, 10 }; setList(M, 3); } tbl[20].alive = true;
		r = simulate(5, true, 2);
		CHECK(r.hops == 2 && r.path[0] == 10 && r.path[1] == 20 && r.finalChan == 20, "порядок 5 -> 10 -> 20 (за номером)");

		/* 4. пропуск непридатних між кандидатами */
		reset(); setList(L, 3); tbl[20].alive = true;
		tbl[10].info.digital = false;
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 20 && r.finalChan == 20, "аналоговий 10 пропущено");
		reset(); setList(L, 3); tbl[20].alive = true; tbl[10].info.forceDmo = true;
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 20, "FORCE_DMO 10 пропущено");
		reset(); setList(L, 3); tbl[20].alive = true; tbl[10].info.rxOnly = true;
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 20, "лише-приймання 10 пропущено");
		reset(); setList(L, 3); tbl[20].alive = true; tbl[10].info.inBand = false;
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 20, "поза діапазоном 10 пропущено");
		reset(); setList(L, 3); tbl[20].alive = true; tbl[10].info.inhibited = true;
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 20, "заблокований 10 пропущено");
		reset(); setList(L, 3); tbl[20].alive = true; tbl[10].info.txFreq = tbl[10].info.rxFreq;
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 20, "симплексний 10 пропущено");
		reset(); setList(L, 3); tbl[20].alive = true; tbl[10].info.txAllowed = false;
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 20, "10 із забороненою передачею пропущено");

		/* 5. дублікат (rx, tx, cc): той самий ретранслятор під іншим номером */
		reset(); setList(L, 3); tbl[20].alive = true;
		tbl[10].info = tbl[5].info;   /* та сама пара частот і колір-код, що в поточного */
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 20, "10 -- дублікат (rx,tx,cc) поточного: пропущено");
		reset(); setList(L, 3); tbl[10].alive = true;
		tbl[10].info = tbl[5].info; tbl[10].info.colourCode = 2U;
		r = simulate(5, true, 2);
		CHECK(r.hops == 1 && r.path[0] == 10 && r.finalChan == 10, "та сама пара частот, але ІНШИЙ колір-код -- не дублікат");
		reset(); setList(L, 3);
		tbl[10].info = tbl[5].info; tbl[20].info = tbl[5].info;
		r = simulate(5, true, 2);
		CHECK(r.hops == 0 && !r.restored && r.finalChan == 5, "усі в списку -- дублікати поточного: стрибків нема, повертати нічого");
		reset(); setList(L, 3); tbl[5].alive = false;
		tbl[20].info = tbl[10].info;   /* 20 дублює 10, який уже випробувано в цьому PTT */
		r = simulate(5, true, 5);
		CHECK(r.hops == 1 && r.path[0] == 10, "20 дублює вже випробуваний 10 -- другого стрибка нема");

		/* 6. ліміт стрибків */
		{
			const unsigned B[] = { 1, 2, 3, 4, 5, 6, 7, 8 };
			reset(); setList(B, 8);
			r = simulate(1, true, 2);
			CHECK(r.hops == 2 && r.restored && r.finalChan == 1 && !r.success, "ліміт 2: два стрибки, усі мовчать -> вихідний повернуто");
			r = simulate(1, true, 1);
			CHECK(r.hops == 1 && r.restored && r.finalChan == 1, "ліміт 1: один стрибок");
			r = simulate(1, true, 5);
			CHECK(r.hops == 5 && r.restored && r.path[4] == 6, "ліміт 5: п'ять стрибків (2..6)");
			tbl[7].alive = true;
			r = simulate(1, true, 5);
			CHECK(r.hops == 5 && !r.success && r.restored, "живий 7 поза лімітом 5 -- не дістаємось");
			tbl[4].alive = true;
			r = simulate(1, true, 5);
			CHECK(r.hops == 3 && r.success && r.finalChan == 4 && !r.restored, "живий 4 у межах ліміту -- лишаємось на 4");
		}

		/* 7. один оберт: не ходимо по колу вдруге */
		reset(); setList(L, 3);
		r = simulate(5, true, 5);
		CHECK(r.hops == 2 && r.restored && r.finalChan == 5, "три мертві канали, ліміт 5: лише два стрибки (10, 20), без другого кола");

		/* 8. поточний не в списку / функція вимкнена */
		reset(); setList(L, 3); tbl[10].alive = true;
		r = simulate(7, true, 2);
		CHECK(!r.roamed && r.hops == 0 && r.finalChan == 7, "поточний 7 НЕ в списку -- не роумимо (стара поведінка)");
		r = simulate(5, false, 2);
		CHECK(!r.roamed && r.hops == 0 && r.finalChan == 5, "функція вимкнена -- не роумимо");

		/* 9. список з одного каналу / порожній */
		reset(); { const unsigned S[] = { 5 }; setList(S, 1); }
		r = simulate(5, true, 2);
		CHECK(r.roamed && r.hops == 0 && !r.restored && r.finalChan == 5, "список з одного каналу -- стрибати нікуди");
		reset();
		r = simulate(5, true, 2);
		CHECK(!r.roamed && r.hops == 0, "порожній список -- не роумимо");

		/* 10. успіх на другому стрибку */
		reset(); setList(L, 3); tbl[20].alive = true;
		r = simulate(5, true, 2);
		CHECK(r.hops == 2 && r.success && !r.restored && r.finalChan == 20, "успіх на 2-му стрибку: лишаємось на знайденому каналі");
	}

	/* ---- повернення вихідного ---- */
	CHECK(!wakeHopShouldRestore(false, false), "не стрибали -- повертати нічого");
	CHECK(!wakeHopShouldRestore(false, true),  "не стрибали (успіх на вихідному) -- повертати нічого");
	CHECK(wakeHopShouldRestore(true, false),   "стрибали, успіху нема -- повернути вихідний");
	CHECK(!wakeHopShouldRestore(true, true),   "стрибали й вдалось -- НЕ повертати (лишаємось на знайденому)");

	/* ---- «роумити лише з поточного у списку» ---- */
	CHECK(wakeHopMayRoam(true, true) && !wakeHopMayRoam(true, false) && !wakeHopMayRoam(false, true) && !wakeHopMayRoam(false, false), "MayRoam: потрібні обидві умови");

	printf(fails ? "ПРОВАЛ: %d\n" : "ВСІ ПЕРЕВІРКИ ПРОЙДЕНО\n", fails);
	return fails ? 1 : 0;
}
