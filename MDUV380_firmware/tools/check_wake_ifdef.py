#!/usr/bin/env python3
"""
check_wake_ifdef.py -- R58: уся діагностика пробудження (ENABLE_WAKE_DIAG / ENABLE_WAKE_HOP_TEST) живе ЛИШЕ під #if.

Навіщо. Типова й користувацькі збірки мають лишатись байт-у-байт тими самими. Хостові тести цього не
бачать, повний diff прошивки -- довгий. Тут три статичні перевірки:

  1. НОВІ файли (wake_diag.[ch], wake_hop.[ch], wake_hop_sel.c, wakediag_ua.h): жодного коду
     (оголошень, визначень) поза #if defined(ENABLE_WAKE_...) -- лише #include і захисник заголовка.
  2. ЗМІНЕНІ файли (HR-C6000.c, uiTxScreen.c, menuMessages.c, usb_com.c): кожне згадування нових
     ідентифікаторів (wakeDiag*, wakeHop*, HRC6000RestartWakeForRoam, MSG_WAKE_DIAG, ...) -- у гілці #if
     з ENABLE_WAKE_* (не в #else). Коментарі не рахуються.
  3. CI (.github/workflows/build.yml): ENABLE_WAKE_* згадується лише в джобі build-ukrainian-wake-diag --
     у користувацькі збірки дефайни потрапити не можуть.

    python3 MDUV380_firmware/tools/check_wake_ifdef.py [--selftest]
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.normpath(os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(FW, ".."))
APP = os.path.join(FW, "application")

NEW_FILES = [
    "include/functions/wake_diag.h",
    "include/functions/wake_hop.h",
    "include/user_interface/languages/wakediag_ua.h",
    "source/functions/wake_diag.c",
    "source/functions/wake_hop.c",
    "source/functions/wake_hop_sel.c",
]
CHANGED_FILES = [
    "source/hardware/HR-C6000.c",
    "source/user_interface/uiTxScreen.c",
    "source/user_interface/menuMessages.c",
    "source/usb/usb_com.c",
]
WAKE_COND = re.compile(r"ENABLE_WAKE_(DIAG|HOP_TEST)")
NEW_IDENT = re.compile(
    r"\b(wakeDiag\w*|wakeHop\w*|HRC6000RestartWakeForRoam|MSG_WAKE_DIAG|MSGS_WAKE_ITEM|WAKE_REFRESH_MS|"
    r"wakeUpdate|wakeEvent|wakeAge|WAKE_ITEM|WAKE_DIAG\w*|WAKE_HOP\w*)\b")
GUARD = re.compile(r"^\s*#\s*(ifndef|define|endif)\b.*_H_\b|^\s*#\s*endif\s*/[*/].*_H_")


def strip_comments(text):
    """Прибрати /* */ і // коментарі та літерали-рядки лишити як є (нам важливі лише ідентифікатори й директиви)."""
    out = []
    i, n = 0, len(text)
    in_str = None
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "\"'":
            in_str = c; out.append(c); i += 1; continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j)); i = j; continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j; continue
        out.append(c); i += 1
    return "".join(out)


def logical_lines(text):
    """Склеїти рядки з продовженням '\\' -> [(номер_початку, текст)]."""
    res, buf, start = [], "", None
    for no, line in enumerate(text.split("\n"), 1):
        if start is None:
            start = no
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
            continue
        res.append((start, buf + line)); buf, start = "", None
    if buf:
        res.append((start, buf))
    return res


def walk(text):
    """Генерує (номер, рядок, у_гілці_wake: bool) для кожного рядка; обробляє #if/#ifdef/#elif/#else/#endif."""
    stack = []   # елемент: [is_wake_cond, in_else]
    for no, line in logical_lines(strip_comments(text)):
        s = line.strip()
        m = re.match(r"#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)", s)
        if m:
            d, rest = m.group(1), m.group(2)
            if d in ("if", "ifdef", "ifndef"):
                stack.append([bool(WAKE_COND.search(rest)) and d != "ifndef", False])
            elif d == "elif":
                if stack:
                    stack[-1][1] = True   # гілку #elif вважаємо НЕ wake (у цьому проєкті такого немає)
            elif d == "else":
                if stack:
                    stack[-1][1] = True
            elif d == "endif":
                if stack:
                    stack.pop()
            yield no, s, any(w and not e for w, e in stack) if d != "endif" else False, True
            continue
        yield no, s, any(w and not e for w, e in stack), s.startswith("#")


def check_macros_only(name, text):
    """Заголовок лише з #define (мовні рядки): код не допускається, #define поза #if -- можна (макроси коду не дають)."""
    bad = []
    for no, s, _in_wake, is_pp in walk(text):
        if s and not is_pp:
            bad.append("%s:%d: код у заголовку лише для макросів: %s" % (name, no, s[:80]))
    return bad


def check_new(name, text):
    bad = []
    for no, s, in_wake, is_pp in walk(text):
        if not s or in_wake:
            continue
        if is_pp:
            if re.match(r"#\s*(include|ifndef|define|endif|if|ifdef|else|elif)\b", s):
                # #define поза wake допустимий лише для захисника заголовка (_H_)
                if s.startswith("#define") and not re.match(r"#define\s+\w+_H_\s*$", s):
                    bad.append((no, "#define поза #if ENABLE_WAKE_*: " + s))
                continue
            bad.append((no, "директива поза #if ENABLE_WAKE_*: " + s))
            continue
        bad.append((no, "код поза #if ENABLE_WAKE_*: " + s[:80]))
    return ["%s:%d: %s" % (name, no, msg) for no, msg in bad]


