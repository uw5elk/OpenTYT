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
 * R7: * -- авто / 10 біт / 11 біт / 16>>6; сторінка «фаза» (T_start: <> -- змінити на 2 мкс, 0 --
 * перезапустити I2S, регістри SPI3/I2S3ext); 5 -- розгортка T_start і сторінка «скан» (таблиця
 * результату: що вийшло за nbits на кожному T); детектор nbits -- рядок 1 і профіль на «фоні».
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
static uint8_t  s_page       PROBE_CCM;   /* 0 -- пакети, 1 -- фон, 2 -- потік, 3 -- кадр, 4 -- регістри, 5 -- фаза, 6 -- скан */
#define PROBE_PAGES          7U
#define PROBE_PAGE_REGS      4U
#define PROBE_PAGE_PHASE     5U
#define PROBE_PAGE_SCAN      6U
#define PROBE_CAP(v, m)      ((unsigned long)(((v) > (m)) ? (m) : (v)))

static void printRow(int row, const char *text)
{
	displayPrintAt(0, PROBE_ROW(row), text, FONT_SIZE_1);
}

/* R7: ручний режим формату (*): «10 біт!» / «11 біт!» / «16>>6!». */
static const char *fmtName(void)
{
	switch (aprsRxProbeFormatMode())
	{
		case APRS_PROBE_FMT_10:
			return APRSPROBE_BITS10;
		case APRS_PROBE_FMT_11:
			return APRSPROBE_BITS11;
		default:
			return APRSPROBE_BITS16;
	}
}

/* nbits вердикту: «?» -- вердикту ще нема. */
static const char *nbitsStr(char *b, size_t n, uint8_t nb)
{
	if (nb == 0U)
	{
		return "?";
	}
	snprintf(b, n, "%u", (unsigned)nb);
	return b;
}

static void drawPackets(const aprsProbeVar_t *st)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	char nb[8];

	snprintf(buf, sizeof(buf), APRSPROBE_FMT_CNT, (unsigned)PROBE_CAP(st->ok, 999U), (unsigned)PROBE_CAP(st->bad, 999U),
			(unsigned)PROBE_CAP(st->flagSeq, 999U));
	printRow(2, buf);

	if (st->srcDst[0] != 0)
	{
		printRow(3, st->srcDst);
		printRow(4, st->info);
	}
	else
	{
		printRow(3, APRSPROBE_LAST_NONE);
	}

	/* R7: кадри окремо для кожного nbits («nbits:ок/помилка», до 4 слотів по 2 в рядку). */
	{
		int rowOut = 5;
		bool any = false;
		for (uint8_t i = 0; i < APRS_PROBE_NB_SLOTS; i += 2)
		{
			char half[2][16];
			int cnt = 0;
			for (uint8_t k = 0; k < 2; k++)
			{
				uint8_t nbits;
				uint16_t ok, bad;
				if (aprsRxProbeNbSlot((uint8_t)(i + k), &nbits, &ok, &bad))
				{
					snprintf(half[cnt], sizeof(half[cnt]), APRSPROBE_FMT_NB, (unsigned)nbits, (unsigned)PROBE_CAP(ok, 999U),
							(unsigned)PROBE_CAP(bad, 999U));
					cnt++;
				}
			}
			if (cnt > 0)
			{
				any = true;
				snprintf(buf, sizeof(buf), (cnt == 2) ? "%s  %s" : "%s", half[0], half[1]);
				printRow(rowOut++, buf);
			}
		}
		if (any == false)
		{
			printRow(5, APRSPROBE_NB_NONE);
		}
	}

	/* R7: рівень (RMS і пік після зведення до масштабу 10 біт) і режекція. */
	{
		char nz[8];
		if (aprsRxProbeNotchAuto() == false)
		{
			snprintf(nz, sizeof(nz), "%s", APRSPROBE_NOTCH_S_OFF);
		}
		else if (aprsRxProbeNotchHz() != 0)
		{
			snprintf(nz, sizeof(nz), "%u", (unsigned)aprsRxProbeNotchHz());
		}
		else
		{
			snprintf(nz, sizeof(nz), "%s", APRSPROBE_NOTCH_S_AUTO);
		}
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_LEVEL, (unsigned)PROBE_CAP(st->rms, 9999U), (unsigned)PROBE_CAP(st->peak, 9999U), nz);
		printRow(7, buf);
	}

	/* Що каже детектор (і в ручному режимі) і скільки разів він змінював уже відомий nbits (з GREEN). */
	{
		const apFmtDet_t *det = aprsRxProbeFormatDet();
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_DET, nbitsStr(nb, sizeof(nb), det->nbits), PROBE_CAP(det->switches, 9999U));
	}
	printRow(8, buf);
}

