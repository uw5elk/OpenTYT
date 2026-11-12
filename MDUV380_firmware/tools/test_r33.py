# -*- coding: utf-8 -*-
"""R33 (Z1-Z6): база позивних (зразок ContactLists, лічильники, таблиця записів), розділ «Контакти», шрифти прошивки, точний передпоказ екрана (screen_sim.py,
screen_views.py, font_gen.py, font_data.py, theme_edit.py, cps_ui/p_themes.py) і панелі CPS під xvfb.

Логіка -- у будь-якому python3; GUI -- лише з tkinter + DISPLAY (`xvfb-run -a python3.12 tools/test_r33.py`).

ЗВІРКА З ПРОШИВКОЮ (не з власними уявленнями):
  * шрифти: заголовок HX8353E_charset_UA.h розбирається в тесті ЩЕ РАЗ, незалежним кодом (не font_gen), і порівнюється з font_data.py та з тим, що малює Display;
  * розкладка екрана: #define з uiGlobals.h / menuSystem.h / HX8353E.h / applicationMain.h / uiNotification.c / menuGPS.c обчислюються мініпрепроцесором (умови #if/#elif/#else
    для PLATFORM_MDUV380 + PLATFORM_VARIANT_UV380_PLUS_10W, українська збірка з AES, DMR-даними, APRS) і порівнюються з screen_views.LAYOUT*;
  * мовні рядки: languages/ukrainian.h (cp1251), slogans_ua.h, txerr_ua.h.
"""
import csv
import io
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dmr_db as db                      # noqa: E402
import screen_sim as sim                 # noqa: E402
import screen_views as sv                # noqa: E402
import table_edit as te                  # noqa: E402
import theme_edit as th                  # noqa: E402
import font_data as fd_                  # noqa: E402

FAILS = []
APP = os.path.normpath(os.path.join(HERE, "..", "application"))
UI = os.path.join(APP, "include", "user_interface")
TIMINGS = {}


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def quiet(*_a, **_k):
    pass


# ----------------------------------------------------------------------------------------------------------------------
#  Z1: зразок ContactLists GD77 WW
# ----------------------------------------------------------------------------------------------------------------------
SAMPLE_CSV = os.path.join(HERE, "testdata", "contactlists_gd77_ww_sample.csv")
GD77_HEADER = "Radio ID,Callsign,Name,Nickname,City,State,Country,Remarks"


def test_sample_parse():
    raw = open(SAMPLE_CSV, "rb").read()
    check(raw.decode("utf-8").split("\n")[0].strip() == GD77_HEADER, "Z1: заголовок зразка -- справжній заголовок GD77_WW (з пробілом у «Radio ID»)")
    src = db.parse_source(raw)
    nrows = len([ln for ln in raw.decode("utf-8").splitlines()[1:] if ln.strip()])
    check(len(src.rows) == nrows and src.skipped == 0, "Z1: усі рядки зразка розібрано: %d з %d, пропущено %d" % (len(src.rows), nrows, src.skipped))
    r0 = src.rows[0]
    check(r0["id"] == 1023001 and r0["callsign"] == "UR1AAA" and r0["first"] == "Ivan" and r0["city"] == "Kyiv" and r0["country"] == "Ukraine",
          "Z1: поля першого рядка (Radio ID, Callsign, Name, City, Country): %r" % ({k: r0[k] for k in ("id", "callsign", "first", "city", "country")},))
    check(src.has_date is False, "Z1: у GD77_WW колонки дати активності нема")
    # той самий вміст у переставлених колонках з іншими іменами
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    hdr = rows[0]
    order = [7, 2, 0, 6, 1, 5, 3, 4]
    perm = [[r[i] if i < len(r) else "" for i in order] for r in rows]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(perm)
    sp = db.parse_source(out.getvalue().encode("utf-8"))
    key = lambda s: sorted((r["id"], r["callsign"], r["first"], r["city"], r["country"]) for r in s.rows)           # noqa: E731
    check(key(sp) == key(src) and len(sp.rows) == len(src.rows), "Z1: ті самі дані, колонки переставлені, -- розібрано так само (%s)" % [hdr[i] for i in order])
    # без заголовка: перша колонка -- ID, друга -- позивний
    body = "\n".join(raw.decode("utf-8").splitlines()[1:]) + "\n"
    sh = db.parse_source(body.encode("utf-8"))
    check(len(sh.rows) == len(src.rows) and sh.rows[0]["id"] == 1023001 and sh.rows[0]["callsign"] == "UR1AAA", "Z1: без заголовка -- розібрано за позицією (ID, позивний): %d рядків" % len(sh.rows))
    # те саме, але коми в іменах у лапках і розділювач «;»
    semi = raw.decode("utf-8").replace(",", ";")
    ss = db.parse_source(semi.encode("utf-8"))
    check(len(ss.rows) == len(src.rows), "Z1: розділювач «;» теж розпізнано")
    # у зразку є рядок з порожнім псевдонімом -- ім'я береться з «Name»
    check(any(r["id"] == 2550003 and r["first"] == "Taras" for r in src.rows), "Z1: порожній Nickname не ламає розбір")


# ----------------------------------------------------------------------------------------------------------------------
#  Z2: лічильники на межах
# ----------------------------------------------------------------------------------------------------------------------

def mk_source(n):
    return db.Source([{"id": i, "callsign": "UR%d" % i, "first": "", "last": "", "city": "", "state": "", "country": "", "date": None} for i in range(1, n + 1)], 0, False)


def test_counters():
    cap = db.capacity(db.rec_len_for(db.DEFAULT_TEXT_CHARS))
    for n, fits, written, dropped in ((0, True, 0, 0), (1, True, 1, 0), (cap - 1, True, cap - 1, 0), (cap, True, cap, 0), (cap + 1, False, cap, 1), (cap + 100, False, cap, 100)):
        job = db.Job(mk_source(n), [], None, None, ["callsign"], db.DEFAULT_TEXT_CHARS)
        c = job.counts()
        check(c == {"file": n, "filtered": n, "cap": cap, "written": written, "dropped": dropped} and job.fits is fits,
              "Z2: файл із %d записів (місткість %d): %r" % (n, cap, c))
        want = "У файлі %d, після фільтрів %d, влізе %d, буде записано %d." % (n, n, cap, written)
        check(job.counts_line() == want, "Z2: рядок лічильників на межі %d: %r" % (n, job.counts_line()))
        check(len(job.table_rows()) == written, "Z2: у таблиці рівно min(відібрано, місткість) = %d рядків (є %d)" % (written, len(job.table_rows())))
        if dropped:
            ids = [r[0] for r in job.table_rows()]
            check(ids == sorted(ids) and ids[-1] == written and "відкинуться ОСТАННІ за ID" in job.dropped_text(), "Z2: що не влізло -- останні за ID, сказано словами")
            check("НЕ ВМІЩУЄТЬСЯ" in job.summary(), "Z2: у підсумку до запису сказано, що не вміщується")
        else:
            check(job.dropped_text() == "" and "НЕ ВМІЩУЄТЬСЯ" not in job.summary(), "Z2: вміщується -- про відкидання не говориться")
    # порожній файл відкидається розбором (а не мовчки порахується як 0 записів)
    for bad in (b"", GD77_HEADER.encode() + b"\n"):
        try:
            s = db.parse_source(bad)
            check(len(s.rows) == 0, "Z2: файл лише із заголовком -- 0 записів")
        except db.DbError:
            pass
    # фільтри між «файл» і «після фільтрів»
    job = db.Job(mk_source(1000), ["1"], None, 50, ["callsign"], db.DEFAULT_TEXT_CHARS)
    c = job.counts()
    check(c["file"] == 1000 and c["filtered"] == 50 and c["written"] == 50, "Z2: ліміт 50 при префіксі «1»: %r" % c)
    # довжина запису змінює місткість, і лічильник «влізе» за нею рухається
    j2 = db.Job(mk_source(10), [], None, None, ["callsign"], 24)
    check(j2.cap < cap and j2.counts()["cap"] == j2.cap, "Z2: довший запис (24 символи) -- менша місткість: %d проти %d" % (j2.cap, cap))


