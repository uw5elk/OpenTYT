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
	apFmt_t  fmt;               /* R5/R7: на цьому варіанті: відліків, |s| >= 480, пік (масштаб 10 біт) */
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
	uint16_t peak;              /* R7: пік |s| у вікні розгортки (480 мс), масштаб 10 біт */
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

/* R5/R6/R7: формат відліку для обробки, кнопка * по колу: авто (типово) / 10 біт / 11 біт / 16>>6.
 * Відлік зводиться до масштабу «10 біт» (apSampleN). Перемикання скидає демодулятор, розгортку й
 * «потік», лічильники -- ні. USB-запис завжди сирий. */
#define APRS_PROBE_FMT_AUTO   0U
#define APRS_PROBE_FMT_10     1U
#define APRS_PROBE_FMT_11     2U
#define APRS_PROBE_FMT_16     3U
#define APRS_PROBE_FMT_MODES  4U
void aprsRxProbeToggleFormat(void);
uint8_t aprsRxProbeFormatMode(void);
/* nbits, яким обробляється зараз (в «авто» -- вердикт детектора; поки його нема -- 10). */
uint8_t aprsRxProbeNbits(void);
/* Стан детектора (nbits, перемикань, лічильники c[j] останнього блока). */
const apFmtDet_t *aprsRxProbeFormatDet(void);

/* R7: кадри (FCS ок / помилка) окремо для кожного nbits, з яким обробляли (до 4 значень, з GREEN
 * і зміни варіанта). false -- слот порожній. */
#define APRS_PROBE_NB_SLOTS   4U
bool aprsRxProbeNbSlot(uint8_t i, uint8_t *nbits, uint16_t *ok, uint16_t *bad);

/* R7: детермінований старт I2S (docs/aprs-rx-feasibility.md, розділ 11). T_start -- мкс від фронту
 * WS 0->1 до вмикання I2SE; типово APRS_PROBE_T_START_US (112: виміряне R6 значення, при якому
 * формат «10» вийшов 6 разів із 6). */
#ifndef APRS_PROBE_T_START_US
#define APRS_PROBE_T_START_US  112U
#endif
#define APRS_PROBE_T_MAX_US    124U
#define APRS_PROBE_T_STEP_US   2U

typedef struct
{
	uint32_t starts;            /* успішних стартів I2S з відкриття проби */
	uint16_t tSetUs;            /* T_start: задане */
	uint16_t tMeasUs;           /* ... виміряне останнього старту (кінець HAL ~ I2SE), за модулем 125 мкс */
	uint16_t halUs;             /* тривалість HAL останнього старту, мкс */
	uint8_t  wsAfter;           /* рівень WS одразу після старту */
	uint8_t  tCnt[4];           /* вердиктів nbits на цьому T_start: 10 / 11 / 16 / інші (скидається при зміні T) */
	/* FRE (прапорець «WS змінився в неочікуваний момент»): опитувань із прапорцем за останню секунду
	 * (R6 рахував усю сесію -- завжди насичувалось) */
	uint16_t freRxSec, freTxSec;
	uint16_t freRxCur, freTxCur;
	uint32_t secMs;             /* початок поточної секунди */
	/* регістри SPI3/I2S3ext (I2S3 + I2S3ext) раз на секунду */
	uint16_t regs[6];           /* I2SProbeRegs() (interfaces/i2s.h): SPI3 CFGR/PR/CR2, I2S3ext CFGR/PR/CR2 */
	uint16_t sr[2];             /* SPI3->SR, I2S3ext->SR -- останнє опитування */
	uint16_t srErr[2];          /* ... і накопичені за секунду UDR | OVR | FRE */
	uint16_t srErrCur[2];
	uint8_t  regsValid;
} aprsProbeDiag_t;
const aprsProbeDiag_t *aprsRxProbeDiag(void);
/* Змінити T_start на delta мкс (з обмеженням 0..124); лічильники tCnt скидаються. Новий T діє
 * з наступного (пере)запуску I2S. */
void aprsRxProbeTAdjust(int delta);
/* Події, після яких стоковий код переписує регістри кодека: відкриття / закриття шумодава,
 * біпи, голосові підказки (з відкриття проби). */
void aprsRxProbeEvents(uint32_t *sqOpen, uint32_t *sqClose, uint32_t *beeps, uint32_t *prompts);
/* Перезапустити I2S (кнопка 0) із поточним T_start без запису регістрів. */
void aprsRxProbeRestartI2S(void);

/* R7: розгортка T_start (кнопка 5): T = 0, 2, ... 124 мкс (63 значення), по APRS_PROBE_SCAN_REPS
 * перезапусків на кожне, після кожного -- вердикт детектора (<= 400 мс). Регістри кодека під час
 * розгортки не пишуться. Код T: 0 -- ще не міряли; 8..16 -- усі перезапуски дали цей nbits;
 * APRS_PROBE_SCAN_MIXED -- різні; APRS_PROBE_SCAN_NONE -- вердикту не було. */
#define APRS_PROBE_SCAN_N      63U
#define APRS_PROBE_SCAN_REPS   6U
#define APRS_PROBE_SCAN_WAIT_MS 400U
#define APRS_PROBE_SCAN_MIXED  0xFEU
#define APRS_PROBE_SCAN_NONE   0xFDU
/* Почати розгортку; якщо вже йде -- скасувати (T_start повертається). */
void aprsRxProbeScanToggle(void);
bool aprsRxProbeScanActive(void);
/* Прогрес: індекс T (0..62) і скільки перезапусків для нього зроблено. */
void aprsRxProbeScanProgress(uint8_t *idx, uint8_t *rep);
uint8_t aprsRxProbeScanCode(uint8_t idx);
/* Найдовший ряд сусідніх T з однаковим стійким nbits (>= 3 поспіль): межі й nbits; centre -- T,
 * на який «авто-фаза» ставить T_start. false -- ряду немає. */
bool aprsRxProbeScanBest(uint16_t *tFrom, uint16_t *tTo, uint8_t *nbits, uint16_t *centre);

/* R6: регістри кодека для сторінки «регістри». Refresh -- прочитати з чипа, не частіше ніж раз
 * на секунду (викликає екран, поки сторінку видно). Reg -- i-й регістр: адреса, значення;
 * false -- ще не читали або читання не вдалося. */
#define APRS_PROBE_NUM_REGS   24U
void aprsRxProbeRegsRefresh(void);
bool aprsRxProbeReg(uint8_t i, uint8_t *addr, uint8_t *val);

/* R4: USB-запис сирих відліків. Стан для екрана (false -- запису не було). */
bool aprsRxProbeCapture(uint32_t *sent, uint32_t *total, uint32_t *lost);
/* Обробник опкоду CPS 'C' 0xB5 (usb_com.c): req -- увесь запит, out -- місце для відповіді
 * ПІСЛЯ [cmd, len_hi, len_lo]. Повертає довжину відповіді. Формат -- у aprs_rx_probe.c. */
int aprsRxProbeUsb(const volatile uint8_t *req, int reqLen, volatile uint8_t *out, int outMax);

/* З i2s.c, переривання DMA: половина буфера bufNum (160 стерео-кадрів, 20 мс). */
void aprsRxProbeI2SBlock(uint32_t bufNum);

#endif /* APRS_RX_PROBE */
#endif /* _OPENGD77_APRS_RX_PROBE_H_ */
