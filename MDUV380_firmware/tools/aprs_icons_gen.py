#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aprs_icons_gen.py -- R20 Ж2: перетворює tools/aprs_icons.txt (ASCII-сітки 24x24) на C-таблицю піктограм і контактний аркуш.

Виходи (КОМІТЯТЬСЯ; CI у мережу не ходить, Python під час збірки прошивки не потрібен):
  application/source/functions/aprs_icons.c   -- індекс [таблиця][код] -> зміщення + пул даних (const у flash, 0 байт RAM/CCM)
  docs/aprs-icons.md                          -- контактний аркуш усіх піктограм (напівблоки), щоб переглянути набір одним файлом

Використання:
  python3 MDUV380_firmware/tools/aprs_icons_gen.py            # перегенерувати обидва файли
  python3 MDUV380_firmware/tools/aprs_icons_gen.py --check    # лише перевірка (код виходу 1, якщо файли застаріли або txt некоректний) -- запускає tests/run_tests.sh

Формат у flash: піктограма -- 72 байти без стиснення (24 рядки по 3 байти, XBM: молодший біт ліворуч, формат displayDrawXBitmap); дані -- в одному з двох пулів:
  пул A -- піктограми, на які посилається ПЕРВИННА таблиця '/' (разом з додатковими кодами, що малюються тим самим зображенням); пул B -- решта (лише додаткова '\\').
  Пул B не компілюється в діагностичній збірці (ENABLE_APRS_RX_PROBE): до фіксованої адреси кодека їй не вистачає місця на всю таблицю.
Індекс iconNo[таблиця][код - 0x21] -> номер піктограми (0xFF -- нема). Виміряно (R20): RLE8 по рядках XBM дає менше 1% (контури товсті, серії короткі); по стовпцях, як у шрифтах, -- близько 16%;
стиснення не вмикалось, бо вільного флешу користувацької збірки після таблиці лишається більше за поріг 4096 Б (див. STATUS.md).

Валідація (падає з конкретним повідомленням і номером рядка): рівно 24 рядки по 24 символи '#'/'.', нема дублікатів (таблиця, код), код в '!'...'~', таблиця '/' або '\\',
назва 1..12 символів, збігається з aprsmode_ua.h (APRSM_SYM_P_xx / APRSM_SYM_A_xx), нема поодиноких пікселів, піктограма не порожня.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
TXT = os.path.join(HERE, 'aprs_icons.txt')
CFILE = os.path.join(ROOT, 'MDUV380_firmware', 'application', 'source', 'functions', 'aprs_icons.c')
MDFILE = os.path.join(ROOT, 'docs', 'aprs-icons.md')
NAMES_H = os.path.join(ROOT, 'MDUV380_firmware', 'application', 'include', 'user_interface', 'languages', 'aprsmode_ua.h')

W = H = 24
NB = W * H // 8      # 72 байти
# назви перших десяти символів -- у aprsmode_ua.h під іншими іменами (APRSM_SYM_CAR ...)
BASE_NAMES = {'>': 'CAR', '[': 'HUMAN', '-': 'HOUSE', 'b': 'BIKE', '<': 'MOTO', 'k': 'TRUCK', 'v': 'VAN', '#': 'DIGI', 'r': 'REPEATER', 'Y': 'YACHT'}


class Err(Exception):
    pass


def parse_txt(path):
    icons = []     # (table, code, name, rows, lineno)
    seen = set()
    lines = open(path, encoding='utf-8').read().split('\n')
    i = 0
    while i < len(lines):
        ln = lines[i]
        i += 1
        if (not ln.strip()) or ln.startswith('//'):
            continue
        m = re.match(r'^@ (.) (.) (.+)$', ln)
        if not m:
            raise Err('%s:%d: очікувався заголовок «@ <таблиця> <код> <назва>», є «%s»' % (os.path.basename(path), i, ln[:40]))
        table, code, name = m.group(1), m.group(2), m.group(3).strip()
        if table not in ('/', '\\'):
            raise Err('%s:%d: таблиця «%s» -- лише / або \\' % (os.path.basename(path), i, table))
        if not ('!' <= code <= '~'):
            raise Err('%s:%d: код «%s» поза діапазоном ! ... ~' % (os.path.basename(path), i, code))
        if (table, code) in seen:
            raise Err('%s:%d: дублікат %s%s' % (os.path.basename(path), i, table, code))
        seen.add((table, code))
        if not (1 <= len(name) <= 12):
            raise Err('%s:%d: назва «%s» -- %d символів, треба 1..12' % (os.path.basename(path), i, name, len(name)))
        rows = lines[i:i + H]
        if len(rows) < H:
            raise Err('%s:%d: %s%s -- менше %d рядків сітки' % (os.path.basename(path), i, table, code, H))
        for k, r in enumerate(rows):
            if len(r) != W or any(ch not in '#.' for ch in r):
                raise Err('%s:%d: %s%s, рядок %d сітки: треба рівно %d символів з «#» і «.» (є %d: «%s»)' % (os.path.basename(path), i + k + 1, table, code, k + 1, W, len(r), r))
        icons.append((table, code, name, rows, i))
        i += H
    return icons


