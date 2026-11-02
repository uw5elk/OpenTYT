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

/* Обмежити число стрибків діапазоном 1..5; 0 і нісенітниця -> типове значення. */
uint8_t roamCfgClampHops(uint8_t hops);

/* Розібрати блок із флеша: true -- блок чинний і виходи enabled та maxHops заповнені (maxHops уже обмежений). */
bool roamCfgParse(const roamOnFlashCfg_t *raw, bool *enabled, uint8_t *maxHops);

/* Зібрати блок для запису. */
void roamCfgBuild(roamOnFlashCfg_t *raw, bool enabled, uint8_t maxHops);

#if !defined(ROAM_CFG_HOST_TEST)
void    roamCfgLoad(void);                         /* на старті (applicationMain.c); блоку немає -- вимкнено, 2 */
bool    roamCfgIsEnabled(void);
uint8_t roamCfgMaxHops(void);
bool    roamCfgSave(bool enabled, uint8_t maxHops); /* true -- збережено (або вже було таке); живий стан міняється лише при успіху */
#endif

#endif /* ENABLE_ROAM_RETRY */

#endif /* FUNCTIONS_ROAM_CFG_H_ */
