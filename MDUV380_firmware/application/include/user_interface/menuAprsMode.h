/*
 * menuAprsMode.h -- екран «Режиму APRS» (R10): сторінки «Монітор», «Станції», «Повідомлення» (R11), «Налаштування» і редактор полів.
 * Логіка режиму (вхід/вихід, налаштування, маяк) -- functions/aprs_mode.c. Як і «APRS станції» (R8), це не
 * окреме меню (новий ID меню -- це +20 Б main RAM), а режим усередині меню «APRS»: menuAprsHub.c передає
 * сюди тіки й події, поки aprsModeIsActive().
 */
#ifndef _OPENGD77_MENU_APRS_MODE_H_
#define _OPENGD77_MENU_APRS_MODE_H_

#include "functions/aprs_mode.h"

#if defined(APRS_RX)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

/* Увійти в режим (aprsModeEnter()) і намалювати «Монітор». false -- зараз не можна (показано сповіщення). */
bool menuAprsModeEnter(void);
/* R11: пункт хабу «Повідомлення APRS» -- увійти в режим і відкрити сторінку «Повідомлення». false -- зараз не можна. */
bool menuAprsModeEnterMessages(void);
/* R13: екран «Повідом. APRS» БЕЗ «Режиму APRS» (див. aprsModeMsgSessionOpen()). true -- відкрито. */
bool menuAprsMsgEnter(void);
/* R11: «Відповісти» з картки станції: за потреби увійти в режим, відкрити набір повідомлення цій станції (адресат уже заданий).
 * false -- не вдалося (режим недоступний чи позивний станції не годиться за адресата); користувачу показано сповіщення. */
bool menuAprsModeReplyTo(const char *call);
/* Кожен тік меню «APRS», поки режим активний. false -- користувач вийшов (RED на «Моніторі»): режим уже
 * вимкнено, треба перемалювати список опцій. */
bool menuAprsModeTick(uiEvent_t *ev);
#endif

#endif /* _OPENGD77_MENU_APRS_MODE_H_ */
