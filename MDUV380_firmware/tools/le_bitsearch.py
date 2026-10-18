#!/usr/bin/env python3
"""AES-fix4 D2: офлайн-пошук ПОЗИЦІЙ бітів late-entry MI у сирих burst-ах стокової рації.
(AES-fix5: гіпотеза «MI у підставленому біті ambe_fr[0][0]» -- окремий інструмент tools/le_bit21.py.)

Вхід -- захоплення з `rxdiag.py --cap` (12 рядків `seq=<n> <27 байтів hex>`, два суперфрейми поспіль; можна й більше суперфреймів --
чим більше, тим однозначніша відповідь). Інструмент не знає й не припускає, де лежать біти: він шукає, які 4 біти кожного з 3 кодових
слів у 6 burst-ах суперфрейму складають слова Golay(24,12) з MI.

Модель (та сама, що в прошивці, dmr_le_mi_build / dmr_le_mi_decode): MI(32 біти) + CRC4 = 36 біт -> три слова Golay(24,12); слово j складається
з по 4 біти кожного з 6 burst-ів (vc 1..6): burst-и 1..3 дають 12 інформаційних біт, 4..6 -- 12 бітів парності. Невідомо ЛИШЕ звідки в 216-бітному
блоці чипа (27 байтів, біт 0 = старший біт байта 0) беруться ці 4 біти. Вони перебираються.

Критерій прийняття -- ТРИСТОРОННІЙ (випадковий набір позицій усі три умови не виконає):
  1. усі три слова Golay(24,12) декодуються в УСІХ суперфреймах (структурний пошук -- з виправленням до --tol помилок, вільний -- точно);
  2. CRC4 збігається в усіх суперфреймах;
  3. MI наступного суперфрейму == LFSR128d(MI попереднього) (суперфрейми поспіль). Це 32-бітна рівність: хибна відповідь має шанс ~2^-32.

Два рівні (структурний першим, бо стійкий до бітових помилок):
  СТРУКТУРНИЙ -- 4 позиції в межах 72-бітної групи (9 байтів = «кодове слово» чипа), ОДНАКОВІ в усіх трьох групах (група j -> слово Golay perm[j]),
                 усі 24 порядки бітів у ніблі, усі 6 перестановок груп, 4 порядки burst-ів у слові (--orders). Простір 72^4 = 26,9 млн кортежів, вектори numpy.
  ВІЛЬНИЙ     -- 4 позиції для КОЖНОГО слова будь-де в усіх 216 бітах (без припущень про групи); лише точний Golay, бо інакше випадкових
                 кандидатів надто багато. Метод: для 4 позицій синдром = A0[a]^A1[b]^A2[c]^A3[d] -- зустріч посередині (дві таблиці по 216^2).
Із --tol>0 поруч з істинним рішенням проходять «майже-рішення» (одна позиція замінена сусідньою, Golay «виправляє» різницю): звіт ставить першим те, де
виправлено НАЙМЕНШЕ біт, решту помічає як підозрілі; точність підтверджує повторний запуск з --tol 0 (на чистому прийомі) або більше суперфреймів.
Позиції з однаковими бітами в усьому захопленні (випадкові «двійники», ~216/4096 на біт при 12 burst-ах) нерозрізнювані -- звіт їх показує.
Якщо повного рішення нема, вільний рівень друкує «Golay-точні» кандидати однакової розкладки в трьох групах -- підказку, яку не слід приймати за відповідь.

Потрібен лише numpy. Час: структурний ~5-15 с на порядок burst-ів, вільний ~3-10 с (Android/Termux -- у кілька разів повільніше, все одно хвилини).

Запуск:
  python3 le_bitsearch.py cap.txt            # файл захоплення (або `-` / без аргументу: stdin)
  python3 le_bitsearch.py cap.txt --tol 1    # менше толерантності (швидше, менше хибних кандидатів)
  python3 le_bitsearch.py --selftest         # самоперевірка на синтетичних захопленнях (D2.5)
Код виходу: 0 -- знайдено, 1 -- не знайдено, 2 -- неправильний вхід.
"""
import argparse, itertools, sys, time
import numpy as np

