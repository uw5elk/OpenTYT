#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R92 (хост, без заліза): напрямок до кореспондента СТРІЛКОЮ у шапці виклику + підпис відстані в УСІХ гілках імені. УСІ ДАНІ СИНТЕТИЧНІ (вигадані координати,
вигадані позивні; реального ефіру й екрана рації не було -- перевіряється геометрія й розкладка за реальним кодом, вирізаним з вихідників).
  1  геометрія lcDistArrowGeom (справжній код, aprsArrowGeom з прошивки): кути 0/45/90/135/180/225/270/315/359/360 -- вістря у очікуваній точці ±1 px (незалежний еталон);
     вся стрілка в комірці 10x10 у правому полі рядка, в межах висоти рядка (16 і 32 при подвійній висоті);
  2  підпис lcDistLabel: лише відстань (без літер сторони), поріг 50 м (45 м -- стрілки нема, 55 м -- є), азимут проти незалежного еталона, неприда­тні координати/своя позиція;
  3  розкладка за РЕАЛЬНИМИ displayContactTextInfos + displaySplitOrSpanText + switch з uiUtilities.c (вирізані, із заглушками дисплея): для кожної з 4 пріоритетів і 3 режимів
     розділення, для гілок TA / "ID:" / ім'я кодплагу / ім'я БД DMR ID -- підпис є, коли є координати й власна позиція; нема, коли їх нема; стрілка стоїть у тому ж рядку, що й підпис,
     комірка стрілки не перекриває жоден надрукований рядок (текст <= 16 символів по 8 px або <= 21 по 6 px);
  4  мутанти: кут від півдня, проти годинникової, без порогу, комірка в тексті, завжди другий рядок, гілка без підпису (по одній з чотирьох), без перевірки власної позиції.
