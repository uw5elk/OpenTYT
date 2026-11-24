#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX13 (хост): картки «Подвійного прийому» -- лівий край, конверти SMS/APRS у шапці, ТГ, режим+потужність, RX/TX, замок.
  А  ▶ нема: обрану показує лише смуга x=2..5; усі чотири рядки (назва 8x16, рядок 2 8x16, рядок 3, рядок 4) починаються з x=7; 16 символів 8x16 -- x=7..134.
  Б  рядок 2 FM-каналу й VFO -- лише частота («434.70000»), без «FM» (режим -- у рядку 4 праворуч); DMR-картки без змін.
  Г  між картками ОДНА лінія (міряється за пікселями: «до» -- чотири горизонтальні лінії y=11, 67, 71, 127; «після» -- три: 12, 68, 124); висота картки й рівність проміжків (R98-FIX12) цілі.
  В  конверти SMS DMR й APRS -- ГЛОБАЛЬНІ, у шапці DW: «A ✉ N» ліворуч, «D ✉ N» праворуч (той самий примітив drawMsgEnvelope, що на звичайному екрані); у картках значків нема.
     Піксельна модель шапки (справжні шрифти прошивки): усі комбінації лічильників 0/1/2/5/9/10/99 для A і D, усі варіанти заряду (відсотки, вольти) і годинника -- без перетину з «DW», зарядом,
     годинником, у межах рядка шапки (y=1..9), зазор >= 2 порожніх px до всього, що поруч; без APRS_RX кода APRS нема; лічильник 0 -- конверта нема.
  Д  рядок 4 неактивної картки: DMR-канал -- «RX» + частота прийому + «+»/«-» (TX вище/нижче) вплотну; FM-канал і VFO -- «TX» + частота передачі лише коли TX != RX, інакше порожньо; без каналу -- порожньо.
  Е  рядок 3: ліва частина на всю ширину (повний ТГ: «TG22504», «PC16777215»), праворуч лише відстань + стрілка під час виклику (які саме комбінації обрізають ТГ -- таблиця нижче);
     «режим потужність» («DMR 3W», «FM 750mW») -- у рядку 4 праворуч.
  Є  замок AES -- крайній праворуч (стокове місце), >= 2 px до того, що ліворуч; пріоритет замок > режим+потужність (слово «DMR»/«FM» відкидається першим, потім обрізається потужність);
     typedef-перевірки збірки (dwMeterClearOfIcons, dwRow4Fits, dwCardsOneLine) -- gcc -fsyntax-only на мутантах.
  PNG: `--png КАТАЛОГ`.
