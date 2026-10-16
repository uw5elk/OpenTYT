# -*- coding: utf-8 -*-
from seed_lib import *
import gen_aprs_icons24 as G

def satellite():
    c = C()
    c.rect(8, 8, 15, 15); c.rect(11, 11, 12, 12, 0)
    c.frame(0, 7, 6, 16, 2); c.rect(3, 9, 3, 14)
    c.frame(17, 7, 23, 16, 2); c.rect(20, 9, 20, 14)
    c.rect(6, 11, 8, 12); c.rect(15, 11, 17, 12)
    c.line(12, 8, 12, 3, 2); c.circ(12, 2, 2)
    c.line(12, 16, 12, 20, 2); c.rect(9, 20, 14, 21)
    return c

def wheelchair():
    c = C()
    c.circ(8, 3, 3)
    c.rect(7, 7, 9, 14)
    c.pl([(8, 14), (15, 14), (18, 21)], 3)
    c.pl([(9, 9), (14, 10)], 2)
    c.arc(9, 17, 6, 0, 360, 2)
    return c

def snowmobile():
    c = C()
    c.poly([(3, 13), (15, 13), (19, 8), (23, 8), (23, 13), (20, 16), (3, 16)])
    c.pl([(6, 13), (8, 7), (11, 7)], 2)
    c.rect(9, 17, 20, 20); c.rect(11, 18, 18, 19, 0)
    c.pl([(0, 19), (3, 22), (11, 22)], 2)
    return c

def redcross():
    c = C()
    c.rect(9, 1, 14, 22); c.rect(1, 9, 22, 14)
    c.rect(11, 3, 12, 20, 0); c.rect(3, 11, 20, 12, 0)
    return c

def scout():  # лілія
    c = C()
    c.ell(12, 8, 3, 7)
    c.pl([(9, 12), (4, 10), (2, 5)], 3); c.pl([(15, 12), (20, 10), (22, 5)], 3)
    c.pl([(2, 5), (5, 8)], 3); c.pl([(22, 5), (19, 8)], 3)
    c.rect(3, 15, 20, 17)
    c.rect(10, 17, 13, 22)
    return c

def trefoil():
    c = C()
    c.circ(12, 6, 5); c.circ(6, 13, 5); c.circ(18, 13, 5)
    c.rect(10, 13, 13, 23)
    c.clear_circ(12, 9, 0)
    return c

def xmark():
    c = C()
    c.line(3, 3, 20, 20, 4); c.line(20, 3, 3, 20, 4)
    return c

def reddot():
    c = C(); c.circ(12, 12, 10); return c

