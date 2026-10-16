/*
 * Copyright (C) 2019-2025 Roger Clark, VK3KYY / G4KYF
 *                         Colin Durbridge, G4EML
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
#include "functions/trx.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/uiLocalisation.h"
#if defined(APRS_R21_NAMES)
#include "functions/sms_multitap.h"
#include "user_interface/languages/aprsmode_ua.h"   /* R23 Y2: APRSM_L_MTHINT */
#endif

static void updateScreen(bool isFirstRun, bool updateScreen);
static void updateCursor(bool moved);
static void handleEvent(uiEvent_t *ev);
static bool contactIsNewOrAtSameIndex(CodeplugContact_t *ct, int index);

static menuStatus_t menuContactDetailsExitCode = MENU_STATUS_SUCCESS;

static CodeplugContact_t tmpContact;
static const char *callTypeString[3];
static int contactDetailsIndex;
static char digits[9];
static char contactName[20];
static int namePos;
static int numPos;

#if defined(APRS_R21_NAMES)
/* R23 Y2: редактор назви контакту -- власний multitap (functions/sms_multitap.c, як у "Нове повідомлення" і редакторі "Режиму APRS") замість стокового
 * латинського keypadAlphaEnable: "АБВ" -> "абв" -> "ABC" -> "abc" -> "123", перемикання клавішею "#". Кирилиця -- байтами cp1251; поле кодплуга 16 байтів,
 * тож ліміт -- 16 символів.
 *
 * НОВОЇ RAM НЕМАЄ (бриф R23): стан multitap живе у вільних місцях наявних статичних змінних цього екрана --
 *   contactName[17] -- клавіша, що гортається (smsMt_t.key), [18] -- номер у циклі (smsMt_t.idx), [19] -- режим набору;
 *   contactName[16] лишається NUL-термінатором (cap = 16, символ перегляду стоїть не далі [15]);
 *   tmpContact.NOT_IN_CODEPLUGDATA_indexNumber (цим екраном не використовується; у кодплуг не пишеться) -- ticksGetMillis() останнього натискання.
 * Набір ЗАВЖДИ додає в кінець назви (multitap ведеться по довжині підтвердженого тексту); стирання -- SK2+ЛІВОРУЧ, як у стоковому редакторі. */
#define CD_NAME_CAP   16
#define CD_MT_KEY     contactName[17]
#define CD_MT_IDX     contactName[18]
#define CD_MT_MODE    contactName[19]
#define CD_MT_MS      ((uint32_t)tmpContact.NOT_IN_CODEPLUGDATA_indexNumber)

static void cdMtReset(void)
{
	CD_MT_KEY = 0;
	CD_MT_IDX = 0;
	CD_MT_MODE = (char)((contactName[0] == 0) ? SMS_MT_UA_UP : SMS_MT_UA_LO);   /* порожня назва починається з великої */
	tmpContact.NOT_IN_CODEPLUGDATA_indexNumber = 0;
}

static uint8_t cdMtMode(void)
{
	return (((uint8_t)CD_MT_MODE) < SMS_MT_MODES) ? (uint8_t)CD_MT_MODE : (uint8_t)SMS_MT_DEFAULT;
}

/* Підтвердити символ, що гортається (якщо є), і поставити курсор у кінець (не далі 15, як у стоковому редакторі). */
static void cdMtCommit(void)
{
	if (CD_MT_KEY != 0)
	{
		smsMt_t mt = { CD_MT_KEY, (uint8_t)CD_MT_IDX };
		int16_t p = (int16_t)(strlen(contactName) - 1U);   /* символ перегляду -- в останній позиції рядка */

		smsMtCommit(&mt, &p);
		CD_MT_KEY = 0;
		CD_MT_IDX = 0;
		namePos = (p > 15) ? 15 : p;
	}
}

static bool cdIsMtKey(uint32_t key)
{
	return ((key >= '0') && (key <= '9')) || (key == '*') || (key == KEY_HASH);
}

