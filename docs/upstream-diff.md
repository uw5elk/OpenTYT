# Відмінності форку від OpenGD77 R20260131

**Складено:** 2026-09-28  
**Бaза (upstream):** коміт `ccd25f0` — "OpenGD77 R20260131 source + UV390 10W Makefile and CI"  
**HEAD форку:** `de9bc32`  
**Підсумок:** 178 файлів змінено, +39 075 / −327 рядків

---

## 1. Нові файли форку

### 1.1. AES-шифрування (`crypto/`)
| Файл | Рядків | Призначення |
|------|--------|-------------|
| `application/include/crypto/dmr_aes.h` | 138 | API AES-256: init, encrypt/decrypt 9-байтного фрейму, зберігання 8 ключів у CCM |
| `application/include/crypto/dmr_aes_hook.h` | 81 | Hook для HR-C6000 RX/TX ISR: перехоплення payload перед декодером |
| `application/source/crypto/dmr_aes.c` | 549 | AES-256-CBC, tiny-AES-128 адаптований під 256-бітний ключ; буфери у `.ccmram` |
| `application/source/crypto/dmr_aes_hook.c` | 843 | RX-перехоплення (decrypt), TX-перехоплення (encrypt), діагностика |

### 1.2. RCTL — дистанційне керування (`crypto/`, `functions/`)
| Файл | Рядків | Призначення |
|------|--------|-------------|
| `application/include/crypto/dmr_rctl_pdu.h` | 110 | PDU-формат команди (ARM+payload, anti-replay кеш у RAM) |
| `application/include/crypto/dmr_rctl_frame.h` | 46 | Упаковка/розпаковка EMB short-LC + rate-3/4 frame |
| `application/include/crypto/dmr_rctl_stock.h` | 134 | Зворотна сумісність зі стоковими TYT-командами (opcode таблиця) |
| `application/include/functions/dmr_rctl_cap.h` | 47 | capability-фрейм (DMR BS CAP) для узгодження шифрування |
| `application/include/functions/dmr_rctl_cfg.h` | 112 | Конфіг (enabled/маска команд) у flash-блоці "RCTL"; `dmrRctlIsInhibited()` |
| `application/include/functions/dmr_rctl_tx.h` | 106 | TX-сторона: побудова команд, queue, діагностичні лічильники |
| `application/source/crypto/dmr_rctl_frame.c` | 132 | Реалізація пакування/розпаковки фреймів |
| `application/source/crypto/dmr_rctl_pdu.c` | 81 | PDU: серіалізація, CRC, anti-replay |
| `application/source/crypto/dmr_rctl_stock.c` | 250 | Стокові команди: декодування, маппінг |
| `application/source/functions/dmr_rctl_cap.c` | 107 | Відповідь на BS CAP request |
| `application/source/functions/dmr_rctl_cfg.c` | 410 | Читання/запис flash-блоку RCTL, inhibit state |
| `application/source/functions/dmr_rctl_tx.c` | 774 | Побудова RCTL-команд, відправка через dmr_data queue |

### 1.3. DMR Data — SMS та data layer (`functions/`)
| Файл | Рядків | Призначення |
|------|--------|-------------|
| `application/include/functions/dmr_data.h` | 58 | Черга TX-бурстів, `dmrDataTxLoad()`, типи блоків |
| `application/include/functions/dmr_sms.h` | 144 | API SMS: send (CONFIRMED PDU), ACK-прапорець, зберігання повідомлень |
| `application/source/functions/dmr_data.c` | 207 | Читання/запис черги TX у flash, TX state machine |
| `application/source/functions/dmr_sms.c` | 1447 | Все SMS: UDH+UCS2 encode, CONFIRMED TX, CRC9, ACK-RX, store у flash |

### 1.4. Переслухати виклик (`functions/`)
| Файл | Рядків | Призначення |
|------|--------|-------------|
| `application/include/functions/callReplay.h` | 194 | Кільцевий буфер AMBE-фреймів у CCM; config структура |
| `application/source/functions/callReplay.c` | 240 | Запис у кільце, конфіг, reset |
| `application/source/functions/callReplayPlayback.c` | 442 | Відтворення через codec/trx/FreeRTOS task |

