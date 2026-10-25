# -*- coding: utf-8 -*-
"""R28 (Z1-Z4): теми рації в CPS (tools/theme_edit.py + cps_ui/p_themes.py) і каскадне видалення APRS-слота (table_edit kind="aprs").
Логіка -- у будь-якому python3; GUI -- лише з tkinter + DISPLAY (`xvfb-run -a python3.12 tools/test_r28.py`; інакше частину з Tk пропущено й сказано про це).
Рації нема: флеш рації підмінено словником байтів (FakeFlash) під тими самими функціями aes_key_store, що викликає custom_data -- тож РЕАЛЬНИЙ
алгоритм пошуку/створення блоків (custom_data.py) відпрацьовує в тесті."""
import os
import random
import re
import struct
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import aes_key_store as aks              # noqa: E402
import codeplug_edit as ced              # noqa: E402
import cps_csv as cc                     # noqa: E402
import custom_data as cd                 # noqa: E402
import table_edit as te                  # noqa: E402
import theme_edit as th                  # noqa: E402
import test_rnext as tr                  # noqa: E402
import test_cps_csv as tc                # noqa: E402

FAILS = []
APP = os.path.join(HERE, "..", "application")
DP = ","


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def read_text(*parts):
    with open(os.path.join(APP, *parts), encoding="utf-8", errors="replace") as f:
        return f.read()


# ----------------------------------------------------------------------------------------------------------------------
#  Зв'язок з прошивкою: усе, на що спирається формат, -- ті самі числа, що в C
# ----------------------------------------------------------------------------------------------------------------------

def _enum_body(text, last_name, typedef_name=None):
    m = re.search(r"typedef enum\s*\{(.*?)\}\s*%s\s*;" % re.escape(typedef_name), text, re.S) if typedef_name else None
    return m.group(1) if m else None


def test_firmware_constants():
    hdr = read_text("include", "hardware", "HX8353E.h")
    body = _enum_body(hdr, None, "themeItem_t")
    check(body is not None, "T1: enum themeItem_t знайдено в HX8353E.h")
    names = re.findall(r"^\s*THEME_ITEM_(\w+)", body, re.M)
    mx = names.index("MAX")
    check(names[:mx] == list(th.KEYS), "T1: порядок і склад 32 елементів у theme_edit == themeItem_t (є: %d, у C: %d)" % (len(th.KEYS), mx))
    check(mx == th.ITEM_COUNT == 32 and th.BLOCK_LEN == 64, "T1: THEME_ITEM_MAX = 32 -> блок 64 байти")

    cph = read_text("include", "functions", "codeplug.h")
    m = re.search(r"typedef enum\s*\{(.*?)\}\s*CodeplugCustomDataType_t", cph, re.S)
    vals, cur, val = {}, -1, None
    for line in m.group(1).splitlines():
        mm = re.match(r"\s*CODEPLUG_CUSTOM_DATA_TYPE_(\w+)\s*(?:=\s*(0x[0-9A-Fa-f]+|\d+))?\s*,?", line)
        if not mm:
            continue
        cur = int(mm.group(2), 0) if mm.group(2) else cur + 1
        vals[mm.group(1)] = cur
    check(vals.get("THEME_DAY") == th.TYPE_THEME_DAY == 4 and vals.get("THEME_NIGHT") == th.TYPE_THEME_NIGHT == 5,
          "T1: типи блоків THEME_DAY=4 / THEME_NIGHT=5: %r" % ({k: vals.get(k) for k in ("THEME_DAY", "THEME_NIGHT")},))
    check(vals.get("EMPTY") == 0xFFFFFFFF, "T1: EMPTY == 0xFFFFFFFF")
    check("#define FLASH_ADDRESS_OFFSET  (128 * 1024)" in cph and cd.FLASH_BASE == 128 * 1024, "T1: FLASH_ADDRESS_OFFSET = 128 KiB = custom_data.FLASH_BASE")
    cpc = read_text("source", "functions", "codeplug.c")
    check("const uint32_t MAX_BLOCK_ADDRESS = 0x10000;" in cpc and cd.MAX_BLOCK_ADDRESS == 0x10000, "T1: MAX_BLOCK_ADDRESS = 0x10000")

    disp = read_text("source", "hardware", "HX8353E_display.c")
    check("memcpy(&themeItems[DAY], &themingTmp, sizeof(themingTmp));" in disp and "uint16_t themingTmp[THEME_ITEM_MAX];" in disp,
          "T1: themeInit копіює РІВНО sizeof(themingTmp) = 64 байти")
    check("(uint8_t *)&themeItems[daytime], (sizeof(uint16_t) * THEME_ITEM_MAX)" in disp, "T1: displayThemeSaveToFlash пише 64 байти без перетворень (RAM = формат блока)")
    check("PLATFORM_COLOUR_FORMAT_SWAP_BYTES(RGB888_TO_PLATFORM_COLOUR_FORMAT(themeDefaults[daytime][i]))" in disp, "T1: стокові значення -> RGB565 зі зміненими байтами")
    app = read_text("source", "applicationMain.c")
    mdi = app[app.index("#elif defined(PLATFORM_MDUV380)"):app.index("#else // MD-2017")]
    check("displayLCD_Type |= DIPLAYLCD_TYPE_RGB;" in mdi, "T1: для MDUV380 дисплей завжди RGB (не BGR)")
    check("((x & 0xf80000) >> 8) + ((x & 0xfc00) >> 5) + ((x & 0xf8) >> 3)" in hdr, "T1: формула RGB888 -> RGB565 у HX8353E.h")

    # стокові таблиці: UA-гілка і «інакше»
    a = disp.index("#if defined(LANGUAGE_BUILD_UKRAINIAN)\n\t// R19")
    b = disp.index("#else\n\tstatic const uint32_t themeDefaults")
    c = disp.index("#endif", b)

    def parse(chunk):
        out = {}
        for part, nm in (("DAY", "day"), ("NIGHT", "night")):
            i = chunk.index("[%s] =" % part)
            j = chunk.index("}", i)
            out[nm] = [(k, int(v, 16)) for k, v in re.findall(r"\[THEME_ITEM_(\w+)\]\s*=\s*0x([0-9A-Fa-f]{6})U", chunk[i:j])]
        return out
    for variant, chunk in (("ua", disp[a:b]), ("classic", disp[b:c])):
        p = parse(chunk)
        for dt in th.DAYTIMES:
            keys = [k for k, _v in p[dt]]
            check(keys == list(th.KEYS), "T1.3: %s/%s: таблиця в C має ті самі 32 ключі в тому ж порядку" % (variant, dt))
            check([v for _k, v in p[dt]] == list(th._TABLES[variant][dt]), "T1.3: %s/%s: стокові значення theme_edit == themeDefaults у C" % (variant, dt))


