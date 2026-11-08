/*
 * test_volume_probe.c -- R77A: діагностичний екран «Гучн. проба». Збирається з СПРАВЖНІМ functions/volume_probe.c (заглушки лише для обладнання:
 * radioWriteReg2byte, режим/частота, час, APRS-стани). Перевіряється:
 *  1  таблиці: DMR 1x/1/2/1/4/1/8 = 0/-6/-12/-18 дБ; FM 80/60/40/25/15 % -> 0xCC/0x99/0x66/0x40/0x26 (80 % збігається зі стоковим 0x06CC);
 *  2  вихід з екрана повертає стокове (DMR зсув 0, FM 0x06CC) -- і після кожного з автоповернень: передача, APRS, зміна каналу, зміна режиму, таймаут 2 хв;
 *  3  FM-крок не пишеться, поки працює APRS-приймач або «Режим APRS», і не пишеться в цифровому режимі; DMR-регістр 0x44 не пишеться НІКОЛИ
 *     (усі записи -- лише 0x44 з високим байтом 0x06 і лише в аналоговому режимі);
 *  4  старт передачі (volumeProbeStopForTx) повертає 0x06CC ДО передачі;
 *  5  хотспот (settingsUsbMode != CPS): екран не відкривається, нічого не змінюється;
 *  6  множник DMR: арифметичний зсув, 0 лишається 0, знак зберігається, для зсуву 0 відлік не змінюється;
 *  7  без прапорця (ця таблиця) -- стокове: кроки 0 -> зсув 0, FM-байт 0xCC.
 */
#include <stdio.h>
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
		static const int db[4] = { 0, -6, -12, -18 };
		static const uint8_t pct[5] = { 80, 60, 40, 25, 15 }, lo[5] = { 0xCC, 0x99, 0x66, 0x40, 0x26 };
		for (uint8_t i = 0; i < 4; i++) { CHECK(vpDmrDb(i) == db[i] && vpDmrShift(i) == i, "DMR крок %u: %d дБ", i, db[i]); }
		for (uint8_t i = 0; i < 5; i++) { CHECK(vpFmPercent(i) == pct[i] && vpFmLow(i) == lo[i], "FM крок %u: %u %% -> 0x%02X", i, pct[i], lo[i]); }
		CHECK(vpFmLow(0) == VP_FM_STOCK_LOW && VP_FM_HIGH == 0x06, "FM крок 0 == стокове 0x06CC");
		int mono = 1;
		for (uint8_t i = 1; i < 5; i++) { if (vpFmLow(i) >= vpFmLow(i - 1)) mono = 0; }
		for (uint8_t i = 1; i < 4; i++) { if (vpDmrShift(i) <= vpDmrShift(i - 1)) mono = 0; }
		CHECK(mono, "таблиці монотонні: кожен крок тихіший за попередній");
		CHECK(vpDmrShift(9) == 0 && vpFmLow(9) == 0xCC, "неправильний крок -> стокове");
	}
	/* 6: множник */
	CHECK(vpDmrApply(1000, 0) == 1000 && vpDmrApply(-1000, 0) == -1000, "зсув 0: відлік без змін");
	CHECK(vpDmrApply(1000, 1) == 500 && vpDmrApply(1000, 3) == 125 && vpDmrApply(-1000, 2) == -250, "зсуви 1/3, знак зберігається");
	CHECK(vpDmrApply(0, 3) == 0 && vpDmrApply(32767, 3) == 4095 && vpDmrApply(-32768, 3) == -4096, "нуль і краї діапазону");

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
	CHECK(volumeProbeDmrStep() == 3, "DMR крок обмежено згори");
	volumeProbeToggleSelect();
	volumeProbeAdjust(+1);
	CHECK(volumeProbeFmStep() == 1 && lastWriteIs(0x99), "FM крок 1 -> 0x0699");
	volumeProbeAdjust(+9);
	CHECK(volumeProbeFmStep() == 4 && lastWriteIs(0x26), "FM крок 4 -> 0x0626 (15 %%)");
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
