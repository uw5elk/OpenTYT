/*
 * uiSmsKeys.c -- підказка літер клавіші і шпаргалка розкладки multitap (ui7). Опис -- у uiSmsKeys.h.
 * Код перенесено з menuMessages.c (composeKeyHint(), layoutUpdate()) без змін поведінки.
 */
#include "user_interface/uiSmsKeys.h"

#if (defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)) || defined(APRS_RX)

#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "user_interface/menuSystem.h"
#include "functions/sms_multitap.h"
#include <string.h>

void uiSmsKeyHint(uint8_t mode, char key, uint8_t idx, int16_t x, int16_t y)
{
	const char *map = smsMtKeyMap(mode, key);
	if (map == NULL) { return; }
	int n = (int)strlen(map);
	int cells = (DISPLAY_SIZE_X - x) / 8;
	int step = ((2 * n - 1) <= cells) ? 2 : 1;
	int start = 0;
	if ((step == 1) && (n > cells))
	{
		start = (int)idx - cells / 2;
		if (start > n - cells) { start = n - cells; }
		if (start < 0) { start = 0; }
	}
	for (int k = start; (k < n) && (((k - start) * step) < cells); k++)
	{
		char one[2] = { (map[k] == ' ') ? '_' : map[k], 0 };
		int16_t cx = (int16_t)(x + (k - start) * step * 8);
		if (k == (int)idx)
		{
			displayFillRect(cx, y, 8, 8, false);
			displayPrintCore(cx, y, one, FONT_SIZE_2, TEXT_ALIGN_LEFT, true);
		}
		else
		{
			displayPrintCore(cx, y, one, FONT_SIZE_2, TEXT_ALIGN_LEFT, false);
		}
	}
}

void uiSmsKeyLayoutDraw(uint8_t mode, const char *title, const char *hint)
{
	static const char keys[] = "1234567890*";

	displayClearBuf();
	menuDisplayTitle(title);

	for (int r = 0; keys[r] != 0; r++)
	{
		char line[28];
		const char *map = smsMtKeyMap(mode, keys[r]);
		int n = (map != NULL) ? (int)strlen(map) : 0;
		int step = ((2 + 2 * n - 1) <= 26) ? 2 : 1;
		int p = 0, k = 0;
		line[p++] = keys[r];
		line[p++] = ' ';
		for (; (k < n) && (p < 26); k++)
		{
			if ((step == 2) && (k > 0)) { line[p++] = ' '; }
			line[p++] = (map[k] == ' ') ? '_' : map[k];
		}
		if (k < n) { line[25] = '>'; p = 26; }   /* не влізло -- позначка, що є ще */
		line[p] = 0;
		displayPrintCore(2, (int16_t)(15 + r * 9), line, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);
	}
	displayPrintCentered(117, hint, FONT_SIZE_1);
}

#endif
