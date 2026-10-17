#!/usr/bin/env python3
"""Read the AES-RX state-machine diagnostic ring from an OpenGD77-AES radio built
with DMR_AES_DIAG_RX. Runs over the USB CDC (CPS) port. NOT committed — bench tool
for diagnosing the rapid-re-PTT RX garble.

Firmware records, in the HR-C6000 ISR, a small CCM ring of decrypt events:
  PI      chip-LC PI parse (the MI the chip surfaced) + whether it (re)seeded
  IVGEN   first IV generated for a (re)seed (the MI the new call STARTS decrypting with)
  WRAP    superframe wrap: late-entry-decode MI (le=ok/fail) vs LFSR self-advance fallback
  LCRESET Voice-LC-Header new-call reset (dmrAesRxEnd)
  RXEND   CRC-valid Terminator (dmrAesRxEnd)
  LATENT  chip Late-Entry interrupt (reg 0x82 bit4) fired: slotState it fired in + whether
          OpenGD77's IDLE gate let it act (gate) and whether stale AES was still active (act)

Usage (Windows, the CDC enumerates as COM4):
  python rxdiag.py --reset            # clear the ring before a test run
  python rxdiag.py                    # dump + decode the ring
  python rxdiag.py --port COM4

AES-fix2: той самий дамп містить і ФАЗУ ПЕРЕДАЧІ (збірка DMR_AES_DIAG_RX=1): передай ~10 с, після передачі (CPS-режим
не потрібен) запусти `python rxdiag.py` -- рядки «TX-фаза» і «TX-зсув k». Скинути перед передачею: `python rxdiag.py --reset`.

AES-fix3: внизу того ж дампу -- блок «СИРІ LC/EMB»: сирі байти LC / EMB-кандидата, які віддав чип, і «наші» байти (PI, Voice LC, EMB SB).
Лише hex, без інтерпретації. Порівняти зі стоковою передачею -- TESTING.md, блок BP.
"""
import argparse, struct, sys, time
try:
    import serial
    from serial.tools import list_ports
except ImportError:   # розбір дампу (print_dump) працює і без pyserial -- на це спирається тест
    serial = None
    list_ports = None

AES_VID, AES_PID = 0x1FC9, 0x0094
TYPE = {1: "PI    ", 2: "WRAP  ", 3: "LCRSET", 4: "RXEND ", 5: "IVGEN ", 6: "BOOT  ", 7: "RESEED", 8: "LATENT"}
SLOTSTATE = {0: "IDLE", 1: "RX_1", 2: "RX_2", 3: "RX_END",
             4: "TXS1", 5: "TXS2", 6: "TXS3", 7: "TXS4", 8: "TXS5"}


def find_port():
    if list_ports is None:
        sys.exit("pyserial required: pip install pyserial")
    for p in list_ports.comports():
        if (p.vid == AES_VID) and (p.pid == AES_PID):
            return p.device
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    ap.add_argument("--reset", action="store_true", help="clear/arm the ring, then exit")
    args = ap.parse_args()

    if serial is None:
        sys.exit("pyserial required: pip install pyserial")
    port = args.port or find_port()
    if not port:
        sys.exit("no OpenGD77 CDC port found (1fc9:0094). Pass --port COMx")
    ser = serial.Serial(port, 115200, timeout=0.5)

    if args.reset:
        ser.reset_input_buffer()
        ser.write(bytes([ord("C"), 0x85])); ser.flush(); time.sleep(0.15)
        print("ring cleared:", ser.read(8))
        return

    ser.reset_input_buffer()
    ser.write(bytes([ord("C"), 0x84])); ser.flush(); time.sleep(0.25)
    r = ser.read(4096)
    if len(r) < 3 or r[0] != ord("C"):
        sys.exit("bad reply: %r" % r[:16])
    n = (r[1] << 8) | r[2]
    data = r[3:3 + n]
    if len(data) < 24 or data[0] != 0xA5:
        sys.exit("bad diag header (len=%d): %r" % (len(data), data[:8]))
    print_dump(data, port)


def hx(b):
    """Сирий hex через пробіл -- без жодної інтерпретації."""
    return " ".join("%02X" % x for x in b)


