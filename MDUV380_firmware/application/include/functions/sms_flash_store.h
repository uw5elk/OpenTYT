/*
 * sms_flash_store.h -- R106-SMSSTORE: сховище SMS DMR (образ s_store з dmr_sms.c) у ВЛАСНИХ вирівняних секторах SPI-флешу,
 * а не в custom-data блоці 7 MESSAGES (там кожна подія переписувала спільний 4-КіБ сектор 2-3 рази разом із сусідніми блоками).
 *
 * Де: сирі адреси SMSF_REGION_ADDR .. + SMSF_SLOTS * 4 КіБ = 0x48000..0x4FFFF -- над сховищем APRS R101 (0x40000..0x47FFF), у вільному
 * проміжку 0x30000..0x4FFFF між custom-data (0x20000..0x2FFFF) і базою позивних №1 (0x50000). Рішення -- claude/r106-smsstore-decisions.md.
 *
 * Слот = заголовок SMSF_HDR_LEN Б + образ з +SMSF_HDR_LEN:
 *   заголовок: [0..3] magic "SMF1" | [4] версія | [5] 0 | [6..7] довжина образу u16 | [8..11] seq u32 | [12..15] CRC32 образу |
 *              [16..19] CRC32 байтів 0..15 | [20..31] 0xFF (не програмуються)
 *   образ:     перші 10 Б dmrSmsStore_t («MSGV», версія 3, rsvd = 0, used, nextSeq) + data[0..used) -- порожній хвіст не пишеться.
 * Порядок запису (як aprs_msg_store): стерти слот, що НЕ є найновішим цілим (спершу порожній/зіпсований, інакше найстаріший) -> образ ->
 * заголовок ОСТАННІМ -> звірка читанням байт-у-байт. Завантаження: найбільший seq (серійна арифметика) серед слотів із цілими заголовком і
 * образом. Обрив живлення в будь-який момент лишає попередній або новий стан цілим; напівзаписаний слот не проходить CRC.
 * Образ пишеться й читається ПРЯМО з/у s_store (CCM, SPI -- опитуванням CPU), буфери -- на стеку (<= 64 + 32 Б). SPI_Flash_sectorbuffer
 * НЕ використовується, нових масивів у RAM/CCM нема.
 *
 * Політика (dmr_sms.c, SMS_STORE_FLASH): нове SMS -- при першій нагоді після вікна квитанції; «прочитано», «усі прочитані», видалення,
 * «доставлено» -- через SMSF_DEFER_S після першої незаписаної зміни; дозапис при штатному вимкненні. Не пишеться під час передачі,
 * квитанції, прийому даних у каналі (тиша SMSF_QUIET_MS) і в режимі CPS. Блок 7 прошивка лише один раз очищує (рішення 2 -- старі SMS
 * не переносяться) і далі не пише.
 *
 * Прапорець збірки ENABLE_SMS_STORE_FLASH (Makefile), діє лише разом з ENABLE_AES і ENABLE_DMR_DATA. Чиста частина збирається на хості з
 * -DSMS_STORE_HOST_TEST (tools/test_r106smsstore.py).
 */
#ifndef FUNCTIONS_SMS_FLASH_STORE_H_
#define FUNCTIONS_SMS_FLASH_STORE_H_

#if defined(ENABLE_SMS_STORE_FLASH) && defined(ENABLE_AES) && defined(ENABLE_DMR_DATA)
#define SMS_STORE_FLASH 1
#endif

#if defined(SMS_STORE_FLASH) || defined(SMS_STORE_HOST_TEST)

#include <stdint.h>
#include <stdbool.h>

#define SMSF_REGION_ADDR    0x48000UL   /* сира адреса SPI-флешу (FLASH_ADDRESS_OFFSET уже враховано), вирівняна на сектор */
#define SMSF_SECTOR         4096UL
#define SMSF_PAGE           256UL
#define SMSF_SLOTS          8U          /* слотів по колу: знос ділиться на 8 */
#define SMSF_HDR_LEN        32U
#define SMSF_HDR_PROG_LEN   20U         /* байти 0..19 програмуються одним викликом, ОСТАННІМИ */
#define SMSF_HDR_CRC_LEN    16U
#define SMSF_MAGIC          0x31464D53UL   /* "SMF1" (LE) */
#define SMSF_VERSION        1U
#define SMSF_CHUNK          64U         /* буфер звірки на стеку */
#define SMSF_IMG_MIN        10U         /* заголовок dmrSmsStore_t без даних */
#define SMSF_IMG_MAX        1352U       /* sizeof(dmrSmsStore_t) -- перевіряється _Static_assert у dmr_sms.c */
#define SMSF_DEFER_S        60U         /* с: відкладений запис («прочитано», видалення, «доставлено») */
#define SMSF_QUIET_MS       2000U       /* мс тиші в каналі (жодного data-burst) перед записом -- квитанція важливіша */

_Static_assert((SMSF_REGION_ADDR % SMSF_SECTOR) == 0UL, "ділянка SMS має бути вирівняна на сектор");
_Static_assert((SMSF_REGION_ADDR >= 0x30000UL) && ((SMSF_REGION_ADDR + (SMSF_SLOTS * SMSF_SECTOR)) <= 0x50000UL),
		"ділянка SMS -- лише у вільному проміжку 0x30000..0x4FFFF (нижче custom-data, з 0x50000 база позивних)");
_Static_assert((SMSF_HDR_LEN + SMSF_IMG_MAX) <= SMSF_SECTOR, "образ має вміститися в один слот");
_Static_assert((SMSF_PAGE % SMSF_CHUNK) == 0UL, "шматок звірки не перетинає межу сторінки");
_Static_assert(SMSF_DEFER_S < 62U, "лічильник відкладення -- 6 біт (s_loaded, біти 2..7)");

#if defined(SMS_STORE_FLASH)
#include "functions/aprs_msg_store.h"
#if defined(AMS_REGION_ADDR)
_Static_assert(((SMSF_REGION_ADDR + (SMSF_SLOTS * SMSF_SECTOR)) <= AMS_REGION_ADDR) ||
		(SMSF_REGION_ADDR >= (AMS_REGION_ADDR + (AMS_SLOTS * AMS_SECTOR))), "ділянка SMS не перетинається зі сховищем APRS (R101)");
#endif
#endif

/* Примітиви SPI_Flash.c (programBytes -- лише з APRS_MSG1_UI або SMS_STORE_FLASH). На хості -- модель NOR у тесті. */
bool SPI_Flash_read(uint32_t addrress, uint8_t *buf, int size);
bool SPI_Flash_eraseSector(uint32_t address);
bool SPI_Flash_programBytes(uint32_t addr, const uint8_t *buf, int len);

/* Чиста частина (без годинника, екрана, радіо). img -- образ (s_store), len -- його довжина (SMSF_IMG_MIN..SMSF_IMG_MAX). */
int  smsfLoadCore(uint8_t *img, uint32_t maxLen);            /* прочитати найновіший цілий слот у img (хвіст до maxLen обнуляється); довжина або -1 */
bool smsfSaveCore(const uint8_t *img, uint32_t len);         /* записати новий слот; true -- записано й звірено */
bool smsfSameCore(const uint8_t *img, uint32_t len);         /* найновіший цілий слот містить рівно цей образ -- писати не треба */

#endif /* SMS_STORE_FLASH || SMS_STORE_HOST_TEST */

#endif /* FUNCTIONS_SMS_FLASH_STORE_H_ */
