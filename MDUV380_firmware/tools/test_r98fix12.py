#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R98-FIX12 (хост): мітка RX/TX без заливки і РІВНІ ВИДИМІ проміжки між рядками карток «Подвійного прийому».
  А  мітка «RX»/«TX» -- звичайний текст 6x8 без фону, кольором решти дрібного тексту (FG_CHANNEL_NAME), x=7..24, далі частота (x=25..78) або S-метр (11 сегментів 4x9
     крок 5, теж x=25..78, два останні червоні, значки з x=95 вільні). Піксельна модель (шрифт прошивки з font_data, СПРАВЖНІ dualRowTag()/dualMeterRow()/dualRenderRow()):
     літери «R», «X», «T» -- рівно за бітмапами шрифту, між ними порожній стовпчик (не зливаються), без заливки, 1:1 і 3x; контраст до фону не менший, ніж у решти
     дрібного тексту (стокові теми «день» і «ніч»); мутанти «заливка повернулась», «мітка зсунута на 1 px», «S-метр 5/6 заходить на значки».
  Б  проміжки між рядками міряються у ПІКСЕЛЯХ (tools/dw_rowgap.py): порожні рядки від базової лінії верхнього рядка до верху великих літер наступного; верхнє поле --
     від рамки до верху великих літер рядка 1, нижнє -- від низу тексту рядка 4 до рамки. У всіх 22 станах гарнесу (чергування, прийом DMR/FM на A і B, виклик зі стрілкою,
     неактивні картки, VFO зі значками, набір цифр, довгі назви, порожня картка): усі п'ять величин -- 4 або 5 px, найбільша відмінність <= 1 px; верхнє поле == нижнє;
     смуга S-метра/значків лишає >= 3 px до сусідніх рядків і рамки; «чорнило» сусідніх рядків ніде не торкається (>= 1 порожній піксель). Метрики шрифту (cap/base) --
     ВИМІРЯНІ за бітмапами шрифту прошивки і дорівнюють DW_CAP16/DW_BASE16/DW_CAP8/DW_BASE8. Для кожної пари гліфів (cp1251) -- клас торкань виносних до рядка 2.
     «До» -- той самий гарнес на коді бази (R98-FIX11): проміжки нерівні (7/4/2), тест це бачить. Мутанти: «рядок 1 зсунуто на 2 px вгору», «рядок 3 притиснуто до рядка 4»,
     «верхнє поле вдвічі більше». Перевірки під час збірки прошивки (typedef dwGapsEven/dwRow4Band/dwTagFitsBeforeMeter/dwMeterClearOfIcons) -- gcc -fsyntax-only на мутантах.
  PNG: `--png КАТАЛОГ` -- шість станів «до/після» 3x (з лініями cap/базова і чисті) і збільшена мітка RX/TX.
