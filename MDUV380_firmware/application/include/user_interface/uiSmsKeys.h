/*
 * uiSmsKeys.h -- підказка літер клавіші і шпаргалка розкладки multitap (ui7). ОДНА реалізація на два екрани набору:
 * «Повідомлення» DMR (menuMessages.c) і повідомлення APRS (menuAprsMode.c, R11-fix2). Раніше жила статично в menuMessages.c
 * (composeKeyHint(), layoutUpdate()); сюди винесена без зміни вигляду.
 *
 * Малює в буфер екрана; displayRender() викликає екран-власник.
 */
#ifndef _OPENGD77_UI_SMS_KEYS_H_
#define _OPENGD77_UI_SMS_KEYS_H_

#include <stdint.h>
#include "functions/aprs_rx_cfg.h"

#if (defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)) || defined(APRS_RX)

/* Рядок символів клавіші `key` у режимі `mode`: FONT_SIZE_2 (8 px) від (x, y); поточний символ idx -- інверсно, пробіл -- '_'.
 * Вміщується 2n-1 клітинок (через пробіл), n -- впритул, інакше вікно навколо поточного. Нічого не малює, якщо в клавіші нема символів. */
void uiSmsKeyHint(uint8_t mode, char key, uint8_t idx, int16_t x, int16_t y);

/* Шпаргалка розкладки режиму `mode`: заголовок `title`, усі клавіші 1..9, 0, * з їхніми символами (FONT_SIZE_1, 26 символів у
 * рядку; довге -- впритул, ще довше -- обрізане з '>' в кінці), знизу підказка `hint`. Очищає екран; displayRender() -- за викликачем. */
void uiSmsKeyLayoutDraw(uint8_t mode, const char *title, const char *hint);

#endif
#endif /* _OPENGD77_UI_SMS_KEYS_H_ */
