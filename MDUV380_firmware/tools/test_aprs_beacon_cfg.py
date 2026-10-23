#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Хост-тест APRS-unify (L5.4): tools/aprs_beacon_cfg.py -- блок бікона (16 Б), шумодав у блоці режиму (72 Б), позивний (EEPROM 0x00E0).

Блок бікона перевіряється ще й проти C-реалізації (tests/golden_aprs_beacon.txt не потрібен: байти порівнюються з тими, що будує прошивка у
tests/test_aprs_mode_state.c -- формат один: 'A','B',1 ... сума 0x5A). Без заліза: custom_data підміняється словником, запис кодплуга -- FakeRadioX.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cps_link as cl            # noqa: E402
import cps_csv as cc             # noqa: E402
import codeplug_view as cv       # noqa: E402
import custom_data as cd         # noqa: E402
import aprs_beacon_cfg as ab     # noqa: E402
import test_cps_csv as tc        # noqa: E402
import test_cps_restore as tr    # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def test_beacon_block():
    d = dict(ab.DEFAULT_BEACON)
    b = ab.beacon_build(d)
    check(len(b) == 16 and b[:3] == b"AB\x01", "магія/версія/довжина")
    check(b[6] == 0x0D, "типовий стан: канал + затухання + стиснення = 0x0D (=%02X)" % b[6])
    check(ab.beacon_parse(b) == d, "записали -> прочитали те саме")
    d2 = dict(d, mode=4, power=5, interval=7, source="gps", decay=False, compressed=False, slow=20, fast=90, low=3, high=80, angle=30, slope=40, time=50, bcnwin=2)
    b2 = ab.beacon_build(d2)
    check(b2[6] == 0x02 and ab.beacon_parse(b2) == d2, "GPS без затухання/стиснення: біти стану %02X" % b2[6])
    # сума: зерно 0x5A
    s = 0x5A
    for x in b[:15]:
        s = (s + x) & 0xFF
    check(b[15] == s, "контрольна сума")
    bad = bytearray(b); bad[5] ^= 1
    check(ab.beacon_parse(bytes(bad)) is None, "зіпсована сума -- відмова")
    check(ab.beacon_parse(b[:15]) is None and ab.beacon_parse(None) is None, "коротший/порожній")
    # поля поза межами прошивки -- блок ігнорується (як aprsBeaconCfgFromBytes)
    for idx, val in ((3, 5), (4, 16), (5, 10), (14, 3), (6, 0), (6, 3)):
        x = bytearray(b); x[idx] = val; x[15] = ab.sum8(x[:15])
        check(ab.beacon_parse(bytes(x)) is None, "байт %d = %d -- відмова" % (idx, val))
    for k, v in (("mode", 5), ("power", 16), ("interval", 10), ("slow", 0), ("fast", 9), ("low", 1), ("high", 91), ("angle", 4), ("slope", 0), ("time", 181), ("bcnwin", 3)):
        try:
            ab.beacon_build(dict(d, **{k: v}))
            check(False, "%s=%d мало бути відмовою" % (k, v))
        except ab.AprsCfgError:
            pass
    try:
        ab.beacon_build(dict(d, source="x"))
        check(False, "source=x")
    except ab.AprsCfgError:
        pass


def test_parse_set():
    d, sql = ab.parse_set(["mode=3", "interval=5", "source=gps", "decay=off", "sql=8"], ab.DEFAULT_BEACON)
    check(d["mode"] == 3 and d["interval"] == 5 and d["source"] == "gps" and d["decay"] is False and sql == 8, "ключ=значення: %r %r" % (d, sql))
    for bad in (["mode"], ["foo=1"], ["mode=x"], ["decay=maybe"]):
        try:
            ab.parse_set(bad, ab.DEFAULT_BEACON)
            check(False, "%r мало бути відмовою" % (bad,))
        except ab.AprsCfgError:
            pass


def test_sql_block():
    b = ab.mode_block_with_sql(None, 7)
    check(len(b) == 72 and b[:3] == b"AM\x01" and ab.mode_block_sql(b) == 7, "новий блок: шумодав 7")
    check(b[5] | (b[6] << 8) == 0x4000, "новий блок: лише маркер міграції (старих даних нема)")
    # існуючий блок: решта байтів не змінюється
    old = bytearray(b)
    old[10] = 0x55; old[71] = ab.sum8(old[:71])
    n = ab.mode_block_with_sql(bytes(old), 12)
    diff = [i for i in range(72) if n[i] != old[i]]
    check(diff == [4, 71] and ab.mode_block_sql(n) == 12, "змінено лише байт 4 і суму: %r" % diff)
    # недійсний блок -- створюється новий
    check(ab.mode_block_sql(ab.mode_block_with_sql(b"\x00" * 72, 3)) == 3, "недійсний блок замінено новим")
    try:
        ab.mode_block_with_sql(None, 22)
        check(False, "sql=22")
    except ab.AprsCfgError:
        pass
    check(ab.mode_block_sql(None) is None and ab.mode_block_sql(b"\xff" * 72) is None, "нема/стертий -- None")


def test_callsign():
    check(ab.callsign_encode("uw5elk") == b"UW5ELK\xff\xff", "позивний -> 8 байтів з 0xFF")
    check(ab.callsign_decode(b"UW5ELK\xff\xff") == "UW5ELK" and ab.callsign_decode(b"\xff" * 8) == "", "декодування")
    for bad in ("", "TOOLONG", "UW-5", "UW 5", "ПРИВІТ", None):
        try:
            ab.callsign_check(bad)
            check(False, "%r мав бути відмовою" % (bad,))
        except ab.AprsCfgError:
            pass


