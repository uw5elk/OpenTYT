#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R109-RELEASEPREP: CI (три набори на пуш, діагностичні лише вручну, релізний job за тегом v*), версія з тегу, дослід RAM.

Actions локально не запустити, тож перевіряється ТЕКСТ і структура .github/workflows/build.yml (YAML + умови `if:` + імена активів),
а також tools/release_version.py і tools/ram_symbols.py на справжніх прикладах. Чого це НЕ доводить -- див. claude/r109-result.md.
  Р1  release_version: теги v1.0.0, v1.0.0-rc1, v2.10.3-rc12 -> версія прошивки, prerelease, рядки version_info.txt; неправильні теги відхиляються.
  Р2  препроцесор gcc: -DGITVERSION=1.0.0r1 / 1.0.0 / abc1234 стають рядком через XSTRINGIFY (як у menuFirmwareInfoScreen.c); обрізання до 7 символів.
  Р3  build.yml: YAML коректний; діагностичні job-и мають `if` лише для workflow_dispatch з inputs.diag; всі діагностичні набори є серед options.
  Р4  build.yml: на пуш лишаються checks, build (ENABLE_AES 0 і 1), build-ukrainian, build-gui-flasher; реліз-job -- лише за тегом, needs усіх чотирьох.
  Р5  build.yml: активи релізу -- рівно .bin, .exe, RELEASE_NOTES.md, THIRD_PARTY_NOTICES.md; .map/.elf/діагностичних у релізі нема; prerelease лише для -rc.
  Р6  build.yml: версія з тегу у прошивці (GITVERSION_ARG лише за тегом) і в CPS (apply-cps); без тегу -- коміт і дата; pip з requirements-cps.txt.
  Р7  build.yml: прибирання старих ci-* релізів і звіт пам'яті (mem_report, codec_margin) збережено; ci-<тег> для тегових запусків.
  Р8  ram_symbols: розбір nm sysv, порівняння, вставка кроку в старі build.yml (3a78279/06b8ee2-подібні); крок є в main-версії.
  Р9  мутанти: без `if` у діагностичному job; реліз-job без умови тегу; діагностичний .bin у релізі; pip без файлу залежностей -- ловляться.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    import yaml
except ImportError:
    # R109-FIX: без PyYAML -- у CI це ПРОВАЛ (тест не має мовчати), локально -- очікуваний пропуск (облік у tests/run_tests.sh).
    if os.environ.get("CI", "").lower() == "true":
        print("ПРОВАЛ test_r109release: немає PyYAML (у CI має бути встановлений: job checks, pip install pyyaml)")
        sys.exit(1)
    print("ПРОПУСК: немає PyYAML -- test_r109release не виконано (pip install pyyaml)")
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(FW, ".."))
YML = os.path.join(ROOT, ".github", "workflows", "build.yml")
sys.path.insert(0, HERE)
import release_version as rv   # noqa: E402
import ram_symbols as rs       # noqa: E402

FAILS = []
N = [0]
DIAG_JOBS = {"build-aes-mi": "aes-mi", "build-aes-diag": "aes-diag", "build-ukrainian-diag": "ukrainian-diag",
             "build-ukrainian-volprobe": "volprobe", "build-ukrainian-tadiag": "tadiag",
             "build-ukrainian-roam-diag": "roam-diag", "build-ukrainian-roam": "roam"}
RELEASE_FILES = ["openuv380-10w-ukrainian-${GITHUB_REF_NAME}.bin", "TYT.MD-UV390UKR.exe", "RELEASE_NOTES.md", "THIRD_PARTY_NOTICES.md"]


def check(cond, msg):
    N[0] += 1
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ:", msg)


def job_text(text, name):
    """Текст job з сирого YAML (від `  name:` до наступного job)."""
    m = re.search(r"^  %s:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)" % re.escape(name), text, re.S | re.M)
    return m.group(1) if m else None


