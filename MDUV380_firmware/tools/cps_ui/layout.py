# -*- coding: utf-8 -*-
"""Спільна розкладка вікна CPS (R36 B1/B2/B4): таблиці з ширинами за вмістом і горизонтальною прокруткою, однакові кнопки групи, межі між
частинами панелі, що запам'ятовуються. Принцип один для всього вікна: ТЕКСТ НІКОЛИ НЕ ОБРІЗАЄТЬСЯ -- якщо місця бракує, з'являється смуга прокрутки
(або текст переноситься), а не обрізання.

Що тут є:
  FitTable / FitTreeview -- таблиця, у якої ширина кожного стовпця = найширше з (заголовок, значення рядків, мінімум), решта вільного місця
                            розподіляється за вагами стовпців; коли всі стовпці разом ширші за віджет -- горизонтальна смуга;
  equal_buttons(...)     -- кнопки групи однієї ширини (за найдовшим підписом);
  PaneMemory             -- межа між частинами (ttk.PanedWindow): мінімальні ширини частин, подвійне клацання по межі = типове положення,
                            положення пам'ятається в налаштуваннях між запусками."""
import math
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

import gui_theme as gt

CELL_PAD = 18          # запас у px до тексту комірки (відступи комірки + запас)
HEAD_PAD = 30          # запас до заголовка: відступи шапки + місце під стрілку сортування
MAX_AUTO = 420         # найширший стовпець за вмістом (довший текст обрізається лише в комірці; повний -- у підказці/редакторі)
SAMPLE_ROWS = 300      # скільки рядків міряти для ширини (таблиці на десятки тисяч рядків не гальмують)


def _font(widget, name="TkDefaultFont"):
    try:
        return tkfont.nametofont(name)
    except tk.TclError:
        return tkfont.Font(root=widget, font=name)


def text_px(widget, text, font=None):
    """Ширина тексту у px (найдовший рядок, якщо їх кілька)."""
    f = font or _font(widget)
    return max([f.measure(line) for line in str(text).split("\n")] or [0])


def ui_scale(widget):
    """Масштаб екрана відносно 96 dpi: 1.0 = 100 %, 1.25 = 125 %, 1.5 = 150 % (Windows: параметр «Масштаб» у налаштуваннях дисплея; `tk scaling` = 96/72 · масштаб).
    Менше 1.0 не буває (мінімальні розміри лише ростуть). R51: мінімальні розміри вікна й частин панелей, що були числами в пікселях, множаться на нього."""
    try:
        k = float(widget.tk.call("tk", "scaling")) / (96.0 / 72.0)
    except (tk.TclError, ValueError):
        k = 1.0
    return max(1.0, k)


# --- кнопки однієї ширини ---------------------------------------------------------------------------------------------------------

def equal_buttons(*buttons, minimum=0):
    """Однакова ширина кнопок групи: за найдовшим підписом + запас gt.BTN_EXTRA. Ширина ttk.Button задається в «символах» (ширина цифри '0')."""
    btns = [b for b in buttons if b is not None]
    if not btns:
        return 0
    f = _font(btns[0])
    zero = max(1, f.measure("0"))
    chars = max([math.ceil(f.measure(str(b.cget("text"))) / zero) for b in btns] + [minimum]) + gt.BTN_EXTRA
    for b in btns:
        b.configure(width=chars)
    return chars


# --- рядок кнопок, що переноситься ---------------------------------------------------------------------------------------------------

