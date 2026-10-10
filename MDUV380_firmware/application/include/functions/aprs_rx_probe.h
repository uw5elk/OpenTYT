/*
 * aprs_rx_probe.h -- діагностика «APRS проба» (R2 -> R3): прийом APRS з I2S від HR-C6000.
 *
 * R2 показав, що прийнятий FM-звук іде по I2S3 без паяння (docs/aprs-rx-feasibility.md, розділ 6).
 * R4: діагностика бітового рівня (сторінки «потік» і «кадр») і запис сирих відліків на ПК по
 * USB (опкод 0xB5, tools/aprs_capture.py, кнопка в gui_flasher.py).
 * R3: лишилися 6 варіантів регістрів кодека, у яких тони розрізнялися й мікрофон вимкнено
 * (А1, А3, А7, А9, А10, А12); на I2S RX працює демодулятор Bell 202 + AX.25 (aprs_afsk.c) і
 * розгортка фону (aprs_probe_dsp.c). Для кожного варіанта -- свої лічильники кадрів і показники
 * фону, тож варіанти можна порівняти справжніми пакетами; перемикання не скидає чужих лічильників.
 *
 * Переривання DMA I2S лише складає блоки по 160 відліків (канал L) у кільце; уся обробка --
 * у тіку екрана (aprsRxProbeService), без блокувань UI. Кільце -- у audioAndHotspotDataBuffer
 * (буфер звуку AMBE/підказок, у FM-прийомі простоює), стан -- одна структура в CCM.
 * Нової main RAM -- 0.
 *
 * Тимчасовий прапорець ENABLE_APRS_RX_PROBE (у CI -- лише українська збірка); екран -- лише в
 * українській збірці. Прибрати після експерименту (STATUS.md).
 */
#ifndef _OPENGD77_APRS_RX_PROBE_H_
#define _OPENGD77_APRS_RX_PROBE_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_APRS_RX_PROBE) && defined(LANGUAGE_BUILD_UKRAINIAN)
#define APRS_RX_PROBE 1
#endif

#if defined(APRS_RX_PROBE)

#include "functions/aprs_afsk.h"

#define APRS_PROBE_NUM_VARIANTS  6

typedef enum
{
	APRS_PROBE_ST_IDLE = 0,     /* ще не стартувало */
	APRS_PROBE_ST_NOT_FM,       /* канал не аналоговий -- нічого не чіпаємо */
	APRS_PROBE_ST_BUSY,         /* I2S зайнятий (голосова підказка) -- пауза */
	APRS_PROBE_ST_NO_WS,        /* немає такту WS від HR-C6000 -- I2S не стартує */
	APRS_PROBE_ST_RUNNING,      /* відліки йдуть */
	APRS_PROBE_ST_WAIT          /* I2S зупинено ззовні -- перезапуск за <= 250 мс */
} aprsProbeStatus_t;

/* Лічильники й показники одного варіанта. */
typedef struct
{
	uint16_t ok;                /* кадрів з правильним FCS */
	uint16_t bad;               /* кадрів з помилковим FCS */
	uint16_t flagSeq;           /* серій прапорців (>= AFSK_FLAG_SEQ поспіль) */
	char     srcDst[20];        /* останній правильний кадр: «SRC-n>DST-n» */
	char     info[24];          /* ... і початок поля info */
	uint16_t badLen;            /* R4: останній кадр з помилковим FCS -- довжина з FCS (0 -- не було) */
	uint8_t  badHead[16];       /* ... і перші 16 байтів */
	/* фон -- останнє вікно розгортки (480 мс) на цьому варіанті */
	uint8_t  bgValid;
	uint8_t  share1;            /* частка топ-1 у RMS, % */
	uint16_t f1;                /* Гц (уточнена) */
	uint16_t a1;                /* амплітуда, сирі одиниці */
	uint16_t f2;
	uint16_t a2;
	uint16_t rms;
	int16_t  dc;
} aprsProbeVar_t;

/* Обнулити стан (CCM не обнуляється стартапом). Один раз при старті, до menuSystemInit(). */
void aprsRxProbeInit(void);

