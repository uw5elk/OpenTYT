/*
 * menuAESKeys.c — on-radio management of the DMRA AES-256 key store.
 *
 * Lets the user enter/replace/clear the AES key slots and pick the global TX key,
 * all without a PC. (Per-channel privacy is set in the Channel Details menu.)
 * Keys are stored in the same OpenGD77 custom-data "AESK" block
 * (SPI-flash 0x20000) the host aes_key_store.py / the CHIRP module use, so the
 * format is shared (see crypto/dmr_aes_hook.c). Key material is never displayed.
 *
 * This whole file compiles to nothing unless built with -DENABLE_AES, so stock
 * builds are byte-identical. Persistent menu state lives in CCM (.aes_ccmram) — not
 * required (the AMBE codec addresses its buffers via the pointer passed in r1, so
 * its RAM placement floats freely), just tidy: it keeps this state alongside the
 * other AES state and out of scarce main RAM. CCM is not zeroed at boot, so all of
 * it is initialised on isFirstRun before use.
 *
 * LEGAL: encrypted voice is illegal on amateur bands in most jurisdictions.
 */

#include "user_interface/uiGlobals.h"
#include "user_interface/menuSystem.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/uiUtilities.h"
#include "functions/codeplug.h"
#include "functions/settings.h"
#include "crypto/dmr_aes.h"
#include "crypto/dmr_aes_hook.h"
#include <string.h>

#if defined(ENABLE_AES)

#include "functions/aes_key_name.h"
#if defined(LANGUAGE_BUILD_UKRAINIAN)
#include "user_interface/languages/aeskeys_ua.h"   /* R96/А3: AESK_LIST_FMT (захист від подвійного включення є) */
#endif
#if defined(AES_KEY_NAMES_ENABLED)
#include "user_interface/uiNameEditor.h"
#include "user_interface/languages/aeskeys_ua.h"
/* R64C: стан редактора імені -- у спільному буфері uiDataGlobal.MessageBox.message (нової RAM/CCM немає): розкладка в uiNameEditor.h; [35] = номер ключа (1..15). */
#define AESK_ED_BUF     (uiDataGlobal.MessageBox.message)
#define AESK_ED_KEYID   (AESK_ED_BUF[35])
#define AESK_ED_ON()    (NAME_ED_ACTIVE(AESK_ED_BUF) == 1)
#endif

// List layout: 15 key-slot rows (keyId 1..15). Global TX-key рядок прибрано (2026-09-11):
// шифрування вибирається лише в налаштуваннях каналу, за замовчуванням вимкнено.
#define AES_NUM_KEYS        15
#define AES_NUM_ITEMS       AES_NUM_KEYS

// Hex editor grid (160x128 colour screen). Pixel coords; tweak on hardware if needed.
#define GRID_COLS    16
#define GRID_ROWS    4
#define GRID_X0      16
#define GRID_Y0      26
#define GRID_CHARW   8     // FONT_SIZE_2 = font_8x8
#define GRID_ROWH    14

// Persistent across tick calls. In CCM (NOT auto-zeroed at boot) -> fully
// initialised on isFirstRun before anything reads it.
static struct
{
	uint16_t keyMask;     // bit k set => keyId k (1..15) has a stored key
	bool     editing;     // hex editor active
	uint8_t  editKeyId;   // key id being edited (1..15)
	int16_t  editPos;     // cursor nibble 0..63
	uint8_t  nib[64];     // editor nibble buffer (cleared after save/cancel)
} s_aes DMR_AES_CCM;   /* CCM-INIT(menuAESKeys) -- усі поля виставляються на isFirstRun */
// NB: keep ALL persistent menu state in CCM (above). Any net-new main-RAM .bss
// shifts the AMBE codec's hardcoded ambebuffer_* addresses and breaks DMR voice,
// so the per-tick exit code is a LOCAL threaded through handleEvent, not a static.

static void updateScreen(void);
static void handleEvent(uiEvent_t *ev, menuStatus_t *exitCode);
static void editorUpdateScreen(void);
static void editorHandleEvent(uiEvent_t *ev);
#if defined(AES_KEY_NAMES_ENABLED)
static void nameDraw(void);
static void nameOpen(int keyId);
static void nameHandleEvent(uiEvent_t *ev);
#endif

