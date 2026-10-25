# -*- coding: utf-8 -*-
"""Час і обсяг по фазах довгої операції з рацією (R32 T2.1).

Навіщо: запис документа складається з кількох довгих кроків (свіже читання рації, страхова копія, запис секторів, перечитування для
звірки). Раніше скільки триває кожен -- ніхто не знав. Тепер кожна фаза міряється: секунди, скільки запитів читання й скільки КіБ
віддала рація (лічильники `CpsLink.stats`), і одним рядком іде в журнал та в підсумок (`phases`).

Використання:
    ph = Phases(link, clock)
    with ph.phase("страхова копія") as rec:
        ...
        rec["note"] = "11 секторів"        # необов'язково
    log(ph.summary())
"""
import time
from contextlib import contextmanager


class Phases:
    def __init__(self, link=None, clock=time.time):
        self.link = link
        self.clock = clock
        self.items = []

    def _stats(self):
        st = getattr(self.link, "stats", None)
        if not isinstance(st, dict):
            return 0, 0
        return st.get("requests", 0), st.get("bytes", 0)

    @contextmanager
    def phase(self, name):
        rec = {"name": name, "seconds": 0.0, "requests": 0, "bytes": 0, "note": ""}
        r0, b0 = self._stats()
        t0 = self.clock()
        try:
            yield rec
        finally:
            r1, b1 = self._stats()
            rec["seconds"] = round(self.clock() - t0, 2)
            rec["requests"] = r1 - r0
            rec["bytes"] = b1 - b0
            self.items.append(rec)

    def total_seconds(self):
        return round(sum(i["seconds"] for i in self.items), 2)

    @staticmethod
    def _one(i):
        parts = ["%.1f с" % i["seconds"]]
        if i["requests"]:
            parts.append("%d запитів, %.1f КіБ" % (i["requests"], i["bytes"] / 1024.0))
        if i["note"]:
            parts.append(i["note"])
        return "%s: %s" % (i["name"], ", ".join(parts))

    def summary(self, title="Час за фазами"):
        if not self.items:
            return ""
        return title + " -- " + "; ".join(self._one(i) for i in self.items) + "; разом %.1f с." % self.total_seconds()

    def as_list(self):
        return [dict(i) for i in self.items]
