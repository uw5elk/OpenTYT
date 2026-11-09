/*
 * volume_low.c -- R78: «Мін.гучність» (постійний тихий нижній рівень). Див. volume_low.h і volume_low_logic.h.
 * Нового шляху запису в кодек немає: FM -- наявна radioWriteReg2byte() (кеш регістрів: те саме значення вдруге не пишеться, тож щомілісекундний
 * виклик нічого не коштує, поки значення стоїть); DMR -- множник у soundRefillData(). DMR-значення 0x44 (0x07FF) не чіпається ніколи.
 */
#include "functions/volume_low.h"

#if defined(VOLUME_LOW)
#include "functions/trx.h"
#include "functions/settings.h"
#include "functions/codeplug.h"
#include "hardware/AT1846S.h"
#if defined(ENABLE_VOLUME_PROBE)
#include "functions/volume_probe.h"   /* визначає VOLUME_PROBE (лише діагностична збірка) */
#endif
#if defined(APRS_RX)
#include "functions/aprs_rx.h"
#include "functions/aprs_mode.h"
#endif

volatile uint16_t volumeLowDmrGainQ15 = VOLLOW_Q15_UNITY;

static uint8_t s_mode;                 /* 0..3, живе значення */
static uint8_t s_pos = VOLLOW_POS_MAX; /* позиція ручки, на якій вона встоялась (до першого встоювання -- без ослаблення) */
static uint8_t s_gate = 0xFFU;         /* бітова маска умов на момент останнього перерахунку (0xFF -- примусово перерахувати) */
static uint8_t s_fmLow = VOLLOW_FM_STOCK_LOW;  /* бажаний low-byte 0x44 для FM (стокове -- не пишемо) */
static bool    s_fmWritten;            /* ми колись писали не-стокове значення в 0x44 і ще не повернули */

static bool aprsActive(void)
{
#if defined(APRS_RX)
	return aprsRxIsRunning() || aprsModeIsActive();
#else
	return false;
#endif
}

static bool probeOpen(void)
{
#if defined(VOLUME_PROBE)
	return volumeProbeIsOn();
#else
	return false;
#endif
}

static uint8_t gateBits(void)
{
	int mode = trxGetMode();

	return (uint8_t)(((mode == RADIO_MODE_ANALOG) ? 1U : 0U) | ((mode == RADIO_MODE_DIGITAL) ? 2U : 0U) | (trxTransmissionEnabled ? 4U : 0U)
			| (aprsActive() ? 8U : 0U) | (probeOpen() ? 16U : 0U) | ((settingsUsbMode == USB_MODE_CPS) ? 32U : 0U));
}

/* Перерахувати цілі за s_mode, s_pos і умовами. */
static void evaluate(uint8_t gate)
{
	const uint8_t knee = vlKnee(s_mode);
	const uint8_t xDmr = vlExtraDb(s_pos, knee, VOLLOW_DEPTH_DMR_DB);
	const uint8_t xFm = vlExtraDb(s_pos, knee, VOLLOW_DEPTH_FM_DB);
	const bool usbCps = ((gate & 32U) != 0U);
	const bool probe = ((gate & 16U) != 0U);

	volumeLowDmrGainQ15 = vlDmrAllowed((gate & 2U) != 0U, probe, usbCps) ? vlDmrGainQ15(xDmr) : (uint16_t)VOLLOW_Q15_UNITY;
	s_fmLow = vlFmAllowed((gate & 1U) != 0U, (gate & 4U) != 0U, (gate & 8U) != 0U, probe, usbCps) ? vlFmLow(xFm) : (uint8_t)VOLLOW_FM_STOCK_LOW;
	s_gate = gate;
}

/* Привести 0x44 у відповідність до s_fmLow. Нестокове пишемо при кожному виклику (кеш відсіює повтори -- і відновлює значення, якщо стокові налаштування
 * FM переписали регістр при зміні каналу/смуги); стокове -- лише один раз після нестокового і лише в аналоговому режимі (у цифровому
 * AT1846DMRSettings уже переписали 0x44 = 0x07FF -- не чіпаємо). Під час передачі не пишемо нічого. */
static void applyFm(void)
{
	if (trxTransmissionEnabled)
	{
		return;
	}
	if (s_fmLow != VOLLOW_FM_STOCK_LOW)
	{
		if (trxGetMode() == RADIO_MODE_ANALOG)
		{
			radioWriteReg2byte(VOLLOW_FM_REG, VOLLOW_FM_HIGH, s_fmLow);
			s_fmWritten = true;
		}
	}
	else if (s_fmWritten)
	{
		if (trxGetMode() == RADIO_MODE_ANALOG)
		{
			radioWriteReg2byte(VOLLOW_FM_REG, VOLLOW_FM_HIGH, VOLLOW_FM_STOCK_LOW);
		}
		s_fmWritten = false;
	}
}

void volumeLowLoad(void)
{
	uint8_t raw = 0U;

	if (codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG, &raw, 1) == false)
	{
		raw = 0U;
	}
	s_mode = vlModeSanitize(raw);
	s_gate = 0xFFU;
}

uint8_t volumeLowGetMode(void)
{
	return s_mode;
}

void volumeLowSetMode(uint8_t mode)
{
	s_mode = vlModeSanitize(mode);
	s_gate = 0xFFU;
}

bool volumeLowSave(void)
{
	uint8_t cur = 0U;
	uint8_t want = s_mode;
	const bool have = codeplugGetOpenGD77CustomDataBounded(CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG, &cur, 1);

	/* Знос флеша: блоку немає і режим «вимк» -- не створюємо блок; те саме значення -- не пишемо. */
	if ((have == false) ? (want == 0U) : (vlModeSanitize(cur) == want))
	{
		return true;
	}
	return codeplugSetOpenGD77CustomData(CODEPLUG_CUSTOM_DATA_TYPE_VOLUME_LOW_CFG, &want, 1);
}

void volumeLowPotSettled(int8_t lastVolume)
{
	s_pos = vlPos(lastVolume);
	s_gate = 0xFFU;
}

void volumeLowTick(void)
{
	if ((s_mode == 0U) && (s_fmWritten == false) && (volumeLowDmrGainQ15 == VOLLOW_Q15_UNITY))
	{
		return;     /* вимкнено і нічого не повертати -- нуль роботи */
	}
	{
		const uint8_t gate = gateBits();

		if (gate != s_gate)
		{
			evaluate(gate);
		}
	}
	applyFm();
}

void volumeLowStopForTx(void)
{
	if (s_fmWritten)
	{
		if (trxGetMode() == RADIO_MODE_ANALOG)
		{
			radioWriteReg2byte(VOLLOW_FM_REG, VOLLOW_FM_HIGH, VOLLOW_FM_STOCK_LOW);
		}
		s_fmWritten = false;
	}
	s_gate = 0xFFU;    /* після передачі умови перерахуються самі */
}
#endif /* VOLUME_LOW */
