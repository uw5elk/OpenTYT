# -*- coding: utf-8 -*-
import math
from nd import *
from prim_a import icon, D, star
from prim_b import car, wheel_r
from prim_c import cloud
from alt_a import ref, rays

@icon('\\G')
def _():
    I = Ic()
    cloud(I, -5)
    for x0, y0 in ((6, 19.5), (12, 22), (18, 19.5)):
        I.seg(x0 - 1.8, y0, x0 + 1.8, y0, 1.8)
        I.seg(x0, y0 - 1.8, x0, y0 + 1.8, 1.8)
    return I

@icon('\\H')
def _():
    I = Ic()
    I.circ(12, 13, 8)
    I.rect(0, 13, 24, 24, 0)
    I.rect(1.5, 15, 22.5, 17.2)
    I.rect(4.5, 19, 19.5, 21.2)
    rays(I, 12, 13, 10.4, 12, 1, 2, -90)
    I.seg(3.2, 6.2, 4.6, 7.6, 2)
    I.seg(20.8, 6.2, 19.4, 7.6, 2)
    return I

@icon('\\I')
def _():
    I = Ic()
    cloud(I, -5)
    for x0 in (4.5, 9.5, 14.5, 19.5):
        I.seg(x0 + 1.5, 14, x0 - 1.0, 21.2, 1.9)
    return I

@icon('\\J')
def _():
    I = Ic()
    I.poly([(15, 1), (5, 13.4), (11, 13.4), (8.6, 23), (19.4, 9.4), (13, 9.4)])
    return I

@icon('\\K')
def _():
    I = Ic()
    I.frame(0.5, 1, 23.5, 23, 2.2)
    text(I, 'K', 7, 5, 2)
    return I

@icon('\\L')
def _():
    I = Ic()
    I.poly([(8, 22.8), (9.6, 9.5), (14.4, 9.5), (16, 22.8)])
    I.rect(9.2, 5.5, 14.8, 9.5)
    I.poly([(8.4, 5.4), (12, 1.2), (15.6, 5.4)])
    I.rect(10.8, 6.6, 13.2, 8.6, 0)
    I.rect(8.8, 14, 15.2, 16, 0)
    I.rect(5, 21.8, 19, 23.6)
    I.rect(0.8, 4.2, 6.2, 5.8)
    I.rect(17.8, 4.2, 23.2, 5.8)
    I.rect(2, 7.4, 7.2, 8.8)
    I.rect(16.8, 7.4, 22, 8.8)
    return I

@icon('\\M')
def _():
    I = Ic()
    I.rect(0, 2, 24, 4.5)
    I.rect(0, 19.5, 24, 22)
    text(I, 'MARS', 0, 8, 1, False)
    return I

@icon('\\N')
def _():
    I = Ic()
    I.poly([(6.5, 16), (8.8, 8.5), (15.2, 8.5), (17.5, 16)])
    I.rect(9.4, 11.4, 14.6, 13.2, 0)
    I.seg(12, 8.5, 12, 2.8, 2)
    I.circ(12, 2.6, 1.8)
    I.polyline([(0.8, 20), (3.5, 18), (6.2, 20), (8.9, 18), (11.6, 20), (14.3, 18), (17, 20), (19.7, 18), (22.4, 20)], 2)
    I.polyline([(0.8, 23), (3.5, 21.4), (6.2, 23), (8.9, 21.4), (11.6, 23), (14.3, 21.4), (17, 23), (19.7, 21.4), (22.4, 23)], 1.6)
    return I

@icon('\\O')
def _():
    I = Ic()
    I.poly([(12, 0.5), (15.8, 6.5), (15.8, 17), (8.2, 17), (8.2, 6.5)])
    I.circ(12, 9.2, 2.2, 0)
    I.poly([(8.2, 11.5), (3, 19), (8.2, 17)])
    I.poly([(15.8, 11.5), (21, 19), (15.8, 17)])
    I.poly([(10, 17.8), (12, 23.5), (14, 17.8)])
    return I

@icon('\\P')
def _():
    I = Ic()
    I.frame(1, 1, 23, 23, 2.2)
    text(I, 'P', 7, 5, 2)
    return I

@icon('\\Q')
def _():
    I = Ic()
    I.polyline([(0.5, 12), (4, 12), (6.2, 4.5), (9.4, 19.5), (12, 2.5), (14.8, 21.5), (17.4, 7.5), (19.6, 12), (23.5, 12)], 2.2)
    return I

