/*
 * roam_ua.h -- R59: рядки меню «Роумінг» та індикаторів (ENABLE_ROAM_RETRY) українською.
 *
 * ВАЖЛИВО: файл у кодуванні cp1251, як ukrainian.h/messages_ua.h/txerr_ua.h/wakediag_ua.h -- саме так шрифт
 * HX8353E_charset_UA.h трактує коди 192-255. Не зберігати в UTF-8.
 *
 * Чому окремим файлом, а не полями в stringsTable_t: цю таблицю читає ще й CPS, і додавання полів ламає
 * сумісність мовних файлів (той самий підхід, що для SMS, RCTL, журналу пробудження).
 *
 * Ширина: FONT_SIZE_3 -- 8 px на символ, екран 160 px; рядок «підпис:значення» тримаємо до 17 символів.
 * FONT_SIZE_1 -- 6 px на символ, до 26 символів у рядок.
 */
#ifndef USER_INTERFACE_LANGUAGES_ROAM_UA_H_
#define USER_INTERFACE_LANGUAGES_ROAM_UA_H_

#define ROAM_MENU_NAME        "Роумінг"
#define ROAM_ROW_AUTO_FMT     "Автоперехід:%s"
#define ROAM_ROW_HOPS_FMT     "Макс.стрибків:%u"
#define ROAM_ROW_CUR_FMT      "Цей у списку:%s"
#define ROAM_ROW_LIST_FMT     "Список (%u)"
#define ROAM_ON_S             "Увімк"
#define ROAM_OFF_S            "Вимк"
#define ROAM_YES_S            "Так"
#define ROAM_NO_S             "Ні"

/* Екран «Список» (лише перегляд). */
#define ROAM_LIST_TITLE_FMT   "Список %u/%u"
#define ROAM_LIST_EMPTY       "(список порожній)"
#define ROAM_LIST_HINT        "U/D:гортати RED:назад"

/* Сповіщення. */
#define ROAM_MSG_ADDED        "Додано\nдо списку"
#define ROAM_MSG_REMOVED      "Прибрано\nзі списку"
#define ROAM_MSG_UNSUITABLE   "Канал не придатний:\nлише цифровий\nретранслятор"
#define ROAM_MSG_NOT_CHANNEL  "Роумінг лише\nна каналах (не VFO)"
#define ROAM_MSG_SAVE_ERR     "Помилка запису"

/* Індикатори на екрані каналу / передачі. */
#define ROAM_IND_LIST         "Р"                     /* поточний канал у списку, функція увімкнена */
#define ROAM_IND_SPARE        "Р>"                    /* рація на каналі, знайденому автопереходом */
#define ROAM_ZONE_SPARE_FMT   "Р> канал %d"           /* рядок зони замість «зона Ch:N» (канал поза зоною) */

#endif /* USER_INTERFACE_LANGUAGES_ROAM_UA_H_ */
