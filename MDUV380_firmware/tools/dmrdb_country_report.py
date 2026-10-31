#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R50: як правильно відібрати «Україну» в user.csv Radioid -- за колонкою COUNTRY чи за початком DMR ID (255)? Рахує по ФАКТИЧНОМУ файлу і НІЧОГО не пише в рацію.

Запуск:  python3 MDUV380_firmware/tools/dmrdb_country_report.py ШЛЯХ/user.csv [країна] [префікс]     (типово: Ukraine 255)
Виводить: скільки рядків з країною, з префіксом, у перетині, лише за країною, лише за префіксом; які країни трапляються у «лише за префіксом» і які початки ID --
у «лише за країною». Це і є підстава вибрати фільтр: якщо «лише за…» майже порожні -- обидва способи однакові; інакше типове «або» (union) не губить нікого."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dmr_db as db   # noqa: E402


def report(rows, country="Ukraine", prefix="255", top=8):
    """rows -- db.Source.rows. -> текст звіту (рядки)."""
    cf = country.casefold()
    both = by_c = by_p = 0
    only_p_countries = collections.Counter()
    only_c_prefixes = collections.Counter()
    seen = set()
    total = 0
    for r in rows:
        rid = r["id"]
        if rid in seen:
            continue
        seen.add(rid)
        total += 1
        c = (r.get("country") or "").strip().casefold() == cf
        p = str(rid).startswith(prefix)
        by_c += c
        by_p += p
        both += c and p
        if p and not c:
            only_p_countries[(r.get("country") or "").strip() or "(порожньо)"] += 1
        if c and not p:
            only_c_prefixes[str(rid)[:3]] += 1
    lines = ["Унікальних ID у файлі: %d" % total,
             "Країна «%s» (колонка COUNTRY): %d" % (country, by_c),
             "Початок ID «%s»: %d" % (prefix, by_p),
             "У перетині (обидва): %d" % both,
             "Лише за країною (ID не з «%s»): %d" % (prefix, by_c - both),
             "Лише за префіксом (країна інша або порожня): %d" % (by_p - both),
             "Об'єднання (країна АБО префікс -- типовий фільтр панелі): %d" % (by_c + by_p - both)]
    if by_p - both:
        lines.append("  у «лише за префіксом» трапляються країни: " + ", ".join("%s=%d" % kv for kv in only_p_countries.most_common(top)))
    if by_c - both:
        lines.append("  у «лише за країною» найчастіші початки ID: " + ", ".join("%s…=%d" % kv for kv in only_c_prefixes.most_common(top)))
    return lines


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = db.read_source_file(argv[1])
    print("\n".join(report(src.rows, argv[2] if len(argv) > 2 else "Ukraine", argv[3] if len(argv) > 3 else "255")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
