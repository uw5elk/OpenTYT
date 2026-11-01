/*
 * wake_diag.h -- R58: журнал сеансів пробудження ретранслятора (лише діагностична збірка).
 *
 * Мета -- виміряти на залізі те, чого немає в коді (R57 §9): реальний час до AWAKEN і до FAILED,
 * кількість пакетів WAKE_1, затримку Δ від «нуля» таймера до наступного пакета, а також (з
 * ENABLE_WAKE_HOP_TEST) що відбувається після стрибка на інший канал під утримуваним PTT.
 *
 * Компілюється лише з -DENABLE_WAKE_DIAG (Makefile; у користувацьких збірках НЕ вмикати).
 * Без нього файл порожній, а виклики в HR-C6000.c / uiTxScreen.c / menuMessages.c / usb_com.c
 * загорнуті в той самий #if -- типова збірка байт-у-байт та сама.
 *
 * Логіка не залежить від заліза: час передається параметром (now, мс), тож хостовий тест
 * (tests/test_wake_diag.c) ганяє її без рації. Записи гарячого шляху ISR -- лише присвоєння й
 * інкременти простих полів; жодних memcpy структур з ISR (memset нового сеансу робить тік).
 */
#ifndef FUNCTIONS_WAKE_DIAG_H_
#define FUNCTIONS_WAKE_DIAG_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_WAKE_DIAG)

#if !(defined(ENABLE_AES) && defined(ENABLE_DMR_DATA))
#error "ENABLE_WAKE_DIAG потребує ENABLE_AES і ENABLE_DMR_DATA (екран журналу -- у меню «Повідомлення»)"
#endif

#define WAKE_DIAG_SESSIONS   12U     /* кільце: кількість останніх сеансів (рахунок пам'яті -- у звіті R58) */
#define WAKE_DIAG_PKT_MAX     6U     /* скільки часів пакетів WAKE_1 зберігати в сеансі (зайве лише рахується) */
#define WAKE_DIAG_ZERO_MAX    6U     /* скільки часів «нулів» таймера зберігати в сеансі */
#define WAKE_DIAG_NONE      0xFFFFU  /* «події не було» у полях часу */

/* Результат попереднього сеансу (біти 0..1 поля flags). */
#define WAKE_DIAG_PREV_NONE     0U   /* перший сеанс після увімкнення / скидання журналу */
#define WAKE_DIAG_PREV_OK       1U   /* попередній дійшов до AWAKEN */
#define WAKE_DIAG_PREV_FAIL     2U   /* попередній завершився FAILED */
#define WAKE_DIAG_PREV_CANCEL   3U   /* попередній обірвано (ні AWAKEN, ні FAILED) */
#define WAKE_DIAG_FLAG_PREV_MASK 0x03U
#define WAKE_DIAG_FLAG_HOP_START 0x04U  /* сеанс почався після стрибка (ENABLE_WAKE_HOP_TEST) */

/* Один сеанс. Часи -- мілісекунди від старту сеансу, WAKE_DIAG_NONE = не було; насичуються на 0xFFFE. */
typedef struct
{
	uint32_t rxFreq;      /* currentRxFrequency (одиниці 10 Гц, як у трансівері) */
	uint32_t txFreq;
	uint16_t chan;        /* номер каналу (uiDataGlobal.currentSelectedChannelNumber) */
	uint8_t  cc;          /* колір-код */
	uint8_t  flags;       /* WAKE_DIAG_PREV_* | WAKE_DIAG_FLAG_* */
	uint16_t to0;         /* repeaterWakeupResponseTimeout на старті: 0 -- випадок B (R57 §1), >0 -- випадок A */
	uint16_t tAwaken;     /* isWaking -> AWAKEN */
	uint16_t tTx;         /* старт передачі після AWAKEN (hrc6000TransitionToTx) */
	uint16_t tFail;       /* isWaking -> FAILED */
	uint16_t hopT;        /* час стрибка з цього сеансу (ENABLE_WAKE_HOP_TEST) */
	uint16_t hopChan;     /* номер нового каналу після стрибка */
	uint8_t  pkts;        /* усього пакетів WAKE_1 (може бути більше WAKE_DIAG_PKT_MAX) */
	uint8_t  zeros;       /* усього «нулів» таймера (кожен = спроба або відмова) */
	uint8_t  maxToggle;   /* максимум rxTSToggled у WAKE_3 */
	uint8_t  intTmo;      /* скільки разів у цьому сеансі спрацював INTERRUPT_TIMEOUT */
	uint16_t pktT[WAKE_DIAG_PKT_MAX];
	uint16_t zeroT[WAKE_DIAG_ZERO_MAX];
} wakeDiagSession_t;

