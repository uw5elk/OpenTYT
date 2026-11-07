/*
 * rxgroup_ui.h -- R65B: чи є екран «Списки прийому» (редактор TG-списків з рації) в цій збірці. Потребує RXGROUP_EDIT_ENABLED (codeplug.h: ENABLE_RXGROUP_EDIT на тлі
 * CODEPLUG_MENU_ENABLED) і ті самі умови, що спільний редактор назви (uiNameEditor.h): українська збірка з multitap. Умова виписана через прапорці, а не через UI_NAME_EDITOR,
 * бо menuSystem.h (потрібен для uiEvent_t в uiNameEditor.h) сам включає цей файл для переліку меню.
 */
#ifndef USER_INTERFACE_RXGROUP_UI_H_
#define USER_INTERFACE_RXGROUP_UI_H_

#include "functions/aprs_rx_cfg.h"
#include "functions/codeplug.h"

#if defined(RXGROUP_EDIT_ENABLED) && defined(LANGUAGE_BUILD_UKRAINIAN) && ((defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)) || defined(APRS_RX))
#define RXGROUP_UI_ENABLED 1
#include "user_interface/languages/rxgroup_ua.h"
#endif

#endif /* USER_INTERFACE_RXGROUP_UI_H_ */
