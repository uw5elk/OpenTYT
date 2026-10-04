/*
 * Рядки екрана SMS-повідомлень українською.
 *
 * ВАЖЛИВО: цей файл, як і ukrainian.h, має кодування cp1251 -- саме так шрифт
 * HX8353E_charset_UA.h трактує коди 192-255. Не зберігати в UTF-8.
 *
 * Чому окремим файлом, а не полями у stringsTable_t: SMS -- функція саме цього
 * форку, а таблицю рядків читає ще й мовний файл, який пише CPS. Три десятки
 * нових полів зламали б ту сумісність і з'їли б близько кілобайта флеша в КОЖНІЙ
 * збірці, зокрема неукраїнській. Тут перемикання відбувається на етапі компіляції.
 */
#ifndef USER_INTERFACE_LANGUAGES_MESSAGES_UA_H_
#define USER_INTERFACE_LANGUAGES_MESSAGES_UA_H_

#define MSGS_TITLE               "Повідомлення"
#define MSGS_INBOX_FMT           "Вхідні (%d)"
#define MSGS_SENT_FMT            "Надіслані (%d)"
#define MSGS_NEW                 "Нове повідомлення"
#define MSGS_TITLE_SENT          "Надіслані"
#define MSGS_TITLE_INBOX         "Вхідні"
#define MSGS_EMPTY               "(порожньо)"
#define MSGS_HINT_BACK           "RED:назад"
#define MSGS_DELETE_ALL          "[Видалити все]"
#define MSGS_TO                  "Кому"
#define MSGS_FROM                "Від"
#define MSGS_HINT_SENT_ITEM      "SK2+GRN:вид GRN:ще раз"
#define MSGS_HINT_INBOX_ITEM     "SK2+GRN:вид GRN:відпов"
#define MSGS_TITLE_NEW           "Нове повідомлення"
#define MSGS_CHARS_FMT           "%d/%d симв."
#define MSGS_HINT_PRESET         "U:шаблон  L:стерти"
#define MSGS_HINT_TO_CANCEL      "GRN:кому  RED:відміна"
#define MSGS_TITLE_RCPT          "Одержувач"
#define MSGS_TO_FMT              "Кому: %s"
#define MSGS_TYPE_FMT            "Тип: %s"
#define MSGS_GROUP               "Група"
#define MSGS_PRIVATE             "Приватний"
#define MSGS_HINT_ID             "0-9:id  L:стерти"
#define MSGS_HINT_GRP_PRIV       "U/D:група/приват"
#define MSGS_HINT_CONTACTS       "SK1:контакти"
#define MSGS_HINT_SEND_BACK      "GRN:надіслати  RED:назад"
#define MSGS_TITLE_PICK_TG       "Вибір TG контакту"
#define MSGS_TITLE_PICK_PC       "Вибір PC контакту"
#define MSGS_NO_CONTACTS         "(немає контактів)"
#define MSGS_SENT_OK             "Надіслано"
#define MSGS_KEYED_TX            "(вихід в ефір)"
#define MSGS_SEND_FAILED         "Не надіслано"
#define MSGS_ERR_GENERIC         "помилка"
#define MSGS_ERR_TX_BUSY         "TX зайнятий"
#define MSGS_ERR_BAD_TEXT        "хибний текст"
#define MSGS_ERR_TOO_LONG        "задовгий текст"
#define MSGS_FAIL_FMT            "%s (%d)"
#define MSGS_HINT_ANY_KEY        "будь-яка клавіша: назад"
#define MSGS_MONITOR_FMT         "Монітор: %s"
#define MSGS_MON_ON              "увімк"
#define MSGS_MON_OFF             "вимк"
/* Банер вхідного: скільки ще НЕпрочитаних, крім показаного (окремим кольором). */
#define MSGS_MORE_UNREAD_FMT     "ще %d непрочит."
#define MSGS_FOREIGN             " (не вам)"

