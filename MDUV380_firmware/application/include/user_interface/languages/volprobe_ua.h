/*
 * volprobe_ua.h -- рядки діагностичного екрана «Гучн. проба» (R77A, menuVolumeProbe.c).
 *
 * УВАГА: файл у кодуванні cp1251, як ukrainian.h/aprsprobe_ua.h -- шрифт HX8353E_charset_UA.h має кирилицю в кодах 192-255. Не конвертувати в UTF-8.
 * Лише під ENABLE_VOLUME_PROBE + українська збірка. Рядки -- прості макроси, а не поля stringsTable_t (ті пише CPS). Довжина ряду -- до 16 символів (R77B: на фото рації обрізались рядки довші за ~16-17, тож межу 26 прибрано).
 */
#ifndef USER_INTERFACE_LANGUAGES_VOLPROBE_UA_H_
#define USER_INTERFACE_LANGUAGES_VOLPROBE_UA_H_

#define VOLPROBE_MENU_NAME     "Гучн. проба"
#define VOLPROBE_MENU_ENTER    "вхід"
#define VOLPROBE_TITLE         "Гучн. проба"
#define VOLPROBE_POT           "Ручка %+dдБ р%d"
#define VOLPROBE_TITLE_FM      "Гучн. проба FM"
#define VOLPROBE_TITLE_DMR     "Гучн. проба DMR"
#define VOLPROBE_DMR_ROW       "%cDMR %s %dдБ"
#define VOLPROBE_FM_ROW        "%cFM %s %dдБ"
#define VOLPROBE_HEX_ROW       "0x06%02X скид %uс"
#define VOLPROBE_FM_BLOCKED    "FM: APRS-блок"
#define VOLPROBE_DMR_IDLE      "DMR лише в DMR"
#define VOLPROBE_FM_IDLE       "FM лише в FM"
#define VOLPROBE_FM_NOTE       "FM дБ -- розрах."
#define VOLPROBE_KEYS1         "Верх/Низ: DMR/FM"
#define VOLPROBE_KEYS2         "Ліво/Право: крок"
#define VOLPROBE_KEYS3         "0: стокове"
#define VOLPROBE_KEYS4         "Червона: вихід"

#endif /* USER_INTERFACE_LANGUAGES_VOLPROBE_UA_H_ */
