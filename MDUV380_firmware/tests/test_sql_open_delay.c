/*
 * test_sql_open_delay.c -- R42: затримка відкриття шумодава FM. Тест СПРАВЖНЬОЇ чистої логіки application/include/functions/sql_open_delay.h
 * (ту саму викликає trx.c) -- без заліза: час і сигнал подаються з тесту.
 *
 * Модель циклу trxCheckAnalogSquelch(): кожні 25 мс (RSSI_NOISE_SAMPLE_PERIOD_PIT) сигнал є/нема; поки сигнал є і динамік вимкнений -- викликається
 * sqlOpenDelayCheck(..., true) і при true динамік відкривається; коли сигнал зникає (гістерезис) -- sqlOpenDelayCheck(..., false) скидає відлік.
 */
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "functions/sql_open_delay.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

#define PERIOD 25U

/* Модель: сигнал присутній у [onAt, offAt) (мс), початок відліку часу -- t0. Повертає момент відкриття динаміка (мс від onAt) або -1, якщо не відкрився. */
static int simulate(uint32_t t0, uint32_t onAt, uint32_t offAt, uint32_t delayMs, uint32_t endAt, uint32_t *sinceOut)
{
	uint32_t since = 0;
	bool open = false;
	int openedAt = -1;

	for (uint32_t t = 0; t <= endAt; t += PERIOD)
	{
		uint32_t now = t0 + t;
		bool signal = (t >= onAt) && (t < offAt);

		if (signal)
		{
			if (!open && sqlOpenDelayCheck(&since, now, delayMs, true))
			{
				open = true;
				openedAt = (int)(t - onAt);
				since = 0;                       /* як trxSqlOpenDelayReset() після відкриття */
			}
		}
		else
		{
			(void)sqlOpenDelayCheck(&since, now, delayMs, false);   /* закриття / відсутність сигналу */
			open = false;
		}
	}
	if (sinceOut) { *sinceOut = since; }
	return openedAt;
}

