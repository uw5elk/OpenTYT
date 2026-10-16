# -*- coding: utf-8 -*-
from seed_lib import *

def policecar():
    c = C()
    c.poly([(1, 12), (5, 12), (8, 6), (16, 6), (19, 12), (23, 12), (23, 18), (1, 18)])
    c.poly([(9, 8), (11, 8), (11, 11), (8, 11)], 0); c.poly([(13, 8), (15, 8), (17, 11), (13, 11)], 0)
    c.rect(10, 2, 14, 4)
    c.rect(8, 3, 9, 3); c.rect(15, 3, 16, 3)
    wheel(c, 6, 19); wheel(c, 17, 19)
    return c

def camp():
    c = C()
    c.poly([(8, 3), (16, 21), (0, 21)])
    c.poly([(8, 11), (11, 21), (5, 21)], 0)
    c.circ(19, 9, 4); c.rect(18, 13, 20, 21)
    c.rect(0, 21, 23, 22)
    return c

def bank():
    c = C()
    c.poly([(12, 0), (23, 7), (1, 7)])
    c.rect(1, 8, 22, 9)
    for x in (3, 9, 15, 20):
        c.rect(x, 10, x + 1, 18)
    c.rect(1, 19, 22, 20); c.rect(0, 21, 23, 22)
    return c

def powerplant():
    c = C()
    c.poly([(5, 8), (19, 8), (17, 23), (7, 23)])
    c.poly([(11, 10), (14, 10), (12, 15), (15, 15), (10, 21), (11, 16), (8, 16)], 0)
    c.circ(9, 3, 3); c.circ(15, 2, 2)
    return c

def crash():
    c = C()
    c.poly([(12, 0), (14, 7), (19, 2), (17, 9), (23, 8), (18, 13), (23, 18), (16, 16), (17, 23), (12, 18), (7, 23), (8, 16), (1, 18), (6, 13), (0, 8), (7, 9), (5, 2), (10, 7)])
    c.poly([(12, 6), (14, 11), (12, 15), (10, 11)], 0)
    return c

def cloud_only():
    c = C()
    cloud_shape(c, 0, 3)
    return c

def meo():
    c = C()
    c.ring(12, 12, 6, 2)
    c.arc(12, 12, 11, 0, 360, 1)
    c.circ(21, 7, 3); c.rect(19, 5, 23, 6, 0) if False else None
    return c

def snowflake():
    c = C()
    for a in (0, 60, 120):
        r = math.radians(a)
        c.line(12 - 11 * math.cos(r), 12 - 11 * math.sin(r), 12 + 11 * math.cos(r), 12 + 11 * math.sin(r), 2)
    for a in (0, 60, 120, 180, 240, 300):
        r = math.radians(a)
        bx, by = 12 + 7 * math.cos(r), 12 + 7 * math.sin(r)
        for da in (-50, 50):
            q = math.radians(a + da)
            c.line(bx, by, bx + 3.5 * math.cos(q), by + 3.5 * math.sin(q), 2)
    c.circ(12, 12, 2)
    return c

def church():
    c = C()
    c.rect(11, 0, 12, 7); c.rect(8, 2, 15, 3)
    c.poly([(12, 8), (17, 13), (17, 22), (7, 22), (7, 13)])
    c.rect(10, 16, 13, 22, 0)
    c.rect(0, 14, 6, 22); c.rect(18, 14, 23, 22)
    return c

def question():
    c = C()
    c.arc(12, 8, 6, 180, 405, 4)
    c.pl([(17, 11), (12, 15), (12, 17)], 4)
    c.rect(10, 20, 13, 23)
    return c

def ring0():
    c = C(); c.ring(12, 12, 11, 4); return c

def wifi():
    c = C()
    c.circ(12, 19, 3)
    c.arc(12, 19, 8, 220, 320, 3)
    c.arc(12, 19, 13, 230, 310, 3)
    c.arc(12, 19, 18, 238, 302, 3) if False else None
    return c

