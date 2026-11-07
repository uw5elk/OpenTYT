/*
 * satellite_tone.h -- R66D: тон CTCSS ПЕРЕДАЧІ супутника за поточним набором частот (1 голос / 2 APRS / 3 інший).
 *
 * Чому окремо: стокове OpenGD77 виставляє currentChannelData->txTone лише при ВИБОРІ супутника (selectSatellite), а клавіші 1/2/3 перемикають
 * currentSatelliteFreqIndex без перерахунку тону (r56-result.md, п. 1-3): «ISS обрано при наборі APRS -> клавіша 1 -> голос без тону 67 Гц»
 * і навпаки «клавіша 2 -> пакет APRS з тоном 67». Під ENABLE_SAT_TONE_SYNC тон береться за набором у кожному місці, де змінюється
 * набір чи розраховуються дані супутника. Без прапорця заголовок не підключається, збірка байт-у-байт стокова.
 *
 * Тон ВЗВЕДЕННЯ (armCTCSS, SK2 під час PTT -- «SO-50 arming», uiTxScreen.c) цим не чіпається: він і далі береться з наборів на момент PTT.
 * Чиста функція (без заліза) -- її перевіряє хост-тест tests/test_sat_tone.c.
 */
#ifndef FUNCTIONS_SATELLITE_TONE_H_
#define FUNCTIONS_SATELLITE_TONE_H_

#include <stdint.h>
#include <stddef.h>
#include "functions/satellite.h"

/* Тон передачі для набору idx супутника sat; 0 («без тону») -- для відсутнього супутника, набору поза 0..2 та наборів APRS/інший (їм txCTCSS примусово 0). */
static inline uint16_t satelliteTxToneFor(const satelliteData_t *sat, satelliteFreq_t idx)
{
	if ((sat == NULL) || ((unsigned)idx > (unsigned)SATELLITE_OTHER_FREQ))
	{
		return 0U;
	}
	return sat->freqs[idx].txCTCSS;
}

#endif /* FUNCTIONS_SATELLITE_TONE_H_ */
