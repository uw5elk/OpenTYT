#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Еталонний кадр APRS для хост-тесту tests/test_aprs_afsk.c (R3) і його FCS.

FCS рахується тут НЕЗАЛЕЖНО від C-коду: не відзеркаленим поліномом 0x1021 (CRC-CCITT
у «прямому» вигляді) з розворотом бітів кожного вхідного байта і результату -- це та сама
CRC-16/X.25, але інший шлях обчислення, тож спільна помилка в обох малоймовірна.
Контроль: CRC-16/X.25("123456789") = 0x906E (каталог CRC RevEng).

Запуск:  python3 MDUV380_firmware/tools/aprs_afsk_ref.py
         python3 MDUV380_firmware/tools/aprs_afsk_ref.py --raw ~/aprs_ref.s16
         (--raw: той самий пакет як AFSK 1200, 8000 Гц, int16 LE, моно -- напр. для перевірки
          стороннім декодером: multimon-ng -t raw -a AFSK1200 ... з попереднім sox -r 22050)
"""
import math
import struct
import sys


def rev8(b):
    return int('{:08b}'.format(b)[::-1], 2)


def rev16(v):
    return int('{:016b}'.format(v)[::-1], 2)


def crc_x25(data):
    crc = 0xFFFF
    for b in data:
        crc ^= rev8(b) << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if (crc & 0x8000) else (crc << 1)
            crc &= 0xFFFF
    return rev16(crc) ^ 0xFFFF


def addr(call, ssid, last):
    c = call.ljust(6)[:6]
    return bytes((ord(ch) << 1) for ch in c) + bytes([0x60 | (ssid << 1) | (1 if last else 0)])


INFO = b'=4926.40N/03201.60E$OpenTYT R3 test 73'


def frame():
    f = addr('APDR16', 0, False) + addr('UR5EAA', 9, False) + addr('WIDE1', 1, True) + bytes([0x03, 0xF0]) + INFO
    fcs = crc_x25(f)
    return f + bytes([fcs & 0xFF, fcs >> 8]), fcs


def afsk(fr, fs=8000, amp=8000, pre=30, post=3):
    bits = []
    for _ in range(pre):
        bits += [(0x7E >> i) & 1 for i in range(8)]
    ones = 0
    for b in fr:
        for i in range(8):
            bit = (b >> i) & 1
            bits.append(bit)
            ones = ones + 1 if bit else 0
            if ones == 5:
                bits.append(0)
                ones = 0
    for _ in range(post):
        bits += [(0x7E >> i) & 1 for i in range(8)]
    out, ph, level, t, n = [], 0.0, 1, 0.0, 0
    for bit in bits:
        if bit == 0:
            level ^= 1
        f = 1200.0 if level else 2200.0
        t += fs / 1200.0
        while n < t:
            ph += 2 * math.pi * f / fs
            out.append(int(round(amp * math.sin(ph))))
            n += 1
    return out


def main():
    assert crc_x25(b'123456789') == 0x906E
    fr, fcs = frame()
    print('кадр, %d байтів з FCS: %s' % (len(fr), fr.hex()))
    print('FCS = 0x%04X (у кадрі LSB першим: %02X %02X)' % (fcs, fr[-2], fr[-1]))
    if '--raw' in sys.argv:
        path = sys.argv[sys.argv.index('--raw') + 1]
        s = [0] * 2400 + afsk(fr) + [0] * 2400
        with open(path, 'wb') as fh:
            fh.write(struct.pack('<%dh' % len(s), *s))
        print('AFSK -> %s (%d відліків, 8000 Гц, int16 LE)' % (path, len(s)))


if __name__ == '__main__':
    main()
