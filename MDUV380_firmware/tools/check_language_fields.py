#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R44-fix F3: звіряє перелік мовних полів `stringsTable_t` (uiLanguage.h) з УСІМА мовними файлами (languages/*.h).

Навіщо. Правило «нові мовні поля -- ОСТАННІМИ, код і ініціалізатори -- під тим самим #if» тримається на увазі, а розбіжність не завжди видно: поле, якого нема у
файлі, мовчки стає порожнім рядком (меню з порожнім пунктом), зайвий ініціалізатор -- помилка лише тієї збірки, яку ніхто не запускав. Тут розбіжність падає ОДРАЗУ,
з назвою поля, файла й набору прапорців, при якому вона є.

Що перевіряється. Для КОЖНОЇ комбінації прапорців, що трапляються в умовах `#if` (uiLanguage.h і мовні файли; усі 2^N комбінацій) -- для кожного файла:
  1. кількість: активних полів структури стільки ж, скільки активних ініціалізаторів `.поле =` у файлі;
  2. склад: немає поля структури без ініціалізатора («порожній рядок у меню») і ініціалізатора без поля структури;
  3. порядок: ініціалізатори йдуть у тому самому порядку, що й поля структури (стокове правило; код читає структуру арифметикою вказівників, а CPS пише файл мови
     за цією розкладкою);
  4. дублі: поле не ініціалізується двічі.
Умови `#if/#ifdef/#ifndef/#elif/#else` обчислюються, тож «поле під одним #if у структурі і під іншим у файлі» видно як розбіжність складу. Файли, які не знають форкових
прапорців (німецька, японська... -- стокові, без полів форка), перевіряються лише при ВИМКНЕНИХ форкових прапорцях; english.h і ukrainian.h (підтримуються нами) -- у всіх
комбінаціях, де вони компілюються (ukrainian.h -- лише з LANGUAGE_BUILD_UKRAINIAN, як у uiLocalisation.c; english.h -- з будь-яким).

Лише читання; нічого не збирає. Код виходу 1 -- є розбіжності.   Запуск: python3 tools/check_language_fields.py [--root КАТАЛОГ_MDUV380_firmware] [--quiet]"""
import argparse
import itertools
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
LANG_REL = os.path.join("application", "include", "user_interface", "languages")
STRUCT_FILE = "uiLanguage.h"
STRICT = ("english.h", "ukrainian.h")          # файли форка: перевіряються по всіх комбінаціях
FORK_FLAG_PREFIXES = ("ENABLE_", "LANGUAGE_BUILD_", "APRS_RX")
BASE_DEFINED = {"PLATFORM_MDUV380", "PLATFORM_VARIANT_UV380_PLUS_10W"}   # цільова платформа форка
MAX_FLAGS = 14
# Відомі прогалини СТОКОВИХ мовних файлів (не ваші: німецька, японська... не підтримуються форком): поле додано форком під HAS_COLOURS (2026-09-03, «S-метр у шапці»),
# у стокових файлах його нема -- там порожній рядок у пункті Options->Display. Це не провал; усе ІНШЕ в стокових файлах і ВСЕ в english.h / ukrainian.h -- провал.
KNOWN_STOCK_GAPS = {"smeter_header"}

_RE_COND = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)$")
_RE_STRUCT_FIELD = re.compile(r"^\s*(?:const\s+)?(?:char|uint8_t)\s+(\w+)\s*\[")
_RE_INIT = re.compile(r"^\s*\.(\w+)\s*=")
_RE_DEFINED = re.compile(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)")


def _strip(text):
    """Прибирає коментарі `//` і `/* */` з рядка умови (мовні файли в cp1251: читаємо як latin-1, байти не втрачаються)."""
    text = re.sub(r"/\*.*?\*/", " ", text)
    return text.split("//")[0].strip()


def _norm_expr(kind, rest):
    rest = _strip(rest)
    if kind == "ifdef":
        return "defined(%s)" % rest.split()[0]
    if kind == "ifndef":
        return "!defined(%s)" % rest.split()[0]
    return rest


def _to_py(expr):
    """C-вираз препроцесора -> python-вираз над множиною DEF."""
    e = _RE_DEFINED.sub(lambda m: "(%r in DEF)" % (m.group(1) or m.group(2)), expr)
    e = e.replace("&&", " and ").replace("||", " or ")
    e = re.sub(r"!(?!=)", " not ", e)
    return e


class Cond:
    """Умова-ланцюжок кадру #if: перелік (вираз, заперечені попередні гілки)."""
    __slots__ = ("exprs",)

    def __init__(self, exprs):
        self.exprs = exprs                  # [(py_expression, [py_expr_of_previous_branches])]

    def ok(self, DEF):
        for cur, prev in self.exprs:
            if prev and any(eval(p, {"DEF": DEF}) for p in prev):
                return False
            if cur is not None and not eval(cur, {"DEF": DEF}):
                return False
        return True


