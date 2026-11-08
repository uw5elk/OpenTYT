/*
 * volume_probe_logic.h -- R77A: ЧИСТА логіка діагностичного екрана «Гучн. проба» (без обладнання, без Tk): таблиці кроків, умови автоповернення
 * до стокових значень, застосування DMR-множника до відліку. Підключається і прошивкою (functions/volume_probe.c, sound.c), і хостовим тестом
 * (tests/test_volume_probe.c). ЕКСПЕРИМЕНТ: нічого не зберігається, після перезавантаження і при виході все стокове.
 *
 * DMR: додаткове ослаблення відліків ПЕРЕД I2S -- зсув вправо на 0..3 біти (1x, 1/2, 1/4, 1/8 = 0, -6, -12, -18 дБ). Застосовується ПІСЛЯ АРУ:
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

#define VP_DMR_STEPS      4U            /* 1x, 1/2, 1/4, 1/8 */
#define VP_FM_STEPS       5U            /* 80 % (стокове), 60, 40, 25, 15 */
#define VP_FM_REG         0x44U
#define VP_FM_HIGH        0x06U         /* старший байт як у AT1846FMSettings */
#define VP_FM_STOCK_LOW   0xCCU         /* 0x06CC -- стокове значення FM */
#define VP_TIMEOUT_MS     120000U       /* 2 хв: після цього все повертається до стокового */

/* DMR: зсув вправо для кроку (0..3); неправильний крок -- без ослаблення. */
static inline uint8_t vpDmrShift(uint8_t step)
{
	return (step < VP_DMR_STEPS) ? step : 0U;
}

/* Ослаблення DMR у дБ (0, -6, -12, -18). */
static inline int vpDmrDb(uint8_t step)
{
	return -6 * (int)vpDmrShift(step);
}

/* Відліку після ослаблення. Арифметичний зсув: 0 лишається 0, знак зберігається. */
static inline int16_t vpDmrApply(int16_t sample, uint8_t shift)
{
	return (int16_t)(sample >> (shift & 3U));
}

/* FM: відсоток від 0x07FF-«100 %» (молодший байт 0xFF) для кроку. */
static inline uint8_t vpFmPercent(uint8_t step)
{
	static const uint8_t pct[VP_FM_STEPS] = { 80U, 60U, 40U, 25U, 15U };
	return pct[(step < VP_FM_STEPS) ? step : 0U];
}

/* FM: молодший байт 0x44 для кроку = округлено(відсоток × 255 / 100): 80 % -> 0xCC (збігається зі стоковим), 60 % -> 0x99, 40 % -> 0x66, 25 % -> 0x40, 15 % -> 0x26. */
static inline uint8_t vpFmLow(uint8_t step)
{
	return (uint8_t)(((uint32_t)vpFmPercent(step) * 255U + 50U) / 100U);
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
