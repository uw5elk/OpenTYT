/*
 * ta_diag.h -- R88: ДІАГНОСТИКА сирого Talker Alias і GPS-блока LC (лише збірка з ENABLE_TA_DIAG).
 *
 * Навіщо. R86 з'ясував, що невідомо, ЩО саме приходить від чужих радіо: формат TA (7-біт / ISO-8 / UTF-8 / UTF-16), довжина,
 * склейка блоків, чи є координати в тексті, чи приходить блок LC 0x08. Цей модуль лише ЗАПАМ'ЯТОВУЄ те, що вже прочитала
 * прошивка, і форматує для екрана «TA diag» (Опції рації, останній пункт). Нічого не пише у кодплаг/флеш, не змінює прийом.
 *
 * Хуки (усі під TA_DIAG, у звичайних збірках їх НЕМАЄ):
 *   taDiagRawLC()      -- hardware/HR-C6000.c, одразу після читання LC з чипа (лише LC з правильним CRC): гістограма FLCO.
 *   taDiagCallLC()     -- там само, у гілці, що пройшла фільтри слота/кольорового коду: дзвінок, блоки TA, блок GPS.
 *   taDiagFwText()     -- user_interface/uiUtilities.c: що саме отримав у talkerAlias декодер прошивки.
 * Чисті функції форматування (taDiagHex, taDiagParseHeader, taDiagDecode, taDiagParseGps, taDiagFmt*) від заліза не залежать
 * і тестуються на хості (tests/test_ta_diag.c).
 */
#ifndef FUNCTIONS_TA_DIAG_H_
#define FUNCTIONS_TA_DIAG_H_

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#if defined(ENABLE_TA_DIAG)
#define TA_DIAG 1

#define TA_DIAG_RECORDS     3U     /* останні виклики (кільце) */
#define TA_DIAG_BLOCKS      4U     /* LC 0x04..0x07 */
#define TA_DIAG_BLOCK_LEN   7U     /* корисних байтів у блоці (LC[2..8]) */
#define TA_DIAG_BUF_LEN     32U    /* як bufferTA[32] у uiUtilities.c: 28 байтів блоків + нулі */
#define TA_DIAG_FLCO_COUNT  64U    /* FLCO -- 6 біт (LC[0] & 0x3F) */
#define TA_DIAG_FW_TEXT_LEN 32U    /* як LinkItem_t.talkerAlias[32] */

typedef struct
{
	uint32_t srcId;                                         /* з LC 0 / 3: байти 6..8 */
	uint32_t tgOrPc;                                        /* з LC 0 / 3: байти 3..5 */
	uint8_t  isPc;                                          /* 1 -- приватний виклик (FLCO 3), 0 -- група (FLCO 0) */
	uint8_t  taMask;                                        /* біт n -- блок 4+n приходив хоч раз */
	uint8_t  taSeen[TA_DIAG_BLOCKS];                        /* скільки РАЗІВ змінився вміст блока (повтори не рахуються) */
	uint8_t  taFid[TA_DIAG_BLOCKS];                         /* байт LC[1] останнього блока */
	uint8_t  ta[TA_DIAG_BLOCKS][TA_DIAG_BLOCK_LEN];         /* сирі байти LC[2..8] блока */
	uint8_t  gpsSeen;                                       /* скільки разів приходив блок 0x08 (зміна вмісту) */
	uint8_t  gpsFid;
	uint8_t  gpsRaw[TA_DIAG_BLOCK_LEN];                     /* LC[2..8] останнього блока 0x08 */
	uint8_t  flco[TA_DIAG_FLCO_COUNT];                      /* гістограма FLCO у цьому виклику (насичується на 255) */
	char     fwText[TA_DIAG_FW_TEXT_LEN];                   /* копія LinkHead->talkerAlias після декодера прошивки */
} taDiagRec_t;

typedef struct
{
	uint8_t  format;      /* LC[2] біти 7..6: 0 7-біт, 1 ISO-8, 2 UTF-8, 3 UTF-16 */
	uint8_t  size;        /* біти 5..1: довжина тексту в символах */
	uint8_t  bit0;        /* молодший біт заголовка (не використовується декодером прошивки) */
} taDiagHdr_t;

/* ---- чисті функції (без заліза) ---- */
/* Шістнадцяткове подання n байтів (великі літери, без роздільників). Завжди завершує рядок нулем; не виходить за outSize.
 * Повертає кількість записаних символів (без нуля). */
size_t taDiagHex(char *out, size_t outSize, const uint8_t *b, size_t n);
/* Розбір першого байта заголовка TA (LC[2] блока 0x04). */
void taDiagParseHeader(uint8_t b0, taDiagHdr_t *h);
const char *taDiagFormatName(uint8_t format);
/* Те саме, що decodeTA() у uiUtilities.c, але з межами: buf -- рівно TA_DIAG_BUF_LEN байтів (склейка блоків 0..3 + нулі),
 * dest -- destLen >= 2 байти. Повертає strlen(dest). */
size_t taDiagDecode(const uint8_t *buf, char *dest, size_t destLen);
/* Склейка блоків у буфер TA_DIAG_BUF_LEN байтів: відсутні блоки -- нулі (як memset у прошивці). */
void taDiagGlue(const taDiagRec_t *r, uint8_t *buf);
/* Розбір блока GPS (LC[2..8], 7 байтів) тією ж арифметикою, що decodeGPSPosition(); результат -- десятитисячні частки градуса
 * (як roundPosition: 4 знаки після коми). errIdx -- код похибки з LC[2] біти 3..1. false, якщо вказівник NULL. */
bool taDiagParseGps(const uint8_t *d7, int32_t *latE4, int32_t *lonE4, uint8_t *errIdx);
/* "-12.3456" (знак лише для від'ємних; ціла частина без нулів зліва). */
void taDiagFmtDeg(char *out, size_t outSize, int32_t e4);
/* Наступний рядок гістограми FLCO: токени "NN:кількість" (NN -- hex) для ненульових, скільки влізе в width символів.
 * *cursor -- наступний індекс FLCO (початково 0). false, коли нічого більше. */
bool taDiagFlcoRow(const uint8_t *cnt, size_t *cursor, char *out, size_t outSize, size_t width);
/* Друкований вигляд байтів тексту: <0x20 і 0x7F -> '.', решта як є (кириличні коди 0xC0..0xFF малюються шрифтом збірки). */
void taDiagPrintable(char *out, size_t outSize, const char *src, size_t offset, size_t n);

/* ---- запам'ятовування (зі заліза) ---- */
void taDiagInit(void);
void taDiagRawLC(const uint8_t *lc);                         /* усі LC з правильним CRC, будь-який слот */
void taDiagCallLC(const uint8_t *lc);                        /* LC, що пройшли фільтр слота/кольорового коду */
void taDiagFwText(const char *talkerAlias);
/* Доступ для екрана: 0 -- найновіший. NULL, якщо запису ще немає. */
const taDiagRec_t *taDiagGet(size_t age);
size_t taDiagCount(void);
uint32_t taDiagAllFlcoTotal(void);
const uint8_t *taDiagAllFlco(void);                          /* гістограма всіх LC (64 байти) */
uint32_t taDiagPfCount(void);                                /* LC з бітом PF (LC[0] & 0x80) */
uint32_t taDiagCrcBadCount(void);                            /* LC із поганим CRC (лише лічильник) */
void taDiagNoteBadCrc(void);
#endif

#endif /* FUNCTIONS_TA_DIAG_H_ */
