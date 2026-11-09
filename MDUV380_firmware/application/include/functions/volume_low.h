/*
 * volume_low.h -- R78: постійний «тихий» нижній рівень гучності («Мін.гучність»). Лише з ENABLE_VOLUME_LOW, лише українська збірка, лише UV380 Plus 10W.
 * Біля мінімуму потенціометра додається ослаблення, лінійне в дБ (крива -- volume_low_logic.h); вище коліна шкала стокова. Налаштування -- один байт
 * у custom-data блоці CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG (= 17): 0 вимк (типово), 1 = K 8, 2 = K 16, 3 = K 24 позицій ручки. Розкладку
 * nonVolatileSettings не чіпає. DMR -- множник відліків у sound.c (після АРУ); FM -- регістр AT1846S 0x44 через наявну radioWriteReg2byte().
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

void volumeLowLoad(void);                     /* на старті і після скасування в меню: режим із флеша (немає блоку -- 0) */
uint8_t volumeLowGetMode(void);               /* 0..3 */
void volumeLowSetMode(uint8_t mode);          /* ЖИВЕ значення (чутно одразу); у флеш лише volumeLowSave() */
bool volumeLowSave(void);                     /* записати режим у блок, якщо відрізняється від флеша; true -- збережено або вже було таке */
void volumeLowPotSettled(int8_t lastVolume);  /* з updateVolumeGain(): ручка встоялась на lastVolume */
void volumeLowTick(void);                     /* щомілісекунди з головного циклу: зміна режиму/передачі/APRS/проби -> перерахунок; захист 0x44 від перезапису */
void volumeLowStopForTx(void);                /* з trxSetTX()/trxActivateTx(): СИНХРОННО повернути стокове 0x44 до початку передачі */
#endif

#endif /* FUNCTIONS_VOLUME_LOW_H_ */
