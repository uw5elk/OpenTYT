/*
 * menuTaDiag.h -- R88: екран «TA diag» (діагностика сирого Talker Alias і GPS-блока LC). Не окреме меню (нового ID меню нема),
 * а режим усередині «Опцій рації» (так само, як «Гучн. проба» R77A): останній пункт, вправо -- відкрити; «Опції рації» передає
 * сюди тіки й події, поки menuTaDiagIsOpen(). Лише збірка з ENABLE_TA_DIAG.
 */
#ifndef _OPENGD77_MENU_TA_DIAG_H_
#define _OPENGD77_MENU_TA_DIAG_H_

#include "functions/ta_diag.h"

#if defined(TA_DIAG)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

#define TADIAG_MENU_NAME   "TA diag"
#define TADIAG_MENU_ENTER  ">>"

void menuTaDiagEnter(void);
bool menuTaDiagIsOpen(void);
void menuTaDiagClose(void);
/* Кожен тік «Опцій рації», поки екран відкритий. false -- вийшли (треба перемалювати список). */
bool menuTaDiagTick(uiEvent_t *ev);
#endif

#endif /* _OPENGD77_MENU_TA_DIAG_H_ */