def digitring(d):
    def f():
        c = C()
        c.ring(12, 12, 11, 2)
        w = c.textw(d, 2)
        c.text(d, (N - w) // 2, 5, 2)
        return c
    return f

def fire():
    c = C()
    c.poly([(12, 0), (16, 6), (19, 10), (21, 15), (19, 20), (14, 23), (9, 23), (4, 20), (2, 15), (4, 10), (7, 12), (9, 6)])
    c.poly([(12, 11), (15, 16), (14, 20), (10, 20), (9, 16)], 0)
    return c

def tent():
    c = C()
    c.poly([(12, 2), (23, 21), (1, 21)])
    c.poly([(12, 11), (16, 21), (8, 21)], 0)
    c.rect(0, 21, 23, 22)
    return c

def locomotive():
    c = C()
    c.rect(1, 9, 13, 17)            # котел
    c.rect(13, 5, 21, 17)           # кабіна
    c.rect(15, 7, 19, 11, 0)
    c.rect(3, 3, 6, 9)              # труба
    c.rect(2, 3, 7, 4)
    c.rect(0, 17, 23, 18)
    for x in (4, 10, 17):
        wheel(c, x, 20, 3)
    return c

def server():
    c = C()
    c.frame(2, 1, 21, 10, 2); c.frame(2, 13, 21, 22, 2)
    c.rect(15, 4, 17, 7); c.rect(15, 16, 17, 19)
    c.rect(5, 4, 11, 4); c.rect(5, 16, 11, 16)
    return c

def storm():
    c = C()
    c.arc(12, 12, 4, 0, 360, 2)
    c.arc(12, 12, 9, 200, 380, 3)
    c.arc(12, 12, 9, 20, 200, 3)
    c.line(21, 12, 22, 4, 3)
    c.line(3, 12, 2, 20, 3)
    c.circ(12, 12, 2)
    return c

def aid():
    c = C()
    c.frame(1, 3, 22, 21, 2)
    c.rect(10, 7, 13, 17); c.rect(7, 10, 16, 13)
    return c

def canoe():
    c = C()
    c.poly([(0, 15), (23, 15), (19, 20), (4, 20)])
    c.line(4, 4, 18, 17, 2)
    c.line(2, 7, 7, 3, 2)
    c.circ(10, 8, 3)
    c.rect(8, 11, 11, 14)
    return c

def eyeball():
    c = C()
    c.ell(12, 12, 11, 7)
    c.ell(12, 12, 8, 4, 0)
    c.circ(12, 12, 4)
    c.circ(12, 12, 1, 0)
    return c

def tractor():
    c = C()
    c.ring(7, 16, 7, 3)
    c.ring(19, 18, 4, 2)
    c.poly([(6, 5), (13, 5), (13, 11), (23, 11), (23, 14), (6, 14)])
    c.rect(8, 7, 11, 9, 0)
    c.rect(14, 8, 22, 9)
    c.circ(7, 16, 1, 0)
    return c

def gridsq():
    c = C()
    c.frame(0, 0, 23, 23, 2)
    c.rect(7, 2, 8, 21); c.rect(15, 2, 16, 21)
    c.rect(2, 7, 21, 8); c.rect(2, 15, 21, 16)
    return c

def hotel():
    c = C()
    c.rect(0, 3, 2, 21)               # узголів'я
    c.rect(0, 13, 23, 16)             # матрац
    c.rect(21, 17, 23, 21)
    c.rect(0, 17, 2, 21)
    c.rect(4, 8, 10, 12)              # подушка
    c.rect(12, 10, 23, 12)
    return c

def school():
    c = C()
    c.poly([(12, 3), (23, 9), (12, 15), (1, 9)])
    c.rect(5, 12, 6, 18); c.rect(17, 12, 18, 18)
    c.poly([(6, 12), (12, 15), (18, 12), (18, 18), (12, 22), (6, 18)])
    c.poly([(12, 9), (12, 9)], 0)
    c.line(21, 10, 21, 20, 2); c.circ(21, 21, 2)
    return c

def pcuser():
    c = C()
    c.frame(1, 1, 15, 12, 2); c.rect(4, 4, 12, 9, 0)
    c.rect(7, 12, 9, 15); c.rect(3, 15, 13, 16)
    c.frame(17, 6, 23, 21, 2); c.rect(19, 9, 21, 10, 0)
    c.rect(18, 19, 22, 19)
    c.rect(2, 19, 14, 22)
    return c

def mac():
    c = C()
    c.frame(3, 1, 20, 21, 2)
    c.rect(6, 4, 17, 12, 0); c.rect(7, 5, 16, 11)
    c.rect(8, 6, 15, 10, 0)
    c.rect(7, 15, 12, 16); c.rect(15, 15, 16, 16)
    c.rect(1, 21, 22, 22)
    return c

def rv():
    c = C()
    c.poly([(0, 4), (17, 4), (17, 8), (23, 12), (23, 18), (0, 18)])
    c.rect(2, 6, 7, 10, 0); c.rect(9, 6, 14, 10, 0)
    c.poly([(19, 10), (21, 13), (19, 13)], 0)
    c.rect(2, 13, 14, 14, 0)
    wheel(c, 5, 19); wheel(c, 18, 19)
    return c

def shuttle():
    c = C()
    c.poly([(12, 0), (14, 4), (14, 12), (23, 20), (23, 22), (14, 20), (14, 22), (12, 23), (10, 22), (10, 20), (1, 22), (1, 20), (10, 12), (10, 4)])
    c.rect(11, 4, 12, 9, 0)
    return c

def sstv():
    c = C()
    c.frame(1, 6, 22, 21, 2)
    c.poly([(5, 17), (10, 10), (13, 14), (16, 11), (19, 17)])
    c.line(8, 6, 3, 1, 2); c.line(15, 6, 20, 1, 2)
    return c

def atv():
    c = C()
    c.frame(0, 7, 15, 20, 2)
    c.poly([(15, 11), (23, 6), (23, 21), (15, 16)])
    c.circ(5, 3, 3); c.circ(12, 3, 3)
    c.circ(7, 13, 2)
    return c

def wxsvc():
    c = C()
    c.circ(12, 8, 7); c.rect(11, 15, 12, 20)
    c.circ(12, 8, 3, 0)
    c.rect(5, 20, 18, 22)
    c.arc(12, 8, 10, 200, 340, 1)
    return c

def helicopter():
    c = C()
    c.line(0, 4, 23, 4, 2); c.rect(11, 4, 12, 7)
    c.ell(10, 12, 8, 5)
    c.ell(10, 12, 4, 2, 0)
    c.rect(17, 11, 22, 12)
    c.line(21, 7, 22, 15, 2)
    c.line(2, 19, 17, 19, 2); c.line(5, 16, 5, 19, 2); c.line(14, 16, 14, 19, 2)
    return c

def winaprs():
    return plaque("WIN")

def dfstation():
    c = C()
    c.poly([(12, 1), (23, 21), (1, 21)]); c.hollow(2)
    c.circ(12, 14, 3)
    c.line(12, 14, 12, 5, 2)
    return c

def mail():
    c = C()
    c.frame(0, 3, 23, 20, 2)
    c.pl([(2, 5), (12, 13), (21, 5)], 2)
    return c

def dish():
    c = C()
    c.arc(10, 10, 9, 90, 270 + 90 - 90, 3)  # заповнимо нижче
    c = C()
    c.arc(11, 11, 10, 100, 280 + 0, 0)
    c = C()
    # тарілка: парабола-чаша + підставка + опромінювач
    c.arc(9, 9, 8, 30, 210, 3)
    c.line(3, 15, 15, 3, 2)
    c.line(11, 11, 19, 19, 3)
    c.rect(14, 20, 23, 22)
    c.line(11, 11, 17, 5, 1)
    c.circ(17, 5, 2)
    return c

def ambulance():
    c = C()
    c.poly([(0, 6), (15, 6), (15, 10), (23, 12), (23, 18), (0, 18)])
    c.rect(5, 9, 9, 10, 0); c.rect(7, 8, 8, 11, 0)
    c.poly([(17, 11), (20, 13), (17, 13)], 0)
    c.rect(5, 3, 9, 4)
    c.rect(2, 14, 13, 15, 0)
    wheel(c, 5, 19); wheel(c, 18, 19)
    return c

def icp():
    c = C()
    c.rect(1, 6, 22, 8)
    c.rect(3, 8, 4, 21); c.rect(19, 8, 20, 21)
    c.line(11, 0, 11, 6, 2); c.rect(12, 0, 18, 3)
    c.rect(1, 21, 22, 22)
    c.rect(8, 12, 15, 21, 0)
    return c

def firedept():
    c = C()
    c.arc(12, 14, 9, 180, 360, 0)
    c.ell(12, 12, 9, 9); c.rect(0, 12, 23, 12, 0)
    c.rect(0, 12, 23, 15)
    c.rect(0, 15, 23, 17)
    c.rect(10, 1, 13, 4)
    c.rect(6, 7, 17, 9, 0)
    c.rect(11, 5, 12, 11, 0)
    return c

def horse():
    c = C()
    c.ell(11, 11, 8, 5)                             # тулуб
    c.poly([(15, 8), (18, 2), (22, 2), (23, 6), (19, 8), (17, 12)])   # шия й голова
    c.poly([(18, 2), (19, 0), (20, 2)])             # вухо
    c.line(15, 6, 14, 2, 2)                         # грива
    c.rect(4, 14, 6, 22); c.rect(8, 14, 10, 22)     # задні ноги
    c.rect(13, 14, 15, 22); c.rect(17, 14, 19, 22)  # передні
    c.line(3, 8, 0, 16, 2)                          # хвіст
    return c

def firetruck():
    c = C()
    c.rect(0, 9, 14, 18)
    c.poly([(14, 7), (18, 7), (23, 12), (23, 18), (14, 18)])
    c.poly([(16, 9), (18, 9), (21, 12), (16, 12)], 0)
    c.line(1, 4, 13, 4, 2); c.line(2, 4, 2, 9, 2); c.line(12, 4, 12, 9, 2)
    c.line(5, 4, 5, 9, 1); c.line(8, 4, 8, 9, 1)
    c.rect(2, 11, 12, 12, 0)
    wheel(c, 5, 19); wheel(c, 18, 19)
    return c

def glider():
    c = C()
    c.poly([(0, 10), (11, 9), (11, 13), (0, 12)])
    c.poly([(23, 10), (12, 9), (12, 13), (23, 12)])
    c.ell(12, 12, 2, 9)
    c.poly([(8, 20), (16, 20), (16, 22), (8, 22)])
    return c

def hospital():
    c = C()
    c.frame(1, 3, 22, 22, 2)
    c.rect(10, 6, 13, 18); c.rect(6, 10, 17, 13)
    c.rect(10, 0, 13, 3)
    return c

def iota():
    c = C()
    c.ell(12, 21, 11, 4)
    c.line(11, 20, 10, 8, 2)
    c.pl([(10, 8), (5, 5), (1, 8)], 2); c.pl([(10, 8), (16, 4), (21, 7)], 2)
    c.pl([(10, 8), (8, 2)], 2); c.pl([(10, 8), (14, 1)], 2)
    return c

def laptop():
    c = C()
    c.frame(3, 2, 20, 15, 2)
    c.poly([(0, 16), (23, 16), (23, 19), (21, 21), (2, 21), (0, 19)])
    c.rect(9, 18, 14, 19, 0)
    return c

def mice():
    c = C()
    c.frame(7, 0, 16, 12, 0)
    c.rect(7, 0, 16, 12); c.rect(9, 2, 14, 10, 0)
    c.arc(12, 11, 8, 10, 170, 2)
    c.rect(11, 18, 12, 20); c.rect(7, 21, 16, 22)
    c.line(9, 4, 14, 4, 1); c.line(9, 7, 14, 7, 1)
    return c

def node():
    c = C()
    c.ring(12, 12, 11, 2); c.ring(12, 12, 6, 2); c.circ(12, 12, 2)
    return c

def eoc():
    c = C()
    c.rect(1, 12, 22, 22); c.rect(4, 15, 7, 18, 0); c.rect(10, 15, 13, 18, 0); c.rect(16, 15, 19, 22, 0)
    c.rect(11, 3, 12, 12)
    c.circ(11, 3, 2)
    c.arc(11, 3, 5, 200, 340, 1); c.arc(11, 3, 8, 200, 340, 1)
    return c

def dog():
    c = C()
    c.ell(11, 11, 8, 4)
    c.poly([(16, 9), (19, 4), (23, 5), (23, 9), (19, 10)])   # голова
    c.poly([(18, 4), (19, 1), (21, 4)])                       # вухо
    c.rect(4, 13, 6, 21); c.rect(8, 13, 10, 21); c.rect(13, 13, 15, 21); c.rect(17, 13, 19, 21)
    c.pl([(3, 9), (0, 4)], 2)
    c.rect(22, 7, 23, 8, 0)
    return c

def gridsq2():
    c = C()
    c.frame(0, 0, 23, 23, 2)
    c.rect(2, 2, 11, 11); c.rect(12, 12, 21, 21)
    return c

def powerboat():
    c = C()
    c.poly([(0, 12), (23, 12), (19, 19), (5, 19)])
    c.poly([(6, 12), (9, 6), (17, 6), (17, 12)])
    c.rect(10, 8, 15, 10, 0)
    c.pl([(0, 22), (4, 20), (8, 22), (12, 20), (16, 22), (20, 20), (23, 22)], 2)
    return c

def truckstop():
    c = C()
    c.rect(1, 3, 22, 19)
    c.rect(4, 6, 19, 11, 0)
    c.rect(4, 14, 7, 16, 0); c.rect(16, 14, 19, 16, 0)
    c.rect(10, 14, 13, 16, 0)
    c.rect(0, 19, 5, 22); c.rect(18, 19, 23, 22)
    return c

def semi():
    c = C()
    c.rect(6, 3, 23, 15)
    c.rect(8, 5, 21, 13, 0)
    c.rect(8, 5, 21, 6)
    c.poly([(0, 8), (4, 8), (5, 12), (5, 17), (0, 17)])
    c.rect(2, 10, 3, 12, 0)
    c.rect(0, 15, 23, 17)
    for x in (3, 12, 17, 21):
        c.circ(x, 20, 2)
    return c

def water():
    c = C()
    c.poly([(8, 0), (14, 7), (14, 11), (11, 14), (5, 14), (2, 11), (2, 7)])
    c.rect(17, 8, 23, 10)
    c.rect(17, 3, 19, 10)
    c.poly([(5, 8), (8, 4), (11, 8), (8, 12)], 0) if False else None
    c.rect(5, 17, 7, 22); c.rect(9, 17, 11, 20); c.rect(13, 17, 15, 22)
    return c

def xaprs():
    c = C()
    c.line(2, 2, 21, 21, 4); c.line(21, 2, 2, 21, 4)
    c.ring(12, 12, 11, 1)
    return c

def yagi():
    c = C()
    c.line(0, 12, 23, 12, 2)
    for x, h in ((3, 9), (8, 6), (12, 7), (16, 5), (20, 4)):
        c.line(x, 12 - h, x, 12 + h, 2)
    c.rect(11, 14, 12, 22)
    return c

def shelter():
    c = C()
    c.poly([(0, 9), (23, 4), (23, 8), (0, 13)])
    c.rect(3, 12, 5, 22); c.rect(18, 8, 20, 22)
    c.rect(1, 22, 22, 23)
    return c

def tncsw1():
    c = C()
    c.frame(0, 3, 23, 20, 2)
    c.pl([(5, 9), (18, 9)], 2); c.poly([(18, 6), (21, 9), (18, 12)])
    c.pl([(18, 14), (5, 14)], 2); c.poly([(5, 11), (2, 14), (5, 17)])
    return c

def tncsw2():
    c = C()
    c.frame(0, 3, 23, 20, 2)
    c.pl([(8, 18), (8, 6)], 2); c.poly([(5, 6), (8, 3), (11, 6)])
    c.pl([(16, 6), (16, 18)], 2); c.poly([(13, 18), (16, 21), (19, 18)])
    return c

def dxcluster():
    return plaque("DX")

def nts():
    return plaque("NTS")

def bbs():
    return plaque("BBS")

def smallplane():
    c = C()
    c.poly([(11, 1), (13, 1), (13, 8), (23, 9), (23, 12), (13, 12), (13, 19), (17, 21), (17, 23), (7, 23), (7, 21), (11, 19), (11, 12), (1, 12), (1, 9), (11, 8)])
    return c

def kiosk():
    c = C()
    c.frame(0, 0, 23, 23, 2)
    c.rect(10, 4, 13, 7); c.rect(10, 10, 13, 19)
    c.rect(8, 19, 15, 20)
    return c

def waypoint():
    c = C()
    c.rect(4, 1, 6, 22)
    c.poly([(6, 2), (22, 2), (17, 8), (22, 14), (6, 14)])
    c.poly([(8, 5), (17, 5), (14, 8), (17, 11), (8, 11)], 0)
    return c

# ---- ревізія 1 (після перегляду аркуша) ----
def snowmobile():
    c = C()
    c.poly([(1, 15), (3, 10), (11, 9), (14, 5), (17, 5), (19, 9), (23, 10), (23, 16), (1, 16)])
    c.rect(5, 12, 7, 13, 0); c.rect(14, 8, 16, 9, 0)
    c.rect(8, 16, 22, 21); c.rect(10, 18, 20, 19, 0)
    c.pl([(0, 20), (1, 22), (9, 22)], 2)
    return c

def storm():
    c = C()
    for off in (0, 180):
        pts = []
        for i in range(0, 40):
            a = math.radians(off + i * 9)
            r = 2.5 + i * 0.22
            pts.append((11.5 + r * math.cos(a), 11.5 + r * math.sin(a)))
        c.pl(pts, 3)
    c.circ(11.5, 11.5, 2)
    return c

def canoe():
    c = C()
    c.poly([(0, 14), (23, 14), (23, 15), (19, 20), (4, 20), (0, 15)])
    c.rect(5, 15, 18, 15, 0)
    c.circ(11, 5, 3)
    c.rect(9, 8, 13, 13)
    c.line(3, 9, 19, 19, 2)
    return c

def dish():
    c = C()
    c.arc(12, 12, 9, 45, 225, 3)
    c.line(5, 19, 19, 5, 2) if False else None
    c.line(12, 12, 19, 5, 2); c.circ(19, 4, 2)
    c.line(7, 17, 7, 22, 3); c.rect(2, 21, 13, 22)
    return c

def firedept():
    c = C()
    c.ell(12, 14, 9, 11)
    c.rect(0, 14, 23, 23, 0)
    c.rect(0, 14, 23, 17)
    c.rect(0, 17, 5, 18)
    c.rect(10, 2, 13, 5, 0)
    c.rect(9, 6, 14, 11, 0)
    c.rect(11, 7, 12, 10)
    return c

def powerboat():
    c = C()
    c.poly([(0, 12), (23, 12), (19, 18), (4, 18)])
    c.poly([(6, 12), (9, 6), (17, 6), (19, 12)])
    c.poly([(10, 8), (16, 8), (17, 10), (9, 10)], 0)
    c.pl([(0, 21), (3, 21), (5, 22)], 2)
    c.pl([(8, 22), (11, 20), (14, 22), (17, 20), (20, 22), (23, 20)], 2)
    return c

def truckstop():
    c = C()
    c.rect(3, 1, 20, 2)
    c.rect(4, 3, 19, 17)
    c.rect(6, 5, 17, 10, 0)
    c.rect(8, 12, 15, 13, 0)
    c.rect(5, 14, 7, 15, 0); c.rect(16, 14, 18, 15, 0)
    c.rect(0, 5, 3, 10)
    c.rect(20, 5, 23, 10)
    c.rect(4, 17, 8, 22); c.rect(15, 17, 19, 22)
    return c

def water():
    c = C()
    c.rect(0, 2, 14, 5)
    c.rect(11, 2, 14, 9)
    c.rect(9, 0, 16, 1)
    c.poly([(12, 12), (17, 18), (17, 20), (12, 23), (7, 20), (7, 18)])
    return c

def xaprs():
    c = C()
    c.ring(12, 12, 11, 2)
    c.line(6, 6, 17, 17, 3); c.line(17, 6, 6, 17, 3)
    return c

def shelter():
    c = C()
    c.poly([(0, 11), (23, 4), (23, 8), (0, 15)])
    c.rect(2, 14, 4, 22); c.rect(19, 7, 21, 22)
    c.rect(4, 18, 19, 19)
    c.rect(0, 22, 23, 23)
    return c

def ambulance():
    c = C()
    c.poly([(0, 6), (15, 6), (15, 10), (23, 12), (23, 18), (0, 18)])
    c.rect(5, 10, 11, 11, 0); c.rect(7, 8, 9, 13, 0)
    c.poly([(17, 11), (20, 13), (17, 13)], 0)
    c.rect(4, 3, 10, 4)
    wheel(c, 5, 19); wheel(c, 18, 19)
    return c

def glider():
    c = C()
    c.rect(0, 10, 23, 12)
    c.ell(12, 11, 2, 9)
    c.rect(8, 19, 16, 20)
    c.rect(11, 5, 12, 8, 0)
    return c

# ---- ревізія 2 ----
def hospital():
    c = C()
    c.rect(8, 1, 15, 22)
    c.rect(1, 9, 7, 22); c.rect(16, 9, 22, 22)
    c.rect(11, 3, 12, 8, 0); c.rect(10, 5, 13, 6, 0)
    for y in (11, 15):
        c.rect(3, y, 5, y + 2, 0); c.rect(18, y, 20, y + 2, 0)
    c.rect(10, 11, 13, 14, 0); c.rect(10, 17, 13, 22, 0)
    return c

def smallplane():
    c = C()
    c.rect(8, 0, 15, 1)
    c.poly([(11, 2), (13, 2), (13, 8), (22, 8), (22, 12), (13, 12), (13, 18), (17, 20), (17, 22), (7, 22), (7, 20), (11, 18), (11, 12), (2, 12), (2, 8), (11, 8)])
    return c