def pump():
    c = C()
    c.frame(2, 2, 14, 22, 2)
    c.rect(4, 4, 12, 9)
    c.rect(0, 22, 17, 23)
    c.pl([(14, 8), (19, 8), (20, 18)], 2)
    c.rect(19, 18, 21, 20)
    return c

def hail():
    c = C()
    cloud_shape(c, 0, -3)
    for x, y in ((6, 16), (12, 19), (17, 16), (9, 22), (20, 21)):
        c.circ(x, y, 2) if (x, y) not in ((9, 22), (20, 21)) else None
    return c

def park():
    c = C()
    c.circ(8, 7, 7); c.rect(7, 12, 9, 22)
    c.rect(13, 14, 23, 15); c.rect(14, 15, 15, 22); c.rect(21, 15, 22, 22)
    c.rect(12, 18, 23, 19)
    return c

def advisory():
    c = C()
    c.rect(3, 1, 5, 23)
    c.poly([(5, 2), (23, 2), (23, 14), (5, 14)])
    c.poly([(8, 5), (20, 5), (20, 11), (8, 11)], 0)
    return c

def keypad():
    c = C()
    for yy in (2, 8, 14, 20):
        for xx in (3, 10, 17):
            c.rect(xx, yy, xx + 3, yy + 2)
    return c

def hurricane():
    c = C()
    for off in (0, 120, 240):
        pts = []
        for i in range(0, 22):
            a = math.radians(off + i * 8)
            r = 4 + i * 0.35
            pts.append((11.5 + r * math.cos(a), 11.5 + r * math.sin(a)))
        c.pl(pts, 3)
    c.ring(11.5, 11.5, 4, 2)
    return c

def boxsq():
    c = C(); c.frame(1, 1, 22, 22, 3); return c

def blowsnow():
    c = C()
    for y, x0, x1 in ((4, 0, 17), (11, 3, 23), (18, 0, 14)):
        c.line(x0, y, x1, y, 2)
    c.pl([(17, 4), (20, 2), (22, 4)], 2); c.pl([(23, 11), (23, 13)], 2)
    c.pl([(14, 18), (17, 16), (19, 18)], 2)
    for x, y in ((3, 7), (9, 14), (19, 21)):
        c.circ(x, y, 1)
    return c

def anchor():
    c = C()
    c.ring(12, 3, 3, 2)
    c.rect(11, 6, 12, 21); c.rect(7, 9, 16, 10)
    c.arc(12, 14, 10, 20, 160, 3)
    c.poly([(0, 14), (4, 12), (4, 18)]); c.poly([(23, 14), (19, 12), (19, 18)])
    return c

def drizzle():
    c = C()
    cloud_shape(c, 0, -3)
    for x in (7, 12, 17):
        c.rect(x, 18, x + 1, 19); c.rect(x - 1, 21, x, 22)
    return c

def smoke():
    c = C()
    for y in (3, 10, 17):
        c.pl([(0, y + 3), (4, y), (8, y + 3), (12, y), (16, y + 3), (20, y), (23, y + 2)], 3)
    return c

def freezing():
    c = C()
    cloud_shape(c, 0, -4)
    c.line(6, 15, 4, 22, 2); c.line(12, 15, 10, 22, 2)
    c.circ(17, 19, 3); c.circ(17, 19, 1, 0)
    return c

def snowshower():
    c = C()
    cloud_shape(c, 0, -4)
    for x in (6, 12, 18):
        c.line(x - 2, 20, x + 2, 20, 2); c.line(x, 17, x, 23, 2)
    return c

def haze():
    c = C()
    c.ell(12, 8, 8, 8)
    c.rect(0, 8, 23, 9, 0) if False else None
    c.rect(0, 11, 23, 23, 0)
    for y in (12, 16, 20):
        c.rect(0, y, 23, y + 1)
    c.rect(0, 14, 23, 14, 0)
    return c