Запуск: python3 tools/test_r92.py"""
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
QUIET = [False]
ARROWS = [0]
R_M = 6371000.0


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


def grab(text, name):
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


def grab_switch(text):
    """switch за пріоритетом показу в шапці виклику (той, що друкує через displayContactTextInfos; перший switch -- пошук контакту в lastHeardListUpdate)."""
    pos = 0
    while True:
        a = text.index("switch (nonVolatileSettings.contactDisplayPriority)", pos)
        i = text.index("{", a)
        d = 0
        for j in range(i, len(text)):
            if text[j] == "{":
                d += 1
            elif text[j] == "}":
                d -= 1
                if d == 0:
                    break
        body = text[a:j + 1]
        if "displayContactTextInfos" in body:
            return body
        pos = j


# ---- незалежний еталон -------------------------------------------------------------------------------------------------------------
def ref_dist_bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    dp = p2 - p1
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d = 2 * R_M * math.asin(min(1.0, math.sqrt(h)))
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return d, (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def ref_label(dm):
    dm = int(dm + 0.5)
    if dm < 1000:
        return "%dм" % dm
    if dm < 10000:
        t = (dm + 50) // 100
        return "%d.%dкм" % (t // 10, t % 10)
    return "%dкм" % ((dm + 500) // 1000)


DRIVER = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#define DEG_TO_RAD  0.017453292519943295
#define RAD_TO_DEG  57.29577951308232
#define TWO_PI      6.283185307179586
#define SQUARE(x)   ((x) * (x))
#define ENABLE_LC_DISTANCE 1
#define APRS_RX 1
#define LANGUAGE_BUILD_UKRAINIAN 1
#define HAS_COLOURS 1
#include "functions/aprs_rx_parse.h"
#include "user_interface/languages/aprsrx_ua.h"
%(MULT)s
double roundPosition(double val);
%(FUNCS)s
%(FMT)s
#include "functions/lc_distance.h"
#include "%(LCC)s"

/* ---- заглушки прошивки ---- */
#define MAX_DMR_ID_CONTACT_TEXT_LENGTH 51
#define DISPLAY_SIZE_X 160
#define FONT_SIZE_1_HEIGHT 8
#define FONT_SIZE_3_HEIGHT 16
#define DISPLAY_Y_POS_CHANNEL_SECOND_LINE (48 + 48)
#define DISPLAY_INFO_CHANNEL 1
#define THEME_ITEM_FG_CHANNEL_CONTACT_INFO 1
#define THEME_ITEM_BG 2
typedef int ucFont_t;
#define FONT_SIZE_1 1
#define FONT_SIZE_3 3
enum SPLIT_CONTACT { SPLIT_CONTACT_SINGLE_LINE_ONLY = 0, SPLIT_CONTACT_ON_TWO_LINES, SPLIT_CONTACT_AUTO };
enum CONTACT_DISPLAY_PRIO { CONTACT_DISPLAY_PRIO_CC_DB_TA = 0, CONTACT_DISPLAY_PRIO_DB_CC_TA, CONTACT_DISPLAY_PRIO_TA_CC_DB, CONTACT_DISPLAY_PRIO_TA_DB_CC };
struct { int splitContact; int contactDisplayPriority; } nonVolatileSettings;
typedef struct { char contact[MAX_DMR_ID_CONTACT_TEXT_LENGTH]; char talkerAlias[32]; double locationLat, locationLon; } LinkItem_t;
LinkItem_t *LinkHead;
static bool g_ownValid, g_dbl; static double g_myLat, g_myLon;
bool settingsLocationIsValid(void) { return g_ownValid; }
double settingsLocationGetLatitude(void) { return g_myLat; }
double settingsLocationGetLongitude(void) { return g_myLon; }
#define UI_USES_DOUBLE_HEIGHT() g_dbl
int16_t uiUtilityChannelFirstLineY(void) { return 64; }
void displayThemeApply(int a, int b) { (void)a; (void)b; }
void displayThemeResetToDefault(void) {}
void coordsToMaidenhead(uint8_t *b, double la, double lo) { (void)la; (void)lo; strcpy((char *)b, "JO60AA"); }

typedef struct { int kind; int a, b, c, d; int font; char text[64]; } Ev;   /* kind 1: друк рядка (a = y), 2: лінія (a,b,c,d) */
static Ev ev[64]; static int nev;
static void addprint(int y, const char *t, int font) { Ev *e = &ev[nev++]; e->kind = 1; e->a = y; e->font = font; snprintf(e->text, sizeof e->text, "%%s", t); }
void displayDrawLine(int16_t x0, int16_t y0, int16_t x1, int16_t y1, bool inv) { (void)inv; Ev *e = &ev[nev++]; e->kind = 2; e->a = x0; e->b = y0; e->c = x1; e->d = y1; }
void displayPrintCenteredDoubleHeight(uint16_t y, const char *text, ucFont_t f, bool dbl) { (void)dbl; addprint(y, text, f); }
void uiUtilityDisplayInformation(const char *str, int line, int yo) { (void)line; (void)yo; addprint(64, str, 3); }
static void displayChannelNameOrRxFrequency(char *buffer, size_t maxLen) { (void)buffer; (void)maxLen; addprint(96, "CHANNEL", 3); }

%(CHOMP)s
%(SPACE)s
%(SPLIT)s
%(CTI)s
%(HELPER)s

static void runswitch(void)
{
	%(SWITCH)s
}

static char *fld(char **p) { char *s = *p; char *q = strchr(s, '|'); if (q) { *q = 0; *p = q + 1; } else { *p = s + strlen(s); } return s; }

int main(void)
{
	char line[512];
	while (fgets(line, sizeof line, stdin))
	{
		line[strcspn(line, "\r\n")] = 0;
		char *p = line;
		char *op = fld(&p);
		if (strcmp(op, "ARROW") == 0)
		{
			int rowY = atoi(fld(&p)), rowH = atoi(fld(&p)); unsigned b = (unsigned)atoi(fld(&p));
			lcDistArrow_t a; lcDistArrowGeom(&a, 160, (int16_t)rowY, (int16_t)rowH, (uint16_t)b);
			printf("A %%d %%d %%d %%d %%d %%d %%d %%d %%d %%d\n", a.g.tx, a.g.ty, a.g.lx, a.g.ly, a.g.rx, a.g.ry, a.bx, a.by, a.cx, a.cy);
		}
		else if (strcmp(op, "LABEL") == 0)
		{
			int own = atoi(fld(&p)); double m1 = atof(fld(&p)), m2 = atof(fld(&p)), l1 = atof(fld(&p)), l2 = atof(fld(&p));
			char buf[32]; memset(buf, 0, sizeof buf); uint16_t br = 0; bool k = false;
			bool ok = lcDistLabel(buf, sizeof buf, own != 0, m1, m2, l1, l2, &br, &k);
			printf("L %%d %%d %%u [%%s]\n", ok, k, br, buf);
		}
		else if (strcmp(op, "ROW") == 0)
		{
			int len = atoi(fld(&p)), single = atoi(fld(&p)), autom = atoi(fld(&p));
			printf("R %%d\n", (int)lcDistLabelRow((size_t)len, single != 0, autom != 0));
		}
		else if (strcmp(op, "CASE") == 0)
		{
			/* CASE|prio|split|own|dbl|myLat|myLon|lat|lon|contact|ta */
			nonVolatileSettings.contactDisplayPriority = atoi(fld(&p)); nonVolatileSettings.splitContact = atoi(fld(&p));
			g_ownValid = atoi(fld(&p)) != 0; g_dbl = atoi(fld(&p)) != 0; g_myLat = atof(fld(&p)); g_myLon = atof(fld(&p));
			static LinkItem_t it; memset(&it, 0, sizeof it); LinkHead = &it;
			it.locationLat = atof(fld(&p)); it.locationLon = atof(fld(&p));
			snprintf(it.contact, sizeof it.contact, "%%s", fld(&p)); snprintf(it.talkerAlias, sizeof it.talkerAlias, "%%s", fld(&p));
			nev = 0; runswitch();
			printf("N %%d\n", nev);
			for (int i = 0; i < nev; i++)
			{
				if (ev[i].kind == 1) printf("P %%d %%d [%%s]\n", ev[i].a, ev[i].font, ev[i].text);
				else printf("D %%d %%d %%d %%d\n", ev[i].a, ev[i].b, ev[i].c, ev[i].d);
			}
		}
		fflush(stdout);
	}
	return 0;
}
'''


def build(lc_text, ui_text, lc_h_text=None, tag="r92_"):
    ax = rd(os.path.join(SRC, "functions", "aprs_rx.c"))
    ui_real = rd(os.path.join(SRC, "user_interface", "uiUtilities.c"))
    mult = re.search(r"#define\s+LOCATION_DECIMAL_PART_MULIPLIER_FIXED_32_DOUBLE[^\n]*", rd(os.path.join(APP, "include", "functions", "settings.h")) + ui_real).group(0)
    funcs = "\n".join(grab(ui_real, n) for n in ("distanceBetweenTwoCoords", "courseTo"))
    fmt = grab(ax, "aprsRxFormatGeo") + "\n" + grab(ax, "aprsRxFormatDist")
    helper = grab(ui_text, "qsoShowNameWithDistance")
    d = tempfile.mkdtemp(prefix=tag)
    lcc = os.path.join(d, "lc_distance.c")
    open(lcc, "w", encoding="utf-8").write(lc_text)
    drv = os.path.join(d, "drv.c")
    cti = grab(ui_text, "displayContactTextInfos").replace("static void displayContactTextInfos", "static void displayContactTextInfos")
    split = grab(ui_text, "displaySplitOrSpanText")
    # displayPrintCenteredDoubleHeight/displayPrintCentered у вирізаному displaySplitOrSpanText -- через заглушку; chomp/getFirstSpacePos -- справжні
    src = DRIVER % {"MULT": mult, "FUNCS": funcs, "FMT": fmt, "LCC": lcc, "CHOMP": grab(ui_real, "chomp"), "SPACE": grab(ui_real, "getFirstSpacePos"),
                    "SPLIT": split, "CTI": cti, "HELPER": helper, "SWITCH": grab_switch(ui_text)}
    open(drv, "w", encoding="utf-8").write(src)
    exe = os.path.join(d, "drv")
    r = subprocess.run(["gcc", "-w", "-std=gnu11", "-I" + APP + "/include", "-I" + FW, "-DLANGUAGE_BUILD_UKRAINIAN", "-DENABLE_LC_DISTANCE", "-DENABLE_APRS_RX", "-o", exe, drv,
                        os.path.join(SRC, "functions", "aprs_rx_parse.c"), os.path.join(SRC, "functions", "aprs_mode_cfg.c"), os.path.join(SRC, "functions", "dmr_sms_text.c"), "-lm"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-2500:]
    return exe, ""


def drive(exe, lines):
    r = subprocess.run([exe], input=("\n".join(lines) + "\n").encode("utf-8"), capture_output=True)
    return r.stdout.decode("cp1251", "replace").splitlines()


# ---- сценарії ----------------------------------------------------------------------------------------------------------------------
ANGLES = [0, 45, 90, 135, 180, 225, 270, 315, 359, 360]
MY = (50.0000, 30.0000)


def offset_point(dist_m, brg_deg):
    """Незалежна точка на заданій відстані й азимуті від MY (сферична пряма задача)."""
    d = dist_m / R_M
    b = math.radians(brg_deg)
    p1, l1 = math.radians(MY[0]), math.radians(MY[1])
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), math.degrees(l2)


def test_geometry(exe, label):
    ok = True
    for rowY, rowH in ((64, 16), (96, 16), (96, 32), (64, 32)):
        cmds = ["ARROW|%d|%d|%d" % (rowY, rowH, a) for a in ANGLES]
        out = [l for l in drive(exe, cmds) if l.startswith("A ")]
        if len(out) != len(ANGLES):
            check(False, "%s: геометрія -- отримано %d рядків" % (label, len(out)))
            return False
        for a, l in zip(ANGLES, out):
            tx, ty, lx, ly, rx, ry, bx, by, cx, cy = map(int, l.split()[1:])
            ex = cx + 4 * math.sin(math.radians(a))
            ey = cy - 4 * math.cos(math.radians(a))
            good = abs(tx - ex) <= 1.0 and abs(ty - ey) <= 1.0 and abs(bx - (2 * cx - tx)) == 0 and abs(by - (2 * cy - ty)) == 0
            good = good and cx == 152 and cy == rowY + rowH // 2
            # усі точки в комірці 10x10 (cx±5) і в межах рядка
            xs, ys = [tx, lx, rx, bx], [ty, ly, ry, by]
            good = good and min(xs) >= cx - 5 and max(xs) <= cx + 5 and min(ys) >= rowY and max(ys) < rowY + rowH
            # комірка правіше за найширший текст (16*8 = 128 px по центру => правий край 144)
            good = good and min(xs) > 144
            if not good:
                ok = False
                check(False, "%s: кут %d, рядок (%d,%d): вістря (%d,%d), очікувано (%.1f,%.1f); комірка/межі" % (label, a, rowY, rowH, tx, ty, ex, ey))
    if ok:
        check(True, "")
    return ok


def test_label(exe, label):
    ok = True
    # азимути й відстані проти еталона
    for dist, brg in ((120, 10), (800, 95), (3400, 200), (25000, 300), (468000, 45)):
        la, lo = offset_point(dist, brg)
        out = [l for l in drive(exe, ["LABEL|1|%.7f|%.7f|%.7f|%.7f" % (MY[0], MY[1], la, lo)]) if l.startswith("L ")]
        rd_, rb = ref_dist_bearing(MY[0], MY[1], la, lo)
        m = re.match(r"L (\d) (\d) (\d+) \[(.*)\]", out[0]) if out else None
        if not m:
            ok = False
            check(False, "%s: LABEL не розібрано: %r" % (label, out))
            continue
        okf, kn, br, txt = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
        diff = min(abs(br - rb), 360 - abs(br - rb))
        if not (okf == 1 and kn == 1 and diff <= 1.0 and txt == ref_label(rd_)):
            ok = False
            check(False, "%s: відстань %d м/азимут %d: C дає ok=%d known=%d br=%d [%s], еталон %.1f° [%s]" % (label, dist, brg, okf, kn, br, txt, rb, ref_label(rd_)))
        if re.search(r"[A-Za-z]", txt):
            ok = False
            check(False, "%s: в тексті підпису літери сторони [%s]" % (label, txt))
    # поріг 50 м
    for dist, want in ((20, 0), (45, 0), (55, 1), (70, 1)):
        la, lo = offset_point(dist, 123)
        out = [l for l in drive(exe, ["LABEL|1|%.7f|%.7f|%.7f|%.7f" % (MY[0], MY[1], la, lo)]) if l.startswith("L ")]
        m = re.match(r"L (\d) (\d)", out[0])
        if not (m and int(m.group(1)) == 1 and int(m.group(2)) == want):
            ok = False
            check(False, "%s: поріг 50 м: %d м -> стрілка=%s, очікувано %d" % (label, dist, m.group(2) if m else "?", want))
    # непридатні
    la, lo = offset_point(5000, 10)
    bad = [("власної нема", "LABEL|0|%.7f|%.7f|%.7f|%.7f" % (MY[0], MY[1], la, lo)),
           ("чужа NaN", "LABEL|1|%.7f|%.7f|nan|nan" % MY),
           ("чужа (0,0)", "LABEL|1|%.7f|%.7f|0|0" % MY),
           ("чужа поза діапазоном", "LABEL|1|%.7f|%.7f|95|10" % MY)]
    for nm, c in bad:
        out = [l for l in drive(exe, [c]) if l.startswith("L ")]
        if not out or not out[0].startswith("L 0 "):
            ok = False
            check(False, "%s: %s -- підпис не має з'являтись (%r)" % (label, nm, out))
    if ok:
        check(True, "")
    return ok


def test_rows(exe, label):
    ok = True
    for ln in (5, 13, 16, 17, 30, 42):
        for single, auto in ((1, 0), (0, 0), (0, 1)):
            out = [l for l in drive(exe, ["ROW|%d|%d|%d" % (ln, single, auto)]) if l.startswith("R ")]
            one = single or (auto and ln <= 16)
            exp = (1 if ln <= 16 else 0) if one else 2
            if not out or int(out[0].split()[1]) != exp:
                ok = False
                check(False, "%s: lcDistLabelRow(%d,single=%d,auto=%d) = %s, очікувано %d" % (label, ln, single, auto, out, exp))
    if ok:
        check(True, "")
    return ok


# контексти імені: (назва, contact, ta)
CONTEXTS = [
    ("TA без БД", "ID:2501234", "UT1AB Ivan"),
    ("БД DMR ID без TA", "UT2XYZ Petro Kyiv", ""),
    ("ім'я кодплагу без TA", "TG Ukraine", ""),
    ("і БД, і TA", "UR5ABC Olena", "OLENA UR5ABC"),
    ("коротке ім'я БД", "R2ABC", ""),
    ("довге ім'я БД (50)", "UT3QQQ Volodymyr Oleksandrovych Shevchenko Kharkiv", ""),
    ("довгий TA", "ID:2509999", "UT4ZZZ Mykola Kovalenko Dnipro UA"),
]


def name_source(prio, contact, ta):
    """Яке ім'я друкує шапка (за switch): group1 = CC_DB_TA/DB_CC_TA, group2 = TA_CC_DB/TA_DB_CC."""
    if prio in (0, 1):
        return ta if (contact.startswith("ID:") and ta) else contact
    return ta if ta else contact