static char hexChar(uint8_t nibble)
{
	return (nibble < 10) ? (char)('0' + nibble) : (char)('A' + nibble - 10);
}

menuStatus_t menuAESKeys(uiEvent_t *ev, bool isFirstRun)
{
	if (isFirstRun)
	{
#if defined(AES_KEY_NAMES_ENABLED)
		nameEdClose(AESK_ED_BUF);   // буфер -- чужа пам'ять: редактор імені закрито
#endif
		s_aes.editing  = false;
		s_aes.editPos  = 0;
		s_aes.editKeyId = 0;
		memset(s_aes.nib, 0, sizeof s_aes.nib);

		s_aes.keyMask  = dmrAesGetKeyMask();

		menuDataGlobal.currentItemIndex = 0;
		menuDataGlobal.numItems = AES_NUM_ITEMS;

		updateScreen();
		return (MENU_STATUS_LIST_TYPE | MENU_STATUS_SUCCESS);
	}

	menuStatus_t exitCode = MENU_STATUS_SUCCESS;

	if (ev->hasEvent)
	{
		// ui3 (2026-10-05): FUNC_REDRAW після закриття картки сповіщення (гучність тощо) --
		// перемалювати поточний екран; інакше картка висить до першої клавіші.
		if ((ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
		{
#if defined(AES_KEY_NAMES_ENABLED)
			if (AESK_ED_ON()) { nameDraw(); return exitCode; }
#endif
			if (s_aes.editing) { editorUpdateScreen(); } else { updateScreen(); }
			return exitCode;
		}
#if defined(AES_KEY_NAMES_ENABLED)
		if (AESK_ED_ON())
		{
			nameHandleEvent(ev);
			return exitCode;
		}
#endif
		if (s_aes.editing)
		{
			editorHandleEvent(ev);
		}
		else
		{
			handleEvent(ev, &exitCode);
		}
	}
	return exitCode;
}

static void updateScreen(void)
{
	char buf[16 + LANGUAGE_TEXTS_LENGTH];

	displayClearBuf();
#if defined(LANGUAGE_BUILD_UKRAINIAN)
	menuDisplayTitle(currentLanguage->aes_keys);   // R94: «Ключі AES» (той самий підпис, що в меню «Налаштування»)
#else
	menuDisplayTitle("AES Keys");
#endif

	for (int i = MENU_START_ITERATION_VALUE; i <= MENU_END_ITERATION_VALUE; i++)
	{
		int mNum = menuGetMenuOffset(AES_NUM_ITEMS, i);
		const char *value;
#if defined(LANGUAGE_BUILD_UKRAINIAN)
		bool keyIsSet = false;
#endif

		if (mNum == MENU_OFFSET_BEFORE_FIRST_ENTRY)
		{
			continue;
		}
		else if (mNum == MENU_OFFSET_AFTER_LAST_ENTRY)
		{
			break;
		}

		{
			int keyId = mNum + 1;
#if defined(LANGUAGE_BUILD_UKRAINIAN)
			// R96/А3: «Ключ N:» і галочка (записано) або «---» (порожньо); текст значення для записаного порожній -- галочку малюємо нижче
			keyIsSet = ((s_aes.keyMask & (1u << keyId)) != 0);
			value = keyIsSet ? "" : "---";
			snprintf(buf, sizeof buf, AESK_LIST_FMT "%s", keyId, value);
#else
			value = (s_aes.keyMask & (1u << keyId)) ? "set" : "---";
			snprintf(buf, sizeof buf, "Key %d:%s", keyId, value);
#endif
		}

		// Colour the value after the ':' like the other option menus.
		const char *colon = strchr(buf, ':');
		int optStart = colon ? (int)(colon - buf + 1) : 0;
#if defined(AES_KEY_NAMES_ENABLED)
		{
			// R64C: у ключа є власне ім'я -- «N ім'я:set» (ім'я скорочується до 11 символів, щоб рядок лишався в 18; двокрапка в імені не збиває колір значення).
			char nm[AESN_CHARS + 1U];
			int keyId = mNum + 1;

			if (dmrAesKeyNameGet((uint8_t)keyId, nm) != 0)
			{
				nm[11] = 0;
				snprintf(buf, sizeof buf, "%d %s:%s", keyId, nm, value);
				optStart = (int)strlen(buf) - (int)strlen(value);
			}
		}
#endif
		menuDisplayEntry(i, mNum, buf, optStart, THEME_ITEM_FG_MENU_ITEM, THEME_ITEM_FG_OPTIONS_VALUE, THEME_ITEM_BG);
#if defined(LANGUAGE_BUILD_UKRAINIAN)
		if (keyIsSet)
		{
			// та сама галочка, що в «Надісланих» (uiDrawTickMark), на місці значення; колір як у інших значень
			uiDrawTickMark((int16_t)(DISPLAY_X_POS_MENU_TEXT_OFFSET + (optStart * 8)), (int16_t)(DISPLAY_Y_POS_MENU_ENTRY_HIGHLIGHT + (i * MENU_ENTRY_HEIGHT)),
					THEME_ITEM_FG_OPTIONS_VALUE, (mNum == menuDataGlobal.currentItemIndex));
		}
#endif
	}

	displayRender();
}

static void handleEvent(uiEvent_t *ev, menuStatus_t *exitCode)
{
	if ((ev->events & KEY_EVENT) == 0)
	{
		return;
	}

	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		menuSystemMenuIncrement(&menuDataGlobal.currentItemIndex, AES_NUM_ITEMS);
		*exitCode |= MENU_STATUS_LIST_TYPE;
		updateScreen();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		menuSystemMenuDecrement(&menuDataGlobal.currentItemIndex, AES_NUM_ITEMS);
		*exitCode |= MENU_STATUS_LIST_TYPE;
		updateScreen();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		menuSystemPopPreviousMenu();
		return;
	}

	int idx = menuDataGlobal.currentItemIndex;

#if defined(AES_KEY_NAMES_ENABLED)
	// R64C: «#» (коротко) на ключі -- перейменувати (спільний редактор назви).
	if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH))
	{
		nameOpen(idx + 1);
		return;
	}
