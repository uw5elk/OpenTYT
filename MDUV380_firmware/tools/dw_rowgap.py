# -*- coding: utf-8 -*-
"""dw_rowgap.py -- R98-FIX12 Б1/Б5: ВИДИМІ проміжки між рядками картки «Подвійного прийому» у моделі кадру (шрифти прошивки з font_data).
Рядки картки: 1 -- назва (8x16), 2 -- абонент/контакт/«FM частота» (8x16), 3 -- «номер TS CC TG ...» (6x8), 4 -- мітка + частота | S-метр, значки.
Метрики (виміряні, не оцінені) для кожного шрифту: cap -- верхній рядок великих літер, base -- нижній рядок літер без виносних:
  6x8:  cap 0, base 6  (виносні Щ, Ц, Д -- рядок 7);   8x16: base 12 (виносні р, у -- до 14; латиниця p, g, y, j -- до 15), cap 3 для кирилиці (А, Б, В, Ш, ...) і 2 для
  латиниці й цифр (A..Z, 0..9) -- кириличні великі на 1 px нижчі; за замовчуванням cap=3 (кирилиця), параметр cap16=2 -- те саме для латинського тексту.
Проміжок між рядками = кількість ПОРОЖНІХ піксельних рядків між базовою лінією верхнього рядка і верхом великих літер наступного;
верхнє поле = порожніх рядків між рамкою картки і верхом великих літер рядка 1; нижнє = між низом рядка 4 і рамкою.
Рядок 4 міряється за смугою (S-метр, значки -- вищі за текст на 1 px зверху й знизу), а якщо їх нема -- за текстом.
Запас виносних (clearance) -- найменша відстань за Чебишовим між «чорнилом» рядка і «чорнилом» наступного (>= 2 означає: між ними є порожній піксель)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)

CAP = {1: 0, 3: 3}
BASE = {1: 6, 3: 12}
FONT_H = {1: 8, 3: 16}


def _sim():
    import screen_sim as sim
    return sim


def text_ink(p):
    """Піксельне «чорнило» тексту-примітива (непінвертований) відносно верху картки."""
    sim = _sim()
    d = sim.Display()
    f = {1: sim.FONT_1, 2: sim.FONT_1_BOLD, 3: sim.FONT_3}.get(p["font"], sim.FONT_1)
    d.print_core(p["x"], p["y"], p["t"], f, sim.ALIGN_LEFT, False)
    return {(x, y) for y in range(sim.H) for x in range(sim.W) if d.px[y * sim.W + x] != sim.IT["BG"]}


def box_ink(b):
    return {(x, y) for y in range(b[1], b[3] + 1) for x in range(b[0], b[2] + 1)}


def arrow_ink(ps):
    """Ink стрілки відстані: трикутники, які малює прошивка (displayFillTriangle -> примітиви «t» гарнеса, рамки -- справжні координати)."""
    pts = set()
    for p in ps:
        if p["k"] == "t":
            pts |= box_ink((p["x"], p["y"], p["x"] + p["w"] - 1, p["y"] + p["h"] - 1))
    return pts


def cheb_min(a, b):
    """Найменша відстань за Чебишовим між двома множинами пікселів (None, якщо одна порожня)."""
    if not a or not b:
        return None
    best = 999
    for (x1, y1) in a:
        for (x2, y2) in b:
            dd = max(abs(x1 - x2), abs(y1 - y2))
            if dd < best:
                best = dd
                if best <= 1:
                    return best
    return best


def measure(D, ps, ph, cap16=None):
    """ps -- примітиви картки (F6.prims_of), ph -- функція підстановки справжньої кирилиці. Повертає словник метрик картки (координати відносно верху картки)."""
    ps = ph(ps)
    CAPS = dict(CAP)
    if cap16 is not None:
        CAPS[3] = cap16                             # 2 -- латинські великі літери й цифри (на 1 px вищі за кириличні)
    R1, R2, R3, R4 = D["DW_ROW1_DY"], D["DW_ROW2_DY"], D["DW_ROW3_DY"], D["DW_ROW4_DY"]
    rows = {1: set(), 2: set(), 3: set(), 4: set()}
    text = {1: None, 2: None, 3: None, 4: None}     # (cap, base) тексту рядка
    band = None                                     # (top, bottom) не-текстових елементів рядка 4
    for p in ps:
        k = p["k"]
        if k == "r" and p["w"] >= 150:
            continue                                # рамка
        if k == "f" and p["x"] == D["DW_SEL_X"] and p["w"] == D["DW_SEL_W"]:
            continue                                # смуга виділення
        if k in "tl" and p["y"] >= D["DW_ARROW_DY"] and p["y"] < R4 and p["x"] > 100:
            continue                                # стрілка -- окремо
        if k == "k":
            r = 4
            band = _union_band(band, p["y"], p["y"] + 8)
            rows[4] |= box_ink((p["x"], p["y"], p["x"] + 9, p["y"] + 8))
            continue
        if k == "T":
            if p["font"] == 3:
                r = 1 if p["y"] < R2 else 2
            elif p["y"] >= R4:
                r = 4
            else:
                r = 3
            if p["inv"]:
                continue                            # інверсний текст -- у межах власного бокса (f), окремо не рахується
            if not p["t"].strip():
                continue
            rows[r] |= text_ink(p)
            c, b = p["y"] + CAPS[p["font"]], p["y"] + BASE[p["font"]]
            old = text[r]
            text[r] = (c, b) if old is None else (min(old[0], c), max(old[1], b))
            continue
        # f, r, l: геометрія -> смуга рядка 4 (усе, що нижче за R4 - 1) або решта
        b = (p["x"], p["y"], p["x"] + p["w"] - 1, p["y"] + p["h"] - 1) if k in "fr" else (p["x"], p["y"], p["x"] + p["w"] - 1, p["y"] + p["h"] - 1)
        if p["y"] >= R4 - 1:
            if k == "f" and p["inv"] == 1 and p["x"] == D["DW_IN_L"] and p["w"] >= 60:
                continue                            # фон під S-метр (колір тла)
            rows[4] |= box_ink(b)
            band = _union_band(band, b[1], b[3])
    rows[3] |= arrow_ink(ps)
    res = {"ink": rows}
    for r in (1, 2, 3):
        res["cap%d" % r] = text[r][0] if text[r] else None
        res["base%d" % r] = text[r][1] if text[r] else None
    t4 = text[4]
    res["top4"] = t4[0] if t4 else None            # за текстом рядка 4 (мітка/частота)
    res["bot4"] = t4[1] if t4 else None
    res["band"] = band                              # смуга S-метра/значків (вища за текст на 1 px згори й знизу)
    res["text4"] = t4
    H = D["DW_CARD_H"]
    c1, b1, c2, b2, c3, b3 = res["cap1"], res["base1"], res["cap2"], res["base2"], res["cap3"], res["base3"]
    res["top"] = (c1 - 1) if c1 is not None else None
    res["g12"] = (c2 - b1 - 1) if (c2 is not None and b1 is not None) else None
    res["g23"] = (c3 - b2 - 1) if (c3 is not None and b2 is not None) else None
    res["g34"] = (res["top4"] - b3 - 1) if (res["top4"] is not None and b3 is not None) else None
    res["bottom"] = (H - 1 - res["bot4"] - 1) if res["bot4"] is not None else None
    res["g34b"] = (band[0] - b3 - 1) if (band and b3 is not None) else None            # до верху смуги (S-метр/значки)
    res["bottomb"] = (H - 1 - band[1] - 1) if band else None                          # від низу смуги до рамки
    res["c12"] = cheb_min(rows[1], rows[2])
    res["c23"] = cheb_min(rows[2], rows[3])
    res["c34"] = cheb_min(rows[3], rows[4])
    return res


def _union_band(band, a, b):
    return (a, b) if band is None else (min(band[0], a), max(band[1], b))


def fmt(m):
    def v(x):
        return "-" if x is None else str(x)
    def c(x):
        return "-" if x is None else str(x - 1)
    return "верх %s | 1-2 %s | 2-3 %s | 3-4 %s (смуга %s) | низ %s (смуга %s) || запас виносних 1/2 %s, 2/3 %s, 3/4 %s" % (
        v(m["top"]), v(m["g12"]), v(m["g23"]), v(m["g34"]), v(m["g34b"]), v(m["bottom"]), v(m["bottomb"]), c(m["c12"]), c(m["c23"]), c(m["c34"]))
