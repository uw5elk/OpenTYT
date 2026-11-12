#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R94-Д (хост): docs/calibration.md узгоджено з кодом.
  1  кожне посилання `файл:рядок[-рядок]` у розділі «Джерела» існує і не виходить за межі файла;
  2  ключові факти документа проти коду: 14 калібрувальних частот і їхні значення, рівні потужності 10 Вт (250,1,5,10), адреса 0x10000 і довжина 0x200, діапазони −128..127 і 0..255,
     частоти PTT 14500000/43500000, коефіцієнти перерахунку 10 Вт, відновлення CPS не пише сектор калібрування;
  3  мутанти: підміна числа в документі ловиться.
Запуск: python3 tools/test_r94d.py"""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); FW = os.path.dirname(HERE); ROOT = os.path.dirname(FW)
FAILS = []; N = [0]
def check(c, m):
    N[0] += 1
    if not c: FAILS.append(m); print("ПРОВАЛ: " + m)
def rd(p): return open(p, encoding="utf-8", errors="replace").read()
def facts_ok(doc, mc, cal, rst):
    o = []
    for v in ("135, 145, 155, 165, 175", "400, 410", "250 мВт, 1 Вт, 5 Вт, 10 Вт", "0x10000", "145.000", "435.000", "−128…127", "0…255", "0,35 / 0,65 / 1,25 / 1,40", "0,40 / 0,70 / 1,20 / 1,35"):
        if v not in doc: o.append("документ: нема %r" % v)
    if "13500000, 14500000, 15500000, 16500000, 17500000" not in mc or "40000000, 41000000" not in mc or "48000000" not in mc: o.append("код: calFreq")
    if "NO_OF_CAL_FREQS 14" not in mc: o.append("код: NO_OF_CAL_FREQS")
    if not re.search(r"PLATFORM_VARIANT_UV380_PLUS_10W\)\s*\nstatic const uint8_t calPower\[NO_OF_POWER_LEVELS\] = \{ 250, 1, 5, 10 \}", mc): o.append("код: calPower 10W")
    if "freq = 14500000" not in mc or "freq = 43500000" not in mc: o.append("код: PTT частоти")
    if "oscTune[freqBand] < 127" not in mc or "> -128" not in mc or "< 255" not in mc: o.append("код: діапазони")
    if "0x10000" not in cal or "CALIBRATION_TABLE_LENGTH 0x200" not in cal: o.append("код: 0x10000/0x200")
    if not re.search(r"10W UV380\s*\n\s*\{0\.35f, 0\.65f, 1\.25f, 1\.40f\},.*\n\s*\{0\.40f, 0\.70f, 1\.20f, 1\.35f\}", cal): o.append("код: коефіцієнти")
    if "want_ee[CAL_START:CAL_END] = cur_ee[CAL_START:CAL_END]" not in rst or "писати заборонено" not in rst: o.append("код: CPS не пише калібрування")
    return o
def main():
    doc = rd(os.path.join(ROOT, "docs", "calibration.md"))
    src = doc.split("## Джерела")[1]
    refs = re.findall(r"`([A-Za-z0-9_./]+\.(?:c|h|py|md|ld|sh)|Makefile)(?::(\d+)(?:-(\d+))?)?`", src)
    n = 0
    for f, a, b in refs:
        cands = [os.path.join(FW, f), os.path.join(FW, "application", f), os.path.join(FW, "application", "source", f), os.path.join(ROOT, f), os.path.join(FW, "tools", f)]
        p = next((c for c in cands if os.path.isfile(c)), None)
        if p is None: check(False, "джерело не знайдено: " + f); continue
        n += 1
        if a:
            ln = len(rd(p).split("\n")); check(int(b or a) <= ln and int(a) >= 1, "%s:%s виходить за межі (%d рядків)" % (f, a, ln))
    check(n >= 20, "перевірено посилань: %d" % n)
    mc = rd(os.path.join(FW, "application/source/user_interface/menuCalibration.c")); cal = rd(os.path.join(FW, "application/source/functions/calibration.c")); rst = rd(os.path.join(FW, "tools/cps_restore.py"))
    e = facts_ok(doc, mc, cal, rst)
    for x in e: check(False, x)
    check(not e, "ключові факти збігаються з кодом")
    for a, b in (("250 мВт, 1 Вт, 5 Вт, 10 Вт", "250 мВт, 1 Вт, 5 Вт, 12 Вт"), ("0x10000", "0x20000"), ("−128…127", "−100…127"), ("145.000", "146.000")):
        check(bool(facts_ok(doc.replace(a, b), mc, cal, rst)), "мутант «%s»" % b)
    print("test_r94d: ПРОВАЛІВ: %d (з %d перевірок)" % (len(FAILS), N[0])); return 1 if FAILS else 0
if __name__ == "__main__": sys.exit(main())
