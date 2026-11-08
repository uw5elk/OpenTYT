# -*- coding: utf-8 -*-
"""Лічильники обміну з рацією (R71 етап 1): скільки запитів читання, скільки КіБ, скільки пакетів запису 'X' і -- головне -- скільки разів ми дочекалися ТАЙМ-АУТУ порту.

Навіщо: секунди на справжній рації досі ніхто не міряв (cps-doc-result, r32-result). Тут лише ЛІЧИЛЬНИКИ, що не залежать від швидкості рації, й обгортка `measure()`, яка
міряє справжній годинник ПК (time.monotonic) довкола будь-якої операції й друкує один рядок у журнал. Лічильники глобальні (одна рація, один процес) і не впливають
на поведінку: це просто цілі числа, які збільшують читачі/писарі.

    with io_stats.measure("Читаю ключі AES"):
        ...
    -> «Вимір «Читаю ключі AES»: 3.4 с; читання: 2 запитів, 1.5 КіБ, очікувань тайм-ауту порту: 0; запис: 0 пакетів 'X'.»
"""
import time
from contextlib import contextmanager

KEYS = ("read_req", "read_bytes", "x_packets", "port_timeouts", "short_reads", "sector_erases", "c_cmds")
COUNTERS = {k: 0 for k in KEYS}


def add(key, n=1):
    COUNTERS[key] = COUNTERS.get(key, 0) + n


def snapshot():
    return dict(COUNTERS)


def delta(before, after=None):
    after = after if after is not None else COUNTERS
    return {k: after.get(k, 0) - before.get(k, 0) for k in KEYS}


def describe(d, seconds):
    return ("%.1f с; читання: %d запитів, %.1f КіБ, очікувань тайм-ауту порту: %d; запис: %d пакетів 'X', стирань секторів: %d"
            % (seconds, d["read_req"], d["read_bytes"] / 1024.0, d["port_timeouts"] + d["short_reads"], d["x_packets"], d.get("sector_erases", 0)))


@contextmanager
def measure(name, clock=time.monotonic, out=print):
    """Міряє операцію справжнім годинником ПК і друкує підсумок навіть при помилці."""
    b = snapshot()
    t0 = clock()
    try:
        yield
    finally:
        try:
            out("Вимір «%s»: %s." % (name, describe(delta(b), clock() - t0)))
        except Exception:  # noqa: BLE001 -- друк підсумку не повинен ховати справжню помилку операції
            pass
