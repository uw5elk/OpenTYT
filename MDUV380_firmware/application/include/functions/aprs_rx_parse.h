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
} aprsAx25_t;

/* Кадр без FCS (FCS перевірив демодулятор). true -- AX.25 UI (контроль 0x03, PID 0xF0) з коректними
 * позивними джерела й призначення. */
bool aprsAx25Parse(const uint8_t *f, uint16_t len, aprsAx25_t *out);

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
} aprsPacket_t;

/* Ніколи не відмовляє: невпізнане -> APRS_T_OTHER. */
void aprsPacketParse(const aprsAx25_t *ax, aprsPacket_t *out);

/* Текст ефіру -> cp1251 для екрана (UTF-8, якщо коректний; інакше байти як cp1251). Керівні -> пробіл.
 * Повертає довжину результату. */
size_t aprsDecodeText(const uint8_t *in, size_t n, char *out, size_t outSize);
/* Чи байти -- коректний UTF-8 (без надмірних кодувань і сурогатів). */
bool aprsIsUtf8(const uint8_t *p, size_t n);

/* Повідомлення адресоване нам: ownCall (до 6 симв., будь-який регістр, хвостові пробіли ігноруються),
 * ownSsid 0..15. Збіг: «CALL-SSID»; для SSID 0 -- «CALL» або «CALL-0». */
bool aprsMsgIsForUs(const char *msgTo, const char *ownCall, uint8_t ownSsid);

/* ---- географія ------------------------------------------------------------------------- */
/* Відстань (метри) і азимут (0..359, 0 = північ) від A до B. */
void aprsGeo(int32_t latAU, int32_t lonAU, int32_t latBU, int32_t lonBU, uint32_t *distM, uint16_t *bearingDeg);
/* Назва сектора азимуту: «N» «NE» «E» «SE» «S» «SW» «W» «NW» (8 секторів по 45°). */
const char *aprsBearingName(uint16_t deg);

/* ---- список станцій і дедуплікація ----------------------------------------------------- */
#define APRS_ST_HASPOS   0x01
#define APRS_ST_MICE     0x02

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

#endif /* ENABLE_APRS_RX */
#endif /* _OPENGD77_APRS_RX_PARSE_H_ */