#endif

	// Усі рядки -- слоти ключів (1..15). Global TX key прибрано.
	{
		int keyId = idx + 1;

		// SK2 + GREEN clears the slot (deliberate combo guards against accidental wipe).
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN) && BUTTONCHECK_DOWN(ev, BUTTON_SK2))
		{
			dmrAesEnsureCustomDataRegion();
			dmrAesClearKey((uint8_t)keyId);
			s_aes.keyMask = dmrAesGetKeyMask();
			updateScreen();
			return;
		}
		// GREEN opens the hex editor to enter / replace the key.
		if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			s_aes.editing  = true;
			s_aes.editKeyId = (uint8_t)keyId;
			s_aes.editPos  = 0;
			memset(s_aes.nib, 0, sizeof s_aes.nib);
			editorUpdateScreen();
			return;
		}
	}
}

static void editorUpdateScreen(void)
{
	char line[GRID_COLS + 1];
	char title[20];

	displayClearBuf();
	snprintf(title, sizeof title, "Enter Key %d", s_aes.editKeyId);
	displayPrintCentered(2, title, FONT_SIZE_2);
	displayPrintCentered(14, "as in TYT CPS", FONT_SIZE_1);

	for (int r = 0; r < GRID_ROWS; r++)
	{
		for (int c = 0; c < GRID_COLS; c++)
		{
			line[c] = hexChar(s_aes.nib[r * GRID_COLS + c]);
		}
		line[GRID_COLS] = 0;
		displayPrintAt(GRID_X0, GRID_Y0 + r * GRID_ROWH, line, FONT_SIZE_2);
	}

	// Cursor box around the focused nibble.
	//
	// isInverted=true -- це ПЕРЕДНІЙ план: displayDrawRect зводиться до displayDrawFastHLine/
	// VLine, а ті інвертують прапорець усередині (HX8353E_display.c:430-438). З false рамка
	// малювалася кольором ТЛА, тобто курсора не було видно взагалі й при ручному введенні
	// ключа не читалось, який саме напівбайт зараз редагується.
	int cr = s_aes.editPos / GRID_COLS;
	int cc = s_aes.editPos % GRID_COLS;
	displayDrawRect(GRID_X0 + cc * GRID_CHARW - 1, GRID_Y0 + cr * GRID_ROWH - 2, GRID_CHARW + 1, FONT_SIZE_2_HEIGHT + 3, true);

	displayPrintCentered(88, "U/D:0-F  L/R:move", FONT_SIZE_1);
	displayPrintCentered(100, "0-9 type  GRN:save", FONT_SIZE_1);
	displayPrintCentered(112, "RED:cancel", FONT_SIZE_1);

	displayRender();
}

