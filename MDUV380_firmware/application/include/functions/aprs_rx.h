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
	uint16_t  msgStored;       /* повідомлень нам, покладених у «Повідомлення» (R8-fix: u16, місце під лічильники нижче) */
	uint16_t  banners;         /* показаних банерів */
	uint16_t  det_switches;    /* зміни вердикту детектора */
	uint16_t  wsTimeouts;      /* R8-fix: таймаутів очікування WS у I2SStartDMA() (DMA не стартовано) */
	uint16_t  syncStops;       /* R8-fix: скільки разів приймач зупинено СИНХРОННО перед передачею/QSY */
	uint16_t  abortTimeouts;   /* R8-fix: HAL_DMA_Abort() не дочекався зупинки потоку DMA (такту нема) */
	uint32_t  fsHz;            /* виміряна частота дискретизації, Гц (0 -- ще не міряли) */
	uint16_t  tMeasUs;         /* T від фронту WS до I2SE, виміряний при останньому старті, мкс */
	uint16_t  halUs;           /* тривалість HAL_I2SEx_TransmitReceive_DMA, мкс */
} aprsRxStats_t;

/* Стан екрана «APRS станції» (user_interface/menuAprsStations.c) -- у тому самому CCM-блоці, що й приймач
 * (окремі статичні змінні екрана коштували б main RAM, а її вільно ~212 Б). */
enum { APRS_RX_VIEW_LIST = 0, APRS_RX_VIEW_CARD, APRS_RX_VIEW_DIAG, APRS_RX_VIEW_DIAG2, APRS_RX_VIEW_PACKET };   /* R15: PACKET -- «Останній пакет» (scroll = перший видимий рядок тексту) */
typedef struct
{
	uint8_t   on;               /* екран відкрито */
	uint8_t   view;             /* APRS_RX_VIEW_* */
	uint8_t   sel;              /* виділений рядок списку (0 -- найновіша станція) */
	uint8_t   scroll;           /* перший видимий рядок списку */
	uint32_t  lastDrawMs;
	char      cardCall[APRS_CALL_LEN];   /* станція на картці (за позивним: порядок списку може змінитися) */
	uint8_t   modeOn;           /* R10: «Режим APRS» активний (aprs_mode.c); у байті вирівнювання -- розмір структури не росте */
	uint8_t   msgOn;            /* R13: екран «Повідом. APRS» відкрито БЕЗ «Режиму APRS» (aprs_mode.c); теж байт вирівнювання */
} aprsRxUi_t;
aprsRxUi_t *aprsRxUi(void);

void aprsRxInit(void);                         /* один раз при старті (стан у CCM не обнуляється) */
void aprsRxTick(void);                         /* з головного циклу, кожну ітерацію (~1 мс) */
void aprsRxI2SBlock(uint32_t bufNum);          /* з переривання DMA I2S (i2s.c) */
/* Негайно зупинити (з задачі), якщо слухаємо, -- ПЕРЕД тим, як код запускає свій I2S / пише в
 * audioAndHotspotDataBuffer (голосова підказка, «Переслухати», екран проби). Безпечно, якщо не слухаємо. */
void aprsRxSuspendForAudio(void);
/* R8-fix: СИНХРОННА зупинка ПЕРЕД початком передачі (PTT, бікон APRS, QSY): trxSetTX()/trxActivateTx() і
 * aprsBeaconingSendBeacon() кличуть її першим ділом. Тік приймача тут запізнюється -- у головному циклі
 * aprsBeaconingTick() іде РАНІШЕ за aprsRxTick(), тож передача встигала б стартувати з ще живим I2S.
 * Безпечно викликати будь-коли (нічого не слухаємо -- нічого не робить, лічильник не росте). */
void aprsRxStopForTx(void);
bool aprsRxIsRunning(void);
/* R10: на частоті зараз іде AFSK (кадр або серія прапорців за останні ms мс) -- маяк «Режиму APRS» чекає. */
bool aprsRxBusy(uint32_t ms);

