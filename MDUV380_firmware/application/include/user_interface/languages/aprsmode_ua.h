/*
 * aprsmode_ua.h -- українські рядки «Режиму APRS» (R10: aprs_mode.c, aprs_mode_cfg.c, menuAprsMode.c).
 *
 * УВАГА: файл у кодуванні cp1251, як ukrainian.h/aprsrx_ua.h -- шрифт рації HX8353E_charset_UA.h має
 * кирилицю в позиціях 192-255. НЕ зберігати в UTF-8.
 *
 * Окремі макроси, а не поля stringsTable_t (структура мов спільна з CPS; режим існує лише в українській
 * збірці з ENABLE_APRS_RX -- за патерном aprsrx_ua.h). Англійської гілки тому немає: без LANGUAGE_BUILD_UKRAINIAN
 * режим не збирається взагалі (aprs_rx_cfg.h).
 *
 * Ширина: рядок екрана (FONT_SIZE_1) -- 26 символів; заголовок -- 16; рядок пункту меню -- 16.
 * Для шаблонів з %s/%u/%lu перевірка в tools/check_menu_widths.py (розділ 7) підставляє НАЙГІРШЕ значення.
 */
#ifndef USER_INTERFACE_LANGUAGES_APRSMODE_UA_H_
#define USER_INTERFACE_LANGUAGES_APRSMODE_UA_H_

/* ---- пункт «Опцій рації» і заголовок ---- */
#define APRSM_MENU            "Режим APRS"
#define APRSM_TITLE_FMT       "Режим APRS %u/%u"
#define APRSM_NOT_NOW         "Зараз не можна"

/* ---- символи (первинна таблиця): назви найуживаніших ---- */
#define APRSM_SYM_CAR         "авто"
#define APRSM_SYM_HUMAN       "людина"
#define APRSM_SYM_HOUSE       "дім"
#define APRSM_SYM_BIKE        "велосипед"
#define APRSM_SYM_MOTO        "мотоцикл"
#define APRSM_SYM_TRUCK       "вантажівка"
#define APRSM_SYM_VAN         "фургон"
#define APRSM_SYM_DIGI        "діджі"
#define APRSM_SYM_REPEATER    "ретранслятор"
#define APRSM_SYM_YACHT       "яхта"

/* ---- помилки маяка (сповіщення 1,5 с; рядок сповіщення -- до 16 символів) ---- */
#define APRSM_ERR_NOCALL      "Нема позивного"
#define APRSM_ERR_NOPOS       "Нема позиції"
#define APRSM_ERR_INHIBIT     "TX заборонено"
#define APRSM_ERR_BAND        "Поза діапазоном"
#define APRSM_ERR_BUSYCH      "Частота зайнята"
#define APRSM_ERR_FAILED      "Маяк не вдався"
#define APRSM_ERR_TOOBIG      "Кадр завеликий"

/* ---- сторінка «Монітор» ---- */
#define APRSM_M_NORX          "Прийом каналу вимкнено"
#define APRSM_M_FREQ          "Частота: %s МГц"
#define APRSM_M_STATE         "Стан: %s"
#define APRSM_M_ST_LISTEN     "Слухаю"
#define APRSM_M_ST_START      "Запуск..."
#define APRSM_M_ST_TX         "ПЕРЕДАЧА МАЯКА"
#define APRSM_M_ST_WAIT       "Чекаю вільну частоту"
#define APRSM_M_ST_SENT       "Маяк передано"
#define APRSM_M_RSSI          "Сигнал: %d дБм %c"
#define APRSM_M_FRAMES        "Кадри: ок %lu пом %lu"
#define APRSM_M_FORMAT        "Біт: %s  Станцій: %u/%u"
#define APRSM_M_LAST          "Остан: %.9s>%.7s"
#define APRSM_M_NOPKT         "Пакетів ще нема"
#define APRSM_M_BEACONS       "Маяків %lu, %s тому"
#define APRSM_M_BEACONS0      "Маяків ще не було"
#define APRSM_M_NEXT          "Наст. маяк: %u:%02u"
#define APRSM_M_MANUAL        "Маяк вручну: GREEN або PTT"
#define APRSM_M_HINT          "<>:стор GREEN:маяк RED:вих"

/* ---- сторінка «Налаштування» ---- */
#define APRSM_ST_HINT         "GREEN:картка <>:стор"
#define APRSM_S_HINT          "<>:змін GREEN:ред *:стор"
#define APRSM_L_FREQ          "Частота"
#define APRSM_L_CALL          "Позивний"
#define APRSM_L_SSID          "SSID"
#define APRSM_L_PATH1         "Шлях 1"
#define APRSM_L_PATH2         "Шлях 2"
#define APRSM_L_ICON_TABLE    "Табл.сим."
#define APRSM_L_ICON_CODE     "Код сим."
#define APRSM_L_COMMENT       "Коментар"
#define APRSM_L_LAT           "Широта"
#define APRSM_L_LON           "Довгота"
#define APRSM_L_AMB           "Неточн."
#define APRSM_L_INTERVAL      "Маяк"
#define APRSM_L_SQL           "Шумодав"
#define APRSM_L_RESET         "Скинути"
#define APRSM_V_FREQ          "%s МГц"
#define APRSM_V_NONE          "нема"
#define APRSM_V_EMPTY         "-"
#define APRSM_V_TBL_PRI       "/ основна"
#define APRSM_V_TBL_SEC       "\\ додаткова"
#define APRSM_V_INT_OFF       "вручну"
#define APRSM_V_INT_FMT       "кожні %uхв"
#define APRSM_V_SQL_DEF       "типовий"
#define APRSM_V_SQL_FMT       "%u%%"
#define APRSM_V_RESET         "GREEN"
#define APRSM_V_RESET_ASK     "GREEN ще раз!"
#define APRSM_V_PATH_FMT      "%s-%u"
#define APRSM_V_CALL_FMT      "%s"

/* ---- редактор поля ---- */
#define APRSM_E_HINT1         "<:стерти #:режим набору"
#define APRSM_E_HINT_TEXT     "GREEN:ОК RED:скасувати"
#define APRSM_E_HINT_NUM      "GREEN:ОК RED:скас. *:."
#define APRSM_E_HINT_COORD    "GREEN:ОК RED:скас. *:. #:-"
#define APRSM_E_MODE          "Режим: %s"
#define APRSM_E_ERR           "Невірне значення"
#define APRSM_E_RANGE_FREQ    "136-174 або 400-480 МГц"
#define APRSM_E_RANGE_LAT     "від -90 до 90"
#define APRSM_E_RANGE_LON     "від -180 до 180"
#define APRSM_E_NOW           "Зараз: %s"
#define APRSM_E_HINT_BS       "<:стерти"
#define APRSM_E_EMPTY_CANCEL  "Порожньо = без змін"
#define APRSM_E_FMT_CALL      "A-Z, 0-9, до 6 символів"
#define APRSM_E_FMT_PATH      "Порожньо = без шляху"
#define APRSM_E_FMT_COMMENT   "До 24 символів"

#endif /* USER_INTERFACE_LANGUAGES_APRSMODE_UA_H_ */
