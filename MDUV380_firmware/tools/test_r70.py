#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R70 (хост-перевірки).

A  затухання без GPS скрізь (рішення власника): прошивка (aprs_mode.c) і CPS (aprs_beacon_cfg.py, p_aprs.py). Поведінку прошивки перевіряє
   tests/test_aprs_settings_ui.c (там же старт без блока); тут -- структура: ОДНЕ місце (noGpsForce) викликається з cfgToSettings, з відкриття сесії і з гілки
   «блока нема», усе під HAS_GPS && FORK_NO_GPS_MENU; cfgToSettings блок не пише.
B  символ слота APRS у CPS -- у ФОРМАТІ ПРОШИВКИ (таблиця 0/1, індекс = код - 33):
   B1 aprs.c:581-582 і aprs_mode_cfg.c містять саме ті правила, на яких стоїть CPS;
   B2 повний круг по всіх 2x94 символах: запис CPS (байти слота) -> РЕАЛЬНИЙ код aprs_mode_cfg.c (tests/icon_fw_dump.c) + правило aprs.c -> той самий символ;
   B3 (0,58) = '[' людина без попередження; новий слот = (0,29) = '>'; індекс > 93 -- правдиве попередження;
   B4 CSV: «Icon table»/«Icon» -- СИРІ байти слота (str(rec[29]), str(rec[30])): круг експорт -> імпорт байт-у-байт для будь-яких значень;
   B5 мутанти (повернення до ASCII, зсув на +-1, переплутані таблиці) валять круг B2.
Запуск: python3 tools/test_r70.py"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
APP = os.path.join(ROOT, "application")
import aprs_symbols as asym      # noqa: E402
import cps_csv as cc             # noqa: E402
import codeplug_edit as ced      # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ: " + msg)