/* R8-fix: події низького рівня з i2s.c -- у лічильники діагностичної сторінки (окремої змінної в main
 * RAM немає: вона коштувала б байтів, яких нема). */
typedef enum { APRS_RX_I2S_EV_WS_TIMEOUT = 0, APRS_RX_I2S_EV_ABORT_TIMEOUT } aprsRxI2sEvent_t;
void aprsRxNoteI2sEvent(aprsRxI2sEvent_t ev);

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
/* R14: лише відстань без сектора («850м» / «6.3км» / «120км») -- для вікна маяка (там азимут цифрою і стрілка). */
void aprsRxFormatDist(char *buf, size_t size, uint32_t distM);

/* ---- R13: вікно маяка (повноекранна картка за позиційним пакетом) ------------------------------------------------ */
/* Дані картки: копія з пакета на момент прийому (запис станції координат у градусах/курсу не тримає, тож дубль у CCM ~64 Б).
 * Малює uiNotification.c (NOTIFICATION_ID_APRS_BEACON), стан і правила показу -- aprs_rx.c (aprsRxWindowTick()). */
typedef struct
{
	bool      active;           /* вікно мусить бути на екрані (до RED / нового пакета / повідомлення / причини, що забороняє) */
	bool      hasGeo;           /* є відстань і азимут (є позиція станції й власна) */
	uint16_t  bearing;          /* азимут на станцію від півночі, 0..359 */
	uint16_t  course;           /* курс станції, 1..360; 0 -- нема */
	uint16_t  speedKn;          /* швидкість, вузли; 0 -- нема/стоїть */
	uint32_t  distM;
	uint32_t  rxSecs;           /* uiDataGlobal.dateTimeSecs у момент прийому */
	/* R14: розібрані розширення коментаря. Радіо (частота/тон/зсув/PHG/радіус) і погода ділять одне місце (union, 16 Б): вони не зустрічаються
	 * разом -- погода розбирається лише для символу '_', і тоді має перевагу. Усе разом +24 Б у CCM (одна копія). */
	int32_t   altM;             /* висота, м (AWIN_F_ALT) */
	union
	{
		struct
		{
			uint32_t freqKHz;   /* 0 -- нема */
			int16_t  shiftKHz;  /* AWIN_F_SHIFT */
			uint16_t extVal;    /* PHG/DFS: 4 hex-цифри phgd; RNG: милі */
			uint16_t rangeVal;  /* радіус, милі або км (AWIN_F_RANGE_KM); 0 -- нема */
			char     tone[5];   /* "T082" / "Toff" / "" */
		} r;
		struct
		{
			int16_t  tempC;
			uint16_t pressDhPa; /* 0.1 гПа */
			uint16_t windDeg;
			uint8_t  humPct, windMph, gustMph;
		} wx;
	} u;
	uint8_t   flags;            /* AWIN_F_* */
	uint8_t   extKind;          /* APRS_EXT_* */
	uint8_t   wxMask;           /* APRS_WX_*; ненульовий -- у u діє wx */
	char      symTable, symCode;
	char      call[APRS_CALL_LEN];
	char      text[APRS_STATION_TEXT];
#define AWIN_F_ALT       0x01
#define AWIN_F_SHIFT     0x02
#define AWIN_F_RANGE_KM  0x04
} aprsRxWin_t;
const aprsRxWin_t *aprsRxWindow(void);
/* RED на вікні (applicationMain.c): вікно закрито оператором -- чекає наступного пакета. */
void aprsRxWindowDismiss(void);
/* Налаштування «Вікно маяка»: aprsBcnWinMode_t (2 вільні біти bitfieldOptions). */
uint8_t aprsRxBcnWinMode(void);
void aprsRxBcnWinSetMode(uint8_t mode);

#endif /* APRS_RX */
#endif /* _OPENGD77_APRS_RX_H_ */
