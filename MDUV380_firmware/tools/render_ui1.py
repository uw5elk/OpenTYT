#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Піксельний рендер екранів ui1 (2026-10-04), ДЕННА і НІЧНА теми:

  * «SMS доставлено» -- велика зелена галочка (displaySmsAckedFullScreen, uiNotification.c);
  * «ПОМИЛКА / Ретранслятор / не відповідає» без третього рядка (uiTxScreen.c, UA-збірка).

Нічого не вигадує: кольори -- з themeDefaults у HX8353E_display.c (через квантування RGB565),
гліфи -- зі справжнього UA-шрифту HX8353E_charset_UA.h, рядки -- з ukrainian.h/txerr_ua.h
(cp1251), координати галочки -- з #define SMS_ACK_CHECK_* у uiNotification.c, лінії -- тим
самим алгоритмом Брезенгема, що displayDrawLine(). Рамка екрана помилки -- спрощено
(прямокутник без заокруглень і тіні).

    python3 render_ui1.py            # -> ui1_preview.png поруч зі скриптом
"""
import os
import re
from PIL import Image

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 160, 128

src = open(f'{FW}/application/source/hardware/HX8353E_display.c', encoding='utf-8').read()
tbl = src[src.index('static const uint32_t themeDefaults'):]
tbl = tbl[:tbl.index('\n\t};')]
themes = {}
for day in ('DAY', 'NIGHT'):
    chunk = tbl[tbl.index(f'[{day}] ='):]
    end = chunk.find('[NIGHT] =', 1)
    if end > 0:
        chunk = chunk[:end]
    themes[day] = {m.group(1): int(m.group(2), 16)
                   for m in re.finditer(r'\[(THEME_ITEM_\w+)\]\s*=\s*0x([0-9A-Fa-f]+)U', chunk)}


def rgb565(c):
    r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
    r, g, b = r & 0xF8, g & 0xFC, b & 0xF8
    return (r | r >> 5, g | g >> 6, b | b >> 5)


fsrc = open(f'{FW}/application/include/hardware/HX8353E_charset_UA.h', encoding='latin-1').read()


def load_font(name):
    m = re.search(name + r'\s*\[\s*\]\s*=\s*\{(.*?)\};', fsrc, re.S)
    body = re.sub(r'//[^\n]*', '', re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S))
    v = [int(x, 0) for x in re.findall(r'0x[0-9a-fA-F]+|\b\d+\b', body)]
    return dict(vals=v, start=v[2], end=v[3], w=v[4], h=v[5], bpc=v[7])


F3 = load_font('font_8x16')     # FONT_SIZE_3


def load_rle_font(name):
    """FONT_SIZE_4 на рації -- font_16x32_compressed (RLE8, дзеркало getUncompressedChar()):
    на кожен символ байт кількості пар, далі пари (значення, довжина-1)."""
    f = load_font(name)
    v, p, glyphs = f['vals'], 8, []
    for _ in range(f['end'] - f['start'] + 1):
        n = v[p]
        out = []
        for k in range(n):
            out += [v[p + 1 + 2 * k]] * (v[p + 2 + 2 * k] + 1)
        glyphs.append(out)
        p += n * 2 + 1
        if p >= len(v):
            break
    f['glyphs'] = glyphs
    return f


F4 = load_rle_font('font_16x32_compressed')    # FONT_SIZE_4 (UA: з кирилицею)


def c_define(path, name, enc='utf-8'):
    s = open(path, encoding=enc).read()
    m = re.search(r'#define\s+' + name + r'\s+(?:"([^"]*)"|(\d+))', s)
    return m.group(1) if m.group(1) is not None else int(m.group(2))


class FB:
    def __init__(self, bg):
        self.px = [[bg] * W for _ in range(H)]

    def set(self, x, y, c):
        if 0 <= x < W and 0 <= y < H:
            self.px[y][x] = c

    def fill(self, x, y, w, h, c):
        for yy in range(max(0, y), min(y + h, H)):
            for xx in range(max(0, x), min(x + w, W)):
                self.px[yy][xx] = c

    def rect(self, x, y, w, h, c):
        self.fill(x, y, w, 1, c); self.fill(x, y + h - 1, w, 1, c)
        self.fill(x, y, 1, h, c); self.fill(x + w - 1, y, 1, h, c)

    def line(self, x0, y0, x1, y1, c):
        """Дзеркало displayDrawLine() (HX8353E_display.c)."""
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0, x1, y1 = y0, x0, y1, x1
        if x0 > x1:
            x0, x1, y0, y1 = x1, x0, y1, y0
        dx, dy = x1 - x0, abs(y1 - y0)
        err = dx >> 1
        ystep = 1 if y0 < y1 else -1
        while x0 <= x1:
            if steep:
                self.set(y0, x0, c)
            else:
                self.set(x0, y0, c)
            err -= dy
            if err < 0:
                y0 += ystep
                err += dx
            x0 += 1

    def text(self, y, s, c, font):
        data = s.encode('cp1251')
        x = (W - font['w'] * len(data)) // 2
        for i, code in enumerate(data):
            if code == 0x20 or not (font['start'] <= code <= font['end']):
                continue
            if 'glyphs' in font:
                cols = font['glyphs'][code - font['start']]
            else:
                off = 8 + (code - font['start']) * font['bpc']
                cols = font['vals'][off:off + font['bpc']]
            for cx in range(font['w']):
                for cy in range(font['h']):
                    idx = cx + (cy // 8) * font['w']
                    if idx < len(cols) and (cols[idx] >> (cy % 8)) & 1:
                        self.set(x + i * font['w'] + cx, y + cy, c)


NOTIF = f'{FW}/application/source/user_interface/uiNotification.c'
CK = {k: c_define(NOTIF, 'SMS_ACK_CHECK_' + k) for k in ('X0', 'Y0', 'XM', 'YM', 'X1', 'Y1', 'THICK')}


def render_ack(theme):
    T = lambda k: rgb565(themes[theme][k])
    fb = FB(T('THEME_ITEM_BG_NOTIFICATION'))
    fb.rect(0, 0, W, H, T('THEME_ITEM_FG_DECORATION'))
    g = T('THEME_ITEM_FG_RSSI_BAR')
    for k in range(CK['THICK']):
        fb.line(CK['X0'], CK['Y0'] + k, CK['XM'], CK['YM'] + k, g)
        fb.line(CK['XM'], CK['YM'] + k, CK['X1'], CK['Y1'] + k, g)
    return fb


def render_txerr(theme):
    T = lambda k: rgb565(themes[theme][k])
    uk = open(f'{FW}/application/include/user_interface/languages/ukrainian.h', encoding='cp1251').read()
    err = re.search(r'\.error\s*=\s*"([^"]*)"', uk).group(1)
    tx = f'{FW}/application/include/user_interface/languages/txerr_ua.h'
    l1, l2 = c_define(tx, 'TXERR_RPT_LINE1', 'cp1251'), c_define(tx, 'TXERR_RPT_LINE2', 'cp1251')
    fb = FB(T('THEME_ITEM_BG'))
    fb.fill(4, 4, W - 6, H - 6, T('THEME_ITEM_BG_NOTIFICATION'))
    fb.rect(4, 4, W - 6, H - 6, T('THEME_ITEM_FG_DECORATION'))
    c = T('THEME_ITEM_FG_WARNING_NOTIFICATION')
    fb.text(4, err, c, F4)
    fb.text(64, l1, c, F3)       # ті самі y, що в uiTxScreen.c (UA-гілка)
    fb.text(82, l2, c, F3)
    return fb


def to_img(fb, scale=3):
    im = Image.new('RGB', (W, H))
    im.putdata([c for row in fb.px for c in row])
    return im.resize((W * scale, H * scale), Image.NEAREST)


if __name__ == '__main__':
    pad, scale = 10, 3
    sheet = Image.new('RGB', (2 * (W * scale + pad) + pad, 2 * (H * scale + pad) + pad), (24, 24, 28))
    for r, theme in enumerate(('DAY', 'NIGHT')):
        for c, fn in enumerate((render_ack, render_txerr)):
            sheet.paste(to_img(fn(theme), scale), (pad + c * (W * scale + pad), pad + r * (H * scale + pad)))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui1_preview.png')
    sheet.save(out)
    print('рендер збережено:', out)
