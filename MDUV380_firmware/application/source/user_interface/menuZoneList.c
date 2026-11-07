/*
 * Copyright (C) 2019-2025 Roger Clark, VK3KYY / G4KYF
 *                         Daniel Caujolle-Bert, F1RMB
 *
 *
 * Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions
 * are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer
 *    in the documentation and/or other materials provided with the distribution.
 *
 * 3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * 4. Use of this source code or binary releases for commercial purposes is strictly forbidden. This includes, without limitation,
 *    incorporation in a commercial product or incorporation into a product or project which allows commercial use.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
 * ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
 * USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 */
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/uiLocalisation.h"
#if defined(ZONE_RENAME_ENABLED)
#include "user_interface/uiNameEditor.h"   /* R64: спільний редактор назви (multitap) -- раніше жив тут */
#endif
#if defined(ZONE_EDIT_ENABLED)
#include "functions/codeplug_zoneedit.h"   /* R43: codeplugZoneListFind -- позначка «канал уже в зоні» у списку вибору */
#endif

/* R46: пункт головного меню «Зона» -- ОДИН екран (MENU_ZONE_LIST) на все: список зон + «Нова зона» (останній рядок); зелена на зоні відкриває дії: «Встановити» (зробити зону
 * поточною -- той самий setZoneToUserSelection(), що перемикав зону в стоковому списку), «Перейменувати», «Канали зони», «Видалити». «Всі канали» -- лише «Встановити».
 * (R44 тримав редагування окремим меню в розділі «Кодплаг» -- два режими екрана; розділ розформовано, режим знову один, як у R42/R43.) */
#if defined(ZONE_RENAME_ENABLED)
#define ZL_EDIT() (true)
#else
#define ZL_EDIT() (false)
#endif

static void updateScreen(bool isFirstRun);
static void handleEvent(uiEvent_t *ev);
static void setZoneToUserSelection(void);
#if defined(ZONE_RENAME_ENABLED)
static void zrStart(int zn);
static void zrHandleEvent(uiEvent_t *ev);
/* Стан редактора назви зони (R42) живе в uiDataGlobal.MessageBox.message -- розкладка в коментарі біля zrDraw() нижче. */
#define ZR_BUF     (uiDataGlobal.MessageBox.message)
#define ZR_CAP     16
#define ZR_ACTIVE  ZR_BUF[20]
#if defined(ZONE_EDIT_ENABLED)
#define ZR_TITLE()  ((ZR_BUF[34] != 0) ? currentLanguage->zone_new : currentLanguage->zone_name)   /* ZR_BUF[34] = ZE_CREATE */
#else
#define ZR_TITLE()  (currentLanguage->zone_name)
#endif
#define ZR_ZN      ZR_BUF[35]   /* номер у списку зон, над якою працюємо (редактор назви й дії R43) */
#endif
#if defined(ZONE_EDIT_ENABLED)
/* R43: дії над зоною. Стан -- у тому ж буфері (байти 32.. не зачіпає редактор, він пише лише [0..27]): новий ОЗП = 0 Б. */
#define ZE_STATE     ZR_BUF[32]   /* ZE_ST_* нижче */
#define ZE_LISTCUR   ZR_BUF[33]   /* курсор списку зон, збережений на час дій (повертаємось на нього) */
#define ZE_CREATE    ZR_BUF[34]   /* 1 -- редактор назви набирає назву НОВОЇ зони */
#define ZE_ST_LIST      0
#define ZE_ST_ACTIONS   1
#define ZE_ST_PICKER    2
#define ZE_ST_CONFIRM   3
#if defined(CODEPLUG_MENU_ENABLED)
#define ZE_ACTIONS_COUNT 4   /* R46: Встановити / Перейменувати / Канали зони / Видалити */
#else
#define ZE_ACTIONS_COUNT 3
#endif
#if defined(CODEPLUG_MENU_ENABLED)
#define ZE_ST_ZCHANS     4   /* R44: «Канали зони» -- список каналів зони: перший рядок «Додати канал», далі канали (зелена на каналі -- вийняти) */
#define ZE_ST_RMCONFIRM  5   /* R44: підтвердження «Вийняти?» для каналу зі списку «Канали зони» */
#define ZE_ZCHCUR    ZR_BUF[36]   /* курсор «Каналів зони», збережений на час вибору каналу (повертаємось на нього) */
#endif
static void zeToList(int selectOrdinal);
static void zeStartCreate(void);
static void zeEnterActions(void);
static void zeHandleEvent(uiEvent_t *ev);
#if defined(CODEPLUG_MENU_ENABLED)
static void zeListEvent(uiEvent_t *ev);
#endif
#endif

static menuStatus_t menuZoneExitCode = MENU_STATUS_SUCCESS;

// Форк: у списку зон приховуємо все, що не є СПРАВЖНЬОЮ зоною (порожні, "сміттєві", з видаленим першим каналом).
// Будуємо відображення "екранний індекс -> справжній номер зони" + завжди віртуальна "Всі канали" (остання).
// R22 Z1.3: правило -- ТА САМА codeplugZoneIsUsable(), що й у перемиканні зон валкодером SK2+енкодер
// (uiChannelMode.c, selectPrevNextZone). До R22 цей коментар стверджував це, але валкодер відкидав лише порожні
// зони -- розходження й давало "зони, яких немає в меню".
static uint8_t s_zoneMap[CODEPLUG_ALL_ZONES_MAX];
static int     s_zoneMapCount;

