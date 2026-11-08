/*
 * volprobe_ua.h -- рядки діагностичного екрана «Гучн. проба» (R77A, menuVolumeProbe.c).
 *
 * УВАГА: файл у кодуванні cp1251, як ukrainian.h/aprsprobe_ua.h -- шрифт HX8353E_charset_UA.h має кирилицю в кодах 192-255. Не конвертувати в UTF-8.
 * Лише під ENABLE_VOLUME_PROBE + українська збірка. Рядки -- прості макроси, а не поля stringsTable_t (ті пише CPS). Довжина ряду на екрані (FONT_SIZE_1,
 * 6 px) -- до 26 символів.
 */
#ifndef USER_INTERFACE_LANGUAGES_VOLPROBE_UA_H_
#define USER_INTERFACE_LANGUAGES_VOLPROBE_UA_H_

#define VOLPROBE_MENU_NAME     "Гучн. проба"
#define VOLPROBE_MENU_ENTER    "вхід"
#define VOLPROBE_TITLE         "Гучн. проба"
#define VOLPROBE_POT           "Потенц.:%+d дБ (рів.%d)"
#define VOLPROBE_MODE_FM       "Режим: FM"
#define VOLPROBE_MODE_DMR      "Режим: DMR"
#define VOLPROBE_MODE_OTHER    "Режим: --"
#define VOLPROBE_DMR_ROW       "%cDMR: %s (%d дБ)"
#define VOLPROBE_FM_ROW        "%cFM:  %u%% (0x%02X%02X)"
#define VOLPROBE_FM_BLOCKED    "FM заблоковано (APRS)"
#define VOLPROBE_DMR_IDLE      "DMR-крок діє лише в DMR"
#define VOLPROBE_FM_IDLE       "FM-крок діє лише в FM"
#define VOLPROBE_KEYS1         "Вгору/Вниз: DMR<>FM"
#define VOLPROBE_KEYS2         "Вліво/Вправо: крок"
#define VOLPROBE_KEYS3         "0: стокове  Червона: вихід"
#define VOLPROBE_LEFT          "Само скинеться через %u с"

#endif /* USER_INTERFACE_LANGUAGES_VOLPROBE_UA_H_ */