/* R6/R7: регістри кодека (прочитані з чипа), старт I2S і події. Рядки 2-3 -- E0..EF, 4-5 -- решта,
 * 6 -- старт I2S, 7 -- FRE за секунду й кількість стартів, 8 -- події. */
static void drawRegs(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	uint8_t addr, val;

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
	/* решта -- по 4: «06:20 10:80 26:FD 34:xx» */
	for (int r = 0; r < 2; r++)
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

	{
		const aprsProbeDiag_t *g = aprsRxProbeDiag();
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_START, (unsigned)g->tSetUs, (unsigned)g->tMeasUs, (unsigned)g->wsAfter);
		printRow(6, buf);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_FRE, (unsigned)PROBE_CAP(g->freRxSec, 999U), (unsigned)PROBE_CAP(g->freTxSec, 999U),
				PROBE_CAP(g->starts, 999U));
		printRow(7, buf);
	}
	{
		uint32_t sqo, sqc, bp, pr;
		aprsRxProbeEvents(&sqo, &sqc, &bp, &pr);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_EVENTS, PROBE_CAP(sqo, 999U), PROBE_CAP(sqc, 999U), PROBE_CAP(bp, 999U), PROBE_CAP(pr, 99U));
		printRow(8, buf);
	}
}

/* R7: сторінка «фаза» -- детермінований старт I2S (T_start), вердикти на цьому T, регістри SPI3/I2S3ext. */
static void drawPhase(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];
	char nb[8];
	const aprsProbeDiag_t *g = aprsRxProbeDiag();

	snprintf(buf, sizeof(buf), APRSPROBE_FMT_PH_T, (unsigned)g->tSetUs, (unsigned)g->tMeasUs);
	printRow(2, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_PH_WS, (unsigned)g->wsAfter, nbitsStr(nb, sizeof(nb), aprsRxProbeFormatDet()->nbits));
	printRow(3, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_PH_HAL, (unsigned)g->halUs, PROBE_CAP(g->starts, 9999U));
	printRow(4, buf);
	snprintf(buf, sizeof(buf), APRSPROBE_FMT_PH_CNT, (unsigned)PROBE_CAP(g->tCnt[0], 99U), (unsigned)PROBE_CAP(g->tCnt[1], 99U),
			(unsigned)PROBE_CAP(g->tCnt[2], 99U), (unsigned)PROBE_CAP(g->tCnt[3], 99U));
	printRow(5, buf);
	if (g->regsValid)
	{
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_PH_S3, (unsigned)g->regs[0], (unsigned)g->regs[1], (unsigned)(g->regs[2] & 0xFFU));
		printRow(6, buf);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_PH_S3SR, (unsigned)g->sr[0], (unsigned)g->srErr[0]);
		printRow(7, buf);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_PH_EXT, (unsigned)g->regs[3], (unsigned)g->sr[1], (unsigned)g->srErr[1]);
		printRow(8, buf);
	}
	else
	{
		printRow(6, APRSPROBE_PH_WAIT);
	}
}

/* Символ клітинки розгортки: цифра k = 16 - nbits, F -- 16, м -- різні, ? -- вердикту не було, . -- не міряли. */
static const char *scanSym(uint8_t code, char *b)
{
	if (code == 0U)
	{
		return ".";
	}
	if (code == APRS_PROBE_SCAN_NONE)
	{
		return "?";
	}
	if (code == APRS_PROBE_SCAN_MIXED)
	{
		return APRSPROBE_SYM_MIX;
	}
	if (code >= AP_NBITS_TRUE16)
	{
		return "F";
	}
	b[0] = (char)('0' + (16 - code));
	b[1] = 0;
	return b;
}

