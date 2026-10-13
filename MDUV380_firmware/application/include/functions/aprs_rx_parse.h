/*
 * aprs_rx_parse.h -- розбір прийнятих кадрів APRS (R8): AX.25 UI, типи пакетів, позиція (звичайна,
 * стиснута, Mic-E), повідомлення, статус, дедуплікація, список станцій, відстань/азимут, текст.
 *
 * ЧИСТИЙ C без заліза: той самий файл збирає хост-тест tests/test_aprs_rx_parse.c (синтетичні
 * кадри, зібрані власним кодувальником у тесті). У прошивці -- під ENABLE_APRS_RX; стан (aprsRxDb_t)
 * лежить у CCM (functions/aprs_rx.c), нової main RAM -- 0.
 *
 * Позиція -- int32 мікроградуси (lat -90e6..90e6, lon -180e6..180e6): точність 0,11 м, без float,
 * 8 Б на станцію. Відстань і азимут -- double за тими самими формулами, що вже є в рації
 * (uiUtilities.c: distanceBetweenTwoCoords() / courseTo(); сфера 6372795 м), але окремою функцією, щоб
 * хост-тест не тягнув увесь UI: нових залежностей від libm у прошивці немає (sin/cos/atan2/sqrt там уже
 * використовуються).
 *
 * Кодування тексту: ефір -- байти (APRSdroid та ін. шлють UTF-8, старі станції -- cp1251/latin-1).
 * Шрифт рації -- cp1251. Спершу пробуємо UTF-8 (символи -> cp1251 через dmrSmsUcs2ToCp1251(), таблиця
 * для SMS, окремої НЕ пишемо); якщо байти -- не коректний UTF-8, показуємо їх як cp1251.
 */
#ifndef _OPENGD77_APRS_RX_PARSE_H_
#define _OPENGD77_APRS_RX_PARSE_H_

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "functions/aprs_rx_cfg.h"

#if defined(ENABLE_APRS_RX)

#define APRS_CALL_LEN        10     /* «AAAAAA-SS» + NUL */
#define APRS_PATH_LEN        24     /* «WIDE1-1*,WIDE2-1» + NUL (обрізається) */
#define APRS_TEXT_LEN        80     /* розкодований текст пакета (повідомлення <= 67 симв.) + NUL */
#define APRS_MSGID_LEN       8
#define APRS_STATIONS_MAX    16
#define APRS_STATION_PATH    20     /* шлях у записі станції (обрізається) */
#define APRS_STATION_TEXT    28     /* останній коментар / статус / повідомлення (обрізається) */
#define APRS_DEDUP_MS        30000UL    /* той самий (джерело, info) у межах 30 с -- один пакет */
#define APRS_DEDUP_SLOTS     4
#define APRS_MSG_SEEN_MS     600000UL   /* повтор того самого повідомлення (без ACK відправник повторює) -- 10 хв */
#define APRS_MSG_SEEN_SLOTS  4

typedef enum
{
	APRS_T_OTHER = 0,       /* об'єкти, погода, телеметрія, запити, невпізнане -- лише лічильник */
	APRS_T_POSITION,
	APRS_T_MESSAGE,
	APRS_T_STATUS
} aprsType_t;

/* ---- AX.25 UI ------------------------------------------------------------------------ */
typedef struct
{
	char           src[APRS_CALL_LEN];      /* «CALL-SSID» (SSID 0 -- без суфікса) */
	char           dst[APRS_CALL_LEN];
	char           path[APRS_PATH_LEN];     /* цифіпітери через кому, «*» -- вже ретрансльовано */
	const uint8_t *info;                    /* поле info (вказує всередину кадру) */
	uint16_t       infoLen;
	bool           tp;                      /* R11-fix: кадр розгорнуто з third-party ("}"): src/dst/path/info -- ВКЛАДЕНОГО кадру */
	char           gate[APRS_CALL_LEN];     /* ... а це -- шлюз (i-gate), що ретранслював (справжнє джерело AX.25-кадру); лише при tp */
} aprsAx25_t;

/* Кадр без FCS (FCS перевірив демодулятор). true -- AX.25 UI (контроль 0x03, PID 0xF0) з коректними
 * позивними джерела й призначення. */
