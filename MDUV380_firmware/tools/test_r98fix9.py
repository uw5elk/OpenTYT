#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX9 (хост): «Подвійний прийом» -- картки: повна назва в рядку 1, номер у рядку 3, значки в рядку 4 праворуч, рядок 4 неактивної картки; CPS без кнопок журналу.
  А/Б  СПРАВЖНІ dualRenderRow()/dualMeterRow()/dualRowTag()/... (гарнес R98-FIX6, сценарії FIX9) + модель кадрового буфера 160x128 (tools/screen_sim.py, справжні шрифти):
       «R2 Робочий» і «Домашній HotSpot» у рядку 1 цілком; номер каналу (1..4 цифри) -- початок рядка 3, не обрізається; значки D/конверт, APRS «A», замок -- у рядку 4 праворуч,
       однакові зазори, не перекриваються з S-метром, міткою й частотою; рядок 4 неактивної картки -- мітка + частота (DMR-канал RX, FM-канал і VFO TX); примітиви не перетинаються
       в усіх станах; найгірші випадки (4-цифровий номер, довгі тони/ТГ, усі значки) -- обрізається лише хвіст рядка 3; мутанти; PNG (--png КАТАЛОГ)
  В    контраст смуги виділення до фону картки й до рамки (кольори стокових тем)
  Г    CPS: кнопок «Збільшити»/«Зменшити» нема в коді, документах і вікні; мутанти (кнопка повернулась; межа не тримає мінімум) -- у Tk (xvfb), інакше ПРОПУСК