def read(*p):
    with open(os.path.join(*p), encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------------------------------------------------------- A
def test_a():
    src = read(APP, "source", "functions", "aprs_mode.c")
    m = re.search(r"#if defined\(HAS_GPS\) && defined\(FORK_NO_GPS_MENU\)\n/\* R69 B2 \+ R70 A1.*?static void noGpsForce\(aprsBeaconingSettings_t \*st\)\n\{(.*?)\n\}\n#else\n#define noGpsForce\(st\)  \(\(void\)0\)\n#endif", src, re.S)
    check(m is not None, "A1: noGpsForce -- під HAS_GPS && FORK_NO_GPS_MENU, у збірці без прапорця -- порожній макрос")
    body = m.group(1) if m else ""
    check("LOCATION_FROM_GPS" in body and "SMART_BEACONING" in body and "DECAY_ALGO_ENABLED" in body, "A1: helper знімає GPS, «Розумний» і затухання")
    cfg = re.search(r"static void cfgToSettings\(.*?\n\}\n", src, re.S).group(0)
    check("noGpsForce(st);" in cfg and "codeplugSetOpenGD77CustomData" not in cfg and "aprsBeaconCfgStore" not in cfg, "A1: cfgToSettings викликає helper і блока не пише")
    check(src.count("noGpsForce(") == 5, "A2: helper: визначення, макрос, cfgToSettings, відкриття сесії, гілка «блока нема» (є %d входжень)" % src.count("noGpsForce("))
    sess = re.search(r"aprsBeaconingGetSettings\(&aprsSettingsCopy\);.*?\n(.*?)\n\tu = aprsModeUi\(\);", src, re.S)
    check(sess is not None and "noGpsForce(&aprsSettingsCopy);" in sess.group(1) and "DECAY_ALGO_ENABLED" not in sess.group(1),
          "A2: відкриття сесії -- через helper, дубля з окремим зняттям затухання нема")
    boot = re.search(r"void aprsBeaconCfgBoot\(bool restoreDefaults\)\n\{.*?\n\}\n", src, re.S).group(0)
    check(re.search(r"noGpsForce\(&cur\);\s*aprsBeaconingBootSet\(&cur\);.*aprsBeaconCfgStore\(\);", boot, re.S) is not None, "A1: старт без блока: затухання знімається ДО створення блока")
    # CPS
    ab = read(HERE, "aprs_beacon_cfg.py")
    check('r["decay"] = False' in ab and "FORK_NO_GPS" in ab, "A3: no_gps_apply знімає затухання під FORK_NO_GPS")
    pa = read(HERE, "cps_ui", "p_aprs.py")
    check(re.search(r"if not abc_\.FORK_NO_GPS:[^\n]*\n\s*ttk\.Checkbutton\(bc, text=\"Алгоритм затухання\"", pa) is not None, "A3: чекбокс затухання створюється лише при FORK_NO_GPS = False")
    import aprs_beacon_cfg as ab_
    d = dict(ab_.DEFAULT_BEACON, decay=True, mode=4, source="gps")
    check(ab_.beacon_build(ab_.no_gps_apply(d))[6] & 4 == 0, "A3: у блоці, що пишеться з CPS, біт затухання знято")
    orig = ab_.FORK_NO_GPS
    ab_.FORK_NO_GPS = False
    try:
        check(ab_.no_gps_apply(d) == d, "A3: FORK_NO_GPS=False -- без змін")
    finally:
        ab_.FORK_NO_GPS = orig


# ---------------------------------------------------------------------------------------------------------------- B
def build_dump():
    exe = os.path.join(tempfile.mkdtemp(prefix="r70_"), "dump")
    fn = [os.path.join(ROOT, "tests", "icon_fw_dump.c")] + [os.path.join(APP, "source", "functions", f) for f in ("aprs_mode_cfg.c", "aprs_rx_parse.c", "dmr_sms_text.c")]
    cmd = ["gcc", "-O1", "-w", "-std=gnu11", "-DENABLE_APRS_RX", "-I", os.path.join(ROOT, "tools", "hoststub"), "-include", os.path.join(ROOT, "tools", "hoststub", "host_compat.h"),
           "-I", os.path.join(APP, "include")] + fn + ["-lm", "-o", exe]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        return None
    out = subprocess.run([exe], capture_output=True, text=True).stdout.split("\n")
    rows = {}
    for ln in out:
        if ln.strip():
            t, i, st, sc, mt, mc = ln.split()
            rows[(int(t), int(i))] = (st, int(sc), mt, int(mc))
    return rows


def cps_write(pair_to_raw, table, code):
    """Що запише CPS у слот для вибраного в сітці символу (таблиця '/' чи '\\\\', ASCII-код): шлях сітка -> поля форми -> запис слота (codeplug_edit/cps_csv)."""
    t, i = pair_to_raw(table, code)
    rec = bytearray(64)
    try:
        cc._aprs_encode_field(rec, 6, str(t))
        cc._aprs_encode_field(rec, 7, str(i))
    except ValueError:
        return -1, -1        # запис відхилено (мутант вийшов за межі) -- рядка в наборі прошивки нема
    return rec[29], rec[30]


def roundtrip(rows, pair_to_raw):
    """Усі 2x94: (таблиця, код) -> байти CPS -> що піде в ефір за прошивкою. Повертає список розбіжностей."""
    bad = []
    for table in ("/", "\\"):
        for code in range(33, 127):
            tb, ib = cps_write(pair_to_raw, table, code)
            row = rows.get((tb, ib))
            if row is None:
                bad.append((table, code, "байти (%d,%d) поза набором" % (tb, ib)))
                continue
            st, sc, mt, mc = row
            if (st, sc) != (table, code) or (mt, mc) != (table, code):
                bad.append((table, code, row))
    return bad


def test_b():
    aprs_c = read(APP, "source", "functions", "aprs.c")
    check("uint8_t symbol = (aprsConfig->iconIndex + '!');" in aprs_c and "uint8_t symTable = ((aprsConfig->iconTable == 0) ? '/' : '\\\\');" in aprs_c,
          "B1: aprs.c містить правило iconIndex + '!' та iconTable == 0 ? '/' : '\\\\'")
    check("('0' - '!')" in aprs_c, "B1: супутниковий конфіг у aprs.c теж в індексах ('0' - '!')")
    mc = read(APP, "source", "functions", "aprs_mode_cfg.c")
    check("d->iconIndex = (uint8_t)('>' - '!');" in mc and "d->iconTable = (raw->iconTable == 0U) ? 0U : 1U;" in mc, "B1: aprs_mode_cfg.c: типовий '>' - '!' і таблиця 0/1")
    rows = build_dump()
    if rows is None:
        check(shutil.which("gcc") is None, "B2: harness aprs_mode_cfg.c не зібрався")
        print("test_r70: нема gcc -- круг B2 пропущено")
        return
    check(len(rows) == 188, "B2: 2x94 пар прогнано кодом прошивки (%d)" % len(rows))
    bad = roundtrip(rows, asym.pair_to_raw)
    check(not bad, "B2: круг CPS -> прошивка (188 символів) без розбіжностей; перші: %r" % bad[:3])
    # B2: піктограма в CPS == піктограма за тією ж парою, що читає рація
    for (t, i), (st, sc, mt, mc) in rows.items():
        check(asym.raw_to_pair(t, i) == (st, sc), "B2: raw_to_pair(%d,%d) == правило прошивки (%s,%d)" % (t, i, st, sc))
        if FAILS:
            break
    # B3
    check(asym.is_known(0, 58) and asym.raw_to_pair(0, 58) == ("/", ord("[")) and "людина" in asym.symbol_text(0, 58) and "нема" not in asym.symbol_text(0, 58), "B3: (0,58) = '[' людина без попередження")
    nv = ced.new_aprs_values()
    check((nv["icon_table"], nv["icon"]) == ("0", "29") and asym.raw_to_pair(0, 29) == ("/", ord(">")), "B3: новий слот = (0,29) = '>'")
    check(not asym.is_known(0, 94) and "поза набором" in asym.unknown_text(0, 94), "B3: індекс > 93 -- попередження")
    check("читає як додаткову" in asym.symbol_text(2, 5), "B3: таблиця > 1 -- сказано, як її читає рація")
    # B4: CSV -- сирі байти
    import random
    rnd = random.Random(70)
    samples = [(0, 58), (0, 29), (1, 0), (1, 93), (2, 200), (47, 62), (255, 255), (0, 0)] + [(rnd.randrange(256), rnd.randrange(256)) for _ in range(300)]
    ok = True
    for t, i in samples:
        rec = bytearray(64)
        rec[29], rec[30] = t, i
        vals = cc.aprs_decode(bytes(rec), ".")
        back = bytearray(64)
        cc._aprs_encode_field(back, 6, vals[6])
        cc._aprs_encode_field(back, 7, vals[7])
        if (back[29], back[30]) != (t, i) or (vals[6], vals[7]) != (str(t), str(i)):
            ok = False
            break
    check(ok, "B4: CSV експорт -> імпорт повертає ті самі сирі байти слота (і текст у CSV = числа слота як є)")
    # B5: мутанти
    ascii_map = lambda table, code: (47 if table == "/" else 92, code)                       # noqa: E731
    shift_p = lambda table, code: (0 if table == "/" else 1, code - 33 + 1)                  # noqa: E731
    shift_m = lambda table, code: (0 if table == "/" else 1, code - 33 - 1)                  # noqa: E731
    swapped = lambda table, code: (1 if table == "/" else 0, code - 33)                     # noqa: E731
    for name, fn in (("ASCII", ascii_map), ("+1", shift_p), ("-1", shift_m), ("таблиці переплутані", swapped)):
        check(len(roundtrip(rows, fn)) > 0, "B5: мутант «%s» ловиться колом" % name)
    check(len(roundtrip(rows, asym.pair_to_raw)) == 0, "B5: справжня функція проходить")


def main():
    test_a()
    test_b()
    if FAILS:
        print("test_r70: ПРОВАЛІВ %d" % len(FAILS))
        sys.exit(1)
    print("test_r70: усе гаразд")


if __name__ == "__main__":
    main()
