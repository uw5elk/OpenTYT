/*
 * aprs_rx.h -- справжній фоновий приймач APRS (R8): AFSK 1200 / AX.25 з I2S HR-C6000 у FM-прийомі.
 *
 * Що це. На каналі APRS (аналоговий FM, RX-частота == частота APRS із налаштувань APRS, та сама, на яку
 * QSY-ить бікон) приймач слухає ефір постійно, незалежно від відкритого екрана: тік викликається з
 * головного циклу (applicationMain.c, після aprsBeaconingTick()), а не з меню. Пакети розбирає
 * aprs_rx_parse.c (список станцій, повідомлення нам, банер).
 *
 * Життєвий цикл. Старт -- детермінований (I2SProbeStart(), T_start = APRS_RX_T_START_US після фронту WS),
 * зупинка -- негайна (I2SProbeAbort()). Приймач зупиняється при: виході з каналу APRS, DMR, передачі
 * (PTT, бікон APRS), скануванні, голосовій підказці й відтворенні «Переслухати» (їм потрібен той самий
 * I2S і той самий буфер), хотспоті/CPS/екрані проби. Умови зникли -- старт знову (пауза
 * APRS_RX_HOLD_MS). Докладно, у тому числі чому буфер кільця вільний, -- docs/aprs-rx-feasibility.md,
 * розділ 12.
 *
 * Пам'ять: стан (~2,4 КБ) -- у CCM (секція .aes_ccmram); кільце -- у audioAndHotspotDataBuffer
 * (простоює в аналоговому FM). Нової main RAM -- 0.
 */
#ifndef _OPENGD77_APRS_RX_H_
#define _OPENGD77_APRS_RX_H_

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "functions/aprs_rx_cfg.h"

#if defined(APRS_RX)

#include "functions/aprs_rx_parse.h"

/* T_start, мкс після фронту WS до вмикання I2SE. Виміряно в R7 (docs, розділ 11): 0...62 мкс -- справжні
 * 16 біт (192/192 запусків), обрано середину -- 32. Можна перевизначити -D APRS_RX_T_START_US=... */
#ifndef APRS_RX_T_START_US
#define APRS_RX_T_START_US     32U
#endif
#define APRS_RX_HOLD_MS        300U     /* пауза між кінцем причини зупинки й новим стартом */
#define APRS_RX_EVAL_MS        500U     /* як часто перевіряти «чи це канал APRS» (дешево, без EEPROM) */
#define APRS_RX_CFG_MS         5000U    /* як часто перечитувати позивний і власну позицію */
#define APRS_RX_NBITS_TRIES    5U       /* перезапусків I2S, поки вердикт nbits != 16, далі -- зі шкалою */
#define APRS_RX_NBITS_PAUSE_MS 200U

/* Чому приймач не працює / що було останньою причиною зупинки (діагностика). */
typedef enum
{
	APRS_RX_WHY_NONE = 0,      /* працює (або ще не зупинявся) */
	APRS_RX_WHY_NOT_APRS,      /* не канал APRS / APRS вимкнено / нема конфігу APRS */
	APRS_RX_WHY_NOT_FM,        /* не аналоговий FM (DMR, режим «нема») */
	APRS_RX_WHY_TX,            /* передача: PTT або бікон APRS */
	APRS_RX_WHY_SCAN,
	APRS_RX_WHY_PROMPT,        /* голосова підказка */
	APRS_RX_WHY_REPLAY,        /* відтворення «Переслухати» */
	APRS_RX_WHY_MENU,          /* хотспот, CPS, екран TX/калібрування тощо */
	APRS_RX_WHY_PROBE,         /* відкрито екран «APRS проба» */
	APRS_RX_WHY_BUSY,          /* I2S зайнятий іншим кодом */
	APRS_RX_WHY_NO_WS,         /* нема такту WS (HR-C6000 не веде I2S) */
	APRS_RX_WHY_MAX
} aprsRxWhy_t;

