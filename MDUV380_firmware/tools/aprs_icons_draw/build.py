# -*- coding: utf-8 -*-
"""build.py -- перемальовує tools/aprs_icons.txt з коду малювання (R20-fix). Назви й порядок піктограм беруться з наявного aprs_icons.txt.

Запуск:  python3 MDUV380_firmware/tools/aprs_icons_draw/build.py [вихідний.txt]
Увага: перезаписує aprs_icons.txt (за замовчуванням) -- ручні правки txt буде втрачено; після запуску виконати tools/aprs_icons_gen.py.
Система координат (nd.py): краї пікселів 0..24, ЦЕНТР КАДРУ = (12, 12); піксель увімкнено при покритті >= 50%. Симетричні фігури, намальовані
навколо x=12, виходять симетричними; більше ніяких зсувів на півпікселя (раніше піктограми малювались навколо колонки 12 -- звідси «криві» кола).
"""
import os, sys, importlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import aprs_icons_gen as g

TXT = os.path.join(os.path.dirname(HERE), 'aprs_icons.txt')

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else TXT
    icons = g.parse_txt(TXT)
    hdr = []
    for ln in open(TXT, encoding='utf-8').read().split('\n'):
        if ln.startswith('//'):
            hdr.append(ln)
        elif ln.startswith('@'):
            break
    import prim_a, prim_b, prim_c, prim_d, alt_a, alt_b, fixes
    D = prim_a.D          # усі модулі наповнюють один словник; пізніші перекривають ранні
    lines = list(hdr) + ['']
    for table, code, name, rows, _ in icons:
        k = table + code
        if k not in D:
            raise SystemExit('нема малюнка для %s (%s)' % (k, name))
        lines.append('@ %s %s %s' % (table, code, name))
        lines.extend(D[k]().rows())
        lines.append('')
    open(out, 'w', encoding='utf-8').write('\n'.join(lines))
    print('записано', out, ':', len(icons), 'піктограм')

if __name__ == '__main__':
    main()