def run_cases(exe):
    """Повертає список (опис, очікування, фактичні рядки)."""
    res = []
    far = offset_point(468000, 45)
    near = offset_point(60, 200)
    tiny = offset_point(40, 200)
    COORDS = [("далеко", far, True, True), ("60 м", near, True, True), ("40 м", tiny, True, False), ("нема координат", (float("nan"), float("nan")), False, False),
              ("(0,0)", (0.0, 0.0), False, False)]
    cmds, meta = [], []
    for prio in range(4):
        for split in (0, 1, 2):
            for dbl in (0, 1):
                for own in (1, 0):
                    for cname, (la, lo), usable, arrow in COORDS:
                        for nm, contact, ta in CONTEXTS:
                            cmds.append("CASE|%d|%d|%d|%d|%.7f|%.7f|%.7f|%.7f|%s|%s" % (prio, split, own, dbl, MY[0], MY[1], la, lo, contact, ta))
                            meta.append((prio, split, dbl, own, cname, la, lo, usable, arrow, nm, contact, ta))
    out = drive(exe, cmds)
    i = 0
    for m in meta:
        assert out[i].startswith("N "), out[i]
        n = int(out[i].split()[1])
        i += 1
        rows = out[i:i + n]
        i += n
        res.append((m, rows))
    return res


