/*
 * menuAprsHub.h -- меню «APRS» (R8-fix, п.5): одне місце для всього, що стосується APRS у форку.
 * Пункт головного меню (поруч із «Повідомленнями»); усередині: «Режим APRS» (R10), «APRS станції» (R8),
 * «Налаштування» (стокове меню APRS, MENU_APRS -- посилання, не копія) і, лише в діагностичній збірці,
 * «APRS проба». Місце під «Повідомлення APRS» (R11) зарезервовано в enum (menuAprsHub.c) -- НЕ реалізовано. Меню існує лише під APRS_RX (ENABLE_APRS_RX + українська); без прапорця збірка
 * байт-у-байт стокова. Новий ID меню коштує +20 Б main RAM (menuFunctions[] 16 Б + menuDataGlobal.data[] 4 Б) --
 * це єдина цифра RAM цього пункту, її підтверджує mem_report.py з CI.
 */
#ifndef _OPENGD77_MENU_APRS_HUB_H_
#define _OPENGD77_MENU_APRS_HUB_H_

#include "functions/aprs_rx_cfg.h"

#if defined(APRS_RX)
#include "user_interface/menuSystem.h"

menuStatus_t menuAprsHub(uiEvent_t *ev, bool isFirstRun);
#endif

#endif /* _OPENGD77_MENU_APRS_HUB_H_ */
