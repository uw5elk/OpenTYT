/*
 * test_volume_probe.c -- R77A: діагностичний екран «Гучн. проба». Збирається з СПРАВЖНІМ functions/volume_probe.c (заглушки лише для обладнання:
 * radioWriteReg2byte, режим/частота, час, APRS-стани). Перевіряється:
 *  1  таблиці (R77B): DMR 1x...1/64 = 0...-36 дБ; FM 80/60/40/25/15/10/6/3/1,5 % -> 0xCC/0x99/0x66/0x40/0x26/0x1A/0x0F/0x08/0x04, дБ розрахункові (80 % збігається зі стоковим 0x06CC);
 *  2  вихід з екрана повертає стокове (DMR зсув 0, FM 0x06CC) -- і після кожного з автоповернень: передача, APRS, зміна каналу, зміна режиму, таймаут 2 хв;
 *  3  FM-крок не пишеться, поки працює APRS-приймач або «Режим APRS», і не пишеться в цифровому режимі; DMR-регістр 0x44 не пишеться НІКОЛИ
 *     (усі записи -- лише 0x44 з високим байтом 0x06 і лише в аналоговому режимі);
 *  4  старт передачі (volumeProbeStopForTx) повертає 0x06CC ДО передачі;
 *  5  хотспот (settingsUsbMode != CPS): екран не відкривається, нічого не змінюється;
 *  6  множник DMR: арифметичний зсув, 0 лишається 0, знак зберігається, для зсуву 0 відлік не змінюється;
 *  7  без прапорця (ця таблиця) -- стокове: кроки 0 -> зсув 0, FM-байт 0xCC.
 */
#include <stdio.h>
#include <math.h>
#include <string.h>
#include "functions/volume_probe.h"
#include "functions/trx.h"
#include "functions/settings.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

/* --- заглушки обладнання --- */
volatile bool trxTransmissionEnabled;
volatile int settingsUsbMode;
static int s_mode = RADIO_MODE_ANALOG;
static uint32_t s_freq = 145500000U;
static uint32_t s_now;
static bool s_aprsRx, s_aprsMode;
static int s_wrN;
static struct { uint8_t reg, hi, lo; } s_wr[64];
static int s_dmrHit44;           /* записів 0x44 з високим байтом 0x07 (DMR) -- мусить лишитись 0 */

bool radioWriteReg2byte(uint8_t reg, uint8_t v1, uint8_t v2)
{
	if (s_wrN < 64) { s_wr[s_wrN].reg = reg; s_wr[s_wrN].hi = v1; s_wr[s_wrN].lo = v2; s_wrN++; }
	if ((reg == 0x44) && (v1 == 0x07)) { s_dmrHit44++; }
	return true;
}
int trxGetMode(void) { return s_mode; }
uint32_t trxGetFrequency(void) { return s_freq; }
uint32_t ticksGetMillis(void) { return s_now; }
bool aprsRxIsRunning(void) { return s_aprsRx; }
bool aprsModeIsActive(void) { return s_aprsMode; }

static void reset(void)
{
	volumeProbeClose();
	trxTransmissionEnabled = false;
	settingsUsbMode = USB_MODE_CPS;
	s_mode = RADIO_MODE_ANALOG; s_freq = 145500000U; s_now = 1000U; s_aprsRx = s_aprsMode = false; s_wrN = 0;
}
static bool lastWriteIs(uint8_t lo) { return (s_wrN > 0) && (s_wr[s_wrN - 1].reg == 0x44) && (s_wr[s_wrN - 1].hi == 0x06) && (s_wr[s_wrN - 1].lo == lo); }

