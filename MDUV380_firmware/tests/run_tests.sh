#!/usr/bin/env bash
#
# Збирає й запускає ВСІ хостові тести. Без рації, без ARM-тулчейну -- звичайний gcc.
#
#     MDUV380_firmware/tests/run_tests.sh          # усі
#     MDUV380_firmware/tests/run_tests.sh rctl     # лише ті, чия назва містить "rctl"
#
# НАВІЩО ЦЕЙ ФАЙЛ. Тести тут лежали давно, але рядки збірки були розкидані по
# коментарях у самих тестах, у кожного свій набір -I та своїх файлів. Через це їх
# фактично ніхто не ганяв, і в CI вони не потрапляли.
#
# Гірше: при ручному запуску легко ОБМАНУТИ САМОГО СЕБЕ. 2026-09-04 я прогнав тест
# однорядковим циклом, компіляція впала через брак -I, але бінарник із попереднього
# запуску лишався в /tmp -- і цикл радісно надрукував "ПРОЙДЕНО". Тому тут:
#   * кожен тест збирається у СВІЙ свіжий каталог, який спершу видаляється;
#   * помилка компіляції -- це провал тесту, а не "пропустимо";
#   * ненульовий код виходу самого тесту -- теж провал;
#   * наприкінці друкується підсумок, і скрипт повертає 1, якщо впав хоч один.
set -u

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$TESTS_DIR/../application"
INC=(-I "$APP/include" -I "$APP/include/crypto")
# -DENABLE_CALL_REPLAY -- глобально, як і AES/DMR_DATA вище: лише test_call_replay
# лінкує functions/callReplay.c (порожній translation unit без цього прапорця), решті
# тестів прапорець просто не зустрічається -- нешкідливо додати його для всіх.
CFLAGS=(-O2 -Wall -Wextra -std=gnu11 -DENABLE_AES -DENABLE_DMR_DATA -DENABLE_CALL_REPLAY)
BUILD="$TESTS_DIR/.build"

CC="${CC:-gcc}"
FILTER="${1:-}"