class FlowFrame(ttk.Frame):
    """Група елементів (кнопки, підписи), що йдуть у рядок, а коли місця бракує -- переносяться на наступний рядок (нічого не обрізається і не вилазить
    за край). Мінімальна ширина, яку група запитує у батька, = найширший елемент, тож вона не розпирає вузьку панель. Елементи створюються з
    master=flow і додаються через add(); однакову ширину кнопок задає equal_buttons() до add()."""

    def __init__(self, parent, gap=gt.GAP):
        super().__init__(parent)
        self.items = []
        self.gap = gap
        self._sig = None
        self.grid_propagate(False)
        self.bind("<Configure>", lambda _e: self.relayout())

    def add(self, widget, sticky="w"):
        self.items.append((widget, sticky))
        self.relayout(force=True)
        return widget

    def relayout(self, force=False):
        if not self.items:
            return
        avail = self.winfo_width()
        if avail <= 1:
            avail = 100000
        rows, x, row = [], 0, []
        for w, _st in self.items:
            iw = w.winfo_reqwidth()
            if row and x + iw > avail:
                rows.append(row)
                row, x = [], 0
            row.append(w)
            x += iw + self.gap
        rows.append(row)
        sig = (tuple(tuple(id(w) for w in r) for r in rows), tuple(w.winfo_reqwidth() for w, _s in self.items))
        if sig == self._sig and not force:
            return
        self._sig = sig
        y = 0
        for r in rows:
            x, rh = 0, 0
            for w in r:
                w.place(x=x, y=y)              # place, а не grid: у grid стовпці спільні для всіх рядків, і нижній рядок зсувався б
                x += w.winfo_reqwidth() + self.gap
                rh = max(rh, w.winfo_reqheight())
            y += rh + 2
        need_w = max(w.winfo_reqwidth() for w, _s in self.items)
        self.configure(width=need_w, height=max(1, y - 2))


def combo_width(combo, values=None, minimum=0, extra=3):
    """Ширина Combobox у «символах» так, щоб найдовше значення (і вибране) влізло повністю: міряється шрифтом, а не кількістю літер."""
    f = _font(combo)
    zero = max(1, f.measure("0"))
    vals = [str(v) for v in (values if values is not None else combo.cget("values"))]
    px = max([f.measure(v) for v in vals] + [0])
    chars = max(minimum, math.ceil(px / zero) + extra)
    combo.configure(width=chars)
    return chars


# --- таблиці ----------------------------------------------------------------------------------------------------------------------

class FitTreeview(ttk.Treeview):
    """Таблиця із заголовками. columns = [(id, заголовок, мінімальна ширина, вага)]; вага 0 -- не розтягувати, >0 -- частка вільного місця.

    Рядки додаються звичайним insert(): після змін ширини перераховуються самі (відкладено, раз на ітерацію циклу подій). Горизонтальна прокрутка --
    через xscrollcommand (див. FitTable)."""

    def __init__(self, parent, columns, **kw):
        kw.setdefault("show", "headings")
        super().__init__(parent, columns=[c[0] for c in columns], **kw)
        self.fit_spec = list(columns)
        self.natural = {}
        self._dirty = False
        self._fit_busy = False
        self.on_refit = None          # функція(): викликається після перерахунку потрібних ширин (FitTable оновлює свій запит)
        for cid, text, minw, _wt in columns:
            self.heading(cid, text=text)
            self.column(cid, width=minw, minwidth=minw, anchor="w", stretch=False)
            self.natural[cid] = minw
        self.bind("<Configure>", lambda _e: self._apply(), add="+")
        self._mark_dirty()

    # --- відстеження змін -----------------------------------------------------------------------

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            try:
                self.after_idle(self.refit)
            except tk.TclError:
                pass

    def insert(self, *a, **kw):
        r = super().insert(*a, **kw)
        self._mark_dirty()
        return r

    def delete(self, *a):
        r = super().delete(*a)
        self._mark_dirty()
        return r

    def item(self, iid, option=None, **kw):
        r = super().item(iid, option, **kw)
        if kw.get("values") is not None or kw.get("text") is not None:
            self._mark_dirty()
        return r

    def heading_text(self, cid):
        return str(self.heading(cid, "text"))

    # --- розрахунок -----------------------------------------------------------------------------

    def required(self):
        """{id: ширина у px, нижче якої текст заголовка чи комірки обрізався б}: найширше з мінімуму, заголовка й значень вибірки рядків (до MAX_AUTO)."""
        f = _font(self)
        hf = _font(self, "TkHeadingFont")
        rows = self.get_children("")[:SAMPLE_ROWS]
        out = {}
        for i, (cid, _t, minw, _wt) in enumerate(self.fit_spec):
            w = max(minw, text_px(self, self.heading_text(cid), hf) + HEAD_PAD)
            for r in rows:
                vals = super().item(r, "values")
                if i < len(vals):
                    w = max(w, min(MAX_AUTO, text_px(self, vals[i], f) + CELL_PAD))
            out[cid] = int(w)
        return out

    def refit(self):
        self._dirty = False
        try:
            self.natural = self.required()
            self._apply()
            if self.on_refit:
                self.on_refit()
        except tk.TclError:
            pass

    def _apply(self):
        if self._fit_busy:
            return
        self._fit_busy = True
        try:
            avail = self.winfo_width()
            nat = self.natural
            extra = avail - sum(nat.values())
            wsum = sum(wt for _c, _t, _m, wt in self.fit_spec)
            weighted = [c for c, _t, _m, wt in self.fit_spec if wt > 0]
            left = extra if (extra > 0 and wsum > 0) else 0
            for cid, _t, _m, wt in self.fit_spec:
                w = nat.get(cid, 40)
                if left > 0 and wt > 0:
                    share = int(extra * wt / wsum)
                    if cid == weighted[-1]:
                        share = left           # остача від округлення -- останньому стовпцю з вагою, щоб сума ширин дорівнювала ширині таблиці
                    share = min(share, left)
                    w += share
                    left -= share
                self.column(cid, width=w, minwidth=min(w, nat.get(cid, w)), stretch=False)
        except tk.TclError:
            pass
        finally:
            self._fit_busy = False

    def total_width(self):
        return sum(int(self.column(c, "width")) for c, *_ in self.fit_spec)

    def clipped_columns(self):
        """Стовпці, ширші за які не можна було б зробити нижче обрізання, але що вужчі за потрібне. Порожній список = нічого не обрізано."""
        req = self.required()
        return [c for c, w in req.items() if int(self.column(c, "width")) < w]


