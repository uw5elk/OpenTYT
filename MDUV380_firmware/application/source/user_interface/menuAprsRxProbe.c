/*
 * menuAprsRxProbe.c -- екран «APRS проба» (R3/R4): прийом APRS з I2S від HR-C6000 на 6 варіантах
 * регістрів кодека. Сторінки (вгору/вниз по колу): «пакети» (лічильники кадрів і останній
 * правильний кадр поточного варіанта), «фон» (розгортка 100..3900 Гц, частка топ-1, частота
 * дискретизації), R4: «потік» (безперервність тону 1200 Гц на межах блоків, колбеки DMA) і
 * «кадр» (останній кадр із помилковим FCS: довжина, hex, адреси «як є»; фаза тактів).
 * Джерело, демодулятор і відновлення стану -- functions/aprs_rx_probe.c; кроки -- TESTING.md, AE.
 *
 * Керування: вліво/вправо -- варіант; вгору/вниз -- сторінка; GREEN -- скинути лічильники
 * поточного варіанта (і «потік», і фазу тактів); # -- режекція авто/вимк; * (R5/R6) -- формат
 * відліку по колу: авто (типово) / 10 біт / 16 біт; 0 (R6) -- перезапустити I2S без запису
 * регістрів (дослід: чи міняється формат від самого перезапуску); RED -- вихід.
 * R6: сторінка «регістри» -- регістри кодека HR-C6000, прочитані з чипа раз на секунду (поки її
 * видно), старт I2S (мкс від фронту WS, рівень WS, FRE) і події, що переписують регістри.
 * USB-запис на ПК (опкод 0xB5) іде, поки екран відкрито; стан -- у рядку 1.
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
static uint8_t  s_page       PROBE_CCM;   /* 0 -- пакети, 1 -- фон, 2 -- потік, 3 -- кадр, 4 -- регістри */
#define PROBE_PAGES          5U
#define PROBE_PAGE_REGS      4U
#define PROBE_CAP(v, m)      ((unsigned long)(((v) > (m)) ? (m) : (v)))

static void printRow(int row, const char *text)
{
	displayPrintAt(0, PROBE_ROW(row), text, FONT_SIZE_1);
}

/* R6: назва формату обробки -- «авто(16)» / «авто(10)» або ручні «10 біт!» / «16 біт!». */
static const char *fmtName(void)
{
	bool is16 = aprsRxProbeFormat16();
	if (aprsRxProbeFormatMode() == APRS_PROBE_FMT_AUTO)
	{
		return is16 ? APRSPROBE_AUTO16 : APRSPROBE_AUTO10;
	}
	return is16 ? APRSPROBE_BITS16 : APRSPROBE_BITS10;
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

	/* R6: що каже детектор (10 чи 16 -- і в ручному режимі) і скільки разів він перемикав (з GREEN). */
	{
		const apFmtDet_t *det = aprsRxProbeFormatDet();
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_DET, (det->is16 ? 16U : 10U), PROBE_CAP(det->switches, 9999U));
	}
	printRow(8, buf);
}

/* R6: регістри кодека (прочитані з чипа), старт I2S і події. Рядки 2-6 -- регістри, 7 -- старт
 * I2S, 8 -- FRE і кількість стартів, 9 (замість підказки) -- події. */
