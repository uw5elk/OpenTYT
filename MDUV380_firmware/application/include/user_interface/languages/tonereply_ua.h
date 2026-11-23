/*
 * tonereply_ua.h -- R99-TONE: рядки «Тон-відгук» (меню «Опції рації», індикатор у шапці екрана каналу/VFO).
 *
 * УВАГА: файл у кодуванні cp1251, як volprobe_ua.h/roam_ua.h -- шрифт HX8353E_charset_UA.h має кирилицю в кодах 192-255. Не конвертувати в UTF-8.
 * Лише під ENABLE_TONE_REPLY + українська збірка (TONE_REPLY_ENABLED, tone_reply.h). Рядки -- прості макроси, а не поля stringsTable_t
 * (мовний файл CPS не змінюється). Пункт меню «підпис:значення» -- до 16 символів (tools/check_menu_widths.py).
 */
#ifndef USER_INTERFACE_LANGUAGES_TONEREPLY_UA_H_
#define USER_INTERFACE_LANGUAGES_TONEREPLY_UA_H_

#define TONEREPLY_MENU_ON      "Тон-відгук"      /* «Тон-відгук:Увімк» / «Тон-відгук:Вимк» */
#define TONEREPLY_MENU_FREQ    "Тон Гц"          /* «Тон Гц:1000» */
#define TONEREPLY_MENU_DUR     "Тон тривал"      /* «Тон тривал:1.0с» */
#define TONEREPLY_MENU_DELAY   "Тон затрим"      /* «Тон затрим:0.5с» */
#define TONEREPLY_ON           "Увімк"
#define TONEREPLY_OFF          "Вимк"
#define TONEREPLY_SEC          "с"               /* секунди: «1.0с» */
#define TONEREPLY_HDR          "ТВ"              /* індикатор у шапці (місце CC; у FM CC не показується) */

#endif /* USER_INTERFACE_LANGUAGES_TONEREPLY_UA_H_ */
