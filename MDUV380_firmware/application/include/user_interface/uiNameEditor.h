/*
 * uiNameEditor.h -- R64: ОДИН редактор короткої назви (multitap, cp1251, до 16 символів) для зон (menuZoneList.c), списків роумінгу (menuRoam.c) і ключів AES
 * (menuAESKeys.c). Раніше жив у menuZoneList.c (R42, zrDraw/zrKey/...); тепер винесений сюди, поведінка редактора зони НЕ змінена.
 *
 * НОВОЇ RAM НЕМАЄ: стан редактора живе в буфері викликача -- uiDataGlobal.MessageBox.message (68 Б; поки відкрите меню, вікно повідомлення не показується):
 *   [0..15] назва (cp1251), [16] завжди 0, [17] клавіша, що гортається, [18] номер у циклі, [19] режим набору, [20] 1 = редактор відкрито,
 *   [24..27] ticksGetMillis() останнього натискання (uint32_t, через memcpy -- без вирівнювання). Байти [28..] редактор не чіпає (власні поля екрана викликача).
 * Набір ЗАВЖДИ додає в кінець; ЛІВОРУЧ стирає; зберігає й скасовує викликач (зелена/червона).
 */
#ifndef USER_INTERFACE_UINAMEEDITOR_H_
#define USER_INTERFACE_UINAMEEDITOR_H_

#include <stdbool.h>
#include "functions/aprs_rx_cfg.h"

/* Редактор є лише в українській збірці з multitap (той самий критерій, що в sms_multitap.h) І лише коли його хтось використовує (назви зон, імена списків роумінгу, імена
 * ключів AES): інакше файл порожній, а збірки без цих функцій -- байт-у-байт як були. */
#if defined(LANGUAGE_BUILD_UKRAINIAN) && ((defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)) || defined(APRS_RX)) && \
	(defined(ENABLE_ZONE_RENAME) || defined(ENABLE_ROAM_RETRY) || defined(ENABLE_AES_KEY_NAMES) || defined(ENABLE_RXGROUP_EDIT))
#define UI_NAME_EDITOR 1

#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"   /* uiEvent_t */

#define NAME_ED_CAP      16
#define NAME_ED_STATE_LEN 28      /* скільки байт буфера належить редактору */
#define NAME_ED_ACTIVE(buf)  ((buf)[20])

/* Підготувати буфер: name (cp1251, до 16 символів; може бути NULL/порожньою) у [0..15], режим «АБВ» для порожньої, «абв» для непорожньої; редактор відкрито. */
void nameEdInit(char *buf, const char *name);
/* Закрити (буфер далі чужий). */
void nameEdClose(char *buf);
/* Підтвердити символ, що гортається (перед збереженням). */
void nameEdCommit(char *buf);
/* Перемалювати екран редактора з заголовком title. */
void nameEdDraw(const char *buf, const char *title);
/* Текстові клавіші (цифри, «*», «#» -- режим) і ЛІВОРУЧ (стерти). true -- подію спожито (екран перемальовано). Зелену/червону викликач обробляє сам. */
bool nameEdHandleKey(char *buf, const char *title, uiEvent_t *ev);

/* R65A: «N ім'я» у вільні total символів рядка (рядок меню збирається як «підпис:значення» у 16 символів, решту snprintf мовчки відрізав би посеред слова).
 * Не влазить -- ім'я скорочується, а в кінці стоять дві крапки як ознака обрізання. total мусить вміщати хоча б номер і пробіл; out >= total+1 байт. */
void nameEdFitLabel(char *out, unsigned num, const char *name, unsigned total);

#endif
#endif /* USER_INTERFACE_UINAMEEDITOR_H_ */