static void editorSave(void)
{
	uint8_t key[DMR_AES_KEY_BYTES];

	for (int i = 0; i < DMR_AES_KEY_BYTES; i++)
	{
		key[i] = (uint8_t)((s_aes.nib[2 * i] << 4) | s_aes.nib[2 * i + 1]);
	}

	dmrAesEnsureCustomDataRegion();
	dmrAesStoreKey(s_aes.editKeyId, key);   // also reloads the key store -> immediate effect, no reboot

	memset(key, 0, sizeof key);
	memset(s_aes.nib, 0, sizeof s_aes.nib);

	s_aes.keyMask = dmrAesGetKeyMask();
	s_aes.editing = false;
	updateScreen();
}

static void editorHandleEvent(uiEvent_t *ev)
{
	if ((ev->events & KEY_EVENT) == 0)
	{
		return;
	}

	if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		memset(s_aes.nib, 0, sizeof s_aes.nib);
		s_aes.editing = false;
		updateScreen();
		return;
	}
	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		editorSave();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_LEFT))
	{
		if (s_aes.editPos > 0) { s_aes.editPos--; }
		editorUpdateScreen();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT))
	{
		if (s_aes.editPos < 63) { s_aes.editPos++; }
		editorUpdateScreen();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_UP))
	{
		s_aes.nib[s_aes.editPos] = (uint8_t)((s_aes.nib[s_aes.editPos] + 1) & 0x0F);
		editorUpdateScreen();
		return;
	}
	if (KEYCHECK_PRESS(ev->keys, KEY_DOWN))
	{
		s_aes.nib[s_aes.editPos] = (uint8_t)((s_aes.nib[s_aes.editPos] + 15) & 0x0F);
		editorUpdateScreen();
		return;
	}
	if (KEYCHECK_SHORTUP_NUMBER(ev->keys))
	{
		s_aes.nib[s_aes.editPos] = (uint8_t)(ev->keys.key - '0');
		if (s_aes.editPos < 63) { s_aes.editPos++; }
		editorUpdateScreen();
		return;
	}
}

#if defined(AES_KEY_NAMES_ENABLED)
// ---- R64C: перейменування ключа ----
static void nameTitle(char *title, size_t len)
{
	snprintf(title, len, AESK_REN_TITLE_FMT, (int)AESK_ED_KEYID);
}

static void nameDraw(void)
{
	char title[24];

	nameTitle(title, sizeof title);
	nameEdDraw(AESK_ED_BUF, title);
}

static void nameOpen(int keyId)
{
	char nm[AESN_CHARS + 1U];

	(void)dmrAesKeyNameGet((uint8_t)keyId, nm);   // власного імені нема -- порожній рядок
	nameEdInit(AESK_ED_BUF, nm);
	AESK_ED_KEYID = (char)keyId;
	nameDraw();
}

static void nameClose(void)
{
	nameEdClose(AESK_ED_BUF);
	updateScreen();
}

static void nameHandleEvent(uiEvent_t *ev)
{
	char title[24];

	if ((ev->events & KEY_EVENT) == 0)
	{
		return;
	}

	nameTitle(title, sizeof title);
	if (nameEdSheetEvent(AESK_ED_BUF, title, ev))   /* R66B: шпаргалка розкладки (ВНИЗ) */
	{
		return;
	}

	if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
	{
		nameEdCommit(AESK_ED_BUF);
		if (dmrAesKeyNameSet((uint8_t)AESK_ED_KEYID, AESK_ED_BUF) != 0)
		{
			nameClose();
			uiNotificationShowShort(1500, AESK_MSG_RENAMED, true);
		}
		else
		{
			uiNotificationShowShort(1500, AESK_MSG_SAVE_ERR, true);   // лишаємось у редакторі: набране не втрачено
		}
	}
	else if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
	{
		nameClose();
	}
	else
	{
		nameTitle(title, sizeof title);
		(void)nameEdHandleKey(AESK_ED_BUF, title, ev);
	}
}
#endif // AES_KEY_NAMES_ENABLED

#endif // ENABLE_AES