def rainshower():
    c = C()
    cloud_shape(c, 0, -4)
    for x in (7, 12, 17):
        c.line(x, 14, x - 3, 22, 2)
    c.line(22, 14, 19, 22, 2) if False else None
    return c

def lightning():
    c = C()
    c.poly([(15, 0), (4, 13), (10, 13), (7, 23), (20, 8), (13, 8), (17, 0)])
    return c

def lighthouse():
    c = C()
    c.poly([(9, 8), (15, 8), (17, 22), (7, 22)])
    c.rect(9, 12, 15, 13, 0); c.rect(8, 17, 16, 18, 0)
    c.rect(8, 3, 15, 7); c.poly([(8, 3), (12, 0), (15, 3)])
    c.rect(10, 4, 13, 6, 0)
    c.pl([(3, 4), (7, 5)], 2); c.pl([(21, 4), (17, 5)], 2)
    c.rect(5, 22, 18, 23)
    return c

def buoy():
    c = C()
    c.rect(11, 0, 12, 7); c.circ(12, 1, 2)
    c.poly([(9, 7), (15, 7), (17, 14), (7, 14)])
    c.rect(5, 14, 18, 17)
    c.pl([(0, 20), (3, 18), (6, 20), (9, 18), (12, 20), (15, 18), (18, 20), (21, 18), (23, 19)], 2)
    return c

def rocket():
    c = C()
    c.poly([(12, 0), (16, 5), (16, 16), (8, 16), (8, 5)])
    c.circ(12, 8, 2, 0)
    c.poly([(8, 12), (3, 18), (3, 21), (8, 18)]); c.poly([(16, 12), (21, 18), (21, 21), (16, 18)])
    c.poly([(9, 17), (15, 17), (12, 23)])
    return c

def parking():
    return boxed("P")

def quake():
    c = C()
    c.pl([(0, 12), (5, 12), (8, 3), (12, 21), (16, 6), (18, 12), (23, 12)], 2)
    c.rect(0, 22, 23, 23)
    return c

def restaurant():
    c = C()
    c.rect(4, 0, 5, 9); c.rect(7, 0, 8, 9); c.rect(10, 0, 11, 9)
    c.rect(4, 9, 11, 11); c.rect(6, 11, 9, 23)
    c.poly([(17, 0), (21, 3), (21, 12), (18, 14), (18, 23), (16, 23), (16, 14), (16, 6)])
    return c

def thunderstorm():
    c = C()
    cloud_shape(c, 0, -5)
    c.poly([(14, 11), (8, 18), (12, 18), (10, 23), (17, 15), (13, 15), (16, 11)])
    return c

def sunny():
    c = C()
    c.circ(12, 12, 6)
    for a in range(0, 360, 45):
        r = math.radians(a)
        c.line(12 + 9 * math.cos(r), 12 + 9 * math.sin(r), 12 + 12 * math.cos(r), 12 + 12 * math.sin(r), 2)
    return c

def vortac():
    c = C()
    c.poly([(7, 1), (17, 1), (23, 12), (17, 23), (7, 23), (1, 12)]); c.hollow(2)
    c.circ(12, 12, 3)
    c.rect(11, 0, 12, 4); c.rect(11, 20, 12, 23)
    return c

def pharmacy():
    c = C()
    c.frame(1, 1, 22, 22, 2)
    c.text("R", 3, 5, 2)
    c.line(14, 12, 20, 20, 2); c.line(20, 12, 14, 20, 2)
    return c

def radio():
    c = C()
    c.rect(8, 6, 17, 22)
    c.rect(10, 8, 15, 12, 0)
    c.rect(10, 15, 15, 16, 0); c.rect(10, 18, 15, 19, 0)
    c.rect(18, 4, 19, 12)
    c.rect(5, 8, 7, 14)
    c.pl([(21, 2), (21, 6)], 1)
    return c

