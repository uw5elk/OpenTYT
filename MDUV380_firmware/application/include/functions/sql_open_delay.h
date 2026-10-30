/*
 * sql_open_delay.h -- R42: затримка ВІДКРИТТЯ шумодава FM. ЧИСТА логіка (без заліза й таймерів), тож тестується на хості
 * (tests/test_sql_open_delay.c). Використовує trx.c (trxCheckAnalogSquelch) і меню «Опції рації».
 *
 * Навіщо: на шумному каналі шумодав б'є коротким шипінням на початку кожної передачі й на випадкових піках шуму. Якщо дозволити динаміку лише після того,
 * як сигнал пробув відкритим N мс, короткі піки не доходять до динаміки зовсім. Ціна -- N мс початку КОЖНОЇ передачі зрізано (про це сказано в меню).
 *
 * Лише під ENABLE_SQL_OPEN_DELAY (див. settings.h, макрос SQL_OPEN_DELAY_ENABLED).
 *
 * Зберігання: nonVolatileSettings.UNUSED_1 (int16_t, раніше нікому не потрібне; розкладка структури не змінюється). Старший байт -- мітка 0xD5, молодший --
 * кількість кроків по 50 мс. Без мітки (нова прошивка над старим сховищем, сміття, скидання) затримки НЕМАЄ: значення читається як 0.
 */
#ifndef _OPENGD77_SQL_OPEN_DELAY_H_
#define _OPENGD77_SQL_OPEN_DELAY_H_

#include <stdint.h>
#include <stdbool.h>

#define SQL_OPEN_DELAY_STEP_MS    50U
#define SQL_OPEN_DELAY_STEPS_MAX  10U      /* 10 x 50 = 500 мс */
#define SQL_OPEN_DELAY_TAG        0xD5U

/* Кроки (0..SQL_OPEN_DELAY_STEPS_MAX) зі збереженого слова. Немає мітки або кроків забагато -> 0 (затримку вимкнено). */
static inline uint8_t sqlOpenDelaySteps(int16_t stored)
{
	uint16_t w = (uint16_t)stored;

	if (((w >> 8) != SQL_OPEN_DELAY_TAG) || ((w & 0xFFU) > SQL_OPEN_DELAY_STEPS_MAX))
	{
		return 0;
	}
	return (uint8_t)(w & 0xFFU);
}

/* Слово для збереження. 0 кроків -> 0 (чисте «вимкнено», без мітки). Забагато кроків обрізається до максимуму. */
static inline int16_t sqlOpenDelayPack(uint8_t steps)
{
	if (steps == 0U)
	{
		return 0;
	}
	if (steps > SQL_OPEN_DELAY_STEPS_MAX)
	{
		steps = (uint8_t)SQL_OPEN_DELAY_STEPS_MAX;
	}
	return (int16_t)(uint16_t)((SQL_OPEN_DELAY_TAG << 8) | steps);
}

static inline uint8_t sqlOpenDelayStepsInc(uint8_t steps)
{
	return (steps >= SQL_OPEN_DELAY_STEPS_MAX) ? (uint8_t)SQL_OPEN_DELAY_STEPS_MAX : (uint8_t)(steps + 1U);
}

static inline uint8_t sqlOpenDelayStepsDec(uint8_t steps)
{
	return (steps == 0U) ? 0U : (uint8_t)(steps - 1U);
}

/*
 * Чи можна відкрити динамік зараз.
 *   since         -- мітка часу, коли сигнал з'явився (0 = ще не позначено). Зберігає викликач.
 *   now           -- поточний час, мс (ticksGetMillis()); перехід через 2^32 коректний (різниця без знака).
 *   delayMs       -- затримка, мс; 0 -- без затримки (поведінка, як до R42).
 *   signalPresent -- сигнал є. false СКИДАЄ мітку: сигнал зник до кінця затримки -- наступна поява починає відлік заново, динамік не відкривався.
 * Повертає true, коли затримка минула (при delayMs == 0 -- одразу).
 */
static inline bool sqlOpenDelayCheck(uint32_t *since, uint32_t now, uint32_t delayMs, bool signalPresent)
{
	if (!signalPresent)
	{
		*since = 0;
		return false;
	}

	if (delayMs == 0U)
	{
		*since = 0;
		return true;
	}

	if (*since == 0U)
	{
		*since = (now != 0U) ? now : 0xFFFFFFFFU;   /* 0 -- «не позначено»; годинник рівно на 0 позначаємо «на 1 мс раніше» (різниця без знака коректна) */
	}

	return ((uint32_t)(now - *since) >= delayMs);
}

#endif /* _OPENGD77_SQL_OPEN_DELAY_H_ */
