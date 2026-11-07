#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aprs_beacon_cfg.py -- APRS-unify (L5): налаштування бікона, шумодав приймача APRS і ПОЗИВНИЙ з ПК.

Одне джерело істини для кожного налаштування (див. STATUS.md, блок BT):
  * позивний                      -- ім'я рації в кодплазі, EEPROM 0x00E0 (8 байтів, дописка 0xFF). Пишеться шляхом відновлення з бекапу
                                     (як редактор контактів), бо CPS-запис «EEPROM» на STM32 -- порожня команда;
  * налаштування стокового бікона -- custom-data блок типу 14 (CODEPLUG_CUSTOM_DATA_TYPE_APRS_BEACON_CFG), 16 байтів, ОСНОВНЕ сховище:
                                     на старті прошивка переносить блок у nonVolatileSettings (aprsBeaconCfgBoot()), меню рації пише його назад;
  * шумодав приймача APRS         -- байт 4 блоку «Режиму APRS» (custom-data типу 13, 72 байти) + контрольна сума; решту блоку не чіпаємо;
  * станція (SSID, шляхи, символ, коментар, позиція, неточність, частота, 300 бод, QSY, «тихо») -- слот конфігу APRS (EEPROM 0x1588):
                                     це розділ APRS у cps_csv.py / «Імпорт CSV у рацію».

Формат блоку бікона (16 Б; дзеркалить aprs_mode_cfg.h, APRSB_BLOCK_LEN):
    0 'A' | 1 'B' | 2 версія=1 | 3 режим (0 вимкн., 1 вручну, 2 PTT, 3 авто, 4 розумний) | 4 потужність (0 -- канал; 1..15) |
    5 стоковий initialInterval (0..9 = 12 с, 30 с, 1, 2, 3, 5, 10, 20, 30, 60 хв) | 6 біти стану (bit0 позиція каналу, bit1 GPS -- рівно один;
    bit2 затухання, bit3 стиснення) | 7 slowRate (хв) | 8 fastRate (с) | 9 lowSpeed | 10 highSpeed (км/год) | 11 turnAngle (°) | 12 turnSlope |
    13 turnTime (с) | 14 вікно маяка (0 всі, 1 лише нові, 2 вимкн.) | 15 сума байтів 0..14 (зерно 0x5A).

Використання (рація ввімкнена ЗВИЧАЙНО, не в DFU):
  python3 aprs_beacon_cfg.py --show
  python3 aprs_beacon_cfg.py --set mode=3 --set interval=5 --set source=gps --set sql=8
  python3 aprs_beacon_cfg.py --callsign UW5ELK
