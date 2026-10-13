/*
 * menuAprsStations.h -- екран «APRS станції» (R8): список станцій, прийнятих фоновим приймачем APRS
 * (functions/aprs_rx.c), картка станції і діагностична сторінка приймача. Як і «APRS проба» (R2) --
 * не окреме меню (новий ID меню -- це +20 Б main RAM у menuFunctions[]/menuDataGlobal), а режим усередині
 * меню «APRS»: menuAprsHub.c передає сюди тіки й події, поки aprsRxUi()->on.
 */
#ifndef _OPENGD77_MENU_APRS_STATIONS_H_
#define _OPENGD77_MENU_APRS_STATIONS_H_

#include "functions/aprs_rx.h"

#if defined(APRS_RX)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

/* Відкрити екран (список). */
void menuAprsStationsEnter(void);
/* R15: пункти меню «APRS»: R16: «Пакети» -- список журналу останніх 8 прийнятих кадрів і повний текст виділеного (RED -- вихід); «Останній маяк» --
 * вікно маяка за збереженими даними (порожньо -- сповіщення «Маяків ще не було»). */
void menuAprsPacketEnter(void);
void menuAprsBeaconShow(void);
/* Закрити (з виходу з меню «APRS», push іншого меню). Безпечно, якщо не відкрито. */
void menuAprsStationsClose(void);
/* Кожен тік меню «APRS», поки екран відкрито. false -- користувач вийшов (RED зі списку), екран уже
 * закрито, треба перемалювати список опцій. */
bool menuAprsStationsTick(uiEvent_t *ev);

/* R19 Е1: спільний список ПУНКТІВ у стоковому вигляді (menuDisplayEntry(), FONT_SIZE_3 8x16, виділення смугою). APRS_LIST_ROWS рядків з y = 16 (під заголовком),
 * внизу лишається рядок підказки FONT_SIZE_1 (y = 116). Вікно йде за виділеним (стан не зберігається: вибір -- у станах екранів, тож вхід/вихід його не скидає).
 * Рядок -- до APRS_LIST_COLS символів (текст починається з x = 8, смуга закінчується на x = 156: 18 повних клітинок 8 px). fn() заповнює рядок і *opt: позиція,
 * з якої текст малюється кольором значення (0 -- одним кольором). */
#define APRS_LIST_ROWS  6
#define APRS_LIST_COLS  18
typedef void (*aprsListItemFn_t)(int index, char *buf, size_t cap, int *opt);
void menuAprsListDraw(int count, int sel, aprsListItemFn_t fn);

/* Короткий тип пакета і вік («45с», «12хв») -- для рядків «Монітора» (cp1251 з aprsrx_ua.h). */
const char *menuAprsStationsTypeStr(uint8_t type);
void menuAprsStationsAgeStr(char *b, size_t n, uint32_t sec);
#endif

#endif /* _OPENGD77_MENU_APRS_STATIONS_H_ */
