/*
 * sms_multitap.h -- власний multitap для екрана «Нове повідомлення» (ui4).
 *
 * Чому не keypadAlphaEnable з io/keyboard.c: та таблиця лише латинська (abc2ABC ...), одна
 * на всі режими й без перемикання регістру. Тут -- кілька режимів, що їх циклічно перемикає
 * '#': «АБВ» -> «абв» -> «ABC» -> «abc» -> «123» (українська збірка) або «ABC» -> «abc» ->
 * «123» (решта). Таблиці -- const (flash), кирилиця -- байтами cp1251 (шрифт рації в
 * українській збірці індексується cp1251), без кириличних літералів у .c (ті -- UTF-8).
 *
 * Модуль ЧИСТИЙ (без таймерів і екрана): час підтвердження (~1 с) рахує викликач і передає
 * сюди лише «та сама клавіша ще в межах вікна чи ні». Тож уся логіка буфера тестується на
 * хості (tests/test_sms_multitap.c).
 *
 * Буфер: buf[0..*pos-1] -- підтверджений текст. Якщо st->key != 0, у buf[*pos] стоїть
 * символ, що ще «гортається» (попередній перегляд), і buf[*pos + 1] == 0; інакше buf[*pos] == 0.
 *
 * Лише під ENABLE_AES && ENABLE_DMR_DATA (як і menuMessages.c) або APRS_RX (R10: редактор «Режиму APRS»).
 */
#ifndef _OPENGD77_SMS_MULTITAP_H_
#define _OPENGD77_SMS_MULTITAP_H_

#include <stdint.h>
#include <stdbool.h>
#include "functions/aprs_rx_cfg.h"   /* R10: APRS_RX -- multitap потрібен і редактору «Режиму APRS» */

#if (defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)) || defined(APRS_RX)

/* Режими набору. Порядок -- порядок перемикання клавішею '#'. */
#if defined(LANGUAGE_BUILD_UKRAINIAN)
enum { SMS_MT_UA_UP = 0, SMS_MT_UA_LO, SMS_MT_LAT_UP, SMS_MT_LAT_LO, SMS_MT_NUM, SMS_MT_MODES };
#define SMS_MT_DEFAULT  SMS_MT_UA_LO      /* «абв» */
#else
enum { SMS_MT_LAT_UP = 0, SMS_MT_LAT_LO, SMS_MT_NUM, SMS_MT_MODES };
#define SMS_MT_DEFAULT  SMS_MT_LAT_LO     /* «abc» */
#endif

/* Час, за який символ, що гортається, підтверджується сам (мс). Як у keyboard.c. */
#define SMS_MT_TIMEOUT_MS  1000U

/* Стан перегляду: key = клавіша ('0'..'9', '*'), чий символ ще гортається; 0 -- нічого. */
typedef struct
{
	char    key;
	uint8_t idx;
} smsMt_t;

/* Наступний режим (для '#'); неприпустимий -> типовий. */
uint8_t     smsMtModeNext(uint8_t mode);
/* Підпис режиму для індикатора (cp1251, 3 символи). Неприпустимий -> підпис типового. */
const char *smsMtModeLabel(uint8_t mode);
/* Послідовність символів клавіші в режимі (cp1251, закінчується 0) або NULL, якщо клавіша
 * не текстова ('#', стрілки тощо). */
const char *smsMtKeyMap(uint8_t mode, char key);

/* Натиснута текстова клавіша key. sameWindow -- true, якщо ТА САМА клавіша натиснута ще до
 * спливання SMS_MT_TIMEOUT_MS від попереднього натискання. cap -- максимальна довжина тексту.
 * Повертає: 0 -- клавіша не текстова або місця немає (нічого не змінено, крім можливого
 * підтвердження попереднього символу); 1 -- символ у перегляді (запустити таймер);
 * 2 -- символ одразу підтверджено (у клавіші лише один варіант, напр. цифра в «123»). */
int  smsMtKey(smsMt_t *st, uint8_t mode, char key, bool sameWindow, char *buf, int16_t *pos, int cap);
/* Підтвердити символ, що гортається (таймаут, інша клавіша, '#', GREEN). */
void smsMtCommit(smsMt_t *st, int16_t *pos);
/* Стерти: спершу символ, що гортається, інакше останній підтверджений. */
void smsMtBackspace(smsMt_t *st, char *buf, int16_t *pos);

#endif
#endif /* _OPENGD77_SMS_MULTITAP_H_ */
