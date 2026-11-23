/*
 * aprs_msg_store.h -- R101-APRSMSG: список «Повідом. APRS» (8 записів, обидва напрямки) зберігається після вимкнення рації.
 *
 * Де: ВЛАСНА ділянка SPI-флешу поза областю custom-data (там запис стирає весь 4-КіБ сектор разом із сусідніми блоками). Сирі адреси
 * AMS_REGION_ADDR .. + AMS_SLOTS * 4 КіБ = 0x40000..0x47FFF -- середина вільного проміжку 0x30000..0x4FFFF між custom-data (0x20000..0x2FFFF)
 * і базою позивних №1 (0x50000). Жоден інший код прошивки і наш CPS туди не пишуть (claude/r101-aprsmsg-recon.md).
 *
 * Слоти: AMS_SLOTS секторів по 4 КіБ, по колу. Слот = заголовок AMS_HDR_LEN Б + дані з +AMS_HDR_LEN.
 *   заголовок: [0..3] magic "AMS1" | [4] версія | [5] записів | [6] lastNum (номер {NN}) | [7] 0 | [8..11] seq u32 | [12..13] довжина даних u16 |
 *              [14..15] 0 | [16..19] CRC32 даних | [20..23] CRC32 змісту (дані без часу -- для «чи змінилось») | [24..27] CRC32 байтів 0..23 | [28..31] 0xFF
 *   запис:     [0..3] час u32 (UTC с; 0 -- невідомо) | [4] біти: 0 напрям, 1..3 стан, 4 непрочитане | [5] спроби |
 *              довжина + позивний (<= 9) | довжина + номер (<= 5) | довжина + текст (<= 79, cp1251). Найгірше 102 Б, 8 записів -- 816 Б.
 * Порядок запису: стерти слот, що НЕ є найновішим цілим (спершу порожній/зіпсований, інакше найстаріший) -> дані -> заголовок ОСТАННІМ -> звірка
 * читанням. Завантаження: найбільший seq (серійна арифметика, переповнення u32 безпечне) серед слотів з цілими заголовком, даними й розбором.
 * Обрив живлення в будь-який момент лишає попередній або новий стан цілим; напівзаписаний слот не проходить CRC.
 *
 * Політика: раз на секунду CRC змісту списку порівнюється з найновішим слотом; якщо відрізняється AMS_DEFER_S секунд поспіль -- запис (не частіше
 * ніж раз на AMS_DEFER_S); при штатному вимкненні ручкою -- дозапис. Не пишеться, поки йде передача або відкрито режим CPS.
 * Пам'ять: стан -- 2 Б у вирівнюванні aprsMsgBox_t (storeSec/storeAge), буфери -- на стеку (<= 96 Б). SPI_Flash_sectorbuffer НЕ використовується.
 *
 * Лише під APRS_MSG1_UI (користувацька збірка); чиста частина збирається на хості з -DAPRS_MSG_STORE_HOST_TEST (tools/test_r101aprsmsg.py).
 */
#ifndef FUNCTIONS_APRS_MSG_STORE_H_
#define FUNCTIONS_APRS_MSG_STORE_H_

#include "functions/aprs_rx_cfg.h"

#if defined(APRS_MSG1_UI) || defined(APRS_MSG_STORE_HOST_TEST)

#include <stdint.h>
#include <stdbool.h>
#include "functions/aprs_msg.h"

#define AMS_REGION_ADDR     0x40000UL   /* сира адреса SPI-флешу (з FLASH_ADDRESS_OFFSET уже), вирівняна на сектор */
#define AMS_SECTOR          4096UL
#define AMS_PAGE            256UL
#define AMS_SLOTS           8U          /* слотів по колу: знос ділиться на 8 */
#define AMS_DEFER_S         60U         /* с: зміст відрізняється від флешу стільки секунд поспіль -> запис */
#define AMS_HDR_LEN         32U
#define AMS_MAGIC           0x31534D41UL   /* "AMS1" (LE) */
#define AMS_VERSION         1U
#define AMS_CHUNK           64U         /* буфер потокового запису/читання на стеку */
#define AMS_CALL_MAX        (APRS_MSG_CALL_LEN - 1U)
#define AMS_ID_MAX          (APRS_MSG_ID_LEN - 1U)
#define AMS_TEXT_MAX        (APRS_MSG_TEXT_LEN - 1U)
#define AMS_ENTRY_MAX       (4U + 1U + 1U + 1U + AMS_CALL_MAX + 1U + AMS_ID_MAX + 1U + AMS_TEXT_MAX)
#define AMS_PAYLOAD_MAX     (APRS_MSG_LIST_MAX * AMS_ENTRY_MAX)
#define AMS_NOTIME_ABS      2U          /* aprsMsgEntry_t.noTime: годинник невідомий, у ms -- абсолютний час UTC с (з флешу) */

_Static_assert((AMS_REGION_ADDR % AMS_SECTOR) == 0UL, "ділянка має бути вирівняна на сектор");
_Static_assert((AMS_REGION_ADDR >= 0x30000UL) && ((AMS_REGION_ADDR + (AMS_SLOTS * AMS_SECTOR)) <= 0x50000UL),
		"ділянка -- лише у вільному проміжку між custom-data (до 0x30000) і базою позивних (з 0x50000)");
_Static_assert((AMS_HDR_LEN + AMS_PAYLOAD_MAX) <= AMS_SECTOR, "образ має вміститися в один слот");
_Static_assert((AMS_PAGE % AMS_CHUNK) == 0UL, "шматок не перетинає межу сторінки");
_Static_assert(AMS_DEFER_S < 255U, "лічильник секунд -- байт");

/* Низький рівень (SPI_Flash.c у прошивці; модель NOR у хост-тесті). programBytes -- команда програмування сторінки на len байт без
 * read-modify-write (len не виходить за межу сторінки). */
bool SPI_Flash_read(uint32_t addrress, uint8_t *buf, int size);
bool SPI_Flash_eraseSector(uint32_t address);
bool SPI_Flash_programBytes(uint32_t addr, const uint8_t *buf, int len);

/* Чиста частина: now -- ticksGetMillis(), clk -- годинник UTC с (0/малий -- не виставлено). */
int  aprsMsgStoreLoadCore(aprsMsgBox_t *b, uint32_t now, uint32_t clk);    /* номер завантаженого слота або -1 (список порожній) */
bool aprsMsgStoreSaveCore(aprsMsgBox_t *b, uint32_t now, uint32_t clk);    /* записати новий слот; true -- записано й звірено */
bool aprsMsgStoreDirtyCore(const aprsMsgBox_t *b, uint32_t now, uint32_t clk);   /* зміст відрізняється від найновішого слота */
/* Раз на секунду (за now): переведення noTime=2 у вік, коли годинник з'явився; порівняння й відкладений запис. Повертає true, якщо записано. */
bool aprsMsgStoreTickCore(aprsMsgBox_t *b, uint32_t now, uint32_t clk, bool writeAllowed);
bool aprsMsgStoreFlushCore(aprsMsgBox_t *b, uint32_t now, uint32_t clk);   /* при вимкненні: записати, якщо відрізняється */

#if defined(APRS_MSG1_UI) && !defined(APRS_MSG_STORE_HOST_TEST)
void aprsMsgStoreLoad(void);    /* старт: ПІСЛЯ aprsMsgBgInit() і menuSystemInit() (годинник уже прочитано) */
void aprsMsgStoreTick(void);    /* головний цикл (UI-задача) */
void aprsMsgStoreFlush(void);   /* штатне вимкнення */
#endif

#endif
#endif /* FUNCTIONS_APRS_MSG_STORE_H_ */
