#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R88 (хост, без заліза): діагностика Talker Alias «TA diag» не потрапляє в основну збірку й нічого не пише.
  1  препроцесор: БЕЗ ENABLE_TA_DIAG (усі конфігурації, крім TADIAG*) у HR-C6000.c, uiUtilities.c, menuRadioOptions.c, menuSystem.c, ta_diag.c,
     menuTaDiag.c немає жодного taDiag*/menuTaDiag* (код діагностики відсутній); З прапорцем -- він є в трьох хуках і в меню;
  2  у build.yml ENABLE_TA_DIAG є ЛИШЕ в задачі build-ukrainian-tadiag; артефакт/файл релізу названо tadiag; ENABLE_ROAM_RETRY там нема;
  3  Makefile: прапорець лише додає -DENABLE_TA_DIAG;
  4  ta_diag.c і menuTaDiag.c цілком під #if TA_DIAG; у них нема запису у флеш/кодплаг/налаштування/custom-data;
  5  хуки в HR-C6000.c лише читають LCBuf (taDiagRawLC/taDiagCallLC/taDiagNoteBadCrc з LCBuf); у uiUtilities.c -- лише taDiagFwText(LinkHead->talkerAlias);
  6  усі літерали рядків екрана «TA diag» -- ASCII, нерозтягнені (<= 16 символів у літералах рядків row());
  7  мовні файли не чіпались (немає згадок TA_DIAG у languages/).
Запуск: python3 tools/test_r88.py"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
APP = os.path.join(FW, "application")
sys.path.insert(0, HERE)
import check_menu_tables as cmt  # noqa: E402

FAILS = []
N = [0]


def check(c, m):
    N[0] += 1
    if not c:
        FAILS.append(m)
        print("ПРОВАЛ:", m)


