/*
 * aprs_fault.c -- R10-fix4: обробник збою Cortex-M, програмний сторож і звіт після перезавантаження. Опис -- aprs_fault.h.
 *
 * ПРАВИЛА ЦЬОГО ФАЙЛУ (код виконується, коли прошивка вже зламана):
 *   - жодної динамічної пам'яті, жодного FreeRTOS і printf в обробнику збою: лише прямі записи в регістри й екранний буфер;
 *   - спершу ЗБЕРЕГТИ (backup-регістри RTC), потім малювати: якщо малювання теж упаде -- запис уже є, і після скидання
 *     його покаже звіт при старті;
 *   - перед кожним читанням зі стека перевірити, що адреса в RAM (інакше друге виключення = lockup без жодного виводу).
 *
 * Розкладка backup-регістрів RTC (BKP0R..BKP19R; переживають NVIC_SystemReset/сторож, НЕ переживають повної втрати
 * живлення; прошивка їх більше ніде не використовує -- батарейна SRAM BKPSRAM це інше):
 *   0 магія+вид   1 PC  2 LR  3 CFSR  4 HFSR  5 MMFAR/BFAR  6 SP  7 IPSR|EXC_RETURN<<8  8 xPSR  9 R0
 *   10..13 адреси повернення зі стека   14 лічильник kick (+біт 31 «сторож увімкнено», біт 30 «IWDG запущено»)
 *   15 стан сторожа (останній kick | лічильник «застрягло» << 16)   16 останній крок трасування (мс від T0 << 16 | n)
 *   17 його значення v   18 T0 (мс)   19 дескриптор головного завдання FreeRTOS
 */
#include "functions/aprs_fault.h"

#if defined(APRS_RX)

#include <stddef.h>
#include "main.h"
#include "FreeRTOS.h"
#include "task.h"
#include "functions/ticks.h"
#include "functions/aprs_fault_fmt.h"
#include "hardware/HX8353E.h"
#include "io/keyboard.h"
#include "io/buttons.h"
#include "user_interface/menuSystem.h"

/* ---- параметри ------------------------------------------------------------------------------------------- */
#ifndef APRS_FAULT_WDG_TICKS
#define APRS_FAULT_WDG_TICKS   20U      /* тіків TIM7 по 100 мс без kick -> скидання (~2 с) */
#endif
#define AF_FAULT_PAGE_MS       4000U    /* скільки висить кожна сторінка на екрані в самому обробнику збою */
#define AF_FAULT_PAGES_SHOWN   3U       /* скільки сторінок показати перед автоскиданням (3 x 4 с = 12 с) */

/* ---- backup-регістри ------------------------------------------------------------------------------------- */
enum
{
	S_MAGIC = 0, S_PC, S_LR, S_CFSR, S_HFSR, S_ADDR, S_SP, S_EXC, S_XPSR, S_R0,
	S_STK0, S_STK1, S_STK2, S_STK3,
	S_KICK, S_WSEEN, S_TRN, S_TRV, S_T0, S_TASK,
	S_COUNT
};
_Static_assert(S_COUNT == 20, "RTC has 20 backup registers");
_Static_assert(offsetof(RTC_TypeDef, BKP19R) == (offsetof(RTC_TypeDef, BKP0R) + (19U * 4U)), "BKP0R..BKP19R must be contiguous");

#define BKP(i)        (((volatile uint32_t *)&RTC->BKP0R)[(i)])
#define KICK_ARMED    0x80000000UL
#define KICK_IWDG     0x40000000UL
#define KICK_CNT      0x3FFFFFFFUL

/* ---- доступ до backup-домену ----------------------------------------------------------------------------- */
static void bkpEnable(void)
{
	RCC->APB1ENR |= RCC_APB1ENR_PWREN;
	(void)RCC->APB1ENR;
	PWR->CR |= PWR_CR_DBP;
}

/* ---- діапазони пам'яті (перед читанням зі стека) --------------------------------------------------------- */
static bool inRam(uint32_t a, uint32_t bytes)
{
	if ((a & 3U) != 0U)
	{
		return false;
	}
	if ((a >= 0x20000000UL) && ((a + bytes) <= 0x20020000UL) && ((a + bytes) > a))
	{
		return true;
	}
	return ((a >= 0x10000000UL) && ((a + bytes) <= 0x10010000UL) && ((a + bytes) > a));
}