/* Текстова клавіша (або "#") у рядку "Назва". */
static void cdNameKey(uiEvent_t *ev)
{
	char k = (char)ev->keys.key;
	uint8_t mode = cdMtMode();
	smsMt_t mt = { CD_MT_KEY, (uint8_t)CD_MT_IDX };
	int16_t p = (int16_t)strlen(contactName);

	if ((ev->keys.event & KEY_MOD_LONG) || ((ev->keys.event & KEY_MOD_PRESS) == 0))
	{
		return;
	}

	if (mt.key != 0)
	{
		p--;   /* підтверджений текст закінчується перед символом, що гортається */
	}

	if (k == KEY_HASH)
	{
		smsMtCommit(&mt, &p);
		CD_MT_MODE = (char)smsMtModeNext(mode);
	}
	else if (smsMtKeyMap(mode, k) != NULL)
	{
		uint32_t now = ticksGetMillis();
		bool same = (mt.key == k) && ((now - CD_MT_MS) < SMS_MT_TIMEOUT_MS);

		if (smsMtKey(&mt, mode, k, same, contactName, &p, CD_NAME_CAP) == 1)
		{
			tmpContact.NOT_IN_CODEPLUGDATA_indexNumber = (int)now;
		}
	}
	else
	{
		return;
	}

	CD_MT_KEY = mt.key;
	CD_MT_IDX = (char)mt.idx;
	namePos = (p > 15) ? 15 : p;
	updateCursor(true);
	updateScreen(false, false);
}

/* Індикатор режиму набору (плашка), підказка "#:режим" і лічильник символів -- внизу екрана, під списком (4 рядки його не досягають). */
static void cdModeChip(void)
{
	const char *lbl = smsMtModeLabel(cdMtMode());
	int16_t chipW = (int16_t)((strlen(lbl) * 6U) + 4U);
	char cnt[12];

	displayFillRect(0, 108, chipW, 10, false);
	displayPrintCore(2, 109, lbl, FONT_SIZE_1, TEXT_ALIGN_LEFT, true);
	displayPrintAt((uint16_t)(chipW + 4), 109, APRSM_L_MTHINT, FONT_SIZE_1);
	snprintf(cnt, sizeof(cnt), "%d/%d", (int)strlen(contactName), CD_NAME_CAP);
	displayPrintCore(0, 109, cnt, FONT_SIZE_1, TEXT_ALIGN_RIGHT, false);
}
#endif

enum
{
	CONTACT_DETAILS_NAME = 0,
	CONTACT_DETAILS_TG,
	CONTACT_DETAILS_CALLTYPE,
	CONTACT_DETAILS_TS,
	NUM_CONTACT_DETAILS_ITEMS
};// The last item in the list is used so that we automatically get a total number of items in the list

static int menuContactDetailsState;
static int menuContactDetailsTimeout;

enum
{
	MENU_CONTACT_DETAILS_DISPLAY = 0,
	MENU_CONTACT_DETAILS_SAVED,
	MENU_CONTACT_DETAILS_EXISTS,
	MENU_CONTACT_DETAILS_FULL
};

menuStatus_t menuContactDetails(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
		menuContactDetailsTimeout = 0;

		callTypeString[0] = currentLanguage->group;
		callTypeString[1] = currentLanguage->private;
		callTypeString[2] = currentLanguage->all;

		voicePromptsInit();

		if (uiDataGlobal.currentSelectedContactIndex == 0)
		{
			contactDetailsIndex = codeplugContactGetFreeIndex();
			tmpContact.name[0] = 0x00;
			tmpContact.callType = CONTACT_CALLTYPE_TG;
			tmpContact.reserve1 = 0xff;
			tmpContact.tgNumber = 0;
			digits[0] = 0x00;
			memset(contactName, 0, 20);
			namePos = 0;
			numPos = 0;
#if defined(APRS_R21_NAMES)
			cdMtReset();
#endif

			if (contactDetailsIndex == 0)
			{
				voicePromptsAppendLanguageString(currentLanguage->list_full);
			}
			else
			{
				voicePromptsAppendLanguageString(currentLanguage->new_contact);
			}
		}
		else
		{
			contactDetailsIndex = contactListContactData.NOT_IN_CODEPLUGDATA_indexNumber;
			memcpy(&tmpContact, &contactListContactData, CONTACT_DATA_STRUCT_SIZE);
			itoa(tmpContact.tgNumber, digits, 10);
#if defined(APRS_R21_NAMES)
			/* R23 Y2.5: назву з CPS (GBK) показуємо вже перекодованою в cp1251, інакше вона відкрилась би кракозябрами, а будь-яка правка зіпсувала б GBK-пари */
			codeplugUtilConvertBufToDisplayString(tmpContact.name, contactName, 16);
#else
			codeplugUtilConvertBufToString(tmpContact.name, contactName, 16);
#endif
			namePos = strlen(contactName);
			numPos = 0;
#if defined(APRS_R21_NAMES)
			cdMtReset();
#endif
		}

		menuContactDetailsState = (contactDetailsIndex == 0) ? MENU_CONTACT_DETAILS_FULL : MENU_CONTACT_DETAILS_DISPLAY;
		menuDataGlobal.currentItemIndex = CONTACT_DETAILS_NAME;
		menuDataGlobal.numItems = NUM_CONTACT_DETAILS_ITEMS;

		updateScreen(isFirstRun, true);
		updateCursor(true);

		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}
	else
	{
		menuContactDetailsExitCode = MENU_STATUS_SUCCESS;

#if defined(APRS_R21_NAMES)
		/* R23 Y2: символ, що гортається, підтверджується сам за SMS_MT_TIMEOUT_MS (як у "Нове повідомлення") */
		if ((menuContactDetailsState == MENU_CONTACT_DETAILS_DISPLAY) && (CD_MT_KEY != 0) && ((ticksGetMillis() - CD_MT_MS) >= SMS_MT_TIMEOUT_MS))
		{
			cdMtCommit();
			updateScreen(false, false);
		}
#endif
		updateCursor(false);
		if (ev->hasEvent || (menuContactDetailsTimeout > 0))
		{
			handleEvent(ev);
		}
	}
	return menuContactDetailsExitCode;
}

