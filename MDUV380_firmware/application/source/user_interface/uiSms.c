/*
 * uiSms.c -- спільне для банера SMS і екранів «Повідомлень» (ui6). Опис -- у uiSms.h.
 *
 * Розбирання на рядки -- functions/sms_format.c (чистий, з хост-тестом), тут лише малювання,
 * тож банер, екран читання і гортання рахують рядки однаково.
 */
#include "user_interface/uiSms.h"

#if defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)

#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "functions/settings.h"
#include "functions/codeplug.h"
#include "functions/sms_format.h"
#include <stdio.h>
#include <string.h>

void uiSmsWhoStr(uint32_t id, int group, char *out, int outsz)
{
	char name[20];   /* contactIDLookup пише до 16 символів + NUL */

	if (outsz <= 0) { return; }
	if (contactIDLookup(id, group ? CONTACT_CALLTYPE_TG : CONTACT_CALLTYPE_PC, name))
	{
		snprintf(out, (size_t)outsz, "%s", name);
		return;
	}
	if (!group)
	{
		dmrIdDataStruct_t rec;
		if (dmrIDLookup(id, &rec) && (rec.text[0] != 0))
		{
			snprintf(out, (size_t)outsz, "%s", rec.text);
			return;
		}
	}
	snprintf(out, (size_t)outsz, group ? "TG %lu" : "%lu", (unsigned long)id);
}

int uiSmsTimeStr(uint32_t t, int mode, char *out, int outsz)
{
	/* «Зараз» -- той самий лічильник, що й годинник у шапці (RTC-переривання, stm32f4xx_it.c). */
	return smsTimeFormat(t, (uint32_t)uiDataGlobal.dateTimeSecs, smsTzOffsetSecs(nonVolatileSettings.timezone),
			mode, out, outsz);
}

int uiSmsDrawWrapped(const char *txt, int n, int cols, int first, int maxLines, int16_t x, int16_t y,
                     int16_t lineH, ucFont_t font, int ellipsis)
{
	char line[UI_SMS_COLS + 4];
	int pos = 0, idx = 0, ls, nx;

	if (cols > UI_SMS_COLS) { cols = UI_SMS_COLS; }
	while (pos < n)
	{
		int l = smsWrapLine(txt, n, pos, cols, &ls, &nx);
		if (nx <= pos) { break; }
		pos = nx;
		if (l <= 0) { continue; }

		if ((idx >= first) && (idx < first + maxLines))
		{
			memcpy(line, txt + ls, (size_t)l);
			line[l] = 0;
			/* Останній видимий рядок, а текст іще є: «...» -- щоб обрізання не виглядало
			 * повним текстом. Саме три крапки: одна читалась би як кінець речення. */
			if (ellipsis && (idx == first + maxLines - 1) && (smsWrapCount(txt + pos, n - pos, cols) > 0))
			{
				int cut = (l <= cols - 3) ? l : (cols - 3);
				if (cut < 0) { cut = 0; }
				line[cut] = '.'; line[cut + 1] = '.'; line[cut + 2] = '.'; line[cut + 3] = 0;
			}
			displayPrintCore(x, (int16_t)(y + (idx - first) * lineH), line, font, TEXT_ALIGN_LEFT, false);
		}
		idx++;
	}
	return idx;
}

#endif
