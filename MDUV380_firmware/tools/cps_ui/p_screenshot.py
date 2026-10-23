# -*- coding: utf-8 -*-
"""Розділ «Рація → Знімок екрана» (R24, лише читання). Перенесено з gui_flasher.py без змін логіки."""
from tkinter import ttk

import tkinter as tk

import cps_link as cps

from .common import output_dir
from .panel import Panel


class ScreenshotPanel(Panel):
    key = "shot"
    title = "Знімок екрана"
    radio_only = True       # увесь розділ потребує рації: у дереві показується приглушеним, коли рації нема

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.header("Знімок екрана", "Знімає те, що зараз на екрані рації, і зберігає в теці MD-UV390UKR (у домашній теці). "
                                     "Лише читання: у рацію нічого не записується. Рація має бути у звичайному режимі (не в DFU).")
        self.shot_diag_var = tk.BooleanVar(value=False)
        self.shot_button = ttk.Button(self, text="Знімок екрана", command=self._on_screenshot_clicked)
        self.shot_button.pack(anchor="w", padx=12, pady=6)
        self.reg(self.shot_button)
        ttk.Checkbutton(self, text="діагностика (обидва порядки байтів + сирий буфер)", variable=self.shot_diag_var).pack(anchor="w", padx=12)

    def _on_screenshot_clicked(self):
        diag = bool(self.shot_diag_var.get())
        self.shell.run_task(lambda: self._screenshot_worker(diag), "Знімаю екран рації...")

    def _screenshot_worker(self, diagnostic):
        ser = cps.open_radio()
        try:
            # ВАЖЛИВО: команду "C",0 (екран CPS) тут НЕ надсилаємо -- знімок мав би показати поточний екран рації, а не екран CPS.
            paths = cps.take_screenshot(cps.CpsLink(ser), output_dir(), diagnostic=diagnostic,
                                        progress=lambda d, t: self.shell.post_progress(int(100.0 * d / t)))
        finally:
            ser.close()
        for p in paths:
            print("Збережено: {}".format(p))
        return paths