static void updateCursor(bool moved)
{
	// Only display the cursor when the fields are displayed
	if (menuContactDetailsState == MENU_CONTACT_DETAILS_DISPLAY)
	{
		displayThemeApply(THEME_ITEM_BG, THEME_ITEM_BG_MENU_ITEM_SELECTED);

		switch (menuDataGlobal.currentItemIndex)
		{
			case CONTACT_DETAILS_NAME:
				menuUpdateCursor(namePos, moved, true);
				break;

			case CONTACT_DETAILS_TG:
				menuUpdateCursor(numPos, moved, true);
				break;
		}

		displayThemeResetToDefault();
	}
}

static void updateScreen(bool isFirstRun, bool allowedToSpeakUpdate)
{
	int mNum = 0;
	char buf[SCREEN_LINE_BUFFER_SIZE];
	const char *leftSide = NULL;// initialise to please the compiler
	const char *leftSideConst = NULL;// initialise to please the compiler
	voicePrompt_t leftSidePrompt;
	const char *rightSideConst = NULL;// initialise to please the compiler
	char rightSideVar[SCREEN_LINE_BUFFER_SIZE];
	voicePrompt_t rightSidePrompt;

	displayClearBuf();

	if (tmpContact.name[0] == 0x00)
	{
		snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s", currentLanguage->new_contact);
	}
	else
	{
		codeplugUtilConvertBufToDisplayString(tmpContact.name, buf, 16);
	}

	menuDisplayTitle(buf);

#if defined(APRS_R21_NAMES)
	keypadAlphaEnable = false;   /* R23 Y2: набір назви -- власний multitap (cdNameKey), клавіші приходять сирими */
#else
	if (menuDataGlobal.currentItemIndex == CONTACT_DETAILS_NAME)
	{
		keypadAlphaEnable = true;
	}
	else
	{
		keypadAlphaEnable = false;
	}
#endif

	switch (menuContactDetailsState)
	{
		case MENU_CONTACT_DETAILS_DISPLAY:
			for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
			{
				mNum = menuGetMenuOffset(NUM_CONTACT_DETAILS_ITEMS, i);
				if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY)
				{
					continue;
				}
				else if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)
				{
					break;
				}

				buf[0] = 0;
				leftSide = NULL;
				leftSideConst = NULL;
				leftSidePrompt = PROMPT_SILENCE;
				rightSideConst = NULL;
				rightSideVar[0] = 0;
				rightSidePrompt = PROMPT_SILENCE;// use PROMPT_SILENCE as flag that the unit has not been set

				switch (mNum)
				{
					case CONTACT_DETAILS_NAME:
						strncpy(rightSideVar, contactName, SCREEN_LINE_BUFFER_SIZE);
						break;

					case CONTACT_DETAILS_TG:
						{
							int nLen = 0;

							switch (tmpContact.callType)
							{
								case CONTACT_CALLTYPE_TG:
									leftSide = currentLanguage->tg;
									leftSidePrompt = PROMPT_TALKGROUP;

									if (!(nLen = strlen(digits)))
									{
										rightSideConst = currentLanguage->none;
									}
									else
									{
										snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%s", digits);
									}
									break;

								case CONTACT_CALLTYPE_PC: // Private
									leftSide = currentLanguage->pc;
									leftSideConst = currentLanguage->private_call;

									if (!(nLen = strlen(digits)))
									{
										rightSideConst = currentLanguage->none;
									}
									else
									{
										snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%s", digits);
									}
									break;

								case CONTACT_CALLTYPE_ALL: // All Call
									leftSide = currentLanguage->all;
									snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%u", MAX_TG_OR_PC_VALUE);
									leftSideConst = currentLanguage->all_call;
									break;
							}

							if (i == 0)
							{
								numPos = strlen(leftSide) + 1 + (nLen ? nLen : strlen(rightSideVar));
							}
						}
						break;

					case CONTACT_DETAILS_CALLTYPE:
						leftSide = currentLanguage->type;
						leftSideConst = currentLanguage->type;
						snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%s", callTypeString[tmpContact.callType]);

						switch (tmpContact.callType)
						{
							case CONTACT_CALLTYPE_TG:
								rightSidePrompt = PROMPT_TALKGROUP;
								break;

							case CONTACT_CALLTYPE_PC: // Private
								rightSideConst = currentLanguage->private_call;
								break;

							case CONTACT_CALLTYPE_ALL: // All Call
								rightSideConst = currentLanguage->all_call;
								break;
						}
						break;

					case CONTACT_DETAILS_TS:
						leftSide = currentLanguage->timeSlot;

						switch (tmpContact.reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_MASK)
						{
							case 1:
							case 3:
								snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%s", currentLanguage->none);
								rightSideConst = currentLanguage->none;
								break;

							case 0:
								snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%u", 1);
								break;

							case 2:
								snprintf(rightSideVar, SCREEN_LINE_BUFFER_SIZE, "%u", 2);
								break;
						}
						break;
				}

				if (leftSide != NULL)
				{
					snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s:%s", leftSide, (rightSideVar[0] ? rightSideVar : (rightSideConst ? rightSideConst : "")));
				}
				else
				{
					strcpy(buf, rightSideVar);
				}

				if ((i == 0) && (allowedToSpeakUpdate))
				{
					if (!isFirstRun)
					{
						voicePromptsInit();
					}

					if (leftSidePrompt != PROMPT_SILENCE)
					{
						voicePromptsAppendPrompt(leftSidePrompt);
						voicePromptsAppendPrompt(PROMPT_SILENCE);
					}
					else if ((leftSideConst != NULL) || (leftSide != NULL))
					{
						voicePromptsAppendLanguageString((leftSideConst ? leftSideConst : leftSide));
					}

					if (rightSidePrompt != PROMPT_SILENCE)
					{
						voicePromptsAppendPrompt(rightSidePrompt);
					}
					else if (rightSideConst != NULL)
					{
						voicePromptsAppendLanguageString(rightSideConst);
					}
					else if (rightSideVar[0] != 0)
					{
						voicePromptsAppendString(rightSideVar);
					}
					else if ((rightSideVar[0] == 0) && (menuDataGlobal.currentItemIndex == CONTACT_DETAILS_NAME))
					{
						voicePromptsAppendLanguageString(currentLanguage->name);
						voicePromptsAppendPrompt(PROMPT_SILENCE);
						voicePromptsAppendLanguageString(currentLanguage->none);
					}

					promptsPlayNotAfterTx();
				}

				switch(mNum)
				{
					case CONTACT_DETAILS_NAME:
						menuDisplayEntry(i, mNum, buf, -1, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
						break;

					default:
						menuDisplayEntry(i, mNum, buf, (strlen(leftSide) + 1), THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
						break;
				}
			}
			break;

		case MENU_CONTACT_DETAILS_SAVED:
			displayPrintCentered(16, currentLanguage->contact_saved, FONT_SIZE_3);
			displayDrawChoice(CHOICE_OK, false);
			break;

		case MENU_CONTACT_DETAILS_EXISTS:
			displayPrintCentered(16, currentLanguage->duplicate, FONT_SIZE_3);
			displayPrintCentered(32, currentLanguage->contact, FONT_SIZE_3);
			displayDrawChoice(CHOICE_OK, false);
			break;

		case MENU_CONTACT_DETAILS_FULL:
			displayPrintCentered(16, currentLanguage->list_full, FONT_SIZE_3);
			displayDrawChoice(CHOICE_OK, false);
			promptsPlayNotAfterTx();
			break;
	}
#if defined(APRS_R21_NAMES)
	if ((menuContactDetailsState == MENU_CONTACT_DETAILS_DISPLAY) && (menuDataGlobal.currentItemIndex == CONTACT_DETAILS_NAME))
	{
		cdModeChip();   /* R23 Y2.2: режим набору видно, назву не перекриває */
	}
#endif
	displayRender();
}

