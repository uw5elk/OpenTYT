#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Декодер DMR data-burst-ів із запису HackRF (.C16: int16 I/Q, little-endian).

Що вміє (2026-09-30, diag3):
  * знаходить УСІ burst-и з валідною (з допуском) синхрою і друкує кожен, навіть без
    валідного CRC: час, синхра, slot type (Golay(20,8): колірний код + Data Type), hex,
    CRC ok/bad;
  * Data Type 3 (CSBK), 6 (data header), 7 (rate-1/2), 0/1/2 (PI/LC/термінатор) --
    BPTC(196,96) + CRC16 (маски CSBK A5A5 / header CCCC, для LC -- лише hex);
  * Data Type 8 (rate-3/4) -- справжній треліс ETSI TS 102 361-1 §B.3.7: 196 біт ->
    98 дібітів -> деперемеження -> 49 точок сузір'я (Table B.8) -> 8-станний автомат
    (Table B.9, декодування Вітербі) -> 48 трибітів = 18 байт; далі DBSN + CRC9 (маска 0x1FF);
  * адреси: CSBK -- байти [4:7]/[7:10], data header -- [2:5]/[5:8].

Поріг виявлення сплесків: max(frac * пік, 4 * медіана огинаючої) -- при малому --frac шум
більше не зливається в один суцільний «регіон».

Самоперевірка: tools/test_dmr_data_rx.py (кодери + синтетичний запис 4FSK).

ЛІЦЕНЗІЯ: написано з нуля за ETSI TS 102 361-1 (таблиці B.7-B.9, Golay з породжуючого
полінома). НЕ базується на ok-dmrlib (AGPL).

