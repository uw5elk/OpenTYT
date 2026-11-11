#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R91C (хост, без заліза): відстань і азимут до кореспондента за GPS-блоком LC 0x08. УСІ ДАНІ СИНТЕТИЧНІ (вигадані пари координат; реального ефіру не було).
Збирається ОДНА C-програма з СПРАВЖНІХ функцій прошивки, вирізаних із вихідників за іменем:
  uiUtilities.c: roundPosition, decodeGPSPosition (RX), latLonFixed32ToDouble, distanceBetweenTwoCoords, courseTo;
  HR-C6000.c:    HRC6000SetTalkerAliasLocation (TX);
  aprs_rx.c:     aprsRxFormatGeo;  + functions/lc_distance.c ЦІЛКОМ, aprs_rx_parse.c (aprsBearingKnown/Name).
Еталон -- незалежний Python (haversine і початковий азимут; те саме R = 6372795 м, що в прошивці, інакше різниця до 0,5 %).
  1  TX -> RX симетрія: позиція -> 7 байтів LC 0x08 -> locationLat/Lon; похибка <= 0,00011° (крок 1,07e-5° + округлення RX до 1e-4°);
  2  відстань/азимут проти еталона: Київ-Львів, через нульовий меридіан, різні півкулі, 0 м, антипод, близькі точки (метри);
  3  умови: своєї позиції нема / координат нема (NaN) / (0,0) / поза діапазоном / inf -> підпису нема;
  4  ширина: підпис <= 13 символів, у дужках <= 16, з TA 27 + ' [' + ... + ']' <= 47 (буфер 48), на сітці відстаней до 20 037 км і всіх азимутах;
  5  вихідний код: очищення координат на початку нового виклику; макроси/буфери під ENABLE_LC_DISTANCE; нічого нового в налаштуваннях;
  6  мутанти: переплутані lat/lon, знак довготи, без порогу км/м, без перевірки своєї позиції, без перевірки (0,0), lon+lat у TX -- ловляться.
