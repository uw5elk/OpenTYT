#!/bin/bash
# R105-RELDOCS: звірка контрольної суми ТИПОВОЇ збірки (без жодних прапорців) з еталоном.
#
# Навіщо. Типова збірка -- це НЕ стоковий OpenGD77, а базовий образ форку з безумовними виправленнями інтерфейсу й хуками
# кодека. Правило проєкту: додавання нових функцій під прапорцями ENABLE_* не змінює її жодного байта. Цей скрипт перевіряє
# саме це: збирає без прапорців, рахує sha256 файла build/openuv380-10w.bin і звіряє з рядком файла tools/default_build.sha256
# для ТОГО САМОГО компілятора (sha залежить від версії arm-none-eabi-gcc, тож еталон -- на кожну версію окремо).
#
# Використання (з будь-якого каталогу):
#   tools/check_default_build.sh              зібрати (make clean + make GITVERSION=x) і звірити
#   tools/check_default_build.sh --no-build   звірити вже наявний build/openuv380-10w.bin (зібраний з GITVERSION=x БЕЗ прапорців)
#   tools/check_default_build.sh --update     зібрати й ДРУКУВАТИ рядок для default_build.sha256 (файл не змінює)
# Коди виходу: 0 -- збігається; 1 -- НЕ збігається (типова збірка змінилась); 2 -- для цього компілятора еталона нема
# (не помилка збірки; додайте рядок з --update, якщо зміна навмисна й перевірена); 3 -- збірка не вдалась.
# ЗАСТЕРЕЖЕННЯ: чистить і перезбирає каталог build/ (крім режиму --no-build).

HERE=$(cd "$(dirname "$0")/.." && pwd)
REF="$HERE/tools/default_build.sha256"
MODE=${1:-}
cd "$HERE" || exit 3
CC=${CROSS:-arm-none-eabi-}gcc
GCCV=$($CC --version 2>/dev/null | head -1 | sed 's/^[^)]*) *//')
[ -n "$GCCV" ] || { echo "check_default_build: компілятор $CC не знайдено"; exit 3; }

if [ "$MODE" != "--no-build" ]; then
    export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1700000000}
    make clean >/dev/null 2>&1
    make -j"$(nproc 2>/dev/null || echo 2)" GITVERSION=x >"$HERE/check_default_build.log" 2>&1 || {
        echo "check_default_build: збірка не вдалась (див. $HERE/check_default_build.log)"; exit 3; }
    rm -f check_default_build.log
fi
BIN=build/openuv380-10w.bin
[ -f "$BIN" ] || { echo "check_default_build: нема $BIN"; exit 3; }
SHA=$(sha256sum "$BIN" | cut -c1-64)
SIZE=$(stat -c %s "$BIN")
echo "типова збірка: sha256=$SHA розмір=$SIZE компілятор=$GCCV"
if [ "$MODE" = "--update" ]; then
    echo "рядок для tools/default_build.sha256:"
    echo "$SHA  $SIZE  $GCCV"
    exit 0
fi
LINE=$(grep -v '^#' "$REF" 2>/dev/null | grep -F -- "  $GCCV" | head -1)
if [ -z "$LINE" ]; then
    echo "check_default_build: у $REF нема еталона для компілятора «$GCCV» (не помилка; додайте рядок з --update)"
    exit 2
fi
EXP=$(echo "$LINE" | cut -d' ' -f1)
if [ "$EXP" = "$SHA" ]; then
    echo "check_default_build: ЗБІГАЄТЬСЯ з еталоном"
    exit 0
fi
echo "check_default_build: НЕ ЗБІГАЄТЬСЯ -- еталон $EXP, зараз $SHA: типова збірка змінилась. Якщо зміна навмисна (безумовне виправлення), перерахуйте еталон (--update) і поясніть у STATUS.md."
exit 1