@icon('\\R')
def _():
    I = Ic()
    for x0 in (3, 5.7, 8.4):
        I.rect(x0, 1.5, x0 + 1.5, 8.5)
    I.rect(3, 7, 9.9, 9.6)
    I.rect(5.2, 9, 7.7, 22.5)
    I.poly([(14.5, 2), (16.6, 1.5), (19, 3), (19, 12.5), (14.5, 12.5)])
    I.rect(15.5, 12, 18.5, 22.5)
    return I

@icon('\\S')
def _():
    I = Ic()
    I.rect(9, 8, 15, 16)
    I.rect(1, 6, 8, 18)
    I.rect(8, 11, 9, 13)
    I.mirror()
    I.rect(1, 11.4, 8, 12.6, 0)
    I.rect(15.9, 11.4, 23, 12.6, 0)
    I.rect(4, 6, 5.2, 18, 0)
    I.rect(18.8, 6, 20, 18, 0)
    I.seg(12, 8, 12, 4, 2)
    I.circ(12, 3.2, 1.8)
    return I

@icon('\\T')
def _():
    I = Ic()
    cloud(I, -5)
    I.poly([(13.5, 11.5), (8.2, 18.2), (11.4, 18.2), (10, 23), (16, 15.8), (12.6, 15.8)])
    return I

@icon('\\U')
def _():
    I = Ic()
    I.circ(12, 12, 5.2)
    rays(I, 12, 12, 7.6, 11, 8, 2.2, -90)
    return I

@icon('\\V')
def _():
    I = Ic()
    pts = [(12 + 11.2 * math.cos(math.radians(60 * k)), 12 + 11.2 * math.sin(math.radians(60 * k))) for k in range(6)]
    pts2 = [(12 + 8.2 * math.cos(math.radians(60 * k)), 12 + 8.2 * math.sin(math.radians(60 * k))) for k in range(6)]
    I.poly(pts)
    I.poly(pts2, 0)
    I.circ(12, 12, 2.6)
    return I

@icon('\\W')
def _():
    I = Ic()
    I.circ(12, 12, 2.6)
    for a in (-90, 30, 150):
        r = math.radians(a)
        ex, ey = 12 + 5.8 * math.cos(r), 12 + 5.8 * math.sin(r)
        I.seg(12, 12, ex, ey, 2)
        I.ring(12 + 8.2 * math.cos(r), 12 + 8.2 * math.sin(r), 3.4, 1.8)
        I.circ(12 + 8.2 * math.cos(r), 12 + 8.2 * math.sin(r), 1.6)
    return I

@icon('\\X')
def _():
    I = Ic()
    I.ring(12, 12, 11.2, 2.2)
    I.rect(10.4, 5.5, 13.6, 18.5)
    I.rect(5.5, 10.4, 18.5, 13.6)
    return I

@icon('\\Y')
def _():
    I = Ic()
    I.frame(7, 8, 18, 23, 2.2)
    I.rect(9.2, 10.4, 15.8, 13.2)
    I.rect(9.2, 16, 15.8, 17.2, 0)
    I.rect(9.2, 19, 15.8, 20.2, 0)
    I.seg(9.5, 8, 9.5, 1.8, 2)
    I.rect(13, 3.2, 16.4, 8)
    return I

@icon('\\[')
def _():
    I = Ic()
    cloud(I, -5)
    I.poly([(6.5, 14), (17.5, 14), (14.8, 22), (9.2, 22)])
    return I

@icon('\\\\')
def _():
    I = Ic()
    I.circ(12, 8.6, 7.4)
    I.poly([(5.2, 12), (12, 23.4), (18.8, 12)])
    I.circ(12, 8.6, 3.2, 0)
    return I

@icon('\\^')
def _():
    I = Ic()
    I.poly([(12, 0.5), (10.6, 5), (10.6, 11), (1.5, 18), (1.5, 20.8), (10.6, 18.6), (10.6, 21.4), (8, 22.6), (8, 23.4), (12, 22.8)])
    I.mirror()
    return I

ref('\\_', '/_')

@icon('\\`')
def _():
    I = Ic()
    cloud(I, -5)
    for x0 in (7, 12, 17):
        I.seg(x0 + 1.2, 15, x0 - 1.2, 21, 2)
    I.circ(7.2, 22.4, 1.2)
    I.circ(17.2, 22.4, 1.2)
    return I

