#!/usr/bin/env python3
"""
wake_diag.py -- R58: прочитати з рації журнал сеансів пробудження ретранслятора (USB CPS, опкод 0xB7).

Працює лише з ДІАГНОСТИЧНОЮ збіркою (CI-джоб build-ukrainian-wake-diag, ENABLE_WAKE_DIAG=1).
Звичайна прошивка відповість "-" на невідомий опкод.

    python3 MDUV380_firmware/tools/wake_diag.py            # прочитати й надрукувати (таблиця + CSV-файл у ~/)
    python3 MDUV380_firmware/tools/wake_diag.py --reset    # скинути журнал на рації
    python3 MDUV380_firmware/tools/wake_diag.py --selftest # перевірка розбору на синтетичному дампі (без рації)

Формат відповіді (див. wakeDiagDump() у wake_diag.c і case 0xB7 у usb_com.c):
    'C', len_hi, len_lo, ver, макс.сеансів, кількість, 0, directTx u16, 0 u16, далі кількість x запис по 52 Б (LE),
    найновіший першим. Запис: rx u32, tx u32, chan u16, cc u8, flags u8, to0 u16, tAwaken u16, tTx u16, tFail u16,
    hopT u16, hopChan u16, pkts u8, zeros u8, maxToggle u8, intTmo u8, pktT[6] u16, zeroT[6] u16.
    Часи -- мс від початку сеансу; 0xFFFF -- «події не було».
"""
import os
import struct
import sys
import time

APP_VID, APP_PID = 0x1FC9, 0x0094
OPCODE = 0xB7
NONE = 0xFFFF
HDR = 8
REC = 52
PKT_MAX = 6
ZERO_MAX = 6
PREV = {0: "-", 1: "ok", 2: "fail", 3: "cncl"}
FLAG_HOP_START = 0x04

REC_FMT = "<IIHBBHHHHHHBBBB%dH%dH" % (PKT_MAX, ZERO_MAX)


def decode(body):
    """Розібрати тіло відповіді (після 'C', len_hi, len_lo) -> (directTx, [сеанс dict, найновіший першим])."""
    if len(body) < HDR:
        raise ValueError("відповідь коротша за заголовок (%d Б)" % len(body))
    ver, maxs, count, _zero, direct, _res = struct.unpack_from("<BBBBHH", body, 0)
    if ver != 1:
        raise ValueError("невідома версія формату %d (очікувалась 1)" % ver)
    need = HDR + count * REC
    if len(body) < need:
        raise ValueError("обірваний дамп: %d сеансів потребують %d Б, є %d" % (count, need, len(body)))
    out = []
    for i in range(count):
        f = struct.unpack_from(REC_FMT, body, HDR + i * REC)
        s = dict(rx=f[0], tx=f[1], chan=f[2], cc=f[3], flags=f[4], to0=f[5], tAwaken=f[6], tTx=f[7],
                 tFail=f[8], hopT=f[9], hopChan=f[10], pkts=f[11], zeros=f[12], maxToggle=f[13], intTmo=f[14],
                 pktT=list(f[15:15 + PKT_MAX]), zeroT=list(f[15 + PKT_MAX:15 + PKT_MAX + ZERO_MAX]))
        out.append(s)
    return direct, out


def t(v):
    return "-" if v == NONE else str(v)


