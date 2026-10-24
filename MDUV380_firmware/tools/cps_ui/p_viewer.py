# -*- coding: utf-8 -*-
"""Розділ «Кодплаг → Перегляд кодплага»: таблиці ДОКУМЕНТА (контакти, групи RX, зони, канали, APRS, DTMF) і редактор контактів.
Власних кнопок відкриття немає: кодплаг відкривається панеллю документа над розділами (з рації або з бекапу). Без відкритого документа --
підказка. Правки контактів лягають у документ; у рацію пишеться лише дією «Записати в рацію»."""
from tkinter import ttk

import codeplug_viewer_gui
import gui_theme as gt

from .common import output_dir
from .panel import HINT_NO_DOC, Panel


class ViewerPanel(Panel):
    key = "viewer"
    title = "Перегляд кодплага"
    scroll = False          # таблиці мають власну прокрутку й розтягуються на всю область
    doc_panel = True

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.viewer = None
        ttk.Label(self, text="Перегляд кодплага", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.placeholder = ttk.Label(self.body, text=HINT_NO_DOC, foreground=gt.P["muted"], wraplength=600, justify="left")
        self.placeholder.pack(anchor="nw", pady=8)
        self.on_document_changed()

    def on_document_changed(self):
        d = self.doc
        if d is None:
            self._drop_viewer()
            self.placeholder.pack(anchor="nw", pady=8)
            return
        self.placeholder.pack_forget()
        if self.viewer is None or self.viewer.document is not d:
            self._drop_viewer()
            self.viewer = codeplug_viewer_gui.CodeplugViewer(self.body, d, output_dir(), is_busy=lambda: self.shell.busy)
            self.viewer.pack(fill="both", expand=True)
        else:
            self.viewer.refresh()

    def _drop_viewer(self):
        if self.viewer is not None:
            try:
                self.viewer.destroy()
            except Exception:  # noqa: BLE001
                pass
            self.viewer = None

    def after_refresh(self):
        if self.viewer is not None:
            self.viewer.set_editable(not self.shell.busy)
