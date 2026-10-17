#!/usr/bin/env python3
"""AES-fix4 D2: тести tools/le_bitsearch.py.

 T0  порт Golay/CRC4/LFSR/побудови слів звірено із СПРАВЖНІМ C (dmr_aes.c) за золотими векторами (згенеровано gcc з dmr_le_mi_build /
     dmr_lfsr128d / dmr_le_mi_decode), інакше самоперевірка D2.5 була б колом;
 T1  синтетичне захоплення НАШОЮ схемою -> інструмент знаходить рівно її (і впізнає як «збігається з прошивкою»); інша схема (структурна з
     перестановкою груп, вільна, інший порядок burst-ів) -> знаходить саме її і каже «відрізняється»; помилки в бітах -> толерантність;
 T2  шум (без сигналу) -> нічого; сигнал без зв'язку LFSR між суперфреймами -> нічого (третя умова працює);
 парсер формату `rxdiag.py --cap`.
"""
import io, os, sys, contextlib
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import le_bitsearch as L
import rxdiag

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


# ---- T0: золоті вектори з C ----
GOLD = [  # mi, next_mi, frag (18 ніблів: vc1 cw0 cw1 cw2, vc2 ...)
    (0x11223344, 0xCC898045, "124134232DB2E19D7C"),
    (0x00000001, 0xB6DB68A3, "00000100C004003006"),
    (0xDEADBEEF, 0x3B1ED802, "DDEEBFAE515C8EBC53"),
    (0x5AE80A87, 0xF8B5AA87, "588A07EABA88F857D5"),
    (0xFFFFFFFF, 0x6DB6D861, "FFFFFFFFAFFDFF8FF3"),
]
for mi, nx, fr in GOLD:
    check(L.lfsr_next(mi) == nx, "LFSR128d(%08X) = %08X, очікувано %08X" % (mi, L.lfsr_next(mi), nx))
    f = L.build_frag(mi)
    got = "".join("%X" % f[vc][cw] for vc in range(1, 7) for cw in range(3))
    check(got == fr, "frag(%08X) = %s, очікувано %s" % (mi, got, fr))
    r = L.decode_mi(L.build_words(mi))
    check(r == (mi, 0), "decode_mi(%08X) = %r" % (mi, r))
# виправлення помилок: до 3 біт у слові виправляються, 4 -- ні (d=8)
w = L.build_words(0xDEADBEEF)
for nerr, expect_ok in ((1, True), (2, True), (3, True), (4, False)):
    ww = list(w)
    for b in range(nerr):
        ww[0] ^= 1 << (23 - b * 5)
    r = L.decode_mi(ww)
    check((r is not None and r[0] == 0xDEADBEEF) == expect_ok, "%d помилок у слові: %r" % (nerr, r))

FW = [tuple(72 * j + p for p in L.FIRMWARE_TUPLE) for j in range(3)]


def canon(sfs, tups, order="std"):
    sid = L.sigids(sfs)
    return (order, tuple(tuple(sid[p] for p in t) for t in tups))


# ---- T1a: наша схема ----
for nsf in (2, 3):
    sfs = L.parse_capture(L.synth_capture(0x11223344, nsf, FW, seed=10 + nsf))
    check(len(sfs) == nsf and len(L.link_pairs(sfs)) == nsf - 1, "парсер: суперфреймів %d" % len(sfs))
    out = []
    n, txt = quiet(L.run, sfs, ["std"], 2, True)
    check(n == 1, "T1a (%d sf): знайдено %d рішень, очікувано 1" % (nsf, n))
    check("ЗБІГАЄТЬСЯ" in txt, "T1a: не впізнав збіг із прошивкою")
    check("MI суперфрейму 0: 11223344" in txt and "MI суперфрейму 1: CC898045" in txt, "T1a: MI у звіті")

# ---- T1b: інша схема, структурна (інші зсуви, групи переставлено) ----
off = (3, 40, 17, 66)
perm = (2, 0, 1)
S2 = [tuple(72 * perm[j] + p for p in off) for j in range(3)]
sfs = L.parse_capture(L.synth_capture(0xCAFEF00D, 3, S2, seed=21))
f = L.structured(sfs, ["std"], 2, lambda *_: None)
check(L.solutions(f, sfs) == {canon(sfs, S2)}, "T1b структурна: рішення %r" % (L.solutions(f, sfs),))
n, txt = quiet(L.run, sfs, ["std"], 2, True)
check(n == 1 and "ВІДРІЗНЯЄТЬСЯ" in txt, "T1b: має сказати «відрізняється»")

