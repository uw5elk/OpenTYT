#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R64C: імена слотів AES-ключів у CPS (tools/stock_key_table.py) -- сумісність зі стоковою таблицею й збіг з прошивкою (functions/aes_key_name.c).
  * Python-кодування імені == кодування прошивки (випадкові імена в cp1251, довжини 0..16, усі літери української абетки) -- компілюється справжній aes_key_name.c;
  * rename_entry міняє ЛИШЕ поле імені (тип, ключ, pad -- ні на біт); порожнє ім'я = стандартне; слот без типу AES -- відмова;
  * імена зі стокової CPS (китайські, довгі) читаються без втрати; стандартне ім'я = «імені нема»;
  * сталі збігаються з dmr_aes_hook.c / aes_key_name.h;
  * мутанти на stock_key_table: кожен мусить провалити тест."""
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stock_key_table as skt  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, ".."))
SRC = os.path.join(ROOT, "application", "source", "crypto", "aes_key_name.c")
INC = os.path.join(ROOT, "application", "include")

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "functions/aes_key_name.h"
int main(void) {
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        char s[40]; uint8_t f[32]; char back[20];
        size_t n = strlen(line);
        while (n && (line[n-1] == '\n' || line[n-1] == '\r')) line[--n] = 0;
        memset(s, 0, sizeof s);
        for (size_t i = 0; i + 1 < n + 1 && i / 2 < 32 && (i + 1) < n + 0 + 1; i += 2) {
            if (i + 1 >= n + 0) break;
            char h[3] = { line[i], line[i+1], 0 };
            s[i / 2] = (char)strtol(h, NULL, 16);
        }
        unsigned len = aesNameToField(s, f);
        unsigned bl = aesNameFromField(f, back);
        printf("%u ", len);
        for (int i = 0; i < 32; i++) printf("%02x", f[i]);
        printf(" %u ", bl);
        for (unsigned i = 0; i < bl; i++) printf("%02x", (unsigned char)back[i]);
        printf("\n");
    }
    return 0;
}
'''


class Run:
    def __init__(self):
        self.n = 0
        self.fails = []

    def check(self, cond, text):
        self.n += 1
        if not cond:
            self.fails.append(text)


def build_harness(td):
    c = os.path.join(td, "h.c")
    with open(c, "w") as f:
        f.write(HARNESS)
    exe = os.path.join(td, "h")
    r = subprocess.run(["gcc", "-O1", "-DAES_KEY_NAME_HOST_TEST", "-I" + INC, c, SRC, "-o", exe], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return exe


def c_encode_many(exe, names_cp):
    inp = "".join(b.hex() + "\n" for b in names_cp)
    out = subprocess.run([exe], input=inp, capture_output=True, text=True, timeout=60).stdout.splitlines()
    res = []
    for line in out:
        parts = line.split(" ")
        res.append((int(parts[0]), bytes.fromhex(parts[1]), bytes.fromhex(parts[3]) if len(parts) > 3 else b""))
    return res


def suite_firmware_match(R, exe):
    rnd = random.Random(64)
    alphabet = [bytes([b]).decode("cp1251") for b in range(0x20, 256) if b != 0x98]
    uk = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯабвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
    names = ["", "Київ", "ЄІЇҐєіїґ", uk[:16], uk[-16:], "я" * 16, "а" * 16, "1", "12", "Key 3", "a b"]
    for _ in range(300):
        n = rnd.randint(0, 16)
        pool = alphabet if rnd.random() < 0.5 else list(uk)
        names.append("".join(rnd.choice(pool) for _ in range(n)))
    names = [nm.rstrip(" ") for nm in names]
    cps = [nm.encode("cp1251") for nm in names]
    got = c_encode_many(exe, cps)
    R.check(len(got) == len(names), "кількість відповідей прошивки: %d з %d" % (len(got), len(names)))
    bad = 0
    for nm, cp, (ln, field, back) in zip(names, cps, got):
        want = skt.encode_name(nm) if nm else bytes(32)
        if field != want or ln != len(nm) or back != cp:
            bad += 1
            if bad <= 3:
                R.fails.append("прошивка і CPS кодують ім'я %r по-різному: C=%s CPS=%s" % (nm, field.hex(), want.hex()))
    R.check(bad == 0, "збіг кодування імен прошивка == CPS на %d іменах (розбіжностей %d)" % (len(names), bad))
    # назад: CPS читає те, що записала прошивка
    R.check(all(skt.decode_name(f) == nm for nm, (_l, f, _b) in zip(names, got)), "CPS читає поля, записані прошивкою, назад у те саме ім'я")


def suite_entry(R):
    key = bytes(range(32))
    base = skt.build_entry(5, key)
    R.check(skt.decode_name(skt.parse_entry(base)[1]) == "5" and skt.is_default_name(5, skt.parse_entry(base)[1]), "N1: новий слот має стандартне ім'я «5» (= імені нема)")
    ren = skt.rename_entry(5, base, "Київ ЄІЇҐєіїґ")
    R.check(len(ren) == 100 and ren[:4] == base[:4] and ren[36:] == base[36:], "N2: rename_entry міняє лише поле імені (тип, ключ, pad -- ні на біт)")
    R.check(skt.decode_name(skt.parse_entry(ren)[1]) == "Київ ЄІЇҐєіїґ" and not skt.is_default_name(5, skt.parse_entry(ren)[1]), "N2: ім'я читається назад і вважається власним")
    R.check(skt.unwrap_key(skt.parse_entry(ren)[2]) == key, "N2: ключ після перейменування той самий")
    back = skt.rename_entry(5, ren, "")
    R.check(back == base, "N3: порожнє ім'я = стандартне: запис повернувся до початкового")
    R.check(skt.rename_entry(5, ren, "   ") == base, "N3: самі пробіли = стандартне")
    # перезапис ключа зберігає ім'я (як прошивка stockKeyWrite)
    key2 = bytes(reversed(range(32)))
    again = skt.build_entry(5, key2, existing_entry100=ren)
    R.check(skt.decode_name(skt.parse_entry(again)[1]) == "Київ ЄІЇҐєіїґ" and skt.unwrap_key(skt.parse_entry(again)[2]) == key2, "N4: новий ключ у слоті зберігає власне ім'я")
    # слот без типу AES -- відмова
    for bad_type in (0x00, 0xFF, 0x01):
        e = bytes([bad_type]) + base[1:]
        try:
            skt.rename_entry(5, e, "x")
            R.check(False, "N5: слот типу 0x%02X -- відмова" % bad_type)
        except ValueError:
            R.check(True, "")
    e7 = bytes([7]) + base[1:]
    R.check(skt.rename_entry(5, e7, "x")[0] == 7, "N5: тип 0x07 теж AES-256, тип зберігається")
    # довжина й символи
    R.check(skt.encode_name("а" * 16) == ("а" * 16).encode("utf-16-le"), "N6: 16 символів проходить, займає все поле")
    for bad in ("а" * 17, "a\x01b", "😀" * 9):
        try:
            skt.encode_name(bad)
            R.check(False, "N6: %r відхиляється" % bad)
        except ValueError:
            R.check(True, "")
    R.check(skt.encode_name("Київ   ") == skt.encode_name("Київ"), "N6: кінцеві пробіли відкидаються")
    # імена зі стокової CPS
    chinese = ("中文密钥" ).encode("utf-16-le").ljust(32, b"\x00")
    R.check(skt.decode_name(chinese) == "中文密钥" and not skt.is_default_name(5, chinese), "N7: китайське ім'я зі стоку читається без втрати")
    R.check(not skt.radio_representable("中文") and skt.radio_representable("Київ ЄІЇҐєіїґ"), "N7: що рація покаже без «?»")
    R.check(skt.decode_name(b"\xff" * 32) == "" and skt.is_default_name(3, b"\xff" * 32), "N7: стерте поле (FF) = імені нема")
    R.check(skt.decode_name(b"A\x00\x00\xd8B\x00" + bytes(26)).startswith("A?") , "N7: зіпсований сурогат -> «?»")
    R.check(skt.is_default_name(12, skt.default_name(12)) and not skt.is_default_name(2, skt.default_name(12)), "N7: стандартне «12» належить ключу 12")


def suite_constants(R):
    hook = open(os.path.join(ROOT, "application", "source", "crypto", "dmr_aes_hook.c"), encoding="utf-8").read()
    hdr = open(os.path.join(INC, "functions", "aes_key_name.h"), encoding="utf-8").read()
    R.check(re.search(r"#define\s+STOCK_KEY_NAME_OFF\s+4\b", hook) is not None and skt.STOCK_KEY_NAME_OFF == 4, "C1: зсув поля імені 4 у dmr_aes_hook.c і stock_key_table.py")
    R.check(re.search(r"#define\s+AESN_CHARS\s+16U", hdr) is not None and skt.NAME_CHARS == 16, "C1: 16 символів у aes_key_name.h і stock_key_table.py")
    R.check(re.search(r"#define\s+AESN_FIELD_LEN\s+32U", hdr) is not None, "C1: поле 32 байти")
    R.check(re.search(r"#define\s+STOCK_KEY_ENTRY_LEN\s+0x64", hook) is not None and skt.STOCK_KEY_ENTRY_LEN == 100, "C1: запис 100 байтів")
    R.check(re.search(r"dmrAesKeyNameSet.*?SPI_Flash_write\(stockKeyEntryAddr\(keyId\) \+ STOCK_KEY_NAME_OFF, want, AESN_FIELD_LEN\)", hook, re.S) is not None,
            "C2: прошивка пише лише 32 байти поля імені (зсув 4 запису слота)")


SUITES = (suite_entry, suite_constants)


def run_all(exe):
    R = Run()
    for s in SUITES:
        try:
            s(R)
        except Exception as e:  # noqa: BLE001
            R.fails.append("%s: виняток %s: %s" % (s.__name__, type(e).__name__, e))
    try:
        suite_firmware_match(R, exe)
    except Exception as e:  # noqa: BLE001
        R.fails.append("suite_firmware_match: виняток %s: %s" % (type(e).__name__, e))
    return R


def mutants():
    out = []

    def patch(name, new):
        def apply():
            old = getattr(skt, name)
            setattr(skt, name, new)
            return lambda: setattr(skt, name, old)
        return apply

    orig_rename = skt.rename_entry

    def rename_keep_default_bug(key_id, e, text):
        r = bytearray(orig_rename(key_id, e, text))
        r[1] ^= 0  # без змін
        return bytes(r)

    def rename_clobbers_key(key_id, e, text):
        r = bytearray(orig_rename(key_id, e, text))
        r[36] ^= 1
        return bytes(r)

    def rename_empty_zero(key_id, e, text):
        r = bytearray(orig_rename(key_id, e, text))
        if not text.strip(" "):
            r[4:36] = bytes(32)
        return bytes(r)

    def rename_any_type(key_id, e, text):
        t = bytearray(e)
        t[0] = 4
        return orig_rename(key_id, bytes(t), text)

    out.append(("rename: псує ключ", patch("rename_entry", rename_clobbers_key)))
    out.append(("rename: порожнє ім'я -> нулі, а не стандартне", patch("rename_entry", rename_empty_zero)))
    out.append(("rename: приймає слот без типу AES", patch("rename_entry", rename_any_type)))
    out.append(("encode_name: не обмежує довжину", patch("encode_name", lambda t: t.rstrip(" ").encode("utf-16-le").ljust(32, b"\x00")[:32] if len(t) <= 16 else t.encode("utf-16-le")[:32])))
    out.append(("encode_name: пробіли лишаються", patch("encode_name", lambda t: t.encode("utf-16-le").ljust(32, b"\x00"))))
    out.append(("decode_name: не зупиняється на FFFF", patch("decode_name", lambda n: bytes(n).decode("utf-16-le", errors="replace").split("\x00")[0])))
    out.append(("decode_name: більше 16 символів", patch("decode_name", lambda n: bytes(n).decode("utf-16-le", errors="replace").split("\x00")[0].replace("￿", ""))))
    out.append(("is_default_name: завжди False", patch("is_default_name", lambda k, n: False)))
    out.append(("is_default_name: завжди True", patch("is_default_name", lambda k, n: True)))
    out.append(("encode_name: кодує в cp1251", patch("encode_name", lambda t: t.rstrip(" ").encode("cp1251").ljust(32, b"\x00"))))
    return out


def main():
    with tempfile.TemporaryDirectory() as td:
        exe = build_harness(td)
        R = run_all(exe)
        for f in R.fails:
            print("ПРОВАЛ:", f)
        if R.fails:
            return 1
        muts = mutants()
        surv = []
        for name, apply in muts:
            restore = apply()
            try:
                M = run_all(exe)
            finally:
                restore()
            if not M.fails:
                surv.append(name)
        for s in surv:
            print("ПРОВАЛ: мутант вижив:", s)
        if surv:
            return 1
        print("test_r64: усе гаразд (%d перевірок; мутантів %d, усі вбито)." % (R.n, len(muts)))
        return 0


if __name__ == "__main__":
    sys.exit(main())
