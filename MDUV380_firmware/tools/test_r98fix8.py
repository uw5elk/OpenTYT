#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX8 (хост): «Подвійний прийом» -- канал картки B і червона, графіка карток, роумінг у DW.
  А   СПРАВЖНІ dual_channel.c (стан і запис блоку 18) + dualStepB() + dualRedToggle(): «B = X ручкою -> червона (VFO B) -> ручка частоти -> червона -> B = X»
      (X з поточної зони, X з іншої зони, A == B), відкладений запис і перезапуск (dcLoad) -- той самий X; слова «закріплений» у коді/документах нема
  Б   СПРАВЖНІ dualRenderRow()/dualMeterRow()/... (гарнес R98-FIX6) + модель кадрового буфера 160x128 (tools/screen_sim.py, справжні шрифти прошивки):
      смуга 4 px і ▶ лише в обраній картці, ▲/▼ переносить; літери A і B у рамці 11x15 -- відступи лівий == правий, верхній == нижній; рамка однакова; вміст
      обох карток з тих самих x; елементи не перетинаються в усіх станах; мутанти; PNG (--png КАТАЛОГ)
  В   СПРАВЖНІ wakeHopBegin()/wakeHopTry()/wakeHopRestore()/wakeHopPoll()/roamDwOnB() (wake_hop.c, конфігурація DUALCH) + СПРАВЖНІЙ dual_channel.c:
      стрибок з A (стоково: «знайдений» стан), з B (канал картки B = знайдений), невдача -> вихідний, два стрибки поспіль, A знайдений + стрибок з B,
      картка VFO без роумінгу, режим вимкнено -- як було; СПРАВЖНІ dualChannelA()/dualLeaveOnB(); збірки без DW -- токени як у базі; мутанти