bool aprsAx25Parse(const uint8_t *f, uint16_t len, aprsAx25_t *out);

/* R11-fix: third-party traffic (APRS101, розділ «Third-Party Traffic»). i-gate, ретранслюючи пакет з APRS-IS в ефір, загортає його:
 * info = "}" + "SRC>DST[,path]:" + оригінальне info. Якщо ax->info починається з '}' і вкладений заголовок коректний, РОЗГОРТАЄ
 * кадр на місці: src/dst/path/info/infoLen -- вкладеного кадру (тобто СПРАВЖНІЙ відправник), gate -- колишнє src, tp = true.
 * Рівно один рівень: уже розгорнутий кадр (tp) удруге не розгортається; якщо після розгортання info знову починається з '}',
 * aprsPacketParse() віднесе його до APRS_T_OTHER. Обрізаний/побитий заголовок -- false, ax не змінюється (лишається кадр шлюзу, «інше»).
 * Нічого не копіює з info: вказівник лише зсувається всередині того самого кадру. */
bool aprsAx25Unwrap(aprsAx25_t *ax);

/* R15: ЗНАЧЕННЯ "сирого" пакета для екрана «Пакети» (журнал, R16): кадр у текстовому вигляді TNC-2, "SRC>DST,DIGI1*,DIGI2:info".
 * Адреси беруться ПРЯМО з кадру (а не з aprsAx25_t, де шлях обрізано до APRS_PATH_LEN), тож усі 8 цифіпітерів збережено. Байти info
 * < 0x20 або > 0x7E показуються як '.'. Вихід завжди завершено NUL (cap >= 1); довше за cap-1 -- обрізається. Повертає довжину без NUL;
 * 0 і out = "" -- кадр не розібрати як AX.25 UI. Викликати ДО aprsAx25Unwrap() (або з тим самим кадром). */
#define APRS_RAW_TEXT_MAX    256U    /* 255 символів + NUL (R16: журнал кадрів обрізає до APRS_JRN_TEXT-1 = 127) */
size_t aprsAx25ToText(const uint8_t *f, uint16_t len, char *out, size_t cap);

/* R15: якщо кадр був third-party і розгорнутий (ax->tp), дописує до out (вже завершеного NUL, довжина curLen) " => SRC>DST[,path]:info"
 * розгорнутого кадру -- ЛИШЕ якщо все влазить у cap-1; інакше out не змінюється. Повертає нову довжину. */
size_t aprsAx25AppendUnwrapped(char *out, size_t cap, size_t curLen, const aprsAx25_t *ax);