def pixels(rows):
    return [[1 if ch == '#' else 0 for ch in r] for r in rows]


def to_bytes(rows):
    """XBM: 3 байти на рядок, молодший біт ліворуч (формат displayDrawXBitmap)"""
    p = pixels(rows)
    out = []
    for y in range(H):
        for b in range(3):
            v = 0
            for bit in range(8):
                if p[y][b * 8 + bit]:
                    v |= 1 << bit
            out.append(v)
    return bytes(out)


# R20-fix: піктограми, які МАЮТЬ бути симетричними відносно вертикальної осі кадру (щити, кола, літаки, будівлі, хмарки тощо). Раніше їх малювали
# навколо колонки 12, а центр кадру 24 px -- між колонками 11 і 12, тому виходили «криві». Тепер це перевіряється: будь-яка правка txt, що ламає
# дзеркальність цих символів, не пройде перевірку. Бічні види (транспорт, тварини) і піктограми з написами сюди не входять.
SYMMETRIC_LR = r"""
/! /# /$ /& /' /( /+ /, /- /. // /0 /8 /A /E /G /M /O /S /W /[ /\ /] /^ /` /d /g /h /l /m /n /o /r /t /w /x /z
\! \# \$ \% \& \' \* \+ \, \- \0 \8 \= \A \C \H \L \O \S \U \V \W \X \\ \^ \a \c \d \i \l \n \o \t \y \z
""".split()

