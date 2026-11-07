#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R66 (хост-перевірки). Розділи додаються по комітах.

A  R66A: індикатор роумінгу на екрані передачі («Р>» малювалось як «Ð>»):
   A1 передумова: у шрифті 16x32 (FONT_SIZE_4, UA) код 0xD0 -- латинська «D з рискою» (збігається з гліфом звичайного charset.h), а не «P»;
   A2 передумова: кириличні гліфи в 16x32 є лише для А И Й К Л М О П Т У;
   A3 у малих шрифтах (6x8, 8x16) код 0xD0 -- кирилична «Р» (відрізняється від латинської «D з рискою»), тож індикатор «Р<N>» на екрані каналу малюється правильно;
   A4 ROAM_IND_SPARE (його малює 16x32): лише ASCII, і кожен символ має непорожній гліф у 16x32; мутант «кирилична Р» ловиться.
Запуск: python3 tools/test_r66.py"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
INC = os.path.join(ROOT, "application", "include")
import font16_probe as F      # noqa: E402

FAILS = []
PASSED = [0]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def small_font(name):
    t = open(os.path.join(INC, "hardware", "HX8353E_charset_UA.h"), encoding="latin-1").read()
    i = t.index("const uint8_t " + name + "[]")
    j = t.index("};", i)
    body = re.sub(r"//[^\n]*", "", t[t.index("{", i) + 1:j])
    return bytes(int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|\b\d+\b", body))


def small_glyph(f, c):
    bpc = f[7]
    o = 8 + (c - f[2]) * bpc
    return f[o:o + bpc]


def indicator_ok(value, f32):
    """Кожен символ -- ASCII і має непорожній гліф у 16x32."""
    for ch in value:
        if ord(ch) > 0x7E:
            return False
        if ch != " " and not any("#" in r for r in F.glyph(f32, ord(ch))):
            return False
    return True


def main():
    ua = F.load(os.path.join(INC, "hardware", "HX8353E_charset_UA.h"))
    lat = F.load(os.path.join(INC, "hardware", "HX8353E_charset.h"))
    check(F.glyph(ua, 0xD0) == F.glyph(lat, 0xD0), "A1: 16x32 UA: гліф 0xD0 збігається з латинським (Ð)")
    check(F.glyph(ua, 0xD0) != F.glyph(ua, 0x50), "A1: 16x32 UA: гліф 0xD0 не є «P»")
    cyr = [c for c in range(0xC0, 0x100) if F.glyph(ua, c) != F.glyph(lat, c)]
    check(bytes(cyr).decode("cp1251") == "АИЙКЛМОПТУ", "A2: кириличні гліфи 16x32: %r" % bytes(cyr).decode("cp1251"))
    f6, f8 = small_font("font_6x8"), small_font("font_8x16")
    lat6 = small_font("font_6x8")
    check(small_glyph(f6, 0xD0) != small_glyph(f6, 0x44) and small_glyph(f8, 0xD0) != small_glyph(f8, 0x44), "A3: у 6x8 і 8x16 0xD0 не є латинською «D»")
    # у малих шрифтах «Р» відрізняється від «Ð» звичайного charset.h
    latf8 = None
    t = open(os.path.join(INC, "hardware", "HX8353E_charset.h"), encoding="latin-1").read()
    i = t.index("const uint8_t font_8x16[]")
    j = t.index("};", i)
    body = re.sub(r"//[^\n]*", "", t[t.index("{", i) + 1:j])
    latf8 = bytes(int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+|\b\d+\b", body))
    check(small_glyph(f8, 0xD0) != small_glyph(latf8, 0xD0), "A3: 8x16 UA: 0xD0 -- не латинська Ð")

    h = open(os.path.join(INC, "user_interface", "languages", "roam_ua.h"), "rb").read().decode("cp1251")
    m = re.search(r'#define\s+ROAM_IND_SPARE\s+"([^"]*)"', h)
    check(m is not None, "A4: ROAM_IND_SPARE знайдено")
    val = m.group(1) if m else ""
    check(indicator_ok(val, ua), "A4: ROAM_IND_SPARE %r -- ASCII з гліфами в 16x32" % val)
    check(not indicator_ok("Р>", ua), "A4: мутант «кирилична Р» ловиться")
    check(not indicator_ok("\xd0>", ua), "A4: мутант «0xD0» ловиться")
    check(val.startswith("R") and val.endswith(">"), "A4: індикатор -- «R>»")
    rui = open(os.path.join(INC, "user_interface", "roam_ui.h"), encoding="utf-8", errors="replace").read()
    m2 = re.search(r'#define\s+ROAM_IND_SPARE\s+"([^"]*)"', rui)
    check(m2 is not None and m2.group(1) == val, "A4: англійський варіант збігається з українським")

    print("test_r66: %d перевірок, провалів %d" % (PASSED[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
