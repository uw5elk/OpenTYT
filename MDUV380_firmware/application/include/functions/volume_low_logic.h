/*
 * volume_low_logic.h -- R78: ЧИСТА логіка постійного «тихого» нижнього рівня гучності («Мін.гучність», ENABLE_VOLUME_LOW): крива, таблиці, рампа.
 * Підключається і прошивкою (functions/volume_low.c, sound.c), і хостовим тестом (tests/test_volume_low.c). Без обладнання.
 *
 * КРИВА. Позиція ручки n = lastVolume + 31 (0 = мінімум, -31 дБ; 0..62). Коліно K (позицій від мінімуму): 8 / 16 / 24 (режими 1/2/3; режим 0 -- вимкнено).
 * Для n >= K додаткового ослаблення нема -- шкала стокова. Для n < K:  extra_dB(n) = округлене( D * (K - n) / K ),  D -- глибина в мінімумі:
 *   DMR  D = 36 дБ  (власник на залізі: 1/64 = -36 дБ комфортно);
 *   FM   D = 23 дБ  (20*log10(0xCC/0x0F) = 22,7 -> 23; власник: 6 % = low-byte 0x0F). Таблиця low-byte нижче 0x0F не опускається (x = 23 дало б 0x0E).
 * Крива лінійна в дБ (пряма на логарифмічному графіку), неперервна в n = K (extra = 0), монотонна: повний рівень = стоковий рівень ручки - extra(n),
 * а стоковий росте на 1 дБ/позицію, тож загалом ще швидше -- рівень не зменшується із зростанням n.
 * ЗАГЛУШЕНО (lastVolume == -99, лінійний вихід вимкнено): позиція = 0, тобто extra = D -- РІВНО як у мінімумі. Так при виході зі «заглушено»
 * ослаблення вже стоїть і не з'являється гучний сплеск; регістри/множник при цьому не перемикаються.
 *
 * DMR: множник відліків ПІСЛЯ АРУ (як у R77A), Q15: gain[x] = round(32768 * 10^(-x/20)), x = 0..36 (крок 1 дБ). Таблиця -- const (флеш).
 * FM:  low-byte AT1846S 0x44 (старший 0x06): low[x] = round(0xCC * 10^(-x/20)), x = 0..23, але не нижче 0x0F; таблиця const (флеш).
 *      [ГІПОТЕЗА] лінійність регістра 0x44 (з R77A/R77B) не виміряна: біля дна байт має лише кілька рівнів.
 */
#ifndef FUNCTIONS_VOLUME_LOW_LOGIC_H_
#define FUNCTIONS_VOLUME_LOW_LOGIC_H_

#include <stdint.h>
#include <stdbool.h>

#define VOLLOW_MODES            4U       /* 0 = вимк, 1 = K 8, 2 = K 16, 3 = K 24 */
#define VOLLOW_DEPTH_DMR_DB     36U
#define VOLLOW_DEPTH_FM_DB      23U
#define VOLLOW_FM_REG           0x44U
#define VOLLOW_FM_HIGH          0x06U
#define VOLLOW_FM_STOCK_LOW     0xCCU    /* 0x06CC -- стокове FM */
#define VOLLOW_FM_FLOOR_LOW     0x0FU    /* нижче НЕ опускатися (6 %) */
#define VOLLOW_Q15_UNITY        32768U
#define VOLLOW_RAMP_STEP        128U     /* зміна Q15-множника за один вихідний відлік (повний діапазон -36 дБ ~ 250 відліків) */
#define VOLLOW_POS_MAX          62U

#define VOLLOW_FIXED_MODE       2U       /* R81: єдиний режим у прошивці -- K = 16 (рішення власника 2026-11-10); меню немає */

/* R81: ефективний режим -- що б не лежало в custom-data блоці 17 (0/1/2/3/сміття/блоку немає), завжди VOLLOW_FIXED_MODE. */
static inline uint8_t vlEffectiveMode(uint8_t raw)
{
	(void)raw;
	return VOLLOW_FIXED_MODE;
}

/* Коліно K для режиму 0..3 (0 -- вимкнено; режим поза діапазоном -- вимкнено). */
static inline uint8_t vlKnee(uint8_t mode)
{
	static const uint8_t k[VOLLOW_MODES] = { 0U, 8U, 16U, 24U };
	return (mode < VOLLOW_MODES) ? k[mode] : 0U;
}