/* ---- пакет APRS ------------------------------------------------------------------------ */
typedef struct
{
	uint8_t  type;                          /* aprsType_t */
	bool     hasPos;
	bool     micE;
	bool     compressed;
	int32_t  latU, lonU;                    /* мікроградуси */
	bool     msgAck;                        /* повідомлення -- ack/rej (текст «ack12»): не зберігається */
	char     msgTo[APRS_CALL_LEN];          /* адресат повідомлення (без пробілів, ВЕРХНІЙ регістр) */
	char     msgId[APRS_MSGID_LEN];         /* номер після «{» (порожній -- нема) */
	char     text[APRS_TEXT_LEN];           /* коментар / статус / текст повідомлення, cp1251 */
	/* R13: символ станції і рух (лише для позиційних пакетів; на стеку викликача, постійної пам'яті не коштує) */
	char     symTable;                      /* '/' основна, '\\' альтернативна, '0'..'9'/'A'..'Z' накладка; 0 -- невідомо */
	char     symCode;                       /* код символу ('!'..'~'); 0 -- невідомо */
	uint16_t course;                       /* градуси 1..360 (0 -- курсу в пакеті нема або "не рухається") */
	uint16_t speedKn;                      /* швидкість, вузли (0 -- нема/стоїть) */
	/* R14: розширення коментаря (commentStrip(), розд. 3 брифу R14). Лише позиційні пакети; на стеку викликача. */
	int32_t  altM;                         /* висота, метри (hasAlt) */
	uint32_t freqKHz;                      /* частота з коментаря "nnn.nnnMHz", кГц; 0 -- нема */
	uint16_t extVal;                       /* PHG/DFS: p,h,g,d по 4 біти (p -- старший); RNG: милі */
	uint16_t rangeVal;                     /* радіус із "Rnnm"/"Rnnk" після частоти (rangeKm -- у км, інакше милі); 0 -- нема */
	int16_t  shiftKHz;                     /* зсув, кГц (hasShift): "-760" у десятках кГц = -7600 */
	uint16_t pressDhPa;                    /* погода: тиск, 0.1 гПа (APRS_WX_PRESS) */
	uint16_t windDeg;                      /* погода: напрям вітру, градуси (APRS_WX_WIND) */
	int16_t  tempC;                        /* погода: температура, °C (APRS_WX_TEMP) */
	char     tone[5];                      /* "T082", "Toff", "C023"; порожній -- нема */
	uint8_t  extKind;                      /* APRS_EXT_* */
	uint8_t  humPct;                       /* погода: вологість, % */
	uint8_t  windMph, gustMph;             /* погода: вітер і порив, милі/год (як у пакеті) */
	uint8_t  wxMask;                       /* APRS_WX_* -- які погодні поля є */
	bool     hasAlt, hasShift, rangeKm;
	bool     killed;                       /* об'єкт/предмет знято з обліку ('_') */
} aprsPacket_t;
#define APRS_EXT_NONE 0
#define APRS_EXT_PHG  1
#define APRS_EXT_RNG  2
#define APRS_EXT_DFS  3
#define APRS_WX_TEMP  0x01
#define APRS_WX_HUM   0x02
#define APRS_WX_PRESS 0x04
#define APRS_WX_WIND  0x08
#define APRS_WX_GUST  0x10

/* Ніколи не відмовляє: невпізнане -> APRS_T_OTHER. */
void aprsPacketParse(const aprsAx25_t *ax, aprsPacket_t *out);

/* Текст ефіру -> cp1251 для екрана (UTF-8, якщо коректний; інакше байти як cp1251). Керівні -> пробіл.
 * Повертає довжину результату. */
size_t aprsDecodeText(const uint8_t *in, size_t n, char *out, size_t outSize);
/* Чи байти -- коректний UTF-8 (без надмірних кодувань і сурогатів). */
bool aprsIsUtf8(const uint8_t *p, size_t n);

/* Повідомлення адресоване нам: ownCall (до 6 симв., будь-який регістр, хвостові пробіли ігноруються),
 * ownSsid 0..15 (більше -- завжди false). msgTo -- вже без хвостових пробілів, ВЕРХНІЙ регістр (aprsPacketParse()).
 * Збіг точний: «CALL-SSID» (SSID 1..15 без нулів попереду); для SSID 0 -- «CALL» або «CALL-0». Пробіл усередині адресата
 * («US5EX -7»), чужий префікс/суфікс («US5EX-70») -- НЕ збіг. */
bool aprsMsgIsForUs(const char *msgTo, const char *ownCall, uint8_t ownSsid);

/* ---- географія ------------------------------------------------------------------------- */
/* Відстань (метри) і азимут (0..359, 0 = північ) від A до B. */
void aprsGeo(int32_t latAU, int32_t lonAU, int32_t latBU, int32_t lonBU, uint32_t *distM, uint16_t *bearingDeg);
/* Назва сектора азимуту: «N» «NE» «E» «SE» «S» «SW» «W» «NW» (8 секторів по 45°). */
const char *aprsBearingName(uint16_t deg);

/* ---- список станцій і дедуплікація ----------------------------------------------------- */
#define APRS_ST_HASPOS   0x01
#define APRS_ST_MICE     0x02
#define APRS_ST_TP       0x04   /* R14: останній кадр прийшов через i-gate (third-party) */

typedef struct
{
	char     call[APRS_CALL_LEN];           /* call[0] == 0 -- вільний запис */
	uint8_t  type;                          /* тип ОСТАННЬОГО пакета (aprsType_t) */
	uint8_t  flags;                         /* APRS_ST_* */
	uint16_t count;                         /* пакетів (без дублікатів), насичується на 65535 */
	int32_t  latU, lonU;                    /* остання відома позиція (flags & HASPOS) */
	uint32_t lastMs;                        /* ticksGetMillis() останнього пакета */
	char     path[APRS_STATION_PATH];
	char     text[APRS_STATION_TEXT];       /* останній непорожній коментар / статус / повідомлення */
} aprsStation_t;

