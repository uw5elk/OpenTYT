# -*- coding: utf-8 -*-
"""R35 (Z1-Z6): супутники (sat_tle.py), картинка заставки (splash_image.py), мелодія вмикання (boot_melody.py),
вилучення блока (custom_data.retire_block), вікно флеш-охоронця rawarea і три панелі CPS (p_satellites, p_splash, p_melody).
R49: голосові підказки (voice_prompts.py, vp_names.py, p_voice) скасовано; їхні перевірки з цього тесту прибрано, а сира область 0xAF400..0xD8000 лишилась захищеною зоною.
Логіка -- у будь-якому python3; GUI -- лише з tkinter + DISPLAY (`xvfb-run -a python3.12 -B tools/test_r35.py`). Рації нема: SPI-флеш підроблено (FakeRadioX з test_cps_restore).

ПРОШИВКА перевіряється на СПРАВЖНЬОМУ коді, де це можливо: з satellite.c витягується satelliteTLE2Native (разом із decompressTleData) і компілюється gcc -- блок, який збирає
CPS, мусить розпакуватися прошивкою в ті самі числа, що стоять у TLE; таблиця частот нот і множник 27 мс звіряються з sound.c; Pillow (якщо встановлений) використовується ЛИШЕ в тесті для перехресної перевірки наших декодерів PNG; сам інструмент його не потребує."""
import datetime
import os
import random
import re
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

import aes_key_store as aks              # noqa: E402
import boot_melody as bm                 # noqa: E402
import cps_link as cl                    # noqa: E402
import custom_data as cd                 # noqa: E402
import custom_region as cr               # noqa: E402
import dmr_db as db                      # noqa: E402
import flash_guard as fg                 # noqa: E402
import sat_tle as st                     # noqa: E402
import splash_image as si                # noqa: E402
import test_cps_restore as tcr           # noqa: E402
import test_r30 as t30                   # noqa: E402
import test_r31 as t31                   # noqa: E402

FAILS = []
PASSED = [0]
tcr.FakeRadioX.close = lambda self: None
APP = os.path.normpath(os.path.join(HERE, "..", "application"))


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def quiet(*_a, **_k):
    pass


def read_text(*parts):
    with open(os.path.join(APP, *parts), encoding="utf-8", errors="replace") as f:
        return f.read()


def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def confirm_recorder(answer=True):
    asked = []

    def confirm(text, plan=None):
        asked.append(text)
        return answer
    return confirm, asked


# ----------------------------------------------------------------------------------------------------------------------
#  Підроблена рація з областю custom-data
# ----------------------------------------------------------------------------------------------------------------------

def region_payloads(types=(1, 2, 3, 4, 5, 8, 10), seed=1):
    """Блоки області: 1 IMAGE (1024), 2 BEEP (512), 3 TLE (2520) + кілька налаштувань (довжини з test_r30.SIZES)."""
    out = t30.make_payloads(seed, [t for t in types if t in t30.SIZES])
    if 1 in types:
        out[1] = bytes(((seed * 5 + i) % 250) + 1 for i in range(1024))
    if 2 in types:
        out[2] = bytes(((seed * 3 + i * 2) % 250) + 1 for i in range(512))
    if 3 in types:
        out[3] = st.build_block([st.Slot.from_tle(st.Tle(*mk_tle("FIX%d" % k, 20000 + k, 25, 30.0 + 11 * k + seed))) for k in range(3)])
    return out


def spi_region(types=(1, 2, 3, 4, 5, 8, 10), seed=1, magic=True, order=None, payloads=None):
    spi = t31.spi_marked()
    t30.put_region(spi, payloads if payloads is not None else region_payloads(types, seed), order or sorted(types), magic)
    return spi


def block_addr(spi, dtype):
    """Зміщення блока (відносно початку області) за типом -- незалежний від custom_data обхід."""
    pos = 12
    base = cd.FLASH_BASE
    while pos < 0x10000:
        t, n = struct.unpack("<ii", bytes(spi[base + pos:base + pos + 8]))
        if n in (0, -1):
            return None
        if t == dtype:
            return pos, n
        pos += 8 + n
    return None


class WriteLog:
    """Записує всі виклики aks.flash_write_block (адреса, довжина), поки діє."""

    def __enter__(self):
        self.calls = []
        self.orig = aks.flash_write_block

        def rec(ser, addr, data):
            self.calls.append((addr, len(data)))
            return self.orig(ser, addr, data)
        aks.flash_write_block = rec
        return self

    def __exit__(self, *a):
        aks.flash_write_block = self.orig


# ----------------------------------------------------------------------------------------------------------------------
#  Z0: константи == код прошивки
# ----------------------------------------------------------------------------------------------------------------------

def test_constants_match_firmware():
    sat_c = read_text("source", "functions", "satellite.c")
    check('DECOMPRESSION_LOOKUP = "%s"' % st.LOOKUP in sat_c, "Z0/A1: таблиця нібл-стиснення збігається з satellite.c")
    sat_h = read_text("include", "functions", "satellite.h")
    check("#define NUM_SATELLITES %d" % st.NUM_SLOTS in sat_h and "forceToSize[%d]" % st.BLOCK_LEN in sat_h, "Z0/A1: NUM_SATELLITES і розмір блока 2520 -- з satellite.h")
    m = re.search(r"typedef struct __attribute__\(\(__packed__\)\)\s*\{(.*?)\}\s*codeplugSatelliteData_t", sat_h, re.S)
    body = m.group(1) if m else ""
    sizes = {"char": 1, "uint8_t": 1, "uint16_t": 2, "uint32_t": 4}
    total = 0
    for typ, name, cnt in re.findall(r"(char|uint8_t|uint16_t|uint32_t)\s+(\w+)(?:\[(\w+)\])?;", body):
        n = 1
        if cnt:
            n = int(cnt) if cnt.isdigit() else int(re.search(r"#define\s+%s\s+(\d+)" % cnt, sat_h).group(1))
        total += sizes[typ] * n
    check(total == st.REC_LEN == st.STRUCT.size, "Z0/A1: запис codeplugSatelliteData_t = %d Б (є %d), struct-формат %d Б" % (total, st.REC_LEN, st.STRUCT.size))
    check(st.NUM_SLOTS * st.REC_LEN + st.PAD_LEN == st.BLOCK_LEN, "Z0/A1: 25*100 + добивка 20 = 2520")
    check(st.BLOCK_TYPE == 3 and bm.BLOCK_TYPE == 2 and si.BLOCK_TYPE == 1, "Z0: типи блоків 1/2/3")
    codeplug_h = read_text("include", "functions", "codeplug.h")
    m = re.search(r"typedef enum\s*\{([^}]*CODEPLUG_CUSTOM_DATA_TYPE_EMPTY[^}]*)\}\s*CodeplugCustomDataType_t", codeplug_h, re.S)
    names = re.findall(r"CODEPLUG_CUSTOM_DATA_TYPE_([A-Z_0-9]+)", re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)) if m else []
    check(names[:4] == ["EMPTY", "IMAGE", "BEEP", "SATELLITE_TLE"], "Z0: у codeplug.h типи 1,2,3 = IMAGE, BEEP, SATELLITE_TLE: %s" % names[:4])
    sound_c = read_text("source", "functions", "sound.c")
    m = re.search(r"freqs\[64\]\s*=\s*\{([^}]*)\}", sound_c)
    check(m is not None and tuple(int(x) for x in m.group(1).split(",")) == bm.FREQS, "Z0/C1: таблиця частот нот збігається з sound.c")
    check("melody[(2 * i) + 1] * %d" % bm.UNIT_MS in sound_c, "Z0/C1: одиниця тривалості %d мс -- з sound.c" % bm.UNIT_MS)
    check(re.search(r"for\s*\(\s*uint16_t\s+i\s*=\s*0\s*;\s*i\s*<\s*%d\s*;" % bm.MAX_NOTES, sound_c) is not None, "Z0/C1: не більше %d пар -- з sound.c" % bm.MAX_NOTES)
    splash_c = read_text("source", "user_interface", "uiSplashScreen.c")
    check("uint8_t melodyBuf[%d]" % bm.BLOCK_LEN in splash_c, "Z0/C1: буфер мелодії %d Б -- з uiSplashScreen.c" % bm.BLOCK_LEN)


# ----------------------------------------------------------------------------------------------------------------------
#  Z2: TLE
# ----------------------------------------------------------------------------------------------------------------------

LOOK = "0123456789. +-*"


def ck(line68):
    s = 0
    for ch in line68:
        if ch.isdigit():
            s += int(ch)
        elif ch == "-":
            s += 1
    return s % 10


def mk_tle(name, norad, yy, day, ndot=" .00000000", inc=51.6416, raan=247.4627, ecc=6703, argp=130.5360, ma=325.0288, mm=15.72125391, rev=56353):
    l1 = "1 %05dU 98067A   %02d%012.8f %s  00000-0 -11606-4 0  292" % (norad, yy, day, ndot)
    l2 = "2 %05d %8.4f %8.4f %07d %8.4f %8.4f %11.8f%05d" % (norad, inc, raan, ecc, argp, ma, mm, rev)
    assert len(l1) == 68 and len(l2) == 68, (len(l1), len(l2))
    return name, l1 + str(ck(l1)), l2 + str(ck(l2))


ISS = ("ISS (ZARYA)", "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927", "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537")


def nib(text, nbytes):
    text = text.ljust(2 * nbytes)
    out = bytearray()
    for i in range(0, 2 * nbytes, 2):
        out.append(LOOK.index(text[i]) * 16 + LOOK.index(text[i + 1]))
    return bytes(out)


def expected_record(name, l1, l2, rx=0, tx=0, ctcss=0):
    """Запис блока за таблицею A1, зібраний незалежно від sat_tle (лише struct і власна нібл-функція)."""
    f1 = l1[18:20] + l1[20:32] + l1[33:43]
    f2 = l2[8:16] + l2[17:25] + l2[26:33] + l2[34:42] + l2[43:51] + l2[52:63] + l2[63:68] + " "
    assert len(f1) == 24 and len(f2) == 56
    return struct.pack("<8s12s28sIIHHIIII24s", name.encode("ascii").ljust(8, b"\0"), nib(f1, 12), nib(f2, 28), rx, tx, ctcss, 0, 0, 0, 0, 0, b"\0" * 24)


FW_SAT = {}


def fw_sat_exe():
    """gcc-харнес: РЕАЛЬНІ decompressTleData + satelliteTLE2Native з satellite.c; satelliteSetElementsTLE2Native замінено друкарем аргументів."""
    if "exe" in FW_SAT:
        return FW_SAT["exe"]
    src = read_text("source", "functions", "satellite.c")
    a = src.index("static float satelliteGetElement")
    b = src.index("uint32_t satelliteDayFn")
    code = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define ONEPPM 1.0e-6
