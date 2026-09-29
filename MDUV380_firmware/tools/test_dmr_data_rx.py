#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Самоперевірка tools/dmr_data_rx.py без ефірних записів (їх у репозиторії немає).

  1. Golay(20,8): опорні значення, мінімальна відстань 8, виправлення до 3 помилок.
  2. BPTC(196,96): кодер -> декодер, з 1 помилкою.
  3. Треліс 3/4 (ETSI §B.3.7): encode -> decode == вихідні 18 байт на випадкових даних,
     і з однією бітовою помилкою в burst-і.
  4. CRC9 rate-3/4 -- ті самі вектори, що в tests/test_dmr_sms_confirmed.c (прошивка).
  5. Синтетичний запис 4FSK (48 кГц): CSBK, CONFIRMED-заголовок, rate-3/4 блок,
     квитанція 01 40 (BBD_0000) і burst із невалідним CRC -- розбір analyze() має знайти
     все, правильно назвати типи, адреси, CRC ok/bad.

ВАЖЛИВО: кодер і декодер тут з одних і тих самих таблиць, тож п.3 доводить лише узгодженість
між ними. Що таблиці B.7-B.9 збігаються з ефіром, покаже справжній запис: у блоків стокової
має бути «CRC9 ok» (випадково CRC9 сходиться з імовірністю 1/512).

