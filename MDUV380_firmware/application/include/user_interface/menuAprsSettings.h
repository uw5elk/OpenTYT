/*
 * menuAprsSettings.h -- «Налаштування» меню «APRS» (R17 Г1). Це не окреме меню (новий ID меню -- це +20 Б main RAM), а екран усередині меню «APRS»:
 * menuAprsHub.c передає сюди тіки й події, поки aprsModeCfgSessionActive().
 */
#ifndef _OPENGD77_MENU_APRS_SETTINGS_H_
#define _OPENGD77_MENU_APRS_SETTINGS_H_

#include "functions/aprs_rx_cfg.h"   /* ENABLE_APRS_RX / APRS_RX (інакше діагностична збірка не бачить екран) */
#include "functions/aprs_mode.h"

#if defined(APRS_RX)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

/* Відкрити сесію налаштувань (вимикає «Слухати APRS») і намалювати список груп. false -- зараз не можна (передача); користувачу показано сповіщення. */
bool menuAprsSettingsEnter(void);
/* Кожен тік меню «APRS», поки відкрито «Налаштування». false -- користувач вийшов (RED зі списку груп): сесію закрито, треба перемалювати меню. */
bool menuAprsSettingsTick(uiEvent_t *ev);
#endif

#endif /* _OPENGD77_MENU_APRS_SETTINGS_H_ */
