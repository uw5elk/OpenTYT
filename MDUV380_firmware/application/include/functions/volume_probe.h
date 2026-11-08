/*
 * volume_probe.h -- R77A: ДІАГНОСТИЧНИЙ екран «Гучн. проба» (останній пункт «Опцій рації») -- ЕКСПЕРИМЕНТ з додатковим ослабленням звуку нижче
 * мінімуму потенціометра. Лише з ENABLE_VOLUME_PROBE, лише українська збірка, лише UV380 Plus 10W. Нічого не зберігається (ні EEPROM, ні флеш,
 * ні custom-data): лише кілька байтів RAM; вихід з екрана, зміна каналу/режиму, передача, APRS і таймаут 2 хв повертають стокове.
 */
#ifndef FUNCTIONS_VOLUME_PROBE_H_
#define FUNCTIONS_VOLUME_PROBE_H_

#include <stdint.h>
#include <stdbool.h>
#include "functions/volume_probe_logic.h"

#if defined(ENABLE_VOLUME_PROBE) && defined(LANGUAGE_BUILD_UKRAINIAN) && defined(PLATFORM_VARIANT_UV380_PLUS_10W)
#define VOLUME_PROBE 1

/* Зсув відліків DMR перед I2S (0 = стокове). Пише лише цей модуль, читає sound.c. */
extern volatile uint8_t volumeProbeDmrShift;

void volumeProbeOpen(void);                    /* відкрити екран: фіксує канал/режим, час, кроки = стокові */
void volumeProbeClose(void);                   /* повернути стокове і закрити; безпечно, якщо не відкрито */
bool volumeProbeIsOn(void);
void volumeProbeStopForTx(void);               /* з trxSetTX()/trxActivateTx(): СИНХРОННО повернути стокове до початку передачі */
vpRestore_t volumeProbeTick(void);             /* кожен тік екрана: перевірка умов автоповернення; ненульове -- уже закрито */
void volumeProbeToggleSelect(void);            /* DMR <-> FM */
void volumeProbeAdjust(int dir);               /* крок вибраної частини (+1 -- сильніше ослаблення, -1 -- слабше) */
void volumeProbeResetAll(void);                /* обидва кроки до стокових (екран лишається) */
uint8_t volumeProbeSelected(void);             /* 0 -- DMR, 1 -- FM */
uint8_t volumeProbeDmrStep(void);
uint8_t volumeProbeFmStep(void);
bool volumeProbeFmBlocked(void);               /* FM-ослаблення зараз заборонене (APRS) */
bool volumeProbeFmApplies(void);               /* FM-крок реально діє (аналоговий режим, не заблоковано) */
uint32_t volumeProbeSecondsLeft(void);
#endif

#endif /* FUNCTIONS_VOLUME_PROBE_H_ */
