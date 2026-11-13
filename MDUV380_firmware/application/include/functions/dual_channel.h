/*
 * dual_channel.h -- R97: «Подвійний прийом» по каналах кодплага (A = поточний канал зони, B = закріплений канал з будь-якої зони).
 *
 * Компілюється лише з -DENABLE_DUAL_CHANNEL в українській збірці UV380 (DUAL_CHANNEL_ENABLED нижче). Без нього файл порожній, а всі
 * виклики загорнуті в той самий #if -- збірка без дефайнів і не-українські збірки байт-у-байт ті самі.
 * Чисті функції (розбір/збирання блоку, перевірка пари, вибір каналу для PTT, крок по позиціях) компілюються ще й з
 * DUAL_CHANNEL_HOST_TEST для хостового тесту tools/test_r97.py.
 *
 * Сховище: custom-data блок CODEPLUG_CUSTOM_DATA_TYPE_DUAL_CHANNEL_CFG (= 18), 8 байт:
 *   [0] version (= 1)
 *   [1] flags: біт 0 -- режим увімкнено; біт 1 -- покажчик на B (0 = на A); решта бітів -- 0
 *   [2] номер каналу B, молодший байт  } абсолютний індекс каналу кодплага 1..1024; 0 = «B не задано»
 *   [3] номер каналу B, старший байт   }
 *   [4..7] резерв (0)
 * Якщо блоку нема або він нечинний -- режим вимкнено, покажчик на A, B не задано.
 * Формат знадобиться CPS (R98) -- змінюючи тут, змінюй там.
 */
#ifndef FUNCTIONS_DUAL_CHANNEL_H_
#define FUNCTIONS_DUAL_CHANNEL_H_

#if defined(ENABLE_DUAL_CHANNEL) && defined(LANGUAGE_BUILD_UKRAINIAN) && defined(PLATFORM_MDUV380)
#define DUAL_CHANNEL_ENABLED 1
#endif

#if defined(DUAL_CHANNEL_ENABLED) || defined(DUAL_CHANNEL_HOST_TEST)

#include <stdint.h>
#include <stdbool.h>

#define DC_CFG_VERSION      1U
#define DC_CFG_LEN          8
#define DC_FLAG_ENABLED     0x01U
#define DC_FLAG_POINTER_B   0x02U
#define DC_CH_MIN           1U
#define DC_CH_MAX           1024U

/* Розкладка блоку на флеші (8 байт, без вирівнювання -- лише uint8_t). */
typedef struct
{
	uint8_t version;
	uint8_t flags;
	uint8_t chBLo;
	uint8_t chBHi;
	uint8_t reserved[4];
} dcOnFlashCfg_t;

/* Розібрати блок: true -- версія відома; виходи заповнені (номер B поза 1..1024 -> 0 «не задано»). false -- виходи = типові (вимк., A, 0). */
bool dcCfgParse(const dcOnFlashCfg_t *raw, bool *enabled, bool *pointerB, uint16_t *chB);
/* Зібрати блок для запису (номер B поза 1..1024 -> 0). */
void dcCfgBuild(dcOnFlashCfg_t *raw, bool enabled, bool pointerB, uint16_t chB);

typedef enum
{
	DC_PAIR_OK = 0,
	DC_PAIR_NO_B,        /* B не задано */
	DC_PAIR_B_DELETED    /* запис каналу B порожній (канал видалено) */
	/* R97-FIX6: «B == A» більше не помилка (було DC_PAIR_B_IS_A) */
} dcPairCheck_t;

/* Чи можна запустити режим: chA -- абсолютний номер поточного каналу, bInUse -- чи використовується запис chB. */
dcPairCheck_t dcCheckPair(uint16_t chA, uint16_t chB, bool bInUse);

/* Куди піде передача (true = на B): під час прийому/утримання (activity) -- на канал, де рація зараз (onB); інакше -- за покажчиком. */
bool dcTxOnB(bool activity, bool onB, bool pointerB);

/* Крок по «позиціях» (канали зони або номери 1..N «Всіх каналів»). at(pos) повертає номер каналу на позиції pos (0 -- позиція
 * непридатна). Від fromPos (або від краю, якщо fromPos < 0) у напрямку dir (+1/-1), не більше n кроків, пропускаючи канал skip.
 * Повертає нову позицію або -1, якщо придатної нема. */
typedef uint16_t (*dcChanAt_t)(int pos, void *ctx);
int dcStepPos(int n, int fromPos, int dir, uint16_t skip, dcChanAt_t at, void *ctx);
/* Позиція каналу ch серед n позицій або -1. */
int dcFindPos(int n, uint16_t ch, dcChanAt_t at, void *ctx);

#endif /* DUAL_CHANNEL_ENABLED || DUAL_CHANNEL_HOST_TEST */

#if defined(DUAL_CHANNEL_ENABLED)
/* Стан у звичайній RAM (не CCM): 8 байт. Обнуляється статично (.bss) -- «вимкнено». */
void     dcLoad(void);                 /* на старті: блок 18 -> RAM */
bool     dcIsEnabled(void);
bool     dcPointerB(void);
uint16_t dcChannelB(void);
bool     dcIsOnB(void);                /* рація ЗАРАЗ налаштована на B */
void     dcSetOnB(bool onB);
bool     dcTxHoldPending(void);        /* після власної передачі з режиму -- утримати той канал */
void     dcSetTxHold(bool hold);
bool     dcMenuValue(void);            /* тимчасове значення пункту швидкого меню «Подв. прийом» */
void     dcSetMenuValue(bool on);
/* Зміни стану. persistNow -- записати блок одразу (вмикання/вимикання, «Встановити як B»); інакше -- відкладений запис
 * (покажчик, B з валкодера): dcSaveIfDue() пише, коли 3 с не було нових змін (знос флеша, валкодер дає по кроку на клацання). */
bool     dcSetEnabled(bool on, bool persistNow);
void     dcSetPointerB(bool pointerB);
bool     dcSetChannelB(uint16_t chB, bool persistNow);
void     dcSaveIfDue(uint32_t nowMs);
bool     dcFlush(void);
void     dcFlushPending(void);          /* записати, лише якщо є відкладені зміни (вимкнення рації) */
#endif

#endif /* FUNCTIONS_DUAL_CHANNEL_H_ */
