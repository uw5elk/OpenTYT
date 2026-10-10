/*
 * menuAprsRxProbe.c -- екран «APRS проба» (R3): прийом APRS з I2S від HR-C6000 на 6 варіантах
 * регістрів кодека. Дві сторінки: «пакети» (лічильники кадрів і останній правильний кадр
 * поточного варіанта) і «фон» (розгортка 100..3900 Гц, частка топ-1, частота дискретизації).
 * Джерело, демодулятор і відновлення стану -- functions/aprs_rx_probe.c; кроки -- TESTING.md, AE.
 *
 * Керування: вліво/вправо -- варіант; вгору/вниз -- сторінка; GREEN -- скинути лічильники
 * поточного варіанта; # -- режекція авто/вимк; RED -- вихід.
 * Перемальовування -- раз на 250 мс і на кожну подію.
 */
#include "user_interface/menuAprsRxProbe.h"

#if defined(APRS_RX_PROBE)

#include "user_interface/uiGlobals.h"
#include "user_interface/uiUtilities.h"
#include "functions/ticks.h"
#include "user_interface/languages/aprsprobe_ua.h"

#define PROBE_CCM            __attribute__((section(".aes_ccmram")))   /* кінець CCM, як у aprs_rx_probe.c */
#define PROBE_ROW(n)         (16 + ((n) * 10))
#define PROBE_REDRAW_MS      250U
#define PROBE_NO_DATA_MS     1000U

/* Стан екрана -- у CCM; ініціалізується в menuAprsRxProbeEnter() (до того не читається). */
static uint32_t s_lastDrawMs PROBE_CCM;
static uint8_t  s_page       PROBE_CCM;   /* 0 -- пакети, 1 -- фон */

static void printRow(int row, const char *text)
{
	displayPrintAt(0, PROBE_ROW(row), text, FONT_SIZE_1);
}

static void drawPackets(const aprsProbeVar_t *st)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];

	snprintf(buf, sizeof(buf), APRSPROBE_FMT_OK, (unsigned)st->ok);
	printRow(2, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_BAD, (unsigned)st->bad);
	printRow(3, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_FLAGS, (unsigned)st->flagSeq);
	printRow(4, buf);

	if (st->srcDst[0] != 0)
	{
		printRow(5, st->srcDst);
		printRow(6, st->info);
	}
	else
	{
		printRow(5, APRSPROBE_LAST_NONE);
	}

	if (aprsRxProbeNotchAuto() == false)
	{
		printRow(7, APRSPROBE_NOTCH_OFF);
	}
	else if (aprsRxProbeNotchHz() != 0)
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_NOTCH, (unsigned)aprsRxProbeNotchHz());
		printRow(7, buf);
	}
	else
	{
		printRow(7, APRSPROBE_NOTCH_AUTO);
	}
}

static void drawBackground(const aprsProbeVar_t *st)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	uint32_t fs, secs;

	if (st->bgValid)
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_RMS, (unsigned)st->rms, (int)st->dc);
		printRow(2, buf);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_TOP1, (unsigned)st->f1, (unsigned)st->a1);
		printRow(3, buf);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_SHARE, (unsigned)st->share1);
		printRow(4, buf);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_TOP2, (unsigned)st->f2, (unsigned)st->a2);
		printRow(5, buf);
	}
	else
	{
		printRow(2, APRSPROBE_BG_WAIT);
	}

	if (aprsRxProbeFs(&fs, &secs))
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_FS, (unsigned long)fs, (unsigned long)secs);
		printRow(6, buf);
	}
	else
	{
		printRow(6, APRSPROBE_FS_WAIT);
	}
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_LOST, (unsigned long)aprsRxProbeOverflows());
	printRow(7, buf);
}