#if defined(ZONE_EDIT_ENABLED)
// Зона, яка читається і в якій НЕМАЄ жодного каналу (порожній список). «Сміттєві» зони (канали є, але перший не існує) сюди НЕ належать -- їх, як і раніше, не показуємо.
static bool zoneIsEmpty(int zn)
{
	CodeplugZone_t z;

	return codeplugZoneGetDataForNumber(zn, &z) && (z.NOT_IN_CODEPLUGDATA_numChannelsInZone == 0);
}
#endif

static void buildZoneMap(void)
{
	int total = codeplugZonesGetCount();
	int allChannelsZone = total - 1;   // остання зона -- віртуальна "Всі канали"

	s_zoneMapCount = 0;
	for (int zn = 0; (zn < total) && (s_zoneMapCount < (int)CODEPLUG_ALL_ZONES_MAX); zn++)
	{
		// "Всі канали" -- завжди показуємо (codeplugZoneIsUsable() теж каже "так")
		if ((zn == allChannelsZone) || codeplugZoneIsUsable(zn, NULL)
#if defined(ZONE_EDIT_ENABLED)
				|| (ZL_EDIT() && zoneIsEmpty(zn))   // R43: порожню (щойно створену або спорожнілу) зону теж показуємо -- інакше в неї не додати каналів
#endif
				)
		{
			s_zoneMap[s_zoneMapCount++] = (uint8_t)zn;
		}
	}
	if (s_zoneMapCount == 0) { s_zoneMap[s_zoneMapCount++] = 0; }   // запобіжник (не має статись)
}

// Екранний індекс, що відповідає збереженій поточній зоні (або 0, якщо та зона порожня/зникла).
static int zoneMapIndexForZone(int zoneNum)
{
	for (int i = 0; i < s_zoneMapCount; i++)
	{
		if (s_zoneMap[i] == zoneNum) { return i; }
	}
	return 0;
}

#if defined(ZONE_EDIT_ENABLED)
// Скільки пунктів у списку: зони + (R43) останній пункт «Нова зона»
static int zoneListItems(void)
{
	return s_zoneMapCount + (ZL_EDIT() ? 1 : 0);
}
#endif

menuStatus_t menuZoneList(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
		buildZoneMap();
#if defined(ZONE_RENAME_ENABLED)
		if (ZL_EDIT())
		{
		ZR_ACTIVE = 0;   // R42: редактор назви закритий (буфер -- чужа пам'ять, див. нижче)
#if defined(ZONE_EDIT_ENABLED)
		ZE_STATE = ZE_ST_LIST;
		ZE_CREATE = 0;
#endif
		}
#endif
#if defined(ZONE_EDIT_ENABLED)
		menuDataGlobal.numItems = zoneListItems();
#else
		menuDataGlobal.numItems = s_zoneMapCount;
#endif
		menuDataGlobal.currentItemIndex = zoneMapIndexForZone(nonVolatileSettings.currentZone);

		voicePromptsInit();
		voicePromptsAppendPrompt(PROMPT_SILENCE);
		voicePromptsAppendLanguageString(currentLanguage->zone);
		voicePromptsAppendLanguageString(currentLanguage->menu);
		voicePromptsAppendPrompt(PROMPT_SILENCE);

		updateScreen(true);
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}
	else
	{
		menuZoneExitCode = MENU_STATUS_SUCCESS;

		if (ev->hasEvent)
		{
			handleEvent(ev);
		}
	}
	return menuZoneExitCode;
}

static void updateScreen(bool isFirstRun)
{
	char nameBuf[17];
	int mNum;
	CodeplugZone_t zoneBuf;

	displayClearBuf();
	menuDisplayTitle(currentLanguage->zones);

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		if (menuDataGlobal.numItems <= (i + 1))
		{
			break;
		}

		mNum = menuGetMenuOffset(menuDataGlobal.numItems, i);
		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY)
		{
			continue;
		}
		else if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)
		{
			break;
		}

#if defined(ZONE_EDIT_ENABLED)
		if (mNum >= s_zoneMapCount)
		{
			snprintf(nameBuf, sizeof(nameBuf), "%s", currentLanguage->zone_new);   // R43: останній пункт «Нова зона»
		}
		else
		{
#endif
		codeplugZoneGetDataForNumber(s_zoneMap[mNum], &zoneBuf);   // mNum -- екранний індекс -> справжня зона
		codeplugUtilConvertBufToDisplayString(zoneBuf.name, nameBuf, 16);// need to convert to zero terminated string
#if defined(ZONE_EDIT_ENABLED)
		}
#endif

		menuDisplayEntry(i, mNum, (char *)nameBuf, 0, THEME_ITEM_FG_ZONE_NAME, THEME_ITEM_COLOUR_NONE, THEME_ITEM_BG);

		if (i == 0)
		{
			if (!isFirstRun)
			{
				voicePromptsInit();
			}

			if (strcmp(nameBuf,currentLanguage->all_channels) == 0)
			{
				voicePromptsAppendLanguageString(currentLanguage->all_channels);
			}
			else
			{
				voicePromptsAppendString(nameBuf);
			}

			promptsPlayNotAfterTx();
		}
	}

	displayRender();
}