/* Скільки слів можна безпечно прочитати від a вгору (не далі кінця RAM/CCM), максимум max. */
static uint32_t safeWords(uint32_t a, uint32_t max)
{
	uint32_t end;

	if ((a >= 0x20000000UL) && (a < 0x20020000UL))
	{
		end = 0x20020000UL;
	}
	else if ((a >= 0x10000000UL) && (a < 0x10010000UL))
	{
		end = 0x10010000UL;
	}
	else
	{
		return 0U;
	}
	end = (end - a) / 4U;
	return (end < max) ? end : max;
}

/* ---- запис ----------------------------------------------------------------------------------------------- */
static void recStackScan(uint32_t spBefore)
{
	uint32_t found[AFLT_NSTK] = { 0 };
	int n = 0;
	uint32_t words = safeWords(spBefore, 96U);

	if ((spBefore & 3U) == 0U && words > 0U)
	{
		n = aprsFaultScanStack((const uint32_t *)spBefore, words, found, AFLT_NSTK);
	}
	for (int i = 0; i < AFLT_NSTK; i++)
	{
		BKP(S_STK0 + i) = (i < n) ? found[i] : 0U;
	}
}

/* ---- екран ----------------------------------------------------------------------------------------------- */
static void hexLine(char *dst, const char *label, uint32_t v)
{
	/* "LB " + 8 hex */
	dst[0] = label[0];
	dst[1] = label[1];
	dst[2] = ' ';
	aprsFaultHex8(&dst[3], v);
}

static void load(aprsFaultRec_t *r)
{
	uint32_t trn = BKP(S_TRN);

	r->kind = aprsFaultKindFromMagic(BKP(S_MAGIC));
	r->pc = BKP(S_PC);
	r->lr = BKP(S_LR);
	r->cfsr = BKP(S_CFSR);
	r->hfsr = BKP(S_HFSR);
	r->addr = BKP(S_ADDR);
	r->sp = BKP(S_SP);
	r->exc = BKP(S_EXC);
	r->xpsr = BKP(S_XPSR);
	r->r0 = BKP(S_R0);
	for (int i = 0; i < AFLT_NSTK; i++)
	{
		r->stk[i] = BKP(S_STK0 + i);
	}
	r->trace = trn & 0xFFFFU;
	r->traceMs = trn >> 16;
	r->traceV = BKP(S_TRV);
}

/* Підготувати дисплей: підсвітка, DMA-пересилка в стані READY (HAL_DMA_Start мовчки повертає HAL_BUSY, якщо ні). */
static void dispPrepare(void)
{
	(void)HAL_DMA_Abort(&hdma_tim1_ch1);                                            /* плавне димування підсвітки */
	HAL_GPIO_WritePin(LCD_BKLIGHT_GPIO_Port, LCD_BKLIGHT_Pin, GPIO_PIN_SET);
	if (HAL_DMA_GetState(&hdma_memtomem_dma2_stream0) != HAL_DMA_STATE_READY)
	{
		(void)HAL_DMA_Abort(&hdma_memtomem_dma2_stream0);
	}
	hdma_memtomem_dma2_stream0.State = HAL_DMA_STATE_READY;
	hdma_memtomem_dma2_stream0.Lock = HAL_UNLOCKED;
}

#define AF_NPAGES 3U

/* Намалювати сторінку звіту. Сторінка 0: вид, PC, LR (великі), CFSR, адреса збою, назва причини;
 * 1: HFSR, SP, xPSR, EXC, R0, v трасування, час; 2: адреси повернення зі стека. */
