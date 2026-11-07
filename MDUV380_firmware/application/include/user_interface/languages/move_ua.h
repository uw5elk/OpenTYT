/*
 * move_ua.h -- R66C: рядки дій «Вгору / Вниз» (переміщення каналу в зоні, menuZoneList.c, і контакту в складі списку прийому, menuRxGroups.c) українською.
 *
 * ВАЖЛИВО: файл у кодуванні cp1251, як roam_ua.h/rxgroup_ua.h. Не зберігати в UTF-8. Рядки НЕ в stringsTable_t (її читає CPS).
 * Ширина: FONT_SIZE_3 -- 8 px на символ, до 16 символів у рядок сповіщення.
 */
#ifndef USER_INTERFACE_LANGUAGES_MOVE_UA_H_
#define USER_INTERFACE_LANGUAGES_MOVE_UA_H_

#define MV_ACT_UP        "Вгору"
#define MV_ACT_DOWN      "Вниз"
#define MV_ACT_REMOVE    "Вийняти"
#define MV_MSG_FIRST     "Це перший\nу списку"
#define MV_MSG_LAST      "Це останній\nу списку"
#define MV_MSG_EDGE      "Межа сектора:\nвикористайте CPS"
#define MV_MSG_SAVE_ERR  "Помилка\nзапису"

#endif
