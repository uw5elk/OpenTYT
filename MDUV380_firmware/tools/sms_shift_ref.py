#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Еталон вибору читання тексту SMS (ui5b): правильний UTF-16LE чи «зсунутий» від Z3DMR.

Той самий алгоритм, що й dmr_sms_text_from_plaintext() у application/source/crypto/dmr_aes.c
(під ENABLE_AES), і той самий генератор випадкових фраз (xorshift32, seed 1), що й
tests/test_dmr_sms_shift.c -- щоб розбіжність між C і Python одразу було видно.

Z3DMR (через стокову рацію) кладе старший байт символу k у pdu[37 + 2k], а не в pdu[39 + 2k]
(UTF-16BE з байта 37; claude/sms-protocol.md, розділ 7). Два читання символу на позиції i
(текст з байта 38 до кінця IP-пакета):
    правильне: u = pdu[i] | pdu[i+1] << 8
    зсунуте:   u = pdu[i] | pdu[i-1] << 8
Правило а): pdu[34..36] == 0D 00 0A і pdu[37] != 0 -> зсунуте безумовно.
Правило б): інакше зсунуте, лише якщо cost(зсунуте) СТРОГО менший за cost(правильне).

Запуск:
    python3 MDUV380_firmware/tools/sms_shift_ref.py          # фіксовані рядки + 3000 фраз
    python3 MDUV380_firmware/tools/sms_shift_ref.py --show N # перші N згенерованих фраз