def _walk(path, line_filter):
    """Читає файл, веде стек умов і для кожного рядка, що пройшов `line_filter` (-> ім'я або None), повертає (ім'я, номер_рядка, стек_умов_кортежем, сирі_вирази)."""
    with open(path, "rb") as f:
        lines = f.read().decode("latin-1").splitlines()
    stack = []          # кадри: {"branches": [py], "cur": py|None}
    out, flags = [], set()
    for no, line in enumerate(lines, 1):
        m = _RE_COND.match(line)
        if m:
            kind, rest = m.group(1), m.group(2)
            if kind in ("if", "ifdef", "ifndef"):
                expr = _norm_expr(kind, rest)
                flags.update(a or b for a, b in _RE_DEFINED.findall(expr))
                py = _to_py(expr)
                stack.append({"branches": [], "cur": py, "raw": expr})
            elif kind == "elif":
                fr = stack[-1]
                fr["branches"].append(fr["cur"])
                expr = _norm_expr(kind, rest)
                flags.update(a or b for a, b in _RE_DEFINED.findall(expr))
                fr["cur"], fr["raw"] = _to_py(expr), expr
            elif kind == "else":
                fr = stack[-1]
                fr["branches"].append(fr["cur"])
                fr["cur"], fr["raw"] = None, "else"
            elif kind == "endif":
                stack.pop()
            continue
        name = line_filter(line)
        if name:
            conds = tuple((fr["cur"], tuple(fr["branches"])) for fr in stack)
            out.append((name, no, conds, tuple(fr["raw"] for fr in stack)))
    return out, flags


def _active(conds, DEF, cache):
    r = cache.get(conds)
    if r is None:
        r = all((cur is None or eval(cur, {"DEF": DEF})) and not any(eval(p, {"DEF": DEF}) for p in prev) for cur, prev in conds)
        cache[conds] = r
    return r


def _is_struct_open(line):
    return line


def load(root):
    ldir = os.path.join(root, LANG_REL)
    sfile = os.path.join(ldir, STRUCT_FILE)
    fields, sflags = _walk(sfile, lambda ln: (_RE_STRUCT_FIELD.match(ln) or [None, None])[1] if _RE_STRUCT_FIELD.match(ln) else None)
    files = {}
    allflags = set(sflags)
    for fn in sorted(os.listdir(ldir)):
        if not fn.endswith(".h") or fn == STRUCT_FILE:
            continue
        p = os.path.join(ldir, fn)
        with open(p, "rb") as f:
            head = f.read().decode("latin-1")
        if "stringsTable_t" not in head or not re.search(r"^\s*\.magicNumber\s*=", head, re.M):
            continue                           # не мовна таблиця (aes_ua.h, rctl_ua.h і т.п. -- рядкові константи)
        inits, flg = _walk(p, lambda ln: (_RE_INIT.match(ln) or [None, None])[1] if _RE_INIT.match(ln) else None)
        files[fn] = (inits, flg)
        allflags |= flg
    return fields, files, allflags


def flags_of_interest(allflags):
    fl = sorted(f for f in allflags if f.startswith(FORK_FLAG_PREFIXES) or f == "HAS_COLOURS")
    return fl