def check_changed(name, text):
    bad = []
    for no, s, in_wake, is_pp in walk(text):
        if in_wake:
            continue
        if NEW_IDENT.search(s) and not (is_pp and re.match(r"#\s*(if|ifdef|elif)\b", s)):
            bad.append("%s:%d: нова діагностика поза #if ENABLE_WAKE_*: %s" % (name, no, s[:90]))
    return bad


def check_ci(text):
    bad = []
    job = None
    in_jobs = False
    for no, line in enumerate(text.split("\n"), 1):
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True; continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if in_jobs and m:
            job = m.group(1)
        if line.lstrip().startswith("#"):
            continue   # коментар YAML (опис джоба стоїть ПЕРЕД його заголовком)
        if "ENABLE_WAKE_" in line and job != "build-ukrainian-wake-diag":
            bad.append("build.yml:%d: ENABLE_WAKE_* поза джобом build-ukrainian-wake-diag (джоб: %s)" % (no, job))
    if "build-ukrainian-wake-diag" not in text:
        bad.append("build.yml: немає джоба build-ukrainian-wake-diag")
    return bad


def run():
    bad = []
    for rel in NEW_FILES:
        p = os.path.join(APP, rel)
        if not os.path.exists(p):
            bad.append("немає файла " + rel); continue
        if rel.endswith("wakediag_ua.h"):
            bad += check_macros_only(rel, open(p, encoding="cp1251", errors="replace").read())
        else:
            bad += check_new(rel, open(p, encoding="utf-8", errors="replace").read())
    for rel in CHANGED_FILES:
        bad += check_changed(rel, open(os.path.join(APP, rel), encoding="utf-8", errors="replace").read())
    ci = os.path.join(ROOT, ".github", "workflows", "build.yml")
    if os.path.exists(ci):
        bad += check_ci(open(ci, encoding="utf-8").read())
    else:
        bad.append("немає .github/workflows/build.yml")
    return bad


def selftest():
    good_new = "#ifndef X_H_\n#define X_H_\n#include <stdint.h>\n#if defined(ENABLE_WAKE_DIAG)\nint a;\nvoid f(void);\n#endif\n#endif\n"
    assert check_new("g.h", good_new) == [], check_new("g.h", good_new)
    assert check_new("b.c", "#if defined(ENABLE_WAKE_DIAG)\nint a;\n#endif\nint leak;\n"), "код поза #if має ловитись"
    assert check_new("b.c", "int leak;\n#if defined(ENABLE_WAKE_DIAG)\nint a;\n#endif\n"), "код до #if має ловитись"
    assert check_new("b.c", "#if defined(ENABLE_WAKE_DIAG)\nint a;\n#else\nint other;\n#endif\n"), "#else ловиться"
    assert check_new("b.c", "#define LEAK 1\n#if defined(ENABLE_WAKE_DIAG)\n#endif\n"), "#define поза #if ловиться"
    assert check_new("b.c", "/* коментар */\n// ще\n#include \"a.h\"\n#if defined(ENABLE_WAKE_DIAG)\nint a;\n#endif\n") == []
    assert check_changed("c.c", "void f(void)\n{\n#if defined(ENABLE_WAKE_DIAG)\n\twakeDiagFail(1);\n#endif\n}\n") == []
    assert check_changed("c.c", "void f(void)\n{\n\twakeDiagFail(1);\n}\n"), "виклик без #if має ловитись"
    assert check_changed("c.c", "#if defined(ENABLE_WAKE_DIAG)\nint x;\n#else\nwakeDiagFail(1);\n#endif\n"), "виклик у #else має ловитись"
    assert check_changed("c.c", "// wakeDiagFail(1);\n/* wakeHopTry */\nint y;\n") == [], "коментарі не рахуються"
    assert check_changed("c.c", "#if defined(ENABLE_SMS_DIAG)\n#if defined(ENABLE_WAKE_DIAG)\nwakeEvent();\n#endif\n#endif\n") == []
    assert check_changed("c.c", "#if defined(ENABLE_WAKE_HOP_TEST) && 1\nwakeHopBegin();\n#endif\nwakeHopTry();\n"), "виклик після #endif ловиться"
    assert check_macros_only("m.h", "#define A \"x\"\n#define B 2\n") == []
    assert check_macros_only("m.h", "#define A 1\nint leak;\n"), "код у макро-заголовку ловиться"
    ok = "jobs:\n  a:\n    x: 1\n  build-ukrainian-wake-diag:\n    run: make ENABLE_WAKE_DIAG=1\n"
    assert check_ci(ok) == [], check_ci(ok)
    assert check_ci(ok + "  b:\n    run: make ENABLE_WAKE_DIAG=1\n"), "дефайн в іншому джобі ловиться"
    assert check_ci("jobs:\n  a:\n    x: 1\n"), "немає джоба -- ловиться"
    assert check_ci(ok.replace("  a:", "  a:\n    # ENABLE_WAKE_DIAG у коментарі")) == [], "коментар YAML не рахується"
    print("check_wake_ifdef selftest: ок")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    problems = run()
    for p in problems:
        print(p)
    if problems:
        print("ПРОВАЛ: %d" % len(problems))
        sys.exit(1)
    print("check_wake_ifdef: ок")
