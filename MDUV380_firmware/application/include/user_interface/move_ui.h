/*
 * move_ui.h -- R66C: рядки дій «Вгору / Вниз» (переміщення). Українська збірка -- languages/move_ua.h (cp1251), решта -- англійські.
 */
#ifndef USER_INTERFACE_MOVE_UI_H_
#define USER_INTERFACE_MOVE_UI_H_

#if defined(LANGUAGE_BUILD_UKRAINIAN)
#include "user_interface/languages/move_ua.h"
#else
#define MV_ACT_UP        "Move up"
#define MV_ACT_DOWN      "Move down"
#define MV_ACT_REMOVE    "Remove"
#define MV_MSG_FIRST     "Already\nfirst"
#define MV_MSG_LAST      "Already\nlast"
#define MV_MSG_EDGE      "Sector edge:\nuse CPS"
#define MV_MSG_SAVE_ERR  "Write\nerror"
#endif

#endif /* USER_INTERFACE_MOVE_UI_H_ */