static void drawPage(const aprsFaultRec_t *r, uint32_t page)
{
	char b[24];
	const bool wdg = (r->kind == AFLT_KIND_WDG);
	size_t n;

	displayClearBuf();
	if (page == 0U)
	{
		const char *k = aprsFaultKindName(r->kind);

		n = 0U;
		while ((k[n] != 0) && (n < 12U))
		{
			b[n] = k[n];
			n++;
		}
		b[n++] = ' ';
		b[n++] = '#';
		n += aprsFaultDec(&b[n], r->trace);
		displayPrintAt(0, 0, b, FONT_SIZE_2);

		displayPrintAt(0, 18, "PC", FONT_SIZE_2);
		aprsFaultHex8(b, r->pc);
		displayPrintAt(16, 10, b, FONT_SIZE_4);
		displayPrintAt(0, 52, "LR", FONT_SIZE_2);
		aprsFaultHex8(b, r->lr);
		displayPrintAt(16, 44, b, FONT_SIZE_4);

		hexLine(b, "CF", r->cfsr);
		displayPrintAt(0, 80, b, FONT_SIZE_3);
		hexLine(b, wdg ? "IP" : "AD", r->addr);
		displayPrintAt(0, 98, b, FONT_SIZE_3);
		displayPrintAt(0, 118, aprsFaultCfsrName(r->cfsr), FONT_SIZE_2);
	}
	else if (page == 1U)
	{
		hexLine(b, "HF", r->hfsr);
		displayPrintAt(0, 0, b, FONT_SIZE_3);
		hexLine(b, "SP", r->sp);
		displayPrintAt(0, 18, b, FONT_SIZE_3);
		hexLine(b, "XP", r->xpsr);
		displayPrintAt(0, 36, b, FONT_SIZE_3);
		hexLine(b, "EX", r->exc);
		displayPrintAt(0, 54, b, FONT_SIZE_3);
		hexLine(b, wdg ? "IL" : "R0", r->r0);
		displayPrintAt(0, 72, b, FONT_SIZE_3);
		hexLine(b, "TV", r->traceV);
		displayPrintAt(0, 90, b, FONT_SIZE_3);
		b[0] = 't';
		b[1] = '=';
		n = 2U + aprsFaultDec(&b[2], r->traceMs);
		b[n++] = ' ';
		b[n++] = 'm';
		b[n++] = 's';
		b[n] = 0;
		displayPrintAt(0, 112, b, FONT_SIZE_2);
	}
	else
	{
		displayPrintAt(0, 0, "STACK (RET ADDR)", FONT_SIZE_2);
		for (int i = 0; i < AFLT_NSTK; i++)
		{
			b[0] = (char)('1' + i);
			b[1] = ' ';
			if (r->stk[i] != 0U)
			{
				aprsFaultHex8(&b[2], r->stk[i]);
			}
			else
			{
				b[2] = '-';
				b[3] = 0;
			}
			displayPrintAt(0, (uint16_t)(14 + (i * 20)), b, FONT_SIZE_3);
		}
		displayPrintAt(0, 100, "ADDR2LINE ON .MAP", FONT_SIZE_1);
	}
	displayRenderWithoutNotification();
}

/* ---- апаратний IWDG як «страховка від зависання самого обробника збою» -------------------------------------- */
/* Запускається в обробнику збою (рація й так буде скинута) і підгодовується лише у busyMs(): якщо малювання екрана
 * зависне (напр. DMA дисплея ніколи не завершиться -- HAL_DMA_PollForTransfer(HAL_MAX_DELAY) чекає вічно), через ~4 с
 * IWDG скине рацію, а запис у backup-регістрах уже збережено -- його покаже звіт при старті. Зупинити IWDG неможливо,
 * але обробник збою завжди закінчується скиданням, тож це безпечно. pr: дільник LSI = 4 << pr (0 -> /4 ... 3 -> /32, 4 -> /64). */
static void iwdgStart(uint32_t pr, uint32_t reload)
{
	IWDG->KR = 0xCCCCU;                 /* старт (далі зупинити не можна -- лише скидання) */
	IWDG->KR = 0x5555U;
	IWDG->PR = pr;
	IWDG->RLR = reload;
	for (uint32_t i = 0U; (i < 100000U) && (IWDG->SR != 0U); i++)
	{
	}
	IWDG->KR = 0xAAAAU;
}

/* ---- затримка без SysTick (в HardFault SysTick не спрацьовує) --------------------------------------------- */
static void busyMs(uint32_t ms)
{
	CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
	DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
	uint32_t t0 = DWT->CYCCNT;
	uint32_t cycles = (SystemCoreClock / 1000U) * ms;

	while ((uint32_t)(DWT->CYCCNT - t0) < cycles)
	{
		IWDG->KR = 0xAAAAU;             /* годуємо страховку обробника збою (див. вище) */
	}
}

/* ---- обробник збою --------------------------------------------------------------------------------------- */
void aprsFaultC(uint32_t *frame, uint32_t excReturn, uint32_t ipsr) __attribute__((noreturn, used));

