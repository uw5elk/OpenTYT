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
/* R15: пункт меню «APRS» «Останній пакет» -- екран із сирим текстом останнього прийнятого кадру (RED -- вихід). */
void menuAprsPacketEnter(void);
/* Закрити (з виходу з меню «APRS», push іншого меню). Безпечно, якщо не відкрито. */
void menuAprsStationsClose(void);
/* Кожен тік меню «APRS», поки екран відкрито. false -- користувач вийшов (RED зі списку), екран уже
 * закрито, треба перемалювати список опцій. */
bool menuAprsStationsTick(uiEvent_t *ev);

/* R10: вбудована сторінка «Станції» «Режиму APRS» (menuAprsMode.c). Стан -- той самий aprsRxUi() (view LIST/CARD,
 * sel, scroll, cardCall). Draw малює тіло (рядки 0..10) БЕЗ заголовка й без displayClearBuf()/displayRender().
 * Key повертає: 0 -- нічого, 1 -- перемалювати, -1 -- вихід зі списку (RED) на попередню сторінку. */
void menuAprsStationsDrawEmbedded(void);
int  menuAprsStationsKeyEmbedded(uiEvent_t *ev);
/* Короткий тип пакета і вік («45с», «12хв») -- для рядків «Монітора» (cp1251 з aprsrx_ua.h). */
const char *menuAprsStationsTypeStr(uint8_t type);
void menuAprsStationsAgeStr(char *b, size_t n, uint32_t sec);
#endif

#endif /* _OPENGD77_MENU_APRS_STATIONS_H_ */
