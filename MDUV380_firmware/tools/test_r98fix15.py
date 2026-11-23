# -*- coding: utf-8 -*-
"""test_r98fix15.py -- R98-FIX15: біжуча стрічка рядка 3 карток «Подвійного прийому» (DW).

  А  рядок 1 (назва 8x16) не переповнюється: 16 символів -> x=7..134 (typedef dwName16Fits), VFO -- 14 символів; рядок 3 без відстані -- до 24 символів
     на всю ширину; переповнення лише під час виклику з відстанню
  Б  стрічка на справжньому dualRenderRow (гарнес карток R98-FIX13, dwMqTestNow -- час): пауза на початку (DW_MQ_PAUSE0 кроків), зсув на символ за крок
     до кінця, пауза в кінці (DW_MQ_PAUSE1), повтор; найгірші випадки: канал 1024 + PC 16777215 + стрілка, ТГ 22504 зі стрілкою і без
  В  нерухомий текст (влазить) не змінюється з часом
  Г  область: заливка лише вікна лівої частини (x=7.., ширина = вікно), відстань і стрілка -- на своїх місцях, зазор >= 1 символ
  Д  скидання: інший текст (ТГ виклику), набір цифр -- з початку
  Е  тік (справжній dualMarqueeTick + помічники, заглушки довкола): перемальовує лише при зміні зсуву, лише смуги свого рядка; не біжить і скидається:
     передача, набір цифр, екран режиму не показано, сповіщення, виклик скінчився, придушення клавіші
  Є  стан -- у RAM (не CCM), 2 структури без масивів
  Ж  мутанти: заливка заходить на праву частину; без скидання при зміні тексту; біжить під час набору цифр
"""
import os, re, subprocess, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_r98fix13 as X  # noqa
R, T, F5, F6, F8, F9 = X.R, X.T, X.F5, X.F6, X.F8, X.F9
FW = X.FW
SRC = os.path.join(X.UI, "uiChannelMode.c")
FAILS = []
N = [0]


QUIET = [False]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        if not QUIET[0]:
            print("ПРОВАЛ: " + m)


def consts(src):
    step = int(re.search(r"#define RSSI_UPDATE_COUNTER_RELOAD\s+(\d+)", T.rd(os.path.join(FW, "application", "include", "user_interface", "uiGlobals.h"))).group(1))
    p0 = int(re.search(r"#define DW_MQ_PAUSE0\s+(\d+)U", src).group(1))
    p1 = int(re.search(r"#define DW_MQ_PAUSE1\s+(\d+)U", src).group(1))
    return step, p0, p1