### 1.5. Спектр-сканер та reject (`functions/`)
| Файл | Рядків | Призначення |
|------|--------|-------------|
| `application/include/functions/spectrum.h` | 441 | VFO sweep API, `spectrumScanAnalogDwellMs`, `spectrumTick()` |
| `application/source/functions/spectrum.c` | 847 | Swept-RSSI сканер, відображення, auto-scale, peak marker |
| `application/include/functions/scanreject.h` | 106 | Швидкий RSSI-reject при скануванні каналів |
| `application/source/functions/scanreject.c` | 102 | Реалізація reject-порогу |

### 1.6. Мовні файли (нові)
| Файл | Рядків | Призначення |
|------|--------|-------------|
| `application/include/user_interface/languages/ukrainian.h` | 365 | Повна українська локалізація (cp1251) |
| `application/include/user_interface/languages/aes_ua.h` | 16 | Рядки меню AES (ua) |
| `application/include/user_interface/languages/rctl_ua.h` | 77 | Рядки меню RCTL (ua) |
| `application/include/user_interface/languages/messages_ua.h` | 60 | Повідомлення SMS store (ua) |
| `application/include/user_interface/languages/slogans_ua.h` | 23 | Гасла сплеш/виключення (ua) |
| `application/include/user_interface/languages/txerr_ua.h` | 30 | Рядки помилок передачі (ua) |

### 1.7. Тести (`tests/`)
| Файл | Рядків | Що тестує |
|------|--------|-----------|
| `tests/run_tests.sh` | 84 | Runner: збирає і запускає всі тести через gcc |
| `tests/mock_codeplug.c/h` | 104 | Заглушка кодплагу для тестів dmr_rctl_cfg |
| `tests/test_dmr_aes.c` | 96 | AES-256: encrypt/decrypt, 9-байтні фрейми |
| `tests/test_emb_sb.c` | 65 | EMB short-burst бітова укладка |
| `tests/test_le_mi.c` | 121 | LC/MI (Link Control / Message Indicator) поля |
| `tests/test_dmr_rctl_pdu.c` | 117 | PDU: серіалізація, anti-replay |
| `tests/test_dmr_rctl_frame.c` | 134 | Frame packing/unpacking |
| `tests/test_dmr_rctl_cfg.c` | 353 | Config: read/write маски, inhibit |
| `tests/test_dmr_rctl_cap.c` | 82 | BS CAP negotiation |
| `tests/test_dmr_rctl_stock.c` | 229 | Стокові команди |
| `tests/test_dmr_sms_ack.c` | 108 | Response header (ACK): байт-у-байт з ефіру (BBD_0005) |
| `tests/test_dmr_sms_confirmed.c` | 175 | CRC9 і укладка CONFIRMED-блока |
| `tests/test_call_replay.c` | 444 | Кільцевий буфер: запис/читання, wrap-around |

### 1.8. Інструменти (`tools/`)
56 нових Python-скриптів та shell-скриптів. Категорії:
- **Ключі AES**: `aes_channel_key.py`, `aes_key_store.py`, `aes_key_tool.py`
- **DMR data TX/RX**: `dmr_data_rx.py`, `dmr_data_tx.py`, `dmr_enc_sms.py`, `dmr_csbk_rx.py`, `fragcap.py`
- **RCTL**: `gate2sens.py`, `amrssi.py`, `amlisten.py`, `amsim.py`
- **Call replay**: `callreplay_config.py`, `antcmp.py`, `antcmp3.py`
- **Спектр**: `sweep.py`, `scanprof.py`
- **CI/якість**: `syntax_check.sh`, `check_string_encoding.py`, `check_menu_widths.py`, `check_smeter_align.py`, `mem_report.py`, `custom_data.py`
- **Прошивка**: `dmr_reboot_dfu.py`, `genam.py`, `chirp_rctl.py`

### 1.9. CI та документація
- `.github/workflows/build.yml` — розширений: матриця ENABLE_AES/ENABLE_DMR_DATA, mem_report.py у CI, хостові тести через `tests/run_tests.sh`
- `STATUS.md`, `TESTING.md`, `BUILD.md`, `USAGE.md`, `PLANS.md`, `RCTL_COMPAT.md` — нові doc-файли
- `docs/notification-buffer.md`, `docs/recording-feasibility.md` — технічні розвідки
- `flash.sh`, `test_build.sh` — допоміжні скрипти
- `README.md` — суттєво розширений (186 рядків зміни)

