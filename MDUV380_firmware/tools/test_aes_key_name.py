#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R64C: повна звірка перетворень імен ключів AES (application/source/crypto/aes_key_name.c) з Python cp1251:
  * усі 256 байтів: cp1251 -> Unicode (байт 0x98, якого нема в cp1251, і байти < 0x20 -> '?');
  * усі 65536 кодових одиниць Unicode: -> cp1251 (чого нема в cp1251 -> '?'; U+0000 -> 0);
  * мутанти: кожна одна зміна в aes_key_name.c мусить провалити звірку або C-тест.
Збирає C-тест хостовим gcc у тимчасовій теці. Запуск: python3 tools/test_aes_key_name.py"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "application", "source", "crypto", "aes_key_name.c")
TEST = os.path.join(ROOT, "tests", "test_aes_key_name.c")
INC = os.path.join(ROOT, "application", "include")


def build(src, td, name):
    exe = os.path.join(td, name)
    r = subprocess.run(["gcc", "-O1", "-Wall", "-Wextra", "-DAES_KEY_NAME_HOST_TEST", "-I" + INC, TEST, src, "-o", exe], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("збірка: " + r.stderr[-800:])
    return exe


def expected():
    b2u, u2b = {}, {}
    for b in range(256):
        try:
            u = ord(bytes([b]).decode("cp1251"))
        except UnicodeDecodeError:
            u = 0x3F
        if b < 0x20:
            u = 0x3F
        b2u[b] = u
    for u in range(65536):
        if u == 0:
            u2b[u] = 0
            continue
        try:
            c = chr(u).encode("cp1251")
            v = c[0] if c[0] >= 0x20 else 0x3F
        except UnicodeEncodeError:
            v = 0x3F
        u2b[u] = v
    return b2u, u2b


def compare(exe):
    out = subprocess.run([exe, "--dump"], capture_output=True, text=True, timeout=60).stdout.splitlines()
    b2u, u2b = expected()
    bad = []
    for line in out:
        k, a, v = line.split()
        a, v = int(a), int(v)
        if (b2u[a] if k == "B" else u2b[a]) != v:
            bad.append((k, a, v))
    return len(out), bad


def run_ctest(exe):
    r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return r.returncode == 0, r.stdout


def main():
    with tempfile.TemporaryDirectory() as td:
        exe = build(SRC, td, "orig")
        n, bad = compare(exe)
        ok, text = run_ctest(exe)
        if n != 256 + 65536 or bad or not ok:
            print("ПРОВАЛ: рядків %d, розбіжностей %d (перші: %s); C-тест %s" % (n, len(bad), bad[:5], "ok" if ok else "ПРОВАЛ\n" + text))
            return 1
        orig = open(SRC, encoding="utf-8").read()
        muts = [
            ("Ґ(0x490) не відображається", "0x0490", "0x0491", 1),
            ("0xC0 -> U+0411", "0x0410U + (b - 0xC0U)", "0x0411U + (b - 0xC0U)", 1),
            ("0x98 не '?'", "return (s_cp1251Hi[b - 0x80U] != 0U) ? s_cp1251Hi[b - 0x80U] : 0x003FU;", "return s_cp1251Hi[b - 0x80U];", 1),
            ("зворотна межа 0x044F -> 0x044E", "(u <= 0x044FU)", "(u <= 0x044EU)", 1),
            ("U+0000 -> '?'", "if (u == 0U)\n\t{\n\t\treturn 0U;\n\t}", "if (u == 0U)\n\t{\n\t\treturn (uint8_t)'?';\n\t}", 1),
            ("керівні < 0x20 пропускаються", "if (u < 0x20U)\n\t{\n\t\treturn (uint8_t)'?';\n\t}", "", 1),
            ("поле: довжина 17", "while (n < AESN_CHARS)\n\t{\n\t\tuint16_t u", "while (n < AESN_CHARS + 1U)\n\t{\n\t\tuint16_t u", 1),
            ("поле: U+FFFF не кінець", "if ((u == 0U) || (u == 0xFFFFU))", "if (u == 0U)", 1),
            ("поле: старший байт відкинуто", "field32[(i * 2U) + 1U] = (uint8_t)(u >> 8);", "field32[(i * 2U) + 1U] = 0U;", 1),
            ("поле: кінцеві пробіли лишаються", "while ((n > 0U) && (cp1251[n - 1U] == ' '))\n\t{\n\t\tn--;\n\t}", "", 1),
            ("поле: не обнуляється", "memset(field32, 0, AESN_FIELD_LEN);\n\n\tif (cp1251 == NULL)", "if (cp1251 == NULL)", 1),
            ("default: однозначне число для 12", "if (keyId >= 10U)", "if (keyId >= 20U)", 1),
            ("default: FF не порожнє", "|| ((field32[0] == 0xFFU) && (field32[1] == 0xFFU))", "", 1),
        ]
        surv = []
        for i, (name, old, new, cnt) in enumerate(muts):
            if orig.count(old) != cnt:
                print("ПРОВАЛ: у вихідному файлі мутант «%s» не знаходить фрагмент (%d входжень)" % (name, orig.count(old)))
                return 1
            p = os.path.join(td, "mut%d.c" % i)
            with open(p, "w", encoding="utf-8") as f:
                f.write(orig.replace(old, new))
            try:
                mexe = build(p, td, "mut%d" % i)
            except RuntimeError:
                continue   # мутант не збирається -- вбито
            _n, mbad = compare(mexe)
            mok, _t = run_ctest(mexe)
            if not mbad and mok:
                surv.append(name)
        if surv:
            for s in surv:
                print("ПРОВАЛ: мутант вижив:", s)
            return 1
        print("test_aes_key_name: усе гаразд (256 байтів + 65536 кодових одиниць звірено з Python cp1251; мутантів %d, усі вбито)." % len(muts))
        return 0


if __name__ == "__main__":
    sys.exit(main())