def print_fix3(data, start):
    """AES-fix3: сирі байти LC/EMB від чипа + «наші» байти. Лише hex, інтерпретації нема. Повертає False, якщо блоку нема."""
    f = data[start:]
    if len(f) < 48 or f[0] != 0xF3:
        print("AES-fix3: у дампі нема блоку сирих LC/EMB (стара збірка?)")
        return False
    rlcN, rlcSz, embN, embSz = f[1], f[2], f[3], f[4]
    total, = struct.unpack_from("<H", f, 5)
    rlcW, embW = f[7], f[8]
    lcSeen, lcDup, embReads, embDup = struct.unpack_from("<4H", f, 9)
    key, src, flg = f[17], f[18], f[19]
    mi, = struct.unpack_from("<I", f, 20)
    srcName = {1: "вибір TX-ключа", 2: "останній RX-ключ", 3: "за замовчуванням 1"}.get(src, "?")
    print("=" * 90)
    print(f"СИРІ LC/EMB (hex, без інтерпретації)   LC від чипа: усього CRC-валідних={lcSeen}, повторів не внесено={lcDup}   "
          f"EMB: читань={embReads}, повторів не внесено={embDup}")
    off = 48
    print(f"-- LC, який віддав чип (page 0x02:0x00..0x0B), від найстарішого; dT = rxDataType, sc = syncClass(0 hdr/EMB,1 voice,2 data,3 RC), PI = reg0x51 bit3, hits = повторів --")
    n = min(rlcW, rlcN)
    first = (rlcW - n) % rlcN if rlcW >= n else 0
    ring = f[off:off + rlcN * rlcSz]
    off += rlcN * rlcSz
    if n == 0:
        print("   (порожньо: CRC-валідного LC за цей час чип не віддавав)")
    for i in range(n):
        o = ((first + i) % rlcN) * rlcSz
        if o + rlcSz > len(ring):
            break
        dt, fl, hits = ring[o], ring[o + 1], ring[o + 2]
        ts, tsl = struct.unpack_from("<HH", ring, o + 4)
        print(f"   LC{i}: dT={dt:2d} sc={fl & 3} PI={(fl >> 2) & 1} hits={hits:3d} ts={ts:5d}..{tsl:5d}   {hx(ring[o + 8:o + 20])}")
    print("-- EMB-кандидат (page 0x02:0x29..0x2C як прочитано на прийомі; лише EMB-переривання і voice burst F) --")
    n = min(embW, embN)
    first = (embW - n) % embN if embW >= n else 0
    ering = f[off:off + embN * embSz]
    if n == 0:
        print("   (порожньо: за цей час EMB-кандидат не читався -- або чип на RX не віддає ці регістри)")
    for i in range(n):
        o = ((first + i) % embN) * embSz
        if o + embSz > len(ering):
            break
        dt, fl = ering[o], ering[o + 1]
        ts, = struct.unpack_from("<H", ering, o + 2)
        print(f"   EMB{i}: dT={dt:2d} sc={fl & 3} ts={ts:5d}   {hx(ering[o + 4:o + 8])}")
    print(f"-- НАШІ байти (побудовані тими самими функціями, що й TX; ключ={key} [{srcName}], MI={mi:08X} довільний, прапорці={flg}) --")
    print(f"   PI  (dmr_pi_build)         : {hx(f[24:31])}")
    print(f"   Voice LC (клон TX)         : {hx(f[31:43])}")
    print(f"   EMB SB  (dmr_emb_sb_build) : {hx(f[43:47])}")
    print("=" * 90)
    return True