---

## 2. Змінені файли upstream

### 2.1. Файли під повним #if-захистом (byte-identical без наших дефайнів)

| Файл | +/- | Дефайн-охорона | Що змінено |
|------|-----|----------------|------------|
| `application/source/functions/trx.c` | +52 | `ENABLE_SPECTRUM` | Swept-RSSI: точки вимірювання, частотний крок для спектра |
| `application/source/functions/settings.c` | +77 | `ENABLE_SPECTRUM`, `ENABLE_FAST_SCAN` | `settingsGetScanStepTimeMilliseconds()` розширено; нові `SCAN_STEP_FAST_MS[]`, `settingsGetAdjacentScanStepTime()` |
| `application/source/user_interface/uiChannelMode.c` | +42/−12 | `ENABLE_AES`, `ENABLE_CALL_REPLAY` + 1 безумовна¹ | AES-іконка на каналі; SK1 → Переслухати; оминання порожніх зон (безумовно) |
| `application/source/user_interface/uiVFOMode.c` | +1221/−27 | `ENABLE_FAST_SCAN`, `ENABLE_SPECTRUM`, `ENABLE_AES`, `ENABLE_CALL_REPLAY` | Spectrum sweep UI; fast-scan; AES-іконка |
| `application/source/functions/rxPowerSaving.c` | невелика | (не аналізувалась детально) | |
| `application/source/functions/sound.c` | +20/−2 | `ENABLE_AES`, `ENABLE_CALL_REPLAY` | Мелодія для подій AES/replay |
| `application/source/hardware/AT1846S.c` | невелика | `ENABLE_SPECTRUM` | Точки вимірювання RSSI для спектра |
| `application/source/hardware/HX8353E_display.c` | невелика | `HAS_COLOURS` | |
| `application/source/hardware/radioHardwareInterface.c` | невелика | `ENABLE_SPECTRUM` | |
| `application/source/interfaces/batteryAndPowerManagement.c` | невелика | (не аналізувалась) | |
| `application/source/interfaces/gps.c` | невелика | `HAS_GPS` | |
| `application/source/user_interface/uiPowerOff.c` | невелика | `LANGUAGE_BUILD_UKRAINIAN` | Гасло замість "73" при вимкненні (ua-build) |
| `application/source/user_interface/menuLanguage.c` | невелика | `LANGUAGE_BUILD_UKRAINIAN` | Рядок "Українська" у меню мови |
| `application/source/user_interface/menuDisplayMenuList.c` | невелика | `ENABLE_AES`, `ENABLE_CALL_REPLAY` | Нові пункти меню |
| `application/source/user_interface/menuDisplayOptions.c` | невелика | `ENABLE_SPECTRUM`, `HAS_COLOURS` | S-meter, Spectrum пункти |
| `application/source/user_interface/menuRadioOptions.c` | невелика | `ENABLE_AES`, `ENABLE_DMR_DATA` | AES keys, Remote Control пункти |
| `application/source/user_interface/menuGeneralOptions.c` | невелика | `ENABLE_FAST_SCAN`, `LANGUAGE_BUILD_UKRAINIAN` | Fast scan dwell; ua-рядки |
| `application/source/user_interface/menuZoneList.c` | невелика | (не аналізувалась) | |
| `application/source/user_interface/menuSoundOptions.c` | невелика | `ENABLE_CALL_REPLAY` | Replay config у меню |
| `application/source/user_interface/menuSatelliteScreen.c` | невелика | `LANGUAGE_BUILD_UKRAINIAN` | |
| `application/source/user_interface/menuChannelDetails.c` | невелика | `ENABLE_AES` | Поле "Encrypt TX" |
| `application/source/user_interface/menuGPS.c` | невелика | `LANGUAGE_BUILD_UKRAINIAN` | |
| `application/source/user_interface/uiLocalisation.c` | невелика | `LANGUAGE_BUILD_UKRAINIAN` | |
| `application/source/user_interface/menuSystem.c` | +35/−1 | `ENABLE_AES`, `ENABLE_DMR_DATA`, `ENABLE_CALL_REPLAY` | Нові екрани у menuSystemGetMenuIDsForStack |
| `application/source/dmr_codec/codec_interface.c` | +35 | `ENABLE_CALL_REPLAY` | Hook запису AMBE-фреймів у кільцевий буфер |
| `application/source/interfaces/usb_com.c` | +1362 | Більшість під #if², але 2 include безумовні | USB CPS команди: AES key import, spectrum sweep, RCTL diag, key injection |

