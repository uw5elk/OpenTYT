#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""font_gen.py -- R33 R1: витягує шрифти font_6x8, font_8x8, font_8x16 з application/include/hardware/HX8353E_charset_UA.h і пише tools/font_data.py
(модуль даних для точного передпоказу екрана в CPS; той самий принцип, що aprs_icons_gen.py -> aprs_icons_data.py: PyInstaller вбудовує імпортований модуль,
а заголовок прошивки в .exe не потрапив би).

Формат таблиці в заголовку (HX8353E_display.c, displayPrintCoreDoubleHeight): 8 байтів шапки [0x00, 0x00, перший код, останній код, ширина, висота, рядків
байтів на символ, байтів на символ], далі гліфи підряд. Символ з кодом c лежить за зміщенням 8 + (c - перший_код) * байтів_на_символ. Піксель (x, y): байт
`x + (y // 8) * ширина`, біт `y % 8` (молодший біт -- верхній рядок). Пробіл не малюється (його нема в таблиці: перший код 33).

Використання:
  python3 MDUV380_firmware/tools/font_gen.py            # перегенерувати font_data.py
  python3 MDUV380_firmware/tools/font_gen.py --check    # лише перевірка (код виходу 1, якщо font_data.py застарів або заголовок не розібрано)
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
HEADER = os.path.join(ROOT, "MDUV380_firmware", "application", "include", "hardware", "HX8353E_charset_UA.h")
OUT = os.path.join(HERE, "font_data.py")
FONTS = ("font_6x8", "font_6x8_bold", "font_8x8", "font_8x16", "font_16x32_compressed")
SIZES = {"font_6x8": (6, 8), "font_6x8_bold": (6, 8), "font_8x8": (8, 8), "font_8x16": (8, 16), "font_16x32_compressed": (16, 32)}

_TABLE = re.compile(r"const\s+uint8_t\s+(\w+)\s*\[\s*\]\s*=\s*\{(.*?)\n\};", re.S)
_NUM = re.compile(r"0[xX][0-9a-fA-F]+|\d+")


class FontError(Exception):
    pass


def parse_header(path=HEADER):
    """{ім'я: bytes} для FONTS. Коментарі `//` відкидаються (у них є цифри: `[ 33] '!'`), решта чисел -- байти таблиці."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    tables = {}
    for m in _TABLE.finditer(text):
        name = m.group(1)
        if name not in FONTS:
            continue
        body = "\n".join(line.split("//", 1)[0] for line in m.group(2).split("\n"))
        vals = [int(t, 0) for t in _NUM.findall(body)]
        if any(v > 255 for v in vals):
            raise FontError("%s: число більше 255 у таблиці" % name)
        tables[name] = bytes(vals)
    for name in FONTS:
        if name not in tables:
            raise FontError("у %s не знайдено таблицю %s" % (os.path.basename(path), name))
        b = tables[name]
        first, last, w, h, bpc = b[2], b[3], b[4], b[5], b[7]      # байт 6 (рядків байтів) прошивка не читає -- у 8x16 він 1, хоч рядків два
        if (w, h) != SIZES[name] or bpc != w * h // 8:
            raise FontError("%s: шапка %r не відповідає розміру %r" % (name, tuple(b[:8]), SIZES[name]))
        if b[0] & 1:                                               # стиснений шрифт (RLE8): кожен символ = n пар (значення, довжина-1), перед ними n
            pos = 8
            for code in range(first, last + 1):
                n = b[pos]
                pos += 1
                total = sum(b[pos + 2 * i + 1] + 1 for i in range(n))
                if total != bpc:
                    raise FontError("%s: символ %d розпаковується у %d байтів замість %d" % (name, code, total, bpc))
                pos += 2 * n
            if pos != len(b):
                raise FontError("%s: після %d символів лишилось %d зайвих байтів" % (name, last - first + 1, len(b) - pos))
        elif len(b) != 8 + (last - first + 1) * bpc:
            raise FontError("%s: шапка %r не збігається з довжиною %d (очікувалось %d)" % (name, tuple(b[:8]), len(b), 8 + (last - first + 1) * bpc))
    return tables


def render(tables):
    out = ['# -*- coding: utf-8 -*-',
           '"""font_data.py -- ЗГЕНЕРОВАНО tools/font_gen.py з HX8353E_charset_UA.h (R33 R1). Руками не правити: python3 MDUV380_firmware/tools/font_gen.py.',
           'Кожна таблиця -- байти як у прошивці (шапка з 8 байтів + гліфи); читання пікселів -- screen_sim.py."""',
           '']
    for name in FONTS:
        b = tables[name]
        out.append("%s = bytes.fromhex(" % name.upper())
        hx = b.hex()
        step = 96
        for i in range(0, len(hx), step):
            out.append('    "%s"' % hx[i:i + step])
        out.append(")")
        out.append("")
    out.append("TABLES = {%s}" % ", ".join('"%s": %s' % (n, n.upper()) for n in FONTS))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="R33 R1: шрифти прошивки -> font_data.py")
    ap.add_argument("--check", action="store_true", help="лише перевірити, що font_data.py збігається із заголовком")
    a = ap.parse_args(argv)
    try:
        text = render(parse_header())
    except (FontError, OSError) as e:
        print("font_gen: %s" % e)
        return 1
    if a.check:
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur != text:
            print("font_gen: font_data.py застарів -- запустіть python3 MDUV380_firmware/tools/font_gen.py")
            return 1
        print("font_gen: font_data.py збігається із заголовком")
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("font_gen: записано %s (%s)" % (os.path.relpath(OUT, ROOT), ", ".join("%s %d Б" % (n, len(parse_header()[n])) for n in FONTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