/* Екран проби відкрито. */
bool aprsRxProbeIsOn(void);
/* Відкрити: вимкнути еко-режим, на FM-каналі -- зберегти регістри й запустити варіант 1.
 * Лічильники всіх варіантів обнуляються. */
void aprsRxProbeOpen(void);
/* Закрити: зупинити I2S, точно відновити регістри HR-C6000 і еко-режим.
 * Безпечно викликати будь-коли (якщо не відкрито -- нічого не робить). */
void aprsRxProbeClose(void);
/* Наступний (+1) / попередній (-1) варіант, по колу. Лічильники варіантів не скидаються. */
void aprsRxProbeSelect(int delta);
/* Часто, з тіку екрана: стан FM, пауза на підказки, повторний запуск I2S, повторне застосування
 * регістрів (стоковий код переписує 0x36/0x10 на початку прийому й біпах) і ОБРОБКА блоків. */
void aprsRxProbeService(void);

/* Скинути лічильники й останній кадр поточного варіанта (кнопка GREEN). */
void aprsRxProbeResetCurrent(void);
/* Режекція з розгортки фону: дозволено (авто) / вимкнено (кнопка #). */
void aprsRxProbeToggleNotch(void);
bool aprsRxProbeNotchAuto(void);
/* Поточна частота режекції, Гц (0 -- вимкнена). */
uint16_t aprsRxProbeNotchHz(void);

uint8_t aprsRxProbeVariant(void);
/* Номер варіанта R2 (1, 3, 7, 9, 10, 12) -- для підпису на екрані. */
uint8_t aprsRxProbeVariantR2(uint8_t v);
aprsProbeStatus_t aprsRxProbeStatus(void);
void aprsRxProbeVariantRegs(uint8_t v, uint8_t *e0, uint8_t *r36, uint8_t *r10);
/* Значення, прочитані на вході (їх і відновлюємо). readOk = false -- читання не вдалося або
 * значення неправдоподібне, тоді відновлюються штатні FM-значення. */
bool aprsRxProbeSavedRegs(uint8_t *e0, uint8_t *r36, uint8_t *r10, bool *readOk);
const aprsProbeVar_t *aprsRxProbeStats(uint8_t v);

/* Виміряна частота дискретизації I2S (відліків за секунду за тиками HAL); false -- ще < 5 с. */
bool aprsRxProbeFs(uint32_t *hz, uint32_t *seconds);
/* Блоків, оброблених / втрачених (кільце переповнилось) з останнього (пере)запуску I2S. */
uint32_t aprsRxProbeBlocks(void);
uint32_t aprsRxProbeOverflows(void);
/* Мілісекунди з останнього блока (для «немає даних»). */
uint32_t aprsRxProbeMsSinceBlock(void);

/* R4: сторінка «потік» -- безперервність тону 1200 Гц на межах блоків, гістограма фази тактів,
 * лічильники колбеків DMA (половина / повний / порушення черговості). */
const apStream_t *aprsRxProbeStream(void);
const uint16_t *aprsRxProbePllHist(void);
void aprsRxProbeDmaCounters(uint32_t *half, uint32_t *full, uint32_t *order);

/* R4: USB-запис сирих відліків. Стан для екрана (false -- запису не було). */
bool aprsRxProbeCapture(uint32_t *sent, uint32_t *total, uint32_t *lost);
/* Обробник опкоду CPS 'C' 0xB5 (usb_com.c): req -- увесь запит, out -- місце для відповіді
 * ПІСЛЯ [cmd, len_hi, len_lo]. Повертає довжину відповіді. Формат -- у aprs_rx_probe.c. */
int aprsRxProbeUsb(const volatile uint8_t *req, int reqLen, volatile uint8_t *out, int outMax);

/* З i2s.c, переривання DMA: половина буфера bufNum (160 стерео-кадрів, 20 мс). */
void aprsRxProbeI2SBlock(uint32_t bufNum);

#endif /* APRS_RX_PROBE */
#endif /* _OPENGD77_APRS_RX_PROBE_H_ */