def mhz(f):
    return "%d.%04d" % (f // 100000, (f % 100000) // 10)


def outcome(s):
    if s["tAwaken"] != NONE:
        return "AWAKEN" + (" TX" if s["tTx"] != NONE else "")
    if s["tFail"] != NONE:
        return "FAILED"
    return "обірвано/триває"


def render(direct, sessions):
    lines = ["Сеансів: %d, передач без пробудження (directTx): %d" % (len(sessions), direct), ""]
    lines.append("%3s %5s %-9s %2s %5s %-5s %-4s %-3s %-7s %-7s %-7s %-7s %s" % (
        "вік", "канал", "RX МГц", "CC", "to0", "поп", "стр", "пак", "Awaken", "Tx", "Fail", "нулі", "результат"))
    for age, s in enumerate(sessions):
        zeros = ",".join(t(v) for v in s["zeroT"][:min(s["zeros"], ZERO_MAX)]) or "-"
        lines.append("%3d %5d %-9s %2d %5d %-5s %-4s %-3d %-7s %-7s %-7s %-7s %s" % (
            age, s["chan"], mhz(s["rx"]), s["cc"], s["to0"], PREV[s["flags"] & 3],
            "так" if s["flags"] & FLAG_HOP_START else "ні", s["pkts"], t(s["tAwaken"]), t(s["tTx"]), t(s["tFail"]),
            zeros, outcome(s)))
        pk = ",".join(t(v) for v in s["pktT"][:min(s["pkts"], PKT_MAX)]) or "-"
        extra = "     пакети(мс): %s  toggle=%d intTmo=%d" % (pk, s["maxToggle"], s["intTmo"])
        if s["hopT"] != NONE:
            extra += "  СТРИБОК через %s мс -> канал %d" % (t(s["hopT"]), s["hopChan"])
        lines.append(extra)
    return "\n".join(lines)


def to_csv(direct, sessions):
    cols = ["age", "chan", "rx", "tx", "cc", "flags", "to0", "tAwaken", "tTx", "tFail", "hopT", "hopChan",
            "pkts", "zeros", "maxToggle", "intTmo"] + ["pkt%d" % i for i in range(PKT_MAX)] + ["zero%d" % i for i in range(ZERO_MAX)]
    rows = [",".join(cols)]
    for age, s in enumerate(sessions):
        vals = [age, s["chan"], s["rx"], s["tx"], s["cc"], s["flags"], s["to0"], s["tAwaken"], s["tTx"], s["tFail"],
                s["hopT"], s["hopChan"], s["pkts"], s["zeros"], s["maxToggle"], s["intTmo"]] + s["pktT"] + s["zeroT"]
        rows.append(",".join(str(v) for v in vals))
    return "\n".join(rows) + "\n"


def find_port():
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.vid == APP_VID and p.pid == APP_PID:
            return p.device
    return None


def read_exact(ser, n, timeout=2.0):
    out = b""
    t0 = time.time()
    while len(out) < n and (time.time() - t0) < timeout:
        out += ser.read(n - len(out))
    return out


def request(ser, flags):
    ser.write(bytes([ord("C"), OPCODE, flags]))
    ser.flush()
    first = read_exact(ser, 1)
    if not first:
        raise RuntimeError("рація не відповідає (кабель? режим CPS?)")
    if first == b"-":
        raise RuntimeError("рація не знає опкоду 0xB7 -- потрібна діагностична збірка пробудження (ENABLE_WAKE_DIAG)")
    if first != b"C":
        raise RuntimeError("несподівана відповідь: %s" % (first + ser.read(64)).hex())
    if flags & 1:
        return b""
    ln = read_exact(ser, 2)
    if len(ln) < 2:
        raise RuntimeError("обірвана відповідь (довжина)")
    n = (ln[0] << 8) | ln[1]
    body = read_exact(ser, n)
    if len(body) < n:
        raise RuntimeError("обірвана відповідь: очікувалось %d Б, прийшло %d" % (n, len(body)))
    return body


def selftest():
    def rec(**k):
        d = dict(rx=43012500, tx=43000000, chan=5, cc=1, flags=0, to0=0, tAwaken=NONE, tTx=NONE, tFail=NONE,
                 hopT=NONE, hopChan=0, pkts=0, zeros=0, maxToggle=0, intTmo=0,
                 pktT=[NONE] * PKT_MAX, zeroT=[NONE] * ZERO_MAX)
        d.update(k)
        return struct.pack(REC_FMT, d["rx"], d["tx"], d["chan"], d["cc"], d["flags"], d["to0"], d["tAwaken"], d["tTx"],
                           d["tFail"], d["hopT"], d["hopChan"], d["pkts"], d["zeros"], d["maxToggle"], d["intTmo"],
                           *d["pktT"], *d["zeroT"])

    assert struct.calcsize(REC_FMT) == REC, struct.calcsize(REC_FMT)
    a = rec(chan=7, tAwaken=1100, tTx=1400, pkts=2, pktT=[0, 60] + [NONE] * 4, to0=0)
    b = rec(chan=8, flags=2 | FLAG_HOP_START, to0=600, tFail=1800, zeros=3, zeroT=[600, 1200, 1800] + [NONE] * 3,
            hopT=1810, hopChan=9)
    body = struct.pack("<BBBBHH", 1, 12, 2, 0, 3, 0) + a + b
    direct, ses = decode(body)
    assert direct == 3 and len(ses) == 2
    assert ses[0]["chan"] == 7 and ses[0]["tAwaken"] == 1100 and ses[0]["pktT"][:2] == [0, 60]
    assert ses[1]["tFail"] == 1800 and ses[1]["hopChan"] == 9 and ses[1]["zeroT"][2] == 1800
    text = render(direct, ses)
    assert "AWAKEN TX" in text and "FAILED" in text and "СТРИБОК через 1810 мс -> канал 9" in text, text
    assert "430.1250" in text, text
    csv = to_csv(direct, ses)
    assert csv.count("\n") == 3 and csv.splitlines()[0].startswith("age,chan"), csv
    for bad, why in ((body[:5], "коротший за заголовок"), (body[:-1], "обірваний"),
                     (struct.pack("<BBBBHH", 2, 12, 0, 0, 0, 0), "версія")):
        try:
            decode(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("очікувався ValueError: " + why)
    assert decode(struct.pack("<BBBBHH", 1, 12, 0, 0, 0, 0)) == (0, [])
    print("wake_diag selftest: ок")


def main():
    if "--selftest" in sys.argv:
        selftest()
        return 0
    import serial
    port = find_port()
    if not port:
        print("рацію не знайдено (USB 1FC9:0094)")
        return 1
    ser = serial.Serial(port, 115200, timeout=0.5)
    try:
        if "--reset" in sys.argv:
            request(ser, 1)
            print("журнал скинуто")
            return 0
        direct, ses = decode(request(ser, 0))
    except (RuntimeError, ValueError) as e:
        print("помилка: %s" % e)
        return 1
    print(render(direct, ses))
    path = os.path.expanduser("~/wake_diag_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_csv(direct, ses))
    print("\nCSV: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
