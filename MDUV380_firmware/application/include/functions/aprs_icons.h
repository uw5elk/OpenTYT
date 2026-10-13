/*
 * aprs_icons.h -- R14: піктограми символів APRS 24x24 (R17; були 16x16) (монохромний XBM, const у flash, 0 байт RAM/CCM) для вікна маяка.
 * Малює uiNotification.c через displayDrawXBitmap(). Чистий C -- перевіряє хост-тест test_aprs_rx_parse.
 */
#ifndef FUNCTIONS_APRS_ICONS_H_
#define FUNCTIONS_APRS_ICONS_H_

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include "functions/aprs_rx_cfg.h"

#define APRS_ICON_W   24
#define APRS_ICON_H   24

/* Піктограма для символу (таблиця, код). Таблиця '/' -- первинна, '\\' -- додаткова, цифра/літера -- ДОДАТКОВА з накладкою
 * (*overlay = true: знак таблиці малюють у центрі). NULL -- піктограми нема (малюють рамку з кодом). */
const uint8_t *aprsIconFind(char table, char code, bool *overlay);
/* Скільки піктограм у таблиці (для звіту/тестів). */
unsigned aprsIconCount(void);

#endif /* FUNCTIONS_APRS_ICONS_H_ */
