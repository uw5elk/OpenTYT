#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX11 (хост): порядок значків, годинник у шапці DW, екран DW без літер A/B, мітка RX/TX, SMS у режимі DW.
  А  звичайний екран: СПРАВЖНІ msgEnvelopeWidth()/drawMsgEnvelope()/headerEnvelopeX() (gcc -E DUALCH + гарнес), піксельна модель зі шрифтом
     прошивки і справжньою бітмапою замка: лічильники 0, 1, 9, 10, 99, з замком і без -- порядок «D ✉ N, замок», зазор >= 2 px, однакові верх і низ,
     без перетинів, поза RSSI-смугою (y<14) і полем позивного (y>=24), разом з APRS «A»; мутанти «замок знову ліворуч», «різна висота».
  Б  шапка DW: годинник той самий, що в звичайній шапці (uiUtilityRenderHeaderCore), двокрапка мерехтить за парністю секунди, оновлення шапки --
     кожні 500 мс і в режимі DW; модель обох фаз.
  В  картки DW: СПРАВЖНІ dualRenderRow()/dualRowTag()/dualMeterRow()/... (гарнес R98-FIX6/FIX9) + справжні функції конверта; кадр 160x128:
     літер A/B нема, назва з x=13, мітка RX/TX по центру прямокутника (1 px з усіх боків), смуга рядка 4 -- 9 px для мітки, S-метра й усіх значків,
     порядок значків як на звичайному екрані, без перетинів; мутанти «літера повернулась», «мітка зміщена на 1 px», «значок вищий за інші»;
     PNG «до/після» (6 станів) з --png КАТАЛОГ.
  Г  SMS у DW: СПРАВЖНІ dualScanning()/dualDataHold() (uiChannelMode.c) і dmrSmsRxExchangeActive() (dmr_sms.c) у моделі часу 1 мс: повідомлення
     на A і на B (заголовок + N блоків + квитанція), довге, обірване, безперервні дані (межа), голос; мутанти «лише за звуком», «без межі»,
     «квитанція з іншої картки».
  R98-FIX12: мітка RX/TX -- звичайний текст без заливки, рядки 2..4 -- нова сітка за видимими межами (y+17, 34, 44): перевірки цього файлу переведено, піксельні проміжки й мітку
  перевіряє tools/test_r98fix12.py.
