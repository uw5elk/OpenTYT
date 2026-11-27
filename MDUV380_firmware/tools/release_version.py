#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R109-RELEASEPREP: версія релізу з тегу `v*` -- для прошивки (GITVERSION), CPS (.exe) і GitHub Release.

Теги: `v<M>.<m>.<p>` (стабільний реліз) і `v<M>.<m>.<p>-rc<N>` (кандидат, prerelease). Інші `v*` -- помилка (CI не публікує).

Підкоманди (їх викликає .github/workflows/build.yml лише при збірці за тегом; без тегу все як було -- коротка sha):
  fw TAG                           -> рядок для make GITVERSION=...: `1.0.0` або `1.0.0r1` (rc -> «r»).
                                      Чому так: екран «Про прошивку» показує лише 7 символів версії
                                      (menuFirmwareInfoScreen.c: versionBuf[9] = 0), довший тег було б обрізано.
  prerelease TAG                   -> `true` для -rcN, інакше `false`.
  apply-cps TAG VERSION_INFO BUILD_INFO SHA DATE
                                   -> переписує version_info.txt (FileVersion/ProductVersion; числова версія -- M.m.p.0)
                                      і створює build_info.txt («версія v1.0.0, коміт abc1234, зібрано 2026-12-01»);
                                      цей рядок показує вікно CPS (cps_ui/common.read_build_info).
Числова версія Windows (VS_FIXEDFILEINFO) без rc: у v1.0.0 і v1.0.0-rc1 вона однакова (1.0.0.0); повний тег лежить у рядкових
полях FileVersion/ProductVersion (їх показує Провідник).
"""
import re
import sys

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?$")
FW_VISIBLE = 7     # стільки символів версії показує «Про прошивку»


def parse_tag(tag):
    m = TAG_RE.match(tag or "")
    if not m:
        raise ValueError("тег «%s» не відповідає v<M>.<m>.<p> або v<M>.<m>.<p>-rc<N>" % tag)
    major, minor, patch = (int(m.group(i)) for i in (1, 2, 3))
    rc = int(m.group(4)) if m.group(4) is not None else None
    if rc is not None and rc == 0:
        raise ValueError("тег «%s»: номер rc починається з 1" % tag)
    return major, minor, patch, rc


def fw_version(tag):
    major, minor, patch, rc = parse_tag(tag)
    return "%d.%d.%d" % (major, minor, patch) + ("r%d" % rc if rc is not None else "")


def is_prerelease(tag):
    return parse_tag(tag)[3] is not None


def cps_strings(tag):
    major, minor, patch, rc = parse_tag(tag)
    num = (major, minor, patch, 0)
    text = "%d.%d.%d" % (major, minor, patch) + ("-rc%d" % rc if rc is not None else "")
    return num, text


def apply_version_info(text, tag):
    """Підставляє версію тегу у вміст tools/version_info.txt. Кидає ValueError, якщо шаблон змінився."""
    num, ver = cps_strings(tag)
    tup = "(%d, %d, %d, %d)" % num
    out, n1 = re.subn(r"filevers=\(\d+, \d+, \d+, \d+\)", "filevers=" + tup, text)
    out, n2 = re.subn(r"prodvers=\(\d+, \d+, \d+, \d+\)", "prodvers=" + tup, out)
    out, n3 = re.subn(r"StringStruct\('FileVersion', '[^']*'\)", "StringStruct('FileVersion', '%s')" % ver, out)
    out, n4 = re.subn(r"StringStruct\('ProductVersion', '[^']*'\)", "StringStruct('ProductVersion', '%s')" % ver, out)
    if (n1, n2, n3, n4) != (1, 1, 1, 1):
        raise ValueError("version_info.txt: очікувалось по одному filevers/prodvers/FileVersion/ProductVersion, є %r" % ((n1, n2, n3, n4),))
    return out


def build_info(tag, sha, date):
    return "версія %s, коміт %s, зібрано %s\n" % (tag, sha, date)


def _utf8_streams():
    """R109-FIX2: на Windows-раннері stdout/stderr за замовчуванням cp1252 -- друк кирилиці падав з UnicodeEncodeError ('charmap' codec).
    Примусово UTF-8 (errors=replace -- діагностика ніколи не має валити скрипт)."""
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv):
    _utf8_streams()
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, tag = argv[1], argv[2]
    try:
        if cmd == "fw":
            v = fw_version(tag)
            if len(v) > FW_VISIBLE:
                print("УВАГА: версія «%s» довша за %d символів -- «Про прошивку» покаже лише початок" % (v, FW_VISIBLE), file=sys.stderr)
            print(v)
        elif cmd == "prerelease":
            print("true" if is_prerelease(tag) else "false")
        elif cmd == "apply-cps":
            if len(argv) != 7:
                print("apply-cps TAG VERSION_INFO BUILD_INFO SHA DATE", file=sys.stderr)
                return 2
            vi, bi, sha, date = argv[3:7]
            src = open(vi, encoding="utf-8").read()
            open(vi, "w", encoding="utf-8").write(apply_version_info(src, tag))
            open(bi, "w", encoding="utf-8").write(build_info(tag, sha, date))
            print("version_info.txt і build_info.txt: версія %s" % tag)
        else:
            print("невідома підкоманда: " + cmd, file=sys.stderr)
            return 2
    except ValueError as e:
        print("ПОМИЛКА: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
