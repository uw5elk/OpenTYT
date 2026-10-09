/*
 * aprs_rx_probe.h -- діагностика R2 «APRS проба» (docs/aprs-rx-feasibility.md, розділ 3):
 * чи доходить прийнятий FM-звук до процесора без паяння.
 *
 *   Джерело А -- I2S3 від HR-C6000 (той самий DMA, що й мікрофон у DMR-передачі), з
 *                перебором регістрів кодека 0xE0 / 0x36 (і 0x10 у двох додаткових варіантах).
 *   Джерело Б -- ніжка PC3 (ADC2, канал 13), відлік з переривання TIM7 на 9600 Гц
 *                (CCM недоступна для DMA, а нової main RAM немає).
 *
 * Ніякого демодулятора: лише рівень і тони 1200/2200 Гц (aprs_probe_dsp.c).
 *
 * Тимчасовий прапорець ENABLE_APRS_RX_PROBE (у CI -- лише українська збірка); екран --
 * лише в українській збірці. Прибрати після експерименту (STATUS.md).
 *
 * Пам'ять: увесь стан -- одна структура в CCM; буфери I2S -- наявні i2s_Rx_Buffer/
 * i2s_Tx_Buffer (у FM простоюють). Нової main RAM -- 0.
 */
#ifndef _OPENGD77_APRS_RX_PROBE_H_
#define _OPENGD77_APRS_RX_PROBE_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_APRS_RX_PROBE) && defined(LANGUAGE_BUILD_UKRAINIAN)
#define APRS_RX_PROBE 1
#endif

#if defined(APRS_RX_PROBE)

#include "functions/aprs_probe_dsp.h"

#define APRS_PROBE_NUM_I2S_VARIANTS  14   /* А1..А14 */
#define APRS_PROBE_NUM_VARIANTS      15   /* + Б (PC3/ADC2) */
#define APRS_PROBE_VARIANT_ADC       (APRS_PROBE_NUM_VARIANTS - 1)

#define APRS_PROBE_ADC_FS            AP_FS_ADC   /* Гц */

typedef enum
{
	APRS_PROBE_ST_IDLE = 0,     /* ще не стартувало */
	APRS_PROBE_ST_NOT_FM,       /* канал не аналоговий -- нічого не чіпаємо */
	APRS_PROBE_ST_BUSY,         /* I2S зайнятий (голосова підказка) -- пауза */
	APRS_PROBE_ST_NO_WS,        /* немає такту WS від HR-C6000 -- I2S не стартує */
	APRS_PROBE_ST_RUNNING,      /* відліки йдуть */
	APRS_PROBE_ST_WAIT          /* I2S зупинено ззовні -- перезапуск за <= 250 мс */
} aprsProbeStatus_t;

/* Обнулити стан (CCM не обнуляється стартапом). Один раз при старті, до menuSystemInit(). */
void aprsRxProbeInit(void);

/* Екран проби відкрито. */
bool aprsRxProbeIsOn(void);
/* Відкрити: вимкнути еко-режим, на FM-каналі -- зберегти регістри й запустити варіант 1. */
void aprsRxProbeOpen(void);
/* Закрити: зупинити I2S/ADC2/TIM7, точно відновити регістри HR-C6000 і еко-режим.
 * Безпечно викликати будь-коли (якщо не відкрито -- нічого не робить). */
void aprsRxProbeClose(void);
/* Наступний (+1) / попередній (-1) варіант джерела, по колу. */
void aprsRxProbeSelect(int delta);
/* Часто, з тіку екрана: стан FM, пауза на підказки, повторний запуск I2S, повторне
 * застосування регістрів (стоковий код переписує 0x36/0x10 на початку прийому й біпах). */
void aprsRxProbeService(void);

uint8_t aprsRxProbeVariant(void);
aprsProbeStatus_t aprsRxProbeStatus(void);
/* Регістри варіанта А (для екрана). false -- це варіант Б. */
bool aprsRxProbeVariantRegs(uint8_t v, uint8_t *e0, uint8_t *r36, uint8_t *r10);
/* Значення, прочитані на вході (їх і відновлюємо). readOk = false -- читання не вдалося або
 * значення неправдоподібне, тоді відновлюються штатні FM-значення. */
bool aprsRxProbeSavedRegs(uint8_t *e0, uint8_t *r36, uint8_t *r10, bool *readOk);

/* Останнє закрите вікно (~240 мс). out[0] -- L (або PC3), out[1] -- R (лише I2S).
 * true -- є нове вікно з моменту *seq (оновлює *seq). */
bool aprsRxProbeResult(apResult_t out[2], uint32_t *seq);
/* Мілісекунди з останнього вікна (для «немає даних»). */
uint32_t aprsRxProbeMsSinceResult(void);

/* З i2s.c, переривання DMA: половина буфера bufNum (160 стерео-кадрів, 20 мс). */
void aprsRxProbeI2SBlock(uint32_t bufNum);

#endif /* APRS_RX_PROBE */
#endif /* _OPENGD77_APRS_RX_PROBE_H_ */
