#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R109-RELEASEPREP (пункт 5): символи .bss/.data/.ccmram збірки -- для досліду «RAM −24 Б між R103 (3a78279) і R106 (06b8ee2)».

Нічого не змінює в артефактах: лише друкує рядки з префіксом RAMSYM (зручно для grep по логу CI, як «Запас до кодека»).

  ram_symbols.py ELF                       -> рядки `RAMSYM <секція> <розмір> <адреса> <ім'я>` (за адресою) і `RAMSUM <секція> <сума> <к-сть>`;
                                              читає `arm-none-eabi-nm -S -f sysv ELF` (потрібен тулчейн; у CI він є).
  ram_symbols.py --diff A.txt B.txt        -> порівняння двох списків RAMSYM (витяг із логів CI): суми секцій, символи, що з'явились/зникли/
                                              змінили розмір, і найбільші проміжки між сусідніми символами (вирівнювання/пads).
  ram_symbols.py --add-ci-step build.yml   -> вставляє крок CI з цим виводом у job build-ukrainian ПІСЛЯ рядка mem_report.py
                                              (для тимчасових гілок на старих комітах; на main крок уже є).

Це ЛИШЕ спосіб побачити, ЧОМУ змінилось: причини наперед не вгадуються.
"""
import re
import subprocess
import sys

SECTIONS = (".bss", ".data", ".ccmram")
CI_STEP = """      - name: Символи RAM (.bss/.data/.ccmram) -- лише дослід, артефакти не змінює
        continue-on-error: true
        working-directory: MDUV380_firmware
        run: python3 tools/ram_symbols.py build/openuv380-10w.elf
"""


def parse_sysv(text):
    """Рядки `ім'я | адреса | клас | тип | розмір | рядок | секція` -> [(секція, розмір, адреса, ім'я)] для SECTIONS."""
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 7:
            continue
        name, addr, _cls, _typ, size, _line, sec = parts[:7]
        if sec not in SECTIONS:
            continue
        try:
            out.append((sec, int(size, 16), int(addr, 16), name))
        except ValueError:
            continue
    out.sort(key=lambda r: (SECTIONS.index(r[0]), r[2], r[3]))
    return out


def format_lines(syms):
    lines = ["RAMSYM %s %d %08x %s" % (sec, size, addr, name) for sec, size, addr, name in syms]
    for sec in SECTIONS:
        sel = [s for s in syms if s[0] == sec]
        lines.append("RAMSUM %s %d %d" % (sec, sum(s[1] for s in sel), len(sel)))
    return lines


def parse_lines(text):
    """Рядки RAMSYM (з префіксами логу або без) -> {секція: [(адреса, розмір, ім'я)]}."""
    res = {s: [] for s in SECTIONS}
    for m in re.finditer(r"RAMSYM (\S+) (\d+) ([0-9a-f]+) (\S+)", text):
        sec = m.group(1)
        if sec in res:
            res[sec].append((int(m.group(3), 16), int(m.group(2)), m.group(4)))
    for sec in res:
        res[sec].sort()
    return res


def gaps(items):
    """Проміжки між кінцем символу і початком наступного: [(розмір, адреса_початку, ім'я_до, ім'я_після)]."""
    out = []
    for (a1, s1, n1), (a2, _s2, n2) in zip(items, items[1:]):
        g = a2 - (a1 + s1)
        if g > 0:
            out.append((g, a1 + s1, n1, n2))
    return sorted(out, reverse=True)


def diff(a_text, b_text):
    A, B = parse_lines(a_text), parse_lines(b_text)
    out = []
    for sec in SECTIONS:
        sa, sb = sum(s for _a, s, _n in A[sec]), sum(s for _a, s, _n in B[sec])
        spa = (A[sec][-1][0] + A[sec][-1][1] - A[sec][0][0]) if A[sec] else 0
        spb = (B[sec][-1][0] + B[sec][-1][1] - B[sec][0][0]) if B[sec] else 0
        out.append("%s: сума розмірів A=%d B=%d (Δ%+d); охоплення A=%d B=%d (Δ%+d); символів A=%d B=%d"
                   % (sec, sa, sb, sb - sa, spa, spb, spb - spa, len(A[sec]), len(B[sec])))
        da, db = {}, {}
        for _a, s, n in A[sec]:
            da[n] = da.get(n, 0) + s
        for _a, s, n in B[sec]:
            db[n] = db.get(n, 0) + s
        ch = [(db.get(n, 0) - da.get(n, 0), n, da.get(n), db.get(n)) for n in set(da) | set(db) if da.get(n) != db.get(n)]
        ch.sort(key=lambda r: (-abs(r[0]), r[1]))
        for d, n, x, y in ch[:30]:
            out.append("  %s: %s -> %s (Δ%+d)%s" % (n, "нема" if x is None else x, "нема" if y is None else y, d,
                                                   "  [новий]" if x is None else ("  [зник]" if y is None else "")))
        if len(ch) > 30:
            out.append("  ... ще змін: %d" % (len(ch) - 30))
        for tag, items in (("A", A[sec]), ("B", B[sec])):
            g = gaps(items)[:5]
            out.append("  проміжки %s (найбільші 5; сума всіх %d): %s" % (tag, sum(x[0] for x in gaps(items)),
                        "; ".join("%d Б @%08x між %s і %s" % x for x in g) or "нема"))
    return "\n".join(out)


def add_ci_step(yml_text):
    """Вставляє CI_STEP після першого рядка з mem_report.py, що йде ПІСЛЯ `  build-ukrainian:`. ValueError, якщо не знайдено."""
    lines = yml_text.split("\n")
    try:
        start = lines.index("  build-ukrainian:")
    except ValueError:
        raise ValueError("у файлі нема job build-ukrainian")
    for i in range(start, len(lines)):
        if "mem_report.py" in lines[i] and lines[i].lstrip().startswith("run:"):
            if "ram_symbols.py" in "\n".join(lines[i:i + 6]):
                raise ValueError("крок ram_symbols.py уже є")
            return "\n".join(lines[:i + 1] + CI_STEP.rstrip("\n").split("\n") + lines[i + 1:])
        if lines[i].startswith("  build-") and i > start:
            break
    raise ValueError("у job build-ukrainian нема кроку mem_report.py")


def main(argv):
    if len(argv) == 4 and argv[1] == "--diff":
        print(diff(open(argv[2], encoding="utf-8", errors="replace").read(), open(argv[3], encoding="utf-8", errors="replace").read()))
        return 0
    if len(argv) == 3 and argv[1] == "--add-ci-step":
        try:
            new = add_ci_step(open(argv[2], encoding="utf-8").read())
        except ValueError as e:
            print("ПОМИЛКА: %s" % e, file=sys.stderr)
            return 1
        open(argv[2], "w", encoding="utf-8").write(new)
        print("крок ram_symbols.py додано в %s" % argv[2])
        return 0
    if len(argv) == 2 and not argv[1].startswith("-"):
        r = subprocess.run(["arm-none-eabi-nm", "-S", "-f", "sysv", argv[1]], capture_output=True, text=True)
        if r.returncode != 0:
            print("ПОМИЛКА: arm-none-eabi-nm: %s" % r.stderr[-300:], file=sys.stderr)
            return 1
        print("\n".join(format_lines(parse_sysv(r.stdout))))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
