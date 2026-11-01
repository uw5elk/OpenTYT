# -*- coding: utf-8 -*-
"""font_scenarios.py -- R50-fix: сценарії шрифту й масштабу для тестів верстки.

Чому: «обрізано / не обрізано» залежить від метрик шрифту. На хості розробки типовий шрифт Tk інший, ніж у CI (xvfb), а на Windows -- ще інший
(Segoe UI) і з масштабом екрана 125-150 %. Тест, що перевіряє верстку лише при одному випадковому шрифті, нічого не гарантує.
Тут -- набір сценаріїв: сімейство шрифту (None = типове для системи) × масштаб у відсотках (100 % = 96 dpi, як `tk scaling` на Windows при 100 %).

Використання (у тесті):
    snap = fs.snapshot(root)
    for sc in fs.scenarios():
        fs.apply(root, sc)
        ... відкрити діалог / пройти зондом layout_probe ...
    fs.restore(root, snap)

Сценарії, чиє сімейство в системі відсутнє, пропускаються (scenarios() повертає лише ті, що можна застосувати); сценарії зі «своїм» сімейством
(None) є завжди, тож перелік ніколи не порожній."""
import tkinter as tk
import tkinter.font as tkfont

NAMED_FONTS = ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkTooltipFont", "TkSmallCaptionFont")
PERCENTS = (100, 125, 150)
# сімейства, що є на типових системах: DejaVu Sans -- типовий шрифт Linux/CI, Liberation Sans -- метрики Arial, Carlito -- метрики Calibri (близько до Segoe UI)
FAMILIES = (None, "DejaVu Sans", "Liberation Sans", "Carlito")
BASE_SIZE = 10


def label(sc):
    fam, pct = sc
    return "%s, %d %%" % (fam or "шрифт системи", pct)


def scenarios(root=None, families=FAMILIES, percents=PERCENTS):
    """[(сімейство|None, відсотки)], лише застосовні (сімейство є в системі)."""
    have = None
    if root is not None:
        try:
            have = set(tkfont.families(root))
        except tk.TclError:
            have = None
    out = []
    for fam in families:
        if fam is not None and have is not None and fam not in have:
            continue
        for pct in percents:
            out.append((fam, pct))
    return out


def snapshot(root):
    """Поточні шрифти й масштаб (щоб повернути після сценаріїв)."""
    fonts = {}
    for n in NAMED_FONTS:
        try:
            fonts[n] = dict(tkfont.nametofont(n, root=root).actual())
        except tk.TclError:
            pass
    return {"scaling": float(root.tk.call("tk", "scaling")), "fonts": fonts}


def apply(root, sc):
    """Застосувати сценарій до root (масштаб Tk + іменовані шрифти); віджети, створені ПІСЛЯ цього, матимуть нові метрики."""
    fam, pct = sc
    root.tk.call("tk", "scaling", 96.0 / 72.0 * pct / 100.0)
    for n in NAMED_FONTS:
        try:
            f = tkfont.nametofont(n, root=root)
        except tk.TclError:
            continue
        if fam is not None:
            f.configure(family=fam)
        f.configure(size=BASE_SIZE if n != "TkSmallCaptionFont" else BASE_SIZE - 1)


def restore(root, snap):
    root.tk.call("tk", "scaling", snap["scaling"])
    for n, d in snap["fonts"].items():
        try:
            tkfont.nametofont(n, root=root).configure(**{k: d[k] for k in ("family", "size", "weight", "slant")})
        except tk.TclError:
            pass
