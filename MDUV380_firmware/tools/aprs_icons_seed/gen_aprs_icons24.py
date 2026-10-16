#!/usr/bin/env python3
# R17 Г5: генератор піктограм APRS 24x24 (XBM, молодший біт ліворуч, 3 байти на рядок = 72 Б).
# Малюємо шарами: set(фігура, 1|0). Контур 2 px -- функцією hollow() (стирає внутрішність, що лишається на відстані >= 2 px від краю).
# Використання: python3 tools_icons24.py c > icons.inc ; python3 tools_icons24.py md > aprs-icons.md ; python3 tools_icons24.py ascii
import math, sys

N = 24


class Cv:
    def __init__(self):
        self.p = [[0] * N for _ in range(N)]

    def px(self, x, y, v):
        if 0 <= x < N and 0 <= y < N:
            self.p[y][x] = v

    def rect(self, x0, y0, x1, y1, v=1):          # включно
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.px(x, y, v)

    def ell(self, cx, cy, rx, ry, v=1):
        for y in range(N):
            for x in range(N):
                if ((x - cx) / (rx + 0.35)) ** 2 + ((y - cy) / (ry + 0.35)) ** 2 <= 1.0:
                    self.px(x, y, v)

    def circ(self, cx, cy, r, v=1):
        self.ell(cx, cy, r, r, v)

    def ring(self, cx, cy, r, w=2, v=1):
        self.circ(cx, cy, r, v)
        self.circ(cx, cy, r - w, 1 - v)

    def poly(self, pts, v=1):
        n = len(pts)
        for y in range(N):
            for x in range(N):
                inside = False
                j = n - 1
                for i in range(n):
                    xi, yi = pts[i]
                    xj, yj = pts[j]
                    if (yi > y + 0.0) != (yj > y + 0.0):
                        xx = (xj - xi) * (y - yi) / (yj - yi) + xi
                        if x + 0.0 < xx:
                            inside = not inside
                    j = i
                if inside:
                    self.px(x, y, v)
        # край включно (щоб вершини не «з'їдались»)
        for i in range(n):
            self.line(pts[i][0], pts[i][1], pts[(i + 1) % n][0], pts[(i + 1) % n][1], 1, v)

    def line(self, x0, y0, x1, y1, w=1, v=1):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1) * 2
        for s in range(steps + 1):
            t = s / steps
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            if w <= 1:
                self.px(int(round(x)), int(round(y)), v)
            else:
                r = w / 2.0
                for yy in range(int(math.floor(y - r)), int(math.ceil(y + r)) + 1):
                    for xx in range(int(math.floor(x - r)), int(math.ceil(x + r)) + 1):
                        if (xx + 0.5 - x - 0.5) ** 2 + (yy - y) ** 2 <= (r + 0.05) ** 2:
                            self.px(xx, yy, v)

    def hollow(self, k=2):
        """Залишити контур завтовшки k px: піксель лишається, якщо в околі k px (Чебишов) є «порожнє» поза силуетом."""
        s = [row[:] for row in self.p]
        for y in range(N):
            for x in range(N):
                if not s[y][x]:
                    continue
                edge = False
                for dy in range(-k, k + 1):
                    for dx in range(-k, k + 1):
                        xx, yy = x + dx, y + dy
                        if xx < 0 or yy < 0 or xx >= N or yy >= N or not s[yy][xx]:
                            edge = True
                self.p[y][x] = 1 if edge else 0

    def bytes(self):
        out = []
        for y in range(N):
            for b in range(3):
                v = 0
                for bit in range(8):
                    if self.p[y][b * 8 + bit]:
                        v |= 1 << bit
                out.append(v)
        return out

    def ascii(self):
        return "\n".join("".join("█" if c else " " for c in row).rstrip() for row in self.p)


def wheel(c, cx, cy, r=3):
    c.circ(cx, cy, r + 1, 0)          # проріз у корпусі навколо колеса
    c.circ(cx, cy, r, 1)
    c.circ(cx, cy, 1, 0)


def car():
    c = Cv()
    c.rect(1, 12, 22, 18)
    c.poly([(5, 12), (8, 6), (16, 6), (19, 12)])
    c.poly([(9, 8), (11, 8), (11, 11), (8, 11)], 0)
    c.poly([(13, 8), (15, 8), (17, 11), (13, 11)], 0)
    wheel(c, 6, 19)
    wheel(c, 17, 19)
    return c


def human():
    c = Cv()
    c.circ(12, 4, 3)
    c.rect(8, 9, 15, 15)
    c.line(8, 10, 3, 16, 3)
    c.line(15, 10, 20, 16, 3)
    c.rect(8, 15, 11, 22)
    c.rect(13, 15, 16, 22)
    c.rect(12, 16, 12, 22, 0)
    return c


