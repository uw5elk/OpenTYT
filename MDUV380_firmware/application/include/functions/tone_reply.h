/*
 * tone_reply.h -- R99-TONE: «Тон-відгук» (перевірка покриття й антен). Коли функцію ввімкнено і рація чула сигнал FM, ПІСЛЯ того як шумодав
 * закрився, вона після затримки передає тон заданої частоти й тривалості. Позивного у відповіді нема (рішення власника); межа -- лише тривалість.
 *
 * Лише FM. DMR не реалізовано: безпечного підтвердженого способу передати чутний тон у DMR нема (claude/r99-tone-recon.md).
 * Компілюється лише з -DENABLE_TONE_REPLY в українській збірці UV380 (TONE_REPLY_ENABLED нижче); без прапорця -- байт-у-байт стокова збірка.
 * Чиста частина (стан-машина, розбір/збирання блоку, межі значень) збирається й на хості з -DTONE_REPLY_HOST_TEST (tools/test_r99tone.py).
 *
 * Сховище: custom-data блок CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG (= 19), 8 байт:
 *   [0] version (= 1)
 *   [1] тривалість тону, ×100 мс (1..50)
 *   [2] затримка перед тоном, ×100 мс (0..50)
 *   [3] резерв (0)
 *   [4..5] частота тону, Гц, uint16 LE (300..3000, крок 50)
 *   [6..7] резерв (0)
 * «Увімкнено» НЕ зберігається: після перезапуску рації функція вимкнена (безпека). Блоку нема / версія невідома -- типові значення.
 */
#ifndef FUNCTIONS_TONE_REPLY_H_
#define FUNCTIONS_TONE_REPLY_H_

#if defined(ENABLE_TONE_REPLY) && defined(LANGUAGE_BUILD_UKRAINIAN) && defined(PLATFORM_MDUV380)
#define TONE_REPLY_ENABLED 1
#endif

#if defined(TONE_REPLY_ENABLED) || defined(TONE_REPLY_HOST_TEST)

#include <stdint.h>
#include <stdbool.h>

#define TR_CFG_VERSION      1U
#define TR_CFG_LEN          8

#define TR_FREQ_MIN         300U      /* Гц -- нижня межа тону (смуга голосового тракту FM) */
#define TR_FREQ_MAX         3000U     /* Гц -- верхня */
#define TR_FREQ_STEP        50U
#define TR_FREQ_DEF         1000U
#define TR_DUR_MIN          1U        /* ×100 мс */
#define TR_DUR_MAX          50U       /* ×100 мс = 5 с: ЖОРСТКА межа тривалості передачі тону */
#define TR_DUR_DEF          10U       /* 1,0 с */
#define TR_DELAY_MAX        50U       /* ×100 мс = 5 с */
#define TR_DELAY_DEF        5U        /* 0,5 с */

#define TR_THRESH_MS        1000U     /* відгук лише на сигнал, що тривав не менше 1 с (короткі сплески шумодава й чужі короткі тони -- ні) */
/* Пауза-сторож після відгуку: найбільша затримка + найбільша тривалість + поріг. Відгук ІНШОЇ рації з цією ж функцією (будь-які налаштування в
 * межах) повністю потрапляє в сторож -- обмін двох рацій затухає за один крок; новий прийом -- лише після сторожа і тиші. */
#define TR_GUARD_MS         ((TR_DELAY_MAX * 100U) + (TR_DUR_MAX * 100U) + TR_THRESH_MS)

/* Стани машини */
enum { TR_ST_IDLE = 0, TR_ST_RX, TR_ST_DELAY, TR_ST_TX, TR_ST_GUARD };
/* Дії, які має виконати обгортка */
enum { TR_ACT_NONE = 0, TR_ACT_START, TR_ACT_STOP };

typedef struct
{
	uint32_t t;        /* ticksGetMillis() початку поточного стану */
	uint8_t  state;    /* TR_ST_* */
} toneReplySm_t;

typedef struct
{
	uint16_t freqHz;
	uint8_t  durDs;    /* ×100 мс */
	uint8_t  delayDs;  /* ×100 мс */
} toneReplyCfg_t;

typedef struct
{
	uint8_t version;
	uint8_t durDs;
	uint8_t delayDs;
	uint8_t reserved0;
	uint8_t freqLo;
	uint8_t freqHi;
	uint8_t reserved1[2];
} toneReplyOnFlash_t;

/* Крок стан-машини (чиста функція). enabled -- функцію ввімкнено; rxOpen -- шумодав відкритий (чути сигнал); txAllowed -- передача зараз дозволена
 * (екран, канал FM, без заборон); cancel -- користувач щось натиснув (PTT, клавіша) або змінився канал. Повертає TR_ACT_*. */
int toneReplyStep(toneReplySm_t *s, uint32_t now, bool enabled, bool rxOpen, bool txAllowed, bool cancel, const toneReplyCfg_t *cfg);
/* Межі значень: привести налаштування до дозволених (частота -- до кроку 50 Гц у 300..3000, тривалість 1..50, затримка 0..50). */
void toneReplyCfgClamp(toneReplyCfg_t *c);
void toneReplyCfgDefaults(toneReplyCfg_t *c);
/* Розібрати блок (false -- версія невідома: типові значення) / зібрати для запису. */
bool toneReplyCfgParse(const toneReplyOnFlash_t *raw, toneReplyCfg_t *c);
void toneReplyCfgBuild(toneReplyOnFlash_t *raw, const toneReplyCfg_t *c);

#if defined(TONE_REPLY_ENABLED)
/* Обгортка на рації (UI-задача). */
void toneReplyLoad(void);                  /* старт: налаштування з блоку 19, «увімкнено» = ні */
void toneReplyTick(const void *ev);        /* головний цикл (applicationMain), кожен прохід; ev -- uiEvent_t* цього проходу */
void toneReplyAbort(void);                 /* PTT: негайно зупинити тон/затримку (до відкриття екрана передачі) */
bool toneReplyIsEnabled(void);
void toneReplySetEnabled(bool on);
bool toneReplyIsTransmitting(void);
toneReplyCfg_t *toneReplyCfg(void);        /* поточні (редаговані меню) налаштування */
bool toneReplySave(void);                  /* записати блок 19, якщо змінилось */
void toneReplyMenuBegin(void);             /* меню: запам'ятати стан для «скасувати» */
void toneReplyMenuCancel(void);            /* меню: повернути запам'ятоване */
#endif

#endif
#endif /* FUNCTIONS_TONE_REPLY_H_ */
