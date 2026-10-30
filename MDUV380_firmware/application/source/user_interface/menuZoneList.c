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
#include "functions/sms_multitap.h"
#include "user_interface/languages/aprsmode_ua.h"   /* APRSM_L_MTHINT -- підказка "#:режим", та сама, що в редакторі контакту */
#endif

static void updateScreen(bool isFirstRun);
static void handleEvent(uiEvent_t *ev);
static void setZoneToUserSelection(void);
#if defined(ZONE_RENAME_ENABLED)
static void zrStart(void);
static void zrHandleEvent(uiEvent_t *ev);
/* Стан редактора назви зони (R42) живе в uiDataGlobal.MessageBox.message -- розкладка в коментарі біля zrDraw() нижче. */
#define ZR_BUF     (uiDataGlobal.MessageBox.message)
#define ZR_CAP     16
#define ZR_KEY     ZR_BUF[17]
#define ZR_IDX     ZR_BUF[18]
#define ZR_MODE    ZR_BUF[19]
#define ZR_ACTIVE  ZR_BUF[20]
#endif

static menuStatus_t menuZoneExitCode = MENU_STATUS_SUCCESS;

// Форк: у списку зон приховуємо все, що не є СПРАВЖНЬОЮ зоною (порожні, "сміттєві", з видаленим першим каналом).
// Будуємо відображення "екранний індекс -> справжній номер зони" + завжди віртуальна "Всі канали" (остання).
// R22 Z1.3: правило -- ТА САМА codeplugZoneIsUsable(), що й у перемиканні зон валкодером SK2+енкодер
// (uiChannelMode.c, selectPrevNextZone). До R22 цей коментар стверджував це, але валкодер відкидав лише порожні
// зони -- розходження й давало "зони, яких немає в меню".
static uint8_t s_zoneMap[CODEPLUG_ALL_ZONES_MAX];
static int     s_zoneMapCount;