¹ Детально: `uiChannelMode.c` має одну безумовну зміну — оминання порожніх зон при перемиканні (пояснення в §4).  
² Детально: `usb_com.c` — безумовний `#include "io/display.h"` та 6 наших headers. Самі headers охороняють свій вміст через `#if defined(ENABLE_DMR_DATA) && defined(ENABLE_AES)` тощо, тому в компіляції без наших дефайнів вони не додають символів.

### 2.2. Файли з безумовними змінами (порушують byte-identical)

| Файл | Зміна | Наслідок для build без дефайнів |
|------|-------|--------------------------------|
| `application/source/functions/codeplug.c` | Функцію `codeplugGetOpenGD77CustomData()` перейменовано та замінено на `codeplugGetOpenGD77CustomDataBounded(maxLen)`. **Без жодного #if.** | Зміна API: повернення нової функції (безпечніша поведінка), стара назва відсутня |
| `application/source/user_interface/uiNotification.c` | Буфер `screenNotificationBufData` у CCM скорочено з `DISPLAY_SIZE_X*DISPLAY_SIZE_Y` (40 960 Б) до `DISPLAY_SIZE_X*NOTIFICATION_APO_BUF_H` (23 040 Б). **Без #if.** | Звільняє 17 920 Б CCMRAM; APO-картка зберігається лише для своїх рядків |
| `application/source/applicationMain.c` | PTT-latch fallback таймер `pttLatchFallbackTimer` (120 с) — знімає залипання на каналах без TOT. **Без #if.** | Нова поведінка: на каналі без TOT залипання автоматично знімається через 2 хв |
| `application/source/applicationMain.c` | `dmrAesInit()`, `callReplayInit()`, `callReplayPlaybackInit()`, `callReplayConfigLoad()`, `dmrAesLoadKeys()`, `dmrSmsInit()` — виклики при старті **без #if** | Функції є no-op без ENABLE_AES/ENABLE_DMR_DATA (перевірено: пусті stub або `#if` всередині). Символи додаються до бінарника, але розмір мінімальний. |
| `application/source/applicationMain.c` | `SCANPROF_PERIOD()` / `SCANPROF_START()` — макроси у тілі циклу **без #if** | Розгортаються в порожнечу без ENABLE_SPECTRUM (макроси-заглушки у spectrum.h) |
| `application/source/hardware/HR-C6000.c` | `5000L / sizeof(portSTACK_TYPE)` → `HRC6000_TASK_STACK_WORDS` | Косметично, розмір стека не змінився |
| `application/source/user_interface/uiTxScreen.c` | `#include "functions/dmr_rctl_cfg.h"` (безумовний); `txErrorHoldMs` 500 мс → 3000 мс при відмові ретранслятора; новий `TXSTOP_REPEATER_NO_RESPONSE` екран | Header безпечний. Поведінка змінюється: екран "немає ретранслятора" тримається 3 с замість 0.5 с; натискання клавіші прибирає достроково |
| `application/source/user_interface/uiSplashScreen.c` | `codeplugGetOpenGD77CustomData()` → `codeplugGetOpenGD77CustomDataBounded()` (вся прошивка) | Пов'язане з перейменуванням в codeplug.c |
| `application/source/user_interface/uiChannelMode.c` | Цикл оминання порожніх зон замість прямого `settingsIncrement/Decrement` | Перемикання зон тепер пропускає зони без каналів |
| `application/source/user_interface/uiVFOMode.c` | `displayRenderRows(..., 2)` → `displayRenderRows(..., uiUtilityRSSIRenderEndRow(2))` | Рядок перемальовування RSSI залежить від нової функції; візуально без HAS_COLOURS ідентично |
| `application/source/user_interface/menuFirmwareInfoScreen.c` | "Bohdan UW5ELK" у списку авторів | Видно у меню About |
| `application/include/user_interface/languages/english.h` | `".celcius"` виправлено (спецсимвол), нові поля AES/RCTL/replay під `#if ENABLE_*`; **безумовно** 2 поля під `#if LANGUAGE_BUILD_UKRAINIAN`: `gps_absent`, `power` | Без LANGUAGE_BUILD_UKRAINIAN ці поля відсутні, але struct розмір не змінюється (нові поля в кінці блоку) |
| `STM32F405VGTX_FLASH.ld` | Нова секція `.aes_ccmram` у CCMRAM | Без ENABLE_AES секція порожня (0 Б), але linker script відрізняється від upstream |

