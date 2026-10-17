#!/usr/bin/env python3
"""AES-fix3: тест розбору дампу tools/rxdiag.py (print_dump / print_fix3) на синтетичному дампі.

Дамп збирається незалежно за розкладкою, описаною в dmrAesGetRxDiag() (application/source/crypto/dmr_aes_hook.c);
ту саму розкладку перевіряє C-тест tests/test_aes_rawdiag.c, тож розбіжність прошивки й розбору ловиться з одного з двох боків.
Перевіряється: сирий hex LC/EMB виводиться дослівно, «наші» байти теж, порожні кільця й дамп без fix3-блоку не падають,
а старі рядки (resync, TX-фаза) і таблиця подій досі друкуються (регресія: змінна `w` більше не затирається).
"""
import io, os, struct, sys, contextlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
import rxdiag  # noqa: E402

RING, REC, TRL = 24, 16, 66


def old_part(write_idx=2, with_pairs=True):
    d = bytearray(32 + RING * REC + TRL)
    d[0] = 0xA5; d[1] = RING; d[2] = REC; d[3] = TRL
    struct.pack_into("<H", d, 4, write_idx)
    # два події: PI (type 1) і RXEND (type 4)
    struct.pack_into("<BBBbHHII", d, 32 + 0 * REC, 1, 1, 0, -1, 1000, 0, 0x11223344, 0x11223344)
    struct.pack_into("<BBBbHHII", d, 32 + 1 * REC, 4, 1, 0, -1, 1500, 0, 0, 0)
    t = 32 + RING * REC
    struct.pack_into("<3H", d, t, 2, 1, 0)       # fix1
    d[t + 6] = 5
    struct.pack_into("<H", d, t + 8, 0)           # fix2: тихих burst-ів 0
    d[t + 10] = 0xFF; d[t + 11] = 0
    struct.pack_into("<3H", d, t + 12, 20, 24, 24)
    if with_pairs:
        for i in range(3):
            struct.pack_into("<H", d, t + 18 + 2 * i, 0x8000 | (i << 8) | i)
    return d


def fix3_part(lcs, embs, ours_key=1, ours_src=3):
    ring_lc = bytearray(8 * 20)
    for i, (dt, fl, hits, ts, tsl, lc) in enumerate(lcs):
        struct.pack_into("<BBBBHH", ring_lc, i * 20, dt, fl, hits, 0, ts, tsl)
        ring_lc[i * 20 + 8:i * 20 + 20] = bytes(lc)
    ring_emb = bytearray(8 * 8)
    for i, (dt, fl, ts, emb) in enumerate(embs):
        struct.pack_into("<BBH", ring_emb, i * 8, dt, fl, ts)
        ring_emb[i * 8 + 4:i * 8 + 8] = bytes(emb)
    f = bytearray(48)
    f[0] = 0xF3; f[1] = 8; f[2] = 20; f[3] = 8; f[4] = 8
    struct.pack_into("<H", f, 5, 48 + 160 + 64)
    f[7] = len(lcs); f[8] = len(embs)
    struct.pack_into("<4H", f, 9, 7, 4, 5, 3)
    f[17] = ours_key; f[18] = ours_src; f[19] = 1
    struct.pack_into("<I", f, 20, 0x11223344)
    f[24:31] = bytes([0x25, 0x10, ours_key, 0x11, 0x22, 0x33, 0x44])
    f[31:43] = bytes([0x00, 0x10, 0x40, 0x00, 0x00, 0x09, 0x30, 0x0D, 0x40, 0, 0, 0])
    f[43:47] = bytes([0x44, 0x42, 0x88, 0x81])
    return bytes(f) + bytes(ring_lc) + bytes(ring_emb)


def run(data):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rxdiag.print_dump(bytes(data), "TEST")
    return buf.getvalue()


fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


lc_a = [0x00, 0x10, 0x40, 0x00, 0x00, 0x09, 0x30, 0x0D, 0x40, 0, 0, 0]
lc_b = [0x25, 0x10, 0x01, 0xAA, 0xBB, 0xCC, 0xDD, 0, 0, 0, 0, 0]
out = run(bytes(old_part()) + fix3_part(
    [(1, 2, 1, 1100, 1300, lc_a), (0, 6, 0, 1200, 1200, lc_b)],
    [(6, 1, 2000, [0x44, 0x42, 0x88, 0x81]), (0, 0, 2100, [0, 0, 0, 0])]))
check("00 10 40 00 00 09 30 0D 40 00 00 00" in out, "сирий LC A не виведено дослівно")
check("25 10 01 AA BB CC DD 00 00 00 00 00" in out, "сирий LC B не виведено дослівно")
check("LC0: dT= 1 sc=2 PI=0 hits=  1 ts= 1100.. 1300" in out, "контекст LC0: " + out)
check("LC1: dT= 0 sc=2 PI=1 hits=  0 ts= 1200.. 1200" in out, "контекст LC1 (fl=6 -> sc=2, PI=1)")
check("EMB0: dT= 6 sc=1 ts= 2000   44 42 88 81" in out, "EMB0")
check("EMB1: dT= 0 sc=0 ts= 2100   00 00 00 00" in out, "EMB1")
check("PI  (dmr_pi_build)         : 25 10 01 11 22 33 44" in out, "наш PI")
check("Voice LC (клон TX)         : 00 10 40 00 00 09 30 0D 40 00 00 00" in out, "наш Voice LC")
check("EMB SB  (dmr_emb_sb_build) : 44 42 88 81" in out, "наш EMB SB")
check("за замовчуванням 1" in out and "MI=11223344" in out, "джерело ключа / MI")
check("усього CRC-валідних=7, повторів не внесено=4" in out and "читань=5, повторів не внесено=3" in out, "лічильники")
# регресія: старі секції досі на місці, а таблиця подій не зламана парами TX-фази
check("TX-фаза, кадр:" in out and "resync MI:" in out, "старі рядки зникли")
check(" 0 |  1000" in out and "PI" in out and "RXEND" in out, "таблиця подій зламана: " + out[:600])

# порожні кільця
out = run(bytes(old_part()) + fix3_part([], []))
check("CRC-валідного LC за цей час чип не віддавав" in out, "порожнє LC-кільце")
check("чип на RX не віддає ці регістри" in out, "порожнє EMB-кільце")

# обгортання: вільнобіжний індекс 10 -> найстаріший у слоті 2
lcs = [(1, 2, 0, 100 + i, 100 + i, [i] * 12) for i in range(8)]
d = bytearray(fix3_part(lcs, []))
d[7] = 10
out = run(bytes(old_part()) + bytes(d))
lines = [ln for ln in out.splitlines() if "LC" in ln and "dT=" in ln]
check(len(lines) == 8, "обгортання: рядків LC %d" % len(lines))
check(lines and lines[0].rstrip().endswith("02 02 02 02 02 02 02 02 02 02 02 02"), "обгортання: найстарішим мусить бути слот 2")

# старий дамп без fix3-блоку
out = run(old_part())
check("нема блоку сирих LC/EMB" in out, "дамп без fix3")

if fails:
    print("ПРОВАЛ test_rxdiag:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ok test_rxdiag")