Запуск: python3 tools/test_r98fix9.py [--png КАТАЛОГ]"""
import os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
import test_r98fix4 as F4  # noqa
import test_r98fix5 as F5  # noqa
import test_r98fix6 as F6  # noqa
import test_r98fix8 as F8  # noqa
T.COMPAT_A_CHANNEL = False
T.COMPAT_FIX4 = False
T.COMPAT_FIX5 = False
T.COMPAT_FIX6 = False
T.COMPAT_FIX7 = False
cmt = T.cmt
FAILS = []; N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
kv = F5.kv
run_c = F8.run_c

# ------------------------------------------------------------------------------------------------ гарнес карток (сценарії FIX9)
# Назви в гарнесі -- ASCII-«плейсхолдери» тієї ж довжини (у кодплазі один символ = один байт); у моделі кадру вони замінюються на кирилицю
PH = {"R2 Robochy": "R2 Робочий", "Domashni HotSpot": "Домашній HotSpot", "R2 Kyiv 145.7": "R2 Київ 145.7"}
assert len(PH["R2 Robochy"]) == 10 and len(PH["Domashni HotSpot"]) == 16 and all(len(k) == len(v) for k, v in PH.items())

ROW_SIGS = ["static Channel_t dualChanOf(const CodeplugChannel_t *ch)", "static void dualCallerText(char *text17)", "static void dualRowTag(int16_t my, const char *tag)",
            "static void dualMeterRow(int16_t y)"] + F6.ROW_SIGS[3:]

H = F6.ROW_HARNESS
H = H.replace("chans[40]", "chans[1100]").replace("used[40]", "used[1100]").replace("(ch > 0) && (ch < 40) && used[ch]", "(ch > 0) && (ch < 1100) && used[ch]")
H = H.replace('const char *getPowerLevel(uint8_t l) { static char b[8]; snprintf(b, sizeof(b), "P%u", (unsigned)l); return b; }',
              'const char *getPowerLevel(uint8_t l) { static char b[8]; snprintf(b, sizeof(b), (l == 9) ? "750" : "3"); return b; }')
H = H.replace('const char *getPowerLevelUnit(uint8_t l) { (void)l; return "W"; }', 'const char *getPowerLevelUnit(uint8_t l) { return (l == 9) ? "mW" : "W"; }')
_A = H.index("	/* назви -- реалістичні")
_B = H.index("	return 0;\n}", _A)
H = H[:_A] + r"""	nonVolatileSettings.txPowerLevel = 2;
#define NAME(i, s) do { memset(chans[i].name, ' ', 16); memcpy(chans[i].name, (s), strlen(s)); } while (0)
	/* канали як у польовій перевірці: A -- «R2 Робочий» (DMR, ключ AES), B -- «Домашній HotSpot» (DMR); решта -- для найгірших випадків */
	chans[9] = chans[5]; NAME(9, "R2 Robochy"); chans[9].txColor = 1; chans[9].encrypt = 1; chans[9].libreDMR_Power = 0;
	chans[15] = chans[5]; NAME(15, "Domashni HotSpot"); chans[15].txColor = 7; chans[15].encrypt = 0; chans[15].libreDMR_Power = 0;
	chans[12] = chans[11]; NAME(12, "UR0LL repeater"); chans[12].chMode = RADIO_MODE_ANALOG; chans[12].rxFreq = 14560000U; chans[12].txFreq = 14600000U; chans[12].rxTone = 885; chans[12].txTone = 885; chans[12].flags = CHANNEL_FLAG_BW_25K;
	chans[39] = chans[5]; NAME(39, "R2 Kyiv 145.7"); chans[39].encrypt = 0; chans[39].libreDMR_Power = 0; chans[39].rxFreq = 43912500U; chans[39].txFreq = 43912500U;
	chans[13] = chans[5]; NAME(13, "WWWWWWWWWWWWWWWW"); chans[13].encrypt = 1; chans[13].libreDMR_Power = 0;
	chans[20] = chans[5]; NAME(20, "X"); chans[20].encrypt = 0; chans[20].libreDMR_Power = 0;
	used[38] = 0;
	chans[9].rxFreq = 43912500U; chans[9].txFreq = 43912500U; chans[15].rxFreq = 43012500U; chans[15].txFreq = 43012500U;
	/* найгірші: 4-цифровий номер, CC15, найдовший ТГ, потужність у мВт; FM з найдовшими тонами (R254.1 T254.1 12.5k) */
	used[1024] = 1; chans[1024] = chans[5]; NAME(1024, "WWWWWWWWWWWWWWWW"); chans[1024].txColor = 15; chans[1024].encrypt = 1; chans[1024].libreDMR_Power = 10;
	used[1023] = 1; chans[1023] = chans[11]; NAME(1023, "FM long tones"); chans[1023].rxTone = 2541; chans[1023].txTone = 2540; chans[1023].flags = 0; chans[1023].libreDMR_Power = 10;
	cts[5].tgNumber = 16777215; cts[5].callType = CONTACT_CALLTYPE_PC; memcpy(cts[5].name, "PC all          ", 16); cts[5].reserve1 = CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;
	chans[1024].contact = 5; chans[5].contact = 2;
	channelScreenChannelData = chans[9];
	/* s1: чергування (польова розкладка): A = 9 «R2 Робочий» з ключем AES і SMS (D12 -> «+»), B = 15 «Домашній HotSpot»; обрана A, обидві неактивні */
	own = 0; known = 1; unD[0] = 12; unD[1] = 0; unA = 0;
	ROW("s1a", 11, false, 9, 0, true, false, false); ROW("s1b", 71, true, 15, 0, false, false, false);
	/* p6: та сама розкладка власника, але обрана B (як на фото): смуга й ▶ на B */
	ROW("p6a", 11, false, 9, 0, false, false, false); ROW("p6b", 71, true, 15, 0, true, false, false);
	/* s2: прийом DMR на A: абонент, відстань, стрілка, S-метр, значки лишаються */
	own = 1; known = 1; rssi = -70; strcpy(item.contact, "ID:2550213"); strcpy(item.talkerAlias, "UR5EQF Bogdan"); strcpy(item.talkgroup, "TG 91234567");
	ROW("s2a", 11, false, 9, 0, true, true, true); ROW("s2b", 71, true, 12, 0, false, false, false);
	/* s3: прийом FM на B (обрана B), сильний сигнал (червоні сегменти) */
	rssi = -60; unD[0] = 0; ROW("s3a", 11, false, 39, 0, false, false, false); ROW("s3b", 71, true, 12, 0, true, true, false);
	/* s4: B = VFO B (DMR) зі значками «D» і APRS «A»; A = 13 (16 широких символів, ключ AES) */
	rssi = -200; own = 0; unD[0] = 0; unD[1] = 2; unA = 12;
	ROW("s4a", 11, false, 13, 0, false, false, false); ROW("s4b", 71, true, 0, 2, true, false, false);
	/* s5: набір цифр на B (покажчик на B) */
	unD[1] = 0; unA = 0; ptrB = 1; directChannelNumber = 12; ROW("s5a", 11, false, 39, 0, false, false, false); ROW("s5b", 71, true, 12, 0, true, false, false); directChannelNumber = 0; ptrB = 0;
	/* s6: найгірший рядок 4: усі три значки (D «+», APRS «A+», замок) -- B = 13 (ключ), неактивна й активна (S-метр, сильний сигнал) */
	unD[1] = 9; unA = 3; ROW("s6b", 71, true, 13, 0, false, false, false); rssi = -60; ROW("s6c", 71, true, 13, 0, true, true, false); rssi = -200; unD[1] = 0; unA = 0;
	/* s7: виклик без азимуту -- відстань без стрілки; VFO B (FM) із «D»; канал, якого нема (38) -- лише номер */
	own = 1; known = 0; ROW("s7a", 11, false, 39, 0, true, true, true); known = 1; own = 0;
	settingsVFOChannel[1].chMode = RADIO_MODE_ANALOG; settingsVFOChannel[1].rxFreq = 14550000U; settingsVFOChannel[1].txFreq = 14610000U; unD[1] = 5;
	ROW("s8b", 71, true, 0, 2, false, false, false); unD[1] = 0;
	ROW("s9a", 11, false, 38, 0, true, false, false);
	/* s10: коротка назва (1 символ) */
	ROW("s10a", 11, false, 20, 0, true, false, false);
	/* s11: найгірші: канал 1024, DMR, CC15, PC16777215, потужність 750mW, ключ, усі значки; і виклик на ньому (ТГ виклику) */
	unD[0] = 9; ROW("w1a", 11, false, 1024, 0, true, false, false);
	own = 1; known = 1; rssi = -70; strcpy(item.talkgroup, "PC 16777215"); ROW("w1c", 11, false, 1024, 0, true, true, true); own = 0; rssi = -200; unD[0] = 0;
	/* s12: FM, найдовші тони, 4-цифровий номер, 750mW */
	ROW("w2a", 11, false, 1023, 0, true, false, false); ROW("w2b", 71, true, 1023, 0, false, false, false);
