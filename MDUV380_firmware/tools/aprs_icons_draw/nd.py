# -*- coding: utf-8 -*-
# Бібліотека малювання піктограм 24x24 (R20-fix). Координати -- краї пікселів: 0..24, ЦЕНТР КАДРУ = (12, 12).
# Піксель увімкнено, якщо покриття >= 50% (вибірка 4x4). Фігури, симетричні відносно x=12, дають симетричну картинку.
import math
N = 24
SS = 4

def _cov(fn):
    """fn(x, y) -> bool у координатах країв; повертає сітку bool за покриттям >= 50%"""
    g = [[False] * N for _ in range(N)]
    for y in range(N):
        for x in range(N):
            c = 0
            for sy in range(SS):
                for sx in range(SS):
                    if fn(x + (sx + 0.5) / SS, y + (sy + 0.5) / SS):
                        c += 1
            g[y][x] = c * 2 >= SS * SS
    return g

class Ic:
    def __init__(self):
        self.p = [[False] * N for _ in range(N)]
    def _apply(self, fn, v=1):
        m = _cov(fn)
        for y in range(N):
            for x in range(N):
                if m[y][x]:
                    self.p[y][x] = bool(v)
        return self
    def rect(self, x0, y0, x1, y1, v=1):
        return self._apply(lambda x, y: x0 <= x <= x1 and y0 <= y <= y1, v)
    def circ(self, cx, cy, r, v=1):
        return self._apply(lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r, v)
    def ring(self, cx, cy, r, w=2, v=1):
        return self._apply(lambda x, y: (r - w) ** 2 <= (x - cx) ** 2 + (y - cy) ** 2 <= r * r, v)
    def ell(self, cx, cy, rx, ry, v=1):
        return self._apply(lambda x, y: ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1, v)
    def ellring(self, cx, cy, rx, ry, w=2, v=1):
        return self._apply(lambda x, y: (((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1) and
                           (((x - cx) / (rx - w)) ** 2 + ((y - cy) / (ry - w)) ** 2 >= 1), v)
    def poly(self, pts, v=1):
        def inside(x, y):
            c = False
            n = len(pts)
            j = n - 1
            for i in range(n):
                xi, yi = pts[i]; xj, yj = pts[j]
                if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                    c = not c
                j = i
            return c
        return self._apply(inside, v)
    def polyline(self, pts, w=2, v=1):
        for i in range(len(pts) - 1):
            self.seg(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], w, v)
        return self
    def seg(self, x0, y0, x1, y1, w=2, v=1, cap=True):
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        h = w / 2.0
        def f(x, y):
            if L2 == 0:
                t = 0
            else:
                t = ((x - x0) * dx + (y - y0) * dy) / L2
                if not cap:
                    if t < 0 or t > 1:
                        return False
                t = max(0, min(1, t))
            px, py = x0 + t * dx, y0 + t * dy
            return (x - px) ** 2 + (y - py) ** 2 <= h * h
        return self._apply(f, v)
    def arc(self, cx, cy, r, a0, a1, w=2, v=1):
        """дуга, кути в градусах: 0 -- праворуч, 90 -- вниз"""
        steps = max(6, int(abs(a1 - a0) / 6))
        pts = [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / steps)),
                cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / steps))) for i in range(steps + 1)]
        return self.polyline(pts, w, v)
    def frame(self, x0, y0, x1, y1, w=2, v=1):
        self.rect(x0, y0, x1, y1, v)
        self.rect(x0 + w, y0 + w, x1 - w, y1 - w, 1 - v)
        return self
    def bits(self, rows, x0, y0, v=1):
        """малюнок з рядків '#'/'.' з лівим верхнім кутом (x0,y0) (цілі)"""
        for dy, r in enumerate(rows):
            for dx, ch in enumerate(r):
                x, y = x0 + dx, y0 + dy
                if ch == '#' and 0 <= x < N and 0 <= y < N:
                    self.p[y][x] = bool(v)
                elif ch == 'x' and 0 <= x < N and 0 <= y < N:   # 'x' -- стерти
                    self.p[y][x] = False
        return self
    def mirror(self):
        """дорисувати дзеркальне відображення ліворуч-праворуч (малюємо лише ліву половину)"""
        for y in range(N):
            for x in range(12):
                v = self.p[y][x] or self.p[y][N - 1 - x]
                self.p[y][x] = v
                self.p[y][N - 1 - x] = v
        return self
    def mirror_l2r(self):
        """права половина = дзеркало лівої (ліва -- головна)"""
        for y in range(N):
            for x in range(12):
                self.p[y][N - 1 - x] = self.p[y][x]
        return self
    def clear(self, x0, y0, x1, y1):
        return self.rect(x0, y0, x1, y1, 0)
    def blit(self, o, dx=0, dy=0, v=1):
        for y in range(N):
            for x in range(N):
                if o.p[y][x]:
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < N and 0 <= yy < N:
                        self.p[yy][xx] = bool(v)
        return self
    def shift(self, dx, dy):
        o = Ic()
        o.blit(self, dx, dy)
        return o
    def copy(self):
        o = Ic()
        o.p = [r[:] for r in self.p]
        return o
    def rows(self):
        return [''.join('#' if v else '.' for v in r) for r in self.p]