/* R7: сторінка «скан» -- таблиця 4 рядки x 16 значень (T = 0..124 мкс крок 2, групи по 4). */
static void drawScan(void)
{
	char buf[SCREEN_LINE_BUFFER_SIZE * 2];

	if (aprsRxProbeScanActive())
	{
		uint8_t idx, rep;
		aprsRxProbeScanProgress(&idx, &rep);
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_SC_RUN, (unsigned)(idx * APRS_PROBE_T_STEP_US), (unsigned)(rep + 1U), (unsigned)APRS_PROBE_SCAN_REPS);
		printRow(2, buf);
	}
	else if (aprsRxProbeScanCode(0) != 0U)
	{
		printRow(2, APRSPROBE_SC_DONE);
	}
	else
	{
		printRow(2, APRSPROBE_SC_IDLE);
	}

	for (int r = 0; r < 4; r++)
	{
		char row[40];
		int o = snprintf(row, sizeof(row), "%3u ", (unsigned)(r * 16 * APRS_PROBE_T_STEP_US));
		for (int k = 0; k < 16; k++)
		{
			int idx = r * 16 + k;
			char tmp[2];
			const char *sym = (idx < (int)APRS_PROBE_SCAN_N) ? scanSym(aprsRxProbeScanCode((uint8_t)idx), tmp) : " ";
			if (((k % 4) == 0) && (k != 0))
			{
				o += snprintf(&row[o], sizeof(row) - (size_t)o, " ");
			}
			o += snprintf(&row[o], sizeof(row) - (size_t)o, "%s", sym);
		}
		printRow(3 + r, row);
	}
	printRow(7, APRSPROBE_SC_LEGEND);
	{
		uint16_t from, to, centre;
		uint8_t nb;
		if (aprsRxProbeScanBest(&from, &to, &nb, &centre))
		{
			snprintf(buf, sizeof(buf), APRSPROBE_FMT_SC_BEST, (unsigned)from, (unsigned)to, (unsigned)nb);
			printRow(8, buf);
		}
		else if (aprsRxProbeScanActive() == false)
		{
			printRow(8, (aprsRxProbeScanCode(0) != 0U) ? APRSPROBE_SC_NO_BEST : "");
		}
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

	/* R7: профіль детектора nbits -- c[15..1] останнього блока, шістнадцяткові цифри c/10 */
	{
		const apFmtDet_t *det = aprsRxProbeFormatDet();
		char prof[20];
		for (int j = 15; j >= 1; j--)
		{
			uint32_t d = ((uint32_t)det->c[j] + 5U) / 10U;
			prof[15 - j] = (char)((d > 15U) ? 'F' : ((d > 9U) ? ('A' + (d - 10U)) : ('0' + d)));
		}
		prof[15] = 0;
		snprintf(buf, sizeof(buf), APRSPROBE_FMT_PROFILE, prof);
		printRow(7, buf);
	}
	{
		const apFmt_t *f = &st->fmt;
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
				APRSPROBE_TITLE_REGS, APRSPROBE_TITLE_PHASE, APRSPROBE_TITLE_SCAN };
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
		if (aprsRxProbeFormatMode() == APRS_PROBE_FMT_AUTO)
		{
			char nb[8];
			snprintf(buf, sizeof(buf), APRSPROBE_FMT_RUN_AUTO, nbitsStr(nb, sizeof(nb), aprsRxProbeFormatDet()->nbits), PROBE_CAP(aprsRxProbeBlocks(), 99999U));
		}
		else
		{
			snprintf(buf, sizeof(buf), APRSPROBE_FMT_RUN_MAN, fmtName(), PROBE_CAP(aprsRxProbeBlocks(), 99999U));
		}
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
	else if (s_page == PROBE_PAGE_REGS)
	{
		drawRegs();
	}
	else if (s_page == PROBE_PAGE_PHASE)
	{
		drawPhase();
	}
	else
	{
		drawScan();
	}

	if (s_page == PROBE_PAGE_PHASE)
	{
		printRow(9, APRSPROBE_FOOTER_PH1);
		printRow(10, APRSPROBE_FOOTER_PH2);
	}
	else if (s_page == PROBE_PAGE_SCAN)
	{
		printRow(9, APRSPROBE_FOOTER_SC1);
		printRow(10, APRSPROBE_FOOTER_SC2);
	}
	else
	{
		printRow(9, APRSPROBE_FOOTER1);
		printRow(10, APRSPROBE_FOOTER2);
	}
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
				int dir = KEYCHECK_PRESS(ev->keys, KEY_RIGHT) ? 1 : -1;
				if (s_page == PROBE_PAGE_PHASE)
				{
					aprsRxProbeTAdjust(dir * (int)APRS_PROBE_T_STEP_US);   /* R7: на сторінці «фаза» <> міняють T_start */
				}
				else
				{
					aprsRxProbeSelect(dir);
				}
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
				aprsRxProbeToggleFormat();   /* R7: авто -> 10 біт -> 11 біт -> 16>>6 -> авто */
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_0))
			{
				aprsRxProbeRestartI2S();     /* R6/R7: лише I2S з поточним T_start, регістри не пишемо */
				redraw = true;
			}
			else if (KEYCHECK_SHORTUP(ev->keys, KEY_5))
			{
				aprsRxProbeScanToggle();     /* R7: розгортка T_start (повторно -- скасувати) */
				s_page = PROBE_PAGE_SCAN;
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