Запуск:  python3 tools/dmr_data_rx.py BBD_0000.C16 --rate 2000000 [--frac 0.06] [--sync-tol 4]
"""
import argparse
import numpy as np

BAUD = 4800.0
SYNC = {
    'BS_DATA':  0xDFF57D75DF5D, 'BS_VOICE': 0x755FD7DF75F7,
    'MS_DATA':  0xD5D7F77FD757, 'MS_VOICE': 0x7F7D5DD57DFD,
    'MS_RC':    0x77D55F7DFD77,
    'T1_DATA':  0xF7FDD5DDFD55, 'T2_DATA':  0xD7557F5FF7F5,
}
# рівні 4FSK за зростанням частоти (-3, -1, +1, +3) -> дібіти ETSI
ETSI = ['11', '10', '00', '01']

DATA_TYPES = {
    0: 'PI_HDR', 1: 'VLC_HDR', 2: 'TERM_LC', 3: 'CSBK', 4: 'MBC_HDR', 5: 'MBC_CONT',
    6: 'DATA_HDR', 7: 'R12_DATA', 8: 'R34_DATA', 9: 'IDLE', 10: 'R1_DATA',
}


def _bits(v, n=48):
    return [(v >> (n - 1 - i)) & 1 for i in range(n)]


SYNCB = {k: _bits(v) for k, v in SYNC.items()}


# ============================ CRC ==========================================
def crc16_ccitt(data):
    """CRC-CCITT (poly 0x1021, init 0) БЕЗ фінального ^0xFFFF -- тому маски тут
    0x5A5A (= A5A5^FFFF, CSBK) і 0x3333 (= CCCC^FFFF, data header)."""
    c = 0
    for by in data:
        for k in range(7, -1, -1):
            b = (by >> k) & 1
            c = (((c << 1) ^ 0x1021) & 0xFFFF) if (((c >> 15) & 1) ^ b) else ((c << 1) & 0xFFFF)
    return c


def bits_to_bytes(bits):
    n = (len(bits) // 8) * 8
    return bytes(sum(int(bits[i + j]) << (7 - j) for j in range(8)) for i in range(0, n, 8))


def bytes_to_bits(data):
    return [(b >> (7 - k)) & 1 for b in data for k in range(8)]


# ============================ BPTC(196,96) =================================
def _h15(d):
    return [d[0]^d[1]^d[2]^d[3]^d[5]^d[7]^d[8], d[1]^d[2]^d[3]^d[4]^d[6]^d[8]^d[9],
            d[2]^d[3]^d[4]^d[5]^d[7]^d[9]^d[10], d[0]^d[1]^d[2]^d[4]^d[6]^d[7]^d[10]]


def _h13(d):
    return [d[0]^d[1]^d[3]^d[5]^d[6], d[0]^d[1]^d[2]^d[4]^d[6]^d[7],
            d[0]^d[1]^d[2]^d[3]^d[5]^d[7]^d[8], d[0]^d[2]^d[4]^d[5]^d[8]]


def _fix(vec, n, k, parf):
    p = parf(vec[:k])
    if all(p[i] == vec[k + i] for i in range(4)):
        return vec
    for i in range(n):
        t = vec[:]; t[i] ^= 1; pp = parf(t[:k])
        if all(pp[j] == t[k + j] for j in range(4)):
            return t
    return vec


def bptc_196_96(info196, fec=True):
    d = [int(info196[(i * 181) % 196]) for i in range(196)]
    if not fec:
        return [d[1 + r * 15 + c] for r in range(9) for c in range(11)][3:99]
    M = [[d[1 + r * 15 + c] for c in range(15)] for r in range(13)]
    for _ in range(2):
        for r in range(13):
            M[r] = _fix(M[r][:], 15, 11, _h15)
        for c in range(15):
            col = _fix([M[r][c] for r in range(13)], 13, 9, _h13)
            for r in range(13):
                M[r][c] = col[r]
    return [M[r][c] for r in range(9) for c in range(11)][3:99]


def bptc_encode(data12):
    """12 байт -> 196 біт (кодер, для синтетичних тестів). R-біти = 0."""
    info = [0, 0, 0] + bytes_to_bits(data12)          # 99 = 9 рядків x 11
    M = [[0] * 15 for _ in range(13)]
    for r in range(9):
        row = info[r * 11:(r + 1) * 11]
        M[r] = row + _h15(row)
    for c in range(15):
        col = [M[r][c] for r in range(9)]
        p = _h13(col)
        for j in range(4):
            M[9 + j][c] = p[j]
    d = [0] * 196
    for r in range(13):
        for c in range(15):
            d[1 + r * 15 + c] = M[r][c]
    out = [0] * 196
    for i in range(196):
        out[(i * 181) % 196] = d[i]
    return out


# ============================ Golay(20,8) -- slot type =====================
# ETSI B.3.1: укорочений розширений Golay. Паритет = (залишок d(x)*x^11 mod g(x)) << 1 |
# загальна парність; g(x) = x^11+x^10+x^6+x^5+x^4+x^2+1 (0xC75). Біт даних 1 <-> x^0.
# Кодове слово в ефірі (MSB першим): CC(4) | DataType(4) | паритет(12); 10 біт до синхри,
# 10 після. Вивід звірено з опорними значеннями (tools/test_dmr_data_rx.py).
_GOLAY_G = 0xC75


def golay2087_parity(d):
    r = d << 11
    for b in range(18, 10, -1):
        if (r >> b) & 1:
            r ^= _GOLAY_G << (b - 11)
    r &= 0x7FF
    return (r << 1) | ((bin(d).count('1') + bin(r).count('1')) & 1)


_GOLAY_CW = [(d << 12) | golay2087_parity(d) for d in range(256)]


def golay2087_encode(d):
    return _GOLAY_CW[d & 0xFF]


def golay2087_decode(w20):
    """-> (байт даних, кількість виправлених бітів) або (None, None), якщо > 3 помилок."""
    best, bd = None, 99
    for d, cw in enumerate(_GOLAY_CW):
        dist = bin(cw ^ w20).count('1')
        if dist < bd:
            bd, best = dist, d
    if bd > 3:
        return None, None
    return best, bd


# ============================ Rate-3/4 треліс (ETSI §B.3.7) =================
# Таблиця перемеження дібітів (ETSI Table B.7): дібіт i в ефірі = дібіт INTERLEAVE[i] коду.
INTERLEAVE = [0, 1, 8, 9, 16, 17, 24, 25, 32, 33, 40, 41, 48, 49, 56, 57, 64, 65, 72, 73, 80, 81, 88, 89, 96, 97,
              2, 3, 10, 11, 18, 19, 26, 27, 34, 35, 42, 43, 50, 51, 58, 59, 66, 67, 74, 75, 82, 83, 90, 91,
              4, 5, 12, 13, 20, 21, 28, 29, 36, 37, 44, 45, 52, 53, 60, 61, 68, 69, 76, 77, 84, 85, 92, 93,
              6, 7, 14, 15, 22, 23, 30, 31, 38, 39, 46, 47, 54, 55, 62, 63, 70, 71, 78, 79, 86, 87, 94, 95]
# Точка сузір'я -> пара символів (ETSI Table B.8).
CONSTELLATION = [(+1, -1), (-1, -1), (+3, -3), (-3, -3), (-3, -1), (+3, -1), (-1, -3), (+1, -3),
                 (-3, +3), (+3, +3), (-1, +1), (+1, +1), (+1, +3), (-1, +3), (+3, +1), (-3, +1)]
_POINT_OF = {pair: i for i, pair in enumerate(CONSTELLATION)}
# Скінченний автомат (ETSI Table B.9): точка = TRELLIS[стан][трибіт], новий стан = трибіт.
TRELLIS = [[0, 8, 4, 12, 2, 10, 6, 14],
           [4, 12, 2, 10, 6, 14, 0, 8],
           [1, 9, 5, 13, 3, 11, 7, 15],
           [5, 13, 3, 11, 7, 15, 1, 9],
           [3, 11, 7, 15, 1, 9, 5, 13],
           [7, 15, 1, 9, 5, 13, 3, 11],
           [2, 10, 6, 14, 0, 8, 4, 12],
           [6, 14, 0, 8, 4, 12, 2, 10]]
_SYM2BITS = {+3: (0, 1), +1: (0, 0), -1: (1, 0), -3: (1, 1)}
_BITS2SYM = {v: k for k, v in _SYM2BITS.items()}


def _point_bits(pt):
    a, b = CONSTELLATION[pt]
    return _SYM2BITS[a] + _SYM2BITS[b]


_PT_DIST = [[sum(x != y for x, y in zip(_point_bits(i), _point_bits(j))) for j in range(16)] for i in range(16)]


def trellis34_encode(data18):
    """18 байт -> 196 біт burst-а (кодер, для самоперевірки й синтетики)."""
    bits = bytes_to_bits(data18)                       # 144 біти
    tribits = [(bits[3 * i] << 2) | (bits[3 * i + 1] << 1) | bits[3 * i + 2] for i in range(48)] + [0]
    state, dibits = 0, []
    for t in tribits:
        pt = TRELLIS[state][t]
        state = t
        dibits.extend(CONSTELLATION[pt])                # 98 символів у порядку коду
    tx = [dibits[INTERLEAVE[i]] for i in range(98)]    # перемеження
    out = []
    for s in tx:
        out.extend(_SYM2BITS[s])
    return out


def trellis34_decode(bits196):
    """196 біт -> (18 байт, кількість бітових розбіжностей на найкращому шляху).
    Вітербі з жорстким рішенням по бітах точок; кінцевий стан 0 (хвостовий трибіт 0)."""
    rx = [_BITS2SYM[(int(bits196[2 * i]), int(bits196[2 * i + 1]))] for i in range(98)]
    dib = [0] * 98
    for i in range(98):
        dib[INTERLEAVE[i]] = rx[i]                      # деперемеження
    pts = [_POINT_OF[(dib[2 * k], dib[2 * k + 1])] for k in range(49)]
    INF = 10 ** 9
    metric = [0] + [INF] * 7
    paths = [[] for _ in range(8)]
    for k, pt in enumerate(pts):
        nm, npaths = [INF] * 8, [None] * 8
        for s in range(8):
            if metric[s] >= INF:
                continue
            for t in range(8):
                m = metric[s] + _PT_DIST[TRELLIS[s][t]][pt]
                if m < nm[t]:
                    nm[t], npaths[t] = m, paths[s] + [t]
        metric, paths = nm, [p if p is not None else [] for p in npaths]
    best = 0 if metric[0] < INF else min(range(8), key=lambda s: metric[s])
    tribits = paths[best][:48]
    bits = []
    for t in tribits:
        bits.extend([(t >> 2) & 1, (t >> 1) & 1, t & 1])
    return bits_to_bytes(bits), metric[best]


# ============================ CRC-9 data-блоків ============================
def _crc9(data, dbsn7, final_mask):
    """poly 0x059, init 0: payload, потім 7 біт DBSN (MSB першим). Як у dmr_sms.c."""
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
    """Rate-1/2 CONFIRMED (§B.3.10), маска 0x0F0."""
    return _crc9(bytes(payload10), dbsn & 0x7F, 0x0F0)


def crc9_r34(payload16, dbsn):
    """Rate-3/4 CONFIRMED (§B.3.12), маска 0x1FF."""
    return _crc9(bytes(payload16), dbsn & 0x7F, 0x1FF)


def _parse_blk_hdr(b, plen):
    """byte0[7:1]=DBSN; CRC9: біт0 у byte0[0], біти 1..8 у byte1[7..0] (як confirmed_block_fill_r34)."""
    dbsn = (b[0] >> 1) & 0x7F
    raw9 = ((b[0] & 1) << 8) | b[1]
    crc_rx = int('{:09b}'.format(raw9)[::-1], 2)
    return dbsn, crc_rx, bytes(b[2:2 + plen])


def check_block_r12(b12):
    """-> (ok, dbsn, payload10) для CONFIRMED rate-1/2 блока."""
    if len(b12) < 12:
        return False, 0, bytes()
    dbsn, crc_rx, payload = _parse_blk_hdr(b12, 10)
    return crc9_r12(payload, dbsn) == crc_rx, dbsn, payload


def check_block_r34(b18):
    """-> (ok, dbsn, payload16) для CONFIRMED rate-3/4 блока."""
    if len(b18) < 18:
        return False, 0, bytes()
    dbsn, crc_rx, payload = _parse_blk_hdr(b18, 16)
    return crc9_r34(payload, dbsn) == crc_rx, dbsn, payload


def pack_block_r34(payload16, dbsn):
    """Зворотне до check_block_r34 (для тестів)."""
    c9 = crc9_r34(payload16, dbsn)
    b1 = 0
    for i in range(1, 9):
        b1 |= ((c9 >> i) & 1) << (8 - i)
    return bytes([((dbsn & 0x7F) << 1) | (c9 & 1), b1]) + bytes(payload16)


# ============================ розбір одного burst-а ========================
def burst_fields(bits, p):
    """Розрізати burst навколо синхри в позиції p: (info196, slot20) або None."""
    L0, R0 = p - 10 - 98, p + 48 + 10
    if L0 < 0 or R0 + 98 > len(bits):
        return None
    info = list(bits[L0:L0 + 98]) + list(bits[R0:R0 + 98])
    slot = list(bits[p - 10:p]) + list(bits[p + 48:p + 58])
    return info, slot


def decode_burst(bits, p):
    """Повний розбір burst-а. Повертає dict або None."""
    f = burst_fields(bits, p)
    if f is None:
        return None
    info, slot = f
    w20 = int(''.join(str(int(b)) for b in slot), 2)
    d, gerr = golay2087_decode(w20)
    r = {'golay_err': gerr, 'cc': None, 'dt': None, 'dtname': '?', 'hex': '', 'crc': 'n/a',
         'a1': None, 'a2': None, 'extra': ''}
    if d is not None:
        r['cc'], r['dt'] = d >> 4, d & 0x0F
        r['dtname'] = DATA_TYPES.get(r['dt'], 'DT%d' % r['dt'])
    dt = r['dt']
    if dt == 8:
        by, verr = trellis34_decode(info)
        ok, dbsn, _ = check_block_r34(by)
        r['hex'] = by.hex()
        r['crc'] = 'CRC9 ok' if ok else 'CRC9 bad'
        r['extra'] = 'DBSN=%d trellis_err=%d' % (dbsn, verr)
        r['ok'] = ok
        r['bytes'] = by
        return r
    by = bits_to_bytes(bptc_196_96(info))[:12]
    r['hex'], r['bytes'] = by.hex(), by
    crc = crc16_ccitt(by[:10]); rx = (by[10] << 8) | by[11]
    if dt == 3:                                 # CSBK
        ok = (crc ^ 0x5A5A) == rx
        r['crc'] = 'CRC ok' if ok else 'CRC bad'
        r['a1'], r['a2'] = int.from_bytes(by[4:7], 'big'), int.from_bytes(by[7:10], 'big')
    elif dt == 6:                               # data header
        ok = (crc ^ 0x3333) == rx
        r['crc'] = 'CRC ok' if ok else 'CRC bad'
        r['a1'], r['a2'] = int.from_bytes(by[2:5], 'big'), int.from_bytes(by[5:8], 'big')
        dpf = by[0] & 0x0F
        r['extra'] = {1: 'Response o9=%02x' % by[9], 2: 'Unconfirmed', 3: 'CONFIRMED A=%d N(S)=%d S=%d' % (
            (by[0] >> 6) & 1, (by[9] >> 4) & 7, by[9] >> 7)}.get(dpf, 'DPF=%d' % dpf)
    elif dt == 7:                               # rate-1/2: CRC9 має сенс лише для CONFIRMED
        ok9, dbsn, _ = check_block_r12(by)
        r['crc'] = 'CRC9(conf) ok' if ok9 else 'CRC9(conf) bad/unconf'
        ok = True
    else:
        ok = None
    r['ok'] = ok
    return r


# ============================ демодуляція ==================================
def demod_candidates(seg, fs, keep=8):
    from scipy import signal as sg
    spb = fs / BAUD
    inst = np.angle(seg[1:] * np.conj(seg[:-1])) * fs / (2 * np.pi)
    mag = np.abs(seg[1:]); strong = mag > mag.max() * 0.3
    base = np.median(inst[strong]) if strong.any() else 0.0
    taps = sg.firwin(151, 7000 / (fs / 2))
    out = []
    for doff in (-600, -300, 0, 300, 600):
        s = seg * np.exp(-2j * np.pi * (base + doff) / fs * np.arange(seg.size))
        s = sg.lfilter(taps, 1, s)
        disc = np.angle(s[1:] * np.conj(s[:-1])) * fs / (2 * np.pi)
        k = int(round(spb)); mf = np.convolve(disc, np.ones(k) / k, mode='same')
        smag = np.abs(s[1:])
        for ph in np.arange(0, spb, max(1.0, spb / 10.0)):
            c = np.round(np.arange(spb + ph, disc.size - spb, spb)).astype(int)
            c = c[(c > 0) & (c < mf.size)]
            if c.size < 40:
                continue
            # Рівні вчимо лише на символах із сигналом: вікно (33 мс) довше за burst (27.5 мс),
            # і хвости тиші/шуму зсували центроїди k-means -> масові помилки ±1/±3.
            strong_c = smag[c] > 0.3 * smag[c].max()
            if strong_c.sum() < 40:
                continue
            v = mf[c] - np.mean(mf[c][strong_c])
            vs = v[strong_c]
            cen = np.sort(np.percentile(vs, [12, 37, 62, 87]))
            for _ in range(20):
                lab = np.abs(vs[:, None] - cen[None, :]).argmin(1)
                for j in range(4):
                    if (lab == j).any():
                        cen[j] = vs[lab == j].mean()
                cen = np.sort(cen)
            lab = np.abs(vs[:, None] - cen[None, :]).argmin(1)
            score = 1 - np.mean((vs - cen[lab]) ** 2) / np.var(vs)
            lab = np.abs(v[:, None] - cen[None, :]).argmin(1)
            bits = np.empty(2 * lab.size, dtype=np.uint8)
            for j, e in enumerate(ETSI):
                bits[0::2][lab == j] = int(e[0]); bits[1::2][lab == j] = int(e[1])
            # час першого символу (з урахуванням затримки FIR 75 відліків)
            out.append((score, bits, (c[0] + 75) / fs))
    out.sort(key=lambda x: -x[0])
    return out[:keep]


def find_syncs(bits, tol):
    """-> [(позиція, назва, помилок)] -- векторизовано (раніше -- чистий Python, години)."""
    if bits.size < 48:
        return []
    win = np.lib.stride_tricks.sliding_window_view(bits, 48)
    res = []
    for name, sb in SYNCB.items():
        err = (win != np.array(sb, dtype=np.uint8)).sum(1)
        for p in np.nonzero(err <= tol)[0]:
            res.append((int(p), name, int(err[p])))
    return res


def find_bursts(iq, fs, frac=0.06):
    """Регіони з сигналом. Поріг = max(frac*пік, 4*медіана огинаючої)."""
    env = np.abs(iq); w = max(1, int(0.001 * fs))
    envs = np.convolve(env, np.ones(w) / w, mode='same'); pk = envs.max()
    noise = float(np.median(envs))
    thr = max(pk * frac, 4.0 * noise)
    idx = np.where(envs > thr)[0]
    if idx.size == 0:
        return [], pk, thr
    regs, s, p = [], idx[0], idx[0]
    for i in idx[1:]:
        if i - p > int(0.008 * fs):
            regs.append((s, p)); s = i
        p = i
    regs.append((s, p))
    return regs, pk, thr


def _rank(r, serr):
    """Вищий -- кращий кандидат для одного й того самого burst-а."""
    return ((r['golay_err'] is not None) * 4 - (r['golay_err'] or 0) + (r['ok'] is True) * 8 - serr)


def analyze(iq, fs, sync_tol=4, frac=0.06, verbose=False):
    """Повний розбір запису -> список burst-ів (dict), по одному на фізичний burst."""
    regs, pk, thr = find_bursts(iq, fs, frac)
    if verbose:
        print("регіонів: %d (поріг %.4f, пік %.4f)" % (len(regs), thr, pk))
    found = []
    for (s, e) in regs:
        t = max(0.0, s / fs - 0.004); t1 = e / fs
        while t < t1:
            # 40 мс = burst (27.5 мс) + запас: FIR (151 відвід) дає ~1.6 мс перехідного процесу на
            # початку вікна, і з кроком 5 мс хоч одне вікно має >= 3.7 мс запасу з кожного боку.
            seg = iq[int(t * fs):int((t + 0.040) * fs)]
            if seg.size < int(0.02 * fs):
                break
            for score, bits, tb0 in demod_candidates(seg, fs):
                for p, name, serr in find_syncs(bits, sync_tol):
                    r = decode_burst(bits, p)
                    if r is None:
                        continue
                    r['t'] = t + tb0 + (p // 2 - 54) / BAUD   # початок burst-а (54 символи до синхри)
                    r['sync'], r['sync_err'] = name, serr
                    found.append(r)
            t += 0.005
    # один фізичний burst ловлять кілька вікон/кандидатів -> кластер по часу (<10 мс), кращий
    found.sort(key=lambda r: r['t'])
    out = []
    for r in found:
        if out and abs(r['t'] - out[-1]['t']) < 0.010:
            if _rank(r, r['sync_err']) > _rank(out[-1], out[-1]['sync_err']):
                out[-1] = r
        else:
            out.append(r)
    return out


def format_burst(r):
    s = "  %8.3fс %-8s синхра-%d " % (r['t'], r['sync'], r['sync_err'])
    if r['dt'] is None:
        s += "[slot type ?      ] "
    else:
        s += "[CC%-2d %-8s g%d] " % (r['cc'], r['dtname'], r['golay_err'])
    s += "%-36s %-14s" % (r['hex'], r['crc'])
    if r['a1'] is not None:
        s += " a1=%d a2=%d" % (r['a1'], r['a2'])
    if r['extra']:
        s += "  " + r['extra']
    return s


def load_c16(path):
    raw = np.fromfile(path, dtype='<i2').astype(np.float32) / 32768.0
    return raw[0::2] + 1j * raw[1::2]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument("infile")
    ap.add_argument("--rate", type=int, required=True, help="частота дискретизації запису, Гц")
    ap.add_argument("--sync-tol", type=int, default=4, help="допуск помилок у 48-бітній синхрі")
    ap.add_argument("--frac", type=float, default=0.06, help="поріг сплеску як частка піку (нижня межа -- 4x шум)")
    a = ap.parse_args()
    iq = load_c16(a.infile); fs = a.rate
    print("тривалість %.2f с   пік |IQ| = %.3f" % (iq.size / fs, float(np.max(np.abs(iq)))))
    bursts = analyze(iq, fs, a.sync_tol, a.frac, verbose=True)
    print("\n=== усі burst-и з синхрою (%d) ===" % len(bursts))
    if not bursts:
        print("  нічого.")
    for r in bursts:
        print(format_burst(r))


if __name__ == "__main__":
    main()