@icon('\\a')
def _():
    I = Ic()
    I.poly([(12, 0.6), (23.4, 12), (12, 23.4), (0.6, 12)])
    I.poly([(12, 4.4), (19.6, 12), (12, 19.6), (4.4, 12)], 0)
    I.rect(10.8, 6.6, 13.2, 17.4)
    I.rect(6.6, 10.8, 17.4, 13.2)
    return I

@icon('\\b')
def _():
    I = Ic()
    for y0, x1 in ((6, 17), (12, 21), (18, 13)):
        I.seg(1.5, y0, x1, y0, 2.2)
    for x, y in ((19, 5), (22, 9), (8, 22), (18, 22), (4, 9)):
        I.circ(x, y, 1.4)
    return I

@icon('\\c')
def _():
    I = Ic()
    I.ring(12, 12, 11.2, 2.2)
    I.poly([(12, 5.5), (18.5, 17.5), (5.5, 17.5)])
    I.poly([(12, 10), (14.8, 15.3), (9.2, 15.3)], 0)
    return I

@icon('\\d')
def _():
    I = Ic()
    I.ring(12, 12, 6.8, 2.2)
    for r in (0, 90, 180, 270):
        c, s = round(math.cos(math.radians(r))), round(math.sin(math.radians(r)))
        I.seg(12 + 6 * c, 12 + 6 * s, 12 + 11.3 * c, 12 + 11.3 * s, 2.2)
    I.circ(12, 12, 1.8)
    return I

@icon('\\e')
def _():
    I = Ic()
    cloud(I, -5)
    I.seg(7, 15.5, 5.4, 20.4, 2)
    I.circ(12, 17.4, 1.6)
    I.seg(16.5, 15.5, 15, 20.4, 2)
    I.circ(11.5, 22.2, 1.4)
    I.circ(19, 22, 1.4)
    return I

@icon('\\f')
def _():
    I = Ic()
    cloud(I, -5)
    I.poly([(5.5, 13.5), (18.5, 13.5), (14.3, 17.5), (12.9, 23), (11.1, 23), (9.7, 17.5)])
    return I

@icon('\\g')
def _():
    I = Ic()
    for y0, x1 in ((6, 15), (12, 21), (18, 12)):
        I.seg(1.5, y0, x1, y0, 2.2)
    I.arc(15, 9, 3, -90, 90, 2.2)
    I.seg(18, 6, 18, 6.01, 2.2)
    I.seg(21, 12, 21, 12.01, 2.2)
    I.arc(12, 15, 3, -90, 90, 2.2)
    I.poly([(13, 1.5), (23, 1.5), (23, 4.2), (13, 4.2)])
    return I

@icon('\\h')
def _():
    I = Ic()
    I.poly([(1, 3), (23, 3), (22, 8.5), (2, 8.5)])
    for x in (4.5, 9.5, 14.5, 19.5):
        I.circ(x, 8.4, 2.5)
    I.rect(2.5, 9.5, 21.5, 22.5)
    I.rect(4.5, 11.5, 12.5, 18, 0)
    I.rect(14.5, 11.5, 19.5, 22.5, 0)
    return I

@icon('\\i')
def _():
    I = Ic()
    star(I, 12, 12.6, 11.6, 4.8)
    return I

@icon('\\j')
def _():
    I = Ic()
    I.seg(5, 20.2, 15, 20.2, 4.4)
    for xx in (5.5, 10, 14.5):
        I.circ(xx, 20.2, 1.0, 0)
    I.rect(4.5, 10, 12, 16.5)
    I.rect(5.5, 11.2, 9.5, 14.6, 0)
    I.polyline([(11, 12), (17, 5), (22, 11)], 2.4)
    I.poly([(19, 11.5), (23.4, 11.5), (22.6, 17.5), (19.8, 17.5)])
    return I

ref('\\k', '/j')

@icon('\\l')
def _():
    I = Ic()
    for k in range(4):
        x0 = 1 + k * 5.5 if False else None
    for x0 in (1, 7.2, 13.4, 19.4):
        I.rect(x0, 1, x0 + 3.6, 3.2)
        I.rect(x0, 20.8, x0 + 3.6, 23)
    for y0 in (7.2, 13.4):
        I.rect(1, y0, 3.2, y0 + 3.6)
        I.rect(20.8, y0, 23, y0 + 3.6)
    I.ring(12, 12, 4.8, 2)
    return I