# назва -> додаткові файли для лінкування (крім самого тесту)
declare -A SRCS=(
	[test_dmr_aes]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"
	[test_dmr_rctl_pdu]="$APP/source/crypto/dmr_rctl_pdu.c"
	[test_dmr_rctl_frame]="$APP/source/crypto/dmr_rctl_frame.c $APP/source/crypto/dmr_rctl_pdu.c $APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"
	[test_dmr_rctl_cfg]="$TESTS_DIR/mock_codeplug.c $APP/source/functions/dmr_rctl_cfg.c $APP/source/crypto/dmr_rctl_pdu.c"
	[test_dmr_rctl_cap]="$APP/source/functions/dmr_rctl_cap.c"
	[test_dmr_rctl_stock]="$APP/source/crypto/dmr_rctl_stock.c"
	[test_emb_sb]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"
	[test_le_mi]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"
	[test_dmr_sms_ack]="$APP/source/functions/dmr_sms_pdu.c $APP/source/functions/dmr_sms_text.c"   # квитанція: СПРАВЖНІЙ білдер заголовка
	[test_dmr_sms_unconf]="$APP/source/functions/dmr_sms_pdu.c $APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # режим 0 == 438ec23 байт-у-байт
	[test_ta_diag]="$APP/source/functions/ta_diag.c -lm"   # R88: чисті функції діагностики TA / GPS-блока LC (лише ENABLE_TA_DIAG); дані синтетичні
	[test_dmr_sms_confirmed]=""       # самодостатній: CRC9 + розкладка CONFIRMED-блока
	[test_call_replay]="$APP/source/functions/callReplay.c"   # лише ЧИСТА кільцева логіка -- callReplayPlayback.c (codec/sound/trx/FreeRTOS) сюди навмисно не тягнеться
	[test_dmr_sms_fix]="$APP/source/functions/dmr_sms_fix.c $APP/source/functions/dmr_sms_pdu.c $APP/source/functions/dmr_sms_text.c"   # fix7: корекція трибітів rate-3/4
	[test_dmr_sms_replay]="$APP/source/functions/dmr_sms.c $APP/source/functions/dmr_sms_fix.c $APP/source/functions/dmr_sms_pdu.c $APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # diag5: СПРАВЖНІЙ збирач SMS, залізо -- заглушки в тесті
	[test_dmr_sms_shift]="$APP/source/functions/dmr_sms_text.c $APP/source/functions/dmr_sms_pdu.c $APP/source/functions/dmr_sms_fix.c $APP/source/crypto/dmr_aes.c"   # ui5: кирилиця від Z3DMR (зсув старших байтів UTF-16)
	[test_dmr_sms_store]="$APP/source/functions/dmr_sms.c $APP/source/functions/dmr_sms_fix.c $APP/source/functions/dmr_sms_pdu.c $APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # ui6: сховище v3 і перетворення v2 -> v3
	[test_dmr_sms_peerb]="$APP/source/functions/dmr_sms.c $APP/source/functions/dmr_sms_fix.c $APP/source/functions/dmr_sms_pdu.c $APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # R98-FIX2 Д: біт 31 peerId (картка B), СПРАВЖНІЙ збирач і сховище
	[test_dmr_sms_flash]="$APP/source/functions/dmr_sms.c $APP/source/functions/sms_flash_store.c $APP/source/functions/dmr_sms_fix.c $APP/source/functions/dmr_sms_pdu.c $APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # R106-SMSSTORE: СПРАВЖНІ збирач, сховище і кільце секторів флешу (модель NOR)
	[test_channel_vox]=""   # ui8: умова VOX на APRS-каналі (лише заголовок)
	[test_sms_format]="$APP/source/functions/sms_format.c"   # ui6: перенесення за словами, форма слова, час
	[test_sms_multitap]="$APP/source/functions/sms_multitap.c"   # ui4: розкладки й логіка multitap набору SMS
	[test_aprs_probe_dsp]="$APP/source/functions/aprs_probe_dsp.c -lm"   # R2: рівень і тони 1200/2200 для екрана «APRS проба»
	[test_aprs_afsk]="$APP/source/functions/aprs_afsk.c $APP/source/functions/aprs_probe_dsp.c -lm"   # R3: демодулятор Bell 202 + AX.25, поріг SNR, завади
	[test_aprs_rx_parse]="$APP/source/functions/aprs_rx_parse.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/dmr_sms_text.c -lm"   # R8: розбір кадрів APRS, Mic-E, дедуплікація, список станцій, відстань
	[test_aprs_mode]="$APP/source/functions/aprs_mode_cfg.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/dmr_sms_text.c -lm"   # R10: налаштування «Режиму APRS» -- блок, типові значення, ефективні, збирання бікона, UTF-8 коментар
	[test_aprs_mode_state]="$APP/source/functions/aprs_mode.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/aprs_msg.c $APP/source/functions/callReplay.c"   # R10: вхід/вихід «Режиму APRS», налаштування, маяк -- РЕАЛЬНИЙ aprs_mode.c, залізо -- заглушки в тесті
	[test_aprs_settings_ui]="$APP/source/functions/aprs_mode.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/aprs_msg.c $APP/source/functions/callReplay.c $APP/source/functions/aprs_icons.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/dmr_sms_text.c $APP/source/functions/sms_multitap.c -lm"   # R17 Г1: справжнє меню «Налаштування» (групи, символ, стокові рядки, скидання, редактор) поверх світу заглушок test_aprs_mode_state.c
	[test_aprs_msg]="$APP/source/functions/aprs_msg.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/dmr_sms_text.c -lm"   # R11: повідомлення APRS -- UTF-8/cp1251, кадр повідомлення й ACK, черга/повтори/ACK/пауза
	[test_aprs_frame]="$APP/source/functions/aprs_mode_cfg.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/dmr_sms_text.c -lm"   # R10-fix2: складання кадру AX.25 -- РЕАЛЬНИЙ aprs.c (#include), еталонний кодувальник у тесті, ASan/UBSan
	[test_aprs_frame_ovf]="$APP/source/functions/aprs_mode_cfg.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/dmr_sms_text.c -lm"   # R10-fix2: гілка «кадр завеликий» -- aprs.c з МАЛИМ буфером
	[test_aprs_icons]="$APP/source/functions/aprs_icons.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/dmr_sms_text.c -lm"   # R14: піктограми 16x16 і назви символів APRS (вікно маяка)
	[test_aprs_fault]="$APP/source/functions/aprs_fault_fmt.c"   # R10-fix4: ЧИСТА частина обробника збою -- hex/dec, CFSR, пошук адрес у стеку, магія запису
	[test_aprs_stations_ui]="$APP/source/functions/aprs_rx_parse.c $APP/source/functions/dmr_sms_text.c -lm"   # R8-fix: справжній екран «APRS станції», дисплей і приймач -- заглушки
	[test_codeplug_zone]="$APP/source/functions/codeplug.c"   # R22 Z1: СПРАВЖНІЙ codeplug.c -- вибір зон (єдине правило «справжня зона», ліміт 68 бітів, крок валкодера); залізо -- заглушки в тесті
	[test_codeplug_chandel]="$APP/source/functions/codeplug.c"   # R41: СПРАВЖНІЙ codeplug.c -- видалення каналу (маска EEPROM/флеш, зони, LUCZ, межі банків, збої запису); EEPROM і NOR-флеш -- образи в пам'яті
	[test_codeplug_zonerename]="$APP/source/functions/codeplug.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/dmr_sms_text.c -lm"   # R42: СПРАВЖНІЙ codeplug.c -- перейменування зони (запис лише 16 байтів назви, кінцева «я» через хвіст 0x00, межі довжини, «Всі канали», збій запису); EEPROM -- образ у пам'яті
	[test_codeplug_zoneedit]="$APP/source/functions/codeplug.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/dmr_sms_text.c -lm"   # R43: СПРАВЖНІЙ codeplug.c -- додати канал у кінець, вийняти зі зсувом, створити й видалити зону, ординал поточної зони, межі, збої запису, автовизначення розкладки 16/80; EEPROM -- образ у пам'яті
	[test_codeplug_contact]="$APP/source/functions/codeplug.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/dmr_sms_text.c -lm"   # R44: СПРАВЖНІЙ codeplug.c -- видалення контакту з каскадом (поле «контакт» у каналах -> 0), лічильник каналів із контактом; EEPROM і NOR-флеш -- образи в пам'яті
	[test_codeplug_rxgroup]="$APP/source/functions/codeplug.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/dmr_sms_text.c -lm"   # R65B: СПРАВЖНІЙ codeplug.c -- редактор списків прийому (створити/перейменувати/склад/видалити з каскадом), порядок записів, обрив живлення в кожній точці
	[test_codeplug_zonemove]="$APP/source/functions/codeplug.c $APP/source/functions/aprs_rx_parse.c $APP/source/functions/aprs_mode_cfg.c $APP/source/functions/dmr_sms_text.c -lm"   # R66C: СПРАВЖНІЙ codeplug.c -- переміщення каналу в зоні (обмін сусідів, один запис 4 Б, LUCZ, межа сектора, обрив після кожного запису)
	[test_volume_probe]="$APP/source/functions/volume_probe.c -lm"   # R77A: СПРАВЖНІЙ volume_probe.c (екран «Гучн. проба»): таблиці, повернення до стокового, захисти APRS/цифра/хотспот; заглушки лише обладнання
	[test_volume_low]="$APP/source/functions/volume_low.c -lm"   # R78: СПРАВЖНІЙ volume_low.c («Мін.гучність»): крива, таблиці, захисти 0x44, збереження
	[test_sat_tone]=""   # R66D: СПРАВЖНЯ чиста функція satellite_tone.h + модель місць запису txTone в екрані супутників (відтворення сценаріїв 5/7/8 з r56-result.md)
	[test_sql_open_delay]=""   # R42: чиста логіка затримки відкриття шумодава (application/include/functions/sql_open_delay.h) -- лише заголовок
	[test_aes_resync]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # AES-fix1: СПРАВЖНІЙ dmr_aes_hook.c (#include) -- ресинхронізація MI, захист від хибного CRC4, обидві конвенції late entry; залізо -- заглушки в тесті
	[test_aes_txphase]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # AES-fix2: СПРАВЖНІЙ dmr_aes_hook.c (#include) -- фаза шифрування TX за ефіром при тихих burst-ах (SILENCE_AUDIO), межа 18 кадрів, B3 тиша на RX; черга кодувальника й залізо -- модель у тесті
	[test_aes_rawdiag]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # AES-fix3: СПРАВЖНІЙ dmr_aes_hook.c (#include, -DDMR_AES_DIAG_RX) -- розкладка дампу сирих LC/EMB, дедуп, блок «наші байти»
	[test_aes_pifilter]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # AES-fix6: СПРАВЖНІЙ dmr_aes_hook.c (#include, -DDMR_AES_DIAG_RX) -- класифікація PI-burst-ів до стокового фільтра, кільця, режими G2
	[test_aes_retune]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # R98-FIX2 Е: СПРАВЖНІЙ dmr_aes_hook.c (#include) -- скидання стану RX AES при перенастроюванні A<->B
	[test_wake_diag]="$APP/source/functions/wake_diag.c"   # R58: СПРАВЖНІЙ wake_diag.c -- журнал сеансів пробудження (кільце, prev, HOP_START, насичення, дамп 0xB7, рядки екрана); укр. варіант -- довжина рядків
	[test_wake_hop]="$APP/source/functions/wake_hop_sel.c"   # R59: СПРАВЖНІЙ wake_hop_sel.c -- придатність каналу, випробувані (rx,tx,cc), ліміт стрибків, кільце по списку, один оберт
	[test_aes_key_name]="$APP/source/crypto/aes_key_name.c"   # R64C: СПРАВЖНІЙ aes_key_name.c -- cp1251 <-> UTF-16LE для імен слотів AES-ключів (повна звірка з Python -- tools/test_aes_key_name.py)
	[test_roam_cfg]="$APP/source/functions/roam_cfg.c"   # R59: СПРАВЖНІЙ roam_cfg.c -- формат custom-data блоку «Роумінгу» (розбір/збірка/межі)
	[test_dmr_sms_text]="$APP/source/functions/dmr_sms_text.c $APP/source/functions/dmr_sms_pdu.c $APP/source/functions/dmr_sms_fix.c $APP/source/crypto/dmr_aes.c"   # ui4: cp1251 <-> UTF-16LE, dst-IP, PDU з кирилицею
)

