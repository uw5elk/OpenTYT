/*
 * aprs_msg.h -- повідомлення APRS (R11): складання інфо-поля, UTF-8 <-> cp1251, список і черга з повторами та ACK.
 *
 * ЧИСТИЙ C без заліза (як aprs_rx_parse.c / aprs_mode_cfg.c): час передається параметром, передача -- не тут. Той самий
 * файл збирає хост-тест tests/test_aprs_msg.c. У типовій збірці (без ENABLE_APRS_RX) порожній translation unit.
 *
 * Формат (APRS101, розділ 14; перевірено за описом протоколу, див. aprs_msg.c):
 *   повідомлення  ":ADDRESSEE_:текст{NN"   -- адресат доповнено пробілами рівно до 9 символів, '{' + номер БЕЗ закриваючої
 *                                             дужки (у брифі «{NN}» -- це позначка поля, а не літеральна «}»);
 *   ACK           ":ADDRESSEE_:ackNN"      -- без дужок; номер -- такий самий, як у повідомленні, якому відповідаємо.
 * Текст в ефірі -- UTF-8 (APRSdroid, aprs.fi показують кирилицю); у рації -- cp1251 (шрифт). Межа 67 БАЙТ UTF-8 (кирилиця
 * -- по 2 байти на літеру), літера не рветься.
 *
 * Пам'ять. Блок aprsMsgBox_t (~1,3 КБ) лежить у стані «Режиму APRS» (позичений буфер «Переслухати», aprs_mode.c) і
 * існує лише поки відкрито режим -- у CCM користувацької збірки він НІЧОГО не займає (вільно лишається 328 Б).
 */
#ifndef _OPENGD77_APRS_MSG_H_
#define _OPENGD77_APRS_MSG_H_

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "functions/aprs_rx_cfg.h"

#if defined(ENABLE_APRS_RX)

#define APRS_MSG_UTF8_MAX      67U      /* текст повідомлення, байт UTF-8 (APRS101) */
#define APRS_MSG_ADDR_LEN      9U       /* адресат в ефірі, символів */
#define APRS_MSG_CALL_LEN      10U      /* адресат/відправник у рації: 9 + NUL */
#define APRS_MSG_ID_LEN        6U       /* номер: до 5 символів + NUL */
#define APRS_MSG_TEXT_LEN      80U      /* текст у списку (cp1251): вхідний може бути довшим за 67 байт -- обрізається */
#define APRS_MSG_JOB_TEXT_LEN  68U      /* текст у черзі (cp1251, <= 67 символів + NUL) */
#define APRS_MSG_LIST_MAX      8U
#define APRS_MSG_QUEUE_MAX     4U
#define APRS_MSG_ATTEMPTS      3U       /* спроб на наше повідомлення */
#define APRS_MSG_RETRY_MS      30000UL  /* інтервал між спробами (і очікування ACK після останньої) */
#define APRS_MSG_GAP_MS        2000UL   /* пауза між будь-якими двома передачами */
#define APRS_MSG_BUSY_MAX_MS   10000UL  /* скільки чекати вільної частоти, потім передаємо все одно */
#define APRS_MSG_ACK_REPEAT_MS 5000UL   /* той самий (адресат, номер) ACK не частіше, ніж раз на 5 с (дублі через кілька діджі) */

enum { AMSG_DIR_IN = 0, AMSG_DIR_OUT = 1 };

/* Стан запису списку. Для вхідних -- AMSG_ST_NONE. */
enum { AMSG_ST_NONE = 0, AMSG_ST_WAIT, AMSG_ST_SENT, AMSG_ST_ACK, AMSG_ST_NOACK };

/* Помилки постановки в чергу. */
enum { AMSG_OK = 0, AMSG_E_CALL, AMSG_E_TEXT, AMSG_E_FULL };

/* Результат перевірки тексту. */
enum { AMSG_TEXT_OK = 0, AMSG_TEXT_EMPTY, AMSG_TEXT_ILLEGAL };

typedef struct
{
	uint32_t ms;                          /* ticksGetMillis() прийому/створення (вік = now - ms) */
	uint8_t  used;
	uint8_t  dir;                         /* AMSG_DIR_* */
	uint8_t  status;                      /* AMSG_ST_* (лише вихідні) */
	uint8_t  unread;                      /* вхідне, ще не відкрите */
	uint8_t  attempts;                    /* вихідне: скільки разів передано */
	uint8_t  noTime;                      /* вік невідомий (запис зі сховища SMS без годинника) */
	char     call[APRS_MSG_CALL_LEN];     /* від кого / кому */
	char     id[APRS_MSG_ID_LEN];         /* номер повідомлення (порожній -- нема) */
	char     text[APRS_MSG_TEXT_LEN];     /* cp1251 */
} aprsMsgEntry_t;

