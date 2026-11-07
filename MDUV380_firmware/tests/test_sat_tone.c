/*
 * test_sat_tone.c -- R66D: тон CTCSS передачі супутника за набором 1/2/3 (application/include/functions/satellite_tone.h -- СПРАВЖНЯ чиста функція,
 * її викликає menuSatelliteScreen.c під ENABLE_SAT_TONE_SYNC).
 *
 * Екран супутників тягне весь UI, тому тут -- модель трьох місць, де екран пише txTone, у порядку виклику з menuSatelliteScreen.c:
 *   стокове:  selectSatellite()      -> txTone = freqs[idx].txCTCSS   (єдине присвоєння, r56-result.md п. 1)
 *   R66D:     клавіші 1/2/3          -> idx = ...; txTone = satelliteTxToneFor(sat, idx)
 *             calculateActiveSatelliteData() (тік, вибір) -> txTone = satelliteTxToneFor(sat, idx)
 * Статичну відповідність моделі коду (кожне місце існує, під #if) перевіряє tools/test_r66.py розділ D.
 *
 * Сценарії -- таблиця r56-result.md п. 3 (5, 7, 8). Колонка «стокове» відтворює ПОМИЛКУ (тест фіксує, що модель стокового коду її має), «R66D» -- виправлення.
 */
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "functions/satellite_tone.h"

static int fails = 0;
#define CHECK(c, ...) do { if (c) { printf("  ok   "); } else { printf("  FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

static satelliteData_t iss, so50, none;
static uint16_t txTone;               /* currentChannelData->txTone */
static satelliteFreq_t idx;           /* currentSatelliteFreqIndex (глобальний, зберігається між супутниками) */
static const satelliteData_t *cur;    /* currentActiveSatellite */
static bool sync;                     /* ENABLE_SAT_TONE_SYNC */

static void calc(void) { if (sync) { txTone = satelliteTxToneFor(cur, idx); } }   /* calculateActiveSatelliteData() */
static void selectSat(const satelliteData_t *s) { cur = s; calc(); txTone = cur->freqs[idx].txCTCSS; }   /* selectSatellite() -- стоковий рядок лишається */
static void key(int k)
{
	idx = (k == 1) ? SATELLITE_VOICE_FREQ : ((k == 2) ? SATELLITE_APRS_FREQ : SATELLITE_OTHER_FREQ);
	if (sync) { txTone = satelliteTxToneFor(cur, idx); }
	calc();   /* nextCalculationTime = 0 -> наступний тік */
}

static void setup(void)
{
	memset(&iss, 0, sizeof(iss)); memset(&so50, 0, sizeof(so50)); memset(&none, 0, sizeof(none));
	iss.freqs[SATELLITE_VOICE_FREQ].txCTCSS = 67;  iss.freqs[SATELLITE_VOICE_FREQ].armCTCSS = 0;
	so50.freqs[SATELLITE_VOICE_FREQ].txCTCSS = 67; so50.freqs[SATELLITE_VOICE_FREQ].armCTCSS = 74;
	/* APRS і «інший»: тон 0 (menuSatelliteScreen.c:1398-1404) */
	iss.freqs[SATELLITE_APRS_FREQ].txFreq = 145825; so50.freqs[SATELLITE_OTHER_FREQ].txFreq = 1;
	txTone = 0; idx = SATELLITE_VOICE_FREQ; cur = &iss;
}

int main(void)
{
	/* ---- стокова модель: помилки відтворюються (сценарії 5, 7) ---- */
	sync = false; setup();
	idx = SATELLITE_VOICE_FREQ; selectSat(&iss); key(2);
	CHECK(txTone == 67, "стокове, сценарій 5: ISS вибрано на голосі -> клавіша 2 (APRS): тон ЛИШИВСЯ 67 -- помилка відтворена (%u)", (unsigned)txTone);
	setup(); idx = SATELLITE_APRS_FREQ; selectSat(&iss); key(1);
	CHECK(txTone == 0, "стокове, сценарій 7: ISS вибрано при наборі APRS -> клавіша 1 (голос): тон ЛИШИВСЯ 0 -- голос без 67 Гц, помилка відтворена (%u)", (unsigned)txTone);

	/* ---- R66D ---- */
	sync = true;
	setup(); idx = SATELLITE_VOICE_FREQ; selectSat(&iss); key(2);
	CHECK(txTone == 0, "R66D, сценарій 5: клавіша 2 -> APRS без тону (%u)", (unsigned)txTone);
	setup(); idx = SATELLITE_APRS_FREQ; selectSat(&iss); key(1);
	CHECK(txTone == 67, "R66D, сценарій 7: клавіша 1 -> голос з тоном 67 (%u)", (unsigned)txTone);
	key(2); key(1);
	CHECK(txTone == 67, "R66D, сценарій 8: 2 -> 1 -> тон голосу 67 (%u)", (unsigned)txTone);
	key(3);
	CHECK(txTone == 0, "R66D: набір 3 («інший») -> без тону (%u)", (unsigned)txTone);
	key(1); selectSat(&so50);
	CHECK(txTone == 67, "R66D: інший супутник з тим самим набором -> 67 (%u)", (unsigned)txTone);
	/* тон взведення не чіпається: armCTCSS лишається в даних супутника, функція його не читає */
	CHECK(so50.freqs[SATELLITE_VOICE_FREQ].armCTCSS == 74 && satelliteTxToneFor(&so50, SATELLITE_VOICE_FREQ) == 67, "R66D: тон взведення (armCTCSS=74) не змішується з тоном передачі (67)");
	/* межі */
	CHECK(satelliteTxToneFor(NULL, SATELLITE_VOICE_FREQ) == 0, "R66D: NULL-супутник -> 0");
	CHECK(satelliteTxToneFor(&iss, (satelliteFreq_t)3) == 0 && satelliteTxToneFor(&iss, (satelliteFreq_t)-1) == 0, "R66D: набір поза 0..2 -> 0");
	CHECK(satelliteTxToneFor(&none, SATELLITE_VOICE_FREQ) == 0, "R66D: супутник без тону -> 0");
	/* таблиця: для всіх 3 наборів результат == поле набору */
	{
		satelliteData_t t; int ok = 1;
		memset(&t, 0, sizeof(t));
		t.freqs[0].txCTCSS = 1; t.freqs[1].txCTCSS = 2; t.freqs[2].txCTCSS = 3;
		for (int i = 0; i < 3; i++) { ok &= (satelliteTxToneFor(&t, (satelliteFreq_t)i) == (uint16_t)(i + 1)); }
		CHECK(ok, "R66D: набір i -> поле freqs[i].txCTCSS (жодного зсуву між наборами)");
	}
	printf("%s (%d)\n", fails ? "ПРОВАЛ" : "усе гаразд", fails);
	return fails ? 1 : 0;
}