# назва -> додаткові прапорці. dmr_sms.c тягне заголовки всієї прошивки (HAL/CMSIS/FreeRTOS),
# тож потрібні ті самі -I і платформні -D, що в tools/syntax_check.sh (конфігурація UA).
FW="$TESTS_DIR/.."
FW_INCS="-I$FW/tools/hoststub -include $FW/tools/hoststub/host_compat.h -I$FW -I$FW/Core/Inc \
 -I$FW/Drivers/CMSIS/Device/ST/STM32F4xx/Include -I$FW/Drivers/CMSIS/Include \
 -I$FW/Drivers/STM32F4xx_HAL_Driver/Inc -I$FW/Drivers/STM32F4xx_HAL_Driver/Inc/Legacy \
 -I$FW/Middlewares/ST/STM32_USB_Device_Library/Class/CDC/Inc -I$FW/Middlewares/ST/STM32_USB_Device_Library/Core/Inc \
 -I$FW/Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2 -I$FW/Middlewares/Third_Party/FreeRTOS/Source/include \
 -I$FW/Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F -I$FW/USB_DEVICE/App -I$FW/USB_DEVICE/Target \
 -I$FW/application/include"
declare -A XFLAGS=(
	[test_dmr_sms_replay]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_codeplug_zone]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-missing-field-initializers"
	[test_codeplug_chandel]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_CHANNEL_DELETE -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-missing-field-initializers"
	[test_codeplug_zonerename]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_AES -DENABLE_APRS_RX -DENABLE_ZONE_RENAME -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-missing-field-initializers"
	[test_codeplug_zoneedit]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_AES -DENABLE_APRS_RX -DENABLE_ZONE_RENAME -DENABLE_ZONE_EDIT -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-missing-field-initializers"
	[test_codeplug_contact]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_AES -DENABLE_APRS_RX -DENABLE_ZONE_RENAME -DENABLE_ZONE_EDIT -DENABLE_CHANNEL_DELETE -DENABLE_CODEPLUG_MENU -funsigned-char -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-missing-field-initializers"   # -funsigned-char: як на ARM (char без знака) -- інакше `name[0] != 0xFF` у кеші контактів хибне на x86
	[test_codeplug_rxgroup]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_AES -DENABLE_APRS_RX -DENABLE_ZONE_RENAME -DENABLE_ZONE_EDIT -DENABLE_CHANNEL_DELETE -DENABLE_CODEPLUG_MENU -DENABLE_RXGROUP_EDIT -funsigned-char -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-missing-field-initializers"
	[test_codeplug_zonemove]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_AES -DENABLE_APRS_RX -DENABLE_ZONE_RENAME -DENABLE_ZONE_EDIT -DENABLE_CHANNEL_DELETE -DENABLE_CODEPLUG_MENU -funsigned-char -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-missing-field-initializers"
	[test_volume_probe]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_VOLUME_PROBE -DENABLE_APRS_RX -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_volume_low]="$FW_INCS -DVOLLOW_TEST_HOOKS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_VOLUME_LOW -DENABLE_VOLUME_PROBE -DENABLE_APRS_RX -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_sat_tone]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_dmr_rctl_stock]="-DENABLE_DMR_DATA"   # R21 З2: тест читає чергу так, як драйвер (functions/dmr_data.h)
	[test_aprs_probe_dsp]="-DENABLE_APRS_RX_PROBE"
	[test_wake_diag]="-DENABLE_WAKE_DIAG"
	[test_ta_diag]="-DENABLE_TA_DIAG"
	[test_wake_hop]="-DENABLE_ROAM_RETRY -DWAKE_HOP_HOST_TEST -DROAM_CFG_HOST_TEST"
	[test_roam_cfg]="-DENABLE_ROAM_RETRY -DROAM_CFG_HOST_TEST"
	[test_aes_key_name]="-DAES_KEY_NAME_HOST_TEST"
	[test_aprs_afsk]="-DENABLE_APRS_RX_PROBE"
	[test_aprs_rx_parse]="-DENABLE_APRS_RX"
	[test_aprs_icons]="-DENABLE_APRS_RX"
	[test_aprs_fault]="-DENABLE_APRS_RX"
	[test_aprs_mode]="-DENABLE_APRS_RX"
	[test_aprs_msg]="-DENABLE_APRS_RX"
	[test_aprs_mode_state]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_APRS_RX -DAPRS_MODE_NO_TRACE -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_aprs_settings_ui]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_APRS_RX -DAPRS_MODE_NO_TRACE -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_aprs_frame]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_APRS_RX -DAPRS_MODE_NO_TRACE -Wl,--unresolved-symbols=ignore-all -fsanitize=address,undefined -fno-sanitize-recover=undefined -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_aprs_frame_ovf]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_APRS_RX -DAPRS_MODE_NO_TRACE -Wl,--unresolved-symbols=ignore-all -fsanitize=address,undefined -fno-sanitize-recover=undefined -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_aprs_stations_ui]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_APRS_RX -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_aes_resync]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-int-to-pointer-cast -fsanitize=address,undefined -fno-sanitize-recover=undefined"   # AES-fix1
	[test_aes_txphase]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-int-to-pointer-cast -fsanitize=address,undefined -fno-sanitize-recover=undefined"   # AES-fix2
	[test_aes_rawdiag]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-int-to-pointer-cast -fsanitize=address,undefined -fno-sanitize-recover=undefined"   # AES-fix3
	[test_aes_pifilter]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-int-to-pointer-cast -fsanitize=address,undefined -fno-sanitize-recover=undefined"   # AES-fix6
	[test_aes_retune]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_DUAL_CHANNEL -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable -Wno-int-to-pointer-cast -fsanitize=address,undefined -fno-sanitize-recover=undefined"
	[test_dmr_sms_store]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_dmr_sms_peerb]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_DUAL_CHANNEL -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
	[test_dmr_sms_flash]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -DENABLE_SMS_STORE_FLASH -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"   # R106: з прапорцем сховища у флеші
)

