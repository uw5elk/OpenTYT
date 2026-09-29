#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Декодер DMR data-burst-ів із .C16.

Декодує:
  * Rate-1/2 (BPTC 196,96): data-header (ACK, CONFIRMED header), CSBK
  * Rate-3/4 (треліс ETSI B.3.7 Table B.9): CONFIRMED data-блоки (18 байт)
    + CRC9 валідація (маска 0x1FF, §B.3.12)

CRC масок у decode_hdr:
  * 0x5A5A -- CSBK/preamble;
  * 0x3333 -- data header (ETSI: crc ^0xCCCC над 80 бітами; наша crc без фін.-XOR -> 0x3333).

Мета: діагностика SMS-квитанцій і CONFIRMED data-блоків (форк OpenTYT).

ЛІЦЕНЗІЯ: написано з нуля за ETSI TS 102 361-1. НЕ базується на ok-dmrlib (AGPL).
"""
import argparse, sys
import numpy as np
from scipy import signal as sg

BAUD = 4800.0
SYNC = {
    'BS_DATA':  0xDFF57D75DF5D, 'BS_VOICE': 0x755FD7DF75F7,
    'MS_DATA':  0xD5D7F77FD757, 'MS_VOICE': 0x7F7D5DD57DFD,
    'MS_RC':    0x77D55F7DFD77,
    'T1_DATA':  0xF7FDD5DDFD55, 'T2_DATA':  0xD7557F5FF7F5,
}
ETSI = ['11', '10', '00', '01']

def _bits(v, n=48):
    return [(v >> (n - 1 - i)) & 1 for i in range(n)]
SYNCB = {k: _bits(v) for k, v in SYNC.items()}

def crc16_ccitt(data):
    c = 0
    for by in data:
        for k in range(7, -1, -1):
            b = (by >> k) & 1
            c = (((c << 1) ^ 0x1021) & 0xFFFF) if (((c >> 15) & 1) ^ b) else ((c << 1) & 0xFFFF)
    return c

def bits_to_bytes(bits):
    n = (len(bits) // 8) * 8
    return bytes(sum(bits[i + j] << (7 - j) for j in range(8)) for i in range(0, n, 8))

def _h15(d):
    return [d[0]^d[1]^d[2]^d[3]^d[5]^d[7]^d[8], d[1]^d[2]^d[3]^d[4]^d[6]^d[8]^d[9],
            d[2]^d[3]^d[4]^d[5]^d[7]^d[9]^d[10], d[0]^d[1]^d[2]^d[4]^d[6]^d[7]^d[10]]
def _h13(d):
    return [d[0]^d[1]^d[3]^d[5]^d[6], d[0]^d[1]^d[2]^d[4]^d[6]^d[7],
            d[0]^d[1]^d[2]^d[3]^d[5]^d[7]^d[8], d[0]^d[2]^d[4]^d[5]^d[8]]
def _fix(vec, n, k, parf):
    p = parf(vec[:k])
    if all(p[i] == vec[k+i] for i in range(4)): return vec
    for i in range(n):
        t = vec[:]; t[i] ^= 1; pp = parf(t[:k])
        if all(pp[j] == t[k+j] for j in range(4)): return t
    return vec
def bptc_196_96(info196, fec=True):
    d = [info196[(i*181) % 196] for i in range(196)]
    if not fec:
        return [d[1+r*15+c] for r in range(9) for c in range(11)][3:99]
    M = [[d[1+r*15+c] for c in range(15)] for r in range(13)]
    for _ in range(2):
        for r in range(13): M[r] = _fix(M[r][:], 15, 11, _h15)
        for c in range(15):
            col = _fix([M[r][c] for r in range(13)], 13, 9, _h13)
            for r in range(13): M[r][c] = col[r]
    return [M[r][c] for r in range(9) for c in range(11)][3:99]

# ---------------------------------------------------------------------------
# Треліс rate-3/4 (ETSI TS 102 361-1 §B.3.7, Table B.9)
# ---------------------------------------------------------------------------
# Таблиця виходів кодера: _TR[state][dibit_input] = 3-бітний символ (0..7).
# Наступний стан завжди = dibit_input.
_TR = [
    [0, 1, 3, 2],   # стан 0
    [7, 6, 4, 5],   # стан 1
    [4, 5, 7, 6],   # стан 2
    [3, 2, 0, 1],   # стан 3
]

def trellis_decode(bits196):
    """Жорстке (hard-decision) декодування треліс rate-3/4 (ETSI §B.3.7, Table B.9).

    Вхід: список/масив з 196 бітів (info-поле burst після деперемеження).
    Зчитує кожні 3 біти як символ (0..7), знаходить найближчий dibit (0..3)
    за мінімальною відстанню Хемінга до таблиці _TR[state][dibit].
    next_state = decoded_dibit. Повертає bytes (~16 байт).
    """
    state = 0
    out_bits = []
    for i in range(0, len(bits196) - 2, 3):
        sym = (bits196[i] << 2) | (bits196[i + 1] << 1) | bits196[i + 2]
        best, bd = 0, 4
        for d in range(4):
            dist = bin(_TR[state][d] ^ sym).count('1')
            if dist < bd:
                bd, best = dist, d
        out_bits.extend([(best >> 1) & 1, best & 1])
        state = best
    n = (len(out_bits) // 8) * 8
    return bytes(sum(out_bits[i + j] << (7 - j) for j in range(8))
                 for i in range(0, n, 8))

# ---------------------------------------------------------------------------
# CRC-9 для data-блоків (ETSI §B.3.10 rate-1/2, §B.3.12 rate-3/4)
# ---------------------------------------------------------------------------
def _crc9(data, dbsn7, final_mask):
    """Базовий CRC-9 (poly=0x059, init=0). Накопичує data, потім 7 DBSN-бітів."""
    reg = 0
    for byte in data:
        for b in range(7, -1, -1):
            msb = (reg >> 8) & 1
            reg = (reg << 1) & 0x1FF
            if msb ^ ((byte >> b) & 1):
                reg ^= 0x059
    for b in range(6, -1, -1):
        msb = (reg >> 8) & 1
        reg = (reg << 1) & 0x1FF
        if msb ^ ((dbsn7 >> b) & 1):
            reg ^= 0x059
    return (~reg & 0x1FF) ^ final_mask

def crc9_r12(payload10, dbsn):
    """CRC-9 для rate-1/2 блоку (ETSI §B.3.10, маска фіналу 0x0F0)."""
    return _crc9(bytes(payload10), dbsn & 0x7F, 0x0F0)

def crc9_r34(payload16, dbsn):
    """CRC-9 для rate-3/4 блоку (ETSI §B.3.12, маска фіналу 0x1FF)."""
    return _crc9(bytes(payload16), dbsn & 0x7F, 0x1FF)

def _parse_blk_hdr(b, plen):
    """Розбирає 2-байтний заголовок блоку: byte0[7:1]=DBSN, {byte0[0],byte1}=CRC9 (bit-reversed).
    Повертає (dbsn, crc_rx, payload)."""
    dbsn = (b[0] >> 1) & 0x7F
    raw9 = ((b[0] & 1) << 8) | b[1]
    crc_rx = int('{:09b}'.format(raw9)[::-1], 2)
    return dbsn, crc_rx, b[2:2 + plen]

def check_block_r12(b12):
    """Валідація 12-байтного rate-1/2 блоку (ETSI §B.3.10).
    Повертає (ok: bool, dbsn: int, payload10: bytes)."""
    if len(b12) < 12:
        return False, 0, bytes()
    dbsn, crc_rx, payload = _parse_blk_hdr(b12, 10)
    return crc9_r12(payload, dbsn) == crc_rx, dbsn, payload

def check_block_r34(b18):
    """Валідація 18-байтного rate-3/4 блоку (ETSI §B.3.12).
    Повертає (ok: bool, dbsn: int, payload16: bytes)."""
    if len(b18) < 18:
        return False, 0, bytes()
    dbsn, crc_rx, payload = _parse_blk_hdr(b18, 16)
    return crc9_r34(payload, dbsn) == crc_rx, dbsn, payload

def decode_r34_blk(bits, p):
    """Спроба декодування rate-3/4 блоку з позиції синхрослова p.
    Аналог decode_hdr, але через треліс. Повертає (bytes18, ok) або None."""
    L0, R0 = p - 10 - 98, p + 48 + 10
    if L0 < 0 or R0 + 98 > len(bits):
        return None
    raw = trellis_decode(bits[L0:L0 + 98] + bits[R0:R0 + 98])
    if len(raw) < 18:
        return None
    b18 = raw[:18]
    ok, _, _ = check_block_r34(b18)
    return b18, ok

def decode_hdr(bits, p, fec=True):
    L0, R0 = p - 10 - 98, p + 48 + 10
    if L0 < 0 or R0 + 98 > len(bits): return None
    by = bits_to_bytes(bptc_196_96(bits[L0:L0+98] + bits[R0:R0+98], fec))
    if len(by) < 12: return None
    crc = crc16_ccitt(by[:10]); rx = (by[10] << 8) | by[11]
    masks = {'csbk5A5A': 0x5A5A, 'hdr3333': 0x3333, 'raw0000': 0x0000, 'ffff': 0xFFFF}
    okmask = next((n for n, m in masks.items() if (crc ^ m) == rx), None)
    return by[:12], okmask

def demod_candidates(seg, fs, keep=8):
    spb = fs / BAUD
    inst = np.angle(seg[1:] * np.conj(seg[:-1])) * fs / (2*np.pi)
    mag = np.abs(seg[1:]); strong = mag > mag.max()*0.3
    base = np.median(inst[strong]) if strong.any() else 0.0
    taps = sg.firwin(151, 7000/(fs/2))
    out = []
    for doff in (-600, -300, 0, 300, 600):
        s = seg * np.exp(-2j*np.pi*(base+doff)/fs*np.arange(seg.size))
        s = sg.lfilter(taps, 1, s)
        disc = np.angle(s[1:]*np.conj(s[:-1])) * fs/(2*np.pi)
        k = int(round(spb)); mf = np.convolve(disc, np.ones(k)/k, mode='same')
        for ph in np.arange(0, spb, 2.0):
            c = np.round(np.arange(spb+ph, disc.size-spb, spb)).astype(int)
            c = c[(c > 0) & (c < mf.size)]
            if c.size < 40: continue
            v = mf[c] - np.mean(mf[c])
            cen = np.sort(np.percentile(v, [12,37,62,87]))
            for _ in range(20):
                lab = np.abs(v[:,None]-cen[None,:]).argmin(1)
                for j in range(4):
                    if (lab==j).any(): cen[j] = v[lab==j].mean()
                cen = np.sort(cen)
            lab = np.abs(v[:,None]-cen[None,:]).argmin(1)
            score = 1 - np.mean((v-cen[lab])**2)/np.var(v)
            bits = []
            for l in lab: bits.extend([int(ETSI[l][0]), int(ETSI[l][1])])
            out.append((score, bits))
    out.sort(key=lambda x: -x[0])
    return [b for _, b in out[:keep]]

def find_bursts(iq, fs, frac=0.06):
    env = np.abs(iq); w = max(1, int(0.001*fs))
    envs = np.convolve(env, np.ones(w)/w, mode='same'); pk = envs.max()
    idx = np.where(envs > pk*frac)[0]
    if idx.size == 0: return [], pk
    regs, s, p = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - p > int(0.008*fs): regs.append((s, p)); s = i
        p = i
    regs.append((s, p)); return regs, pk

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("infile"); ap.add_argument("--rate", type=int, required=True)
    ap.add_argument("--sync-tol", type=int, default=4)
    a = ap.parse_args()
    raw = np.fromfile(a.infile, dtype='<i2').astype(np.float32)/32768.0
    iq = raw[0::2] + 1j*raw[1::2]; fs = a.rate
    peak = float(np.max(np.abs(iq)))
    print("тривалість %.2f с   пік |IQ| = %.3f" % (iq.size/fs, peak))
    regs, pk = find_bursts(iq, fs)
    print("регіонів: %d" % len(regs))
    # (час, sync, hex12, маска) -- унікалізуємо по (час-округл, hex)
    seen = {}
    for (s, e) in regs:
        t0, t1 = s/fs, e/fs; t = max(0.0, t0 - 0.004)
        while t < t1:
            seg = iq[int(t*fs):int((t+0.033)*fs)]
            if seg.size < int(0.02*fs): break
            for bits in demod_candidates(seg, fs):
                for name, sb in SYNCB.items():
                    for p in range(0, len(bits)-48):
                        if sum(1 for i in range(48) if bits[p+i] != sb[i]) <= a.sync_tol:
                            r = decode_hdr(bits, p)
                            if r and r[1]:  # тільки з валідним CRC хоч по одній масці
                                key = (round(t*100), r[0].hex())
                                seen.setdefault(key, (round(t,3), name, r[0], r[1]))
            t += 0.005
    print("\n=== data/CSBK burst-и з валідним CRC ===")
    if not seen:
        print("  нічого."); return
    for (_, (t, name, by, mask)) in sorted(seen.items(), key=lambda x: x[1][0]):
        print("  %.3fс %-8s [%-8s] %s  a1=%d a2=%d" % (
            t, name, mask, by.hex(),
            int.from_bytes(by[4:7],'big') if len(by)>=7 else 0,
            int.from_bytes(by[7:10],'big') if len(by)>=10 else 0))

if __name__ == "__main__":
    main()
