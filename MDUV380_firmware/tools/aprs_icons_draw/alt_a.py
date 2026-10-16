# -*- coding: utf-8 -*-
import math
from nd import *
from prim_a import icon, D, star
from prim_b import car, wheel_r
from prim_c import cloud


def ref(newk, oldk):
    D[newk] = D[oldk]

def rays(I, cx, cy, r0, r1, n, w=2.2, a0=-90):
    for k in range(n):
        a = math.radians(a0 + 360.0 * k / n)
        I.seg(cx + r0 * math.cos(a), cy + r0 * math.sin(a), cx + r1 * math.cos(a), cy + r1 * math.sin(a), w)

@icon('\\!')
def _():
    I = Ic()
    I.poly([(12, 1.2), (23.2, 21.8), (0.8, 21.8)])
    I.poly([(12, 7.6), (18.6, 19.4), (5.4, 19.4)], 0)
    I.rect(10.8, 9.5, 13.2, 15)
    I.rect(10.8, 16.3, 13.2, 18.4)
    return I

@icon('\\#')
def _():
    I = Ic()
    I.ring(12, 12, 11.2, 2.2)
    star(I, 12, 12.6, 8.4, 3.6)
    return I

@icon('\\$')
def _():
    I = Ic()
    I.poly([(0.8, 8.5), (12, 1.5), (23.2, 8.5)])
    I.rect(1.5, 9.6, 22.5, 11.2)
    for x0 in (3, 8, 13, 18):
        I.rect(x0, 12.2, x0 + 3, 18.6)
    I.rect(0.8, 19.6, 23.2, 21)
    I.rect(0.8, 21.8, 23.2, 23.4)
    return I

@icon('\\%')
def _():
    I = Ic()
    I.poly([(5, 22.8), (7.8, 12), (6.2, 4), (17.8, 4), (16.2, 12), (19, 22.8)])
    I.rect(7.8, 1.6, 16.2, 3)
    I.seg(9.5, 15, 14.5, 15, 1.6, 0)
    return I

ref('\\&', '/&')

@icon("\\'")
def _():
    I = Ic()
    pts = []
    for k in range(16):
        a = math.radians(-90 + 22.5 * k)
        r = 11.5 if k % 2 == 0 else 6.2
        pts.append((12 + r * math.cos(a), 12 + r * math.sin(a)))
    I.poly(pts)
    I.circ(12, 12, 2.6, 0)
    return I

@icon('\\(')
def _():
    I = Ic()
    cloud(I, 0)
    return I

@icon('\\)')
def _():
    I = Ic()
    I.ellring(12, 12, 11.4, 5.4, 2.2)
    I.circ(12, 12, 4.6)
    I.circ(12, 12, 1.4, 0)
    I.circ(12, 6.6, 1.5, 0)
    return I

@icon('\\*')
def _():
    I = Ic()
    for k in range(3):
        a = math.radians(-90 + 60 * k)
        I.seg(12 - 10.8 * math.cos(a), 12 - 10.8 * math.sin(a), 12 + 10.8 * math.cos(a), 12 + 10.8 * math.sin(a), 2.2)
    for k in range(6):
        a = math.radians(-90 + 60 * k)
        ex, ey = 12 + 9.8 * math.cos(a), 12 + 9.8 * math.sin(a)
        bx, by = 12 + 6.6 * math.cos(a), 12 + 6.6 * math.sin(a)
        for s in (-1, 1):
            b = a + s * math.radians(55)
            I.seg(bx, by, bx + 3.2 * math.cos(b), by + 3.2 * math.sin(b), 1.8)
    return I

@icon('\\+')
def _():
    I = Ic()
    I.rect(2, 13, 22, 22.5)
    I.rect(8.5, 7.5, 15.5, 13)
    I.poly([(8.5, 7.8), (12, 4.8), (15.5, 7.8)])
    I.rect(11, 0.8, 13, 5)
    I.rect(9, 2, 15, 3.6)
    I.rect(10.5, 17, 13.5, 22.5, 0)
    I.rect(4, 15, 6.4, 18, 0)
    I.rect(17.6, 15, 20, 18, 0)
    return I

@icon('\\,')
def _():
    I = Ic()
    I.circ(12, 6.8, 4.8)
    I.circ(6.6, 14.2, 4.8)
    I.circ(17.4, 14.2, 4.8)
    I.circ(12, 12.5, 4)
    I.rect(10.9, 14, 13.1, 23)
    I.seg(12, 18, 6.5, 21.5, 1.8)
    I.seg(12, 18, 17.5, 21.5, 1.8)
    return I

@icon('\\-')
def _():
    I = Ic()
    I.poly([(0.5, 13.5), (12, 3.2), (23.5, 13.5)])
    I.rect(3.5, 12.4, 20.5, 22.5)
    I.rect(10, 16, 14, 22.5, 0)
    I.rect(5.5, 14.5, 8.5, 17.5, 0)
    I.rect(15.5, 14.5, 18.5, 17.5, 0)
    I.rect(11, 0.5, 13, 5)
    return I

