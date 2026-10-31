/*
 * menuCodeplug.c -- R44/R46: пункт головного меню «Канали» (список усіх каналів кодплага; Змінити / Видалити / Додати в зону).
 *
 * «Зона» і «Контакти» в головному меню обслуговують наявні екрани (menuZoneList.c, menuContactList.c); тут -- лише канали. ЛОГІКУ видалення каналу й додавання
 * в зону НЕ переписано: викликаються ті самі codeplugChannelDelete (через uiChannelModeDeleteChannel, R41) і codeplugZoneAddChannel (R43).
 *
 * Список читається ПО ОДНОМУ каналу з кодплага (codeplugZoneEditNthChannel) -- копії в пам'яті нема. Стан екрана живе в uiDataGlobal.MessageBox.message (поки відкритий цей екран,
 * вікно повідомлення не показується): НОВОЇ RAM = 0 Б, як і в редакторі назви зони (R42).
 *   [0] стан CC_ST_*, [1..2] курсор списку каналів (uint16, лишається на час дій), [3] курсор вибору зони не потрібен -- він у menuDataGlobal.currentItemIndex.
 */
#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/uiLocalisation.h"

#if defined(CODEPLUG_MENU_ENABLED)

#define CC_BUF      (uiDataGlobal.MessageBox.message)
#define CC_STATE    CC_BUF[0]
#define CC_CUR_LO   CC_BUF[1]
#define CC_CUR_HI   CC_BUF[2]

#define CC_ST_LIST      0   /* список усіх каналів */
#define CC_ST_ACTIONS   1   /* Змінити / Видалити / Додати в зону */
#define CC_ST_CONFIRM   2   /* підтвердження видалення */
#define CC_ST_ZONEPICK  3   /* вибір зони для «Додати в зону» */

#define CC_ACTIONS_COUNT 3

static int ccCursor(void)
{
	return ((uint8_t)CC_CUR_LO) | (((uint8_t)CC_CUR_HI) << 8);
}

static void ccSetCursor(int v)
{
	CC_CUR_LO = (char)(v & 0xFF);
	CC_CUR_HI = (char)((v >> 8) & 0xFF);
}

/* Канал, над яким працюємо (стоїть під курсором списку в момент входу в дії) */
static int ccChannel(void)
{
	return codeplugZoneEditNthChannel(ccCursor());
}

/* Назва каналу в cp1251 для показу: лише перші 16 байтів запису */
static void ccChannelName(int ch, char *out17)
{
	CodeplugChannel_t chBuf;

	codeplugChannelGetDataWithOffsetAndLengthForIndex(ch, &chBuf, 0, 16);
	codeplugUtilConvertBufToDisplayString(chBuf.name, out17, 16);
}

static int ccRealZones(void)
{
	return codeplugZonesGetCount() - 1;   // остання -- віртуальна «Всі канали»
}

static void ccDraw(void)
{
	char nameBuf[17];
	char buf[SCREEN_LINE_BUFFER_SIZE];
	int mNum;

	displayClearBuf();

	if (CC_STATE == CC_ST_CONFIRM)
	{
		int ch = ccChannel();

		ccChannelName(ch, nameBuf);
		menuDisplayTitle(currentLanguage->delete_channel_qm);
		displayPrintCentered(24, nameBuf, FONT_SIZE_3);
		snprintf(buf, sizeof(buf), "%s %d", currentLanguage->in_zones, codeplugChannelCountZones(ch));   // у скількох зонах стоїть канал (він зникне з усіх)
		displayPrintCentered(44, buf, FONT_SIZE_3);
		displayDrawChoice(CHOICE_YESNO, false);
		displayRender();
		return;
	}

	if (CC_STATE == CC_ST_LIST)
	{
		menuDisplayTitle(currentLanguage->cp_channels);
	}
	else if (CC_STATE == CC_ST_ACTIONS)
	{
		ccChannelName(ccChannel(), nameBuf);
		snprintf(buf, sizeof(buf), "%d %s", ccChannel(), nameBuf);
		menuDisplayTitle(buf);
	}
	else
	{
		menuDisplayTitle(currentLanguage->cp_choose_zone);
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

		if (CC_STATE == CC_ST_LIST)
		{
			int ch = codeplugZoneEditNthChannel(mNum);

			ccChannelName(ch, nameBuf);
			snprintf(buf, sizeof(buf), "%d %s", ch, nameBuf);
		}
		else if (CC_STATE == CC_ST_ACTIONS)
		{
			snprintf(buf, sizeof(buf), "%s", (mNum == 0) ? currentLanguage->cp_edit : ((mNum == 1) ? currentLanguage->cp_delete : currentLanguage->cp_to_zone));
		}
		else
		{
			CodeplugZone_t zoneBuf;

			if (codeplugZoneGetDataForNumber(mNum, &zoneBuf))
			{
				codeplugUtilConvertBufToDisplayString(zoneBuf.name, nameBuf, 16);
			}
			else
			{
				snprintf(nameBuf, sizeof(nameBuf), "?");
			}
			snprintf(buf, sizeof(buf), "%s", nameBuf);
		}

		menuDisplayEntry(i, mNum, buf, 0, THEME_ITEM_FG_ZONE_NAME, THEME_ITEM_COLOUR_NONE, THEME_ITEM_BG);
	}

	displayRender();
}

