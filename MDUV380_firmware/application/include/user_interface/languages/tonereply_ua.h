/*
 * tonereply_ua.h -- R99-TONE / R100-TONE / R102-TONE: рядки «Тон-відгук» (пункт головного меню й підменю menuToneReply.c, індикатор у шапці екрана каналу/VFO).
 *
 * УВАГА: файл у кодуванні cp1251, як volprobe_ua.h/roam_ua.h -- шрифт HX8353E_charset_UA.h має кирилицю в кодах 192-255. Не конвертувати в UTF-8.
 * Лише під ENABLE_TONE_REPLY + українська збірка (TONE_REPLY_ENABLED, tone_reply.h). Рядки -- прості макроси, а не поля stringsTable_t
 * (мовний файл CPS не змінюється). Пункт «підпис:значення» -- до 16 символів (tools/check_menu_widths.py, розділ 10).
 */
#ifndef USER_INTERFACE_LANGUAGES_TONEREPLY_UA_H_
#define USER_INTERFACE_LANGUAGES_TONEREPLY_UA_H_

#define TONEREPLY_MAIN         "Тон-відгук"      /* пункт головного меню і заголовок підменю */
#define TONEREPLY_MENU_ON      "Тон-відгук"      /* «Тон-відгук:Увімк» / «Тон-відгук:Вимк» */
#define TONEREPLY_MENU_FREQ    "Частота"         /* «Частота:1000» */
#define TONEREPLY_MENU_DUR     "Тривал"          /* «Тривал:10с» */
#define TONEREPLY_MENU_DELAY   "Затрим"          /* «Затрим:2с» */
#define TONEREPLY_MENU_THRESH  "Поріг"           /* «Поріг:1.0с» (R110: крок 0,1 с; найдовше «Поріг:5.0с» -- 10 символів) */
#define TONEREPLY_ON           "Увімк"
#define TONEREPLY_OFF          "Вимк"
#define TONEREPLY_SEC          "с"               /* секунди: «10с» */
#define TONEREPLY_HDR          "ТВ"              /* індикатор у шапці (місце CC; у FM CC не показується) */

#endif /* USER_INTERFACE_LANGUAGES_TONEREPLY_UA_H_ */