def rd(p):
    with open(p, encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def pp(rel, incs, defs):
    r = subprocess.run(["gcc", "-E", "-P", "-std=gnu11", "-w"] + incs + defs + [rel], cwd=FW, capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else None


FILES_HOOK = ["application/source/hardware/HR-C6000.c", "application/source/user_interface/uiUtilities.c",
              "application/source/user_interface/menuRadioOptions.c", "application/source/user_interface/menuSystem.c"]
FILES_NEW = ["application/source/functions/ta_diag.c", "application/source/user_interface/menuTaDiag.c"]
IDENT = re.compile(r"\b(taDiag[A-Za-z]*|menuTaDiag[A-Za-z]*|TA_DIAG[A-Z_]*)\b")


def main():
    incs, cfgs = cmt.load_configs(FW)
    names = [n for n, _ in cfgs]
    check("TADIAG" in names and "TADIAGEN" in names and "TADIAGBARE" in names, "syntax_check.sh: є конфігурації TADIAG, TADIAGEN, TADIAGBARE")

    # 1: без прапорця -- діагностики немає
    clean = [(n, d) for n, d in cfgs if "-DENABLE_TA_DIAG" not in d]
    for rel in FILES_HOOK + FILES_NEW:
        for n, d in clean:
            out = pp(rel, incs, d)
            if out is None:
                continue                      # файл не збирається в цій конфігурації (як у решти перевірок) -- це робить syntax_check
            hits = sorted(set(IDENT.findall(out)))
            check(not hits, "%s [%s]: без ENABLE_TA_DIAG є ідентифікатори діагностики: %r" % (rel, n, hits[:5]))
    d_on = dict(cfgs)["TADIAG"]
    for rel, must in (("application/source/hardware/HR-C6000.c", ("taDiagRawLC", "taDiagCallLC", "taDiagNoteBadCrc")),
                      ("application/source/user_interface/uiUtilities.c", ("taDiagFwText",)),
                      ("application/source/user_interface/menuRadioOptions.c", ("menuTaDiagEnter", "menuTaDiagTick", "menuTaDiagClose", "menuTaDiagIsOpen")),
                      ("application/source/user_interface/menuSystem.c", ("menuTaDiagClose",)),
                      ("application/source/functions/ta_diag.c", ("taDiagDecode", "taDiagCallLC", "taDiagRawLC")),
                      ("application/source/user_interface/menuTaDiag.c", ("menuTaDiagEnter", "taDiagGet"))):
        out = pp(rel, incs, d_on)
        check(out is not None, "%s: збирається препроцесором з ENABLE_TA_DIAG (TADIAG)" % rel)
        if out is not None:
            for m in must:
                check(re.search(r"\b%s\b" % m, out) is not None, "%s: з ENABLE_TA_DIAG є %s" % (rel, m))
    # мутант перевірки 1: виклик поза #if ловиться
    check(IDENT.findall("void f(void)\n{\n\ttaDiagRawLC(0);\n}\n") != [], "мутант: виклик без #if ловиться")

    # 2: build.yml
    y = rd(os.path.join(os.path.dirname(FW), ".github", "workflows", "build.yml"))
    jobs = re.split(r"\n  (?=[A-Za-z0-9_-]+:\n    )", y)
    uncommented = lambda j: re.sub(r"(?m)^\s*#.*$", "", j)
    with_flag = [j.split(":", 1)[0].strip() for j in jobs if "ENABLE_TA_DIAG" in uncommented(j)]
    check(with_flag == ["build-ukrainian-tadiag"], "build.yml: ENABLE_TA_DIAG лише в build-ukrainian-tadiag (є: %r)" % with_flag)
    job = [j for j in jobs if j.startswith("build-ukrainian-tadiag:")]
    check(len(job) == 1, "build.yml: рівно одна задача build-ukrainian-tadiag")
    if job:
        j = uncommented(job[0])
        check("needs: build-ukrainian" in j, "build.yml: tadiag залежить від build-ukrainian (реліз ci-<sha> створює вона)")
        check("openuv380-10w-ukrainian-tadiag-${SHORT}.bin" in j, "build.yml: файл релізу openuv380-10w-ukrainian-tadiag-<sha>.bin")
        check("name: openuv380-10w-ukrainian-tadiag" in j, "build.yml: артефакт openuv380-10w-ukrainian-tadiag")
        check("ENABLE_ROAM_RETRY" not in j and "ENABLE_VOLUME_PROBE" not in j, "build.yml: у tadiag нема ENABLE_ROAM_RETRY/ENABLE_VOLUME_PROBE")
        check("mem_report.py" in j and "codec_margin.sh" in j, "build.yml: tadiag друкує звіт пам'яті й запас до кодека")
    # R109: вхід ручного запуску workflow_dispatch.inputs.diag (список наборів) згадує tadiag як варіант вибору -- це не задача
    others = [j.split(":", 1)[0].strip() for j in jobs if "tadiag" in uncommented(j) and not j.startswith(("build-ukrainian-tadiag:", "workflow_dispatch:"))]
    check(not others, "build.yml: інші задачі не згадують tadiag: %r" % others)

    # 3: Makefile
    mk = rd(os.path.join(FW, "Makefile"))
    check(re.search(r"ifeq \(\$\(ENABLE_TA_DIAG\),1\)\nDEFS \+= -DENABLE_TA_DIAG\nendif", mk) is not None, "Makefile: прапорець лише додає -DENABLE_TA_DIAG")
    check(mk.count("ENABLE_TA_DIAG") == 2, "Makefile: ENABLE_TA_DIAG згадується тільки в ifeq і DEFS (є %d)" % mk.count("ENABLE_TA_DIAG"))

    # 4: нові файли -- цілком під #if
    for rel in FILES_NEW:
        s = rd(os.path.join(FW, rel))
        body = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
        body = "\n".join(l for l in body.split("\n") if l.strip())
        first = body.split("\n")[0:3]
        check(any("TA_DIAG" in l and l.lstrip().startswith("#if") for l in first), "%s: перші рядки -- #include і #if defined(TA_DIAG)" % rel)
        check(body.rstrip().split("\n")[-1].lstrip().startswith("#endif"), "%s: закінчується #endif" % rel)
        forbid = re.compile(r"\b(EEPROM_Write|SPI_Flash_write|SPI_Flash_erase|codeplug[A-Za-z]*Save|codeplugSet[A-Za-z]*|settingsSave[A-Za-z]*|settingsSet[A-Za-z]*|"
                            r"settingsIncrement|settingsDecrement|nonVolatileSettings\s*\.[A-Za-z]+\s*=[^=]|flash_write[A-Za-z_]*|custom_data[A-Za-z_]*)\b")
        check(forbid.search(body) is None, "%s: нема запису у флеш/кодплаг/налаштування: %r" % (rel, forbid.findall(body)[:3]))
    mk_s = rd(os.path.join(APP, "source/user_interface/menuTaDiag.c"))
    check("trxSet" not in mk_s and "HRC6000" not in mk_s and "radioWrite" not in mk_s, "menuTaDiag.c: нічого не пише в радіотракт")

    # 5: хуки лише читають
    h = rd(os.path.join(APP, "source/hardware/HR-C6000.c"))
    calls = re.findall(r"\b(taDiag[A-Za-z]*)\s*\(([^)]*)\)", h)
    check(sorted(c[0] for c in calls) == ["taDiagCallLC", "taDiagNoteBadCrc", "taDiagRawLC"], "HR-C6000.c: рівно три виклики діагностики (є %r)" % [c[0] for c in calls])
    check(all(a.strip() in ("LCBuf", "") for _, a in calls), "HR-C6000.c: усі виклики діагностики отримують лише LCBuf: %r" % calls)
    check(len(re.findall(r"#if defined\(TA_DIAG\)", h)) == 2, "HR-C6000.c: два блоки #if defined(TA_DIAG)")
    u = rd(os.path.join(APP, "source/user_interface/uiUtilities.c"))
    uc = re.findall(r"\b(taDiag[A-Za-z]*)\s*\(([^)]*)\)", u)
    check(uc == [("taDiagFwText", "LinkHead->talkerAlias")], "uiUtilities.c: єдиний виклик taDiagFwText(LinkHead->talkerAlias): %r" % uc)

    # 6: літерали екрана -- ASCII, <= 16 символів (форматні рядки з %-специфікаторами рахуються без підстановки: верхня межа ~ нижче)
    lit = re.findall(r'(?:row\(\s*\d+\s*,\s*|label,\s*|snprintf\(buf, sizeof\(buf\),\s*)"((?:[^"\\]|\\.)*)"', mk_s)
    check(len(lit) >= 15, "menuTaDiag.c: знайдено літерали екрана (%d)" % len(lit))
    for l in lit:
        check(all(ord(c) < 128 for c in l), "menuTaDiag.c: літерал '%s' -- не ASCII" % l)
        flat = re.sub(r"%(?:l|z)?[ud]|%02X|%s|%c|%lu", "", l)     # без підстановок: має бути помітно коротше за 16
        check(len(flat) <= 16, "menuTaDiag.c: літерал '%s' надто довгий (%d без підстановок)" % (l, len(flat)))

    # 7: мовні файли не чіпались
    for root, _, files in os.walk(os.path.join(APP, "include/user_interface/languages")):
        for f in files:
            if f.endswith(".h"):
                with open(os.path.join(root, f), "rb") as fh:
                    check(b"TA_DIAG" not in fh.read() and b"taDiag" not in open(os.path.join(root, f), "rb").read(), "languages/%s: нема згадок діагностики TA" % f)

    if FAILS:
        print("test_r88: %d провалів" % len(FAILS))
        return 1
    print("test_r88: усе гаразд (%d перевірок)" % N[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