static void ccToList(int cursor)
{
	CC_STATE = CC_ST_LIST;
	menuDataGlobal.numItems = codeplugZoneEditChannelCount();
	if (cursor >= menuDataGlobal.numItems)
	{
		cursor = menuDataGlobal.numItems - 1;
	}
	menuDataGlobal.currentItemIndex = (cursor < 0) ? 0 : cursor;
	ccDraw();
}

static void ccToActions(void)
{
	ccSetCursor(menuDataGlobal.currentItemIndex);
	CC_STATE = CC_ST_ACTIONS;
	menuDataGlobal.numItems = CC_ACTIONS_COUNT;
	menuDataGlobal.currentItemIndex = 0;
	ccDraw();
}

/* «Змінити»: встановлюємо канал поточним у «Всіх каналах» (так само, як вибір зони в робочому списку) і відкриваємо НАЯВНІ «Деталі каналу» -- їх не переписано. */
static void ccEdit(void)
{
	int ch = ccChannel();

	settingsSet(nonVolatileSettings.overrideTG, 0);   // скинути перевизначення TG
	settingsSet(nonVolatileSettings.currentZone, (int16_t)(codeplugZonesGetCount() - 1));   // «Всі канали»
	settingsSet(nonVolatileSettings.currentIndexInTRxGroupList[SETTINGS_CHANNEL_MODE], 0);
	codeplugSetLastUsedChannelInZone(-1, (int16_t)ch);
	codeplugSaveLastUsedChannelInZone();
	channelScreenChannelData.rxFreq = 0x00;   // екран каналу перечитає зону й канал
	settingsSaveIfNeeded(true);
	menuSystemPopAllAndDisplaySpecificRootMenu(UI_CHANNEL_MODE, true);
	menuSystemPushNewMenu(MENU_CHANNEL_DETAILS);
}

static void ccNotify2(const char *l1, const char *l2)
{
	char msg[NOTIFICATION_MESSAGE_LEN_MAX];

	snprintf(msg, sizeof(msg), "%s\n%s", l1, l2);
	uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 2500, msg, false);
}

/* «Видалити»: перевірки, як були у швидкому меню каналу (R41) -- «Канали лише для читання» і єдиний канал у кодплазі */
static void ccToConfirm(void)
{
	if (settingsIsOptionBitSet(BIT_CHANNELS_ARE_READ_ONLY))
	{
		ccNotify2(currentLanguage->aprs_channel, currentLanguage->locked);
		return;
	}
	if (codeplugChannelCountInUse() <= 1)
	{
		ccNotify2(currentLanguage->last_channel, currentLanguage->cannot_delete);
		return;
	}
	CC_STATE = CC_ST_CONFIRM;
	ccDraw();
}

static void ccToZonePick(void)
{
	if (ccRealZones() <= 0)
	{
		uiNotificationShowShort(1500U, currentLanguage->error, false);
		return;
	}
	CC_STATE = CC_ST_ZONEPICK;
	menuDataGlobal.numItems = ccRealZones();
	menuDataGlobal.currentItemIndex = 0;
	ccDraw();
}