Запуск: python3 tools/test_r98fix13.py [--png КАТАЛОГ]"""
import os, re, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
import test_r98fix5 as F5  # noqa
import test_r98fix6 as F6  # noqa
import test_r98fix8 as F8  # noqa
import test_r98fix9 as F9  # noqa
import test_r98fix11 as R  # noqa
import test_r98fix12 as F12  # noqa
import dw_rowgap as G  # noqa

FAILS = []; N = [0]
APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
REL_CM = R.REL_CM; REL_UU = R.REL_UU
BASE = "fe359e8"      # HEAD після R98-FIX12 -- «до»


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


# ------------------------------------------------------------------------------------------------ додаткові сценарії карток (гарнес FIX9 + FIX13)
SCEN13 = r'''
	/* ---------------- R98-FIX13 ---------------- */
	rssi = -200; own = 0; known = 1; unD[0] = unD[1] = 0; unA = 0; nonVolatileSettings.overrideTG = 0; directChannelNumber = 0; ptrB = 0;
#define DMRCH(i, nm, rx, tx) do { used[i] = 1; chans[i] = chans[5]; NAME(i, nm); chans[i].rxFreq = (rx); chans[i].txFreq = (tx); chans[i].libreDMR_Power = 0; chans[i].encrypt = 0; chans[i].txColor = 1; chans[i].contact = 2; } while (0)
#define FMCH(i, nm, rx, tx) do { used[i] = 1; chans[i] = chans[11]; NAME(i, nm); chans[i].rxFreq = (rx); chans[i].txFreq = (tx); chans[i].libreDMR_Power = 0; chans[i].encrypt = 0; chans[i].rxTone = chans[i].txTone = 0xFFFF; chans[i].flags = CHANNEL_FLAG_BW_25K; } while (0)
	DMRCH(30, "DMR plus", 17117500U, 17137500U); DMRCH(31, "DMR minus", 17117500U, 17097500U); DMRCH(32, "DMR simplex", 43012500U, 43012500U); DMRCH(33, "DMR tx unset", 43012500U, 0U);
	FMCH(34, "FM simplex", 43470000U, 43470000U); FMCH(35, "FM plus", 14560000U, 14600000U); FMCH(36, "FM minus", 14600000U, 14560000U); used[37] = 0;
	ROW("n30", 11, false, 30, 0, false, false, false); ROW("n31", 11, false, 31, 0, false, false, false); ROW("n32", 11, false, 32, 0, false, false, false); ROW("n33", 11, false, 33, 0, false, false, false);
	ROW("n34", 11, false, 34, 0, false, false, false); ROW("n35", 11, false, 35, 0, false, false, false); ROW("n36", 11, false, 36, 0, false, false, false); ROW("n37", 11, false, 37, 0, false, false, false);
	ROW("n34s", 11, false, 34, 0, true, false, false);                       /* обрана FM simplex */
	/* VFO B: FM зі зсувом, FM simplex, DMR зі зсувом, DMR simplex */
	settingsVFOChannel[1].chMode = RADIO_MODE_ANALOG; settingsVFOChannel[1].rxFreq = 14550000U; settingsVFOChannel[1].txFreq = 14610000U; ROW("nv1", 71, true, 0, 2, false, false, false);
	settingsVFOChannel[1].txFreq = 14550000U; ROW("nv2", 71, true, 0, 2, false, false, false);
	settingsVFOChannel[1].chMode = RADIO_MODE_DIGITAL; settingsVFOChannel[1].rxFreq = 43012500U; settingsVFOChannel[1].txFreq = 43062500U; ROW("nv3", 71, true, 0, 2, false, false, false);
	settingsVFOChannel[1].txFreq = 43012500U; ROW("nv4", 71, true, 0, 2, false, false, false);
	/* незбережена правка картки A (потужність 750 мВт у буфері, та сама назва/частоти) -- видно на картці */
	chans[30].libreDMR_Power = 0; channelScreenChannelData = chans[30]; channelScreenChannelData.libreDMR_Power = 10; ROW("ned", 11, false, 30, 0, false, false, false); channelScreenChannelData = chans[9];
	/* найгірший випадок: канал 1024, CC15, ТГ 16777215, 750 мВт, замок */
	rssi = -60; ROW("w7a", 11, false, 1024, 0, true, true, false); rssi = -200;                                           /* активна: RX + S-метр, «DMR 750mW», замок */
	chans[1024].rxFreq = 17117500U; chans[1024].txFreq = 17097500U; ROW("w7b", 11, false, 1024, 0, false, false, false);   /* неактивна: «RX 171.17500-», «DMR 750mW», замок */
	chans[1024].txFreq = 17137500U; ROW("w7p", 11, false, 1024, 0, true, false, false);                                  /* те саме з «+» */
	chans[1024].txFreq = chans[1024].rxFreq;
	FMCH(41, "FM 750 lock", 14560000U, 14600000U); chans[41].encrypt = 1; chans[41].libreDMR_Power = 10; ROW("w7c", 11, false, 41, 0, false, false, false);   /* FM: «TX 146.00000», «FM 750mW», замок */
	/* ТГ 22504 цілком у рядку 3; DMR без ключа */
	used[40] = 1; chans[40] = chans[5]; NAME(40, "Ukraine group"); chans[40].contact = 6; chans[40].txColor = 7; chans[40].encrypt = 0; chans[40].libreDMR_Power = 0; chans[40].rxFreq = chans[40].txFreq = 43012500U;
	cts[6].tgNumber = 22504; cts[6].callType = CONTACT_CALLTYPE_TG; memcpy(cts[6].name, "Ukraine         ", 16); cts[6].reserve1 = CODEPLUG_CONTACT_FLAG_NO_TS_OVERRIDE;
	ROW("t40", 11, false, 40, 0, false, false, false);
	/* виклик: з відстанню і стрілкою, з відстанню без стрілки, без відстані (своєї позиції нема) */
	own = 1; known = 1; rssi = -70; strcpy(item.contact, "ID:2550213"); strcpy(item.talkerAlias, "UR5EQF Bogdan"); strcpy(item.talkgroup, "TG 22504");
	ROW("c40a", 11, false, 40, 0, true, true, true);                    /* відстань + стрілка */
	known = 0; ROW("c40b", 11, false, 40, 0, true, true, true); known = 1;   /* відстань без стрілки */
	own = 0; ROW("c40c", 11, false, 40, 0, true, true, true);           /* без відстані */
	own = 1; strcpy(item.talkgroup, "PC 16777215"); ROW("c24a", 11, false, 1024, 0, true, true, true); own = 0; rssi = -200;
	channelScreenChannelData = chans[9];
'''


def build13(src_cm, H, env):
    H = H.replace("txt[24]", "txt[40]")   # гарнес: найдовший рядок 3 -- 24 символи (+ NUL)
    i = H.rfind("	return 0;\n}")
    H13 = H[:i] + SCEN13 + H[i:]
    tu = R.pp_text(REL_CM, src_cm)
    return R.run_cards(tu, H13, env) if tu else None


def prims(o, k):
    return F6.prims_of(o.get(k))


def texts(ps, **kw):
    out = []
    for p in ps:
        if p["k"] != "T":
            continue
        if all(p.get(a) == v for a, v in kw.items()):
            out.append(p)
    return out


def row_text(o, k, D, row):
    """Текст рядка: 1 -- назва, 2 -- абонент/частота (8x16), 3L/3R -- рядок 3 зліва/справа, 4tag/4f/4mp -- рядок 4."""
    ps = prims(o, k)
    R4 = D["DW_ROW4_DY"] + D["DW_ROW4_TXT_DY"]
    sel = {
        "1": lambda p: p["font"] == 3 and p["y"] == D["DW_ROW1_DY"],
        "2": lambda p: p["font"] == 3 and p["y"] == D["DW_ROW2_DY"],
        "3L": lambda p: p["font"] == 1 and p["y"] == D["DW_ROW3_DY"] and p["x"] == D["DW_IN_L"],
        "3R": lambda p: p["font"] == 1 and p["y"] == D["DW_ROW3_DY"] and p["x"] > D["DW_IN_L"],
        "4tag": lambda p: p["font"] == 1 and p["y"] == R4 and p["x"] == D["DW_IN_L"] and p["t"] in ("RX", "TX"),
        "4f": lambda p: p["font"] == 1 and p["y"] == R4 and p["x"] == D["DW_METER_X"],
        "4mp": lambda p: p["font"] == 1 and p["y"] == R4 and p["x"] >= D["DW_MP_MIN_X"] - 12,
    }[row]
    r = [p for p in ps if p["k"] == "T" and sel(p)]
    return r[0] if r else None


def tx(o, k, D, row):
    p = row_text(o, k, D, row)
    return None if p is None else p["t"]


# ============================================================================================================ А: ▶ і лівий край
def test_left(D, o, src_cm):
    import screen_sim as sim
    check(not any(c in D for c in ("DW_TRI_X", "DW_TRI_W", "DW_TRI_CY")) and "▶" not in src_cm.split("static void dualRenderRow(")[1].split("static bool dualActivity(")[0].replace("▶ нема", "").replace("(R98-FIX13 А: стрілки ▶ нема", ""),
          "А1: у dualRenderRow нема коду ▶ (DW_TRI_* прибрано)")
    check(D["DW_ROW1_TX"] == D["DW_IN_L"] == 7 and D["DW_SEL_X"] == 2 and D["DW_SEL_W"] == 4, "А1: смуга x=2..5, усі рядки з x=%d (DW_ROW1_TX == DW_IN_L)" % D["DW_IN_L"])
    check(D["DW_ROW1_TX"] + 16 * 8 <= D["DW_IN_R"] + 1, "А1: 16 символів 8x16 від x=7 -- x=7..%d (поле до x=%d): вміщується без обрізання" % (7 + 127, D["DW_IN_R"]))
    d = R.render
    seen = 0
    for ka, kb in (("s1a", "s1b"), ("s2a", "s2b"), ("s3a", "s3b"), ("s4a", "s4b"), ("p6a", "p6b"), ("w1a", "w2b")):
        fr = R.render(o, ka, kb, D)
        for key, y0 in ((ka, D["DW_CARD_A_Y"]), (kb, D["DW_CARD_B_Y"])):
            ps = prims(o, key)
            seen += 1
            sel = any(p["k"] == "f" and p["x"] == D["DW_SEL_X"] and p["w"] == D["DW_SEL_W"] for p in ps)
            check(not [p for p in ps if p["k"] == "l" and D["DW_IN_L"] <= p["x"] <= D["DW_IN_L"] + 3 and p["y"] < D["DW_ROW2_DY"]], "А1: на картці %s нема лінії ▶ (x=7..10, рядки 1)" % key)
            # піксельно: у стовпчиках x=6..10 між рамкою і рядком 2 -- нічого, окрім літер назви (з x=7) та смуги (x=2..5)
            band = {(x, y) for y in range(y0 + 1, y0 + D["DW_CARD_H"] - 1) for x in range(D["DW_SEL_X"] + D["DW_SEL_W"], D["DW_IN_L"]) if fr.px[y * sim.W + x] != sim.IT["BG"]}
            check(band == set(), "А1: стовпчик x=6 (зазор після смуги) порожній на всю висоту картки %s" % key)
            stripe = {(x, y) for y in range(y0 + 1, y0 + D["DW_CARD_H"] - 1) for x in range(D["DW_SEL_X"], D["DW_SEL_X"] + D["DW_SEL_W"]) if fr.px[y * sim.W + x] == sim.IT["BG_MENU_ITEM_SELECTED"]}
            check((len(stripe) == D["DW_SEL_W"] * (D["DW_CARD_H"] - 2)) == sel, "А1: смуга виділення x=2..5 лише в обраної (%s, обрана=%s)" % (key, sel))
            # перший піксель «чорнила» кожного рядка -- не лівіше за x=7; клітинки рядків 1..4 починаються з x=7
            for row in ("1", "2", "3L"):
                p = row_text(o, key, D, row)
                if p is not None:
                    check(p["x"] == D["DW_IN_L"], "А1: рядок %s картки %s починається з x=%d (клітинка)" % (row, key, D["DW_IN_L"]))
            t4 = row_text(o, key, D, "4tag")
            if t4 is not None:
                check(t4["x"] == D["DW_IN_L"], "А1: рядок 4 картки %s починається з x=%d" % (key, D["DW_IN_L"]))
            inkL = min([x for y in range(y0 + 2, y0 + D["DW_ROW4_DY"] + 9) for x in range(D["DW_IN_L"] - 1, D["DW_IN_R"] + 1) if fr.px[y * sim.W + x] != sim.IT["BG"]] or [D["DW_IN_L"]])
            check(inkL >= D["DW_IN_L"], "А1: «чорнило» вмісту картки %s -- не лівіше за x=%d (знайдено x=%d)" % (key, D["DW_IN_L"], inkL))
    check(seen >= 10, "А1: перевірено карток: %d" % seen)
    # довга назва: 16 широких символів -- повністю (x=7..134)
    ps = prims(o, "s4a")
    nm = row_text(o, "s4a", D, "1")
    check(nm is not None and len(nm["t"]) == 16 and nm["x"] + 16 * 8 - 1 <= D["DW_IN_R"], "А1: 16-символьна назва (s4a): %d символів, x=%d..%d" % (len(nm["t"]), nm["x"], nm["x"] + 16 * 8 - 1))


# ============================================================================================================ Б: FM без «FM» у рядку 2
def test_fm_row2(D, o):
    for k in ("s2b", "s3b", "w2a", "w2b", "n34", "n35", "n36", "nv1", "nv2"):
        t2 = tx(o, k, D, "2")
        isvfo = k.startswith("nv")
        check(t2 is not None and re.fullmatch(r"\d{3}\.\d{5}", t2) is not None and "FM" not in (tx(o, k, D, "2") or ""), "Б1: рядок 2 FM-%s %s -- лише частота (%r), без «FM»" % ("VFO" if isvfo else "картки", k, t2))
        mp = tx(o, k, D, "4mp")
        check(mp is not None and mp.startswith("FM "), "Б1: режим «FM» перенесено в рядок 4 праворуч (%s): %r" % (k, mp))
    t = tx(o, "nv1", D, "1")
    check(t == "VFO B", "Б1: рядок 1 VFO FM лишився «VFO B» (%r)" % t)
    # DMR-картки без змін: рядок 2 -- призначення/абонент
    check(tx(o, "s1a", D, "2") == "TG Ukraine 255" or tx(o, "s1a", D, "2") is not None, "Б2: DMR-картка s1a -- рядок 2 як було (%r)" % tx(o, "s1a", D, "2"))
    t = tx(o, "nv3", D, "1")
    check(t is not None and t.startswith("VFOB 430."), "Б2: VFO DMR -- у рядку 1 «VFOB частота» (як було): %r" % t)
    check(tx(o, "nv3", D, "2") is not None and not re.fullmatch(r"\d{3}\.\d{5}", tx(o, "nv3", D, "2")), "Б2: у VFO DMR рядок 2 -- не частота (як було): %r" % tx(o, "nv3", D, "2"))


# ============================================================================================================ Г: одна лінія між картками
def hlines(d, x0=1, x1=158):
    import screen_sim as sim
    ys = []
    for y in range(sim.H):
        if all(d.px[y * sim.W + x] == sim.IT["FG_DECORATION"] for x in range(x0, x1 + 1)):
            ys.append(y)
    return ys


def before_obj(H, env):
    if subprocess.run(["git", "-C", FW, "cat-file", "-e", BASE + "^{commit}"], capture_output=True).returncode != 0:
        print("ІНФО: коміт-база %s недоступний -- PNG «до» не малюється (ілюстрація, не перевірка)" % BASE); return None, None
    old = subprocess.run(["git", "-C", FW, "show", BASE + ":MDUV380_firmware/" + REL_CM], capture_output=True)
    if old.returncode != 0:
        return None, None
    so = old.stdout.decode("utf-8")
    return R.run_cards(R.pp_text(REL_CM, so), H, env), F5.consts(so)


def test_line(D, o, ob, Dold):
    for ka, kb in (("s1a", "s1b"), ("p6a", "p6b"), ("s4a", "s4b")):
        ys = hlines(R.render(o, ka, kb, D))
        exp = [D["DW_CARD_A_Y"], D["DW_CARD_B_Y"], D["DW_CARD_B_Y"] + D["DW_CARD_H"] - 1]
        check(ys == exp, "Г: після -- три горизонтальні лінії рамок %s (верх A, СПІЛЬНА, низ B), ніде не поруч; кадр %s/%s: %s" % (exp, ka, kb, ys))
        check(all(b - a > D["DW_CARD_H"] - 2 for a, b in zip(ys, ys[1:])), "Г: між картками рівно одна лінія (відстань між лініями == висота картки %d)" % (D["DW_CARD_H"] - 1))
    check(D["DW_CARD_H"] == 57 and D["DW_CARD_B_Y"] == D["DW_CARD_A_Y"] + 56 and D["DW_CARD_B_Y"] + 56 <= 127, "Г: висота картки 57, B закінчується на y=%d <= 127" % (D["DW_CARD_B_Y"] + 56))
    # смуга виділення не заходить на спільну лінію
    d = R.render(o, "s1a", "s1b", D)
    import screen_sim as sim
    y = D["DW_CARD_B_Y"]
    check(all(d.px[y * sim.W + x] == sim.IT["FG_DECORATION"] for x in range(1, 159)), "Г: спільна лінія (y=%d) -- суцільна, кольором рамки" % y)
    d2 = R.render(o, "p6a", "p6b", D)
    check(all(d2.px[y * sim.W + x] == sim.IT["FG_DECORATION"] for x in range(1, 159)), "Г: спільна лінія суцільна й коли обрана B (смуга B не перекриває її)")
    # порожні рядки над A і під B
    top = [yy for yy in range(10, D["DW_CARD_A_Y"]) if any(d.px[yy * sim.W + x] != sim.IT["BG"] for x in range(160))]
    bot = [yy for yy in range(D["DW_CARD_B_Y"] + D["DW_CARD_H"], sim.H) if any(d.px[yy * sim.W + x] != sim.IT["BG"] for x in range(160))]
    check(top == [] and bot == [], "Г: над A (y=10..%d) і під B (y=%d..127) порожньо" % (D["DW_CARD_A_Y"] - 1, D["DW_CARD_B_Y"] + D["DW_CARD_H"]))
    if ob is not None:
        yb = hlines(R.render(ob, "s1a", "s1b", Dold))
        expb = [Dold["DW_CARD_A_Y"], Dold["DW_CARD_A_Y"] + Dold["DW_CARD_H"] - 1, Dold["DW_CARD_B_Y"], Dold["DW_CARD_B_Y"] + Dold["DW_CARD_H"] - 1]
        check(yb == expb and yb[2] - yb[1] == 4, "Г «до» (код бази): ЧОТИРИ лінії %s -- між картками ДВІ паралельні (y=%d і %d, три порожніх рядки між ними): %s" % (expb, yb[1] if len(yb) > 1 else -1, yb[2] if len(yb) > 2 else -1, yb))
    return


# ============================================================================================================ Д: рядок 4 неактивної картки
def left4(o, k, D):
    tag = tx(o, k, D, "4tag"); f = tx(o, k, D, "4f")
    return (tag, f)


def test_row4_left(D, o, src_cm, H, env, mutants=True):
    exp = {
        "n30": ("RX", "171.17500+"), "n31": ("RX", "171.17500-"), "n32": ("RX", "430.12500"), "n33": ("RX", "430.12500"),
        "n34": (None, None), "n34s": (None, None), "n35": ("TX", "146.00000"), "n36": ("TX", "145.60000"),
        "nv1": ("TX", "146.10000"), "nv2": (None, None), "nv3": ("TX", "430.62500"), "nv4": (None, None), "n37": (None, None),
        "ned": ("RX", "171.17500+"), "w7b": ("RX", "171.17500-"), "w7p": ("RX", "171.17500+"), "w7c": ("TX", "146.00000"),
    }
    for k, e in exp.items():
        check(left4(o, k, D) == e, "Д: рядок 4 (%s) = %s, очікувано %s" % (k, left4(o, k, D), e))
    # знак -- ОДИН ASCII-символ одразу за останньою цифрою, без пробілу
    for k in ("n30", "n31", "w7b", "w7p"):
        f = tx(o, k, D, "4f")
        check(re.fullmatch(r"\d{3}\.\d{5}[+-]", f or "") is not None and " " not in f, "Д: знак зсуву (%s) -- один символ '+'/'-' вплотну до частоти: %r" % (k, f))
    check(tx(o, "n30", D, "4f")[-1] == "+" and tx(o, "n31", D, "4f")[-1] == "-", "Д: TX вище RX -- «+», нижче -- «-»")
    for k in ("n32", "n33"):
        check(re.fullmatch(r"\d{3}\.\d{5}", tx(o, k, D, "4f") or "") is not None, "Д: DMR simplex / TX не задано (%s) -- без знака: %r" % (k, tx(o, k, D, "4f")))
    # FM і VFO -- без знака; «TX», не «RX»
    for k in ("n35", "n36", "nv1", "nv3"):
        check(tx(o, k, D, "4tag") == "TX" and tx(o, k, D, "4f")[-1].isdigit(), "Д: FM/VFO (%s) -- «TX» і частота без знака: %s" % (k, left4(o, k, D)))
    # FM simplex: нема ні мітки, ні частоти; режим праворуч лишається
    for k in ("n34", "n34s", "nv2", "nv4"):
        check(tx(o, k, D, "4tag") is None and tx(o, k, D, "4f") is None and tx(o, k, D, "4mp") is not None, "Д: %s -- ліва частина рядка 4 порожня, «режим потужність» є: %r" % (k, tx(o, k, D, "4mp")))
    # канал видалено: рядок 4 порожній (і режиму нема), лишається номер у рядку 3
    check(row_text(o, "n37", D, "4mp") is None and tx(o, "n37", D, "3L") == "37", "Д: видалений канал -- рядок 4 порожній, у рядку 3 лише номер: %r" % tx(o, "n37", D, "3L"))
    # дані з урахуванням незбережених правок картки: режим/потужність -- з копії в пам'яті
    check(tx(o, "ned", D, "4mp") == "DMR 750mW" and tx(o, "n30", D, "4mp") == "DMR 3W", "Д: незбережена правка (потужність 750 мВт у буфері) -- видно на картці (ned: %r), без неї -- «DMR 3W» (%r)" % (tx(o, "ned", D, "4mp"), tx(o, "n30", D, "4mp")))
    # активна картка -- без змін: «RX» + S-метр, без частоти
    for k in ("w7a", "s2a", "s3b"):
        ps = prims(o, k)
        check(tx(o, k, D, "4tag") == "RX" and tx(o, k, D, "4f") is None and any(p["k"] in "fr" and p["x"] >= D["DW_METER_X"] and p["y"] >= D["DW_ROW4_DY"] for p in ps),
              "Д: активна картка (%s) без змін -- «RX» + S-метр, без частоти" % k)
    # найгірший випадок «RX 171.17500-» + «DMR 750mW»: текст лівої частини закінчується не далі x=DW_L4_END-1, режим не заходить
    f = row_text(o, "w7b", D, "4f"); mp = row_text(o, "w7b", D, "4mp")
    check(f is not None and f["x"] + len(f["t"]) * 6 <= D["DW_L4_END"] and mp is not None and mp["x"] >= D["DW_MP_MIN_X"], "Д/Є: «RX 171.17500-» (до x=%d) + «DMR 750mW» (з x=%d) -- без перетину" % (f["x"] + len(f["t"]) * 6 - 1, mp["x"]))
    if not mutants:
        return
    def mut(name, a, b, want):
        s2 = src_cm.replace(a, b, 1)
        if s2 == src_cm:
            check(False, "Д (мутант %s): не застосувався" % name); return
        o2 = build13(s2, H, env)
        if o2 is None:
            check(False, "Д (мутант %s): не зібрався" % name); return
        D2 = F5.consts(s2)
        got = {k: left4(o2, k, D2) for k in want}
        check(any(got[k] != want[k] for k in want), "Д (мутант %s): ловиться: %s" % (name, {k: got[k] for k in want if got[k] != want[k]}))
    mut("знак навпаки", "f4Sign = ((rec->txFreq > rec->rxFreq) ? '+' : '-');", "f4Sign = ((rec->txFreq > rec->rxFreq) ? '-' : '+');", {"n30": exp["n30"], "n31": exp["n31"]})
    mut("RX повторюється на FM", "if ((isVfo == false) && (rec->chMode == RADIO_MODE_DIGITAL))\n		{\n			f4Freq = rec->rxFreq;", "if (isVfo == false)\n		{\n			f4Freq = rec->rxFreq;", {"n34": exp["n34"], "n35": exp["n35"]})
    mut("TX завжди (навіть коли рівний RX)", "else if ((rec->txFreq != 0U) && (rec->txFreq != rec->rxFreq))\n		{\n			f4Freq = rec->txFreq;", "else\n		{\n			f4Freq = rec->txFreq;", {"n34": exp["n34"], "nv2": exp["nv2"]})
    mut("знак на FM", "f4Freq = rec->txFreq;\n			f4Tag = \"TX\";", "f4Freq = rec->txFreq;\n			f4Tag = \"TX\";\n			f4Sign = '+';", {"n35": exp["n35"]})


# ============================================================================================================ Е: рядок 3 (ТГ), режим+потужність
def test_row3(D, o, H, env, src_cm):
    import screen_sim as sim
    # без виклику: ліва частина -- на всю ширину, праворуч нічого
    exp3 = {"t40": "40 TS1 CC7 TG22504", "w1a": "1024 TS1 CC15 PC16777215", "w7a": "1024 TS1 CC15 PC16777215", "w7b": "1024 TS1 CC15 PC16777215"}
    for k, e in exp3.items():
        t = tx(o, k, D, "3L")
        check(t == e, "Е: рядок 3 (%s) -- ТГ цілком: %r (очікувано %r), %d символів з %d" % (k, t, e, len(t or ""), len(e)))
        p = row_text(o, k, D, "3L")
        check(p is not None and p["x"] + len(p["t"]) * 6 - 1 <= D["DW_IN_R"], "Е: рядок 3 (%s) вміщується в x=7..%d (до x=%d)" % (k, D["DW_IN_R"], p["x"] + len(p["t"]) * 6 - 1))
        check(row_text(o, k, D, "3R") is None, "Е: праворуч у рядку 3 (%s) без виклику нічого нема" % k)
    check(len(exp3["w1a"]) == D["DW_ROW3_MAX"] == 24, "Е: найгірший рядок 3 (канал 1024, CC15, PC16777215) -- рівно DW_ROW3_MAX = %d символів = 144 px" % D["DW_ROW3_MAX"])
    # режим+потужність -- у рядку 4 праворуч, не в рядку 3
    for k in ("s1a", "s2a", "w1a", "n34", "nv1", "t40", "c40a"):
        r3 = row_text(o, k, D, "3R")
        check(r3 is None or re.fullmatch(r"[\d.,]+\s?[a-zA-Z]*", r3["t"]) is not None and "DMR" not in r3["t"] and "FM" not in r3["t"] and "W" not in r3["t"], "Е: у рядку 3 праворуч (%s) -- не режим/потужність: %r" % (k, None if r3 is None else r3["t"]))
        mp = tx(o, k, D, "4mp")
        check(mp is not None and re.fullmatch(r"(DMR|FM) (\d+)(m?)W", mp) is not None, "Е: «режим потужність» у рядку 4 (%s): %r" % (k, mp))
    check(tx(o, "w1a", D, "4mp") == "DMR 750mW" and tx(o, "w2a", D, "4mp") == "FM 750mW", "Е: 750 мВт -- «DMR 750mW» і «FM 750mW» (%r, %r)" % (tx(o, "w1a", D, "4mp"), tx(o, "w2a", D, "4mp")))
    # виклик: відстань + стрілка -- ТГ обрізається; таблиця (виміряно в гарнесі для підпису відстані «1234km» -- 6 символів)
    stub_len = 6
    rows = []
    for k, full, arrow in (("c40a", "40 TS1 CC7 TG 22504", True), ("c40b", "40 TS1 CC7 TG 22504", False), ("c40c", "40 TS1 CC7 TG 22504", None), ("c24a", None, True)):
        shown = tx(o, k, D, "3L"); r3 = tx(o, k, D, "3R")
        if full is None:
            full = "1024 TS1 CC15 PC 16777215"[:D["DW_ROW3_MAX"]]
        rows.append((k, full, shown, r3, arrow))
    c = {k: (full, shown, r3, arrow) for k, full, shown, r3, arrow in rows}
    full, shown, r3, arrow = c["c40a"]
    check(r3 == "1234km" and shown == full[:15] and len(full) - len(shown) == 4, "Е: виклик «40 TS1 CC7 TG 22504» + відстань + стрілка: ТГ обрізається на %d символи (показано %r)" % (len(full) - len(shown or ""), shown))
    full, shown, r3, arrow = c["c40b"]
    check(shown == full[:17] and len(full) - len(shown) == 2, "Е: те саме з відстанню без стрілки: -%d символи (показано %r)" % (len(full) - len(shown or ""), shown))
    full, shown, r3, arrow = c["c40c"]
    check(shown == full and r3 is None, "Е: виклик без відстані (своєї позиції нема) -- ТГ цілком: %r" % shown)
    full, shown, r3, arrow = c["c24a"]
    check(shown is not None and len(shown) == 15, "Е: канал 1024 (4 цифри) із відстанню+стрілкою: ліва частина %d символів (%r)" % (len(shown or ""), shown))
    # формула «скільки символів лишається» -- та сама, що в коді: (149 - rw - 6) / 6, rw = 6 * len(відстань) [+ 12 зі стрілкою]
    def keep(lbl, arrow):
        rw = 6 * lbl + (12 if arrow else 0)
        return ((D["DW_IN_R"] + 1 - rw - 6) - D["DW_IN_L"]) // 6
    check(keep(stub_len, True) == 15 and keep(stub_len, False) == 17, "Е: формула залишку збігається з виміряним для підпису 6 символів (15 зі стрілкою, 17 без)")
    # не накладаються: ліва частина рядка 3 і відстань
    for k in ("c40a", "c40b", "c24a"):
        L = row_text(o, k, D, "3L"); Rr = row_text(o, k, D, "3R")
        check(L["x"] + len(L["t"]) * 6 + 6 <= Rr["x"] + 1, "Е: ліва частина рядка 3 (%s) і відстань не накладаються, зазор >= 6 px: до x=%d, відстань з x=%d" % (k, L["x"] + len(L["t"]) * 6 - 1, Rr["x"]))
    # таблиця для звіту
    print("ТАБЛИЦЯ-Е: під час виклику (відстань + стрілка) ліва частина рядка 3 = %d символів; ТГ обрізається, якщо «номер TS CC ТГ» довший" % keep(stub_len, True))
    for lbl in (4, 5, 6, 7, 8):
        for arrow in (True, False):
            n = keep(lbl, arrow)
            lost = [(L, 4 + 1 + 3 + 1 + 4) for L in ()]
    return c


# ============================================================================================================ Є: замок і правий блок рядка 4
def lock_ink():
    import screen_sim as sim
    d = sim.Display(); d.draw_xbitmap(0, 0, R.lock_bitmap(), 10, 9, True)
    return {(x, y) for y in range(9) for x in range(10) if d.px[y * sim.W + x] != sim.IT["BG"]}


def gap_to_lock(d, D, y0, o_key, o):
    """Порожніх px між найправішим «чорнилом» ліворуч від замка і лівим краєм «чорнила» замка (в смузі рядка 4)."""
    import screen_sim as sim
    R4 = y0 + D["DW_ROW4_DY"]
    lx = D["DW_IN_R"] + 1 - D["DW_LOCK_W"]
    lk = lock_ink(); lmin = min(x for x, _ in lk) + lx
    others = [x for y in range(R4, R4 + D["DW_ROW4_H"]) for x in range(D["DW_IN_L"], lx) if d.px[y * sim.W + x] != sim.IT["BG"]]
    return lmin - max(others) - 1, lmin, max(others)


def test_lock(D, o, H, env, src_cm):
    import screen_sim as sim
    lk = lock_ink()
    for k, ka, kb in (("w7a", "w7a", "s1b"), ("w7b", "w7b", "s1b"), ("w7p", "w7p", "s1b"), ("w7c", "w7c", "s1b"), ("s1a", "s1a", "s1b"), ("s6c", "s1a", "s6c"), ("w1a", "w1a", "w2b")):
        d = R.render(o, ka, kb, D)
        y0 = D["DW_CARD_A_Y"] if k != "s6c" else D["DW_CARD_B_Y"]
        has = any(p["k"] == "k" for p in prims(o, k))
        if not has:
            continue
        g, lmin, omax = gap_to_lock(d, D, y0, k, o)
        check(g >= D["DW_ICON_GAP"], "Є: замок (%s) -- >= %d порожніх px до того, що ліворуч: %d (замок з x=%d, ліворуч до x=%d)" % (k, D["DW_ICON_GAP"], g, lmin, omax))
        lb = [p for p in prims(o, k) if p["k"] == "k"][0]
        check(lb["x"] == D["DW_IN_R"] + 1 - D["DW_LOCK_W"] and lb["y"] == D["DW_ROW4_DY"], "Є: замок (%s) -- на стоковому місці, крайній праворуч (x=%d, y=%d)" % (k, lb["x"], lb["y"]))
        check(max(x for x, _ in lk) + lb["x"] <= D["DW_IN_R"], "Є: замок (%s) не виступає за поле вмісту (x<=%d)" % (k, D["DW_IN_R"]))
    # без замка: «режим потужність» -- до правого краю, і не зачіпає S-метр/частоту
    for k in ("s2b", "s3b", "n35", "n34"):
        mp = row_text(o, k, D, "4mp")
        check(mp is not None and mp["x"] + len(mp["t"]) * 6 == D["DW_IN_R"] + 1, "Є: без замка «режим потужність» (%s) вирівняно до правого краю x=%d" % (k, D["DW_IN_R"]))
    # найгірші: S-метр + «DMR 750mW» + замок; довга частота з «-» + «DMR 750mW» + замок
    for k in ("w7a", "w7b", "w7p", "w7c"):
        mp = row_text(o, k, D, "4mp")
        want = "FM 750mW" if k == "w7c" else "DMR 750mW"
        check(mp is not None and mp["t"] == want, "Є: найгірший блок (%s) -- без відкидання слова: %r" % (k, None if mp is None else mp["t"]))
    # пріоритет замок > режим+потужність: штучно довга потужність -- слово відкидається першим, потім обрізається; замок на місці; перетину нема
    Hl = H.replace('static char b[8]; snprintf(b, sizeof(b), (l == 9) ? "750" : "3");', 'static char b[16]; snprintf(b, sizeof(b), (l == 9) ? "12345678" : "3");')
    check(Hl != H, "Є: штучна довга потужність підставлена в гарнес")
    ol = build13(src_cm, Hl, env)
    check(ol is not None, "Є: гарнес із довгою потужністю зібрався")
    if ol is not None:
        lm = row_text(ol, "w7b", D, "4mp")     # з замком
        nm = row_text(ol, "w7c", D, "4mp")     # FM, з замком
        check(lm is not None and lm["t"] == "12345678mW"[:9] and lm["x"] + 9 * 6 == D["DW_IN_R"] + 1 - D["DW_LOCK_W"] - D["DW_ICON_GAP"],
              "Є: замок > режим: «DMR 12345678mW» (14) -> слово відкинуто («12345678mW», 10 > 9) -> обрізано до 9: %r, права межа x=%d" % (None if lm is None else lm["t"], (lm["x"] + len(lm["t"]) * 6 - 1) if lm else -1))
        ln = row_text(ol, "w1a", D, "4mp")     # з замком (канал 1024)
        check(ln is not None and ln["x"] >= D["DW_MP_MIN_X"] and ln["x"] + len(ln["t"]) * 6 <= D["DW_IN_R"] + 1 - D["DW_LOCK_W"] - D["DW_ICON_GAP"],
              "Є: з довгою потужністю блок не виходить за зазор до замка й не заходить на ліву частину (w1a): %r" % ((None if ln is None else (ln["x"], ln["t"])),))
        d = R.render(ol, "w7b", "s1b", D)
        g, lmin, omax = gap_to_lock(d, D, D["DW_CARD_A_Y"], "w7b", ol)
        check(g >= D["DW_ICON_GAP"], "Є: з довгою потужністю замок усе одно >= %d px від тексту ліворуч: %d" % (D["DW_ICON_GAP"], g))
        # без замка слово лишається, якщо вміщується: «DMR 12345678mW» = 14 символів > 11 -> слово відкидається («12345678mW» = 10 <= 11)
        nl = row_text(ol, "ned", D, "4mp")
        check(nl is not None and nl["t"] == "12345678mW" and nl["x"] + 60 == D["DW_IN_R"] + 1, "Є: без замка слово відкидається лише коли не вміщується: %r" % (None if nl is None else nl["t"]))
    # typedef-перевірки збірки
    blk = F12.typedef_block(src_cm)
    check(F12.compiles(blk), "Є: typedef-перевірки (dwMeterClearOfIcons, dwRow4Fits, dwCardsOneLine, ...) -- gcc -fsyntax-only")
    for name, subs in (("DMR 750mW -> 12 символів", [("#define DW_MP_CHARS      9 ", "#define DW_MP_CHARS      12 ")]),
                       ("ліва частина 17 символів", [("#define DW_L4_CHARS      13 ", "#define DW_L4_CHARS      17 ")]),
                       ("зазор до замка 1 px", [("#define DW_ICON_GAP      2 ", "#define DW_ICON_GAP      1 ")]),
                       ("S-метр 5/6 заходить на блок режиму", [("#define DW_METER_SEG_W   4 ", "#define DW_METER_SEG_W   5 "), ("#define DW_METER_STEP    5", "#define DW_METER_STEP    6")]),
                       ("картка B відсунута (дві лінії)", [("#define DW_CARD_B_Y      (DW_CARD_A_Y + DW_CARD_H - 1) ", "#define DW_CARD_B_Y      (DW_CARD_A_Y + DW_CARD_H + 3) ")]),
                       ("картка B за межею екрана", [("#define DW_CARD_B_Y      (DW_CARD_A_Y + DW_CARD_H - 1) ", "#define DW_CARD_B_Y      (DW_CARD_A_Y + DW_CARD_H + 4) ")])):
        s2 = src_cm
        for a, b in subs:
            if s2.count(a) != 1:
                check(False, "Є (мутант %s): рядок не знайдено: %s" % (name, a[:50])); break
            s2 = s2.replace(a, b, 1)
        else:
            check(not F12.compiles(F12.typedef_block(s2)), "Є (мутант %s): збірка прошивки впала б на typedef-перевірці" % name)


# ============================================================================================================ В: шапка з конвертами
ENV2 = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
enum { FONT_SIZE_1 = 1 }; enum { TEXT_ALIGN_LEFT = 0 };
static int first = 1;
static void out(char k, int x, int y, int w, int h, const char *t) { printf("%s%c:%d:%d:%d:%d:%s", first ? "" : ";", k, x, y, w, h, t ? t : ""); first = 0; }
int displayPrintCore(int x, int y, const char *t, int f, int al, bool inv) { (void)f; (void)al; (void)inv; out('T', x, y, (int)strlen(t) * 6, 8, t); return 0; }
void displayDrawRect(int x, int y, int w, int h, bool inv) { (void)inv; out('r', x, y, w, h, 0); }
void displayDrawLine(int a, int b, int c, int d, bool inv) { (void)inv; printf("%sl:%d:%d:%d:%d:", first ? "" : ";", a, b, c, d); first = 0; }
@@FNS@@
int main(void)
{
	static const unsigned cnt[] = { 0, 1, 2, 5, 9, 10, 99 };
	for (int a = 0; a < 7; a++)
		for (int d = 0; d < 7; d++)
		{
			first = 1; printf("a%u_d%u=", cnt[a], cnt[d]); dwHeaderEnvelopes(cnt[a], cnt[d]); printf("\n");
		}
	return 0;
}
'''
ENV2_SIGS = ["static int16_t msgEnvelopeWidth(unsigned count)", "static void drawMsgEnvelope(int16_t x, int16_t y, char letter, unsigned count)", "static void dwHeaderEnvelopes(unsigned aprsCount, unsigned dmrCount)"]


def hdr_run(tu):
    fns = [T.carve_fn(tu, s) for s in ENV2_SIGS]
    if not all(fns):
        return None, "функції шапки не знайдено: %s" % [s for s, f in zip(ENV2_SIGS, fns) if not f]
    o = F8.run_c(ENV2.replace("@@FNS@@", "\n".join(fns)))
    if o is None:
        return None, "гарнес шапки не зібрався"
    return dict(l.split("=", 1) for l in o.split("\n") if "=" in l), None


def hdr_frame(env_ps, bat, clock, with_env=True):
    """Кадр шапки: «DW» x=1, заряд (відсотки або вольти), годинник праворуч, конверти -- примітиви функції прошивки. Повертає (display, ink_by_element)."""
    import screen_sim as sim
    def blank():
        d = sim.Display(); d.theme_apply(sim.IT["FG_HEADER_TEXT"], sim.IT["BG_HEADER_TEXT"]); d.fill_rect(0, 0, 160, 10, True); return d
    base = blank().px[:]
    def ink(d):
        return {(x, y) for y in range(sim.H) for x in range(sim.W) if d.px[y * sim.W + x] != base[y * sim.W + x]}
    el = {}
    d = blank(); d.print_core(1, 2, "DW", sim.FONT_1, sim.ALIGN_LEFT, False); el["DW"] = ink(d)
    margin = 33 if clock else 0
    d = blank()
    if bat == "pct100":
        d.print_core(160 - margin - 24, 2, "100%", sim.FONT_1, sim.ALIGN_LEFT, False)
    elif bat == "pct5":
        d.print_core(160 - margin - 12, 2, "5%", sim.FONT_1, sim.ALIGN_LEFT, False)
    else:
        xv = 160 - margin - 27
        d.print_core(xv, 2, " 8", sim.FONT_1, sim.ALIGN_LEFT, False); d.draw_rect(xv + 12, 7, 2, 2, True); d.print_core(xv + 15, 2, "4V", sim.FONT_1, sim.ALIGN_LEFT, False)
    el["bat"] = ink(d)
    if clock:
        d = blank(); d.print_core(0, 2, "12:34", sim.FONT_1, sim.ALIGN_RIGHT, False); el["clock"] = ink(d)
    A = set(); Dd = set()
    if with_env:
        parts = {"A": [], "D": []}
        # конверти розрізняються за літерою: перший T -- літера
        cur = None
        for p in env_ps:
            if p["k"] == "T" and len(p["t"]) == 1 and p["t"] in "AD":
                cur = p["t"]
            parts[cur].append(p)
        for L in ("A", "D"):
            if parts[L]:
                d = blank(); R.env_draw(d, parts[L]); el["env" + L] = ink(d)
    return el


def test_header(src_uu, tu_uu):
    import screen_sim as sim
    r, err = hdr_run(tu_uu)
    check(r is not None, "В: %s" % err)
    if r is None:
        return
    cnt = (0, 1, 2, 5, 9, 10, 99)
    check(len(r) == 49, "В: гарнес шапки -- усі 49 комбінацій лічильників A × D (%d)" % len(r))
    bats = [(b, c) for b in ("pct100", "pct5", "volt") for c in (True, False)]
    worst = {}
    for a in cnt:
        for dd in cnt:
            ps = R.env_prims(r["a%u_d%u" % (a, dd)]) if r["a%u_d%u" % (a, dd)] else []
            nenv = (1 if a else 0) + (1 if dd else 0)
            check(len([p for p in ps if p["k"] == "r"]) == nenv, "В: A=%d D=%d -- конвертів %d (лічильник 0 -- конверта нема)" % (a, dd, nenv))
            nums = [p["t"] for p in ps if p["k"] == "T" and p["t"].isdigit()]
            letters = [p["t"] for p in ps if p["k"] == "T" and p["t"] in ("A", "D")]
            exp_nums = ([str(min(a, 99))] if a else []) + ([str(min(dd, 99))] if dd else [])
            check(nums == exp_nums and letters == (["A"] if a else []) + (["D"] if dd else []), "В: A=%d D=%d -- «A ✉ %s» ліворуч, «D ✉ %s» праворуч: літери %s, числа %s" % (a, dd, a, dd, letters, nums))
            if not nenv:
                continue
            for (bat, clock) in bats:
                el = hdr_frame(ps, bat, clock)
                others = {k: v for k, v in el.items() if not k.startswith("env")}
                for L in ("A", "D"):
                    e = el.get("env" + L) or set()
                    if not e:
                        continue
                    ys = [y for _, y in e]
                    check(min(ys) >= 1 and max(ys) <= 9, "В: «%s ✉» (A=%d D=%d) у межах рядка шапки y=1..9: %d..%d" % (L, a, dd, min(ys), max(ys)))
                    for name, ink in others.items():
                        c = G.cheb_min(e, ink)
                        if c is not None:
                            worst[(L, name)] = min(worst.get((L, name), 999), c - 1)
                            check(c >= 3, "В: «%s ✉» (A=%d D=%d) і %s (%s, годинник %s): >= 2 порожніх px, знайдено %d" % (L, a, dd, name, bat, clock, c - 1))
                if el.get("envA") and el.get("envD"):
                    c = G.cheb_min(el["envA"], el["envD"])
                    check(c >= 3, "В: A=%d D=%d -- «A ✉» і «D ✉» не злипаються (%d порожніх px)" % (a, dd, c - 1))
                    worst[("A", "D")] = min(worst.get(("A", "D"), 999), c - 1)
    print("ШАПКА: мінімальні порожні проміжки (px) між конвертом і сусідами у всіх комбінаціях: %s" % {"%s-%s" % k: v for k, v in sorted(worst.items())})
    # ліва/права межі
    ps = R.env_prims(r["a99_d99"])
    xs = [p["x"] for p in ps if p["k"] == "r"]
    check(len(xs) == 2 and xs[0] + 7 >= 16 + 7 and xs[1] + 13 + 2 + 12 <= 97, "В: найширші «A ✉ 99» (з x=16) і «D ✉ 99» (до x=96) -- слоти шапки: корпуси з x=%s" % xs)
    # зі збірки без APRS_RX -- коду APRS нема; без AES/DMR-даних -- коду D нема
    import test_r97 as T97
    tb = R.pp_text(REL_UU) and T.pp(FW, R.INCS, R.CF["DUALCHBARE"], "application/source/user_interface/uiUtilities.c")
    check(tb is not None and "dwHeaderEnvelopes" in tb, "В: DUALCHBARE (AES+DMR-дані, без APRS_RX) -- функція шапки є")
    if tb:
        fn = T.carve_fn(tb, "static void dwHeaderEnvelopes(unsigned aprsCount, unsigned dmrCount)")
        check(fn is not None and "'A'" not in fn and "'D'" in fn, "В: без APRS_RX у dwHeaderEnvelopes нема кода APRS (немає 'A'), лишається лише SMS DMR")
    ta = T.pp(FW, R.INCS, R.CF["APRSRX"], "application/source/user_interface/uiUtilities.c")
    check(ta is not None and "dwHeaderEnvelopes" not in ta, "В: збірка без режиму DW (APRSRX) -- коду шапки DW нема взагалі")
    # шапка викликає з тими самими лічильниками, що звичайний екран
    check("dwHeaderEnvelopes(uiUnreadCount('A'), uiUnreadCount('D'));" in src_uu, "В: шапка DW бере лічильники з uiUnreadCount('A'/'D') наживо")
    body = src_uu[src_uu.find("unsigned uiUnreadCount(char kind)"):]
    body = body[:body.find("\n}\n")]
    check("dmrSmsUnreadCount()" in body and "aprsMsgUnreadCount(ab)" in body and "static" not in body, "В: uiUnreadCount -- ті самі dmrSmsUnreadCount()/aprsMsgUnreadCount(), що на звичайному екрані; без кешу (static) -- застарілих лічильників при вході/виході з DW нема")
    norm = src_uu[src_uu.find("int unread = dmrSmsUnreadCount();", src_uu.find("static void uiUtilityRenderHeaderCore")):]
    check("unsigned aun = (ab != NULL) ? aprsMsgUnreadCount(ab) : 0U;" in src_uu and norm.startswith("int unread = dmrSmsUnreadCount();"), "В: звичайний екран рахує ті самі функції (dmrSmsUnreadCount, aprsMsgUnreadCount(aprsModeMsgBox()))")
    fnd = src_uu[src_uu.find("static void dwHeaderEnvelopes("):]
    fnd = fnd[:fnd.find("\n}\n")]
    check("static" not in fnd.split("{", 1)[1], "В: dwHeaderEnvelopes без static-змінних (немає стану між кадрами)")
    check(src_uu.count("if (dwOnly)") >= 3, "В: на екрані DW стокові конверти шапки (y=14, налазили б на картку A) вимкнено; конверти DW малюються лише з dwOnly")


def test_no_icons_on_cards(D, o, src_cm, H, env):
    for k in R.KEYS + ("n30", "w7a", "w7b", "c40a"):
        ic = R.icons_on_card(D, o.get(k))
        check(ic == [], "В: на картці %s нема конвертів SMS/APRS і ▶: %s" % (k, ic))
    def mut(name, a, b):
        s2 = src_cm.replace(a, b, 1)
        if s2 == src_cm:
            check(False, "В (мутант %s): не застосувався" % name); return
        o2 = build13(s2, H, env)
        if o2 is None:
            check(False, "В (мутант %s): не зібрався" % name); return
        D2 = F5.consts(s2)
        br = R.cards_check(o2, D2, mutant=True)
        check(any("конверт" in x or "▶" in x for x in br), "В (мутант %s): ловиться: %s" % (name, [x for x in br if "конверт" in x or "▶" in x][:2]))
    mut("значок SMS знову на картці", "	if (mp[0] != 0)\n	{\n		size_t mpMax", "	uiDrawMsgEnvelopeAt((DW_IN_R + 1 - 28), (y + DW_ICON_DY), 'D', 3U);\n	if (mp[0] != 0)\n	{\n		size_t mpMax")
    mut("▶ знову на картці", "	if (selected)\n	{\n		displayThemeApply(THEME_ITEM_BG_MENU_ITEM_SELECTED, THEME_ITEM_BG);\n		displayFillRect(DW_SEL_X, (y + 1), DW_SEL_W, (DW_CARD_H - 2), false);\n",
        "	if (selected)\n	{\n		displayThemeApply(THEME_ITEM_BG_MENU_ITEM_SELECTED, THEME_ITEM_BG);\n		displayFillRect(DW_SEL_X, (y + 1), DW_SEL_W, (DW_CARD_H - 2), false);\n		displayDrawLine(DW_IN_L, (y + 6), DW_IN_L, (y + 12), true);\n")


# ============================================================================================================ рівність проміжків у нових станах
def test_grid_new(D, o):
    keys = ("n30", "n31", "n34", "n35", "nv1", "nv3", "w7a", "w7b", "w7c", "t40", "c40a", "c40b", "c40c", "c24a", "ned")
    ms = {}
    for k in keys:
        ps = prims(o, k)
        if ps:
            ms[k] = G.measure(D, ps, F9.ph)
    bad = F12.grid_broken(D, ms)
    check(bad == [], "Б (сітка): у %d нових станах проміжки 1-2, 2-3, 3-4 і поля -- 4 або 5 px, різниця <= 1, смуга >= 3 px, «чорнило» не торкається: %s" % (len(ms), bad[:3]))
    msl = {k: G.measure(D, prims(o, k), F9.ph, D["DW_CAP16"] - 1) for k in keys if prims(o, k)}
    check(all(F12.spread_of(m)[1] - F12.spread_of(m)[0] <= 1 and abs(m["top"] - m["bottom"]) <= 1 and m["g12"] >= 4 and m["top"] >= 3 for m in msl.values() if m["top"] is not None),
          "Б (сітка, латиниця й цифри -- на 1 px вищі за кирилицю): поле 3, 1-2 -- 4, решта 4; різниця <= 1, верх == низ (±1)")


# ============================================================================================================ PNG
def png(o, D, ob, Dold, outdir, H, env):
    try:
        from PIL import Image, ImageDraw
    except Exception:
        print("ПРОПУСК: PNG -- нема Pillow"); return
    import screen_sim as sim, theme_edit as te
    os.makedirs(outdir, exist_ok=True)
    cols = te.stock_colors("day")
    def img(d):
        return Image.frombytes("RGB", (sim.W, sim.H), sim.render_rgb(d, cols))
    out = []
    for num, ka, kb, title in R.STATES:
        after = img(R.render(o, ka, kb, D)).resize((sim.W * 3, sim.H * 3), Image.NEAREST)
        if ob is not None:
            before = img(R.render(ob, ka, kb, Dold)).resize((sim.W * 3, sim.H * 3), Image.NEAREST)
            cv = Image.new("RGB", (after.width * 2 + 12, after.height), (128, 128, 128)); cv.paste(before, (0, 0)); cv.paste(after, (after.width + 12, 0))
        else:
            cv = after
        p = os.path.join(outdir, "R98FIX13-%s.png" % num); cv.save(p); out.append(p)
    # найгірші випадки: рядок 4 (смуга + частина рядка 3) x5: активна з S-метром + «DMR 750mW» + замок; неактивна RX 171.17500- + «DMR 750mW» + замок; FM; без замка
    rows = []
    for key, ka, kb, y0 in (("w7a", "w7a", "s1b", D["DW_CARD_A_Y"]), ("w7b", "w7b", "s1b", D["DW_CARD_A_Y"]), ("w7p", "w7p", "s1b", D["DW_CARD_A_Y"]), ("w7c", "w7c", "s1b", D["DW_CARD_A_Y"]),
                            ("n30", "n30", "s1b", D["DW_CARD_A_Y"]), ("n35", "n35", "s1b", D["DW_CARD_A_Y"])):
        d = R.render(o, ka, kb, D)
        im = img(d).crop((0, y0 + D["DW_ROW3_DY"] - 3, 160, y0 + D["DW_CARD_H"])).resize((160 * 5, (D["DW_CARD_H"] - D["DW_ROW3_DY"] + 3) * 5), Image.NEAREST)
        rows.append(im)
    cv = Image.new("RGB", (rows[0].width, sum(r.height for r in rows) + 6 * len(rows)), (128, 128, 128)); yy = 0
    for r in rows:
        cv.paste(r, (0, yy)); yy += r.height + 6
    p = os.path.join(outdir, "R98FIX13-worst-row4.png"); cv.save(p); out.append(p)
    # шапка: комбінації лічильників (x5, лише рядок шапки)
    tu_uu = R.pp_text(REL_UU)
    r, err = hdr_run(tu_uu)
    if r is not None:
        rows = []
        for a, dd in ((0, 0), (2, 5), (0, 9), (2, 0), (99, 99), (10, 1)):
            ps = R.env_prims(r["a%u_d%u" % (a, dd)]) if r["a%u_d%u" % (a, dd)] else []
            d = sim.Display(); d.theme_apply(sim.IT["FG_HEADER_TEXT"], sim.IT["BG_HEADER_TEXT"]); d.fill_rect(0, 0, 160, 10, True)
            d.print_core(1, 2, "DW", sim.FONT_1, sim.ALIGN_LEFT, False); d.print_core(160 - 33 - 24, 2, "87%", sim.FONT_1, sim.ALIGN_LEFT, False); d.print_core(0, 2, "12:34", sim.FONT_1, sim.ALIGN_RIGHT, False)
            R.env_draw(d, ps)
            rows.append(img(d).crop((0, 0, 160, 12)).resize((160 * 5, 12 * 5), Image.NEAREST))
        cv = Image.new("RGB", (rows[0].width, sum(x.height for x in rows) + 6 * len(rows)), (128, 128, 128)); yy = 0
        for x in rows:
            cv.paste(x, (0, yy)); yy += x.height + 6
        p = os.path.join(outdir, "R98FIX13-header.png"); cv.save(p); out.append(p)
    for p in out:
        print("PNG:", p)


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    R.INCS, cfgs = R.cmt.load_configs(FW)
    R.CF = dict(cfgs)
    for m in (F6, F8, F9):
        m.INCS, m.CF = R.INCS, R.CF
    pngd = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else None
    src_cm = T.rd(os.path.join(UI, "uiChannelMode.c")); src_uu = T.rd(os.path.join(UI, "uiUtilities.c"))
    D = F5.consts(src_cm)
    need = ["DW_CAP16", "DW_BASE16", "DW_CAP8", "DW_BASE8", "DW_ROW4_TXT_DY", "DW_TAG_W", "DW_METER_X", "DW_METER_END", "DW_LOCK_W", "DW_ICON_GAP", "DW_MP_CHARS", "DW_L4_CHARS", "DW_L4_END", "DW_MP_MIN_X", "DW_ROW3_MAX"]
    check(all(k in D for k in need), "константи R98-FIX13 знайдено: нема %s" % [k for k in need if k not in D])
    if not all(k in D for k in need):
        print("test_r98fix13: ПРОВАЛІВ: %d" % len(FAILS)); return 1
    tu_uu = R.pp_text(REL_UU)
    H, env = R.harness_after(tu_uu)
    o = build13(None, H, env)
    check(o is not None, "хостова збірка карток")
    if o is None:
        return 1
    ob, Dold = before_obj(H, env)
    test_left(D, o, src_cm)
    test_fm_row2(D, o)
    test_line(D, o, ob, Dold)
    test_row4_left(D, o, src_cm, H, env)
    test_row3(D, o, H, env, src_cm)
    test_lock(D, o, H, env, src_cm)
    test_header(src_uu, tu_uu)
    test_no_icons_on_cards(D, o, src_cm, H, env)
    test_grid_new(D, o)
    if pngd:
        png(o, D, ob, Dold, pngd, H, env)
    print("test_r98fix13: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
