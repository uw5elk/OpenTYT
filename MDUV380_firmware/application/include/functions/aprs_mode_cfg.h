/*
 * aprs_mode_cfg.h -- налаштування «Режиму APRS» (R10): що редагується з рації, як це зберігається і як
 * з типових значень кодплага та оверрайдів складається те, з чим працює режим.
 *
 * ЧИСТИЙ C без заліза (як aprs_rx_parse.c): той самий файл збирає хост-тест tests/test_aprs_mode.c.
 * Усе під ENABLE_APRS_RX -- у типовій збірці порожній translation unit.
 *
 * Звідки налаштування (APRS-unify). Кожне налаштування живе в ОДНОМУ місці й редагується і з рації, і з ПК:
 *   - позивний -- ім'я рації (EEPROM 0x00E0, codeplugSetRadioName());
 *   - станція (SSID, шляхи, символ, коментар, позиція, неточність, частота, 300 бод / QSY / «тихо» / «використовувати позицію») -- слот конфігу APRS
 *     кодплага (EEPROM 0x1588, codeplugAPRSSetDataForIndex()): слот каналу (aprsConfigIndex), інакше №1;
 *   - інтервал і режим бікона, потужність, джерело позиції, затухання, стиснення, розумний маяк, вікно маяка -- блок
 *     CODEPLUG_CUSTOM_DATA_TYPE_APRS_BEACON_CFG (див. нижче) <-> стокові nonVolatileSettings;
 *   - шумодав приймача APRS -- блок режиму (APRSM_BLOCK_LEN байт).
 * Блок режиму (aprsModeCfg_t) лишився «чернеткою»: ov-біти між правкою в меню і записом у слот, шумодав і маркер міграції. Старі блоки з
 * оверрайдами один раз переносяться у слот (aprsModeMigrate()). Тож зміна слота з CPS підхоплюється одразу, а правка з рації видна в CPS.
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
#define APRSM_COMMENT_LEN     25         /* 24 символи cp1251 + NUL (як comment[24] у конфігу кодплага) */
#define APRSM_COMMENT_MAX     24
#define APRSM_COMMENT_AIR_MAX 43         /* рекомендований максимум коментаря позиції в ефірі, байт UTF-8 */
#define APRSM_BLOCK_LEN       72         /* довжина custom-data блоку (незмінна) */
#define APRSM_FREQ_DEFAULT    14480000UL /* 144,800 МГц, одиниці 10 Гц */
#define APRSM_INTERVALS       6          /* 0 / 5 / 10 / 15 / 30 / 60 хв */
#define APRSM_SQL_MAX         21         /* 0 -- типовий; 1..21 -- 0..100 % (як у каналі) */
#define APRSM_QSY_LEN         24         /* R21 З4: «FFF.FFFMHz Cnnn +nnn» (20 символів) + NUL, з запасом */
#define APRSM_ICON_MAX        93         /* iconIndex: символ = '!' + iconIndex (0x21..0x7E) */

/* Які поля задано з рації (інакше -- типове значення з кодплага). */
#define APRSM_OV_FREQ         0x0001U
#define APRSM_OV_LEGACY_CALL  0x0002U    /* BT-unify: лише в старих блоках (позивний тепер один -- ім'я рації, EEPROM 0x00E0); читається для міграції, назад не пишеться */
#define APRSM_OV_SSID         0x0004U
#define APRSM_OV_PATH1        0x0008U
#define APRSM_OV_PATH2        0x0010U
#define APRSM_OV_ICON         0x0020U    /* таблиця й код символу -- разом */
#define APRSM_OV_COMMENT      0x0040U
#define APRSM_OV_LAT          0x0080U
#define APRSM_OV_LON          0x0100U
#define APRSM_OV_AMB          0x0200U
#define APRSM_OV_ALL          0x03FFU
#define APRSM_OV_MIGRATED     0x4000U    /* APRS-unify: міграцію оверрайдів у кодплаг виконано (біт у старих блоках ніколи не стоїть: FromBytes маскував 0x03FF) */