def parse(rows):
    prints, lines = [], []
    for r in rows:
        if r.startswith("P "):
            mm = re.match(r"P (\d+) (\d+) \[(.*)\]$", r)
            prints.append((int(mm.group(1)), int(mm.group(2)), mm.group(3)))
        else:
            lines.append(tuple(int(x) for x in r.split()[1:]))
    return prints, lines


def test_cases(exe, label):
    ok = True
    cnt = 0
    for m, rows in run_cases(exe):
        prio, split, dbl, own, cname, la, lo, usable, arrow, nm, contact, ta = m
        prints, lines = parse(rows)
        name = name_source(prio, contact, ta)
        where = "%s / prio=%d split=%d dbl=%d own=%d / %s / %s" % (label, prio, split, dbl, own, cname, nm)
        cnt += 1
        has_dist = any(re.search(r"\[\d+(\.\d)?(м|км)\]", t) for _, _, t in prints)
        expect_label = bool(own and usable)
        # видимість: у режимі "лише один рядок" підпис видно, тільки якщо "ім'я [відстань]" вміщається в 16 символів
        if expect_label:
            d_ref, _ = ref_dist_bearing(MY[0], MY[1], la, lo)
            lab = ref_label(d_ref)
            full = name[:42 - len(lab) - 3] + " [" + lab + "]"
            visible = not (split == 0 and len(full) > 16)
            has_exact = any(("[" + lab + "]") in t for _, _, t in prints)
            if has_exact != visible:
                ok = False
                check(False, "%s: підпис [%s] %s, очікувано %s; рядки %r" % (where, lab, "є" if has_exact else "нема", "є" if visible else "нема", prints))
            want_arrow = visible and arrow
        else:
            if has_dist:
                ok = False
                check(False, "%s: підпис відстані з'явився без координат/власної позиції: %r" % (where, prints))
            want_arrow = False
            # без підпису -- стокова поведінка: лише TA з координатами може мати Maidenhead
            if (not (own and usable)) and not any("JO60AA" in t for _, _, t in prints) and ta and name == ta and not (la != la):
                pass
        if len(lines) == 3:
            ARROWS[0] += 1
        if want_arrow != (len(lines) == 3):
            ok = False
            check(False, "%s: ліній стрілки %d, очікувано %d" % (where, len(lines), 3 if want_arrow else 0))
        if lines and len(lines) == 3:
            # лінії: хвіст->вістря, вістря->ліве крило, вістря->праве крило
            (bx, by, tx, ty), (t2x, t2y, lx, ly), (t3x, t3y, rx, ry) = lines
            _, brg = ref_dist_bearing(MY[0], MY[1], la, lo)
            cx, cy = (bx + tx) / 2.0, (by + ty) / 2.0
            ex, ey = cx + 4 * math.sin(math.radians(brg)), cy - 4 * math.cos(math.radians(brg))
            if not (abs(tx - ex) <= 1.0 and abs(ty - ey) <= 1.0 and (t2x, t2y) == (tx, ty) and (t3x, t3y) == (tx, ty)):
                ok = False
                check(False, "%s: напрям стрілки не збігається з азимутом %.1f° (вістря (%d,%d), очікувано (%.1f,%.1f))" % (where, brg, tx, ty, ex, ey))
            rowH = 32 if dbl else 16
            # у якому рядку надруковано підпис?
            lab_y = [y for y, f, t in prints if "[" in t and re.search(r"\d(м|км)\]", t)]
            row_start = 64 if (lab_y and lab_y[0] == 64) else 96
            xs, ys = [bx, tx, lx, rx], [by, ty, ly, ry]
            if not (min(ys) >= row_start and max(ys) < row_start + rowH):
                ok = False
                check(False, "%s: стрілка (y %d..%d) не в рядку підпису (початок %d, висота %d)" % (where, min(ys), max(ys), row_start, rowH))
            # комірка не перекриває жоден надрукований рядок цього ж рядка екрана
            for y, f, t in prints:
                same_row = (row_start <= y < row_start + rowH)
                w = len(t) * (8 if f == 3 else 6)
                right = (160 + w) // 2
                if same_row and min(xs) <= right:
                    ok = False
                    check(False, "%s: комірка стрілки (x від %d) перекриває рядок [%s] (правий край %d)" % (where, min(xs), t, right))
        # ширина кожного надрукованого рядка в межах екрана: шрифт 3 -- <= 16, шрифт 1 -- <= 21 (стокові межі displaySplitOrSpanText); підпис їх не збільшує
        for y, f, t in prints:
            if f == 3 and len(t) > 16 and y in (64, 96) and t not in (name,) and "[" in t and re.search(r"\d(м|км)\]", t):
                ok = False
                check(False, "%s: рядок із підписом [%s] довший за 16 символів" % (where, t))
    if ok:
        check(True, "")
    return ok, cnt


