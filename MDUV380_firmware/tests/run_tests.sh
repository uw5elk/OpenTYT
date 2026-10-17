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
	[test_dmr_sms_confirmed]=""       # самодостатній: CRC9 + розкладка CONFIRMED-блока
	[test_call_replay]="$APP/source/functions/callReplay.c"   # лише ЧИСТА кільцева логіка -- callReplayPlayback.c (codec/sound/trx/FreeRTOS) сюди навмисно не тягнеться
	[test_dmr_sms_fix]="$APP/source/functions/dmr_sms_fix.c $APP/source/functions/dmr_sms_pdu.c $APP/source/functions/dmr_sms_text.c"   # fix7: корекція трибітів rate-3/4
	[test_dmr_sms_replay]="$APP/source/functions/dmr_sms.c $APP/source/functions/dmr_sms_fix.c $APP/source/functions/dmr_sms_pdu.c $APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # diag5: СПРАВЖНІЙ збирач SMS, залізо -- заглушки в тесті
	[test_dmr_sms_shift]="$APP/source/functions/dmr_sms_text.c $APP/source/functions/dmr_sms_pdu.c $APP/source/functions/dmr_sms_fix.c $APP/source/crypto/dmr_aes.c"   # ui5: кирилиця від Z3DMR (зсув старших байтів UTF-16)
	[test_dmr_sms_store]="$APP/source/functions/dmr_sms.c $APP/source/functions/dmr_sms_fix.c $APP/source/functions/dmr_sms_pdu.c $APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # ui6: сховище v3 і перетворення v2 -> v3
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
	[test_aes_resync]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # AES-fix1: СПРАВЖНІЙ dmr_aes_hook.c (#include) -- ресинхронізація MI, захист від хибного CRC4, обидві конвенції late entry; залізо -- заглушки в тесті
	[test_aes_txphase]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # AES-fix2: СПРАВЖНІЙ dmr_aes_hook.c (#include) -- фаза шифрування TX за ефіром при тихих burst-ах (SILENCE_AUDIO), межа 18 кадрів, B3 тиша на RX; черга кодувальника й залізо -- модель у тесті
	[test_aes_rawdiag]="$APP/source/crypto/dmr_aes.c $APP/source/functions/dmr_sms_text.c"   # AES-fix3: СПРАВЖНІЙ dmr_aes_hook.c (#include, -DDMR_AES_DIAG_RX) -- розкладка дампу сирих LC/EMB, дедуп, блок «наші байти»
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
	[test_dmr_rctl_stock]="-DENABLE_DMR_DATA"   # R21 З2: тест читає чергу так, як драйвер (functions/dmr_data.h)
	[test_aprs_probe_dsp]="-DENABLE_APRS_RX_PROBE"
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
	[test_dmr_sms_store]="$FW_INCS -DUSE_HAL_DRIVER -DSTM32F405xx -DPLATFORM_MDUV380 -DPLATFORM_VARIANT_UV380_PLUS_10W -DNDEBUG -DLANGUAGE_BUILD_UKRAINIAN -Wno-unused-parameter -Wno-sign-compare -Wno-unused-function -Wno-unused-variable"
)

# cleanup1 (2026-10-05): тести, які ще раз збираються з -DENABLE_SMS_DIAG (окремий бінарник
# <назва>_smsdiag) -- діагностику SMS у CI не вмикають, тож інакше її код ніхто б не ганяв.
SMSDIAG_TOO=(test_dmr_sms_replay)
# ui4: тести, які ще раз збираються з -DLANGUAGE_BUILD_UKRAINIAN (бінарник <назва>_ua) --
# кириличні розкладки існують лише в українській збірці.
UA_TOO=(test_sms_multitap)
# AES-fix1: тест ресинхронізації збирається ще й зі збіркою-кандидатом AES_TX_MI_CURRENT (бінарник <назва>_cur)
# та з діагностикою прийому DMR_AES_DIAG_RX (<назва>_diag) -- інакше ні цей режим, ні діагностичний код у CI не компілювалися б.
MICUR_TOO=(test_aes_resync test_aes_txphase)
DIAGRX_TOO=(test_aes_resync test_aes_txphase test_aes_rawdiag)
# AES-fix2: ІНВЕРТОВАНІ збірки з вимкненим фіксом фази TX (-DAES_TX_PHASE_FIX_OFF): тест має ЗНАЙТИ зсув (ловить дефект);
# і те саме разом з діагностикою (<назва>_diagnofix) -- дамп фази мусить показати k=3, а не 0.
NOFIX_TOO=(test_aes_txphase)

rm -rf "$BUILD" && mkdir -p "$BUILD"

pass=0; fail=0
for src in "$TESTS_DIR"/test_*.c; do
	name="$(basename "$src" .c)"
	if [ -n "$FILTER" ] && [[ "$name" != *"$FILTER"* ]]; then continue; fi

	if [ -z "${SRCS[$name]+x}" ]; then
		echo "ПРОПУЩЕНО $name -- немає запису в таблиці SRCS цього скрипта"
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