#if defined(ZONE_RENAME_ENABLED)
/* R42: перейменування зони -- клавіша «#» (коротко) на зоні у списку. Редактор -- той самий multitap (functions/sms_multitap.c), що в назві контакту й SMS:
 * «АБВ» -> «абв» -> «ABC» -> «abc» -> «123», режим перемикає «#»; кирилиця -- байтами cp1251. Назва пишеться в кодплаг тим самим codeplugUtilConvertStringToBuf,
 * що назви каналів і контактів (R34/R36), тож кінцева «я» (0xFF) переживає запис: хвіст 0x00.
 *
 * НОВОЇ RAM НЕМАЄ: стан редактора живе в uiDataGlobal.MessageBox.message (68 Б; поки відкритий список «Зони», вікно повідомлення не показується):
 *   [0..15] назва (cp1251), [16] завжди 0, [17] клавіша, що гортається, [18] номер у циклі, [19] режим набору, [20] 1 = редактор відкрито,
 *   [24..27] ticksGetMillis() останнього натискання (uint32_t, через memcpy -- без вирівнювання).
 * Набір ЗАВЖДИ додає в кінець; ЛІВОРУЧ стирає; ЗЕЛЕНА зберігає; ЧЕРВОНА скасовує. Віртуальну «Всі канали» перейменувати не можна (її назва -- з мовної таблиці). */

/* R64: сам редактор (набір, малювання) -- у спільному uiNameEditor.c; тут лише заголовок екрана. */
static void zrDraw(void)
{
	nameEdDraw(ZR_BUF, ZR_TITLE());
}

static void zrStart(int zn)
{
	CodeplugZone_t zoneBuf;

	if (zn == (codeplugZonesGetCount() - 1))
	{
		uiNotificationShowShort(1500U, currentLanguage->zone_rename_all, false);
		return;
	}

	if (!codeplugZoneGetDataForNumber(zn, &zoneBuf))
	{
		uiNotificationShowShort(1500U, currentLanguage->error, false);
		return;
	}

	{
		char nm[ZR_CAP + 1];

		memset(nm, 0, sizeof(nm));
		codeplugUtilConvertBufToDisplayString(zoneBuf.name, nm, 16);   // у cp1251 (назву з CPS в UTF-8 перекодовано), 17 байтів із нулем
		nameEdInit(ZR_BUF, nm);   // R64: очищає [0..27], ставить режим і ZR_ACTIVE = 1
	}
	ZR_ZN = (char)zn;
	zrDraw();
}

#if defined(ZONE_EDIT_ENABLED)
// Показати «що» і «Максимум: N» (межа кількості зон чи каналів у зоні) -- словами, а не мовчазною відмовою
static void zeNotifyMax(const char *what, int max)
{
	char msg[NOTIFICATION_MESSAGE_LEN_MAX];

	snprintf(msg, sizeof(msg), "%s\n%s %d", what, currentLanguage->zone_max, max);
	uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 2500, msg, false);
}

// Редактор назви закрито кнопкою «зберегти» для НОВОЇ зони
static void zeCreateSave(void)
{
	int16_t cur = nonVolatileSettings.currentZone;
	int newOrdinal = -1;

	switch (codeplugZoneCreate(ZR_BUF, &cur, &newOrdinal))
	{
		case CODEPLUG_ZONE_EDIT_OK:
			// Нова зона могла стати ліворуч від поточної -- ординал поточної перераховано всередині, тут лише зберігаємо
			settingsSet(nonVolatileSettings.currentZone, cur);
			channelScreenChannelData.rxFreq = 0x00;   // екран каналу перечитає зону
			settingsSaveIfNeeded(true);
			uiNotificationShowShort(1500U, currentLanguage->zone_created, false);
			zeToList(newOrdinal);
			break;
		case CODEPLUG_ZONE_EDIT_NAME_EMPTY:
			uiNotificationShowShort(1500U, currentLanguage->zone_name_empty, false);   // лишаємось у редакторі
			break;
		case CODEPLUG_ZONE_EDIT_NAME_TOO_LONG:
			uiNotificationShowShort(1500U, currentLanguage->zone_name_ya, false);
			break;
		case CODEPLUG_ZONE_EDIT_NO_FREE_ZONE:
			zeNotifyMax(currentLanguage->zone_too_many, (int)CODEPLUG_ZONES_MAX);
			zeToList(-1);
			break;
		default:
			uiNotificationShowShort(1500U, currentLanguage->error, false);
			zeToList(-1);
			break;
	}
}
#endif