# cleanup1 (2026-10-05): тести, які ще раз збираються з -DENABLE_SMS_DIAG (окремий бінарник
# <назва>_smsdiag) -- діагностику SMS у CI не вмикають, тож інакше її код ніхто б не ганяв.
SMSDIAG_TOO=(test_dmr_sms_replay)
# ui4: тести, які ще раз збираються з -DLANGUAGE_BUILD_UKRAINIAN (бінарник <назва>_ua) --
# кириличні розкладки існують лише в українській збірці.
UA_TOO=(test_sms_multitap test_wake_diag)
# AES-fix1: тест ресинхронізації збирається ще й зі збіркою-кандидатом AES_TX_MI_CURRENT (бінарник <назва>_cur)
# та з діагностикою прийому DMR_AES_DIAG_RX (<назва>_diag) -- інакше ні цей режим, ні діагностичний код у CI не компілювалися б.
MICUR_TOO=(test_aes_resync test_aes_txphase)
DIAGRX_TOO=(test_aes_resync test_aes_txphase test_aes_rawdiag test_aes_pifilter)
# AES-fix2: ІНВЕРТОВАНІ збірки з вимкненим фіксом фази TX (-DAES_TX_PHASE_FIX_OFF): тест має ЗНАЙТИ зсув (ловить дефект);
# і те саме разом з діагностикою (<назва>_diagnofix) -- дамп фази мусить показати k=3, а не 0.
NOFIX_TOO=(test_aes_txphase)

rm -rf "$BUILD" && mkdir -p "$BUILD"