Запуск: python3 tools/test_r98fix11.py [--png КАТАЛОГ]"""
import os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
import test_r98fix5 as F5  # noqa
import test_r98fix6 as F6  # noqa
import test_r98fix8 as F8  # noqa
import test_r98fix9 as F9  # noqa
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
REL_CM = "application/source/user_interface/uiChannelMode.c"
REL_UU = "application/source/user_interface/uiUtilities.c"
REL_SMS = "application/source/functions/dmr_sms.c"
BASE = "cc52420"   # R98-FIX10 -- «до» для PNG
INCS = None; CF = None


def pp_text(rel, text=None):
    """gcc -E (DUALCH) файла з дерева або його зміненого тексту (тимчасовий файл; включення -- через -I)."""
    if text is None:
        return T.pp(FW, INCS, CF["DUALCH"], rel)
    d = tempfile.mkdtemp(prefix="r98f11_")
    try:
        p = os.path.join(d, os.path.basename(rel)); open(p, "w", encoding="utf-8").write(text)
        return T.pp(FW, INCS, CF["DUALCH"], p)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def lock_bitmap():
    src = T.rd(os.path.join(UI, "uiUtilities.c"))
    m = re.search(r"uiAesPadlockBitmap\[\]\s*=\s*\{(.*?)\};", src, re.S)
    return bytes(int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def ink(d, x0=0, y0=0, x1=159, y1=127):
    import screen_sim as sim
    return {(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1) if d.px[y * sim.W + x] != sim.IT["BG"]}


def bbox(pts):
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)) if pts else None


# =================================================================================================== А: звичайний екран
ENV_HARNESS = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
enum { FONT_SIZE_1 = 1 }; enum { TEXT_ALIGN_LEFT = 0 }; enum { UI_CHANNEL_MODE = 7, UI_VFO_MODE = 8, MENU_SATELLITE = 9 };
static int menu = UI_CHANNEL_MODE, aes = 0, first = 1;
int menuSystemGetCurrentMenuNumber(void) { return menu; }
int uiChannelHasAesEnabled(void) { return aes; }
static void out(char k, int x, int y, int w, int h, const char *t) { printf("%s%c:%d:%d:%d:%d:%s", first ? "" : ";", k, x, y, w, h, t ? t : ""); first = 0; }
int displayPrintCore(int x, int y, const char *t, int f, int al, bool inv) { (void)f; (void)al; (void)inv; out('T', x, y, (int)strlen(t) * 6, 8, t); return 0; }
void displayDrawRect(int x, int y, int w, int h, bool inv) { (void)inv; out('r', x, y, w, h, 0); }
void displayDrawLine(int a, int b, int c, int d, bool inv) { (void)inv; printf("%sl:%d:%d:%d:%d:", first ? "" : ";", a, b, c, d); first = 0; }
@@FNS@@
int main(void)
{
	static const unsigned cnt[] = { 1, 9, 10, 99, 120 };
	for (int m = 0; m < 3; m++)
		for (int a = 0; a < 2; a++)
			for (int i = 0; i < 5; i++)
			{
				menu = (m == 0) ? UI_CHANNEL_MODE : ((m == 1) ? UI_VFO_MODE : MENU_SATELLITE); aes = a; first = 1;
				printf("m%d_a%d_n%u=", m, a, cnt[i]); drawMsgEnvelope(headerEnvelopeX(cnt[i]), ENV_Y, 'D', cnt[i]); printf("\n");
			}
	first = 1; printf("aprs="); drawMsgEnvelope(2, ENV_Y, 'A', 99); printf("\n");
	return 0;
}
'''
ENV_SIGS = ["static int16_t msgEnvelopeWidth(unsigned count)", "static void drawMsgEnvelope(int16_t x, int16_t y, char letter, unsigned count)",
            "static int16_t headerEnvelopeX(unsigned count)"]


def env_run(tu):
    fns = [T.carve_fn(tu, s) for s in ENV_SIGS]
    if not all(fns):
        return None, "функції конверта не знайдено: %s" % [s for s, f in zip(ENV_SIGS, fns) if not f]
    m = re.search(r"drawMsgEnvelope\(headerEnvelopeX\(\(unsigned\)unread\), ([^,]+), 'D'", tu)
    ma = re.search(r"drawMsgEnvelope\(2, ([^,]+), 'A', aun\)", tu)
    lk = re.search(r"void uiDrawAesEnabledIcon\(void\)\s*\{\s*if \(uiChannelHasAesEnabled\(\)\)\s*\{\s*displayDrawXBitmap\(([^,]+), ([^,]+), uiAesPadlockBitmap", tu)
    if not (m and ma and lk):
        return None, "виклики конверта/замка в шапці не знайдено (D=%s A=%s замок=%s)" % (bool(m), bool(ma), bool(lk))
    ey, ay = int(eval(m.group(1))), int(eval(ma.group(1)))
    code = ENV_HARNESS.replace("@@FNS@@", "#define ENV_Y %d\n" % ey + "\n".join(fns))
    o = F8.run_c(code)
    if o is None:
        return None, "гарнес конверта не зібрався"
    res = dict(l.split("=", 1) for l in o.split("\n") if "=" in l)
    return {"res": res, "ey": ey, "ay": ay, "lock": (int(eval(lk.group(1))), int(eval(lk.group(2))))}, None


def env_prims(s):
    ps = []
    for it in s.split(";"):
        f = it.split(":", 5)
        if f[0] == "l":
            ps.append({"k": "l", "c": [int(v) for v in f[1:5]]})
        elif len(f) == 6:
            ps.append({"k": f[0], "x": int(f[1]), "y": int(f[2]), "w": int(f[3]), "h": int(f[4]), "t": f[5]})
    return ps


def env_draw(d, ps):
    import screen_sim as sim
    for p in ps:
        if p["k"] == "T":
            d.print_core(p["x"], p["y"], p["t"], sim.FONT_1, sim.ALIGN_LEFT, False)
        elif p["k"] == "r":
            d.draw_rect(p["x"], p["y"], p["w"], p["h"], True)
        elif p["k"] == "l":
            a, b, c, e = p["c"]; d.draw_line(a, b, c, e, True)


def test_normal(tu, src_uu, mutant=None):
    """А: повертає список зламаних властивостей (для мутантів) або перевіряє (mutant=None)."""
    import screen_sim as sim
    r, err = env_run(tu)
    if mutant is None:
        check(r is not None, "А: %s" % err)
    if r is None:
        return ["build"]
    bm = lock_bitmap(); lx, ly = r["lock"]
    broken = []
    def want(c, m):
        if not c:
            broken.append(m)
        if mutant is None:
            check(c, m)
    want((lx, ly) == (147, 14), "А3: замок -- на стоковому місці x=147..156, y=14 (як до R98-FIX10): %s" % ((lx, ly),))
    dl = sim.Display(); dl.draw_xbitmap(lx, ly, bm, 10, 9, True); L = ink(dl); Lb = bbox(L)
    for m in range(3):
        for a in range(2):
            for n in (1, 9, 10, 99, 120):
                ps = env_prims(r["res"]["m%d_a%d_n%d" % (m, a, n)])
                de = sim.Display(); env_draw(de, ps); E = ink(de); Eb = bbox(E)
                rect = [p for p in ps if p["k"] == "r"][0]
                txt = [p for p in ps if p["k"] == "T"]
                block_r = max(p["x"] + p["w"] - 1 for p in ps if p["k"] in "Tr")
                lockShown = (a == 1 and m < 2)
                tag = "%s, замок %s, N=%d" % (("канал", "VFO", "супутник")[m], "є" if a else "нема", n)
                # порядок: D < конверт < число
                want(txt[0]["t"] == "D" and txt[0]["x"] < rect["x"] < txt[1]["x"], "А1: порядок «D ✉ N» (%s)" % tag)
                want(rect["y"] == ly and rect["h"] == 9, "А2: корпус конверта на висоті замка y=%d..%d (%s): y=%d h=%d" % (ly, ly + 8, tag, rect["y"], rect["h"]))
                want(Eb[1] >= 14 and Eb[3] <= 23, "А1: конверт поза RSSI-смугою (y<14) і полем позивного (y>=24) (%s): %s" % (tag, Eb))
                tb = bbox(set().union(*[{q for q in E if txt[0]["x"] <= q[0] < txt[0]["x"] + 6}]))
                want(tb is not None and tb[1] == rect["y"] + 1 and tb[3] == rect["y"] + 7, "А2: літера по центру корпуса по вертикалі (%s): %s" % (tag, tb))
                if lockShown:
                    want(not (E & L), "А1: замок і конверт без спільних пікселів (%s)" % tag)
                    want(Lb[0] - block_r - 1 >= 2 and Eb[2] < Lb[0], "А1: конверт ліворуч від замка, зазор >= 2 px (%s): блок до x=%d, замок з x=%d" % (tag, block_r, Lb[0]))
                    want(block_r == lx - 2 - 1, "А1: правий край блока -- рівно за 2 px до замка (як у DW, DW_ICON_GAP) (%s): %d" % (tag, block_r))
                else:
                    want(block_r == 157, "А3: без замка -- конверт притиснутий до правого краю, як було (%s): %d" % (tag, block_r))
                # з APRS «A»
                pa = env_prims(r["res"]["aprs"]); da = sim.Display(); env_draw(da, pa); A = ink(da)
                want(not (A & E) and not (A & L) and bbox(A)[2] + 2 < Eb[0], "А1: з конвертом APRS «A» (x=2) без перетину (%s)" % tag)
    pa = env_prims(r["res"]["aprs"])
    want([p for p in pa if p["k"] == "r"][0]["y"] == ly, "А2: конверт APRS «A» на тій самій висоті, що «D ✉ N» і замок")
    # А3: лічильник 0 -- конверта нема, замок на місці (у коді шапки: unread > 0)
    hdr = tu[tu.find("int unread = dmrSmsUnreadCount();"):]
    hdr = hdr[:hdr.find("drawMsgEnvelope(2,")]
    want("if (unread > 0)" in hdr, "А3: лічильник 0 -- конверт не малюється (умова unread > 0)")
    return broken


def test_part_a(src_uu):
    tu = pp_text(REL_UU)
    check(tu is not None, "А: препроцесування uiUtilities.c (DUALCH)")
    if tu is None:
        return
    test_normal(tu, src_uu)
    # мутанти
    m1 = src_uu.replace("int16_t right = (lockShown ? (int16_t)(DISPLAY_SIZE_X - UI_AES_PADLOCK_W - 3 - UI_ICON_GAP) : (int16_t)(DISPLAY_SIZE_X - 2));",
                        "int16_t right = (int16_t)(DISPLAY_SIZE_X - 2); (void)lockShown;", 1)
    b1 = test_normal(pp_text(REL_UU, m1) or "", m1, mutant=True) if m1 != src_uu else ["незастосовано"]
    check(any("А1" in b for b in b1) and "незастосовано" not in b1, "А5 (мутант «замок знову ліворуч / конверт на старому місці»): ловиться: %s" % b1[:2])
    m2 = src_uu.replace("#define MSG_ENV_Y          (DISPLAY_Y_POS_BAR + 4)", "#define MSG_ENV_Y          (DISPLAY_Y_POS_BAR + 6)", 1)
    b2 = test_normal(pp_text(REL_UU, m2) or "", m2, mutant=True) if m2 != src_uu else ["незастосовано"]
    check(any("А2" in b for b in b2) and "незастосовано" not in b2, "А5 (мутант «різна висота»): ловиться: %s" % b2[:2])
    # збірки без режиму: стокові рядки на місці (у гілках #else)
    check("#else\n\t\t\tint16_t ex = (int16_t)(DISPLAY_SIZE_X - 2 - msgEnvelopeWidth((unsigned)unread));\n\t\t\tdrawMsgEnvelope(ex, DISPLAY_Y_POS_BAR + 6, 'D', (unsigned)unread);\n#endif" in src_uu,
          "А: без DUAL_CHANNEL_ENABLED -- стоковий виклик конверта «D» (x=158-w, y=16) без змін")
    check("#else\n\t\t\tdrawMsgEnvelope(2, DISPLAY_Y_POS_BAR + 6, 'A', aun);\n#endif" in src_uu, "А: без DUAL_CHANNEL_ENABLED -- конверт APRS як був")
    check("uiAesPadlockX" not in src_uu, "А3: зсув замка R98-FIX10 (uiAesPadlockX) прибрано -- замок знову на стоковому місці")
    blk = src_uu[src_uu.find("void uiDrawAesEnabledIcon(void)"):]
    blk = blk[:blk.find("\n}\n")]
    check("displayDrawXBitmap(DISPLAY_SIZE_X - UI_AES_PADLOCK_W - 3, 14, uiAesPadlockBitmap, UI_AES_PADLOCK_W, UI_AES_PADLOCK_H, true);" in blk and "#if" not in blk,
          "А3: uiDrawAesEnabledIcon() -- стоковий текст без умов (як до R98-FIX10)")


# =================================================================================================== Б: годинник
def test_part_b(src_uu):
    import screen_sim as sim
    core = src_uu[src_uu.find("static void uiUtilityRenderHeaderCore("):src_uu.find("void uiUtilityRenderHeader(bool isVFODualWatchScanning, bool isVFOSweepScanning, bool forceBatteryDisplay)\n{")]
    fmt = '"%02u%c%02u", timeAndDate.tm_hour, (((timeAndDate.tm_sec % 2) == 0) ? \':\' : \' \') ,timeAndDate.tm_min'
    check(src_uu.count(fmt) == 1 and fmt in core, "Б1: годинник шапки один (uiUtilityRenderHeaderCore): двокрапка -- у парну секунду, пробіл -- у непарну (стоково)")
    i = core.find(fmt); pre = core[:i]
    check(pre.rfind("if (displayTime)") > pre.rfind("dwOnly") or "dwOnly" not in pre[pre.rfind("if (displayTime)"):],
          "Б1: формат годинника не залежить від режиму DW (dwOnly його не чіпає)")
    dw = src_uu[src_uu.find("void uiUtilityRenderHeaderDw(bool forceBatteryDisplay)"):]
    dw = dw[:dw.find("\n}\n")]
    check("uiUtilityRenderHeaderCore(false, false, forceBatteryDisplay, &ov);" in dw, "Б1: шапка DW малюється тією самою uiUtilityRenderHeaderCore()")
    am = T.rd(os.path.join(APP, "source", "applicationMain.c"))
    check(re.search(r"if \(ticksTimerHasExpired\(&updateClockTimer\)\)\s*\{\s*headerRowIsDirty = true;\s*ticksTimerStart\(&updateClockTimer, 500U\);", am) is not None,
          "Б1: шапка з годинником оновлюється кожні 500 мс (updateClockTimer) -- у будь-якому режимі")
    check("if ((currentMenu == UI_CHANNEL_MODE) && uiChannelModeDualHeader((buttons & BUTTON_SK1) == BUTTON_SK1))" in am,
          "Б1: на екрані DW це оновлення малює шапку DW (uiChannelModeDualHeader -> uiUtilityRenderHeaderDw)")
    # модель обох фаз (той самий формат, вирівнювання праворуч, y=DISPLAY_Y_POS_HEADER=2)
    ph = []
    for sec in (2, 3):
        t = "%02u%c%02u" % (1, ":" if sec % 2 == 0 else " ", 3)
        d = sim.Display(); d.theme_apply(sim.IT["FG_HEADER_TEXT"], sim.IT["BG_HEADER_TEXT"]); d.fill_rect(0, 0, 160, 10, True)
        d.print_core(0, 2, t, sim.FONT_1, sim.ALIGN_RIGHT, False)
        col = {(x, y) for y in range(10) for x in range(142, 148) if d.px[y * sim.W + x] == sim.IT["FG_HEADER_TEXT"]}
        ph.append(len(col))
    check(ph[0] > 0 and ph[1] == 0, "Б2: модель шапки DW: парна секунда -- «01:03» (двокрапка %d px), непарна -- «01 03» (0 px; фаза фото)" % ph[0])


# =================================================================================================== В: картки DW
LINE_A = "add('l', x0, y0, (a > c ? a - c : c - a) + 1, (b > d ? b - d : d - b) + 1, 0, inv); }"
LINE_B = "add('l', x0, y0, (a > c ? a - c : c - a) + 1, (b > d ? b - d : d - b) + 1, (((a < c) != (b < d)) && (a != c) && (b != d)) ? \"/\" : 0, inv); }"


def harness_before():
    return F9.H.replace(LINE_A, LINE_B)


def harness_after(tu_uu):
    H = harness_before()
    H = H.replace("enum { FONT_SIZE_1 = 1, FONT_SIZE_3 = 3, FONT_SIZE_4 = 4 };", "enum { FONT_SIZE_1 = 1, FONT_SIZE_1_BOLD = 2, FONT_SIZE_3 = 3, FONT_SIZE_4 = 4 };")
    H = H.replace("int w = (f == FONT_SIZE_1) ? 6 : (f == FONT_SIZE_3 ? 8 : 16), h = (f == FONT_SIZE_1) ? 8 : (f == FONT_SIZE_3 ? 16 : 32);",
                  "int w = ((f == FONT_SIZE_1) || (f == FONT_SIZE_1_BOLD)) ? 6 : (f == FONT_SIZE_3 ? 8 : 16), h = ((f == FONT_SIZE_1) || (f == FONT_SIZE_1_BOLD)) ? 8 : (f == FONT_SIZE_3 ? 16 : 32);")
    # R98-FIX13 В: у картках значків SMS/APRS більше нема -- uiMsgEnvelopeWidth()/uiDrawMsgEnvelopeAt() з uiUtilities.c прибрано; заглушки потрібні лише МУТАНТАМ («значок знову на картці»)
    # і гарнесу коду бази (R98-FIX11/12), що їх викликав; корисний код карток їх не викликає (cards_check це перевіряє).
    stub = ("int16_t uiMsgEnvelopeWidth(unsigned count) { return (count > 9U) ? 34 : 28; }\n"
            "void uiDrawMsgEnvelopeAt(int16_t x, int16_t y, char letter, unsigned count) { char lt[2] = { letter, 0 }; char nb[4]; snprintf(nb, sizeof nb, \"%u\", count); "
            "displayPrintCore(x, y + 1, lt, FONT_SIZE_1, TEXT_ALIGN_LEFT, false); displayDrawRect(x + 7, y, 13, 9, true); displayDrawLine(x + 7, y, x + 13, y + 4, true); "
            "displayDrawLine(x + 19, y, x + 13, y + 4, true); displayPrintCore(x + 22, y + 1, nb, FONT_SIZE_1, TEXT_ALIGN_LEFT, false); }")
    return H, [stub]


def run_cards(tu_cm, H, extra):
    fns, fa = F9.run_scenarios(tu_cm)
    if not (all(fns) and fa):
        return None
    o = F8.run_c(H.replace("@@FNS@@", fa + "\n" + "\n".join(extra) + "\n" + "\n".join(fns)))
    if o is None:
        return None
    return dict(l.split("=", 1) for l in o.split("\n") if "=" in l)


FONT_OF = None


def render(o, ka, kb, D):
    """Кадр 160x128: шапка DW (як у uiUtilityRenderHeaderCore: «DW» x=1, заряд, час праворуч, y=2) + примітиви карток; замок -- справжня бітмапа."""
    import screen_sim as sim, screen_views as sv
    fonts = {1: sim.FONT_1, 2: sim.FONT_1_BOLD, 3: sim.FONT_3}
    bm = lock_bitmap()
    d = sim.Display()
    d.theme_apply(sim.IT["FG_HEADER_TEXT"], sim.IT["BG_HEADER_TEXT"]); d.fill_rect(0, 0, 160, 10, True)
    d.print_core(1, 2, "DW", sim.FONT_1, sim.ALIGN_LEFT, False)
    d.print_core(160 - 33 - 18, 2, "87%", sim.FONT_1, sim.ALIGN_LEFT, False)
    d.print_core(0, 2, "12:34", sim.FONT_1, sim.ALIGN_RIGHT, False)
    for key, y0 in ((ka, D["DW_CARD_A_Y"]), (kb, D["DW_CARD_B_Y"])):
        ps = F9.ph(F6.prims_of(o.get(key)))
        arr = [p for p in ps if p["k"] == "t"]
        for p in ps:
            d.theme_apply(sim.IT[p["fg"]], sim.IT["BG"])
            x, y = p["x"], p["y"] + y0
            if p["k"] == "T":
                d.print_core(x, y, p["t"], fonts.get(p["font"], sim.FONT_1), sim.ALIGN_LEFT, bool(p["inv"]))
            elif p["k"] == "f":
                d.fill_rect(x, y, p["w"], p["h"], bool(p["inv"]))
            elif p["k"] == "r":
                d.draw_rect(x, y, p["w"], p["h"], bool(p["inv"]))
            elif p["k"] == "l" and not (arr and p["y"] >= D["DW_ARROW_DY"] - 1 and p["y"] < D["DW_ROW4_DY"] and p["x"] > 100):
                # лінії ▶ і клапана конверта; «/» -- діагональ справа наліво (гарнес пише напрям у текст примітива)
                if p["t"] == "/":
                    d.draw_line(x + p["w"] - 1, y, x, y + p["h"] - 1, True)
                else:
                    d.draw_line(x, y, x + p["w"] - 1, y + p["h"] - 1, True)
            elif p["k"] == "k":
                d.theme_apply(sim.IT["FG_CHANNEL_NAME"], sim.IT["BG"]); d.draw_xbitmap(x, y, bm, 10, 9, True)
        if arr:
            cx = (min(p["x"] for p in arr) + max(p["x"] + p["w"] - 1 for p in arr)) // 2
            cy = (min(p["y"] for p in arr) + max(p["y"] + p["h"] - 1 for p in arr)) // 2 + y0
            tip, lft, rgt, notch = sv.chevron_geom(cx, cy, 4, 45)
            d.theme_apply(sim.IT["FG_CHANNEL_CONTACT_INFO"], sim.IT["BG"])
            d.fill_triangle(tip[0], tip[1], lft[0], lft[1], notch[0], notch[1], True)
            d.fill_triangle(tip[0], tip[1], rgt[0], rgt[1], notch[0], notch[1], True)
    return d


def analyse_after(D, line):
    """Елементи картки (константи R98-FIX13). (елементи, рамки, нерозпізнані, перетини, поза полем)."""
    ps = F6.prims_of(line)
    R4 = D["DW_ROW4_DY"]; el = {}; bad = []
    for p in ps:
        b = F6.box(p)
        if p["k"] == "r" and p["w"] >= 150:
            n = "frame"
        elif p["k"] == "f" and p["x"] == D["DW_SEL_X"] and p["w"] == D["DW_SEL_W"]:
            n = "stripe"
        elif p["k"] == "T" and p["font"] == 3 and p["y"] == D["DW_ROW1_DY"]:
            n = "row1"
        elif p["k"] == "T" and p["font"] == 3 and p["y"] == D["DW_ROW2_DY"]:
            n = "row2"
        elif p["k"] == "T" and p["y"] == D["DW_ROW3_DY"]:
            n = "row3L" if p["x"] == D["DW_IN_L"] else "row3R"
        elif p["k"] == "f" and p["inv"] == 1 and p["x"] == D["DW_IN_L"] and p["y"] == D["DW_ROW3_DY"] and p["h"] == 8:
            n = "row3L"         # R98-FIX15: заливка вікна стрічки -- клітинка лівої частини рядка 3 (перевіряє tools/test_r98fix15.py)
        elif p["k"] in "tl" and D["DW_ARROW_DY"] <= p["y"] and b[3] <= D["DW_ARROW_DY"] + D["DW_ARROW_CELL"] - 1:
            n = "arrow"
        elif p["k"] == "f" and p["inv"] == 1 and p["y"] == R4 and p["x"] == D["DW_IN_L"] and p["w"] == D["DW_METER_END"] - D["DW_IN_L"]:
            n = "meterbg"
        elif p["y"] >= R4 and p["k"] == "T" and p["inv"] == 0 and p["x"] == D["DW_IN_L"] and p["y"] == R4 + D["DW_ROW4_TXT_DY"] and p["t"] in ("RX", "TX"):
            n = "tag"           # R98-FIX12 А: мітка -- звичайний текст без заливки
        elif p["k"] == "T" and p["y"] == R4 + D["DW_ROW4_TXT_DY"] and p["x"] == D["DW_METER_X"]:
            n = "f4"
        elif p["k"] in "fr" and p["y"] >= R4 and D["DW_METER_X"] <= p["x"] and b[2] < D["DW_METER_END"]:
            n = "meter"
        elif p["k"] == "k":
            n = "lock"
        elif p["k"] == "T" and p["y"] == R4 + D["DW_ROW4_TXT_DY"] and p["x"] >= D["DW_MP_MIN_X"] - 12 and p["inv"] == 0:
            n = "mp"            # R98-FIX13 Е: «режим потужність» праворуч у рядку 4
        else:
            bad.append(p); continue
        el.setdefault(n, []).append(p)
    boxes = {k: F6.union([F6.box(p) for p in v]) for k, v in el.items() if k not in ("frame", "meterbg")}
    if "row1" in boxes:
        b1 = boxes["row1"]
        boxes["row1"] = (b1[0], b1[1], b1[2], b1[3] - 1)   # R98-FIX12 Б: нижній рядок клітинки рядка 1 (виносні латиниці) -- спільний із верхнім рядком клітинки рядка 2
    if "arrow" in boxes:
        x0, y0, x1, y1 = boxes["arrow"]; cx = (x0 + x1) // 2
        boxes["arrow"] = (cx - 5, D["DW_ARROW_DY"], cx + 4, D["DW_ARROW_DY"] + D["DW_ARROW_CELL"] - 1)
    names = sorted(boxes)
    ov = [(a, b) for i, a in enumerate(names) for b in names[i + 1:] if not F5.disjoint(boxes[a], boxes[b])]
    out = [k for k, b in boxes.items() if k != "stripe" and (b[0] < D["DW_IN_L"] or b[2] > D["DW_IN_R"] or b[1] < 1 or b[3] > D["DW_CARD_H"] - 2)]
    return el, boxes, bad, ov, out


KEYS = F9.KEYS


def icons_on_card(D, line):
    """R98-FIX13 В: значки SMS/APRS і ▶ на картці -- перелік знайденого (порожній -- гаразд)."""
    R4 = D["DW_ROW4_DY"]; found = []
    for p in F6.prims_of(line):
        if p["k"] == "r" and p["w"] == 13 and p["h"] == 9:
            found.append("корпус конверта")
        elif p["k"] == "f" and p["w"] == 13 and p["y"] >= R4 and p["inv"] == 0:
            found.append("бокс APRS")
        elif p["k"] == "T" and p["y"] >= R4 and p["font"] == 1 and p["t"][:1] in ("D", "A") and p["t"] not in ("RX", "TX") and len(p["t"]) <= 2 and p["x"] != D["DW_METER_X"] and not p["t"].isdigit():
            found.append("літера %s" % p["t"])
        elif p["k"] == "l" and D["DW_IN_L"] <= p["x"] <= D["DW_IN_L"] + 3 and p["y"] < D["DW_ROW2_DY"]:
            found.append("▶")
    return found


def cards_check(o, D, mutant=False):
    """Повертає список зламаних властивостей; без mutant -- ще й check(). Розкладка R98-FIX13."""
    import screen_sim as sim
    broken = []
    def want(c, m):
        if not c:
            broken.append(m)
        if not mutant:
            check(c, m)
    R4 = D["DW_ROW4_DY"]; H4 = D["DW_ROW4_H"]
    for k in KEYS:
        el, boxes, bad, ov, out = analyse_after(D, o.get(k))
        want(icons_on_card(D, o.get(k)) == [], "В (R98-FIX13): на картці нема конвертів SMS/APRS і стрілки ▶ (%s): %s" % (k, icons_on_card(D, o.get(k))))
        want(bad == [], "В: усі примітиви картки розпізнано (%s): %s" % (k, [(p["k"], p["x"], p["y"], p["w"], p["h"], p["t"]) for p in bad][:3]))
        want(ov == [], "В3: елементи картки не перетинаються (%s): %s" % (k, ov))
        want(out == [], "В3: усе в полі вмісту x=%d..%d, над нижньою рамкою (%s): %s" % (D["DW_IN_L"], D["DW_IN_R"], k, out))
        # А (R98-FIX13): рядки 1..4 починаються з одного x=DW_IN_L
        starts = {}
        for n in ("row1", "row2", "row3L", "tag"):
            if n in el:
                starts[n] = min(p["x"] for p in el[n])
        want(all(v == D["DW_IN_L"] for v in starts.values()), "А: рядки 1..4 починаються з x=%d (%s): %s" % (D["DW_IN_L"], k, starts))
        # рядок 4: усе 9 px заввишки, однаковий верх
        r4 = [p for n in ("tag", "meter", "lock") for p in el.get(n, []) if p["k"] in "frk"]
        want(all(p["y"] == R4 and p["h"] == H4 for p in r4), "В2/В3: мітка, сегменти S-метра й замок -- смуга y+%d..%d (%s)" % (R4, R4 + H4 - 1, k))
        tx = [p for n in ("tag", "f4", "mp") for p in el.get(n, []) if p["k"] == "T"]
        want(all(p["y"] == R4 + 1 for p in tx), "В2: текст рядка 4 (мітка, частота, режим+потужність) -- на одній базовій лінії y+%d (%s)" % (R4 + 1, k))
        # замок -- крайній праворуч (стокове місце), режим+потужність -- вирівняний до його лівого краю із зазором >= DW_ICON_GAP
        if "lock" in boxes:
            lb = boxes["lock"]
            want(lb[2] == D["DW_IN_R"] and lb[0] == D["DW_IN_R"] + 1 - D["DW_LOCK_W"], "Є: замок AES -- крайній праворуч x=%d..%d (%s): %s" % (D["DW_IN_R"] + 1 - D["DW_LOCK_W"], D["DW_IN_R"], k, lb))
        if "mp" in boxes:
            mb = boxes["mp"]
            edge = (boxes["lock"][0] - D["DW_ICON_GAP"] - 1) if "lock" in boxes else D["DW_IN_R"]
            want(mb[2] == edge, "Є: «режим потужність» -- вирівняний праворуч (до x=%d) (%s): %s" % (edge, k, mb))
            want(mb[0] >= D["DW_MP_MIN_X"], "Є: «режим потужність» не заходить на ліву частину рядка 4 (з x=%d) (%s): %s" % (D["DW_MP_MIN_X"], k, mb))
        if "lock" in boxes and "mp" in boxes:
            want(boxes["lock"][0] - boxes["mp"][2] - 1 >= D["DW_ICON_GAP"], "Є: між «режим потужність» і замком >= %d px (%s)" % (D["DW_ICON_GAP"], k))
    # піксельно (R98-FIX12 А): мітка RX/TX -- звичайний текст без заливки: у смузі мітки (x=DW_IN_L..+DW_TAG_W-1, рядки смуги) є лише піксели гліфів, «чорнило» -- рядки
    # смуги 1..7 (по центру смуги 9 px), колір -- як у решти дрібного тексту (FG_CHANNEL_NAME), літери «R»/«X»/«T» розпізнаються за бітмапою шрифту
    for k in ("s1a", "s1b", "s2a", "s3b", "s6c", "w2b"):
        d = render(o, k if k.endswith("a") else "s1a", k if k.endswith(("b", "c")) else "s1b", D)
        y0 = (D["DW_CARD_A_Y"] if k.endswith("a") else D["DW_CARD_B_Y"]) + R4
        x0 = D["DW_IN_L"]; x1 = x0 + D["DW_TAG_W"] - 1
        pts = {(x, y) for y in range(y0, y0 + H4) for x in range(x0, x1 + 1) if d.px[y * sim.W + x] != sim.IT["BG"]}
        tb = bbox(pts)
        if tb is None:
            continue        # R98-FIX13 Д: у FM/VFO без різниці TX/RX ліва частина порожня
        want(tb[1] == y0 + 1 and tb[3] == y0 + 7, "В2/А: мітка RX/TX -- «чорнило» в рядках смуги 1..7 (по центру смуги 9 px) (%s): %s" % (k, tb))
        want(all(d.px[y * sim.W + x] == sim.IT["FG_CHANNEL_NAME"] for (x, y) in pts), "А: мітка RX/TX -- кольором решти дрібного тексту (FG_CHANNEL_NAME), без заливки (%s)" % k)
        want(len(pts) < 40, "А: у смузі мітки лише піксели літер, не суцільна заливка (%s): %d px" % (k, len(pts)))
    return broken


def test_part_v(src_cm, src_uu, png_dir):
    D = F5.consts(src_cm)
    need = ["DW_ROW1_DY", "DW_ROW2_DY", "DW_ROW3_DY", "DW_ROW4_DY", "DW_ROW4_H", "DW_ROW1_TX", "DW_TAG_W", "DW_METER_X", "DW_METER_END", "DW_LOCK_W", "DW_ICON_GAP", "DW_MP_CHARS", "DW_L4_END", "DW_MP_MIN_X"]
    check(all(k in D for k in need), "В: константи R98-FIX13 знайдено: нема %s" % [k for k in need if k not in D])
    if not all(k in D for k in need):
        return
    check(not any(k in D for k in ("DW_LET_L", "DW_LET_W", "DW_LET_H", "DW_LET_GX", "DW_TRI_X", "DW_TRI_W", "DW_TRI_CY", "DW_AP_W", "DW_AP_H", "DW_UN_W_MAX", "DW_ICONS_W")),
          "В1 (R98-FIX13 А/В): констант рамки літери A/B, стрілки ▶ і значків SMS/APRS у картках нема")
    check(D["DW_ROW1_TX"] == D["DW_IN_L"] == 7 and D["DW_ROW1_TX"] + 16 * 8 <= D["DW_IN_R"] + 1,
          "А1: назва з x=%d -- там само, де рядки 2..4; 16 символів 8x16 -- x=%d..%d" % (D["DW_ROW1_TX"], D["DW_ROW1_TX"], D["DW_ROW1_TX"] + 127))
    check(D["DW_ROW1_TX"] + 16 * 8 + 3 + 4 * 6 > D["DW_IN_R"] + 1, "В1: номер (4 цифри 6x8 + зазор) поруч із 16 символами назви в рядок 1 не вміщується -- лишається в рядку 3")
    check(D["DW_ROW1_DY"] + 15 <= D["DW_ROW2_DY"] and D["DW_ROW2_DY"] + 15 <= D["DW_ROW3_DY"] and D["DW_ROW3_DY"] + 8 < D["DW_ROW4_DY"] and D["DW_ROW4_DY"] + D["DW_ROW4_H"] + 3 <= D["DW_CARD_H"] - 1,
          "В3: сітка рядків 1/2/3/4: клітинки 8x16 рядків 1 і 2 -- спільний піксельний рядок (проміжки за видимими межами -- test_r98fix12), смуга рядка 4 + 3 px до нижньої рамки")
    check(D["DW_METER_END"] + D["DW_ICON_GAP"] <= D["DW_IN_R"] + 1 - D["DW_LOCK_W"] - D["DW_ICON_GAP"] - D["DW_MP_CHARS"] * 6,
          "В3: S-метр (до x=%d) не заходить на блок «режим потужність» (з x=%d) і замок" % (D["DW_METER_END"] - 1, D["DW_IN_R"] + 1 - D["DW_LOCK_W"] - D["DW_ICON_GAP"] - D["DW_MP_CHARS"] * 6))
    tu_cm = pp_text(REL_CM); tu_uu = pp_text(REL_UU)
    check(bool(tu_cm) and bool(tu_uu), "В: препроцесування uiChannelMode.c / uiUtilities.c")
    if not (tu_cm and tu_uu):
        return
    H, env = harness_after(tu_uu)
    o = run_cards(tu_cm, H, env)
    check(o is not None, "В: хостова збірка карток")
    if o is None:
        return
    cards_check(o, D)
    # мутанти
    def mut(name, a, b, part):
        s2 = src_cm.replace(a, b, 1)
        if s2 == src_cm:
            check(False, "В4 (мутант %s): не застосувався" % name); return
        o2 = run_cards(pp_text(REL_CM, s2) or "", H, env)
        br = cards_check(o2, F5.consts(s2), mutant=True) if o2 else ["build"]
        check(any(part in x for x in br), "В4 (мутант %s): ловиться: %s" % (name, br[:2]))
    mut("літера A/B повернулась", "	// R98-FIX11 В1: літери A/B у рамці більше нема -- верхня картка A, нижня B; обрану показує смуга\n	displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);\n",
        "	displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);\n	displayPrintCore(9, (y + DW_ROW1_DY), (isB ? \"B\" : \"A\"), FONT_SIZE_3, TEXT_ALIGN_LEFT, false);\n", "А:")
    mut("мітка RX зміщена на 1 px", "displayPrintCore(DW_IN_L, (my + DW_ROW4_TXT_DY), tag, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);",
        "displayPrintCore(DW_IN_L, my, tag, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);", "В2")
    mut("замок нижче за решту рядка 4", "#define DW_ICON_DY       DW_ROW4_DY ", "#define DW_ICON_DY       (DW_ROW4_DY + 1) ", "В2/В3")
    # PNG «до/після»
    if png_dir:
        snapshots(o, D, png_dir)


STATES = [("1", "s1a", "s1b", "чергування: A «R2 Робочий» (ключ, SMS), B «Домашній HotSpot»"),
          ("2", "s2a", "s2b", "прийом DMR на A: абонент, відстань, стрілка, S-метр"),
          ("3", "s3a", "s3b", "прийом FM на B, сильний сигнал"),
          ("4", "s4a", "s4b", "B = VFO B зі значками SMS і APRS; A -- 16 широких символів, ключ"),
          ("5", "s5a", "s5b", "набір цифр на B"),
          ("6", "p6a", "p6b", "неактивні картки, обрана B: «R2 Робочий» і «Домашній HotSpot»")]


def before_frames():
    """«До» -- той самий гарнес і сценарії на коді бази (R98-FIX10)."""
    if subprocess.run(["git", "-C", FW, "cat-file", "-e", BASE + "^{commit}"], capture_output=True).returncode != 0:
        print("ІНФО: коміт-база %s недоступний -- PNG «до» не малюється (ілюстрація, не перевірка)" % BASE); return None, None
    old = subprocess.run(["git", "-C", FW, "show", BASE + ":MDUV380_firmware/" + REL_CM], capture_output=True)
    if old.returncode != 0:
        return None, None
    s = old.stdout.decode("utf-8")
    t = pp_text(REL_CM, s)
    if not t:
        return None, None
    o = run_cards(t, harness_before(), [])
    return o, F5.consts(s)


def snapshots(o, D, png_dir):
    try:
        from PIL import Image
    except Exception:
        print("ПРОПУСК: PNG -- нема Pillow"); return
    import screen_sim as sim, theme_edit as te
    os.makedirs(png_dir, exist_ok=True)
    ob, Db = before_frames()
    cols = te.stock_colors("day")
    def img(d):
        return Image.frombytes("RGB", (sim.W, sim.H), sim.render_rgb(d, cols))
    for num, ka, kb, title in STATES:
        after = img(render(o, ka, kb, D))
        if ob is not None:
            before = img(render(ob, ka, kb, Db))
            canvas = Image.new("RGB", (sim.W * 2 + 8, sim.H), (128, 128, 128))
            canvas.paste(before, (0, 0)); canvas.paste(after, (sim.W + 8, 0))
        else:
            canvas = after
        canvas = canvas.resize((canvas.width * 3, canvas.height * 3), Image.NEAREST)
        p = os.path.join(png_dir, "R98FIX11-%s.png" % num)
        canvas.save(p)
        print("PNG: %s -- %s (ліворуч -- до, праворуч -- після)" % (p, title))


# =================================================================================================== Г: SMS у DW
ENG = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
enum { SCAN_STATE_SCANNING = 0, SCAN_STATE_SHORT_PAUSED, SCAN_STATE_PAUSED };
enum { RADIO_MODE_NONE, RADIO_MODE_ANALOG, RADIO_MODE_DIGITAL };
enum { DMR_STATE_IDLE = 0 }; enum { DMR_MODE_AUTO = 0, DMR_MODE_DMO, DMR_MODE_RMO }; enum { RADIO_DEVICE_PRIMARY = 0 };
enum { AUDIO_AMP_CHANNEL_RF = (1 << 1) }; enum { QSO_DISPLAY_IDLE = 0, QSO_DISPLAY_DEFAULT_SCREEN = 1 };
struct { struct { bool active; int scanType; int state; struct { uint32_t start; uint32_t timeout; } timer; int dwellTime; int stepTimeMilliseconds; } Scan; int displayQSOState; } uiDataGlobal;
struct { int dmrCcTsFilter; int scanDelay; } nonVolatileSettings;
struct { int trxDMRModeRx; } dev, *currentRadioDevice = &dev;
int slotState = 0, dmrMonitorCapturedTS = -1;
static uint32_t now = 1000;
static int mode = RADIO_MODE_DIGITAL, carrier = 0, rf = 0, onB = 0, tunes = 0, txBusy = 0;
static volatile uint32_t s_lastRxBurstMs; static volatile uint8_t s_rxReady; static uint8_t s_ackPending;
uint32_t ticksGetMillis(void) { return now; }
int dmrDataTxBusy(void) { return txBusy; }
int trxGetMode(void) { return mode; }
int trxGetDMRTimeSlot(void) { return 0; }
bool HRC6000HasGotSync(void) { return false; }
bool trxCarrierDetected(int d) { (void)d; return carrier; }
uint32_t audioAmpGetStatus(void) { return rf ? 0xFFFFu : 0u; }
void hidesChannelDetails(void) {}
bool dcIsOnB(void) { return onB; }
static void dualTune(bool toB) { onB = toB; tunes++; }
static void dualSetDwell(void) { uiDataGlobal.Scan.dwellTime = 60; uiDataGlobal.Scan.timer.timeout = 60; }
@@FNS@@
/* ---- модель ефіру: відправник на картці card шле PRE CSBK-преамбул і nb burst-ів даних (заголовок + блоки) по 60 мс (несуча весь час); якщо всі
 * burst-и даних прийнято -- PDU, квитанція. Преамбули потрібні саме для того, щоб приймач (скануючий) встиг стати на канал: їх губити можна. */
#define PRE 6
static int card, nb, ackMs, txOnB, txAll, rxSeen, lost, ackDone, ackWrong, cont;
static uint32_t t0, tEnd, tAckQ, tAckTx;
static void reset(int c, int n, int ack, int filterTs)
{
	memset(&uiDataGlobal, 0, sizeof uiDataGlobal); uiDataGlobal.Scan.active = true; uiDataGlobal.Scan.state = SCAN_STATE_SCANNING; uiDataGlobal.Scan.stepTimeMilliseconds = 30;
	nonVolatileSettings.scanDelay = 2; nonVolatileSettings.dmrCcTsFilter = filterTs ? 0xFF : 0; dev.trxDMRModeRx = DMR_MODE_DMO;
	dualSetDwell(); onB = 0; tunes = 0; carrier = rf = 0; txBusy = 0; s_lastRxBurstMs = 0; s_rxReady = 0; s_ackPending = 0;
	card = c; nb = n; ackMs = ack; rxSeen = 0; lost = 0; ackDone = 0; ackWrong = 0; cont = 0; t0 = now + 37; tEnd = t0 + (uint32_t)(n + PRE) * 60U; tAckQ = 0; tAckTx = 0;
}
static void step(void)
{
	now++;
	int on = (onB == card);
	int sending = cont ? (now >= t0) : ((now >= t0) && (now < tEnd));
	carrier = (sending && on);
	if (sending && (((now - t0) % 60U) == 0U))
	{
		int data = cont || (((now - t0) / 60U) >= PRE);
		if (on) { s_lastRxBurstMs = now; if (data) rxSeen++; } else if (data) { lost++; }
	}
	if (!cont && (now == tEnd + 1))
	{
		if (lost == 0 && rxSeen == nb) { s_rxReady = 1; }
	}
	if (s_rxReady && (now == tEnd + 3)) { s_rxReady = 0; if (ackMs > 0) { s_ackPending = 1; tAckQ = now; } else { ackDone = 1; } }
	if (s_ackPending && ((now - s_lastRxBurstMs) >= 65U)) { s_ackPending = 0; txBusy = 1; tAckTx = now; txOnB = onB; }
	if (txBusy)
	{
		if (onB != txOnB) { ackWrong = 1; }
		if ((now - tAckTx) >= (uint32_t)ackMs) { txBusy = 0; ackDone = (ackWrong == 0) && (txOnB == card); }
	}
	if (uiDataGlobal.Scan.active) { dualScanning(); }
}
static uint32_t firstTuneAfter(uint32_t t, int limit) { int k = tunes; for (int i = 0; i < limit; i++) { step(); if (tunes != k && now >= t) return now - t; } return 999999; }
int main(void)
{
	/* 1/2: повідомлення 20 burst-ів (1,2 с) з квитанцією 120 мс на A і на B, фільтр TS увімкнено (найкоротша пауза 0,5 с) */
	for (int c = 0; c < 2; c++)
	{
		reset(c, 20, 120, 1);
		while (now < tEnd + 2000) step();
		printf("sms%d=%d,%d,%d,%d\n", c, rxSeen, lost, ackDone, ackWrong);
	}
	/* 3: довге -- 45 burst-ів (2,7 с), квитанція 120 мс */
	reset(1, 45, 120, 0); while (now < tEnd + 2000) step(); printf("long=%d,%d,%d\n", rxSeen, lost, ackDone);
	/* 4: квитанція довша за вікно тиші (6 преамбул діагностичної збірки + заголовок = 420 мс): іде з тієї самої картки */
	reset(0, 12, 420, 1); while (now < tEnd + 3000) step(); printf("ack=%d,%d,%d\n", lost, ackDone, ackWrong);
	/* 5: обірване -- відправник замовк після 8 burst-ів з 30: чергування відновлюється (перше перемикання після тиші) */
	reset(0, 30, 120, 1); while (now < t0 + (PRE + 8) * 60) step(); tEnd = now; uint32_t q = now; uint32_t d5 = firstTuneAfter(q, 5000); printf("abort=%u\n", (unsigned)d5);
	/* 6: безперервні дані на A -- не довше межі (від першого burst-а до першого перемикання) */
	reset(0, 1, 0, 1); cont = 1; uint32_t d6 = firstTuneAfter(t0, 20000); printf("cont=%u\n", (unsigned)d6);
	/* 7: голос 2 с (звук), без даних: утримання як було -- scanDelay*1000 після звуку */
	reset(0, 1, 0, 1); nb = 0; t0 = now + 37; tEnd = t0 + 2000;
	while (now < t0 + 5) { now++; carrier = (onB == 0) && (now >= t0); if (uiDataGlobal.Scan.active) dualScanning(); }
	rf = 1; while (now < tEnd) { now++; carrier = 1; if (uiDataGlobal.Scan.active) dualScanning(); }
	rf = 0; carrier = 0; { int k = tunes; uint32_t ts = now; while (tunes == k && (now - ts) < 9000) { now++; dualScanning(); } printf("voice=%u,%d\n", (unsigned)(now - ts), onB); }
	return 0;
}
'''


def run_engine(tu_cm, tu_sms):
    fns = [T.carve_fn(tu_sms, "int dmrSmsRxExchangeActive(uint32_t idleMs)"), T.carve_fn(tu_cm, "static void dualDataHold(void)"), T.carve_fn(tu_cm, "static void dualScanning(void)")]
    if not all(fns):
        return None, fns
    o = F8.run_c(ENG.replace("@@FNS@@", "\n".join(fns)))
    return (dict(l.split("=", 1) for l in o.split("\n") if "=" in l) if o else None), fns


def eng_eval(o, cap, idle):
    """(властивість, виконано) для результатів моделі."""
    r = {}
    for c in ("0", "1"):
        v = [int(x) for x in o["sms" + c].split(",")]
        r["sms" + c] = (v[0] == 20 and v[1] == 0 and v[2] == 1 and v[3] == 0)
    v = [int(x) for x in o["long"].split(",")]; r["long"] = (v[0] == 45 and v[1] == 0 and v[2] == 1)
    v = [int(x) for x in o["ack"].split(",")]; r["ack"] = (v[0] == 0 and v[1] == 1 and v[2] == 0)
    r["abort"] = (int(o["abort"]) <= idle + 5)
    d6 = int(o["cont"]); r["cont"] = (d6 <= cap + idle + 600)
    v = o["voice"].split(","); r["voice"] = (1990 <= int(v[0]) <= 2010)
    return r


def test_part_g(src_cm, src_sms):
    tu_cm = pp_text(REL_CM); tu_sms = pp_text(REL_SMS)
    check(bool(tu_cm) and bool(tu_sms), "Г: препроцесування uiChannelMode.c / dmr_sms.c (DUALCH)")
    if not (tu_cm and tu_sms):
        return
    hdr = T.rd(os.path.join(APP, "include", "functions", "dmr_sms.h"))
    m = re.search(r"#define DMR_SMS_RX_EXCHANGE_MAX_MS\s+(.+)", hdr)
    cap = int(eval(m.group(1))) if m else 0
    check(cap == ((16 + 1 + 1 + 32 + 1) * 60) + 2500, "Г1: межа утримання -- найдовший обмін за кодом: 51 burst x 60 мс + SMS_ACK_MAX_WAIT_MS 2500 = %d мс" % cap)
    idle = 360
    check("#define DW_DATA_IDLE_MS   (TIMESLOT_DURATION * 12)" in src_cm, "Г1: вікно тиші -- суперкадр DMR (TIMESLOT_DURATION * 12 = 360 мс)")
    o, fns = run_engine(tu_cm, tu_sms)
    check(o is not None, "Г2: хостова збірка рушія (dualScanning + dualDataHold + dmrSmsRxExchangeActive)")
    if o is None:
        return
    r = eng_eval(o, cap, idle)
    check(r["sms0"], "Г2: SMS на A (20 burst-ів, фільтр TS, пауза 0,5 с): усі burst-и прийнято, квитанція з A: %s" % o["sms0"])
    check(r["sms1"], "Г2: SMS на B: усі burst-и прийнято, квитанція з B: %s" % o["sms1"])
    check(r["long"], "Г2: довге повідомлення (45 burst-ів, 2,7 с) не рветься чергуванням: %s" % o["long"])
    check(r["ack"], "Г2: квитанція 420 мс (довша за вікно тиші) -- уся з картки прийому: %s" % o["ack"])
    check(r["abort"], "Г2: обірваний обмін -- чергування відновлюється за <= %d мс тиші: %s" % (idle + 5, o["abort"]))
    check(r["cont"], "Г2: безперервні дані -- перемикання не пізніше межі %d мс (+вікно): %s мс" % (cap, o["cont"]))
    check(r["voice"], "Г2: голос -- утримання як було (scanDelay*1000 = 2000 мс після звуку), рація на картці: %s" % o["voice"])
    # мутанти
    def mut(name, i, a, b, prop):
        f2 = list(fns)
        if a not in f2[i]:
            check(False, "Г2 (мутант %s): не застосувався" % name); return
        f2[i] = f2[i].replace(a, b, 1)
        oo = F8.run_c(ENG.replace("@@FNS@@", "\n".join(f2)))
        rr = eng_eval(dict(l.split("=", 1) for l in oo.split("\n") if "=" in l), cap, idle) if oo else {}
        check(rr != {} and rr.get(prop) is False, "Г2 (мутант %s): ловиться (%s)" % (name, prop))
    mut("утримання лише за звуком", 2, "dualDataHold();", ";", "sms0")
    capx = "< (((16 + 1 + 1 + (384 / 12) + 1) * 60) + 2500)"
    if capx in fns[1]:
        mut("утримання без межі (залипає)", 1, capx, "< 0xFFFFFFFFu", "cont")
    else:
        check(False, "Г2 (мутант без межі): вираз межі в dualDataHold() не знайдено")
    mut("квитанція йде з іншої картки", 0, "|| (s_ackPending != 0) || (dmrDataTxBusy() != 0)", "", "ack")
    # без нових змінних
    blk = src_cm[src_cm.find("static void dualDataHold(void)"):]
    blk = blk[:blk.find("\n}\n")]
    check("static " not in blk[blk.find("{"):], "Г3: dualDataHold() -- без статичних змінних (початок відліку -- у Scan.timer.start)")
    sms = src_sms[src_sms.find("int dmrSmsRxExchangeActive(uint32_t idleMs)"):]
    sms = sms[:sms.find("\n}\n")]
    check("static " not in sms and "s_lastRxBurstMs" in sms and "s_rxReady" in sms and "s_ackPending" in sms and "dmrDataTxBusy()" in sms,
          "Г1/Г3: dmrSmsRxExchangeActive() -- лише наявні мітка/прапорці (burst, PDU, квитанція в черзі, наша передача)")
    um = T.rd(os.path.join(UI, "uiVFOMode.c")) + T.rd(os.path.join(UI, "uiChannelMode.c"))
    check(len(re.findall(r"ticksTimerStart\(&uiDataGlobal\.Scan\.timer", um)) == len(re.findall(r"ticksTimerStart\(&uiDataGlobal\.Scan\.timer", T.rd(os.path.join(UI, "uiVFOMode.c")))) and
          "ticksTimerHasExpired(&uiDataGlobal.Scan.timer)" not in T.rd(os.path.join(UI, "uiChannelMode.c")),
          "Г3: Scan.timer.start у режимі каналу більше ніхто не використовує (лише VFO-розгортка) -- можна тримати початок відліку")


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    global INCS, CF
    INCS, cfgs = cmt.load_configs(FW)
    CF = dict(cfgs)
    F6.INCS, F6.CF = INCS, CF
    F8.INCS, F8.CF = INCS, CF
    F9.INCS, F9.CF = INCS, CF
    png = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else None
    src_cm = T.rd(os.path.join(UI, "uiChannelMode.c"))
    src_uu = T.rd(os.path.join(UI, "uiUtilities.c"))
    src_sms = T.rd(os.path.join(APP, "source", "functions", "dmr_sms.c"))
    test_part_a(src_uu)
    test_part_b(src_uu)
    test_part_v(src_cm, src_uu, png)
    test_part_g(src_cm, src_sms)
    print("test_r98fix11: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