# ----------------------------------------------------------------------------------------------------------------------
#  Кольори, блок, файл (Z2), набори (Z3)
# ----------------------------------------------------------------------------------------------------------------------

def c_macro(x):
    """Дослівна копія RGB888_TO_PLATFORM_COLOUR_FORMAT для RGB-дисплея, плюс PLATFORM_COLOUR_FORMAT_SWAP_BYTES, і потім -- байти LE-пам'яті."""
    p = ((x & 0xf80000) >> 8) + ((x & 0xfc00) >> 5) + ((x & 0xf8) >> 3)
    swapped = ((p & 0xFF) << 8) | ((p & 0xFF00) >> 8)
    return bytes([swapped & 0xFF, swapped >> 8])        # little-endian uint16 у пам'яті/флеші


def test_colours_and_block():
    bad = [v for v in range(0x10000) if th.rgb888_to_565(th.rgb565_to_888(v)) != v]
    check(not bad, "кольори: RGB565 -> RGB888 -> RGB565 повертає те саме на всіх 65536 значеннях (збіг: %d)" % len(bad))
    rng = random.Random(28)
    for _ in range(2000):
        x = rng.getrandbits(24)
        check(th.encode_block([th.rgb888_to_565(x)] * 32)[:2] == c_macro(x), "формат: байти кольору 0x%06X == те, що кладе прошивка (макрос + swap + LE)" % x)
        if FAILS:
            break
    for var in ("ua", "classic"):
        for dt in th.DAYTIMES:
            blk = th.encode_block(th.stock_colors(dt, var))
            want = b"".join(c_macro(x) for x in th._TABLES[var][dt])
            check(blk == want and len(blk) == 64, "стокова %s/%s: 64 байти == те, що прошивка отримала б із themeDefaults" % (var, dt))
            check(th.decode_block(blk) == th.stock_colors(dt, var), "стокова %s/%s: decode(encode) == вихідні" % (var, dt))
    check(th.from_hex("#FF00FF") == 0xF81F and th.to_hex(0xF81F) == "#FF00FF", "hex: #FF00FF <-> 0xF81F")
    for bad_hex in ("", "#12", "#GG0000", "#1234567", "red"):
        try:
            th.from_hex(bad_hex)
            check(False, "hex %r мав бути відхилений" % bad_hex)
        except ValueError:
            pass
    for bad_cols in ([0] * 31, [0] * 33, [0x10000] + [0] * 31, [-1] + [0] * 31):
        try:
            th.encode_block(bad_cols)
            check(False, "encode_block мав відхилити %r" % (bad_cols[:2],))
        except ValueError:
            pass


def test_file_roundtrip():
    """Z2: файл теми -> завантажити -> зберегти == той самий файл, байт у байт."""
    tmp = tempfile.mkdtemp(prefix="r28f_")
    rng = random.Random(7)
    samples = []
    for dt in th.DAYTIMES:
        for _k, _n, _d, cols in th.available_sets(dt):
            samples.append((dt, cols))
        samples.append((dt, [rng.getrandbits(16) for _ in range(32)]))
    for i, (dt, cols) in enumerate(samples):
        p1, p2 = os.path.join(tmp, "a%d.txt" % i), os.path.join(tmp, "b%d.txt" % i)
        th.save_file(p1, dt, cols)
        dt2, cols2 = th.load_file(p1)
        th.save_file(p2, dt2, cols2)
        a, b = open(p1, "rb").read(), open(p2, "rb").read()
        check(a == b and dt2 == dt and cols2 == cols, "Z2: зразок %d (%s): завантажити -> зберегти == той самий файл" % (i, dt))
    check(a.endswith(b"\n") and b"\r" not in a and not a.startswith(b"\xef\xbb\xbf"), "Z2: файл UTF-8, без BOM, переноси \\n")
    # зовнішній файл (CRLF, BOM, нижній регістр, довільні RGB888): приймається, колір квантується відкиданням молодших бітів, як у прошивці
    txt = "﻿" + th.to_file_text("day", th.stock_colors("day")).replace("\n", "\r\n").replace("#FFFFFF", "#ffffff")
    dt, cols = th.from_file_text(txt)
    check(dt == "day" and cols == th.stock_colors("day"), "Z2: файл із BOM/CRLF/нижнім регістром читається")
    lines = th.to_file_text("night", th.stock_colors("night")).splitlines()
    odd = [l for l in lines if not l.startswith("FG_DEFAULT")] + ["FG_DEFAULT = #0A0B0C"]
    dt, cols = th.from_file_text("\n".join(odd))
    check(cols[0] == th.rgb888_to_565(0x0A0B0C), "Z2: довільний #RRGGBB квантується як у прошивці")
    # помилки
    good = th.to_file_text("day", th.stock_colors("day"))
    cases = {
        "чужий формат": good.replace(th.FILE_FORMAT, "other"),
        "нема daytime": "\n".join(l for l in good.splitlines() if not l.startswith("daytime")),
        "daytime=dusk": good.replace("daytime = day", "daytime = dusk"),
        "бракує кольору": "\n".join(l for l in good.splitlines() if not l.startswith("FG_BD_COLOUR")),
        "дубль": good + "BG = #000000\n",
        "невідомий ключ": good + "FG_X = #000000\n",
        "поганий hex": good.replace("#000000", "#00000G", 1),
        "рядок без =": good + "дурниця\n",
    }
    for name, text in cases.items():
        try:
            th.from_file_text(text)
            check(False, "Z2: файл «%s» мав бути відхилений" % name)
        except th.ThemeFileError as e:
            check(bool(str(e)), "Z2: «%s» -- пояснення українською: %s" % (name, e))
    bad_path = os.path.join(tmp, "latin.txt")
    open(bad_path, "wb").write(b"\xe7\xe0\xe2\xe5\n")           # «зав» у cp1251 -- не UTF-8
    try:
        th.load_file(bad_path)
        check(False, "Z2: файл не в UTF-8 мав бути відхилений")
    except th.ThemeFileError:
        pass


