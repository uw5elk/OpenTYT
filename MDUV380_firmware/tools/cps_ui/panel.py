# -*- coding: utf-8 -*-
"""Базовий клас панелі правої області. Панель знає тільки про `shell` (вікно CpsApp) і його сервіси:
  shell.log(text), shell.set_status(text, kind), shell.run_task(...), shell.post(fn), shell.confirm_from_worker(...),
  shell.conn (RadioConnection), shell.busy, shell.show(key), shell.doc (відкритий документ кодплага або None).
Дії, що потребують рації або розблокованого запису, реєструються через reg(): оболонка сама вимикає їх із поясненням причини
(P1.7: недоступне не зникає, а лишається видимим і вимкненим)."""
import time
from tkinter import ttk

import cps_restore as cps_rest
import gui_theme as gt

WRAP_MIN = 300         # підписи з wraplength від цього значення -- довгі пояснення, що переносяться за шириною вікна
WRAP_FLOOR = 240       # найменша ширина переносу, коли вікно вужче
WRAP_MARGIN = 8        # запас праворуч: рамки й відступи контейнерів не повинні виштовхувати підпис за видиму область (інакше смуги вмикаються по колу)
FLIP_LIMIT = 8         # скільки разів за 2 с смуги можуть змінити стан, перш ніж їх зафіксують увімкненими
SCROLL_SLACK = 2       # вміст ширший за область менш як на стільки px смуги не вмикає

BUSY_REASON = "Триває інша операція -- зачекай, поки вона завершиться."
HINT_NO_DOC = "Відкрийте кодплаг з рації або з бекапу"