void aprsFaultC(uint32_t *frame, uint32_t excReturn, uint32_t ipsr)
{
	uint32_t cfsr = SCB->CFSR;
	uint32_t hfsr = SCB->HFSR;
	uint32_t kind;
	uint32_t addr = 0U;
	uint32_t spBefore = 0U;
	bool frameOk;

	bkpEnable();
	switch (ipsr & 0x1FFU)
	{
		case 4U:  kind = AFLT_KIND_MEM;   break;
		case 5U:  kind = AFLT_KIND_BUS;   break;
		case 6U:  kind = AFLT_KIND_USAGE; break;
		default:  kind = AFLT_KIND_HARD;  break;
	}
	if ((cfsr & 0x80U) != 0U)          /* MMARVALID */
	{
		addr = SCB->MMFAR;
	}
	else if ((cfsr & 0x8000U) != 0U)   /* BFARVALID */
	{
		addr = SCB->BFAR;
	}

	frameOk = inRam((uint32_t)frame, 32U);
	BKP(S_CFSR) = cfsr;
	BKP(S_HFSR) = hfsr;
	BKP(S_ADDR) = addr;
	BKP(S_EXC) = (ipsr & 0x1FFU) | ((excReturn & 0xFFU) << 8);
	if (frameOk)
	{
		uint32_t frameBytes = ((excReturn & 0x10U) != 0U) ? 32U : 104U;   /* бит 4 == 0 -- розширений кадр з FPU */

		BKP(S_PC) = frame[6];
		BKP(S_LR) = frame[5];
		BKP(S_XPSR) = frame[7];
		BKP(S_R0) = frame[0];
		spBefore = (uint32_t)frame + frameBytes + (((frame[7] >> 9) & 1U) * 4U);
		BKP(S_SP) = spBefore;
		recStackScan(spBefore);
	}
	else
	{
		BKP(S_PC) = 0U;
		BKP(S_LR) = 0U;
		BKP(S_XPSR) = 0U;
		BKP(S_R0) = 0U;
		BKP(S_SP) = (uint32_t)frame;
		recStackScan(0U);
	}
	BKP(S_MAGIC) = aprsFaultMagicFromKind(kind);   /* запис дійсний -- тільки тепер */

	/* Екран: кілька сторінок по черзі, потім перезавантаження (гасить передавач). */
	{
		aprsFaultRec_t rec;

		load(&rec);
		iwdgStart(4U, 2000U);   /* ~4 с: страховка, якщо зависне саме малювання */
		dispPrepare();
		for (uint32_t i = 0U; i < AF_FAULT_PAGES_SHOWN; i++)
		{
			drawPage(&rec, i % AF_NPAGES);
			busyMs(AF_FAULT_PAGE_MS);
		}
	}
	__DSB();
	NVIC_SystemReset();
	for (;;)
	{
	}
}

/* Тонкі «голі» входи: вибрати стек (MSP/PSP) за EXC_RETURN і передати кадр у C. Місце виклику не псують -- r0..r2 вільні. */
#define AF_TRAMPOLINE_BODY \
	__asm volatile( \
		"tst lr, #4        \n" \
		"ite eq            \n" \
		"mrseq r0, msp     \n" \
		"mrsne r0, psp     \n" \
		"mov r1, lr        \n" \
		"mrs r2, ipsr      \n" \
		"b aprsFaultC      \n")

__attribute__((naked)) void HardFault_Handler(void)   { AF_TRAMPOLINE_BODY; }
__attribute__((naked)) void MemManage_Handler(void)   { AF_TRAMPOLINE_BODY; }
__attribute__((naked)) void BusFault_Handler(void)    { AF_TRAMPOLINE_BODY; }
__attribute__((naked)) void UsageFault_Handler(void)  { AF_TRAMPOLINE_BODY; }

/* ---- трасування -------------------------------------------------------------------------------------------- */
void aprsFaultTraceMark(void)
{
	BKP(S_T0) = ticksGetMillis();
	BKP(S_TRN) = 0U;
}

uint32_t aprsFaultTraceNote(uint32_t n, uint32_t v)
{
	uint32_t now = ticksGetMillis();
	uint32_t trn = BKP(S_TRN);
	uint32_t t0 = BKP(S_T0);
	uint32_t last = t0 + (trn >> 16);
	uint32_t dt;

	/* Нова серія, якщо від попереднього кроку (або від мітки) минуло > 3 с: t відлічуємо від цього кроку. Після скидання
	 * тіки йдуть знову з нуля, тому «минуло» у вигляді uint32 стає величезним -- теж нова серія. */
	if ((uint32_t)(now - last) > 3000U)
	{
		t0 = now;
		BKP(S_T0) = t0;
	}
	dt = now - t0;
	BKP(S_TRN) = (((dt > 0xFFFFU) ? 0xFFFFU : dt) << 16) | (n & 0xFFFFU);
	BKP(S_TRV) = v;
	aprsFaultKick();
	return dt;
}

