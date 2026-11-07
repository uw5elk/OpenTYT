#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R65B: редактор списків прийому на рації -- сумісність з CPS у обидва боки + ширини рядків.

B1  прошивка (справжній codeplug.c, хост) створила «Київ» (7,8,9) і «Зоря» (кінець 0xFF -> хвіст 0x00); CPS-код (cps_csv.Image / table_edit.tg_lists)
    бачить обидва списки з тими самими назвами й складом; довжини в таблиці = к-сть контактів;
B2  записи, зібрані CPS-кодом (назва pad16, склад <H + нулі до 64 байтів, set_group), прошивка читає так само, як СТОКОВИЙ codeplugRxGroupGetDataForIndex;
B3  ширини: рядки рядків меню/екранів з languages/rxgroup_ua.h <= 16 знаків (cp1251), кожен рядок повідомлення (між \\n) <= 16.
Запуск: python3 tools/test_r65b.py"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import cps_csv as cc            # noqa: E402
import cps_link as cl           # noqa: E402
import table_edit as te         # noqa: E402
import test_r53 as t53          # noqa: E402
import mutants_rxgroup as mr    # noqa: E402

FAILS = []
PASSED = [0]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)
    else:
        PASSED[0] += 1


def build(td):
    exe = os.path.join(td, "t_rxg")
    b = subprocess.run(mr.build_cmd(mr.CP, exe), capture_output=True, text=True, cwd=ROOT)
    check(b.returncode == 0, "збірка C-тесту: " + b.stderr[-300:])
    return exe if b.returncode == 0 else None


def run_mode(exe, mode, path):
    env = dict(os.environ, RXG_MODE=mode, RXG_FILE=path)
    return subprocess.run([exe], capture_output=True, text=True, errors="replace", env=env, timeout=120)


def main():
    with tempfile.TemporaryDirectory() as td:
        exe = build(td)
        if exe is None:
            return 1
        dump = os.path.join(td, "rx.dump")
        p = run_mode(exe, "dump", dump)
        check(p.returncode == 0, "B1: dump завершився кодом %d" % p.returncode)
        raw = open(dump, "rb").read()
        check(len(raw) == 76 + 76 * 80, "B1: розмір образу %d" % len(raw))
        img = t53.blank_image()
        img.set_fl(cl.CP_ADDR_RX_GROUP_LEN, raw[:76])
        img.set_fl(cl.CP_ADDR_RX_GROUP, raw[76:])
        lists = {n: (s, m) for s, n, m in te.tg_lists(img)}
        check("Київ" in lists and lists["Київ"][1] == [7, 8, 9], "B1: CPS бачить «Київ» (7,8,9): %r" % (lists,))
        check("Зоря" in lists and lists["Зоря"][1] == [1, 2, 3, 4], "B1: CPS бачить «Зоря» (1,2,3,4): %r" % (lists,))
        lens = img.fl(cl.CP_ADDR_RX_GROUP_LEN, 76)
        for n, (s, m) in lists.items():
            check(lens[s] == len(m), "B1: довжина в таблиці для «%s» = %d, а контактів %d" % (n, lens[s], len(m)))

        # B2: CPS-образ -> прошивка
        img2 = t53.blank_image()
        specs = [(0, "Alfa", [1, 2, 3]), (2, "Робочий", [4]), (29, "Zulu", [5, 6]), (30, "Зоря", [1, 2, 3, 4]), (75, "N" * 16, list(range(1, 33)))]
        for slot, name, mem in specs:
            nb = cc.pad16(name.encode("cp1251"))
            rec = bytearray(nb) + bytearray(b"".join(m.to_bytes(2, "little") for m in mem).ljust(64, b"\x00"))
            img2.set_group(slot, bytes(rec), len(mem))
        f2 = os.path.join(td, "cps.img")
        open(f2, "wb").write(bytes(img2.fl(cl.CP_ADDR_RX_GROUP_LEN, 76)) + bytes(img2.fl(cl.CP_ADDR_RX_GROUP, 76 * 80)))
        p = run_mode(exe, "load", f2)
        check(p.returncode == 0, "B2: load завершився кодом %d (%s)" % (p.returncode, p.stdout[-200:]))
        seen = {}
        for ln in p.stdout.splitlines():
            m = re.match(r"SLOT (\d+) NAME ([0-9A-F]*) MEM([\d ]*) STOCK (\d+)", ln)
            if m:
                seen[int(m.group(1))] = (bytes.fromhex(m.group(2)), [int(x) for x in m.group(3).split()], int(m.group(4)))
        check(sorted(seen) == [s + 1 for s, _n, _m in specs], "B2: прошивка бачить слоти %r" % sorted(seen))
        for slot, name, mem in specs:
            g = seen.get(slot + 1)
            if g is None:
                continue
            check(g[1] == mem, "B2: склад слота %d: %r" % (slot + 1, g[1]))
            check(g[2] == len(mem), "B2: сток-читач слота %d бачить %d контактів, мало бути %d" % (slot + 1, g[2], len(mem)))
            check(g[0].decode("cp1251").rstrip("\xff") == name or g[0].decode("cp1251") == name, "B2: назва слота %d: %r" % (slot + 1, g[0]))

    # B3: ширини
    h = open(os.path.join(ROOT, "application", "include", "user_interface", "languages", "rxgroup_ua.h"), "rb").read().decode("cp1251")
    nstr = 0
    for mm in re.finditer(r'#define\s+(RXG_\w+)\s+"((?:[^"\\]|\\.)*)"', h):
        key, val = mm.group(1), mm.group(2)
        nstr += 1
        for part in val.split("\\n"):
            part = part.replace("%s", "").replace("%d", "")
            w = len(part)
            check(w <= 16 or "%" in mm.group(2) and w <= 22, "B3: %s: рядок «%s» -- %d знаків (>16)" % (key, part, w))
    check(nstr >= 10, "B3: знайдено лише %d рядків RXG_*" % nstr)
    print("test_r65b: %d перевірок, провалів %d" % (PASSED[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