typedef struct
{
	uint32_t nextMs;                      /* коли можна передавати (повідомлення: наступна спроба/кінець очікування ACK) */
	uint8_t  type;                        /* 0 -- вільний слот, 1 -- повідомлення, 2 -- ACK */
	uint8_t  attempts;
	char     to[APRS_MSG_CALL_LEN];
	char     id[APRS_MSG_ID_LEN];
	char     text[APRS_MSG_JOB_TEXT_LEN]; /* cp1251; для ACK порожній */
} aprsMsgJob_t;

enum { AMSG_JOB_FREE = 0, AMSG_JOB_MSG = 1, AMSG_JOB_ACK = 2 };

typedef struct
{
	aprsMsgEntry_t list[APRS_MSG_LIST_MAX];   /* [0] -- найновіше */
	aprsMsgJob_t   q[APRS_MSG_QUEUE_MAX];
	uint32_t       lastTxMs;                  /* кінець останньої передачі (0 -- ще не було) */
	uint32_t       busySinceMs;               /* коли почали чекати вільну частоту (0 -- не чекаємо) */
	uint32_t       lastAckMs;                 /* коли пішов останній ACK (0 -- не було) */
	int8_t         inflight;                  /* слот черги, що зараз у ефірі (-1 -- нема) */
	uint8_t        txActive;                  /* передача почалась, кінець ще не відмічено */
	uint8_t        lastNum;                   /* останній використаний номер 1..99 (0 -- ще не було) */
	char           lastAckTo[APRS_MSG_CALL_LEN];
	char           lastAckId[APRS_MSG_ID_LEN];
} aprsMsgBox_t;

/* ---- символи й текст ------------------------------------------------------------------------------------ */
/* Скільки байт UTF-8 займе символ cp1251 `c`; 0 -- символ у повідомленні заборонено: керівні (<0x20, 0x7F), ':' (за вимогою
 * брифу), '|' '~' '{' (APRS101: '|' і '~' зарезервовано для TNC, '{' починає номер), а також байти >= 0x80, яких немає в
 * кирилиці/Є І Ї Ґ/№. */
size_t aprsMsgCharBytes(uint8_t c);
/* Байтів UTF-8 у рядку cp1251; заборонений символ рахується як 1 (його замінить '?'). */
size_t aprsMsgUtf8Len(const char *cp1251);
/* Чи влізе символ `c` у рядок `cur` цілим: символ дозволений і utf8len(cur) + bytes(c) <= 67. */
bool aprsMsgCanAppend(const char *cur, uint8_t c);
/* Перевірка тексту: AMSG_TEXT_EMPTY -- порожній або самі пробіли; AMSG_TEXT_ILLEGAL -- є заборонений символ. */
int aprsMsgTextCheck(const char *cp1251);
/* cp1251 -> UTF-8, не більше 67 байт і не більше cap-1; літеру не рве; заборонений символ -> '?'. Повертає довжину; NUL ставить. */
size_t aprsMsgToUtf8(const char *cp1251, char *out, size_t cap);

/* Адресат: A-Z (з малих -> великі), 0-9, один '-'; 1..9 символів; після '-' 1-2 цифри, SSID 1..15 («-0» відкидається).
 * out[10]. Повертає false, якщо не підходить. */
bool aprsMsgNormCall(char out[APRS_MSG_CALL_LEN], const char *in);

/* ---- кадр ----------------------------------------------------------------------------------------------- */
/* Інфо-поле повідомлення. to -- нормалізований адресат; id -- «NN» або порожній (тоді без «{»). Повертає довжину (з NUL у
 * out), 0 -- помилка (адресат, текст порожній/заборонений, мало місця). Хвостові пробіли тексту відкидаються. */
size_t aprsMsgBuildMessage(char *out, size_t cap, const char *to, const char *cp1251Text, const char *id);
/* Інфо-поле ACK. id -- як у повідомленні, якому відповідаємо (непорожній). Повертає довжину, 0 -- помилка. */
size_t aprsMsgBuildAck(char *out, size_t cap, const char *to, const char *id);

