/*
 * aprsrx_ua.h -- українські рядки справжнього приймача APRS (R8: aprs_rx.c, menuAprsStations.c).
 *
 * УВАГА: файл у кодуванні cp1251, як ukrainian.h/txerr_ua.h -- шрифт рації
 * HX8353E_charset_UA.h має кирилицю в позиціях 192-255. НЕ зберігати в UTF-8.
 *
 * Окремі макроси, а не поля stringsTable_t: структура мов спільна з CPS, а приймач існує лише в
 * українській збірці з ENABLE_APRS_RX (за патерном aprsprobe_ua.h).
 *
 * Ширина: FONT_SIZE_1 -- 6 px на символ, екран 128 px => до 21 символа в рядку; заголовок
 * (FONT_SIZE_2) -- 16; банер (рядок повідомлення) -- до 16 символів.
 */
#ifndef USER_INTERFACE_LANGUAGES_APRSRX_UA_H_
#define USER_INTERFACE_LANGUAGES_APRSRX_UA_H_

/* ---- одиниці та сектори (відстань і азимут: «3.2км NE») ---- */
#define APRSRX_M              "м"
#define APRSRX_KM             "км"

/* ---- типи пакета (другий рядок банера, якщо відстані нема) ---- */
#define APRSRX_T_POS          "позиція"
#define APRSRX_T_MSG          "повідомл."
#define APRSRX_T_STATUS       "статус"
#define APRSRX_T_OTHER        "пакет"

/* ---- банер: перший рядок «APRS ПОЗИВНИЙ» формується в коді (латиниця) ---- */
#define APRSRX_BANNER_FMT     "APRS %s\n%s"
#define APRSRX_MSG_NOTE_FMT   "APRS %s: %s"

/* ---- екран «APRS станції» ---- */
#define APRSRX_TITLE          "APRS станції"
#define APRSRX_EMPTY          "Станцій ще нема"
#define APRSRX_OFF_NOT_APRS   "Не канал APRS"
#define APRSRX_OFF_NOT_FM     "Лише аналог FM"
#define APRSRX_OFF_TX         "Передача"
#define APRSRX_OFF_SCAN       "Сканування"
#define APRSRX_OFF_PROMPT     "Голос. підказка"
#define APRSRX_OFF_REPLAY     "Переслухати"
#define APRSRX_OFF_MENU       "Екран зайнятий"
#define APRSRX_OFF_PROBE      "Відкрита проба"
#define APRSRX_OFF_BUSY       "I2S зайнятий"
#define APRSRX_OFF_NOWS       "Нема такту WS"
#define APRSRX_LISTENING      "Слухаю"
#define APRSRX_WAITING        "Запуск..."
#define APRSRX_AGE_S          "%luс"
#define APRSRX_AGE_M          "%luхв"
#define APRSRX_AGE_H          "%luг"
#define APRSRX_AGE_D          "%luд"
#define APRSRX_HINT_LIST      "GREEN:картка #:діагн."
#define APRSRX_HINT_CARD      "UP/DN:станція RED:назад"
#define APRSRX_HINT_DIAG      "0:скинути RED:назад"
#define APRSRX_CARD_POS       "Поз: %s"
#define APRSRX_CARD_NOPOS     "Позиції нема"
#define APRSRX_CARD_DIST      "Відст: %s"
#define APRSRX_CARD_NODIST    "Відстані нема"
#define APRSRX_CARD_PKTS      "Пакетів: %u"
#define APRSRX_CARD_LAST      "Остан.: %s тому"
#define APRSRX_CARD_TYPE      "Тип: %s"
#define APRSRX_STATUS_FMT     "%s %u/%u"
#define APRSRX_DIAG_NOBITS    "?"
#define APRSRX_CARD_PATH      "Шлях: %s"
#define APRSRX_CARD_MICE      "Mic-E"
#define APRSRX_DIAG_TITLE     "APRS приймач"

#endif /* USER_INTERFACE_LANGUAGES_APRSRX_UA_H_ */