def test_ready_sets():
    """Z3: кожен готовий набір дає саме ті байти, яких чекає формат (рахуємо незалежно від encode_block), і читабельний на кожній парі."""
    roles = {"night_red": th._N_RED, "night_hc": th._N_HC, "day_hc": th._D_HC}
    for key, (name, dts, desc, mn, cols) in th.READY_SETS.items():
        expect = b"".join(c_macro(roles[key][k]) for k in th.KEYS)
        check(th.encode_block(cols) == expect and len(expect) == 64, "Z3: набір «%s»: 64 байти == формат прошивки" % name)
        check(len(set(cols)) > 5, "Z3: набір «%s» -- не однотонний" % name)
        weak = th.weak_pairs(cols, text_min=mn, graphic_min=th.GRAPHIC_MIN)
        check(not weak, "Z3: набір «%s»: кожна пара не слабша за %.1f:1 (текст) / 3:1 (графіка); слабкі: %r" % (name, mn, weak))
        check(th.worst_contrast(cols) >= mn, "Z3: набір «%s»: найгірший текстовий контраст %.2f >= %.1f" % (name, th.worst_contrast(cols), mn))
        check(desc and name and set(dts) <= set(th.DAYTIMES), "Z3: набір «%s» має опис і прив'язку до теми" % name)
    check(len(th.READY_SETS) >= 2, "T4: щонайменше 2 готових набори, крім стокових")
    check(any("night" in v[1] and "мінімум" in v[0].lower() for v in th.READY_SETS.values()), "T4: є нічний набір «мінімум світла»")
    check(any("night" in v[1] and "контраст" in v[0].lower() for v in th.READY_SETS.values()), "T4: є нічний набір «високий контраст»")
    # стокові: кожна пара, крім відомої виняткової, проходить 4.5:1 -- підтвердження, що таблиця PAIRS узята з реального коду
    for var in ("ua", "classic"):
        for dt in th.DAYTIMES:
            weak = [(a, b) for a, b, _c, _n, _t in th.weak_pairs(th.stock_colors(dt, var))]
            check(set(weak) <= {("FG_TX_COUNTER", "BG_HEADER_TEXT")}, "PAIRS: стокова %s/%s слабка лише на відомій парі (APRS-мітка в шапці): %r" % (var, dt, weak))
    # слабкий контраст виявляється
    ugly = th.stock_colors("day")
    ugly[th.INDEX["FG_DEFAULT"]] = ugly[th.INDEX["BG"]]
    check(("FG_DEFAULT", "BG") in [(a, b) for a, b, *_ in th.weak_pairs(ugly)], "PAIRS: текст того самого кольору, що тло, -- слабка пара")
    check(abs(th.contrast(0x0000, 0xFFFF) - 21.0) < 1e-6, "контраст чорного й білого = 21:1")
    # перегляд покриває всі 32 елементи, кожен -- відомий ключ
    check(th.preview_items_covered() == set(th.KEYS), "T3: перегляд малює кожен із 32 елементів теми (бракує: %r)" % (sorted(set(th.KEYS) - th.preview_items_covered()),))
    for skey, _t in th.preview_screens():
        d = th.render_preview(skey)
        check(len(d.px) == th.SCREEN_W * th.SCREEN_H and max(d.px) < th.ITEM_COUNT, "T3: %s: буфер 160x128, індекси елементів у межах 0..31" % skey)


# ----------------------------------------------------------------------------------------------------------------------
#  Рація: custom_data над підміненим флешем
# ----------------------------------------------------------------------------------------------------------------------

class FakeFlash:
    """SPI-флеш у пам'яті; ставить підміну на aes_key_store.flash_read / flash_write_block (їх викликає custom_data)."""

    def __init__(self, magic=True, blocks=(), size=0x40000):
        self.mem = bytearray(b"\xff" * size)
        self.writes = []
        if magic:
            pos = cd.FLASH_BASE
            self.mem[pos:pos + 12] = b"OpenGD77" + b"\x00" * 4
            pos += 12
            for dtype, data in blocks:
                self.mem[pos:pos + 8] = struct.pack("<ii", dtype, len(data))
                self.mem[pos + 8:pos + 8 + len(data)] = data
                pos += 8 + len(data)

    def install(self):
        self._r, self._w = aks.flash_read, aks.flash_write_block
        aks.flash_read = lambda ser, addr, ln: bytes(self.mem[addr:addr + ln])

        def w(ser, addr, data):
            self.writes.append((addr, len(data)))
            self.mem[addr:addr + len(data)] = data
        aks.flash_write_block = w
        return self

    def uninstall(self):
        aks.flash_read, aks.flash_write_block = self._r, self._w

    def region(self):
        return bytes(self.mem[cd.FLASH_BASE:cd.FLASH_BASE + 0x10000])


