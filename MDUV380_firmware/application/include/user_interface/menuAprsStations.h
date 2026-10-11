/*
 * menuAprsStations.h -- екран «APRS станції» (R8): список станцій, прийнятих фоновим приймачем APRS
 * (functions/aprs_rx.c), картка станції і діагностична сторінка приймача. Як і «APRS проба» (R2) --
 * не окреме меню (новий ID меню -- це +20 Б main RAM у menuFunctions[]/menuDataGlobal), а режим усередині
 * «Опцій рації»: menuRadioOptions.c передає сюди тіки й події, поки aprsRxUi()->on.
 */
#ifndef _OPENGD77_MENU_APRS_STATIONS_H_
#define _OPENGD77_MENU_APRS_STATIONS_H_

#include "functions/aprs_rx.h"

#if defined(APRS_RX)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

/* Відкрити екран (список). */
void menuAprsStationsEnter(void);
/* Закрити (з виходу з «Опцій рації», push іншого меню). Безпечно, якщо не відкрито. */
void menuAprsStationsClose(void);
/* Кожен тік «Опцій рації», поки екран відкрито. false -- користувач вийшов (RED зі списку), екран уже
 * закрито, треба перемалювати список опцій. */
bool menuAprsStationsTick(uiEvent_t *ev);
#endif

#endif /* _OPENGD77_MENU_APRS_STATIONS_H_ */