def check(root, quiet=False):
    fields, files, allflags = load(root)
    if not fields:
        return ["Не знайдено жодного поля `const char ...[...]` у %s -- розбір зламано або шлях хибний (%s)" % (STRUCT_FILE, root)]
    flags = flags_of_interest(allflags)
    if len(flags) > MAX_FLAGS:
        return ["Занадто багато прапорців в умовах (%d > %d): %s -- розшир перевірку свідомо" % (len(flags), MAX_FLAGS, flags)]
    problems = []
    seen = set()

    def report(kind, fn, field, combo, detail):
        key = (kind, fn, field)
        if key in seen:
            return
        seen.add(key)
        on = [f for f, v in zip(flags, combo) if v]
        problems.append("%s: файл %s, поле «%s»: %s (прапорці: %s)" % (kind, fn, field, detail, " ".join("-D" + f for f in on) or "жодного"))

    gaps = {}
    stats = {"комбінацій": 0, "файлів": len(files), "полів у структурі (макс.)": 0, "ініціалізаторів у ukrainian.h (макс.)": 0}
    fork_off = [f for f in flags if f.startswith(("ENABLE_", "LANGUAGE_BUILD_", "APRS_RX"))]
    # дублі -- незалежно від прапорців (перший-ліпший збіг у межах одного #if-кадру не рахуємо дублем лише, якщо гілки взаємовиключні -- перевіряється нижче)
    for combo in itertools.product((False, True), repeat=len(flags)):
        DEF = set(BASE_DEFINED) | {f for f, v in zip(flags, combo) if v}
        ua = "LANGUAGE_BUILD_UKRAINIAN" in DEF
        forks_on = any(f in DEF for f in fork_off)
        cache = {}
        sfields = [n for n, _no, conds, _raw in fields if _active(conds, DEF, cache)]
        stats["комбінацій"] += 1
        stats["полів у структурі (макс.)"] = max(stats["полів у структурі (макс.)"], len(sfields))
        sset = set(sfields)
        for fn, (inits, flg) in files.items():
            if fn == "ukrainian.h" and not ua:
                pass                           # у збірці без українського прапорця цей файл не компілюється, але має узгоджуватись і так
            strict = fn in STRICT
            if not strict and forks_on:
                continue                       # стокова мова + прапорці форка: такого поєднання в збірках нема
            cache2 = {}
            ifields = [n for n, _no, conds, _raw in inits if _active(conds, DEF, cache2)]
            if fn == "ukrainian.h":
                stats["ініціалізаторів у ukrainian.h (макс.)"] = max(stats["ініціалізаторів у ukrainian.h (макс.)"], len(ifields))
            iset = set(ifields)
            # дублі
            if len(iset) != len(ifields):
                dup = next(n for n in ifields if ifields.count(n) > 1)
                report("ДУБЛЬ ініціалізатора", fn, dup, combo, "поле ініціалізується двічі")
            for n in sfields:
                if n not in iset:
                    if not strict and n in KNOWN_STOCK_GAPS:
                        gaps.setdefault(n, set()).add(fn)
                        continue
                    report("ПОЛЕ БЕЗ ЗНАЧЕННЯ", fn, n, combo, "є в структурі, нема ініціалізатора -- у меню буде порожній рядок")
            for n in ifields:
                if n not in sset:
                    report("ЗАЙВИЙ ІНІЦІАЛІЗАТОР", fn, n, combo, "поля нема в структурі (або воно під іншою умовою) -- збірка з цими прапорцями не скомпілюється")
            if sset == iset and len(sfields) == len(ifields) and sfields != ifields:
                a = next(i for i, (x, y) in enumerate(zip(sfields, ifields)) if x != y)
                report("ПОРЯДОК", fn, ifields[a], combo, "на позиції %d структура має «%s», файл -- «%s»; нові поля мають іти ОСТАННІМИ й в одному порядку" % (a + 1, sfields[a], ifields[a]))
            if len(sfields) != len(ifields) and not (sset - iset) and not (iset - sset):
                report("КІЛЬКІСТЬ", fn, "?", combo, "полів %d, ініціалізаторів %d" % (len(sfields), len(ifields)))
    if gaps and not quiet:
        for n, fs in sorted(gaps.items()):
            print("check_language_fields: відома прогалина стокових мов: поле «%s» є в структурі (HAS_COLOURS), нема у %d стокових файлах -- порожній рядок, не провал" % (n, len(fs)))
    if not quiet:
        print("check_language_fields: комбінацій прапорців %d (%s), мовних файлів %d, полів у структурі до %d, ініціалізаторів у ukrainian.h до %d" % (
            stats["комбінацій"], ", ".join(flags), stats["файлів"], stats["полів у структурі (макс.)"], stats["ініціалізаторів у ukrainian.h (макс.)"]))
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=DEFAULT_ROOT, help="каталог MDUV380_firmware (за замовчуванням -- той, де лежить цей скрипт)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    problems = check(args.root, args.quiet)
    if problems:
        print("\nПРОВАЛ: розбіжності мовних полів (%d):" % len(problems))
        for p in problems[:60]:
            print("  - " + p)
        if len(problems) > 60:
            print("  ... і ще %d" % (len(problems) - 60))
        sys.exit(1)
    print("check_language_fields: усе гаразд (поля, порядок, умови збігаються в усіх мовних файлах)")


if __name__ == "__main__":
    main()