def test_radio_io():
    other = [(1, bytes(range(200))), (2, b"\x07" * 40)]
    cols_d = th.stock_colors("day")
    cols_n = th.available_sets("night")[2][3]

    # a) області OpenGD77 нема
    f = FakeFlash(magic=False).install()
    try:
        check(th.read_theme(None, "day") == (th.ST_NOREGION, None), "IO: без області OpenGD77 -> ST_NOREGION")
        try:
            th.write_theme(None, "day", cols_d)
            check(False, "IO: запис без області мав відмовити")
        except RuntimeError as e:
            check("OpenGD77" in str(e), "IO: відмова пояснена: %s" % e)
        check(not f.writes, "IO: при відмові нічого не записано")
    finally:
        f.uninstall()

    # b) область є, тем нема: створення в першому вільному слоті, інші блоки не чіпаються
    f = FakeFlash(blocks=other).install()
    try:
        before = f.region()
        check(th.read_theme(None, "day") == (th.ST_ABSENT, None), "IO: блока нема -> ST_ABSENT")
        msg = th.write_theme(None, "day", cols_d)
        check("OK" in msg and "створено" in msg, "IO: денну створено й звірено: %s" % msg)
        after = f.region()
        first_empty = 12 + 8 + 200 + 8 + 40
        check(after[:first_empty] == before[:first_empty], "IO: наявні блоки (зображення, звук) не змінилися")
        check(struct.unpack("<ii", after[first_empty:first_empty + 8]) == (4, 64) and after[first_empty + 8:first_empty + 72] == th.encode_block(cols_d),
              "IO: денний блок: тип 4, довжина 64, дані == encode_block")
        check(after[first_empty + 72:] == before[first_empty + 72:], "IO: далі за блоком усе 0xFF як було")
        th.write_theme(None, "night", cols_n)
        st, back = th.read_theme(None, "night")
        check(st == th.ST_OK and back == cols_n, "IO: нічна створена слідом і читається назад")
        st, back = th.read_theme(None, "day")
        check(st == th.ST_OK and back == cols_d, "IO: денна на місці")
        # повторний запис денної: той самий блок, нічна не зачеплена
        new_d = list(reversed(cols_d))
        n_before = f.region()[first_empty + 72:first_empty + 144]
        th.write_theme(None, "day", new_d)
        check(th.read_theme(None, "day") == (th.ST_OK, new_d) and f.region()[first_empty + 72:first_empty + 144] == n_before,
              "IO: перезапис денної не зачепив нічну")
        # жоден запис не вийшов за область 0x20000..0x30000 (калібрування 0x10000 і все решта -- поза нею)
        check(all(cd.FLASH_BASE <= a and a + n <= cd.FLASH_BASE + 0x10000 for a, n in f.writes), "IO: усі записи лише в області custom-data: %r" % (f.writes[:3],))
        check(all(a < 0x10000 or a >= 0x11000 for a, _n in f.writes), "IO: сектор калібрування 0x10000 не зачеплено")
    finally:
        f.uninstall()

    # c) блок нестандартної довжини: читати дозволено, писати -- ні
    f = FakeFlash(blocks=other + [(4, b"\x00" * 40)]).install()
    try:
        check(th.read_theme(None, "day")[0] == th.ST_BADLEN, "IO: блок 40 байтів -> ST_BADLEN")
        snap = bytes(f.mem)
        try:
            th.write_theme(None, "day", cols_d)
            check(False, "IO: запис у блок чужої довжини мав відмовити")
        except RuntimeError as e:
            check("довжин" in str(e), "IO: відмова пояснена: %s" % e)
        check(bytes(f.mem) == snap, "IO: пам'ять не змінилася")
    finally:
        f.uninstall()

    # d) довший блок (>64): читаємо перші 64, писати не можна
    f = FakeFlash(blocks=[(5, th.encode_block(cols_n) + b"\x01\x02")]).install()
    try:
        st, back = th.read_theme(None, "night")
        check(st == th.ST_BADLEN and back == cols_n, "IO: блок 66 байтів -> перші 64 читаються, стан ST_BADLEN")
    finally:
        f.uninstall()

    # e) немає місця
    big = [(1, b"\x00" * (0x10000 - 12 - 8 - 20))]
    f = FakeFlash(blocks=big).install()
    try:
        # R37: область є, але вільних 20 Б -- це «блока нема» (читання місця не потребує), а не «області нема»; нестача місця вилазить лише при записі
        check(th.read_theme(None, "day")[0] == th.ST_ABSENT, "IO: область майже повна -> читання каже ST_ABSENT (область є, блока нема)")
        try:
            th.write_theme(None, "day", cols_d)
            check(False, "IO: запис у майже повну область мав відмовити")
        except RuntimeError as e:
            check("місця" in str(e), "IO: відмова записати у майже повну область пояснена словами про місце: %s" % e)
    finally:
        f.uninstall()

    # f) звірка читанням ловить хибний запис
    f = FakeFlash(blocks=other).install()
    try:
        orig = aks.flash_write_block
        aks.flash_write_block = lambda ser, addr, data: orig(ser, addr, bytes(data[:-1]) + bytes([data[-1] ^ 0xFF])) if len(data) > 8 else orig(ser, addr, data)
        try:
            th.write_theme(None, "day", cols_d)
            check(False, "IO: збій запису мав бути виявлений звіркою")
        except RuntimeError as e:
            check("НЕ збіглася" in str(e), "IO: звірка виявила розбіжність: %s" % e)
    finally:
        f.uninstall()