/* Додати канал у зону під курсором: ті самі результати й слова, що у виборі каналу для зони (R43) */
static void ccAddToZone(void)
{
	int zn = menuDataGlobal.currentItemIndex;

	switch (codeplugZoneAddChannel(zn, ccChannel()))
	{
		case CODEPLUG_ZONE_EDIT_OK:
			channelScreenChannelData.rxFreq = 0x00;   // екран каналу перечитає зону
			uiNotificationShowShort(1000U, currentLanguage->zone_ch_added, false);
			ccToList(ccCursor());
			break;
		case CODEPLUG_ZONE_EDIT_ALREADY_IN_ZONE:
			uiNotificationShowShort(1500U, currentLanguage->zone_has_channel, false);
			break;
		case CODEPLUG_ZONE_EDIT_ZONE_FULL:
		{
			char msg[NOTIFICATION_MESSAGE_LEN_MAX];

			snprintf(msg, sizeof(msg), "%s\n%s %d", currentLanguage->zone_full, currentLanguage->zone_max, codeplugChannelsPerZone);
			uiNotificationShow(NOTIFICATION_TYPE_MESSAGE, NOTIFICATION_ID_MESSAGE, 2500, msg, false);
			break;
		}
		default:
			uiNotificationShowShort(1500U, currentLanguage->error, false);
			break;
	}
}

static void ccHandleEvent(uiEvent_t *ev)
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
			ccDraw();
		}
		return;
	}

	if ((ev->events & KEY_EVENT) == 0)
	{
		return;
	}

	if (CC_STATE == CC_ST_CONFIRM)
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			int ch = ccChannel();

			(void)uiChannelModeDeleteChannel(ch);   // та сама логіка й порядок запису, що в R41; показує «Канал видалено» або помилку
			ccToList(ccCursor());
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
		{
			CC_STATE = CC_ST_ACTIONS;
			ccDraw();
		}
		return;
	}

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
		ccDraw();
		}
	else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, menuDataGlobal.numItems);
		ccDraw();
		}
	else if ((CC_STATE == CC_ST_LIST) && (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_LEFT)))
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
		ccDraw();
		}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		if (CC_STATE == CC_ST_LIST)
		{
			if (menuDataGlobal.numItems > 0)
			{
				ccToActions();
			}
		}
		else if (CC_STATE == CC_ST_ACTIONS)
		{
			switch (menuDataGlobal.currentItemIndex)
			{
				case 0:
					ccEdit();
					break;
				case 1:
					ccToConfirm();
					break;
				default:
					ccToZonePick();
					break;
			}
		}
		else
		{
			ccAddToZone();
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		if (CC_STATE == CC_ST_LIST)
		{
			menuSystemPopPreviousMenu();
		}
		else if (CC_STATE == CC_ST_ACTIONS)
		{
			ccToList(ccCursor());
		}
		else
		{
			CC_STATE = CC_ST_ACTIONS;   // з вибору зони -- назад до дій над каналом
			menuDataGlobal.numItems = CC_ACTIONS_COUNT;
			menuDataGlobal.currentItemIndex = 2;
			ccDraw();
		}
	}
}

menuStatus_t menuCodeplugChannels(uiEvent_t *ev, bool isFirstRun)
{
	menuStatus_t exitCode = MENU_STATUS_SUCCESS;   // НЕ статична змінна: нової RAM немає

	if (isFirstRun)
	{
		int cur = 0;
		int curCh = uiDataGlobal.currentSelectedChannelNumber;

		// Стати на канал, на якому зараз стоїть рація (якщо він справжній): номер у списку = скільки каналів у масці ДО нього
		if (codeplugAllChannelsIndexIsInUse(curCh))
		{
			for (int ch = 1; ch < curCh; ch++)
			{
				if (codeplugAllChannelsIndexIsInUse(ch))
				{
					cur++;
				}
			}
		}

		ccToList(cur);

		voicePromptsInit();
		voicePromptsAppendPrompt(PROMPT_SILENCE);
		voicePromptsAppendLanguageString(currentLanguage->cp_channels);
		voicePromptsAppendLanguageString(currentLanguage->menu);
		voicePromptsAppendPrompt(PROMPT_SILENCE);

		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	if (ev->hasEvent)
	{
		ccHandleEvent(ev);

		// Сигнал «перший пункт списку» лише на гортанні (як у інших списках)
		if ((ev->events & KEY_EVENT) && (KEYCHECK_PRESS(ev->keys, KEY_DOWN) || KEYCHECK_PRESS(ev->keys, KEY_UP) ||
				((CC_STATE == CC_ST_LIST) && (KEYCHECK_PRESS(ev->keys, KEY_LEFT) || KEYCHECK_PRESS(ev->keys, KEY_RIGHT)))))
		{
			exitCode |= MENU_STATUS_LIST_TYPE;
		}
	}

	return exitCode;
}

#endif // CODEPLUG_MENU_ENABLED