static void handleEvent(uiEvent_t *ev)
{
	dmrIdDataStruct_t foundRecord;
	char buf[SCREEN_LINE_BUFFER_SIZE];
	int sLen = strlen(digits);

	if (ev->events & BUTTON_EVENT)
	{
		if (repeatVoicePromptOnSK1(ev))
		{
			return;
		}
	}

	if ((ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		updateScreen(false, false);
		return;
	}

	// Not entering a frequency numeric digit
	bool allowedToSpeakUpdate = true;

	switch (menuContactDetailsState)
	{
		case MENU_CONTACT_DETAILS_DISPLAY:
			if (ev->events & KEY_EVENT)
			{
#if defined(APRS_R21_NAMES)
				/* R23 Y2: будь-яка не текстова клавіша (стрілки, GREEN, RED, SK) спершу підтверджує символ, що гортається */
				if ((CD_MT_KEY != 0) && (ev->keys.key != 0) && (ev->keys.event & KEY_MOD_PRESS) && (cdIsMtKey(ev->keys.key) == false))
				{
					cdMtCommit();
				}
#endif
				if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
				{
					menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, NUM_CONTACT_DETAILS_ITEMS);
					updateScreen(false, true);
					menuContactDetailsExitCode |= MENU_STATUS_LIST_TYPE;
				}
				else if (KEYCHECK_PRESS(ev->keys, KEY_UP))
				{
					menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, NUM_CONTACT_DETAILS_ITEMS);
					updateScreen(false, true);
					menuContactDetailsExitCode |= MENU_STATUS_LIST_TYPE;
				}
				else if (KEYCHECK_LONGDOWN(ev->keys, KEY_RIGHT) || KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_RIGHT))
				{
					if (menuDataGlobal.currentItemIndex == CONTACT_DETAILS_NAME)
					{
						namePos = strlen(contactName);
						updateScreen(false, !voicePromptsIsPlaying());
					}
				}
				else if (KEYCHECK_SHORTUP(ev->keys, KEY_RIGHT)
#if defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
						|| KEYCHECK_SHORTUP(ev->keys, KEY_ROTARY_INCREMENT)
#endif
				)
				{
					switch(menuDataGlobal.currentItemIndex)
					{
						case CONTACT_DETAILS_NAME:
							moveCursorRightInString(contactName, &namePos, 16, BUTTONCHECK_DOWN(ev, BUTTON_SK2));
							updateCursor(true);
							allowedToSpeakUpdate = (strlen(contactName) == 0);
							break;

						case CONTACT_DETAILS_TG:
							break;

						case CONTACT_DETAILS_CALLTYPE:
							if (tmpContact.callType < CONTACT_CALLTYPE_ALL)
							{
								tmpContact.callType++;
							}
							itoa(tmpContact.callType == CONTACT_CALLTYPE_ALL ? MAX_TG_OR_PC_VALUE : tmpContact.tgNumber, digits, 10);
							if (tmpContact.tgNumber == 0)
							{
								digits[0] = 0;
							}
							break;

						case CONTACT_DETAILS_TS:
							if ((tmpContact.reserve1 & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE) && ((tmpContact.reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK) == 0))
							{
								tmpContact.reserve1 |= (CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE | CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK);
							}

							if (tmpContact.reserve1 & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE || ((tmpContact.reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_MASK) == 0x00))
							{
								tmpContact.reserve1 &= ~CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;
								tmpContact.reserve1 ^= CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK;
							}
							break;
					}
					updateScreen(false, allowedToSpeakUpdate);
				}
				else if (KEYCHECK_LONGDOWN(ev->keys, KEY_LEFT) || KEYCHECK_LONGDOWN_REPEAT(ev->keys, KEY_LEFT))
				{
					if (menuDataGlobal.currentItemIndex == CONTACT_DETAILS_NAME)
					{
						namePos = 0;
						updateScreen(false, !voicePromptsIsPlaying());
					}
				}
				else if (KEYCHECK_SHORTUP(ev->keys, KEY_LEFT)
#if defined(PLATFORM_RT84_DM1701) || defined(PLATFORM_MD2017)
						|| KEYCHECK_SHORTUP(ev->keys, KEY_ROTARY_DECREMENT)
#endif
				)
				{
					switch(menuDataGlobal.currentItemIndex)
					{
						case CONTACT_DETAILS_NAME:
							moveCursorLeftInString(contactName, &namePos, BUTTONCHECK_DOWN(ev, BUTTON_SK2));
							updateCursor(true);
							allowedToSpeakUpdate = (strlen(contactName) == 0);
							break;

						case CONTACT_DETAILS_TG:
							if (sLen > 0)
							{
								digits[sLen - 1] = 0x00;
							}
							updateCursor(true);
							break;

						case CONTACT_DETAILS_CALLTYPE:
							if (tmpContact.callType > 0)
							{
								tmpContact.callType--;
							}
							itoa(tmpContact.callType == CONTACT_CALLTYPE_ALL ? MAX_TG_OR_PC_VALUE : tmpContact.tgNumber, digits, 10);
							if (tmpContact.tgNumber == 0)
							{
								digits[0] = 0;
							}
							break;

						case CONTACT_DETAILS_TS:
							if (((tmpContact.reserve1 & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE) == 0x0) || ((tmpContact.reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_MASK) == 0x00))
							{
								if (((tmpContact.reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_MASK) == 0x00))
								{
									tmpContact.reserve1 ^= CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;
								}
								else
								{
									tmpContact.reserve1 ^= CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK;
								}
							}
							break;
					}
					updateScreen(false, allowedToSpeakUpdate);
				}
				else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
				{
					if (tmpContact.callType == CONTACT_CALLTYPE_ALL)
					{
						tmpContact.tgNumber = MAX_TG_OR_PC_VALUE;
					}
					else
					{
						tmpContact.tgNumber = (uint32_t)atoi(digits);
					}

					if ((tmpContact.tgNumber >= MIN_TG_OR_PC_VALUE) && (tmpContact.tgNumber <= MAX_TG_OR_PC_VALUE))
					{
						codeplugUtilConvertStringToBuf(contactName, tmpContact.name, 16);
						if ((contactDetailsIndex >= CODEPLUG_CONTACTS_MIN) && (contactDetailsIndex <= CODEPLUG_CONTACTS_MAX))
						{
							if (tmpContact.name[0] == 0xff)
							{
								if (tmpContact.callType == CONTACT_CALLTYPE_PC)
								{
									if (dmrIDLookup(tmpContact.tgNumber, &foundRecord))
									{
										codeplugUtilConvertStringToBuf(foundRecord.text, tmpContact.name, 16);
									}
									else
									{
										snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s %u", currentLanguage->pc, tmpContact.tgNumber);
										codeplugUtilConvertStringToBuf(buf, tmpContact.name, 16);
									}
								}
								else
								{
									snprintf(buf, SCREEN_LINE_BUFFER_SIZE, "%s %u", currentLanguage->tg, tmpContact.tgNumber);
									codeplugUtilConvertStringToBuf(buf, tmpContact.name, 16);
								}
							}

							voicePromptsInit();
							if (contactIsNewOrAtSameIndex(&tmpContact, contactDetailsIndex))
							{
								codeplugContactSaveDataForIndex(contactDetailsIndex, &tmpContact);

								menuContactDetailsTimeout = 2000;
								menuContactDetailsState = MENU_CONTACT_DETAILS_SAVED;
								voicePromptsAppendLanguageString(currentLanguage->contact_saved);
							}
							else
							{
								menuContactDetailsTimeout = 2000;
								menuContactDetailsState = MENU_CONTACT_DETAILS_EXISTS;
								voicePromptsAppendLanguageString(currentLanguage->duplicate);
							}
							voicePromptsPlay();
						}
					}
					updateScreen(false, allowedToSpeakUpdate);
					return;
				}
				else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
				{
					menuSystemPopPreviousMenu();
					return;
				}
				else
				{
					if (menuDataGlobal.currentItemIndex == CONTACT_DETAILS_TG)
					{
						if (tmpContact.callType != CONTACT_CALLTYPE_ALL)
						{
							// Add a digit
							if (sLen < NUM_PC_OR_TG_DIGITS)
							{
								int keyval = menuGetKeypadKeyValue(ev, true);

								char c[2] = {0, 0};

								if (keyval != 99)
								{
									c[0] = keyval + '0';
									strcat(digits, c);
								}
								updateScreen(false, allowedToSpeakUpdate);
							}
						}
					}
					else if (menuDataGlobal.currentItemIndex == CONTACT_DETAILS_NAME)
					{
#if defined(APRS_R21_NAMES)
						cdNameKey(ev);   /* R23 Y2: multitap замість стокового латинського введення */
#else
						if ((ev->keys.event == KEY_MOD_PREVIEW) && (namePos < 16))
						{
							contactName[namePos] = ev->keys.key;
							updateCursor(true);
							announceChar(ev->keys.key);
							updateScreen(false, false);
						}
						else if ((ev->keys.event == KEY_MOD_PRESS) && (namePos < 16))
						{
							contactName[namePos] = ev->keys.key;
							if (namePos < strlen(contactName) && namePos < 15)
							{
								namePos++;
							}
							updateCursor(true);
							announceChar(ev->keys.key);
							updateScreen(false, false);
						}
#endif
					}
				}
			}
			break;

		case MENU_CONTACT_DETAILS_SAVED:
			menuContactDetailsTimeout--;
			if ((menuContactDetailsTimeout == 0) || KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) || KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				menuContactDetailsTimeout = 0;
				menuSystemPopPreviousMenu();
				return;
			}
			break;

		case MENU_CONTACT_DETAILS_EXISTS:
			menuContactDetailsTimeout--;
			if ((menuContactDetailsTimeout == 0) || KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) || KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				menuContactDetailsTimeout = 0;
				menuContactDetailsState = MENU_CONTACT_DETAILS_DISPLAY;
				updateScreen(false, allowedToSpeakUpdate);
			}
			break;

		case MENU_CONTACT_DETAILS_FULL:
			if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) || KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				menuSystemPopPreviousMenu();
			}
			break;
	}
}

