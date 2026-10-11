/*
 * menuAprsMode.h -- екран «Режиму APRS» (R10): сторінки «Монітор», «Станції», «Налаштування» і редактор полів.
 * Логіка режиму (вхід/вихід, налаштування, маяк) -- functions/aprs_mode.c. Як і «APRS станції» (R8), це не
 * окреме меню (новий ID меню -- це +20 Б main RAM), а режим усередині «Опцій рації»: menuRadioOptions.c передає
 * сюди тіки й події, поки aprsModeIsActive().
 */
#ifndef _OPENGD77_MENU_APRS_MODE_H_
#define _OPENGD77_MENU_APRS_MODE_H_

#include "functions/aprs_mode.h"

#if defined(APRS_RX)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

/* Увійти в режим (aprsModeEnter()) і намалювати «Монітор». false -- зараз не можна (показано сповіщення). */
bool menuAprsModeEnter(void);
/* Кожен тік «Опцій рації», поки режим активний. false -- користувач вийшов (RED на «Моніторі»): режим уже
 * вимкнено, треба перемалювати список опцій. */
bool menuAprsModeTick(uiEvent_t *ev);
#endif

#endif /* _OPENGD77_MENU_APRS_MODE_H_ */