# ----------------------------------------------------------------------------------------------------------------------
#  Z4: каскадне видалення APRS-слота (логіка)
# ----------------------------------------------------------------------------------------------------------------------

def aprs_fixture():
    """Образ із трьома APRS-слотами: «APRS», «BASE1», «BASE2»; канали №1 (цифровий) і №2 (аналоговий) посилаються на №3 (BASE2), №... на №2."""
    img, _spi, _cp = tr.fixture_img()
    v = ced.new_aprs_values()
    for nm in ("BASE1", "BASE2"):
        v["name"] = nm
        img = ced.apply_aprs_slot(img, None, dict(v)).image
    img = te.channel_edit(img, 1, {"APRS": "#3"}, DP).image
    img = te.channel_edit(img, 2, {"APRS": "#3"}, DP).image
    return img


def same(a, b):
    return bytes(a.eeprom) == bytes(b.eeprom) and bytes(a.flash) == bytes(b.flash)


def test_aprs_cascade_logic():
    img = aprs_fixture()
    check([s for s, _r in img.aprs()] == [0, 1, 2], "Z4: у фікстурі три APRS-слоти")
    refs = te.references(img, "aprs", 2)
    check(len(refs.items) == 2 and "№1" in refs.items[0][1] and "№2" in refs.items[1][1], "Z4: посилання знайдено в цифровому І аналоговому каналі: %r" % (refs.items,))
    check(not te.references(img, "aprs", 1) and len(te.references(img, "aprs", 0).items) == 1, "Z4: на слот №2 ніхто не посилається, на №1 -- один канал (№3 з фікстури)")
    # скасувати (cascade=False) -> відмова, нічого не змінено
    try:
        te.delete_entity(img, "aprs", 2, DP)
        check(False, "Z4: видалення зі посиланнями без cascade мало відмовити")
    except te.TableEditError as e:
        check("використовується" in str(e) and "№1" in str(e), "Z4: відмова називає канали: %s" % str(e).splitlines()[-2:])
    snap = (bytes(img.eeprom), bytes(img.flash))
    check((bytes(img.eeprom), bytes(img.flash)) == snap, "Z4: образ після відмови не змінено")
    # каскад
    res = te.delete_entity(img, "aprs", 2, DP, cascade=True)
    n = res.image
    check([s for s, _r in n.aprs()] == [0, 1], "Z4: каскад: лишилося два слоти")
    check(te.channel_refs(n, 1)["APRS"] == 0 and te.channel_refs(n, 2)["APRS"] == 0, "Z4: каскад: поле APRS у обох каналах порожнє")
    check(te.channel_refs(n, 3)["APRS"] == 1, "Z4: каскад не зачепив посилання інших каналів на інші слоти (канал №3 -> слот №1)")
    check(te.channel_refs(n, 1)["Contact"] == te.channel_refs(img, 1)["Contact"] and te.channel_refs(n, 1)["TG List"] == te.channel_refs(img, 1)["TG List"],
          "Z4: каскад не зачепив інші посилання каналу")
    check(bytes(n.ee(cc.ADDR_APRS + 2 * cc.APRS_SIZE, cc.APRS_SIZE)) == b"\xff" * cc.APRS_SIZE, "Z4: байти видаленого слота -- 0xFF (як при видаленні старим шляхом)")
    check(("APRS", "BASE2") in res.removed, "Z4: у підсумку -- видалено «BASE2»: %r" % (res.removed,))
    # той самий образ, що дає старий шлях (спершу прибрати посилання, потім стерти слот)
    old = te.channel_edit(te.channel_edit(img, 1, {"APRS": "None"}, DP).image, 2, {"APRS": "None"}, DP).image
    old = ced.delete_aprs_slot(old, 2).image
    check(same(n, old), "Z4: каскад == (прибрати посилання + codeplug_edit.delete_aprs_slot) байт у байт")
    # слот без посилань видаляється без каскаду
    img2 = ced.apply_aprs_slot(n, None, dict(ced.new_aprs_values(), name="TMP")).image
    check(not te.references(img2, "aprs", 2), "Z4: новий слот без посилань")
    r2 = te.delete_entity(img2, "aprs", 2, DP)
    check([s for s, _r in r2.image.aprs()] == [0, 1] and same(r2.image, n), "Z4: слот без посилань видаляється без питань і дає той самий образ")
    # середній слот -- відмова навіть з каскадом
    for casc in (False, True):
        try:
            te.delete_entity(img, "aprs", 1, DP, cascade=casc)
            check(False, "Z4: видалення середнього слота мало відмовити (cascade=%r)" % casc)
        except te.TableEditError as e:
            check("з середини" in str(e), "Z4: середній слот: пояснення (cascade=%r)" % casc)
    check("з середини" in (te.aprs_delete_problem(img, 0) or "") and te.aprs_delete_problem(img, 2) is None and "порожній" in (te.aprs_delete_problem(img, 5) or ""),
          "Z4: aprs_delete_problem: середній / останній / неіснуючий")
    # посилання на інший слот лишаються
    img3 = te.channel_edit(img, 2, {"APRS": "#2"}, DP).image
    n3 = te.delete_entity(img3, "aprs", 2, DP, cascade=True).image
    check(te.channel_refs(n3, 2)["APRS"] == 2 and te.channel_refs(n3, 1)["APRS"] == 0, "Z4: посилання на слот №2 лишилося, на №3 прибрано")
    # документ не змінюється при відмові (EditorPanel і блок APRS використовують один і той самий діалог)
    check("def delete_choice(" in open(os.path.join(HERE, "gui_dialogs.py"), encoding="utf-8").read(), "Z4: спільний діалог gd.delete_choice")
    src = open(os.path.join(HERE, "cps_ui", "editor_base.py"), encoding="utf-8").read()
    src2 = open(os.path.join(HERE, "cps_ui", "p_aprs_slots.py"), encoding="utf-8").read()
    check("gd.delete_choice(" in src and "gd.delete_choice(" in src2, "Z4: редактори й блок APRS видаляють через ОДИН діалог, не окрему логіку")
    check("te.delete_entity(" in src2 and "ced.delete_aprs_slot" not in src2, "Z4: блок APRS видаляє через table_edit.delete_entity")