"""
import argparse
import struct
import sys

TYPE_APRS_MODE_CFG = 13       # CODEPLUG_CUSTOM_DATA_TYPE_APRS_MODE_CFG (codeplug.h; 12-й -- SMS_TX_MODE)
TYPE_APRS_BEACON_CFG = 14     # CODEPLUG_CUSTOM_DATA_TYPE_APRS_BEACON_CFG
BEACON_LEN = 16
MODE_LEN = 72
SEED = 0x5A                   # APRSM_SUM_SEED
CALLSIGN_ADDR = 0x00E0        # CODEPLUG_ADDR_USER_CALLSIGN
CALLSIGN_LEN = 8
SQL_MAX = 21                  # APRSM_SQL_MAX: 0 -- типовий; 1..21 -- 0..100 % (як у каналі)
MODE_OV_MIGRATED = 0x4000     # APRSM_OV_MIGRATED

MODE_NAMES = ["Вимкнено", "Вручну", "PTT", "Авто", "Розумний"]
MODE_SMART, MODE_AUTO = 4, 3

# R69 B1: у рації НЕМА GPS-приймача (аналог FORK_NO_GPS_MENU в applicationMain.h). Один прапорець ховає в CPS «Джерело позиції», панель «Розумний маяк» і значення
# «Розумний» у «Режимі»; формат блока (16 Б), його читання й запис не змінюються -- значення полів зберігаються як прочитані. Для рації з GPS: FORK_NO_GPS = False.
FORK_NO_GPS = True
MODE_NAMES_UI = MODE_NAMES[:MODE_SMART] if FORK_NO_GPS else MODE_NAMES    # що показує список «Режим»
INITIAL_SECS = [12, 30, 60, 120, 180, 300, 600, 1200, 1800, 3600]       # initialIntervalsInSecs[]
BCNWIN_NAMES = ["Усі", "Лише нові", "Вимкнено"]

# (ключ, мін, макс) -- межі з aprs.h (APRS_SMART_BEACON_*)
RANGES = {
    "mode": (0, 4), "power": (0, 15), "interval": (0, 9), "bcnwin": (0, 2),
    "slow": (1, 100), "fast": (10, 180), "low": (2, 30), "high": (2, 90),
    "angle": (5, 90), "slope": (1, 255), "time": (5, 180), "sql": (0, SQL_MAX),
}

DEFAULT_BEACON = {
    "mode": 0, "power": 0, "interval": 2, "source": "channel", "decay": True, "compressed": True,
    "slow": 30, "fast": 120, "low": 5, "high": 70, "angle": 28, "slope": 26, "time": 60, "bcnwin": 0,
}


class AprsCfgError(ValueError):
    pass


def sum8(b):
    s = SEED
    for x in b:
        s = (s + x) & 0xFF
    return s


# ------------------------------------------------------------------------------------------------ блок бікона

def beacon_build(d):
    """dict (ключі DEFAULT_BEACON) -> 16 байтів. AprsCfgError -- значення поза межами."""
    for k in ("mode", "power", "interval", "bcnwin", "slow", "fast", "low", "high", "angle", "slope", "time"):
        lo, hi = RANGES[k]
        v = d[k]
        if not isinstance(v, int) or isinstance(v, bool) or v < lo or v > hi:
            raise AprsCfgError("%s: %r поза межами %d..%d" % (k, v, lo, hi))
    if d["source"] not in ("channel", "gps"):
        raise AprsCfgError("source: channel або gps, а не %r" % (d["source"],))
    state = (1 if d["source"] == "channel" else 2) | (4 if d["decay"] else 0) | (8 if d["compressed"] else 0)
    b = bytearray(BEACON_LEN)
    b[0:3] = b"AB\x01"
    b[3] = d["mode"]
    b[4] = d["power"]
    b[5] = d["interval"]
    b[6] = state
    b[7], b[8], b[9], b[10] = d["slow"], d["fast"], d["low"], d["high"]
    b[11], b[12], b[13] = d["angle"], d["slope"], d["time"]
    b[14] = d["bcnwin"]
    b[15] = sum8(b[:15])
    return bytes(b)


def no_gps_apply(d):
    """R69 B2: dict бікона -> копія, приведена до єдиного можливого стану рації без GPS (джерело «канал», «Розумний» -> «Авто»); решта полів, зокрема «затухання»
    й параметри розумного маяка, -- без змін. FORK_NO_GPS = False -- повертає копію як є. Те саме прошивка робить при завантаженні блока (cfgToSettings())."""
    r = dict(d)
    if FORK_NO_GPS:
        r["source"] = "channel"
        if r["mode"] == MODE_SMART:
            r["mode"] = MODE_AUTO
    return r


def beacon_parse(b):
    """16 байтів -> dict або None (довжина/магія/версія/сума/поля поза межами -- як у прошивці: блок ігнорується)."""
    if b is None or len(b) != BEACON_LEN or b[0:3] != b"AB\x01" or b[15] != sum8(b[:15]):
        return None
    if b[3] > 4 or b[4] > 15 or b[5] > 9 or b[14] > 2 or (b[6] & 3) not in (1, 2):
        return None
    return {
        "mode": b[3], "power": b[4], "interval": b[5], "source": "channel" if (b[6] & 1) else "gps",
        "decay": bool(b[6] & 4), "compressed": bool(b[6] & 8),
        "slow": b[7], "fast": b[8], "low": b[9], "high": b[10], "angle": b[11], "slope": b[12], "time": b[13], "bcnwin": b[14],
    }


# ------------------------------------------------------------------------------------------------ шумодав у блоці режиму

def mode_block_sql(b):
    """Шумодав із блоку режиму (72 Б) або None, якщо блок недійсний."""
    if b is None or len(b) != MODE_LEN or b[0:2] != b"AM" or b[2] != 1 or b[71] != sum8(b[:71]):
        return None
    return b[4] if b[4] <= SQL_MAX else 0


def mode_block_with_sql(b, sql):
    """Блок режиму з новим шумодавом. b -- наявний (дійсний) блок або None/недійсний: тоді створюється новий порожній --
    без оверрайдів, із маркером міграції (старих даних нема, мігрувати нічого). Решта байтів наявного блоку не змінюється."""
    if not isinstance(sql, int) or isinstance(sql, bool) or sql < 0 or sql > SQL_MAX:
        raise AprsCfgError("sql: 0..%d" % SQL_MAX)
    if mode_block_sql(b) is None:
        n = bytearray(MODE_LEN)
        n[0:3] = b"AM\x01"
        n[5:7] = struct.pack("<H", MODE_OV_MIGRATED)
    else:
        n = bytearray(b)
    n[4] = sql
    n[71] = sum8(n[:71])
    return bytes(n)


# ------------------------------------------------------------------------------------------------ позивний

def callsign_check(text):
    """Нормалізований позивний (A-Z 0-9, 1..6 символів, верхній регістр). AprsCfgError -- не підходить."""
    t = (text or "").strip().upper()
    if not (1 <= len(t) <= 6) or not all(("A" <= c <= "Z") or ("0" <= c <= "9") for c in t):
        raise AprsCfgError("позивний: 1..6 символів A-Z, 0-9 (без SSID й пробілів)")
    return t


def callsign_encode(text):
    """Байти імені рації для EEPROM 0x00E0: ASCII + дописка 0xFF до 8."""
    t = callsign_check(text)
    return t.encode("ascii") + b"\xff" * (CALLSIGN_LEN - len(t))


def callsign_decode(b):
    raw = bytes(b[:CALLSIGN_LEN])
    out = []
    for x in raw:
        if x in (0x00, 0xFF) or x == 0x20:
            break
        out.append(chr(x) if 0x21 <= x < 0x7F else "?")
    return "".join(out)


def apply_callsign(base_img, text):
    """Накласти позивний на образ кодплага (cps_csv.Image). Повертає cps_csv.ImportResult (як у contact_edit.apply_ops)."""
    import cps_csv as cc
    img = cc.Image(base_img.eeprom, base_img.flash, base_img.base)
    res = cc.ImportResult()
    new = callsign_encode(text)
    old = img.ee(CALLSIGN_ADDR, CALLSIGN_LEN)
    if old != new:
        img.set_ee(CALLSIGN_ADDR, new)
        res.changed.append(("Позивний", "%s -> %s" % (callsign_decode(old) or "(порожньо)", callsign_check(text))))
    res.image = img
    return res


CALLSIGN_TITLE = "ЗМІНА ПОЗИВНОГО -- рація буде ПЕРЕЗАПИСАНА."


def callsign_to_radio(link, text, confirm, progress=None, log=print, out_dir=".", now=None, clock=None, post_reset=True):
    """Прочитати поточний кодплаг рації, змінити позивний, записати шляхом відновлення з бекапу (страхова копія, підтвердження, перевірка)."""
    import time as _t
    import codeplug_view as cv
    import cps_csv as cc
    clock = clock or _t.time
    callsign_check(text)

    def prog(pct, t):
        if progress:
            progress(max(0, min(100, int(pct))), t)

    prog(0, "Читаю поточний кодплаг рації...")
    cp, _m = cv.codeplug_from_radio(link, lambda p, t: prog(p * 0.25, t))
    res = apply_callsign(cc.Image.from_codeplug(cp), text)
    if not res.any_change():
        prog(100, "Позивний уже такий")
        return {"cancelled": False, "nothingToDo": True, "sectorsWritten": 0, "report": res}
    return cc.write_image_via_restore(link, res, confirm, progress=lambda p, t: prog(27 + p * 0.73, t), log=log, now=now, clock=clock,
                                      post_reset=post_reset, title=CALLSIGN_TITLE, out_dir=out_dir, zip_prefix="codeplug_callsign",
                                      note="Образ після зміни позивного поверх поточного стану рації. Це те, що буде записано.")


# ------------------------------------------------------------------------------------------------ рація (custom-data)

def read_state(ser):
    """-> {"beacon": dict|None (блока нема/недійсний), "sql": int|None, "beaconRaw": bytes|None, "modeRaw": bytes|None}"""
    import custom_data as cd
    braw = cd.read_block(ser, TYPE_APRS_BEACON_CFG, BEACON_LEN)
    mraw = cd.read_block(ser, TYPE_APRS_MODE_CFG, MODE_LEN)
    return {"beacon": beacon_parse(braw), "sql": mode_block_sql(mraw), "beaconRaw": braw, "modeRaw": mraw}


def write_state(ser, beacon=None, sql=None):
    """Записати блок бікона і/або шумодав (кожен -- лише якщо передано). Повертає список текстових підсумків; AprsCfgError -- збій запису."""
    import custom_data as cd
    out = []
    if beacon is not None:
        payload = beacon_build(beacon)
        ok, msg = cd.write_block(ser, TYPE_APRS_BEACON_CFG, payload)
        if not ok:
            raise AprsCfgError("блок бікона: " + msg)
        rb = cd.read_block(ser, TYPE_APRS_BEACON_CFG, BEACON_LEN)
        out.append("Блок бікона записано (%s). Звірка читанням: %s." % (msg, "OK" if rb == payload else "НЕЗБІГ"))
    if sql is not None:
        cur = cd.read_block(ser, TYPE_APRS_MODE_CFG, MODE_LEN)
        payload = mode_block_with_sql(cur, sql)
        ok, msg = cd.write_block(ser, TYPE_APRS_MODE_CFG, payload)
        if not ok:
            raise AprsCfgError("блок режиму (шумодав): " + msg)
        rb = cd.read_block(ser, TYPE_APRS_MODE_CFG, MODE_LEN)
        out.append("Шумодав приймача APRS = %d записано (%s). Звірка читанням: %s." % (sql, msg, "OK" if rb == payload else "НЕЗБІГ"))
    return out


def describe(d):
    if d is None:
        return "блока бікона нема (рація візьме поточні стокові налаштування й створить його сама)"
    return ("режим=%s, потужність=%s, інтервал=%d с (індекс %d), позиція=%s, затухання=%s, стиснення=%s, розумний: slow=%d хв fast=%d с low=%d high=%d кут=%d нахил=%d час=%d с, вікно=%s" % (
        MODE_NAMES[d["mode"]], "канал" if d["power"] == 0 else d["power"], INITIAL_SECS[d["interval"]], d["interval"],
        "канал" if d["source"] == "channel" else "GPS", "так" if d["decay"] else "ні", "так" if d["compressed"] else "ні",
        d["slow"], d["fast"], d["low"], d["high"], d["angle"], d["slope"], d["time"], BCNWIN_NAMES[d["bcnwin"]]))


def parse_set(items, base):
    """['mode=3', 'source=gps', 'decay=on', 'sql=8'] -> (dict бікона, sql|None). base -- dict відправної точки."""
    d = dict(base)
    sql = None
    for it in items:
        if "=" not in it:
            raise AprsCfgError("очікується ключ=значення, а не %r" % it)
        k, v = [x.strip().lower() for x in it.split("=", 1)]
        if k == "sql":
            sql = _int(k, v)
        elif k == "source":
            d["source"] = v
        elif k in ("decay", "compressed"):
            if v not in ("on", "off", "1", "0", "yes", "no", "так", "ні"):
                raise AprsCfgError("%s: on/off" % k)
            d[k] = v in ("on", "1", "yes", "так")
        elif k in RANGES:
            d[k] = _int(k, v)
        else:
            raise AprsCfgError("невідомий ключ %r (є: mode power interval source decay compressed slow fast low high angle slope time bcnwin sql)" % k)
    return d, sql


def _int(k, v):
    try:
        return int(v)
    except ValueError:
        raise AprsCfgError("%s: ціле число, а не %r" % (k, v))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true", help="прочитати поточний стан")
    ap.add_argument("--set", action="append", default=[], metavar="КЛЮЧ=ЗНАЧЕННЯ", help="змінити поле бікона або sql (можна кілька разів)")
    ap.add_argument("--callsign", default=None, help="новий позивний (запис кодплага шляхом відновлення з бекапу, з підтвердженням)")
    ap.add_argument("--port", default=None)
    a = ap.parse_args(argv)

    try:
        if a.callsign is not None:
            callsign_check(a.callsign)
        parse_set(a.set, DEFAULT_BEACON)   # лише перевірка синтаксису до звернення до рації
    except AprsCfgError as e:
        sys.exit("помилка: %s" % e)
    import cps_link as cl
    ser = cl.open_radio(a.port)
    try:
        link = cl.CpsLink(ser)
        st = read_state(ser)
        call = callsign_decode(link.read(cl.CPS_ACCESS_EEPROM, CALLSIGN_ADDR, CALLSIGN_LEN))
        print("позивний:", call or "(не заданий)")
        print("шумодав приймача APRS:", "блока нема (типовий)" if st["sql"] is None else st["sql"])
        print("бікон:", describe(st["beacon"]))
        if a.set:
            base = st["beacon"] or DEFAULT_BEACON
            d, sql = parse_set(a.set, base)
            beacon_keys = [x.split('=')[0].strip().lower() for x in a.set]
            changed_beacon = (d != base) or (st["beacon"] is None and any(k != "sql" for k in beacon_keys))
            for line in write_state(ser, beacon=d if changed_beacon else None, sql=sql):
                print(line)
            print("Нове значення рація підхопить після перезапуску (зміни бікона діють з наступного старту).")
        if a.callsign is not None:
            def confirm(text, _plan):
                print(text)
                return input("Записати в рацію? [y/N] ").strip().lower() == "y"
            res = callsign_to_radio(link, a.callsign, confirm, progress=lambda p, t: print("%3d%% %s" % (p, t)))
            print("Скасовано." if res.get("cancelled") else ("Позивний уже такий." if res.get("nothingToDo") else "Позивний записано."))
    finally:
        try:
            ser.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