Запуск:  python3 MDUV380_firmware/tools/test_dmr_data_rx.py   (потрібні numpy, scipy)
"""
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dmr_data_rx as D  # noqa: E402

fails = 0


def check(cond, what):
    global fails
    if cond:
        print("  ok   " + what)
    else:
        fails += 1
        print("  FAIL " + what)


def crc16_hdr(data10, mask):
    """CRC заголовка як у прошивці: crc16_ccitt (без ^FFFF) ^ (mask ^ 0xFFFF)."""
    c = D.crc16_ccitt(data10) ^ (mask ^ 0xFFFF)
    return bytes(data10) + bytes([c >> 8, c & 0xFF])


def t_golay():
    # опорні точки (паритет 12 біт) -- див. коментар у dmr_data_rx.py
    ref = {1: 0x8EB, 2: 0x93E, 3: 0x1D5, 4: 0xA97, 8: 0xDC6, 9: 0x52D}
    check(all(D.golay2087_parity(d) == p for d, p in ref.items()), "Golay(20,8): опорні паритети")
    dmin = min(bin(D.golay2087_encode(d)).count('1') for d in range(1, 256))
    check(dmin == 8, "Golay(20,8): мінімальна відстань %d" % dmin)
    rnd = random.Random(1)
    ok = True
    for d in range(256):
        w = D.golay2087_encode(d)
        for b in rnd.sample(range(20), 3):
            w ^= 1 << b
        dd, e = D.golay2087_decode(w)
        ok = ok and (dd == d and e == 3)
    check(ok, "Golay(20,8): 3 помилки виправляються для всіх 256 слів")


def t_bptc():
    rnd = random.Random(2)
    ok = True
    for _ in range(50):
        data = bytes(rnd.randrange(256) for _ in range(12))
        enc = D.bptc_encode(data)
        ok = ok and D.bits_to_bytes(D.bptc_196_96(enc)) == data
        enc[rnd.randrange(196)] ^= 1
        ok = ok and D.bits_to_bytes(D.bptc_196_96(enc)) == data
    check(ok, "BPTC(196,96): encode->decode, і з 1 помилкою (50 випадкових)")


def t_trellis():
    rnd = random.Random(3)
    ok, ok1, n1 = True, 0, 200
    for _ in range(200):
        data = bytes(rnd.randrange(256) for _ in range(18))
        enc = D.trellis34_encode(data)
        dec, err = D.trellis34_decode(enc)
        ok = ok and dec == data and err == 0 and len(enc) == 196
        enc[rnd.randrange(196)] ^= 1
        dec1, _ = D.trellis34_decode(enc)
        ok1 += (dec1 == data)
    check(ok, "треліс 3/4: encode->decode == 18 байт (200 випадкових), 196 біт, 0 розбіжностей")
    check(ok1 == n1, "треліс 3/4: 1 бітова помилка виправлена в %d/%d" % (ok1, n1))


def t_crc9():
    z = bytes(16); seq = bytes(range(1, 17)); ff = bytes([0xFF] * 16)
    vec = [(z, 0, 0x000), (z, 1, 0x059), (z, 2, 0x0B2), (seq, 0, 0x092), (ff, 0, 0x03C), (ff, 3, 0x0D7)]
    check(all(D.crc9_r34(p, d) == c for p, d, c in vec), "CRC9 rate-3/4 == вектори прошивки (test_dmr_sms_confirmed.c)")
    b = D.pack_block_r34(seq, 5)
    okb, dbsn, pl = D.check_block_r34(b)
    bad = bytearray(b); bad[7] ^= 0x10
    check(okb and dbsn == 5 and pl == seq and not D.check_block_r34(bytes(bad))[0],
          "rate-3/4 блок: pack -> check ok, псування -> bad")


# ---------------------------------------------------------------- синтетика
FS = 48000
SPB = int(FS / D.BAUD)          # 10 відліків на символ


def make_burst(info196, dt, cc=1, sync='BS_DATA'):
    slot = [(D.golay2087_encode((cc << 4) | dt) >> (19 - i)) & 1 for i in range(20)]
    return list(info196[:98]) + slot[:10] + D.SYNCB[sync] + slot[10:] + list(info196[98:])


def modulate(bursts, period=0.060, lead=0.05, noise=0.01, seed=4):
    rnd = np.random.default_rng(seed)
    total = int((lead * 2 + period * len(bursts)) * FS)
    freq = np.zeros(total)
    amp = np.zeros(total)
    for k, b in enumerate(bursts):
        start = int((lead + k * period) * FS)
        for i in range(0, 264, 2):
            sym = D._BITS2SYM[(b[i], b[i + 1])]
            s = start + (i // 2) * SPB
            freq[s:s + SPB] = sym * 648.0
            amp[s:s + SPB] = 1.0
    phase = 2 * np.pi * np.cumsum(freq) / FS
    iq = amp * np.exp(1j * phase)
    iq = iq + noise * (rnd.standard_normal(total) + 1j * rnd.standard_normal(total))
    return iq


def t_synthetic():
    dst, src = 0x26EA29, 0x26EA0F
    csbk = crc16_hdr(bytes([0xBD, 0x00, 0x80, 0x03]) + dst.to_bytes(3, 'big') + src.to_bytes(3, 'big'), 0xA5A5)
    hdr = crc16_hdr(bytes([0x43, 0x4E]) + dst.to_bytes(3, 'big') + src.to_bytes(3, 'big') + bytes([0x84, 0x88]), 0xCCCC)
    blk = D.pack_block_r34(bytes(range(0x30, 0x40)), 0)
    ack = bytes.fromhex('014026ea0f26ea290008668d')          # квитанція стокової з BBD_0000
    junk = bytearray(crc16_hdr(bytes(range(10)), 0xCCCC)); junk[11] ^= 0xFF   # CRC зіпсовано
    bursts = [make_burst(D.bptc_encode(csbk), 3),
              make_burst(D.bptc_encode(hdr), 6),
              make_burst(D.trellis34_encode(blk), 8),
              make_burst(D.bptc_encode(bytes(junk)), 6),
              make_burst(D.bptc_encode(ack), 6)]
    iq = modulate(bursts)
    res = D.analyze(iq, FS, sync_tol=4, frac=0.06)
    for r in res:
        print("       " + D.format_burst(r))
    check(len(res) == 5, "синтетика: знайдено %d burst-ів із 5" % len(res))
    if len(res) != 5:
        return
    r0, r1, r2, r3, r4 = res
    check(r0['dt'] == 3 and r0['crc'] == 'CRC ok' and r0['a1'] == dst and r0['a2'] == src,
          "CSBK: тип 3, CRC ok, a1/a2 з байтів [4:7]/[7:10]")
    check(r1['dt'] == 6 and r1['crc'] == 'CRC ok' and r1['a1'] == dst and r1['a2'] == src
          and 'CONFIRMED' in r1['extra'] and 'N(S)=0 S=1' in r1['extra'],
          "заголовок 43..: тип 6, CRC ok, a1/a2 з [2:5]/[5:8], CONFIRMED N(S)=0 S=1")
    check(r2['dt'] == 8 and r2['crc'] == 'CRC9 ok' and r2['bytes'] == blk and 'DBSN=0' in r2['extra'],
          "rate-3/4: тип 8, 18 байт збігаються, DBSN=0, CRC9 ok")
    check(r3['dt'] == 6 and r3['crc'] == 'CRC bad', "burst із зіпсованим CRC надруковано як «CRC bad»")
    check(r4['dt'] == 6 and r4['crc'] == 'CRC ok' and 'Response o9=08' in r4['extra']
          and r4['a1'] == src and r4['a2'] == dst, "квитанція 01 40 (BBD_0000): Response, o9=08, адреси")
    times = [round(r['t'] - res[0]['t'], 3) for r in res]
    check(all(abs(tt - 0.060 * k) < 0.003 for k, tt in enumerate(times)), "час burst-ів з кроком 60 мс: %s" % times)


def t_threshold():
    # Лише шум + один слабкий burst: при frac=0.001 поріг тримає 4x медіана, а не шум.
    iq = modulate([make_burst(D.bptc_encode(bytes(12)), 3)], lead=0.3, noise=0.05)
    regs, pk, thr = D.find_bursts(iq, FS, frac=0.001)
    check(len(regs) == 1, "поріг max(frac*пік, 4*медіана): при frac=0.001 регіонів %d (очік. 1)" % len(regs))


def t_robust():
    # Зсув несучої (HackRF не точно на частоті) і шум: rate-3/4 + квитанція мають розбиратись.
    blk = D.pack_block_r34(bytes(range(16)), 3)
    bs = [make_burst(D.trellis34_encode(blk), 8),
          make_burst(D.bptc_encode(bytes.fromhex('014026ea0f26ea290008668d')), 6)]
    ok = True
    for off, noise in [(800, 0.05), (-1500, 0.1), (0, 0.2)]:
        iq = modulate(bs, noise=noise)
        iq = iq * np.exp(2j * np.pi * off * np.arange(iq.size) / FS)
        res = D.analyze(iq, FS)
        ok = ok and [(r['dt'], r['crc']) for r in res] == [(8, 'CRC9 ok'), (6, 'CRC ok')]
    check(ok, "зсув несучої +800/-1500 Гц і шум до 0.2: rate-3/4 і квитанція розібрані")


if __name__ == "__main__":
    print("test_dmr_data_rx:")
    t_golay(); t_bptc(); t_trellis(); t_crc9(); t_synthetic(); t_threshold(); t_robust()
    print("ПРОВАЛ (%d)" % fails if fails else "ПРОЙДЕНО")
    sys.exit(1 if fails else 0)