# ---- таблиці Golay(24,12) з dmr_aes.c (LE_G, LE_H); звірка з C -- tools/test_le_bitsearch.py (золоті вектори) ----
_G = (
    '100000000000110001110101',
    '010000000000011000111011',
    '001000000000111101101000',
    '000100000000011110110100',
    '000010000000001111011010',
    '000001000000110110011001',
    '000000100000011011001101',
    '000000010000001101100111',
    '000000001000110111000110',
    '000000000100101010010111',
    '000000000010100100111110',
    '000000000001100011101011',
)
_H = (
    '101001001111100000000000',
    '111101101000010000000000',
    '011110110100001000000000',
    '001111011010000100000000',
    '000111101101000010000000',
    '101010111001000001000000',
    '111100010011000000100000',
    '110111000110000000010000',
    '011011100011000000001000',
    '100100111110000000000100',
    '010010011111000000000010',
    '110001110101000000000001',
)
G = [[int(ch) for ch in row] for row in _G]       # G[i][j]: інформаційний біт i -> вихідний біт j
H = [[int(ch) for ch in row] for row in _H]       # H[r][j]
COL = []                                           # COL[j] = стовпчик синдрому біта j слова (12 біт, рядок 0 = старший)
for _j in range(24):
    _c = 0
    for _r in range(12):
        _c |= H[_r][_j] << (11 - _r)
    COL.append(_c)

# firmware dmrAesRxLateEntry: слово j (= кодове слово чипа j) бере OTA-біти 71/67/63/59 своєї 72-бітної групи (MSB-first індекс)
FIRMWARE_TUPLE = (71, 67, 63, 59)
ORDERS = {                       # порядок burst-ів у слові: o-й блок слова бере burst order[o] суперфрейму (індекс 0 = vc 1)
    "std":      (0, 1, 2, 3, 4, 5),
    "swap":     (3, 4, 5, 0, 1, 2),
    "rev":      (5, 4, 3, 2, 1, 0),
    "revswap":  (2, 1, 0, 5, 4, 3),
}


# ---- порт dmr_aes.c: CRC4, LFSR128d, побудова/декодування late-entry слів ----
def crc4(mi32):
    buf = (mi32 & 0xFFFFFFFF) << 4
    for i in range(32):
        if (buf >> (35 - i)) & 1:
            buf ^= 0b10011 << (31 - i)
    return (buf & 0xF) ^ 0xF


def lfsr_next(mi):
    lfsr = mi & 0xFFFFFFFF
    nxt = 0
    for cnt in range(96):
        bit = ((lfsr >> 31) ^ (lfsr >> 21) ^ (lfsr >> 1) ^ lfsr) & 1
        lfsr = ((lfsr << 1) | bit) & 0xFFFFFFFFFFFFFFFF
        if cnt < 32:
            nxt = (nxt << 1) | bit
    return nxt


def golay_encode(info12):
    w = 0
    for j in range(24):
        s = 0
        for i in range(12):
            if (info12 >> (11 - i)) & 1:
                s ^= G[i][j]
        w = (w << 1) | s
    return w                                         # біт 23 = слово[0]


def build_words(mi):
    """MI -> три 24-бітні слова Golay (слово[0] = старший біт), як dmr_le_mi_build."""
    mi36 = ((mi & 0xFFFFFFFF) << 4) | crc4(mi)
    return [golay_encode((mi36 >> (24 - 12 * j)) & 0xFFF) for j in range(3)]


def build_frag(mi):
    """frag[vc 1..6][cw 0..2] -- ніблі, як dmr_le_mi_build (для золотих тестів і синтетичного захоплення)."""
    words = build_words(mi)
    return {vc: [(words[cw] >> (20 - 4 * (vc - 1))) & 0xF for cw in range(3)] for vc in range(1, 7)}


def _syn(w):
    s = 0
    for j in range(24):
        if (w >> (23 - j)) & 1:
            s ^= COL[j]
    return s


_FIX = {0: 0}
for _t in range(1, 4):
    for _pos in itertools.combinations(range(24), _t):
        _m = 0; _s = 0
        for _j in _pos:
            _m |= 1 << (23 - _j); _s ^= COL[_j]
        _FIX[_s] = _m