/* Розмір одного запису в USB-дампі (0xB7) -- див. wakeDiagDump(). */
#define WAKE_DIAG_REC_LEN    52U
#define WAKE_DIAG_DUMP_HDR    8U
#define WAKE_DIAG_DUMP_VER    1U

void wakeDiagInit(void);                       /* обнулити журнал (CCM-INIT/BSS не гарантує нулів) */
void wakeDiagReset(void);                      /* те саме за командою оператора */

/* Гачки (викликає HR-C6000.c: старт/пакет/нуль -- задача HRC6000, пакет/AWAKEN/TX/токл -- ISR). */
void wakeDiagBegin(uint32_t now, int16_t chan, uint32_t rxFreq, uint32_t txFreq, uint8_t cc, uint16_t to0);
void wakeDiagPacket(uint32_t now);
void wakeDiagZero(uint32_t now);
void wakeDiagAwaken(uint32_t now);
void wakeDiagTxStart(uint32_t now);            /* без відкритого сеансу -- лічиться як «пряма передача» */
void wakeDiagFail(uint32_t now);
void wakeDiagToggle(uint8_t value);
void wakeDiagIntTimeout(void);
void wakeDiagHop(uint32_t now, int16_t newChan);   /* стрибок: позначити в поточному сеансі, наступний -- HOP_START */

/* Читання (екран, USB). age 0 = найновіший. */
uint8_t  wakeDiagCount(void);
bool     wakeDiagGet(uint8_t age, wakeDiagSession_t *out);
uint16_t wakeDiagDirectTx(void);

/* Серіалізація для USB: [ver, макс. сеансів, кількість, 0, u32 directTx] + кількість x запис (LE, найновіший першим).
 * Повертає довжину; сеанси, що не влізли в max, відкидаються з кінця (старіші). */
int wakeDiagDump(uint8_t *buf, int max);

/* Текст екрана: рядок line (0..WAKE_DIAG_LINES-1) сеансу s з порядковим номером age (0 = найновіший) з total.
 * Повертає false, якщо такого рядка немає. Формати -- нижче (укр. або англ. залежно від збірки). */
#define WAKE_DIAG_LINES 9U
bool wakeDiagLine(const wakeDiagSession_t *s, unsigned age, unsigned total, unsigned directTx,
		unsigned line, char *buf, int bufSize);

/* Формати рядків екрана: FONT_SIZE_1, до 26 символів у рядок. Укр. значення -- languages/wakediag_ua.h (cp1251). */
#if defined(LANGUAGE_BUILD_UKRAINIAN)
#include "user_interface/languages/wakediag_ua.h"
#else
#define WAKE_TITLE_FMT    "Wake %u/%u"
#define WAKE_ITEM         "Wake-up log"
#define WAKE_EMPTY        "(no wake-ups yet)"
#define WAKE_HINT         "U/D:session L:reset"
#define WAKE_L1_FMT       "#%u RX %lu.%04lu CC%u"
#define WAKE_L2_FMT       "TX %lu.%04lu to0=%u"
#define WAKE_L3_FMT       "prev:%s hs:%s dir %u"
#define WAKE_PKT_FMT      "Pkt%u:"
#define WAKE_ZERO_FMT     "Zero%u:"
#define WAKE_L7_FMT       "Awk %s Tx %s Fl %s"
#define WAKE_L8_FMT       "ts%u it%u hop %s>%u"
#define WAKE_PREV_NONE_S  "-"
#define WAKE_PREV_OK_S    "ok"
#define WAKE_PREV_FAIL_S  "fail"
#define WAKE_PREV_CNCL_S  "cncl"
#define WAKE_YES_S        "y"
#define WAKE_NO_S         "n"
#endif

#endif /* ENABLE_WAKE_DIAG */

#endif /* FUNCTIONS_WAKE_DIAG_H_ */