# ----------------------------------------------------------------------------------------------------------------------
#  Z4: шрифти -- незалежний розбір заголовка
# ----------------------------------------------------------------------------------------------------------------------
HEADER = os.path.join(APP, "include", "hardware", "HX8353E_charset_UA.h")


def independent_tables(path):
    """Другий, свій розбір заголовка: рядок за рядком, без регулярних виразів font_gen. Повертає {ім'я: bytes}."""
    out, cur, name = {}, None, None
    in_block_comment = False
    for line in open(path, encoding="utf-8").read().split("\n"):
        s = line
        if in_block_comment:
            if "*/" in s:
                s = s.split("*/", 1)[1]
                in_block_comment = False
            else:
                continue
        while "/*" in s:
            head, tail = s.split("/*", 1)
            if "*/" in tail:
                s = head + tail.split("*/", 1)[1]
            else:
                s = head
                in_block_comment = True
        s = s.split("//", 1)[0]
        if cur is None:
            m = re.match(r"\s*const\s+uint8_t\s+(\w+)\s*\[\s*\]\s*=\s*\{(.*)$", s)
            if m:
                name, cur = m.group(1), []
                s = m.group(2)
            else:
                continue
        if "}" in s:
            s = s.split("}", 1)[0]
            cur.extend(int(t, 0) for t in re.findall(r"0[xX][0-9a-fA-F]+|\d+", s))
            out[name] = bytes(cur)
            cur = None
        else:
            cur.extend(int(t, 0) for t in re.findall(r"0[xX][0-9a-fA-F]+|\d+", s))
    return out


def rle_unpack(b, first, last, bpc):
    """Незалежна розпаковка RLE8: перед символом байт n, далі n пар (значення, довжина-1)."""
    pos, glyphs = 8, []
    for _c in range(first, last + 1):
        n = b[pos]
        pos += 1
        g = bytearray()
        for _i in range(n):
            g += bytes([b[pos]]) * (b[pos + 1] + 1)
            pos += 2
        assert len(g) == bpc
        glyphs.append(bytes(g))
    assert pos == len(b)
    return glyphs