typedef struct
{
	aprsStation_t st[APRS_STATIONS_MAX];
	struct { uint32_t hash; uint32_t ms; } dedup[APRS_DEDUP_SLOTS];
	struct { uint32_t hash; uint32_t ms; } seen[APRS_MSG_SEEN_SLOTS];
	uint8_t dedupNext, seenNext;
	uint16_t tpUnwrapped;                   /* R11-fix: скільки кадрів розгорнуто з third-party (у байтах вирівнювання -- розмір структури не росте) */
	uint32_t total;                         /* пакетів з коректним FCS, розібраних як AX.25 UI */
	uint32_t dups;                          /* ... з них дублікатів */
	uint32_t other;                         /* ... з них APRS_T_OTHER */
} aprsRxDb_t;

void aprsDbInit(aprsRxDb_t *db);
/* true -- такий (джерело, info) уже був у межах APRS_DEDUP_MS (дублікат). Інакше запам'ятовує й false. */
bool aprsDbIsDuplicate(aprsRxDb_t *db, const aprsAx25_t *ax, uint32_t nowMs);
/* Додати/оновити станцію. Нема місця -- замінюється НАЙСТАРІШИЙ запис (найбільший вік). Повертає запис. */
aprsStation_t *aprsDbUpdate(aprsRxDb_t *db, const aprsAx25_t *ax, const aprsPacket_t *pkt, uint32_t nowMs);
/* Скільки зайнято. */
int aprsDbCount(const aprsRxDb_t *db);
/* n-та за новизною станція (0 -- найновіша); NULL -- n поза межами. */
const aprsStation_t *aprsDbNth(const aprsRxDb_t *db, int n, uint32_t nowMs);
/* true -- це повідомлення (джерело, номер, текст) уже віддавали нам у межах APRS_MSG_SEEN_MS. Інакше
 * запам'ятовує й false. */
bool aprsDbMsgSeen(aprsRxDb_t *db, const aprsAx25_t *ax, const aprsPacket_t *pkt, uint32_t nowMs);

/* ---- R13: вікно маяка (чиста логіка, хост-тести) ----------------------------------------------------------------- */
/* Режими налаштування «Вікно маяка» (2 біти nonVolatileSettings.bitfieldOptions; 0 -- типово «Усі»). */
typedef enum
{
	APRS_BCNWIN_ALL = 0,    /* кожен позиційний пакет */
	APRS_BCNWIN_NEW = 1,    /* лише перший пакет станції, якої ще нема у списку */
	APRS_BCNWIN_OFF = 2     /* вікна нема (лишається звичайний банер) */
} aprsBcnWinMode_t;

/* Чи показувати вікно для цього пакета: позиційний (звичайна, стиснута, Mic-E; координат у пакеті може й не бути -- тоді вікно без стрілки) і режим дозволяє.
 * isNewStation -- станцію щойно додано до списку (її перший пакет). */
bool aprsBeaconWindowWanted(aprsBcnWinMode_t mode, const aprsPacket_t *pkt, bool isNewStation);

/* Геометрія стрілки «від центру в бік станції»: центр (cx,cy), довжина len (піксели), азимут bearingDeg (0 = північ угорі, за годинниковою;
 * будь-яке значення береться по модулю 360). Вістря (tx,ty); крила (lx,ly) і (rx,ry) -- кінці двох відрізків від вістря назад під ±28° до
 * осі, завдовжки ~40% len (не менше 4 px). Координати округлено до цілих; екран -- y вниз. */
typedef struct
{
	int16_t tx, ty;
	int16_t lx, ly;
	int16_t rx, ry;
} aprsArrow_t;
void aprsArrowGeom(aprsArrow_t *a, int16_t cx, int16_t cy, int16_t len, uint16_t bearingDeg);
/* Чи малювати стрілку: є відстань/азимут і станція не в тій самій точці (azimut при нульовій відстані не визначений). */
bool aprsBeaconArrowVisible(bool hasGeo, uint32_t distM);
/* Вузли -> км/год (округлено до цілих; 1 вузол = 1.852 км/год). */
uint16_t aprsKnotsToKmh(uint16_t kn);