def scen(step, p0, p1):
    """Сценарії карток. Ключі: <серія>_<мс>. Серія -- один і той самий текст із наростаючим часом (стан картки A тягнеться між викликами)."""
    L = [r'''
	rssi = -70; own = 1; known = 1; unD[0] = unD[1] = 0; unA = 0; nonVolatileSettings.overrideTG = 0; directChannelNumber = 0; ptrB = 0;
	used[40] = 1; chans[40] = chans[5]; NAME(40, "Ukraine group"); chans[40].contact = 6; chans[40].txColor = 7; chans[40].encrypt = 0; chans[40].libreDMR_Power = 0; chans[40].rxFreq = chans[40].txFreq = 43012500U;
	cts[6].tgNumber = 22504; cts[6].callType = CONTACT_CALLTYPE_TG; memcpy(cts[6].name, "Ukraine         ", 16); cts[6].reserve1 = CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;
	used[2] = 1; chans[2] = chans[5]; NAME(2, "Two"); chans[2].contact = 6; chans[2].txColor = 1; chans[2].encrypt = 0; chans[2].libreDMR_Power = 0;
	strcpy(item.contact, "ID:2550213"); strcpy(item.talkerAlias, "UR5EQF Bogdan");
''']
    times = lambda base: [base + t for t in sorted(set([0, step, (p0 - 1) * step, p0 * step - 1, p0 * step] + [p0 * step + i * step for i in range(1, 12)] +
                                                       [(p0 + 9 + p1) * step + i * step for i in range(0, 12)]))]
    series = [("a", 0, 'strcpy(item.talkgroup, "TG 22504"); known = 1; own = 1;', 40),        # ТГ 22504, відстань + стрілка
              ("b", 100000, 'strcpy(item.talkgroup, "TG 22504"); known = 0; own = 1;', 40),   # відстань без стрілки
              ("w", 200000, 'strcpy(item.talkgroup, "PC 16777215"); known = 1; own = 1;', 1024),   # найгірший: канал 1024, CC15, PC 16777215, стрілка
              ("s", 300000, 'strcpy(item.talkgroup, "TG 22504"); known = 1; own = 0;', 40),   # без відстані -- влазить, нерухомо
              ("c", 400000, 'strcpy(item.talkgroup, "TG 9"); known = 1; own = 1;', 2)]        # канал 2, ТГ 9 -- влазить і з відстанню
    for name, base, setup, ch in series:
        L.append("\t" + setup)
        for t in times(base):
            L.append('\tdwMqTestNow = %dU; ROW("%s_%d", 11, false, %d, 0, true, true, true);' % (t, name, t - base, ch))
    # Д: зміна тексту посеред зсуву -- з початку; набір цифр -- з початку
    base = 500000
    L.append('\tstrcpy(item.talkgroup, "PC 16777215"); known = 1; own = 1;')
    L.append('\tdwMqTestNow = %dU; ROW("r_0", 11, false, 1024, 0, true, true, true);' % base)
    L.append('\tdwMqTestNow = %dU; ROW("r_mid", 11, false, 1024, 0, true, true, true);' % (base + (p0 + 3) * step))
    L.append('\tstrcpy(item.talkgroup, "PC 16777214"); dwMqTestNow = %dU; ROW("r_new", 11, false, 1024, 0, true, true, true);' % (base + (p0 + 3) * step + 1))
    L.append('\tdwMqTestNow = %dU; ROW("r_new2", 11, false, 1024, 0, true, true, true);' % (base + (p0 + 3) * step + 2 + (p0 + 2) * step))
    L.append('\tdirectChannelNumber = 12; dwMqTestNow = %dU; ROW("r_dig", 11, false, 1024, 0, true, true, true); directChannelNumber = 0;' % (base + (p0 + 3) * step + 3 + (p0 + 2) * step))
    L.append('\tdwMqTestNow = %dU; ROW("r_after", 11, false, 1024, 0, true, true, true);' % (base + (p0 + 3) * step + 4 + (p0 + 2) * step))
    L.append('\town = 0; rssi = -200; known = 1;')
    return "\n".join(L) + "\n"


def full_text(series):
    return {"a": "40 TS1 CC7 TG 22504", "b": "40 TS1 CC7 TG 22504", "w": "1024 TS1 CC15 PC 16777215", "s": "40 TS1 CC7 TG 22504", "c": "2 TS1 CC1 TG 9"}[series]


def run_cards(src, step, p0, p1):
    X.SCEN13 = scen(step, p0, p1)
    tu_uu = R.pp_text(X.REL_UU)
    H, env = R.harness_after(tu_uu)
    return X.build13(src, H, env)


def fills(o, k, D):
    return [p for p in X.prims(o, k) if p["k"] == "f" and p["y"] == D["DW_ROW3_DY"]]