/* ---- kick / арм ------------------------------------------------------------------------------------------- */
void aprsFaultKick(void)
{
	uint32_t k = BKP(S_KICK);

	BKP(S_KICK) = (k & (KICK_ARMED | KICK_IWDG)) | ((k + 1U) & KICK_CNT);
#if defined(APRS_FAULT_IWDG)
	if ((k & KICK_IWDG) != 0U)
	{
		IWDG->KR = 0xAAAAU;
	}
#endif
}

void aprsFaultArm(bool on)
{
	uint32_t k = BKP(S_KICK);

	if (on)
	{
#if defined(APRS_FAULT_IWDG)
		if ((k & KICK_IWDG) == 0U)
		{
			iwdgStart(3U, 2000U);   /* LSI/32 ~ 1 кГц, 2000 -> ~2 с (LSI 17..47 кГц -- розкид 1,4..3,8 с) */
			k |= KICK_IWDG;
		}
#endif
		k |= KICK_ARMED;
	}
	else
	{
		k &= ~KICK_ARMED;
	}
	BKP(S_KICK) = (k & (KICK_ARMED | KICK_IWDG)) | ((k + 1U) & KICK_CNT);
	if (!on)
	{
		BKP(S_WSEEN) = 0U;
	}
}

void aprsFaultLoopTick(bool modeActive)
{
	uint32_t k = BKP(S_KICK);

	if (modeActive != ((k & KICK_ARMED) != 0U))
	{
		aprsFaultArm(modeActive);
	}
	else
	{
		aprsFaultKick();
	}
}

/* ---- програмний сторож (TIM7, пріоритет 0) -------------------------------------------------------------------- */
void aprsWdgC(uint32_t *frame, uint32_t excReturn) __attribute__((used));

void aprsWdgC(uint32_t *frame, uint32_t excReturn)
{
	uint32_t k;
	uint32_t seen;
	uint32_t stuck;
	uint32_t pc = 0U, lr = 0U, sp = 0U, ipc = 0U, ilr = 0U;
	uint32_t cur;
	uint32_t task;

	TIM7->SR = 0U;                       /* зняти прапорець оновлення */
	k = BKP(S_KICK);
	if ((k & KICK_ARMED) == 0U)
	{
		BKP(S_WSEEN) = 0U;
		return;
	}
	seen = BKP(S_WSEEN);
	if ((k & 0xFFFFU) != (seen & 0xFFFFU))
	{
		BKP(S_WSEEN) = (k & 0xFFFFU);
		return;
	}
	stuck = (seen >> 16) + 1U;
	if (stuck < APRS_FAULT_WDG_TICKS)
	{
		BKP(S_WSEEN) = (seen & 0xFFFFU) | (stuck << 16);
		return;
	}

	/* ---- спрацював: зберегти, де що було, і перезавантажити ---- */
	if (inRam((uint32_t)frame, 32U))
	{
		ipc = frame[6];
		ilr = frame[5];
	}
	cur = (uint32_t)xTaskGetCurrentTaskHandle();
	task = BKP(S_TASK);
	if ((task != 0U) && (task == cur) && inRam((uint32_t)frame, 32U))
	{
		/* перервано саме головне завдання -- його PC/LR це і є місце зависання */
		uint32_t fb = ((excReturn & 0x10U) != 0U) ? 32U : 104U;

		pc = frame[6];
		lr = frame[5];
		sp = (uint32_t)frame + fb;
	}
	else if ((task != 0U) && inRam(task, 4U))
	{
		/* головне завдання витіснене: його контекст лежить на його стеку (порт CM4F: r4-r11, EXC_RETURN, [s16-s31], r0-r3, r12, lr, pc, xpsr) */
		uint32_t top = *(volatile uint32_t *)task;

		if (inRam(top, 4U * 9U) && (safeWords(top, 9U + 16U + 8U) >= (9U + 8U)))
		{
			uint32_t ex = ((volatile uint32_t *)top)[8];
			uint32_t hw = top + (4U * 9U) + (((ex & 0x10U) == 0U) ? (4U * 16U) : 0U);

			if (inRam(hw, 32U))
			{
				pc = ((volatile uint32_t *)hw)[6];
				lr = ((volatile uint32_t *)hw)[5];
				sp = hw + (((ex & 0x10U) == 0U) ? 104U : 32U);
			}
		}
	}
	BKP(S_PC) = pc;
	BKP(S_LR) = lr;
	BKP(S_CFSR) = 0U;
	BKP(S_HFSR) = 0U;
	BKP(S_ADDR) = ipc;
	BKP(S_SP) = sp;
	BKP(S_EXC) = 0U;
	BKP(S_XPSR) = 0U;
	BKP(S_R0) = ilr;
	recStackScan(sp);
	BKP(S_MAGIC) = aprsFaultMagicFromKind(AFLT_KIND_WDG);
	__DSB();
	NVIC_SystemReset();
}

