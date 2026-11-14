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
 *   [4] R98: тип B: 0 -- канал кодплага (номер у [2..3]); 1 -- VFO A; 2 -- VFO B; інше -> 0 (канал). Для VFO номер у [2..3]
 *       зберігається як є (останній канал B), але не використовується
 *   [5] R98: тип A (читається; підтримано лише 0 -- «поточний канал»; ненульове трактується як 0, без помилки)
 *   [6..7] резерв (0)
 * Старі записи (R97: [4..7] = 0) читаються як «B -- канал». Якщо блоку нема або він нечинний -- режим вимкнено, покажчик на A, B не задано.
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
#define DC_TYPE_CHANNEL     0U     /* R98: B -- канал кодплага */
#define DC_TYPE_VFO_A       1U     /* R98: B -- VFO A */
#define DC_TYPE_VFO_B       2U     /* R98: B -- VFO B */

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
/* R98: те саме з типами A/B (reserved[0] -- тип B; reserved[1] біти 0..1 -- тип ПОТОЧНОГО A, R98-FIX4); тип поза 0..2 -> 0. Старі виклики = типи 0.
 * R98-FIX4 А/Б7 -- розкладка reserved[1..3] (довжина блоку та сама, 8 Б):
 *   reserved[1] біти 0..1 -- тип поточного A (0 канал, 1 VFO A, 2 VFO B; 3 -> 0);
 *   reserved[1] біти 2..3 -- «A для повернення» (0 нема, 1 канал, 2 VFO A, 3 VFO B); reserved[2..3] -- його номер каналу (uint16 LE, 1..1024).
 * Прошивки до R98-FIX4 reserved[1..3] не читають (тип A у них завжди 0) і при записі обнуляють. */
bool dcCfgParseEx(const dcOnFlashCfg_t *raw, bool *enabled, bool *pointerB, uint16_t *chB, uint8_t *typeB, uint8_t *typeA);
void dcCfgBuildEx(dcOnFlashCfg_t *raw, bool enabled, bool pointerB, uint16_t chB, uint8_t typeB, uint8_t typeA);
/* R98: чи ціль (тип, індекс) A збігається з ціллю B. Ключ -- пара (тип, індекс): канали -- за номером, VFO -- за типом
 * (індекс ігнорується); пара «канал A, VFO B» ніколи не рівна, два різні VFO -- теж. Номер -1 як ключ не використовується. */
bool dcSameTarget(uint8_t typeA, uint16_t idxA, uint8_t typeB, uint16_t idxB);
/* R98-FIX4 А: «A для повернення» у блоці. Get: false -- нема (або номер поза 1..1024 для каналу); тип -- DC_TYPE_*. Set: тип DC_TYPE_*, idx -- лише для каналу. */
bool dcCfgGetReturnA(const dcOnFlashCfg_t *raw, uint8_t *type, uint16_t *idx);
void dcCfgSetReturnA(dcOnFlashCfg_t *raw, uint8_t type, uint16_t idx);
void dcCfgCopyReturnA(dcOnFlashCfg_t *dst, const dcOnFlashCfg_t *src);

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
/* R98: крок ручки на картці B по ЗАМКНЕНОМУ циклу «канали зони (позиції 0..n-1) -> VFO A (n) -> VFO B (n+1) -> перший канал».
 * fromExt -- поточна позиція (канал: позиція в зоні; VFO A = n; VFO B = n+1; <0 або поза циклом -- старт від краю за напрямком).
 * Непридатні позиції каналів (at() == 0) пропускаються; VFO придатні завжди. Повертає нову позицію (0..n+1) або -1 (лише якщо n < 0). */
int dcStepExt(int n, int fromExt, int dir, dcChanAt_t at, void *ctx);
/* Позиція каналу ch серед n позицій або -1. */
int dcFindPos(int n, uint16_t ch, dcChanAt_t at, void *ctx);

#endif /* DUAL_CHANNEL_ENABLED || DUAL_CHANNEL_HOST_TEST */

#if defined(DUAL_CHANNEL_ENABLED)
/* Стан у звичайній RAM (не CCM): 8 байт. Обнуляється статично (.bss) -- «вимкнено». */
void     dcLoad(void);                 /* на старті: блок 18 -> RAM */
bool     dcIsEnabled(void);
bool     dcPointerB(void);
uint16_t dcChannelB(void);
uint8_t  dcTypeB(void);                /* R98: DC_TYPE_* цілі B */
bool     dcBIsVfo(void);
void     dcSetTypeB(uint8_t typeB);     /* відкладений запис (як покажчик/B з валкодера) */
uint8_t  dcTypeA(void);                /* R98-FIX4 Б: DC_TYPE_* поточного A (2 біти у вільних бітах стану -- RAM не росте) */
bool     dcAIsVfo(void);
void     dcSetTypeA(uint8_t typeA);     /* відкладений запис */
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
/* R98-FIX4 А: вимкнути режим і ОДНИМ записом блоку зберегти «A для повернення» (лише при вимкненні на обраній картці B). */
bool     dcDisableWithReturnA(uint8_t typeRet, uint16_t idxRet);
/* R98-FIX4 А: прочитати «A для повернення» з блоку (одне читання при вмиканні). */
bool     dcGetReturnA(uint8_t *typeRet, uint16_t *idxRet);
#endif

#endif /* FUNCTIONS_DUAL_CHANNEL_H_ */