def golay_correct(w):
    """-> (виправлене слово, число виправлених біт) або None (>3 помилок)."""
    m = _FIX.get(_syn(w))
    if m is None:
        return None
    return w ^ m, bin(m).count("1")


def decode_mi(words):
    """три слова -> (mi, число виправлених) або None, якщо Golay/CRC4 не зійшлись."""
    mi36 = 0; err = 0
    for w in words:
        r = golay_correct(w)
        if r is None:
            return None
        mi36 = (mi36 << 12) | (r[0] >> 12); err += r[1]
    mi = mi36 >> 4
    if (mi36 & 0xF) != crc4(mi):
        return None
    return mi, err


# ---- вхід ----
def parse_capture(text):
    """-> список суперфреймів; кожен {'bits': ndarray(6,216) uint8, 'linked': bool (іде одразу за попереднім)}."""
    bursts = []          # (seq, bytes, brk) brk = перед рядком був порожній рядок/розрив
    brk = False
    for line in text.splitlines():
        t = line.strip()
        if not t:
            brk = True
            continue
        if t.startswith("#") or not t.lower().startswith("seq="):
            continue
        head, _, rest = t.partition(" ")
        try:
            seq = int(head.split("=", 1)[1])
            raw = bytes.fromhex(rest.replace(" ", ""))
        except ValueError:
            raise SystemExit("не розібрав рядок: %r" % t[:80])
        if len(raw) != 27:
            raise SystemExit("рядок має %d байтів, треба 27: %r" % (len(raw), t[:60]))
        bursts.append((seq, raw, brk))
        brk = False
    sfs = []
    i = 0
    while i + 6 <= len(bursts):
        grp = bursts[i:i + 6]
        if [g[0] for g in grp] == [1, 2, 3, 4, 5, 6] and not any(g[2] for g in grp[1:]):
            bits = np.stack([np.unpackbits(np.frombuffer(g[1], dtype=np.uint8)) for g in grp])
            sfs.append({"bits": bits, "linked": bool(sfs) and not grp[0][2] and i > 0})
            i += 6
        else:
            i += 1
    return sfs


def link_pairs(sfs):
    return [(s - 1, s) for s in range(1, len(sfs)) if sfs[s]["linked"]]


# ---- допоміжне для пошуку ----
def _pass_table(tol):
    t = np.zeros(4096, dtype=bool)
    for s, m in _FIX.items():
        if bin(m).count("1") <= tol:
            t[s] = True
    return t


def _acols(bits, order, lo, hi):
    """A[k][p] (k=0..3, p по [lo,hi)): синдромний внесок позиції p, якщо вона k-й біт ніблів слова: XOR по 6 burst-ах слова."""
    X = bits[list(order)][:, lo:hi].astype(np.uint16)                      # (6, n)
    out = []
    for k in range(4):
        hk = np.array([COL[4 * o + k] for o in range(6)], dtype=np.uint16)[:, None]
        out.append(np.bitwise_xor.reduce(X * hk, axis=0).astype(np.uint16))
    return out


def _nibbles(bits, order, tup):
    """значення 24-бітного слова для кортежу позицій tup (4 позиції, k=0 -- старший біт ніблу)."""
    w = 0
    for o in range(6):
        for k in range(4):
            w = (w << 1) | int(bits[order[o]][tup[k]])
    return w


def _score_tail(sfs, order, tups, perm, tol):
    """tups[g] -- кортеж позицій слова, що лежить у групі/слові j=perm... повертає (mis, err) або None; тристоронній тест."""
    mis = []; errs = 0
    for sf in sfs:
        words = [_nibbles(sf["bits"], order, tup) for tup in tups]
        r = decode_mi(words)
        if r is None:
            return None
        if r[1] > tol * 3:
            return None
        mis.append(r[0]); errs += r[1]
    return mis, errs


def _relation(mis, pairs):
    """-> 'next'/'same'/'prev' якщо ВСІ пари підпорядковуються одному відношенню, інакше None; None й без пар (нема що перевіряти)."""
    if not pairs:
        return None
    for name, f in (("next", lambda a, b: b == lfsr_next(a)), ("same", lambda a, b: a == b), ("prev", lambda a, b: a == lfsr_next(b))):
        if all(f(mis[a], mis[b]) for a, b in pairs):
            return name
    return None


