/*
 * menuAprsSettings.h -- «Налаштування» меню «APRS» (R17 Г1). Це не окреме меню (новий ID меню -- це +20 Б main RAM), а екран усередині меню «APRS»:
 * menuAprsHub.c передає сюди тіки й події, поки aprsModeCfgSessionActive().
 */
#ifndef _OPENGD77_MENU_APRS_SETTINGS_H_
#define _OPENGD77_MENU_APRS_SETTINGS_H_

#include "functions/aprs_rx_cfg.h"   /* ENABLE_APRS_RX / APRS_RX (інакше діагностична збірка не бачить екран) */
#include "functions/aprs_mode.h"
#include "functions/aprs.h"   /* aprsSmartBeaconingSettings_t */

#if defined(APRS_RX)
#include "user_interface/menuSystem.h"   /* uiEvent_t */

/* Відкрити сесію налаштувань (вимикає «Слухати APRS») і намалювати список груп. false -- зараз не можна (передача); користувачу показано сповіщення. */
bool menuAprsSettingsEnter(void);
/* R21 З5: пресет розумного маяка 0..6 зі стокової таблиці (menuAPRSOptions.c); name -- його назва; NULL -- номер поза таблицею. */
#if defined(APRS_R21_PRESETS)
const aprsSmartBeaconingSettings_t *aprsSmartPresetGet(unsigned i, const char **name);
#endif
/* Кожен тік меню «APRS», поки відкрито «Налаштування». false -- користувач вийшов (RED зі списку груп): сесію закрито, треба перемалювати меню. */
bool menuAprsSettingsTick(uiEvent_t *ev);

#if defined(ENABLE_APRS_RX_PROBE)
/* R20 Ж2: діагностичний екран «Таблиця символів» -- 8 сторінок по 24 піктограми (6x4); малює лише сторінку, стану не має. */
#define MENU_APRS_SYMTAB_PAGES     8U
#define MENU_APRS_SYMTAB_PER_PAGE  24U
void menuAprsSymTableDraw(unsigned page);
#endif
#endif

#endif /* _OPENGD77_MENU_APRS_SETTINGS_H_ */
