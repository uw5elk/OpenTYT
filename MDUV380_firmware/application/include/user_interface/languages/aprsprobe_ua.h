/*
 * aprsprobe_ua.h -- рядки діагностичного екрана «APRS проба» (R2, menuAprsRxProbe.c).
 *
 * ВАЖЛИВО: файл у кодуванні cp1251, як ukrainian.h/txerr_ua.h -- саме так шрифт
 * HX8353E_charset_UA.h трактує коди 192-255. Не зберігати в UTF-8.
 *
 * Окремим файлом, а не полями stringsTable_t: таблицю читає CPS. Екран існує лише в
 * українській збірці з ENABLE_APRS_RX_PROBE, тож англійських відповідників немає.
 *
 * Ширина: FONT_SIZE_1 -- 6 px на символ, екран 160 px => максимум 26 символів;
 * пункт меню (FONT_SIZE_3, буфер 17) -- до 16.
 */
#ifndef USER_INTERFACE_LANGUAGES_APRSPROBE_UA_H_
#define USER_INTERFACE_LANGUAGES_APRSPROBE_UA_H_

/* Пункт «Опції рації» і заголовок екрана. */
#define APRSPROBE_TITLE          "APRS проба"

/* DMR-канал: нічого не чіпаємо. */
#define APRSPROBE_ONLY_FM        "Лише FM"

/* Рядок 1: варіант джерела. А -- I2S з регістрами HR-C6000, Б -- PC3/ADC2. */
#define APRSPROBE_FMT_HDR_A      "А%u/%u E0=%02X 36=%02X 10=%02X"
#define APRSPROBE_FMT_HDR_B      "Б%u/%u PC3 ADC2 %u Гц"

/* Рядок 2: стан. Номер вікна (~4 за секунду) -- доказ, що відліки йдуть. */
#define APRSPROBE_FMT_RUN_A      "I2S 8000 Гц, вікно %lu"
#define APRSPROBE_FMT_RUN_B      "ADC2 кан.13, вікно %lu"
#define APRSPROBE_NO_WS          "I2S: немає такту WS"
#define APRSPROBE_BUSY           "Пауза: голос. підказка"
#define APRSPROBE_NO_DATA        "Немає даних > 1 с"
#define APRSPROBE_WAIT           "Чекаю дані..."

/* Три рядки на канал (L, R або PC3). Сирі одиниці джерела. */
#define APRSPROBE_FMT_LVL        "%-3s RMS %5lu пік %5lu"
#define APRSPROBE_FMT_TONES      "    1200 %5lu  2200 %5lu"
#define APRSPROBE_FMT_DC         "    DC %6ld %+3dдБ %s"
#define APRSPROBE_WIN_1200       ">1200"
#define APRSPROBE_WIN_2200       ">2200"
#define APRSPROBE_WIN_NONE       "рівні"
#define APRSPROBE_WIN_WEAK       "--"      /* тону немає -- лише шум */

/* Значення регістрів на вході (їх і відновлюємо). «?» -- прочитати не вдалося, відновлюються
 * штатні FM-значення. */
#define APRSPROBE_FMT_SAVED      "Було E0=%02X 36=%02X 10=%02X"
#define APRSPROBE_FMT_SAVED_BAD  "Було? E0=%02X 36=%02X 10=%02X"

#define APRSPROBE_FOOTER         "<> варіант    RED вихід"

#endif /* USER_INTERFACE_LANGUAGES_APRSPROBE_UA_H_ */