def wallcloud():
    c = C()
    cloud_shape(c, 0, -5)
    c.poly([(8, 14), (16, 14), (15, 20), (9, 20)])
    c.rect(10, 20, 14, 23)
    return c

def gpspin():
    c = C()
    c.poly([(12, 23), (3, 12), (3, 7), (7, 2), (17, 2), (21, 7), (21, 12)])
    c.circ(12, 9, 4, 0)
    return c

def umbrella():
    c = C()
    c.ell(12, 10, 11, 9)
    c.rect(0, 11, 23, 20, 0)
    c.rect(0, 10, 23, 11)
    c.rect(11, 11, 12, 19)
    c.arc(10, 19, 3, 0, 180, 2)
    return c

def arrl():
    c = C()
    c.poly([(12, 0), (23, 12), (12, 23), (1, 12)]); c.hollow(2)
    c.text("A", 9, 8, 1, True) if False else None
    c.rect(11, 8, 12, 15); c.rect(9, 10, 14, 11)
    c.poly([(8, 16), (12, 7), (16, 16)], 0) if False else None
    return c

def dust():
    c = C()
    for y, x0, x1 in ((4, 0, 12), (11, 4, 23), (18, 0, 10)):
        c.line(x0, y, x1, y, 2)
    for x, y in ((14, 4), (18, 3), (20, 5), (6, 8), (10, 14), (14, 17), (18, 19), (21, 16)):
        c.rect(x, y, x + 1, y + 1)
    return c

def civildef():
    c = C()
    c.ring(12, 12, 11, 2)
    c.poly([(12, 5), (18, 17), (6, 17)]); c.poly([(12, 10), (15, 15), (9, 15)], 0)
    return c

def dxspot():
    c = C()
    c.ring(12, 12, 8, 2)
    c.rect(11, 0, 12, 6); c.rect(11, 17, 12, 23); c.rect(0, 11, 6, 12); c.rect(17, 11, 23, 12)
    c.circ(12, 12, 2)
    return c

def sleet():
    c = C()
    cloud_shape(c, 0, -5)
    c.line(6, 15, 4, 22, 2); c.line(12, 15, 10, 22, 2)
    c.circ(18, 18, 2); c.circ(15, 22, 1) if False else None
    c.rect(16, 21, 18, 22)
    return c

def funnel():
    c = C()
    cloud_shape(c, 0, -6)
    c.poly([(4, 11), (20, 11), (14, 16), (13, 22), (10, 22), (10, 16)])
    return c

def gale():
    c = C()
    c.rect(2, 1, 3, 23)
    c.poly([(3, 2), (12, 2), (12, 7), (3, 7)])
    c.poly([(12, 2), (22, 2), (22, 7), (12, 7)], 0)
    c.rect(12, 2, 22, 7)
    c.rect(14, 4, 20, 5, 0)
    c.rect(3, 9, 12, 14)
    return c

def store():
    c = C()
    c.poly([(1, 2), (22, 2), (23, 9), (0, 9)])
    for x in (4, 10, 16):
        c.rect(x, 3, x + 2, 8, 0)
    c.frame(2, 9, 21, 22, 2)
    c.rect(9, 13, 14, 22, 0)
    return c

def star():
    c = C()
    pts = []
    for i in range(10):
        r = 11 if i % 2 == 0 else 4.6
        a = math.radians(-90 + i * 36)
        pts.append((11.5 + r * math.cos(a), 12.5 + r * math.sin(a)))
    c.poly([(round(x), round(y)) for x, y in pts])
    return c

def excavator():
    c = C()
    c.rect(1, 19, 15, 22); c.rect(3, 20, 13, 21, 0)
    c.rect(2, 11, 10, 18)
    c.rect(3, 12, 6, 15, 0)
    c.pl([(9, 12), (14, 4), (20, 8)], 3)
    c.poly([(19, 7), (23, 9), (22, 14), (18, 12)])
    return c