def card_checks(o, D, step, p0, p1, tag=""):
    keys = sorted({k for k in o if re.match(r"^[abwsc]_\d+$", k)}, key=lambda k: (k[0], int(k[2:])))
    ok_all = True
    for ser in "abw":
        ks = [k for k in keys if k[0] == ser]
        full = full_text(ser)
        L = X.tx(o, ks[0], D, "3L")
        win = len(L) if L else 0
        k_over = len(full) - win
        check(L is not None and 0 < win < len(full) and full.startswith(L), "Б0%s (%s): на старті -- початок тексту у вікні %d символів (виліт %d): %r" % (tag, ser, win, k_over, L))
        if not L:
            ok_all = False
            continue
        bad = []
        for k in ks:
            t = int(k[2:])
            cyc = (p0 + k_over + p1) * step
            e = t % cyc
            exp = 0 if e < p0 * step else min(k_over, (e - p0 * step) // step + 1)
            got = X.tx(o, k, D, "3L")
            if got != full[exp:exp + win]:
                bad.append((t, got, full[exp:exp + win]))
        check(bad == [], "Б1%s (%s): пауза %d кроків, зсув на символ за %d мс до кінця, пауза %d кроків, повтор: %r" % (tag, ser, p0, step, p1, bad[:3]))
        ok_all = ok_all and bad == []
        # повний текст проходить за цикл: кожен символ хоча б раз у вікні
        seen = set()
        for k in ks:
            got = X.tx(o, k, D, "3L") or ""
            i = full.find(got)
            if i >= 0:
                seen |= set(range(i, i + len(got)))
        check(seen == set(range(len(full))), "Б2%s (%s): за цикл видно весь текст «%s»" % (tag, ser, full))
        # Г: область
        badg = []
        for k in ks:
            fl = fills(o, k, D)
            r3 = X.row_text(o, k, D, "3R")
            if len(fl) != 1 or fl[0]["x"] != D["DW_IN_L"] or fl[0]["w"] != win * 6 or fl[0]["h"] != 8:
                badg.append((k, "заливка", fl))
            elif r3 is None or r3["x"] < fl[0]["x"] + fl[0]["w"] + 6:
                badg.append((k, "відстань", r3))
            arrow = [p for p in X.prims(o, k) if p["k"] == "t"]
            if ser in "aw" and arrow and min(p["x"] for p in arrow) < fl[0]["x"] + fl[0]["w"]:
                badg.append((k, "стрілка", arrow[:1]))
        ok_all = ok_all and badg == []
        check(badg == [], "Г1%s (%s): заливка лише вікна (x=%d, ширина %d px, висота 8), відстань/стрілка правіше, зазор >= 6 px: %r" % (tag, ser, D["DW_IN_L"], win * 6, badg[:2]))
        sel = [p for p in X.prims(o, ks[0]) if p["k"] == "f" and p["x"] == D["DW_SEL_X"]]
        check(sel and all(p["x"] + p["w"] <= D["DW_IN_L"] - 1 for p in sel), "Г2%s (%s): смуга вибору не зачеплена (x<=%d)" % (tag, ser, D["DW_IN_L"] - 2))
    # найгірший -- виміряно
    for ser, exp_win in (("a", None), ("b", None), ("w", None)):
        pass
    # В: нерухомий
    for ser in "sc":
        vals = {X.tx(o, k, D, "3L") for k in keys if k[0] == ser}
        check(vals == {full_text(ser)} and not any(fills(o, k, D) for k in keys if k[0] == ser),
              "В1%s (%s): текст, що влазить, нерухомий і без заливки вікна: %r" % (tag, ser, vals))
    return ok_all


def reset_checks(o, D, tag=""):
    full = "1024 TS1 CC15 PC 16777215"
    win = len(X.tx(o, "r_0", D, "3L") or "")
    mid = X.tx(o, "r_mid", D, "3L")
    new = X.tx(o, "r_new", D, "3L")
    new2 = X.tx(o, "r_new2", D, "3L")
    dig = X.tx(o, "r_dig", D, "3L")
    aft = X.tx(o, "r_after", D, "3L")
    check(mid is not None and mid != full[:win], "Д0%s: посеред циклу текст зсунуто: %r" % (tag, mid))
    check(new == "1024 TS1 CC15 PC 16777214"[:win], "Д1%s: інший ТГ/ID виклику -- з початку (пауза): %r" % (tag, new))
    check(new2 is not None and new2 != new, "Д2%s: після нової паузи -- знову зсув: %r" % (tag, new2))
    check(dig == "1024 TS1 CC15 PC 16777214"[:win] or (dig or "").startswith("1024"), "Д3%s: набір цифр -- початок тексту: %r" % (tag, dig))
    check(aft == "1024 TS1 CC15 PC 16777214"[:win], "Д4%s: після набору цифр -- цикл з початку (пауза): %r" % (tag, aft))
    return new == "1024 TS1 CC15 PC 16777214"[:win] and aft == "1024 TS1 CC15 PC 16777214"[:win]


# ------------------------------------------------------------------------------------------------------- Е: тік
TICK_H = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stddef.h>
enum { THEME_ITEM_FG_CHANNEL_NAME = 1, THEME_ITEM_BG = 2 };
enum { FONT_SIZE_1 = 0 };
enum { TEXT_ALIGN_LEFT = 0 };
struct { _Bool displayChannelSettings; } uiDataGlobal;
struct { char talkgroup[32]; } itemS, *LinkHead = &itemS;
int directChannelNumber;
static _Bool s_dualQuiet;
static int g_shown = 1, g_tx = 0, g_notif = 0, g_menu = @@MENU@@, g_caller = 1;
static uint32_t g_now;
static int g_rows = 0, g_rowA = -1, g_rowB = -1, g_print = 0;
_Bool uiChannelModeDualScreenShown(void) { return g_shown; }
_Bool isTransmittingIgnoringAPRSBeaconing(void) { return g_tx; }
_Bool uiNotificationIsVisible(void) { return g_notif; }
int menuSystemGetCurrentMenuNumber(void) { return g_menu; }
static _Bool dualCallerNow(void) { return g_caller; }
uint32_t ticksGetMillis(void) { return g_now; }
void displayThemeApply(int a, int b) { }
void displayThemeResetToDefault(void) { }
void displayFillRect(int16_t x, int16_t y, int16_t w, int16_t h, _Bool inv) { printf("F %d %d %d %d\n", x, y, w, h); }
int displayPrintCore(int16_t x, int16_t y, const char *t, int f, int a, _Bool inv) { printf("P %d %d %s\n", x, y, t); g_print++; return 0; }
void displayRenderRows(int16_t s, int16_t e) { printf("R %d %d\n", s, e); g_rows++; }
@@FNS@@
static void tick(const char *tag) { printf("== %s %lu\n", tag, (unsigned long)g_now); dualMarqueeTick(); }
int main(void)
{
	/* картка A: канал 1024, TS1 CC15, PC 16777215, вікно 15 символів -- як після повного малювання */
	strcpy(itemS.talkgroup, "PC 16777215");
	dwMqA.ch = 1024; dwMqA.ts = 1; dwMqA.cc = 15; dwMqA.win = 15; dwMqA.len = 25; dwMqA.t0 = 1000; dwMqA.shown = 0;
	{ char l3[32]; dwMqText(l3, sizeof l3, &dwMqA); dwMqA.sig = dwMqSig(l3, dwMqA.win); printf("TEXT %s\n", l3); }
	for (g_now = 1000; g_now <= 1000 + @@CYC@@; g_now += 10) { tick("run"); }
	/* передача посеред зсуву: не малює, скидає */
	g_now += @@MID@@; tick("mid");
	g_tx = 1; g_now += 10; tick("tx"); g_now += 5000; tick("tx2"); g_tx = 0;
	g_now += 10; tick("after_tx");
	/* набір цифр */
	g_now += @@MID@@; tick("mid2"); directChannelNumber = 5; g_now += 10; tick("dig"); g_now += 3000; tick("dig2"); directChannelNumber = 0; g_now += 10; tick("after_dig");
	/* екран режиму не показано / сповіщення / виклик скінчився / придушення / інше меню */
	g_now += @@MID@@; tick("mid3"); g_shown = 0; g_now += 10; tick("noshow"); g_shown = 1;
	g_notif = 1; g_now += 10; tick("notif"); g_notif = 0;
	g_caller = 0; g_now += 10; tick("nocall"); g_caller = 1;
	s_dualQuiet = 1; g_now += 10; tick("quiet"); s_dualQuiet = 0;
	g_menu = g_menu + 1; g_now += 10; tick("menu"); g_menu = g_menu - 1;
	g_now += 10; tick("back");
	/* ТГ змінився між повними малюваннями -- з початку */
	g_now += @@MID@@; tick("mid4"); strcpy(itemS.talkgroup, "PC 16777214"); g_now += 10; tick("tgchg");
	/* ТГ став коротким -- влазить: стрічки нема */
	strcpy(itemS.talkgroup, "9"); g_now += 10; tick("short"); g_now += @@MID@@; tick("short2");
	printf("WIN %u\n", dwMqA.win);
	return 0;
}
'''


def tick_build(src, step, p0, p1):
    tu = R.pp_text(X.REL_CM, src)
    if tu is None:
        return None, "pp"
    m = re.search(r"typedef struct\s*\{[^{}]*\}\s*dwMarquee_t;", tu)
    fns = [m.group(0) if m else None, "static dwMarquee_t dwMqA;", "static dwMarquee_t dwMqB;"]
    for s in ("static uint16_t dwMqSig(const char *t, size_t win)", "static uint8_t dwMqStep(dwMarquee_t *m, uint32_t now)",
              "static void dwMqText(char *l3, size_t size, const dwMarquee_t *m)", "static void dwMqDrawWindow(int16_t y, const char *l3, uint8_t win, uint8_t k)",
              "static void dualMarqueeTick(void)"):
        fns.append(T.carve_fn(tu, s))
    if not all(fns):
        return None, "carve %r" % [i for i, f in enumerate(fns) if not f]
    menu = re.search(r"menuSystemGetCurrentMenuNumber\(\) == (\w+)", fns[-1])
    k = 25 - 15
    mname = menu.group(1) if menu else "0"
    h = TICK_H.replace("@@FNS@@", "\n".join(fns)).replace("@@MENU@@", "7" if not mname.isdigit() else mname)
    if not mname.isdigit():
        h = h.replace("int directChannelNumber;", "enum { %s = 7 };\nint directChannelNumber;" % mname)
    h = h.replace("@@CYC@@", str((p0 + k + p1) * step + 2 * step)).replace("@@MID@@", str((p0 + 4) * step))
    d = tempfile.mkdtemp(prefix="r98f15_")
    try:
        c = os.path.join(d, "t.c"); open(c, "w").write(h)
        r = subprocess.run(["gcc", "-std=gnu11", "-w", "-o", c + ".x", c], capture_output=True, text=True)
        if r.returncode != 0:
            return None, r.stderr[-800:]
        return subprocess.run([c + ".x"], capture_output=True, text=True, timeout=60).stdout, ""
    finally:
        shutil.rmtree(d, ignore_errors=True)


def tick_parse(out):
    ev = []
    cur = None
    for l in out.splitlines():
        if l.startswith("== "):
            _, tag, t = l.split(); cur = {"tag": tag, "t": int(t), "F": [], "P": [], "R": []}; ev.append(cur)
        elif cur is not None and l[:2] in ("F ", "P ", "R "):
            cur[l[0]].append(l[2:])
    return ev


def tick_checks(out, step, p0, p1, D, tag=""):
    ev = tick_parse(out)
    full = "1024 TS1 CC15 PC 16777215"
    run = [e for e in ev if e["tag"] == "run"]
    draws = [e for e in run if e["P"]]
    ya = D["DW_CARD_A_Y"] + D["DW_ROW3_DY"]
    exp_rows = "%d %d" % (ya // 8, (ya + 7) // 8 + 1)
    texts = [e["P"][0].split(" ", 2)[2] for e in draws]
    exp = [full[i:i + 15] for i in range(1, 11)] + [full[:15]]
    check(texts == exp, "Е1%s: тік малює лише при зміні зсуву: 10 кроків по символу, потім повернення на початок: %r" % (tag, texts))
    t_first = draws[0]["t"] - 1000 if draws else None
    check(t_first == p0 * step, "Е2%s: перший зсув -- після паузи %d мс: %r" % (tag, p0 * step, t_first))
    gaps = [draws[i + 1]["t"] - draws[i]["t"] for i in range(len(draws) - 2)]
    check(gaps and all(g == step for g in gaps), "Е3%s: крок %d мс: %r" % (tag, step, gaps[:5]))
    check(draws and all(e["R"] == [exp_rows] and e["F"] == ["%d %d %d 8" % (D["DW_IN_L"], ya, 15 * 6)] for e in draws),
          "Е4%s: перемальовано лише вікно (x=%d, y=%d, 90x8) і смуги рядків %s: %r" % (tag, D["DW_IN_L"], ya, exp_rows, (draws[0]["F"], draws[0]["R"]) if draws else None))
    check(len(run) > 50 and sum(1 for e in run if e["P"] or e["R"]) == len(draws), "Е5%s: без зміни зсуву тік нічого не малює (на %d тіках %d малювань)" % (tag, len(run), len(draws)))
    by = {e["tag"]: e for e in ev}
    for t in ("tx", "tx2", "dig", "dig2", "noshow", "notif", "nocall", "quiet", "menu"):
        check(t in by and not by[t]["P"] and not by[t]["R"], "Е6%s: «%s» -- не малює" % (tag, t))
    for t in ("after_tx", "after_dig", "back"):
        e = by.get(t)
        check(e is not None and e["P"] and e["P"][0].endswith(full[:15]), "Е7%s: після «%s» -- з початку тексту: %r" % (tag, t, e and e["P"]))
    e = by.get("tgchg")
    check(e is not None and (not e["P"] or e["P"][0].endswith("1024 TS1 CC15 P")), "Е8%s: інший ТГ -- з початку: %r" % (tag, e and e["P"]))
    check("WIN 0" in out and not by["short2"]["P"], "Е9%s: ТГ, що влазить, -- стрічки нема: %r" % (tag, by.get("short2")))
    return texts == exp and all(t in by and not by[t]["P"] for t in ("dig", "dig2"))


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    R.INCS, cfgs = R.cmt.load_configs(FW)
    R.CF = dict(cfgs)
    for m in (F6, F8, F9):
        m.INCS, m.CF = R.INCS, R.CF
    src = T.rd(SRC)
    D = F5.consts(src)
    step, p0, p1 = consts(src)
    check(step == 200 and "#define DW_MQ_STEP_MS    RSSI_UPDATE_COUNTER_RELOAD" in src, "0: крок стрічки -- період тіку RSSI/S-метра (RSSI_UPDATE_COUNTER_RELOAD = %d мс)" % step)

    # А
    check(re.search(r"typedef char dwName16Fits\[\(\(DW_ROW1_TX \+ \(DW_ROW1_MAX \* 8\)\) <= \(DW_IN_R \+ 1\)\) \? 1 : -1\];", src) is not None and
          D["DW_ROW1_TX"] + 16 * 8 <= D["DW_IN_R"] + 1 and "if (strlen(l1) > DW_ROW1_MAX)" in src,
          "А1: рядок 1 -- до 16 символів 8x16, x=%d..%d <= %d: не переповнюється, стрічка не потрібна" % (D["DW_ROW1_TX"], D["DW_ROW1_TX"] + 127, D["DW_IN_R"]))
    check(D["DW_ROW3_MAX"] * 6 <= D["DW_IN_R"] + 1 - D["DW_IN_L"] and "char l3[DW_ROW3_BUF];" in src and "#define DW_ROW3_BUF      (DW_ROW3_MAX + 2)" in src,
          "А2: рядок 3 без відстані -- до %d символів у ширині x=%d..%d: влазить завжди" % (D["DW_ROW3_MAX"], D["DW_IN_L"], D["DW_IN_R"]))

    o = run_cards(None, step, p0, p1)
    check(o is not None, "Б: хостова збірка карток (справжній dualRenderRow)")
    if o is None:
        return finish()
    card_checks(o, D, step, p0, p1)
    reset_checks(o, D)
    # виміряно: вікна
    for ser, ch in (("a", "40"), ("b", "40"), ("w", "1024")):
        k0 = [k for k in o if k == ser + "_0"]
        L = X.tx(o, k0[0], D, "3L") if k0 else None
        print("  виміряно (%s): вікно %d символів, повний текст %d -- виліт %d" % (ser, len(L or ""), len(full_text(ser)), len(full_text(ser)) - len(L or "")))

    out, err = tick_build(src, step, p0, p1)
    check(out is not None, "Е0: гарнес тіку (dualMarqueeTick і помічники) зібрався: %s" % err)
    if out:
        tick_checks(out, step, p0, p1, D)

    # Є: пам'ять
    check(re.search(r"^static dwMarquee_t dwMqA;", src, re.M) is not None and re.search(r"^static dwMarquee_t dwMqB;", src, re.M) is not None and
          "DMR_AES_CCM" not in src[src.index("typedef struct\n{\n\tuint32_t t0;"):src.index("static uint16_t dwMqSig")] and
          not re.search(r"dwMarquee_t\s+\w+\s*\[", src), "Є1: стан стрічки -- дві структури в RAM (без атрибута CCM), без масивів")
    blk = src[src.index("typedef struct\n{\n\tuint32_t t0;"):src.index("} dwMarquee_t;")]
    check("[" not in blk, "Є2: у dwMarquee_t немає масивів")

    # Ж: мутанти
    def mut(name, a, b, kind):
        s2 = src.replace(a, b, 1)
        if s2 == src:
            check(False, "Ж (%s): шаблон не знайдено" % name); return
        if kind == "cards":
            o2 = run_cards(s2, step, p0, p1)
            if o2 is None:
                check(True, "Ж (%s): не збирається -- ловиться" % name); return
            n0 = len(FAILS); QUIET[0] = True
            ok = card_checks(o2, D, step, p0, p1, tag="[m]") and reset_checks(o2, D, tag="[m]")
            QUIET[0] = False; del FAILS[n0:]
            check(not ok, "Ж (%s): ловиться" % name)
        else:
            out2, e2 = tick_build(s2, step, p0, p1)
            if out2 is None:
                check(True, "Ж (%s): не збирається -- ловиться" % name); return
            n0 = len(FAILS); QUIET[0] = True
            ok = tick_checks(out2, step, p0, p1, D, tag="[m]")
            QUIET[0] = False; del FAILS[n0:]
            check(not ok, "Ж (%s): ловиться" % name)
    mut("заливка заходить на праву частину", "displayFillRect(DW_IN_L, (y + DW_ROW3_DY), (int16_t)(win * 6), 8, true);",
        "displayFillRect(DW_IN_L, (y + DW_ROW3_DY), (int16_t)((win + 3) * 6), 8, true);", "cards")
    mut("без скидання при зміні тексту", "if ((sig != mq->sig) || (mq->win == 0U) || (directChannelNumber != 0))", "if ((mq->win == 0U) || (directChannelNumber != 0))", "cards")
    mut("біжить під час набору цифр", "(directChannelNumber == 0) && (s_dualQuiet == false)", "(s_dualQuiet == false)", "tick")
    return finish()


def finish():
    print("test_r98fix15: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
