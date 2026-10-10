/*
 * aprsprobe_ua.h -- рядки діагностичного екрана «APRS проба» (R2/R3, menuAprsRxProbe.c).
 *
 * ВАЖЛИВО: файл у кодуванні cp1251, як ukrainian.h/txerr_ua.h -- саме так шрифт
 * HX8353E_charset_UA.h трактує коди 192-255. Не зберігати в UTF-8.
 *
 * Окремим файлом, а не полями stringsTable_t: таблицю читає CPS. Екран існує лише в
 * українській збірці з ENABLE_APRS_RX_PROBE, тож англійських відповідників немає.
 *
 * Ширина: FONT_SIZE_1 -- 6 px на символ, екран 160 px => максимум 26 символів (з найдовшими
 * числами -- перевірено рендером R4; «Макс» -- градуси);
 * заголовок (FONT_SIZE_2) -- 20; пункт меню (FONT_SIZE_3, буфер 17) -- до 16.
 */
#ifndef USER_INTERFACE_LANGUAGES_APRSPROBE_UA_H_
#define USER_INTERFACE_LANGUAGES_APRSPROBE_UA_H_

/* Пункт «Опції рації» і заголовки сторінок. */
#define APRSPROBE_TITLE          "APRS проба"
#define APRSPROBE_TITLE_PKT      "APRS проба: пакети"
#define APRSPROBE_TITLE_BG       "APRS проба: фон"
#define APRSPROBE_TITLE_STREAM   "APRS проба: потік"
#define APRSPROBE_TITLE_FRAME    "APRS проба: кадр"

/* DMR-канал: нічого не чіпаємо. */
#define APRSPROBE_ONLY_FM        "Лише FM"

/* Рядок 0: варіант (номер з R2, позиція з 6, регістри). */
#define APRSPROBE_FMT_HDR        "А%u %u/%u E0=%02X 36=%02X 10=%02X"

/* Рядок 1: стан I2S. */
#define APRSPROBE_FMT_RUN        "I2S: блоків %lu"
#define APRSPROBE_NO_WS          "I2S: немає такту WS"
#define APRSPROBE_BUSY           "Пауза: голос. підказка"
#define APRSPROBE_NO_DATA        "Немає даних > 1 с"
#define APRSPROBE_WAIT           "Чекаю дані..."

/* Сторінка «пакети» -- лічильники поточного варіанта. */
#define APRSPROBE_FMT_OK         "Кадрів FCS ок: %u"
#define APRSPROBE_FMT_BAD        "FCS помилка: %u"
#define APRSPROBE_FMT_FLAGS      "Серій прапорців: %u"
#define APRSPROBE_LAST_NONE      "Правильних кадрів ще нема"
#define APRSPROBE_FMT_NOTCH      "Режекція: %u Гц"
#define APRSPROBE_NOTCH_AUTO     "Режекція: авто, не треба"
#define APRSPROBE_NOTCH_OFF      "Режекція: вимкнена (#)"

/* Сторінка «фон» -- розгортка 100..3900 Гц на поточному варіанті. */
#define APRSPROBE_FMT_RMS        "RMS %u  DC %d"
#define APRSPROBE_FMT_TOP1       "Топ-1 %u Гц  A=%u"
#define APRSPROBE_FMT_SHARE      "  частка %u %% RMS"
#define APRSPROBE_FMT_TOP2       "Топ-2 %u Гц  A=%u"
#define APRSPROBE_BG_WAIT        "Розгортка... (0,5 с)"
#define APRSPROBE_FMT_FS         "fs %lu Гц (за %lu с)"
#define APRSPROBE_FS_WAIT        "fs: вимірюю (5 с)"
#define APRSPROBE_FMT_LOST       "Втрачено блоків: %lu"

/* R4, сторінка «потік»: сталий тон 1200 Гц -- фаза на межах блоків по 160 (DMA-половин). */
#define APRSPROBE_FMT_TONE       "Тон 1200 A=%u бл.%lu"
#define APRSPROBE_FMT_JUMP_B     "Стрибки >30: межа %lu"
#define APRSPROBE_FMT_JUMP_IN    " всередині %lu (контр.)"
#define APRSPROBE_FMT_JUMP_MAX   "Макс: межа %u, вн. %u"
#define APRSPROBE_FMT_TONE_OFF   "Розстройка тону %s%lu.%lu Гц"
#define APRSPROBE_FMT_DMA        "DMA пол/пов %lu/%lu"
#define APRSPROBE_FMT_DMA_ORDER  "  порушень черги: %lu"
#define APRSPROBE_FMT_USB        "USB %lu/%lu, втр. %lu"

/* R4, сторінка «кадр»: останній кадр із помилковим FCS і фаза тактів. */
#define APRSPROBE_FMT_BADLEN     "FCS-помилка: %u Б"
#define APRSPROBE_BAD_NONE       "Помилкових кадрів ще нема"
#define APRSPROBE_FMT_ADDR       "Адр.: %s"
#define APRSPROBE_PLL_TITLE      "ФАПЧ, % на 1/8 біта:"
#define APRSPROBE_FMT_PLL_N      "переходів: %lu"

/* Значення регістрів на вході (їх і відновлюємо). «?» -- прочитати не вдалося, відновлюються
 * штатні FM-значення. */
#define APRSPROBE_FMT_SAVED      "Було E0=%02X 36=%02X 10=%02X"
#define APRSPROBE_FMT_SAVED_BAD  "Було? E0=%02X 36=%02X 10=%02X"

#define APRSPROBE_FOOTER1        "^v стор.  GREEN скинути"
#define APRSPROBE_FOOTER2        "<> варіант #реж RED вихід"

#endif /* USER_INTERFACE_LANGUAGES_APRSPROBE_UA_H_ */
