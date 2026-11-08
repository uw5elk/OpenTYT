/*
 * roaming_gate.h -- R74: стоковий «Roaming» (відстань до каналів зони за GPS, nonVolatileSettings.roaming) на раціях БЕЗ GPS.
 *
 * У форку для рацій без GPS-приймача (HAS_GPS && FORK_NO_GPS_MENU, applicationMain.h) пункт «Roaming» у швидкому меню каналу ховається (uiChannelMode.c; номери решти
 * пунктів швидкого меню НЕ зсуваються -- швидкі клавіші зберігають номер пункту), а будь-яке збережене значення, відмінне від ROAMING_OFF (рація з нього прошивалась),
 * на логіку НЕ впливає: усі місця, де значення ЧИТАЛОСЯ для роботи, беруть ROAMING_EFFECTIVE(). Саме значення в nonVolatileSettings і розкладка структури не змінюються.
 * Наш роумінг за списками (ENABLE_ROAM_RETRY) цього не стосується. Повернути стоковий пункт: прибрати FORK_NO_GPS_MENU (applicationMain.h).
 */
#ifndef FUNCTIONS_ROAMING_GATE_H_
#define FUNCTIONS_ROAMING_GATE_H_

#include "applicationMain.h"
#include "functions/settings.h"

#if defined(HAS_GPS) && defined(FORK_NO_GPS_MENU)
#define ROAMING_STOCK_HIDDEN 1
#define ROAMING_EFFECTIVE() (ROAMING_OFF)
#else
#define ROAMING_EFFECTIVE() (nonVolatileSettings.roaming)
#endif

#endif /* FUNCTIONS_ROAMING_GATE_H_ */
