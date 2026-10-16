# -*- coding: utf-8 -*-
# Бібліотека малювання для tools/aprs_icons_seed.py (R20 Ж2): надбудова над Cv з gen_aprs_icons24.py.
import math
from gen_aprs_icons24 import Cv, N, wheel

F57 = {}
def _g(ch, rows):
    F57[ch] = rows
_g('0', ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.")
_g('1', "..#..|.##..|..#..|..#..|..#..|..#..|.###.")
_g('2', ".###.|#...#|....#|...#.|..#..|.#...|#####")
_g('3', "#####|...#.|..#..|...#.|....#|#...#|.###.")
_g('4', "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.")
_g('5', "#####|#....|####.|....#|....#|#...#|.###.")
_g('6', "..##.|.#...|#....|####.|#...#|#...#|.###.")
_g('7', "#####|....#|...#.|..#..|.#...|.#...|.#...")
_g('8', ".###.|#...#|#...#|.###.|#...#|#...#|.###.")
_g('9', ".###.|#...#|#...#|.####|....#|...#.|.##..")
_g('A', ".###.|#...#|#...#|#####|#...#|#...#|#...#")
_g('B', "####.|#...#|#...#|####.|#...#|#...#|####.")
_g('C', ".###.|#...#|#....|#....|#....|#...#|.###.")
_g('D', "####.|#...#|#...#|#...#|#...#|#...#|####.")
_g('E', "#####|#....|#....|####.|#....|#....|#####")
_g('F', "#####|#....|#....|####.|#....|#....|#....")
_g('G', ".###.|#...#|#....|#.###|#...#|#...#|.####")
_g('H', "#...#|#...#|#...#|#####|#...#|#...#|#...#")
_g('I', ".###.|..#..|..#..|..#..|..#..|..#..|.###.")
_g('K', "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#")
_g('L', "#....|#....|#....|#....|#....|#....|#####")
_g('M', "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#")
_g('N', "#...#|##..#|#.#.#|#..##|#...#|#...#|#...#")
_g('O', ".###.|#...#|#...#|#...#|#...#|#...#|.###.")
_g('P', "####.|#...#|#...#|####.|#....|#....|#....")
_g('R', "####.|#...#|#...#|####.|#.#..|#..#.|#...#")
_g('S', ".####|#....|#....|.###.|....#|....#|####.")
_g('T', "#####|..#..|..#..|..#..|..#..|..#..|..#..")
_g('U', "#...#|#...#|#...#|#...#|#...#|#...#|.###.")
_g('V', "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..")
_g('W', "#...#|#...#|#...#|#.#.#|#.#.#|##.##|#...#")
_g('X', "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#")
_g('Y', "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..")
_g('Z', "#####|....#|...#.|..#..|.#...|#....|#####")
_g('$', "..#..|.####|#.#..|.###.|..#.#|####.|..#..")
_g('?', ".###.|#...#|....#|...#.|..#..|.....|..#..")
_g('i', "..#..|.....|.##..|..#..|..#..|..#..|.###.")

class C(Cv):
    def arc(self, cx, cy, r, a0, a1, w=2, v=1):
        """дуга; кути в градусах, 0 = праворуч, 90 = вниз (y вниз)"""
        steps = max(8, int(abs(a1 - a0) * r / 3))
        pts = []
        for i in range(steps + 1):
            a = math.radians(a0 + (a1 - a0) * i / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self.pl(pts, w, v)

    def line(self, x0, y0, x1, y1, w=1, v=1):
        steps = int(max(abs(x1 - x0), abs(y1 - y0), 1) * 3)
        for s in range(steps + 1):
            t = s / steps
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t
            if w <= 1:
                self.px(int(round(x)), int(round(y)), v)
            else:
                r = w / 2.0
                for yy in range(int(math.floor(y - r)) - 1, int(math.ceil(y + r)) + 2):
                    for xx in range(int(math.floor(x - r)) - 1, int(math.ceil(x + r)) + 2):
                        if (xx - x) ** 2 + (yy - y) ** 2 <= (r + 0.05) ** 2:
                            self.px(xx, yy, v)

    def pl(self, pts, w=2, v=1):
        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], w, v)

    def frame(self, x0, y0, x1, y1, w=2, v=1):
        self.rect(x0, y0, x1, y1, v)
        self.rect(x0 + w, y0 + w, x1 - w, y1 - w, 1 - v)

    def text(self, s, x, y, scale=1, bold=False, v=1):
        cx = x
        for ch in s:
            g = F57[ch]
            for r, row in enumerate(g.split('|')):
                for c, k in enumerate(row):
                    if k == '#':
                        for dy in range(scale + (1 if bold else 0)):
                            for dx in range(scale + (1 if bold else 0)):
                                self.px(cx + c * scale + dx, y + r * scale + dy, v)
            cx += 5 * scale + (1 if bold else 0) + 1
        return cx

    def textw(self, s, scale=1, bold=False):
        return len(s) * (5 * scale + (1 if bold else 0) + 1) - 1

    def blit(self, o, dx=0, dy=0, v=1):
        for y in range(N):
            for x in range(N):
                if o.p[y][x]:
                    self.px(x + dx, y + dy, v)

    def clear_circ(self, cx, cy, r):
        self.circ(cx, cy, r, 0)

    def copy(self):
        c = C()
        c.p = [row[:] for row in self.p]
        return c

    def poly_outline(self, pts, k=2):
        t = C(); t.poly(pts); t.hollow(k); self.blit(t)

    def fx(self):
        """дзеркало по горизонталі"""
        c = C()
        for y in range(N):
            for x in range(N):
                c.p[y][N - 1 - x] = self.p[y][x]
        return c

