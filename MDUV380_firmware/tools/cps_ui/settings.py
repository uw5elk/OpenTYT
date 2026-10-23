# -*- coding: utf-8 -*-
"""Прості налаштування оболонки: розмір вікна, останній розділ дерева, чи розгорнутий журнал, десятковий знак CSV.

Файл лежить ПОРУЧ З ПРОГРАМОЮ (для .exe -- у теці самого .exe; з джерела -- у tools/). Якщо туди писати не можна (наприклад,
.exe у «Program Files»), використовується файл у домашній теці. Помилки читання/запису ніколи не заважають роботі: без
налаштувань програма просто відкривається зі стандартними значеннями.
"""
import json
import os
import sys
from pathlib import Path

FILE_NAME = "tyt_md_uv390ukr_ui.json"


def _candidates():
    env = os.environ.get("TYT_CPS_SETTINGS")
    if env:
        return [env]
    if getattr(sys, "frozen", False):
        near = os.path.dirname(os.path.abspath(sys.executable))
    else:
        near = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [os.path.join(near, FILE_NAME), str(Path.home() / ("." + FILE_NAME))]


class Settings:
    def __init__(self, path=None):
        self.data = {}
        self.path = path
        self.load()

    def load(self):
        paths = [self.path] if self.path else _candidates()
        for p in paths:
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    self.data = d
                    self.path = p
                    return
            except (OSError, ValueError):
                continue
        if not self.path:
            self.path = paths[0]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        """True, якщо записано. Спершу -- поруч із програмою, при відмові -- у домашній теці."""
        paths = [self.path] if os.environ.get("TYT_CPS_SETTINGS") else [self.path] + [c for c in _candidates() if c != self.path]
        for p in paths:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=1)
                self.path = p
                return True
            except OSError:
                continue
        return False