typedef struct
{
	uint8_t   state;           /* 0 -- вимкнено, 1 -- очікує/пробує стартувати, 2 -- слухає */
	uint8_t   why;             /* aprsRxWhy_t: причина, якщо state != 2 */
	uint8_t   nbits;           /* вердикт детектора формату (0 -- ще нема; 16 -- справжні 16 біт) */
	uint8_t   triesLeft;       /* перезапусків I2S до прийняття нешкали */
	bool      scaled;          /* працюємо зі шкалою (nbits != 16) -- перезапуски вичерпано */
	uint32_t  starts;          /* стартів I2S */
	uint32_t  startFails;      /* невдалих стартів (WS немає, I2S зайнятий) */
	uint32_t  nbitsRestarts;   /* перезапусків через вердикт != 16 */
	uint32_t  nbitsScaled;     /* разів, коли довелося працювати зі шкалою */
	uint32_t  blocks;          /* оброблених блоків за сеанс */
	uint32_t  overflows;       /* блоків, втрачених через переповнення кільця */
	uint32_t  gateDrops;       /* блоків, відкинутих у перериванні (підказка/TX/режим) */
	uint32_t  framesOk;        /* кадрів з правильним FCS */
	uint32_t  framesBad;       /* кадрів з помилковим FCS */
	uint32_t  stops[APRS_RX_WHY_MAX];   /* скільки разів зупинялися з цієї причини */
	uint32_t  msgStored;       /* повідомлень нам, покладених у «Повідомлення» */
	uint32_t  banners;         /* показаних банерів */
	uint32_t  det_switches;    /* зміни вердикту детектора */
	uint32_t  fsHz;            /* виміряна частота дискретизації, Гц (0 -- ще не міряли) */
	uint16_t  tMeasUs;         /* T від фронту WS до I2SE, виміряний при останньому старті, мкс */
	uint16_t  halUs;           /* тривалість HAL_I2SEx_TransmitReceive_DMA, мкс */
} aprsRxStats_t;

/* Стан екрана «APRS станції» (user_interface/menuAprsStations.c) -- у тому самому CCM-блоці, що й приймач
 * (окремі статичні змінні екрана коштували б main RAM, а її вільно ~212 Б). */
enum { APRS_RX_VIEW_LIST = 0, APRS_RX_VIEW_CARD, APRS_RX_VIEW_DIAG };
typedef struct
{
	uint8_t   on;               /* екран відкрито */
	uint8_t   view;             /* APRS_RX_VIEW_* */
	uint8_t   sel;              /* виділений рядок списку (0 -- найновіша станція) */
	uint8_t   scroll;           /* перший видимий рядок списку */
	uint32_t  lastDrawMs;
	char      cardCall[APRS_CALL_LEN];   /* станція на картці (за позивним: порядок списку може змінитися) */
} aprsRxUi_t;
aprsRxUi_t *aprsRxUi(void);

void aprsRxInit(void);                         /* один раз при старті (стан у CCM не обнуляється) */
void aprsRxTick(void);                         /* з головного циклу, кожну ітерацію (~1 мс) */
void aprsRxI2SBlock(uint32_t bufNum);          /* з переривання DMA I2S (i2s.c) */
/* Негайно зупинити (з задачі), якщо слухаємо, -- ПЕРЕД тим, як код запускає свій I2S / пише в
 * audioAndHotspotDataBuffer (голосова підказка, «Переслухати», екран проби). Безпечно, якщо не слухаємо. */
void aprsRxSuspendForAudio(void);
bool aprsRxIsRunning(void);

const aprsRxDb_t    *aprsRxDb(void);
const aprsRxStats_t *aprsRxStats(void);
/* Власна позиція (мікроградуси) -- для відстані й азимуту. false -- позиції нема. */
bool aprsRxOwnPosition(int32_t *latU, int32_t *lonU);
/* Відстань/азимут до станції від нашої позиції. false -- у станції або в нас нема позиції. */
bool aprsRxStationGeo(const aprsStation_t *st, uint32_t *distM, uint16_t *bearing);
/* Повернути лічильники/список до нуля (екран «APRS станції», діагностична сторінка). */
void aprsRxClear(void);
/* Скільки секунд тому останній пакет станції (для списку); 0xFFFFFFFF -- запис порожній. */
uint32_t aprsRxAgeSec(const aprsStation_t *st);
/* «850м NE» / «3.2км NE» / «120км NW» -- відстань і сектор азимуту (латиниця + «м»/«км» із aprsrx_ua.h, cp1251). */
void aprsRxFormatGeo(char *buf, size_t size, uint32_t distM, uint16_t bearing);

#endif /* APRS_RX */
#endif /* _OPENGD77_APRS_RX_H_ */