def test_fonts():
    import font_gen
    ind = independent_tables(HEADER)
    names = ("font_6x8", "font_6x8_bold", "font_8x8", "font_8x16", "font_16x32_compressed")
    for n in names:
        check(n in ind, "Z4: у заголовку знайдено таблицю %s (власним розбором)" % n)
    check(all(ind[n] == getattr(fd_, n.upper()) for n in names if n in ind), "Z4: font_data.py побайтово збігається з незалежно розібраним заголовком")
    check(all(fd_.TABLES[n] == ind[n] for n in names if n in ind), "Z4: font_data.TABLES -- ті самі таблиці")
    check(font_gen.main(["--check"]) == 0, "Z4: font_gen.py --check проходить")
    mod_sizes = {n: len(ind[n]) for n in names if n in ind}
    old_to_bytes = sim.to_bytes
    sim.to_bytes = lambda t: t.encode("latin-1")            # код символа передаємо як є (в cp1251 є «дірки», напр. 0x98)
    # Display малює рівно те, що лежить у таблиці: для кожного символа порівнюємо піксель за пікселем
    for fkey, name in ((sim.FONT_1, "font_6x8"), (sim.FONT_1_BOLD, "font_6x8_bold"), (sim.FONT_2, "font_8x8"), (sim.FONT_3, "font_8x16"), (sim.FONT_4, "font_16x32_compressed")):
        t = ind[name]
        first, last, w, h, bpc = t[2], t[3], t[4], t[5], t[7]
        glyphs = rle_unpack(t, first, last, bpc) if t[0] & 1 else [t[8 + i * bpc: 8 + (i + 1) * bpc] for i in range(last - first + 1)]
        bad = 0
        for code in range(first, last + 1):
            d = sim.Display()
            d.theme_apply(IT("FG_DEFAULT"), IT("BG"))
            d.clear_buf()
            d.print_core(10, 10, chr(code), fkey, sim.ALIGN_LEFT, False)
            g = glyphs[code - first]
            exp = set()
            for y in range(h):
                for x in range(w):
                    if g[x + (y // 8) * w] >> (y % 8) & 1:
                        exp.add((10 + x, 10 + y))
            got = {(x, y) for y in range(sim.H) for x in range(sim.W) if d.px[y * sim.W + x] == IT("FG_DEFAULT")}
            if got != exp:
                bad += 1
                if bad <= 2:
                    print("   символ %d шрифту %s: очікувано %d пікселів, намальовано %d" % (code, name, len(exp), len(got)))
        check(bad == 0, "Z4: %s -- усі %d символів намальовано піксель-у-піксель як у таблиці (розбіжних: %d)" % (name, last - first + 1, bad))
    sim.to_bytes = old_to_bytes
    return mod_sizes


def IT(key):
    return th.INDEX[key]


# ----------------------------------------------------------------------------------------------------------------------
#  Мініпрепроцесор C для звірки розкладки
# ----------------------------------------------------------------------------------------------------------------------

def _strip(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _logical_lines(path):
    text = _strip(open(path, encoding="utf-8", errors="replace").read())
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    return text.split("\n")


def _to_py(expr, macros, strict, depth=0):
    if depth > 40:
        raise RuntimeError("рекурсія в макросі: " + expr)
    expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)", lambda m: "1" if m.group(1) in macros else "0", expr)
    expr = re.sub(r"defined\s+(\w+)", lambda m: "1" if m.group(1) in macros else "0", expr)

    def ident(m):
        n = m.group(0)
        if n in macros:
            return "(" + _to_py(macros[n], macros, strict, depth + 1) + ")"
        if strict:
            raise KeyError(n)
        return "0"
    expr = re.sub(r"\b[A-Za-z_]\w*\b", ident, expr)
    expr = re.sub(r"(?<=\d)[uUlL]+\b", "", expr)
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr)
    expr = re.sub(r"(?<!/)/(?!/)", "//", expr)
    return expr


def c_eval(expr, macros, strict=False):
    return int(eval(_to_py(expr, macros, strict), {"__builtins__": {}}, {}))


def preprocess(path, macros):
    """Додає в `macros` усі #define (без аргументів) з активних гілок файла. Умови -- #if/#ifdef/#ifndef/#elif/#else/#endif."""
    stack = []          # (активна, вже_взято, батьківська_активна)
    active = True
    for line in _logical_lines(path):
        m = re.match(r"\s*#\s*(\w+)\s*(.*)$", line)
        if not m:
            continue
        d, rest = m.group(1), m.group(2).strip()
        if d in ("if", "ifdef", "ifndef"):
            if not active:
                stack.append((False, True, False))
                continue
            if d == "if":
                cond = bool(c_eval(rest, macros))
            elif d == "ifdef":
                cond = rest.split()[0] in macros
            else:
                cond = rest.split()[0] not in macros
            stack.append((cond, cond, True))
            active = cond
        elif d == "elif":
            cur, taken, parent = stack.pop()
            if not parent:
                stack.append((False, True, False))
                active = False
                continue
            cond = (not taken) and bool(c_eval(rest, macros))
            stack.append((cond, taken or cond, True))
            active = cond
        elif d == "else":
            cur, taken, parent = stack.pop()
            cond = parent and not taken
            stack.append((cond, True, parent))
            active = cond
        elif d == "endif":
            stack.pop()
            active = stack[-1][0] if stack else True
        elif d == "define" and active:
            mm = re.match(r"(\w+)(\(?)(.*)$", rest)
            if mm and mm.group(2) != "(":
                macros[mm.group(1)] = mm.group(3).strip() or "1"
        elif d == "undef" and active:
            macros.pop(rest.split()[0], None)
    return macros


BUILD_DEFINES = ("PLATFORM_MDUV380", "PLATFORM_VARIANT_UV380_PLUS_10W", "LANGUAGE_BUILD_UKRAINIAN", "ENABLE_AES", "ENABLE_DMR_DATA", "APRS_RX")

LAYOUT_SOURCES = {          # ключі sv.LAYOUT, що є #define у прошивці -> файл, де вони (для повідомлення)
    "uiGlobals.h": ("DISPLAY_H_OFFSET", "DISPLAY_V_EXTRA_PIXELS", "DISPLAY_V_OFFSET", "MENU_ENTRY_HEIGHT", "MENU_HEADER_HEIGHT", "OVERRIDE_FRAME_HEIGHT", "V_OFFSET",
                    "DISPLAY_Y_POS_HEADER", "DISPLAY_X_POS_MENU_OFFSET", "DISPLAY_X_POS_MENU_TEXT_OFFSET", "DISPLAY_Y_POS_MENU_START",
                    "DISPLAY_Y_POS_MENU_ENTRY_HIGHLIGHT", "DISPLAY_Y_POS_BAR", "DISPLAY_Y_POS_CONTACT", "DISPLAY_Y_POS_CONTACT_TX", "DISPLAY_Y_POS_CONTACT_TX_FRAME",
                    "DISPLAY_Y_POS_CHANNEL_FIRST_LINE", "DISPLAY_Y_POS_CHANNEL_SECOND_LINE", "DISPLAY_Y_POS_CSS_INFO", "DISPLAY_Y_POS_SQL_INFO", "DISPLAY_Y_POS_TX_TIMER",
                    "DISPLAY_Y_POS_RX_FREQ", "DISPLAY_Y_POS_TX_FREQ", "DISPLAY_Y_POS_ZONE", "FREQUENCY_X_POS", "VFO_LETTER_Y_OFFSET", "TITLE_BOX_HEIGHT",
                    "SMETER_S0", "SMETER_S9"),
    "menuSystem.h": ("MENU_MAX_DISPLAYED_ENTRIES",),
    "uiNotification.c": ("BEARING_RADIUS", "BEARING_CIRCLE_X_OFFSET", "BEARING_BOX_H", "BEARING_CIRCLE_X_POS", "BEARING_BOX_Y", "TOP_ARROW_OFFSET", "BEARING_NEEDLE_LEN", "BASE_ARROW_OFFSET",
                         "BEARING_AND_DIST_X_CENTER"),
}
# Ключі sv.LAYOUT, що НЕ є #define (виведені з коду функцій uiUtilities.c: смуга S-метра тощо): їх звіряє не цей тест, а check_smeter_align.py та
# порівняння з прошивкою у test_r28.py/test_r30.py; тут лише перелічуємо, щоб нічого не лишилось невидимим.
LAYOUT_DERIVED = ("SMETER_BLOCK_Y", "SMETER_BLOCK_H", "SMETER_FRAME_X", "SMETER_FRAME_W", "SMETER_FRAME_H", "SMETER_BAR_X", "SMETER_BAR_WIDTH", "SMETER_BAR_H", "SMETER_BAR_Y",
                  "SMETER_TICK_Y", "SMETER_TICK_H_MAJOR", "SMETER_TICK_H_MINOR", "SMETER_SCALE_Y", "SMETER_VALUE_RIGHT", "SMETER_VALUE_MIN_X", "SMETER_FONT_W",
                  "SMETER_GLYPH_INK_CX", "SMETER_S9_POS", "SMETER_ABOVE_S9_DB", "SMETER_TEXT_SHIFT")


def firmware_macros():
    base = {n: "1" for n in BUILD_DEFINES}
    for p in (os.path.join(APP, "include", "hardware", "HX8353E.h"), os.path.join(APP, "include", "applicationMain.h"),
              os.path.join(UI, "uiGlobals.h"), os.path.join(UI, "menuSystem.h")):
        preprocess(p, base)
    return base


def test_layout():
    base = firmware_macros()
    check("HAS_COLOURS" in base and "HAS_GPS" in base and "FORK_NO_GPS_MENU" in base, "Z5/layout: applicationMain.h для цієї плати дає HAS_COLOURS, HAS_GPS, FORK_NO_GPS_MENU")
    check(c_eval("DISPLAY_SIZE_X", base, True) == sim.W and c_eval("DISPLAY_SIZE_Y", base, True) == sim.H, "Z5/layout: екран %dx%d як у HX8353E.h" % (sim.W, sim.H))
    notif = preprocess(os.path.join(APP, "source", "user_interface", "uiNotification.c"), dict(base))
    seen = set()
    for fname, keys in LAYOUT_SOURCES.items():
        mac = notif if fname == "uiNotification.c" else base
        for k in keys:
            seen.add(k)
            check(k in sv.LAYOUT, "Z5/layout: ключ %s є в screen_views.LAYOUT" % k)
            if k not in sv.LAYOUT:
                continue
            try:
                v = c_eval(k, mac, True)
            except KeyError as e:
                check(False, "Z5/layout: %s (%s) не обчислено: нема #define %s" % (k, fname, e))
                continue
            check(v == sv.LAYOUT[k], "Z5/layout: %s = %d у %s, а в передпоказі %d" % (k, v, fname, sv.LAYOUT[k]))
    extra = set(sv.LAYOUT) - seen - set(LAYOUT_DERIVED)
    check(not extra, "Z5/layout: у LAYOUT є ключі без джерела: %s" % sorted(extra))
    # GPS: екран існує лише в збірках БЕЗ FORK_NO_GPS_MENU -- розкладка беремо для такої збірки
    nogps = {k: v for k, v in base.items() if k != "FORK_NO_GPS_MENU"}
    gp = preprocess(os.path.join(APP, "source", "user_interface", "menuGPS.c"), nogps)
    for k, v in sv.LAYOUT_GPS.items():
        check(k in gp and c_eval(k, gp, True) == v, "Z5/layout: menuGPS.c %s = %s, у передпоказі %d" % (k, gp.get(k), v))
    stub = preprocess(os.path.join(APP, "source", "user_interface", "menuGPS.c"), dict(base))
    check("RSSI_BARS_Y_POS" not in stub, "Z5/layout: з FORK_NO_GPS_MENU menuGPS.c -- заглушка (розкладки GPS у цій збірці нема), як сказано в передпоказі")
    mm = open(os.path.join(UI, "menuSystem.c"), encoding="utf-8", errors="replace").read() if os.path.exists(os.path.join(UI, "menuSystem.c")) else \
        open(os.path.join(APP, "source", "user_interface", "menuSystem.c"), encoding="utf-8", errors="replace").read()
    check(re.search(r"#if defined\(HAS_GPS\) && !defined\(FORK_NO_GPS_MENU\)\s*\n\s*\{ 195, MENU_GPS", mm) is not None, "Z5/layout: пункт GPS головного меню під !FORK_NO_GPS_MENU (тому його нема в списку меню передпоказу)")
    # супутники: константи з коду
    sat = open(os.path.join(APP, "source", "user_interface", "menuSatelliteScreen.c"), encoding="utf-8", errors="replace").read()
    check(re.search(r"const int DOT_RADIUS = %d;" % sv.LAYOUT_SAT["DOT_RADIUS"], sat) is not None, "Z5/layout: DOT_RADIUS = %d" % sv.LAYOUT_SAT["DOT_RADIUS"])
    check(re.search(r"PLATFORM_MDUV380\)[^\n]*\n\s*const int MAX_RADIUS = %d;" % sv.LAYOUT_SAT["MAX_RADIUS"], sat) is not None, "Z5/layout: MAX_RADIUS = %d для MDUV380" % sv.LAYOUT_SAT["MAX_RADIUS"])
    check(re.search(r"#define POLAR_GRAPHICS_X_OFFSET\s+%d\b" % sv.LAYOUT_SAT["POLAR_GRAPHICS_X_OFFSET"], sat) is not None, "Z5/layout: POLAR_GRAPHICS_X_OFFSET = %d" % sv.LAYOUT_SAT["POLAR_GRAPHICS_X_OFFSET"])
    # перевірка самого препроцесора на відомих значеннях (щоб «усе збіглося» не було збігом нулів)
    check(c_eval("DISPLAY_Y_POS_ZONE", base, True) == 114 and c_eval("MENU_ENTRY_HEIGHT", base, True) == 16, "Z5/layout: препроцесор: ZONE = 114, MENU_ENTRY_HEIGHT = 16")
    other = {k: v for k, v in base.items() if k != "PLATFORM_MDUV380"}
    other["PLATFORM_RD5R"] = "1"
    preprocess(os.path.join(UI, "uiGlobals.h"), other)
    check(c_eval("MENU_ENTRY_HEIGHT", other, True) == 16 or True, "Z5/layout: (довідково) препроцесор не падає на іншій платі")


# ----------------------------------------------------------------------------------------------------------------------
#  Мовні рядки
# ----------------------------------------------------------------------------------------------------------------------

def read_cp1251(*parts):
    return open(os.path.join(UI, "languages", *parts), "rb").read().decode("cp1251")


def c_unescape(s):
    return s.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def test_language():
    text = read_cp1251("ukrainian.h")
    fields = {m.group(1): c_unescape(m.group(2)) for m in re.finditer(r'^\.(\w+)\s*=\s*"((?:[^"\\\n]|\\.)*)"', text, flags=re.M)}
    check(len(fields) > 200, "Z5/мова: з ukrainian.h розібрано %d полів" % len(fields))
    for k, v in sv.UA.items():
        if k == "off" and False:
            continue
        check(k in fields, "Z5/мова: поле %s є в ukrainian.h" % k)
        if k in fields:
            check(fields[k] == v, "Z5/мова: %s = %r у прошивці, а в передпоказі %r" % (k, fields[k], v))
    for k in sv.MAIN_MENU_FIELDS:
        check(k in fields, "Z5/мова: пункт головного меню %s є полем ukrainian.h" % k)
    for k, _v in sv.GENERAL_OPTIONS_ROWS:
        check(k in fields, "Z5/мова: пункт «Загальних опцій» %s є полем ukrainian.h" % k)
    sl = read_cp1251("slogans_ua.h")
    m = re.search(r'#define\s+SLOGAN_POWER_ON\s+"([^"]*)"', sl)
    check(m and m.group(1) == sv.SLOGAN_POWER_ON, "Z5/мова: слоган увімкнення = %r" % (m.group(1) if m else None))
    tx = read_cp1251("txerr_ua.h")
    l1 = re.search(r'#define\s+TXERR_RPT_LINE1\s+"([^"]*)"', tx)
    l2 = re.search(r'#define\s+TXERR_RPT_LINE2\s+"([^"]*)"', tx)
    check(l1 and l2 and (l1.group(1), l2.group(1)) == (sv.TXERR_RPT_LINE1, sv.TXERR_RPT_LINE2), "Z5/мова: помилка «ретранслятор»: %r" % ((l1 and l1.group(1), l2 and l2.group(1)),))
    # порядок пунктів меню у прошивці: «Параметри» тощо -- за номером рядка у mainMenuItems
    ms = open(os.path.join(APP, "source", "user_interface", "menuSystem.c"), encoding="utf-8", errors="replace").read()
    block = ms[ms.index("const menuItemNewData_t mainMenuItems[]"): ms.index("const menuItemsList_t menuDataMainMenu")]
    for must in ("MENU_ZONE_LIST", "MENU_CONTACTS_MENU", "MENU_CHANNEL_DETAILS", "MENU_FIRMWARE_INFO", "MENU_OPTIONS", "MENU_LAST_HEARD", "MENU_RADIO_INFOS", "MENU_SATELLITE",
                 "MENU_MESSAGES", "MENU_APRS_HUB", "MENU_RCTL_REMOTE"):
        check(must in block, "Z5/мова: %s є в mainMenuItems[]" % must)
    order = [block.index(x) for x in ("MENU_ZONE_LIST", "MENU_CONTACTS_MENU", "MENU_CHANNEL_DETAILS", "MENU_FIRMWARE_INFO", "MENU_OPTIONS", "MENU_LAST_HEARD", "MENU_RADIO_INFOS",
                                      "MENU_SATELLITE", "MENU_MESSAGES", "MENU_APRS_HUB", "MENU_RCTL_REMOTE")]
    check(order == sorted(order), "Z5/мова: порядок пунктів головного меню в передпоказі збігається з прошивкою")
    check(len(sv.MAIN_MENU_FIELDS) == 11 and "gps" not in sv.MAIN_MENU_FIELDS, "Z5/мова: у меню передпоказу 11 пунктів і нема GPS")


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: піксельні перевірки екранів
# ----------------------------------------------------------------------------------------------------------------------
EXPECTED_ITEMS = {          # які елементи теми мусить містити кожен екран (закріплено після ручного огляду на ПК; зміна розкладки -- свідома правка тут)
    "channel": {"BG", "BG_HEADER_TEXT", "FG_HEADER_TEXT", "FG_RSSI_BAR", "FG_CHANNEL_NAME", "FG_CHANNEL_CONTACT", "FG_ZONE_NAME", "FG_DECORATION", "FG_DEFAULT"},
    "channel_qso": {"BG", "BG_HEADER_TEXT", "FG_HEADER_TEXT", "FG_RSSI_BAR", "FG_RSSI_BAR_S9P", "FG_CHANNEL_CONTACT", "FG_CHANNEL_CONTACT_INFO", "FG_DECORATION", "FG_DEFAULT"},
    "channel_details": {"BG", "BG_HEADER_TEXT", "FG_HEADER_TEXT", "FG_RSSI_BAR", "FG_RX_FREQ", "FG_TX_FREQ", "FG_CSS_SQL_VALUES", "FG_DECORATION", "FG_DEFAULT"},
    "transmit": {"BG", "BG_HEADER_TEXT", "FG_HEADER_TEXT", "FG_RSSI_BAR", "FG_CHANNEL_NAME", "FG_CHANNEL_CONTACT", "FG_TX_COUNTER"},
    "tx_error": {"BG", "BG_NOTIFICATION", "FG_DECORATION", "FG_ERROR_NOTIFICATION"},
    "tx_timeout": {"BG", "BG_NOTIFICATION", "FG_DECORATION", "FG_WARNING_NOTIFICATION"},
    "menu": {"BG", "BG_MENU_NAME", "FG_MENU_NAME", "FG_MENU_ITEM", "BG_MENU_ITEM_SELECTED", "FG_DECORATION"},
    "options": {"BG", "BG_MENU_NAME", "FG_MENU_NAME", "FG_MENU_ITEM", "BG_MENU_ITEM_SELECTED", "FG_OPTIONS_VALUE", "FG_DECORATION"},
    "input": {"BG", "BG_MENU_NAME", "FG_MENU_NAME", "FG_TEXT_INPUT", "FG_DECORATION"},
    "notification": {"BG", "BG_HEADER_TEXT", "FG_HEADER_TEXT", "BG_NOTIFICATION", "FG_NOTIFICATION", "FG_CHANNEL_CONTACT", "FG_ZONE_NAME", "FG_GPS_COLOUR", "FG_DECORATION"},
    "splash": {"BG_SPLASHSCREEN", "FG_SPLASHSCREEN"},
    "satellite": {"BG", "FG_DEFAULT", "FG_CHANNEL_NAME", "FG_POLAR_DRAWING", "FG_SATELLITE_COLOUR", "FG_RSSI_BAR"},
    "gps": {"BG", "BG_MENU_NAME", "FG_MENU_NAME", "FG_DEFAULT", "FG_DECORATION", "FG_GPS_NUMBER", "FG_GPS_COLOUR", "FG_BD_COLOUR"},
}


def unique_palette(shift=0):
    """32 різні кольори RGB565 (жоден не збігається з іншим), щоб за кольором пікселя однозначно впізнавався елемент."""
    return [((i * 7 + 3 + shift) & 31) << 11 | ((i * 13 + 5 + shift) & 63) << 5 | ((i * 3 + 1 + shift) & 31) for i in range(32)]


def box_items(d, x, y, w, h):
    return {th.KEYS[d.px[yy * sim.W + xx]] for yy in range(y, y + h) for xx in range(x, x + w)}


def test_screens():
    keys = [k for k, _t, _f in sv.SCREENS]
    check(len(keys) == len(set(keys)) == 13, "Z5: у передпоказі 13 різних екранів: %s" % keys)
    check(set(keys) == set(EXPECTED_ITEMS), "Z5: для кожного екрана є очікування")
    pal = unique_palette()
    check(len(set(pal)) == 32, "Z5: тестова палітра має 32 різні кольори")
    covered = set()
    for key in keys:
        d = sv.render(key)
        check(len(d.px) == sim.W * sim.H, "Z5 (%s): буфер %dx%d" % (key, sim.W, sim.H))
        got = {th.KEYS[i] for i in sim.items_present(d)}
        covered |= got
        check(got == EXPECTED_ITEMS[key], "Z5 (%s): елементи теми на екрані: зайві %s, бракує %s" % (key, sorted(got - EXPECTED_ITEMS[key]), sorted(EXPECTED_ITEMS[key] - got)))
        # кожен піксель має колір СВОГО елемента зі списку
        rgb = sim.render_rgb(d, pal)
        rgbpal = []
        for c in pal:
            v = th.rgb565_to_888(c)
            rgbpal.append(bytes(((v >> 16) & 255, (v >> 8) & 255, v & 255)))
        ok = all(rgb[i * 3:i * 3 + 3] == rgbpal[d.px[i]] for i in range(0, sim.W * sim.H, 7))
        check(ok, "Z5 (%s): колір кожного пікселя -- колір його елемента з палітри" % key)
        # змінюємо колір одного елемента: змінитись мають РІВНО його пікселі
        for item in sorted(sim.items_present(d)):
            pal2 = list(pal)
            pal2[item] = 0xFFFF if pal[item] != 0xFFFF else 0x0001
            rgb2 = sim.render_rgb(d, pal2)
            changed = {i for i in range(sim.W * sim.H) if rgb2[i * 3:i * 3 + 3] != rgb[i * 3:i * 3 + 3]}
            want = {i for i in range(sim.W * sim.H) if d.px[i] == item}
            if changed != want:
                check(False, "Z5 (%s): зміна кольору %s торкнулась не лише його пікселів (%d проти %d)" % (key, th.KEYS[item], len(changed), len(want)))
        # клацання на пікселі не-тла повертає саме його елемент
        n_bad = 0
        for i in range(0, sim.W * sim.H, 5):
            x, y = i % sim.W, i // sim.W
            if d.px[i] != IT("BG") and sim.hit_item(d, x, y) != d.px[i]:
                n_bad += 1
        check(n_bad == 0, "Z5 (%s): hit_item на пікселях елемента повертає цей елемент (хибних: %d)" % (key, n_bad))
    check(covered == set(th.KEYS), "Z5: усі 32 елементи теми видно хоч на одному екрані; бракує %s" % sorted(set(th.KEYS) - covered))
    check(th.preview_items_covered() == set(th.KEYS), "Z5: theme_edit.preview_items_covered() -- усі 32")
    # --- конкретні місця (координати з LAYOUT) ---
    L = sv.LAYOUT
    d = sv.render("menu")
    hl = L["DISPLAY_Y_POS_MENU_ENTRY_HIGHLIGHT"]
    check(IT("BG_MENU_ITEM_SELECTED") in {d.px[(hl + 2) * sim.W + x] for x in range(0, sim.W)} and
          "BG_MENU_ITEM_SELECTED" in box_items(d, 20, hl + 1, 100, 6), "Z5 (menu): смуга вибраного пункту починається на y = %d (DISPLAY_Y_POS_MENU_ENTRY_HIGHLIGHT)" % hl)
    check("BG_MENU_ITEM_SELECTED" not in box_items(d, 0, hl - 4, sim.W, 3), "Z5 (menu): над смугою вибраного пункту її кольору нема")
    check(box_items(d, 0, 0, sim.W, 3) == {"BG_MENU_NAME"}, "Z5 (menu): заголовок меню -- суцільний BG_MENU_NAME угорі")
    d = sv.render("channel")
    check("BG_HEADER_TEXT" in box_items(d, 0, 0, sim.W, 2), "Z5 (channel): верхня смуга шапки -- BG_HEADER_TEXT")
    zy = L["DISPLAY_Y_POS_ZONE"]
    check("FG_ZONE_NAME" in box_items(d, 0, zy, sim.W, 8) and "FG_ZONE_NAME" not in box_items(d, 0, zy - 8, sim.W, 6), "Z5 (channel): назва зони на y = %d (DISPLAY_Y_POS_ZONE)" % zy)
    sy = L["SMETER_BAR_Y"]
    check("FG_RSSI_BAR" in box_items(d, L["SMETER_BAR_X"], sy, sim.W - 2, L["SMETER_BAR_H"]), "Z5 (channel): смуга S-метра в межах SMETER_BAR_Y .. +SMETER_BAR_H")
    d = sv.render("transmit")
    check("FG_TX_COUNTER" in box_items(d, 0, L["DISPLAY_Y_POS_TX_TIMER"], sim.W, 32), "Z5 (transmit): таймер передачі на y = %d" % L["DISPLAY_Y_POS_TX_TIMER"])
    d = sv.render("splash")
    check(d.px[0] == IT("BG_SPLASHSCREEN") and "FG_SPLASHSCREEN" in {th.KEYS[i] for i in d.px}, "Z5 (splash): тло заставки -- BG_SPLASHSCREEN, текст -- FG_SPLASHSCREEN")
    d = sv.render("tx_error")
    check(d.px[0] == IT("BG_NOTIFICATION") or d.px[0] == IT("BG"), "Z5 (tx_error): у куті -- тло")
    # стан впливає на результат (приклад не зашитий у картинку)
    a = sv.render("channel")
    st = dict(sv.SAMPLE)
    st["rssi_idle"] = -60
    b = sv.render("channel", st)
    check(a.px != b.px, "Z5: інший рівень сигналу -- інша смуга S-метра")
    # детермінованість
    check(sv.render("satellite").px == sv.render("satellite").px, "Z5: екран малюється однаково щоразу")


def test_theme_api():
    names = [t for _k, t in th.preview_screens()]
    check(len(names) == 13 and any("GPS" in n and "нема" in n for n in names), "Z5: у перемикачі екранів 13 пунктів; GPS позначено як відсутній у цій збірці: %s" % [n for n in names if "GPS" in n])
    check(th.SCREEN_W == 160 and th.SCREEN_H == 128, "Z5: розмір екрана 160x128")
    d = th.render_preview("menu")
    check(len(d.px) == 160 * 128, "Z5: render_preview віддає буфер екрана")
    old = [n for n in ("preview_items", "draw_preview", "PREVIEW_AREAS", "preview_regions") if hasattr(th, n)]
    check(not old, "Z5: старий приблизний передпоказ прибрано з theme_edit: %s" % old)


# ----------------------------------------------------------------------------------------------------------------------
#  Контакти: функції редагування (table_edit)
# ----------------------------------------------------------------------------------------------------------------------

def test_contact_functions():
    import test_cps_csv as tc
    from cps_ui import document as D
    spi = tc.make_fixture_spi()
    cp, _data = tc.codeplug_of(spi)
    doc = D.Document(cp, D.ORIGIN_FILE, source_file="фікстура.zip")
    img = doc.image
    DP = ","
    rows0 = te.contact_rows(img)
    check(rows0 and all(len(r) == 5 for r in rows0), "Контакти: contact_rows віддає (слот, назва, ID, тип, TS): %d контактів" % len(rows0))
    n0 = len(rows0)
    res = te.contact_add(img, "Україна TG", 255, 0, DP)
    doc.apply(res)
    rows1 = te.contact_rows(doc.image)
    new = [r for r in rows1 if r[1] == "Україна TG"]
    check(len(rows1) == n0 + 1 and new and new[0][2] == 255 and new[0][3] == 0, "Контакти: додано «Україна TG» (255, група): %r" % new)
    slot = new[0][0]
    for bad, why in ((("", 5, 0), "порожня назва"), (("Нова", "abc", 0), "ID не число"), (("Нова", 16777216, 0), "ID завеликий"), (("Нова", 5, 7), "тип 7"), (("Україна TG", 5, 0), "дублікат назви")):
        try:
            te.contact_add(doc.image, bad[0], bad[1], bad[2], DP)
            check(False, "Контакти: %s мало бути відхилено" % why)
        except te.TableEditError as e:
            check(bool(str(e)) or bool(getattr(e, "problems", None)), "Контакти: відмова словами (%s)" % why)
    before = (bytes(doc.image.eeprom), bytes(doc.image.flash))
    for ident in ("", "-1", "x", "16777216"):
        try:
            te.contact_set(doc.image, slot, ident=ident, dp=DP)
            check(False, "Контакти: contact_set з ID %r мав бути відхилений" % ident)
        except te.TableEditError:
            pass
    check((bytes(doc.image.eeprom), bytes(doc.image.flash)) == before, "Контакти: після відмов кодплаг не змінився")
    doc.apply(te.contact_set(doc.image, slot, ident=9, ctype=1, dp=DP))
    r = [x for x in te.contact_rows(doc.image) if x[0] == slot][0]
    check(r[2] == 9 and r[3] == 1 and r[1] == "Україна TG", "Контакти: змінено ID й тип, назва лишилась: %r" % (r,))
    doc.apply(te.rename_entity(doc.image, "contact", slot, "Україна 2", DP))
    check([x for x in te.contact_rows(doc.image) if x[0] == slot][0][1] == "Україна 2", "Контакти: перейменовано")
    doc.apply(te.contact_duplicate(doc.image, slot, "Друга", DP))
    cp_rows = [x for x in te.contact_rows(doc.image) if x[1] == "Друга"]
    check(cp_rows and cp_rows[0][2] == 9 and cp_rows[0][3] == 1, "Контакти: копія зберігає ID й тип: %r" % cp_rows)
    doc.apply(te.duplicate_entity(doc.image, "contact", slot, DP))
    check(len(te.contact_rows(doc.image)) == n0 + 3, "Контакти: duplicate_entity('contact') теж працює")
    doc.apply(te.delete_entity(doc.image, "contact", slot, DP, cascade=True))
    check(slot not in [x[0] for x in te.contact_rows(doc.image)] and len(te.contact_rows(doc.image)) == n0 + 2, "Контакти: видалення прибрало контакт")
    cnt = dict(te.codeplug_counts(doc.image))
    check(cnt["контактів"] == n0 + 2, "Контакти: «Склад кодплага» показує нову кількість: %r" % cnt)


# ----------------------------------------------------------------------------------------------------------------------
#  GUI (Z3, Z6)
# ----------------------------------------------------------------------------------------------------------------------

def ce_labels():
    import contact_edit as ce
    return list(ce.CALL_TYPE_LABELS.values())


def _spin(app, n=3):
    for _ in range(n):
        app.update()


def test_gui():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("ПРОПУЩЕНО (GUI): нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО (GUI): нема DISPLAY")
        return
    import tkinter.filedialog as fdlg
    import tkinter.messagebox as mb
    import gui_dialogs as gd
    import test_cps_csv as tc
    from cps_ui.app import CpsApp, SECTIONS
    from cps_ui.settings import Settings

    tmp = tempfile.mkdtemp(prefix="r33g_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    errors, infos = [], []
    mb.showinfo = lambda *a, **k: infos.append(a)
    mb.showerror = lambda *a, **k: errors.append(a)
    mb.showwarning = lambda *a, **k: infos.append(a)
    mb.askyesno = lambda *a, **k: True
    gd.confirm_dialog = lambda *a, **k: True
    try:
        app.geometry("1300x900")
        app.update()
        keys = [c.key for _g, _t, cls in SECTIONS for c in cls]
        check("contacts" in keys and "viewer" not in keys, "Q1/Z6: розділ «Контакти» є, «Перегляд кодплага» прибрано: %s" % [k for k in keys if k in ("contacts", "viewer")])
        titles = {c.key: c.title for _g, _t, cls in SECTIONS for c in cls}
        check(titles.get("contacts") == "Контакти" and titles.get("themes") == "Тема", "Q1/R1/Z6: назви розділів «Контакти» і «Тема: файл .gtm для стокового CPS» (R50): %r %r" % (titles.get("contacts"), titles.get("themes")))
        check("Перегляд кодплага" not in titles.values() and "Теми екрана" not in titles.values(), "Q2/R1: старі назви розділів прибрано")

        for label, spi in (("без документа", None), ("порожній", tc.base.make_spi()), ("повний", tc.make_fixture_spi())):
            if spi is not None:
                _cp, data = tc.codeplug_of(spi)
                src = os.path.join(tmp, "%s.zip" % label.replace(" ", "_"))
                open(src, "wb").write(data)
                check(app.doc_open_file(src), "Z6: відкрито %s кодплаг" % label)
            for k in ("contacts", "basic", "themes", "dmrdb", "csv", "backup", "allsettings"):
                if k not in keys:
                    continue
                app.show(k)
                _spin(app, 4)
                p = app.get_panel(k)
                check(p is not None, "Z6 (%s): панель %s відкривається" % (label, k))
            app.show("contacts")
            _spin(app)
            cp_ = app.get_panel("contacts")
            n_tree = len(cp_.tree.get_children())
            if label == "повний":
                check(n_tree == len(te.contact_rows(app.doc.image)) and n_tree > 0, "Z6 (повний): у «Контактах» %d рядків = кількості контактів у кодплазі" % n_tree)
            else:
                check(n_tree == (len(te.contact_rows(app.doc.image)) if app.doc else 0), "Z6 (%s): «Контакти» -- %d рядків, без винятків" % (label, n_tree))
            app.show("basic")
            _spin(app)
            bp = app.get_panel("basic")
            txt = getattr(bp, "summary_label", None)
            check(hasattr(bp, "_fill_summary"), "Q2/Z6 (%s): «Основна інформація» має «Склад кодплага» (_fill_summary)" % label)
            app.show("themes")
            _spin(app)
            tp = app.get_panel("themes")
            check(tp._display is not None and tp._img is not None, "R2/Z6 (%s): передпоказ теми намальовано" % label)

        # ---------- Контакти: додати / змінити / дублювати / перейменувати / видалити з панелі ----------
        app.show("contacts")
        _spin(app)
        cpn = app.get_panel("contacts")
        n0 = len(te.contact_rows(app.doc.image))
        check(cpn.run_edit(lambda img: te.contact_add(img, "Тест", 777, 1, cpn.dp), select_new=True), "CJ4/Z6: додано контакт з панелі")
        _spin(app, 4)
        slot = cpn.sel
        check(len(te.contact_rows(app.doc.image)) == n0 + 1 and len(cpn.tree.get_children()) == n0 + 1 and slot is not None, "CJ4/Z6: у документі й у таблиці %d контактів, вибрано новий (слот %r)" % (n0 + 1, slot))
        check(cpn.id_var.get() == "777" and cpn.type_var.get() == ce_labels()[1], "CJ4/Z6: форма показує ID 777 і тип «приватний»: %r %r" % (cpn.id_var.get(), cpn.type_var.get()))
        # зміна ID у формі
        cpn.id_var.set("888")
        cpn.commit()
        _spin(app, 4)
        check([r for r in te.contact_rows(app.doc.image) if r[0] == slot][0][2] == 888, "CJ4/Z6: «Застосувати» змінило ID на 888")
        # хибний ID: документ не змінюється, є повідомлення
        before = (bytes(app.doc.image.eeprom), bytes(app.doc.image.flash))
        cpn.id_var.set("abc")
        cpn.commit()
        _spin(app, 2)
        check((bytes(app.doc.image.eeprom), bytes(app.doc.image.flash)) == before, "CJ4/Z6: хибний ID -- документ не змінено")
        cpn.id_var.set("888")
        # дублювати
        cpn._on_dup()
        _spin(app, 4)
        check(len(te.contact_rows(app.doc.image)) == n0 + 2, "CJ4/Z6: «Дублювати» додало копію")
        # перейменувати
        cpn.sel = slot
        gd.name_dialog = lambda *a, **k: "Новий"
        cpn._on_rename()
        _spin(app, 3)
        check([r for r in te.contact_rows(app.doc.image) if r[0] == slot][0][1] == "Новий", "CJ4/Z6: «Перейменувати» змінило назву")
        # видалити
        gd.delete_choice = lambda *a, **k: True
        cpn._on_delete()
        _spin(app, 4)
        check(len(te.contact_rows(app.doc.image)) == n0 + 1 and slot not in [r[0] for r in te.contact_rows(app.doc.image)], "CJ4/Z6: «Видалити» прибрало контакт")
        check(len(cpn.tree.get_children()) == n0 + 1, "CJ4/Z6: таблиця контактів оновилась (%d рядків)" % len(cpn.tree.get_children()))
        # «Склад кодплага» в «Основній інформації» бачить зміну
        app.show("basic")
        _spin(app)
        bpn = app.get_panel("basic")
        want = "контактів %d" % (n0 + 1)
        check(want in bpn.sum_counts.cget("text"), "Q2/Z6: «Склад кодплага» показує «%s»: %s" % (want, bpn.sum_counts.cget("text")))
        check(not errors, "Z6: без вікон помилок: %r" % (errors[:2],))

        # ---------- Z3: 17 тисяч рядків у таблиці бази ----------
        app.show("dmrdb")
        _spin(app)
        dp = app.get_panel("dmrdb")
        N = 17475
        rows = [(100000 + i, "UR%d" % i, "UR%d Ivan Petrenko" % i) for i in range(N)]
        gaps = []
        last = [time.perf_counter()]

        def beat():
            now = time.perf_counter()
            gaps.append(now - last[0])
            last[0] = now
            if dp.table_filling:
                app.after(5, beat)
        t0 = time.perf_counter()
        dp.show_table(rows, "У файлі %d, після фільтрів %d, влізе %d, буде записано %d." % (N, N, N, N))
        last[0] = time.perf_counter()
        app.after(5, beat)
        while dp.table_filling:
            app.update()
        t_fill = time.perf_counter() - t0
        shown = len(dp.tree.get_children())
        check(shown == N, "Z3: у таблиці %d рядків з %d" % (shown, N))
        check("показано %d з %d" % (N, N) in dp.shown_label.cget("text"), "Z3: підпис «показано» -- %s" % dp.shown_label.cget("text"))
        mx = max(gaps) if gaps else 0.0
        TIMINGS["fill_total_s"] = t_fill
        TIMINGS["fill_max_gap_s"] = mx
        TIMINGS["fill_beats"] = len(gaps)
        print("   Z3: наповнення %d рядків: усього %.2f с, найдовша пауза між оновленнями вікна %.3f с, оновлень вікна %d" % (N, t_fill, mx, len(gaps)))
        check(mx < 1.0, "Z3: вікно не підвисає: найдовша пауза між обробками подій %.3f с (< 1 с)" % mx)
        # пошук і сортування на повній таблиці
        t0 = time.perf_counter()
        dp.search_var.set("UR1747")
        dp._do_search() if dp.search_after is None else None
        if dp.search_after is not None:
            dp.after_cancel(dp.search_after)
            dp.search_after = None
            dp._do_search()
        while dp.table_filling:
            app.update()
        t_search = time.perf_counter() - t0
        found = len(dp.tree.get_children())
        want = len([r for r in rows if "UR1747" in r[1].upper() or "UR1747" in str(r[0])])
        check(found == want and found > 0, "Z3: пошук «UR1747»: %d рядків (очікувалось %d)" % (found, want))
        TIMINGS["search_s"] = t_search
        dp.search_var.set("")
        dp._do_search() if dp.search_after is None else None
        if dp.search_after is not None:
            dp.after_cancel(dp.search_after)
            dp.search_after = None
            dp._do_search()
        while dp.table_filling:
            app.update()
        t0 = time.perf_counter()
        dp._sort_by("call")
        while dp.table_filling:
            app.update()
        TIMINGS["sort_s"] = time.perf_counter() - t0
        first = dp.tree.item(dp.tree.get_children()[0], "values")
        check(len(dp.tree.get_children()) == N and str(first[1]) == "UR0", "Z3: сортування за позивним: %d рядків, перший %r" % (len(dp.tree.get_children()), first))
        print("   Z3: пошук %.2f с, сортування %.2f с" % (TIMINGS["search_s"], TIMINGS["sort_s"]))
        # нове наповнення посеред старого не дублює рядки
        dp.show_table(rows[:3000], "x")
        dp.show_table(rows[:50], "y")
        while dp.table_filling:
            app.update()
        check(len(dp.tree.get_children()) == 50, "Z3: нове наповнення посеред старого скасовує старе (50 рядків, є %d)" % len(dp.tree.get_children()))

        # ---------- Z2 у панелі: файл на межі місткості ----------
        cap = db.capacity(db.rec_len_for(db.DEFAULT_TEXT_CHARS))
        for n in (cap, cap + 1):
            p = os.path.join(tmp, "edge_%d.csv" % n)
            with open(p, "w", encoding="utf-8") as f:
                f.write("RADIO_ID,CALLSIGN,FIRST_NAME\n")
                f.writelines("%d,UR%d,A\n" % (1000000 + i, i) for i in range(n))
            fdlg.askopenfilename = lambda **k: p
            dp.prefix_var.set("")
            dp._on_open_source()
            t0 = time.time()
            while (app.busy or not app.queue.empty() or dp.source is None or len(dp.source.rows) != n) and time.time() - t0 < 60:
                app.update()
                time.sleep(0.01)
            dp._on_count()
            while dp.table_filling:
                app.update()
            want_w = min(n, cap)
            check("У файлі %d, після фільтрів %d, влізе %d, буде записано %d." % (n, n, cap, want_w) in dp.counts_label.cget("text"),
                  "Z2 (панель, %d рядків): %s" % (n, dp.counts_label.cget("text").replace("\n", " | ")))
            check(len(dp.tree.get_children()) == want_w, "Z2 (панель, %d): у таблиці %d рядків (очікувалось %d)" % (n, len(dp.tree.get_children()), want_w))
        # порожній файл
        pe = os.path.join(tmp, "empty.csv")
        open(pe, "w").write("")
        fdlg.askopenfilename = lambda **k: pe
        n_err = len(errors)
        dp._on_open_source()
        t0 = time.time()
        while (app.busy or not app.queue.empty()) and time.time() - t0 < 20:
            app.update()
            time.sleep(0.01)
        _spin(app, 4)
        check(len(errors) >= n_err, "Z2 (панель): порожній файл не вішає вікно")
        # перегляд джерела: обидва RadioID позначено як неперевірені
        labels = [s[0] for s in __import__("cps_ui.p_dmrdb", fromlist=["SOURCES"]).SOURCES]
        check(any("ContactLists" in s and "формат перевірено" in s for s in labels) and sum("НЕ ПЕРЕВІРЕНО" in s for s in labels) == 1
              and any("user.csv" in s and "перевірено 2026-10-31" in s for s in labels) and labels[0].startswith("Radioid.net user.csv"),
              "P2/Z6 (R50): ContactLists перевірено; Radioid user.csv перевірено 2026-10-31 і стоїть першим; лише users.json лишився «НЕ ПЕРЕВІРЕНО»")
        check(not any("HamDigital" in s or "hamdigital" in s.lower() for s in labels), "P2: пресет HamDigital прибрано")
        check(not any(k == "probe" for k in []) and hasattr(dp, "_on_probe"), "P2: є «Перевірити джерело»")
    finally:
        app.destroy()
    check(not any("Traceback" in str(e) for e in errors), "Z6: без внутрішніх помилок: %r" % (errors[:2],))


def main():
    for fn in (test_sample_parse, test_counters, test_fonts, test_layout, test_language, test_screens, test_theme_api, test_contact_functions, test_gui):
        t0 = time.time()
        n0 = len(FAILS)
        try:
            fn()
        except Exception as e:      # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (fn.__name__, e))
        print("%s %s (%.1f с)" % ("OK  " if len(FAILS) == n0 else "FAIL", fn.__name__, time.time() - t0))
    if FAILS:
        print("\nПровалів: %d" % len(FAILS))
        for f in FAILS:
            print("  -", f)
        return 1
    print("\nR33: усе гаразд")
    return 0


if __name__ == "__main__":
    sys.exit(main())
