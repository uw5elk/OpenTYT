#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R66C: мутанти переміщення каналу в зоні (codeplug.c, codeplugZoneMoveChannel). Кожен мутант -- одна правка тексту справжнього codeplug.c; test_codeplug_zonemove мусить на ньому
ПРОВАЛИТИСЬ (збірка не вдалась -- теж провал мутанта-вижившого лише якщо не зібралось, тож збірку перевіряємо окремо на оригіналі). Прапори й джерела беруться з tests/run_tests.sh."""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
APP = os.path.join(FW, "application")
CP = os.path.join(APP, "source", "functions", "codeplug.c")

MUTANTS = [
    ("немає обміну", "pair[0] = z.channels[lo + 1];\n\tpair[1] = z.channels[lo];", "pair[0] = z.channels[lo];\n\tpair[1] = z.channels[lo + 1];"),
    ("пише не в ту позицію (pos замість lo)", "16 + (int)(sizeof(uint16_t) * lo);", "16 + (int)(sizeof(uint16_t) * pos);"),
    ("LUCZ не оновлюється", "if (newIdx != idx)\n\t{\n\t\tcodeplugSetLastUsedChannelInZone", "if (0)\n\t{\n\t\tcodeplugSetLastUsedChannelInZone"),
    ("LUCZ у зворотний бік", "newIdx = (idx == lo) ? (lo + 1) : ((idx == (lo + 1)) ? lo : idx);", "newIdx = (idx == lo) ? lo : ((idx == (lo + 1)) ? (lo + 1) : idx);"),
    ("немає перевірки межі сектора", "if (((addr / 4096) != ((addr + 3) / 4096)))", "if (0)"),
    ("межа сектора надто сувора (addr+4: відхиляє пару впритул до межі)", "((addr + 3) / 4096)))\n\t{\n\t\treturn CODEPLUG_ZONE_EDIT_SECTOR_EDGE", "((addr + 4) / 4096)))\n\t{\n\t\treturn CODEPLUG_ZONE_EDIT_SECTOR_EDGE"),
    ("запис 6 байтів", "(uint8_t *)pair, (int)sizeof(pair)))\n\t{\n\t\treturn CODEPLUG_ZONE_EDIT_WRITE_ERROR", "(uint8_t *)pair, (int)sizeof(pair) + 2))\n\t{\n\t\treturn CODEPLUG_ZONE_EDIT_WRITE_ERROR"),
    ("крок не перевіряється", "if (((dir != -1) && (dir != 1)) || !codeplugZoneGetDataForNumber(zoneNum, &z))\n\t{\n\t\treturn CODEPLUG_ZONE_EDIT_NOT_REAL;\n\t}\n\n\tnum", "if (!codeplugZoneGetDataForNumber(zoneNum, &z))\n\t{\n\t\treturn CODEPLUG_ZONE_EDIT_NOT_REAL;\n\t}\n\n\tnum"),
    ("вихід за кінець списку дозволено", "(pos >= num) || (to < 0) || (to >= num))", "(pos >= num) || (to < 0))"),
    ("поточна зона не перечитується", "\tnewIdx = (idx == lo) ? (lo + 1) : ((idx == (lo + 1)) ? lo : idx);\n\tif (newIdx != idx)\n\t{\n\t\tcodeplugSetLastUsedChannelInZone(bit, (int16_t)newIdx);\n\t\tcodeplugSaveLastUsedChannelInZone();\n\t}\n\n\tcodeplugZoneRefreshCurrent(bit, zoneNum);", "\tnewIdx = (idx == lo) ? (lo + 1) : ((idx == (lo + 1)) ? lo : idx);\n\tif (newIdx != idx)\n\t{\n\t\tcodeplugSetLastUsedChannelInZone(bit, (int16_t)newIdx);\n\t\tcodeplugSaveLastUsedChannelInZone();\n\t}\n"),
    ("збій запису мовчки пропускається", "if (!EEPROM_Write(addr, (uint8_t *)pair, (int)sizeof(pair)))\n\t{\n\t\treturn CODEPLUG_ZONE_EDIT_WRITE_ERROR;\n\t}\n\n\tidx", "(void)EEPROM_Write(addr, (uint8_t *)pair, (int)sizeof(pair));\n\n\tidx"),
]


def build_cmd(src, exe):
    s = open(os.path.join(HERE, "run_tests.sh"), encoding="utf-8").read()
    fw = s[s.index('FW_INCS="'):]
    fw = fw[:fw.index('"\n', 10) + 2].replace("$FW", FW)
    m = re.search(r'FW_INCS="(.*?)"\n', fw, re.S)
    incs = m.group(1).replace("\\\n", " ")
    incs = incs.replace("$FW", FW)
    xf = re.search(r'\[test_codeplug_zonemove\]="\$FW_INCS ([^"]*)"', s).group(1).split("#")[0]
    cmd = ["gcc", "-O1", "-w"] + incs.split() + xf.split() + [os.path.join(HERE, "test_codeplug_zonemove.c"), src,
                                                               os.path.join(APP, "source", "functions", "aprs_rx_parse.c"),
                                                               os.path.join(APP, "source", "functions", "aprs_mode_cfg.c"),
                                                               os.path.join(APP, "source", "functions", "dmr_sms_text.c"), "-lm",
                                                               "-I", os.path.join(APP, "include"), "-I", os.path.join(APP, "include", "crypto"), "-o", exe]
    return cmd


def run(src, td, tag):
    exe = os.path.join(td, "t_" + tag)
    b = subprocess.run(build_cmd(src, exe), capture_output=True, text=True, cwd=FW)
    if b.returncode != 0:
        return None, b.stderr[-300:]
    p = subprocess.run([exe], capture_output=True, text=True, errors="replace", timeout=300)
    return p.returncode, p.stdout


def main():
    code = open(CP, encoding="utf-8").read()
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        rc, out = run(CP, td, "orig")
        if rc != 0:
            print("ПРОВАЛ: оригінал не проходить тест (%r): %s" % (rc, out[-300:]))
            return 1
        for i, (name, old, new) in enumerate(MUTANTS):
            if code.count(old) != 1:
                print("ПРОВАЛ: мутант «%s»: фрагмент зустрічається %d разів (мусить 1)" % (name, code.count(old)))
                bad += 1
                continue
            mp = os.path.join(td, "codeplug.c")
            open(mp, "w", encoding="utf-8").write(code.replace(old, new))
            rc, out = run(mp, td, "m%d" % i)
            if rc is None:
                print("ПРОВАЛ: мутант «%s» не збирається: %s" % (name, out))
                bad += 1
            elif rc == 0:
                print("ПРОВАЛ: мутант вижив: «%s»" % name)
                bad += 1
    if bad:
        print("mutants_zonemove: %d проблем" % bad)
        return 1
    print("mutants_zonemove: усі %d мутантів убито" % len(MUTANTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
