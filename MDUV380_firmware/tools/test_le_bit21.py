#!/usr/bin/env python3
"""AES-fix5 F2.5: тести tools/le_bit21.py.

 T0  деперемежування і FEC звірено на справжньому кадрі тиші (SILENCE_AUDIO, 9 байтів): таблиці однозначні, Golay-слова рядків 0/1 (з PN-маскою)
     дають нуль розбіжностей, [0][0] збігається з парністю -- інакше таблиці були б хибні;
 T1  вбудована самоперевірка (--selftest): знаходить обидві моделі (36 бітів на два суперфрейми у всіх розкладках; другий підставлений біт),
     F2.2 показує [0][0], шум і слова без зв'язку LFSR -> нічого, бітова помилка в другому слові -> --tol;
 T2  формат: 24-burst дамп (USB 0x89) -> rxdiag.format_cap -> парсер le_bitsearch -> 4 суперфрейми.
"""
import io, os, sys, contextlib
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import le_bit21 as B
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


# ---- T0 ----
SIL = bytes([0xB9, 0xE8, 0x81, 0x52, 0x61, 0x73, 0x00, 0x2A, 0x6B])
bits = [(SIL[i // 8] >> (7 - i % 8)) & 1 for i in range(72)]
f = B.frame_of(bits)
d0, d1 = B.analyse_frame(f)
check(not d0 and not d1, "кадр тиші: розбіжності рядка 0 %s, рядка 1 %s (мають бути порожні)" % (d0, d1))
check(len(set(B.CELL)) == 72, "таблиця деперемежування не взаємно однозначна")
rows = [sum(1 for (r, c) in B.CELL if r == k) for k in range(4)]
check(rows == [24, 23, 11, 14], "розміри рядків %s" % rows)
check(B.OTA[(0, 0)] == B.STUFF_OTA == 21, "ambe_fr[0][0] має бути ефірним бітом 21, а є %s" % B.OTA[(0, 0)])
# один перевернутий біт у Golay-слові рядка 0 має бути виявлений саме на своїй позиції
for pos in (21, 20, 0, 40):
    b2 = list(bits); b2[pos] ^= 1
    e0, e1 = B.analyse_frame(B.frame_of(b2))
    r, c = B.CELL[pos]
    ok = (r == 0 and (c in e0)) or (r == 1 and (c in e1)) or (r in (2, 3) and not e0 and not e1)
    check(ok, "збій ефірного біта %d -> (%d,%d): d0=%s d1=%s" % (pos, r, c, e0, e1))

# ---- T1 ----
ok, out = quiet(B.selftest)
check(ok, "selftest провалений:\n" + out)

# ---- T2 ----
import random
rnd = random.Random(5)
cap = 24
seqs = [(i % 6) + 1 for i in range(cap)]
payload = bytes(rnd.randrange(256) for _ in range(cap * 27))
data = bytes([3, cap, cap, 0]) + bytes(seqs) + payload
text = rxdiag.format_cap(data)
check(sum(1 for l in text.splitlines() if l.startswith("seq=")) == cap, "format_cap: кількість рядків seq= не дорівнює %d" % cap)
sfs = L.parse_capture(text)
check(len(sfs) == 4, "парсер: %d суперфреймів, треба 4" % len(sfs))

if fails:
    print("ПРОВАЛ:")
    for m in fails:
        print(" -", m)
    sys.exit(1)
print("test_le_bit21: ok")