Запуск: python3 tools/test_r98fix12.py [--png КАТАЛОГ]"""
import os, re, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import test_r97 as T  # noqa
import test_r98fix5 as F5  # noqa
import test_r98fix6 as F6  # noqa
import test_r98fix8 as F8  # noqa
import test_r98fix9 as F9  # noqa
import test_r98fix11 as R  # noqa
import dw_rowgap as G  # noqa

FAILS = []; N = [0]
APP = T.APP; FW = T.FW
UI = os.path.join(APP, "source", "user_interface")
REL_CM = R.REL_CM
BASE = "7e8ed05"      # R98-FIX11 (HEAD на початку R98-FIX12) -- «до»


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m); print("ПРОВАЛ: " + m)


def font_rows(font, ch):
    """Рядки з «чорнилом» гліфа за СИРИМИ байтами шрифту (незалежно від print_core)."""
    import screen_sim as sim
    f = sim.FONTS[font]; g = f.glyph(ch.encode("cp1251")[0] - f.first)
    return {gy for gx in range(f.w) for gy in range(f.h) if (g[gx + (gy // 8) * f.w] >> (gy % 8)) & 1}


def font_ink(font, ch):
    import screen_sim as sim
    f = sim.FONTS[font]; g = f.glyph(ch.encode("cp1251")[0] - f.first)
    return {(gx, gy) for gx in range(f.w) for gy in range(f.h) if (g[gx + (gy // 8) * f.w] >> (gy % 8)) & 1}


def build(src_cm, H, env):
    """Гарнес карток для (зміненого) тексту uiChannelMode.c; None -- не зібралось."""
    tu = R.pp_text(REL_CM, src_cm)
    return R.run_cards(tu, H, env) if tu else None


def measure_all(D, o, cap16=None):
    out = {}
    for k in F9.KEYS:
        ps = F6.prims_of(o.get(k))
        if ps:
            out[k] = G.measure(D, ps, F9.ph, cap16)
    return out


def spread_of(m):
    v = [m[n] for n in ("top", "g12", "g23", "g34", "bottom") if m[n] is not None]
    return (min(v), max(v)) if v else None


def grid_broken(D, ms):
    """Перелік порушень рівності проміжків за станами (порожній -- усе гаразд)."""
    bad = []
    for k, m in ms.items():
        if m["top"] is None:
            continue
        lo, hi = spread_of(m)
        if hi - lo > 1 or lo < 4:
            bad.append((k, "проміжки %s" % (G.fmt(m).split("||")[0].strip(),)))
        if m["top"] is not None and m["bottom"] is not None and abs(m["top"] - m["bottom"]) > 1:
            bad.append((k, "поле зверху %s != знизу %s" % (m["top"], m["bottom"])))
        for n in ("g34b", "bottomb"):
            if m[n] is not None and m[n] < 3:
                bad.append((k, "смуга рядка 4: %s = %s < 3" % (n, m[n])))
        for n in ("c12", "c23", "c34"):
            if m[n] is not None and m[n] < 2:
                bad.append((k, "«чорнило» рядків торкається (%s = %s)" % (n, m[n])))
    return bad


# ============================================================================================================ А
def test_tag(D, o, src_cm, H, env):
    import screen_sim as sim, theme_edit as te
    R4 = D["DW_ROW4_DY"]; T4 = D["DW_ROW4_TXT_DY"]; X0 = D["DW_IN_L"]
    check(D["DW_TAG_W"] == 3 * 6 and D["DW_METER_X"] == X0 + D["DW_TAG_W"] == 25, "А1: «RX » = 3 символи 6x8 = 18 px (x=%d..%d), далі x=%d" % (X0, X0 + 17, D["DW_METER_X"]))
    check(D["DW_METER_END"] - D["DW_METER_X"] == 9 * 6 and D["DW_METER_SEGS"] == 11 and D["DW_METER_HOT"] == 2,
          "А1: S-метр -- 11 сегментів, 2 останні червоні, ширина 54 px = ширина частоти з 9 символів (x=%d..%d)" % (D["DW_METER_X"], D["DW_METER_END"] - 1))
    mpx = D["DW_IN_R"] + 1 - D["DW_LOCK_W"] - D["DW_ICON_GAP"] - D["DW_MP_CHARS"] * 6
    check(D["DW_METER_END"] + D["DW_ICON_GAP"] <= mpx, "А1: dwMeterClearOfIcons (R98-FIX13) -- S-метр (до x=%d) не заходить на «DMR 750mW» (з x=%d) і замок" % (D["DW_METER_END"] - 1, mpx))
    keys = (("s1a", "p6a"), ("s2a", "DMR"), ("s2b", "FM"), ("s4b", "VFO"), ("s3a", "FM"), ("p6b", "DMR"))
    stock = {v: te.stock_colors(v) for v in ("day", "night")}
    def lum(c565):
        r = ((c565 >> 11) & 31) * 255 // 31; g = ((c565 >> 5) & 63) * 255 // 63; b = (c565 & 31) * 255 // 31
        f = lambda v: (v / 255 / 12.92) if v / 255 <= 0.03928 else (((v / 255) + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    for var, cols in stock.items():
        lf, lb = lum(cols[sim.IT["FG_CHANNEL_NAME"]]), lum(cols[sim.IT["BG"]])
        ratio = (max(lf, lb) + 0.05) / (min(lf, lb) + 0.05)
        check(ratio >= 4.5, "А2: контраст мітки (FG_CHANNEL_NAME) до фону картки у стоковій темі «%s» -- %.1f:1 (>= 4,5:1), як у решти дрібного тексту (той самий елемент теми)" % (var, ratio))
    seen = 0
    for ka, kb in (("s1a", "s1b"), ("s2a", "s2b"), ("s3a", "s3b"), ("s4a", "s4b"), ("p6a", "p6b")):
        d = R.render(o, ka, kb, D)
        for (key, y0) in ((ka, D["DW_CARD_A_Y"]), (kb, D["DW_CARD_B_Y"])):
            tags = [p for p in F6.prims_of(o.get(key)) if p["k"] == "T" and p["x"] == X0 and p["y"] == R4 + T4 and p["font"] == 1 and p["t"] in ("RX", "TX")]
            if not tags:
                continue
            tag = tags[0]["t"]; seen += 1
            band_y = y0 + R4
            pts = {(x, y) for y in range(band_y, band_y + D["DW_ROW4_H"]) for x in range(X0, X0 + D["DW_TAG_W"]) if d.px[y * sim.W + x] != sim.IT["BG"]}
            exp = set()
            for i, ch in enumerate(tag):
                exp |= {(X0 + i * 6 + gx, y0 + R4 + T4 + gy) for (gx, gy) in font_ink(sim.FONT_1, ch)}
            check(pts == exp, "А2: мітка «%s» (%s) -- рівно піксели гліфів шрифту 6x8 у x=%d, y=%d (без заливки): зайвих %d, бракує %d" % (tag, key, X0, band_y + T4, len(pts - exp), len(exp - pts)))
            check(all(d.px[y * sim.W + x] == sim.IT["FG_CHANNEL_NAME"] for (x, y) in pts), "А2: мітка «%s» (%s) -- кольором FG_CHANNEL_NAME, як рядок 3" % (tag, key))
            # літери не зливаються: між гліфами 1 порожній стовпчик
            cols = sorted({x for x, _ in pts})
            check(all((c + 1) in cols or (c + 1) == cols[-1] + 1 or (c + 1 - X0) % 6 == 5 for c in cols[:-1]), "А2: літери мітки «%s» (%s) без зливання" % (tag, key))
            check((X0 + 5) not in cols and (X0 + 11) not in cols, "А2: між літерами мітки «%s» (%s) -- порожній стовпчик (x=%d, %d)" % (tag, key, X0 + 5, X0 + 11))
            # 3x: компоненти зв'язності
            comp = _components({(x * 3 + dx, y * 3 + dy) for (x, y) in pts for dx in range(3) for dy in range(3)})
            comp1 = _components(pts)
            check(comp1 == 2 and comp == 2, "А2: «%s» (%s) -- дві окремі літери і в масштабі 1:1 (%d), і при 3x (%d)" % (tag, key, comp1, comp))
            # контраст «чорнила» до фону -- піксель мітки відрізняється від фону картки
            check(len({d.px[y * sim.W + x] for (x, y) in pts} | {sim.IT["BG"]}) == 2, "А2: мітка (%s) -- лише колір тексту на фоні картки" % key)
    check(seen >= 8, "А2: перевірено міток у кадрах: %d (>= 8)" % seen)
    # f4: частота починається там, де в активної -- S-метр
    ps = F6.prims_of(o.get("p6a"))
    f4 = [p for p in ps if p["k"] == "T" and p["y"] == R4 + T4 and p["x"] == D["DW_METER_X"]]
    check(len(f4) == 1, "А1: частота неактивної картки -- з x=%d (там, де в активної починається S-метр)" % D["DW_METER_X"])
    # S-метр: два останні сегменти червоні при сильному сигналі (s3a)
    ps = F6.prims_of(o.get("s3a")) + F6.prims_of(o.get("s2a"))
    hot = [p for p in ps if p["k"] == "f" and p["inv"] == 0 and p["fg"] == "FG_RSSI_BAR_S9P"]
    check(len(hot) >= 2, "А1: сегменти «понад S9» (червоні) -- у сильному сигналі: %d" % len(hot))
    # мутанти
    def mut(name, a, b, pat):
        s2 = src_cm.replace(a, b, 1)
        if s2 == src_cm:
            check(False, "А3 (мутант %s): не застосувався" % name); return
        o2 = build(s2, H, env)
        D2 = F5.consts(s2)
        bad = []
        if o2 is None:
            bad = ["збірка"]
        else:
            try:
                br = R.cards_check(o2, D2, mutant=True)
            except Exception as e:  # noqa: BLE001
                br = ["виняток %s" % e]
            bad = [x for x in br if re.search(pat, x)]
        check(bool(bad), "А3 (мутант %s): ловиться: %s" % (name, bad[:2]))
    mut("заливка повернулась", "	displayPrintCore(DW_IN_L, (my + DW_ROW4_TXT_DY), tag, FONT_SIZE_1, TEXT_ALIGN_LEFT, false);",
        "	displayFillRect(DW_IN_L, my, 13, DW_ROW4_H, false);\n	displayPrintCore((DW_IN_L + 1), (my + DW_ROW4_TXT_DY), tag, FONT_SIZE_1, TEXT_ALIGN_LEFT, true);", "А|В")
    mut("мітка зсунута на 1 px", "displayPrintCore(DW_IN_L, (my + DW_ROW4_TXT_DY), tag,", "displayPrintCore(DW_IN_L, (my + DW_ROW4_TXT_DY + 1), tag,", "А|В")
    mut("мітка іншого кольору", "displayThemeApply(THEME_ITEM_FG_CHANNEL_NAME, THEME_ITEM_BG);\n	displayPrintCore(DW_IN_L, (my + DW_ROW4_TXT_DY), tag,", "displayThemeApply(THEME_ITEM_FG_DECORATION, THEME_ITEM_BG);\n	displayPrintCore(DW_IN_L, (my + DW_ROW4_TXT_DY), tag,", "А|В")


def _components(pts):
    pts = set(pts); n = 0
    while pts:
        n += 1
        st = [pts.pop()]
        while st:
            x, y = st.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in pts:
                        pts.discard(q); st.append(q)
    return n


# ============================================================================================================ Б
def typedef_block(src, defs=""):
    """Рядки констант DW_* і typedef-перевірок uiChannelMode.c (для gcc -fsyntax-only)."""
    a = src.index("#define DW_CARD_X")
    b = src.index("typedef char dwRow4Band")
    b = src.index("\n", b) + 1
    return "#define DISPLAY_Y_POS_BAR 10\n" + defs + src[a:b]


def compiles(code):
    d = tempfile.mkdtemp(prefix="r98f12_")
    try:
        c = os.path.join(d, "t.c"); open(c, "w", encoding="utf-8").write(code)
        return subprocess.run(["gcc", "-fsyntax-only", "-w", c], capture_output=True).returncode == 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_grid(D, o, src_cm, H, env):
    import screen_sim as sim
    # Б1: метри шрифту -- виміряні, не оцінені
    CYR = "АБВГЕЖЗИКЛМНОПРСТУХЧШЬЮЯ"; LAT = "ABCDEFGHIJKLMNOPRSTUVWXYZ0123456789"
    cap16 = {min(font_rows(sim.FONT_3, c)) for c in CYR}; lat16 = {min(font_rows(sim.FONT_3, c)) for c in LAT}
    base16 = {max(font_rows(sim.FONT_3, c)) for c in CYR + LAT}
    cap8 = {min(font_rows(sim.FONT_1, c)) for c in CYR + LAT}; base8 = {max(font_rows(sim.FONT_1, c)) for c in CYR + LAT}
    check((cap16, base16, cap8, base8) == ({D["DW_CAP16"]}, {D["DW_BASE16"]}, {D["DW_CAP8"]}, {D["DW_BASE8"]}) and lat16 == {D["DW_CAP16"] - 1},
          "Б1: метри шрифту, виміряні за бітмапами прошивки: 8x16 cap кирилиці=%s, латиниці й цифр=%s, base=%s; 6x8 cap=%s base=%s -- дорівнюють DW_CAP16/BASE16/CAP8/BASE8 (%s)" %
          (cap16, lat16, base16, cap8, base8, (D["DW_CAP16"], D["DW_BASE16"], D["DW_CAP8"], D["DW_BASE8"])))
    check(max(max(font_rows(sim.FONT_3, c)) for c in "рупфЩЦ") <= D["DW_BASE16"] + 2 and max(max(font_rows(sim.FONT_3, c)) for c in "gjpqy") == D["DW_BASE16"] + 3,
          "Б1: виносні -- кирилиця р, у, ф, Щ, Ц до базової +2, латиниця g, j, p, q, y -- +3")
    ms = measure_all(D, o)
    check(len(ms) >= 20, "Б4: стани гарнесу з картками: %d (>= 20)" % len(ms))
    # Б2: рівність у всіх станах
    bad = grid_broken(D, ms)
    check(bad == [], "Б2/Б4: у всіх %d станах -- проміжки 1-2, 2-3, 3-4 і поля зверху/знизу рівні (4 або 5 px, різниця <= 1), верх == низ, смуга >= 3 px, «чорнило» не торкається: %s" % (len(ms), bad[:3]))
    vals = {n: sorted({m[n] for m in ms.values() if m[n] is not None}) for n in ("top", "g12", "g23", "g34", "bottom")}
    check(vals == {"top": [4], "g12": [5], "g23": [4], "g34": [4], "bottom": [4]}, "Б2: сталі проміжки (текст кирилицею) у всіх станах: %s" % vals)
    # той самий вимір для латинського тексту (великі літери й цифри на 1 px вищі): поле 3, 1-2 -- 4
    msl = measure_all(D, o, cap16=D["DW_CAP16"] - 1)
    vl = {n: sorted({m[n] for m in msl.values() if m[n] is not None}) for n in ("top", "g12", "g23", "g34", "bottom")}
    check(vl == {"top": [3], "g12": [4], "g23": [4], "g34": [4], "bottom": [4]}, "Б2: проміжки для латинського тексту: поле 3, 1-2 -- 4, решта 4: %s" % vl)
    check(all(spread_of(m)[1] - spread_of(m)[0] <= 1 and abs(m["top"] - m["bottom"]) <= 1 for m in msl.values() if m["top"] is not None), "Б2: латинський текст -- різниця між проміжками й полями <= 1 px, верх == низ (±1)")
    check((D["DW_GAP_12"], D["DW_GAP_23"], D["DW_GAP_34"], D["DW_GAP_TOP"], D["DW_GAP_BOT"]) == (5, 4, 4, 4, 4), "Б3: константи DW_GAP_* (1-2, 2-3, 3-4, верх, низ) = 5/4/4/4/4")
    # Б3: «чорнило» стрілки і значків -- не ближче 1 px (c34 >= 2 у станах зі стрілкою)
    arrows = [k for k in ms if G.arrow_ink(F6.prims_of(o.get(k)))]
    check(len(arrows) >= 2, "Б4: стани зі стрілкою відстані: %s" % arrows)
    for k in arrows:
        m = ms[k]
        ai = G.arrow_ink(F6.prims_of(o.get(k)))
        ys = [y for _, y in ai]
        c = (min(ys) + max(ys)) / 2.0; tc = D["DW_ROW3_DY"] + (D["DW_CAP8"] + D["DW_BASE8"]) / 2.0
        check(abs(c - tc) <= 1.0, "Б4: стрілка відстані (%s) по центру рядка 3: центр %.1f, рядка %.1f" % (k, c, tc))
    # Б5: виносні: класи торкань за повною таблицею cp1251 (рядок 1 -> рядок 2 з вертикальним зсувом клітинок DW_ROW2_DY - DW_ROW1_DY)
    dy = D["DW_ROW2_DY"] - D["DW_ROW1_DY"]
    chars = [bytes([c]).decode("cp1251") for c in range(33, 256) if bytes([c]).decode("cp1251", errors="replace") != "\ufffd"]
    rows = {}
    for c in chars:
        r = font_rows(sim.FONT_3, c)
        if r:
            rows[c] = (min(r), max(r))
    touch = {(u, l) for u in rows for l in rows if rows[l][0] + dy - rows[u][1] <= 1}
    typical = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,:-+/ _") | set("АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЬЮЯабвгдежзийклмнопрстуфхцчшщьюяІіЄє")
    tt = {(u, l) for (u, l) in touch if u in typical and l in typical}
    check(all(l == "f" for _, l in tt),
          "Б5: серед типових символів (латиниця, цифри, кирилиця без Й, Ї, Ґ) торкання можливе лише латинських виносних (Q g j p q y , _) до «f» (на 1 px вища за великі): %s" % sorted(tt)[:6])
    check(all(u in "Qgjpqy,_" for u, _ in tt), "Б5: кириличні виносні (р, у, ф, Щ, Ц, д) типових символів НЕ торкаються рядка 2: %s" % sorted({u for u, _ in tt}))
    worst = [("Домашній HotSpot", "TG Ukraine 255"), ("Домашній HotSpot", "Щука Цап"), ("Папуга", "UR5EQF Bogdan"), ("Робочий", "Щука Цап"), ("Щука Цап", "145,500 Ukraine"),
             ("Папуга", "Папуга, Щука"), ("Domashni Gypsy", "R2 Київ 145,7")]
    for a, b in worst:
        d = sim.Display()
        d.print_core(D["DW_ROW1_TX"], D["DW_ROW1_DY"], a, sim.FONT_3, sim.ALIGN_LEFT, False)
        i1 = {(x, y) for y in range(sim.H) for x in range(sim.W) if d.px[y * sim.W + x] != sim.IT["BG"]}
        d = sim.Display()
        d.print_core(D["DW_IN_L"], D["DW_ROW2_DY"], b, sim.FONT_3, sim.ALIGN_LEFT, False)
        i2 = {(x, y) for y in range(sim.H) for x in range(sim.W) if d.px[y * sim.W + x] != sim.IT["BG"]}
        c = G.cheb_min(i1, i2)
        check(c is not None and c >= 2, "Б5: виносні «%s» над «%s» не торкаються (запас %s порожній піксель)" % (a, b, None if c is None else c - 1))
    # Б7: мутанти за константами
    def mut(name, subs, pat=None):
        s2 = src_cm
        for a, b in subs:
            if s2.count(a) != 1:
                check(False, "Б7 (мутант %s): рядок не знайдено: %s" % (name, a[:50])); return
            s2 = s2.replace(a, b, 1)
        o2 = build(s2, H, env)
        D2 = F5.consts(s2)
        br = grid_broken(D2, measure_all(D2, o2)) if o2 else ["збірка"]
        check(br != [], "Б7 (мутант %s): ловиться: %s" % (name, br[:1]))
        ok = compiles(typedef_block(s2))
        return ok
    mut("рядок 1 зсунуто на 2 px вгору", [("#define DW_ROW1_DY       2 ", "#define DW_ROW1_DY       0 ")])
    mut("рядок 3 притиснуто до рядка 4", [("#define DW_ROW3_DY       34 ", "#define DW_ROW3_DY       37 ")])
    mut("верхнє поле вдвічі більше", [("#define DW_ROW1_DY       2 ", "#define DW_ROW1_DY       6 ")])
    # перевірки під час збірки прошивки
    base_ok = compiles(typedef_block(src_cm))
    check(base_ok, "Б8: константи й typedef-перевірки сітки/мітки/S-метра збираються (gcc -fsyntax-only)")
    for name, subs in (("рядок 1 зсунуто на 2 px вгору", [("#define DW_ROW1_DY       2 ", "#define DW_ROW1_DY       0 ")]),
                       ("рядок 3 притиснуто до рядка 4", [("#define DW_ROW3_DY       34 ", "#define DW_ROW3_DY       37 ")]),
                       ("верхнє поле вдвічі більше", [("#define DW_ROW1_DY       2 ", "#define DW_ROW1_DY       6 ")]),
                       ("S-метр 5/6 заходить на значки", [("#define DW_METER_SEG_W   4 ", "#define DW_METER_SEG_W   5 "), ("#define DW_METER_STEP    5", "#define DW_METER_STEP    6")]),
                       ("мітка вужча за 3 символи", [("#define DW_TAG_W         18 ", "#define DW_TAG_W         13 ")])):
        s2 = src_cm
        for a, b in subs:
            if s2.count(a) != 1:
                check(False, "Б8 (мутант %s): рядок не знайдено: %s" % (name, a[:50])); break
            s2 = s2.replace(a, b, 1)
        else:
            check(not compiles(typedef_block(s2)), "Б8 (мутант %s): збірка прошивки впала б на typedef-перевірці" % name)


# ============================================================================================================ PNG
def lines_png(d, D, y0s, ms_by_card):
    pass


def png(o, D, png_dir, H, env):
    try:
        from PIL import Image, ImageDraw
    except Exception:
        print("ПРОПУСК: PNG -- нема Pillow"); return
    import screen_sim as sim, theme_edit as te
    os.makedirs(png_dir, exist_ok=True)
    cols = te.stock_colors("day")
    ob = Dold = None
    if subprocess.run(["git", "-C", FW, "cat-file", "-e", BASE + "^{commit}"], capture_output=True).returncode == 0:
        old = subprocess.run(["git", "-C", FW, "show", BASE + ":MDUV380_firmware/" + REL_CM], capture_output=True)
        if old.returncode == 0:
            so = old.stdout.decode("utf-8"); Dold = F5.consts(so)
            ob = R.run_cards(R.pp_text(REL_CM, so), H, env)
    def img(d):
        return Image.frombytes("RGB", (sim.W, sim.H), sim.render_rgb(d, cols))
    def guides(im, Dx, scale, ka_key_ps):
        dr = ImageDraw.Draw(im)
        for (ps, y0) in ka_key_ps:
            if not ps:
                continue
            m = G.measure(Dx, ps, F9.ph)
            for name, yy, colr in (("cap1", m["cap1"], (220, 0, 0)), ("base1", m["base1"], (0, 90, 255)), ("cap2", m["cap2"], (220, 0, 0)), ("base2", m["base2"], (0, 90, 255)),
                                   ("cap3", m["cap3"], (220, 0, 0)), ("base3", m["base3"], (0, 90, 255)), ("cap4", m["top4"], (220, 0, 0)), ("base4", m["bot4"], (0, 90, 255))):
                if yy is None:
                    continue
                Y = (y0 + yy) * scale + (0 if colr[0] == 220 else scale - 1)
                dr.line([(2 * scale, Y), (157 * scale, Y)], fill=colr, width=1)
    out = []
    for num, ka, kb, title in R.STATES:
        def pair(oo, Dx, lines):
            d = R.render(oo, ka, kb, Dx)
            im = img(d).resize((sim.W * 3, sim.H * 3), Image.NEAREST)
            if lines:
                guides(im, Dx, 3, [(F6.prims_of(oo.get(ka)), Dx["DW_CARD_A_Y"]), (F6.prims_of(oo.get(kb)), Dx["DW_CARD_B_Y"])])
            return im
        for lines, suffix in ((False, ""), (True, "-lines")):
            after = pair(o, D, lines)
            if ob is not None:
                before = pair(ob, Dold, lines)
                cv = Image.new("RGB", (after.width * 2 + 12, after.height), (128, 128, 128))
                cv.paste(before, (0, 0)); cv.paste(after, (after.width + 12, 0))
            else:
                cv = after
            p = os.path.join(png_dir, "R98FIX12-%s%s.png" % (num, suffix))
            cv.save(p); out.append(p)
    # збільшена мітка: неактивна DMR, неактивна FM, неактивна VFO, активна з S-метром (x4, смуга рядка 4 + частина рядка 3)
    rows = []
    for key, y0 in (("p6a", D["DW_CARD_A_Y"]), ("s2b", D["DW_CARD_B_Y"]), ("s4b", D["DW_CARD_B_Y"]), ("s2a", D["DW_CARD_A_Y"])):
        ka, kb = (key, "s1b") if key.endswith("a") else ("s1a", key)
        d = R.render(o, ka, kb, D)
        im = img(d).crop((0, y0 + D["DW_ROW3_DY"] - 3, 160, y0 + D["DW_CARD_H"])).resize((160 * 5, (D["DW_CARD_H"] - D["DW_ROW3_DY"] + 3) * 5), Image.NEAREST)
        rows.append(im)
    cv = Image.new("RGB", (rows[0].width, sum(r.height for r in rows) + 6 * len(rows)), (128, 128, 128))
    yy = 0
    for r in rows:
        cv.paste(r, (0, yy)); yy += r.height + 6
    p = os.path.join(png_dir, "R98FIX12-RX.png"); cv.save(p); out.append(p)
    for p in out:
        print("PNG:", p)


def main():
    if not shutil.which("gcc"):
        print("ПРОПУСК: gcc нема"); return 0
    R.INCS, cfgs = R.cmt.load_configs(FW)
    R.CF = dict(cfgs)
    F6.INCS, F6.CF = R.INCS, R.CF
    F8.INCS, F8.CF = R.INCS, R.CF
    F9.INCS, F9.CF = R.INCS, R.CF
    pngd = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else None
    src_cm = T.rd(os.path.join(UI, "uiChannelMode.c"))
    D = F5.consts(src_cm)
    need = ["DW_CAP16", "DW_BASE16", "DW_CAP8", "DW_BASE8", "DW_ROW4_TXT_DY", "DW_GAP_12", "DW_GAP_23", "DW_GAP_34", "DW_GAP_TOP", "DW_GAP_BOT", "DW_TAG_W", "DW_METER_X", "DW_METER_END"]
    check(all(k in D for k in need), "константи R98-FIX12 знайдено: нема %s" % [k for k in need if k not in D])
    if not all(k in D for k in need):
        print("test_r98fix12: ПРОВАЛІВ: %d" % len(FAILS)); return 1
    tu_uu = R.pp_text(R.REL_UU)
    H, env = R.harness_after(tu_uu)
    o = build(None, H, env)
    check(o is not None, "хостова збірка карток")
    if o is None:
        return 1
    test_tag(D, o, src_cm, H, env)
    test_grid(D, o, src_cm, H, env)
    if pngd:
        png(o, D, pngd, H, env)
    print("test_r98fix12: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0]))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
