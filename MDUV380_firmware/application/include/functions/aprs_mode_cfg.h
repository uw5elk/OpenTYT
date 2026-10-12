/*
 * aprs_mode_cfg.h -- налаштування «Режиму APRS» (R10): що редагується з рації, як це зберігається і як
 * з типових значень кодплуга та оверрайдів складається те, з чим працює режим.
 *
 * ЧИСТИЙ C без заліза (як aprs_rx_parse.c): той самий файл збирає хост-тест tests/test_aprs_mode.c.
 * Усе під ENABLE_APRS_RX -- у типовій збірці порожній translation unit.
 *
 * Звідки налаштування. У кодплузі є конфіг APRS (CodeplugAPRSConfig_t), але ФУНКЦІЇ ЗАПИСУ його в кодплуг
 * у прошивці НЕМАЄ (лише codeplugAPRSGetDataForIndex()), і вигадувати запис не можна. Тому все, що
 * користувач міняє з рації, лежить у НОВОМУ малому custom-data блоці (CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG,
 * APRSM_BLOCK_LEN байт) як ОВЕРРАЙДИ поверх конфігу кодплуга: біт у ov означає «це поле задано з рації»,
 * інакше береться типове значення з кодплуга (або запасне). Тож зміна конфігу в CPS підхоплюється
 * автоматично для всіх полів, яких користувач не чіпав; «Скинути» знімає біти.
 *
 * Одиниці. Частота -- як rxFreq каналу: 10 Гц (144,800 МГц = 14480000). Позиція -- мікроградуси int32
 * (як у R8). Позивний/шлях -- ASCII верхнім регістром, до 6 символів. Коментар -- cp1251 (шрифт рації),
 * в ефір іде UTF-8 (aprsModeCommentToUtf8()).
 */
#ifndef _OPENGD77_APRS_MODE_CFG_H_
#define _OPENGD77_APRS_MODE_CFG_H_

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "functions/aprs_rx_cfg.h"

#if defined(ENABLE_APRS_RX)

#define APRSM_CALL_LEN        7          /* 6 символів + NUL */
#define APRSM_COMMENT_LEN     25         /* 24 символи cp1251 + NUL (як comment[24] у конфігу кодплуга) */
#define APRSM_COMMENT_MAX     24
#define APRSM_COMMENT_AIR_MAX 43         /* рекомендований максимум коментаря позиції в ефірі, байт UTF-8 */
#define APRSM_BLOCK_LEN       72         /* довжина custom-data блоку (незмінна) */
#define APRSM_FREQ_DEFAULT    14480000UL /* 144,800 МГц, одиниці 10 Гц */
#define APRSM_INTERVALS       6          /* 0 / 5 / 10 / 15 / 30 / 60 хв */
#define APRSM_SQL_MAX         21         /* 0 -- типовий; 1..21 -- 0..100 % (як у каналі) */
#define APRSM_ICON_MAX        93         /* iconIndex: символ = '!' + iconIndex (0x21..0x7E) */

/* Які поля задано з рації (інакше -- типове значення з кодплуга). */
#define APRSM_OV_FREQ         0x0001U
#define APRSM_OV_CALL         0x0002U
#define APRSM_OV_SSID         0x0004U
#define APRSM_OV_PATH1        0x0008U
#define APRSM_OV_PATH2        0x0010U
#define APRSM_OV_ICON         0x0020U    /* таблиця й код символу -- разом */
#define APRSM_OV_COMMENT      0x0040U
#define APRSM_OV_LAT          0x0080U
#define APRSM_OV_LON          0x0100U
#define APRSM_OV_AMB          0x0200U
#define APRSM_OV_ALL          0x03FFU

/* Налаштування, що зберігаються (значення полів без біта в ov -- ігноруються). */
typedef struct
{
	uint16_t ov;
	uint32_t freq;
	char     call[APRSM_CALL_LEN];
	uint8_t  ssid;                          /* 0..15 */
	char     path[2][APRSM_CALL_LEN];
	uint8_t  pathSsid[2];                   /* 0..7 */
	uint8_t  iconTable;                     /* 0 -- '/', 1 -- '\' */
	uint8_t  iconIndex;                     /* 0..APRSM_ICON_MAX */
	char     comment[APRSM_COMMENT_LEN];    /* cp1251 */
	int32_t  latU, lonU;
	uint8_t  ambiguity;                     /* 0..7 (як біти 5-7 flags конфігу: 0 -- точно) */
	uint8_t  interval;                      /* індекс: 0 -- вимкнено, 1..5 -- 5/10/15/30/60 хв (без оверрайду) */
	uint8_t  sql;                           /* 0..APRSM_SQL_MAX (без оверрайду) */
} aprsModeCfg_t;

/* Дзеркало CodeplugAPRSConfig_t (functions/codeplug.h) -- рівно ті самі байти (64). Прошивка перевіряє
 * _Static_assert-ом, що розміри збігаються; хост-тест будує його напряму. */
typedef struct __attribute__((packed))
{
	char     name[8];
	uint8_t  senderSSID;
	uint8_t  latitude[3];
	uint8_t  longitude[3];
	struct __attribute__((packed)) { char name[6]; uint8_t ssid; } paths[2];
	uint8_t  iconTable;
	uint8_t  iconIndex;
	char     comment[24];
	uint32_t txFrequency;
	uint8_t  reserved[2];
	uint8_t  flags;
	uint16_t magicVer;
} aprsModeRawCfg_t;

#define APRSM_RAW_FLAG_USE_POSITION   0x02U
#define APRSM_RAW_FLAG_AMB_MASK       0xE0U