static void zrSave(void)
{
	int zn = (uint8_t)ZR_ZN;

	nameEdCommit(ZR_BUF);

#if defined(ZONE_EDIT_ENABLED)
	if (ZE_CREATE != 0)
	{
		zeCreateSave();
		return;
	}
#endif

	switch (codeplugZoneRename(zn, ZR_BUF))
	{
		case CODEPLUG_ZONE_RENAME_OK:
			ZR_ACTIVE = 0;
			uiNotificationShowShort(1500U, currentLanguage->zone_renamed, false);
#if defined(ZONE_EDIT_ENABLED)
			zeToList(-1);
#else
			updateScreen(false);
#endif
			break;
		case CODEPLUG_ZONE_RENAME_EMPTY:
			uiNotificationShowShort(1500U, currentLanguage->zone_name_empty, false);   // лишаємось у редакторі
			break;
		case CODEPLUG_ZONE_RENAME_AMBIGUOUS_TAIL:
		case CODEPLUG_ZONE_RENAME_TOO_LONG:
			uiNotificationShowShort(1500U, currentLanguage->zone_name_ya, false);
			break;
		case CODEPLUG_ZONE_RENAME_NOT_REAL:
			ZR_ACTIVE = 0;
			uiNotificationShowShort(1500U, currentLanguage->zone_rename_all, false);
#if defined(ZONE_EDIT_ENABLED)
			zeToList(-1);
#else
			updateScreen(false);
#endif
			break;
		default:
			ZR_ACTIVE = 0;
			uiNotificationShowShort(1500U, currentLanguage->error, false);
#if defined(ZONE_EDIT_ENABLED)
			zeToList(-1);
#else
			updateScreen(false);
#endif
			break;
	}
}

static void zrHandleEvent(uiEvent_t *ev)
{
	if (ev->events & FUNCTION_EVENT)
	{
		if (ev->function == FUNC_REDRAW)
		{
			zrDraw();
		}
		return;
	}

	if ((ev->events & KEY_EVENT) == 0)
	{
		return;
	}

	if (nameEdSheetEvent(ZR_BUF, ZR_TITLE(), ev))   /* R66B: шпаргалка розкладки (ВНИЗ) */
	{
		return;
	}

	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		zrSave();
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		ZR_ACTIVE = 0;
#if defined(ZONE_EDIT_ENABLED)
		zeToList(-1);
#else
		updateScreen(false);
#endif
	}
	else
	{
		(void)nameEdHandleKey(ZR_BUF, ZR_TITLE(), ev);
	}
}
#endif // ZONE_RENAME_ENABLED

#if defined(ZONE_EDIT_ENABLED)
/* R43: дії над зоною зі списку «Зони» -- «#» на зоні відкриває короткий список: «Назва зони» (редактор R42), «Додати канал» (вибір каналу з кодплага), «Видалити зону».
 * Останній пункт самого списку -- «Нова зона» (редактор назви, порожній список каналів). Вибір каналу читає канали ПО ОДНОМУ з кодплага (codeplugZoneEditNthChannel):
 * копії списку в пам'яті немає. Усі підекрани користуються тими ж menuDataGlobal.numItems/currentItemIndex, що й список; курсор списку зберігає ZE_LISTCUR. */

static const char *zeActionLabel(int i)
{
#if defined(CODEPLUG_MENU_ENABLED)
	// R46: «Встановити» першою (курсор стоїть на ній: зелена-зелена = обрати зону, як у стоковому списку), «Видалити» -- останньою
	return (i == 0) ? currentLanguage->cp_set_zone : ((i == 1) ? currentLanguage->cp_rename : ((i == 2) ? currentLanguage->cp_zone_chans : currentLanguage->cp_delete));
#else
	return (i == 0) ? currentLanguage->zone_name : ((i == 1) ? currentLanguage->zone_add_channel : currentLanguage->zone_delete);
#endif
}

// Повернутися до списку зон. selectOrdinal >= 0 -- стати на цю зону; -1 -- на збережений курсор (обмежений новою довжиною списку)
static void zeToList(int selectOrdinal)
{
	int idx;

	ZE_STATE = ZE_ST_LIST;
	ZE_CREATE = 0;
	ZR_ACTIVE = 0;
	buildZoneMap();
	menuDataGlobal.numItems = zoneListItems();

	if (selectOrdinal >= 0)
	{
		idx = zoneMapIndexForZone(selectOrdinal);
	}
	else
	{
		idx = (uint8_t)ZE_LISTCUR;
		if (idx >= menuDataGlobal.numItems)
		{
			idx = menuDataGlobal.numItems - 1;
		}
	}
	menuDataGlobal.currentItemIndex = idx;
	menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	updateScreen(false);
}