def yml_problems(text):
    """Усі порушення правил R109 у тексті build.yml (порожній список -- усе гаразд)."""
    bad = []
    try:
        d = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return ["YAML: %s" % e]
    jobs = d["jobs"]
    on = d.get(True) or d.get("on")
    disp = (on or {}).get("workflow_dispatch") or {}
    opts = (((disp.get("inputs") or {}).get("diag") or {}).get("options")) or []
    for job, key in DIAG_JOBS.items():
        j = jobs.get(job)
        if j is None:
            bad.append("нема job %s" % job)
            continue
        cond = str(j.get("if", ""))
        if "github.event_name == 'workflow_dispatch'" not in cond or "inputs.diag == '%s'" % key not in cond or "inputs.diag == 'all'" not in cond:
            bad.append("%s: умова `if` не обмежує ручним запуском із вибором «%s»: %r" % (job, key, cond))
        if key not in opts:
            bad.append("inputs.diag.options не містить %s" % key)
    for k in ("none", "all"):
        if k not in opts:
            bad.append("inputs.diag.options без %s" % k)
    # на пуш лишаються лише основні
    always = sorted(n for n, j in jobs.items() if "if" not in j and n not in DIAG_JOBS)
    if always != ["build", "build-ukrainian", "checks"]:
        bad.append("job-и без умови: %r (мають бути checks, build, build-ukrainian)" % always)
    if sorted(str(x) for x in jobs["build"]["strategy"]["matrix"]["aes"]) != ["0", "1"]:
        bad.append("build: матриця aes має бути 0 і 1 (контрольна без прапорців + мовна перевірка)")
    # реліз
    rel = jobs.get("release")
    if rel is None:
        bad.append("нема job release")
    else:
        if "startsWith(github.ref, 'refs/tags/v')" not in str(rel.get("if", "")):
            bad.append("release: нема умови тегу v*")
        if sorted(rel.get("needs", [])) != ["build", "build-gui-flasher", "build-ukrainian", "checks"]:
            bad.append("release: needs %r" % rel.get("needs"))
        rt = job_text(text, "release") or ""
        for f in RELEASE_FILES:
            if f not in rt:
                bad.append("release: нема активу %s" % f)
        if re.search(r"\.(map|elf|hex)\b", rt.split("gh release create")[-1]) or re.search(r"diag|volprobe|tadiag|roam", rt.split("gh release create")[-1]):
            bad.append("release: у списку активів є .map/.elf/.hex або діагностичне")
        n_inline = len(re.findall(r'"out/[^"]+"|\bout/[A-Z_]+\.md\b', rt.split("gh release create")[-1]))
        if n_inline != 4:
            bad.append("release: активів out/... має бути рівно 4, є %d" % n_inline)
        if "--prerelease" not in rt or 'PRERELEASE}" = "true"' not in rt:
            bad.append("release: prerelease лише за -rc (умова відсутня)")
        if "--verify-tag" not in rt:
            bad.append("release: нема --verify-tag")
    # версія й залежності
    bu = job_text(text, "build-ukrainian") or ""
    if "GITVERSION_ARG" not in bu or "refs/tags/v" not in bu or "release_version.py fw" not in bu:
        bad.append("build-ukrainian: нема версії з тегу")
    if not re.search(r"if: startsWith\(github\.ref, 'refs/tags/v'\)\n\s+run: \|\n\s+set -euo pipefail\n\s+FWV=", bu):
        bad.append("build-ukrainian: крок версії не обмежено тегом")
    if bu.count("${GITVERSION_ARG}") != 1:
        bad.append("build-ukrainian: ${GITVERSION_ARG} має бути в команді make один раз")
    for other in ("build", "checks"):
        if "GITVERSION_ARG" in (job_text(text, other) or ""):
            bad.append("%s: GITVERSION_ARG поза build-ukrainian" % other)
    gf = job_text(text, "build-gui-flasher") or ""
    if "requirements-cps.txt" not in gf or re.search(r"pip install pyinstaller", gf):
        bad.append("build-gui-flasher: залежності не з requirements-cps.txt")
    if "pip freeze" not in gf:
        bad.append("build-gui-flasher: нема pip freeze")
    if "release_version.py apply-cps" not in gf or "коміт $(git rev-parse --short HEAD), зібрано" not in gf:
        bad.append("build-gui-flasher: нема версії з тегу в CPS або звичайного підпису")
    if "startsWith(github.ref, 'refs/tags/v')" not in str(jobs["build-gui-flasher"].get("if", "")):
        bad.append("build-gui-flasher: нема збірки .exe за тегом")
    # збереження старого
    if "startswith(\"ci-\")" not in bu or "лишити 5" not in bu:
        bad.append("build-ukrainian: прибирання старих ci-* релізів зникло")
    if "mem_report.py" not in bu or "codec_margin.sh" not in bu:
        bad.append("build-ukrainian: звіт пам'яті/запас до кодека зникли")
    if "ram_symbols.py" not in bu:
        bad.append("build-ukrainian: нема кроку ram_symbols.py")
    if "CI_TAG" not in bu or 'refs/tags/v*' not in bu:
        bad.append("build-ukrainian: нема ci-<тег> для тегових запусків")
    return bad


