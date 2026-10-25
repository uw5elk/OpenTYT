#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Шукає застарілі форми термінів у текстах і коді інструментів (R32 T1).

ЧОМУ. У R30 і R31 бандли приносили назад старий термін, бо збиралися від бази, де він ще лежав, -- обидва рази це дало конфлікт зливання
в `cps_link.py`. Тепер стару форму ловить перевірка: у `tests/run_tests.sh`, у CI і в наборі «перед доставкою».

ЯК ДОДАТИ НОВЕ СЛОВО. Одним рядком у `OLD_FORMS` нижче: `("стара основа", "нова основа")`. Збіг -- за ОСНОВОЮ без урахування регістру, тож одна
пара ловить усі відмінки й словоформи (стара основа + будь-яке закінчення). Нова основа потрібна лише для `--fix` та підказки.

Що скануємо: `*.py`, `*.md`, `*.sh`, `*.yml`, `*.yaml`, `*.txt` у всьому репозиторії.
Що НЕ скануємо: `application/` (код прошивки), будь-який каталог `languages/` (файли в cp1251), `.git`, `.build`, `__pycache__`, `FirmwareLoader`, а також
сам цей файл (у ньому старі основи -- дані). Рядок можна позначити винятком, дописавши в нього `term-ok` (для цитат, де стара форма потрібна навмисно).
Файл, що не декодується як UTF-8, пропускається з попередженням (це не наш предмет -- його ловить check_string_encoding.py).

Запуск:
    python3 MDUV380_firmware/tools/check_terminology.py             # перевірка; код виходу 1, якщо знайдено
    python3 MDUV380_firmware/tools/check_terminology.py --fix       # механічна заміна на нову основу (зберігає регістр першої літери)
    python3 MDUV380_firmware/tools/check_terminology.py --root DIR  # інший корінь (тести)
"""
import argparse
import os
import re
import sys

# ---- ЄДИНЕ МІСЦЕ СПИСКУ ФОРМ: (стара основа, нова основа) -------------------------------------------------------------------------------------
OLD_FORMS = [
    ("кодплуг", "кодплаг"),   # кодплуг, кодплуга, кодплугом, кодплугові ...
    ("кодплуз", "кодплаз"),   # кодплузі
]
# -----------------------------------------------------------------------------------------------------------------------------------------------

EXTENSIONS = (".py", ".md", ".sh", ".yml", ".yaml", ".txt")
SKIP_DIRS = {".git", ".build", "__pycache__", "application", "languages", "FirmwareLoader", "node_modules"}
ALLOW_MARK = "term-ok"

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SELF = os.path.abspath(__file__)


def _pattern():
    return re.compile("(" + "|".join(re.escape(o) for o, _ in OLD_FORMS) + ")", re.IGNORECASE)


def iter_files(root):
    """Усі файли потрібних розширень під `root`, без пропущених каталогів і без самого цього файла."""
    root = os.path.abspath(root)
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if not f.endswith(EXTENSIONS):
                continue
            p = os.path.join(d, f)
            if os.path.abspath(p) == SELF:
                continue
            yield p


def _read(path):
    """Текст файла або None (не UTF-8)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def find(root=None):
    """Повертає (знайдено, пропущено): знайдено = [(шлях, №рядка, рядок, збіг)], пропущено = [шлях, що не UTF-8]."""
    root = DEFAULT_ROOT if root is None else root
    pat = _pattern()
    found, skipped = [], []
    for p in iter_files(root):
        text = _read(p)
        if text is None:
            skipped.append(p)
            continue
        for n, line in enumerate(text.split("\n"), 1):
            if ALLOW_MARK in line:
                continue
            m = pat.search(line)
            if m:
                found.append((os.path.relpath(p, root), n, line.strip(), m.group(0)))
    return found, skipped


def _replace_stem(match_text, new_stem_for):
    """Підставляє нову основу, зберігаючи регістр: перша велика -- перша велика; усе велике -- усе велике."""
    low = match_text.lower()
    new = new_stem_for[low]
    if match_text.isupper():
        return new.upper()
    if match_text[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


def fix(root=None):
    """Механічна заміна старих основ на нові в усіх скануваних файлах. Повертає {шлях: кількість замін}."""
    root = DEFAULT_ROOT if root is None else root
    pat = _pattern()
    mapping = {o.lower(): n for o, n in OLD_FORMS}
    changed = {}
    for p in iter_files(root):
        text = _read(p)
        if text is None:
            continue
        out_lines, cnt = [], 0
        for line in text.split("\n"):
            if ALLOW_MARK in line:
                out_lines.append(line)
                continue
            new, k = pat.subn(lambda m: _replace_stem(m.group(0), mapping), line)
            cnt += k
            out_lines.append(new)
        if cnt:
            with open(p, "wb") as fh:
                fh.write("\n".join(out_lines).encode("utf-8"))
            changed[os.path.relpath(p, root)] = cnt
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description="R32 T1: перевірка застарілих форм термінів.")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="корінь для сканування (типово -- корінь репозиторію)")
    ap.add_argument("--fix", action="store_true", help="замінити знайдене на нову основу")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.root):
        print("Немає каталогу: %s" % a.root)
        return 2
    if a.fix:
        ch = fix(a.root)
        for p, k in sorted(ch.items()):
            print("замінено %4d  %s" % (k, p))
        print("Усього файлів: %d, замін: %d" % (len(ch), sum(ch.values())))
    found, skipped = find(a.root)
    for p in skipped:
        print("попередження: не UTF-8, пропущено: %s" % os.path.relpath(p, a.root))
    if not found:
        print("Чисто: застарілих форм термінів немає (перевірено форм: %d)" % len(OLD_FORMS))
        return 0
    for p, n, line, m in found:
        new = next((nn for oo, nn in OLD_FORMS if m.lower().startswith(oo)), "нова форма")
        print("%s:%d: «%s» -> %s…  | %s" % (p, n, m, new, line[:100]))
    print("Знайдено застарілих форм: %d (у файлах: %d). Виправити: python3 MDUV380_firmware/tools/check_terminology.py --fix"
          % (len(found), len({f[0] for f in found})))
    return 1


if __name__ == "__main__":
    sys.exit(main())