// Малює список під курсором: ZE_ST_ACTIONS -- дії над зоною (R46: чотири, перша «Встановити»), ZE_ST_PICKER -- канали з кодплага (позначені «*» вже в зоні), ZE_ST_CONFIRM -- підтвердження видалення зони
static void zeDraw(void)
{
	char nameBuf[17];
	char buf[SCREEN_LINE_BUFFER_SIZE];
	CodeplugZone_t zoneBuf;
	int mNum;

	displayClearBuf();

	if (ZE_STATE == ZE_ST_CONFIRM)
	{
		codeplugZoneGetDataForNumber((uint8_t)ZR_ZN, &zoneBuf);
		codeplugUtilConvertBufToDisplayString(zoneBuf.name, nameBuf, 16);
		menuDisplayTitle(currentLanguage->zone_delete_qm);
		displayPrintCentered(24, nameBuf, FONT_SIZE_3);
		snprintf(buf, sizeof(buf), "%s %d", currentLanguage->zone_chans, zoneBuf.NOT_IN_CODEPLUGDATA_numChannelsInZone);
		displayPrintCentered(44, buf, FONT_SIZE_3);
		displayPrintCentered(60, currentLanguage->zone_chans_kept, FONT_SIZE_3);   // канали при видаленні зони НЕ видаляються -- кажемо це прямо
		displayDrawChoice(CHOICE_YESNO, false);
		displayRender();
		return;
	}

#if defined(CODEPLUG_MENU_ENABLED)
	if (ZE_STATE == ZE_ST_RMCONFIRM)
	{
		CodeplugChannel_t rmCh;
		int rmPos = menuDataGlobal.currentItemIndex - 1;
		int rmChan = 0;

		codeplugZoneGetDataForNumber((uint8_t)ZR_ZN, &zoneBuf);
		if ((rmPos >= 0) && (rmPos < zoneBuf.NOT_IN_CODEPLUGDATA_numChannelsInZone))
		{
			rmChan = zoneBuf.channels[rmPos];
		}
		codeplugChannelGetDataWithOffsetAndLengthForIndex(rmChan, &rmCh, 0, 16);   // лише назва: перші 16 байтів запису
		codeplugUtilConvertBufToDisplayString(rmCh.name, nameBuf, 16);
		menuDisplayTitle(currentLanguage->zone_remove_qm);
		displayPrintCentered(24, nameBuf, FONT_SIZE_3);   // який канал виймаємо
		codeplugUtilConvertBufToDisplayString(zoneBuf.name, buf, 16);
		displayPrintCentered(44, buf, FONT_SIZE_3);   // з якої зони
		displayPrintCentered(60, currentLanguage->zone_chan_stays, FONT_SIZE_3);   // канал НЕ видаляється -- кажемо це прямо
		displayDrawChoice(CHOICE_YESNO, false);
		displayRender();
		return;
	}
#endif

	if (ZE_STATE == ZE_ST_ACTIONS)
	{
		codeplugZoneGetDataForNumber((uint8_t)ZR_ZN, &zoneBuf);
		codeplugUtilConvertBufToDisplayString(zoneBuf.name, nameBuf, 16);
		menuDisplayTitle(nameBuf);
	}
#if defined(CODEPLUG_MENU_ENABLED)
	else if (ZE_STATE == ZE_ST_ZCHANS)
	{
		codeplugZoneGetDataForNumber((uint8_t)ZR_ZN, &zoneBuf);
		codeplugUtilConvertBufToDisplayString(zoneBuf.name, nameBuf, 16);
		menuDisplayTitle(nameBuf);
	}
#endif
	else
	{
		codeplugZoneGetDataForNumber((uint8_t)ZR_ZN, &zoneBuf);   // для позначок «вже в зоні»
		menuDisplayTitle(currentLanguage->zone_add_channel);
	}

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		if (menuDataGlobal.numItems <= (i + 1))
		{
			break;
		}

		mNum = menuGetMenuOffset(menuDataGlobal.numItems, i);
		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY)
		{
			continue;
		}
		else if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)
		{
			break;
		}

		if (ZE_STATE == ZE_ST_ACTIONS)
		{
			snprintf(buf, sizeof(buf), "%s", zeActionLabel(mNum));
		}
#if defined(CODEPLUG_MENU_ENABLED)
		else if (ZE_STATE == ZE_ST_ZCHANS)
		{
			if (mNum == 0)
			{
				snprintf(buf, sizeof(buf), "%s", currentLanguage->zone_add_channel);   // перший рядок -- додати
			}
			else
			{
				CodeplugChannel_t zCh;
				int zChan = zoneBuf.channels[mNum - 1];

				codeplugChannelGetDataWithOffsetAndLengthForIndex(zChan, &zCh, 0, 16);   // лише назва: перші 16 байтів запису
				codeplugUtilConvertBufToDisplayString(zCh.name, nameBuf, 16);
				snprintf(buf, sizeof(buf), "%d %s", zChan, nameBuf);
			}
		}
#endif
		else
		{
			CodeplugChannel_t chBuf;
			int ch = codeplugZoneEditNthChannel(mNum);

			codeplugChannelGetDataWithOffsetAndLengthForIndex(ch, &chBuf, 0, 16);   // лише назва: перші 16 байтів запису
			codeplugUtilConvertBufToDisplayString(chBuf.name, nameBuf, 16);
			snprintf(buf, sizeof(buf), "%s%d %s",
					(codeplugZoneListFind(zoneBuf.channels, zoneBuf.NOT_IN_CODEPLUGDATA_numChannelsInZone, (uint16_t)ch) >= 0) ? "*" : "", ch, nameBuf);
		}

		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_ZONE_NAME, THEME_ITEM_COLOUR_NONE, THEME_ITEM_BG);
	}

	displayRender();
}

static void zeToActions(void)
{
	ZE_STATE = ZE_ST_ACTIONS;
	menuDataGlobal.numItems = ZE_ACTIONS_COUNT;
	menuDataGlobal.currentItemIndex = 0;
	zeDraw();
}

#if defined(CODEPLUG_MENU_ENABLED)
// R46: «Встановити». Зона обирається ТИМ САМИМ setZoneToUserSelection(), що й у стоковому списку (скидає overrideTG, пише currentZone, зберігає, виходить на екран каналів): лише
// ставимо екранний індекс цієї зони -- дублювання коду нема. Курсор дій після цього не потрібен: усі меню закриваються. Порожню зону не обираємо -- стоковий список таких не показував
// (перемикатись нема на що); «Всі канали» (віртуальна) завжди обирається.
static void zeSetActive(int zn)
{
	if ((zn != (codeplugZonesGetCount() - 1)) && zoneIsEmpty(zn))
	{
		uiNotificationShowShort(1500U, currentLanguage->zone_empty, false);   // «Зона пуста»
		return;
	}

	menuDataGlobal.currentItemIndex = zoneMapIndexForZone(zn);
	setZoneToUserSelection();
}
#endif