/* ---- R16: історія прийому (журнал кадрів + дані маяка кожної станції) ------------------------------------------- */
/* Поля даних маяка -- ОДИН список для запису станції (aprsBcnRec_t) і для вікна маяка (aprsRxWin_t, aprs_rx.h): вікно = запис + active + call,
 * тож відкриття вікна станції -- один memcpy. Позивного в записі нема (він у db.st[i].call), прапорець "активне" -- у вікні.
 * Радіо (частота/тон/зсув/PHG/радіус) і погода ділять одне місце (union, 16 Б): вони не зустрічаються разом -- погода розбирається лише
 * для символу '_', і тоді має перевагу. */
#define APRS_BCN_REC_FIELDS \
	bool      hasGeo;           /* є відстань і азимут (є позиція станції й власна) */ \
	uint16_t  bearing;          /* азимут на станцію від півночі, 0..359 */ \
	uint16_t  course;           /* курс станції, 1..360; 0 -- нема */ \
	uint16_t  speedKn;          /* швидкість, вузли; 0 -- нема/стоїть */ \
	uint32_t  distM; \
	uint32_t  rxSecs;           /* uiDataGlobal.dateTimeSecs у момент прийому */ \
	int32_t   altM;             /* висота, м (AWIN_F_ALT) */ \
	union \
	{ \
		struct \
		{ \
			uint32_t freqKHz;   /* 0 -- нема */ \
			int16_t  shiftKHz;  /* AWIN_F_SHIFT */ \
			uint16_t extVal;    /* PHG/DFS: 4 hex-цифри phgd; RNG: милі */ \
			uint16_t rangeVal;  /* радіус, милі або км (AWIN_F_RANGE_KM); 0 -- нема */ \
			char     tone[5];   /* "T082" / "Toff" / "" */ \
		} r; \
		struct \
		{ \
			int16_t  tempC; \
			uint16_t pressDhPa; /* 0.1 гПа */ \
			uint16_t windDeg; \
			uint8_t  humPct, windMph, gustMph; \
		} wx; \
	} u; \
	uint8_t   flags;            /* AWIN_F_* */ \
	uint8_t   extKind;          /* APRS_EXT_* */ \
	uint8_t   wxMask;           /* APRS_WX_*; ненульовий -- у u діє wx */ \
	char      symTable, symCode; \
	char      text[APRS_STATION_TEXT];
#define AWIN_F_ALT       0x01
#define AWIN_F_SHIFT     0x02
#define AWIN_F_RANGE_KM  0x04
#define AWIN_F_MANUAL    0x08   /* R15: вікно відкрито з меню («Останній маяк») -- живе до RED незалежно від екрана й каналу */
#define AWIN_F_VALID     0x10   /* R16: запис маяка заповнено (нуль у flags -- маяка від цієї станції не було) */
typedef struct
{
	APRS_BCN_REC_FIELDS
} aprsBcnRec_t;

#define APRS_JRN_SLOTS   8      /* скільки останніх кадрів тримає журнал */
#define APRS_JRN_TEXT    128    /* кадр у вигляді TNC-2: 127 символів + NUL */
typedef struct
{
	uint32_t rxSecs;            /* uiDataGlobal.dateTimeSecs у момент прийому */
	char     text[APRS_JRN_TEXT];
} aprsJrnEntry_t;

/* Увесь стан історії -- ОДИН блок у резерві «Переслухати» (callReplay.h: CALL_REPLAY_APRS_HIST_BYTES; _Static_assert у aprs_mode.c).
 * bcn[] індексований ТАК САМО, як aprsRxDb_t.st[]. Нулі = порожньо, тож обнулення резерву на старті (callReplayBorrowReset()) його ініціалізує. */
typedef struct
{
	aprsBcnRec_t   bcn[APRS_STATIONS_MAX];
	aprsJrnEntry_t jrn[APRS_JRN_SLOTS];
	uint8_t        jrnHead;     /* куди писати наступний кадр */
	uint8_t        jrnCount;    /* 0..APRS_JRN_SLOTS */
	uint8_t        lastBcn1;    /* 1 + індекс найсвіжішого запису маяка; 0 -- маяків ще не було */
} aprsHist_t;

