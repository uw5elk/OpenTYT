/*
 * rxgroup_ua.h -- R65B: рядки меню «Списки прийому» (menuRxGroups.c, ENABLE_RXGROUP_EDIT) українською.
 *
 * ВАЖЛИВО: файл у кодуванні cp1251, як roam_ua.h/aeskeys_ua.h. Не зберігати в UTF-8. Рядки НЕ в stringsTable_t (її читає CPS).
 * Ширина: FONT_SIZE_3 -- 8 px на символ, до 16-18 символів у рядок.
 */
#ifndef USER_INTERFACE_LANGUAGES_RXGROUP_UA_H_
#define USER_INTERFACE_LANGUAGES_RXGROUP_UA_H_

#define RXG_MENU_NAME         "Списки прийому"
#define RXG_NEW_ROW           "+ Новий список"
#define RXG_NEW_TITLE         "Новий список"
#define RXG_REN_TITLE         "Назва списку"
#define RXG_ACT_MEMBERS       "Склад"
#define RXG_ACT_RENAME        "Перейменувати"
#define RXG_ACT_DELETE        "Видалити"
#define RXG_MEM_TITLE_FMT     "%.11s (%u)"
#define RXG_ADD_ROW           "+ Додати контакт"
#define RXG_PICK_TITLE        "Контакт (TG)"
#define RXG_PICK_FIRST_TITLE  "Перший контакт"
#define RXG_RM_TITLE          "Вийняти контакт?"
#define RXG_RM_LAST_HINT      "Останній: список"
#define RXG_RM_LAST_HINT2     "буде видалено"
#define RXG_DEL_TITLE         "Видалити список?"
#define RXG_DEL_CHANS_FMT     "Каналів: %u"
#define RXG_MSG_CREATED       "Список\nстворено"
#define RXG_MSG_RENAMED       "Назву\nзмінено"
#define RXG_MSG_ADDED         "Контакт\nдодано"
#define RXG_MSG_REMOVED       "Контакт\nвийнято"
#define RXG_MSG_DELETED       "Список\nвидалено"
#define RXG_MSG_SAVE_ERR      "Помилка\nзапису"
#define RXG_MSG_NAME_EMPTY    "Назва\nпорожня"
#define RXG_MSG_NAME_DUP      "Така назва\nвже є"
#define RXG_MSG_NAME_TAIL     "Скоротіть назву\n16 знаків із «я»"
#define RXG_MSG_FULL          "Усі 76 списків\nзайняті"
#define RXG_MSG_MAX           "Не більше\n32 контактів"
#define RXG_MSG_DUP_MEMBER    "Контакт уже\nу списку"
#define RXG_MSG_NO_TG         "Нема TG-\nконтактів"
#define RXG_MSG_READONLY      "Кодплаг\nзахищено"
#define RXG_BUSY_TITLE        "Запис списку"
#define RXG_BUSY_HINT         "Не вимикайте"

#endif /* USER_INTERFACE_LANGUAGES_RXGROUP_UA_H_ */