@icon('\\.')
def _():
    I = Ic()
    I.polyline([(6.5, 7.5), (7.8, 3.8), (12, 2), (16.2, 3.8), (17.4, 7.5), (15.6, 10.8), (12, 13.2), (12, 15.4)], 3)
    I.rect(10.4, 18.6, 13.6, 22)
    return I

@icon('\\/')
def _():
    I = Ic()
    I.rect(4, 1.5, 6.4, 22.8)
    I.poly([(6.4, 2.5), (21.5, 2.5), (17.5, 7.5), (21.5, 12.5), (6.4, 12.5)])
    return I

@icon('\\0')
def _():
    I = Ic()
    I.ring(12, 12, 11.2, 3)
    return I

@icon('\\8')
def _():
    I = Ic()
    I.circ(12, 19.8, 2.2)
    for r in (7, 11.6, 16.2):
        I.arc(12, 19.8, r, 228, 312, 2.4)
    return I

@icon('\\9')
def _():
    I = Ic()
    I.frame(2, 2.5, 14, 22.5, 2.2)
    I.rect(4.2, 4.7, 11.8, 10)
    I.rect(1, 21, 15, 23)
    I.polyline([(14, 8.5), (18.5, 8.5), (18.5, 16.5), (21.4, 16.5), (21.4, 20.5)], 2)
    I.poly([(19.5, 12), (22.5, 12), (22.5, 15.5), (19.5, 15.5)])
    return I

@icon('\\:')
def _():
    I = Ic()
    cloud(I, -5)
    for x0, y0 in ((6, 19), (12, 21.4), (18, 19)):
        I.circ(x0, y0, 1.8)
    return I

@icon('\;')
def _():
    I = Ic()
    I.circ(7.5, 8, 6.2)
    I.rect(6.4, 13, 8.6, 22.5)
    I.rect(12.5, 14, 23, 16.4)
    I.seg(14.5, 16, 13, 22.5, 2)
    I.seg(21, 16, 22.4, 22.5, 2)
    I.rect(15, 11, 21, 12.6)
    return I

@icon('\\<')
def _():
    I = Ic()
    I.rect(4, 1.5, 6.4, 22.8)
    I.poly([(6.4, 3), (21.5, 7.5), (6.4, 12.2)])
    return I

@icon('\\=')
def _():
    I = Ic()
    for y0 in (1.5, 7.5, 13.5, 19.5):
        for x0 in (3, 10, 17):
            I.rect(x0, y0, x0 + 4, y0 + 3.2)
    return I

ref('\\>', '/>')

@icon('\\?')
def _():
    I = Ic()
    I.frame(1, 1, 23, 23, 2.2)
    I.circ(12, 6.6, 1.9)
    I.rect(10.6, 10, 13.4, 18)
    I.rect(8.4, 17, 15.6, 19.4)
    I.rect(8.4, 10, 10.6, 11.9)
    return I

@icon('\\@')
def _():
    I = Ic()
    pts = []
    for i in range(0, 121):
        t = i / 120.0
        a = math.radians(-110 - 760 * t)
        r = 2.0 + 9.2 * t
        pts.append((12 + r * math.cos(a), 12 + r * math.sin(a)))
    I.polyline(pts, 2.4)
    return I

@icon('\\A')
def _():
    I = Ic()
    I.frame(2, 2, 22, 22, 3)
    return I

@icon('\\B')
def _():
    I = Ic()
    for y0, x1 in ((6, 17), (12, 20), (18, 14)):
        I.seg(1.5, y0, x1, y0, 2.2)
    I.arc(17, 3.5, 2.5, -90, 90, 2.2)
    I.arc(20, 9.5, 2.5, -90, 90, 2.2)
    I.arc(14, 15.5, 2.5, -90, 90, 2.2)
    return I

@icon('\\C')
def _():
    I = Ic()
    I.ring(12, 4.2, 2.8, 1.6)
    I.seg(12, 6.6, 12, 21, 2.2)
    I.seg(7.2, 9.6, 16.8, 9.6, 2.2)
    I.arc(12, 13.5, 9.2, 20, 160, 2.4)
    I.poly([(1.6, 13), (4.4, 13.2), (2.6, 17.6)])
    I.poly([(22.4, 13), (19.6, 13.2), (21.4, 17.6)])
    return I

@icon('\\D')
def _():
    I = Ic()
    cloud(I, -5)
    for x0 in (6.5, 12, 17.5):
        I.rect(x0 - 0.8, 17.5, x0 + 0.8, 20.2)
        I.rect(x0 - 0.8, 21.2, x0 + 0.8, 23)
    return I

@icon('\\E')
def _():
    I = Ic()
    for yy in (4.5, 12, 19.5):
        pts = [(1 + i * 2, yy + 1.7 * math.sin(math.radians(i * 70))) for i in range(12)]
        I.polyline(pts, 2.2)
    return I

@icon('\\F')
def _():
    I = Ic()
    cloud(I, -5)
    I.seg(8, 15.5, 6.4, 20, 2)
    I.seg(15, 15.5, 13.4, 20, 2)
    I.circ(11.5, 21.4, 1.6)
    I.circ(18.5, 19.4, 1.6)
    I.circ(5, 22.4, 1.6)
    return I