# ---- СТРУКТУРНИЙ пошук ----
def structured(sfs, orders, tol, log):
    pairs = link_pairs(sfs)
    valid = _pass_table(tol)
    found = []
    ng = 3
    for oname in orders:
        order = ORDERS[oname]
        t0 = time.time()
        # words[(g, s)] = A0..A3 по 72 позиціях групи g суперфрейму s
        words = [[_acols(sf["bits"], order, 72 * g, 72 * g + 72) for sf in sfs] for g in range(ng)]
        flat = [w for g in range(ng) for w in words[g]]
        w0 = flat[0]
        pcd = (w0[2][:, None] ^ w0[3][None, :]).reshape(-1)                  # (c,d) -> 5184
        cand = []
        for a0 in range(0, 72, 6):
            a = np.arange(a0, min(a0 + 6, 72))
            pab = w0[0][a][:, None] ^ w0[1][None, :]                          # (ca,72)
            syn = pab[:, :, None] ^ pcd[None, None, :]                        # (ca,72,5184)
            ia, ib, icd = np.nonzero(valid[syn])
            if ia.size == 0:
                continue
            aa = a[ia]; bb = ib; cc = icd // 72; dd = icd % 72
            ok = np.ones(aa.size, dtype=bool)
            for w in flat[1:]:
                s = w[0][aa] ^ w[1][bb] ^ w[2][cc] ^ w[3][dd]
                ok &= valid[s]
                if not ok.any():
                    break
            else:
                for x in zip(aa[ok], bb[ok], cc[ok], dd[ok]):
                    if len(set(x)) == 4:
                        cand.append(tuple(int(v) for v in x))
        log("   порядок burst-ів %-8s кандидатів за Golay(tol=%d) у всіх %d словах: %d  (%.1f с)" % (oname, tol, len(flat), len(cand), time.time() - t0))
        for tup in cand:
            for perm in itertools.permutations(range(ng)):
                tups = [tuple(72 * perm[j] + p for p in tup) for j in range(ng)]      # слово j бере групу perm[j]
                r = _score_tail(sfs, order, tups, perm, tol)
                if r is None:
                    continue
                mis, errs = r
                rel = _relation(mis, pairs)
                if pairs and rel is None:
                    continue
                found.append({"tier": "structured", "order": oname, "tups": tups, "perm": perm, "mis": mis, "errs": errs, "rel": rel,
                              "nopairs": not pairs})
    return found


