/*
 * wakediag_ua.h -- R58: рядки сторінки «Журнал пробудж.» (меню «Повідомлення», лише з ENABLE_WAKE_DIAG) українською.
 *
 * ВАЖЛИВО: файл у кодуванні cp1251, як ukrainian.h/messages_ua.h/txerr_ua.h -- саме так шрифт HX8353E_charset_UA.h
 * трактує коди 192-255. Не зберігати в UTF-8. Лише діагностична збірка; поля stringsTable_t не чіпаємо
 * (ту таблицю читає ще й CPS).
 *
 * Ширина: FONT_SIZE_1 -- 6 px на символ, екран 160 px => максимум 26 символів у рядок.
 */
#ifndef USER_INTERFACE_LANGUAGES_WAKEDIAG_UA_H_
#define USER_INTERFACE_LANGUAGES_WAKEDIAG_UA_H_

#define WAKE_TITLE_FMT    "Пробудж. %u/%u"
#define WAKE_ITEM         "Журнал пробудж."
#define WAKE_EMPTY        "(пробуджень ще не було)"
#define WAKE_HINT         "U/D:сеанс дов.GRN:скид"
#define WAKE_L1_FMT       "#%u RX %lu.%04lu CC%u"
#define WAKE_L2_FMT       "TX %lu.%04lu to0=%u"
#define WAKE_L3_FMT       "поп:%s стр:%s пр %u"
#define WAKE_PKT_FMT      "Пак%u:"
#define WAKE_ZERO_FMT     "Нуль%u:"
#define WAKE_L7_FMT       "Прб %s Пер %s Вд %s"
#define WAKE_L8_FMT       "ts%u it%u стр %s>%u"
#define WAKE_PREV_NONE_S  "-"
#define WAKE_PREV_OK_S    "ок"
#define WAKE_PREV_FAIL_S  "вд"
#define WAKE_PREV_CNCL_S  "обр"
#define WAKE_YES_S        "т"
#define WAKE_NO_S         "н"

#endif /* USER_INTERFACE_LANGUAGES_WAKEDIAG_UA_H_ */
