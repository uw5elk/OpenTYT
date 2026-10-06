#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Піксельний рендер екрана набору SMS і шпаргалки розкладки (menuMessages.c), ui7.

Нічого не вигадує: шрифти, теми й перенесення за словами -- з render_sms_banner.py (той самий
дзеркальний код), розкладки клавіш -- зі СПРАВЖНЬОГО functions/sms_multitap.c (компілюється
хостовим gcc з -DLANGUAGE_BUILD_UKRAINIAN і друкує smsMtKeyMap()), розкладка екрана --
composeUpdate()/composeKeyHint()/layoutUpdate() рядок у рядок.

    python3 render_sms_compose.py      # -> sms_compose_preview.png
"""
import os, subprocess, tempfile
import render_sms_banner as R

FW = R.FW
W, H = R.W, R.H
F1, F2, F3 = R.F1, R.F2, R.F3

# ---------- розкладки -- зі справжнього sms_multitap.c ------------------------
def load_maps():
    src = r'''
#include <stdio.h>
#include "functions/sms_multitap.h"
int main(void) {
    for (int m = 0; m < SMS_MT_MODES; m++) {
        printf("L %s\n", smsMtModeLabel((unsigned char)m));
        for (const char *k = "1234567890*"; *k; k++) printf("K %c %s\n", *k, smsMtKeyMap((unsigned char)m, *k));
    }
    return 0;
}'''
    d = tempfile.mkdtemp()
    c, exe = os.path.join(d, 'm.c'), os.path.join(d, 'm')
    open(c, 'w').write(src)
    subprocess.check_call(['gcc', '-DENABLE_AES', '-DENABLE_DMR_DATA', '-DLANGUAGE_BUILD_UKRAINIAN',
                           '-I', f'{FW}/application/include', '-o', exe, c,
                           f'{FW}/application/source/functions/sms_multitap.c'])
    out = subprocess.check_output([exe])
    modes = []
    for line in out.split(b'\n'):
        if line.startswith(b'L '):
            modes.append({'label': line[2:].decode('cp1251'), 'keys': {}})
        elif line.startswith(b'K '):
            modes[-1]['keys'][chr(line[2])] = line[4:].decode('cp1251')
    return modes

MODES = load_maps()
MODE_ABV_UP, MODE_ABV, MODE_ABC_UP, MODE_ABC, MODE_123 = range(5)

# ---------- дзеркало smsWrapPos() ---------------------------------------------
def wrap_pos(s, w, pos):
    r, p, n = 0, 0, len(s)
    pos = max(0, min(pos, n))
    while p < n:
        ls, l, nx = R.wrap_line(s, p, w)
        if l <= 0:
            break
        zone = nx
        while zone < n and s[zone] == ' ':
            zone += 1
        if pos < zone or zone >= n:
            c = max(0, pos - ls)
            return (r, c) if c < w else (r + 1, 0)
        r += 1
        p = nx
    return pos // w, pos % w

# ---------- дзеркало composeUpdate() ------------------------------------------
def compose(theme, text, mode, big=True, pending_key=None, pending_idx=0, cap=144, presets=False):
    T = lambda k: R.rgb565(R.themes[theme][k])
    fg, bg = T('THEME_ITEM_FG_DEFAULT'), T('THEME_ITEM_BG')
    fb = R.FB(bg)
    fb.fill(0, 0, W, 14, T('THEME_ITEM_BG_MENU_NAME'))
    fb.fill(0, 13, W, 1, T('THEME_ITEM_FG_DECORATION'))
    fb.text(0, 3, 'Нове повідомлення', T('THEME_ITEM_FG_MENU_NAME'), F2, 'center')

    font, glyph_h, line_h, rows, y0 = (F3, 16, 16, 4, 23) if big else (F2, 8, 14, 5, 22)
    if pending_key is not None:
        text = text + MODES[mode]['keys'][pending_key][pending_idx]
        cur = len(text) - 1
    else:
        cur = len(text)
    n = len(text)
    cr, cc = wrap_pos(text, 20, cur)
    win = cr
    if cur >= cap and cur > 0:
        win = wrap_pos(text, 20, cur - 1)[0]
    first = max(0, win - (rows - 1))
    R.draw_wrapped(fb, text, 20, first, rows, 0, y0, line_h, font, False, fg)
    cx, cy = cc * 8, y0 + (cr - first) * line_h
    if cr - first < rows:
        if pending_key is not None:
            fb.fill(cx, cy, 8, glyph_h, fg)
            fb.text(cx, cy, text[cur], bg, font)
        elif cur < cap:
            fb.text(cx, cy, '_', fg, font)

    lbl = MODES[mode]['label']
    chip_w = len(lbl) * 6 + 4
    fb.fill(0, 95, chip_w, 10, fg)
    fb.text(2, 96, lbl, bg, F1)
    if pending_key is not None:                      # composeKeyHint()
        mp = MODES[mode]['keys'][pending_key]
        x = chip_w + 4
        cells = (W - x) // 8
        step = 2 if (2 * len(mp) - 1) <= cells else 1
        start = 0
        if step == 1 and len(mp) > cells:
            start = max(0, min(pending_idx - cells // 2, len(mp) - cells))
        for k in range(start, len(mp)):
            if (k - start) * step >= cells:
                break
            ch = '_' if mp[k] == ' ' else mp[k]
            kx = x + (k - start) * step * 8
            if k == pending_idx:
                fb.fill(kx, 96, 8, 8, fg)
                fb.text(kx, 96, ch, bg, F2)
            else:
                fb.text(kx, 96, ch, fg, F2)
    else:
        fb.text(chip_w + 4, 96, '#:режим', fg, F1)
        cnt = '%d/%d симв.' % (n, cap)
        fb.text(W - len(cnt) * 6, 96, cnt, fg, F1)
    fb.text(0, 106, 'U:шаблон D:літ. L:стерти' if presets else 'D:літери  L:стерти', fg, F1, 'center')
    fb.text(0, 116, 'GRN:кому  RED:відміна', fg, F1, 'center')
    return fb

# ---------- дзеркало layoutUpdate() -------------------------------------------
def layout(theme, mode):
    T = lambda k: R.rgb565(R.themes[theme][k])
    fg = T('THEME_ITEM_FG_DEFAULT')
    fb = R.FB(T('THEME_ITEM_BG'))
    fb.fill(0, 0, W, 14, T('THEME_ITEM_BG_MENU_NAME'))
    fb.fill(0, 13, W, 1, T('THEME_ITEM_FG_DECORATION'))
    fb.text(0, 3, 'Розкладка: ' + MODES[mode]['label'], T('THEME_ITEM_FG_MENU_NAME'), F2, 'center')
    for r, key in enumerate('1234567890*'):
        mp = MODES[mode]['keys'][key]
        step = 2 if (2 + 2 * len(mp) - 1) <= 26 else 1
        line = key + ' '
        k = 0
        while k < len(mp) and len(line) < 26:
            if step == 2 and k > 0:
                line += ' '
            line += '_' if mp[k] == ' ' else mp[k]
            k += 1
        if k < len(mp):
            line = line[:25] + '>'
        fb.text(2, 15 + r * 9, line, fg, F1)
    fb.text(0, 117, 'будь-яка клавіша: назад', fg, F1, 'center')
    return fb

if __name__ == '__main__':
    long_txt = 'Привіт. Тест кирилиці на OpenTYT. Виходимо на позицію через десять хвилин, перевірте батареї'
    frames = [
        compose('DAY', 'Привіт. Тест кирилиці на OpenTYT.', MODE_ABV),
        compose('DAY', long_txt, MODE_ABV),
        compose('DAY', 'Привіт. Тест кирилиці на ', MODE_ABV, pending_key='2', pending_idx=2),
        compose('DAY', long_txt, MODE_ABV, big=False),
        compose('DAY', 'QTH ', MODE_ABC_UP, pending_key='1', pending_idx=6, presets=True),
        compose('DAY', 'Тел. +380', MODE_123, pending_key='*', pending_idx=2),
        layout('DAY', MODE_ABV),
        layout('DAY', MODE_ABC),
        layout('NIGHT', MODE_123),
    ]
    R.sheet(frames, 3, 'sms_compose_preview.png')
    print('ряд 1: набір великим (коротке / автогортання / підказка «2» в абв, поточна «в»);')
    print('ряд 2: малий шрифт / підказка «1» в ABC (вікно) / «*» у 123; ряд 3: шпаргалки абв / abc / 123 (нічна)')
