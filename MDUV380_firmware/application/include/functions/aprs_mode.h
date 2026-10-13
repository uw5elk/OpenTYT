/*
 * aprs_mode.h -- «Режим APRS» (R10): окремий режим рації, у якому вона стоїть на частоті APRS і працює ТІЛЬКИ з APRS,
 * як окрема APRS-станція: слухає без пропусків (R8-приймач, але частота -- власна, а не частота каналу), показує
 * монітор / список станцій / налаштування, передає маяк (вручну, PTT, періодично). Вихід повертає канал і все
 * інше.
 *
 * Як це влаштовано (докладно -- docs/aprs-rx-feasibility.md, розділ 13):
 *  - Вхід -- пункт «Режим APRS» у «Опціях рації» (як і екран «APRS станції», R8: режим усередині меню, без власного
 *    ID меню -- він коштував би main RAM). Рація «паркується», як екран супутників: currentChannelData тимчасово
 *    вказує на власний «канал» режиму (аналоговий FM, 12,5 кГц, без CSS, частота APRS), а збережений канал/VFO не
 *    чіпається. Вихід (RED з монітора, вихід з меню будь-яким шляхом) повертає вказівник і перезавантажує канал тим
 *    самим шляхом, що й вихід з екрана супутників.
 *  - Стан режиму -- у позиченому буфері "Переслухати" (callReplayBorrow(), 13,5 КБ CCM): у режимі APRS DMR-голос не
 *    приймається, а вільного CCM у збірці лишається ~300 Б. Без "Переслухати" (діагностична збірка) -- у статичній
 *    структурі в CCM. Прапорець «режим активний» -- не в цьому буфері, а в aprsRxUi()->modeOn (CCM приймача, у
 *    байтах вирівнювання), бо його читають і тоді, коли режим не активний.
 *  - Налаштування -- оверрайди поверх конфігу APRS кодплуга в новому custom-data блоці (aprs_mode_cfg.h).
 *  - Приймач -- той самий R8 (aprs_rx.c): у режимі він завжди «хоче слухати» й бере частоту з «каналу» режиму.
 *  - PTT у режимі передає маяк, а не голос (applicationMain.c викликає aprsModeOnPtt() і гасить кнопку).
 */
#ifndef _OPENGD77_APRS_MODE_H_
#define _OPENGD77_APRS_MODE_H_

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "functions/aprs_rx_cfg.h"

#if defined(APRS_RX)

#include "functions/aprs_mode_cfg.h"
#include "functions/aprs_rx_parse.h"
#include "functions/sms_multitap.h"
#include "functions/aprs_msg.h"

/* Сторінки режиму. R11: «Повідомлення» -- між «Станціями» і «Налаштуваннями». */
/* R17 Г1: «Монітор» і «Станції» прибрано з режиму (залишились числові значення: aprsModeEnter() ставить MONITOR у свій mem()->ui, яким екрани більше не користуються). */
enum { APRS_MODE_PAGE_MONITOR = 0, APRS_MODE_PAGE_STATIONS, APRS_MODE_PAGE_MESSAGES, APRS_MODE_PAGE_SETTINGS, APRS_MODE_PAGES };

/* R11: вигляди сторінки «Повідомлення». R15: HOME -- перший екран (Нове / Вхідні / Надіслані); LIST показує лише один напрямок. */
enum { APRS_MSG_VIEW_LIST = 0, APRS_MSG_VIEW_READ, APRS_MSG_VIEW_CALL, APRS_MSG_VIEW_TEXT, APRS_MSG_VIEW_HOME, APRS_MSG_VIEW_CONFIRM };

/* R11: стан екрана «Повідомлення» (лежить у aprsModeUi_t, тобто в позиченому буфері режиму). */
typedef struct
{
	uint8_t  view;                            /* APRS_MSG_VIEW_* */
	uint8_t  sel;                             /* вибраний запис списку: R15 -- номер у ВІДФІЛЬТРОВАНОМУ списку (див. dirFilter) */
	uint8_t  scroll;                          /* R15: вибраний пункт першого екрана (HOME): 0 Нове, 1 Вхідні, 2 Надіслані, 3 (R18) Видалити всі */
	uint8_t  readTop;                         /* перший видимий рядок тексту в читанні */
	uint8_t  mtMode;                          /* режим набору (sms_multitap) */
	uint8_t  err;                             /* набір: останнє GREEN не прийняло значення. R18: у CONFIRM -- 1 видалити ВСІ, 0 -- один запис */
	uint8_t  reply;                           /* набір: відповідь (адресат заданий, одразу текст). R18: у CONFIRM -- вигляд, куди повернутись по RED */
	uint8_t  layout;                          /* набір: показано шпаргалку розкладки (D) */
	uint8_t  swallowUp;                       /* клавіша, що закрила шпаргалку: її відпускання набір не обробляє */
	uint8_t  dirFilter;                       /* R15: AMSG_DIR_IN / AMSG_DIR_OUT -- який список показано (стає у вільний байт вирівнювання перед pos) */
	int16_t  pos;                             /* довжина підтвердженого тексту в набраному рядку */
	smsMt_t  mt;                              /* символ, що гортається */
	uint32_t keyMs;                           /* ticksGetMillis() останнього натискання тексту */
	char     call[APRS_MSG_CALL_LEN + 2];     /* адресат (набір) */
	char     text[APRS_MSG_JOB_TEXT_LEN + 2]; /* текст (набір), cp1251 */
} aprsMsgUi_t;

