/*
 * tone_reply.h -- R99-TONE / R100-TONE: «Тон-відгук» (перевірка покриття й антен). Коли функцію ввімкнено і рація чула сигнал FM, ПІСЛЯ того як шумодав
 * закрився, вона після затримки передає тон заданої частоти й тривалості. Позивного у відповіді нема (рішення власника); межа -- лише тривалість.
 *
 * Лише FM. DMR не реалізовано: безпечного підтвердженого способу передати чутний тон у DMR нема (claude/r99-tone-recon.md).
 * Компілюється лише з -DENABLE_TONE_REPLY в українській збірці UV380 (TONE_REPLY_ENABLED нижче); без прапорця -- байт-у-байт стокова збірка.
 * Чиста частина (стан-машина, розбір/збирання блоку, межі значень) збирається й на хості з -DTONE_REPLY_HOST_TEST (tools/test_r99tone.py,
 * tools/test_r100tone.py). Константи TONE_REPLY_* -- ЄДИНЕ джерело меж і типових значень: CPS (tools/tone_reply_cfg.py) розбирає їх з цього файла.
 *
 * Сховище: custom-data блок CODEPLUG_CUSTOM_DATA_TYPE_TONE_REPLY_CFG (= 19), 8 байт. R100: версія 2:
 *   [0] version (= 2)
 *   [1] тривалість тону, с (TONE_REPLY_DUR_MIN_S..TONE_REPLY_DUR_MAX_S)
 *   [2] затримка перед тоном, с (TONE_REPLY_DELAY_MIN_S..TONE_REPLY_DELAY_MAX_S)
 *   [3] біт 0 -- «увімкнено» (R100: зберігається після вимкнення рації); решта бітів 0
 *   [4..5] частота тону, Гц, uint16 LE (TONE_REPLY_FREQ_MIN..TONE_REPLY_FREQ_MAX, крок TONE_REPLY_FREQ_STEP)
 *   [6..7] резерв (0)
 * Версія 1 (R99-TONE): [1] тривалість ×100 мс, [2] затримка ×100 мс, [3] 0; «увімкнено» не зберігалось. Читається з міграцією: секунди = округлення
 * ВГОРУ в межах нових констант, «увімкнено» = 0; у флеші лишається v1, доки користувач не збереже (тоді v2).
 * Блоку нема / версія невідома -- типові значення (1000 Гц, 10 с, 2 с), вимкнено.
 */
#ifndef FUNCTIONS_TONE_REPLY_H_
#define FUNCTIONS_TONE_REPLY_H_

#if defined(ENABLE_TONE_REPLY) && defined(LANGUAGE_BUILD_UKRAINIAN) && defined(PLATFORM_MDUV380)
#define TONE_REPLY_ENABLED 1
#endif

#if defined(TONE_REPLY_ENABLED) || defined(TONE_REPLY_HOST_TEST)

#include <stdint.h>
#include <stdbool.h>

#define TONE_REPLY_CFG_VERSION   2U
#define TONE_REPLY_CFG_V1        1U
#define TONE_REPLY_CFG_LEN       8

#define TONE_REPLY_FREQ_MIN      300U      /* Гц -- нижня межа тону (смуга голосового тракту FM) */
#define TONE_REPLY_FREQ_MAX      3000U     /* Гц -- верхня */
#define TONE_REPLY_FREQ_STEP     50U
#define TONE_REPLY_FREQ_DEF      1000U
#define TONE_REPLY_DUR_MIN_S     1U        /* с */
#define TONE_REPLY_DUR_MAX_S     60U       /* с: ЖОРСТКА межа тривалості передачі тону (стан-машина обрізає навіть пошкоджене значення) */
#define TONE_REPLY_DUR_DEF_S     10U
#define TONE_REPLY_DELAY_MIN_S   0U
#define TONE_REPLY_DELAY_MAX_S   10U
#define TONE_REPLY_DELAY_DEF_S   2U
#define TONE_REPLY_STEP_S        1U        /* крок тривалості й затримки в меню й CPS */
#define TONE_REPLY_FLAG_ENABLED  0x01U     /* [3] біт 0 */