/* Типові значення (кодплуг, а де його нема -- запасні). */
typedef struct
{
	bool     hasCfg;                        /* конфіг APRS є */
	uint32_t freq;                          /* txFrequency конфігу; 0 -- нема */
	char     call[APRSM_CALL_LEN];          /* позивний рації (ім'я), до 6 символів */
	uint8_t  ssid;
	char     path[2][APRSM_CALL_LEN];
	uint8_t  pathSsid[2];
	uint8_t  iconTable, iconIndex;
	char     comment[APRSM_COMMENT_LEN];
	bool     hasPos;
	int32_t  latU, lonU;
	uint8_t  ambiguity;
} aprsModeDefaults_t;

/* Ефективні значення: типові + оверрайди. З цим працюють екран, приймач і маяк. */
typedef struct
{
	uint32_t freq;
	char     call[APRSM_CALL_LEN];
	uint8_t  ssid;
	char     path[2][APRSM_CALL_LEN];
	uint8_t  pathSsid[2];
	uint8_t  iconTable, iconIndex;
	char     comment[APRSM_COMMENT_LEN];
	bool     hasPos;
	int32_t  latU, lonU;
	uint8_t  ambiguity;
	uint8_t  interval;
	uint8_t  sql;
} aprsModeEff_t;

/* ---- збереження ----------------------------------------------------------------------------------- */
void aprsModeCfgInit(aprsModeCfg_t *c);                                 /* без оверрайдів, інтервал 0, шумодав типовий */
void aprsModeCfgToBytes(const aprsModeCfg_t *c, uint8_t out[APRSM_BLOCK_LEN]);
/* false -- довжина/магія/версія/контрольна сума не ті: тоді *c = aprsModeCfgInit(), блок ігнорується.
 * Поля, що не пройшли перевірку (позивний з недопустимими символами, частота поза діапазоном...), --
 * просто знімаються з ov. */
bool aprsModeCfgFromBytes(aprsModeCfg_t *c, const uint8_t *b, size_t len);

/* ---- типові значення й ефективні -------------------------------------------------------------------- */
/* raw/rawValid -- конфіг APRS з кодплуга (rawValid == false -- нема); radioName -- ім'я рації (кодплуг),
 * settingsPos* -- позиція з налаштувань рації (хоч не задана -- false). */
void aprsModeDefaultsBuild(aprsModeDefaults_t *d, const aprsModeRawCfg_t *raw, bool rawValid,
		const char *radioName, bool settingsPosValid, int32_t settingsLatU, int32_t settingsLonU);
void aprsModeEffective(const aprsModeCfg_t *c, const aprsModeDefaults_t *d, aprsModeEff_t *e);
/* Складання структури, з якою працює маяк прошивки (aprsSendPacket()): шлях, SSID, символ, неточність.
 * Частота QSY = 0 (режим уже стоїть на частоті), позиція йде окремо (не USE_POSITION). Коментар тут НЕ
 * кладеться (у ефір він іде UTF-8, довший за comment[24]) -- див. aprsModeCommentToUtf8(). */
void aprsModeToBeaconCfg(const aprsModeEff_t *e, aprsModeRawCfg_t *out);

/* ---- перевірки й текст ------------------------------------------------------------------------------ */
bool aprsModeFreqValid(uint32_t f);                 /* 135..174 МГц або 400..480 МГц (в одиницях 10 Гц) */
bool aprsModeCallValid(const char *s);              /* 1..6 символів A-Z 0-9 */
bool aprsModePathValid(const char *s);              /* порожній (шляху нема) або як позивний */
/* Приведення до верхнього регістру і обрізання; повертає довжину. */
size_t aprsModeNormCall(char *dst, size_t dstSize, const char *src);
bool aprsModeParseFreq(const char *s, uint32_t *f10Hz);    /* «144.825» (МГц) */
void aprsModeFormatFreq(char *b, size_t n, uint32_t f10Hz); /* «144.8250»: мін. 3 знаки після крапки */
bool aprsModeParseCoord(const char *s, bool isLat, int32_t *u); /* «-50.4501»; діапазон лат ±90, лон ±180 */
void aprsModeFormatCoord(char *b, size_t n, int32_t u);     /* «50.450100» -> «50.4501» (до 6 знаків без хвостових нулів, мін. 4) */
/* Коментар cp1251 -> UTF-8 для ефіру; результат не довший за cap-1 байт і не більше
 * APRSM_COMMENT_AIR_MAX, не рветься посеред символу. Повертає довжину. */
size_t aprsModeCommentToUtf8(const char *cp1251, char *out, size_t cap);
/* R11: cp1251 -> Unicode (кирилиця, Є/І/Ї/Ґ, №; усе інше з байтів >= 0x80 -- '?'). Лише для c >= 0x80: ASCII викликач обробляє сам. */
uint16_t aprsModeCp1251ToUcs2(uint8_t c);
/* Коротка назва найуживаніших символів первинної таблиці (cp1251); NULL -- назви нема. */
const char *aprsModeSymbolName(uint8_t table, uint8_t index);
/* Наступний символ із названих (для швидкого перебору); починає з наступного після (table,index). */
void aprsModeSymbolNextNamed(uint8_t *table, uint8_t *index);
/* 24-бітна позиція кодплуга (знак -- біт 23; ціла частина -- біти 22..15; частка -- молодші 15 біт у
 * одиницях 1E-4 градуса) -> мікроградуси. Та сама формула, що latLonFixed24ToDouble() (uiUtilities.c). */
int32_t aprsModeFixed24ToMicro(const uint8_t b[3]);
/* Інтервал маяка, мс (0 -- вимкнено). */
uint32_t aprsModeIntervalMs(uint8_t idx);
uint8_t  aprsModeIntervalMinutes(uint8_t idx);

#endif /* ENABLE_APRS_RX */
#endif /* _OPENGD77_APRS_MODE_CFG_H_ */
