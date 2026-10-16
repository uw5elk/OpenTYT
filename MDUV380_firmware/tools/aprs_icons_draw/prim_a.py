# -*- coding: utf-8 -*-
import math
from nd import *
D = {}
def icon(*keys):
    def deco(fn):
        for k in keys:
            D[k] = fn
        return fn
    return deco

def star(I, cx, cy, ro, ri, v=1):
    pts = []
    for k in range(10):
        a = math.radians(-90 + 36 * k)
        r = ro if k % 2 == 0 else ri
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    I.poly(pts, v)

@icon('/!')
def _():
    I = Ic()
    I.poly([(3, 1.5), (21, 1.5), (21, 11), (17.5, 16.5), (12, 22.5), (6.5, 16.5), (3, 11)])
    I.poly([(5.4, 3.9), (18.6, 3.9), (18.6, 10.3), (15.6, 15.2), (12, 19.4), (8.4, 15.2), (5.4, 10.3)], 0)
    star(I, 12, 10.6, 5.6, 2.4)
    return I

@icon('/#')
def _():
    I = Ic()
    I.poly([(12, 0.6), (23.4, 12), (12, 23.4), (0.6, 12)])
    I.poly([(12, 4.4), (19.6, 12), (12, 19.6), (4.4, 12)], 0)
    I.circ(12, 12, 3.4)
    return I

@icon('/$')
def _():
    I = Ic()
    I.frame(5, 1, 19, 23, 2)
    I.rect(8, 4, 16, 8)
    for yy in (10, 13, 16, 19):
        for xx in (8, 11, 14):
            I.rect(xx, yy, xx + 2, yy + 2)
    return I

@icon('/%')
def _():
    I = Ic()
    I.rect(0, 1, 24, 3.5)
    I.rect(0, 20.5, 24, 23)
    text(I, 'DX', 1, 5, 2)
    return I

@icon('/&')
def _():
    I = Ic()
    I.ring(12, 12, 11.2, 2.2)
    I.ellring(12, 12, 5.6, 11.2, 2.2)
    I.rect(1, 11, 23, 13)
    return I

@icon("/'")
def _():
    I = Ic()
    I.rect(10.4, 3, 13.6, 20)
    I.circ(12, 4.2, 1.6)
    I.poly([(10.4, 8), (1, 14), (1, 16.8), (10.4, 13.6)])
    I.poly([(10.4, 18), (5, 22.5), (5, 23.4), (10.4, 21)])
    I.mirror()
    return I

@icon('/(')
def _():
    I = Ic()
    I.rect(9, 8, 15, 16)
    I.frame(1, 6, 8, 18, 2)
    I.rect(8, 11, 9, 13)
    I.mirror()
    I.seg(12, 8, 12, 4, 2)
    I.circ(12, 3.2, 1.8)
    I.seg(12, 16, 12, 20, 2)
    I.circ(12, 20.8, 1.8)
    return I

@icon('/)')
def _():
    I = Ic()
    I.ring(10, 16.5, 6.5, 2)
    I.circ(9, 3.4, 2.4)
    I.seg(9, 7, 9, 14, 2.6)
    I.seg(9, 9.6, 15, 12, 2)
    I.seg(9, 14, 17, 14, 2.6)
    I.seg(17, 14, 19, 20, 2.6)
    I.seg(19, 20.5, 22, 20.5, 2)
    return I

@icon('/*')
def _():
    I = Ic()
    I.poly([(2.5, 17), (3.5, 12.5), (10, 10.5), (12, 5.5), (16.5, 5.5), (15.5, 10), (21.5, 13), (21.5, 17)])
    I.seg(6.5, 19.5, 16, 19.5, 5)
    for xx in (6.5, 11.2, 15.8):
        I.circ(xx, 19.5, 1.0, 0)
    I.seg(15.5, 22.6, 22.5, 21.2, 2)
    I.seg(18.5, 16.5, 17.5, 22, 2)
    return I

@icon('/+')
def _():
    I = Ic()
    I.rect(8.6, 1.5, 15.4, 22.5)
    I.rect(1.5, 8.6, 22.5, 15.4)
    return I

@icon('/,')
def _():
    I = Ic()
    I.poly([(12, 0.5), (15.2, 5), (15.2, 10.5), (12, 15.5), (8.8, 10.5), (8.8, 5)])
    I.polyline([(9.5, 14.5), (4.8, 12.8), (2.6, 8.8), (3.6, 5)], 2.8)
    I.circ(3.8, 4.8, 2.0)
    I.mirror()
    I.rect(4, 16, 20, 18.6)
    I.rect(10.4, 18.6, 13.6, 23.5)
    return I

@icon('/-')
def _():
    I = Ic()
    I.poly([(0.5, 12.2), (12, 1.5), (23.5, 12.2)])
    I.rect(3.5, 11, 20.5, 22.5)
    I.rect(10, 15, 14, 22.5, 0)
    I.rect(5.5, 13.5, 8.5, 16.5, 0)
    I.rect(15.5, 13.5, 18.5, 16.5, 0)
    return I

@icon('/.')
def _():
    I = Ic()
    I.seg(3.5, 3.5, 20.5, 20.5, 3.6)
    I.seg(20.5, 3.5, 3.5, 20.5, 3.6)
    return I

@icon('//')
def _():
    I = Ic()
    I.circ(12, 12, 10.2)
    return I

for _d in '0123456789':
    def _mk(d):
        def f():
            I = Ic()
            I.ring(12, 12, 11.2, 2.2)
            digit(I, d)
            return I
        return f
    D['/' + _d] = _mk(_d)
