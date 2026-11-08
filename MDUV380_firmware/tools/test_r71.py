#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R71 (хост-перевірки; ТІЛЬКИ ЛІЧИЛЬНИКИ -- на підставній рації секунди нічого не означають).

1  вимір (етап 1): io_stats, обгортка measure() із підставним годинником, підключення до run_task, лічильники в читачах/писарях;
   сценарії r71_scenarios.py дають числа запитів/КіБ/очікувань тайм-ауту для кожної операції.
Запуск: python3 tools/test_r71.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import io_stats                    # noqa: E402
import aes_key_store as aks        # noqa: E402
import r71_scenarios as sc         # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("ПРОВАЛ: " + msg)


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def table():
    return {name: d for name, d in sc.table()}


def test_measure():
    lines = []
    t = iter([100.0, 103.4])
    b = io_stats.snapshot()
    with io_stats.measure("Читаю ключі AES", clock=lambda: next(t), out=lines.append):
        io_stats.add("read_req", 2)
        io_stats.add("read_bytes", 1536)
    check(len(lines) == 1 and "Читаю ключі AES" in lines[0] and "3.4 с" in lines[0] and "2 запитів" in lines[0] and "1.5 КіБ" in lines[0], "measure: рядок журналу: %r" % lines)
    check(io_stats.delta(b)["read_req"] == 2, "delta рахує різницю")
    out = []
    try:
        with io_stats.measure("збій", clock=lambda: 0.0, out=out.append):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    check(len(out) == 1, "measure друкує підсумок і при помилці")
    app = read(HERE, "cps_ui", "app.py")
    check("io_stats.measure(status_text" in app and "if quiet:" in app, "run_task міряє кожну не фонову операцію")


def test_counters():
    env = sc.Env()
    try:
        b = io_stats.snapshot()
        aks.flash_read(env.radio, 0x20000, 12)
        d = io_stats.delta(b)
        check(d["read_req"] == 1 and d["read_bytes"] == 12, "flash_read рахує запит і байти: %r" % d)
    finally:
        env.close()


def test_fast_reader():
    """2.1: aks.flash_read -- тонка обгортка швидкого читача (довжина з заголовка відповіді), без очікувань тайм-ауту."""
    t = table()
    for name in ("AES: «Оновити слоти» (15 записів)", "RCTL: прочитати", "бікон/шумодав: прочитати"):
        d = t[name]
        check(d["port_timeouts"] + d["short_reads"] == 0, "%s: очікувань тайм-ауту у читанні 0, а є %r" % (name, d))
    check(t["AES: «Оновити слоти» (15 записів)"]["read_req"] == 15, "до 2.2 «Оновити слоти» = 15 запитів (дані: %r)" % t["AES: «Оновити слоти» (15 записів)"])
    src = read(HERE, "aes_key_store.py")
    i = src.index("def flash_read(")
    body = src[i:i + 900]
    check("time.sleep" not in body and "ser.read(" not in body, "flash_read не спить і не читає сирий порт")


def main():
    test_measure()
    test_counters()
    test_fast_reader()
    if FAILS:
        print("test_r71: ПРОВАЛІВ %d" % len(FAILS))
        sys.exit(1)
    print("test_r71: усе гаразд")


if __name__ == "__main__":
    main()
