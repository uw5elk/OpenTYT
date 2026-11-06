/*
 * roam_ua.h -- R59/R60: рядки меню «Роумінг» та індикаторів (ENABLE_ROAM_RETRY) українською.
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
#define ROAM_ROW_CHLIST_FMT   "Спис.каналу:%s%s"      /* значення (Вимк, 1..10) і «*», поки зміну не збережено зеленою */
#define ROAM_ROW_LISTS_S      "Списки"
#define ROAM_ON_S             "Увімк"
#define ROAM_OFF_S            "Вимк"

/* R60: «Деталі каналу», новий останній пункт. */
#define ROAM_DET_LABEL        "Роум.список"

/* R60: вибір списку 1..10. */
#define ROAM_PICK_TITLE       "Списки роумінгу"
#define ROAM_PICK_ROW_FMT     "Список %u"

/* R60: члени списку; останній рядок додає канал. */
#define ROAM_MEM_TITLE_FMT    "Список %u (%u)"
#define ROAM_ADD_ROW          "+ Додати канал..."
#define ROAM_ADD_TITLE_FMT    "У список %u"

/* R60: підтвердження. */
#define ROAM_CFM_REMOVE_TITLE "Прибрати канал?"
#define ROAM_CFM_FROM_FMT     "зі списку %u"
#define ROAM_CFM_MOVE_TITLE   "Перенести канал?"
#define ROAM_CFM_MOVE_FMT     "зі списку %u в %u"

/* Сповіщення. */
#define ROAM_MSG_ADDED        "Додано\nдо списку"
#define ROAM_MSG_REMOVED      "Прибрано\nзі списку"
#define ROAM_MSG_MOVED        "Перенесено\nу список"
#define ROAM_MSG_ALREADY      "Уже в цьому\nсписку"
#define ROAM_MSG_UNSUITABLE   "Канал не придатний:\nлише цифровий\nретранслятор"
#define ROAM_MSG_NOT_CHANNEL  "Роумінг лише\nна каналах (не VFO)"
#define ROAM_MSG_READONLY     "Канали захищені\nвід запису"
#define ROAM_MSG_SAVE_ERR     "Помилка запису"

/* Індикатори на екрані каналу / передачі. */
#define ROAM_IND_LIST         "Р"                     /* поточний канал у списку, функція увімкнена; з номером списку: « Р1».. « Р10» */
#define ROAM_IND_SPARE        "Р>"                    /* рація на каналі, знайденому автопереходом */
#define ROAM_ZONE_SPARE_FMT   "Р> канал %d"           /* рядок зони замість «зона Ch:N» (канал поза зоною) */

#endif /* USER_INTERFACE_LANGUAGES_ROAM_UA_H_ */