if [ -z "$FILTER" ] || [[ "check_ccm_init" == *"$FILTER"* ]]; then
	# R10-fix5: кожна APRS-змінна в CCM має явну ініціалізацію (CCM при старті -- сміття): самоперевірка + перевірка коду прошивки
	if out="$(python3 "$TESTS_DIR/../tools/check_ccm_init.py" --selftest 2>&1 && python3 "$TESTS_DIR/../tools/check_ccm_init.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            check_ccm_init (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        check_ccm_init (python)"; printf '%s\n' "$out" | tail -20
	fi
fi

if [ -z "$FILTER" ] || [[ "aprs_icons_gen" == *"$FILTER"* ]]; then
	# R20 Ж2: tools/aprs_icons.txt коректний (24x24, без дублікатів/поодиноких пікселів, назви збігаються з aprsmode_ua.h), а aprs_icons.c і docs/aprs-icons.md не застаріли
	if out="$(python3 "$TESTS_DIR/../tools/aprs_icons_gen.py" --check 2>&1)"; then
		pass=$((pass + 1)); echo "ok            aprs_icons_gen --check (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        aprs_icons_gen --check (python)"; printf '%s\n' "$out" | tail -10
	fi
fi

if [ -z "$FILTER" ] || [[ "test_aprs_capture aprs_offline" == *"$FILTER"* ]]; then
	# R4: самоперевірки інструментів запису «APRS проби» (без рації): розбір відповідей 0xB5 і
	# склеювання за номерами блоків; офлайн-аналіз еталонного WAV тим самим C-демодулятором.
	if out="$(python3 "$TESTS_DIR/../tools/test_aprs_capture.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_aprs_capture (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_aprs_capture (python)"; printf '%s\n' "$out" | tail -10
	fi
	if out="$(python3 "$TESTS_DIR/../tools/aprs_offline.py" --selftest 2>&1)"; then
		pass=$((pass + 1)); echo "ok            aprs_offline --selftest (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        aprs_offline --selftest (python)"; printf '%s\n' "$out" | tail -10
	fi
fi

# R24: знімок екрана і бекап кодплуга (tools/cps_link.py, tools/cps_backup_info.py) -- підставна «рація», лише стандартна бібліотека.
if [ -z "$FILTER" ] || [[ "test_cps_link" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_cps_link.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_cps_link (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_cps_link (python)"; printf '%s\n' "$out" | tail -10
	fi
fi

# AES-fix3: розбір дампу діагностики (tools/rxdiag.py) -- сирий hex LC/EMB + «наші» байти, на синтетичному дампі.
if [ -z "$FILTER" ] || [[ "test_rxdiag" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_rxdiag.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_rxdiag (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_rxdiag (python)"; printf '%s\n' "$out" | tail -10
	fi
fi

# R25: відновлення кодплуга (tools/cps_restore.py) і перегляд (tools/codeplug_view.py) -- підставна «рація» з X 1/2/3.
if [ -z "$FILTER" ] || [[ "test_cps_restore" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_cps_restore.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_cps_restore (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_cps_restore (python)"; printf '%s\n' "$out" | tail -10
	fi
fi

# R26: CSV-обмін кодплуга (tools/cps_csv.py) -- оборотність байт-у-байт, кирилиця, кома/крапка, відмови до запису, імпорт через шлях відновлення.
if [ -z "$FILTER" ] || [[ "test_cps_csv" == *"$FILTER"* ]]; then
	if out="$(python3 -B "$TESTS_DIR/../tools/test_cps_csv.py" 2>&1)"; then
		pass=$((pass + 1)); echo "ok            test_cps_csv (python)"
	else
		fail=$((fail + 1)); echo "ПРОВАЛ        test_cps_csv (python)"; printf '%s\n' "$out" | tail -10
	fi
fi

# R26 V2/V3: контакти-редактор і темна тема. Логіка й палітра -- у будь-якому python3; віджети Tk -- лише з tkinter + xvfb-run (інакше цю частину
# тест сам пропускає й каже про це).
for T in test_contact_edit test_gui_theme; do
	if [ -z "$FILTER" ] || [[ "$T" == *"$FILTER"* ]]; then
		PYTK=""
		for cand in python3 python3.12 python3.11 python3.10 python3.13; do
			if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import tkinter" 2>/dev/null; then PYTK="$cand"; break; fi
		done
		if [ -n "$PYTK" ] && command -v xvfb-run >/dev/null 2>&1; then
			if out="$(timeout 240 xvfb-run -a "$PYTK" -B "$TESTS_DIR/../tools/$T.py" 2>&1)"; then
				pass=$((pass + 1)); echo "ok            $T (python + Tk під xvfb)"
			else
				fail=$((fail + 1)); echo "ПРОВАЛ        $T (python + Tk під xvfb)"; printf '%s\n' "$out" | tail -10
			fi
		else
			if out="$(python3 -B "$TESTS_DIR/../tools/$T.py" 2>&1)"; then
				pass=$((pass + 1)); echo "ok            $T (python; частину з Tk пропущено -- нема tkinter або xvfb-run)"
			else
				fail=$((fail + 1)); echo "ПРОВАЛ        $T (python)"; printf '%s\n' "$out" | tail -10
			fi
		fi
	fi
done

# Python-самоперевірка декодера ефірних записів (tools/dmr_data_rx.py). Потрібні numpy+scipy;
# якщо їх немає (напр. мінімальний CI) -- пропускаємо з попередженням, а не валимо прогін.
if [ -z "$FILTER" ] || [[ "test_dmr_data_rx" == *"$FILTER"* ]]; then
	if python3 -c "import numpy, scipy" 2>/dev/null; then
		if out="$(python3 "$TESTS_DIR/../tools/test_dmr_data_rx.py" 2>&1)"; then
			pass=$((pass + 1)); echo "ok            test_dmr_data_rx (python)"
		else
			fail=$((fail + 1)); echo "ПРОВАЛ        test_dmr_data_rx (python)"
			printf '%s\n' "$out" | tail -20
		fi
	else
		echo "ПРОПУЩЕНО     test_dmr_data_rx (python) -- немає numpy/scipy"
	fi
fi

echo
echo "Тестів пройдено: $pass, провалено: $fail"
[ "$fail" -eq 0 ] || exit 1
exit 0