def main():
    # Р1
    cases = {"v1.0.0": ("1.0.0", False, (1, 0, 0, 0), "1.0.0"), "v1.0.0-rc1": ("1.0.0r1", True, (1, 0, 0, 0), "1.0.0-rc1"),
             "v2.10.3-rc12": ("2.10.3r12", True, (2, 10, 3, 0), "2.10.3-rc12")}
    for tag, (fw, pre, num, txt) in cases.items():
        check(rv.fw_version(tag) == fw, "Р1: %s -> %s" % (tag, rv.fw_version(tag)))
        check(rv.is_prerelease(tag) == pre, "Р1: %s prerelease=%s" % (tag, rv.is_prerelease(tag)))
        check(rv.cps_strings(tag) == (num, txt), "Р1: %s CPS %r" % (tag, rv.cps_strings(tag)))
    for bad in ("v1.0", "1.0.0", "v1.0.0-beta", "v1.0.0-rc0", "v1.0.0-rc", "v1.0.0rc1", "vx", "", "v1.0.0-rc1-x", "v1.0.0 "):
        try:
            rv.parse_tag(bad)
            check(False, "Р1: тег «%s» мав бути відхилений" % bad)
        except ValueError:
            check(True, "")
    with open(os.path.join(HERE, "version_info.txt"), encoding="utf-8") as f:
        vi = f.read()
    out = rv.apply_version_info(vi, "v1.2.3-rc4")
    check("filevers=(1, 2, 3, 0)" in out and "prodvers=(1, 2, 3, 0)" in out and "StringStruct('FileVersion', '1.2.3-rc4')" in out
          and "StringStruct('ProductVersion', '1.2.3-rc4')" in out, "Р1: version_info.txt оновлено")
    check(out.count("VSVersionInfo(") == 1 and out.replace("1.2.3-rc4", "1.0.0.0").replace("(1, 2, 3, 0)", "(1, 0, 0, 0)") == vi,
          "Р1: змінено лише версію (решта version_info.txt без змін)")
    try:
        compile(out, "version_info.txt", "exec")
    except SyntaxError as e:
        check(False, "Р1: version_info.txt після правки -- не Python: %s" % e)
    try:
        rv.apply_version_info(vi.replace("filevers=(1, 0, 0, 0),", ""), "v1.0.0")
        check(False, "Р1: зміна шаблону version_info.txt має давати помилку")
    except ValueError:
        check(True, "")
    check(rv.build_info("v1.0.0", "abc1234", "2026-12-01") == "версія v1.0.0, коміт abc1234, зібрано 2026-12-01\n", "Р1: build_info")
    with tempfile.TemporaryDirectory() as t:
        vip, bip = os.path.join(t, "version_info.txt"), os.path.join(t, "build_info.txt")
        open(vip, "w", encoding="utf-8").write(vi)
        r = subprocess.run([sys.executable, os.path.join(HERE, "release_version.py"), "apply-cps", "v1.0.0-rc1", vip, bip, "abc1234", "2026-12-01"],
                           capture_output=True, text=True)
        check(r.returncode == 0 and "1.0.0-rc1" in open(vip, encoding="utf-8").read() and open(bip, encoding="utf-8").read().startswith("версія v1.0.0-rc1"),
              "Р1: CLI apply-cps: %s" % r.stderr[-200:])
        r = subprocess.run([sys.executable, os.path.join(HERE, "release_version.py"), "fw", "v1.0.0-rc1"], capture_output=True, text=True)
        check(r.stdout.strip() == "1.0.0r1" and r.returncode == 0, "Р1: CLI fw")
        r = subprocess.run([sys.executable, os.path.join(HERE, "release_version.py"), "fw", "v1.0"], capture_output=True, text=True)
        check(r.returncode == 1, "Р1: CLI fw з поганим тегом -> код 1")
    # Р2
    if shutil.which("gcc") is None:
        print("ПРОПУСК: gcc нема -- Р2 (XSTRINGIFY версії) не виконано (це не «пройдено»)")
    else:
        src = '#define STRINGIFY(s) #s\n#define XSTRINGIFY(s) STRINGIFY(s)\nconst char v[] = XSTRINGIFY(GITVERSION);\n'
        for ver in ("1.0.0r1", "1.0.0", "abc1234", "2.10.3r12"):
            r = subprocess.run(["gcc", "-E", "-P", "-DGITVERSION=" + ver, "-x", "c", "-"], input=src, capture_output=True, text=True)
            check('"%s"' % ver in r.stdout, "Р2: GITVERSION=%s -> %r" % (ver, r.stdout.strip()[-30:]))
    check(len(rv.fw_version("v1.0.0-rc1")) <= rv.FW_VISIBLE and len(rv.fw_version("v1.10.0-rc1")) > rv.FW_VISIBLE,
          "Р2: 7 символів (versionBuf[9]=0): v1.0.0-rc1 вміщується, v1.10.0-rc1 -- ні (CLI друкує УВАГА)")
    # Р3-Р7
    text = open(YML, encoding="utf-8").read()
    probs = yml_problems(text)
    check(not probs, "Р3-Р7: build.yml: " + "; ".join(probs))
    # Р8
    sysv = ("Symbols from x.elf:\n\nName Value Class Type Size Line Section\n\n"
            "aaa                 |20000010|   b  |            OBJECT|00000004|     |.bss\n"
            "bbb                 |20000018|   B  |            OBJECT|00000008|     |.bss\n"
            "ccm1                |10000000|   b  |            OBJECT|00000100|     |.ccmram\n"
            "txt                 |08000000|   T  |              FUNC|00000010|     |.text\n"
            "dd                  |20000000|   d  |            OBJECT|00000008|     |.data\n")
    syms = rs.parse_sysv(sysv)
    check([s[3] for s in syms] == ["dd", "aaa", "bbb", "ccm1"] or [s[3] for s in syms] == ["aaa", "bbb", "dd", "ccm1"] or len(syms) == 4,
          "Р8: parse_sysv бере лише .bss/.data/.ccmram: %r" % syms)
    lines = rs.format_lines(syms)
    check("RAMSYM .bss 4 20000010 aaa" in lines and "RAMSUM .bss 12 2" in lines and "RAMSUM .ccmram 256 1" in lines, "Р8: формат: %r" % lines)
    other = "\n".join(lines).replace("RAMSYM .bss 8 20000018 bbb", "RAMSYM .bss 8 2000001c bbb")
    d = rs.diff("\n".join(lines), other)
    check("проміжки B" in d and "4 Б" in d and "bbb" in d, "Р8: diff бачить проміжок: %s" % d[:200])
    other2 = "\n".join(lines).replace("RAMSYM .bss 4 20000010 aaa", "RAMSYM .bss 12 20000010 aaa")
    check("aaa: 4 -> 12 (Δ+8)" in rs.diff("\n".join(lines), other2), "Р8: diff бачить зміну розміру")
    check("[новий]" in rs.diff("\n".join(lines), "\n".join(lines) + "\nRAMSYM .bss 4 20000030 zzz"), "Р8: diff бачить новий символ")
    # префікси логу CI (job\tкрок\tчас текст) не заважають
    logged = "\n".join("build-ukrainian\tСимволи RAM\t2026-11-27T10:00:00.0000000Z " + l for l in lines)
    check(rs.parse_lines(logged) == rs.parse_lines("\n".join(lines)), "Р8: префікси логу CI відкидаються")
    old = open(YML, encoding="utf-8").read()
    stripped = old.replace(rs.CI_STEP, "")
    check(stripped != old and "ram_symbols.py" not in stripped, "Р8: крок можна прибрати для старої версії")
    try:
        new = rs.add_ci_step(stripped)
        check(new == old, "Р8: add_ci_step відтворює main-версію build.yml")
    except ValueError as e:
        check(False, "Р8: add_ci_step: %s" % e)
    try:
        rs.add_ci_step(old)
        check(False, "Р8: повторна вставка має відхилятись")
    except ValueError:
        check(True, "")
    # Р9: мутанти
    def mutant(name, text2):
        check(text2 != text, "Р9: мутант «%s» застосовано" % name)
        check(bool(yml_problems(text2)), "Р9: мутант «%s» не спіймано" % name)
    mutant("без if у volprobe", re.sub(r"(  build-ukrainian-volprobe:\n)(?:    #[^\n]*\n)?    if: [^\n]*\n", r"\1", text))
    mutant("реліз без умови тегу", text.replace("    if: startsWith(github.ref, 'refs/tags/v')\n    needs: [checks, build, build-ukrainian, build-gui-flasher]",
                                                "    needs: [checks, build, build-ukrainian, build-gui-flasher]"))
    mutant("діагностичний .bin у релізі", text.replace('out/RELEASE_NOTES.md out/THIRD_PARTY_NOTICES.md', 'out/RELEASE_NOTES.md out/THIRD_PARTY_NOTICES.md out/openuv380-10w-ukrainian-tadiag.bin'))
    mutant("pip без requirements-cps", text.replace("pip install -r MDUV380_firmware/tools/requirements-cps.txt", "pip install pyinstaller pyusb pyserial libusb cryptography"))
    mutant("GITVERSION завжди", text.replace("if: startsWith(github.ref, 'refs/tags/v')\n        run: |\n          set -euo pipefail\n          FWV=", "run: |\n          set -euo pipefail\n          FWV="))
    mutant("без --verify-tag", text.replace("--verify-tag ", ""))
    print("test_r109release: перевірок %d, провалів %d" % (N[0], len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
