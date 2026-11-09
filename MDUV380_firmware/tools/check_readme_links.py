#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R80: перевірка README.md -- відносні посилання й зображення існують, якорі (#...) відповідають заголовкам, PNG у docs/img до 300 КБ, посилання на
зображення, яких ще нема, -- лише в коментарях-заглушках <!-- TODO: фото ... -->; слова «виправлено» нема (ми не заявляємо виправлень до перевірки на залізі);
файл у UTF-8. Без мережі: зовнішні (http/https/mailto) посилання не перевіряються.
Запуск: python3 tools/check_readme_links.py [шлях/до/README.md]"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_PNG = 300 * 1024


def slug(title):
    """GitHub-подібний якір: нижній регістр, без розділових знаків, пробіли -> дефіси (кирилиця лишається)."""
    t = re.sub(r"[`*_]", "", title.strip().lower())
    t = re.sub(r"[^\w\s-]", "", t, flags=re.UNICODE)
    return re.sub(r"\s", "-", t)


def check(path):
    errs = []
    try:
        raw = open(path, "rb").read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return ["%s: не читається як UTF-8 (%s)" % (path, e)]
    base = os.path.dirname(os.path.abspath(path))
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)          # коментарі-заглушки не перевіряються
    body_nocode = re.sub(r"```.*?```", "", body, flags=re.S)
    anchors = {slug(m.group(2)) for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", body_nocode, re.M)}
    links = re.findall(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", body_nocode)
    links += re.findall(r"<img[^>]+src=\"([^\"]+)\"", body_nocode)
    seen_img = set()
    for url in links:
        if re.match(r"^(https?:|mailto:)", url):
            continue
        target, _, frag = url.partition("#")
        if not target:
            if frag and frag not in anchors:
                errs.append("якір #%s не відповідає жодному заголовку" % frag)
            continue
        p = os.path.normpath(os.path.join(base, target))
        if not os.path.exists(p):
            errs.append("немає файлу: %s" % url)
            continue
        if target.lower().endswith(".png"):
            seen_img.add(p)
            if os.path.getsize(p) > MAX_PNG:
                errs.append("зображення більше 300 КБ: %s (%d Б)" % (url, os.path.getsize(p)))
    if "виправлено" in text.lower():
        errs.append("у README є слово «виправлено» (не заявляємо виправлень до перевірки на залізі)")
    img_dir = os.path.join(base, "docs", "img")
    if os.path.isdir(img_dir):
        for fn in sorted(os.listdir(img_dir)):
            p = os.path.join(img_dir, fn)
            if fn.lower().endswith(".png") and p not in seen_img:
                errs.append("зображення docs/img/%s не використано в README" % fn)
            if fn.lower().endswith(".png") and os.path.getsize(p) > MAX_PNG:
                errs.append("зображення docs/img/%s більше 300 КБ" % fn)
    return errs


def selftest():
    """Самоперевірка: на штучному README ловить зламане посилання, зламаний якір, слово «виправлено» і НЕ чіпає закоментовану заглушку."""
    import tempfile
    d = tempfile.mkdtemp(prefix="rdm_")
    p = os.path.join(d, "README.md")
    open(p, "w", encoding="utf-8").write("# Заголовок\n[a](#заголовок) [b](#нема) [c](нема.md) ![d](docs/img/x.png)\n<!-- TODO: ![e](docs/img/y.png) -->\nвиправлено\n")
    e = check(p)
    ok = (len(e) == 4 and any("#нема" in x for x in e) and any("нема.md" in x for x in e) and any("x.png" in x for x in e) and any("виправлено" in x for x in e))
    if not ok:
        print("ПРОВАЛ: самоперевірка check_readme_links: %r" % e)
    return ok


if __name__ == "__main__":
    if not selftest():
        sys.exit(1)
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "README.md")
    errs = check(path)
    for e in errs:
        print("ПРОВАЛ:", e)
    if errs:
        sys.exit(1)
    print("check_readme_links: усе гаразд (%s)" % os.path.basename(path))
