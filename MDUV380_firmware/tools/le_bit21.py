#!/usr/bin/env python3
"""AES-fix5 F2: перевірка гіпотези «стокова ховає біти late-entry MI в ПІДСТАВЛЕНИХ бітах AMBE-кадру» (claude/aes-mi-bit-found.md).

Вхід -- захоплення `rxdiag.py --cap` (24 burst-и = чотири суперфрейми поспіль; формат рядків `seq=<n> <27 байтів hex>`).
Потрібен лише numpy. Код виходу: 0 -- модель підтверджено зв'язком LFSR, 1 -- не підтверджено, 2 -- неправильний вхід.

Що робить:
  F2.1 деперемежування 72 ефірних бітів кожного кодового слова (9 байтів буфера чипа, біт 0 = старший біт байта 0) у матрицю ambe_fr[4][24]
       за розкладом DMR AMBE+2 (таблицю тут складено ПРАВИЛАМИ, не списком: див. ota_to_cell; перевірено: взаємно однозначна, рядки 24/23/11/14 бітів,
       опорні точки з вимірювання -- OTA 21 = [0][0], 5 = [0][4], 9 = [0][3], 1 = [0][5], 13 = [0][2], 71/67/63/59 = [3][0..3]).
  F2.2 статистика розбіжностей з Golay: рядок [0] -- слово Golay(23,12) (порядок [0][23..1], старший біт першим, твірний 0xC75) + біт [0][0] -- загальна
       парність (парна); рядок [1] -- те саме після зняття PN-маски, засіяної 12 бітами даних рядка [0]. Для кожної позиції -- у скількох кадрах вона
       відрізняється від найближчого кодового слова. Підставлений біт видно як позицію, що розходиться приблизно в половині кадрів; кілька піків = кілька
       підставлених бітів у захищених рядках. Незахищені рядки [2],[3] FEC не викриває -- цим методом їх не видно (див. F2.4).
  F2.3 модель «36 бітів на ДВА суперфрейми»: з кожного кодового слова беремо один біт (типово OTA 21), 18 бітів на суперфрейм, 36 бітів на пару суперфреймів.
       Перебираються: порядок збору в суперфреймі (за часом burst-major / за кодовим словом cw-major), склад пари (А+Б, Б+А, чергування А/Б, Б/А),
       прямий і зворотний порядок бітів, CRC4 на початку і в кінці. Критерій -- MI наступного слова == LFSR128d^n(MI попереднього), n = 0..3
       (слово охоплює два суперфрейми, а MI в TX просувається щосуперфрейму, тож n=2 теж правдоподібне). Це 32-бітна рівність, шанс випадково ~2^-32 на спробу.
       CRC4 -- лише підтвердження після знайденого зв'язку: перебираються всі 16 поліномів x^4+..., init 0/F, xorout 0/F.
  F2.4 запасна гіпотеза: слово -- в ОДНОМУ суперфреймі, 18 бітів [0][0] + 18 бітів з ДРУГОЇ позиції (будь-яка з решти 71, зокрема НЕзахищені рядки [2],[3]);
       критерій -- зв'язок LFSR між СУСІДНІМИ суперфреймами (три пари на чотирьох суперфреймах). Не перебирається: різні другі позиції для різних кодових слів.

Запуск:
  python3 le_bit21.py cap.txt            # усе: статистика, F2.3, при невдачі F2.4
  python3 le_bit21.py cap.txt --tol 2    # терпіти до 2 бітових помилок у зв'язку LFSR (канал із помилками)
  python3 le_bit21.py --selftest         # самоперевірка на синтетиці (F2.5)
"""
import argparse, itertools, sys
import numpy as np
import le_bitsearch as L

STUFF_OTA = 21            # ефірний біт, що розходиться з FEC (вимірювання 2026-10-18): ambe_fr[0][0]


