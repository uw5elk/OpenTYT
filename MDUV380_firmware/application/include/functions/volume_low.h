/*
 * volume_low.h -- R78: постійний «тихий» нижній рівень гучності («Мін.гучність»). Лише з ENABLE_VOLUME_LOW, лише українська збірка, лише UV380 Plus 10W.
 * Біля мінімуму потенціометра додається ослаблення, лінійне в дБ (крива -- volume_low_logic.h); вище коліна шкала стокова. R81: налаштування НЕМАЄ -- функція завжди ввімкнена з колінном K = 16 позицій ручки (VOLLOW_FIXED_MODE, volume_low_logic.h); пункт меню прибрано.
 * Custom-data блок CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG (= 17, 1 байт) лишається в кодплузі незмінним, але ігнорується (старі значення 0..3/сміття/немає блоку -- усі дають K = 16).
 * Розкладку nonVolatileSettings не чіпає. DMR -- множник відліків у sound.c (після АРУ); FM -- регістр AT1846S 0x44 через наявну radioWriteReg2byte().
 * Діагностична проба (ENABLE_VOLUME_PROBE) має пріоритет: поки відкрита -- ця функція стокова, після виходу з проби відновлюється сама.
 */
#ifndef FUNCTIONS_VOLUME_LOW_H_
#define FUNCTIONS_VOLUME_LOW_H_

#include <stdint.h>
#include <stdbool.h>
#include "functions/volume_low_logic.h"

#if defined(ENABLE_VOLUME_LOW) && defined(LANGUAGE_BUILD_UKRAINIAN) && defined(PLATFORM_VARIANT_UV380_PLUS_10W)
#define VOLUME_LOW 1

/* Цільовий множник DMR (Q15; 32768 = без ослаблення). Пише лише volume_low.c, читає sound.c (там рампа до цієї цілі). */
extern volatile uint16_t volumeLowDmrGainQ15;

void volumeLowLoad(void);                     /* на старті: фіксований режим K = 16 (блок 17 не читається) */
#if defined(VOLLOW_TEST_HOOKS)
uint8_t volumeLowGetMode(void);               /* лише хост-тести: 0..3 */
void volumeLowSetMode(uint8_t mode);          /* лише хост-тести: перебір K для перевірки кривої */
#endif
void volumeLowPotSettled(int8_t lastVolume);  /* з updateVolumeGain(): ручка встоялась на lastVolume */
void volumeLowTick(void);                     /* щомілісекунди з головного циклу: зміна режиму/передачі/APRS/проби -> перерахунок; захист 0x44 від перезапису */
void volumeLowStopForTx(void);                /* з trxSetTX()/trxActivateTx(): СИНХРОННО повернути стокове 0x44 до початку передачі */
#endif

#endif /* FUNCTIONS_VOLUME_LOW_H_ */