/* ---- список і черга ------------------------------------------------------------------------------------- */
/* seed -- початок лічильника номерів (перший номер буде (seed % 99) + 1): щоб новий сеанс не повторював номери
 * попереднього, які одержувач ще пам'ятає. Тест викликає з 0. */
void aprsMsgInit(aprsMsgBox_t *b, uint32_t seed);
/* Поставити наше повідомлення в чергу (і запис «чекає» у список). Адресат -- довільний (нормалізується тут). */
int aprsMsgSend(aprsMsgBox_t *b, const char *to, const char *cp1251Text, uint32_t now);
/* Вхідне повідомлення нам (текст cp1251, id -- номер або порожній). true -- нове (додано у список, непрочитане); false --
 * повтор (той самий відправник і номер) або нема місця. */
bool aprsMsgOnIncoming(aprsMsgBox_t *b, const char *from, const char *cp1251Text, const char *id, uint32_t now);
/* Вхідне повідомлення з номером => відповісти ACK негайно. true -- ACK поставлено в чергу; false -- вже є/щойно був/черга
 * повна/номера нема. Викликати і для ПОВТОРІВ (відправник не почув наш ACK). */
bool aprsMsgQueueAck(aprsMsgBox_t *b, const char *to, const char *id, uint32_t now);
/* Прийшов ":МИ:ackNN" (або "rejNN" -- isRej). Скасовує повтори відповідного нашого повідомлення. true -- знайдено. */
bool aprsMsgOnAckRx(aprsMsgBox_t *b, const char *from, const char *id, bool isRej);

/* Що передати зараз. Повертає довжину інфо-поля в info (з NUL) або 0 -- нічого. txOk -- умови передачі (APRS увімкнено, не
 * приймається пакет, PTT не натиснуто, не DMR-TX) -- їх рахує викликач. busy -- частота зайнята. Усередині: завершення
 * очікування ACK («без ACK»), пауза 2 с між передачами, пріоритет ACK, очікування вільної частоти до 10 с. */
size_t aprsMsgPoll(aprsMsgBox_t *b, uint32_t now, bool busy, bool txOk, char *info, size_t cap);
/* Результат спроби передачі кадру, виданого aprsMsgPoll(). ok -- передачу почато. fatal -- марно повторювати (TX заборонено...):
 * повідомлення одразу «без ACK». */
void aprsMsgTxDone(aprsMsgBox_t *b, uint32_t now, bool ok, bool fatal);
/* Будь-яка передача справді закінчилась (aprsTxProgress == IDLE) -- і повідомлення, і маяк: від цього моменту рахується пауза
 * 2 с. */
void aprsMsgTxEnded(aprsMsgBox_t *b, uint32_t now);
/* Чи минула пауза 2 с після останньої передачі (для маяка «Режиму APRS»). */
bool aprsMsgGapOk(const aprsMsgBox_t *b, uint32_t now);
/* Скасувати все, що ще не пішло (вихід з режиму): повідомлення стають «без ACK», ACK відкидаються. */
void aprsMsgCancelAll(aprsMsgBox_t *b);

/* Запис зі сховища SMS (прапорець APRS): текст «ВІДПРАВНИК: повідомлення» -> відправник (<= 9 символів) і текст. false -- не схоже. */
bool aprsMsgSplitInbox(const char *note, char call[APRS_MSG_CALL_LEN], const char **text);
/* Перенесення за словами для екрана (як smsWrapLine() у sms_format.c, але без залежності від збірки AES/DMR): рядок шириною до w
 * символів з позиції start тексту s (довжина len); пробіли на початку пропускаються; розрив -- на останньому пробілі, що влазить;
 * слово довше за w рубається по w. Повертає довжину рядка без кінцевих пробілів; *lineStart -- перший непробільний символ; *next
 * -- звідки шукати наступний рядок (>= len, якщо текст закінчився). */
int aprsMsgWrapLine(const char *s, int len, int start, int w, int *lineStart, int *next);

unsigned aprsMsgPendingCount(const aprsMsgBox_t *b);   /* наших повідомлень, що чекають передачі/ACK */
unsigned aprsMsgUnreadCount(const aprsMsgBox_t *b);
unsigned aprsMsgListCount(const aprsMsgBox_t *b);
void aprsMsgMarkRead(aprsMsgBox_t *b, unsigned idx);

#endif /* ENABLE_APRS_RX */
#endif /* _OPENGD77_APRS_MSG_H_ */
