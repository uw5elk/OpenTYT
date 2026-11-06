#!/usr/bin/env python3
"""
check_wake_ifdef.py -- R58/R59: уся діагностика пробудження (ENABLE_WAKE_DIAG) і «Роумінг» (ENABLE_ROAM_RETRY) живуть ЛИШЕ під #if.

Навіщо. Типова й користувацькі збірки мають лишатись байт-у-байт тими самими. Хостові тести цього не
бачать, повний diff прошивки -- довгий. Тут три статичні перевірки:

  1. НОВІ файли (wake_diag.[ch], wake_hop.[ch], wake_hop_sel.c, roam_cfg.[ch], menuRoam.c, roam_ui.h, wakediag_ua.h,
     roam_ua.h): жодного коду (оголошень, визначень) поза #if defined(ENABLE_WAKE_DIAG / ENABLE_ROAM_RETRY) -- лише
     #include і захисник заголовка.
  2. ЗМІНЕНІ файли (HR-C6000.c, uiTxScreen.c, uiChannelMode.c, menuSystem.[ch], menuDisplayMenuList.c, applicationMain.c,
     codeplug.h, usb_com.c): кожне згадування нових ідентифікаторів (wakeDiag*, wakeHop*, roam*, MENU_ROAM, ROAM_*,
     HRC6000RestartWakeForRoam, ...) -- у гілці #if з цими дефайнами (не в #else). Коментарі не рахуються.
     menuMessages.c (журнал переїхав у «Роумінг») нових ідентифікаторів НЕ містить взагалі.
  3. CI (.github/workflows/build.yml): ENABLE_WAKE_DIAG згадується лише в джобі build-ukrainian-roam-diag, ENABLE_ROAM_RETRY --
     лише в build-ukrainian-roam-diag, build-ukrainian-roam і (R60C, після перевірки на залізі) build-ukrainian -- ENABLE_WAKE_DIAG у користувацькі збірки
     потрапити не може.

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
    "include/functions/roam_cfg.h",
    "include/user_interface/roam_ui.h",
    "include/user_interface/languages/wakediag_ua.h",
    "include/user_interface/languages/roam_ua.h",
    "source/functions/wake_diag.c",
    "source/functions/wake_hop.c",
    "source/functions/wake_hop_sel.c",
    "source/functions/roam_cfg.c",
    "source/user_interface/menuRoam.c",
]
CHANGED_FILES = [
    "source/hardware/HR-C6000.c",
    "source/user_interface/uiTxScreen.c",
    "source/user_interface/uiChannelMode.c",
    "source/user_interface/menuSystem.c",
    "source/user_interface/menuDisplayMenuList.c",
    "source/applicationMain.c",
    "source/usb/usb_com.c",
    "include/user_interface/menuSystem.h",
    "include/functions/codeplug.h",
]
# Файли, де нових ідентифікаторів не має бути ВЗАГАЛІ (R59: журнал пробудження переїхав із «Повідомлень» у «Роумінг»).
ABSENT_FILES = [
    "source/user_interface/menuMessages.c",
]
WAKE_COND = re.compile(r"ENABLE_(WAKE_DIAG|ROAM_RETRY)")
NEW_IDENT = re.compile(
    r"\b(wakeDiag\w*|wakeHop\w*|HRC6000RestartWakeForRoam|MSG_WAKE_DIAG|MSGS_WAKE_ITEM|WAKE_REFRESH_MS|"
    r"wakeUpdate|wakeEvent|wakeAge|WAKE_ITEM|WAKE_DIAG\w*|WAKE_HOP\w*|"
    r"roam(Cfg|Is|Active|Clear|Current|List|Toggle|Load)\w*|ROAM_\w+|MENU_ROAM|menuRoam|"
    r"CODEPLUG_CUSTOM_DATA_TYPE_ROAM_CFG|roam_cfg|roam_ui)\b")
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


CI_ALLOWED = {
    "ENABLE_WAKE_": {"build-ukrainian-roam-diag"},
    "ENABLE_ROAM_": {"build-ukrainian-roam-diag", "build-ukrainian-roam", "build-ukrainian", "build-ukrainian-rodata-after-codec"},     # R60C: роумінг -- в основній українській збірці; R63C: ТЕСТОВИЙ джоб з .rodata після кодека (та сама конфігурація, що build-ukrainian)
}


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
        for token, jobs in CI_ALLOWED.items():
            if token in line and job not in jobs:
                bad.append("build.yml:%d: %s* поза дозволеними джобами %s (джоб: %s)" % (no, token, sorted(jobs), job))
    for need in ("build-ukrainian-roam-diag", "build-ukrainian-roam"):
        if not re.search(r"(?m)^  " + re.escape(need) + r":\s*$", text):
            bad.append("build.yml: немає джоба " + need)
    if re.search(r"(?m)^  build-ukrainian-wake-diag:\s*$", text):
        bad.append("build.yml: лишився старий джоб build-ukrainian-wake-diag (перейменовано в build-ukrainian-roam-diag)")
    return bad


def run():
    bad = []
    for rel in NEW_FILES:
        p = os.path.join(APP, rel)
        if not os.path.exists(p):
            bad.append("немає файла " + rel); continue
        if rel.endswith("_ua.h"):
            bad += check_macros_only(rel, open(p, encoding="cp1251", errors="replace").read())
        else:
            bad += check_new(rel, open(p, encoding="utf-8", errors="replace").read())
    for rel in CHANGED_FILES:
        bad += check_changed(rel, open(os.path.join(APP, rel), encoding="utf-8", errors="replace").read())
    for rel in ABSENT_FILES:
        for no, line, _w, _pp in walk(open(os.path.join(APP, rel), encoding="utf-8", errors="replace").read()):
            if NEW_IDENT.search(line):
                bad.append("%s:%d: у цьому файлі нових ідентифікаторів бути не повинно: %s" % (rel, no, line[:80]))
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
    assert check_changed("c.c", "#if defined(ENABLE_ROAM_RETRY) && 1\nwakeHopBegin();\n#endif\nwakeHopTry();\n"), "виклик після #endif ловиться"
    assert check_changed("c.c", "#if defined(ENABLE_ROAM_RETRY)\nroamClear();\n#else\nx();\n#endif\n") == []
    assert check_changed("c.c", "roamIsActive();\n"), "roam* без #if ловиться"
    assert check_changed("c.c", "#if defined(ENABLE_ROAM_RETRY)\nint a;\n#else\nroamClear();\n#endif\n"), "roam* в #else ловиться"
    assert check_changed("c.c", "x = ROAM_MENU_NAME;\n"), "ROAM_* без #if ловиться"
    assert check_changed("c.c", "if (nonVolatileSettings.roaming != ROAMING_OFF) {}\nCHANNEL_FLAG_ROAMING;\n") == [], "стокове «roaming» не чіпаємо"
    assert check_macros_only("m.h", "#define A \"x\"\n#define B 2\n") == []
    assert check_macros_only("m.h", "#define A 1\nint leak;\n"), "код у макро-заголовку ловиться"
    ok = ("jobs:\n  a:\n    x: 1\n  build-ukrainian-roam-diag:\n    run: make ENABLE_WAKE_DIAG=1 ENABLE_ROAM_RETRY=1\n"
          "  build-ukrainian-roam:\n    run: make ENABLE_ROAM_RETRY=1\n")
    assert check_ci(ok) == [], check_ci(ok)
    assert check_ci(ok + "  b:\n    run: make ENABLE_WAKE_DIAG=1\n"), "дефайн в іншому джобі ловиться"
    assert check_ci(ok + "  b:\n    run: make ENABLE_ROAM_RETRY=1\n"), "ROAM_RETRY в іншому джобі ловиться"
    assert check_ci(ok + "  build-ukrainian:\n    run: make ENABLE_ROAM_RETRY=1\n") == [], "R60C: ROAM_RETRY в основній українській збірці дозволено"
    assert check_ci(ok + "  build-ukrainian:\n    run: make ENABLE_WAKE_DIAG=1\n"), "R60C: журнал в основній українській збірці заборонено"
    assert check_ci(ok.replace("make ENABLE_ROAM_RETRY=1\n", "make ENABLE_WAKE_DIAG=1\n")), "WAKE_DIAG у джобі без журналу ловиться"
    assert check_ci("jobs:\n  a:\n    x: 1\n"), "немає джобів -- ловиться"
    assert check_ci(ok + "  build-ukrainian-wake-diag:\n    x: 1\n"), "старий джоб ловиться"
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