int main(void)
{
	printf("test_volume_probe\n");
#if !defined(VOLUME_PROBE)
	printf("  FAIL VOLUME_PROBE не визначено (потрібні -DENABLE_VOLUME_PROBE -DLANGUAGE_BUILD_UKRAINIAN і Plus 10W)\n");
	return 1;
#else
	/* 1: таблиці */
	{
		static const int db[VP_DMR_STEPS] = { 0, -6, -12, -18, -24, -30, -36 };
		static const uint16_t pm[VP_FM_STEPS] = { 800, 600, 400, 250, 150, 100, 60, 30, 15 };
		static const uint8_t lo[VP_FM_STEPS] = { 0xCC, 0x99, 0x66, 0x40, 0x26, 0x1A, 0x0F, 0x08, 0x04 };
		CHECK(VP_DMR_STEPS == 7 && VP_FM_STEPS == 9, "R77B: 7 кроків DMR і 9 кроків FM");
		for (uint8_t i = 0; i < VP_DMR_STEPS; i++) { CHECK(vpDmrDb(i) == db[i] && vpDmrShift(i) == i, "DMR крок %u: %d дБ", i, db[i]); }
		for (uint8_t i = 0; i < VP_FM_STEPS; i++) { CHECK(vpFmPermille(i) == pm[i] && vpFmLow(i) == lo[i], "FM крок %u: %u промілле -> 0x%02X", i, pm[i], lo[i]); }
		CHECK(vpFmLow(0) == VP_FM_STOCK_LOW && VP_FM_HIGH == 0x06, "FM крок 0 == стокове 0x06CC");
		int mono = 1;
		for (uint8_t i = 1; i < VP_FM_STEPS; i++) { if (vpFmLow(i) >= vpFmLow(i - 1)) mono = 0; }
		for (uint8_t i = 1; i < VP_DMR_STEPS; i++) { if (vpDmrShift(i) <= vpDmrShift(i - 1)) mono = 0; }
		CHECK(mono, "таблиці монотонні: кожен крок тихіший за попередній");
		CHECK(vpFmLow(VP_FM_STEPS - 1) >= 1, "найглибший FM-байт не нуль (0x04)");
		/* розрахункове дБ: таблиця десятих збігається з 20*log10(low/0xCC) (не гірше 0,1 дБ), округлене -- не гірше 0,5 */
		for (uint8_t i = 0; i < VP_FM_STEPS; i++)
		{
			double ex = 20.0 * log10((double)vpFmLow(i) / (double)VP_FM_STOCK_LOW);
			CHECK(fabs(vpFmDbTenths(i) / 10.0 - ex) <= 0.1, "FM крок %u: %.1f дБ розрахункове (таблиця %d/10)", i, ex, (int)vpFmDbTenths(i));
			CHECK(fabs((double)vpFmDb(i) - ex) <= 0.51, "FM крок %u: округлене %d дБ", i, vpFmDb(i));
		}
		CHECK(vpFmDb(0) == 0 && vpFmDb(8) == -34 && vpFmDb(5) == -18, "дБ: стокове 0, останній -34, 10 %% -18");
		CHECK(vpDmrShift(9) == 0 && vpFmLow(9) == 0xCC, "неправильний крок -> стокове");
	}
	/* 6: множник */
	CHECK(vpDmrApply(1000, 0) == 1000 && vpDmrApply(-1000, 0) == -1000, "зсув 0: відлік без змін");
	CHECK(vpDmrApply(1000, 1) == 500 && vpDmrApply(1000, 3) == 125 && vpDmrApply(-1000, 2) == -250, "зсуви 1/3, знак зберігається");
	CHECK(vpDmrApply(0, 3) == 0 && vpDmrApply(32767, 3) == 4095 && vpDmrApply(-32768, 3) == -4096, "нуль і краї діапазону");
	CHECK(vpDmrApply(32767, 6) == 511 && vpDmrApply(-32768, 6) == -512 && vpDmrApply(6400, 6) == 100, "глибокий зсув 6 (1/64)");
	CHECK(vpDmrApply(1024, 7) == vpDmrApply(1024, 6) && vpDmrApply(1024, 200) == 16, "зсув понад 6 обрізається до 6");

	/* 7: початковий стан */
	reset();
	CHECK(volumeProbeDmrShift == 0, "до відкриття: DMR зсув 0");

	/* відкрити, змінити, вийти -> стокове */
	reset();
	volumeProbeOpen();
	CHECK(volumeProbeIsOn() && volumeProbeDmrStep() == 0 && volumeProbeFmStep() == 0, "відкрито: обидва кроки стокові");
	volumeProbeAdjust(+1); volumeProbeAdjust(+1);
	CHECK(volumeProbeDmrStep() == 2 && volumeProbeDmrShift == 2, "DMR крок 2 -> зсув 2");
	volumeProbeAdjust(+9);
	CHECK(volumeProbeDmrStep() == 6 && volumeProbeDmrShift == 6, "DMR крок обмежено згори (1/64)");
	volumeProbeToggleSelect();
	volumeProbeAdjust(+1);
	CHECK(volumeProbeFmStep() == 1 && lastWriteIs(0x99), "FM крок 1 -> 0x0699");
	volumeProbeAdjust(+9);
	CHECK(volumeProbeFmStep() == 8 && lastWriteIs(0x04), "FM крок 8 -> 0x0604 (1,5 %%)");
	volumeProbeClose();
	CHECK(!volumeProbeIsOn() && volumeProbeDmrShift == 0, "вихід: DMR зсув 0");
	CHECK(lastWriteIs(0xCC), "вихід: FM повернуто 0x06CC");
	{ int n = s_wrN; volumeProbeClose(); CHECK(n == s_wrN, "повторний Close нічого не пише"); }

	/* 2: автоповернення */
	{
		struct { const char *name; int how; } cases[] = { {"передача", 0}, {"APRS-приймач", 1}, {"«Режим APRS»", 2}, {"зміна каналу", 3}, {"зміна режиму", 4}, {"таймаут 2 хв", 5}, {"хотспот", 6} };
		for (unsigned c = 0; c < sizeof(cases) / sizeof(cases[0]); c++)
		{
			reset();
			volumeProbeOpen();
			volumeProbeAdjust(+2);                 /* DMR крок 2 */
			volumeProbeToggleSelect(); volumeProbeAdjust(+2);   /* FM крок 2 -> 0x66 записано */
			CHECK(lastWriteIs(0x66), "[%s] FM крок записано", cases[c].name);
			switch (cases[c].how)
			{
				case 0: trxTransmissionEnabled = true; break;
				case 1: s_aprsRx = true; break;
				case 2: s_aprsMode = true; break;
				case 3: s_freq += 12500U; break;
				case 4: s_mode = RADIO_MODE_DIGITAL; break;
				case 5: s_now += VP_TIMEOUT_MS + 1U; break;
				case 6: settingsUsbMode = USB_MODE_HOTSPOT; break;
			}
			vpRestore_t r = volumeProbeTick();
			CHECK(r != VP_KEEP && !volumeProbeIsOn(), "[%s] екран закрито автоматично (%d)", cases[c].name, (int)r);
			CHECK(volumeProbeDmrShift == 0, "[%s] DMR зсув 0", cases[c].name);
			if (cases[c].how == 4)
			{
				CHECK(!lastWriteIs(0xCC), "[%s] у цифровому режимі 0x06CC НЕ пишемо (0x44 уже переписав AT1846DMRSettings)", cases[c].name);
			}
			else
			{
				CHECK(lastWriteIs(0xCC), "[%s] FM повернуто 0x06CC", cases[c].name);
			}
		}
		reset();
		volumeProbeOpen();
		s_now += VP_TIMEOUT_MS - 1000U;
		CHECK(volumeProbeTick() == VP_KEEP && volumeProbeIsOn(), "за секунду до таймауту екран ще відкритий");
		CHECK(volumeProbeSecondsLeft() == 1, "лишилось 1 с");
	}

	/* 3: захисти FM */
	reset();
	s_aprsRx = true;
	volumeProbeOpen();
	volumeProbeToggleSelect();
	{
		int n = s_wrN;
		volumeProbeAdjust(+1);
		CHECK(s_wrN == n && volumeProbeFmBlocked() && !volumeProbeFmApplies(), "APRS-приймач працює: FM-крок НЕ пишеться, екран знає про блок");
	}
	volumeProbeClose();
	reset();
	s_aprsMode = true;
	volumeProbeOpen(); volumeProbeToggleSelect();
	{
		int n = s_wrN;
		volumeProbeAdjust(+1);
		CHECK(s_wrN == n && volumeProbeFmBlocked(), "«Режим APRS»: FM-крок НЕ пишеться");
	}
	volumeProbeClose();
	reset();
	s_mode = RADIO_MODE_DIGITAL;
	volumeProbeOpen(); volumeProbeToggleSelect();
	{
		int n = s_wrN;
		volumeProbeAdjust(+1);
		CHECK(s_wrN == n && !volumeProbeFmApplies(), "цифровий режим: FM-крок НЕ пишеться");
		volumeProbeToggleSelect(); volumeProbeAdjust(+1);
		CHECK(s_wrN == n && volumeProbeDmrShift == 1, "цифровий режим: DMR-множник діє, регістрів не пишемо");
	}
	volumeProbeClose();
	CHECK(s_dmrHit44 == 0, "регістр 0x44 з DMR-значенням (високий байт 0x07) не писався жодного разу");
	{
		int bad = 0;
		for (int i = 0; i < s_wrN; i++) { if (s_wr[i].reg != 0x44 || s_wr[i].hi != 0x06) bad++; }
		CHECK(bad == 0, "усі записи в кодек -- лише 0x44 з високим байтом 0x06");
	}

	/* 4: старт передачі */
	reset();
	volumeProbeOpen(); volumeProbeToggleSelect(); volumeProbeAdjust(+3);
	CHECK(lastWriteIs(0x40), "FM 25 %% записано");
	volumeProbeStopForTx();
	CHECK(lastWriteIs(0xCC) && !volumeProbeIsOn(), "volumeProbeStopForTx повертає 0x06CC до передачі");

	/* 5: хотспот */
	reset();
	settingsUsbMode = USB_MODE_HOTSPOT;
	volumeProbeOpen();
	CHECK(!volumeProbeIsOn(), "хотспот: екран не відкрито");
	volumeProbeAdjust(+1);
	CHECK(volumeProbeDmrShift == 0 && s_wrN == 0, "хотспот: нічого не змінено");

	/* скидання всього без виходу */
	reset();
	volumeProbeOpen(); volumeProbeAdjust(+3); volumeProbeToggleSelect(); volumeProbeAdjust(+2);
	volumeProbeResetAll();
	CHECK(volumeProbeIsOn() && volumeProbeDmrShift == 0 && lastWriteIs(0xCC), "«0»: обидва кроки стокові, екран лишається");
	volumeProbeClose();
#endif
	printf("%s\n", fails ? "ПРОВАЛ" : "OK");
	return fails ? 1 : 0;
}
