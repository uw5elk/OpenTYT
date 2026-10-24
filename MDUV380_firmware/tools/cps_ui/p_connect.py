# -*- coding: utf-8 -*-
"""Розділ «Рація → Підключення і стан»: порт, модель, версія прошивки, заряд; кнопка «Оновити» (повторний пошук)."""
from tkinter import ttk

import gui_theme as gt

from .connection import BATTERY_NOTE
from .panel import Panel


class ConnectionPanel(Panel):
    key = "conn"
    title = "Підключення і стан"

    def __init__(self, parent, shell):
        super().__init__(parent, shell)
        self.header("Підключення і стан",
                    "Рацію шукаємо один раз при запуску й ще раз за кнопкою «Оновити» (а також після дій, що перезавантажують рацію). "
                    "Порт відкривається тільки на час операції.")
        box = ttk.LabelFrame(self, text="Рація")
        box.pack(fill="x", padx=12, pady=6)
        self.vals = {}
        for i, (k, label) in enumerate((("state", "Стан"), ("port", "Порт"), ("model", "Модель"), ("fw", "Версія прошивки"),
                                        ("built", "Збірка прошивки"), ("battery", "Заряд акумулятора"))):
            ttk.Label(box, text=label + ":", width=20).grid(row=i, column=0, sticky="w", padx=(8, 4), pady=2)
            v = ttk.Label(box, text="", wraplength=420, justify="left")
            v.grid(row=i, column=1, sticky="w", padx=4, pady=2)
            self.vals[k] = v
        box.columnconfigure(1, weight=1)
        # значення переносяться за шириною рамки (на вузькому вікні довгий рядок про заряд не вилазить за край)
        box.bind("<Configure>", lambda e: [v.config(wraplength=max(160, e.width - 200)) for v in self.vals.values()])
        self.refresh_btn = ttk.Button(self, text="Оновити", command=lambda: self.shell.refresh_connection(force=True))
        self.refresh_btn.pack(anchor="w", padx=12, pady=6)
        self.reg(self.refresh_btn, radio=False)
        ttk.Label(self, wraplength=640, justify="left", foreground=gt.P["muted"],
                  text=("Режим DFU (прошивка) тут не показується: рація в завантажувачі не відповідає CPS-протоколу, "
                        "тому розділ «Прошивка» доступний і без знайденої рації.")).pack(anchor="w", padx=12, pady=(0, 6))
        self.extra = ttk.Label(self, text="", wraplength=640, justify="left", foreground=gt.P["warn"])
        self.extra.pack(anchor="w", padx=12, pady=2)

    def after_refresh(self):
        c = self.shell.conn
        v = self.vals
        if c.state == "unknown":
            v["state"].config(text="Шукаю рацію...", foreground=gt.P["info"])
        elif c.state == "found":
            v["state"].config(text="Рацію знайдено", foreground=gt.P["ok"])
        else:
            v["state"].config(text="Рацію не знайдено", foreground=gt.P["err"])
        v["port"].config(text=c.port or "—")
        if c.info:
            v["model"].config(text=c.model_name() + ("" if c.is_expected_model() else " -- це НЕ MD-UV390: функції цього CPS розраховані на MDUV380"),
                              foreground=gt.P["fg"] if c.is_expected_model() else gt.P["warn"])
            v["fw"].config(text=c.info.get("gitRevision") or "—")
            v["built"].config(text=c.info.get("buildDateTime") or "—")
        else:
            for k in ("model", "fw", "built"):
                v[k].config(text="—", foreground=gt.P["fg"])
        v["battery"].config(text=BATTERY_NOTE, foreground=gt.P["muted"])
        self.extra.config(text=("Порт знайдено, але версію прочитати не вдалося: %s" % c.error) if (c.found and c.error and not c.info)
                          else (c.error if (c.state == "absent" and c.error) else ""))