# ---- F2.1: деперемежування ----
def ota_to_cell(n):
    """ефірний біт n (0..71) кодового слова -> (рядок, стовпець) у ambe_fr[4][24].
    Дибіт i = n//2 (36 дибітів). Перший біт дибіта (n парний) і другий (n непарний) лягають у різні рядки за правилами:"""
    i = n // 2
    if n % 2 == 0:
        if i % 2 == 0:
            return 0, 23 - i // 2                    # парні дибіти -> рядок 0, стовпці 23..6
        return (1, 10 - (i - 1) // 2) if i <= 21 else (2, 10 - (i - 23) // 2)   # непарні -> рядок 1 (стовпці 10..0), далі рядок 2 (10..4)
    if i % 2 == 0:
        return (0, 5 - i // 2) if i <= 10 else (1, 22 - (i - 12) // 2)           # парні: рядок 0 (5..0), далі рядок 1 (22..11)
    return (2, 3 - (i - 1) // 2) if i <= 7 else (3, 13 - (i - 9) // 2)           # непарні: рядок 2 (3..0), далі рядок 3 (13..0)


CELL = [ota_to_cell(n) for n in range(72)]
OTA = {c: n for n, c in enumerate(CELL)}
assert len(set(CELL)) == 72, "розклад деперемежування не взаємно однозначний"


def frame_of(bits72):
    f = [[0] * 24 for _ in range(4)]
    for n in range(72):
        r, c = CELL[n]
        f[r][c] = int(bits72[n])
    return f


# ---- Golay(23,12), твірний 0xC75; точний декодер (досконалий код: будь-яке слово в межах 3 помилок) ----
GPOLY = 0xC75


def _rem(v, nbits=23):
    for i in range(nbits - 1, 10, -1):
        if (v >> i) & 1:
            v ^= GPOLY << (i - 11)
    return v


def g_encode(d12):
    v = (d12 & 0xFFF) << 11
    return v | _rem(v)


_SYN = {}
for _t in range(0, 4):
    for _pos in itertools.combinations(range(23), _t):
        _m = 0
        for _p in _pos:
            _m |= 1 << _p
        _SYN[_rem(_m)] = _m
assert len(_SYN) == 2048, len(_SYN)


def g_correct(w23):
    m = _SYN[_rem(w23)]
    return w23 ^ m, m


def pn_bits(u0):
    """PN-маска рядка [1] (23 біти): LCG, засіяна 12 бітами даних рядка [0]; перший біт маски стоїть при старшому біті слова."""
    pr = 16 * u0
    out = []
    for _ in range(23):
        pr = (173 * pr + 13849) & 0xFFFF
        out.append((pr >> 15) & 1)
    return out


def row_word(f, row, hi, lo):
    """слово з f[row][hi..lo], старший біт першим (hi -- старший)."""
    v = 0
    for c in range(hi, lo - 1, -1):
        v = (v << 1) | f[row][c]
    return v


def analyse_frame(f):
    """-> (розбіжності рядка 0 [позиції стовпців 0..23], розбіжності рядка 1 [стовпці 0..22]).
    Рядок 0: слово [23..1] -> найближче кодове, позиція стовпця c <-> біт (c-1) слова; [0][0] порівнюється з парністю виправленого слова."""
    w0 = row_word(f, 0, 23, 1)
    c0, m0 = g_correct(w0)
    d0 = [c + 1 for c in range(23) if (m0 >> c) & 1]
    if f[0][0] != (bin(c0).count("1") & 1):
        d0.append(0)
    u0 = c0 >> 11                                                   # 12 бітів даних [0][23..12]
    pn = pn_bits(u0)
    pnv = 0
    for b in pn:
        pnv = (pnv << 1) | b
    w1 = row_word(f, 1, 22, 0) ^ pnv
    c1, m1 = g_correct(w1)
    d1 = [c for c in range(23) if (m1 >> c) & 1]
    return d0, d1


def stats(sfs, out=print):
    n = 0
    h0 = np.zeros(24, dtype=int); h1 = np.zeros(23, dtype=int)
    nerr = {}
    for sf in sfs:
        for v in range(6):
            for j in range(3):
                f = frame_of(sf["bits"][v][72 * j:72 * j + 72])
                d0, d1 = analyse_frame(f)
                n += 1
                for c in d0: h0[c] += 1
                for c in d1: h1[c] += 1
                nerr[len(d0)] = nerr.get(len(d0), 0) + 1
    out("--- F2.2 статистика розбіжностей з Golay: кадрів (кодових слів) = %d ---" % n)
    out("    розподіл числа розбіжностей на кадр (рядок [0]): " + ", ".join("%d: %d" % (k, nerr[k]) for k in sorted(nerr)))
    top = sorted(range(24), key=lambda c: -h0[c])[:6]
    out("    рядок [0] (захищений Golay + парність):")
    for c in top:
        if h0[c]:
            out("       ambe_fr[0][%2d] (ефірний біт %2d): %3d з %d  (%2.0f%%)%s" % (c, OTA[(0, c)], h0[c], n, 100.0 * h0[c] / n,
                "   <-- піднятий над шумом" if h0[c] >= max(8, 0.2 * n) else ""))
    top = sorted(range(23), key=lambda c: -h1[c])[:4]
    out("    рядок [1] (захищений Golay(23,12) після зняття PN-маски):")
    for c in top:
        if h1[c]:
            out("       ambe_fr[1][%2d] (ефірний біт %2d): %3d з %d  (%2.0f%%)%s" % (c, OTA[(1, c)], h1[c], n, 100.0 * h1[c] / n,
                "   <-- піднятий над шумом" if h1[c] >= max(8, 0.2 * n) else ""))
    peaks0 = [c for c in range(24) if h0[c] >= max(8, 0.2 * n)]
    peaks1 = [c for c in range(23) if h1[c] >= max(8, 0.2 * n)]
    out("    піків над шумом: рядок [0]: %s; рядок [1]: %s" % (
        [("[0][%d]" % c) for c in peaks0] or "нема", [("[1][%d]" % c) for c in peaks1] or "нема"))
    if len(peaks0) + len(peaks1) > 1:
        out("    УВАГА: піків кілька -- підставлених бітів у захищених рядках може бути більше одного (F2.3 бере лише --cell)")
    return h0, h1, n


# ---- вилучення потоків бітів ----
def cell_bits(sf, ota):
    """-> масив [6 burst-ів][3 кодових слова] бітів на ефірній позиції ota кожного кодового слова."""
    return [[int(sf["bits"][v][72 * j + ota]) for j in range(3)] for v in range(6)]


def flat(b, order):
    if order == "time":
        return [b[v][j] for v in range(6) for j in range(3)]           # burst за burst, у burst-і cw 0..2
    return [b[v][j] for j in range(3) for v in range(6)]                # cw за cw, у cw burst-и 1..6


def unflat(seq18, order):
    b = [[0] * 3 for _ in range(6)]
    k = 0
    if order == "time":
        for v in range(6):
            for j in range(3):
                b[v][j] = seq18[k]; k += 1
    else:
        for j in range(3):
            for v in range(6):
                b[v][j] = seq18[k]; k += 1
    return b


COMPOSE = ("AB", "BA", "altAB", "altBA")


def compose(a, b, how):
    if how == "AB":
        return a + b
    if how == "BA":
        return b + a
    seq = []
    x, y = (a, b) if how == "altAB" else (b, a)
    for p, q in zip(x, y):
        seq += [p, q]
    return seq


def decompose(seq, how):
    """обернена до compose: 36 бітів -> (a, b)"""
    if how == "AB":
        return seq[:18], seq[18:]
    if how == "BA":
        return seq[18:], seq[:18]
    x, y = seq[0::2], seq[1::2]
    return (x, y) if how == "altAB" else (y, x)


def split_word(seq36, rev, crcpos):
    """36 бітів -> (mi32, crc4) за прямим/зворотним порядком і положенням CRC."""
    s = seq36[::-1] if rev else seq36
    mi_bits, crc_bits = (s[:32], s[32:]) if crcpos == "end" else (s[4:], s[:4])
    mi = 0
    for b in mi_bits: mi = (mi << 1) | b
    crc = 0
    for b in crc_bits: crc = (crc << 1) | b
    return mi, crc


def join_word(mi, crc, rev, crcpos):
    mb = [(mi >> (31 - i)) & 1 for i in range(32)]
    cb = [(crc >> (3 - i)) & 1 for i in range(4)]
    s = mb + cb if crcpos == "end" else cb + mb
    return s[::-1] if rev else s


def lfsr_chain(mi, n):
    for _ in range(n):
        mi = L.lfsr_next(mi)
    return mi


def ham(a, b):
    return bin((a ^ b) & 0xFFFFFFFF).count("1")


def crc4_generic(mi, poly, init, xorout):
    reg = init
    for i in range(32):
        bit = (mi >> (31 - i)) & 1
        top = (reg >> 3) & 1
        reg = (reg << 1) & 0xF
        if top ^ bit:
            reg ^= poly
    return reg ^ xorout


def crc_family(pairs):
    """pairs: [(mi, crc4)] -> список (poly, init, xorout, порядок бітів CRC), що збігаються на ВСІХ словах."""
    res = []
    for poly in range(16):
        for init in (0, 0xF):
            for xo in (0, 0xF):
                for rv in (0, 1):
                    ok = True
                    for mi, crc in pairs:
                        c = crc4_generic(mi, poly, init, xo)
                        if rv:
                            c = int("{:04b}".format(c)[::-1], 2)
                        if c != crc:
                            ok = False; break
                    if ok:
                        res.append((poly, init, xo, rv))
    return res


# ---- F2.3 / F2.4 ----
def runs(sfs):
    """послідовності суперфреймів поспіль (зв'язок з parse_capture)."""
    out = []; cur = []
    for k, sf in enumerate(sfs):
        if sf["linked"] and cur:
            cur.append(k)
        else:
            if cur: out.append(cur)
            cur = [k]
    if cur: out.append(cur)
    return out


def _rel(words, nmax, tol):
    """words -- МІ послідовних слів; -> n, якщо ВСІ сусідні пари мають mi[k+1] ~ lfsr^n(mi[k]) (відстань <= tol), інакше None. Найменший n."""
    for n in range(0, nmax + 1):
        if n == 0 and len(set(words)) == 1 and words[0] in (0, 0xFFFFFFFF):
            continue
        if all(ham(lfsr_chain(words[k], n), words[k + 1]) <= tol for k in range(len(words) - 1)):
            return n
    return None


def model_two_sf(sfs, ota, tol, out):
    """F2.3: слово = пара суперфреймів. -> список знахідок."""
    found = []; trials = 0
    for run in runs(sfs):
        for off in (0, 1):
            pairs = [(run[k], run[k + 1]) for k in range(off, len(run) - 1, 2)]
            if len(pairs) < 2:
                continue
            for order in ("time", "cw"):
                for how in COMPOSE:
                    for rev in (False, True):
                        for crcpos in ("end", "start"):
                            words = []
                            for a_i, b_i in pairs:
                                a = flat(cell_bits(sfs[a_i], ota), order); b = flat(cell_bits(sfs[b_i], ota), order)
                                words.append(split_word(compose(a, b, how), rev, crcpos))
                            trials += 1
                            n = _rel([w[0] for w in words], 3, tol)
                            if n is not None:
                                found.append({"model": "F2.3", "order": order, "compose": how, "rev": rev, "crcpos": crcpos, "n": n,
                                              "words": words, "off": off, "pairs": pairs, "cell": ota,
                                              "dist": max(ham(lfsr_chain(words[k][0], n), words[k + 1][0]) for k in range(len(words) - 1))})
    return found, trials


def model_second(sfs, ota, tol, out):
    """F2.4: слово = ОДИН суперфрейм: 18 бітів ota + 18 бітів з другої позиції p."""
    found = []; trials = 0
    for run in runs(sfs):
        if len(run) < 2:
            continue
        for p in range(72):
            if p == ota:
                continue
            for order in ("time", "cw"):
                A = {k: flat(cell_bits(sfs[k], ota), order) for k in run}
                B = {k: flat(cell_bits(sfs[k], p), order) for k in run}
                for how in COMPOSE:
                    for rev in (False, True):
                        for crcpos in ("end", "start"):
                            words = [split_word(compose(A[k], B[k], how), rev, crcpos) for k in run]
                            trials += 1
                            n = _rel([w[0] for w in words], 2, tol)
                            if n is not None:
                                found.append({"model": "F2.4", "order": order, "compose": how, "rev": rev, "crcpos": crcpos, "n": n,
                                              "words": words, "p": p, "cell": ota, "run": run,
                                              "dist": max(ham(lfsr_chain(words[k][0], n), words[k + 1][0]) for k in range(len(words) - 1))})
    return found, trials


def fp_prob(trials, nsteps, tol, npairs):
    """оцінка очікуваного числа ХИБНИХ збігів: trials * (nsteps+1 значень n) * P(відстань <= tol)^npairs, P = sum C(32,k)/2^32."""
    from math import comb
    pr = sum(comb(32, k) for k in range(tol + 1)) / 2.0 ** 32
    return trials * nsteps * (pr ** npairs)


def describe(f, out):
    m = f["model"]
    cellname = "ambe_fr[%d][%d]" % CELL[f["cell"]]
    out("  модель %s: біт %s (ефірний біт %d)%s" % (m, cellname, f["cell"],
        "" if m == "F2.3" else " + друга позиція %s (ефірний біт %d)" % ("ambe_fr[%d][%d]" % CELL[f["p"]], f["p"])))
    out("    збір за: %s;  склад: %s;  порядок бітів: %s;  CRC4: %s;  зв'язок: MI[наст] == LFSR128d^%d(MI[попер]), найбільша відстань %d біт" % (
        {"time": "часом (burst за burst)", "cw": "кодовим словом (cw за cw)"}[f["order"]], f["compose"], "ЗВОРОТНИЙ" if f["rev"] else "прямий",
        "на початку" if f["crcpos"] == "start" else "в кінці", f["n"], f["dist"]))
    for k, (mi, crc) in enumerate(f["words"]):
        out("      слово %d: MI=%08X CRC4(з бітів)=%X" % (k, mi, crc))
    fam = crc_family(f["words"])
    std = all(L.crc4(mi) == crc for mi, crc in f["words"])
    out("    CRC4 стандартний (x^4+x+1, інверсія, як у dmr_le_mi_build): %s" % ("ЗБІГАЄТЬСЯ" if std else "ні"))
    if fam:
        out("    інші CRC4, що збігаються на всіх словах (поліном, init, xorout, CRC у зворотному порядку): " + "; ".join(
            "0x%X/%X/%X/%d" % x for x in fam[:6]) + (" ..." if len(fam) > 6 else ""))
    else:
        out("    жоден CRC4 із перебору (16 поліномів x init x xorout x порядок) не збігся -- CRC інший або біти з помилками")


def analyse(sfs, ota=STUFF_OTA, tol=0, fallback="auto", out=print):
    """-> (підтверджено?, знахідки F2.3, знахідки F2.4)"""
    f23 = []; f24 = []
    out("суперфреймів: %d, послідовностей поспіль: %s" % (len(sfs), [len(r) for r in runs(sfs)]))
    if len(sfs) >= 2:
        stats(sfs, out)
    out("--- F2.3: модель «36 бітів на два суперфрейми», біт ambe_fr[%d][%d] (ефірний %d) ---" % (CELL[ota][0], CELL[ota][1], ota))
    if not any(len(r) >= 4 for r in runs(sfs)):
        out("    потрібно щонайменше 4 суперфрейми ПОСЛІДОВНО (два слова = пара зв'язку LFSR); є лише %s -- перевірку зв'язку виконати неможливо." % [len(r) for r in runs(sfs)])
    else:
        f23, tr = model_two_sf(sfs, ota, tol, out)
        out("    спроб (розкладок): %d, знайдено: %d, очікувано хибних ≈ %.2g" % (tr, len(f23), fp_prob(tr, 4, tol, 1)))
        for f in f23:
            describe(f, out)
    confirmed = bool(f23)
    if (not confirmed and fallback == "auto") or fallback == "always":
        out("--- F2.4: запасна гіпотеза: слово в ОДНОМУ суперфреймі, 18 бітів ambe_fr[%d][%d] + 18 бітів з другої позиції (усі 71 інші) ---" % CELL[ota])
        if not any(len(r) >= 2 for r in runs(sfs)):
            out("    потрібно щонайменше 2 суперфрейми поспіль")
        else:
            f24, tr = model_second(sfs, ota, tol, out)
            npairs = max(len(r) for r in runs(sfs)) - 1
            out("    спроб: %d, знайдено: %d, очікувано хибних ≈ %.2g (пар зв'язку на послідовність: %d)" % (tr, len(f24), fp_prob(tr, 3, tol, npairs), npairs))
            for f in f24:
                describe(f, out)
            confirmed = confirmed or bool(f24)
    if not confirmed:
        out("\nМодель НЕ ПІДТВЕРДЖЕНО зв'язком LFSR. Це не спростовує, що біт [0][0] підставлений (див. статистику F2.2) -- лише що 18 бітів на суперфрейм\n"
            "у перевірених розкладках не складаються в MI. Можливо: бітові помилки (спробуй --tol 2), інша розкладка слова, кілька підставлених бітів, "
            "захоплення з розривами (скидань > 0).")
    return confirmed, f23, f24


# ---- синтетика (F2.5) ----
def synth_frame_bits(rng, stuff=None, ber=0.0):
    """випадковий AMBE-подібний кадр із коректним FEC (c0: Golay+парність, c1: Golay + PN) -> 72 ефірних бітів. stuff: {ota: bit} -- підстановка ПІСЛЯ FEC."""
    f = [[0] * 24 for _ in range(4)]
    u0 = int(rng.integers(0, 4096)); u1 = int(rng.integers(0, 4096))
    cw0 = g_encode(u0)
    for k in range(23):
        f[0][23 - k] = (cw0 >> (22 - k)) & 1
    f[0][0] = bin(cw0).count("1") & 1
    pn = pn_bits(u0)
    cw1 = g_encode(u1)
    for k in range(23):
        f[1][22 - k] = ((cw1 >> (22 - k)) & 1) ^ pn[k]
    for c in range(11): f[2][c] = int(rng.integers(0, 2))
    for c in range(14): f[3][c] = int(rng.integers(0, 2))
    bits = [f[r][c] for (r, c) in CELL]
    for ota, b in (stuff or {}).items():
        bits[ota] = b
    if ber:
        bits = [b ^ int(rng.random() < ber) for b in bits]
    return bits


def synth_capture(model, nsf=4, seed=1, ber=0.0, mi0=0x1234ABCD, order="time", how="altAB", rev=False, crcpos="end", p=None, noise=False):
    """model: 'F2.3' (слово на два суперфрейми, біт 21), 'F2.4' (слово в суперфреймі, біти 21 і p), або шум (noise=True)."""
    rng = np.random.default_rng(seed)
    nstream = {s: ({}, {}) for s in range(nsf)}            # sf -> (a-біти за burst/cw, b-біти)
    mi = mi0
    if not noise:
        if model == "F2.3":
            for k in range(0, nsf, 2):
                seq = join_word(mi, L.crc4(mi), rev, crcpos)
                a, b = decompose(seq, how)
                # у моделі F2.3 пара (A,B) -- це два суперфрейми по 18 бітів
                nstream[k] = (unflat(a, order), None); nstream[k + 1] = (unflat(b, order), None)
                mi = L.lfsr_next(mi)
        else:
            for s in range(nsf):
                seq = join_word(mi, L.crc4(mi), rev, crcpos)
                a, b = decompose(seq, how)
                nstream[s] = (unflat(a, order), unflat(b, order))
                mi = L.lfsr_next(mi)
    lines = []
    for s in range(nsf):
        for v in range(6):
            chunk = []
            for j in range(3):
                stuff = None
                if noise:
                    stuff = {STUFF_OTA: int(rng.integers(0, 2))}
                    if p is not None: stuff[p] = int(rng.integers(0, 2))
                else:
                    stuff = {STUFF_OTA: nstream[s][0][v][j]}
                    if model == "F2.4":
                        stuff[p] = nstream[s][1][v][j]
                chunk += synth_frame_bits(rng, stuff, ber)
            lines.append("seq=%d %s" % (v + 1, np.packbits(np.array(chunk, dtype=np.uint8)).tobytes().hex().upper()))
    return "\n".join(lines) + "\n"


def selftest(out=print):
    ok = True
    def check(cond, msg):
        nonlocal ok
        out("самоперевірка %-62s %s" % (msg, "ok" if cond else "ПРОВАЛ"))
        ok &= bool(cond)
    quiet = lambda *a: None
    # 1. F2.3 за різними розкладками -> знаходить саме її
    for (order, how, rev, crcpos) in (("time", "altAB", False, "end"), ("cw", "AB", True, "start"), ("time", "BA", False, "start")):
        sfs = L.parse_capture(synth_capture("F2.3", 4, seed=3, order=order, how=how, rev=rev, crcpos=crcpos))
        f, _ = model_two_sf(sfs, STUFF_OTA, 0, quiet)
        hit = [x for x in f if (x["order"], x["compose"], x["rev"], x["crcpos"]) == (order, how, rev, crcpos)]
        check(len(f) == 1 and len(hit) == 1 and hit[0]["n"] == 1 and L.crc4(hit[0]["words"][0][0]) == hit[0]["words"][0][1],
              "F2.3 %s/%s/%s/%s: знайдено %d" % (order, how, "rev" if rev else "fwd", crcpos, len(f)))
    # 2. F2.4: друга позиція в НЕзахищеному рядку [3] ([3][5]) -> знаходить p і розкладку
    p = OTA[(3, 5)]
    sfs = L.parse_capture(synth_capture("F2.4", 4, seed=4, how="altBA", order="cw", rev=True, crcpos="end", p=p))
    f, _ = model_second(sfs, STUFF_OTA, 0, quiet)
    hit = [x for x in f if x["p"] == p and (x["order"], x["compose"], x["rev"], x["crcpos"]) == ("cw", "altBA", True, "end")]
    check(len(f) == 1 and len(hit) == 1, "F2.4 друга позиція [3][5] (ефірний %d): знайдено %d" % (p, len(f)))
    # 3. статистика: біт [0][0] піднятий, інших піків нема
    sfs = L.parse_capture(synth_capture("F2.3", 4, seed=5))
    h0, h1, n = stats(sfs, quiet)
    check(h0[0] >= 0.3 * n and max(h0[1:]) == 0 and max(h1) == 0, "F2.2 статистика: [0][0]=%d з %d, інші %d/%d" % (h0[0], n, max(h0[1:]), max(h1)))
    # 3b. два підставлені біти в захищених рядках -> два піки
    rng = np.random.default_rng(6)
    lines = []
    for s in range(4):
        for v in range(6):
            chunk = []
            for j in range(3):
                chunk += synth_frame_bits(rng, {STUFF_OTA: int(rng.integers(0, 2)), OTA[(0, 7)]: int(rng.integers(0, 2))})
            lines.append("seq=%d %s" % (v + 1, np.packbits(np.array(chunk, dtype=np.uint8)).tobytes().hex().upper()))
    h0, h1, n = stats(L.parse_capture("\n".join(lines)), quiet)
    check(h0[0] >= 0.3 * n and h0[7] >= 0.2 * n, "F2.2 два підставлені біти: [0][0]=%d [0][7]=%d з %d" % (h0[0], h0[7], n))
    # 4. шум -> нічого (і F2.3, і F2.4)
    for seed in (11, 12):
        sfs = L.parse_capture(synth_capture("F2.3", 4, seed=seed, noise=True, p=OTA[(3, 5)]))
        f1, _ = model_two_sf(sfs, STUFF_OTA, 0, quiet); f2, _ = model_second(sfs, STUFF_OTA, 0, quiet)
        check(not f1 and not f2, "шум (seed %d): F2.3 знайдено %d, F2.4 знайдено %d" % (seed, len(f1), len(f2)))
    # 5. сигнал без зв'язку LFSR (інше MI в другому слові) -> нічого
    sfs = L.parse_capture(synth_capture("F2.3", 4, seed=7))
    text = synth_capture("F2.3", 2, seed=7, mi0=0x1234ABCD) + synth_capture("F2.3", 2, seed=8, mi0=0x0F0F0F0F)
    f, _ = model_two_sf(L.parse_capture(text), STUFF_OTA, 0, quiet)
    check(not f, "два слова без зв'язку LFSR: знайдено %d" % len(f))
    # 6. помилки в бітах: tol=0 не знаходить, tol=2 знаходить (одна помилка в другому слові)
    text = synth_capture("F2.3", 4, seed=9)
    lines = text.splitlines()
    # перевернути один потрібний біт у ДРУГОМУ слові (burst 12, cw 0): ota 21 -> байт 2, маска 0x04.
    # Помилка в першому слові після lfsr_chain розтікається на багато бітів, тому --tol її не поглинає (див. довідку).
    seq12, hexs = lines[12].split(" ", 1)
    raw = bytearray.fromhex(hexs); raw[2] ^= 0x04
    lines[12] = seq12 + " " + raw.hex().upper()
    sfs = L.parse_capture("\n".join(lines) + "\n")
    f0, _ = model_two_sf(sfs, STUFF_OTA, 0, quiet); f2, _ = model_two_sf(sfs, STUFF_OTA, 2, quiet)
    check(not f0 and len(f2) >= 1, "один бітовий збій: tol=0 -> %d, tol=2 -> %d" % (len(f0), len(f2)))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", default="-", help="захоплення (rxdiag.py --cap); `-` -- stdin")
    ap.add_argument("--tol", type=int, default=0, choices=range(0, 5), help="скільки бітів різниці терпіти у зв'язку LFSR (типово 0). Поглинає помилки лише в ОСТАННЬОМУ слові ланцюжка: помилка в першому слові розтікається по lfsr_chain на багато бітів")
    ap.add_argument("--cell", type=int, default=STUFF_OTA, help="ефірний біт (0..71), який вважаємо підставленим (типово 21 = ambe_fr[0][0])")
    ap.add_argument("--fallback", choices=("auto", "always", "never"), default="auto", help="F2.4: auto -- лише коли F2.3 не підтвердилась")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    sfs = L.parse_capture(text)
    if len(sfs) < 2:
        print("потрібно щонайменше 2 повні суперфрейми (seq 1..6 поспіль), знайдено %d" % len(sfs), file=sys.stderr)
        sys.exit(2)
    if not 0 <= args.cell < 72:
        print("--cell має бути 0..71", file=sys.stderr); sys.exit(2)
    ok, _a, _b = analyse(sfs, args.cell, args.tol, args.fallback)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