def print_dump(data, port=""):
    ring = data[1]; rec = data[2]
    w = data[4] | (data[5] << 8)
    cnt = struct.unpack_from("<7H", data, 6)   # PI WRAP LCRESET RXEND IVGEN BOOTSTRAP RESEED
    leOk, leFail = struct.unpack_from("<2H", data, 20)
    lcReads, piValid, burstCalls = struct.unpack_from("<3H", data, 24)
    leInt = struct.unpack_from("<H", data, 30)[0] if len(data) >= 32 else 0
    body = data[32:32 + ring * rec]

    print(f"port {port}  ring={ring} rec={rec} writeIdx={w}")
    print(f"counts: PI={cnt[0]} WRAP={cnt[1]} LCRESET={cnt[2]} RXEND={cnt[3]} IVGEN={cnt[4]} "
          f"BOOTSTRAP={cnt[5]} RESEED={cnt[6]} LATEENTRY-int={leInt}   late-entry-decode: ok={leOk} fail={leFail}")
    print(f"        LC-reads={lcReads}  valid-PI={piValid}  RxBurst-calls={burstCalls}  "
          f"(non-PI LCs = {lcReads-piValid})")
    trl = data[3]
    tail = data[32 + ring * rec:32 + ring * rec + trl]
    if trl >= 7 and len(tail) >= 7:   # AES-fix1: хвіст після кільця
        tw, tm, tr = struct.unpack_from("<3H", tail, 0)
        fl = tail[6]
        print(f"resync MI: прийнято «двічі поспіль»={tw}  «пропущено один суперфрейм»={tm}  відхилено={tr}   "
              f"прапорці: PI-якір={fl & 1} конвенція={'ПОТОЧНИЙ' if fl & 2 else 'наступний'} підтверджена={(fl >> 2) & 1}")
    if trl >= 18 and len(tail) >= 18:   # AES-fix2: фаза ПЕРЕДАЧІ (B0/B2)
        silent, = struct.unpack_from("<H", tail, 8)
        firstSeq, firstBurst = tail[10], tail[11]
        bursts, encN, consumed = struct.unpack_from("<3H", tail, 12)
        print(f"TX-фаза: тихих burst-ів (SILENCE_AUDIO при активній шифрованій передачі)={silent}  "
              + ("перший: ЖОДНОГО" if firstSeq == 0xFF else f"перший на txSequence={firstSeq} (burst №{firstBurst} від початку голосу)")
              + f"  голосових burst-ів усього={bursts}  закодовано кадрів={encN}  пішло в ефір кадрів={consumed}")
        pairs = []
        for i in range((len(tail) - 18) // 2):
            pw, = struct.unpack_from("<H", tail, 18 + 2 * i)   # не `w`: це індекс запису кільця, його нижче читає цикл виводу
            if pw & 0x8000:
                pairs.append((i, (pw >> 8) & 0x7F, pw & 0xFF))
        if pairs:
            ks = [(pos - cnt) % 18 for _, cnt, pos in pairs]
            print("TX-фаза, кадр: (фаза шифрування -> позиція в ефірі, зсув k):  "
                  + "  ".join(f"{i}:{cnt}->{pos} k={(pos - cnt) % 18}" for i, cnt, pos in pairs))
            print("TX-зсув k: " + ", ".join(f"k={k}: {ks.count(k)} кадрів" for k in sorted(set(ks))) + "   (після фіксу всі k=0, крім <=2 кадрів у черзі на момент тихого burst)")
        else:
            print("TX-фаза: пар кадрів ще нема (передачі не було, або дамп знято до першого голосового burst)")
    print("-" * 90)
    print(" # |   ts   dT | type   | seq last | mi        leMi      | flags")
    print("-" * 90)

    nvalid = min(w, ring)
    start = (w - nvalid) % ring if w >= nvalid else 0
    prev_ts = None
    for i in range(nvalid):
        idx = (start + i) % ring
        o = idx * rec
        t = body[o]; fl = body[o + 1]; seq = body[o + 2]
        ls = body[o + 3] - 256 if body[o + 3] >= 128 else body[o + 3]
        ts = body[o + 4] | (body[o + 5] << 8)
        mi = struct.unpack_from("<I", body, o + 8)[0]
        aux = struct.unpack_from("<I", body, o + 12)[0]
        if t == 0:
            continue
        dt = "" if prev_ts is None else f"{(ts - prev_ts) & 0xFFFF:5d}"
        prev_ts = ts
        name = TYPE.get(t, f"?{t}")
        if t == 1:
            f = []
            if fl & 1: f.append("valid")
            f.append("SEEDED" if (fl & 2) else "no-seed")
            f.append("wasActive" if (fl & 4) else "wasIdle")
            fs = " ".join(f)
        elif t == 2:   # WRAP (active self-advance); AES-fix1: біти 5-6 = 3 -> розбіжне MI відхилено (лише запам'ятано)
            fs = ("LE-OK" if (fl & 1) else "LE-FAIL") + (" diverge" if (fl & 8) else "") + (" REJECTED(pending)" if ((fl >> 5) & 3) == 3 else "")
        elif t == 6:   # BOOTSTRAP (idle -> active from late entry)
            fs = ("LE-OK" if (fl & 1) else "LE-FAIL") + (" confirmed" if (fl & 8) else "") + (" ACTIVATED" if (fl & 0x10) else " (no-seed)")
        elif t == 7:   # RESEED (active track switch on diverging confirmed late entry)
            how = (fl >> 5) & 3   # AES-fix1: 1 «двічі поспіль», 2 «пропущено один суперфрейм», 0 = виклик без якоря PI
            fs = "SWITCHED-TRACK" + {0: " (late-entry call)", 1: " (twice in a row)", 2: " (missed one superframe)"}.get(how, "")
        elif t in (3, 4):
            fs = "wasActive" if (fl & 1) else "wasIdle"
        elif t == 8:   # LATEENTRY: chip late-entry interrupt fired. seq = slotState it fired in.
            st = SLOTSTATE.get(seq, f"st{seq}")
            fs = f"slot={st} " + ("GATE-OK(acted)" if (fl & 1) else "GATE-DROPPED") + (" stale-AES-active" if (fl & 2) else "")
        else:
            fs = ""
        print(f"{i:2d} | {ts:5d} {dt:>5} | {name} | {seq:3d} {ls:4d} | {mi:08X}  {aux:08X} | {fs}")
    print_fix3(data, 32 + ring * rec + trl)


if __name__ == "__main__":
    main()