int main(void)
{
	/* --- Z1.1: затримка 0 -- відкриваємося одразу, як до R42 */
	CHECK(simulate(1000, 100, 2000, 0, 2000, NULL) == 0, "Z1.1 затримка 0: відкрилось у перший же цикл з сигналом");
	{
		uint32_t since = 77;
		CHECK(sqlOpenDelayCheck(&since, 5000, 0, true) == true && since == 0, "Z1.1 затримка 0: true і мітку не лишає");
	}

	/* --- Z1.2: сигнал утримується -- відкриття рівно після затримки (з точністю до кроку циклу) */
	{
		int o300 = simulate(1000, 100, 5000, 300, 5000, NULL);
		CHECK(o300 >= 300 && o300 < 300 + (int)PERIOD, "Z1.2 300 мс: відкрилось через %d мс (>= 300, < 325)", o300);
		int o50 = simulate(1000, 100, 5000, 50, 5000, NULL);
		CHECK(o50 >= 50 && o50 < 50 + (int)PERIOD, "Z1.2 50 мс: через %d мс", o50);
	}

	/* --- Z1.3: сигнал з'явився й зник ДО кінця затримки -- динамік не відкривається ніколи, мітка скинута */
	{
		uint32_t since = 123;
		int o = simulate(1000, 100, 100 + 200, 300, 2000, &since);       /* сигнал 200 мс при затримці 300 */
		CHECK(o == -1, "Z1.3 сигнал 200 мс при затримці 300: динамік НЕ відкривався");
		CHECK(since == 0, "Z1.3 після зникнення сигналу мітка скинута (since=%u)", since);
		int o2 = simulate(1000, 100, 100 + 275, 300, 2000, &since);      /* 275 мс < 300 */
		CHECK(o2 == -1, "Z1.3 сигнал 275 мс при затримці 300: не відкривався");
	}

	/* --- Z1.3b: коли сигналу нема, перевірка НІКОЛИ не каже «можна» (динамік не відкриється без сигналу) і скидає мітку */
	{
		uint32_t since = 5000;
		CHECK(sqlOpenDelayCheck(&since, 9000, 300, false) == false && since == 0, "Z1.3b сигналу нема: false і мітка скинута");
		since = 5000;
		CHECK(sqlOpenDelayCheck(&since, 9000, 0, false) == false && since == 0, "Z1.3b сигналу нема й затримка 0: false і мітка скинута");
	}

	/* --- Z1.4: два короткі сплески підряд НЕ складаються (відлік починається заново) */
	{
		uint32_t since = 0;
		bool opened = false;
		uint32_t t0 = 5000;
		for (uint32_t t = 0; t < 1000; t += PERIOD)
		{
			bool signal = (t < 200) || ((t >= 250) && (t < 450));    /* 200 мс + пауза + 200 мс; затримка 300 */
			if (signal) { if (sqlOpenDelayCheck(&since, t0 + t, 300, true)) { opened = true; } }
			else        { (void)sqlOpenDelayCheck(&since, t0 + t, 300, false); }
		}
		CHECK(!opened, "Z1.4 два сплески по 200 мс з паузою при затримці 300 не складаються в 400");
	}

	/* --- Z1.5: межа 500 мс */
	{
		int o = simulate(1000, 0, 5000, 500, 5000, NULL);
		CHECK(o >= 500 && o < 525, "Z1.5 500 мс: відкрилось через %d мс", o);
		int s = simulate(1000, 0, 475, 500, 2000, NULL);
		CHECK(s == -1, "Z1.5 сигнал 475 мс при затримці 500: не відкривався");
		uint32_t since = 0;
		CHECK(!sqlOpenDelayCheck(&since, 1000, 500, true), "Z1.5 перше виклик -- рано");
		CHECK(!sqlOpenDelayCheck(&since, 1499, 500, true), "Z1.5 499 мс -- ще рано");
		CHECK(sqlOpenDelayCheck(&since, 1500, 500, true), "Z1.5 рівно 500 мс -- можна");
	}

	/* --- Z1.6: перехід годинника через 2^32 і через 0 */
	{
		uint32_t since = 0;
		CHECK(!sqlOpenDelayCheck(&since, 0xFFFFFF00U, 300, true), "Z1.6 старт перед переходом");
		CHECK(!sqlOpenDelayCheck(&since, 0x00000010U, 300, true), "Z1.6 після переходу: пройшло лише 272 мс (рано)");
		CHECK(sqlOpenDelayCheck(&since, 0x00000040U, 300, true), "Z1.6 після переходу: пройшло 320 мс (можна)");
		since = 0;
		CHECK(!sqlOpenDelayCheck(&since, 0, 300, true) && since != 0, "Z1.6 годинник рівно 0: мітка не лишається «непозначеною»");
		CHECK(!sqlOpenDelayCheck(&since, 100, 300, true), "Z1.6 через 100 мс від нуля -- рано");
		CHECK(sqlOpenDelayCheck(&since, 301, 300, true), "Z1.6 через 301 мс від нуля -- можна");
	}

	/* --- Z1.7: збережене значення: мітка, діапазон, крок */
	CHECK(sqlOpenDelaySteps(0) == 0, "Z1.7 0 -> 0");
	CHECK(sqlOpenDelaySteps(sqlOpenDelayPack(6)) == 6, "Z1.7 6 кроків (300 мс) туди й назад");
	CHECK(sqlOpenDelaySteps(sqlOpenDelayPack(10)) == 10, "Z1.7 10 кроків (500 мс) туди й назад");
	CHECK(sqlOpenDelayPack(11) == sqlOpenDelayPack(10), "Z1.7 11 обрізається до 10 (межа діапазону)");
	CHECK(sqlOpenDelayPack(0) == 0, "Z1.7 0 кроків зберігається як чистий 0");
	CHECK(sqlOpenDelaySteps(6) == 0, "Z1.7 слово без мітки (6) -> затримки нема");
	CHECK(sqlOpenDelaySteps((int16_t)0x1234) == 0, "Z1.7 сміття без мітки -> нема");
	CHECK(sqlOpenDelaySteps((int16_t)(uint16_t)0xD50B) == 0, "Z1.7 мітка є, але 11 кроків (поза діапазоном) -> нема");
	CHECK(sqlOpenDelaySteps((int16_t)(uint16_t)0xD5FF) == 0, "Z1.7 мітка є, 255 кроків -> нема");
	CHECK(sqlOpenDelaySteps((int16_t)(uint16_t)0xD500) == 0, "Z1.7 мітка й 0 кроків -> 0");
	CHECK(sqlOpenDelayStepsInc(9) == 10 && sqlOpenDelayStepsInc(10) == 10 && sqlOpenDelayStepsInc(0) == 1, "Z1.7 Inc: 9->10, на межі стоїть, 0->1");
	CHECK(sqlOpenDelayStepsDec(1) == 0 && sqlOpenDelayStepsDec(0) == 0 && sqlOpenDelayStepsDec(10) == 9, "Z1.7 Dec: 1->0, на нулі стоїть, 10->9");
	{
		uint8_t s = 0; int n = 0;
		while (s < 20 && n < 30) { uint8_t nx = sqlOpenDelayStepsInc(s); if (nx == s) { break; } s = nx; n++; }
		CHECK(s == SQL_OPEN_DELAY_STEPS_MAX && n == 10, "Z1.7 від 0 до межі рівно 10 кроків = 500 мс (%d)", n);
		CHECK(SQL_OPEN_DELAY_STEPS_MAX * SQL_OPEN_DELAY_STEP_MS == 500, "Z1.7 максимум 500 мс");
	}

	printf("\n%s (%d провалів)\n", fails ? "ПРОВАЛ" : "OK", fails);
	return fails ? 1 : 0;
}
