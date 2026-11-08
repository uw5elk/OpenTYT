/*
 * volume_probe.c -- R77A: діагностичний екран «Гучн. проба», логіка й запис регістра. Див. volume_probe.h і volume_probe_logic.h.
 * Нового шляху запису в кодек немає: FM -- наявна radioWriteReg2byte() (з кешем регістрів: повторне те саме значення не пишеться); DMR -- лише
 * множник у soundRefillData(). DMR-регістр AT1846S 0x44 (0x07FF) не чіпається ніколи.
 */
#include "functions/volume_probe.h"

#if defined(VOLUME_PROBE)
#include "functions/trx.h"
#include "functions/settings.h"
#include "hardware/AT1846S.h"
#include "functions/ticks.h"
#if defined(APRS_RX)
#include "functions/aprs_rx.h"
#include "functions/aprs_mode.h"
#endif

volatile uint8_t volumeProbeDmrShift = 0U;

static bool     s_on;
static uint8_t  s_sel;            /* 0 -- DMR, 1 -- FM */
static uint8_t  s_dmr;            /* крок DMR 0..VP_DMR_STEPS-1 */
static uint8_t  s_fm;             /* крок FM 0..VP_FM_STEPS-1 */
static bool     s_fmWritten;      /* ми писали 0x44 не-стоковим значенням: при виході треба повернути */
static uint8_t  s_mode;           /* режим (аналог/цифра) на вході */
static uint32_t s_freq;           /* RX-частота на вході */
static uint32_t s_t0;             /* тік входу */

static bool aprsBlocked(void)
{
#if defined(APRS_RX)
	return vpFmBlocked(aprsRxIsRunning(), aprsModeIsActive());
#else
	return false;
#endif
}

bool volumeProbeIsOn(void)
{
	return s_on;
}

bool volumeProbeFmBlocked(void)
{
	return aprsBlocked();
}

bool volumeProbeFmApplies(void)
{
	return s_on && (trxGetMode() == RADIO_MODE_ANALOG) && (aprsBlocked() == false) && (trxTransmissionEnabled == false);
}

/* Записати 0x44 для поточного FM-кроку, якщо це дозволено; інакше FM лишається стоковим. */
static void applyFm(void)
{
	if (volumeProbeFmApplies() && (s_fm != 0U))
	{
		radioWriteReg2byte(VP_FM_REG, VP_FM_HIGH, vpFmLow(s_fm));
		s_fmWritten = true;
	}
	else if (s_fmWritten && (trxGetMode() == RADIO_MODE_ANALOG))
	{
		radioWriteReg2byte(VP_FM_REG, VP_FM_HIGH, VP_FM_STOCK_LOW);
		s_fmWritten = false;
	}
	else if (s_fmWritten)
	{
		/* режим змінився на цифровий: AT1846DMRSettings уже переписали 0x44 (0x07FF) -- не чіпаємо */
		s_fmWritten = false;
	}
}

static void applyDmr(void)
{
	volumeProbeDmrShift = vpDmrShift(s_dmr);
}

void volumeProbeOpen(void)
{
	if (settingsUsbMode != USB_MODE_CPS)      /* хотспот/налагодження: ніяких змін */
	{
		return;
	}
	s_on = true;
	s_sel = 0U;
	s_dmr = 0U;
	s_fm = 0U;
	s_fmWritten = false;
	s_mode = (uint8_t)trxGetMode();
	s_freq = trxGetFrequency();
	s_t0 = ticksGetMillis();
	applyDmr();
}

void volumeProbeClose(void)
{
	if (s_on == false)
	{
		return;
	}
	s_dmr = 0U;
	s_fm = 0U;
	applyDmr();
	/* FM: якщо 0x44 міняли -- повернути 0x06CC (аналог) */
	if (s_fmWritten)
	{
		if (trxGetMode() == RADIO_MODE_ANALOG)
		{
			radioWriteReg2byte(VP_FM_REG, VP_FM_HIGH, VP_FM_STOCK_LOW);
		}
		s_fmWritten = false;
	}
	s_on = false;
}

void volumeProbeStopForTx(void)
{
	/* trxTransmissionEnabled ще не виставлено, тож відновлення йде через стокову гілку нижче -- але FM-регістр треба повернути ДО передачі */
	volumeProbeClose();
}

vpRestore_t volumeProbeTick(void)
{
	if (s_on == false)
	{
		return VP_KEEP;
	}
	bool changed = ((uint8_t)trxGetMode() != s_mode) || (trxGetFrequency() != s_freq) || (settingsUsbMode != USB_MODE_CPS);
	vpRestore_t r = vpRestoreReason(trxTransmissionEnabled, aprsBlocked(), (s_fm != 0U), changed, ticksGetMillis() - s_t0);

	if (r != VP_KEEP)
	{
		volumeProbeClose();
	}
	return r;
}

void volumeProbeToggleSelect(void)
{
	s_sel ^= 1U;
}

void volumeProbeAdjust(int dir)
{
	if (s_on == false)
	{
		return;
	}
	if (s_sel == 0U)
	{
		int v = (int)s_dmr + dir;
		s_dmr = (uint8_t)((v < 0) ? 0 : ((v >= (int)VP_DMR_STEPS) ? (int)(VP_DMR_STEPS - 1U) : v));
		applyDmr();
	}
	else
	{
		int v = (int)s_fm + dir;
		s_fm = (uint8_t)((v < 0) ? 0 : ((v >= (int)VP_FM_STEPS) ? (int)(VP_FM_STEPS - 1U) : v));
		applyFm();
	}
}

void volumeProbeResetAll(void)
{
	s_dmr = 0U;
	s_fm = 0U;
	applyDmr();
	applyFm();
}

uint8_t volumeProbeSelected(void)
{
	return s_sel;
}

uint8_t volumeProbeDmrStep(void)
{
	return s_dmr;
}

uint8_t volumeProbeFmStep(void)
{
	return s_fm;
}

uint32_t volumeProbeSecondsLeft(void)
{
	uint32_t el = ticksGetMillis() - s_t0;
	return (el >= VP_TIMEOUT_MS) ? 0U : ((VP_TIMEOUT_MS - el) / 1000U);
}
#endif /* VOLUME_PROBE */