Код виходу 1, якщо хоч одна фраза прочиталась не так.
"""
import sys

# ---------------------------------------------------------------- класи символів
S, B, D, L, C, O = 'S', 'B', 'D', 'L', 'C', 'O'
C_EXTRA = {0x401, 0x451, 0x404, 0x454, 0x406, 0x456, 0x407, 0x457, 0x40E, 0x45E, 0x490, 0x491}
LOWER_EXTRA = {0x451, 0x454, 0x456, 0x457, 0x45E, 0x491}
UPPER_EXTRA = {0x401, 0x404, 0x406, 0x407, 0x40E, 0x490}
RUSSIAN = {0x44B, 0x44D, 0x44A, 0x451, 0x42B, 0x42D, 0x42A, 0x401}   # ы э ъ ё Ы Э Ъ Ё


def to_cp1251(u):
    """Як dmrSmsUcs2ToCp1251(): '?' для того, чого в cp1251 немає; керівні -> пробіл."""
    if u == 0:
        return 0
    if u < 0x20:
        return 0x20
    if u == 0x7F:
        return 0x3F
    try:
        return chr(u).encode('cp1251')[0]
    except UnicodeEncodeError:
        return 0x3F


def cls(u):
    if u == 0x20:
        return S
    if u < 0x20 or 0x7F <= u <= 0x9F or (u != 0x3F and to_cp1251(u) == 0x3F):
        return B
    if 0x30 <= u <= 0x39:
        return D
    if 0x41 <= u <= 0x5A or 0x61 <= u <= 0x7A:
        return L
    if 0x410 <= u <= 0x44F or u in C_EXTRA:
        return C
    return O


def is_lower(u):
    return 0x61 <= u <= 0x7A or 0x430 <= u <= 0x44F or u in LOWER_EXTRA


def is_upper(u):
    return 0x41 <= u <= 0x5A or 0x410 <= u <= 0x42F or u in UPPER_EXTRA


def cost(seq):
    c = 0
    for u in seq:
        if cls(u) == B:
            c += 3
        if u in RUSSIAN:
            c += 1
    for x, y in zip(seq, seq[1:]):
        cx, cy = cls(x), cls(y)
        if cx != cy and cx != S and cy != S:
            c += 1
        if is_lower(x) and is_upper(y):
            c += 1
        if cx == C and y in (0x3C, 0x3D, 0x3E, 0x40):   # < = > @
            c += 1
    if len(seq) >= 2 and cls(seq[-2]) == C and cls(seq[-1]) in (L, D):
        c += 2
    # ui5b, ДОДАТКОВО до брифу: +1 за пробіл на початку тексту або одразу після пробілу.
    # «Р» (U+0420) після символу зі старшим байтом 00 (початок, латиниця, цифра, пробіл, знак)
    # у зсунутому читанні правильного тексту стає пробілом, а знак після кириличного слова --
    # літерою (? -> п, : -> к), і зникають два переходи класів: «Рація?» -> « аціяп». Без цього
    # доданку такі фрази (і seed 1, фраза #2912) читались як зсунуті.
    for k, u in enumerate(seq):
        if u == 0x20 and (k == 0 or seq[k - 1] == 0x20):
            c += 1
    return c


def reading(pdu, tend, shifted):
    return [pdu[i] | ((pdu[i - 1] if shifted else pdu[i + 1]) << 8) for i in range(38, tend - 1, 2)]


def decode(pdu):
    """Текст cp1251 (bytes), як його покаже рація."""
    tend = min((pdu[2] << 8) | pdu[3], len(pdu))
    shifted = False
    if tend > 39:
        if pdu[34] == 0x0D and pdu[35] == 0 and pdu[36] == 0x0A and pdu[37] != 0:
            shifted = True
        elif cost(reading(pdu, tend, True)) < cost(reading(pdu, tend, False)):
            shifted = True
    out = bytearray()
    for u in reading(pdu, tend, shifted):
        b = to_cp1251(u)
        if b:
            out.append(b)
    return bytes(out)


# ---------------------------------------------------------------- PDU
def build_pdu(text, shifted):
    """Мінімальний IPv4/UDP/TMS (лише те, що читає декодер): текст -- str."""
    units = [ord(ch) for ch in text]
    body = bytearray()
    if not shifted:
        body.extend(b'\x0d\x00\x0a\x00')
        for u in units:
            body += bytes((u & 0xFF, u >> 8))
    else:
        # UTF-16BE з байта 37: LF = 0A у pdu[36], старший байт першого символу -- pdu[37];
        # сирітський байт у кінці = 00.
        body.extend(b'\x0d\x00\x0a')
        for u in units:
            body += bytes((u >> 8, u & 0xFF))
        body.append(0)
    pdu = bytearray(34) + body
    pdu[0] = 0x45
    pdu[9] = 0x11
    pdu[2] = len(pdu) >> 8
    pdu[3] = len(pdu) & 0xFF
    return bytes(pdu)


# ---------------------------------------------------------------- генератор фраз (як у C)
class Rng:
    """xorshift32 -- той самий, що в tests/test_dmr_sms_shift.c."""
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def next(self):
        x = self.s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.s = x
        return x

    def below(self, n):
        return self.next() % n


UA_WORDS = ['привіт', 'добре', 'дякую', 'як', 'справи', 'їжак', 'ґанок', 'є', 'щось', 'зв\'язок',
            'прийом', 'чую', 'тебе', 'добрий', 'день', 'вечір', 'буду', 'на', 'місці', 'через',
            'хвилин', 'канал', 'рація', 'батарея', 'сідає', 'їду', 'додому', 'все', 'гаразд',
            'юнак', 'яблуко', 'шлях', 'ціль', 'фото', 'тиша', 'перевірка', 'сигнал', 'слабкий',
            'Богдан', 'Київ', 'Львів', 'Україна', 'Ірина', 'Євген', 'Їжакевич', 'Ґудзь', 'ок']
EN_WORDS = ['hello', 'ok', 'yes', 'no', 'copy', 'roger', 'test', 'radio', 'check', 'good',
            'morning', 'net', 'qsl', 'qth', 'rst', 'dmr', 'Hi', 'OK', 'QSL', 'DMR', 'CQ', 'TNX', 'GM']
CALLS = ['UW5ELK', 'UR5EQF', 'UT7UA', 'US0IZ', 'DL1ABC', 'EM3XYZ', 'UX1UA', 'UR3QTW']
PUNCT = ',.!?:)'


def phrase(r):
    words = []
    for k in range(1 + r.below(6)):
        t = r.below(10)
        if t < 5:
            w = UA_WORDS[r.below(len(UA_WORDS))]
            if k == 0 and r.below(2):
                w = w[0].upper() + w[1:]
        elif t < 7:
            w = EN_WORDS[r.below(len(EN_WORDS))]
        elif t < 8:
            w = CALLS[r.below(len(CALLS))]
        else:
            w = str(r.below(100000))
        if r.below(4) == 0:
            w += PUNCT[r.below(len(PUNCT))]
        words.append(w)
    return ' '.join(words)


FIXED = ['а', 'т', 'Ґ', 'ааааа', 'абв', 'OKдобре', '1добре', 'тест123', 'DMRка', 'добре!', 'добре)',
         'Hi,привіт', 'OK, добре', 'Hi, Богдан!', 'Привіт, як справи?', 'добре дякую',
         'Привіт іІєЄїЇґҐ', '73!', 'QSL?', 'Hello', 'ok', '2550213']


def phrases_hash(count=3000, seed=1):
    """FNV-1a усіх фраз у cp1251, кожна з '\\n' -- C-тест порівнює зі своїм, щоб фрази збігались."""
    h = 0x811C9DC5
    r = Rng(seed)
    for _ in range(count):
        for b in phrase(r).encode('cp1251') + b'\n':
            h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def check(text):
    want = text.encode('cp1251')
    bad = []
    for sh in (False, True):
        got = decode(build_pdu(text, sh))
        if got != want:
            bad.append((sh, got.decode('cp1251', errors='replace')))
    return bad


def main():
    if '--show' in sys.argv:
        r = Rng(1)
        for _ in range(int(sys.argv[sys.argv.index('--show') + 1])):
            print(phrase(r))
        return 0
    fails = 0
    for t in FIXED:
        for sh, got in check(t):
            fails += 1
            print('ПРОВАЛ (%s) %r -> %r' % ('зсунутий' if sh else 'правильний', t, got))
    r = Rng(1)
    for n in range(3000):
        t = phrase(r)
        for sh, got in check(t):
            fails += 1
            print('ПРОВАЛ #%d (%s) %r -> %r' % (n, 'зсунутий' if sh else 'правильний', t, got))
    print('фіксованих %d, випадкових 3000 (обидва кодування): провалів %d' % (len(FIXED), fails))
    print('FNV-1a 3000 фраз (cp1251, через \\n): 0x%08X' % phrases_hash())
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
