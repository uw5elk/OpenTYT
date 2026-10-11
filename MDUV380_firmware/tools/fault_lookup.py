#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fault_lookup.py -- R10-fix4: адреса зі звіту про збій рації -> функція (+зсув, файл) за .map ТОГО САМОГО коміту.

Використання (Termux, python3 є, більше нічого не треба):

    python3 MDUV380_firmware/tools/fault_lookup.py openuv380-10w-ukrainian-XXXXXXX.map 0800ABCD 0800ABD1 ...

Адреси -- hex із екрана рації (з "0x" чи без; біт Thumb (молодший) ігнорується). Для кожної друкує
    адреса -> функція+зсув  (файл.o, розмір секції)
Імена беруться з секцій .text.<ім'я> (збірка йде з -ffunction-sections, тож тут є і ЛОКАЛЬНІ static-функції, яких немає в таблиці
символів .map) та з глобальних символів. Номер РЯДКА .map не дає -- для нього потрібен .elf і arm-none-eabi-addr2line
(опція --elf FILE; якщо addr2line є в PATH, викликається автоматично).

ВАЖЛИВО. .map має бути від того самого коміту, що прошитий у рацію (у назві прошивки openuv380-10w-ukrainian-<sha>.bin
той самий <sha>). Інакше адреси вкажуть не туди.
"""
import re
import subprocess
import shutil
import sys
import bisect

SEC_ONE = re.compile(r'^ (\.\S+)\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(\S+)\s*$')
SEC_HDR = re.compile(r'^ (\.\S+)\s*$')
SEC_BODY = re.compile(r'^\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s+(\S+)\s*$')
SYM = re.compile(r'^\s+(0x[0-9a-fA-F]{8,16})\s+([A-Za-z_][A-Za-z0-9_.$]*)\s*$')


def parse_map(path):
    secs = []   # (start, size, name, obj)
    syms = []   # (addr, name)
    pending = None
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.rstrip('\n')
            m = SEC_ONE.match(line)
            if m:
                pending = None
                a, sz = int(m.group(2), 16), int(m.group(3), 16)
                if sz and 0x08000000 <= a < 0x08200000:
                    secs.append((a, sz, m.group(1), m.group(4)))
                continue
            m = SEC_HDR.match(line)
            if m:
                pending = m.group(1)
                continue
            if pending:
                m = SEC_BODY.match(line)
                if m:
                    a, sz = int(m.group(1), 16), int(m.group(2), 16)
                    if sz and 0x08000000 <= a < 0x08200000:
                        secs.append((a, sz, pending, m.group(3)))
                pending = None
                continue
            m = SYM.match(line)
            if m:
                a = int(m.group(1), 16)
                if 0x08000000 <= a < 0x08200000:
                    syms.append((a, m.group(2)))
    secs.sort()
    syms.sort()
    return secs, syms


def lookup(secs, syms, addr):
    addr &= ~1
    starts = [s[0] for s in secs]
    i = bisect.bisect_right(starts, addr) - 1
    sec = None
    if i >= 0 and secs[i][0] <= addr < secs[i][0] + secs[i][1]:
        sec = secs[i]
    gname = None
    j = bisect.bisect_right([s[0] for s in syms], addr) - 1
    if j >= 0:
        gname = syms[j]
    return sec, gname


def main(argv):
    elf = None
    args = []
    it = iter(argv[1:])
    for a in it:
        if a == '--elf':
            elf = next(it, None)
        else:
            args.append(a)
    if len(args) < 2:
        print(__doc__)
        return 2
    secs, syms = parse_map(args[0])
    if not secs:
        print('У .map не знайдено жодної секції коду (0x08......) -- це точно map-файл прошивки?')
        return 1
    a2l = shutil.which('arm-none-eabi-addr2line') if elf else None
    for t in args[1:]:
        try:
            addr = int(t, 16)
        except ValueError:
            print('%s: не hex-адреса' % t)
            continue
        sec, g = lookup(secs, syms, addr)
        out = '%08X -> ' % addr
        if sec:
            name = sec[2]
            for pre in ('.text.', '.rodata.', '.data.'):
                if name.startswith(pre):
                    name = name[len(pre):]
                    break
            out += '%s+0x%X  (%s, секція %d Б)' % (name, (addr & ~1) - sec[0], sec[3].split('/')[-1], sec[1])
        elif g:
            out += '%s+0x%X  (найближчий глобальний символ; секції не знайдено)' % (g[1], (addr & ~1) - g[0])
        else:
            out += 'не в коді прошивки (адреса поза 0x08000000..0x081FFFFF або .map не той)'
        print(out)
        if a2l:
            r = subprocess.run([a2l, '-e', elf, '-f', '-C', '-i', '%X' % addr], capture_output=True, text=True)
            for ln in r.stdout.strip().splitlines():
                print('      ' + ln)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
