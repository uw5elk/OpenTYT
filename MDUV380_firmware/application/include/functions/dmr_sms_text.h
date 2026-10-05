/*
 * dmr_sms_text.h -- текст SMS: cp1251 (шрифт і сховище рації) <-> UTF-16LE (ефір, TMS) (ui4).
 *
 * Шрифт рації в українській збірці індексується cp1251, сховище SMS -- байти (char): 1 байт =
 * 1 символ на екрані. В ефірі текст TMS -- UTF-16LE (стокова TYT шле кирилицю як U+0410..U+044F).
 * Таблиця -- повна Windows-1251 (const, у flash): 0x00..0x7F як є, 0xC0..0xFF -> U+0410..U+044F,
 * 0x80..0xBF -- за таблицею (Ґ ґ Є є І і Ї ї Ё ё № ...). Байт 0x98 у cp1251 не визначений -> '?'.
 *
 * Лише під ENABLE_AES (як crypto/dmr_aes.c, що з нього розбирає вхідний текст). Без заліза --
 * хостові тести лінкують цей файл.
 */
#ifndef _OPENGD77_DMR_SMS_TEXT_H_
#define _OPENGD77_DMR_SMS_TEXT_H_

#include <stdint.h>

#if defined(ENABLE_AES)

/* Байт cp1251 -> код Unicode (U+0000..U+FFFF). Невизначений (0x98) -> '?'. */
uint16_t dmrSmsCp1251ToUcs2(uint8_t c);
/* Код Unicode -> байт cp1251. Чого в cp1251 немає -> '?'. Керівні U+0001..U+001F (CR, LF, TAB
 * тощо) -> пробіл. U+0000 -> 0 (викликач пропускає). */
uint8_t  dmrSmsUcs2ToCp1251(uint16_t u);

#endif
#endif /* _OPENGD77_DMR_SMS_TEXT_H_ */