typedef struct { double RA; } satelliteKeps_t;
typedef struct { char name[17]; satelliteKeps_t keps; } satelliteData_t;
static void satelliteSetElementsTLE2Native(float YE_in, float TE_in, float M2_in, float IN_in, float RA_in, float EC_in, float WP_in, float MA_in,
                                           float MM_in, float RV_in, float ALON_in, satelliteKeps_t *k)
{
	(void)k;
	printf("%.9g %.9g %.9g %.9g %.9g %.9g %.9g %.9g %.9g %.9g %.9g\n", YE_in, TE_in, M2_in, IN_in, RA_in, EC_in, WP_in, MA_in, MM_in, RV_in, ALON_in);
}
""" + src[a:b] + r"""
static int hexv(char c) { return (c >= '0' && c <= '9') ? c - '0' : c - 'a' + 10; }
int main(int argc, char **argv)
{
	uint8_t k1[12], k2[28];
	satelliteData_t d;
	(void)argc;
	for (int i = 0; i < 12; i++) k1[i] = (uint8_t)(hexv(argv[2][2 * i]) * 16 + hexv(argv[2][2 * i + 1]));
	for (int i = 0; i < 28; i++) k2[i] = (uint8_t)(hexv(argv[3][2 * i]) * 16 + hexv(argv[3][2 * i + 1]));
	satelliteTLE2Native(argv[1], k1, k2, &d);
	printf("%s\n", d.name);
	return 0;
}
"""
    d = tempfile.mkdtemp(prefix="r35sat_")
    cpath, exe = os.path.join(d, "t.c"), os.path.join(d, "t")
    open(cpath, "w", encoding="utf-8").write(code)
    try:
        r = subprocess.run(["gcc", "-O1", "-w", "-o", exe, cpath, "-lm"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print("ПРОПУЩЕНО (gcc):", e)
        FW_SAT["exe"] = None
        return None
    if r.returncode != 0:
        print(r.stderr[:2000])
        FW_SAT["exe"] = False
    else:
        FW_SAT["exe"] = exe
    return FW_SAT["exe"]


def fw_decode(rec100):
    exe = fw_sat_exe()
    name = rec100[:8].split(b"\0")[0].decode("ascii")
    r = subprocess.run([exe, name, rec100[8:20].hex(), rec100[20:48].hex()], capture_output=True, text=True, timeout=20)
    lines = r.stdout.strip().split("\n")
    return [f32(float(x)) for x in lines[0].split()], lines[1]


def expected_elements(l1, l2):
    """Те, що має отримати satelliteSetElementsTLE2Native, з урахуванням того, що satelliteGetElement повертає float."""
    ge = lambda s: f32(float(s))      # noqa: E731
    return [f32(ge(l1[18:20]) + 2000), ge(l1[20:32]), ge(l1[33:43]), ge(l2[8:16]), ge(l2[17:25]), f32(ge(l2[26:33]) * 1.0e-7), ge(l2[34:42]), ge(l2[43:51]),
            ge(l2[52:63]), f32(ge(l2[63:68]) + 1.0e-6), 0.0]


def test_tle():
    # --- розбір: пробіли, CRLF, порожні рядки, BOM, назва з префіксом "0 ", неповні й зіпсовані записи ---
    name, l1, l2 = ISS
    check(ck(l1[:68]) == int(l1[68]) and ck(l2[:68]) == int(l2[68]), "Z2: еталонний TLE МКС має правильні контрольні суми (незалежна функція)")
    n2, a1, a2 = mk_tle("AO-7", 7530, 24, 45.5)
    n3, b1, b2 = mk_tle("FO-29 (JAS-2)", 24278, 25, 300.12345678, ndot="-.00000123", inc=98.5, mm=13.52)
    n4, c1, c2 = mk_tle("TOOLONGSATNAME-X", 99999, 3, 1.0)
    text = "﻿" + "\r\n".join([name + "   ", l1 + "  ", l2, "", "  ", n2, a1, a2, "0 " + n3, b1 + " ", b2, n4, c1, c2]) + "\r\n"
    tles, notes = st.parse_tle_text(text)
    check([t.name for t in tles] == [name, n2, n3, n4] and all(t.ok for t in tles), "Z2: CRLF, порожні рядки, пробіли в кінці, BOM, префікс «0 »: %r %r" % (tles, notes))
    check([t.short_name() for t in tles] == ["ISS", "AO-7", "FO-29", "TOOLONGS"], "Z2: короткі назви: %r" % [t.short_name() for t in tles])
    check(tles[0].catalog == "25544" and tles[0].epoch == datetime.datetime(2008, 1, 1) + datetime.timedelta(days=263.51782528), "Z2: номер NORAD і епоха МКС")
    # неповний запис: рядок 1 без рядка 2
    tles, notes = st.parse_tle_text("\n".join([name, l1, "SOMETHING", n2, a1, a2]))
    check([t.name for t in tles] == [n2] and notes, "Z2: неповний запис (нема рядка 2) пропущено з зауваженням, наступний розібрано: %r %r" % (tles, notes))
    tles, notes = st.parse_tle_text("\n".join([name, l1]))
    check(tles == [] and notes, "Z2: файл обривається посеред запису -- нічого не розібрано, є зауваження: %r" % notes)
    tles, notes = st.parse_tle_text("\n".join([name, l2, n2, a1, a2]))
    check([t.name for t in tles] == [n2] and notes, "Z2: рядок 2 без рядка 1 пропущено")
    tles, notes = st.parse_tle_text("це не TLE\nа просто текст\n")
    check(tles == [] and notes, "Z2: сміття -- порожній результат й зауваження")
    tles, notes = st.parse_tle_text("")
    check(tles == [] and notes, "Z2: порожній файл")
    bad = l1[:-1] + str((int(l1[-1]) + 1) % 10)
    tles, notes = st.parse_tle_text("\n".join([name, bad, l2]))
    check(len(tles) == 1 and not tles[0].ok and "контрольна сума" in tles[0].problems[0], "Z2: зіпсована контрольна сума -> набір непридатний із причиною: %r" % tles[0].problems)
    short = l1[:50]
    tles, notes = st.parse_tle_text("\n".join([name, short, l2]))
    check(not any(t.ok for t in tles), "Z2: надто короткий рядок 1 -- непридатний")
    # символи, яких блок не вміщує (літера у числовому полі)
    weird = l1[:20] + "26A.51782528" + l1[32:68]
    weird += str(ck(weird))
    tles, notes = st.parse_tle_text("\n".join([name, weird, l2]))
    check(tles and not tles[0].ok, "Z2: нечислове поле епохи -- непридатний, запис не буде створено: %r" % (tles[0].problems if tles else None))
    # --- байти блока рівно за A1 ---
    recs = [mk_tle("SAT%d" % i, 40000 + i, 20 + i, 10.0 + 33 * i, mm=14.0 + i / 10.0) for i in range(5)]
    tl = [st.Tle(n, a, b) for n, a, b in recs]
    slots = [st.Slot.from_tle(t) for t in tl]
    slots[1].rx1, slots[1].tx1, slots[1].ctcss = 145_925_000, 435_300_000, 670
    blk = st.build_block(slots)
    exp = b"".join(expected_record(n, a, b, (145_925_000 if i == 1 else 0), (435_300_000 if i == 1 else 0), (670 if i == 1 else 0)) for i, (n, a, b) in enumerate(recs))
    check(len(blk) == 2520 and blk == exp + bytes(2520 - len(exp)), "Z2/A1: блок для 5 супутників = 2520 Б, байти збігаються з незалежно зібраними за таблицею A1")
    check(blk[500:] == bytes(2020), "Z2/A1: решта слотів і добивка 20 Б -- нулі")
    back = st.parse_block(blk)
    check([s.name for s in back.slots] == [r[0] for r in recs] and back.slots[1].rx1 == 145_925_000 and back.slots[1].ctcss == 670 and back.hidden == 0,
          "Z2: parse_block(build_block(...)) повертає слоти")
    check(st.build_block(back.slots) == blk, "Z2: збирання розібраного блока дає ті самі байти")
    # повний блок 25
    many = [st.Slot.from_tle(st.Tle(*mk_tle("S%d" % i, 50000 + i, 21, 5.0 + i))) for i in range(25)]
    check(len(st.build_block(many)) == 2520, "Z2: 25 слотів -- рівно 2520 Б")
    try:
        st.build_block(many + [many[0]])
        check(False, "Z2: 26 слотів мали бути відхилені")
    except st.SatError:
        pass
    # приховані записи після порожнього слота
    raw = bytearray(blk)
    raw[24 * 100:25 * 100] = exp[:100]
    pb = st.parse_block(bytes(raw))
    check(len(pb.slots) == 5 and pb.hidden == 1, "Z2: запис після порожнього слота прошивка не бачить -- hidden=1 (%d)" % pb.hidden)
    # назви: порожня й довша за 8 символів відхиляються
    for bad_name in ("", "TOOLONGNAME"):
        try:
            st.Slot(bad_name, slots[0].l1, slots[0].l2).pack()
            check(False, "Z2: назва %r мала бути відхилена" % bad_name)
        except st.SatError:
            pass
    # --- прошивка розпаковує записи в ті самі числа, що стоять у TLE ---
    exe = fw_sat_exe()
    if exe:
        rnd = random.Random(35)
        sample = [ISS]
        for i in range(40):
            sample.append(mk_tle("R%d" % i, rnd.randrange(1, 99999), rnd.randrange(0, 40), rnd.uniform(1.0, 366.99), ndot=rnd.choice([" .00000000", "-.00002182", " .00012345", "-.00000001"]),
                                 inc=rnd.uniform(0, 179.9999), raan=rnd.uniform(0, 359.9999), ecc=rnd.randrange(0, 9999999), argp=rnd.uniform(0, 359.9999), ma=rnd.uniform(0, 359.9999),
                                 mm=rnd.uniform(0.5, 16.99999999), rev=rnd.randrange(0, 99999)))
        bad_n = 0
        for n, a, b in sample:
            slot = st.Slot.from_tle(st.Tle(n, a, b))
            rec = slot.pack()
            got, nm = fw_decode(rec)
            want = expected_elements(a, b)
            if got != want or nm != slot.name:
                bad_n += 1
                print("  розбіжність", n, got, want, nm)
        check(bad_n == 0, "Z2/A1: РЕАЛЬНА satelliteTLE2Native з satellite.c розпаковує %d записів у ті самі числа, що в TLE (розбіжностей %d)" % (len(sample), bad_n))
        got, nm = fw_decode(st.Slot.from_tle(st.Tle(*ISS)).pack())
        check(abs(got[3] - 51.6416) < 1e-4 and abs(got[8] - 15.72125391) < 1e-5 and nm == "ISS", "Z2/A1: МКС після розпаковування прошивкою: нахил 51.6416, рух 15.7212539")
    # --- пошук, лічильники, злиття, оновлення ---
    big = [st.Tle(*mk_tle("SAT-%02d (X%d)" % (i, i), 10000 + i, 25, 100.0 + i)) for i in range(30)]
    check(len(st.filter_tles(big, "sat-0")) == 10 and len(st.filter_tles(big, "10005")) == 1 and len(st.filter_tles(big, "")) == 30 and st.filter_tles(big, "nope") == [],
          "Z2/A4: пошук за назвою (без регістру) і за номером NORAD")
    check("Знайдено 30, відібрано 28" in st.counts_line(30, 28, 0) and "не влізе 3" in st.counts_line(30, 28, 0) and "вільних 5" in st.counts_line(30, 3, 20),
          "Z2/A4: лічильники «знайдено / відібрано / влізе»: %s | %s" % (st.counts_line(30, 28, 0), st.counts_line(30, 3, 20)))
    merged, dropped = st.merge_add([], big[:27])
    check(len(merged) == 25 and dropped == 2, "Z2/A4: 27 відібраних -- у 25 слотів влізло, 2 відкинуто (%d, %d)" % (len(merged), dropped))
    cur = [st.Slot.from_tle(big[3], name="SAT-03")]
    cur[0].rx1, cur[0].tx1, cur[0].ctcss, cur[0].extra = 145_800_000, 435_000_000, 885, b"extra-data"
    fresh = [st.Tle(*mk_tle("SAT-03 (X3)", 10003, 26, 200.0, inc=60.0))]
    m = st.match_updates(cur, fresh)
    upd = st.apply_updates(cur, {m[0][0]: m[0][1][0]})
    check(len(m) == 1 and upd[0].name == "SAT-03" and (upd[0].rx1, upd[0].tx1, upd[0].ctcss) == (145_800_000, 435_000_000, 885) and upd[0].extra.startswith(b"extra-data")
          and upd[0].l1 != cur[0].l1 and abs(upd[0].inclination - 60.0) < 1e-6, "Z2/A4: оновлення елементів зберігає назву, частоти, субтон і AdditionalData")
    amb = st.match_updates(cur, [st.Tle(*mk_tle("SAT-03 (X3)", 10003, 26, 200.0)), st.Tle(*mk_tle("SAT-03", 10003, 26, 201.0))])
    check(len(amb) == 1 and len(amb[0][1]) == 2, "Z2/A4: два набори з однаковою назвою -- неоднозначність видно")
    # --- застарілі елементи (A5) ---
    now = datetime.datetime(2026, 10, 10)
    old = st.Slot.from_tle(st.Tle(*mk_tle("OLDSAT", 1, 26, 100.0)))        # 2026-04-10
    new = st.Slot.from_tle(st.Tle(*mk_tle("NEWSAT", 2, 26, 270.0)))        # 2026-09-27
    txt = st.stale_text([old, new], now=now)
    check("OLDSAT" in txt and "NEWSAT" not in txt and "старші за 30" in txt, "Z2/A5: попередження про епоху старшу за місяць -- лише для старого: %r" % txt)
    check(st.stale_text([new], now=now) == "", "Z2/A5: свіжі елементи -- без попередження")
    # --- запис на підробленій рації ---
    spi = spi_region()
    before = bytes(spi)
    radio = tcr.FakeRadioX(bytearray(spi))
    d = tempfile.mkdtemp(prefix="r35sat_w_")
    state, blk0, raw0 = st.read_slots(radio)
    check(state == st.ST_OK and raw0 == region_payloads()[3], "Z2/A5: читання наявного блока супутників (сирі байти збігаються)")
    with WriteLog() as wl:
        text, safety = st.write_slots(radio, slots, safety_dir=d, log=quiet)
    after = bytes(radio.spi)
    pos, _n = block_addr(spi, 3)
    check(after[cd.FLASH_BASE + pos + 8:cd.FLASH_BASE + pos + 8 + 2520] == blk, "Z2/A5: блок у рації == збудований байт-в-байт")
    check(open(safety, "rb").read() == region_payloads()[3] and "Звірка читанням: OK" in text, "Z2/A5: страхова копія = старий блок; звірка читанням пройшла")
    check(all(cd.FLASH_BASE <= a and a + n <= cd.FLASH_BASE + 0x10000 for a, n in wl.calls) and t31.untouched_outside(before, after, cd.FLASH_BASE + pos, cd.FLASH_BASE + pos + 8 + 2520),
          "Z2/Z6: запис торкнувся лише області custom-data й лише цього блока")
    # блок іншої довжини -- відмова
    bad_payloads = region_payloads()
    bad_payloads[3] = bad_payloads[3][:2000]
    r2 = tcr.FakeRadioX(bytearray(spi_region(payloads=bad_payloads)))
    try:
        st.write_slots(r2, slots, safety_dir=d, log=quiet)
        check(False, "Z2: блок нестандартної довжини мав бути відхилений")
    except RuntimeError as e:
        check(r2.x_total == 0 and "довжин" in str(e), "Z2/A5: блок іншої довжини -- відмова словами, у рацію нічого: %s" % e)
    # області немає
    r3 = tcr.FakeRadioX(bytearray(spi_region(magic=False)))
    try:
        st.write_slots(r3, slots, safety_dir=d, log=quiet)
        check(False, "Z2: без області мав бути відхилений")
    except RuntimeError:
        check(r3.x_total == 0, "Z2: нема області OpenGD77 -- відмова, у рацію нічого")
    # блока нема: створюється
    r4 = tcr.FakeRadioX(bytearray(spi_region(types=(4, 5, 8))))
    text4, safety4 = st.write_slots(r4, slots, safety_dir=d, log=quiet)
    check(safety4 is None and st.read_slots(r4)[0] == st.ST_OK and "створено" in text4, "Z2/A5: блока не було -- створено новий (страхової копії нема, бо нема що зберігати)")
    # --- мережа: локальний HTTP-сервер, лише явні виклики ---
    import http.server
    import socketserver
    body = "\r\n".join([name, l1, l2, n2, a1, a2]).encode() + b"\r\n"

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/ok":
                rng = self.headers.get("Range")
                data = body[:int(rng.split("-")[1]) + 1] if rng else body
                self.send_response(206 if rng else 200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(data)))
                if rng:
                    self.send_header("Content-Range", "bytes 0-%d/%d" % (len(data) - 1, len(body)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path == "/html":
                data = b"<html><body>Access denied</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                data = b"not found"
                self.send_response(404)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = "http://127.0.0.1:%d" % port
        pr = st.probe_url(base + "/ok", nbytes=2048)
        check(pr["ok"] and pr["sets"] == 2 and "ISS" in pr["head"] and "ПІДХОДИТЬ" in st.probe_text(pr), "Z2/A3: «Перевірити джерело» показує початок і розпізнає набори: %s" % st.probe_text(pr).split("\n")[0])
        pr2 = st.probe_url(base + "/html")
        check(not pr2["ok"] and "Access denied" in pr2["head"] and "НЕ розпізнає" in st.probe_text(pr2), "Z2/A3: HTML замість TLE -- показано вміст і чесно сказано, що не підходить")
        pr3 = st.probe_url(base + "/missing")
        check(not pr3["ok"] and pr3["status"] == 404 and "404" in st.probe_text(pr3), "Z2/A3: 404 -- код відповіді видно")
        dest = os.path.join(d, "net.tle")
        n_ = st.download(base + "/ok", dest)
        check(n_ == len(body) and open(dest, "rb").read() == body and not os.path.exists(dest + ".part"), "Z2/A3: завантаження кладе рівно те, що віддав сервер")
        try:
            st.download(base + "/missing", os.path.join(d, "x.tle"))
            check(False, "Z2/A3: 404 мав дати помилку")
        except Exception:  # noqa: BLE001
            check(not os.path.exists(os.path.join(d, "x.tle")), "Z2/A3: невдале завантаження не лишає файла")
    finally:
        srv.shutdown()
        srv.server_close()
    for bad_url in ("ftp://x/y", "celestrak.org/x", ""):
        try:
            st.probe_url(bad_url)
            check(False, "Z2/A3: адреса %r мала бути відхилена" % bad_url)
        except st.SatError:
            pass
    check(st.CELESTRAK_AMATEUR.startswith("https://celestrak.org/"), "Z2/A3: адреса пресету -- з брифу; НЕ перевірена в цій збірці (див. звіт)")


# ----------------------------------------------------------------------------------------------------------------------
#  Z3: картинка заставки
# ----------------------------------------------------------------------------------------------------------------------

def png_chunk(tag, body):
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)


ADAM7 = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def pack_bits(vals, depth):
    per = 8 // depth
    out = bytearray()
    for i in range(0, len(vals), per):
        b = 0
        for k in range(per):
            v = vals[i + k] if i + k < len(vals) else 0
            b |= v << (8 - depth * (k + 1))
        out.append(b)
    return bytes(out)


def scan_rows(pixels, depth, x0, y0, dx, dy, w, h):
    rows = []
    for y in range(y0, h, dy):
        px = [pixels[y][x] for x in range(x0, w, dx)]
        if not px:
            continue
        if depth < 8:
            rows.append(pack_bits([p[0] for p in px], depth))
        elif depth == 8:
            rows.append(bytes(c for p in px for c in p))
        else:
            rows.append(b"".join(struct.pack(">H", c) for p in px for c in p))
    return rows


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def filter_rows(rows, bpp, rnd):
    out = bytearray()
    if not rows:
        return b""
    prev = bytes(len(rows[0]))
    for row in rows:
        ft = rnd.randrange(5)
        out.append(ft)
        for i, x in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = (0, a, b, (a + b) // 2, paeth(a, b, c))[ft]
            out.append((x - pred) & 0xFF)
        prev = row
    return bytes(out)


def png_encode(w, h, ctype, depth, pixels, palette=None, trns=None, interlace=False, rnd=None):
    rnd = rnd or random.Random(1)
    bpp = max(1, CHANNELS[ctype] * depth // 8)
    if interlace:
        data = b""
        for x0, y0, dx, dy in ADAM7:
            data += filter_rows(scan_rows(pixels, depth, x0, y0, dx, dy, w, h), bpp, rnd)
    else:
        data = filter_rows(scan_rows(pixels, depth, 0, 0, 1, 1, w, h), bpp, rnd)
    out = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 1 if interlace else 0))
    if palette:
        out += png_chunk(b"PLTE", b"".join(bytes(c) for c in palette))
    if trns is not None:
        out += png_chunk(b"tRNS", bytes(trns))
    return out + png_chunk(b"IDAT", zlib.compress(data, 6)) + png_chunk(b"IEND", b"")


def lum(r, g, b):
    return (299 * r + 587 * g + 114 * b + 500) // 1000


def over(v, a):
    return v if a >= 255 else (v * a + 255 * (255 - a) + 127) // 255


def expected_gray(ctype, depth, p, palette, trns):
    if ctype == 0:
        return round(p[0] * 255 / ((1 << depth) - 1))
    if ctype == 4:
        v = p[0] if depth == 8 else p[0] >> 8
        a = p[1] if depth == 8 else p[1] >> 8
        return over(v, a)
    if ctype == 2:
        c = [x if depth == 8 else x >> 8 for x in p]
        return lum(*c)
    if ctype == 6:
        r, g, b, a = [x if depth == 8 else x >> 8 for x in p]
        return over(lum(r, g, b), a)
    if ctype == 3:
        r, g, b = palette[p[0]]
        a = trns[p[0]] if trns is not None and p[0] < len(trns) else 255
        return over(lum(r, g, b), a)
    raise AssertionError


def gen_png_case(rnd, w, h, ctype, depth, interlace, with_trns=False):
    maxv = (1 << depth) - 1
    palette = trns = None
    if ctype == 3:
        palette = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(1 << depth)]
        if with_trns:
            trns = [rnd.randrange(256) for _ in range(max(1, (1 << depth) // 2))]
        pix = [[(rnd.randrange(1 << depth),) for _ in range(w)] for _ in range(h)]
    else:
        pix = [[tuple(rnd.randrange(maxv + 1) for _ in range(CHANNELS[ctype])) for _ in range(w)] for _ in range(h)]
    data = png_encode(w, h, ctype, depth, pix, palette, trns, interlace, rnd)
    exp = bytes(expected_gray(ctype, depth, pix[y][x], palette, trns) for y in range(h) for x in range(w))
    return data, exp, pix


def bmp_encode(w, h, bpp, pixels, palette=None, top_down=False):
    """pixels[y][x]: bpp 24/32 -- (r,g,b[,a]); bpp 1/4/8 -- індекс палітри."""
    rowbytes = ((w * bpp + 31) // 32) * 4
    rows = []
    for y in range(h):
        row = bytearray()
        if bpp in (24, 32):
            for x in range(w):
                p = pixels[y][x]
                row += bytes([p[2], p[1], p[0]]) + (bytes([p[3] if len(p) > 3 else 255]) if bpp == 32 else b"")
        else:
            row = bytearray(pack_bits([pixels[y][x] for x in range(w)], bpp))
        row = bytes(row).ljust(rowbytes, b"\0")
        rows.append(row)
    if not top_down:
        rows.reverse()
    pal = b"".join(bytes([c[2], c[1], c[0], 0]) for c in palette) if palette else b""
    off = 14 + 40 + len(pal)
    body = b"".join(rows)
    hdr = struct.pack("<2sIHHI", b"BM", off + len(body), 0, 0, off)
    dib = struct.pack("<IiiHHIIiiII", 40, w, -h if top_down else h, 1, bpp, 0, len(body), 2835, 2835, len(palette) if palette else 0, 0)
    return hdr + dib + pal + body


def fit_geometry(sw, sh, mode):
    """Незалежний розрахунок: прямокутник (x0, y0, x1, y1), який має займати картинка на 128x64."""
    if mode in ("fill", "stretch"):
        return 0, 0, 128, 64
    sc = min(128 / sw, 64 / sh)
    nw, nh = max(1, min(128, round(sw * sc))), max(1, min(64, round(sh * sc)))
    ox, oy = (128 - nw) // 2, (64 - nh) // 2
    return ox, oy, ox + nw, oy + nh


def bbox_of(ink):
    xs = [i % 128 for i, v in enumerate(ink) if v]
    ys = [i // 128 for i, v in enumerate(ink) if v]
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None


FW_IMG = {}


def fw_image_exe():
    """gcc-харнес: РЕАЛЬНА displayConvertGD77ImageData з HX8353E_display.c (screenBuf, кольори тла/переднього плану -- підставні)."""
    if "exe" in FW_IMG:
        return FW_IMG["exe"]
    src = read_text("source", "hardware", "HX8353E_display.c")
    a = src.index("void displayConvertGD77ImageData(uint8_t *dataBuf)")
    b = src.index("\n}\n", a) + 3
    code = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define DISPLAY_SIZE_X 160
#define DISPLAY_SIZE_Y 128
static uint16_t screenBuf[DISPLAY_SIZE_X * DISPLAY_SIZE_Y];
static uint16_t backgroundColour = 1, foregroundColour = 2;
""" + src[a:b] + r"""
static int hexv(char c) { return (c >= '0' && c <= '9') ? c - '0' : c - 'a' + 10; }
int main(int argc, char **argv)
{
	uint8_t buf[1024];
	(void)argc;
	for (int i = 0; i < 1024; i++) buf[i] = (uint8_t)(hexv(argv[1][2 * i]) * 16 + hexv(argv[1][2 * i + 1]));
	displayConvertGD77ImageData(buf);
	for (int i = 0; i < DISPLAY_SIZE_X * DISPLAY_SIZE_Y; i++) putchar('0' + screenBuf[i]);
	putchar('\n');
	return 0;
}
"""
    d = tempfile.mkdtemp(prefix="r35img_")
    cpath, exe = os.path.join(d, "t.c"), os.path.join(d, "t")
    open(cpath, "w", encoding="utf-8").write(code)
    try:
        r = subprocess.run(["gcc", "-O1", "-w", "-o", exe, cpath], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print("ПРОПУЩЕНО (gcc):", e)
        FW_IMG["exe"] = None
        return None
    if r.returncode != 0:
        print(r.stderr[:2000])
        FW_IMG["exe"] = False
    else:
        FW_IMG["exe"] = exe
    return FW_IMG["exe"]


def test_image():
    rnd = random.Random(3501)
    # --- розкладка блока: незалежна формула + РЕАЛЬНА функція прошивки ---
    ink = bytes(rnd.randrange(2) for _ in range(128 * 64))
    blk = si.ink_to_block(ink)
    exp = bytearray(1024)
    for y in range(64):
        for x in range(128):
            if not ink[y * 128 + x]:
                exp[(y // 8) * 128 + x] |= 1 << (y % 8)
    check(len(blk) == 1024 and blk == bytes(exp), "Z3/B1: ink -> блок: байт[сторінка*128+x], біт y%8, біт 0 = передній план (незалежна формула)")
    check(si.block_to_ink(blk) == ink and si.block_to_ink(blk + b"\x55" * 40) == ink, "Z3/B1: блок -> ink -- обернення; зайві байти ігноруються")
    check(si.ink_to_block(bytes(8192)) == b"\xff" * 1024 and si.ink_to_block(bytes([1]) * 8192) == bytes(1024), "Z3/B1: без переднього плану -- усі біти 1; увесь передній план -- усі 0")
    try:
        si.block_to_ink(blk[:1000])
        check(False, "Z3: короткий блок мав бути відхилений")
    except si.ImageError:
        pass
    exe = fw_image_exe()
    if exe:
        for case in ("random", "sparse", "full"):
            ink_c = ink if case == "random" else (bytes(1 if rnd.random() < 0.03 else 0 for _ in range(8192)) if case == "sparse" else bytes([1]) * 8192)
            out = subprocess.run([exe, si.ink_to_block(ink_c).hex()], capture_output=True, text=True, timeout=20).stdout.strip()
            bad = 0
            for y in range(128):
                for x in range(160):
                    ch = out[y * 160 + x]
                    inside = 16 <= x < 144 and 32 <= y < 96
                    if inside:
                        want = "2" if ink_c[(y - 32) * 128 + (x - 16)] else "1"
                    else:
                        want = "1" if y * 160 + x < 512 else "0"
                    if ch != want:
                        bad += 1
            check(bad == 0, "Z3/B1: РЕАЛЬНА displayConvertGD77ImageData малює наш блок (%s) на екрані 160x128 у (16,32), 1 -> тло, 0 -> передній план; розбіжностей %d" % (case, bad))
        scr = si.screen_rgb(ink, (255, 0, 0), (0, 0, 255))
        out = subprocess.run([exe, blk.hex()], capture_output=True, text=True, timeout=20).stdout.strip()
        bad = sum(1 for i in range(160 * 128) if (out[i] == "2") != (scr[3 * i:3 * i + 3] == bytes((255, 0, 0))) and not (out[i] == "0" and scr[3 * i:3 * i + 3] == bytes((0, 0, 255))) and not (out[i] == "1" and scr[3 * i:3 * i + 3] == bytes((0, 0, 255))))
        check(bad == 0, "Z3/B2: screen_rgb (передпоказ) збігається з тим, що малює прошивка")
    # --- декодери PNG: усі типи, глибини, переплетення, фільтри ---
    cases = [(0, 1), (0, 2), (0, 4), (0, 8), (0, 16), (4, 8), (4, 16), (2, 8), (2, 16), (6, 8), (6, 16), (3, 1), (3, 2), (3, 4), (3, 8)]
    n_ok = 0
    for ctype, depth in cases:
        for interlace in (False, True):
            for (w, h) in ((13, 7), (1, 1), (8, 8), (5, 17)):
                for trns in ((False, True) if ctype == 3 else (False,)):
                    data, exp_g, _pix = gen_png_case(rnd, w, h, ctype, depth, interlace, trns)
                    try:
                        g = si.decode(data)
                    except Exception as e:  # noqa: BLE001
                        check(False, "Z3/B2: PNG тип %d глибина %d переплетення %s %dx%d не прочитано: %s" % (ctype, depth, interlace, w, h, e))
                        continue
                    diff = max(abs(a - b) for a, b in zip(g.data, exp_g)) if len(g.data) == len(exp_g) else 999
                    if (g.w, g.h) != (w, h) or diff > 1:
                        check(False, "Z3/B2: PNG тип %d глибина %d переплетення %s %dx%d%s: розмір %sx%s, найбільша різниця %d" % (ctype, depth, interlace, w, h, " +tRNS" if trns else "", g.w, g.h, diff))
                    else:
                        n_ok += 1
    check(n_ok == len(cases) * 2 * 4 + 4 * 2 * 4, "Z3/B2: PNG усіх типів/глибин, з переплетенням і без, з фільтрами 0-4 і tRNS декодуються в яскравість (різниця <= 1): %d варіантів" % n_ok)
    # прозорість змішується з тлом (білим за замовчуванням, чорним на запит)
    rgba = png_encode(2, 1, 6, 8, [[(255, 255, 255, 0), (255, 255, 255, 255)]])
    check(si.decode(rgba).data == bytes([255, 255]) and si.decode(rgba, transparent_to=0).data == bytes([0, 255]), "Z3/B2: прозорі точки -> тло за вибором (біле / чорне)")
    # зіпсовані PNG
    good = png_encode(4, 4, 0, 8, [[(i,) for i in range(4)] for _ in range(4)])
    for what, bad in (("обрізаний", good[:40]), ("без IDAT", good.replace(b"IDAT", b"JUNK")), ("не стискається", good[:-20] + b"x" * 8 + good[-12:]), ("нульовий розмір", png_encode(4, 4, 0, 8, [[(1,)] * 4] * 4)[:16] + b"\0" * 8 + png_encode(4, 4, 0, 8, [[(1,)] * 4] * 4)[24:])):
        try:
            si.decode(bad)
            check(False, "Z3/B2: %s PNG мав дати помилку словами" % what)
        except si.ImageError as e:
            check(str(e) != "", "Z3: %s PNG -- помилка словами: %s" % (what, e))
        except Exception as e:  # noqa: BLE001
            check(False, "Z3/B2: %s PNG дав не ImageError, а %r" % (what, e))
    for what, data in (("JPEG", b"\xff\xd8\xff\xe0" + b"\0" * 20), ("GIF", b"GIF89a" + b"\0" * 20), ("сміття", b"hello world" * 3), ("порожній", b"")):
        try:
            si.decode(data)
            check(False, "Z3: %s мав бути відхилений" % what)
        except si.ImageError:
            pass
    # --- BMP / PNM ---
    for bpp, top in ((24, False), (24, True), (32, False), (8, False), (4, False), (1, False)):
        w, h = 11, 5
        if bpp in (24, 32):
            pix = [[tuple(rnd.randrange(256) for _ in range(3)) + ((255,) if bpp == 32 else ()) for _ in range(w)] for _ in range(h)]
            exp_g = bytes(lum(*pix[y][x][:3]) for y in range(h) for x in range(w))
            data = bmp_encode(w, h, bpp, pix, None, top)
        else:
            pal = [tuple(rnd.randrange(256) for _ in range(3)) for _ in range(1 << bpp)]
            pix = [[rnd.randrange(1 << bpp) for _ in range(w)] for _ in range(h)]
            exp_g = bytes(lum(*pal[pix[y][x]]) for y in range(h) for x in range(w))
            data = bmp_encode(w, h, bpp, pix, pal, top)
        try:
            g = si.decode(data)
            check((g.w, g.h) == (w, h) and max(abs(a - b) for a, b in zip(g.data, exp_g)) <= 1, "Z3/B2: BMP %d біт%s читається" % (bpp, ", зверху вниз" if top else ""))
        except Exception as e:  # noqa: BLE001
            check(False, "Z3/B2: BMP %d біт не прочитано: %s" % (bpp, e))
    g = si.decode(b"P5\n# comment\n3 2\n255\n" + bytes([0, 128, 255, 10, 20, 30]))
    check((g.w, g.h) == (3, 2) and g.data == bytes([0, 128, 255, 10, 20, 30]), "Z3/B2: PGM (P5) із коментарем")
    g = si.decode(b"P2\n3 1\n15\n0 5 15\n")
    check(g.data == bytes([0, 85, 255]), "Z3/B2: PGM (P2) шкала 15 -> 255")
    g = si.decode(b"P4\n8 1\n" + bytes([0b10100000]))
    check(g.data[:3] == bytes([0, 255, 0]), "Z3/B2: PBM (P4): біт 1 = чорний")
    g = si.decode(b"P6\n2 1\n255\n" + bytes([255, 0, 0, 0, 0, 255]))
    check(g.data == bytes([lum(255, 0, 0), lum(0, 0, 255)]), "Z3/B2: PPM (P6)")
    # --- вписування й квантування: розміри, не кратні цільовому ---
    sizes = [(128, 64), (256, 128), (100, 50), (300, 200), (64, 64), (1000, 3), (3, 1000), (129, 65), (127, 63), (1, 1), (500, 500), (640, 480), (10, 640)]
    for (sw, sh) in sizes:
        g = si.Gray(sw, sh, bytes([255]) * (sw * sh))                          # білий прямокутник
        for fit in ("fit", "fill", "stretch"):
            ink_ = si.convert(g, fit, "threshold", 128, True)
            if len(ink_) != 8192:
                check(False, "Z3/B3: %dx%d/%s -- ink не 8192" % (sw, sh, fit))
                continue
            bb = bbox_of(ink_)
            gx0, gy0, gx1, gy1 = fit_geometry(sw, sh, fit)
            full = sum(ink_) == (gx1 - gx0) * (gy1 - gy0)
            check(bb == (gx0, gy0, gx1, gy1) and full, "Z3/B3: білий %dx%d, режим %s: передній план займає рівно %s (є %s, точок %d з %d)" % (
                sw, sh, fit, (gx0, gy0, gx1, gy1), bb, sum(ink_), (gx1 - gx0) * (gy1 - gy0)))
            blk_ = si.ink_to_block(ink_)
            check(si.block_to_ink(blk_) == ink_, "Z3: блок -> ink -> те саме для %dx%d/%s" % (sw, sh, fit))
            png = si.ink_to_gray_png(ink_)
            gg = si.decode(png)
            check((gg.w, gg.h) == (128, 64) and bytes(255 if v else 0 for v in ink_) == gg.data, "Z3/B5: ink -> PNG -> декодер: ті самі точки (%dx%d/%s)" % (sw, sh, fit))
        # чорний вхід: нічого не світиться
        gb = si.Gray(sw, sh, bytes(sw * sh))
        check(sum(si.convert(gb, "fill", "threshold", 128, True)) == 0 and sum(si.convert(gb, "fill", "threshold", 128, False)) == 8192, "Z3/B3: чорне джерело: світлі=передній план -> порожньо; інверсія -> усе")
    # fit: поля -- це тло, навіть коли інверсія робить «темне» переднім планом
    g = si.Gray(100, 100, bytes(100 * 100))
    inv = si.convert(g, "fit", "threshold", 128, False)
    check(bbox_of(inv) == (32, 0, 96, 64) and sum(inv) == 64 * 64, "Z3/B3: інверсія у режимі «вписати»: поля лишаються тлом, передній план лише в межах картинки")
    # round trip рівно 128x64: без втрат
    ink_in = bytes(1 if ((x // 4 + y // 4) % 2 == 0 or (x * y) % 7 == 0) else 0 for y in range(64) for x in range(128))
    png_in = si.ink_to_gray_png(ink_in)
    for fit in ("fit", "fill", "stretch"):
        for quant in ("threshold", "dither", "bayer"):
            got = si.convert(si.decode(png_in), fit, quant, 128, True)
            if quant == "threshold":
                check(got == ink_in, "Z3: PNG 128x64 -> ink (поріг, %s) без втрат" % fit)
    got_blk = si.ink_to_block(si.convert(si.decode(png_in), "stretch", "threshold", 128, True))
    check(si.ink_to_gray_png(si.block_to_ink(got_blk)) == png_in, "Z3: PNG -> біти -> PNG повертає той самий файл байт-в-байт (128x64, 1 біт)")
    # чесне квантування: сірий градієнт -> частка передніх точок ~ яскравості
    for level in (32, 96, 128, 200):
        g = si.Gray(128, 64, bytes([level]) * 8192)
        for quant in ("dither", "bayer"):
            frac = sum(si.convert(g, "stretch", quant, 128, True)) / 8192.0
            check(abs(frac - level / 255.0) < 0.04, "Z3/B3: рівномірний сірий %d, %s: частка переднього плану %.3f ~ %.3f" % (level, quant, frac, level / 255.0))
        check(sum(si.convert(g, "stretch", "threshold", 128, True)) in (0, 8192), "Z3/B3: поріг дає лише чорне/біле")
    grad = si.Gray(128, 64, bytes(x * 2 for _y in range(64) for x in range(128)))
    f = si.convert(grad, "stretch", "dither", 128, True)
    left = sum(f[y * 128 + x] for y in range(64) for x in range(32)) / (64 * 32.0)
    right = sum(f[y * 128 + x] for y in range(64) for x in range(96, 128)) / (64 * 32.0)
    check(left < 0.25 and right > 0.7, "Z3/B3: градієнт у Флойді-Штейнберзі: ліва чверть темна (%.2f), права світла (%.2f)" % (left, right))
    # --- зображення з кольору: PNG RGB -> блок ---
    rgb = [[(255, 255, 255) if (x + y) % 2 else (0, 0, 0) for x in range(128)] for y in range(64)]
    g = si.decode(png_encode(128, 64, 2, 8, rgb))
    ink_ = si.convert(g, "fit", "threshold", 128, True)
    check(all(ink_[y * 128 + x] == ((x + y) % 2) for y in range(64) for x in range(128)), "Z3: кольоровий PNG-шахівниця -> ink точно по пікселях")
    # Pillow (лише перехресна перевірка тесту)
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image:
        import io
        for mode in ("RGB", "RGBA", "L", "P", "LA", "1"):
            im = Image.new(mode if mode != "P" else "RGB", (37, 29))
            px = im.load()
            for y in range(29):
                for x in range(37):
                    v = rnd.randrange(256)
                    if mode in ("RGB", "RGBA"):
                        px[x, y] = (rnd.randrange(256), rnd.randrange(256), v) + ((rnd.randrange(256),) if mode == "RGBA" else ())
                    elif mode == "LA":
                        px[x, y] = (v, rnd.randrange(256))
                    elif mode == "1":
                        px[x, y] = 255 * rnd.randrange(2)
                    else:
                        px[x, y] = (v, v // 2, 255 - v) if mode == "RGB" else v
            if mode == "P":
                im = im.convert("P", palette=Image.ADAPTIVE, colors=16)
            for kw in ({}, {"optimize": True}):
                buf = io.BytesIO()
                im.save(buf, "PNG", **kw)
                g = si.decode(buf.getvalue())
                ref = im.convert("RGBA")
                bg = Image.new("RGBA", ref.size, (255, 255, 255, 255))
                ref = Image.alpha_composite(bg, ref).convert("L")
                diff = max(abs(a - b) for a, b in zip(g.data, ref.tobytes()))
                check((g.w, g.h) == im.size and diff <= 2, "Z3/B2 (Pillow): PNG, створений Pillow (%s%s), наш декодер збігається з Pillow (різниця %d)" % (mode, ", optimize" if kw else "", diff))


def diff_positions(a, b):
    return [i for i in range(min(len(a), len(b))) if a[i] != b[i]]


def test_image_radio():
    d = tempfile.mkdtemp(prefix="r35img_")
    rnd = random.Random(77)
    ink = bytes(rnd.randrange(2) for _ in range(8192))
    spi = spi_region()
    before = bytes(spi)
    pos, ln = block_addr(spi, 1)
    lo, hi = cd.FLASH_BASE + pos, cd.FLASH_BASE + pos + 8 + 1024
    # --- читання ---
    radio = tcr.FakeRadioX(bytearray(spi))
    state, ink0, ln0 = si.read_image(radio)
    check(state == si.ST_OK and ln0 == 1024 and ink0 == si.block_to_ink(region_payloads()[1]), "Z3/B4: читання наявної картинки")
    # --- запис у наявний блок ---
    with WriteLog() as wl:
        text = si.write_image(radio, ink)
    after = bytes(radio.spi)
    check(after[lo + 8:hi] == si.ink_to_block(ink) and "Звірка" in text, "Z3/B4: блок у рації == ink_to_block(ink); звірка читанням в тексті")
    check(t31.untouched_outside(before, after, lo, hi) and all(lo - 4096 < a and a + n <= hi + 4096 and cd.FLASH_BASE <= a for a, n in wl.calls),
          "Z3/B4/Z6: змінено лише байти блока картинки; усі записи в межах області custom-data")
    check(not radio.cal_touched and bytes(radio.spi[:0x20000]) == before[:0x20000], "Z3/Z6: EEPROM і калібрування не зачеплені")
    state, ink1, _ = si.read_image(radio)
    check(state == si.ST_OK and ink1 == ink, "Z3/B4: прочитана назад картинка == записана")
    # --- вилучення ---
    radio.commits.clear()
    with WriteLog() as wl:
        text = si.remove_image(radio)
    after2 = bytes(radio.spi)
    dp = diff_positions(after, after2)
    check(dp and all(lo <= p < lo + 4 for p in dp), "Z3/B4: «Прибрати картинку» змінила лише поле типу в заголовку блока (байти %s)" % dp[:6])
    check(struct.unpack("<ii", after2[lo:lo + 8]) == (cd.RETIRED_BASE + 1, 1024) and after2[lo + 8:hi] == after[lo + 8:hi], "Z3/B4: тип = 0x7E000001, довжина й дані лишилися")
    check(si.read_image(radio)[0] == si.ST_ABSENT, "Z3/B4: після вилучення прошивка (find_or_alloc_block) картинки не бачить")
    # --- повторне додавання: новий блок після останнього ---
    t2 = si.write_image(radio, ink)
    after3 = bytes(radio.spi)
    newpos = block_addr(after3, 1)
    check(newpos is not None and newpos[0] > pos and newpos[1] == 1024, "Z3/B4: нова картинка лягла в НОВИЙ блок далі за старим (старе місце не перевикористано): %s" % (newpos,))
    check(after3[lo:hi] == after2[lo:hi] and si.read_image(radio)[1] == ink, "Z3/B4: вилучений блок не зачеплено, нова картинка читається")
    reg = cr.parse_region(after3[cd.FLASH_BASE:cd.FLASH_BASE + 0x10000])
    check(not reg.problems and any(cd.is_retired(b.type) for b in reg.blocks) and any(b.type == 1 for b in reg.blocks), "Z3/B4: custom_region бачить вилучений блок і новий без проблем: %r" % reg.problems)
    # ще раз вилучити й додати: два вилучені блоки того самого типу не вважаються помилкою
    si.remove_image(radio)
    si.write_image(radio, ink)
    reg = cr.parse_region(bytes(radio.spi[cd.FLASH_BASE:cd.FLASH_BASE + 0x10000]))
    check(not reg.problems and [b.type for b in reg.blocks].count(cd.RETIRED_BASE + 1) == 2, "Z3/B4: два вилучені блоки одного типу -- не помилка області: %r" % reg.problems)
    check(not cr.default_selected([b for b in reg.blocks if cd.is_retired(b.type)][0]), "Z3/B4: вилучений блок не потрапляє в «застосувати» типово")
    # --- блока нема ---
    r2 = tcr.FakeRadioX(bytearray(spi_region(types=(2, 3, 4, 5))))
    b2 = bytes(r2.spi)
    check(si.read_image(r2)[0] == si.ST_ABSENT, "Z3/B4: блока нема -- стан «нема»")
    si.write_image(r2, ink)
    p2 = block_addr(bytes(r2.spi), 1)
    check(p2 is not None and si.read_image(r2)[1] == ink and t31.untouched_outside(b2, bytes(r2.spi), cd.FLASH_BASE + p2[0], cd.FLASH_BASE + p2[0] + 8 + 1024),
          "Z3/B4: нову картинку створено в першому вільному місці, решта області не змінена")
    # --- нестандартна довжина ---
    pl = region_payloads()
    pl[1] = pl[1][:1000]
    r3 = tcr.FakeRadioX(bytearray(spi_region(payloads=pl)))
    check(si.read_image(r3)[0] == si.ST_BADLEN, "Z3/B4: блок 1000 Б -- стан «нестандартна довжина»")
    try:
        si.write_image(r3, ink)
        check(False, "Z3/B4: запис у блок нестандартної довжини мав бути відхилений")
    except RuntimeError as e:
        check(r3.x_total == 0, "Z3/B4: відмова словами, у рацію нічого: %s" % e)
    si.remove_image(r3)
    si.write_image(r3, ink)
    check(si.read_image(r3)[0] == si.ST_OK, "Z3/B4: вилучити й записати знову -- шлях для блока нестандартної довжини працює")
    # --- області нема ---
    r4 = tcr.FakeRadioX(bytearray(spi_region(magic=False)))
    for fn, nm in ((lambda: si.write_image(r4, ink), "запис"), (lambda: si.remove_image(r4), "вилучення")):
        try:
            fn()
            check(False, "Z3: %s без області мало бути відхилене" % nm)
        except RuntimeError:
            pass
    check(r4.x_total == 0 and si.read_image(r4)[0] == si.ST_NOREGION, "Z3/B4: без області OpenGD77 -- відмова, у рацію нічого")
    # --- місця нема ---
    pl = {4: bytes(0xFF00 - 12 - 8)}
    r5 = tcr.FakeRadioX(bytearray(spi_region(types=(4,), payloads=pl)))
    try:
        si.write_image(r5, ink)
        check(False, "Z3/B4: без місця запис мав бути відхилений")
    except RuntimeError as e:
        check(r5.x_total == 0, "Z3/B4: нема місця в області -- відмова, у рацію нічого: %s" % e)
    # remove, коли блока нема
    try:
        si.remove_image(tcr.FakeRadioX(bytearray(spi_region(types=(2,)))))
        check(False, "Z3: вилучення неіснуючого блока мало дати помилку")
    except RuntimeError:
        pass
    # --- PNG збереження картинки з рації ---
    png = si.ink_to_gray_png(ink)
    gg = si.decode(png)
    check(gg.data == bytes(255 if v else 0 for v in ink), "Z3/B5: PNG з картинки з рації розкодовується назад у ті самі точки")
    scr = si.screen_png(ink, (10, 20, 30), (200, 210, 220), 1)
    chk = si.decode(scr)
    check((chk.w, chk.h) == (160, 128), "Z3/B2: передпоказ -- екран 160x128")
    scr4 = si.screen_png(ink, (10, 20, 30), (200, 210, 220), 4)
    check(si.decode(scr4).w == 640, "Z3/B2: передпоказ ×4 -- 640x512")


# ----------------------------------------------------------------------------------------------------------------------
#  Z4: мелодія
# ----------------------------------------------------------------------------------------------------------------------

def test_melody():
    rnd = random.Random(4)
    for _ in range(60):
        n = rnd.randrange(1, 255)
        tones = [bm.Tone(rnd.randrange(64), rnd.randrange(1, 256)) for _ in range(n)]
        blk = bm.build(tones)
        back, skip, warns = bm.parse(blk)
        exp = b"".join(bytes([t.note, t.units]) for t in tones) + (b"\0\0" if n < 255 else b"")
        check(len(blk) == 512 and blk[:len(exp)] == exp and blk[len(exp):] == bytes(512 - len(exp)) and back == tones and not skip and not warns,
              "Z4/C1: %d тонів -> блок 512 Б (пари + термінатор + нулі) -> ті самі тони" % n)
    tones255 = [bm.Tone(i % 64, 1 + i % 200) for i in range(255)]
    blk = bm.build(tones255)
    check(len(blk) == 512 and bm.parse(blk)[0] == tones255 and blk[510:] == b"\0\0", "Z4/C1: 255 тонів -- без термінатора, але блок 512 Б, розбір дає 255")
    try:
        bm.build(tones255 + [bm.Tone(1, 1)])
        check(False, "Z4: 256 тонів мали бути відхилені")
    except bm.MelodyError:
        pass
    # у менший блок
    t20 = [bm.Tone(10, 5)] * 20
    check(len(bm.build(t20, 42)) == 42 and bm.parse(bm.build(t20, 42))[0] == t20, "Z4/C1: 20 тонів у блок 42 Б (рівно з термінатором)")
    try:
        bm.build(t20, 40)
        check(False, "Z4: 20 тонів у 40 Б не вміщуються")
    except bm.MelodyError as e:
        check("40" in str(e), "Z4/C1: не вміщується в наявний блок -- пояснення з розмірами: %s" % e)
    try:
        bm.build([])
        check(False, "Z4: порожня мелодія мала бути відхилена")
    except bm.MelodyError:
        pass
    # режим «без заставки»
    sk = bm.build([], skip_splash=True)
    check(sk == bytes(512) and bm.parse(sk) == ([], True, bm.parse(sk)[2]) and bm.parse(sk)[2], "Z4/C1: «без мелодії»: 512 нулів, перші два байти 0 -> рація пропускає заставку й мелодію")
    # парсинг як у прошивці
    raw = bytes([5, 3, 70, 2, 0, 0])
    tones, skip, warns = bm.parse(raw + bytes(506))
    check([(t.note, t.units) for t in tones] == [(5, 3), (63, 2)] and warns, "Z4/C1: нота > 63 обмежується до 63 з зауваженням")
    tones, skip, warns = bm.parse(bytes([5, 3, 6, 4]))
    check(len(tones) == 2 and any("термінатор" in w for w in warns), "Z4/C1: блок без термінатора -- зауваження про сміття за межею")
    check(bm.parse(bytes([0, 0, 9, 9]) + bytes(508))[1] is True, "Z4/C1: 0,0 на початку = пропуск заставки (як у прошивці)")
    # пауза в середині блока: нота 0 з тривалістю > 0 -- звичайна пауза
    t, s, w = bm.parse(bytes([0, 4, 7, 2, 0, 0]) + bytes(506))
    check(not s and [(x.note, x.units) for x in t] == [(0, 4), (7, 2)], "Z4/C1: нота 0 із тривалістю -- пауза (тиха), а не пропуск заставки")
    # Tone: межі
    for args in ((64, 1), (-1, 1), (1, 0), (1, 256)):
        try:
            bm.Tone(*args)
            check(False, "Z4: Tone%r мав бути відхилений" % (args,))
        except bm.MelodyError:
            pass
    # частоти/мс
    check(bm.Tone(36, 10).hz == 784 and bm.Tone(36, 10).ms == 270 and bm.ms_to_units(100) == 4 and bm.ms_to_units(1) == 1 and bm.ms_to_units(99999) == 255, "Z4/C2: 784 Гц, 10 одиниць = 270 мс; ms_to_units округлює")
    check(bm.nearest_note(880) == 38 and bm.nearest_note(0) == 0 and bm.nearest_note(100) == 1 and bm.nearest_note(10000) == 63 and bm.nearest_note(440) == 26,
          "Z4/C2: найближча нота: 880 -> 38, 440 -> 26, поза діапазоном -- крайні")
    for i in range(1, 64):
        midi = 43 + i
        f = 440.0 * 2 ** ((midi - 69) / 12.0)
        if abs(f - bm.FREQS[i]) > 1.2:
            check(False, "Z4/C2: ім'я ноти %d (%s) не відповідає частоті %d Гц" % (i, bm.note_name(i), bm.FREQS[i]))
            break
    check(bm.note_name(26) == "ля4" and bm.note_name(0) == "пауза" and bm.note_name(1) == "соль#2", "Z4/C2: назви нот: індекс 26 = ля4 (440 Гц)")
    # пресети
    keys = [p[0] for p in bm.PRESETS]
    check("silence" in keys and "stock" in keys and len(set(keys)) == len(keys), "Z4/C3: пресети унікальні, є «вбудована» і «тиша»")
    for k, title, desc, make in bm.PRESETS:
        tl = make()
        blk = bm.build(tl)
        check(bm.parse(blk)[0] == tl and 0 < len(tl) <= 255 and tl == bm.preset(k), "Z4/C3: пресет «%s» вміщується в 512 Б й читається назад" % title)
    stock = bm.preset("stock")
    check(len(stock) == len(bm.STOCK_POWER_ON) and all(abs(t.ms - ms) <= 14 and (t.hz == hz or hz == 0) for t, (hz, ms) in zip(stock, bm.STOCK_POWER_ON)),
          "Z4/C3: «вбудована» відтворює MELODY_POWER_ON з точністю до кроку 27 мс")
    sil = bm.preset("silence")
    check(len(sil) == 1 and sil[0].note == 0 and 1950 <= sil[0].ms <= 2050, "Z4/C3: «тиша на 2 с» -- одна пауза ~2 с (не 0,0: заставка показується)")
    try:
        bm.preset("nope")
        check(False, "Z4: невідомий пресет")
    except bm.MelodyError:
        pass
    # морзе
    m = bm.morse_tones("73", 880, 60)
    on = [t for t in m if t.note]
    check(len(on) == 10 and all(t.hz == 880 for t in on), "Z4/C3: «73» -- 5 знаків «7» + 5 знаків «3» = 10 звучань")
    try:
        bm.morse_tones("Ж")
        check(False, "Z4: «Ж» немає в таблиці Морзе")
    except bm.MelodyError:
        pass
    # програвання
    calls = []
    n_played = bm.play(bm.preset("rise"), beep=lambda hz, ms: calls.append(("b", hz, ms)), sleep=lambda s: calls.append(("s", s)))
    check(n_played == 3 and [c[0] for c in calls] == ["b", "b", "b"] and calls[0][1] == 523, "Z4/C4: програвання викликає beep(hz, ms) для кожного тону")
    calls.clear()
    stop = [False]
    bm.play(bm.preset("stock"), beep=lambda hz, ms: (calls.append(1), stop.__setitem__(0, len(calls) >= 2)), sleep=lambda s: calls.append(0), should_stop=lambda: stop[0])
    check(len(calls) <= 4, "Z4/C4: «Стоп» зупиняє програвання")
    if bm.player() is None:
        try:
            bm.play(bm.preset("rise"))
            check(False, "Z4/C4: без winsound програвання мало дати MelodyError")
        except bm.MelodyError as e:
            check("winsound" in str(e), "Z4/C4: без winsound -- чесне повідомлення, ноти показуються в списку: %s" % e)
    # --- рація ---
    d_tones = bm.preset("hello")
    spi = spi_region()
    before = bytes(spi)
    pos, ln = block_addr(spi, 2)
    lo, hi = cd.FLASH_BASE + pos, cd.FLASH_BASE + pos + 8 + 512
    radio = tcr.FakeRadioX(bytearray(spi))
    state, l0, raw0 = bm.read_melody(radio)
    check(state == bm.ST_OK and l0 == 512 and raw0 == region_payloads()[2], "Z4/C1: читання наявного блока мелодії")
    with WriteLog() as wl:
        text = bm.write_melody(radio, d_tones)
    after = bytes(radio.spi)
    check(after[lo + 8:hi] == bm.build(d_tones) and "Звірка читанням: OK" in text, "Z4/C1/Z5: блок у рації == build(tones); звірка читанням")
    check(t31.untouched_outside(before, after, lo, hi) and all(cd.FLASH_BASE <= a and a + n <= cd.FLASH_BASE + 0x10000 for a, n in wl.calls), "Z4/Z6: змінено лише блок мелодії; запис у межах області")
    check(bm.parse(bm.read_melody(radio)[2])[0] == d_tones, "Z4: редактор -> байти -> рація -> байти -> редактор: ті самі тони")
    bm.write_melody(radio, [], skip_splash=True)
    check(bytes(radio.spi[lo + 8:hi]) == bytes(512), "Z4/C3: «без мелодії» записано як 512 нулів")
    # блока нема
    r2 = tcr.FakeRadioX(bytearray(spi_region(types=(1, 3, 4))))
    check(bm.read_melody(r2)[0] == bm.ST_ABSENT, "Z4: блока мелодії нема -- стан «нема»")
    bm.write_melody(r2, d_tones)
    p2 = block_addr(bytes(r2.spi), 2)
    check(p2 is not None and p2[1] == 512 and bm.parse(bm.read_melody(r2)[2])[0] == d_tones, "Z4: блок створено на 512 Б")
    # менший блок у рації
    pl = region_payloads()
    pl[2] = bytes(range(1, 31))                               # 30 Б = 14 пар + термінатор
    r3 = tcr.FakeRadioX(bytearray(spi_region(payloads=pl)))
    small = [bm.Tone(10, 3)] * 14
    bm.write_melody(r3, small)
    check(bm.read_melody(r3)[1] == 30 and bm.parse(bm.read_melody(r3)[2])[0] == small, "Z4/C1: у наявний блок 30 Б вміщується мелодія з 14 тонів")
    x_before = r3.x_total
    try:
        bm.write_melody(r3, [bm.Tone(10, 3)] * 30)
        check(False, "Z4: довга мелодія в короткий блок мала бути відхилена без replace")
    except RuntimeError as e:
        check(r3.x_total == x_before and "довжин" in str(e), "Z4/C1: без згоди на заміну -- відмова словами, у рацію нічого: %s" % e)
    b3 = bytes(r3.spi)
    long_t = [bm.Tone(10 + i % 20, 3 + i % 5) for i in range(60)]
    text = bm.write_melody(r3, long_t, replace=True)
    a3 = bytes(r3.spi)
    p_old = block_addr(b3, 2)
    dp = diff_positions(b3, a3)
    check("вилучено" in text and bm.read_melody(r3)[1] == 512 and bm.parse(bm.read_melody(r3)[2])[0] == long_t, "Z4/C1: replace=True -- старий вилучено, новий 512 Б читається")
    old_lo = cd.FLASH_BASE + p_old[0]
    check(struct.unpack("<ii", a3[old_lo:old_lo + 8]) == (cd.RETIRED_BASE + 2, 30) and a3[old_lo + 8:old_lo + 8 + 30] == b3[old_lo + 8:old_lo + 8 + 30], "Z4/C1: старий блок вилучено (лише тип), дані й довжина на місці")
    check(all(cd.FLASH_BASE <= p < cd.FLASH_BASE + 0x10000 for p in dp), "Z4/Z6: зміни лише в області custom-data")
    # remove
    rr = tcr.FakeRadioX(bytearray(spi))
    t_ = bm.remove_melody(rr)
    check(bm.read_melody(rr)[0] == bm.ST_ABSENT and diff_positions(bytes(rr.spi), before) and all(lo <= p < lo + 4 for p in diff_positions(bytes(rr.spi), before)),
          "Z4/C3: «Повернути вбудовану» змінила лише тип блока (4 байти)")
    try:
        bm.remove_melody(rr)
        check(False, "Z4: повторне вилучення мало дати помилку")
    except RuntimeError:
        pass
    r4 = tcr.FakeRadioX(bytearray(spi_region(magic=False)))
    try:
        bm.write_melody(r4, d_tones)
        check(False, "Z4: без області")
    except RuntimeError:
        check(r4.x_total == 0, "Z4: без області -- відмова, у рацію нічого")


# ----------------------------------------------------------------------------------------------------------------------
#  Z5: сира область 0xAF400..0xD8000 (охоронець)
# ----------------------------------------------------------------------------------------------------------------------

RAW_START, RAW_END = cl.RAW_AREA_START, cl.RAW_AREA_END


def spi_raw():
    """SPI-флеш з позначеними областями й порожньою (0xFF) сирою областю 0xAF400..0xD8000."""
    spi = t31.spi_marked()
    spi[RAW_START:RAW_END] = b"\xff" * (RAW_END - RAW_START)
    return spi


def sector_span(addr, n):
    return addr // 4096 * 4096, (addr + n + 4095) // 4096 * 4096


def bounds_violations():
    """Спроби запису, які ОБОВ'ЯЗКОВО мають бути відхилені охоронцем; повертає список тих, що пройшли (має бути порожній)."""
    radio = tcr.FakeRadioX(bytearray(spi_raw()))
    out = []
    bad = [("rawarea", 0xAF3FF, 2, "байт перед сирою областю"), ("rawarea", 0xAF000, 8, "початок сектора перед областю"), ("rawarea", 0xD7FFF, 2, "через кінець області"),
           ("rawarea", 0xD8000, 4, "область №2 бази"), ("rawarea", 0x10000, 4, "калібрування"), ("rawarea", 0x10FFC, 8, "кінець калібрування"),
           ("rawarea", 0x20000, 4, "custom-data"), ("rawarea", 0x50000, 4, "база позивних"), ("rawarea", 0x9B000, 4, "кодплаг"), ("rawarea", 0xDA000, 4, "ключі AES"),
           ("rawarea", 0xD9F9C, 100, "запис 0 таблиці ключів"), ("rawarea", 0x0, 4, "EEPROM"), ("rawarea", 0xAF400, RAW_END - RAW_START + 1, "довше за область"),
           ("dmrdb", RAW_START, 4, "база не пише в сиру область"), ("keys", RAW_START, 4, "ключі не пишуть у сиру область"), ("dmrdb", 0xD7FFC, 4, "база не пише в кінець сирої області"),
           ("rawarea", 0x90000, 4, "між базою і кодплагом"), ("rawarea", 0xB0000 - 0x2000, 4, "кодплаг у флеші")]
    for w, a, n, what in bad:
        try:
            fg.write_span(radio, a, b"\xab" * n, w)
            out.append("запис %s 0x%X +%d (%s) пройшов" % (w, a, n, what))
        except fg.GuardError:
            pass
    if radio.x_total != 0 or radio.cal_touched:
        out.append("відхилені записи все ж дійшли до рації (x=%d)" % radio.x_total)
    return out


def test_bounds():
    check(bounds_violations() == [], "Z6: усі спроби запису за межі вікон відхилено: %r" % bounds_violations())
    radio = tcr.FakeRadioX(bytearray(spi_raw()))
    fg.write_span(radio, RAW_START, b"\x11" * 4, "rawarea")
    fg.write_span(radio, RAW_END - 4, b"\x22" * 4, "rawarea")
    check(bytes(radio.spi[RAW_START:RAW_START + 4]) == b"\x11" * 4 and bytes(radio.spi[RAW_END - 4:RAW_END]) == b"\x22" * 4, "Z6: крайні байти сирої області пишуться")
    # тест бачить зламану межу (мутація в процесі): розширене вниз вікно -> порушення з'являються
    saved = dict(fg.WINDOWS)
    try:
        fg.WINDOWS["rawarea"] = (0xAF000, RAW_END)
        check(bounds_violations() != [], "Z6/мутація: розширене вікно сирої області (з 0xAF000) -- перевірка меж це ловить")
        fg.WINDOWS["rawarea"] = (RAW_START, 0xDA100)
        check(bounds_violations() != [] or fg.check_windows() != [], "Z6/мутація: вікно сирої області, що наїхало на ключі AES, -- ловиться")
    finally:
        fg.WINDOWS.clear()
        fg.WINDOWS.update(saved)
    check(bounds_violations() == [] and fg.check_windows() == [], "Z6: після відновлення вікон перевірка знову чиста")
    # custom_data: поза областю відхиляється
    wrote = []
    orig = aks.flash_write_block
    aks.flash_write_block = lambda ser, addr, data: wrote.append(addr)
    try:
        for addr, n in ((0x1FFFF, 2), (0x30000, 1), (0x10000, 4096), (0x2FFF1, 16)):
            try:
                cd.flash_write_span(None, addr, b"\1" * n)
                check(False, "Z6: custom_data записав 0x%X +%d" % (addr, n))
            except ValueError:
                pass
    finally:
        aks.flash_write_block = orig
    check(wrote == [], "Z6: custom_data не дійшов до флеша з адресами поза областю")
    # retire_block: нема блока / нема області -- нічого не пишеться
    r1 = tcr.FakeRadioX(bytearray(spi_region(types=(2,))))
    ok, why = cd.retire_block(r1, 1)
    check(not ok and r1.x_total == 0, "Z6: вилучення неіснуючого блока -- відмова, 0 записів: %s" % why)
    r2 = tcr.FakeRadioX(bytearray(spi_region(magic=False)))
    ok, why = cd.retire_block(r2, 1)
    check(not ok and r2.x_total == 0, "Z6: вилучення без області -- відмова, 0 записів")


def test_combined():
    """Усі нові дії поспіль на одному флеші: змінюються лише custom-data (0x20000..0x2FFFF); решта (зокрема сира область 0xAF400..0xD8000) -- байт-в-байт."""
    old_sleep = t31.no_sleep()
    try:
        d = tempfile.mkdtemp(prefix="r35c_")
        spi = spi_region()
        spi[RAW_START:RAW_END] = b"\xff" * (RAW_END - RAW_START)
        before = bytes(spi)
        radio = tcr.FakeRadioX(bytearray(spi))
        rnd = random.Random(8)
        ink = bytes(rnd.randrange(2) for _ in range(8192))
        slots = [st.Slot.from_tle(st.Tle(*mk_tle("C%d" % i, 30000 + i, 25, 40.0 + i))) for i in range(7)]
        with WriteLog() as wl:
            st.write_slots(radio, slots, safety_dir=d, log=quiet)
            si.write_image(radio, ink)
            si.remove_image(radio)
            si.write_image(radio, ink)
            bm.write_melody(radio, bm.preset("bell"))
            bm.write_melody(radio, [], skip_splash=True)
            bm.remove_melody(radio)
            bm.write_melody(radio, bm.preset("siren"))
        after = bytes(radio.spi)
        changed = diff_positions(before, after)
        allowed = lambda p: cd.FLASH_BASE <= p < cd.FLASH_BASE + 0x10000      # noqa: E731
        check(changed and all(allowed(p) for p in changed), "Z6: змінені байти лише в custom-data (поза: %s)" % [hex(p) for p in changed if not allowed(p)][:5])
        for name, lo, hi in (("EEPROM з калібруванням", 0, 0x20000), ("база позивних (область №1)", db.AREA1_START, db.AREA1_START + db.AREA1_LEN), ("кодплаг у флеші", 0x9B000, 0xAF000),
                             ("область №2 бази", db.AREA2_START, cl.AES_KEYS_RAW_START), ("ключі AES", cl.AES_KEYS_RAW_START, cl.AES_KEYS_RAW_START + cl.AES_KEYS_RAW_LEN),
                             ("решта флеша після ключів", cl.AES_KEYS_RAW_START + cl.AES_KEYS_RAW_LEN, len(before))):
            check(before[lo:hi] == after[lo:hi], "Z6/CL6: %s після всіх нових дій побайтово та сама" % name)
        check(not radio.cal_touched, "Z6: калібрування не зачеплено")
        # кожен виклик запису лежить в області custom-data
        sectors_cd = [a for a, _n in wl.calls if cd.FLASH_BASE <= a < cd.FLASH_BASE + 0x10000]
        check(len(sectors_cd) == len(wl.calls) and all(not (0x10000 <= a < 0x11000) for a, _n in wl.calls), "Z6: усі %d викликів запису -- у custom-data" % len(wl.calls))
        # інші блоки області не змінилися
        reg0 = {b.type: b.payload for b in cr.parse_region(before[cd.FLASH_BASE:cd.FLASH_BASE + 0x10000]).blocks}
        reg1 = {b.type: b.payload for b in cr.parse_region(after[cd.FLASH_BASE:cd.FLASH_BASE + 0x10000]).blocks}
        same = all(reg0[t] == reg1[t] for t in (4, 5, 8, 10))
        check(same, "Z6/CL6: блоки налаштувань (ключі/теми/SMS/RCTL) після дій з картинкою, мелодією й супутниками не змінилися")
        check(before[RAW_START:RAW_END] == after[RAW_START:RAW_END], "Z6: сира область 0xAF400..0xD8000 після всіх дій не змінилась")
    finally:
        time.sleep = old_sleep


# ----------------------------------------------------------------------------------------------------------------------
#  Z1: панелі (xvfb)
# ----------------------------------------------------------------------------------------------------------------------

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
    import tkinter.filedialog as fd
    import tkinter.messagebox as mb
    import gui_dialogs as gd
    import test_cps_csv as tc
    from cps_ui.app import CpsApp, SECTIONS
    from cps_ui.settings import Settings

    old_sleep = t31.no_sleep()
    tmp = tempfile.mkdtemp(prefix="r35g_")
    spath = os.path.join(tmp, "ui.json")
    os.environ["TYT_CPS_SETTINGS"] = spath
    os.environ["HOME"] = tmp
    app = CpsApp(settings=Settings(spath), autoprobe=False)
    errors, infos, asks, confirms = [], [], [], []
    mb.showinfo = lambda *a, **k: infos.append(a)
    mb.showerror = lambda *a, **k: errors.append(a)
    mb.showwarning = lambda *a, **k: infos.append(a)
    mb.askyesno = lambda *a, **k: (asks.append(a), True)[1]
    gd.confirm_dialog = lambda *a, **k: (confirms.append(a), True)[1]
    orig_open_radio = cl.open_radio
    try:
        app.geometry("1300x900")
        app.update()
        keys = [c.key for _g, _t, cls in SECTIONS for c in cls]
        titles = {c.key: c.title for _g, _t, cls in SECTIONS for c in cls}
        for k in ("satellites", "splash", "melody"):
            check(k in keys, "Z1: панель «%s» є в SECTIONS" % k)
        grp = {g: [c.key for c in cls] for g, _t, cls in SECTIONS}
        check(all(k in grp["grp_service"] for k in ("satellites", "splash", "melody")), "Z1/A2: усі три панелі -- у групі «Сервіс»")
        check(len(set(titles.values())) == len(titles), "Z1: назви розділів унікальні: %r" % [t for t in titles.values() if list(titles.values()).count(t) > 1])
        for label, spi in (("без документа", None), ("порожній", tc.base.make_spi()), ("повний", tc.make_fixture_spi())):
            if spi is not None:
                _cp, data = tc.codeplug_of(spi)
                src = os.path.join(tmp, "%s.zip" % label.replace(" ", "_"))
                open(src, "wb").write(data)
                check(app.doc_open_file(src), "Z1: відкрито %s кодплаг" % label)
            for k in ("satellites", "splash", "melody"):
                app.show(k)
                _spin(app, 4)
                p = app.get_panel(k)
                check(p is not None and p.key == k, "Z1 (%s): панель %s відкривається" % (label, k))
            sp, sl, mp = (app.get_panel(k) for k in ("satellites", "splash", "melody"))
            for nm, wdg in (("супутники: Прочитати", sp.read_btn), ("супутники: Записати", sp.write_btn), ("заставка: Прочитати", sl.read_btn), ("заставка: Записати", sl.write_btn),
                            ("заставка: Прибрати", sl.remove_btn), ("мелодія: Прочитати", mp.read_btn), ("мелодія: Записати", mp.write_btn), ("мелодія: Повернути", mp.restore_btn)):
                check(str(wdg.cget("state")) == "disabled", "Z1 (%s): без рації «%s» вимкнено, не прибрано" % (label, nm))
            for nm, wdg in (("супутники: Відкрити файл", sp.open_btn), ("супутники: Перевірити джерело", sp.probe_btn), ("заставка: Відкрити файл", sl.open_btn)):
                check(str(wdg.cget("state")) != "disabled", "Z1 (%s): «%s» не потребує рації -- доступна" % (label, nm))
            check(sl.boot_label.cget("text") != "" or label != "без документа", "Z1/B4 (%s): підказка про тип екрана вітання" % label)
        # ---------- радіо підроблено ----------
        spi_r = spi_region()
        spi_r[RAW_START:RAW_END] = b"\xff" * (RAW_END - RAW_START)
        before = bytes(spi_r)
        radio = tcr.FakeRadioX(bytearray(spi_r))
        cl.open_radio = lambda *a, **k: radio

        # --- Супутники ---
        app.show("satellites")
        sp = app.get_panel("satellites")
        tlefile = os.path.join(tmp, "amateur.txt")
        recs = [mk_tle("SAT-%d" % i, 41000 + i, 26, 270.0 + i) for i in range(4)] + [ISS]
        open(tlefile, "wb").write(("\r\n".join(x for r in recs for x in r) + "\r\nнапівзапис\r\n1 99999U 98067A   08264.51782528 -.00002182").encode("utf-8"))
        sp.load_file(tlefile)
        _spin(app)
        check(len(sp.tles) == 5 and "наборів елементів 5" in sp.src_label.cget("text"), "Z1/A3: файл TLE розібрано, обірваний запис не потрапив: %s" % sp.src_label.cget("text"))
        sp.search_var.set("sat-")
        sp._refilter()
        check(len(sp.tle_view) == 4 and "Знайдено 4" in sp.counts_label.cget("text"), "Z1/A4: пошук «sat-» -- 4 з 5; лічильник: %s" % sp.counts_label.cget("text"))
        sp.tle_tree.selection_set(*sp.tle_tree.get_children())
        _spin(app)
        check("відібрано 4" in sp.counts_label.cget("text"), "Z1/A4: лічильник відібраних: %s" % sp.counts_label.cget("text"))
        sp._on_read()
        _wait_idle(app)
        n0 = len(sp.slots)
        check(sp.radio_state == st.ST_OK and n0 == 3, "Z1/A5: прочитано з рації: 3 слоти з фікстури (%d)" % n0)
        sp._on_add()
        _spin(app)
        check(len(sp.slots) == n0 + 4 and sp.is_dirty(), "Z1/A4: 4 відібрані додано в слоти (%d), є незаписані зміни" % len(sp.slots))
        sp.slot_tree.selection_set("0")
        _spin(app)
        sp.name_var.set("SATONE")
        sp.rx_var.set("145,925")
        sp.tx_var.set("435.3")
        sp.ctcss_var.set("67")
        sp._on_apply_form()
        check(sp.slots[0].name == "SATONE" and sp.slots[0].rx1 == 145_925_000 and sp.slots[0].tx1 == 435_300_000 and sp.slots[0].ctcss == 670, "Z1/A2: форма слота: назва, МГц, субтон 67 Гц -> 670")
        sp.name_var.set("ЗАДОВГАНАЗВА")
        sp._on_apply_form()
        check(errors and sp.slots[0].name == "SATONE", "Z1/A2: хибна назва -- повідомлення, слот не змінено")
        errors.clear()
        confirms.clear()
        sp._on_write()
        _wait_idle(app)
        pos_t, _l = block_addr(bytes(radio.spi), 3)
        blk = bytes(radio.spi[cd.FLASH_BASE + pos_t + 8:cd.FLASH_BASE + pos_t + 8 + 2520])
        check(blk == st.build_block(sp.slots) and confirms and "SATONE" in confirms[-1][2], "Z1/A5: запис з панелі: блок у рації == build_block(слоти); підтвердження перелічує слоти")
        check(not sp.is_dirty() and any("Звірка читанням: OK" in str(i) for i in infos), "Z1/A5: після запису «незаписаних змін» нема, повідомлення про звірку")
        saf = [f for f in os.listdir(os.path.join(tmp, "MD-UV390UKR")) if f.startswith("satellites_pre-write")] if os.path.isdir(os.path.join(tmp, "MD-UV390UKR")) else []
        check(len(saf) == 1, "Z1/A5: страхову копію блока збережено у MD-UV390UKR: %r" % saf)
        # оновлення наявних
        fresh = os.path.join(tmp, "fresh.txt")
        nn, a1, a2 = mk_tle("SAT-2", 41002, 26, 280.0, inc=77.0)
        open(fresh, "w").write("\n".join([nn, a1, a2]) + "\n")
        sp.load_file(fresh)
        chosen, amb, missing = sp.plan_update()
        check(len(chosen) == 1 and not amb and len(missing) == len(sp.slots) - 1, "Z1/A4: оновлення за назвою -- збіг один, решта лишаються")
        confirms.clear()
        sp._on_update_existing()
        _spin(app)
        idx = list(chosen)[0]
        check(abs(sp.slots[idx].inclination - 77.0) < 1e-6 and sp.slots[idx].name == "SAT-2" and confirms, "Z1/A4: елементи оновлено (нахил 77), назва лишилась, було підтвердження")
        # читання назад
        sp._on_read()
        _wait_idle(app)
        check([s.name for s in sp.slots][0] == "SATONE" and len(sp.slots) == 7, "Z1/A5: прочитані з рації слоти == записані")

        # --- Заставка ---
        app.show("splash")
        sl = app.get_panel("splash")
        grad = png_encode(300, 200, 0, 8, [[(int(255 * x / 299),) for x in range(300)] for _y in range(200)])
        sl.load_image_bytes(grad, "gradient.png")
        _spin(app)
        check(sl.ink is not None and len(sl.ink) == 8192 and sl._img is not None, "Z1/B2: PNG 300x200 завантажено, передпоказ намальовано")
        ink_ref = sl.ink
        for fit in ("fill", "stretch", "fit"):
            sl.fit_var.set(fit)
            sl._on_option()
            check(len(sl.ink) == 8192, "Z1/B2: режим %s працює" % fit)
        sl.fit_var.set("fit")
        sl.daytime.set("day")
        sl._on_option()
        check(sl._img is not None, "Z1/B2: денна тема -- передпоказ перемальовано")
        sl.daytime.set("night")
        sl._on_option()
        confirms.clear()
        sl._on_write()
        _wait_idle(app)
        pos_i, _l = block_addr(bytes(radio.spi), 1)
        check(bytes(radio.spi[cd.FLASH_BASE + pos_i + 8:cd.FLASH_BASE + pos_i + 8 + 1024]) == si.ink_to_block(sl.ink) and confirms, "Z1/B4: запис з панелі: блок у рації == ink_to_block; було підтвердження")
        sl._on_read()
        _wait_idle(app)
        check(sl.radio_state == si.ST_OK and sl.radio_ink == sl.ink, "Z1/B4: прочитано з рації == записане")
        pngp = os.path.join(tmp, "radio.png")
        fd.asksaveasfilename = lambda **k: pngp
        sl._on_save_radio_png()
        check(os.path.exists(pngp) and si.decode(open(pngp, "rb").read()).data == bytes(255 if v else 0 for v in sl.radio_ink), "Z1/B5: «Зберегти картинку з рації у PNG» -- файл розкодовується в ті самі точки")
        pngp2 = os.path.join(tmp, "prev.png")
        fd.asksaveasfilename = lambda **k: pngp2
        sl._on_save_preview_png()
        gp = si.decode(open(pngp2, "rb").read())
        check((gp.w, gp.h) == (160 * 4, 128 * 4), "Z1/B2: передпоказ у PNG ×4 -- 640x512")
        confirms.clear()
        sl._on_remove()
        _wait_idle(app)
        check(si.read_image(radio)[0] == si.ST_ABSENT and sl.radio_state == si.ST_ABSENT and confirms, "Z1/B4: «Прибрати картинку» -- блока для прошивки нема, було підтвердження (CL3)")
        sl._on_option()
        check(not errors, "Z1: без вікон помилок: %r" % errors)

        # --- Мелодія ---
        app.show("melody")
        mp = app.get_panel("melody")
        mp.preset_var.set("Привітання")
        mp._on_preset()
        check(mp.tones == bm.preset("hello") and len(mp.tree.get_children()) == 4, "Z1/C3: готова мелодія «Привітання» в списку (4 тони)")
        mp.note_var.set(bm.note_name(40))
        mp.ms_var.set("300")
        mp._on_add()
        check(len(mp.tones) == 5 and mp.tones[-1] == bm.Tone(40, bm.ms_to_units(300)), "Z1/C2: додано тон (нота 40, 300 мс -> 11 одиниць)")
        mp.tree.selection_set("0")
        _spin(app)
        check(mp.note_var.get() == bm.note_name(mp.tones[0].note), "Z1/C2: вибір рядка підставляє значення в форму")
        mp.ms_var.set("abc")
        mp._on_replace()
        check(errors and mp.tones[0] == bm.preset("hello")[0], "Z1/C2: хибна тривалість -- повідомлення, тон не змінено")
        errors.clear()
        mp.ms_var.set("1000")
        mp._on_replace()
        check(mp.tones[0].units == bm.ms_to_units(1000), "Z1/C2: заміна вибраного тону")
        mp._move(1)
        check(mp.selected() == 1, "Z1/C2: тон пересунуто вниз")
        mp._on_delete()
        check(len(mp.tones) == 4, "Z1/C2: тон прибрано")
        mp.morse_var.set("73")
        mp._on_morse()
        check(len(mp.tones) == 4 + len(bm.morse_tones("73")), "Z1/C3: морзе «73» дописано")
        mp.morse_var.set("Ж")
        mp._on_morse()
        check(errors, "Z1/C3: літери поза таблицею -- повідомлення")
        errors.clear()
        mp._on_clear()
        mp.preset_var.set("Дзвінок")
        mp._on_preset()
        planned = list(mp.tones)
        mp._on_play()
        _spin(app)
        check(bm.player() is not None or "недоступне" in mp.play_label.cget("text"), "Z1/C4: без winsound -- «Прослухати» чесно каже, що недоступне, і показує ноти")
        confirms.clear()
        mp._on_write()
        _wait_idle(app)
        pos_m, _l = block_addr(bytes(radio.spi), 2)
        check(bytes(radio.spi[cd.FLASH_BASE + pos_m + 8:cd.FLASH_BASE + pos_m + 8 + 512]) == bm.build(planned) and confirms, "Z1/C3: запис з панелі: блок мелодії == build(tones)")
        mp._on_clear()
        mp._on_read()
        _wait_idle(app)
        check(mp.tones == planned and mp.radio_state == bm.ST_OK, "Z1/C2: прочитана з рації мелодія == записана")
        mp.preset_var.set(bm.PRESETS[-1][1] if False else "(без заставки і мелодії)")
        mp._on_preset()
        check(mp.skip_splash and str(mp.add_btn.cget("state")) == "disabled", "Z1/C3: «без заставки і мелодії» -- список редагування вимкнено")
        mp._on_write()
        _wait_idle(app)
        check(bytes(radio.spi[cd.FLASH_BASE + pos_m + 8:cd.FLASH_BASE + pos_m + 8 + 512]) == bytes(512), "Z1/C3: записано режим «без мелодії» (512 нулів)")
        mp._on_read()
        _wait_idle(app)
        check(mp.skip_splash and mp.radio_warns, "Z1/C3: прочитано назад як режим «без заставки»")
        mp._on_restore()
        _wait_idle(app)
        check(bm.read_melody(radio)[0] == bm.ST_ABSENT, "Z1/C3: «Повернути вбудовану» -- блока мелодії для прошивки нема (CL4)")
        check(not errors, "Z1: без вікон помилок (мелодія): %r" % errors)

        # у кінці: все, що не мало змінюватися, -- те саме, що було (CL6)
        after = bytes(radio.spi)
        check(before[:0x20000] == after[:0x20000] and before[db.AREA1_START:0x9B000 + 0x14000] == after[db.AREA1_START:0x9B000 + 0x14000] and before[RAW_START:] == after[RAW_START:],
              "Z1/CL6: EEPROM, база, кодплаг, ключі після всіх дій з панелей не змінились")
        check(not errors, "Z1: без вікон помилок: %r" % errors)
    finally:
        cl.open_radio = orig_open_radio
        time.sleep = old_sleep
        try:
            app.destroy()
        except Exception:  # noqa: BLE001
            pass


def _wait_idle(app, limit=30.0):
    return t31._wait_idle(app, limit)


def main():
    import faulthandler
    faulthandler.dump_traceback_later(900, exit=True)
    old_sleep = t31.no_sleep()
    for t in (test_constants_match_firmware, test_tle, test_image, test_image_radio, test_melody, test_bounds, test_combined, test_gui):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    time.sleep = old_sleep
    if FAILS:
        print("test_r35: ПРОВАЛЕНО перевірок: %d" % len(FAILS))
        return 1
    print("test_r35: усе гаразд (%d перевірок: супутники TLE, картинка заставки, мелодія вмикання, межі запису, панелі)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
