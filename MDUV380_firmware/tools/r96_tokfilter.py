# -*- coding: utf-8 -*-
"""R96: фільтр токенів для тестів, що порівнюють препроцесований текст із комітами-базами (test_r46, test_r47, test_r78).
Вирізає лише законні R96-вставки (мертвий код у не-UA збірках / код під LANGUAGE_BUILD_UKRAINIAN), щоб решта порівнянь лишилась строгою:
  - прототип uiDrawTickMark (uiUtilities.h, ENABLE_AES; функція в образ не потрапляє -- sha AES-збірки не змінився);
  - QUICKKEY_SLOT_UNWRITTEN у quickkeyIsEmpty() (codeplug.c) і в диспетчері швидких клавіш (applicationMain.c): у не-UA збірці це `(0)`, в UA -- перевірка 0xFFFF."""
import re

_PATS = (
    (b"void uiDrawTickMark(int16_t cx, int16_t cy, themeItem_t fg, bool focused);", b""),
    (b"void uiDrawTickMark(int16_t cx, int16_t cy, themeItem_t fg, _Bool focused);", b""),
    (b"(data == 0x8000) || (0) ||", b"(data == 0x8000) ||"),
    (b"(data == 0x8000) || ((data) == 0xFFFF) ||", b"(data == 0x8000) ||"),
    (b"if ((0)) { keyFunction = 0; }", b""),
    (b"if (((keyFunction) == 0xFFFF)) { keyFunction = 0; }", b""),
)


def strip_r96(raw):
    j = b" ".join(raw.split())
    for a, b in _PATS:
        j = j.replace(a, b)
    return j