class TolScrollbar(gt.AutoScrollbar):
    """Горизонтальна смуга таблиці: ховається, коли вміст лишається за межею менш як на пів відсотка (округлення ширин не повинно викликати смугу)."""

    def set(self, lo, hi):
        if float(lo) <= 0.0 and float(hi) >= 0.995:
            self.grid_remove()
            ttk.Scrollbar.set(self, lo, hi)
        else:
            super().set(lo, hi)


class FitTable(ttk.Frame):
    """Рамка: таблиця + вертикальна й горизонтальна смуги (з'являються лише коли потрібні). tree -- FitTreeview."""

    def __init__(self, parent, columns, height=10, selectmode="browse", **kw):
        super().__init__(parent)
        self.tree = FitTreeview(self, columns, height=height, selectmode=selectmode, **kw)
        self.vs = gt.AutoScrollbar(self, orient="vertical", command=self.tree.yview)
        self.hs = TolScrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.vs.set, xscrollcommand=self.hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vs.grid(row=0, column=1, sticky="ns")
        self.hs.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        # Запит розміру рамки задаємо самі: інакше Treeview запитує суму ПОТОЧНИХ ширин стовпців (а вони розтягнуті під попередню ширину), і після
        # звуження області (з'явилась вертикальна смуга прокрутки) запит лишається завеликим -> зайва горизонтальна смуга всієї панелі.
        self.grid_propagate(False)
        self.tree.on_refit = self._request
        self._request()

    def _request(self):
        try:
            w = sum(self.tree.natural.values()) + 4
            h = self.tree.winfo_reqheight() + (self.hs.winfo_reqheight() if self.h_scroll_visible() else 0)
            if int(self.cget("width")) != w or int(self.cget("height")) != h:
                self.configure(width=w, height=h)
        except tk.TclError:
            pass

    def min_width(self):
        """Ширина, за якої жоден стовпець не потребує горизонтальної прокрутки."""
        return sum(self.tree.required().values()) + 4

    def h_scroll_visible(self):
        return bool(self.hs.winfo_manager()) and self.hs.winfo_ismapped()


# --- межі між частинами ------------------------------------------------------------------------------------------------------------