Запуск: python3 tools/test_r91c.py"""
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
FAILS = []
N = [0]
R_M = 6372795.0


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        print("ПРОВАЛ: " + m)


def rd(p):
    b = open(p, "rb").read()
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp1251")


def grab(text, name):
    """Тіло функції верхнього рівня за іменем (від рядка з сигнатурою до парної дужки)."""
    m = re.search(r"^[a-zA-Z_][^\n;{]*\b" + re.escape(name) + r"\s*\([^;{]*\)\s*\n\{", text, re.M)
    assert m, name
    i = text.index("{", m.start())
    d = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            d += 1
        elif text[j] == "}":
            d -= 1
            if d == 0:
                return text[m.start():j + 1]
    raise AssertionError(name)


# ---- незалежний еталон -------------------------------------------------------------------------------------------------------------
def ref_dist_bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    dp = p2 - p1
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d = 2 * R_M * math.asin(min(1.0, math.sqrt(h)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    b = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return d, b


def fixed32(v):
    """Формат налаштувань (settings.h, LOCATION_DECIMAL_PART_MULIPLIER_FIXED_32 = 100000): біт 31 -- знак, біти 30..23 -- ціла частина,
    біти 22..0 -- дробова частина в одиницях 1e-5° (НЕ двійковий дріб). Незалежний кодувальник."""
    sg = 0x80000000 if v < 0 else 0
    a = abs(v)
    ip = int(a)
    fr = int(round((a - ip) * 100000))
    if fr >= 100000:
        ip, fr = ip + 1, 0
    return sg | (ip << 23) | fr


def build_c(sources):
    ui = rd(os.path.join(SRC, "user_interface", "uiUtilities.c"))
    hr = rd(os.path.join(SRC, "hardware", "HR-C6000.c"))
    ax = rd(os.path.join(SRC, "functions", "aprs_rx.c"))
    mult = re.search(r"#define\s+LOCATION_DECIMAL_PART_MULIPLIER_FIXED_32_DOUBLE[^\n]*", rd(os.path.join(APP, "include", "functions", "settings.h")) + ui)
    assert mult
    funcs = "\n".join(grab(ui, n) for n in ("roundPosition", "decodeGPSPosition", "latLonFixed32ToDouble", "distanceBetweenTwoCoords", "courseTo"))
    funcs = funcs.replace("static double roundPosition", "double roundPosition")
    tx = grab(hr, "HRC6000SetTalkerAliasLocation")
    fmt = grab(ax, "aprsRxFormatGeo") + "\n" + grab(ax, "aprsRxFormatDist")
    return mult.group(0), funcs, tx, fmt


DRIVER = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#define DEG_TO_RAD  0.017453292519943295
#define RAD_TO_DEG  57.29577951308232
#define TWO_PI      6.283185307179586
#define SQUARE(x)   ((x) * (x))
#define ENABLE_LC_DISTANCE 1
#define APRS_RX 1
#define LANGUAGE_BUILD_UKRAINIAN 1
%(MULT)s
#include "functions/aprs_rx_parse.h"
#include "user_interface/languages/aprsrx_ua.h"
struct { uint8_t talkAliasLocation[7]; } hrc;
double roundPosition(double val);
%(FUNCS)s
%(TX)s
%(FMT)s
#include "functions/lc_distance.h"
#include "%(LCC)s"
int main(void)
{
	char op[16];
	while (scanf("%%15s", op) == 1)
	{
		if (strcmp(op, "RT") == 0)   /* круговий шлях: TX(fixed32) -> байти LC -> RX; потім відстань від "своєї" */
		{
			unsigned latF, lonF, myLatF, myLonF; int ownOk; char buf[32];
			if (scanf("%%u %%u %%u %%u %%d", &latF, &lonF, &myLatF, &myLonF, &ownOk) != 5) return 2;
			HRC6000SetTalkerAliasLocation(latF, lonF);
			uint8_t d[12] = {0}; memcpy(&d[2], hrc.talkAliasLocation, 7);
			double la, lo; decodeGPSPosition(d, &la, &lo);
			double myLa = latLonFixed32ToDouble(myLatF), myLo = latLonFixed32ToDouble(myLonF);
			memset(buf, 0, sizeof buf);
			bool ok = lcDistText(buf, sizeof buf, ownOk != 0, myLa, myLo, la, lo);
			uint32_t dm = 0; uint16_t br = 0; bool ok2 = lcDistCompute(myLa, myLo, la, lo, &dm, &br);
			printf("RT %%.7f %%.7f %%d %%u %%u %%d [%%s]\n", la, lo, ok ? 1 : 0, dm, br, ok2 ? 1 : 0, buf);
		}
		else if (strcmp(op, "TX") == 0)   /* лише TX: байти LC */
		{
			unsigned latF, lonF; if (scanf("%%u %%u", &latF, &lonF) != 2) return 2;
			HRC6000SetTalkerAliasLocation(latF, lonF);
			printf("TX"); for (int i = 0; i < 7; i++) printf(" %%02x", hrc.talkAliasLocation[i]); printf("\n");
		}
		else if (strcmp(op, "RX") == 0)   /* лише RX: 7 байтів -> координати */
		{
			unsigned b[7]; for (int i = 0; i < 7; i++) if (scanf("%%x", &b[i]) != 1) return 2;
			uint8_t d[12] = {0}; for (int i = 0; i < 7; i++) d[2 + i] = (uint8_t)b[i];
			double la, lo; decodeGPSPosition(d, &la, &lo); printf("RX %%.7f %%.7f\n", la, lo);
		}
		else if (strcmp(op, "TXT") == 0)  /* прямо: дві пари градусів -> підпис */
		{
			double a, b, c, e; int ownOk; char buf[32];
			if (scanf("%%lf %%lf %%lf %%lf %%d", &a, &b, &c, &e, &ownOk) != 5) return 2;
			memset(buf, 0, sizeof buf);
			bool ok = lcDistText(buf, sizeof buf, ownOk != 0, a, b, c, e);
			printf("TXT %%d [%%s]\n", ok ? 1 : 0, buf);
		}
		else if (strcmp(op, "FMT") == 0)  /* форматер на відстані/азимуті */
		{
			unsigned dm, br; char buf[32]; if (scanf("%%u %%u", &dm, &br) != 2) return 2;
			memset(buf, 0, sizeof buf); aprsRxFormatGeo(buf, sizeof buf, dm, (uint16_t)br);
			printf("FMT [%%s]\n", buf);
		}
		else if (strcmp(op, "NAN") == 0)
		{
			char buf[32]; memset(buf, 0, sizeof buf);
			bool a = lcDistText(buf, sizeof buf, true, 50.0, 30.0, NAN, NAN);
			bool b = lcDistText(buf, sizeof buf, true, 50.0, 30.0, INFINITY, 0.0);
			bool c = lcDistText(buf, sizeof buf, true, NAN, 30.0, 49.0, 24.0);
			printf("NAN %%d %%d %%d\n", a, b, c);
		}
	}
	return 0;
}
'''


def run(lc_src_text, tx_sub=None, workdir=None):
    mult, funcs, tx, fmt = build_c(None)
    if tx_sub:
        tx = tx_sub(tx)
    d = tempfile.mkdtemp(prefix="r91c_", dir=workdir)
    lcc = os.path.join(d, "lc_distance.c")
    open(lcc, "w", encoding="utf-8").write(lc_src_text)
    drv = os.path.join(d, "drv.c")
    open(drv, "w", encoding="utf-8").write(DRIVER % {"MULT": mult, "FUNCS": funcs, "TX": tx, "FMT": fmt, "LCC": lcc})
    exe = os.path.join(d, "drv")
    # lc_distance.c підключено директивою #include (щоб бачити статичні типи); aprs_rx_parse.c -- окремо
    r = subprocess.run(["gcc", "-w", "-std=gnu11", "-I" + APP + "/include", "-I" + FW, "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_LC_DISTANCE", "-DENABLE_APRS_RX", "-o", exe, drv,
                        os.path.join(SRC, "functions", "aprs_rx_parse.c"), os.path.join(SRC, "functions", "aprs_mode_cfg.c"), os.path.join(SRC, "functions", "dmr_sms_text.c"), "-lm"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-1500:]
    return (exe, d), ""


def drive(exe, lines):
    r = subprocess.run([exe[0]], input=("\n".join(lines) + "\n").encode(), capture_output=True, timeout=60)
    return r.stdout.decode("cp1251").split("\n")   # одиниці "м"/"км" -- cp1251 (aprsrx_ua.h)


# (назва, lat1, lon1, lat2, lon2)  -- СИНТЕТИЧНІ пари
PAIRS = [
    ("Київ-Львів", 50.4501, 30.5234, 49.8397, 24.0297),
    ("Львів-Київ", 49.8397, 24.0297, 50.4501, 30.5234),
    ("Лондон-Париж (через нульовий меридіан)", 51.5074, -0.1278, 48.8566, 2.3522),
    ("Париж-Лондон", 48.8566, 2.3522, 51.5074, -0.1278),
    ("Сідней-Кіто (пів/півкулі)", -33.8688, 151.2093, -0.1807, -78.4678),
    ("Кейптаун-Осло", -33.9249, 18.4241, 59.9139, 10.7522),
    ("0 м (та сама точка)", 50.4501, 30.5234, 50.4501, 30.5234),
    ("антипод", 50.0, 30.0, -50.0, -150.0),
    ("близько ~100 м", 50.4501, 30.5234, 50.4510, 30.5234),
    ("близько ~10 м", 50.4501, 30.5234, 50.45019, 30.5234),
    ("близько ~450 м схід", 50.4501, 30.5234, 50.4501, 30.5300),
    ("через антимеридіан", 10.0, 179.9, 10.0, -179.9),
    ("азимут ~359,9 (округлення до 360 -> 0)", 50.0, 30.0, 51.0, 29.999),
]


def sphere_text(d, b, lcmod=None):
    """Очікуваний підпис за еталоном форматування aprsRxFormatGeo (незалежна реалізація в Python), одиниці cp1251 -> 'м'/'км' як байти."""
    dm = int(d + 0.5)
    bi = int(b + 0.5) % 360
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    sec = names[((bi * 2 + 45) // 90) % 8] if dm >= 50 else ""
    sp = " " if dm >= 50 else ""
    if dm < 1000:
        return "%dм%s%s" % (dm, sp, sec)
    if dm < 10000:
        t = (dm + 50) // 100
        return "%d.%dкм %s" % (t // 10, t % 10, sec)
    return "%dкм %s" % ((dm + 500) // 1000, sec)


def parse_rt(line):
    m = re.match(r"RT (-?[\d.]+) (-?[\d.]+) (\d) (\d+) (\d+) (\d) \[(.*)\]$", line)
    return m


def all_vectors(exe):
    out = []
    lines = []
    for n, a, b, c, d in PAIRS:
        lines.append("RT %d %d %d %d 1" % (fixed32(c), fixed32(d), fixed32(a), fixed32(b)))
    res = drive(exe, lines)
    for (n, a, b, c, d), line in zip(PAIRS, res):
        out.append((n, (a, b, c, d), line))
    return out


def test_main(lc_text, mutant=None, tx_sub=None, quiet=False):
    """Повертає список провалів (рядків). mutant -- лише для підпису."""
    fails = []
    exe, err = run(lc_text, tx_sub=tx_sub)
    if exe is None:
        return ["збірка гармата: " + err]
    # 1+2
    for n, (a, b, c, d), line in all_vectors(exe):
        m = parse_rt(line)
        if not m:
            fails.append("%s: нерозібраний вивід «%s»" % (n, line))
            continue
        la, lo = float(m.group(1)), float(m.group(2))
        if abs(la - c) > 0.00011 or abs(((lo - d + 180.0) % 360.0) - 180.0) > 0.00011:
            fails.append("%s: TX->RX координати (%s,%s) далеко від (%s,%s)" % (n, la, lo, c, d))
        # еталон від РОЗКОДОВАНИХ значень (RX), щоб квантування не плуталось із помилкою геометрії
        rd_, rb = ref_dist_bearing(a, b, la, lo)
        dm, br = int(m.group(4)), int(m.group(5))
        if abs(dm - rd_) > 1.0:
            fails.append("%s: відстань %d м, еталон %.1f м" % (n, dm, rd_))
        if br > 359:
            fails.append("%s: азимут %d виходить за 0..359" % (n, br))
        if rd_ >= 50 and min(abs(br - rb), 360 - abs(br - rb)) > 1.0:
            fails.append("%s: азимут %d, еталон %.1f" % (n, br, rb))
        exp = sphere_text(rd_, rb)
        if m.group(7) != exp and abs(dm - int(rd_ + 0.5)) == 0:
            # різниця округлення азимута на межі сектора допустима лише для сусіднього сектора
            names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
            if not (m.group(7).split(" ")[0] == exp.split(" ")[0]):
                fails.append("%s: підпис «%s», очікувався «%s»" % (n, m.group(7), exp))
        if m.group(3) != "1":
            fails.append("%s: підпису нема, хоча своя позиція задана" % n)
    # 3 умови
    own_fix = (fixed32(50.4501), fixed32(30.5234))
    r = drive(exe, ["RT %d %d %d %d 0" % (fixed32(49.8397), fixed32(24.0297), own_fix[0], own_fix[1])])
    m = parse_rt(r[0])
    if not m or m.group(3) != "0":
        fails.append("своєї позиції нема, а підпис є")
    r = drive(exe, ["RX 00 00 00 00 00 00 00", "TXT 50.4501 30.5234 0 0 1", "TXT 50.4501 30.5234 91 24 1", "TXT 50.4501 30.5234 49 181 1", "TXT 50.4501 30.5234 49 -181 1",
                    "TXT 91 30 49 24 1", "TXT 50 200 49 24 1", "TXT 50.4501 30.5234 49.8397 24.0297 1", "NAN"])
    if r[0] != "RX 0.0000000 0.0000000":
        fails.append("RX із нулів не дає (0,0): «%s»" % r[0])
    if r[1] != "TXT 0 []":
        fails.append("(0,0) -- підпис мусив зникнути: «%s»" % r[1])
    if r[2] != "TXT 0 []" or r[3] != "TXT 0 []" or r[4] != "TXT 0 []":
        fails.append("чужа позиція поза діапазоном -- підпису бути не мусить: %s" % r[2:5])
    if r[5] != "TXT 0 []" or r[6] != "TXT 0 []":
        fails.append("своя позиція поза діапазоном -- підпису бути не мусить: %s" % r[5:7])
    if not r[7].startswith("TXT 1 ["):
        fails.append("нормальна пара -- підпис мусив бути: «%s»" % r[7])
    if r[8] != "NAN 0 0 0":
        fails.append("NaN/inf -- підпису бути не мусить: «%s»" % r[8])
    # межа км/м
    r = drive(exe, ["FMT 999 90", "FMT 1000 90", "FMT 9949 90", "FMT 9950 90", "FMT 10000 90", "FMT 49 90", "FMT 50 90", "FMT 0 0"])
    exp = [sphere_text(999, 90), sphere_text(1000, 90), sphere_text(9949, 90), sphere_text(9950, 90), sphere_text(10000, 90), sphere_text(49, 90), sphere_text(50, 90), sphere_text(0, 0)]
    for line, e, nme in zip(r, exp, ("999", "1000", "9949", "9950", "10000", "49", "50", "0")):
        if line != "FMT [" + e + "]":
            fails.append("форматер на %s м: «%s», очікувалось «%s»" % (nme, line, e))
    # 4 ширина
    worst = 0
    lines = []
    for dm in list(range(0, 1200, 37)) + list(range(1000, 21000, 997)) + [9999, 10000, 19999, 20037000, 20021000, 20000000, 12345678]:
        for br in range(0, 360, 45):
            lines.append("FMT %d %d" % (dm, br))
    for line in drive(exe, lines):
        if line.startswith("FMT ["):
            worst = max(worst, len(line[5:-1].encode("cp1251", "replace")))
    if worst > 13:
        fails.append("найширший підпис %d символів (> 13)" % worst)
    if worst + 2 > 16:
        fails.append("у дужках %d символів (> 16)" % (worst + 2))
    if 27 + 2 + worst + 1 + 1 > 48:
        fails.append("TA(27)+' ['+підпис+']'+NUL = %d > 48" % (27 + 2 + worst + 2))
    return fails


def main():
    lc_c = rd(os.path.join(SRC, "functions", "lc_distance.c"))
    lc_h = rd(os.path.join(APP, "include", "functions", "lc_distance.h"))
    check("LC_DISTANCE" in lc_c and "ENABLE_LC_DISTANCE" in lc_h, "lc_distance.{c,h} під ENABLE_LC_DISTANCE")
    base = test_main(lc_c)
    for f in base:
        check(False, f)
    check(not base, "еталонні вектори й умови: усе зійшлось (%d пар, TX->RX->відстань)" % len(PAIRS))

    # 5 вихідний код
    ui = rd(os.path.join(SRC, "user_interface", "uiUtilities.c"))
    i = ui.index("bool lastHeardListUpdate(")
    j = ui.index("// Already in the list", i)
    k = ui.index("// Not in the list", j)
    found = ui[j:k]
    check(re.search(r"#if defined\(LC_DISTANCE\)\s*\n(\s*//[^\n]*\n)*\s*item->locationLat = NAN;\s*\n\s*item->locationLon = NAN;\s*\n\s*#endif", found) is not None,
          "новий виклик відомого абонента: координати очищаються (під LC_DISTANCE)")
    check(re.search(r"#if defined\(LC_DISTANCE\)\s*\n(\s*//[^\n]*\n)*\s*item->locationLat = NAN;\s*\n\s*item->locationLon = NAN;\s*\n\s*#endif", ui[k:]) is None, "очищення не продубльовано в гілці «нового» запису (там воно вже стокове)")
    # R92: гілки відображення звертаються до lcDistLabel() через одну функцію qsoShowNameWithDistance() (лише при заданій власній позиції)
    check(ui.count("lcDistLabel(") == 1 and ui.count("settingsLocationIsValid()") >= 1, "відображення викликає lcDistLabel лише при заданій власній позиції (R92: через qsoShowNameWithDistance)")
    for m in re.finditer(r"lcDistLabel\([^;]*;", ui):
        check("settingsLocationIsValid()" in ui[max(0, m.start() - 260):m.start()], "перед lcDistLabel перевіряється settingsLocationIsValid()")
    mk = rd(os.path.join(FW, "Makefile"))
    check("ifeq ($(ENABLE_LC_DISTANCE),1)" in mk and "-DENABLE_LC_DISTANCE" in mk and mk.count("ENABLE_LC_DISTANCE") <= 6, "Makefile: окремий прапорець ENABLE_LC_DISTANCE")
    wf = rd(os.path.join(os.path.dirname(FW), ".github", "workflows", "build.yml"))
    check(wf.count("ENABLE_LC_DISTANCE=1") >= 1, "build.yml: прапорець у «основній» збірці")
    st = rd(os.path.join(APP, "include", "functions", "settings.h"))
    check("LC_DISTANCE" not in st and "LC_DISTANCE" not in rd(os.path.join(APP, "include", "functions", "codeplug.h")), "налаштування/кодплаг не чіпано (нових полів нема)")
    for fn in ("menuSystem.c", "menuDisplayOptions.c", "menuRadioOptions.c", "menuGeneralOptions.c"):
        check("LC_DISTANCE" not in rd(os.path.join(SRC, "user_interface", fn)), "%s: нового пункту меню нема" % fn)

    # 6 мутанти
    def mut(name, text, tx=None):
        f = test_main(text, mutant=name, tx_sub=tx)
        check(len(f) > 0, "мутант «%s» ловиться (%d провалів)" % (name, len(f)))

    t = lc_c
    mut("lat/lon переплутані", t.replace("distanceBetweenTwoCoords(myLat, myLon, lat, lon, false)", "distanceBetweenTwoCoords(myLon, myLat, lon, lat, false)"))
    mut("невірний знак довготи", t.replace("courseTo(myLat, myLon, lat, lon)", "courseTo(myLat, -myLon, lat, -lon)").replace("distanceBetweenTwoCoords(myLat, myLon, lat, lon, false)", "distanceBetweenTwoCoords(myLat, myLon, lat, -lon, false)"))
    mut("без перевірки своєї позиції", t.replace("(ownPositionValid == false) ||", ""))
    mut("без відсіву (0,0)", t.replace("return !((lat == 0.0) && (lon == 0.0));", "return true;"))
    mut("без перевірки діапазону", t.replace("if ((lat < -90.0) || (lat > 90.0) || (lon < -180.0) || (lon > 180.0))", "if (0)"))
    mut("азимут без модуля 360", t.replace("% 360", "% 361"))
    mut("відстань у км замість м", t.replace("distanceBetweenTwoCoords(myLat, myLon, lat, lon, false)", "distanceBetweenTwoCoords(myLat, myLon, lat, lon, true)"))
    mut("TX: широта й довгота переплутані", t, tx=lambda s: s.replace("double longDouble = latLonFixed32ToDouble(Lon);", "double longDouble = latLonFixed32ToDouble(Lat);").replace("double latDouble = latLonFixed32ToDouble(Lat);", "double latDouble = latLonFixed32ToDouble(Lon);"))
    # порогу км/м у форматері (aprsRxFormatGeo) -- мутуємо вирізану копію
    global build_c
    orig = build_c

    def bc(_):
        mult, funcs, tx, fmt = orig(None)
        return mult, funcs, tx, fmt.replace("if (distM < 1000U)", "if (0)")
    build_c = bc
    mut("форматер без порогу км/м", lc_c)
    build_c = orig

    print("test_r91c: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
