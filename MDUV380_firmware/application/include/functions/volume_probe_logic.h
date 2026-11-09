/*
 * volume_probe_logic.h -- R77A: ЧИСТА логіка діагностичного екрана «Гучн. проба» (без обладнання, без Tk): таблиці кроків, умови автоповернення
 * до стокових значень, застосування DMR-множника до відліку. Підключається і прошивкою (functions/volume_probe.c, sound.c), і хостовим тестом
 * (tests/test_volume_probe.c). ЕКСПЕРИМЕНТ: нічого не зберігається, після перезавантаження і при виході все стокове.
 *
 * DMR: додаткове ослаблення відліків ПЕРЕД I2S -- зсув вправо на 0..6 бітів (1x ... 1/64 = 0, -6 ... -36 дБ; R77B: глибші кроки). Застосовується ПІСЛЯ АРУ:
 * АРУ (sound.c, soundRefillData) міряє пік ВХІДНИХ відліків (dmrRxAGCpeakRx із swapper.byte16 -- до множення), тож ослаблення на виході
 * не змінює її вхід, і вона не «підсилює назад».
 *
 * FM: AT1846S, регістр 0x44, молодший байт (старший 0x06 лишається). [ГІПОТЕЗА] Припущення, що байт масштабує гучність виходу, грунтується
 * лише на коментарях у коді: AT1846S.c -- «{0x44,0x06,0xCC} set internal volume to 80%» для FM і «{0x44,0x07,0xFF} Set internal volume / AF gain
 * to 100%» для DMR; 0xCC/0xFF = 80 %; aprs.c пише в цей регістр значення «гучності» 0..61 для тону маяка; AT1846S.c:231-235 згадує 0xCF як
 * «знижене» значення. Даташита немає, тож скільки дБ дає крок -- невідомо; це й міряє екран.
 */
#ifndef FUNCTIONS_VOLUME_PROBE_LOGIC_H_
#define FUNCTIONS_VOLUME_PROBE_LOGIC_H_

#include <stdint.h>
#include <stdbool.h>

#define VP_DMR_STEPS      7U            /* R77B: 1x, 1/2, 1/4, 1/8, 1/16, 1/32, 1/64 (0..-36 дБ) */
#define VP_DMR_MAX_SHIFT  6U
#define VP_FM_STEPS       9U            /* R77B: 80 % (стокове), 60, 40, 25, 15, 10, 6, 3, 1,5 */
#define VP_FM_REG         0x44U
#define VP_FM_HIGH        0x06U         /* старший байт як у AT1846FMSettings */
#define VP_FM_STOCK_LOW   0xCCU         /* 0x06CC -- стокове значення FM */
#define VP_TIMEOUT_MS     120000U       /* 2 хв: після цього все повертається до стокового */

/* DMR: зсув вправо для кроку (0..3); неправильний крок -- без ослаблення. */
static inline uint8_t vpDmrShift(uint8_t step)
{
	return (step < VP_DMR_STEPS) ? step : 0U;
}

/* Ослаблення DMR у дБ (0, -6, ... -36). */
static inline int vpDmrDb(uint8_t step)
{
	return -6 * (int)vpDmrShift(step);
}

/* Відліку після ослаблення. Арифметичний зсув: 0 лишається 0, знак зберігається. Зсув понад VP_DMR_MAX_SHIFT обрізається до нього. */
static inline int16_t vpDmrApply(int16_t sample, uint8_t shift)
{
	return (int16_t)(sample >> ((shift > VP_DMR_MAX_SHIFT) ? VP_DMR_MAX_SHIFT : shift));
}

/* FM: «відсоток» від 0x07FF-«100 %» (молодший байт 0xFF) у промілле: 80, 60, 40, 25, 15, 10, 6, 3, 1,5 %. */
static inline uint16_t vpFmPermille(uint8_t step)
{
	static const uint16_t pm[VP_FM_STEPS] = { 800U, 600U, 400U, 250U, 150U, 100U, 60U, 30U, 15U };
	return pm[(step < VP_FM_STEPS) ? step : 0U];
}

/* FM: молодший байт 0x44 для кроку = округлено(промілле × 255 / 1000): 0xCC (збігається зі стоковим), 0x99, 0x66, 0x40, 0x26, 0x1A, 0x0F, 0x08, 0x04. */
static inline uint8_t vpFmLow(uint8_t step)
{
	return (uint8_t)(((uint32_t)vpFmPermille(step) * 255U + 500U) / 1000U);
}

/* FM: РОЗРАХУНКОВЕ (не виміряне!) ослаблення відносно стокового 0xCC, десяті дБ: 20*log10(low/0xCC) за гіпотезою лінійності регістра.
 * Таблиця пораховано заздалегідь (без libm у прошивці); хостовий тест звіряє її з log10. */
static inline int16_t vpFmDbTenths(uint8_t step)
{
	static const int16_t t[VP_FM_STEPS] = { 0, -25, -60, -101, -146, -179, -227, -281, -342 };
	return t[(step < VP_FM_STEPS) ? step : 0U];
}

/* Те саме, округлене до цілих дБ (для екрана). */
static inline int vpFmDb(uint8_t step)
{
	int16_t v = vpFmDbTenths(step);
	return (v < 0) ? -(((-v) + 5) / 10) : ((v + 5) / 10);
}

/* FM-ослаблення заборонене, коли працює APRS-приймач або «Режим APRS»: вони беруть відліки з того самого FM-шляху I2S (HR-C6000), і зміна
 * рівня зсуває амплітуду (запас до ±512 у 10-бітному форматі, docs/aprs-rx-feasibility.md 9.4) -- прийом пакетів зламався б. */
static inline bool vpFmBlocked(bool aprsRxRunning, bool aprsModeActive)
{
	return aprsRxRunning || aprsModeActive;
}

typedef enum { VP_KEEP = 0, VP_RESTORE_TX, VP_RESTORE_APRS, VP_RESTORE_CHANNEL, VP_RESTORE_TIMEOUT } vpRestore_t;

/* Чи треба повернути стокові значення. Пріоритет: передача, APRS (лише коли FM-крок не стоковий), зміна каналу/режиму, таймаут. */
static inline vpRestore_t vpRestoreReason(bool tx, bool aprsBlocked, bool fmChanged, bool channelOrModeChanged, uint32_t elapsedMs)
{
	if (tx)
	{
		return VP_RESTORE_TX;
	}
	if (aprsBlocked && fmChanged)
	{
		return VP_RESTORE_APRS;
	}
	if (channelOrModeChanged)
	{
		return VP_RESTORE_CHANNEL;
	}
	if (elapsedMs >= VP_TIMEOUT_MS)
	{
		return VP_RESTORE_TIMEOUT;
	}
	return VP_KEEP;
}

#endif /* FUNCTIONS_VOLUME_PROBE_LOGIC_H_ */