class PaneMemory:
    """Обгортка однієї межі ttk.PanedWindow: мінімум для обох частин, подвійне клацання по межі = типове положення, запам'ятовування в налаштуваннях.

    name        -- ключ у налаштуваннях («sash_<name>»);
    min_first / min_second -- функції, що дають мінімальну ширину (висоту) частин у px;
    default     -- функція: типове положення межі (px від початку вікна PanedWindow)."""

    def __init__(self, pane, name, default, min_first=None, min_second=None, index=0, shell=None, request=False):
        self.pane, self.name, self.index = pane, name, index
        self.default = default
        self.min_first = min_first or (lambda: 80)
        self.min_second = min_second or (lambda: 80)
        self.shell = shell
        self.request = request               # True: сама межа «просить» у батька ширину не менше суми мінімумів (тоді вузьке вікно дає прокрутку, а не стискання)
        self.restored = False
        self._busy = False
        self.vertical = str(pane.cget("orient")) == "vertical"
        pane.bind("<Double-Button-1>", self._on_double, add="+")
        pane.bind("<B1-Motion>", lambda _e: self._soon(), add="+")
        pane.bind("<ButtonRelease-1>", lambda _e: self._soon(), add="+")
        pane.bind("<Configure>", lambda _e: self._soon(), add="+")

    # --- розміри ---

    def total(self):
        return self.pane.winfo_height() if self.vertical else self.pane.winfo_width()

    def position(self):
        return int(self.pane.sashpos(self.index))

    def clamp(self, pos):
        tot = self.total()
        if tot <= 1:
            return int(pos)
        lo = self.min_first()
        hi = tot - self.min_second() - gt.SASH
        if hi < lo:                      # місця на обидві мінімуми нема: віддаємо перевагу першій частині
            return int(lo)
        return int(max(lo, min(hi, pos)))

    def set(self, pos):
        """Поставити межу (з урахуванням мінімумів). Захист від повторного входу: зміна положення породжує <Configure>, а той -- спробу відновлення."""
        if self._busy:
            return
        self._busy = True
        try:
            self.pane.sashpos(self.index, self.clamp(pos))
        except tk.TclError:
            pass
        finally:
            self._busy = False

    def _soon(self):
        try:
            self.pane.after_idle(self._enforce)
        except tk.TclError:
            pass

    def update_request(self):
        """Запитана ширина (висота) = сума мінімумів обох частин: ScrollFrame, у якому лежить панель, побачить її й дасть смугу прокрутки."""
        if not self.request:
            return
        try:
            need = int(self.min_first() + self.min_second() + gt.SASH)
            self.pane.configure(**({"height": need} if self.vertical else {"width": need}))
        except tk.TclError:
            pass

    def _enforce(self):
        try:
            self.update_request()
            if self.total() <= 1:
                return
            cur = self.position()
            fixed = self.clamp(cur)
            if fixed != cur:
                self.pane.sashpos(self.index, fixed)
        except tk.TclError:
            pass

    # --- подвійне клацання ---

    def hit(self, x, y):
        try:
            pos = self.position()
        except tk.TclError:
            return False
        v = y if self.vertical else x
        return pos - 3 <= v <= pos + gt.SASH + 3

    def _on_double(self, e):
        if self.hit(e.x, e.y):
            self.reset()
            return "break"
        return None

    def reset(self):
        self.set(self.default())

    # --- налаштування ---

    def key(self):
        return "sash_" + self.name

    def restore(self, settings):
        """Положення з налаштувань (або типове). Викликати, коли панель уже показано (до цього вона має розмір 1x1)."""
        try:
            if self.total() <= 1:
                return False
            if self._busy:
                return False
            self.restored = True               # ДО set(): повторні події під час самої установки вже не повертаються сюди
            saved = settings.get(self.key()) if settings is not None else None
            self.set(saved if isinstance(saved, int) and saved > 0 else self.default())
            return True
        except tk.TclError:
            return False

    def store(self, settings):
        if settings is None or not self.restored:
            return
        try:
            if self.total() > 1:
                settings.set(self.key(), self.position())
        except tk.TclError:
            pass