// Зелена на зоні (R43: «#»): відкрити дії
static void zeEnterActions(void)
{
	int zn = (menuDataGlobal.currentItemIndex < s_zoneMapCount) ? s_zoneMap[menuDataGlobal.currentItemIndex] : -1;

#if defined(CODEPLUG_MENU_ENABLED)
	if (zn == (codeplugZonesGetCount() - 1))
	{
		zeSetActive(zn);   // R46: «Всі канали» -- віртуальна зона, редагувати нічого; єдина дія над нею -- «Встановити», тож без списку дій
		return;
	}
	if (zn < 0)
	{
		return;   // пункт «Нова зона» сюди не потрапляє (його обробляє zeListEvent), запобіжник
	}
#else
	if ((zn < 0) || (zn == (codeplugZonesGetCount() - 1)))
	{
		uiNotificationShowShort(1500U, currentLanguage->zone_rename_all, false);   // «Всі канали» (і пункт «Нова зона») -- не зона для редагування
		return;
	}
#endif

	ZE_LISTCUR = (char)menuDataGlobal.currentItemIndex;
	ZR_ZN = (char)zn;
	zeToActions();
	voicePromptsInit();
	voicePromptsAppendLanguageString(currentLanguage->zone);
	promptsPlayNotAfterTx();
}

// Пункт «Нова зона»: редактор назви з порожнім рядком; зона з'явиться в кодплазі лише після «зберегти»
static void zeStartCreate(void)
{
	ZE_LISTCUR = (char)menuDataGlobal.currentItemIndex;
	ZR_ZN = 0;
	nameEdInit(ZR_BUF, NULL);   // R64: порожня назва, режим «АБВ», редактор відкрито
	ZE_CREATE = 1;
	zrDraw();
}

static void zeToPicker(void)
{
	if (codeplugZoneEditChannelCount() == 0)
	{
		uiNotificationShowShort(1500U, currentLanguage->error, false);
		return;
	}
#if defined(CODEPLUG_MENU_ENABLED)
	ZE_ZCHCUR = (char)menuDataGlobal.currentItemIndex;   // R44: повернення з вибору -- на той самий рядок «Каналів зони»
#endif
	ZE_STATE = ZE_ST_PICKER;
	menuDataGlobal.numItems = codeplugZoneEditChannelCount();
	menuDataGlobal.currentItemIndex = 0;
	zeDraw();
}

static void zeAddSelected(void)
{
	int ch = codeplugZoneEditNthChannel(menuDataGlobal.currentItemIndex);

	switch (codeplugZoneAddChannel((uint8_t)ZR_ZN, ch))
	{
		case CODEPLUG_ZONE_EDIT_OK:
			channelScreenChannelData.rxFreq = 0x00;   // екран каналу перечитає зону
			uiNotificationShowShort(1000U, currentLanguage->zone_ch_added, false);
			zeDraw();
			break;
		case CODEPLUG_ZONE_EDIT_ALREADY_IN_ZONE:
			uiNotificationShowShort(1500U, currentLanguage->zone_has_channel, false);
			break;
		case CODEPLUG_ZONE_EDIT_ZONE_FULL:
			zeNotifyMax(currentLanguage->zone_full, codeplugChannelsPerZone);   // зона заповнена -- кажемо словами і скільки максимум
			break;
		default:
			uiNotificationShowShort(1500U, currentLanguage->error, false);
			break;
	}
}

// Підтверджено «Видалити зону». Канали не чіпаються; поточна зона (якщо це вона) стає «Всі канали».
static void zeDeleteConfirmed(void)
{
	int16_t cur = nonVolatileSettings.currentZone;

	if (codeplugZoneDelete((uint8_t)ZR_ZN, &cur) == CODEPLUG_ZONE_EDIT_OK)
	{
		settingsSet(nonVolatileSettings.currentZone, cur);
		channelScreenChannelData.rxFreq = 0x00;   // екран каналу перечитає зону (uiChannelInitializeCurrentZone), вибір піде на «Всі канали», якщо поточну видалено
		settingsSaveIfNeeded(true);
		uiNotificationShowShort(1500U, currentLanguage->zone_deleted, false);
	}
	else
	{
		uiNotificationShowShort(1500U, currentLanguage->error, false);
	}
	zeToList(-1);
}

#if defined(CODEPLUG_MENU_ENABLED)
// R44: «Канали зони». cursor -- на який рядок стати (обмежується довжиною списку): 0 -- «Додати канал», далі канали зони за порядком у кодплазі
static void zeToZChans(int cursor)
{
	CodeplugZone_t zoneBuf;

	if (!codeplugZoneGetDataForNumber((uint8_t)ZR_ZN, &zoneBuf))
	{
		uiNotificationShowShort(1500U, currentLanguage->error, false);
		zeToList(-1);
		return;
	}
	ZE_STATE = ZE_ST_ZCHANS;
	menuDataGlobal.numItems = 1 + zoneBuf.NOT_IN_CODEPLUGDATA_numChannelsInZone;
	if (cursor >= menuDataGlobal.numItems)
	{
		cursor = menuDataGlobal.numItems - 1;
	}
	menuDataGlobal.currentItemIndex = (cursor < 0) ? 0 : cursor;
	menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	zeDraw();
}