// Check if the contact ct already exists in the codeplug contact list, at the same index, or if it's new
// Used to avoid duplicates
// Three contacts with the same TG/TC number can exist: no TS override, or TS1 || TS2 set
static bool contactIsNewOrAtSameIndex(CodeplugContact_t *ct, int index)
{
	CodeplugContact_t ct2;
	uint8_t ctTs = (((ct->reserve1 & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE) == 0x00) ? (((ct->reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK) >> 1) + 1) : 0);

	int ct2Index = codeplugContactIndexByTGorPC(ct->tgNumber, ct->callType, &ct2, ctTs);

	if ((ct2Index == -1) || // Doesn't exist yet
			(ct2.NOT_IN_CODEPLUGDATA_indexNumber == index)) // We are editing the contact, this is not a duplicate
	{
		return true;
	}

	if (ctTs == 0) // the contact don't have an override, so we need the two possible overridden contacts
	{
		// At least one contact exist, but we need to check TS override
		do
		{
			// Compare the TS override values
			if ((((ct2.reserve1 & CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE) == 0x00) ? (((ct2.reserve1 & CODEPLUG_CONTACT_FLAG_TS_OVERRIDE_TIMESLOT_MASK) >> 1) + 1) : 0) == ctTs)
			{
				// We are editing the contact, this is not a duplicate
				if (ct2.NOT_IN_CODEPLUGDATA_indexNumber == index)
				{
					return true;
				}

				return false;
			}

			// Pick the next available and identical (by tgpc, type) contact in the list
			ct2Index = codeplugContactIndexByTGorPCFromNumber((ct2Index + 1), ct->tgNumber, ct->callType, &ct2, ctTs);
		}
		while (ct2Index != -1);

		return true;
	}

	return false;
}

