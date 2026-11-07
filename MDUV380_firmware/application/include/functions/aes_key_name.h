/*
 * aes_key_name.h -- R64C: ім'я слота AES-ключа. Таблиця ключів -- СТОКОВА (TYT): запис 100 Б = [тип:4][ім'я UTF-16LE:32][загорнутий ключ:32][pad:32],
 * ім'я -- до 16 символів UTF-16LE, решта нулі (див. dmr_aes_hook.c, STOCK_KEY_NAME_OFF). Прошивка показує/редагує ім'я в cp1251 (шрифт екрана, редактор назв);
 * тут -- ЧИСТІ перетворення cp1251 <-> UTF-16LE без залежностей (тестуються на хості: tests/test_aes_key_name.c, усі 256 байтів і усі 65536 кодових одиниць проти Python cp1251).
 * Те, чого нема в cp1251 (китайське ім'я зі стокової CPS тощо), показується як «?»; байт 0x98 (його нема в cp1251) теж «?».
 * Ім'я за замовчуванням -- десяткове число keyId ("1".."15"); таке ім'я рахується «імені нема» (рядок меню лишається «Key N»).
 * Формат читає й пише також CPS (tools/stock_key_table.py: decode_name/encode_name) -- змінюючи тут, змінюй там.
 */
#ifndef FUNCTIONS_AES_KEY_NAME_H_
#define FUNCTIONS_AES_KEY_NAME_H_

#include <stdint.h>
#include <stdbool.h>
#include "user_interface/uiNameEditor.h"

/* R64C: імена ключів -- лише там, де їх хтось показує/редагує: ENABLE_AES + ENABLE_AES_KEY_NAMES + спільний редактор (українська збірка з multitap). Інакше файли порожні
 * і збірки ENABLE_AES=* без прапорця -- байт-у-байт як були. Хост-тест (tests/test_aes_key_name.c) вмикає код прапорцем AES_KEY_NAME_HOST_TEST. */
#if (defined(ENABLE_AES) && defined(ENABLE_AES_KEY_NAMES) && defined(UI_NAME_EDITOR)) || defined(AES_KEY_NAME_HOST_TEST)
#define AES_KEY_NAMES_ENABLED 1

#define AESN_CHARS        16U
#define AESN_FIELD_LEN    32U     /* AESN_CHARS x 2 байти UTF-16LE */

/* Байт cp1251 -> кодова одиниця Unicode. 0x98 (нема в cp1251) і байти < 0x20 -> '?' (0x003F). */
uint16_t aesNameCp1251ToUnicode(uint8_t b);
/* Кодова одиниця Unicode -> байт cp1251; чого нема в cp1251 (і сурогати, і керівні) -> '?'. U+0000 -> 0. */
uint8_t  aesNameUnicodeToCp1251(uint16_t u);

/* Поле імені слота (32 Б, UTF-16LE) -> out (cp1251, AESN_CHARS + 1 Б, завершений нулем). Кінець -- U+0000 або U+FFFF (стерта флеш). Повертає довжину. */
unsigned aesNameFromField(const uint8_t *field32, char *out);
/* cp1251 -> поле імені (32 Б): до 16 символів, кінець на байті < 0x20, кінцеві пробіли відкидаються, решта поля -- нулі. Повертає довжину. */
unsigned aesNameToField(const char *cp1251, uint8_t *field32);
/* Поле = ім'я за замовчуванням слота keyId (десяткове число) АБО порожнє (стерте/нульове)? Тоді власного імені нема. */
bool     aesNameIsDefault(uint8_t keyId, const uint8_t *field32);

#if !defined(AES_KEY_NAME_HOST_TEST)
/* Ім'я слота keyId (1..15) зі стокової таблиці ключів -> out (cp1251, AESN_CHARS + 1 Б). Повертає 1, якщо там ВЛАСНЕ ім'я; 0 -- імені нема (стандартне «1».."15»,
 * порожнє, слот не ініціалізований, keyId поза 1..15): out = "". Лише читає флеш, нічого не тримає в пам'яті. UI/основний цикл. */
int dmrAesKeyNameGet(uint8_t keyId, char *out);
/* Записати ім'я слота (cp1251; порожнє = повернути стандартне «keyId»). Пише ЛИШЕ 32 байти поля імені (зсув 4 запису слота), ключ і тип не чіпає; слот, якого ще нема
 * в таблиці (тип не AES-256), спершу ініціалізується як порожній стоковий слот. Перевіряє перечитуванням. 1 -- збережено. UI/основний цикл (SPI_Flash_write чекає osDelay). */
int dmrAesKeyNameSet(uint8_t keyId, const char *cp1251);
#endif

#endif /* AES_KEY_NAMES_ENABLED */

#endif /* FUNCTIONS_AES_KEY_NAME_H_ */