def house():
    c = Cv()
    c.poly([(0, 11), (12, 1), (23, 11)])
    c.rect(3, 11, 20, 22)
    c.rect(16, 3, 18, 8)
    c.rect(9, 15, 13, 22, 0)
    c.rect(5, 13, 7, 15, 0)
    c.rect(16, 13, 18, 15, 0)
    return c


def bike():
    c = Cv()
    for cx in (5, 18):
        c.ring(cx, 17, 5, 2)
    c.line(5, 17, 11, 17, 2)
    c.line(11, 17, 8, 8, 2)
    c.line(8, 8, 16, 8, 2)
    c.line(16, 8, 18, 17, 2)
    c.line(5, 6, 10, 6, 2)
    c.line(14, 5, 18, 5, 2)
    c.line(16, 5, 16, 8, 2)
    return c


def moto():
    c = Cv()
    for cx in (5, 19):
        c.ring(cx, 17, 5, 2)
    c.poly([(7, 17), (9, 11), (16, 11), (18, 17)])
    c.rect(5, 9, 13, 11)
    c.line(16, 11, 19, 6, 2)
    c.line(17, 5, 21, 5, 2)
    return c


def truck():
    c = Cv()
    c.rect(0, 4, 14, 17)
    c.rect(2, 6, 12, 15, 0)
    c.poly([(15, 9), (19, 9), (23, 13), (23, 17), (15, 17)])
    c.poly([(17, 10), (19, 10), (21, 13), (17, 13)], 0)
    wheel(c, 5, 19)
    wheel(c, 18, 19)
    return c


def van():
    c = Cv()
    c.poly([(1, 6), (16, 6), (22, 12), (22, 18), (1, 18)])
    c.rect(3, 8, 7, 11, 0)
    c.rect(9, 8, 14, 11, 0)
    c.poly([(16, 8), (17, 8), (20, 11), (16, 11)], 0)
    wheel(c, 6, 19)
    wheel(c, 17, 19)
    return c


def jeep():
    c = Cv()
    c.rect(1, 11, 22, 18)
    c.rect(2, 6, 4, 11)
    c.line(2, 6, 14, 6, 2)
    c.poly([(14, 6), (17, 6), (19, 11), (14, 11)])
    c.rect(5, 12, 12, 13, 0)
    wheel(c, 6, 19, 4)
    wheel(c, 17, 19, 4)
    return c


def bus():
    c = Cv()
    c.rect(0, 3, 23, 18)
    for x in (2, 7, 12, 17):
        c.rect(x, 5, x + 3, 10, 0)
    c.rect(21, 5, 22, 10, 0)
    c.rect(2, 13, 21, 13, 0)
    wheel(c, 6, 19)
    wheel(c, 17, 19)
    return c


def digi():
    c = Cv()
    c.poly([(12, 0), (23, 12), (12, 23), (1, 12)])
    c.hollow(2)
    c.poly([(12, 7), (17, 12), (12, 17), (7, 12)])
    return c


def digi_alt():
    c = Cv()
    c.ring(12, 12, 11, 2)
    c.circ(12, 12, 4)
    return c


def antenna():
    c = Cv()
    c.poly([(12, 8), (19, 23), (5, 23)])
    c.hollow(2)
    c.rect(11, 6, 12, 12)
    c.line(7, 19, 17, 19, 2)
    c.circ(12, 4, 2)
    for r in (6, 10):
        t = Cv()
        t.ring(12, 4, r, 1)
        t.rect(0, 5, 23, 23, 0)
        for y in range(N):
            for x in range(N):
                if t.p[y][x]:
                    c.px(x, y, 1)
    return c


def gateway():
    c = Cv()
    c.ring(12, 12, 11, 2)
    c.rect(1, 11, 22, 12)
    c.ell(12, 12, 6, 11, 1)
    c.ell(12, 12, 4, 9, 0)
    c.rect(11, 1, 12, 22)
    return c


def cloud(c, dy=0):
    c.circ(8, 11 + dy, 5)
    c.circ(14, 8 + dy, 6)
    c.circ(18, 12 + dy, 4)
    c.rect(6, 11 + dy, 19, 16 + dy)


def wx():
    c = Cv()
    cloud(c, -2)
    for x in (7, 12, 17):
        c.line(x, 17, x - 2, 22, 2)
    return c


def cloudy():
    c = Cv()
    cloud(c, 1)
    c.circ(8, 7, 3, 0)
    return c


def sail():
    c = Cv()
    c.poly([(1, 18), (23, 18), (19, 23), (5, 23)])
    c.rect(11, 1, 12, 18)
    c.poly([(10, 2), (10, 16), (2, 16)])
    c.poly([(14, 4), (14, 16), (21, 16)])
    return c