__attribute__((naked)) void TIM7_IRQHandler(void)
{
	__asm volatile(
		"tst lr, #4        \n"
		"ite eq            \n"
		"mrseq r0, msp     \n"
		"mrsne r0, psp     \n"
		"mov r1, lr        \n"
		"b aprsWdgC        \n");
}

/* ---- ініціалізація ------------------------------------------------------------------------------------------- */
void aprsFaultInit(void)
{
	uint32_t f;

	bkpEnable();
	BKP(S_TASK) = (uint32_t)xTaskGetCurrentTaskHandle();
	BKP(S_KICK) = 0U;                        /* після скидання сторож вимкнено (арм -- у головному циклі); IWDG теж скинуто */
	BKP(S_WSEEN) = 0U;

#if defined(APRS_FAULT_IWDG)
	if ((RCC->CSR & RCC_CSR_IWDGRSTF) != 0U)
	{
		if (aprsFaultKindFromMagic(BKP(S_MAGIC)) == AFLT_KIND_NONE)
		{
			/* IWDG скинув без нашого запису: лишився лише останній крок трасування */
			for (int i = S_PC; i <= S_STK3; i++)
			{
				BKP(i) = 0U;
			}
			BKP(S_MAGIC) = aprsFaultMagicFromKind(AFLT_KIND_IWDG);
		}
	}
	RCC->CSR |= RCC_CSR_RMVF;                 /* інакше прапорець IWDG лишався б після кожного наступного скидання */
#endif

	/* TIM7: 10 Гц. Тактування таймера = PCLK1, помноженого на 2, якщо дільник APB1 != 1. */
	__HAL_RCC_TIM7_CLK_ENABLE();
	f = HAL_RCC_GetPCLK1Freq();
	if ((RCC->CFGR & RCC_CFGR_PPRE1_2) != 0U)
	{
		f *= 2U;
	}
	TIM7->CR1 = 0U;
	TIM7->PSC = (uint16_t)((f / 10000U) - 1U);     /* 10 кГц */
	TIM7->ARR = 999U;                                /* 100 мс */
	TIM7->EGR = TIM_EGR_UG;
	TIM7->SR = 0U;
	TIM7->DIER = TIM_DIER_UIE;
	NVIC_SetPriority(TIM7_IRQn, 0U);                 /* вищий за configMAX_SYSCALL_INTERRUPT_PRIORITY: не маскується критичними секціями FreeRTOS */
	NVIC_EnableIRQ(TIM7_IRQn);
	TIM7->CR1 = TIM_CR1_CEN;
}

/* ---- звіт при старті ----------------------------------------------------------------------------------------- */
static bool anyKeyDown(void)
{
	return (keyboardRead() != KEY_NONE) || (buttonsRead() != 0U);
}

static void waitKey(void)
{
	uint32_t t0 = ticksGetMillis();

	while (anyKeyDown() && ((ticksGetMillis() - t0) < 2000U))   /* спершу відпустити те, що тримали при вмиканні */
	{
		vTaskDelay(20U / portTICK_PERIOD_MS);
	}
	t0 = ticksGetMillis();
	while ((ticksGetMillis() - t0) < 600000U)                   /* до 10 хв -- далі продовжити старт */
	{
		vTaskDelay(20U / portTICK_PERIOD_MS);
		if (anyKeyDown())
		{
			vTaskDelay(40U / portTICK_PERIOD_MS);
			if (anyKeyDown())
			{
				break;
			}
		}
	}
}

bool aprsFaultBootReport(void)
{
	aprsFaultRec_t rec;

	bkpEnable();
	load(&rec);
	if (rec.kind == AFLT_KIND_NONE)
	{
		return false;
	}
	dispPrepare();
	for (uint32_t p = 0U; p < AF_NPAGES; p++)
	{
		drawPage(&rec, p);
		waitKey();
	}
	BKP(S_MAGIC) = 0U;     /* показано -- стерти, щоб не з'являтись при кожному старті */
	return true;
}

#endif /* APRS_RX */