def test_callsign_flow():
    spi = tc.make_fixture_spi()
    cp, _data = tc.codeplug_of(spi)
    img = cc.Image.from_codeplug(cp)
    res = ab.apply_callsign(img, "r2abc")
    check(res.any_change() and bytes(res.image.ee(cl.CP_ADDR_USER_CALLSIGN, 8)) == b"R2ABC\xff\xff\xff", "образ: позивник у 0x00E0")
    check(bytes(img.ee(cl.CP_ADDR_USER_CALLSIGN, 8)) != b"R2ABC\xff\xff\xff", "вихідний образ не змінено")
    same = ab.apply_callsign(res.image, "R2ABC")
    check(not same.any_change(), "той самий позивний -- змін немає")
    with tempfile.TemporaryDirectory() as d:
        radio = tr.FakeRadioX(bytearray(spi))
        texts = []
        with tr.Unlocked():
            r = ab.callsign_to_radio(cl.CpsLink(radio, retries=0), "R2ABC", lambda t, p: texts.append(t) or True, log=lambda *_: None, out_dir=d)
        check(r["sectorsWritten"] >= 1 and radio.c_calls[-1] == bytes([6, 1]), "запис пройшов шляхом відновлення")
        check("ЗМІНА ПОЗИВНОГО" in texts[0] and "R2ABC" in texts[0], "діалог показує зміну")
        cp2, _ = cv.codeplug_from_radio(cl.CpsLink(tr.FakeRadioX(radio.spi), retries=0))
        check(bytes(cp2.eeprom[cl.CP_ADDR_USER_CALLSIGN:cl.CP_ADDR_USER_CALLSIGN + 8]) == b"R2ABC\xff\xff\xff", "у рації: позивний змінено")
        # скасування -- нічого не записано
        radio2 = tr.FakeRadioX(bytearray(spi))
        with tr.Unlocked():
            r2 = ab.callsign_to_radio(cl.CpsLink(radio2, retries=0), "R2ABC", lambda t, p: False, log=lambda *_: None, out_dir=d)
        check(r2.get("cancelled") and radio2.x_total == 0, "скасовано -- жодної X-команди")
        # поганий позивний -- до звернення до рації
        radio3 = tr.FakeRadioX(bytearray(spi))
        try:
            ab.callsign_to_radio(cl.CpsLink(radio3, retries=0), "bad-call", lambda t, p: True, log=lambda *_: None, out_dir=d)
            check(False, "поганий позивний")
        except ab.AprsCfgError:
            pass
        check(not radio3.requests if hasattr(radio3, "requests") else True, "поганий позивний -- рацію не чіпали")


def test_state_io():
    store = {}
    orig_r, orig_w = cd.read_block, cd.write_block
    cd.read_block = lambda ser, t, n: store.get(t)
    def _w(ser, t, p):
        store[t] = bytes(p)
        return True, "тест"
    cd.write_block = _w
    try:
        st = ab.read_state(None)
        check(st["beacon"] is None and st["sql"] is None, "порожня рація: блоків нема")
        out = ab.write_state(None, beacon=dict(ab.DEFAULT_BEACON, mode=3), sql=9)
        check(len(out) == 2 and all("OK" in x for x in out), "запис + звірка: %r" % out)
        st = ab.read_state(None)
        check(st["beacon"]["mode"] == 3 and st["sql"] == 9, "прочитали записане")
        check(len(store[ab.TYPE_APRS_BEACON_CFG]) == 16 and len(store[ab.TYPE_APRS_MODE_CFG]) == 72, "довжини блоків 16 і 72")
        out = ab.write_state(None, sql=0)
        check(ab.read_state(None)["sql"] == 0 and ab.read_state(None)["beacon"]["mode"] == 3, "шумодав окремо не чіпає бікон")
        check(ab.TYPE_APRS_MODE_CFG == 13 and ab.TYPE_APRS_BEACON_CFG == 14, "номери типів custom-data (codeplug.h)")
    finally:
        cd.read_block, cd.write_block = orig_r, orig_w


def test_gui():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("ПРОПУЩЕНО (GUI): нема tkinter")
        return
    if not os.environ.get("DISPLAY"):
        print("ПРОПУЩЕНО (GUI): нема DISPLAY")
        return
    import gui_flasher as gf
    app = gf.FlasherApp()
    try:
        w = gf.AprsBeaconWindow(app)
        w.update()
        d0 = dict(ab.DEFAULT_BEACON, mode=4, power=3, interval=6, source="gps", decay=False, compressed=True, slow=11, fast=33, low=4, high=66, angle=33, slope=44, time=55, bcnwin=1)
        w._apply_state({"call": "UW5ELK", "sql": 5, "beacon": d0})
        d, sql = w._collect()
        check(d == d0 and sql == 5, "вікно: стан -> поля -> стан: %r" % d)
        check(w.vars["call"].get() == "UW5ELK", "позивний у полі")
        w.vars["fast"].set("9")
        try:
            w._collect()
            check(False, "fast=9 мав дати відмову")
        except ab.AprsCfgError:
            pass
        w.destroy()
    finally:
        app.destroy()


def main():
    test_beacon_block()
    test_parse_set()
    test_sql_block()
    test_callsign()
    test_callsign_flow()
    test_state_io()
    test_gui()
    if FAILS:
        print("test_aprs_beacon_cfg: ПРОВАЛІВ %d" % len(FAILS))
        sys.exit(1)
    print("test_aprs_beacon_cfg: усе гаразд")


if __name__ == "__main__":
    main()
