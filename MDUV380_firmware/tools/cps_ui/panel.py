# -*- coding: utf-8 -*-
"""Базовий клас панелі правої області. Панель знає тільки про `shell` (вікно CpsApp) і його сервіси:
  shell.log(text), shell.set_status(text, kind), shell.run_task(...), shell.post(fn), shell.confirm_from_worker(...),
  shell.conn (RadioConnection), shell.busy, shell.show(key), shell.doc (відкритий документ кодплага або None).
Дії, що потребують рації або розблокованого запису, реєструються через reg(): оболонка сама вимикає їх із поясненням причини
(P1.7: недоступне не зникає, а лишається видимим і вимкненим)."""
from tkinter import ttk

import cps_restore as cps_rest
import gui_theme as gt

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
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, e):
        """Довгі підписи переносяться за шириною панелі (а не за фіксованими 600 px посеред порожнечі)."""
        if e.widget is not self:
            return
        if self._wrap_labels is None:
            self._wrap_labels = []
            stack = list(self.winfo_children())
            while stack:
                w = stack.pop()
                stack.extend(w.winfo_children())
                if w.winfo_class() == "TLabel":
                    try:
                        if int(str(w.cget("wraplength"))) >= 500:       # лише довгі пояснення; вузькі підписи таблиць не чіпаємо
                            self._wrap_labels.append(w)
                    except (ValueError, Exception):  # noqa: BLE001
                        pass
        wl = max(320, e.width - 64)
        for w in self._wrap_labels:
            try:
                w.config(wraplength=wl)
            except Exception:  # noqa: BLE001 -- віджет міг бути знищений
                pass

    # --- побудова ---

    def header(self, text, hint=None):
        """Заголовок панелі + необов'язковий пояснювальний рядок."""
        ttk.Label(self, text=text, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
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


def tk_error():
    import tkinter
    return tkinter.TclError


class ScrollFrame(ttk.Frame):
    """Область з вертикальною прокруткою для високих панелей (коли вікно маленьке). Панель кладеться в `inner`."""

    def __init__(self, parent):
        super().__init__(parent)
        import tkinter as tk
        self.canvas = tk.Canvas(self, bg=gt.P["bg"], highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self._bar_shown = False          # смуга з'являється лише тоді, коли вміст вищий за область (CPS-fix2 S2)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", self._bind_wheel)
            w.bind("<Leave>", self._unbind_wheel)
        self._seen_req = 0
        self._poll_id = self.after(200, self._poll_req)

    def _poll_req(self):
        """Висота, яку ЗАПИТУЄ вміст, змінюється й без зміни розміру вікна (відкрито документ, зникла підказка, з'явився рядок). Вікно-елемент canvas
        має явну висоту, тож <Configure> від такої зміни не приходить -- перевіряємо запит ~5 разів на секунду (дешево: одне порівняння)."""
        try:
            req = self.inner.winfo_reqheight()
            if req != self._seen_req:
                self._seen_req = req
                self._fit()
            self._poll_id = self.after(200, self._poll_req)
        except tk_error():
            pass          # вікно знищено

    def _fit(self):
        """Вміст займає всю ширину й, якщо коротший за область, усю висоту (тоді форми можуть розтягуватись); якщо вищий -- прокрутка."""
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        need = self.inner.winfo_reqheight() > h > 1
        if need != self._bar_shown:
            self._bar_shown = need
            if need:
                self.vbar.pack(side="right", fill="y", before=self.canvas)
            else:
                self.vbar.pack_forget()
                self.canvas.yview_moveto(0)
        self.canvas.itemconfigure(self._win, width=w, height=max(h, self.inner.winfo_reqheight()))
        self.canvas.configure(scrollregion=(0, 0, w, max(h, self.inner.winfo_reqheight())))

    def _on_inner(self, _e):
        self._fit()

    def _on_canvas(self, _e):
        self._fit()

    def _bind_wheel(self, _e):
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", self._wheel)
        self.canvas.bind_all("<Button-5>", self._wheel)

    def _unbind_wheel(self, _e):
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
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
