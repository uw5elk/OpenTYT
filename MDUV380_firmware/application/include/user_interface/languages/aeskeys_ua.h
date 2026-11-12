/*
 * aeskeys_ua.h -- R64C: рядки перейменування AES-ключів (menuAESKeys.c, ENABLE_AES_KEY_NAMES) українською.
 *
 * ВАЖЛИВО: файл у кодуванні cp1251, як roam_ua.h/ukrainian.h -- саме так шрифт HX8353E_charset_UA.h трактує коди 192-255. Не зберігати в UTF-8.
 * Меню «AES Keys» решту підписів має англійськими -- їх не чіпаємо; нове -- редактор імені (R64C) і рядки списку «Ключ N:» з галочкою (R96/А3).
 */
#ifndef USER_INTERFACE_LANGUAGES_AESKEYS_UA_H_
#define USER_INTERFACE_LANGUAGES_AESKEYS_UA_H_

#define AESK_LIST_FMT         "Ключ %d:"   /* R96/А3: рядок списку ключів; значення "записано" малюється галочкою (uiDrawTickMark), порожнє -- "---" */
#define AESK_REN_TITLE_FMT    "Ім'я ключа %d"
#define AESK_MSG_RENAMED      "Ім'я ключа\nзбережено"
#define AESK_MSG_SAVE_ERR     "Помилка запису"

#define AESK_DET_LABEL_SHORT  "Ключ"   /* R65A: короткий підпис рядка ключа в «Деталях каналу», коли в ключа є ім'я (з «Шифр. TX» ім'я не вміщається в 16 символів) */

#endif /* USER_INTERFACE_LANGUAGES_AESKEYS_UA_H_ */
