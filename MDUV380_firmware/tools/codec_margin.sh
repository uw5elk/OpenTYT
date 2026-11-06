#!/bin/bash
# R62A: запас (або перевищення) коду до фіксованої адреси кодека 0x0807537C, у байтах.
#
# Навіщо. Блок кодека AMBE лежить за ЖОРСТКОЮ адресою (STM32F405VGTX_FLASH.ld: «. = ABSOLUTE(0x807537C)»), тож усе, що лінкер ставить
# до нього (.isr_vector, .text, .rodata, ...), мусить вміститись. Коли не вміщається, ld зупиняється з
# «cannot move location counter backwards (from XXXXXXXX to 0807537c)» і не пише ні .bin, ні повної .map -- а коли вміщається,
# запас видно лише в .map (рядок *fill* під .codec_bin_section_1). Цей скрипт дає ОДНЕ число в обох випадках.
#
# Як. З об'єктів, які вже зібрав `make`, робиться ДОДАТКОВЕ лінкування у файл $BUILD/codec-margin.elf за тим самим Makefile, але з
# ТИМЧАСОВОЮ копією лінкер-скрипта, де «. = ABSOLUTE(0x807537C)» замінено на «__pre_codec = .» (позиція лічильника адрес без підгонки до
# кодека). Запас = 0x0807537C - __pre_codec; мінус -- перевищення. Справжні build/openuv380-10w.{elf,bin,hex,map} і сам лінкер-скрипт
# НЕ чіпаються; допоміжні файли в кінці видаляються (інакше їх підхопили б glob-и build/*.elf, build/*.map в артефактах).
#
# Використання (з каталогу MDUV380_firmware, після `make`, навіть невдалого лінкування):
#   tools/codec_margin.sh [підпис]
# Змінні: BUILD (типово build), TARGET (типово openuv380-10w), LD (типово STM32F405VGTX_FLASH.ld). Код виходу завжди 0 -- це лише інформація, крок CI не повинен ламати збірку.

BUILD=${BUILD:-build}
TARGET=${TARGET:-openuv380-10w}
CROSS=${CROSS:-arm-none-eabi-}
LABEL=${1:-$TARGET}
CODEC=$((0x0807537C))
LD=${LD:-STM32F405VGTX_FLASH.ld}   # R63C: для збірки з ENABLE_RODATA_AFTER_CODEC=1 викликати з LD=STM32F405VGTX_FLASH_RODATA_AFTER_CODEC.ld
MARGIN_TARGET=codec-margin

TMP=$(mktemp -d "${TMPDIR:-/tmp}/codec_margin.XXXXXX") || { echo "codec_margin: не вдалося створити тимчасовий каталог"; exit 0; }
cleanup() {
    rm -rf "$TMP"
    rm -f "$BUILD/$MARGIN_TARGET.elf" "$BUILD/$MARGIN_TARGET.map" "$BUILD/$MARGIN_TARGET.bin" "$BUILD/$MARGIN_TARGET.hex"
}
trap cleanup EXIT

say() {
    echo "$1"
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then echo "$1" >> "$GITHUB_STEP_SUMMARY"; fi
}

[ -f "$LD" ] || { say "codec_margin: нема $LD (запускати з MDUV380_firmware)"; exit 0; }

# Тимчасова копія лінкер-скрипта: єдина зміна -- рядок із ABSOLUTE.
sed 's|^\([[:space:]]*\)\. = ABSOLUTE(0x807537C) ;|\1__pre_codec = . ;|' "$LD" > "$TMP/margin.ld"
if ! grep -q '^[[:space:]]*__pre_codec = \. ;' "$TMP/margin.ld" || cmp -s "$LD" "$TMP/margin.ld"; then
    say "codec_margin: у $LD не знайдено рядка '. = ABSOLUTE(0x807537C) ;' -- скрипт треба поправити разом зі змінами лінкер-скрипта"
    exit 0
fi

MK=(make "BUILD=$BUILD" "TARGET=$MARGIN_TARGET" "LDSCRIPT=$TMP/margin.ld" "$BUILD/$MARGIN_TARGET.elf")

# Якщо об'єкти не зібрані (збій компіляції), make почав би компілювати наново -- тоді нічого не міряємо.
if "${MK[@]}" -n 2>/dev/null | grep -q -- ' -c '; then
    say "codec_margin [$LABEL]: об'єкти не зібрані (збій компіляції?) -- запас не вимірюється"
    exit 0
fi

if ! "${MK[@]}" > "$TMP/link.log" 2>&1; then
    say "codec_margin [$LABEL]: допоміжне лінкування не вдалося:"
    tail -n 5 "$TMP/link.log"
    exit 0
fi

PRE=$("${CROSS}nm" "$BUILD/$MARGIN_TARGET.elf" 2>/dev/null | awk '$3=="__pre_codec"{print $1}')
if [ -z "$PRE" ]; then
    say "codec_margin [$LABEL]: символу __pre_codec нема в допоміжному .elf"
    exit 0
fi
PRE=$((16#$PRE))
DIFF=$((CODEC - PRE))

if [ "$DIFF" -ge 0 ]; then
    say "Запас до кодека 0x0807537C [$LABEL]: +$DIFF Б (код закінчується на $(printf '0x%08X' "$PRE"))"
else
    say "ПЕРЕВИЩЕННЯ над кодеком 0x0807537C [$LABEL]: $((-DIFF)) Б (код закінчується на $(printf '0x%08X' "$PRE"))"
    echo "  (повідомлення ld «cannot move location counter backwards (from ...)» у логу Build може показувати інше число: в одному локальному вимірі (gcc 13.2.1) ld дав 9348 проти 9316 тут; причину різниці в 32 Б не з'ясовано, остаточне -- ld)"
fi

# Перехресна перевірка за справжньою .map (є лише коли основне лінкування вдалось): *fill* під .codec_bin_section_1 -- це той самий запас.
MAP="$BUILD/$TARGET.map"
if [ -f "$MAP" ] && grep -q '^\.codec_bin_section_1' "$MAP"; then
    FILL=$(awk '/^\.codec_bin_section_1/{f=1;next} f&&/\*fill\*/{print $3;exit} f&&/^\.[a-z]/{exit}' "$MAP")
    if [ -n "$FILL" ]; then
        echo "  перехресна перевірка за $MAP: *fill* = $((FILL)) Б ($( [ "$((FILL))" -eq "$DIFF" ] && echo збігається || echo РОЗБІГАЄТЬСЯ ))"
    else
        echo "  перехресна перевірка: у $MAP під .codec_bin_section_1 нема *fill* (запас 0 або карта неповна)"
    fi
fi
exit 0