def balloon():
    c = Cv()
    c.circ(12, 9, 8)
    c.hollow(2)
    c.ell(12, 9, 3, 7, 1)
    c.line(7, 16, 10, 20, 1)
    c.line(17, 16, 14, 20, 1)
    c.rect(9, 20, 14, 23)
    return c


def plane():
    c = Cv()
    c.poly([(12, 8), (23, 15), (23, 17), (12, 14), (1, 17), (1, 15)])
    c.ell(12, 12, 2, 10, 1)
    c.poly([(12, 18), (17, 23), (7, 23)])
    return c


def phone():
    c = Cv()
    c.rect(6, 1, 17, 22)
    c.rect(8, 3, 15, 10, 0)
    for yy in (13, 16, 19):
        for xx in (9, 12, 15):
            c.rect(xx - 1, yy - 1, xx, yy, 0)
    return c


def tcpip():
    c = Cv()
    c.rect(1, 2, 22, 16)
    c.rect(3, 4, 20, 14, 0)
    c.rect(5, 6, 12, 7)
    c.rect(5, 10, 16, 11)
    c.rect(10, 17, 13, 19)
    c.rect(5, 20, 18, 22)
    return c


def police():
    c = Cv()
    c.poly([(2, 1), (21, 1), (21, 12), (12, 23), (2, 12)])
    c.hollow(2)
    c.poly([(12, 6), (16, 11), (12, 16), (8, 11)])
    return c


def emerg():
    c = Cv()
    c.poly([(12, 0), (23, 22), (1, 22)])
    c.hollow(2)
    c.rect(11, 8, 13, 15)
    c.rect(11, 17, 13, 19)
    return c


def tri():
    c = Cv()
    c.poly([(12, 1), (23, 22), (1, 22)])
    c.poly([(12, 9), (17, 18), (7, 18)], 0)
    return c


ICONS = [
    ('/', '>', 'авто', car), ('/', '[', 'людина', human), ('/', '-', 'будинок', house), ('/', 'b', 'велосипед', bike),
    ('/', '<', 'мотоцикл', moto), ('/', 'k', 'вантажівка', truck), ('/', 'v', 'фургон', van), ('/', 'j', 'джип', jeep),
    ('/', 'U', 'автобус', bus), ('/', '#', 'діджіпітер', digi), ('/', 'r', 'ретранслятор', antenna), ('/', '&', 'шлюз', gateway),
    ('/', '_', 'метеостанція', wx), ('/', 'Y', 'яхта', sail), ('/', 'O', 'повітряна куля', balloon), ('/', '^', 'літак', plane),
    ('/', '$', 'телефон', phone), ('/', 'I', 'TCP/IP', tcpip), ('/', '(', 'хмарно', cloudy), ('/', '!', 'поліція', police),
    ('\\', '!', 'аварія', emerg), ('\\', 'n', 'трикутник', tri), ('\\', '#', 'діджіпітер (дод.)', digi_alt),
]

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'ascii'
    if mode == 'c':
        for t, code, name, fn in ICONS:
            b = fn().bytes()
            tc = "'\\\\'" if t == '\\' else "'%s'" % t
            cc = "'\\\\'" if code == '\\' else "'%s'" % code
            print("\t{ %s, %s, { %s } }," % (tc, cc, ", ".join("0x%02X" % v for v in b)))
    elif mode == 'md':
        print("# Піктограми символів APRS (R14, R17)\n")
        print("Монохромні 24x24 (XBM, 72 байти кожна), const у flash — `MDUV380_firmware/application/source/functions/aprs_icons.c`. Малюються у вікні")
        print("маяка (x = 4, y = 100) через `displayDrawXBitmap()`; у вибірнику символу «Режиму APRS» — ті самі. Таблиця `/` — первинна, `\\` — додаткова;")
        print("таблиця-цифра/літера — додаткова піктограма плюс знак таблиці в блоці 8x8 з інверсним тлом у правому нижньому куті (накладка).")
        print("Символу нема в наборі — рамка 24x24 із самим знаком (FONT_SIZE_1). Додаткова таблиця для кодів `> k u v s ^ _ & S` бере піктограму первинної.\n")
        print("Файл `aprs_icons.c` (масив `icons[]`) згенеровано скриптом `tools/gen_aprs_icons24.py` (підкоманда `c`), цей файл — підкомандою `md`.\n")
        for t, code, name, fn in ICONS:
            print("## `%s%s` — %s\n\n```" % (t, code, name))
            print(fn().ascii())
            print("```\n")
    else:
        for t, code, name, fn in ICONS:
            print("=== %s%s %s" % (t, code, name))
            print(fn().ascii())