pass=0; fail=0; notk=0
# R105: облік пропусків. Тест, що мовчки пропустив частину перевірок, -- НЕ «пройдено»: кожен рядок «ПРОПУСК…» з виводу python-тесту
# (і «ПРОПУЩЕНО…» цього скрипта) рахується й друкується. Очікуваний пропуск -- лише через відсутність в оточенні gcc, Pillow/PIL,
# numpy/scipy, tkinter/xvfb (перелік EXPECTED_SKIP_RE). Усе інше -- НЕОЧІКУВАНИЙ пропуск; у режимі CI (змінна CI=true, її ставить
# GitHub Actions) він дорівнює провалу.
# Рахуються лише рядки, що ПОЧИНАЮТЬСЯ з «ПРОПУСК». Старіші тести (R41-R47, R44fix, R64_editor та ін.) повідомляють про пропуск словом
# «пропущено» посеред рядка -- їх цей облік НЕ бачить (R105 їх не чіпав; список -- у claude/r105-result.md).
skip_exp=0; skip_unexp=0
EXPECTED_SKIP_RE='gcc нема|нема Pillow|PIL нема|Pillow|Tk/xvfb|numpy/scipy|tkinter|xvfb-run|немає PyYAML'
note_skips() {   # $1 -- назва тесту, $2 -- його повний вивід
	local name="$1" line
	while IFS= read -r line; do
		[ -n "$line" ] || continue
		if printf '%s' "$line" | grep -qE "$EXPECTED_SKIP_RE"; then
			skip_exp=$((skip_exp + 1)); echo "  ПРОПУСК (очікуваний, оточення) [$name]: ${line:0:150}"
		else
			skip_unexp=$((skip_unexp + 1)); echo "  ПРОПУСК (НЕОЧІКУВАНИЙ) [$name]: ${line:0:150}"
		fi
	done < <(printf '%s\n' "$2" | grep -E '^ПРОПУСК')
}
# R76B: вивід невдалого тесту для логу CI: усі рядки з ПРОВАЛ/FAIL/Traceback/Error (до 40) і хвіст (до 40 рядків). Раніше було лише tail -10, а
# його забивав шум (рядки «Супутники записані…»), тож причину падіння в CI було не видно. Формат рядків ok/ПРОВАЛ/ПРОПУЩЕНО не змінено.
show_fail() {
	local o="$1" m
	m="$(printf '%s\n' "$o" | grep -E 'ПРОВАЛ|FAIL|Traceback|Error|Exception' | head -40)"
	if [ -n "$m" ]; then echo "  --- рядки з помилками:"; printf '%s\n' "$m" | sed 's/^/  /'; fi
	echo "  --- хвіст виводу:"; printf '%s\n' "$o" | tail -40 | sed 's/^/  /'
}
for src in "$TESTS_DIR"/test_*.c; do
	name="$(basename "$src" .c)"
	if [ -n "$FILTER" ] && [[ "$name" != *"$FILTER"* ]]; then continue; fi

	if [ -z "${SRCS[$name]+x}" ]; then
		echo "ПРОПУЩЕНО $name -- немає запису в таблиці SRCS цього скрипта"
		skip_unexp=$((skip_unexp + 1))
		continue
	fi
	extra="${SRCS[$name]}"   # може бути порожнім -> самодостатній тест (лінкуємо лише сам файл)
	xflags="${XFLAGS[$name]:-}"

	variants=("")
	for d in "${SMSDIAG_TOO[@]}"; do [ "$d" = "$name" ] && variants+=("-DENABLE_SMS_DIAG"); done
	for d in "${UA_TOO[@]}"; do [ "$d" = "$name" ] && variants+=("-DLANGUAGE_BUILD_UKRAINIAN"); done
	for d in "${MICUR_TOO[@]}"; do [ "$d" = "$name" ] && variants+=("-DAES_TX_MI_CURRENT"); done
	for d in "${DIAGRX_TOO[@]}"; do [ "$d" = "$name" ] && variants+=("-DDMR_AES_DIAG_RX"); done
	for d in "${NOFIX_TOO[@]}"; do [ "$d" = "$name" ] && variants+=("-DAES_TX_PHASE_FIX_OFF" "-DDMR_AES_DIAG_RX -DAES_TX_PHASE_FIX_OFF"); done
	for vflag in "${variants[@]}"; do
		vname="$name"
		[ "$vflag" = "-DENABLE_SMS_DIAG" ] && vname="${name}_smsdiag"
		[ "$vflag" = "-DLANGUAGE_BUILD_UKRAINIAN" ] && vname="${name}_ua"
		[ "$vflag" = "-DAES_TX_MI_CURRENT" ] && vname="${name}_cur"
		[ "$vflag" = "-DDMR_AES_DIAG_RX" ] && vname="${name}_diag"
		[ "$vflag" = "-DAES_TX_PHASE_FIX_OFF" ] && vname="${name}_nofix"
		[ "$vflag" = "-DDMR_AES_DIAG_RX -DAES_TX_PHASE_FIX_OFF" ] && vname="${name}_diagnofix"
		bin="$BUILD/$vname"
		# shellcheck disable=SC2086
		if ! out="$("$CC" "${CFLAGS[@]}" $xflags $vflag "${INC[@]}" -o "$bin" "$src" $extra 2>&1)"; then
			fail=$((fail + 1))
			echo "ЗБІРКА ВПАЛА  $vname"
			printf "%s\n" "$out" | grep -E "error|undefined|rror" | head -12
			continue
		fi

		if out="$("$bin" 2>&1)"; then
			pass=$((pass + 1))
			echo "ok            $vname"
		else
			fail=$((fail + 1))
			echo "ПРОВАЛ        $vname"
			printf '%s\n' "$out" | tail -20
		fi
	done
done