// Зелена на каналі зі списку «Канали зони»: екран підтвердження «Вийняти?». «Канали лише для читання» (Загальні -> Блокування) діють, як на швидкому меню каналу (R43).
static void zeToRmConfirm(void)
{
	if (settingsIsOptionBitSet(BIT_CHANNELS_ARE_READ_ONLY))
	{
		char msg[NOTIFICATION_MESSAGE_LEN_MAX];

		snprintf(msg, sizeof(msg), "%s\n%s", currentLanguage->aprs_channel, currentLanguage->locked);
		uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 2500, msg, false);
		return;
	}
	ZE_STATE = ZE_ST_RMCONFIRM;
	zeDraw();
}

// Підтверджено «Вийняти?»: та сама логіка, що була у швидкому меню каналу (uiChannelModeZoneRemoveChannelAt); канал не видаляється
static void zeRemoveConfirmed(void)
{
	int pos = menuDataGlobal.currentItemIndex - 1;

	(void)uiChannelModeZoneRemoveChannelAt((uint8_t)ZR_ZN, pos);
	zeToZChans(pos + 1);   // курсор лишається поруч (на наступному каналі, що зайняв місце)
}

// Список зон («Зона» в головному меню): зелена -- дії над зоною (або «Нова зона» на останньому рядку), червона -- назад до головного меню.
// Швидкі клавіші, як у стоковому списку: SK2+цифра на зоні запам'ятовує її (ID меню 2 + номер рядка), збережена швидка клавіша перемикає зону одразу.
static void zeListEvent(uiEvent_t *ev)
{
	if (ev->events & BUTTON_EVENT)
	{
		if (repeatVoicePromptOnSK1(ev))
		{
			return;
		}
	}

	if (ev->events & FUNCTION_EVENT)
	{
		if (ev->function == FUNC_REDRAW)
		{
			updateScreen(false);
		}
		else if ((QUICKKEY_TYPE(ev->function) == QUICKKEY_MENU) && (QUICKKEY_LONGENTRYID(ev->function) > 0) && (QUICKKEY_LONGENTRYID(ev->function) <= s_zoneMapCount))
		{
			// Збережена швидка клавіша на зону (рядок = номер - 1). «Нова зона» (останній рядок) сюди не потрапляє: <= s_zoneMapCount, а не numItems
			zeSetActive(s_zoneMap[QUICKKEY_LONGENTRYID(ev->function) - 1]);
		}
		return;
	}

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
		updateScreen(false);
		menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
		updateScreen(false);
		menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if (KEYCHECK_SHORTUP_NUMBER(ev->keys) && BUTTONCHECK_DOWN(ev, BUTTON_SK2))
	{
		if (menuDataGlobal.currentItemIndex < s_zoneMapCount)   // на «Новій зоні» швидку клавішу не запам'ятовуємо
		{
			saveQuickkeyMenuLongValue(ev->keys.key, menuSystemGetCurrentMenuNumber(), menuDataGlobal.currentItemIndex + 1);
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		if (menuDataGlobal.currentItemIndex >= s_zoneMapCount)
		{
			zeStartCreate();   // останній пункт «Нова зона»
		}
		else
		{
			zeEnterActions();
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		menuSystemPopPreviousMenu();
	}
}
#endif // CODEPLUG_MENU_ENABLED

static void zeHandleEvent(uiEvent_t *ev)
{
	if (ev->events & FUNCTION_EVENT)
	{
		if (ev->function == FUNC_REDRAW)
		{
			zeDraw();
		}
		return;
	}

	if ((ev->events & KEY_EVENT) == 0)
	{
		return;
	}

	if (ZE_STATE == ZE_ST_CONFIRM)
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			zeDeleteConfirmed();
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			zeToActions();
		}
		return;
	}
#if defined(CODEPLUG_MENU_ENABLED)
	if (ZE_STATE == ZE_ST_RMCONFIRM)
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			zeRemoveConfirmed();
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			ZE_STATE = ZE_ST_ZCHANS;   // скасовано: канал лишається в зоні, курсор там само
			zeDraw();
		}
		return;
	}