#define TONE_REPLY_THRESH_MS     1000U     /* відгук лише на сигнал, що тривав не менше 1 с (короткі сплески шумодава й чужі короткі тони -- ні) */
/* Пауза-сторож після відгуку: найбільша затримка + найбільша тривалість + поріг (обчислюється з констант). Відгук ІНШОЇ рації з цією ж функцією (будь-які
 * налаштування в межах) повністю потрапляє в сторож -- обмін двох рацій затухає за один крок; новий прийом -- лише після сторожа і тиші. */
#define TONE_REPLY_GUARD_MS      (((TONE_REPLY_DELAY_MAX_S + TONE_REPLY_DUR_MAX_S) * 1000U) + TONE_REPLY_THRESH_MS)
_Static_assert(TONE_REPLY_GUARD_MS >= (((TONE_REPLY_DELAY_MAX_S + TONE_REPLY_DUR_MAX_S) * 1000U) + TONE_REPLY_THRESH_MS), "сторож має покривати найбільшу затримку, тривалість і поріг");
_Static_assert((TONE_REPLY_DUR_MAX_S <= 255U) && (TONE_REPLY_DELAY_MAX_S <= 255U) && (TONE_REPLY_DUR_MIN_S >= 1U), "секунди -- байт блоку 19");

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
	uint8_t  durS;     /* с */
	uint8_t  delayS;   /* с */
} toneReplyCfg_t;

typedef struct
{
	uint8_t version;
	uint8_t dur;       /* v2: с; v1: ×100 мс */
	uint8_t delay;     /* v2: с; v1: ×100 мс */
	uint8_t flags;     /* v2: біт 0 -- увімкнено */
	uint8_t freqLo;
	uint8_t freqHi;
	uint8_t reserved1[2];
} toneReplyOnFlash_t;

/* Крок стан-машини (чиста функція). enabled -- функцію ввімкнено; rxOpen -- шумодав відкритий (чути сигнал); txAllowed -- передача зараз дозволена
 * (екран, канал FM, без заборон); cancel -- користувач щось натиснув (PTT, клавіша) або змінився канал. Повертає TR_ACT_*. */
int toneReplyStep(toneReplySm_t *s, uint32_t now, bool enabled, bool rxOpen, bool txAllowed, bool cancel, const toneReplyCfg_t *cfg);
/* Межі значень: привести налаштування до дозволених. */
void toneReplyCfgClamp(toneReplyCfg_t *c);
void toneReplyCfgDefaults(toneReplyCfg_t *c);
/* Розібрати блок: повертає версію, з якої прочитано (2, 1 -- з міграцією), або 0 -- невідома/сміття (типові значення, вимкнено). */
int toneReplyCfgParse(const toneReplyOnFlash_t *raw, toneReplyCfg_t *c, bool *enabled);
/* Зібрати блок версії 2. */
void toneReplyCfgBuild(toneReplyOnFlash_t *raw, const toneReplyCfg_t *c, bool enabled);

#if defined(TONE_REPLY_ENABLED)
/* Обгортка на рації (UI-задача). */
void toneReplyLoad(void);                  /* старт: налаштування й «увімкнено» з блоку 19; стан-машина -- ЧЕКАЮ, на старті нічого не передається */
void toneReplyTick(const void *ev);        /* головний цикл (applicationMain), кожен прохід; ev -- uiEvent_t* цього проходу */
void toneReplyAbort(void);                 /* PTT: негайно зупинити тон/затримку (до відкриття екрана передачі) */
bool toneReplyIsEnabled(void);
void toneReplySetEnabled(bool on);
bool toneReplyIsTransmitting(void);
toneReplyCfg_t *toneReplyCfg(void);        /* поточні (редаговані меню) налаштування */
bool toneReplySave(void);                  /* записати блок 19 (v2), якщо змінилось (налаштування або «увімкнено") */
void toneReplyMenuCancel(void);            /* меню: повернути збережене */
#endif

#endif
#endif /* FUNCTIONS_TONE_REPLY_H_ */