Запуск: python3 tools/test_r98fix8.py [--png КАТАЛОГ]"""
import os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
import test_r98fix4 as F4  # noqa
import test_r98fix5 as F5  # noqa
import test_r98fix6 as F6  # noqa
T.COMPAT_A_CHANNEL = False
T.COMPAT_FIX4 = False
T.COMPAT_FIX5 = False
T.COMPAT_FIX6 = False
T.COMPAT_FIX7 = False   # бачимо поточні функції (R98-FIX8)
cmt = T.cmt
FAILS = []; N = [0]
BASE = "e1ca1ad"   # HEAD після R98-FIX7 у дереві розробки (у клоні власника хеш інший -- тоді ПРОПУСК)


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
FN = os.path.join(APP, "source", "functions")
INC = os.path.join(APP, "include")
kv = F5.kv


def run_c(code):
    d = tempfile.mkdtemp(prefix="r98f8_")
    try:
        c = os.path.join(d, "h.c"); open(c, "w", encoding="utf-8").write(code)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-I", INC, "-o", os.path.join(d, "h"), c], capture_output=True)
        if r.returncode != 0:
            print(r.stderr.decode()[:3000]); return None
        return subprocess.run([os.path.join(d, "h")], capture_output=True).stdout.decode()
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ А: канал картки B і червона
A_STUBS = r'''
typedef struct { char name[16]; uint32_t rxFreq; uint32_t txFreq; uint8_t chMode; } CodeplugChannel_t;
typedef struct { int NOT_IN_CODEPLUGDATA_numChannelsInZone; int NOT_IN_CODEPLUGDATA_highestIndex; int NOT_IN_CODEPLUGDATA_indexNumber; uint16_t channels[8]; } CodeplugZone_t;
#define CODEPLUG_ZONE_IS_ALLCHANNELS(z) ((z).NOT_IN_CODEPLUGDATA_indexNumber < 0)
enum { MELODY_ERROR_BEEP = 1 }; enum { SCAN_STATE_SCANNING = 2 }; enum { QSO_DISPLAY_DEFAULT_SCREEN = 1 };
static struct { struct { int state; } Scan; int displayQSOState; } uiDataGlobal;
static CodeplugZone_t currentZone, zone2; static int useZone2 = 0, used[64], lastA = 12, beep = 0, tunes = 0;
static CodeplugChannel_t channelScreenChannelData, settingsVFOChannel[2], *currentChannelData = &channelScreenChannelData;
static uint8_t s_dualBKeep; static uint32_t s_dualKeyMs;
static uint16_t dualZoneChannelAt(int pos, void *ctx) { const CodeplugZone_t *z = ctx ? (const CodeplugZone_t *)ctx : &currentZone; return (pos >= 0 && pos < z->NOT_IN_CODEPLUGDATA_numChannelsInZone && used[z->channels[pos]]) ? z->channels[pos] : 0; }
static const CodeplugZone_t *dualZoneB(CodeplugZone_t *b) { (void)b; return useZone2 ? &zone2 : NULL; }
static uint16_t dualChannelA(void) { return (uint16_t)lastA; }
static bool codeplugAllChannelsIndexIsInUse(int c) { return (c > 0) && (c < 64) && used[c]; }
static void dualBReset(void) { s_dualBKeep = 0; }
static bool dualIsRunning(void) { return true; }
static void dualAutoResume(void) {}
static void dualSuspend(void) {}
static void dualTune(bool b) { (void)b; tunes++; }
static void dualSetDwell(void) {}
static void dualSwapBufs(void) {}
static void soundSetMelody(int m) { (void)m; beep++; }
static void uiChannelModeLoadChannelData(bool a, bool b) { (void)a; (void)b; }
static void uiChannelModeUpdateScreen(int x) { (void)x; }
static void vfoKnob(int d) { settingsVFOChannel[1].rxFreq += (uint32_t)(d * 1250); }   /* ручка на картці VFO -- частота (uiVFOModeDualStep), chB не чіпає */
@@FNS@@
static void z(CodeplugZone_t *zz, int idx, int n, const int *ch) { zz->NOT_IN_CODEPLUGDATA_indexNumber = idx; zz->NOT_IN_CODEPLUGDATA_numChannelsInZone = n; for (int i = 0; i < n; i++) { zz->channels[i] = (uint16_t)ch[i]; used[ch[i]] = 1; } }
static uint32_t now = 1000;
static void tick(void) { now += 4000; dcSaveIfDue(now); now += 4000; dcSaveIfDue(now); }
int main(void)
{
	static const int z1[4] = { 5, 7, 12, 30 }, z2[2] = { 20, 21 };
	z(&currentZone, 1, 4, z1); z(&zone2, 2, 2, z2);
	memset(g_blk, 0, 8); g_have = 0; dcLoad(); dcSetChannelB(5, true); dcSetEnabled(true, true); dcSetPointerB(true);
	/* s1: X = 7 ручкою з 5; червона -> VFO B; ручка частоти; червона -> 7; відкладений запис і «перезапуск» (dcLoad) -- 7, тип «канал» */
	dualStepB(1); int x = dcChannelB(); dualRedToggle(); int t1 = dcTypeB(), c1 = dcChannelB(); vfoKnob(1); vfoKnob(1); dualRedToggle();
	printf("s1=%d,%d,%d,%d,%d", x, t1, c1, dcTypeB(), dcChannelB()); tick(); dcLoad(); printf(",%d,%d,%d\n", dcChannelB(), dcTypeB(), beep);
	/* s2: червона одразу після ручки (запис ще відкладений) -- той самий X; вихід з режиму (запис одразу) і вхід -- той самий X */
	dualStepB(1); x = dcChannelB(); dualRedToggle(); dualRedToggle(); int c2 = dcChannelB(); dcDisableWithReturnA(0, 12); dcLoad(); dcSetEnabled(true, true);
	printf("s2=%d,%d,%d,%d\n", x, c2, dcChannelB(), dcTypeB());
	/* s3: X з іншої зони (SK2 + ручка вибрала зону 2): ручка -> 20; червона, ручка частоти, червона -> 20 */
	useZone2 = 1; dualStepB(1); x = dcChannelB(); dualRedToggle(); vfoKnob(-1); dualRedToggle(); printf("s3=%d,%d,%d\n", x, dcChannelB(), dcTypeB()); useZone2 = 0;
	/* s4: A == B: A = 7, ручкою B = 7 (з 5); червона -> VFO B; червона -> 7 */
	lastA = 7; dcSetChannelB(5, false); dualStepB(1); x = dcChannelB(); dualRedToggle(); int t4 = dcTypeB(); dualRedToggle(); printf("s4=%d,%d,%d,%d\n", x, t4, dcChannelB(), dcTypeB());
	return 0;
}
'''
A_EXP = {"s1": "7,2,7,0,7,7,0,0", "s2": "12,12,12,0", "s3": "20,20,0", "s4": "7,2,7,0"}


def test_a(t):
    dc = T.rd(os.path.join(FN, "dual_channel.c"))
    fns = [T.carve_fn(t, s) for s in ("static void dualStepB(int dir)", "static void dualRedToggle(void)")]
    check(all(fns), "А: dualStepB / dualRedToggle знайдено")
    if not all(fns):
        return
    code = lambda f: F4.prelude(dc) + A_STUBS.replace("@@FNS@@", "\n".join(f))
    out = run_c(code(fns))
    check(out is not None, "А: хостова збірка (справжній dual_channel.c + dualStepB + dualRedToggle)")
    o = kv(out)
    names = {"s1": "B = X ручкою -> червона (VFO B, номер X лишається) -> ручка частоти -> червона -> X; після відкладеного запису й перезапуску -- X",
             "s2": "червона, поки запис ручки відкладений; вихід/вхід у режим -- той самий X",
             "s3": "X з іншої зони (зона B, вибрана SK2 + ручкою) -- червона повертає X",
             "s4": "A == B: B = X = A, червона туди й назад -- X"}
    for k, v in A_EXP.items():
        check(o.get(k) == v, "А1/А3 (%s): %s -- очікувано «%s», є «%s»" % (k, names[k], v, o.get(k)))
    rt = fns[1]
    m = rt.replace("dcSetTypeB(0U);", "(void)dcSetChannelB(dualZoneChannelAt(0, ((void *)0)), 0);")
    mo = kv(run_c(code([fns[0], m]))) if m != rt else {}
    check(m != rt and mo.get("s1") not in (None, A_EXP["s1"]), "А (мутант): червона повертає B на перший канал зони, а не на обраний -- ловиться")
    # А2: слова «закріплений» нема в коді DW, описі блоку 18 і документах
    top = os.path.dirname(FW)
    files = [os.path.join(UI, "uiChannelMode.c"), os.path.join(FN, "dual_channel.c"), os.path.join(INC, "functions", "dual_channel.h"), os.path.join(FN, "wake_hop.c"),
             os.path.join(HERE, "custom_region.py")] + [os.path.join(top, f) for f in ("USAGE.md", "README.md", "STATUS.md", "TESTING.md", os.path.join("docs", "menu-reference.md"), os.path.join("docs", "dual-vfo-recon.md"))]
    hits = [os.path.basename(f) for f in files if os.path.exists(f) and re.search(r"закріплен(ий|ого|ому|им) (канал|VFO)|pinned", T.rd(f), re.I)]
    check(hits == [], "А2: «закріплений канал/VFO» прибрано (замість -- «канал картки B»): %s" % hits)


# ------------------------------------------------------------------------------------------------ Б: графіка карток
def classify(D, ps):
    """Примітив -> елемент картки (за константами R98-FIX8). Повертає {елемент: [примітиви]}, нерозпізнані."""
    el = {}; bad = []
    unx = [p["x"] for p in ps if p["k"] == "T" and p["t"] == "D" and p["font"] == 1]
    unx = unx[0] if unx else None
    for p in ps:
        b = F6.box(p)
        if p["k"] == "r" and p["w"] >= 150:
            name = "frame"
        elif p["k"] == "f" and p["x"] == D["DW_SEL_X"] and p["w"] == D["DW_SEL_W"]:
            name = "stripe"
        elif p["k"] == "l" and D["DW_TRI_X"] <= p["x"] <= D["DW_TRI_X"] + D["DW_TRI_W"] - 1 and p["y"] < D["DW_ROW2_DY"]:
            name = "tri"
        elif (p["k"] == "r" and p["x"] == D["DW_LET_L"] and p["w"] == D["DW_LET_W"]) or (p["k"] == "T" and p["t"] in ("A", "B") and p["font"] == 3 and p["x"] == D["DW_LET_GX"]):
            name = "letter"
        elif p["k"] == "k":
            name = "lock"
        elif (p["k"] == "f" and p["w"] == D["DW_AP_W"] and p["h"] == D["DW_AP_H"]) or (p["k"] == "T" and p["inv"] == 1 and p["t"][:1] == "A" and p["font"] == 1 and p["y"] < D["DW_ROW2_DY"]):
            name = "aprs"
        elif unx is not None and p["y"] < D["DW_ROW2_DY"] and unx <= p["x"] <= unx + D["DW_UN_W"] - 1 and p["k"] in "Trl":
            name = "D"
        elif p["k"] == "T" and p["font"] == 3 and p["y"] == D["DW_ROW1_DY"]:
            name = "row1"
        elif p["k"] == "T" and p["font"] == 3 and p["y"] == D["DW_ROW2_DY"]:
            name = "row2"
        elif p["k"] == "T" and p["y"] == D["DW_ROW3_DY"]:
            name = "row3L" if p["x"] == D["DW_IN_L"] else "row3R"
        elif p["k"] in "tl" and p["y"] >= D["DW_ARROW_DY"] and b[3] <= D["DW_ARROW_DY"] + D["DW_ARROW_CELL"] - 1:
            name = "arrow"
        elif p["y"] >= D["DW_ROW4_DY"]:
            name = "meter"
        else:
            bad.append(p); continue
        el.setdefault(name, []).append(p)
    return el, bad


def analyse(D, line):
    ps = F6.prims_of(line)
    el, bad = classify(D, ps)
    boxes = {k: F6.union([F6.box(p) for p in v]) for k, v in el.items() if k not in ("frame",)}
    if "arrow" in boxes:
        x0, y0, x1, y1 = boxes["arrow"]; cx = (x0 + x1) // 2
        boxes["arrow"] = (cx - 5, D["DW_ARROW_DY"], cx + 4, D["DW_ARROW_DY"] + D["DW_ARROW_CELL"] - 1)
    if "meter" in boxes:
        boxes["meter"] = (D["DW_IN_L"], D["DW_ROW4_DY"], D["DW_IN_R"], D["DW_ROW4_DY"] + D["DW_METER_H"] - 1)
    names = sorted(boxes)
    ov = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if not F5.disjoint(boxes[a], boxes[b])]
    out = [k for k, b in boxes.items() if k != "stripe" and (b[0] < D["DW_IN_L"] or b[2] > D["DW_IN_R"] or b[1] < D["DW_ROW1_DY"] or b[3] > D["DW_ROW4_DY"] + D["DW_METER_H"] - 1)]
    txt = {k: [(p["t"], p["x"]) for p in v if p["k"] == "T"] for k, v in el.items()}
    return ps, el, boxes, bad, ov, out, txt


def render(D, o, ka, kb):
    """Модель кадрового буфера 160x128: шапка + примітиви обох карток (справжні шрифти screen_sim). Повертає Display."""
    import screen_sim as sim
    d = sim.Display()
    d.theme_apply(sim.IT["FG_HEADER_TEXT"], sim.IT["BG_HEADER_TEXT"]); d.fill_rect(0, 0, 160, 10, True)
    d.print_core(1, 2, "DW", sim.FONT_1, sim.ALIGN_LEFT, False)
    d.print_core(160 - 30 - 3 - 18, 2, "87%", sim.FONT_1, sim.ALIGN_LEFT, False)
    d.print_core(160 - 30, 2, "12:34", sim.FONT_1, sim.ALIGN_LEFT, False)
    FONT = {1: sim.FONT_1, 3: sim.FONT_3}
    for key, y0 in ((ka, D["DW_CARD_A_Y"]), (kb, D["DW_CARD_B_Y"])):
        ps = F6.prims_of(o.get(key))
        for p in ps:
            d.theme_apply(sim.IT[p["fg"]], sim.IT["BG"])
            x, y = p["x"], p["y"] + y0
            if p["k"] == "T":
                d.print_core(x, y, p["t"], FONT.get(p["font"], sim.FONT_1), sim.ALIGN_LEFT, bool(p["inv"]))
            elif p["k"] == "f":
                d.fill_rect(x, y, p["w"], p["h"], bool(p["inv"]))
            elif p["k"] == "r":
                d.draw_rect(x, y, p["w"], p["h"], bool(p["inv"]))
            elif p["k"] == "l" and p["y"] < D["DW_ARROW_DY"]:
                d.draw_line(x, y, x + p["w"] - 1, y + p["h"] - 1, True)
            elif p["k"] == "k":   # замок AES -- спрощений контур 10x9 (бітмапи uiDrawAesIconAt у моделі нема)
                d.theme_apply(sim.IT["FG_CHANNEL_NAME"], sim.IT["BG"])
                d.draw_rect(x, y + 3, 10, 6, True); d.draw_rect(x + 2, y, 6, 4, True)
        arr = [p for p in ps if p["k"] == "t"]
        if arr:   # стрілка відстані: справжня геометрія aprsChevronGeom (screen_views.chevron_geom), азимут сценарію 45°
            import screen_views as sv
            cx = (min(p["x"] for p in arr) + max(p["x"] + p["w"] - 1 for p in arr)) // 2
            cy = (min(p["y"] for p in arr) + max(p["y"] + p["h"] - 1 for p in arr)) // 2 + y0
            tip, lft, rgt, notch = sv.chevron_geom(cx, cy, 4, 45)
            d.theme_apply(sim.IT["FG_CHANNEL_CONTACT_INFO"], sim.IT["BG"])
            d.fill_triangle(tip[0], tip[1], lft[0], lft[1], notch[0], notch[1], True)
            d.fill_triangle(tip[0], tip[1], rgt[0], rgt[1], notch[0], notch[1], True)
    return d


def px(d, x, y):
    import screen_sim as sim
    return sim.pixel_item(d, x, y)


def card_pixels(D, d, y0, x0, x1, y1, y2, item):
    import screen_sim as sim
    return [(x, y) for y in range(y0 + y1, y0 + y2 + 1) for x in range(x0, x1 + 1) if px(d, x, y) == sim.IT[item]]


def letter_pads(D, d, y0):
    """Відступи «чорнила» літери до рамки (лівий, правий, верхній, нижній) за кадровим буфером."""
    import screen_sim as sim
    L, W, H, TY = D["DW_LET_L"], D["DW_LET_W"], D["DW_LET_H"], y0 + D["DW_ROW1_DY"]
    ink = [(x, y) for y in range(TY + 1, TY + H - 1) for x in range(L + 1, L + W - 1) if px(d, x, y) == sim.IT["FG_CHANNEL_NAME"]]
    frame = all(px(d, x, TY) == sim.IT["FG_CHANNEL_NAME"] and px(d, x, TY + H - 1) == sim.IT["FG_CHANNEL_NAME"] for x in range(L, L + W)) and \
        all(px(d, L, y) == sim.IT["FG_CHANNEL_NAME"] and px(d, L + W - 1, y) == sim.IT["FG_CHANNEL_NAME"] for y in range(TY, TY + H))
    if not ink:
        return None, frame
    xs = [p[0] for p in ink]; ys = [p[1] for p in ink]
    return (min(xs) - (L + 1), (L + W - 2) - max(xs), min(ys) - (TY + 1), (TY + H - 2) - max(ys)), frame


def test_layout(t, src, png_dir):
    if "#define DW_ROW1_MAX" in src:
        print("ПРОПУСК: Б -- розкладку FIX8 (номер і значки в рядку 1, S-метр на всю ширину) замінено в R98-FIX9 А/Б (повна назва в рядку 1, номер у рядку 3, значки в рядку 4); перевіряє tools/test_r98fix9.py")
        return
    D = F5.consts(src)
    need = ["DW_CARD_X", "DW_CARD_W", "DW_CARD_H", "DW_CARD_A_Y", "DW_CARD_B_Y", "DW_SEL_X", "DW_SEL_W", "DW_IN_L", "DW_IN_R", "DW_ROW1_DY", "DW_ROW2_DY", "DW_ROW3_DY",
            "DW_ROW4_DY", "DW_TRI_X", "DW_TRI_W", "DW_TRI_CY", "DW_LET_L", "DW_LET_W", "DW_LET_H", "DW_LET_GX", "DW_ROW1_TX", "DW_ICON_DY", "DW_UN_W", "DW_AP_W", "DW_AP_H",
            "DW_ROW3_MAX", "DW_ARROW_DY", "DW_ARROW_CELL", "DW_METER_H", "DW_TAG_W", "DW_METER_SEG_W", "DW_METER_STEP", "DW_METER_SEGS", "DW_METER_X", "DW_METER_HOT"]
    check(all(k in D for k in need), "Б: константи розкладки DW_* знайдено: нема %s" % [k for k in need if k not in D])
    if not all(k in D for k in need):
        return
    g = type("G", (), D)
    check(g.DW_SEL_X == g.DW_CARD_X + 1 and g.DW_SEL_W == 4 and g.DW_IN_L == g.DW_SEL_X + g.DW_SEL_W + 1, "Б2: смуга 4 px одразу за рамкою, вміст -- з x=%d (зазор 1 px)" % g.DW_IN_L)
    check(g.DW_LET_W % 2 == 1 and g.DW_LET_H % 2 == 1 and g.DW_LET_L == g.DW_TRI_X + g.DW_TRI_W + 1 and g.DW_LET_GX == g.DW_LET_L + 2 and g.DW_TRI_CY == g.DW_ROW1_DY + g.DW_LET_H // 2,
          "Б1: рамка літери непарна (%dx%d), клітинка літери на 2 px від лівого краю рамки, ▶ по центру рамки" % (g.DW_LET_W, g.DW_LET_H))
    check(g.DW_ROW3_MAX == (g.DW_IN_R + 1 - g.DW_IN_L) // 6 and g.DW_IN_L + g.DW_TAG_W < g.DW_METER_X and g.DW_METER_X + (g.DW_METER_SEGS - 1) * g.DW_METER_STEP + g.DW_METER_SEG_W - 1 == g.DW_IN_R
          and g.DW_METER_SEGS == 11 and g.DW_METER_HOT == 2, "Б2: рядок 3 -- %d символів; S-метр: мітка RX x=%d..%d, 11 сегментів x=%d..%d, два останні червоні" % (g.DW_ROW3_MAX, g.DW_IN_L, g.DW_IN_L + g.DW_TAG_W - 1, g.DW_METER_X, g.DW_IN_R))
    fns = [T.carve_fn(t, s) for s in F6.ROW_SIGS]
    tl = T.pp(FW, INCS, CF["DUALCH"], "application/source/functions/lc_distance.c") or ""
    fa = T.carve_fn(tl, "void lcDistArrowAfter(lcDistArrow_t *a, const lcDistSpan_t *tail, const lcDistSpan_t *above, int16_t screenW, uint16_t bearingDeg)")
    check(all(fns) and fa is not None, "Б: функції картки знайдено")
    if not (all(fns) and fa):
        return
    code = lambda f: F6.ROW_HARNESS.replace("@@FNS@@", fa + "\n" + "\n".join(f))
    out = run_c(code(fns))
    check(out is not None, "Б: хостова збірка карток")
    o = kv(out)
    keys = ("s1a", "s1b", "s2a", "s2b", "s3a", "s3b", "s4a", "s4b", "s5a", "s5b", "s6b", "s7a")
    R = {}
    for k in keys:
        R[k] = analyse(D, o.get(k))
        ps, el, boxes, bad, ov, outz, txt = R[k]
        check(o.get(k) is not None and not bad and not ov and not outz, "Б4 (%s): кожен примітив -- у своєму елементі, без перетинів, у полі вмісту: нерозпізнані %s, перетини %s, поза полем %s" % (k, bad[:2], ov, outz))
    sel = {"s1a": 1, "s1b": 0, "s2a": 1, "s2b": 0, "s3a": 0, "s3b": 1, "s4a": 0, "s4b": 1, "s5a": 0, "s5b": 1, "s6b": 0, "s7a": 1}
    for k in keys:
        el = R[k][1]
        has = ("stripe" in el, "tri" in el)
        ok = (has == (True, True)) if sel[k] else (has == (False, False))
        check(ok, "Б2 (%s): смуга і ▶ %s (є: смуга %s, ▶ %s)" % (k, "є в обраній" if sel[k] else "нема в необраній", has[0], has[1]))
        if sel[k] and ok:
            st = el["stripe"][0]; tr = el["tri"]
            check(st["fg"] == "BG_MENU_ITEM_SELECTED" and st["y"] == 1 and st["h"] == g.DW_CARD_H - 2 and all(p["fg"] == "BG_MENU_ITEM_SELECTED" for p in tr)
                  and sorted(p["h"] for p in tr) == [1, 3, 5, 7], "Б2 (%s): смуга x=%d..%d уздовж усього лівого краю, ▶ 4x7 -- колір виділення теми" % (k, g.DW_SEL_X, g.DW_SEL_X + 3))
        fr = el.get("frame", [])
        check(len(fr) == 1 and fr[0]["fg"] == "FG_DECORATION", "Б2 (%s): рамка картки однакова -- 1 px кольором декору" % k)
    # вміст не «стрибає»: картка A (канал 39) обрана (s1a) і необрана (s3a) -- ті самі x
    xs = lambda k: sorted((n, x) for n, v in R[k][6].items() for (_t, x) in v)
    check(xs("s1a") == xs("s3a"), "Б2/Б6: вміст картки однаковий за x, обрана вона чи ні: %s / %s" % (xs("s1a"), xs("s3a")))
    # модель кадрового буфера: смуга/▶ у пікселях; літери симетричні
    pairs = (("1", "s1a", "s1b"), ("2", "s2a", "s2b"), ("3", "s3a", "s3b"), ("4", "s4a", "s4b"), ("5", "s5a", "s5b"))
    for n, ka, kb in pairs:
        d = render(D, o, ka, kb)
        for key, y0 in ((ka, g.DW_CARD_A_Y), (kb, g.DW_CARD_B_Y)):
            sp = card_pixels(D, d, y0, g.DW_SEL_X, g.DW_SEL_X + g.DW_SEL_W - 1, 1, g.DW_CARD_H - 2, "BG_MENU_ITEM_SELECTED")
            tp = card_pixels(D, d, y0, g.DW_TRI_X, g.DW_TRI_X + g.DW_TRI_W - 1, g.DW_ROW1_DY, g.DW_ROW1_DY + g.DW_LET_H - 1, "BG_MENU_ITEM_SELECTED")
            want = (g.DW_SEL_W * (g.DW_CARD_H - 2), 16) if sel[key] else (0, 0)
            check((len(sp), len(tp)) == want, "Б4 (кадр %s, %s): пікселів смуги/▶ %s, очікувано %s" % (n, key, (len(sp), len(tp)), want))
            pads, frame = letter_pads(D, d, y0)
            check(frame and pads is not None and pads[0] == pads[1] and pads[2] == pads[3], "Б1 (кадр %s, %s): літера в рамці -- лівий == правий, верхній == нижній: %s, рамка ціла %s" % (n, key, pads, frame))
    # мутанти
    rr = fns[-1]
    m1 = rr.replace(" if (selected)\n {\n  displayThemeApply(THEME_ITEM_BG_MENU_ITEM_SELECTED", " if (1)\n {\n  displayThemeApply(THEME_ITEM_BG_MENU_ITEM_SELECTED", 1)
    m2 = rr.replace(" if (selected)\n {\n  displayThemeApply(THEME_ITEM_BG_MENU_ITEM_SELECTED", " if (isB == 0)\n {\n  displayThemeApply(THEME_ITEM_BG_MENU_ITEM_SELECTED", 1)
    m3 = rr.replace("displayPrintCore(((((1 + 1) + 4 + 1) + 4 + 1) + 2), (y + 3), letter", "displayPrintCore(((((1 + 1) + 4 + 1) + 4 + 1) + 1), (y + 3), letter", 1)
    for what, m, test in (("смуга й ▶ в обох картках", m1, lambda r: "stripe" in r["s1b"][1]),
                          ("смуга не переходить при зміні покажчика (лишається на A)", m2, lambda r: "stripe" in r["s3a"][1] or "stripe" not in r["s3b"][1]),
                          ("літера зсунута на 1 px (несиметрично)", m3, None)):
        f2 = list(fns); f2[-1] = m
        mo = kv(run_c(code(f2))) if m != rr else {}
        if test is not None:
            r2 = {k: analyse(D, mo.get(k)) for k in ("s1b", "s3a", "s3b")} if mo else {}
            check(m != rr and r2 and test(r2), "Б4 (мутант): %s -- ловиться" % what)
        else:
            caught = False
            if mo:
                d = render(D, mo, "s1a", "s1b"); pads, _f = letter_pads(D, d, g.DW_CARD_A_Y)
                caught = pads is None or pads[0] != pads[1]
            check(m != rr and caught, "Б1 (мутант): %s -- ловиться" % what)
    if png_dir:
        snapshots(D, o, png_dir)


def snapshots(D, o, png_dir):
    """Б5: PNG -- модель кадрового буфера (справжні шрифти прошивки з HX8353E_charset_UA.h, стокова денна тема). Шапка -- як uiUtilityRenderHeaderDw;
    замок AES -- спрощений контур (у моделі нема бітмапи uiDrawAesIconAt); стрілка відстані -- справжня геометрія, азимут сценарію 45°."""
    import screen_sim as sim
    import theme_edit as te
    try:
        from PIL import Image
    except ImportError:
        print("ПРОПУСК: PIL нема -- PNG не згенеровано"); return
    colors = te.stock_colors("day")
    for n, ka, kb in (("1", "s1a", "s1b"), ("2", "s2a", "s2b"), ("3", "s3a", "s3b"), ("4", "s4a", "s4b"), ("5", "s5a", "s5b")):
        d = render(D, o, ka, kb)
        img = Image.frombytes("RGB", (160, 128), sim.render_rgb(d, colors)).resize((480, 384), Image.NEAREST)
        path = os.path.join(png_dir, "R98FIX8-%s.png" % n)
        img.save(path)
        print("PNG: %s" % path)


# ------------------------------------------------------------------------------------------------ В: роумінг у DW
V_STUBS = r'''
typedef struct { char name[16]; uint32_t rxFreq; uint32_t txFreq; uint8_t txColor; uint8_t list; } CodeplugChannel_t;
typedef struct { int n; } wakeHopTried_t;
enum { UI_CHANNEL_MODE = 3, UI_VFO_MODE = 4 }; enum { RADIO_MODE_ANALOG = 1, RADIO_MODE_DIGITAL = 2 }; enum { USB_MODE_CPS = 0, USB_MODE_HOTSPOT = 1 };
enum { WAKING_MODE_NONE = 0, WAKING_MODE_AWAKEN = 3, WAKING_MODE_FAILED = 4 };
static struct { int currentSelectedChannelNumber; bool reverseRepeaterChannel; bool talkaround; } uiDataGlobal;
static CodeplugChannel_t chans[40], channelScreenChannelData, *currentChannelData = &channelScreenChannelData;
static int settingsUsbMode = USB_MODE_CPS, rootMenu = UI_CHANNEL_MODE, mode = RADIO_MODE_DIGITAL, waking = WAKING_MODE_NONE, roamOn = 1, maxHops = 2, lucz = 5, stockLoads = 0;
static int dead[40], vfoDead;   /* канал «не прокидається»: пробудження на ньому -- FAILED; vfoDead -- те саме для VFO (номер -1) */
static wakeHopTried_t s_tried;
static bool     s_active; static uint16_t s_num; static bool s_listMode; static uint8_t s_hops; static bool s_away; static bool s_success; static bool s_origRoamed;
static uint16_t s_origNum; static uint16_t s_curNum;
static bool roamIsActive(void) { return s_active; }
static uint16_t roamActiveChannel(void) { return s_num; }
static void roamClear(void) { s_active = 0; }
static void wakeHopTriedReset(wakeHopTried_t *t) { t->n = 0; }
static bool wakeHopTriedAdd(wakeHopTried_t *t, uint32_t a, uint32_t b, uint8_t c) { (void)a; (void)b; (void)c; t->n++; return true; }
static bool wakeHopMayRoam(bool on, uint8_t list) { return on && (list != 0); }
static bool wakeHopMayHop(uint8_t h, uint8_t m) { return h < m; }
static bool wakeHopShouldRestore(bool away, bool ok) { return away && !ok; }
static bool roamCfgIsEnabled(void) { return roamOn; }
static uint8_t roamCfgMaxHops(void) { return (uint8_t)maxHops; }
static uint8_t roamCurrentList(void) { return currentChannelData->list; }
static int menuSystemGetRootMenuNumber(void) { return rootMenu; }
static int trxGetMode(void) { return mode; }
static int HRC6000GetIsWakingState(void) { return waking; }
static void HRC6000RestartWakeForRoam(void) {}
static bool candidateIsOk(unsigned n, void *c) { (void)c; return (n < 40) && (chans[n].list != 0) && (chans[n].list == currentChannelData->list); }
static bool wakeHopFindNext(unsigned cur, unsigned lo, unsigned hi, bool (*ok)(unsigned, void *), void *ctx, unsigned *next)
{ (void)lo; (void)hi; for (unsigned i = 1; i < 40; i++) { unsigned n = 1 + ((cur - 1 + i) % 39); if (n == cur) break; if (ok(n, ctx)) { *next = n; return true; } } return false; }
static void roamLoadChannel(int num) { *currentChannelData = chans[num]; uiDataGlobal.currentSelectedChannelNumber = num; }
/* стоковий uiChannelModeLoadChannelData(false, ...): канал зони («останній канал зони») з кодплага */
static void uiChannelModeLoadChannelData(bool mem, bool x) { (void)x; stockLoads++; if (!mem) { channelScreenChannelData = chans[lucz]; uiDataGlobal.currentSelectedChannelNumber = lucz; } }
@@FNS@@
/* передача: Begin; доки пробудження FAILED і є куди -- стрибок (wakeHopTry); кінець -- Restore */
static int ptt(void)
{
	int hops = 0;
	wakeHopBegin();
	for (int i = 0; i < 10; i++)
	{
		int c = uiDataGlobal.currentSelectedChannelNumber;
		waking = ((c > 0 && c < 40) ? dead[c] : vfoDead) ? WAKING_MODE_FAILED : WAKING_MODE_AWAKEN;
		if (waking != WAKING_MODE_FAILED) { wakeHopPoll(); break; }
		if (!wakeHopTry()) break;
		hops++;
	}
	wakeHopRestore();
	return hops;
}
static void mk(int i, int list) { memset(&chans[i], 0, sizeof(chans[i])); snprintf(chans[i].name, 16, "Ch%d", i); chans[i].rxFreq = 43000000U + (uint32_t)i; chans[i].txFreq = chans[i].rxFreq + 760000U; chans[i].list = (uint8_t)list; }
static void onA(int ch) { dcSetOnB(false); channelScreenChannelData = chans[ch]; uiDataGlobal.currentSelectedChannelNumber = ch; }
static void onB(int ch) { dcSetOnB(true); channelScreenChannelData = chans[ch]; uiDataGlobal.currentSelectedChannelNumber = ch; }
static void reset(void) { memset(dead, 0, sizeof(dead)); s_active = 0; s_num = 0; stockLoads = 0; }
int main(void)
{
	for (int i = 1; i < 40; i++) mk(i, 0);
	mk(5, 1); mk(6, 1); mk(9, 1); mk(20, 2); mk(21, 2); mk(22, 2); mk(30, 0);
	memset(g_blk, 0, 8); g_have = 0; dcLoad(); dcSetChannelB(20, true); dcSetEnabled(true, true);
	/* v1: A = 5 (список 1) не прокидається -> стрибок на 6, рація лишається на 6; A -- «знайдений» стоково (s_active, номер 6); B не змінено */
	reset(); dead[5] = 1; onA(5); int h = ptt(); printf("v1=%d,%d,%d,%d,%d,%s\n", h, uiDataGlobal.currentSelectedChannelNumber, roamIsActive(), roamActiveChannel(), dcChannelB(), channelScreenChannelData.name);
	/* v2: B = 20 (список 2) не прокидається -> 21; канал картки B = 21, стан A (s_active) не чіпали */
	reset(); dead[20] = 1; onB(20); h = ptt(); printf("v2=%d,%d,%d,%d,%s\n", h, dcChannelB(), roamIsActive(), uiDataGlobal.currentSelectedChannelNumber, channelScreenChannelData.name);
	/* v3: невдача на B: 21, 22, 20 мовчать (усі в списку 2) -> повернення на вихідний 21 (і канал картки B = 21) */
	reset(); dead[20] = dead[21] = dead[22] = 1; onB(21); h = ptt(); printf("v3=%d,%d,%d,%s\n", h, dcChannelB(), uiDataGlobal.currentSelectedChannelNumber, channelScreenChannelData.name);
	/* v4: два стрибки поспіль на B: 21, 22 мовчать -> 20 (ліміт 2) */
	reset(); dcSetChannelB(21, false); dead[21] = dead[22] = 1; onB(21); h = ptt(); printf("v4=%d,%d\n", h, dcChannelB());
	/* v5: A знайдений (6), потім стрибок з B: стан A лишається (s_active, 6) */
	reset(); dead[5] = 1; onA(5); ptt(); dead[20] = 1; dcSetChannelB(20, false); onB(20); ptt(); printf("v5=%d,%d,%d\n", roamIsActive(), roamActiveChannel(), dcChannelB());
	/* v6: невдача на A (5, 6, 9 мовчать): стоково -- roamClear + канал зони */
	reset(); dead[5] = dead[6] = dead[9] = 1; onA(5); h = ptt(); printf("v6=%d,%d,%d,%d\n", h, roamIsActive(), stockLoads, uiDataGlobal.currentSelectedChannelNumber);
	/* v7: картка VFO (номер CH_DETAILS_VFO_CHANNEL = -1) -- без роумінгу */
	reset(); int b7 = dcChannelB(); onB(5); uiDataGlobal.currentSelectedChannelNumber = -1; vfoDead = 1; h = ptt(); vfoDead = 0; printf("v7=%d,%d,%d\n", h, dcChannelB() == b7, roamIsActive());
	/* v8: режим вимкнено -- стоковий роумінг, як був (стрибок з 5 на 6, «знайдений» стан) */
	reset(); dcSetEnabled(false, true); dcSetChannelB(20, true); dead[5] = 1; onA(5); dcSetOnB(false); h = ptt(); printf("v8=%d,%d,%d,%d\n", h, roamIsActive(), roamActiveChannel(), dcChannelB());
	/* v9: успіх з першої спроби (канал прокидається) -- нічого не змінюється */
	dcSetEnabled(true, true); reset(); onB(20); h = ptt(); printf("v9=%d,%d,%d\n", h, dcChannelB(), roamIsActive());
	return 0;
}
'''
V_EXP = {"v1": "1,6,1,6,20,Ch6", "v2": "1,21,0,21,Ch21", "v3": "2,21,21,Ch21", "v4": "2,20", "v5": "1,6,21", "v6": "2,0,1,5", "v7": "0,1,0", "v8": "1,1,6,20", "v9": "0,20,0"}
V_NAMES = {"v1": "стрибок з A: рація на знайденому (6), A -- «знайдений» стоково, B не змінено", "v2": "стрибок з B: канал картки B = знайдений (21), стан A не чіпали",
           "v3": "невдалий стрибок з B (усі мовчать) -- повернення на вихідний 21", "v4": "два стрибки поспіль з B -- канал картки B = другий знайдений (20)",
           "v5": "A знайдений, потім стрибок з B -- «знайдений» стан A лишається", "v6": "невдача на A -- стоково: roamClear + канал зони",
           "v7": "картка VFO -- роумінгу нема", "v8": "режим вимкнено -- стоковий роумінг без змін", "v9": "прокинувся з першої спроби -- нічого не змінюється"}


def test_roam(tw, t, src):
    sigs = ("static _Bool roamDwOnB(void)", "void wakeHopBegin(void)", "_Bool wakeHopTry(void)", "void wakeHopPoll(void)", "void wakeHopRestore(void)")
    fns = [T.carve_fn(tw, s) for s in sigs]
    check(all(fns), "В: wakeHopBegin/Try/Poll/Restore/roamDwOnB знайдено (wake_hop.c, DUALCH)")
    if not all(fns):
        return
    dc = T.rd(os.path.join(FN, "dual_channel.c"))
    code = lambda f: F4.prelude(dc) + V_STUBS.replace("@@FNS@@", "\n".join(f))
    out = run_c(code(fns))
    check(out is not None, "В: хостова збірка роумінгу (справжні wake_hop.c + dual_channel.c)")
    o = kv(out)
    for k, v in V_EXP.items():
        check(o.get(k) == v, "В3 (%s): %s -- очікувано «%s», є «%s»" % (k, V_NAMES[k], v, o.get(k)))
    b, tr, rs = fns[1], fns[2], fns[4]
    muts = (("роумінг далі вимкнений у DW", 1, b.replace("if (wakeHopMayRoam(roamCfgIsEnabled(), roamCurrentList()) &&", "if (wakeHopMayRoam(roamCfgIsEnabled(), roamCurrentList()) && (dcIsEnabled() == 0) &&"), "v2"),
            ("B не оновлюється на знайдений", 2, tr.replace("(void)dcSetChannelB((uint16_t)next, 0);", ";"), "v2"),
            ("невдалий стрибок лишає на чужому каналі", 4, rs.replace("roamLoadChannel((int)s_origNum);\n   (void)dcSetChannelB(s_origNum, 0);", ";"), "v3"),
            ("роумінг на VFO-картці (нема перевірки номера каналу)", 1, b.replace("(s_origNum >= 1) && (s_origNum <= 1024)", "1"), "v7"),
            ("стрибок з B затирає «знайдений» стан A", 2, tr.replace("(void)dcSetChannelB((uint16_t)next, 0);\n }\n else\n {", "(void)dcSetChannelB((uint16_t)next, 0);\n }\n {"), "v5"))
    for what, idx, m, key in muts:
        f2 = list(fns); f2[idx] = m
        mo = kv(run_c(code(f2))) if m != fns[idx] else {}
        check(m != fns[idx] and mo.get(key) not in (None, V_EXP[key]), "В3 (мутант): %s -- ловиться" % what)
    # A показує знайдений канал; вихід на B знімає «знайдений» стан A; ручка на A -- стоковий LoadChannelData(false) (roamClear)
    ca = T.carve_fn(t, "static uint16_t dualChannelA(void)") or ""
    check("if (roamIsActive())" in ca and "return roamActiveChannel();" in ca, "В1: dualChannelA() -- знайдений роумінгом канал A (картка A, рівність A == B, «A для повернення»)")
    lb = T.carve_fn(t, "static void dualLeaveOnB(void)") or ""
    check(lb.find("roamClear();") >= 0 and lb.find("roamClear();") < lb.rfind("uiChannelModeLoadChannelData(1, 0);"), "В1: вихід з режиму на B знімає «знайдений» стан A до завантаження (номер -- B, а не знайдений A)")
    ld = src[src.find("void uiChannelModeLoadChannelData(bool useChannelDataInMemory, bool loadVoicePromptAnnouncement)"):]
    ld = ld[:ld.find("if (!useChannelDataInMemory)")]
    check(ld.find("dcIsOnB()") < ld.find("roamIsActive()") and "roamClear();" in ld, "В1: на B номер -- канал картки B (гілка R97 раніше за роумінг); явна зміна каналу (ручка на A) -- roamClear, як стоково")


def test_tokens():
    """Збірки без DW (ROAM, UA, AES1): токени wake_hop.c і uiChannelMode.c -- як у базі."""
    if subprocess.run(["git", "-C", FW, "cat-file", "-e", BASE + "^{commit}"], capture_output=True).returncode != 0:
        print("ПРОПУСК: база недоступна (CI/клон без історії): порівняння токенів збірок без DW з %s не виконано" % BASE)
        return
    root = tempfile.mkdtemp(prefix="r98f8_base_")
    try:
        tar = subprocess.run(["git", "-C", FW, "archive", BASE, "application"], capture_output=True)
        subprocess.run(["tar", "-x", "-C", root], input=tar.stdout, check=True)
        for e in os.listdir(FW):
            if e != "application" and not os.path.exists(os.path.join(root, e)):
                os.symlink(os.path.join(FW, e), os.path.join(root, e))
        bad = []
        for name in ("ROAM", "UA", "AES1"):
            if name not in CF:
                continue
            for rel in ("application/source/functions/wake_hop.c", "application/source/user_interface/uiChannelMode.c", "application/source/functions/dual_channel.c"):
                a, b = T.pp(FW, INCS, CF[name], rel), T.pp(root, INCS, CF[name], rel)
                if (a or "").split() != (b or "").split():
                    bad.append((name, os.path.basename(rel)))
        check(bad == [], "В3: збірки без DW (ROAM/UA/AES1) -- токени wake_hop.c, uiChannelMode.c, dual_channel.c як у базі %s: %s" % (BASE, bad))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    global INCS, CF
    INCS, cfgs = cmt.load_configs(FW)
    CF = dict(cfgs)
    F6.INCS, F6.CF = INCS, CF
    png = None
    if "--png" in sys.argv:
        png = sys.argv[sys.argv.index("--png") + 1]
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    t = T.pp(FW, INCS, CF["DUALCH"], "application/source/user_interface/uiChannelMode.c") or ""
    tw = T.pp(FW, INCS, CF["DUALCH"], "application/source/functions/wake_hop.c") or ""
    check(t != "" and tw != "", "препроцесування uiChannelMode.c / wake_hop.c (DUALCH)")
    test_a(t)
    test_layout(t, src, png)
    test_roam(tw, t, src)
    test_tokens()
    print("test_r98fix8: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


INCS = None; CF = None

if __name__ == "__main__":
    sys.exit(main())