static void buildZoneMap(void)
{
	int total = codeplugZonesGetCount();
	int allChannelsZone = total - 1;   // остання зона -- віртуальна "Всі канали"

	s_zoneMapCount = 0;
	for (int zn = 0; (zn < total) && (s_zoneMapCount < (int)CODEPLUG_ALL_ZONES_MAX); zn++)
	{
		// "Всі канали" -- завжди показуємо (codeplugZoneIsUsable() теж каже "так")
		if ((zn == allChannelsZone) || codeplugZoneIsUsable(zn, NULL))
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

menuStatus_t menuZoneList(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
		buildZoneMap();
#if defined(ZONE_RENAME_ENABLED)
		ZR_ACTIVE = 0;   // R42: редактор назви закритий (буфер -- чужа пам'ять, див. нижче)
#endif
		menuDataGlobal.numItems = s_zoneMapCount;
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

		codeplugZoneGetDataForNumber(s_zoneMap[mNum], &zoneBuf);   // mNum -- екранний індекс -> справжня зона
		codeplugUtilConvertBufToDisplayString(zoneBuf.name, nameBuf, 16);// need to convert to zero terminated string

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

static uint32_t zrGetMs(void)
{
	uint32_t v;

	memcpy(&v, &ZR_BUF[24], sizeof(v));
	return v;
}

static void zrSetMs(uint32_t v)
{
	memcpy(&ZR_BUF[24], &v, sizeof(v));
}

static uint8_t zrMode(void)
{
	return (((uint8_t)ZR_MODE) < SMS_MT_MODES) ? (uint8_t)ZR_MODE : (uint8_t)SMS_MT_DEFAULT;
}

static void zrDraw(void)
{
	char line[ZR_CAP + 2];
	char cnt[12];
	int n = (int)strlen(ZR_BUF);
	const char *lbl = smsMtModeLabel(zrMode());
	int16_t chipW = (int16_t)((strlen(lbl) * 6U) + 4U);

	if (n > ZR_CAP)
	{
		n = ZR_CAP;
	}
	memcpy(line, ZR_BUF, (size_t)n);
	if (n < ZR_CAP)
	{
		line[n++] = '_';   // курсор: наступний символ піде сюди
	}
	line[n] = 0;

	displayClearBuf();
	menuDisplayTitle(currentLanguage->zone_name);
	displayThemeApply(THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
	displayPrintCore(0, 48, line, FONT_SIZE_3, TEXT_ALIGN_CENTER, false);
	displayThemeApply(THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_BG);

	// Індикатор режиму набору, підказка "#:режим" і лічильник -- внизу, як в редакторі назви контакту
	displayFillRect(0, 108, chipW, 10, false);
	displayPrintCore(2, 109, lbl, FONT_SIZE_1, TEXT_ALIGN_LEFT, true);
	displayPrintAt((uint16_t)(chipW + 4), 109, APRSM_L_MTHINT, FONT_SIZE_1);
	snprintf(cnt, sizeof(cnt), "%d/%d", (int)strlen(ZR_BUF), ZR_CAP);
	displayPrintCore(0, 109, cnt, FONT_SIZE_1, TEXT_ALIGN_RIGHT, false);
	displayRender();
}

static void zrStart(void)
{
	CodeplugZone_t zoneBuf;
	int zn = s_zoneMap[menuDataGlobal.currentItemIndex];

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

	memset(ZR_BUF, 0, 28);
	codeplugUtilConvertBufToDisplayString(zoneBuf.name, ZR_BUF, 16);   // у cp1251 (назву з CPS в UTF-8 перекодовано), 17 байтів із нулем
	ZR_KEY = 0;
	ZR_IDX = 0;
	ZR_MODE = (char)((ZR_BUF[0] == 0) ? SMS_MT_UA_UP : SMS_MT_UA_LO);   // порожня назва починається з великої
	zrSetMs(0);
	ZR_ACTIVE = 1;
	zrDraw();
}

// Підтвердити символ, що гортається (якщо є)
static void zrCommit(void)
{
	if (ZR_KEY != 0)
	{
		smsMt_t mt = { ZR_KEY, (uint8_t)ZR_IDX };
		int16_t p = (int16_t)(strlen(ZR_BUF) - 1U);   // символ перегляду -- в останній позиції рядка

		smsMtCommit(&mt, &p);
		ZR_KEY = 0;
		ZR_IDX = 0;
	}
}

static void zrSave(void)
{
	int zn = s_zoneMap[menuDataGlobal.currentItemIndex];

	zrCommit();

	switch (codeplugZoneRename(zn, ZR_BUF))
	{
		case CODEPLUG_ZONE_RENAME_OK:
			ZR_ACTIVE = 0;
			uiNotificationShowShort(1500U, currentLanguage->zone_renamed, false);
			updateScreen(false);
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
			updateScreen(false);
			break;
		default:
			ZR_ACTIVE = 0;
			uiNotificationShowShort(1500U, currentLanguage->error, false);
			updateScreen(false);
			break;
	}
}

// Текстова клавіша (цифри/"*" -- на натисканні, "#" -- на відпусканні: режим набору)
static void zrKey(uiEvent_t *ev)
{
	char k = (char)ev->keys.key;
	uint8_t mode = zrMode();
	smsMt_t mt = { ZR_KEY, (uint8_t)ZR_IDX };
	int16_t p = (int16_t)strlen(ZR_BUF);

	if (mt.key != 0)
	{
		p--;   // підтверджений текст закінчується перед символом, що гортається
	}

	if (k == KEY_HASH)
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH) == false)
		{
			return;
		}
		smsMtCommit(&mt, &p);
		ZR_MODE = (char)smsMtModeNext(mode);
	}
	else
	{
		if ((ev->keys.event & KEY_MOD_LONG) || ((ev->keys.event & KEY_MOD_PRESS) == 0) || (smsMtKeyMap(mode, k) == NULL))
		{
			return;
		}

		uint32_t now = ticksGetMillis();
		bool same = (mt.key == k) && ((now - zrGetMs()) < SMS_MT_TIMEOUT_MS);

		if (smsMtKey(&mt, mode, k, same, ZR_BUF, &p, ZR_CAP) == 1)
		{
			zrSetMs(now);
		}
	}

	ZR_KEY = mt.key;
	ZR_IDX = (char)mt.idx;
	zrDraw();
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

	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		zrSave();
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		ZR_ACTIVE = 0;
		updateScreen(false);
	}
	else if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))
	{
		smsMt_t mt = { ZR_KEY, (uint8_t)ZR_IDX };
		int16_t p = (int16_t)strlen(ZR_BUF);

		if (mt.key != 0)
		{
			p--;   // підтверджений текст закінчується перед символом, що гортається
		}
		smsMtBackspace(&mt, ZR_BUF, &p);
		ZR_KEY = mt.key;
		ZR_IDX = (char)mt.idx;
		zrDraw();
	}
	else if (((ev->keys.key >= '0') && (ev->keys.key <= '9')) || (ev->keys.key == '*') || (ev->keys.key == KEY_HASH))
	{
		zrKey(ev);
	}
}
#endif // ZONE_RENAME_ENABLED

static void handleEvent(uiEvent_t *ev)
{
#if defined(ZONE_RENAME_ENABLED)
	if (ZR_ACTIVE == 1)
	{
		zrHandleEvent(ev);
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
#if defined(ZONE_RENAME_ENABLED)
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH))
	{
		zrStart();   // R42: перейменувати зону під курсором
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
	settingsSet(nonVolatileSettings.overrideTG, 0); // remove any TG override
	// Форк: екранний індекс -> справжній номер зони (порожні пропущено, тож індекси не збігаються).
	settingsSet(nonVolatileSettings.currentZone, (int16_t) s_zoneMap[menuDataGlobal.currentItemIndex]);
	settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 0);// Since we are switching zones the TRx Group index should be reset
	channelScreenChannelData.rxFreq = 0x00; // Flag to the Channel screen that the channel data is now invalid and needs to be reloaded

	settingsSaveIfNeeded(true);
	menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, true);
	uiDataGlobal.displayQSOState = QSO_DISPLAY_DEFAULT_SCREEN; // Force screen redraw
}