/* Поля сторінки «Налаштування» (порядок рядків). R17: «Табл.сим.» і «Код сим.» -> один пункт «Символ» (APRSM_F_SYMBOL). */
enum
{
	APRSM_F_FREQ = 0, APRSM_F_CALL, APRSM_F_SSID, APRSM_F_PATH1, APRSM_F_PATH2, APRSM_F_SYMBOL,
	APRSM_F_COMMENT, APRSM_F_LAT, APRSM_F_LON, APRSM_F_AMB, APRSM_F_INTERVAL, APRSM_F_SQL, APRSM_F_RESET, APRSM_F_COUNT
};

/* Редактор поля (текст / число) -- стан екрана, лежить у стані режиму. */
typedef struct
{
	uint8_t  active;          /* редактор відкрито */
	uint8_t  field;           /* APRSM_F_* */
	uint8_t  mtMode;          /* режим набору (sms_multitap) */
	uint8_t  err;             /* останнє GREEN не прийняло значення */
	int16_t  pos;             /* довжина підтвердженого тексту в buf */
	uint8_t  cap;             /* максимальна довжина */
	smsMt_t  mt;              /* символ, що гортається */
	uint32_t keyMs;           /* ticksGetMillis() останнього натискання тексту */
	char     buf[APRSM_COMMENT_LEN + 2];
} aprsModeEdit_t;

/* Чому маяк не пішов / результат останньої спроби (для екрана). */
typedef enum
{
	APRS_MODE_BCN_NONE = 0,
	APRS_MODE_BCN_SENT,
	APRS_MODE_BCN_BUSY_CH,    /* частота зайнята, чекаємо */
	APRS_MODE_BCN_NOCALL,
	APRS_MODE_BCN_NOPOS,
	APRS_MODE_BCN_INHIBIT,
	APRS_MODE_BCN_BAND,
	APRS_MODE_BCN_FAILED,
	APRS_MODE_BCN_TOOBIG      /* R10-fix2: кадр завеликий */
} aprsModeBcnState_t;

typedef struct
{
	uint8_t  page;
	uint8_t  sel;             /* рядок налаштувань */
	uint8_t  scroll;
	uint8_t  resetArmed;      /* «Скинути»: перше GREEN натиснуто, чекаємо друге */
	uint32_t lastDrawMs;
	aprsModeEdit_t edit;
	aprsMsgUi_t    msg;               /* R11 */
} aprsModeUi_t;

/* ---- життєвий цикл --------------------------------------------------------------------------------- */
bool aprsModeIsActive(void);                 /* безпечно викликати завжди */
bool aprsModeEnter(void);                    /* false -- зараз не можна (екран зайнятий, TX тощо) */
void aprsModeExit(void);                     /* ідемпотентно; повертає канал, режим, еко, I2S */
void aprsModeTick(void);                     /* з головного циклу (applicationMain.c) після aprsRxTick() */
void aprsModeOnPtt(void);                    /* PTT у режимі: замовити маяк (голос заблоковано) */

/* ---- для екрана ------------------------------------------------------------------------------------- */
aprsModeUi_t        *aprsModeUi(void);
/* R13 (П.5): екран «Повідом. APRS» без входу в «Режим APRS». Стан екрана (aprsModeUi_t) лежить у резерві постійного блока повідомлень
 * (callReplay.h: CALL_REPLAY_APRS_UI_BYTES), кільце «Переслухати» не позичається. Поки сесія відкрита, aprsModeUi() повертає цей стан.
 * Open -- обнуляє екран і ставить сторінку «Повідомлення»; Close -- ідемпотентно. Сесія й «Режим APRS» одночасно не живуть. */
/* R16: історія прийому APRS (aprsHist_t: журнал 8 останніх кадрів + дані маяка кожної станції). Живе в резерві постійного блока повідомлень
 * (callReplay.h: CALL_REPLAY_APRS_HIST_BYTES) і не залежить від того, чи відкрито «Режим APRS». Пише aprs_rx.c, читають екрани «Пакети»/маяк. */
