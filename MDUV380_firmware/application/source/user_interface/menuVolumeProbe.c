/*
 * menuVolumeProbe.c -- R77A: екран «Гучн. проба» (діагностика додаткового ослаблення звуку). Логіка й регістри -- functions/volume_probe.c.
 */
#include "user_interface/menuVolumeProbe.h"

#if defined(VOLUME_PROBE)
#include <stdio.h>
#include "applicationMain.h"
#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "functions/trx.h"
#include "functions/ticks.h"
#include "hardware/HX8353E.h"
#include "io/keyboard.h"
#include "user_interface/uiLocalisation.h"
#include "user_interface/languages/volprobe_ua.h"

#define VP_ROW(n)       (16 + ((n) * 10))
#define VP_REDRAW_MS    500U
#define VP_ARM_MS       400U     /* повтор клавіші входу (Вправо) в перші 400 мс не міняє крок */

static uint32_t s_lastDraw;
static uint32_t s_enterMs;

static void row(int n, const char *text)
{
	displayPrintAt(0, VP_ROW(n), text, FONT_SIZE_1);
}

static const char *dmrName(uint8_t step)
{
	static const char *const names[VP_DMR_STEPS] = { "1x ", "1/2", "1/4", "1/8" };
	return names[(step < VP_DMR_STEPS) ? step : 0U];
}

static void draw(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE];
	int mode = trxGetMode();
	uint8_t fm = volumeProbeFmStep();
	uint8_t dm = volumeProbeDmrStep();
	uint8_t sel = volumeProbeSelected();

	s_lastDraw = ticksGetMillis();
	displayClearBuf();
	menuDisplayTitle(VOLPROBE_TITLE);

	snprintf(buf, sizeof(buf), VOLPROBE_POT, (int)lastVolume, (int)(lastVolume + 32));
	row(0, buf);
	row(1, (mode == RADIO_MODE_ANALOG) ? VOLPROBE_MODE_FM : ((mode == RADIO_MODE_DIGITAL) ? VOLPROBE_MODE_DMR : VOLPROBE_MODE_OTHER));
	snprintf(buf, sizeof(buf), VOLPROBE_DMR_ROW, (sel == 0U) ? '>' : ' ', dmrName(dm), vpDmrDb(dm));
	row(2, buf);
	snprintf(buf, sizeof(buf), VOLPROBE_FM_ROW, (sel == 1U) ? '>' : ' ', (unsigned)vpFmPercent(fm), (unsigned)VP_FM_HIGH, (unsigned)vpFmLow(fm));
	row(3, buf);

	/* Рядок 4: чому крок не діє зараз (APRS -- причина: приймач читає відліки з того ж FM-шляху). */
	if (volumeProbeFmBlocked())
	{
		row(4, VOLPROBE_FM_BLOCKED);
	}
	else if ((mode != RADIO_MODE_DIGITAL) && (dm != 0U))
	{
		row(4, VOLPROBE_DMR_IDLE);
	}
	else if ((mode != RADIO_MODE_ANALOG) && (fm != 0U))
	{
		row(4, VOLPROBE_FM_IDLE);
	}

	row(6, VOLPROBE_KEYS1);
	row(7, VOLPROBE_KEYS2);
	row(8, VOLPROBE_KEYS3);
	snprintf(buf, sizeof(buf), VOLPROBE_LEFT, (unsigned)volumeProbeSecondsLeft());
	row(9, buf);
	displayRender();
}

void menuVolumeProbeEnter(void)
{
	volumeProbeOpen();
	s_enterMs = ticksGetMillis();
	if (volumeProbeIsOn())
	{
		draw();
	}
}

bool menuVolumeProbeTick(uiEvent_t *ev)
{
	bool redraw = false;
	vpRestore_t r = volumeProbeTick();

	if (r != VP_KEEP)
	{
		/* автоповернення (передача, APRS, канал/режим, таймаут): проба закрита, стокове повернуто */
		return false;
	}

	if (ev->hasEvent && (ev->events & KEY_EVENT))
	{
		if (KEYCHECK_SHORTUP(ev->keys, KEY_RED) || KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
		{
			volumeProbeClose();
			return false;
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_LEFT))
		{
			if ((ticksGetMillis() - s_enterMs) >= VP_ARM_MS)
			{
				volumeProbeAdjust(KEYCHECK_PRESS(ev->keys, KEY_RIGHT) ? 1 : -1);
				redraw = true;
			}
		}
		else if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN))
		{
			volumeProbeToggleSelect();
			redraw = true;
		}
		else if (KEYCHECK_SHORTUP(ev->keys, KEY_0))
		{
			volumeProbeResetAll();
			redraw = true;
		}
	}
	if (ev->hasEvent && (ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
	{
		redraw = true;
	}

	if (volumeProbeIsOn() && (redraw || ((ticksGetMillis() - s_lastDraw) >= VP_REDRAW_MS)))
	{
		draw();
	}
	return volumeProbeIsOn();
}
#endif /* VOLUME_PROBE */
