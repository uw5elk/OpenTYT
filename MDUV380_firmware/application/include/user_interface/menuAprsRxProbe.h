/*
 * menuAprsRxProbe.h -- екран «APRS проба» (R2). Не окреме меню (новий ID меню -- це +20 Б
 * main RAM у menuFunctions[]/menuDataGlobal), а режим усередині меню «APRS»:
 * menuAprsHub.c передає сюди тіки й події, поки aprsRxProbeIsOn().
 */
#ifndef _OPENGD77_MENU_APRS_RX_PROBE_H_
#define _OPENGD77_MENU_APRS_RX_PROBE_H_

#include "functions/aprs_rx_probe.h"

#if defined(APRS_RX_PROBE)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

/* Відкрити екран (і пробу). */
void menuAprsRxProbeEnter(void);
/* Кожен тік меню «APRS», поки проба відкрита. false -- користувач вийшов (RED), проба вже
 * закрита, треба перемалювати список. */
bool menuAprsRxProbeTick(uiEvent_t *ev);
#endif

#endif /* _OPENGD77_MENU_APRS_RX_PROBE_H_ */
