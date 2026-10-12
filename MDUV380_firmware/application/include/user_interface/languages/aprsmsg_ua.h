/*
 * aprsmsg_ua.h -- українські рядки екрана «Повідомлення APRS» (R11: menuAprsMode.c, menuAprsHub.c).
 *
 * УВАГА: файл у кодуванні cp1251, як aprsmode_ua.h/aprsrx_ua.h/ukrainian.h -- шрифт рації HX8353E_charset_UA.h має
 * кирилицю в позиціях 192-255. НЕ зберігати в UTF-8.
 *
 * Окремі макроси, а не поля stringsTable_t (структура мов спільна з CPS; екран існує лише в українській збірці з
 * ENABLE_APRS_RX -- за патерном aprsmode_ua.h). Англійської гілки тому немає: без LANGUAGE_BUILD_UKRAINIAN екран не
 * збирається взагалі (aprs_rx_cfg.h).
 *
 * Ширина: рядок екрана (FONT_SIZE_1) -- 26 символів; заголовок і пункт меню -- 16; рядок сповіщення -- 16; слово стану в рядку
 * списку -- 9; великий шрифт (FONT_SIZE_3) -- 20 символів. Перевірка -- tools/check_menu_widths.py (розділ 8).
 */
#ifndef USER_INTERFACE_LANGUAGES_APRSMSG_UA_H_
#define USER_INTERFACE_LANGUAGES_APRSMSG_UA_H_

/* ---- пункт меню «APRS» і заголовки ---- */
#define APRSMSG_MENU          "Повідом. APRS"
#define APRSMSG_TITLE         "Повідом. APRS"
#define APRSMSG_TITLE_NEW     "Нове повідом."
#define APRSMSG_TITLE_REPLY   "Відповідь"
#define APRSMSG_TITLE_READ    "Повідом. APRS"

/* ---- слова стану вихідного повідомлення (у рядку списку -- 9 символів) ---- */
#define APRSMSG_ST_WAIT       "чекає"
#define APRSMSG_ST_SENT       "надіслано"
#define APRSMSG_ST_ACK        "ACK"
#define APRSMSG_ST_NOACK      "без ACK"

/* ---- список ---- */
#define APRSMSG_L_HDR         "Нових: %u  В черзі: %u"
#define APRSMSG_L_EMPTY       "Повідомлень нема"
#define APRSMSG_L_HINT        "GREEN:чит. *:нове <>:стор"
#define APRSMSG_L_NOTIME      "--"

/* ---- читання ---- */
#define APRSMSG_R_FROM        "Від: %s"
#define APRSMSG_R_TO          "Кому: %s"
#define APRSMSG_R_HINT        "GREEN:відповісти RED:назад"

/* ---- набір ---- */
#define APRSMSG_C_CALL        "Кому (позивний):"
#define APRSMSG_C_CALL_HINT   "A-Z, 0-9, -SSID"
#define APRSMSG_C_CALL_KEYS   "GREEN:далі RED:скасув."
#define APRSMSG_C_TO          "Кому: %s"
#define APRSMSG_C_LEFT        "Лишилось: %u Б"
#define APRSMSG_C_MODE_HINT   "#:режим"
#define APRSMSG_C_HINT1       "<:стерти"
#define APRSMSG_C_HINT2       "GREEN:надіслати RED:назад"

/* ---- сповіщення (до 16 символів) ---- */
#define APRSMSG_E_CALL        "Невірн.позивний"
#define APRSMSG_E_TEXT        "Порожній текст"
#define APRSMSG_E_FULL        "Черга повна"
#define APRSMSG_E_EXIT        "RED ще раз:вихід"
#define APRSMSG_E_NOTX        "Не передано"

#endif /* USER_INTERFACE_LANGUAGES_APRSMSG_UA_H_ */