static void draw(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	uint8_t v = aprsRxProbeVariant();
	aprsProbeStatus_t st = aprsRxProbeStatus();

	s_lastDrawMs = ticksGetMillis();

	displayClearBuf();
	menuDisplayTitle((s_page == 0) ? APRSPROBE_TITLE_PKT : APRSPROBE_TITLE_BG);

	if (st == APRS_PROBE_ST_NOT_FM)
	{
		displayPrintCentered(52, APRSPROBE_ONLY_FM, FONT_SIZE_3);
		printRow(10, APRSPROBE_FOOTER2);
		displayRender();
		return;
	}

	/* Рядок 0: варіант. */
	{
		uint8_t e0, r36, r10;
		aprsRxProbeVariantRegs(v, &e0, &r36, &r10);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_HDR, (unsigned)aprsRxProbeVariantR2(v), (unsigned)(v + 1),
				(unsigned)APRS_PROBE_NUM_VARIANTS, (unsigned)e0, (unsigned)r36, (unsigned)r10);
		printRow(0, buf);
	}

	/* Рядок 1: стан I2S. */
	if (st == APRS_PROBE_ST_NO_WS)
	{
		printRow(1, APRSPROBE_NO_WS);
	}
	else if (st == APRS_PROBE_ST_BUSY)
	{
		printRow(1, APRSPROBE_BUSY);
	}
	else if (st != APRS_PROBE_ST_RUNNING)
	{
		printRow(1, APRSPROBE_WAIT);
	}
	else if (aprsRxProbeMsSinceBlock() > PROBE_NO_DATA_MS)
	{
		printRow(1, APRSPROBE_NO_DATA);
	}
	else
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_RUN, (unsigned long)aprsRxProbeBlocks());
		printRow(1, buf);
	}

	const aprsProbeVar_t *stats = aprsRxProbeStats(v);
	if (s_page == 0)
	{
		drawPackets(stats);
	}
	else
	{
		drawBackground(stats);
	}

	/* Рядок 8: регістри на вході -- саме їх буде відновлено. */
	{
		uint8_t e0, r36, r10;
		bool ok;
		if (aprsRxProbeSavedRegs(&e0, &r36, &r10, &ok))
		{
			snprintf(buf, sizeof(buf), (ok ? APRSPROBE_FMT_SAVED : APRSPROBE_FMT_SAVED_BAD),
					(unsigned)e0, (unsigned)r36, (unsigned)r10);
			printRow(8, buf);
		}
	}

	printRow(9, APRSPROBE_FOOTER1);
	printRow(10, APRSPROBE_FOOTER2);
	displayRender();
}

void menuAprsRxProbeEnter(void)
{
	s_page = 0;
	aprsRxProbeOpen();
	draw();
}

bool menuAprsRxProbeTick(uiEvent_t *ev)
{
	bool redraw = false;

	if (ev->hasEvent)
	{
		if (ev->events & KEY_EVENT)
		{
			if (KEYCHECK_SHORTUP(ev->keys, KEY_RED))
			{
				aprsRxProbeClose();
				return false;
			}
			else if (KEYCHECK_PRESS(ev->keys, KEY_RIGHT) || KEYCHECK_PRESS(ev->keys, KEY_LEFT))
			{
				aprsRxProbeSelect(KEYCHECK_PRESS(ev->keys, KEY_RIGHT) ? 1 : -1);
				redraw = true;
			}
			else if (KEYCHECK_PRESS(ev->keys, KEY_UP) || KEYCHECK_PRESS(ev->keys, KEY_DOWN))
			{
				s_page ^= 1;
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
			{
				aprsRxProbeResetCurrent();
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_HASH))
			{
				aprsRxProbeToggleNotch();
				redraw = true;
			}
		}

		if ((ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
		{
			redraw = true;
		}
	}

	aprsRxProbeService();

	if (redraw || ((ticksGetMillis() - s_lastDrawMs) >= PROBE_REDRAW_MS))
	{
		draw();
	}
	return true;
}

#endif /* APRS_RX_PROBE */
