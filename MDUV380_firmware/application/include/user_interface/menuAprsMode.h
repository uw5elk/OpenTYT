/*
 * menuAprsMode.h -- екран «Повідом. APRS» (R11, R13, R15). R17 Г1: «Режим APRS» зі сторінками прибрано; налаштування -- menuAprsSettings.h.
 * Як і «APRS станції» (R8), це не окреме меню (новий ID меню -- це +20 Б main RAM), а екран усередині меню «APRS»: menuAprsHub.c передає
 * сюди тіки й події, поки відкрито «Повідом. APRS» (aprsModeMsgSessionActive()).
 */
#ifndef _OPENGD77_MENU_APRS_MODE_H_
#define _OPENGD77_MENU_APRS_MODE_H_

#include "functions/aprs_mode.h"

#if defined(APRS_RX)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

/* Екран «Повідом. APRS» (див. aprsModeMsgSessionOpen()): працює з увімкненим «Слухати APRS» і без нього. true -- відкрито. */
bool menuAprsMsgEnter(void);
/* «Відповісти» з картки станції: відкрити набір повідомлення цій станції (адресат уже заданий).
 * false -- не вдалося (позивний станції не годиться за адресата); користувачу показано сповіщення. */
bool menuAprsModeReplyTo(const char *call);
/* Кожен тік меню «APRS», поки відкрито «Повідом. APRS». false -- користувач вийшов (RED з першого екрана): сесію закрито, треба перемалювати меню. */
bool menuAprsModeTick(uiEvent_t *ev);
#endif

#endif /* _OPENGD77_MENU_APRS_MODE_H_ */