static void drawRegs(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	uint8_t addr, val;
	uint32_t starts, us, ws, freRx, freTx;

	aprsRxProbeRegsRefresh();

	/* E0..EF -- рядками по 8: «E0 89 0F 06 52 27 1A 00 00» */
	for (int r = 0; r < 2; r++)
	{
		int o = 0;
		for (int i = 0; i < 8; i++)
		{
			bool ok = aprsRxProbeReg((uint8_t)(r * 8 + i), &addr, &val);
			if (i == 0)
			{
				o += snprintf(&buf[o], sizeof(buf) - o, "%02X", (unsigned)addr);
			}
			o += ok ? snprintf(&buf[o], sizeof(buf) - o, " %02X", (unsigned)val) : snprintf(&buf[o], sizeof(buf) - o, " --");
		}
		printRow(2 + r, buf);
	}
	/* решта -- по 4: «06:20 10:80 25:0E 26:FD» */
	for (int r = 0; r < 3; r++)
	{
		int o = 0;
		for (int i = 0; i < 4; i++)
		{
			bool ok = aprsRxProbeReg((uint8_t)(16 + r * 4 + i), &addr, &val);
			o += ok ? snprintf(&buf[o], sizeof(buf) - o, (i == 0) ? "%02X:%02X" : " %02X:%02X", (unsigned)addr, (unsigned)val) :
					snprintf(&buf[o], sizeof(buf) - o, (i == 0) ? "%02X:--" : " %02X:--", (unsigned)addr);
		}
		printRow(4 + r, buf);
	}

	aprsRxProbeI2SDiag(&starts, &us, &ws, &freRx, &freTx);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_START, PROBE_CAP(us, 99999U), (unsigned)ws);
	printRow(7, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_FRE, PROBE_CAP(freRx, 9999U), PROBE_CAP(freTx, 9999U), PROBE_CAP(starts, 999U));
	printRow(8, buf);
	{
		uint32_t sqo, sqc, bp, pr;
		aprsRxProbeEvents(&sqo, &sqc, &bp, &pr);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_EVENTS, PROBE_CAP(sqo, 999U), PROBE_CAP(sqc, 999U), PROBE_CAP(bp, 999U), PROBE_CAP(pr, 99U));
		printRow(9, buf);
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
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_FS, (unsigned long)fs, (unsigned long)secs, (unsigned long)aprsRxProbeOverflows());
	}
	else
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FS_WAIT, (unsigned long)aprsRxProbeOverflows());
	}
	printRow(6, buf);

	/* R5: формат відліку на цьому варіанті (з останнього GREEN). У R4: біт 10 ~50 %, біти 10..15
	 * завжди однакові, пік |s| ~360 з 512. */
	{
		const apFmt_t *f = &st->fmt;
		uint32_t pct = (f->n > 0) ? (uint32_t)(((uint64_t)f->b10 * 100U + f->n / 2U) / f->n) : 0U;
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_B10, (unsigned long)pct, (unsigned long)((f->nonUni > 999999U) ? 999999U : f->nonUni));
		printRow(7, buf);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_NEAR, (unsigned long)((f->nearLim > 999999U) ? 999999U : f->nearLim), (unsigned)f->peak);
		printRow(8, buf);
	}
}

static void drawStream(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	const apStream_t *st = aprsRxProbeStream();
	uint32_t half, full, order;

	snprintf(buf, sizeof(buf), APRSPROBE_FMT_TONE, (unsigned)st->amp, (unsigned long)st->blocks);
	printRow(2, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_JUMP_B, (unsigned long)st->jumpsB);
	printRow(3, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_JUMP_IN, (unsigned long)st->jumpsIn);
	printRow(4, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_JUMP_MAX, (unsigned)st->maxB, (unsigned)st->maxIn);
	printRow(5, buf);
	{
		/* у printf прошивки немає float -- десяті вручну */
		float off = apStreamOffsetHz(st);
		bool neg = (off < 0.0f);
		uint32_t t = (uint32_t)((neg ? -off : off) * 10.0f + 0.5f);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_TONE_OFF, (neg ? "-" : "+"), (unsigned long)(t / 10U), (unsigned long)(t % 10U));
		printRow(6, buf);
	}
	aprsRxProbeDmaCounters(&half, &full, &order);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_DMA, (unsigned long)half, (unsigned long)full);
	printRow(7, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_DMA_ORDER, (unsigned long)order);
	printRow(8, buf);
}