def areas():
    c = C()
    for x in range(0, 24, 6):
        c.rect(x, 1, x + 3, 2); c.rect(x, 21, x + 3, 22)
    for y in range(0, 24, 6):
        c.rect(1, y, 2, y + 3); c.rect(21, y, 22, y + 3)
    c.ring(12, 12, 5, 2)
    return c

def signpost():
    c = C()
    c.frame(0, 1, 23, 13, 2)
    c.text("123", 4, 4, 1)
    c.rect(11, 13, 12, 23)
    return c

def smallring():
    c = C(); c.ring(12, 12, 6, 3); return c

def partly():
    c = C()
    c.circ(8, 8, 6)
    for a in range(180, 300, 40):
        pass
    c.line(8, 0, 8, 1, 2); c.line(0, 8, 1, 8, 2); c.line(2, 2, 3, 3, 2); c.line(14, 2, 13, 3, 2)
    cloud_shape(c, 1, 5, 0)
    cloud_shape(c, 1, 5, 1)
    c.circ(8, 8, 6, 0) if False else None
    return c

def restrooms():
    c = C()
    c.circ(5, 3, 2); c.rect(3, 6, 7, 14); c.rect(3, 14, 4, 22); c.rect(6, 14, 7, 22)
    c.rect(0, 7, 2, 13); c.rect(8, 7, 10, 13)
    c.circ(18, 3, 2); c.poly([(18, 6), (22, 17), (14, 17)])
    c.rect(16, 17, 17, 22); c.rect(19, 17, 20, 22)
    return c

def ship():
    c = C()
    c.poly([(0, 15), (23, 15), (19, 21), (4, 21)])
    c.rect(4, 9, 17, 14); c.rect(6, 11, 15, 12, 0)
    c.rect(8, 4, 12, 9)
    c.rect(9, 1, 11, 4)
    c.line(15, 3, 15, 9, 1)
    return c

def tornado():
    c = C()
    c.rect(1, 1, 22, 3)
    c.rect(3, 6, 20, 8)
    c.rect(6, 11, 17, 13)
    c.rect(9, 16, 14, 18)
    c.rect(11, 20, 13, 22)
    return c

def flood():
    c = C()
    for y in (4, 11, 18):
        c.pl([(0, y + 2), (3, y), (6, y + 2), (9, y), (12, y + 2), (15, y), (18, y + 2), (21, y), (23, y + 1)], 3)
    return c

def barrier():
    c = C()
    c.rect(0, 4, 23, 11)
    for x in range(-4, 24, 8):
        c.poly([(x, 4), (x + 4, 4), (x + 8, 11), (x + 4, 11)], 0)
    c.rect(3, 11, 5, 22); c.rect(18, 11, 20, 22)
    return c

def binoculars():
    c = C()
    c.ring(6, 15, 6, 2); c.ring(17, 15, 6, 2)
    c.rect(2, 3, 9, 9); c.rect(14, 3, 21, 9)
    c.rect(9, 5, 14, 7)
    c.rect(4, 4, 7, 5, 0) if False else None
    return c

def fog():
    c = C()
    for y, x0, x1 in ((3, 0, 17), (9, 6, 23), (15, 0, 17), (21, 6, 23)):
        c.line(x0, y, x1, y, 3)
    return c

# ---- ревізія 1 ----
def cloud_grow(c, ox, oy, g, v):
    c.circ(8 + ox, 11 + oy, 5 + g, v); c.circ(14 + ox, 8 + oy, 6 + g, v); c.circ(18 + ox, 12 + oy, 4 + g, v)
    c.rect(6 + ox, 11 + oy - g, 19 + ox, 16 + oy + g, v)