def wheel(I, cx, cy, r=3.2, hub=1.0):
    I.circ(cx, cy, r, 1)
    I.circ(cx, cy, hub, 0)

# --- цифри 8x12 (штрих 2 px), центр кадру співпадає з центром гліфа -----------------------------------------
DIG = {
 '0': ".######.|##....##|##....##|##....##|##....##|##....##|##....##|##....##|##....##|##....##|##....##|.######.",
 '1': "...##...|..###...|.####...|...##...|...##...|...##...|...##...|...##...|...##...|...##...|.######.|.######.",
 '2': ".######.|##....##|......##|......##|.....##.|....##..|...##...|..##....|.##.....|##......|########|########",
 '3': ".######.|##....##|......##|......##|...####.|...####.|......##|......##|......##|##....##|##....##|.######.",
 '4': ".....##.|....###.|...####.|..##.##.|.##..##.|##...##.|########|########|.....##.|.....##.|.....##.|.....##.",
 '5': "########|########|##......|##......|#######.|##....##|......##|......##|......##|##....##|##....##|.######.",
 '6': "..#####.|.##.....|##......|##......|#######.|##....##|##....##|##....##|##....##|##....##|##....##|.######.",
 '7': "########|########|......##|.....##.|.....##.|....##..|....##..|...##...|...##...|..##....|..##....|..##....",
 '8': ".######.|##....##|##....##|##....##|.######.|.######.|##....##|##....##|##....##|##....##|##....##|.######.",
}
_r6 = DIG['6'].split('|')
DIG['9'] = '|'.join(r[::-1] for r in _r6[::-1])
def digit(I, ch, x0=8, y0=6, v=1):
    I.bits(DIG[ch].split('|'), x0, y0, v)
    return I

# --- 5x7 шрифт для написів (як у seed_lib) -----------------------------------------------------------------
F57 = {}
for _ch, _rows in {
 'A': ".###.|#...#|#...#|#####|#...#|#...#|#...#", 'B': "####.|#...#|#...#|####.|#...#|#...#|####.",
 'C': ".###.|#...#|#....|#....|#....|#...#|.###.", 'D': "####.|#...#|#...#|#...#|#...#|#...#|####.",
 'E': "#####|#....|#....|####.|#....|#....|#####", 'F': "#####|#....|#....|####.|#....|#....|#....",
 'G': ".###.|#...#|#....|#.###|#...#|#...#|.####", 'H': "#...#|#...#|#...#|#####|#...#|#...#|#...#",
 'I': ".###.|..#..|..#..|..#..|..#..|..#..|.###.", 'K': "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
 'L': "#....|#....|#....|#....|#....|#....|#####", 'M': "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#",
 'N': "#...#|##..#|#.#.#|#..##|#...#|#...#|#...#", 'O': ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
 'P': "####.|#...#|#...#|####.|#....|#....|#....", 'R': "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
 'S': ".####|#....|#....|.###.|....#|....#|####.", 'T': "#####|..#..|..#..|..#..|..#..|..#..|..#..",
 'U': "#...#|#...#|#...#|#...#|#...#|#...#|.###.", 'V': "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
 'W': "#...#|#...#|#...#|#.#.#|#.#.#|##.##|#...#", 'X': "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
 'Y': "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..", 'Z': "#####|....#|...#.|..#..|.#...|#....|#####",
 '1': "..#..|.##..|..#..|..#..|..#..|..#..|.###.", '2': ".###.|#...#|....#|...#.|..#..|.#...|#####",
 '3': "#####|...#.|..#..|...#.|....#|#...#|.###.",
}.items():
    F57[_ch] = _rows
def text(I, s, x, y, scale=1, bold=False, v=1):
    cx = x
    for ch in s:
        g = F57[ch]
        for r, row in enumerate(g.split('|')):
            for c, k in enumerate(row):
                if k == '#':
                    for dy in range(scale + (1 if bold else 0)):
                        for dx in range(scale + (1 if bold else 0)):
                            xx, yy = cx + c * scale + dx, y + r * scale + dy
                            if 0 <= xx < N and 0 <= yy < N:
                                I.p[yy][xx] = bool(v)
        cx += 5 * scale + (1 if bold else 0) + 1
    return cx
def textw(s, scale=1, bold=False):
    return len(s) * (5 * scale + (1 if bold else 0) + 1) - 1
def ctext(I, s, y, scale=1, bold=False, v=1):
    w = textw(s, scale, bold)
    text(I, s, (N - w) // 2, y, scale, bold, v)
