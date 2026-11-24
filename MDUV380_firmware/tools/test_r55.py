#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R55: стартова таблиця без недостовірного, субтони лише на передачу, вік TLE і таблиці. Хост-тести, без рації й без Tk.

E1  склад стартової таблиці: 8 рядків, без NORAD 62461 / 62690 / 40931, Rx3 AO-123 = 0, тон AO-91 = 670; джерела пояснюють кожне прибрання; оригінал-фікстура (11 рядків) не змінилась;
E2  вік TLE в усіх порогових точках: 7 / 8 / 30 / 31 діб, ISS 3 / 4 доби (за назвою і за NORAD), дробові доби, епоха в майбутньому, нечитна епоха; МУТАНТИ для кожного порога;
E3  підсумок віку, старі слоти для окремого підтвердження запису, текст колонки;
E4  субтони лише на передачу: слот, блок прошивки й код екрана супутників не мають приймального субтону; «TX 67» у підсумку слота; парсер таблиці читає стовпець CTCSS як тон передачі;
E5  прошивка (лише читання): rxTone екрана супутників = NONE при кожному вході, txTone ставиться з txCTCSS вибраного набору, у наборів APRS / маяк субтону передачі нема;
E6  дата перевірки таблиці: VERIFIED_DATE, діб тому, нагадування лише ПІСЛЯ 90 діб, дата зміни файла; МУТАНТ порога;
E7  підключено до tests/run_tests.sh, є кроки DD1..DD4 у TESTING.md.
Запуск: python3 tools/test_r55.py"""
import datetime
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
FAILS = []
PASSED = [0]

import sat_table as stb          # noqa: E402
import sat_tle as st             # noqa: E402
import test_r35 as t35           # noqa: E402

ORIG = os.path.join(HERE, "testdata", "satellites_user_2026-11-01.txt")
NOW = datetime.datetime(2026, 11, 1)            # 2026-11-01 00:00 -- день року 305


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8", errors="replace") as f:
        return f.read()


def aged(name, days, norad=50001, now=NOW):
    """Слот, епоха якого на момент now рівно days діб тому (days може бути дробовим)."""
    epoch_day = 305.0 - days
    tle = st.Tle(*t35.mk_tle(name, norad, 26, epoch_day))
    s = st.Slot.from_tle(tle, name=name)
    assert abs(s.age_days(now) - days) < 1e-3, (days, s.age_days(now))
    return s


# ---------------------------------------------------------------------------------------------------------------------------------
def test_e1_table():
    rows, notes = stb.default_rows()
    check(len(rows) == 8 and not notes, "E1: стартова таблиця -- 8 рядків (%d, %r)" % (len(rows), notes))
    by = {r.name: r for r in rows}
    check(set(by) == {"AO-91", "AO-123", "ISS", "LilacSat", "PO-101", "SO-50", "SONATE-2", "UmKA-1"}, "E1: склад: %r" % sorted(by))
    nums = {r.norad for r in rows}
    check(not ({62461, 62690, 40931} & nums), "E1: немає NORAD 62461, 62690, 40931")
    check(by["AO-123"].rx3 == 0 and by["AO-123"].rx1 == 435_400_000 and by["AO-123"].tx1 == 145_850_000, "E1: Rx3 AO-123 = 0, решта AO-123 без змін")
    check(by["AO-91"].ctcss == 670 and by["AO-91"].rx1 == 145_960_000 and by["AO-91"].tx1 == 435_250_000, "E1: тон AO-91 = 670")
    errors, warns, nofreq = stb.validate_slots([stb.fill_slot(st.Slot(r.name), r) for r in rows])
    check(not errors and not warns and not nofreq, "E1: усі 8 проходять перевірку частот")
    # фікстура-оригінал не змінилась (11 рядків, IO-86 і Rx3 AO-123 на місці)
    orows, onotes = stb.read_table_file(ORIG)
    ob = {r.name: r for r in orows}
    check(len(orows) == 11 and not onotes and ob["IO-86"].rx1 == 435_880_000 and ob["AO-123"].rx3 == 436_210_000, "E1: оригінал на 11 рядків лишився незмінним")
    md = read(HERE, "satellites_sources.md")
    for frag in ("IO-86", "40931", "404", "AO-123", "436.210", "JE9PEL", "2026-11-01", "DD4", "AO-91"):
        check(frag in md, "E1: у satellites_sources.md згадано «%s»" % frag)
    check(len(re.findall(r"\|\s*40931\s*\|", md)) == 0, "E1: IO-86 не лишився рядком таблиці джерел")


def levels_table():
    """[(звичайний, ISS)] для віку 0, 3, 4, 7, 8, 30, 31 діб."""
    out = []
    for n in (0, 3, 4, 7, 8, 30, 31):
        out.append((st.age_level(aged("SAT", n), NOW)[1], st.age_level(aged("ISS", n), NOW)[1]))
    return out


EXPECT_LEVELS = [("ok", "ok"), ("ok", "ok"), ("ok", "stale"), ("ok", "stale"), ("stale", "stale"), ("stale", "stale"), ("old", "old")]


def test_e2_age():
    check(st.TLE_AGE_GOOD_DAYS == 7 and st.TLE_AGE_STALE_DAYS == 30 and st.TLE_AGE_GOOD_DAYS_ISS == 3 and st.ISS_NORAD == 25544, "E2: пороги в іменованих константах: 7 / 30 / ISS 3")
    check(levels_table() == EXPECT_LEVELS, "E2: пороги 0/3/4/7/8/30/31 діб (звичайний, ISS): %r" % levels_table())
    for n, exp in ((7, "ok"), (8, "stale"), (30, "stale"), (31, "old")):
        d, lvl = st.age_level(aged("SAT", n), NOW)
        check(d == n and lvl == exp, "E2: %d діб -> %s (%r)" % (n, exp, (d, lvl)))
    for n, exp in ((3, "ok"), (4, "stale"), (30, "stale"), (31, "old")):
        d, lvl = st.age_level(aged("ISS", n), NOW)
        check(d == n and lvl == exp, "E2: ISS %d діб -> %s (%r)" % (n, exp, (d, lvl)))
    # ISS за NORAD (слот названо інакше) і за назвою в різному написанні
    check(st.age_level(aged("MYSAT", 4), NOW, norad=25544)[1] == "stale", "E2: ISS за NORAD 25544: 4 доби -- жовте")
    check(st.age_level(aged("MYSAT", 4), NOW, norad=1234)[1] == "ok", "E2: чужий NORAD -- звичайні пороги")
    check(st.age_level(aged("iss", 4), NOW)[1] == "stale" and st.age_level(aged("ISS-2", 4), NOW)[1] == "ok", "E2: за назвою «ISS» (регістр не важливий); «ISS-2» -- не ISS")
    # вік рахується в цілих добах (дробова частина відкидається), як і показується
    check(st.age_level(aged("SAT", 7.9), NOW) == (7, "ok") and st.age_level(aged("SAT", 30.9), NOW) == (30, "stale") and st.age_level(aged("SAT", 31.0), NOW) == (31, "old"),
          "E2: 7.9 -> 7 діб, 30.9 -> 30, 31.0 -> 31")
    check(st.age_level(aged("ISS", 3.9), NOW) == (3, "ok"), "E2: ISS 3.9 -> 3 доби, без позначки")
    # епоха в майбутньому (збитий годинник) -> 0 діб; нечитна епоха
    fut = aged("SAT", 0)
    check(st.age_level(fut, NOW - datetime.timedelta(days=2)) == (0, "ok"), "E2: епоха в майбутньому -> 0 діб")
    check(st.age_level(st.Slot("EMPTY"), NOW) == (None, "unknown") and st.age_text(st.Slot("EMPTY"), NOW) == "?", "E2: нема епохи -> «?»")
    # поточна дата -- параметр: той самий слот у різні дні
    s = aged("SAT", 0)
    check([st.age_level(s, NOW + datetime.timedelta(days=d))[1] for d in (7, 8, 30, 31)] == ["ok", "stale", "stale", "old"], "E2: now -- параметр функції")
    # МУТАНТИ порогів: кожна підміна константи змінює таблицю рівнів (тест реагує)
    base = levels_table()
    for const, val in (("TLE_AGE_GOOD_DAYS", 6), ("TLE_AGE_GOOD_DAYS", 8), ("TLE_AGE_STALE_DAYS", 29), ("TLE_AGE_STALE_DAYS", 31), ("TLE_AGE_GOOD_DAYS_ISS", 2), ("TLE_AGE_GOOD_DAYS_ISS", 4)):
        old = getattr(st, const)
        setattr(st, const, val)
        try:
            check(levels_table() != base and levels_table() != EXPECT_LEVELS, "E2/мутант: %s = %d змінює рівні (тест це бачить)" % (const, val))
        finally:
            setattr(st, const, old)
    check(levels_table() == EXPECT_LEVELS, "E2: константи відновлено")
    # мутант «ISS без суворості»: звичайні пороги для ISS дали б інший результат на 4 добі
    old = st.is_iss
    st.is_iss = lambda slot, norad=None: False
    try:
        check(st.age_level(aged("ISS", 4), NOW)[1] == "ok" and levels_table() != EXPECT_LEVELS, "E2/мутант: без особливого порога ISS 4 доби -- «ok» (тест це ловить)")
    finally:
        st.is_iss = old


def test_e3_summary():
    check(st.age_text(aged("SAT", 5), NOW) == "5 дн." and st.age_text(aged("SAT", 12), NOW) == "12 дн. застарів" and st.age_text(aged("SAT", 40), NOW) == "40 дн. старий",
          "E3: колонка віку: %r %r %r" % (st.age_text(aged("SAT", 5), NOW), st.age_text(aged("SAT", 12), NOW), st.age_text(aged("SAT", 40), NOW)))
    slots = [aged("FRESH", 2, 1), aged("STALE1", 12, 2), aged("ISS", 5, 25544), aged("OLD1", 40, 3), aged("OLD2", 31, 4), st.Slot("NOEPOCH")]
    old = st.old_slots(slots, NOW)
    check(old == [(4, "OLD1", 40), (5, "OLD2", 31)], "E3: старі слоти для підтвердження запису (номер, ім'я, діб): %r" % (old,))
    txt, has_old = st.age_summary(slots, NOW)
    check(has_old and "OLD1 (40 дн.)" in txt and "OLD2 (31 дн.)" in txt and "STALE1 (12 дн.)" in txt and "ISS (5 дн.)" in txt and "FRESH" not in txt and "NOEPOCH" not in txt,
          "E3: підсумок віку: %s" % txt)
    txt2, has_old2 = st.age_summary([aged("A", 8), aged("B", 3)], NOW)
    check(not has_old2 and "A (8 дн.)" in txt2 and "B" not in txt2.replace("Застаріли", ""), "E3: лише жовті -- без червоного прапора: %s" % txt2)
    check(st.age_summary([aged("A", 1)], NOW) == ("", False) and st.old_slots([aged("A", 30)], NOW) == [], "E3: свіжі / рівно 30 діб -- нічого не просить")


def test_e4_tx_only():
    # слот і блок
    s = st.Slot("SO-50", rx1=436_795_000, tx1=145_850_000, ctcss=670, arm=744)
    attrs = [a.lower() for a in vars(s)]
    check(not any(("rxtone" in a or "rx_tone" in a or "rxctcss" in a or "rx_ctcss" in a or "rxcss" in a) for a in attrs), "E4: у слоті нема приймального субтону: %r" % attrs)
    sat_h = read(APP, "include", "functions", "satellite.h")
    check("rxCTCSS" not in sat_h and "rxTone" not in sat_h and "txCTCSS" in sat_h and "armCTCSS" in sat_h, "E4: у satellite.h лише txCTCSS / armCTCSS (приймального нема)")
    # текст підсумку
    t = s.freq_text()
    check("TX 67 Гц" in t and "взведення TX 74.4 Гц" in t, "E4: підсумок слота: «TX 67», «взведення TX 74.4»: %s" % t)
    check("TX 67" in st.Slot("A", rx1=1, tx1=2, ctcss=670).freq_text() and "TX 88.5" in st.Slot("A", rx1=145_000_000, tx1=435_000_000, ctcss=885).freq_text(), "E4: 670 -> «TX 67», 885 -> «TX 88.5»")
    check(", TX " not in st.Slot("A", rx1=145_000_000, tx1=435_000_000).freq_text() and "взведення" not in st.Slot("A", rx1=145_000_000, tx1=435_000_000).freq_text(), "E4: без субтону -- тон не згадується")
    check(not re.search(r"(?<!TX )\b67\b", s.freq_text().replace("TX 67", "")), "E4: голе «67» (без «TX») у підсумку не трапляється")
    # парсер таблиці: стовпець CTCSS = тон передачі (лише голосовий набір)
    r, _n = stb.parse_table("27607U,SO-50,436.795,145.85,67,74.4,0,0,436.795,0,\n")
    sl = stb.fill_slot(st.Slot("SO-50"), r[0])
    check(sl.ctcss == 670 and sl.arm == 744, "E4: стовпці CTCSS / ArmCTCSS -> тон передачі й тон взведення")
    check("приймання завжди без субтону" in read(HERE, "sat_table.py").lower(), "E4: sat_table.py: стовпці CTCSS / ArmCTCSS -- тон передачі, приймання без субтону")


def test_e5_firmware_readonly():
    scr = read(APP, "source", "user_interface", "menuSatelliteScreen.c")
    check("satelliteChannelData.rxTone = CODEPLUG_CSS_TONE_NONE;" in scr, "E5: перший вхід: rxTone = CODEPLUG_CSS_TONE_NONE (menuSatelliteScreen.c)")
    check(len(re.findall(r"trxSetRxCSS\(RADIO_DEVICE_PRIMARY, satelliteChannelData\.rxTone\);// Never any Rx CTCSS", scr)) == 1, "E5: кожен вхід: trxSetRxCSS(..., rxTone) з коментарем «Never any Rx CTCSS»")
    check(len(re.findall(r"rxTone\s*=", scr)) == 1, "E5: rxTone в екрані супутників присвоюється лише один раз (NONE): %d" % len(re.findall(r"rxTone\s*=", scr)))
    tx_assign = re.findall(r"currentChannelData->txTone\s*=\s*([^;]+);", scr)
    # R66D: поза прапорцем -- лише стокове присвоєння; під ENABLE_SAT_TONE_SYNC ще рівно два, і лише через satelliteTxToneFor(поточний супутник, поточний набір)
    stock = "currentActiveSatellite->freqs[currentSatelliteFreqIndex].txCTCSS"
    synced = "satelliteTxToneFor(currentActiveSatellite, currentSatelliteFreqIndex)"
    check(sorted(tx_assign) == sorted([stock, synced, synced]), "E5: txTone ставиться лише з txCTCSS вибраного набору (стокове + 2 під ENABLE_SAT_TONE_SYNC): %r" % (tx_assign,))
    sat_c = read(APP, "source", "functions", "satellite.c")
    check("freqs[SATELLITE_APRS_FREQ].txCTCSS = currentSatelliteData->freqs[SATELLITE_APRS_FREQ].armCTCSS = 0;" in sat_c
          and "freqs[SATELLITE_OTHER_FREQ].txCTCSS = currentSatelliteData->freqs[SATELLITE_OTHER_FREQ].armCTCSS = 0;" in sat_c, "E5: у наборів APRS / маяк субтон передачі й взведення = 0 (satellite.c)")
    check(len(re.findall(r"freqs\[SATELLITE_(?:APRS|OTHER)_FREQ\]\.(?:txCTCSS|armCTCSS) = 0;//codeplugKepsData", scr)) == 4, "E5: loadKeps: субтон наборів APRS / маяк = 0 (4 присвоєння)")
    tx = read(APP, "source", "user_interface", "uiTxScreen.c")
    check("trxSetTxCSS(currentChannelData->txTone);" in tx and "trxSetRxCSS(RADIO_DEVICE_PRIMARY, currentChannelData->rxTone);" in tx, "E5: uiTxScreen.c: на передачі -- txTone, після неї RX-CSS = rxTone (NONE)")
    # спостереження для звіту (не помилка тесту): клавіші 1/2/3 змінюють лише currentSatelliteFreqIndex, txTone не оновлюється
    keys = re.findall(r"^\t+currentSatelliteFreqIndex = SATELLITE_\w+;", scr, re.M)
    check(len(keys) == 3, "E5: клавіші 1/2/3 лише міняють currentSatelliteFreqIndex (3 присвоєння), стокове OpenGD77 txTone тут не оновлює (R55); з R66D це робить блок під ENABLE_SAT_TONE_SYNC")


def test_e6_table_date():
    d0 = datetime.date(2026, 11, 1)
    check(stb.TABLE_RECHECK_DAYS == 90, "E6: поріг нагадування 90 діб у константі")
    check(stb.builtin_verified_date() == d0, "E6: VERIFIED_DATE вбудованої таблиці == 2026-11-01")
    for n, remind in ((0, False), (89, False), (90, False), (91, True), (300, True)):
        today = d0 + datetime.timedelta(days=n)
        txt = stb.table_recheck_text(d0, today)
        check(bool(txt) == remind, "E6: %d діб після звірки -- нагадування %s (%r)" % (n, "є" if remind else "нема", txt[:40]))
        if remind:
            check("AMSAT" in txt and "https://www.amsat.org/live-fm-satellites/" in txt and ("%d діб" % n) in txt, "E6: у нагадуванні AMSAT FM, адреса і скільки діб: %s" % txt)
    check(stb.table_age_days(d0, d0 + datetime.timedelta(days=5)) == 5 and stb.table_age_days(d0, d0 - datetime.timedelta(days=3)) == 0 and stb.table_age_days(None, d0) is None,
          "E6: діб тому: 5; дата в майбутньому -> 0; невідома -> None")
    check(stb.table_date_text("вбудована", d0, d0 + datetime.timedelta(days=3)) == "вбудована, перевірена 2026-11-01 (3 діб тому)", "E6: підпис вбудованої: %s" % stb.table_date_text("вбудована", d0, d0 + datetime.timedelta(days=3)))
    check(stb.table_date_text("файл x.txt", d0, d0) == "файл x.txt, змінено 2026-11-01 (0 діб тому)" and "невідома" in stb.table_date_text("файл x.txt", None, d0), "E6: підпис свого файла й невідомої дати")
    check(stb.table_recheck_text(None, d0) == "", "E6: дата невідома -- без нагадування")
    # дата зміни файла
    p = os.path.join(tempfile.mkdtemp(prefix="r55_"), "satellites.txt")
    open(p, "wb").write(open(ORIG, "rb").read())
    ts = datetime.datetime(2026, 7, 4, 12, 0).timestamp()
    os.utime(p, (ts, ts))
    check(stb.file_date(p) == datetime.date(2026, 7, 4) and stb.file_date(p + ".нема") is None, "E6: дата зміни файла береться з mtime")
    check(stb.table_recheck_text(stb.file_date(p), d0) != "" and stb.table_age_days(stb.file_date(p), d0) == 120, "E6: файл 4 липня -> 120 діб -> нагадування")
    # МУТАНТ порога
    old = stb.TABLE_RECHECK_DAYS
    stb.TABLE_RECHECK_DAYS = 30
    try:
        check(stb.table_recheck_text(d0, d0 + datetime.timedelta(days=60)) != "" and stb.table_recheck_text(d0, d0 + datetime.timedelta(days=90)) != "", "E6/мутант: поріг 30 дає нагадування вже на 60-й день (тест це бачить)")
    finally:
        stb.TABLE_RECHECK_DAYS = old
    check(stb.table_recheck_text(d0, d0 + datetime.timedelta(days=60)) == "", "E6: константу відновлено")
    # генератор записує дату
    tmp = tempfile.mkdtemp(prefix="r55gen_")
    dst = os.path.join(tmp, "sat_table_data.py")
    stb.generate_data_module(dst=dst, verified="2030-01-02")
    check("VERIFIED_DATE = '2030-01-02'" in read(dst) and "LINES = (" in read(dst), "E6: генератор записує VERIFIED_DATE разом з рядками")


def test_e7_wiring():
    rt = read(FW, "tests", "run_tests.sh")
    check(re.search(r"\btest_r55\b", rt) is not None and re.search(r"\btest_r55_ui\b", rt) is not None, "E7: test_r55 і test_r55_ui у tests/run_tests.sh")
    tt = read(os.path.dirname(FW), "TESTING.md") + read(os.path.dirname(FW), "docs", "archive", "TESTING-history.md")  # R105: старі блоки в архіві
    for n in ("DD1", "DD2", "DD3", "DD4"):
        check(re.search(r"\b%s\b" % n, tt) is not None, "E7: у TESTING.md є крок %s" % n)


def main():
    for t in (test_e1_table, test_e2_age, test_e3_summary, test_e4_tx_only, test_e5_firmware_readonly, test_e6_table_date, test_e7_wiring):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append("%s: виняток %r" % (t.__name__, e))
    if FAILS:
        print("\nПРОВАЛІВ: %d" % len(FAILS))
        return 1
    print("test_r55: усе гаразд (%d перевірок: таблиця без недостовірного, вік TLE, субтони лише на передачу, дата перевірки таблиці)." % PASSED[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
