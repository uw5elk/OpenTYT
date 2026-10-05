/*
 * uiSms.h -- спільне для банера SMS (uiNotification.c) і екранів «Повідомлень» (menuMessages.c),
 * ui6: позивний/ім'я замість ID, місцевий час повідомлення, текст з перенесенням за словами.
 *
 * Лише під ENABLE_AES && ENABLE_DMR_DATA.
 */
#ifndef _OPENGD77_UI_SMS_H_
#define _OPENGD77_UI_SMS_H_

#include <stdint.h>
#include "hardware/HX8353E.h"

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)

/* Символів у рядку тексту SMS (font_8x8 і font_8x16 -- обидва 8 px, екран 160 px, x = 0). */
#define UI_SMS_COLS  20

/* Позивний/ім'я: контакт кодплага (TG -- якщо group), потім база DMR ID, інакше число
 * («TG 9» для групи). out -- щонайменше 20 Б. Та сама логіка, що для вхідного дзвінка. */
void uiSmsWhoStr(uint32_t id, int group, char *out, int outsz);

/* Час повідомлення (с UTC) у місцевому поясі (nonVolatileSettings.timezone, як годинник на
 * головному екрані); «сьогодні» -- за годинником рації. mode -- SMS_TIME_* (sms_format.h).
 * Час 0 -> порожній рядок. Повертає довжину. */
int  uiSmsTimeStr(uint32_t t, int mode, char *out, int outsz);

/* Текст з перенесенням за словами (smsWrapLine, cols символів у рядку): малює рядки
 * [first, first + maxLines) з (x, y) через lineH. ellipsis != 0 -- якщо після останнього
 * показаного рядка текст ще є, закінчити його «...». Повертає загальну кількість рядків. */
int  uiSmsDrawWrapped(const char *txt, int n, int cols, int first, int maxLines, int16_t x, int16_t y,
                      int16_t lineH, ucFont_t font, int ellipsis);

#endif
#endif /* _OPENGD77_UI_SMS_H_ */
