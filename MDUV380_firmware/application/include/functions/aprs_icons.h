/*
 * aprs_icons.h -- піктограми символів APRS 24x24 (монохромний XBM, const у flash, 0 байт RAM/CCM) для вікна маяка та переліку символів.
 * R20 Ж2: власне малювання, джерело tools/aprs_icons.txt -> tools/aprs_icons_gen.py -> aprs_icons.c. Малює uiNotification.c через
 * displayDrawXBitmap(). Чистий C -- перевіряє хост-тест test_aprs_icons.
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
 * (*overlay = true: знак таблиці малюють у куті 8x8). NULL -- піктограми нема (зарезервований/невідомий код): малюють рамку 24x24
 * зі ЗНАКОМ коду великим шрифтом FONT_SIZE_3 (8x16) по центру -- рамка (x+8, y+4) -- не крапку. */
const uint8_t *aprsIconFind(char table, char code, bool *overlay);
/* Скільки піктограм у таблиці (для звіту/тестів). */
unsigned aprsIconCount(void);

#endif /* FUNCTIONS_APRS_ICONS_H_ */
