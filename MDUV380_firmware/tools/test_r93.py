#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R93 (хост, без заліза): єдина форма напрямку -- «навігаційний наконечник» (гострий трикутник з виїмкою ззаду) в екрані APRS, голці сповіщення «пеленг», шапці виклику й передпоказі CPS.
УСІ ДАНІ СИНТЕТИЧНІ (кути -- перебір 0..359, довжини -- справжні константи прошивки); вигляд на екрані рації НЕ перевірявся.
  1  aprsChevronGeom (справжній код aprs_chevron.c) проти незалежного еталона (поворот канонічних точок матрицею): вістря на осі в напрямку азимута, основа симетрична, виїмка на осі,
     пропорції (півширина 0.8*len, виїмка 0.72*len) -- для всіх 360 кутів і довжин 4 (шапка), 15 (голка), 18 (екран APRS) з допуском ±1 px;
  2  вписування: екран APRS -- кутові точки на відстані < 24 px від центру (риски кільця R-6..R-2 = 25..29); голка -- < 20 px (риски кола R-4..R = 20..24); шапка -- у комірці 10x10;
  3  дві заливки (вістря-ліва-виїмка, вістря-права-виїмка) не перекриваються і разом дорівнюють площі наконечника (виїмка на осі);
  4  паритет з передпоказом CPS: screen_views.chevron_geom дає ті самі точки, що C, для всіх 360 кутів і трьох довжин;
  5  джерела: екран APRS, голка (під APRS_RX; стокова лишилась у #else) і шапка викликають aprsChevronGeom; старий стрижень aprsArrowPoly з екрана прибрано;
  6  мутанти: кут від півдня, дзеркально (проти годинникової), без виїмки, інша ширина, перекручена виїмка, передпоказ з іншою довжиною.
Запуск: python3 tools/test_r93.py"""
import math
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
SRC = os.path.join(APP, "source")
sys.path.insert(0, HERE)
FAILS = []
N = [0]
QUIET = [False]


def check(c, m):
    if not QUIET[0]:
        N[0] += 1
    if not c:
        FAILS.append(m)
        if not QUIET[0]:
            print("ПРОВАЛ: " + m)


def rd(p):
    b = open(p, "rb").read()
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1251")


DRIVER = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include "functions/aprs_chevron.h"
int main(int argc, char **argv)
{
	(void)argc;
	int len = atoi(argv[1]);
	for (int b = 0; b < 360; b++)
	{
		aprsChevron_t c; aprsChevronGeom(&c, 100, 60, (int16_t)len, (uint16_t)b);
		printf("%d %d %d %d %d %d %d %d %d\n", b, c.tx, c.ty, c.lx, c.ly, c.rx, c.ry, c.nx, c.ny);
	}
	aprsChevron_t c; aprsChevronGeom(&c, 100, 60, (int16_t)len, 360);
	printf("360 %d %d %d %d %d %d %d %d\n", c.tx, c.ty, c.lx, c.ly, c.rx, c.ry, c.nx, c.ny);
	return 0;
}
'''


def build(parse_text):
    d = tempfile.mkdtemp(prefix="r93_")
    pc = os.path.join(d, "aprs_chevron.c")
    open(pc, "w", encoding="utf-8").write(parse_text)
    drv = os.path.join(d, "drv.c")
    open(drv, "w").write(DRIVER)
    exe = os.path.join(d, "drv")
    r = subprocess.run(["gcc", "-w", "-std=gnu11", "-I" + APP + "/include", "-I" + FW, "-DLANGUAGE_BUILD_UKRAINIAN", "-DAPRS_RX=1", "-DENABLE_APRS_RX", "-o", exe, drv, pc, "-lm"], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-1500:]
    return exe, ""


def geom(exe, ln):
    out = subprocess.run([exe, str(ln)], capture_output=True, text=True).stdout.split("\n")
    rows = {}
    for l in out:
        if l.strip():
            v = list(map(int, l.split()))
            rows[v[0]] = v[1:]
    return rows


def area(p, q, r):
    return abs((q[0] - p[0]) * (r[1] - p[1]) - (r[0] - p[0]) * (q[1] - p[1])) / 2.0


def ref_points(ln, b):
    """Незалежний еталон: канонічні точки в системі (u вздовж осі до вістря, v праворуч) обертаються на кут азимута."""
    a = math.radians(b)
    def rot(u, v):
        # азимут a від півночі за годинниковою: вісь = (sin a, -cos a), права рука = (cos a, sin a)
        return (100 + u * math.sin(a) + v * math.cos(a), 60 - u * math.cos(a) + v * math.sin(a))
    sh = 0.16 * ln   # R98-FIX3 Д: (cx,cy) -- центр описаного кола; середина осі на 0.16*ln попереду
    return {"tip": rot(sh + ln, 0), "left": rot(sh - ln, -0.8 * ln), "right": rot(sh - ln, 0.8 * ln), "notch": rot(sh - 0.72 * ln, 0)}


def test_geom(exe, label):
    ok = True
    for ln in (4, 15, 18):
        rows = geom(exe, ln)
        if len(rows) != 361:
            check(False, "%s: len %d: отримано %d рядків" % (label, ln, len(rows)))
            return False
        for b in range(361):
            v = rows[b]
            pts = {"tip": (v[0], v[1]), "left": (v[2], v[3]), "right": (v[4], v[5]), "notch": (v[6], v[7])}
            ref = ref_points(ln, b % 360)
            for k in pts:
                if abs(pts[k][0] - ref[k][0]) > 1.0 or abs(pts[k][1] - ref[k][1]) > 1.0:
                    ok = False
                    check(False, "%s: len %d кут %d: %s (%d,%d), еталон (%.1f,%.1f)" % (label, ln, b, k, pts[k][0], pts[k][1], ref[k][0], ref[k][1]))
                    break
        # вписування
        mx = max(math.hypot(rows[b][i] - 100, rows[b][i + 1] - 60) for b in range(360) for i in (0, 2, 4, 6))
        lim = {4: 5.7, 15: 20.0, 18: 24.0}[ln]
        if not mx < lim:
            ok = False
            check(False, "%s: len %d: найдальша точка на %.2f px від центру (ліміт %.1f)" % (label, ln, mx, lim))
        if ln == 4:
            for b in range(360):
                xs = [rows[b][i] for i in (0, 2, 4, 6)]
                ys = [rows[b][i] for i in (1, 3, 5, 7)]
                if min(xs) < 95 or max(xs) > 105 or min(ys) < 55 or max(ys) > 65:
                    ok = False
                    check(False, "%s: шапка, кут %d: наконечник виходить за комірку 10x10" % (label, b))
                    break
        # два трикутники не перекриваються й разом складають наконечник (для len >= 15, де округлення дрібне)
        if ln >= 15:
            for b in range(0, 360, 5):
                v = rows[b]
                tip, l, r, n = (v[0], v[1]), (v[2], v[3]), (v[4], v[5]), (v[6], v[7])
                a1, a2 = area(tip, l, n), area(tip, r, n)
                full = area(l, tip, r) - area(l, n, r)
                if abs((a1 + a2) - full) > 0.15 * full + 3.0 or min(a1, a2) < 0.25 * max(a1, a2):
                    ok = False
                    check(False, "%s: len %d кут %d: заливки (%.1f + %.1f) не складають наконечник (%.1f) або несиметричні" % (label, ln, b, a1, a2, full))
                    break
        # напрям: вістря -- у бік азимута (ліво/право -- дзеркальні)
        for b in (0, 90, 180, 270):
            v = rows[b]
            dx, dy = v[0] - 100, v[1] - 60
            t = int(1.16 * ln + 0.5)   # R98-FIX3 Д: вістря на 1.16*ln від центру описаного кола
            exp = {0: (0, -t), 90: (t, 0), 180: (0, t), 270: (-t, 0)}[b]
            if (dx, dy) != exp:
                ok = False
                check(False, "%s: len %d кут %d: вістря зсунуте на (%d,%d), очікувано %s" % (label, ln, b, dx, dy, exp))
    if ok:
        check(True, "")
    return ok


def test_parity(exe, label):
    import screen_views as sv
    ok = True
    for ln in (4, 15, 18):
        rows = geom(exe, ln)
        for b in range(360):
            t, l, r, n = sv.chevron_geom(100, 60, ln, b)
            v = rows[b]
            if (t, l, r, n) != ((v[0], v[1]), (v[2], v[3]), (v[4], v[5]), (v[6], v[7])):
                ok = False
                check(False, "%s: передпоказ CPS і прошивка розходяться (len %d, кут %d): %r проти %r" % (label, ln, b, (t, l, r, n), v))
                break
    if ok:
        check(True, "")
    return ok


def main():
    parse_c = rd(os.path.join(SRC, "functions", "aprs_chevron.c"))
    exe, err = build(parse_c)
    check(exe is not None, "драйвер зібрався: " + err)
    if exe is None:
        print(err)
        return 1
    test_geom(exe, "база")
    test_parity(exe, "база")

    # 5 джерела
    un = rd(os.path.join(SRC, "user_interface", "uiNotification.c"))
    uu = rd(os.path.join(SRC, "user_interface", "uiUtilities.c"))
    lc = rd(os.path.join(SRC, "functions", "lc_distance.c"))
    i = un.index("static void aprsWinDrawArrow(")
    j = un.index("\n}\n", i)
    win = un[i:j]
    check("aprsChevronGeom(" in win and "aprsArrowPoly" not in win, "екран APRS малює наконечник (aprsChevronGeom), без старого стрижня")
    check(win.count("displayFillTriangle(") == 2, "екран APRS: два залиті трикутники")
    k = un.index("// Needle")
    blk = un[k:k + 2500]
    check(re.search(r"#if defined\(APRS_RX\)[\s\S]*aprsChevronGeom\([\s\S]*#else[\s\S]*displayFillTriangle\(x1, y1, x2, y2, x3, y3, true\);[\s\S]*#endif", blk) is not None,
          "голка сповіщення: наконечник під APRS_RX, стокова голка в #else")
    check("aprsChevronGeom(" in lc and "lcDistArrow_t" in uu and uu.count("displayFillTriangle(a.g.") == 2, "шапка виклику: наконечник з aprsChevronGeom двома заливками")
    sv = rd(os.path.join(HERE, "screen_views.py"))
    check("chevron_geom(" in sv and '"BEARING_NEEDLE_LEN": 15' in sv, "передпоказ CPS малює наконечник; довжина 15 = BEARING_RADIUS - 9")
    check("#define BEARING_NEEDLE_LEN         (BEARING_RADIUS - 9)" in un, "довжина голки в прошивці = BEARING_RADIUS - 9 (24 - 9 = 15)")
    check("#define APRS_WIN_ARROW   18" in un, "довжина осі в екрані APRS = 18")
    check("aprsChevronGeom" in rd(os.path.join(APP, "include", "functions", "aprs_chevron.h")), "прототип у заголовку aprs_chevron.h")
    check("aprsChevron" not in rd(os.path.join(APP, "include", "functions", "aprs_rx_parse.h")) and "aprsChevron" not in rd(os.path.join(SRC, "functions", "aprs_rx_parse.c")), "aprs_rx_parse.{h,c} не чіпано (препроцесований вигляд інших файлів не змінюється)")

    # 6 мутанти
    def mut(name, text=None, which="geom", parity_sub=None):
        e, er = build(text or parse_c)
        if e is None:
            check(False, "мутант «%s»: не зібрався: %s" % (name, er[-300:]))
            return
        n0 = len(FAILS)
        QUIET[0] = True
        if which == "geom":
            test_geom(e, "мутант")
        else:
            test_parity(e, "мутант")
        QUIET[0] = False
        caught = len(FAILS) > n0
        del FAILS[n0:]
        check(caught, "мутант «%s» ловиться" % name)

    ch = grab_chevron(parse_c)
    mut("кут від півдня", parse_c.replace(ch, ch.replace("(double)(bearingDeg % 360U) * rad", "(double)((bearingDeg + 180U) % 360U) * rad")))
    mut("дзеркально (проти годинникової)", parse_c.replace(ch, ch.replace("(double)(bearingDeg % 360U) * rad", "(double)((360U - (bearingDeg % 360U)) % 360U) * rad")))
    mut("без виїмки (виїмка = центр основи)", parse_c.replace(ch, ch.replace("const double nd = 0.72 * L;", "const double nd = 1.0 * L;")))
    mut("інша ширина (1.4*len)", parse_c.replace(ch, ch.replace("const double hw = 0.8 * L;", "const double hw = 1.4 * L;")))
    mut("праве й ліве переплутані", parse_c.replace(ch, ch.replace("c->lx = (int16_t)iround(ox + (-dx * L) - (px * hw));", "c->lx = (int16_t)iround(ox + (-dx * L) + (px * hw));")))
    mut("виїмка попереду", parse_c.replace(ch, ch.replace("ox + (-dx * nd)", "ox + (dx * nd)").replace("oy + (-dy * nd)", "oy + (dy * nd)")))
    mut("старий центр (середина осі, R93)", parse_c.replace(ch, ch.replace("const double sh = 0.16 * L;", "const double sh = 0.0 * L;")))   # R98-FIX3 Д
    # паритет: передпоказ з іншою пропорцією
    import screen_views as sv
    orig = sv.chevron_geom
    sv.chevron_geom = lambda cx, cy, length, b: orig(cx, cy, length + 1, b)
    QUIET[0] = True
    n0 = len(FAILS)
    test_parity(exe, "мутант")
    QUIET[0] = False
    caught = len(FAILS) > n0
    del FAILS[n0:]
    sv.chevron_geom = orig
    check(caught, "мутант «передпоказ з іншою довжиною» ловиться (паритет)")

    print("test_r93: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


def grab_chevron(text):
    m = re.search(r"^void aprsChevronGeom\([^)]*\)\s*\n\{", text, re.M)
    i = text.index("{", m.start())
    d = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            d += 1
        elif text[j] == "}":
            d -= 1
            if d == 0:
                return text[m.start():j + 1]
    raise AssertionError


if __name__ == "__main__":
    sys.exit(main())