# ---- T1c: вільна схема (позиції будь-де), і інший порядок burst-ів ----
rng = np.random.default_rng(77)
pos = rng.choice(216, size=12, replace=False)
S3 = [tuple(int(v) for v in pos[4 * j:4 * j + 4]) for j in range(3)]
sfs = L.parse_capture(L.synth_capture(0x0BADF00D, 3, S3, seed=22))
f, _h = L.free(sfs, ["std"], lambda *_: None)
check(L.solutions(f, sfs) == {canon(sfs, S3)}, "T1c вільна: %r" % (L.solutions(f, sfs),))
sfs = L.parse_capture(L.synth_capture(0x0BADF00D, 3, S3, order=L.ORDERS["rev"], seed=23))
f, _h = L.free(sfs, ["std", "rev"], lambda *_: None)
check(L.solutions(f, sfs) == {canon(sfs, S3, "rev")}, "T1c: порядок burst-ів rev не знайдено/плутається: %r" % (L.solutions(f, sfs),))

# ---- T1d: біти з помилками (по 1 на слово) ----
sfs = L.parse_capture(L.synth_capture(0x13572468, 3, FW, seed=31, flips=1))
f = L.structured(sfs, ["std"], 2, lambda *_: None)
check(L.solutions(f, sfs) == {canon(sfs, FW)}, "T1d: з помилками tol=2 не знайшов: %r" % (L.solutions(f, sfs),))
f = L.structured(sfs, ["std"], 0, lambda *_: None)
check(not f, "T1d: tol=0 не мав би знайти захоплення з помилками (знайшов %d)" % len(f))

# ---- T2: шум -- нічого (усі порядки, обидва рівні) ----
for seed, nb in ((5, 12), (6, 12), (7, 18), (8, 24)):
    rng = np.random.default_rng(seed)
    txt = "\n".join("seq=%d %s" % (i % 6 + 1, rng.integers(0, 256, 27, dtype=np.uint8).tobytes().hex()) for i in range(nb))
    sfs = L.parse_capture(txt)
    n, _ = quiet(L.run, sfs, list(L.ORDERS), 2, True)
    check(n == 0, "T2: шум (seed=%d, %d burst-ів) дав %d «рішень»" % (seed, nb, n))

# ---- T2b: Golay/CRC правильні, але між суперфреймами нема зв'язку LFSR -> нічого ----
sfs = L.parse_capture(L.synth_capture(0, 2, FW, seed=41, mis=[0x11223344, 0x99999999]))
n, _ = quiet(L.run, sfs, ["std"], 2, True)
check(n == 0, "T2b: без зв'язку LFSR знайдено %d рішень -- третя умова не працює" % n)
# та сама пара, але зв'язок є -> знайдено (контроль для T2b)
sfs = L.parse_capture(L.synth_capture(0, 2, FW, seed=41, mis=[0x11223344, L.lfsr_next(0x11223344)]))
n, _ = quiet(L.run, sfs, ["std"], 2, True)
check(n == 1, "T2b контроль: зі зв'язком LFSR знайдено %d" % n)

# ---- формат rxdiag --cap -> парсер ----
raw = bytes([3, 12, 12, 0]) + bytes([1, 2, 3, 4, 5, 6] * 2) + bytes(rng.integers(0, 256, 12 * 27, dtype=np.uint8))
txt = rxdiag.format_cap(raw)
check(txt.startswith("# захоплення") and txt.count("\nseq=") == 12, "format_cap: 12 рядків seq=")
check(len(L.parse_capture(txt)) == 2, "парсер читає вивід rxdiag --cap")
check(len(L.parse_capture(rxdiag.format_cap(bytes([1, 5, 12, 0]) + bytes([1, 2, 3, 4, 5] + [0] * 7) + bytes(12 * 27)))) == 0, "5 burst-ів -> 0 суперфреймів")
check("УВАГА" in rxdiag.format_cap(bytes([2, 7, 12, 0]) + bytes(12 + 12 * 27)), "незавершене захоплення -> попередження")
# розрив seq: 1..6, 1..5,(втрачено 6)... -> другий суперфрейм не складається
lines = txt.splitlines()
broken = "\n".join(lines[:1] + lines[1:12] + [lines[12].replace("seq=6", "seq=2")])
check(len(L.parse_capture(broken)) == 1, "розрив seq: лишився 1 повний суперфрейм")
# порожній рядок між суперфреймами = розрив (LFSR-зв'язок не припускається)
split = "\n".join(lines[:7] + [""] + lines[7:])
sfs = L.parse_capture(split)
check(len(sfs) == 2 and not L.link_pairs(sfs), "порожній рядок між суперфреймами розриває зв'язок")

if fails:
    print("ПРОВАЛ test_le_bitsearch:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ok test_le_bitsearch")