@icon('\\m')
def _():
    I = Ic()
    I.frame(1, 1.5, 23, 14.5, 2.2)
    text(I, '123', 3, 5, 1, True)
    I.rect(10.8, 14.5, 13.2, 23)
    return I

@icon('\\n')
def _():
    I = Ic()
    I.poly([(12, 1.8), (23, 21.6), (1, 21.6)])
    I.poly([(12, 8.2), (18.2, 19), (5.8, 19)], 0)
    I.circ(12, 15, 2.2)
    return I

@icon('\\o')
def _():
    I = Ic()
    I.ring(12, 12, 6.8, 2.6)
    return I

@icon('\\p')
def _():
    I = Ic()
    I.circ(7.5, 8, 3.8)
    rays(I, 7.5, 8, 5.4, 7.6, 8, 1.8, -90)
    cloud(I, 2.8, )
    return I

@icon('\\r')
def _():
    I = Ic()
    I.circ(6, 4.4, 2.6)
    I.rect(3.5, 8, 8.5, 15)
    I.rect(1.2, 8.2, 3.5, 14)
    I.rect(8.5, 8.2, 10.8, 14)
    I.rect(3.9, 14.5, 5.8, 22.8)
    I.rect(6.2, 14.5, 8.1, 22.8)
    I.circ(18, 4.4, 2.6)
    I.poly([(18, 7.6), (22.6, 17), (13.4, 17)])
    I.rect(16.6, 17, 19.4, 22.8)
    I.rect(12, 10.5, 12.6, 11, 0)
    return I

@icon('\\s')
def _():
    I = Ic()
    I.poly([(0.8, 14), (23.2, 14), (19.5, 20.5), (4.5, 20.5)])
    I.rect(5, 8, 16, 14)
    I.rect(7, 10, 9, 12, 0)
    I.rect(11, 10, 13, 12, 0)
    I.rect(16, 10.5, 18.5, 14)
    I.rect(8, 3, 11, 8)
    I.rect(1.5, 22.2, 22.5, 23.6)
    return I

@icon('\\t')
def _():
    I = Ic()
    for x0, x1, y0 in ((1.5, 22.5, 2), (4, 20, 6.4), (6.5, 17.5, 10.8), (8.8, 15.2, 15.2), (10.6, 13.4, 19.4)):
        I.rect(x0, y0, x1, y0 + 2.4)
    return I

ref('\\u', '/u')
ref('\\v', '/v')

@icon('\\w')
def _():
    I = Ic()
    I.poly([(5, 10), (12, 3), (19, 10)])
    I.rect(7, 9.4, 17, 14.2)
    I.rect(10.6, 10.6, 13.4, 14.2, 0)
    for k, yy in enumerate((16.5, 20.8)):
        pts = [(0.5 + i * 2, yy + 1.4 * math.sin(math.radians(i * 70 + k * 60))) for i in range(12)]
        I.polyline(pts, 2.2)
    return I

@icon('\\x')
def _():
    I = Ic()
    I.rect(0.5, 5.5, 23.5, 14.5)
    for x0 in (-3, 3, 9, 15, 21):
        I.poly([(x0 + 2, 5.5), (x0 + 5, 5.5), (x0 + 2, 14.5), (x0 - 1, 14.5)], 0)
    I.rect(0.5, 5.5, 23.5, 6.6)
    I.rect(0.5, 13.4, 23.5, 14.5)
    I.rect(3, 14.5, 6, 22.5)
    I.rect(18, 14.5, 21, 22.5)
    return I

@icon('\\y')
def _():
    I = Ic()
    I.rect(2, 3.5, 9.5, 11)
    I.rect(14.5, 3.5, 22, 11)
    I.ring(6, 15.5, 5, 2.6)
    I.ring(18, 15.5, 5, 2.6)
    I.rect(9.2, 12, 14.8, 15.6)
    return I

ref('\\z', '/z')

@icon('\\{')
def _():
    I = Ic()
    for x0, x1, y0 in ((2, 21, 3), (5, 22.5, 8), (1.5, 18.5, 13), (4, 22, 18)):
        I.seg(x0 + 1, y0 + 1, x1 - 1, y0 + 1, 2.4)
    return I

ref('\\|', '/|')
ref('\\~', '/~')
