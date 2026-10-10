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
#define APRSPROBE_TITLE_REGS     "APRS проба: регістри"
#define APRSPROBE_TITLE_PHASE    "APRS проба: фаза"
#define APRSPROBE_TITLE_SCAN     "APRS проба: скан"

/* DMR-канал: нічого не чіпаємо. */
#define APRSPROBE_ONLY_FM        "Лише FM"

/* Рядок 0: варіант (номер з R2, позиція з 6, регістри). */
#define APRSPROBE_FMT_HDR        "А%u %u/%u E0=%02X 36=%02X 10=%02X"

/* Рядок 1: стан I2S. R7: «авто» -- nbits за вердиктом детектора (? -- вердикту ще нема); ручні
 * режими (*): 10 біт!, 11 біт!, 16>>6! (справжні 16 біт, v >> 6). */
#define APRSPROBE_FMT_RUN_AUTO   "I2S авто nbits=%s бл.%lu"
#define APRSPROBE_FMT_RUN_MAN    "I2S %s бл.%lu"
#define APRSPROBE_BITS10         "10 біт!"
#define APRSPROBE_BITS11         "11 біт!"
#define APRSPROBE_BITS16         "16>>6!"
#define APRSPROBE_NO_WS          "I2S: немає такту WS"
#define APRSPROBE_BUSY           "Пауза: голос. підказка"
#define APRSPROBE_NO_DATA        "Немає даних > 1 с"
#define APRSPROBE_WAIT           "Чекаю дані..."

/* Сторінка «пакети» -- лічильники поточного варіанта. R7: кадри FCS ок / помилка / серії прапорців
 * в одному рядку; нижче -- по слотах nbits «nbits:ок/помилка» (до 4); рівень (RMS і пік після
 * зведення до 10 біт) і режекція; рядок 8 -- вердикт детектора (nbits) і число його перемикань. */
#define APRSPROBE_FMT_CNT        "ок %u  пом. %u  сер. %u"
#define APRSPROBE_LAST_NONE      "Правильних кадрів ще нема"
#define APRSPROBE_FMT_NB         "%u:%u/%u"
#define APRSPROBE_NB_NONE        "кадрів по nbits ще нема"
#define APRSPROBE_FMT_LEVEL      "RMS %u пік %u реж.%s"
#define APRSPROBE_NOTCH_S_AUTO   "авто"
#define APRSPROBE_NOTCH_S_OFF    "викл"
#define APRSPROBE_FMT_DET        "Детект. %s, перемик. %lu"

/* Сторінка «фон» -- розгортка 100..3900 Гц на поточному варіанті. */
#define APRSPROBE_FMT_RMS        "RMS %u  DC %d"
#define APRSPROBE_FMT_TOP1       "Топ-1 %u Гц  A=%u"
#define APRSPROBE_FMT_SHARE      "  частка %u %% RMS"
#define APRSPROBE_FMT_TOP2       "Топ-2 %u Гц  A=%u"
#define APRSPROBE_BG_WAIT        "Розгортка... (0,5 с)"
#define APRSPROBE_FMT_FS         "fs %lu (%lu с) втр. %lu"
#define APRSPROBE_FS_WAIT        "fs вимір (5 с), втр. %lu"
/* R7, сторінка «фон»: профіль детектора -- 15 цифр для j = 15..1: c[j]/10 (шістнадцяткова, F -- 150
 * і більше), де c[j] -- слів останнього блока з 160, у яких біт j != біт j-1. Сміття над nbits бітами
 * дає різкий пік (5-8) на j = nbits і нулі вище. R5: |s| >= 480 і пік (масштаб 10 біт, з GREEN). */
#define APRSPROBE_FMT_PROFILE    "c15-1 %s"
#define APRSPROBE_FMT_NEAR       "|s|>=480 %lu  пік %u"

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

/* R6/R7, сторінка «регістри»: регістри кодека -- рядками; старт I2S (T_start, виміряне T, рівень WS
 * одразу після); FRE (опитувань із прапорцем ЗА ОСТАННЮ СЕКУНДУ: прийом/передача) і стартів I2S;
 * події: шумодав (ШД) відкрився/закрився, біпи, голосові підказки (пк). */
#define APRSPROBE_FMT_START      "Старт T=%u вим.%u WS=%u"
#define APRSPROBE_FMT_FRE        "FRE/с %u/%u, стартів %lu"
#define APRSPROBE_FMT_EVENTS     "ШД +%lu/-%lu біп %lu пк %lu"

/* R7, сторінка «фаза»: T_start (мкс від фронту WS 0->1 до вмикання I2SE), виміряне, рівень WS одразу
 * після, nbits; HAL; скільки разів на цьому T вийшов кожен nbits; SPI3 (приймач) і I2S3ext. «ош» --
 * накопичені за секунду UDR|OVR|FRE; CFG/PR/CR2 -- I2SCFGR/I2SPR/CR2. */
#define APRSPROBE_FMT_PH_T       "T_start %u мкс, вим. %u"
#define APRSPROBE_FMT_PH_WS      "WS після %u, nbits %s"
#define APRSPROBE_FMT_PH_HAL     "HAL %u мкс, стартів %lu"
#define APRSPROBE_FMT_PH_CNT     "T:10=%u 11=%u 16=%u ін=%u"
#define APRSPROBE_FMT_PH_S3      "S3 CFG %04X PR %04X CR2 %02X"
#define APRSPROBE_FMT_PH_S3SR    "S3 SR %04X ош %03X"
#define APRSPROBE_FMT_PH_EXT     "ext CFG %04X SR %04X ош%03X"
#define APRSPROBE_PH_WAIT        "Чекаю секунду..."
#define APRSPROBE_FOOTER_PH1     "<> T-/+2 0 пуск 5 скан"
#define APRSPROBE_FOOTER_PH2     "^v стор. RED вихід"

/* R7, сторінка «скан»: T = 0, 2 ... 124 мкс по 6 перезапусків. Символ на T: цифра k = 16 - nbits
 * (6 -- nbits 10, 5 -- nbits 11), F -- справжні 16, м -- різні nbits, ? -- вердикту не було,
 * . -- ще не міряли. */
#define APRSPROBE_SYM_MIX        "м"
#define APRSPROBE_FMT_SC_RUN     "Скан T=%u мкс, прогін %u/%u"
#define APRSPROBE_SC_IDLE        "5 - розгортка T_start"
#define APRSPROBE_SC_DONE        "Скан завершено"
#define APRSPROBE_FMT_SC_ROW     "%3u %s"
#define APRSPROBE_SC_LEGEND      "6=10б 5=11б F=16 м=різн ?"
#define APRSPROBE_FMT_SC_BEST    "Стаб.: T %u..%u nbits %u"
#define APRSPROBE_SC_NO_BEST     "Стійкого ряду T немає"
#define APRSPROBE_FOOTER_SC1     "5 стоп/пуск ^v стор."
#define APRSPROBE_FOOTER_SC2     "GREEN скин. RED вихід"

/* Значення регістрів на вході (їх і відновлюємо). «?» -- прочитати не вдалося, відновлюються
 * штатні FM-значення. */
#define APRSPROBE_FMT_SAVED      "Було E0=%02X 36=%02X 10=%02X"
#define APRSPROBE_FMT_SAVED_BAD  "Було? E0=%02X 36=%02X 10=%02X"

#define APRSPROBE_FOOTER1        "^v стор. GREEN скин. *біт"
#define APRSPROBE_FOOTER2        "<> варіант #реж RED вихід"

#endif /* USER_INTERFACE_LANGUAGES_APRSPROBE_UA_H_ */
