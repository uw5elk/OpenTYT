# -*- coding: utf-8 -*-
"""R76: проста підказка під кнопкою (працює й на вимкнених ttk-кнопках: Enter/Leave до них доходять). Текст бере з функції щоразу наново."""
import tkinter as tk

import gui_theme as gt


class Tooltip:
    DELAY_MS = 400

    def __init__(self, widget, text_fn):
        self.w = widget
        self.text_fn = text_fn
        self._tip = None
        self._after = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self._leave, add="+")

    def _enter(self, _e=None):
        self._cancel()
        self._after = self.w.after(self.DELAY_MS, self._show)

    def _cancel(self):
        if self._after is not None:
            try:
                self.w.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self):
        self._after = None
        try:
            text = self.text_fn()
            if not text or self._tip is not None:
                return
            tip = tk.Toplevel(self.w)
            tip.wm_overrideredirect(True)
            tip.configure(bg=gt.P["border"])
            tk.Label(tip, text=text, justify="left", wraplength=360, bg=gt.P["surface"], fg=gt.P["fg"], padx=8, pady=4).pack(padx=1, pady=1)
            tip.wm_geometry("+%d+%d" % (self.w.winfo_rootx() + 8, self.w.winfo_rooty() + self.w.winfo_height() + 4))
            self._tip = tip
        except tk.TclError:
            self._tip = None

    def _leave(self, _e=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
