/*
 * roam_cfg.h -- R59: налаштування «Роумінгу» (автоперехід на наступний канал зі списку, коли ретранслятор
 * не відповідає на пробудження під утримуваним PTT). Малий custom-data блок у кодплазі.
 *
 * Компілюється лише з -DENABLE_ROAM_RETRY. Без нього файл порожній, а всі виклики загорнуті в той самий #if --
 * типова збірка байт-у-байт та сама.
 *
 * Блок: тип CODEPLUG_CUSTOM_DATA_TYPE_ROAM_CFG (= 15), 8 байт: magic "ROAM", version, enabled (0/1),
 * maxHops (1..5), резерв. Якщо блоку немає (нова/нечіпана рація) -- функція ВИМКНЕНА, макс. стрибків 2.
 * Пишеться лише при зміні користувачем (пропуск запису, якщо на флеші вже те саме).
 *
 * Формат читає й пише також CPS (tools/roam_cfg.py) -- змінюючи тут, змінюй там.
 */
#ifndef FUNCTIONS_ROAM_CFG_H_
#define FUNCTIONS_ROAM_CFG_H_

#include <stdint.h>
#include <stdbool.h>

#if defined(ENABLE_ROAM_RETRY)

#define ROAM_HOPS_MIN      1U
#define ROAM_HOPS_MAX      5U
#define ROAM_HOPS_DEFAULT  2U

#define ROAM_CFG_MAGIC     "ROAM"
#define ROAM_CFG_VERSION   1U

/* Розкладка блоку на флеші (8 байт). */
typedef struct
{
	char    magic[4];    /* "ROAM" */
	uint8_t version;     /* 1 */
	uint8_t enabled;     /* 0/1 */
	uint8_t maxHops;     /* 1..5 */
	uint8_t reserved;    /* 0 */
} roamOnFlashCfg_t;

/*
 * R60: НОМЕР СПИСКУ роумінгу каналу (0 = канал у жодному списку, 1..10). Зберігається в запису каналу кодплагу, у байті 37
 * (CodeplugChannel_t._UNUSED_1 -- прошивка його більше ніде не читає й не пише; наш CPS теж не чіпав), З МІТКОЮ, за зразком мітки
 * слота AES (0xA0): байт = 0xC0 | N, N = 1..10 (тобто 0xC1..0xCA). Будь-що інше (0x00, 0xFF, випадкове значення від стороннього
 * CPS, 0xCB..0xCF) = «списку нема». Так сміття у вільному байті не стає списком само собою.
 * Старий прапорець R59 (CHANNEL_FLAG_ROAMING, біт 0x01 LibreDMR_flag1) прошивка більше НЕ читає; кожен запис списку прошивкою
 * знімає його, щоб одноразове перетворення в CPS не оживило вже скасований список. Формат читає й пише також CPS
 * (tools/roam_cfg.py: LIST_BYTE_OFFSET, LIST_TAG) -- змінюючи тут, змінюй там.
 */
#define ROAM_LISTS_COUNT       10U
#define ROAM_LIST_BYTE_OFFSET  37U      /* зсув у 56-байтовому записі каналу */
#define ROAM_LIST_TAG          0xC0U
#define ROAM_LIST_TAG_MASK     0xF0U
#define ROAM_LIST_VALUE_MASK   0x0FU

/* Байт запису -> номер списку 0..10 (нерозпізнане -> 0). */
uint8_t roamListFromByte(uint8_t b);
/* Номер списку -> байт запису: 0 (і число поза 1..10) -> 0x00; N -> 0xC0 | N. */
uint8_t roamListToByte(uint8_t list);

/* Обмежити число стрибків діапазоном 1..5; 0 і нісенітниця -> типове значення. */
uint8_t roamCfgClampHops(uint8_t hops);

/* Розібрати блок із флеша: true -- блок чинний і виходи enabled та maxHops заповнені (maxHops уже обмежений). */
bool roamCfgParse(const roamOnFlashCfg_t *raw, bool *enabled, uint8_t *maxHops);

/* Зібрати блок для запису. */
void roamCfgBuild(roamOnFlashCfg_t *raw, bool enabled, uint8_t maxHops);

/*
 * R64: ІМЕНА списків роумінгу. Окремий custom-data блок CODEPLUG_CUSTOM_DATA_TYPE_ROAM_NAMES (= 16), 160 Б = 10 імен x 16 Б (ім'я списку N --
 * зсув (N-1)*16). Ім'я -- байти cp1251 (як назви каналів/зон), ДО 16 символів, решта слота -- 0x00. Порожнє ім'я (перший байт 0x00, або лише пробіли) =
 * «імені нема»: скрізь показується «Список N». Байт < 0x20 у слоті вважається кінцем імені. Блок пишеться лише при першому перейменуванні
 * (до того його нема -- імена порожні). Формат читає й пише також CPS (tools/roam_cfg.py: NAMES_*) -- змінюючи тут, змінюй там.
 */
#define ROAM_NAME_LEN          16U
#define ROAM_NAMES_BLOCK_LEN   (ROAM_LISTS_COUNT * ROAM_NAME_LEN)

/* Слот імені списку list (1..10) із блоку block (ROAM_NAMES_BLOCK_LEN байт) -> out (ROAM_NAME_LEN + 1 байт, завершений нулем). Повертає довжину;
 * список поза 1..10 або порожнє ім'я -> 0 і out = "". */
unsigned roamNameDecode(const uint8_t *block, uint8_t list, char *out);
/* Записати name (cp1251, до 16 символів; обрізається на першому байті < 0x20; кінцеві пробіли відкидаються) у слот list блоку block, решту слота -- 0x00.
 * Повертає довжину збереженого імені (0 -- ім'я порожнє, слот обнулено); список поза 1..10 -> 0 і блок не змінено. */
unsigned roamNameEncode(uint8_t *block, uint8_t list, const char *name);

#if !defined(ROAM_CFG_HOST_TEST)
/* Ім'я списку з кодплагу (читається блок, береться один слот). true -- блок є (ім'я може бути порожнім, тоді out = ""); false -- блоку нема або він
 * чужої довжини: out = "". out -- ROAM_NAME_LEN + 1 байт. Не тримає ніякої статичної пам'яті: буфер блоку (160 Б) -- на стеку. */
bool roamNameGet(uint8_t list, char *out);
/* Записати ім'я списку: читає блок (нема -- нульовий), міняє один слот, пише назад і ПЕРЕВІРЯЄ перечитуванням. Не пише, якщо там уже саме це.
 * true -- збережено (або вже було таке). Те, що блок існує з іншою довжиною (чужий запис), -- false (змінювати довжину блоку не можна). */
bool roamNameSet(uint8_t list, const char *name);
void    roamCfgLoad(void);                         /* на старті (applicationMain.c); блоку немає -- вимкнено, 2 */
bool    roamCfgIsEnabled(void);
uint8_t roamCfgMaxHops(void);
bool    roamCfgSave(bool enabled, uint8_t maxHops); /* true -- збережено (або вже було таке); живий стан міняється лише при успіху */
#endif

#endif /* ENABLE_ROAM_RETRY */

#endif /* FUNCTIONS_ROAM_CFG_H_ */