---

## 3. Видимі зміни для користувача без наших дефайнів

Якщо зібрати форк **без** ENABLE_AES, ENABLE_DMR_DATA, ENABLE_CALL_REPLAY, ENABLE_SPECTRUM:

1. **PTT latch на каналах без TOT** — залипання автоматично знімається через 120 с. В upstream такого обмеження не було.
2. **Екран помилки ретранслятора** — тримається 3000 мс (upstream: 500 мс); закривається будь-якою клавішею.
3. **Оминання порожніх зон** — при переключенні зон зони з 0 каналів пропускаються.
4. **"Bohdan UW5ELK"** — у списку авторів (меню About → Firmware info).
5. **APO notification card** — займає меншу область CCMRAM (17 920 Б менше); функціонально майже непомітно (можливий 1-пкс артефакт на межі картки в крайніх випадках, задокументовано у `docs/notification-buffer.md`).
6. **Екран вимкнення** — гасло замість "73" (лише LANGUAGE_BUILD_UKRAINIAN).
7. **Splash screen** — лише гасло, без OpenGD77/line1/line2 (лише LANGUAGE_BUILD_UKRAINIAN).
8. **Авторський список** (About) — "Bohdan UW5ELK" у списку.

---

## 4. Перевірка обіцянки «байт-у-байт ідентична апстріму»

**Висновок: обіцянка формально не виконується.** Є 8 класів безумовних відмінностей:

| # | Відмінність | Вплив на бінарник |
|---|-------------|-------------------|
| 1 | `codeplugGetOpenGD77CustomDataBounded()` замість `codeplugGetOpenGD77CustomData()` | Нова функція, нова назва; стара відсутня — **значна** |
| 2 | Буфер APO 23 040 Б замість 40 960 Б у CCMRAM | Зменшення CCM-сегмента **значна** |
| 3 | PTT latch fallback 120 с | Нова глобальна змінна + таймер | **значна** |
| 4 | `txErrorHoldMs` та `TXSTOP_REPEATER_NO_RESPONSE` | Новий code path в uiTxScreen | **помітна** |
| 5 | Оминання порожніх зон при перемиканні | Зміна поведінки zone switch | **помітна** |
| 6 | "Bohdan UW5ELK" у авторах | +одна строка в .rodata | **незначна** |
| 7 | Виклики `dmrAesInit()` тощо при старті | Додаються stub-символи (pусті тіла), незначне збільшення .text | **незначна** |
| 8 | `STM32F405VGTX_FLASH.ld` відрізняється | Linker script — впливає на .map, але без AES-символів секція порожня | **незначна** |

**Де вважалося "безпечним":** усі нові заголовки `dmr_*.h` / `callReplay.h` вмикають вміст лише через `#if defined(ENABLE_*)`, тому безумовний `#include` у `usb_com.c` та `uiTxScreen.c` не додає символів. Макроси `SCANPROF_*` розгортаються в `((void)0)` без ENABLE_SPECTRUM.

---

## 5. Чого немає відносно upstream

Ми не вилучали жодного upstream функціоналу навмисно. Усі стокові можливості (FM/DMR прийом/передача, hotspot, сканування, satellite, APRS, голосові підказки тощо) лишились незмінними або незначно доповнені за рахунок нашого коду.

Єдине обмеження: буфер APO-картки скорочено з повноекранного до 72 рядків (§4, п.2). При переключенні APO-картки у нас зберігається лише нижня частина екрана; верхня частина при поверненні може мати 1-пкс артефакт на межі збереженої / незбереженої областей. Задокументовано у `docs/notification-buffer.md`.

---

*Файл згенеровано 2026-09-28. Оновити при наступних значних змінах.*