def plaque(txt, top=True):
    """напис жирним 5x7 між двома смугами; 1-2 літери -- у 2x"""
    c = C()
    if len(txt) <= 2:
        w = c.textw(txt, 2)
        c.text(txt, (N - w) // 2, 5, 2)
        c.rect(0, 0, 23, 1); c.rect(0, 22, 23, 23)
    else:
        w = c.textw(txt, 1, True)
        c.text(txt, (N - w) // 2 + 0, 8, 1, True)
        c.rect(0, 3, 23, 4); c.rect(0, 19, 23, 20)
    return c

def boxed(txt):
    c = C()
    c.frame(0, 2, 23, 21, 2)
    w = c.textw(txt, 2)
    if len(txt) <= 1:
        c.text(txt, (N - w) // 2, 5, 2)
    else:
        c.text(txt, (N - w) // 2, 5, 2)
    return c

def cloud_shape(c, ox=0, oy=0, v=1):
    c.circ(8 + ox, 11 + oy, 5, v); c.circ(14 + ox, 8 + oy, 6, v); c.circ(18 + ox, 12 + oy, 4, v)
    c.rect(6 + ox, 11 + oy, 19 + ox, 16 + oy, v)

def sheet_png(items, path, cols=16, scale=3):
    """контактний аркуш для перегляду: items = [(label, Cv)]"""
    from PIL import Image, ImageDraw, ImageFont
    cell = N * scale + 14
    rows = (len(items) + cols - 1) // cols
    img = Image.new('RGB', (cols * (N * scale + 8) + 8, rows * (cell + 6) + 8), (30, 30, 36))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', 10)
    for i, (lab, cv) in enumerate(items):
        gx = 8 + (i % cols) * (N * scale + 8)
        gy = 8 + (i // cols) * (cell + 6)
        d.rectangle([gx - 1, gy - 1, gx + N * scale, gy + N * scale], fill=(222, 228, 214))
        if cv is not None:
            for y in range(N):
                for x in range(N):
                    if cv.p[y][x]:
                        d.rectangle([gx + x * scale, gy + y * scale, gx + x * scale + scale - 1, gy + y * scale + scale - 1], fill=(10, 20, 40))
        d.text((gx, gy + N * scale + 1), lab, fill=(240, 240, 120), font=f)
    img.save(path)