void aprsHistClear(aprsHist_t *h);            /* усе в нуль */
void aprsHistClearBeacons(aprsHist_t *h);     /* лише дані маяків (після скидання списку станцій) */
/* ГОЛОВНА ПАСТКА: aprsDbUpdate() витісняє найстарішу станцію й займає її слот -- запис маяка цього слота мусить бути обнулений, інакше нова
 * станція покаже чужі дані. Викликати ПІСЛЯ aprsDbUpdate() для кожного пакета: нова станція (count == 1) -- запис обнуляється. */
void aprsHistStationTouch(aprsHist_t *h, const aprsRxDb_t *db, const aprsStation_t *s);
/* Записати маяк станції s (за позиційним пакетом): geo -- відстань/азимут, якщо відомі. stText -- коментар станції (обрізаний). Робить запис
 * "найсвіжішим". Повертає запис. */
const aprsBcnRec_t *aprsHistBeaconFill(aprsHist_t *h, const aprsRxDb_t *db, const aprsStation_t *s, const aprsPacket_t *pkt,
		bool hasGeo, uint32_t distM, uint16_t bearing, uint32_t rxSecs);
/* Запис маяка станції; NULL -- маяків від неї не було (або s не з db). */
const aprsBcnRec_t *aprsHistBeaconOf(const aprsHist_t *h, const aprsRxDb_t *db, const aprsStation_t *s);
/* Найсвіжіший запис маяка і індекс його станції в db.st[]; NULL -- нема. */
const aprsBcnRec_t *aprsHistBeaconLast(const aprsHist_t *h, int *dbIdx);
/* R17 Г4: станції, між якими гортається вікно маяка: ті самі, що в «APRS станції», у ТОМУ Ж порядку (найновіша першою, aprsDbNth()), але лише ті,
 * що мають збережений маяк (AWIN_F_VALID) і позицію (APRS_ST_HASPOS). out[] -- індекси в db.st[], не більше max; повертає скільки записано. */
int aprsHistBeaconOrder(const aprsHist_t *h, const aprsRxDb_t *db, uint32_t nowMs, uint8_t *out, int max);
/* Позиція індексу dbIdx у списку order[0..count) (0-based); -1 -- його там нема. */
int aprsBeaconOrderFind(const uint8_t *order, int count, int dbIdx);
/* Сусід у списку: від позиції pos на step (+1 -- старіша, -1 -- новіша), кільцем. pos < 0 (станції нема у списку): step > 0 дає першу, step < 0 -- останню. -1 -- список порожній. */
int aprsBeaconOrderStep(int pos, int count, int step);

/* Журнал: кадр -> TNC-2 (aprsAx25ToText(), непечатні -> '.'), обрізано до APRS_JRN_TEXT-1. false -- кадр не розібрати як AX.25 UI (не записано).
 * Викликати ДО aprsAx25Unwrap(). */
bool aprsJrnAdd(aprsHist_t *h, uint32_t rxSecs, const uint8_t *frame, uint16_t len);
/* n-й за новизною (0 -- найновіший); NULL -- n поза межами. */
const aprsJrnEntry_t *aprsJrnNth(const aprsHist_t *h, int n);
/* Номер слота журналу (0..APRS_JRN_SLOTS-1), у якому лежить n-й за новизною кадр; -1 -- n поза межами. І навпаки: запис слота (NULL -- слот порожній), n за новизною. */
int aprsJrnSlotOf(const aprsHist_t *h, int n);
const aprsJrnEntry_t *aprsJrnAtSlot(const aprsHist_t *h, int slot);
int aprsJrnNOfSlot(const aprsHist_t *h, int slot);
/* Для рядка списку: позивний джерела (до '>', не довше APRS_CALL_LEN-1) і DTI (перший байт info після першого ':'; '-' -- info порожнє). */
void aprsJrnSummary(const aprsJrnEntry_t *e, char *call, char *dti);

#endif /* ENABLE_APRS_RX */
#endif /* _OPENGD77_APRS_RX_PARSE_H_ */
