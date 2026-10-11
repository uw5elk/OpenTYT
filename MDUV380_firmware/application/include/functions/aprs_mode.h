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

/* Сторінки режиму. PAGE_MESSAGES -- місце для R11 (не реалізовано): порядок сторінок поки без нього. */
enum { APRS_MODE_PAGE_MONITOR = 0, APRS_MODE_PAGE_STATIONS, APRS_MODE_PAGE_SETTINGS, APRS_MODE_PAGES };

/* Поля сторінки «Налаштування» (порядок рядків). */
enum
{
	APRSM_F_FREQ = 0, APRSM_F_CALL, APRSM_F_SSID, APRSM_F_PATH1, APRSM_F_PATH2, APRSM_F_ICON_TABLE, APRSM_F_ICON_CODE,
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

/* Інфо про останній прийнятий пакет (для «Монітора»). */
typedef struct
{
	bool     valid;
	uint8_t  type;
	bool     hasGeo;
	uint32_t distM;
	uint16_t bearing;
	uint32_t ms;              /* ticksGetMillis() прийому */
	char     src[APRS_CALL_LEN];
	char     dst[APRS_CALL_LEN];
} aprsModeLast_t;

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
} aprsModeUi_t;

/* ---- життєвий цикл --------------------------------------------------------------------------------- */
bool aprsModeIsActive(void);                 /* безпечно викликати завжди */
bool aprsModeEnter(void);                    /* false -- зараз не можна (екран зайнятий, TX тощо) */
void aprsModeExit(void);                     /* ідемпотентно; повертає канал, режим, еко, I2S */
void aprsModeTick(void);                     /* з головного циклу (applicationMain.c) після aprsRxTick() */
void aprsModeOnPtt(void);                    /* PTT у режимі: замовити маяк (голос заблоковано) */

/* ---- для екрана ------------------------------------------------------------------------------------- */
aprsModeUi_t        *aprsModeUi(void);
aprsModeCfg_t       *aprsModeCfg(void);
const aprsModeEff_t *aprsModeEff(void);
const aprsModeDefaults_t *aprsModeDefaults(void);
void aprsModeCfgChanged(uint16_t whatChanged);   /* оверрайди/налаштування змінено: перерахувати, підлаштувати радіо, відкласти запис */
void aprsModeCfgReset(void);                     /* зняти всі оверрайди, інтервал 0, шумодав типовий */
void aprsModeRequestBeacon(void);                /* ручний маяк (GREEN на «Моніторі») */
const aprsModeLast_t *aprsModeLast(void);
uint32_t aprsModeBeaconCount(void);
uint32_t aprsModeLastBeaconAgeSec(void);         /* 0xFFFFFFFF -- ще не було */
uint32_t aprsModeNextBeaconSec(void);            /* 0xFFFFFFFF -- періодичного нема */
aprsModeBcnState_t aprsModeBeaconState(void);
bool aprsModeIsTransmitting(void);

/* ---- для приймача (aprs_rx.c) ---------------------------------------------------------------------------- */
/* Власний позивний/SSID/позиція режиму (замість конфігу каналу). false -- режим не активний. */
bool aprsModeOwnInfo(char call[8], uint8_t *ssid, bool *hasPos, int32_t *latU, int32_t *lonU);
/* Кожен розібраний недублікат (CRC ок) -- для «останнього пакета» на «Моніторі». */
void aprsModeOnFrame(const aprsAx25_t *ax, const aprsPacket_t *pkt, bool hasGeo, uint32_t distM, uint16_t bearing);

#endif /* APRS_RX */
#endif /* _OPENGD77_APRS_MODE_H_ */