class Panel(ttk.Frame):
    key = ""
    title = ""
    radio_only = False     # True -- увесь розділ потребує рації (у дереві приглушується, коли рації нема)
    scroll = True          # False -- панель сама розтягується на всю область і має власну прокрутку (таблиці)
    doc_panel = False      # True -- панель працює з ДОКУМЕНТОМ кодплага (shell.doc); без документа показує підказку HINT_NO_DOC

    def __init__(self, parent, shell):
        super().__init__(parent)
        self.shell = shell
        self._regs = []        # [(віджет, потребує рації, потребує розблокованого запису, потребує відкритого документа)]
        self.note = None
        self._wrap_labels = None
        self._doc_stale = False
        self._host = getattr(parent, "scroll_host", None)       # ScrollFrame, у який вкладено панель (або None)
        if self._host is not None:
            self._host.width_listeners.append(self.rewrap)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, e):
        """Довгі підписи переносяться за шириною видимої області (а не за фіксованими 640 px посеред порожнечі)."""
        if e.widget is self:
            self.rewrap()

    def avail_width(self):
        """Ширина ВИДИМОЇ області панелі: у прокручуваній -- ширина вікна прокрутки (а не розтягнутого вмісту), інакше -- сама панель."""
        if self._host is not None:
            return self._host.avail_width()
        return max(1, self.winfo_width())

    def on_avail(self, avail):
        """Змінилась ВИДИМА ширина панелі: місце для нащадків, що перемикають розкладку (одна колонка / дві) за доступною, а не розтягнутою шириною."""

    def _nested_host(self, w):
        """Найближча власна область прокрутки підпису (не та, що належить самій панелі) або None; за потреби підписується на зміни її ширини."""
        a = w.master
        while a is not None and a is not self:
            host = getattr(a, "scroll_host", None)
            if host is not None and host is not self._host:
                seen = self.__dict__.setdefault("_nested_seen", set())
                if id(host) not in seen:
                    seen.add(id(host))
                    host.width_listeners.append(lambda _w: self.rewrap())
                return host
            a = a.master
        return None

    def wrap_labels(self):
        """Довгі пояснення панелі (wraplength >= WRAP_MIN); підпис із `_fixed_wrap = True` не чіпаємо."""
        out, stack = [], list(self.winfo_children())
        while stack:
            w = stack.pop()
            stack.extend(w.winfo_children())
            if w.winfo_class() == "TLabel" and not getattr(w, "_fixed_wrap", False):
                try:
                    if int(str(w.cget("wraplength"))) >= WRAP_MIN:
                        out.append(w)
                except (ValueError, tk_error()):
                    pass
        return out

    def rewrap(self, avail=None):
        """Підігнати wraplength довгих підписів під видиму ширину мінус відступ підпису від лівого краю панелі."""
        avail = avail or self.avail_width()
        if avail <= 1:
            return
        self.on_avail(avail)
        left = self.winfo_rootx()
        for w in self.wrap_labels():
            try:
                if w.winfo_ismapped():
                    indent = max(0, w.winfo_rootx() - left)
                    w._wrap_indent = indent
                else:
                    # відступ непоказаного підпису виміряти не можна: беремо останній відомий (або типовий) і уточнюємо, щойно підпис з'явиться
                    indent = getattr(w, "_wrap_indent", 2 * gt.PAD)
                    if not getattr(w, "_wrap_map_bound", False):
                        w._wrap_map_bound = True
                        w.bind("<Map>", lambda _e: self.after_idle(self.rewrap), add="+")
                room = avail
                nested = self._nested_host(w)
                if nested is not None:
                    # підпис усередині власної області прокрутки (форма редактора): межа -- видимий правий край ТІЄЇ області, а не всієї панелі
                    room = min(avail, max(1, nested.winfo_rootx() - left + nested.avail_width()))
                w.config(wraplength=max(WRAP_FLOOR, room - indent - 2 * gt.PAD - WRAP_MARGIN))
            except tk_error():
                pass          # віджет міг бути знищений
        if self._host is not None:
            self._host.after_idle(self._host.refit)         # перенос змінив потрібну висоту -- не чекати опитування

    # --- побудова ---

    def header(self, text, hint=None, purpose=None):
        """Заголовок панелі + необов'язковий пояснювальний рядок. purpose (R33 Q4) -- один рядок «Для чого цей розділ» (не плутати схожі розділи)."""
        ttk.Label(self, text=text, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        if purpose:
            ttk.Label(self, text="Для чого: " + purpose, wraplength=640, justify="left").pack(anchor="w", padx=12, pady=(0, 4))
        if hint:
            ttk.Label(self, text=hint, wraplength=640, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 6))
        self.make_note()     # причина вимкнення -- одразу під заголовком, а не внизу довгої панелі

    def make_note(self, parent=None):
        """Рядок із причиною, чому дії вимкнені. Створюється один раз; текст оновлює refresh_state(). Коли причини нема, рядок
        не займає місця (ховається разом зі своїм контейнером)."""
        if self.note is not None:
            return self.note
        self._note_box = ttk.Frame(parent or self)
        self._note_box.pack(anchor="w", fill="x")
        self.note = ttk.Label(self._note_box, text="", wraplength=640, justify="left", foreground=gt.P["warn"])
        return self.note

    def _set_note(self, text):
        if self.note is None:
            return
        self.note.config(text=text)
        if text:
            self.note.pack(anchor="w", padx=12, pady=(0, 4))
        else:
            self.note.pack_forget()

    def reg(self, widget, radio=True, write=False, doc=False):
        """Зареєструвати кнопку: потребує знайденої рації (radio), розблокованого запису (write) і/або відкритого документа (doc)."""
        self._regs.append((widget, radio, write, doc))
        return widget

    # --- стан ---

    def disabled_reason(self, radio=True, write=False, doc=False):
        """Текст причини вимкнення або None, якщо дія доступна."""
        if self.shell.busy:
            return BUSY_REASON
        if doc and self.shell.doc is None:
            return HINT_NO_DOC
        if radio and not self.shell.conn.found:
            return self.shell.conn.reason()
        if write and not cps_rest.RESTORE_UNLOCKED:
            return cps_rest.LOCKED_CAPTION
        return None

    def refresh_state(self):
        shown = None
        for w, radio, write, need_doc in self._regs:
            reason = self.disabled_reason(radio, write, need_doc)
            try:
                w.config(state="disabled" if reason else "normal")
            except Exception:  # noqa: BLE001 -- віджет міг бути знищений (напр. перегляд кодплага)
                continue
            if reason and shown is None and reason not in (cps_rest.LOCKED_CAPTION, HINT_NO_DOC):
                shown = reason
        self._set_note(shown or "")
        self.after_refresh()

    def after_refresh(self):
        """Місце для додаткових оновлень у нащадках (підписи, що залежать від стану)."""

    @property
    def doc(self):
        return self.shell.doc

    def doc_event(self, visible):
        """Документ змінився (відкрито, закрито, відредаговано). Невидима панель оновиться при показі, видима -- одразу."""
        if visible:
            self._doc_stale = False
            self.on_document_changed()
            self.refresh_state()
        else:
            self._doc_stale = True

    def on_document_changed(self):
        """Місце для нащадків, що працюють з документом: перемалювати вміст за shell.doc."""

    def on_show(self):
        """Викликається щоразу, коли розділ обрано в дереві."""
        if self._doc_stale:
            self._doc_stale = False
            self.on_document_changed()
        self.refresh_state()
        self.after_idle(self.rewrap)


def tk_error():
    import tkinter
    return tkinter.TclError


