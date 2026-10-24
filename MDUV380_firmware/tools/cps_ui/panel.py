# -*- coding: utf-8 -*-
"""Базовий клас панелі правої області. Панель знає тільки про `shell` (вікно CpsApp) і його сервіси:
  shell.log(text), shell.set_status(text, kind), shell.run_task(...), shell.post(fn), shell.confirm_from_worker(...),
  shell.conn (RadioConnection), shell.busy, shell.show(key).
Дії, що потребують рації або розблокованого запису, реєструються через reg(): оболонка сама вимикає їх із поясненням причини
(P1.7: недоступне не зникає, а лишається видимим і вимкненим)."""
from tkinter import ttk

import cps_restore as cps_rest
import gui_theme as gt

BUSY_REASON = "Триває інша операція -- зачекай, поки вона завершиться."


class Panel(ttk.Frame):
    key = ""
    title = ""
    radio_only = False     # True -- увесь розділ потребує рації (у дереві приглушується, коли рації нема)
    scroll = True          # False -- панель сама розтягується на всю область і має власну прокрутку (таблиці)

    def __init__(self, parent, shell):
        super().__init__(parent)
        self.shell = shell
        self._regs = []        # [(віджет, потребує рації, потребує розблокованого запису)]
        self.note = None

    # --- побудова ---

    def header(self, text, hint=None):
        """Заголовок панелі + необов'язковий пояснювальний рядок."""
        ttk.Label(self, text=text, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        if hint:
            ttk.Label(self, text=hint, wraplength=640, justify="left", foreground=gt.P["muted"]).pack(anchor="w", padx=12, pady=(0, 6))
        self.make_note()     # причина вимкнення -- одразу під заголовком, а не внизу довгої панелі

    def make_note(self, parent=None):
        """Рядок із причиною, чому дії вимкнені. Створюється один раз; текст оновлює refresh_state()."""
        if self.note is not None:
            return self.note
        self.note = ttk.Label(parent or self, text="", wraplength=640, justify="left", foreground=gt.P["warn"])
        self.note.pack(anchor="w", padx=12, pady=(0, 4))
        return self.note

    def reg(self, widget, radio=True, write=False):
        """Зареєструвати кнопку: потребує знайденої рації (radio) і/або розблокованого запису (write)."""
        self._regs.append((widget, radio, write))
        return widget

    # --- стан ---

    def disabled_reason(self, radio=True, write=False):
        """Текст причини вимкнення або None, якщо дія доступна."""
        if self.shell.busy:
            return BUSY_REASON
        if radio and not self.shell.conn.found:
            return self.shell.conn.reason()
        if write and not cps_rest.RESTORE_UNLOCKED:
            return cps_rest.LOCKED_CAPTION
        return None

    def refresh_state(self):
        shown = None
        for w, radio, write in self._regs:
            reason = self.disabled_reason(radio, write)
            try:
                w.config(state="disabled" if reason else "normal")
            except Exception:  # noqa: BLE001 -- віджет міг бути знищений (напр. перегляд кодплага)
                continue
            if reason and shown is None and reason != cps_rest.LOCKED_CAPTION:
                shown = reason
        if self.note is not None:
            self.note.config(text=shown or "")
        self.after_refresh()

    def after_refresh(self):
        """Місце для додаткових оновлень у нащадках (підписи, що залежать від стану)."""

    def on_show(self):
        """Викликається щоразу, коли розділ обрано в дереві."""
        self.refresh_state()


class ScrollFrame(ttk.Frame):
    """Область з вертикальною прокруткою для високих панелей (коли вікно маленьке). Панель кладеться в `inner`."""

    def __init__(self, parent):
        super().__init__(parent)
        import tkinter as tk
        self.canvas = tk.Canvas(self, bg=gt.P["bg"], highlightthickness=0, borderwidth=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", self._bind_wheel)
            w.bind("<Leave>", self._unbind_wheel)

    def _on_inner(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

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