#endif

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
		zeDraw();
		menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
		zeDraw();
		menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if ((ZE_STATE == ZE_ST_PICKER) && (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_LEFT)))
	{
		// До 1024 каналів: вліво/вправо -- через 10
		for (int k = 0; k < 10; k++)
		{
			if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
			{
				menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
			}
			else
			{
				menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
			}
		}
		zeDraw();
		menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		if (ZE_STATE == ZE_ST_PICKER)
		{
			zeAddSelected();
		}
#if defined(CODEPLUG_MENU_ENABLED)
		else if (ZE_STATE == ZE_ST_ZCHANS)
		{
			if (menuDataGlobal.currentItemIndex == 0)
			{
				zeToPicker();   // «Додати канал»
			}
			else
			{
				zeToRmConfirm();   // канал зони -- вийняти (з підтвердженням)
			}
		}
#endif
#if defined(CODEPLUG_MENU_ENABLED)
		else if (menuDataGlobal.currentItemIndex == 0)
		{
			zeSetActive((uint8_t)ZR_ZN);   // R46: «Встановити»
		}
		else if (menuDataGlobal.currentItemIndex == 1)
		{
			zrStart((uint8_t)ZR_ZN);   // «Перейменувати»: редактор R42
		}
		else if (menuDataGlobal.currentItemIndex == 2)
		{
			zeToZChans(0);   // R44: «Канали зони» (додати/вийняти)
		}
#else
		else if (menuDataGlobal.currentItemIndex == 0)
		{
			zrStart((uint8_t)ZR_ZN);   // «Назва зони»: редактор R42
		}
		else if (menuDataGlobal.currentItemIndex == 1)
		{
			zeToPicker();
		}
#endif
		else
		{
			ZE_STATE = ZE_ST_CONFIRM;
			zeDraw();
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		if (ZE_STATE == ZE_ST_PICKER)
		{
#if defined(CODEPLUG_MENU_ENABLED)
			zeToZChans((uint8_t)ZE_ZCHCUR);   // R44: назад до «Каналів зони» на той самий рядок
#else
			zeToActions();
#endif
		}
#if defined(CODEPLUG_MENU_ENABLED)
		else if (ZE_STATE == ZE_ST_ZCHANS)
		{
			zeToActions();
		}
#endif
		else
		{
			zeToList(-1);
		}
	}
}
#endif // ZONE_EDIT_ENABLED

static void handleEvent(uiEvent_t *ev)
{
#if defined(ZONE_RENAME_ENABLED)
	if (ZL_EDIT() && (ZR_ACTIVE == 1))
	{
		zrHandleEvent(ev);
		return;
	}
#endif
#if defined(ZONE_EDIT_ENABLED)
	if (ZL_EDIT() && (ZE_STATE != ZE_ST_LIST))
	{
		zeHandleEvent(ev);
		return;
	}
#endif
#if defined(CODEPLUG_MENU_ENABLED)
	if (ZL_EDIT())
	{
		zeListEvent(ev);   // R44: список зон у режимі редагування -- без перемикання зони, швидких клавіш і «#»
		return;
	}
#endif

	if (ev->events & BUTTON_EVENT)
	{
		if (repeatVoicePromptOnSK1(ev))
		{
			return;
		}
	}

	if (ev->events & FUNCTION_EVENT)
	{
		if (ev->function == FUNC_REDRAW)
		{
			updateScreen(false);
		}
		else if ((QUICKKEY_TYPE(ev->function) == QUICKKEY_MENU) && (QUICKKEY_LONGENTRYID(ev->function) > 0) && (QUICKKEY_LONGENTRYID(ev->function) <= menuDataGlobal.numItems))
		{
			menuDataGlobal.currentItemIndex = QUICKKEY_LONGENTRYID(ev->function) - 1;
			setZoneToUserSelection();
		}

		return;
	}

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
		updateScreen(false);
		menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
		updateScreen(false);
		menuZoneExitCode |= MENU_STATUS_LIST_TYPE;
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		setZoneToUserSelection();
		return;
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		menuSystemPopPreviousMenu();
		return;
	}
#if defined(ZONE_RENAME_ENABLED) && !defined(CODEPLUG_MENU_ENABLED)   /* R46: у збірці з ENABLE_CODEPLUG_MENU список обслуговує zeListEvent: «#» нічого не відкриває, дії -- на зеленій */
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH))
	{
#if defined(ZONE_EDIT_ENABLED)
		zeEnterActions();   // R43: «#» відкриває дії над зоною (серед них «Назва зони» -- редактор R42)
#else
		zrStart(s_zoneMap[menuDataGlobal.currentItemIndex]);   // R42: перейменувати зону під курсором
#endif
		return;
	}
#endif
	else if (KEYCHECK_SHORTUP_NUMBER(ev->keys) && BUTTONCHECK_DOWN(ev, BUTTON_SK2))
	{
		saveQuickkeyMenuLongValue(ev->keys.key, menuSystemGetCurrentMenuNumber(), menuDataGlobal.currentItemIndex + 1);
		return;
	}
}


static void setZoneToUserSelection(void)
{
#if defined(ZONE_EDIT_ENABLED) && !defined(CODEPLUG_MENU_ENABLED)   /* R46: у збірці з ENABLE_CODEPLUG_MENU вибір зони й дії розділені (zeListEvent/zeSetActive) */
	if (menuDataGlobal.currentItemIndex >= s_zoneMapCount)
	{
		zeStartCreate();   // R43: останній пункт «Нова зона»
		return;
	}
	if (zoneIsEmpty(s_zoneMap[menuDataGlobal.currentItemIndex]))
	{
		zeEnterActions();   // R43: порожня зона -- перемикатись нема на що, відкриваємо дії (серед них «Додати канал»)
		return;
	}
#endif
	settingsSet(nonVolatileSettings.overrideTG, 0); // remove any TG override
	// Форк: екранний індекс -> справжній номер зони (порожні пропущено, тож індекси не збігаються).
	settingsSet(nonVolatileSettings.currentZone, (int16_t) s_zoneMap[menuDataGlobal.currentItemIndex]);
	settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 0);// Since we are switching zones the TRx Group index should be reset
	channelScreenChannelData.rxFreq = 0x00; // Flag to the Channel screen that the channel data is now invalid and needs to be reloaded

	settingsSaveIfNeeded(true);
	menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, true);
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; // Force screen redraw
}
