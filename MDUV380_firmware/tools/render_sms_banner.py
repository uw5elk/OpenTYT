#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Піксельний рендер банера вхідного SMS (uiNotification.c) і екрана читання (menuMessages.c), ui6.

Нічого не вигадує: гліфи -- зі справжнього UA-набору (HX8353E_charset_UA.h), кольори -- з таблиці
themeDefaults у HX8353E_display.c, а перенесення за словами ПОВТОРЮЄ smsWrapLine()
(functions/sms_format.c) рядок у рядок, розкладка -- displaySmsFullScreen() і readUpdate().
Тобто якщо тут текст обрізало чи виліз за край -- так само буде й на рації.

    python3 render_sms_banner.py      # -> sms_banner_preview.png, sms_read_preview.png
"""
import os, re
from PIL import Image

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.dirname(os.path.abspath(__file__))
W, H = 160, 128

# ---------- теми з реального коду -------------------------------------------
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

# ---------- шрифти ----------------------------------------------------------
fsrc = open(f'{FW}/application/include/hardware/HX8353E_charset_UA.h', encoding='latin-1').read()
def load_font(name):
    m = re.search(r'\b' + name + r'\s*\[\s*\]\s*=\s*\{(.*?)\};', fsrc, re.S)
    body = re.sub(r'//[^\n]*', '', re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S))
    v = [int(x, 0) for x in re.findall(r'0x[0-9a-fA-F]+|\b\d+\b', body)]
    return dict(vals=v, start=v[2], end=v[3], w=v[4], h=v[5], bpc=v[7])

F1 = load_font('font_6x8')     # FONT_SIZE_1 -- відправник, час, підказки
F2 = load_font('font_8x8')     # FONT_SIZE_2 -- лічильник; «малий» шрифт читання
F3 = load_font('font_8x16')    # FONT_SIZE_3 -- текст банера; «великий» шрифт читання

class FB:
    def __init__(self, bg):
        self.px = [[bg] * W for _ in range(H)]
    def fill(self, x, y, w, h, c):
        for yy in range(max(0, y), min(y + h, H)):
            for xx in range(max(0, x), min(x + w, W)):
                self.px[yy][xx] = c
    def rect(self, x, y, w, h, c):
        self.fill(x, y, w, 1, c); self.fill(x, y + h - 1, w, 1, c)
        self.fill(x, y, 1, h, c); self.fill(x + w - 1, y, 1, h, c)
    def tri(self, pts, c):
        (x0, y0), (x1, y1), (x2, y2) = pts
        for yy in range(min(y0, y1, y2), max(y0, y1, y2) + 1):
            xs = []
            for (ax, ay), (bx, by) in (((x0, y0), (x1, y1)), ((x1, y1), (x2, y2)), ((x2, y2), (x0, y0))):
                if ay != by and min(ay, by) <= yy <= max(ay, by):
                    xs.append(ax + (yy - ay) * (bx - ax) / (by - ay))
            if xs:
                a, b = int(round(min(xs))), int(round(max(xs)))
                self.fill(a, yy, b - a + 1, 1, c)
    def text(self, x, y, s, c, font, align='left'):
        data = s.encode('cp1251') if isinstance(s, str) else s
        n = len(data)
        if x + font['w'] * n > W:                     # як displayPrintCore: обрізає по краю
            n = max(0, (W - x) // font['w'])
        if align == 'center':
            x = (W - font['w'] * n) // 2
        for i, code in enumerate(data[:n]):
            if code == 0x20 or not (font['start'] <= code <= font['end']):
                continue
            off = 8 + (code - font['start']) * font['bpc']
            cols = font['vals'][off:off + font['bpc']]
            for cx in range(font['w']):
                for cy in range(font['h']):
                    idx = cx + (cy // 8) * font['w']
                    if idx < len(cols) and (cols[idx] >> (cy % 8)) & 1:
                        px, py = x + i * font['w'] + cx, y + cy
                        if 0 <= px < W and 0 <= py < H:
                            self.px[py][px] = c

# ---------- дзеркало functions/sms_format.c ---------------------------------
def wrap_line(s, start, w):
    """smsWrapLine(): (lineStart, length, next)."""
    p, n = start, len(s)
    while p < n and s[p] == ' ':
        p += 1
    if p >= n or w <= 0:
        return p, 0, n
    if n - p <= w:
        end = n
    elif s[p + w] == ' ':
        end = p + w
    else:
        sp = -1
        for i in range(p + w - 1, p, -1):
            if s[i] == ' ':
                sp = i
                break
        end = sp if sp > 0 else p + w
    nxt = end
    while end > p and s[end - 1] == ' ':
        end -= 1
    return p, end - p, nxt

def wrap_lines(s, w):
    out, pos = [], 0
    while pos < len(s):
        ls, l, nx = wrap_line(s, pos, w)
        if nx <= pos:
            break
        pos = nx
        if l > 0:
            out.append((s[ls:ls + l], pos))
    return out

def plural(n):
    d, h = n % 10, n % 100
    if d == 1 and h != 11:
        return 0
    if 2 <= d <= 4 and not (12 <= h <= 14):
        return 1
    return 2

def draw_wrapped(fb, txt, cols, first, max_lines, x, y, line_h, font, ellipsis, c):
    """uiSmsDrawWrapped()."""
    lines = wrap_lines(txt, cols)
    for idx, (line, pos_after) in enumerate(lines):
        if first <= idx < first + max_lines:
            if ellipsis and idx == first + max_lines - 1 and wrap_lines(txt[pos_after:], cols):
                cut = min(len(line), cols - 3)
                line = line[:cut] + '...'
            fb.text(x, y + (idx - first) * line_h, line, c, font)
    return len(lines)

# ---------- дзеркало displaySmsFullScreen() (ui6) ----------------------------
UNREAD = ('%d непрочитане', '%d непрочитані', '%d непрочитаних')

def banner(theme, hdr, tm, txt, unread, foreign=False):
    T = lambda k: rgb565(themes[theme][k])
    line_h, cnt_h, text_y = 16, 8, 14
    cols = (W - 6) // 8
    reserved = (cnt_h + 2) if unread > 1 else 0
    max_lines = max(1, (H - text_y - 2 - reserved) // line_h)
    fb = FB(T('THEME_ITEM_BG_NOTIFICATION'))
    fb.rect(0, 0, W, H, T('THEME_ITEM_FG_DECORATION'))
    max_chars = (W - 6 - ((len(tm) * 6 + 6) if tm else 0)) // 6
    fb.text(3, 3, hdr[:max_chars], T('THEME_ITEM_FG_WARNING_NOTIFICATION' if foreign else 'THEME_ITEM_FG_NOTIFICATION'), F1)
    if tm:
        fb.text(W - 3 - len(tm) * 6, 3, tm, T('THEME_ITEM_FG_NOTIFICATION'), F1)
    fb.fill(3, 12, W - 6, 1, T('THEME_ITEM_FG_DECORATION'))
    draw_wrapped(fb, txt, cols, 0, max_lines, 3, text_y, line_h, F3, True, T('THEME_ITEM_FG_NOTIFICATION'))
    if unread > 1:
        fb.text(0, H - cnt_h - 2, UNREAD[plural(unread)] % unread, T('THEME_ITEM_FG_WARNING_NOTIFICATION'), F2, 'center')
    return fb

# ---------- дзеркало readUpdate() (ui6) --------------------------------------
def read_screen(theme, title, hdr, tm, txt, big, scroll, hint):
    T = lambda k: rgb565(themes[theme][k])
    fb = FB(T('THEME_ITEM_BG'))
    fb.fill(0, 0, W, 14, T('THEME_ITEM_BG_MENU_NAME'))
    fb.fill(0, 13, W, 1, T('THEME_ITEM_FG_DECORATION'))
    fb.text(0, 3, title, T('THEME_ITEM_FG_MENU_NAME'), F2, 'center')
    fg = T('THEME_ITEM_FG_DEFAULT')
    fb.text(2, 16, hdr, fg, F1)
    text_y = 26
    if tm:
        if 2 + len(hdr.encode('cp1251')) * 6 + 6 + len(tm) * 6 <= W - 2:
            fb.text(W - 2 - len(tm) * 6, 16, tm, fg, F1)
        else:
            fb.text(W - 2 - len(tm) * 6, 25, tm, fg, F1)
            text_y = 35
    font, glyph_h, line_h = (F3, 16, 16) if big else (F2, 8, 11)
    rows = (111 - text_y - glyph_h) // line_h + 1
    total = len(wrap_lines(txt, 20))
    max_scroll = max(0, total - rows)
    scroll = min(scroll, max_scroll)
    draw_wrapped(fb, txt, 20, scroll, rows, 0, text_y, line_h, font, False, fg)
    fb.text(0, 112, hint, fg, F1, 'center')
    if scroll > 0:
        fb.tri(((4, 112), (0, 119), (8, 119)), fg)
    if scroll < max_scroll:
        fb.tri(((W - 9, 112), (W - 1, 112), (W - 5, 119)), fg)
    return fb

def to_img(fb, scale=3):
    im = Image.new('RGB', (W, H))
    im.putdata([c for row in fb.px for c in row])
    return im.resize((W * scale, H * scale), Image.NEAREST)

def sheet(frames, cols, name, scale=3, pad=10):
    rows = (len(frames) + cols - 1) // cols
    img = Image.new('RGB', (cols * (W * scale + pad) + pad, rows * (H * scale + pad) + pad), (24, 24, 28))
    for i, fb in enumerate(frames):
        r, c = divmod(i, cols)
        img.paste(to_img(fb, scale), (pad + c * (W * scale + pad), pad + r * (H * scale + pad)))
    path = os.path.join(OUT, name)
    img.save(path)
    print('рендер збережено:', path)

LONG = ('Виходимо на позицію через десять хвилин, підтвердьте готовність і '
        'перевірте батареї. Зв\'язок на другому каналі, позивний Ґанок. Їжак -- запасний.')
TEST = 'Привіт. Тест кирилиці на OpenTYT. ІіЄєҐґЇї'

if __name__ == '__main__':
    frames = []
    for theme in ('DAY', 'NIGHT'):
        frames.append(banner(theme, 'Від UW5ELK', '21:30', TEST, 4))
        frames.append(banner(theme, 'UR5EQF -> UT7UA', '09:05', 'Перевірка зв\'язку, прийом.', 1, foreign=True))
        frames.append(banner(theme, 'Від UW5ELK Bohdan Melnyk', '', LONG, 22))
    sheet(frames, 3, 'sms_banner_preview.png')

    frames = []
    hint = 'SK2+GRN:вид GRN:відпов'
    frames.append(read_screen('DAY', 'Вхідні', 'Від UW5ELK', '05.10 21:30', TEST, True, 0, hint))
    frames.append(read_screen('DAY', 'Вхідні', 'Від UW5ELK', '05.10 21:30', LONG, True, 0, hint))
    frames.append(read_screen('DAY', 'Вхідні', 'Від UW5ELK', '05.10 21:30', LONG, True, 3, hint))
    frames.append(read_screen('DAY', 'Вхідні', 'Від UW5ELK', '05.10 21:30', TEST, False, 0, hint))
    frames.append(read_screen('DAY', 'Вхідні', 'Від UW5ELK Bohdan (не вам)', '05.10 21:30', LONG, False, 0, hint))
    frames.append(read_screen('DAY', 'Вхідні', 'Від UW5ELK', '', LONG, False, 1, hint))
    sheet(frames, 3, 'sms_read_preview.png')
    print('банер: верхній ряд -- ДЕННА тема, нижній -- НІЧНА; читання: верхній ряд -- «великий», нижній -- «малий»')