def main():
    lc_c = rd(os.path.join(SRC, "functions", "lc_distance.c"))
    ui = rd(os.path.join(SRC, "user_interface", "uiUtilities.c"))
    exe, err = build(lc_c, ui)
    check(exe is not None, "драйвер зібрався на хості: " + (err or ""))
    if exe is None:
        print(err)
        return 1
    test_geometry(exe, "база")
    test_label(exe, "база")
    test_rows(exe, "база")
    ok, cnt = test_cases(exe, "база")
    check(ARROWS[0] >= 200, "стрілку намальовано в достатній кількості сценаріїв (%d)" % ARROWS[0])
    print("test_r92: сценаріїв гілок: %d, зі стрілкою: %d" % (cnt, ARROWS[0]))

    # джерельні перевірки: кожен із 4 виклики на місці, під LC_DISTANCE
    sw = grab_switch(ui)
    check(sw.count("qsoShowNameWithDistance(") == 4, "switch: рівно 4 виклики (TA, ID:-фолбек, ім'я з БД/кодплагу в обох групах пріоритетів)")
    check(len(re.findall(r"#if defined\(LC_DISTANCE\)\s*\n[^\n]*\n?\s*(?://[^\n]*\n\s*)?if \(qsoShowNameWithDistance", sw)) + len(re.findall(r"#if defined\(LC_DISTANCE\)[^\n]*\n(?:\s*//[^\n]*\n)*\s*if \(qsoShowNameWithDistance", sw)) >= 4,
          "усі виклики під #if defined(LC_DISTANCE)")
    check("qsoShowNameWithDistance(LinkHead->talkerAlias)" in sw and sw.count("qsoShowNameWithDistance(LinkHead->contact)") == 2, "імена: talkerAlias -- в TA-гілках, contact -- у двох гілках БД/кодплагу")
    h = rd(os.path.join(APP, "include", "functions", "lc_distance.h"))
    check("aprsArrowGeom" in rd(os.path.join(SRC, "functions", "lc_distance.c")) and "ENABLE_LC_DISTANCE" in h, "геометрія -- через aprsArrowGeom (без дубліката)")
    check(not re.search(r"\bsin\(|\bcos\(", rd(os.path.join(SRC, "functions", "lc_distance.c"))), "lc_distance.c не дублює тригонометрію стрілки")

    # ---- мутанти ----
    def mut(name, lc_text=None, ui_text=None, which=None):
        e, er = build(lc_text or lc_c, ui_text or ui, tag="r92m_")
        if e is None:
            check(False, "мутант «%s»: не зібрався: %s" % (name, er[-400:]))
            return
        saved = (list(FAILS), N[0])
        n0 = len(FAILS)
        QUIET[0] = True
        fn = {"geom": test_geometry, "label": test_label, "rows": test_rows}
        caught = False
        for k, f in fn.items():
            if which in (None, k):
                before = len(FAILS)
                f(e, "мутант")
                if len(FAILS) > before:
                    caught = True
        if which in (None, "cases"):
            before = len(FAILS)
            test_cases(e, "мутант")
            if len(FAILS) > before:
                caught = True
        QUIET[0] = False
        del FAILS[n0:]               # провали мутанта -- очікувані, у підсумок не йдуть
        check(caught, "мутант «%s» ловиться" % name)

    mut("кут від півдня (+180)", lc_c.replace("aprsArrowGeom(&a->g, a->cx, a->cy, LC_ARROW_LEN, bearingDeg);", "aprsArrowGeom(&a->g, a->cx, a->cy, LC_ARROW_LEN, (uint16_t)(bearingDeg + 180U));"))
    mut("проти годинникової (360-кут)", lc_c.replace("aprsArrowGeom(&a->g, a->cx, a->cy, LC_ARROW_LEN, bearingDeg);", "aprsArrowGeom(&a->g, a->cx, a->cy, LC_ARROW_LEN, (uint16_t)((360U - (bearingDeg % 360U)) %% 360U));".replace("%%", "%")))
    mut("без порогу 50 м", lc_c.replace("*bearingKnown = aprsBearingKnown(distM);", "*bearingKnown = true;"))
    mut("комірка в тексті (поле 40 px)", lc_c.replace("a->cx = (int16_t)(screenW - LC_ARROW_MARGIN);", "a->cx = (int16_t)(screenW - 40);"))
    mut("завжди другий рядок", lc_c.replace("return (textLen <= 16U) ? LC_ROW_FIRST : LC_ROW_NONE;", "return LC_ROW_SECOND;"))
    mut("центр не в середині рядка", lc_c.replace("a->cy = (int16_t)(rowY + (rowH / 2));", "a->cy = (int16_t)(rowY + rowH);"))
    mut("без перевірки власної позиції", ui_text=ui.replace("(LinkHead->locationLat <= 90) && settingsLocationIsValid() &&", "(LinkHead->locationLat <= 90) &&"), which="cases")
    # гілка без підпису: по одному з 4 викликів замінюється стоковим друком
    sites = [m.start() for m in re.finditer(r"if \(qsoShowNameWithDistance\([^)]*\) == false\)", ui)]
    check(len(sites) == 4, "у коді 4 місця виклику (для мутантів)")
    for idx, st in enumerate(sites):
        m = re.compile(r"if \(qsoShowNameWithDistance\([^)]*\) == false\)").match(ui, st)
        mutated = ui[:st] + "if (1)" + ui[m.end():]
        mut("гілка №%d без підпису" % (idx + 1), ui_text=mutated, which="cases")
    # «ширина»: підпис довшого вигляду -- рядок без обрізання імені
    mut("ім'я без обрізання (підпис випадає за 42)", ui_text=ui.replace("(int)(42U - strlen(label) - 3U)", "50"), which="cases")

    print("test_r92: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