# R65B: мутанти редактора списків прийому (codeplug.c, RXGROUP_EDIT_ENABLED) -- кожен мутант мусить провалити test_codeplug_rxgroup
if [ -z "$FILTER" ] || [[ "rxgroup" == *"$FILTER"* ]] || [[ "$FILTER" == *"rxgroup"* ]]; then
	if out="$(python3 "$TESTS_DIR/mutants_rxgroup.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            mutants_rxgroup (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        mutants_rxgroup (python)"; printf '%s\n' "$out" | tail -20
	fi
fi

# R66C: мутанти переміщення каналу в зоні (codeplugZoneMoveChannel) -- кожен мутант мусить провалити test_codeplug_zonemove
if [ -z "$FILTER" ] || [[ "zonemove" == *"$FILTER"* ]] || [[ "$FILTER" == *"zonemove"* ]]; then
	if out="$(python3 "$TESTS_DIR/mutants_zonemove.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            mutants_zonemove (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        mutants_zonemove (python)"; printf '%s\n' "$out" | tail -20
	fi
fi

# R58: діагностика пробудження -- мутаційна перевірка тестів (кожен мутант мусить провалити тест), розбір дампу tools/wake_diag.py і статична перевірка «усе під #if».
if [ -z "$FILTER" ] || [[ "wake" == *"$FILTER"* ]] || [[ "$FILTER" == *"wake"* ]]; then
	if out="$(python3 "$TESTS_DIR/mutants_wake.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            mutants_wake (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        mutants_wake (python)"; printf '%s\n' "$out" | tail -20
	fi
	if out="$(python3 "$TESTS_DIR/../tools/wake_diag.py" --selftest 2>&1)"; then
		pass=$((pass + 1)); echo "ok            wake_diag --selftest (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        wake_diag --selftest (python)"; show_fail "$out"
	fi
	if out="$(python3 "$TESTS_DIR/../tools/check_wake_ifdef.py" --selftest 2>&1 && python3 "$TESTS_DIR/../tools/check_wake_ifdef.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            check_wake_ifdef (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        check_wake_ifdef (python)"; show_fail "$out"
	fi
fi

if [ -z "$FILTER" ] || [[ "check_ccm_init" == *"$FILTER"* ]]; then
	# R10-fix5: кожна APRS-змінна в CCM має явну ініціалізацію (CCM при старті -- сміття): самоперевірка + перевірка коду прошивки
	if out="$(python3 "$TESTS_DIR/../tools/check_ccm_init.py" --selftest 2>&1 && python3 "$TESTS_DIR/../tools/check_ccm_init.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            check_ccm_init (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        check_ccm_init (python)"; printf '%s\n' "$out" | tail -20
	fi
fi

if [ -z "$FILTER" ] || [[ "check_terminology" == *"$FILTER"* ]]; then
	# R32 T1: у текстах і коді інструментів немає застарілих форм термінів (список -- на початку tools/check_terminology.py); прошивку й languages/ не чіпає
	if out="$(python3 "$TESTS_DIR/../tools/check_terminology.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            check_terminology (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        check_terminology (python)"; printf '%s\n' "$out" | tail -20
	fi
fi

if [ -z "$FILTER" ] || [[ "check_language_fields" == *"$FILTER"* ]]; then
	# R44-fix F3: мовні поля -- структура stringsTable_t проти УСІХ мовних файлів (кількість, склад, порядок, умови #if) у всіх комбінаціях прапорців
	if out="$(python3 "$TESTS_DIR/../tools/check_language_fields.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            check_language_fields (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        check_language_fields (python)"; printf '%s\n' "$out" | tail -20
	fi
fi

if [ -z "$FILTER" ] || [[ "check_menu_tables" == *"$FILTER"* ]]; then
	# R44-fix F3: menuFunctions[] і menuDataGlobal.data[] проти enum MENU_SCREENS у кожній конфігурації syntax_check.sh (R44: &menuDataCodeplug лягало на позицію 40 замість 46 -> HardFault)
	if out="$(python3 "$TESTS_DIR/../tools/check_menu_tables.py" --quiet 2>&1)"; then
		pass=$((pass + 1)); echo "ok            check_menu_tables (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        check_menu_tables (python)"; printf '%s\n' "$out" | tail -20
	fi
fi

if [ -z "$FILTER" ] || [[ "font_gen" == *"$FILTER"* ]]; then
	# R33 R1: tools/font_data.py (шрифти для точного передпоказу екрана в CPS) збігається з HX8353E_charset_UA.h
	if out="$(python3 "$TESTS_DIR/../tools/font_gen.py" --check 2>&1)"; then
		pass=$((pass + 1)); echo "ok            font_gen --check (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        font_gen --check (python)"; show_fail "$out"
	fi
fi

if [ -z "$FILTER" ] || [[ "aprs_icons_gen" == *"$FILTER"* ]]; then
	# R20 Ж2: tools/aprs_icons.txt коректний (24x24, без дублікатів/поодиноких пікселів, назви збігаються з aprsmode_ua.h), а aprs_icons.c і docs/aprs-icons.md не застаріли
	if out="$(python3 "$TESTS_DIR/../tools/aprs_icons_gen.py" --check 2>&1)"; then
		pass=$((pass + 1)); echo "ok            aprs_icons_gen --check (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        aprs_icons_gen --check (python)"; show_fail "$out"
	fi
fi

if [ -z "$FILTER" ] || [[ "test_aprs_capture aprs_offline" == *"$FILTER"* ]]; then
	# R4: самоперевірки інструментів запису «APRS проби» (без рації): розбір відповідей 0xB5 і
	# склеювання за номерами блоків; офлайн-аналіз еталонного WAV тим самим C-демодулятором.
	if out="$(python3 "$TESTS_DIR/../tools/test_aprs_capture.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_aprs_capture (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_aprs_capture (python)"; show_fail "$out"
	fi
	if out="$(python3 "$TESTS_DIR/../tools/aprs_offline.py" --selftest 2>&1)"; then
		pass=$((pass + 1)); echo "ok            aprs_offline --selftest (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        aprs_offline --selftest (python)"; show_fail "$out"
	fi
fi

# R24: знімок екрана і бекап кодплага (tools/cps_link.py, tools/cps_backup_info.py) -- підставна «рація», лише стандартна бібліотека.
if [ -z "$FILTER" ] || [[ "test_cps_link" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_cps_link.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_cps_link (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_cps_link (python)"; show_fail "$out"
	fi
fi

# AES-fix3: розбір дампу діагностики (tools/rxdiag.py) -- сирий hex LC/EMB + «наші» байти, на синтетичному дампі.
if [ -z "$FILTER" ] || [[ "test_rxdiag" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_rxdiag.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_rxdiag (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_rxdiag (python)"; show_fail "$out"
	fi
fi

# AES-fix4: пошук позицій бітів late-entry MI (tools/le_bitsearch.py, потрібен numpy) -- золоті вектори з C, синтетичні захоплення, шум, LFSR-зв'язок.
if [ -z "$FILTER" ] || [[ "test_le_bitsearch" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_le_bitsearch.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_le_bitsearch (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_le_bitsearch (python)"; show_fail "$out"
	fi
fi

# AES-fix5: перевірка гіпотези «MI у біті ambe_fr[0][0]» (tools/le_bit21.py, потрібен numpy) -- деперемежування на кадрі тиші, синтетичні моделі, шум.
if [ -z "$FILTER" ] || [[ "test_le_bit21" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_le_bit21.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_le_bit21 (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_le_bit21 (python)"; show_fail "$out"
	fi
fi

# R25: відновлення кодплага (tools/cps_restore.py) і перегляд (tools/codeplug_view.py) -- підставна «рація» з X 1/2/3.
if [ -z "$FILTER" ] || [[ "test_cps_restore" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_cps_restore.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_cps_restore (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_cps_restore (python)"; show_fail "$out"
	fi
fi

# R26: CSV-обмін кодплага (tools/cps_csv.py) -- оборотність байт-у-байт, кирилиця, кома/крапка, відмови до запису, імпорт через шлях відновлення.
if [ -z "$FILTER" ] || [[ "test_cps_csv" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_cps_csv.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_cps_csv (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_cps_csv (python)"; show_fail "$out"
	fi
fi

# R26 V2/V3 + APRS-unify L5.4 (бікон/шумодав/позивний з ПК): контакти-редактор, темна тема, tools/aprs_beacon_cfg.py; CPS-shell: tools/cps_ui (дерево розділів); CPS-doc: кодплаг як документ (test_cps_doc); CPS-fix2 + етап 3: редактори списків прийому, зон і каналів (test_cps_edit); CPS-fix3: сітка символів APRS, злита панель APRS, ключ AES у каналі (test_cps_fix3); R-next: загальні налаштування, VFO, DTMF (test_rnext); R28: теми екрана рації й каскадне видалення APRS-слота (test_r28); R30: файл теми .gtm, область custom-data у бекапі/відновленні/файлі налаштувань (test_r30); R31: ключі AES у бекапі/відновленні, база позивних DMR ID, охоронець меж запису (test_r31); R32: перевірка термінології, розбір джерел бази з tools/testdata, виміри фаз запису й передача образу в страхову копію, склад архіву (test_r32); R33: зразок ContactLists, лічильники бази, таблиця записів, розділ «Контакти», шрифти прошивки, точний передпоказ екрана з перевіркою розкладки й мовних рядків за вихідним кодом (test_r33); R34: байт 0xFF у назвах -- мала «я» (test_r34); R35: супутники TLE, картинка заставки, мелодія вмикання, вилучення блока custom-data, вікно rawarea охоронця (test_r35; формат звіряється з прошивкою gcc). R36: вікно CPS без обрізання тексту на 1024x768 і 1920x1080, межі з пам'яттю, копіювання за кодом клавіші на будь-якій розкладці, контекстні меню, таблиці за вмістом, хвіст 0x00 у назвах (test_r36; зонд tools/layout_probe.py). R37: стан і ущільнення області custom-data, обрив запису на кожному кроці, вікно customdata охоронця, хук нестачі місця (test_r37). Логіка -- у будь-якому python3; віджети Tk -- лише з tkinter + xvfb-run (інакше цю частину
# тест сам пропускає й каже про це).
# R59: «Роумінг» у CPS -- прапорець каналу, колонка CSV «Roam», блок налаштувань №15, попередження, безпечний запис, 38 мутантів (test_r59); розділ і колонка в Tk (test_r59_ui).
# R79B: як у CI, Tk-тести йдуть лише з шрифтами DejaVu + Liberation (інший набір шрифтів дає інші ширини, і регресії розкладки R76B/R79 не ловились
# до CI). Якщо обох тек нема або FONTCONFIG_FILE уже заданий -- лишається як є.
if [ -z "${FONTCONFIG_FILE:-}" ] && [ -d /usr/share/fonts/truetype/dejavu ] && [ -d /usr/share/fonts/truetype/liberation ]; then
	FCDIR="$(mktemp -d)"
	printf '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig><dir>/usr/share/fonts/truetype/dejavu</dir><dir>/usr/share/fonts/truetype/liberation</dir><cachedir>%s/cache</cachedir></fontconfig>\n' "$FCDIR" > "$FCDIR/fonts.conf"
	export FONTCONFIG_FILE="$FCDIR/fonts.conf"
fi
for T in test_contact_edit test_gui_theme test_aprs_beacon_cfg test_cps_ui test_cps_doc test_cps_edit test_cps_fix3 test_rnext test_r28 test_r30 test_r31 test_r32 test_r33 test_r34 test_r35 test_r36 test_r37 test_r41 test_r42 test_r43 test_r44 test_r44fix test_r46 test_r47 test_r50 test_r50fix test_r51 test_r53 test_r53_ui test_r54 test_r54_ui test_r55 test_r55_ui test_r56 test_r56_ui test_r59 test_r59_ui test_aes_key_name test_r64 test_r64_editor test_r65 test_r65b test_r66 test_r70 test_r71 test_r73 test_r74 test_r75 test_r76 test_r77a test_r78 test_r81 test_r79 test_r88 test_r91a test_r91b test_r91c test_r92 test_r93 test_r82 test_r94a test_r94b test_r94d test_r95 test_r96 test_r97 test_r98 test_r98fix1 test_r98fix2 test_r98fix3 test_r98fix4 test_r98fix5 test_r98fix6 test_r98fix7 test_r98fix8 test_r98fix9 test_r98fix10 test_r98fix11 test_r98fix12 test_r98fix13 test_r98msg1 test_r98fix15 test_r99tone test_r100tone test_r100cps test_r101aprsmsg test_r107cps test_r107usb test_r108flush test_r108keys test_r109release test_r110tonestep; do
	if [ -z "$FILTER" ] || [[ "$T" == *"$FILTER"* ]]; then
		PYTK=""
		for cand in python3 python3.12 python3.11 python3.10 python3.13; do
			if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import tkinter" 2>/dev/null; then PYTK="$cand"; break; fi
		done
		if [ -n "$PYTK" ] && command -v xvfb-run >/dev/null 2>&1; then
			# R51: test_r50fix проходить 6 сценаріїв шрифт × масштаб по всіх розділах (≈125 с на вільній машині, більше під навантаженням) -- ліміт для нього 900 с
			TMO=240; [ "$T" = "test_r50fix" ] && TMO=900; [ "$T" = "test_r53_ui" ] && TMO=600; [ "$T" = "test_r98fix13" ] && TMO=900; [ "$T" = "test_r98fix15" ] && TMO=900; [ "$T" = "test_r100cps" ] && TMO=600
			out="$(timeout "$TMO" xvfb-run -a "$PYTK" -B "$TESTS_DIR/../tools/$T.py" 2>&1)"; rc=$?
			if [ "$rc" -eq 0 ]; then
				pass=$((pass + 1)); echo "ok            $T (python + Tk під xvfb)"; note_skips "$T" "$out"
			else
				fail=$((fail + 1)); echo "ПРОВАЛ        $T (python + Tk під xvfb)"; [ "$rc" -eq 124 ] && echo "  (перевищено ліміт часу ${TMO} с)"; show_fail "$out"
			fi
		else
			if out="$(python3 -B "$TESTS_DIR/../tools/$T.py" 2>&1)"; then
				pass=$((pass + 1)); notk=$((notk + 1)); echo "ok            $T (python; частину з Tk пропущено -- нема tkinter або xvfb-run)"; note_skips "$T" "$out"
			else
				fail=$((fail + 1)); echo "ПРОВАЛ        $T (python)"; show_fail "$out"
			fi
		fi
	fi
done

# Python-самоперевірка декодера ефірних записів (tools/dmr_data_rx.py). Потрібні numpy+scipy;
# якщо їх немає (напр. мінімальний CI) -- пропускаємо з попередженням, а не валимо прогін.
if [ -z "$FILTER" ] || [[ "test_dmr_data_rx" == *"$FILTER"* ]]; then
	if python3 -c "import numpy, scipy" 2>/dev/null; then
		if out="$(python3 "$TESTS_DIR/../tools/test_dmr_data_rx.py" 2>&1)"; then
			pass=$((pass + 1)); echo "ok            test_dmr_data_rx (python)"; note_skips "test_dmr_data_rx" "$out"
		else
			fail=$((fail + 1)); echo "ПРОВАЛ        test_dmr_data_rx (python)"
			printf '%s\n' "$out" | tail -20
		fi
	else
		echo "ПРОПУЩЕНО     test_dmr_data_rx (python) -- немає numpy/scipy"
		skip_exp=$((skip_exp + 1))
	fi
fi

# R102: «Тон-відгук» без сторожа, поріг, свіже відкриття, блок 19 v3 (tools/test_r102tone.py: справжній tone_reply.c на хості, дві рації, мутанти). Без Tk, потрібен gcc.
# Окремим блоком (а не в списку вище), щоб патчі R101 і R102 застосовувались у будь-якому порядку без конфлікту.
if [ -z "$FILTER" ] || [[ "test_r102tone" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_r102tone.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_r102tone (python)"; note_skips "test_r102tone" "$out"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_r102tone (python)"; show_fail "$out"
	fi
fi

# R103: «Тон-відгук» -- після кінця/скасування тону екран каналу/VFO перемальовується без відліку «0» (tools/test_r103tone.py: справжній tone_reply.c на хості, модель екрана, мутанти).
# Окремим блоком (а не в списку вище) -- як R101/R102, щоб патчі застосовувались у будь-якому порядку без конфлікту. Без Tk, потрібен gcc.
if [ -z "$FILTER" ] || [[ "test_r103tone" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_r103tone.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_r103tone (python)"; note_skips "test_r103tone" "$out"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_r103tone (python)"; show_fail "$out"
	fi
fi

# R106-SMSSTORE: сховище SMS у власному кільці секторів флешу (tools/test_r106smsstore.py: справжній sms_flash_store.c з моделлю NOR -- обриви,
# пошкодження, знос, мутанти; справжній dmr_sms.c через tests/test_dmr_sms_flash.c -- міграція, політика запису, мутанти). Без Tk, потрібен gcc.
# Окремим блоком (як R101..R103), щоб патчі застосовувались у будь-якому порядку без конфлікту.
if [ -z "$FILTER" ] || [[ "test_r106smsstore" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_r106smsstore.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_r106smsstore (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_r106smsstore (python)"; show_fail "$out"
	fi
fi

# R80: README.md -- відносні посилання, якорі й зображення (docs/img, до 300 КБ), без слова «виправлено» (tools/check_readme_links.py, самоперевірка всередині).
if [ -z "$FILTER" ] || [[ "check_readme_links" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/check_readme_links.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            check_readme_links (python)"; note_skips "check_readme_links" "$out"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        check_readme_links (python)"; show_fail "$out"
	fi
fi

echo
# R105: підсумок пропусків; у CI неочікуваний пропуск -- провал (тест, що мовчки пропустився, не «пройдено»)
echo "Пропущено перевірок: очікуваних (немає gcc/Pillow/numpy/Tk у оточенні) $skip_exp, неочікуваних $skip_unexp"
if [ "$skip_unexp" -gt 0 ]; then
	if [ "${CI:-}" = "true" ]; then
		echo "ПРОВАЛ        режим CI: неочікуваних пропусків $skip_unexp -- кожен пропуск має бути прибраний або пояснений (див. рядки «ПРОПУСК (НЕОЧІКУВАНИЙ)» вище)"
		fail=$((fail + 1))
	else
		echo "УВАГА: неочікуваних пропусків $skip_unexp (у CI це був би провал)"
	fi
fi
if [ "$skip_exp" -gt 0 ]; then echo "УВАГА: очікуваних пропусків $skip_exp -- у оточенні бракує інструмента; це не прогін як у CI"; fi
echo "Тестів пройдено: $pass, провалено: $fail"
# R98-FIX14: мовчазний пропуск Tk-частини -- видно в підсумку (CI має xvfb і tkinter; без них частину перевірок не виконано)
if [ "$notk" -gt 0 ]; then echo "УВАГА: у $notk тестах Tk-частину пропущено (нема tkinter або xvfb-run) -- це не прогін як у CI"; fi
[ "$fail" -eq 0 ] || exit 1
exit 0
