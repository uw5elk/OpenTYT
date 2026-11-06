/*
 * roam_ui.h -- R59/R60: рядки «Роумінгу» (меню, сповіщення, індикатори) -- українські з languages/roam_ua.h або англійські.
 * Не через stringsTable_t (див. шапку roam_ua.h). Лише з ENABLE_ROAM_RETRY.
 */
#ifndef USER_INTERFACE_ROAM_UI_H_
#define USER_INTERFACE_ROAM_UI_H_

#if defined(ENABLE_ROAM_RETRY)
#if defined(LANGUAGE_BUILD_UKRAINIAN)
#include "user_interface/languages/roam_ua.h"
#else
#define ROAM_MENU_NAME        "Roaming"
#define ROAM_ROW_AUTO_FMT     "Auto-hop:%s"
#define ROAM_ROW_HOPS_FMT     "Max hops:%u"
#define ROAM_ROW_CHLIST_FMT   "Ch list:%s%s"
#define ROAM_ROW_LISTS_S      "Lists"
#define ROAM_ON_S             "On"
#define ROAM_OFF_S            "Off"
#define ROAM_DET_LABEL        "Roam list"
#define ROAM_PICK_TITLE       "Roaming lists"
#define ROAM_PICK_ROW_FMT     "List %u"
#define ROAM_MEM_TITLE_FMT    "List %u (%u)"
#define ROAM_ADD_ROW          "+ Add channel..."
#define ROAM_ADD_TITLE_FMT    "To list %u"
#define ROAM_CFM_REMOVE_TITLE "Remove channel?"
#define ROAM_CFM_FROM_FMT     "from list %u"
#define ROAM_CFM_MOVE_TITLE   "Move channel?"
#define ROAM_CFM_MOVE_FMT     "from list %u to %u"
#define ROAM_MSG_ADDED        "Added\nto list"
#define ROAM_MSG_REMOVED      "Removed\nfrom list"
#define ROAM_MSG_MOVED        "Moved\nto list"
#define ROAM_MSG_ALREADY      "Already in\nthis list"
#define ROAM_MSG_UNSUITABLE   "Channel unsuitable:\ndigital repeater\nchannels only"
#define ROAM_MSG_NOT_CHANNEL  "Roaming works on\nchannels only (no VFO)"
#define ROAM_MSG_READONLY     "Channels are\nwrite-protected"
#define ROAM_MSG_SAVE_ERR     "Save error"
#define ROAM_IND_LIST         "R"
#define ROAM_IND_SPARE        "R>"
#define ROAM_ZONE_SPARE_FMT   "R> chan %d"
#endif
#endif /* ENABLE_ROAM_RETRY */

#endif /* USER_INTERFACE_ROAM_UI_H_ */