aprsHist_t *aprsModeHist(void);
/* R17 Г1: сесії екранів меню «APRS» (стан екрана -- завжди в блоці сесії; режим «Слухати APRS» від них не залежить):
 *  - MsgSessionOpen -- «Повідом. APRS» (msgOn == 1);
 *  - SettingsSessionOpen -- «Налаштування» (msgOn == 2): вимикає «Слухати», позичає кільце під cfg/def/eff, читає налаштування з флешу; радіо не чіпає. false -- не можна (передача).
 *  Close закриває будь-яку (для налаштувань: записує, якщо змінено, і віддає кільце), ідемпотентно. */
bool aprsModeMsgSessionOpen(void);
bool aprsModeSettingsSessionOpen(void);
bool aprsModeCfgSessionActive(void);
void aprsModeCfgSessionTick(void);               /* запис у флеш після паузи в редагуванні */
/* R17 Г1: «Передати маяк» (див. aprs_mode.c). Poll -- кожен тік меню. */
bool aprsModeBeaconOnce(void);
bool aprsModeBeaconOnceBusy(void);
void aprsModeBeaconOncePoll(void);
void aprsModeMsgSessionClose(void);
bool aprsModeMsgSessionActive(void);
aprsModeCfg_t       *aprsModeCfg(void);
const aprsModeEff_t *aprsModeEff(void);
const aprsModeDefaults_t *aprsModeDefaults(void);
void aprsModeCfgChanged(uint16_t whatChanged);   /* оверрайди/налаштування змінено: перерахувати, підлаштувати радіо, відкласти запис */
void aprsModeCfgReset(void);                     /* зняти всі оверрайди, інтервал 0, шумодав типовий */
void aprsModeRequestBeacon(void);                /* ручний маяк (GREEN на «Моніторі») */
uint32_t aprsModeBeaconCount(void);
uint32_t aprsModeLastBeaconAgeSec(void);         /* 0xFFFFFFFF -- ще не було */
uint32_t aprsModeNextBeaconSec(void);            /* 0xFFFFFFFF -- періодичного нема */
aprsModeBcnState_t aprsModeBeaconState(void);
bool aprsModeIsTransmitting(void);

/* ---- R11 / R11-fix2: повідомлення APRS ------------------------------------------------------------------- */
/* ПОСТІЙНИЙ блок: список і фонова черга передачі (повідомлення + ACK). Живе й поза «Режимом APRS» (див. aprs_msg.h). */
aprsMsgBox_t *aprsModeMsgBox(void);
/* Старт прошивки (applicationMain.c), після callReplayBorrowReset(): CCM там сміття. */
void aprsMsgBgInit(void);
/* Фонова черга передачі: з головного циклу (applicationMain.c) ПЕРЕД aprsBeaconingTick(). Працює на будь-якому екрані. */
void aprsMsgBgTick(void);
/* Поставити наше повідомлення в чергу. Повертає AMSG_OK, AMSG_E_CALL / AMSG_E_TEXT / AMSG_E_FULL або -1, якщо режим не активний
 * чи нема власного допустимого позивного; -2 -- поза режимом і APRS вимкнено/призупинено (не передасться). R13 (П.6): позивний-SSID відправника
 * береться ЗАРАЗ (режим: його; поза режимом: стоковий) і фіксується в завданні. Саму передачу робить aprsMsgBgTick() -- навіть
 * після виходу з режиму. */
int aprsModeMsgSend(const char *to, const char *cp1251Text);
bool aprsModeHasCall(void);                      /* власний позивний режиму дійсний (без нього передавати нічого) */

/* ---- для приймача (aprs_rx.c) ---------------------------------------------------------------------------- */
/* Повідомлення/ACK, адресовані нам, ДО відсіву дублікатів (незалежно від того, відкрито «Режим APRS»): ACK на наше -- скасувати
 * повтори; повідомлення з номером -- поставити ACK негайно (на КОЖНУ копію, бо відправник повторює, доки не почує ACK).
 * Викликати лише для pkt->type == APRS_T_MESSAGE нам. */
void aprsMsgBgOnMessage(const aprsAx25_t *ax, const aprsPacket_t *pkt);
/* Нове (недублікат) повідомлення нам -- у список «Повідом. APRS». true -- додано (нове, не повтор). Сховище SMS НЕ чіпає. */
bool aprsMsgBgNewMessage(const aprsAx25_t *ax, const aprsPacket_t *pkt);
/* Власний позивний/SSID/позиція режиму (замість конфігу каналу). false -- режим не активний. */
bool aprsModeOwnInfo(char call[8], uint8_t *ssid, bool *hasPos, int32_t *latU, int32_t *lonU);

#endif /* APRS_RX */
#endif /* _OPENGD77_APRS_MODE_H_ */