def partly():
    c = C()
    c.circ(8, 8, 6)
    for a in range(0, 360, 45):
        r = math.radians(a)
        c.line(8 + 8 * math.cos(r), 8 + 8 * math.sin(r), 8 + 10.5 * math.cos(r), 8 + 10.5 * math.sin(r), 2)
    cloud_grow(c, 1, 7, 1, 0)
    cloud_grow(c, 1, 7, 0, 1)
    c.rect(0, 23, 23, 23, 0)
    return c

def pharmacy():
    return plaque("RX")

def gale():
    c = C()
    c.rect(2, 0, 4, 23)
    c.poly([(5, 2), (22, 6), (5, 10)])
    c.poly([(5, 13), (22, 17), (5, 21)])
    return c

def barrier():
    c = C()
    c.rect(0, 3, 23, 11)
    for x in (5, 13, 21):
        c.line(x, 3, x - 5, 11, 2, 0)
    c.rect(3, 11, 5, 22); c.rect(18, 11, 20, 22)
    return c

def blowsnow():
    c = C()
    c.rect(0, 3, 15, 5); c.rect(5, 10, 23, 12); c.rect(0, 17, 12, 19)
    c.rect(18, 2, 20, 4); c.rect(17, 16, 19, 18); c.rect(2, 7, 4, 8); c.rect(9, 14, 11, 15); c.rect(20, 20, 22, 22)
    return c

def powerplant():
    c = C()
    c.poly([(4, 7), (20, 7), (15, 13), (19, 23), (5, 23), (9, 13)])
    c.poly([(13, 14), (9, 19), (12, 19), (11, 22), (16, 17), (13, 17), (14, 14)], 0)
    c.circ(9, 3, 3); c.circ(16, 3, 2)
    return c

def meo():
    c = C()
    c.ring(12, 12, 11, 2)
    c.circ(12, 12, 4)
    c.rect(18, 2, 23, 7); c.rect(19, 3, 22, 6, 0); c.rect(20, 4, 21, 5)
    return c

def mars():
    G = {'M': "#...#|##.##|#.#.#|#...#|#...#", 'A': ".###.|#...#|#####|#...#|#...#", 'R': "####.|#...#|####.|#..#.|#...#", 'S': ".####|#....|.###.|....#|####."}
    c = C()
    x = 0
    for ch in "MARS":
        for r, row in enumerate(G[ch].split('|')):
            for k, t in enumerate(row):
                if t == '#':
                    c.rect(x + k, 7 + r * 2, x + k, 8 + r * 2)
        x += 6
    c.rect(0, 2, 23, 3); c.rect(0, 20, 23, 21)
    return c

def kenwood():
    return plaque("K")

# ---- ревізія 2 ----
def partly():
    c = C()
    c.circ(7, 7, 5)
    for a in range(0, 360, 45):
        r = math.radians(a)
        c.line(7 + 7.5 * math.cos(r), 7 + 7.5 * math.sin(r), 7 + 10 * math.cos(r), 7 + 10 * math.sin(r), 2)
    cloud_grow(c, 2, 8, 2, 0)
    cloud_grow(c, 2, 8, 0, 1)
    return c

def barrier():
    c = C()
    c.rect(0, 3, 23, 11)
    for x in (6, 14, 22):
        c.poly([(x, 3), (x + 3, 3), (x - 2, 11), (x - 5, 11)], 0)
    c.rect(3, 11, 5, 22); c.rect(18, 11, 20, 22)
    return c

def partly():
    c = C()
    c.circ(8, 8, 4)
    for a in (135, 180, 225, 270, 315):
        r = math.radians(a)
        c.line(8 + 6.3 * math.cos(r), 8 + 6.3 * math.sin(r), 8 + 8.6 * math.cos(r), 8 + 8.6 * math.sin(r), 2)
    def cl(g, v):
        c.circ(10, 17, 4 + g, v); c.circ(16, 14, 5 + g, v); c.circ(19, 18, 3 + g, v); c.rect(8, 17 - g, 20, 21 + g, v)
    cl(2, 0); cl(0, 1)
    return c