""" + H[_B:]


def analyse(D, line):
    """Примітиви картки -> елементи (за константами FIX9). Повертає (примітиви, елементи, обмежувальні рамки, нерозпізнані, перетини, поза полем, тексти)."""
    ps = F6.prims_of(line)
    el = {}; bad = []
    unx = [p["x"] for p in ps if p["k"] == "T" and p["t"] == "D" and p["font"] == 1 and p["y"] >= D["DW_ROW4_DY"]]
    unx = unx[0] if unx else None
    R4 = D["DW_ROW4_DY"]
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
        elif (p["k"] == "f" and p["w"] == D["DW_AP_W"] and p["h"] == D["DW_AP_H"]) or (p["k"] == "T" and p["inv"] == 1 and p["t"][:1] == "A" and p["font"] == 1 and p["y"] >= R4):
            name = "aprs"
        elif unx is not None and p["y"] >= R4 and unx <= p["x"] <= unx + D["DW_UN_W"] - 1 and p["k"] in "Trl":
            name = "D"
        elif p["k"] == "T" and p["font"] == 3 and p["y"] == D["DW_ROW1_DY"]:
            name = "row1"
        elif p["k"] == "T" and p["font"] == 3 and p["y"] == D["DW_ROW2_DY"]:
            name = "row2"
        elif p["k"] == "T" and p["y"] == D["DW_ROW3_DY"]:
            name = "row3L" if p["x"] == D["DW_IN_L"] else "row3R"
        elif p["k"] in "tl" and p["y"] >= D["DW_ARROW_DY"] and b[3] <= D["DW_ARROW_DY"] + D["DW_ARROW_CELL"] - 1:
            name = "arrow"
        elif p["k"] == "f" and p["x"] == D["DW_IN_L"] and p["w"] == D["DW_TAG_W"] and p["y"] == R4:
            name = "tag"
        elif p["k"] == "T" and p["inv"] == 1 and p["y"] == R4 and p["t"] in ("RX", "TX"):
            name = "tag"
        elif p["k"] == "T" and p["y"] == R4 and p["font"] == 1 and p["x"] == D["DW_METER_X"]:
            name = "f4"
        elif p["k"] == "f" and p["inv"] == 1 and p["y"] == R4 and p["x"] == D["DW_IN_L"] and p["w"] == D["DW_METER_END"] - D["DW_IN_L"]:
            name = "meterbg"   # очищення ділянки S-метра фоном (не елемент)
        elif p["y"] >= R4 and p["x"] >= D["DW_METER_X"] and b[2] < D["DW_METER_END"]:
            name = "meter"
        else:
            bad.append(p); continue
        el.setdefault(name, []).append(p)
    boxes = {k: F6.union([F6.box(p) for p in v]) for k, v in el.items() if k not in ("frame", "meterbg")}
    if "arrow" in boxes:
        x0, y0, x1, y1 = boxes["arrow"]; cx = (x0 + x1) // 2
        boxes["arrow"] = (cx - 5, D["DW_ARROW_DY"], cx + 4, D["DW_ARROW_DY"] + D["DW_ARROW_CELL"] - 1)
    names = sorted(boxes)
    ov = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if not F5.disjoint(boxes[a], boxes[b])]
    ymax = D["DW_CARD_H"] - 3
    out = [k for k, b in boxes.items() if k not in ("stripe",) and (b[0] < D["DW_IN_L"] or b[2] > D["DW_IN_R"] or b[1] < D["DW_ROW1_DY"] or b[3] > ymax)]
    txt = {k: [p["t"] for p in v if p["k"] == "T"] for k, v in el.items()}
    return ps, el, boxes, bad, ov, out, txt


def ph(ps):
    """Плейсхолдери назв -> справжня кирилиця (для моделі кадру й PNG)."""
    res = []
    for p in ps:
        q = dict(p)
        if q["k"] == "T" and q["font"] == 3 and q["t"] in PH:
            q["t"] = PH[q["t"]]
        res.append(q)
    return res


def render(D, o, ka, kb):
    """Модель кадрового буфера 160x128 (справжні шрифти прошивки): шапка + примітиви обох карток."""
    import screen_sim as sim
    d = sim.Display()
    d.theme_apply(sim.IT["FG_HEADER_TEXT"], sim.IT["BG_HEADER_TEXT"]); d.fill_rect(0, 0, 160, 10, True)
    d.print_core(1, 2, "DW", sim.FONT_1, sim.ALIGN_LEFT, False)
    d.print_core(160 - 30 - 3 - 18, 2, "87%", sim.FONT_1, sim.ALIGN_LEFT, False)
    d.print_core(160 - 30, 2, "12:34", sim.FONT_1, sim.ALIGN_LEFT, False)
    FONT = {1: sim.FONT_1, 3: sim.FONT_3}
    for key, y0 in ((ka, D["DW_CARD_A_Y"]), (kb, D["DW_CARD_B_Y"])):
        ps = ph(F6.prims_of(o.get(key)))
        for p in ps:
            d.theme_apply(sim.IT[p["fg"]], sim.IT["BG"])
            x, y = p["x"], p["y"] + y0
            if p["k"] == "T":
                d.print_core(x, y, p["t"], FONT.get(p["font"], sim.FONT_1), sim.ALIGN_LEFT, bool(p["inv"]))
            elif p["k"] == "f":
                d.fill_rect(x, y, p["w"], p["h"], bool(p["inv"]))
            elif p["k"] == "r":
                d.draw_rect(x, y, p["w"], p["h"], bool(p["inv"]))
            elif p["k"] == "l" and (p["y"] < D["DW_ARROW_DY"] or p["y"] >= D["DW_ROW4_DY"]):
                # лінії ▶ (x<=10, y<ROW2) і значка SMS «конверт» (рядок 4); лінії стрілки відстані (y 36..45) малює справжня геометрія нижче
                d.draw_line(x, y, x + p["w"] - 1, y + p["h"] - 1, True)
            elif p["k"] == "k":   # замок AES -- спрощений контур 10x9 (бітмапи uiDrawAesIconAt у моделі нема)
                d.theme_apply(sim.IT["FG_CHANNEL_NAME"], sim.IT["BG"])
                d.draw_rect(x, y + 3, 10, 6, True); d.draw_rect(x + 2, y, 6, 4, True)
        arr = [p for p in ps if p["k"] == "t"]
        if arr:
            import screen_views as sv
            cx = (min(p["x"] for p in arr) + max(p["x"] + p["w"] - 1 for p in arr)) // 2
            cy = (min(p["y"] for p in arr) + max(p["y"] + p["h"] - 1 for p in arr)) // 2 + y0
            tip, lft, rgt, notch = sv.chevron_geom(cx, cy, 4, 45)
            d.theme_apply(sim.IT["FG_CHANNEL_CONTACT_INFO"], sim.IT["BG"])
            d.fill_triangle(tip[0], tip[1], lft[0], lft[1], notch[0], notch[1], True)
            d.fill_triangle(tip[0], tip[1], rgt[0], rgt[1], notch[0], notch[1], True)
    return d


def ink_in(D, d, y0, x0, x1, y1, y2):
    import screen_sim as sim
    return [(x, y) for y in range(y0 + y1, y0 + y2 + 1) for x in range(x0, x1 + 1) if F8.px(d, x, y) != sim.IT["BG"]]


KEYS = ("s1a", "s1b", "p6a", "p6b", "s2a", "s2b", "s3a", "s3b", "s4a", "s4b", "s5a", "s5b", "s6b", "s6c", "s7a", "s8b", "s9a", "s10a", "w1a", "w1c", "w2a", "w2b")


def run_scenarios(t):
    fa = T.carve_fn(T.pp(FW, INCS, CF["DUALCH"], "application/source/functions/lc_distance.c") or "", "void lcDistArrowAfter(lcDistArrow_t *a, const lcDistSpan_t *tail, const lcDistSpan_t *above, int16_t screenW, uint16_t bearingDeg)")
    fns = [T.carve_fn(t, s) for s in ROW_SIGS]
    return fns, fa


def build_code(fns, fa):
    return H.replace("@@FNS@@", fa + "\n" + "\n".join(fns))


def test_contrast():
    """В: контраст кольору смуги/▶ (BG_MENU_ITEM_SELECTED) до фону картки (BG) у стокових темах (день/ніч) -- >= 7:1 (рівень AAA для тексту); кращі за контрастом наявні кольори теми
    є лише в «денній» темі й усі темні (чорний/темно-синій/темно-бордовий), як і сама рамка -- на білому тлі смуга від рамки відрізнялась би не кольором, а лише відтінком темного: заміни
    немає, смуга лишається BG_MENU_ITEM_SELECTED (у «нічній» -- бурштинова, чітко відмінна від сіро-блакитної рамки)."""
    import theme_edit as te
    import screen_sim as sim
    IT = sim.IT; inv = {v: k for k, v in IT.items()}

    def rgb565(v):
        return (((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)

    def lum(c):
        f = lambda v: (v / 255) / 12.92 if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
        r, g_, b = [f(x) for x in c]
        return 0.2126 * r + 0.7152 * g_ + 0.0722 * b

    def cr(a, b):
        la, lb = lum(a), lum(b)
        if la < lb:
            la, lb = lb, la
        return (la + 0.05) / (lb + 0.05)
    for th in ("day", "night"):
        C = te.stock_colors(th)
        bg = rgb565(C[IT["BG"]]); fr = rgb565(C[IT["FG_DECORATION"]]); sel = rgb565(C[IT["BG_MENU_ITEM_SELECTED"]])
        check(cr(sel, bg) >= 7.0, "В (%s): смуга до фону картки %.2f:1 (>= 7:1)" % (th, cr(sel, bg)))
        better = [(inv.get(i, i), rgb565(v)) for i, v in enumerate(C) if cr(rgb565(v), bg) > cr(sel, bg) and rgb565(v) != fr]
        dark = all(max(c) < 140 for _n, c in better) if th == "day" else True
        check(dark, "В (%s): кращі за контрастом наявні кольори теми -- лише темні (чорний/темно-синій), тобто такі ж, як рамка: %s" % (th, better))
        print("В (%s): смуга/фон %.2f:1, рамка/фон %.2f:1, смуга/рамка %.2f:1" % (th, cr(sel, bg), cr(fr, bg), cr(sel, fr)))


def snapshots(D, o, png_dir):
    """Т4: PNG -- модель кадрового буфера (справжні шрифти прошивки, стокова денна тема). Шапка -- як uiUtilityRenderHeaderDw; замок AES -- спрощений контур; стрілка відстані -- справжня геометрія."""
    import screen_sim as sim
    import theme_edit as te
    try:
        from PIL import Image
    except ImportError:
        print("ПРОПУСК: PIL нема -- PNG не згенеровано"); return
    colors = te.stock_colors("day")
    for n, ka, kb in (("1", "s1a", "s1b"), ("2", "s2a", "s2b"), ("3", "s3a", "s3b"), ("4", "s4a", "s4b"), ("5", "s5a", "s5b"), ("6", "p6a", "p6b")):
        d = render(D, o, ka, kb)
        img = Image.frombytes("RGB", (160, 128), sim.render_rgb(d, colors)).resize((480, 384), Image.NEAREST)
        path = os.path.join(png_dir, "R98FIX9-%s.png" % n)
        img.save(path)
        print("PNG: %s" % path)


INCS = None; CF = None


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    global INCS, CF
    INCS, cfgs = cmt.load_configs(FW)
    CF = dict(cfgs)
    F6.INCS, F6.CF = INCS, CF
    F8.INCS, F8.CF = INCS, CF
    png = None
    if "--png" in sys.argv:
        png = sys.argv[sys.argv.index("--png") + 1]
    src = T.rd(os.path.join(UI, "uiChannelMode.c"))
    t = T.pp(FW, INCS, CF["DUALCH"], "application/source/user_interface/uiChannelMode.c") or ""
    check(t != "", "препроцесування uiChannelMode.c (DUALCH)")
    test_cps()
    print("test_r98fix9: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


PROBE = r"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layout_probe as lp
import test_r54_ui as t54
app = t54.new_app(None)
app.apply_min_size()
app.geometry("1100x760")
lp.spin(app, 0.5)
labels = []
stack = [app]
while stack:
    w = stack.pop()
    try:
        labels.append(str(w.cget("text")))
    except Exception:
        pass
    stack.extend(w.winfo_children())
res = {"btn": bool(hasattr(app, "log_big_btn") or hasattr(app, "toggle_log_big") or any(t in ("Збільшити", "Зменшити") for t in labels))}
pl = app.pane_log
h0 = app.vpane.winfo_height() - pl.position()
pl.set(10 ** 5); lp.spin(app, 0.3)
res["log_min"] = app.vpane.winfo_height() - pl.position()
pl.set(0); lp.spin(app, 0.3)
res["top_min"] = pl.position()
pl.reset(); lp.spin(app, 0.3)
res["log_default"] = app.vpane.winfo_height() - pl.position()
print("RESULT " + json.dumps(res))
app.destroy()
"""