/* Режим TX SMS (2026-09-29): рядок у головному меню «Повідомлення». */
#define MSGS_TX_MODE_FMT         "TX: %s"
#define MSGS_TX_MODE_UNCONF      "Без підтв."
#define MSGS_TX_MODE_R12         "Підтв. 1/2"
#define MSGS_TX_MODE_R34         "Підтв. 3/4"

/* Екран «Діагностика» (2026-09-30): лічильники ланцюга квитанції. FONT_SIZE_1 -- до 26
 * символів у рядку з числами. Розшифровка -- TESTING.md, блок M. */
#define MSGS_DIAG                "Діагностика"
#define MSGS_DG_ACK1_FMT         "Квит RX: бач %u черг %u"
#define MSGS_DG_ACK2_FMT         "  ефір %u простр %u"
#define MSGS_DG_ACK3_FMT         "  пауза %u мс"
#define MSGS_DG_DATA1_FMT        "Дані: відк %u старт %u"
#define MSGS_DG_DATA2_FMT        "  тайм %u без старт %u"
#define MSGS_DG_CONF_FMT         "Наші CONF: %u"
#define MSGS_DG_RESP_FMT         "Відп %u нам %u наші %u"
#define MSGS_DG_HDR_FMT          "Заг6 HW %u SW %u пог %u"
#define MSGS_DG_FAST_FMT         "%cШв. кінець: %s"
#define MSGS_DG_HINT             "DN:стор.2 дов.GRN:скид RED"

/* Екран «Діагностика», сторінка 2 (fix3, 2026-10-02): лічильники ISR до фільтрів і
 * перемикачі (GREEN на виділеному рядку). '%c' -- маркер виділення ('>' або пробіл). */
#define MSGS_DIAG2               "Діагностика 2"
#define MSGS_DG_ISR_FMT          "ISR: т6 %u т8 %u"
#define MSGS_DG_FILT_FMT         "Фільтр RX: т6 %u т8 %u"
#define MSGS_DG_REAL_FMT         "Квит факт: %u мс"
#define MSGS_DG_BYP_FMT          "%cRX обхід: %s"
#define MSGS_DG_PRE_FMT          "%cКвит. преамб: %u"
#define MSGS_DG_TERM_FMT         "%cКвит. терм.: %s"
#define MSGS_DG_YES              "так"
#define MSGS_DG_NO               "ні"
#define MSGS_DG_HINT2            "U/D GRN:змін дов:скид RED"

/* ui1/fix4 (2026-10-04): «Діагностика» стор. 2 -- етапи затримки квитанції (тиша->черга +
 * черга->ключування + ключування->старт TX + старт->перший burst) і перемикач цільової паузи. */
#define MSGS_DG_STG_FMT          "Етапи: %u+%u+%u+%u"
#define MSGS_DG_PAUSE_FMT        "%cКвит. пауза: %u мс"

/* diag5 (2026-10-04): «Діагностика» стор. 3 -- де гине вхідний PDU (TESTING.md, блок R).
 * PDU: зібрано з валідним CRC32 / блоків рівно як у заголовку, а CRC32 не зійшовся.
 * Блок: без заголовка / відкинуто, бо попередній PDU ще не забрано / переповнення / зайві.
 * Цикл: головний цикл відкинув -- не нам / зіпсований. Забір: найдовше «готовий -> забрано». */
#define MSGS_DIAG3               "Діагностика 3"
#define MSGS_DG3_PDU_FMT         "PDU: ок %u CRC пог %u"
#define MSGS_DG3_BLK1_FMT        "Блок: безЗаг %u зайн %u"
#define MSGS_DG3_BLK2_FMT        "  переп %u зайві %u"
#define MSGS_DG3_TICK_FMT        "Цикл: не нам %u зіпс %u"
#define MSGS_DG3_PICK_FMT        "Забір макс: %u мс"
#define MSGS_DG3_HINT            "UP:стор.2 дов.GRN:скид RED"

#endif /* USER_INTERFACE_LANGUAGES_MESSAGES_UA_H_ */
