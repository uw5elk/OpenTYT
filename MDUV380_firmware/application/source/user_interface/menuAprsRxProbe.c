/*
 * menuAprsRxProbe.c -- екран «APRS проба» (R2): рівень і тони 1200/2200 Гц з двох можливих
 * джерел прийнятого FM-звуку -- I2S від HR-C6000 (варіанти А) і PC3/ADC2 (варіант Б).
 * Джерела й відновлення стану -- functions/aprs_rx_probe.c; що й як записувати -- TESTING.md, AD.
 *
 * Керування: вліво/вправо -- попередній/наступний варіант, RED -- вихід.
 * Оновлення -- коли закривається вікно вимірювання (~240 мс), стан -- щонайменше раз на 250 мс.
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
static uint32_t   s_seenSeq    PROBE_CCM;
static uint32_t   s_lastDrawMs PROBE_CCM;
static uint32_t   s_windows    PROBE_CCM;
static apResult_t s_shown[2]   PROBE_CCM;
static bool       s_haveShown  PROBE_CCM;

static void printRow(int row, const char *text)
{
	displayPrintAt(0, PROBE_ROW(row), text, FONT_SIZE_1);
}

static void drawChannel(int row, const char *label, const apResult_t *r)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	const char *win = (r->winner == AP_WIN_1200) ? APRSPROBE_WIN_1200 :
			((r->winner == AP_WIN_2200) ? APRSPROBE_WIN_2200 :
			((r->winner == AP_WIN_WEAK) ? APRSPROBE_WIN_WEAK : APRSPROBE_WIN_NONE));

	snprintf(buf, sizeof(buf), APRSPROBE_FMT_LVL, label, (unsigned long)r->rms, (unsigned long)r->peak);
	printRow(row, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_TONES, (unsigned long)r->a1200, (unsigned long)r->a2200);
	printRow(row + 1, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_DC, (long)r->mean, (int)r->ratioDb, win);
	printRow(row + 2, buf);
}

static void draw(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	uint8_t v = aprsRxProbeVariant();
	aprsProbeStatus_t st = aprsRxProbeStatus();
	bool isA = (v < APRS_PROBE_NUM_I2S_VARIANTS);

	s_lastDrawMs = ticksGetMillis();

	displayClearBuf();
	menuDisplayTitle(APRSPROBE_TITLE);

	if (st == APRS_PROBE_ST_NOT_FM)
	{
		displayPrintCentered(52, APRSPROBE_ONLY_FM, FONT_SIZE_3);
		printRow(10, APRSPROBE_FOOTER);
		displayRender();
		return;
	}

	/* Рядок 0: варіант. */
	if (isA)
	{
		uint8_t e0, r36, r10;
		aprsRxProbeVariantRegs(v, &e0, &r36, &r10);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_HDR_A, (unsigned)(v + 1), (unsigned)APRS_PROBE_NUM_VARIANTS,
				(unsigned)e0, (unsigned)r36, (unsigned)r10);
	}
	else
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_HDR_B, (unsigned)(v + 1), (unsigned)APRS_PROBE_NUM_VARIANTS,
				(unsigned)APRS_PROBE_ADC_FS);
	}
	printRow(0, buf);

	/* Рядок 1: стан джерела. */
	const char *stText = NULL;
	if (st == APRS_PROBE_ST_NO_WS)
	{
		stText = APRSPROBE_NO_WS;
	}
	else if (st == APRS_PROBE_ST_BUSY)
	{
		stText = APRSPROBE_BUSY;
	}
	else if (st != APRS_PROBE_ST_RUNNING)
	{
		stText = APRSPROBE_WAIT;
	}
	else if (aprsRxProbeMsSinceResult() > PROBE_NO_DATA_MS)
	{
		stText = APRSPROBE_NO_DATA;
	}

	if (stText != NULL)
	{
		printRow(1, stText);
	}
	else
	{
		snprintf(buf, sizeof(buf), (isA ? APRSPROBE_FMT_RUN_A : APRSPROBE_FMT_RUN_B), (unsigned long)s_windows);
		printRow(1, buf);
	}

	/* Рядки 2..7: виміри (останнє закрите вікно цього варіанта). */
	if (s_haveShown)
	{
		if (isA)
		{
			drawChannel(2, "L", &s_shown[0]);
			drawChannel(5, "R", &s_shown[1]);
		}
		else
		{
			drawChannel(2, "PC3", &s_shown[0]);
		}
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

	printRow(10, APRSPROBE_FOOTER);
	displayRender();
}

static void resetShown(void)
{
	s_haveShown = false;
	s_windows = 0;
	memset(s_shown, 0, sizeof(s_shown));
}

void menuAprsRxProbeEnter(void)
{
	s_seenSeq = 0;
	resetShown();
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
				resetShown();
				redraw = true;
			}
		}

		if ((ev->events & FUNCTION_EVENT) && (ev->function == FUNC_REDRAW))
		{
			redraw = true;
		}
	}

	aprsRxProbeService();

	apResult_t res[2];
	if (aprsRxProbeResult(res, &s_seenSeq))
	{
		s_shown[0] = res[0];
		s_shown[1] = res[1];
		s_haveShown = (res[0].valid != 0);
		if (s_haveShown)
		{
			s_windows++;
		}
		redraw = true;
	}

	if (redraw || ((ticksGetMillis() - s_lastDrawMs) >= PROBE_REDRAW_MS))
	{
		draw();
	}
	return true;
}

#endif /* APRS_RX_PROBE */
