# -*- coding: utf-8 -*-
"""R96: фільтр токенів для тестів, що порівнюють препроцесований текст із комітами-базами (test_r46, test_r47, test_r78).
Вирізає лише законні R96-вставки (мертвий код у не-UA збірках / код під LANGUAGE_BUILD_UKRAINIAN), щоб решта порівнянь лишилась строгою:
  - прототип uiDrawTickMark (uiUtilities.h, ENABLE_AES; функція в образ не потрапляє -- sha AES-збірки не змінився);
  - QUICKKEY_SLOT_UNWRITTEN у quickkeyIsEmpty() (codeplug.c) і в диспетчері швидких клавіш (applicationMain.c): у не-UA збірці це `(0)`, в UA -- перевірка 0xFFFF.
R98-FIX2 Л (той самий принцип -- лише прототипи, без коду в чужих файлах):
  - keypadAlphaPreviewMap (keyboard.h, LANGUAGE_BUILD_UKRAINIAN) і uiSmsKeyHintMap (uiSmsKeys.h) -- підказка літер у назві каналу.
R98-FIX3 Б: стоковий крок шумодава ▲/▼ екрана каналу винесено в static inline (always_inline) channelSquelchStep(dir) -- для порівняння з базою виклики
channelSquelchStep(1)/(-1) розгортаються назад у стокові блоки, а визначення функції вирізається (байт-у-байт образу перевіряє sha типової збірки)."""
import re

_PATS = (
    (b"void uiDrawTickMark(int16_t cx, int16_t cy, themeItem_t fg, bool focused);", b""),
    (b"void uiDrawTickMark(int16_t cx, int16_t cy, themeItem_t fg, _Bool focused);", b""),
    (b"(data == 0x8000) || (0) ||", b"(data == 0x8000) ||"),
    (b"(data == 0x8000) || ((data) == 0xFFFF) ||", b"(data == 0x8000) ||"),
    (b"if ((0)) { keyFunction = 0; }", b""),
    (b"if (((keyFunction) == 0xFFFF)) { keyFunction = 0; }", b""),
    (b"const char *keypadAlphaPreviewMap(int *idx);", b""),
    (b"void uiSmsKeyHintMap(const char *map, int idx, int16_t x, int16_t y);", b""),
)


_SQL_DEF = re.compile(rb"static inline __attribute__\(\(always_inline\)\) void channelSquelchStep\(int dir\) \{ (.*?) if \(dir > 0\) \{ (if \(currentChannelData->sql < CODEPLUG_MAX_VARIABLE_SQUELCH\) \{ currentChannelData->sql\+\+; \}) \} else \{ (if \(currentChannelData->sql > CODEPLUG_MIN_VARIABLE_SQUELCH\) \{ currentChannelData->sql--; \}) \} (.*?uiChannelModeUpdateScreen\(0\);) \}")


def strip_r98fix3(j):
    m = _SQL_DEF.search(j)
    if not m:
        return j
    pre, inc, dec, post = m.group(1), m.group(2), m.group(3), m.group(4)
    j = j[:m.start()] + j[m.end():]
    j = j.replace(b"channelSquelchStep(1);", pre + b" " + inc + b" " + post)
    j = j.replace(b"channelSquelchStep(-1);", pre + b" " + dec + b" " + post)
    return b" ".join(j.split())


def strip_r96(raw):
    j = b" ".join(raw.split())
    for a, b in _PATS:
        j = j.replace(a, b)
    return strip_r98fix3(j)