def validate(icons):
    names = open(NAMES_H, 'rb').read().decode('cp1251')
    defs = {m.group(1): m.group(2) for m in re.finditer(r'#define\s+(APRSM_SYM_\w+)\s+"([^"]*)"', names)}
    for table, code, name, rows, ln in icons:
        p = pixels(rows)
        ink = sum(map(sum, p))
        if ink < 8:
            raise Err('%s%s: піктограма (майже) порожня (%d пікселів)' % (table, code, ink))
        for y in range(H):
            for x in range(W):
                if p[y][x] and not any(0 <= x + dx < W and 0 <= y + dy < H and p[y + dy][x + dx] for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy):
                    raise Err('%s%s: поодинокий піксель (x=%d, y=%d) -- на цьому екрані він розмивається' % (table, code, x, y))
        if (table + code) in SYMMETRIC_LR:
            bad = sum(1 for y in range(H) for x in range(W // 2) if p[y][x] != p[y][W - 1 - x])
            if bad:
                raise Err('%s%s: піктограма має бути симетричною, а розбіжностей із дзеркалом -- %d пікселів' % (table, code, bad))
        key = ('APRSM_SYM_' + BASE_NAMES[code]) if (table == '/' and code in BASE_NAMES) else 'APRSM_SYM_%s_%02X' % ('P' if table == '/' else 'A', ord(code))
        if key not in defs:
            raise Err('%s%s: у aprsmode_ua.h нема %s (назва «%s»)' % (table, code, key, name))
        if defs[key] != name:
            raise Err('%s%s: назва в txt «%s» не збігається з aprsmode_ua.h «%s» (%s)' % (table, code, name, defs[key], key))


def build_c(icons):
    """піктограми -> (текст C, розміри). Пул A -- зображення первинної таблиці, пул B -- решта; однакові зображення зберігаються один раз."""
    uniq = []
    num = {}
    prim = [ic for ic in icons if ic[0] == '/']
    alt = [ic for ic in icons if ic[0] != '/']
    for grp in (prim, alt):
        for table, code, name, rows, ln in grp:
            data = to_bytes(rows)
            if data not in num:
                num[data] = len(uniq)
                uniq.append(data)
        if grp is prim:
            nA = len(uniq)
    nB = len(uniq) - nA
    assert len(uniq) < 0xFF
    index = [[None] * 94 for _ in range(2)]
    for table, code, name, rows, ln in icons:
        index[0 if table == '/' else 1][ord(code) - 0x21] = num[to_bytes(rows)]
    sizes = {'icons': len(icons), 'unique': len(uniq), 'poolA': nA * NB, 'poolB': nB * NB, 'index': 2 * 94, 'nA': nA, 'nB': nB}
    L = []
    L.append('/*')
    L.append(' * aprs_icons.c -- піктограми символів APRS 24x24 (R14/R17/R20). ЗГЕНЕРОВАНО tools/aprs_icons_gen.py з tools/aprs_icons.txt -- НЕ РЕДАГУВАТИ РУКАМИ:')
    L.append(' * правити треба tools/aprs_icons.txt і перегенерувати (python3 MDUV380_firmware/tools/aprs_icons_gen.py). Вигляд усіх піктограм -- docs/aprs-icons.md.')
    L.append(' * Кожна -- 72 байти (24 рядки по 3 байти, XBM: молодший біт ліворуч, displayDrawXBitmap()), без стиснення. Індекс iconNo[таблиця][код - 0x21] -> номер піктограми')
    L.append(' * (ICON_NONE -- нема). Пул A (%d шт.) -- зображення первинної таблиці; пул B (%d шт.) -- решта (лише додаткова) і в діагностичній збірці ENABLE_APRS_RX_PROBE не компілюється.' % (nA, nB))
    L.append(' * Піктограм (кодів): %d, унікальних зображень %d: пул A %d Б + пул B %d Б + індекс %d Б. Усе const у flash, 0 байт RAM/CCM.' % (sizes['icons'], sizes['unique'], sizes['poolA'], sizes['poolB'], sizes['index']))
    L.append(' */')
    L.append('#include "functions/aprs_rx_cfg.h"   /* ENABLE_APRS_RX (у т.ч. з ENABLE_APRS_RX_PROBE) */')
    L.append('#include "functions/aprs_icons.h"')
    L.append('')
    L.append('#if defined(ENABLE_APRS_RX)')
    L.append('')
    L.append('#define ICON_NONE   0xFFU')
    L.append('#define ICON_COUNT_A  %d' % nA)
    L.append('')
    L.append('static const uint8_t iconNo[2][94] =')
    L.append('{')
    for t_ in (0, 1):
        L.append('\t{   /* таблиця \'%s\' */' % ('/' if t_ == 0 else '\\\\'))
        row = index[t_]
        for s in range(0, 94, 16):
            L.append('\t\t' + ', '.join(('ICON_NONE' if v is None else '%3d' % v) for v in row[s:s + 16]) + ',')
        L.append('\t},')
    L.append('};')
    L.append('')
    def pool(name, items):
        L.append('static const uint8_t %s[][%d] =' % (name, NB))
        L.append('{')
        for k, d in enumerate(items):
            L.append('\t{ /* №%d */' % (k + (0 if name == 'iconPoolA' else nA)))
            for s in range(0, NB, 12):
                L.append('\t\t' + ', '.join('0x%02X' % b for b in d[s:s + 12]) + ',')
            L.append('\t},')
        L.append('};')
        L.append('')
    pool('iconPoolA', uniq[:nA])
    if nB:
        L.append('#if ! defined(ENABLE_APRS_RX_PROBE)')
        pool('iconPoolB', uniq[nA:])
        L.append('#endif')
        L.append('')
    L.append('const uint8_t *aprsIconFind(char table, char code, bool *overlay)')
    L.append('{')
    L.append('\tint tab;')
    L.append('\tbool ov = false;')
    L.append('\tuint8_t no;')
    L.append('')
    L.append('\t*overlay = false;')
    L.append('\tif ((code < \'!\') || (code > \'~\'))')
    L.append('\t{')
    L.append('\t\treturn NULL;')
    L.append('\t}')
    L.append('\tif (table == \'/\')')
    L.append('\t{')
    L.append('\t\ttab = 0;')
    L.append('\t}')
    L.append('\telse if (table == \'\\\\\')')
    L.append('\t{')
    L.append('\t\ttab = 1;')
    L.append('\t}')
    L.append('\telse if (((table >= \'0\') && (table <= \'9\')) || ((table >= \'A\') && (table <= \'Z\')))')
    L.append('\t{')
    L.append('\t\ttab = 1;      /* накладка: піктограма додаткового набору, знак таблиці малюють поверх */')
    L.append('\t\tov = true;')
    L.append('\t}')
    L.append('\telse')
    L.append('\t{')
    L.append('\t\treturn NULL;   /* таблиці, якої в APRS нема */')
    L.append('\t}')
    L.append('\tno = iconNo[tab][code - \'!\'];')
    L.append('\tif (no == ICON_NONE)')
    L.append('\t{')
    L.append('\t\treturn NULL;   /* код зарезервований у специфікації або нестандартний -- рамка зі знаком */')
    L.append('\t}')
    L.append('\tif (no < ICON_COUNT_A)')
    L.append('\t{')
    L.append('\t\t*overlay = ov;')
    L.append('\t\treturn iconPoolA[no];')
    L.append('\t}')
    if nB:
        L.append('#if ! defined(ENABLE_APRS_RX_PROBE)')
        L.append('\t*overlay = ov;')
        L.append('\treturn iconPoolB[no - ICON_COUNT_A];')
        L.append('#else')
        L.append('\treturn NULL;   /* діагностична збірка: пулу B нема (місце до адреси кодека) -- рамка зі знаком */')
        L.append('#endif')
    else:
        L.append('\treturn NULL;')
    L.append('}')
    L.append('')
    L.append('unsigned aprsIconCount(void)')
    L.append('{')
    L.append('\treturn %du;' % len(icons))
    L.append('}')
    L.append('')
    L.append('#endif /* ENABLE_APRS_RX */')
    L.append('')
    return '\n'.join(L), sizes


def half_rows(rows):
    """24 рядки пікселів -> 12 рядків напівблоків (▀ ▄ █)"""
    p = pixels(rows)
    out = []
    for y in range(0, H, 2):
        s = ''
        for x in range(W):
            a, b = p[y][x], p[y + 1][x]
            s += '█' if (a and b) else ('▀' if a else ('▄' if b else ' '))
        out.append(s)
    return out


def build_md(icons, sizes):
    L = []
    L.append('# Піктограми символів APRS (контактний аркуш)\n')
    L.append('Усі піктограми 24×24 (R20 Ж2) одним файлом — щоб переглянути набір і сказати, що перемалювати. Кожна піктограма показана напівблоками (`▀▄█`, два пікселі по висоті на знак), '
             'тож пропорції збережено. **Джерело** — `MDUV380_firmware/tools/aprs_icons.txt` (ASCII-сітки `#`/`.`; правте там і запускайте `python3 MDUV380_firmware/tools/aprs_icons_gen.py`). '
             '`MDUV380_firmware/application/source/functions/aprs_icons.c` і цей файл — згенеровані.\n')
    L.append('Таблиця `/` — первинна, `\\` — додаткова; таблиця-цифра чи літера (накладка) малює піктограму додаткової таблиці й знак накладки в куті 8×8. '
             'Символи, яких тут нема, зарезервовані специфікацією APRS — для них прошивка малює рамку 24×24 зі знаком символу.\n')
    L.append('Усього піктограм: **%d** кодів (унікальних зображень %d). У flash: пул A (первинна таблиця) %d Б + пул B (решта) %d Б + індекс %d Б = **%d Б**; діагностична збірка містить лише пул A.\n' % (sizes['icons'], sizes['unique'], sizes['poolA'], sizes['poolB'], sizes['index'], sizes['poolA'] + sizes['poolB'] + sizes['index']))
    for table, title in (('/', 'Первинна таблиця `/`'), ('\\', 'Додаткова таблиця `\\`')):
        L.append('## %s\n' % title)
        group = [ic for ic in icons if ic[0] == table]
        for s in range(0, len(group), 4):
            chunk = group[s:s + 4]
            cap = '   '.join(('%s%s %s' % (t, c, n)).ljust(24)[:24] for t, c, n, _r, _l in chunk)
            hr = [half_rows(ic[3]) for ic in chunk]
            L.append('```text')
            L.append(cap.rstrip())
            for k in range(H // 2):
                L.append('   '.join(h[k] for h in hr).rstrip())
            L.append('```\n')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='не писати файли; код виходу 1, якщо вони застаріли')
    a = ap.parse_args()
    try:
        icons = parse_txt(TXT)
        validate(icons)
    except Err as e:
        print('ПОМИЛКА:', e)
        return 1
    icons.sort(key=lambda ic: (0 if ic[0] == '/' else 1, ord(ic[1])))
    c, sizes = build_c(icons)
    md = build_md(icons, sizes)
    print('кодів %d, унікальних зображень %d (A %d + B %d), пул A %d Б + B %d Б + індекс %d Б = %d Б' %
          (sizes['icons'], sizes['unique'], sizes['nA'], sizes['nB'], sizes['poolA'], sizes['poolB'], sizes['index'], sizes['poolA'] + sizes['poolB'] + sizes['index']))
    if a.check:
        bad = 0
        for path, text in ((CFILE, c), (MDFILE, md)):
            cur = open(path, encoding='utf-8').read() if os.path.exists(path) else None
            if cur != text:
                print('ЗАСТАРІЛО:', os.path.relpath(path, ROOT), '-- перегенеруйте aprs_icons_gen.py')
                bad = 1
        return bad
    open(CFILE, 'w', encoding='utf-8', newline='\n').write(c)
    os.makedirs(os.path.dirname(MDFILE), exist_ok=True)
    open(MDFILE, 'w', encoding='utf-8', newline='\n').write(md)
    print('записано', os.path.relpath(CFILE, ROOT), 'і', os.path.relpath(MDFILE, ROOT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