def cps_probe(mutations):
    """Копія tools/ у тимчасовому каталозі з мутаціями (список (файл, що, на що)); зонд у Tk під xvfb. None -- Tk недоступний."""
    py = shutil.which("python3.12") or shutil.which("python3")
    if not (shutil.which("xvfb-run") and py and subprocess.run([py, "-c", "import tkinter"], capture_output=True).returncode == 0):
        return None
    d = tempfile.mkdtemp(prefix="r98f9_")
    try:
        dst = os.path.join(d, "tools")
        shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns("__pycache__", "testdata", "*.png", "*.bin"))
        for rel, a, b in mutations:
            p = os.path.join(dst, rel); txt = open(p, encoding="utf-8").read()
            if a not in txt:
                return {"error": "мутація: шаблон не знайдено в %s: %s" % (rel, a[:50])}
            open(p, "w", encoding="utf-8").write(txt.replace(a, b, 1))
        open(os.path.join(dst, "probe_r98fix9.py"), "w", encoding="utf-8").write(PROBE)
        r = subprocess.run(["xvfb-run", "-a", py, "probe_r98fix9.py"], cwd=dst, capture_output=True, timeout=240, env=dict(os.environ, PYTHONPATH=""))
        m = re.search(r"RESULT (\{.*\})", r.stdout.decode("utf-8", "replace"))
        if not m:
            return {"error": (r.stderr.decode("utf-8", "replace") or r.stdout.decode("utf-8", "replace"))[-600:]}
        import json
        return json.loads(m.group(1))
    except subprocess.TimeoutExpired:
        return {"error": "таймаут зонда"}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_cps():
    """Г: кнопок журналу нема (код, документи, вікно); межа з «хватом»; мутанти -- у Tk."""
    top = os.path.dirname(FW)
    app_py = T.rd(os.path.join(HERE, "cps_ui", "app.py"))
    check(not re.search(r"log_big|toggle_log_big|\"Збільшити\"|\"Зменшити\"", app_py), "Г2: у cps_ui/app.py нема кнопки/методу «Збільшити»/«Зменшити» журналу (мертвого коду теж)")
    docs = [os.path.join(top, f) for f in ("USAGE.md", "README.md")] + [os.path.join(top, "docs", f) for f in os.listdir(os.path.join(top, "docs")) if f.endswith(".md")]
    bad = [os.path.basename(f) for f in docs if re.search(r"(Збільшити|Зменшити)[^.\n]{0,40}журнал|журнал[^.\n]{0,40}(Збільшити|Зменшити)",
                                                          "\n".join(l for l in T.rd(f).split("\n") if "нема" not in l))]   # рядки «кнопок нема» -- це і є потрібна згадка
    check(bad == [], "Г5: у USAGE/README/docs нема згадок кнопок «Збільшити»/«Зменшити» журналу: %s" % bad)
    usage = T.rd(os.path.join(top, "USAGE.md"))
    check(re.search(r"висоту журналу змінюйте, перетягнувши межу між деревом і журналом", usage) is not None, "Г5: USAGE.md каже, що висоту журналу міняють межею")
    gt = T.rd(os.path.join(HERE, "gui_theme.py"))
    m = re.search(r"^SASH\s*=\s*(\d+)", gt, re.M); gp = re.search(r"^SASH_GRIP\s*=\s*(\d+)", gt, re.M)
    check(m and gp and int(m.group(1)) >= 5 and int(gp.group(1)) >= 10 and "gripcount=SASH_GRIP" in gt and "gripcount=gt.SASH_GRIP" in app_py,
          "Г3: межа -- зона захоплення >= 5 px (%s), «хват» -- %s крапок у темі й у застосунку" % (m and m.group(1), gp and gp.group(1)))
    ok = cps_probe([])
    if ok is None:
        print("ПРОПУСК: Г4 -- Tk/xvfb-run нема (віджетні перевірки й мутанти CPS -- лише з tkinter + xvfb)"); return
    check("error" not in ok, "Г4: зонд CPS: %s" % ok.get("error"))
    if "error" in ok:
        return
    check(ok["btn"] is False and ok["log_min"] >= 40 and ok["top_min"] >= 160 and abs(ok["log_default"] - 100) <= 30,
          "Г1/Г4: вікно без кнопок; межа тримає мінімуми (журнал >= 40 px: %d, дерево >= 160 px: %d); типова висота журналу %d" % (ok["log_min"], ok["top_min"], ok["log_default"]))
    m1 = cps_probe([("cps_ui/app.py", '        ttk.Label(head, text="Журнал").pack(side="left")\n', '        ttk.Label(head, text="Журнал").pack(side="left")\n        self.log_big_btn = ttk.Button(head, text="Збільшити")\n        self.log_big_btn.pack(side="right")\n')])
    check(m1 and "error" not in m1 and m1["btn"] is True, "Г4 (мутант): кнопка повернулась -- ловиться (%s)" % m1)
    m2 = cps_probe([("cps_ui/layout.py", "hi = tot - self.min_second() - gt.SASH", "hi = tot + 10 ** 4")])
    check(m2 and "error" not in m2 and m2["log_min"] < 40, "Г4 (мутант): межа не тримає мінімум висоти журналу -- ловиться (%s)" % m2)


if __name__ == "__main__":
    sys.exit(main())
