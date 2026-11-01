#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R54: таблиця частот супутників у CPS (tools/sat_table.py, satellites.txt, sat_table_data.py). Хост-тести, без рації й без Tk.

P1  ОРИГІНАЛЬНИЙ файл користувача на 11 рядків (tools/testdata/satellites_user_2026-11-01.txt): очікувані значення в Гц / 0,1 Гц, усі 11 проходять перевірку без помилок;
P2  стартова таблиця: рівно 9 рядків, без NORAD 62461 і 62690, значення рядків побайтово ті самі, що в оригіналі; вбудований модуль == satellites.txt;
P3  сталі звіряються з прошивкою: смуги приймання й межі передачі (trx.c), довжина імені й AdditionalData (satellite.h), зсуви шляху APRS і SSID (aprs.c), поділ на 10 (menuSatelliteScreen.c);
P4  стійкість парсера: порожні рядки, зайві пробіли, малі літери «u», без літери, дробові субтони, CRLF/BOM, без заголовка, сміття, мало полів, довге ім'я, дублікат NORAD;
P5  шлях APRS: кодування/розбір ↔ те, що читає прошивка; SSID лише 0..9; хвіст [14..23] зберігається;
P6  слот із рядка таблиці -> запис блока: зсуви й значення (звірка struct), розпаковка вертає те саме;
P7  автозаповнення за NORAD: ім'я з таблиці, ручні частоти не перезаписуються, немає запису -> нулі, «Заповнити порожні» за назвою;
P8  «Додати з таблиці»: рядки без TLE перелічені, дублі не додаються, понад 25 не додається;
P9  перевірка перед записом: за смугою рації -- помилка, TX поза межами -- попередження, нулі -- «без частот», кожен набір окремо; МУТАНТИ;
P10 підключено до tests/run_tests.sh, є кроки DC1..DC5 у TESTING.md.
Запуск: python3 tools/test_r54.py"""
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
FAILS = []
PASSED = [0]

import sat_table as stb          # noqa: E402
import sat_tle as st             # noqa: E402
import test_r35 as t35           # noqa: E402


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8", errors="replace") as f:
        return f.read()


def tle_for(norad, name="X", day=300.0):
    n, l1, l2 = t35.mk_tle(name, norad, 26, day)
    tles, _notes = st.parse_tle_text("\n".join((n, l1, l2)))
    assert tles and tles[0].ok, (norad, tles)
    return tles[0]


ORIG = os.path.join(HERE, "testdata", "satellites_user_2026-11-01.txt")

# Очікування з брифу R54 (МГц -> Гц ×10^6, тон ×10): (NORAD, ім'я, rx1, tx1, ctcss, arm, rx2, tx2, rx3, tx3, aprs)
EXPECT = {
    43017: ("AO-91", 145_960_000, 435_250_000, 670, 0, 0, 0, 145_960_000, 0, ""),
    61781: ("AO-123", 435_400_000, 145_850_000, 670, 0, 0, 0, 436_210_000, 0, ""),
    40931: ("IO-86", 435_880_000, 145_880_000, 885, 0, 0, 0, 437_425_000, 0, ""),
    25544: ("ISS", 437_800_000, 145_990_000, 670, 0, 145_825_000, 145_825_000, 145_800_000, 0, "RS0ISS"),
    40908: ("LilacSat", 437_200_000, 144_350_000, 0, 0, 0, 0, 437_200_000, 0, ""),
    62461: ("POEM 4", 145_870_000, 0, 0, 0, 145_825_000, 145_825_000, 145_870_000, 0, ""),
    43678: ("PO-101", 145_900_000, 437_500_000, 1413, 0, 0, 0, 145_900_000, 0, ""),
    27607: ("SO-50", 436_795_000, 145_850_000, 670, 744, 0, 0, 436_795_000, 0, ""),
    62690: ("SO-124", 436_885_000, 145_925_000, 0, 0, 0, 0, 436_885_000, 0, ""),
    59112: ("SONATE-2", 145_880_000, 0, 0, 0, 145_825_000, 145_825_000, 145_840_000, 0, "DP0SNX"),
    57172: ("UmKA-1", 437_625_000, 0, 0, 0, 0, 0, 437_625_000, 0, ""),
}


def row_tuple(r):
    return (r.name, r.rx1, r.tx1, r.ctcss, r.arm, r.rx2, r.tx2, r.rx3, r.tx3, r.aprs)


def slot_of(r):
    return stb.fill_slot(st.Slot(r.name), r)


# ---------------------------------------------------------------------------------------------------------------------------------
def test_p1_original():
    rows, notes = stb.read_table_file(ORIG)
    check(len(rows) == 11 and not notes, "P1: оригінал -- 11 рядків без зауважень (%d, %r)" % (len(rows), notes))
    got = {r.norad: row_tuple(r) for r in rows}
    check(set(got) == set(EXPECT), "P1: номери NORAD: %r" % sorted(got))
    for k, exp in EXPECT.items():
        check(got.get(k) == exp, "P1: %d: %r != %r" % (k, got.get(k), exp))
    # tx1 = 0 не означає «передачі нема»: у POEM 4 і SONATE-2 є Tx2
    check(got[62461][6] == 145_825_000 and got[59112][6] == 145_825_000 and got[62461][2] == 0 and got[59112][2] == 0, "P1: POEM 4 / SONATE-2: Tx1=0, Tx2=145.825")
    errors, warns, nofreq = stb.validate_slots([slot_of(r) for r in rows])
    check(not errors and not warns and not nofreq, "P1: усі 11 рядків проходять перевірку без помилок і попереджень: %r %r %r" % (errors, warns, nofreq))
    # перший рядок файла -- заголовок, пропущений мовчки (не як сміття)
    first = open(ORIG, encoding="ascii").read().split("\n")[0]
    check(first.startswith("Cat") and not any("Cat" in n for n in notes), "P1: заголовок пропущено без зауваження")


def test_p2_starter():
    rows, notes = stb.default_rows()
    check(len(rows) == 9 and not notes, "P2: стартова таблиця -- 9 рядків (%d, %r)" % (len(rows), notes))
    nums = {r.norad for r in rows}
    check(62461 not in nums and 62690 not in nums, "P2: POEM 4 (62461) і SO-124 (62690) прибрано")
    check(nums == set(EXPECT) - {62461, 62690}, "P2: решта 9 на місці: %r" % sorted(nums))
    for r in rows:
        check(row_tuple(r) == EXPECT[r.norad], "P2: %d без змін проти оригіналу" % r.norad)
    orig_lines = [ln for ln in open(ORIG, encoding="ascii").read().split("\n") if ln.strip() and not ln.startswith(("62461U", "62690U"))]
    cur_lines = [ln for ln in open(os.path.join(HERE, "satellites.txt"), encoding="ascii").read().split("\n") if ln.strip()]
    check(cur_lines == orig_lines, "P2: рядки satellites.txt побайтово збігаються з оригіналом без двох зійшлих")
    import sat_table_data
    check([ln for ln in cur_lines] == list(sat_table_data.LINES), "P2: sat_table_data.py синхронний з satellites.txt (перегенеруй: python3 MDUV380_firmware/tools/sat_table.py)")
    check(os.path.isfile(os.path.join(HERE, "satellites_sources.md")), "P2: є satellites_sources.md")
    md = read(HERE, "satellites_sources.md")
    for tag in ("2026-11-01", "⚠", "AO-91", "IO-86", "AO-123", "POEM 4", "SO-124", "JE9PEL", "SatNOGS"):
        check(tag in md, "P2: у satellites_sources.md згадано «%s»" % tag)


def _hw_from_trx():
    t = read(APP, "source", "functions", "trx.c")
    blocks = [m.start() for m in re.finditer(r"RADIO_HARDWARE_FREQUENCY_BANDS\[RADIO_BANDS_TOTAL_NUM\]\s*=", t)]
    blk = t[blocks[1]:t.index("};", blocks[1])]
    blk = re.sub(r"#if defined\(ENABLE_SPECTRUM\).*?#else(.*?)#endif", r"\1", blk, flags=re.S)
    mins = [int(x) for x in re.findall(r"\.minFreq=(\d+)", blk)]
    maxs = [int(x) for x in re.findall(r"\.maxFreq=(\d+)", blk)]
    d = t.index("DEFAULT_USER_FREQUENCY_BANDS[RADIO_BANDS_TOTAL_NUM]")
    dblk = t[d:t.index("};", d)]
    dmins = [int(x) for x in re.findall(r"\.minFreq=(\d+)", dblk)]
    dmaxs = [int(x) for x in re.findall(r"\.maxFreq=(\d+)", dblk)]
    return mins, maxs, dmins, dmaxs


def test_p3_firmware_constants():
    mins, maxs, dmins, dmaxs = _hw_from_trx()
    check(len(mins) == 3 and len(maxs) == 3, "P3: trx.c: три апаратні смуги знайдено (%r %r)" % (mins, maxs))
    check(tuple((a * 10, b * 10) for a, b in zip(mins, maxs)) == stb.HW_BANDS_HZ, "P3: смуги приймання == trx.c (%r vs %r)" % (list(zip(mins, maxs)), stb.HW_BANDS_HZ))
    check(tuple((a * 10, b * 10) for a, b in zip(dmins, dmaxs)) == stb.TX_BANDS_HZ, "P3: межі передачі за замовчуванням == trx.c (%r)" % (list(zip(dmins, dmaxs)),))
    sett = read(APP, "source", "functions", "settings.c")
    check(re.search(r"txFreqLimited\s*=.{0,500}?BAND_LIMITS_ON_LEGACY_DEFAULT", sett, re.S) is not None, "P3: за замовчуванням txFreqLimited = BAND_LIMITS_ON_LEGACY_DEFAULT")
    sat_h = read(APP, "include", "functions", "satellite.h")
    check(re.search(r"ADDITION_DATA_SIZE\s+24", sat_h) is not None and st.ADDITIONAL_LEN == 24, "P3: AdditionalData = 24 Б")
    check(re.search(r"TLE_Name\[8\]", sat_h) is not None and st.NAME_LEN == 8, "P3: TLE_Name[8]")
    scr = read(APP, "source", "user_interface", "menuSatelliteScreen.c")
    check("rxFreq / 10" in scr and "txFreq / 10" in scr, "P3: частоти слота в Гц (ділення на 10 до одиниць 10 Гц каналу)")
    aprs = read(APP, "source", "functions", "aprs.c")
    for frag in ("AdditionalData[0], 6U", "AdditionalData[6] - '0'", "AdditionalData[7], 6U", "AdditionalData[13] - '0'", "(aprsConfig->paths[p].SSID + '0') << 1"):
        check(frag in aprs, "P3: aprs.c містить «%s»" % frag)


def test_p4_parser():
    hdr = "Cat  #,Name    ,    Rx1,    Tx1, CTCSS, ArmCTCSS,    Rx2,    Tx2,    Rx3,    Tx3,APRS Config\n"
    good = "25544U,ISS     ,437.800,145.990,     67,       0,145.825,145.825,145.800,      0,RS0ISS\n"
    r, n = stb.parse_table(hdr + good)
    check(len(r) == 1 and not n and row_tuple(r[0]) == EXPECT[25544], "P4: базовий рядок")
    r, n = stb.parse_table("\n\n  \n" + hdr + "\n\n" + good + "\n\n   \n")
    check(len(r) == 1 and not n, "P4: порожні рядки й пробільні рядки скрізь")
    r, n = stb.parse_table("25544u ,  ISS ,  437.8 , 145.99,67,0, 145.825 ,145.825,145.8,0,  RS0ISS  \n")
    check(len(r) == 1 and not n and row_tuple(r[0]) == EXPECT[25544], "P4: малі літери «u», зайві пробіли, без заголовка")
    r, n = stb.parse_table("25544,ISS,437.8,145.99,67,0,0,0,0,0\n")
    check(len(r) == 1 and r[0].aprs == "" and not n, "P4: без літери U і без 11-го поля")
    r, n = stb.parse_table("27607U,SO-50,436.795,145.85,67.1,74.4,0,0,0,0,\n")
    check(r and r[0].ctcss == 671, "P4: дробові субтони 67.1 -> 671")
    check(r[0].arm == 744, "P4: тон взведення 74.4 -> 744")
    r, n = stb.parse_table((hdr + good).replace("\n", "\r\n"))
    check(len(r) == 1 and not n, "P4: CRLF")
    r, n = stb.parse_table(b"\xef\xbb\xbf" + (hdr + good).encode("ascii"))
    check(len(r) == 1 and not n, "P4: BOM")
    # поганий рядок пропускається, решта читається
    mixed = hdr + "сміття без ком\n" + "99999U,TOOLONGNAME,1,1,0,0,0,0,0,0,\n" + "11111U,A,abc,0,0,0,0,0,0,0,\n" + "22222U,B,145.9,0\n" + \
            "33333U,C,5000,0,0,0,0,0,0,0,\n" + "44444U,D,145.9,0,400,0,0,0,0,0,\n" + good + good.replace("ISS     ", "ISS2    ") + "55555U,Ж,145.9,0,0,0,0,0,0,0,\n"
    r, n = stb.parse_table(mixed)
    check([x.norad for x in r] == [25544], "P4: з 9 рядків придатний лише один: %r" % ([x.norad for x in r],))
    check(len(n) == 8, "P4: зауваження на кожен пропущений рядок: %d" % len(n))
    check(any("сміття" in x for x in n) and any("TOOLONG" in x for x in n) and any("не число" in x for x in n) and any("полів" in x for x in n)
          and any("поза розумними" in x for x in n) and any("поза межами" in x for x in n) and any("уже був" in x for x in n) and any("ASCII" in x for x in n),
          "P4: причини названо: %r" % (n,))
    r, n = stb.parse_table(hdr)
    check(r == [] and n == [], "P4: лише заголовок -- 0 рядків")
    r, n = stb.parse_table("")
    check(r == [] and n == [], "P4: порожній текст")
    r, n = stb.parse_table("25544U,ISS,437.8,145.99,67,0,0,0,0,0,TOOLONGCALLSIGN\n")
    check(len(r) == 1 and r[0].aprs == "" and len(n) == 1 and "шлях APRS" in n[0], "P4: поганий шлях APRS -- рядок прочитано, шлях проігноровано з зауваженням")
    r, n = stb.parse_table("25544U,ISS,437.8,145.99,67,0,0,0,0,0,WIDE1-1,RS0ISS\n")
    check(len(r) == 1 and r[0].aprs == "WIDE1-1 RS0ISS", "P4: два елементи шляху через кому в 11-му полі: %r" % (r[0].aprs if r else None))
    r, n = stb.parse_table("1U,A,nan,0,0,0,0,0,0,0\n2U,B,inf,0,0,0,0,0,0,0\n3U,C,-1,0,0,0,0,0,0,0\n")
    check(r == [] and len(n) == 3, "P4: nan / inf / від'ємна частота відкидаються")


def fw_read_path(extra):
    """Те, що робить aprs.c (aprsBeaconingPrepareSatelliteConfig + заголовок AX.25): [(ім'я, SSID-цифра-в-ефір)] або [] (AdditionalData[0] == 0)."""
    b = bytes(extra).ljust(24, b"\x00")
    if b[0] == 0:
        return []
    out = []
    for off, ssid_off in ((0, 6), (7, 13)):
        name = b[off:off + 6].split(b"\x00", 1)[0]
        if off == 7 and not name:
            break
        out.append((name.decode("ascii"), chr(((b[ssid_off] - ord("0")) & 0xFF) + ord("0")) if ((b[ssid_off] - ord("0")) & 0xFF) < 10 else "?"))
    return out


def test_p5_aprs():
    b = stb.encode_aprs("RS0ISS")
    check(len(b) == 24 and b[0:6] == b"RS0ISS" and b[6] == ord("0") and b[7:] == b"\x00" * 17, "P5: RS0ISS -> ім'я [0..5], '0' у [6], далі нулі: %r" % b)
    check(fw_read_path(b) == [("RS0ISS", "0")], "P5: прошивка читає RS0ISS-0")
    b = stb.encode_aprs("DP0SNX")
    check(fw_read_path(b) == [("DP0SNX", "0")], "P5: DP0SNX")
    b = stb.encode_aprs("WIDE1-1, rs0iss-5")
    check(b[0:5] == b"WIDE1" and b[5] == 0 and b[6] == ord("1") and b[7:13] == b"RS0ISS" and b[13] == ord("5"), "P5: два елементи, верхній регістр, SSID: %r" % b)
    check(fw_read_path(b) == [("WIDE1", "1"), ("RS0ISS", "5")], "P5: прошивка читає обидва")
    check(stb.decode_aprs(b) == "WIDE1-1 RS0ISS-5", "P5: розбір назад: %r" % stb.decode_aprs(b))
    for txt in ("RS0ISS", "DP0SNX", "A", "ABC-9", "WIDE1-1 WIDE2-2", "RS0ISS-0", ""):
        rt = stb.aprs_to_text(stb.parse_aprs_text(txt))
        check(stb.decode_aprs(stb.encode_aprs(txt)) == rt, "P5: кругообіг «%s» -> «%s»" % (txt, rt))
    check(stb.encode_aprs("") == b"\x00" * 24 and stb.decode_aprs(b"") == "" and stb.decode_aprs(b"\x00" * 24) == "", "P5: порожній шлях -- 24 нулі, шляху нема")
    for bad in ("RS0ISS-10", "RS0ISS-15", "TOOLONG", "A B C", "RS0ISS-", "Ж", "AB$"):
        try:
            stb.parse_aprs_text(bad)
            check(False, "P5: «%s» мало відхилитись" % bad)
        except st.SatError:
            check(True, "")
    old = bytes(range(1, 25))
    new = stb.encode_aprs("RS0ISS", old)
    check(new[14:] == old[14:] and new[:7] == b"RS0ISS0", "P5: хвіст [14..23] зберігається зі старого значення")
    odd = b"RS0ISS\x07" + b"\x00" * 17
    check(stb.decode_aprs(odd) == "RS0ISS-?", "P5: нечитний SSID показано «-?»")


def test_p6_block():
    rows, _n = stb.read_table_file(ORIG)
    by = {r.norad: r for r in rows}
    s = slot_of(by[25544])
    raw = s.pack()
    check(len(raw) == 100, "P6: запис 100 Б")
    vals = struct.unpack_from("<IIHHIIII", raw, 48)
    check(vals == (437_800_000, 145_990_000, 670, 0, 145_825_000, 145_825_000, 145_800_000, 0), "P6: ISS: зсуви 48..75: %r" % (vals,))
    check(raw[76:82] == b"RS0ISS" and raw[82] == ord("0") and raw[83:100] == b"\x00" * 17, "P6: ISS: шлях APRS у AdditionalData (зсув 76)")
    s2 = slot_of(by[27607])
    vals = struct.unpack_from("<IIHH", s2.pack(), 48)
    check(vals == (436_795_000, 145_850_000, 670, 744), "P6: SO-50: тон 670 і тон взведення 744 (зсуви 56, 58): %r" % (vals,))
    back = st.Slot.unpack(raw)
    check(back.rx1 == s.rx1 and back.tx1 == s.tx1 and back.ctcss == s.ctcss and back.rx2 == s.rx2 and back.tx2 == s.tx2 and back.rx3 == s.rx3 and back.extra == s.extra,
          "P6: розпаковка вертає те саме")
    check(stb.decode_aprs(back.extra) == "RS0ISS", "P6: шлях після розпаковки")
    for r in rows:
        sl = slot_of(r)
        check(st.Slot.unpack(sl.pack()).freq_text() == sl.freq_text(), "P6: %s кругообіг" % r.name)
    check(slot_of(by[59112]).freq_text().startswith("RX 145.88 / TX - МГц") and "APRS 145.825/145.825" in slot_of(by[59112]).freq_text(), "P6: підпис SONATE-2: %s" % slot_of(by[59112]).freq_text())
    check(st.Slot("Z").freq_text() == "без частот", "P6: порожній слот -- «без частот»")


def test_p7_autofill():
    table = stb.by_norad(stb.read_table_file(ORIG)[0])
    tles = [tle_for(40908, "CAS-3H"), tle_for(25544, "ISS (ZARYA)"), tle_for(777, "NOPE-1"), tle_for(27607, "SAUDISAT 1C (SO-50)")]
    slots, dropped = stb.merge_add_table([], tles, table)
    check(dropped == 0 and [s.name for s in slots] == ["LilacSat", "ISS", "NOPE-1", "SO-50"], "P7: ім'я з таблиці, а не з Celestrak: %r" % [s.name for s in slots])
    iss = slots[1]
    check((iss.rx1, iss.tx1, iss.ctcss, iss.rx2, iss.tx2, iss.rx3) == (437_800_000, 145_990_000, 670, 145_825_000, 145_825_000, 145_800_000) and stb.decode_aprs(iss.extra) == "RS0ISS",
          "P7: ISS заповнено повністю, включно з шляхом APRS")
    check(slots[3].arm == 744, "P7: SO-50: тон взведення")
    nope = slots[2]
    check(not stb.slot_has_freqs(nope) and stb.check_slot(nope)[0][0] == "nofreq", "P7: немає запису в таблиці -> нулі й мітка «без частот»")
    # ручні частоти не перезаписуються
    manual = st.Slot("ISS", tles[1].line1, tles[1].line2, rx1=145_000_000)
    out, filled, kept, nomatch, amb = stb.fill_existing([manual, st.Slot("LilacSat"), st.Slot("ZZZ")], list(table.values()))
    check(out[0].rx1 == 145_000_000 and out[0].tx1 == 0 and kept == ["ISS"], "P7: слот із ручною частотою не чіпається")
    check(filled == ["LilacSat"] and out[1].rx1 == 437_200_000 and out[1].tx1 == 144_350_000, "P7: порожній слот за назвою заповнено: %r" % filled)
    check(nomatch == ["ZZZ"] and not stb.slot_has_freqs(out[2]), "P7: назви нема в таблиці -> лишається")
    # ручний шлях APRS або субтон теж «вручну»
    s_tone = st.Slot("ISS", ctcss=1000)
    check(not stb.slot_is_blank(s_tone) and not stb.slot_is_blank(st.Slot("ISS", extra=b"AB" + b"\x00" * 22)) and stb.slot_is_blank(st.Slot("ISS")), "P7: порожнім слот вважається лише без частот, субтонів і шляху")
    # неоднозначна назва
    dup = [stb.Row(1, "ABC", rx1=145_900_000), stb.Row(2, "abc", rx1=145_800_000)]
    out, filled, kept, nomatch, amb = stb.fill_existing([st.Slot("ABC")], dup)
    check(amb == ["ABC"] and not filled and not stb.slot_has_freqs(out[0]), "P7: назва двічі в таблиці -- слот не чіпається")
    # слот, прочитаний з рації, зіставляється без урахування регістру й розділових знаків
    out, filled, *_ = stb.fill_existing([st.Slot("so-50")], list(table.values()))
    check(filled == ["so-50"], "P7: «so-50» == SO-50")
    # оновлення елементів зберігає частоти (R35, незмінно)
    upd = st.apply_updates(slots, {1: tle_for(25544, "ISS (ZARYA)", day=310.0)})
    check(upd[1].rx2 == 145_825_000 and stb.decode_aprs(upd[1].extra) == "RS0ISS", "P7: apply_updates зберігає частоти й шлях APRS")
    # merge_add_table в наявні слоти не втручається
    base = [manual]
    merged, _d = stb.merge_add_table(base, [tles[0]], table)
    check(merged[0].rx1 == 145_000_000 and merged[0].tx1 == 0, "P7: наявний слот у merge_add_table не змінюється")


def test_p8_add_from_table():
    rows = stb.read_table_file(ORIG)[0]
    tles = [tle_for(43017, "AO-91"), tle_for(25544, "ISS"), tle_for(25544, "ISS", day=250.0), tle_for(59112, "SONATE-2"), tle_for(99999, "OTHER")]
    out, rep = stb.add_from_table([], rows, tles)
    check(rep.added == ["AO-91", "ISS", "SONATE-2"], "P8: додано лише ті, для яких є TLE, у порядку таблиці: %r" % rep.added)
    names_missing = [n for n, _k in rep.missing]
    check(names_missing == ["AO-123", "IO-86", "LilacSat", "POEM 4", "PO-101", "SO-50", "SO-124", "UmKA-1"], "P8: «немає TLE» перелічено: %r" % names_missing)
    check([k for _n, k in rep.missing][:2] == [61781, 40931], "P8: у переліку є номери NORAD")
    iss = [s for s in out if s.name == "ISS"][0]
    newest = max((t for t in tles if t.catalog == "25544"), key=lambda t: t.epoch)
    check(iss.l1 == st.fields1_text(newest.line1), "P8: з двох наборів ISS взято найсвіжіший")
    check(next(s for s in out if s.name == "SONATE-2").rx2 == 145_825_000, "P8: частоти підтягнулись")
    out2, rep2 = stb.add_from_table(out, rows, tles)
    check(rep2.added == [] and rep2.exists == ["AO-91", "ISS", "SONATE-2"] and len(out2) == 3, "P8: повторне додавання не дублює: %r" % rep2.exists)
    txt = stb.report_text(rep, len(rows))
    check("Немає TLE" in txt and "не помилка" in txt and "AO-123 (61781)" in txt, "P8: текст звіту")
    # понад 25
    big_rows = [stb.Row(1000 + i, "S%d" % i, rx1=145_900_000, tx1=435_000_000) for i in range(30)]
    big_tles = [tle_for(1000 + i, "S%d" % i) for i in range(30)]
    out3, rep3 = stb.add_from_table([], big_rows, big_tles)
    check(len(out3) == 25 and len(rep3.added) == 25 and len(rep3.dropped) == 5 and "Не влізло" in stb.report_text(rep3, 30), "P8: 30 рядків -- 25 слотів, 5 не влізло з попередженням")
    out4, rep4 = stb.add_from_table([st.Slot("OLD%d" % i) for i in range(24)], big_rows[:3], big_tles[:3])
    check(len(out4) == 25 and rep4.added == ["S0"] and rep4.dropped == ["S1", "S2"], "P8: вільний лише один слот")
    # merge_add_table з >25
    m, dropped = stb.merge_add_table([], big_tles, stb.by_norad(big_rows))
    check(len(m) == 25 and dropped == 5, "P8: merge_add_table: 25 слотів, 5 не влізло")
    # TLE з проблемами не береться
    bad = tle_for(43017, "AO-91")
    bad.problems = ["тест"]
    o5, r5 = stb.add_from_table([], rows[:1], [bad])
    check(o5 == [] and r5.missing and r5.missing[0][1] == 43017, "P8: непридатний набір вважається відсутнім")


def one(**kw):
    s = st.Slot("T")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def levels(s):
    return sorted(l for l, _t in stb.check_slot(s))


def test_p9_validation():
    # коректні
    check(levels(one(rx1=145_960_000, tx1=435_250_000)) == [], "P9: 145.96 / 435.25 без зауважень")
    check(levels(one(rx2=145_825_000, tx2=145_825_000)) == [], "P9: набір APRS окремо коректний")
    # МУТАНТ 1: частота поза апаратними смугами = помилка (кожне з шести полів окремо)
    for fld in ("rx1", "tx1", "rx2", "tx2", "rx3", "tx3"):
        for hz in (100_000_000, 126_999_999, 178_000_001, 189_999_999, 282_000_001, 379_999_999, 564_000_001, 900_000_000):
            lv = levels(one(**{"rx1": 145_960_000, fld: hz}) if fld != "rx1" else one(rx1=hz))
            check("error" in lv, "P9/мутант «поза смугою»: %s = %d -> помилка (%r)" % (fld, hz, lv))
    for hz in (127_000_000, 178_000_000, 190_000_000, 282_000_000, 380_000_000, 564_000_000):
        check("error" not in levels(one(rx1=hz)), "P9: межа смуги рації %d включно" % hz)
    # МУТАНТ 2: TX поза межами передачі за замовчуванням (але в смузі рації) = попередження, не помилка
    for fld in ("tx1", "tx2", "tx3"):
        for hz in (150_000_000, 143_999_999, 148_000_001, 200_000_000, 270_000_000, 460_000_000, 419_999_999, 450_000_001):
            lv = levels(one(rx1=145_960_000, **{fld: hz}))
            check(lv == ["warn"], "P9/мутант «TX поза межами»: %s = %d -> попередження (%r)" % (fld, hz, lv))
    for hz in (144_000_000, 148_000_000, 222_000_000, 225_000_000, 420_000_000, 450_000_000):
        check(levels(one(rx1=145_960_000, tx1=hz)) == [], "P9: межа передачі %d включно" % hz)
    # RX поза межами передачі -- не попередження (RX можна будь-де в смузі рації)
    check(levels(one(rx1=137_000_000)) == [], "P9: RX 137 МГц у смузі рації без зауважень")
    # МУТАНТ 3: нулі
    check(levels(st.Slot("Z")) == ["nofreq"], "P9/мутант «нулі»: усі нульові -- «без частот»")
    check(levels(one(ctcss=670)) == ["nofreq"], "P9: лише субтон -- усе одно «без частот»")
    check(levels(one(tx2=145_825_000)) == [], "P9: лише Tx2 -- не «без частот»")
    # кожен набір окремо: помилка в наборі 2 при коректному наборі 1
    iss = slot_of(stb.by_norad(stb.read_table_file(ORIG)[0])[25544])
    iss.tx2 = 90_000_000
    errs = [t for l, t in stb.check_slot(iss) if l == "error"]
    check(len(errs) == 1 and "TX2" in errs[0] and "APRS" in errs[0], "P9: помилка названа за набором: %r" % errs)
    iss.tx2 = 270_000_000
    w = [t for l, t in stb.check_slot(iss) if l == "warn"]
    check(len(w) == 1 and "TX2" in w[0], "P9: попередження названо за набором: %r" % w)
    # validate_slots: номер слота й ім'я
    e, w, nf = stb.validate_slots([one(rx1=145_960_000), one(rx1=100_000_000, name="BAD"), st.Slot("ZERO")])
    check(len(e) == 1 and e[0].startswith("слот 2 «BAD»") and len(nf) == 1 and nf[0].startswith("слот 3 «ZERO»") and not w, "P9: validate_slots: %r %r %r" % (e, w, nf))
    # перевірка справді залежить від констант (мутація констант змінює результат)
    old = stb.HW_BANDS_HZ
    try:
        stb.HW_BANDS_HZ = ((144_000_000, 146_000_000),)
        check("error" in levels(one(rx1=437_000_000)), "P9: мутація HW_BANDS_HZ видна")
    finally:
        stb.HW_BANDS_HZ = old
    check(levels(one(rx1=437_000_000)) == [], "P9: константи відновлено")


def test_p10_wiring():
    rt = read(FW, "tests", "run_tests.sh")
    check("test_r54 " in rt or "test_r54;" in rt or re.search(r"\btest_r54\b", rt) is not None, "P10: test_r54 у tests/run_tests.sh")
    check(re.search(r"\btest_r54_ui\b", rt) is not None, "P10: test_r54_ui у tests/run_tests.sh")
    tt = read(os.path.dirname(FW), "TESTING.md")
    for n in ("DC1", "DC2", "DC3", "DC4", "DC5"):
        check(re.search(r"\b%s\b" % n, tt) is not None, "P10: у TESTING.md є крок %s" % n)
    ps = read(HERE, "cps_ui", "p_satellites.py")
    check("НЕ ПЕРЕВІРЕНО" not in ps.split("SOURCES")[1].split("\n")[0], "P10: біля адреси Celestrak нема мітки «НЕ ПЕРЕВІРЕНО»")
    check("взято з брифу" not in ps, "P10: підказка не називає адресу неперевіреною")
    # прошивка не змінена: жодного файла application/ у дифі цього завдання (звіряється в процесі доставки; тут -- що модуль не пише в блок інакше)
    check(len(st.build_block([stb.fill_slot(st.Slot("A"), stb.Row(1, "A", rx1=145_900_000))])) == 2520, "P10: блок -- 2520 Б")


def main():
    for t in (test_p1_original, test_p2_starter, test_p3_firmware_constants, test_p4_parser, test_p5_aprs, test_p6_block, test_p7_autofill, test_p8_add_from_table,
              test_p9_validation, test_p10_wiring):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        return 1
    print("test_r54: усе гаразд (%d перевірок: таблиця частот супутників, автозаповнення, перевірка меж, шлях APRS)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