# ---- ВІЛЬНИЙ пошук (точний Golay) ----
def free(sfs, orders, log, maxcand=4000):
    pairs = link_pairs(sfs)
    found = []; hints = []
    for oname in orders:
        order = ORDERS[oname]
        t0 = time.time()
        A = [_acols(sf["bits"], order, 0, 216) for sf in sfs]
        a0 = A[0]
        p1 = (a0[0][:, None] ^ a0[1][None, :]).reshape(-1)
        p2 = (a0[2][:, None] ^ a0[3][None, :]).reshape(-1)
        srt = np.argsort(p2, kind="stable")
        p2s = p2[srt]
        left = np.searchsorted(p2s, p1, side="left"); right = np.searchsorted(p2s, p1, side="right")
        cnt = right - left
        tot = int(cnt.sum())
        i1 = np.repeat(np.arange(p1.size), cnt)
        base = np.repeat(np.cumsum(cnt) - cnt, cnt)
        i2 = srt[np.arange(tot) - base + np.repeat(left, cnt)]
        a, b, c, d = i1 // 216, i1 % 216, i2 // 216, i2 % 216
        ok = (a != b) & (a != c) & (a != d) & (b != c) & (b != d) & (c != d)
        for Ak in A[1:]:
            ok &= (Ak[0][a] ^ Ak[1][b] ^ Ak[2][c] ^ Ak[3][d]) == 0
        a, b, c, d = a[ok], b[ok], c[ok], d[ok]
        n = a.size
        log("   порядок burst-ів %-8s точних Golay-слів у всіх %d суперфреймах: %d  (%.1f с)" % (oname, len(sfs), n, time.time() - t0))
        if n < 3:
            continue
        if n > maxcand:
            log("   ! надто багато кандидатів (%d > %d) -- ймовірно, майже сталі біти у вході; відсічено" % (n, maxcand))
            continue
        info = []                                   # info[s][cand] -- 12 інформаційних біт (burst-и order[0..2])
        for sf in sfs:
            X = sf["bits"].astype(np.uint32)
            v = np.zeros(n, dtype=np.uint32)
            for o in range(3):
                bb = X[order[o]]
                nib = (bb[a] << 3) | (bb[b] << 2) | (bb[c] << 1) | bb[d]
                v = (v << 4) | nib
            info.append(v)
        pos = np.stack([a, b, c, d], axis=1)
        # ординарні трійки (слово 0, слово 1, слово 2); позиції всіх 12 бітів різні
        idx = np.arange(n)
        I, J, K = np.meshgrid(idx, idx, idx, indexing="ij")
        I = I.reshape(-1); J = J.reshape(-1); K = K.reshape(-1)
        keep = (I != J) & (I != K) & (J != K)
        I, J, K = I[keep], J[keep], K[keep]
        okd = np.ones(I.size, dtype=bool)
        for q in range(4):
            for r in range(4):
                okd &= pos[I, q] != pos[J, r]
                okd &= pos[I, q] != pos[K, r]
                okd &= pos[J, q] != pos[K, r]
        I, J, K = I[okd], J[okd], K[okd]
        crc_ok = np.ones(I.size, dtype=bool)
        mi36s = []
        for s in range(len(sfs)):
            m36 = (info[s][I].astype(np.uint64) << 24) | (info[s][J].astype(np.uint64) << 12) | info[s][K].astype(np.uint64)
            mi36s.append(m36)
            buf = (m36 >> np.uint64(4)) << np.uint64(4)   # MI<<4: ділимо без самого CRC, як crc4()
            for i in range(32):
                bit = (buf >> np.uint64(35 - i)) & np.uint64(1)
                buf ^= bit * np.uint64(0b10011 << (31 - i))
            crc_ok &= ((buf & np.uint64(0xF)) ^ np.uint64(0xF)) == (m36 & np.uint64(0xF))
        sel = np.nonzero(crc_ok)[0]
        log("      трійок слів: %d, з CRC4 у всіх суперфреймах: %d" % (I.size, sel.size))
        for q in sel:
            mis = [int(m36[q] >> np.uint64(4)) for m36 in mi36s]
            rel = _relation(mis, pairs)
            if pairs and rel is None:
                continue
            tups = [tuple(int(v) for v in pos[x]) for x in (I[q], J[q], K[q])]
            found.append({"tier": "free", "order": oname, "tups": tups, "perm": None, "mis": mis, "errs": 0, "rel": rel, "nopairs": not pairs})
        # підказка: Golay-точні кандидати з ОДНАКОВИМИ зсувами в межах однієї 72-бітної групи
        byoff = {}
        for x in range(n):
            t = tuple(int(v) for v in pos[x])
            if len({p // 72 for p in t}) == 1:
                byoff.setdefault(tuple(p % 72 for p in t), set()).add(t[0] // 72)
        for off, groups in byoff.items():
            if len(groups) == 3:
                hints.append((oname, off))
    return found, hints


# ---- звіт ----
def fmt_pos(p):
    return "%3d (байт %2d, біт %d [7=старший], група %d зсув %2d)" % (p, p // 8, 7 - p % 8, p // 72, p % 72)


def sigids(sfs):
    """id «підпису» кожної з 216 позицій: позиції з ОДНАКОВИМИ бітами в усіх burst-ах захоплення неможливо розрізнити. 12 burst-ів дають
    лише 12-бітний підпис, тож випадкові двійники трапляються (216/4096 на біт) -- тому відповідь тим однозначніша, чим більше суперфреймів."""
    cols = np.concatenate([sf["bits"] for sf in sfs], axis=0)          # (6*N, 216)
    ids = {}; out = []
    for p in range(216):
        out.append(ids.setdefault(cols[:, p].tobytes(), len(ids)))
    return out


def report(found, label, out, sfs):
    sid = sigids(sfs)
    twins = {}
    for p in range(216):
        twins.setdefault(sid[p], []).append(p)
    fw = [tuple(72 * j + p for p in FIRMWARE_TUPLE) for j in range(3)]
    fwkey = tuple(tuple(sid[p] for p in t) for t in fw)
    groups = {}
    for f in found:
        key = (f["order"], tuple(tuple(sid[p] for p in t) for t in f["tups"]))
        groups.setdefault(key, []).append(f)
    # Із толерантністю до помилок поруч з істинними позиціями проходять «майже-рішення» (одна позиція замінена сусідньою, Golay «виправляє» різницю
    # і MI виходить той самий). Тому першим іде рішення з НАЙМЕНШОЮ кількістю виправлених помилок; решта -- підозрілі, бо гірші на ту саму суму.
    items = sorted(groups.items(), key=lambda kv: (min(x["errs"] for x in kv[1]), kv[0][0]))
    best = min((min(x["errs"] for x in fs) for _, fs in items), default=0)
    n = 0
    for (oname, key), fs in items:
        f = min(fs, key=lambda x: x["errs"])
        primary = f["errs"] == best
        if primary:
            n += 1
        out("\n=== %s (%s) порядок burst-ів у слові=%s, помилок виправлено=%d%s" % (
            ("ЗНАЙДЕНО #%d" % n) if primary else "ПІДОЗРІЛЕ майже-рішення (гірше за найкраще на %d виправлених біт; ймовірно хибна заміна однієї позиції)" % (f["errs"] - best),
            label, oname, f["errs"], "" if not f["nopairs"] else "  (!) суперфрейми не поспіль -- умову 3 (LFSR) не перевірено"))
        for j, t in enumerate(f["tups"]):
            out("  слово Golay %d (4 біти ніблу, від старшого): %s" % (j, " ".join("%d" % p for p in t)))
            for k, p in enumerate(t):
                tw = [q for q in twins[sid[p]] if q != p]
                out("      біт ніблу %d <- %s%s" % (3 - k, fmt_pos(p), ("   [двійники з тими самими бітами в захопленні: %s]" % tw) if tw else ""))
        for s, mi in enumerate(f["mis"]):
            out("  MI суперфрейму %d: %08X" % (s, mi))
        out("  відношення MI між суперфреймами поспіль: %s" % (
            {"next": "MI[n+1] == LFSR128d(MI[n])  (очікувано)", "same": "MI не змінюється (!)", "prev": "навпаки: MI[n] == LFSR128d(MI[n+1]) (!)", None: "нема що перевіряти"}[f["rel"]]))
        same = (key == fwkey) and oname == "std"
        out("  ПОТОЧНА схема прошивки (слово j: 72j+71, 72j+67, 72j+63, 72j+59, burst-и 1..6): %s" % (
            "ЗБІГАЄТЬСЯ -- позиції в прошивці правильні, шукай причину деінде" if same else "ВІДРІЗНЯЄТЬСЯ -- позиції в прошивці хибні"))
        if len(fs) > 1:
            out("  (ще %d записів з тими самими бітами, відрізняються лише вибором двійників)" % (len(fs) - 1))
    return n


def run(sfs, orders, tol, do_free, out=print):
    out("суперфреймів у захопленні: %d, пар поспіль: %d" % (len(sfs), len(link_pairs(sfs))))
    t0 = time.time()
    out("--- СТРУКТУРНИЙ пошук (позиції в 72-бітній групі, однакові в трьох групах; толерантність до помилок Golay: до %d біт на слово) ---" % tol)
    f1 = structured(sfs, orders, tol, out)
    n = report(f1, "структурний", out, sfs)
    f2 = []; hints = []
    if n == 0 and do_free:
        out("--- ВІЛЬНИЙ пошук (4 позиції для кожного слова будь-де у 216 бітах; лише точний Golay) ---")
        f2, hints = free(sfs, orders, out)
        n = report(f2, "вільний", out, sfs)
        if n == 0 and hints:
            out("\nПІДКАЗКА (НЕ відповідь): Golay-точні кандидати однакової розкладки у всіх трьох групах, але CRC4/LFSR не зійшлись:")
            for oname, off in hints[:10]:
                out("   порядок %s, зсуви в групі: %s" % (oname, off))
    out("\nчас: %.1f с" % (time.time() - t0))
    if n == 0:
        out("НЕ ЗНАЙДЕНО. Це не доводить, що біти не в буфері чипа: можливі помилки у вході, інший склад слів (див. docs у шапці), або LE взагалі не в цих бітах.")
    return n


# ---- синтетичне захоплення (D2.5) ----
def synth_capture(mi1, nsf, tups, order=ORDERS["std"], seed=1, flips=0, mis=None):
    """burst-и: випадкові 216 біт, у позиції tups[j] кладуться ніблі слова j. tups[j] -- 4 позиції (k=0 -- старший біт).
    flips -- скільки біт на слово перевернути (випадкові з 24 біт слова); mis -- явні MI по суперфреймах. -> текст у форматі rxdiag --cap."""
    rng = np.random.default_rng(seed)
    lines = []
    mi = mi1
    for s in range(nsf):
        if mis is not None:
            mi = mis[s]                 # явні MI суперфреймів (для негативного тесту: без зв'язку LFSR)
        bits = rng.integers(0, 2, size=(6, 216), dtype=np.uint8)
        words = build_words(mi)
        for j in range(3):
            w = words[j]
            if flips:
                for pbit in rng.choice(24, size=flips, replace=False):
                    w ^= 1 << (23 - int(pbit))
            for o in range(6):
                nib = (w >> (20 - 4 * o)) & 0xF
                for k in range(4):
                    bits[order[o]][tups[j][k]] = (nib >> (3 - k)) & 1
        for v in range(6):
            lines.append("seq=%d %s" % (v + 1, np.packbits(bits[v]).tobytes().hex().upper()))
        mi = lfsr_next(mi)
    return "\n".join(lines) + "\n"


def solutions(found, sfs):
    """-> множина канонічних рішень (порядок, підписи позицій по словах) -- двійники не множать рішення."""
    sid = sigids(sfs)
    return {(f["order"], tuple(tuple(sid[p] for p in t) for t in f["tups"])) for f in found}


def selftest(out=print):
    fw = [tuple(72 * j + p for p in FIRMWARE_TUPLE) for j in range(3)]
    ok = True
    for nsf in (2, 4):
        sfs = parse_capture(synth_capture(0x11223344, nsf, fw, seed=nsf))
        sid = sigids(sfs)
        want = ("std", tuple(tuple(sid[p] for p in t) for t in fw))
        f = structured(sfs, ["std"], 2, lambda *_: None)
        r = solutions(f, sfs) == {want}
        out("самоперевірка 1 (наша схема, %d суперфрейми, структурний): %s" % (nsf, "ok" if r else "ПРОВАЛ"))
        ok &= r
        f, _ = free(sfs, ["std"], lambda *_: None)
        r = solutions(f, sfs) == {want}
        out("самоперевірка 1 (наша схема, %d суперфрейми, вільний):     %s" % (nsf, "ok" if r else "ПРОВАЛ"))
        ok &= r
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", default="-", help="захоплення (rxdiag.py --cap); `-` -- stdin")
    ap.add_argument("--tol", type=int, default=2, choices=(0, 1, 2), help="скільки помилок на слово Golay терпіти у структурному пошуку (типово 2)")
    ap.add_argument("--orders", default="std,swap,rev,revswap", help="порядки burst-ів у слові через кому (типово всі 4)")
    ap.add_argument("--no-free", action="store_true", help="лише структурний рівень")
    ap.add_argument("--selftest", action="store_true", help="самоперевірка на синтетичному захопленні")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(0 if selftest() else 1)
    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    sfs = parse_capture(text)
    if len(sfs) < 2:
        print("потрібно щонайменше 2 повні суперфрейми (seq 1..6 поспіль) -- знайдено %d. Перезніми захоплення: rxdiag.py --arm, передача, rxdiag.py --cap" % len(sfs), file=sys.stderr)
        sys.exit(2)
    orders = [o for o in args.orders.split(",") if o]
    for o in orders:
        if o not in ORDERS:
            print("невідомий порядок %r (є: %s)" % (o, ",".join(ORDERS)), file=sys.stderr)
            sys.exit(2)
    n = run(sfs, orders, args.tol, not args.no_free)
    sys.exit(0 if n else 1)


if __name__ == "__main__":
    main()