class ScrollFrame(ttk.Frame):
    """Область з прокруткою для панелей. Вміст займає всю ширину й, якщо коротший за область, усю висоту (форми й таблиці можуть розтягуватись).
    Якщо вміст вищий -- з'являється вертикальна смуга; якщо ширший за мінімум, якого вимагають його віджети, -- горизонтальна (R36 B1: текст
    не обрізається, а прокручується). Панель кладеться в `inner`; `avail_width()` -- ширина ВИДИМОЇ області, від неї рахується перенос підписів."""

    def __init__(self, parent):
        super().__init__(parent)
        import tkinter as tk
        self.canvas = tk.Canvas(self, bg=gt.P["bg"], highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self._bar_shown = False          # смуги з'являються лише тоді, коли вміст більший за область (CPS-fix2 S2)
        self._hbar_shown = False
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self.inner.scroll_host = self
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.width_listeners = []        # функції(avail_width): викликаються, коли змінюється ширина видимої області
        self._last_avail = None
        self._flips = []                 # моменти змін стану смуг (для запобіжника)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.bind("<Configure>", self._on_canvas)
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", self._bind_wheel)
            w.bind("<Leave>", self._unbind_wheel)
        self._seen_req = (0, 0)
        self._poll_id = self.after(200, self._poll_req)

    def destroy(self):
        try:
            self.after_cancel(self._poll_id)          # інакше після знищення лишається «invalid command name ..._poll_req»
        except Exception:  # noqa: BLE001
            pass
        super().destroy()

    def avail_width(self):
        """Ширина видимої області без вертикальної смуги (за станом смуг, який щойно вирішив _fit)."""
        W = self.winfo_width()
        if W <= 1:
            return max(1, self.canvas.winfo_width())
        return max(1, W - (max(1, self.vbar.winfo_reqwidth()) if self._bar_shown else 0))

    def _poll_req(self):
        """Розмір, який ЗАПИТУЄ вміст, змінюється й без зміни розміру вікна (відкрито документ, зник підпис, з'явився рядок). Вікно-елемент canvas
        має явний розмір, тож <Configure> від такої зміни не приходить -- перевіряємо запит ~5 разів на секунду (дешево: одне порівняння)."""
        try:
            req = (self.inner.winfo_reqwidth(), self.inner.winfo_reqheight())
            if req != self._seen_req:
                self._seen_req = req
                self._fit()
            self._poll_id = self.after(200, self._poll_req)
        except tk_error():
            pass          # вікно знищено

    def _fit(self):
        """Вміст займає всю видиму ширину (але не менше потрібної) і всю висоту (але не менше потрібної); зайве -- прокрутка.
        Чи потрібні смуги, вирішується за ПОВНОЮ областю рамки (а не за полотном, яке саме звужується смугами) -- інакше смуги вмикають одна одну по колу
        (вертикальна звужує полотно -> потрібна горизонтальна -> вона зменшує висоту -> потрібна вертикальна ...)."""
        W, H = self.winfo_width(), self.winfo_height()
        rh, rw = self.inner.winfo_reqheight(), self.inner.winfo_reqwidth()
        bw = max(1, self.vbar.winfo_reqwidth())
        bh = max(1, self.hbar.winfo_reqheight())
        if W <= 1 or H <= 1:
            need_v = need_h = False
        else:
            need_v, need_h = rh > H, rw > W + SCROLL_SLACK
            if need_v and not need_h:
                need_h = rw > W - bw + SCROLL_SLACK
            elif need_h and not need_v:
                need_v = rh > H - bh
        # запобіжник від вічного миготіння смуг на нестандартних шрифтах: коли стан смуг змінюється надто часто, залишаємо смуги ввімкненими
        now = time.monotonic()
        if (need_v, need_h) != (self._bar_shown, self._hbar_shown):
            self._flips = [t for t in self._flips if now - t < 2.0] + [now]
            if len(self._flips) > FLIP_LIMIT:
                need_v, need_h = need_v or self._bar_shown, need_h or self._hbar_shown
        if need_v != self._bar_shown:
            self._bar_shown = need_v
            if need_v:
                self.vbar.pack(side="right", fill="y", before=self.canvas)
            else:
                self.vbar.pack_forget()
                self.canvas.yview_moveto(0)
        if need_h != self._hbar_shown:
            self._hbar_shown = need_h
            if need_h:
                self.hbar.pack(side="bottom", fill="x", before=self.canvas)
            else:
                self.hbar.pack_forget()
                self.canvas.xview_moveto(0)
        w = W - (bw if need_v else 0) if W > 1 else self.canvas.winfo_width()
        h = H - (bh if need_h else 0) if H > 1 else self.canvas.winfo_height()
        iw, ih = max(w, rw), max(h, rh)
        self.canvas.itemconfigure(self._win, width=iw, height=ih)
        self.canvas.configure(scrollregion=(0, 0, iw, ih))
        if w != self._last_avail and w > 1:
            self._last_avail = w
            for fn in list(self.width_listeners):
                try:
                    fn(w)
                except Exception:  # noqa: BLE001 -- слухач міг належати знищеній панелі
                    pass

    def refit(self):
        try:
            self._fit()
        except tk_error():
            pass

    def h_scroll_active(self):
        return self._hbar_shown

    def v_scroll_active(self):
        return self._bar_shown

    def _on_inner(self, _e):
        self._fit()

    def _on_canvas(self, _e):
        self._fit()

    def _bind_wheel(self, _e):
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Shift-MouseWheel>", self._hwheel)
        self.canvas.bind_all("<Button-4>", self._wheel)
        self.canvas.bind_all("<Button-5>", self._wheel)

    def _unbind_wheel(self, _e):
        for ev in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(ev)

    def _wheel(self, e):
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height():
            return
        if getattr(e, "num", 0) == 4:
            step = -1
        elif getattr(e, "num", 0) == 5:
            step = 1
        else:
            step = -1 if e.delta > 0 else 1
        self.canvas.yview_scroll(step * 2, "units")

    def _hwheel(self, e):
        if not self._hbar_shown:
            return
        self.canvas.xview_scroll((-1 if e.delta > 0 else 1) * 2, "units")
        return "break"