# ----------------------------------------------------------------------------------------------------------------------
#  GUI
# ----------------------------------------------------------------------------------------------------------------------

def _all(w):
    yield w
    for c in w.winfo_children():
        yield from _all(c)


def _spin(app, n=3):
    for _ in range(n):
        app.update()


def _wait_idle(app, limit=3.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.update()
        if not app.busy and app.queue.empty():
            return
        time.sleep(0.02)


class Ev:
    def __init__(self, x, y):
        self.x, self.y = x, y


def test_gui():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("ПРОПУЩЕНО (GUI): нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО (GUI): нема DISPLAY")
        return
    import tkinter.colorchooser as colorchooser
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import cps_link as cl
    import gui_dialogs as gd
    from cps_ui.app import CpsApp
    from cps_ui.settings import Settings

    tmp = tempfile.mkdtemp(prefix="r28_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    errors, infos = [], []
    mb.showinfo = lambda *a, **k: infos.append(a)
    mb.showerror = lambda *a, **k: errors.append(a)
    gd.confirm_dialog = lambda *a, **k: True
    orig_open_radio = cl.open_radio
    flash = None
    try:
        app.geometry("1300x900")
        app.update()
        # --- Z1: панель без документа ---
        app.show("themes")
        _spin(app)
        p = app.get_panel("themes")
        check(type(p).__name__ == "ThemesPanel" and "themes" in dict((c.key, c) for _g, _t, cl_ in __import__("cps_ui.app", fromlist=["SECTIONS"]).SECTIONS for c in cl_),
              "Z1: панель «Теми екрана» є в SECTIONS")
        check(len(p._rows) == 32 and all(r["hex"].cget("text").startswith("#") for r in p._rows), "Z1: у списку 32 кольори з hex")
        check(p._img is not None and len(p._screens) >= 6, "Z1: екран перегляду намальовано, у перемикачі кілька екранів (%d)" % len(p._screens))
        check(str(p.write_btn.cget("state")) == "disabled" and str(p.read_btn.cget("state")) == "disabled", "Z1: без рації читання/запис вимкнені")
        check(str(p.save_btn.cget("state")) != "disabled" and str(p.reset_btn.cget("state")) != "disabled", "Z1: файл і «Скинути» працюють без рації")
        check(p.dt == "night" and p.colors["night"] == th.stock_colors("night"), "Z1: початково нічна тема стокова")

        # перемикач день/ніч
        p.daytime.set("day")
        p._on_daytime()
        _spin(app)
        check(p._rows[1]["hex"].cget("text") == th.to_hex(th.stock_colors("day")[1]) == "#FFFFFF", "T2: перемикач на денну -- тло #FFFFFF")
        p.daytime.set("night")
        p._on_daytime()
        check(p._rows[1]["hex"].cget("text") == th.to_hex(th.stock_colors("night")[1]), "T2: назад на нічну")

        # зміна кольору стандартним вибирачем (підміна askcolor)
        asked = []
        colorchooser.askcolor = lambda **k: (asked.append(k) or ((18, 52, 86), "#123456"))
        p._on_pick(th.INDEX["BG"])
        _spin(app)
        want = th.from_hex("#123456")
        check(p.colors["night"][1] == want and p.touched["night"] and not p.touched["day"], "T2: вибраний колір потрапив у робочу копію (лише нічну)")
        check(p._rows[1]["swatch"].cget("bg").upper() == th.to_hex(want) and p._rows[1]["mark"].cget("text") == "●", "T2: зразок оновлено, є позначка «змінено»")
        check(asked and "Тло екрана" in asked[0]["title"] and asked[0]["color"] == th.to_hex(th.stock_colors("night")[1]), "T2: вибирач відкрито з поточним кольором і назвою елемента")
        # перегляд змінився: фон екрана «Канал» має новий колір
        n = int(p.scale_var.get())
        px = p._img.get(80 * n, 100 * n)
        check("#%02X%02X%02X" % tuple(px) == th.to_hex(want), "T3: перегляд перемальовано новим кольором тла: %r" % (px,))
        # скасований вибирач нічого не міняє
        colorchooser.askcolor = lambda **k: (None, None)
        before = list(p.colors["night"])
        p._on_pick(5)
        check(p.colors["night"] == before, "T2: «Скасувати» у вибирачі колір не змінює")
        # клацання по перегляду підсвічує рядок
        d0 = p._display
        idx = d0.px.index(th.INDEX["FG_CHANNEL_NAME"])
        n = int(p.scale_var.get())
        p._on_preview_click(Ev((idx % th.SCREEN_W) * n + n // 2, (idx // th.SCREEN_W) * n + n // 2))
        check(p._selected == th.INDEX["FG_CHANNEL_NAME"], "T3: клацання по назві каналу в перегляді вибирає її колір у списку")

        # готовий набір
        keys = {n: k for k, n, _d, _c in th.available_sets("night")}
        check(len(keys) >= 4, "T2/T4: у списку наборів стокові й готові: %r" % list(keys))
        p.set_var.set("Ніч: високий контраст")
        p._on_apply_set()
        check(p.colors["night"] == th.READY_SETS["night_hc"][4] and not p.warn_label.cget("text"), "T4: набір «Ніч: високий контраст» застосовано, слабкого контрасту нема")
        # «Скинути до стокової»
        p._on_reset()
        check(p.colors["night"] == th.stock_colors("night") and p.touched["night"], "T2: «Скинути до стокової» повертає значення прошивки (і позначає як незаписане)")
        p.screen_combo.current([k for k, _t in p._screens].index("menu"))
        p._on_screen_change()
        check(th.INDEX["BG_MENU_ITEM_SELECTED"] in set(p._display.px), "T3: перемикач екранів: у меню є виділений пункт")

        # файл: зберегти -> змінити -> завантажити -> те саме
        p.apply_set("night_red")
        path = os.path.join(tmp, "t.txt")
        fd.asksaveasfilename = lambda **k: path
        p._on_save_file()
        saved = open(path, "rb").read()
        check(saved == th.to_file_text("night", th.READY_SETS["night_red"][4]).encode("utf-8"), "T2: файл збережено кнопкою")
        p._on_reset()
        p.daytime.set("day")
        p._on_daytime()
        fd.askopenfilename = lambda **k: path
        p._on_load_file()
        check(p.dt == "night" and p.colors["night"] == th.READY_SETS["night_red"][4], "T2: завантаження файла перемкнуло на тему з файла й повернуло кольори (CE5)")
        p._on_save_file()
        check(open(path, "rb").read() == saved, "Z2 (GUI): завантажити -> зберегти == той самий файл")
        bad = os.path.join(tmp, "bad.txt")
        open(bad, "w", encoding="utf-8").write("це не тема\n")
        fd.askopenfilename = lambda **k: bad
        n_err = len(errors)
        p._on_load_file()
        check(len(errors) == n_err + 1 and p.colors["night"] == th.READY_SETS["night_red"][4], "T2: поганий файл -- повідомлення, кольори не змінено")

        # --- документи: порожній кодплаг і повний; теми від документа не залежать і документ не чіпають ---
        for label, spi in (("порожній", tc.base.make_spi()), ("повний", tc.make_fixture_spi())):
            _cp, data = tc.codeplug_of(spi)
            src = os.path.join(tmp, "%s.zip" % label)
            open(src, "wb").write(data)
            check(app.doc_open_file(src), "Z1: відкрито %s кодплаг" % label)
            app.show("themes")
            _spin(app)
            p.apply_set("night_hc")
            _spin(app)
            check(len(p._rows) == 32 and not app.doc.modified, "Z1: %s кодплаг: панель працює, документ не змінено темою" % label)
            check(p.write_plan() == ["night"], "Z1: %s кодплаг: до запису -- лише змінена нічна" % label)

        # --- рація: підроблений флеш ---
        flash = FakeFlash(blocks=[(1, bytes(range(100)))]).install()

        class FakeSer:
            closed = False

            def close(self):
                FakeSer.closed = True
        cl.open_radio = lambda *a, **k: FakeSer()
        p.apply_set("night_red")
        snapshot = {"night": list(p.colors["night"])}
        p.colors["day"] = th.READY_SETS["day_hc"][4]
        p.touched["day"] = True
        check(p.write_plan() == ["day", "night"], "CE2: до запису -- обидві змінені теми")
        p._on_write()                                   # через run_task: потік + post
        _wait_idle(app)
        check(not app.busy and FakeSer.closed, "CE2: запис завершено, порт закрито")
        check(th.read_theme(None, "night") == (th.ST_OK, snapshot["night"]) and th.read_theme(None, "day") == (th.ST_OK, th.READY_SETS["day_hc"][4]),
              "CE2: у «флеші рації» обидві теми == робоча копія")
        check(not p.touched["night"] and not p.touched["day"] and p.radio_state["night"] == th.ST_OK, "CE2: після запису «незаписаного» нема")
        check(p.write_plan() == [], "CE2: повторний запис не потрібен")
        n_info = len(infos)
        p._on_write()
        check(len(infos) == n_info + 1, "CE2: «Записати» без змін -- підказка, а не запис")
        # читання повертає записане; блока нема -> стокова
        p.apply_set("night_hc")
        p.touched["night"] = False                      # пропускаємо підтвердження «зміни пропадуть»
        p.touched["day"] = False
        flash.mem[cd.FLASH_BASE + 12 + 8 + 100:] = b"\xff" * (len(flash.mem) - (cd.FLASH_BASE + 12 + 8 + 100))      # стерти обидва теми-блоки
        p._on_read()
        _wait_idle(app)
        check(p.radio_state == {"day": th.ST_ABSENT, "night": th.ST_ABSENT} and p.colors["night"] == th.stock_colors("night") and p.colors["day"] == th.stock_colors("day"),
              "CE1: блока нема -> показано стокову, стан «блока теми в рації нема»")
        check("блока теми в рації нема" in p.info.cget("text"), "CE1: стан показано словами: %s" % p.info.cget("text"))
        th.write_theme(None, "night", th.READY_SETS["night_hc"][4])
        p._on_read()
        _wait_idle(app)
        check(p.colors["night"] == th.READY_SETS["night_hc"][4] and p.base["night"] == p.colors["night"] and not any(p.touched.values()), "CE1: читання з рації принесло записану нічну тему")
        # CE4: скинути до стокової й записати -- байти == стокові
        p.daytime.set("night")
        p._on_reset()
        p._on_write()
        _wait_idle(app)
        check(th.read_theme(None, "night")[1] == th.stock_colors("night"), "CE4: після «Скинути до стокової» + запису в рації -- стокова тема")
        # відмова, коли запис неможливий
        p.apply_set("night_red")
        p.radio_state["night"] = th.ST_NOREGION
        snap = bytes(flash.mem)
        n_err = len(errors)
        p._on_write()
        check(len(errors) == n_err + 1 and bytes(flash.mem) == snap, "Z1: ST_NOREGION -- пояснення замість запису, флеш не змінено")
        # скасування підтвердження записом не робить
        p.radio_state["night"] = th.ST_OK
        gd.confirm_dialog = lambda *a, **k: False
        p._on_write()
        _spin(app)
        check(bytes(flash.mem) == snap, "Z1: «Скасувати» у підтвердженні -- запису нема")
        gd.confirm_dialog = lambda *a, **k: True
        check(not app.doc.modified, "Z1: теми жодного разу не зробили документ зміненим")

        # --- Z4 (GUI): каскад видалення APRS-слота ---
        flash.uninstall()
        flash = None
        cl.open_radio = orig_open_radio
        src = os.path.join(tmp, "aprs.zip")
        _cp, data = tc.codeplug_of(tc.make_fixture_spi())
        open(src, "wb").write(data)
        check(app.doc_open_file(src), "Z4: відкрито кодплаг для APRS")
        v = ced.new_aprs_values()
        for nm in ("BASE1", "BASE2"):
            app.doc.apply(ced.apply_aprs_slot(app.doc.image, None, dict(v, name=nm)))
        app.doc.apply(te.channel_edit(app.doc.image, 1, {"APRS": "#3"}, DP))
        app.doc.apply(te.channel_edit(app.doc.image, 2, {"APRS": "#3"}, DP))
        app.show("aprs")
        _spin(app)
        st = app.get_panel("aprs").station
        st.tree.selection_set(st.tree.get_children()[2])
        _spin(app)
        check(st.current == 2, "Z4: вибрано слот №3 (BASE2)")
        calls = {"choice": [], "confirm": []}
        snap = (bytes(app.doc.image.eeprom), bytes(app.doc.image.flash))
        gd.choice_dialog = lambda parent, title, text, buttons, default_index=0: (calls["choice"].append((title, text, [b[1] for b in buttons])) or "cancel")
        gd.confirm_dialog = lambda *a, **k: (calls["confirm"].append(a[1:3]) or True)
        st._on_delete()
        _spin(app)
        check(len(calls["choice"]) == 1 and calls["choice"][0][2] == ["cancel", "cascade"], "Z4: є посилання -- показано вибір «Скасувати» / «Видалити разом із посиланнями»")
        check("№1" in calls["choice"][0][1] and "№2" in calls["choice"][0][1] and "None" in calls["choice"][0][1], "Z4: у тексті названо канали й сказано, що поле стане «None»")
        check((bytes(app.doc.image.eeprom), bytes(app.doc.image.flash)) == snap and len(app.doc.image.aprs()) == 3, "Z4: «Скасувати» -- документ не змінено")
        gd.choice_dialog = lambda parent, title, text, buttons, default_index=0: (calls["choice"].append((title, text, [b[1] for b in buttons])) or "cascade")
        st._on_delete()
        _spin(app)
        check(len(app.doc.image.aprs()) == 2 and te.channel_refs(app.doc.image, 1)["APRS"] == 0 and te.channel_refs(app.doc.image, 2)["APRS"] == 0,
              "Z4: «Видалити разом із посиланнями» -- слот зник, поле APRS у каналах порожнє")
        check(st.current == 0 and app.doc.modified, "Z4: після видалення вибрано перший слот (як і раніше), документ змінено (current=%r, змінено=%r)" % (st.current, app.doc.modified))
        # слот без посилань: звичайне підтвердження, діалогу вибору нема
        calls["choice"].clear()
        st.tree.selection_set(st.tree.get_children()[1])
        _spin(app)
        st._on_delete()
        _spin(app)
        check(not calls["choice"] and len(calls["confirm"]) == 1 and len(app.doc.image.aprs()) == 1, "Z4: слот без посилань видалено за простим підтвердженням, без діалогу вибору")
        # середній слот: пояснення ДО будь-яких запитань
        for nm in ("MID1", "MID2"):
            app.doc.apply(ced.apply_aprs_slot(app.doc.image, None, dict(v, name=nm)))
        _spin(app)
        st.tree.selection_set(st.tree.get_children()[1])
        _spin(app)
        calls["choice"].clear()
        calls["confirm"].clear()
        n_err = len(errors)
        st._on_delete()
        check(len(errors) == n_err + 1 and not calls["choice"] and not calls["confirm"] and len(app.doc.image.aprs()) == 3,
              "Z4: слот із середини -- одразу пояснення (без питань), документ не змінено")
    finally:
        if flash is not None:
            flash.uninstall()
        cl.open_radio = orig_open_radio
        app.destroy()


def main():
    import faulthandler
    faulthandler.dump_traceback_later(150, exit=True)
    for t in (test_firmware_constants, test_colours_and_block, test_file_roundtrip, test_ready_sets, test_radio_io, test_aprs_cascade_logic, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("test_r28: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_r28: усе гаразд (формат тем = прошивка, файл, набори, запис у підроблений флеш, панель, каскад видалення APRS-слота).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