static void drawFrame(const aprsProbeVar_t *st)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];

	if (st->badLen != 0)
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_BADLEN, (unsigned)st->badLen);
		printRow(2, buf);
		for (int r = 0; r < 2; r++)
		{
			int o = 0;
			for (int i = 0; i < 8; i++)
			{
				int k = r * 8 + i;
				if (k < (int)st->badLen)
				{
					o += snprintf(&buf[o], sizeof(buf) - o, (i == 0) ? "%02X" : " %02X", (unsigned)st->badHead[k]);
				}
			}
			buf[o] = 0;
			printRow(3 + r, buf);
		}
		{
			char addr[24];
			ax25LooseAddr(st->badHead, (st->badLen < 16) ? st->badLen : 16, addr, sizeof(addr));
			snprintf(buf, sizeof(buf), APRSPROBE_FMT_ADDR, addr);
			printRow(5, buf);
		}
	}
	else
	{
		printRow(2, APRSPROBE_BAD_NONE);
	}

	{
		const uint16_t *h = aprsRxProbePllHist();
		uint32_t tot = 0;
		for (int i = 0; i < 8; i++)
		{
			tot += h[i];
		}
		printRow(6, APRSPROBE_PLL_TITLE);
		int o = 0;
		for (int i = 0; i < 8; i++)
		{
			uint32_t pct = (tot > 0) ? ((h[i] * 100U + tot / 2U) / tot) : 0U;
			if (pct > 99U)
			{
				pct = 99U;
			}
			o += snprintf(&buf[o], sizeof(buf) - o, (i == 0) ? "%2lu" : " %2lu", (unsigned long)pct);
		}
		printRow(7, buf);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_PLL_N, (unsigned long)tot);
		printRow(8, buf);
	}
}

static void draw(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	uint8_t v = aprsRxProbeVariant();
	aprsProbeStatus_t st = aprsRxProbeStatus();

	s_lastDrawMs = ticksGetMillis();

	displayClearBuf();
	{
		static const char * const titles[PROBE_PAGES] = { APRSPROBE_TITLE_PKT, APRSPROBE_TITLE_BG, APRSPROBE_TITLE_STREAM, APRSPROBE_TITLE_FRAME,
				APRSPROBE_TITLE_REGS };
		menuDisplayTitle(titles[(s_page < PROBE_PAGES) ? s_page : 0]);
	}

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

	/* Рядок 1: стан I2S (або USB-запис, якщо йде / щойно був). */
	uint32_t cs, ct, cl;
	if (aprsRxProbeCapture(&cs, &ct, &cl))
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_USB, (unsigned long)cs, (unsigned long)ct, (unsigned long)cl);
		printRow(1, buf);
	}
	else if (st == APRS_PROBE_ST_NO_WS)
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
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_RUN, fmtName(), (unsigned long)aprsRxProbeBlocks());
		printRow(1, buf);
	}

	/* R6: рядок 8 «пакетів» -- формат і перемикання (раніше там були регістри на вході; тепер
	 * поточні значення регістрів -- на сторінці «регістри»). */
	const aprsProbeVar_t *stats = aprsRxProbeStats(v);
	if (s_page == 0)
	{
		drawPackets(stats);
	}
	else if (s_page == 1)
	{
		drawBackground(stats);
	}
	else if (s_page == 2)
	{
		drawStream();
	}
	else if (s_page == 3)
	{
		drawFrame(stats);
	}
	else
	{
		drawRegs();   /* рядок 9 -- події замість підказки */
	}

	if (s_page != PROBE_PAGE_REGS)
	{
		printRow(9, APRSPROBE_FOOTER1);
	}
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
				s_page = (uint8_t)((s_page + (KEYCHECK_PRESS(ev->keys, KEY_DOWN) ? 1U : (PROBE_PAGES - 1U))) % PROBE_PAGES);
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_GREEN))
			{
				aprsRxProbeResetCurrent();
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_STAR))
			{
				aprsRxProbeToggleFormat();   /* R6: авто -> 10 біт -> 16 біт -> авто */
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_0))
			{
				aprsRxProbeRestartI2S();     /* R6: лише I2S, регістри не пишемо */
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
