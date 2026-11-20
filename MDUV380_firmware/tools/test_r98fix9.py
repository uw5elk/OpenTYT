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


def test_layout(t, src, png_dir):
    D = F5.consts(src)
    need = ["DW_CARD_W", "DW_CARD_H", "DW_CARD_A_Y", "DW_CARD_B_Y", "DW_SEL_X", "DW_SEL_W", "DW_IN_L", "DW_IN_R", "DW_ROW1_DY", "DW_ROW2_DY", "DW_ROW3_DY", "DW_ROW4_DY", "DW_LET_L", "DW_LET_W",
            "DW_LET_H", "DW_LET_GX", "DW_ROW1_TX", "DW_ROW1_MAX", "DW_ICON_DY", "DW_ICON_GAP", "DW_ICONS_W", "DW_LOCK_W", "DW_UN_W", "DW_AP_W", "DW_AP_H", "DW_ROW3_MAX", "DW_ARROW_DY", "DW_ARROW_CELL",
            "DW_METER_H", "DW_TAG_W", "DW_METER_SEG_W", "DW_METER_STEP", "DW_METER_SEGS", "DW_METER_X", "DW_METER_END", "DW_METER_HOT", "DW_TRI_X", "DW_TRI_W"]
    check(all(k in D for k in need), "А/Б: константи DW_* знайдено: нема %s" % [k for k in need if k not in D])
    if not all(k in D for k in need):
        return
    g = type("G", (), D)
    # А1: поле назви
    check(g.DW_ROW1_MAX == 16 and g.DW_ROW1_TX + g.DW_ROW1_MAX * 8 <= g.DW_IN_R + 1 and g.DW_ROW1_TX >= g.DW_LET_L + g.DW_LET_W + 1,
          "А1: назва -- 16 символів 8x16: x=%d..%d (<= %d), за рамкою літери (x<=%d)" % (g.DW_ROW1_TX, g.DW_ROW1_TX + 16 * 8 - 1, g.DW_IN_R, g.DW_LET_L + g.DW_LET_W - 1))
    # Б2/Б3: значки (усі три разом) праворуч від S-метра, мітки й частоти
    check(g.DW_ICONS_W == g.DW_UN_W + g.DW_ICON_GAP + g.DW_AP_W + g.DW_ICON_GAP + g.DW_LOCK_W and g.DW_ICON_DY == g.DW_ROW4_DY, "Б2: значки в рядку 4 (y+%d), усі три разом %d px" % (g.DW_ICON_DY, g.DW_ICONS_W))
    icons_l = g.DW_IN_R + 1 - g.DW_ICONS_W
    last = g.DW_METER_X + (g.DW_METER_SEGS - 1) * g.DW_METER_STEP + g.DW_METER_SEG_W - 1
    check(g.DW_METER_END == last + 1 and last < icons_l - 3 and g.DW_METER_SEGS == 11 and g.DW_METER_HOT == 2 and g.DW_IN_L + g.DW_TAG_W < g.DW_METER_X and g.DW_METER_SEG_W < g.DW_METER_STEP,
          "Б3: S-метр: мітка x=%d..%d, 11 сегментів %dx%d крок %d: x=%d..%d; значки (до %d px) -- з x=%d (зазор %d px); два останні червоні" %
          (g.DW_IN_L, g.DW_IN_L + g.DW_TAG_W - 1, g.DW_METER_SEG_W, g.DW_METER_H, g.DW_METER_STEP, g.DW_METER_X, last, g.DW_ICONS_W, icons_l, icons_l - last - 1))
    fns, fa = run_scenarios(t)
    check(all(fns) and fa is not None, "А/Б: функції картки знайдено (ROW_SIGS + lcDistArrowAfter)")
    if not (all(fns) and fa):
        return
    out = run_c(build_code(fns, fa))
    check(out is not None, "А/Б: хостова збірка карток")
    o = kv(out)
    R = {}
    for k in KEYS:
        R[k] = analyse(D, o.get(k))
        ps, el, boxes, bad, ov, outz, txt = R[k]
        check(o.get(k) is not None and not bad and not ov and not outz,
              "Т1 (%s): кожен примітив -- у своєму елементі, без перетинів, у полі вмісту: нерозпізнані %s, перетини %s, поза полем %s" % (k, [(p["k"], p["x"], p["y"], p["t"]) for p in bad], ov, outz))
    T1 = lambda k: R[k][6]
    # А1/А2: повна назва; номера в рядку 1 нема
    check(T1("s1a")["row1"] == ["R2 Robochy"] and T1("s1b")["row1"] == ["Domashni HotSpot"], "А1: рядок 1 -- повні назви «R2 Робочий» і «Домашній HotSpot»: %s / %s" % (T1("s1a")["row1"], T1("s1b")["row1"]))
    check(T1("p6a")["row1"] == ["R2 Robochy"] and T1("p6b")["row1"] == ["Domashni HotSpot"] and "stripe" in R["p6b"][1] and "stripe" not in R["p6a"][1],
          "А1 (p6): розкладка з фото власника, обрана B: повні назви, смуга лише на B")
    check(T1("s10a")["row1"] == ["X"] and T1("s4a")["row1"] == ["W" * 16] and T1("s6b")["row1"] == ["W" * 16] and T1("w1a")["row1"] == ["W" * 16],
          "А2: назви довжиною 1 і 16 («широкі» W) -- цілком")
    for k in KEYS:
        r1 = [p for p in R[k][1].get("row1", []) if p["k"] == "T"]
        if r1:
            check(r1[0]["x"] == g.DW_ROW1_TX and r1[0]["x"] + r1[0]["w"] - 1 <= g.DW_IN_R and len(r1[0]["t"]) <= 16, "А2 (%s): назва x=%d..%d -- між рамкою літери й правим краєм вмісту" % (k, r1[0]["x"], r1[0]["x"] + r1[0]["w"] - 1))
    # VFO: рядок 1 -- «VFOB частота» / «VFO B»
    check(T1("s4b")["row1"] == ["VFOB 430.12500"] and T1("s8b")["row1"] == ["VFO B"], "А1: картка VFO -- рядок 1: %s / %s" % (T1("s4b")["row1"], T1("s8b")["row1"]))
    # Б1: номер -- початок рядка 3, не обрізається; на VFO номера нема
    def row3(k):
        v = T1(k).get("row3L", [""]); return v[0] if v else ""
    num = {"s1a": "9", "s1b": "15", "s2a": "9", "s2b": "12", "s3a": "39", "s3b": "12", "s4a": "13", "s6b": "13", "w1a": "1024", "w1c": "1024", "w2a": "1023", "w2b": "1023", "s9a": "38", "s10a": "20"}
    for k, n in num.items():
        r = row3(k)
        check(r == n or r.startswith(n + " "), "Б1 (%s): рядок 3 починається з номера каналу «%s»: «%s»" % (k, n, r))
    check(row3("s4b") == "" or not re.match(r"^\d+ ", row3("s4b")), "Б1: на картці VFO номера каналу нема: «%s»" % row3("s4b"))
    check(row3("s9a") == "38" and T1("s9a").get("row1", [""]) == [""] or "row1" not in T1("s9a"), "Б1: каналу, якого нема, -- лише номер у рядку 3, рядок 1 порожній: %s / %s" % (row3("s9a"), T1("s9a").get("row1")))
    # типові стани -- нічого не обрізається; найгірші -- обрізається лише хвіст l3 (номер і правий блок цілі)
    check(row3("s1a") == "9 TS1 CC1 TG 9" or row3("s1a").startswith("9 TS1 CC1"), "Б1: типовий DMR -- «%s»" % row3("s1a"))
    check(row3("s1b").startswith("15 TS1 CC7 TG"), "Б1: типовий DMR (B) -- «%s»" % row3("s1b"))
    check(row3("s2b").startswith("12 ") and ("12.5k" in row3("s2b") or "25k" in row3("s2b")), "Б1: типовий FM -- «%s»" % row3("s2b"))
    for k in ("w1a", "w1c", "w2a", "w2b"):
        r3r = T1(k).get("row3R", [""])
        r3l = row3(k)
        check(r3r != [""] and r3l.startswith("102") and len(r3l) <= g.DW_ROW3_MAX, "Б1 (%s, найгірший): номер цілий, правий блок %s цілий; ліва частина «%s» (%d символів) обрізана лише з хвоста" % (k, r3r, r3l, len(r3l)))
    # Б2: значки -- рядок 4, праворуч, однакові зазори, порядок D, APRS, замок
    for k, want in (("s1a", ("D", "lock")), ("s4b", ("D", "aprs")), ("s6b", ("D", "aprs", "lock")), ("s6c", ("D", "aprs", "lock")), ("s2a", ("D", "lock")), ("s4a", ("lock",))):
        el = R[k][1]; bx = R[k][2]
        got = tuple(n for n in sorted((n for n in ("D", "aprs", "lock") if n in el), key=lambda n: bx[n][0]))
        check(got == want, "Б2 (%s): значки зліва направо %s, очікувано %s" % (k, got, want))
        xs = sorted((bx[n][0], bx[n][2], n) for n in got)
        gaps = [xs[i + 1][0] - xs[i][1] - 1 for i in range(len(xs) - 1)]
        check(xs[-1][1] == g.DW_IN_R and all(gp == g.DW_ICON_GAP or (gp == g.DW_ICON_GAP and True) for gp in gaps) and all(bx[n][1] >= g.DW_ROW4_DY and bx[n][3] <= g.DW_CARD_H - 3 for n in got),
              "Б2 (%s): значки вирівняні до правого краю x=%d, зазори %s px (однакові = %d), у рядку 4 (y+%d..%d)" % (k, g.DW_IN_R, gaps, g.DW_ICON_GAP, g.DW_ROW4_DY, g.DW_CARD_H - 3))
    # Б3: S-метр і значки в одному рядку -- без перекриття, 11 сегментів; сильний сигнал -- два червоні
    for k in ("s2a", "s3b", "s6c", "w1c"):
        el = R[k][1]
        segs = [p for p in el.get("meter", []) if p["k"] in "fr" and p["w"] == g.DW_METER_SEG_W]
        check(len(segs) == g.DW_METER_SEGS, "Б3 (%s): S-метр -- %d сегментів: %d" % (k, g.DW_METER_SEGS, len(segs)))
        check(max([p["x"] + p["w"] - 1 for p in segs] or [0]) < min([R[k][2][n][0] for n in ("D", "aprs", "lock") if n in R[k][2]] or [10 ** 6]), "Б3 (%s): S-метр лівіше за значки" % k)
        check("tag" in el and [p["t"] for p in el["tag"] if p["k"] == "T"] == ["RX"] and "f4" not in el, "Б3 (%s): активна картка -- «RX» + S-метр, частоти нема" % k)
    hot = [p for p in R["s3b"][1]["meter"] if p["k"] == "f" and p["w"] == g.DW_METER_SEG_W]
    check(len(hot) == g.DW_METER_SEGS and sum(1 for p in hot if p["fg"] == "FG_RSSI_BAR_S9P") == 2 and all(p["fg"] == "FG_RSSI_BAR_S9P" for p in hot[-2:]),
          "Б3: сильний сигнал -- залито %d сегментів, останні два (S9+10, S9+20) кольором «понад S9»" % len(hot))
    # Б4: неактивна -- рядок 4 не порожній: DMR-канал RX; FM-канал і VFO -- TX
    exp4 = {"s1a": ("RX", "439.12500"), "s1b": ("RX", "430.12500"), "s2b": ("TX", "146.00000"), "s3a": ("RX", "439.12500"), "s4a": ("RX", "145.50000"), "s4b": ("TX", "145.50000"),
            "s6b": ("RX", "145.50000"), "w2a": ("TX", "145.50000"), "s8b": ("TX", "146.10000"), "s10a": ("RX", "145.50000")}
    for k, (tg, fq) in exp4.items():
        el = R[k][1]
        tgs = [p["t"] for p in el.get("tag", []) if p["k"] == "T"]
        f4 = [p["t"] for p in el.get("f4", [])]
        check(tgs == [tg] and f4 == [fq], "Б4 (%s): рядок 4 неактивної -- мітка «%s» і частота «%s»: є %s / %s" % (k, tg, fq, tgs, f4))
    check("tag" not in R["s9a"][1] and "f4" not in R["s9a"][1], "Б4: каналу, якого нема, -- рядок 4 порожній (без вигаданих даних)")
    # Б5: праворуч у рядку 3 -- режим/потужність і відстань+стрілка на місці
    check(T1("s1a").get("row3R") == ["DMR 3W"] and T1("s2b").get("row3R") == ["FM 3W"], "Б5: праворуч у рядку 3 -- режим і потужність: %s / %s" % (T1("s1a").get("row3R"), T1("s2b").get("row3R")))
    check(T1("s2a").get("row3R") == ["1234km"] and "arrow" in R["s2a"][1] and "arrow" not in R["s7a"][1] and T1("s7a").get("row3R") == ["1234km"], "Б5: виклик -- відстань і стрілка (без азимуту -- лише відстань)")
    check(T1("s2a").get("row2") == ["UR5EQF Bogdan"] and T1("s5b").get("row2") == ["1234567890123456"], "Б5: рядок 2 не змінено (абонент / поле набору)")
    # Т1 кадр: піксельні перевірки (модель кадрового буфера)
    import screen_sim as sim
    pairs = (("1", "s1a", "s1b"), ("2", "s2a", "s2b"), ("3", "s3a", "s3b"), ("4", "s4a", "s4b"), ("5", "s5a", "s5b"), ("6", "s6b", "s6c"))
    for n, ka, kb in pairs:
        d = render(D, o, ka, kb)
        for key, y0 in ((ka, g.DW_CARD_A_Y), (kb, g.DW_CARD_B_Y)):
            # у рядку 4 неактивної картки є «чорнило» (не порожній прямокутник)
            ink = ink_in(D, d, y0, g.DW_IN_L, g.DW_IN_R, g.DW_ROW4_DY, g.DW_ROW4_DY + g.DW_METER_H - 1)
            check(len(ink) > 20, "Т1 (кадр %s, %s): рядок 4 не порожній (пікселів %d)" % (n, key, len(ink)))
            # область між S-метром/частотою і значками порожня (зазор >= 3 px)
            pads, frame = F8.letter_pads(D, d, y0)
            check(frame and pads is not None and pads[0] == pads[1] and pads[2] == pads[3], "Б (кадр %s, %s): літера в рамці симетрична %s" % (n, key, pads))
            # назва не заходить на рамку літери й правий край картки
            gap = ink_in(D, d, y0, g.DW_LET_L + g.DW_LET_W, g.DW_ROW1_TX - 1, g.DW_ROW1_DY, g.DW_ROW1_DY + 15)
            right = ink_in(D, d, y0, g.DW_IN_R + 1, g.DW_CARD_W - 1, 1, g.DW_CARD_H - 2)
            check(not gap and not right, "А2 (кадр %s, %s): між рамкою літери й назвою, а також праворуч від вмісту -- порожньо (зазор %d, правий %d)" % (n, key, len(gap), len(right)))
    # В: контраст смуги
    test_contrast()
    # Т2: мутанти
    rr = fns[-1]; mt = fns[3]
    def mutate(what, fn_idx, pat, new, check_fn):
        f2 = list(fns); base = f2[fn_idx]
        f2[fn_idx] = base.replace(pat, new, 1) if pat in base else base
        if f2[fn_idx] == base:
            check(False, "Т2 (мутант): %s -- шаблон не знайдено в препроцесованому тексті: %s" % (what, pat[:60])); return
        mo = kv(run_c(build_code(f2, fa)))
        res = {k: analyse(D, mo.get(k)) for k in KEYS if mo.get(k) is not None}
        check(bool(res) and check_fn(res, mo), "Т2 (мутант): %s -- ловиться" % what)
    mutate("номер у рядку 1 (назва знову коротшає)", len(fns) - 1, 'snprintf(l1, sizeof(l1), "%s", name);', 'snprintf(l1, sizeof(l1), "%u %s", (unsigned)ch, name);',
           lambda r, mo: r["s1a"][6].get("row1") != ["R2 Robochy"] and r["s1b"][6].get("row1") != ["Domashni HotSpot"])
    mutate("значок замка в рядку 1", len(fns) - 1, "uiDrawAesIconAt(lockX, (y + %d))" % g.DW_ICON_DY, "uiDrawAesIconAt(lockX, (y + 7))",
           lambda r, mo: any(p["k"] == "k" and p["y"] < g.DW_ROW2_DY for k in r for p in r[k][1].get("lock", [])))
    mutate("S-метр заходить на значки (крок 12)", 3, "(i - 1) * %d" % g.DW_METER_STEP, "(i - 1) * 12",
           lambda r, mo: any((r[k][3] or r[k][4] or r[k][5]) for k in ("s6c", "w1c", "s2a")))   # сегменти поза ділянкою S-метра / перетин зі значками / вихід за поле
    mutate("рядок 4 неактивної порожній", len(fns) - 1, "else if (f4Tag != ((void *)0))", "else if (0)",
           lambda r, mo: "tag" not in r["s1b"][1] and "f4" not in r["s1b"][1])
    mutate("номер не в рядку 3 (l3 без номера)", len(fns) - 1, 'nn = (size_t)snprintf(l3, sizeof(l3), "%u ", (unsigned)ch);', "nn = 0;",
           lambda r, mo: not (r["s1b"][6].get("row3L", [""])[0].startswith("15 ")))
    if png_dir:
        snapshots(D, o, png_dir)


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
    test_layout(t, src, png)
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