/* Налаштування, що зберігаються (значення полів без біта в ov -- ігноруються). */
typedef struct
{
	uint16_t ov;
	uint32_t freq;
	char     legacyCall[APRSM_CALL_LEN];    /* лише з старого блоку (міграція в ім'я рації); aprsModeCfgToBytes() пише нулі */
	uint8_t  ssid;                          /* 0..15 */
	char     path[2][APRSM_CALL_LEN];
	uint8_t  pathSsid[2];                   /* 0..7 */
	uint8_t  iconTable;                     /* 0 -- '/', 1 -- '\' */
	uint8_t  iconIndex;                     /* 0..APRSM_ICON_MAX */
	char     comment[APRSM_COMMENT_LEN];    /* cp1251 */
	int32_t  latU, lonU;
	uint8_t  ambiguity;                     /* 0..7 (як біти 5-7 flags конфігу: 0 -- точно) */
	uint8_t  interval;                      /* ЛИШЕ для міграції: старий індекс 0 -- вимкнено, 1..5 -- 5/10/15/30/60 хв. Далі інтервал один -- стоковий initialInterval; ToBytes пише 0 */
	uint8_t  sql;                           /* 0..APRSM_SQL_MAX (без оверрайду) */
	uint8_t  qsyOff;                        /* ЛИШЕ для міграції (R21 З4): 1 -- QSY був вимкнений. Далі -- прапорець CODEPLUG_APRS_CONFIG_FLAG_TRANSMIT_QSY_INFO у слоті; ToBytes пише 0 */
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

#define APRSM_RAW_FLAG_300_BAUDS      0x01U   /* == CODEPLUG_APRS_CONFIG_FLAG_* (codeplug.h) */
#define APRSM_RAW_FLAG_USE_POSITION   0x02U
#define APRSM_RAW_FLAG_QSY            0x04U
#define APRSM_RAW_FLAG_SILENT         0x08U
#define APRSM_RAW_FLAG_MASK           0x0FU
#define APRSM_RAW_FLAG_AMB_MASK       0xE0U

/* Типові значення (кодплаг, а де його нема -- запасні). */
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
	uint8_t  flags;                         /* APRSM_RAW_FLAG_300_BAUDS | _QSY | _SILENT (| _USE_POSITION) зі слота; без слота -- 0 */
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
	uint8_t  flags;                         /* як у aprsModeDefaults_t */
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
/* raw/rawValid -- конфіг APRS з кодплага (rawValid == false -- нема); radioName -- ім'я рації (кодплаг),
 * settingsPos* -- позиція з налаштувань рації (хоч не задана -- false). */
void aprsModeDefaultsBuild(aprsModeDefaults_t *d, const aprsModeRawCfg_t *raw, bool rawValid,
		const char *radioName, bool settingsPosValid, int32_t settingsLatU, int32_t settingsLonU);
void aprsModeEffective(const aprsModeCfg_t *c, const aprsModeDefaults_t *d, aprsModeEff_t *e);
/* Складання структури, з якою працює маяк прошивки (aprsSendPacket()): шлях, SSID, символ, неточність.
 * Частота QSY = 0 (режим уже стоїть на частоті), позиція йде окремо (не USE_POSITION). Коментар тут НЕ
 * кладеться (у ефір він іде UTF-8, довший за comment[24]) -- див. aprsModeCommentToUtf8(). */
void aprsModeToBeaconCfg(const aprsModeEff_t *e, aprsModeRawCfg_t *out);

/* R21 З4: QSY у коментарі маяка -- той самий формат, що додає стокова передача (aprs.c, aprsSendPacket) і що розбирає commentStrip() (R14):
 * «FFF.FFFMHz Xnnn ±nnn» -- частота прийому каналу (кГц), тон, зсув TX-RX у десятках кГц. toneKind: 'C' -- CTCSS (toneVal = тон у Гц без десяткових, пишеться як «T082» -- основна форма APRS Frequency Spec; стокова TYT шле «C082», обидві форми допустимі),
 * 'D' -- DCS (toneVal -- код, шістнадцяткові цифри), інакше «Toff». wide=false -- літери малі (вузька смуга: «t082», «toff»; за специфікацією мала перша літера = NARROW).
 * Зсув понад 9,9 МГц -- «+000». rxFreq/txFreq -- в одиницях 10 Гц, як у каналі. out має вміщати APRSM_QSY_LEN; порожній рядок (повертає 0) --
 * частоти нема або поза 1..999,999 МГц. */
#if defined(APRS_R21_QSY)
size_t aprsModeQsyFormat(char *out, size_t cap, uint32_t rxFreq, uint32_t txFreq, char toneKind, unsigned toneVal, bool wide);
/* Коментар для ефіру: «QSY␠текст». cp1251 -> UTF-8 (aprsModeCommentToUtf8), QSY (якщо не порожній) стоїть ПЕРШИМ і не обрізається -- коли разом не влазять
 * у cap-1 байт, обрізається текст користувача (не посеред символу). Порожній текст -- без кінцевого пробілу. Повертає довжину результату. */
size_t aprsModeCommentWithQsy(const char *cp1251, const char *qsy, char *out, size_t cap);
#endif

/* ---- APRS-unify (L5.3): блок налаштувань стокового бікона (CODEPLUG_CUSTOM_DATA_TYPE_APRS_BEACON_CFG) -- ОСНОВНЕ сховище -----------------------------------------
 * Розкладка (16 Б): 0 'A', 1 'B', 2 версія (1), 3 режим бікона (0 вимкн., 1 вручну, 2 PTT, 3 авто, 4 розумний), 4 потужність (0 -- канал; 1..), 5 стоковий initialInterval
 * (0..9 -> 12 с, 30 с, 1, 2, 3, 5, 10, 20, 30, 60 хв), 6 біти стану (0 -- позиція каналу, 1 -- GPS, 2 -- затухання, 3 -- стиснення; рівно один з бітів 0/1),
 * 7 slowRate (хв), 8 fastRate (с), 9 lowSpeed, 10 highSpeed (км/год), 11 turnAngle (°), 12 turnSlope, 13 turnTime (с), 14 вікно маяка (0 всі, 1 лише нові, 2 вимкн.),
 * 15 контрольна сума (байти 0..14, зерно 0x5A). */
#define APRSB_BLOCK_LEN  16
typedef struct
{
	uint8_t mode, power, initialInterval, stateBits;
	uint8_t slowRate, fastRate, lowSpeed, highSpeed, turnAngle, turnSlope, turnTime;
	uint8_t bcnWin;
} aprsBeaconCfg_t;
void aprsBeaconCfgToBytes(const aprsBeaconCfg_t *c, uint8_t out[APRSB_BLOCK_LEN]);
/* false -- довжина/магія/версія/сума чи поля поза допустимим -- блок ігнорується (межі розумного маяка клампить прошивка при застосуванні). */
bool aprsBeaconCfgFromBytes(aprsBeaconCfg_t *c, const uint8_t *b, size_t len);

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
/* R14: назва за символом пакета: table '/' -- первинна, інакше (у т.ч. накладка) -- додаткова; NULL -- нема в таблиці */
const char *aprsSymbolNameEx(char table, char code);
/* R17: вибір символу в налаштуваннях. Перелік -- усі названі: спершу первинна таблиця, потім додаткова. Символ без назви (решта з 188)
 * вибирають «вручну»: таблиця + код. Це чиста логіка стану вибору (без екрана) -- її перевіряє хост-тест; екран -- menuAprsMode.c. */
typedef struct
{
	uint8_t manual;   /* 0 -- перелік назв, 1 -- вручну (таблиця + код) */
	uint8_t table;    /* 0 -- '/', 1 -- '\\' (вручну) */
	uint8_t index;    /* код - '!' (вручну) */
	uint8_t pos;      /* номер у переліку (перелік) */
} aprsSymPick_t;
unsigned aprsSymbolListCount(void);
bool aprsSymbolListGet(unsigned i, uint8_t *table, uint8_t *index, const char **name);
int  aprsSymbolListFind(uint8_t table, uint8_t index);          /* -1 -- такого символу в переліку нема */
void aprsSymPickInit(aprsSymPick_t *p, uint8_t table, uint8_t index);   /* названий -- перелік на ньому; без назви -- вручну */
void aprsSymPickStep(aprsSymPick_t *p, int dir);                /* ручка / ←→: перелік -- ±1 по колу; вручну -- код ±1 по колу (0..APRSM_ICON_MAX) */
void aprsSymPickTable(aprsSymPick_t *p);                        /* вручну: інша таблиця */
void aprsSymPickToggle(aprsSymPick_t *p);                       /* перелік <-> вручну (символ переноситься) */
void aprsSymPickResult(const aprsSymPick_t *p, uint8_t *table, uint8_t *index);
/* Наступний символ із названих (для швидкого перебору); починає з наступного після (table,index). */
void aprsModeSymbolNextNamed(uint8_t *table, uint8_t *index);
/* 24-бітна позиція кодплага (знак -- біт 23; ціла частина -- біти 22..15; частка -- молодші 15 біт у
 * одиницях 1E-4 градуса) -> мікроградуси. Та сама формула, що latLonFixed24ToDouble() (uiUtilities.c). */
int32_t aprsModeFixed24ToMicro(const uint8_t b[3]);
/* Старий (до unify) інтервал режиму: індекс 0..5 -> хвилини (0 -- вимкнено). Лише для міграції. */
uint8_t  aprsModeIntervalMinutes(uint8_t idx);

/* ---- APRS-unify: одне джерело істини для кожного налаштування ------------------------------------------------------------------------------
 * Станція (SSID, шляхи, символ, коментар, позиція, неточність, частота, прапорці 300 бод / QSY / «тихо» / «використовувати позицію») живе в слоті конфігу APRS
 * кодплага (EEPROM 0x1588, 64 Б); позивний -- в імені рації (EEPROM 0x00E0, 8 Б); інтервал -- стоковий initialInterval. Блок режиму (aprsModeCfg_t) лишився
 * ЛИШЕ як «чернетка» (ov-біти між правкою в меню і записом у слот), шумодав приймача й маркер міграції. Старі блоки (з оверрайдами, інтервалом, qsyOff,
 * позивним) один раз переносяться у слот / ім'я / initialInterval функцією aprsModeMigrate(). */
#define APRSM_NAME_RAW_LEN  8
typedef struct
{
	aprsModeRawCfg_t raw;                       /* слот: той, що призначено каналу (або №1) */
	bool             rawValid;                  /* слот існує в кодплазі; false -- raw лише заготовка (aprsModeStoreBlank()), у кодплаг ще не записана */
	uint8_t          name[APRSM_NAME_RAW_LEN];  /* ім'я рації як у кодплазі: 0xFF-дописка */
} aprsModeStore_t;

#define APRSM_FOLD_RAW    0x01U    /* слот змінено (треба записати) */
#define APRSM_FOLD_NAME   0x02U    /* ім'я рації змінено */
#define APRSM_FOLD_INIT   0x04U    /* змінено стоковий initialInterval (міграція) */
#define APRSM_FOLD_BLOCK  0x08U    /* змінено блок режиму (міграція: маркер) */

void aprsModeStoreBlank(aprsModeStore_t *s);                                     /* заготовка слота; name не чіпає */
bool aprsModeStoreSetCall(aprsModeStore_t *s, const char *call, bool *valid);   /* позивний -> name; true -- ім'я змінилося; *valid -- позивний пройшов перевірку */
void aprsModeStoreSetFlag(aprsModeStore_t *s, uint8_t mask, bool on);           /* APRSM_RAW_FLAG_* */
void aprsModeMicroToFixed24(int32_t u, uint8_t b[3]);                           /* обернене до aprsModeFixed24ToMicro(); крок 1E-4 градуса */
/* Скласти «чернетку» (ov-біти) у слот і зняти складені біти. d -- поточні типові (потрібні, коли задано лише широту АБО лише довготу). Повертає APRSM_FOLD_RAW,
 * якщо слот змінився. Лише широта/довгота без пари лишаються в ov, доки не буде другої. */
unsigned aprsModeFold(aprsModeCfg_t *c, aprsModeStore_t *s, const aprsModeDefaults_t *d);
/* Найближчий до старого інтервалу (хвилини за aprsModeIntervalMinutes()) індекс у таблиці стокових інтервалів secs[n] (секунди); порівну -- довший. */
uint8_t aprsModeNearestInitial(uint8_t oldIdx, const uint16_t *secs, unsigned n);
/* Одноразова міграція старого блоку: позивний -> ім'я; ov -> слот; interval != 0 -> *initialInterval (найближче значення); qsyOff -> знімає прапорець QSY
 * у слоті; ставить APRSM_OV_MIGRATED. 0 -- уже мігровано. Біти APRSM_FOLD_* -- що саме змінилося. */
unsigned aprsModeMigrate(aprsModeCfg_t *c, aprsModeStore_t *s, const aprsModeDefaults_t *d,
		uint8_t *initialInterval, const uint16_t *secs, unsigned n);

#endif /* ENABLE_APRS_RX */
#endif /* _OPENGD77_APRS_MODE_CFG_H_ */