/* Значення з флеша -> режим: 0..3, решта -- 0 (вимкнено). */
static inline uint8_t vlModeSanitize(uint8_t raw)
{
	return (raw < VOLLOW_MODES) ? raw : 0U;
}

/* lastVolume (-99 заглушено, -31..31) -> позиція 0..62; заглушено і нижче -31 -> 0, вище 31 -> 62. */
static inline uint8_t vlPos(int8_t lastVolume)
{
	int v = (int)lastVolume;
	if (v < -31) { v = -31; }
	if (v > 31) { v = 31; }
	return (uint8_t)(v + 31);
}

/* Додаткове ослаблення, ціле дБ: round(D*(K-n)/K) для n < K; 0 для n >= K або K == 0. */
static inline uint8_t vlExtraDb(uint8_t n, uint8_t knee, uint8_t depthDb)
{
	if ((knee == 0U) || (n >= knee))
	{
		return 0U;
	}
	return (uint8_t)((2U * (uint32_t)depthDb * (uint32_t)(knee - n) + knee) / (2U * (uint32_t)knee));
}

/* DMR: множник Q15 для x дБ ослаблення (x обрізається до 36). */
static inline uint16_t vlDmrGainQ15(uint8_t x)
{
	static const uint16_t g[VOLLOW_DEPTH_DMR_DB + 1U] = {
		32768U, 29205U, 26029U, 23198U, 20675U, 18427U, 16423U, 14637U, 13045U,
		11627U, 10362U, 9235U, 8231U, 7336U, 6538U, 5827U, 5193U, 4629U,
		4125U, 3677U, 3277U, 2920U, 2603U, 2320U, 2068U, 1843U, 1642U,
		1464U, 1305U, 1163U, 1036U, 924U, 823U, 734U, 654U, 583U,
		519U
	};
	return g[(x > VOLLOW_DEPTH_DMR_DB) ? VOLLOW_DEPTH_DMR_DB : x];
}

/* FM: молодший байт 0x44 для x дБ ослаблення (x обрізається до 23); завжди >= 0x0F. */
static inline uint8_t vlFmLow(uint8_t x)
{
	static const uint8_t l[VOLLOW_DEPTH_FM_DB + 1U] = {
		204U, 182U, 162U, 144U, 129U, 115U, 102U, 91U, 81U, 72U, 65U, 57U,
		51U, 46U, 41U, 36U, 32U, 29U, 26U, 23U, 20U, 18U, 16U, 15U
	};
	return l[(x > VOLLOW_DEPTH_FM_DB) ? VOLLOW_DEPTH_FM_DB : x];
}

/* Рампа множника: один крок до цілі (без клацань при зміні кроку; зсув на 1 дБ ~ 27 відліків). */
static inline uint16_t vlRamp(uint16_t cur, uint16_t target)
{
	if (cur < target)
	{
		return (uint16_t)(((uint32_t)(target - cur) <= VOLLOW_RAMP_STEP) ? target : (cur + VOLLOW_RAMP_STEP));
	}
	if (cur > target)
	{
		return (uint16_t)(((uint32_t)(cur - target) <= VOLLOW_RAMP_STEP) ? target : (cur - VOLLOW_RAMP_STEP));
	}
	return cur;
}

/* Застосувати множник Q15 до відліку (арифметичний зсув; для одиничного множника відлік без змін). */
static inline int16_t vlApply(int16_t sample, uint16_t gainQ15)
{
	if (gainQ15 >= VOLLOW_Q15_UNITY)
	{
		return sample;
	}
	return (int16_t)(((int32_t)sample * (int32_t)gainQ15) >> 15);
}

/* Умови, за яких FM-ослаблення діє: аналоговий режим, не передача, нема APRS-приймача/режиму APRS, діагностична проба закрита, USB не в режимі хотспота. */
static inline bool vlFmAllowed(bool analog, bool tx, bool aprs, bool probeOn, bool usbCps)
{
	return analog && (tx == false) && (aprs == false) && (probeOn == false) && usbCps;
}

/* DMR-множник діє: цифровий режим, проба закрита, USB не в режимі хотспота. */
static inline bool vlDmrAllowed(bool digital, bool probeOn, bool usbCps)
{
	return digital && (probeOn == false) && usbCps;
}

#endif /* FUNCTIONS_VOLUME_LOW_LOGIC_H_ */
